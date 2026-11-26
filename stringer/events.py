"""Monitor the Situation events as Gather's input.

Fixture events come from the Archive (stringer_private/archive). Fields kept: what the map's
Story File 'event' block lists. Source: Monitor the Situation (monitor-the-situation.com), used
under its terms: /v1 API and Archive, attribution, no republishing."""
from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import paths

ATTRIBUTION = "Events by Monitor the Situation (monitor-the-situation.com)"


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass
class Event:
    id: str
    title: str
    summary: str
    category: str
    subtype: str
    severity: str
    confidence: str
    country: str
    location_name: str
    lat: str
    lng: str
    report_count: str
    start: datetime            # first_reported_at: the event's exact start
    created_at: str
    url: str
    source_urls: list[str] = field(default_factory=list)

    @property
    def short(self) -> str:
        return self.id[:8]

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["start"] = self.start.isoformat().replace("+00:00", "Z")
        return d


def from_archive_row(r: dict) -> Event:
    return Event(id=r["id"], title=r["title"], summary=r["summary"], category=r["category"],
                 subtype=r["subtype"], severity=r["severity"], confidence=r["confidence"],
                 country=r["country"], location_name=r["location_name"], lat=r["lat"], lng=r["lng"],
                 report_count=r["report_count"], start=parse_ts(r["first_reported_at"]),
                 created_at=r["created_at"], url=r["url"], source_urls=r["sources"].split())


def from_dict(d: dict) -> Event:
    """An Event from its saved form (Event.as_dict, as gather.json keeps it)."""
    f = {k: d.get(k, "") for k in Event.__dataclass_fields__}
    f["start"] = parse_ts(d["start"])
    f["source_urls"] = list(d.get("source_urls") or [])
    return Event(**f)


def from_live(e: dict) -> Event:
    """An Event from the live /v1/events feed (or a saved snapshot of it). The feed has no
    first_reported_at; the first source's time is the same thing (the Archive shows they match), so
    the start is the earliest source time, else created_at."""
    srcs = e.get("sources") or []
    urls = [s["url"] if isinstance(s, dict) else str(s) for s in srcs]
    times = sorted(parse_ts(s.get("published_at")) for s in srcs if isinstance(s, dict) and s.get("published_at"))
    start = times[0] if times else parse_ts(e.get("created_at"))
    s = lambda k: "" if e.get(k) is None else str(e.get(k))
    return Event(id=s("id"), title=s("title"), summary=s("summary"), category=s("category"), subtype=s("subtype"),
                 severity=s("severity"), confidence=s("confidence"), country=s("country"),
                 location_name=s("location_name"), lat=s("lat"), lng=s("lng"), report_count=s("report_count"),
                 start=start, created_at=s("created_at"), url=s("url"), source_urls=urls)


def load_archive(ids: set[str]) -> dict[str, Event]:
    """Events by full id or 8-character short id."""
    csv.field_size_limit(10 ** 9)
    shorts = {i[:8] for i in ids}
    out = {}
    with gzip.open(paths.ARCHIVE_GZ, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"][:8] in shorts:
                out[r["id"][:8]] = from_archive_row(r)
    return out


def fixture_rows(sets=("pipeline", "chain")) -> list[dict]:
    with open(paths.FIXTURES_CSV, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["set"] in sets]


def fixture_events(sets=("pipeline", "chain")) -> list[Event]:
    rows = fixture_rows(sets)
    ev = load_archive({r["id"] for r in rows})
    missing = [r["id"] for r in rows if r["id"][:8] not in ev]
    if missing:
        raise KeyError(f"fixture events not in the Archive: {missing}")
    return [ev[r["id"][:8]] for r in rows]
