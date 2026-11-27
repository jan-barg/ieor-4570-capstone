"""The Gate content-check eval plug-in, on a made-up sample, with the keyword rule and a fake model."""
import json

from stringer.evals import runner
from stringer.evals.gate_policy_eval import GatePolicyEval


def sample(tmp_path):
    rows = [("a1", "labeled", "refuse", "Gunman Wounds Pupils at Primary School"),
            ("a2", "ordinary", "allow", "Parliament Passes Budget"),
            ("a3", "hard", "allow", "Teen Arrested Over Mall Plot"),
            ("a4", "made_up", "refuse", "Toddler Trapped in Well for Two Days")]
    items = [dict(id=k, short=k, group=g, draft=lab, source="claude-draft", reason="", your_call=False, split="tune",
                  event=dict(id=k, title=t, summary="", category="conflict", subtype="x", country=""))
             for k, g, lab, t in rows]
    p = tmp_path / "sample.json"
    p.write_text(json.dumps({"version": "t", "items": items}))
    return p


def test_keyword_baseline_scores_and_mistakes(tmp_path):
    step = GatePolicyEval(sample=sample(tmp_path), labels=tmp_path / "none.json")
    rec = runner.run_eval(step, model="code:keywords", split="all", out_dir=tmp_path)
    s = rec["summary"]
    assert s["labeled"] == 4 and s["missed_refusals"] == 1 and s["wrong_refusals"] == 0
    assert s["missed_refusals_real"] == 0 and s["caught"] == 0.5 and s["score"] == 0.75
    assert [m["story"] for m in step.mistakes(rec)] == ["a4"]


def test_jan_answers_override_drafts(tmp_path):
    lab = tmp_path / "labels.json"
    lab.write_text(json.dumps({"version": "jan-review-1", "labels": {"a3": {"label": "refuse"}}}))
    step = GatePolicyEval(sample=sample(tmp_path), labels=lab)
    key = step.load_key()
    assert key["a3"] == {"label": "refuse", "source": "jan", "group": "hard"} and key["a2"]["source"] == "claude-draft"


def test_model_run_counts_retries(tmp_path):
    class R:
        def __init__(self, t):
            self.text, self.usage, self.cost, self.latency_s = t, {"input_uncached": 10, "output": 5}, {"total": 0.0}, 0.0
    answers = iter(["oops"] + ['{"reason": "r", "child_role": "none", "verdict": "allow"}'] * 10)

    def complete(model, messages, **kw):
        return R(next(answers))
    step = GatePolicyEval(sample=sample(tmp_path), labels=tmp_path / "none.json")
    rec = runner.run_eval(step, model="haiku-5-5", split="all", out_dir=tmp_path, complete_fn=complete, workers=1,
                          use_cache=False)
    assert rec["summary"]["retries"] == 1 and rec["summary"]["fallbacks"] == 0
