"""Step 6: checks the rendered MP4 and writes what goes with it (design settled Nov 26).

  - loudness: measured, then set to -14 LUFS (the level TikTok and Instagram play at), true peak at most
    -1.5 dB, in two ffmpeg passes; the picture is copied untouched;
  - the file's facts from ffprobe, checked against what the plan asked for;
  - poster.jpg: the hook, once its title has decoded;
  - captions.vtt and captions.srt: every spoken word (the burned-in captions leave out words already on
    screen; these files don't, they are for people who can't hear the video);
  - render.json: the record of the whole run.

    rec = finish(raw_mp4, plan, out_dir, record)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

LUFS, TRUE_PEAK, LRA = -14.0, -1.5, 11.0
LUFS_TOLERANCE = 1.0
SECONDS_TOLERANCE = 0.15


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def probe(mp4: Path) -> dict:
    out = json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)]).stdout)
    v = next((s for s in out["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in out["streams"] if s["codec_type"] == "audio"), {})
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    return dict(width=v.get("width"), height=v.get("height"), fps=round(int(num) / max(1, int(den)), 3),
                video_codec=v.get("codec_name"), pixel_format=v.get("pix_fmt"), audio_codec=a.get("codec_name"),
                audio_rate=int(a.get("sample_rate") or 0), seconds=round(float(out["format"].get("duration") or 0), 3),
                megabytes=round(int(out["format"].get("size") or 0) / 1e6, 2))


def loudness(mp4: Path) -> dict:
    """EBU R128 measurement of the file's audio (integrated LUFS, true peak, range)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-af",
                          f"loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA={LRA}:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        raise RuntimeError(f"no loudness measurement for {mp4.name}")
    return json.loads(m.group(0))


LIMIT_DB = TRUE_PEAK - 1.0      # the limiter's ceiling: 1 dB of room for the AAC encoder's overshoot


def normalise(src: Path, dst: Path) -> dict:
    """Measure, then raise the whole mix to -14 LUFS with one fixed gain and catch the few peaks that would go over
    with a limiter (Nov 26: with the music bed, ffmpeg's loudnorm fell back to its dynamic mode on two videos and
    their true peaks came out at -0.55 and +0.84 dB). Returns the before and after measurements."""
    before = loudness(src)
    gain = LUFS - float(before["input_i"])
    af = f"volume={gain:.2f}dB,alimiter=limit={10 ** (LIMIT_DB / 20):.4f}:attack=5:release=50:level=disabled"
    _run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-c:v", "copy", "-af", af, "-ar", "44100",
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)])
    after = loudness(dst)
    return dict(before_lufs=float(before["input_i"]), before_true_peak=float(before["input_tp"]),
                lufs=float(after["input_i"]), true_peak=float(after["input_tp"]), range=float(after["input_lra"]))


def poster(mp4: Path, plan: dict, out: Path) -> Path:
    hook = plan["beats"][0]
    t = (hook["start"] + 0.75 * (hook["end"] - hook["start"])) / plan["fps"]
    _run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", "-q:v", "3", str(out)])
    return out


def _stamp(frames: int, fps: int, sep: str) -> str:
    ms = round(frames * 1000 / fps)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def vtt(subs: list[dict], fps: int) -> str:
    cues = [f"{_stamp(c['start'], fps, '.')} --> {_stamp(c['end'], fps, '.')}\n{' '.join(w['w'] for w in c['words'])}"
            for c in subs]
    return "WEBVTT\n\n" + "\n\n".join(cues) + "\n"


def srt(subs: list[dict], fps: int) -> str:
    cues = [f"{i}\n{_stamp(c['start'], fps, ',')} --> {_stamp(c['end'], fps, ',')}\n{' '.join(w['w'] for w in c['words'])}"
            for i, c in enumerate(subs, 1)]
    return "\n\n".join(cues) + "\n"


def problems(facts: dict, loud: dict, plan: dict) -> list[str]:
    """What's wrong with the file against the plan (an empty list means it's good)."""
    out = []
    if (facts["width"], facts["height"]) != (plan["width"], plan["height"]):
        out.append(f"size {facts['width']}x{facts['height']}, not {plan['width']}x{plan['height']}")
    if abs(facts["fps"] - plan["fps"]) > 0.01:
        out.append(f"{facts['fps']} frames a second, not {plan['fps']}")
    if facts["video_codec"] != "h264" or facts["audio_codec"] != "aac":
        out.append(f"codecs {facts['video_codec']}/{facts['audio_codec']}, not h264/aac")
    want = plan["frames"] / plan["fps"]
    if abs(facts["seconds"] - want) > SECONDS_TOLERANCE:
        out.append(f"{facts['seconds']} s long, the plan says {want:.2f} s")
    if abs(loud["lufs"] - LUFS) > LUFS_TOLERANCE:
        out.append(f"loudness {loud['lufs']} LUFS, not {LUFS}")
    if loud["true_peak"] > TRUE_PEAK + 0.5:
        out.append(f"true peak {loud['true_peak']} dB, over {TRUE_PEAK}")
    return out


def finish(raw: Path, plan: dict, out_dir: Path, record: dict, *, keep_raw: bool = False) -> dict:
    """From the raw render to the finished files; returns the record (also written to render.json)."""
    video = out_dir / "video.mp4"
    loud = normalise(raw, video)
    facts = probe(video)
    poster(video, plan, out_dir / "poster.jpg")
    (out_dir / "captions.vtt").write_text(vtt(plan["subtitles"], plan["fps"]), encoding="utf-8")
    (out_dir / "captions.srt").write_text(srt(plan["subtitles"], plan["fps"]), encoding="utf-8")
    if not keep_raw:
        raw.unlink(missing_ok=True)
    skipped = [dict(beat=b["n"], kind=b["broll"]["kind"], name=b["broll"]["name"], why=b["broll"]["skipped"])
               for b in plan["beats"] if b["broll"].get("skipped")]
    rec = dict(record, finished=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               files=dict(video="video.mp4", poster="poster.jpg", captions=["captions.vtt", "captions.srt"], plan="plan.json"),
               video=facts, loudness=loud, problems=problems(facts, loud, plan),
               plan=dict(version=plan["version"], catalog=plan["catalog"], frames=plan["frames"],
                         shots=[b["shot"] for b in plan["beats"]], swaps=plan["swaps"], broll_skipped=skipped),
               post=plan.get("post"), credits=plan["sources_card"].get("credits"))
    (out_dir / "render.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec
