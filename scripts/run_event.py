"""Make one video from a live event: the Gate, then modules 1-8 (stringer/pipeline.py), with each step timed.

    python -m scripts.run_event --list                 # eligible events in the live feed now (free)
    python -m scripts.run_event 1e965a70               # through the Gate, then the whole pipeline (paid)
    python -m scripts.run_event 1e965a70 --snapshot    # take the event from the newest saved poll instead
    python -m scripts.run_event 1e965a70 --no-gate     # skip the Gate (testing only: no limits, no records)

Paid: about $0.66 in model calls, about 7 Tavily credits and about 250 ElevenLabs credits a video
(Jan approved 3-5 timing runs on Nov 27). The Gate keeps its records in GATE_STORE (default
stringer_private/gate/); the story folder is stringer_private/live/stories/<event id>/, the run's
timings are in stringer_private/runs/pipeline-<time>.json and the story's pipeline.json.

Each event counts as its own visitor here (`cli:<event>`), so a timing session isn't held to the
site's 3-an-hour visitor limit; the daily cap and the 3-at-once limit still apply."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from stringer import feed, paths, pipeline
from stringer.gate import Gate, TooCostly
from stringer.gate import rules


def list_events(events: list[dict]) -> int:
    ok = sorted((e for e in events if rules.eligible(e)), key=lambda e: -(rules.number(e.get("report_count")) or 0))
    print(f"{len(ok)} of {len(events)} events pass the eligibility rules (the content check runs at the click)")
    for e in ok:
        print(f"  {str(e['id'])[:8]}  {int(rules.number(e.get('report_count')) or 0):>3} reports  "
              f"sev {e.get('severity')}  {str(e.get('category'))[:12]:12} {str(e.get('title'))[:80]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("event", nargs="?", help="event id, or its first characters")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--snapshot", action="store_true", help="use the newest saved poll, not the live feed")
    ap.add_argument("--no-gate", action="store_true", help="skip the Gate (testing only)")
    ap.add_argument("--no-render", action="store_true", help="stop after the render plan (no MP4)")
    a = ap.parse_args(argv)
    if a.snapshot:
        events, src = feed.newest_snapshot()
        print(f"{len(events)} events from {src.name if src else 'no snapshot'}")
    else:
        events = feed.fetch()
        print(f"{len(events)} events in the live feed")
    if a.list or not a.event:
        return list_events(events)
    raw = feed.find(a.event, events)
    if raw is None:
        sys.exit(f"no single event matches {a.event}")
    print(f"{str(raw['id'])[:8]} {raw.get('title')}")

    ticket = None
    if not a.no_gate:
        g = Gate()
        d = g.start(raw, visitor=f"cli:{str(raw['id'])[:8]}")
        if not d.ok:
            print(f"Gate: {d.code}: {d.message}" + (f" ({d.detail})" if getattr(d, "detail", "") else ""))
            return 1
        ticket = d.ticket
        print(f"Gate: go (ticket {ticket.id}, estimate ${ticket.estimate_usd:.2f})")
    try:
        rec = pipeline.run(raw, ticket, render=not a.no_render)
    except TooCostly as e:
        if ticket:
            ticket.finish(no_video=f"too costly: {e}")
        print(f"no video: too costly: {e}")
        return 1
    except Exception as e:
        if ticket:
            ticket.finish(error=repr(e))
        raise
    if ticket:
        if rec["outcome"] == "done":
            ticket.finish(video=rec["video"])
        else:
            ticket.finish(no_video=rec["why"])
    print(f"{rec['outcome']}{': ' + rec['why'] if rec.get('why') else ''}  {rec['seconds']:.0f} s in all, "
          f"${rec['usd']:.3f}, {rec['model_calls']} model calls")
    for name, s in rec["steps"].items():
        print(f"  {name:<12} {s['seconds']:>6.1f} s  ${s['usd']:.4f}")
    if rec.get("video"):
        print(f"video: {rec['video']['mp4']}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths.RUNS.mkdir(parents=True, exist_ok=True)
    (paths.RUNS / f"pipeline-{stamp}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
