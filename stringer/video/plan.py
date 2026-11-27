"""Step 4: the render plan, everything the drawing code needs, in frames (30 a second).

One JSON file, read by the Remotion project in render/:
  - every beat: its first and last frame, its shot and blanks, its looked-up places and pictures, its
    marked words as frames counted from the beat's first frame, and its source label;
  - the captions burned into the picture: chunks of up to 4 words that never cross a cut, each word with its
    frames, leaving out words the picture already shows as they are read (Jan, Nov 26: "no need for
    subtitles" when the narrator reads text that is on screen); the full subtitles for the captions file;
  - the sources card, the credits and the overlays ("Made with AI", "Illustration", "Developing");
  - the audio: the narration file and the music bed.

A map beat whose place can't be found becomes a headline card here, and the swap is listed with step 1's.

    p = build(beats, narration, script, event, swaps=[], music="ambient-1.mp3")
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from .. import shots
from . import people, places
from .check import as_headline

VERSION = "plan-1"
FPS, WIDTH, HEIGHT = 30, 1080, 1920
AI_MARK = "Made with AI"
DRAWN = ("map_locate", "map_link", "map_spread")           # shots that are drawn illustrations
# The props render/src/props.js draws (decision 8: these 10 first, the other 11 after the first videos).
PROPS = ("ballot box", "bridge", "train", "document", "plane", "drone", "flag", "missile", "computer chip", "cargo ship")
CAPTION_WORDS = 4
MUSIC_DB = -16.0   # the bed under the voice (eval 6: at least 12 dB under). The bed file is stored at the voice's own
                   # loudness (about -21 LUFS, make.MUSIC), so this is how far under the voice it sits.


def fr(t: float) -> int:
    return int(round(t * FPS))


# ---- the source label ----------------------------------------------------------------------------------

_SMALL = {"a", "an", "the", "one", "two", "three", "several", "some", "of", "and"}


def _stems(s: str) -> set[str]:
    return {re.sub(r"s$", "", w) for w in re.findall(r"[a-z]+", s.lower()) if w not in _SMALL}


def source_label(named: list[str]) -> str:
    """'Source: …' while a line that names its source plays (decision 14): split at ';', drop 'the outlet',
    drop a name the one before already covers, at most two names, 'state-controlled media' kept."""
    kept: list[str] = []
    for n in named or []:
        for x in str(n).split(";"):
            x = x.strip()
            if not x or places.norm(x) in ("outlet", "the outlet", "outlets"):
                continue
            st = _stems(x)
            if any(st <= _stems(k) or _stems(k) <= st for k in kept):
                continue
            kept.append(x[0].upper() + x[1:])
    kept = kept[:2]
    if not kept:
        return ""
    return ("Source: " if len(kept) == 1 else "Sources: ") + " · ".join(kept)


# ---- captions ------------------------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return re.findall(r"[a-z0-9]+", "".join(c for c in t if not unicodedata.combining(c)))


def screen_texts(b: dict, marks: list[dict]) -> list[str]:
    """The words a beat's picture shows, field by field (what the drawing code in render/ puts on screen)."""
    bl, shot = b.get("blanks") or {}, b["shot"]
    out: list = []
    if shot in ("hook", "headline"):
        out.append(bl.get("title"))
    elif shot == "sides":
        out += [m["text"] for m in marks if m["mark"] in ("sideA", "sideB")]
    elif shot == "quote":
        q = bl.get("quote")
        out += [q.get("text") if isinstance(q, dict) else q, bl.get("speaker"), bl.get("role")]
    elif shot == "timeline":
        for st in bl.get("steps") or []:
            out += [st.get("when"), st.get("what")]
    elif shot == "big_number":
        out += [bl.get(k) for k in ("value", "unit", "label", "compare_value", "compare_label")]
    elif shot == "claim_vs_claim":
        for a in bl.get("accounts") or []:
            out += [a.get("who"), a.get("says") or a.get("what")]
    elif shot == "document":
        out += [bl.get(k) for k in ("title", "issued_by", "outcome")]
    elif shot == "tally":
        for r in bl.get("rows") or []:
            out += [r.get("label"), r.get("value")]
        out.append(bl.get("total"))
    elif shot.startswith("map_"):
        out += list(bl.get("places") or []) + [bl.get("label")]
    return [str(x) for x in out if x not in (None, "")]


def read_on_screen(field: str, spoken: list[str]) -> set[int]:
    """Which spoken words (indexes into spoken tokens) read out this on-screen field. A field counts as read
    when at least 60% of its words are spoken in order, in runs of 2 or more, within a stretch at most 3
    words longer than the field; the whole stretch is hidden, so no stray word is left as its own caption.
    Fields of one word never count (hiding one caption word looks broken)."""
    f = _tokens(field)
    if len(f) < 2 or not spoken:
        return set()
    allb = [m for m in difflib.SequenceMatcher(None, spoken, f, autojunk=False).get_matching_blocks() if m.size]
    core = [m for m in allb if m.size >= 2]
    if not core or sum(m.size for m in core) < 0.6 * len(f):
        return set()
    a0, a1 = core[0].a, core[-1].a + core[-1].size
    for m in allb:                       # single matching words right next to the stretch belong to it
        if a1 <= m.a <= a1 + 2:
            a1 = max(a1, m.a + m.size)
        elif a0 - 2 <= m.a < a0:
            a0 = m.a
    if a1 - a0 <= len(f) + 3:
        return set(range(a0, a1))
    return {i for m in core if m.size >= 3 for i in range(m.a, m.a + m.size)}


def shown_words(beats: list[dict], narr: dict) -> set[int]:
    """Indexes into narr["words"] of the words the picture shows while they are read."""
    hidden: set[int] = set()
    for i, b in enumerate(beats):
        idx = [k for k, w in enumerate(narr["words"]) if w["beat"] == i]
        # one token list for the beat, and which word each token came from
        toks, owner = [], []
        for k in idx:
            for t in _tokens(narr["words"][k]["w"]):
                toks.append(t)
                owner.append(k)
        marks = [m for m in narr["marks"] if m["beat"] == i]
        for field in screen_texts(b, marks):
            hidden |= {owner[j] for j in read_on_screen(field, toks)}
    return hidden


def captions(words: list[dict], hidden: set[int] = frozenset()) -> list[dict]:
    """Chunks of up to 4 words, broken at sentence ends, after commas, at every cut and around hidden words."""
    chunks, cur = [], []
    for k, w in enumerate(words):
        if k in hidden:
            if cur:
                chunks.append(cur)
                cur = []
            continue
        cur.append(k)
        nxt = words[k + 1] if k + 1 < len(words) else None
        if (len(cur) == CAPTION_WORDS or re.search(r"[.?!]$", w["w"]) or (re.search(r"[,;:]$", w["w"]) and len(cur) >= 2)
                or nxt is None or nxt["beat"] != w["beat"] or k + 1 in hidden):
            chunks.append(cur)
            cur = []
    out = []
    for c in chunks:
        first, last = words[c[0]], words[c[-1]]
        nxt = words[c[-1] + 1] if c[-1] + 1 < len(words) else None
        end = nxt["start"] if nxt and nxt["beat"] == last["beat"] and c[-1] + 1 not in hidden else last["end"] + 0.25
        out.append(dict(beat=first["beat"], start=fr(first["start"]), end=fr(end),
                        words=[dict(w=words[k]["w"], start=fr(words[k]["start"]), end=fr(words[k]["end"])) for k in c]))
    return out


# ---- the beats -----------------------------------------------------------------------------------------

def _map(beat: dict, event: dict, g) -> tuple[dict | None, list[str]]:
    """The map data of a map beat: found places, outline, frame. Places not found are listed."""
    bl = beat["blanks"]
    kind = bl.get("place_kind") or "point"
    found, missing = [], []
    for name in bl.get("places") or []:
        p = places.find(name, kind if beat["shot"] == "map_locate" else "point", event, g)
        (found if p else missing).append(p or name)
    if not found:
        return None, missing
    shot = beat["shot"]
    if shot == "map_link" and len(found) < 2 or shot == "map_spread" and len(found) < 2:
        shot = "map_locate"
        found = found[:1]
    outline = g.shape(found[0].get("shape")) if shot == "map_locate" and found[0].get("shape") else None
    box = places.frame(found, g)
    ctx = places.context(box, g, skip=[(p["lng"], p["lat"]) for p in found])
    return dict(shot=shot, frame=box, context=ctx, lakes=g.lakes(box), outline=outline, label=bl.get("label") or "",
                places=[dict(name=p["name"], lat=p["lat"], lng=p["lng"], kind=p["kind"], how=p["how"], found=p.get("found"))
                        for p in found]), missing


def hook_map(event: dict, g) -> dict | None:
    """The hook's backdrop: the event's own place in dots, with a pin."""
    try:
        lat, lng = float(event["lat"]), float(event["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    loc = str(event.get("location_name") or "")
    hit = g.lookup(loc, ["country"], None) if loc else None
    box = places.frame([dict(hit, shape=hit.get("id"))], g) if hit else places.point_box(lat, lng, 320)
    return dict(frame=box, context=places.context(box, g, skip=[(lng, lat)]), lakes=g.lakes(box),
                places=[dict(name=loc, lat=lat, lng=lng)], outline=None)


def _beat(b: dict, i: int, narr: dict, event: dict, g, swaps: list, p7) -> dict:
    t = narr["beats"][i]
    start, end = fr(t["start"]), fr(t["end"])
    words = [w for w in narr["words"] if w["beat"] == i]
    marks = [dict(mark=m["mark"], text=m["text"], start=fr(m["start"]) - start, end=fr(m["end"]) - start,
                  words=[dict(w=w["w"], start=fr(w["start"]) - start, end=fr(w["end"]) - start)
                         for w in narr["words"][m["first_word"]:m["last_word"] + 1]])
             for m in narr["marks"] if m["beat"] == i]
    out = dict(n=b.get("n", i + 1), shot=b["shot"], start=start, end=end, frames=end - start,
               blanks=b.get("blanks") or {}, claims=b.get("claims") or [], marks=marks,
               words=[dict(w=w["w"], start=fr(w["start"]) - start, end=fr(w["end"]) - start) for w in words],
               label=source_label(b.get("named") or []), swapped_from=b.get("swapped_from"))
    br = b.get("broll") or {}
    out["broll"] = dict(kind=br.get("kind") or "none", name=br.get("name") or "")
    if out["broll"]["kind"] == "prop" and out["broll"]["name"] not in PROPS:
        out["broll"]["skipped"] = "prop not drawn yet"
    if out["broll"]["kind"] == "prop" and b["shot"] == "document" and out["broll"]["name"] == "document":
        out["broll"]["skipped"] = "the shot already shows a document"
    if out["broll"]["kind"] == "portrait":
        pt = people.portrait(br.get("name"))
        out["broll"]["portrait"] = pt
        if pt is None:
            out["broll"]["skipped"] = "no approved portrait"
    if b["shot"].startswith("map_"):
        m, missing = _map(b, event, g)
        if m is None:
            nb, rec = as_headline(b, p7, f"place not found: {', '.join(map(str, missing))}") if p7 is not None else \
                (dict(b, shot="headline", blanks={"title": ""}, swapped_from=b["shot"]),
                 dict(beat=b.get("n"), shot=b["shot"], became="headline", title_kept=False,
                      why=f"place not found: {', '.join(map(str, missing))}"))
            swaps.append(rec)
            return _beat(nb, i, narr, event, g, swaps, p7)
        out["shot"], out["map"] = m["shot"], m
        if missing:
            out["map"]["missing"] = [str(x) for x in missing]
    if b["shot"] == "hook":
        out["map"] = hook_map(event, g)
    drawn_prop = out["broll"]["kind"] == "prop" and not out["broll"].get("skipped")
    out["illustration"] = out["shot"] in DRAWN or drawn_prop or (b["shot"] == "hook" and bool(out.get("map")))
    return out


def build(beats: list[dict], narr: dict, script: dict, event: dict, *, swaps: list | None = None,
          music: str | None = None, g=None, p7=None) -> dict:
    """The render plan. narr: voice.narrate()'s result for the same beats. p7: module 7's packet, so a
    swapped beat keeps its title only when it passes the on-screen check."""
    g = g or places.default()
    swaps = list(swaps or [])
    plan_beats = [_beat(b, i, narr, event, g, swaps, p7) for i, b in enumerate(beats)]
    # On screen the credits name the site; the full links go in the post's caption (Jan, Nov 26: "just site name").
    credits = [c for c in script.get("credits") or [] if not re.match(r"https?://", str(c))]
    links = [c for c in script.get("credits") or [] if re.match(r"https?://", str(c))]
    voice_credit = "Narration voice by ElevenLabs" if narr["voice"].get("engine") == "elevenlabs" else ""
    portrait_credits = people.credits([b["broll"]["portrait"] for b in plan_beats if b["broll"].get("portrait")])
    total = fr(narr["duration"])
    return dict(
        version=VERSION, catalog=shots.catalog()["version"], fps=FPS, width=WIDTH, height=HEIGHT, frames=total,
        story=dict(id=(event or {}).get("id"), title=script.get("title") or "", developing=bool(script.get("developing"))),
        audio=dict(voice="narration.mp3", music=music, music_db=MUSIC_DB if music else None),
        beats=plan_beats, captions=captions(narr["words"], shown_words(plan_beats, narr)),
        subtitles=captions(narr["words"]), post=dict(links=links),
        sources_card=dict(script.get("sources_card") or {}, credits=credits + [x for x in [voice_credit] if x] + portrait_credits),
        overlays=dict(ai_mark=AI_MARK), swaps=swaps,
        voice=dict(narr["voice"], seconds=narr["seconds"], chars=narr["chars"], words_per_second=narr.get("words_per_second")))
