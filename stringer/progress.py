"""Live progress of one video while it is made (module 9's progress page, map step 3; Nov 27).

The pipeline writes one small JSON record to the Gate's store, progress/<event>/<ticket>.json, as each of
the 8 steps starts and ends and as model calls come back. The website reads it every 2 to 3 seconds and
shows what each agent is doing. It holds counts and short summaries only (no article text): which outlets
each side is, how many articles were found and kept, a few claims and verdicts, the script's beats.

    p = Progress(store, event_id, ticket_id, title="...")
    p.begin("gather")                          # a step starts
    p.call({...})                              # a model call came back (models.on_call)
    p.end("gather", row, hands_on={...})       # a step ended: its seconds, dollars and counts
    p.finish("done" | "no_video" | "failed", why="...")

Example record, a third of the way in:
    {"state": "running", "current": "story_file",
     "steps": {"sides": {"t0": 0.0, "t1": 1.5, "seconds": 1.52, "usd": 0.0002, "info": {"kind": "none"}, ...},
               "story_file": {"t0": 16.0, "t1": null}},
     "calls": [{"t": 1.4, "step": "sides", "name": "lens", "model": "haiku-5-5", "usd": 0.0002, ...}], ...}

Writing must never stop a video: every store error is swallowed (and printed once). Writes are spaced at
least INTERVAL_S apart; a step's start and end are written at once.

summarize(step, read, info) builds a step's hand-on from the story folder's own files (the pipeline's
folder while it runs, or a finished run's files later), so the same summary serves both."""
from __future__ import annotations

import copy
import datetime as dt
import threading
import time

VERSION = "progress-1"
INTERVAL_S = 1.5

# The 8 agents, in the order pipeline.run calls them, with the plain words the pages show (Jan, Nov 27:
# "use the 8 agents everywhere"). typical_s: about how long each takes (four Mac runs, Nov 27); the front
# page's bar moves by these shares.
AGENTS = [
    dict(key="sides", agent="Sides picker", label="Finding the two sides", typical_s=3,
         does="Reads the event and decides which groups of outlets tell it differently."),
    dict(key="gather", agent="Searcher", label="Searching the news", typical_s=30,
         does="Writes searches for each side and for background, runs them and keeps every article it finds."),
    dict(key="same_story", agent="Same-story filter", label="Dropping other stories", typical_s=8,
         does="Checks each article is about this event, not an older or different one."),
    dict(key="balance_pick", agent="Balancer", label="Picking a fair set", typical_s=2,
         does="Picks about ten articles so both sides are heard, and searches again if one side is short."),
    dict(key="story_file", agent="News brief writer", label="Reading the articles", typical_s=90,
         does="Reads each article in full once, notes every fact with its exact quote, then merges them into claims."),
    dict(key="fact_check", agent="Fact checker", label="Checking every claim", typical_s=25,
         does="Checks each claim against the articles: confirmed, say who said it, or drop it."),
    dict(key="script", agent="Script writer", label="Writing the script", typical_s=60,
         does="Writes a 60-second script where every line cites the claims behind it, then checks each line."),
    dict(key="video", agent="Video maker", label="Recording and drawing", typical_s=62,
         does="Records the narrator, plans each shot and draws the video frame by frame."),
]
KEYS = [a["key"] for a in AGENTS]

# What a model call was for, in plain words, from the name the module gave it (models.complete's name/step).
PURPOSES = [
    ("lens", "pick the sides"), ("query_writer", "write the searches"), ("same_story", "judge the articles"),
    ("balance", "write a search for the short side"), ("brief_read", "read an article"),
    ("brief_merge verify", "check the merge"), ("brief_merge", "merge facts into claims"),
    ("brief_blind", "what each side left out"), ("brief_framing", "how each side tells it"),
    ("brief_onecall", "write the news brief"), ("fact_check", "check the claims"),
    ("script fix", "fix a line"), ("script_line", "check every line"), ("line", "check every line"),
    ("script_words", "check the wording"), ("words", "check the wording"), ("script", "write the script"),
    ("voice_direction", "plan the voice"), ("video.direction", "plan the voice"), ("direction", "plan the voice"),
]


def purpose(name: str | None) -> str:
    n = str(name or "").strip().lower()
    for prefix, words in PURPOSES:
        if n.startswith(prefix):
            return words
    return n.replace("_", " ") or "model call"


def _iso(t: float | None = None) -> str:
    return dt.datetime.fromtimestamp(t if t is not None else time.time(), dt.timezone.utc) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")


def key_for(event_id: str, ticket_id: str) -> str:
    from .gate.core import safe_id
    return f"progress/{safe_id(event_id)}/{safe_id(ticket_id)}.json"


class Progress:
    """The live record of one run. Thread-safe: model calls come back on worker threads."""

    def __init__(self, store, event_id: str, ticket_id: str, title: str = "", *, clock=time.time,
                 interval: float = INTERVAL_S, say=print):
        self.store, self.key, self.clock, self.interval, self.say = store, key_for(event_id, ticket_id), clock, interval, say
        self.t_start = clock()
        self.doc = {"version": VERSION, "event": str(event_id), "ticket": str(ticket_id), "title": str(title or "")[:300],
                    "started": _iso(self.t_start), "updated": _iso(self.t_start), "state": "running", "current": None,
                    "steps": {}, "calls": [], "searches": [], "usd": 0.0, "model_calls": 0, "seconds": None,
                    "why": None, "estimate_usd": None}
        self._lock = threading.Lock()
        self._last_write = 0.0
        self._timer: threading.Timer | None = None
        self._warned = False
        self.write()

    def now(self) -> float:
        return round(self.clock() - self.t_start, 2)

    # ---- what the pipeline tells it ------------------------------------------------------------------
    def begin(self, step: str) -> float:
        """A step starts. Returns the wall-clock time, so the pipeline can time the step with it."""
        with self._lock:
            self.doc["current"] = step
            self.doc["steps"][step] = {"t0": self.now(), "t1": None}
        self.write()
        return time.time()

    def call(self, info: dict) -> None:
        """One model call came back (models.on_call). It belongs to the step that is running."""
        with self._lock:
            self.doc["calls"].append({
                "t": self.now(), "step": self.doc["current"], "name": str(info.get("name") or info.get("step") or "")[:80],
                "model": info.get("model"), "usd": round(float(info.get("usd") or 0.0), 6),
                "tokens_in": int(info.get("tokens_in") or 0), "tokens_out": int(info.get("tokens_out") or 0),
                "seconds": round(float(info.get("seconds") or 0.0), 2), "error": bool(info.get("error"))})
            if not info.get("error"):
                self.doc["model_calls"] += 1
        self.write(soon=True)

    def end(self, step: str, row: dict, hands_on: dict | None = None, searches: list | None = None) -> None:
        """A step ended. row is pipeline.run's line for it: seconds, usd and the step's own counts."""
        info = {k: v for k, v in (row or {}).items() if k not in ("seconds", "usd")}
        with self._lock:
            s = self.doc["steps"].setdefault(step, {"t0": max(0.0, self.now() - float(row.get("seconds") or 0))})
            s.update(t1=self.now(), seconds=row.get("seconds"), usd=row.get("usd"), info=info, hands_on=hands_on)
            if searches:
                t0, t1 = s["t0"], s["t1"]
                n = len(searches)
                for i, q in enumerate(searches):      # times aren't recorded per search: spread them over the step
                    self.doc["searches"].append(dict(q, step=step, t=round(t0 + (t1 - t0) * (i + 1) / (n + 1), 2)))
            self.doc["usd"] = round(sum(float(x.get("usd") or 0) for x in self.doc["steps"].values()), 6)
            if self.doc["current"] == step:
                self.doc["current"] = None
        self.write()

    def note(self, **kw) -> None:
        with self._lock:
            self.doc.update(kw)
        self.write(soon=True)

    def finish(self, outcome: str, why: str | None = None, *, seconds: float | None = None, usd: float | None = None) -> None:
        with self._lock:
            cur = self.doc["current"]
            if cur and cur in self.doc["steps"] and self.doc["steps"][cur].get("t1") is None:
                self.doc["steps"][cur]["stopped_at"] = self.now()
            self.doc.update(state=outcome, why=(str(why)[:600] if why else None), current=None,
                            seconds=round(seconds if seconds is not None else self.now(), 2))
            if usd is not None:
                self.doc["usd"] = round(float(usd), 6)
        self.write()

    # ---- writing ------------------------------------------------------------------------------------
    def write(self, soon: bool = False) -> None:
        """Write now, or (soon=True) within INTERVAL_S, so a burst of calls is one write."""
        if soon and self.clock() - self._last_write < self.interval:
            with self._lock:
                if self._timer is None:
                    self._timer = threading.Timer(self.interval, self.write)
                    self._timer.daemon = True
                    self._timer.start()
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self.doc["updated"] = _iso(self.clock())
            doc = copy.deepcopy(self.doc)
            self._last_write = self.clock()
        try:
            self.store.update(self.key, lambda cur: (doc, None))
        except Exception as e:                      # the page goes stale; the video carries on
            if not self._warned:
                self._warned = True
                self.say(f"  progress: could not save {self.key}: {e!r}"[:300])


# ---- hand-ons: what each step passes to the next, in short ------------------------------------------
def _cut(s, n: int = 220) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _names(read, table=None) -> dict:
    """outlet id -> outlet name, from the articles (their outlet_name) and the outlet table when given."""
    out = {}
    if table is not None:
        try:
            for oid, o in getattr(table, "by_id", {}).items():
                out[oid] = getattr(o, "name", None) or oid
        except Exception:
            pass
    for a in read("articles.jsonl") or []:
        if a.get("outlet") and a.get("outlet_name"):
            out.setdefault(a["outlet"], a["outlet_name"])
    return out


def _sides(read) -> list[dict]:
    lens = read("lens.json") or {}
    g = (read("gather.json") or {}).get("lens") or {}
    return list(lens.get("sides") or g.get("sides") or [])


def summarize(step: str, read, info: dict | None = None, table=None) -> dict | None:
    """A step's hand-on from the story folder. read(name) returns a file's JSON (a list for .jsonl) or None.
    Never raises: a summary that can't be made is None, and the page shows the counts alone."""
    try:
        return _SUMMARY[step](read, info or {}, table)
    except Exception:
        return None


def _h_sides(read, info, table):
    lens = read("lens.json") or {}
    names = _names(read, table)
    sides = _sides(read)
    out = {"kind": lens.get("kind") or info.get("kind"), "reason": _cut(lens.get("reason"), 300),
           "chosen_by": lens.get("chosen_by") or "model"}
    for i, k in enumerate(("side_a", "side_b")):
        if i < len(sides):
            ids = list(sides[i].get("outlet_ids") or [])
            out[k] = {"label": sides[i].get("label") or sides[i].get("side_id"), "side_id": sides[i].get("side_id"),
                      "outlets": [names.get(o, o) for o in ids[:8]], "n": len(ids)}
    return out


def _h_gather(read, info, table):
    g = read("gather.json") or {}
    arts = read("articles.jsonl") or []
    sides = _sides(read)
    by_side, seen = {}, set()
    for s in sides:
        ids = set(s.get("outlet_ids") or [])
        n = sum(1 for a in arts if a.get("outlet") in ids)
        seen |= {a.get("id") for a in arts if a.get("outlet") in ids}
        by_side[s.get("label") or s.get("side_id")] = n
    by_side["elsewhere"] = sum(1 for a in arts if a.get("id") not in seen)
    c = g.get("counts") or {}
    return {"articles": c.get("articles", len(arts)), "outlets": c.get("outlets", len({a.get("outlet") for a in arts})),
            "by_side": by_side, "full_text": (c.get("text_status") or {}).get("full")}


def searches_of(read) -> list[dict]:
    """The news searches Gather ran (gather.json's log): name, query, results, credits."""
    g = read("gather.json") or {}
    log = g.get("log") or {}
    out = []
    for q in log.get("searches") or []:
        qid = str(q.get("qid") or "")
        name = qid.split("_", 1)[1].replace("_", " ") if "_" in qid else qid
        credits = sum(int(a.get("credits") or 0) for a in q.get("attempts") or [] if not a.get("cached"))
        out.append({"name": name, "query": _cut(q.get("query"), 160), "results": int(q.get("results") or 0),
                    "credits": credits, "source": "news search",
                    "note": "tried again" if len(q.get("attempts") or []) > 1 else ""})
    for q in log.get("guardian") or []:
        out.append({"name": "Guardian", "query": _cut(q.get("query"), 160), "results": int(q.get("results") or 0),
                    "credits": 0, "source": "The Guardian's search", "note": ""})
    own = log.get("own") or {}
    if own:
        out.append({"name": "own page", "query": "the event's own source pages", "results": int(own.get("ok") or 0),
                    "credits": int(own.get("credits") or 0), "source": "full text", "note": "read the full text"})
    return out


def _h_same(read, info, table):
    arts = read("articles.jsonl") or []
    counts = {"same": 0, "different": 0, "follow_up": 0}
    for a in arts:
        v = a.get("verdict")
        if v in counts:
            counts[v] += 1
    examples = []
    for want in ("same", "different", "follow_up"):
        pool = [a for a in arts if a.get("verdict") == want and a.get("verdict_reason")]
        pool.sort(key=lambda a: a.get("verdict_by") != "model")       # the model's own words first
        if pool:
            a = pool[0]
            examples.append({"outlet": a.get("outlet_name") or a.get("outlet"), "verdict": want.replace("_", "-"),
                             "why": _cut(a.get("verdict_reason"), 160)})
    return dict(counts, examples=examples)


def _h_pick(read, info, table):
    p = read("picked.json") or {}
    names = _names(read, table)
    picked = [{"outlet": names.get(r.get("outlet"), r.get("outlet")),
               "side": r.get("group") if r.get("group") in ("A", "B", "wire") else "other",
               "title": _cut(r.get("title"), 120)} for r in p.get("rows") or []]
    flags = list(p.get("flags") or [])
    if read("balance.json"):
        flags.insert(0, "One side was short, so it searched again.")
    return {"picked": picked, "flags": [_cut(f, 160) for f in flags], "available": p.get("available")}


def _side_letter(read):
    sides = _sides(read)
    return {s.get("side_id"): "AB"[i] for i, s in enumerate(sides[:2])}


def _h_brief(read, info, table):
    sf = read("story_file.json") or read("checked_story_file.json") or {}
    letter = _side_letter(read)
    claims = sf.get("claims") or []
    ranked = sorted(claims, key=lambda c: -len(c.get("articles") or []))[:4]
    sample = [{"id": c.get("id"), "claim": _cut(c.get("claim"), 220), "who_says": _cut(c.get("who_says"), 60),
               "articles": len(c.get("articles") or []),
               "sides": [letter[s] for s in c.get("sides") or [] if s in letter]} for c in ranked]
    ways = {}
    for p in sf.get("perspectives") or []:
        pts = [_cut(x.get("point"), 200) for x in (p.get("points") or [])[:2] if x.get("point")]
        if pts:
            ways[p.get("label") or p.get("side_id")] = pts
    left = [_cut(b.get("text") or b.get("point") or b.get("claim") or b.get("what"), 200)
            for b in (sf.get("blindspots") or [])[:2] if isinstance(b, dict)]
    return {"claims_sample": sample, "how_each_side_tells_it": ways, "left_out": [x for x in left if x],
            "facts": (sf.get("counts") or {}).get("facts"), "claims": len(claims)}


STATUS_WORDS = {"confirmed": "confirmed", "say_with_source": "say who said it", "dropped": "dropped",
                "unchecked": "unchecked"}


def _h_check(read, info, table):
    sf = read("checked_story_file.json") or {}
    claims = sf.get("claims") or []
    out, seen = [], set()
    for want in ("confirmed", "say_with_source", "dropped", "confirmed"):
        for c in claims:
            if c.get("status") == want and c.get("id") not in seen:
                seen.add(c.get("id"))
                out.append({"id": c.get("id"), "status": STATUS_WORDS.get(want, want), "claim": _cut(c.get("claim"), 220),
                            "why": _cut((c.get("check") or {}).get("why") or c.get("reason"), 220)})
                break
    return {"verdicts": out, "counts": (sf.get("fact_check") or {}).get("counts") or {}}


def _h_script(read, info, table):
    sc = read("script.json") or {}
    beats = [{"n": b.get("n"), "shot": b.get("shot"), "say": _cut(b.get("say"), 240), "claims": list(b.get("claims") or [])[:6]}
             for b in sc.get("beats") or []]
    out = {"title": _cut(sc.get("title"), 120), "beats": beats, "words": sc.get("words"), "status": sc.get("status")}
    if sc.get("status") == "no video":
        probs = ((sc.get("checks") or {}).get("final") or {}).get("problems") or []
        drafts = ((sc.get("drafts") or {}).get("final") or (sc.get("drafts") or {}).get("first") or {}).get("beats") or []
        n = int((probs[0] or {}).get("beat") or 1) if probs else 1
        b = drafts[n - 1] if 0 < n <= len(drafts) else {}
        out["failed_beat"] = {"n": n, "shot": b.get("shot") or "hook", "say": _cut(b.get("say"), 240),
                              "claims": list(b.get("claims") or [])[:6],
                              "why": _cut((probs[0] or {}).get("what") if probs else sc.get("reason"), 400)}
        out["reason"] = _cut(sc.get("reason"), 400)
    return out


VIDEO_PARTS = [("check", "Final check"), ("direction", "Planning the voice"), ("voice", "Recording the voice"),
               ("plan", "Planning the shots"), ("render", "Drawing the frames"), ("files", "Sound levels, poster, captions")]


def _h_video(read, info, table):
    parts_s = info.get("parts_seconds") or {}
    parts = [{"part": k, "label": label, "seconds": parts_s[k]} for k, label in VIDEO_PARTS if k in parts_s]
    out = {"parts": parts, "voice": f"{info.get('voice_credits')} voice credits" if info.get("voice_credits") else None,
           "status": info.get("status")}
    for k in ("frames", "captions", "beats", "duration_s"):
        if info.get(k) is not None:
            out[k] = info[k]
    if out.get("duration_s"):
        d = int(round(float(out["duration_s"])))
        out["length"] = f"{d // 60}:{d % 60:02d}"
    return out


_SUMMARY = {"sides": _h_sides, "gather": _h_gather, "same_story": _h_same, "balance_pick": _h_pick,
            "story_file": _h_brief, "fact_check": _h_check, "script": _h_script, "video": _h_video}


def folder_reader(d):
    """read(name) over a local story folder."""
    import json
    from pathlib import Path
    d = Path(d)

    def read(name):
        p = d / name
        if not p.exists():
            return None
        text = p.read_text(encoding="utf-8")
        if name.endswith(".jsonl"):
            return [json.loads(x) for x in text.split("\n") if x.strip()]
        return json.loads(text)
    return read
