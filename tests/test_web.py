"""The deploy-test website (web/server.py), offline: the Gate on an in-memory store, its keyword rule in
place of the model, a made-up event, and a stand-in pipeline."""
from __future__ import annotations

import threading
import time

from stringer.gate import Gate, MemoryStore
from web import server

EVENT = {"id": "00000000-0000-4000-8000-0000000000we", "title": "Made-up storm floods the Avalon port",
         "summary": "Invented for the website test.", "category": "disaster", "subtype": "flood",
         "severity": 3, "confidence": 60, "country": "Freedonia", "report_count": 12,
         "created_at": "2026-11-27T10:00:00Z", "sources": []}


def site(monkeypatch, outcome="done"):
    monkeypatch.delenv("STRINGER_JOB", raising=False)
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=lambda: 500)
    s = server.Site(gate=g, fetch=lambda: [EVENT])
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
        if s.record(EVENT["id"])["state"] == state:
            return True
        time.sleep(0.02)
    return False


def test_list_click_and_video(monkeypatch):
    s, done = site(monkeypatch)
    s.refresh()
    assert "Made-up storm floods the Avalon port" in s.page()
    r = s.make(EVENT["id"], "visitor-1")
    assert r["ok"] and r["code"] == "making"
    assert done.wait(5) and wait_for(s, "done")
    assert s.record(EVENT["id"])["video"]["duration_s"] == 60.0
    again = s.make(EVENT["id"], "visitor-2")                  # one video per event
    assert not again["ok"] and again["code"] == "has_video"


def test_no_video_is_shown_with_its_reason(monkeypatch):
    s, done = site(monkeypatch, outcome="no_video")
    s.refresh()
    assert s.make(EVENT["id"], "visitor-1")["ok"]
    assert done.wait(5) and wait_for(s, "no_video")
    assert "too few claims" in s.record(EVENT["id"])["why"]


def test_unknown_event_is_refused(monkeypatch):
    s, _ = site(monkeypatch)
    s.refresh()
    assert s.make("not-in-the-list", "visitor-1")["code"] == "unknown"


def test_page_escapes_titles(monkeypatch):
    s, _ = site(monkeypatch)
    EVENT2 = dict(EVENT, id="00000000-0000-4000-8000-0000000000x2", title="<script>alert(1)</script> flood")
    s.fetch = lambda: [EVENT2]
    s.refresh()
    assert "<script>alert(1)</script>" not in s.page()


def test_media_names():
    ok = "videos/00000000-0000-4000-8000-0000000000we/20261127T041927-bfb309ea/video.mp4"
    assert server.MEDIA.fullmatch(ok)
    assert server.MEDIA.fullmatch(ok.replace("video.mp4", "poster.jpg"))
    for bad in ("stories/x/y/story_file.json", "videos/x/y/script.json", "videos/x/video.mp4",
                "videos/x/y/../video.mp4x", "videos/x y/z/video.mp4", "gate/slots.json"):
        assert not server.MEDIA.fullmatch(bad), bad


def test_job_records_site_paths(monkeypatch, tmp_path):
    from scripts import run_job
    out = tmp_path / "video"
    out.mkdir()
    for f in ("video.mp4", "poster.jpg"):
        (out / f).write_bytes(b"x")
    (tmp_path / "script.json").write_text("{}")
    sent = []
    monkeypatch.setenv("STRINGER_VIDEO_BUCKET", "vids")
    monkeypatch.setenv("STRINGER_PRIVATE_BUCKET", "priv")
    monkeypatch.setattr(run_job.cloud, "upload", lambda b, n, p, **kw: sent.append((b, n)) or "")
    rec = {"video": {"mp4": str(out / "video.mp4"), "duration_s": 60.0}, "seconds": 200.0, "usd": 0.5}
    v = run_job.upload_outputs(tmp_path, rec, EVENT["id"], "T1")
    assert v["url"] == f"/media/videos/{EVENT['id']}/T1/video.mp4" and server.MEDIA.fullmatch(v["url"][7:])
    assert v["poster"].endswith("/poster.jpg") and v["captions"] is None
    assert ("priv", f"stories/{EVENT['id']}/T1/script.json") in sent
    assert all(b == "vids" for b, n in sent if n.startswith("videos/"))
