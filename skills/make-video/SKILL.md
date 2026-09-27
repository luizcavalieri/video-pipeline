---
name: make-video
description: Turn a folder of raw travel / off-road / camping footage (DJI Osmo, iPhone) into a reviewed script and a DaVinci Resolve-ready timeline. Use when Luiz points at a footage folder and wants a video made from it, or asks to resume a make-video job at a later phase (review, script, assemble).
---

# /make-video <folder>

Pipeline: **ingest → review → script → (Luiz approves) → assemble → Resolve**.
Each phase is its own session. State lives in `<folder>/_edit/`, so any phase can resume.
Originals are never modified — ingest only reads, and everything written goes to `_edit/`.

## Hard rules (context budget)
- Never `cat` `manifest.json`, `review.json` or a sheet into the main session. Query them with
  `python3 -c` one-liners that print summaries.
- Only sub-agents look at contact sheets. The main session sees `review.json` (a few KB).
- Scripts run on Luiz's Mac (device shell), never in the cloud workspace. Footage never leaves the NAS.
- Copy the pipeline scripts to the Mac VM's local disk before running (`$HOME/pipeline`). The NAS
  mount is lazy on writes: never run a script straight from a file just written to the NAS.
- The DJI `.LRF` files are 720p proxies; analysis always uses them. Never decode a 4K `.MP4`
  unless there is no proxy.
- The working copy of the repo is `~/workspace/video-pipeline` (connect it to edit scripts).
  Edit files there via the Mac shell; never run `git` in the sandbox (it can't delete lock
  files and leaves the repo wedged). Luiz commits and pushes from his own terminal.

## Phase 0 — setup (every session)
1. Confirm the folder is connected (`get_device_info`). If not, ask Luiz to add it.
2. `mkdir -p $HOME/pipeline` on the Mac and put `ingest.py`, `assemble.py` there:
   `git clone --depth 1 <PIPELINE_REPO_URL> $HOME/pipeline` (GitHub is reachable from the VM).
   Fallback: gzip+base64 the file through the shell. Never use device_commit_files for scripts
   (it has landed corrupted files).
3. `which ffmpeg ffprobe python3` — all three must exist. `python3 -c "import numpy, PIL"`.
4. Check what already exists: `ls <folder>/_edit/` → decide which phase to resume.

## Phase 1 — ingest (Mac, in bursts)
The Mac shell kills background processes when a call ends, so ingest runs in resumable bursts:
```
python3 $HOME/pipeline/ingest.py "<folder>" --workers 4 --budget 140 2>&1 | tail -3
```
Repeat the call until it prints `ALL DONE` (≈ 1 burst per 40 min of footage; the last bursts
finish the longest clips — drop `--budget` to 90 if a call times out). Work is saved per
2-minute segment under `_edit/parts/`, so a killed call loses at most a few seconds.
Output: `_edit/manifest.json` (~3 KB/clip), `_edit/sheets/*.jpg` (~170 KB each).
Sanity check: `error` entries, `motion` length ≈ duration, clips with no `index_desc`.
Reading the profiles: motion pegged at 9 for a whole clip = handheld shake, not action.

## Phase 2 — review (cloud, parallel sub-agents)
1. Stage all sheets to the cloud: `device_stage_files` (≤50 per call).
2. Build batches of ~8 clips. For each batch produce a compact text block from the manifest:
   `id, duration, index_desc, motion (as a string of digits), scenes, tile times`.
3. Launch one `Agent` per batch **in a single message** (concurrent). Each agent gets
   `review_prompt.md` + its batch text + the staged sheet paths to `Read`. It returns a JSON array.
4. Merge into `_edit/review.json` (write via the Mac shell, then confirm size with `wc -c`).
5. Print a one-screen summary: count by role, the `interest ≥ 4` moments with timecodes.

## Phase 3 — script (main session, small input)
Inputs: `review.json` summary + `index.md` day narrative + any brief from Luiz (target length,
song, tone). Write `_edit/script.md` with:
- **Concept** (3 lines): the arc, the hook in the first 5 s, the ending beat, tone (funny beats
  come from contrast — e.g. sheep/cow stares, the odometer rollover, rain → sun).
- **Shot list table**: `# | clip id | in | out | speed | duration on timeline | note`.
  Target 4–7 min. Driving connectors at 2–4×, never longer than 8 s on the timeline.
  Moments at 1×. Camp/cooking as breathing room between driving blocks.
- **Music**: if Luiz supplied a song, mark beat/section cue points where blocks should change.
  Otherwise suggest genre / BPM / mood for him to pick.
- **Titles/captions**: 3–6 short overlays max (place names, day markers, one-liners).
- A fenced ```json shotlist``` block mirroring the table — this is what `assemble.py` reads.
Send the script to Luiz (SendUserMessage) and STOP. He edits or approves.

## Phase 4 — assemble (Mac, after approval)
```
python3 $HOME/pipeline/assemble.py "<folder>" --script _edit/script.md [--music song.mp3]
```
Produces in `_edit/out/`:
- `roughcut_720p.mp4` — the whole cut from the LRF proxies, speed changes applied, music if
  given. Luiz watches this before opening Resolve. Built first; it's cheap.
- `timeline.fcpxml` — ordered clips with in/out points referencing the 4K originals, with
  retime attributes. Free Resolve imports these inconsistently, so `script.md` also lists every
  speed change as a table he can apply by hand (Change Clip Speed) if they don't come across.
- `connectors/*.mp4` — optional `--bake`: sped-up connectors rendered from the 4K originals so
  the timeline needs no retime at all. 4K HEVC decode in the Mac VM is slow with no GPU, so
  this runs in the same burst/resume pattern as ingest and can take a while.
Send the rough cut path and a 3-line "what to check" note.

## Phase 5 — Resolve (Luiz)
File → Import → Timeline → `timeline.fcpxml`. Media is relinked by path (NAS paths must match).
Colour, transitions, titles, audio ducking are done by hand. If a title list was scripted,
paste it from `script.md`.

## Files in the pipeline repo
- `ingest.py` — analysis → manifest + sheets (done, tested on Turon River 2026-08).
- `review_prompt.md` — sub-agent instructions (done).
- `assemble.py` — shotlist → FCPXML + baked connectors + rough cut (Phase 4; build on first use).
