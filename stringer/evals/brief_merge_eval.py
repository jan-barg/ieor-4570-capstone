"""The eval for module 5, step 2 (merging fact cards into claims), plugged into the runner.

Option prompt=merge-2 runs an earlier prompt, for before-and-after comparisons; option
judge_prompt=cov-2 the coverage judge with worked examples (see brief_read_eval).

Input: step 1's saved output, not a fresh step 1 run, so step 2's scores move only when step 2
changes. By default the latest step 1 run with the decided step 1 model (config `brief_read`),
the current step 1 version and the same article cap; option facts=<run file> picks another.

Same answer sheets, holdout and judge prompt as step 1 and the one-call baseline, so coverage
compares straight across: step 1's coverage is the most the merge can keep.

Scores:
  coverage           share of must-have facts that at least one claim states (judge)
  lost               must-have facts step 1's cards had that the claims don't
  cards_unused       step 1 cards left out of every claim (share of all cards)
  claims_per_story   claims kept per story
  multi_article      share of claims backed by 2 or more articles (merging across articles)
  conflicts          claims marked as conflicting with another
  stories_failed     stories with no usable answer after one retry (must stay 0)
Merge quality (a second judge call per story, same judge model; option quality=0 turns it off):
  bad_claims         claims holding a card that doesn't state the claim, or two accounts in one
  lost_cards         left-out cards about the event whose fact no claim states
  false_conflicts    marked conflict pairs that aren't real disagreements
  missed_conflicts   clear disagreements between claims that aren't marked
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import brief_merge, brief_read, models, paths
from .brief_read_eval import JUDGE_MAX_TOKENS, BriefReadEval, with_judge
from .runner import Item

QUALITY_SCHEMA = {"type": "json_schema", "json_schema": {"name": "merge_quality", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["bad_claims", "lost_cards", "false_conflicts", "missed_conflicts"],
    "properties": {
        "bad_claims": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["claim", "cards", "why"],
            "properties": {"claim": {"type": "string"}, "cards": {"type": "array", "items": {"type": "string"}},
                           "why": {"type": "string"}}}},
        "lost_cards": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["card", "why"],
            "properties": {"card": {"type": "string"}, "why": {"type": "string"}}}},
        "false_conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["a", "b", "why"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "why": {"type": "string"}}}},
        "missed_conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["a", "b", "why"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "why": {"type": "string"}}}}}}}}

QUALITY_SYSTEM = """You check how fact cards from news articles were merged into claims. Each claim lists the cards behind it; some cards went into no claim.

Report only problems, in four lists:
1. bad_claims: claims with a card that doesn't state the claim's fact (a different number, date, place, actor, or a different fact altogether; extra detail on a card is fine), or a claim that puts two different accounts into one sentence ("some said X, while Y said Z"). Give the claim id, the misfit card ids (empty for two accounts in one), and why.
2. lost_cards: cards that went into no claim, are about this event, and state a fact that no claim states. Give the card id and why. Skip cards whose fact a claim already states, and cards not about the event (other news, site text).
3. false_conflicts: pairs marked as conflicting that don't disagree (they are about different things, or say the same). Give both claim ids and why.
4. missed_conflicts: pairs of claims not marked as conflicting that clearly give different accounts of the same thing (a different number for the same count, a different date for the same moment, damage called severe and minor, an attack blamed on different actors). Two separate events on different days are not a conflict. Only clear cases.

Use the ids exactly as given. Answer with JSON only."""


def quality_messages(event: dict, claims: list[dict], cards: list[dict], unused_ids: set) -> tuple[list[dict], dict]:
    """The quality judge's input, with cards under short ids (K1, K2, ...). Returns (messages, {short: card id})."""
    short = {c["id"]: f"K{i}" for i, c in enumerate(cards, 1)}
    text = {c["id"]: c for c in cards}

    def line(cid):
        c = text[cid]
        q = (c.get("quote_en") or c.get("quote") or "")[:160]
        return f"  {short[cid]}: {c['fact']}  (words: \"{q}\")"
    out = []
    for cl in claims:
        conf = f"  [conflicts with: {', '.join(cl['conflicts_with'])}]" if cl.get("conflicts_with") else ""
        out.append(f"{cl['id']} [{cl['kind']}; who: {cl['who_says']}] {cl['claim']}{conf}")
        out += [line(f) for f in cl["facts"] if f in text]
    left = [line(c["id"]) for c in cards if c["id"] in unused_ids]
    body = (f"Event: {event.get('title', '')}\n{event.get('summary', '')}\n\nClaims and their cards:\n" + "\n".join(out)
            + "\n\nCards in no claim:\n" + ("\n".join(left) or "  (none)"))
    return [{"role": "system", "content": QUALITY_SYSTEM}, {"role": "user", "content": body}], {v: k for k, v in short.items()}


def step1_run(n: str, model: str | None = None, runs_dir=None) -> Path:
    """The latest saved step 1 run for this model, version and cap."""
    model = model or models.model_for("brief_read")
    d = Path(runs_dir or paths.EVALS / "runs" / "brief_read")
    found = sorted(d.glob(f"brief_read-*-{model}-{brief_read.VERSION}-n{n}.json"))
    if not found:
        raise FileNotFoundError(f"no step 1 run for {model}, {brief_read.VERSION}, n={n} in {d}")
    return found[-1]


class BriefMergeEval(BriefReadEval):
    name = "brief_merge"
    model_step = "brief_merge"
    headline = ("coverage", "lost", "lost_cards", "bad_claims", "missed_conflicts", "false_conflicts",
                "cards_unused", "claims_per_story", "conflicts", "claims_joined", "stories_failed", "must_have")
    report_title = "News brief, step 2: merging fact cards into claims"
    report_intro = ("Step 2 gets a story's fact cards from step 1 (no article text, no outlet names, no sides) and "
                    "merges them into claims, each listing the cards behind it. Scored on Jan's 26 answer sheets with "
                    "step 1's judge and judge prompt: how many must-have facts the claims still state, and how many "
                    "step 1 had that the merge lost. A second judge call checks the merge itself: misfit cards, "
                    "cards lost, and conflicts marked wrongly or missed.")
    metric_notes = {
        "coverage": ("Coverage", "The main score: share of must-have facts that at least one claim states."),
        "lost": ("Lost in the merge", "Must-have facts step 1's cards had that no claim states."),
        "lost_cards": ("Cards lost", "Cards about the event, left out of every claim, whose fact no claim states (judge)."),
        "bad_claims": ("Bad claims", "Claims with a card that doesn't state them, or two accounts in one sentence (judge)."),
        "missed_conflicts": ("Conflicts missed", "Clear disagreements between claims that aren't marked (judge)."),
        "false_conflicts": ("False conflicts", "Marked conflicts that aren't real disagreements (judge)."),
        "cards_unused": ("Cards left out", "Share of step 1's cards that went into no claim (code)."),
        "claims_per_story": ("Claims per story", "Claims kept per story."),
        "conflicts": ("Conflicting claims", "Claims marked as contradicting another claim."),
        "claims_joined": ("Claims joined", "merge-12 and later: claims folded into another claim stating the same fact."),
        "stories_failed": ("Failed stories", "Stories with no usable answer after one retry. Must be 0."),
        "must_have": ("Must-have facts", "Must-have facts in the stories run."),
    }

    def __init__(self, n=None, judge=None, stories_dir=None, sheets=None, facts=None, quality="1", prompt=None,
                 judge_prompt=None, from_run=None):
        super().__init__(n=n, judge=judge, stories_dir=stories_dir, sheets=sheets, judge_prompt=judge_prompt,
                         from_run=from_run)
        self.facts_path = Path(facts) if facts else None
        self.quality = str(quality) != "0"
        self._step1 = None
        self.prompt = prompt or brief_merge.VERSION
        if self.prompt not in brief_merge.PROMPTS:
            raise KeyError(f"no prompt {self.prompt}; known: {', '.join(brief_merge.PROMPTS)}")
        self.version = with_judge(f"{self.prompt}-n{self.n}", self.judge_prompt)

    def step1(self) -> dict:
        """{story: {"output", "found_each"}} from the saved step 1 run, plus the run id."""
        if self._step1 is None:
            p = self.facts_path or step1_run(self.n)
            d = json.loads(p.read_text(encoding="utf-8"))
            self._step1 = dict(run_id=d.get("run_id"), stories={
                r["story"]: dict(output=r["output"], found_each=(r.get("scores") or {}).get("found_each") or [])
                for r in d.get("items_detail") or [] if r.get("output")})
        return self._step1

    def load(self, only=None, split="tune") -> list[Item]:
        have = self.step1()["stories"]
        return [i for i in super().load(only=only, split=split) if i.story in have]

    def _event(self, item: Item) -> dict:
        return json.loads((Path(item.data["dir"]) / "gather.json").read_text(encoding="utf-8"))["event"]

    def _times(self, item: Item) -> dict:
        """Article id -> published time, for the conflict pass."""
        f = Path(item.data["dir"]) / "articles.jsonl"
        if not f.exists():
            return {}
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").split("\n") if x.strip()]
        return {a["id"]: a["published_at"] if a.get("date_precision", "time") == "time" else a["published_at"][:10]
                for a in rows if a.get("id") and a.get("published_at")}

    def judge_cards(self, out: dict) -> list[dict]:
        """What the coverage judge reads: step 2's claims, each with its first source's quote."""
        return [dict(id=c["id"], fact=c["claim"], quote=(c["sources"] or [{}])[0].get("quote", ""),
                     quote_en=(c["sources"] or [{}])[0].get("quote_en", "")) for c in out["claims"]]

    def run(self, item: Item, ctx):
        if self.from_run:
            return self.rejudge(item, ctx)             # the merge quality verdicts stay as saved
        s1 = self.step1()
        event = self._event(item)
        step1 = s1["stories"][item.story]["output"]
        complete = lambda msgs, name=None, **p: ctx.complete(msgs, name=name, **p)
        out = brief_merge.merge_story(event, step1, complete, model=ctx.model, prompt=self.prompt,
                                      times=self._times(item))
        out["step1_run"] = s1["run_id"]
        must = item.data["sheet"]["facts"]
        cards = self.judge_cards(out)
        out["judge"] = self._judge(must, cards, ctx) if must and cards else {"model": self.judge, "results": {}}
        if self.quality and out["claims"]:
            out["quality"] = self._quality(event, out, brief_merge.cards_of(step1), ctx)
        return out

    def _quality(self, event, out, cards, ctx) -> dict:
        msgs, ids = quality_messages(event, out["claims"], cards, {u["id"] for u in out["unused"]})
        res = None
        for attempt in range(2):
            try:
                r = ctx.complete(msgs if attempt == 0 else msgs + [{"role": "user", "content": brief_read.RETRY_JSON}],
                                 name=f"{self.name} quality judge", model=self.judge, max_tokens=JUDGE_MAX_TOKENS * 2,
                                 response_format=QUALITY_SCHEMA, timeout=brief_read.CALL_TIMEOUT_S)
                res = json.loads(r.text.strip().removeprefix("```json").removesuffix("```"))
                if all(isinstance(res.get(k), list) for k in ("bad_claims", "lost_cards", "false_conflicts",
                                                                "missed_conflicts")):
                    break
                res = None
            except Exception as e:                     # unusable or failed: one more try, then report
                if type(e).__name__ == "BudgetExceeded":
                    raise
                res = None
        if res is None:
            return {"model": self.judge, "error": "no usable quality judge answer"}
        claim_ids = {c["id"] for c in out["claims"]}
        pair = lambda x: isinstance(x, dict) and x.get("a") in claim_ids and x.get("b") in claim_ids and x["a"] != x["b"]
        return {"model": self.judge,
                "bad_claims": [dict(claim=x["claim"], cards=[ids.get(k, k) for k in x.get("cards") or []], why=x.get("why", ""))
                               for x in res["bad_claims"] if isinstance(x, dict) and x.get("claim") in claim_ids],
                "lost_cards": [dict(card=ids[x["card"]], why=x.get("why", "")) for x in res["lost_cards"]
                               if isinstance(x, dict) and x.get("card") in ids],
                "false_conflicts": [dict(a=x["a"], b=x["b"], why=x.get("why", "")) for x in res["false_conflicts"] if pair(x)],
                "missed_conflicts": [dict(a=x["a"], b=x["b"], why=x.get("why", "")) for x in res["missed_conflicts"] if pair(x)]}

    def plan(self, item: Item, model: str) -> list[dict]:
        if self.from_run:
            return self.judge_plan(item)
        cards = brief_merge.cards_of(self.step1()["stories"][item.story]["output"])
        if not cards:
            return []
        return [{"messages": brief_merge.messages_for(self._event(item), cards, self.prompt),
                 "params": brief_merge.params_for(model), "expect_output": 5000}]

    def score(self, item: Item, output, key: dict) -> dict:
        must = key.get(item.story) or []
        res = (output.get("judge") or {}).get("results") or {}
        found = [bool((res.get(f"M{i}") or {}).get("found")) for i in range(1, len(must) + 1)]
        before = (self.step1()["stories"].get(item.story) or {}).get("found_each") or []
        lost = [i for i, (b, f) in enumerate(zip(before, found)) if b and not f]
        ch = output.get("checks") or {}
        kept = output.get("claims") or []
        q = output.get("quality") or {}
        has_q = bool(q) and not q.get("error")
        pairs = lambda k: len({tuple(sorted((x["a"], x["b"]))) for x in q.get(k) or []})
        marked = len({tuple(sorted((c["id"], x))) for c in kept for x in c.get("conflicts_with") or []})
        return dict(must_have=len(must), found=sum(found), found_each=found, step1_found=sum(before),
                    lost=len(lost), lost_each=lost,
                    coverage=round(sum(found) / len(must), 3) if must else None,
                    claims=len(kept), claims_dropped=ch.get("claims_dropped", 0),
                    cards=ch.get("cards", 0), cards_unused=ch.get("cards_unused", 0),
                    unknown_cards=ch.get("unknown_cards", 0), multi_article=ch.get("multi_article", 0),
                    conflicts=ch.get("conflicts", 0), conflict_pairs=marked, failed=bool(ch.get("error")),
                    retried_json=bool(ch.get("retried_json")), judge_error=(output.get("judge") or {}).get("error"),
                    quality_checked=has_q,
                    bad_claims=len({x["claim"] for x in q.get("bad_claims") or []}) if has_q else None,
                    lost_cards=len({x["card"] for x in q.get("lost_cards") or []}) if has_q else None,
                    false_conflicts=pairs("false_conflicts") if has_q else None,
                    missed_conflicts=pairs("missed_conflicts") if has_q else None,
                    quality_error=q.get("error"), claims_joined=ch.get("claims_joined", 0),
                    join_groups=ch.get("join_groups", 0), join_rejected=ch.get("join_rejected", 0),
                    join_error=ch.get("join_error"), join_proposed=ch.get("join_proposed", 0),
                    join_numbers_refused=ch.get("join_numbers_refused", 0), join_check_same=ch.get("join_check_same", 0),
                    own_marks=ch.get("own_marks", 0), own_marks_kept=ch.get("own_marks_kept", 0),
                    own_marks_updates=ch.get("own_marks_updates", 0), own_check_error=ch.get("own_check_error"))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        must, cards, claims, n = tot("must_have"), tot("cards"), tot("claims"), len(scores)
        checked = [s for s in scores if s.get("quality_checked")]
        qtot = lambda k: sum(s.get(k) or 0 for s in checked) if checked else None
        return dict(coverage=round(tot("found") / must, 3) if must else None, must_have=must, found=tot("found"),
                    step1_coverage=round(tot("step1_found") / must, 3) if must else None, lost=tot("lost"),
                    lost_cards=qtot("lost_cards"), bad_claims=qtot("bad_claims"),
                    missed_conflicts=qtot("missed_conflicts"), false_conflicts=qtot("false_conflicts"),
                    conflict_pairs=tot("conflict_pairs"), quality_checked=len(checked),
                    quality_errors=sum(bool(s.get("quality_error")) for s in scores),
                    cards_unused=round(tot("cards_unused") / cards, 3) if cards else None,
                    claims_per_story=round(claims / n, 1) if n else None,
                    multi_article=round(tot("multi_article") / claims, 3) if claims else None,
                    conflicts=tot("conflicts"), claims_dropped=tot("claims_dropped"),
                    unknown_cards=tot("unknown_cards"), stories_failed=tot("failed"),
                    claims_joined=tot("claims_joined"), join_groups=tot("join_groups"), join_rejected=tot("join_rejected"),
                    join_errors=sum(bool(s.get("join_error")) for s in scores), join_proposed=tot("join_proposed"),
                    join_numbers_refused=tot("join_numbers_refused"), join_check_same=tot("join_check_same"),
                    own_marks=tot("own_marks"), own_marks_kept=tot("own_marks_kept"), own_marks_updates=tot("own_marks_updates"),
                    own_check_errors=sum(bool(s.get("own_check_error")) for s in scores),
                    json_retries=tot("retried_json"), judge_errors=sum(bool(s.get("judge_error")) for s in scores),
                    step1_run=self.step1()["run_id"],
                    stories={i.story: s.get("coverage") for i, s in zip(items, scores)})
