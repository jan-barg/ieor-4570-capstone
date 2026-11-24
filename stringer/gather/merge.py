"""After the searches: merge results by URL, date them, tag new coverage vs background, mark
snippet-only text, and attach outlet labels (module 3).

Rules (map, module 1, "Code after the searches"):
  - merge by URL without query strings (a few article-id parameters are kept, see KEEP_PARAMS);
  - published at or after the event's exact start -> new coverage; before -> background;
    a date with no time on the start day -> role "unclear", flagged;
  - text under 1,500 characters -> snippet only (a lead, not evidence);
  - Guardian API text replaces Tavily's Guardian snippets."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

from ..outlets import OutletTable, clean_host

FULL_TEXT_MIN = 1500
# Query parameters that identify an article on some sites (everything else, like utm_* or
# at_medium=RSS, is tracking and is dropped before merging).
KEEP_PARAMS = {"id", "p", "articleid", "article_id", "storyid", "story_id", "newsid", "aid"}
VIA_RANK = {"guardian_api": 3, "tavily_extract": 2, "tavily_search": 1, "mts_source": 0}
GUARDIAN_NOISE = re.compile(r"(/live/|morning-mail|first-thing|-briefing-|/briefing/)")


def url_key(url: str) -> str:
    p = urlsplit(url.strip())
    host = clean_host(p.hostname or "")
    path = re.sub(r"/+$", "", p.path) or "/"
    keep = [(k, v) for k, v in parse_qsl(p.query) if k.lower() in KEEP_PARAMS]
    return host + path + ("?" + urlencode(keep) if keep else "")


def article_id(key: str) -> str:
    return "a_" + hashlib.sha1(key.encode()).hexdigest()[:10]


def parse_date(s) -> tuple[datetime | None, str | None]:
    """-> (UTC datetime, precision 'time' | 'day')."""
    if not s:
        return None, None
    s = str(s).strip()
    d = None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None, None
    if d is None:
        return None, None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone.utc)
    precision = "day" if (d.hour, d.minute, d.second) == (0, 0, 0) else "time"
    return d, precision


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def url_date(url: str):
    p = urlsplit(url).path.lower()
    for rx, kind in ((r"/(20\d\d)[/-](\d{1,2})[/-](\d{1,2})(?:/|-|$)", "num"),
                     (r"/(20\d\d)/([a-z]{3})/(\d{1,2})/", "mon"),
                     (r"(?:/|-)(20\d\d)(\d\d)(\d\d)(?:-|/|$)", "num")):
        m = re.search(rx, p)
        if m:
            y, mo, d = m.groups()
            mo = MONTHS.get(mo, 0) if kind == "mon" else int(mo)
            try:
                return datetime(int(y), mo, int(d), tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


@dataclass
class Hit:
    url: str
    via: str                       # tavily_search | tavily_extract | guardian_api | mts_source
    query_id: str
    rank: int
    title: str = ""
    text: str = ""
    published: str | None = None
    extra: dict = field(default_factory=dict)


def text_status(text: str) -> str:
    n = len((text or "").strip())
    return "full" if n >= FULL_TEXT_MIN else ("snippet_only" if n else "none")


def role_for(published: datetime | None, precision: str | None, start: datetime):
    if published is None:
        return "unclear", ["no_date"]
    if precision == "day":
        if published.date() == start.date():
            return "unclear", ["day_only_on_start_day"]
        return ("new_coverage" if published.date() > start.date() else "background"), ["day_only"]
    return ("new_coverage" if published >= start else "background"), []


def is_guardian_noise(url: str, extra: dict) -> bool:
    if "theguardian.com" not in url:
        return False
    return extra.get("type") == "liveblog" or bool(GUARDIAN_NOISE.search(url.lower()))


def merge(hits: list[Hit], start: datetime, own_urls: list[str], table: OutletTable,
          window_end: datetime | None = None) -> tuple[list[dict], dict]:
    own_keys = {url_key(u) for u in own_urls}
    groups: dict[str, list[Hit]] = {}
    dropped = {"guardian_noise": 0}
    for h in hits:
        k = url_key(h.url)
        if k not in own_keys and is_guardian_noise(h.url, h.extra):
            dropped["guardian_noise"] += 1
            continue
        groups.setdefault(k, []).append(h)

    articles = []
    for k, hs in groups.items():
        hs_by_text = sorted(hs, key=lambda h: (VIA_RANK[h.via] if h.via == "guardian_api" else 0,
                                               len(h.text or "")), reverse=True)
        best = hs_by_text[0]
        title = next((h.title for h in sorted(hs, key=lambda h: -VIA_RANK[h.via]) if h.title), "")
        dated = []
        for h in sorted(hs, key=lambda h: -VIA_RANK[h.via]):
            d, prec = parse_date(h.published)
            if d:
                dated.append((0 if prec == "time" else 1, -VIA_RANK[h.via], d, prec, h.via))
        if dated:
            _, _, pub, prec, date_src = sorted(dated, key=lambda x: (x[0], x[1]))[0]
        else:
            pub, prec, date_src = url_date(hs[0].url), "day", "url"
            if pub is None:
                prec = date_src = None
        role, flags = role_for(pub, prec, start)
        if pub and window_end and pub > window_end:
            flags.append("after_window")
        url = next((h.url for h in hs if h.via == "guardian_api"), hs[0].url)
        lab = table.label(url)
        text = best.text or ""
        articles.append({
            "id": article_id(k), "url": url, "url_key": k,
            "outlet": lab["outlet_id"], "outlet_name": lab["outlet_name"],
            "published_at": pub.isoformat().replace("+00:00", "Z") if pub else None,
            "date_precision": prec, "date_source": date_src,
            "role": role, "date_flags": flags,
            "title": title, "text_status": text_status(text), "text_chars": len(text.strip()),
            "text_via": best.via, "own_source": k in own_keys,
            "found_by": sorted({f"{h.via}:{h.query_id}" for h in hs}),
            "best_rank": min(h.rank for h in hs),
            "labels": {kk: v for kk, v in lab.items() if kk != "url"},
            "guardian": next((h.extra for h in hs if h.via == "guardian_api"), None),
            "verdict": None, "side": None,          # filled by modules 2 and 4
            "text": text,
        })
    articles.sort(key=lambda a: (a["role"] != "new_coverage", a["best_rank"], a["url_key"]))
    return articles, dropped
