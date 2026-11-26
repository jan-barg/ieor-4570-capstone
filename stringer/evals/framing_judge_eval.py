"""A judge for step 4's points on how each side tells it (module 5), graded against Jan.

    python -m scripts.run_eval run framing_judge --model gemini-3.5-flash-lite --split all --cap <approved>
    python -m scripts.run_eval rescore framing_judge <run id>        # after new grades from Jan, free
    (--opt judge_prompt=fjudge-1 for the first prompt, which wanted a voices point to quote someone's words)

Input: each two-side story's points as the Story File holds them (story_file.json "perspectives"),
plus exactly what step 4 saw when it wrote them: every article's outlet, headline, opening and
words used, and the claims only that side reports (rebuilt with brief_framing.groups_for). One call
per story grades every point "good" or "weak", with the test it fails:
  specific   says something concrete (which words, what it leads with, whose words, who is blamed)
  contrast   the other side tells it differently (not the same words or the same stress)
  quotes     the quotes, read where they appear, show it (for a voices point, the names of the
             sources it relies on are enough; words a side reports from the other camp aren't its own)
  neutral    it describes, without judging which side is right
The judge is from another model family than step 4 (Sonnet).

Answer key: Jan's grades, stringer_private/story_file_design/framing/grades_jan.json, written from
the grading page: {"stories": {story: {"<side_id>#<n>": {"grade": "good"|"weak", "point": ...}}}}.
Stories Jan hasn't graded still get judged; agreement counts only graded points.

Scores:
  agreement          points where the judge and Jan give the same grade, of the points Jan graded
  judge_good_share   points the judge calls good, all stories
  jan_good_share     points Jan calls good
  judge_kinder       Jan weak, judge good (the misses that matter: a weak point would pass)
  judge_harsher      Jan good, judge weak
  ungraded           points the judge gave no grade (a judge slip; must stay 0)
  stories_failed     stories with no usable judge answer after one retry (must stay 0)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import brief_framing, brief_read, paths, story_file
from .brief_framing_eval import BriefFramingEval
from .brief_read_eval import JUDGE_MAX_TOKENS
from .runner import Item

VERSION = "fjudge-2"      # the default since Nov 25 (Jan: "Yes, switch"): a voices point may quote just the names of
                           # its sources, as Jan graded; fjudge-1 required someone's words (29 vs 28 of 36 agree)
GRADES = paths.PRIVATE / "story_file_design" / "framing" / "grades_jan.json"
FAILS = ("specific", "contrast", "quotes", "neutral")

SYSTEM = """You check points that describe how one side's news outlets tell a story differently from the other side. A writer read what you see below (each side's articles: outlet, headline, opening sentence and the words it uses; and the claims only that side reports, which are our own neutral summaries, not the outlets' words) and wrote the points. Each point has a kind (word choice, emphasis, voices, blame or credit) and quotes that should show it.

Grade every point "good" or "weak". A point is good only when all four hold:
- specific: it says something concrete about how the side tells it: which words, what it leads with or plays down, whose words it relies on, who it blames or credits. "Uses official terms" or "focuses on the event" is not specific.
- contrast: the other side tells it differently. Check the other side's articles: if they use the same words or stress the same thing, it is not a contrast. A difference between two outlets of the same side is not a contrast between sides.
- quotes: the quotes, read in their article, show the point. A voices point needs quotes showing someone's words being used, not only a name or a title. Words a side reports from the other camp (in quotation marks, or "what X calls") are not that side's own words.
- neutral: it describes how the side tells it, without saying which side is right.

For each point give its id, the grade, the first test it fails ("" if good), and why in one short sentence. Grade every point. Answer with JSON only: {"grades": [...]}."""


SYSTEM_2 = SYSTEM.replace(
    "A voices point needs quotes showing someone's words being used, not only a name or a title. ",
    "For a voices point, quoting the names or titles of the people or bodies the side relies on is enough. ")
assert SYSTEM_2 != SYSTEM
PROMPTS = {"fjudge-1": SYSTEM, "fjudge-2": SYSTEM_2}


def schema(ids: list[str]) -> dict:
    g = {"type": "object", "additionalProperties": False, "required": ["id", "grade", "fails", "why"],
         "properties": {"id": {"type": "string", "enum": ids}, "grade": {"type": "string", "enum": ["good", "weak"]},
                        "fails": {"type": "string", "enum": [""] + list(FAILS)}, "why": {"type": "string"}}}
    return {"type": "json_schema", "json_schema": {"name": "framing_grades", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["grades"],
        "properties": {"grades": {"type": "array", "items": g}}}}}


def points_of(perspectives: list[dict]) -> list[dict]:
    """The Story File's points in order, each with its id (P1..) and key ("<side_id>#<n>", n from 1)."""
    out = []
    for s in perspectives or []:
        for n, p in enumerate(s.get("points") or [], 1):
            out.append(dict(id=f"P{len(out) + 1}", key=f"{s['side_id']}#{n}", side_id=s["side_id"], side=s["label"],
                            kind=p["kind"], point=p["point"], quotes=p.get("quotes") or []))
    return out


def messages_for(body: str, points: list[dict], label_of: dict, letter_of: dict, prompt: str = VERSION) -> list[dict]:
    """body: the user message step 4 got. label_of: {article id: "A1"}; letter_of: {side_id: "A"}."""
    lines = []
    for p in points:
        lines.append(f"{p['id']} [side {letter_of.get(p['side_id'], '?')}: {p['side']}; {p['kind']}] {p['point']}")
        for q in p["quotes"]:
            en = f" (English: {q['words_en']})" if q.get("words_en") else ""
            lines.append(f"   - {label_of.get(q['article'], '?')} {q.get('outlet') or ''}: \"{q['words']}\"{en}")
    return [{"role": "system", "content": PROMPTS[prompt]},
            {"role": "user", "content": f"What the writer saw:\n\n{body}\n\nPoints to grade ({len(points)}):\n" + "\n".join(lines)}]


def _parse(text: str | None, ids: set) -> dict | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("grades"), list):
        return None
    got = {}
    for x in d["grades"]:
        if isinstance(x, dict) and x.get("id") in ids and x["id"] not in got and x.get("grade") in ("good", "weak"):
            fails = x.get("fails") if x.get("fails") in FAILS else ""
            got[x["id"]] = dict(grade=x["grade"], fails="" if x["grade"] == "good" else fails, why=str(x.get("why", ""))[:300])
    return got


def judge(messages: list[dict], ids: list[str], complete, *, name: str = "framing_judge") -> dict:
    """{"grades": {id: {grade, fails, why}}, "calls", "error"}. One retry on an unusable answer or on
    missing grades (naming them); the more complete answer is kept."""
    params = dict(max_tokens=JUDGE_MAX_TOKENS * 2, response_format=schema(ids), timeout=brief_read.CALL_TIMEOUT_S)
    want, best, errs, calls = set(ids), None, [], 0
    for attempt in range(2):
        msgs = messages
        if attempt:
            missing = [i for i in ids if i not in (best or {})]
            note = brief_read.RETRY_JSON if best is None else f"Grade every point; these are missing: {', '.join(missing)}. Answer again with all of them, JSON only."
            msgs = messages + [{"role": "user", "content": note}]
        text, err = brief_read._call(complete, msgs, params, name if attempt == 0 else f"{name} retry")
        calls += 1
        if err:
            errs.append(err)
        got = _parse(text, want)
        if got is not None and (best is None or len(got) > len(best)):
            best = got
        if best is not None and len(best) == len(want):
            break
    if best is None:
        return dict(grades={}, calls=calls, error="no usable framing judge answer after one retry" + (f" ({errs[-1]})" if errs else ""))
    return dict(grades=best, calls=calls, error=None)


def load_grades(path: Path = GRADES) -> dict:
    """{story: {key: "good"|"weak"}} from Jan's grading page; {} when there are none yet."""
    if not Path(path).exists():
        return {}
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s: {k: v["grade"] for k, v in pts.items() if v.get("grade") in ("good", "weak")}
            for s, pts in (d.get("stories") or {}).items()}


class FramingJudgeEval(BriefFramingEval):
    name = "framing_judge"
    model_step = None
    headline = ("agreement", "judge_good_share", "jan_good_share", "judge_kinder", "judge_harsher", "ungraded", "stories_failed")
    report_title = "Story File: a judge for how each side tells it"
    report_intro = ("A judge from another model family than step 4 (Sonnet) grades every point on how each side tells "
                    "the story: good only if it is specific, a real contrast with the other side, shown by its quotes, "
                    "and neutral. It sees what step 4 saw. Its grades are compared with Jan's on the stories Jan graded.")
    metric_notes = {
        "agreement": ("Agrees with Jan", "Points where the judge gives Jan's grade, of the points Jan graded."),
        "judge_good_share": ("Judge: good", "Share of all points the judge calls good."),
        "jan_good_share": ("Jan: good", "Share of Jan's graded points Jan calls good."),
        "judge_kinder": ("Judge kinder", "Jan weak, judge good: a weak point would pass."),
        "judge_harsher": ("Judge harsher", "Jan good, judge weak."),
        "ungraded": ("Ungraded points", "Points the judge gave no grade. Must be 0."),
        "stories_failed": ("Failed stories", "No usable judge answer after one retry. Must be 0."),
    }

    def __init__(self, n=None, stories_dir=None, sheets=None, merge=None, merge_version=None, runs_dir=None,
                 grades=None, judge_prompt=None):
        super().__init__(n=n, stories_dir=stories_dir, sheets=sheets, merge=merge, merge_version=merge_version,
                         runs_dir=runs_dir)
        self.grades_path = Path(grades or GRADES)
        self.judge_prompt = judge_prompt or VERSION
        if self.judge_prompt not in PROMPTS:
            raise ValueError(f"unknown judge prompt {self.judge_prompt}; known: {', '.join(PROMPTS)}")
        self.version = f"{self.judge_prompt}-{story_file.VERSION}-{brief_framing.VERSION}-{self.merge_version}"

    def load_key(self) -> dict:
        return load_grades(self.grades_path)

    def key_version(self) -> str:
        g = self.load_key()
        return f"Jan's grades: {sum(len(v) for v in g.values())} points on {len(g)} stories"

    def _call_input(self, item: Item):
        """(messages, points) or (None, reason)."""
        sf = story_file.read(Path(item.data["dir"]))[1]
        points = points_of(sf.get("perspectives"))
        if not points:
            return None, "no points (no two sides, or both sides empty)"
        sides, step1, arts, event = self._inputs(item)
        if sides.get("error"):
            return None, sides["error"]
        outlets, framing = brief_framing.outlets_and_framing(sides, step1)
        groups, _ = brief_framing.groups_for(sides, arts)
        msgs, labels = brief_framing.messages_for(event, groups, framing, outlets)
        label_of = {aid: lab for lab, aid in labels.items()}
        letter_of = {g["side_id"]: k for k, g in groups.items()}
        return messages_for(msgs[1]["content"], points, label_of, letter_of, self.judge_prompt), points

    def run(self, item: Item, ctx):
        msgs, points = self._call_input(item)
        if msgs is None:
            return dict(points=[], skipped=points)
        complete = lambda m, name=None, **p: ctx.complete(m, name=name, **p)
        res = judge(msgs, [p["id"] for p in points], complete)
        for p in points:
            p.update(res["grades"].get(p["id"]) or dict(grade=None, fails="", why=""))
        return dict(points=points, calls=res["calls"], error=res["error"])

    def plan(self, item: Item, model: str) -> list[dict]:
        msgs, points = self._call_input(item)
        if msgs is None:
            return []
        ids = [p["id"] for p in points]
        return [dict(messages=msgs, params=dict(max_tokens=JUDGE_MAX_TOKENS * 2, response_format=schema(ids)),
                     expect_output=60 * len(ids) + 200)]

    def score(self, item: Item, output, key: dict) -> dict:
        pts = output.get("points") or []
        jan = (key or {}).get(item.story) or {}
        both = [(p["grade"], jan[p["key"]]) for p in pts if p["key"] in jan and p.get("grade")]
        return dict(points=len(pts), judged=sum(bool(p.get("grade")) for p in pts),
                    judge_good=sum(p.get("grade") == "good" for p in pts), ungraded=sum(not p.get("grade") for p in pts),
                    jan=len(both), jan_good=sum(j == "good" for _, j in both), agree=sum(a == j for a, j in both),
                    kinder=sum(a == "good" and j == "weak" for a, j in both),
                    harsher=sum(a == "weak" and j == "good" for a, j in both),
                    fails={f: sum(p.get("fails") == f for p in pts) for f in FAILS},
                    failed=bool(output.get("error")))

    def summarize(self, items: list[Item], scores: list[dict]) -> dict:
        tot = lambda k: sum(s.get(k) or 0 for s in scores)
        jan, judged = tot("jan"), tot("judged")
        return dict(agreement=round(tot("agree") / jan, 3) if jan else None, jan_points=jan,
                    judge_good_share=round(tot("judge_good") / judged, 3) if judged else None,
                    jan_good_share=round(tot("jan_good") / jan, 3) if jan else None,
                    judge_kinder=tot("kinder"), judge_harsher=tot("harsher"), points=tot("points"),
                    ungraded=tot("ungraded"), stories_failed=tot("failed"),
                    fails={f: sum((s.get("fails") or {}).get(f, 0) for s in scores) for f in FAILS},
                    stories={i.story: s.get("points") for i, s in zip(items, scores)})

    def mistakes(self, rec: dict) -> list[dict]:
        """Every weak grade and every disagreement with Jan, for the hand check."""
        key = self.load_key()
        out = []
        for r in rec.get("items_detail") or []:
            jan = key.get(r["story"]) or {}
            for p in (r.get("output") or {}).get("points") or []:
                j = jan.get(p["key"])
                if p.get("grade") == "weak" or (j and j != p.get("grade")):
                    q = "; ".join(f"{x.get('outlet')}: “{x['words']}”" for x in p["quotes"])
                    out.append(dict(story=r["story"], kind=f"judge {p.get('grade')}" + (f", Jan {j}" if j else ""),
                                    title=p["point"], url=None, gold=f"{p['side']} · {p['kind']}", pred=q,
                                    reason=(f"fails {p['fails']}: " if p.get("fails") else "") + (p.get("why") or ""),
                                    source=p["key"]))
        return out
