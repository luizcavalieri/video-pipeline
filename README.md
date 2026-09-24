# video-pipeline

Turns a folder of raw travel / off-road / camping footage into a reviewed script and a
DaVinci Resolve-ready timeline, driven by Claude with the `make-video` skill.

Phases: **ingest → review → script → (approve) → assemble → Resolve**. State lives in
`<footage folder>/_edit/`; originals are never modified.

## Requirements (on the machine that can see the footage)
- ffmpeg / ffprobe
- python3 with numpy

## Layout
- `scripts/ingest.py` — analyses every clip (prefers DJI `.LRF` proxies) → `manifest.json` + contact sheets. Runs in resumable time-budgeted bursts.
- `scripts/assemble.py` — shot list → rough cut + FCPXML (coming).
- `prompts/review_prompt.md` — instructions for the clip-review sub-agents.
- `skills/make-video/SKILL.md` — the Claude skill that orchestrates the phases.

## Usage
```
python3 scripts/ingest.py "/path/to/trip" --workers 4 --budget 140   # repeat until ALL DONE
```
