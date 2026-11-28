"""The custom animation's model steps and the code between them (design: Nov 27 test rounds; build Nov 28).

  1. candidates (code): the checked script's beats a window fits under and long enough to play in;
  2. storyboard (Haiku, low effort): reads module 7's packet (the checked research file) and those beats, picks one
     (an enum of their numbers) and plans the moment its sentence tells, its cues and what it needs from the library
     (each thing a catalogue name or "none", schema-enforced);
  3. drawing (Sonnet): writes draw(k, p, cues) with the kit; things matched to "none" it draws itself;
  4. cue words (Haiku, low effort, beside the drawing): one spoken word of the beat for each cue, from an enum of
     the beat's words;
  5. cue times (code): each cue word's start in the recorded voice, as a share of the beat, then spaced (in
     storyboard order, at least 0.12 apart, between 0.08 and 0.85: round 5 fired two cues on one word).

The steps start once the script is checked (fix 2, Nov 28: planned beside the writer, the storyboard guessed which
moment the script would tell, and 2 of 4 stories fell back because no beat cited its claims), and never change the
writer's prompt, so the script is the same with the animation on or off. With no beat a window fits under, nothing
is paid. Every model answer must parse and fit its schema: the shape is enforced, the token limit is large, a bad
answer is asked once more, and a step that still fails falls back (no storyboard or no drawing: the beat keeps its
normal shot; no cue words: the cues are spread evenly). Answers are cached on disk under their request, so the same
story is never paid for twice (paths.PRIVATE/video_cache/animation/).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .. import brief_read, paths, script_writer as sw
from . import guide, library

STORYBOARD, DRAWING, CUES = "anim_storyboard", "anim_drawing", "anim_cues"     # steps in config/models.toml
DEFAULT_MODELS = {STORYBOARD: "haiku-5-5", DRAWING: "sonnet-5-5", CUES: "haiku-5-5"}
MAX_TOKENS = {STORYBOARD: 16000, DRAWING: 32000, CUES: 8000}
EFFORT = {STORYBOARD: "low", CUES: "low"}
TIMEOUT_S = {STORYBOARD: 120, DRAWING: 300, CUES: 60}
CACHE = paths.PRIVATE / "video_cache" / "animation"
MAX_CUES = 3

# Shots a window fits under: their words keep to the top, smaller, and the window takes the room below
# (render/src/anim.js; each shot's compact layout shows the same words, so the captions rule in plan.py holds).
# Not the hook (its map is the video's opening), sides, sources, timeline and quote (their words need the whole
# card), claim_vs_claim (two accounts that disagree: no picture should side with one), a big number with a
# comparison (its two bars need the card) or a tally of more than 3 rows.
ELIGIBLE = ("headline", "map_locate", "map_link", "map_spread", "big_number", "document", "tally")
TALLY_ROWS = 3


def window_fits(b: dict) -> bool:
    """Whether this beat's shot keeps a compact layout with a window under it (render/src/anim.js)."""
    bl = b.get("blanks") or {}
    if b.get("shot") not in ELIGIBLE:
        return False
    if b["shot"] == "big_number" and bl.get("compare_value"):
        return False
    return not (b["shot"] == "tally" and len(bl.get("rows") or []) > TALLY_ROWS)
MIN_SECONDS = 3.5           # a shorter beat is no place for a 3-part animation

CUE_GAP, CUE_LO, CUE_HI = 0.12, 0.08, 0.85


def model_for(step: str) -> str:
    try:
        from .. import models
        return models.model_for(step)
    except (KeyError, FileNotFoundError):
        return DEFAULT_MODELS[step]


def default_complete(trace_id: str | None = None):
    """models.complete with each step's model from config/models.toml, joined to the video's trace."""
    def complete(messages, name=None, step=None, **params):
        from .. import models
        return models.complete(step, messages, name=name, trace_id=trace_id, metadata=dict(module=8, part="animation"),
                               **params)
    return complete


# ---- one JSON answer: enforced shape, large limit, one retry, cached ----

def _key(model: str, messages: list[dict], schema: dict) -> str:
    raw = json.dumps(dict(model=model, messages=messages, schema=schema), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def ask_json(step: str, messages: list[dict], schema: dict, complete, *, check=None, cache: Path | None = CACHE,
             name: str | None = None) -> tuple[dict | None, dict]:
    """(the answer, its record) or (None, its record). check(d) -> problem or "" (a problem counts as a bad answer)."""
    model = model_for(step)
    rec = dict(step=step, model=model, calls=0, usd=0.0, seconds=0.0, cached=False, error=None)
    path = Path(cache) / step / f"{_key(model, messages, schema)}.json" if cache else None
    if path and path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        rec.update(cached=True, usd_first=saved.get("usd"), seconds_first=saved.get("seconds"))
        return saved["answer"], rec
    params = dict(model=model, max_tokens=MAX_TOKENS[step], response_format=schema, timeout=TIMEOUT_S[step])
    if step in EFFORT:
        params["reasoning_effort"] = EFFORT[step]
    t0, text, problem = time.time(), "", ""
    for attempt in range(2):
        msgs = messages if attempt == 0 else messages + ([{"role": "assistant", "content": text}] if text else []) + [
            {"role": "user", "content": brief_read.RETRY_JSON + (f" Problem: {problem}" if problem else "")}]
        rec["calls"] += 1
        try:
            r = complete(msgs, name=f"{name or step}{' retry' if attempt else ''}", step=step, **params)
            text = r.text or ""
            rec["usd"] += float((getattr(r, "cost", None) or {}).get("total") or 0)
        except Exception as e:                       # a failed call counts as an empty answer; the retry follows
            if type(e).__name__ == "BudgetExceeded":
                raise
            text, rec["error"] = "", f"{type(e).__name__}: {e}"[:300]
            continue
        d = sw._json(text)
        problem = "the answer is not a JSON object" if not isinstance(d, dict) else (check(d) if check else "")
        if not problem:
            rec.update(seconds=round(time.time() - t0, 2), usd=round(rec["usd"], 5), error=None)
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(dict(answer=d, usd=rec["usd"], seconds=rec["seconds"], model=model),
                                           ensure_ascii=False), encoding="utf-8")
            return d, rec
        rec["error"] = problem
    rec.update(seconds=round(time.time() - t0, 2), usd=round(rec["usd"], 5))
    return None, rec


# ---- 2. storyboard ----

def cue_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())[:20] or "cue"


def clean_storyboard(sb: dict, claim_ids, beats: list[dict] | None = None) -> dict:
    """The picked beat (its index into beats, its number, its sentence and its known claim ids); cue names made plain
    and unique (at most 3, in order); needs kept as given. Without beats (an older storyboard), claims as given."""
    names, cues = set(), []
    for c in sb.get("cues") or []:
        if not isinstance(c, dict):
            continue
        n = cue_name(c.get("name"))
        while n in names:
            n += "x"
        names.add(n)
        cues.append(dict(name=n, what=str(c.get("what") or "")))
    needs = [dict(thing=str(x.get("thing") or ""), piece=x.get("piece") if x.get("piece") in library.pieces() else library.NONE)
             for x in sb.get("needs") or [] if isinstance(x, dict)]
    picked = {}
    if beats is not None:
        i = next(k for k, b in enumerate(beats) if str(b.get("n", k + 1)) == str(sb.get("beat")))
        b = beats[i]
        picked = dict(index=i, beat=b.get("n", i + 1), line=b.get("voice") or "", claims=list(b.get("claims") or []))
    claims = picked.pop("claims", None) if picked else list(map(str, sb.get("claims") or []))
    return dict(**picked, claims=[c for c in dict.fromkeys(map(str, claims)) if c in set(claim_ids)],
                show=str(sb.get("show") or "").strip(), agreed=str(sb.get("agreed") or ""), avoid=str(sb.get("avoid") or ""),
                cues=cues[:MAX_CUES], needs=needs)


def beat_list(beats: list[dict], idx: list[int]) -> str:
    """The beats the storyboard may pick, as it reads them: number, shot, the claims cited, the sentence."""
    return "\n".join(f"Beat {beats[i].get('n', i + 1)} ({beats[i].get('shot')}; cites {', '.join(beats[i].get('claims') or []) or 'nothing'}): "
                     f"{beats[i].get('voice') or ''}" for i in idx)


def storyboard(packet_text: str, claim_ids, beats: list[dict], idx: list[int], complete,
               cache: Path | None = CACHE) -> tuple[dict | None, dict]:
    """The plan for the beats at idx (candidates()): the beat it picks and the moment its sentence tells."""
    def check(d):
        return "" if str(d.get("show") or "").strip() else "show is empty"
    nums = [str(beats[i].get("n", i + 1)) for i in idx]
    user = (packet_text + "\n\nTHE SCRIPT'S BEATS THAT CAN HOLD THE ANIMATION (pick one)\n" + beat_list(beats, idx))
    msgs = [{"role": "system", "content": guide.STORYBOARD_SYSTEM}, {"role": "user", "content": user}]
    d, rec = ask_json(STORYBOARD, msgs, guide.storyboard_schema(nums), complete, check=check, cache=cache,
                      name="animation storyboard")
    return (clean_storyboard(d, claim_ids, beats) if d else None), rec


def missing(sb: dict) -> list[str]:
    """The things the library lacks, which the drawing model draws itself."""
    return [x["thing"] for x in sb.get("needs") or [] if x.get("piece") == library.NONE and x.get("thing")]


# ---- 3. drawing ----

def drawing(sb: dict, packet_text: str, complete, cache: Path | None = CACHE) -> tuple[dict | None, dict]:
    def check(d):
        return "" if "function draw" in str(d.get("code") or "") else "code must define function draw(k, p, cues)"
    board = {k: v for k, v in sb.items() if k not in ("needs", "index")}
    msgs = [{"role": "system", "content": guide.draw_system(missing(sb))},
            {"role": "user", "content": "STORYBOARD\n" + json.dumps(board, ensure_ascii=False, indent=1)
             + "\n\nTHE CHECKED RESEARCH FILE\n" + packet_text}]
    return ask_json(DRAWING, msgs, guide.DRAW_SCHEMA, complete, check=check, cache=cache, name="animation drawing")


# ---- 1. the candidates (and a beat's words) ----

def beat_words(beat: dict) -> list[str]:
    """The beat's spoken words, split as the voice's timings split them (voice.words_of: on whitespace)."""
    return re.findall(r"\S+", beat.get("voice") or "")


def candidates(beats: list[dict]) -> tuple[list[int], str]:
    """(indexes into beats, why there are none). The beats a window fits under and long enough to play in."""
    fits = [i for i, b in enumerate(beats) if window_fits(b)]
    if not fits:
        return [], "no beat is a shot a window fits under"
    long = [i for i in fits if len(beat_words(beats[i])) / 2.6 >= MIN_SECONDS]   # module 7's pace: 2.6 words a second
    return (long, "") if long else ([], "the beats a window fits under are too short")


# ---- 4. cue words ----

def place_cues(sb: dict, beat: dict, complete, cache: Path | None = CACHE) -> tuple[dict, dict]:
    """{cue name: index of its word in the beat}, in storyboard order with rising indexes, or {} on failure."""
    words = beat_words(beat)
    names = [c["name"] for c in sb.get("cues") or []]
    if not names or not words:
        return {}, dict(step=CUES, calls=0, usd=0.0, cached=False, error="no cues or no words")
    tokens = guide.numbered(words)

    def check(d):
        idx = [tokens.index(d[n]) if d.get(n) in tokens else -1 for n in names]
        if -1 in idx:
            return "every cue needs one of the numbered words"
        return ""
    lines = "\n".join(f"- {c['name']}: {c['what']}" for c in sb["cues"])
    user = (f"THE ANIMATION\n{sb['show']}\n\nTHE CUES, in the order they happen\n{lines}\n\n"
            f"THE LINE, word by word\n" + "\n".join(tokens))
    msgs = [{"role": "system", "content": guide.CUES_SYSTEM}, {"role": "user", "content": user}]
    d, rec = ask_json(CUES, msgs, guide.cues_schema(names, words), complete, check=check, cache=cache, name="animation cue words")
    if not d:
        return {}, rec
    return {n: tokens.index(d[n]) for n in names}, rec


# ---- 5. cue times ----

def cue_times(placed: dict, names: list[str], beat_words_timed: list[dict], start: float, end: float) -> dict:
    """{name: share of the beat} from each placed word's start in the voice; a cue with no word gets an even slot.
    beat_words_timed: the voice's words of this beat ({w, start, end} in seconds), in order."""
    span = max(1e-6, end - start)
    out = {}
    for i, n in enumerate(names):
        k = placed.get(n)
        if k is not None and 0 <= k < len(beat_words_timed):
            out[n] = round(min(1.0, max(0.0, (beat_words_timed[k]["start"] - start) / span)), 3)
        else:
            out[n] = round((i + 1) / (len(names) + 1), 3)
    return out


def space_cues(cues: dict, names: list[str], gap: float = CUE_GAP, lo: float = CUE_LO, hi: float = CUE_HI) -> dict:
    """Cue times in storyboard order, at least `gap` apart, inside [lo, hi] (round 6: so two things never fire on the
    same word and nothing happens before the scene is set or too late to be seen)."""
    keys = [k for k in dict.fromkeys(names) if k in cues]
    if not keys:
        return dict(cues)
    gap = min(gap, (hi - lo) / max(1, len(keys) - 1))
    t = [min(max(cues[k], lo), hi) for k in keys]
    for i in range(1, len(t)):
        t[i] = max(t[i], t[i - 1] + gap)
    if t[-1] > hi:
        t[-1] = hi
        for i in range(len(t) - 2, -1, -1):
            t[i] = min(t[i], t[i + 1] - gap)
    return {**cues, **{k: round(v, 3) for k, v in zip(keys, t)}}
