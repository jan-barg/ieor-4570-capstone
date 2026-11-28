"""The custom animation: for each story, a model draws a short paper-cutout animation of the story's key moment,
and it plays in a window inside one beat of the video, under that beat's words, timed to the spoken words
(tested in rounds 2-6 on Nov 27; built Nov 28 on branch custom-animation-ab). Off by default.

The switch: STRINGER_ANIMATION=1 in the environment (or animation=True for make.make / pipeline.run). Off, nothing
here runs and every video is exactly as before.

How one animation is made (steps.py has the details, guide.py the prompts, box.py the lock):

    place  (once the script is checked, beside the voice)
           the beats a window fits under -> storyboard (picks one) -> drawing      code, then model calls, in a thread
                                                                -> cue words      one small call, beside the drawing
    finish (once the voice exists)     cue times -> frames in the box  waits for the drawing up to a deadline

The beat keeps its normal shot when anything fails: no beat a window fits under (then nothing is paid), no
storyboard, no drawing, the drawing refused, throwing an error, leaving a frame blank, slower than 20 ms a frame,
or not ready by the deadline ("late"). Things the library lacks don't stop it: the drawing model draws only those.
Every outcome is recorded in the video folder's animation.json.

    job = animation.start(packet_text, claim_ids)        # module 7's packet; returns at once, nothing runs yet
    job.place(beats)                                      # the checked script's beats; returns at once
    anim = job.finish(narration, out_dir)                 # None, or the beat's window for plan.build
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import box, steps

VERSION = "anim-1"
FRAMES = ("card", "plate")          # the window's look (render/src/anim.js); "card" (Jan's pick, Nov 28) unless chosen
DEADLINE_S = 40.0                   # after the voice is recorded, the drawing may take this much longer, then "late"
                                    # (storyboard and drawing took 21-57 s in the A/B; they start with the voice
                                    # director and the voice, which take about 18 s)


def enabled(flag: bool | None = None) -> bool:
    """The switch: an explicit flag wins; otherwise STRINGER_ANIMATION in the environment (off by default)."""
    if flag is not None:
        return bool(flag)
    return os.environ.get("STRINGER_ANIMATION", "").strip().lower() in ("1", "on", "true", "yes")


def frame_style(name: str | None = None) -> str:
    name = name or os.environ.get("STRINGER_ANIMATION_FRAME") or FRAMES[0]
    return name if name in FRAMES else FRAMES[0]


class Job:
    """One story's animation, from storyboard to frames. Every method returns at once except finish()."""

    def __init__(self, packet_text: str, claim_ids, *, complete=None, trace_id: str | None = None,
                 cache: Path | None = steps.CACHE, frame: str | None = None, deadline_s: float = DEADLINE_S):
        self.packet_text, self.claim_ids = packet_text, list(claim_ids)
        self.deadline_s = deadline_s
        self.complete = complete or steps.default_complete(trace_id)
        self.cache = cache
        self.t0 = time.time()
        self.rec = dict(version=VERSION, frame=frame_style(frame), status="started", fallback=None, steps={},
                        storyboard=None, missing=[], beat=None, cues=None, box=None)
        self._sb_ready = threading.Event()
        self._sb = None
        self._no_beat = None
        self._pool = ThreadPoolExecutor(2, thread_name_prefix="animation")
        self._drawing = None
        self._placing = None

    def place(self, beats: list[dict]) -> None:
        """Once the script's beats are final (after module 8's check): plan, draw and pick the cue words."""
        beats = [dict(b) for b in beats]
        self._drawing = self._pool.submit(self._plan, beats)
        self._placing = self._pool.submit(self._place, beats)

    # the beats a window fits under, the storyboard (it picks one), then the drawing
    def _plan(self, beats: list[dict]) -> dict | None:
        try:
            idx, why = steps.candidates(beats)
            if not idx:
                self._no_beat = why
                return None
            sb, r1 = steps.storyboard(self.packet_text, self.claim_ids, beats, idx, self.complete, self.cache)
            self.rec["steps"]["storyboard"] = dict(r1, done_at=round(time.time() - self.t0, 2), candidates=len(idx))
            self._sb = sb
        finally:
            self._sb_ready.set()
        if sb is None:
            return None
        self.rec.update(storyboard=sb, missing=steps.missing(sb))
        d, r2 = steps.drawing(sb, self.packet_text, self.complete, self.cache)
        self.rec["steps"]["drawing"] = dict(r2, done_at=round(time.time() - self.t0, 2))
        return d

    # the picked beat's cue words, beside the drawing
    def _place(self, beats: list[dict]) -> dict | None:
        self._sb_ready.wait()
        sb = self._sb
        if sb is None:
            return None
        i = sb["index"]
        placed, r = steps.place_cues(sb, beats[i], self.complete, self.cache)
        self.rec["steps"]["cues"] = dict(r, done_at=round(time.time() - self.t0, 2))
        b = beats[i]
        return dict(index=i, n=b.get("n", i + 1), shot=b.get("shot"), say=b.get("voice") or b.get("say"),
                    claims=b.get("claims"), placed=placed, words=steps.beat_words(b))

    def _fallback(self, why: str) -> None:
        self.rec.update(status="fallback", fallback=why)

    def finish(self, narr: dict, out_dir: Path, *, deadline_s: float | None = None, fps: int = 30) -> dict | None:
        """After the voice: wait for the drawing (up to deadline_s, the job's own by default), time the cues to the
        voice, draw the frames in the box. Returns the window for plan.build ({"beat": index, "frames", "dir",
        "cues", "frame"}) or None. Writes out_dir/animation.json either way."""
        out_dir = Path(out_dir)
        deadline_s = self.deadline_s if deadline_s is None else deadline_s
        t_wait = time.time()
        try:
            return self._finish(narr, out_dir, deadline_s, fps, t_wait)
        except Exception as e:                       # never stop a video: the beat keeps its normal shot
            self._fallback(f"crashed: {type(e).__name__}: {e}"[:300])
            return None
        finally:
            self.rec["seconds"] = round(time.time() - self.t0, 2)
            self.rec["usd"] = round(sum((s or {}).get("usd") or 0 for s in self.rec["steps"].values()), 5)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "animation.json").write_text(json.dumps(self.rec, ensure_ascii=False, indent=1), encoding="utf-8")
            self._pool.shutdown(wait=False)

    def _finish(self, narr, out_dir, deadline_s, fps, t_wait) -> dict | None:
        if self._drawing is None:
            self._fallback("the script's beats were never given")
            return None
        try:
            d = self._drawing.result(timeout=deadline_s)
        except TimeoutError:
            self.rec["waited_s"] = round(time.time() - t_wait, 2)
            self._fallback(f"late: the drawing was not ready {deadline_s:.0f} s after the voice")
            return None
        self.rec["waited_s"] = round(time.time() - t_wait, 2)
        if self._no_beat:
            self._fallback(self._no_beat)
            return None
        if self._sb is None:
            self._fallback("no storyboard: " + str((self.rec["steps"].get("storyboard") or {}).get("error")))
            return None
        if not d:
            self._fallback("no drawing: " + str((self.rec["steps"].get("drawing") or {}).get("error")))
            return None
        self.rec.update(plan=d.get("plan"), code=d.get("code"))
        pl = self._placing.result(timeout=max(5.0, deadline_s))
        i = pl["index"]
        bt = narr["beats"][i]
        start, end = int(round(bt["start"] * fps)), int(round(bt["end"] * fps))
        words = [w for w in narr["words"] if w["beat"] == i]
        if len(words) != len(pl["words"]):           # the voice split the line differently: match by text, in order
            words = _align(pl["words"], words)
        names = [c["name"] for c in self._sb["cues"]]
        placed = steps.cue_times(pl["placed"], names, words, bt["start"], bt["end"])
        cues = steps.space_cues(placed, names)
        self.rec.update(beat=dict(index=i, n=pl["n"], shot=pl["shot"], say=pl["say"], claims=pl["claims"],
                                  seconds=round(bt["end"] - bt["start"], 2)),
                        cues=dict(words={n: (pl["words"][pl["placed"][n]] if n in pl["placed"] else None) for n in names},
                                  placed=placed, spaced=cues))
        frames = max(2, end - start)
        tb = time.time()
        rec = box.draw(d["code"], out_dir / "anim", frames=frames, cues=cues)
        rec["seconds_total"] = round(time.time() - tb, 2)
        self.rec["box"] = rec
        (out_dir / "anim").mkdir(parents=True, exist_ok=True)     # refused code never reaches the box, which makes it
        (out_dir / "anim" / "code.js").write_text(d["code"], encoding="utf-8")
        if not rec["ok"]:
            self._fallback(rec["why"])
            return None
        self.rec["status"] = "drawn"
        return dict(beat=i, frames=frames, dir="anim", cues=cues, frame=self.rec["frame"], still=rec.get("still"))


def summary(rec: dict) -> dict:
    """The few fields of animation.json that render.json and the pipeline's record keep."""
    bx = rec.get("box") or {}
    return dict(status=rec.get("status"), fallback=rec.get("fallback"), frame=rec.get("frame"),
                beat=(rec.get("beat") or {}).get("n"), shot=(rec.get("beat") or {}).get("shot"),
                missing=rec.get("missing") or [], usd=rec.get("usd"), waited_s=rec.get("waited_s"),
                box=dict(status=bx.get("status"), frames=bx.get("frames"), ms_p95=bx.get("ms_p95"),
                         still=bx.get("still"), sandbox=bx.get("sandbox"), blocked=len(bx.get("blocked") or [])) if bx else None)


def _align(want: list[str], timed: list[dict]) -> list[dict]:
    """The timed words for each of `want` (the beat's words as split before the voice), matched in order by text."""
    out, k = [], 0
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
    for w in want:
        j = next((j for j in range(k, len(timed)) if norm(timed[j]["w"]) == norm(w)), None)
        if j is None:
            out.append(timed[min(k, len(timed) - 1)] if timed else dict(w=w, start=0.0, end=0.0))
        else:
            out.append(timed[j])
            k = j + 1
    return out


def start(packet_text: str, claim_ids, **kw) -> Job:
    """A story's animation job; nothing runs until place() gives it the checked script's beats."""
    return Job(packet_text, claim_ids, **kw)
