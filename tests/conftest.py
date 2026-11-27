"""Shared test setup: the tests stay offline and leave nothing behind.

Two things every test gets, without asking:
  - a tracer that writes to a temp folder with Langfuse off. Before this (Nov 27 review), tests that used
    a fake Tavily or the eval runner logged through the real tracer: each run added made-up lines to
    stringer_private/runs/calls-<day>.jsonl and sent made-up traces and eval scores to Langfuse;
  - the folders in stringer.paths put back afterwards (pipeline.run points STORIES and RAW at its run);
  - no look at the ElevenLabs account: a Gate made without voice_left= would otherwise ask the real one.
"""
import pytest

from stringer import paths, tracing
from stringer.gate import credits

_PATH_NAMES = ("STORIES", "RAW", "ARTICLE_CACHE", "RUNS")


@pytest.fixture(autouse=True)
def offline_tracer(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("STRINGER_NO_LANGFUSE", "1")
    log = tmp_path_factory.mktemp("calls")
    monkeypatch.setattr(tracing, "_TRACER", tracing.Tracer(log_dir=log, enable_langfuse=False))
    monkeypatch.setattr(paths, "RUNS", log)
    yield


@pytest.fixture(autouse=True)
def no_credit_lookups(monkeypatch):
    monkeypatch.setattr(credits, "voice_credits_left", lambda *a, **k: None)
    yield


@pytest.fixture(autouse=True)
def restore_paths():
    before = {n: getattr(paths, n) for n in _PATH_NAMES}
    yield
    for n, v in before.items():
        setattr(paths, n, v)
