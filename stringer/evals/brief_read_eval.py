"""The eval for module 5, step 1 (reading each article into fact cards), plugged into the runner.

Inputs: the frozen stories that have a hand-checked answer sheet (26). Each story runs step 1 on
the articles the pick chooses (10 by default; option n=20 or n=all compares caps, decided Nov 24).

Answer key: stringer_private/fixtures/answer_sheets_v2.json, checked by Jan (84 must-have facts).

Scores:
  coverage           share of must-have facts that at least one fact card states (a judge model
                     decides, from a different family than the models tested; the judge's own
                     calls count in the run's cost)
  quote_ok_first     share of fact cards whose quote was in the article word for word on the
                     first answer (code)
  facts_dropped      cards dropped because their quote still failed after the one retry
  facts_per_article  cards kept per article
  articles_failed    articles with no usable answer after one retry (must stay 0)
  json_retries       articles that needed the retry for unusable JSON

Option judge_prompt=cov-2 runs the coverage judge with worked examples and the every-part rule
(built Nov 25 after a hand check of 84 verdicts); runs with it carry "-cov-2" in their version.
Option from_run=<run file> asks only the judge again, on that run's saved outputs (no step calls;
the steps 2 and baseline evals take it too). Each output then names the run in "rejudged_from".
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .. import brief_read, paths, pick
from .runner import Item, Step

SHEETS = paths.FIXTURES / "answer_sheets_v2.json"
HOLDOUT = {5, 10, 15, 20, 25}            # answer sheets kept out of prompt changes
JUDGE = "gemini-3.5-flash-lite"           # Google: not one of the families tested for step 1
JUDGE_MAX_TOKENS = 4000

JUDGE_SCHEMA = {"type": "json_schema", "json_schema": {"name": "coverage", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "found", "cards"],
        "properties": {"id": {"type": "string"}, "found": {"type": "boolean"},
                       "cards": {"type": "array", "items": {"type": "string"}}}}}}}}}

JUDGE_SYSTEM = """You check whether fact cards taken from news articles contain each of a story's must-have facts.

A must-have fact counts as found when at least one card states the same core fact: the same who and what, and the same number if the fact has one. Wording may differ, and extra detail is fine. A card that only hints at the fact, states something related, or gives a different number does not count.

For every must-have fact, answer with its id, whether it is found, and the ids of the cards that state it (empty if not found). Answer with JSON only."""

# cov-2 (Nov 25): cov-1 plus the every-part rule and worked examples. The examples are made up
# (no real story), one for each kind of mistake the hand check found: a same-fact rewording
# missed, half-there facts passed, and a step 1 card passed that hints at a toll without giving it.
JUDGE_SYSTEM_2 = """You check whether fact cards taken from news articles contain each of a story's must-have facts.

A must-have fact counts as found when the cards state the same core fact: the same who and what, and the same number if the fact has one. Wording may differ, and extra detail is fine. A card that only hints at the fact, states something related, or gives a different number does not count.

If the fact has several parts (a list of things, or two statements joined by "and" or a semicolon), it counts as found only when the cards, taken together, state every part. Words in brackets are background, not a part to find.

Examples (made up, not from this story):
- Must-have: "No drones were shot down." Card: "Air defenses did not intercept any of the drones." Found: the same fact in other words.
- Must-have: "Four people were hurt." Card: "In the port district, one person died and four were injured." Found: the same count; the death is extra detail.
- Must-have: "The governor says up to 40 people may have died." Card: "The governor called the fire a tragedy." Not found: the right person, but no death toll.
- Must-have: "About 12 rockets were fired." Card: "The army fired rockets of two types." Not found: no number. A card saying "9 rockets were fired" is not found either: a different number.
- Must-have: "Strikes hit Lorne, Varsel and Tormac." Cards name Lorne and Varsel only. Not found: one part is missing.
- Must-have: "Rebel leaders say the dam was blown up; repairs could take a year." Card: "Rebel leaders say the dam was blown up." Not found: the second part is missing.
- Must-have: "Government officials say the dam was blown up." Card: "Rebel leaders say the dam was blown up." Not found: a different who.

For every must-have fact, answer with its id, whether it is found, and the ids of the cards that state it (empty if not found). Answer with JSON only."""

JUDGE_PROMPTS = {"cov-1": JUDGE_SYSTEM, "cov-2": JUDGE_SYSTEM_2}
JUDGE_PROMPT = "cov-1"                     # the default; runs with another prompt carry its name in their version


def judge_prompt_of(name: str | None) -> str:
    name = name or JUDGE_PROMPT
    if name not in JUDGE_PROMPTS:
        raise KeyError(f"no coverage judge prompt {name}; known: {', '.join(JUDGE_PROMPTS)}")
    return name


def with_judge(version: str, judge_prompt: str) -> str:
    """The step version, plus the judge prompt's name when it isn't cov-1 (older runs have none)."""
    return version if judge_prompt == "cov-1" else f"{version}-{judge_prompt}"


def judge_messages(must_have: list[str], facts: list[dict], prompt: str = JUDGE_PROMPT) -> tuple[list[dict], dict]:
    ids = {}
    lines = []
    for i, f in enumerate(facts, 1):
        ids[f"F{i}"] = f["id"]
        q = (f.get("quote_en") or f.get("quote") or "")[:200]
        lines.append(f"F{i}: {f['fact']}  [quote: {q}]")
    body = ("Must-have facts:\n" + "\n".join(f"M{i}: {m}" for i, m in enumerate(must_have, 1))
            + "\n\nFact cards:\n" + ("\n".join(lines) or "(none)"))
    return [{"role": "system", "content": JUDGE_PROMPTS[prompt]}, {"role": "user", "content": body}], ids


class BriefReadEval(Step):
    name = "brief_read"
    model_step = "brief_read"
    headline = ("coverage", "quote_ok_first", "facts_per_article", "facts_dropped", "articles_failed",
                "json_retries", "must_have", "articles")
    report_title = "News brief, step 1: reading each article"
    report_intro = ("Step 1 reads each picked article and lists its facts, each with the article's exact words. "
                    "Runs are scored on Jan's 26 answer sheets: how many must-have facts the cards cover "
                    "(a judge from another model family decides), and how many quotes check out word for word.")
    metric_notes = {
        "coverage": ("Coverage", "The main score: share of must-have facts that at least one fact card states."),
        "quote_ok_first": ("Quotes exact", "Share of cards whose quote was in the article word for word on the first try."),
        "facts_per_article": ("Cards per article", "Fact cards kept per article."),
        "facts_dropped": ("Cards dropped", "Cards dropped because their quote failed even after the retry."),
        "articles_failed": ("Failed articles", "Articles with no usable answer after one retry. Must be 0."),
        "json_retries": ("JSON retries", "Articles that needed a second ask because the answer wasn't usable JSON."),
        "must_have": ("Must-have facts", "Must-have facts in the stories run."),
        "articles": ("Articles", "Articles read."),
    }

    def __init__(self, n=None, judge=None, stories_dir=None, sheets=None, judge_prompt=None, from_run=None):
        self.n = str(n or "10")
        self.judge = judge or JUDGE
        self.judge_prompt = judge_prompt_of(judge_prompt)
        self.from_run = Path(from_run) if from_run else None
        self._saved = None
        self.stories_dir = Path(stories_dir or paths.STORIES)
        self.sheets_path = Path(sheets or SHEETS)
        self.version = with_judge(f"{brief_read.VERSION}-n{self.n}", self.judge_prompt)

    # -- inputs ---------------------------------------------------------------------------------
    def _sheets(self) -> dict:
        return {s["short_id"]: s for s in json.loads(self.sheets_path.read_text(encoding="utf-8"))["stories"]}

    def load(self, only=None, split="tune") -> list[Item]:
        sheets = self._sheets()
        dirs = {d.name[:8]: d for d in sorted(self.stories_dir.iterdir()) if (d / "gather.json").exists()}
        items = [Item(id=f"story:{sid}", story=sid, data={"dir": str(dirs[sid]), "sheet": sh},
                      split="holdout" if sh["n"] in HOLDOUT else "tune")
                 for sid, sh in sorted(sheets.items(), key=lambda kv: kv[1]["n"]) if sid in dirs]
        if only:
            items = [i for i in items if i.story in set(only)]
        if self.from_run:
            items = [i for i in items if i.story in self.saved()["stories"]]
        if split != "all":
            items = [i for i in items if i.split == split]
        return items

    def load_key(self) -> dict:
        return {sid: sh["facts"] for sid, sh in self._sheets().items()}

    def key_version(self) -> str:
        d = json.loads(self.sheets_path.read_text(encoding="utf-8"))
        return f"{d.get('version')} ({d['counts']['facts']} must-have facts)"

    def _articles(self, item: Item):
        d = Path(item.data["dir"])
        meta = json.loads((d / "gather.json").read_text(encoding="utf-8"))
        arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
        n = 100_000 if self.n == "all" else int(self.n)
        chosen = set(pick.pick(arts, meta["lens"], n=n)["picked"])
        return meta["event"], [a for a in arts if a["id"] in chosen]

    # -- running --------------------------------------------------------------------------------
    def run(self, item: Item, ctx):
        if self.from_run:
            return self.rejudge(item, ctx)
        event, arts = self._articles(item)
        complete = lambda msgs, name=None, **p: ctx.complete(msgs, name=name, **p)
        out = brief_read.read_story(event, arts, complete, model=ctx.model)
        must = item.data["sheet"]["facts"]
        out["judge"] = self._judge(must, self.judge_cards(out), ctx) if must else {"model": self.judge, "results": {}}
        return out

    def judge_cards(self, out: dict) -> list[dict]:
        """What the coverage judge reads from a step's output: step 1's fact cards."""
        return [f for r in out["articles"] for f in r["facts"]]

    # -- judge-only reruns (option from_run) --------------------------------------------------------
    def saved(self) -> dict:
        """{"run_id", "stories": {story: output}} from the run named by option from_run."""
        if self._saved is None:
            d = json.loads(self.from_run.read_text(encoding="utf-8"))
            self._saved = dict(run_id=d.get("run_id"), stories={
                r["story"]: r["output"] for r in d.get("items_detail") or [] if r.get("output")})
        return self._saved

    def rejudge(self, item: Item, ctx) -> dict:
        """The saved output with a fresh coverage verdict; everything else is kept as it was."""
        out = copy.deepcopy(self.saved()["stories"][item.story])
        out["rejudged_from"] = self.saved()["run_id"]
        must, cards = item.data["sheet"]["facts"], self.judge_cards(out)
        out["judge"] = (self._judge(must, cards, ctx) if must and cards
                        else {"model": self.judge, "prompt": self.judge_prompt, "results": {}})
        return out

    def judge_plan(self, item: Item) -> list[dict]:
        out = self.saved()["stories"].get(item.story)
        must, cards = item.data["sheet"]["facts"], self.judge_cards(out) if out else []
        if not (must and cards):
            return []
        return [{"model": self.judge, "messages": judge_messages(must, cards, self.judge_prompt)[0],
                 "params": {"max_tokens": JUDGE_MAX_TOKENS, "response_format": JUDGE_SCHEMA},
                 "expect_output": 40 * len(must) + 100}]

    def _judge(self, must, facts, ctx) -> dict:
        msgs, ids = judge_messages(must, facts, self.judge_prompt)
        res = None
        for attempt in range(2):
            try:
                r = ctx.complete(msgs if attempt == 0 else msgs + [{"role": "user", "content": brief_read.RETRY_JSON}],
                                 name=f"{self.name} judge", model=self.judge, max_tokens=JUDGE_MAX_TOKENS,
                                 response_format=JUDGE_SCHEMA, timeout=brief_read.CALL_TIMEOUT_S)
                res = json.loads(r.text.strip().removeprefix("```json").removesuffix("```"))["results"]
                break
            except Exception as e:                     # unusable or failed: one more try, then report
                if type(e).__name__ == "BudgetExceeded":
                    raise
                res = None
        if res is None:
            return {"model": self.judge, "prompt": self.judge_prompt, "error": "no usable judge answer", "results": {}}
        out = {}
        for x in res:
            if isinstance(x, dict) and str(x.get("id", "")).startswith("M"):
                out[x["id"]] = {"found": bool(x.get("found")), "cards": [ids.get(c, c) for c in x.get("cards") or []]}
        return {"model": self.judge, "prompt": self.judge_prompt, "results": out}

    def plan(self, item: Item, model: str) -> list[dict]:
        if self.from_run:
            return self.judge_plan(item)
        event, arts = self._articles(item)
        calls = []
        for a in arts:
            if a.get("text_status") != "full":
                continue
            text, _ = brief_read.shown_text(a)
            calls.append({"messages": brief_read.messages_for(event, a, text), "params": brief_read.params_for(model),
                          "expect_output": 1800})
        return calls

    # -- scoring --------------------------------------------------------------------------------
    def score(self, item: Item, output, key: dict) -> dict:
        must = key.get(item.story) or []
        res = (output.get("judge") or {}).get("results") or {}
        found = [bool((res.get(f"M{i}") or {}).get("found")) for i in range(1, len(must) + 1)]
        arts = output.get("articles") or []
        ch = [a["checks"] for a in arts]
        first = sum(c.get("facts_first", 0) for c in ch)
        bad = sum(c.get("quotes_bad_first", 0) for c in ch)
        kept = sum(len(a["facts"]) for a in arts)
        return dict(must_have=len(must), found=sum(found), found_each=found,
                    coverage=round(sum(found) / len(must), 3) if must else None,
                    articles=len(arts), facts=kept, facts_first=first, quotes_bad_first=bad,
                    facts_dropped=sum(c.get("facts_dropped", 0) for c in ch),
                    articles_failed=sum(bool(c.get("error")) for c in ch),
                    json_retries=sum(bool(c.get("retried_json")) for c in ch),
                    quote_retries=sum(bool(c.get("retried_quotes")) for c in ch),
                    non_english=sum((a.get("lang") or "en") != "en" for a in arts),
                    text_cut=sum(bool(c.get("text_cut")) for c in ch),
                    judge_error=(output.get("judge") or {}).get("error"))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        must, first, arts = tot("must_have"), tot("facts_first"), tot("articles")
        return dict(coverage=round(tot("found") / must, 3) if must else None, must_have=must, found=tot("found"),
                    quote_ok_first=round(1 - tot("quotes_bad_first") / first, 3) if first else None,
                    facts_per_article=round(tot("facts") / arts, 2) if arts else None,
                    facts_dropped=tot("facts_dropped"), articles_failed=tot("articles_failed"),
                    json_retries=tot("json_retries"), quote_retries=tot("quote_retries"), articles=arts,
                    non_english=tot("non_english"), text_cut=tot("text_cut"),
                    judge_errors=sum(bool(s.get("judge_error")) for s in scores),
                    stories={i.story: s.get("coverage") for i, s in zip(items, scores)})

    # -- report ---------------------------------------------------------------------------------
    def story_names(self) -> dict[str, str]:
        return {sid: sh["title"] for sid, sh in self._sheets().items()}

    def mistakes(self, rec: dict) -> list[dict]:
        key = self.load_key()
        out = []
        for row in rec.get("items_detail") or []:
            sc = row.get("scores") or {}
            for fact, ok in zip(key.get(row["story"]) or [], sc.get("found_each") or []):
                if not ok:
                    out.append(dict(story=row["story"], kind="missed fact", title=fact, url=None,
                                    gold="found", pred="missed", reason="", source="jan"))
        return out
