"""What the website's pages read, built from the Gate's records and each run's saved files (module 9, Nov 27).

The four design pages (stringer_private/frontend_designs) were drawn on one made-up object each:
window.STRINGER_DEMO (front page and admin) and window.STRINGER_RUN (progress page). These functions build
the same shapes from real data, so the pages need few changes:

    front(site, visitor, user)      -> /api/site: the site's numbers, the 8 steps, finished videos, the events
    receipts(files, event, ticket)  -> what one video was made from: each side, outlets, claims checked
    run_view(doc, ...)              -> /api/progress: one run, live or finished, in the progress page's shape
    admin(site)                     -> /admin/api: reports, hidden videos, the log, money, every video

Article text never leaves the private bucket: receipts and hand-ons carry counts, outlet names, the
pipeline's own claims and lines, and short reasons. Events are by Monitor the Situation; every page says so.

Example: a finished video's receipt (from checked_story_file.json and script.json's sources_card):
    {"sides": {"kind": "two sides", "A": {"label": "Pro-Ukraine (Ukrainian outlets)", "articles": 2,
     "outlets": ["The Kyiv Independent", "Ukrainska Pravda"]}, ...}, "articles": 10, "claims": 60,
     "claimsBacked": 56, ...}"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from stringer import paths
from stringer import progress as P
from stringer.gate.core import safe_id

NY = ZoneInfo("America/New_York")
CREDIT = "Events by Monitor the Situation"
MINUTES_PER_VIDEO = "4–5"
REASON_LABELS = {"child_victim": "A child victim is shown or named", "wrong_facts": "Wrong facts",
                 "one_sided": "One-sided", "offensive": "Offensive", "other": "Something else"}
MODEL_NAMES = {"haiku-5-5": "Claude Haiku 5.5", "sonnet-5-5": "Claude Sonnet 5.5", "opus-5-5": "Claude Opus 5.5",
               "gpt-6.1-terra": "GPT-6.1 Terra", "gpt-oss-120b": "gpt-oss-120b",
               "deepseek-v4.1-flash": "DeepSeek V4.1 Flash", "glm-5.2": "GLM 5.2",
               "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite", "gemini-3.6-flash": "Gemini 3.6 Flash",
               "gemini-3.8-flash": "Gemini 3.8 Flash"}


def iso(t: dt.datetime | None = None) -> str:
    return (t or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds") \
        .replace("+00:00", "Z")


def parse(s) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def cut(s, n: int = 220) -> str:
    return P._cut(s, n)


def ago(t: dt.datetime | None, now: dt.datetime) -> str:
    if not t:
        return ""
    m = max(0, round((now - t).total_seconds() / 60))
    if m < 60:
        return f"{m} min ago"
    h = round(m / 60)
    return f"{h} h ago" if h < 24 else f"{round(h / 24)} d ago"


def confidence_word(v) -> str:
    c = num(v)
    if c is None:
        return ""
    return "Verified" if c >= 56 else "Developing" if c >= 31 else "Unconfirmed"


def clip_length(seconds) -> str:
    s = num(seconds)
    if not s:
        return ""
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def steps_list() -> list[dict]:
    total = sum(a["typical_s"] for a in P.AGENTS)
    return [dict(key=a["key"], label=a["label"], agent=a["agent"], does=a["does"],
                 share=round(a["typical_s"] / total, 4)) for a in P.AGENTS]


def last_ticket(rec: dict, want: tuple = ("done", "no_video", "failed")) -> str | None:
    """The ticket of an event's latest finished run (or its running one)."""
    if (rec.get("ticket") or {}).get("id") and rec.get("state") == "making":
        return rec["ticket"]["id"]
    for h in reversed(rec.get("history") or []):
        if h.get("ticket") and (h.get("outcome") in want):
            return h["ticket"]
    v = rec.get("video") or {}
    url = str(v.get("url") or "")
    if url.startswith("/media/videos/"):
        parts = url.split("/")
        if len(parts) >= 5:
            return parts[4]
    return None


# ---- a finished run's files (the private bucket on the site, the Mac's live story folder otherwise) ---------
MISS_S = 60          # a file that wasn't there is asked for again after this long (it may land later)


class Files:
    """read(event, ticket, name) -> the parsed file, or None.

    The bucket keeps one event's newest run at stories/<event>/ (scripts/run_job.py: a rerun overwrites it),
    with run.json naming its ticket; runs before Nov 27 kept a folder per ticket, stories/<event>/<ticket>/.
    A file is read from the event's folder only while run.json names the ticket asked for, so an older
    video's receipts never come from a newer run. Found files are kept; misses are asked again after MISS_S."""

    def __init__(self, bucket: str | None = None, local: Path | None = None, opener=None, clock=time.monotonic):
        self.bucket = bucket
        self.local = Path(local or paths.PRIVATE / "live" / "stories")
        self._open = opener
        self._clock = clock
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _get(self, name: str):
        """One object from the private bucket, parsed, or None."""
        from stringer import cloud
        r = (self._open or cloud.open_object)(self.bucket, name)
        try:
            if r.status_code != 200:
                return None
            body = b"".join(r.iter_content(256 * 1024)).decode("utf-8")
        finally:
            r.close()
        if name.endswith(".jsonl"):
            return [json.loads(x) for x in body.split("\n") if x.strip()]
        return json.loads(body)

    def _fetch(self, eid: str, tid: str | None, name: str):
        e = safe_id(eid)
        if self.bucket:
            note = self.read(eid, None, "run.json") if name != "run.json" else None
            if name == "run.json" or not tid or (note or {}).get("ticket") == tid:
                hit = self._get(f"stories/{e}/{name}")
                if hit is not None or not tid:
                    return hit
            return self._get(f"stories/{e}/{safe_id(tid)}/{name}")
        cands = ([self.local / e / safe_id(tid) / name] if tid else []) + [self.local / e / name]
        hit = next((p for p in cands if p.exists()), None)
        if hit is None:
            return None
        body = hit.read_text(encoding="utf-8")
        if name.endswith(".jsonl"):
            return [json.loads(x) for x in body.split("\n") if x.strip()]
        return json.loads(body)

    def read(self, eid: str, tid: str | None, name: str):
        k = (eid, tid, name)
        now = self._clock()
        with self._lock:
            hit = self._cache.get(k)
        # run.json changes with each rerun: kept like a miss, so a new run is seen within MISS_S
        if hit is not None and (hit[1] is not None and name != "run.json" or now - hit[0] < MISS_S):
            return hit[1]
        try:
            v = self._fetch(eid, tid, name)
        except Exception:
            return None                                  # not kept: try again next time
        with self._lock:
            self._cache[k] = (now, v)
        return v

    def reader(self, eid: str, tid: str | None):
        return lambda name: self.read(eid, tid, name)

    def local_media(self, eid: str, name: str) -> Path | None:
        p = self.local / safe_id(eid) / "video" / name
        return p if p.exists() else None


# ---- receipts: what a video was made from ------------------------------------------------------------------
def receipts(files: Files, eid: str, tid: str | None) -> dict | None:
    """The short summary the receipts rail shows. Built from checked_story_file.json and script.json's
    sources_card; no article text. None when the run's files aren't there."""
    sf = files.read(eid, tid, "checked_story_file.json")
    sc = files.read(eid, tid, "script.json") or {}
    if not sf:
        return None
    ev = sf.get("event") or {}
    card = sc.get("sources_card") or {}
    sources = sf.get("sources") or []
    counts = (sf.get("fact_check") or {}).get("counts") or {}
    claims = sf.get("claims") or []
    total = int(counts.get("claims") or len(claims))
    confirmed = int(counts.get("confirmed") or sum(1 for c in claims if c.get("status") == "confirmed"))
    say = int(counts.get("say_with_source") or sum(1 for c in claims if c.get("status") == "say_with_source"))
    dropped = int(counts.get("dropped") or sum(1 for c in claims if c.get("status") == "dropped"))
    read_n = int(card.get("read") or (sf.get("counts") or {}).get("articles_read") or len(sources))
    sides = sf.get("sides") or {}
    persp = {p.get("side_id"): p for p in sf.get("perspectives") or []}
    if sides.get("kind") == "two sides" and sides.get("A") and sides.get("B"):
        out_sides = {"kind": "two sides"}
        for k in ("A", "B"):
            s = sides[k]
            names = []
            for src in sources:
                if src.get("group") == k and src.get("outlet_name") and src["outlet_name"] not in names:
                    names.append(src["outlet_name"])
            p = persp.get(s.get("side_id")) or {}
            pts = [x.get("point") for x in p.get("points") or [] if x.get("point")]
            out_sides[k] = {"label": s.get("label") or s.get("side_id"), "articles": int(s.get("articles") or 0),
                            "outlets": names}
            out_sides["how" + k] = cut(pts[0], 240) if pts else (
                "No article from this side was read, so the video says the side had no coverage."
                if not s.get("articles") else "")
        out_sides["words"] = []                          # no step saves word pairs (map module 9: dropped)
    else:
        out_sides = {"kind": "no real divide",
                     "reason": cut(sides.get("reason") or "The outlets tell this story the same way.", 260)}
    dek = ""
    cap = str(sc.get("caption") or "").strip()
    if cap:
        dek = cut(cap.split(". ")[0].rstrip(".") + ".", 200)
    return {
        "event": {"title": ev.get("title"), "category": ev.get("category"), "subtype": ev.get("subtype"),
                  "country": ev.get("country"), "region": ev.get("region"), "place": ev.get("location_name"),
                  "lat": num(ev.get("lat")), "lng": num(ev.get("lng")), "url": ev.get("url"),
                  "severity": num(ev.get("severity")), "confidence": confidence_word(ev.get("confidence")),
                  "reports": num(ev.get("report_count"))},
        "title": cut(sc.get("title"), 140) or None, "dek": dek,
        "sides": out_sides, "articles": read_n,
        "outlets": len({s.get("outlet_name") or s.get("outlet") for s in sources}) or read_n,
        "elsewhere": int(card.get("elsewhere") or 0), "outletList": list(card.get("outlets") or [])[:16],
        "claims": total, "claimsBacked": confirmed + say, "confirmed": confirmed, "sayWho": say, "dropped": dropped,
        "aiMark": card.get("ai_mark") or f"Made with AI from {read_n} news articles",
        "words": sc.get("words"), "beats": len(sc.get("beats") or []),
    }


# ---- progress: one run, in the progress page's shape -------------------------------------------------------
def from_pipeline(pl: dict, read, ticket: str | None = None) -> dict:
    """A progress record for a run that only left pipeline.json (runs before live progress, or a recorded
    one): steps back to back from their seconds, hand-ons from the run's files, no call-by-call detail."""
    t, steps = 0.0, {}
    for k in P.KEYS:
        row = (pl.get("steps") or {}).get(k)
        if not row:
            continue
        sec = float(row.get("seconds") or 0)
        info = {a: b for a, b in row.items() if a not in ("seconds", "usd")}
        hv = dict(info)
        if k == "video":
            hv["duration_s"] = (pl.get("video") or {}).get("duration_s")
        steps[k] = {"t0": round(t, 2), "t1": round(t + sec, 2), "seconds": row.get("seconds"), "usd": row.get("usd"),
                    "info": info, "hands_on": P.summarize(k, read, hv)}
        t += sec
    outcome = pl.get("outcome") or "failed"
    return {"version": P.VERSION, "event": pl.get("event"), "ticket": ticket, "title": pl.get("title"),
            "started": pl.get("started"), "updated": pl.get("finished"), "state": outcome, "current": None,
            "steps": steps, "calls": [], "searches": [dict(q, step="gather", t=None) for q in P.searches_of(read)],
            "usd": pl.get("usd"), "model_calls": pl.get("model_calls"), "seconds": pl.get("seconds"),
            "why": pl.get("why"), "estimate_usd": (pl.get("estimate_after_gather") or {}).get("usd"),
            "from_pipeline_json": True}


def _call_row(c: dict) -> dict:
    return {"model": c.get("model"), "purpose": P.purpose(c.get("name")), "tokens_in": c.get("tokens_in") or 0,
            "tokens_out": c.get("tokens_out") or 0, "usd": c.get("usd") or 0.0, "seconds": c.get("seconds") or 0.0,
            "note": "the call failed" if c.get("error") else "", "t": c.get("t"), "error": bool(c.get("error"))}


def run_view(doc: dict, *, now: dt.datetime | None = None, by: str | None = None, event: dict | None = None,
             video: dict | None = None, estimate_usd: float | None = None, cap_usd: float = 5.0) -> dict:
    """The progress page's run object (the shape of _shared/run.js's `run`), from a progress record."""
    now = now or dt.datetime.now(dt.timezone.utc)
    started = parse(doc.get("started"))
    live = doc.get("state") == "running"
    elapsed = round((now - started).total_seconds(), 1) if started else None
    stepsd = doc.get("steps") or {}
    calls = doc.get("calls") or []
    searches = doc.get("searches") or []
    out_steps, timeline = [], []
    for a in P.AGENTS:
        k = a["key"]
        s = stepsd.get(k)
        row = dict(key=k, agent=a["agent"], label=a["label"], does=a["does"], typical_s=a["typical_s"])
        if not s:
            row.update(status="skipped" if not live else "waiting", seconds=None, usd=None, counts={}, calls=[],
                       searches=[], hands_on=None, start=None, end=None)
            out_steps.append(row)
            continue
        t0, t1 = s.get("t0"), s.get("t1")
        if t1 is None:
            st = "running" if live else ("stopped" if doc.get("state") in ("no_video", "failed") else "running")
        else:
            st = "done"
        mine = [_call_row(c) for c in calls if c.get("step") == k]
        qs = [{"name": q.get("name"), "query": q.get("query"), "results": q.get("results") or 0,
               "credits": q.get("credits") or 0, "seconds": 0, "note": q.get("note") or "", "t": q.get("t"),
               "source": q.get("source")} for q in searches if q.get("step") == k]
        counts = {x: y for x, y in (s.get("info") or {}).items() if not isinstance(y, (list, dict))}
        for x, y in (s.get("info") or {}).items():
            if x == "counts" and isinstance(y, dict):
                counts.update(y)
        ho = s.get("hands_on")
        row.update(status=st, seconds=s.get("seconds"), usd=s.get("usd"), counts=counts, info=s.get("info") or {},
                   calls=mine, searches=qs, hands_on=ho, start=t0, end=t1,
                   parts=(ho or {}).get("parts") if k == "video" else None)
        out_steps.append(row)
        timeline.append({"t": t0, "type": "step_start", "step": k})
        for c in mine:
            if c["t"] is not None:
                timeline.append({"t": c["t"], "type": "call", "step": k, "what": c["purpose"]})
        for q in qs:
            if q["t"] is not None:
                timeline.append({"t": q["t"], "type": "search", "step": k, "what": q["name"]})
        if t1 is not None:
            timeline.append({"t": t1, "type": "step_end", "step": k, "usd": s.get("usd")})
    # a run that stopped at the script: the last steps never ran
    if doc.get("state") in ("no_video", "failed"):
        for r in out_steps:
            if r["status"] == "waiting":
                r["status"] = "skipped"
    timeline.sort(key=lambda e: (e["t"] or 0, 0 if e["type"] == "step_start" else 2 if e["type"] == "step_end" else 1))
    secs = doc.get("seconds")
    if live:
        secs = elapsed
    used = {c["model"] for r in out_steps for c in r["calls"] if c.get("model")}
    return {
        "event": doc.get("title") or (event or {}).get("title") or "", "event_id": doc.get("event"),
        "ticket": doc.get("ticket"), "started": doc.get("started"), "updated": doc.get("updated"), "by": by,
        "estimate_usd": doc.get("estimate_usd") or estimate_usd, "cap_usd": cap_usd,
        "outcome": None if live else ("done" if doc.get("state") == "done" else doc.get("state")),
        "state": doc.get("state"), "live": live, "elapsed": elapsed, "current": doc.get("current"),
        "seconds": secs, "usd": doc.get("usd") or 0.0,
        "model_calls": doc.get("model_calls") if doc.get("model_calls") is not None else len(calls),
        "why": doc.get("why"), "steps": out_steps, "timeline": timeline,
        "calls_recorded": bool(calls) or not doc.get("from_pipeline_json"),
        "video": video, "event_meta": event or {},
        "models": {m: MODEL_NAMES.get(m, m) for m in used},
    }


def progress_pct(doc: dict | None, now: dt.datetime) -> tuple[str | None, float]:
    """(current step, percent) for the front page's bar, from the progress record and each step's usual time."""
    if not doc:
        return None, 0.0
    total = sum(a["typical_s"] for a in P.AGENTS)
    started = parse(doc.get("started"))
    elapsed = (now - started).total_seconds() if started else 0
    done_s, cur = 0.0, doc.get("current")
    for a in P.AGENTS:
        s = (doc.get("steps") or {}).get(a["key"])
        if s and s.get("t1") is not None:
            done_s += a["typical_s"]
        elif s and a["key"] == cur:
            ran = max(0.0, elapsed - float(s.get("t0") or 0))
            done_s += min(ran, a["typical_s"] * 0.95)
    return cur, round(min(99.0, 100 * done_s / total), 1)
