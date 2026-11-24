"""Logging of every model call and search: tokens, cached tokens, cost, time.

Two sinks:
  1. always: one JSON line per event in stringer_private/runs/calls-<UTC date>.jsonl
  2. Langfuse, when its keys are in the Keychain (langfuse_public_key, langfuse_secret_key,
     optional langfuse_host). One trace per story/run, one generation per model call, one span
     per search.

Inputs and outputs are not copied into the local log (they can hold article text); Langfuse gets
them truncated, since it is the debugging view."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import tomllib
import uuid

from . import keys, paths

_LOCK = threading.Lock()
CONFIG = paths.CODE / "config" / "models.toml"
MAX_IO_CHARS = 4000


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Tracer:
    def __init__(self, langfuse_client=None, log_dir=None, enable_langfuse=True):
        self.log_dir = log_dir or paths.RUNS
        self.lf = langfuse_client
        if self.lf is None and enable_langfuse and os.environ.get("STRINGER_NO_LANGFUSE") != "1":
            self.lf = _langfuse_from_keychain()

    # -- traces ---------------------------------------------------------------
    def new_trace(self, name: str, metadata: dict | None = None) -> str:
        if self.lf is not None:
            tid = self.lf.create_trace_id()
            root = self.lf.start_observation(trace_context={"trace_id": tid}, name=name,
                                             as_type="span", metadata=metadata or {})
            root.end()
        else:
            tid = uuid.uuid4().hex
        self._local(dict(kind="trace", trace_id=tid, name=name, metadata=metadata or {}))
        return tid

    # -- events ---------------------------------------------------------------
    def generation(self, *, name, model, litellm_model, trace_id=None, input=None, output=None,
                   usage: dict, cost: dict, start: dt.datetime, end: dt.datetime,
                   metadata: dict | None = None, error: str | None = None):
        rec = dict(kind="generation", trace_id=trace_id, name=name, model=model,
                   litellm_model=litellm_model, usage=usage, cost_usd=cost,
                   latency_s=round((end - start).total_seconds(), 3), error=error,
                   metadata=metadata or {})
        self._local(rec)
        if self.lf is not None:
            g = self.lf.start_observation(
                trace_context={"trace_id": trace_id} if trace_id else None, name=name,
                as_type="generation", model=litellm_model, input=_clip(input), metadata=metadata or {},
                level="ERROR" if error else "DEFAULT", status_message=error)
            g.update(output=_clip(output), usage_details=_lf_usage(usage),
                     cost_details=_lf_cost(cost), completion_start_time=end)
            g.end()

    def span(self, *, name, trace_id=None, input=None, output=None, metadata=None,
             start=None, end=None, error=None):
        rec = dict(kind="span", trace_id=trace_id, name=name, metadata=metadata or {},
                   error=error)
        if start and end:
            rec["latency_s"] = round((end - start).total_seconds(), 3)
        self._local(rec)
        if self.lf is not None:
            s = self.lf.start_observation(
                trace_context={"trace_id": trace_id} if trace_id else None, name=name,
                as_type="tool", input=_clip(input), metadata=metadata or {},
                level="ERROR" if error else "DEFAULT", status_message=error)
            s.update(output=_clip(output))
            s.end()

    def flush(self):
        if self.lf is not None:
            self.lf.flush()

    def _local(self, rec):
        rec = dict(ts=_now().isoformat(timespec="milliseconds"), **rec)
        os.makedirs(self.log_dir, exist_ok=True)
        path = os.path.join(self.log_dir, f"calls-{_now():%Y-%m-%d}.jsonl")
        with _LOCK, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _clip(x):
    if x is None:
        return None
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= MAX_IO_CHARS else s[:MAX_IO_CHARS] + f"... [{len(s)} chars]"


def _lf_usage(u: dict) -> dict:
    return {"input": u.get("input_uncached", 0), "input_cached_tokens": u.get("cached", 0),
            "input_cache_write": u.get("cache_write", 0), "output": u.get("output", 0),
            "output_reasoning_tokens": u.get("reasoning", 0), "total": u.get("total", 0)}


def _lf_cost(c: dict) -> dict:
    return {"input": c.get("input", 0.0), "input_cached_tokens": c.get("cached", 0.0),
            "input_cache_write": c.get("cache_write", 0.0), "output": c.get("output", 0.0),
            "total": c.get("total", 0.0)}


def _langfuse_from_keychain():
    cfg = tomllib.loads(CONFIG.read_text())["langfuse"]
    if not (keys.has(cfg["public_key_item"]) and keys.has(cfg["secret_key_item"])):
        return None
    from langfuse import Langfuse
    host = keys.get(cfg["host_item"]) if keys.has(cfg["host_item"]) else "https://cloud.langfuse.com"
    return Langfuse(public_key=keys.get(cfg["public_key_item"]),
                    secret_key=keys.get(cfg["secret_key_item"]), base_url=host)


_TRACER: Tracer | None = None


def tracer() -> Tracer:
    global _TRACER
    if _TRACER is None:
        _TRACER = Tracer()
    return _TRACER


def langfuse_on() -> bool:
    return tracer().lf is not None
