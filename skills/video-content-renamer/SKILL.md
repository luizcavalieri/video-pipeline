---
name: video-content-renamer
description: Renames video files to meaningful, content-based snake_case names by actually looking at the footage. Use this whenever someone has a folder of videos with generic, camera-generated, or meaningless filenames — DJI_0234.MP4, GX010078.MP4, IMG_4471.MOV, VID_20260714_091200.mp4, C0012.MP4, clip_01.mkv, "movie.mov" — and wants them named after what's actually in them. Trigger on phrases like "rename my travel videos", "my GoPro clips all have useless names", "sort out the videos from my trip", "name these files based on what's in them", "organise my drone footage", "my camera named everything DJI_xxxx", or any request to group clips by day, catalogue a video folder, or make it browsable. Also use it when someone wants a written summary or index of what a folder of videos contains — it writes an index.md of per-clip descriptions alongside the footage. Do not use it for photos, for transcoding or editing video, or for renaming non-video files.
---

> **Running outside Cowork (e.g. Claude Code on your own machine)?** This skill was written for a cloud
> sandbox linked to a computer (`device_bash`, `device_request_folder_access`, `device_stage_files`,
> `device_commit_files`, `SendUserFile`). If those tools are not in your tool list, you are already on the
> user's machine: run the shell snippets directly with `DIR` set to the real folder path, look at the
> contact-sheet JPEGs with `Read` instead of staging them, write `index.md` straight into the folder,
> and skip the "cannot delete" caveats (the rename-only rule still stands).
> **macOS:** the snippets use GNU syntax (`stat -c`, `date -d`). Either `brew install coreutils` and use
> `gstat` / `gdate`, or translate to BSD (`stat -f %m`, `date -j -f`). Not yet tested outside Cowork.

# Video Content Renamer

Turn a folder of camera-vomit filenames into names a human can read six months later.

The heart of this is simple: look at each video, decide what it actually shows, propose names, get approval, rename. Everything else in this document exists to stop that simple loop from making a mess of someone's footage.

## Three rules that override everything else

**1. Never rename before the user approves the full list.** They know their trip; you don't. A name that looks great from four frames can be flatly wrong about which mountain that is. The approval gate is the whole safety mechanism.

**2. Never modify the contents of a video file.** Every change this skill makes to existing files is a `mv`. Don't rewrite containers, don't inject metadata tags, don't re-encode, don't "fix" anything inside a file — even when the user's video tooling would make it easy. A rename leaves capture timestamps, audio tracks, subtitles, and GoPro GPS telemetry untouched by construction, which means the worst possible outcome of a bug here is a wrong filename the user can change back. That property is worth more than any feature you could add by giving it up.

Writing a *new* file alongside the videos — the `index.md` in Step 7 — doesn't conflict with this. It touches nothing that already exists, and the user can delete it. That's the whole reason the descriptions live in a sidecar file instead of inside the videos.

**3. Skipping is always better than guessing or failing.** Unreadable file, exotic container, weird companion — skip it, keep going, list it at the end. A partial rename the user can resume beats a half-finished folder or a confidently wrong name.

## Where the work happens

Videos are large. Copying them into this session is slow and often impossible, so the inspection runs **on the user's own machine** via `device_bash`, and only the small contact-sheet JPEGs get staged here for viewing.

Two constraints of that environment shape the design:

- `device_bash` **cannot delete files.** `rm` fails. Nothing below needs it — renaming doesn't create anything to clean up, which is a second quiet benefit of the rename-only approach.
- It is a **Linux** VM with the user's folders mounted, even on a Mac. Use GNU syntax (`stat -c`, `date -d`), not BSD.

If `device_bash` is unavailable, the fallback is to stage videos into this session, inspect them here, and rename via `device_commit_files`. That only works for a handful of small files — say so plainly rather than starting a transfer that will time out.

## Step 1 — Find the folder

If the user named a folder, use it. If not, ask which folder holds the videos — one question, then stop. Don't guess between `~/Movies` and `~/Desktop`; a wrong guess wastes a whole round trip.

Once you have a path, call `device_request_folder_access` on **that specific folder**, with a one-line reason. Ask for the narrowest folder that does the job — requesting a home directory reads as overreach and gets declined.

## Step 2 — Check ffmpeg

```bash
echo "ffmpeg: $(command -v ffmpeg || echo MISSING)"
echo "ffprobe: $(command -v ffprobe || echo MISSING)"
```

If either is missing, stop and tell the user — reading frames is the entire basis for naming. Offer the stage-into-session fallback for a small folder.

## Step 3 — Inventory

```bash
DIR="$HOME/mnt/<folder>"
find "$DIR" -maxdepth 1 -type f \
  \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.avi' -o -iname '*.mkv' \
     -o -iname '*.m4v' -o -iname '*.mts' -o -iname '*.m2ts' -o -iname '*.wmv' \
     -o -iname '*.flv' -o -iname '*.webm' -o -iname '*.3gp' -o -iname '*.insv' \) \
  -print0 | while IFS= read -r -d '' f; do
    ct=$(ffprobe -v error -show_entries format_tags=creation_time -of default=nw=1:nk=1 "$f" 2>/dev/null | head -1)
    dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f" 2>/dev/null | head -1)
    printf '%s\t%s\t%s\t%s\t%s\n' "$f" "${ct:-NONE}" "${dur:-UNREADABLE}" "$(stat -c %Y "$f")" "$(stat -c %s "$f")"
  done
```

Read the result carefully:

- `dur=UNREADABLE` or size 0 means the file can't be opened — typically not yet downloaded from iCloud or living on a detached drive. **Skip it**, and name it explicitly in your final summary so the user can download it and ask you to continue. Don't let one of these abort the run.
- Recurse into subfolders only if the user asked; a flat `-maxdepth 1` avoids surprising them by reorganising a nested archive.

### Choosing the date for each file

Prefer the container's embedded `creation_time`, because it survives being copied between drives, synced through iCloud, or dumped off a card. Filesystem timestamps routinely get reset to the *copy* date, which would collapse an entire two-week trip into "day1".

Fall back to `mtime` only when `creation_time` is absent — common in AVI, and in MP4s that have been through some editors. If you fall back for some files, say so in the summary; it's the most likely source of a wrong day number.

`creation_time` is stored in UTC. Convert to the user's local timezone before taking the date, or clips shot in the evening will land on the wrong day.

### Day numbering

`day1` is the earliest date present in the folder, `day2` the next *calendar date that has footage*, and so on. Skip empty days — if nothing was shot on the trip's third day, the fourth day's clips are `day3_`, not `day4_`. Users read these numbers as "the Nth day I filmed", and gaps look like missing files.

## Step 4 — Contact sheets

One frame is not enough. The 3-second mark of a real video is often a lens cap, the ground, a shaky pan, or someone's thigh — and a name derived from it will be confidently wrong. Sampling across the clip gives you the arc of the shot instead of one arbitrary instant.

### How many frames

Pick the grid from the clip's duration:

| Duration | Frames | Grid |
|---|---|---|
| under ~5s | 1 | single frame at midpoint |
| 5s – 90s | 4 | 2x2 |
| 90s – 8min | 9 | 3x3 |
| over 8min | 16 | 4x4 |

The surprising part, and the reason to be generous here: **a denser grid costs the same as a sparse one.** The sheet is downscaled to fit roughly 1568px on its long edge before it's read, so a 2x2 and a 3x3 filling that same envelope carry near-identical image cost. What varies is resolution per frame, not tokens. Nine frames at 522x294 each are still comfortably readable — small signage stays legible — while four frames of a five-minute clip will simply miss most of what happened in it.

Keep the grid roughly square. A 5x2 strip fits ten frames but letterboxes each cell down to about a third of the area a 3x3 cell gets, and that's where real footage — hazy, low-contrast, textured, unlike a test pattern — starts getting misread. One extra frame is not worth that.

### Extracting

```bash
SHEETS="$HOME/.cache/vcr/sheets"; mkdir -p "$SHEETS"
f="<video path>"; base=$(basename "$f"); D=<duration>; N=<frame count>; COLS=<cols>; ROWS=<rows>
rm -f "$SHEETS"/_f*.png
for ((k=0;k<N;k++)); do
  T=$(awk -v d="$D" -v k=$k -v n=$N 'BEGIN{printf "%.3f", d*(k+0.5)/n}')
  ffmpeg -hide_banner -loglevel error -y -ss "$T" -i "$f" -frames:v 1 \
    -vf "scale=1280:-2" "$SHEETS/_f$(printf %02d $k).png"
done
ffmpeg -hide_banner -loglevel error -y -pattern_type glob -i "$SHEETS/_f*.png" \
  -filter_complex "tile=${COLS}x${ROWS}:margin=4:padding=4:color=white,scale='if(gt(iw,ih),1568,-2)':'if(gt(iw,ih),-2,1568)'" \
  -frames:v 1 -q:v 3 "$SHEETS/$base.jpg"
```

Sampling at `(k+0.5)/N` centres each frame in its slice, which avoids both the dead first moment and the trailing frames where the camera is being lowered.

`-ss` comes **before** `-i` — that's fast seek. On a multi-gigabyte file it's the difference between about a second and a full decode pass; nine frames off a 1.8GB clip take a few seconds total.

Frames read left-to-right, top-to-bottom in time order. Say so when describing a sheet — it's the only cue to which frame came first.

If a seek lands past the end and produces nothing, fall back to frame one rather than failing the file. If the tile step finds fewer PNGs than expected, tile what you have.

Write sheets to `$HOME/.cache/vcr/` — **outside** the user's folder. You can't delete them afterwards, so leaving them in their travel folder would be litter you can't sweep up.

Then stage the sheets into this session with `device_stage_files` and actually look at them. Batch them — one call for many small JPEGs, not one call each.

For an unusually long clip where nine or sixteen frames still leave you guessing, it's fine to re-sheet just that one file at higher density, or to sheet a single suspicious segment. Better one extra look than a wrong name.

## Step 5 — Propose names

Look at each sheet and write a name that would let the user find this clip in three years.

**Shape:** `dayN_<what it is>`, snake_case, lowercase, no spaces or punctuation, roughly 3–6 words after the day prefix. Long enough to be specific, short enough to read in a file list.

**Content:** aim for location, subject, and conditions or mood where the footage actually shows them.

```
day2_foggy_alpine_lake_walk
day3_summit_boardwalk_rocky_plateau
day1_harbour_ferry_departure_sunset
day5_rainforest_creek_crossing
```

Some judgement worth applying:

- **Don't invent specifics you can't see.** If you can read a sign, use the place name. If you're inferring "Iceland" from black sand, write `black_sand_beach` and let the user add the name. A wrong proper noun is worse than a generic-but-true description — it's the kind of error that survives unnoticed for years.
- **Describe the footage, not the frame.** A few stills of a still landscape with a moving figure is a walk, not a photograph.

- **Name long clips for the journey, not one scene.** A denser grid on a long clip will often show genuinely different places — forest, then ridge, then summit. Don't pick whichever frame you looked at last. If there's a clear arc, name it as one: `day3_forest_trail_to_summit`. If the dominant scene occupies most of the frames, name that and let the rest go. If it's really several unrelated segments stitched together, say so when you present the list and offer to name it broadly — `day4_mixed_trail_and_village` — since the alternative is splitting the file, which this skill deliberately doesn't do.
- **Disambiguate siblings.** Six clips of the same waterfall need `_wide`, `_closeup`, `_from_bridge` — not six variants of the same words. Same-name collisions are a real failure mode; check the whole proposed list for duplicates before presenting it, and append `_2`, `_3` only as a last resort.
- **Leave good names alone.** A file already called `sunrise_over_the_fjord.mp4` doesn't need touching. Propose a change only to fix a genuine typo or add a missing day prefix, and flag it separately so the user sees you're editing something they wrote.

Also draft a description per clip — two or three sentences, richer than the name. Nothing gets written *inside* the video, but these become the `index.md` that lands beside the footage in Step 7, so they're worth real effort. Note what's happening, where the camera is, the light and conditions, anything distinctive. Detail that won't fit in a filename belongs here rather than being discarded.

Present the list as a table: current name → proposed name → description. Group it by day. Then **stop and wait.** Do not touch a single file until the user says go. If they revise some names, apply their wording exactly — they know the trip.

## Step 6 — Rename, with companions

Cameras emit sidecar files that must travel with the video or they become orphans: `.LRF` and `.THM` (proxies and thumbnails), `.AAC` (external audio), `.SRT` and `.WAV`, `.XML` and `.CPI` (Sony/Panasonic metadata), `.GPX` (track logs).

Match by **stem**, case-insensitively, and rename every companion to the new stem, keeping its own extension:

```bash
cd "$DIR"
old="DJI_0234"; new="day2_foggy_alpine_lake_walk"
for c in "$old".*; do
  [ -e "$c" ] || continue
  ext="${c##*.}"
  mv -n -- "$c" "$new.$ext"
done
```

`-n` means never clobber an existing file. If a target name already exists, `mv` leaves it alone — check afterwards and report it rather than silently overwriting someone's footage.

Extensions keep their original case by default, which leaves you with `day2_foggy_alpine_lake_walk.MP4`. Lowercasing them reads better next to snake_case names, but it changes files the user didn't ask you to change — so offer it once alongside the name list rather than doing it unprompted.

## Step 7 — Write `index.md` into the video folder

The descriptions are the most valuable thing produced here, and a filename can only carry a few words of them. Write the full version to `index.md` **in the same folder as the videos**, so the detail lives with the footage rather than evaporating with this conversation. A filename tells the user which clip is which; the index tells them what's actually in it.

This is a standard step, not an offer. Do it after the renames succeed, without being asked.

Build the file locally, then place it with `SendUserFile` followed by `device_commit_files` to `<video folder>/index.md`. That path also gives the user a copy in the conversation.

Use this structure:

```markdown
# <Folder name> — video index

<N> clips, <first date> to <last date>. Renamed <date>.

## Day 1 — <weekday, date>

### day1_harbour_ferry_departure_sunset.mp4
*0:42 · 18:05*

Ferry pulling away from the harbour terminal in low orange light, gulls
crossing frame, the town receding on the left. Handheld from the stern deck.

*Was: DJI_0234.MP4*

### day1_...
```

What each part is doing:

- **Two or three sentences per clip**, not one line. This is the place for the detail the filename had to drop — what's happening, where the camera is, the light and weather, anything distinctive enough to jog a memory.
- **Duration and capture time** make the index usable for finding a specific moment.
- **The old filename** matters more than it looks: it's the only remaining link back to whatever the user's editing project, backup catalogue, or notes still call that clip.
- **Day headings with real dates**, since `day3` means nothing on its own a year later.

Close the file with the same exceptions you report in chat — skipped files, uncertain dates — so the index stays truthful about what it doesn't cover.

### If `index.md` already exists

Don't clobber it. Read it first.

- If it's an index this skill wrote (same heading structure), **merge**: keep existing entries, add the new clips, re-sort by day. A resumed run should end with one complete index, not two partial ones.
- If it's something the user wrote, leave it alone entirely. Write `video_index.md` instead and say which name you used and why.

## Step 8 — Summarise in the conversation

Close with prose the user can actually read, not a log dump. Group by day, give each clip's new name and a sentence on what's in it, and point at the index file for the fuller version.

Then, separately and briefly:

- files skipped because they were unreadable, **named individually**, with the note that they can download them and ask you to continue
- files whose day came from filesystem mtime rather than embedded capture time (most likely to be wrong)
- any name collisions where `mv -n` declined to act
- the leftover contact sheets in `$HOME/.cache/vcr/`, which you can't delete

## Resuming

If the user comes back after downloading missing files, don't redo the whole folder. Re-run the inventory and work only on what's still generic.

Read the existing `index.md` first — it's the record of what the last run did. It gives you the established day numbering, which you must keep anchored to the **original earliest date** rather than the earliest date among the remaining files, or the second batch will get day numbers that contradict the first. It also tells you which names are already taken, so you don't propose a duplicate.

Merge the new clips into that index rather than starting a new one.
