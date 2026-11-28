"""The website (web/server.py), offline: the Gate on an in-memory store, its keyword rule in place of the
model, made-up events and story files, and a stand-in pipeline. Nothing here is real news."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from stringer import progress as P
from stringer.gate import Gate, MemoryStore
from web import data as D
from web import server

EVENT = {"id": "00000000-0000-4000-8000-0000000000we", "title": "Made-up storm floods the Avalon port",
         "summary": "Invented for the website test.", "category": "disaster", "subtype": "flood",
         "severity": 3, "confidence": 60, "country": "Freedonia", "report_count": 12,
         "created_at": "2026-11-27T10:00:00Z", "sources": []}
EID = EVENT["id"]
TOKEN = "made-up-admin-token"


def site(monkeypatch, tmp_path, outcome="done", token=""):
    monkeypatch.delenv("STRINGER_JOB", raising=False)
    monkeypatch.delenv("STRINGER_VIDEO_BUCKET", raising=False)
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=lambda: 500)
    s = server.Site(gate=g, fetch=lambda: [EVENT], files=D.Files(local=tmp_path / "stories"), admin_token=token)
    done = threading.Event()

    def fake_run(raw, ticket, **kw):
        try:
            if outcome == "done":
                return {"outcome": "done", "video": {"mp4": "/x/video.mp4", "duration_s": 60.0}, "seconds": 200.0,
                        "usd": 0.6}
            return {"outcome": "no_video", "why": "script: too few claims", "seconds": 90.0, "usd": 0.3}
        finally:
            done.set()
    monkeypatch.setattr(server.pipeline, "run", fake_run)
    return s, done


def wait_for(s, state, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if s.record(EID)["state"] == state:
            return True
        time.sleep(0.02)
    return False


def with_video(s, visitor="maker") -> str:
    """EVENT with a finished video in the store, the way a run leaves it. Returns the run's ticket id."""
    t = s.gate.start(EVENT, visitor).ticket
    t.finish(video={"duration_s": 61.0, "seconds": 240.0, "usd": 0.7, "made_at": "2026-11-27T11:00:00Z"})
    s.refresh()
    return t.id


@pytest.fixture
def serve():
    """The site's real request handler on a free port."""
    running = []

    def start(s):
        h = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(s))
        threading.Thread(target=h.serve_forever, daemon=True).start()
        running.append(h)
        return f"http://127.0.0.1:{h.server_address[1]}"
    yield start
    for h in running:
        h.shutdown()
        h.server_close()


def call(url, path, body=None, headers=None):
    """(status, headers, body bytes); a JSON body makes it a POST."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ---- the list, the click, the video ------------------------------------------------------------------------

def test_list_click_and_video(monkeypatch, tmp_path):
    s, done = site(monkeypatch, tmp_path)
    s.refresh()
    f = s.front("visitor-1")
    assert [(e["title"], e["state"]) for e in f["events"]] == [(EVENT["title"], "ready")]
    r = s.make(EID, "visitor-1")
    assert r["ok"] and r["code"] == "making" and r["progress"] == f"/progress?event={EID}"
    assert done.wait(5) and wait_for(s, "done")
    assert s.record(EID)["video"]["duration_s"] == 60.0
    again = s.make(EID, "visitor-2")                          # one video per event
    assert not again["ok"] and again["code"] == "has_video"
    for _ in range(2):                                        # the row stays "has a video" before the list's refresh
        f = s.front("visitor-1")
        assert f["events"][0]["state"] == "has_video" and f["events"][0]["video"] == EID
    v = f["videos"][0]
    assert v["id"] == EID and v["src"].startswith(f"/media/videos/{EID}/") and v["src"].endswith("/video.mp4")
    assert v["receipts"] is False and v["sides"]["kind"] == "no real divide"     # no story files saved here


def test_no_video_is_shown_with_its_reason(monkeypatch, tmp_path):
    s, done = site(monkeypatch, tmp_path, outcome="no_video")
    s.refresh()
    assert s.make(EID, "visitor-1")["ok"]
    assert done.wait(5) and wait_for(s, "no_video")
    assert "too few claims" in s.record(EID)["why"]
    row = s.front("visitor-1")["events"][0]
    assert row["state"] == "no_video" and "too few claims" in row["reason"]


def test_unknown_event_is_refused(monkeypatch, tmp_path):
    s, _ = site(monkeypatch, tmp_path)
    s.refresh()
    assert s.make("not-in-the-list", "visitor-1")["code"] == "unknown"


def test_titles_reach_the_page_only_as_json(monkeypatch, tmp_path, serve):
    """The pages are fixed files; titles come from /api/site and the page escapes them (esc in common.js)."""
    s, _ = site(monkeypatch, tmp_path)
    bad = dict(EVENT, id="00000000-0000-4000-8000-0000000000x2", title="<script>alert(1)</script> flood")
    s.fetch = lambda: [bad]
    s.refresh()
    url = serve(s)
    for page in ("/", "/feed", "/progress", "/admin"):
        code, h, body = call(url, page)
        assert code == 200 and h["Content-Type"].startswith("text/html") and b"alert(1)" not in body, page
    code, h, body = call(url, "/api/site")
    assert code == 200 and h["Content-Type"].startswith("application/json")
    assert json.loads(body)["events"][0]["title"] == bad["title"]
    js = (server.STATIC / "feed" / "js" / "front.js").read_text(encoding="utf-8")
    assert "esc(e.title)" in js


def test_site_numbers_and_limits(monkeypatch, tmp_path):
    s, _ = site(monkeypatch, tmp_path)
    s.refresh()
    n = s.front("visitor-1")["site"]
    assert n["open"] and n["videosToday"] == 0 and n["youThisHour"] == 0 and n["reportsToday"] == 0
    assert n["perPersonPerHour"] == s.gate.lim["per_visitor_per_hour"] and n["capPerVideo"] > 0
    s.gate.set_mode("closed", by="jan")
    assert s.front("visitor-1")["site"]["open"] is False
    assert s.make(EID, "visitor-1")["code"] == "closed"


# ---- reports ---------------------------------------------------------------------------------------------------

def test_report_hides_the_video_and_has_a_daily_limit(monkeypatch, tmp_path):
    s, _ = site(monkeypatch, tmp_path)
    s.refresh()
    assert s.report(EID, "viewer", "wrong_facts", "x")["ok"] is False        # nothing up to report yet
    with_video(s)
    r = s.report(EID, "viewer", "wrong_facts", "The date is wrong.")
    assert r == {"ok": True, "code": "reported", "hidden": True, "message": "Thanks. We'll take a look."}
    f = s.front("viewer")
    assert f["videos"] == [] and f["site"]["reportsToday"] == 1
    for _ in range(s.gate.rep["per_visitor_per_day"] - 1):
        assert s.report(EID, "viewer", "other", "")["ok"]
    out = s.report(EID, "viewer", "other", "")
    assert out["ok"] is False and out["code"] == "report_limit"
    assert s.report("../../slots", "viewer", "other", "")["ok"] is False      # not an event id


def test_report_route(monkeypatch, tmp_path, serve):
    s, _ = site(monkeypatch, tmp_path)
    with_video(s)
    url = serve(s)
    code, h, body = call(url, "/report", {"event": EID, "reason": "one_sided", "note": "Only one side."})
    assert code == 200 and json.loads(body)["code"] == "reported"
    assert "stringer_visitor=" in h.get("Set-Cookie", "")                      # a new visitor gets its cookie
    rep = s.gate.reports(EID)[0]
    assert rep["reason"] == "one_sided" and rep["note"] == "Only one side."


# ---- the admin side --------------------------------------------------------------------------------------------

def test_admin_needs_the_token(monkeypatch, tmp_path, serve):
    s, _ = site(monkeypatch, tmp_path)
    url = serve(s)
    assert call(url, "/admin/api")[0] == 503                                   # no token set up: closed
    assert call(url, "/admin/api/pause", {})[0] == 503
    s2, _ = site(monkeypatch, tmp_path, token=TOKEN)
    url2 = serve(s2)
    assert call(url2, "/admin/api")[0] == 401
    assert call(url2, "/admin/api", headers={server.ADMIN_HEADER: "wrong"})[0] == 401
    assert call(url2, "/admin/api/pause", {}, headers={server.ADMIN_HEADER: "wrong"})[0] == 401
    assert s2.gate.mode == "open"
    code, _, body = call(url2, "/admin/api", headers={server.ADMIN_HEADER: TOKEN})
    d = json.loads(body)
    assert code == 200 and {"site", "reports", "hidden", "log", "videos", "making", "spend", "steps"} <= set(d)
    assert [x["key"] for x in d["steps"]] == P.KEYS


def test_admin_actions(monkeypatch, tmp_path, serve):
    s, _ = site(monkeypatch, tmp_path, token=TOKEN)
    with_video(s)
    url = serve(s)
    act = lambda a, b: json.loads(call(url, f"/admin/api/{a}", b, headers={server.ADMIN_HEADER: TOKEN})[2])
    assert act("take_down", {"event": EID, "note": "checking a fact"})["record"]["hidden"] is True
    assert s.front("v")["videos"] == []
    out = act("restore", {"event": EID, "keep_up": True})
    assert out["record"] == {"hidden": False, "keep_up": True, "state": "done"}
    assert s.report(EID, "viewer", "other", "")["hidden"] is False            # kept up: reports don't hide it
    assert [v["id"] for v in s.front("v")["videos"]] == [EID]
    assert act("remake", {"event": EID, "note": " "})["ok"] is False          # a remake needs a note
    out = act("remake", {"event": EID, "note": "The script misread the date."})
    assert out["ok"] and out["record"]["hidden"] is False and out["record"]["state"] is None
    d = s.admin()
    assert {v["id"]: v for v in d["videos"]}[EID]["status"] == "remake"       # the old video stays on the desk
    assert s.make(EID, "visitor-1")["ok"]                                     # it can be made again
    assert act("pause", {"note": "a break"})["mode"] == "closed" and s.gate.mode == "closed"
    assert act("open", {})["mode"] == "open"
    assert act("nonsense", {"event": EID})["ok"] is False
    assert act("take_down", {})["ok"] is False                                 # no event id
    kinds = [e["kind"] for e in s.gate.log()]
    assert {"taken_down", "restored", "remake", "paused", "opened"} <= set(kinds)
    assert s.admin()["site"]["modeBy"] == "admin"


# ---- hidden videos aren't served, except to the review desk -----------------------------------------------------

def test_media_of_a_hidden_video_needs_the_admin_pass(monkeypatch, tmp_path, serve):
    s, _ = site(monkeypatch, tmp_path, token=TOKEN)
    tid = with_video(s)
    vid = tmp_path / "stories" / EID / "video"
    vid.mkdir(parents=True)
    (vid / "poster.jpg").write_bytes(b"made-up poster")
    url = serve(s)
    path = f"/media/videos/{EID}/{tid}/poster.jpg"
    assert call(url, path)[2] == b"made-up poster"
    s.admin_act("take_down", {"event": EID}, "jan")                         # this machine stops serving it at once
    assert call(url, path)[0] == 404
    signed = s.admin_link(path)
    assert signed.startswith(path + "?exp=") and call(url, signed)[2] == b"made-up poster"
    assert call(url, signed[:-1] + ("0" if signed[-1] != "0" else "1"))[0] == 404     # a changed pass fails
    expired = int(time.time()) - 5
    assert call(url, f"{path}?exp={expired}&k={s.media_pass(path[7:], expired)}")[0] == 404
    hidden = {v["id"]: v for v in s.admin()["videos"]}[EID]
    assert "?exp=" in hidden["poster"]                                          # the desk's links carry the pass


def test_media_names():
    ok = "videos/00000000-0000-4000-8000-0000000000we/20261127T041927-bfb309ea/video.mp4"
    assert server.MEDIA.fullmatch(ok)
    assert server.MEDIA.fullmatch(ok.replace("video.mp4", "poster.jpg"))
    for bad in ("stories/x/y/story_file.json", "videos/x/y/script.json", "videos/x/video.mp4",
                "videos/x/y/../video.mp4x", "videos/x y/z/video.mp4", "gate/slots.json"):
        assert not server.MEDIA.fullmatch(bad), bad


# ---- live progress ---------------------------------------------------------------------------------------------

def test_progress_of_a_running_video(monkeypatch, tmp_path, serve):
    s, _ = site(monkeypatch, tmp_path)
    s.refresh()
    t = s.gate.start(EVENT, "visitor-1").ticket
    s.refresh()                                             # started elsewhere: the list says "being made"
    p = P.Progress(s.gate.store, EID, t.id, title=EVENT["title"], say=lambda *_: None)
    p.end("sides", {"seconds": 1.5, "usd": 0.0002, "kind": "two sides"})
    p.begin("gather")
    v = s.progress(EID, "visitor-1")
    assert v["live"] and v["by"] == "you" and v["current"] == "gather"
    st = {x["key"]: x["status"] for x in v["steps"]}
    assert st["sides"] == "done" and st["gather"] == "running" and st["video"] == "waiting"
    assert s.progress(EID, "visitor-2")["by"] == "another student"
    row = s.front("visitor-1")["events"][0]
    assert row["state"] == "making" and row["progress"]["step"] == "gather" and row["progress"]["by"] == "you"
    url = serve(s)
    code, _, body = call(url, f"/api/progress?event={EID}")
    assert code == 200 and json.loads(body)["live"] is True
    assert call(url, "/api/progress?event=00000000-0000-4000-8000-00000000none")[0] == 404
    assert call(url, "/api/progress?event=../../slots")[0] == 404
    p.finish("no_video", "script: too few claims", seconds=40.0, usd=0.2)
    t.finish(no_video="script: too few claims")
    v = s.progress(EID, "visitor-1")
    assert not v["live"] and v["outcome"] == "no_video" and "too few claims" in v["why"]
    assert {x["key"]: x["status"] for x in v["steps"]}["gather"] == "stopped"


def test_a_run_that_stopped_without_saying_so_shows_as_failed(monkeypatch, tmp_path):
    s, _ = site(monkeypatch, tmp_path)
    t = s.gate.start(EVENT, "visitor-1").ticket
    p = P.Progress(s.gate.store, EID, t.id, say=lambda *_: None)
    p.begin("story_file")                                   # the machine died here
    t.finish(error="RuntimeError('lost')")
    v = s.progress(EID, "visitor-1")
    assert v["live"] is False and v["state"] == "failed" and "stopped" in v["why"]


# ---- static files ----------------------------------------------------------------------------------------------

def test_static_files_are_gzipped_cached_and_safe(monkeypatch, tmp_path, serve):
    s, _ = site(monkeypatch, tmp_path)
    url = serve(s)
    code, h, body = call(url, "/static/feed/js/front.js", headers={"Accept-Encoding": "gzip"})
    assert code == 200 and h["Content-Encoding"] == "gzip" and h["Content-Type"].startswith("text/javascript")
    assert b"STRINGER_GET" in gzip.decompress(body)
    assert call(url, "/static/feed/js/front.js", headers={"If-None-Match": h["ETag"]})[0] == 304
    for bad in ("/static/../server.py", "/static/feed/../../server.py", "/static/%2e%2e/server.py",
                "/static/feed/js/nothing.js"):
        assert call(url, bad)[0] == 404, bad
    assert call(url, "/favicon.ico")[0] == 204
    assert call(url, "/front.html")[0] == 200                               # old names go to the new ones


def test_static_file_is_read_again_when_it_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "STATIC", tmp_path)
    f = tmp_path / "made-up.js"
    f.write_text("one")
    assert server.static_file("made-up.js")[0] == b"one"
    f.write_text("two")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert server.static_file("made-up.js")[0] == b"two"


def test_no_video_frames_in_the_repo():
    """The designs' media/ folders hold frames from real videos; only code and fonts were copied."""
    files = [p for p in server.STATIC.rglob("*") if p.is_file()]
    assert files and not [p for p in files if "media" in p.relative_to(server.STATIC).parts]
    assert not [p for p in files if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".gif")]


# ---- the Cloud Run job's uploads ---------------------------------------------------------------------------------

def test_job_records_site_paths(monkeypatch, tmp_path):
    from scripts import run_job
    out = tmp_path / "video"
    out.mkdir()
    for f in ("video.mp4", "poster.jpg"):
        (out / f).write_bytes(b"x")
    sent = []
    monkeypatch.setenv("STRINGER_VIDEO_BUCKET", "vids")
    monkeypatch.setattr(run_job.cloud, "upload", lambda b, n, p, **kw: sent.append((b, n)) or "")
    rec = {"video": {"mp4": str(out / "video.mp4"), "duration_s": 60.0}, "seconds": 200.0, "usd": 0.5}
    v = run_job.upload_media(rec, EVENT["id"], "T1")
    assert v["url"] == f"/media/videos/{EVENT['id']}/T1/video.mp4" and server.MEDIA.fullmatch(v["url"][7:])
    assert v["poster"].endswith("/poster.jpg") and v["captions"] is None
    assert sent and all(b == "vids" and n.startswith("videos/") for b, n in sent)


def test_a_job_that_cannot_start_gives_the_click_back(monkeypatch, tmp_path):
    s, _ = site(monkeypatch, tmp_path)
    s.refresh()
    monkeypatch.setenv("STRINGER_JOB", "stringer-make")
    monkeypatch.setenv("STRINGER_PROJECT", "made-up-project")

    def no_start(*a, **kw):
        raise ConnectionError("Cloud Run did not answer")
    monkeypatch.setattr(server.cloud, "start_job", no_start)
    r = s.make(EVENT["id"], "visitor-1")
    assert not r["ok"] and r["code"] == "start_failed" and "try again" in r["message"]
    st = s.gate.status()
    assert st["videos_today"] == 0 and st["being_made"] == 0                   # nothing was used up
    assert s.record(EVENT["id"])["state"] is None                              # not "making": the button is back
    started = []
    monkeypatch.setattr(server.cloud, "start_job", lambda *a, **kw: started.append(a) or "op")
    assert s.make(EVENT["id"], "visitor-1")["ok"] and len(started) == 1        # and the same visitor can click again


def test_a_crashed_run_shows_the_button_again_and_a_taken_down_video_is_not_served(monkeypatch, tmp_path):
    import datetime as dt
    now = [dt.datetime(2026, 12, 9, 15, 0, tzinfo=dt.timezone.utc)]
    monkeypatch.delenv("STRINGER_JOB", raising=False)
    monkeypatch.setenv("STRINGER_VIDEO_BUCKET", "vids")                       # the site's own rule, not the Mac's
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=lambda: 500, now=lambda: now[0])
    s = server.Site(gate=g, fetch=lambda: [EVENT], files=D.Files(local=tmp_path))
    eid = EVENT["id"]
    t = g.start(EVENT, "visitor-1").ticket                    # a run that then dies without a word
    assert s.record(eid)["state"] == "making"
    now[0] += dt.timedelta(minutes=25)
    assert s.record(eid) == {"state": None, "video": None, "why": None, "failed": True}
    t2 = g.start(EVENT, "visitor-2").ticket
    path = f"videos/{eid}/{t2.id}/video.mp4"
    t2.finish(video={"url": "/media/" + path})
    assert s.record(eid)["state"] == "done" and s.may_watch(path)
    g.take_down(eid, by="jan")
    s._watch.clear()                                          # (the 30-second memory of the last answer)
    assert s.record(eid) == {"state": "unavailable", "video": None, "why": None, "failed": False}
    assert not s.may_watch(path) and not s.may_watch(f"videos/{eid}/{t.id}/video.mp4")


# ---- the list on Cloud Run: refreshed by the requests themselves (Nov 27) ----------------------------------------
def until(ok, timeout=5.0):
    end = time.time() + timeout
    while not ok():
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def slow_site(tmp_path, gate_open: threading.Event, calls: list):
    def fetch():
        calls.append(threading.current_thread().name)
        assert gate_open.wait(5)
        return [EVENT]
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=lambda: 500)
    return server.Site(gate=g, fetch=fetch, files=D.Files(local=tmp_path / "stories"))


def test_a_request_refreshes_the_list_in_its_own_thread(tmp_path):
    go, calls = threading.Event(), []
    go.set()
    s = slow_site(tmp_path, go, calls)
    s.fresh()
    assert calls == [threading.current_thread().name] and [str(l.event["id"]) for l in s.listings] == [EID]
    s.fresh()
    assert len(calls) == 1                                   # fresh for REFRESH_S: no second fetch


def test_with_no_list_yet_a_request_waits_for_the_refresh_in_progress(tmp_path):
    go, calls = threading.Event(), []
    s = slow_site(tmp_path, go, calls)
    first = threading.Thread(target=s.fresh)
    first.start()
    until(lambda: calls)
    threading.Timer(0.2, go.set).start()
    t0 = time.time()
    s.fresh()                                                # waits on the first one (no fetch of its own)
    first.join(5)
    assert time.time() - t0 >= 0.15 and len(calls) == 1 and s.listings


def test_with_a_list_a_request_does_not_wait_for_a_refresh(tmp_path):
    go, calls = threading.Event(), []
    go.set()
    s = slow_site(tmp_path, go, calls)
    s.fresh()
    go.clear()
    s.updated -= server.REFRESH_S + 1                        # the list is old now
    s.tried -= server.RETRY_S + 1
    first = threading.Thread(target=s.fresh)
    first.start()
    until(lambda: len(calls) == 2)
    t0 = time.time()
    s.fresh()                                                # the last list is shown at once
    assert time.time() - t0 < 0.1 and s.listings
    go.set()
    first.join(5)


def test_on_cloud_run_no_background_thread_refreshes_the_list(monkeypatch):
    started = []
    monkeypatch.setenv("K_SERVICE", "stringer-web")
    monkeypatch.setattr(server.threading, "Thread", lambda target, **kw: started.append(target.__name__) or
                        type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(server, "ThreadingHTTPServer", lambda *a, **kw: type("S", (), {"serve_forever": lambda self: None})())
    monkeypatch.setattr(server, "Gate", lambda **kw: Gate(MemoryStore(), complete=None, model=""))
    server.main(["--port", "0", "--no-model"])
    assert "keep_fresh" not in started and "geo" in started


# ---- hot ranking and story chains (Nov 27) -------------------------------------------------------------------

def feed_event(n: int, hours_ago: float, reports: int = 9, country: str = "Freedonia") -> dict:
    """A made-up eligible feed event whose reports all came in `hours_ago` (its first and newest report)."""
    t = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return dict(EVENT, id=f"00000000-0000-4000-8000-{n:012d}", title=f"Made-up event {n}", country=country,
                report_count=reports, created_at=t,
                sources=[{"url": f"https://example.org/{n}/{i}", "published_at": t} for i in range(reports)])


def test_the_front_page_ranks_events_and_groups_a_chain(monkeypatch, tmp_path):
    early, late, other, mk = feed_event(1, 30), feed_event(2, 3), feed_event(3, 1, country="Sylvania"), feed_event(4, 2)
    extra = [feed_event(10 + i, 1 + i / 10, reports=30, country=f"Country {i}") for i in range(10)]   # hotter
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=lambda: 500)
    feed = [early, late, other, mk] + extra
    s = server.Site(gate=g, fetch=lambda: feed, files=D.Files(local=tmp_path / "stories"))
    for i, e in enumerate((early, late, other)):
        g.store.put(f"raw_events/{e['id']}.json", e, None)
        g.start(e, f"maker-{i}").ticket.finish(video={"duration_s": 60.0, "seconds": 200.0, "usd": 0.2})
    g.store.put(f"raw_events/{mk['id']}.json", mk, None)
    assert g.start(mk, "maker-9").ok                         # a follow-up still being made
    g.join_chain(late["id"], [early["id"]])
    g.join_chain(mk["id"], [early["id"]])
    s.refresh()
    f = s.front("visitor-1")
    leads = []
    for v in f["videos"]:
        if v["chain"] not in {x["chain"] for x in leads}:
            leads.append(v)
    assert [v["id"] for v in leads] == [other["id"], late["id"]]        # one story per chain, hottest first
    parts = f["chains"][early["id"]]
    assert [p["id"] for p in parts] == [early["id"], late["id"], mk["id"]] and parts[-1]["kind"] == "making"
    assert other["id"] not in f["chains"]                                # a story of one video
    ids = [e["id"] for e in f["events"]]
    assert len(ids) == 11 and mk["id"] in ids                            # the top 10, plus the run being made
    assert early["id"] not in ids                                        # its chain shows its newest event
    freedonia = [e for e in f["events"] if e["country"] == "Freedonia"]
    assert len(freedonia) <= 3
