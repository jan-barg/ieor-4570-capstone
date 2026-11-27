"""Module 7 over every checked Story File: writes script.json into each story's folder, for the video
step (module 8). The writer is the model config/models.toml names for `script`; the line check and the
wording check use `script_line_check` and `script_words`.

    python -m scripts.write_scripts estimate [--only <id>[,<id>...]] [--output-factor 1.0]
        free: calls, tokens and cost per story (the writer, one fix round, the two checks), and how
        many of those calls the eval already answered
    python -m scripts.write_scripts run --cap <usd> [--only ...] [--tone serious|casual|high-energy]
                                        [--angle "..."] [--reuse-eval-answers]
        paid: every call goes to the story's Langfuse trace. --reuse-eval-answers: when the eval already
        made the exact same call, its saved answer is used for free (the test stories on this machine
        only; the product has no eval cache).

The run stops before a call that could take the spend past --cap; the story it was on is not written.
A story with no video is still written (status "no video" and why), as the design says.

Story folders are paths.STORIES/<event id>/ with module 6's checked_story_file.json. Writes
<folder>/script.json and stringer_private/script_design/scripts/summary.json (and estimate.json). No path
outside paths.py, so it runs unchanged where STRINGER_PRIVATE points at a Cloud Storage mount.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
import time

from stringer import fact_check, models, paths, script_writer as sw
from stringer.evals.cache import CallCache, call_key
from stringer.evals.runner import count_tokens

OUT = paths.PRIVATE / "script_design" / "scripts"


class BudgetExceeded(RuntimeError):
    """The next call could pass the cap. brief_read._call lets an error of this name through."""


def story_dirs(only: str | None = None) -> list:
    """Folders module 6 has checked. only: one id or several, comma-separated (short ids are fine)."""
    ds = sorted(d for d in paths.STORIES.iterdir() if (d / fact_check.CHECKED_FILE).exists())
    want = [x.strip() for x in (only or "").split(",") if x.strip()]
    return [d for d in ds if any(d.name.startswith(w) for w in want)] if want else ds


def trace_of(story_dir) -> str | None:
    try:
        return json.loads((story_dir / "gather.json").read_text(encoding="utf-8")).get("langfuse_trace_id")
    except (OSError, ValueError):
        return None


def worst_case_usd(alias: str, messages: list[dict], max_tokens: int) -> float:
    m = models.spec(alias)
    tokens_in = len(json.dumps(messages, ensure_ascii=False)) / 2.5
    return (tokens_in * max(m["input"], m.get("cache_write", 0)) + max_tokens * m["output"]) / 1e6


class Caller:
    """The run's model calls (each names its own model): the spend cap, optional replay of the eval's
    saved answers, and the totals."""

    def __init__(self, cap_usd: float, reuse: bool = False, cache: CallCache | None = None, complete=None):
        self.cap = cap_usd
        self.cache = (cache or CallCache()) if reuse else None
        self.complete_fn = complete or models.complete
        self.spent = self.held = 0.0
        self.paid = self.replayed = 0
        self.lock = threading.Lock()

    def for_story(self, trace_id: str | None):
        def complete(messages, name=None, model=None, **params):
            alias = model
            key_params = dict(params, max_tokens=params.get("max_tokens") or sw.MAX_TOKENS)
            if self.cache is not None:
                hit = self.cache.get(call_key(models.spec(alias)["litellm"], messages, key_params))
                if hit is not None:
                    with self.lock:
                        self.replayed += 1
                    return models.Result(text=hit["text"], model=alias, usage=hit["usage"],
                                         cost=models.cost_of(alias, hit["usage"]), latency_s=0.0)
            need = worst_case_usd(alias, messages, key_params["max_tokens"])
            with self.lock:
                if self.spent + self.held + need > self.cap:
                    raise BudgetExceeded(f"the next call could take the spend past the ${self.cap} cap "
                                         f"(spent ${self.spent:.4f})")
                self.held += need
            try:
                r = self.complete_fn(None, messages, model=alias, trace_id=trace_id, name=name or "script", **params)
            finally:
                with self.lock:
                    self.held -= need
            with self.lock:
                self.spent += float(r.cost["total"])
                self.paid += 1
            return r
        return complete


def row_for(story_dir, s: dict, cost: float, seconds: float) -> dict:
    return dict(story=story_dir.name[:8], event=s.get("event"), status=s["status"], reason=s.get("reason", ""),
                words=s.get("words"), beats=len(s.get("beats") or []), cuts=len((s.get("checks") or {}).get("cuts") or []),
                fix_round=bool(s.get("fix_round")), held=s.get("held") or [], calls=s.get("calls"),
                cost_usd=round(cost, 5), seconds=round(seconds, 1))


def run(cap: float, only: str | None = None, reuse: bool = False, caller: Caller | None = None,
        tone: str = sw.TONE, angle: str = "") -> dict:
    writer = models.model_for("script")
    caller = caller or Caller(cap, reuse)
    rows, stopped = [], None
    for d in story_dirs(only):
        t0, before = time.time(), caller.spent
        try:
            s = sw.write_folder(d, caller.for_story(trace_of(d)), model=writer, tone=tone, angle=angle)
        except BudgetExceeded as e:
            stopped = f"{d.name[:8]}: {e}; not written"
            print("stopped at", stopped)
            break
        s["cost_usd"] = round(caller.spent - before, 6)
        sw.write_file(d, s)
        r = row_for(d, s, caller.spent - before, time.time() - t0)
        rows.append(r)
        print(f"{r['story']}: {r['status']}, {r['words']} words, {r['beats']} beats, {r['cuts']} cut"
              + (", fixed once" if r["fix_round"] else "") + f"; ${r['cost_usd']:.4f}, {r['seconds']} s"
              + (f"; {r['reason']}" if r["reason"] else ""))
    s = dict(model=writer, line_model=sw._model_for(sw.LINE_STEP, sw.LINE_MODEL),
             words_model=sw._model_for(sw.WORDS_STEP, sw.WORDS_MODEL), version=sw.VERSION, tone=tone, angle=angle,
             finished_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), cap_usd=cap,
             spent_usd=round(caller.spent, 5), paid_calls=caller.paid, replayed_calls=caller.replayed,
             stories=len(rows), stopped=stopped,
             statuses={k: sum(r["status"] == k for r in rows) for k in ("ok", "ok with cuts", "no video")},
             stories_detail=rows)
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def estimate(only: str | None = None, output_factor: float = 1.0, cache: CallCache | None = None) -> dict:
    """From the eval's plan, without the eval's own judges and plants."""
    from stringer.evals.script_eval import ScriptEval
    writer = models.model_for("script")
    step = ScriptEval(plants=False, sheets=paths.PRIVATE / "none.json")
    cache = cache or CallCache()
    rows = []
    for d in story_dirs(only):
        from stringer.evals.runner import Item
        item = Item(id=d.name[:8], story=d.name[:8], data={"dir": str(d), "n": None})
        r = dict(story=d.name[:8], calls=0, eval_answered=0, input_tokens=0, output_tokens=0, usd=0.0, usd_unanswered=0.0)
        for c in step.plan(item, writer):
            alias = c.get("model") or writer
            lm = models.spec(alias)["litellm"]
            params = dict(c["params"], max_tokens=c["params"].get("max_tokens") or sw.MAX_TOKENS)
            ti, to = count_tokens(lm, c["messages"]), c["expect_output"] * (output_factor if alias == writer else 1.0)
            usd = models.cost_of(alias, dict(input_uncached=ti, cached=0, cache_write=0, output=to))["total"]
            hit = cache.has(call_key(lm, c["messages"], params))
            r["calls"] += 1
            r["eval_answered"] += hit
            r["input_tokens"] += ti
            r["output_tokens"] += int(to)
            r["usd"] += usd
            r["usd_unanswered"] += 0 if hit else usd
        rows.append(r)
    tot = lambda k: sum(r[k] for r in rows)
    s = dict(model=writer, version=sw.VERSION, stories=len(rows),
             **{k: (round(tot(k), 4) if k.startswith("usd") else tot(k))
                for k in ("calls", "eval_answered", "input_tokens", "output_tokens", "usd", "usd_unanswered")},
             stories_detail=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "estimate.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("estimate", "run"))
    ap.add_argument("--only")
    ap.add_argument("--cap", type=float)
    ap.add_argument("--tone", default=sw.TONE)
    ap.add_argument("--angle", default="")
    ap.add_argument("--output-factor", type=float, default=1.0)
    ap.add_argument("--reuse-eval-answers", action="store_true")
    a = ap.parse_args(argv)
    if a.mode == "estimate":
        s = estimate(a.only, a.output_factor)
    else:
        if a.cap is None:
            sys.exit("run needs --cap <usd>: it pays for model calls")
        s = run(a.cap, a.only, a.reuse_eval_answers, tone=a.tone, angle=a.angle)
    print(json.dumps({k: v for k, v in s.items() if k != "stories_detail"}, indent=1))


if __name__ == "__main__":
    main()
