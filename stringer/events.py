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
