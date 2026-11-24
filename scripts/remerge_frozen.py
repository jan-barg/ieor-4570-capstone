"""Rebuild the frozen stories with the current Gather code, from saved responses only.

    python -m scripts.remerge_frozen                 # all frozen stories
    python -m scripts.remerge_frozen --only <short id> ...

Spends nothing: the Tavily and Guardian clients run offline (a missing saved response stops that
story), and the saved queries are reused, so the query-writing model isn't called. Use it after
changing merge rules, cut-offs or outlet labels. gather.json keeps the original freeze's cost,
time and trace, and records the rebuild under "remerged"."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

os.environ.setdefault("STRINGER_NO_LANGFUSE", "1")

from stringer import paths  # noqa: E402
from stringer.events import fixture_events  # noqa: E402
from stringer.gather import clients, run, sides, store  # noqa: E402
from stringer.gather.queries import QuerySet  # noqa: E402
from stringer.outlets import OutletTable  # noqa: E402

KEEP_FROM_FREEZE = ("gathered_at", "credits_this_run", "seconds", "langfuse_trace_id", "gather_version")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="event short ids")
    a = ap.parse_args(argv)
    t = OutletTable.load()
    lenses = sides.fixture_lenses(t)
    frozen = {p.name for p in paths.STORIES.iterdir() if (p / "gather.json").exists()}
    events = [e for e in fixture_events() if e.id in frozen and (not a.only or e.short in a.only)]
    tv = clients.Tavily(offline=True)
    g = clients.Guardian(offline=True)
    cache = store.ArticleCache()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    failed = []
    for i, ev in enumerate(events, 1):
        old = store.read_meta(ev.id)
        before = len(store.read_articles(ev.id))
        try:
            run.gather_event(ev, lenses[ev.short], t, tv, g, queries=QuerySet(**old["queries"]),
                             window_days=2, cache=cache, wait_s=0)
        except FileNotFoundError as e:
            print(f"[{i}/{len(events)}] {ev.short} SKIPPED: {e}")
            failed.append(ev.short)
            continue
        meta = store.read_meta(ev.id)
        arts = store.read_articles(ev.id)
        for k in KEEP_FROM_FREEZE:
            if k in old:
                meta[k] = old[k]
        meta["remerged"] = {"at": now, "code": run.VERSION, "articles_before": before,
                            "guardian_cut": meta["log"].get("guardian_cut")}
        store.write_story(ev.id, arts, meta)
        print(f"[{i}/{len(events)}] {ev.short} {before} -> {len(arts)} articles "
              f"(Guardian cut {meta['log'].get('guardian_cut')})")
    print(f"{len(events) - len(failed)} stories rebuilt, {len(failed)} skipped; no API calls made")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
