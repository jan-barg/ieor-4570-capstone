"""Module 5, step 4 (how each side tells it). Made-up stories only; the model is a fake."""
import json

from stringer import brief_framing, brief_sides
from stringer.evals import brief_framing_eval, runner

LENS = {"kind": "world", "sides": [
    {"side_id": "north", "label": "Northland outlets", "outlet_ids": ["n_daily", "n_post"]},
    {"side_id": "south", "label": "Southland outlets", "outlet_ids": ["s_times", "s_news"]}]}
EVENT = {"title": "Bridge closes after storm", "summary": "A storm shut the river bridge.", "confidence": "70"}
TEXT = {"a_n1": "Southern sabotage is suspected after the bridge supports failed overnight, the defence minister said on Friday.",
        "a_n2": "The regime in the south has questions to answer after the bridge supports failed, the minister said on Friday.",
        "a_s1": "Officials shut the river bridge on Friday after the storm damaged two supports, engineers said at a briefing.",
        "a_s2": "Engineers blamed years of neglect by the northern government for the failure of the old river bridge supports."}


def art(aid, outlet):
    return {"id": aid, "outlet": outlet, "url": f"https://example.test/{aid}", "published_at": "2026-01-02T03:04:00Z",
            "title": f"Headline {aid} - Outlet", "text": TEXT.get(aid, "Short text about the bridge closing on Friday after the storm."),
            "labels": {"outlet_id": outlet, "outlet_name": outlet.replace("_", " ").title(), "reliability": 0.8,
                       "is_wire": False, "us_lean": None, "state_media": None}}


ARTS = [art("a_n1", "n_daily"), art("a_n2", "n_post"), art("a_s1", "s_times"), art("a_s2", "s_news"), art("a_w1", "wire")]
GROUPS = {"a_n1": "A", "a_n2": "A", "a_s1": "B", "a_s2": "B", "a_w1": "wire"}
FRAMING = {"a_n1": dict(headline="Sabotage feared as bridge fails", opening="Southern sabotage is suspected after the bridge supports failed overnight.",
                        terms=["sabotage", "southern agents"]),
           "a_n2": dict(headline="Southern regime blamed for bridge failure", opening="The regime in the south has questions to answer.",
                        terms=["regime", "bridge failure"]),
           "a_s1": dict(headline="Storm shuts river bridge", opening="Officials shut the river bridge on Friday.", terms=["storm", "river bridge"]),
           "a_s2": dict(headline="Neglect behind bridge collapse, engineers say",
                        opening="Engineers blamed years of neglect by the northern government.", terms=["neglect", "northern government"])}
STEP1 = {"articles": [{"article": a, "lang": "en", "facts": [], "framing": f} for a, f in FRAMING.items()]}


def claim(cid, text, *arts):
    return {"id": cid, "claim": text, "kind": "event", "who_says": "the outlet", "conflicts_with": [],
            "sources": [{"fact": f"{a}#1", "article": a, "quote": "q"} for a in arts], "articles": sorted(set(arts))}


STEP2 = {"claims": [claim("C1", "The bridge closed on Friday.", "a_n1", "a_s1"),
                    claim("C2", "The defence minister suspects sabotage.", "a_n1", "a_n2"),
                    claim("C3", "Engineers blamed years of neglect.", "a_s2"),
                    claim("C4", "Ferries will run.", "a_w1")]}


def sides(lens=LENS, s1=STEP1, arts=ARTS):
    return brief_sides.add_sides(STEP2, s1, arts, GROUPS, lens, EVENT)


GOOD = {"side_a": {"points": [
            {"point": "Northern outlets frame the failure as southern sabotage.", "kind": "blame or credit",
             "quotes": [{"article": "A1", "words": "Southern sabotage is suspected", "words_en": ""},
                        {"article": "A2", "words": "Southern regime blamed", "words_en": ""}]},
            {"point": "Northern outlets call the southern government a regime.", "kind": "word choice",
             "quotes": [{"article": "A2", "words": "regime", "words_en": ""}]}]},
        "side_b": {"points": [
            {"point": "Southern outlets lead with the storm and the closure.", "kind": "emphasis",
             "quotes": [{"article": "B1", "words": "Storm shuts river bridge", "words_en": ""}]},
            {"point": "Southern outlets blame northern neglect.", "kind": "blame or credit",
             "quotes": [{"article": "B2", "words": "years of neglect by the northern government", "words_en": ""}]}]}}


class Fake:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, messages, name=None, **params):
        self.calls.append((name, messages, params))
        a = self.answers.pop(0) if self.answers else ""
        return type("R", (), {"text": a if isinstance(a, str) else json.dumps(a)})()


def frame(fake, **kw):
    return brief_framing.frame_story(sides(**kw), STEP1, ARTS, EVENT, fake, model="deepseek-v4.1-flash")["framing"]


def test_the_call_sees_each_sides_framing_and_one_side_claims_but_not_the_wires():
    fake = Fake(GOOD)
    frame(fake)
    body = fake.calls[0][1][1]["content"]
    assert "Side A: Northland outlets (2 articles)" in body and "[A1] N Daily" in body and "Words used: sabotage; southern agents" in body
    assert "Claims only side A reports (1):\n- The defence minister suspects sabotage." in body
    assert "Claims only side B reports (1):\n- Engineers blamed years of neglect." in body
    assert "Wire" not in body and "Ferries" not in body
    sch = fake.calls[0][2]["response_format"]["json_schema"]["schema"]["properties"]
    assert sch["side_a"]["properties"]["points"]["items"]["properties"]["quotes"]["items"]["properties"]["article"]["enum"] == ["A1", "A2"]
    assert fake.calls[0][2]["max_tokens"] == brief_framing.MAX_TOKENS[brief_framing.VERSION] == 4000
    assert "never quote them" in fake.calls[0][1][0]["content"]


def test_points_keep_checked_quotes_with_article_ids_and_outlet_counts():
    f = frame(Fake(GOOD))
    a, b = f["sides"]
    assert a["side_id"] == "north" and len(a["points"]) == 2 and len(b["points"]) == 2
    p = a["points"][0]
    assert p["articles"] == ["a_n1", "a_n2"] and p["outlets"] == 2 and p["quotes"][0]["outlet"] == "N Daily"
    assert b["points"][1]["quotes"][0]["article"] == "a_s2" and f["calls"] == 1 and f["quotes_bad_first"] == 0


def test_quotes_match_whole_words_and_forgive_only_typography_and_case():
    hay = brief_framing._hay(ARTS[0], FRAMING["a_n1"])
    assert brief_framing.found("southern  SABOTAGE is suspected", hay)
    assert brief_framing.found("“Sabotage feared”", hay)
    assert not brief_framing.found("sabot", hay) and not brief_framing.found("an", hay)
    assert not brief_framing.found("northern sabotage", hay)


def test_a_bad_quote_gets_one_retry_and_points_without_good_quotes_are_dropped():
    bad = json.loads(json.dumps(GOOD))
    bad["side_a"]["points"][1]["quotes"][0]["words"] = "dictatorship"            # not in A2
    bad["side_b"]["points"][0]["quotes"][0].update(article="A1", words="Southern sabotage is suspected")   # the other side's words
    fake = Fake(bad, bad)
    f = frame(fake)
    assert f["retried_quotes"] and f["quotes_bad_first"] == 2 and f["calls"] == 2
    assert "dictatorship" in fake.calls[1][1][-1]["content"]
    assert [len(s["points"]) for s in f["sides"]] == [1, 1] and f["points_dropped"] == 2
    f = frame(Fake(bad, GOOD))                                                  # the retry fixes them
    assert [len(s["points"]) for s in f["sides"]] == [2, 2] and f["points_dropped"] == 0


def test_no_real_divide_is_skipped_without_a_call_and_an_empty_side_is_recorded():
    fake = Fake(GOOD)
    f = frame(fake, lens={"kind": "none", "sides": []})
    assert fake.calls == [] and f["skipped"] == [{"reason": "no real divide"}] and f["sides"] == []
    arts = [a for a in ARTS if a["id"] not in ("a_s1", "a_s2")]
    one = {"side_a": GOOD["side_a"]}
    fake = Fake(one)
    out = brief_framing.frame_story(sides(arts=arts), STEP1, arts, EVENT, fake, model="m")["framing"]
    assert out["skipped"][0]["reason"] == "empty side" and out["skipped"][0]["side"] == "south"
    assert [s["side_id"] for s in out["sides"]] == ["north"] and "side_b" not in fake.calls[0][2]["response_format"]["json_schema"]["schema"]["properties"]


def test_unusable_answers_give_an_error_and_no_points():
    f = frame(Fake("nope", '{"side_a": {"points": []}, "side_b": {"points": []}}'))
    assert f["error"].startswith("no usable answer") and f["sides"] == [] and f["calls"] == 2
    f = frame(Fake("```json\n" + json.dumps(GOOD) + "\n```"))
    assert len(f["sides"]) == 2


def test_a_snippet_only_article_shows_its_headline_only():
    s1 = {"articles": [r for r in STEP1["articles"] if r["article"] != "a_s2"]}
    fake = Fake(GOOD)
    brief_framing.frame_story(sides(s1=s1), s1, ARTS, EVENT, fake, model="m")
    body = fake.calls[0][1][1]["content"]
    assert "[B2] S News\n  Headline: Headline a_s2\n  (headline only)" in body


def test_the_eval_scores_and_summarizes(tmp_path):
    ev = brief_framing_eval.BriefFramingEval(runs_dir=tmp_path)
    assert ev.version.startswith(f"{brief_framing.VERSION}-{brief_sides.VERSION}-")
    item = runner.Item(id="story:s1", story="s1", data={})
    out = brief_framing.frame_story(sides(), STEP1, ARTS, EVENT, Fake(GOOD), model="m")
    sc = ev.score(item, out, {})
    assert sc["points"] == 4 and sc["pattern"] == 1 and sc["described"] == 2 and not sc["failed"]
    s = ev.summarize([item], [sc])
    assert s["points_per_side"] == 2.0 and s["pattern_share"] == 0.25 and s["sides_described"] == 2
    rows = ev.mistakes({"items_detail": [{"story": "s1", "output": out}]})
    assert len(rows) == 4 and rows[0]["pred"].startswith("N Daily: “Southern sabotage is suspected”")


def test_joined_items_other_articles_of_the_side_and_cjk_are_handled():
    d = json.loads(json.dumps(GOOD))
    d["side_a"]["points"][1]["quotes"] = [{"article": "A1", "words": "regime; sabotage", "words_en": ""}]   # joined; regime is A2's
    d["side_b"]["points"][0]["quotes"] = [{"article": "B2", "words": "Storm shuts river bridge", "words_en": ""}]  # it's B1's
    f = frame(Fake(d))
    assert f["quotes_bad_first"] == 0 and f["calls"] == 1
    q = f["sides"][0]["points"][1]["quotes"]
    assert [(x["article"], x["words"]) for x in q] == [("a_n2", "regime"), ("a_n1", "sabotage")]
    assert f["sides"][1]["points"][0]["quotes"][0]["article"] == "a_s1"
    hay = brief_framing.norm("国家主席习近平同美国总统通电话").lower()
    assert brief_framing.found("国家主席习近平", hay) and not brief_framing.found("习近平主席", hay)
    assert brief_framing.found("دریادار", brief_framing.norm("دريادار عزمايی").lower())


def test_the_first_prompt_stays_runnable():
    fake = Fake(GOOD)
    brief_framing.frame_story(sides(), STEP1, ARTS, EVENT, fake, model="m", prompt="frame-1")
    assert fake.calls[0][1][0]["content"] == brief_framing.SYSTEM and fake.calls[0][2]["max_tokens"] == 8000
    import pytest
    with pytest.raises(ValueError):
        brief_framing_eval.BriefFramingEval(prompt="frame-9")
