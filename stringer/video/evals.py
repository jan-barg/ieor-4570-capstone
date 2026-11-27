"""Module 8's evals (design page section 5, as trimmed and agreed Nov 26). scripts/eval_video.py runs them.

Code over what module 8 made for each frozen story (its video/ folder: plan.json, render.json, video.mp4),
plus broken scripts made by code. No model is called. Each check returns a list of problems in plain words
(empty = passed) or a few numbers:

  1  speed        time from script to finished file, per step (on the Mac until Cloud Run is deployed)
  2  reliability  real scripts all finish or stop cleanly; broken scripts never crash and each is handled
                  the way its kind of breakage should be (swap to a headline card, stop, or skip the picture)
  3  on-screen    the plan's on-screen words pass module 7's on-screen check again; the sources card adds up
  4  required     hook title on screen by 2 s, balance bar, credits (Monitor the Situation; AllSides when a side
                  comes from its ratings), the AI mark, a source label wherever a line names one
  5  sync         shot start vs its first word, marked animation vs its word, caption vs its word
  6  format       size, frame rate, codecs, 44-72 s, -14 LUFS +-1, true peak, no flashing
  7  layout       stills drawn with plan.debug_layout (render/src/layout.js): safe area, cut off, size,
                  contrast, overlapping text
  8  maps         pins inside the frame and their place's outline, framing fits the kind, outlines straight
                  from the map file, the event's own place holds the event's point
  11 shot choice  module 8's own swaps <= 10% of beats; no shot 3 times in a row
  13 cost         voice at list price + render on Cloud Run (estimated from Stage B) <= $0.25 a video
"""
from __future__ import annotations

import copy
import json
import math
import random
import re
import subprocess
from pathlib import Path

from .. import script_writer as sw
from .. import shots
from . import check, files, places, plan, voice

FPS = plan.FPS

# Bars (design page section 5).
SPEED_P95_S = 180
SWAP_RATE_MAX = 0.10
SYNC_SHOT_MS, SYNC_MARK_MS, SYNC_CAPTION_MS = 150, 150, 100
LENGTH_S = (44.0, 72.0)
COST_MAX_USD = 0.25
FLASH_DELTA = 0.10 * 255           # a frame-to-frame change of a tenth of full brightness, over the whole frame
FLASHES_PER_SECOND_MAX = 3

# Prices, for the cost bar. The voice is free on Jan's student plan; the list price is what it would cost.
VOICE_USD_PER_1K_CHARS = 0.04      # ElevenLabs Flash v2.5 list price (pricing page, read Nov 24)
CLOUD_RUN_USD_PER_S = 8 * 0.000024 + 16 * 0.0000025   # 8 vCPU + 16 GiB, request-based, tier 1
CLOUD_RUN_SECONDS_PER_VIDEO_SECOND = 1.75             # Stage B: a 60 s video in about 1.5-2 minutes

# Draw code that starts an animation a little before its word (render/src): the map highlight, 4 frames.
DRAW_LEAD_FRAMES = {"map_locate": 4, "map_link": 4, "map_spread": 4}
LAYOUT_SAFE = (60, 150, 960, 1440)   # render/src/layout.js SAFE (left, top, right, bottom), output pixels
LAYOUT_MIN_PX = 24                   # render/src/layout.js MIN_PX
ALLSIDES_SIDES = {"us_left", "us_right"}    # US lens sides built from AllSides leans (module 4)
LABEL_HIDDEN_ON = {"sides", "sources"}      # shots that draw no "Source:" label


def ms(frames: float) -> float:
    return round(frames * 1000 / FPS, 1)


# ---- 3: on-screen facts --------------------------------------------------------------------------------

def on_screen(pl: dict, p7: dict) -> list[str]:
    out = []
    for b in pl["beats"]:
        if b["shot"] in ("sides", "sources"):
            continue
        beat = dict(shot=b["shot"], blanks=b.get("blanks") or {}, claims=b.get("claims") or [], say="",
                    broll=b.get("broll") or {})
        try:
            errs = sw._on_screen(check.internal(beat), p7)
        except Exception as e:                                         # noqa: BLE001 - reported, not raised
            errs = [f"the check itself failed ({type(e).__name__}: {e})"]
        out += [f"beat {b['n']} ({b['shot']}): {e}" for e in errs]
    sc = pl.get("sources_card") or {}
    read = sc.get("read") or 0
    parts = sum(s.get("read") or 0 for s in sc.get("sides") or []) + (sc.get("elsewhere") or 0)
    if parts != read:
        out.append(f"sources card: the sides and elsewhere add up to {parts}, the card says {read} read")
    if len(sc.get("outlets") or []) > read:
        out.append(f"sources card: {len(sc['outlets'])} outlets listed for {read} articles read")
    return out


# ---- 4: required parts ---------------------------------------------------------------------------------

def required(pl: dict, script: dict) -> list[str]:
    out = []
    beats = pl["beats"]
    hook = beats[0] if beats else {}
    title = (hook.get("blanks") or {}).get("title") or ""
    if hook.get("shot") != "hook" or hook.get("start") != 0:
        out.append("the video doesn't open on the hook")
    elif not title.strip():
        out.append("the hook has no title")
    elif (2 + len(title)) / FPS > 2.0:                         # cards.js: one letter a frame from frame 2
        out.append(f"the hook title is fully on screen only after {(2 + len(title)) / FPS:.1f} s")
    sc = pl.get("sources_card") or {}
    if not beats or beats[-1]["shot"] != "sources":
        out.append("the video doesn't end on the sources card")
    if sum(s.get("read") or 0 for s in sc.get("sides") or []) + (sc.get("elsewhere") or 0) <= 0:
        out.append("the balance bar would be empty")
    credits = sc.get("credits") or []
    if not any(str(c).startswith("Events by Monitor the Situation") for c in credits):
        out.append("no credit for Monitor the Situation")
    if {s.get("side_id") for s in sc.get("sides") or []} & ALLSIDES_SIDES and not any("AllSides" in str(c) for c in credits):
        out.append("a side comes from AllSides ratings, but AllSides isn't credited")
    if not (pl.get("overlays") or {}).get("ai_mark") or not sc.get("ai_mark"):
        out.append("the AI mark is missing")
    by_n = {b.get("n"): b for b in script.get("beats") or []}
    for b in beats:
        want = plan.source_label((by_n.get(b["n"]) or {}).get("named") or [])
        if want and b.get("label") != want and not b.get("swapped_from"):
            out.append(f"beat {b['n']}: the line names a source but the label reads {b.get('label')!r}")
        if b.get("label") and b["shot"] in LABEL_HIDDEN_ON:
            out.append(f"beat {b['n']}: a source label on a {b['shot']} shot, which doesn't draw one")
    return out


# ---- 5: sync -------------------------------------------------------------------------------------------

def sync(pl: dict) -> dict:
    """Worst gaps in milliseconds. The frames come from the voice's own word times, so the gaps are the
    cut's lead (the shot starts a moment before its first word) and rounding to whole frames."""
    shot, mark, cap = [], [], []
    for b in pl["beats"]:
        if b.get("words"):
            shot.append(ms(b["words"][0]["start"]))                     # beat-relative frames
        for m in b.get("marks") or []:
            if m.get("words"):
                drawn = m["start"] - DRAW_LEAD_FRAMES.get(b["shot"], 0)
                mark.append(ms(drawn - m["words"][0]["start"]))
    abs_words = {}
    for b in pl["beats"]:
        for w in b.get("words") or []:
            abs_words.setdefault(b["start"] + w["start"], w["w"])
    for c in pl.get("captions") or []:
        for w in c["words"]:
            near = min(abs_words, key=lambda f: abs(f - w["start"])) if abs_words else w["start"]
            cap.append(ms(w["start"] - near))
    worst = lambda xs: max((abs(x) for x in xs), default=0.0)   # noqa: E731
    out = dict(shot_ms=worst(shot), mark_ms=worst(mark), caption_ms=worst(cap),
               shot_median_ms=sorted(shot)[len(shot) // 2] if shot else 0.0)
    out["problems"] = [f"{k.replace('_ms', '')} off by {v} ms (bar {bar})" for k, v, bar in
                       (("shot_ms", out["shot_ms"], SYNC_SHOT_MS), ("mark_ms", out["mark_ms"], SYNC_MARK_MS),
                        ("caption_ms", out["caption_ms"], SYNC_CAPTION_MS)) if v > bar]
    return out


# ---- 6: format and sound -------------------------------------------------------------------------------

def brightness(mp4: Path) -> list[float]:
    """Mean brightness (0-255) of every frame, from a small copy of the video."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp4), "-vf",
                        "scale=96:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(x) for x in re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", r.stderr)]


def flashes(ys: list[float]) -> int:
    """The most flashes in any one second: a flash is a pair of big opposite changes in brightness."""
    big = [(i, 1 if ys[i] > ys[i - 1] else -1) for i in range(1, len(ys)) if abs(ys[i] - ys[i - 1]) >= FLASH_DELTA]
    best = 0
    for k, (i, _) in enumerate(big):
        window = [d for j, d in big[k:] if j - i < FPS]
        pairs = sum(1 for a, b in zip(window, window[1:]) if a != b)
        best = max(best, (pairs + 1) // 2)
    return best


def fmt(rec: dict, pl: dict, mp4: Path | None) -> dict:
    facts, loud = rec.get("video") or {}, rec.get("loudness") or {}
    out = dict(seconds=facts.get("seconds"), lufs=loud.get("lufs"), true_peak=loud.get("true_peak"),
               problems=list(files.problems(facts, loud, pl)) if facts and loud else ["no render record"])
    s = facts.get("seconds") or 0
    if not LENGTH_S[0] <= s <= LENGTH_S[1]:
        out["problems"].append(f"{s} s long, outside {LENGTH_S[0]:.0f}-{LENGTH_S[1]:.0f} s")
    if mp4 and mp4.exists():
        out["flashes_per_second"] = flashes(brightness(mp4))
        if out["flashes_per_second"] > FLASHES_PER_SECOND_MAX:
            out["problems"].append(f"{out['flashes_per_second']} flashes in one second")
    if (pl.get("audio") or {}).get("music"):
        out["music_db"] = (pl["audio"] or {}).get("music_db")
        if out["music_db"] is not None and out["music_db"] > -12:
            out["problems"].append(f"music only {-out['music_db']} dB under the voice")
    return out


# ---- 8: maps -------------------------------------------------------------------------------------------

def _close(a, b, tol=1e-3) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _contains_box(outer, inner, tol=1e-3) -> bool:
    return outer[0] <= inner[0] + tol and outer[1] <= inner[1] + tol and outer[2] >= inner[2] - tol and outer[3] >= inner[3] - tol


EDGE_KM = 25      # an event's point this close to its place's edge counts as in it (a bridge, a port, a coast)


def near(shape: dict, lng: float, lat: float, km: float = EDGE_KM) -> bool:
    """Inside the outline, or within km of one of its edge points."""
    if places.contains(shape, lng, lat):
        return True
    return any(places.km(lat, lng, y, x) <= km for poly in shape["coordinates"] for ring in poly for x, y in ring)


def maps(pl: dict, event: dict, g: places.Gazetteer) -> dict:
    out, checked = [], 0
    try:
        ev = (float(event["lng"]), float(event["lat"]))
    except (KeyError, TypeError, ValueError):
        ev = None
    loc = places.norm(str(event.get("location_name") or ""))
    for b in pl["beats"]:
        m = b.get("map")
        if not m:
            continue
        checked += 1
        tag = f"beat {b['n']} ({b['shot']})"
        fr_ = m["frame"]
        for p in m["places"]:
            if not places.in_box(fr_, p["lng"], p["lat"]):
                out.append(f"{tag}: {p['name']} is outside the map's frame")
        if b["shot"] == "hook":
            if ev and not places.in_box(fr_, *ev):
                out.append(f"{tag}: the event's point is outside the hook's map")
            continue
        found = []
        kind = (b.get("blanks") or {}).get("place_kind") or "point"
        for p in m["places"]:
            f = places.find(p["name"], kind if b["shot"] == "map_locate" else "point", event, g)
            found.append(f)
            if not f or not _close((f["lng"], f["lat"]), (p["lng"], p["lat"])):
                out.append(f"{tag}: {p['name']} doesn't look up to the same place again")
        first = found[0]
        if m.get("outline") is not None:
            if not first or g.shape(first.get("shape")) != m["outline"]:
                out.append(f"{tag}: the outline isn't the map file's shape for {m['places'][0]['name']}")
            elif not places.contains(m["outline"], m["places"][0]["lng"], m["places"][0]["lat"]):
                out.append(f"{tag}: {m['places'][0]['name']}'s label point lies outside its own outline")
        if first and all(found):
            want = places.frame([f for f in found if f], g)
            if not _close(fr_, want):
                out.append(f"{tag}: the frame doesn't fit a {first['kind']} ({fr_} vs {want})")
            if len(found) == 1 and first["kind"] in ("province", "country", "sea") and first.get("bbox"):
                inner = places._main_bbox(g.shape(first.get("shape")), first["bbox"])
                if not _contains_box(fr_, inner):
                    out.append(f"{tag}: the frame cuts off part of {first['name']}")
        own = [p for p in m["places"] if loc and places.norm(p["name"]) and places.norm(p["name"]) in loc]
        if ev and own:
            if not places.in_box(fr_, *ev):
                out.append(f"{tag}: the event's own place is mapped, but the event's point is outside the frame")
            elif m.get("outline") is not None and own[0] is m["places"][0] and not near(m["outline"], *ev):
                out.append(f"{tag}: the event's point is more than {EDGE_KM} km outside the outline of {own[0]['name']}")
    return dict(maps=checked, problems=out)


# ---- 11: shot choice -----------------------------------------------------------------------------------

def shot_choice(pl: dict) -> dict:
    shots_ = [b["shot"] for b in pl["beats"]]
    triples = [i + 1 for i in range(len(shots_) - 2) if shots_[i] == shots_[i + 1] == shots_[i + 2]]
    return dict(beats=len(shots_), swaps=len(pl.get("swaps") or []), triples=triples,
                swapped=[dict(beat=s.get("beat"), shot=s.get("shot"), why=s.get("why")) for s in pl.get("swaps") or []])


# ---- 13: cost, 1: speed --------------------------------------------------------------------------------

def cost(rec: dict) -> dict:
    v = (rec.get("steps") or {}).get("voice") or {}
    calls = 2 if v.get("revoiced") else 1
    voice_usd = round((v.get("chars") or 0) * calls / 1000 * VOICE_USD_PER_1K_CHARS, 4)
    seconds = (rec.get("video") or {}).get("seconds") or v.get("duration") or 0
    render_usd = round(seconds * CLOUD_RUN_SECONDS_PER_VIDEO_SECOND * CLOUD_RUN_USD_PER_S, 4)
    return dict(credits_charged=v.get("credits") or 0, chars=v.get("chars") or 0, calls=calls,
                voice_usd=voice_usd, render_usd=render_usd, total_usd=round(voice_usd + render_usd, 4))


def speed(rec: dict) -> dict:
    st = rec.get("steps") or {}
    return dict(total_s=rec.get("seconds"), render_s=(st.get("render") or {}).get("seconds"),
                files_s=(st.get("files") or {}).get("seconds"), voice_s=(st.get("voice") or {}).get("seconds"),
                voice_reused=(st.get("voice") or {}).get("reused"))


def p95(xs: list[float]) -> float:
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, math.ceil(0.95 * len(xs)) - 1)] if xs else 0.0


# ---- 2: broken scripts ---------------------------------------------------------------------------------
# Each kind of breakage, what it does to a copy of a real script, and how module 8 should handle it:
#   "swap"  the broken beat becomes a headline card;   "stop"  no video;
#   "skip"  the beat keeps its shot, its picture is left out;   "ok"  drawn as it is (or redrawn safely).

def _pick(s: dict, rnd: random.Random, shots_: tuple[str, ...] | None = None, middle=True) -> dict | None:
    """A beat to break; the script remembers which (s["_beat"]), so its swap counts even when the unbroken
    script already swapped that beat."""
    bs = [b for b in s["beats"][1:-1] if (not shots_ or b["shot"] in shots_)] if middle else s["beats"]
    b = rnd.choice(bs) if bs else None
    if b:
        s["_beat"] = b.get("n")
    return b


def _m_unknown_shot(s, rnd):
    b = _pick(s, rnd)
    b["shot"] = "hologram"
    return s


def _m_empty_blanks(s, rnd):
    b = _pick(s, rnd, ("big_number", "timeline", "quote", "tally", "claim_vs_claim", "document", "map_locate"))
    if not b:
        return None
    b["blanks"] = {}
    return s


def _m_wrong_types(s, rnd):
    b = _pick(s, rnd, ("big_number", "timeline", "quote", "tally", "claim_vs_claim", "document", "headline"))
    if not b:
        return None
    b["blanks"] = {k: (12345 if isinstance(v, str) else "not a list") for k, v in (b.get("blanks") or {}).items()} or {"title": 7}
    return s


def _m_long_title(s, rnd):
    b = _pick(s, rnd, ("headline",))
    if not b:
        return None
    b["blanks"] = dict(b.get("blanks") or {}, title=" ".join(["Officials"] * 60))
    return s


def _m_long_quote(s, rnd):
    b = _pick(s, rnd, ("quote",))
    if not b:
        return None
    q = (b.get("blanks") or {}).get("quote") or {}
    text = (q.get("text") if isinstance(q, dict) else str(q)) or "words"
    b["blanks"]["quote"] = dict(q if isinstance(q, dict) else {}, text=(text + " ") * 12)
    return s


def _m_unknown_place(s, rnd):
    b = _pick(s, rnd, ("map_locate", "map_link", "map_spread"))
    if not b:
        return None
    b["blanks"]["places"] = ["Qzxvbnm Atoll"]
    return s


def _m_bracket(s, rnd):
    b = _pick(s, rnd)
    b["voice"] = (b.get("voice") or "") + " [pause]"
    return s


def _m_number(s, rnd):
    b = _pick(s, rnd, ("big_number",))
    if not b:
        return None
    b["blanks"]["value"] = "987,654"
    return s


def _m_broken_hook(s, rnd):
    s["beats"][0]["blanks"] = {}
    return s


def _m_no_sources_card(s, rnd):
    s["sources_card"] = None
    return s


def _m_no_beats(s, rnd):
    s["beats"] = []
    return s


def _m_hook_last(s, rnd):
    s["beats"] = s["beats"][1:-1] + [s["beats"][0], s["beats"][-1]]
    return s


def _bare(s, rnd, shots_):
    """A middle beat of one of these shots with no picture of its own yet."""
    bs = [b for b in s["beats"][1:-1] if b["shot"] in shots_ and (b.get("broll") or {}).get("kind") in (None, "none")]
    b = rnd.choice(bs) if bs else None
    if b:
        s["_beat"] = b.get("n")
    return b


def _m_unknown_prop(s, rnd):
    b = _bare(s, rnd, ("headline", "big_number", "timeline", "map_locate"))
    undrawn = sorted(set(shots.catalog()["broll"]["props"]) - set(plan.PROPS))
    if not b or not undrawn:
        return None
    b["broll"] = dict(kind="prop", name=rnd.choice(undrawn))       # on the catalog's list, not drawn yet
    return s


def _m_unknown_person(s, rnd):
    b = _bare(s, rnd, ("headline", "quote"))
    if not b:
        return None
    b["broll"] = dict(kind="portrait", name="Ottoline Qwerty")
    return s


def _m_quote_changed(s, rnd):
    b = _pick(s, rnd, ("quote",))
    if not b:
        return None
    q = dict((b.get("blanks") or {}).get("quote") or {})
    q["text"] = (q.get("text") or "") + " and much more"
    b["blanks"]["quote"] = q
    return s


def _m_link_one_place(s, rnd):
    b = _pick(s, rnd, ("map_locate",))
    if not b:
        return None
    b["shot"] = "map_link"
    b["blanks"] = {k: v for k, v in b["blanks"].items() if k != "place_kind"}
    b["blanks"]["places"] = list(b["blanks"].get("places") or [])[:1]
    return s


def _m_many_steps(s, rnd):
    b = _pick(s, rnd, ("timeline",))
    if not b:
        return None
    steps_ = list((b.get("blanks") or {}).get("steps") or [])
    b["blanks"]["steps"] = (steps_ * 12)[:12]
    return s


def _m_no_rows(s, rnd):
    b = _pick(s, rnd, ("tally",))
    if not b:
        return None
    b["blanks"]["rows"] = []
    return s


def _m_many_named(s, rnd):
    b = _pick(s, rnd)
    b["named"] = [f"Official number {i}" for i in range(20)]
    return s


def _m_repeat_beat(s, rnd):
    b = _bare(s, rnd, tuple(shots.catalog()["shots"]))
    if not b:
        return None
    i = s["beats"].index(b)
    s["beats"][i:i + 1] = [copy.deepcopy(b) for _ in range(3)]
    return s


MUTATIONS = [
    ("unknown shot", _m_unknown_shot, "swap"),
    ("empty blanks", _m_empty_blanks, "swap"),
    ("fields of the wrong type", _m_wrong_types, "swap"),
    ("60-word headline", _m_long_title, "swap"),
    ("quote repeated 12 times", _m_long_quote, "swap"),
    ("quote changed from the evidence", _m_quote_changed, "swap"),
    ("place that doesn't exist", _m_unknown_place, "swap"),
    ("bracket left for the voice", _m_bracket, "stop"),
    ("number not in the claims", _m_number, "swap"),
    ("broken hook", _m_broken_hook, "stop"),
    ("no sources card", _m_no_sources_card, "stop"),
    ("no beats", _m_no_beats, "stop"),
    ("hook not first", _m_hook_last, "stop"),
    ("prop that isn't drawn", _m_unknown_prop, "skip"),
    ("person with no portrait", _m_unknown_person, "skip"),
    ("link with one place", _m_link_one_place, "swap"),
    ("12 timeline steps", _m_many_steps, "swap"),
    ("tally with no rows", _m_no_rows, "swap"),
    ("20 named sources", _m_many_named, "ok"),
    ("one beat three times", _m_repeat_beat, "ok"),
]
OUTCOMES = ("ok", "skip", "swap", "stop", "crash")


def outcome(s: dict, p7: dict, event: dict, base: dict, g, cache: Path) -> tuple[str, dict | None, str]:
    """What module 8's steps 1-4 do with a script: (outcome, plan or None, detail)."""
    try:
        res = check.check_script(s, p7)
        if res["stop"]:
            return "stop", None, res["stop"]
        narr = voice.narrate(res["beats"], voice.Paced(audio=False), cache_dir=cache)
        pl = plan.build(res["beats"], narr, s, event, swaps=res["swaps"], g=g, p7=p7)
    except Exception as e:                                            # noqa: BLE001 - a crash is the finding
        return "crash", None, f"{type(e).__name__}: {e}"
    skipped = sum(1 for b in pl["beats"] if (b.get("broll") or {}).get("skipped"))
    hit = [x for x in pl["swaps"] if s.get("_beat") is not None and x.get("beat") == s.get("_beat")]
    if len(pl["swaps"]) > base["swaps"] or hit:
        return "swap", pl, "; ".join(str(x.get("why"))[:120] for x in (hit or pl["swaps"][base["swaps"]:]))
    if skipped > base["skipped"]:
        return "skip", pl, "picture left out"
    return "ok", pl, ""


def baseline(s: dict, p7: dict, event: dict, g, cache: Path) -> dict:
    res = check.check_script(s, p7)
    if res["stop"]:
        return dict(stop=res["stop"])
    narr = voice.narrate(res["beats"], voice.Paced(audio=False), cache_dir=cache)
    pl = plan.build(res["beats"], narr, s, event, swaps=res["swaps"], g=g, p7=p7)
    return dict(stop=None, swaps=len(pl["swaps"]), skipped=sum(1 for b in pl["beats"] if (b.get("broll") or {}).get("skipped")))


def confusion(results: list[dict]) -> dict:
    m = {e: {a: 0 for a in OUTCOMES} for e in OUTCOMES if e != "crash"}
    for r in results:
        m[r["expected"]][r["actual"]] += 1
    return m


def save(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
