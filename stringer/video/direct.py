"""Step 1b: the voice director adds delivery tags to the lines, never words. On for every video (Jan, Nov 26:
"v4 turbo with expressive tags", after listening to the A/B).

Jan, Nov 26: "add an extra agent that takes in the speech ... leaving the entire speech as is just adding
those 11 lab flags that signify emotion."

The idea: ElevenLabs' expressive models (Eleven v3, v4 and v4 Turbo) read short bracketed tags as stage
directions, not words. "[serious] The bridge was hit overnight." is read seriously; the tag itself is not
spoken. The director is one cheap model call that gets the narrator's lines (the words the voice reads,
marks already taken out) and returns each line with a few tags put in. Then code checks every line:

  - take the tags out and the line must be the same, letter for letter (no word added, dropped or moved);
  - only tags from TAGS, at most MAX_PER_LINE in a line, no two tags in a row, none at the end of a line;
  - a line that gives one side's account (a sides or claim-vs-claim shot) gets only the NEUTRAL tags,
    so the narrator never sounds more doubtful of one side than the other.

A line that fails keeps no tags and is read as before; a failed call leaves every line untagged. So the
step can make the reading better but can never stop a video or change what it says.

    lines = direct(beats, title, complete)           # complete = models.complete-like callable
    lines["lines"][0] -> {"n": 1, "voice": "Ukraine says ...", "tagged": "[serious] Ukraine says ...", "ok": True}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import brief_read

STEP = "voice_direction"
DEFAULT_MODEL = "haiku-5-5"
MAX_PER_LINE = 2
MAX_TOKENS = 4000
CALL_TIMEOUT_S = 60

# The tags a calm news explainer may use. ElevenLabs' tag list is open-ended; this one is kept short and
# free of tags that take sides or add drama (no [skeptical], [sarcastic], [urgent], no sound effects).
NEUTRAL = ["calm", "measured", "matter-of-fact", "thoughtful", "short pause"]
TONE = ["serious", "somber", "curious", "warm", "emphatic", "long pause"]
TAGS = NEUTRAL + TONE
SIDE_SHOTS = {"sides", "claim_vs_claim"}

TAG = re.compile(r"\[([a-z][a-z' -]{0,30})\]")


def untag(tagged: str) -> tuple[str, list[int]]:
    """The line without its tags, and for every letter kept, its index in the tagged line.
    A tag goes with one space next to it, so "[calm] The bridge" and "hit. [calm] The" both come out clean."""
    drop = set()
    for m in TAG.finditer(tagged):
        drop.update(range(m.start(), m.end()))
        if m.end() < len(tagged) and tagged[m.end()] == " ":
            drop.add(m.end())
        elif m.start() > 0 and tagged[m.start() - 1] == " ":
            drop.add(m.start() - 1)
    keep = [i for i in range(len(tagged)) if i not in drop]
    return "".join(tagged[i] for i in keep), keep


def tags_in(tagged: str) -> list[str]:
    return [m.group(1) for m in TAG.finditer(tagged)]


def line_problems(voice_line: str, tagged: str, shot: str) -> list[str]:
    """Why a tagged line can't be used (empty when it can)."""
    probs = []
    plain, _ = untag(tagged)
    if plain != voice_line:
        probs.append("the words changed")
    found = tags_in(tagged)
    bad = [t for t in found if t not in TAGS]
    if bad:
        probs.append(f"tags not on the list: {', '.join(bad)}")
    if len(found) > MAX_PER_LINE:
        probs.append(f"{len(found)} tags (at most {MAX_PER_LINE})")
    if re.search(r"\]\s*\[", tagged):
        probs.append("two tags in a row")
    if found and re.search(r"\]\s*$", tagged):
        probs.append("a tag at the end of the line")
    if shot in SIDE_SHOTS and any(t not in NEUTRAL for t in found):
        probs.append("a side's line may only have the neutral tags")
    if "[" in TAG.sub("", tagged) or "]" in TAG.sub("", tagged):
        probs.append("a stray bracket")
    return probs


STYLES = {
    # the first try (Nov 26): calm throughout, a tag only where the tone shifts
    "steady": f"""- Most lines need one tag or none. A steady, calm reading is the goal: use [somber] only for deaths and injuries,
  [emphatic] only for the one number or fact the story turns on, [warm] only for good news.""",
    # for Jan's ear test: more colour, same limits and the same fairness rule
    "expressive": f"""- Give the reading more colour than a flat newsreader: let the tone follow what each line is about. Use [serious]
  for stakes and threats, [somber] for deaths and injuries, [curious] for open questions and puzzles, [warm] for good
  news or human moments, [emphatic] for the number or fact the story turns on, [short pause] before a turn.
  Keep it natural: a tag where the tone changes, not on every sentence.""",
}


STYLE = "expressive"          # Jan's pick, Nov 26


def system(style: str = STYLE) -> str:
    return f"""You direct the narrator of a 60-second neutral news explainer video.
You get the narrator's lines as JSON, numbered. Return every line with a few delivery tags put in, so the voice reads it
with the right tone. The tags are stage directions in square brackets; the voice does not say them.

Rules:
- Never change a line's words or punctuation: no word added, removed, reordered or respelled. Only insert tags.
- Use only these tags: {", ".join(f"[{t}]" for t in TAGS)}.
- Put a tag right before the words it colours, at the start of the line or of a sentence. At most {MAX_PER_LINE} tags in a line, never two in a row, never at the end.
- Line 1 opens the video: give it one tag that sets the tone of the whole story.
{STYLES[style]}
- Lines with "side": true give one side's account. They get only {", ".join(f"[{t}]" for t in NEUTRAL)}, and the
  same kind of tag for each side, so the narrator never sounds more doubtful of one side than the other.

Answer with JSON only: {{"lines": [{{"n": 1, "line": "the line with its tags"}}, ...]}}"""


def messages(beats: list[dict], title: str, style: str = STYLE) -> list[dict]:
    # the lines go in as JSON, so a label like "side" can't be mistaken for part of a line (it was, Nov 26)
    rows = [dict(n=i, side=b.get("shot") in SIDE_SHOTS, line=b["voice"]) for i, b in enumerate(beats, 1)]
    user = f"Story: {title}\n\nLines:\n" + json.dumps(rows, ensure_ascii=False, indent=0)
    return [{"role": "system", "content": system(style)}, {"role": "user", "content": user}]


def schema() -> dict:
    line = {"type": "object", "additionalProperties": False, "required": ["n", "line"],
            "properties": {"n": {"type": "integer"}, "line": {"type": "string"}}}
    return {"type": "json_schema", "json_schema": {"name": "direction", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["lines"],
        "properties": {"lines": {"type": "array", "items": line}}}}}


def _parse(text: str) -> dict[int, str] | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None
    if not isinstance(d, dict) or not isinstance(d.get("lines"), list):
        return None
    out = {}
    for x in d["lines"]:
        if isinstance(x, dict) and isinstance(x.get("n"), int) and isinstance(x.get("line"), str):
            out[x["n"]] = x["line"].strip()
    return out or None


def model_call(messages, name=None, model=None, trace_id=None, **params):
    """The live call: models.complete with the model config/models.toml names for this step."""
    from .. import models
    return models.complete(STEP, messages, model=model, name=name, metadata=dict(module=8), trace_id=trace_id,
                           **params)


def model_for() -> str:
    from .. import models
    try:
        return models.model_for(STEP)
    except KeyError:
        return DEFAULT_MODEL


def reuse(path: Path, beats: list[dict], model: str | None = None, style: str = STYLE) -> dict | None:
    """The direction written last time for exactly these lines (same model and style), else None.
    A re-render then reads the same tagged text, so the saved recording is used and no voice credits are spent;
    a fresh direction would tag differently and need a new recording every time."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not d.get("answered") or d.get("style") != style or d.get("model") != (model or model_for()):
        return None
    if [x.get("voice") for x in d.get("lines") or []] != [b["voice"] for b in beats]:
        return None
    return dict(d, reused=True)


def direct(beats: list[dict], title: str, complete=None, model: str | None = None, style: str = STYLE) -> dict:
    """Every beat's line, tagged where the director's tags pass the checks (else as it was)."""
    complete = complete or model_call
    model = model or model_for()
    params = dict(model=model, max_tokens=MAX_TOKENS, response_format=schema(), timeout=CALL_TIMEOUT_S)
    msgs = messages(beats, title, style)
    got, calls, errors = None, 0, []
    for attempt in range(2):
        m = msgs if attempt == 0 else msgs + [{"role": "user", "content": brief_read.RETRY_JSON}]
        text, err = brief_read._call(complete, m, params, "voice direction" if attempt == 0 else "voice direction retry")
        calls += 1
        if err:
            errors.append(err)
        got = _parse(text)
        if got is not None:
            break
    lines = []
    for i, b in enumerate(beats, 1):
        tagged = (got or {}).get(i, b["voice"])
        probs = line_problems(b["voice"], tagged, b.get("shot") or "") if got else []
        ok = not probs
        lines.append(dict(n=b.get("n", i), shot=b.get("shot"), voice=b["voice"], tagged=tagged if ok else b["voice"],
                          asked=tagged, ok=ok, problems=probs, tags=tags_in(tagged) if ok else []))
    return dict(model=model, style=style, calls=calls, errors=errors, answered=got is not None, lines=lines,
                tags=sum(len(x["tags"]) for x in lines), refused=sum(1 for x in lines if not x["ok"]))
