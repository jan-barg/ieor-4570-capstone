"""Step 1: check the script before anything is voiced or drawn.

Module 7 already checked its script; this is the last guard before the render (settled Nov 26):
  - a "no video" script stops here;
  - every beat's shot, blanks and word marks must fit the shared catalog (config/shot_catalog.json);
  - the on-screen check runs again, the same code module 7 runs (numbers from the beat's cited claims,
    names from the story, quotes letter for letter), and the quote a quote shot draws must be its card's
    evidence quote;
  - the text sent to the voice may hold no [ or ] at all.

A beat that fails becomes a headline card. Its title is kept only when the title itself passes the
on-screen check; otherwise the card carries no words of its own (only its picture and the captions), so
nothing unchecked reaches the screen. A failing hook or sources beat means no video. Every swap is listed.

    out = check_script(script, packet)
    out["stop"]   -> None, or why there is no video
    out["beats"]  -> the beats to draw (script.json beat shape, swaps applied)
    out["swaps"]  -> [{"beat": 3, "shot": "tally", "became": "headline", "title_kept": False, "why": "..."}]
"""
from __future__ import annotations

import copy

from .. import script_writer as sw
from .. import shots

ESSENTIAL = ("hook", "sources")
PLACE_KINDS = ("point", "province", "country", "sea")


def internal(b: dict) -> dict:
    """A script.json beat in the flat shape module 7's checks read (blanks at the top level)."""
    bl = b.get("blanks") or {}
    spec = shots.catalog()["shots"].get(b.get("shot"), {"blanks": {}})
    d = {k: copy.deepcopy(bl.get(k, [] if k in ("places", "accounts", "rows", "steps", "points") else ""))
         for k in spec["blanks"]}
    d.update(shot=b.get("shot"), say=b.get("say") or "", claims=list(b.get("claims") or []),
             points=list(b.get("points") or []), broll_kind=(b.get("broll") or {}).get("kind") or "none",
             broll=(b.get("broll") or {}).get("name") or "")
    return d


def _shape_problems(b: dict) -> list[str]:
    """Types and kinds the drawing code relies on, beyond module 7's blank rules."""
    out = []
    sh = b["shot"]
    if sh.startswith("map_") and any(not isinstance(x, str) or not x.strip() for x in b["places"]):
        out.append("a place name is empty")
    if sh == "map_locate" and b["place_kind"] not in PLACE_KINDS:
        out.append(f"place kind \"{b['place_kind']}\" is not one of {', '.join(PLACE_KINDS)}")
    if sh == "tally" and any(not isinstance(r, dict) or not r.get("label") or not str(r.get("value", "")).strip()
                             for r in b["rows"]):
        out.append("a tally row needs its label and value")
    if sh == "timeline" and any(not isinstance(s, dict) or not s.get("what") for s in b["steps"]):
        out.append("a timeline step needs what happened")
    if sh == "claim_vs_claim" and any(not isinstance(a, dict) for a in b["accounts"]):
        out.append("an account is not an object")
    return out


def beat_problems(beat: dict, p: dict) -> list[str]:
    """Everything wrong with one script.json beat, in plain words; empty when it can be drawn."""
    sh = beat.get("shot")
    if sh not in shots.catalog()["shots"]:
        return [f"\"{sh}\" is not a shot in the catalog"]
    b = internal(beat)
    try:
        probs = _shape_problems(b)
        if probs:
            return probs
        probs = sw._blank_problems(b, p) + sw._mark_problems(b, p)
        if beat.get("voice") != shots.voice(b["say"]):
            probs.append("the voice text is not the line with its marks taken out")
        if "[" in (beat.get("voice") or "") or "]" in (beat.get("voice") or ""):
            probs.append("a bracket is left in the text for the voice")
        if sh == "quote" and not (beat.get("blanks") or {}).get("quote", {}).get("text"):
            probs.append("the quote shot has no quote text")
        if sh == "quote":
            # the drawn quote is a copy inside the beat: it must be the evidence quote its card points to
            # (found by the video evals, Nov 26: module 7's check reads the card, not this copy)
            bl = beat.get("blanks") or {}
            evq = (p.get("quotes") or {}).get(bl.get("card")) or {}
            shown = (bl.get("quote") or {}).get("text")
            if evq and shown and shown != evq.get("text"):
                probs.append("the quote on screen isn't the evidence quote letter for letter")
        if not probs and sh not in ("sides", "sources"):
            probs += sw._on_screen(b, p)
    except (KeyError, TypeError, AttributeError) as e:          # a field of the wrong type or missing
        probs = [f"the beat is malformed ({type(e).__name__}: {e})"]
    return probs


def _title_ok(beat: dict, p: dict) -> str:
    """The beat's own title or headline when it passes the on-screen check, else ''."""
    t = (beat.get("blanks") or {}).get("title")
    if not isinstance(t, str) or not t.strip() or len(t.split()) > shots.limits()["headline_words_max"]:
        return ""
    probe = dict(internal(dict(beat, shot="headline")), title=t)
    return t if not sw._on_screen(probe, p) else ""


def as_headline(beat: dict, p: dict, why: str) -> tuple[dict, dict]:
    """The beat redrawn as a headline card, and the record of the swap."""
    title = _title_ok(beat, p)
    voice_text = beat.get("voice") if isinstance(beat.get("voice"), str) else shots.voice(beat.get("say") or "")
    nb = dict(beat, shot="headline", blanks={"title": title}, swapped_from=beat.get("shot"),
              say=shots.voice(beat.get("say") or ""), voice=voice_text)
    return nb, dict(beat=beat.get("n"), shot=beat.get("shot"), became="headline", title_kept=bool(title), why=why)


def check_script(script: dict, p: dict) -> dict:
    """Step 1 over a whole script.json. p: module 7's packet for the same story (sw.packet)."""
    if script.get("status") == "no video" or not script.get("beats"):
        return dict(beats=[], swaps=[], stop=f"module 7 wrote no video: {script.get('reason') or 'no beats'}")
    if not script.get("sources_card"):
        return dict(beats=[], swaps=[], stop="the script has no sources card")
    beats, swaps = [], []
    for beat in script["beats"]:
        probs = beat_problems(beat, p)
        if not probs:
            beats.append(copy.deepcopy(beat))
            continue
        why = "; ".join(probs)
        if beat.get("shot") in ESSENTIAL:
            return dict(beats=[], swaps=swaps, stop=f"the {beat.get('shot')} beat can't be drawn: {why}")
        nb, sw_rec = as_headline(beat, p, why)
        beats.append(nb)
        swaps.append(sw_rec)
    if beats[0]["shot"] != "hook" or beats[-1]["shot"] != "sources":
        return dict(beats=[], swaps=swaps, stop="the script must open with the hook and end with the sources card")
    text = voice_text(beats)
    if "[" in text or "]" in text:
        return dict(beats=[], swaps=swaps, stop="a bracket is left in the text for the voice")
    return dict(beats=beats, swaps=swaps, stop=None)


def voice_text(beats: list[dict]) -> str:
    """Exactly what the voice reads: each beat's voice text, a line break between beats."""
    return "\n".join(b["voice"] for b in beats)
