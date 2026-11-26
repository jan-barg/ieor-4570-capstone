"""Planted mistakes for the fact check eval (system map: Shared eval fixtures, the fabricated Story
Files; design agreed Nov 25, Jan).

Each test story gets two planted copies:
  "judge" copy  about 4 mistakes only the model judge can catch, each in a different group of
                fact_check.BATCH claims, so the judge sees one planted claim among real ones
  "code"  copy  2 mistakes the free paperwork pass must catch (no model call)
Mistakes a script can make (cards, addresses, dates, numbers) are made by scripts/plant_mistakes.py;
the rest are written by Claude in a hand-made file. The answer key is the record itself: what was
changed and the right outcome. Jan decided (Nov 25) the planted ones need no hand check.

A record: {id, story, copy, kind, made_by, claim, set: {claim field: new value}, new_facts: [fact
rows to add], sources: {source id: {field: new value}}, original: {...}, expect: {...}, note}.
"""
from __future__ import annotations

import copy
import datetime as dt
import random
import re

from .. import fact_check

# kind -> (copy, made by, the right outcome)
KINDS = {
    "no card": ("code", "script", "dropped"),
    "unknown article": ("code", "script", "card off"),
    "quote changed": ("code", "script", "card off"),
    "look-alike address": ("code", "script", "cards off"),
    "early date": ("code", "script", "cards off"),
    "wrong sides": ("code", "script", "sides fixed"),
    "swapped cards": ("judge", "script", "dropped"),
    "number changed": ("judge", "script", "dropped"),
    "date changed": ("judge", "script", "dropped"),
    "actors reversed": ("judge", "Claude", "dropped"),
    "attribution dropped": ("judge", "Claude", "named the speaker"),
    "hedge removed": ("judge", "Claude", "dropped"),
    "place changed": ("judge", "Claude", "dropped"),
    "contradicts the event": ("judge", "Claude", "dropped"),
}
CODE_KINDS = [k for k, v in KINDS.items() if v[0] == "code"]
JUDGE_SCRIPT_KINDS = [k for k, v in KINDS.items() if v[0] == "judge" and v[1] == "script"]
HAND_KINDS = [k for k, v in KINDS.items() if v[1] == "Claude"]
OUTCOMES = ("dropped", "named the speaker", "named the outlet", "confirmed", "unchecked")


# ---- applying records ----------------------------------------------------------------------------------

def apply(sf: dict, facts: list[dict], records: list[dict]) -> tuple[dict, list[dict]]:
    """A copy of the Story File and facts with the records' changes made."""
    sf = copy.deepcopy(sf)
    facts = [dict(f) for f in facts]
    cl = {c["id"]: c for c in sf["claims"]}
    src = {s["id"]: s for s in sf["sources"]}
    for r in records:
        if r.get("claim"):
            cl[r["claim"]].update(copy.deepcopy(r.get("set") or {}))
        facts += [dict(f) for f in r.get("new_facts") or []]
        for sid, ch in (r.get("sources") or {}).items():
            src[sid].update(ch)
    return sf, facts


# ---- scoring --------------------------------------------------------------------------------------------

def outcome(claim: dict) -> str:
    st = claim.get("status")
    if st == "say with source":
        return "named the speaker" if "a" in (claim.get("check") or {}).get("rules", []) else "named the outlet"
    return st if st in OUTCOMES else "unchecked"


def score_record(r: dict, checked: dict) -> dict:
    """{kind, expect, got, right, critical} for one record against the checked Story File."""
    cl = {c["id"]: c for c in checked["claims"]}
    exp = KINDS[r["kind"]][2]
    if KINDS[r["kind"]][0] == "judge":
        got = outcome(cl[r["claim"]])
        critical = got in ("confirmed", "named the outlet") or (exp == "dropped" and got == "named the speaker")
        return dict(kind=r["kind"], expect=exp, got=got, right=got == exp, critical=critical)
    if r["kind"] == "no card":
        got = "dropped" if cl[r["claim"]]["status"] == "dropped" else outcome(cl[r["claim"]])
    elif r["kind"] in ("unknown article", "quote changed"):
        want = set(r["expect"]["cards_off"])
        off = set((cl[r["claim"]].get("check") or {}).get("cards_off") or {})
        got = "card off" if want <= off else "card kept"
    elif r["kind"] in ("look-alike address", "early date"):
        want = set(r["expect"]["cards_off"])
        off = {x for c in checked["claims"] for x in ((c.get("check") or {}).get("cards_off") or {})}
        got = "cards off" if want <= off else f"{len(want - off)} of {len(want)} cards kept"
    else:                                                                    # wrong sides
        c = cl[r["claim"]]
        ok = c.get("sides") == r["expect"]["sides"] and (not r["expect"].get("blindspot_removed") or not c.get("blindspot"))
        got = "sides fixed" if ok else "sides kept"
    return dict(kind=r["kind"], expect=exp, got=got, right=got == exp, critical=got != exp)


# ---- making the mechanical ones -----------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
_YEAR = re.compile(r"^(19|20)\d\d$")


def change_number(text: str, quotes: list[str]) -> tuple[str, str, str] | None:
    """(new text, old number, new number) with one number changed to one that is in no quote, or None.
    Years and ordinals ("35th") are left alone."""
    for m in _NUMBER.finditer(text):
        old = m.group(1)
        after = text[m.end():m.end() + 2]
        if _YEAR.match(old) or re.match(r"(st|nd|rd|th)\b", after) or re.search(_MON + r"\s$", text[:m.start()]):
            continue                                       # a year, an ordinal, or a day of the month
        digits = old.replace(",", "")
        v = int(digits)
        new_v = v + 3 if v < 10 else int(str((int(digits[0]) % 9) + 1) + digits[1:])
        new = f"{new_v:,}" if "," in old else str(new_v)
        cand = text[:m.start(1)] + new + text[m.end(1):]
        if new not in fact_check.numbers_missing(cand, quotes):
            continue
        return cand, old, new
    return None


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"


def change_date(text: str) -> tuple[str, str, str] | None:
    """(new text, old, new) with a weekday moved two days or a day of the month moved three, or None."""
    m = re.search(r"\b(" + "|".join(DAYS) + r")\b", text)
    if m:
        new = DAYS[(DAYS.index(m.group(1)) + 2) % 7]
        return text[:m.start()] + new + text[m.end():], m.group(1), new
    for pat in (_MON + r"\s(\d{1,2})\b", r"\b(\d{1,2})\s" + _MON):
        m = re.search(pat, text)
        if m:
            g = 2 if m.group(2).isdigit() else 1
            d = int(m.group(g))
            nd = d + 3 if d <= 25 else d - 3
            s, e = m.span(g)
            return text[:s] + str(nd) + text[e:], m.group(0), text[m.start():s] + str(nd) + text[e:m.end()]
    return None


def lookalike_url(url: str) -> str:
    """The same page on a look-alike domain: theguardian.com becomes theguardian-news.com."""
    m = re.match(r"(https?://)([^/]+)(.*)", url)
    if not m:
        return url
    labels = m.group(2).split(".")
    i = len(labels) - 2
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "gov", "ac", "edu"):
        i = len(labels) - 3
    labels[i] = labels[i] + "-news"
    return m.group(1) + ".".join(labels) + m.group(3)


def swap_words(quote: str, rng: random.Random) -> str | None:
    w = quote.split(" ")
    spots = [i for i in range(len(w) - 1) if w[i] != w[i + 1] and len(w[i]) > 2 and len(w[i + 1]) > 2]
    if not spots:
        return None
    i = rng.choice(spots)
    w[i], w[i + 1] = w[i + 1], w[i]
    return " ".join(w)


def early(event_start: str, days: int = 30) -> str:
    t = dt.datetime.fromisoformat(event_start.replace("Z", "+00:00")) - dt.timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")
