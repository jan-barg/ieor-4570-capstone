"""A cache of model answers, keyed by the exact call (model + messages + parameters).

Why: re-running an eval with the same model and prompt, or re-scoring it after the answer key
changes, should cost nothing. The same call always gets the saved answer back, so the second run
of an unchanged prompt makes no model calls at all. Change one word of the prompt and the key
changes, so a new prompt version is always really called.

Stored under stringer_private/evals/cache/<2 hex>/<sha256>.json: the answer text, the token
counts and the time the call took. Cost is not stored; it is recomputed from the tokens with the
prices in config/models.toml, so a price fix applies to old runs too. Answers can quote article
text, which is why the cache lives in the private folder."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .. import paths


def call_key(litellm_model: str, messages: list[dict], params: dict | None = None) -> str:
    params = {k: v for k, v in (params or {}).items() if k != "timeout"}     # a timeout doesn't change the answer
    blob = json.dumps({"model": litellm_model, "messages": messages, "params": params},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CallCache:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or paths.EVALS / "cache")

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def has(self, key: str) -> bool:
        return self._path(key).exists()

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, record: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = dict(record, cached_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, p)
