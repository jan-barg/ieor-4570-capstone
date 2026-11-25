"""Apply the same-story filter (module 2) to every frozen story, then the pick step can skip the
articles it marks "different".

    python -m scripts.filter_articles --model haiku-5-5 --cap 1.00    # runs it (costs money; hard cap)
    python -m scripts.filter_articles --from-run <run id>             # writes a saved run's verdicts, free
    python -m scripts.pick_articles                                   # then re-pick

It goes through the eval runner, so calls already made in an eval come from the cache for free,
the run is one Langfuse trace, and it is saved like any eval run. Per story it writes:
  articles.jsonl   each row's `verdict` (same / follow_up / different / null), `verdict_reason`, `verdict_by`
  same_story.json  the filter's own record: version, model, run id, counts, flags, side check, verdicts
                   (kept apart so a rebuild of articles.jsonl can get the verdicts back with --reapply)"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from stringer import paths
from stringer.evals import runner
from stringer.evals.same_story_eval import SameStoryEval
from stringer.gather import store


def write_story(story_dir, out: dict, *, model: str, run_id: str) -> dict:
    arts = [json.loads(line) for line in (story_dir / "articles.jsonl").read_text(encoding="utf-8").split("\n") if line.strip()]
    v = out["verdicts"]
    for a in arts:
        x = v.get(a["id"]) or {}
        a["verdict"] = x.get("verdict")
        a["verdict_reason"] = x.get("reason")
        a["verdict_by"] = x.get("by")
    lines = "\n".join(json.dumps(a, ensure_ascii=False) for a in arts)
    store._atomic_write(story_dir / "articles.jsonl", lines + "\n")
    rec = dict(version=out["version"], model=model, run_id=run_id,
               applied_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               counts=out.get("counts"), flags=out.get("flags"), sides=out.get("sides"),
               problems=out.get("problems"), verdicts=v)
    store._atomic_write(story_dir / "same_story.json", json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model")
    ap.add_argument("--cap", type=float, default=1.0)
    ap.add_argument("--from-run", help="write the verdicts of a saved eval run instead of running")
    ap.add_argument("--reapply", action="store_true", help="copy each story's same_story.json back into articles.jsonl")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    dirs = {d.name[:8]: d for d in sorted(paths.STORIES.iterdir()) if (d / "gather.json").exists()}

    if a.reapply:
        for sid, d in dirs.items():
            p = d / "same_story.json"
            if p.exists() and (not a.only or sid in a.only):
                rec = json.loads(p.read_text(encoding="utf-8"))
                write_story(d, rec, model=rec["model"], run_id=rec["run_id"])
                print(f"{sid} reapplied ({rec['model']}, {rec['run_id']})")
        return 0

    step = SameStoryEval(all_stories=True)
    if a.from_run:
        rec = runner.load_run(a.from_run)
    else:
        items = [i for i in step.load(only=a.only, split="all") if i.id.startswith("articles:")]
        rec = runner.run_eval(step, model=a.model, cap_usd=a.cap, split="all", items=items, workers=a.workers,
                              label="apply to the frozen stories")
        print(f"{rec['run_id']}: {rec['status']}; cost ${rec['cost_usd']:.4f}, new spend ${rec['spent_usd']:.4f}, "
              f"{rec['calls']} calls ({rec['cache_hits']} cached), {rec['wall_s']} s")
    total, flagged = {}, 0
    for row in rec["items_detail"]:
        if not row["id"].startswith("articles:") or row.get("output") is None:
            if row["id"].startswith("articles:"):
                print(f"{row['story']} NOT WRITTEN: {row['error']}")
            continue
        if a.only and row["story"] not in a.only:
            continue
        out = write_story(dirs[row["story"]], row["output"], model=rec["model"], run_id=rec["run_id"])
        c = out["counts"] or {}
        for k, n in c.items():
            total[k] = total.get(k, 0) + n
        flagged += bool(out["flags"])
        print(f"{row['story']} {json.dumps(c, sort_keys=True)}  {'; '.join(out['flags'] or [])}")
    print(f"verdicts in all: {json.dumps(total, sort_keys=True)}; {flagged} stories flagged. "
          f"Next: python -m scripts.pick_articles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
