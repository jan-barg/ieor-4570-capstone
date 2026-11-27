"""Makes module 8's videos for frozen stories (design settled Nov 26).

    python scripts/make_videos.py a1b2c3d4 e5f6a7b8          # ElevenLabs voice, outputs in each story's video/
    python scripts/make_videos.py --voice paced --plan-only    # every story, silent paced voice, plans only
    python scripts/make_videos.py a1b2c3d4 --voice-model eleven_flash_v2_5 --no-direct     # the old voice, no director

Story ids may be the first 8 characters. Prints one line per story and writes a summary JSON to
stringer_private/runs/videos-<UTC time>.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stringer import paths  # noqa: E402
from stringer.video import make, voice  # noqa: E402


def story_dirs(ids: list[str]) -> list[Path]:
    all_dirs = sorted(d for d in paths.STORIES.iterdir() if (d / "script.json").exists())
    if not ids:
        return all_dirs
    out = []
    for i in ids:
        hit = [d for d in all_dirs if d.name.startswith(i)]
        if len(hit) != 1:
            raise SystemExit(f"{i}: {len(hit)} stories match")
        out += hit
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--voice", choices=["elevenlabs", "paced"], default="elevenlabs")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--music", type=Path, default=make.MUSIC if make.MUSIC.exists() else None,
                    help="the music bed (default: Jan's ambient track, if it's there)")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="a folder for the outputs (default: each story's video/)")
    ap.add_argument("--voice-model", default=voice.ElevenLabs.MODEL,
                    help="the ElevenLabs model (default v4 Turbo, Jan's pick); v4 Turbo, v4 and v3 read delivery tags")
    ap.add_argument("--no-direct", action="store_true", help="skip the voice director")
    a = ap.parse_args()
    if a.no_music:
        a.music = None
    engine = voice.ElevenLabs(model=a.voice_model) if a.voice == "elevenlabs" else voice.Paced()
    a.direct = not a.no_direct and getattr(engine, "tags", False)
    cache = paths.PRIVATE / "video_cache" / "paced" if a.voice == "paced" else None
    recs = []
    for d in story_dirs(a.ids):
        out = (a.out / d.name[:8]) if a.out else d / "video"
        if a.plan_only:
            rec = make.prepare(d, engine, out, voice_cache=cache, music=a.music, direction=a.direct)
        else:
            rec = make.make(d, engine, out, music=a.music, direction=a.direct)
        recs.append(rec)
        st = rec.get("steps", {})
        print(f"{d.name[:8]}  {rec['status']:<9} {rec.get('why', '')[:80]}"
              f"  {st.get('voice', {}).get('duration', '')} s  credits {st.get('voice', {}).get('credits', '')}"
              f"  render {st.get('render', {}).get('render_seconds', '')} s  problems {rec.get('problems', '')}", flush=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths.RUNS.mkdir(parents=True, exist_ok=True)
    (paths.RUNS / f"videos-{stamp}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
