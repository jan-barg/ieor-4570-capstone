"""Pick the articles the later steps read, for every frozen story (stringer/pick.py).

    python -m scripts.pick_articles              # all frozen stories, 10 each
    python -m scripts.pick_articles --n 20       # another cap, to compare on the eval

Free and offline: it only reads articles.jsonl and gather.json. Writes picked.json (or
picked_<n>.json for a cap other than 10) next to them; the full pool stays as it was."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from stringer import paths, pick
from stringer.gather import store


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=pick.N)
    ap.add_argument("--only", nargs="*", help="event short ids")
    a = ap.parse_args(argv)
    name = "picked.json" if a.n == pick.N else f"picked_{a.n}.json"
    total, flagged = Counter(), 0
    for d in sorted(p for p in paths.STORIES.iterdir() if (p / "gather.json").exists()):
        if a.only and d.name[:8] not in a.only:
            continue
        meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
        arts = store.read_articles(d.name)
        r = pick.pick(arts, meta["lens"], n=a.n)
        r["event"] = meta["event"]["id"]
        (d / name).write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        g = Counter(row["group"] for row in r["rows"])
        total.update(g)
        flagged += bool(r["flags"])
        print(f"{d.name[:8]} {meta['lens']['kind']:5} {len(arts):3} -> {len(r['picked']):2}  "
              f"{dict(sorted(g.items()))}  {'; '.join(r['flags'])}")
    print(f"wrote {name}; picks by group {dict(total)}; {flagged} stories flagged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
