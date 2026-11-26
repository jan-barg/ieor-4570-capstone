"""The eval for module 5, step 4: how each side tells it (brief_framing.py).

    python -m scripts.run_eval estimate brief_framing --split all
    python -m scripts.run_eval run brief_framing --split all --cap <approved>   (--opt prompt=frame-1 for the first prompt)

Input: the same as step 3 (the latest run of the current step 2 version per story, the step 1 run it used, the pick of 10
articles); step 3 runs first, in code, then one call per story with two sides.

No answer key: code checks every quote, and the report lists every point with its quotes for a hand
check. The design's judge (another model family grades each point; Jan grades the judge on about 6
stories) comes later.

Scores (stories with two sides):
  points_per_side    kept points per side described (2-3 asked)
  pattern_share      kept points whose quotes come from 2+ of the side's outlets
  sides_described    sides with at least one kept point
  quotes_bad_first   quotes not found word for word on the first answer
  points_dropped     points left with no good quote after the retry
  stories_failed     stories with no step 2 output, or no usable answer (must stay 0)
"""
from __future__ import annotations

from .. import brief_framing, brief_sides
from .brief_sides_eval import BriefSidesEval
from .runner import Item


class BriefFramingEval(BriefSidesEval):
    name = "brief_framing"
    model_step = "brief_framing"
    headline = ("points_per_side", "pattern_share", "sides_described", "quotes_bad_first", "points_dropped", "stories_failed")
    report_title = "News brief, step 4: how each side tells it"
    report_intro = ("For each story with two sides, one call reads each side's headlines, openings and word choices (from step 1) "
                    "and the claims only that side reports, and gives 2-3 points per side on how its outlets tell the story "
                    "differently: words, emphasis, voices, blame or credit. Every point quotes the side's own words; code "
                    "checks each quote word for word. No answer key: the list below is for a hand check.")
    metric_notes = {
        "points_per_side": ("Points per side", "Kept points per side described (2-3 asked)."),
        "pattern_share": ("Shared by 2+ outlets", "Kept points whose quotes come from 2 or more of the side's outlets."),
        "sides_described": ("Sides described", "Sides with at least one kept point."),
        "quotes_bad_first": ("Bad quotes, first answer", "Quotes not found word for word before the retry."),
        "points_dropped": ("Points dropped", "Points left with no good quote after the retry."),
        "stories_failed": ("Failed stories", "No step 2 output, or no usable answer. Must be 0."),
    }

    def __init__(self, n=None, stories_dir=None, sheets=None, merge=None, merge_version=None, runs_dir=None, prompt=None):
        super().__init__(n=n, stories_dir=stories_dir, sheets=sheets, merge=merge, merge_version=merge_version,
                         runs_dir=runs_dir)
        self.prompt = prompt or brief_framing.VERSION
        if self.prompt not in brief_framing.PROMPTS:
            raise ValueError(f"unknown prompt {self.prompt}; known: {', '.join(brief_framing.PROMPTS)}")
        self.version = f"{self.prompt}-{brief_sides.VERSION}-{self.merge_version}-n{self.n}"

    def _inputs(self, item: Item):
        sides = BriefSidesEval.run(self, item, None)
        if sides.get("error"):
            return sides, None, None, None
        step1 = self.step1(sides["step1_run"]).get(item.story) if sides.get("step1_run") else None
        event, _, arts, _ = self._story(item)
        return sides, step1, arts, event

    def run(self, item: Item, ctx):
        sides, step1, arts, event = self._inputs(item)
        if sides.get("error"):
            return sides
        complete = lambda msgs, name=None, **p: ctx.complete(msgs, name=name, **p)
        return brief_framing.frame_story(sides, step1, arts, event, complete, model=ctx.model, prompt=self.prompt)

    def plan(self, item: Item, model: str) -> list[dict]:
        sides, step1, arts, event = self._inputs(item)
        if sides.get("error") or (sides.get("sides") or {}).get("kind") != "two sides":
            return []
        calls = []

        def fake(msgs, name=None, **p):
            calls.append(dict(messages=msgs, params=dict(max_tokens=p.get("max_tokens")), expect_output=1000))
            raise RuntimeError("estimate only")
        brief_framing.frame_story(sides, step1, arts, event, fake, model=model, prompt=self.prompt)
        return calls[:1]

    def score(self, item: Item, output, key: dict) -> dict:
        f = output.get("framing") or {}
        pts = [p for s in f.get("sides") or [] for p in s["points"]]
        two = f.get("kind") == "two sides"
        return dict(two_sides=two, sides=len(f.get("sides") or []),
                    described=sum(bool(s["points"]) for s in f.get("sides") or []), points=len(pts),
                    pattern=sum(p["outlets"] >= 2 for p in pts), quotes_bad_first=f.get("quotes_bad_first", 0),
                    points_dropped=f.get("points_dropped", 0), quotes_dropped=f.get("quotes_dropped", 0),
                    skipped=[x.get("reason") for x in f.get("skipped") or []],
                    failed=bool(output.get("error")) or bool(f.get("error")))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        sides, pts = tot("sides"), tot("points")
        return dict(points_per_side=round(pts / sides, 2) if sides else None,
                    pattern_share=round(tot("pattern") / pts, 3) if pts else None,
                    sides_described=tot("described"), sides_asked=sides, points=pts,
                    quotes_bad_first=tot("quotes_bad_first"), points_dropped=tot("points_dropped"),
                    quotes_dropped=tot("quotes_dropped"), stories_failed=tot("failed"),
                    two_side_stories=sum(bool(s.get("two_sides")) for s in scores),
                    empty_sides_skipped=sum(x == "empty side" for s in scores for x in s.get("skipped") or []),
                    stories={i.story: s.get("points") for i, s in zip(items, scores)})

    def mistakes(self, rec: dict) -> list[dict]:
        """Every kept point, for the hand check."""
        out = []
        for r in rec.get("items_detail") or []:
            f = (r.get("output") or {}).get("framing") or {}
            for s in f.get("sides") or []:
                for p in s["points"]:
                    q = "; ".join(f"{x['outlet']}: “{x['words']}”" + (f" ({x['words_en']})" if x["words_en"] else "")
                                  for x in p["quotes"])
                    out.append(dict(story=r["story"], kind=p["kind"], title=p["point"], url=None, gold=s["label"],
                                    pred=q, reason=f"{p['outlets']} outlet(s)", source=""))
        return out
