"""Module 5's one-call baseline and its eval. Made-up articles, events and sides only."""
import json
from types import SimpleNamespace

from stringer import brief_onecall
from stringer.evals import brief_onecall_eval, runner

EVENT = {"title": "Bridge closes after storm", "summary": "A storm damaged the river bridge in Testville.",
         "start": "2026-01-02T03:04:00Z"}
LENS = {"kind": "world", "sides": [{"side_id": "north", "label": "Northland outlets"},
                                   {"side_id": "south", "label": "Southland outlets"}]}
NO_SIDES = {"kind": "none", "sides": []}
A1 = {"id": "a_n1", "text_status": "full", "title": "Storm wrecks Testville bridge - North Daily",
      "text": "# Storm wrecks Testville bridge\nThe river bridge in Testville was closed on Friday after a storm "
              "cracked two of its supports, city officials said. Southland's careless engineers built it."}
B1 = {"id": "a_s1", "text_status": "full", "title": "Testville bridge shut for checks - South Times",
      "text": "# Testville bridge shut for checks\nThe Testville bridge was shut for safety checks on Friday, "
              "officials said, and ferries will carry drivers across the river until it reopens."}
SNIP = {"id": "a_x1", "text_status": "snippet", "title": "Bridge news", "text": "short"}
GROUPS = {"a_n1": "A", "a_s1": "B", "a_x1": "other"}


def answer(claims, persp=()):
    return json.dumps({"claims": claims, "perspectives": list(persp)})


def claim(text, *sources, kind="event", who="city officials", conflicts=()):
    return {"claim": text, "kind": kind, "who_says": who, "conflicts_with": list(conflicts),
            "sources": [{"article": a, "quote": q, "quote_en": ""} for a, q in sources]}


CLOSED = claim("Officials closed the Testville bridge on Friday.",
               ("R1", "was closed on Friday after a storm cracked two of its supports"),
               ("R2", "was shut for safety checks on Friday"))
FERRIES = claim("Ferries will carry drivers until the bridge reopens.",
                ("R2", "ferries will carry drivers across the river"))
MADE_UP = claim("The bridge collapsed into the river.", ("R1", "the bridge collapsed completely into the river"))
POINT_A = {"side": "A", "points": [{"point": "Blames Southland's engineers.",
                                     "quotes": [{"article": "R1", "words": "careless engineers"}]}]}


def fake(*texts):
    calls = []

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, params=params))
        t = texts[min(len(calls), len(texts)) - 1]
        if isinstance(t, Exception):
            raise t
        return SimpleNamespace(text=t)
    return complete, calls


def test_one_call_sees_labels_sides_and_no_outlet_names():
    complete, calls = fake(answer([CLOSED]))
    brief_onecall.write_story(EVENT, [A1, B1, SNIP], LENS, GROUPS, complete, model="sonnet-5-5")
    assert len(calls) == 1 and calls[0]["params"]["response_format"]["type"] == "json_schema"
    user = calls[0]["messages"][1]["content"]
    assert "=== R1 | side: Side A ===" in user and "=== R2 | side: Side B ===" in user
    assert "Side A: Northland outlets" in user and "R3" not in user          # the snippet is left out
    assert "North Daily" not in user and "South Times" not in user          # outlet hidden


def test_claims_keep_checked_sources_and_get_ids_and_sides():
    complete, _ = fake(answer([CLOSED, FERRIES]))
    out = brief_onecall.write_story(EVENT, [A1, B1], LENS, GROUPS, complete)
    assert [c["id"] for c in out["claims"]] == ["C1", "C2"]
    assert [s["article"] for s in out["claims"][0]["sources"]] == ["a_n1", "a_s1"]
    assert out["claims"][0]["sides"] == ["A", "B"] and out["claims"][1]["sides"] == ["B"]
    assert out["checks"]["sources_bad"] == 0 and out["checks"]["claims_dropped"] == 0


def test_a_bad_quote_drops_that_source_and_a_claim_with_none_left():
    half = claim("Officials closed the bridge.", ("R1", "was closed on Friday after a storm cracked"),
                 ("R2", "the bridge was totally destroyed by the storm"))
    complete, calls = fake(answer([half, MADE_UP]))
    out = brief_onecall.write_story(EVENT, [A1, B1], LENS, GROUPS, complete)
    assert len(calls) == 1                                                   # no quote retry
    assert len(out["claims"]) == 1 and len(out["claims"][0]["sources"]) == 1
    assert out["checks"]["sources_bad"] == 2 and out["checks"]["claims_dropped"] == 1
    assert out["dropped"][0]["claim"].startswith("The bridge collapsed")


def test_conflicts_point_at_claim_ids_and_skip_dropped_claims():
    c1 = claim("Officials closed the bridge.", ("R1", "was closed on Friday after a storm cracked"), conflicts=[3])
    c3 = claim("The bridge was shut for checks.", ("R2", "was shut for safety checks on Friday"), conflicts=[1, 2])
    complete, _ = fake(answer([c1, MADE_UP, c3]))
    out = brief_onecall.write_story(EVENT, [A1, B1], LENS, GROUPS, complete)
    assert out["claims"][0]["conflicts_with"] == ["C2"] and out["claims"][1]["conflicts_with"] == ["C1"]


def test_perspective_words_must_be_in_an_article_on_that_side():
    wrong = {"side": "B", "points": [{"point": "Calls it careless.", "quotes": [{"article": "R1", "words": "careless engineers"}]},
                                     {"point": "Invents words.", "quotes": [{"article": "R2", "words": "a total disgrace"}]}]}
    complete, _ = fake(answer([CLOSED], [POINT_A, wrong]))
    out = brief_onecall.write_story(EVENT, [A1, B1], LENS, GROUPS, complete)
    c = out["checks"]
    assert (c["persp_quotes"], c["persp_bad"], c["persp_wrong_side"], c["points"]) == (3, 1, 1, 3)
    assert out["perspectives"][0]["label"] == "Northland outlets"


def test_no_real_divide_drops_any_perspectives():
    complete, calls = fake(answer([CLOSED], [POINT_A]))
    out = brief_onecall.write_story(EVENT, [A1, B1], NO_SIDES, GROUPS, complete)
    assert "no real divide" in calls[0]["messages"][1]["content"] and "side: neither" in calls[0]["messages"][1]["content"]
    assert out["perspectives"] == [] and out["sides"] == "no real divide"


def test_unusable_json_or_a_failed_call_is_asked_once_more_then_reported():
    complete, calls = fake(TimeoutError("timed out"), answer([CLOSED]))
    out = brief_onecall.write_story(EVENT, [A1, B1], LENS, GROUPS, complete)
    assert len(calls) == 2 and out["checks"]["retried_json"] and len(out["claims"]) == 1
    complete, calls = fake("not json", "still not json")
    out = brief_onecall.write_story(EVENT, [A1, B1], LENS, GROUPS, complete)
    assert len(calls) == 2 and out["claims"] == [] and out["checks"]["error"]


def test_scoring_counts_only_kept_claims_for_coverage():
    ev = brief_onecall_eval.BriefOneCallEval()
    item = runner.Item(id="story:s1", story="s1", data={})
    out = {"claims": [{"id": "C1"}, {"id": "C2"}], "articles": [{}, {}],
           "checks": dict(claims_first=3, claims_dropped=1, sources_first=4, sources_bad=1, persp_quotes=2,
                          persp_bad=0, persp_wrong_side=1, points=2),
           "judge": {"results": {"M1": {"found": True, "cards": ["C1"]}, "M2": {"found": True, "cards": ["X3"]},
                                 "M3": {"found": False, "cards": []}}}}
    s = ev.score(item, out, {"s1": ["a", "b", "c"]})
    assert (s["found"], s["found_all"], s["coverage"]) == (1, 2, 0.333)
    summ = ev.summarize([item], [s])
    assert summ["quote_ok"] == 0.75 and summ["persp_ok"] == 0.5 and summ["coverage_all"] == 0.667


def test_the_plan_is_one_call_per_story():
    ev = brief_onecall_eval.BriefOneCallEval()
    ev._story = lambda item: (EVENT, LENS, [A1, B1, SNIP], GROUPS)
    calls = ev.plan(runner.Item(id="story:s1", story="s1", data={}), "sonnet-5-5")
    assert len(calls) == 1 and calls[0]["params"]["max_tokens"] == brief_onecall.MAX_TOKENS
