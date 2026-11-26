"""Module 5 step 1 (reading an article into fact cards) and its eval. Made-up articles and events only."""
import json
from types import SimpleNamespace

from stringer import brief_read
from stringer.evals import brief_read_eval, runner

EVENT = {"title": "Bridge closes after storm", "summary": "A storm damaged the river bridge in Testville.",
         "start": "2026-01-02T03:04:00Z"}
TEXT = ("* [Home](https://x.example) * [World](https://x.example/w)\n"
        "# Storm shuts Testville bridge\n"
        "The river bridge in Testville was closed on Friday after a storm cracked two of its supports, "
        "city officials said.\n"
        "“We will not reopen it until engineers sign off,” the mayor, Ann Example, told reporters.\n"
        "[Read more: other news](https://x.example/other)")
ART = {"id": "a_test1", "text": TEXT, "title": "Storm shuts Testville bridge - Example Times", "text_status": "full"}


def answer(facts, lang="en"):
    return json.dumps({"language": lang, "facts": facts,
                       "framing": {"headline": "Storm shuts Testville bridge", "opening": "The river bridge", "terms": ["storm"]}})


GOOD = {"fact": "Officials closed the Testville bridge after a storm cracked two supports.",
        "quote": "was closed on Friday after a storm cracked two of its supports", "quote_en": "",
        "kind": "event", "who_says": "city officials"}
MAYOR = {"fact": "The mayor said the bridge stays shut until engineers approve it.",
         "quote": "\"We will not reopen it until engineers sign off,\"", "quote_en": "",
         "kind": "statement", "who_says": "the mayor"}
MADE_UP = dict(GOOD, quote="the bridge collapsed completely into the river", fact="The bridge collapsed.")


def fake(*texts):
    calls = []

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, params=params))
        return SimpleNamespace(text=texts[min(len(calls), len(texts)) - 1])
    return complete, calls


def test_menus_and_link_markup_are_gone_from_what_the_model_sees():
    text, cut = brief_read.shown_text(ART)
    assert text.startswith("# Storm shuts") and "x.example" not in text and not cut
    assert "Read more" not in text


def test_quotes_match_through_typography_only():
    t = brief_read.norm(brief_read.shown_text(ART)[0])
    assert brief_read.find_quote("\"We will not reopen it until engineers sign off,\"", t) >= 0   # straight vs curly
    assert brief_read.find_quote("was  closed on Friday\nafter a storm", t) >= 0                    # spacing
    assert brief_read.find_quote("cracked two of its supports, city‑officials said", t) == -1  # hyphen is not a space
    assert brief_read.norm("Russian‑installed governor") == "Russian-installed governor"   # read-2
    assert brief_read.find_quote("was closed on Saturday after a storm", t) == -1                  # a changed word
    assert brief_read.find_quote("was closed", t) == -1                                             # too short to prove anything


def test_good_answer_gives_checked_cards_with_ids():
    complete, calls = fake(answer([GOOD, MAYOR]))
    out = brief_read.read_article(EVENT, ART, complete, model="haiku-5-5")
    assert [f["id"] for f in out["facts"]] == ["a_test1#1", "a_test1#2"]
    assert out["checks"]["facts_first"] == 2 and out["checks"]["quotes_bad_first"] == 0 and len(calls) == 1
    assert calls[0]["params"]["response_format"]["type"] == "json_schema"
    assert "Example Times" not in json.dumps(calls[0]["messages"])                                 # outlet hidden


def test_a_failed_quote_gets_one_retry_naming_it():
    complete, calls = fake(answer([GOOD, MADE_UP]), answer([GOOD, MAYOR]))
    out = brief_read.read_article(EVENT, ART, complete)
    assert len(calls) == 2 and "the bridge collapsed completely" in calls[1]["messages"][-1]["content"]
    assert out["checks"]["retried_quotes"] and out["checks"]["facts_dropped"] == 0 and len(out["facts"]) == 2


def test_a_quote_that_fails_twice_is_dropped_and_counted():
    complete, calls = fake(answer([GOOD, MADE_UP]), answer([GOOD, MADE_UP]))
    out = brief_read.read_article(EVENT, ART, complete)
    assert len(out["facts"]) == 1 and out["checks"]["facts_dropped"] == 1


def test_unusable_json_is_asked_again_once_then_reported():
    complete, calls = fake("Sorry, here are the facts: none", "still not json")
    out = brief_read.read_article(EVENT, ART, complete)
    assert len(calls) == 2 and out["facts"] == [] and out["checks"]["error"]
    complete, _ = fake("```json\n" + answer([GOOD]) + "\n```")
    assert len(brief_read.read_article(EVENT, ART, complete)["facts"]) == 1


def test_gpt_oss_reasons_on_low_effort():
    assert brief_read.params_for("gpt-oss-120b")["reasoning_effort"] == "low"
    assert "reasoning_effort" not in brief_read.params_for("haiku-5-5")


def test_judge_sees_short_ids_and_answers_map_back():
    facts = [dict(GOOD, id="a_test1#1"), dict(MAYOR, id="a_test1#2")]
    msgs, ids = brief_read_eval.judge_messages(["The bridge was closed."], facts)
    assert "M1: The bridge was closed." in msgs[1]["content"] and ids == {"F1": "a_test1#1", "F2": "a_test1#2"}


def test_scoring_counts_coverage_and_quotes():
    ev = brief_read_eval.BriefReadEval()
    item = runner.Item(id="story:s1", story="s1", data={})
    out = {"articles": [{"article": "a1", "lang": "fr", "facts": [{}, {}],
                         "checks": dict(facts_first=3, quotes_bad_first=1, facts_dropped=1, retried_json=True)},
                        {"article": "a2", "lang": "en", "facts": [], "checks": dict(error="no usable answer")}],
           "judge": {"results": {"M1": {"found": True}, "M2": {"found": False}}}}
    s = ev.score(item, out, {"s1": ["fact one", "fact two"]})
    assert (s["coverage"], s["found"], s["facts_dropped"], s["articles_failed"], s["non_english"]) == (0.5, 1, 1, 1, 1)
    summ = ev.summarize([item], [s])
    assert summ["quote_ok_first"] == round(1 - 1 / 3, 3) and summ["facts_per_article"] == 1.0


def test_ctx_can_call_a_fixed_judge_model_through_the_same_cap():
    seen = []

    def complete_fn(model, messages, **kw):
        seen.append(model)
        return SimpleNamespace(text="{}", usage={"input_uncached": 10, "output": 5}, cost={"total": 0.0001},
                               latency_s=0.1)
    ctx = runner.Ctx(model="haiku-5-5", trace_id=None, budget=runner.Budget(1.0), cache=None, complete_fn=complete_fn)
    ctx.complete([{"role": "user", "content": "hi"}])
    ctx.complete([{"role": "user", "content": "hi"}], model="gemini-3.5-flash-lite")
    assert seen == ["haiku-5-5", "gemini-3.5-flash-lite"] and ctx.stats.calls == 2


def test_a_hung_or_failed_call_counts_as_an_empty_answer():
    calls = []

    def complete(messages, name=None, **params):
        calls.append(params)
        if len(calls) == 1:
            raise TimeoutError("timed out after 180 s")
        return SimpleNamespace(text=answer([GOOD]))
    out = brief_read.read_article(EVENT, ART, complete)
    assert len(out["facts"]) == 1 and out["checks"]["retried_json"] and "TimeoutError" in out["checks"]["call_errors"][0]
    assert calls[0]["timeout"] == brief_read.CALL_TIMEOUT_S


def test_the_cost_cap_still_stops_the_run():
    class BudgetExceeded(RuntimeError):
        pass

    def complete(messages, name=None, **params):
        raise BudgetExceeded("cap")
    try:
        brief_read.read_article(EVENT, ART, complete)
        assert False, "should have stopped"
    except BudgetExceeded:
        pass


def test_a_timeout_does_not_change_the_cache_key():
    from stringer.evals.cache import call_key
    m = [{"role": "user", "content": "x"}]
    assert call_key("m", m, {"max_tokens": 5, "timeout": 180}) == call_key("m", m, {"max_tokens": 5})
