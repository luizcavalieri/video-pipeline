#!/usr/bin/env python3
"""
ingest.py — analyse a folder of footage into a compact manifest + contact sheets.

Read-only on originals. Everything is written to <folder>/_edit/.

Usage:
    python3 ingest.py "<footage folder>" [--workers 4] [--budget 150] [--force]

Designed to run in short, resumable bursts (the Mac sandbox kills processes when a shell
call ends): each run does as much as fits in --budget seconds, saves partial work under
_edit/parts/, and exits. Re-run until it prints "ALL DONE".

Outputs:
    _edit/manifest.json      one entry per clip (schema below)
    _edit/sheets/<clip>.jpg  contact sheet, 6 columns, up to 24 tiles, timecode burned in
    _edit/parts/<clip>/      per-segment scratch (safe to delete once manifest is complete)

Prefers the DJI .LRF proxy (720p H.264) when one exists; falls back to the full file.

CLIP SCHEMA (manifest["clips"][i]):
    id, file, proxy, created (ISO local), duration (s), fps, width, height, has_audio
    sheet        relative path of contact sheet
    tiles        [sec, ...] timestamp of each tile, row-major (matches burned-in timecode)
    scenes       [sec, ...] big visual changes (frame-diff spikes)
    motion       [0-9 per second]  0 = parked/static, 9 = fast/bumpy
    loud         [0-9 per second]  relative loudness
    bright       mean brightness 0-255
    index_desc   "What's in it" text from index.md, if present
    mtime        original file mtime (for resume)
"""
import argparse, json, re, subprocess, time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
MIN_DURATION = 1.0
SEG = 120.0                 # seconds of footage per job
SHEET_COLS, SHEET_MAX_TILES, TILE_W = 6, 24, 320
MOTION_HI = 12.0            # grey levels/px/frame ≈ fast driving → 9
SCENE_SPIKE = 25.0          # frame diff above this = scene change
LOCAL_TZ_OFFSET_H = 10


def ffprobe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", str(path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return json.loads(r.stdout)


def parse_index(folder):
    p = folder / "index.md"
    out = {}
    if p.exists():
        for line in p.read_text(errors="ignore").splitlines():
            m = re.match(r"^\|\s*[^|]*\|\s*[^|]*\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$", line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def creation_time(fmt):
    ct = (fmt.get("tags") or {}).get("creation_time")
    if not ct:
        return None
    try:
        dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        if dt.utcoffset() == timedelta(0):
            dt = dt.astimezone(timezone(timedelta(hours=LOCAL_TZ_OFFSET_H)))
        return dt.replace(microsecond=0).isoformat()
    except ValueError:
        return ct


def q(arr, hi):
    return np.clip(np.round(np.asarray(arr, dtype=float) / hi * 9), 0, 9).astype(int).tolist()


# ---------- jobs (run in worker processes) ----------

def job_segment(src, start, length, out_json):
    """One decode of [start, start+length): motion/scene from 2 fps grey frames, loudness from PCM."""
    w, h, fps, sr = 64, 36, 2, 8000
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                        "-i", str(src), "-vf", f"fps={fps},scale={w}:{h}", "-pix_fmt", "gray",
                        "-f", "rawvideo", "-"], capture_output=True, timeout=600)
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    motion, scenes, bright = [], [], 0.0
    if n >= 2:
        fr = buf[: n * w * h].reshape(n, h, w).astype(np.int16)
        d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
        motion = [float(d[i:i + fps].mean()) for i in range(0, len(d), fps)]
        scenes = [round(start + (i + 1) / fps, 1) for i in np.where(d > SCENE_SPIKE)[0]]
        bright = float(fr.mean())
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                        "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, timeout=600)
    pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    m = pcm.size // sr
    loud = []
    if m:
        rms = np.sqrt((pcm[: m * sr].reshape(m, sr) ** 2).mean(axis=1))
        loud = (20 * np.log10(np.maximum(rms, 1e-5)) + 60).clip(0, 60).tolist()
    Path(out_json).write_text(json.dumps({"start": start, "motion": motion, "scenes": scenes,
                                          "bright": bright, "n": n, "loud": loud}))
    return out_json


def job_sheet(src, duration, out_jpg):
    n = int(min(SHEET_MAX_TILES, max(4, duration // 2)))
    step = duration / n
    rows = -(-n // SHEET_COLS)
    base = f"fps=1/{step:.4f}:round=up,scale={TILE_W}:-2,"
    txt = "drawtext=text='%{pts\\:hms}':x=6:y=6:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.5,"
    for vf in (base + txt + f"tile={SHEET_COLS}x{rows}", base + f"tile={SHEET_COLS}x{rows}"):
        r = subprocess.run(["ffmpeg", "-v", "error", "-skip_frame", "nokey", "-i", str(src), "-vf", vf,
                            "-frames:v", "1", "-q:v", "5", "-y", str(out_jpg)],
                           capture_output=True, timeout=900)
        if r.returncode == 0 and Path(out_jpg).exists():
            break
    return [round(step * i, 1) for i in range(n)]


# ---------- driver ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget", type=float, default=150, help="stop submitting new jobs after N s")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time()

    folder = Path(a.folder).resolve()
    edit = folder / "_edit"
    (edit / "sheets").mkdir(parents=True, exist_ok=True)
    (edit / "parts").mkdir(exist_ok=True)
    mpath = edit / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() and not a.force else {"clips": []}
    done = {c["id"]: c for c in manifest["clips"] if "error" not in c}
    index = parse_index(folder)

    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))
    todo = [p for p in files if p.stem not in done or done[p.stem].get("mtime") != p.stat().st_mtime]

    # Probe + plan jobs (cheap). Short clips first so partial runs still yield usable data.
    plans = []
    for p in todo:
        try:
            info = ffprobe(p)
        except Exception as e:
            done[p.stem] = {"id": p.stem, "file": p.name, "error": str(e)[:300]}
            continue
        dur = float(info["format"].get("duration") or 0)
        if dur < MIN_DURATION:
            done[p.stem] = {"id": p.stem, "file": p.name, "skipped": f"too short ({dur:.2f}s)"}
            continue
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        num, den = v.get("r_frame_rate", "25/1").split("/")
        proxy = p.with_suffix(".LRF")
        src = proxy if proxy.exists() else p
        pdir = edit / "parts" / p.stem
        pdir.mkdir(exist_ok=True)
        segs = [(s, min(SEG, dur - s)) for s in np.arange(0, dur, SEG)]
        plans.append({
            "id": p.stem, "file": p.name, "proxy": proxy.name if src is proxy else None, "src": src,
            "created": creation_time(info["format"]), "duration": round(dur, 2),
            "fps": round(int(num) / int(den), 3), "width": v["width"], "height": v["height"],
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
            "index_desc": index.get(p.stem), "mtime": p.stat().st_mtime, "pdir": pdir,
            "segs": segs, "sheet": edit / "sheets" / f"{p.stem}.jpg",
        })
    plans.sort(key=lambda x: x["duration"])

    jobs = []   # (plan, kind, callable args)
    for pl in plans:
        if not pl["sheet"].exists() or not (pl["pdir"] / "tiles.json").exists():
            jobs.append((pl, "sheet"))
        for i, (s, ln) in enumerate(pl["segs"]):
            if not (pl["pdir"] / f"seg{i:03d}.json").exists():
                jobs.append((pl, ("seg", i, s, ln)))
    print(f"{len(files)} clips, {len(plans)} incomplete, {len(jobs)} jobs pending, budget {a.budget}s", flush=True)

    def submit(ex, pl, kind):
        if kind == "sheet":
            return ex.submit(job_sheet, pl["src"], pl["duration"], pl["sheet"])
        _, i, s, ln = kind
        return ex.submit(job_segment, pl["src"], s, ln, pl["pdir"] / f"seg{i:03d}.json")

    running, finished = {}, 0
    with ProcessPoolExecutor(a.workers) as ex:
        it = iter(jobs)
        while True:
            while len(running) < a.workers and time.time() - t0 < a.budget:
                nxt = next(it, None)
                if nxt is None:
                    break
                running[submit(ex, *nxt)] = nxt
            if not running:
                break
            dn, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for f in dn:
                pl, kind = running.pop(f)
                try:
                    res = f.result()
                    if kind == "sheet":
                        (pl["pdir"] / "tiles.json").write_text(json.dumps(res))
                    finished += 1
                    print(f"  ok {pl['id']} {'sheet' if kind == 'sheet' else f'seg {kind[1]}'}", flush=True)
                except Exception as e:
                    print(f"  ERR {pl['id']} {kind}: {str(e)[:120]}", flush=True)

    # Assemble any clip whose parts are all present.
    completed = 0
    for pl in plans:
        parts = [pl["pdir"] / f"seg{i:03d}.json" for i in range(len(pl["segs"]))]
        tiles = pl["pdir"] / "tiles.json"
        if not (tiles.exists() and all(x.exists() for x in parts)):
            continue
        segs = [json.loads(x.read_text()) for x in parts]
        motion = sum((s["motion"] for s in segs), [])
        loud = sum((s["loud"] for s in segs), [])
        nfr = sum(s["n"] for s in segs) or 1
        bright = sum(s["bright"] * s["n"] for s in segs) / nfr
        done[pl["id"]] = {
            "id": pl["id"], "file": pl["file"], "proxy": pl["proxy"], "created": pl["created"],
            "duration": pl["duration"], "fps": pl["fps"], "width": pl["width"], "height": pl["height"],
            "has_audio": pl["has_audio"], "sheet": f"sheets/{pl['sheet'].name}",
            "tiles": json.loads(tiles.read_text()),
            "scenes": sum((s["scenes"] for s in segs), []),
            "motion": q(motion, MOTION_HI), "loud": q(loud, 50.0), "bright": round(bright, 1),
            "index_desc": pl["index_desc"], "mtime": pl["mtime"],
        }
        completed += 1

    manifest["clips"] = sorted(done.values(), key=lambda c: (c.get("created") or "", c["id"]))
    manifest["folder"] = str(folder)
    manifest["generated"] = datetime.now().replace(microsecond=0).isoformat()
    mpath.write_text(json.dumps(manifest, indent=1))
    ok = [c for c in manifest["clips"] if "error" not in c and "skipped" not in c]
    remaining = len(plans) - completed
    print(f"{finished} jobs done in {time.time()-t0:.0f}s; {len(ok)} clips complete, "
          f"{sum(c['duration'] for c in ok)/60:.1f} min of footage; {remaining} clips still incomplete")
    print("ALL DONE" if remaining == 0 else "RUN AGAIN")


if __name__ == "__main__":
    main()
