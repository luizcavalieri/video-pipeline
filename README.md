# video-pipeline

Turns a folder of raw travel / off-road / camping footage into a reviewed script and a
DaVinci Resolve (free) timeline, driven by Claude with the `make-video` skill.

Phases: **ingest → review → script → (approve) → assemble → Resolve**. State lives in
`<footage folder>/_edit/`; originals are never modified and the media never moves.

**It is tuned for travel / off-road / camping footage.** See "Made for travel footage" below for what to
edit if yours is different.

Proven on a 2-day 4WD trip: 69 clips / 172 min → 64-shot, 6:21 cut, imported into Resolve with
all clips linked; ~15 min of hand work in Resolve (apply 27 speed changes from `speeds.md`).

## Install

**Claude Code** (recommended):
```
git clone <this repo> ~/video-pipeline
mkdir -p ~/.claude/skills && cp -r ~/video-pipeline/skills/make-video ~/video-pipeline/skills/video-content-renamer ~/.claude/skills/
pip install -r ~/video-pipeline/requirements.txt
```
Then tell Claude where the repo lives (the skill refers to it as `$PIPELINE`), e.g. "the pipeline is in
~/video-pipeline", and point it at a footage folder: "make a video from ~/footage/my-trip".

**claude.ai**: zip each of `skills/make-video` and `skills/video-content-renamer` and upload both under
Settings → Capabilities → Skills.
The scripts need a shell with ffmpeg, so this only works if your session can run commands on the
machine that holds the footage.

## Requirements
- ffmpeg / ffprobe on PATH
- Python 3.10+ with numpy (`pip install -r requirements.txt`). Tested on 3.10.
- ffmpeg built with libx264 and AAC (the default Homebrew/apt builds). Tested on 4.4.2.
- DaVinci Resolve (free is fine). Tested with **Resolve 21**; other versions are untested, and the
  FCPXML import behaviour described under "Dead ends" may differ.
- The `video-content-renamer` skill (included in `skills/`): `make-video` runs it first when clips still
  have camera names or there is no `index.md`. It renames your footage after you approve a list, and
  writes the `index.md` that the pipeline reads. Skip it only if your clips are already well named and
  you have written `index.md` by hand (format below).
- An agent that can run **parallel sub-agents** (Claude Code's Agent tool) for the review phase. Without
  one, review runs sequentially and is much slower.

## Assumptions (read before using your own footage)
- **DJI-style clips**: `.MP4` with an embedded time-of-day start timecode. Resolve links the
  timeline to your files by that timecode. Ingest prefers the `.LRF` 720p proxy next to each clip.
  GoPro/iPhone/other cameras: no proxy (ingest decodes the full file, much slower) and timecode may
  be absent (clips start at 0), which weakens the linking. Untested.
- **25 fps, 3840x2160 sequence** (`FPS` and the `<format>` in `scripts/assemble.py`). Clips at other
  frame rates are declared with their own rate, but the sequence itself is 25p. For 24/30 fps work,
  change `FPS` and the sequence format.
- **Resolve free**: no external scripting, so everything is imported via FCPXML plus ~15 min of
  manual speed changes. With Studio you could script the speed step, but that is not implemented.
- **Naming**: every clip needs a stem that is stable and, ideally, descriptive, plus an `index.md`
  in the footage folder with a per-clip description and a day narrative. The renamer skill writes
  this. By hand, the format `ingest.py` parses is a table of `| day | time | stem | desc |` rows, or
  `### stem.MP4` headings followed by paragraphs.
- **Slow media**: if footage is on a NAS, writes there can be very slow. That is why the cut and
  work files go to `--work-dir` on a local disk and `_edit/` stays small (sheets are ~170 KB each).

## Made for travel footage: what to change for yours
This pipeline was built and tuned for one kind of video: a 4-7 minute social cut of **travel, off-road and
camping trips** (driving, water crossings, camp life, scenery, the odd animal or sign), shot on a DJI
Osmo and an iPhone. Its idea of "interesting" is baked into prompts and rules, not code. If your footage
is something else (a wedding, a sports day, a city break), edit these:

| Where | What is travel-specific | How to adapt |
|---|---|---|
| `prompts/review_prompt.md` | The **tags** (`driving`, `offroad`, `water_crossing`, `obstacle`, `camp`, `cooking`, `wildlife`, `sign`, `night`, ...), the **moment candidates** (water crossings, gates, steep bits, odometer rollovers, sign reveals), the "connector" idea (driving that only links two places, speed 3-4x), and the calibration line ("a 7-minute video uses ~40 shots from ~70 clips") | Rewrite the tag list and the candidate list for your subject, e.g. `speech`, `crowd`, `goal`, `food`, `toast`. **No script reads the tags or roles**; only Claude does, so change or extend them freely. Keep the JSON shape (`id`, `interest`, `role`, `moments[in,out,speed]`, `note`), because the later phases summarise those fields. |
| `skills/make-video/SKILL.md`, Phase 3 | The **pacing rules** (4-7 min target; driving connectors 2-4x and at most 8 s; moments 6-10 s; set pieces 10-15 s; time-lapses 8-16x), the **title/caption** advice (place names, day markers, one-liners on gags), and "funny beats come from contrast" | Replace with your own edit style: target length, how long a shot may stay on screen, which speeds are normal, what captions you want. |
| `skills/make-video/SKILL.md`, frontmatter | The `description` says "travel / off-road / camping footage" and decides **when the skill triggers** | Reword it to match your footage, or Claude may not pick the skill up. |
| `skills/make-video/SKILL.md`, Phase 1-2 | "Motion pegged at 9 for a whole clip = handheld shake, not action" assumes vehicle-mounted or walking footage | Adjust the hint if your camera work is different (tripod, gimbal, drone). |
| `scripts/ingest.py` constants | `MOTION_HI` (what counts as fast; tuned so driving reads ~9), `SCENE_SPIKE` (frame difference that counts as a cut), `SEG` (seconds per job), `SHEET_COLS`/`SHEET_MAX_TILES`/`TILE_W` (contact-sheet size), `MIN_DURATION` | Tune if the motion profile is flat or maxed out on your footage (e.g. sports needs a higher `MOTION_HI`). |
| `scripts/ingest.py` `LOCAL_TZ_OFFSET_H` | Hardcoded to **+10** (Sydney standard time) for the `created` timestamp. It ignores daylight saving. | Set your own offset. It only affects the `created` field, not the cut. |
| `scripts/assemble.py` constants | `FPS = 25`, the 3840x2160 sequence, the 1280x720 rough cut (`W, H`), the x264 settings, `VIDEO_EXT` | See Assumptions above; change for 24/30 fps work or other resolutions. |
| `skills/video-content-renamer/SKILL.md` | Names are `dayN_<what it shows>` with days counted as the Nth calendar date that has footage. That suits multi-day trips. | For a single-day event or a non-trip project, change the naming scheme (e.g. `ceremony_`, `reception_`). `ingest.py` only needs a stable clip stem and, optionally, the `index.md` descriptions. |

Not in the table but worth knowing: the phases hand work to each other only through files (`index.md` and
`manifest.json` into review, `review.json` into scripting, `script.md` into assemble), so you can swap the
logic behind a phase (a different reviewer prompt, a different scripting style) as long as it still
produces the same file.

## Layout
- `scripts/ingest.py`: analyses every clip → `_edit/manifest.json` + timecoded contact sheets.
  Resumable, time-budgeted bursts.
- `prompts/review_prompt.md`: instructions for the parallel clip-review sub-agents that find the
  interesting moments → `_edit/review.json`.
- `scripts/assemble.py`: approved shot list (`_edit/script.md`) → 720p rough cut (local,
  disposable), `_edit/timeline.fcpxml` (4K originals, every shot at 1×) and `_edit/speeds.md`.
- `skills/make-video/SKILL.md`: the Claude skill that orchestrates the phases.
- `skills/video-content-renamer/SKILL.md`: renames clips by content and writes `index.md`. Written for
  Cowork; has a preface for plain Claude Code, but that path is untested (macOS needs GNU `stat`/`date`).
- `docs/cowork-sandbox-notes.md`: optional; only if Claude runs from a cloud sandbox linked to your
  computer (call limits, file-commit caching bug, NAS quirks).

## Usage
```
python3 scripts/ingest.py "/path/to/trip" --workers 4 --budget 140            # repeat until ALL DONE
python3 scripts/assemble.py "/path/to/trip" --budget 100                      # repeat until ALL DONE
python3 scripts/assemble.py "/path/to/trip" --timeline-only                   # just FCPXML + speeds.md
```
Set these once (e.g. in `~/.zshrc`):
```
export PIPELINE=~/video-pipeline        # where this repo lives (the skill refers to it)
export VIDEO_WORK_DIR=~/video_work      # fast local disk; rough cuts go to $VIDEO_WORK_DIR/<trip name>
```
The rough cut is also copied to `<trip>/_edit/roughcut_720p.mp4` so you can watch it (the copy is
resumable; skip it with `--no-publish`). `--work-dir` overrides `VIDEO_WORK_DIR`. `--media-root` defaults to the footage folder itself; pass it
only when Resolve sees the footage at a different path (e.g. footage on a NAS that the shell mounts
elsewhere).
`--budget N` stops starting new work after N seconds so each run fits a tool-call time limit.
Re-run the same command until it prints `ALL DONE`.

## Resolve notes
- Import: File → Import → Timeline → `timeline.fcpxml`. In the folder picker, type the volume root
  (e.g. `/Volumes/Videos`) into the Path Name box, since the picker only lists configured locations.
  Clips link via the embedded start timecode.
- Speeds are not in the FCPXML on purpose (see below). Apply them from `speeds.md`, end of
  timeline first, with Ripple Sequence on.

## Dead ends (don't re-try these)
- **FCPXML `<timeMap>` speed ramps** import into Resolve as freeze frames. Tried absolute and
  clip-relative values. `assemble.py --retime` still exists but is not recommended.
- **Clip names and notes** in the FCPXML are ignored by Resolve, so titles/notes live in `script.md`
  and `speeds.md`, not in the timeline.
- **Setting clip speed through Resolve's scripting API**: there is no speed setter, and external
  scripting is Studio-only anyway.
- **Baking sped-up shots into local files** works but makes the timeline depend on local media and
  duplicates gigabytes. Rejected.
- **Declaring assets at 0s** instead of their embedded timecode: Resolve then fails to match clips
  that start at e.g. 18:46:57:11.
