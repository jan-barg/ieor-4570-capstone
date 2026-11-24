"""Gather one event end to end: queries -> searches -> merge -> labels -> frozen story folder."""
from __future__ import annotations

import datetime as dt
import time

from ..events import ATTRIBUTION, Event
from ..outlets import OutletTable
from ..tracing import tracer
from .clients import Guardian, Tavily
from .merge import merge, url_key
from .plan import own_links, run_plan
from .queries import QuerySet, model_queries, template_queries
from .sides import Lens
from .store import ArticleCache, write_story

VERSION = "gather-1.0 (2026-11-24)"


def gather_event(ev: Event, lens: Lens, t: OutletTable, tv: Tavily, g: Guardian, *,
                 writer: str = "model", window_days: int | None = 2, queries: QuerySet | None = None,
                 cache: ArticleCache | None = None, wait_s: int = 30, write: bool = True) -> dict:
    cache = cache or ArticleCache()
    tr = tracer()
    tid = tr.new_trace(f"gather:{ev.short}", {"event": ev.id, "title": ev.title, "lens": lens.kind})
    t0 = time.time()
    spent0 = tv.ledger.spent
    if queries is None:
        queries = model_queries(ev, lens, t, trace_id=tid) if writer == "model" else template_queries(ev, lens)
    end_date = (ev.start + dt.timedelta(days=window_days)).strftime("%Y-%m-%d") if window_days else None
    window_end = (dt.datetime.combine((ev.start + dt.timedelta(days=window_days)).date(), dt.time(23, 59, 59),
                                      tzinfo=dt.timezone.utc) if window_days else None)
    extract_urls, _, _ = own_links(ev)
    cached_full = cache.full_text_keys({url_key(u) for u in extract_urls})
    hits, log = run_plan(ev, lens, queries, t, tv, g, end_date=end_date, cached_full=cached_full,
                         trace_id=tid, wait_s=wait_s)
    articles, dropped = merge(hits, ev.start, ev.source_urls, t, window_end=window_end)
    for a in articles:
        cache.fill_from_cache(a)
        if a["text_chars"] > 0:
            cache.merge_in(dict(a, _event=ev.id))
    credits = round(tv.ledger.spent - spent0, 2)
    counts = summarize(articles)
    meta = {
        "event": ev.as_dict(), "attribution": ATTRIBUTION, "gather_version": VERSION,
        "gathered_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "window": {"start_date": ev.start.strftime("%Y-%m-%d"), "end_date": end_date},
        "lens": {"kind": lens.kind, "source": lens.source,
                 "sides": [{"side_id": s.side_id, "label": s.label, "outlet_ids": s.outlet_ids}
                           for s in lens.sides]},
        "queries": queries.as_dict(), "log": log, "dropped": dropped,
        "credits_this_run": credits, "seconds": round(time.time() - t0, 1),
        "counts": counts, "langfuse_trace_id": tid,
    }
    if write:
        write_story(ev.id, articles, meta)
    tr.span(name=f"gather_done:{ev.short}", trace_id=tid, output=counts,
            metadata={"credits": credits, "articles": len(articles)})
    return meta


def summarize(articles: list[dict]) -> dict:
    from collections import Counter
    c = Counter(a["role"] for a in articles)
    ts = Counter(a["text_status"] for a in articles)
    return {"articles": len(articles), "roles": dict(c), "text_status": dict(ts),
            "outlets": len({a["outlet"] for a in articles if a["outlet"]}),
            "own_sources": sum(a["own_source"] for a in articles),
            "unrated": sum(not a["labels"]["rated"] for a in articles)}
