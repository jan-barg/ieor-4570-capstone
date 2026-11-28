"""The hot score and the front page's variety rule (stringer/hot.py). Made-up events only."""
from __future__ import annotations

import datetime as dt
import random

import pytest

from stringer import hot

NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)


def at(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def event(eid="e", reports=12, recent=5, newest_h=2.0, severity=3, country="Freedonia", **kw):
    """`reports` reports: `recent` of them inside the last 6 hours (the newest `newest_h` ago), the rest older."""
    times = [newest_h + i * 0.5 for i in range(recent)] + [7 + i for i in range(reports - recent)]
    return dict(id=eid, report_count=reports, severity=severity, country=country,
                sources=[{"url": f"https://example.org/{eid}/{i}", "published_at": at(h)} for i, h in enumerate(times)],
                created_at=at(max(times) if times else 1), **kw)


def test_the_docstring_example():
    s = hot.score(event(), NOW)
    assert s["recent"] == 5 and s["hours"] == 2.0
    assert s["hot"] == pytest.approx(5.555, abs=0.01)


def test_momentum_counts_only_the_last_six_hours_and_never_the_future():
    e = event(reports=10, recent=3)
    e["sources"].append({"url": "https://example.org/later", "published_at": at(-1)})    # an hour from now
    assert hot.score(e, NOW)["recent"] == 3


def test_freshness_halves_every_half_life():
    e = event(reports=6, recent=0, newest_h=9)
    later = hot.score(e, NOW + dt.timedelta(hours=hot.HALF_LIFE_H))
    assert later["hot"] == pytest.approx(hot.score(e, NOW)["hot"] / 2, rel=0.01)


def test_severity_is_a_small_bump_and_no_sources_falls_back_to_updated_at():
    two, four = hot.score(event(severity=2), NOW), hot.score(event(severity=4), NOW)
    assert four["hot"] == pytest.approx(two["hot"] * 1.5, rel=0.001)
    bare = {"id": "b", "report_count": 8, "severity": 2, "updated_at": at(8), "created_at": at(30)}
    assert hot.score(bare, NOW)["hours"] == 8.0 and hot.score(bare, NOW)["recent"] == 0


def test_rank_orders_by_score_and_keeps_three_per_country():
    evs = [event(f"f{i}", reports=20 - i, country="Freedonia") for i in range(5)] + [event("s", reports=8, country="Sylvania")]
    ranked = hot.rank(evs, NOW)
    assert [e["id"] for e in ranked] == ["f0", "f1", "f2", "s"]                 # the 4th and 5th Freedonia ones drop
    every = hot.rank(evs, NOW, top=None, drop=False)                            # the video feed keeps them, later
    assert [e["id"] for e in every] == ["f0", "f1", "f2", "s", "f3", "f4"]


def test_one_slot_per_chain_shows_its_newest_event_and_a_run_being_made_stays():
    old = event("old", reports=40, recent=0, newest_h=10)          # hotter, but an earlier step of the story
    new = event("new", reports=8, recent=2, newest_h=1)            # first report 12 h ago, the old one's 46 h ago
    other = event("other", reports=9, country="Sylvania")
    chain = {"old": "c1", "new": "c1"}
    ranked = hot.rank([old, new, other], NOW, chain_of=lambda e: chain.get(e["id"]))
    assert {e["id"] for e in ranked} == {"new", "other"}
    kept = hot.rank([old, new, other], NOW, chain_of=lambda e: chain.get(e["id"]), keep=lambda e: e["id"] == "old")
    assert {e["id"] for e in kept} == {"old", "new", "other"}
    cut = hot.rank([event(f"x{i}", country=f"C{i}") for i in range(12)] + [event("mk", reports=7, recent=0, newest_h=40)],
                   NOW, keep=lambda e: e["id"] == "mk")
    assert len(cut) == 11 and cut[-1]["id"] == "mk"                 # the top 10, then the one being made


def test_the_variety_rule_holds_on_a_random_feed():
    rng = random.Random(7)
    evs = [event(f"r{i}", reports=rng.randint(7, 60), recent=rng.randint(0, 6), newest_h=rng.uniform(0.1, 30),
                 severity=rng.randint(1, 5), country=rng.choice(["A", "B", "C", "D"])) for i in range(60)]
    chain = {e["id"]: f"c{rng.randint(0, 15)}" for e in evs if rng.random() < 0.5}
    ranked = hot.rank(evs, NOW, chain_of=lambda e: chain.get(e["id"]))
    assert len(ranked) == hot.TOP
    chains = [chain[e["id"]] for e in ranked if e["id"] in chain]
    assert len(chains) == len(set(chains))                          # no story twice
    for c in "ABCD":
        assert sum(e["country"] == c for e in ranked) <= hot.PER_COUNTRY
    scores = [hot.score(e, NOW)["hot"] for e in ranked]
    assert scores == sorted(scores, reverse=True)
