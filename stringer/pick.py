"""Pick the articles the later steps read: at most 10 per story, balanced (decided Nov 24, Jan).

Gather keeps a wide pool (Tavily charges per search, not per result), and this step chooses what
the models read, so a big pool doesn't mean more model compute. Past about 10 articles, extra ones
mostly repeat the same facts. The pool stays saved, so the fact-finding eval can compare caps
(10 against 20 or all) on how many must-have facts each one covers.

Rules, all code, no model:
  1. Usable: full text, a news or wire outlet, not an opinion section, not background, and not
     judged off-topic by the same-story step (verdict "different").
  2. Coverage first. An article dated after the event is coverage; so is an undated one that the
     same-story step calls the same story or that the event itself cites (decided Nov 25: 40 of
     the event's own full-text sources were left out for having no date). Other undated
     articles are a fallback.
  3. At most one article per outlet, and no wire copies: two articles are copies when half or
     more of the shorter one's 8-word runs appear in the other, on menu-cleaned text
     (`clean.runs`; decided Nov 25, tested on 20,701 pairs).
  4. Two sides: up to 4 per side, and the bigger side gets at most one more than the smaller.
     The rest come from outlets on neither side, wires first. A thin side is flagged, never
     padded. Only if the neutral outlets run out do the sides grow, one pair at a time.
     An empty side (no usable article) is flagged and no longer holds the other side to one:
     that side gives up to 3, neutral outlets fill, and if they run out that side fills to 10.
  5. No split: up to 4 from the story's local press (if it has one), then wires, then the rest.
  6. Within a group: the event's own cited sources first, then articles more searches found,
     then the best search rank, then the longest text.

An article's side comes from its outlet (side lists, state media). Articles from unlabeled outlets
stay on neither side: a side model (Jev) was tested and dropped on Nov 25 because it put most
straight reporting on a side. `group_of` still honours an article's own `side` field (a side_id)
if something ever fills it; nothing does today.
"""
from __future__ import annotations

from collections import defaultdict

from stringer import clean

VERSION = "pick-2 (2026-11-25)"
N = 10
PER_SIDE = 4
EMPTY_SIDE_MAX = 3    # what the side with coverage gives when the other side has none
LOCAL_FIRST = 4
ROLES = ("new_coverage", "unclear")
COPY_SHARE = 0.5      # share of the shorter article's 8-word runs found in the other: a wire copy


def usable(a: dict) -> bool:
    L = a.get("labels") or {}
    return (a.get("text_status") == "full" and a.get("role") in ROLES
            and L.get("kind") in ("news", "wire") and L.get("section") != "opinion"
            and a.get("verdict") != "different")


def is_coverage(a: dict) -> bool:
    """Dated coverage, or undated but confirmed: same story per module 2, or cited by the event."""
    return a.get("role") == "new_coverage" or a.get("verdict") == "same" or bool(a.get("own_source"))


def rank_key(a: dict):
    return (not is_coverage(a), not a.get("own_source"), -len(a.get("found_by") or []),
            a.get("best_rank") if a.get("best_rank") is not None else 99, -(a.get("text_chars") or 0),
            a.get("url_key", ""))


def copy_share(runs_a: set, runs_b: set) -> float:
    """Share of the shorter text's 8-word runs that appear in the other text."""
    if not runs_a or not runs_b:
        return 0.0
    return len(runs_a & runs_b) / min(len(runs_a), len(runs_b))


def is_copy(a: dict, b: dict) -> bool:
    return copy_share(clean.runs(a.get("text", "")), clean.runs(b.get("text", ""))) >= COPY_SHARE


def group_of(a: dict, lens: dict) -> str:
    """A or B for the two sides, else local, wire or other. `lens` is gather.json's lens record."""
    sides = (lens.get("sides") or [])[:2]
    for g, s in zip("AB", sides):
        if a.get("outlet") in s["outlet_ids"]:
            return g
    if a.get("side"):                                  # unused today: no side model (Nov 25)
        for g, s in zip("AB", sides):
            if a["side"] == s["side_id"]:
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
    chosen, outlets, why, runs = [], set(), {}, {}

    def runs_of(a: dict) -> set:
        if a["id"] not in runs:
            runs[a["id"]] = clean.runs(a.get("text", ""))
        return runs[a["id"]]

    def copies_one(a: dict) -> bool:
        return any(copy_share(runs_of(a), runs_of(c)) >= COPY_SHARE for c in chosen)

    def take(group: str, limit: int) -> int:
        got = 0
        for a in by[group]:
            if got >= limit or len(chosen) >= n:
                break
            if a["id"] in why or a.get("outlet") in outlets or copies_one(a):
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
        name = {g: s["side_id"] for g, s in zip("AB", sides)}
        small, big = sorted("AB", key=lambda g: (distinct(g), g))
        got_small = take(small, PER_SIDE)
        if got_small == 0:                         # empty side: the other side isn't held to one
            got_big = take(big, EMPTY_SIDE_MAX)
            flags.append(f"empty side: {name[small]} had no usable articles")
            if got_big == 0:
                flags.append(f"empty side: {name[big]} had no usable articles")
            take("wire", n)
            take("other", n)
            take(big, n)                           # neutrals ran out: the side with coverage fills
        else:
            got_big = take(big, min(PER_SIDE, got_small + 1))
            if got_small < PER_SIDE:
                flags.append(f"thin side: {name[small]} gave {got_small} of {PER_SIDE}, "
                             f"so {name[big]} was held to {got_big}")
            take("wire", n)
            take("other", n)
            while len(chosen) < n:                 # neutrals ran out: grow both sides together
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
