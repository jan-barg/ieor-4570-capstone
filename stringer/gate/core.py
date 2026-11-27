"""The Gate (module 0): may this event become a video, and can one start right now?

What the website calls (decided Nov 26, Jan, decisions page "Stringer Gate Decisions"):
    gate.screen(events)          -> the events the front page may show, each "ready", "making" or
                                    "has_video". Refused events are simply left out (Jan: "we don't
                                    show that it was refused").
    gate.check(event)            -> Decision for one event; changes nothing but the saved content check.
    gate.start(event, visitor)   -> Decision; on go it carries a Ticket: the event is claimed and the
                                    day's count, the site's "at once" count and the visitor's count are
                                    taken, all or none.
    ticket.charge(usd, what)     -> after each paid step; stops a runaway video past $5.
    ticket.checkpoint(n_articles=...) after the searches: stops before the dear steps if the rest of
                                    the video would pass $5 (Jan: work the cost out before spending).
    ticket.finish(video=... | no_video=... | error=...)
    gate.report(event, visitor, reason, note)   the Report link; the first report hides the video
    gate.take_down / restore / remake / reports / hidden / log / status         the admin side
    gate.set_mode("closed" | "open", by, note)   the admin's pause button (kept in the store, module 9)
    gate.visitor_status(visitor) -> this visitor's starts this hour and reports today (the front page meter)

The checks, cheapest first: the site is open; the event qualifies (rules.py); the content check
allows it (policy.py, saved per event); it isn't taken down; it has no video and none is being made;
Tavily has credits; the cost estimate is under $5 (cost.py); then the claim, the day's 30, the 3 at
once and the visitor's 3 an hour. Every record is in the shared store (store.py), so the answers
hold across Cloud Run machines.

Example: two people click the same event a second apart. The first start() claims
events/<id>.json (state "making") and gets a ticket; the second start() reads "making" and gets
Decision(ok=False, code="making", message="A video for this story is being made...")."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import secrets
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from . import cost, policy, rules
from .store import NO_CHANGE, Store, store_from_env

# Plain sentences the front page shows. Events the Gate refuses for what they are (too small, the
# content rule, taken down, an earlier "no video") never reach the list; if a stale page still sends
# one, it gets the neutral UNAVAILABLE line, never the reason (Jan, Nov 26).
UNAVAILABLE = "This story isn't available for a video."
MESSAGES = {
    "go": "Make the video",
    "has_video": "Watch the video",
    "making": "A video for this story is being made. Check back in a few minutes.",
    "closed": "New videos are paused right now.",
    "day_full": "Today's {n} videos are made. New ones from midnight, New York time.",
    "visitor_pace": "You've started {n} videos this hour. Try again in {m} minutes.",
    "busy": "{n} videos are being made right now. Try again in a few minutes.",
    "searches_low": "New videos are paused for now: this month's news searches are used up.",
    "not_eligible": UNAVAILABLE, "policy": UNAVAILABLE, "taken_down": UNAVAILABLE, "no_video": UNAVAILABLE,
    "too_many_tries": UNAVAILABLE, "too_costly": UNAVAILABLE,
}
SHOWN = ("go", "making", "has_video")     # what screen() keeps


class VideoOverBudget(RuntimeError):
    """A running video passed the per-video cap (a backstop: the estimates should prevent it)."""


class TooCostly(RuntimeError):
    """The rest of the video would pass the per-video cap; stop before spending it."""


class ClaimLost(RuntimeError):
    """This ticket's claim ran out and the event was claimed again; stop, so one event never gets two videos."""


@dataclass
class Decision:
    ok: bool
    code: str
    message: str
    detail: str = ""              # for logs and the admin side, never shown to visitors
    ticket: "Ticket | None" = None
    video: dict | None = None
    retry_after_s: int | None = None

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "ticket"}
        d["ticket"] = self.ticket.id if self.ticket else None
        return d


@dataclass
class Listing:
    event: object
    state: str                    # ready | making | has_video
    video: dict | None = None


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def safe_id(event_id: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]", "", str(event_id or ""))
    if not s:
        raise ValueError(f"bad event id {event_id!r}")
    return s[:80]


def clean_note(text: str, limit: int) -> str:
    """A viewer's report note: printable characters only, at most `limit` of them."""
    t = "".join(ch for ch in str(text or "") if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return t.strip()[:limit]


def tavily_credits_left() -> int | None:
    """Credits left on the Tavily plan (Tavily's own /usage answer; free to ask). None if unknown."""
    import requests
    from .. import keys
    try:
        r = requests.get("https://api.tavily.com/usage", timeout=10,
                         headers={"Authorization": "Bearer " + keys.get("tavily_api_key")})
        a = (r.json() or {}).get("account") or {}
        left = int(a["plan_limit"]) - int(a.get("plan_usage") or 0)
        if a.get("paygo_limit"):
            left += int(a["paygo_limit"]) - int(a.get("paygo_usage") or 0)
        return left
    except Exception:
        return None


class Gate:
    def __init__(self, store: Store | None = None, *, cfg: dict | None = None, complete=None, model: str | None = None,
                 now=None, tavily_left=tavily_credits_left, mode: str | None = None, workers: int = 8):
        self.store = store or store_from_env()
        self.cfg = cfg or rules.config()
        self.lim = self.cfg["limits"]
        self.rep = self.cfg["reports"]
        self._complete = complete
        self._model = model
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.tavily_left = tavily_left
        self._mode_given = (mode or "").strip().lower() or None
        self._mode_default = (os.environ.get("GATE_MODE") or self.lim.get("mode", "open")).strip().lower()
        self._mode_seen: tuple[float, str] | None = None
        self.workers = workers
        self._tavily_seen: tuple[float, int | None] | None = None
        self._salt: str | None = None

    # ---- small helpers ------------------------------------------------------------------------------
    MODE_KEY = "settings/mode.json"
    MODE_CHECK_S = 10

    @property
    def mode(self) -> str:
        """open or closed. A mode given to Gate(...) wins; then the admin's switch in the store (looked up at
        most every 10 s); then GATE_MODE; then config/gate.toml."""
        if self._mode_given:
            return self._mode_given
        if not self._mode_seen or time.monotonic() - self._mode_seen[0] > self.MODE_CHECK_S:
            try:
                rec, _ = self.store.get(self.MODE_KEY)
            except Exception:
                rec = None
            self._mode_seen = (time.monotonic(), str((rec or {}).get("mode") or self._mode_default).lower())
        return self._mode_seen[1]

    @mode.setter
    def mode(self, value: str) -> None:
        self._mode_given = (value or "").strip().lower() or None

    def set_mode(self, mode: str, by: str, note: str = "") -> dict:
        """The admin's pause and reopen: kept in the store, so every machine of the site sees it."""
        mode = "closed" if str(mode).strip().lower() == "closed" else "open"
        rec = {"mode": mode, "by": by, "at": _iso(self.now()), "note": clean_note(note, self.rep["note_max_chars"])}
        self.store.update(self.MODE_KEY, lambda cur: (rec, None))
        self._mode_seen = (time.monotonic(), mode)
        self._log("paused" if mode == "closed" else "opened", None, by=by, note=rec["note"])
        return rec

    @property
    def model(self) -> str:
        if self._model is None:
            from .. import models
            try:
                self._model = models.model_for("gate_policy")
            except KeyError:
                self._model = ""
        return self._model

    @property
    def complete(self):
        if self._complete is None and self.model:
            self._complete = policy.live_complete(model=self.model)
        return self._complete

    def day(self, t: dt.datetime | None = None) -> str:
        return (t or self.now()).astimezone(ZoneInfo(self.lim["day_timezone"])).date().isoformat()

    def salt(self) -> str:
        if self._salt is None:
            new = secrets.token_hex(16)
            self._salt = self.store.update("salt.json", lambda cur: (NO_CHANGE, cur["salt"]) if cur
                                           else ({"salt": new}, new))
        return self._salt

    def visitor_key(self, visitor: str) -> str:
        """Visitors are kept only as a salted hash of the cookie id or internet address the site passes."""
        return hashlib.sha256((self.salt() + "|" + str(visitor or "anonymous")).encode()).hexdigest()[:20]

    def _ekey(self, event_id: str) -> str:
        return f"events/{safe_id(event_id)}.json"

    def _log(self, kind: str, event_id: str | None = None, **detail) -> None:
        t = self.now()
        self.store.add(f"log/{self.day(t)}/{t:%Y%m%dT%H%M%S}-{time.time_ns():020d}-{secrets.token_hex(2)}.json",
                       {"kind": kind, "event": event_id, "at": _iso(t), **detail})

    def _fresh(self, ticket: dict | None) -> bool:
        beat = _parse((ticket or {}).get("beat"))
        return bool(beat) and (self.now() - beat).total_seconds() < self.lim["claim_lease_minutes"] * 60

    def _searches_low(self) -> bool:
        if self.tavily_left is None:
            return False
        if not self._tavily_seen or time.monotonic() - self._tavily_seen[0] > self.lim["tavily_check_minutes"] * 60:
            self._tavily_seen = (time.monotonic(), self.tavily_left())
        left = self._tavily_seen[1]
        return left is not None and left < self.lim["tavily_min_credits"]

    def _no(self, code: str, detail: str = "", **kw) -> Decision:
        n = {"day_full": self.lim["videos_per_day"], "busy": self.lim["at_once"],
             "visitor_pace": self.lim["per_visitor_per_hour"]}.get(code)
        m = kw.pop("minutes", None)
        return Decision(False, code, MESSAGES[code].format(n=n, m=m), detail, **kw)

    # ---- the content check, saved per event ---------------------------------------------------------
    def verdict(self, event) -> dict:
        """The content check's answer for this event, from the saved one when the event's text, the
        prompt and the model are unchanged; otherwise one check (model, else the keyword rule)."""
        eid = str(rules.field(event, "id"))
        h = policy.text_hash(event)
        rec, _ = self.store.get(self._ekey(eid))
        p = (rec or {}).get("policy")
        model = self.model if self.complete else ""
        if p and p.get("hash") == h and p.get("prompt") == policy.VERSION and (p.get("model") or "") == model:
            return p
        v = policy.judge(event, self.complete, model=model)
        p = dict(v.as_dict(), hash=h, at=_iso(self.now()))

        def put(cur):
            cur = cur or {"id": eid}
            cur["policy"] = p
            return cur, None
        self.store.update(self._ekey(eid), put)
        return p

    # ---- read-only answers --------------------------------------------------------------------------
    def _state(self, rec: dict) -> tuple[str, str]:
        """(code, detail) for an event's own record: go, has_video, making, taken_down, no_video, too_many_tries."""
        if rec.get("hidden"):
            return "taken_down", f"hidden by {rec.get('hidden_by')}"
        st = rec.get("state")
        if st == "done":
            return "has_video", ""
        if st == "making" and self._fresh(rec.get("ticket")):
            return "making", ""
        if st == "no_video":
            return "no_video", rec.get("no_video_reason") or ""
        if int(rec.get("tries") or 0) >= self.lim["max_tries"]:
            return "too_many_tries", f"{rec.get('tries')} tries"
        return "go", ""

    def check(self, event) -> Decision:
        if self.mode != "open":
            return self._no("closed")
        fails = rules.failures(event, self.cfg)
        if fails:
            return self._no("not_eligible", "fails " + ", ".join(fails))
        p = self.verdict(event)
        if p["verdict"] != "allow":
            return self._no("policy", p.get("reason", ""))
        rec, _ = self.store.get(self._ekey(str(rules.field(event, "id"))))
        code, detail = self._state(rec or {})
        if code == "go":
            return Decision(True, "go", MESSAGES["go"])
        if code == "has_video":
            return Decision(False, "has_video", MESSAGES["has_video"], video=(rec or {}).get("video"))
        return self._no(code, detail)

    def screen(self, events) -> list[Listing]:
        """The front page's list: qualifying, allowed events that are ready, being made or have a
        video, in the order given. Content checks for new events run side by side."""
        events = list(events)
        if self.mode != "open":
            return []
        todo = [e for e in events if not rules.failures(e, self.cfg)]
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as ex:
            list(ex.map(self.verdict, todo))
        out = []
        for e in todo:
            d = self.check(e)
            if d.code in SHOWN:
                out.append(Listing(e, {"go": "ready"}.get(d.code, d.code), d.video))
        return out

    def status(self) -> dict:
        """Site-wide numbers for the front page and the admin side."""
        slots, _ = self.store.get("slots.json")
        slots = self._tidy_slots(slots)
        return {"mode": self.mode, "day": self.day(), "videos_today": slots["started"],
                "videos_per_day": self.lim["videos_per_day"], "being_made": len(slots["active"]),
                "at_once": self.lim["at_once"], "searches_low": self._searches_low(),
                "estimate_usd": cost.estimate("start", cfg=self.cfg)["usd"]}

    def visitor_status(self, visitor: str) -> dict:
        """One visitor's own numbers: videos started in the last hour (and when the next is free), reports today."""
        rec, _ = self.store.get(f"visitors/{self.visitor_key(visitor)}.json")
        rec = rec or {}
        now = self.now()
        starts = [_parse(s) for s in rec.get("starts") or []]
        starts = [s for s in starts if s and (now - s).total_seconds() < 3600]
        hour = self.lim["per_visitor_per_hour"]
        wait = int(3600 - (now - min(starts)).total_seconds()) if len(starts) >= hour else 0
        r = rec.get("reports") or {}
        return {"this_hour": len(starts), "per_hour": hour, "retry_after_s": max(0, wait),
                "reports_today": int(r.get("n") or 0) if r.get("day") == self.day(now) else 0,
                "reports_per_day": self.rep["per_visitor_per_day"]}

    # ---- the click ----------------------------------------------------------------------------------
    def _tidy_slots(self, cur: dict | None) -> dict:
        cur = cur or {}
        today = self.day()
        if cur.get("day") != today:
            cur = {"day": today, "started": 0, "active": cur.get("active") or {}}
        cur["active"] = {t: a for t, a in (cur.get("active") or {}).items() if self._fresh(a)}
        return cur

    def start(self, event, visitor: str) -> Decision:
        d = self.check(event)
        if not d.ok:
            return d
        if self._searches_low():
            return self._no("searches_low")
        est = cost.estimate("start", cfg=self.cfg)
        if est["usd"] > self.lim["max_video_usd"]:
            return self._no("too_costly", f"estimate ${est['usd']:.2f} over ${self.lim['max_video_usd']:.2f}")
        eid = str(rules.field(event, "id"))
        ekey = self._ekey(eid)
        vkey = self.visitor_key(visitor)
        now = self.now()
        tid = f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"
        ticket = {"id": tid, "visitor": vkey, "started": _iso(now), "beat": _iso(now)}

        def claim(cur):
            cur = cur or {"id": eid}
            code, detail = self._state(cur)
            if code != "go":
                return NO_CHANGE, (code, detail, cur.get("video"))
            was = {k: cur.get(k) for k in ("state", "ticket", "tries")}
            if cur.get("state") == "making":          # its claim ran out: that run crashed
                cur.setdefault("history", []).append({"ticket": (cur.get("ticket") or {}).get("id"),
                                                      "outcome": "crashed (no progress)", "at": _iso(now)})
            cur.update(state="making", ticket=ticket, tries=int(cur.get("tries") or 0) + 1, before=was,
                       title=str(rules.field(event, "title") or "")[:200])
            return cur, ("go", "", None)
        code, detail, video = self.store.update(ekey, claim)
        if code != "go":
            if code == "has_video":
                return Decision(False, code, MESSAGES[code], video=video)
            return self._no(code, detail)

        def take_slot(cur):
            cur = self._tidy_slots(cur)
            if cur["started"] >= self.lim["videos_per_day"]:
                return NO_CHANGE, "day_full"
            if len(cur["active"]) >= self.lim["at_once"]:
                return NO_CHANGE, "busy"
            cur["started"] += 1
            cur["active"][tid] = {"event": eid, "started": _iso(now), "beat": _iso(now)}
            return cur, "ok"
        r = self.store.update("slots.json", take_slot)
        if r != "ok":
            self._release_claim(ekey, tid)
            return self._no(r)

        hour = self.lim["per_visitor_per_hour"]

        def take_visitor(cur):
            cur = cur or {}
            starts = [s for s in cur.get("starts") or [] if (now - _parse(s)).total_seconds() < 3600]
            if len(starts) >= hour:
                wait = 3600 - (now - _parse(min(starts))).total_seconds()
                return NO_CHANGE, max(1, int(wait))
            cur["starts"] = starts + [_iso(now)]
            return cur, 0
        wait = self.store.update(f"visitors/{vkey}.json", take_visitor)
        if wait:
            self._release_slot(tid, uncount=True)
            self._release_claim(ekey, tid)
            return self._no("visitor_pace", minutes=max(1, round(wait / 60)), retry_after_s=wait)

        self._log("start", eid, ticket=tid, visitor=vkey, estimate_usd=est["usd"])
        return Decision(True, "go", MESSAGES["go"], ticket=Ticket(self, eid, tid, est["usd"]))

    def _release_claim(self, ekey: str, tid: str) -> None:
        def undo(cur):
            if not cur or (cur.get("ticket") or {}).get("id") != tid:
                return NO_CHANGE, None
            before = cur.pop("before", {}) or {}
            cur.update(state=before.get("state"), ticket=before.get("ticket"), tries=before.get("tries") or 0)
            return cur, None
        self.store.update(ekey, undo)

    def _release_slot(self, tid: str, uncount: bool = False) -> None:
        def undo(cur):
            if not cur or tid not in (cur.get("active") or {}):
                return NO_CHANGE, None
            a = cur["active"].pop(tid)
            if uncount and cur.get("day") == self.day(_parse(a["started"])):
                cur["started"] = max(0, int(cur.get("started") or 0) - 1)
            return cur, None
        self.store.update("slots.json", undo)

    def ticket(self, event_id: str) -> "Ticket | None":
        """The running ticket for an event (for a pipeline that runs apart from the click)."""
        rec, _ = self.store.get(self._ekey(event_id))
        t = (rec or {}).get("ticket")
        if not rec or rec.get("state") != "making" or not t:
            return None
        tk = Ticket(self, event_id, t["id"], 0.0)
        tk.spent = float(t.get("spent") or 0.0)
        return tk

    # ---- reports and the admin side -----------------------------------------------------------------
    def report(self, event_id: str, visitor: str, reason: str, note: str = "") -> dict:
        """A viewer's report. Saved with its note, logged; the first one hides the video until Jan looks
        (unless Jan restored it with keep_up). Each visitor can send 5 a day."""
        eid = safe_id(event_id)
        vkey = self.visitor_key(visitor)
        now = self.now()
        today = self.day(now)
        reason = reason if reason in self.rep["reasons"] else "other"
        note = clean_note(note, self.rep["note_max_chars"])
        limit = self.rep["per_visitor_per_day"]

        def count(cur):
            cur = cur or {}
            r = cur.get("reports") or {}
            n = r.get("n", 0) if r.get("day") == today else 0
            if n >= limit:
                return NO_CHANGE, False
            cur["reports"] = {"day": today, "n": n + 1}
            return cur, True
        if not self.store.update(f"visitors/{vkey}.json", count):
            return {"ok": False, "code": "report_limit", "message": "You've sent the most reports for today. Thanks for helping."}
        rid = f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"
        self.store.add(f"reports/{eid}/{rid}.json", {"id": rid, "event": eid, "visitor": vkey, "reason": reason,
                                                     "note": note, "at": _iso(now)})

        def mark(cur):
            cur = cur or {"id": eid}
            cur["reports"] = int(cur.get("reports") or 0) + 1
            cur["reports_since_review"] = int(cur.get("reports_since_review") or 0) + 1
            hide = (not cur.get("hidden") and not cur.get("keep_up")
                    and cur["reports_since_review"] >= self.rep["hide_after"])
            if hide:
                cur.update(hidden=True, hidden_by="reports", hidden_at=_iso(now))
            return cur, hide
        hid = self.store.update(self._ekey(eid), mark)
        self._log("report", eid, report=rid, reason=reason, visitor=vkey, note=note)
        if hid:
            self._log("hidden", eid, by="reports", report=rid)
        return {"ok": True, "code": "reported", "hidden": hid, "message": "Thanks. We'll take a look."}

    def _admin_set(self, event_id: str, kind: str, by: str, note: str, change) -> dict:
        eid = safe_id(event_id)

        def apply(cur):
            cur = cur or {"id": eid}
            change(cur)
            return cur, cur
        rec = self.store.update(self._ekey(eid), apply)
        self._log(kind, eid, by=by, note=clean_note(note, self.rep["note_max_chars"]))
        return rec

    def take_down(self, event_id: str, by: str, note: str = "") -> dict:
        """Hide a video now; the story can't be made again until restored."""
        now = _iso(self.now())
        return self._admin_set(event_id, "taken_down", by, note,
                               lambda c: c.update(hidden=True, hidden_by=by, hidden_at=now, keep_up=False))

    def restore(self, event_id: str, by: str, note: str = "", keep_up: bool = False) -> dict:
        """Show a hidden video again. keep_up: later reports are still saved but don't hide it."""
        return self._admin_set(event_id, "restored", by, note,
                               lambda c: c.update(hidden=False, hidden_by=None, keep_up=bool(keep_up),
                                                  reports_since_review=0))

    def remake(self, event_id: str, by: str, note: str = "") -> dict:
        """Let an event be made again (Jan only): clears its video, "no video" and tries. A video hidden by
        reports goes too: its old video is gone, so the hide has nothing left to hide."""
        def change(c):
            c.setdefault("history", []).append({"outcome": f"reset for a remake by {by}", "at": _iso(self.now()),
                                                "video": c.get("video")})
            c.update(state=None, ticket=None, tries=0, video=None, no_video_reason=None, hidden=False, hidden_by=None,
                     keep_up=False, reports_since_review=0)
        return self._admin_set(event_id, "remake", by, note, change)

    def reports(self, event_id: str | None = None) -> list[dict]:
        keys = self.store.list(f"reports/{safe_id(event_id)}/" if event_id else "reports/")
        return sorted((self.store.get(k)[0] for k in keys), key=lambda r: r["at"], reverse=True)

    def hidden(self) -> list[dict]:
        recs = (self.store.get(k)[0] for k in self.store.list("events/"))
        return [r for r in recs if r and r.get("hidden")]

    def log(self, day: str | None = None) -> list[dict]:
        keys = self.store.list(f"log/{day or self.day()}/")
        return [self.store.get(k)[0] for k in keys]


@dataclass
class Ticket:
    """One video's permission to run: what it has spent, and the way to stop it in time."""
    gate: Gate
    event_id: str
    id: str
    estimate_usd: float
    spent: float = 0.0
    parts: dict = field(default_factory=dict)
    _last_beat: float = field(default_factory=time.monotonic)

    @property
    def cap(self) -> float:
        return float(self.gate.lim["max_video_usd"])

    def charge(self, usd: float, what: str = "") -> None:
        usd = max(0.0, float(usd or 0.0))
        self.spent += usd
        if what:
            self.parts[what] = self.parts.get(what, 0.0) + usd
        if self.spent > self.cap:
            raise VideoOverBudget(f"spent ${self.spent:.2f}, over the ${self.cap:.2f} cap")
        if time.monotonic() - self._last_beat >= self.gate.lim["beat_seconds"]:
            self.beat()

    def wrap(self, complete):
        """A complete() that charges each call's cost to this ticket (models.complete's signature)."""
        def charged(*a, **kw):
            r = complete(*a, **kw)
            self.charge((getattr(r, "cost", None) or {}).get("total", 0.0), kw.get("name") or "model")
            return r
        return charged

    def checkpoint(self, stage: str = "after_gather", n_articles: int | None = None) -> dict:
        """After the searches: will the rest fit under the cap? Raises TooCostly before it's spent."""
        est = cost.estimate(stage, n_articles, cfg=self.gate.cfg)
        if self.spent + est["usd"] > self.cap:
            raise TooCostly(f"spent ${self.spent:.2f} + ${est['usd']:.2f} still to come is over ${self.cap:.2f}")
        self.beat()
        return est

    def beat(self) -> None:
        """Tell the Gate this video is still alive. Raises ClaimLost if the claim was taken over."""
        g, now = self.gate, _iso(self.gate.now())
        self._last_beat = time.monotonic()

        def ev(cur):
            if not cur or (cur.get("ticket") or {}).get("id") != self.id or cur.get("state") != "making":
                return NO_CHANGE, False
            cur["ticket"].update(beat=now, spent=round(self.spent, 6))
            return cur, True
        if not g.store.update(g._ekey(self.event_id), ev):
            raise ClaimLost(f"{self.event_id}: ticket {self.id} no longer holds the claim")

        def sl(cur):
            if not cur or self.id not in (cur.get("active") or {}):
                return NO_CHANGE, None
            cur["active"][self.id]["beat"] = now
            return cur, None
        g.store.update("slots.json", sl)

    def finish(self, *, video: dict | None = None, no_video: str | None = None, error: str | None = None) -> dict:
        """The video is done (video), the pipeline decided against it (no_video: final), or it crashed
        (error: a later click may try again, up to max_tries)."""
        g = self.gate
        g_now = g.now()
        outcome = "done" if video is not None else ("no_video" if no_video else "failed")

        def ev(cur):
            if not cur or (cur.get("ticket") or {}).get("id") != self.id:
                return NO_CHANGE, False
            cur.pop("before", None)
            cur.update(state=outcome, ticket=None, spent_usd=round(float(cur.get("spent_usd") or 0) + self.spent, 6))
            if video is not None:
                cur["video"] = dict(video, made_at=_iso(g_now))
            if no_video:
                cur["no_video_reason"] = str(no_video)[:500]
            cur.setdefault("history", []).append({"ticket": self.id, "outcome": outcome, "spent_usd": round(self.spent, 6),
                                                  "at": _iso(g_now), "error": (str(error)[:300] if error else None)})
            return cur, True
        owned = g.store.update(g._ekey(self.event_id), ev)
        g._release_slot(self.id)
        day = g.day(g_now)

        def led(cur):
            cur = cur or {"day": day, "videos": [], "spent_usd": 0.0}
            cur["videos"].append({"event": self.event_id, "ticket": self.id, "outcome": outcome,
                                  "spent_usd": round(self.spent, 6), "parts": {k: round(v, 6) for k, v in self.parts.items()}})
            cur["spent_usd"] = round(float(cur["spent_usd"]) + self.spent, 6)
            return cur, None
        g.store.update(f"days/{day}.json", led)
        g._log("video_" + outcome, self.event_id, ticket=self.id, spent_usd=round(self.spent, 6),
               reason=(no_video or error or None), stale=not owned)
        return {"outcome": outcome, "spent_usd": round(self.spent, 6), "owned": owned}
