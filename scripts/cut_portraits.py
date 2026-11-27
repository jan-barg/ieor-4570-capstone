"""Cuts each approved person out of their portrait photo, for the cutout portraits (Jan, Nov 27: sticker on the
hook and headlines, the standing cutout on quotes).

    python scripts/cut_portraits.py            # -> people/cutouts/<slug>.png, and cutout + face in people.json

Runs on the Mac only: the cutting is Apple's Vision framework (scripts/cut_portraits.swift, compiled here with
swiftc). It is free and takes a few seconds for all the photos. Cloud Run only reads the finished PNGs, which
live with the photos in the private assets.

Each row of people.json gets "cutout" (file name in people/cutouts/) and "face" (the face box as fractions of the
cutout, top-left origin), which the renderer uses to keep the face clear of words and captions. A photo Vision
can't cut keeps no cutout, and its portrait falls back to the dotted badge.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stringer.video.people import FOLDER  # noqa: E402

VERSION = "people-2"
SWIFT = Path(__file__).resolve().parent / "cut_portraits.swift"


def merge(doc: dict, results: list[dict], cut_dir: str = "cutouts") -> dict:
    """people.json with each row's cutout and face box from the cutter's output lines (matched by photo file stem).
    A row with no clean result loses any old cutout, so a stale file is never used."""
    by_stem = {r["file"]: r for r in results if not r.get("error")}
    people = []
    for p in doc.get("people", []):
        row = {k: v for k, v in p.items() if k not in ("cutout", "face")}
        r = by_stem.get(Path(p.get("file", "")).stem)
        if r and r.get("face"):
            row["cutout"] = f"{cut_dir}/{r['file']}.png"
            row["face"] = [round(float(x), 3) for x in r["face"]]
        people.append(row)
    return dict(doc, version=VERSION, people=people)


def cut(photos: Path, out: Path) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "cut_portraits"
        subprocess.run(["swiftc", "-O", str(SWIFT), "-o", str(exe)], check=True, capture_output=True)
        res = subprocess.run([str(exe), str(photos), str(out)], check=True, capture_output=True, text=True)
    return [json.loads(line) for line in res.stdout.splitlines() if line.strip()]


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("cut_portraits runs on the Mac only (Apple's Vision framework).")
    f = FOLDER / "people.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    results = cut(FOLDER / "photos", FOLDER / "cutouts")
    new = merge(doc, results)
    f.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    done = sum(1 for p in new["people"] if p.get("cutout"))
    bad = [r["file"] for r in results if r.get("error") or not r.get("face")]
    print(json.dumps({"people": len(new["people"]), "cut": done, "no_cutout": bad, "version": VERSION}))


if __name__ == "__main__":
    main()
