"""One live event, end to end: modules 1 to 8 for one story (map, build order step 7; Nov 27).

The Gate (module 0) has already said go and handed over a ticket. Then, in order:

    sides (module 4's lens) -> Gather (1) -> same-story filter (2) -> follow-up for a short side (4)
    -> pick -> [cost check] -> Story File (5) -> fact check (6) -> script (7) -> video (8)

Each step is timed. Every model call is counted through models.on_cost, whichever module makes it,
and Tavily and ElevenLabs credits are priced from config/gate.toml and the Starter plan. When a step
ends, its spend goes to the ticket (which also tells the Gate the video is alive), and after the
searches the ticket checks the rest will fit under the $5 cap before the dear steps start.

The follow-up check (stringer/followup.py) runs in its own thread from the start, beside the sides step: is
this event another step of a story that already has a video? A match joins that story's chain on the front
page; it never waits the run, and a failure there never stops the video. Its result is rec["follow_up"].

Two things run beside others instead of after them (Nov 27, for the 5 minutes a viewer waits): the last
Story File calls (story_file.build_story's lanes), and the fact check's model, which starts as soon as
the claims are final and so finishes during the Story File step. Its seconds are in the story_file row;
its dollars are moved to the fact_check row.

One Langfuse trace per video: the run opens it and every model call, search and video step joins it,
with one span per step carrying its seconds and dollars. The id is rec["trace_id"].

While it runs, it keeps progress/<event>/<ticket>.json in the Gate's store up to date (stringer/progress.py):
each step's start and end, its counts and a short hand-on, and every model call, so the website's progress
page can show the run live (module 9). Runs given a Gate ticket get this on their own; `progress=` passes one
in. The fact check's calls, made during the Story File step, are filed under fact_check.

    rec = pipeline.run(raw_event, ticket)      # raw_event: one event from the live /v1/events feed
    rec["outcome"]                             # "done", "no_video" (with rec["why"]) or "planned" (render=False)
    rec["steps"]["gather"]                     # {"seconds": 41.2, "usd": 0.07, ...}

How a run can end, and what the caller does with the ticket:
    "done"                the video's files exist            -> ticket.finish(video=...)
    "no_video"            a judgment about the story: final  -> ticket.finish(no_video=why)
    "planned"             a plan-only test run, no MP4       -> ticket.cancel(...)
    TooCostly             the rest would pass the cap        -> ticket.finish(no_video=...), final
    VideoOverBudget       the cap was passed                 -> ticket.finish(no_video=...), final
    CouldNotFinish        a model gave no usable answer      -> ticket.finish(error=...): a later click may retry
    any other error       a crash                            -> ticket.finish(error=...): a later click may retry
Whatever the end, pipeline.json is written into the story folder (once the folder exists), so a failed
run leaves its timings and its reason behind. The story folder is paths.STORIES/<event id>/, the same
files the module scripts write; paths.STORIES and paths.RAW are put back when the run ends."""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import threading
import time
from pathlib import Path

from . import fact_check, lens as lens_step, models, outlets, paths, pick, same_story, story_file, tracing
from . import balance, followup
from . import progress as progress_mod
from . import script_writer as sw
from .events import from_live
from .gate import rules as gate_rules
from .gather import clients, run as gather_run, store

VERSION = "pipeline-2 (2026-11-27, lanes, one trace, outages retryable)"
LIVE = paths.PRIVATE / "live"
TAVILY_LIMIT = 40                        # most Tavily credits one video may spend (test stories used 4-12)
ELEVENLABS_USD_PER_CREDIT = 6 / 30_000   # Starter plan: $6 a month for 30,000 credits (Jan, Nov 24)


class CouldNotFinish(RuntimeError):
    """A model the video needs gave no usable answer (an outage, a timeout). Not a judgment about the
    story, so not a "no video": the caller files the run as failed, and a later click may try again."""


class Meter:
    """Model spend by step, counted from every answered call while the run is on (any thread)."""

    def __init__(self):
        self.by_step: dict[str, float] = {}
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, step, alias, usd: float) -> None:
        with self._lock:
            k = step or alias or "model"
            self.by_step[k] = self.by_step.get(k, 0.0) + usd
            self.calls += 1

    def total(self) -> float:
        with self._lock:
            return sum(self.by_step.values())


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _read(d: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
    arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
    return meta, arts


def _write_articles(d: Path, arts: list[dict]) -> None:
    store._atomic_write(d / "articles.jsonl", "\n".join(json.dumps(a, ensure_ascii=False) for a in arts) + "\n")


def _write_json(path: Path, obj) -> None:
    store._atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def _apply_verdicts(arts: list[dict], res: dict) -> None:
    """Module 2's verdicts into the articles, as scripts/filter_articles.py writes them."""
    v = res["verdicts"]
    for a in arts:
        x = v.get(a["id"]) or {}
        a.update(verdict=x.get("verdict"), verdict_reason=x.get("reason"), verdict_by=x.get("by"))


def _script_step(name: str | None) -> str:
    """The models.toml step behind one of the script writer's calls, from the name it gives the call.
    With it the call gets its own time limit and its cost is filed under the step, not the model."""
    n = str(name or "")
    return sw.LINE_STEP if n.startswith("script line") else sw.WORDS_STEP if n.startswith("script words") else "script"



FOLLOWUP_WAIT_S = 60          # the check normally ends during the sides step (one ~6 s call); never wait longer


def _start_followup(raw_event: dict, ticket, tid, event_id: str, say):
    """Starts the follow-up check in its own thread when the run has a Gate (it reads and writes the Gate's
    records). Returns (thread, result box) or None."""
    gate = getattr(ticket, "gate", None) if ticket is not None else None
    if gate is None:
        return None
    box: dict = {}
    complete = lens_step.live_complete("same_story", trace_id=tid, metadata={"event": event_id, "part": "follow_up"})

    def work():
        try:
            box["out"] = followup.check(raw_event, gate, complete)
        except Exception as e:                      # grouping is a nicety: the video goes on without it
            box["out"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    t = threading.Thread(target=work, name="follow-up", daemon=True)
    t.start()
    return t, box


def _end_followup(follow, say, wait: float = FOLLOWUP_WAIT_S) -> dict | None:
    if follow is None:
        return None
    t, box = follow
    t.join(wait)
    out = box.get("out") or {"error": f"still running after {wait:.0f} s"}
    if out.get("error"):
        say(f"  follow-up    {out['error']}"[:200])
    else:
        say(f"  follow-up    {out.get('seconds', 0):>6.1f} s  candidates {out.get('candidates')}  "
            f"matches {len(out.get('matches') or [])}  chain {out.get('chain') or '-'}")
    return out


def run(raw_event: dict, ticket=None, *, stories_dir: Path | None = None, raw_dir: Path | None = None,
        tavily_limit: float = TAVILY_LIMIT, voice_engine=None, music: Path | None = None, render: bool = True,
        progress=None, say=print) -> dict:
    """Modules 1-8 for one live event. `ticket` (the Gate's) gets each step's spend; None runs uncharged.
    `progress` (a progress.Progress) gets each step live; a Gate ticket brings its own."""
    from .video import make  # the video module imports Remotion helpers; load it only when a run starts

    ev = from_live(raw_event)
    P = progress
    if P is None and ticket is not None and getattr(ticket, "gate", None) is not None:
        try:
            P = progress_mod.Progress(ticket.gate.store, ev.id, ticket.id, title=ev.title, say=say)
        except Exception as e:                      # no live page for this run; the video still gets made
            say(f"  progress: off ({e!r})"[:200])
            P = None
    price = gate_rules.config()["cost"]["tavily_usd_per_credit"]
    meter, t_all = Meter(), time.time()
    tr = tracing.tracer()
    tid = tr.new_trace(f"video:{ev.short} {ev.title[:60]}", {"event": ev.id, "title": ev.title},
                       input={"event": ev.id, "title": ev.title}, keep_open=True)
    before_paths = (paths.STORIES, paths.RAW)                 # put back in the `finally` below
    paths.STORIES = Path(stories_dir or LIVE / "stories")     # live stories stay out of the frozen test set
    paths.RAW = Path(raw_dir or LIVE / "raw")
    paths.RAW.mkdir(parents=True, exist_ok=True)
    rec = dict(version=VERSION, event=ev.id, title=ev.title, started=_now(), trace_id=tid, steps={}, outcome=None)
    state = {"model_usd": 0.0}
    folder = {"d": None}

    def begin(name: str) -> float:
        return P.begin(name) if P is not None else time.time()

    def read(name: str):
        if folder["d"] is None:
            return None
        return progress_mod.folder_reader(folder["d"])(name)

    def done(name: str, t0: float, extra_usd: float = 0.0, hands_on: dict | None = None, **info) -> dict:
        model_now = meter.total()
        usd = max(0.0, (model_now - state["model_usd"]) + extra_usd)
        state["model_usd"] = model_now
        row = dict(seconds=round(time.time() - t0, 2), usd=round(usd, 5), **info)
        rec["steps"][name] = row
        say(f"  {name:<12} {row['seconds']:>6.1f} s  ${row['usd']:.4f}  "
            + "  ".join(f"{k} {v}" for k, v in info.items() if not isinstance(v, (dict, list))))
        tr.span(name=f"step.{name}", trace_id=tid, output=dict(seconds=row["seconds"], usd=row["usd"]),
                metadata={k: v for k, v in row.items() if not isinstance(v, (dict, list))})
        if P is not None:
            h = hands_on if hands_on is not None else progress_mod.summarize(name, read, row, table=state.get("table"))
            P.end(name, row, hands_on=h, searches=progress_mod.searches_of(read) if name == "gather" else None)
        if ticket is not None:
            ticket.charge(usd, name)
        return row

    def finish(outcome: str, why: str = "", video: dict | None = None) -> dict:
        rec.update(outcome=outcome, why=why or None, video=video, seconds=round(time.time() - t_all, 2),
                   usd=round(sum(s["usd"] for s in rec["steps"].values()), 5), model_calls=meter.calls,
                   model_usd_by_step={k: round(v, 5) for k, v in sorted(meter.by_step.items())}, finished=_now())
        d = store.story_dir(ev.id)
        if d.exists():
            _write_json(d / "pipeline.json", rec)
        if P is not None:
            P.finish(outcome, why or None, seconds=rec["seconds"], usd=rec["usd"])
        return rec

    follow = None
    watch = models.on_call(P.call) if P is not None else contextlib.nullcontext()
    try:
        with models.on_cost(meter), models.live_timeouts(), watch:
            # the follow-up check (stringer/followup.py): one model call beside the sides step, never a wait.
            # Is this event another step of a story that already has a video? A match joins its story chain.
            follow = _start_followup(raw_event, ticket, tid, ev.id, say)

            # module 4's lens: which two camps of outlets the video compares (or none)
            t0 = begin("sides")
            table = outlets.table()
            state["table"] = table
            lens_call = lens_step.live_complete("lens", trace_id=tid, metadata={"event": ev.id})
            chosen, lens_rec = lens_step.choose(ev, table, lens_call, model=models.model_for("lens"))
            lens_step.record_new_sides(ev, chosen)
            done("sides", t0, kind=chosen.kind,
                 hands_on=progress_mod.summarize("sides", lambda n: lens_rec if n == "lens.json" else None, table=table)
                 if P is not None else None)

            # module 1: searches, merge, labels -> the story folder. The article cache sits beside the
            # run's own folders, never in the frozen test set's.
            t0 = begin("gather")
            tv = clients.Tavily(ledger=clients.CreditLedger(limit=tavily_limit), raw_dir=str(paths.RAW))
            gd = clients.Guardian(raw_dir=str(paths.RAW))
            cache = store.ArticleCache(root=str(paths.RAW.parent / "article_cache"))
            meta = gather_run.gather_event(ev, chosen, table, tv, gd, writer="model", window_days=2,
                                           cache=cache, trace_id=tid)
            d = store.story_dir(ev.id)
            folder["d"] = d
            _write_json(d / "lens.json", lens_rec)
            rec["follow_up"] = _end_followup(follow, say)
            credits = tv.ledger.spent
            done("gather", t0, extra_usd=credits * price, articles=meta["counts"]["articles"], tavily_credits=credits,
                 query_writer=(meta.get("queries") or {}).get("writer"))

            # module 2: same story / follow-up / different for every article
            t0 = begin("same_story")
            meta, arts = _read(d)
            judge = lens_step.live_complete("same_story", trace_id=tid, metadata={"event": ev.id})
            res = same_story.filter_story(meta["event"], arts, judge, lens=meta["lens"])
            _apply_verdicts(arts, res)
            _write_articles(d, arts)
            _write_json(d / "same_story.json", dict(version=res["version"], model=models.model_for("same_story"),
                                                    run_id="live", applied_at=_now(), counts=res.get("counts"),
                                                    flags=res.get("flags"), sides=res.get("sides"),
                                                    problems=res.get("problems"), verdicts=res["verdicts"]))
            done("same_story", t0, counts=res.get("counts") or {})

            # module 4's follow-up: one more round for a side that came up short, then the pick
            t0 = begin("balance_pick")
            before = tv.ledger.spent
            short = balance.estimate(meta["lens"], arts, table)["sides"]
            if short:
                brec = balance.followup(meta, arts, table, tv, judge, trace_id=tid)
                _write_articles(d, arts)
                _write_json(d / "balance.json", brec)
            p = pick.pick(arts, meta["lens"])
            p["event"] = meta["event"]["id"]
            _write_json(d / "picked.json", p)
            credits = tv.ledger.spent - before
            done("balance_pick", t0, extra_usd=credits * price, short_sides=len(short), tavily_credits=credits,
                 picked=len(p["picked"]), pick_flags=p["flags"])

            # the Gate's second look: will the dear steps fit under the cap? (raises TooCostly)
            # It scales the reading step by the articles that will be read: the picked ones, not the pool.
            if ticket is not None:
                rec["estimate_after_gather"] = ticket.checkpoint(n_articles=len(p["picked"]))
                if P is not None:
                    P.note(estimate_usd=(rec["estimate_after_gather"] or {}).get("usd"))

            # module 5: the Story File (news brief), with module 6's judge started beside its last calls
            t0 = begin("story_file")
            fc_model = models.model_for("fact_check")
            by_id = {a["id"]: a for a in arts}
            early: dict = {}

            def fc_complete(messages, name=None, **params):
                return models.complete("fact_check", messages, model=fc_model, trace_id=tid, name=name or "fact_check",
                                       **params)

            def judge_early(facts0, sf0):
                t = time.time()
                early["judged"] = fact_check.judge_early(sf0, facts0, by_id, fc_complete, model=fc_model, table=table)
                early["seconds"] = round(time.time() - t, 2)
            facts, sf = story_file.build_story(meta, arts, trace_id=tid, early=judge_early)
            problems = story_file.validate(sf, facts)
            story_file.write(d, facts, sf)
            judge_usd = meter.by_step.get("fact_check", 0.0)          # spent during this step, belongs to the next
            done("story_file", t0, extra_usd=-judge_usd, facts=len(facts), claims=len(sf["claims"]),
                 problems=len(problems))

            # module 6: the fact check's rules, on the judge's answer from above
            t0 = begin("fact_check")
            facts, sf = fact_check.check_folder(d, fc_complete, model=fc_model, table=table, judged=early.get("judged"))
            fact_check.write_checked(d, facts, sf)
            done("fact_check", t0, extra_usd=judge_usd, judge_seconds=early.get("seconds"),
                 **{k: v for k, v in (sf["fact_check"]["counts"] or {}).items()})

            # module 7: the script
            t0 = begin("script")

            def sc_complete(messages, name=None, model=None, **params):
                return models.complete(_script_step(name), messages, model=model, trace_id=tid, name=name or "script",
                                       **params)
            script = sw.write_folder(d, sc_complete, model=models.model_for("script"))
            sw.write_file(d, script)
            done("script", t0, status=script["status"], words=script.get("words"), held=script.get("held") or [])
            if script["status"] == "no video":
                if script.get("broke"):                 # a model gave no answer: a failure, not a judgment
                    raise CouldNotFinish(f"script: {script['broke']}")
                return finish("no_video", f"script: {script.get('reason') or 'no video'}")

            # module 8: the video
            t0 = begin("video")
            vrec = make.make(d, voice_engine, music=music if music is not None else
                             (make.MUSIC if make.MUSIC.exists() else None), render=render, trace_id=tid)
            vcredits = ((vrec.get("steps") or {}).get("voice") or {}).get("credits") or 0
            steps = {k: v.get("seconds") for k, v in (vrec.get("steps") or {}).items() if isinstance(v, dict)}
            vsteps = vrec.get("steps") or {}
            vinfo = dict(status=vrec["status"], voice_credits=vcredits, parts_seconds=steps,
                         duration_s=(vsteps.get("voice") or {}).get("duration"),
                         frames=(vsteps.get("plan") or {}).get("frames"), captions=(vsteps.get("plan") or {}).get("captions"),
                         beats=(vsteps.get("plan") or {}).get("beats"))
            done("video", t0, extra_usd=vcredits * ELEVENLABS_USD_PER_CREDIT, status=vrec["status"],
                 voice_credits=vcredits, parts_seconds=steps,
                 hands_on=progress_mod.summarize("video", read, vinfo) if P is not None else None)
            if vrec["status"] == "stopped":
                return finish("no_video", f"video: {vrec.get('why')}")
            out = Path(vrec.get("out_dir") or d / "video")
            duration = ((vrec.get("steps") or {}).get("voice") or {}).get("duration")
            if vrec["status"] != "rendered":            # render=False: a plan and a voice, no MP4 to show
                return finish("planned", video=dict(plan=str(out / "plan.json"), duration_s=duration, status=vrec["status"]))
            video = dict(mp4=str(out / "video.mp4"), poster=str(out / "poster.jpg"), duration_s=duration,
                         status=vrec["status"])
            return finish("done", video=video)
    except Exception as e:
        too_costly = type(e).__name__ in ("TooCostly", "VideoOverBudget")
        finish("no_video" if too_costly else "failed", (f"too costly: {e}" if too_costly else repr(e))[:500])
        raise
    finally:
        if follow is not None and rec.get("follow_up") is None:
            rec["follow_up"] = _end_followup(follow, say, wait=0)
        paths.STORIES, paths.RAW = before_paths
        tr.end_trace(tid, output={k: rec.get(k) for k in ("outcome", "why", "video", "seconds", "usd", "model_calls")},
                     error=rec.get("why") if rec.get("outcome") == "failed" else None)
        tr.flush()
