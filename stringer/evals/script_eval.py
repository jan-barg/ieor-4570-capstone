"""The eval for module 7, the script writer, plugged into the runner (design agreed Nov 26, Jan: "All as
recommended"; overview page section 7).

    python -m scripts.run_eval estimate script --model sonnet-5-5 --split all
    python -m scripts.run_eval run script --model sonnet-5-5 --split all --cap 2.00

Inputs: every story folder with a checked Story File (module 6's output). The 26 with an answer sheet
are scored: 21 tune stories, and sheets 5, 10, 15, 20 and 25 held out of prompt changes. A folder with no
sheet (the live story) gets the split "live": its script is written and checked, with no sheet scores.
One item per story. The writer is the run's model; the line check and the loaded-words check use the
models config/models.toml names for them, so every writer is checked by the same checkers.

Answer keys (private, under stringer_private/):
  fixtures/answer_sheets_v2.json   the must-have facts of each story, and the note on the 6 stories
                                   where who says so is the trap
Planted mistakes (made by code, no key file): OFF by default since Nov 26 (Jan: the claims were already
fact-checked in module 6, whose checker was drilled with planted mistakes; a second drill here chases
marginal gains). With plants=1, up to two of a script's lines are copied with one mistake each (a changed
number, a swapped or dropped speaker, a dropped hedge, the wrong claims cited, one side of a disagreement
said as fact) and checked again.

Scores:
  first_clean        the main score: share of stories whose first draft passed every check
  videos             share of stories that got a video (with or without cuts)
  rules_final_ok     share of final drafts with no broken code rule (after the one fix round)
  on_screen_final_ok share of final drafts whose on-screen text all passed
  lines_backed_first share of lines the line check found backed in the first draft
  lines_backed_final the same in the final draft
  cut_beats          beats cut or turned into a headline card
  loaded_final       loaded words left in final drafts
  coverage           share of must-have facts a line states (a fixed judge, cov-1's rules)
  who_says           on the 6 trap stories: of the noted points a script mentions, the share it attributes
  plants_caught      (plants=1 only) share of planted mistakes caught by code or the line check
  words, step_cost, step_seconds, failures
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .. import brief_read, fact_check, paths, script_writer as sw, shots, story_file
from .brief_read_eval import HOLDOUT, JUDGE, JUDGE_MAX_TOKENS, JUDGE_SCHEMA, SHEETS
from .runner import Item, Step

COV_SYSTEM = """You check whether the lines of a news video script state each of a story's must-have facts.

A must-have fact counts as found when at least one line states the same core fact: the same who and what, and the same number if the fact has one. Wording may differ, and extra detail is fine. A line that gives the fact as someone's account ("X says ...") counts. A line that only hints at the fact, states something related, or gives a different number does not count.

For every must-have fact, answer with its id, whether it is found, and the ids of the lines that state it (empty if not found). Answer with JSON only."""

WHO_SYSTEM = """You check a news video script against a fact-checker's note. The note says which points in this story are someone's claim or interpretation, or which words are one side's framing, and should not be stated as plain fact.

List each such point from the note. For each one, say whether the script mentions it, and if it does, whether it attributes it: says who says it ("exit polls show ...", "analysts say ...", "X calls it ...") or puts the framing word in a quote, instead of stating it as fact. A point the script doesn't mention is not attributed and not a failure.

Answer with JSON only."""

WHO_SCHEMA = {"type": "json_schema", "json_schema": {"name": "who_says", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["points"],
    "properties": {"points": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["point", "mentioned", "attributed", "lines"],
        "properties": {"point": {"type": "string"}, "mentioned": {"type": "boolean"}, "attributed": {"type": "boolean"},
                       "lines": {"type": "array", "items": {"type": "string"}}}}}}}}}

PLANT_KINDS = ("number", "speaker swapped", "speaker dropped", "hedge dropped", "wrong claims", "half a conflict")
HEDGE_WORDS = ("reportedly", "at least", "about", "around", "nearly", "up to", "more than", "preliminary", "may", "suggest",
               "appears to", "appear to", "allegedly", "possibly")
PLANTS_PER_STORY = 2


def _share(a, b):
    return round(a / b, 3) if b else None


def _lines(script: dict) -> list[str]:
    return [f"L{b['n']}: {shots.display(b['say'])}" for b in script.get("beats") or []]


# ---- planted mistakes (code) -------------------------------------------------------------------------

def _bump(m: re.Match) -> str:
    s = m.group(0)
    n = int(s.replace(",", ""))
    new = n * 2 + 3 if n < 10 else n + max(1, n // 4) + 7
    return f"{new:,}" if "," in s else str(new)


def _verbatim(text: str, name: str) -> re.Match | None:
    return re.search(re.escape(name), text, re.I) if name else None


def plant(beat: dict, kind: str, p: dict, beats: list[dict]) -> dict | None:
    """A copy of one checked beat with one mistake of the given kind, or None when the beat has nothing
    to plant it in. The copy keeps its blanks, so code checks it the same way."""
    say = beat["say"]
    cited = [p["claims"][x] for x in beat["claims"] if x in p["claims"]]
    if kind == "number":
        unq = shots.MARK.sub(lambda m: "" if m.group(1) == "quote" else m.group(0), say)
        m = re.search(r"\b\d[\d,]*\b", unq)
        if not m or (len(m.group(0)) == 4 and m.group(0).startswith(("19", "20"))):
            return None
        new = re.sub(re.escape(m.group(0)), _bump(m), say, count=1)
        return dict(beat, say=new) if new != say else None
    if kind in ("speaker swapped", "speaker dropped"):
        for c in cited:
            if c["status"] != "say with source":
                continue
            m = _verbatim(say, c.get("attribute_to") or "")
            if not m:
                continue
            if kind == "speaker swapped":
                others = sorted({x.get("attribute_to") for x in p["claims"].values()
                                 if x.get("attribute_to") and x["id"] not in beat["claims"]
                                 and x.get("attribute_to") != c["attribute_to"] and len(x["attribute_to"]) < 60})
                if not others:
                    return None
                return dict(beat, say=say[:m.start()] + others[len(say) % len(others)] + say[m.end():])
            cut_ = re.compile(re.escape(m.group(0)) + r"\s+(says|said|reports|reported)(\s+that)?\s+", re.I)
            new = cut_.sub("", say, count=1)
            new = re.sub(r"(?i)according to " + re.escape(m.group(0)) + r",?\s*", "", new, count=1)
            if new == say:
                return None
            new = re.sub(r"(^|\]\s*|\[\w+ )([a-z])", lambda x: x.group(1) + x.group(2).upper(), new, count=1)
            return dict(beat, say=new)
        return None
    if kind == "hedge dropped":
        for h in HEDGE_WORDS:
            rx = re.compile(rf"\b{re.escape(h)}\w*\s+", re.I)
            unq = shots.MARK.sub(lambda m: "" if m.group(1) == "quote" else m.group(0), say)
            if rx.search(unq):
                new = rx.sub("", say, count=1)
                return dict(beat, say=new) if new != say else None
        return None
    if kind == "wrong claims":
        for other in beats:
            if other is beat or not other["claims"] or set(other["claims"]) & set(beat["claims"]):
                continue
            if other["shot"] in ("sides", "sources"):
                continue
            return dict(beat, claims=list(other["claims"]), card="", accounts=[])
        return None
    if kind == "half a conflict" and beat["shot"] == "claim_vs_claim":
        left = [w for m, w in shots.marks(say) if m == "left"]
        acc = beat["accounts"][0] if beat["accounts"] else None
        c = p["claims"].get(acc["claim"]) if acc else None
        if not (left and c):
            return None
        m = _verbatim(left[0], c.get("attribute_to") or "")
        if not m:
            return None
        rest = re.sub(r"^\s*(says|said|reports)(\s+that)?\s+", "", left[0][m.end():], flags=re.I).strip()
        if not rest:
            return None
        return dict(beat, shot="headline", say=rest[0].upper() + rest[1:], claims=[c["id"]], accounts=[],
                    title=" ".join(rest.split()[:6]))
    return None


def plants_for(script: dict, p: dict, story: str, n: int = PLANTS_PER_STORY) -> list[dict]:
    """Up to n planted lines, one kind each, picked the same way every run (from the story id)."""
    final = script.get("_final_beats") or []
    start = int(hashlib.sha1(story.encode()).hexdigest(), 16) % len(PLANT_KINDS)
    kinds = PLANT_KINDS[start:] + PLANT_KINDS[:start]
    out, used = [], set()
    for kind in kinds:
        for i, b in enumerate(final):
            if i in used or b["shot"] in ("sources", "sides"):
                continue
            new = plant(b, kind, p, final)
            if new is not None:
                out.append(dict(kind=kind, beat=i + 1, original=b["say"], beat_data=new))
                used.add(i)
                break
        if len(out) >= n:
            break
    return out


# ---- the step ----------------------------------------------------------------------------------------

class ScriptEval(Step):
    name = "script"
    model_step = "script"
    version = sw.VERSION
    headline = ("first_clean", "videos", "rules_final_ok", "on_screen_final_ok", "lines_backed_first", "lines_backed_final",
                "cut_beats", "loaded_final", "coverage", "who_says", "words",
                "step_cost", "step_seconds", "failures")
    report_title = "Script writer (module 7)"
    report_intro = ("The script writer turns each story's checked research file into a 60-second video script: beats, "
                    "each one shot with its spoken line and the claims it rests on. Code checks the rules, the fact "
                    "check's model checks every line against its quotes, a second model checks the wording, and the "
                    "writer gets one round to fix what failed. Runs are scored on the 26 answer sheets (must-have "
                    "facts, who says so) and on cost and time.")
    metric_notes = {
        "first_clean": ("Clean first try", "The main score: share of stories whose first draft passed every check (rules, on-screen text, line check, wording)."),
        "videos": ("Videos", "Share of stories that got a video, with or without cut beats."),
        "rules_final_ok": ("Rules kept", "Share of final drafts (after the one fix round) with no broken code rule. Target 1."),
        "on_screen_final_ok": ("On-screen OK", "Share of final drafts whose on-screen numbers, names and quotes all come from the cited claims. Target 1."),
        "lines_backed_first": ("Lines backed, 1st", "Share of lines the line check found backed by their claims' quotes in the first draft."),
        "lines_backed_final": ("Lines backed, final", "The same after the fix round."),
        "cut_beats": ("Beats cut", "Beats that still failed after the fix round and were cut or turned into a headline card."),
        "loaded_final": ("Loaded words", "Loaded words the wording check still found in final drafts."),
        "coverage": ("Must-haves", "Share of the answer sheets' must-have facts that a line states (a judge from another family decides)."),
        "who_says": ("Who says so", "On the 6 trap stories: of the points the note says need a source that a script mentions, the share it attributes."),
        "plants_caught": ("Plants caught", "Share of planted mistakes (a changed number, a dropped speaker, ...) caught by code or the line check."),
        "plants_reached": ("Plants passed", "Planted mistakes that passed every check and would reach the video. Must be 0."),
        "words": ("Words", "Spoken words per script, on average (aim 135 to 165; refused above 180)."),
        "step_cost": ("Cost / story", "The script's own cost per story (writer, fix round, line and wording checks); the judges are the eval's extra."),
        "step_seconds": ("Seconds / story", "Model time per story for the script's own calls, one after another."),
        "failures": ("No answer", "Stories where the writer gave no usable answer after a retry. Must be 0."),
    }
    class_names = {k: k for k in PLANT_KINDS} | {"backed": "Backed (missed)", "caught by code": "Caught by code",
                                                 "needs a name": "Needs a name", "not backed": "Not backed",
                                                 "no answer": "No answer"}

    def __init__(self, stories_dir=None, sheets=None, tone=None, angle=None, line_model=None, words_model=None,
                 judge=None, fix=None, plants=None):
        self.stories_dir = Path(stories_dir or paths.STORIES)
        self.sheets_path = Path(sheets or SHEETS)
        self.tone = tone or sw.TONE
        self.angle = angle or ""
        self.line_model = line_model or sw._model_for(sw.LINE_STEP, sw.LINE_MODEL)
        self.words_model = words_model or sw._model_for(sw.WORDS_STEP, sw.WORDS_MODEL)
        self.judge = judge or JUDGE
        self.fix = str(fix).lower() not in ("0", "false", "no") if fix is not None else True
        self.plants = str(plants).lower() in ("1", "true", "yes") if plants is not None else False   # off (Jan, Nov 26)
        if self.tone != sw.TONE or self.angle or not self.fix:
            self.version = f"{sw.VERSION}-{self.tone}" + ("-angle" if self.angle else "") + ("" if self.fix else "-nofix")

    # -- inputs ---------------------------------------------------------------------------------
    def _sheets(self) -> dict:
        if not self.sheets_path.exists():
            return {}
        return {s["short_id"]: s for s in json.loads(self.sheets_path.read_text(encoding="utf-8"))["stories"]}

    def load(self, only=None, split="tune") -> list[Item]:
        sheets = self._sheets()
        items = []
        for d in sorted(self.stories_dir.iterdir()):
            if not (d / fact_check.CHECKED_FILE).exists():
                continue
            sid = d.name[:8]
            sh = sheets.get(sid)
            sp = "live" if sh is None else ("holdout" if sh["n"] in HOLDOUT else "tune")
            items.append(Item(id=f"story:{sid}", story=sid, data={"dir": str(d), "n": sh["n"] if sh else None}, split=sp))
        items.sort(key=lambda i: (i.data["n"] is None, i.data["n"] or 0, i.story))
        if only:
            items = [i for i in items if i.story in set(only)]
        if split != "all":
            items = [i for i in items if i.split == split]
        return items

    def load_key(self) -> dict:
        return {"sheets": self._sheets()}

    def key_version(self) -> str:
        s = self._sheets()
        return f"answer sheets v2 ({sum(len(x['facts']) for x in s.values())} must-have facts, " \
               f"{sum(bool(x['who_says_so']) for x in s.values())} who-says-so notes) + code-made plants"

    def _story(self, item: Item):
        d = Path(item.data["dir"])
        facts, _ = story_file.read(d)
        return fact_check.read_checked(d), facts, fact_check.read_articles(d)

    # -- running --------------------------------------------------------------------------------
    def run(self, item: Item, ctx):
        sf, facts, arts = self._story(item)
        t0, c0 = ctx.stats.latency_s, ctx.stats.cost_usd
        script = sw.write_script(sf, facts, arts, ctx.complete, model=ctx.model, line_model=self.line_model,
                                 words_model=self.words_model, tone=self.tone, angle=self.angle, fix=self.fix,
                                 cost=lambda: ctx.stats.cost_usd)
        step_cost, step_s = ctx.stats.cost_usd - c0, ctx.stats.latency_s - t0
        sheet = self._sheets().get(item.story)
        out = dict(script=script, step_cost_usd=round(step_cost, 6), step_seconds=round(step_s, 2),
                   coverage=None, who_says=None, plants=[])
        if not script["beats"]:
            return out
        if sheet:
            out["coverage"] = self._coverage(sheet["facts"], script, ctx)
            if sheet.get("who_says_so"):
                out["who_says"] = self._who_says(sheet["note"], script, ctx)
        if self.plants:
            out["plants"] = self._plants(item, sf, facts, arts, script, ctx)
        return out

    def _judge_call(self, ctx, msgs, schema, name):
        for attempt in range(2):
            try:
                r = ctx.complete(msgs if attempt == 0 else msgs + [{"role": "user", "content": brief_read.RETRY_JSON}],
                                 name=name, model=self.judge, max_tokens=JUDGE_MAX_TOKENS, response_format=schema,
                                 timeout=brief_read.CALL_TIMEOUT_S)
                return json.loads(r.text.strip().removeprefix("```json").removesuffix("```"))
            except Exception as e:
                if type(e).__name__ == "BudgetExceeded":
                    raise
        return None

    def _coverage_messages(self, must: list[str], script: dict) -> list[dict]:
        body = ("Must-have facts:\n" + "\n".join(f"M{i}: {m}" for i, m in enumerate(must, 1))
                + "\n\nScript lines:\n" + "\n".join(_lines(script)))
        return [{"role": "system", "content": COV_SYSTEM}, {"role": "user", "content": body}]

    def _coverage(self, must: list[str], script: dict, ctx) -> dict:
        d = self._judge_call(ctx, self._coverage_messages(must, script), JUDGE_SCHEMA, "script eval coverage")
        if not isinstance(d, dict) or not isinstance(d.get("results"), list):
            return dict(error="no usable judge answer", results={})
        res = {x["id"]: dict(found=bool(x.get("found")), lines=x.get("cards") or [])
               for x in d["results"] if isinstance(x, dict) and str(x.get("id", "")).startswith("M")}
        return dict(results=res, must=must)

    def _who_messages(self, note: str, script: dict) -> list[dict]:
        return [{"role": "system", "content": WHO_SYSTEM},
                {"role": "user", "content": f"Note: {note}\n\nScript lines:\n" + "\n".join(_lines(script))}]

    def _who_says(self, note: str, script: dict, ctx) -> dict:
        d = self._judge_call(ctx, self._who_messages(note, script), WHO_SCHEMA, "script eval who says")
        if not isinstance(d, dict) or not isinstance(d.get("points"), list):
            return dict(error="no usable judge answer", points=[])
        return dict(points=[dict(point=str(x.get("point", ""))[:300], mentioned=bool(x.get("mentioned")),
                                 attributed=bool(x.get("attributed")), lines=x.get("lines") or [])
                            for x in d["points"] if isinstance(x, dict)], note=note)

    def _plants(self, item, sf, facts, arts, script, ctx) -> list[dict]:
        contexts = sw.contexts_for(facts, arts)
        p = sw.packet(sf, facts, contexts, tone=self.tone, angle=self.angle)
        final = [_beat_in(b) for b in script["beats"]]
        planted = plants_for(dict(script, _final_beats=final), p, item.story)
        if not planted:
            return []
        mini = dict(beats=[x["beat_data"] for x in planted])
        code = sw.code_problems(dict(beats=mini["beats"]), p)
        code = [x for x in code if x["beat"] is not None and x["rule"] not in ("repeat",)]
        lc = sw.line_check(mini, p, facts, contexts, ctx.complete, model=self.line_model, name="script eval plants")
        lp = sw.line_problems(mini, p, lc)
        out = []
        for n, x in enumerate(planted, 1):
            by_code = [y["what"] for y in code if y["beat"] == n]
            by_line = [y["what"] for y in lp if y["beat"] == n]
            v = lc["verdicts"].get(n)
            out.append(dict(kind=x["kind"], beat=x["beat"], original=x["original"], planted=x["beat_data"]["say"],
                            claims=x["beat_data"]["claims"], verdict=(v or {}).get("verdict") or "no answer",
                            why=(v or {}).get("why", ""), by_code=by_code, by_line=by_line,
                            caught=bool(by_code or by_line)))
        return out

    def plan(self, item: Item, model: str) -> list[dict]:
        """The writer's call, a fix round of the same size plus its first answer, and the checks on a
        stand-in script of 9 beats citing the strongest claims (the real script isn't known before it is
        written)."""
        sf, facts, arts = self._story(item)
        contexts = sw.contexts_for(facts, arts)
        p = sw.packet(sf, facts, contexts, tone=self.tone, angle=self.angle)
        if not p["claims"]:
            return []
        msgs = sw.messages_for(p)
        params = sw._params(p, model)
        params.pop("model")
        calls = [dict(messages=msgs, params=params, expect_output=3000)]
        if self.fix:
            calls.append(dict(messages=msgs + [{"role": "assistant", "content": "x" * 9000},
                                               {"role": "user", "content": sw.FIX.format(problems="- " + "y" * 600)}],
                              params=params, expect_output=3000))
        ids = list(p["claims"])
        stand_in = dict(beats=[sw.normalize_beat(dict(shot="headline", say="A line of about twenty words " * 3,
                                                      claims=ids[2 * i:2 * i + 2]), p) for i in range(9)])
        lp = sw.line_plan(stand_in, p, facts, contexts, self.line_model)
        lp["model"] = lp["params"].pop("model")
        wp = sw.words_plan(stand_in, p, self.words_model)
        wp["model"] = wp["params"].pop("model")
        calls += [lp, wp]
        if self.fix:
            calls += [dict(lp, expect_output=lp["expect_output"] // 2), dict(wp, expect_output=wp["expect_output"] // 2)]
        sheet = self._sheets().get(item.story)
        if sheet:
            calls.append(dict(model=self.judge, messages=self._coverage_messages(sheet["facts"], dict(beats=[
                dict(n=i + 1, say="A line of about twenty words " * 3) for i in range(9)])),
                params=dict(max_tokens=JUDGE_MAX_TOKENS, response_format=JUDGE_SCHEMA), expect_output=200))
            if sheet.get("who_says_so"):
                calls.append(dict(model=self.judge, messages=self._who_messages(sheet["note"], dict(beats=[
                    dict(n=i + 1, say="A line of about twenty words " * 3) for i in range(9)])),
                    params=dict(max_tokens=JUDGE_MAX_TOKENS, response_format=WHO_SCHEMA), expect_output=300))
        if self.plants:
            two = dict(beats=stand_in["beats"][:2])
            pp = sw.line_plan(two, p, facts, contexts, self.line_model)
            pp["model"] = pp["params"].pop("model")
            calls.append(pp)
        return calls

    # -- scoring --------------------------------------------------------------------------------
    def score(self, item: Item, output, key: dict) -> dict:
        s = output["script"]
        ch = s.get("checks") or {}
        first, final = ch.get("first") or {}, ch.get("final") or {}
        cov = output.get("coverage") or {}
        res = cov.get("results") or {}
        who = output.get("who_says") or {}
        pts = [x for x in who.get("points") or [] if x["mentioned"]]
        plants = output.get("plants") or []
        conf = {}
        for x in plants:
            got = "caught by code" if x["by_code"] and not x["by_line"] else x["verdict"]
            if not x["caught"]:
                got = "backed"
            conf[f"{x['kind']}->{got}"] = conf.get(f"{x['kind']}->{got}", 0) + 1
        loaded = lambda c: sum(1 for f in c.get("loaded") or [] if f["level"] == "loaded" and f["found"] and not f["quoted"])
        clean_first = bool(first) and not first.get("problems")
        return dict(
            status=s["status"], video=s["status"] != "no video", failed=s["status"] == "no video" and not first,
            clean_first=clean_first, fix_round=bool(s.get("fix_round")),
            rules_first=len(first.get("rules") or []), rules_final=len(final.get("rules") or []),
            on_screen_first=len(first.get("on_screen") or []), on_screen_final=len(final.get("on_screen") or []),
            lines_first=first.get("lines") or 0, backed_first=first.get("backed") or 0,
            lines_final=final.get("lines") or 0, backed_final=final.get("backed") or 0,
            lines_backed_first=_share(first.get("backed") or 0, first.get("lines") or 0),
            loaded_first=loaded(first), loaded_final=loaded(final),
            cuts=len(ch.get("cuts") or []), words=s.get("words") or 0, beats=len(s.get("beats") or []),
            warnings=len(final.get("warnings") or []),
            must=len(cov.get("must") or []), found=sum(1 for v in res.values() if v["found"]),
            who_points=len(pts), who_ok=sum(x["attributed"] for x in pts),
            plants=len(plants), plants_caught=sum(x["caught"] for x in plants),
            plants_line=sum(bool(x["by_line"]) for x in plants), confusion=conf,
            step_cost_usd=output.get("step_cost_usd") or 0.0, step_seconds=output.get("step_seconds") or 0.0,
            reason=s.get("reason") or "")

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        n = len(scores)
        vids = [s for s in scores if s.get("video")]
        drafted = [s for s in scores if not s.get("failed")]
        conf = {}
        for s in scores:
            for k, v in (s.get("confusion") or {}).items():
                conf[k] = conf.get(k, 0) + v
        return dict(
            first_clean=_share(sum(bool(s.get("clean_first")) for s in scores), n),
            videos=_share(len(vids), n),
            rules_final_ok=_share(sum(s.get("rules_final") == 0 for s in drafted), len(drafted)),
            on_screen_final_ok=_share(sum(s.get("on_screen_final") == 0 for s in drafted), len(drafted)),
            lines_backed_first=_share(tot("backed_first"), tot("lines_first")),
            lines_backed_final=_share(tot("backed_final"), tot("lines_final")),
            cut_beats=tot("cuts"), loaded_final=tot("loaded_final"), loaded_first=tot("loaded_first"),
            coverage=_share(tot("found"), tot("must")), who_says=_share(tot("who_ok"), tot("who_points")),
            plants_caught=_share(tot("plants_caught"), tot("plants")), plants_reached=tot("plants") - tot("plants_caught"),
            plants_line=_share(tot("plants_line"), tot("plants")), plants=tot("plants"),
            words=round(sum(s["words"] for s in vids) / len(vids), 1) if vids else None,
            step_cost=round(tot("step_cost_usd") / n, 4) if n else None,
            step_seconds=round(tot("step_seconds") / n, 1) if n else None,
            failures=sum(bool(s.get("failed")) for s in scores), fix_rounds=sum(bool(s.get("fix_round")) for s in scores),
            rules_first_total=tot("rules_first"), on_screen_first_total=tot("on_screen_first"), warnings=tot("warnings"),
            no_video={i.story: s.get("reason") for i, s in zip(items, scores) if not s.get("video")},
            confusion=conf,
            stories={i.story: s.get("lines_backed_first") for i, s in zip(items, scores)})

    # -- report ---------------------------------------------------------------------------------
    def story_names(self) -> dict[str, str]:
        out = {sid: sh["title"] for sid, sh in self._sheets().items()}
        for d in self.stories_dir.iterdir():
            if d.name[:8] not in out and (d / fact_check.CHECKED_FILE).exists():
                out[d.name[:8]] = ((fact_check.read_checked(d).get("event") or {}).get("title") or d.name[:8])
        return out

    def mistakes(self, rec: dict) -> list[dict]:
        out = []
        for row in rec.get("items_detail") or []:
            o = row.get("output") or {}
            s = o.get("script") or {}
            ch = s.get("checks") or {}
            st = row["story"]
            if s.get("status") == "no video":
                out.append(dict(story=st, kind="no video", title=s.get("event") or "", url=None, gold="a video",
                                pred="no video", reason=s.get("reason", ""), source="script"))
            for x in (ch.get("first") or {}).get("problems") or []:
                out.append(dict(story=st, kind=f"first draft: {x['rule']}", title=f"beat {x['beat']}" if x["beat"] else "the script",
                                url=None, gold="passes", pred="fails", reason=x["what"], source="first draft"))
            for x in (ch.get("final") or {}).get("problems") or [] if s.get("fix_round") else []:
                out.append(dict(story=st, kind=f"after the fix: {x['rule']}", title=f"beat {x['beat']}" if x["beat"] else "the script",
                                url=None, gold="passes", pred="fails", reason=x["what"], source="final draft"))
            for x in ch.get("cuts") or []:
                out.append(dict(story=st, kind=f"beat {x['became']}", title=f"beat {x['beat']}", url=None, gold="kept",
                                pred=x["became"], reason=x["why"], source="cuts"))
            for x in o.get("plants") or []:
                if not x["caught"]:
                    out.append(dict(story=st, kind=f"plant passed: {x['kind']}", title=x["planted"], url=None,
                                    gold="caught", pred=x["verdict"], reason=x.get("why") or f"was: {x['original']}",
                                    source="planted"))
            cov = o.get("coverage") or {}
            for i, m in enumerate(cov.get("must") or [], 1):
                r = (cov.get("results") or {}).get(f"M{i}")
                if r is not None and not r["found"]:
                    out.append(dict(story=st, kind="must-have not stated", title=m, url=None, gold="stated", pred="missing",
                                    reason="", source="coverage judge"))
            for x in (o.get("who_says") or {}).get("points") or []:
                if x["mentioned"] and not x["attributed"]:
                    out.append(dict(story=st, kind="said as fact", title=x["point"], url=None, gold="attributed",
                                    pred="as fact", reason=", ".join(x.get("lines") or []), source="who-says judge"))
        return out


def _beat_in(b: dict) -> dict:
    """A finished beat (script.json) back into the writer's beat shape, for planting."""
    raw = dict(shot=b["shot"], say=b["say"], claims=b.get("claims") or [], points=b.get("points") or [],
               broll_kind=(b.get("broll") or {}).get("kind") or "none", broll=(b.get("broll") or {}).get("name") or "")
    bl = b.get("blanks") or {}
    for k in sw.BEAT_FIELDS:
        if k in bl and k not in ("points",):
            raw[k] = bl[k]
    if b["shot"] == "sides":
        raw["points"] = [x["id"] if isinstance(x, dict) else x for x in bl.get("points") or b.get("points") or []]
    raw["card"] = bl.get("card", "")
    out = {k: raw.get(k, [] if k in sw.LIST_FIELDS else "") for k in sw.BEAT_FIELDS}
    out["blindspot"] = ""
    return out
