---
name: make-video
description: Turn a folder of raw travel / off-road / camping footage (DJI Osmo, iPhone) into a reviewed script and a DaVinci Resolve-ready timeline. Use when Luiz points at a footage folder and wants a video made from it, or asks to resume a make-video job at a later phase (review, script, assemble).
---

# /make-video <folder>

Pipeline: **ingest → review → script → (Luiz approves) → assemble → Resolve**.
Each phase is its own session. State lives in `<folder>/_edit/`, so any phase can resume.
Proven end to end on `Turon River Solo Camping - 150826` (2026-09): 69 clips, 172 min → 6:21 cut.

## Hard rules
- **Originals are never modified.** Ingest only reads; everything written goes to `_edit/`.
  The only allowed change to footage is renaming (the `video-content-renamer` skill, run first).
- **Main media stays on the NAS.** The one sanctioned local video file is the 720p rough cut in
  `~/workspace/_video_work/<trip>/` — a disposable preview. Never make the timeline depend on
  local media (no "baking" sped-up shots into local files; tried, rejected).
- Resolve is the free version: no external scripting. Everything Claude makes must be *importable*.
- Context budget: never `cat` `manifest.json`, `review.json` or a sheet into the main session;
  query them with `python3 -c` one-liners. Only sub-agents look at contact sheets.
- Scripts run on Luiz's Mac (device shell), never in the cloud workspace. Footage never leaves the NAS.
- Scripts run from the VM's local disk (`$HOME/pipeline`), never straight from a connected folder.
- The working copy of the repo is `~/workspace/video-pipeline`. Never run `git` in the sandbox
  (it leaves lock files it can't remove). Luiz commits and pushes from his own terminal.

## Mac sandbox facts
- Linux VM with ffmpeg, python3, numpy, PIL. 3-min call limit; background processes die when a
  call ends → every long job runs in resumable bursts (`--budget`).
- Reads from the NAS are fast; **writes to the NAS ~0.6 MB/s**, to local disk ~35 MB/s.
- The NAS mount serves stale bytes for a few seconds after a write: `md5sum` before running a
  freshly written script.
- **`device_commit_files` caches by staged path.** Committing a changed file under a path it has
  seen before silently writes the *first* version. Copy to a new staged name (`foo_v2.py`) for
  every re-commit and verify with `md5sum` on the Mac. Fallback that always works: gzip+base64
  the file and paste it through `device_bash`.
- Deleting in a connected folder needs `device_request_delete_permission` once per session.
  SMB leaves `.smbdelete*` tombstones + empty dirs behind; Luiz bins those in Finder.

## Phase 0 — setup (every session)
1. `get_device_info`: both the trip folder and `~/workspace/video-pipeline` must be connected.
2. `cp -r $HOME/mnt/video-pipeline $HOME/pipeline` (the working copy is ahead of GitHub whenever
   there are uncommitted edits; `git clone --depth 1 https://github.com/luizcavalieri/video-pipeline.git $HOME/pipeline` is the fallback).
3. `which ffmpeg ffprobe python3`; `python3 -c "import numpy, PIL"`.
4. `ls <folder>/_edit/` → decide which phase to resume.

## Phase 1 — ingest (Mac, in bursts)
```
python3 $HOME/pipeline/scripts/ingest.py "<folder>" --workers 4 --budget 140 2>&1 | tail -3
```
Repeat until `ALL DONE` (≈ 1 burst per 40 min of footage; drop `--budget` to 90 if a call times
out). Progress is saved per 2-min segment under `_edit/parts/`; delete `parts/` once done.
Output: `_edit/manifest.json` (~3 KB/clip), `_edit/sheets/*.jpg` (~170 KB each, timecoded tiles).
Uses the DJI `.LRF` 720p proxies; never decodes a 4K `.MP4` unless there is no proxy.
Sanity: `error` entries, `motion` length ≈ duration, clips with no `index_desc`.
Motion pegged at 9 for a whole clip = handheld shake, not action.

## Phase 2 — review (cloud, parallel sub-agents) — the step that finds the interesting bits
1. `device_stage_files` all sheets to the cloud (≤50 per call).
2. Batches of ~8 clips. For each, a compact text block from the manifest:
   `id, duration, index_desc, motion (digit string), scenes, tile times`.
3. One `Agent` per batch **in a single message** (concurrent, ~1 min wall time). Each gets
   `prompts/review_prompt.md` + its batch text + the staged sheet paths to `Read`. Returns a JSON array.
4. Merge into `_edit/review.json` (write via the Mac shell, confirm with `wc -c`).
5. Print a one-screen summary: count by role, the `interest ≥ 4` moments with timecodes.
On Turon this found the real beats unprompted (rain→sun pivot, "SHUT THE GATE MATE" sign, the
cow stare, three escalating water crossings, odometer 20,000 km, Mount Panorama finale).

## Phase 3 — script (main session, small input)
Inputs: `review.json` summary + `index.md` day narrative + Luiz's brief (target length, song, tone).
Write `_edit/script.md`:
- **Concept** (3 lines): arc, hook in the first 5 s, ending beat, tone. Funny beats come from
  contrast (animal stares, signs, the odometer, weather turning).
- **Shot list table**: `# | clip id | in | out | speed | timeline duration | note`. Target 4–7 min
  (Turon: scripted 6:21, final 7:22 — the song set the length). Driving connectors at 2–4×, ≤ 8 s
  on the timeline. Moments at 1×, 6–10 s; the set pieces (water crossings, the finale) earn 10–15 s.
  Camp/cooking as breathing room between driving blocks. Time-lapses (cooking, setup) at 8–16×.
- **Out-points must be inside the clip** — check `out ≤ duration` from the manifest. (`assemble.py`
  clamps and warns, but fix the script.)
- **Music**: if a song was given, cut to its length and mark the beat/section cue points where
  blocks change. Otherwise suggest genre / BPM / mood for Luiz to pick and expect him to stretch
  the cut to fit the song later.
- **Titles/captions**: 6–10 short overlays — opening title over the hook, place names as they
  appear (towns, valleys, roads), day markers ("NEXT MORNING"), one-liners on the gags ("JUST
  SEND IT", "MY NEXT CAMPING SITE"), a graphic for a number moment (odometer), and a closing
  title card after the cut to black. Put each in the shot's `note`. Mark pieces-to-camera as
  "CHECK AUDIO" — on Turon both earned their place.
- Name the two shots to drop first if the cut runs long.
- A fenced ```json shotlist``` block mirroring the table — what `assemble.py` reads.
Send the script (SendUserMessage) and STOP. Luiz edits or approves.

## Phase 4 — assemble (Mac, in bursts, after approval)
```
python3 $HOME/pipeline/scripts/assemble.py "<folder>" \
  --media-root "/Volumes/Videos/travels/<trip folder name>" \
  --work-dir "$HOME/mnt/workspace/_video_work/<trip folder name>" --budget 100 2>&1 | tail -4
```
Repeat until `ALL DONE` (≈ 15 shots per burst). Produces:
- `<work-dir>/roughcut_720p.mp4` — the cut from proxies, speeds applied; `--music song` mixes a
  track. Luiz watches this to judge the cut and audition music. Disposable.
- `_edit/timeline.fcpxml` — 4K originals, in/out per shot, **every shot at 1×** (see Phase 5).
- `_edit/speeds.md` — the speed changes to apply by hand, ordered end-of-timeline first.
`--timeline-only` rewrites just the last two (seconds) after a script tweak.
Sanity: rough-cut `ffprobe` duration = script total; contact-sheet the rough cut (`fps=1/8,
tile=8x6`) and look before handing over.

## Phase 5 — Resolve (Luiz, ~15 min)
1. File → Import → Timeline → `_edit/timeline.fcpxml`. In the media folder picker type
   `/Volumes/Videos` into the **Path Name** box (the picker only lists configured locations).
   All clips link because assets carry the DJI time-of-day start timecode.
2. Sequence reads the 1× length (Turon: 11:09). Apply the speeds from `speeds.md` top to bottom:
   playhead at the position → right-click the clip → Change Clip Speed → % → **Ripple Sequence**.
   Sequence then reads the script length (Turon: 6:21).
3. Music, titles, colour, ducking by hand.

Why it is done this way (don't re-litigate): Resolve imports FCPXML `<timeMap>` speed ramps as
freeze frames (absolute and clip-relative both tried); it ignores FCPXML clip names and notes;
its scripting API has no speed setter (and external scripting is Studio-only anyway); baking
sped shots to local files works but breaks the "media stays on the NAS" rule.

## Files
- Repo: `scripts/ingest.py`, `scripts/assemble.py`, `prompts/review_prompt.md`, this skill, `README.md`.
- `<trip>/_edit/`: `manifest.json`, `sheets/`, `batches/`, `review.json`, `script.md`,
  `timeline.fcpxml`, `speeds.md`. (`parts/` only while ingest is running.)
- Local, disposable: `~/workspace/_video_work/<trip>/segs/`, `roughcut_720p.mp4`.
