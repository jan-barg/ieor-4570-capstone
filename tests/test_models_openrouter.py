"""OpenRouter models (added Nov 26 for the fact check's model test). No network, no real key."""
from stringer import models


def test_openrouter_call_uses_its_key_strips_cache_marks_and_asks_for_hosts_that_honour_the_schema(monkeypatch):
    asked = []
    monkeypatch.setattr(models.keys, "get", lambda s: asked.append(s) or "test-key")
    msgs = [{"role": "user", "content": [models.cache_block("A" * 10), models.text_block("q")]}]
    kw = models.call_kwargs("gpt-6.1-terra", msgs)
    assert kw["model"] == "openrouter/openai/gpt-6.1-terra"
    assert asked == ["openrouter_api_key"] and kw["api_key"] == "test-key"
    assert kw["messages"][0]["content"] == "A" * 10 + "q"
    assert kw["extra_body"]["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert msgs[0]["content"][0]["cache_control"]  # caller's list not modified


def test_new_fact_check_candidates_have_prices():
    c = models.cost_of("gpt-6.1-terra", dict(input_uncached=1_000_000, cached=1_000_000, cache_write=0, output=1_000_000))
    assert (c["input"], c["cached"], c["output"]) == (1.0, 0.05, 5.0)
    g = models.spec("gemini-3.8-flash")
    assert g["provider"] == "vertex" and (g["input"], g["output"]) == (0.75, 3.75)
