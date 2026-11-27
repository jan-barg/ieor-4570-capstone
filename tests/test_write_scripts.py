"""Module 7 on story folders: script.json written beside the checked file, the spend cap, replay of the
eval's saved answers, and the free estimate. The made-up flood story; the model is a fake."""
import json

import pytest
from test_script_writer import ARTICLES, FACTS, Fake, answer, story

from scripts import write_scripts as ws
from stringer import fact_check, models, script_writer as sw, story_file
from stringer.evals.cache import CallCache, call_key


def make_folder(root, name, trace="trace-1"):
    d = root / name
    sf = story()
    story_file.write(d, FACTS, sf)
    (d / fact_check.CHECKED_FILE).write_text(json.dumps(sf), encoding="utf-8")
    (d / "articles.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ARTICLES.values()), encoding="utf-8")
    (d / "gather.json").write_text(json.dumps({"langfuse_trace_id": trace}), encoding="utf-8")
    return d


def paid(fake, log):
    """models.complete's shape: (step, messages, model=, trace_id=, name=, **params) -> Result with a cost."""
    def complete(step, messages, model=None, trace_id=None, name=None, **params):
        log.append(dict(step=step, model=model, trace_id=trace_id, name=name))
        usage = dict(input_uncached=1000, cached=0, cache_write=0, output=200, reasoning=0, total=1200)
        return models.Result(text=fake(messages, name=name, model=model, **params).text, model=model, usage=usage,
                             cost=models.cost_of(model, usage), latency_s=0.1)
    return complete


@pytest.fixture
def folders(tmp_path, monkeypatch):
    stories = tmp_path / "stories"
    monkeypatch.setattr(ws.paths, "STORIES", stories)
    monkeypatch.setattr(ws, "OUT", tmp_path / "scripts")
    make_folder(stories, "11111111-aaaa")
    make_folder(stories, "22222222-bbbb", trace="trace-2")
    (stories / "33333333-not-checked").mkdir()            # no checked file yet: skipped
    return stories


def test_run_writes_a_script_per_checked_folder_into_its_trace(folders, tmp_path):
    log = []
    caller = ws.Caller(5.0, complete=paid(Fake([answer(), answer()]), log))
    s = ws.run(5.0, caller=caller)
    assert s["stories"] == 2 and s["statuses"]["ok"] == 2 and s["stopped"] is None
    got = sw.read_script(folders / "11111111-aaaa")
    assert got["status"] == "ok" and got["model"] == models.model_for("script") and got["cost_usd"] > 0
    assert [x["model"] for x in log[:3]] == [models.model_for("script"), models.model_for("script_line_check"),
                                             models.model_for("script_words")]
    assert {x["trace_id"] for x in log[:3]} == {"trace-1"} and {x["trace_id"] for x in log[3:]} == {"trace-2"}
    assert (tmp_path / "scripts" / "summary.json").exists()


def test_run_stops_before_the_cap(folders):
    caller = ws.Caller(0.0001, complete=paid(Fake([answer()]), []))
    s = ws.run(0.0001, caller=caller)
    assert s["stories"] == 0 and "not written" in s["stopped"]
    assert not (folders / "11111111-aaaa" / sw.SCRIPT_FILE).exists()


def test_eval_answers_are_replayed_for_free(folders, tmp_path):
    cache = CallCache(tmp_path / "cache")
    d = folders / "11111111-aaaa"
    facts, _ = story_file.read(d)
    p = sw.packet(fact_check.read_checked(d), facts, sw.contexts_for(facts, fact_check.read_articles(d)))
    writer = models.model_for("script")
    params = sw._params(p, writer)
    params.pop("model")
    cache.put(call_key(models.spec(writer)["litellm"], sw.messages_for(p), params),
              dict(text=json.dumps(answer()), usage=dict(input_uncached=10, cached=0, cache_write=0, output=10)))
    log = []
    caller = ws.Caller(5.0, reuse=True, cache=cache, complete=paid(Fake([]), log))   # the fake writer has nothing left
    s = ws.run(5.0, only="11111111", caller=caller)
    assert caller.replayed == 1 and s["statuses"]["ok"] == 1
    assert [x["name"] for x in log] == ["script line check", "script words"]


def test_estimate_is_free_and_counts_the_fix_round(folders):
    s = ws.estimate()
    assert s["stories"] == 2 and s["calls"] == 2 * 6 and s["usd"] > 0     # writer, fix, line, words, line, words
