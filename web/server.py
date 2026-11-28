"""Stringer's website (module 9, Nov 27): the four pages Jan picked, on the Gate's records and each run's files.

Standard library only. Pages (from stringer_private/frontend_designs; the look gets tweaked later):
    GET  /                    the landing page: how a video is made, one map (direction 3, the atlas)
    GET  /feed                the front page: finished videos, down for the next story; the events (direction 2)
    GET  /progress?event=<id> one video being made, agent by agent, live (or how a finished run went)
    GET  /admin               the review desk: reports, hidden videos, the log, money (needs GATE_ADMIN_TOKEN)
JSON the pages read (the shapes of the designs' window.STRINGER_DEMO and window.STRINGER_RUN; web/data.py):
    GET  /api/site            the site's numbers, the 8 steps, finished videos with their receipts, the events
    GET  /api/progress?event=<id>   one run; the page asks every 2 to 3 seconds while it runs
    GET  /api/receipts?event=<id>   what one video was made from (no article text)
    POST /make?event=<id>     the click: the Gate decides; on go, the event is saved and the job starts
    POST /report              {"event", "reason", "note"}: the Report link; the first report hides the video
    GET  /admin/api           everything the desk shows      } both need the header X-Admin-Token:
    POST /admin/api/<action>  take_down, restore, remake,    } <GATE_ADMIN_TOKEN>
                              pause, open ({"event", "note", "keep_up"})
    GET  /status?event=<id>   what a visitor may see of one event (the Gate's view; the deploy test page's poll)
    GET  /media/videos/<event>/<ticket>/<file>   a finished video, poster or captions, streamed from the
                              private video bucket (with Range, so the player can seek); on the Mac, from the
                              run's own folder
    GET  /static/...          the pages' code, styles and fonts (gzipped when the browser takes it)
    GET  /healthz             "ok"

On Cloud Run the site sits behind Identity-Aware Proxy: only signed-in Columbia accounts get in (Jan,
Nov 27), and the account IAP names is the visitor for the Gate's per-visitor limits (a cookie otherwise).
STRINGER_JOB names the Cloud Run job that makes a video (scripts/run_job.py). Without it, the video is made
in this process, on a thread.

On the Mac:  python -m web.server --port 8080            (the live feed and the local Gate store)
             python -m web.server --feed events.json --no-model    (a saved feed, keyword content rule)"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from stringer import cloud, feed, hot, paths, pipeline
from stringer import progress as prog
from stringer.gate import MESSAGES, Gate, TooCostly, VideoOverBudget
from stringer.gate.core import safe_id

from . import data as D
from . import geo

REFRESH_S = 300
MEDIA_PASS_S = 3600              # how long a hidden video's link on the review desk works
RETRY_S = 60
FIRST_WAIT_S = 90               # with no list yet, a request waits this long for the one being built
COOKIE = "stringer_visitor"
IAP_USER = "X-Goog-Authenticated-User-Id"
IAP_EMAIL = "X-Goog-Authenticated-User-Email"
IAP_SIGN_OUT = "/_gcp_iap/clear_login_cookie"
ADMIN_HEADER = "X-Admin-Token"
MEDIA = re.compile(r"videos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(video\.mp4|poster\.jpg|captions\.vtt|captions\.srt)")
WEB = Path(__file__).resolve().parent
STATIC = WEB / "static"
FONTS = paths.CODE / "render" / "public" / "fonts"
PAGES = {"/": "atlas/landing.html", "/feed": "feed/front.html", "/progress": "feed/progress.html",
         "/admin": "feed/admin.html"}
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".json": "application/json",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg"}
SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]+")


class Site:
    def __init__(self, gate: Gate | None = None, fetch=feed.fetch, files: D.Files | None = None,
                 admin_token: str | None = None):
        self.gate = gate or Gate()
        self.fetch = fetch
        self.files = files or D.Files(os.environ.get("STRINGER_PRIVATE_BUCKET") or None)
        self.admin_token = admin_token if admin_token is not None else os.environ.get("GATE_ADMIN_TOKEN", "")
        self.events: dict[str, dict] = {}
        self.listings: list = []
        self.records: dict[str, dict] = {}          # every event the Gate has a record of (for finished videos)
        self.updated = 0.0
        self.error = ""
        self.tried = 0.0
        self.lock = threading.Lock()
        self.refreshing = threading.Lock()
        self._receipts: dict = {}
        self._runs: dict = {}                       # finished runs' progress views never change
        self._raws: dict = {}                       # raw events read from the store (saved at the click)
        self._geo: tuple[bytes, bytes] | None = None
        self._geo_lock = threading.Lock()
        self._watch: dict[str, tuple[float, bool]] = {}   # /media answers, kept 30 s (a player asks in pieces)

    # ---- the list, refreshed from the feed every few minutes ---------------------------------------------
    def refresh(self) -> None:
        try:
            events = self.fetch()
            listings = self.gate.screen(events)
            with self.lock:
                self.events = {str(e["id"]): e for e in events}
                self.listings, self.updated, self.error = listings, time.time(), ""
        except Exception as e:                       # keep the last good list
            self.error = repr(e)[:300]
        self.load_records()

    def load_records(self) -> None:
        """Every event record in the store, read side by side (the finished videos live here)."""
        try:
            keys = self.gate.store.list("events/")
            with ThreadPoolExecutor(max_workers=8) as ex:
                recs = list(ex.map(lambda k: self.gate.store.get(k)[0], keys))
            with self.lock:
                self.records = {str(r.get("id")): r for r in recs if r and r.get("id")}
        except Exception as e:
            self.error = self.error or repr(e)[:300]

    def fresh(self, wait: bool = True) -> None:
        """Refreshes the list when it is older than REFRESH_S (after a failure, at most once a minute), in the
        calling thread. On Cloud Run that is a request's thread on purpose: an instance gets CPU only while it
        answers a request, so a refresh left to a background thread crawls (Nov 27: the first list after a
        deploy was still empty after 5 minutes, and came in 30 s once requests kept arriving).
        Other requests meanwhile show the last list. With no list yet, a request (wait=True) waits for the
        refresh in progress, up to FIRST_WAIT_S, which also keeps the instance's CPU on for it."""
        now = time.time()
        if now - self.updated < REFRESH_S:
            return
        if self.refreshing.acquire(blocking=False):
            try:
                if now - self.tried < RETRY_S:       # a failed try a moment ago: show the last list
                    return
                self.tried = now
                self.refresh()
            finally:
                self.refreshing.release()
        elif wait and not self.updated:              # the first list is being built: wait for it
            if self.refreshing.acquire(timeout=FIRST_WAIT_S):
                self.refreshing.release()

    def keep_fresh(self) -> None:
        """For a site on the Mac. Not started on Cloud Run (K_SERVICE set), where requests refresh the list."""
        while True:
            self.fresh()
            time.sleep(RETRY_S)

    def get_record(self, event_id: str) -> dict:
        rec, _ = self.gate.store.get(f"events/{safe_id(event_id)}.json")
        if rec:
            with self.lock:
                self.records[str(rec.get("id") or event_id)] = rec
        return rec or {}

    def record(self, event_id: str) -> dict:
        """What a visitor may see of one event: the Gate's view (gate.view), never the raw record, which says
        "making" after a run has crashed and still holds a taken-down video."""
        eid = safe_id(event_id)
        v = self.gate.view(eid)
        state = {"has_video": "done", "ready": None}.get(v["state"], v["state"])
        video = self.video_urls(eid, self.get_record(eid)) if v["state"] == "has_video" else None
        return {"state": state, "video": video, "why": v.get("reason"), "failed": bool(v.get("failed"))}

    def may_watch(self, name: str) -> bool:
        """May /media serve videos/<event>/<ticket>/<file>? Only the files of the video the event shows now
        (gate.may_watch), remembered 30 s. Runs made on the Mac saved file paths, not /media addresses: there
        the address is the one video_urls gives."""
        now = time.time()
        hit = self._watch.get(name)
        if hit and now - hit[0] < 30:
            return hit[1]
        ok = self.gate.may_watch(name)
        if not ok and not os.environ.get("STRINGER_VIDEO_BUCKET"):
            eid = name.split("/")[1]
            if self.gate.view(eid)["state"] == "has_video":
                urls = self.video_urls(eid, self.get_record(eid)) or {}
                folder = "/media/" + name.rsplit("/", 1)[0] + "/"
                ok = str(urls.get("src") or "").startswith(folder)
        if len(self._watch) > 500:
            self._watch.clear()
        self._watch[name] = (now, ok)
        return ok

    def forget_watch(self, eid: str) -> None:
        """A video was hidden or changed here: stop serving it at once on this machine."""
        self._watch = {k: v for k, v in self._watch.items() if k.split("/")[1:2] != [eid]}

    # ---- the click -----------------------------------------------------------------------------------------
    def make(self, event_id: str, visitor: str) -> dict:
        with self.lock:
            raw = self.events.get(event_id)
        if raw is None:
            return {"ok": False, "code": "unknown", "message": "That event isn't in the list any more."}
        d = self.gate.start(raw, visitor)
        if not d.ok:
            return {"ok": False, "code": d.code, "message": d.message, "video": d.video,
                    "retry_after_s": d.retry_after_s}
        try:
            self.gate.store.update(f"raw_events/{safe_id(event_id)}.json", lambda cur: (raw, None))
            if os.environ.get("STRINGER_JOB"):
                cloud.start_job(cloud.setting("STRINGER_PROJECT"), cloud.setting("STRINGER_REGION", "us-east1"),
                                cloud.setting("STRINGER_JOB"), [event_id])
            else:
                threading.Thread(target=self._make_here, args=(raw, d.ticket), daemon=True).start()
        except Exception as e:
            # The video never began. Give the click back (the claim, the slot, the day's and the visitor's
            # count), or the event would show "being made" for 20 minutes with nothing running.
            print(f"could not start the video for {safe_id(event_id)}: {e!r}"[:300])
            d.ticket.cancel(f"the job could not be started: {e!r}")
            self.get_record(event_id)
            return {"ok": False, "code": "start_failed",
                    "message": "The video couldn't start just now. Please try again in a minute."}
        self.get_record(event_id)
        return {"ok": True, "code": "making", "message": "Making the video. This takes a few minutes.",
                "ticket": d.ticket.id, "progress": f"/progress?event={event_id}"}

    def _make_here(self, raw: dict, ticket) -> None:
        try:
            rec = pipeline.run(raw, ticket)
        except (TooCostly, VideoOverBudget) as e:
            ticket.finish(no_video=f"too costly: {e}")
            return
        except Exception as e:
            ticket.finish(error=repr(e))
            return
        if rec["outcome"] == "done":
            ticket.finish(video=dict(rec["video"], seconds=rec["seconds"], usd=rec["usd"]))
        elif rec["outcome"] == "planned":
            ticket.cancel("a plan-only run")
        else:
            ticket.finish(no_video=rec["why"])

    # ---- the report link -----------------------------------------------------------------------------------
    def report(self, event_id: str, visitor: str, reason: str, note: str) -> dict:
        try:
            eid = safe_id(event_id)
        except ValueError:
            return {"ok": False, "message": "That video isn't here any more."}
        rec = self.get_record(eid)
        if rec.get("state") != "done":
            return {"ok": False, "message": "You can report a video once it's up."}
        out = self.gate.report(eid, visitor, reason, note)
        if out.get("hidden"):
            self.forget_watch(eid)
        self.get_record(eid)
        return out

    # ---- the pieces the pages show -------------------------------------------------------------------------
    def video_urls(self, eid: str, rec: dict) -> dict | None:
        """The video's addresses on this site. Runs made on the Mac saved file paths, so they get the same
        /media/... addresses, which the Mac's /media serves from the run's folder."""
        v = rec.get("video") if rec else None
        if not v:
            return None
        out = {"src": v.get("url"), "poster": v.get("poster") if str(v.get("poster") or "").startswith("/media/") else None,
               "captions": v.get("captions"), "duration_s": v.get("duration_s")}
        if not out["src"]:
            tid = D.last_ticket(rec, ("done",)) or "local"
            base = f"/media/videos/{safe_id(eid)}/{safe_id(tid)}"
            out.update(src=f"{base}/video.mp4", poster=f"{base}/poster.jpg")
        elif not out["poster"]:
            out["poster"] = out["src"].rsplit("/", 1)[0] + "/poster.jpg"
        return out

    def receipts(self, eid: str, rec: dict | None = None) -> dict | None:
        rec = rec if rec is not None else self.get_record(eid)
        tid = D.last_ticket(rec, ("done",))
        k = (eid, tid)
        if k not in self._receipts:
            r = D.receipts(self.files, eid, tid)
            if r is None:
                return None                          # not cached: the files may land later
            self._receipts[k] = r
        return self._receipts[k]

    def raw_event(self, eid: str) -> dict:
        with self.lock:
            e = self.events.get(eid) or self._raws.get(eid)
        if e:
            return e
        try:
            r, _ = self.gate.store.get(f"raw_events/{safe_id(eid)}.json")
        except Exception:
            r = None
        if r:
            with self.lock:                           # saved once, at the click: it never changes
                self._raws[eid] = r
        return r or {}

    def video_row(self, eid: str, rec: dict, now: dt.datetime) -> dict | None:
        """One finished video, as the front page's videos[] (content.js's shape)."""
        urls = self.video_urls(eid, rec)
        if not urls:
            return None
        rc = self.receipts(eid, rec) or {}
        ev = dict(rc.get("event") or {})
        raw = self.raw_event(eid)
        for k_raw, k in (("category", "category"), ("subtype", "subtype"), ("country", "country"),
                         ("region", "region"), ("location_name", "place"), ("url", "url"), ("title", "title")):
            if raw.get(k_raw) and not ev.get(k):
                ev[k] = raw[k_raw]
        v = rec.get("video") or {}
        made = v.get("made_at")
        secs = v.get("seconds")
        return {
            "id": eid, "event": eid, "chain": eid, "part": 1, "of": 1,
            "headline": rc.get("title") or rec.get("title") or ev.get("title") or "",
            "eventTitle": rec.get("title") or ev.get("title") or "", "dek": rc.get("dek") or "",
            "category": ev.get("category") or "", "subtype": ev.get("subtype") or "", "country": ev.get("country") or "",
            "region": ev.get("region") or "", "place": ev.get("place") or ev.get("country") or "",
            "lat": ev.get("lat"), "lng": ev.get("lng"), "url": ev.get("url"),
            "confidence": ev.get("confidence") or D.confidence_word(raw.get("confidence")),
            "sides": rc.get("sides") or {"kind": "no real divide", "reason": "The receipts for this video aren't saved."},
            "articles": rc.get("articles") or 0, "outlets": rc.get("outlets") or 0,
            "claims": rc.get("claims") or 0, "claimsBacked": rc.get("claimsBacked") or 0,
            "confirmed": rc.get("confirmed"), "sayWho": rc.get("sayWho"), "dropped": rc.get("dropped"),
            "elsewhere": rc.get("elsewhere"), "outletList": rc.get("outletList") or [], "aiMark": rc.get("aiMark"),
            "receipts": bool(rc),
            "made": made, "minutes": round(float(secs) / 60, 1) if secs else None, "cost": v.get("usd"),
            "duration": D.clip_length(urls.get("duration_s")), "src": urls["src"], "poster": urls["poster"],
            "captions": urls.get("captions"), "reported": bool(rec.get("reports")), "keptUp": bool(rec.get("keep_up")),
            "hidden": bool(rec.get("hidden")),
        }

    def video_feed(self, records: dict, now: dt.datetime) -> tuple[list[dict], dict]:
        """The finished videos for "Hot right now", and the story chains (module 9; Nov 27).

        A chain is the events the follow-up check joined (the record's `chain`; stringer/followup.py).
        Each story is led by its newest event's video, and stories are ranked by that event's hot score
        (stringer/hot.py), with a fourth-or-later story from one country moved down, not dropped. videos[]
        keeps every video, each story's lead first; chains{} lists a chain's parts oldest first, with a
        follow-up still being made as a "making" part. A story of one video has no chains{} entry."""
        raws: dict = {}
        by_chain: dict = {}
        for eid, rec in records.items():
            if rec.get("state") == "done" and rec.get("video") and not rec.get("hidden"):
                v = self.video_row(eid, rec, now)
                if v:
                    v["chain"] = rec.get("chain") or eid
                    raws[eid] = self.raw_event(eid)
                    by_chain.setdefault(v["chain"], []).append(v)

        def start(eid: str) -> str:
            e = raws.get(eid) or {}
            times = hot.report_times(e, now)
            t = times[0] if times else D.parse(e.get("created_at"))
            return D.iso(t) if t else ""
        making: dict = {}
        for eid, rec in records.items():
            if rec.get("state") == "making" and rec.get("chain") in by_chain and not rec.get("hidden"):
                raws[eid] = raw = self.raw_event(eid)
                making.setdefault(rec["chain"], []).append(
                    {"id": eid, "event": eid, "kind": "making", "state": "making", "chain": rec["chain"],
                     "headline": rec.get("title") or raw.get("title") or "", "subtype": raw.get("subtype") or "",
                     "country": raw.get("country") or ""})
        for parts in by_chain.values():
            parts.sort(key=lambda v: start(v["id"]))
        leads = hot.rank([parts[-1] for parts in by_chain.values()], now, event_of=lambda v: raws.get(v["id"]) or {},
                         top=None, drop=False)
        videos = []
        for lead in leads:
            videos.append(lead)
            videos += [v for v in by_chain[lead["chain"]] if v is not lead]
        chains = {}
        for key, parts in by_chain.items():
            allp = parts + making.get(key, [])
            if len(allp) > 1:
                chains[key] = sorted(allp, key=lambda p: start(p["id"]))
        return videos, chains

    def visitor_user(self, visitor: str, email: str | None) -> dict:
        if email:
            local = email.split("@", 1)[0]
            letters = re.sub(r"[^A-Za-z]", "", local)[:2].upper() or local[:2].upper()
            return {"name": local, "email": email, "initials": letters, "iap": True, "signOut": IAP_SIGN_OUT,
                    "school": "Columbia University"}
        return {"name": "You", "email": "", "initials": "", "iap": False, "signOut": None, "school": ""}

    def progress_doc(self, eid: str, rec: dict) -> tuple[dict | None, str | None]:
        tid = D.last_ticket(rec)
        if not tid:
            return None, None
        running = self.running(rec) and (rec.get("ticket") or {}).get("id") == tid
        if not running and (eid, tid) in self._runs:
            return self._runs[(eid, tid)], tid
        doc, _ = self.gate.store.get(prog.key_for(eid, tid))
        if doc is None and not running:
            pl = self.files.read(eid, tid, "pipeline.json")
            if pl:
                doc = D.from_pipeline(pl, self.files.reader(eid, tid), tid)
        if doc is None and running:
            t = rec.get("ticket") or {}
            doc = {"version": prog.VERSION, "event": eid, "ticket": tid, "title": rec.get("title"),
                   "started": t.get("started"), "state": "running", "current": None, "steps": {}, "calls": [],
                   "searches": [], "usd": t.get("spent") or 0.0, "model_calls": 0}
        if doc is not None and not running and doc.get("state") != "running":
            self._runs[(eid, tid)] = doc
        if doc is not None and not running and doc.get("state") == "running":
            # the run ended without saying so (a crash): show it as stopped
            doc = dict(doc, state="failed" if rec.get("state") != "no_video" else "no_video",
                       why=rec.get("no_video_reason") or doc.get("why") or "The run stopped without finishing.")
        return doc, tid

    def event_meta(self, eid: str, rec: dict) -> dict:
        raw = self.raw_event(eid)
        rc = self.receipts(eid, rec) or {}
        ev = rc.get("event") or {}
        return {"id": eid, "title": rec.get("title") or raw.get("title") or ev.get("title"),
                "category": raw.get("category") or ev.get("category"), "subtype": raw.get("subtype") or ev.get("subtype"),
                "country": raw.get("country") or ev.get("country"), "url": raw.get("url") or ev.get("url"),
                "confidence": D.confidence_word(raw.get("confidence")) or ev.get("confidence")}

    def progress(self, eid: str, visitor: str) -> dict | None:
        rec = self.get_record(eid)
        if not rec:
            return None
        doc, tid = self.progress_doc(eid, rec)
        if doc is None:
            return None
        t = rec.get("ticket") or {}
        by = None
        if self.running(rec) and t.get("visitor"):
            by = "you" if t["visitor"] == self.gate.visitor_key(visitor) else "another student"
        video = self.video_urls(eid, rec) if rec.get("state") == "done" and not rec.get("hidden") else None
        st = self.gate.status()
        out = D.run_view(doc, by=by, event=self.event_meta(eid, rec), video=video, estimate_usd=st["estimate_usd"],
                         cap_usd=float(self.gate.lim["max_video_usd"]))
        out["record_state"] = "hidden" if rec.get("hidden") else rec.get("state")
        out["no_video_reason"] = rec.get("no_video_reason")
        return out

    def site_numbers(self, visitor: str) -> dict:
        st = self.gate.status()
        vs = self.gate.visitor_status(visitor)
        return {"open": st["mode"] == "open", "mode": st["mode"], "videosToday": st["videos_today"],
                "videosPerDay": st["videos_per_day"], "beingMade": st["being_made"], "atOnce": st["at_once"],
                "youThisHour": vs["this_hour"], "perPersonPerHour": vs["per_hour"],
                "retryAfterS": vs["retry_after_s"], "reportsToday": vs["reports_today"],
                "reportsPerDay": vs["reports_per_day"], "searchesLow": st["searches_low"], "voiceLow": st.get("voice_low", False),
                "estimatePerVideo": round(float(st["estimate_usd"]), 2), "capPerVideo": float(self.gate.lim["max_video_usd"]),
                "minutesPerVideo": D.MINUTES_PER_VIDEO}

    def running(self, rec: dict) -> bool:
        """A run holds the event and has shown life lately (the Gate's own test: a crashed run's record
        still says "making")."""
        return rec.get("state") == "making" and self.gate._fresh(rec.get("ticket"))

    def row_state(self, rec: dict, listed: str) -> str:
        """An event row's state from its record, read the way gate.view reads it: a video that finished,
        failed or was hidden since the list was made shows so at once (the list alone would say "ready"
        until its next refresh). From the records already in memory: one store read per event on every
        poll would be too many."""
        code, _ = self.gate._state(rec)
        return {"go": "ready", "has_video": "has_video", "making": "making", "no_video": "no_video",
                "taken_down": "hidden", "too_many_tries": "no_video"}.get(code, listed)

    def front(self, visitor: str, email: str | None = None) -> dict:
        """The front page's data: window.STRINGER_DEMO's shape, on real records."""
        now = dt.datetime.now(dt.timezone.utc)
        with self.lock:
            rows, updated, err = list(self.listings), self.updated, self.error
            records = dict(self.records)
        vkey = self.gate.visitor_key(visitor)
        events = []
        for li in rows:
            e = li.event
            eid = str(e.get("id"))
            state = li.state
            rec = records.get(eid) or {}
            if state == "making" or rec.get("state") == "making":
                rec = self.get_record(eid)
                if rec:
                    records[eid] = rec               # newer than the list's copy; it may carry a new chain
            if rec:                                  # the record is newer than the list (made every 5 minutes)
                state = self.row_state(rec, state)
            row = {"id": eid, "title": e.get("title") or "", "category": e.get("category") or "",
                   "subtype": e.get("subtype") or "", "country": e.get("country") or "", "region": e.get("region") or "",
                   "severity": D.num(e.get("severity")), "confidence": D.confidence_word(e.get("confidence")),
                   "reports": int(D.num(e.get("report_count")) or 0),
                   "lastReport": D.ago(D.parse(e.get("updated_at") or e.get("last_reported_at") or e.get("created_at")), now),
                   "url": e.get("url"), "state": state}
            if state == "has_video":
                row["video"] = eid
            if state == "no_video":
                row["reason"] = rec.get("no_video_reason") or MESSAGES["too_many_tries"]
            if state == "making":
                t = rec.get("ticket") or {}
                doc = None
                if t.get("id"):
                    try:
                        doc, _ = self.gate.store.get(prog.key_for(eid, t["id"]))
                    except Exception:
                        doc = None
                step, pct = D.progress_pct(doc, now)
                started = D.parse(t.get("started"))
                row["progress"] = {"step": step or "sides", "pct": pct, "ticket": t.get("id"),
                                   "startedAgo": D.ago(started, now).replace(" ago", "") if started else "",
                                   "started": t.get("started"), "by": "you" if t.get("visitor") == vkey else "another student"}
            events.append((row, e))
        # the top 10 by hot score, one per story chain, at most 3 from a country; a run being made always shows
        events = [r for r, _ in hot.rank(events, now, event_of=lambda t: t[1],
                                         chain_of=lambda t: (records.get(t[0]["id"]) or {}).get("chain"),
                                         keep=lambda t: t[0]["state"] == "making")]
        videos, chains = self.video_feed(records, now)
        msgs = dict(MESSAGES, unavailable=MESSAGES["no_video"], report_thanks="Thanks. We'll take a look.")
        lim = self.gate.lim
        msgs.update(day_full=MESSAGES["day_full"].format(n=lim["videos_per_day"]),
                    busy=MESSAGES["busy"].format(n=lim["at_once"]))
        return {
            "now": D.iso(now), "user": self.visitor_user(visitor, email), "credit": D.CREDIT,
            "site": self.site_numbers(visitor), "steps": D.steps_list(), "gateMessages": msgs,
            "reportReasons": [{"key": k, "label": D.REASON_LABELS.get(k, k)} for k in self.gate.rep["reasons"]],
            "videos": videos, "chains": chains, "events": events,
            "listUpdated": D.iso(dt.datetime.fromtimestamp(updated, dt.timezone.utc)) if updated else None,
            "listError": bool(err),
        }

    # ---- the admin side -----------------------------------------------------------------------------------
    # a hidden video isn't served, except to the review desk: its links there carry a pass that ends in an hour
    def media_pass(self, name: str, exp: int) -> str:
        return hmac.new(self.admin_token.encode(), f"{name}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def admin_link(self, url: str | None) -> str | None:
        if not url or not url.startswith("/media/") or not self.admin_token:
            return url
        exp = int(time.time()) + MEDIA_PASS_S
        return f"{url}?exp={exp}&k={self.media_pass(url[len('/media/'):], exp)}"

    def media_pass_ok(self, name: str, q: dict) -> bool:
        try:
            exp = int((q.get("exp") or ["0"])[0])
        except ValueError:
            return False
        k = (q.get("k") or [""])[0]
        return bool(self.admin_token) and exp >= time.time() and hmac.compare_digest(k, self.media_pass(name, exp))

    def admin_ok(self, token: str | None) -> bool:
        return bool(self.admin_token) and hmac.compare_digest(str(token or ""), self.admin_token)

    def admin(self) -> dict:
        """The review desk's data: reports, hidden videos, the log (3 days), money (7 days), every video."""
        g = self.gate
        now = dt.datetime.now(dt.timezone.utc)
        self.load_records()
        with self.lock:
            records = dict(self.records)
        title = lambda eid: (records.get(eid) or {}).get("title") or ""
        st = g.status()
        days = [g.day(now - dt.timedelta(days=i)) for i in range(7)]

        def get_many(keys):
            with ThreadPoolExecutor(max_workers=8) as ex:
                return [x for x in ex.map(lambda k: g.store.get(k)[0], keys) if x]
        reports = get_many(g.store.list("reports/"))
        reports.sort(key=lambda r: r.get("at") or "", reverse=True)

        def report_status(rec):
            if rec.get("hidden"):
                return "hidden, waiting for you" if rec.get("hidden_by") == "reports" else f"taken down by {rec.get('hidden_by')}"
            if rec.get("keep_up"):
                return "restored, marked to stay up"
            return "restored" if not rec.get("reports_since_review") else "open"
        out_reports = [{"id": r.get("id"), "video": r.get("event"), "headline": title(r.get("event")),
                        "reason": r.get("reason"), "note": r.get("note") or "", "at": r.get("at"),
                        "visitor": "visitor " + str(r.get("visitor") or "")[:4],
                        "status": report_status(records.get(r.get("event")) or {})} for r in reports]
        log_keys = []
        for day in days[:3]:
            log_keys += g.store.list(f"log/{day}/")
        log = get_many(log_keys)
        log.sort(key=lambda x: x.get("at") or "", reverse=True)

        def who(x):
            k = x.get("kind")
            if k in ("start", "report"):
                return "visitor " + str(x.get("visitor") or "")[:4]
            if k.startswith("video_"):
                return "pipeline"
            if k == "hidden" and x.get("by") == "reports":
                return "first report"
            return x.get("by") or "gate"

        def detail(x):
            k = x.get("kind")
            if k == "start":
                return f"estimate ${float(x.get('estimate_usd') or 0):.2f}"
            if k.startswith("video_"):
                bits = [f"${float(x.get('spent_usd') or 0):.2f} spent"]
                if x.get("reason"):
                    bits.insert(0, D.cut(x["reason"], 140))
                return " · ".join(bits)
            if k == "report":
                return D.REASON_LABELS.get(x.get("reason"), x.get("reason") or "").lower()
            return D.cut(x.get("note") or "", 200)
        out_log = [{"at": x.get("at"), "kind": x.get("kind"), "event": x.get("event"),
                    "what": title(x.get("event")) or {"paused": "New videos paused", "opened": "New videos open again"}.get(
                        x.get("kind"), ""), "who": who(x), "detail": detail(x)} for x in log]
        ledgers = {d: (g.store.get(f"days/{d}.json")[0] or {}) for d in days}
        per_step: dict = {}
        for v in (ledgers[days[0]].get("videos") or []):
            for k, u in (v.get("parts") or {}).items():
                per_step[k] = round(per_step.get(k, 0.0) + float(u or 0), 6)
        making = [r for r in records.values() if self.running(r)]
        making_rows = []
        for r in making:
            t = r.get("ticket") or {}
            doc = None
            if t.get("id"):
                try:
                    doc, _ = g.store.get(prog.key_for(str(r.get("id")), t["id"]))
                except Exception:
                    doc = None
            step, pct = D.progress_pct(doc, now)
            making_rows.append({"id": r.get("id"), "title": r.get("title") or "", "step": step, "pct": pct,
                                "started": t.get("started"), "spent": t.get("spent"),
                                "by": "visitor " + str(t.get("visitor") or "")[:4]})
        videos = []
        for eid, rec in records.items():
            last = (rec.get("history") or [{}])[-1] or {}
            remade = not rec.get("video") and rec.get("state") in (None, "ready") \
                and str(last.get("outcome") or "").startswith("reset for a remake")
            if not rec.get("video") and not rec.get("hidden") and rec.get("state") not in ("no_video",) and not remade:
                continue
            urls = self.video_urls(eid, dict(rec, video=last.get("video")) if remade else rec) or {}
            if rec.get("hidden") or remade:
                urls = dict(urls, src=self.admin_link(urls.get("src")), poster=self.admin_link(urls.get("poster")))
            v = rec.get("video") or (last.get("video") if remade else None) or {}
            rc = (self.receipts(eid, rec) or {}) if rec.get("video") else {}
            status = "down" if rec.get("hidden") and rec.get("hidden_by") != "reports" else \
                "hidden" if rec.get("hidden") else "remake" if remade else "up" if rec.get("state") == "done" \
                else rec.get("state") or "none"
            videos.append({"id": eid, "headline": rc.get("title") or rec.get("title") or "",
                           "articles": rc.get("articles"), "outlets": rc.get("outlets"), "claims": rc.get("claims"),
                           "claimsBacked": rc.get("claimsBacked"),
                           "eventTitle": rec.get("title") or "", "status": status, "state": rec.get("state"),
                           "made": v.get("made_at"), "cost": v.get("usd") if v.get("usd") is not None else rec.get("spent_usd"),
                           "minutes": round(float(v["seconds"]) / 60, 1) if v.get("seconds") else None,
                           "src": urls.get("src"), "poster": urls.get("poster"), "duration": D.clip_length(urls.get("duration_s")),
                           "reports": int(rec.get("reports") or 0), "keptUp": bool(rec.get("keep_up")),
                           "hiddenBy": rec.get("hidden_by"), "hiddenAt": rec.get("hidden_at"),
                           "noVideoReason": rec.get("no_video_reason")})
        videos.sort(key=lambda v: v.get("made") or "", reverse=True)
        hidden = [{"video": r.get("id"), "headline": r.get("title") or "", "since": r.get("hidden_at"),
                   "reports": int(r.get("reports") or 0), "by": r.get("hidden_by")}
                  for r in records.values() if r.get("hidden")]
        left = None
        try:
            left = g._tavily_seen[1] if g._tavily_seen else (g.tavily_left() if g.tavily_left else None)
        except Exception:
            left = None
        mode_rec = (g.store.get(g.MODE_KEY)[0] or {})
        return {
            "now": D.iso(now),
            "site": dict(self.site_numbers("admin"), searchCreditsLeft=left, searchCreditsPauseAt=g.lim["tavily_min_credits"],
                         spentToday=float(ledgers[days[0]].get("spent_usd") or 0.0), modeBy=mode_rec.get("by"),
                         modeAt=mode_rec.get("at"), modeNote=mode_rec.get("note")),
            "reports": out_reports, "hidden": hidden, "log": out_log, "videos": videos, "making": making_rows,
            "spend": {"today": float(ledgers[days[0]].get("spent_usd") or 0.0),
                      "inProgressEstimate": round(len(making) * float(st["estimate_usd"]), 2),
                      "last7days": [{"day": d, "usd": float(ledgers[d].get("spent_usd") or 0.0),
                                     "videos": len(ledgers[d].get("videos") or [])} for d in reversed(days)],
                      "perStep": per_step},
            "steps": D.steps_list(), "reportReasons": [{"key": k, "label": D.REASON_LABELS.get(k, k)} for k in g.rep["reasons"]],
            "events": [{"id": k, "title": r.get("title") or ""} for k, r in records.items()],
            "gateMessages": dict(MESSAGES),
        }

    def admin_act(self, action: str, body: dict, by: str) -> dict:
        g = self.gate
        note = str(body.get("note") or "")
        if action in ("pause", "open"):
            out = g.set_mode("closed" if action == "pause" else "open", by=by, note=note)
            return {"ok": True, "mode": out["mode"]}
        eid = body.get("event")
        try:
            eid = safe_id(eid)
        except ValueError:
            return {"ok": False, "message": "Which video? The event id is missing."}
        if action == "take_down":
            rec = g.take_down(eid, by=by, note=note)
        elif action == "restore":
            rec = g.restore(eid, by=by, note=note, keep_up=bool(body.get("keep_up")))
        elif action == "remake":
            if not note.strip():
                return {"ok": False, "message": "Write a note first. Stringer needs to know what to fix."}
            rec = g.remake(eid, by=by, note=note)
        else:
            return {"ok": False, "message": f"Unknown action {action!r}."}
        with self.lock:
            self.records[eid] = rec
        self._receipts = {k: v for k, v in self._receipts.items() if k[0] != eid}
        self.forget_watch(eid)
        return {"ok": True, "record": {"hidden": bool(rec.get("hidden")), "keep_up": bool(rec.get("keep_up")),
                                       "state": rec.get("state")}}

    # ---- the landing page's map --------------------------------------------------------------------------
    def geo(self) -> tuple[bytes, bytes] | None:
        with self._geo_lock:
            if self._geo is None:
                text = geo.load()
                if text is None:
                    return None
                raw = text.encode("utf-8")
                self._geo = (raw, gzip.compress(raw, 6))
            return self._geo


# ---- static files: the pages' code and fonts, kept in memory with a gzipped copy -----------------------------
_static: dict[str, tuple[int, tuple[bytes, bytes | None, str, str]]] = {}
_static_lock = threading.Lock()


def static_file(rel: str) -> tuple[bytes, bytes | None, str, str] | None:
    """(body, gzipped body or None, content type, etag) for /static/<rel>, or None. Kept in memory and read
    again only when the file changes (one stat per request), so edits show on reload on the Mac."""
    if not SAFE_PATH.fullmatch(rel) or ".." in rel.split("/"):
        return None
    if rel.startswith("fonts/"):
        p = (FONTS / rel[len("fonts/"):]).resolve()
        root = FONTS.resolve()
    else:
        p = (STATIC / rel).resolve()
        root = STATIC.resolve()
    if root not in p.parents:
        return None
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return None
    if not p.is_file():
        return None
    with _static_lock:
        hit = _static.get(rel)
        if hit and hit[0] == mtime:
            return hit[1]
    body = p.read_bytes()
    ctype = TYPES.get(p.suffix) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    gz = gzip.compress(body, 6) if ctype.startswith(("text/", "application/json", "image/svg")) and len(body) > 1024 else None
    item = (body, gz, ctype, '"' + hashlib.sha1(body).hexdigest()[:16] + '"')
    with _static_lock:
        _static[rel] = (mtime, item)
    return item


def handler_for(site: Site):
    class H(BaseHTTPRequestHandler):
        def _visitor(self) -> tuple[str, bool]:
            if self.headers.get(IAP_USER):
                return "iap:" + self.headers[IAP_USER], False
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE and v:
                    return v, False
            return secrets.token_hex(16), True

        def _email(self) -> str | None:
            e = self.headers.get(IAP_EMAIL) or ""
            return e.split(":", 1)[1] if ":" in e else (e or None)

        def _send(self, code: int, body, ctype: str, cookie: str | None = None, cache: str = "no-store",
                  extra: dict | None = None) -> None:
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            if cookie:
                self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _json(self, obj, code: int = 200, cookie: str | None = None) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str), "application/json; charset=utf-8", cookie)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 20000:
                return {}
            try:
                d = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return d if isinstance(d, dict) else {}

        def _gz_ok(self) -> bool:
            return "gzip" in (self.headers.get("Accept-Encoding") or "")

        def _static(self, rel: str) -> None:
            if rel == "atlas/js/data/geo.js":
                g = site.geo()
                if not g:
                    return self._send(404, "map data not built", "text/plain")
                raw, gz = g
                etag = '"geo-' + hashlib.sha1(raw[:4096]).hexdigest()[:12] + f'-{len(raw)}"'
                item = (raw, gz, TYPES[".js"], etag)
            else:
                item = static_file(rel)
            if item is None:
                return self._send(404, "not found", "text/plain")
            body, gz, ctype, etag = item
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            extra = {"ETag": etag, "Vary": "Accept-Encoding"}
            if gz is not None and self._gz_ok():
                extra["Content-Encoding"] = "gzip"
                body = gz
            self._send(200, body, ctype, cache="private, max-age=300", extra=extra)

        def _page(self, rel: str, cookie: str | None) -> None:
            item = static_file(rel)
            if item is None:
                return self._send(404, "not found", "text/plain")
            body, gz, ctype, etag = item
            extra = {"Vary": "Accept-Encoding"}
            if gz is not None and self._gz_ok():
                extra["Content-Encoding"] = "gzip"
                body = gz
            self._send(200, body, ctype, cookie=cookie, cache="no-cache", extra=extra)

        def _media(self, name: str, q: dict | None = None) -> None:
            if not MEDIA.fullmatch(name):
                return self._send(404, "not found", "text/plain")
            eid = name.split("/")[1]
            # only the files of the video its event shows now (not a taken-down or replaced one's), except
            # on the review desk, whose links carry a pass that ends in an hour
            if not site.may_watch(name) and not site.media_pass_ok(name, q or {}):
                return self._send(404, "not found", "text/plain")
            bucket = os.environ.get("STRINGER_VIDEO_BUCKET")
            if not bucket:
                p = site.files.local_media(eid, name.rsplit("/", 1)[1])
                return self._local_file(p) if p else self._send(404, "not found", "text/plain")
            r = cloud.open_object(bucket, name, self.headers.get("Range"))
            try:
                if r.status_code not in (200, 206):
                    code = r.status_code if r.status_code in (404, 416) else 502
                    return self._send(code, "not found" if code == 404 else "unavailable", "text/plain")
                self.send_response(r.status_code)
                for h in ("Content-Type", "Content-Length", "Content-Range"):
                    if r.headers.get(h):
                        self.send_header(h, r.headers[h])
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                for chunk in r.iter_content(256 * 1024):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):   # the player moved on mid-stream
                pass
            finally:
                r.close()

        def _local_file(self, p: Path) -> None:
            """A run's own file on the Mac, with one byte range (so the player can seek)."""
            size = p.stat().st_size
            ctype = mimetypes.guess_type(p.name)[0] or ("text/vtt" if p.suffix == ".vtt" else "application/octet-stream")
            start, end, code = 0, size - 1, 200
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "private, max-age=3600")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with open(p, "rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(256 * 1024, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _admin_by(self) -> str:
            e = self._email()
            return e.split("@", 1)[0] if e else "admin"

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            visitor, new = self._visitor()
            cookie = visitor if new else None
            if u.path == "/healthz":
                return self._send(200, "ok", "text/plain")
            if u.path == "/favicon.ico":                 # the pages have none; say so without a 404
                self.send_response(204)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                return
            if u.path.startswith("/static/"):
                return self._static(u.path[len("/static/"):])
            if u.path.startswith("/media/"):
                return self._media(u.path[len("/media/"):], q)
            if u.path in PAGES:                       # the page's own /api/site call brings the list
                return self._page(PAGES[u.path], cookie)
            if u.path == "/api/site":
                site.fresh()
                return self._json(site.front(visitor, self._email()), cookie=cookie)
            if u.path == "/api/progress" and q.get("event"):
                try:
                    out = site.progress(safe_id(q["event"][0]), visitor)
                except ValueError:
                    out = None
                return self._json(out, cookie=cookie) if out else self._json({"error": "no run for this story"}, 404)
            if u.path == "/api/receipts" and q.get("event"):
                try:
                    out = site.receipts(safe_id(q["event"][0]))
                except ValueError:
                    out = None
                return self._json(out) if out else self._json({"error": "no receipts for this story"}, 404)
            if u.path == "/status" and q.get("event"):
                try:
                    return self._json(site.record(q["event"][0]))
                except ValueError:                       # not an event id at all
                    return self._send(400, "bad event id", "text/plain")
            if u.path == "/admin/api":
                if not site.admin_token:
                    return self._json({"error": "The admin token isn't set up yet (GATE_ADMIN_TOKEN)."}, 503)
                if not site.admin_ok(self.headers.get(ADMIN_HEADER)):
                    time.sleep(0.4)
                    return self._json({"error": "That isn't the admin password."}, 401)
                return self._json(site.admin())
            if u.path in ("/front.html", "/landing.html", "/progress.html", "/admin.html"):
                return self._redirect({"/front.html": "/feed", "/landing.html": "/", "/progress.html": "/progress",
                                       "/admin.html": "/admin"}[u.path] + (f"?{u.query}" if u.query else ""))
            self._send(404, "not found", "text/plain")

        def _redirect(self, to: str) -> None:
            self.send_response(302)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            visitor, new = self._visitor()
            cookie = visitor if new else None
            if u.path == "/make" and q.get("event"):
                return self._json(site.make(q["event"][0], visitor), cookie=cookie)
            if u.path == "/report":
                b = self._body()
                return self._json(site.report(str(b.get("event") or ""), visitor, str(b.get("reason") or "other"),
                                              str(b.get("note") or "")), cookie=cookie)
            if u.path.startswith("/admin/api/"):
                if not site.admin_token:
                    return self._json({"error": "The admin token isn't set up yet (GATE_ADMIN_TOKEN)."}, 503)
                if not site.admin_ok(self.headers.get(ADMIN_HEADER)):
                    time.sleep(0.4)
                    return self._json({"error": "That isn't the admin password."}, 401)
                return self._json(site.admin_act(u.path[len("/admin/api/"):], self._body(), self._admin_by()))
            self._send(404, "not found", "text/plain")

        def log_message(self, fmt, *args):     # one short line per request, no visitor ids
            p = urlparse(self.path).path
            if p.startswith("/static/") or p == "/healthz":
                return
            print(f"{self.command} {p} -> {args[1] if len(args) > 1 else ''}")
    return H


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    ap.add_argument("--feed", help="read events from this JSON file instead of the live feed (a list, or {events: [...]})")
    ap.add_argument("--no-model", action="store_true", help="content check by the keyword rule only (no model calls)")
    a = ap.parse_args(argv)
    fetch = feed.fetch
    if a.feed:
        path = Path(a.feed)
        fetch = lambda: feed._events_of(json.loads(path.read_text(encoding="utf-8")))
    gate = Gate(complete=None, model="") if a.no_model else Gate()
    site = Site(gate=gate, fetch=fetch)
    if not os.environ.get("K_SERVICE"):          # on Cloud Run a background thread gets no CPU between requests
        threading.Thread(target=site.keep_fresh, daemon=True).start()
    threading.Thread(target=site.geo, daemon=True).start()        # build the map data once, before anyone asks
    print(f"Stringer site on :{a.port}")
    ThreadingHTTPServer(("0.0.0.0", a.port), handler_for(site)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
