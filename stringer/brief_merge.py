"""Module 5, step 2: merge step 1's fact cards into claims.

One merge call per story, on the same model as step 1 (config/models.toml), then up to four short calls
that only mark things on its claims: a retry for cards it left out, a conflict finder, a check of the
conflict pairs, and a check of the merge call's own conflict marks (merge_claims, mark_conflicts).
The merge call gets the event and the fact cards from step 1 (about 130 a
story at 10 articles): each card's sentence, kind, who says so and its English quote, grouped by
article under a number. No article text, no outlet names, no sides (decided Nov 24), so it can't
favour one side's version.

It returns claims: one checkable fact each, in neutral words, keeping who says so when the cards
attribute it, with the ids of every card behind it. When cards disagree (12 dead against 15),
both stay as separate claims marked as conflicting. Background cards become claims of kind
"background" (Nov 25: no history field).

Code then checks the answer: card ids that don't exist are dropped, a claim left with no card is
dropped, and cards that end up in no claim are counted (the model may leave out cards that aren't
about the event, like leftover menu text). Each claim keeps its cards' article ids and exact
quotes, so code can still check quotes and step 3 can count sides.

Never an unusable answer (decided Nov 25): enforced JSON schema, a generous output limit, one
retry for a broken answer or failed call, then the story is reported as failed, never guessed at.

    merge_story(event, step1, complete, *, model) -> {"claims", "dropped", "unused", "checks"}
"""
from __future__ import annotations

import json
import re

from . import brief_read
from .brief_read import KINDS

VERSION = "merge-14"         # merge-14 (default from Nov 25, Jan; 183 marked pairs -> 108, no real conflict lost): merge-11, and the merge call's own conflict marks also go through the
                             #          check call (they skipped it: on the Kyiv bridges live run ~25 casualty pairs were
                             #          marked though most agree; on the 26 test stories 83 of 183 marked pairs)
                             # merge-13 (tried Nov 25, not kept: 30 of 37 folds right, 2 wrong, finds ~1 in 5 repeats): the join keeps one claim's own words (the one that already says
                             #          everything), refuses a pair whose numbers differ (code), and a check call says
                             #          same / adds / differs per pair; only "same" joins
                             # merge-12 (tried Nov 25, dropped: 100 of 243 joins wrong, conflicts hidden, facts lost): merge-11, then a join pass: one call groups claims that state the
                             #          same fact (Kerch: 6+ claims said the arch fell), code merges each group
                             # merge-11: the check also calls numbers that fit together, different scopes or periods,
                             #          and a plan against what happened "none" (merge-10 still kept those)
                             # merge-10: merge-7's conflict pass finds candidates, then a second call checks each pair
                             #          (dispute / update / none) with when each claim was reported
                             # merge-9: the conflict pass lists disputed points with every claim on each side, and
                             #          keeps counts that rose over time apart as updates (merge-8 found half of the real pairs)
                             # merge-8: the conflict pass sees when each claim was reported and names the shared thing;
                             #          rising counts and different scopes are not conflicts (merge-7: about half wrong)
                             # merge-7: the conflict pass says yes or no per pair (merge-6 listed agreeing pairs too)
                             # merge-6: merge-5, then a separate call that finds conflicts between the claims
                             # merge-5: the same retry from 5% (merge-4 left real details out at 6-9%)
                             # merge-4: merge-3's prompt, plus one retry when over 10% of cards are in no claim
                             # merge-3: prompt keeps reactions and conflicting accounts, one account a claim, example
                             # merge-2: an answer with no claims is asked again once, like broken JSON
MAX_TOKENS = 32000          # about 5,000 expected; Opus can't turn thinking off, and thinking counts here
CALL_TIMEOUT_S = 600
QUOTE_CHARS = 240

SCHEMA = {"type": "json_schema", "json_schema": {"name": "claims", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["claims"],
    "properties": {"claims": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["claim", "kind", "who_says", "cards", "conflicts_with"],
        "properties": {
            "claim": {"type": "string"},
            "kind": {"type": "string", "enum": list(KINDS)},
            "who_says": {"type": "string"},
            "cards": {"type": "array", "items": {"type": "string"}},
            "conflicts_with": {"type": "array", "items": {"type": "integer"}}}}}}}}}

SYSTEM_2 = """You merge fact cards into claims for a news brief. The cards were taken from several news articles about one event; each has a short English sentence, its kind, who the article says it comes from, and the article's words (in English). You don't see the articles, which outlets wrote them, or which side each outlet is on.

Each claim:
- claim: one short English sentence with one checkable thing (who did what, where, when, how many). Use neutral words. If the cards say who it comes from (police, a ministry, a witness), keep that in the sentence ("Police said at least 12 people died."); state it plainly only when the cards give it on the articles' own authority.
- cards: the ids of every card that states this same fact. Cards from different articles that say the same thing go in one claim.
- kind: "event" (what happened), "number" (a count, amount or measurement), "statement" (what someone said or claimed), "reaction" (how others responded), or "background" (something that happened before this event).
- who_says: who the cards say the claim comes from ("police", "Ukraine's General Staff"; several, separated by "; "), or "the outlet" if no card attributes it.
- conflicts_with: the numbers of the claims it contradicts (1 for the first claim in your list), otherwise empty.

Rules:
- Every card about this event goes into a claim. Leave out only cards that are not about this event (other news, ads, site text).
- One claim per distinct fact: don't merge cards that say different things, and don't split one fact into several claims.
- A claim says no more than its cards: no added details, numbers, causes or judgments.
- When cards disagree on a number, a date, a place, who did it or what it was (12 dead against 15; "an attack" against "an accident"), keep each account as its own claim with who says so, and mark them as conflicting. A later, higher count is still its own claim, not a merge.
- A side's claim stays that side's claim ("Russia's Defense Ministry said ..."); don't decide which account is true.
- Most important claims first.

Answer with JSON only."""

SYSTEM_3 = """You merge fact cards into claims for a news brief. The cards were taken from several news articles about one event; each has a short English sentence, its kind, who the article says it comes from, and the article's words (in English). You don't see the articles, which outlets wrote them, or which side each outlet is on.

Each claim:
- claim: one short English sentence with one checkable thing (who did what, where, when, how many). Use neutral words. If the cards say who it comes from (police, a ministry, a witness), keep that in the sentence ("Police said at least 12 people died."); state it plainly only when the cards give it on the articles' own authority.
- cards: the ids of every card that states this same fact.
- kind: "event" (what happened), "number" (a count, amount or measurement), "statement" (what someone said or claimed), "reaction" (how others responded), or "background" (something that happened before this event).
- who_says: who the cards say the claim comes from ("police", "Ukraine's General Staff"; several, separated by "; "), or "the outlet" if no card attributes it.
- conflicts_with: the numbers of the claims it contradicts (1 for the first claim in your list), otherwise empty.

Rules:
- Every card about this event goes into a claim. If its fact is already a claim, add the card to that claim's cards; if not, write a new claim. Reactions and statements are facts too, however short or one-sided: what a government, state media, an official, a critic or an expert said or did. Leave out only cards not about this event (other news, ads, site text). Before answering, check that every card about the event is in some claim.
- A card goes into a claim only if it states that claim's fact with the same number, date, place and actor. A card that adds a different fact goes into a claim of its own.
- One claim holds one account. Never write "some said X, while Y said Z" or "reports differ": write one claim per account, each with who says so, and put each in the other's conflicts_with.
- Mark as conflicting only claims that give different accounts of the same thing: a different number for the same count, a different date or time for the same moment, damage called severe by one and minor by another, an attack blamed on different actors. Two events on different days (a first and a second strike) are separate claims, not a conflict.
- A claim says no more than its cards: no added details, numbers, causes or judgments.
- A side's claim stays that side's claim ("Russia's Defense Ministry said ..."); don't decide which account is true.
- Most important claims first.

Example (made-up cards):
F1 [number; who: police] Police said 12 people died.
F2 [number; who: the health ministry] The health ministry said 15 people died.
F3 [event; who: the outlet] The bridge collapsed on Friday.
F4 [event; who: the outlet] The bridge fell into the river on Friday.
F5 [reaction; who: the opposition] The opposition called the collapse a disgrace.
F6 [statement; who: the mayor] The mayor said the damage was minor.
Claims:
1. "The bridge collapsed into the river on Friday." cards F3, F4; conflicts_with [4]
2. "Police said 12 people died." cards F1; conflicts_with [3]
3. "The health ministry said 15 people died." cards F2; conflicts_with [2]
4. "The mayor said the damage was minor." cards F6; conflicts_with [1]
5. "The opposition called the collapse a disgrace." cards F5; kind reaction

Answer with JSON only."""

PROMPTS = {"merge-2": SYSTEM_2, "merge-3": SYSTEM_3, "merge-4": SYSTEM_3, "merge-5": SYSTEM_3, "merge-6": SYSTEM_3,
           "merge-7": SYSTEM_3, "merge-8": SYSTEM_3,
           "merge-9": SYSTEM_3, "merge-10": SYSTEM_3,
           "merge-11": SYSTEM_3, "merge-12": SYSTEM_3, "merge-13": SYSTEM_3, "merge-14": SYSTEM_3}
# versions that ask again when more than this share of cards is left out; merge-3 sometimes stopped
# early (3 claims for 143 cards on measles); at 10%, merge-4 still left real details out at 6-9%
COMPLETE_RETRY = {"merge-4": 0.10, "merge-5": 0.05, "merge-6": 0.05, "merge-7": 0.05, "merge-8": 0.05, "merge-9": 0.05, "merge-10": 0.05, "merge-11": 0.05, "merge-12": 0.05, "merge-13": 0.05, "merge-14": 0.05}
# versions that run the conflict pass: merge-5 kept accounts apart but often didn't mark them
# (Kerch: "two killed" against "no casualties"; Ebola: symptoms from October 6 against October 7)
CONFLICT_PASS = {"merge-6": 1, "merge-7": 2, "merge-8": 3, "merge-9": 4, "merge-10": 2, "merge-11": 2, "merge-12": 2, "merge-13": 2, "merge-14": 2}
# versions that check each candidate pair in a second call (merge-7 found 79% of real conflicts, but only
# about a fifth of its pairs were real; finding and judging in one call didn't fix that in merge-8 or merge-9)
VERIFY = {"merge-10": 1, "merge-11": 2, "merge-12": 2, "merge-13": 2, "merge-14": 2}     # version -> check prompt     # version -> conflict prompt and schema
# versions that also check the merge call's own conflict marks; before, only the conflict pass's pairs were checked
OWN_CHECK = {"merge-14"}
SYSTEM = PROMPTS[VERSION]

RETRY_JSON = brief_read.RETRY_JSON
RETRY_EMPTY = "Your answer had no claims. Merge the fact cards into claims and answer again with JSON only."
RETRY_INCOMPLETE = ("These cards are in no claim: {ids}. Every card about this event must be in a claim. "
                    "Answer again with the full list of claims: add each of these cards to the claim that states "
                    "its fact, or write a new claim for it. Leave out only cards not about this event. JSON only.")


# ---- the call -----------------------------------------------------------------------------------------

def cards_of(step1: dict) -> list[dict]:
    """Step 1's kept cards for a story, in article order, each with its short id (F1, F2, ...) and
    the number of the article it came from."""
    out = []
    for n, a in enumerate([a for a in step1.get("articles") or [] if a.get("facts")], 1):
        for f in a["facts"]:
            out.append(dict(f, short=f"F{len(out) + 1}", art_n=n, article=a["article"]))
    return out


def messages_for(event: dict, cards: list[dict], prompt: str = VERSION) -> list[dict]:
    ev = (f"Event: {event.get('title', '')}\n{event.get('summary', '')}\n"
          f"Started: {(event.get('start') or '')[:16].replace('T', ' ')} UTC")
    lines, last = [], None
    for c in cards:
        if c["art_n"] != last:
            lines.append(f"\nArticle {c['art_n']}")
            last = c["art_n"]
        q = (c.get("quote_en") or c.get("quote") or "")[:QUOTE_CHARS]
        lines.append(f"{c['short']} [{c['kind']}; who: {c['who_says']}] {c['fact']}  (words: \"{q}\")")
    return [{"role": "system", "content": PROMPTS[prompt]},
            {"role": "user", "content": f"{ev}\n\nFact cards ({len(cards)}):" + "\n".join(lines)}]


def params_for(model: str) -> dict:
    p = dict(max_tokens=MAX_TOKENS, response_format=SCHEMA, timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        p["reasoning_effort"] = "low"
    return p


def _parse(text: str) -> dict | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    for cand in (t, (re.search(r"\{.*\}", t, re.S) or [None])[0]):
        if not cand:
            continue
        try:
            d = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and isinstance(d.get("claims"), list):
            return d
    return None


def _ask(complete, messages, params, name):
    """One call plus one retry when the answer isn't usable: not JSON, a failed call, or no claims
    at all (merge-2: DeepSeek once answered {"claims": []} for 136 cards)."""
    text, err = brief_read._call(complete, messages, params, name)
    d = _parse(text)
    if _has_claims(d):
        return d, 1, []
    note = RETRY_EMPTY if d is not None else RETRY_JSON
    again = messages + ([{"role": "assistant", "content": text}] if text else []) + [{"role": "user", "content": note}]
    text2, err2 = brief_read._call(complete, again, params, f"{name} retry")
    d2 = _parse(text2)
    return (d2 if _has_claims(d2) else None), 2, [e for e in (err, err2) if e]


def _has_claims(d: dict | None) -> bool:
    """At least one claim with words and a card id (DeepSeek once sent a single blank claim)."""
    return d is not None and any(isinstance(x, dict) and (x.get("claim") or "").strip()
                                 and any(str(s).strip() for s in x.get("cards") or []) for x in d["claims"])


# ---- the conflict pass ---------------------------------------------------------------------------------

CONFLICT_SCHEMA = {"type": "json_schema", "json_schema": {"name": "conflicts", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["conflicts"],
    "properties": {"conflicts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["a", "b", "why"],
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "why": {"type": "string"}}}}}}}}

CONFLICT_SYSTEM = """You find conflicts between the claims of a news brief about one event. Two claims conflict when they give different accounts of the same thing, so they can't both be fully right:
- a different number for the same count ("12 people died" against "15 people died"; "21 missiles" against "about 30 missiles");
- a different date or time for the same moment ("symptoms began on October 6" against "on October 7");
- a different account of what happened or how bad it was ("the span collapsed into the sea" against "the damage was minor"; "no casualties" against "two people were killed");
- a different actor blamed, or a denial against a claim ("Russia said a drone hit the plant" against "Ukraine denied any strike there").

Not conflicts:
- claims about different things, places or moments (two strikes on different days; a count the claims themselves say rose over time);
- claims that agree, or where one only adds detail to the other;
- the same account told by different sources.

List every conflicting pair once, using the claim ids exactly as given, with a few words on why. If there are none, give an empty list. Answer with JSON only."""

CONFLICT_SCHEMA_2 = {"type": "json_schema", "json_schema": {"name": "conflicts", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["pairs"],
    "properties": {"pairs": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["a", "b", "why", "conflict"],
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "why": {"type": "string"},
                       "conflict": {"type": "boolean"}}}}}}}}

CONFLICT_SYSTEM_2 = """You find conflicts between the claims of a news brief about one event. Two claims conflict when they give different accounts of the same thing, so they can't both be fully right:
- a different number for the same count ("12 people died" against "15 people died"; "more than 6,600 flights were cancelled" against "nearly 5,000");
- a different date or time for the same moment ("symptoms began on October 6" against "on October 7"; "lifted at 8:15 p.m." against "lifted at 8:30 p.m.");
- a different account of what happened or how bad it was ("the span collapsed into the sea" against "the damage was minor"; "no casualties" against "two people were killed");
- a different actor blamed, or a denial against a claim ("Russia said a drone hit the plant" against "Ukraine denied any strike there").

Not conflicts:
- claims about different things, places or moments (two strikes on different days; a count the claims themselves say rose over time);
- stages of a developing story ("the ground stop remains in effect" and later "the ground stop was lifted");
- the same thing said in other words or with more detail ("about 8:15 p.m." and "8:15 p.m."; "on Tuesday" and "on November 17" when that was a Tuesday);
- the same account told by different sources, or two statements that can both be true.

For each pair of claims you check, give both claim ids exactly as given, a few words on why, and conflict: true only if they really give different accounts of the same thing, otherwise false. Answer with JSON only."""

CONFLICT_SCHEMA_3 = {"type": "json_schema", "json_schema": {"name": "conflicts", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["pairs"],
    "properties": {"pairs": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["a", "b", "same_thing", "why", "conflict"],
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "same_thing": {"type": "string"},
                       "why": {"type": "string"}, "conflict": {"type": "boolean"}}}}}}}}

CONFLICT_SYSTEM_3 = """You find conflicts between the claims of a news brief about one event. Each claim shows when the articles behind it were published.

Two claims conflict only when they describe the same thing, at the same point in the story, and can't both be right:
- a different number for the same count at the same time ("12 people died" against "15 people died", both reported that morning);
- a different date or time for the same moment ("symptoms began on October 6" against "on October 7");
- a different account of what happened or how bad it was ("the span collapsed into the sea" against "the damage was minor"; "no one was hurt in the blast" against "the blast killed two people");
- a different actor blamed, or a denial against a claim ("Russia said a drone hit the plant" against "Ukraine denied any strike there").

Not conflicts:
- a running count reported at different times (dead, injured, arrested, flights cancelled): a higher number in a later report is an update. It is a conflict only when reports a few hours apart or less give different numbers for the same moment;
- different scopes: one day against a whole week, one district against the region, one airline or country against all of them, one month's forecast against another's;
- different moments or stages of the story ("the ground stop remains in effect", later "the ground stop was lifted");
- the same thing in other words or with more detail; two statements that can both be true; claims about unrelated things.

For each pair you check, give both claim ids exactly as given, the one thing both claims are about (same_thing), a few words on why, and conflict: true only if they give different accounts of that same thing. When unsure, conflict: false. Answer with JSON only."""

CONFLICT_SCHEMA_4 = {"type": "json_schema", "json_schema": {"name": "points", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["points"],
    "properties": {"points": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["thing", "type", "accounts"],
        "properties": {"thing": {"type": "string"}, "type": {"type": "string", "enum": ["dispute", "update"]},
                       "accounts": {"type": "array", "items": {
                           "type": "object", "additionalProperties": False, "required": ["claims", "says"],
                           "properties": {"claims": {"type": "array", "items": {"type": "string"}},
                                          "says": {"type": "string"}}}}}}}}}}}

CONFLICT_SYSTEM_4 = """You find the points where the claims of a news brief about one event give different accounts of the same thing. Each claim shows when the articles behind it were published (UTC).

Group the claims by what they are about (the death toll, the cause, the damage, who did it, when something happened, a count), then check within each group whether the claims tell the same story.

List a point when its claims give different accounts of the same thing:
- type "dispute": the accounts can't all be right. Different numbers for the same count reported at about the same time (a few hours apart or less); a different date or time for the same moment; a different account of what happened or how bad it was ("the span collapsed into the sea" against "the damage was minor"); a different cause or actor ("hit a naval mine" against "struck by a missile"); a denial against a claim;
- type "update": the account changed as the story developed. A running count (dead, injured, arrested, flights cancelled) that is higher in later reports, or a status that changed (closed, later reopened).

Not a point at all:
- claims about different scopes (one day against a whole week, one district against the region, one airline against all of them), different moments, or different things;
- the same account in other words or with more detail; statements that can both be true.

For each point give the thing it is about, its type, and two or more accounts. Each account lists the ids of every claim that gives it, exactly as given, and says in a few words what they say. Put each claim in at most one account of a point. If there are no points, give an empty list. Answer with JSON only."""

CONFLICT_SYSTEMS = {1: CONFLICT_SYSTEM, 2: CONFLICT_SYSTEM_2, 3: CONFLICT_SYSTEM_3, 4: CONFLICT_SYSTEM_4}
CONFLICT_SCHEMAS = {1: CONFLICT_SCHEMA, 2: CONFLICT_SCHEMA_2, 3: CONFLICT_SCHEMA_3, 4: CONFLICT_SCHEMA_4}
CONFLICT_MAX_TOKENS = 8000


def _when(t: str) -> str:
    """'2026-11-17T05:15:42Z' -> 'Nov 17 05:15' (UTC)."""
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    try:
        return f"{months[int(t[5:7]) - 1]} {int(t[8:10])} {t[11:16]}".strip()
    except (ValueError, IndexError):
        return ""


def reported(claim: dict, times: dict | None) -> str:
    """When the articles behind a claim were published: 'Nov 17 05:15' or 'Nov 17 05:15 to Nov 18 09:02'."""
    ts = sorted(t for t in ((times or {}).get(a) for a in claim.get("articles") or []) if t)
    if not ts:
        return "unknown"
    first, last = _when(ts[0]), _when(ts[-1])
    return first if first == last else f"{first} to {last}"


def conflict_messages(event: dict, claims: list[dict], variant: int = 2, times: dict | None = None) -> list[dict]:
    """The claims only (no cards). From variant 3 each claim also shows when it was reported (UTC);
    times maps article id -> published time."""
    if variant >= 3:
        lines = [f"{c['id']} [{c['kind']}; who: {c['who_says']}; reported: {reported(c, times)}] {c['claim']}" for c in claims]
    else:
        lines = [f"{c['id']} [{c['kind']}; who: {c['who_says']}] {c['claim']}" for c in claims]
    return [{"role": "system", "content": CONFLICT_SYSTEMS[variant]},
            {"role": "user", "content": f"Event: {event.get('title', '')}\n\nClaims ({len(claims)}):\n" + "\n".join(lines)}]


def find_conflicts(event: dict, claims: list[dict], complete, *, model: str = "", name: str = "brief_merge conflicts",
                   variant: int = 2, times: dict | None = None):
    """The conflict pass: one call over the claims (no cards). Returns (pairs, calls, error); a pair is
    (claim id, claim id, why). An unusable answer is asked again once; if that fails too, no pairs are
    added and the error is recorded (the merge's own conflicts stay)."""
    ids = {c["id"] for c in claims}
    params = dict(max_tokens=CONFLICT_MAX_TOKENS, response_format=CONFLICT_SCHEMAS[variant],
                  timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        params["reasoning_effort"] = "low"
    msgs = conflict_messages(event, claims, variant, times)
    errs = []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": RETRY_JSON}],
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
        key_name = "conflicts" if variant == 1 else "pairs"
        if isinstance(d, dict) and isinstance(d.get(key_name), list):
            pairs, seen = [], set()
            for x in d[key_name]:
                if not isinstance(x, dict) or (variant != 1 and x.get("conflict") is not True):
                    continue
                a, b = str(x.get("a", "")).strip(), str(x.get("b", "")).strip()
                key = tuple(sorted((a, b)))
                if a in ids and b in ids and a != b and key not in seen:
                    seen.add(key)
                    why = str(x.get("why", ""))
                    if x.get("same_thing"):
                        why = f"{x['same_thing']}: {why}"
                    pairs.append((a, b, why[:300]))
            return pairs, attempt + 1, None
    return [], 2, "no usable conflict answer after one retry" + (f" ({errs[-1]})" if errs else "")


def _clean_points(raw, ids: set) -> list[dict]:
    """Points with a known type and at least two accounts that each name a known claim; a claim stays in
    the first account of a point that names it."""
    out = []
    for x in raw:
        if not isinstance(x, dict) or x.get("type") not in ("dispute", "update"):
            continue
        seen, accounts = set(), []
        for a in x.get("accounts") or []:
            if not isinstance(a, dict):
                continue
            cs = []
            for c in a.get("claims") or []:
                c = str(c).strip()
                if c in ids and c not in seen:
                    seen.add(c)
                    cs.append(c)
            if cs:
                accounts.append(dict(claims=cs, says=str(a.get("says", ""))[:200]))
        if len(accounts) >= 2:
            out.append(dict(thing=str(x.get("thing", ""))[:200], type=x["type"], accounts=accounts))
    return out


def find_points(event: dict, claims: list[dict], complete, *, model: str = "", name: str = "brief_merge conflicts",
                times: dict | None = None):
    """The conflict pass from merge-9: one call that lists disputed points and updates, each with its
    accounts. Returns (points, calls, error), asked again once like find_conflicts."""
    ids = {c["id"] for c in claims}
    params = dict(max_tokens=CONFLICT_MAX_TOKENS, response_format=CONFLICT_SCHEMA_4, timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        params["reasoning_effort"] = "low"
    msgs = conflict_messages(event, claims, 4, times)
    errs = []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": RETRY_JSON}],
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
        if isinstance(d, dict) and isinstance(d.get("points"), list):
            return _clean_points(d["points"], ids), attempt + 1, None
    return [], 2, "no usable conflict answer after one retry" + (f" ({errs[-1]})" if errs else "")


def point_pairs(points: list[dict]) -> list[tuple]:
    """Claim pairs on different sides of each disputed point (updates are not conflicts)."""
    pairs, seen = [], set()
    for p in points:
        if p["type"] != "dispute":
            continue
        acc = p["accounts"]
        for i in range(len(acc)):
            for j in range(i + 1, len(acc)):
                for a in acc[i]["claims"]:
                    for b in acc[j]["claims"]:
                        key = tuple(sorted((a, b)))
                        if a != b and key not in seen:
                            seen.add(key)
                            pairs.append((a, b, f"{p['thing']}: {acc[i]['says']} / {acc[j]['says']}"[:300]))
    return pairs


VERIFY_SCHEMA = {"type": "json_schema", "json_schema": {"name": "checks", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["checks"],
    "properties": {"checks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["pair", "same_thing", "why", "verdict"],
        "properties": {"pair": {"type": "integer"}, "same_thing": {"type": "string"}, "why": {"type": "string"},
                       "verdict": {"type": "string", "enum": ["dispute", "update", "none"]}}}}}}}}

VERIFY_SYSTEM = """You check possible conflicts between the claims of a news brief about one event. Each pair shows two claims, who says each, and when the articles behind each were published (UTC; a date alone means the time is unknown).

For each pair decide:
- "dispute": both claims are about the same thing and can't both be right. Different dates or times for the same moment; different accounts of what happened, how bad it was, its cause or who did it ("the span collapsed into the sea" against "the damage was minor"; "hit a naval mine" against "struck by a missile"); a denial against a claim; different numbers for the same count when they are not simply an older and a newer figure: two sources at about the same time, a later report with a lower number, or a number that doesn't change (a final result, a past event's toll, a total for a stated period);
- "update": the same thing, but the story moved on: a running count (dead, injured, missing, arrested, flights cancelled) that is higher in a later report, or a status that changed (closed, later reopened);
- "none": anything else. Different scopes (one day against a week, one district against the region, one airline against all of them), different moments or events, the same account in other words or rounded, or statements that can both be true.

For every pair give its number, the one thing both claims are about (same_thing), a few words on why, and the verdict. Answer with JSON only."""


VERIFY_SYSTEM_2 = """You check possible conflicts between the claims of a news brief about one event. Each pair shows two claims, who says each, and when the articles behind each were published (UTC; a date alone means the time is unknown).

For each pair decide:
- "dispute": both claims are about exactly the same thing and can't both be right. Different dates or times for the same moment; different accounts of what happened, how bad it was, its cause or who did it ("the span collapsed into the sea" against "the damage was minor"; "hit a naval mine" against "struck by a missile"); a denial against a claim; different numbers for the same count when they are not simply an older and a newer figure: two sources at about the same time, a later report with a lower number, or a number that doesn't change (a final result, a past event's toll, a total for a stated period);
- "update": the same thing, but the story moved on: a running count (dead, injured, missing, arrested, flights cancelled) that is higher in a later report, or a status that changed (closed, later reopened);
- "none": anything else, including:
  - numbers that fit together: "more than 500,000" and "550,000"; "$6.3 billion" and "about $6.36 billion"; "hundreds" and "over 800"; one named ship and "two ships sank";
  - different scopes or periods, even when they overlap: October 1 to 11 against October 6 to 14; Monday against Sunday; police officers against police, gendarmes and firefighters; the capital against the capital region; deployed against total;
  - a plan, forecast or expectation against what happened ("set to last under an hour" and "lasted an hour and a half");
  - different moments or events, the same account in other words, or statements that can both be true.

Choose "dispute" only when you can say exactly why both claims can't be right; if your reason mentions different scopes, periods, days or events, the verdict is "none". For every pair give its number, the one thing both claims are about (same_thing), a few words on why, and the verdict. Answer with JSON only."""

VERIFY_SYSTEMS = {1: VERIFY_SYSTEM, 2: VERIFY_SYSTEM_2}


def verify_messages(event: dict, claims: list[dict], pairs, times: dict | None = None, variant: int = 1) -> list[dict]:
    by = {c["id"]: c for c in claims}

    def line(cid):
        c = by[cid]
        return f"  {cid} [{c['kind']}; who: {c['who_says']}; reported: {reported(c, times)}] {c['claim']}"
    body = "\n".join(f"P{i}\n{line(a)}\n{line(b)}" for i, (a, b, _) in enumerate(pairs, 1))
    return [{"role": "system", "content": VERIFY_SYSTEMS[variant]},
            {"role": "user", "content": f"Event: {event.get('title', '')}\n\nPairs ({len(pairs)}):\n{body}"}]


def verify_pairs(event: dict, claims: list[dict], pairs, complete, *, model: str = "",
                 name: str = "brief_merge verify", times: dict | None = None, variant: int = 1):
    """Checks each candidate pair. Returns (disputes, updates, calls, error, unchecked): disputes and
    updates are pairs with the checker's reason; a pair it skipped counts as unchecked and is not kept."""
    params = dict(max_tokens=CONFLICT_MAX_TOKENS, response_format=VERIFY_SCHEMA, timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        params["reasoning_effort"] = "low"
    msgs = verify_messages(event, claims, pairs, times, variant)
    errs = []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": RETRY_JSON}],
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
        if isinstance(d, dict) and isinstance(d.get("checks"), list):
            verdicts = {}
            for x in d["checks"]:
                if isinstance(x, dict) and isinstance(x.get("pair"), int) and 1 <= x["pair"] <= len(pairs):
                    verdicts.setdefault(x["pair"], x)
            disputes, updates = [], []
            for i, (a, b, _) in enumerate(pairs, 1):
                x = verdicts.get(i)
                why = f"{x.get('same_thing', '')}: {x.get('why', '')}"[:300] if x else ""
                if x and x.get("verdict") == "dispute":
                    disputes.append((a, b, why))
                elif x and x.get("verdict") == "update":
                    updates.append((a, b, why))
            return disputes, updates, attempt + 1, None, len(pairs) - len(verdicts)
    return None, [], 2, "no usable check answer after one retry" + (f" ({errs[-1]})" if errs else ""), len(pairs)


def own_check(event: dict, out: dict, disputes: list, found: list, complete, *, model: str = "", times=None,
              variant: int = 2) -> tuple[list, int]:
    """merge-14: the merge call's own conflict marks go through the check call too. A mark the check
    already judged (the conflict pass found it as well) takes that verdict; the rest are checked in one
    more call. Clears every claim's marks and returns (disputes to mark, calls); updates join
    out["updates"]. If the extra call fails twice, the unchecked marks are kept, as in merge-11."""
    claims = out["claims"]
    own = sorted({tuple(sorted((c["id"], o))) for c in claims for o in c["conflicts_with"]})
    judged = {tuple(sorted((a, b))) for a, b, _ in found}
    todo = [(a, b, "marked by the merge call") for a, b in own if (a, b) not in judged]
    d2, u2, calls, err, unchecked = ([], [], 0, None, 0)
    if todo:
        d2, u2, calls, err, unchecked = verify_pairs(event, claims, todo, complete, model=model,
                                                    name="brief_merge verify own", times=times, variant=variant)
        if d2 is None:                                 # the check failed: keep the merge call's marks
            d2, u2 = todo, []
    for c in claims:
        c["conflicts_with"] = []
    known = {tuple(sorted((a, b))) for a, b, _ in disputes}
    disputes = disputes + [p for p in d2 if tuple(sorted(p[:2])) not in known]
    out["updates"] = (out.get("updates") or []) + [dict(a=a, b=b, why=w) for a, b, w in u2]
    kept = {tuple(sorted(p[:2])) for p in disputes}
    upd = {tuple(sorted((u["a"], u["b"]))) for u in out["updates"]}
    out["own_marks"] = [dict(a=a, b=b, checked=("before" if (a, b) in judged else "own call"),
                             verdict="dispute" if (a, b) in kept else "update" if (a, b) in upd else "none")
                        for a, b in own]
    out["checks"].update(own_marks=len(own), own_marks_kept=sum(m["verdict"] == "dispute" for m in out["own_marks"]),
                         own_marks_updates=sum(m["verdict"] == "update" for m in out["own_marks"]),
                         own_check_error=err, own_unchecked=unchecked)
    return disputes, calls


def add_conflicts(claims: list[dict], pairs) -> int:
    """Marks each pair on both claims. Returns how many pairs were new."""
    by = {c["id"]: c for c in claims}
    new = 0
    for a, b, _ in pairs:
        if b not in by[a]["conflicts_with"] or a not in by[b]["conflicts_with"]:
            new += 1
        for x, y in ((a, b), (b, a)):
            if y not in by[x]["conflicts_with"]:
                by[x]["conflicts_with"].append(y)
    return new


# ---- the join pass (merge-12) -------------------------------------------------------------------------

JOIN = {"merge-12": 1, "merge-13": 2}      # version -> join variant (after the conflict check)
JOIN_MAX_TOKENS = 8000


def join_schema(ids: list[str]) -> dict:
    group = {"type": "object", "additionalProperties": False, "required": ["claims", "claim", "who_says", "why"],
             "properties": {"claims": {"type": "array", "items": {"type": "string", "enum": ids}},
                            "claim": {"type": "string"}, "who_says": {"type": "string"}, "why": {"type": "string"}}}
    return {"type": "json_schema", "json_schema": {"name": "repeats", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["groups"],
        "properties": {"groups": {"type": "array", "items": group}}}}}


JOIN_SYSTEM = """You check the claims of a news brief about one event for repeats. The claims were merged from many articles' fact cards in one pass, and sometimes the same fact ended up in two or more claims: worded differently, credited to different sources, or one with a little more detail.

Find every group of claims that state the same fact: the same event, number, date, place and actor. For each group give:
- claims: the ids of the claims in the group (two or more).
- claim: one short English sentence for the joined claim, in neutral words. Say only what at least one of the group's claims says, and keep every detail any of them gives.
- who_says: who the group's claims say it comes from, several separated by "; ", or "the outlet" if none of them credits a source. If any claim credits a source, keep that source in the sentence ("Ukraine's General Staff said ...").
- why: a few words on why they are the same fact.

Rules:
- Join only repeats. Claims that give different facts stay apart, even on the same topic: the House count and the Senate count, flights delayed and flights cancelled, a first strike and a second strike, an event and someone's reaction to it, a fact and the background before it.
- Never join claims that disagree. A different number, date, time or cause for the same thing is a conflict, not a repeat. Pairs already marked as conflicting or as an update are listed; never put both claims of such a pair in one group.
- The same fact from two speakers (two officials who both say the span collapsed) is one fact: join it and name both in who_says. A speaker's claim and the same fact stated by an outlet on its own authority are one fact too.
- One side's account stays that side's: never join it with a different account from the other side.
- Each claim goes in at most one group. Leave out claims that have no repeat.

Answer with JSON only: {"groups": [...]}, with an empty list if there are no repeats."""


def join_messages(event: dict, claims: list[dict], updates=()) -> list[dict]:
    lines = [f"{c['id']} [{c['kind']}; who: {c['who_says']}] {c['claim']}" for c in claims]
    seen, marked = set(), []
    for c in claims:
        for o in c.get("conflicts_with") or []:
            key = tuple(sorted((c["id"], o)))
            if key not in seen:
                seen.add(key)
                marked.append(f"{key[0]} and {key[1]} (conflict)")
    for u in updates or []:
        marked.append(f"{u['a']} and {u['b']} (update)")
    body = f"Event: {event.get('title', '')}\n\nClaims ({len(claims)}):\n" + "\n".join(lines)
    body += "\n\nPairs that must stay apart:\n" + ("\n".join(marked) if marked else "none")
    return [{"role": "system", "content": JOIN_SYSTEM}, {"role": "user", "content": body}]


def find_joins(event: dict, claims: list[dict], complete, *, model: str = "", name: str = "brief_merge join",
               updates=()):
    """One call over the claims. Returns (groups, calls, error); a group is {claims, claim, who_says, why}.
    An unusable answer is asked again once; if that fails too, nothing is joined and the error is recorded."""
    ids = [c["id"] for c in claims]
    params = dict(max_tokens=JOIN_MAX_TOKENS, response_format=join_schema(ids), timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        params["reasoning_effort"] = "low"
    msgs = join_messages(event, claims, updates)
    errs = []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": RETRY_JSON}],
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
        if isinstance(d, dict) and isinstance(d.get("groups"), list):
            groups = [dict(claims=[str(i).strip() for i in g.get("claims") or []], claim=str(g.get("claim") or "").strip(),
                           who_says=str(g.get("who_says") or "").strip(), why=str(g.get("why") or "").strip()[:300])
                      for g in d["groups"] if isinstance(g, dict)]
            return groups, attempt + 1, None
    return [], 2, "no usable join answer after one retry" + (f" ({errs[-1]})" if errs else "")


def join_claims(claims: list[dict], groups: list[dict], updates=()) -> tuple[list, list, list, dict]:
    """Merges each group into its first claim (the most important). A group loses claims already in an
    earlier group or unknown ids; a group holding a conflict or update pair is rejected whole.
    Returns (claims, joined, rejected, {removed id: kept id})."""
    by = {c["id"]: c for c in claims}
    order = {c["id"]: i for i, c in enumerate(claims)}
    apart = {frozenset((c["id"], o)) for c in claims for o in c.get("conflicts_with") or []}
    apart |= {frozenset((u["a"], u["b"])) for u in updates or []}
    used, joined, rejected, remap = set(), [], [], {}
    for g in groups:
        ids = sorted({i for i in g["claims"] if i in by and i not in used}, key=order.get)
        if len(ids) < 2:
            continue
        clash = [sorted(p) for p in apart if p <= set(ids)]
        if clash:
            rejected.append(dict(claims=ids, why=g["why"], reason=f"holds a pair that must stay apart: {clash[0]}"))
            continue
        keep, rest = by[ids[0]], [by[i] for i in ids[1:]]
        before = {c["id"]: c["claim"] for c in [keep] + rest}
        speakers = list(dict.fromkeys(w.strip() for c in [keep] + rest for w in c["who_says"].split(";")
                                      if w.strip() and w.strip() != "the outlet"))
        keep["claim"] = g["claim"] or keep["claim"]
        keep["who_says"] = g["who_says"] or "; ".join(speakers) or "the outlet"
        for c in rest:
            for s in c["sources"]:
                if s["fact"] not in keep["facts"]:
                    keep["facts"].append(s["fact"])
                    keep["sources"].append(s)
            keep["conflicts_with"] += [o for o in c["conflicts_with"] if o not in keep["conflicts_with"]]
            remap[c["id"]] = keep["id"]
        keep["articles"] = sorted({s["article"] for s in keep["sources"]})
        used.update(ids)
        joined.append(dict(keep=keep["id"], joined=[c["id"] for c in rest], before=before, claim=keep["claim"],
                           who_says=keep["who_says"], why=g["why"]))
    out = [c for c in claims if c["id"] not in remap]
    for c in out:
        c["conflicts_with"] = [x for x in dict.fromkeys(remap.get(o, o) for o in c["conflicts_with"]) if x != c["id"]]
    return out, joined, rejected, remap


# merge-13: no rewording. The join call names, per group, the claim whose sentence already says everything
# the others say; code refuses a pair whose numbers differ; a check call then says same / adds / differs
# for each pair, and only "same" joins. merge-12 let the model rewrite, and 100 of its 243 joins were wrong.

def join_schema_2(ids: list[str]) -> dict:
    group = {"type": "object", "additionalProperties": False, "required": ["keep", "others", "why"],
             "properties": {"keep": {"type": "string", "enum": ids},
                            "others": {"type": "array", "items": {"type": "string", "enum": ids}},
                            "why": {"type": "string"}}}
    return {"type": "json_schema", "json_schema": {"name": "repeats", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["groups"],
        "properties": {"groups": {"type": "array", "items": group}}}}}


JOIN_SYSTEM_2 = """You check the claims of a news brief about one event for repeats. The claims were merged from many articles' fact cards in one pass, and sometimes the same fact ended up in two claims, worded differently or credited to different sources.

A repeat is a claim that says nothing another claim doesn't already say, apart from who says it. For each group of repeats give:
- keep: the claim whose sentence already says everything the others in the group say (every number, name, date, place and hedge such as "may have" or "reportedly").
- others: the claims that say nothing beyond keep, apart from who says it.
- why: a few words.

Rules:
- Only true repeats. If a claim adds anything keep doesn't say (a number, a time, a cause, a second fact), it is not a repeat: leave it out.
- Never group claims that disagree: a different number, date, time, place or cause for the same thing, or two sides' different accounts. Pairs already marked as conflicting or as an update are listed; never group them.
- Different topics stay apart even if they sound alike: the House count and the Senate count, flights delayed and flights cancelled, an event and a reaction to it, a fact and the background before it.
- Each claim appears in at most one group. Leave out claims that have no repeat.

Answer with JSON only: {"groups": [...]}, with an empty list if there are no repeats."""

JOIN_CHECK_SCHEMA = {"type": "json_schema", "json_schema": {"name": "join_checks", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["checks"],
    "properties": {"checks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["pair", "verdict", "why"],
        "properties": {"pair": {"type": "integer"}, "why": {"type": "string"},
                       "verdict": {"type": "string", "enum": ["same", "adds", "differs"]}}}}}}}}

JOIN_CHECK_SYSTEM = """You check pairs of claims from a news brief about one event. In each pair, K is a claim we keep and O is a claim we would fold into K because it seems to say the same thing.

For each pair answer:
- "same": O says nothing K doesn't already say, apart from who says it, and they don't disagree. Different wording is fine.
- "adds": O says something K doesn't: a number, time, place, name, cause, hedge ("may have", "reportedly") or a second fact.
- "differs": they are different facts, or they disagree (a different number, date, time, place or cause, or a different account of what happened).

When unsure, answer "adds" or "differs": folding O into K must never lose or change a fact. Answer with JSON only: {"checks": [{"pair": 1, "verdict": "...", "why": "..."}, ...]}, one per pair."""

_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
              "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30",
              "forty": "40", "fifty": "50", "hundred": "100", "hundreds": "hundreds", "thousand": "1000",
              "thousands": "thousands", "dozen": "12", "dozens": "dozens", "million": "million", "billion": "billion",
              "half": "half", "first": "1st", "second": "2nd", "third": "3rd"}


def numbers(s: str) -> set[str]:
    """The numbers a sentence gives: digits (commas dropped) and number words, normalized."""
    s = (s or "").lower()
    out = {x.replace(",", "").rstrip(".") for x in re.findall(r"\d[\d,.]*\d|\d", s)}
    out |= {_NUM_WORDS[w] for w in re.findall(r"[a-z]+", s) if w in _NUM_WORDS}
    return out


def numbers_fit(other: str, keep: str) -> bool:
    """Every number in the other claim also appears in the kept one (so a fold can't hide 40 against 42)."""
    return numbers(other) <= numbers(keep)


def find_joins_2(event: dict, claims: list[dict], complete, *, model: str = "", name: str = "brief_merge join",
                 updates=()):
    """Groups {keep, others, why} (valid ids only; keep not among others). Returns (groups, calls, error)."""
    ids = [c["id"] for c in claims]
    params = dict(max_tokens=JOIN_MAX_TOKENS, response_format=join_schema_2(ids), timeout=CALL_TIMEOUT_S)
    msgs = join_messages(event, claims, updates)
    msgs[0] = {"role": "system", "content": JOIN_SYSTEM_2}
    known, errs = set(ids), []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": RETRY_JSON}],
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
        if isinstance(d, dict) and isinstance(d.get("groups"), list):
            out = []
            for g in d["groups"]:
                if not isinstance(g, dict) or str(g.get("keep", "")).strip() not in known:
                    continue
                k = str(g["keep"]).strip()
                others = [o for o in dict.fromkeys(str(x).strip() for x in g.get("others") or []) if o in known and o != k]
                if others:
                    out.append(dict(keep=k, others=others, why=str(g.get("why") or "").strip()[:300]))
            return out, attempt + 1, None
    return [], 2, "no usable join answer after one retry" + (f" ({errs[-1]})" if errs else "")


def check_joins(event: dict, claims: list[dict], pairs: list[tuple], complete, *, model: str = "",
                name: str = "brief_merge join check"):
    """One call over the (keep, other) pairs. Returns ({pair: (verdict, why)}, calls, error); on an unusable
    answer twice, an empty dict, so nothing is joined."""
    by = {c["id"]: c for c in claims}
    lines = [f"Pair {i}:\nK ({k}; who: {by[k]['who_says']}): {by[k]['claim']}\nO ({o}; who: {by[o]['who_says']}): {by[o]['claim']}"
             for i, (k, o) in enumerate(pairs, 1)]
    msgs = [{"role": "system", "content": JOIN_CHECK_SYSTEM},
            {"role": "user", "content": f"Event: {event.get('title', '')}\n\n" + "\n\n".join(lines)}]
    params = dict(max_tokens=JOIN_MAX_TOKENS, response_format=JOIN_CHECK_SCHEMA, timeout=CALL_TIMEOUT_S)
    errs = []
    for attempt in range(2):
        text, err = brief_read._call(complete, msgs if attempt == 0 else msgs + [{"role": "user", "content": RETRY_JSON}],
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
        if isinstance(d, dict) and isinstance(d.get("checks"), list):
            got = {}
            for x in d["checks"]:
                if isinstance(x, dict) and isinstance(x.get("pair"), int) and 1 <= x["pair"] <= len(pairs) \
                        and x.get("verdict") in ("same", "adds", "differs"):
                    got.setdefault(pairs[x["pair"] - 1], (x["verdict"], str(x.get("why") or "")[:300]))
            return got, attempt + 1, None
    return {}, 2, "no usable join check after one retry" + (f" ({errs[-1]})" if errs else "")


def join_kept(claims: list[dict], groups: list[dict], updates=()) -> tuple[list, list, list, dict]:
    """Folds each group's others into its keep claim, keeping keep's words. An other already used, the keep
    of another group, or in a pair that must stay apart with any claim of the group is left out.
    Returns (claims, joined, rejected, {removed id: kept id})."""
    by = {c["id"]: c for c in claims}
    apart = {frozenset((c["id"], o)) for c in claims for o in c.get("conflicts_with") or []}
    apart |= {frozenset((u["a"], u["b"])) for u in updates or []}
    used, joined, rejected, remap = set(), [], [], {}
    for g in groups:
        k = g["keep"]
        if k in used or k in remap:
            rejected += [dict(claims=[k, o], reason="the kept claim is already in another group") for o in g["others"]]
            continue
        members, take = [k], []
        for o in g["others"]:
            if o in used or o in remap:
                rejected.append(dict(claims=[k, o], reason="already in another group"))
            elif any(frozenset((o, m)) in apart for m in members):
                rejected.append(dict(claims=[k, o], reason="a pair that must stay apart"))
            else:
                members.append(o)
                take.append(o)
        if not take:
            continue
        keep = by[k]
        before = {i: by[i]["claim"] for i in members}
        speakers = list(dict.fromkeys(w.strip() for i in members for w in by[i]["who_says"].split(";") if w.strip()))
        named = [w for w in speakers if w != "the outlet"]
        keep["who_says"] = "; ".join(named + (["the outlet"] if "the outlet" in speakers and named else [])) or "the outlet"
        for o in take:
            for s in by[o]["sources"]:
                if s["fact"] not in keep["facts"]:
                    keep["facts"].append(s["fact"])
                    keep["sources"].append(s)
            keep["conflicts_with"] += [x for x in by[o]["conflicts_with"] if x not in keep["conflicts_with"]]
            remap[o] = k
        keep["articles"] = sorted({s["article"] for s in keep["sources"]})
        used.update(members)
        joined.append(dict(keep=k, joined=take, before=before, claim=keep["claim"], who_says=keep["who_says"], why=g["why"]))
    out = [c for c in claims if c["id"] not in remap]
    for c in out:
        c["conflicts_with"] = [x for x in dict.fromkeys(remap.get(o, o) for o in c["conflicts_with"]) if x != c["id"]]
    return out, joined, rejected, remap


def remap_pairs(pairs: list[dict], remap: dict) -> list[dict]:
    """Pair records ({a, b, why}) after a join; a pair whose two claims were joined goes."""
    out = []
    for p in pairs or []:
        a, b = remap.get(p["a"], p["a"]), remap.get(p["b"], p["b"])
        if a != b:
            out.append(dict(p, a=a, b=b))
    return out


# ---- checking ------------------------------------------------------------------------------------------

def check(d: dict, cards: list[dict]) -> tuple[list, list, list, dict]:
    """Checked claims, dropped claims, unused cards, and the counts."""
    by = {c["short"]: c for c in cards}
    c = dict(claims_first=0, unknown_cards=0, claims_dropped=0, cards_unused=0, cards=len(cards),
             multi_article=0, conflicts=0)
    raw = [x for x in (d.get("claims") or []) if isinstance(x, dict) and (x.get("claim") or "").strip()]
    c["claims_first"] = len(raw)
    kept, dropped, num, used = [], [], {}, set()
    for i, x in enumerate(raw, 1):
        ids = []
        for s in x.get("cards") or []:
            s = str(s).strip()
            if s in by and s not in ids:
                ids.append(s)
            elif s not in by:
                c["unknown_cards"] += 1
        claim = dict(claim=x["claim"].strip(), kind=x.get("kind") if x.get("kind") in KINDS else "event",
                     who_says=(x.get("who_says") or "").strip() or "the outlet",
                     conflicts_with=[n for n in (x.get("conflicts_with") or []) if isinstance(n, int)],
                     facts=[by[s]["id"] for s in ids],
                     sources=[dict(fact=by[s]["id"], article=by[s]["article"], quote=by[s]["quote"],
                                   quote_en=by[s].get("quote_en", ""), pos=by[s].get("pos")) for s in ids],
                     articles=sorted({by[s]["article"] for s in ids}))
        if ids:
            claim["id"] = f"C{len(kept) + 1}"
            num[i] = claim["id"]
            used.update(ids)
            kept.append(claim)
        else:
            dropped.append(claim)
    for claim in kept:                         # list numbers -> claim ids; conflicts with dropped claims go
        claim["conflicts_with"] = [num[n] for n in claim["conflicts_with"] if n in num and num[n] != claim["id"]]
    unused = [dict(id=x["id"], fact=x["fact"], kind=x["kind"]) for x in cards if x["short"] not in used]
    c.update(claims_dropped=len(dropped), cards_unused=len(unused),
             multi_article=sum(len(k["articles"]) > 1 for k in kept),
             conflicts=sum(bool(k["conflicts_with"]) for k in kept))
    return kept, dropped, unused, c


# ---- one story ------------------------------------------------------------------------------------------

def claims_final_after_merge(prompt: str = VERSION) -> bool:
    """True when nothing after the merge call (and its retry) adds, drops or rewords a claim: the later
    calls only mark conflicts and updates on the claims. False for the join versions (merge-12, merge-13).
    When true, work that reads only the claims' words and cards (the fact check's judge, the blindspot
    judge, framing) can start as soon as merge_claims() returns, beside mark_conflicts()."""
    return prompt not in JOIN


def merge_story(event: dict, step1: dict, complete, *, model: str = "", name: str = "brief_merge",
                prompt: str = VERSION, times: dict | None = None) -> dict:
    """Step 2 for one story, from step 1's output for it (read_story's result). times maps article id ->
    published time; the conflict pass shows it from merge-8. The two halves, for callers that run other
    work beside the second: merge_claims(), then mark_conflicts()."""
    out = merge_claims(event, step1, complete, model=model, name=name, prompt=prompt, times=times)
    return mark_conflicts(event, out, complete, model=model, prompt=prompt, times=times)


def merge_claims(event: dict, step1: dict, complete, *, model: str = "", name: str = "brief_merge",
                 prompt: str = VERSION, times: dict | None = None) -> dict:
    """The merge call, with its retry for left-out cards: the claims with their cards."""
    cards = cards_of(step1)
    out = dict(version=prompt, claims=[], dropped=[], unused=[],
               checks=dict(calls=0, retried_json=False, call_errors=[], error=None, cards=len(cards)))
    ch = out["checks"]
    if not cards:
        ch["error"] = "no fact cards from step 1"
        return out
    d, n, errs = _ask(complete, messages_for(event, cards, prompt), params_for(model), name)
    ch.update(calls=n, retried_json=n > 1, call_errors=errs)
    if d is None:
        ch["error"] = "no usable answer after one retry" + (f" ({errs[-1]})" if errs else "")
        return out
    out["claims"], out["dropped"], out["unused"], counts = check(d, cards)
    ch.update(counts, retried_incomplete=False, unused_first=counts["cards_unused"])
    if prompt in COMPLETE_RETRY and counts["cards_unused"] > COMPLETE_RETRY[prompt] * len(cards):
        short = {c["id"]: c["short"] for c in cards}
        note = RETRY_INCOMPLETE.format(ids=", ".join(short[u["id"]] for u in out["unused"]))
        again = messages_for(event, cards, prompt) + [{"role": "assistant", "content": json.dumps(d, ensure_ascii=False)},
                                                      {"role": "user", "content": note}]
        d2, n2, errs2 = _ask(complete, again, params_for(model), f"{name} retry incomplete")
        ch.update(calls=ch["calls"] + n2, retried_incomplete=True, call_errors=ch["call_errors"] + errs2)
        if d2 is not None:
            k2, dr2, un2, c2 = check(d2, cards)
            if len(un2) < len(out["unused"]):           # keep the answer that leaves fewer cards out
                out["claims"], out["dropped"], out["unused"] = k2, dr2, un2
                ch.update(c2)
    return out


def mark_conflicts(event: dict, out: dict, complete, *, model: str = "", prompt: str = VERSION,
                   times: dict | None = None) -> dict:
    """Everything after the merge call, on merge_claims()'s output (changed in place and returned): the
    conflict pass, the check of its pairs and of the merge call's own marks, and for the two join
    versions the join. From merge-14 on it only sets conflicts_with on claims and adds updates."""
    ch = out["checks"]
    if prompt in CONFLICT_PASS and len(out["claims"]) > 1:
        if CONFLICT_PASS[prompt] == 4:
            points, n3, err3 = find_points(event, out["claims"], complete, model=model, times=times)
            pairs = point_pairs(points)
            out["conflict_points"] = points
            ch.update(disputes=sum(p["type"] == "dispute" for p in points), updates=sum(p["type"] == "update" for p in points))
        else:
            pairs, n3, err3 = find_conflicts(event, out["claims"], complete, model=model, variant=CONFLICT_PASS[prompt],
                                             times=times)
        found = []
        if prompt in VERIFY and pairs:
            found = pairs
            disputes, updates, n4, err4, unchecked = verify_pairs(event, out["claims"], found, complete, model=model,
                                                                  times=times, variant=VERIFY[prompt])
            n3 += n4
            if disputes is None:                      # the check failed: keep the unchecked candidates
                disputes = found
            pairs = disputes
            out["conflict_candidates"] = [dict(a=a, b=b, why=w) for a, b, w in found]
            out["updates"] = [dict(a=a, b=b, why=w) for a, b, w in updates]
            ch.update(conflict_candidates=len(found), verify_error=err4, verify_unchecked=unchecked,
                      updates=len(updates))
        if prompt in OWN_CHECK:
            pairs, n6 = own_check(event, out, pairs, found, complete, model=model, times=times, variant=VERIFY[prompt])
            n3 += n6
        added = add_conflicts(out["claims"], pairs)
        out["conflict_pass"] = [dict(a=a, b=b, why=w) for a, b, w in pairs]
        ch.update(calls=ch["calls"] + n3, conflict_pass_found=len(pairs), conflict_pass_added=added,
                  conflict_pass_error=err3, conflicts=sum(bool(k["conflicts_with"]) for k in out["claims"]))
    if prompt in JOIN and len(out["claims"]) > 1:
        before = len(out["claims"])
        if JOIN[prompt] == 1:
            groups, n5, err5 = find_joins(event, out["claims"], complete, model=model, updates=out.get("updates") or [])
            out["claims"], out["joined"], out["join_rejected"], remap = join_claims(out["claims"], groups, out.get("updates") or [])
        else:
            groups, n5, err5 = find_joins_2(event, out["claims"], complete, model=model, updates=out.get("updates") or [])
            by = {c["id"]: c for c in out["claims"]}
            proposed = [(g["keep"], o) for g in groups for o in g["others"]]
            fit = [p for p in proposed if numbers_fit(by[p[1]]["claim"], by[p[0]]["claim"])]
            verdicts, n6, err6 = (check_joins(event, out["claims"], fit, complete, model=model) if fit else ({}, 0, None))
            n5 += n6
            err5 = err5 or err6
            out["join_checks"] = [dict(keep=k, other=o, numbers_fit=(k, o) in fit,
                                       verdict=(verdicts.get((k, o)) or (None, ""))[0], why=(verdicts.get((k, o)) or (None, ""))[1])
                                  for k, o in proposed]
            same = [dict(keep=g["keep"], others=[o for o in g["others"] if (verdicts.get((g["keep"], o)) or ("",))[0] == "same"],
                         why=g["why"]) for g in groups]
            out["claims"], out["joined"], out["join_rejected"], remap = join_kept(out["claims"], [g for g in same if g["others"]],
                                                                                 out.get("updates") or [])
            ch.update(join_proposed=len(proposed), join_numbers_refused=len(proposed) - len(fit),
                      join_check_same=sum(v[0] == "same" for v in verdicts.values()))
        for key in ("updates", "conflict_pass", "conflict_candidates"):
            if key in out:
                out[key] = remap_pairs(out[key], remap)
        ch.update(calls=ch["calls"] + n5, join_error=err5, join_groups=len(out["joined"]),
                  claims_joined=before - len(out["claims"]), join_rejected=len(out["join_rejected"]),
                  multi_article=sum(len(k["articles"]) > 1 for k in out["claims"]),
                  conflicts=sum(bool(k["conflicts_with"]) for k in out["claims"]))
    return out
