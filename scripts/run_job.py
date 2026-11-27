"""The Cloud Run job that makes one video (one execution per click; the website starts it).

    python -m scripts.run_job <event id>

The website has already passed the Gate (start) and saved the event as the feed gave it, in the Gate's
store at raw_events/<event id>.json. This picks up the Gate's ticket for that event and runs modules 1-8
(stringer/pipeline.py) in a folder of its own. Then, whatever the outcome:

  1. the ticket is finished first, so the website knows at once:
       done       the video, poster and captions are in the video bucket; the ticket gets the video's
                  address on the website (/media/..., which streams it from the bucket)
       no video   with the reason (final: the story itself, or its cost)
       failed     a crash, a failed upload, or a model that gave no answer (a later click may try again)
  2. the story's files go to the private bucket at stories/<event id>/, also after a "no video" or a
     failure, so there is always something to look at. A later run of the same event overwrites them
     (Jan, Nov 27: "the files should be kept. But then if it is rerun, overwritten."), and files the new
     run did not make are removed, so the folder never mixes two runs.

Before Nov 27 only a finished video's files were uploaded (under a folder per ticket), and an upload
that failed left the event "being made" for 20 minutes."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

from stringer import cloud, paths, pipeline
from stringer.gate import Gate, TooCostly, VideoOverBudget
from stringer.gate.core import safe_id

MEDIA_FILES = ("video.mp4", "poster.jpg", "captions.vtt", "captions.srt")
# What is kept of a run, as (name in the bucket, path inside the story folder). articles.jsonl holds the
# full article texts: private, never served, and needed to check a quote against its article later.
STORY_FILES = (("pipeline.json", "pipeline.json"), ("gather.json", "gather.json"), ("lens.json", "lens.json"),
               ("articles.jsonl", "articles.jsonl"), ("same_story.json", "same_story.json"),
               ("balance.json", "balance.json"), ("picked.json", "picked.json"),
               ("story_file.json", "story_file.json"), ("facts.jsonl", "facts.jsonl"),
               ("checked_story_file.json", "checked_story_file.json"), ("script.json", "script.json"),
               ("direction.json", "video/direction.json"), ("plan.json", "video/plan.json"),
               ("render.json", "video/render.json"))
CALL_LOG, RUN_FILE = "calls.jsonl", "run.json"


def story_base(event_id: str) -> str:
    """Where one event's story files live in the private bucket (the newest run's; see the docstring)."""
    return f"stories/{safe_id(event_id)}"


def upload_media(rec: dict, event_id: str, ticket_id: str) -> dict:
    """The finished video's files into the video bucket, under this ticket's own folder (a video that is
    showing is never overwritten). Returns the record the Gate keeps: addresses on the website."""
    vb = cloud.setting("STRINGER_VIDEO_BUCKET")
    base = f"videos/{safe_id(event_id)}/{ticket_id}"
    urls = {}
    out = Path(rec["video"]["mp4"]).parent
    for f in MEDIA_FILES:
        if (out / f).exists():
            cloud.upload(vb, f"{base}/{f}", out / f, cache="private, max-age=3600")
            urls[f] = f"/media/{base}/{f}"
    if "video.mp4" not in urls:
        raise FileNotFoundError(f"the pipeline said done, but {out / 'video.mp4'} is not there")
    return dict(url=urls["video.mp4"], poster=urls.get("poster.jpg"), captions=urls.get("captions.vtt"),
                duration_s=rec["video"].get("duration_s"), seconds=rec.get("seconds"), usd=rec.get("usd"))


def upload_story(story: Path, event_id: str, ticket_id: str, outcome: str, say=print) -> list[str]:
    """This run's story files and its call log into stories/<event id>/, replacing an earlier run's.
    One file failing doesn't stop the others. Returns the names sent."""
    pb = cloud.setting("STRINGER_PRIVATE_BUCKET")
    base = story_base(event_id)
    todo = [(name, story / rel) for name, rel in STORY_FILES]
    logs = sorted(Path(paths.RUNS).glob("calls-*.jsonl")) if Path(paths.RUNS).is_dir() else []
    if logs:
        todo.append((CALL_LOG, logs[-1]))        # every model call and search of this run, with its seconds
    sent = []
    for name, path in todo:
        try:
            if path.exists():
                cloud.upload(pb, f"{base}/{name}", path, cache="no-store")
                sent.append(name)
            else:
                cloud.delete(pb, f"{base}/{name}")           # an earlier run's copy must not pass for this run's
        except Exception as e:
            say(f"could not put {name} in the private bucket: {e!r}"[:300])
    try:
        note = Path(tempfile.mkdtemp(prefix="stringer-run-")) / RUN_FILE
        note.write_text(json.dumps(dict(event=event_id, ticket=ticket_id, outcome=outcome, files=sent,
                                        at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))),
                        encoding="utf-8")
        cloud.upload(pb, f"{base}/{RUN_FILE}", note, cache="no-store")
    except Exception as e:
        say(f"could not put {RUN_FILE} in the private bucket: {e!r}"[:300])
    return sent


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
    story = work / "stories" / str(raw.get("id", event_id))
    outcome = "failed"
    try:
        rec = pipeline.run(raw, ticket, stories_dir=work / "stories", raw_dir=work / "raw")
        if rec["outcome"] == "done":
            video = upload_media(rec, event_id, ticket.id)       # a failed upload ends in "failed", below
            ticket.finish(video=video)
            outcome = "done"
            print(f"done in {rec['seconds']:.0f} s, ${rec['usd']:.3f}: {video['url']}")
            for name, s in rec["steps"].items():
                print(f"  {name:<12} {s['seconds']:>6.1f} s  ${s['usd']:.4f}")
        else:
            why = rec.get("why") or f"the run ended as {rec['outcome']}"
            ticket.finish(no_video=why)
            outcome = "no_video"
            print(f"no video: {why}")
        return 0
    except (TooCostly, VideoOverBudget) as e:                    # final: the same story would cost the same again
        ticket.finish(no_video=f"too costly: {e}")
        outcome = "no_video"
        print(f"no video: too costly: {e}")
        return 0
    except Exception as e:
        ticket.finish(error=repr(e))
        raise
    finally:
        try:
            upload_story(story, event_id, ticket.id, outcome)
        except Exception as e:                                   # the outcome stands; only its files are missing
            print(f"could not upload the story files: {e!r}"[:300])


if __name__ == "__main__":
    sys.exit(main())
