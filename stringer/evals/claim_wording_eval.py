"""The loaded-words check on the Story Files' claims (module 5): a model judge, no word list (decided
Nov 25, Jan).

    python -m scripts.run_eval run claim_wording --model gemini-3.5-flash-lite --split all --cap 0.20

Input: each story's story_file.json as built now (its claims, with who says each). One call per story
lists the claims whose own wording takes a side or judges; words inside quotation marks or that a named
source is reported as using don't count. Code checks that each flagged word is really in the claim and
whether it sits inside quotation marks.

There is no answer key: the report lists every flag for a hand check.

Scores (all stories):
  flagged_share     claims flagged (loaded or borderline) out of all claims
  loaded            claims flagged "loaded" (takes a side or judges)
  borderline        claims flagged "borderline" (some readers would see a slant)
  own_voice_share   of the flagged claims, those whose who_says is "the outlet"
  words_missing     flags whose words aren't in the claim (a judge slip; kept for the hand check)
  in_quotes         flags whose words sit inside quotation marks in the claim (shouldn't be flagged)
  stories_failed    stories with no usable judge answer after one retry (must stay 0)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import brief_merge, brief_read, story_file
from .brief_read_eval import JUDGE_MAX_TOKENS, BriefReadEval
from .runner import Item

VERSION = "wording-1"

SYSTEM = """You check the wording of the claims in a news brief about one event. Every claim must be worded neutrally: in plain words a wire service would use, so that viewers on any side can accept the wording even when they dispute the fact.

Flag a claim when its own words take a side or pass judgment:
- labels one side uses for the other ("regime", "terrorists" for a state's forces, "junta", "occupiers", "puppet");
- loaded verbs and adjectives ("slammed", "lashed out", "blasted", "brutal", "shameful", "stunning", "humiliating");
- words that assume a contested point or soften what happened ("so-called", "illegal" when legality is disputed, "liberated" for captured, "aggression");
- dramatic words that add no fact ("massive", "historic", "unprecedented", "devastating"), unless the claim itself gives the scale.

Don't flag:
- words inside quotation marks, or words a named source is reported as using ("Zelensky called the attack horrific", "Russia called it a terrorist act"): reporting what someone said is neutral;
- plain words for what happened: killed, attack, strike, bomb, war, invasion, protest, militants;
- a fact you think is wrong or one-sided: only the wording counts here.

For each flagged claim give its id, the loaded words exactly as they appear in the claim, why in a few words, a neutral rewording of the whole claim, and the level: "loaded" (takes a side or judges) or "borderline" (some readers would see a slant). Leave out claims worded neutrally. Answer with JSON only: {"flags": [...]}, with an empty list if every claim is neutral."""


def schema(ids: list[str]) -> dict:
    flag = {"type": "object", "additionalProperties": False, "required": ["id", "words", "why", "neutral", "level"],
            "properties": {"id": {"type": "string", "enum": ids}, "words": {"type": "string"}, "why": {"type": "string"},
                           "neutral": {"type": "string"}, "level": {"type": "string", "enum": ["loaded", "borderline"]}}}
    return {"type": "json_schema", "json_schema": {"name": "wording", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["flags"],
        "properties": {"flags": {"type": "array", "items": flag}}}}}


def messages_for(event: dict, claims: list[dict]) -> list[dict]:
    lines = [f"{c['id']} [who says: {c.get('who_says') or 'the outlet'}] {c['claim']}" for c in claims]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Event: {event.get('title', '')}\n\nClaims ({len(claims)}):\n" + "\n".join(lines)}]


_QUOTED = re.compile(r"[\"“”‘’'«»]([^\"“”‘’'«»]{2,})[\"“”‘’'«»]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[“”«»]", '"', re.sub(r"[‘’]", "'", s or ""))).strip().lower()


def placed(claim: str, words: str) -> tuple[bool, bool]:
    """(the words are in the claim, they sit inside quotation marks there)."""
    c, w = _norm(claim), _norm(words).strip(" \"'.,")
    if not w or w not in c:
        return False, False
    i = c.index(w)
    return True, any(m.start(1) <= i < m.end(1) for m in _QUOTED.finditer(c))


def judge(event: dict, claims: list[dict], complete, *, model: str = "", name: str = "claim_wording judge") -> dict:
    """{"flags": [...], "error"}: one call, one retry on an unusable answer; flags for unknown ids are dropped."""
    ids = [c["id"] for c in claims]
    by = {c["id"]: c for c in claims}
    msgs = messages_for(event, claims)
    params = dict(max_tokens=JUDGE_MAX_TOKENS * 2, response_format=schema(ids), timeout=brief_read.CALL_TIMEOUT_S)
    errs = []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": brief_read.RETRY_JSON}],
                                     params, name if attempt == 0 else f"{name} retry")
        if err:
            errs.append(err)
        t = (text or "").strip()
        if t.startswith("```"):
            t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
        try:
            d = json.loads(t)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and isinstance(d.get("flags"), list):
            flags, seen = [], set()
            for x in d["flags"]:
                if not isinstance(x, dict) or x.get("id") not in by or x["id"] in seen:
                    continue
                seen.add(x["id"])
                c = by[x["id"]]
                found, quoted = placed(c["claim"], str(x.get("words", "")))
                flags.append(dict(id=x["id"], claim=c["claim"], who_says=c.get("who_says"), kind=c.get("kind"),
                                  words=str(x.get("words", ""))[:200], why=str(x.get("why", ""))[:300],
                                  neutral=str(x.get("neutral", ""))[:400],
                                  level=x.get("level") if x.get("level") in ("loaded", "borderline") else "borderline",
                                  words_found=found, in_quotes=quoted))
            return dict(flags=flags, calls=attempt + 1, error=None)
    return dict(flags=[], calls=2, error="no usable wording judge answer after one retry" + (f" ({errs[-1]})" if errs else ""))


class ClaimWordingEval(BriefReadEval):
    name = "claim_wording"
    model_step = None
    headline = ("flagged_share", "loaded", "borderline", "own_voice_share", "words_missing", "in_quotes", "stories_failed")
    report_title = "Story File: loaded words in claims (model judge)"
    report_intro = ("A judge from another model family (Gemini; steps 1 and 2 use DeepSeek) reads each story's claims "
                    "and flags wording that takes a side or judges. Words in quotation marks or that a named source is "
                    "reported as using don't count. No answer key: every flag is listed for a hand check.")
    metric_notes = {
        "flagged_share": ("Claims flagged", "Share of all claims the judge flagged, loaded or borderline."),
        "loaded": ("Loaded", "Claims flagged as taking a side or judging."),
        "borderline": ("Borderline", "Claims flagged as wording some readers would see as slanted."),
        "own_voice_share": ("In the outlet's own voice", "Of the flagged claims, those whose who_says is \"the outlet\"."),
        "words_missing": ("Words not in the claim", "Flags whose words aren't in the claim (a judge slip)."),
        "in_quotes": ("Words in quotation marks", "Flags on words inside quotation marks (the judge should skip these)."),
        "stories_failed": ("Failed stories", "Stories with no usable judge answer after one retry. Must be 0."),
    }

    def __init__(self, n=None, judge=None, stories_dir=None, sheets=None):
        super().__init__(n=n, judge=judge, stories_dir=stories_dir, sheets=sheets)
        self.version = f"{VERSION}-{story_file.VERSION}-{brief_merge.VERSION}"

    def _file(self, item: Item) -> dict:
        return story_file.read(Path(item.data["dir"]))[1]

    def run(self, item: Item, ctx):
        sf = self._file(item)
        if not sf.get("claims"):
            return dict(flags=[], claims=0, error="no claims in the Story File")
        complete = lambda msgs, name=None, **p: ctx.complete(msgs, name=name, **p)
        out = judge(sf["event"], sf["claims"], complete, model=ctx.model)
        out.update(claims=len(sf["claims"]), own_voice=sum((c.get("who_says") or "the outlet") == "the outlet" for c in sf["claims"]),
                   step2=(sf["meta"]["steps"].get("brief_merge") or {}).get("run"))
        return out

    def plan(self, item: Item, model: str) -> list[dict]:
        sf = self._file(item)
        if not sf.get("claims"):
            return []
        ids = [c["id"] for c in sf["claims"]]
        return [dict(messages=messages_for(sf["event"], sf["claims"]),
                     params=dict(max_tokens=JUDGE_MAX_TOKENS * 2, response_format=schema(ids)), expect_output=1500)]

    def score(self, item: Item, output, key: dict) -> dict:
        f = output.get("flags") or []
        return dict(claims=output.get("claims", 0), flagged=len(f), loaded=sum(x["level"] == "loaded" for x in f),
                    borderline=sum(x["level"] == "borderline" for x in f),
                    own_voice_flagged=sum((x.get("who_says") or "the outlet") == "the outlet" for x in f),
                    words_missing=sum(not x["words_found"] for x in f), in_quotes=sum(x["in_quotes"] for x in f),
                    failed=bool(output.get("error")))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        claims, flagged = tot("claims"), tot("flagged")
        return dict(flagged_share=round(flagged / claims, 3) if claims else None, flagged=flagged, claims=claims,
                    loaded=tot("loaded"), borderline=tot("borderline"),
                    own_voice_share=round(tot("own_voice_flagged") / flagged, 3) if flagged else None,
                    words_missing=tot("words_missing"), in_quotes=tot("in_quotes"), stories_failed=tot("failed"),
                    stories={i.story: s.get("flagged") for i, s in zip(items, scores)})

    def mistakes(self, rec: dict) -> list[dict]:
        """Every flag, for the hand check."""
        return [dict(story=r["story"], kind=x["level"], title=x["claim"], url=None, gold=f"who says: {x.get('who_says')}",
                     pred=f"{x['words']} -> {x['neutral']}", reason=x["why"]
                     + ("" if x["words_found"] else " [words not in the claim]") + (" [inside quotes]" if x["in_quotes"] else ""),
                     source=x["id"])
                for r in rec.get("items_detail") or [] for x in (r.get("output") or {}).get("flags") or []]
