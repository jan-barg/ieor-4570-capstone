"""Step 3b: a portrait name in the script becomes a portrait drawn ahead of time (settled Nov 26, decision 7).

The list lives with the photos, in paths.PRIVATE/video_assets/people/people.json:

    {"version": "people-2", "people": [
       {"name": "Volodymyr Zelenskyy", "aliases": ["Zelensky", "Volodymyr Zelensky"],
        "file": "photos/zelenskyy.jpg", "photo": "https://commons.wikimedia.org/...", "license": "CC BY 4.0",
        "author": "…", "approved": true,
        "cutout": "cutouts/zelenskyy.png", "face": [0.3, 0.12, 0.7, 0.5]}]}

Only entries Jan approved are used. A person who isn't on the list, or whose file is missing, gets no
portrait (the beat keeps its other picture, or none). "cutout" and "face" come from scripts/cut_portraits.py
(people-2, Nov 27): the person cut out of the photo, and where their face is in it. With them the portrait is
drawn as a cutout (a sticker, or standing on a quote); without them, as the older dotted badge.
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
    """{"name", "file" (full path), "credit"} for an approved portrait, else None. With a cutout on disk, also
    "cutout" (full path) and "face" (its face box, fractions of the cutout, top-left origin)."""
    folder = Path(folder or FOLDER)
    p = _load(str(folder)).get(norm(name or ""))
    if not p:
        return None
    face = p.get("face")
    cut = folder / p["cutout"] if p.get("cutout") else None
    has_cut = bool(cut and cut.is_file() and isinstance(face, list) and len(face) == 4)
    how = "cut out from" if has_cut else "redrawn from"
    author, lic = p.get("author") or "unknown", p.get("license") or ""
    credit = f"Portrait of {p['name']} {how} a photo by {author}, {lic}".strip(", ")
    out = dict(name=p["name"], file=str(folder / p["file"]), credit=credit, photo=dict(how=how, author=author, license=lic))
    if has_cut:
        out.update(cutout=str(cut), face=[float(x) for x in face])
    return out


def credits(portraits: list[dict]) -> list[str]:
    """The sources card's portrait credits, one line per photo source: "Portraits of A and B cut out from photos by
    The White House, Public domain". A portrait without its photo details keeps its own credit."""
    groups: dict[tuple, set] = {}
    out = set()
    for p in portraits:
        ph = p.get("photo")
        if ph:
            groups.setdefault((ph["how"], ph["author"], ph["license"]), set()).add(p["name"])
        elif p.get("credit"):
            out.add(p["credit"])
    for (how, author, lic), names in groups.items():
        ns = sorted(names)
        who = ns[0] if len(ns) == 1 else ", ".join(ns[:-1]) + " and " + ns[-1]
        photo = "a photo" if len(ns) == 1 else "photos"
        out.add(f"Portrait{'s' if len(ns) > 1 else ''} of {who} {how} {photo} by {author}, {lic}".strip(", "))
    return sorted(out)
