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
    def __init__(self, too_costly=False):
        self.charges, self.checkpoints, self.too_costly = [], [], too_costly

    def charge(self, usd, what=""):
        self.charges.append((what, round(usd, 6)))

    def checkpoint(self, stage="after_gather", n_articles=None):
        self.checkpoints.append(n_articles)
        if self.too_costly:
            raise TooCostly("the rest would pass the cap")
        return {"usd": 0.5}


class TooCostly(RuntimeError):
    pass


class Lens:
    kind = "split"


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Stand-ins for modules 1-8. Each one 'spends' through the model layer's cost hook."""
    order = []

    def spend(step, usd):
        models._tell_listeners(step, step, {"total": usd})

    traces = {}

    def choose(ev, table, complete, model=""):
        order.append("sides")
        spend("lens", 0.001)
        return Lens(), {"chosen_by": "model"}

    def gather_event(ev, lens, table, tv, gd, **kw):
        order.append("gather")
        traces["gather"], traces["cache"] = kw.get("trace_id"), kw["cache"].root
        spend("query_writer", 0.002)
        tv.ledger.spent += 7
        d = pipeline.store.story_dir(ev.id)
        d.mkdir(parents=True, exist_ok=True)
        arts = [{"id": f"a{i}", "outlet": f"o{i}", "text": "x"} for i in range(5)]
        meta = {"event": {"id": ev.id, "title": ev.title}, "lens": {"kind": "split", "sides": []},
                "langfuse_trace_id": kw.get("trace_id"), "counts": {"articles": len(arts)}}
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
    monkeypatch.setattr(pipeline.pick, "pick", lambda arts, lens: {"picked": [a["id"] for a in arts[:3]], "flags": []})

    def build_story(meta, arts, trace_id=None, early=None):
        order.append("story_file")
        traces["story_file"] = trace_id
        spend("brief_read", 0.05)
        early([{"id": "f1"}], {"claims": [{"id": "c1"}]})           # the fact check's judge, beside the last calls
        return [{"id": "f1"}], {"claims": [{"id": "c1"}]}

    def judge_early(sf, facts, articles, complete, model="", table=None):
        order.append("judge")
        spend("fact_check", 0.01)
        return {"verdicts": {"c1": {}}, "calls": 1, "errors": [], "missing": []}
    monkeypatch.setattr(pipeline.fact_check, "judge_early", judge_early)
    monkeypatch.setattr(pipeline.story_file, "build_story", build_story)
    monkeypatch.setattr(pipeline.story_file, "validate", lambda sf, facts: [])
    monkeypatch.setattr(pipeline.story_file, "write", lambda d, facts, sf: None)

    def check_folder(d, complete, model="", table=None, judged=None):
        order.append("fact_check")
        traces["judged"] = judged
        return [], {"fact_check": {"counts": {"claims": 1, "confirmed": 1}}}
    monkeypatch.setattr(pipeline.fact_check, "check_folder", check_folder)
    monkeypatch.setattr(pipeline.fact_check, "write_checked", lambda d, facts, sf: None)
    state = {"script": "ok", "broke": "", "video": "rendered"}

    def write_folder(d, complete, model=""):
        order.append("script")
        spend("script", 0.04)
        return {"status": state["script"], "words": 140, "reason": "too few claims", "broke": state["broke"],
                "held": ["too few articles"]}
    monkeypatch.setattr(pipeline.sw, "write_folder", write_folder)
    monkeypatch.setattr(pipeline.sw, "write_file", lambda d, s: None)

    from stringer.video import make

    def fake_make(d, engine=None, out_dir=None, music=None, render=True, trace_id=None):
        order.append("video")
        traces["video"] = trace_id
        status = state["video"] if render else "planned"
        return {"status": status, "out_dir": str(d / "video"), "why": "the hook failed the last check",
                "steps": {"voice": {"credits": 250, "duration": 61.0, "seconds": 9.0}, "render": {"seconds": 40.0}}}
    monkeypatch.setattr(make, "make", fake_make)
    return dict(order=order, state=state, traces=traces,
                dirs=dict(stories_dir=tmp_path / "stories", raw_dir=tmp_path / "raw"))


def test_runs_every_module_in_order_and_charges_the_ticket(fakes):
    t = FakeTicket()
    rec = pipeline.run(EVENT, t, say=lambda *_: None, **fakes["dirs"])
    assert fakes["order"] == ["sides", "gather", "same_story", "story_file", "judge", "fact_check", "script", "video"]
    assert rec["outcome"] == "done" and rec["video"]["duration_s"] == 61.0
    charged = dict(t.charges)
    assert list(charged) == ["sides", "gather", "same_story", "balance_pick", "story_file", "fact_check",
                             "script", "video"]
    assert charged["gather"] == pytest.approx(0.002 + 7 * 0.008)            # model + Tavily credits
    assert charged["video"] == pytest.approx(250 * pipeline.ELEVENLABS_USD_PER_CREDIT)
    assert t.checkpoints == [3]                                              # the articles picked, not the 5 gathered
    assert rec["usd"] == pytest.approx(sum(charged.values()), abs=1e-4)
    assert rec["model_usd_by_step"]["brief_read"] == pytest.approx(0.05)
    # the judge ran inside the Story File step; its cost is filed under the fact check
    assert charged["story_file"] == pytest.approx(0.05) and charged["fact_check"] == pytest.approx(0.01)
    assert fakes["traces"]["judged"]["verdicts"] == {"c1": {}}
    # one trace for the whole video, handed to every module that makes calls
    tid = rec["trace_id"]
    assert tid and fakes["traces"]["gather"] == tid == fakes["traces"]["story_file"] == fakes["traces"]["video"]
    assert str(fakes["traces"]["cache"]).endswith("article_cache") and "frozen" not in str(fakes["traces"]["cache"])
    assert rec["steps"]["script"]["held"] == ["too few articles"]            # a note; the video was still made
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


def test_a_breakdown_is_a_failure_that_can_be_retried_not_a_no_video(fakes):
    fakes["state"].update(script="no video", broke="the script writer gave no usable answer")
    with pytest.raises(pipeline.CouldNotFinish, match="script writer"):
        pipeline.run(EVENT, FakeTicket(), say=lambda *_: None, **fakes["dirs"])
    saved = json.loads((fakes["dirs"]["stories_dir"] / EVENT["id"] / "pipeline.json").read_text())
    assert saved["outcome"] == "failed" and "CouldNotFinish" in saved["why"] and "script" in saved["steps"]
    assert "video" not in fakes["order"]


def test_too_costly_leaves_its_record_and_still_raises(fakes):
    with pytest.raises(TooCostly):
        pipeline.run(EVENT, FakeTicket(too_costly=True), say=lambda *_: None, **fakes["dirs"])
    saved = json.loads((fakes["dirs"]["stories_dir"] / EVENT["id"] / "pipeline.json").read_text())
    assert saved["outcome"] == "no_video" and saved["why"].startswith("too costly") and "story_file" not in fakes["order"]


def test_a_stopped_video_is_no_video_and_a_plan_only_run_is_not_a_video(fakes):
    fakes["state"]["video"] = "stopped"
    rec = pipeline.run(EVENT, FakeTicket(), say=lambda *_: None, **fakes["dirs"])
    assert rec["outcome"] == "no_video" and rec["why"] == "video: the hook failed the last check"
    fakes["state"]["video"] = "rendered"
    rec = pipeline.run(EVENT, FakeTicket(), say=lambda *_: None, render=False, **fakes["dirs"])
    assert rec["outcome"] == "planned" and "mp4" not in rec["video"]


def test_the_story_folders_are_put_back_when_the_run_ends(fakes):
    from stringer import paths
    before = (paths.STORIES, paths.RAW)
    pipeline.run(EVENT, None, say=lambda *_: None, **fakes["dirs"])
    assert (paths.STORIES, paths.RAW) == before
    fakes["state"].update(script="no video", broke="the line check gave no answer for 3 line(s)")
    with pytest.raises(pipeline.CouldNotFinish):
        pipeline.run(EVENT, None, say=lambda *_: None, **fakes["dirs"])
    assert (paths.STORIES, paths.RAW) == before


def test_script_calls_are_filed_under_their_steps():
    assert pipeline._script_step("script") == "script" and pipeline._script_step("script fix") == "script"
    assert pipeline._script_step("script line check retry") == "script_line_check"
    assert pipeline._script_step("script words") == "script_words"
