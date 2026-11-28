"""The custom animation's A/B (Nov 28): the same frozen stories made twice, A with the switch off (every beat
keeps its normal shot) and B with it on (one beat gets the model-drawn animation in a window), then side by
side, with stills, checks, a judge and a report page.

The script is held fixed by construction. Both arms read the story's script.json (never rewritten), the voice
director's saved direction.json and the saved recording (a new recording raises instead of paying), so the words,
the voice and every beat's timing are identical: only the animated beat's picture differs. The animation never
changes the writer's prompt, so this is also what a live run would give.

    python scripts/animation_ab.py <story ids...> --out <folder>                    # A, B (card), side by side
    python scripts/animation_ab.py <id> --out <folder> --looks card,plate --judge    # both looks, and the judge
    python scripts/animation_ab.py --report <folder>                                # the report page again

Story ids may be the first 8 characters (frozen stories in stringer_private/frozen/stories). Every model call's
cost goes to spend.json (--ledger; <folder>/spend.json by default) as it is answered; a paid step whose estimate would take the total past --cap
(default 15 USD) stops the run. Answers are cached (stringer/animation/steps.py), so a rerun is free.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import functools
import hashlib
import html
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stringer import animation, models, paths  # noqa: E402
from stringer.animation import steps  # noqa: E402
from stringer.video import make, render as render_step, voice  # noqa: E402

FROZEN = paths.PRIVATE / "frozen" / "stories"
EST_B = 0.20           # the most one story's storyboard, drawing and cue words have cost (rounds 5-6: 0.065-0.084)
EST_JUDGE = 0.05
JUDGE_MODEL = "sonnet-5-5"
STILL_AT = (0.12, 0.4, 0.68, 0.95)      # where in the animated beat the stills are taken


class OverCap(RuntimeError):
    pass


class Ledger:
    """spend.json: every paid call, as it is answered (any thread, any process: each entry is added to the file as it
    stands, under a file lock), and the running total."""

    def __init__(self, path: Path, cap: float):
        self.path, self.cap, self._lock = Path(path), cap, threading.Lock()
        self.what = ""

    def _read(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else dict(total_usd=0.0, calls=[])

    def __call__(self, step, alias, usd: float) -> None:
        with self._lock, open(self.path.with_suffix(".lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            d = self._read()
            d["cap_usd"] = self.cap
            d["calls"].append(dict(at=dt.datetime.now().isoformat(timespec="seconds"), step=step, model=alias,
                                   usd=round(float(usd or 0), 6), what=self.what))
            d["total_usd"] = round(sum(c["usd"] for c in d["calls"]), 6)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1))
            tmp.replace(self.path)

    @property
    def total(self) -> float:
        return self._read()["total_usd"]

    def check(self, estimate: float, what: str) -> None:
        self.what = what
        if self.total + estimate > self.cap:
            raise OverCap(f"{what}: {self.total:.3f} spent + up to {estimate:.2f} would pass the {self.cap:.2f} USD cap")


class CachedOnly(voice.ElevenLabs):
    """The saved recording or nothing: the A/B never pays for a new voice."""

    def speak(self, text, out):
        raise RuntimeError("the A/B would record a new voice; it only reuses saved ones")


def story_dir(i: str) -> Path:
    hit = [d for d in FROZEN.iterdir() if d.name.startswith(i) and (d / "script.json").exists()]
    if len(hit) != 1:
        raise SystemExit(f"{i}: {len(hit)} frozen stories match")
    return hit[0]


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- one arm ----------------------------------------------------------------------------------------------

def arm(story: Path, out: Path, *, anim, video: bool) -> dict:
    """make.make for one arm into `out`, with the story's saved direction (so the saved recording is reused)."""
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(story / "video" / "direction.json", out / "direction.json")
    t0 = time.time()
    rec = make.make(story, CachedOnly(), out, music=make.MUSIC if make.MUSIC.exists() else None, render=video,
                    trace=False, anim=anim)
    rec["wall_seconds"] = round(time.time() - t0, 2)
    (out / "arm.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    return rec


def stills(out: Path, plan_path: Path, frames: list[int], name: str) -> dict:
    """PNG stills of the given frames, with the layout check (eval 7) on, shrunk to JPEGs for the page."""
    pl = json.loads(plan_path.read_text())
    dbg = out / f"plan-{name}-debug.json"
    dbg.write_text(json.dumps(dict(pl, debug_layout=True)))
    folder = out / f"stills-{name}"
    r = render_step.render(dbg, out, folder, mode="stills", extra=["--frames", ",".join(map(str, frames))])
    jpgs = []
    for f in r["files"]:
        j = Path(f).with_suffix(".jpg")
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", f, "-vf", "scale=540:-1", "-q:v", "3", str(j)])
        Path(f).unlink(missing_ok=True)
        jpgs.append(j.name)
    dbg.unlink(missing_ok=True)
    return dict(files=[f"{folder.name}/{j}" for j in jpgs], layout=r.get("layout") or [], errors=r.get("browser_errors") or [])


def strip(images: list[Path], dest: Path, width: int = 1600) -> None:
    ins = sum([["-i", str(p)] for p in images], [])
    sh(["ffmpeg", "-loglevel", "error", "-y", *ins, "-filter_complex",
        f"{''.join(f'[{i}]' for i in range(len(images)))}hstack={len(images)},scale={width}:-1", "-q:v", "3", str(dest)])


FONT = next((f for f in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
             if Path(f).exists()), None)


@functools.lru_cache(maxsize=1)
def has_drawtext() -> bool:
    """Some ffmpeg builds (this Mac's Homebrew one) have no drawtext filter, so no labels can be burnt in."""
    return " drawtext " in sh(["ffmpeg", "-hide_banner", "-filters"]).stdout


def side_by_side(videos: list[tuple[str, Path]], dest: Path) -> str:
    """The arms next to each other at half size, with the first arm's sound (all the same). Each is labelled when
    ffmpeg can draw text; otherwise they stand in the order given (the report says which is which). Returns ffmpeg's
    error, or ""."""
    ins = sum([["-i", str(v)] for _, v in videos], [])
    parts = []
    for i, (label, _) in enumerate(videos):
        lab = (f",drawtext=fontfile='{FONT}':text='{label}':x=20:y=20:fontsize=34:fontcolor=white:box=1:"
               f"boxcolor=black@0.6:boxborderw=10") if FONT and has_drawtext() else ""
        parts.append(f"[{i}:v]scale=540:960{lab}[v{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(videos))) + f"hstack={len(videos)}[v]"
    r = sh(["ffmpeg", "-loglevel", "error", "-y", *ins, "-filter_complex", graph, "-map", "[v]", "-map", "0:a",
            "-c:v", "libx264", "-crf", "24", "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k", "-shortest", str(dest)])
    return "" if r.returncode == 0 and dest.exists() else (r.stderr or "ffmpeg failed")[-300:]


# ---- the judge ----------------------------------------------------------------------------------------------

JUDGE_SYSTEM = """You judge one beat of a short vertical news explainer video (made for phones), in two versions.
You see, for each version, a strip of stills from that beat in time order, left to right. The words spoken during the
beat and the facts it may show are given. The two versions have the same words, voice and captions; only the picture
differs. Judge only what you see.

Score each version 1 to 5 on:
- clarity: on a phone, what the picture shows reads at a glance; text is legible; nothing overlaps or is cut off;
- fit: the picture shows what the spoken line says and nothing it does not (no invented events, numbers or outcomes;
  where accounts disagree, no side's account drawn as settled);
- craft: it looks finished, coherent and calm, like a professional news explainer;
- interest: it holds attention and helps a viewer understand or remember the line.
Then say which version a viewer would rather see (X, Y or same), and list concrete problems in each (faces drawn,
words or letters inside a drawing, a real country's flag, something drawn that the line does not say, overlap,
clutter, a picture that stands still, a picture that is hard to read small)."""

JUDGE_SCHEMA = {"type": "json_schema", "json_schema": {"name": "beat_judgment", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["X", "Y", "prefer", "why"],
    "properties": {
        **{k: {"type": "object", "additionalProperties": False, "required": ["clarity", "fit", "craft", "interest", "problems"],
               "properties": {"clarity": {"type": "integer"}, "fit": {"type": "integer"}, "craft": {"type": "integer"},
                              "interest": {"type": "integer"}, "problems": {"type": "array", "items": {"type": "string"}}}}
           for k in ("X", "Y")},
        "prefer": {"type": "string", "enum": ["X", "Y", "same"]},
        "why": {"type": "string"}}}}}


def judge(story: str, line: str, facts: str, a_strip: Path, b_strip: Path) -> dict:
    """Which picture serves the beat better: A or B, shown as X and Y in an order fixed by the story id."""
    b_first = int(hashlib.sha256(story.encode()).hexdigest(), 16) % 2 == 0
    x, y = (b_strip, a_strip) if b_first else (a_strip, b_strip)
    img = lambda p: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()}}  # noqa: E731
    msgs = [{"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": f"THE SPOKEN LINE\n{line}\n\nFACTS IT MAY SHOW\n{facts}\n\nVERSION X"}, img(x),
                {"type": "text", "text": "VERSION Y"}, img(y)]}]
    d, rec = steps.ask_json("anim_judge", msgs, JUDGE_SCHEMA, lambda m, name=None, step=None, **p: models.complete(
        step, m, name=name, **p), cache=steps.CACHE, name="animation A/B judge")
    if not d:
        return dict(error=rec.get("error"), rec=rec)
    a, b = (d["Y"], d["X"]) if b_first else (d["X"], d["Y"])
    prefer = {"same": "same", "X": "B" if b_first else "A", "Y": "A" if b_first else "B"}[d["prefer"]]
    return dict(A=a, B=b, prefer=prefer, why=d["why"], usd=rec.get("usd"), cached=rec.get("cached"))


steps.DEFAULT_MODELS["anim_judge"] = JUDGE_MODEL
steps.MAX_TOKENS["anim_judge"] = 4000
steps.TIMEOUT_S["anim_judge"] = 120


# ---- one story ----------------------------------------------------------------------------------------------

VOICE_S = 15.0         # a live ElevenLabs call for a ~60 s script (the A/B reuses saved recordings, so it is not timed)


def live_budget() -> float:
    """How long a live run gives the storyboard and drawing, which start once the script is checked: about 3 s for
    the check and voice director, the voice call, then the job's grace (animation.DEADLINE_S)."""
    return round(3 + VOICE_S + animation.DEADLINE_S, 1)


def run_story(story: Path, out: Path, looks: list[str], *, video: bool, do_judge: bool, ledger: Ledger) -> dict:
    short = story.name[:8]
    root = out / short
    root.mkdir(parents=True, exist_ok=True)
    res: dict = dict(story=short, title=json.loads((story / "script.json").read_text()).get("title"), arms={})
    print(f"[{short}] A", flush=True)
    ra = arm(story, root / "A", anim=False, video=video)
    res["arms"]["A"] = dict(status=ra["status"], seconds=ra["wall_seconds"],
                            render_seconds=(ra["steps"].get("render") or {}).get("seconds"))
    for look in looks:
        ledger.check(EST_B, f"{short} B-{look}")
        print(f"[{short}] B-{look}", flush=True)
        job = make.start_animation(story, frame=look, deadline_s=900)
        rb = arm(story, root / f"B-{look}", anim=job, video=video)
        an = json.loads((root / f"B-{look}" / "animation.json").read_text())
        res["arms"][f"B-{look}"] = dict(status=rb["status"], seconds=rb["wall_seconds"],
                                        render_seconds=(rb["steps"].get("render") or {}).get("seconds"), animation=an)
    b0 = res["arms"][f"B-{looks[0]}"]["animation"]
    plan_a = json.loads((root / "A" / "plan.json").read_text())
    res["live_budget_s"] = live_budget()
    st = b0.get("steps") or {}
    first = lambda s: (s or {}).get("seconds_first") if (s or {}).get("cached") else (s or {}).get("seconds")  # noqa: E731
    res["drawing_ready_s"] = round(sum(first(st.get(k)) or 0 for k in ("storyboard", "drawing")), 1) if st else None
    res["late_live"] = (res["drawing_ready_s"] or 0) > (res["live_budget_s"] or 1e9) if res["drawing_ready_s"] else None
    cost_first = lambda s: (s or {}).get("usd_first") if (s or {}).get("cached") else (s or {}).get("usd")  # noqa: E731
    res["usd_per_video"] = round(sum(cost_first(st.get(k)) or 0 for k in ("storyboard", "drawing", "cues")), 4)
    if b0.get("status") == "drawn":
        n = b0["beat"]["n"]
        pb = next(b for b in plan_a["beats"] if b["n"] == n)
        frames = [pb["start"] + int(pb["frames"] * f) for f in STILL_AT]
        res["beat_frames"] = frames
        res["stills"] = {"A": stills(root, root / "A" / "plan.json", frames, "A")}
        for look in looks:
            if res["arms"][f"B-{look}"]["animation"].get("status") == "drawn":
                res["stills"][f"B-{look}"] = stills(root / f"B-{look}", root / f"B-{look}" / "plan.json", frames, f"B-{look}")
                res["stills"][f"B-{look}"]["files"] = [f"B-{look}/{f}" for f in res["stills"][f"B-{look}"]["files"]]
        # the animation alone, six frames across the beat
        box_dir = root / f"B-{looks[0]}" / "anim"
        picks = [box_dir / f"f{int((pb['frames'] - 1) * k / 5):04d}.jpg" for k in range(6)]
        strip(picks, root / "animation-strip.jpg")
        for name in res["stills"]:
            strip([root / f for f in res["stills"][name]["files"]], root / f"stills-{name}.jpg", width=1440)
        if do_judge:
            ledger.check(EST_JUDGE * len(looks), f"{short} judge")
            sb = b0.get("storyboard") or {}
            facts = f"{sb.get('agreed', '')}\nNot to be shown as settled: {sb.get('avoid', '')}"
            res["judge"] = {look: judge(short, b0["beat"]["say"], facts, root / "stills-A.jpg", root / f"stills-B-{look}.jpg")
                            for look in looks if f"B-{look}" in res["stills"]}
    if video and (root / "A" / "video.mp4").exists():
        vids = [("A: as now", root / "A" / "video.mp4")] + [(f"B: animation ({look})", root / f"B-{look}" / "video.mp4")
                                                          for look in looks if (root / f"B-{look}" / "video.mp4").exists()]
        res["side_by_side"] = dict(order=[label for label, _ in vids], error=side_by_side(vids, root / "side_by_side.mp4"))
    (root / "ab.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return res


# ---- the report page -------------------------------------------------------------------------------------------

def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


CSS = """
:root{--paper:#F3EEE1;--deep:#E9E2CF;--ink:#1A2A86;--soft:rgba(26,42,134,.72);--ver:#E8622C;--ok:#2E7D3F;--bad:#B5401F}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif}
main{max-width:1500px;margin:0 auto;padding:28px 24px 80px}h1{font:400 34px Georgia,serif;margin:0 0 6px}
h2{font:400 26px Georgia,serif;margin:46px 0 8px;border-top:2px solid var(--ink);padding-top:18px}h3{margin:22px 0 6px;font-size:15px;text-transform:uppercase;letter-spacing:.06em}
.lede{color:var(--soft);max-width:900px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:#FBF8EF;border-radius:6px;padding:14px 16px;box-shadow:0 1px 0 rgba(26,42,134,.12)}
table{border-collapse:collapse;width:100%;background:#FBF8EF}td,th{padding:6px 10px;border-bottom:1px solid var(--deep);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--soft)}img,video{max-width:100%;border-radius:4px;display:block}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}.ok{background:#DDEBD8;color:var(--ok)}.bad{background:#F6D9CE;color:var(--bad)}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}.small{font-size:13px;color:var(--soft)}
.big{font:400 40px Georgia,serif}.row{display:flex;gap:14px;flex-wrap:wrap}.row>*{flex:1 1 300px}
"""


def report(out: Path, ledger: Path) -> Path:
    stories = [json.loads(p.read_text()) for p in sorted(out.glob("*/ab.json"))]
    spend = json.loads(ledger.read_text()) if ledger.exists() else dict(total_usd=0, cap_usd=15)
    looks = sorted({k[2:] for s in stories for k in s["arms"] if k.startswith("B-")}, key=lambda x: (x != "card", x))
    drawn = [s for s in stories if any((v.get("animation") or {}).get("status") == "drawn" for v in s["arms"].values())]
    prefs = [j["prefer"] for s in stories for j in (s.get("judge") or {}).values() if "prefer" in j]
    H = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>Animation A/B</title><style>{CSS}</style><main>",
         "<h1>Custom animation: A/B</h1>",
         "<p class=lede>A is the video as it is made today. B is the same video (same script, same recorded voice, same "
         "timing) with one beat given a model-drawn paper-cutout animation in a window under that beat's words. "
         f"Made {dt.date.today().isoformat()} from frozen stories; every model answer cached, so this page can be rebuilt for free.</p>",
         "<div class=grid>",
         f"<div class=card><div class=small>stories</div><div class=big>{len(stories)}</div></div>",
         f"<div class=card><div class=small>animation drawn</div><div class=big>{len(drawn)} of {len(stories)}</div></div>",
         f"<div class=card><div class=small>judge prefers B</div><div class=big>{prefs.count('B')} of {len(prefs)}</div>"
         f"<div class=small>A {prefs.count('A')} · same {prefs.count('same')}</div></div>",
         f"<div class=card><div class=small>spent on models (whole build)</div><div class=big>${spend['total_usd']:.2f}</div>"
         f"<div class=small>cap ${spend.get('cap_usd', 15):.0f}</div></div></div>"]
    # summary table
    H.append("<h2>Every story at a glance</h2><table><tr><th>story</th><th>animated beat</th><th>outcome</th><th>box</th>"
             "<th>cost per video</th><th>drawing ready</th><th>live budget</th><th>judge (A → B)</th></tr>")
    for s in stories:
        an = s["arms"][f"B-{looks[0]}"]["animation"] if f"B-{looks[0]}" in s["arms"] else {}
        bx = an.get("box") or {}
        st = "<span class='tag ok'>drawn</span>" if an.get("status") == "drawn" else f"<span class='tag bad'>fallback</span> {esc(an.get('fallback'))}"
        j = (s.get("judge") or {}).get(looks[0]) or {}
        jt = ""
        if "A" in j:
            sa = sum(j["A"][k] for k in ("clarity", "fit", "craft", "interest"))
            sb_ = sum(j["B"][k] for k in ("clarity", "fit", "craft", "interest"))
            jt = f"{sa}/20 → {sb_}/20 · prefers <b>{esc(j['prefer'])}</b>"
        beat = an.get("beat") or {}
        H.append(f"<tr><td><b>{esc(s['title'])}</b><div class='small mono'>{esc(s['story'])}</div></td>"
                 f"<td>{esc(beat.get('n'))} · {esc(beat.get('shot'))}</td><td>{st}</td>"
                 f"<td class=small>{esc(bx.get('ms_p95'))} ms/frame (p95)<br>still at end {esc(bx.get('still'))}<br>"
                 f"sandbox {esc(bx.get('sandbox'))}, blocked {len(bx.get('blocked') or [])}</td>"
                 f"<td>${s.get('usd_per_video', 0):.3f}</td><td>{esc(s.get('drawing_ready_s'))} s</td>"
                 f"<td>{esc(s.get('live_budget_s'))} s {'<span class=\"tag bad\">late</span>' if s.get('late_live') else ''}</td>"
                 f"<td>{jt}</td></tr>")
    H.append("</table>")
    if len(looks) > 1:
        H.append("<h2>The window's looks</h2><p class=lede>Two looks are built and selectable with "
                 "<span class=mono>STRINGER_ANIMATION_FRAME</span>: <b>card</b> (the default: a paper-edged card, tilted a "
                 "hair, laid on the page) and <b>plate</b> (edge to edge, a vermilion rule on top). The frames inside are the "
                 "same drawing; only the frame differs. Each story below shows every look that was made for it.</p>")
    for s in stories:
        root = s["story"]
        H.append(f"<h2>{esc(s['title'])} <span class='small mono'>{esc(root)}</span></h2>")
        if (out / root / "side_by_side.mp4").exists():
            order = (s.get("side_by_side") or {}).get("order") or ["A: as now"] + [f"B: animation ({n[2:]})" for n in s["arms"] if n != "A"]
            H.append(f"<h3>The videos side by side, left to right: {esc(' | '.join(order))} (sound from A; all have "
                     f"the same voice)</h3><video controls preload=metadata src='{root}/side_by_side.mp4' "
                     f"style='max-width:100%;max-height:720px'></video>")
        for name, arm_rec in s["arms"].items():
            if (out / root / name / "video.mp4").exists():
                H.append(f"<div class=small>{esc(name)}: <a href='{root}/{name}/video.mp4'>full video</a> · made in "
                         f"{esc(arm_rec.get('seconds'))} s (render {esc(arm_rec.get('render_seconds'))} s)</div>")
        if s.get("stills"):
            H.append("<h3>The animated beat, four moments (left to right)</h3>")
            for name in s["stills"]:
                lay = [p for x in s["stills"][name]["layout"] for p in x.get("problems") or []]
                H.append(f"<div class=small><b>{esc(name)}</b> · layout check: "
                         f"{'<span class=\"tag ok\">no problems</span>' if not lay else '<span class=\"tag bad\">' + str(len(lay)) + ' problems</span> ' + esc('; '.join(sorted({p['kind'] + ': ' + p.get('text', '') for p in lay}))[:400])}</div>"
                         f"<img src='{root}/stills-{name}.jpg'>")
            H.append(f"<h3>The animation alone (the frames the box drew, across the beat)</h3><img src='{root}/animation-strip.jpg'>")
        for name, arm_rec in s["arms"].items():
            an = arm_rec.get("animation")
            if not an:
                continue
            sb = an.get("storyboard") or {}
            cues = an.get("cues") or {}
            bx = an.get("box") or {}
            stp = an.get("steps") or {}
            rows = [("outcome", an.get("status") + (f" — {an.get('fallback')}" if an.get("fallback") else "")),
                    ("beat", f"{(an.get('beat') or {}).get('n')} · {(an.get('beat') or {}).get('shot')} · {(an.get('beat') or {}).get('seconds')} s"),
                    ("line", (an.get("beat") or {}).get("say")),
                    ("storyboard", sb.get("show")), ("agreed facts", sb.get("agreed")), ("kept out", sb.get("avoid")),
                    ("claims", ", ".join(sb.get("claims") or [])),
                    ("library pieces", ", ".join(f"{x['thing']} → {x['piece']}" for x in sb.get("needs") or [])),
                    ("drawn by the model (not in the library)", ", ".join(an.get("missing") or []) or "nothing"),
                    ("cue words → times", ", ".join(f"{k}: “{(cues.get('words') or {}).get(k)}” at {v}" for k, v in (cues.get("spaced") or {}).items())),
                    ("box", f"{bx.get('status')} · {bx.get('frames')} frames in {bx.get('seconds')} s · {bx.get('ms_median')} ms median, "
                            f"{bx.get('ms_p95')} p95 · blank {bx.get('blank_frames')} · errors {bx.get('frame_errors')} · "
                            f"OS sandbox {bx.get('sandbox')} · requests blocked {len(bx.get('blocked') or [])} · words dropped {bx.get('text_calls')}"),
                    ("model steps", " · ".join(f"{k}: {v.get('model')} {'(cached) ' if v.get('cached') else ''}"
                                               f"${(v.get('usd_first') if v.get('cached') else v.get('usd')) or 0:.4f}, "
                                               f"{(v.get('seconds_first') if v.get('cached') else v.get('seconds')) or 0} s"
                                               f"{', error: ' + str(v.get('error')) if v.get('error') else ''}" for k, v in stp.items()))]
            H.append(f"<h3>{esc(name)}: what happened</h3><table>" + "".join(
                f"<tr><th style='width:220px'>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows) + "</table>")
        for look, j in (s.get("judge") or {}).items():
            if "A" not in j:
                H.append(f"<div class=small>judge ({esc(look)}): {esc(j.get('error'))}</div>")
                continue
            H.append(f"<h3>The judge ({esc(JUDGE_MODEL)}, sees four stills of each, unlabelled, order fixed per story): B-{esc(look)} vs A</h3><table>"
                     "<tr><th></th><th>clarity</th><th>fit</th><th>craft</th><th>interest</th><th>problems it saw</th></tr>" +
                     "".join(f"<tr><td><b>{k}</b></td>" + "".join(f"<td>{j[k][m]}</td>" for m in ("clarity", "fit", "craft", "interest"))
                             + f"<td class=small>{esc('; '.join(j[k]['problems']))}</td></tr>" for k in ("A", "B")) +
                     f"</table><p>Prefers <b>{esc(j['prefer'])}</b>: {esc(j['why'])}</p>")
    H.append("<h2>Spend</h2><table><tr><th>when</th><th>what</th><th>step</th><th>model</th><th>USD</th></tr>" + "".join(
        f"<tr><td class=mono>{esc(c['at'])}</td><td>{esc(c.get('what'))}</td><td>{esc(c['step'])}</td><td>{esc(c['model'])}</td>"
        f"<td>{c['usd']:.4f}</td></tr>" for c in spend.get("calls", [])) +
        f"<tr><th colspan=4>total</th><th>${spend['total_usd']:.4f}</th></tr></table></main>")
    page = out / "report.html"
    page.write_text("\n".join(H), encoding="utf-8")
    return page


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--looks", default="card")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--cap", type=float, default=15.0)
    ap.add_argument("--ledger", type=Path, help="spend.json to add to (default: <out>/spend.json)")
    ap.add_argument("--report", action="store_true", help="only rebuild the report page")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    a.ledger = a.ledger or a.out / "spend.json"
    if not a.report:
        ledger = Ledger(a.ledger, a.cap)
        with models.on_cost(ledger):
            for i in a.ids:
                try:
                    r = run_story(story_dir(i), a.out, a.looks.split(","), video=not a.no_video, do_judge=a.judge, ledger=ledger)
                except OverCap as e:
                    print(f"stopped: {e}")
                    break
                b = r["arms"][f"B-{a.looks.split(',')[0]}"]["animation"]
                print(f"[{r['story']}] {b['status']} {b.get('fallback') or ''} · ${ledger.total:.3f} spent", flush=True)
    print(report(a.out, a.ledger))


if __name__ == "__main__":
    main()
