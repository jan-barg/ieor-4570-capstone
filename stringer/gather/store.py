"""The settled storage layout (map, Cross-cutting, Nov 24): one folder per story.

    stringer_private/frozen/
      stories/<event id>/articles.jsonl   one row per article: id, url, outlet, date, outlet labels,
                                          role, text status, full text (private, never served)
      stories/<event id>/gather.json      the event, lens, queries, every search with its credits
      article_cache/<2 hex>/<sha1>.json   one file per URL, shared across stories
      raw/<event short>/...               every API response, so re-runs cost nothing

The article cache keeps the best text seen for a URL, so a follow-up story that finds the same
article again doesn't fetch it again (own links already cached in full skip Extract)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from .. import paths


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class ArticleCache:
    def __init__(self, root=None):
        self.root = root or paths.ARTICLE_CACHE

    def _path(self, key: str) -> str:
        h = hashlib.sha1(key.encode()).hexdigest()
        return os.path.join(self.root, h[:2], h + ".json")

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return None

    def full_text_keys(self, keys) -> set[str]:
        out = set()
        for k in keys:
            c = self.get(k)
            if c and c.get("text_status") == "full":
                out.add(k)
        return out

    def merge_in(self, a: dict) -> dict:
        """Store the article if its text beats what's cached; return the cached best."""
        key = a["url_key"]
        cur = self.get(key)
        rank = {"guardian_api": 3, "tavily_extract": 2, "tavily_search": 1, "mts_source": 0}
        better = cur is None or (
            (rank.get(a["text_via"], 0), a["text_chars"]) > (rank.get(cur.get("text_via"), 0),
                                                              cur.get("text_chars", 0))
            and a["text_chars"] > 0)
        if better:
            rec = {k: a[k] for k in ("url", "url_key", "title", "published_at", "date_precision",
                                     "text_status", "text_chars", "text_via", "text")}
            rec["cached_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rec["seen_in"] = sorted(set((cur or {}).get("seen_in", [])) | {a.get("_event", "")} - {""})
            _atomic_write(self._path(key), json.dumps(rec, ensure_ascii=False))
            return rec
        if a.get("_event") and a["_event"] not in cur.get("seen_in", []):
            cur["seen_in"] = sorted(set(cur.get("seen_in", [])) | {a["_event"]})
            _atomic_write(self._path(key), json.dumps(cur, ensure_ascii=False))
        return cur

    def fill_from_cache(self, a: dict) -> dict:
        """Use the cached text when it is better than what this run found."""
        c = self.get(a["url_key"])
        if c and c.get("text_chars", 0) > a["text_chars"] and c.get("text"):
            a.update(text=c["text"], text_chars=c["text_chars"], text_status=c["text_status"],
                     text_via=c["text_via"] + "(cache)")
            if not a.get("title"):
                a["title"] = c.get("title", "")
        return a


def story_dir(event_id: str):
    return paths.STORIES / event_id


def write_story(event_id: str, articles: list[dict], meta: dict):
    d = story_dir(event_id)
    lines = "\n".join(json.dumps({k: v for k, v in a.items() if not k.startswith("_")},
                                 ensure_ascii=False) for a in articles)
    _atomic_write(d / "articles.jsonl", lines + ("\n" if lines else ""))
    _atomic_write(d / "gather.json", json.dumps(meta, ensure_ascii=False, indent=1, default=str))


def read_articles(event_id: str) -> list[dict]:
    p = story_dir(event_id) / "articles.jsonl"
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_meta(event_id: str) -> dict:
    with open(story_dir(event_id) / "gather.json", encoding="utf-8") as f:
        return json.load(f)
