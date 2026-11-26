"""The judge for step 4's points, on made-up sides and points (no real stories)."""
import json
from types import SimpleNamespace

from stringer.evals import framing_judge_eval as fj

PERSPECTIVES = [
    dict(side_id="north", label="Northern outlets", points=[
        dict(kind="word choice", point="Northern outlets call the march a riot.",
             quotes=[dict(article="a1", outlet="North Daily", words="riot", words_en="")]),
        dict(kind="voices", point="They quote the mayor.",
             quotes=[dict(article="a2", outlet="North Times", words="Bürgermeister", words_en="mayor")])]),
    dict(side_id="south", label="Southern outlets", points=[
        dict(kind="emphasis", point="Southern outlets lead with the arrests.",
             quotes=[dict(article="b1", outlet="South Post", words="dozens arrested", words_en="")])]),
]


def fake(*texts):
    calls = []

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, params=params))
        t = texts[min(len(calls), len(texts)) - 1]
        if isinstance(t, Exception):
            raise t
        return SimpleNamespace(text=t)
    return complete, calls


def answer(*grades):
    return json.dumps({"grades": [dict(id=i, grade=g, fails=f, why="w") for i, g, f in grades]})


def test_points_get_ids_and_stable_keys_and_the_judge_sees_labels_and_english():
    pts = fj.points_of(PERSPECTIVES)
    assert [(p["id"], p["key"]) for p in pts] == [("P1", "north#1"), ("P2", "north#2"), ("P3", "south#1")]
    msgs = fj.messages_for("Event: a march", pts, {"a1": "A1", "a2": "A2", "b1": "B1"}, {"north": "A", "south": "B"})
    user = msgs[1]["content"]
    assert user.startswith("What the writer saw:\n\nEvent: a march\n\nPoints to grade (3):")
    assert "P1 [side A: Northern outlets; word choice] Northern outlets call the march a riot." in user
    assert '   - A2 North Times: "Bürgermeister" (English: mayor)' in user and "P3 [side B: Southern outlets; emphasis]" in user


def test_grades_are_kept_only_for_known_points_and_a_good_point_fails_nothing():
    complete, calls = fake(answer(("P1", "good", "contrast"), ("P2", "weak", "quotes"), ("P9", "good", ""),
                                  ("P3", "weak", "bogus"), ("P1", "weak", "specific")))
    out = fj.judge([{"role": "user", "content": "x"}], ["P1", "P2", "P3"], complete)
    assert out["grades"] == {"P1": dict(grade="good", fails="", why="w"), "P2": dict(grade="weak", fails="quotes", why="w"),
                             "P3": dict(grade="weak", fails="", why="w")}
    assert len(calls) == 1 and out["error"] is None
    assert calls[0]["params"]["response_format"]["json_schema"]["schema"]["properties"]["grades"]["items"]["properties"]["id"]["enum"] == ["P1", "P2", "P3"]


def test_missing_grades_are_asked_for_by_name_and_the_fuller_answer_wins():
    complete, calls = fake(answer(("P1", "good", "")), answer(("P1", "good", ""), ("P2", "weak", "contrast"), ("P3", "good", "")))
    out = fj.judge([{"role": "user", "content": "x"}], ["P1", "P2", "P3"], complete)
    assert len(calls) == 2 and "these are missing: P2, P3" in calls[1]["messages"][-1]["content"]
    assert set(out["grades"]) == {"P1", "P2", "P3"}
    complete, calls = fake(answer(("P1", "good", ""), ("P2", "weak", "quotes")), "not json")
    out = fj.judge([{"role": "user", "content": "x"}], ["P1", "P2", "P3"], complete)
    assert set(out["grades"]) == {"P1", "P2"} and out["error"] is None


def test_no_usable_answer_after_one_retry_is_an_error_not_a_guess():
    complete, calls = fake("nope", TimeoutError("hung"))
    out = fj.judge([{"role": "user", "content": "x"}], ["P1"], complete)
    assert out["grades"] == {} and out["error"].startswith("no usable framing judge answer") and "TimeoutError" in out["error"]


def test_agreement_with_jan_counts_only_points_jan_graded(tmp_path):
    g = tmp_path / "grades.json"
    g.write_text(json.dumps({"stories": {"s1": {"north#1": {"grade": "weak"}, "north#2": {"grade": "good"},
                                                "south#1": {"grade": "good"}, "south#2": {"grade": "maybe"}}}}))
    key = fj.load_grades(g)
    assert key == {"s1": {"north#1": "weak", "north#2": "good", "south#1": "good"}}
    e = fj.FramingJudgeEval(grades=g)
    out = dict(points=[dict(key="north#1", grade="good", fails=""), dict(key="north#2", grade="good", fails=""),
                       dict(key="south#1", grade="weak", fails="contrast"), dict(key="south#3", grade=None, fails="")])
    s = e.score(SimpleNamespace(story="s1"), out, key)
    assert (s["jan"], s["agree"], s["kinder"], s["harsher"], s["ungraded"], s["judge_good"]) == (3, 1, 1, 1, 1, 2)
    summ = e.summarize([SimpleNamespace(story="s1")], [s])
    assert summ["agreement"] == 0.333 and summ["jan_good_share"] == 0.667 and summ["fails"]["contrast"] == 1
    assert fj.load_grades(tmp_path / "none.json") == {}


def test_fjudge_2_accepts_names_as_a_voices_points_quotes_and_runs_under_its_own_version():
    assert "not only a name" in fj.PROMPTS["fjudge-1"] and "not only a name" not in fj.PROMPTS["fjudge-2"]
    assert "quoting the names or titles of the people or bodies the side relies on is enough" in fj.PROMPTS["fjudge-2"]
    assert fj.messages_for("b", [], {}, {}, "fjudge-2")[0]["content"] == fj.PROMPTS["fjudge-2"]
    assert fj.FramingJudgeEval(judge_prompt="fjudge-2").version.startswith("fjudge-2-")
    assert fj.FramingJudgeEval().version.startswith("fjudge-2-") and fj.VERSION == "fjudge-2"
    assert fj.FramingJudgeEval(judge_prompt="fjudge-1").version.startswith("fjudge-1-")
