"""Pick the articles the later steps read: at most 10 per story, balanced (decided Nov 24, Jan).

Gather keeps a wide pool (Tavily charges per search, not per result), and this step chooses what
the models read, so a big pool doesn't mean more model compute. Past about 10 articles, extra ones
mostly repeat the same facts. The pool stays saved, so the fact-finding eval can compare caps
(10 against 20 or all) on how many must-have facts each one covers.

Rules, all code, no model:
  1. Usable: full text, a news or wire outlet, not an opinion section, dated as coverage of the
     event ("new_coverage"; "unclear" only as a fallback), and not judged off-topic by the
     same-story step once that exists (verdict "different").
  2. At most one article per outlet, and no near-copies (the same wire story under two outlets).
  3. Two sides: up to 4 per side, and the bigger side gets at most one more than the smaller.
     The rest come from outlets on neither side, wires first. A side with too little is flagged,
     never padded. Only if the neutral outlets run out do the sides grow, one pair at a time.
  4. No split: up to 4 from the story's local press (if it has one), then wires, then the rest.
  5. Within a group: the event's own cited sources first, then articles more searches found,
     then the best search rank, then the longest text.
"""
from __future__ import annotations

import re
from collections import defaultdict

VERSION = "pick-1 (2026-11-24)"
N = 10
PER_SIDE = 4
LOCAL_FIRST = 4
ROLE_ORDER = {"new_coverage": 0, "unclear": 1}
COPY_TITLE = 0.6      # title word overlap at which two articles count as the same story copy
COPY_TEXT = 0.5       # share of shared 8-word runs in the opening text, same idea


def usable(a: dict) -> bool:
    L = a.get("labels") or {}
    return (a.get("text_status") == "full" and a.get("role") in ROLE_ORDER
            and L.get("kind") in ("news", "wire") and L.get("section") != "opinion"
            and a.get("verdict") != "different")


def rank_key(a: dict):
    return (ROLE_ORDER[a["role"]], not a.get("own_source"), -len(a.get("found_by") or []),
            a.get("best_rank") if a.get("best_rank") is not None else 99, -(a.get("text_chars") or 0),
            a.get("url_key", ""))


def _title_words(title: str) -> set[str]:
    title = re.split(r"\s[-|–—]\s(?=[^-|–—]*$)", title or "")[0]       # drop " - Outlet Name"
    return {w for w in re.findall(r"\w+", title.lower()) if len(w) >= 3}


def _runs(text: str, k=8) -> set[tuple]:
    w = re.findall(r"\w+", (text or "")[:2000].lower())
    return {tuple(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def near_copy(a: dict, b: dict) -> bool:
    ta, tb = _title_words(a.get("title", "")), _title_words(b.get("title", ""))
    if ta and tb and len(ta & tb) / len(ta | tb) >= COPY_TITLE:
        return True
    ra, rb = _runs(a.get("text", "")), _runs(b.get("text", ""))
    return bool(ra and rb) and len(ra & rb) / min(len(ra), len(rb)) >= COPY_TEXT


def group_of(a: dict, lens: dict) -> str:
    """A or B for the two sides, else local, wire or other. `lens` is gather.json's lens record."""
    for g, s in zip("AB", (lens.get("sides") or [])[:2]):
        if a.get("outlet") in s["outlet_ids"]:
            return g
    local = lens.get("local")
    if local and a.get("outlet") in local["outlet_ids"]:
        return "local"
    return "wire" if (a.get("labels") or {}).get("is_wire") else "other"


def pick(articles: list[dict], lens: dict, n: int = N) -> dict:
    pool = sorted((a for a in articles if usable(a)), key=rank_key)
    by = defaultdict(list)
    for a in pool:
        by[group_of(a, lens)].append(a)
    chosen, outlets, why = [], set(), {}

    def take(group: str, limit: int) -> int:
        got = 0
        for a in by[group]:
            if got >= limit or len(chosen) >= n:
                break
            if a["id"] in why or a.get("outlet") in outlets or any(near_copy(a, c) for c in chosen):
                continue
            chosen.append(a)
            outlets.add(a.get("outlet"))
            why[a["id"]] = group
            got += 1
        return got

    def distinct(group: str) -> int:
        return len({a.get("outlet") for a in by[group]})

    sides = (lens.get("sides") or [])[:2]
    flags = []
    if len(sides) == 2:
        small, big = sorted("AB", key=lambda g: (distinct(g), g))
        got_small = take(small, PER_SIDE)
        got_big = take(big, min(PER_SIDE, got_small + 1))
        if got_small < PER_SIDE:
            name = dict(zip("AB", sides))
            flags.append(f"thin side: {name[small]['side_id']} gave {got_small} of {PER_SIDE}, "
                         f"so {name[big]['side_id']} was held to {got_big}")
        take("wire", n)
        take("other", n)
        while len(chosen) < n:                     # neutrals ran out: grow both sides together
            if not (take(small, 1) and take(big, 1)):
                break
    else:
        take("local", LOCAL_FIRST)
        take("wire", n)
        take("other", n)
        take("local", n)
    if len(chosen) < n:
        flags.append(f"only {len(chosen)} usable articles")
    return {
        "version": VERSION, "n": n,
        "picked": [a["id"] for a in chosen],
        "rows": [{"id": a["id"], "group": why[a["id"]], "outlet": a.get("outlet"),
                  "own_source": bool(a.get("own_source")), "title": a.get("title", "")} for a in chosen],
        "available": {g: distinct(g) for g in sorted(by)},
        "usable": len(pool), "flags": flags,
    }
