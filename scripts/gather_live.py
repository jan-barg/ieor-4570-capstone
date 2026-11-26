"""Gather a live event: choose its sides (stringer/lens.py), then run Gather, with no hand-made lens file.

    python -m scripts.gather_live --list                        # live events with 5+ reports in the newest snapshot (free)
    python -m scripts.gather_live --event <id> --dry-run        # the sides (one model call, a fraction of a cent) + credit estimate
    python -m scripts.gather_live --event <id> --sides code     # the plain-code rule chooses the sides (free)
    python -m scripts.gather_live --event <id>                  # sides + Gather (Tavily credits; capped by --limit)

The event comes from the live feed's saved snapshots (stringer_private/live_snapshots/, newest
first; an 8-character short id is enough) or from --event-json, one event object as the
/v1/events feed returns it. Live stories are kept apart from the frozen test stories:
stringer_private/live/stories/<event id>/ (gather.json keeps the sides, why, and code's flags) and
live/raw/ for Tavily's and the Guardian's responses. New sides the model built are added to
stringer_private/outlets/proposed_sides.jsonl for Jan to review; side_lists.csv is never changed.
Then: same-story filter, `python -m scripts.balance_followup --stories-dir <live/stories>`, and the pick."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from stringer import lens, models, paths
from stringer.events import ATTRIBUTION, from_live
from stringer.gather import clients, run, store
from stringer.outlets import OutletTable

LIVE = paths.PRIVATE / "live"
SNAPSHOTS = paths.PRIVATE / "live_snapshots"
SAFETY = 20


def snapshot_files(d: Path) -> list[Path]:
    return sorted(d.glob("*.json.gz"), reverse=True)


def find_event(eid: str, d: Path) -> tuple[dict, Path] | tuple[None, None]:
    for f in snapshot_files(d):
        try:
            evs = json.load(gzip.open(f)).get("events") or []
        except (OSError, json.JSONDecodeError):
            continue
        for e in evs:
            if str(e.get("id", "")).startswith(eid):
                return e, f
    return None, None


def list_events(d: Path, min_reports: int = 5) -> int:
    files = snapshot_files(d)
    if not files:
        print(f"no snapshots in {d}")
        return 1
    evs = json.load(gzip.open(files[0])).get("events") or []
    rows = sorted((e for e in evs if int(e.get("report_count") or 0) >= min_reports),
                  key=lambda e: -int(e.get("report_count") or 0))
    print(f"{files[0].name}: {len(rows)} events with {min_reports}+ reports ({ATTRIBUTION})")
    for e in rows:
        print(f"  {e['id'][:8]}  {e.get('report_count'):>3}  {str(e.get('country') or '')[:18]:18} {e.get('title', '')[:70]}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list live events in the newest snapshot")
    ap.add_argument("--event", help="event id (or its first 8 characters)")
    ap.add_argument("--event-json", help="a file with one event object from the /v1/events feed")
    ap.add_argument("--snapshots", default=str(SNAPSHOTS))
    ap.add_argument("--sides", choices=["model", "code"], default="model",
                    help="who chooses the sides: the lens step's model (config/models.toml) or the code rule")
    ap.add_argument("--model", help="model alias for the sides (default: the lens step's model in config/models.toml)")
    ap.add_argument("--writer", choices=["model", "template"], default="model", help="who writes the searches")
    ap.add_argument("--dry-run", action="store_true", help="choose the sides and estimate credits; no searches")
    ap.add_argument("--limit", type=float, default=20, help="most Tavily credits this run may spend")
    ap.add_argument("--window-days", type=int, default=2)
    a = ap.parse_args(argv)
    if a.list:
        return list_events(Path(a.snapshots))
    if a.event_json:
        raw_ev, src = json.loads(Path(a.event_json).read_text(encoding="utf-8")), Path(a.event_json)
    elif a.event:
        raw_ev, src = find_event(a.event, Path(a.snapshots))
        if raw_ev is None:
            sys.exit(f"event {a.event} is in none of the snapshots in {a.snapshots}")
    else:
        ap.error("give --event, --event-json or --list")
    ev = from_live(raw_ev)
    print(f"{ev.short} {ev.title} ({ev.country or 'no country'}; from {src.name})")

    # live stories and their raw responses stay out of the frozen test set
    paths.STORIES = LIVE / "stories"
    paths.RAW = LIVE / "raw"
    t = OutletTable.load()
    complete = lens.live_complete("lens", metadata={"event": ev.id}) if a.sides == "model" else None
    model = (a.model or models.model_for("lens")) if complete else ""
    if complete and a.model:
        complete = lens.live_complete("lens", metadata={"event": ev.id}, model=a.model)
    chosen, rec = lens.choose(ev, t, complete, model=model)
    print(f"sides ({rec['chosen_by']}): {chosen.kind}")
    for s in chosen.sides:
        print(f"  {s.side_id}: {s.label} ({len(s.outlet_ids)} outlets: {', '.join(s.outlet_ids[:8])}"
              f"{'…' if len(s.outlet_ids) > 8 else ''})")
    if chosen.local:
        print(f"  local press {chosen.local_code}: {len(chosen.local.outlet_ids)} outlets")
    print(f"  why: {chosen.reason}")
    for f in chosen.flags:
        print(f"  flag: {f}")

    from scripts.freeze_fixtures import estimate          # same estimate the freeze used
    cache = store.ArticleCache()
    est = estimate(ev, chosen, t, cache, a.window_days)
    print(f"Gather: {est['searches']} searches, {est['new_searches']} new, {est['extract_links']} own links to read; "
          f"about {est['credits_with_retries']:.0f} credits ({est['worst_case']} worst case)")
    if a.dry_run:
        return 0
    u = clients.Tavily().usage()
    left = (u["limit"] - u["used"]) if u["limit"] is not None and u["used"] is not None else None
    cap = a.limit if left is None else min(a.limit, left - SAFETY)
    if est["credits_with_retries"] > cap:
        sys.exit(f"STOP: about {est['credits_with_retries']:.0f} credits is over the cap ({cap:.0f}). Ask Jan first.")
    n_new = lens.record_new_sides(ev, chosen)
    if n_new:
        print(f"{n_new} new side(s) saved for review in outlets/proposed_sides.jsonl")
    (paths.RAW).mkdir(parents=True, exist_ok=True)
    tv = clients.Tavily(ledger=clients.CreditLedger(limit=cap), raw_dir=str(paths.RAW))
    g = clients.Guardian(raw_dir=str(paths.RAW))
    meta = run.gather_event(ev, chosen, t, tv, g, writer=a.writer, window_days=a.window_days, cache=cache)
    d = store.story_dir(ev.id)
    (d / "lens.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    c = meta["counts"]
    print(f"gathered {c['articles']} articles ({c['roles'].get('new_coverage', 0)} new coverage, "
          f"{c['text_status'].get('full', 0)} full text), {meta['credits_this_run']} credits, {meta['seconds']} s -> {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
