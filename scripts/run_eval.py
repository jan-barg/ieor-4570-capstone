"""Run a step's eval on the frozen stories, estimate its cost, re-score a saved run, or print the
comparison table (stringer/evals/runner.py explains the parts).

    python -m scripts.run_eval estimate same_story --model haiku-5-5        # free: tokens and $ estimate
    python -m scripts.run_eval run same_story --model haiku-5-5 --cap 0.50  # costs money; hard cap
    python -m scripts.run_eval run same_story --model code:keywords         # plain-code baseline, free
    python -m scripts.run_eval rescore same_story <run id>                  # new answer key, no model calls
    python -m scripts.run_eval compare same_story                           # the side-by-side table
    python -m scripts.run_eval report same_story                            # rebuild the visual report

--split tune (default) runs only the stories used for prompt changes; holdout runs the ones kept out
of them; all runs both. Results go to stringer_private/evals/ (private: outputs can quote articles).
Every run and re-score also rebuilds the step's visual report, evals/<step>_report.html."""
from __future__ import annotations

import argparse
import json
import sys

from stringer import paths
from stringer.evals import runner, steps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "estimate"):
        p = sub.add_parser(name)
        p.add_argument("step", choices=steps.names())
        p.add_argument("--model", help="alias from config/models.toml, or code:<baseline>")
        p.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
        p.add_argument("--only", nargs="*", help="event short ids")
        p.add_argument("--all-stories", action="store_true",
                       help="every frozen story, not just labeled ones (same_story only; other steps refuse it)")
        p.add_argument("--opt", action="append", default=[], help="step option key=value (e.g. batch=25)")
    pr = sub.choices["run"]
    pr.add_argument("--cap", type=float, default=runner.DEFAULT_CAP_USD, help="hard cost cap in USD")
    pr.add_argument("--workers", type=int, default=6)
    pr.add_argument("--label", default="")
    pr.add_argument("--notes", default="")
    pr.add_argument("--no-cache", action="store_true")
    sub.choices["estimate"].add_argument("--output-factor", type=float, default=1.0,
                                         help="multiply the guessed output (3 for models that think first)")
    rs = sub.add_parser("rescore")
    rs.add_argument("step", choices=steps.names())
    rs.add_argument("run_id")
    cp = sub.add_parser("compare")
    cp.add_argument("step", choices=steps.names())
    cp.add_argument("--split")
    cp.add_argument("--write", action="store_true", help=f"also write {paths.EVALS}/<step>_comparison.md")
    rp = sub.add_parser("report")
    rp.add_argument("step", choices=steps.names())
    a = ap.parse_args(argv)

    opts = dict(o.split("=", 1) for o in getattr(a, "opt", []))
    if getattr(a, "all_stories", False):
        opts["all_stories"] = "1"
    step = steps.get(a.step, **opts)
    if a.cmd == "estimate":
        e = runner.estimate(step, model=a.model, only=a.only, split=a.split, output_factor=a.output_factor)
        print(json.dumps(e, indent=1))
    elif a.cmd == "run":
        rec = runner.run_eval(step, model=a.model, cap_usd=a.cap, only=a.only, split=a.split,
                              workers=a.workers, label=a.label, notes=a.notes, use_cache=not a.no_cache)
        print(f"{rec['run_id']}: {rec['status']}; {rec['stories']} stories, {rec['calls']} calls "
              f"({rec['cache_hits']} from cache); cost ${rec['cost_usd']:.4f}, new spend ${rec['spent_usd']:.4f}, "
              f"{rec['wall_s']} s")
        print(json.dumps({k: v for k, v in rec["summary"].items() if k != "stories"}, indent=1))
        for r in rec["items_detail"]:
            if r["error"]:
                print(f"  {r['id']}: {r['error']}")
        print(f"saved {rec['file']}")
        print(f"report {paths.EVALS / f'{a.step}_report.html'}")
    elif a.cmd == "report":
        print(f"wrote {runner.write_report(step)}")
    elif a.cmd == "rescore":
        rec = runner.rescore(step, a.run_id)
        print(json.dumps({k: v for k, v in rec["summary"].items() if k != "stories"}, indent=1))
        print(f"saved {rec['file']}")
    else:
        t = runner.compare_table(step, split=a.split)
        print(t)
        if a.write:
            p = paths.EVALS / f"{a.step}_comparison.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {a.step}: eval runs\n\n{t}", encoding="utf-8")
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
