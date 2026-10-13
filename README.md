# video-pipeline

Turns a folder of raw travel / off-road / camping footage into a reviewed script and a
DaVinci Resolve (free) timeline, driven by Claude with the `make-video` skill.

Phases: **ingest → review → script → (approve) → assemble → Resolve**. State lives in
`<footage folder>/_edit/`; originals are never modified and the media never moves.

Proven on a 2-day 4WD trip: 69 clips / 172 min → 64-shot, 6:21 cut, imported into Resolve with
all clips linked; ~15 min of hand work in Resolve (apply 27 speed changes from `speeds.md`).

## Install

**Claude Code** (recommended):
```
git clone <this repo> ~/video-pipeline
mkdir -p ~/.claude/skills && cp -r ~/video-pipeline/skills/make-video ~/.claude/skills/
pip install -r ~/video-pipeline/requirements.txt
```
Then tell Claude where the repo lives (the skill refers to it as `$PIPELINE`), e.g. "the pipeline is in
~/video-pipeline", and point it at a footage folder: "make a video from ~/footage/my-trip".

**claude.ai**: zip the `skills/make-video` folder and upload it under Settings → Capabilities → Skills.
The scripts need a shell with ffmpeg, so this only works if your session can run commands on the
machine that holds the footage.

## Requirements
- ffmpeg / ffprobe on PATH
- Python 3 with numpy + Pillow (`pip install -r requirements.txt`)
- DaVinci Resolve (free is fine)
- Optional: the `video-content-renamer` skill, to give camera-named clips meaningful names

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

## Layout
- `scripts/ingest.py`: analyses every clip → `_edit/manifest.json` + timecoded contact sheets.
  Resumable, time-budgeted bursts.
- `prompts/review_prompt.md`: instructions for the parallel clip-review sub-agents that find the
  interesting moments → `_edit/review.json`.
- `scripts/assemble.py`: approved shot list (`_edit/script.md`) → 720p rough cut (local,
  disposable), `_edit/timeline.fcpxml` (4K originals, every shot at 1×) and `_edit/speeds.md`.
- `skills/make-video/SKILL.md`: the Claude skill that orchestrates the phases.
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
