"""The Cloud Run job that makes one video (one execution per click; the website starts it).

    python -m scripts.run_job <event id>

The website has already passed the Gate (start) and saved the event as the feed gave it, in the Gate's
store at raw_events/<event id>.json. This picks up the Gate's ticket for that event, runs modules 1-8
(stringer/pipeline.py) in a folder of its own, puts the video, poster and captions in the video bucket
and the story's files in the private bucket, then finishes the ticket: done with the video's address
on the website (/media/..., which streams it from the bucket), no video with the reason, or failed
(a later click may try again)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from stringer import cloud, pipeline
from stringer.gate import Gate, TooCostly
from stringer.gate.core import safe_id

MEDIA_FILES = ("video.mp4", "poster.jpg", "captions.vtt", "captions.srt")
PRIVATE_FILES = ("gather.json", "lens.json", "same_story.json", "balance.json", "picked.json", "story_file.json",
                 "facts.jsonl", "checked_story_file.json", "script.json", "pipeline.json")


def upload_outputs(story: Path, rec: dict, event_id: str, ticket_id: str) -> dict:
    vb, pb = cloud.setting("STRINGER_VIDEO_BUCKET"), cloud.setting("STRINGER_PRIVATE_BUCKET")
    base = f"videos/{safe_id(event_id)}/{ticket_id}"
    urls = {}
    out = Path(rec["video"]["mp4"]).parent
    for f in MEDIA_FILES:
        if (out / f).exists():
            cloud.upload(vb, f"{base}/{f}", out / f, cache="private, max-age=3600")
            urls[f] = f"/media/{base}/{f}"
    for f in PRIVATE_FILES:
        if (story / f).exists():
            cloud.upload(pb, f"stories/{safe_id(event_id)}/{ticket_id}/{f}", story / f, cache="no-store")
    return dict(url=urls.get("video.mp4"), poster=urls.get("poster.jpg"), captions=urls.get("captions.vtt"),
                duration_s=rec["video"].get("duration_s"), seconds=rec.get("seconds"), usd=rec.get("usd"))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        sys.exit("usage: python -m scripts.run_job <event id>")
    event_id = argv[0]
    g = Gate()
    ticket = g.ticket(event_id)
    if ticket is None:
        print(f"{event_id}: no running ticket (taken over, finished or never started); nothing to do")
        return 0
    raw, _ = g.store.get(f"raw_events/{safe_id(event_id)}.json")
    if not raw:
        ticket.finish(error="the event wasn't saved before the job started")
        return 1
    work = Path(os.environ.get("STRINGER_WORK") or tempfile.mkdtemp(prefix="stringer-"))
    try:
        rec = pipeline.run(raw, ticket, stories_dir=work / "stories", raw_dir=work / "raw")
    except TooCostly as e:
        ticket.finish(no_video=f"too costly: {e}")
        print(f"no video: too costly: {e}")
        return 0
    except Exception as e:
        ticket.finish(error=repr(e))
        raise
    if rec["outcome"] != "done":
        ticket.finish(no_video=rec["why"])
        print(f"no video: {rec['why']}")
        return 0
    video = upload_outputs(work / "stories" / event_id, rec, event_id, ticket.id)
    ticket.finish(video=video)
    print(f"done in {rec['seconds']:.0f} s, ${rec['usd']:.3f}: {video['url']}")
    for name, s in rec["steps"].items():
        print(f"  {name:<12} {s['seconds']:>6.1f} s  ${s['usd']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
