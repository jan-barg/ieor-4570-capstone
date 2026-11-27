"""The live Monitor the Situation feed: the events a video can start from.

    from stringer import feed
    events = feed.fetch()                 # one GET of /v1/events (MTS_API_KEY, or the Mac's Keychain)
    ev = feed.find("1e965a70", events)    # an event by its id or the id's first characters

Events by Monitor the Situation (monitor-the-situation.com). Its terms forbid republishing the data,
so what this returns stays in memory or in stringer_private/, never in the repo.
`newest_snapshot()` reads the live logger's last saved poll instead, for offline runs."""
from __future__ import annotations

import gzip
import json
import urllib.request
from pathlib import Path

from . import keys, paths

URL = "https://monitor-the-situation.com/v1/events"
USER_AGENT = "stringer/1.0"
KEY_NAMES = ("mts_api_key", "mts-api")
SNAPSHOTS = paths.PRIVATE / "live_snapshots"


def _events_of(d) -> list[dict]:
    return list(d.get("events") or []) if isinstance(d, dict) else list(d or [])


def api_key() -> str:
    """MTS_API_KEY from the environment or stringer/.env, else the Mac's Keychain under either name the
    live logger used ("mts_api_key", or "mts-api" from its first setup)."""
    for name in KEY_NAMES:
        if keys.has(name):
            return keys.get(name)
    raise keys.MissingKey(f"MTS_API_KEY not set: add it to {keys.ENV_FILE}")


def fetch(timeout: int = 60) -> list[dict]:
    """The feed now, as a list of event dicts (the shape events.from_live and the Gate read)."""
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {api_key()}", "Accept": "application/json",
        "Accept-Encoding": "gzip", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body, enc = r.read(), (r.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        body = gzip.decompress(body)
    return _events_of(json.loads(body))


def newest_snapshot(folder: Path | None = None) -> tuple[list[dict], Path | None]:
    """The events in the live logger's newest saved poll, and that file (none saved: [], None)."""
    files = sorted(Path(folder or SNAPSHOTS).glob("*.json*"))
    if not files:
        return [], None
    raw = files[-1].read_bytes()
    if files[-1].suffix == ".gz":
        raw = gzip.decompress(raw)
    return _events_of(json.loads(raw)), files[-1]


def find(event_id: str, events: list[dict]) -> dict | None:
    """The one event whose id is `event_id` or starts with it; None when none or several match."""
    hits = [e for e in events if str(e.get("id", "")).startswith(event_id)]
    return hits[0] if len(hits) == 1 else None
