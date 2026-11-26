"""Module 5, step 2 (merging fact cards into claims) and its eval. Made-up cards and events only."""
import json
from types import SimpleNamespace

from stringer import brief_merge
from stringer.evals import brief_merge_eval, runner

EVENT = {"title": "Bridge closes after storm", "summary": "A storm damaged the river bridge in Testville.",
         "start": "2026-01-02T03:04:00Z"}


def card(art, k, fact, quote, kind="event", who="the outlet", quote_en=""):
    return {"id": f"{art}#{k}", "fact": fact, "quote": quote, "quote_en": quote_en, "kind": kind, "who_says": who, "pos": 10}


STEP1 = {"articles": [
    {"article": "a_n1", "facts": [
        card("a_n1", 1, "The Testville bridge closed on Friday.", "the bridge was closed on Friday"),
        card("a_n1", 2, "Police said 12 people were hurt.", "police said 12 people were hurt", "number", "police")]},
    {"article": "a_empty", "facts": []},
    {"article": "a_s1", "facts": [
        card("a_s1", 1, "The bridge was shut on Friday.", "le pont a été fermé vendredi", quote_en="the bridge was shut on Friday"),
        card("a_s1", 2, "The mayor said 15 people were hurt.", "15 personnes ont été blessées", "number", "the mayor",
             quote_en="15 people were hurt"),
        card("a_s1", 3, "Subscribe to our newsletter.", "abonnez-vous à notre lettre")]}]}


def answer(claims):
    return json.dumps({"claims": claims})


def claim(text, cards, kind="event", who="the outlet", conflicts=()):
    return {"claim": text, "kind": kind, "who_says": who, "cards": list(cards), "conflicts_with": list(conflicts)}


def fake(*texts):
    calls = []

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, params=params))
        t = texts[min(len(calls), len(texts)) - 1]
        if isinstance(t, Exception):
            raise t
        return SimpleNamespace(text=t)
    return complete, calls


def test_the_model_sees_short_card_ids_english_words_and_no_outlets():
    complete, calls = fake(answer([]))
    brief_merge.merge_story(EVENT, STEP1, complete, model="sonnet-5-5")
    user = calls[0]["messages"][1]["content"]
    assert "Fact cards (5):" in user and "\nArticle 1\nF1 [event; who: the outlet]" in user
    assert "\nArticle 2\nF3 " in user                                       # the article with no cards is skipped
    assert "the bridge was shut on Friday" in user and "le pont" not in user  # English words where there are any
    assert "a_n1" not in user and calls[0]["params"]["response_format"]["type"] == "json_schema"


def test_claims_map_back_to_cards_articles_and_quotes():
    complete, _ = fake(answer([claim("The Testville bridge closed on Friday.", ["F1", "F3"]),
                               claim("Police said 12 people were hurt.", ["F2"], "number", "police", [3]),
                               claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor", [2])]))
    out = brief_merge.merge_story(EVENT, STEP1, complete)
    c1, c2, c3 = out["claims"]
    assert c1["facts"] == ["a_n1#1", "a_s1#1"] and c1["articles"] == ["a_n1", "a_s1"]
    assert c1["sources"][1]["quote"] == "le pont a été fermé vendredi"          # the original words stay for checking
    assert c2["conflicts_with"] == ["C3"] and c3["conflicts_with"] == ["C2"]
    ch = out["checks"]
    assert (ch["multi_article"], ch["conflicts"], ch["cards_unused"]) == (1, 2, 1)
    assert out["unused"][0]["fact"].startswith("Subscribe")


def test_unknown_card_ids_are_dropped_and_a_claim_left_with_none_goes():
    complete, _ = fake(answer([claim("The bridge closed.", ["F1", "F99"]), claim("Made up.", ["F42"]),
                               claim("Hurt.", ["F2"], conflicts=[2])]))
    out = brief_merge.merge_story(EVENT, STEP1, complete)
    assert [c["id"] for c in out["claims"]] == ["C1", "C2"] and out["claims"][1]["conflicts_with"] == []
    assert out["checks"]["unknown_cards"] == 2 and out["checks"]["claims_dropped"] == 1


def test_unusable_json_or_a_failed_call_is_asked_once_more_then_reported():
    complete, calls = fake(TimeoutError("timed out"), answer([claim("The bridge closed.", ["F1"])]))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-3")
    assert len(calls) == 2 and out["checks"]["retried_json"] and len(out["claims"]) == 1
    complete, calls = fake("not json", "still not json")
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-3")
    assert len(calls) == 2 and out["claims"] == [] and out["checks"]["error"]


def test_an_answer_with_no_claims_is_asked_once_more():
    complete, calls = fake(answer([]), answer([claim("The bridge closed.", ["F1"])]))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-3")
    assert len(calls) == 2 and "no claims" in calls[1]["messages"][-1]["content"] and len(out["claims"]) == 1
    complete, calls = fake(answer([]), answer([]))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-3")
    assert len(calls) == 2 and out["checks"]["error"] and out["claims"] == []
    complete, calls = fake(answer([claim("", [""])]), answer([claim("The bridge closed.", ["F1"])]))   # one blank claim
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-3")
    assert len(calls) == 2 and len(out["claims"]) == 1


def test_a_story_with_no_cards_makes_no_call():
    complete, calls = fake(answer([]))
    out = brief_merge.merge_story(EVENT, {"articles": []}, complete)
    assert calls == [] and out["checks"]["error"]


def test_scoring_counts_facts_lost_against_step_1():
    ev = brief_merge_eval.BriefMergeEval(facts="unused.json")
    ev._step1 = {"run_id": "r1", "stories": {"s1": {"output": STEP1, "found_each": [True, True, False]}}}
    item = runner.Item(id="story:s1", story="s1", data={})
    out = {"claims": [{"id": "C1", "articles": ["a", "b"]}, {"id": "C2", "articles": ["a"]}],
           "checks": dict(cards=5, cards_unused=1, multi_article=1, conflicts=0, claims_dropped=0),
           "judge": {"results": {"M1": {"found": True}, "M2": {"found": False}, "M3": {"found": True}}}}
    s = ev.score(item, out, {"s1": ["a", "b", "c"]})
    assert (s["found"], s["step1_found"], s["lost"], s["lost_each"]) == (2, 2, 1, [1])
    summ = ev.summarize([item], [s])
    assert summ["cards_unused"] == 0.2 and summ["multi_article"] == 0.5 and summ["step1_coverage"] == 0.667


def test_the_eval_finds_the_latest_step_1_run_for_the_decided_model(tmp_path):
    for ts in ("20260101T000000", "20260102T000000"):
        (tmp_path / f"brief_read-{ts}-deepseek-v4.1-flash-read-2-n10.json").write_text("{}")
    (tmp_path / "brief_read-20260103T000000-haiku-5-5-read-2-n10.json").write_text("{}")
    p = brief_merge_eval.step1_run("10", model="deepseek-v4.1-flash", runs_dir=tmp_path)
    assert p.name.startswith("brief_read-20260102")


def test_both_prompts_can_run_and_the_eval_names_the_one_it_used():
    complete, calls = fake(answer([claim("The bridge closed.", ["F1"])]))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-2")
    assert calls[0]["messages"][0]["content"] == brief_merge.PROMPTS["merge-2"] and out["version"] == "merge-2"
    assert "Example (made-up cards)" in brief_merge.PROMPTS["merge-3"] and brief_merge.VERSION == "merge-14"
    assert brief_merge_eval.BriefMergeEval(facts="x.json", prompt="merge-2").version == "merge-2-n10"
    try:
        brief_merge_eval.BriefMergeEval(facts="x.json", prompt="merge-99")
        assert False, "unknown prompt should fail"
    except KeyError:
        pass


QUALITY_ANSWER = json.dumps({
    "bad_claims": [{"claim": "C1", "cards": ["K3"], "why": "different date"}, {"claim": "C9", "cards": [], "why": "no such claim"}],
    "lost_cards": [{"card": "K5", "why": "the mayor's figure is in no claim"}, {"card": "K99", "why": "unknown"}],
    "false_conflicts": [{"a": "C2", "b": "C1", "why": "different things"}],
    "missed_conflicts": [{"a": "C2", "b": "C3", "why": "12 against 15"}, {"a": "C3", "b": "C2", "why": "same pair"}]})


def test_quality_judge_sees_claims_with_their_cards_and_its_answer_maps_back():
    ev = brief_merge_eval.BriefMergeEval(facts="x.json")
    complete, calls = fake(answer([claim("The bridge closed on Friday.", ["F1", "F3"], conflicts=[2]),
                                   claim("Police said 12 people were hurt.", ["F2"], "number", "police", [1]),
                                   claim("Subscribe.", ["F5"])]))
    out = brief_merge.merge_story(EVENT, STEP1, complete)
    seen = []

    class Ctx:
        def complete(self, msgs, name=None, model=None, **p):
            seen.append(dict(msgs=msgs, model=model, params=p))
            return SimpleNamespace(text=QUALITY_ANSWER)
    q = ev._quality(EVENT, out, brief_merge.cards_of(STEP1), Ctx())
    body = seen[0]["msgs"][1]["content"]
    assert seen[0]["model"] == ev.judge and seen[0]["params"]["response_format"]["json_schema"]["name"] == "merge_quality"
    assert "C1 [event; who: the outlet] The bridge closed on Friday.  [conflicts with: C2]" in body
    assert "  K3: The bridge was shut on Friday." in body and "Cards in no claim:\n  K4: The mayor said 15" in body
    assert q["bad_claims"] == [{"claim": "C1", "cards": ["a_s1#1"], "why": "different date"}]
    assert [x["card"] for x in q["lost_cards"]] == ["a_s1#3"]                    # K5; K99 is unknown and dropped
    ev._step1 = {"run_id": "r1", "stories": {"s1": {"output": STEP1, "found_each": []}}}
    s = ev.score(runner.Item(id="story:s1", story="s1", data={}), dict(out, quality=q, judge={"results": {}}), {"s1": []})
    assert (s["bad_claims"], s["lost_cards"], s["false_conflicts"], s["missed_conflicts"]) == (1, 1, 1, 1)


def test_too_many_cards_left_out_gets_one_retry_naming_them():
    short = answer([claim("The bridge closed.", ["F1"])])                       # 4 of 5 cards left out
    full = answer([claim("The bridge closed on Friday.", ["F1", "F3"]), claim("Police said 12 were hurt.", ["F2"], conflicts=[3]),
                   claim("The mayor said 15 were hurt.", ["F4"], conflicts=[2])])
    complete, calls = fake(short, full)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-5")
    assert len(calls) == 2 and "These cards are in no claim: F2, F3, F4, F5" in calls[1]["messages"][-1]["content"]
    assert out["checks"]["retried_incomplete"] and out["checks"]["unused_first"] == 4 and out["checks"]["cards_unused"] == 1
    assert len(out["claims"]) == 3
    complete, calls = fake(short, answer([claim("Nothing better.", ["F5"])]))   # a retry no better is not kept
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-5")
    assert len(calls) == 2 and out["claims"][0]["claim"] == "The bridge closed."
    complete, calls = fake(short)                                                # merge-3 never asked again
    brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-3")
    assert len(calls) == 1


def test_the_conflict_pass_marks_pairs_the_merge_missed():
    merged = answer([claim("The bridge closed on Friday.", ["F1", "F3"]), claim("Police said 12 people were hurt.", ["F2"], "number", "police"),
                     claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor"), claim("Subscribe.", ["F5"])])
    found = json.dumps({"conflicts": [{"a": "C2", "b": "C3", "why": "12 against 15"}, {"a": "C3", "b": "C2", "why": "again"},
                                      {"a": "C1", "b": "C9", "why": "no such claim"}]})
    complete, calls = fake(merged, found)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-6")
    assert len(calls) == 2 and calls[1]["messages"][0]["content"] == brief_merge.CONFLICT_SYSTEM
    assert "C2 [number; who: police] Police said 12 people were hurt." in calls[1]["messages"][1]["content"]
    assert "F2" not in calls[1]["messages"][1]["content"]                       # claims only, no cards
    c = {x["id"]: x for x in out["claims"]}
    assert c["C2"]["conflicts_with"] == ["C3"] and c["C3"]["conflicts_with"] == ["C2"] and c["C1"]["conflicts_with"] == []
    assert out["checks"]["conflict_pass_found"] == 1 and out["checks"]["conflict_pass_added"] == 1
    assert out["checks"]["conflicts"] == 2


def test_a_failed_conflict_pass_keeps_the_merge_and_records_the_error():
    merged = answer([claim("Police said 12 were hurt.", ["F1", "F2", "F3"], conflicts=[2]), claim("The mayor said 15.", ["F4", "F5"], conflicts=[1])])
    complete, calls = fake(merged, "not json", TimeoutError("hung"))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-7")
    assert len(calls) == 3 and out["checks"]["conflict_pass_error"] and out["claims"][0]["conflicts_with"] == ["C2"]
    complete, calls = fake(merged)
    brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-5")          # merge-5 has no conflict pass
    assert len(calls) == 1


def test_merge_7_keeps_only_pairs_marked_as_conflicts():
    merged = answer([claim("The bridge closed on Friday.", ["F1", "F3"]), claim("Police said 12 people were hurt.", ["F2"], "number", "police"),
                     claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor"), claim("Subscribe.", ["F5"])])
    found = json.dumps({"pairs": [{"a": "C2", "b": "C3", "why": "12 against 15", "conflict": True},
                                  {"a": "C1", "b": "C2", "why": "different things", "conflict": False}]})
    complete, calls = fake(merged, found)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-7")
    assert calls[1]["messages"][0]["content"] == brief_merge.CONFLICT_SYSTEM_2
    assert calls[1]["params"]["response_format"]["json_schema"]["schema"]["required"] == ["pairs"]
    assert [(p["a"], p["b"]) for p in out["conflict_pass"]] == [("C2", "C3")] and out["claims"][0]["conflicts_with"] == []


def test_merge_8_shows_when_each_claim_was_reported_and_names_the_shared_thing():
    merged = answer([claim("The bridge closed on Friday.", ["F1", "F3"]), claim("Police said 12 people were hurt.", ["F2"], "number", "police"),
                     claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor"), claim("Subscribe.", ["F5"])])
    found = json.dumps({"pairs": [{"a": "C2", "b": "C3", "same_thing": "people hurt", "why": "12 against 15", "conflict": True},
                                  {"a": "C1", "b": "C2", "same_thing": "", "why": "different things", "conflict": False}]})
    complete, calls = fake(merged, found)
    times = {"a_n1": "2026-01-02T05:15:42Z", "a_s1": "2026-01-03T09:02:00Z"}
    out = brief_merge.merge_story(EVENT, STEP1, complete, times=times, prompt="merge-8")
    assert out["version"] == "merge-8" and calls[1]["messages"][0]["content"] == brief_merge.CONFLICT_SYSTEM_3
    body = calls[1]["messages"][1]["content"]
    assert "C1 [event; who: the outlet; reported: Jan 2 05:15 to Jan 3 09:02] The bridge closed on Friday." in body
    assert "C2 [number; who: police; reported: Jan 2 05:15]" in body and "C3 [number; who: the mayor; reported: Jan 3 09:02]" in body
    assert "same_thing" in calls[1]["params"]["response_format"]["json_schema"]["schema"]["properties"]["pairs"]["items"]["required"]
    assert out["conflict_pass"] == [{"a": "C2", "b": "C3", "why": "people hurt: 12 against 15"}]
    assert out["claims"][1]["conflicts_with"] == ["C3"] and out["claims"][0]["conflicts_with"] == []


def test_a_claim_with_no_known_times_says_unknown():
    assert brief_merge.reported({"articles": ["a_x"]}, {}) == "unknown"
    assert brief_merge.reported({"articles": ["a_x", "a_y"]}, {"a_x": "2026-11-17T05:15:00Z", "a_y": "2026-11-17T05:15:59Z"}) == "Nov 17 05:15"


def test_merge_9_marks_every_claim_pair_across_a_disputed_point_but_not_updates():
    merged = answer([claim("The bridge closed on Friday.", ["F1"]), claim("Police said 12 people were hurt.", ["F2"], "number", "police"),
                     claim("The bridge was shut on Friday.", ["F3"]), claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor"),
                     claim("Subscribe.", ["F5"])])
    found = json.dumps({"points": [
        {"thing": "people hurt", "type": "dispute", "accounts": [{"claims": ["C2", "C9"], "says": "12"}, {"claims": ["C4", "C2"], "says": "15"},
                                                                {"claims": ["C5"], "says": "none"}]},
        {"thing": "bridge status", "type": "update", "accounts": [{"claims": ["C1"], "says": "closed"}, {"claims": ["C3"], "says": "shut"}]},
        {"thing": "only one side", "type": "dispute", "accounts": [{"claims": ["C1"], "says": "x"}, {"claims": ["C7"], "says": "y"}]},
        {"thing": "odd type", "type": "maybe", "accounts": [{"claims": ["C1"], "says": "x"}, {"claims": ["C3"], "says": "y"}]}]})
    complete, calls = fake(merged, found)
    out = brief_merge.merge_story(EVENT, STEP1, complete, times={"a_n1": "2026-01-02T05:15:42Z"}, prompt="merge-9")
    assert out["version"] == "merge-9" and calls[1]["messages"][0]["content"] == brief_merge.CONFLICT_SYSTEM_4
    assert "reported: Jan 2 05:15]" in calls[1]["messages"][1]["content"]
    assert [p["thing"] for p in out["conflict_points"]] == ["people hurt", "bridge status"]
    assert out["conflict_points"][0]["accounts"][1]["claims"] == ["C4"]           # C2 stays in its first account
    assert [(p["a"], p["b"]) for p in out["conflict_pass"]] == [("C2", "C4"), ("C2", "C5"), ("C4", "C5")]
    c = {x["id"]: x for x in out["claims"]}
    assert c["C2"]["conflicts_with"] == ["C4", "C5"] and c["C1"]["conflicts_with"] == [] and c["C3"]["conflicts_with"] == []
    assert (out["checks"]["disputes"], out["checks"]["updates"], out["checks"]["conflict_pass_found"]) == (1, 1, 3)


def test_merge_9_asks_once_more_when_the_points_answer_is_unusable():
    merged = answer([claim("Police said 12 were hurt.", ["F1", "F2", "F3"]), claim("The mayor said 15.", ["F4", "F5"])])
    good = json.dumps({"points": [{"thing": "hurt", "type": "dispute", "accounts": [{"claims": ["C1"], "says": "12"},
                                                                                   {"claims": ["C2"], "says": "15"}]}]})
    complete, calls = fake(merged, "not json", good)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-9")
    assert len(calls) == 3 and out["checks"]["conflict_pass_error"] is None and out["claims"][0]["conflicts_with"] == ["C2"]
    complete, calls = fake(merged, "not json", TimeoutError("hung"))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-9")
    assert out["checks"]["conflict_pass_error"] and out["conflict_points"] == [] and out["claims"][0]["conflicts_with"] == []


MERGED_4 = answer([claim("The bridge closed on Friday.", ["F1"]), claim("Police said 12 people were hurt.", ["F2"], "number", "police"),
                   claim("The bridge was shut on Friday.", ["F3"]), claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor"),
                   claim("Subscribe.", ["F5"])])
FOUND_3 = json.dumps({"pairs": [{"a": "C2", "b": "C4", "why": "12 against 15", "conflict": True},
                                {"a": "C1", "b": "C3", "why": "closed against shut", "conflict": True},
                                {"a": "C1", "b": "C5", "why": "odd", "conflict": True}]})


def test_merge_10_keeps_only_candidates_the_check_calls_disputes():
    checks = json.dumps({"checks": [{"pair": 1, "same_thing": "people hurt", "why": "two sources, same time", "verdict": "dispute"},
                                    {"pair": 2, "same_thing": "bridge", "why": "same thing in other words", "verdict": "none"},
                                    {"pair": 9, "same_thing": "x", "why": "no such pair", "verdict": "dispute"}]})
    complete, calls = fake(MERGED_4, FOUND_3, checks)
    out = brief_merge.merge_story(EVENT, STEP1, complete, times={"a_n1": "2026-01-02T05:15:42Z", "a_s1": "2026-01-03"},
                                  prompt="merge-10")
    assert out["version"] == "merge-10" and len(calls) == 3
    assert calls[1]["messages"][0]["content"] == brief_merge.CONFLICT_SYSTEM_2                     # merge-7's finder
    v = calls[2]["messages"]
    assert v[0]["content"] == brief_merge.VERIFY_SYSTEM and "Pairs (3):" in v[1]["content"]
    assert "P1\n  C2 [number; who: police; reported: Jan 2 05:15] Police said 12 people were hurt.\n  C4 [number; who: the mayor; reported: Jan 3]" in v[1]["content"]
    assert [(p["a"], p["b"]) for p in out["conflict_pass"]] == [("C2", "C4")] and len(out["conflict_candidates"]) == 3
    c = {x["id"]: x for x in out["claims"]}
    assert c["C2"]["conflicts_with"] == ["C4"] and c["C1"]["conflicts_with"] == []
    ch = out["checks"]
    assert (ch["conflict_candidates"], ch["verify_unchecked"], ch["verify_error"], ch["calls"]) == (3, 1, None, 3)


def test_merge_10_keeps_updates_apart_and_falls_back_to_candidates_if_the_check_fails():
    checks = json.dumps({"checks": [{"pair": 1, "same_thing": "hurt", "why": "later and higher", "verdict": "update"},
                                    {"pair": 2, "same_thing": "b", "why": "w", "verdict": "none"},
                                    {"pair": 3, "same_thing": "c", "why": "w", "verdict": "none"}]})
    complete, _ = fake(MERGED_4, FOUND_3, checks)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-10")
    assert out["conflict_pass"] == [] and out["updates"] == [{"a": "C2", "b": "C4", "why": "hurt: later and higher"}]
    assert all(c["conflicts_with"] == [] for c in out["claims"])
    complete, calls = fake(MERGED_4, FOUND_3, "not json", TimeoutError("hung"))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-10")
    assert len(calls) == 4 and out["checks"]["verify_error"] and len(out["conflict_pass"]) == 3


def test_merge_11_checks_with_the_stricter_prompt():
    checks = json.dumps({"checks": [{"pair": 1, "same_thing": "hurt", "why": "two sources", "verdict": "dispute"}]})
    complete, calls = fake(MERGED_4, FOUND_3, checks)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-11")
    assert out["version"] == "merge-11" and calls[2]["messages"][0]["content"] == brief_merge.VERIFY_SYSTEM_2
    assert "numbers that fit together" in brief_merge.VERIFY_SYSTEM_2 and [(p["a"], p["b"]) for p in out["conflict_pass"]] == [("C2", "C4")]


JOINS = json.dumps({"groups": [
    {"claims": ["C3", "C1"], "claim": "The bridge closed on Friday.", "who_says": "the outlet", "why": "same closure"},
    {"claims": ["C2", "C4"], "claim": "People were hurt.", "who_says": "police; the mayor", "why": "both on the hurt"},
    {"claims": ["C1", "C5"], "claim": "x", "who_says": "x", "why": "C1 is already taken"}]})


def test_merge_12_joins_repeated_claims_after_the_conflict_check():
    checks = json.dumps({"checks": [{"pair": 1, "same_thing": "hurt", "why": "two sources", "verdict": "dispute"}]})
    complete, calls = fake(MERGED_4, FOUND_3, checks, JOINS)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-12")
    assert len(calls) == 4 and calls[3]["messages"][0]["content"] == brief_merge.JOIN_SYSTEM
    body = calls[3]["messages"][1]["content"]
    assert "C2 and C4 (conflict)" in body and "C3 [event; who: the outlet] The bridge was shut on Friday." in body
    enum = calls[3]["params"]["response_format"]["json_schema"]["schema"]["properties"]["groups"]["items"]["properties"]["claims"]["items"]["enum"]
    assert enum == ["C1", "C2", "C3", "C4", "C5"]
    assert [c["id"] for c in out["claims"]] == ["C1", "C2", "C4", "C5"]            # C3 joined into C1, ids kept
    c1 = out["claims"][0]
    assert c1["facts"] == ["a_n1#1", "a_s1#1"] and c1["articles"] == ["a_n1", "a_s1"] and len(c1["sources"]) == 2
    assert out["joined"] == [dict(keep="C1", joined=["C3"], before={"C1": "The bridge closed on Friday.", "C3": "The bridge was shut on Friday."},
                                  claim="The bridge closed on Friday.", who_says="the outlet", why="same closure")]
    assert len(out["join_rejected"]) == 1 and "C2" in out["join_rejected"][0]["reason"]     # a conflict pair stays apart
    ch = out["checks"]
    assert ch["claims_joined"] == 1 and ch["join_groups"] == 1 and ch["join_error"] is None and ch["multi_article"] == 1
    complete, calls = fake(MERGED_4, FOUND_3, checks)
    brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-11")               # merge-11: no join call
    assert len(calls) == 3


def test_joining_moves_conflicts_and_updates_to_the_kept_claim():
    def c(i, text, facts, conflicts=(), who="the outlet"):
        return dict(id=i, claim=text, kind="number", who_says=who, conflicts_with=list(conflicts), facts=list(facts),
                    sources=[dict(fact=f, article=f.split("#")[0], quote="q") for f in facts],
                    articles=sorted({f.split("#")[0] for f in facts}))
    claims = [c("C1", "Police said 12 died.", ["a1#1"], ["C3"], "police"), c("C2", "Officers said 12 people died.", ["a2#1"], [], "officers"),
              c("C3", "The mayor said 15 died.", ["a3#1"], ["C1"], "the mayor"), c("C4", "Later 20 had died.", ["a4#1"])]
    updates = [dict(a="C2", b="C4", why="rose"), dict(a="C1", b="C2", why="odd")]
    groups = [dict(claims=["C2", "C1"], claim="", who_says="", why="same count")]
    out, joined, rejected, remap = brief_merge.join_claims(claims, groups, [updates[0]])
    assert remap == {"C2": "C1"} and [x["id"] for x in out] == ["C1", "C3", "C4"]
    assert out[0]["who_says"] == "police; officers" and out[0]["claim"] == "Police said 12 died."   # empty answer: kept words
    assert out[0]["conflicts_with"] == ["C3"] and out[1]["conflicts_with"] == ["C1"]
    assert brief_merge.remap_pairs(updates, remap) == [dict(a="C1", b="C4", why="rose")]           # C1-C2 is now one claim
    claims2 = [dict(x, conflicts_with=list(x["conflicts_with"])) for x in claims]
    _, joined, rejected, remap = brief_merge.join_claims(claims2, [dict(claims=["C1", "C3"], claim="", who_says="", why="")])
    assert not joined and remap == {} and rejected[0]["claims"] == ["C1", "C3"]


def test_an_unusable_join_answer_keeps_the_claims_and_records_the_error():
    checks = json.dumps({"checks": []})
    complete, calls = fake(MERGED_4, json.dumps({"pairs": []}), "nope", "still nope")
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-12")
    assert len(calls) == 4 and out["checks"]["join_error"].startswith("no usable join answer")
    assert len(out["claims"]) == 5 and out["joined"] == [] and out["checks"]["claims_joined"] == 0


KEEPS = json.dumps({"groups": [
    {"keep": "C1", "others": ["C3", "C5", "C1", "C9"], "why": "same closure"},   # C1 and unknown C9 dropped by code
    {"keep": "C2", "others": ["C4"], "why": "both on the hurt"}]})


def test_merge_13_keeps_one_claims_words_and_joins_only_checked_pairs():
    checks = json.dumps({"checks": [{"pair": 1, "same_thing": "hurt", "why": "two sources", "verdict": "dispute"}]})
    same = json.dumps({"checks": [{"pair": 1, "verdict": "same", "why": "shut is closed"},
                                  {"pair": 2, "verdict": "adds", "why": "different fact"}]})
    complete, calls = fake(MERGED_4, FOUND_3, checks, KEEPS, same)
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-13")
    assert len(calls) == 5 and calls[3]["messages"][0]["content"] == brief_merge.JOIN_SYSTEM_2
    check = calls[4]["messages"]
    assert check[0]["content"] == brief_merge.JOIN_CHECK_SYSTEM and "Pair 3" not in check[1]["content"]   # 12 vs 15 never asked
    assert "Pair 1:\nK (C1; who: the outlet): The bridge closed on Friday.\nO (C3; who: the outlet): The bridge was shut on Friday." in check[1]["content"]
    assert [c["id"] for c in out["claims"]] == ["C1", "C2", "C4", "C5"]
    assert out["claims"][0]["claim"] == "The bridge closed on Friday." and out["claims"][0]["facts"] == ["a_n1#1", "a_s1#1"]
    assert [(j["keep"], j["other"], j["numbers_fit"], j["verdict"]) for j in out["join_checks"]] == [
        ("C1", "C3", True, "same"), ("C1", "C5", True, "adds"), ("C2", "C4", False, None)]
    ch = out["checks"]
    assert (ch["join_proposed"], ch["join_numbers_refused"], ch["join_check_same"], ch["claims_joined"]) == (3, 1, 1, 1)
    assert ch["calls"] == 5 and ch["join_error"] is None


def test_merge_13_joins_nothing_when_the_check_answer_is_unusable():
    complete, calls = fake(MERGED_4, json.dumps({"pairs": []}), KEEPS, "nope", "still nope")
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-13")
    assert len(calls) == 5 and out["checks"]["join_error"].startswith("no usable join check")   # merge, conflicts, join, check, retry
    assert len(out["claims"]) == 5 and out["joined"] == [] and out["checks"]["claims_joined"] == 0


def test_the_number_guard_and_kept_words():
    assert brief_merge.numbers("About 1,200 people, three of them hurt, on 25 Nov.") == {"1200", "3", "25"}
    assert brief_merge.numbers_fit("Police said 12 were hurt.", "Twelve people, police said 12, were hurt on Friday 3rd")
    assert not brief_merge.numbers_fit("The talk lasted 42 minutes.", "The talk lasted about 40 minutes.")
    assert not brief_merge.numbers_fit("Five were wounded.", "6 were wounded.")
    def c(i, text, facts, conflicts=(), who="the outlet"):
        return dict(id=i, claim=text, kind="number", who_says=who, conflicts_with=list(conflicts), facts=list(facts),
                    sources=[dict(fact=f, article=f.split("#")[0], quote="q") for f in facts],
                    articles=sorted({f.split("#")[0] for f in facts}))
    claims = [c("C1", "Police said 12 died.", ["a1#1"], ["C3"], "police"), c("C2", "12 people died.", ["a2#1"]),
              c("C3", "The mayor said 15 died.", ["a3#1"], ["C1"], "the mayor"), c("C4", "Twelve died.", ["a4#1"], [], "officers; the outlet")]
    out, joined, rejected, remap = brief_merge.join_kept(claims, [dict(keep="C1", others=["C2", "C3", "C4"], why="w"),
                                                                 dict(keep="C2", others=["C4"], why="w")])
    assert remap == {"C2": "C1", "C4": "C1"} and [x["id"] for x in out] == ["C1", "C3"]
    assert out[0]["claim"] == "Police said 12 died." and out[0]["who_says"] == "police; officers; the outlet"
    assert out[0]["articles"] == ["a1", "a2", "a4"] and out[1]["conflicts_with"] == ["C1"]
    assert [r["reason"] for r in rejected] == ["a pair that must stay apart", "the kept claim is already in another group"]


MERGED_OWN = answer([claim("The bridge closed on Friday.", ["F1"], conflicts=[3, 5]),
                     claim("Police said 12 people were hurt.", ["F2"], "number", "police", [4]),
                     claim("The bridge was shut on Friday.", ["F3"], conflicts=[1]),
                     claim("The mayor said 15 people were hurt.", ["F4"], "number", "the mayor", [2]),
                     claim("Subscribe.", ["F5"], conflicts=[1])])
FOUND_1 = json.dumps({"pairs": [{"a": "C2", "b": "C4", "why": "12 against 15", "conflict": True}]})


def verdicts(*vs):
    return json.dumps({"checks": [{"pair": i, "same_thing": "x", "why": "w", "verdict": v} for i, v in enumerate(vs, 1)]})


def test_merge_14_checks_the_merge_calls_own_conflict_marks():
    complete, calls = fake(MERGED_OWN, FOUND_1, verdicts("dispute"), verdicts("none", "update"))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-14")
    assert len(calls) == 4 and calls[3]["name"] == "brief_merge verify own"
    body = calls[3]["messages"][1]["content"]
    assert "Pairs (2):" in body and "P1\n  C1 " in body and "\n  C3 " in body and "P2\n  C1 " in body and "\n  C5 " in body
    c = {x["id"]: x for x in out["claims"]}
    assert c["C2"]["conflicts_with"] == ["C4"] and c["C1"]["conflicts_with"] == [] and c["C3"]["conflicts_with"] == []
    assert out["updates"] == [dict(a="C1", b="C5", why="x: w")]
    assert [(m["a"], m["b"], m["checked"], m["verdict"]) for m in out["own_marks"]] == [
        ("C1", "C3", "own call", "none"), ("C1", "C5", "own call", "update"), ("C2", "C4", "before", "dispute")]
    ch = out["checks"]
    assert (ch["own_marks"], ch["own_marks_kept"], ch["own_marks_updates"], ch["own_check_error"], ch["calls"]) == (3, 1, 1, None, 4)


def test_merge_14_keeps_the_own_marks_if_their_check_fails_and_merge_11_never_checks_them():
    complete, calls = fake(MERGED_OWN, json.dumps({"pairs": []}), "nope", "still nope")
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-14")
    assert len(calls) == 4 and out["checks"]["own_check_error"].startswith("no usable check answer")
    c = {x["id"]: x for x in out["claims"]}
    assert sorted(c["C1"]["conflicts_with"]) == ["C3", "C5"] and c["C4"]["conflicts_with"] == ["C2"]
    complete, calls = fake(MERGED_OWN, FOUND_1, verdicts("none"))
    out = brief_merge.merge_story(EVENT, STEP1, complete, prompt="merge-11")    # merge-11: marks stay unchecked
    assert len(calls) == 3 and sorted(out["claims"][0]["conflicts_with"]) == ["C3", "C5"]
    assert out["claims"][1]["conflicts_with"] == ["C4"] and "own_marks" not in out
