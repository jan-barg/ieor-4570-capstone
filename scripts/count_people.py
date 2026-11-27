"""Counts the people the news names most, to choose module 8's portraits (Jan, Nov 26: "look through more
articles to see what people are named the most").

    python scripts/count_people.py              # -> stringer_private/video_assets/people/candidates.json
    python scripts/count_people.py --shortlist  # counts the hand-picked people in people/shortlist.json

Two sources, each counted by how many separate items name the person (not how many times):
  articles   every article text behind the frozen stories (stringer_private/frozen/article_cache)
  events     every distinct event in the live feed snapshots (titles and summaries)

A name is two or three capitalised words. Names made of place words or organisation words are dropped,
and a person's surname alone ("Trump said") counts for the full name when the surname belongs to only one
candidate. This is a first sort; a person still has to be picked by hand and approved by Jan.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stringer import paths  # noqa: E402
from stringer.video import places  # noqa: E402

OUT = paths.PRIVATE / "video_assets" / "people" / "candidates.json"
SHORTLIST = paths.PRIVATE / "video_assets" / "people" / "shortlist.json"
WORD = r"(?:[A-Z][a-zà-ÿ'’]+(?:-[A-Z]?[a-zà-ÿ'’]+)?|[A-Z]\.)"
PARTICLE = r"(?:\s(?:bin|al|el|de|da|di|van|von|der|le|la|du)[\s-])?"
NAME = re.compile(rf"\b({WORD}{PARTICLE}(?:\s{WORD}){{1,2}})\b")
NOT_PEOPLE = set("""
the a an and of in on at for to by with from new news times post daily journal press agency media
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december
house senate congress parliament ministry minister department council court supreme union party front
army forces force guard navy police office committee commission bank fund group company corp inc ltd
university college school hospital airport station street road bridge square palace hall tower
state states united nations republic kingdom federation national international global world east west
north south central european western eastern northern southern middle security defense defence foreign
interior affairs prime president vice general secretary chief director spokesperson spokesman leader
mr mrs ms dr sir lord saint st islamic democratic republican labour liberal conservative socialist
white black red green city county region province district island islands sea gulf ocean strait
gaza strip bank west street wall mount lake river valley coast
""".split())


def candidates(text: str) -> set[str]:
    out = set()
    for m in NAME.finditer(text):
        n = re.sub(r"\s+", " ", m.group(1)).strip()
        parts = [p.lower().strip(".") for p in re.split(r"[\s-]", n)]
        if any(p in NOT_PEOPLE for p in parts) or len(n) < 6:
            continue
        out.add(n)
    return out


def article_texts() -> list[str]:
    out = []
    for f in (paths.PRIVATE / "frozen" / "article_cache").rglob("*.json"):
        try:
            a = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        t = f"{a.get('title') or ''}\n{a.get('text') or ''}"
        if t.strip():
            out.append(t)
    return out


def event_texts() -> list[str]:
    seen = {}
    for f in sorted((paths.PRIVATE / "live_snapshots").glob("*.json.gz")):
        try:
            d = json.loads(gzip.decompress(f.read_bytes()))
        except (OSError, json.JSONDecodeError, EOFError):
            continue
        for e in d.get("events") or []:
            seen[e.get("id")] = f"{e.get('title') or ''}. {e.get('summary') or ''}"
    return list(seen.values())


def count(texts: list[str], g: places.Gazetteer) -> tuple[Counter, dict[str, set[int]]]:
    full, where = Counter(), defaultdict(set)
    for i, t in enumerate(texts):
        for n in candidates(t):
            if g.lookup(n, ["country", "province", "sea", "point"], None):
                continue
            full[n] += 1
            where[n].add(i)
    return full, where


def count_shortlist() -> None:
    """How many articles and events name each hand-picked person (any of its spellings), into shortlist.json."""
    d = json.loads(SHORTLIST.read_text(encoding="utf-8"))
    sources = {"articles": article_texts(), "events": event_texts()}
    for p in d["people"]:
        pat = re.compile(r"\b(?:" + "|".join(p["match"]) + r")\b")
        for name, texts in sources.items():
            p[name] = sum(1 for t in texts if pat.search(t))
    d["counted"] = {k: len(v) for k, v in sources.items()}
    d["people"].sort(key=lambda p: (-p["events"], -p["articles"]))
    SHORTLIST.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{d['counted']} -> {SHORTLIST}")
    for p in d["people"]:
        print(f"{p['events']:5} {p['articles']:5}  {p['name']:<26} {p['group']:<9} {p['role']}")


def main() -> None:
    if "--shortlist" in sys.argv:
        return count_shortlist()
    g = places.default()
    sources = {"articles": article_texts(), "events": event_texts()}
    result = {}
    for name, texts in sources.items():
        full, where = count(texts, g)
        # a surname alone counts for the one candidate (with 3+ full mentions) that owns it
        owners = defaultdict(list)
        for n, c in full.items():
            if c >= 3:
                owners[n.split()[-1]].append(n)
        for sur, ns in owners.items():
            if len(ns) != 1 or sur.lower() in NOT_PEOPLE or g.lookup(sur, ["country", "province", "sea", "point"], None):
                continue
            pat = re.compile(rf"\b{re.escape(sur)}\b")
            where[ns[0]] |= {i for i, t in enumerate(texts) if pat.search(t)}
        result[name] = dict(items=len(texts), people={n: len(where[n]) for n, c in full.items() if c >= 2})
    names = set(result["articles"]["people"]) | set(result["events"]["people"])
    rows = sorted(({"name": n, "articles": result["articles"]["people"].get(n, 0),
                    "events": result["events"]["people"].get(n, 0)} for n in names),
                  key=lambda r: -(r["articles"] / max(1, result["articles"]["items"]) + r["events"] / max(1, result["events"]["items"])))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(articles=result["articles"]["items"], events=result["events"]["items"],
                                   people=rows[:400]), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{result['articles']['items']} articles, {result['events']['items']} events -> {OUT}")
    for r in rows[:120]:
        print(f"{r['articles']:5} {r['events']:5}  {r['name']}")


if __name__ == "__main__":
    main()
