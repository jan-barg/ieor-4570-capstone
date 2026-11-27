"""Rebuild the frozen stories with the current Gather code, from saved responses only.

    python -m scripts.remerge_frozen                 # all frozen stories
    python -m scripts.remerge_frozen --only <short id> ...
    python -m scripts.remerge_frozen --only <short id> --new-searches --max-credits 30

By default it spends nothing: the Tavily and Guardian clients run offline (a missing saved response
stops that story), and the saved queries are reused, so the query-writing model isn't called. Use it
after changing merge rules, cut-offs or outlet labels. --new-searches lets Tavily run only the
searches that have no saved response (e.g. a search added to the plan), under a hard credit cap;
the Guardian stays offline. With --new-searches, a story whose local press was added after the freeze
also makes one small paid call to the query writer, outside that credit cap. gather.json keeps the original freeze's cost, time and trace, and
records the rebuild (and any new credits) under "remerged"."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

os.environ.setdefault("STRINGER_NO_LANGFUSE", "1")

from stringer import paths  # noqa: E402
from stringer.events import fixture_events  # noqa: E402
from stringer.gather import clients, queries, run, sides, store  # noqa: E402
from stringer.gather.queries import QuerySet  # noqa: E402
from stringer.outlets import OutletTable  # noqa: E402

KEEP_FROM_FREEZE = ("gathered_at", "credits_this_run", "seconds", "langfuse_trace_id", "gather_version")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="event short ids")
    ap.add_argument("--new-searches", action="store_true", help="run Tavily searches with no saved response")
    ap.add_argument("--max-credits", type=float, default=30, help="hard cap with --new-searches")
    a = ap.parse_args(argv)
    t = OutletTable.load()
    lenses = sides.fixture_lenses(t)
    frozen = {p.name for p in paths.STORIES.iterdir() if (p / "gather.json").exists()}
    events = [e for e in fixture_events() if e.id in frozen and (not a.only or e.short in a.only)]
    tv = (clients.Tavily(ledger=clients.CreditLedger(limit=a.max_credits)) if a.new_searches
          else clients.Tavily(offline=True))
    g = clients.Guardian(offline=True)
    cache = store.ArticleCache()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    failed = []
    for i, ev in enumerate(events, 1):
        old = store.read_meta(ev.id)
        before = len(store.read_articles(ev.id))
        spent0 = tv.ledger.spent
        lens, qs, added = lenses[ev.short], QuerySet(**old["queries"]), None
        if a.new_searches and lens.local and lens.local.side_id not in qs.sides:
            # a local press added after the freeze: ask the query writer for its query only
            extra = queries.model_queries(ev, sides.Lens("none", [], local=lens.local), t)
            added = qs.sides[lens.local.side_id] = extra.sides[lens.local.side_id]
            qs.cost_usd = round(qs.cost_usd + extra.cost_usd, 6)
        try:
            run.gather_event(ev, lens, t, tv, g, queries=qs,
                             window_days=2, cache=cache, wait_s=0)
        except (FileNotFoundError, clients.BudgetExceeded) as e:
            print(f"[{i}/{len(events)}] {ev.short} SKIPPED: {e}")
            failed.append(ev.short)
            continue
        meta = store.read_meta(ev.id)
        arts = store.read_articles(ev.id)
        for k in KEEP_FROM_FREEZE:
            if k in old:
                meta[k] = old[k]
        meta["remerged"] = {"at": now, "code": run.VERSION, "articles_before": before,
                            "guardian_cut": meta["log"].get("guardian_cut"),
                            "new_credits": round(tv.ledger.spent - spent0, 2)}
        if added:
            meta["remerged"]["query_added"] = {lens.local.side_id: added}
        store.write_story(ev.id, arts, meta)
        print(f"[{i}/{len(events)}] {ev.short} {before} -> {len(arts)} articles "
              f"(Guardian cut {meta['log'].get('guardian_cut')})")
    print(f"{len(events) - len(failed)} stories rebuilt, {len(failed)} skipped; "
          f"{tv.ledger.calls} new Tavily calls, {tv.ledger.spent:.0f} credits")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
