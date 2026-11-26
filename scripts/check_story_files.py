"""Module 6 over every Story File: writes checked_story_file.json into each story's folder, for the
script writer (module 7). The model is the one config/models.toml names for fact_check (Haiku since
November 26, Jan).

    python -m scripts.check_story_files estimate [--only <id>[,<id>...]]
        free: judge calls, tokens and cost per story, and how many calls the eval already answered
    python -m scripts.check_story_files run --cap <usd> [--only <id>[,<id>...]] [--reuse-eval-answers]
        paid: one judge call per 20 claims, 3 side by side; every call goes to the story's Langfuse trace.
        --reuse-eval-answers: when the eval already made the exact same call (same model, prompt
        version and claims), its saved answer is used for free. Only for the test stories on this
        machine; the product has no eval cache.

The run stops before a call that could take the spend past --cap; the story it was on is not written.
A story whose calls failed is still written: those claims are "unchecked" and flagged, as the design says.

Story folders are paths.STORIES/<event id>/ with module 5's story_file.json. Writes
<folder>/checked_story_file.json and stringer_private/fact_check_design/checked/summary.json (and
estimate.json). No path outside paths.py, so it runs unchanged where STRINGER_PRIVATE points at a
Cloud Storage mount.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
import time

from stringer import fact_check, models, outlets, paths, story_file
from stringer.evals.cache import CallCache, call_key
from stringer.evals.runner import count_tokens

OUT = paths.PRIVATE / "fact_check_design" / "checked"
OUTPUT_FACTOR = 5.3      # judge_plan expects the visible answer only; Haiku's thinking made its real output
                         # 5.3x that (fitted Nov 26 on the 13 stories of its check-5 eval run)


class BudgetExceeded(RuntimeError):
    """The next call could pass the cap. brief_read._call lets an error of this name through."""


def story_dirs(only: str | None = None) -> list:
    """Folders module 5 has filled. only: one id or several, comma-separated (short ids are fine)."""
    ds = sorted(d for d in paths.STORIES.iterdir() if (d / "story_file.json").exists())
    want = [x.strip() for x in (only or "").split(",") if x.strip()]
    return [d for d in ds if any(d.name.startswith(w) for w in want)] if want else ds


def trace_of(story_dir) -> str | None:
    """The story's Langfuse trace (from Gather), so the fact check lands in the same trace."""
    try:
        return json.loads((story_dir / "gather.json").read_text(encoding="utf-8")).get("langfuse_trace_id")
    except (OSError, ValueError):
        return None


def worst_case_usd(alias: str, messages: list[dict], max_tokens: int) -> float:
    """The most one call can cost: generous input count at the dearest input price, plus every output token."""
    m = models.spec(alias)
    tokens_in = len(json.dumps(messages, ensure_ascii=False)) / 2.5
    return (tokens_in * max(m["input"], m.get("cache_write", 0)) + max_tokens * m["output"]) / 1e6


class Caller:
    """The run's model calls: the spend cap (held for calls in flight), optional replay of the eval's
    saved answers, and the totals."""

    def __init__(self, alias: str, cap_usd: float, reuse: bool = False, cache: CallCache | None = None,
                 complete=None):
        self.alias, self.cap = alias, cap_usd
        self.litellm = models.spec(alias)["litellm"]
        self.cache = (cache or CallCache()) if reuse else None
        self.complete_fn = complete or models.complete
        self.spent = self.held = 0.0
        self.paid = self.replayed = 0
        self.lock = threading.Lock()

    def for_story(self, trace_id: str | None):
        def complete(messages, name=None, **params):
            if self.cache is not None:
                hit = self.cache.get(call_key(self.litellm, messages, params))
                if hit is not None:
                    with self.lock:
                        self.replayed += 1
                    return models.Result(text=hit["text"], model=self.alias, usage=hit["usage"],
                                         cost=models.cost_of(self.alias, hit["usage"]), latency_s=0.0)
            need = worst_case_usd(self.alias, messages, params.get("max_tokens") or fact_check.MAX_TOKENS)
            with self.lock:
                if self.spent + self.held + need > self.cap:
                    raise BudgetExceeded(f"the next call could take the spend past the ${self.cap} cap "
                                         f"(spent ${self.spent:.4f})")
                self.held += need
            try:
                r = self.complete_fn("fact_check", messages, model=self.alias, trace_id=trace_id,
                                     name=name or "fact_check", **params)
            finally:
                with self.lock:
                    self.held -= need
            with self.lock:
                self.spent += float(r.cost["total"])
                self.paid += 1
            return r
        return complete


def row_for(story_dir, sf: dict, cost: float, seconds: float) -> dict:
    fc = sf["fact_check"]
    n = fc["counts"]
    return dict(story=story_dir.name[:8], event=(sf.get("event") or {}).get("title"), claims=n["claims"],
                confirmed=n["confirmed"], say_with_source=n["say_with_source"], dropped=n["dropped"],
                unchecked=n["unchecked"], calls=fc["calls"], errors=len(fc["errors"]),
                flags=[f["code"] for f in sf.get("flags") or [] if f.get("code") in fact_check.FLAGS],
                cost_usd=round(cost, 5), seconds=round(seconds, 1))


def run(cap: float, only: str | None = None, reuse: bool = False, caller: Caller | None = None,
        table=None) -> dict:
    alias = caller.alias if caller else models.model_for("fact_check")
    caller = caller or Caller(alias, cap, reuse)
    table = table if table is not None else outlets.table()
    rows, stopped = [], None
    for d in story_dirs(only):
        t0, before = time.time(), caller.spent
        try:
            facts, sf = fact_check.check_folder(d, caller.for_story(trace_of(d)), model=alias, table=table)
        except BudgetExceeded as e:
            stopped = f"{d.name[:8]}: {e}; not written"
            print("stopped at", stopped)
            break
        fact_check.write_checked(d, facts, sf)
        r = row_for(d, sf, caller.spent - before, time.time() - t0)
        rows.append(r)
        print(f"{r['story']}: {r['claims']} claims: {r['confirmed']} confirmed, {r['say_with_source']} say with source, "
              f"{r['dropped']} dropped, {r['unchecked']} unchecked; {r['calls']} calls, ${r['cost_usd']:.4f}, {r['seconds']} s"
              + (f"; flags: {', '.join(r['flags'])}" if r["flags"] else ""))
    tot = lambda k: sum(r[k] for r in rows)
    s = dict(model=alias, version=fact_check.VERSION, finished_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             cap_usd=cap, spent_usd=round(caller.spent, 5), paid_calls=caller.paid, replayed_calls=caller.replayed,
             stories=len(rows), stopped=stopped,
             totals={k: tot(k) for k in ("claims", "confirmed", "say_with_source", "dropped", "unchecked", "calls", "errors")},
             stories_detail=rows)
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def estimate(only: str | None = None, table=None, cache: CallCache | None = None) -> dict:
    alias = models.model_for("fact_check")
    lm = models.spec(alias)["litellm"]
    cache = cache or CallCache()
    table = table if table is not None else outlets.table()
    rows = []
    for d in story_dirs(only):
        facts, sf = story_file.read(d)
        pw = fact_check.paperwork(sf, facts, fact_check.read_articles(d), table)
        r = dict(story=d.name[:8], claims=len(sf.get("claims") or []), calls=0, eval_answered=0,
                 input_tokens=0, output_tokens=0, usd=0.0, usd_unanswered=0.0)
        for c in fact_check.judge_plan(sf, facts, pw, alias):
            ti, to = count_tokens(lm, c["messages"]), c["expect_output"] * OUTPUT_FACTOR
            usd = models.cost_of(alias, dict(input_uncached=ti, cached=0, cache_write=0, output=to))["total"]
            hit = cache.has(call_key(lm, c["messages"], c["params"]))
            r["calls"] += 1
            r["eval_answered"] += hit
            r["input_tokens"] += ti
            r["output_tokens"] += to
            r["usd"] += usd
            r["usd_unanswered"] += 0 if hit else usd
        rows.append(r)
    tot = lambda k: sum(r[k] for r in rows)
    s = dict(model=alias, version=fact_check.VERSION, stories=len(rows),
             **{k: (round(tot(k), 4) if k.startswith("usd") else tot(k))
                for k in ("claims", "calls", "eval_answered", "input_tokens", "output_tokens", "usd", "usd_unanswered")},
             stories_detail=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "estimate.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("estimate", "run"))
    ap.add_argument("--only")
    ap.add_argument("--cap", type=float)
    ap.add_argument("--reuse-eval-answers", action="store_true")
    a = ap.parse_args(argv)
    if a.mode == "estimate":
        s = estimate(a.only)
    else:
        if a.cap is None:
            sys.exit("run needs --cap <usd>: it pays for model calls")
        s = run(a.cap, a.only, a.reuse_eval_answers)
    print(json.dumps({k: v for k, v in s.items() if k != "stories_detail"}, indent=1))


if __name__ == "__main__":
    main()
