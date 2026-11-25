"""The shared eval runner. Offline: a made-up step and a fake model, no keys, no network."""
import json

import pytest

from stringer import models, tracing
from stringer.evals import runner
from stringer.evals.cache import CallCache, call_key
from stringer.evals.runner import Item


@pytest.fixture(autouse=True)
def quiet_tracer(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "_TRACER", tracing.Tracer(log_dir=tmp_path / "log", enable_langfuse=False))


class FakeModel:
    """Answers with the upper-cased question; counts the calls it really gets."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *, model, messages, trace_id=None, name=None, metadata=None, **params):
        self.calls += 1
        n_in = runner.count_tokens(models.spec(model)["litellm"], messages)
        n_out = min(100, params["max_tokens"])
        usage = dict(prompt=n_in, input_uncached=n_in, cached=0, cache_write=0, output=n_out, reasoning=0,
                     total=n_in + n_out)
        q = messages[-1]["content"]
        return models.Result(text=q.upper(), model=model, usage=usage, cost=models.cost_of(model, usage),
                             latency_s=0.01)


class Shout(runner.Step):
    """Made-up step: the right answer to a word is the word in capitals."""
    name = "shout"
    version = "s1"
    model_step = "same_story"
    headline = ("accuracy",)

    def __init__(self, key=None):
        self.key = key or {"s1": "APPLE", "s2": "PEAR", "s3": "PLUM"}

    def load(self, only=None, split="tune"):
        words = {"s1": "apple", "s2": "pear", "s3": "plum"}
        return [Item(id=k, story=k, data={"word": w}, split="tune") for k, w in words.items()
                if not only or k in only]

    def load_key(self):
        return self.key

    def plan(self, item, model):
        return [{"messages": [{"role": "user", "content": item.data["word"]}], "params": {"max_tokens": 200},
                 "expect_output": 100}]

    def run(self, item, ctx):
        if ctx.is_code:
            return {"answer": item.data["word"].upper()}
        c = self.plan(item, ctx.model)[0]
        return {"answer": ctx.complete(c["messages"], **c["params"]).text}

    def score(self, item, output, key):
        return {"right": int(output["answer"] == key[item.id])}

    def summarize(self, items, scores):
        return {"accuracy": sum(s["right"] for s in scores) / len(scores)}


def test_run_scores_and_saves(tmp_path):
    fake = FakeModel()
    rec = runner.run_eval(Shout(), model="haiku-5-5", cap_usd=1.0, out_dir=tmp_path, complete_fn=fake)
    assert rec["status"] == "done" and rec["summary"]["accuracy"] == 1.0
    assert fake.calls == 3 and rec["calls"] == 3 and rec["cache_hits"] == 0
    assert rec["cost_usd"] > 0 and rec["spent_usd"] == pytest.approx(rec["cost_usd"], rel=1e-2)
    saved = json.loads((tmp_path / "runs" / "shout" / f"{rec['run_id']}.json").read_text())
    assert [r["story"] for r in saved["items_detail"]] == ["s1", "s2", "s3"]
    assert saved["items_detail"][0]["tokens"]["output"] == 100
    assert saved["tokens"]["output"] == 300
    index = (tmp_path / "runs" / "index.jsonl").read_text().splitlines()
    assert len(index) == 1 and "items_detail" not in json.loads(index[0])


def test_second_run_comes_from_the_cache(tmp_path):
    fake = FakeModel()
    first = runner.run_eval(Shout(), model="haiku-5-5", out_dir=tmp_path, complete_fn=fake)
    second = runner.run_eval(Shout(), model="haiku-5-5", out_dir=tmp_path, complete_fn=fake)
    assert fake.calls == 3                                  # nothing new was called
    assert second["cache_hits"] == 3 and second["spent_usd"] == 0
    assert second["cost_usd"] == pytest.approx(first["cost_usd"])   # list-price cost still shown
    other = runner.run_eval(Shout(), model="deepseek-v4.1-flash", out_dir=tmp_path, complete_fn=fake)
    assert fake.calls == 6 and other["cache_hits"] == 0     # another model is another key


def test_cost_cap_stops_the_run_before_overspending(tmp_path):
    fake = FakeModel()
    msgs = Shout().plan(Item("s1", "s1", {"word": "apple"}), "haiku-5-5")[0]["messages"]
    worst = runner.worst_case_usd("haiku-5-5", runner.count_tokens("anthropic/claude-haiku-5-5", msgs), 200)
    cap = 1.5 * worst                                       # room for one call, not two
    rec = runner.run_eval(Shout(), model="haiku-5-5", cap_usd=cap, workers=1, out_dir=tmp_path,
                          complete_fn=fake)
    assert rec["status"] == "stopped at cost cap"
    assert fake.calls == 1 and rec["spent_usd"] <= cap
    errs = [r["error"] for r in rec["items_detail"] if r["error"]]
    assert len(errs) == 2 and any("cost cap" in e for e in errs)


def test_budget_holds_and_settles():
    b = runner.Budget(1.0)
    h = b.hold(0.6)
    with pytest.raises(runner.BudgetExceeded):
        b.hold(0.5)                                         # 0.6 held + 0.5 > 1.0
    b.settle(h, 0.1)
    b.hold(0.5)                                             # spent 0.1 + 0.5 is fine now
    assert b.spent == pytest.approx(0.1)


def test_rescore_uses_saved_outputs_and_the_new_key(tmp_path):
    fake = FakeModel()
    rec = runner.run_eval(Shout(), model="haiku-5-5", out_dir=tmp_path, complete_fn=fake)
    re = runner.rescore(Shout(key={"s1": "APPLE", "s2": "WRONG", "s3": "PLUM"}), rec["run_id"], out_dir=tmp_path)
    assert fake.calls == 3
    assert re["summary"]["accuracy"] == pytest.approx(2 / 3) and re["rescored_from"] == rec["run_id"]
    assert re["spent_usd"] == 0 and re["cost_usd"] == pytest.approx(rec["cost_usd"])


def test_code_baseline_makes_no_calls(tmp_path):
    fake = FakeModel()
    rec = runner.run_eval(Shout(), model="code:upper", out_dir=tmp_path, complete_fn=fake)
    assert fake.calls == 0 and rec["summary"]["accuracy"] == 1.0 and rec["cost_usd"] == 0


def test_estimate_counts_tokens_and_skips_cached_calls(tmp_path):
    est = runner.estimate(Shout(), model="haiku-5-5", out_dir=tmp_path)
    assert est["calls"] == 3 and est["cached_calls"] == 0 and est["output_tokens"] == 300
    assert est["worst_usd"] >= est["est_usd"] > 0
    runner.run_eval(Shout(), model="haiku-5-5", out_dir=tmp_path, complete_fn=FakeModel(), only=["s1"])
    est = runner.estimate(Shout(), model="haiku-5-5", out_dir=tmp_path)
    assert est["cached_calls"] == 1


def test_compare_table_has_one_row_per_run(tmp_path):
    fake = FakeModel()
    runner.run_eval(Shout(), model="haiku-5-5", out_dir=tmp_path, complete_fn=fake, label="first try")
    runner.run_eval(Shout(), model="code:upper", out_dir=tmp_path, complete_fn=fake)
    t = runner.compare_table(Shout(), out_dir=tmp_path)
    lines = t.strip().splitlines()
    assert len(lines) == 4 and "accuracy" in lines[0] and "first try" in lines[2] and "code:upper" in lines[3]


def test_cache_key_changes_with_any_word_of_the_prompt(tmp_path):
    a = call_key("m", [{"role": "user", "content": "hello"}], {"max_tokens": 5})
    assert a == call_key("m", [{"role": "user", "content": "hello"}], {"max_tokens": 5})
    assert a != call_key("m", [{"role": "user", "content": "hello!"}], {"max_tokens": 5})
    assert a != call_key("m", [{"role": "user", "content": "hello"}], {"max_tokens": 6})
    c = CallCache(tmp_path)
    c.put(a, {"text": "x", "usage": {}})
    assert c.has(a) and c.get(a)["text"] == "x"


def test_a_failing_item_does_not_sink_the_run(tmp_path):
    class Flaky(Shout):
        def run(self, item, ctx):
            if item.id == "s2":
                raise ValueError("bad output")
            return super().run(item, ctx)
    rec = runner.run_eval(Flaky(), model="haiku-5-5", out_dir=tmp_path, complete_fn=FakeModel())
    assert rec["status"] == "done with errors" and rec["summary"]["items_failed"] == 1
    assert rec["summary"]["accuracy"] == 1.0                # scored on the items that ran


def test_report_is_rebuilt_after_each_run(tmp_path):
    from stringer.evals import report
    runner.run_eval(Shout(), model="code:upper", out_dir=tmp_path, use_cache=False)
    runner.run_eval(Shout(), model="haiku-5-5", out_dir=tmp_path, complete_fn=FakeModel(), only=["s1"])
    page = report.report_path(Shout(), tmp_path).read_text(encoding="utf-8")
    assert "<title>" in page and "upper (code)" in page
    assert "Partial runs" in page and "haiku-5-5" in page          # the one-word run is not compared
