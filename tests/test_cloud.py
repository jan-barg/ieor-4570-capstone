"""cloud.py's calls, with a fake Google session: nothing leaves the machine."""
from types import SimpleNamespace as NS

import pytest

from stringer import cloud


class FakeSession:
    def __init__(self, delete_status=204):
        self.calls = []
        self.delete_status = delete_status

    def post(self, url, **kw):
        self.calls.append(("post", url, kw))
        body = kw.get("data").read() if kw.get("data") is not None else None
        self.calls[-1][2]["body"] = body
        return NS(raise_for_status=lambda: None, json=lambda: {"name": "operations/op-1"})

    def get(self, url, **kw):
        self.calls.append(("get", url, kw))
        return NS(status_code=206, headers={"Content-Range": "bytes 0-9/100"})

    def delete(self, url, **kw):
        self.calls.append(("delete", url, kw))
        return NS(status_code=self.delete_status, raise_for_status=lambda: None)


@pytest.fixture
def fake(monkeypatch):
    s = FakeSession()
    monkeypatch.setattr(cloud, "_session", s)
    return s


def test_upload_names_the_object_and_its_type(fake, tmp_path):
    f = tmp_path / "video.mp4"
    f.write_bytes(b"\x00\x01")
    assert (cloud.upload("made-up-bucket", "videos/abc/video.mp4", f, cache="private, max-age=0")
            == "gs://made-up-bucket/videos/abc/video.mp4")
    kind, url, kw = fake.calls[0]
    assert kind == "post" and "/b/made-up-bucket/o" in url
    assert kw["params"] == {"uploadType": "media", "name": "videos/abc/video.mp4"}
    assert kw["headers"] == {"Content-Type": "video/mp4", "Cache-Control": "private, max-age=0"}
    assert kw["body"] == b"\x00\x01"


def test_open_object_streams_and_passes_the_range_through(fake):
    r = cloud.open_object("made-up-bucket", "videos/abc/video.mp4", range_header="bytes=0-9")
    kind, url, kw = fake.calls[0]
    assert r.status_code == 206 and url.endswith("/o/videos%2Fabc%2Fvideo.mp4")
    assert kw["stream"] is True and kw["headers"] == {"Range": "bytes=0-9"} and kw["params"] == {"alt": "media"}


def test_delete_says_whether_there_was_anything_to_remove(fake, monkeypatch):
    assert cloud.delete("made-up-bucket", "videos/abc/video.mp4") is True
    kind, url, _ = fake.calls[0]
    assert kind == "delete" and url.endswith("/o/videos%2Fabc%2Fvideo.mp4")
    monkeypatch.setattr(cloud, "_session", FakeSession(delete_status=404))
    assert cloud.delete("made-up-bucket", "videos/abc/video.mp4") is False


def test_start_job_sends_the_arguments_as_strings(fake):
    assert cloud.start_job("made-up-project", "us-east1", "stringer-make", ["--event", 42]) == "operations/op-1"
    kind, url, kw = fake.calls[0]
    assert url.endswith("/projects/made-up-project/locations/us-east1/jobs/stringer-make:run")
    assert kw["json"] == {"overrides": {"containerOverrides": [{"args": ["--event", "42"]}]}}


def test_a_missing_setting_says_which(monkeypatch):
    monkeypatch.delenv("STRINGER_MADE_UP", raising=False)
    with pytest.raises(RuntimeError, match="STRINGER_MADE_UP"):
        cloud.setting("STRINGER_MADE_UP")
    assert cloud.setting("STRINGER_MADE_UP", "x") == "x"
