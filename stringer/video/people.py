"""Step 3b: a portrait name in the script becomes a portrait drawn ahead of time (settled Nov 26, decision 7).

The list lives with the photos, in paths.PRIVATE/video_assets/people/people.json:

    {"version": "people-1", "people": [
       {"name": "Volodymyr Zelenskyy", "aliases": ["Zelensky", "Volodymyr Zelensky"],
        "file": "zelenskyy.png", "photo": "https://commons.wikimedia.org/...", "license": "CC BY 4.0",
        "author": "…", "approved": true}]}

Only entries Jan approved are used. A person who isn't on the list, or whose file is missing, gets no
portrait (the beat keeps its other picture, or none).
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

from .. import paths
from .places import norm

FOLDER = paths.PRIVATE / "video_assets" / "people"


@functools.lru_cache(maxsize=4)
def _load(folder: str) -> dict[str, dict]:
    f = Path(folder) / "people.json"
    if not f.exists():
        return {}
    out = {}
    for p in json.loads(f.read_text(encoding="utf-8")).get("people", []):
        if not p.get("approved") or not (Path(folder) / p.get("file", "")).is_file():
            continue
        for n in [p["name"]] + p.get("aliases", []):
            out.setdefault(norm(n), p)
    return out


def portrait(name: str, folder: Path | None = None) -> dict | None:
    """{"name", "file" (full path), "credit"} for an approved portrait, else None."""
    folder = Path(folder or FOLDER)
    p = _load(str(folder)).get(norm(name or ""))
    if not p:
        return None
    credit = f"Portrait of {p['name']} redrawn from a photo by {p.get('author') or 'unknown'}, {p.get('license') or ''}".strip(", ")
    return dict(name=p["name"], file=str(folder / p["file"]), credit=credit)
