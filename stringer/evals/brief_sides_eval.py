"""The eval for module 5, step 3 (code adds sides, blindspots, independent sources and flags).

Run it with the model "code:sides" (no model is called, so it costs nothing):
    python -m scripts.run_eval run brief_sides --model code:sides --split all

Input: step 2's saved output (the latest run per story of the current step 2 version with the
decided step 2 model; option merge=<run file>[,<run file>] picks others, later files win), the step
1 run that step 2 used, and the same pick of 10 articles. So step 3's numbers move only when step 3
changes.

There is no answer key for sides or blindspots: these are counts to read, plus a hand check. A
model judge for blindspots (is the fact really missing from that side, and does it matter) comes
later.

Scores (stories with two sides unless said otherwise):
  blindspot_stories   stories where blindspots can be counted against at least one side
                      (that side has 2+ read articles)
  blindspots_per_story  blindspot candidates per such story
  one_side_share      claims reported by exactly one side
  both_sides_share    claims reported by both sides
  neither_only_share  claims only outlets on neither side report (wires, unlabeled outlets)
  unrated_only        claims whose sources are all unrated (all stories)
  low_reliability     claims whose rated sources all score under 0.5 (all stories)
  same_sentence_joined  claims where two articles gave the same sentence and count once (all stories)
  stories_failed      stories with no step 2 output to work from (must stay 0)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .. import brief_merge, brief_sides, models, paths, pick
from .brief_read_eval import BriefReadEval
from .runner import Item


class BriefSidesEval(BriefReadEval):
    name = "brief_sides"
    model_step = None
    headline = ("blindspots_per_story", "blindspot_stories", "one_side_share", "both_sides_share",
                "neither_only_share", "unrated_only", "low_reliability", "same_sentence_joined", "stories_failed")
    report_title = "News brief, step 3: sides and blindspots (code)"
    report_intro = ("Code adds to each claim from step 2 which sides report it, how many independent sources back it "
                    "(a wire copy or the same sentence counts once) and flags for unrated or low-reliability sources; "
                    "it lists blindspots (claims one side reports and the other, with 2+ articles, doesn't) and the "
                    "story's flags. No answer key: these are counts to read and check by hand.")
    metric_notes = {
        "blindspots_per_story": ("Blindspots per story", "Blindspot candidates per story where they can be counted."),
        "blindspot_stories": ("Stories with blindspots counted", "Two-side stories where at least one side has 2+ read articles."),
        "one_side_share": ("One side only", "Share of claims (two-side stories) that exactly one side reports."),
        "both_sides_share": ("Both sides", "Share of claims (two-side stories) that both sides report."),
        "neither_only_share": ("Neither side only", "Share of claims (two-side stories) only wires and unlabeled outlets report."),
        "unrated_only": ("Unrated only", "Claims whose sources are all unrated."),
        "low_reliability": ("Low reliability", "Claims whose rated sources all score under 0.5."),
        "same_sentence_joined": ("Same sentence joined", "Claims where two articles gave the same sentence and count once."),
        "stories_failed": ("Failed stories", "Stories with no step 2 output. Must be 0."),
    }

    def __init__(self, n=None, stories_dir=None, sheets=None, merge=None, merge_version=None, runs_dir=None):
        super().__init__(n=n, stories_dir=stories_dir, sheets=sheets)
        self.merge_version = merge_version or brief_merge.VERSION
        self.merge_paths = [Path(p) for p in merge.split(",")] if merge else None
        self.runs_dir = Path(runs_dir or paths.EVALS / "runs")
        self._step2, self._step1 = None, {}
        self._lock = threading.Lock()      # run() is called from several workers at once
        self.version = f"{brief_sides.VERSION}-{self.merge_version}-n{self.n}"

    def step2(self) -> dict:
        """{story: (step 2 output, step 2 run id)}, the latest run per story."""
        with self._lock:
            if self._step2 is None:
                paths_ = self.merge_paths
                if paths_ is None:
                    model = models.model_for("brief_merge")
                    paths_ = sorted((self.runs_dir / "brief_merge").glob(
                        f"brief_merge-*-{model}-{self.merge_version}-n{self.n}.json"))
                got = {}
                for p in paths_:
                    d = json.loads(Path(p).read_text(encoding="utf-8"))
                    for r in d.get("items_detail") or []:
                        if r.get("output") and (r["output"].get("claims") or not r["output"]["checks"].get("error")):
                            got[r["story"]] = (r["output"], d.get("run_id"))
                self._step2 = got
            return self._step2

    def step1(self, run_id: str) -> dict:
        with self._lock:
            if run_id not in self._step1:
                d = json.loads((self.runs_dir / "brief_read" / f"{run_id}.json").read_text(encoding="utf-8"))
                self._step1[run_id] = {r["story"]: r["output"] for r in d.get("items_detail") or [] if r.get("output")}
            return self._step1[run_id]

    def _story(self, item: Item):
        d = Path(item.data["dir"])
        meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
        arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
        p = pick.pick(arts, meta["lens"], n=100_000 if self.n == "all" else int(self.n))
        by = {a["id"]: a for a in arts}
        return meta["event"], meta["lens"], [by[i] for i in p["picked"]], {r["id"]: r["group"] for r in p["rows"]}

    def run(self, item: Item, ctx):
        got = self.step2().get(item.story)
        if not got:
            return {"error": "no step 2 output for this story", "claims": [], "counts": {}}
        step2, run2 = got
        s1_run = step2.get("step1_run")
        step1 = self.step1(s1_run).get(item.story) if s1_run else None
        event, lens, arts, groups = self._story(item)
        out = brief_sides.add_sides(step2, step1, arts, groups, lens, event)
        out.update(step2_run=run2, step1_run=s1_run)
        return out

    def score(self, item: Item, output, key: dict) -> dict:
        c = output.get("counts") or {}
        sides = (output.get("sides") or {}).get("kind") == "two sides"
        flags = [f["code"] for f in output.get("flags") or []]
        ra, rb = c.get("read_A") or 0, c.get("read_B") or 0
        can_blind = sides and min(ra, rb) >= 1 and max(ra, rb) >= brief_sides.MIN_SILENT
        return dict(two_sides=sides, can_blind=bool(can_blind), claims=c.get("claims", 0),
                    one_side=c.get("one_side", 0) if sides else 0, both_sides=c.get("both_sides", 0) if sides else 0,
                    neither_only=c.get("neither_only", 0) if sides else 0, blindspots=c.get("blindspots", 0),
                    unrated_only=c.get("unrated_only", 0), low_reliability=c.get("low_reliability", 0),
                    same_sentence_joined=c.get("same_sentence_joined", 0), read_A=c.get("read_A"), read_B=c.get("read_B"),
                    flags=flags, failed=bool(output.get("error")))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k, w=None: sum((s.get(k) or 0) for s in scores if w is None or s.get(w))
        two = tot("claims", "two_sides")
        nb = sum(bool(s.get("can_blind")) for s in scores)
        flag_counts = {}
        for s in scores:
            for f in s.get("flags") or []:
                flag_counts[f] = flag_counts.get(f, 0) + 1
        return dict(blindspots_per_story=round(tot("blindspots") / nb, 1) if nb else None, blindspot_stories=nb,
                    two_side_stories=sum(bool(s.get("two_sides")) for s in scores),
                    one_side_share=round(tot("one_side", "two_sides") / two, 3) if two else None,
                    both_sides_share=round(tot("both_sides", "two_sides") / two, 3) if two else None,
                    neither_only_share=round(tot("neither_only", "two_sides") / two, 3) if two else None,
                    unrated_only=tot("unrated_only"), low_reliability=tot("low_reliability"),
                    same_sentence_joined=tot("same_sentence_joined"), claims=tot("claims"),
                    blindspots=tot("blindspots"), story_flags=flag_counts, stories_failed=tot("failed"),
                    stories={i.story: s.get("blindspots") for i, s in zip(items, scores)})
