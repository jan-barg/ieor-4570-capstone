"""Step 5: hands the render plan and its audio to the Remotion project in render/ (settled Nov 26).

It runs `node render/render.mjs` as a child process, on the Mac and inside the Cloud Run job that makes a
video (one image holds Python, Node and headless Chrome). Prints nothing; returns render.mjs's one-line
JSON report.

    render(plan_path, run_dir, out_mp4)                  -> {"file", "frames", "seconds", "render_seconds", ...}
    render(plan_path, run_dir, out_dir, mode="stills", extra=["--frames", "10,200"])
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import paths

PROJECT = paths.CODE / "render"
TIMEOUT = 1800


class RenderError(RuntimeError):
    pass


def render(plan_path: Path, run_dir: Path, out: Path, *, mode: str = "video", extra: list[str] = ()) -> dict:
    cmd = ["node", "render.mjs", mode, str(plan_path), str(run_dir), str(out), *extra]
    r = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True, timeout=TIMEOUT)
    lines = (r.stdout or "").strip().splitlines()
    if r.returncode or not lines:
        raise RenderError((r.stderr or r.stdout or "render.mjs gave no report")[-2000:])
    return json.loads(lines[-1])
