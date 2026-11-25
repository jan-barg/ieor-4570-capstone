"""The shared eval runner (map, Cross-cutting: eval harness).

It runs one pipeline step on saved inputs with a chosen model, scores the output against a
hand-made answer key, and records per-story scores, tokens, cost and time. Every model choice and
every prompt change (hill-climbing) goes through it, so all runs can be compared side by side.

A step plugs in as a small class (see Step) with three main methods:
    load(only, split) -> the saved inputs, as Items (one unit of work each, e.g. one story)
    run(item, ctx)    -> does the step's work on one Item; every model call goes through
                         ctx.complete(), never models.complete() directly
    score(item, output, key) -> compares one Item's output with the answer key (plain code)
plus summarize() for the run's headline numbers and plan() for cost estimates.

What the runner adds around that:
  - Model answers are cached by their exact input (cache.py). Running the same model and prompt
    again, or re-scoring after the answer key changes, makes no model calls.
  - A hard cost cap per run. Before each call the runner sets aside the most that call could
    cost (its input tokens plus max_tokens of output, at full price) and refuses the call if
    that could take the run over the cap. The run then stops and is saved as "stopped".
  - One Langfuse trace per run: every model call is a generation in it, and the headline scores
    are trace scores.
  - A private results file per run (stringer_private/evals/runs/<step>/<run id>.json, with every
    output, since outputs can quote articles) and one summary row in evals/runs/index.jsonl.
    compare_table() builds the side-by-side table (model or prompt version, score, cost, time)
    that the hill-climbing log is written from.

Example:
    from stringer.evals import runner, steps
    rec = runner.run_eval(steps.get("same_story"), model="haiku-5-5", cap_usd=0.50)
    rec["summary"]["drop_f1"], rec["cost_usd"], rec["wall_s"]

Cost words used in results: `cost_usd` is what the run's model calls cost at list price, cached
or not (so runs compare fairly); `spent_usd` is new money this run actually spent (0 for a re-run
that hit the cache)."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .. import models, paths
from ..tracing import tracer
from .cache import CallCache, call_key

DEFAULT_CAP_USD = 1.00
DEFAULT_MAX_TOKENS = 4096
CODE_PREFIX = "code:"           # "model" names for plain-code baselines, e.g. "code:keywords"


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Item:
    id: str
    story: str                  # the event id (8-char short id) this item belongs to
    data: dict
    split: str = "tune"         # "tune" (used for prompt changes) or "holdout" (kept out of them)


class Step:
    """Base class for a step's eval plug-in. Override the methods; keep `version` in step with
    the prompt and code, since the comparison table groups runs by it."""
    name = "step"
    version = "v0"
    model_step: str | None = None       # key under [steps] in models.toml: the default model
    headline: tuple[str, ...] = ()      # summary keys shown in the comparison table; the first is the main score
    # for the visual report (report.py); all optional
    report_title = ""
    report_intro = ""                   # what the step does and what it is scored against, in plain words
    metric_notes: dict = {}             # headline key -> (short name, what it means in plain words)
    class_names: dict = {}              # label -> display name, in the order the confusion grid shows them

    def load(self, only=None, split="tune") -> list[Item]:
        raise NotImplementedError

    def load_key(self) -> dict:
        return {}

    def key_version(self) -> str:
        return ""

    def run(self, item: Item, ctx: "Ctx"):
        raise NotImplementedError

    def plan(self, item: Item, model: str) -> list[dict]:
        """The calls run() will make first, for estimates: [{"messages", "params",
        "expect_output"}]. Retries are extra. Optional."""
        return []

    def score(self, item: Item, output, key: dict) -> dict:
        return {}

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        return {}

    def story_names(self) -> dict[str, str]:
        """{story id: short title}, for the report."""
        return {}

    def mistakes(self, rec: dict) -> list[dict]:
        """A saved run's wrong answers for the report: [{story, kind, title, url, gold, pred, reason,
        source}]."""
        return []


# ---- money -------------------------------------------------------------------------------------

class Budget:
    """A hard cap: hold() sets aside a call's worst case before it runs, settle() books the real
    cost after. Thread-safe."""

    def __init__(self, cap_usd: float):
        self.cap = float(cap_usd)
        self.spent = 0.0
        self.held = 0.0
        self._lock = threading.Lock()

    def hold(self, usd: float) -> float:
        with self._lock:
            if self.spent + self.held + usd > self.cap + 1e-12:
                raise BudgetExceeded(f"a call that could cost ${usd:.4f} would pass the ${self.cap:.2f} cap "
                                     f"(spent ${self.spent:.4f}, ${self.held:.4f} held for calls in flight)")
            self.held += usd
            return usd

    def settle(self, held: float, actual: float) -> None:
        with self._lock:
            self.held -= held
            self.spent += actual


def count_tokens(litellm_model: str, messages: list[dict]) -> int:
    """Input tokens, roughly (tokenizers differ by model; the results record the real counts)."""
    try:
        import litellm
        return int(litellm.token_counter(model=litellm_model, messages=messages))
    except Exception:
        return int(len(json.dumps(messages, ensure_ascii=False)) / 3.5) + 1


INPUT_MARGIN = 1.3     # our token count can be under a model's own tokenizer; hold 30% more


def worst_case_usd(alias: str, tokens_in: int, max_out: int) -> float:
    """The most a call can cost: every input token at the full (or cache-write) price, plus
    max_tokens of output (reasoning counts toward max_tokens on every provider we use)."""
    m = models.spec(alias)
    return (tokens_in * INPUT_MARGIN * max(m["input"], m.get("cache_write", 0)) + max_out * m["output"]) / 1e6


# ---- the context a step's run() gets ---------------------------------------------------------

@dataclass
class CallResult:
    text: str
    model: str
    usage: dict
    cost: dict
    latency_s: float
    cached: bool


@dataclass
class ItemStats:
    calls: int = 0
    cache_hits: int = 0
    cost_usd: float = 0.0
    spent_usd: float = 0.0
    latency_s: float = 0.0
    tokens: Counter = field(default_factory=Counter)

    def as_dict(self):
        return dict(calls=self.calls, cache_hits=self.cache_hits, cost_usd=round(self.cost_usd, 8),
                    spent_usd=round(self.spent_usd, 8), latency_s=round(self.latency_s, 2),
                    tokens=dict(self.tokens))


class Ctx:
    """What a step's run() gets: the model alias, and complete() for every model call."""

    def __init__(self, *, model: str, trace_id: str | None, budget: Budget, cache: CallCache | None,
                 complete_fn, item: Item | None = None, step_name: str = ""):
        self.model = model
        self.trace_id = trace_id
        self.budget = budget
        self.cache = cache
        self.complete_fn = complete_fn
        self.item = item
        self.step_name = step_name
        self.stats = ItemStats()

    @property
    def is_code(self) -> bool:
        return self.model.startswith(CODE_PREFIX)

    def complete(self, messages: list[dict], *, name: str | None = None, max_tokens: int | None = None,
                 **params) -> CallResult:
        if self.is_code:
            raise RuntimeError(f"{self.model} is a plain-code baseline; it can't call a model")
        params = dict(params, max_tokens=max_tokens or DEFAULT_MAX_TOKENS)
        litellm_model = models.spec(self.model)["litellm"]
        key = call_key(litellm_model, messages, params)
        hit = self.cache.get(key) if self.cache else None
        if hit is not None:
            usage = hit["usage"]
            r = CallResult(text=hit["text"], model=self.model, usage=usage,
                           cost=models.cost_of(self.model, usage), latency_s=hit.get("latency_s", 0.0),
                           cached=True)
            self.stats.cache_hits += 1
        else:
            held = self.budget.hold(worst_case_usd(self.model, count_tokens(litellm_model, messages),
                                                   params["max_tokens"]))
            try:
                res = self.complete_fn(model=self.model, messages=messages, trace_id=self.trace_id,
                                       name=name or self.step_name,
                                       metadata={"eval_step": self.step_name,
                                                 "item": self.item.id if self.item else None},
                                       **params)
            except Exception:
                self.budget.settle(held, 0.0)
                raise
            self.budget.settle(held, res.cost["total"])
            if self.cache:
                self.cache.put(key, dict(text=res.text, usage=res.usage, latency_s=res.latency_s,
                                         litellm_model=litellm_model, alias=self.model))
            r = CallResult(text=res.text, model=self.model, usage=res.usage, cost=res.cost,
                           latency_s=res.latency_s, cached=False)
            self.stats.spent_usd += res.cost["total"]
        self.stats.calls += 1
        self.stats.cost_usd += r.cost["total"]
        self.stats.latency_s += r.latency_s
        for k in ("input_uncached", "cached", "cache_write", "output", "reasoning"):
            self.stats.tokens[k] += int(r.usage.get(k, 0) or 0)
        return r


# ---- running, re-scoring, comparing ----------------------------------------------------------

def _now():
    return dt.datetime.now(dt.timezone.utc)


def _runs_dir(out_dir) -> Path:
    return Path(out_dir or paths.EVALS) / "runs"


def default_model(step: Step) -> str:
    return models.model_for(step.model_step)


def run_eval(step: Step, *, model: str | None = None, cap_usd: float = DEFAULT_CAP_USD, only=None,
             split: str = "tune", workers: int = 6, label: str = "", notes: str = "",
             out_dir=None, complete_fn=None, cache: CallCache | None = None, use_cache: bool = True,
             items: list[Item] | None = None) -> dict:
    """Run `step` on its saved inputs with `model` (an alias from models.toml, or "code:<name>"
    for a plain-code baseline), score every item, save and return the run record."""
    alias = model or default_model(step)
    if not alias.startswith(CODE_PREFIX):
        models.spec(alias)                                    # fail fast on a typo
    if cache is None and use_cache:
        cache = CallCache(Path(out_dir) / "cache" if out_dir else None)
    items = items if items is not None else step.load(only=only, split=split)
    key = step.load_key()
    started = _now()
    run_id = f"{step.name}-{started:%Y%m%dT%H%M%S}-{alias.replace(':', '_')}-{step.version}"
    tid = tracer().new_trace(f"eval:{step.name}", metadata=dict(
        run_id=run_id, step=step.name, version=step.version, model=alias, split=split,
        items=len(items), cap_usd=cap_usd, label=label))
    budget = Budget(cap_usd)
    stop = threading.Event()
    complete_fn = complete_fn or models.complete

    def one(item: Item):
        ctx = Ctx(model=alias, trace_id=tid, budget=budget, cache=cache, complete_fn=complete_fn,
                  item=item, step_name=step.name)
        if stop.is_set():
            return item, None, "skipped: the run stopped at the cost cap", ctx.stats, 0.0
        t0 = time.monotonic()
        try:
            out, err = step.run(item, ctx), None
        except BudgetExceeded as e:
            stop.set()
            out, err = None, f"stopped at the cost cap: {e}"
        except Exception as e:                                # one bad item shouldn't sink the run
            out, err = None, f"{type(e).__name__}: {e}"[:500]
        return item, out, err, ctx.stats, time.monotonic() - t0

    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        done = list(ex.map(one, items))
    wall = time.monotonic() - t_start

    rows, ok_items, ok_scores = [], [], []
    for item, out, err, stats, secs in done:
        scores = step.score(item, out, key) if out is not None else {}
        if out is not None:
            ok_items.append(item)
            ok_scores.append(scores)
        rows.append(dict(id=item.id, story=item.story, split=item.split, scores=scores, error=err,
                         seconds=round(secs, 2), output=out, **stats.as_dict()))
    rec = _record(step, alias, run_id, rows, ok_items, ok_scores, started=started, wall=wall,
                  cap_usd=cap_usd, spent=budget.spent, split=split, label=label, notes=notes,
                  trace_id=tid, stopped=stop.is_set())
    _save(rec, out_dir)
    _report_to_langfuse(rec, step)
    write_report(step, out_dir)
    return rec


def write_report(step: Step, out_dir=None):
    """Rebuild the step's visual report (report.py). A report problem never fails a run."""
    from . import report
    try:
        return report.write(step, out_dir)
    except Exception as e:                                    # pragma: no cover - reported, not raised
        print(f"note: the eval report could not be rebuilt: {type(e).__name__}: {e}")
        return None


def _record(step, alias, run_id, rows, ok_items, ok_scores, *, started, wall, cap_usd, spent, split,
            label, notes, trace_id, stopped, extra=None) -> dict:
    tokens = Counter()
    for r in rows:
        tokens.update(r.get("tokens") or {})
    errors = [r for r in rows if r["error"]]
    status = "stopped at cost cap" if stopped else ("done with errors" if errors else "done")
    summary = step.summarize(ok_items, ok_scores) if ok_items else {}
    summary["items_failed"] = len(errors)
    stories = sorted({r["story"] for r in rows})
    cost = sum(r.get("cost_usd", 0.0) for r in rows)
    rec = dict(
        run_id=run_id, step=step.name, version=step.version, key_version=step.key_version(),
        model=alias, label=label, notes=notes, split=split, status=status,
        started_at=started.isoformat(timespec="seconds"), finished_at=_now().isoformat(timespec="seconds"),
        wall_s=round(wall, 1), items=len(rows), stories=len(stories), cap_usd=cap_usd,
        cost_usd=round(cost, 6), cost_per_story_usd=round(cost / max(len(stories), 1), 6),
        spent_usd=round(spent, 6), calls=sum(r.get("calls", 0) for r in rows),
        cache_hits=sum(r.get("cache_hits", 0) for r in rows),
        model_seconds=round(sum(r.get("latency_s", 0.0) for r in rows), 1),
        tokens=dict(tokens), langfuse_trace_id=trace_id, summary=summary, items_detail=rows)
    rec.update(extra or {})
    return rec


def _save(rec: dict, out_dir=None) -> Path:
    d = _runs_dir(out_dir) / rec["step"]
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rec['run_id']}.json"
    p.write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    row = {k: v for k, v in rec.items() if k != "items_detail"}
    row["file"] = str(p.relative_to(_runs_dir(out_dir)))
    with open(_runs_dir(out_dir) / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    rec["file"] = str(p)
    return p


def _report_to_langfuse(rec: dict, step: Step) -> None:
    t = tracer()
    t.span(name="eval summary", trace_id=rec["langfuse_trace_id"],
           output={k: rec[k] for k in ("status", "summary", "cost_usd", "spent_usd", "wall_s", "calls",
                                       "cache_hits", "tokens")},
           metadata=dict(run_id=rec["run_id"], model=rec["model"], version=rec["version"]))
    for k in step.headline:
        v = rec["summary"].get(k)
        if isinstance(v, (int, float)) and v is not None:
            t.score(trace_id=rec["langfuse_trace_id"], name=k, value=float(v))
    t.score(trace_id=rec["langfuse_trace_id"], name="cost_usd", value=float(rec["cost_usd"]))
    t.flush()


def load_run(run: str | Path, out_dir=None) -> dict:
    p = Path(run)
    if not p.exists():
        hits = sorted(_runs_dir(out_dir).glob(f"*/{run}*.json"))
        if not hits:
            raise FileNotFoundError(f"no saved run matching {run}")
        p = hits[-1]
    return json.loads(p.read_text(encoding="utf-8"))


def rescore(step: Step, run: str | Path, *, out_dir=None) -> dict:
    """Score a saved run's outputs again against the current answer key. No model calls: the
    outputs are read from the run file. Saved as a new run, '<old id>-rescored-<time>'."""
    old = load_run(run, out_dir)
    key = step.load_key()
    by_id = {i.id: i for i in step.load(only=None, split="all")}
    rows, ok_items, ok_scores = [], [], []
    for r in old["items_detail"]:
        r = dict(r)
        item = by_id.get(r["id"]) or Item(id=r["id"], story=r["story"], data={}, split=r.get("split", "tune"))
        if r.get("output") is not None:
            r["scores"] = step.score(item, r["output"], key)
            ok_items.append(item)
            ok_scores.append(r["scores"])
        r["spent_usd"] = 0.0
        rows.append(r)
    started = _now()
    rec = _record(step, old["model"], f"{old['run_id']}-rescored-{started:%Y%m%dT%H%M%S}", rows, ok_items,
                  ok_scores, started=started, wall=0.0, cap_usd=0.0, spent=0.0, split=old["split"],
                  label=old.get("label", ""), notes=f"re-scored from {old['run_id']}",
                  trace_id=old.get("langfuse_trace_id"), stopped=False,
                  extra=dict(rescored_from=old["run_id"], version=old["version"]))
    rec["wall_s"] = old.get("wall_s", 0.0)
    _save(rec, out_dir)
    write_report(step, out_dir)
    return rec


def estimate(step: Step, *, model: str | None = None, only=None, split="tune", output_factor: float = 1.0,
             out_dir=None, cache: CallCache | None = None, items: list[Item] | None = None) -> dict:
    """What a run would cost, from step.plan(): input tokens counted, output guessed by the step
    (times output_factor, e.g. 3 for models that think before answering). Calls already in the
    cache cost nothing new."""
    alias = model or default_model(step)
    items = items if items is not None else step.load(only=only, split=split)
    if alias.startswith(CODE_PREFIX):
        return dict(model=alias, items=len(items), calls=0, cached_calls=0, est_usd=0.0, worst_usd=0.0)
    cache = cache or CallCache(Path(out_dir) / "cache" if out_dir else None)
    m = models.spec(alias)
    calls = cached = tin = tout = 0
    worst = 0.0
    for item in items:
        for c in step.plan(item, alias):
            params = dict(c.get("params") or {})
            params["max_tokens"] = params.get("max_tokens") or DEFAULT_MAX_TOKENS
            calls += 1
            if cache.has(call_key(m["litellm"], c["messages"], params)):
                cached += 1
                continue
            n = count_tokens(m["litellm"], c["messages"])
            tin += n
            tout += int(c.get("expect_output", 500) * output_factor)
            worst += worst_case_usd(alias, n, params["max_tokens"])
    est = (tin * m["input"] + tout * m["output"]) / 1e6
    return dict(model=alias, items=len(items), stories=len({i.story for i in items}), calls=calls,
                cached_calls=cached, input_tokens=tin, output_tokens=tout, est_usd=round(est, 4),
                worst_usd=round(worst, 4))


def index_rows(step_name: str, out_dir=None) -> list[dict]:
    p = _runs_dir(out_dir) / "index.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r["step"] == step_name]


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}"
    return "" if v is None else str(v)


def compare_table(step: Step, rows: list[dict] | None = None, out_dir=None, split: str | None = None) -> str:
    """The side-by-side table of runs (Markdown): model, prompt version, scores, cost, time."""
    rows = rows if rows is not None else index_rows(step.name, out_dir)
    if split:
        rows = [r for r in rows if r.get("split") == split]
    head = ["Run", "Model", "Version", "Split", "Stories", *step.headline, "Cost ($)", "Cost per story ($)",
            "New spend ($)", "Time (s)", "Status", "Label"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        s = r.get("summary") or {}
        cells = [r["finished_at"][:16].replace("T", " "), r["model"], r["version"], r.get("split", ""),
                 r.get("stories", ""), *[_fmt(s.get(k)) for k in step.headline], f"{r['cost_usd']:.4f}",
                 f"{r['cost_per_story_usd']:.4f}", f"{r['spent_usd']:.4f}", _fmt(r.get("wall_s")),
                 r["status"], r.get("label", "")]
        out.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(out) + "\n"
