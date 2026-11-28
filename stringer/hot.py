"""How "hot" a story is right now, for the front page's order (module 9; formula drafted Nov 23, built Nov 27).

Plain code, no model. For one event from the live feed:

    hot = [log2(1 + reports) + log2(1 + reports in the last 6 hours)]
          x (1 + 0.25 x (severity - 2))
          x 0.5 ^ (hours since the last report / 4)

    size       the log of the report count, so an 80-report story doesn't stay on top for days
    momentum   reports in the last 6 hours. The feed lists every report with its time (`sources`,
               `published_at`), so this needs no saved history (Nov 27: in the saved snapshots the list's
               length matched report_count for 79% of events, and was off by 1 or 2 for most of the rest)
    severity   a small bump only: +25% a level above 2. Multiplying by severity filled the list with war
    freshness  halves every 4 hours since the newest report (else updated_at, else created_at). 4 hours, not the
               draft's 8 (Jan, Nov 27): MTS's own rhythm. A report follows the last after 36 min (median) and 90%
               of gaps are under 4 h, so a story quiet that long is probably over. Replaying the saved feed log,
               the half-life hardly changes which 10 show (96-98% the same from 2 to 24 h; new events, about one an
               hour, set the pace); it decides which story is on top (4 h vs 8 h: another #1 at 21% of moments)

Example (made up): 12 reports, 5 of them in the last 6 hours, severity 3, newest report 2 hours ago:
    [log2(13) + log2(6)] x 1.25 x 0.5^(2/4) = (3.70 + 2.58) x 1.25 x 0.71 = 5.55

Then the variety rule, in rank(): one slot per story chain (its newest event), and at most 3 events from one
country in the list. Jan, Nov 27: ship this formula with no hand-ranking eval; code checks the variety rule
and that no story shows twice, and frames of the ranking at a few saved moments go to Jan to look over."""
from __future__ import annotations

import datetime as dt
import math

from .events import parse_ts

MOMENTUM_H = 6.0
HALF_LIFE_H = 4.0         # Jan, Nov 27 (was 8 in the draft)
SEVERITY_STEP = 0.25
TOP = 10
PER_COUNTRY = 3


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def report_times(e: dict, now: dt.datetime) -> list[dt.datetime]:
    """The times of the event's reports up to now, oldest first."""
    out = []
    for s in e.get("sources") or []:
        t = parse_ts(s.get("published_at")) if isinstance(s, dict) else None
        if t is not None and t <= now:
            out.append(t)
    return sorted(out)


def last_report(e: dict, now: dt.datetime) -> dt.datetime | None:
    times = report_times(e, now)
    if times:
        return times[-1]
    for k in ("updated_at", "created_at"):
        t = parse_ts(e.get(k))
        if t is not None:
            return min(t, now)
    return None


def score(e: dict, now: dt.datetime) -> dict:
    """{"hot", "size", "momentum", "recent", "severity_x", "freshness", "hours"} for one feed event."""
    reports = max(0, int(_num(e.get("report_count"))))
    since = now - dt.timedelta(hours=MOMENTUM_H)
    recent = sum(1 for t in report_times(e, now) if t > since)
    size, momentum = math.log2(1 + reports), math.log2(1 + recent)
    sev = max(0.5, 1 + SEVERITY_STEP * (_num(e.get("severity"), 2) - 2))
    last = last_report(e, now)
    hours = max(0.0, (now - last).total_seconds() / 3600) if last else None
    fresh = 0.5 ** (hours / HALF_LIFE_H) if hours is not None else 0.0
    return dict(hot=round((size + momentum) * sev * fresh, 4), size=round(size, 3), momentum=round(momentum, 3),
                recent=recent, severity_x=round(sev, 3), freshness=round(fresh, 4),
                hours=round(hours, 2) if hours is not None else None)


def rank(items: list, now: dt.datetime, *, event_of=lambda x: x, chain_of=None, top: int | None = TOP,
         per_country: int | None = PER_COUNTRY, drop: bool = True, keep=None) -> list:
    """`items` by hot score, highest first, with the variety rule.

    event_of(item) gives the feed event to score; chain_of(item) the item's story chain (None: its own).
    One item per chain: the chain's newest event (by start), wherever its score puts it. Past `per_country`
    items from one country, drop=True leaves the rest out (the event list) and drop=False moves them after
    everything else, in score order (the video feed, which keeps every video). `top` cuts the list; items
    keep(item) says yes to are kept even when the rules would leave them out (a video being made)."""
    def start(x):
        e = event_of(x) or {}
        times = report_times(e, now)
        return times[0] if times else (parse_ts(e.get("created_at")) or now)

    scored = [(x, score(event_of(x) or {}, now)["hot"]) for x in items]
    newest: dict = {}
    for x, _ in scored:
        c = chain_of(x) if chain_of else None
        if c and (c not in newest or start(x) > start(newest[c])):
            newest[c] = x
    first, later = [], []
    per: dict = {}
    for x, h in sorted(scored, key=lambda p: -p[1]):
        c = chain_of(x) if chain_of else None
        kept = bool(keep and keep(x))
        if c and newest.get(c) is not x and not kept:
            continue
        country = str((event_of(x) or {}).get("country") or "").strip().lower()
        n = per.get(country, 0)
        if per_country is not None and country and n >= per_country and not kept:
            if not drop:
                later.append(x)
            continue
        per[country] = n + 1
        first.append(x)
    ranked = first + later
    if top is None:
        return ranked
    cut = ranked[:top]
    if keep:
        cut += [x for x in ranked[top:] if keep(x)]
    return cut
