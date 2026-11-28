"""The follow-up check (stringer/followup.py) and the Gate's chains (Gate.join_chain), offline: an in-memory
store, made-up events and a stand-in model. Nothing here is real news."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

from stringer import followup, pipeline
from stringer.gate import Gate, MemoryStore

NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - dt.timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def eid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def raw(n: int, days_ago: float, country="Freedonia", region="Made-up Region", title=None) -> dict:
    return {"id": eid(n), "title": title or f"Made-up event {n}", "summary": "Invented for the test.",
            "country": country, "region": region, "created_at": iso(days_ago),
            "sources": [{"url": f"https://example.org/{n}", "published_at": iso(days_ago)}]}


def gate_with(videos: list[tuple[dict, dict]]) -> Gate:
    """A Gate whose store holds these (raw event, record) pairs."""
    g = Gate(MemoryStore(), complete=None, model="", tavily_left=lambda: 500)
    for r, rec in videos:
        g.store.put(f"raw_events/{r['id']}.json", r, None)
        g.store.put(g._ekey(r["id"]), dict({"id": r["id"]}, **rec), None)
    return g


def done(days_ago: float, **kw) -> dict:
    return dict(state="done", video={"made_at": iso(days_ago), "duration_s": 60.0}, **kw)


class Model:
    """Answers compare_events with a verdict per item, by the item's title."""
    def __init__(self, verdicts: dict):
        self.verdicts, self.calls = verdicts, []

    def __call__(self, messages, name=None, **params):
        self.calls.append(name)
        text = messages[0]["content"][-1]["text"]
        items = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        out = [{"id": it["id"], "verdict": self.verdicts.get(it["headline"], "different"), "reason": "made up"}
               for it in items]
        return SimpleNamespace(text=json.dumps({"verdicts": out}))


def test_candidates_are_the_weeks_shown_videos_anywhere_newest_first():
    g = gate_with([
        (raw(1, 3), done(3)),                                   # 3 days: in
        (raw(2, 1), done(1)),                                   # 1 day: in, first
        (raw(3, 9), done(9)),                                   # too old
        (raw(4, 2.5, country="Sylvania", region="Elsewhere"), done(2.5)),    # far away: in (no place filter)
        (raw(6, 2), done(2, hidden=True)),                      # taken down
        (raw(7, 2), {"state": "making"}),                       # no video yet
    ])
    me = raw(99, 0)
    got = [c["id"] for c in followup.candidates(me, g.store, NOW)]
    assert got == [eid(2), eid(4), eid(1)]
    assert len(followup.candidates(me, g.store, NOW, most=2)) == 2


def test_a_long_week_goes_to_the_model_in_batches(monkeypatch):
    g = gate_with([(raw(n, 0.05 * n, title=f"Made-up event {n}"), done(0.05 * n)) for n in range(1, 31)])
    monkeypatch.setattr(followup, "BATCH", 12)
    model = Model({"Made-up event 30": "follow_up"})
    out = followup.check(raw(99, 0), g, model, NOW)
    assert out["candidates"] == 30 and len(model.calls) == 3
    assert [m["id"] for m in out["matches"]] == [eid(30)] and out["chain"] == eid(30)


def test_a_match_joins_the_chain_both_ways_and_no_candidates_means_no_call():
    g = gate_with([(raw(1, 2, title="Made-up dam bursts"), done(2)),
                   (raw(2, 1, title="Made-up port strike ends"), done(1))])
    model = Model({"Made-up dam bursts": "follow_up"})
    out = followup.check(raw(9, 0, title="Made-up dam inquiry opens"), g, model, NOW)
    assert out["candidates"] == 2 and [m["id"] for m in out["matches"]] == [eid(1)] and out["chain"] == eid(1)
    assert g.store.get(g._ekey(eid(9)))[0]["chain"] == eid(1) == g.store.get(g._ekey(eid(1)))[0]["chain"]
    assert "chain" not in g.store.get(g._ekey(eid(2)))[0]
    lone = gate_with([(raw(1, 9), done(9))])                     # only a video older than a week
    quiet = Model({})
    alone = followup.check(raw(9, 0), lone, quiet, NOW)
    assert (alone["candidates"], alone["matches"], alone["chain"], quiet.calls) == (0, [], None, [])


def test_matches_in_two_chains_join_them_under_the_oldest():
    g = gate_with([(raw(1, 5), done(5, chain=eid(1))), (raw(2, 4), done(4, chain=eid(1))),
                   (raw(3, 2), done(2, chain=eid(3))), (raw(4, 1), done(1, chain=eid(3)))])
    cid = g.join_chain(eid(9), [eid(2), eid(4)])                 # oldest first: eid(2) sits in chain eid(1)
    assert cid == eid(1)
    assert {g.store.get(g._ekey(eid(n)))[0]["chain"] for n in (1, 2, 3, 4, 9)} == {eid(1)}
    assert g.join_chain(eid(9), []) is None and g.join_chain(eid(9), [eid(9)]) is None
    assert any(e["kind"] == "chain" and e["chain"] == eid(1) for e in g.log())


def test_the_pipeline_check_never_stops_a_video(monkeypatch):
    assert pipeline._start_followup(raw(9, 0), None, "t", eid(9), print) is None       # no Gate: no check
    def boom(*a, **kw):
        raise RuntimeError("store down")
    monkeypatch.setattr(followup, "check", boom)
    ticket = SimpleNamespace(gate=gate_with([]))
    out = pipeline._end_followup(pipeline._start_followup(raw(9, 0), ticket, "t", eid(9), lambda *a: None),
                                 lambda *a: None)
    assert out == {"error": "RuntimeError: store down"}
