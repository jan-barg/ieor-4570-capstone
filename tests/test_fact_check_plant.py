"""The fact check eval's planted mistakes. Made-up stories only (the ones in test_fact_check)."""
import random

from stringer import fact_check
from stringer.evals import fact_check_plant as fp
from test_fact_check import ARTICLES, EVENT, FACTS, TEXTS, Table, claim, source, story


def base():
    return story([claim("C1", "The bridge closed on Friday.", "a_n1#1", "a_s1#1"),
                  claim("C2", "Ferries will carry drivers.", "a_s1#2"),
                  claim("C3", "Engineers expect repairs to take three months.", "a_n1#2")])


def check(sf, facts):
    return fact_check.check_story(sf, facts, ARTICLES, None, model="code", table=Table())[1]     # (facts, Story File)


# ---- applying records ----------------------------------------------------------------------------------

def test_apply_changes_a_copy():
    sf = base()
    new = dict(FACTS[6], id="a_s1#2-planted", quote="Ferries carry will drivers across the river")
    recs = [dict(kind="quote changed", claim="C2", set=dict(facts=["a_s1#2-planted"]), new_facts=[new]),
            dict(kind="early date", claim=None, sources={"a_n1": dict(published_at="2025-12-01T00:00:00Z")})]
    out, facts = fp.apply(sf, FACTS, recs)
    assert out["claims"][1]["facts"] == ["a_s1#2-planted"] and facts[-1]["id"] == "a_s1#2-planted"
    assert out["sources"][0]["published_at"] == "2025-12-01T00:00:00Z"
    assert sf["claims"][1]["facts"] == ["a_s1#2"] and sf["sources"][0]["published_at"] != "2025-12-01T00:00:00Z"
    assert len(facts) == len(FACTS) + 1


# ---- the code copy: no model, every planted mistake caught ---------------------------------------------

def test_code_copy_mistakes_are_caught_by_the_paperwork_pass():
    sf = base()
    swapped = fp.swap_words(FACTS[6]["quote"], random.Random(1))
    recs = [
        dict(id="P1", kind="no card", claim="C3", set=dict(facts=[]), expect={}),
        dict(id="P2", kind="quote changed", claim="C2", set=dict(facts=["a_s1#2-p"]),
             new_facts=[dict(FACTS[6], id="a_s1#2-p", quote=swapped)], expect=dict(cards_off=["a_s1#2-p"])),
        dict(id="P3", kind="look-alike address", claim=None, sources={"a_n1": dict(url=fp.lookalike_url(source("a_n1")["url"]))},
             expect=dict(cards_off=["a_n1#1"], source="a_n1")),
    ]
    planted, facts = fp.apply(sf, FACTS, recs)
    checked = check(planted, facts)
    scores = [fp.score_record(r, checked) for r in recs]
    assert [s["got"] for s in scores] == ["dropped", "card off", "cards off"]
    assert all(s["right"] and not s["critical"] for s in scores)


def test_code_copy_scores_a_miss():
    sf = base()
    r = dict(id="P1", kind="unknown article", claim="C2", expect=dict(cards_off=["a_s1#2"]))   # nothing was planted
    s = fp.score_record(r, check(sf, FACTS))
    assert s["got"] == "card kept" and s["critical"] and not s["right"]


def test_wrong_sides_are_fixed():
    sf = base()
    recs = [dict(id="P1", kind="wrong sides", claim="C2", set=dict(sides=["north", "south"]), expect=dict(sides=["south"])),
            dict(id="P2", kind="wrong sides", claim="C3", expect=dict(sides=["north"], blindspot_removed=True),
                 set=dict(blindspot=dict(silent_side="north", status="blindspot", matters="central", why="planted", evidence=None)))]
    planted, facts = fp.apply(sf, FACTS, recs)
    checked = check(planted, facts)
    assert [fp.score_record(r, checked)["got"] for r in recs] == ["sides fixed", "sides fixed"]


def test_early_date_takes_off_the_cards():
    sf = base()
    r = dict(id="P1", kind="early date", claim=None, sources={"a_s1": dict(published_at=fp.early(EVENT["start"]))},
             expect=dict(cards_off=["a_s1#1", "a_s1#2"], source="a_s1"))
    planted, facts = fp.apply(sf, FACTS, [r])
    assert fp.score_record(r, check(planted, facts))["got"] == "cards off"


# ---- the judge copy: outcomes and critical misses -----------------------------------------------------

def test_outcome_names():
    assert fp.outcome(dict(status="say with source", check=dict(rules=["a"]))) == "named the speaker"
    assert fp.outcome(dict(status="say with source", check=dict(rules=["c"]))) == "named the outlet"
    assert fp.outcome(dict(status="dropped")) == "dropped"
    assert fp.outcome(dict(status="confirmed")) == "confirmed"
    assert fp.outcome(dict(status=None)) == "unchecked"


def test_judge_copy_critical_misses():
    def score(kind, status, rules=()):
        checked = dict(claims=[dict(id="C1", status=status, check=dict(rules=list(rules)))])
        return fp.score_record(dict(kind=kind, claim="C1"), checked)
    assert score("actors reversed", "dropped") == dict(kind="actors reversed", expect="dropped", got="dropped", right=True, critical=False)
    assert score("actors reversed", "confirmed")["critical"]
    assert score("actors reversed", "say with source", ["c"])["critical"]          # repeated with the outlet's name
    assert score("actors reversed", "say with source", ["a"])["critical"]          # a wrong fact, just attributed
    assert not score("actors reversed", "unchecked")["critical"]                   # missed, but flagged as unchecked
    s = score("attribution dropped", "say with source", ["a"])
    assert s["right"] and not s["critical"]
    s = score("attribution dropped", "dropped")
    assert not s["right"] and not s["critical"]                                    # too strict, but safe


# ---- making the mechanical ones -----------------------------------------------------------------------

def test_change_number_skips_years_days_and_ordinals():
    assert fp.change_number("Repairs take 3 months", ["at least three months"]) == ("Repairs take 6 months", "3", "6")
    assert fp.change_number("In 2026, 40 people fled", ["40 people fled in 2026"]) == ("In 2026, 50 people fled", "40", "50")
    assert fp.change_number("On Nov. 4, 12 drones fell", ["12 drones"]) == ("On Nov. 4, 22 drones fell", "12", "22")
    assert fp.change_number("the 35th day, 1,441 drones", ["1441 drones"]) == ("the 35th day, 2,441 drones", "1,441", "2,441")
    assert fp.change_number("9 dead", ["9 dead"]) == ("12 dead", "9", "12")
    assert fp.change_number("No numbers here", []) is None


def test_change_number_needs_a_number_no_quote_has():
    assert fp.change_number("3 ships", ["3 ships, then 6 more"]) is None


def test_change_date():
    assert fp.change_date("The bridge closed on Friday.") == ("The bridge closed on Sunday.", "Friday", "Sunday")
    assert fp.change_date("Attacked on Oct. 22 at night")[0] == "Attacked on Oct. 25 at night"
    assert fp.change_date("Since 28 October")[0] == "Since 25 October"
    assert fp.change_date("Last year") is None


def test_lookalike_url():
    assert fp.lookalike_url("https://www.theguardian.com/world/x") == "https://www.theguardian-news.com/world/x"
    assert fp.lookalike_url("https://www.bbc.co.uk/news/1") == "https://www.bbc-news.co.uk/news/1"
    assert fp.lookalike_url("https://example.com") == "https://example-news.com"


def test_swap_words_keeps_the_words():
    q = FACTS[0]["quote"]
    s = fp.swap_words(q, random.Random(3))
    assert s != q and sorted(s.split()) == sorted(q.split())
    assert fp.swap_words("a b", random.Random(0)) is None


def test_every_kind_has_a_copy_and_outcome():
    assert set(fp.CODE_KINDS) | set(fp.JUDGE_SCRIPT_KINDS) | set(fp.HAND_KINDS) == set(fp.KINDS)
    assert all(v[0] in ("code", "judge") for v in fp.KINDS.values())
    assert TEXTS  # the shared made-up story is loaded
