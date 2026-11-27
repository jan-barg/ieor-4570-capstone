"""Runs module 8's steps in order for one story folder (design settled Nov 26).

    rec = make(story_dir)                         # ElevenLabs voice, render, files; outputs in story_dir/video/
    rec = prepare(story_dir, voice.Paced(), out)  # steps 1-4 only: plan.json and narration.mp3 in out

A narration longer than 72 s (with the 1.5 s hold) is not read again: the same recording is played
up to 12% faster (free; a second reading cost the credits again and came out no shorter, Nov 26).
The record says what happened at each step, how long it took and what the voice cost. The steps join
the Langfuse trace given as trace_id (the live pipeline's, one per video); render.json keeps its id.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .. import fact_check, paths, script_writer as sw, story_file, tracing
from . import check, direct, files, plan, render as render_step, voice

MAX_SECONDS = 72.0
FIT_MARGIN = 0.3       # a sped-up video aims this far under MAX_SECONDS
# The music bed (decision 11): Jan's ambient track from ElevenLabs ("Clean Reportage", 120 s, Nov 26), stored 7.8 dB
# quieter than he made it so it matches the voice's loudness (-21 LUFS); plan.MUSIC_DB then sets it 16 dB under.
MUSIC = paths.PRIVATE / "video_assets" / "music" / "clean-reportage.mp3"


def inputs(story_dir: Path) -> tuple[dict, dict, dict]:
    """script.json (with today's credits and sources card), the checked story file and module 7's packet (for the on-screen check)."""
    script = json.loads((story_dir / "script.json").read_text(encoding="utf-8"))
    facts, _ = story_file.read(story_dir)
    sf = fact_check.read_checked(story_dir)
    arts = fact_check.read_articles(story_dir)
    arts = {a["id"]: a for a in arts} if isinstance(arts, list) else arts
    p7 = sw.packet(sf, facts, sw.contexts_for(facts, arts))
    # code-made, so an older script gets today's credits and sources card
    script = dict(script, credits=sw.credits(sf, p7))
    if script.get("sources_card"):
        script["sources_card"] = sw.sources_card(sf, p7)
    return script, sf, p7


def prepare(story_dir: Path, engine, out_dir: Path, *, voice_cache: Path | None = None, music: Path | None = None,
            direction: bool = True, complete=None, trace_id: str | None = None) -> dict:
    """Steps 1-4. Writes out_dir/plan.json and out_dir/narration.mp3 (and the music bed, if any).
    The voice director runs first (direct.py) when the voice reads tags; direction=False skips it."""
    t0 = time.time()
    if complete is None and trace_id:
        complete = lambda messages, name=None, model=None, **p: direct.model_call(      # noqa: E731
            messages, name=name, model=model, trace_id=trace_id, **p)
    script, sf, p7 = inputs(story_dir)
    rec: dict = dict(story=story_dir.name, status="", steps={})
    res = check.check_script(script, p7)
    rec["steps"]["check"] = dict(seconds=round(time.time() - t0, 2), swaps=res["swaps"], stop=res["stop"])
    if res["stop"]:
        return dict(rec, status="stopped", why=res["stop"])
    directed = None
    if direction and getattr(engine, "tags", False):
        td = time.time()
        d = direct.reuse(out_dir / "direction.json", res["beats"])    # same lines as last time: same tags, saved voice
        if d is None:
            d = direct.direct(res["beats"], script.get("title") or "", complete)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "direction.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        directed = [x["tagged"] for x in d["lines"]]
        rec["steps"]["direction"] = dict(seconds=round(time.time() - td, 2), model=d["model"],
                                         calls=0 if d.get("reused") else d["calls"], reused=bool(d.get("reused")),
                                         tags=d["tags"], refused=d["refused"], answered=d["answered"])
    t1 = time.time()
    narr = voice.narrate(res["beats"], engine, cache_dir=voice_cache, directed=directed, trim_opening=True)
    credits = narr.get("credits_now") or 0
    if narr["duration"] > MAX_SECONDS:
        # too long: play the same recording a little faster (free). A second recording at the voice's own
        # speed setting cost the credits again and came out no shorter on eleven_v4_turbo (Nov 26).
        tempo = min(voice.MAX_TEMPO, narr["seconds"] / (MAX_SECONDS - FIT_MARGIN - voice.HOLD))
        narr = voice.narrate(res["beats"], engine, cache_dir=voice_cache, directed=directed, tempo=tempo,
                             trim_opening=True)
    rec["steps"]["voice"] = dict(seconds=round(time.time() - t1, 2), reused=narr["reused"], tempo=narr["tempo"],
                                 credits=credits, voice=narr["voice"], duration=narr["duration"], chars=narr["chars"])
    t2 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(narr["audio"], out_dir / "narration.mp3")
    if music:
        shutil.copyfile(music, out_dir / Path(music).name)
    pl = plan.build(res["beats"], narr, script, sf["event"], swaps=res["swaps"], music=Path(music).name if music else None, p7=p7)
    (out_dir / "plan.json").write_text(json.dumps(pl, ensure_ascii=False), encoding="utf-8")
    rec["steps"]["plan"] = dict(seconds=round(time.time() - t2, 2), frames=pl["frames"], beats=len(pl["beats"]),
                                swaps=pl["swaps"], captions=len(pl["captions"]))
    return dict(rec, status="planned", plan=str(out_dir / "plan.json"), out_dir=str(out_dir))


def make(story_dir: Path, engine=None, out_dir: Path | None = None, *, music: Path | None = None,
         render: bool = True, extra: list[str] = (), trace: bool = True, direction: bool = True, complete=None,
         trace_id: str | None = None) -> dict:
    """The whole module for one story: plan, MP4, loudness, poster, captions files and render.json.
    Each step's time goes to the local call log and Langfuse, into the trace `trace_id` when one is given
    (the live pipeline's trace for this video), else into a trace of this module's own."""
    engine = engine or voice.ElevenLabs()
    out_dir = Path(out_dir or story_dir / "video")
    started = time.time()
    if trace and not trace_id:
        trace_id = tracing.tracer().new_trace(f"video:{story_dir.name[:8]}", metadata=dict(module=8))
    rec = prepare(story_dir, engine, out_dir, music=music, direction=direction, complete=complete,
                  trace_id=trace_id if trace else None)
    if trace:
        rec["trace_id"] = trace_id
    if rec["status"] == "planned" and render:
        t = time.time()
        raw = out_dir / "render.mp4"
        r = render_step.render(Path(rec["plan"]), out_dir, raw, extra=list(extra))
        rec["steps"]["render"] = dict(r, seconds=round(time.time() - t, 2))
        t = time.time()
        pl = json.loads(Path(rec["plan"]).read_text(encoding="utf-8"))
        rec = files.finish(raw, pl, out_dir, dict(rec, status="rendered"))
        rec["steps"]["files"] = dict(seconds=round(time.time() - t, 2))
        rec["seconds"] = round(time.time() - started, 2)
        (out_dir / "render.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if trace:
        _trace(rec, trace_id)
    return rec


def _trace(rec: dict, trace_id: str) -> None:
    """One span per step of this module, in the video's trace."""
    tr = tracing.tracer()
    for name, st in rec.get("steps", {}).items():
        tr.span(name=f"video.{name}", trace_id=trace_id, metadata={k: v for k, v in st.items() if k != "voice"},
                output=dict(seconds=st.get("seconds")), error=st.get("stop"))
    tr.flush()
