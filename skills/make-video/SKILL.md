---
name: make-video
description: Turn a folder of raw travel / off-road / camping footage (DJI Osmo, iPhone) into a reviewed script and a DaVinci Resolve-ready timeline. Use when the user points at a footage folder and wants a video made from it, or asks to resume a make-video job at a later phase (review, script, assemble).
---

# /make-video <folder>

Pipeline: **ingest → review → script → (user approves) → assemble → Resolve**.
Each phase can be its own session. State lives in `<folder>/_edit/`, so any phase can resume.
Proven end to end on a 2-day solo 4WD camping trip: 69 clips, 172 min → 6:21 cut.

## Assumptions (check before starting; see README "Assumptions")
- Footage is DJI Osmo-style: `.MP4` with embedded time-of-day start timecode, optional `.LRF` proxies.
  iPhone/other clips work but have no proxy and no meaningful timecode (slower ingest, weaker linking).
- Timeline grid is **25 fps, 3840x2160** (`FPS` in `assemble.py`). Other frame rates import but
  the sequence itself is 25p.
- DaVinci Resolve **free**. The `.fcpxml` import path is the only integration.
- ffmpeg/ffprobe and Python 3 with numpy + Pillow on the machine that can see the footage.

## Hard rules
- **Originals are never modified.** Ingest only reads; everything written goes to `_edit/`.
  The only allowed change to footage is renaming (the `video-content-renamer` skill, Phase 0).
- **Footage stays where it is** (NAS, external drive, whatever). The one local video file is the
  720p rough cut in `--work-dir`, a disposable preview. Never make the timeline depend on
  local media (no "baking" sped-up shots into local files; tried, rejected).
- Resolve is the free version: no external scripting. Everything Claude makes must be *importable*.
- Context budget: never `cat` `manifest.json`, `review.json` or a sheet into the main session;
  query them with `python3 -c` one-liners. Only sub-agents look at contact sheets.
- Long jobs run in resumable bursts (`--budget N` seconds, re-run until `ALL DONE`) so they fit
  inside a tool-call time limit. Run scripts from a local disk, not over a slow network mount.

## Phase 0 — setup (every session)
1. Confirm the trip folder is reachable and note two paths:
   - the folder as this machine sees it (`<folder>`), and
   - the same folder as **Resolve** sees it (`--media-root`; defaults to the first, so only pass it
    when they differ, e.g. a mounted volume).
2. **Names check.** `ls <folder>` — if clips still carry camera names (`DJI_…`, `IMG_…`, `GX…`,
   `VID_…`, `C00…`) or there is no `index.md`, run the `video-content-renamer` skill on the
   folder first (if you don't have it, write a short `index.md` by hand, see README). Ingest keys
   everything on the clip stem and Phase 3 reads `index.md`.
3. `which ffmpeg ffprobe python3`; `python3 -c "import numpy, PIL"` (`pip install -r requirements.txt`).
4. `ls <folder>/_edit/` → decide which phase to resume.
Below, `$PIPELINE` is wherever this repo is checked out (README: set `PIPELINE` and `VIDEO_WORK_DIR` once).

> Running through a Cowork-style cloud sandbox linked to a computer (`device_*` tools)? Read
> `docs/cowork-sandbox-notes.md` first: it has the call limits, caching bugs and per-phase overrides.

## Phase 1 — ingest (in bursts)
```
python3 $PIPELINE/scripts/ingest.py "<folder>" --workers 4 --budget 140 2>&1 | tail -3
```
Repeat until `ALL DONE` (≈ 1 burst per 40 min of footage; drop `--budget` to 90 if a call times
out). Progress is saved per 2-min segment under `_edit/parts/`; delete `parts/` once done.
Output: `_edit/manifest.json` (~3 KB/clip), `_edit/sheets/*.jpg` (~170 KB each, timecoded tiles).
Uses the DJI `.LRF` 720p proxies; never decodes a 4K `.MP4` unless there is no proxy.
Sanity: `error` entries, `motion` length ≈ duration, clips with no `index_desc`.
Motion pegged at 9 for a whole clip = handheld shake, not action.

## Phase 2 — review (cloud, parallel sub-agents) — the step that finds the interesting bits
1. Make sure the contact sheets are readable by sub-agents (`_edit/sheets/*.jpg`).
2. Batches of ~8 clips. For each, a compact text block from the manifest:
   `id, duration, index_desc, motion (digit string), scenes, tile times`.
3. One `Agent` per batch **in a single message** (concurrent, ~1 min wall time). Each gets
   `prompts/review_prompt.md` + its batch text + the staged sheet paths to `Read`. Returns a JSON array.
4. Merge into `_edit/review.json` (confirm with `wc -c`).
5. Print a one-screen summary: count by role, the `interest ≥ 4` moments with timecodes.
On the reference trip this found the real beats unprompted (rain→sun pivot, "SHUT THE GATE MATE" sign, the
cow stare, three escalating water crossings, odometer 20,000 km, Mount Panorama finale).

## Phase 3 — script (main session, small input)
Inputs: `review.json` summary + `index.md` day narrative + the user's brief (target length, song, tone).
Write `_edit/script.md`:
- **Concept** (3 lines): arc, hook in the first 5 s, ending beat, tone. Funny beats come from
  contrast (animal stares, signs, the odometer, weather turning).
- **Shot list table**: `# | clip id | in | out | speed | timeline duration | note`. Target 4–7 min
  (example: scripted 6:21, final 7:22 — the song set the length). Driving connectors at 2–4×, ≤ 8 s
  on the timeline. Moments at 1×, 6–10 s; the set pieces (water crossings, the finale) earn 10–15 s.
  Camp/cooking as breathing room between driving blocks. Time-lapses (cooking, setup) at 8–16×.
- **Out-points must be inside the clip** — check `out ≤ duration` from the manifest. (`assemble.py`
  clamps and warns, but fix the script.)
- **Music**: if a song was given, cut to its length and mark the beat/section cue points where
  blocks change. Otherwise suggest genre / BPM / mood for the user to pick and expect them to stretch
  the cut to fit the song later.
- **Titles/captions**: 6–10 short overlays — opening title over the hook, place names as they
  appear (towns, valleys, roads), day markers ("NEXT MORNING"), one-liners on the gags ("JUST
  SEND IT", "MY NEXT CAMPING SITE"), a graphic for a number moment (odometer), and a closing
  title card after the cut to black. Put each in the shot's `note`. Mark pieces-to-camera as
  "CHECK AUDIO".
- Name the two shots to drop first if the cut runs long.
- A fenced ```json shotlist``` block mirroring the table — what `assemble.py` reads.
Send the script to the user and STOP. They edit or approve.

## Phase 4 — assemble (in bursts, after approval)
```
python3 $PIPELINE/scripts/assemble.py "<folder>" --budget 100 2>&1 | tail -4
```
Repeat until `ALL DONE` (≈ 15 shots per burst). Add `--media-root` / `--work-dir` only to override
`$VIDEO_WORK_DIR` or when Resolve sees the footage elsewhere. Produces:
- `<work-dir>/roughcut_720p.mp4` — the cut from proxies, speeds applied; `--music song` mixes a
  track. **Also copied to `<folder>/_edit/roughcut_720p.mp4`** (resumable; `ALL DONE` only prints once
  the copy is complete), because the work dir is often somewhere the user can't open. The user watches
  this to judge the cut and audition music. Always tell them where it is. Disposable.
- `_edit/timeline.fcpxml` — 4K originals, in/out per shot, **every shot at 1×** (see Phase 5).
- `_edit/speeds.md` — the speed changes to apply by hand, ordered end-of-timeline first.
`--timeline-only` rewrites just the last two (seconds) after a script tweak.
Sanity: rough-cut `ffprobe` duration = script total; contact-sheet the rough cut (`fps=1/8,
tile=8x6`) and look before handing over.

## Phase 5 — Resolve (user, ~15 min)
1. File → Import → Timeline → `_edit/timeline.fcpxml`. In the media folder picker type
   the volume root (e.g. `/Volumes/Videos`) into the **Path Name** box (the picker only lists configured locations).
   All clips link because assets carry the DJI time-of-day start timecode.
2. Sequence reads the 1× length (example: 11:09). Apply the speeds from `speeds.md` top to bottom:
   playhead at the position → right-click the clip → Change Clip Speed → % → **Ripple Sequence**.
   Sequence then reads the script length (example: 6:21).
3. Music, titles, colour, ducking by hand.

Why it is done this way (don't re-litigate): Resolve imports FCPXML `<timeMap>` speed ramps as
freeze frames (absolute and clip-relative both tried); it ignores FCPXML clip names and notes;
its scripting API has no speed setter (and external scripting is Studio-only anyway); baking
sped shots to local files works but breaks the "footage stays where it is" rule.

## Files
- Repo: `scripts/ingest.py`, `scripts/assemble.py`, `prompts/review_prompt.md`, this skill, `README.md`.
- `<trip>/_edit/`: `manifest.json`, `sheets/`, `batches/`, `review.json`, `script.md`,
  `timeline.fcpxml`, `speeds.md`. (`parts/` only while ingest is running.)
- Local, disposable: `<work-dir>/segs/`, `roughcut_720p.mp4`.
