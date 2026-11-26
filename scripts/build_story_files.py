"""Write each story's facts.jsonl and story_file.json (module 5), plus one page of readable briefs.

    python -m scripts.build_story_files from-runs            free: joins the saved eval runs of every step
        [--merge merge-12]          a step 2 version on trial: written to story_files/<version>/ instead
        [--framing-merge merge-11]  take step 4 from runs made on another step 2 version (its points quote
                                    articles, not claims, so they stay valid when only claims change)
    python -m scripts.build_story_files live --only <id> --cap <usd>   paid: runs every step live
        (its brief page goes to story_files/live/)

from-runs uses, per story, the latest run of the blindspot judge and of step 4 made with the decided
models and current versions; both point to the step 2 run (and through it the step 1 run) they
read, which must be the same one. Step 3 is code and is inside both outputs.

Writes into each story's folder (stringer_private/frozen/stories/<event id>/) and
stringer_private/story_file_design/story_files/ (briefs.html and summary.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stringer import (brief_blind, brief_framing, brief_merge, brief_read, brief_sides, models, paths,
                      story_brief, story_file)

RUNS = paths.EVALS / "runs"
OUT = paths.PRIVATE / "story_file_design" / "story_files"


def _latest(step: str, version: str) -> dict:
    model = models.model_for(step)
    files = sorted((RUNS / step).glob(f"{step}-*-{model}-{version}.json"))
    if not files:
        sys.exit(f"no {step} run for {model} {version}")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _run(step: str, run_id: str, cache: dict) -> dict:
    if run_id not in cache:
        cache[run_id] = json.loads((RUNS / step / f"{run_id}.json").read_text(encoding="utf-8"))
    return cache[run_id]


def _by_story(run: dict) -> dict:
    return {r["story"]: r for r in run.get("items_detail") or [] if r.get("output")}


def _dirs() -> dict:
    return {d.name[:8]: d for d in paths.STORIES.iterdir() if d.is_dir()}


def from_runs(merge: str | None = None, framing_merge: str | None = None) -> list[tuple]:
    merge = merge or brief_merge.VERSION
    framing_merge = framing_merge or merge
    blind = _latest("brief_blind", f"{brief_blind.VERSION}-{brief_sides.VERSION}-{merge}-n10")
    frame = _latest("brief_framing", f"{brief_framing.VERSION}-{brief_sides.VERSION}-{framing_merge}-n10")
    trial = merge != brief_merge.VERSION
    b_rows, f_rows, dirs, cache = _by_story(blind), _by_story(frame), _dirs(), {}
    print(f"judge run {blind['run_id']}\nstep 4 run {frame['run_id']}")
    done = []
    for story in sorted(b_rows):
        b, f = b_rows[story]["output"], (f_rows.get(story) or {}).get("output")
        if b.get("error") or not f or f.get("error"):
            print(f"{story}: skipped (missing or failed output)")
            continue
        if b["step2_run"] != f["step2_run"] and framing_merge == merge:
            print(f"{story}: skipped (the judge and step 4 read different step 2 runs)")
            continue
        r2 = _run("brief_merge", b["step2_run"], cache)
        r1 = _run("brief_read", b["step1_run"], cache)
        step2 = _by_story(r2)[story]["output"]
        step1 = _by_story(r1)[story]["output"]
        meta = json.loads((dirs[story] / "gather.json").read_text(encoding="utf-8"))
        steps = dict(brief_read=dict(version=step1.get("version"), model=r1["model"], run=r1["run_id"]),
                     brief_merge=dict(version=step2.get("version"), model=r2["model"], run=r2["run_id"]),
                     brief_sides=dict(version=b.get("version"), model="code"),
                     brief_blind=dict(version=(b.get("blind_counts") or {}).get("version"), model=blind["model"], run=blind["run_id"]),
                     brief_framing=dict(version=(f.get("framing") or {}).get("version"), model=frame["model"], run=frame["run_id"],
                                        step2_run=f["step2_run"]))
        # steps 1 and 2's eval items also paid for their judges, so only 3b and 4 give a production cost
        cost = dict(brief_read=None, brief_merge=None, brief_blind=b_rows[story].get("cost_usd"),
                    brief_framing=f_rows[story].get("cost_usd"))
        facts, sf = story_file.assemble(meta, step1, step2, b, f.get("framing"), steps=steps, cost_usd=cost)
        probs = story_file.validate(sf, facts)
        story_file.write(OUT / merge / dirs[story].name if trial else dirs[story], facts, sf)
        done.append((facts, sf, probs))
        print(f"{story}: {len(facts)} facts, {len(sf['claims'])} claims, "
              f"{'ok' if not probs else str(len(probs)) + ' problems: ' + '; '.join(probs[:3])}")
    return done


def live(only: str, cap: float) -> list[tuple]:
    dirs = _dirs()
    d = dirs.get(only[:8]) or sys.exit(f"no story {only}")
    meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
    arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
    facts, sf = story_file.build_story(meta, arts, cap_usd=cap, trace_id=meta.get("langfuse_trace_id"))
    probs = story_file.validate(sf, facts)
    story_file.write(d, facts, sf)
    print(f"{only[:8]}: {len(facts)} facts, {len(sf['claims'])} claims, cost ${sf['meta']['cost_usd']['total']}, "
          f"{'ok' if not probs else probs}")
    return [(facts, sf, probs)]


def summarize(done: list[tuple]) -> dict:
    tot = lambda k: sum((sf["counts"].get(k) or 0) for _, sf, _ in done)
    return dict(version=story_file.VERSION, stories=len(done), problems=sum(len(p) for *_, p in done),
                two_sides=sum((sf.get("sides") or {}).get("kind") == "two sides" for _, sf, _ in done),
                facts=tot("facts"), claims=tot("claims"), conflicts=tot("conflicts"), updates=tot("updates"),
                blindspots_central=tot("blindspots_central"), blindspots_detail=tot("blindspots_detail"),
                perspective_points=tot("perspective_points"),
                flags={code: sum(any(f["code"] == code for f in sf["flags"]) for _, sf, _ in done)
                       for code in brief_sides.FLAGS},
                story_file_kb=[round(len(json.dumps(sf, ensure_ascii=False)) / 1000, 1) for _, sf, _ in done],
                errors=[x for _, sf, _ in done for x in sf["meta"]["errors"]])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("from-runs", "live"))
    ap.add_argument("--only")
    ap.add_argument("--cap", type=float)
    ap.add_argument("--merge")
    ap.add_argument("--framing-merge")
    a = ap.parse_args(argv)
    if a.mode == "live" and (not a.only or a.cap is None):
        sys.exit("live needs --only <story id> and --cap <usd>: it pays for model calls")
    done = from_runs(a.merge, a.framing_merge) if a.mode == "from-runs" else live(a.only, a.cap)
    # live runs and trial versions get their own page, so the from-runs page of all stories stays whole
    out = OUT / "live" if a.mode == "live" else OUT / a.merge if a.merge and a.merge != brief_merge.VERSION else OUT
    out.mkdir(parents=True, exist_ok=True)
    s = summarize(done)
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    intro = (f"{len(done)} stories, built by code from the saved runs of every step "
             f"(Story File {story_file.VERSION}). Click a row or pick a story. Private: quotes real articles.")
    (out / "briefs.html").write_text(story_brief.page(done, "Story Files", intro), encoding="utf-8")
    print(json.dumps({k: v for k, v in s.items() if k != "story_file_kb"}, indent=1))
    print("pages", out / "briefs.html")


if __name__ == "__main__":
    main()
