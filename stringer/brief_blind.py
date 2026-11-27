"""Module 5, step 3b: a judge checks step 3's blindspot candidates against the silent side's own text.

Step 3 (code, brief_sides.py) lists claims one side reports and the other side doesn't, but it sees an
article only through step 1's fact cards, so a fact step 1 left out of an article looks missing. On
the 26 test stories, even candidates with 3+ independent sources were often reported by the silent
side in other words (Nov 25). So one call per silent side reads the candidates and the full text of
that side's read articles, and says for each claim:
  "reports it"         an article states the same fact; it must copy the sentence, and code checks it
  "different account"  an article covers the same point but tells it another way (also quoted)
  "missing"            no article on that side states it: a confirmed blindspot
plus whether the fact is central to the story or a detail.

Code checks every quote word for word (brief_read.find_quote). A bad quote gets one retry naming it;
if it is still bad, or the retry turns it into "missing", the claim is "unclear" and is not passed on
as a blindspot; so is "missing" with a quote that is in the article (the model found something). A failed call (after one retry) leaves that side's candidates "unchecked", also not
passed on. So a wrong blindspot needs the model to say "missing" on its first answer.

Only candidates with MIN_SOURCES+ independent sources are checked (one-article claims are mostly one
outlet's extra detail), strongest first, at most MAX_CLAIMS per side.

    judge_blindspots(sides, articles, event, complete, model=...) -> step 3's output with the checks added
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import brief_read
from .brief_read import find_quote, headline, norm, shown_text

VERSION = "blind-4"          # blind-4: "missing" with a quote that is in the article counts as unclear
                             #          (the Fed's 10-2 vote, quoted from NPR, was called missing).
                             #          On the 26 stories: 45 blindspots, 38 right (hand check), central 20 of 25.
                             # blind-5 (tried Nov 25, not used): a fact given by another speaker counts as reported;
                             #          the quote must state the claim's main fact. It found the Kerch arch collapse
                             #          but read "main fact" too literally (wanted the speaker, "six days"):
                             #          57 blindspots, 43 right, central 22 of 33. Run it with --opt prompt=blind-5.
                             # blind-3: the retry also names claims with no answer (one side got {"checks": []})
                             # blind-2: claim ids and article labels fixed in the answer's shape, and
                             #          rows matched by id, then claim text, then order (blind-1 lost 35 of 93)
MIN_SOURCES = 2          # candidates with at least this many independent sources are checked
MAX_CLAIMS = 10          # per silent side, strongest first (the 26 test stories: at most 15 a story)
MAX_TOKENS = {"blind-4": 16000, "blind-5": 8000}   # version -> answer limit
CALL_TIMEOUT_S = 300
VERDICTS = ("reports it", "different account", "missing")
MATTERS = ("central", "detail")

def schema_for(ids: list[str], labels: list[str]) -> dict:
    """The answer's shape, with the claim ids and article labels fixed to the ones asked about
    (blind-1 let the model write the claim's text, once in Russian, where the id belonged)."""
    return {"type": "json_schema", "json_schema": {"name": "blindspot_checks", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["checks"],
        "properties": {"checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["claim_id", "quote", "quote_en", "article", "why", "verdict", "matters"],
            "properties": {"claim_id": {"type": "string", "enum": list(ids)},
                           "quote": {"type": "string"}, "quote_en": {"type": "string"},
                           "article": {"type": "string", "enum": [*labels, ""]}, "why": {"type": "string"},
                           "verdict": {"type": "string", "enum": list(VERDICTS)},
                           "matters": {"type": "string", "enum": list(MATTERS)}}}}}}}}


SYSTEM = """You check what one side's news coverage leaves out. You get claims that outlets on one side of a story report, and the full text of the articles from the other side (the "silent side"), which supposedly don't report them. For each claim, read every silent-side article and decide whether it states that fact.

For each claim, in this order:
- claim_id: the claim's id as given (C12), never its text.
- quote: if a silent-side article states the claim's fact or gives its own version of the same point, copy the sentence that does, word for word from the article, in the article's language (at least 6 words; never shorten, translate or fix it). Otherwise "".
- quote_en: the quote in English if the article isn't in English, otherwise "".
- article: the label of the quote's article (S1, S2, ...), otherwise "".
- why: a few words on what you found.
- verdict:
  - "reports it": the article states the same fact, even in other words, more briefly, with a rounded number, or inside a longer sentence;
  - "different account": the article covers exactly the same point but tells it another way: another number, cause, outcome or culprit, or a denial ("the damage was minor" against "the span collapsed");
  - "missing": no silent-side article states the fact or covers that point. Mentioning the topic, the place or the people is not stating the fact.
- matters: "central" if a viewer needs the fact to understand what happened (what happened, the toll or scale, who did it or is blamed, the main decision, outcome or official response); "detail" for background, color, side remarks, small figures and reactions of minor players.

Answer once for every claim, in the order given, with JSON only."""

SYSTEM_2 = """You check what one side's news coverage leaves out. You get claims that outlets on one side of a story report, and the full text of the articles from the other side (the "silent side"), which supposedly don't report them. For each claim, read every silent-side article and decide whether its readers learn that fact.

For each claim, in this order:
- claim_id: the claim's id as given (C12), never its text.
- quote: if a silent-side article states the claim's main fact or gives its own version of it, copy the sentence that does, word for word from the article, in the article's language (at least 6 words; never shorten, translate or fix it). Otherwise "".
- quote_en: the quote in English if the article isn't in English, otherwise "".
- article: the label of the quote's article (S1, S2, ...), otherwise "".
- why: a few words on what the quote says and whether it is the claim's main fact.
- verdict:
  - "reports it": the article states the claim's main fact, even in other words, more briefly, with a rounded number, inside a longer sentence, or from another speaker or source. A fact counts even when someone else says it: for "a company spokesperson said the chief executive will stay on", the sentence "the chief executive will remain in his post" reports it. But a reaction or opinion (someone criticizing, praising, warning, demanding) counts only if the article gives that same person's reaction;
  - "different account": the article covers exactly the same point but tells it another way: another number, cause, outcome or culprit, or a denial ("the damage was minor" against "the dam burst");
  - "missing": no silent-side article states the claim's main fact or covers that point.
  The quote must state the main fact itself. A sentence about a consequence, a related event, the topic, the place or the people is not enough: for "the dam burst", "roads in the valley were closed" doesn't report it, so if nothing else does, the verdict is "missing".
- matters: "central" if a viewer needs the fact to understand what happened (what happened, the toll or scale, who did it or is blamed, the main decision, outcome or official response); "detail" for background, color, side remarks, small figures and reactions of minor players.

Answer once for every claim, in the order given, with JSON only."""

PROMPTS = {"blind-4": SYSTEM, "blind-5": SYSTEM_2}


RETRY_JSON = brief_read.RETRY_JSON
RETRY_QUOTES = ("These quotes are not word for word in the article you named:\n{bad}\n"
                "For these claims, copy the sentence exactly as it appears in the article (same language, same words).")
RETRY_SKIPPED = "You gave no answer for these claims: {ids}. Check them too."
RETRY_END = "Answer again for all claims, with JSON only."


def candidates(sides: dict) -> list[dict]:
    """The candidates to check, per silent side: [{silent_side, label, reported_by, claims, cut}]."""
    out = []
    for b in sides.get("blindspots") or []:
        ids = [c for c in b["claims"] if (b.get("sources") or {}).get(c, 1) >= MIN_SOURCES]
        if ids:
            out.append(dict(silent_side=b["silent_side"], label=b.get("label") or b["silent_side"],
                            reported_by=b.get("reported_by"), claims=ids[:MAX_CLAIMS], cut=max(0, len(ids) - MAX_CLAIMS)))
    return out


def silent_articles(sides: dict, articles: list[dict], side_id: str) -> list[dict]:
    """The silent side's read articles, in pick order."""
    ids = [s["id"] for s in sides.get("sources") or [] if s.get("side") == side_id and s.get("read")]
    by = {a["id"]: a for a in articles}
    return [by[i] for i in ids if i in by]


def messages_for(event: dict, claims: list[dict], arts: list[dict], label: str, outlets: dict,
                 prompt: str = VERSION) -> tuple[list[dict], dict]:
    """(messages, {S1: article id}). claims: the candidate claims (step 3's claim dicts)."""
    labels = {f"S{i}": a["id"] for i, a in enumerate(arts, 1)}
    cl = "\n".join(f"- {c['id']}: {c['claim']} (reported by: {', '.join(sorted({outlets.get(a, a) for a in c['articles']}))})"
                   for c in claims)
    parts = []
    for lab, a in zip(labels, arts):
        text, _ = shown_text(a)
        when = (a.get("published_at") or "")[:16].replace("T", " ")
        parts.append(f"[{lab}] {outlets.get(a['id'], a.get('outlet', ''))}, {when} UTC\nHeadline: {headline(a)}\n{text}")
    body = (f"Event: {event.get('title', '')}\n{event.get('summary', '')}\n\n"
            f"Claims to check ({len(claims)}):\n{cl}\n\n"
            f"Silent side: {label}. Its articles ({len(arts)}):\n\n" + "\n\n---\n\n".join(parts))
    return [{"role": "system", "content": PROMPTS[prompt]}, {"role": "user", "content": body}], labels


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
        if isinstance(d, dict) and isinstance(d.get("checks"), list):
            return d
    return None


def _ask(complete, messages, params, name):
    """One call plus one retry when the answer isn't usable JSON. Returns (parsed or None, calls, errors)."""
    text, err = brief_read._call(complete, messages, params, name)
    d = _parse(text)
    if d is not None:
        return d, 1, [e for e in (err,) if e]
    again = messages + ([{"role": "assistant", "content": text}] if text else []) + [{"role": "user", "content": RETRY_JSON}]
    text2, err2 = brief_read._call(complete, again, params, f"{name} retry json")
    return _parse(text2), 2, [e for e in (err, err2) if e]


def _match(checks: list, ids: list[str], claims: dict) -> dict:
    """{claim id: answer row}: by id, then by the claim's text, then by order when the unmatched rows
    and claims line up one to one."""
    rows = [x for x in checks if isinstance(x, dict)]
    out, left = {}, []
    by_text = {_key(claims[i]["claim"]): i for i in ids if i in claims}
    for x in rows:
        cid = str(x.get("claim_id") or x.get("claim") or "").strip()
        cid = next((i for i in ids if i.lower() == cid.lower()), None) or by_text.get(_key(cid))
        if cid and cid not in out:
            out[cid] = x
        else:
            left.append(x)
    todo = [i for i in ids if i not in out]
    if left and len(left) == len(todo):
        out.update(zip(todo, left))
    return out


def _key(s: str) -> str:
    return " ".join(re.findall(r"\w+", (s or "").lower()))


def _rows(d: dict, ids: list[str], labels: dict, texts: dict, claims: dict | None = None) -> dict:
    """{claim id: row} from one answer; each row's quote checked against the named article."""
    out = {}
    for cid, x in _match(d.get("checks") or [], ids, claims or {}).items():
        v = x.get("verdict") if x.get("verdict") in VERDICTS else None
        art = labels.get((x.get("article") or "").strip())
        q = (x.get("quote") or "").strip()
        ok = bool(art and q and find_quote(q, texts[art]) >= 0)
        out[cid] = dict(claim=cid, verdict=v, matters=x.get("matters") if x.get("matters") in MATTERS else "detail",
                        article=art, quote=q, quote_en=(x.get("quote_en") or "").strip(),
                        why=(x.get("why") or "").strip()[:300], quote_ok=ok)
    return out


def _status(row: dict | None, retried: bool = False) -> str:
    """What the check means for the Story File: blindspot, reported, told differently, unclear or unchecked."""
    if row is None or row["verdict"] is None:
        return "unchecked"
    if row["verdict"] == "missing":           # blind-4: "missing" while quoting a sentence it found is not sure
        return "unclear" if retried or row["quote_ok"] else "blindspot"
    if not row["quote_ok"]:
        return "unclear"
    return "reported" if row["verdict"] == "reports it" else "told differently"


def judge_side(event: dict, cand: dict, claims: dict, arts: list[dict], outlets: dict, complete, *,
               model: str = "", name: str = "brief_blind", prompt: str = VERSION) -> dict:
    """One silent side: one call (plus a JSON retry, and one retry for bad quotes or claims with no answer)."""
    ids = cand["claims"]
    res = dict(silent_side=cand["silent_side"], label=cand["label"], reported_by=cand["reported_by"],
               checked=[], cut=cand["cut"], calls=0, retried_quotes=False, quotes_bad_first=0, skipped_first=0, error=None, call_errors=[])
    if not arts:
        res["error"] = "no silent-side article text"
        res["checked"] = [dict(claim=i, status="unchecked") for i in ids]
        return res
    msgs, labels = messages_for(event, [claims[i] for i in ids], arts, cand["label"], outlets, prompt)
    texts = {a["id"]: norm(shown_text(a)[0]) for a in arts}
    params = dict(max_tokens=MAX_TOKENS[prompt], response_format=schema_for(ids, list(labels)), timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        params["reasoning_effort"] = "low"
    d, n, errs = _ask(complete, msgs, params, name)
    res["calls"] += n
    res["call_errors"] += errs
    if d is None:
        res["error"] = "no usable answer after one retry" + (f" ({errs[-1]})" if errs else "")
        res["checked"] = [dict(claim=i, status="unchecked") for i in ids]
        return res
    rows = _rows(d, ids, labels, texts, claims)
    status = {i: _status(rows.get(i)) for i in ids}
    bad = [rows[i] for i in ids if i in rows and rows[i]["verdict"] in ("reports it", "different account") and not rows[i]["quote_ok"]]
    skipped = [i for i in ids if status[i] == "unchecked"]
    res["quotes_bad_first"], res["skipped_first"] = len(bad), len(skipped)
    if bad or skipped:                        # one retry, naming the bad quotes and the claims with no answer
        res["retried_quotes"] = bool(bad)
        inv = {v: k for k, v in labels.items()}
        note = []
        if bad:
            note.append(RETRY_QUOTES.format(bad="\n".join(f"- {x['claim']} ({inv.get(x['article'], 'no article named')}): "
                                                          f"{x['quote'][:300]}" for x in bad)))
        if skipped:
            note.append(RETRY_SKIPPED.format(ids=", ".join(skipped)))
        again = msgs + [{"role": "assistant", "content": json.dumps(d, ensure_ascii=False)},
                        {"role": "user", "content": "\n\n".join(note + [RETRY_END])}]
        d2, n2, errs2 = _ask(complete, again, params, f"{name} retry")
        res["calls"] += n2
        res["call_errors"] += errs2
        rows2 = _rows(d2, ids, labels, texts, claims) if d2 else {}
        for x in bad:                         # a bad quote that is still bad, or turns "missing", stays unclear
            r2 = rows2.get(x["claim"])
            if r2 is not None:
                rows[x["claim"]] = r2
            status[x["claim"]] = _status(r2, retried=True) if r2 is not None else "unclear"
        for i in skipped:                     # a first answer for these claims
            if rows2.get(i) is not None:
                rows[i] = rows2[i]
                status[i] = _status(rows2[i])
    for i in ids:
        r = rows.get(i)
        res["checked"].append(dict(r or dict(claim=i), status=status[i]))
    return res


def judge_blindspots(sides: dict, articles: list[dict], event: dict, complete, *, model: str = "",
                     name: str = "brief_blind", prompt: str = VERSION) -> dict:
    """Step 3's output with each checked side's results, the confirmed blindspots and counts added."""
    return with_judged(sides, judge_sides(sides, articles, event, complete, model=model, name=name, prompt=prompt),
                       prompt=prompt)


def judge_sides(sides: dict, articles: list[dict], event: dict, complete, *, model: str = "",
                name: str = "brief_blind", prompt: str = VERSION) -> list[dict]:
    """The judge's calls: one result per silent side, in candidates() order. The two sides don't read each
    other's answers, so they are asked side by side."""
    claims = {c["id"]: c for c in sides.get("claims") or []}
    outlets = {s["id"]: s.get("outlet_name") or s.get("outlet") or s["id"] for s in sides.get("sources") or []}
    cands = candidates(sides)

    def one(cand):
        arts = silent_articles(sides, articles, cand["silent_side"])
        return judge_side(event, cand, claims, arts, outlets, complete, model=model,
                          name=f"{name} {cand['silent_side']}", prompt=prompt)
    if len(cands) < 2:
        return [one(c) for c in cands]
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        return list(ex.map(one, cands))


def with_judged(sides: dict, judged: list[dict], *, prompt: str = VERSION) -> dict:
    """Step 3's output with judge_sides()'s results joined in. `sides` may be a later copy of step 3's
    output than the one the judge read (same claims, with conflict marks added since)."""
    out = dict(sides)
    status = {}
    for j in judged:
        for r in j["checked"]:
            status[r["claim"]] = (j["silent_side"], r)
    out["claims"] = []
    for c in sides.get("claims") or []:
        c = dict(c)
        if c["id"] in status:
            r = status[c["id"]][1]
            c["blindspot_check"] = dict(status=r["status"], matters=r.get("matters"))
        out["claims"].append(c)
    out["blindspot_checks"] = judged
    out["confirmed_blindspots"] = [dict(silent_side=j["silent_side"], label=j["label"], reported_by=j["reported_by"],
                                        central=[r["claim"] for r in j["checked"] if r["status"] == "blindspot" and r.get("matters") == "central"],
                                        detail=[r["claim"] for r in j["checked"] if r["status"] == "blindspot" and r.get("matters") != "central"])
                                   for j in judged if any(r["status"] == "blindspot" for r in j["checked"])]
    rows = [r for j in judged for r in j["checked"]]
    cnt = lambda s: sum(r["status"] == s for r in rows)
    out["blind_counts"] = dict(version=prompt, candidates=sum(len(b["claims"]) for b in sides.get("blindspots") or []),
                               checked=len(rows), cut=sum(j["cut"] for j in judged), sides_checked=len(judged),
                               blindspot=cnt("blindspot"), central=sum(r["status"] == "blindspot" and r.get("matters") == "central" for r in rows),
                               reported=cnt("reported"), told_differently=cnt("told differently"), unclear=cnt("unclear"),
                               unchecked=cnt("unchecked"), quotes_bad_first=sum(j["quotes_bad_first"] for j in judged),
                               calls=sum(j["calls"] for j in judged), errors=sum(bool(j["error"]) for j in judged))
    return out
