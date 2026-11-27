"""Runs module 8's evals over the frozen stories (stringer/video/evals.py explains each one), then writes
the results and the visual report.

    python scripts/eval_video.py                       # all of it (about 10 minutes on the Mac)
    python scripts/eval_video.py --no-layout --broken-renders 0      # code checks only, about a minute
    python scripts/eval_video.py --report-only <run json>            # rebuild the report from saved results

Needs each story's video/ folder (scripts/make_videos.py). Results go to stringer_private/evals/video/
(private: they quote the stories); the report is stringer_private/evals/video_report.html.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stringer import paths  # noqa: E402
from stringer.video import check, eval_report, evals, make, places, render  # noqa: E402

OUT = paths.PRIVATE / "evals" / "video"
REPORT = paths.PRIVATE / "evals" / "video_report.html"
PER_MUTATION = 11          # 20 kinds x up to 11 stories = about 200 broken scripts


def story_dirs() -> list[Path]:
    return sorted(d for d in paths.STORIES.iterdir() if (d / "script.json").exists())


def per_story(d: Path, g) -> dict:
    script, sf, p7 = make.inputs(d)
    event = sf["event"]
    vd = d / "video"
    row = dict(id=d.name, id8=d.name[:8], title=script.get("title") or "", status="", why="")
    stop = check.check_script(script, p7)["stop"]
    if stop:
        return dict(row, status="stopped", why=stop)
    if not (vd / "plan.json").exists() or not (vd / "render.json").exists():
        return dict(row, status="missing", why="no video made yet")
    pl = json.loads((vd / "plan.json").read_text(encoding="utf-8"))
    rec = json.loads((vd / "render.json").read_text(encoding="utf-8"))
    row.update(status=rec.get("status") or "rendered", shots=[b["shot"] for b in pl["beats"]],
               on_screen=evals.on_screen(pl, p7), required=evals.required(pl, script), sync=evals.sync(pl),
               maps=evals.maps(pl, event, g), shot_choice=evals.shot_choice(pl), cost=evals.cost(rec),
               speed=evals.speed(rec), format=evals.fmt(rec, pl, vd / "video.mp4"),
               broll=[dict(beat=b["n"], **{k: v for k, v in (b.get("broll") or {}).items() if k != "portrait"})
                      for b in pl["beats"] if (b.get("broll") or {}).get("kind") not in (None, "none")])
    return row


def broken_scripts(dirs: list[Path], g, n_renders: int) -> dict:
    rnd = random.Random(8)
    cache = OUT / "broken" / "voice"
    loaded, bases = {}, {}
    for d in dirs:
        script, sf, p7 = make.inputs(d)
        b = evals.baseline(script, p7, sf["event"], g, cache)
        if not b["stop"]:
            loaded[d.name], bases[d.name] = (script, sf["event"], p7), b
    results, plans = [], []
    for name, fn, expected in evals.MUTATIONS:
        ids = list(loaded)
        rnd.shuffle(ids)
        made = 0
        for sid in ids:
            if made >= PER_MUTATION:
                break
            script, event, p7 = loaded[sid]
            s = fn(json.loads(json.dumps(script)), rnd)
            if s is None:
                continue
            made += 1
            actual, pl, detail = evals.outcome(s, p7, event, bases[sid], g, cache)
            results.append(dict(kind=name, story=sid[:8], expected=expected, actual=actual, detail=detail[:300]))
            if pl is not None:
                plans.append((name, sid[:8], pl))
    # Some of the handled ones are drawn too, one still per beat, so the drawing code meets them as well.
    drawn = []
    picks, seen = [], set()
    for name, sid, pl in plans:                                   # one per kind first, then the rest
        if name not in seen:
            picks.append((name, sid, pl))
            seen.add(name)
    picks += [x for x in plans if x not in picks]
    for i, (name, sid, pl) in enumerate(picks[:n_renders]):
        folder = OUT / "broken" / f"{i:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.json").write_text(json.dumps(pl, ensure_ascii=False), encoding="utf-8")
        try:
            r = render.render(folder / "plan.json", folder, folder / "stills", mode="stills", extra=("--frames", "auto"))
            drawn.append(dict(kind=name, story=sid, ok=not r.get("browser_errors"), errors=r.get("browser_errors") or []))
        except Exception as e:                                         # noqa: BLE001 - a failure is the finding
            drawn.append(dict(kind=name, story=sid, ok=False, errors=[f"{type(e).__name__}: {str(e)[:300]}"]))
    return dict(results=results, confusion=evals.confusion(results), drawn=drawn)


def layout_one(d: Path) -> dict:
    vd = d / "video"
    pl = json.loads((vd / "plan.json").read_text(encoding="utf-8"))
    folder = OUT / "layout" / d.name[:8]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.json").write_text(json.dumps(dict(pl, debug_layout=True), ensure_ascii=False), encoding="utf-8")
    try:
        r = render.render(folder / "plan.json", vd, folder / "stills", mode="stills", extra=("--frames", "auto"))
        return dict(id8=d.name[:8], frames=r.get("layout") or [], errors=r.get("browser_errors") or [])
    except Exception as e:                                             # noqa: BLE001
        return dict(id8=d.name[:8], frames=[], errors=[f"{type(e).__name__}: {str(e)[:300]}"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-layout", action="store_true")
    ap.add_argument("--broken-renders", type=int, default=20)
    ap.add_argument("--report-only", type=Path)
    a = ap.parse_args()
    if a.report_only:
        run = json.loads(a.report_only.read_text(encoding="utf-8"))
        eval_report.write(run, REPORT)
        print(REPORT)
        return
    t0 = time.time()
    g = places.default()
    dirs = story_dirs()
    with ThreadPoolExecutor(4) as pool:                       # the flash check decodes every video
        stories = list(pool.map(lambda d: per_story(d, g), dirs))
    print(f"stories checked in {time.time() - t0:.0f} s", flush=True)
    t1 = time.time()
    broken = broken_scripts(dirs, g, a.broken_renders)
    print(f"broken scripts in {time.time() - t1:.0f} s", flush=True)
    layout = []
    if not a.no_layout:
        t2 = time.time()
        made = [d for d in dirs if (d / "video" / "plan.json").exists() and (d / "video" / "render.json").exists()]
        with ThreadPoolExecutor(3) as pool:
            layout = list(pool.map(layout_one, made))
        print(f"layout stills in {time.time() - t2:.0f} s", flush=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = dict(run=stamp, seconds=round(time.time() - t0, 1), stories=stories, broken=broken, layout=layout,
               bars=dict(speed_p95_s=evals.SPEED_P95_S, swap_rate_max=evals.SWAP_RATE_MAX, sync_ms=[evals.SYNC_SHOT_MS,
                         evals.SYNC_MARK_MS, evals.SYNC_CAPTION_MS], length_s=evals.LENGTH_S, cost_max_usd=evals.COST_MAX_USD,
                         safe_area=evals.LAYOUT_SAFE, min_px=evals.LAYOUT_MIN_PX))
    evals.save(run, OUT / f"run-{stamp}.json")
    eval_report.write(run, REPORT)
    print(OUT / f"run-{stamp}.json")
    print(REPORT)


if __name__ == "__main__":
    main()
