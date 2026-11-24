"""Model layer tests. Offline ones always run; the live smoke test runs with STRINGER_LIVE=1."""
import datetime as dt
import os
from types import SimpleNamespace as NS

import pytest

from stringer import models
from stringer.tracing import Tracer


def test_every_step_names_a_configured_model():
    cfg = models.config()
    for step, alias in cfg["steps"].items():
        assert alias in cfg["models"], step
    for alias, m in cfg["models"].items():
        assert m["provider"] in {"vertex", "anthropic"}, alias
        assert m["input"] > 0 and m["output"] > 0, alias


def test_dotted_aliases_are_single_keys():
    assert "glm-5.2" in models.config()["models"]
    assert "deepseek-v4.1-flash" in models.shortlist()


def fake_resp(prompt, out, cached=None, read=None, write=None, reasoning=None):
    return NS(usage=NS(prompt_tokens=prompt, completion_tokens=out,
                       prompt_tokens_details=NS(cached_tokens=cached) if cached is not None else None,
                       cache_read_input_tokens=read, cache_creation_input_tokens=write,
                       completion_tokens_details=NS(reasoning_tokens=reasoning) if reasoning else None))


def test_usage_openai_style_cached_tokens():
    u = models.usage_from(fake_resp(3162, 10, cached=3072))
    assert u == dict(prompt=3162, input_uncached=90, cached=3072, cache_write=0, output=10,
                     reasoning=0, total=3172)


def test_usage_anthropic_style_cache_read_and_write():
    u = models.usage_from(fake_resp(2000, 50, read=1500, write=400))
    assert (u["cached"], u["cache_write"], u["input_uncached"]) == (1500, 400, 100)


def test_cost_uses_cached_price():
    u = dict(input_uncached=1_000_000, cached=1_000_000, cache_write=0, output=1_000_000)
    c = models.cost_of("deepseek-v4.1-flash", u)
    assert c["input"] == pytest.approx(0.30) and c["cached"] == pytest.approx(0.006)
    assert c["output"] == pytest.approx(1.20) and c["total"] == pytest.approx(1.506)


def test_cache_marks_removed_for_vertex_kept_for_claude(monkeypatch):
    msgs = [{"role": "user", "content": [models.cache_block("A" * 10), models.text_block("q")]}]
    kw = models.call_kwargs("deepseek-v4.1-flash", msgs)
    assert kw["messages"][0]["content"] == "A" * 10 + "q"
    assert kw["extra_headers"]["x-goog-user-project"] == "agentic-ai-msds"
    assert kw["vertex_location"] == "global"
    monkeypatch.setattr(models.keys, "get", lambda s: "test-key")
    kw = models.call_kwargs("haiku-5-5", msgs)
    assert kw["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert msgs[0]["content"][0]["cache_control"]  # caller's list not modified


class FakeObs:
    def __init__(self, log, kw):
        self.log, self.kw = log, kw

    def update(self, **kw):
        self.kw.update(kw)

    def end(self):
        self.log.append(self.kw)


class FakeLangfuse:
    def __init__(self):
        self.log = []

    def create_trace_id(self):
        return "t" * 32

    def start_observation(self, **kw):
        return FakeObs(self.log, dict(kw))

    def flush(self):
        pass


def test_tracer_sends_tokens_cached_tokens_and_cost(tmp_path):
    lf = FakeLangfuse()
    tr = Tracer(langfuse_client=lf, log_dir=str(tmp_path))
    tid = tr.new_trace("story", {"event": "x"})
    now = dt.datetime.now(dt.timezone.utc)
    usage = dict(prompt=3162, input_uncached=90, cached=3072, cache_write=0, output=10, reasoning=0,
                 total=3172)
    tr.generation(name="brief_read", model="deepseek-v4.1-flash", litellm_model="vertex_ai/x",
                  trace_id=tid, input="in", output="out", usage=usage,
                  cost=dict(input=1e-5, cached=2e-5, cache_write=0, output=1e-5, total=4e-5),
                  start=now, end=now)
    gen = [o for o in lf.log if o.get("as_type") == "generation"][0]
    assert gen["usage_details"]["input_cached_tokens"] == 3072
    assert gen["usage_details"]["input"] == 90
    assert gen["cost_details"]["total"] == pytest.approx(4e-5)
    assert gen["trace_context"] == {"trace_id": tid}
    local = list(tmp_path.glob("calls-*.jsonl"))[0].read_text()
    assert '"cached": 3072' in local and '"in"' not in local   # no prompt text in the local log


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("STRINGER_LIVE") != "1", reason="set STRINGER_LIVE=1 (costs cents)")
def test_smoke_shortlist_answers_and_reports_cache():
    from scripts.smoke_models import main
    reachable = [a for a in models.shortlist() if "note" not in models.spec(a)]
    results = main(reachable)
    for r in results:
        if r["status"].startswith("skipped"):
            continue
        assert r["status"] == "ok", r
        assert "cached_tokens_call2" in r
    caching = {r["model"]: r["cached_tokens_call2"] for r in results if r.get("calls")}
    assert caching.get("deepseek-v4.1-flash", 0) > 2000   # automatic cache seen Nov 24
