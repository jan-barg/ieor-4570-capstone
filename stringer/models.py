"""The model layer: every model is called the same way, through LiteLLM.

The idea: code asks for a *step* ("brief_read"), config/models.toml says which model that step
uses, and every call is logged with tokens, cached tokens and cost (tracing.py).

    from stringer import models
    r = models.complete("query_writer", [{"role": "user", "content": "..."}], trace_id=tid)
    r.text, r.usage["cached"], r.cost["total"]

Prompt caching (settled Nov 24): order every repeated call as instructions -> examples ->
(mark) -> event -> (mark) -> article. Mark a block with cache_block(text). The marks are sent to
Claude (explicit caching); for Vertex models they are removed, since DeepSeek and GLM cache on
their own and LiteLLM would otherwise turn a Gemini mark into a paid stored cache."""
from __future__ import annotations

import copy
import datetime as dt
import functools
import tomllib
from dataclasses import dataclass

from . import keys, paths
from .tracing import tracer

CONFIG = paths.CODE / "config" / "models.toml"


@functools.lru_cache(maxsize=1)
def config() -> dict:
    return tomllib.loads(CONFIG.read_text())


def model_for(step: str) -> str:
    return config()["steps"][step]


def spec(alias: str) -> dict:
    m = config()["models"].get(alias)
    if m is None:
        raise KeyError(f"model alias '{alias}' not in {CONFIG}")
    return m


def shortlist() -> list[str]:
    return [a for a, m in config()["models"].items() if m.get("shortlist")]


def cache_block(text: str) -> dict:
    """A text content block with a cache mark after it."""
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


@dataclass
class Result:
    text: str
    model: str
    usage: dict        # input_uncached, cached, cache_write, output, reasoning, total
    cost: dict         # USD: input, cached, cache_write, output, total
    latency_s: float
    raw: object = None


def usage_from(resp) -> dict:
    """Normalise LiteLLM usage across providers. prompt_tokens counts every input token
    (LiteLLM adds Anthropic's cache reads and writes into it)."""
    u = resp.usage
    prompt = int(getattr(u, "prompt_tokens", 0) or 0)
    out = int(getattr(u, "completion_tokens", 0) or 0)
    details = getattr(u, "prompt_tokens_details", None)
    cached = int((getattr(details, "cached_tokens", None) if details else None)
                 or getattr(u, "cache_read_input_tokens", 0) or 0)
    write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    cdet = getattr(u, "completion_tokens_details", None)
    reasoning = int((getattr(cdet, "reasoning_tokens", None) if cdet else None) or 0)
    return dict(prompt=prompt, input_uncached=max(prompt - cached - write, 0), cached=cached,
                cache_write=write, output=out, reasoning=reasoning, total=prompt + out)


def cost_of(alias: str, usage: dict) -> dict:
    m = spec(alias)
    per = 1_000_000
    c = dict(input=usage["input_uncached"] * m["input"] / per,
             cached=usage["cached"] * m.get("cached_input", m["input"]) / per,
             cache_write=usage["cache_write"] * m.get("cache_write", m["input"]) / per,
             output=usage["output"] * m["output"] / per)
    c["total"] = sum(c.values())
    return {k: round(v, 8) for k, v in c.items()}


def _strip_cache_marks(messages):
    msgs = copy.deepcopy(messages)
    for m in msgs:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
            if all(isinstance(b, dict) and b.get("type") == "text" for b in m["content"]):
                m["content"] = "".join(b["text"] for b in m["content"])
    return msgs


def call_kwargs(alias: str, messages: list[dict]) -> dict:
    m = spec(alias)
    kw = dict(model=m["litellm"])
    if m["provider"] == "vertex":
        v = config()["vertex"]
        kw.update(vertex_project=v["project"], vertex_location=v["location"],
                  extra_headers={"x-goog-user-project": v["user_project_header"]},
                  messages=_strip_cache_marks(messages))
    elif m["provider"] == "anthropic":
        kw.update(api_key=keys.get(config()["anthropic"]["keychain_item"]), messages=messages)
    else:
        raise ValueError(f"unknown provider {m['provider']}")
    return kw


def complete(step: str | None = None, messages: list[dict] | None = None, *, model: str | None = None,
             trace_id: str | None = None, name: str | None = None, metadata: dict | None = None,
             **params) -> Result:
    """One model call. Give a step (looked up in config) or a model alias."""
    import litellm
    litellm.suppress_debug_info = True
    alias = model or model_for(step)
    kw = call_kwargs(alias, messages)
    kw.update(params)
    start = dt.datetime.now(dt.timezone.utc)
    try:
        resp = litellm.completion(**kw)
    except Exception as e:
        end = dt.datetime.now(dt.timezone.utc)
        tracer().generation(name=name or step or alias, model=alias, litellm_model=kw["model"],
                            trace_id=trace_id, input=messages, usage={}, cost={}, start=start,
                            end=end, metadata=dict(metadata or {}, step=step), error=repr(e)[:500])
        raise
    end = dt.datetime.now(dt.timezone.utc)
    usage = usage_from(resp)
    cost = cost_of(alias, usage)
    text = resp.choices[0].message.content or ""
    tracer().generation(name=name or step or alias, model=alias, litellm_model=kw["model"],
                        trace_id=trace_id, input=messages, output=text, usage=usage, cost=cost,
                        start=start, end=end, metadata=dict(metadata or {}, step=step))
    return Result(text=text, model=alias, usage=usage, cost=cost,
                  latency_s=round((end - start).total_seconds(), 3), raw=resp)
