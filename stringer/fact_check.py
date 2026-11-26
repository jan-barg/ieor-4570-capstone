"""Module 6: the fact check. Reads a Story File and gives every claim one of three answers for the
script writer: confirmed (say it plainly), say with source (name who says it), or dropped (never in
the script). Design agreed November 25 (Jan; system map, module 6; overview page
stringer_private/fact_check_design/overview.html).

Three passes:
  1. paperwork() (code, free): every card still points to a read article in the file and its quote
     reads back at its saved position (story_file.quote_at); the article's web address belongs to its
     outlet; the article isn't dated well before the event. A failing card comes off its claim, and a
     claim with no card left is dropped. Numbers in a claim that appear in none of its quotes are
     passed to the judge as a note.
  2. judge() (one model call per BATCH claims, a few side by side): the event, then each claim with
     who says it and each card's quote inside its sentence with a sentence on each side (original
     language, plus step 1's English for non-English articles; no outlet names). Per claim: backed /
     needs a name / not backed (and what is wrong), the cards that don't back it, English that doesn't
     match its original, and whether the claim contradicts the event summary. The answer's shape is
     enforced (claim ids and card labels fixed in it), with one retry for an unusable answer and one
     for claims left out; claims still without an answer are "unchecked" and the video can't use them.
  3. apply() (code, free): cards the judge says don't back their claim come off, the claim's articles,
     independent sources, sides and flags are counted again, and the rules set each claim's status:
       dropped          not backed, or no card left
       say with source  backed, but (a) the quotes give it as someone's account and the sentence
                        doesn't say whose, (b) every source is unrated or under 0.5, (c) it is in an
                        outlet's own voice with one independent source, or (d) it conflicts with
                        another claim or contradicts the event summary
       confirmed        backed, and none of a-d applies
     A claim that is dropped or changes sides loses its blindspot mark. The story gets fact-check flags.

Decided with the design (Jan, Nov 25): a failing claim is dropped, never rewritten, and nothing goes
back to step 2. One-outlet claims that repeat another claim's fact are combined by the script writer
(a script line citing claims from 2+ independent outlets may say the fact plainly), not here.

    check_story(sf, facts, articles, complete, model=...) -> (facts, checked Story File)
    check_story(sf, facts, articles, None)                -> passes 1 and 3 only (claims "unchecked")
    check_folder(story_dir, complete, model=...), write_checked(), read_checked()
                                                          -> the same on a story folder; the checked file
                                                             is <folder>/checked_story_file.json
                                                             (scripts/check_story_files.py runs every story)
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import brief_read, brief_sides, story_file

VERSION = "check-5"       # check-2 (Nov 25): the reason first; kept hedges are backed; speaker never the outlet.
                            # check-3 (Nov 25): any difference the reason finds means not backed
                            # check-4 (Nov 26): one card is enough (others that differ go in bad_cards);
                            #   reported speech may turn "we" into "they". From Haiku's wrong drops.
                            # check-5 (Nov 26, after the Kerch smoke of 3.8 Flash and Terra): cards may back a
                            #   claim together ("one is enough" only when they disagree); each card shows
                            #   "said by: X" from the reader, who saw the whole article.
BATCH = 20                  # claims per judge call
BATCH_WORKERS = 3           # judge calls side by side within one story
MAX_TOKENS = 16000          # thinking counts toward this on some models
CALL_TIMEOUT_S = 300
EARLY_HOURS = 48            # an article dated more than this before the event's start isn't coverage of it
MANY_DROPS = 0.10           # more than this share of claims dropped: no video until a person looks
CONTEXT_CHARS = 500         # at most this much of the sentence before and after a quote
SENTENCE_CHARS = 900        # and of the quote's own sentence

STATUSES = ("confirmed", "say with source", "dropped", "unchecked")
VERDICTS = ("backed", "needs a name", "not backed")
PROBLEMS = ("none", "number", "who did what", "place or date", "cause", "more certain than the quotes",
            "not in the quotes", "other")
OWN_VOICE = {"", "the outlet", "the article"}

FLAGS = {   # code -> (who reads it, what it does); the fact check's additions to the fixed flag list
    "many drops": ("the pipeline", "no video until a person looks"),
    "against the event": ("the script writer", "gives both accounts: these claims disagree with the event summary"),
    "unchecked": ("the pipeline", "these claims got no usable judge answer; the script can't use them"),
}

SYSTEM = """You check the claims in a news research file against the article quotes they rest on. An earlier step wrote each claim from the quotes shown under it. Your job is to say whether those quotes really back the claim.

For each claim, answer in this order:

why: first, one short sentence comparing the claim with its quotes: what matches, and what differs, if anything. Then give the verdict that follows from it.

verdict
- "backed": the quotes, read in their sentences, say what the claim says. Shorter wording, another word order or a translation are fine, and so is leaving details out. Every number, name, place, date, cause and who-did-what-to-whom that the claim states must match the quotes. A claim that keeps the quotes' own hedge ("photos suggest", "reportedly", "around") is backed. Reported speech is fine too: a speaker's "I" or "we" may become "he", "she" or "they".
  Cards may back a claim together, each for its own part. When cards disagree, one is enough: if one card says what the claim says and another gives a different figure, name or place, the claim is backed; put the card that differs in bad_cards.
- "needs a name": the quotes say it only as one party's account (someone says, claims, reports, according to someone), and the claim states it as plain fact without saying whose account it is. A claim that already says who says it ("X said ...", "according to X") is not this case. If one card states it as plain fact in the article's own voice, the claim is backed.
- "not backed": the quotes don't say it, or say something different.

Your "why" sentence decides the verdict. If it finds any difference between the claim and the cards that back it, in a number, name, place, date, cause, who did what, or how certain the claim is, even a slight one, the verdict is "not backed". The one exception is a claim whose only difference is that it leaves out whose account it is: that is "needs a name".

problem: "none" when backed or needs a name; otherwise the main thing that is wrong:
- "number": a figure differs from the quotes, or isn't in them;
- "who did what": the actors, or who did what to whom, differ;
- "place or date": a place, day or date differs;
- "cause": cause and effect are changed or added;
- "more certain than the quotes": the quotes hedge (may, might, suggest, appear, reportedly, allegedly, unconfirmed) and the claim drops it;
- "not in the quotes": the quotes are about something else;
- "other".

speaker: for "needs a name", the party whose account it is, as the quotes name them (for example "Russia's Transport Ministry" or "Vedomosti, citing the Transport Ministry"); otherwise empty. Never "the outlet" or "the article".

bad_cards: the claim's cards that don't back it, when other cards do. Leave it empty when every card backs the claim or when none does.

bad_translations: cards whose English text doesn't say what the original-language quote says.

against_event: true when the claim contradicts the event summary at the top: a different toll, a different actor, or says it didn't happen. A detail the summary doesn't mention is not a contradiction.

Read each quote in its sentence and the sentences around it: they often say who "he", "it" or "they" is, or that a statement is someone's account. A card marked "said by: X" is a quote the article gives as X's words (an earlier reader saw the whole article); trust it for who is speaking when the quote's own sentences don't say. Judge only from the quotes and their sentences, never from what you know about the news. A note under a claim lists numbers that appear in none of its quotes; check them. Answer for every claim, with JSON only."""

RETRY_MISSING = "You left out some claims. Answer for every claim below, with JSON only."


# ---- pass 1: paperwork (code) ------------------------------------------------------------------------

def _when(s: str | None):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def source_problems(sf: dict, table=None) -> dict:
    """{source id: why it can't back a claim} for web addresses that don't belong to their outlet and
    articles dated more than EARLY_HOURS before the event's start."""
    out = {}
    start = _when((sf.get("event") or {}).get("start"))
    if table is None:
        from . import outlets
        table = outlets.table()
    for s in sf.get("sources") or []:
        url = s.get("url") or ""
        if url and s.get("outlet"):
            o, _how = table.match_domain(url)
            if o is None or getattr(o, "outlet_id", None) != s["outlet"]:
                out[s["id"]] = f"web address doesn't belong to {s.get('outlet_name') or s['outlet']}"
                continue
        p = _when(s.get("published_at"))
        if start and p and (start - p).total_seconds() > EARLY_HOURS * 3600:
            out[s["id"]] = f"dated {round((start - p).total_seconds() / 86400)} days before the event"
    return out


_NUM = re.compile(r"\d[\d,.]*\d|\d")
_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
          "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "dozen": "12", "hundred": "100",
          "thousand": "1000", "million": "1000000"}


def _nums(text: str) -> set[str]:
    out = {n.replace(",", "").rstrip(".") for n in _NUM.findall(text or "")}
    out |= {n.split(".")[0] for n in out if "." in n}
    low = (text or "").lower()
    out |= {v for w, v in _WORDS.items() if re.search(rf"\b{w}\b", low)}
    return out


def numbers_missing(claim: str, quotes: list[str]) -> list[str]:
    """Numbers in the claim that appear in none of its quotes (number words count: "two" is 2)."""
    have = set().union(*[_nums(q) for q in quotes]) if quotes else set()
    out = []
    for n in _NUM.findall(claim or ""):
        k = n.replace(",", "").rstrip(".")
        if k not in have and k.split(".")[0] not in have and n not in out:
            out.append(n)
    return out


def paperwork(sf: dict, facts: list[dict], articles: dict, table=None) -> dict:
    """Pass 1. articles: {article id: article with its text}. Returns
    {"cards_off": {fact id: why}, "sources_off": {source id: why}, "contexts": {fact id: quote_at},
     "numbers": {claim id: [numbers in no quote]}}."""
    src = {s["id"]: s for s in sf.get("sources") or []}
    bad_src = source_problems(sf, table)
    fid = {f["id"]: f for f in facts}
    cards_off, contexts = {}, {}
    for f in facts:
        s = src.get(f["article"])
        if s is None:
            cards_off[f["id"]] = "article not in the file"
        elif not s.get("read"):
            cards_off[f["id"]] = "article not read"
        elif f["article"] in bad_src:
            cards_off[f["id"]] = bad_src[f["article"]]
        elif f["article"] not in articles:
            cards_off[f["id"]] = "article text missing"
        else:
            q = story_file.quote_at(articles[f["article"]], f)
            if q is None:
                cards_off[f["id"]] = "quote not found at its place in the article"
            else:
                contexts[f["id"]] = q
    numbers = {}
    for c in sf.get("claims") or []:
        kept = [fid[x] for x in c.get("facts") or [] if x in fid and x not in cards_off]
        for x in c.get("facts") or []:
            if x not in fid:
                cards_off[x] = "card not in the file"
        miss = numbers_missing(c.get("claim", ""), [k.get("quote", "") + " " + (k.get("quote_en") or "") for k in kept])
        if miss and kept:
            numbers[c["id"]] = miss
    return dict(cards_off=cards_off, sources_off=bad_src, contexts=contexts, numbers=numbers)


# ---- pass 2: the judge (model) -----------------------------------------------------------------------

def _clip(s: str, n: int, tail: bool = False) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return "…" + s[-n:] if tail else s[:n] + "…"


def card_text(ctx: dict, fact: dict, lang: str | None) -> str:
    q = ctx["quote"]
    sent = ctx["sentence"]
    if len(sent) > SENTENCE_CHARS:                       # keep the quote, trim the rest of a run-on sentence
        i = sent.find(q)
        lo = max(0, i - (SENTENCE_CHARS - len(q)) // 2) if i >= 0 else 0
        sent = ("…" if lo else "") + sent[lo:lo + max(SENTENCE_CHARS, len(q) + 40)] + "…"
    marked = sent.replace(q, f"[[{q}]]", 1) if q in sent else f"{sent} [[{q}]]"
    parts = [p for p in (_clip(ctx.get("before"), CONTEXT_CHARS, tail=True), marked,
                         _clip(ctx.get("after"), CONTEXT_CHARS)) if p]
    out = " ".join(parts)
    en = (fact.get("quote_en") or "").strip()
    if lang and lang != "en":
        out += f"\n      English of the [[quote]] ({lang}): \"{en}\"" if en else f"\n      ({lang}; no English given)"
    return out


def batches(claims: list[dict], size: int = BATCH) -> list[list[dict]]:
    """Claims in file order, in fixed groups of `size` (fixed by position, so a change to one claim
    changes only its own group's call)."""
    return [claims[i:i + size] for i in range(0, len(claims), size)]


def messages_for(event: dict, items: list[dict]) -> tuple[list[dict], dict]:
    """items: [{"claim": claim, "cards": [(fact, context, lang)], "numbers": [...]}].
    Returns (messages, {card label: fact id})."""
    labels, lines = {}, []
    for it in items:
        c = it["claim"]
        lines.append(f"{c['id']} · {c.get('kind') or 'claim'} · who says: {c.get('who_says') or 'the outlet'}")
        lines.append(f"Claim: {c['claim']}")
        for f, ctx, lang in it["cards"]:
            lab = f"K{len(labels) + 1}"
            labels[lab] = f["id"]
            who = _speaker(f.get("who_says"))
            lines.append(f"  {lab}{f' (said by: {who})' if who else ''}: {card_text(ctx, f, lang)}")
        if it.get("numbers"):
            lines.append(f"  Note: {', '.join(it['numbers'])} appear{'s' if len(it['numbers']) == 1 else ''} in none of the quotes.")
        lines.append("")
    head = (f"Event: {event.get('title', '')}\nEvent summary: {event.get('summary', '')}\n\n"
            f"Claims ({len(items)}). Each card shows the quote in [[double brackets]] inside its sentence, "
            "with a sentence before and after.\n\n")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": head + "\n".join(lines).rstrip()}], labels


def schema(ids: list[str], labels: list[str]) -> dict:
    lab = {"type": "array", "items": {"type": "string", "enum": labels or ["K0"]}}
    item = {"type": "object", "additionalProperties": False,
            "required": ["id", "why", "verdict", "problem", "speaker", "bad_cards", "bad_translations", "against_event"],
            "properties": {"id": {"type": "string", "enum": ids}, "why": {"type": "string"},   # the reason first
                           "verdict": {"type": "string", "enum": list(VERDICTS)},
                           "problem": {"type": "string", "enum": list(PROBLEMS)}, "speaker": {"type": "string"},
                           "bad_cards": lab, "bad_translations": lab, "against_event": {"type": "boolean"}}}
    return {"type": "json_schema", "json_schema": {"name": "fact_check", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["claims"],
        "properties": {"claims": {"type": "array", "items": item}}}}}


def params_for(model: str, ids: list[str], labels: list[str]) -> dict:
    p = dict(max_tokens=MAX_TOKENS, response_format=schema(ids, labels), timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        p["reasoning_effort"] = "low"
    return p


def _parse(text: str) -> list | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        return None
    return d["claims"] if isinstance(d, dict) and isinstance(d.get("claims"), list) else None


def _speaker(s) -> str:
    """The judge's speaker, or "" when it names the article's own voice (the outlet is named by rule c)."""
    s = str(s or "").strip()[:200]
    low = s.lower()
    return "" if low in OWN_VOICE or low.startswith(("the outlet", "the article", "the author", "unnamed")) else s


def _verdicts(rows: list, items: list[dict], labels: dict) -> dict:
    """{claim id: verdict dict} from the parsed answer; unknown ids and other claims' cards are dropped."""
    own = {it["claim"]["id"]: {lab for lab, fid in labels.items() if fid in {f["id"] for f, _, _ in it["cards"]}}
           for it in items}
    out = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("id") not in own or r["id"] in out:
            continue
        v = r.get("verdict") if r.get("verdict") in VERDICTS else None
        if v is None:
            continue
        mine = own[r["id"]]
        out[r["id"]] = dict(
            verdict=v, problem=r.get("problem") if r.get("problem") in PROBLEMS else "other",
            speaker=_speaker(r.get("speaker")),
            bad_cards=sorted({labels[x] for x in r.get("bad_cards") or [] if x in mine}),
            bad_translations=sorted({labels[x] for x in r.get("bad_translations") or [] if x in mine}),
            against_event=bool(r.get("against_event")), why=str(r.get("why") or "").strip()[:400])
    return out


def judge_batch(event: dict, items: list[dict], complete, *, model: str = "", name: str = "fact_check") -> dict:
    """One group of claims: one call, one retry for an unusable answer, then one call on any claims left
    out. Returns {"verdicts": {claim id: ...}, "calls", "errors", "missing": [claim ids]}."""
    verdicts, calls, errors = {}, 0, []
    todo = list(items)
    for round_ in range(2):                       # round 2 asks again only for claims left out
        if not todo:
            break
        msgs, labels = messages_for(event, todo)
        ids = [it["claim"]["id"] for it in todo]
        params = params_for(model, ids, list(labels))
        if round_ == 1:
            msgs = msgs[:-1] + [{"role": "user", "content": RETRY_MISSING + "\n\n" + msgs[-1]["content"]}]
        got = None
        for attempt in range(2 if round_ == 0 else 1):
            m = msgs if attempt == 0 else msgs + [{"role": "user", "content": brief_read.RETRY_JSON}]
            text, err = brief_read._call(complete, m, params, name if (round_, attempt) == (0, 0) else f"{name} retry")
            calls += 1
            if err:
                errors.append(err)
            got = _parse(text)
            if got is not None:
                break
        if got is not None:
            verdicts.update(_verdicts(got, todo, labels))
        todo = [it for it in todo if it["claim"]["id"] not in verdicts]
    return dict(verdicts=verdicts, calls=calls, errors=errors, missing=[it["claim"]["id"] for it in todo])


def judge_plan(sf: dict, facts: list[dict], pw: dict, model: str, size: int = BATCH) -> list[dict]:
    """The first call of each group, for cost estimates: [{"messages", "params", "expect_output"}]."""
    return [dict(messages=m, params=p, expect_output=60 + 45 * n) for m, p, n in _batch_calls(sf, facts, pw, model, size)]


def _items(sf: dict, facts: list[dict], pw: dict) -> list[dict]:
    fid = {f["id"]: f for f in facts}
    lang = {s["id"]: s.get("lang") for s in sf.get("sources") or []}
    out = []
    for c in sf.get("claims") or []:
        cards = [(fid[x], pw["contexts"][x], lang.get(fid[x]["article"])) for x in c.get("facts") or []
                 if x in fid and x not in pw["cards_off"] and x in pw["contexts"]]
        out.append(dict(claim=c, cards=cards, numbers=pw["numbers"].get(c["id"], [])) if cards else None)
    return out


def _batch_calls(sf, facts, pw, model, size):
    its = _items(sf, facts, pw)
    for group in batches(its, size):
        group = [g for g in group if g]
        if group:
            m, labels = messages_for(sf.get("event") or {}, group)
            yield m, params_for(model, [g["claim"]["id"] for g in group], list(labels)), len(group)


def judge(sf: dict, facts: list[dict], pw: dict, complete, *, model: str = "", size: int = BATCH,
          workers: int = BATCH_WORKERS) -> dict:
    """Pass 2 over every claim that still has a card. Returns {"verdicts", "calls", "errors", "missing"}."""
    groups = [[g for g in grp if g] for grp in batches(_items(sf, facts, pw), size)]
    groups = [g for g in groups if g]
    event = sf.get("event") or {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        res = list(ex.map(lambda g: judge_batch(event, g, complete, model=model), groups))
    out = dict(verdicts={}, calls=0, errors=[], missing=[])
    for r in res:
        out["verdicts"].update(r["verdicts"])
        out["calls"] += r["calls"]
        out["errors"] += r["errors"]
        out["missing"] += r["missing"]
    return out


# ---- pass 3: the rules (code) ------------------------------------------------------------------------

def _side_names(sf: dict) -> list[str]:
    s = sf.get("sides") or {}
    return [s[g]["side_id"] for g in "AB" if isinstance(s.get(g), dict) and s[g].get("side_id")]


def recount(claim: dict, kept_articles: list[str], src: dict, side_order: list[str]) -> dict:
    """articles, sides, neither, independent, independent_groups and flags for the articles left."""
    arts = list(dict.fromkeys(kept_articles))
    sides = {(src.get(a) or {}).get("side") for a in arts} - {None}
    groups = [[a for a in g if a in arts] for g in claim.get("independent_groups") or []]
    groups = [g for g in groups if g]
    grouped = {a for g in groups for a in g}
    groups += [[a] for a in arts if a not in grouped]
    by_id = {a: src.get(a) or {} for a in arts}
    return dict(articles=arts, sides=[s for s in side_order if s in sides],
                neither=sum(1 for a in arts if (src.get(a) or {}).get("side") is None),
                independent=len(groups), independent_groups=groups if len(groups) < len(arts) else [],
                flags=brief_sides.claim_flags(dict(articles=arts), by_id) if arts else [])


def _outlets(arts: list[str], src: dict) -> str:
    names = []
    for a in arts:
        s = src.get(a) or {}
        n = s.get("outlet_name") or s.get("outlet") or a
        if s.get("state_media") in ("State-Controlled", "State-Affiliated", "Captured") and "state media" not in n.lower():
            n = f"{n} ({s['state_media'].lower()} media)"
        if n not in names:
            names.append(n)
    return " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]


def flag(code: str, detail: str, **extra) -> dict:
    reader, action = FLAGS[code]
    return dict(code=code, detail=detail, reader=reader, action=action, **extra)


def apply(sf: dict, facts: list[dict], pw: dict, judged: dict | None, *, model: str = "code") -> tuple[list[dict], dict]:
    """Pass 3: the checked Story File (a copy) and facts with translation marks."""
    sf = copy.deepcopy(sf)
    facts = [dict(f) for f in facts]
    fid = {f["id"]: f for f in facts}
    src = {s["id"]: s for s in sf.get("sources") or []}
    order = _side_names(sf)
    verdicts = (judged or {}).get("verdicts") or {}
    missing = set((judged or {}).get("missing") or [])
    bad_tr = set()
    status_of = {}
    for c in sf.get("claims") or []:
        v = verdicts.get(c["id"])
        off = {x: pw["cards_off"][x] for x in c.get("facts") or [] if x in pw["cards_off"]}
        if v and v["verdict"] != "not backed":
            for x in v["bad_cards"]:
                off.setdefault(x, "doesn't back the claim (judge)")
        if v:
            bad_tr.update(v["bad_translations"])
        kept = [x for x in c.get("facts") or [] if x not in off and x in fid]
        before = dict(articles=list(c.get("articles") or []), sides=list(c.get("sides") or []),
                      independent=c.get("independent"))
        rc = recount(c, [fid[x]["article"] for x in kept], src, order)
        check = dict(version=VERSION, verdict=(v or {}).get("verdict"), problem=(v or {}).get("problem"),
                     why=(v or {}).get("why") or "", speaker=(v or {}).get("speaker") or "",
                     against_event=bool((v or {}).get("against_event")), cards_off=off,
                     bad_translations=sorted(set((v or {}).get("bad_translations") or [])),
                     number_note=pw["numbers"].get(c["id"], []), rules=[], before=None)
        c["check"] = check
        if not c.get("facts"):
            c["status"], c["reason"], c["attribute_to"] = "dropped", "no card", None
        elif not kept:
            c["status"], c["reason"], c["attribute_to"] = "dropped", "no card left: " + "; ".join(sorted(set(off.values()))), None
        elif v is None:
            c["status"] = "unchecked"
            c["reason"] = "no usable judge answer" if (c["id"] in missing or judged is not None) else "not judged"
            c["attribute_to"] = None
        elif v["verdict"] == "not backed":
            c["status"], c["attribute_to"] = "dropped", None
            c["reason"] = f"not backed: {v['problem']}" + (f": {v['why']}" if v["why"] else "")
        else:
            c["status"] = "pending"
        if kept and kept != list(c.get("facts") or []):
            c["facts"] = kept
            c.update({k: rc[k] for k in ("articles", "sides", "neither", "independent", "independent_groups", "flags")})
            if before["articles"] != rc["articles"] or before["sides"] != rc["sides"] or before["independent"] != rc["independent"]:
                check["before"] = before
        elif kept:
            fixed = rc["sides"]
            if fixed != list(c.get("sides") or []):              # a side mark the articles don't back
                check["before"] = before
                c.update(sides=fixed, neither=rc["neither"])
            c["flags"] = rc["flags"]                             # reliability flags, from the sources
        status_of[c["id"]] = c["status"]
    # rules a-d need every claim's status (a conflict with a dropped claim doesn't count)
    for c in sf.get("claims") or []:
        if c["status"] != "pending":
            continue
        v, check = verdicts[c["id"]], c["check"]
        who = (c.get("who_says") or "").strip()
        named = who if who.lower() not in OWN_VOICE else ""
        rules, reasons = [], []
        if v["verdict"] == "needs a name":
            rules.append("a")
            reasons.append(f"the quotes give it as {v['speaker'] or named or 'someone'}'s account")
        if c.get("flags"):
            rules.append("b")
            reasons.append("every source is " + ("unrated" if "unrated only" in c["flags"] else "under 0.5"))
        if not named and c.get("independent", 0) <= 1:
            rules.append("c")
            reasons.append("one outlet, in its own voice")
        live = [x for x in c.get("conflicts_with") or [] if status_of.get(x) not in ("dropped", None)]
        if live or v["against_event"]:
            rules.append("d")
            reasons.append(("conflicts with " + ", ".join(live)) if live else "contradicts the event summary")
            if v["against_event"] and live:
                reasons.append("contradicts the event summary")
        check["rules"] = rules
        if rules:
            c["status"] = "say with source"
            c["attribute_to"] = (v["speaker"] if "a" in rules and v["speaker"] else None) or named or _outlets(c["articles"], src)
            c["reason"] = "; ".join(reasons)
        else:
            c["status"], c["reason"], c["attribute_to"] = "confirmed", "backed", None
        status_of[c["id"]] = c["status"]
    # blindspots: a claim that was dropped or changed sides loses its mark
    lost = set()
    for c in sf.get("claims") or []:
        b = c.get("blindspot")
        if not b:
            continue
        changed = c["check"].get("before") and c["check"]["before"]["sides"] != c.get("sides")
        reported = b.get("silent_side") in (c.get("sides") or [])
        if c["status"] == "dropped" or changed or reported:
            c["check"]["blindspot_removed"] = b.get("status")
            c["blindspot"] = None
            lost.add(c["id"])
    for b in sf.get("blindspots") or []:
        for k in ("central", "detail"):
            if k in b:
                b[k] = [x for x in b[k] if x not in lost]
    for f in facts:
        if f["id"] in bad_tr:
            f["translation_ok"] = False
    cl = sf.get("claims") or []
    n = {s: sum(c["status"] == s for c in cl) for s in STATUSES}
    flags = [x for x in sf.get("flags") or [] if x.get("code") not in FLAGS]
    if cl and n["dropped"] / len(cl) > MANY_DROPS:
        flags.append(flag("many drops", f"{n['dropped']} of {len(cl)} claims dropped (over {MANY_DROPS:.0%})"))
    against = [c["id"] for c in cl if c["check"].get("against_event") and c["status"] != "dropped"]
    if against:
        flags.append(flag("against the event", f"{len(against)} claims", claims=against))
    unchecked = [c["id"] for c in cl if c["status"] == "unchecked" and judged is not None]
    if unchecked:
        flags.append(flag("unchecked", f"{len(unchecked)} claims", claims=unchecked))
    sf["flags"] = flags
    sf["fact_check"] = dict(
        version=VERSION, model=model,
        counts=dict(claims=len(cl), **{s.replace(" ", "_"): n[s] for s in STATUSES},
                    needs_name=sum((c["check"].get("verdict") == "needs a name") for c in cl),
                    rule_a=sum("a" in c["check"]["rules"] for c in cl), rule_b=sum("b" in c["check"]["rules"] for c in cl),
                    rule_c=sum("c" in c["check"]["rules"] for c in cl), rule_d=sum("d" in c["check"]["rules"] for c in cl),
                    cards_off=sum(len(c["check"]["cards_off"]) for c in cl),
                    claims_recounted=sum(bool(c["check"].get("before")) for c in cl),
                    blindspots_removed=len(lost), against_event=len(against), bad_translations=len(bad_tr),
                    number_notes=len(pw["numbers"]), sources_off=len(pw["sources_off"])),
        sources_off=pw["sources_off"],
        calls=(judged or {}).get("calls", 0), errors=(judged or {}).get("errors", [])[:20])
    sf.setdefault("meta", {}).setdefault("steps", {})["fact_check"] = dict(version=VERSION, model=model)
    return facts, sf


# ---- all together ------------------------------------------------------------------------------------

def check_story(sf: dict, facts: list[dict], articles: dict | list, complete=None, *, model: str = "",
                table=None, size: int = BATCH, workers: int = BATCH_WORKERS) -> tuple[list[dict], dict]:
    """The fact check for one story. articles: {id: article} or a list (articles.jsonl rows).
    complete=None runs passes 1 and 3 only: every claim that keeps a card is "unchecked"."""
    if isinstance(articles, list):
        articles = {a["id"]: a for a in articles}
    pw = paperwork(sf, facts, articles, table)
    judged = judge(sf, facts, pw, complete, model=model, size=size, workers=workers) if complete else None
    return apply(sf, facts, pw, judged, model=model if complete else "code")


# ---- the story folder --------------------------------------------------------------------------------
# One folder per story (system map, cross-cutting): module 5 writes facts.jsonl and story_file.json, the
# fact check adds checked_story_file.json beside them, and the script writer (module 7) reads that. The
# folder is found through paths.py only, so the same code runs on a Cloud Storage mount on GCP.

CHECKED_FILE = "checked_story_file.json"


def read_articles(story_dir) -> dict:
    """{article id: article} from the folder's articles.jsonl (Gather's file, with the full texts)."""
    rows = (Path(story_dir) / "articles.jsonl").read_text(encoding="utf-8").split("\n")
    return {a["id"]: a for a in (json.loads(x) for x in rows if x.strip())}


def check_folder(story_dir, complete=None, *, model: str = "", table=None,
                 workers: int = BATCH_WORKERS) -> tuple[list[dict], dict]:
    """check_story() on one story folder: its Story File, facts and articles."""
    facts, sf = story_file.read(story_dir)
    return check_story(sf, facts, read_articles(story_dir), complete, model=model, table=table, workers=workers)


def write_checked(story_dir, facts: list[dict], sf: dict) -> Path:
    """Writes the checked Story File into the story's folder, whole or not at all. facts.jsonl stays
    module 5's file: the facts whose English doesn't match the original are listed in the checked file
    (fact_check.bad_translation_facts) instead."""
    fc = dict(sf.get("fact_check") or {},
              bad_translation_facts=sorted(f["id"] for f in facts if f.get("translation_ok") is False))
    p = Path(story_dir) / CHECKED_FILE
    story_file._atomic(p, json.dumps(dict(sf, fact_check=fc), ensure_ascii=False, indent=1))
    return p


def read_checked(story_dir) -> dict:
    """The checked Story File the script writer reads."""
    return json.loads((Path(story_dir) / CHECKED_FILE).read_text(encoding="utf-8"))
