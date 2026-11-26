"""The coverage judge's prompts (cov-1, cov-2) and how the three news brief evals pick one. Made-up data only."""
import json
from types import SimpleNamespace

import pytest

from stringer import brief_read
from stringer.evals import brief_merge_eval, brief_onecall_eval, brief_read_eval as bre

FACTS = [dict(id="a1#1", fact="Air defenses did not intercept any of the drones.", quote_en="none were downed")]


def test_cov_1_stays_the_default_and_old_version_names_do_not_change():
    assert bre.JUDGE_PROMPT == "cov-1" and bre.JUDGE_PROMPTS["cov-1"] is bre.JUDGE_SYSTEM
    assert bre.BriefReadEval().version == f"{brief_read.VERSION}-n10"
    assert bre.judge_messages(["No drones were shot down."], FACTS)[0][0]["content"] == bre.JUDGE_SYSTEM


def test_cov_2_has_the_every_part_rule_and_made_up_examples():
    p = bre.JUDGE_PROMPTS["cov-2"]
    assert p.startswith(bre.JUDGE_SYSTEM.split("\n\n")[0])
    assert "taken together, state every part" in p and "Words in brackets are background" in p
    assert "Examples (made up, not from this story):" in p and p.count("\n- Must-have:") == 7
    assert p.endswith(bre.JUDGE_SYSTEM.split("\n\n")[-1])
    msgs, ids = bre.judge_messages(["No drones were shot down."], FACTS, "cov-2")
    assert msgs[0]["content"] == p and ids == {"F1": "a1#1"} and "M1: No drones were shot down." in msgs[1]["content"]


def test_every_eval_names_a_non_default_judge_prompt_in_its_version():
    for cls, base in [(bre.BriefReadEval, {}), (brief_onecall_eval.BriefOneCallEval, {}),
                      (brief_merge_eval.BriefMergeEval, {})]:
        plain, cov2 = cls(**base), cls(judge_prompt="cov-2", **base)
        assert cov2.version == plain.version + "-cov-2" and cov2.judge_prompt == "cov-2"
        assert cls(judge_prompt="cov-1", **base).version == plain.version
    with pytest.raises(KeyError, match="known: cov-1, cov-2"):
        bre.BriefReadEval(judge_prompt="cov-9")


def test_the_judge_call_uses_the_chosen_prompt_and_records_it():
    seen = []

    def complete(messages, name=None, **p):
        seen.append(messages)
        return SimpleNamespace(text=json.dumps({"results": [dict(id="M1", found=True, cards=["F1"])]}))
    ctx = SimpleNamespace(complete=complete)
    out = bre.BriefReadEval(judge_prompt="cov-2")._judge(["No drones were shot down."], FACTS, ctx)
    assert seen[0][0]["content"] == bre.JUDGE_SYSTEM_2
    assert out == {"model": bre.JUDGE, "prompt": "cov-2", "results": {"M1": {"found": True, "cards": ["a1#1"]}}}


def _saved_run(tmp_path):
    out = {"articles": [{"facts": FACTS}], "judge": {"model": "old", "results": {"M1": {"found": False, "cards": []}}},
           "kept": "as saved"}
    p = tmp_path / "run.json"
    p.write_text(json.dumps({"run_id": "brief_read-old", "items_detail": [
        {"story": "s1", "output": out}, {"story": "s2", "output": None}]}))
    return p


def test_a_judge_only_rerun_keeps_the_saved_output_and_asks_only_the_judge(tmp_path):
    e = bre.BriefReadEval(judge_prompt="cov-2", from_run=_saved_run(tmp_path))
    item = SimpleNamespace(story="s1", data={"sheet": {"facts": ["No drones were shot down."]}})
    names = []

    def complete(messages, name=None, model=None, **p):
        names.append((name, model))
        return SimpleNamespace(text=json.dumps({"results": [dict(id="M1", found=True, cards=["F1"])]}))
    out = e.run(item, SimpleNamespace(complete=complete, model="deepseek-v4.1-flash"))
    assert names == [("brief_read judge", bre.JUDGE)]
    assert out["kept"] == "as saved" and out["rejudged_from"] == "brief_read-old"
    assert out["judge"]["prompt"] == "cov-2" and out["judge"]["results"]["M1"] == {"found": True, "cards": ["a1#1"]}
    assert e.saved()["stories"].keys() == {"s1"}
    (call,) = e.plan(item, "deepseek-v4.1-flash")
    assert call["model"] == bre.JUDGE and call["messages"][0]["content"] == bre.JUDGE_SYSTEM_2
    assert call["params"] == {"max_tokens": bre.JUDGE_MAX_TOKENS, "response_format": bre.JUDGE_SCHEMA}


def test_the_estimate_prices_a_planned_call_at_its_own_model(tmp_path):
    from stringer import models
    from stringer.evals import runner

    class Two(runner.Step):
        def plan(self, item, model):
            msgs = [{"role": "user", "content": "x " * 400}]
            return [{"messages": msgs, "expect_output": 1000}, {"model": bre.JUDGE, "messages": msgs, "expect_output": 1000}]
    item = SimpleNamespace(story="s1")
    cache = runner.CallCache(tmp_path / "cache")
    got = runner.estimate(Two(), model="deepseek-v4.1-flash", items=[item], cache=cache)
    a, b = models.spec("deepseek-v4.1-flash"), models.spec(bre.JUDGE)
    n = runner.count_tokens(a["litellm"], [{"role": "user", "content": "x " * 400}])
    m = runner.count_tokens(b["litellm"], [{"role": "user", "content": "x " * 400}])
    want = (n * a["input"] + 1000 * a["output"] + m * b["input"] + 1000 * b["output"]) / 1e6
    assert got["calls"] == 2 and abs(got["est_usd"] - round(want, 4)) < 1e-4
