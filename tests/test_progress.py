"""Live progress (stringer/progress.py) and the website's data builders (web/data.py), offline. Made-up runs,
story files and outlets only."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from stringer import progress as P
from stringer.gate import MemoryStore
from web import data as D

EID = "00000000-0000-4000-8000-00000000pr01"
NOW = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def stored(store, tid="T1"):
    return store.get(P.key_for(EID, tid))[0]


# ---- the writer ------------------------------------------------------------------------------------------------

def test_steps_calls_and_the_finish_are_written():
    store, clock = MemoryStore(), Clock()
    p = P.Progress(store, EID, "T1", title="Made-up flood", clock=clock, say=lambda *_: None)
    assert stored(store)["state"] == "running" and stored(store)["steps"] == {}
    p.begin("sides")
    clock.t += 1.0
    p.call({"name": "lens", "model": "haiku-5-5", "usd": 0.0002, "tokens_in": 900, "tokens_out": 80, "seconds": 0.9})
    p.call({"name": "lens", "model": "haiku-5-5", "error": "timeout"})
    assert stored(store)["calls"] == []                    # a burst of calls waits for the next write
    clock.t += 0.5
    p.end("sides", {"seconds": 1.5, "usd": 0.0002, "kind": "two sides"})
    doc = stored(store)
    assert doc["current"] is None and doc["model_calls"] == 1 and len(doc["calls"]) == 2
    assert [c["step"] for c in doc["calls"]] == ["sides", "sides"] and doc["calls"][1]["error"] is True
    assert doc["steps"]["sides"] == {"t0": 0.0, "t1": 1.5, "seconds": 1.5, "usd": 0.0002,
                                     "info": {"kind": "two sides"}, "hands_on": None}
    p.begin("gather")
    clock.t += 10
    p.end("gather", {"seconds": 10, "usd": 0.05, "articles": 4},
          searches=[{"name": "side a", "query": "flood port"}, {"name": "side b", "query": "flood harbour"}])
    doc = stored(store)
    assert doc["usd"] == pytest.approx(0.0502)
    assert [q["t"] for q in doc["searches"]] == pytest.approx([1.5 + 10 / 3, 1.5 + 20 / 3], abs=0.01)
    p.begin("same_story")
    clock.t += 2
    p.finish("failed", "x" * 900)
    doc = stored(store)
    assert doc["state"] == "failed" and len(doc["why"]) == 600 and doc["current"] is None
    assert doc["steps"]["same_story"]["stopped_at"] == pytest.approx(13.5) and doc["seconds"] == pytest.approx(13.5)


def test_a_store_that_fails_never_stops_the_video():
    class Broken(MemoryStore):
        def update(self, key, fn):
            raise OSError("the bucket is away")
    said = []
    p = P.Progress(Broken(), EID, "T1", clock=Clock(), say=said.append)
    p.begin("sides")
    p.end("sides", {"seconds": 1, "usd": 0})
    p.finish("done")
    assert len(said) == 1 and "could not save" in said[0]


def test_keys_are_safe():
    assert P.key_for(EID, "20261127T150000-ab12") == f"progress/{EID}/20261127T150000-ab12.json"
    assert P.key_for("../../slots", "a/b") == "progress/slots/ab.json"
    with pytest.raises(ValueError):
        P.key_for("../..", "T1")


def test_eight_agents_in_pipeline_order():
    assert P.KEYS == ["sides", "gather", "same_story", "balance_pick", "story_file", "fact_check", "script", "video"]
    assert P.purpose("query_writer") == "write the searches"


# ---- hand-ons from a story folder --------------------------------------------------------------------------------

def folder(tmp_path):
    """A made-up story folder: two sides of invented outlets, four articles, a log of searches."""
    d = tmp_path / "story"
    d.mkdir()
    lens = {"kind": "two sides", "reason": "Invented outlets split on who is to blame.", "chosen_by": "model",
            "sides": [{"side_id": "harbour", "label": "Harbour papers", "outlet_ids": ["o1", "o2"]},
                      {"side_id": "inland", "label": "Inland papers", "outlet_ids": ["o3"]}]}
    arts = [{"id": f"a{i}", "outlet": o, "text": "SECRET ARTICLE TEXT"} for i, o in enumerate(["o1", "o2", "o3", "o9"])]
    gather = {"event": {"id": EID, "title": "Made-up flood"}, "counts": {"articles": 4, "outlets": 4},
              "log": {"searches": [{"qid": "q1_side_a", "query": "flood port", "results": 3,
                                    "attempts": [{"credits": 1}, {"credits": 1, "cached": True}]}],
                      "guardian": [{"query": "flood", "results": 2}]}}
    (d / "lens.json").write_text(json.dumps(lens))
    (d / "gather.json").write_text(json.dumps(gather))
    (d / "articles.jsonl").write_text("\n".join(json.dumps(a) for a in arts) + "\n")
    return d


def test_hand_ons_are_short_and_have_no_article_text(tmp_path):
    read = P.folder_reader(folder(tmp_path))
    sides = P.summarize("sides", read)
    assert sides["kind"] == "two sides" and sides["side_a"]["label"] == "Harbour papers" and sides["side_b"]["n"] == 1
    g = P.summarize("gather", read)
    assert g["articles"] == 4 and g["by_side"] == {"Harbour papers": 2, "Inland papers": 1, "elsewhere": 1}
    qs = P.searches_of(read)
    assert [(q["name"], q["credits"], q["note"]) for q in qs] == [("side a", 1, "tried again"), ("Guardian", 0, "")]
    assert "SECRET" not in json.dumps([sides, g, qs])
    assert P.summarize("script", lambda name: 1 / 0) is None          # a summary that can't be made is None


# ---- receipts ---------------------------------------------------------------------------------------------------

def story_files(root, tid="T1", two_sides=True):
    d = root / EID / tid
    d.mkdir(parents=True)
    sides = ({"kind": "two sides", "A": {"side_id": "harbour", "label": "Harbour papers", "articles": 2},
              "B": {"side_id": "inland", "label": "Inland papers", "articles": 0}}
             if two_sides else {"kind": "none", "reason": "Every invented outlet tells it the same way."})
    sf = {"event": {"title": "Made-up flood", "category": "disaster", "country": "Freedonia", "lat": "1.5",
                    "confidence": 60, "location_name": "Avalon"},
          "sides": sides,
          "sources": [{"outlet_name": "Avalon Herald", "group": "A", "text": "SECRET ARTICLE TEXT"},
                      {"outlet_name": "Port Daily", "group": "A", "quote": "SECRET QUOTE"},
                      {"outlet_name": "Avalon Herald", "group": "A"}],
          "perspectives": [{"side_id": "harbour", "points": [{"point": "The harbour board was warned."}]}],
          "claims": [{"id": "c1", "status": "confirmed"}, {"id": "c2", "status": "say_with_source"},
                     {"id": "c3", "status": "dropped"}],
          "fact_check": {"counts": {"claims": 3, "confirmed": 1, "say_with_source": 1, "dropped": 1}}}
    sc = {"title": "Avalon's port floods", "caption": "The port closed after a storm. More rain is due.",
          "sources_card": {"read": 3, "elsewhere": 2, "outlets": ["Avalon Herald", "Port Daily"],
                           "ai_mark": "Made with AI from 3 news articles"},
          "beats": [{"n": 1}, {"n": 2}]}
    (d / "checked_story_file.json").write_text(json.dumps(sf))
    (d / "script.json").write_text(json.dumps(sc))
    return d


def test_receipts_are_a_summary_without_article_text(tmp_path):
    story_files(tmp_path)
    r = D.receipts(D.Files(local=tmp_path), EID, "T1")
    assert r["title"] == "Avalon's port floods" and r["dek"] == "The port closed after a storm."
    assert r["sides"]["kind"] == "two sides" and r["sides"]["A"]["outlets"] == ["Avalon Herald", "Port Daily"]
    assert r["sides"]["howA"] == "The harbour board was warned." and "no coverage" in r["sides"]["howB"]
    assert r["sides"]["words"] == []                                    # word pairs: dropped
    assert (r["claims"], r["claimsBacked"], r["confirmed"], r["sayWho"], r["dropped"]) == (3, 2, 1, 1, 1)
    assert r["articles"] == 3 and r["outlets"] == 2 and r["elsewhere"] == 2 and r["beats"] == 2
    assert r["event"]["lat"] == 1.5 and r["event"]["place"] == "Avalon" and r["event"]["confidence"]
    assert "SECRET" not in json.dumps(r)


def test_receipts_without_a_divide_or_files(tmp_path):
    story_files(tmp_path, two_sides=False)
    r = D.receipts(D.Files(local=tmp_path), EID, "T1")
    assert r["sides"] == {"kind": "no real divide", "reason": "Every invented outlet tells it the same way."}
    assert D.receipts(D.Files(local=tmp_path), EID, "T2") is None
    assert D.receipts(D.Files(local=tmp_path / "nothing"), EID, "T1") is None


class Resp:
    def __init__(self, code, body=b""):
        self.status_code, self.body = code, body

    def iter_content(self, n):
        yield self.body

    def close(self):
        pass


def test_story_files_from_the_bucket():
    """stories/<event>/ holds the newest run, and run.json names its ticket (scripts/run_job.py); runs before
    Nov 27 kept stories/<event>/<ticket>/. A video's receipts must come from its own run."""
    objects = {f"stories/{EID}/run.json": {"ticket": "T2", "outcome": "no_video"},
               f"stories/{EID}/pipeline.json": {"run": "T2"},
               f"stories/{EID}/T1/pipeline.json": {"run": "T1"}}
    asked = []

    def opener(bucket, name):
        asked.append((bucket, name))
        return Resp(200, json.dumps(objects[name]).encode()) if name in objects else Resp(404)
    clock = Clock(0.0)
    f = D.Files(bucket="priv", opener=opener, clock=clock)
    assert f.read(EID, "T2", "pipeline.json") == {"run": "T2"}
    assert f.read(EID, "T1", "pipeline.json") == {"run": "T1"}             # an older video's own folder
    assert f.read(EID, "T3", "pipeline.json") is None                      # not this run's files
    n = len(asked)
    assert f.read(EID, "T2", "pipeline.json") == {"run": "T2"} and f.read(EID, "T3", "pipeline.json") is None
    assert len(asked) == n and all(b == "priv" for b, _ in asked)          # found files and recent misses are kept
    objects.update({f"stories/{EID}/run.json": {"ticket": "T3"}, f"stories/{EID}/pipeline.json": {"run": "T3"}})
    clock.t += D.MISS_S + 1
    assert f.read(EID, "T3", "pipeline.json") == {"run": "T3"}             # a rerun's files show a minute later
    assert f.read(EID, "T2", "pipeline.json") == {"run": "T2"}             # still T2's own


# ---- the progress page's run -------------------------------------------------------------------------------------

PIPELINE = {"event": EID, "title": "Made-up flood", "started": "2026-11-27T14:00:00Z",
            "finished": "2026-11-27T14:02:00Z", "outcome": "no_video", "why": "script: too few claims",
            "seconds": 120.0, "usd": 0.31, "model_calls": 12, "estimate_after_gather": {"usd": 0.9},
            "steps": {"sides": {"seconds": 2.0, "usd": 0.001, "kind": "two sides"},
                      "gather": {"seconds": 30.0, "usd": 0.1, "articles": 4},
                      "same_story": {"seconds": 8.0, "usd": 0.01},
                      "balance_pick": {"seconds": 1.0, "usd": 0.0},
                      "story_file": {"seconds": 60.0, "usd": 0.15},
                      "fact_check": {"seconds": 10.0, "usd": 0.02},
                      "script": {"seconds": 9.0, "usd": 0.029, "status": "no video"}}}


def test_a_finished_run_from_its_pipeline_json(tmp_path):
    doc = D.from_pipeline(PIPELINE, P.folder_reader(folder(tmp_path)), "T1")
    assert doc["state"] == "no_video" and doc["from_pipeline_json"] and doc["estimate_usd"] == 0.9
    assert [(k, s["t0"], s["t1"]) for k, s in doc["steps"].items()][:3] == [("sides", 0.0, 2.0), ("gather", 2.0, 32.0),
                                                                           ("same_story", 32.0, 40.0)]
    assert [q["name"] for q in doc["searches"]] == ["side a", "Guardian"]
    v = D.run_view(doc, now=NOW, cap_usd=5.0)
    assert v["outcome"] == "no_video" and v["live"] is False and v["calls_recorded"] is False
    st = {s["key"]: s["status"] for s in v["steps"]}
    assert st["script"] == "done" and st["video"] == "skipped" and v["model_calls"] == 12
    assert v["steps"][0]["counts"] == {"kind": "two sides"} and v["estimate_usd"] == 0.9


def test_a_live_run_view():
    doc = {"event": EID, "ticket": "T1", "title": "Made-up flood", "started": "2026-11-27T14:59:00Z", "state": "running",
           "current": "story_file", "usd": 0.2, "model_calls": 3,
           "steps": {"sides": {"t0": 0, "t1": 2, "usd": 0.001}, "gather": {"t0": 2, "t1": 30, "usd": 0.1},
                     "story_file": {"t0": 31, "t1": None}},
           "calls": [{"t": 1.0, "step": "sides", "name": "lens", "model": "haiku-5-5", "usd": 0.001},
                     {"t": 40.0, "step": "story_file", "name": "brief_read", "model": "sonnet-5-5", "error": True}],
           "searches": [{"t": 10.0, "step": "gather", "name": "side a", "query": "flood"}]}
    v = D.run_view(doc, now=NOW, by="you")
    assert v["live"] and v["outcome"] is None and v["elapsed"] == 60.0 and v["seconds"] == 60.0 and v["by"] == "you"
    st = {s["key"]: s["status"] for s in v["steps"]}
    assert st == {"sides": "done", "gather": "done", "same_story": "waiting", "balance_pick": "waiting",
                  "story_file": "running", "fact_check": "waiting", "script": "waiting", "video": "waiting"}
    assert v["models"] == {"haiku-5-5": "Claude Haiku 5.5", "sonnet-5-5": "Claude Sonnet 5.5"}
    times = [e["t"] for e in v["timeline"]]
    kinds = [e["type"] for e in v["timeline"]]
    assert times == sorted(times) and [kinds.count(k) for k in ("step_start", "step_end", "call", "search")] == [3, 2, 2, 1]
    assert v["steps"][4]["calls"][0]["note"] == "the call failed"
    step, pct = D.progress_pct(doc, NOW)
    typical = {a["key"]: a["typical_s"] for a in P.AGENTS}
    want = 100 * (typical["sides"] + typical["gather"] + 29) / sum(typical.values())
    assert step == "story_file" and pct == pytest.approx(want, abs=0.1)
    assert D.progress_pct(None, NOW) == (None, 0.0)


def test_which_run_an_event_shows():
    making = {"state": "making", "ticket": {"id": "T3"}, "history": [{"ticket": "T1", "outcome": "done"}]}
    assert D.last_ticket(making) == "T3"
    rec = {"state": "done", "history": [{"ticket": "T1", "outcome": "done"}, {"ticket": "T2", "outcome": "failed"}]}
    assert D.last_ticket(rec) == "T2" and D.last_ticket(rec, ("done",)) == "T1"
    assert D.last_ticket({"video": {"url": f"/media/videos/{EID}/T9/video.mp4"}}) == "T9"
    assert D.last_ticket({}) is None
