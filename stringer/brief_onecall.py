"""Module 5, the baseline to beat: one model call reads all the picked articles and writes the Story File.

The four-step build (read each article, merge facts into claims, code adds sides, compare how each
side tells it) has to score better than this on the answer sheets, or this wins for having fewer
parts (decided Nov 24). It covers the model steps 1, 2 and 4 in one call; step 3 is code and will
run on either one's claims, since every claim lists the articles behind it.

The call gets the event, the story's two sides (or that it has none), and each picked full-text
article under a label (R1, R2, ...) with its side, headline and menu-cleaned text, the same text
step 1 sees. Outlet names stay hidden, as in step 1. It returns claims, each with every article that
reports it and that article's exact words, and 2-3 points per side on how the side tells it.

Code checks every quote against the text the model saw (typography only, as in step 1). A source
whose quote isn't there is dropped; a claim left with no checked source is dropped and counted.
Perspective quotes must be in the article cited, and that article must be on the side. There is
no retry for bad quotes, since a retry would rewrite the whole file (a second full call).

Never an unusable answer (decided Nov 25): enforced JSON schema, a generous output limit, one
retry for a broken answer or failed call, then the story is reported as failed, never guessed at.

    write_story(event, articles, lens, groups, complete, *, model) -> {"claims", "perspectives", ...}
"""
from __future__ import annotations

import json
import re

from . import brief_read
from .brief_read import KINDS, MIN_QUOTE_WORDS, find_quote, headline, norm, shown_text

VERSION = "onecall-1"
MAX_CLAIMS = 40
MAX_QUOTE_WORDS = 30
MAX_TOKENS = 32000          # about 8,000 expected; room for long stories and any thinking
CALL_TIMEOUT_S = 600        # one long answer; step 1's calls are short and use 45 s

SCHEMA = {"type": "json_schema", "json_schema": {"name": "story_file", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["claims", "perspectives"],
    "properties": {
        "claims": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["claim", "kind", "who_says", "conflicts_with", "sources"],
            "properties": {
                "claim": {"type": "string"},
                "kind": {"type": "string", "enum": list(KINDS)},
                "who_says": {"type": "string"},
                "conflicts_with": {"type": "array", "items": {"type": "integer"}},
                "sources": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["article", "quote", "quote_en"],
                    "properties": {"article": {"type": "string"}, "quote": {"type": "string"},
                                   "quote_en": {"type": "string"}}}}}}},
        "perspectives": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["side", "points"],
            "properties": {
                "side": {"type": "string", "enum": ["A", "B"]},
                "points": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["point", "quotes"],
                    "properties": {
                        "point": {"type": "string"},
                        "quotes": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["article", "words"],
                            "properties": {"article": {"type": "string"},
                                           "words": {"type": "string"}}}}}}}}}}}}}}

SYSTEM = f"""You write the Story File for one news event from the news articles about it: the checkable facts the articles report, merged into claims, and how each side tells the story. Every claim and every point must be backed by the articles' own words, copied exactly.

Claims (at most {MAX_CLAIMS}, most important first):
- claim: one short English sentence with one checkable thing (who did what, where, when, how many). Use neutral words, not the articles' loaded ones. If the articles say who the claim comes from (police, a ministry, a witness), keep that in the sentence ("Police said at least 12 people died.").
- When several articles report the same fact, write one claim and list every article that reports it. When articles disagree (12 dead against 15), keep both as separate claims and put each one's number (1 for the first claim in your list) in the other's conflicts_with; otherwise conflicts_with is empty.
- kind: "event" (what happened), "number" (a count, amount or measurement), "statement" (what someone said or claimed), "reaction" (how others responded), or "background" (something that happened before this event).
- who_says: who the articles say the claim comes from ("police", "Ukraine's General Staff", "a witness"), or "the outlet" if the articles state it on their own authority.
- sources: every article that reports the claim, each with:
  - article: its label, like "R3";
  - quote: that article's exact words that back the claim, {MIN_QUOTE_WORDS} to {MAX_QUOTE_WORDS} words, one unbroken stretch, in the article's own language. Copy it character for character: no ellipses, no fixes, no joining two sentences. Code checks it against the article, and a source whose quote isn't there is dropped;
  - quote_en: the quote in English if the article is not in English; otherwise an empty string.
- Only facts about this event, or background needed to understand it. Ignore menus, ads, newsletter prompts, links and other stories that may be left in the texts.
- Don't decide which side is right: a claim one side makes is written as that side's claim ("Russia's Defense Ministry said ...").

How each side tells it (perspectives):
- For each side listed with articles, 2 or 3 points on how that side's articles tell the story compared with the other articles: the facts they stress or leave out, and the words they use for the people, groups and the event.
- Each point lists the words it is about: the article label and the words copied exactly from that article (as short as one or two words, such as "blue tsunami"). Cite only that side's articles for its points.
- If the story has no sides, or a side has no articles, write no points for it.

Answer with JSON only."""

RETRY_JSON = brief_read.RETRY_JSON


# ---- the call -----------------------------------------------------------------------------------------

def side_of(group: str) -> str | None:
    """The pick's group (A, B, wire, local, other) as a side: A, B, or None for neither."""
    return group if group in ("A", "B") else None


def side_names(lens: dict) -> dict:
    """{"A": label, "B": label} from the lens, or {} when the story has no real divide."""
    sides = (lens or {}).get("sides") or []
    if (lens or {}).get("kind") == "none" or len(sides) < 2:
        return {}
    return {"A": sides[0].get("label") or sides[0].get("side_id"), "B": sides[1].get("label") or sides[1].get("side_id")}


def prepare(articles: list[dict], groups: dict) -> list[dict]:
    """The full-text articles with their label, side and shown text, in the order given."""
    rows = []
    for a in articles:
        if a.get("text_status") != "full":
            continue
        text, cut = shown_text(a)
        rows.append(dict(label=f"R{len(rows) + 1}", id=a["id"], side=side_of(groups.get(a["id"], "")),
                         headline=headline(a), text=text, text_norm=norm(text), cut=cut))
    return rows


def messages_for(event: dict, lens: dict, rows: list[dict]) -> list[dict]:
    names = side_names(lens)
    ev = (f"Event: {event.get('title', '')}\n{event.get('summary', '')}\n"
          f"Started: {(event.get('start') or '')[:16].replace('T', ' ')} UTC")
    if names:
        have = {r["side"] for r in rows}
        sides = "Sides:\n" + "\n".join(
            f"- Side {k}: {v}" + ("" if k in have else " (no articles here: write no points for it)")
            for k, v in names.items())
    else:
        sides = "Sides: this story has no real divide. Leave perspectives empty."
    arts = "\n\n".join(
        f"=== {r['label']} | side: {('Side ' + r['side']) if r['side'] and names else 'neither'} ===\n"
        f"Headline: {r['headline']}\n\n{r['text']}" for r in rows)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{ev}\n\n{sides}\n\nArticles:\n\n{arts}"}]


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
    """One call plus one retry when the answer isn't usable JSON or the call failed."""
    text, err = brief_read._call(complete, messages, params, name)
    d = _parse(text)
    if d is not None:
        return d, 1, []
    again = messages + ([{"role": "assistant", "content": text}] if text else []) + [{"role": "user", "content": RETRY_JSON}]
    text2, err2 = brief_read._call(complete, again, params, f"{name} retry json")
    return _parse(text2), 2, [e for e in (err, err2) if e]


# ---- checking ------------------------------------------------------------------------------------------

def _words_in(words: str, text_norm: str) -> bool:
    """A perspective's quoted words: any length, but they must be in the article (typography only)."""
    w = norm(words).strip(" .,;:\"'")
    return bool(w) and w in text_norm


def check(d: dict, rows: list[dict], names: dict) -> tuple[list, list, list, dict]:
    """Checked claims, dropped claims, checked perspectives, and the counts."""
    by = {r["label"]: r for r in rows}
    c = dict(claims_first=0, sources_first=0, sources_bad=0, unknown_articles=0, claims_dropped=0,
             persp_quotes=0, persp_bad=0, persp_wrong_side=0, points=0)
    raw = [x for x in (d.get("claims") or []) if isinstance(x, dict) and (x.get("claim") or "").strip()]
    c["claims_first"] = len(raw)
    kept, dropped, num = [], [], {}
    for i, x in enumerate(raw[:MAX_CLAIMS], 1):
        srcs, bad = [], []
        for s in x.get("sources") or []:
            if not isinstance(s, dict):
                continue
            c["sources_first"] += 1
            r = by.get(str(s.get("article", "")).strip())
            pos = find_quote(s.get("quote", ""), r["text_norm"]) if r else -1
            row = dict(article=r["id"] if r else str(s.get("article", "")), label=s.get("article"),
                       quote=(s.get("quote") or "").strip(), quote_en=(s.get("quote_en") or "").strip(), pos=pos)
            if r is None:
                c["unknown_articles"] += 1
            if pos >= 0 and not any(q["article"] == row["article"] for q in srcs):
                srcs.append(row)
            elif pos < 0:
                bad.append(row)
        c["sources_bad"] += len(bad)
        claim = dict(claim=x["claim"].strip(), kind=x.get("kind") if x.get("kind") in KINDS else "event",
                     who_says=(x.get("who_says") or "").strip() or "the outlet", sources=srcs, bad_sources=bad,
                     conflicts_with=[n for n in (x.get("conflicts_with") or []) if isinstance(n, int)],
                     sides=sorted({by[s["label"]]["side"] for s in srcs if by.get(s["label"]) and by[s["label"]]["side"]}))
        if srcs:
            claim["id"] = f"C{len(kept) + 1}"
            num[i] = claim["id"]
            kept.append(claim)
        else:
            dropped.append(claim)
    c["claims_dropped"] = len(dropped)
    for claim in kept:                         # list numbers -> claim ids; conflicts with dropped claims go
        claim["conflicts_with"] = [num[n] for n in claim["conflicts_with"] if n in num and num[n] != claim["id"]]
    persp = []
    for p in d.get("perspectives") or []:
        if not isinstance(p, dict) or p.get("side") not in names:
            continue
        pts = []
        for pt in p.get("points") or []:
            if not isinstance(pt, dict) or not (pt.get("point") or "").strip():
                continue
            qs = []
            for q in pt.get("quotes") or []:
                if not isinstance(q, dict):
                    continue
                c["persp_quotes"] += 1
                r = by.get(str(q.get("article", "")).strip())
                ok = bool(r) and _words_in(q.get("words", ""), r["text_norm"])
                same_side = bool(r) and r["side"] == p["side"]
                c["persp_bad"] += not ok
                c["persp_wrong_side"] += ok and not same_side
                qs.append(dict(article=r["id"] if r else str(q.get("article", "")), words=(q.get("words") or "").strip(),
                               found=ok, same_side=same_side))
            c["points"] += 1
            pts.append(dict(point=pt["point"].strip(), quotes=qs))
        persp.append(dict(side=p["side"], label=names[p["side"]], points=pts))
    return kept, dropped, persp, c


# ---- one story ------------------------------------------------------------------------------------------

def write_story(event: dict, articles: list[dict], lens: dict, groups: dict, complete, *, model: str = "",
                name: str = "brief_onecall") -> dict:
    """The baseline for one story. groups: {article id: the pick's group}."""
    rows = prepare(articles, groups)
    names = side_names(lens)
    out = dict(version=VERSION, articles=[dict(id=r["id"], label=r["label"], side=r["side"], chars=len(r["text"]),
                                                cut=r["cut"]) for r in rows],
               sides=names or "no real divide", claims=[], dropped=[], perspectives=[],
               checks=dict(calls=0, retried_json=False, call_errors=[], error=None))
    ch = out["checks"]
    if not rows:
        ch["error"] = "no full-text articles"
        return out
    d, n, errs = _ask(complete, messages_for(event, lens, rows), params_for(model), name)
    ch.update(calls=n, retried_json=n > 1, call_errors=errs)
    if d is None:
        ch["error"] = "no usable answer after one retry" + (f" ({errs[-1]})" if errs else "")
        return out
    out["claims"], out["dropped"], out["perspectives"], counts = check(d, rows, names)
    ch.update(counts)
    return out
