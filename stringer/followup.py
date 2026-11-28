"""The follow-up check: is this event another step of a story that already has a video? (Jan, Nov 27.)

It runs at the click, inside the video job, beside the sides step, so nobody waits for it. Module 2's model
(same_story.compare_events, prompt p2) compares the event with recent videos' events:

    candidates  finished videos still shown, made in the last 7 days, wherever their event happened. Newest
                first, at most 70 (the Gate allows 10 videos a day). No candidates: no call. There is no place
                filter (Jan, Nov 27): on real related events from the saved feed log, "same country or region"
                kept Singapore's probe of a firm the US had blacklisted away from the model, which joins the two
                when it sees them. At most 10 videos a day keeps the list short, and the model rarely joins.
    the call    batches of 25, side by side (about $0.002 a click with a full week of videos). Each
                candidate gets "same" (the same event reported twice), "follow_up" (a separate step that
                grows out of this event, or leads into it) or "different".
    the chain   every "same" or "follow_up" match joins one story chain with this event (Gate.join_chain).
                The front page shows a chain's videos side by side, oldest on the left.

Grouping only: the video itself is made exactly as before (Jan, Nov 27). A failure here never stops the
video; the event just stands alone.

Example (made up): a video exists for "Dam bursts, flooding three valley towns", made Saturday. On Monday
someone clicks "Inquiry into the dam collapse opens". Saturday's video is a candidate, with the week's
others. The model says "follow_up", so both join chain <Saturday's event id>, and Monday's video sits to the
right of Saturday's. If Monday's had been clicked first, Saturday's click would find Monday's video and join it the
same way: the check goes both ways."""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor

from . import same_story
from .events import from_live, parse_ts
from .gate.core import safe_id

WINDOW_DAYS = 7
MAX_CANDIDATES = 70      # 7 days x the Gate's 10 videos a day
BATCH = 25               # candidates per model call; the batches run side by side
JOINS = ("same", "follow_up")


def as_event(raw: dict) -> dict:
    """The fields compare_events reads, from a raw feed event."""
    ev = from_live(raw)
    return {"id": str(raw.get("id") or ""), "title": ev.title, "summary": ev.summary,
            "start": ev.start.isoformat() if ev.start else str(raw.get("created_at") or ""),
            "location_name": ev.location_name, "country": str(raw.get("country") or ""),
            "region": str(raw.get("region") or "")}


def candidates(raw: dict, store, now: dt.datetime | None = None, *, window_days: int = WINDOW_DAYS,
               most: int = MAX_CANDIDATES) -> list[dict]:
    """Recent shown videos' events, newest video first, as compare_events wants them."""
    now = now or dt.datetime.now(dt.timezone.utc)
    me = safe_id(str(raw.get("id") or ""))
    keys = store.list("events/")
    with ThreadPoolExecutor(max_workers=8) as ex:
        recs = [r for r in ex.map(lambda k: store.get(k)[0], keys) if r]
    since = now - dt.timedelta(days=window_days)
    done = []
    for r in recs:
        made = parse_ts(((r.get("video") or {}).get("made_at")))
        rid = safe_id(str(r.get("id") or ""))
        if (r.get("state") == "done" and r.get("video") and not r.get("hidden") and rid and rid != me
                and made is not None and since <= made <= now):
            done.append((made, rid))
    done.sort(reverse=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        raws = list(ex.map(lambda p: store.get(f"raw_events/{p[1]}.json")[0], done[:most]))
    return [as_event(r) for r in raws if r]


def check(raw: dict, gate, complete, now: dt.datetime | None = None) -> dict:
    """Run the check and join the chain. Returns what to keep in pipeline.json:
    {"candidates", "matches": [{"id", "title", "verdict", "reason"}], "chain", "problems", "seconds"}."""
    t0 = time.time()
    cands = candidates(raw, gate.store, now)
    out = dict(candidates=len(cands), matches=[], chain=None, problems=[])
    if cands:
        me = as_event(raw)
        chunks = [cands[i:i + BATCH] for i in range(0, len(cands), BATCH)]
        with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
            answers = list(ex.map(lambda ch: same_story.compare_events(me, ch, complete), chunks))
        verdicts = {}
        for res in answers:
            verdicts.update(res["verdicts"])
            out["problems"] += res.get("problems") or []
        for c in cands:
            v = verdicts.get(c["id"]) or {}
            if v.get("verdict") in JOINS:
                out["matches"].append(dict(id=c["id"], title=c["title"], verdict=v["verdict"],
                                           reason=v.get("reason") or "", start=c["start"]))
        out["matches"].sort(key=lambda m: m["start"])          # oldest first: the chain keeps the oldest's id
        if out["matches"]:
            out["chain"] = gate.join_chain(str(raw.get("id") or ""), [m["id"] for m in out["matches"]])
    out["seconds"] = round(time.time() - t0, 2)
    return out
