"""Module 2: the same-story filter ("off-topic filter"). Keeps only the articles about this event.

For every article Gather found, a model says one of three things, with a short reason:
    same        it reports this event (the same attack, vote, ruling or announcement, including
                updates, reactions and analysis of it)
    follow_up   a separate step that grows directly out of this event (or leads into it)
    different   another event, even in the same war, country or topic
pick.py then drops "different" and keeps the rest. The same model call also compares two events,
which the front page will use to group follow-up events into video chains (compare_events).

Example (made up): the event is "Dam bursts, flooding three valley towns" on Saturday.
"Floodwater reaches third town as death toll rises" -> same. "Inquiry into the dam opens" two
weeks later -> follow_up. "Another dam inspected in a different region" -> different.

The prompt has versions (PROMPTS; VERSION is the one in use), so an old eval run can be repeated.

What the model sees, per article (map, Cross-cutting: each agent gets a packet built by code):
the headline, when it was published compared with the event's start ("3.7 hours after the event
started"), and the first ~600 characters. No outlet names: they're cut from headlines and text,
so the verdict rests on the facts, not on who wrote it. Articles go in batches (BATCH per call),
the instructions and the event first, so the shared part can be cached.

Code around the model:
  - the event's own cited sources are "same" by rule (Monitor the Situation cited them);
  - rows with no headline and no text get no verdict ("nothing to judge");
  - every article must come back with a valid verdict: broken JSON is read item by item, and
    missing ones are asked again once, with a note saying why;
  - the side-drop check: on a two-sided story, flag it when one side loses far more of its
    articles to "different" than the other (the filter shouldn't quietly unbalance a story)."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime

from .events import parse_ts
from .models import cache_block, text_block

VERSION = "p2"           # the prompt in use; PROMPTS keeps the older ones so old runs can be repeated
VERDICTS = ("same", "follow_up", "different")
BATCH = 25
OPENING_CHARS = 600
MAX_TOKENS = 8000            # per batch call; thinking models count their thinking here too
SIDE_DROP_GAP = 0.30         # flag when one side's drop share is this much above the other's
SIDE_MIN = 4                 # ...and both sides had at least this many judged articles

_P1 = """You decide whether news items are about one specific news event.

You get the event (its title, a summary, when it started and where) and a numbered list of items. Usually the items are news articles: each has an id, its headline, when it was published compared with the event's start, and its opening text. Outlet names have been removed on purpose: judge only by the facts the item reports, not by its tone or who published it.

Give each item one verdict:
- "same": it reports this event. The same incident, attack, vote, ruling, decision or announcement, including first reports, updated tolls and details, reactions to it, and analysis of it.
- "follow_up": it belongs to the same chain of events, but is mainly about an earlier or a later step, not this one. For example: the event is a shooting, and the item is about the gunman dying in hospital two days later, or a national day of mourning; the event is the vote count, and the item is about the exit polls the night before.
- "different": it is about another event, even if it is the same war, country, people or topic. For example: another missile strike in the same war on another day; a different election; a roundup or newsletter that only mentions this event among many others; a general explainer not tied to this event.

Rules:
- An item that mainly reports this event but also mentions later developments is "same".
- Items can be in any language. Judge them the same way.
- When the opening text is missing, judge from the headline and the date.
- Publication time helps: an item published long before the event started cannot report it, but it may be an earlier step of the same story.
- The reason is at most 15 words and names the fact that decided it.

When the items are other events instead of articles, judge each the same way: "same" means it is the same event reported twice; "follow_up" means an earlier or later step of the same story; "different" means a separate event.

Answer with JSON only, one entry per item, in the same order:
{"verdicts": [{"id": "A1", "verdict": "same", "reason": "..."}]}"""

# p2 (2026-11-24): the stages of one process within about a day are "same" (p1's own example called exit
# polls a follow-up of the count, against the answer key), and "follow_up" no longer covers other incidents
# of the same war or chain, which are "different" (they were being kept).
_P2 = """You decide whether news items are about one specific news event.

You get the event (its title, a summary, when it started and where) and a numbered list of items. Usually the items are news articles: each has an id, its headline, when it was published compared with the event's start, and its opening text. Outlet names have been removed on purpose: judge only by the facts the item reports, not by its tone or who published it.

Give each item one verdict:
- "same": it reports this event. The same incident, attack, vote, ruling, decision or announcement, including first reports, updated tolls and details, reactions to it, and analysis of it. The stages of one process that unfold within a day or so are one event: an election's voting, exit polls, count and result; an attack, its rising death toll and the naming of the attacker.
- "follow_up": it is mainly about a separate step that grows directly out of this event, or leads directly into it, and is news in its own right. For example: the event is a shooting, and the item is about the gunman dying in hospital two days later, or a national day of mourning for the victims; the event is an election, and the item is about coalition talks or a government formed weeks later.
- "different": it is about another event, even if it is the same war, country, people or topic. For example: another missile strike or attack wave in the same war, even a day apart; a threat, warning or retaliation over something else; a different election; a roundup or newsletter that only mentions this event among many others; a general explainer not tied to this event.

Rules:
- An item that mainly reports this event but also mentions later developments is "same".
- Being part of the same war, campaign or chain of events is not enough for "follow_up": the item must be about a step of this event itself. Otherwise it is "different".
- Items can be in any language. Judge them the same way.
- When the opening text is missing, judge from the headline and the date.
- Publication time helps: an item published long before the event started cannot report it, but it may be an earlier step of the same story.
- The reason is at most 15 words and names the fact that decided it.

When the items are other events instead of articles, judge each the same way: "same" means it is the same event reported twice, or another stage of the same process within a day or so (exit polls and the count of one election); "follow_up" means a separate earlier or later step that grows directly out of this event; "different" means a separate event.

Answer with JSON only, one entry per item, in the same order:
{"verdicts": [{"id": "A1", "verdict": "same", "reason": "..."}]}"""

PROMPTS = {"p1": _P1, "p2": _P2}
INSTRUCTIONS = PROMPTS[VERSION]

_ALIASES = {"same": "same", "same story": "same", "same_story": "same", "same event": "same",
            "follow_up": "follow_up", "follow-up": "follow_up", "follow up": "follow_up", "followup": "follow_up",
            "related": "follow_up", "different": "different", "off-topic": "different", "off topic": "different",
            "unrelated": "different", "different event": "different"}
_SALVAGE = re.compile(r'"id"\s*:\s*"([^"]+)"\s*,\s*"verdict"\s*:\s*"([^"]+)"'
                      r'(?:\s*,\s*"reason"\s*:\s*"((?:[^"\\]|\\.)*)")?')
_SEP = re.compile(r"\s+[-|–—]\s+(?=[^-|–—]*$)")
_WORD = re.compile(r"\w+", re.UNICODE)


# ---- the packet -------------------------------------------------------------------------------

def _names(a: dict) -> list[str]:
    L = a.get("labels") or {}
    out = {a.get("outlet_name"), L.get("outlet_name"), L.get("allsides_name")}
    return sorted((n for n in out if n and len(n) >= 3), key=len, reverse=True)


def strip_outlet(title: str, names: list[str]) -> str:
    """Drop a trailing ' - Outlet Name' / ' | Outlet' and any other mention of the outlet."""
    t = (title or "").strip()
    m = _SEP.search(t)
    if m:
        tail = t[m.end():].strip().lower()
        tail_words = set(_WORD.findall(tail))
        for n in names:
            nw = {w for w in _WORD.findall(n.lower()) if len(w) >= 3 and w != "the"}
            if n.lower() in tail or (nw and nw & tail_words) or len(tail_words) <= 2 and tail.endswith((".com", ".org")):
                t = t[:m.start()].strip()
                break
    return mask_names(t, names)


def mask_names(text: str, names: list[str]) -> str:
    for n in names:
        text = re.sub(re.escape(n), "[outlet]", text, flags=re.IGNORECASE)
    return text


def opening(text: str | None, n: int = OPENING_CHARS) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    return cut[:cut.rfind(" ")] + " …" if " " in cut else cut


def when(published_at: str | None, precision: str | None, start: datetime, what="published",
         ref="the event started") -> str:
    t = parse_ts(published_at)
    if t is None:
        return f"{what}: date unknown"
    h = (t - start).total_seconds() / 3600
    if precision == "day":
        days = (t.date() - start.date()).days
        if days == 0:
            return f"{what} the same day {ref}, time unknown"
        return f"{what} {abs(days)} day{'s' if abs(days) != 1 else ''} {'after' if days > 0 else 'before'} {ref}, time unknown"
    a = abs(h)
    span = f"{a:.1f} hours" if a < 48 else f"{a / 24:.1f} days"
    return f"{what} {span} {'after' if h >= 0 else 'before'} {ref}"


def event_text(e: dict) -> str:
    start = parse_ts(e["start"])
    lines = [f"Title: {e['title']}", f"Summary: {e.get('summary') or ''}",
             f"Started: {start:%a %Y-%m-%d %H:%M} UTC" if start else "Started: unknown"]
    if e.get("location_name"):
        lines.append(f"Place: {e['location_name']}")
    return "THE EVENT\n" + "\n".join(lines)


def article_packet(a: dict, start: datetime, pid: str) -> dict:
    names = _names(a)
    return {"id": pid, "headline": strip_outlet(a.get("title") or "", names) or "(no headline)",
            "when": when(a.get("published_at"), a.get("date_precision"), start),
            "opening": mask_names(opening(a.get("text")), names) or "(no text)"}


def event_packet(other: dict, start: datetime, pid: str) -> dict:
    return {"id": pid, "headline": other["title"],
            "when": when(other["start"], "time", start, what="started", ref="the first event started"),
            "opening": opening(other.get("summary"), 900) or "(no summary)"}


RETRY_NOTE = ("These items are being sent again because the last answer for them was missing or could not "
              "be read. Give a verdict for every item. Every object needs all three keys: id, verdict, reason. ")


def messages_for(event: dict, packets: list[dict], kind: str = "articles", retry: bool = False,
                 prompt: str | None = None) -> list[dict]:
    items = "\n".join(json.dumps(p, ensure_ascii=False) for p in packets)
    head = "THE ITEMS (news articles)" if kind == "articles" else "THE ITEMS (other events)"
    note = RETRY_NOTE if retry else ""
    return [{"role": "user", "content": [
        cache_block(PROMPTS[prompt or VERSION] + "\n\n" + event_text(event)),
        text_block(f"\n\n{head}, one JSON object per line:\n{items}\n\n{note}Answer with the JSON only.")]}]


# ---- reading the answer -----------------------------------------------------------------------

def parse_verdicts(text: str, ids: list[str]) -> tuple[dict, list[str]]:
    """{packet id: {"verdict", "reason"}} for the ids that came back valid, and what went wrong."""
    problems = []
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    data = None
    for cand in (t, t[t.find("{"):t.rfind("}") + 1] if "{" in t else "", t[t.find("["):t.rfind("]") + 1] if "[" in t else ""):
        if not cand:
            continue
        try:
            data = json.loads(cand)
            break
        except json.JSONDecodeError:
            continue
    if data is None:
        # broken JSON (e.g. one object missing a key): read the verdicts object by object instead
        rows = [{"id": m.group(1), "verdict": m.group(2), "reason": m.group(3) or ""} for m in _SALVAGE.finditer(t)]
        if not rows:
            return {}, ["answer is not JSON"]
        problems.append(f"answer is not valid JSON; read {len(rows)} verdicts from it one by one")
        data = {"verdicts": rows}
    rows = data.get("verdicts") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}, ["no verdicts list"]
    want, out = set(ids), {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("id", "")).strip()
        v = _ALIASES.get(str(r.get("verdict", "")).strip().lower())
        if pid not in want:
            problems.append(f"unknown id {pid!r}")
            continue
        if v is None:
            problems.append(f"{pid}: bad verdict {r.get('verdict')!r}")
            continue
        out[pid] = {"verdict": v, "reason": str(r.get("reason") or "")[:200]}
    missing = [i for i in ids if i not in out]
    if missing:
        problems.append(f"{len(missing)} missing")
    return out, problems


# ---- one story --------------------------------------------------------------------------------

def to_judge(articles: list[dict]) -> tuple[list[dict], dict]:
    """Split the pool: the articles the model judges, and verdicts set by rule."""
    judged, ruled = [], {}
    for a in sorted(articles, key=lambda x: (x.get("published_at") or "", x["id"])):
        if a.get("own_source"):
            ruled[a["id"]] = {"verdict": "same", "reason": "the event cites it", "by": "rule"}
        elif not (a.get("title") or "").strip() and not (a.get("text") or "").strip():
            ruled[a["id"]] = {"verdict": None, "reason": "nothing to judge", "by": "rule"}
        else:
            judged.append(a)
    return judged, ruled


def plan_story(event: dict, articles: list[dict], batch: int = BATCH, prompt: str | None = None) -> list[dict]:
    """The first-pass calls for a story: [{"messages", "ids": {packet id: article id}, ...}]."""
    start = parse_ts(event["start"])
    judged, _ = to_judge(articles)
    calls = []
    for b in range(0, len(judged), batch):
        chunk = judged[b:b + batch]
        ids = {f"A{i + 1}": a["id"] for i, a in enumerate(chunk)}
        packets = [article_packet(a, start, pid) for pid, a in zip(ids, chunk)]
        calls.append({"messages": messages_for(event, packets, prompt=prompt), "ids": ids, "packets": packets,
                      "params": {"max_tokens": MAX_TOKENS}, "expect_output": 35 * len(chunk) + 30})
    return calls


def _judge(event, packets, ids, complete, kind, name, prompt=None):
    """One call plus one retry for whatever didn't come back. Returns {packet id: verdict}, problems."""
    r = complete(messages_for(event, packets, kind, prompt=prompt), name=name, max_tokens=MAX_TOKENS)
    got, problems = parse_verdicts(r.text, list(ids))
    missing = [p for p in packets if p["id"] not in got]
    if missing:
        r2 = complete(messages_for(event, missing, kind, retry=True, prompt=prompt), name=f"{name} retry",
                      max_tokens=MAX_TOKENS)
        again, p2 = parse_verdicts(r2.text, [p["id"] for p in missing])
        got.update(again)
        problems += [f"retry: {p}" for p in p2]
    return got, problems


def filter_story(event: dict, articles: list[dict], complete, *, lens: dict | None = None,
                 batch: int = BATCH, prompt: str | None = None) -> dict:
    """Verdicts for every article in one story's pool.

    `complete(messages, name=..., max_tokens=...)` makes one model call and returns an object with
    `.text` (models.complete with the step bound, or an eval runner's ctx.complete)."""
    judged, verdicts = to_judge(articles)
    problems = []
    for c in plan_story(event, articles, batch, prompt):
        got, probs = _judge(event, c["packets"], c["ids"], complete, "articles", "same_story", prompt)
        problems += probs
        for pid, aid in c["ids"].items():
            v = got.get(pid)
            verdicts[aid] = dict(v, by="model") if v else {"verdict": None, "reason": "no verdict from the model",
                                                         "by": "model"}
    return dict(version=prompt or VERSION, verdicts=verdicts, **checks(articles, verdicts, lens), problems=problems[:20])


def checks(articles: list[dict], verdicts: dict, lens: dict | None) -> dict:
    """The code checks on one story's verdicts: counts, articles with no verdict, side drops."""
    counts = Counter(str(verdicts.get(a["id"], {}).get("verdict")) for a in articles)
    missing = [a["id"] for a in articles if verdicts.get(a["id"], {}).get("by") == "model"
               and verdicts[a["id"]]["verdict"] is None]
    flags = []
    if missing:
        flags.append(f"{len(missing)} articles got no verdict")
    sides = {}
    for s in ((lens or {}).get("sides") or [])[:2]:
        mine = [a for a in articles if a.get("outlet") in set(s["outlet_ids"])
                and verdicts.get(a["id"], {}).get("by") == "model" and verdicts[a["id"]]["verdict"]]
        dropped = sum(verdicts[a["id"]]["verdict"] == "different" for a in mine)
        sides[s["side_id"]] = {"judged": len(mine), "different": dropped,
                               "share": round(dropped / len(mine), 3) if mine else None}
    if len(sides) == 2:
        (na, a), (nb, b) = sides.items()
        if a["judged"] >= SIDE_MIN and b["judged"] >= SIDE_MIN and abs(a["share"] - b["share"]) >= SIDE_DROP_GAP:
            hi, lo = (na, nb) if a["share"] > b["share"] else (nb, na)
            flags.append(f"side drop: {hi} lost {sides[hi]['different']} of {sides[hi]['judged']} to 'different', "
                         f"{lo} lost {sides[lo]['different']} of {sides[lo]['judged']}")
    return dict(counts=dict(counts), no_verdict=missing, sides=sides, flags=flags)


# ---- event against event (front page grouping) -----------------------------------------------

def compare_events(event: dict, others: list[dict], complete, prompt: str | None = None) -> dict:
    """Verdicts for other events against `event`: {other id: {"verdict", "reason"}}."""
    start = parse_ts(event["start"])
    ids = {f"E{i + 1}": o["id"] for i, o in enumerate(others)}
    packets = [event_packet(o, start, pid) for pid, o in zip(ids, others)]
    got, problems = _judge(event, packets, ids, complete, "events", "same_story events", prompt)
    out = {oid: (dict(got[pid], by="model") if pid in got else {"verdict": None, "reason": "no verdict", "by": "model"})
           for pid, oid in ids.items()}
    return dict(version=prompt or VERSION, verdicts=out, problems=problems)


# ---- the plain-code baseline: shared words, no model ----------------------------------------

STOP = set("the a an and or of in on at to for from by with as is are was were be been after before over "
           "into its it this that his her their says said say new first than more most up out".split())
KEYWORD_MIN = 0.25


def _content_words(s: str) -> set[str]:
    return {w for w in _WORD.findall((s or "").lower()) if len(w) >= 3 and w not in STOP and not w.isdigit()}


def keyword_story(event: dict, articles: list[dict], lens: dict | None = None, threshold: float = KEYWORD_MIN) -> dict:
    """Baseline: "same" when enough of the event title's words appear in the headline and opening,
    else "different". Never says follow_up. Shows how much a model adds."""
    ev = _content_words(event["title"])
    judged, verdicts = to_judge(articles)
    for a in judged:
        words = _content_words((a.get("title") or "") + " " + opening(a.get("text")))
        share = len(ev & words) / max(len(ev), 1)
        verdicts[a["id"]] = {"verdict": "same" if share >= threshold else "different",
                             "reason": f"{share:.0%} of the title's words", "by": "model"}
    return dict(version=f"keywords-{threshold}", verdicts=verdicts, **checks(articles, verdicts, lens), problems=[])


def keyword_events(event: dict, others: list[dict], threshold: float = KEYWORD_MIN) -> dict:
    ev = _content_words(event["title"])
    out = {}
    for o in others:
        share = len(ev & _content_words(o["title"] + " " + (o.get("summary") or ""))) / max(len(ev), 1)
        out[o["id"]] = {"verdict": "same" if share >= threshold else "different", "reason": f"{share:.0%}", "by": "model"}
    return dict(version=f"keywords-{threshold}", verdicts=out, problems=[])
