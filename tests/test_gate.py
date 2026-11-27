"""Module 0, the Gate: eligibility, the shared store, the limits, the claim, the ticket, reports.
Made-up events only; no model calls (the content check uses the keyword rule here)."""
import datetime as dt
import json
import threading

import pytest

from stringer.gate import (ClaimLost, Conflict, Gate, GCSStore, LocalStore, MemoryStore, TooCostly, VideoOverBudget,
                           cost, rules)
from stringer.gate.store import NO_CHANGE


def ev(i="e1", **kw):
    base = dict(id=f"test-{i}", title="Parliament Passes Budget",
                summary="Lawmakers approved the annual budget after a long debate.", category="political",
                subtype="legislation", severity=2, confidence=55, report_count=9, country="Freedonia")
    base.update(kw)
    return base


class Clock:
    def __init__(self, t="2026-12-09T15:00:00+00:00"):
        self.t = dt.datetime.fromisoformat(t)

    def __call__(self):
        return self.t

    def add(self, **kw):
        self.t += dt.timedelta(**kw)


def gate(store=None, clock=None, credits=500, cfg=None, **kw):
    return Gate(store or MemoryStore(), cfg=cfg, complete=None, model="", now=clock or Clock(),
                tavily_left=(lambda: credits), **kw)


def cfg_with(**limits):
    c = json.loads(json.dumps(rules.config()))
    c["limits"].update(limits)
    return c


# ---- eligibility -----------------------------------------------------------------------------------

def test_eligibility_rules():
    assert rules.failures(ev()) == []
    assert rules.failures(ev(report_count=6)) == ["reports"]
    assert rules.failures(ev(severity=1)) == ["severity"]
    assert rules.failures(ev(confidence=30)) == ["confidence"]
    assert rules.failures(ev(category="sports")) == ["category"]
    assert rules.failures(ev(category="Disaster")) == []
    # the Archive gives numbers as strings; missing values fail
    assert rules.failures(ev(severity="2", confidence="31", report_count="7")) == []
    assert rules.failures(ev(severity="", report_count=None)) == ["severity", "reports"]


# ---- the store -------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["memory", "local"])
def test_store_compare_and_write(kind, tmp_path):
    s = MemoryStore() if kind == "memory" else LocalStore(tmp_path)
    assert s.get("a/b.json") == (None, None)
    v1 = s.put("a/b.json", {"n": 1}, None)
    with pytest.raises(Conflict):
        s.put("a/b.json", {"n": 2}, None)              # create-only fails when it exists
    with pytest.raises(Conflict):
        s.put("a/b.json", {"n": 2}, "999")             # stale version
    s.put("a/b.json", {"n": 2}, v1)
    assert s.get("a/b.json")[0] == {"n": 2}
    s.add("log/x.json", {"k": 1})
    assert s.list("a/") == ["a/b.json"] and s.list("log/") == ["log/x.json"]
    assert s.update("a/b.json", lambda cur: (NO_CHANGE, cur["n"])) == 2


@pytest.mark.parametrize("kind", ["memory", "local"])
def test_store_update_is_safe_under_many_threads(kind, tmp_path):
    s = MemoryStore() if kind == "memory" else LocalStore(tmp_path)

    def bump(cur):
        cur = cur or {"n": 0}
        cur["n"] += 1
        return cur, None
    threads = [threading.Thread(target=lambda: [s.update("c.json", bump) for _ in range(10)]) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert s.get("c.json")[0]["n"] == 80


def test_local_store_refuses_keys_outside_its_folder(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path / "g").get("../escape.json")


class FakeResp:
    def __init__(self, status, body=b"", headers=None, js=None):
        self.status_code, self.content, self.headers, self._js = status, body, headers or {}, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeGCS:
    """Just enough of the Cloud Storage JSON API: media get, media upload with ifGenerationMatch, list."""

    def __init__(self):
        self.objs = {}

    def get(self, url, params=None, timeout=None):
        if params and params.get("alt") == "media":
            from urllib.parse import unquote
            name = unquote(url.rsplit("/o/", 1)[1])
            if name not in self.objs:
                return FakeResp(404)
            body, gen = self.objs[name]
            return FakeResp(200, body, {"x-goog-generation": str(gen)})
        items = [{"name": n} for n in sorted(self.objs) if n.startswith(params["prefix"])]
        return FakeResp(200, js={"items": items})

    def post(self, url, params=None, data=None, headers=None, timeout=None):
        name, want = params["name"], int(params["ifGenerationMatch"])
        have = self.objs.get(name, (None, 0))[1]
        if want != have:
            return FakeResp(412)
        self.objs[name] = (data, have + 1)
        return FakeResp(200, js={"generation": str(have + 1)})


def test_gcs_store_uses_generation_match():
    fake = FakeGCS()
    s = GCSStore("bucket", "gate", session=fake)
    assert s.get("events/x.json") == (None, None)
    v = s.put("events/x.json", {"a": 1}, None)
    assert v == "1" and "gate/events/x.json" in fake.objs
    with pytest.raises(Conflict):
        s.put("events/x.json", {"a": 2}, None)
    s.update("events/x.json", lambda cur: (dict(cur, a=cur["a"] + 1), None))
    assert s.get("events/x.json") == ({"a": 2}, "2")
    assert s.list("events/") == ["events/x.json"]


def test_gcs_store_waits_out_a_busy_answer_but_never_resends_a_write_after_a_network_error(monkeypatch):
    from stringer.gate import store as store_mod
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)

    class Flaky(FakeGCS):
        def __init__(self, get_plan=(), post_plan=()):
            super().__init__()
            self.get_plan, self.post_plan, self.gets, self.posts = list(get_plan), list(post_plan), 0, 0

        def get(self, url, params=None, timeout=None):
            self.gets += 1
            step = self.get_plan.pop(0) if self.get_plan else None
            if isinstance(step, Exception):
                raise step
            return FakeResp(step) if step else super().get(url, params=params, timeout=timeout)

        def post(self, url, params=None, data=None, headers=None, timeout=None):
            self.posts += 1
            step = self.post_plan.pop(0) if self.post_plan else None
            if isinstance(step, Exception):
                raise step
            return FakeResp(step) if step else super().post(url, params=params, data=data, headers=headers, timeout=timeout)

    busy = Flaky(get_plan=[503, ConnectionError("reset")], post_plan=[503])
    s = GCSStore("bucket", "gate", session=busy)
    assert s.put("slots.json", {"n": 1}, None) == "1" and busy.posts == 2          # 503, then written once
    assert s.get("slots.json") == ({"n": 1}, "1") and busy.gets == 3               # 503, a network error, then read
    lost = Flaky(post_plan=[ConnectionError("the answer never came")])
    with pytest.raises(ConnectionError):                                             # maybe written: don't send it twice
        GCSStore("bucket", "gate", session=lost).put("slots.json", {"n": 1}, None)
    assert lost.posts == 1
    still = Flaky(get_plan=[503, 503, 503])
    with pytest.raises(RuntimeError):                                                # busy three times: the error is real
        GCSStore("bucket", "gate", session=still).get("slots.json")


def test_voice_credits_left_is_the_limit_minus_the_use_and_none_when_unknown(monkeypatch):
    import io
    import json as js
    from stringer.gate import credits
    monkeypatch.setattr(credits.keys, "get", lambda name: "k")
    monkeypatch.setattr(credits.urllib.request, "urlopen",
                        lambda req, timeout=None: io.BytesIO(js.dumps({"character_count": 20000, "character_limit": 100000}).encode()))
    assert credits._ask_elevenlabs() == 80000          # (the tests' shared setup stubs voice_credits_left itself)

    def down(req, timeout=None):
        raise OSError("no network")
    monkeypatch.setattr(credits.urllib.request, "urlopen", down)
    assert credits._ask_elevenlabs() is None


# ---- check, screen, start --------------------------------------------------------------------------

def test_go_and_a_second_click_waits():
    g = gate()
    d = g.start(ev(), "visitor-a")
    assert d.ok and d.code == "go" and d.ticket
    d2 = g.start(ev(), "visitor-b")
    assert not d2.ok and d2.code == "making" and "being made" in d2.message
    assert g.status()["videos_today"] == 1 and g.status()["being_made"] == 1


def test_screen_leaves_out_refused_events_without_saying_why():
    g = gate()
    child = ev("c1", title="Drone Strike Kills Four-Year-Old Girl", summary="A girl was killed.", category="conflict")
    small = ev("s1", report_count=3)
    ok = ev("o1")
    shown = g.screen([child, small, ok])
    assert [l.event["id"] for l in shown] == [ok["id"]] and shown[0].state == "ready"
    d = g.start(child, "v")
    assert d.code == "policy" and d.message == "This story isn't available for a video."


def test_content_check_is_saved_and_redone_when_the_text_changes():
    calls = []

    class Fake:
        def __init__(self, text):
            self.text = text

    def complete(messages, name=None, **params):
        calls.append(messages[-1]["content"])
        return Fake('{"reason": "budget vote", "child_role": "none", "verdict": "allow"}')
    g = Gate(MemoryStore(), complete=complete, model="haiku-5-5", now=Clock(), tavily_left=None)
    e = ev()
    assert g.verdict(e)["verdict"] == "allow" and g.verdict(e)["by"] == "model"
    assert len(calls) == 1                              # saved
    g.verdict(dict(e, summary="Lawmakers approved the budget late at night."))
    assert len(calls) == 2                              # the text changed


def test_day_cap_counts_videos_not_dollars():
    clock = Clock()
    g = gate(clock=clock, cfg=cfg_with(videos_per_day=2, per_visitor_per_hour=10, at_once=10))
    for i in range(2):
        t = g.start(ev(f"d{i}"), f"v{i}").ticket
        t.finish(video={"url": "x"})
    d = g.start(ev("d9"), "v9")
    assert d.code == "day_full" and "2 videos" in d.message
    clock.add(hours=15)                                 # 06:00Z next day: past midnight in New York
    assert g.start(ev("d9"), "v9").ok


def test_day_starts_at_midnight_new_york():
    clock = Clock("2026-12-10T04:59:00+00:00")         # 23:59 in New York, Dec 9
    g = gate(clock=clock)
    assert g.day() == "2026-12-09"
    clock.add(minutes=2)
    assert g.day() == "2026-12-10"


def test_at_once_limit_and_release_on_finish():
    g = gate(cfg=cfg_with(at_once=1, per_visitor_per_hour=10))
    t = g.start(ev("a"), "v").ticket
    assert g.start(ev("b"), "v").code == "busy"
    t.finish(error="boom")
    assert g.start(ev("b"), "v").ok


def test_visitor_pace_and_rollback():
    clock = Clock()
    g = gate(clock=clock)
    for i in range(3):
        g.start(ev(f"p{i}"), "same-person").ticket.finish(video={"url": "u"})
    d = g.start(ev("p3"), "same-person")
    assert d.code == "visitor_pace" and d.retry_after_s and "Try again in 60 minutes" in d.message
    # the refused click took nothing: the event is free and the day's count is 3
    assert g.status()["videos_today"] == 3
    assert g.start(ev("p3"), "someone-else").ok
    clock.add(minutes=61)
    assert g.start(ev("p4"), "same-person").ok


def test_visitors_are_stored_only_as_a_salted_hash():
    s = MemoryStore()
    g = gate(store=s)
    g.start(ev(), "203.0.113.7")
    dump = json.dumps({k: s.get(k)[0] for k in s.list("")})
    assert "203.0.113.7" not in dump
    assert g.visitor_key("203.0.113.7") == gate(store=s).visitor_key("203.0.113.7")   # same salt on every machine


def test_crashed_run_frees_after_the_lease_and_counts_tries():
    clock = Clock()
    g = gate(clock=clock, cfg=cfg_with(max_tries=2, per_visitor_per_hour=10, at_once=10))
    t1 = g.start(ev(), "v").ticket
    assert g.start(ev(), "v").code == "making"
    clock.add(minutes=21)                               # no progress for longer than the lease
    t2 = g.start(ev(), "v").ticket
    assert t2 and t2.id != t1.id
    with pytest.raises(ClaimLost):
        t1.beat()                                       # the old run must stop
    t2.finish(error="service down")
    assert g.start(ev(), "v").code == "too_many_tries"


def test_no_video_is_final_and_has_video_links_it():
    g = gate()
    g.start(ev("n"), "v").ticket.finish(no_video="too little coverage from one side")
    d = g.start(ev("n"), "v")
    assert d.code == "no_video" and d.message == "This story isn't available for a video."
    assert g.screen([ev("n")]) == []
    g.start(ev("h"), "v").ticket.finish(video={"url": "https://example.test/v.mp4"})
    d = g.start(ev("h"), "v")
    assert d.code == "has_video" and d.video["url"].endswith("v.mp4")
    assert [l.state for l in g.screen([ev("h")])] == ["has_video"]


def test_closed_mode_and_low_searches():
    assert gate(mode="closed").start(ev(), "v").code == "closed"
    assert gate(mode="closed").screen([ev()]) == []
    assert gate(credits=10).start(ev(), "v").code == "searches_low"
    assert gate(credits=None).start(ev(), "v").ok           # unknown credits never block


def test_cost_is_worked_out_before_spending():
    est = cost.estimate("start")
    assert 0.2 < est["usd"] < 5 and "searches" in est["parts"]
    assert cost.estimate("after_gather", 200)["usd"] > cost.estimate("after_gather", 19)["usd"]
    g = gate(cfg=cfg_with(max_video_usd=0.05))
    assert g.start(ev(), "v").code == "too_costly"            # refused before anything is spent
    g = gate(cfg=cfg_with(max_video_usd=1.0))
    t = g.start(ev(), "v").ticket
    t.charge(0.04, "searches")
    with pytest.raises(TooCostly):
        t.checkpoint(n_articles=2000)                      # a huge story stops after the searches
    assert t.checkpoint(n_articles=30)["usd"] < 1.0


def test_charge_backstop():
    g = gate()
    t = g.start(ev(), "v").ticket
    t.charge(0.25, "script")
    assert t.spent == 0.25 and t.parts == {"script": 0.25}
    with pytest.raises(VideoOverBudget):
        t.charge(5.0, "runaway")
    out = t.finish(error="over budget")
    assert out["outcome"] == "failed" and g.store.get(f"days/{g.day()}.json")[0]["spent_usd"] == 5.25


def test_ticket_can_be_picked_up_by_another_process():
    s = MemoryStore()
    g = gate(store=s)
    t = g.start(ev(), "v").ticket
    t.charge(0.1, "gather")
    t.beat()
    t2 = gate(store=s).ticket(ev()["id"])
    assert t2.id == t.id and abs(t2.spent - 0.1) < 1e-9


def test_concurrent_clicks_make_one_video():
    s = MemoryStore()
    results = []

    def click(i):
        results.append(gate(store=s).start(ev(), f"v{i}"))
    threads = [threading.Thread(target=click, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(d.ok for d in results) == 1
    assert {d.code for d in results if not d.ok} == {"making"}


# ---- reports, takedown, log ------------------------------------------------------------------------

def test_first_report_hides_and_admin_restores():
    g = gate()
    g.start(ev(), "v").ticket.finish(video={"url": "u"})
    eid = ev()["id"]
    r = g.report(eid, "viewer", "wrong_facts", "The date is wrong.\x00\x07")
    assert r["ok"] and r["hidden"]
    assert g.screen([ev()]) == [] and g.start(ev(), "v").code == "taken_down"
    rep = g.reports(eid)[0]
    assert rep["note"] == "The date is wrong." and rep["reason"] == "wrong_facts" and "viewer" not in json.dumps(rep)
    assert [h["id"] for h in g.hidden()] == [eid]
    g.restore(eid, by="jan", keep_up=True)
    assert [l.state for l in g.screen([ev()])] == ["has_video"]
    assert g.report(eid, "troll", "other", "")["hidden"] is False      # kept up after review
    kinds = [e["kind"] for e in g.log()]
    assert kinds.count("report") == 2 and "hidden" in kinds and "restored" in kinds and "start" in kinds


def test_report_limit_per_visitor_and_unknown_reason():
    g = gate()
    for i in range(5):
        assert g.report(ev(f"r{i}")["id"], "same", "nonsense")["ok"]
    assert g.reports()[0]["reason"] == "other"
    assert not g.report(ev("r9")["id"], "same", "other")["ok"]


def test_take_down_blocks_making_and_remake_resets():
    g = gate(cfg=cfg_with(per_visitor_per_hour=10))
    eid = ev()["id"]
    g.take_down(eid, by="jan", note="checking a fact")
    assert g.start(ev(), "v").code == "taken_down"
    g.restore(eid, by="jan")
    g.start(ev(), "v").ticket.finish(no_video="thin")
    assert g.start(ev(), "v").code == "no_video"
    g.remake(eid, by="jan")
    assert g.start(ev(), "v").ok
    assert "remake" in [e["kind"] for e in g.log()]


def test_local_store_end_to_end(tmp_path):
    g = gate(store=LocalStore(tmp_path / "gate"))
    t = g.start(ev(), "v").ticket
    t.finish(video={"url": "u"})
    assert (tmp_path / "gate" / "events").is_dir() and g.start(ev(), "v").code == "has_video"


# ---- Nov 27 review fixes -----------------------------------------------------------------------------

def test_low_voice_credits_pause_new_videos_and_an_unknown_count_does_not():
    assert gate(voice_left=lambda: 100).start(ev(), "v").code == "voice_low"
    assert gate(voice_left=lambda: None).start(ev(), "v").ok
    assert gate(voice_left=lambda: 100_000).start(ev(), "v").ok
    g = gate(voice_left=lambda: 100)
    assert g.status()["voice_low"] is True and "narration" in g.start(ev(), "v").message


def test_a_fallback_content_answer_is_kept_only_for_a_while():
    calls, down = [], [True]

    class Fake:
        def __init__(self, text):
            self.text = text

    def complete(messages, name=None, **params):
        calls.append(name)
        if down[0]:
            raise TimeoutError("the model is down")
        return Fake('{"reason": "budget vote", "child_role": "none", "verdict": "allow"}')
    clock = Clock()
    g = Gate(MemoryStore(), complete=complete, model="haiku-5-5", now=clock, tavily_left=None, voice_left=None)
    e = ev()
    first = g.verdict(e)
    assert first["fallback"] and first["by"].startswith("code:keywords") and len(calls) == 2    # one try, one retry
    g.verdict(e)
    assert len(calls) == 2                                   # within ten minutes the fallback answer is reused
    clock.add(minutes=11)
    down[0] = False
    again = g.verdict(e)
    assert again["by"] == "model" and not again["fallback"] and len(calls) == 3
    clock.add(days=3)
    g.verdict(e)
    assert len(calls) == 3                                   # the model's own answer is kept for good


def test_view_is_what_a_visitor_may_see():
    clock = Clock()
    g = gate(clock=clock)
    eid = ev()["id"]
    assert g.view(eid) == {"state": "ready", "failed": False}
    t = g.start(ev(), "v").ticket
    assert g.view(eid) == {"state": "making"}
    clock.add(minutes=25)                                    # the run went silent: crashed
    assert g.view(eid) == {"state": "ready", "failed": True}
    t2 = g.start(ev(), "w").ticket
    t2.finish(video={"url": f"/media/videos/{eid}/{t2.id}/video.mp4", "poster": f"/media/videos/{eid}/{t2.id}/poster.jpg"})
    assert g.view(eid)["state"] == "has_video" and g.view(eid)["video"]["url"].endswith("video.mp4")
    assert g.may_watch(f"videos/{eid}/{t2.id}/video.mp4") and g.may_watch(f"videos/{eid}/{t2.id}/captions.vtt")
    assert not g.may_watch(f"videos/{eid}/{t.id}/video.mp4")            # another run's files
    assert not g.may_watch("videos/unknown-event/x/video.mp4") and not g.may_watch("videos/../x/y")
    g.take_down(eid, by="jan")
    assert g.view(eid) == {"state": "unavailable"} and not g.may_watch(f"videos/{eid}/{t2.id}/video.mp4")
    other = ev("e2")
    g.start(other, "v").ticket.finish(no_video="script: the hook beat still fails")
    assert g.view(other["id"]) == {"state": "no_video", "reason": "script: the hook beat still fails"}


def test_cancel_gives_back_everything_the_click_took():
    g = gate(cfg=cfg_with(per_visitor_per_hour=1))
    eid = ev()["id"]
    t = g.start(ev(), "v").ticket
    assert g.status()["videos_today"] == 1 and g.status()["being_made"] == 1
    assert t.cancel("the job could not be started") is True
    st = g.status()
    assert st["videos_today"] == 0 and st["being_made"] == 0 and g.view(eid) == {"state": "ready", "failed": False}
    rec = g.store.get(f"events/{eid}.json")[0]
    assert rec["tries"] == 0 and rec["ticket"] is None
    assert g.start(ev(), "v").ok                              # the visitor's one start this hour came back too
    assert "start_cancelled" in [e["kind"] for e in g.log()]
    assert t.cancel() is False                               # a second cancel finds nothing of its own


def test_remake_clears_a_hide_and_a_report_hides_only_a_video():
    g = gate(cfg=cfg_with(per_visitor_per_hour=10))
    eid = ev()["id"]
    r = g.report(eid, "viewer", "wrong_facts", "no video yet")
    assert r["ok"] and r["hidden"] is False and g.start(ev(), "v").ok        # an unmade event stays on the list
    g.ticket(eid).finish(video={"url": "u"})
    assert g.report(eid, "viewer2", "wrong_facts")["hidden"] is True
    g.remake(eid, by="jan")
    assert g.view(eid) == {"state": "ready", "failed": False} and g.start(ev(), "v").ok


def test_finish_takes_an_empty_reason_as_no_video_and_nothing_as_failed():
    g = gate(cfg=cfg_with(per_visitor_per_hour=10))
    assert g.start(ev("a"), "v").ticket.finish(no_video="")["outcome"] == "no_video"
    assert g.store.get(f"events/{ev('a')['id']}.json")[0]["no_video_reason"] == "no video"
    assert g.start(ev("b"), "v").ticket.finish()["outcome"] == "failed"


class FlakyStore(MemoryStore):
    """A store whose writes to chosen keys fail while `down` is set (Cloud Storage having a bad minute)."""

    def __init__(self):
        super().__init__()
        self.down = ()

    def put(self, key, value, version):
        if any(key.startswith(k) for k in self.down):
            raise ConnectionError(f"could not write {key}")
        return super().put(key, value, version)


def test_a_missed_heartbeat_does_not_end_a_running_video():
    store, clock = FlakyStore(), Clock()
    g = gate(store=store, clock=clock)
    t = g.start(ev(), "v").ticket
    t._last_beat -= 3600                                     # a beat is due
    store.down = ("events/",)
    t.charge(0.01, "gather")                                 # the store is down: noted, not raised
    assert t.missed_beats == 1 and t.spent == 0.01
    store.down = ()
    t._last_beat -= 3600
    t.charge(0.01, "same_story")
    assert t.missed_beats == 1 and g.store.get(f"events/{ev()['id']}.json")[0]["ticket"]["spent"] == 0.02
    g.remake(ev()["id"], by="jan")                           # the claim is gone: that still stops the run
    t._last_beat -= 3600
    with pytest.raises(ClaimLost):
        t.charge(0.01, "story_file")


def test_a_store_error_in_the_middle_of_a_start_gives_the_claim_back():
    store = FlakyStore()
    g = gate(store=store)
    store.down = ("slots.json",)
    with pytest.raises(ConnectionError):
        g.start(ev(), "v")
    store.down = ()
    assert g.view(ev()["id"]) == {"state": "ready", "failed": False} and g.start(ev(), "v").ok
