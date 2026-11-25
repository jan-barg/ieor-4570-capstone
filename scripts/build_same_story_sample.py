"""Draw the sample Jan labels by hand for the same-story filter (module 2), and split it into the
part used for prompt changes ("tune") and the part kept out of them ("holdout").

    python -m scripts.build_same_story_sample          # writes fixtures/same_story_sample_v1.json

Free and offline: reads the frozen stories, fixture_lenses_v1.csv and same_story_pairs_extra.csv.

Two kinds of items:
  1. An article and the event whose search found it: is the article about this event, an earlier
     or later stage of it (follow-up), or a different event? 4 per story, one from each stratum:
       guardian  a Guardian result (about half of them are off-topic)
       picked    one of the 10 articles the pick step currently hands to the news brief
       before    published before the event started, preferring the 48 hours before it (an
               earlier stage of the story, or something else)
       undated   no date from the search (often a side's own outlets, often not in English);
                 if none, an article only one search found
     A stratum with nothing in it is filled from the rest of the story's pool. The event's own
     cited sources are left out: the filter marks them "same" by rule.
  2. Two events: the same event, the same chain (follow-up), or different? Every follow-up event
     against the event it follows, neighbouring follow-ups of the same chain against each other,
     and the hand-picked look-alikes in same_story_pairs_extra.csv. The front page will use this to
     group follow-up events into video chains.

Split: by story, whole chains together (a follow-up shares articles with its parent), every third
chain and every third single story to "holdout"."""
from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from collections import defaultdict

from stringer import paths
from stringer.events import parse_ts
from stringer.gather import store

VERSION = "same-story-sample-v1"
OUT = paths.FIXTURES / "same_story_sample_v1.json"
EXTRA_PAIRS = paths.FIXTURES / "same_story_pairs_extra.csv"
STRATA = ("guardian", "picked", "before", "undated")


def _h(s: str) -> str:
    return hashlib.sha1(f"{VERSION}:{s}".encode()).hexdigest()


def chains() -> tuple[dict[str, str], set[str]]:
    """short id -> the short id of its chain's first event (itself for a story with no chain),
    and the follow-ups the fixture list marks as hard negatives (same war, different event)."""
    head, hard = {}, set()
    for r in csv.DictReader(open(paths.FIXTURE_LENSES_CSV, encoding="utf-8")):
        src = r["source"]
        head[r["event"]] = src.split()[2] if src.startswith("chain of") else r["event"]
        if "hard negative" in src:
            hard.add(r["event"])
    return head, hard


def split_of(head: dict[str, str]) -> dict[str, str]:
    groups = defaultdict(list)
    for sid, h in head.items():
        groups[h].append(sid)
    multi = sorted((g for g in groups if len(groups[g]) > 1), key=_h)
    single = sorted((g for g in groups if len(groups[g]) == 1), key=_h)
    out = {}
    for ordered in (multi, single):
        for i, g in enumerate(ordered):
            for sid in groups[g]:
                out[sid] = "holdout" if i % 3 == 2 else "tune"
    return out


def hours_after(a: dict, start) -> float | None:
    t = parse_ts(a.get("published_at"))
    return None if t is None else round((t - start).total_seconds() / 3600, 1)


def article_view(a: dict, start) -> dict:
    return dict(article_id=a["id"], url=a["url"], title=(a.get("title") or "").strip(),
                outlet=a.get("outlet_name") or a.get("outlet"), published_at=a.get("published_at"),
                date_precision=a.get("date_precision"), hours_after_start=hours_after(a, start),
                role=a.get("role"), text_status=a.get("text_status"))


def event_view(meta: dict) -> dict:
    e = meta["event"]
    return dict(id=e["id"], short=e["id"][:8], title=e["title"], start=e["start"],
                place=e.get("location_name"), url=e["url"], lens=meta["lens"]["kind"])


def pick_articles(arts: list[dict], picked: set[str], rng: random.Random, start) -> list[tuple[str, dict]]:
    pool = [dict(a, _h=hours_after(a, start)) for a in arts if not a.get("own_source")
            and (a.get("title") or "").strip() and "x.com/" not in a["url"]]
    pool.sort(key=lambda a: a["id"])
    tests = {
        "guardian": lambda a: a.get("outlet") == "theguardian",
        "picked": lambda a: a["id"] in picked,
        "before": lambda a: a.get("role") == "background",
        "undated": lambda a: a.get("role") == "unclear",
    }
    chosen, used = [], set()
    for s in STRATA:
        cands = [a for a in pool if tests[s](a) and a["id"] not in used]
        if s == "before":                    # the 48 hours before the start: the hard cases
            near = [a for a in cands if (a.get("_h") or -1e9) >= -48]
            cands = near or cands
        if s == "undated" and not cands:
            cands = [a for a in pool if len(a.get("found_by") or []) == 1 and a.get("outlet") != "theguardian"
                     and a["id"] not in used]
        if not cands:
            cands = [a for a in pool if a["id"] not in used]
            s = f"{s} (empty, filled from the rest)"
        if cands:
            a = rng.choice(cands)
            chosen.append((s, a))
            used.add(a["id"])
    return chosen


def main(argv=None):
    head, hard = chains()
    split = split_of(head)
    metas, items = {}, []
    for d in sorted(p for p in paths.STORIES.iterdir() if (p / "gather.json").exists()):
        meta = store.read_meta(d.name)
        sid = d.name[:8]
        metas[sid] = meta
        arts = store.read_articles(d.name)
        picked = set(json.loads((d / "picked.json").read_text())["picked"]) if (d / "picked.json").exists() else set()
        start = parse_ts(meta["event"]["start"])
        for stratum, a in pick_articles(arts, picked, random.Random(_h(sid)), start):
            items.append(dict(id=f"a:{sid}:{a['id']}", kind="article", story=sid, split=split.get(sid, "tune"),
                              stratum=stratum, article=article_view(a, start)))
    pairs = []
    by_chain = defaultdict(list)
    for sid, h in head.items():
        if h != sid:
            pairs.append((h, sid, "listed as a hard negative: same war, a different event" if sid in hard
                          else "follow-up event against the event it follows"))
            by_chain[h].append(sid)
    for h, kids in by_chain.items():
        kids.sort(key=lambda s: metas[s]["event"]["start"])
        for x, y in zip(kids, kids[1:]):
            pairs.append((x, y, "two follow-ups of the same chain"))
    for r in csv.DictReader(open(EXTRA_PAIRS, encoding="utf-8")):
        pairs.append((r["a"], r["b"], r["why"]))
    for a, b, why in pairs:
        ea, eb = metas[a]["event"], metas[b]["event"]
        days = round((parse_ts(eb["start"]) - parse_ts(ea["start"])).total_seconds() / 86400, 2)
        items.append(dict(id=f"e:{a}:{b}", kind="event_pair", story=a, split=split.get(a, "tune"),
                          stratum="event pair", why=why, other=event_view(metas[b]), days_after=days))
    out = dict(version=VERSION, note="Drawn by scripts/build_same_story_sample.py. Labels go in "
               "same_story_labels_v1.json; this file only lists what to label.",
               events={sid: event_view(m) for sid, m in metas.items()},
               splits={s: sorted(k for k, v in split.items() if v == s) for s in ("tune", "holdout")},
               items=items)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_art = sum(i["kind"] == "article" for i in items)
    print(f"wrote {OUT}: {n_art} article items over {len(metas)} stories, {len(items) - n_art} event pairs; "
          f"holdout stories {len(out['splits']['holdout'])}, tune {len(out['splits']['tune'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
