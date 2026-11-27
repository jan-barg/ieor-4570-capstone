"""The website on the Mac with no paid calls: a Gate store and a saved feed built from runs already made.

    python -m scripts.local_site <folder>                       # <folder>/gate and <folder>/feed.json
    GATE_STORE=<folder>/gate python -m web.server --feed <folder>/feed.json --no-model --port 8080

    python -m scripts.local_site <folder> --live <event-id8> --speed 10
        replays that recorded run as if it were being made right now: the event is "being made", and its
        progress record (progress/<event>/<ticket>.json) fills in step by step at the recorded times (10x
        faster here), with the model calls from the call log. The progress page shows it live.

The recorded runs are the story folders in stringer_private/live/stories/ (pipeline.json and the step files),
so the feed and the store hold real Monitor the Situation events: they stay in the folder you name, which
should be outside the repo. Three made-up events are added, ready for a video. Nothing here calls a model,
Tavily or ElevenLabs; the content check is the keyword rule (the site's --no-model)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

from stringer import paths
from stringer import progress as P
from stringer.gate import Gate, LocalStore

from stringer.gate.core import safe_id

STORIES = paths.PRIVATE / "live" / "stories"
MADE_UP = [   # invented events, in the feed's plain wire style (none of this is real)
    {"id": "00000000-0000-4000-8000-0000000000a1", "title": "Landslide blocks main highway in the Gorkha district",
     "summary": "Made up for the local site.", "category": "disaster", "subtype": "landslide", "severity": 3,
     "confidence": 60, "country": "Nepal", "region": "Asia", "location_name": "Gorkha", "report_count": 12},
    {"id": "00000000-0000-4000-8000-0000000000a2", "title": "Electoral commission delays count in local elections",
     "summary": "Made up for the local site.", "category": "political", "subtype": "election", "severity": 2,
     "confidence": 75, "country": "Malawi", "region": "Africa", "location_name": "Lilongwe", "report_count": 8},
    {"id": "00000000-0000-4000-8000-0000000000a3", "title": "Port workers strike for a third day over night shifts",
     "summary": "Made up for the local site.", "category": "economic", "subtype": "labour strike", "severity": 2,
     "confidence": 65, "country": "Belgium", "region": "Europe", "location_name": "Antwerp", "report_count": 15},
]


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def recorded() -> list[tuple[Path, dict]]:
    out = []
    for d in sorted(STORIES.glob("*/pipeline.json")):
        out.append((d.parent, json.loads(d.read_text(encoding="utf-8"))))
    return out


def feed_event(d: Path, now: dt.datetime) -> dict:
    ev = dict(json.loads((d / "gather.json").read_text(encoding="utf-8"))["event"])
    for k in ("severity", "confidence", "report_count", "lat", "lng"):
        try:
            ev[k] = float(ev[k]) if k in ("lat", "lng") else int(float(ev[k]))
        except (KeyError, TypeError, ValueError):
            pass
    ev.setdefault("updated_at", ev.get("created_at"))
    ev.pop("source_urls", None)
    return ev


def seed(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    gate_dir = folder / "gate"
    if gate_dir.exists():
        shutil.rmtree(gate_dir)
    store = LocalStore(gate_dir)
    g = Gate(store, complete=None, model="", tavily_left=None)
    now = dt.datetime.now(dt.timezone.utc)
    feed = []
    for i, (d, pl) in enumerate(recorded()):
        ev = feed_event(d, now)
        ev["updated_at"] = _iso(now - dt.timedelta(minutes=7 + 23 * i))
        feed.append(ev)
        g.verdict(ev)                                   # the keyword rule's answer, saved like the site saves it
        tid = f"rec-{str(pl['event'])[:8]}"
        made = now - dt.timedelta(hours=1 + 5 * i)
        rec, _ = store.get(f"events/{safe_id(ev['id'])}.json")
        rec = dict(rec or {"id": ev["id"]}, title=ev["title"], tries=1, ticket=None, spent_usd=pl.get("usd"))
        if pl.get("outcome") == "done":
            rec.update(state="done", video={"duration_s": (pl.get("video") or {}).get("duration_s"), "status": "rendered",
                                            "seconds": pl.get("seconds"), "usd": pl.get("usd"), "made_at": _iso(made)})
        else:
            rec.update(state="no_video", no_video_reason=pl.get("why"))
        rec["history"] = [{"ticket": tid, "outcome": rec["state"], "spent_usd": pl.get("usd"), "at": _iso(made)}]
        store.update(f"events/{safe_id(ev['id'])}.json", lambda cur, rec=rec: (rec, None))
        store.update(f"raw_events/{safe_id(ev['id'])}.json", lambda cur, ev=ev: (ev, None))
        day = g.day(made)

        def led(cur, pl=pl, tid=tid, ev=ev, rec=rec):
            cur = cur or {"day": day, "videos": [], "spent_usd": 0.0}
            cur["videos"].append({"event": ev["id"], "ticket": tid, "outcome": rec["state"], "spent_usd": pl.get("usd"),
                                  "parts": {k: v.get("usd") for k, v in (pl.get("steps") or {}).items()}})
            cur["spent_usd"] = round(float(cur["spent_usd"]) + float(pl.get("usd") or 0), 6)
            return cur, None
        store.update(f"days/{day}.json", led)
    for j, e in enumerate(MADE_UP):
        e = dict(e, created_at=_iso(now - dt.timedelta(hours=2 + j)), updated_at=_iso(now - dt.timedelta(minutes=12 + 30 * j)))
        feed.append(e)
    (folder / "feed.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    return gate_dir, folder / "feed.json"


def calls_from_log(pl: dict) -> list[dict]:
    """The run's model calls from the Mac's call log (stringer_private/runs/calls-<day>.jsonl), by time."""
    t0 = dt.datetime.fromisoformat(pl["started"].replace("Z", "+00:00"))
    t1 = dt.datetime.fromisoformat(pl["finished"].replace("Z", "+00:00"))
    out = []
    for day in {t0.date(), t1.date()}:
        f = paths.RUNS / f"calls-{day.isoformat()}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") != "generation" or str(r.get("name") or "").startswith(("gate_policy", "eval")):
                continue
            ts = dt.datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
            if not (t0 <= ts <= t1):
                continue
            u = r.get("usage") or {}
            out.append({"t": round((ts - t0).total_seconds(), 2), "name": r.get("name"), "model": r.get("model"),
                        "usd": (r.get("cost_usd") or {}).get("total") or 0.0, "tokens_in": u.get("prompt") or 0,
                        "tokens_out": u.get("output") or 0, "seconds": r.get("latency_s") or 0.0,
                        "error": bool(r.get("error"))})
    return sorted(out, key=lambda c: c["t"])


def live(folder: Path, prefix: str, speed: float, say=print) -> None:
    """Replay one recorded run into the store as if it were running now."""
    hits = [(d, pl) for d, pl in recorded() if str(pl["event"]).startswith(prefix)]
    if len(hits) != 1:
        sys.exit(f"{prefix}: {len(hits)} recorded runs match")
    d, pl = hits[0]
    store = LocalStore(folder / "gate")
    g = Gate(store, complete=None, model="", tavily_left=None)
    eid = pl["event"]
    now = dt.datetime.now(dt.timezone.utc)
    tid = f"{now:%Y%m%dT%H%M%S}-replay"
    ticket = {"id": tid, "visitor": g.visitor_key("local-replay"), "started": _iso(now), "beat": _iso(now)}
    prev, _ = store.get(f"events/{safe_id(eid)}.json")

    def claim(cur):
        cur = dict(cur or {"id": eid})
        cur.update(state="making", ticket=ticket, video=None, no_video_reason=None)
        return cur, None
    store.update(f"events/{safe_id(eid)}.json", claim)
    read = P.folder_reader(d)
    calls = calls_from_log(pl)
    prog = P.Progress(store, eid, tid, title=pl.get("title"), interval=0.5)
    clock0 = time.time()

    def wait_until(t_run: float) -> None:          # run time -> wall time at this speed
        left = clock0 + t_run / speed - time.time()
        if left > 0:
            time.sleep(left)
    t, ci = 0.0, 0
    for k in P.KEYS:
        row = (pl.get("steps") or {}).get(k)
        if not row:
            continue
        wait_until(t)
        prog.begin(k)
        say(f"  {k:<12} starts at {t:6.1f} s")
        end = t + float(row.get("seconds") or 0)
        while ci < len(calls) and calls[ci]["t"] <= end:
            wait_until(calls[ci]["t"])
            prog.call(calls[ci])
            ci += 1
        wait_until(end)
        info = dict(row)
        if k == "video":
            info["duration_s"] = (pl.get("video") or {}).get("duration_s")
        prog.end(k, row, hands_on=P.summarize(k, read, info), searches=P.searches_of(read) if k == "gather" else None)
        t = end
    prog.finish(pl.get("outcome"), pl.get("why"), seconds=pl.get("seconds"), usd=pl.get("usd"))

    def done(cur):
        cur = dict(cur or {"id": eid})
        base = prev or {}
        cur.update(state=base.get("state") or pl.get("outcome"), ticket=None, video=base.get("video"),
                   no_video_reason=base.get("no_video_reason"))
        cur.setdefault("history", []).append({"ticket": tid, "outcome": cur["state"], "spent_usd": pl.get("usd"),
                                              "at": _iso(dt.datetime.now(dt.timezone.utc))})
        if cur.get("video"):
            cur["video"] = dict(cur["video"], made_at=_iso(dt.datetime.now(dt.timezone.utc)))
        return cur, None
    store.update(f"events/{safe_id(eid)}.json", done)
    say(f"done: {pl.get('outcome')} after {pl.get('seconds')} s of run time")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--live", help="replay this recorded run (event id or its start) as if it were being made now")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args(argv)
    if a.live:
        live(a.folder, a.live, a.speed)
        return 0
    gate_dir, feed = seed(a.folder)
    print(f"store {gate_dir}\nfeed  {feed}\n\nGATE_STORE={gate_dir} python -m web.server --feed {feed} --no-model --port 8080")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
