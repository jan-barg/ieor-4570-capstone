"""Tavily and Guardian clients.

Every response is saved under stringer_private/frozen/raw/<event>/<name>.json (with its params,
no key), and a saved response is reused instead of calling again. So re-running a story costs
no credits, and the frozen fixtures can always be rebuilt from raw/.

Tavily credits are counted from each response's `usage.credits`, and a budget stops the run
before a call would go over it."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import keys, paths
from ..tracing import tracer


class BudgetExceeded(RuntimeError):
    pass


class CreditLedger:
    """Counts Tavily credits spent by network calls in this run (cache hits are free)."""

    def __init__(self, limit: float | None = None):
        self.limit = limit
        self.spent = 0.0
        self.calls = 0
        self._lock = threading.Lock()

    def reserve(self, estimate: float):
        with self._lock:
            if self.limit is not None and self.spent + estimate > self.limit:
                raise BudgetExceeded(f"would spend {self.spent + estimate:.0f} > limit {self.limit:.0f}")
            self.spent += estimate
            self.calls += 1

    def settle(self, estimate: float, actual: float | None):
        if actual is None:
            return
        with self._lock:
            self.spent += actual - estimate


def _save(path: str, rec: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Tavily:
    BASE = "https://api.tavily.com"

    def __init__(self, ledger: CreditLedger | None = None, raw_dir=None, offline=False):
        self.ledger = ledger or CreditLedger()
        self.raw_dir = raw_dir or paths.RAW
        self.offline = offline   # True: only cached responses; a missing one raises

    def _post(self, path, body, timeout=90):
        req = urllib.request.Request(
            self.BASE + path, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": "Bearer " + keys.get("tavily_api_key"),
                     "Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read()), time.time() - t0
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read())
            except Exception:
                payload = {"error": str(e)}
            return e.code, payload, time.time() - t0
        except (urllib.error.URLError, TimeoutError) as e:
            return 0, {"error": repr(e)}, time.time() - t0

    def call(self, path: str, params: dict, save_as: str, estimate: float, trace_id=None) -> dict:
        out = os.path.join(self.raw_dir, save_as + ".json")
        if os.path.exists(out):
            with open(out, encoding="utf-8") as f:
                rec = json.load(f)
            rec["cached"] = True
            return rec
        if self.offline:
            raise FileNotFoundError(f"offline and no saved response: {out}")
        self.ledger.reserve(estimate)
        body = dict(params, include_usage=True)
        start = dt.datetime.now(dt.timezone.utc)
        status, resp, wall = self._post(path, body)
        end = dt.datetime.now(dt.timezone.utc)
        credits = (resp.get("usage") or {}).get("credits") if isinstance(resp, dict) else None
        # failed requests are assumed free; a 200 without a usage field keeps the estimate
        self.ledger.settle(estimate, credits if status == 200 else 0)
        rec = {"path": path, "params": body, "status": status, "wall_s": round(wall, 2),
               "called_at": _now_iso(), "credits": credits, "response": resp}
        if status == 200:
            _save(out, rec)   # failed calls aren't cached, so a re-run tries again
        n = len(resp.get("results", [])) if isinstance(resp, dict) else 0
        tracer().span(name=f"tavily{path}:{os.path.basename(save_as)}", trace_id=trace_id,
                      input={k: (v if k not in ("include_domains", "urls") else f"{len(v)} items")
                             for k, v in body.items()},
                      output={"status": status, "results": n, "credits": credits},
                      metadata={"credits": credits, "results": n, "status": status},
                      start=start, end=end, error=None if status == 200 else str(resp)[:300])
        rec["cached"] = False
        return rec

    def search(self, save_as, trace_id=None, **params) -> dict:
        cost = 2 if params.get("search_depth") == "advanced" else 1
        return self.call("/search", params, save_as, cost, trace_id)

    def extract(self, save_as, urls, trace_id=None, **params) -> dict:
        return self.call("/extract", dict(params, urls=urls), save_as,
                         max(1, math.ceil(len(urls) / 5)), trace_id)

    def usage(self) -> dict:
        req = urllib.request.Request(self.BASE + "/usage",
                                     headers={"Authorization": "Bearer " + keys.get("tavily_api_key")})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        acct = d.get("account", {})
        return {"plan": acct.get("current_plan"), "used": acct.get("plan_usage"),
                "limit": acct.get("plan_limit"), "paygo_used": acct.get("paygo_usage")}


class Guardian:
    """Guardian Content API (free developer key: 1 call/s, 500 calls/day)."""
    BASE = "https://content.guardianapis.com/"
    FIELDS = "bodyText,wordcount,firstPublicationDate,byline,trailText,headline"
    _lock = threading.Lock()
    _last = [0.0]

    def __init__(self, raw_dir=None, offline=False):
        self.raw_dir = raw_dir or paths.RAW
        self.offline = offline
        self.calls = 0

    def get(self, path, params, save_as, trace_id=None) -> dict:
        out = os.path.join(self.raw_dir, save_as + ".json")
        if os.path.exists(out):
            with open(out, encoding="utf-8") as f:
                rec = json.load(f)
            rec["cached"] = True
            return rec
        if self.offline:
            raise FileNotFoundError(f"offline and no saved response: {out}")
        with self._lock:   # one call per second across threads
            wait = 1.1 - (time.time() - self._last[0])
            if wait > 0:
                time.sleep(wait)
            url = self.BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
            req = urllib.request.Request(url, headers={"api-key": keys.get("guardian_api_key"),
                                                       "User-Agent": "stringer-class-project"})
            start = dt.datetime.now(dt.timezone.utc)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    status, resp = r.status, json.loads(r.read())["response"]
            except urllib.error.HTTPError as e:
                status, resp = e.code, {"error": e.read()[:300].decode("utf-8", "replace")}
            except (urllib.error.URLError, TimeoutError) as e:
                status, resp = 0, {"error": repr(e)}
            self._last[0] = time.time()
            self.calls += 1
        end = dt.datetime.now(dt.timezone.utc)
        rec = {"path": path, "params": params, "status": status, "called_at": _now_iso(),
               "response": resp}
        if status == 200:
            _save(out, rec)
        tracer().span(name=f"guardian:{os.path.basename(save_as)}", trace_id=trace_id,
                      input={"path": path, **params},
                      output={"status": status, "results": len(resp.get("results", []))
                              if isinstance(resp, dict) else 0},
                      start=start, end=end, error=None if status == 200 else str(resp)[:300])
        rec["cached"] = False
        return rec

    def search(self, save_as, q, from_date=None, to_date=None, page_size=20, trace_id=None) -> dict:
        p = {"q": q, "page-size": page_size, "order-by": "relevance", "show-fields": self.FIELDS}
        if from_date:
            p["from-date"] = from_date
        if to_date:
            p["to-date"] = to_date
        return self.get("search", p, save_as, trace_id)

    def item(self, save_as, web_url, trace_id=None) -> dict:
        path = urllib.parse.urlsplit(web_url).path.lstrip("/")
        return self.get(path, {"show-fields": self.FIELDS}, save_as, trace_id)
