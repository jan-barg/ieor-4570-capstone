"""The eval for module 5's baseline (one call writes the whole Story File), plugged into the runner.

Same stories, answer sheets, pick (10 articles), holdout and judge as step 1's eval, with the same
judge prompt, so coverage compares straight across: step 1's coverage is the most the four-step
build can reach (merging can only lose facts), and this is what one call reaches.

Scores:
  coverage           share of must-have facts that at least one kept claim states (judge)
  coverage_all       the same, counting claims later dropped for bad quotes too
  quote_ok           share of claim sources whose quote is in the article word for word
                     (one try: there is no quote retry in the baseline)
  claims             claims kept per story
  claims_dropped     claims left with no checked quote, dropped
  persp_ok           share of the words quoted in how each side tells it that are in the article
                     cited, which is on that side
  stories_failed     stories with no usable answer after one retry (must stay 0)
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import brief_onecall, pick
from .brief_read_eval import BriefReadEval, judge_messages, with_judge
from .runner import Item


class BriefOneCallEval(BriefReadEval):
    name = "brief_onecall"
    model_step = "brief_onecall"
    headline = ("coverage", "coverage_all", "quote_ok", "claims_per_story", "claims_dropped", "persp_ok",
                "stories_failed", "must_have")
    report_title = "News brief: the one-call baseline"
    report_intro = ("The baseline the four-step news brief has to beat: one call reads the 10 picked articles and "
                    "writes the whole Story File (claims with exact quotes, and how each side tells it). Scored on "
                    "Jan's 26 answer sheets with step 1's judge and judge prompt, so coverage compares straight across.")
    metric_notes = {
        "coverage": ("Coverage", "The main score: share of must-have facts that at least one kept claim states."),
        "coverage_all": ("Coverage before drops", "The same, counting claims dropped for bad quotes too."),
        "quote_ok": ("Quotes exact", "Share of claim quotes found in their article word for word (one try, no retry)."),
        "claims_per_story": ("Claims per story", "Claims kept per story."),
        "claims_dropped": ("Claims dropped", "Claims left with no checked quote."),
        "persp_ok": ("Side quotes exact", "Share of words quoted in how each side tells it that are in the cited article, on that side."),
        "stories_failed": ("Failed stories", "Stories with no usable answer after one retry. Must be 0."),
        "must_have": ("Must-have facts", "Must-have facts in the stories run."),
    }

    def __init__(self, n=None, judge=None, stories_dir=None, sheets=None, judge_prompt=None, from_run=None):
        super().__init__(n=n, judge=judge, stories_dir=stories_dir, sheets=sheets, judge_prompt=judge_prompt,
                         from_run=from_run)
        self.version = with_judge(f"{brief_onecall.VERSION}-n{self.n}", self.judge_prompt)

    def _story(self, item: Item):
        d = Path(item.data["dir"])
        meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
        arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
        n = 100_000 if self.n == "all" else int(self.n)
        p = pick.pick(arts, meta["lens"], n=n)
        groups = {r["id"]: r["group"] for r in p["rows"]}
        by = {a["id"]: a for a in arts}
        return meta["event"], meta["lens"], [by[i] for i in p["picked"]], groups

    def run(self, item: Item, ctx):
        if self.from_run:
            return self.rejudge(item, ctx)
        event, lens, arts, groups = self._story(item)
        complete = lambda msgs, name=None, **p: ctx.complete(msgs, name=name, **p)
        out = brief_onecall.write_story(event, arts, lens, groups, complete, model=ctx.model)
        must = item.data["sheet"]["facts"]
        cards = self.judge_cards(out)
        out["judge"] = self._judge(must, cards, ctx) if must and cards else {"model": self.judge, "results": {}}
        return out

    def judge_cards(self, out: dict) -> list[dict]:
        """What the coverage judge reads: kept and dropped claims (coverage_all counts both)."""
        return [dict(id=c.get("id") or f"X{i}", fact=c["claim"],
                     quote=(c["sources"] or c["bad_sources"] or [{}])[0].get("quote", ""),
                     quote_en=(c["sources"] or c["bad_sources"] or [{}])[0].get("quote_en", ""))
                for i, c in enumerate(out["claims"] + out["dropped"], 1)]

    def plan(self, item: Item, model: str) -> list[dict]:
        if self.from_run:
            return self.judge_plan(item)
        event, lens, arts, groups = self._story(item)
        rows = brief_onecall.prepare(arts, groups)
        if not rows:
            return []
        return [{"messages": brief_onecall.messages_for(event, lens, rows), "params": brief_onecall.params_for(model),
                 "expect_output": 9000}]

    def score(self, item: Item, output, key: dict) -> dict:
        must = key.get(item.story) or []
        res = (output.get("judge") or {}).get("results") or {}
        kept = {c["id"] for c in output.get("claims") or []}
        found_any = [bool((res.get(f"M{i}") or {}).get("found")) for i in range(1, len(must) + 1)]
        found = [ok and any(c in kept for c in (res.get(f"M{i}") or {}).get("cards") or [])
                 for i, ok in enumerate(found_any, 1)]
        ch = output.get("checks") or {}
        return dict(must_have=len(must), found=sum(found), found_each=found, found_all=sum(found_any),
                    coverage=round(sum(found) / len(must), 3) if must else None,
                    claims=len(output.get("claims") or []), claims_first=ch.get("claims_first", 0),
                    claims_dropped=ch.get("claims_dropped", 0), sources_first=ch.get("sources_first", 0),
                    sources_bad=ch.get("sources_bad", 0), unknown_articles=ch.get("unknown_articles", 0),
                    persp_quotes=ch.get("persp_quotes", 0),
                    persp_bad=ch.get("persp_bad", 0) + ch.get("persp_wrong_side", 0), points=ch.get("points", 0),
                    failed=bool(ch.get("error")), retried_json=bool(ch.get("retried_json")),
                    articles=len(output.get("articles") or []),
                    judge_error=(output.get("judge") or {}).get("error"))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        must, src, pq, n = tot("must_have"), tot("sources_first"), tot("persp_quotes"), len(scores)
        return dict(coverage=round(tot("found") / must, 3) if must else None,
                    coverage_all=round(tot("found_all") / must, 3) if must else None,
                    must_have=must, found=tot("found"),
                    quote_ok=round(1 - tot("sources_bad") / src, 3) if src else None,
                    claims_per_story=round(tot("claims") / n, 1) if n else None, claims_dropped=tot("claims_dropped"),
                    persp_ok=round(1 - tot("persp_bad") / pq, 3) if pq else None, points=tot("points"),
                    stories_failed=tot("failed"), json_retries=tot("retried_json"),
                    unknown_articles=tot("unknown_articles"), articles=tot("articles"),
                    judge_errors=sum(bool(s.get("judge_error")) for s in scores),
                    stories={i.story: s.get("coverage") for i, s in zip(items, scores)})
