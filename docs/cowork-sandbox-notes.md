# Cowork / sandbox notes (optional)

Only relevant if Claude drives the pipeline from a **cloud sandbox linked to your computer**
(Claude desktop app + `device_*` tools), rather than a normal shell on the machine that holds the
footage. In Claude Code on your own machine, ignore this file. Everything here was learned the hard
way while building the pipeline; the generic `SKILL.md` assumes none of it.

## Hard rules in this mode
- Scripts run on the user's computer through the device shell, never in the cloud workspace.
  Footage never leaves its drive/NAS.
- Scripts run from the VM's local disk (`$HOME/pipeline`), never straight from a connected folder.
- The working copy of the repo is a connected folder (e.g. `~/workspace/video-pipeline`).
  **Never run `git` in the sandbox**: it leaves lock files it can't remove. The user commits and
  pushes from their own terminal.
- The main media stays on the NAS. The one sanctioned local video file is the 720p rough cut in the
  work dir (e.g. `~/workspace/_video_work/<trip>/`), a disposable preview.

## Sandbox facts
- Linux VM with ffmpeg, python3, numpy. **3-minute call limit**; background processes die when
  a call ends, so every long job runs in resumable bursts (`--budget`).
- Reads from the NAS are fast; **writes to the NAS ~0.6 MB/s**, to local disk ~35 MB/s.
- The NAS mount serves stale bytes for a few seconds after a write: `md5sum` before running a
  freshly written script.
- **`device_commit_files` caches by staged path.** Committing a changed file under a path it has
  seen before silently writes the *first* version. Copy to a new staged name (`foo_v2.py`) for every
  re-commit and verify with `md5sum` on the Mac. Fallback that always works: gzip+base64 the file
  and paste it through `device_bash`.
- Deleting in a connected folder needs `device_request_delete_permission` once per session. SMB
  leaves `.smbdelete*` tombstones + empty dirs behind; the user bins those in Finder.

## Phase overrides
**Phase 0 (setup)**
1. `get_device_info`: both the trip folder and the repo folder must be connected.
2. Copy the repo to the VM's local disk and use that copy as `$PIPELINE`:
   `cp -r $HOME/mnt/video-pipeline $HOME/pipeline`. The working copy is ahead of GitHub whenever
   there are uncommitted edits; `git clone --depth 1 <repo url> $HOME/pipeline` is the fallback.

**Phase 2 (review)**
- `device_stage_files` all contact sheets to the cloud first (≤50 per call) so sub-agents can `Read`
  them. Write the merged `review.json` via the Mac shell and confirm with `wc -c`.

**Phase 3 (script)**
- Send the script with `SendUserMessage` and STOP; the user edits or approves.

**Phase 4 (assemble)**
```
python3 $HOME/pipeline/scripts/assemble.py "<folder>" \
  --media-root "/Volumes/Videos/travels/<trip folder name>" \
  --work-dir "$HOME/mnt/workspace/_video_work/<trip folder name>" --budget 100 2>&1 | tail -4
```
Repeat until `ALL DONE` (≈ 15 shots per burst). Pass `--media-root` explicitly here: the default is the
sandbox's own path (`/sessions/...`), which Resolve can't see.

The work dir lives on the VM, which the user cannot open. `assemble.py` therefore copies the rough cut
to `<folder>/_edit/roughcut_720p.mp4` (chunked and resumable, so it survives the 3-minute call limit
over slow NAS writes). Tell the user that path. Use `--no-publish` to skip.

## Reference trip
The pipeline was proven end to end on a 2-day solo 4WD camping trip (69 clips, 172 min → 6:21
scripted cut, 7:22 final once the song set the length; 1× timeline 11:09). It found the real beats
unprompted: a rain→sun pivot, a "SHUT THE GATE MATE" sign, a cow stare, three escalating water
crossings, an odometer rollover and the finale. Both pieces-to-camera earned their place, so keep
the "CHECK AUDIO" flag.
