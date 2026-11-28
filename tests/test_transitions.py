"""Transitions between beats (stringer/video/transitions.py, render/src/transitions.js): made-up beats only."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from stringer.video import make, transitions as tx

ROOT = Path(__file__).resolve().parents[1]


def beats(*shots, frames=150):
    """Made-up plan beats: one per shot, `frames` long each (a number or one per shot)."""
    lengths = frames if isinstance(frames, (list, tuple)) else [frames] * len(shots)
    out, start = [], 0
    for i, (shot, f) in enumerate(zip(shots, lengths)):
        out.append(dict(n=i + 1, shot=shot, start=start, end=start + f, frames=f))
        start += f
    return out


STORY = ("hook", "claim_vs_claim", "map_locate", "map_link", "headline", "big_number", "sides", "sources")


@pytest.mark.parametrize("value, how", [
    (None, "mix"), ("", "mix"), ("nonsense", "mix"), ("1", "mix"), ("on", "mix"), ("MIX", "mix"), (" yes ", "mix"),
    ("off", "off"), ("0", "off"), ("OFF", "off"), ("cuts", "off"),
    ("tear", "tear"), ("Slide", "slide"), ("dissolve", "dissolve"), ("push", "push"), ("wipe", "wipe"),
])
def test_the_mix_is_on_unless_switched_off_and_a_kind_is_read_by_name(value, how, monkeypatch):
    monkeypatch.delenv("STRINGER_TRANSITIONS", raising=False)
    assert tx.style(value) == how
    if value is not None:
        monkeypatch.setenv("STRINGER_TRANSITIONS", value)
        assert tx.style() == how
        assert tx.style("off") == "off"              # an explicit value wins over the environment


def test_off_leaves_every_beat_as_it_was():
    b = beats(*STORY)
    before = json.dumps(b)
    assert tx.add(b, "off") == {}
    assert json.dumps(b) == before
    assert tx.choose(b, "off") == [None] * len(b)


def test_the_mix_moves_where_the_story_turns_a_page_and_cuts_between_cards():
    b = beats(*STORY)
    note = tx.add(b, "mix")
    #            hook>claims  claims>map   map>map  map>headline headline>number number>sides sides>sources
    assert note == dict(style="mix", kinds=["tear", "dissolve", "push", "dissolve", "cut", "slide", "dissolve"])
    assert "enter" not in b[0]
    assert "enter" not in b[5]                       # headline to big number: two cards, a cut
    assert b[1]["enter"] == dict(kind="tear", frames=tx.KINDS["tear"], pre=tx.KINDS["tear"] // 3)


def test_the_mix_keeps_cuts_in_a_run_of_cards():
    kinds = tx.choose(beats("hook", "big_number", "headline", "headline", "tally", "sides", "sources"), "mix")
    assert kinds == [None, "tear", None, None, None, "slide", "dissolve"]


@pytest.mark.parametrize("kind", sorted(tx.KINDS))
def test_a_kind_by_name_is_used_at_every_change(kind):
    b = beats(*STORY)
    tx.add(b, kind)
    assert "enter" not in b[0]
    assert {x["enter"]["kind"] for x in b[1:]} == {kind}


@pytest.mark.parametrize("how", ["mix", "slide"])
def test_a_beat_too_short_to_move_in_gets_a_cut_on_both_sides(how):
    short = tx.MIN_FRAMES - 1
    kinds = tx.choose(beats("hook", "map_locate", "map_locate", "headline", frames=[150, short, 150, 150]), how)
    assert kinds[1] is None and kinds[2] is None     # into and out of the short beat
    assert kinds[3] == ("dissolve" if how == "mix" else "slide")     # the next change moves as usual


def test_every_change_fits_in_its_beats_and_starts_in_the_pause():
    for kind, frames in tx.KINDS.items():
        b = beats(*STORY, frames=tx.MIN_FRAMES)
        tx.add(b, kind)
        for x in b[1:]:
            e = x["enter"]
            assert 0 < e["pre"] < e["frames"] < tx.MIN_FRAMES
            assert e["frames"] == frames


def test_every_kind_has_a_drawing_and_the_renderer_holds_beats_for_it():
    js = (ROOT / "render" / "src" / "transitions.js").read_text()
    drawn = set(re.findall(r"case '(\w+)'", js))
    assert set(tx.KINDS) - {"dissolve"} <= drawn      # dissolve is the default case of both looks
    assert "dissolve" in js
    video = (ROOT / "render" / "src" / "Video.jsx").read_text()
    assert "next.enter.frames - pre(next)" in video and "beat.start - lead" in video


def test_the_maker_draws_the_mix_unless_switched_off(tmp_path, monkeypatch):
    seen = []

    def prepare(story_dir, engine, out_dir, **kw):
        seen.append(kw)
        return dict(status="stopped", why="test")
    monkeypatch.setattr(make, "prepare", prepare)
    monkeypatch.delenv("STRINGER_TRANSITIONS", raising=False)
    make.make(tmp_path, object(), tmp_path / "out", render=False, trace=False, anim=False)
    assert seen[-1]["transitions"] == "mix"
    monkeypatch.setenv("STRINGER_TRANSITIONS", "off")
    make.make(tmp_path, object(), tmp_path / "out", render=False, trace=False, anim=False)
    assert "transitions" not in seen[-1]             # off: the call is exactly as before transitions
    make.make(tmp_path, object(), tmp_path / "out", render=False, trace=False, anim=False, transitions="tear")
    assert seen[-1]["transitions"] == "tear"
