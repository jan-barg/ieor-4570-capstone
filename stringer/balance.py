"""When a side comes up short: one follow-up round before the pick (module 4, decided Nov 26, Jan,
design page "Choosing a story's sides", question 4).

Why: on the 40 frozen stories, 13 sides ended with 0 or 1 usable articles, and for 8 of them the
side's search had found on-topic articles whose page text never came back (snippets only), so the
pick couldn't use them. A new search doesn't fix that; reading the page does.

The round, only for a side with fewer than MIN_USABLE usable articles (distinct outlets), after the
same-story filter has run:
  1. read   Read the pages already found for that side that the same-story filter kept (same story
            or follow-up) but that have no full text (Tavily Extract, about 1 credit per 5 pages).
  2. search If the side is still short, one more search over that side's outlets with a different
            query: the English title if the side's first search was in another language, else the
            reworded query. One attempt, no retries. New articles go through the same-story filter.
  3. flag   Whatever is still short stays flagged by the pick, as before.

At most one round per story. Nothing here changes which side an article is on: that still comes
from its outlet."""
from __future__ import annotations

import datetime as dt
import math

from . import pick, same_story
from .events import Event, from_dict
from .gather import merge, plan
from .gather.sides import Side, split_by_mode
from .outlets import OutletTable

VERSION = "followup-1"
MIN_USABLE = 2
READ_MAX = 10           # pages read per side
SEARCH_MAX = 10
KEEP = ("same", "follow_up")


def usable_outlets(articles: list[dict], side: dict) -> set[str]:
    ids = set(side["outlet_ids"])
    return {a["outlet"] for a in articles if a.get("outlet") in ids and pick.usable(a)}


def readable(a: dict, side: dict) -> bool:
    """On this side, kept by the same-story filter, and usable but for its missing text."""
    L = a.get("labels") or {}
    return (a.get("outlet") in set(side["outlet_ids"]) and a.get("text_status") != "full"
            and a.get("verdict") in KEEP and a.get("role") in pick.ROLES
            and L.get("kind") in ("news", "wire") and L.get("section") != "opinion" and bool(a.get("url")))


def short_sides(lens: dict, articles: list[dict], min_usable: int = MIN_USABLE) -> list[dict]:
    out = []
    for s in (lens.get("sides") or [])[:2]:
        have = usable_outlets(articles, s)
        if len(have) >= min_usable:
            continue
        rows = sorted((a for a in articles if readable(a, s) and a["outlet"] not in have), key=pick.rank_key)
        seen, todo = set(), []
        for a in rows:                      # one page per outlet is enough to count it
            if a["outlet"] not in seen:
                seen.add(a["outlet"])
                todo.append(a)
        out.append(dict(side=s, usable=len(have), to_read=todo[:READ_MAX]))
    return out


def second_query(qs: dict, side_id: str) -> str:
    title = (qs.get("core") or "").strip()
    first = (qs.get("sides") or {}).get(side_id, "").strip()
    if first and first.lower() != title.lower():
        return title
    return (qs.get("reworded") or title).strip()


def estimate(lens: dict, articles: list[dict], t: OutletTable) -> dict:
    """Credits, worst case: every short side reads its pages and also searches again."""
    t_read = t_search = 0
    sides = []
    for s in short_sides(lens, articles):
        r = math.ceil(len(s["to_read"]) / 5) if s["to_read"] else 0
        side = s["side"]
        n_modes = len(split_by_mode(t, Side(side["side_id"], side.get("label", ""), side["outlet_ids"])))
        t_read += r
        t_search += n_modes
        sides.append(dict(side_id=s["side"]["side_id"], usable=s["usable"], pages=len(s["to_read"]),
                          read_credits=r, search_credits=n_modes))
    return dict(sides=sides, read_credits=t_read, search_credits_max=t_search, credits_max=t_read + t_search)


def read_pages(tv, ev: Event, s: dict, trace_id=None) -> dict:
    rows = s["to_read"]
    sid = s["side"]["side_id"]
    log = dict(step="read", side_id=sid, pages=len(rows), credits=0, ok=0, full=0)
    if not rows:
        return log
    rec = tv.extract(f"{ev.short}/q6_followup_read_{sid}", [a["url"] for a in rows], trace_id=trace_id,
                     extract_depth="basic", format="markdown", include_published_date=True)
    resp = rec.get("response") or {}
    by_key = {merge.url_key(a["url"]): a for a in rows}
    log.update(credits=rec.get("credits") or 0, cached=bool(rec.get("cached")), status=rec.get("status"),
               failed=len(resp.get("failed_results") or []))
    for r in resp.get("results") or []:
        a = by_key.get(merge.url_key(r.get("url") or ""))
        text = (r.get("raw_content") or "").strip()
        if a is None or len(text) <= (a.get("text_chars") or 0):
            continue
        log["ok"] += 1
        a.update(text=text, text_chars=len(text), text_status=merge.text_status(text), text_via="tavily_extract")
        a["found_by"] = sorted(set(a.get("found_by") or []) | {"tavily_extract:q6_followup_read"})
        log["full"] += a["text_status"] == "full"
    return log


def search_again(tv, ev: Event, s: dict, meta: dict, t: OutletTable, articles: list[dict], trace_id=None):
    """One more search over the side's outlets. Returns (new rows, rows it filled in, log)."""
    side = s["side"]
    q = second_query(meta.get("queries") or {}, side["side_id"])
    end = (meta.get("window") or {}).get("end_date")
    window_end = (dt.datetime.combine(dt.date.fromisoformat(end), dt.time(23, 59, 59), tzinfo=dt.timezone.utc)
                  if end else None)
    hits, logs = [], []
    for topic, hosts in split_by_mode(t, Side(side["side_id"], side.get("label", ""), side["outlet_ids"])):
        qid = f"q6_followup_{side['side_id']}_{topic}"
        p = dict(include_raw_content=True, search_depth="basic", start_date=plan.day(ev.start), topic=topic,
                 query=q, include_domains=hosts, max_results=SEARCH_MAX)
        if end:
            p["end_date"] = end
        if topic == "general":
            p["include_published_date"] = True
        rec = tv.search(f"{ev.short}/{qid}", trace_id=trace_id, **p)
        got = plan.tavily_hits(rec, qid)
        hits += got
        logs.append(dict(step="search", side_id=side["side_id"], qid=qid, query=q, results=len(got),
                         credits=rec.get("credits") or 0, cached=bool(rec.get("cached")), status=rec.get("status")))
    rows, _ = merge.merge(hits, ev.start, ev.source_urls, t, window_end=window_end)
    have = {a["url_key"]: a for a in articles}
    new, filled = [], []
    for r in rows:
        old = have.get(r["url_key"])
        if old is None:
            new.append(r)
        elif r["text_chars"] > (old.get("text_chars") or 0) and r["text_status"] == "full":
            old.update(text=r["text"], text_chars=r["text_chars"], text_status="full", text_via=r["text_via"])
            old["found_by"] = sorted(set(old.get("found_by") or []) | set(r["found_by"]))
            filled.append(old)
        else:
            old["found_by"] = sorted(set(old.get("found_by") or []) | set(r["found_by"]))
    return new, filled, logs


def followup(meta: dict, articles: list[dict], t: OutletTable, tv, complete=None, *, trace_id=None,
             min_usable: int = MIN_USABLE) -> dict:
    """One follow-up round on one story, in place: `articles` gains text and new rows. `complete`
    judges new rows with the same-story filter (models.complete bound to its step, or an eval
    ctx.complete); with None, new rows keep verdict None (not judged), as Gather leaves them."""
    ev = from_dict(meta["event"])
    lens = meta["lens"]
    before = {s["side_id"]: len(usable_outlets(articles, s)) for s in (lens.get("sides") or [])[:2]}
    log, added = [], []
    for s in short_sides(lens, articles, min_usable):
        log.append(read_pages(tv, ev, s, trace_id))
        if len(usable_outlets(articles, s["side"])) >= min_usable:
            continue
        new, filled, slogs = search_again(tv, ev, s, meta, t, articles, trace_id)
        log += slogs
        if new and complete is not None:
            res = same_story.filter_story(meta["event"], new, complete, lens=lens)
            for a in new:
                v = res["verdicts"].get(a["id"]) or {}
                a.update(verdict=v.get("verdict"), verdict_reason=v.get("reason"), verdict_by=v.get("by"))
        articles.extend(new)
        added += [a["id"] for a in new]
        log.append(dict(step="merge", side_id=s["side"]["side_id"], new=len(new), filled=len(filled)))
    after = {s["side_id"]: len(usable_outlets(articles, s)) for s in (lens.get("sides") or [])[:2]}
    return dict(version=VERSION, min_usable=min_usable, before=before, after=after, added=added,
                credits=sum(x.get("credits") or 0 for x in log if not x.get("cached")), log=log,
                at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
