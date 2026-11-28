"""Draws a model-written animation, `function draw(k, p, cues)`, in the locked box (render/anim/box.mjs), and
decides whether its frames may go into the video.

The drawing code is untrusted model output. The real lock is the box (its docstring lists every layer): its own
headless Chrome with no network and a throwaway profile, a page that may load and connect to nothing and allows
no eval, and a Web Worker (no page, no DOM) whose way out is deleted before the code loads, with a watchdog for a
frame that never ends. Only JPEG frames come out. The word check below is a first, cheap layer, not the lock: it
refuses code that names a way out (as the test harness did, Nov 27), with quoted text blanked so a kit name such as
k.prop('document') is not refused.

    rec = draw(code, out_dir, frames=270, cues={"flash": 0.3})
    rec["ok"], rec["why"]        # False and "too slow" -> the beat keeps its normal shot
"""
from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import paths

RENDER = paths.CODE / "render"
SCALE = 1.2                  # frames come out 1080 x 720: sharp on the 1080-wide video
QUALITY = 0.9
LIMIT_MS = 20.0              # a frame must draw in under 20 ms at the test window's size (900 x 600) ...
TIMEOUT_S = 150

BANNED = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|import|eval|Function|document|window|globalThis|self|"
                    r"localStorage|sessionStorage|indexedDB|navigator|location|setTimeout|setInterval|"
                    r"requestAnimationFrame|Worker|postMessage|importScripts|Date|performance|ownerDocument|defaultView)\b|"
                    r"Math\.random")


def limit_ms(scale: float = SCALE) -> float:
    """... and the box draws scale x scale as many pixels, so its bar is that much higher (28.8 ms at 1.2)."""
    return LIMIT_MS * scale * scale


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    return re.sub(r"(^|[^:\\])//[^\n]*", r"\1", code)


def strip_strings(code: str) -> str:
    """Quoted text blanked ('...', "...", and `...` without ${...}): a name inside quotes reaches nothing (the box
    allows no eval), and kit names such as k.prop('document') must not be refused."""
    code = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", code)
    code = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', code)
    return re.sub(r"`(?:\\.|[^`\\$])*`", "``", code)


def refused(code: str) -> list[str]:
    """The banned names the code uses outside comments and quotes (empty: not refused)."""
    return sorted(set(m.group(0) for m in BANNED.finditer(strip_strings(strip_comments(code or "")))))


@functools.lru_cache(maxsize=1)
def available() -> bool:
    """Whether node and the box's headless Chrome are here (the tests that start the box skip without them)."""
    if not shutil.which("node"):
        return False
    try:
        r = subprocess.run(["node", "--input-type=module", "-e",
                            "import('./anim/box.mjs').then((m) => console.log(m.browserPath() || ''))"],
                           cwd=RENDER, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(r.stdout.strip())


def run_box(job: dict, out_dir: Path, timeout_s: float = TIMEOUT_S) -> dict:
    """One run of render/anim/box.mjs: the job in, the frames in out_dir, its report back."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(job, f)
        job_path = f.name
    try:
        r = subprocess.run(["node", "anim/box.mjs", job_path, str(out_dir)], cwd=RENDER, capture_output=True, text=True,
                           timeout=timeout_s + 30)
    except subprocess.TimeoutExpired:
        return dict(status="timeout", errors=["the box did not answer in time"])
    finally:
        Path(job_path).unlink(missing_ok=True)
    lines = (r.stdout or "").strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        return dict(status="no report", errors=[(r.stderr or r.stdout or "the box printed nothing")[-400:]])


def still_share(change: list, tail: float = 0.4, eps: float = 0.0004) -> float:
    """The share of the last `tail` of frames that barely differ from the frame before (a scene standing still)."""
    xs = [c for c in (change or []) if c is not None]
    if not xs:
        return 0.0
    end = xs[int(len(xs) * (1 - tail)):]
    return round(sum(c < eps for c in end) / max(1, len(end)), 3)


def verdict(rec: dict, frames: int, scale: float = SCALE) -> tuple[bool, str]:
    """May these frames go into the video? (ok, why not). The beat keeps its normal shot when the drawing failed,
    threw on any frame, left a frame blank, is too slow, or came out short."""
    st = rec.get("status")
    if st != "drawn":
        return False, {"too slow": "too slow", "timeout": "the box ran out of time"}.get(st, f"drawing failed: {'; '.join(rec.get('errors') or [st or '?'])[:200]}")
    if rec.get("frame_errors"):
        return False, f"drawing threw an error on {rec['frame_errors']} frame(s): {(rec.get('errors') or [''])[0][:160]}"
    if rec.get("blank_frames"):
        return False, f"{rec['blank_frames']} blank frame(s)"
    if (rec.get("ms_p95") or 0) > limit_ms(scale):
        return False, f"too slow: {rec['ms_p95']} ms a frame (95th percentile; the bar is {limit_ms(scale):.1f} at this size)"
    if rec.get("frames", 0) < frames:
        return False, f"only {rec.get('frames', 0)} of {frames} frames came out"
    return True, ""


def draw(code: str, out_dir: Path, *, frames: int, cues: dict, scale: float = SCALE, quality: float = QUALITY,
         timeout_s: float = TIMEOUT_S) -> dict:
    """The static check, then the box. Returns the box's report plus ok, why, refused and still (a share)."""
    bad = refused(code)
    if bad:
        return dict(status="refused", refused=bad, ok=False, why=f"refused: names {', '.join(bad)}", frames=0)
    rec = run_box(dict(code=code, frames=int(frames), cues=cues, scale=scale, quality=quality, limit_ms=limit_ms(scale),
                       timeout_s=timeout_s), Path(out_dir), timeout_s)
    ok, why = verdict(rec, int(frames), scale)
    rec.update(ok=ok, why=why, refused=[], still=still_share(rec.get("change")))
    rec.pop("ms", None)                                   # long lists stay out of the record
    rec["change"] = None
    return rec
