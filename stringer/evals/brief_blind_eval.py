"""The eval for module 5, step 3b: a judge checks step 3's blindspot candidates against the silent
side's own article text (brief_blind.py).

    python -m scripts.run_eval run brief_blind --split all --cap 0.15
    (--opt prompt=blind-5 runs the tried, unused prompt; blind-1 to blind-3 differ only in code that is gone)

Input: the same as step 3 (the latest run of the current step 2 version per story, its step 1 run and the pick of 10
articles); step 3 runs first, in code, then one call per silent side with candidates.

There is no answer key yet: the counts say what the judge decided, and the report lists every
checked claim with the quote it found, for a hand check.

Scores (all stories):
  blindspots_per_story  confirmed blindspots per story with candidates checked
  central_per_story     the same, only facts the judge calls central
  reported_share        checked claims the silent side does report (quote checked)
  told_differently      checked claims the silent side tells another way (quote checked)
  unclear               checked claims whose quote failed twice, or that turned "missing" on the retry
  unchecked             checked claims with no usable answer (must stay 0)
  quotes_bad_first      quotes not found word for word on the first answer
  stories_failed        stories with no step 2 output, or a side whose call failed (must stay 0)
"""
from __future__ import annotations

from .. import brief_blind, brief_sides
from .brief_sides_eval import BriefSidesEval
from .runner import Item


class BriefBlindEval(BriefSidesEval):
    name = "brief_blind"
    model_step = "brief_blind"
    headline = ("blindspots_per_story", "central_per_story", "reported_share", "told_differently", "unclear",
                "unchecked", "quotes_bad_first", "stories_failed")
    report_title = "News brief, step 3b: blindspot judge"
    report_intro = ("Step 3 (code) lists claims one side reports and the other side doesn't. For candidates with 2 or more "
                    "independent sources, one call per silent side reads that side's full articles and says whether each "
                    "fact is there (it must copy the sentence, and code checks it word for word), told another way, or "
                    "missing, and whether it is central. Only 'missing' on the first answer counts as a blindspot. No "
                    "answer key yet: the list below is for a hand check.")
    metric_notes = {
        "blindspots_per_story": ("Blindspots per story", "Confirmed blindspots per story with candidates checked."),
        "central_per_story": ("Central ones per story", "Confirmed blindspots the judge calls central."),
        "reported_share": ("Reported after all", "Share of checked claims the silent side does report (quote checked)."),
        "told_differently": ("Told differently", "Checked claims the silent side tells another way (quote checked)."),
        "unclear": ("Unclear", "Quote failed twice, or turned 'missing' on the retry. Not passed on."),
        "unchecked": ("Unchecked", "Checked claims with no usable answer. Must be 0."),
        "quotes_bad_first": ("Bad quotes, first answer", "Quotes not found word for word before the retry."),
        "stories_failed": ("Failed stories", "No step 2 output, or a side's call failed. Must be 0."),
    }

    def __init__(self, n=None, stories_dir=None, sheets=None, merge=None, merge_version=None, runs_dir=None, prompt=None):
        super().__init__(n=n, stories_dir=stories_dir, sheets=sheets, merge=merge, merge_version=merge_version,
                         runs_dir=runs_dir)
        self.prompt = prompt or brief_blind.VERSION
        if self.prompt not in brief_blind.PROMPTS:
            raise ValueError(f"unknown prompt {self.prompt}; known: {', '.join(brief_blind.PROMPTS)}")
        self.version = f"{self.prompt}-{brief_sides.VERSION}-{self.merge_version}-n{self.n}"

    def run(self, item: Item, ctx):
        sides = super().run(item, ctx)
        if sides.get("error"):
            return sides
        event, _, arts, _ = self._story(item)
        complete = lambda msgs, name=None, **p: ctx.complete(msgs, name=name, **p)
        return brief_blind.judge_blindspots(sides, arts, event, complete, model=ctx.model, prompt=self.prompt)

    def plan(self, item: Item, model: str) -> list[dict]:
        sides = BriefSidesEval.run(self, item, None)
        if sides.get("error"):
            return []
        event, _, arts, _ = self._story(item)
        claims = {c["id"]: c for c in sides["claims"]}
        outlets = {s["id"]: s.get("outlet_name") or s["id"] for s in sides["sources"]}
        out = []
        for cand in brief_blind.candidates(sides):
            a = brief_blind.silent_articles(sides, arts, cand["silent_side"])
            msgs, _ = brief_blind.messages_for(event, [claims[i] for i in cand["claims"]], a, cand["label"], outlets, self.prompt)
            out.append(dict(messages=msgs, params=dict(max_tokens=brief_blind.MAX_TOKENS[self.prompt]),
                            expect_output=180 * len(cand["claims"])))
        return out

    def score(self, item: Item, output, key: dict) -> dict:
        c = output.get("blind_counts") or {}
        return dict(checked=c.get("checked", 0), blindspot=c.get("blindspot", 0), central=c.get("central", 0),
                    reported=c.get("reported", 0), told_differently=c.get("told_differently", 0),
                    unclear=c.get("unclear", 0), unchecked=c.get("unchecked", 0),
                    quotes_bad_first=c.get("quotes_bad_first", 0), cut=c.get("cut", 0),
                    failed=bool(output.get("error")) or bool(c.get("errors")))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        with_c = sum(1 for s in scores if s.get("checked"))
        checked = tot("checked")
        return dict(blindspots_per_story=round(tot("blindspot") / with_c, 2) if with_c else None,
                    central_per_story=round(tot("central") / with_c, 2) if with_c else None,
                    reported_share=round(tot("reported") / checked, 3) if checked else None,
                    told_differently=tot("told_differently"), unclear=tot("unclear"), unchecked=tot("unchecked"),
                    quotes_bad_first=tot("quotes_bad_first"), stories_failed=tot("failed"),
                    checked=checked, blindspots=tot("blindspot"), central=tot("central"), reported=tot("reported"),
                    cut=tot("cut"), stories_checked=with_c,
                    stories={i.story: s.get("blindspot") for i, s in zip(items, scores)})

    def mistakes(self, rec: dict) -> list[dict]:
        """Every checked claim, for the hand check (there is no answer key, so nothing is 'wrong' yet)."""
        out = []
        for r in rec.get("items_detail") or []:
            o = r.get("output") or {}
            claims = {c["id"]: c for c in o.get("claims") or []}
            src = {s["id"]: s for s in o.get("sources") or []}
            for j in o.get("blindspot_checks") or []:
                for x in j["checked"]:
                    s = src.get(x.get("article")) or {}
                    out.append(dict(story=r["story"], kind=x["status"], title=(claims.get(x["claim"]) or {}).get("claim", ""),
                                    url=s.get("url"), gold=f"silent: {j['label']}", pred=x.get("quote_en") or x.get("quote") or "",
                                    reason=f"{x.get('matters', '')}; {x.get('why', '')}", source=s.get("outlet_name") or ""))
        return out
