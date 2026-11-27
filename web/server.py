"""Stringer's test website: list the events the Gate allows, press "Make video", watch it arrive.

For testing the deploy only (Jan, Nov 27); the real front page (module 9) replaces it. Standard
library only. Routes:
    GET  /                 the list (refreshed from the live feed every few minutes)
    POST /make?event=<id>  the click: the Gate decides; on go, the event is saved and the job starts
    GET  /status?event=<id>  what a visitor may see of the event (the Gate's view): making, done (with the
                           video), no video, unavailable, or nothing yet
    GET  /media/videos/<event>/<ticket>/<file>   a finished video, poster or captions, streamed from the
                           private video bucket (with Range, so the player can seek)
    GET  /healthz          "ok"

On Cloud Run the site sits behind Identity-Aware Proxy: only signed-in Columbia accounts get in (Jan,
Nov 27), and the account IAP names is the visitor for the Gate's per-visitor limits (a cookie otherwise).

On Cloud Run STRINGER_JOB names the job that makes a video (scripts/run_job.py). Without it, the
video is made in this process, on a thread (for a local try: python -m web.server --port 8080)."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from stringer import cloud, feed, pipeline
from stringer.gate import Gate, TooCostly, VideoOverBudget
from stringer.gate.core import safe_id

REFRESH_S = 300
RETRY_S = 60
COOKIE = "stringer_visitor"
IAP_USER = "X-Goog-Authenticated-User-Id"
MEDIA = re.compile(r"videos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(video\.mp4|poster\.jpg|captions\.vtt|captions\.srt)")


class Site:
    def __init__(self, gate: Gate | None = None, fetch=feed.fetch):
        self.gate = gate or Gate()
        self.fetch = fetch
        self.events: dict[str, dict] = {}
        self.listings: list = []
        self.updated = 0.0
        self.error = ""
        self.tried = 0.0
        self.lock = threading.Lock()
        self.refreshing = threading.Lock()
        self._watch: dict[str, tuple[float, bool]] = {}

    def refresh(self) -> None:
        try:
            events = self.fetch()
            listings = self.gate.screen(events)
            with self.lock:
                self.events = {str(e["id"]): e for e in events}
                self.listings, self.updated, self.error = listings, time.time(), ""
        except Exception as e:                       # keep the last good list
            self.error = repr(e)[:300]

    def fresh(self) -> None:
        """Refreshes the list when it is older than REFRESH_S (after a failure, at most once a minute).
        Called from requests too: Cloud Run gives an idle instance almost no CPU, so a timer alone stalls."""
        now = time.time()
        if now - self.updated < REFRESH_S or now - self.tried < RETRY_S:
            return
        if not self.refreshing.acquire(blocking=False):
            return                                   # another request is refreshing: show the last list
        try:
            self.tried = now
            self.refresh()
        finally:
            self.refreshing.release()

    def keep_fresh(self) -> None:
        while True:
            self.fresh()
            time.sleep(RETRY_S)

    def record(self, event_id: str) -> dict:
        """What the page shows for one event: the Gate's view of it (gate.view), never the raw record.
        The record still says "making" after a run has crashed, and still holds a taken-down video."""
        v = self.gate.view(event_id)
        state = {"has_video": "done", "ready": None}.get(v["state"], v["state"])
        return {"state": state, "video": v.get("video"), "why": v.get("reason"), "failed": bool(v.get("failed"))}

    def may_watch(self, name: str) -> bool:
        """gate.may_watch with a 30-second memory: a player asks for one video in many pieces."""
        now = time.time()
        hit = self._watch.get(name)
        if hit and now - hit[0] < 30:
            return hit[1]
        ok = self.gate.may_watch(name)
        if len(self._watch) > 500:
            self._watch.clear()
        self._watch[name] = (now, ok)
        return ok

    def make(self, event_id: str, visitor: str) -> dict:
        with self.lock:
            raw = self.events.get(event_id)
        if raw is None:
            return {"ok": False, "code": "unknown", "message": "That event isn't in the list any more."}
        d = self.gate.start(raw, visitor)
        if not d.ok:
            return {"ok": False, "code": d.code, "message": d.message, "video": d.video}
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
            return {"ok": False, "code": "start_failed", "message": "The video couldn't be started. Please try again."}
        return {"ok": True, "code": "making", "message": "Making the video. This takes a few minutes."}

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

    def page(self) -> str:
        with self.lock:
            rows, updated, err = list(self.listings), self.updated, self.error
        st = self.gate.status()
        items = []
        for li in rows:
            e, eid = li.event, html.escape(str(li.event["id"]))
            title = html.escape(str(e.get("title") or ""))
            meta = html.escape(f"{e.get('category')} · severity {e.get('severity')} · {e.get('report_count')} reports")
            items.append(f'<li data-id="{eid}" data-state="{html.escape(li.state)}"><div class="t">{title}</div>'
                         f'<div class="m">{meta}</div><div class="a"></div></li>')
        when = time.strftime("%H:%M UTC", time.gmtime(updated)) if updated else "not yet"
        return PAGE.format(items="\n".join(items) or "<li>No events yet. The list loads in a minute.</li>",
                           when=when, err=html.escape(err), today=st["videos_today"], per_day=st["videos_per_day"])


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Stringer test</title>
<style>
:root{{--bg:#fafafa;--ink:#18181b;--soft:#71717a;--line:#e4e4e7;--accent:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#09090b;--ink:#f4f4f5;--soft:#a1a1aa;--line:#27272a;--accent:#60a5fa}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px}} h1{{font-size:20px;margin:0 0 4px}}
.s{{color:var(--soft);font-size:13px;margin-bottom:20px}} ul{{list-style:none;padding:0;margin:0}}
li{{border-top:1px solid var(--line);padding:14px 0}} .t{{font-weight:600}} .m{{color:var(--soft);font-size:13px}}
.a{{margin-top:8px;font-size:14px}} button{{font:inherit;padding:6px 12px;border:1px solid var(--accent);
background:none;color:var(--accent);border-radius:6px;cursor:pointer}} video{{width:220px;border-radius:8px;display:block}}
</style></head><body><main>
<h1>Stringer: deploy test</h1>
<div class="s">Test page only. Events by Monitor the Situation. List updated {when}. Videos today: {today} of {per_day}. {err}</div>
<ul>{items}</ul></main>
<script>
const act = (li, st) => {{
  const a = li.querySelector('.a'); a.textContent = '';
  if (st.state === 'done' && st.video && st.video.url) {{
    const v = document.createElement('video'); v.controls = true; v.src = st.video.url;
    if (st.video.poster) v.poster = st.video.poster; a.append(v); return; }}
  if (st.state === 'making') {{ a.textContent = 'Making the video…'; setTimeout(() => poll(li), 2000); return; }}
  if (st.state === 'no_video') {{ a.textContent = 'No video: ' + (st.why || ''); return; }}
  if (st.state === 'unavailable') {{ a.textContent = "This story isn't available for a video."; return; }}
  if (st.failed) {{ const n = document.createElement('div'); n.textContent = "The last try didn't finish. You can try again."; a.append(n); }}
  const b = document.createElement('button'); b.textContent = 'Make video';
  b.onclick = async () => {{
    b.disabled = true;
    const r = await fetch('/make?event=' + encodeURIComponent(li.dataset.id), {{method: 'POST'}});
    const d = await r.json(); a.textContent = d.message || '';
    if (d.ok) setTimeout(() => poll(li), 3000); else b.disabled = false;
  }};
  a.append(b);
}};
const poll = async li => {{
  const r = await fetch('/status?event=' + encodeURIComponent(li.dataset.id)); act(li, await r.json()); }};
document.querySelectorAll('li[data-id]').forEach(li => poll(li));
</script></body></html>"""


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

        def _send(self, code: int, body: str, ctype: str, cookie: str | None = None) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code: int = 200, cookie: str | None = None) -> None:
            self._send(code, json.dumps(obj), "application/json", cookie)

        def _media(self, name: str) -> None:
            bucket = os.environ.get("STRINGER_VIDEO_BUCKET")
            # only the files of a video its event shows right now: not a taken-down or replaced one's
            if not bucket or not MEDIA.fullmatch(name) or not site.may_watch(name):
                return self._send(404, "not found", "text/plain")
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

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            visitor, new = self._visitor()
            if u.path == "/healthz":
                return self._send(200, "ok", "text/plain")
            if u.path.startswith("/media/"):
                return self._media(u.path[len("/media/"):])
            if u.path == "/status" and q.get("event"):
                try:
                    return self._json(site.record(q["event"][0]))
                except ValueError:                       # not an event id at all
                    return self._send(400, "bad event id", "text/plain")
            if u.path == "/":
                site.fresh()
                return self._send(200, site.page(), "text/html; charset=utf-8", visitor if new else None)
            self._send(404, "not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            visitor, new = self._visitor()
            if u.path == "/make" and q.get("event"):
                return self._json(site.make(q["event"][0], visitor), cookie=visitor if new else None)
            self._send(404, "not found", "text/plain")

        def log_message(self, fmt, *args):     # one short line per request, no visitor ids
            print(f"{self.command} {urlparse(self.path).path} -> {args[1] if len(args) > 1 else ''}")
    return H


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    a = ap.parse_args(argv)
    site = Site()
    threading.Thread(target=site.keep_fresh, daemon=True).start()
    print(f"Stringer test site on :{a.port}")
    ThreadingHTTPServer(("0.0.0.0", a.port), handler_for(site)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
