"""The query plan (map, module 1), run for one event.

  #  search             mode                         domains                         query        results
  1  core               news                         every news/wire row (<= 300)    title        20
  2  core, reworded     news                         same                            reworded     20
  3  side A             news for US outlets,         side A's outlets                side query   10
  4  side B               general for the rest       side B's outlets                side query   10
  4  local press        general (stories with one    the story's country's outlets   title, then  20 each
                          set in the lens file)        (searched, never compared)      a query in
                                                                                     the local
                                                                                     language
  5  right tail         general (US lens only)       right outlets minus Fox/NY Post title        10
  6  Guardian           Guardian API                 theguardian.com                 title keywords;
                                                                                     reworded joined with OR  20 each,
                                                                                     top 8 kept (see cut_guardian)
     own sources        Extract (Guardian links via the API)  the event's links minus X posts
     background         general                      every news/wire row, end_date = day before   10

Every search: page text on, a domain list, start_date = the event's UTC day, basic depth.
Fewer than 5 results -> retry right away, then once more after ~30 s. General mode asks for
published dates. Fixtures add end_date = start + 2 days."""
from __future__ import annotations

import datetime as dt
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..events import Event
from ..outlets import OutletTable
from .clients import BudgetExceeded, Guardian, Tavily
from .merge import Hit, is_guardian_noise, url_key
from .queries import QuerySet, terms
from .sides import Lens, split_by_mode, us_sides

# Per Guardian search, keep the top 8 by relevance, not counting liveblogs and newsletters (merge
# drops those). Nov 24 check on the 40 frozen stories, labeled blind to rank: #1 is on the event
# ~83% of the time, #4-5 ~50%, #8-10 ~28%, past #15 under 10%. Top 8 keeps 85% of the on-topic
# Guardian articles and halves the pile (21 -> 11 per story).
GUARDIAN_KEEP = 8
LOCAL_MAX = 20      # the two side searches it replaces on a no-split story returned 10 each
THIN = 5
RETRY_WAIT_S = 30
X_HOSTS = ("x.com/", "twitter.com/")


@dataclass
class Search:
    qid: str
    params: dict
    kind: str = "tavily"


@dataclass
class SearchLog:
    qid: str
    topic: str
    query: str
    domains: int
    attempts: list = field(default_factory=list)   # [{results, credits, cached}]
    used_attempt: int = 0
    results: int = 0


def day(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%d")


def build_searches(ev: Event, lens: Lens, qs: QuerySet, t: OutletTable,
                   end_date: str | None) -> list[Search]:
    core = t.core_domains()
    base = dict(include_raw_content=True, search_depth="basic", start_date=day(ev.start))
    if end_date:
        base["end_date"] = end_date
    out = [Search("q1_core", dict(base, topic="news", query=qs.core, include_domains=core, max_results=20)),
           Search("q2_reworded", dict(base, topic="news", query=qs.reworded, include_domains=core,
                                      max_results=20))]
    for i, side in enumerate(lens.sides):
        tag = "ab"[i] if i < 2 else str(i)
        for topic, hosts in split_by_mode(t, side):
            p = dict(base, topic=topic, query=qs.sides.get(side.side_id, qs.core),
                     include_domains=hosts, max_results=10)
            if topic == "general":
                p["include_published_date"] = True
            out.append(Search(f"q3{tag}_side_{side.side_id}_{topic}", p))
    if lens.local:
        # The English title alone finds only local outlets' English pages (Krakow, Nov 24: 19 hits,
        # 15 from the state broadcaster's English site, none of the Polish-language coverage), so a
        # second search uses the query writer's local-language query when there is one.
        lang_q = qs.sides.get(lens.local.side_id, "")
        for topic, hosts in split_by_mode(t, lens.local):
            for suffix, q in (("", qs.core), ("_lang", lang_q)):
                if not q or (suffix and q.strip().lower() == qs.core.strip().lower()):
                    continue
                p = dict(base, topic=topic, query=q, include_domains=hosts, max_results=LOCAL_MAX)
                if topic == "general":
                    p["include_published_date"] = True
                out.append(Search(f"q4_{lens.local.side_id}{suffix}_{topic}", p))
    if lens.kind == "us":
        tail = us_sides(t)["us_right_tail"]
        out.append(Search("q5_right_tail", dict(base, topic="general", include_published_date=True,
                                                 query=qs.core, include_domains=t.hosts(set(tail.outlet_ids), None),
                                                 max_results=10)))
    bg_end = day(ev.start - dt.timedelta(days=1))
    out.append(Search("q9_background", dict(include_raw_content=True, search_depth="basic", topic="general",
                                            include_published_date=True, query=qs.background,
                                            include_domains=core, end_date=bg_end, max_results=10)))
    return out


def run_search(tv: Tavily, ev: Event, s: Search, trace_id=None, wait_s=RETRY_WAIT_S) -> tuple[dict, SearchLog]:
    """One search with the thin-result retries. Returns the fullest response."""
    log = SearchLog(s.qid, s.params.get("topic"), s.params.get("query"), len(s.params.get("include_domains", [])))
    best, best_n = None, -1
    for attempt in range(3):
        name = f"{ev.short}/{s.qid}" + (f"__retry{attempt}" if attempt else "")
        if attempt == 2:
            # the second retry waits ~30 s, unless its response is already saved
            import os
            if not os.path.exists(os.path.join(tv.raw_dir, name + ".json")) and not tv.offline:
                time.sleep(wait_s)
        rec = tv.search(name, trace_id=trace_id, **s.params)
        n = len((rec.get("response") or {}).get("results", [])) if rec.get("status") == 200 else 0
        log.attempts.append(dict(results=n, credits=rec.get("credits"), cached=rec.get("cached"),
                                 status=rec.get("status")))
        if n > best_n:
            best, best_n, log.used_attempt = rec, n, attempt
        if n >= THIN:
            break
    log.results = max(best_n, 0)
    return best, log


def tavily_hits(rec: dict, qid: str) -> list[Hit]:
    out = []
    for i, r in enumerate((rec.get("response") or {}).get("results", []) if rec else []):
        out.append(Hit(url=r["url"], via="tavily_search", query_id=qid, rank=i + 1,
                       title=r.get("title") or "", text=r.get("raw_content") or r.get("content") or "",
                       published=r.get("published_date")))
    return out


def guardian_hit(r: dict, qid: str, rank: int) -> Hit:
    f = r.get("fields", {})
    return Hit(url=r["webUrl"], via="guardian_api", query_id=qid, rank=rank,
               title=f.get("headline") or r.get("webTitle") or "", text=f.get("bodyText") or "",
               published=f.get("firstPublicationDate") or r.get("webPublicationDate"),
               extra={"type": r.get("type"), "section": r.get("sectionId"),
                      "pillar": r.get("pillarName"), "wordcount": f.get("wordcount")})


def guardian_searches(g: Guardian, ev: Event, qs: QuerySet, end_date, trace_id=None) -> tuple[list[Hit], list[dict]]:
    hits, logs = [], []
    queries = [("g1_title", " ".join(terms(ev.title))),
               ("g2_reworded_or", " OR ".join(dict.fromkeys(terms(qs.reworded))))]
    for qid, q in queries:
        if not q:
            continue
        rec = g.search(f"{ev.short}/{qid}", q, day(ev.start), end_date, trace_id=trace_id)
        res = (rec.get("response") or {}).get("results", []) if rec.get("status") == 200 else []
        logs.append(dict(qid=qid, query=q, status=rec.get("status"), results=len(res), cached=rec.get("cached")))
        clean = 0
        for i, r in enumerate(res):
            h = guardian_hit(r, qid, i + 1)
            if not is_guardian_noise(h.url, h.extra):
                clean += 1
                h.extra["clean_rank"] = clean    # rank among real articles, used by cut_guardian
            hits.append(h)
    return hits, logs


def cut_guardian(hits: list[Hit], keep: int = GUARDIAN_KEEP) -> tuple[list[Hit], int]:
    """Drop Guardian search results ranked below `keep` in their search. A result survives if it
    made the cut in the other Guardian search, or if Tavily found it too. (The event's own Guardian
    links are fetched after this, so they are never cut.) Returns the hits and how many distinct
    articles were cut."""
    elsewhere = {url_key(h.url) for h in hits if h.via != "guardian_api"}
    out, cut = [], set()
    for h in hits:
        r = h.extra.get("clean_rank") if h.via == "guardian_api" else None
        if r is not None and r > keep and url_key(h.url) not in elsewhere:
            cut.add(url_key(h.url))
            continue
        out.append(h)
    kept = {url_key(h.url) for h in out}
    return out, len(cut - kept)


def guardian_items(g: Guardian, ev: Event, urls: list[str], qid: str, trace_id=None) -> tuple[list[Hit], list[dict]]:
    hits, logs = [], []
    for u in urls:
        name = f"{ev.short}/{qid}_" + re.sub(r"[^a-z0-9]+", "-", url_key(u).split("theguardian.com/")[-1].lower())[:80]
        rec = g.item(name, u, trace_id=trace_id)
        content = (rec.get("response") or {}).get("content") if rec.get("status") == 200 else None
        logs.append(dict(qid=qid, url=u, status=rec.get("status"), cached=rec.get("cached")))
        if content:
            hits.append(guardian_hit(content, qid, 1))
    return hits, logs


X_EPOCH_MS = 1288834974657


def x_post_time(url: str) -> str | None:
    """X post ids carry their creation time (snowflake ids): ms = (id >> 22) + X_EPOCH_MS."""
    m = re.search(r"/status(?:es)?/(\d{6,})", url)
    if not m:
        return None
    ms = (int(m.group(1)) >> 22) + X_EPOCH_MS
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def source_hits(ev: Event) -> list[Hit]:
    """Every link the event cites becomes a row, even without text (X posts, blocked sites)."""
    return [Hit(url=u, via="mts_source", query_id="mts_sources", rank=0,
                published=x_post_time(u) if any(h in u.lower() for h in X_HOSTS) else None)
            for u in ev.source_urls]


def own_links(ev: Event) -> tuple[list[str], list[str], list[str]]:
    """-> (links for Extract, Guardian links, X posts)."""
    extract, guardian, xposts = [], [], []
    for u in ev.source_urls:
        low = u.lower()
        if any(h in low for h in X_HOSTS):
            xposts.append(u)
        elif "theguardian.com/" in low:
            guardian.append(u)
        else:
            extract.append(u)
    return extract, guardian, xposts


def extract_own(tv: Tavily, ev: Event, urls: list[str], cached_full: set[str], trace_id=None) -> tuple[list[Hit], dict]:
    """Extract the event's own links, skipping ones the shared article cache already has in full."""
    todo = [u for u in urls if url_key(u) not in cached_full]
    log = dict(qid="own_extract", urls=len(urls), skipped_cached=len(urls) - len(todo), credits=None)
    if not todo:
        return [], log
    rec = tv.extract(f"{ev.short}/own_extract", todo, trace_id=trace_id, extract_depth="basic",
                     format="markdown", include_published_date=True)
    resp = rec.get("response") or {}
    log.update(credits=rec.get("credits"), cached=rec.get("cached"), status=rec.get("status"),
               ok=len(resp.get("results", [])), failed=len(resp.get("failed_results", [])))
    hits = [Hit(url=r["url"], via="tavily_extract", query_id="own_extract", rank=1,
                title=r.get("title") or "", text=r.get("raw_content") or "",
                published=r.get("published_date")) for r in resp.get("results", [])]
    return hits, log


def run_plan(ev: Event, lens: Lens, qs: QuerySet, t: OutletTable, tv: Tavily, g: Guardian,
             end_date: str | None = None, cached_full: set[str] = frozenset(), trace_id=None,
             wait_s=RETRY_WAIT_S, workers=6) -> tuple[list[Hit], dict]:
    searches = build_searches(ev, lens, qs, t, end_date)
    hits: list[Hit] = []
    log = {"searches": [], "guardian": [], "own": {}}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(run_search, tv, ev, s, trace_id, wait_s) for s in searches]
        g_search = pool.submit(guardian_searches, g, ev, qs, end_date, trace_id)
        extract_urls, g_own, xposts = own_links(ev)
        f_extract = pool.submit(extract_own, tv, ev, extract_urls, cached_full, trace_id)
        for s, f in zip(searches, futs):
            rec, slog = f.result()      # re-raises BudgetExceeded
            log["searches"].append(slog.__dict__)
            hits += tavily_hits(rec, s.qid)
        gh, glog = g_search.result()
        hits += gh
        log["guardian"] += glog
        eh, elog = f_extract.result()
        hits += eh
        log["own"] = dict(elog, guardian_links=len(g_own), x_posts=len(xposts))
    hits, log["guardian_cut"] = cut_guardian(hits)
    # Guardian links: the event's own, plus any Tavily found that the API searches didn't return
    have = {url_key(h.url) for h in hits if h.via == "guardian_api"}
    tav_guardian = list(dict.fromkeys(h.url for h in hits if h.via != "guardian_api"
                                      and "theguardian.com/" in h.url and url_key(h.url) not in have))
    gi, gil = guardian_items(g, ev, g_own, "g_own", trace_id)
    gt, gtl = guardian_items(g, ev, [u for u in tav_guardian if url_key(u) not in {url_key(x) for x in g_own}],
                             "g_from_tavily", trace_id)
    hits += gi + gt
    log["guardian"] += gil + gtl
    hits += source_hits(ev)
    log["x_posts"] = xposts
    return hits, log


__all__ = ["run_plan", "build_searches", "BudgetExceeded", "own_links"]
