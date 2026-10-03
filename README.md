# video-pipeline

Turns a folder of raw travel / off-road / camping footage into a reviewed script and a
DaVinci Resolve (free) timeline, driven by Claude with the `make-video` skill.

Phases: **ingest → review → script → (approve) → assemble → Resolve**. State lives in
`<footage folder>/_edit/`; originals are never modified and the media never leaves the NAS.

Proven on a 2-day 4WD trip: 69 clips / 172 min → 64-shot, 6:21 cut, imported into Resolve with
all clips linked; ~15 min of hand work in Resolve (apply 27 speed changes from `speeds.md`).

## Requirements (on the machine that can see the footage)
- ffmpeg / ffprobe
- python3 with numpy + Pillow

## Layout
- `scripts/ingest.py` — analyses every clip (uses DJI `.LRF` proxies) → `_edit/manifest.json` +
  timecoded contact sheets. Resumable, time-budgeted bursts.
- `prompts/review_prompt.md` — instructions for the parallel clip-review sub-agents that find the
  interesting moments → `_edit/review.json`.
- `scripts/assemble.py` — approved shot list (`_edit/script.md`) → 720p rough cut (local, disposable),
  `_edit/timeline.fcpxml` (4K originals, every shot at 1×) and `_edit/speeds.md`.
- `skills/make-video/SKILL.md` — the Claude skill that orchestrates the phases and holds the
  hard-won Resolve/sandbox facts.

## Usage
```
python3 scripts/ingest.py "/path/to/trip" --workers 4 --budget 140            # repeat until ALL DONE
python3 scripts/assemble.py "/path/to/trip" --media-root "/Volumes/Videos/travels/trip" \
    --work-dir ~/workspace/_video_work/trip --budget 100                       # repeat until ALL DONE
python3 scripts/assemble.py "/path/to/trip" --media-root ... --timeline-only  # just the FCPXML + speeds.md
```

## Resolve notes
- Import: File → Import → Timeline → `timeline.fcpxml`; type the volume (`/Volumes/Videos`) into
  the Path Name box of the folder picker. Clips link via the embedded start timecode.
- Speeds are not in the FCPXML on purpose: Resolve imports `<timeMap>` as freeze frames and its
  API cannot set clip speed. Apply them from `speeds.md` (end of timeline first, Ripple Sequence on).
