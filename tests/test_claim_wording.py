"""The loaded-words judge on made-up claims (no real stories)."""
import json
from types import SimpleNamespace

from stringer.evals import claim_wording_eval as cw

EVENT = {"title": "Bridge closes after storm"}
CLAIMS = [dict(id="C1", claim="The mayor slammed the regime's brutal response.", who_says="the outlet", kind="statement"),
          dict(id="C2", claim="The mayor called the response 'shameful'.", who_says="the mayor", kind="statement"),
          dict(id="C3", claim="The bridge closed on Friday.", who_says="the outlet", kind="event")]


def fake(*texts):
    calls = []

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, params=params))
        t = texts[min(len(calls), len(texts)) - 1]
        if isinstance(t, Exception):
            raise t
        return SimpleNamespace(text=t)
    return complete, calls


def answer(*flags):
    return json.dumps({"flags": [dict(id=i, words=w, why="why", neutral="n", level=l) for i, w, l in flags]})


def test_the_judge_sees_who_says_each_claim_and_only_known_ids_are_kept():
    complete, calls = fake(answer(("C1", "slammed the regime's brutal", "loaded"), ("C2", "shameful", "borderline"),
                                  ("C9", "x", "loaded"), ("C1", "again", "loaded"), ("C3", "stormy", "borderline")))
    out = cw.judge(EVENT, CLAIMS, complete)
    user = calls[0]["messages"][1]["content"]
    assert "Claims (3):\nC1 [who says: the outlet] The mayor slammed" in user and "C2 [who says: the mayor]" in user
    assert calls[0]["params"]["response_format"]["json_schema"]["schema"]["properties"]["flags"]["items"]["properties"]["id"]["enum"] == ["C1", "C2", "C3"]
    assert [(f["id"], f["level"], f["words_found"], f["in_quotes"]) for f in out["flags"]] == [
        ("C1", "loaded", True, False), ("C2", "borderline", True, True), ("C3", "borderline", False, False)]
    assert out["error"] is None and out["calls"] == 1


def test_an_unusable_answer_is_asked_again_then_recorded():
    complete, calls = fake("not json", answer(("C1", "brutal", "loaded")))
    out = cw.judge(EVENT, CLAIMS, complete)
    assert len(calls) == 2 and calls[1]["name"].endswith("retry") and len(out["flags"]) == 1
    complete, calls = fake("nope", TimeoutError("hung"))
    out = cw.judge(EVENT, CLAIMS, complete)
    assert out["flags"] == [] and out["error"].startswith("no usable wording judge answer") and "TimeoutError" in out["error"]


def test_words_are_placed_in_the_claim_with_curly_quotes():
    assert cw.placed("He called it a “terrorist act” on Friday.", "terrorist act") == (True, True)
    assert cw.placed("Troops liberated the town.", "Liberated") == (True, False)
    assert cw.placed("Troops took the town.", "liberated") == (False, False)


def test_scores_add_up():
    e = cw.ClaimWordingEval()
    flags = [dict(level="loaded", who_says="the outlet", words_found=True, in_quotes=False),
             dict(level="borderline", who_says="the mayor", words_found=False, in_quotes=True)]
    s = e.score(None, dict(flags=flags, claims=40), {})
    assert (s["flagged"], s["loaded"], s["borderline"], s["own_voice_flagged"], s["words_missing"], s["in_quotes"]) == (2, 1, 1, 1, 1, 1)
    summ = e.summarize([SimpleNamespace(story="x")], [s])
    assert summ["flagged_share"] == 0.05 and summ["own_voice_share"] == 0.5
