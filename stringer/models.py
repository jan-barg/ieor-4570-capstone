"""The model layer: every model is called the same way, through LiteLLM.

The idea: code asks for a *step* ("brief_read"), config/models.toml says which model that step
uses, and every call is logged with tokens, cached tokens and cost (tracing.py).

    from stringer import models
    r = models.complete("query_writer", [{"role": "user", "content": "..."}], trace_id=tid)
    r.text, r.usage["cached"], r.cost["total"]

Prompt caching (settled Nov 24): order every repeated call as instructions -> examples ->
(mark) -> event -> (mark) -> article. Mark a block with cache_block(text). The marks are sent to
Claude (explicit caching); for Vertex models they are removed, since DeepSeek and GLM cache on
their own and LiteLLM would otherwise turn a Gemini mark into a paid stored cache. OpenRouter models
(provider "openrouter", added Nov 26 for the fact check's model test) have them removed too."""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import functools
import os
import threading
import tomllib
from dataclasses import dataclass

from . import keys, paths
from .tracing import tracer

CONFIG = paths.CODE / "config" / "models.toml"

# Cost listeners: fn(step, alias, usd) runs after every call that got an answer. The one-event runner
# (pipeline.py) uses it to count a video's model spend for the Gate, whichever module made the call.
_listeners: list = []
_listeners_lock = threading.Lock()


@contextlib.contextmanager
def on_cost(fn):
    """While inside the block, fn(step, alias, usd) is called after each answered call (any thread)."""
    with _listeners_lock:
        _listeners.append(fn)
    try:
        yield fn
    finally:
        with _listeners_lock:
            _listeners.remove(fn)


# Time limits while a live video is being made: {step: seconds} from config/models.toml's [live_timeouts],
# None outside one. Process-wide, like the cost listeners: one video per process on Cloud Run.
_live_timeouts: dict | None = None


@contextlib.contextmanager
def live_timeouts(table: dict | None = None):
    """While inside the block, a model call may take at most its step's limit from [live_timeouts] (or the
    table given), even where the module asks for longer. Modules keep generous limits for eval runs; a
    video a viewer is waiting for cannot wait ten minutes on one stuck call."""
    global _live_timeouts
    before = _live_timeouts
    _live_timeouts = dict(table if table is not None else (config().get("live_timeouts") or {}))
    try:
        yield _live_timeouts
    finally:
        _live_timeouts = before


def _log_call(**kw) -> None:
    """One line in the call log and Langfuse. Never raises: by now the answer is paid for (or the real
    error is on its way up), and losing either to a logging hiccup would be worse than a missing line."""
    try:
        tracer().generation(**kw)
    except Exception:
        pass


def _tell_listeners(step, alias, cost: dict) -> None:
    with _listeners_lock:
        fns = list(_listeners)
    for fn in fns:
        fn(step, alias, float((cost or {}).get("total") or 0.0))


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
        # On Cloud Run the models are called in the service's own project (Jan, Nov 27: Vertex is turned
        # on in agentic-ai-capstone-jgb2170); STRINGER_VERTEX_PROJECT names it. The Mac keeps models.toml's.
        project = os.environ.get("STRINGER_VERTEX_PROJECT") or v["project"]
        header = os.environ.get("STRINGER_VERTEX_PROJECT") or v["user_project_header"]
        kw.update(vertex_project=project, vertex_location=v["location"],
                  extra_headers={"x-goog-user-project": header},
                  messages=_strip_cache_marks(messages))
    elif m["provider"] == "anthropic":
        kw.update(api_key=keys.get(config()["anthropic"]["keychain_item"]), messages=messages)
    elif m["provider"] == "openrouter":
        # Only hosts that honour every parameter (the JSON schema above all) and don't keep the data.
        o = config().get("openrouter", {})
        kw.update(api_key=keys.get(o.get("key_item", "openrouter_api_key")), messages=_strip_cache_marks(messages),
                  extra_body={"provider": {"require_parameters": True, "data_collection": "deny"}})
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
    if _live_timeouts:
        limit = _live_timeouts.get(step or "") or _live_timeouts.get("default")
        if limit:
            kw["timeout"] = min(float(kw.get("timeout") or limit), float(limit))
    start = dt.datetime.now(dt.timezone.utc)
    try:
        resp = litellm.completion(**kw)
    except Exception as e:
        end = dt.datetime.now(dt.timezone.utc)
        _log_call(name=name or step or alias, model=alias, litellm_model=kw["model"],
                  trace_id=trace_id, input=messages, usage={}, cost={}, start=start,
                  end=end, metadata=dict(metadata or {}, step=step), error=repr(e)[:500])
        raise
    end = dt.datetime.now(dt.timezone.utc)
    usage = usage_from(resp)
    cost = cost_of(alias, usage)
    text = resp.choices[0].message.content or ""
    _log_call(name=name or step or alias, model=alias, litellm_model=kw["model"],
              trace_id=trace_id, input=messages, output=text, usage=usage, cost=cost,
              start=start, end=end, metadata=dict(metadata or {}, step=step))
    _tell_listeners(step, alias, cost)
    return Result(text=text, model=alias, usage=usage, cost=cost,
                  latency_s=round((end - start).total_seconds(), 3), raw=resp)
