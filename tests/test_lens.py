"""Choosing a story's sides (module 4, stringer/lens.py). Everything here is made up: invented
outlets on .example domains, invented side lists and invented events. No model is called; a fake
`complete` returns canned answers."""
import csv
import datetime as dt
import json

import pytest

from stringer import lens
from stringer.events import Event
from stringer.outlets import Outlet, OutletTable

COLS = ["outlet_id", "name", "domains", "x_handles", "kind", "country", "us_lean", "us_lean_opinion",
        "opinion_paths", "allsides_name", "allsides_date", "allsides_confidence", "reliability",
        "reliability_domain", "state_media", "state_media_entity", "state_media_year", "wikidata", "notes"]

OUTLETS = [  # id, kind, country, us_lean, state media
    ("leftdaily", "news", "US", "Left", ""), ("centerwire", "wire", "INT", "", ""),
    ("rightpost", "news", "US", "Right", ""), ("leanright", "news", "US", "Lean Right", ""),
    ("leanleft", "news", "US", "Lean Left", ""),
    ("northstate", "news", "NA", "", "State-Controlled"), ("northfree", "news", "NA", "", ""),
    ("southherald", "news", "SA", "", ""), ("southtimes", "news", "SA", "", ""),
    ("eastnews", "news", "EA", "", ""), ("eastgov", "news", "EA", "", "Captured Public"),
    ("worldtv", "news", "GB", "", "Independent Public"), ("vidsite", "platform", "", "", ""),
]
LISTS = [("north", "Northland outlets", "northstate;northfree"),
         ("south", "Southland outlets", "southherald;southtimes"),
         ("east_gov", "Pro-government Eastland outlets", "eastgov"),
         ("east_opp", "Eastland opposition outlets", "eastnews")]
START = dt.datetime(2026, 11, 20, 8, 0, tzinfo=dt.timezone.utc)


def row(oid, kind, country, lean, sm):
    r = {c: "" for c in COLS}
    r.update(outlet_id=oid, name=oid.capitalize(), domains=f"{oid}.example", kind=kind, country=country,
             us_lean=lean, reliability="0.7", state_media=sm)
    return r


@pytest.fixture()
def t():
    return OutletTable([Outlet.from_row(row(*o)) for o in OUTLETS])


@pytest.fixture()
def lists_csv(tmp_path):
    p = tmp_path / "side_lists.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["side_id", "label", "outlet_ids"])
        w.writerows(LISTS)
    return p


@pytest.fixture()
def lists(t, lists_csv):
    return lens.ready_lists(t, path=lists_csv)


@pytest.fixture()
def pairs(lists_csv):
    return lens.list_pairs(lists_csv)


def ev(country="Northland", title="Northland Shells Southland Border Town", sources=None):
    return Event(id="00000000-0000-4000-8000-0000000000aa", title=title,
                 summary="An invented event for tests.", category="conflict", subtype="strike", severity="3",
                 confidence="55", country=country, location_name="Border town", lat="1", lng="2",
                 report_count="9", start=START, created_at="2026-11-20T08:05:00Z", url="https://example.invalid/e",
                 source_urls=sources or ["https://northfree.example/a/1", "https://x.com/somebody/status/1"])


def fake(*answers):
    """A `complete` that returns the given answers in turn (a dict is sent as JSON, an Exception is raised)."""
    calls = []

    class R:
        def __init__(self, text):
            self.text = text

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, params=params))
        a = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return R(a if isinstance(a, str) else json.dumps(a))
    complete.calls = calls
    return complete


EMPTY = {"label": "", "list": "", "outlets": []}


def world(a, b, reason="Northland and Southland blame each other."):
    return {"reason": reason, "kind": "world", "side_a": a, "side_b": b, "local_press": ""}


# --- the plain-code rule ------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def codes(monkeypatch):
    monkeypatch.setitem(lens.COUNTRY_CODES, "Northland", "NA")
    monkeypatch.setitem(lens.COUNTRY_CODES, "Southland", "SA")
    monkeypatch.setitem(lens.COUNTRY_CODES, "Eastland", "EA")
    monkeypatch.setitem(lens.COUNTRY_CODES, "Westland", "WL")


def test_pairs_are_consecutive_rows(pairs):
    assert pairs == [("north", "south"), ("east_gov", "east_opp")]


def test_rule_us_story_is_left_against_right(t, lists, pairs):
    L = lens.rule_lens(ev("United States"), t, lists, pairs)
    assert L.kind == "us" and [s.side_id for s in L.sides] == ["us_left", "us_right"]
    assert set(L.sides[0].outlet_ids) == {"leftdaily", "leanleft"}
    assert set(L.sides[1].outlet_ids) == {"rightpost", "leanright"}


def test_rule_country_with_a_pair_gets_it(t, lists, pairs):
    L = lens.rule_lens(ev("Southland"), t, lists, pairs)
    assert L.kind == "world" and [s.side_id for s in L.sides] == ["north", "south"]


def test_rule_other_country_has_no_split_and_local_press(t, lists, pairs):
    L = lens.rule_lens(ev("Westland"), t, lists, pairs)
    assert L.kind == "none" and L.local is None and L.local_code == "WL"
    assert any("no outlets on file for local press WL" in f for f in L.flags)
    hidden = {k: v for k, v in lists.items() if k not in ("east_gov", "east_opp")}
    L2 = lens.rule_lens(ev("Eastland"), t, hidden, pairs)      # cold mode: its lists are hidden
    assert L2.kind == "none" and set(L2.local.outlet_ids) == {"eastnews", "eastgov"}


def test_choose_without_a_model_uses_the_rule(t, lists, pairs):
    L, rec = lens.choose(ev("Southland"), t, None, lists=lists, pairs=pairs)
    assert rec["chosen_by"] == "code:rule" and rec["calls"] == 0 and L.kind == "world"


# --- the model's answer, checked by code -----------------------------------------------------------
def test_world_answer_with_a_list_and_a_new_side(t, lists, pairs):
    c = fake(world({"label": "Northland outlets", "list": "north", "outlets": []},
                   {"label": "Southland and its backers", "list": "", "outlets": ["southtimes", "worldtv"]}))
    L, rec = lens.choose(ev(), t, c, model="m", lists=lists, pairs=pairs)
    assert rec["chosen_by"] == "model" and rec["calls"] == 1 and not rec["retried"]
    a, b = L.sides
    assert a.side_id == "north" and a.outlet_ids == ["northstate", "northfree"]
    assert b.side_id == "new_southland_and_its_backers" and b.outlet_ids == ["southtimes", "worldtv"]
    assert L.reason.startswith("Northland and Southland") and L.flags == []
    assert c.calls[0]["params"]["response_format"]["json_schema"]["strict"] is True
    assert c.calls[0]["params"]["max_tokens"] >= 8000


def test_list_plus_extra_outlets_gets_its_own_id(t, lists, pairs):
    c = fake(world({"label": "US right and Northland", "list": "us_right", "outlets": ["northstate"]},
                   {"label": "Southland outlets", "list": "south", "outlets": ["southtimes"]}))
    L, _ = lens.choose(ev(), t, c, lists=lists, pairs=pairs)
    a, b = L.sides
    assert a.side_id == "us_right_plus" and set(a.outlet_ids) == {"rightpost", "leanright", "northstate"}
    assert b.side_id == "south" and b.outlet_ids == ["southherald", "southtimes"]   # nothing new: plain list


def test_unknown_ids_and_platforms_are_dropped_and_flagged(t, lists, pairs):
    c = fake(world({"label": "Northland outlets", "list": "", "outlets": ["northstate", "madeup", "vidsite"]},
                   {"label": "Southland outlets", "list": "no_such_list", "outlets": ["southherald"]}))
    L, _ = lens.choose(ev(), t, c, lists=lists, pairs=pairs)
    assert L.sides[0].outlet_ids == ["northstate"] and L.sides[1].outlet_ids == ["southherald"]
    assert any("madeup" in f and "vidsite" in f for f in L.flags)
    assert any("unknown side list 'no_such_list'" in f for f in L.flags)


def test_a_side_with_nothing_on_file_keeps_its_name_and_is_flagged(t, lists, pairs):
    c = fake(world({"label": "Northland outlets", "list": "north", "outlets": []},
                   {"label": "Islander outlets", "list": "", "outlets": []}))
    L, _ = lens.choose(ev(), t, c, lists=lists, pairs=pairs)
    assert L.kind == "world" and L.sides[1].label == "Islander outlets" and L.sides[1].outlet_ids == []
    assert "no outlets on file: Islander outlets" in L.flags


def test_shared_outlets_are_flagged(t, lists, pairs):
    c = fake(world({"label": "A", "list": "north", "outlets": []},
                   {"label": "B", "list": "", "outlets": ["northfree", "southtimes"]}))
    L, _ = lens.choose(ev(), t, c, lists=lists, pairs=pairs)
    assert any(f.startswith("sides share outlets") and "northfree" in f for f in L.flags)


def test_us_answer_ignores_any_sides_the_model_gave(t, lists, pairs):
    c = fake({"reason": "Parties fight over it.", "kind": "us", "side_a": {"label": "x", "list": "north", "outlets": []},
              "side_b": EMPTY, "local_press": ""})
    L, _ = lens.choose(ev("United States"), t, c, lists=lists, pairs=pairs)
    assert L.kind == "us" and [s.side_id for s in L.sides] == ["us_left", "us_right"]


def test_no_split_with_local_press(t, lists, pairs):
    c = fake({"reason": "An accident.", "kind": "none", "side_a": EMPTY, "side_b": EMPTY, "local_press": "ea"})
    L, rec = lens.choose(ev("Eastland"), t, c, lists=lists, pairs=pairs)
    assert L.kind == "none" and L.sides == [] and L.local.side_id == "local_ea" and L.local_code == "EA"
    assert rec["local_code"] == "EA" and rec["local"]["outlet_ids"] == ["eastnews", "eastgov"]


def test_no_split_us_story_gets_no_local_press(t, lists, pairs):
    c = fake({"reason": "A router failure.", "kind": "none", "side_a": EMPTY, "side_b": EMPTY, "local_press": "US"})
    L, _ = lens.choose(ev("United States"), t, c, lists=lists, pairs=pairs)
    assert L.kind == "none" and L.local is None and L.local_code == ""


# --- never an unusable answer: retry, then the code rule --------------------------------------------
def test_bad_json_gets_one_retry_with_a_note(t, lists, pairs):
    good = world({"label": "N", "list": "north", "outlets": []}, {"label": "S", "list": "south", "outlets": []})
    c = fake("not json at all", good)
    L, rec = lens.choose(ev(), t, c, lists=lists, pairs=pairs)
    assert rec["retried"] and rec["calls"] == 2 and rec["chosen_by"] == "model" and L.kind == "world"
    last = c.calls[1]["messages"][-1]["content"]
    assert "could not be used" in last and "not a JSON object" in last


def test_a_world_answer_without_sides_is_retried(t, lists, pairs):
    c = fake(world(EMPTY, EMPTY), world({"label": "N", "list": "north", "outlets": []},
                                        {"label": "S", "list": "south", "outlets": []}))
    _, rec = lens.choose(ev(), t, c, lists=lists, pairs=pairs)
    assert rec["retried"] and "two sides" in c.calls[1]["messages"][-1]["content"]


def test_two_unusable_answers_fall_back_to_the_rule(t, lists, pairs):
    c = fake(RuntimeError("provider down"), '{"kind": "maybe"}')
    L, rec = lens.choose(ev("Southland"), t, c, lists=lists, pairs=pairs)
    assert rec["fallback"] and rec["chosen_by"] == "code:rule (fallback)" and rec["calls"] == 2
    assert L.kind == "world" and L.source == "code:rule (fallback)"
    assert any("unusable after one retry" in f for f in L.flags)
    assert "provider down" in rec["errors"][0]


def test_the_cost_cap_is_not_swallowed(t, lists, pairs):
    class BudgetExceeded(RuntimeError):
        pass
    with pytest.raises(BudgetExceeded):
        lens.choose(ev(), t, fake(BudgetExceeded("cap")), lists=lists, pairs=pairs)


# --- what the model is shown ------------------------------------------------------------------------
def test_messages_show_lists_outlets_and_own_sources(t, lists):
    m = lens.messages_for(ev(), t, lists)
    menus, event = m[1]["content"][0]["text"], m[1]["content"][1]["text"]
    assert "cache_control" in m[1]["content"][0]
    assert "- north: Northland outlets. Outlets: Northstate, Northfree" in menus
    assert "northstate (Northstate; State-Controlled)" in menus and "centerwire (Centerwire; wire)" in menus
    assert "vidsite" not in menus                                    # platforms are not offered
    assert "us_left:" in menus and "us_right_tail" not in menus
    assert "Northfree (NA)" in event and "X account @somebody" in event


def test_cold_mode_hides_a_storys_own_lists(t, lists_csv):
    hidden = lens.ready_lists(t, hide=("north", "south"), path=lists_csv)
    menus = lens.messages_for(ev(), t, hidden)[1]["content"][0]["text"]
    assert "- north:" not in menus and "- east_gov:" in menus
    c = fake(world({"label": "Northland outlets", "list": "north", "outlets": []},
                   {"label": "Southland outlets", "list": "", "outlets": ["southherald"]}))
    L, _ = lens.choose(ev(), t, c, lists=hidden)
    assert any("unknown side list 'north'" in f for f in L.flags) and L.sides[0].outlet_ids == []


def test_schema_requires_every_field():
    s = lens.SCHEMA["json_schema"]["schema"]
    assert s["required"] == ["reason", "kind", "side_a", "side_b", "local_press"]
    assert s["properties"]["kind"]["enum"] == ["us", "world", "none"]
    assert s["additionalProperties"] is False


# --- records -------------------------------------------------------------------------------------------
def test_record_and_new_sides_file(t, lists, pairs, tmp_path):
    c = fake(world({"label": "Northland outlets", "list": "north", "outlets": []},
                   {"label": "Southland backers", "list": "", "outlets": ["southtimes"]}))
    L, rec = lens.choose(ev(), t, c, model="m", lists=lists, pairs=pairs)
    assert rec["kind"] == "world" and rec["sides"][1]["outlet_ids"] == ["southtimes"]
    assert rec["answer"]["side_b"]["label"] == "Southland backers"
    json.dumps(rec)                                                  # plain data, for gather.json and the eval
    p = tmp_path / "proposed_sides.jsonl"
    assert lens.record_new_sides(ev(), L, p) == 1
    saved = [json.loads(x) for x in p.read_text().splitlines()]
    assert saved[0]["side_id"] == "new_southland_backers" and saved[0]["outlet_ids"] == ["southtimes"]
