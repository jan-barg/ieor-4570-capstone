"""Freeze Gather's results for the 40 test stories (26 pipeline + 14 chain).

    python -m scripts.freeze_fixtures --dry-run                  # plan + credit estimate, spends nothing
    python -m scripts.freeze_fixtures --writer model             # the real run
    python -m scripts.freeze_fixtures --writer template --only <event short id> ...

Every API response is saved under frozen/raw/, so a re-run (or a run that stopped halfway)
only pays for what is missing. Before spending anything the script asks Tavily how many plan
credits are left and refuses to start if the estimate doesn't fit under both --limit (400 by
default) and the plan's remaining credits, so the run can never spill into pay-as-you-go.
The same limit is enforced call by call while it runs."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time

from stringer import paths
from stringer.events import ATTRIBUTION, fixture_events, fixture_rows
from stringer.gather import clients, plan, queries, run, sides, store
from stringer.gather.merge import url_key
from stringer.outlets import OutletTable

SAFETY = 20          # credits kept free below the plan's remaining balance
RETRY_SHARE = 0.15   # share of searches expected to come back thin and retry once


def estimate(ev, lens, t, cache, window_days):
    """Credits this story would cost now, counting only calls with no saved response."""
    end = (ev.start + dt.timedelta(days=window_days)).strftime("%Y-%m-%d") if window_days else None
    qs = queries.template_queries(ev, lens)            # the number of searches doesn't depend on wording
    searches = plan.build_searches(ev, lens, qs, t, end)
    new = [s for s in searches
           if not os.path.exists(os.path.join(paths.RAW, f"{ev.short}/{s.qid}.json"))]
    extract_urls, g_own, xposts = plan.own_links(ev)
    todo = [u for u in extract_urls if url_key(u) not in cache.full_text_keys({url_key(x) for x in extract_urls})]
    ext_saved = os.path.exists(os.path.join(paths.RAW, f"{ev.short}/own_extract.json"))
    ext = 0 if ext_saved or not todo else math.ceil(len(todo) / 5)
    return {"event": ev.short, "lens": lens.kind, "searches": len(searches), "new_searches": len(new),
            "extract_links": len(todo), "x_posts": len(xposts), "guardian_own": len(g_own),
            "credits": len(new) + ext, "credits_with_retries": len(new) + ext + RETRY_SHARE * len(new),
            "worst_case": 3 * len(new) + ext}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--writer", choices=["model", "template"], help="who writes the reworded, side and background queries")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=float, default=400, help="most Tavily credits this run may spend")
    ap.add_argument("--window-days", type=int, default=2, help="end_date = start + this many days")
    ap.add_argument("--only", nargs="*", help="event short ids")
    ap.add_argument("--no-usage-check", action="store_true", help="dry run only: skip asking Tavily for the balance")
    ap.add_argument("--wait", type=int, default=plan.RETRY_WAIT_S, help="seconds before the second retry")
    a = ap.parse_args(argv)
    if not a.dry_run and not a.writer:
        ap.error("--writer is required for a real run (model or template)")

    t = OutletTable.load()
    lenses = sides.fixture_lenses(t)
    rows = {r["id"][:8]: r for r in fixture_rows()}
    events = fixture_events()
    if a.only:
        events = [e for e in events if e.short in set(a.only)]
    missing = [e.short for e in events if e.short not in lenses]
    if missing:
        sys.exit(f"no lens in fixture_lenses_v1.csv for {missing}")
    cache = store.ArticleCache()

    est = [estimate(e, lenses[e.short], t, cache, a.window_days) for e in events]
    total = sum(x["credits"] for x in est)
    likely = math.ceil(sum(x["credits_with_retries"] for x in est))
    worst = sum(x["worst_case"] for x in est)
    print(f"{len(events)} stories, window start..start+{a.window_days}d")
    print(f"{'event':9} {'set':8} {'lens':5} {'searches':>8} {'new':>4} {'extract':>7} {'credits':>7}")
    for x in est:
        print(f"{x['event']:9} {rows[x['event']]['set']:8} {x['lens']:5} {x['searches']:8} "
              f"{x['new_searches']:4} {x['extract_links']:7} {x['credits']:7}")
    print(f"estimate: {total} credits with no retries, ~{likely} with typical retries, {worst} worst case")

    balance = None
    if not a.no_usage_check or not a.dry_run:
        tv0 = clients.Tavily()
        u = tv0.usage()
        if u["limit"] is not None and u["used"] is not None:
            balance = u["limit"] - u["used"]
        print(f"Tavily plan {u['plan']}: {u['used']} of {u['limit']} used, {balance} left "
              f"(pay-as-you-go used: {u['paygo_used']})")
    cap = a.limit if balance is None else min(a.limit, balance - SAFETY)
    print(f"this run may spend at most {cap:.0f} credits")
    if likely > cap:
        sys.exit(f"STOP: the likely cost ({likely}) is over the cap ({cap:.0f}). Ask Jan before going on.")
    if a.dry_run:
        return 0

    tv = clients.Tavily(ledger=clients.CreditLedger(limit=cap))
    g = clients.Guardian()
    started = dt.datetime.now(dt.timezone.utc)
    done, failed = [], []
    for i, ev in enumerate(events, 1):
        t0 = time.time()
        try:
            meta = run.gather_event(ev, lenses[ev.short], t, tv, g, writer=a.writer,
                                    window_days=a.window_days, cache=cache, wait_s=a.wait)
        except clients.BudgetExceeded as e:
            print(f"[{i}/{len(events)}] {ev.short} STOPPED: {e}. Saved responses are kept; re-run to resume.")
            failed.append({"event": ev.short, "error": f"budget: {e}"})
            break
        except Exception as e:          # one bad story shouldn't stop the other 39
            print(f"[{i}/{len(events)}] {ev.short} FAILED: {e!r}")
            failed.append({"event": ev.short, "error": repr(e)[:500]})
            continue
        c = meta["counts"]
        done.append({"event": ev.short, "credits": meta["credits_this_run"], **c})
        print(f"[{i}/{len(events)}] {ev.short} {c['articles']} articles "
              f"({c['roles'].get('new_coverage', 0)} new, {c['text_status'].get('full', 0)} full text), "
              f"{meta['credits_this_run']} credits, {time.time() - t0:.0f}s; run total {tv.ledger.spent:.0f}")
    summary = {"attribution": ATTRIBUTION, "gather_version": run.VERSION, "writer": a.writer,
               "window_days": a.window_days, "started": started.isoformat(timespec="seconds"),
               "finished": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "estimate": {"no_retries": total, "likely": likely, "worst": worst},
               "credits_spent": round(tv.ledger.spent, 2), "tavily_calls": tv.ledger.calls,
               "guardian_calls": g.calls, "stories": done, "failed": failed}
    os.makedirs(paths.RUNS, exist_ok=True)
    out = paths.RUNS / f"freeze-{started:%Y-%m-%dT%H%M}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"{len(done)} stories frozen, {len(failed)} failed, {tv.ledger.spent:.0f} credits; summary {out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
