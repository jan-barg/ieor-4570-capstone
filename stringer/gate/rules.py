"""Is an event big and solid enough for a video? Plain code (settled Nov 23, map module 0).

An event qualifies when it is in one of the five categories, has severity 2 or more, confidence 31 or
more (Developing or Verified), and 7 or more news reports. Works on an events.Event (whose numbers are
strings, as the Archive gives them) or on a live-feed dict (numbers as numbers).

    failures(event)  -> ["reports"]       # the rules it fails, [] when it qualifies
    eligible(event)  -> False"""
from __future__ import annotations

import functools
import tomllib

from .. import paths

CONFIG = paths.CODE / "config" / "gate.toml"
RULES = ("category", "severity", "confidence", "reports")


@functools.lru_cache(maxsize=1)
def config() -> dict:
    return tomllib.loads(CONFIG.read_text())


def field(event, name: str):
    if isinstance(event, dict):
        return event.get(name)
    return getattr(event, name, None)


def number(v) -> float | None:
    """A count or score as a number; None when it is missing or not a number."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def failures(event, cfg: dict | None = None) -> list[str]:
    e = (cfg or config())["eligibility"]
    out = []
    if str(field(event, "category") or "").strip().lower() not in e["categories"]:
        out.append("category")
    checks = (("severity", e["min_severity"]), ("confidence", e["min_confidence"]),
              ("reports", e["min_reports"]))
    for rule, least in checks:
        v = number(field(event, "report_count" if rule == "reports" else rule))
        if v is None or v < least:
            out.append(rule)
    return out


def eligible(event, cfg: dict | None = None) -> bool:
    return not failures(event, cfg)
