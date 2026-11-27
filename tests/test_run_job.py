"""The Cloud Run job (scripts/run_job.py): every way a run can end finishes its ticket and keeps its files.
The Gate, the pipeline and Cloud Storage are stand-ins; the event is made up."""
import json

import pytest

from scripts import run_job
from stringer.gate import Gate, MemoryStore, TooCostly, VideoOverBudget

EVENT = dict(id="test-job-1", title="Parliament Passes Budget", summary="Lawmakers approved the annual budget.",
             category="political", subtype="legislation", severity=2, confidence=55, report_count=9, country="Freedonia")


@pytest.fixture
def job(monkeypatch, tmp_path):
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=None, voice_left=None)
    t = g.start(EVENT, "visitor").ticket
    g.store.update(f"raw_events/{EVENT['id']}.json", lambda cur: (EVENT, None))
    bucket, log, state = {}, [], dict(fail_upload=(), run=None)

    def upload(b, name, path, **kw):
        if any(name.endswith(x) for x in state["fail_upload"]):
            raise ConnectionError(f"could not upload {name}")
        bucket[(b, name)] = path.read_bytes()
        log.append(("upload", name))
        return ""

    def delete(b, name, **kw):
        log.append(("delete", name))
        return bucket.pop((b, name), None) is not None

    def run(raw, ticket, stories_dir=None, raw_dir=None, **kw):
        import shutil
        story = stories_dir / raw["id"]
        shutil.rmtree(story, ignore_errors=True)          # each execution of the real job starts in an empty folder
        (story / "video").mkdir(parents=True)
        return state["run"](story, ticket)
    monkeypatch.setenv("STRINGER_VIDEO_BUCKET", "vids")
    monkeypatch.setenv("STRINGER_PRIVATE_BUCKET", "priv")
    monkeypatch.setenv("STRINGER_WORK", str(tmp_path / "work"))
    monkeypatch.setattr(run_job, "Gate", lambda: g)
    monkeypatch.setattr(run_job.cloud, "upload", upload)
    monkeypatch.setattr(run_job.cloud, "delete", delete)
    monkeypatch.setattr(run_job.pipeline, "run", run)
    finishes = []
    real_finish = type(t).finish

    def finish(self, **kw):
        log.append(("finish", next(k for k, v in kw.items() if v is not None)))
        finishes.append(kw)
        return real_finish(self, **kw)
    monkeypatch.setattr(type(t), "finish", finish)
    return dict(gate=g, ticket=t, bucket=bucket, log=log, state=state, finishes=finishes)


def made(story, usd=0.2):
    for f in ("video.mp4", "poster.jpg", "captions.vtt"):
        (story / "video" / f).write_bytes(b"x")
    (story / "video" / "render.json").write_text("{}")
    for f in ("pipeline.json", "script.json", "articles.jsonl"):
        (story / f).write_text("{}")
    return {"outcome": "done", "seconds": 250.0, "usd": usd, "steps": {},
            "video": {"mp4": str(story / "video" / "video.mp4"), "duration_s": 61.0}}


def test_a_finished_video_tells_the_gate_before_the_story_files_go_up(job):
    job["state"]["run"] = lambda story, ticket: made(story)
    assert run_job.main([EVENT["id"]]) == 0
    eid, tid = EVENT["id"], job["ticket"].id
    v = job["gate"].view(eid)
    assert v["state"] == "has_video" and v["video"]["url"] == f"/media/videos/{eid}/{tid}/video.mp4"
    assert job["gate"].may_watch(f"videos/{eid}/{tid}/poster.jpg")
    names = [n for kind, n in job["log"] if kind == "upload"]
    done_at = job["log"].index(("finish", "video"))
    assert all(n.startswith("videos/") for kind, n in job["log"][:done_at] if kind == "upload")
    assert f"stories/{eid}/script.json" in names[names.index(f"videos/{eid}/{tid}/captions.vtt"):]
    assert ("priv", f"stories/{eid}/articles.jsonl") in job["bucket"] and ("priv", f"stories/{eid}/render.json") in job["bucket"]
    note = json.loads(job["bucket"][("priv", f"stories/{eid}/run.json")])
    assert note["ticket"] == tid and note["outcome"] == "done" and "pipeline.json" in note["files"]


def test_no_video_and_a_crash_keep_their_files_and_a_rerun_overwrites_them(job):
    eid = EVENT["id"]

    def no_video(story, ticket):
        (story / "pipeline.json").write_text('{"outcome": "no_video"}')
        (story / "script.json").write_text('{"status": "no video"}')
        return {"outcome": "no_video", "why": "script: the hook beat still fails", "seconds": 200.0, "usd": 0.1}
    job["state"]["run"] = no_video
    assert run_job.main([eid]) == 0
    assert job["gate"].view(eid) == {"state": "no_video", "reason": "script: the hook beat still fails"}
    assert job["bucket"][("priv", f"stories/{eid}/script.json")] == b'{"status": "no video"}'

    # a remake that crashes early: its files replace the old run's, and what it didn't make is removed
    job["gate"].remake(eid, by="jan")
    job["gate"].start(EVENT, "visitor")

    def crash(story, ticket):
        (story / "pipeline.json").write_text('{"outcome": "failed"}')
        raise RuntimeError("the search service is down")
    job["state"]["run"] = crash
    with pytest.raises(RuntimeError, match="search service"):
        run_job.main([eid])
    assert job["finishes"][-1]["error"].startswith("RuntimeError")
    assert job["gate"].view(eid) == {"state": "ready", "failed": True}            # a later click may try again
    assert job["bucket"][("priv", f"stories/{eid}/pipeline.json")] == b'{"outcome": "failed"}'
    assert ("priv", f"stories/{eid}/script.json") not in job["bucket"]            # the old run's script is gone
    assert json.loads(job["bucket"][("priv", f"stories/{eid}/run.json")])["outcome"] == "failed"


def test_a_failed_video_upload_finishes_the_ticket_as_failed(job):
    job["state"].update(run=lambda story, ticket: made(story), fail_upload=("video.mp4",))
    with pytest.raises(ConnectionError):
        run_job.main([EVENT["id"]])
    assert job["finishes"][-1]["error"].startswith("ConnectionError")
    assert job["gate"].view(EVENT["id"]) == {"state": "ready", "failed": True}    # not stuck at "making"
    assert ("priv", f"stories/{EVENT['id']}/pipeline.json") in job["bucket"]      # the story files still went up


def test_going_over_the_cap_is_final_like_too_costly(job):
    def over(story, ticket):
        raise VideoOverBudget("spent $5.20, over the $5.00 cap")
    job["state"]["run"] = over
    assert run_job.main([EVENT["id"]]) == 0
    assert job["gate"].view(EVENT["id"])["state"] == "no_video"

    job["gate"].remake(EVENT["id"], by="jan")
    job["gate"].start(EVENT, "visitor")

    def costly(story, ticket):
        raise TooCostly("the rest would pass the cap")
    job["state"]["run"] = costly
    assert run_job.main([EVENT["id"]]) == 0
    assert job["gate"].view(EVENT["id"])["reason"].startswith("too costly")


def test_a_story_file_that_fails_to_upload_does_not_stop_the_others(job):
    job["state"].update(run=lambda story, ticket: made(story), fail_upload=("script.json",))
    assert run_job.main([EVENT["id"]]) == 0
    assert job["gate"].view(EVENT["id"])["state"] == "has_video"
    assert ("priv", f"stories/{EVENT['id']}/articles.jsonl") in job["bucket"]
