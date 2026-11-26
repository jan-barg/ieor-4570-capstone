"""The follow-up round for short sides (stringer/balance.py), after the same-story filter and before the pick.

    python -m scripts.balance_followup --test --dry-run          # free: which sides are short, worst-case credits
    python -m scripts.balance_followup --test --limit 45         # the test on copies of the frozen stories
    python -m scripts.balance_followup --stories-dir <dir> --only <id>   # a live story, in place, then re-pick

--test never touches the frozen stories: it copies each story with a short side to
stringer_private/balance_design/followup_test/stories/<id>/ (picked.json there is renamed
picked_before.json), saves Tavily's responses under followup_test/raw/, runs the round, re-picks and
writes followup_test/summary.json. New articles are judged by the same-story filter's model
(config/models.toml, step same_story), a few cents at most.

Before spending, it asks Tavily how many plan credits are left and refuses to start if the worst case
doesn't fit under --limit and the balance, so it can't spill into pay-as-you-go."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

from stringer import balance, lens, paths, pick
from stringer.gather import clients, store
from stringer.outlets import OutletTable

TEST = paths.PRIVATE / "balance_design" / "followup_test"
SAFETY = 20


def read(d: Path):
    meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
    arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
    return meta, arts


def write(d: Path, arts: list[dict], rec: dict, meta: dict):
    store._atomic_write(d / "articles.jsonl", "\n".join(json.dumps(a, ensure_ascii=False) for a in arts) + "\n")
    store._atomic_write(d / "balance.json", json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    p = pick.pick(arts, meta["lens"])
    p["event"] = meta["event"]["id"]
    store._atomic_write(d / "picked.json", json.dumps(p, ensure_ascii=False, indent=1) + "\n")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="run on copies of the frozen stories")
    ap.add_argument("--stories-dir", help="run in place on the stories in this folder (live stories)")
    ap.add_argument("--only", nargs="*", help="event short ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=float, default=45, help="most Tavily credits this run may spend")
    ap.add_argument("--no-filter", action="store_true", help="don't judge new articles (they stay unjudged, as Gather leaves them)")
    a = ap.parse_args(argv)
    if not (a.test or a.stories_dir):
        ap.error("give --test or --stories-dir")
    src = paths.STORIES if a.test else Path(a.stories_dir)
    t = OutletTable.load()
    todo = []
    for d in sorted(p for p in src.iterdir() if (p / "gather.json").exists()):
        if a.only and d.name[:8] not in a.only:
            continue
        meta, arts = read(d)
        est = balance.estimate(meta["lens"], arts, t)
        if est["sides"]:
            todo.append((d, meta, arts, est))
    worst = sum(e["credits_max"] for *_, e in todo)
    reads = sum(e["read_credits"] for *_, e in todo)
    print(f"{len(todo)} stories with a short side (fewer than {balance.MIN_USABLE} usable outlets)")
    for d, meta, _, e in todo:
        for s in e["sides"]:
            print(f"  {d.name[:8]} {meta['event']['title'][:44]:44} {s['side_id']:22} usable {s['usable']}  "
                  f"pages to read {s['pages']:2} ({s['read_credits']} cr)  search {s['search_credits']} cr if still short")
    print(f"worst case {worst} credits ({reads} for reading pages, the rest only for sides still short)")
    if a.dry_run or not todo:
        return 0
    tv0 = clients.Tavily()
    u = tv0.usage()
    left = (u["limit"] - u["used"]) if u["limit"] is not None and u["used"] is not None else None
    cap = a.limit if left is None else min(a.limit, left - SAFETY)
    print(f"Tavily plan {u['plan']}: {u['used']} of {u['limit']} used, {left} left; this run may spend {cap:.0f}")
    if worst > cap:
        sys.exit(f"STOP: the worst case ({worst}) is over the cap ({cap:.0f}). Ask Jan before going on.")
    raw = (TEST / "raw") if a.test else (src.parent / "raw")
    tv = clients.Tavily(ledger=clients.CreditLedger(limit=cap), raw_dir=str(raw))
    complete = None if a.no_filter else lens.live_complete("same_story")
    rows, totals = [], Counter()
    for d, meta, arts, _ in todo:
        out = d
        if a.test:
            out = TEST / "stories" / d.name
            out.mkdir(parents=True, exist_ok=True)
            for f in ("gather.json", "articles.jsonl"):
                shutil.copy2(d / f, out / f)
            if (d / "picked.json").exists():
                shutil.copy2(d / "picked.json", out / "picked_before.json")
        try:
            rec = balance.followup(meta, arts, t, tv, complete)
        except clients.BudgetExceeded as e:
            print(f"{d.name[:8]} STOPPED at the credit cap: {e}")
            break
        before_pick = json.loads((d / "picked.json").read_text(encoding="utf-8")) if (d / "picked.json").exists() else {}
        p = write(out, arts, rec, meta)
        g0 = Counter(r["group"] for r in before_pick.get("rows") or [])
        g1 = Counter(r["group"] for r in p["rows"])
        row = dict(event=d.name[:8], title=meta["event"]["title"], before=rec["before"], after=rec["after"],
                   credits=rec["credits"], added=len(rec["added"]), picks_before=dict(g0), picks_after=dict(g1),
                   flags_before=before_pick.get("flags"), flags_after=p["flags"], log=rec["log"])
        rows.append(row)
        totals["credits"] += rec["credits"]
        print(f"{d.name[:8]} usable per side {rec['before']} -> {rec['after']}; picks {dict(g0)} -> {dict(g1)}; "
              f"{rec['credits']} credits, {len(rec['added'])} new articles")
    summary = dict(version=balance.VERSION, stories=rows, credits=totals["credits"], tavily_calls=tv.ledger.calls)
    target = (TEST if a.test else src.parent) / "followup_summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{totals['credits']} credits in all; summary {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
