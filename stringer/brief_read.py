"""Module 5, step 1: read one article and list its facts, each backed by the article's exact words.

One model call per full-text article (small model, outlet name hidden). It gets the event's title,
summary and date plus the article's headline and menu-cleaned text, and returns fact cards and
framing (see SCHEMA). Code then checks every quote word for word against the text the model saw.

Never an unusable answer (decided Nov 25): the JSON shape is enforced by the API where the model
supports it, the output limit is generous, a broken or empty answer is asked again once, and if
that fails too the article gives no facts and is reported, never guessed at. A quote that isn't in
the article gets one retry for that article (telling the model which quotes failed); facts whose
quotes still fail are dropped and counted.

    read_article(event, article, complete) -> {"article", "lang", "facts", "framing", "checks"}
    read_story(event, articles, complete)  -> {"articles": [...], "facts": n, ...}
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import clean

VERSION = "read-2"          # read-2: non-breaking hyphens and thin spaces count as typography
KINDS = ("event", "number", "statement", "reaction", "background")
MAX_FACTS = 15
MAX_TOKENS = 16000          # thinking counts toward this on Haiku; 2,000 was too few in the menu test
TEXT_CHARS = 40000          # about 10,000 tokens; longer cleaned texts are cut (and the cut is recorded)
MIN_QUOTE_WORDS = 4
CALL_TIMEOUT_S = 45        # a call normally takes 5-15 s; DeepSeek once hung for 600 s, and on Nov 27 a live
                           # call hung until the old 180 s limit. The JSON retry follows a timed-out call.
WORKERS = 8                # articles read side by side after the first

SCHEMA = {"type": "json_schema", "json_schema": {"name": "article_facts", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["language", "facts", "framing"],
    "properties": {
        "language": {"type": "string", "description": "ISO 639-1 code of the article's language"},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["fact", "quote", "quote_en", "kind", "who_says"],
            "properties": {
                "fact": {"type": "string"},
                "quote": {"type": "string"},
                "quote_en": {"type": "string"},
                "kind": {"type": "string", "enum": list(KINDS)},
                "who_says": {"type": "string"}}}},
        "framing": {"type": "object", "additionalProperties": False,
                    "required": ["headline", "opening", "terms"],
                    "properties": {
                        "headline": {"type": "string"},
                        "opening": {"type": "string"},
                        "terms": {"type": "array", "items": {"type": "string"}}}}}}}}

SYSTEM = f"""You read one news article about a known event and list the facts it reports. Every fact must be backed by the article's own words, copied exactly.

Rules for facts (at most {MAX_FACTS}, most important first, no repeats):
- fact: one short English sentence with one checkable thing (who did what, where, when, how many). Use neutral words, not the article's loaded ones. If the article says who the fact comes from (police, a ministry, a witness), keep that in the sentence ("Police said at least 12 people died.").
- quote: the article's exact words that back the fact, {MIN_QUOTE_WORDS} to 40 words, one unbroken stretch, in the article's own language. Copy it character for character: no ellipses, no fixes, no joining two sentences. Code checks it against the article.
- quote_en: the quote in English if the article is not in English; otherwise an empty string.
- kind: "event" (what happened), "number" (a count, amount or measurement), "statement" (what someone said or claimed), "reaction" (how others responded), or "background" (something that happened before this event).
- who_says: who the article says the fact comes from ("police", "Ukraine's General Staff", "a witness"), or "the outlet" if the article states it on its own authority.
- Only facts about this event, or background needed to understand it. Ignore menus, ads, newsletter prompts, links and other stories that may be left in the text.

Framing (for comparing how outlets tell the story):
- headline: the article's headline as printed.
- opening: the first sentence of the article's body, copied exactly.
- terms: up to 6 words or short phrases, copied exactly, that the article uses for the main people, groups and the event itself (for example "riot" or "protest", "regime" or "government").

Answer with JSON only."""

RETRY_JSON = "Your last answer could not be read as JSON matching the required shape. Answer again with JSON only."
RETRY_QUOTES = ("These quotes are not in the article word for word:\n{bad}\n"
                "Answer again with the full list. Copy every quote exactly from the article text, or leave that fact out.")


# ---- the text the model sees ---------------------------------------------------------------------

def shown_text(article: dict) -> tuple[str, bool]:
    """Menu-cleaned text, link markup reduced to the link's words, images removed, starting at the
    first headline line if there is one, cut at TEXT_CHARS. Returns (text, was_cut)."""
    t = clean.clean(article.get("text") or "")
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = clean.LINK.sub(lambda m: m.group(1), t)
    m = re.search(r"^# ", t, re.M)
    if m and len(t) - m.start() > 500:
        t = t[m.start():]
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:TEXT_CHARS], len(t) > TEXT_CHARS


def headline(article: dict) -> str:
    return re.split(r"\s[-|–—]\s(?=[^-|–—]*$)", article.get("title") or "")[0]     # drop " - Outlet Name"


def messages_for(event: dict, article: dict, text: str) -> list[dict]:
    ev = (f"Event: {event.get('title', '')}\n{event.get('summary', '')}\n"
          f"Started: {(event.get('start') or '')[:16].replace('T', ' ')} UTC")
    body = f"{ev}\n\nArticle headline: {headline(article)}\n\nArticle text:\n{text}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": body}]


# ---- checking quotes --------------------------------------------------------------------------------

_SAME = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                       "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
                       "–": "-", "—": "-", "−": "-", " ": " ", "*": "", "_": "",
                       # read-2: non-breaking and other hyphens, thin spaces, invisible marks
                       "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2015": "-",
                       "\u2007": " ", "\u2009": " ", "\u200a": " ", "\u202f": " ",
                       "\u200b": "", "\u00ad": "", "\u2060": ""})


def norm(s: str) -> str:
    """Forgives only typography: curly vs straight quotes, dash kinds, spaces, markdown emphasis."""
    return re.sub(r"\s+", " ", (s or "").translate(_SAME)).strip()


def find_quote(quote: str, text_norm: str) -> int:
    """Position of the quote in the normalized article text, or -1. Too-short quotes never match."""
    q = norm(quote).strip(" .,;:\"'")
    if len(q.split()) < MIN_QUOTE_WORDS:
        return -1
    return text_norm.find(q)


# ---- one article ------------------------------------------------------------------------------------

def _parse(text: str) -> dict | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(d, dict) or not isinstance(d.get("facts"), list):
        return None
    return d


def _call(complete, messages, params, name):
    """One call; a failed call (timeout, provider error) counts as an empty answer. The eval's cost
    cap is the one error that must stop the run, so it passes through."""
    try:
        return complete(messages, name=name, **params).text or "", None
    except Exception as e:
        if type(e).__name__ == "BudgetExceeded":
            raise
        return "", f"{type(e).__name__}: {e}"[:300]


def _ask(complete, messages, params, name):
    """One call plus one retry when the answer isn't usable JSON (or the call failed).
    Returns (parsed or None, calls, call errors)."""
    text, err = _call(complete, messages, params, name)
    d = _parse(text)
    if d is not None:
        return d, 1, []
    again = messages + ([{"role": "assistant", "content": text}] if text else []) + [{"role": "user", "content": RETRY_JSON}]
    text2, err2 = _call(complete, again, params, f"{name} retry json")
    return _parse(text2), 2, [e for e in (err, err2) if e]


def _check(d: dict, text_norm: str):
    good, bad = [], []
    for f in d.get("facts") or []:
        if not isinstance(f, dict) or not (f.get("fact") or "").strip():
            continue
        pos = find_quote(f.get("quote", ""), text_norm)
        kind = f.get("kind") if f.get("kind") in KINDS else "event"
        row = dict(fact=f["fact"].strip(), quote=(f.get("quote") or "").strip(),
                   quote_en=(f.get("quote_en") or "").strip(), kind=kind,
                   who_says=(f.get("who_says") or "").strip() or "the outlet", pos=pos)
        (good if pos >= 0 else bad).append(row)
    return good, bad


def params_for(model: str) -> dict:
    p = dict(max_tokens=MAX_TOKENS, response_format=SCHEMA, timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        p["reasoning_effort"] = "low"
    return p


def read_article(event: dict, article: dict, complete, *, model: str = "", name: str = "brief_read") -> dict:
    text, cut = shown_text(article)
    text_norm = norm(text)
    out = dict(article=article["id"], lang=None, facts=[], framing=None,
               checks=dict(calls=0, retried_json=False, retried_quotes=False, facts_first=0, quotes_bad_first=0,
                           facts_dropped=0, text_chars=len(text), text_cut=cut, error=None))
    c = out["checks"]
    msgs = messages_for(event, article, text)
    params = params_for(model)
    d, n, errs = _ask(complete, msgs, params, name)
    c["calls"] += n
    c["retried_json"] = n > 1
    c["call_errors"] = errs
    if d is None:
        c["error"] = "no usable answer after one retry" + (f" ({errs[-1]})" if errs else "")
        return out
    good, bad = _check(d, text_norm)
    c["facts_first"], c["quotes_bad_first"] = len(good) + len(bad), len(bad)
    if bad:                                    # one retry for this article, naming the failed quotes
        c["retried_quotes"] = True
        note = RETRY_QUOTES.format(bad="\n".join(f"- {b['quote'][:300]}" for b in bad[:20]))
        again = msgs + [{"role": "assistant", "content": json.dumps(d, ensure_ascii=False)},
                        {"role": "user", "content": note}]
        d2, n2, errs2 = _ask(complete, again, params, f"{name} retry quotes")
        c["calls"] += n2
        c["call_errors"] += errs2
        if d2 is not None:
            g2, b2 = _check(d2, text_norm)
            if len(g2) >= len(good):           # keep the better of the two answers
                d, good, bad = d2, g2, b2
    c["facts_dropped"] = len(bad)
    out["lang"] = (d.get("language") or "").strip().lower()[:5] or None
    fr = d.get("framing") if isinstance(d.get("framing"), dict) else {}
    out["framing"] = dict(headline=(fr.get("headline") or "").strip(), opening=(fr.get("opening") or "").strip(),
                          terms=[t for t in (fr.get("terms") or []) if isinstance(t, str) and t.strip()][:6])
    seen = set()
    for f in good[:MAX_FACTS]:
        if norm(f["quote"]) in seen:
            continue
        seen.add(norm(f["quote"]))
        f["id"] = f"{article['id']}#{len(out['facts']) + 1}"
        out["facts"].append(f)
    return out


def read_story(event: dict, articles: list[dict], complete, *, model: str = "", workers: int = WORKERS) -> dict:
    """Step 1 for one story: every full-text article. The first is read alone so the shared instructions
    are in the provider's cache, then the rest side by side (map, prompt caching: fan-out). Nov 27: read
    one after another, a live story's 10-12 articles took a minute of the 5 a grader waits."""
    todo = [a for a in articles if a.get("text_status") == "full"]
    read = lambda a: read_article(event, a, complete, model=model)
    rows = [read(a) for a in todo[:1]]
    if len(todo) > 1:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            rows += list(ex.map(read, todo[1:]))
    return dict(version=VERSION, articles=rows, facts=sum(len(r["facts"]) for r in rows),
                failed=[r["article"] for r in rows if r["checks"]["error"]])
