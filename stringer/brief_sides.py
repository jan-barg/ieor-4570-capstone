"""Module 5, step 3: code adds the sides, blindspots, independent sources and flags. No model.

In:  step 2's claims (each with its sources: fact id, article id, quote), step 1's list of the
     articles it read, the picked articles (outlet labels), the pick's groups (A, B, wire, local,
     other), the story's sides (gather.json's lens) and the event.
Out: sources[] (the slim source list of the Story File), sides, each claim's sides, independent
     sources and flags, blindspots[] and the story's flags[].

Rules (decided Nov 23-25, Jan; system map, module 5 Settled):
- A side reports a claim when at least one of the claim's sources is an article on that side.
  Wires, local press and unlabeled outlets are on neither side.
- Independent sources: each article counts once, and two count as one when they are wire copies
  (pick.is_copy, which pick-2 already keeps out), or when they share wire text (SHARED_TEXT of their
  8-word runs, counted on the reporting prose with quotations left out) and the claim's quotes from
  them are the same sentence (the LA Times re-running AP's sentences). Outlets quoting the same
  speaker or document, or two wires writing the same short line, stay apart.
- Blindspot: a claim one side reports and the other doesn't, counted only when the silent side has
  at least MIN_SILENT read articles, so its silence means something. These are candidates, strongest
  first (more independent sources): on the 26 test stories about 50 a story, 87% resting on one
  article, and even at 3+ sources many are facts the other side does report in a claim step 2 kept
  apart. A judge has to check that the fact is really missing from that side and that it matters.
- Flags, a fixed list, each with a code rule, the step that reads it and what it does: thin side,
  empty side, developing, too few articles (story); unrated only, low reliability (claim). "Too few
  articles" is a note for the record and never stops a video (Jan, Nov 27).

    add_sides(step2, step1, articles, groups, lens, event) -> the step 3 part of the Story File
"""
from __future__ import annotations

import re

from . import clean, pick
from .outlets import LOW_RELIABILITY
from .brief_read import headline, norm

VERSION = "sides-3"     # sides-3: shared wire text is measured on the reporting prose, quotations left out
                        #          (sides-2 still joined four outlets that each reprinted Trump's whole post)
                        # sides-2: the same sentence counts once only between articles that share wire text
                        #          (sides-1 also joined outlets quoting the same speaker)
MIN_SILENT = 2          # blindspots only against a side with at least this many read articles (Nov 25)
RELIABLE = LOW_RELIABILITY   # a source scoring this or more can confirm a claim (Lin et al.; 0.5, set in outlets.py)
DEVELOPING = 56         # event confidence under this is "developing" (Monitor the Situation's "Verified" is 56+)
MIN_ARTICLES = 5        # fewer read articles than this gets the "too few articles" flag. A note, not a stop:
                        # the video is still made (Jan, Nov 27: "the way it works now is okay")
SAME_SENTENCE_WORDS = 6 # a shorter quote inside a longer one counts as the same sentence from this length
SHARED_TEXT = 0.10      # articles sharing this share of their prose's 8-word runs reuse wire text
                        # (quote-sharing pairs share 0-1% of prose, wire reuse 11-41%; tested Nov 25)
QUOTED = re.compile(r"“[^”]{0,3000}”|\"[^\"\n]{0,3000}\"|«[^»]{0,3000}»|„[^“”]{0,3000}[“”]")

FLAGS = {   # code -> (who reads it, what it does)
    "thin side": ("step 3", "no blindspots against this side; the video says coverage from it was thin"),
    "empty side": ("step 4 and the video", "skipped in how each side tells it; the video says the side had no coverage"),
    "developing": ("the script writer", "hedges: details may still change"),
    "too few articles": ("the pipeline", "noted in script.json (held) and pipeline.json; the video is still made"),
    "unrated only": ("the fact check", "stated as fact only if a source scoring 0.5 or more backs it; "
                                       "otherwise unconfirmed, or said with its source named"),
    "low reliability": ("the fact check", "stated as fact only if a source scoring 0.5 or more backs it; "
                                          "otherwise unconfirmed, or said with its source named"),
}


def flag(code: str, detail: str, **extra) -> dict:
    reader, action = FLAGS[code]
    return dict(code=code, detail=detail, reader=reader, action=action, **extra)


def side_ids(lens: dict) -> dict:
    """{"A": {"side_id", "label"}, "B": {...}} from gather.json's lens, or {} when there is no real divide."""
    sides = (lens or {}).get("sides") or []
    if (lens or {}).get("kind") == "none" or len(sides) < 2:
        return {}
    return {g: dict(side_id=s.get("side_id") or g, label=s.get("label") or s.get("side_id") or g)
            for g, s in zip("AB", sides[:2])}


def sources_of(articles: list[dict], groups: dict, names: dict, read: dict) -> list[dict]:
    """The Story File's slim source list: no text (it stays in articles.jsonl)."""
    out = []
    for a in articles:
        L = a.get("labels") or {}
        g = groups.get(a["id"], "other")
        out.append(dict(id=a["id"], url=a.get("url"), outlet=a.get("outlet") or L.get("outlet_id"),
                        outlet_name=L.get("outlet_name") or a.get("outlet_name"), published_at=a.get("published_at"),
                        headline=headline(a), group=g, side=names[g]["side_id"] if g in names else None,
                        lean=L.get("us_lean"), reliability=L.get("reliability"), state_media=L.get("state_media"),
                        wire=bool(L.get("is_wire")), rated=L.get("reliability") is not None,
                        read=a["id"] in read, lang=(read.get(a["id"]) or {}).get("lang")))
    return out


def _words(q: str) -> str:
    return " ".join(re.findall(r"\w+", norm(q).lower()))


def same_sentence(q1: str, q2: str) -> bool:
    """Two quotes are the same sentence when their words match, or the shorter (6+ words) sits inside the longer."""
    a, b = _words(q1), _words(q2)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short.split()) >= SAME_SENTENCE_WORDS and f" {short} " in f" {long_} "


def independent_groups(claim: dict, shares: dict) -> list[list[str]]:
    """The claim's articles, joined when they are wire copies, or share wire text and give the same
    sentence for it. shares: {frozenset of two article ids: share of 8-word runs}."""
    arts = list(dict.fromkeys(s["article"] for s in claim.get("sources") or []))
    quotes = {a: [s.get("quote") or "" for s in claim["sources"] if s["article"] == a] for a in arts}
    parent = {a: a for a in arts}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(arts):
        for b in arts[i + 1:]:
            sh = shares.get(frozenset((a, b)), 0.0)
            if sh >= pick.COPY_SHARE or (sh >= SHARED_TEXT and any(same_sentence(x, y)
                                                                  for x in quotes[a] for y in quotes[b])):
                parent[root(b)] = root(a)
    out = {}
    for a in arts:
        out.setdefault(root(a), []).append(a)
    return list(out.values())


def prose_runs(text: str, k: int = 8) -> set[str]:
    """8-word runs of the cleaned text without quotations ("...", “...”, «...», > quote lines), so two
    outlets reprinting the same statement don't look like a shared wire story."""
    lines = [ln for ln in clean.clean(text or "").split("\n") if not ln.lstrip().startswith(">")]
    prose = QUOTED.sub(" ", clean.LINK.sub(lambda m: m.group(1), "\n".join(lines)))
    words = re.findall(r"\w+", prose.lower())
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def shared_text(articles: list[dict]) -> dict:
    """{frozenset of two article ids: share}, for pairs that are wire copies (pick's check: 50%+ of
    the cleaned text's 8-word runs) or share SHARED_TEXT of their prose. A copy is recorded as 1.0."""
    full = {a["id"]: clean.runs(a.get("text", "")) for a in articles}
    prose = {a["id"]: prose_runs(a.get("text", "")) for a in articles}
    out = {}
    for i, a in enumerate(articles):
        for b in articles[i + 1:]:
            key = frozenset((a["id"], b["id"]))
            if pick.copy_share(full[a["id"]], full[b["id"]]) >= pick.COPY_SHARE:
                out[key] = 1.0
            else:
                sh = pick.copy_share(prose[a["id"]], prose[b["id"]])
                if sh >= SHARED_TEXT:
                    out[key] = round(sh, 3)
    return out


def claim_flags(claim: dict, by_id: dict) -> list[str]:
    scores = [(by_id.get(a) or {}).get("reliability") for a in claim["articles"]]
    if all(s is None for s in scores):
        return ["unrated only"]
    if not any(s is not None and s >= RELIABLE for s in scores):
        return ["low reliability"]
    return []


def add_sides(step2: dict, step1: dict, articles: list[dict], groups: dict, lens: dict, event: dict) -> dict:
    """Step 3 for one story."""
    names = side_ids(lens)
    # "read" means step 1 gave an answer for the article; one it failed on (a timeout, an unusable answer)
    # was sent but not read, and must not count toward "we read N articles", thin sides or blindspots
    read = {r["article"]: r for r in (step1 or {}).get("articles") or [] if not (r.get("checks") or {}).get("error")}
    sources = sources_of(articles, groups, names, read)
    by_id = {s["id"]: s for s in sources}
    shares = shared_text(articles)
    n_read = {g: sum(1 for s in sources if s["group"] == g and s["read"]) for g in names}
    out = dict(version=VERSION, sources=sources, claims=[], blindspots=[], flags=[],
               sides=dict(kind="two sides", **{g: dict(names[g], articles=n_read[g]) for g in names})
               if names else dict(kind="no real divide", reason=(lens or {}).get("reason") or (lens or {}).get("kind") or ""))
    other = {"A": "B", "B": "A"}
    blind = {g: [] for g in names}
    for c in step2.get("claims") or []:
        c = dict(c)
        c["articles"] = list(dict.fromkeys(c.get("articles") or [s["article"] for s in c.get("sources") or []]))
        gs = {(by_id.get(a) or {}).get("group", "other") for a in c["articles"]}
        c["sides"] = [names[g]["side_id"] for g in "AB" if g in names and g in gs]
        c["neither"] = sum(1 for a in c["articles"] if (by_id.get(a) or {}).get("group", "other") not in names)
        grp = independent_groups(c, shares)
        c["independent"] = len(grp)
        c["independent_groups"] = grp if len(grp) < len(c["articles"]) else []
        c["flags"] = claim_flags(c, by_id)
        c["blindspot_of"] = None
        if len(c["sides"]) == 1:
            g = next(g for g in "AB" if names.get(g, {}).get("side_id") == c["sides"][0])
            silent = other[g]
            if n_read[silent] >= MIN_SILENT:
                c["blindspot_of"] = names[silent]["side_id"]
                blind[silent].append(c["id"])
        out["claims"].append(c)
    ind = {c["id"]: c["independent"] for c in out["claims"]}
    for g in names:
        if blind[g]:                      # strongest first: more independent sources report the claim
            ids = sorted(blind[g], key=lambda i: -ind[i])
            out["blindspots"].append(dict(silent_side=names[g]["side_id"], label=names[g]["label"],
                                          reported_by=names[other[g]]["side_id"], claims=ids,
                                          sources={i: ind[i] for i in ids}))
    for g in names:
        if n_read[g] == 0:
            out["flags"].append(flag("empty side", f"{names[g]['label']}: no article read", side=names[g]["side_id"]))
        elif n_read[g] < MIN_SILENT:
            out["flags"].append(flag("thin side", f"{names[g]['label']}: {n_read[g]} article read",
                                     side=names[g]["side_id"]))
    try:
        conf = int(float((event or {}).get("confidence")))
    except (TypeError, ValueError):
        conf = None
    if conf is not None and conf < DEVELOPING:
        out["flags"].append(flag("developing", f"event confidence {conf} (under {DEVELOPING})"))
    total = sum(1 for s in sources if s["read"])
    if total < MIN_ARTICLES:
        out["flags"].append(flag("too few articles", f"{total} articles read (under {MIN_ARTICLES})"))
    for code in ("unrated only", "low reliability"):
        ids = [c["id"] for c in out["claims"] if code in c["flags"]]
        if ids:
            out["flags"].append(flag(code, f"{len(ids)} claims", claims=ids))
    cl = out["claims"]
    out["counts"] = dict(
        claims=len(cl), articles_read=total, **{f"read_{g}": n_read[g] for g in names},
        both_sides=sum(len(c["sides"]) == 2 for c in cl),
        one_side=sum(len(c["sides"]) == 1 for c in cl),
        neither_only=sum(not c["sides"] for c in cl),
        blindspots=sum(len(b["claims"]) for b in out["blindspots"]),
        unrated_only=sum("unrated only" in c["flags"] for c in cl),
        low_reliability=sum("low reliability" in c["flags"] for c in cl),
        multi_source=sum(len(c["articles"]) > 1 for c in cl),
        same_sentence_joined=sum(bool(c["independent_groups"]) for c in cl),
        copy_pairs=sum(v >= pick.COPY_SHARE for v in shares.values()),
        shared_text_pairs=len(shares))
    return out
