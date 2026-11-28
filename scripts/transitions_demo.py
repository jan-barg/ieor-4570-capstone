"""Transitions between beats, shown on videos the A/B already made: no model call, no voice call, nothing paid.

For each story, one saved arm of the A/B (<ab>/<id>/<arm>/: its plan.json, narration, music bed and animation frames)
is copied, its plan given transitions (stringer/video/transitions.py) and drawn again; the version with cuts is the
saved video itself, so the two differ only in how beats give way to each other. Out, in --out:
  <id>/<style>/video.mp4            the video with that style of transitions
  <id>/<style>/side_by_side.mp4     the saved video (cuts) on the left, this one on the right, the same sound
  <id>/<style>/strips/*.jpg         stills across each change, one strip per change
  transitions.json, report.html     what was made, the flash check on both versions, and the page to look at it

    python scripts/transitions_demo.py --ab <A/B folder> --out <folder> --stories <id>,<id> --arm B-card
    python scripts/transitions_demo.py ... --kinds-story <id> --kinds-arm A      # each kind across one story
    python scripts/transitions_demo.py ... --left-arm A --title "Final videos"          # today's video on the left
    python scripts/transitions_demo.py ... --report                                   # the page again, nothing drawn
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stringer.video import evals, files, render as render_step, transitions as tx  # noqa: E402

STRIP_AT = (-1, 0.15, 0.35, 0.55, 0.75, 0.92)        # where in a change the strip's stills fall (-1: the frame before)


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def styled_plan(src: Path, style: str) -> dict:
    pl = json.loads((src / "plan.json").read_text())
    for b in pl["beats"]:
        b.pop("enter", None)
    pl.pop("transitions", None)
    note = tx.add(pl["beats"], style)
    if note:
        pl["transitions"] = note
    return pl


def draw(src: Path, dst: Path, style: str) -> dict:
    """The saved arm `src` drawn again into `dst` with `style` transitions. Returns its record."""
    dst.mkdir(parents=True, exist_ok=True)
    pl = styled_plan(src, style)
    for name in [pl["audio"].get("voice"), pl["audio"].get("music")]:
        if name:
            shutil.copyfile(src / name, dst / name)
    for b in pl["beats"]:
        if b.get("anim") and not (dst / b["anim"]["dir"]).exists():
            shutil.copytree(src / b["anim"]["dir"], dst / b["anim"]["dir"])
    (dst / "plan.json").write_text(json.dumps(pl, ensure_ascii=False))
    t = time.time()
    r = render_step.render(dst / "plan.json", dst, dst / "render.mp4")
    rec = files.finish(dst / "render.mp4", pl, dst, dict(status="rendered", source=str(src), style=style,
                                                       render=dict(r, seconds=round(time.time() - t, 1))))
    return rec


def strips(dst: Path, src: Path) -> list[dict]:
    """Stills across each change of dst's plan, one strip per change (beat n, kind, file)."""
    pl = json.loads((dst / "plan.json").read_text())
    rows = []
    for b in pl["beats"][1:]:
        e = b.get("enter")
        if not e:
            continue
        first = b["start"] - e["pre"]
        at = [first - 1] + [first + round(e["frames"] * q) for q in STRIP_AT[1:]] + [first + e["frames"] + 2]
        rows.append(dict(n=b["n"], kind=e["kind"], frames=at))
    if not rows:
        return []
    want = sorted({f for r in rows for f in r["frames"]})
    folder = dst / "strip-stills"
    r = render_step.render(dst / "plan.json", dst, folder, mode="stills", extra=["--frames", ",".join(map(str, want))])
    by = {int(Path(f).stem.split("-")[-1]): f for f in r["files"]}
    (dst / "strips").mkdir(exist_ok=True)
    for row in rows:
        ins = sum([["-i", by[f]] for f in row["frames"]], [])
        k = len(row["frames"])
        graph = "".join(f"[{i}:v]scale=216:384,pad=222:384:0:0:white[s{i}];" for i in range(k)) + \
            "".join(f"[s{i}]" for i in range(k)) + f"hstack={k}"
        dest = dst / "strips" / f"beat{row['n']}-{row['kind']}.jpg"
        sh(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", graph, "-frames:v", "1", "-update", "1", str(dest)])
        row["file"] = str(dest.relative_to(dst))
    shutil.rmtree(folder, ignore_errors=True)
    return rows


def side_by_side(left: Path, right: Path, dest: Path) -> str:
    graph = "[0:v]scale=540:960[a];[1:v]scale=540:960[b];[a][b]hstack=2[v]"
    r = sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(left), "-i", str(right), "-filter_complex", graph,
            "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-crf", "24", "-preset", "veryfast", "-c:a", "aac",
            "-b:a", "128k", "-shortest", str(dest)])
    return "" if r.returncode == 0 and dest.exists() else (r.stderr or "ffmpeg failed")[-300:]


def one(ab: Path, out: Path, story: str, arm: str, style: str, left_arm: str | None = None) -> dict:
    src = ab / story / arm
    left = ab / story / (left_arm or arm) / "video.mp4"
    dst = out / story / style
    print(f"[{story}] {arm} + {style}", flush=True)
    rec = draw(src, dst, style)
    rows = strips(dst, src)
    err = side_by_side(left, dst / "video.mp4", dst / "side_by_side.mp4")
    pl = json.loads((dst / "plan.json").read_text())
    changes = [dict(n=b["n"], from_shot=a["shot"], to_shot=b["shot"], kind=(b.get("enter") or {}).get("kind") or "cut")
               for a, b in zip(pl["beats"], pl["beats"][1:])]
    return dict(story=story, arm=arm, left_arm=left_arm or arm, style=style, changes=changes, strips=rows, side_by_side_error=err,
                render_seconds=rec["render"]["seconds"], problems=rec.get("problems"),
                flashes=dict(cuts=evals.flashes(evals.brightness(left)),
                             transitions=evals.flashes(evals.brightness(dst / "video.mp4"))))


# ---- the page ------------------------------------------------------------------------------------------------

NOTES = {
    "dissolve": "the new picture fades in over the old",
    "slide": "a new sheet slides in from the right over the old, which drifts left and dims a little",
    "push": "both move left together, as if the camera travelled along one long sheet",
    "tear": "the old sheet is torn away to the left along a ragged edge; the new one is underneath",
    "wipe": "a vermilion band sweeps left to right; the new picture is behind it",
}
RULE = [("out of the opening (hook)", "tear", "the cover is torn open: the story starts"),
        ("into the sides card", "slide", "a new sheet: how each side tells it"),
        ("into the sources card", "dissolve", "a quiet close"),
        ("map to map", "push", "on to the next place"),
        ("map to card, card to map", "dissolve", "the picture changes kind"),
        ("card to card", "cut", "keeps the pace through a run of facts"),
        ("next to a beat under 1.5 s", "cut", "no room to move")]


def page(out: Path, runs: list[dict], titles: dict, title: str = "Beat transitions") -> str:
    esc = lambda x: html.escape(str(x))                       # noqa: E731
    H = [f"<!doctype html><meta charset=utf-8><title>{esc(title)}</title><style>",
         "body{font:15px/1.5 -apple-system,system-ui,sans-serif;margin:24px auto;max-width:1200px;padding:0 16px;color:#1A2A86;background:#F3EEE1}",
         "h1{font-size:26px;margin:0 0 4px}h2{margin:36px 0 8px;font-size:20px}h3{margin:20px 0 6px;font-size:16px}",
         ".lede{max-width:820px}table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #c9c1aa;padding:4px 8px;text-align:left;vertical-align:top}",
         "img{max-width:100%;display:block;margin:4px 0 12px;border:1px solid #c9c1aa}video{width:100%;max-width:1080px;background:#000}",
         ".mono{font-family:ui-monospace,Menlo,monospace;font-size:13px}.k{font-weight:600}.small{font-size:13px;color:#47507f}</style>",
         f"<h1>{esc(title)}</h1>",
         "<p class=lede>How one beat's picture gives way to the next. The mix below is on by default (Jan's OK, Nov 28); "
         "<span class=mono>STRINGER_TRANSITIONS=off</span> makes every change a cut; a kind's name "
         "(<span class=mono>dissolve</span>, <span class=mono>slide</span>, <span class=mono>push</span>, "
         "<span class=mono>tear</span>, <span class=mono>wipe</span>) puts that kind at every change. Each change starts a "
         "third of its length before the next line's first word, in the pause. The videos here are the A/B's saved videos drawn "
         "again with transitions: same words, voice, captions and pictures, nothing paid.</p>",
         "<h2>The mix: when each kind is used</h2><table><tr><th>Change</th><th>Kind</th><th>Why</th></tr>"]
    H += [f"<tr><td>{esc(a)}</td><td class=k>{esc(k)}</td><td>{esc(w)}</td></tr>" for a, k, w in RULE]
    H.append("</table>")
    kinds = [r for r in runs if r["style"] in tx.KINDS]
    if kinds:
        H.append("<h2>Each kind on its own</h2><p class=lede>One story, the same kind at every change. Each strip runs "
                 "left to right across one change: the frame before it, five frames during it, a frame after it.</p>")
        for r in kinds:
            s = r["strips"][0] if r["strips"] else None
            H.append(f"<h3>{esc(r['style'])}: {esc(NOTES.get(r['style'], ''))} "
                     f"<span class=small>({tx.KINDS[r['style']]} frames, {tx.KINDS[r['style']] / 30:.2f} s)</span></h3>")
            if s:
                H.append(f"<img src='{esc(r['story'])}/{esc(r['style'])}/{esc(s['file'])}' loading=lazy>")
            H.append(f"<p class=small>Whole video: <a href='{esc(r['story'])}/{esc(r['style'])}/video.mp4'>video.mp4</a> · "
                     f"with the cut version beside it: <a href='{esc(r['story'])}/{esc(r['style'])}/side_by_side.mp4'>side_by_side.mp4</a></p>")
    mixes = [r for r in runs if r["style"] == "mix"]
    if mixes:
        today = all(r.get("left_arm") == "A" for r in mixes)
        H.append("<h2>The mix on each story</h2><p class=lede>"
                 + ("Left: the video as it is today (no animation, cuts). Right: the same script and voice with the "
                    "animation (card look) and the mix of transitions. " if today else
                    "Left: the saved video, with cuts. Right: the same video with the mix. ")
                 + "Flashes: the most big opposite brightness changes in any one second (the format check allows 3).</p>")
        for r in mixes:
            base = f"{esc(r['story'])}/mix"
            H.append(f"<h3>{esc(titles.get(r['story'], r['story']))} <span class=small>({esc(r['story'])}, "
                     f"{esc(r['arm'])})</span></h3>")
            H.append(f"<video controls preload=metadata src='{base}/side_by_side.mp4'></video>")
            H.append("<table><tr><th>Into beat</th><th>From</th><th>To</th><th>Kind</th></tr>")
            H += [f"<tr><td>{c['n']}</td><td>{esc(c['from_shot'])}</td><td>{esc(c['to_shot'])}</td>"
                  f"<td class=k>{esc(c['kind'])}</td></tr>" for c in r["changes"]]
            H.append(f"</table><p class=small>Flashes per second, left {r['flashes']['cuts']}, right "
                     f"{r['flashes']['transitions']}. Problems from the format check: {esc(r['problems'] or 'none')}.</p>")
            for s in r["strips"]:
                H.append(f"<p class=small>Into beat {s['n']}: {esc(s['kind'])}</p><img src='{base}/{esc(s['file'])}' loading=lazy>")
    path = out / "report.html"
    path.write_text("\n".join(H), encoding="utf-8")
    return str(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ab", type=Path, required=True, help="the A/B folder (one folder per story, one per arm)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stories", default="", help="story ids (8 characters), comma-separated, for the mix")
    ap.add_argument("--arm", default="B-card", help="which saved arm the mix is drawn on (A, B-card, ...)")
    ap.add_argument("--kinds-story", default="", help="a story to draw with each kind at every change")
    ap.add_argument("--kinds-arm", default="A")
    ap.add_argument("--left-arm", default=None, help="the saved arm shown on the left of each side by side (default: --arm)")
    ap.add_argument("--title", default="Beat transitions")
    ap.add_argument("--report", action="store_true", help="only write the page again from transitions.json")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rec_path = a.out / "transitions.json"
    runs = json.loads(rec_path.read_text()) if rec_path.exists() else []
    if not a.report:
        todo = [(s, a.arm, "mix", a.left_arm) for s in filter(None, a.stories.split(","))]
        if a.kinds_story:
            todo += [(a.kinds_story, a.kinds_arm, k, None) for k in tx.KINDS]
        for story, arm, style, left_arm in todo:
            r = one(a.ab, a.out, story, arm, style, left_arm)
            runs = [x for x in runs if (x["story"], x["style"]) != (story, style)] + [r]
            rec_path.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    titles = {}
    for r in runs:
        ab = a.ab / r["story"] / "ab.json"
        if ab.exists():
            titles[r["story"]] = json.loads(ab.read_text()).get("title") or r["story"]
    print(page(a.out, runs, titles, a.title))


if __name__ == "__main__":
    main()
