"""Where the Gate keeps its shared records: a folder of small JSON files on the Mac, a Cloud Storage
bucket on the site (decided Nov 26, Jan). Several Cloud Run machines serve the site at once, so
nothing the Gate counts can live in memory.

The one idea that makes it safe: every record has a version, and a write can say "only if the record
is still at the version I read" (Cloud Storage calls it ifGenerationMatch). If another machine wrote
first, the write is refused and the caller reads again and retries. update() wraps that loop.

Example: two clicks on the same event land on two machines in the same second. Both read
events/abc.json at version 7 and both try to write "being made". Cloud Storage accepts the first
write (now version 8) and refuses the second, whose retry then sees "being made" and turns back.

    s = LocalStore(path) | GCSStore("bucket", "gate/") | MemoryStore()
    value, version = s.get("events/abc.json")          # (None, None) when absent
    s.put("events/abc.json", {...}, version)            # version None: create only
    s.update("slots.json", lambda cur: (new_value, result))   # read, change, write, retry
    s.add("log/2026-12-09/<unique>.json", {...})        # a new record that never changes
    s.list("log/2026-12-09/")                           # keys under a prefix, sorted

store_from_env(): GATE_STORE = "gs://bucket/prefix" or a folder; default stringer_private/gate/."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import random
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

from .. import paths

NO_CHANGE = object()        # an update() function returns (NO_CHANGE, result) to write nothing


class Conflict(RuntimeError):
    """The record changed since it was read (or already exists, for a create)."""


class Store:
    def get(self, key: str) -> tuple[dict | None, str | None]:
        raise NotImplementedError

    def put(self, key: str, value: dict, version: str | None) -> str:
        """Write `value` if the record is still at `version` (None: only if it doesn't exist yet).
        Returns the new version; raises Conflict otherwise."""
        raise NotImplementedError

    def list(self, prefix: str) -> list[str]:
        raise NotImplementedError

    def add(self, key: str, value: dict) -> str:
        return self.put(key, value, None)

    def update(self, key: str, fn, *, attempts: int = 25):
        """Read the record, let fn(current or None) return (new value, result), write it if nobody
        changed it meanwhile, and retry from a fresh read if they did. Returns fn's result."""
        for i in range(attempts):
            cur, ver = self.get(key)
            new, result = fn(copy.deepcopy(cur))
            if new is NO_CHANGE:
                return result
            try:
                self.put(key, new, ver)
                return result
            except Conflict:
                time.sleep(min(0.5, 0.01 * (2 ** i)) * random.random())
        raise Conflict(f"{key}: still changing after {attempts} tries")


class MemoryStore(Store):
    """For tests: the same rules, kept in a dict."""

    def __init__(self):
        self._d: dict[str, tuple[str, int]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._d.get(key)
        return (json.loads(hit[0]), str(hit[1])) if hit else (None, None)

    def put(self, key, value, version):
        body = json.dumps(value, ensure_ascii=False, default=str)
        with self._lock:
            hit = self._d.get(key)
            now = str(hit[1]) if hit else None
            if now != version:
                raise Conflict(f"{key}: at version {now}, not {version}")
            n = (hit[1] if hit else 0) + 1
            self._d[key] = (body, n)
            return str(n)

    def list(self, prefix):
        with self._lock:
            return sorted(k for k in self._d if k.startswith(prefix))


class LocalStore(Store):
    """A folder of JSON files; one lock file makes each compare-and-write atomic across threads and
    processes on this machine. Each file holds {"version": n, "value": {...}}."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lockfile = self.root / ".lock"
        self._tlock = threading.Lock()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"bad key {key!r}")
        return p

    def _read(self, p: Path):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, None
        return d["value"], str(d["version"])

    def get(self, key):
        return self._read(self._path(key))

    def put(self, key, value, version):
        p = self._path(key)
        with self._tlock, open(self._lockfile, "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                _, now = self._read(p)
                if now != version:
                    raise Conflict(f"{key}: at version {now}, not {version}")
                n = int(now or 0) + 1
                p.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"version": n, "value": value}, f, ensure_ascii=False, default=str)
                os.replace(tmp, p)
                return str(n)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def list(self, prefix):
        base = self.root
        out = []
        for p in base.rglob("*.json"):
            k = p.relative_to(base).as_posix()
            if k.startswith(prefix) and not p.name.startswith(".tmp-"):
                out.append(k)
        return sorted(out)


class GCSStore(Store):
    """Cloud Storage through its JSON API, with ifGenerationMatch for the compare-and-write (no extra
    library: google-auth's AuthorizedSession). The bucket for these records must not be public:
    reports carry viewers' notes."""

    API = "https://storage.googleapis.com/storage/v1/b/{bucket}/o"
    UPLOAD = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
    BUSY = (429, 500, 502, 503, 504)     # "try again shortly": the request was not carried out
    TRIES = 3

    def __init__(self, bucket: str, prefix: str = "gate/", session=None, timeout: float = 15.0):
        self.bucket = bucket
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"
        self.timeout = timeout
        self._session = session

    @property
    def session(self):
        if self._session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
            self._session = AuthorizedSession(creds)
        return self._session

    def _name(self, key: str) -> str:
        return self.prefix + key

    def _send(self, method: str, url: str, *, reading: bool, **kw):
        """One request, tried again after a short pause when Cloud Storage says it is busy. Before this
        (Nov 27 review) one 503 inside a running video's heartbeat ended the whole paid run.
        A read is also tried again after a network error. A write is not: the write may have landed, and
        sending it again would be refused as a conflict, which update() would answer by applying the
        change a second time (counting a video twice)."""
        last = None
        for attempt in range(self.TRIES):
            try:
                r = getattr(self.session, method)(url, timeout=self.timeout, **kw)
            except Exception as e:
                if not reading or attempt == self.TRIES - 1:
                    raise
                last = e
            else:
                if r.status_code not in self.BUSY or attempt == self.TRIES - 1:
                    return r
            time.sleep(0.3 * (attempt + 1) * (1 + random.random()))
        raise last          # not reached: the loop returns or raises on its last try

    def get(self, key):
        url = self.API.format(bucket=self.bucket) + "/" + quote(self._name(key), safe="")
        r = self._send("get", url, reading=True, params={"alt": "media"})
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        return json.loads(r.content.decode("utf-8")), str(r.headers["x-goog-generation"])

    def put(self, key, value, version):
        body = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        params = {"uploadType": "media", "name": self._name(key), "ifGenerationMatch": version or "0"}
        r = self._send("post", self.UPLOAD.format(bucket=self.bucket), reading=False, params=params, data=body,
                       headers={"Content-Type": "application/json", "Cache-Control": "no-store"})
        if r.status_code in (409, 412):
            raise Conflict(f"{key}: changed since version {version}")
        r.raise_for_status()
        return str(r.json()["generation"])

    def list(self, prefix):
        out, token = [], None
        while True:
            params = {"prefix": self._name(prefix), "fields": "items(name),nextPageToken"}
            if token:
                params["pageToken"] = token
            r = self._send("get", self.API.format(bucket=self.bucket), reading=True, params=params)
            r.raise_for_status()
            d = r.json()
            out += [i["name"][len(self.prefix):] for i in d.get("items") or []]
            token = d.get("nextPageToken")
            if not token:
                return sorted(out)


def store_from_env() -> Store:
    where = os.environ.get("GATE_STORE", "").strip()
    if where.startswith("gs://"):
        bucket, _, prefix = where[5:].partition("/")
        return GCSStore(bucket, prefix or "gate/")
    return LocalStore(where or (paths.PRIVATE / "gate"))
