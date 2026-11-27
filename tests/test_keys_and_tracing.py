"""Key lookup and the one-trace-per-video plumbing. No keys, no network."""
import subprocess
from types import SimpleNamespace

import pytest

from stringer import keys, tracing
from stringer.video import direct, files, make


def test_a_key_that_is_not_set_is_just_missing_on_a_machine_without_a_keychain(monkeypatch):
    def no_security_tool(*a, **k):
        raise FileNotFoundError("security")
    monkeypatch.setattr(subprocess, "run", no_security_tool)
    monkeypatch.delenv("STRINGER_TEST_ONLY_KEY", raising=False)
    keys.get.cache_clear()
    assert keys.has("stringer_test_only_key") is False                 # used to raise FileNotFoundError on Linux
    with pytest.raises(keys.MissingKey):
        keys.get("stringer_test_only_key")
    monkeypatch.setenv("STRINGER_TEST_ONLY_KEY", "abc")
    assert keys.get("stringer_test_only_key") == "abc"
    keys.get.cache_clear()


def test_loudness_is_read_from_the_meters_summary():
    text = """[Parsed_ebur128_0 @ 0x1] t: 63.8   TARGET:-23 LUFS    M: -15.1 S: -14.9     I: -14.6 LUFS       LRA:   2.1 LU
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -14.5 LUFS
    Threshold: -24.7 LUFS

  Loudness range:
    LRA:         2.2 LU
    Threshold: -34.6 LUFS
    LRA low:   -15.9 LUFS
    LRA high:  -13.7 LUFS

  True peak:
    Peak:       -2.2 dBFS
"""
    assert files.read_ebur128(text) == {"input_i": -14.5, "input_tp": -2.2, "input_lra": 2.2}
    with pytest.raises(RuntimeError):
        files.read_ebur128("no audio stream")


class Recorder(tracing.Tracer):
    def __init__(self, tmp):
        super().__init__(log_dir=tmp, enable_langfuse=False)
        self.new, self.spans = [], []

    def new_trace(self, name, metadata=None):
        self.new.append(name)
        return f"trace-{len(self.new)}"

    def span(self, **kw):
        self.spans.append(kw)


def test_the_video_steps_join_the_trace_they_are_given(monkeypatch, tmp_path):
    rec = Recorder(tmp_path)
    monkeypatch.setattr(tracing, "_TRACER", rec)
    steps = {"check": {"seconds": 0.1, "stop": None}, "voice": {"seconds": 9.0, "voice": "x"}}
    make._trace(dict(story="abcdef0123", status="planned", steps=steps), "trace-of-the-video")
    assert rec.new == [] and {s["trace_id"] for s in rec.spans} == {"trace-of-the-video"}
    assert [s["name"] for s in rec.spans] == ["video.check", "video.voice"]


def test_the_voice_director_call_carries_the_trace(monkeypatch):
    seen = {}

    def complete(step, messages, **kw):
        seen.update(step=step, trace_id=kw.get("trace_id"))
        return SimpleNamespace(text="")
    from stringer import models
    monkeypatch.setattr(models, "complete", complete)
    direct.model_call([{"role": "user", "content": "x"}], name="voice direction", model="haiku-5-5", trace_id="t-1")
    assert seen == {"step": "voice_direction", "trace_id": "t-1"}
