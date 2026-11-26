"""Module 6 on story folders: the checked Story File written beside module 5's files, the run's spend cap,
and replay of the eval's saved answers. Made-up stories only; the model is a fake."""
import json

import pytest
from test_fact_check import ARTICLES, FACTS, Table, claim, fake_judge, story

from scripts import check_story_files as csf
from stringer import fact_check, models, story_file
from stringer.evals.cache import CallCache, call_key

ALIAS = "haiku-5-5"


def make_folder(root, name, claims, trace="trace-1"):
    d = root / name
    story_file.write(d, FACTS, story(claims))
    (d / "articles.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ARTICLES.values()), encoding="utf-8")
    (d / "gather.json").write_text(json.dumps({"langfuse_trace_id": trace}), encoding="utf-8")
    return d


def paid_fake(answers, log):
    """models.complete's shape: (step, messages, model=, trace_id=, name=, **params) -> Result with a cost."""
    judge = fake_judge(answers)

    def complete(step, messages, model=None, trace_id=None, name=None, **params):
        log.append(dict(step=step, model=model, trace_id=trace_id, messages=messages, params=params))
        usage = dict(input_uncached=1000, cached=0, cache_write=0, output=200, reasoning=0, total=1200)
        return models.Result(text=judge(messages, name=name, **params).text, model=model, usage=usage,
                             cost=models.cost_of(model, usage), latency_s=0.1)
    return complete


@pytest.fixture
def folders(tmp_path, monkeypatch):
    stories = tmp_path / "stories"
    monkeypatch.setattr(csf.paths, "STORIES", stories)
    monkeypatch.setattr(csf, "OUT", tmp_path / "checked")
    make_folder(stories, "11111111-aaaa", [claim("C1", "Ferries will carry drivers across the river.", "a_l1#1", "a_s1#2"),
                                           claim("C2", "The bridge closed on Friday.", "a_n1#1", "a_s1#1")])
    make_folder(stories, "22222222-bbbb", [claim("C1", "Engineers expect three months of repairs.", "a_n1#2")], trace="trace-2")
    (stories / "33333333-gather-only").mkdir()            # a folder module 5 hasn't filled: skipped
    return stories


def test_checked_file_is_written_beside_module_5s_files_and_lists_bad_translations(folders):
    d = folders / "11111111-aaaa"
    facts_before = (d / "facts.jsonl").read_text(encoding="utf-8")
    facts, sf = fact_check.check_folder(d, fake_judge({"C1": dict(bad_translations=["K1"])}), model="fake", table=Table())
    p = fact_check.write_checked(d, facts, sf)
    assert p == d / fact_check.CHECKED_FILE
    got = fact_check.read_checked(d)
    assert [c["status"] for c in got["claims"]] == ["confirmed", "confirmed"]
    assert got["fact_check"]["bad_translation_facts"] == ["a_l1#1"]
    assert (d / "facts.jsonl").read_text(encoding="utf-8") == facts_before          # module 5's files untouched
    assert story_file.read(d)[1]["claims"][0]["status"] is None


def test_run_checks_every_filled_folder_into_its_trace_and_writes_a_summary(folders):
    log = []
    caller = csf.Caller(ALIAS, 1.0, complete=paid_fake({"C2": dict(verdict="not backed", problem="other")}, log))
    s = csf.run(1.0, caller=caller, table=Table())
    assert [r["story"] for r in s["stories_detail"]] == ["11111111", "22222222"]
    assert {x["trace_id"] for x in log} == {"trace-1", "trace-2"} and {x["step"] for x in log} == {"fact_check"}
    one = fact_check.read_checked(folders / "11111111-aaaa")
    assert [c["status"] for c in one["claims"]] == ["confirmed", "dropped"]
    assert one["fact_check"]["model"] == ALIAS
    assert s["totals"]["dropped"] == 1 and s["paid_calls"] == len(log) == 2 and s["stopped"] is None
    assert s["spent_usd"] == pytest.approx(sum(r["cost_usd"] for r in s["stories_detail"]), abs=1e-4) and s["spent_usd"] > 0
    assert json.loads((csf.OUT / "summary.json").read_text())["stories"] == 2


def test_run_stops_before_a_call_that_could_pass_the_cap_and_leaves_that_story_unwritten(folders):
    log = []
    s = csf.run(0.0001, caller=csf.Caller(ALIAS, 0.0001, complete=paid_fake({}, log)), table=Table())
    assert log == [] and s["stories"] == 0 and s["stopped"].startswith("11111111")
    assert not (folders / "11111111-aaaa" / fact_check.CHECKED_FILE).exists()
    assert not (csf.OUT / "summary.json").exists()


def test_reuse_takes_the_evals_answer_for_the_same_call_and_pays_for_the_rest(folders, tmp_path):
    first = []
    csf.run(1.0, only="22222222", caller=csf.Caller(ALIAS, 1.0, complete=paid_fake({}, first)), table=Table())
    cache = CallCache(tmp_path / "eval_cache")
    lm = models.spec(ALIAS)["litellm"]
    for x in first:                                       # as the eval would have saved them (max_tokens kept)
        cache.put(call_key(lm, x["messages"], x["params"]),
                  dict(text=json.dumps({"claims": [dict(id="C1", why="", verdict="not backed", problem="other", speaker="",
                                                         bad_cards=[], bad_translations=[], against_event=False)]}),
                       usage=dict(input_uncached=1000, cached=0, cache_write=0, output=200, reasoning=0, total=1200)))
    log = []
    s = csf.run(1.0, caller=csf.Caller(ALIAS, 1.0, reuse=True, cache=cache, complete=paid_fake({}, log)), table=Table())
    assert s["replayed_calls"] == 1 and s["paid_calls"] == 1 == len(log)          # story 2 replayed, story 1 paid
    assert {x["trace_id"] for x in log} == {"trace-1"}
    assert fact_check.read_checked(folders / "22222222-bbbb")["claims"][0]["status"] == "dropped"   # the saved answer
    assert s["spent_usd"] == pytest.approx(s["stories_detail"][0]["cost_usd"], abs=1e-5)


def test_estimate_counts_calls_cost_and_what_the_eval_already_answered(folders, tmp_path, monkeypatch):
    monkeypatch.setattr(csf, "count_tokens", lambda lm, msgs: 5000)
    monkeypatch.setattr(csf.models, "model_for", lambda step: ALIAS)
    cache = CallCache(tmp_path / "eval_cache")
    sf2 = story_file.read(folders / "22222222-bbbb")[1]
    pw = fact_check.paperwork(sf2, FACTS, ARTICLES, Table())
    c = fact_check.judge_plan(sf2, FACTS, pw, ALIAS)[0]
    cache.put(call_key(models.spec(ALIAS)["litellm"], c["messages"], c["params"]), dict(text="{}", usage={}))
    s = csf.estimate(table=Table(), cache=cache)
    assert (s["stories"], s["calls"], s["eval_answered"], s["input_tokens"]) == (2, 2, 1, 10000)
    assert 0 < s["usd_unanswered"] < s["usd"]
    assert (csf.OUT / "estimate.json").exists()


def test_only_takes_several_short_ids(folders):
    assert [d.name for d in csf.story_dirs("2222, 1111")] == ["11111111-aaaa", "22222222-bbbb"]
    assert [d.name for d in csf.story_dirs()] == ["11111111-aaaa", "22222222-bbbb"]


def test_run_needs_a_cap():
    with pytest.raises(SystemExit):
        csf.main(["run"])
