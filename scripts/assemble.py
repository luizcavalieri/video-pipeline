#!/usr/bin/env python3
"""
assemble.py — turn the approved shot list in _edit/script.md into
  <work-dir>/roughcut_720p.mp4   (from proxies; speed changes applied; optional music) — a temporary
                                 local preview for judging the cut and auditioning music
  _edit/timeline.fcpxml          (references the 4K originals; import into DaVinci Resolve)
  _edit/speeds.md                (the speed changes to apply by hand in Resolve, end-of-timeline first)

Usage:
    python3 assemble.py "<footage folder>" --media-root "/Volumes/.../<folder>" \
        --work-dir "<fast local dir>" [--script _edit/script.md] [--music song.mp3] \
        [--workers 4] [--budget 150] [--timeline-only] [--force]

Runs in resumable bursts like ingest.py: each shot is rendered to <work-dir>/segs/NNN.mp4;
re-run until it prints "ALL DONE". --work-dir must be a fast local disk (writes to the NAS
through the desktop bridge run at well under 1 MB/s); only the small FCPXML and speeds.md go
to <folder>/_edit/. --timeline-only skips the rendering and just (re)writes those two.

--media-root is the folder's path *as Resolve will see it on the Mac* (the sandbox mounts
it elsewhere). It is only used inside the FCPXML.

Resolve (free) and the FCPXML: two things must be right for the 4K originals to link —
assets carry the file's embedded start timecode (DJI writes time-of-day), and the volume
(/Volumes/Videos) must be typed into the Path Name box of Resolve's folder picker on import.
Speed changes are NOT put in the FCPXML: Resolve imports <timeMap> as freeze frames, and
its scripting API has no speed setter, so every shot is placed at 1x over its full source
range and the speeds are applied by hand from speeds.md (~10 min for ~30 clips).
Resolve also ignores FCPXML clip names and notes, so nothing useful is put there.
--retime keeps the <timeMap> variant for other NLEs.

The shot list is the ```json shotlist``` block in script.md: a list of
{n, clip, in, out, speed, note}. `clip` is the file stem; the original is <clip>.MP4/.MOV/...
and the proxy, if any, is <clip>.LRF.
"""
import argparse, json, re, subprocess, time, html
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

VIDEO_EXT = [".MP4", ".mp4", ".MOV", ".mov", ".mkv", ".m4v"]
FPS = 25
W, H = 1280, 720


def find_original(folder, stem):
    for ext in VIDEO_EXT:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(stem)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                        "-show_format", str(path)], capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout)


def load_shotlist(script_path):
    txt = Path(script_path).read_text()
    m = re.search(r"```json shotlist\s*\n(.*?)\n```", txt, re.S)
    if not m:
        raise SystemExit("no ```json shotlist``` block in " + str(script_path))
    shots = json.loads(m.group(1))
    for s in shots:
        s["speed"] = float(s.get("speed", 1))
        s["dur"] = (s["out"] - s["in"]) / s["speed"]
    return shots


def atempo_chain(speed):
    """ffmpeg atempo accepts 0.5..2.0 per instance; chain for larger factors."""
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0"); speed /= 2.0
    while speed < 0.5:
        parts.append("atempo=0.5"); speed /= 0.5
    parts.append(f"atempo={speed:.4f}")
    return ",".join(parts)


def render_segment(src, has_audio, shot, out):
    sp = shot["speed"]
    vf = (f"setpts=PTS/{sp},scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{shot['in']:.3f}", "-t", f"{shot['out']-shot['in']:.3f}",
           "-i", str(src)]
    if has_audio:
        cmd += ["-af", atempo_chain(sp)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", f"{shot['dur']:.3f}",
            "-movflags", "+faststart", str(out)]
    tmp = out.with_suffix(".part.mp4")
    cmd[-1] = str(tmp)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        raise RuntimeError(r.stderr.strip()[-300:])
    tmp.replace(out)
    return out


def concat(seg_paths, out, music=None):
    lst = out.parent / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in seg_paths))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if music:
        cmd += ["-i", str(music), "-filter_complex",
                "[0:a]volume=0.5[a0];[1:a]volume=0.7[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    cmd.append(str(out))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:])


def fr(sec):
    """seconds → FCPXML rational time string on a 25 fps grid"""
    n = int(round(sec * FPS))
    return f"{n}/{FPS}s"


def frame_dur(fps):
    if abs(fps - round(fps)) < 0.01:
        return f"1/{int(round(fps))}s"
    return f"1001/{int(round(fps * 1001))}s"          # 29.97 → 1001/30000s


def start_timecode(info, fps):
    """Embedded start timecode (DJI writes time-of-day) → seconds. Resolve matches clips by
    timecode, so an asset declared at 0s never overlaps a file whose TC starts at 18:46:57:11."""
    tc = None
    for st in info["streams"]:
        tc = (st.get("tags") or {}).get("timecode")
        if tc:
            break
    tc = tc or (info["format"].get("tags") or {}).get("timecode")
    if not tc:
        return 0.0
    m = re.match(r"(\d+):(\d+):(\d+)[:;](\d+)", tc)
    if not m:
        return 0.0
    h, mi, se, f = map(int, m.groups())
    return h * 3600 + mi * 60 + se + f / fps


def tc(sec, fps=FPS):
    f = int(round(sec * fps))
    return f"{f//(3600*fps):02d}:{f//(60*fps)%60:02d}:{f//fps%60:02d}:{f%fps:02d}"


def write_fcpxml(shots, originals, media_root, out, name, retime=False):
    """FCPXML 1.9. One asset per source file (own frame rate + embedded start timecode), one
    asset-clip per shot, sequential offsets on the 25 fps grid.
    retime=False (default, for Resolve): every shot at 1x over its full source range.
    retime=True: speed changes as <timeMap> (Resolve imports these as freeze frames)."""
    formats, assets, ids = {}, [], {}
    def fmt_id(fps, w, h):
        key = (fps, w, h)
        if key not in formats:
            formats[key] = f"f{len(formats)+1}"
        return formats[key]
    for stem, (path, info) in originals.items():
        v = next(st for st in info["streams"] if st["codec_type"] == "video")
        num, den = v.get("r_frame_rate", "25/1").split("/")
        fps = int(num) / int(den)
        a = any(st["codec_type"] == "audio" for st in info["streams"])
        dur = float(info["format"]["duration"])
        tc0 = start_timecode(info, fps)
        aid = f"r{len(ids)+1}"
        ids[stem] = (aid, tc0)
        src = "file://" + html.escape(str(Path(media_root) / path.name))
        audio_attrs = 'hasAudio="1" audioSources="1" audioChannels="2" audioRate="48000"' if a else ""
        assets.append(f'    <asset id="{aid}" name="{html.escape(stem)}" start="{fr(tc0)}" duration="{fr(dur)}" '
                      f'hasVideo="1" {audio_attrs} format="{fmt_id(fps, v["width"], v["height"])}" src="{src}"/>')
    fmt_lines = [f'    <format id="{fid}" name="FFVideoFormat{h}p{fps:g}" frameDuration="{frame_dur(fps)}" width="{w}" height="{h}"/>'
                 for (fps, w, h), fid in formats.items()]
    clips, speeds, t = [], [], 0.0
    for s in shots:
        note = html.escape(s.get("note", "")[:120])
        aid, tc0 = ids[s["clip"]]
        sp = s["speed"]
        sped = abs(sp - 1) > 1e-6
        src_len = s["out"] - s["in"]
        body, dur = "", s["dur"]
        if sped and retime:
            body = (f'\n        <timeMap>\n          <timept time="0s" value="{fr(tc0 + s["in"])}" interp="linear"/>\n'
                    f'          <timept time="{fr(src_len/sp)}" value="{fr(tc0 + s["out"])}" interp="linear"/>\n        </timeMap>\n      ')
        elif sped:
            dur = src_len
            speeds.append((t, s["n"], s["clip"], sp, src_len))
        clips.append(f'      <asset-clip ref="{aid}" name="{html.escape(s["clip"])} #{s["n"]}" offset="{fr(t)}" '
                     f'start="{fr(tc0 + s["in"])}" duration="{fr(dur)}" tcFormat="NDF">{body}'
                     f'<note>{note}</note></asset-clip>')
        t = round((t + dur) * FPS) / FPS                 # stay on the frame grid so offsets never drift
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    <format id="r0" name="FFVideoFormat2160p25" frameDuration="1/{FPS}s" width="3840" height="2160"/>
{chr(10).join(fmt_lines)}
{chr(10).join(assets)}
  </resources>
  <library>
    <event name="{html.escape(name)}">
      <project name="{html.escape(name)} — v1">
        <sequence format="r0" duration="{fr(t)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
{chr(10).join(clips)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''
    Path(out).write_text(xml)
    if speeds:
        final = sum(s["dur"] for s in shots)
        md = [f"# Speeds to apply in Resolve — {len(speeds)} clips", "",
              "Timeline imports at 1x ({}); after these it should read {}.".format(tc(t)[3:], tc(final)[3:]),
              "Work top to bottom (end of timeline first) so ripple never moves a position you haven't done.",
              "Park the playhead at the position → the clip starting there → right-click → Change Clip Speed →",
              "type the %, tick **Ripple Sequence**. For very high factors Resolve may refuse the %: enter Duration instead.", "",
              "| Timeline pos (1x) | # | Clip | Speed | 1x length | → |", "|---|---|---|---|---|---|"]
        for o, n, clip, sp, ln in sorted(speeds, reverse=True):
            md.append(f"| {tc(o)} | {n} | {clip} | {sp*100:g}% | {ln:.0f}s | {ln/sp:.1f}s |")
        Path(out).with_name("speeds.md").write_text("\n".join(md) + "\n")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--media-root", required=True, help="folder path as seen by Resolve on the Mac")
    ap.add_argument("--script", default="_edit/script.md")
    ap.add_argument("--music", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget", type=float, default=150)
    ap.add_argument("--work-dir", default=None,
                    help="where segments + rough cut are written: a fast local disk, e.g. ~/workspace/_video_work/<trip>")
    ap.add_argument("--retime", action="store_true",
                    help="FCPXML: express speed changes as <timeMap> (not for Resolve — it imports them as "
                         "freeze frames). Default: shots at 1x + speeds.md to apply by hand.")
    ap.add_argument("--timeline-only", action="store_true",
                    help="skip segments/rough cut; only (re)write _edit/timeline.fcpxml + speeds.md")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time()

    folder = Path(a.folder).resolve()
    if not a.timeline_only and not a.work_dir:
        ap.error("--work-dir is required for rendering (a fast local disk, never the NAS)")
    out = Path(a.work_dir).resolve() if a.work_dir else None
    segs = out / "segs" if out else None
    if segs:
        segs.mkdir(parents=True, exist_ok=True)
    shots = load_shotlist(folder / a.script if not Path(a.script).is_absolute() else a.script)
    total = sum(s["dur"] for s in shots)
    print(f"{len(shots)} shots, timeline {int(total//60)}:{int(total%60):02d}", flush=True)

    originals, proxies = {}, {}
    for s in shots:
        if s["clip"] not in originals:
            o = find_original(folder, s["clip"])
            originals[s["clip"]] = (o, probe(o))
            p = o.with_suffix(".LRF")
            proxies[s["clip"]] = p if p.exists() else o
        src_dur = float(originals[s["clip"]][1]["format"]["duration"])
        if s["out"] > src_dur + 0.02:                  # shot list overshoots the file: clamp, don't fail
            print(f"  WARN #{s['n']} {s['clip']}: out {s['out']}s > clip length {src_dur:.2f}s, clamped", flush=True)
            s["out"] = round(src_dur, 2)
            s["dur"] = (s["out"] - s["in"]) / s["speed"]

    def write_timeline():
        xml_out = folder / "_edit" / "timeline.fcpxml"          # small: keep it next to the footage
        tl = write_fcpxml(shots, originals, a.media_root, xml_out, folder.name, retime=a.retime)
        print(f"timeline  → {xml_out} ({int(tl//60)}:{int(tl%60):02d} at 1x"
              f"{'' if a.retime else ', speeds in _edit/speeds.md'})")

    if a.timeline_only:
        write_timeline(); print("ALL DONE"); return

    def seg_ok(seg, s):
        """a segment counts only if it exists and its duration matches the plan (a burst that is
        killed mid-encode leaves a truncated file behind)"""
        if not seg.exists() or seg.stat().st_size < 1000:
            return False
        try:
            d = float(probe(seg)["format"].get("duration") or 0)
        except Exception:
            return False
        return abs(d - s["dur"]) < 0.5

    todo = []
    for s in shots:
        seg = segs / f"{s['n']:03d}.mp4"
        if a.force or not seg_ok(seg, s):
            todo.append((s, seg))
    print(f"{len(todo)} segments to render, budget {a.budget}s", flush=True)

    running, it, done_n, errs = {}, iter(todo), 0, 0
    with ThreadPoolExecutor(a.workers) as ex:
        while True:
            while len(running) < a.workers and time.time() - t0 < a.budget:
                nxt = next(it, None)
                if nxt is None:
                    break
                s, seg = nxt
                src = proxies[s["clip"]]
                has_audio = any(st["codec_type"] == "audio" for st in probe(src)["streams"])
                running[ex.submit(render_segment, src, has_audio, s, seg)] = s
            if not running:
                break
            dn, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for f in dn:
                s = running.pop(f)
                try:
                    f.result(); done_n += 1
                    print(f"  ok #{s['n']} {s['clip']} {s['dur']:.1f}s", flush=True)
                except Exception as e:
                    errs += 1
                    print(f"  ERR #{s['n']} {s['clip']}: {e}", flush=True)

    missing = [s for s in shots if not seg_ok(segs / f"{s['n']:03d}.mp4", s)]
    print(f"{done_n} rendered in {time.time()-t0:.0f}s, {errs} errors, {len(missing)} segments missing")
    if missing:
        print("RUN AGAIN"); return

    rc = out / "roughcut_720p.mp4"
    if a.force or not rc.exists():
        concat([segs / f"{s['n']:03d}.mp4" for s in shots], rc, a.music)

    print(f"rough cut → {rc} ({rc.stat().st_size/1e6:.0f} MB)")
    write_timeline()
    print("ALL DONE")


if __name__ == "__main__":
    main()
