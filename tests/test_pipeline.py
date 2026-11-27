"""The one-event runner (stringer/pipeline.py) and its cost hook, offline: every module is a stand-in.
Made-up event and articles only."""
from __future__ import annotations

import json

import pytest

from stringer import feed, models, pipeline

EVENT = {"id": "00000000-0000-4000-8000-00000000e2e1", "title": "Flooding closes the port of Avalon",
         "summary": "Made-up event for the runner test.", "category": "disaster", "subtype": "flood",
         "severity": 3, "confidence": 60, "country": "Freedonia", "report_count": 9,
         "created_at": "2026-11-27T10:00:00Z", "sources": [{"url": "https://example.org/a",
                                                            "published_at": "2026-11-27T09:00:00Z"}]}


class FakeTicket:
    def __init__(self):
        self.charges, self.checkpoints = [], []

    def charge(self, usd, what=""):
        self.charges.append((what, round(usd, 6)))

    def checkpoint(self, stage="after_gather", n_articles=None):
        self.checkpoints.append(n_articles)
        return {"usd": 0.5}


class Lens:
    kind = "split"


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Stand-ins for modules 1-8. Each one 'spends' through the model layer's cost hook."""
    order = []

    def spend(step, usd):
        models._tell_listeners(step, step, {"total": usd})

    def choose(ev, table, complete, model=""):
        order.append("sides")
        spend("lens", 0.001)
        return Lens(), {"chosen_by": "model"}

    def gather_event(ev, lens, table, tv, gd, **kw):
        order.append("gather")
        spend("query_writer", 0.002)
        tv.ledger.spent += 7
        d = pipeline.store.story_dir(ev.id)
        d.mkdir(parents=True, exist_ok=True)
        arts = [{"id": f"a{i}", "outlet": f"o{i}", "text": "x"} for i in range(5)]
        meta = {"event": {"id": ev.id, "title": ev.title}, "lens": {"kind": "split", "sides": []},
                "langfuse_trace_id": None, "counts": {"articles": len(arts)}}
        (d / "articles.jsonl").write_text("\n".join(json.dumps(a) for a in arts) + "\n")
        (d / "gather.json").write_text(json.dumps(meta))
        return meta

    def filter_story(event, arts, complete, lens=None):
        order.append("same_story")
        spend("same_story", 0.003)
        return {"version": "t", "verdicts": {a["id"]: {"verdict": "same", "reason": "", "by": "model"} for a in arts},
                "counts": {"same": len(arts)}, "flags": [], "problems": []}

    monkeypatch.setattr(pipeline.outlets, "table", lambda: object())
    monkeypatch.setattr(pipeline.lens_step, "choose", choose)
    monkeypatch.setattr(pipeline.lens_step, "record_new_sides", lambda ev, lens: 0)
    monkeypatch.setattr(pipeline.gather_run, "gather_event", gather_event)
    monkeypatch.setattr(pipeline.same_story, "filter_story", filter_story)
    monkeypatch.setattr(pipeline.balance, "estimate", lambda lens, arts, t: {"sides": []})
    monkeypatch.setattr(pipeline.pick, "pick", lambda arts, lens: {"picked": [a["id"] for a in arts], "flags": []})

    def build_story(meta, arts, trace_id=None):
        order.append("story_file")
        spend("brief_read", 0.05)
        return [{"id": "f1"}], {"claims": [{"id": "c1"}]}
    monkeypatch.setattr(pipeline.story_file, "build_story", build_story)
    monkeypatch.setattr(pipeline.story_file, "validate", lambda sf, facts: [])
    monkeypatch.setattr(pipeline.story_file, "write", lambda d, facts, sf: None)

    def check_folder(d, complete, model="", table=None):
        order.append("fact_check")
        spend("fact_check", 0.01)
        return [], {"fact_check": {"counts": {"claims": 1, "confirmed": 1}}}
    monkeypatch.setattr(pipeline.fact_check, "check_folder", check_folder)
    monkeypatch.setattr(pipeline.fact_check, "write_checked", lambda d, facts, sf: None)
    state = {"script": "ok"}

    def write_folder(d, complete, model=""):
        order.append("script")
        spend("script", 0.04)
        return {"status": state["script"], "words": 140, "reason": "too few claims"}
    monkeypatch.setattr(pipeline.sw, "write_folder", write_folder)
    monkeypatch.setattr(pipeline.sw, "write_file", lambda d, s: None)

    from stringer.video import make

    def fake_make(d, engine=None, out_dir=None, music=None, render=True):
        order.append("video")
        return {"status": "rendered", "out_dir": str(d / "video"),
                "steps": {"voice": {"credits": 250, "duration": 61.0, "seconds": 9.0}, "render": {"seconds": 40.0}}}
    monkeypatch.setattr(make, "make", fake_make)
    return dict(order=order, state=state, dirs=dict(stories_dir=tmp_path / "stories", raw_dir=tmp_path / "raw"))


def test_runs_every_module_in_order_and_charges_the_ticket(fakes):
    t = FakeTicket()
    rec = pipeline.run(EVENT, t, say=lambda *_: None, **fakes["dirs"])
    assert fakes["order"] == ["sides", "gather", "same_story", "story_file", "fact_check", "script", "video"]
    assert rec["outcome"] == "done" and rec["video"]["duration_s"] == 61.0
    charged = dict(t.charges)
    assert list(charged) == ["sides", "gather", "same_story", "balance_pick", "story_file", "fact_check",
                             "script", "video"]
    assert charged["gather"] == pytest.approx(0.002 + 7 * 0.008)            # model + Tavily credits
    assert charged["video"] == pytest.approx(250 * pipeline.ELEVENLABS_USD_PER_CREDIT)
    assert t.checkpoints == [5]                                              # after Gather, before module 5
    assert rec["usd"] == pytest.approx(sum(charged.values()), abs=1e-4)
    assert rec["model_usd_by_step"]["brief_read"] == pytest.approx(0.05)
    saved = json.loads((fakes["dirs"]["stories_dir"] / EVENT["id"] / "pipeline.json").read_text())
    assert saved["outcome"] == "done" and set(saved["steps"]) == set(charged)


def test_script_with_no_video_stops_before_the_video(fakes):
    fakes["state"]["script"] = "no video"
    rec = pipeline.run(EVENT, FakeTicket(), say=lambda *_: None, **fakes["dirs"])
    assert rec["outcome"] == "no_video" and "too few claims" in rec["why"]
    assert "video" not in fakes["order"]


def test_without_a_ticket_nothing_is_charged(fakes):
    rec = pipeline.run(EVENT, None, say=lambda *_: None, **fakes["dirs"])
    assert rec["outcome"] == "done" and "estimate_after_gather" not in rec


def test_cost_listener_sees_calls_only_while_on():
    seen = []
    with models.on_cost(lambda step, alias, usd: seen.append((step, usd))):
        models._tell_listeners("lens", "haiku", {"total": 0.25})
    models._tell_listeners("lens", "haiku", {"total": 1.0})
    assert seen == [("lens", 0.25)]


def test_feed_find_needs_one_match():
    evs = [{"id": "abc111"}, {"id": "abc222"}, {"id": "def333"}]
    assert feed.find("def", evs)["id"] == "def333"
    assert feed.find("abc", evs) is None and feed.find("zzz", evs) is None
    assert feed._events_of({"count": 1, "events": [{"id": "x"}]}) == [{"id": "x"}]


def test_vertex_project_can_be_named_by_the_environment(monkeypatch):
    alias = next(a for a, m in models.config()["models"].items() if m["provider"] == "vertex")
    monkeypatch.setenv("STRINGER_VERTEX_PROJECT", "made-up-project")
    kw = models.call_kwargs(alias, [{"role": "user", "content": "hi"}])
    assert kw["vertex_project"] == "made-up-project"
    assert kw["extra_headers"]["x-goog-user-project"] == "made-up-project"


# ---- live progress: a Gate ticket brings its own progress record (module 9) -------------------------------------

class GateTicket(FakeTicket):
    """A ticket like the Gate's: it knows its store, so the run writes progress/<event>/<ticket>.json."""

    def __init__(self, store):
        super().__init__()
        self.id = "20261127T100000-made"
        self.gate = type("G", (), {"store": store})()


def progress_doc(store):
    from stringer import progress
    return store.get(progress.key_for(EVENT["id"], "20261127T100000-made"))[0]


def test_a_gate_ticket_gets_live_progress(fakes, monkeypatch):
    from stringer.gate import MemoryStore
    store = MemoryStore()
    real_pick = pipeline.pick.pick

    def pick_with_a_call(arts, lens):                       # one model call, told the way models.complete tells it
        models._tell_call({"step": "pick", "name": "pick", "model": "haiku-5-5", "usd": 0.001, "tokens_in": 10,
                           "tokens_out": 5, "seconds": 0.2, "error": None})
        return real_pick(arts, lens)
    monkeypatch.setattr(pipeline.pick, "pick", pick_with_a_call)
    rec = pipeline.run(EVENT, GateTicket(store), say=lambda *_: None, **fakes["dirs"])
    doc = progress_doc(store)
    assert rec["outcome"] == "done" and doc["state"] == "done" and doc["current"] is None
    assert list(doc["steps"]) == ["sides", "gather", "same_story", "balance_pick", "story_file", "fact_check",
                                  "script", "video"]
    assert all(s["t1"] is not None and s["t1"] >= s["t0"] for s in doc["steps"].values())
    assert [(c["step"], c["model"]) for c in doc["calls"]] == [("balance_pick", "haiku-5-5")]
    assert doc["usd"] == pytest.approx(rec["usd"], abs=1e-4)
    models._tell_call({"model": "after the run"})           # the listener is gone once the run ends
    assert len(progress_doc(store)["calls"]) == 1


def test_progress_of_a_run_that_stops(fakes):
    from stringer.gate import MemoryStore
    store = MemoryStore()
    fakes["state"]["script"] = "no video"
    pipeline.run(EVENT, GateTicket(store), say=lambda *_: None, **fakes["dirs"])
    doc = progress_doc(store)
    assert doc["state"] == "no_video" and "too few claims" in doc["why"] and "video" not in doc["steps"]


def test_progress_of_a_run_that_crashes(fakes, monkeypatch):
    from stringer.gate import MemoryStore
    store = MemoryStore()

    def broken(*a, **kw):
        raise RuntimeError("made-up crash")
    monkeypatch.setattr(pipeline.story_file, "build_story", broken)
    with pytest.raises(RuntimeError):
        pipeline.run(EVENT, GateTicket(store), say=lambda *_: None, **fakes["dirs"])
    doc = progress_doc(store)
    assert doc["state"] == "failed" and "made-up crash" in doc["why"]
    assert "stopped_at" in doc["steps"]["story_file"] and doc["steps"]["story_file"]["t1"] is None
