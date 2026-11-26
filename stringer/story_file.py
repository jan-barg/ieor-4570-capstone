"""Module 5: put the news brief's steps together into the Story File.

Each story folder gains two files (system map, Cross-cutting -> Storage):
  facts.jsonl      one row per step 1 fact card: id, article, fact (English), quote (the article's
                   language), quote_en, kind, who_says, pos (see FACTS_POS)
  story_file.json  event, sides, sources (no text), claims (pointing to fact ids), updates,
                   perspectives (how each side tells it), blindspots, flags, counts, meta

Two ways in:
  build_story(meta, articles, complete_for)   runs every step live: pick, step 1 read, step 2 merge,
                                              step 3 sides (code), 3b blindspot judge, step 4 framing
  assemble(meta, step1, step2, judged, framing, ...)   joins step outputs already made (the eval runs)

Rules:
- Claims point to fact ids; quotes live once, in facts.jsonl. A fact's `pos` is where its quote
  starts in the article's cleaned, normalized text (brief_read.shown_text, then brief_read.norm),
  which is where step 1 checked it; quote_at() reads it back with a sentence on each side, which is
  what the fact check needs.
- Every blindspot candidate (a claim only one side reports, against a side with 2+ read articles)
  gets a status: blindspot / reported / told differently / unclear / unchecked from the judge, or
  "not checked" (one independent source, or past the judge's 10 a side). Only "blindspot" claims are
  listed under blindspots[], split into central and detail.
- status and reason on each claim stay empty: the fact check (module 6) fills them.
- validate() checks that every id points somewhere; build_story and the script stop on a problem.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

from . import brief_blind, brief_framing, brief_merge, brief_read, brief_sides, models, pick

VERSION = "sf-1"
FACTS_POS = ("character offset of the quote (brief_read.norm, outer punctuation stripped) in "
             "brief_read.norm(brief_read.shown_text(article)[0])")
EVENT_FIELDS = ("id", "title", "summary", "category", "subtype", "severity", "confidence", "country",
                "location_name", "lat", "lng", "report_count", "start", "created_at", "url", "source_urls")
STEPS = ("brief_read", "brief_merge", "brief_blind", "brief_framing")      # the model steps, in order


# ---- inputs -----------------------------------------------------------------------------------------

def picked(meta: dict, articles: list[dict], n: int = 10) -> tuple[list[dict], dict]:
    """The pick of at most n articles (in pick order) and each one's group (A, B, wire, local, other)."""
    p = pick.pick(articles, meta["lens"], n=n)
    by = {a["id"]: a for a in articles}
    return [by[i] for i in p["picked"]], {r["id"]: r["group"] for r in p["rows"]}


def times_of(articles: list[dict]) -> dict:
    """Article id -> published time (the date alone when the time is unknown), for step 2's conflict check."""
    return {a["id"]: a["published_at"] if a.get("date_precision", "time") == "time" else a["published_at"][:10]
            for a in articles if a.get("id") and a.get("published_at")}


# ---- the parts --------------------------------------------------------------------------------------

def fact_rows(step1: dict) -> list[dict]:
    rows = []
    for r in (step1 or {}).get("articles") or []:
        for f in r.get("facts") or []:
            rows.append(dict(id=f["id"], article=r["article"], fact=f["fact"], quote=f["quote"],
                             quote_en=f.get("quote_en") or "", kind=f.get("kind"), who_says=f.get("who_says"),
                             pos=f.get("pos")))
    return rows


def event_of(meta: dict) -> dict:
    ev = meta.get("event") or {}
    return {k: ev.get(k) for k in EVENT_FIELDS if k in ev}


def _evidence(row: dict) -> dict | None:
    if row.get("status") in ("reported", "told differently") and row.get("quote"):
        return dict(article=row.get("article"), quote=row["quote"], quote_en=row.get("quote_en") or "")
    return None


def blind_status(judged: dict) -> dict:
    """{claim id: blindspot field} for every candidate step 3 listed."""
    rows = {}
    for j in judged.get("blindspot_checks") or []:
        for r in j["checked"]:
            rows[r["claim"]] = dict(silent_side=j["silent_side"], status=r["status"], matters=r.get("matters"),
                                    why=r.get("why") or "", evidence=_evidence(r))
    out = {}
    for b in judged.get("blindspots") or []:
        for cid in b["claims"]:
            if cid in rows:
                out[cid] = rows[cid]
            else:
                n = (b.get("sources") or {}).get(cid, 1)
                out[cid] = dict(silent_side=b["silent_side"], status="not checked", matters=None,
                                why=("one independent source" if n < brief_blind.MIN_SOURCES
                                     else f"past the judge's {brief_blind.MAX_CLAIMS} a side"), evidence=None)
    return out


def claim_rows(judged: dict) -> list[dict]:
    blind = blind_status(judged)
    out = []
    for c in judged.get("claims") or []:
        out.append(dict(id=c["id"], claim=c["claim"], kind=c.get("kind"), who_says=c.get("who_says"),
                        facts=list(c.get("facts") or [s["fact"] for s in c.get("sources") or []]),
                        articles=list(c.get("articles") or []), conflicts_with=list(c.get("conflicts_with") or []),
                        sides=list(c.get("sides") or []), neither=c.get("neither", 0),
                        independent=c.get("independent"), independent_groups=c.get("independent_groups") or [],
                        flags=list(c.get("flags") or []), blindspot=blind.get(c["id"]), status=None, reason=None))
    return out


# step 2 sometimes ends a claim with "according to the article", which names nobody (3 of 2,288 claims on
# the 26 test stories); code puts in the outlet the claim's articles come from and keeps step 2's words
_VAGUE = re.compile(r"according to the article('s headline)?", re.I)


def name_outlets(claims: list[dict], sources: list[dict]) -> int:
    """Swaps "according to the article" for the outlets behind the claim. Returns how many claims changed;
    each keeps its old wording in claim_step2."""
    names = {s["id"]: s.get("outlet_name") or s.get("outlet") for s in sources}
    n = 0
    for c in claims:
        outs = list(dict.fromkeys(names[a] for a in c["articles"] if names.get(a)))
        if not outs or not _VAGUE.search(c["claim"]):
            continue
        who = outs[0] if len(outs) == 1 else ", ".join(outs[:-1]) + " and " + outs[-1]
        c["claim_step2"] = c["claim"]
        c["claim"] = _VAGUE.sub(lambda m: f"according to {who}" + ("'s headline" if m.group(1) else ""), c["claim"])
        n += 1
    return n


def blindspot_rows(judged: dict, claims: list[dict]) -> list[dict]:
    """Per silent side: the confirmed blindspots (central first) and how many candidates there were."""
    out = []
    for b in judged.get("blindspots") or []:
        mine = [c for c in claims if (c["blindspot"] or {}).get("silent_side") == b["silent_side"]]
        conf = [c for c in mine if c["blindspot"]["status"] == "blindspot"]
        out.append(dict(silent_side=b["silent_side"], label=b.get("label"), reported_by=b.get("reported_by"),
                        central=[c["id"] for c in conf if c["blindspot"]["matters"] == "central"],
                        detail=[c["id"] for c in conf if c["blindspot"]["matters"] != "central"],
                        candidates=len(mine), checked=sum(c["blindspot"]["status"] != "not checked" for c in mine)))
    return out


def perspective_rows(framing: dict | None) -> tuple[list[dict], list[dict]]:
    f = framing or {}
    sides = [dict(side_id=s["side_id"], label=s["label"], articles=s["articles"],
                  points=[dict(kind=p["kind"], point=p["point"], outlets=p["outlets"], articles=p["articles"],
                               quotes=[dict(article=q["article"], outlet=q["outlet"], words=q["words"],
                                            words_en=q.get("words_en") or "") for q in p["quotes"]])
                          for p in s["points"]])
             for s in f.get("sides") or []]
    return sides, list(f.get("skipped") or [])


# ---- the whole file ---------------------------------------------------------------------------------

def assemble(meta: dict, step1: dict, step2: dict, judged: dict, framing: dict | None, *,
             steps: dict | None = None, cost_usd: dict | None = None, trace_id: str | None = None,
             now: str | None = None) -> tuple[list[dict], dict]:
    """(facts rows, Story File) from the step outputs. judged = brief_blind.judge_blindspots's output
    (step 3's output plus the judge); framing = brief_framing.frame_story's "framing" part."""
    facts = fact_rows(step1)
    claims = claim_rows(judged)
    named = name_outlets(claims, judged.get("sources") or [])
    persp, skipped = perspective_rows(framing)
    blind = blindspot_rows(judged, claims)
    cost = dict(cost_usd or {})
    known = [v for v in cost.values() if v is not None]
    bc, fr = judged.get("blind_counts") or {}, framing or {}
    counts = dict(judged.get("counts") or {}, facts=len(facts),
                  blindspots_central=sum(len(b["central"]) for b in blind),
                  blindspots_detail=sum(len(b["detail"]) for b in blind),
                  blindspot_candidates_checked=bc.get("checked", 0),
                  perspective_points=sum(len(s["points"]) for s in persp),
                  conflicts=sum(bool(c["conflicts_with"]) for c in claims),
                  updates=len(step2.get("updates") or []), outlet_named=named)
    sf = dict(
        version=VERSION,
        event=event_of(meta),
        attribution=meta.get("attribution"),
        sides=judged.get("sides"),
        sources=judged.get("sources") or [],
        claims=claims,
        updates=list(step2.get("updates") or []),
        perspectives=persp,
        perspectives_skipped=skipped,
        blindspots=blind,
        flags=judged.get("flags") or [],
        counts=counts,
        meta=dict(created_at=now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                  event_created_at=(meta.get("event") or {}).get("created_at"),
                  event_report_count=(meta.get("event") or {}).get("report_count"),
                  gathered_at=meta.get("gathered_at"), gather_version=meta.get("gather_version"),
                  steps=steps or {}, sides_version=judged.get("version"), pick_version=getattr(pick, "VERSION", None),
                  facts_pos=FACTS_POS, langfuse_trace_id=trace_id or meta.get("langfuse_trace_id"),
                  cost_usd=dict(cost, total=round(sum(known), 6) if known and len(known) == len(cost) else None),
                  errors=_errors(step1, step2, judged, framing)))
    return facts, sf


def _errors(step1, step2, judged, framing) -> list[str]:
    out = [f"step 1: {r['article']}: {r['checks']['error']}" for r in (step1 or {}).get("articles") or []
           if (r.get("checks") or {}).get("error")]
    if ((step2 or {}).get("checks") or {}).get("error"):
        out.append(f"step 2: {step2['checks']['error']}")
    out += [f"step 3b: {j['silent_side']}: {j['error']}" for j in judged.get("blindspot_checks") or [] if j.get("error")]
    if (framing or {}).get("error"):
        out.append(f"step 4: {framing['error']}")
    return out


def validate(sf: dict, facts: list[dict]) -> list[str]:
    """Every id points somewhere real. An empty list means the Story File holds together."""
    bad = []
    src = {s["id"]: s for s in sf.get("sources") or []}
    fid = {f["id"]: f for f in facts}
    cid = {c["id"]: c for c in sf.get("claims") or []}
    if len(fid) != len(facts):
        bad.append("fact ids repeat")
    for f in facts:
        if f["article"] not in src:
            bad.append(f"fact {f['id']}: article {f['article']} not in sources")
        elif not src[f["article"]].get("read"):
            bad.append(f"fact {f['id']}: article {f['article']} not marked read")
    for c in cid.values():
        for x in c["facts"]:
            if x not in fid:
                bad.append(f"claim {c['id']}: fact {x} missing")
            elif fid[x]["article"] not in c["articles"]:
                bad.append(f"claim {c['id']}: fact {x}'s article not in its articles")
        if not c["facts"]:
            bad.append(f"claim {c['id']}: no facts")
        bad += [f"claim {c['id']}: conflicts with unknown {x}" for x in c["conflicts_with"] if x not in cid]
        bad += [f"claim {c['id']}: article {a} not in sources" for a in c["articles"] if a not in src]
    for b in sf.get("blindspots") or []:
        for x in b["central"] + b["detail"]:
            if x not in cid or (cid[x]["blindspot"] or {}).get("status") != "blindspot":
                bad.append(f"blindspot {x} ({b['silent_side']}): not a confirmed blindspot claim")
    for p in sf.get("perspectives") or []:
        for pt in p["points"]:
            if not pt["quotes"]:
                bad.append(f"perspective {p['side_id']}: a point with no quote")
            for q in pt["quotes"]:
                if q["article"] not in src:
                    bad.append(f"perspective {p['side_id']}: article {q['article']} not in sources")
                elif src[q["article"]].get("side") != p["side_id"]:
                    bad.append(f"perspective {p['side_id']}: quote from {q['article']}, not on this side")
    for u in sf.get("updates") or []:
        bad += [f"update: unknown claim {x}" for x in (u.get("a"), u.get("b")) if x not in cid]
    return bad


# ---- reading a quote back ---------------------------------------------------------------------------

_SENT = re.compile(r"(?:(?<=[.!?。！？])|(?<=[.!?。！？][\"'”’»)]))\s+(?:#{1,6}\s+)?|\s#{1,6}\s+|\n+")   # also after ." and at a heading


def quote_at(article: dict, fact: dict, sentences: int = 1) -> dict | None:
    """The fact's quote read back from its article at `pos`, with `sentences` sentences on each side.
    None when the position doesn't hold the quote (the article changed, or a bad position)."""
    pos = fact.get("pos")
    if pos is None or pos < 0:
        return None
    text = brief_read.norm(brief_read.shown_text(article)[0])
    q = brief_read.norm(fact["quote"]).strip(" .,;:\"'")
    if not q or text[pos:pos + len(q)] != q:
        return None
    spans, start = [], 0
    for m in _SENT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans = [(a, b) for a, b in spans + [(start, len(text))] if text[a:b].strip()]
    i = next(k for k, (a, b) in enumerate(spans) if b > pos)                 # the sentence the quote starts in
    j = next(k for k, (a, b) in enumerate(spans) if b >= pos + len(q))       # and the one it ends in
    part = lambda s: " ".join(text[a:b] for a, b in s)
    return dict(quote=q, sentence=text[spans[i][0]:spans[j][1]],
                before=part(spans[max(0, i - sentences):i]), after=part(spans[j + 1:j + 1 + sentences]))


# ---- running it all ---------------------------------------------------------------------------------

class Spend:
    """Adds up what each step's calls cost and stops before a call once the cap is passed."""

    def __init__(self, cap_usd: float | None = None):
        self.cap, self.by_step = cap_usd, {}

    def total(self) -> float:
        return round(sum(self.by_step.values()), 6)

    def wrap(self, step: str, complete):
        self.by_step.setdefault(step, 0.0)

        def call(messages, name=None, **params):
            if self.cap is not None and self.total() >= self.cap:
                raise RuntimeError(f"spend cap ${self.cap} reached")
            r = complete(messages, name=name, **params)
            self.by_step[step] += float(((getattr(r, "cost", None) or {}).get("total")) or 0.0)
            return r
        return call


def live_complete(step: str, trace_id: str | None = None):
    """The model call for a step: the model config/models.toml names, logged to Langfuse."""
    alias = models.model_for(step)
    return alias, (lambda messages, name=None, **p: models.complete(step, messages, model=alias, trace_id=trace_id,
                                                                    name=name or step, **p))


def build_story(meta: dict, articles: list[dict], complete_for=None, *, n: int = 10, cap_usd: float | None = None,
                trace_id: str | None = None) -> tuple[list[dict], dict]:
    """Every step live for one story. complete_for(step) -> (model alias, complete function);
    the default calls the models in config/models.toml."""
    complete_for = complete_for or (lambda step: live_complete(step, trace_id))
    spend = Spend(cap_usd)
    event = meta["event"]
    arts, groups = picked(meta, articles, n)
    used = {}

    def step_fn(step):
        alias, fn = complete_for(step)
        used[step] = alias
        return alias, spend.wrap(step, fn)

    alias, fn = step_fn("brief_read")
    step1 = brief_read.read_story(event, arts, fn, model=alias)
    alias, fn = step_fn("brief_merge")
    step2 = brief_merge.merge_story(event, step1, fn, model=alias, times=times_of(arts))
    sides = brief_sides.add_sides(step2, step1, arts, groups, meta["lens"], event)
    alias, fn = step_fn("brief_blind")
    judged = brief_blind.judge_blindspots(sides, arts, event, fn, model=alias)
    alias, fn = step_fn("brief_framing")
    framing = brief_framing.frame_story(sides, step1, arts, event, fn, model=alias)["framing"]
    versions = dict(brief_read=brief_read.VERSION, brief_merge=brief_merge.VERSION, brief_sides=brief_sides.VERSION,
                    brief_blind=brief_blind.VERSION, brief_framing=brief_framing.VERSION)
    steps = {s: dict(version=versions[s], model=used.get(s, "code")) for s in versions}
    facts, sf = assemble(meta, step1, step2, judged, framing, steps=steps,
                         cost_usd={s: round(v, 6) for s, v in spend.by_step.items()}, trace_id=trace_id)
    return facts, sf


# ---- files ------------------------------------------------------------------------------------------

def _atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write(story_dir: Path, facts: list[dict], sf: dict) -> None:
    story_dir = Path(story_dir)
    _atomic(story_dir / "facts.jsonl", "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts))
    _atomic(story_dir / "story_file.json", json.dumps(sf, ensure_ascii=False, indent=1))


def read(story_dir: Path) -> tuple[list[dict], dict]:
    story_dir = Path(story_dir)
    facts = [json.loads(x) for x in (story_dir / "facts.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
    return facts, json.loads((story_dir / "story_file.json").read_text(encoding="utf-8"))
