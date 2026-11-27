"""Choose a story's sides (module 4, Balance): which two camps of outlets a video compares, or that
the story has no real split. Runs before Gather, because the side searches need the sides.

The answer (a gather.sides.Lens) is one of three kinds:
  us     US left against right. The two sides are built in code from AllSides ratings.
  world  a world story's two sides, each a ready-made side list (side_lists.csv), a new side made of
         outlets from the outlet table, or a list plus extra outlets.
  none   no real split, plus the country whose own press gets searched (local press).

How (decided Nov 26, Jan, design page "Choosing a story's sides"):
  1. One model call reads the event (title, summary, place, category, the outlets its own links
     come from) next to the side lists and the outlet table. The answer format is enforced
     (JSON schema), the output limit is big, an unusable answer gets one retry, and if that fails
     too the plain-code rule below decides.
  2. Code checks the answer: outlet ids not in the table are dropped, a side with nothing on file
     keeps its name and gets a flag, two sides sharing outlets are flagged. New sides are never
     written into side_lists.csv; a live run saves them to a review file for Jan (record_new_sides;
     on the Mac only: on Cloud Run the story's lens.json, kept in the private bucket, holds the same).
  3. The plain-code rule (also the eval's free baseline): a US story is left against right; a
     country with a ready-made pair of side lists gets that pair; anything else has no split and
     searches its own country's press.

`complete(messages, name=..., **params)` makes one model call and returns an object with .text,
the same shape as the eval runner's ctx.complete; live_complete() wraps models.complete."""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from . import calls, models, paths
from .events import Event
from .gather.sides import Lens, Side, local_press, side_lists, us_sides
from .outlets import OutletTable

VERSION = "lens-3"         # the prompt in use (eval, Nov 26: lens-3 beat lens-1 by about 4 of 40 in cold mode)
KINDS = ("us", "world", "none")
MAX_TOKENS = 8000            # thinking counts toward this on some models; the answer itself is ~300 tokens
CALL_TIMEOUT_S = 180
MENU_KINDS = ("news", "wire")
US_CODE = "US"

# MTS country names -> the two-letter codes outlets.csv uses. Covers every country with outlets on
# file plus the common event countries; the model writes codes itself, this is for the code rule.
COUNTRY_CODES = {
    "United States": "US", "United Kingdom": "GB", "Ukraine": "UA", "Russia": "RU", "Israel": "IL",
    "Palestine": "PS", "Iran": "IR", "Saudi Arabia": "SA", "Yemen": "YE", "United Arab Emirates": "AE",
    "Qatar": "QA", "Lebanon": "LB", "Syria": "SY", "Iraq": "IQ", "Turkey": "TR", "Egypt": "EG",
    "Libya": "LY", "China": "CN", "Hong Kong": "HK", "Taiwan": "TW", "Japan": "JP", "South Korea": "KR",
    "North Korea": "KP", "India": "IN", "Pakistan": "PK", "Bangladesh": "BD", "Myanmar": "MM",
    "Singapore": "SG", "Australia": "AU", "France": "FR", "Germany": "DE", "Spain": "ES", "Italy": "IT",
    "Netherlands": "NL", "Switzerland": "CH", "Poland": "PL", "Serbia": "RS", "Hungary": "HU",
    "Finland": "FI", "Sweden": "SE", "Brazil": "BR", "Argentina": "AR", "Colombia": "CO",
    "Venezuela": "VE", "Mexico": "MX", "Canada": "CA", "Dominican Republic": "DO", "Nigeria": "NG",
    "South Africa": "ZA", "Kenya": "KE", "The Gambia": "GM", "Gambia": "GM", "Vietnam": "VN",
}

SCHEMA_SIDE = {"type": "object", "additionalProperties": False, "required": ["label", "list", "outlets"],
               "properties": {"label": {"type": "string"}, "list": {"type": "string"},
                              "outlets": {"type": "array", "items": {"type": "string"}}}}
SCHEMA = {"type": "json_schema", "json_schema": {"name": "story_sides", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["reason", "kind", "side_a", "side_b", "local_press"],
    "properties": {"reason": {"type": "string"},                     # the reason first
                   "kind": {"type": "string", "enum": list(KINDS)},
                   "side_a": SCHEMA_SIDE, "side_b": SCHEMA_SIDE,
                   "local_press": {"type": "string"}}}}}

PROMPT_LENS1 = """You decide which two sides a short news video compares for one event, before any coverage is searched. The video shows how two camps of news outlets tell the same story, or says plainly that the story has no real split.

Answer with one of three kinds:
- "us": a story about US politics, government or public life where left-leaning and right-leaning US outlets tell it differently. Code builds these two sides (AllSides left against right), so leave side_a and side_b empty.
- "world": a story with a clear two-sided divide outside US domestic politics: two countries or armed groups in a conflict, a government against its opposition, the backers of an action against its opponents.
- "none": no real divide. Accidents, natural disasters, disease cases, crimes and attacks that nobody disputes along political lines, science and space, markets, hacks. This holds for US stories too: a US event with no partisan angle is "none".

How to choose:
- Pick the divide the coverage itself will show: who tells this story differently. If the main dispute is between countries or parties abroad, it is "world" even when the US is involved.
- Don't invent a split because a country has political camps. A mass shooting in a country with left and right outlets is "none" unless its coverage argues about it along those lines.
- Exactly two sides. If more parties are involved, use the clearest two-way divide.

For a "world" story, each side has:
- label: who the side is, in a few plain words ("Ukrainian outlets", "Pro-government Serbian outlets").
- list: the id of a ready-made side list below that fits this side, or "" if none fits.
- outlets: outlet ids from the outlet table below, to add to the list or, when no list fits, to make up the side. Use only ids from the table. Pick outlets that speak for that side: its state media, outlets owned by or aligned with it, outlets from its country. Leave out international outlets that report straight (wires, the BBC, Al Jazeera and the like) unless they clearly take this side.
- If the table has no outlets for a side, still give its label, with list "" and outlets []. Code flags it.
For "us" and "none", give both sides as {"label": "", "list": "", "outlets": []}.

reason: one or two plain, neutral sentences: the divide and why, or why there is no real split.

local_press: for "none", the two-letter country code (ISO 3166-1) of the country whose press covers the story as home news, such as "ES" for a train crash in Spain. Use "" for a global story with no home country and for a US story. For "us" and "world", use "".

Answer with the JSON object only."""

# lens-2 (Nov 26): lens-1's misses on the cold eval, written as general rules: US policy stories called
# "no split" (Jan, Nov 26: a central-bank decision and a disease outbreak in the US stay left/right),
# riots against a government called crime, a summit with rival powers called US, camps that mix countries.
PROMPT_LENS2 = """You decide which two sides a short news video compares for one event, before any coverage is searched. The video shows how two camps of news outlets tell the same story, or says plainly that the story has no real split.

Answer with one of three kinds:
- "us": a story in US public life that touches government or policy, where left-leaning and right-leaning US outlets frame it differently even when the facts aren't disputed. That covers elections, the White House, Congress and its hearings, the courts, the central bank and the economy, public-health policy and outbreaks in the US, immigration, and companies or executives caught up with Washington (a hearing, a national-security probe, a regulator). A US government action aimed abroad (sanctions, tariffs, leaving a treaty) is "us" when the argument about it runs mainly through US politics. Code builds these two sides (AllSides left against right), so leave side_a and side_b empty.
- "world": a story with a clear two-sided divide outside US domestic politics: two countries or armed groups in a conflict; a government against its opposition, including mass protests or riots against a government (the protesters' camp against the government and law-and-order camp); a summit, deal or showdown between rival powers, such as the US with Russia or China (those powers' state media against Western outlets); the backers of an action against its opponents.
- "none": no real divide. Accidents, natural disasters, disease cases outside the US, crimes and attacks that nobody disputes along political lines, science and space, plain market moves, hacks, and a government agency's routine operations (a ground stop for weather or an outage, a product recall). A US story is "none" only when it has no government or policy angle.

How to choose:
- Pick the divide the coverage itself will show: who tells this story differently. If the main dispute is between countries or parties abroad, it is "world" even when the US is involved.
- Don't invent a split because a country has political camps. A mass shooting in a country with left and right outlets is "none" unless its coverage argues about it along those lines. Protests and riots aimed at a government are a divide, not a crime story.
- Exactly two sides. If more parties are involved, use the clearest two-way divide.
- A side can mix countries when they take the same position, such as a foreign government's media and the US outlets backing the same leader or plan.

For a "world" story, each side has:
- label: who the side is, in a few plain words ("Ukrainian outlets", "Pro-government Serbian outlets").
- list: the id of a ready-made side list below that fits this side, or "" if none fits.
- outlets: outlet ids from the outlet table below, to add to the list or, when no list fits, to make up the side. Use only ids from the table. Pick outlets that speak for that side: its state media, outlets owned by or aligned with it, outlets from its country. Leave out international outlets that report straight (wires, the BBC, Al Jazeera and the like) unless they clearly take this side.
- If the table has no outlets for a side, still give its label, with list "" and outlets []. Code flags it.
For "us" and "none", give both sides as {"label": "", "list": "", "outlets": []}.

reason: one or two plain, neutral sentences: the divide and why, or why there is no real split.

local_press: for "none", the two-letter country code (ISO 3166-1) of the country whose press covers the story as home news, such as "ES" for a train crash in Spain. Use "" for a global story with no home country and for a US story. For "us" and "world", use "".

Answer with the JSON object only."""

# lens-3 (Nov 26): lens-2 with "routine operations" narrowed to technical or safety steps; in lens-2 the
# word "routine" led to a government formation abroad being called "no split" (a follow-up story's miss).
PROMPT_LENS3 = PROMPT_LENS2.replace(
    "and a government agency's routine operations (a ground stop for weather or an outage, a product recall)",
    "and a government agency's technical or safety steps (a ground stop for weather or an outage, a product recall)")
assert PROMPT_LENS3 != PROMPT_LENS2

PROMPTS = {"lens-1": PROMPT_LENS1, "lens-2": PROMPT_LENS2, "lens-3": PROMPT_LENS3}

RETRY_NOTE = ("Your last answer could not be used ({why}). Answer again with one JSON object with the keys "
              "reason, kind, side_a, side_b and local_press, following the rules above.")


# ---- inputs ---------------------------------------------------------------------------------------

def ready_lists(t: OutletTable, hide=(), path=None) -> dict[str, Side]:
    """The side lists the model may pick from: the hand-made world lists plus US left and right
    (a world side can use them, such as US right-leaning outlets backing one party). `hide` takes
    lists out (the eval's cold mode)."""
    sl = side_lists(t, path) if path else side_lists(t)
    sl.pop("us_right_tail", None)
    return {k: v for k, v in sl.items() if k not in set(hide)}


def list_pairs(path=None) -> list[tuple[str, str]]:
    """The ready-made pairs: side_lists.csv keeps a pair's two lists on consecutive rows."""
    import csv
    with open(path or paths.SIDE_LISTS_CSV, newline="", encoding="utf-8") as f:
        ids = [r["side_id"] for r in csv.DictReader(f)]
    return [(ids[i], ids[i + 1]) for i in range(0, len(ids) - 1, 2)]


def majority_country(t: OutletTable, side: Side) -> str:
    c = Counter(t.by_id[i].country for i in side.outlet_ids if i in t.by_id)
    return c.most_common(1)[0][0] if c else ""


def menu_lists(t: OutletTable, lists: dict[str, Side]) -> str:
    lines = []
    for sid, s in lists.items():
        if sid in ("us_left", "us_right"):
            lines.append(f"- {sid}: {s.label} ({len(s.outlet_ids)} US outlets)")
            continue
        names = ", ".join(t.by_id[i].name for i in s.outlet_ids if i in t.by_id)
        lines.append(f"- {sid}: {s.label}. Outlets: {names}")
    return "\n".join(lines)


def menu_outlets(t: OutletTable) -> str:
    """Every news and wire outlet, by country: id (name; state media level)."""
    by = {}
    for o in t.outlets:
        if o.kind not in MENU_KINDS:
            continue
        sm = f"; {o.state_media}" if o.state_media else ""
        wire = "; wire" if o.kind == "wire" else ""
        by.setdefault(o.country or "none", []).append(f"{o.outlet_id} ({o.name}{wire}{sm})")
    order = sorted(by, key=lambda c: (c in ("none", "INT", "EU"), c))
    return "\n".join(f"{c}: " + ", ".join(by[c]) for c in order)


def own_sources(ev: Event, t: OutletTable) -> str:
    """The outlets and X accounts the event's own links come from."""
    seen, out = set(), []
    for u in ev.source_urls:
        lab = t.label(u)
        if lab["outlet_id"]:
            s = f"{lab['outlet_name']} ({lab['country'] or 'no country'})"
        elif lab["x_account"]:
            s = f"X account @{lab['x_account']}"
        else:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return "; ".join(out) or "none listed"


def event_block(ev: Event, t: OutletTable) -> str:
    return (f"Event title: {ev.title}\nSummary: {ev.summary}\nCategory: {ev.category} / {ev.subtype}\n"
            f"Country: {ev.country or 'not given'}\nPlace: {ev.location_name or 'not given'}\n"
            f"Started: {ev.start:%Y-%m-%d %H:%M} UTC\nThe event's own sources: {own_sources(ev, t)}")


def messages_for(ev: Event, t: OutletTable, lists: dict[str, Side], prompt: str = VERSION) -> list[dict]:
    menus = (f"Ready-made side lists (id: label. outlets):\n{menu_lists(t, lists)}\n\n"
             f"Outlet table (country code: id (name; wire; state media level)):\n{menu_outlets(t)}")
    return [{"role": "system", "content": PROMPTS[prompt]},
            {"role": "user", "content": [models.cache_block(menus), models.text_block(event_block(ev, t))]}]


def params_for(model: str = "") -> dict:
    p = dict(max_tokens=MAX_TOKENS, response_format=SCHEMA, timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        p["reasoning_effort"] = "low"
    return p


# ---- reading and checking the answer --------------------------------------------------------------

def parse(text: str) -> dict | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            d = None
    return d if isinstance(d, dict) else None


def problem(d: dict | None) -> str:
    """Why an answer can't be used ("" when it can)."""
    if d is None:
        return "not a JSON object"
    if d.get("kind") not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}"
    if d["kind"] == "world":
        for k in ("side_a", "side_b"):
            s = d.get(k)
            if not isinstance(s, dict) or not (str(s.get("label") or "").strip() or s.get("list")):
                return f"a world story needs two sides; {k} has no label and no list"
    return ""


def slug(text: str, n: int = 28) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:n].strip("_") or "side"


def build_side(raw: dict, t: OutletTable, lists: dict[str, Side], tag: str, flags: list[str]) -> Side:
    """A world side from the model's {label, list, outlets}: a ready-made list, plus or instead of
    outlets from the table. Unknown ids are dropped (and flagged); platforms never count."""
    label = str(raw.get("label") or "").strip()
    lid = str(raw.get("list") or "").strip()
    base = lists.get(lid)
    if lid and base is None:
        flags.append(f"side {tag}: unknown side list '{lid}' ignored")
    ids, unknown = [], []
    for i in (base.outlet_ids if base else []) + [str(x).strip() for x in raw.get("outlets") or []]:
        o = t.by_id.get(i)
        if o is None or o.is_platform:
            unknown.append(i)
        elif i not in ids:
            ids.append(i)
    if unknown:
        flags.append(f"side {tag}: dropped ids not in the outlet table: {', '.join(unknown[:8])}")
    extra = [i for i in ids if not base or i not in base.outlet_ids]
    if base and not extra:
        side = Side(base.side_id, base.label, ids)
    elif base:
        side = Side(f"{base.side_id}_plus", label or base.label, ids)
    else:
        side = Side(f"new_{slug(label or tag)}", label or f"side {tag}", ids)
    if not ids:
        flags.append(f"no outlets on file: {side.label}")
    return side


def build(d: dict, t: OutletTable, lists: dict[str, Side], source: str) -> Lens:
    """Turn a usable answer into a Lens, with code's checks as flags."""
    flags: list[str] = []
    reason = str(d.get("reason") or "").strip()
    kind = d["kind"]
    if kind == "us":
        us = us_sides(t)
        return Lens("us", [us["us_left"], us["us_right"]], source, None, reason=reason, flags=flags)
    if kind == "world":
        a = build_side(d["side_a"], t, lists, "a", flags)
        b = build_side(d["side_b"], t, lists, "b", flags)
        if a.side_id == b.side_id:
            b = Side(b.side_id + "_b", b.label, b.outlet_ids)
        shared = set(a.outlet_ids) & set(b.outlet_ids)
        if shared:
            flags.append(f"sides share outlets (they count for side a): {', '.join(sorted(shared)[:8])}")
        return Lens("world", [a, b], source, None, reason=reason, flags=flags)
    cc = str(d.get("local_press") or "").strip().upper()
    local = None
    if cc and cc != US_CODE:
        local = local_press(t, cc)
        if local is None:
            flags.append(f"no outlets on file for local press {cc}")
    elif cc == US_CODE:
        flags.append("no local press for a US story: the main searches already cover US outlets")
    return Lens("none", [], source, local, reason=reason, flags=flags, local_code=cc if cc != US_CODE else "")


# ---- the plain-code rule (fallback and eval baseline) --------------------------------------------

def rule_lens(ev: Event, t: OutletTable, lists: dict[str, Side], pairs=None, source="code:rule") -> Lens:
    cc = COUNTRY_CODES.get((ev.country or "").strip(), "")
    if cc == US_CODE:
        return build({"kind": "us", "reason": "A US story: left- against right-leaning US outlets (code rule)."},
                     t, lists, source)
    for a, b in pairs if pairs is not None else list_pairs():
        if a in lists and b in lists and cc and cc in (majority_country(t, lists[a]), majority_country(t, lists[b])):
            return build({"kind": "world", "reason": f"A ready-made pair of side lists covers {ev.country} (code rule).",
                          "side_a": {"label": "", "list": a, "outlets": []},
                          "side_b": {"label": "", "list": b, "outlets": []}}, t, lists, source)
    return build({"kind": "none", "local_press": cc,
                  "reason": "No ready-made side lists for this country, so no split (code rule)."}, t, lists, source)


# ---- choosing -------------------------------------------------------------------------------------

_call = calls.call      # one call; a failed call counts as an empty answer (stringer/calls.py)


def choose(ev: Event, t: OutletTable, complete=None, *, model: str = "", hide=(), lists=None, pairs=None,
           prompt: str = VERSION, name: str = "lens") -> tuple[Lens, dict]:
    """The story's sides. Returns (Lens, record); the record is what gather.json and the eval keep.
    With complete=None the plain-code rule decides (no model call)."""
    lists = lists if lists is not None else ready_lists(t, hide)
    rec = dict(version=prompt, model=model or None, calls=0, retried=False, fallback=False, errors=[],
               answer=None)
    if complete is None:
        lens = rule_lens(ev, t, lists, pairs)
        rec["chosen_by"] = "code:rule"
        return lens, dict(rec, **record_of(lens))
    msgs = messages_for(ev, t, lists, prompt)
    params = params_for(model)
    text, err = _call(complete, msgs, params, name)
    rec["calls"] = 1
    d = parse(text)
    why = problem(d) if not err else f"call failed: {err}"
    if err:
        rec["errors"].append(err)
    if why:
        rec["retried"] = True
        again = msgs + ([{"role": "assistant", "content": text}] if text else []) + \
            [{"role": "user", "content": RETRY_NOTE.format(why=why)}]
        text2, err2 = _call(complete, again, params, f"{name} retry")
        rec["calls"] = 2
        if err2:
            rec["errors"].append(err2)
        d = parse(text2)
        why = problem(d) if not err2 else f"call failed: {err2}"
    if why:
        lens = rule_lens(ev, t, lists, pairs, source="code:rule (fallback)")
        lens.flags.append(f"model answer unusable after one retry ({why}); the code rule chose")
        rec.update(fallback=True, chosen_by="code:rule (fallback)")
        return lens, dict(rec, **record_of(lens))
    rec["answer"] = d
    lens = build(d, t, lists, f"model:{model or 'lens'} {prompt}")
    rec["chosen_by"] = "model"
    return lens, dict(rec, **record_of(lens))


def record_of(lens: Lens) -> dict:
    """The lens as plain data (gather.json's lens record shape, plus reason and flags)."""
    side = lambda s: {"side_id": s.side_id, "label": s.label, "outlet_ids": list(s.outlet_ids)}
    return {"kind": lens.kind, "source": lens.source, "reason": lens.reason, "flags": list(lens.flags),
            "sides": [side(s) for s in lens.sides], "local": side(lens.local) if lens.local else None,
            "local_code": lens.local_code}


def live_complete(step: str = "lens", trace_id=None, metadata=None, model: str | None = None):
    """A `complete` for live runs of this step (calls.live_complete with this module's step as the default)."""
    return calls.live_complete(step, trace_id=trace_id, metadata=metadata, model=model)


def record_new_sides(ev: Event, lens: Lens, path=None) -> int:
    """Save a live run's new sides (not ready-made lists) for Jan to review. Never edits side_lists.csv."""
    new = [s for s in lens.sides if s.side_id.startswith("new_") or s.side_id.endswith("_plus")]
    if not new:
        return 0
    p = path or (paths.PRIVATE / "outlets" / "proposed_sides.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(p, "a", encoding="utf-8") as f:
        for s in new:
            f.write(json.dumps({"event": ev.id, "title": ev.title, "side_id": s.side_id, "label": s.label,
                                "outlet_ids": s.outlet_ids, "source": lens.source, "reason": lens.reason,
                                "at": at}, ensure_ascii=False) + "\n")
    return len(new)
