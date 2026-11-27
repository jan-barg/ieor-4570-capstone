"""Jan's admin commands for the Gate (module 0) until the site's admin panel exists, and the same
calls the panel will make. Reads and writes the store GATE_STORE points at (default
stringer_private/gate/; gs://bucket/prefix on the site).

    python -m scripts.gate_admin status                      # today's count, videos being made, searches
    python -m scripts.gate_admin reports [--event ID]        # every report with its note, newest first
    python -m scripts.gate_admin hidden                      # videos hidden right now (waiting for you)
    python -m scripts.gate_admin log [--day 2026-12-09]      # reports, hides, restores, starts, outcomes
    python -m scripts.gate_admin hide ID --note "why"        # take a video down now
    python -m scripts.gate_admin restore ID [--keep-up]      # show it again (--keep-up: reports no longer hide it)
    python -m scripts.gate_admin remake ID                   # let an event be made again"""
from __future__ import annotations

import argparse
import json

from stringer.gate import Gate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("hidden")
    r = sub.add_parser("reports")
    r.add_argument("--event")
    lg = sub.add_parser("log")
    lg.add_argument("--day")
    for name in ("hide", "restore", "remake"):
        p = sub.add_parser(name)
        p.add_argument("event")
        p.add_argument("--note", default="")
        p.add_argument("--by", default="jan")
        if name == "restore":
            p.add_argument("--keep-up", action="store_true")
    a = ap.parse_args(argv)
    g = Gate(complete=None, model="")
    if a.cmd == "status":
        out = g.status()
    elif a.cmd == "hidden":
        out = [{k: r.get(k) for k in ("id", "title", "hidden_by", "hidden_at", "reports", "video")} for r in g.hidden()]
    elif a.cmd == "reports":
        out = g.reports(a.event)
    elif a.cmd == "log":
        out = g.log(a.day)
    elif a.cmd == "hide":
        out = g.take_down(a.event, by=a.by, note=a.note)
    elif a.cmd == "restore":
        out = g.restore(a.event, by=a.by, note=a.note, keep_up=a.keep_up)
    else:
        out = g.remake(a.event, by=a.by, note=a.note)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
