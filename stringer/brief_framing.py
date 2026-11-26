"""Module 5, step 4: how each side tells it. One call per story with two sides.

In:  step 3's output (claims with the sides that report them, the slim sources list, the story's sides
     and flags), step 1's framing per read article (headline, opening sentence, up to 6 words it uses
     for the main people and the event, all in the article's language), and the picked articles
     (their text, so code can check quotes; a snippet-only article gives its headline only).
Out: for each side with articles, 2-3 points on how its outlets tell the story differently from the
     other side: the words they use, what they lead with, whose voices they quote, who they blame or
     credit. Each point quotes the side's own words with the article they come from.

Rules (system map, module 5, step 4; decided Nov 24-25):
- Skipped for stories with no real divide: the Story File records "no real divide".
- A side with no article (empty side) is skipped and recorded; the other side still gets its points
  (what its outlets call things and stress), and the video says the silent side had no coverage.
- Code checks every quote word for word (typography forgiven, case ignored, whole words) in the named
  article's headline, opening or cleaned text. One retry names the bad quotes; then bad quotes are
  dropped, and a point left with no good quote is dropped.
- The model sees no outlet names in the claims list, only in the article list, so it can name an
  outlet when a point rests on one article.

    frame_story(sides, step1, articles, event, complete, model=...) -> the step 4 part of the Story File
"""
from __future__ import annotations

import json
import re

from . import brief_read
from .brief_read import headline, norm, shown_text

VERSION = "frame-2"       # frame-2: the claims are marked as our summaries, never to quote (frame-1 quoted them
                          #          for about half of its 57 bad quotes); one word-list item per quote; limit
                          #          4,000 tokens (the longest frame-1 answer was 1,304). Code (both versions):
                          #          "a; b" is checked as two quotes, a quote found in another article of the same
                          #          side counts for that article, CJK text matches without word boundaries
MAX_POINTS = 3            # per side
MAX_CLAIMS = 12           # claims only that side reports, shown per side (most independent sources first)
MAX_TOKENS = {"frame-1": 8000, "frame-2": 4000}   # version -> answer limit
CALL_TIMEOUT_S = 300
KINDS = ("word choice", "emphasis", "voices", "blame or credit")

SYSTEM = """You compare how two sides' news outlets tell the same story. For each side you get its articles (outlet, headline, opening sentence and the words it uses for the main people, groups and the event) and the claims only that side reports.

For each side, give 2 or 3 points on how its outlets tell the story differently from the other side. Kinds of points:
- "word choice": the words used for the event, the people or the place ("riot" against "protest", "regime" against "government", "occupied Crimea" against "Crimea");
- "emphasis": what the side leads with or stresses, and what it plays down;
- "voices": whose words the side relies on (officials of one government, the military, victims, experts);
- "blame or credit": who the side holds responsible or gives credit to.

Each point:
- point: one neutral sentence describing how this side tells it, in English. Describe, don't judge which side is right. If it rests on one article, name the outlet ("Fox News calls it ..."); prefer what several of the side's articles share.
- kind: one of the kinds above.
- quotes: 1 to 4 short quotes (a word to a sentence) that show it, copied exactly from that side's headlines, openings or word lists, in the article's language, each with its article label (A1, B2, ...), plus an English translation if it isn't English (otherwise "").

A point must be about the side, not a single fact, and must differ from the other side: if both sides use the same words, it isn't a point. Answer with JSON only."""

SYSTEM_2 = SYSTEM.replace(
    "and the claims only that side reports.",
    "and the claims only that side reports. The claims are our own neutral summaries in English, not the outlets' "
    "words: use them only to see what each side stresses, and never quote them.").replace(
    "copied exactly from that side's headlines, openings or word lists, in the article's language,",
    "copied exactly from that side's headline, opening or word-list lines, in the article's language (one word-list "
    "item per quote; don't join items),")
assert SYSTEM_2 != SYSTEM and SYSTEM_2.count("never quote them") == 1 and SYSTEM_2.count("one word-list item") == 1

PROMPTS = {"frame-1": SYSTEM, "frame-2": SYSTEM_2}


RETRY_JSON = brief_read.RETRY_JSON
RETRY_QUOTES = ("These quotes are not word for word in the article you named:\n{bad}\n"
                "Copy each quote exactly as it appears in that article's headline, opening or word list, or "
                "replace it with one that does. Answer again for both sides, with JSON only.")


def schema_for(labels: dict) -> dict:
    """labels: {"A": [A1, A2, ...], "B": [...]} for the sides that get points."""
    def point(labs):
        return {"type": "object", "additionalProperties": False, "required": ["point", "kind", "quotes"],
                "properties": {"point": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
                               "quotes": {"type": "array", "items": {
                                   "type": "object", "additionalProperties": False,
                                   "required": ["article", "words", "words_en"],
                                   "properties": {"article": {"type": "string", "enum": labs},
                                                  "words": {"type": "string"}, "words_en": {"type": "string"}}}}}}
    props = {f"side_{g.lower()}": {"type": "object", "additionalProperties": False, "required": ["points"],
                                   "properties": {"points": {"type": "array", "items": point(labs)}}}
             for g, labs in labels.items()}
    return {"type": "json_schema", "json_schema": {"name": "framing", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": list(props), "properties": props}}}


def side_articles(sides: dict, articles: list[dict], side_id: str) -> list[dict]:
    """The picked articles on one side, in pick order (read or snippet-only)."""
    by = {a["id"]: a for a in articles}
    return [by[s["id"]] for s in sides.get("sources") or [] if s.get("side") == side_id and s["id"] in by]


def _hay(article: dict, fr: dict | None) -> str:
    fr = fr or {}
    parts = [headline(article), article.get("title") or "", fr.get("headline") or "", fr.get("opening") or "",
             "\n".join(fr.get("terms") or []), shown_text(article)[0]]
    return norm("\n".join(parts)).lower()


_ARABIC = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " "})
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def found(words: str, hay: str) -> bool:
    """The words appear in the text as whole words (typography forgiven, case ignored; Chinese, Japanese
    and Korean match as plain text, since they have no spaces)."""
    w = norm(words.translate(_ARABIC)).strip(" .,;:!?\"'«»“”„()").lower()
    if len(w) < 3 and not (_CJK.search(w) and len(w) >= 2):
        return False
    hay = hay.translate(_ARABIC)
    if _CJK.search(w):
        return w in hay
    return re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", hay) is not None


def locate(words: str, label: str, side_labels: list[str], labels: dict, hays: dict) -> list[tuple[str, str]]:
    """[(label, words)] for a quote: the named article first, then the side's other articles; "a; b"
    that isn't found whole is checked as separate quotes. Empty when nothing is found."""
    order = [label] + [l for l in side_labels if l != label] if label in side_labels else list(side_labels)
    for lab in order:
        if found(words, hays[labels[lab]]):
            return [(lab, words)]
    if ";" in words:
        parts = [x.strip() for x in words.split(";") if x.strip()]
        got = [locate(x, label, side_labels, labels, hays) for x in parts]
        if all(got):
            return [g[0] for g in got]
    return []


def messages_for(event: dict, groups: dict, framing: dict, outlets: dict, prompt: str = VERSION) -> tuple[list[dict], dict]:
    """groups: {"A": {"label", "articles": [...], "claims": [...]}, ...}. Returns (messages, {label: article id})."""
    labels, blocks = {}, []
    for g, s in groups.items():
        lines = [f"Side {g}: {s['label']} ({len(s['articles'])} articles)"]
        for i, a in enumerate(s["articles"], 1):
            lab = f"{g}{i}"
            labels[lab] = a["id"]
            fr = framing.get(a["id"])
            if fr:
                terms = "; ".join(fr.get("terms") or [])
                lines.append(f"[{lab}] {outlets.get(a['id'], a['id'])}\n  Headline: {fr.get('headline') or headline(a)}\n"
                             f"  Opening: {fr.get('opening') or ''}\n  Words used: {terms}")
            else:
                lines.append(f"[{lab}] {outlets.get(a['id'], a['id'])}\n  Headline: {headline(a)}\n  (headline only)")
        cl = s["claims"]
        lines.append(f"Claims only side {g} reports ({len(cl)}" + (f" of {s['claims_total']}, most-sourced first" if s['claims_total'] > len(cl) else "") + "):")
        lines += [f"- {c}" for c in cl] or ["- (none)"]
        blocks.append("\n".join(lines))
    body = f"Event: {event.get('title', '')}\n{event.get('summary', '')}\n\n" + "\n\n".join(blocks)
    return [{"role": "system", "content": PROMPTS[prompt]}, {"role": "user", "content": body}], labels


def _parse(text: str, keys: list[str]) -> dict | None:
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
        if isinstance(d, dict) and any(isinstance(d.get(k), dict) and d[k].get("points") for k in keys):
            return d
    return None


def _ask(complete, messages, params, name, keys):
    """One call plus one retry when the answer isn't usable JSON with at least one point."""
    text, err = brief_read._call(complete, messages, params, name)
    d = _parse(text, keys)
    if d is not None:
        return d, 1, [e for e in (err,) if e]
    again = messages + ([{"role": "assistant", "content": text}] if text else []) + [{"role": "user", "content": RETRY_JSON}]
    text2, err2 = brief_read._call(complete, again, params, f"{name} retry json")
    return _parse(text2, keys), 2, [e for e in (err, err2) if e]


def _check(d: dict, groups: dict, labels: dict, hays: dict):
    """{side: [points with each quote checked]}, and the bad quotes [(label, words)]."""
    out, bad = {}, []
    for g in groups:
        pts = []
        for p in ((d.get(f"side_{g.lower()}") or {}).get("points") or [])[:MAX_POINTS]:
            if not isinstance(p, dict) or not (p.get("point") or "").strip():
                continue
            qs = []
            side_labels = [l for l in labels if l.startswith(g)]
            for q in p.get("quotes") or []:
                if not isinstance(q, dict) or not (q.get("words") or "").strip():
                    continue
                lab, words = (q.get("article") or "").strip(), q["words"].strip()
                hits = locate(words, lab, side_labels, labels, {labels[l]: hays[labels[l]] for l in side_labels})
                for hl, hw in hits:
                    qs.append(dict(label=hl, article=labels[hl], words=hw, ok=True,
                                   words_en=(q.get("words_en") or "").strip() if hw == words else ""))
                if not hits:
                    qs.append(dict(label=lab, article=labels.get(lab), words=words, words_en=(q.get("words_en") or "").strip(), ok=False))
                    bad.append((lab, words))
            pts.append(dict(point=p["point"].strip(), kind=p.get("kind") if p.get("kind") in KINDS else "emphasis", quotes=qs))
        out[g] = pts
    return out, bad


def outlets_and_framing(sides: dict, step1: dict | None) -> tuple[dict, dict]:
    """({article id: outlet name}, {article id: step 1's headline, opening and words used})."""
    outlets = {x["id"]: x.get("outlet_name") or x.get("outlet") or x["id"] for x in sides.get("sources") or []}
    framing = {r["article"]: r.get("framing") for r in (step1 or {}).get("articles") or [] if r.get("framing")}
    return outlets, framing


def groups_for(sides: dict, articles: list[dict]) -> tuple[dict, list[dict]]:
    """What step 4 sees per side, {"A": {side_id, label, articles, claims, claims_total}, ...}, and the
    sides skipped for having no articles."""
    s = sides.get("sides") or {}
    groups, skipped = {}, []
    for g in "AB":
        if g not in s:
            continue
        arts = side_articles(sides, articles, s[g]["side_id"])
        if not arts:
            skipped.append(dict(side=s[g]["side_id"], label=s[g]["label"], reason="empty side"))
            continue
        only = sorted((c for c in sides.get("claims") or [] if c.get("sides") == [s[g]["side_id"]]),
                      key=lambda c: -(c.get("independent") or 1))
        groups[g] = dict(side_id=s[g]["side_id"], label=s[g]["label"], articles=arts,
                         claims=[c["claim"] for c in only[:MAX_CLAIMS]], claims_total=len(only))
    return groups, skipped


def frame_story(sides: dict, step1: dict, articles: list[dict], event: dict, complete, *, model: str = "",
                name: str = "brief_framing", prompt: str = VERSION) -> dict:
    """Step 4 for one story: step 3's output with "framing" added."""
    out = dict(sides)
    res = dict(version=prompt, kind=(sides.get("sides") or {}).get("kind"), sides=[], skipped=[], calls=0,
               retried_quotes=False, quotes_bad_first=0, quotes_dropped=0, points_dropped=0, error=None, call_errors=[])
    out["framing"] = res
    s = sides.get("sides") or {}
    if s.get("kind") != "two sides":
        res["skipped"].append(dict(reason="no real divide"))
        return out
    outlets, framing = outlets_and_framing(sides, step1)
    groups, skipped = groups_for(sides, articles)
    res["skipped"] += skipped
    if not groups:
        return out
    msgs, labels = messages_for(event, groups, framing, outlets, prompt)
    hays = {a["id"]: _hay(a, framing.get(a["id"])) for g in groups.values() for a in g["articles"]}
    keys = [f"side_{g.lower()}" for g in groups]
    params = dict(max_tokens=MAX_TOKENS[prompt], response_format=schema_for({g: [l for l in labels if l.startswith(g)] for g in groups}),
                  timeout=CALL_TIMEOUT_S)
    if model.startswith("gpt-oss"):
        params["reasoning_effort"] = "low"
    d, n, errs = _ask(complete, msgs, params, name, keys)
    res["calls"] += n
    res["call_errors"] += errs
    if d is None:
        res["error"] = "no usable answer after one retry" + (f" ({errs[-1]})" if errs else "")
        return out
    pts, bad = _check(d, groups, labels, hays)
    res["quotes_bad_first"] = len(bad)
    if bad:                                    # one retry naming the bad quotes; keep the better answer
        res["retried_quotes"] = True
        note = RETRY_QUOTES.format(bad="\n".join(f"- {lab or 'no article named'}: {w[:200]}" for lab, w in bad[:20]))
        again = msgs + [{"role": "assistant", "content": json.dumps(d, ensure_ascii=False)}, {"role": "user", "content": note}]
        d2, n2, errs2 = _ask(complete, again, params, f"{name} retry quotes", keys)
        res["calls"] += n2
        res["call_errors"] += errs2
        if d2 is not None:
            pts2, bad2 = _check(d2, groups, labels, hays)
            good = lambda P: sum(q["ok"] for ps in P.values() for p in ps for q in p["quotes"])
            if len(bad2) < len(bad) and good(pts2) >= good(pts):
                pts, bad = pts2, bad2
    for g, grp in groups.items():
        kept = []
        for p in pts.get(g) or []:
            ok = [q for q in p["quotes"] if q["ok"]]
            res["quotes_dropped"] += len(p["quotes"]) - len(ok)
            if not ok:
                res["points_dropped"] += 1
                continue
            arts = list(dict.fromkeys(q["article"] for q in ok))
            kept.append(dict(point=p["point"], kind=p["kind"], articles=arts, outlets=len({outlets.get(a) for a in arts}),
                             quotes=[dict(article=q["article"], outlet=outlets.get(q["article"]), words=q["words"],
                                          words_en=q["words_en"]) for q in ok]))
        res["sides"].append(dict(side_id=grp["side_id"], label=grp["label"], articles=len(grp["articles"]), points=kept))
    return out
