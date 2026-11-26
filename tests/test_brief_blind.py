"""Module 5, step 3b (the blindspot judge). Made-up stories only; the model is a fake."""
import json

from stringer import brief_blind, brief_sides
from stringer.evals import brief_blind_eval, runner

LENS = {"kind": "world", "sides": [
    {"side_id": "north", "label": "Northland outlets", "outlet_ids": ["n_daily", "n_post"]},
    {"side_id": "south", "label": "Southland outlets", "outlet_ids": ["s_times", "s_news"]}]}
EVENT = {"title": "Bridge closes after storm", "summary": "A storm shut the river bridge.", "confidence": "70"}

N1 = ("The river bridge closed on Friday after the overnight storm cracked two of its main supports, officials said. "
      "Engineers expect the repairs to take at least three months before traffic can return.")
N2 = ("Two supports of the river bridge cracked in the storm and the crossing was closed on Friday morning by the city. "
      "The mayor said the city had ignored warnings about the supports for five years before the storm.")
S1 = ("Officials shut the river bridge on Friday after storm damage was found during an inspection of the structure. "
      "Two of the bridge's supports cracked during the storm, engineers said at a news conference on Friday. "
      "Repairs will take about a month, the regional transport minister told reporters in the capital.")
S2 = ("Ferries will carry drivers across the river while the damaged bridge stays closed for repairs, the operator said. "
      "Repairs will take about a month according to the regional transport ministry, which blamed the storm for it.")


def art(aid, outlet, text):
    return {"id": aid, "outlet": outlet, "url": f"https://example.test/{aid}", "published_at": "2026-01-02T03:04:00Z",
            "title": f"Headline {aid} - Outlet", "text": text,
            "labels": {"outlet_id": outlet, "outlet_name": outlet.title(), "reliability": 0.8, "is_wire": False,
                       "us_lean": None, "state_media": None}}


ARTS = [art("a_n1", "n_daily", N1), art("a_n2", "n_post", N2), art("a_s1", "s_times", S1), art("a_s2", "s_news", S2)]
GROUPS = {"a_n1": "A", "a_n2": "A", "a_s1": "B", "a_s2": "B"}
STEP1 = {"articles": [{"article": a["id"], "lang": "en", "facts": []} for a in ARTS]}


def claim(cid, text, *arts):
    return {"id": cid, "claim": text, "kind": "event", "who_says": "the outlet", "conflicts_with": [],
            "sources": [{"fact": f"{a}#1", "article": a, "quote": f"quote from {a} for {cid}"} for a in arts],
            "articles": sorted(set(arts))}


STEP2 = {"claims": [
    claim("C1", "The bridge closed on Friday.", "a_n1", "a_s1"),
    claim("C2", "Two supports cracked in the storm.", "a_n1", "a_n2"),                 # south says it too
    claim("C3", "The city ignored warnings for five years.", "a_n1", "a_n2"),          # missing from the south
    claim("C4", "Repairs will take at least three months.", "a_n1", "a_n2"),           # south: about a month
    claim("C5", "A northern blog says the mayor knew.", "a_n1"),                       # one source: not checked
    claim("C6", "Ferries will carry drivers across the river.", "a_s1", "a_s2")]}      # north is silent


def sides():
    return brief_sides.add_sides(STEP2, STEP1, ARTS, GROUPS, LENS, EVENT)


def row(cid, verdict, quote="", article="", matters="central", quote_en=""):
    return dict(claim_id=cid, quote=quote, quote_en=quote_en, article=article, why="made up", verdict=verdict, matters=matters)


GOOD_SOUTH = [row("C2", "reports it", "Two of the bridge's supports cracked during the storm, engineers said", "S1"),
              row("C3", "missing"),
              row("C4", "different account", "Repairs will take about a month, the regional transport minister told reporters", "S1",
                  matters="detail")]
GOOD_NORTH = [row("C6", "missing", matters="detail")]


class Fake:
    """Answers per silent side from a list of scripted answers (text or dict); records the calls."""

    def __init__(self, south, north=None):
        self.answers = {"Southland outlets": list(south), "Northland outlets": list(north or [{"checks": GOOD_NORTH}])}
        self.calls = []

    def __call__(self, messages, name=None, **params):
        self.calls.append((name, messages, params))
        side = next(k for k in self.answers if f"Silent side: {k}." in messages[1]["content"])
        a = self.answers[side].pop(0) if self.answers[side] else ""
        return type("R", (), {"text": a if isinstance(a, str) else json.dumps(a)})()


def judge(fake):
    return brief_blind.judge_blindspots(sides(), ARTS, EVENT, fake, model="deepseek-v4.1-flash")


def south(out):
    return next(j for j in out["blindspot_checks"] if j["silent_side"] == "south")


def test_only_candidates_with_two_independent_sources_are_checked():
    c = {x["silent_side"]: x for x in brief_blind.candidates(sides())}
    assert c["south"]["claims"] == ["C2", "C3", "C4"] and c["north"]["claims"] == ["C6"]     # C5: one source
    many = dict(sides(), blindspots=[dict(silent_side="south", label="S", reported_by="north",
                                          claims=[f"X{i}" for i in range(14)], sources={f"X{i}": 2 for i in range(14)})])
    got = brief_blind.candidates(many)[0]
    assert len(got["claims"]) == brief_blind.MAX_CLAIMS and got["cut"] == 14 - brief_blind.MAX_CLAIMS


def test_the_judge_sees_the_claims_and_only_the_silent_sides_articles():
    fake = Fake([{"checks": GOOD_SOUTH}])
    judge(fake)
    south = next(m for _, m, _ in fake.calls if "Silent side: Southland" in m[1]["content"])[1]["content"]
    assert "- C2: Two supports cracked in the storm. (reported by: N_Daily, N_Post)" in south
    assert "[S1] S_Times" in south and "[S2] S_News" in south and "ignored warnings" not in south.split("Its articles")[1]
    assert all(p["max_tokens"] == brief_blind.MAX_TOKENS[brief_blind.VERSION] for _, _, p in fake.calls)
    sch = next(p for _, m, p in fake.calls if "Silent side: Southland" in m[1]["content"])["response_format"]["json_schema"]["schema"]
    item = sch["properties"]["checks"]["items"]["properties"]
    assert item["claim_id"]["enum"] == ["C2", "C3", "C4"] and item["article"]["enum"] == ["S1", "S2", ""]


def test_checked_quotes_decide_reported_told_differently_and_blindspot():
    out = judge(Fake([{"checks": GOOD_SOUTH}]))
    st = {r["claim"]: r["status"] for j in out["blindspot_checks"] for r in j["checked"]}
    assert st == {"C2": "reported", "C3": "blindspot", "C4": "told differently", "C6": "blindspot"}
    conf = {b["silent_side"]: b for b in out["confirmed_blindspots"]}
    assert conf["south"]["central"] == ["C3"] and conf["north"]["detail"] == ["C6"] and conf["north"]["central"] == []
    c = {x["id"]: x for x in out["claims"]}
    assert c["C3"]["blindspot_check"] == {"status": "blindspot", "matters": "central"} and "blindspot_check" not in c["C5"]
    assert c["C2"]["blindspot_of"] == "south"          # step 3's candidate mark stays
    k = out["blind_counts"]
    assert (k["checked"], k["blindspot"], k["central"], k["reported"], k["told_differently"], k["calls"]) == (4, 2, 1, 1, 1, 2)


def test_a_bad_quote_gets_one_retry_and_stays_unclear_if_still_bad_or_turned_missing():
    bad = [row("C2", "reports it", "Two supports were badly cracked by the storm", "S1"), row("C3", "missing"),
           row("C4", "different account", "Repairs might take weeks, the minister said", "S2")]
    fixed = [GOOD_SOUTH[0], row("C3", "missing"), row("C4", "missing")]
    fake = Fake([{"checks": bad}, {"checks": fixed}])
    out = judge(fake)
    st = {r["claim"]: r["status"] for r in south(out)["checked"]}
    assert st == {"C2": "reported", "C3": "blindspot", "C4": "unclear"}      # C4 turned "missing" on the retry
    j = south(out)
    assert j["retried_quotes"] and j["quotes_bad_first"] == 2 and j["calls"] == 2
    note = next(m for n, m, _ in fake.calls if n.endswith("retry"))[-1]["content"]
    assert "C2 (S1)" in note and "C4 (S2)" in note and "C3" not in note
    out = judge(Fake([{"checks": bad}, {"checks": bad}]))
    assert {r["claim"]: r["status"] for r in south(out)["checked"]}["C2"] == "unclear"


def test_unusable_answers_leave_the_side_unchecked_never_confirmed():
    out = judge(Fake(["not json", "still not json"]))
    j = next(x for x in out["blindspot_checks"] if x["silent_side"] == "south")
    assert j["error"].startswith("no usable answer") and j["calls"] == 2
    assert all(r["status"] == "unchecked" for r in j["checked"])
    assert all(b["silent_side"] != "south" for b in out["confirmed_blindspots"])
    assert out["blind_counts"]["unchecked"] == 3 and out["blind_counts"]["errors"] == 1
    out = judge(Fake(["```json\n" + json.dumps({"checks": GOOD_SOUTH}) + "\n```"]))     # fenced JSON still reads
    assert out["blind_counts"]["blindspot"] == 2


def test_a_claim_the_judge_skips_or_a_made_up_label_is_not_a_blindspot():
    out = judge(Fake([{"checks": [GOOD_SOUTH[0], row("C4", "reports it", GOOD_SOUTH[2]["quote"], "S9")]},
                      {"checks": [GOOD_SOUTH[0], row("C4", "reports it", GOOD_SOUTH[2]["quote"], "S9")]}]))
    st = {r["claim"]: r["status"] for r in south(out)["checked"]}
    assert st == {"C2": "reported", "C3": "unchecked", "C4": "unclear"}     # C3 skipped twice


def test_the_eval_scores_and_summarizes(tmp_path):
    ev = brief_blind_eval.BriefBlindEval(runs_dir=tmp_path)
    assert ev.version.startswith(f"{brief_blind.VERSION}-{brief_sides.VERSION}-")
    item = runner.Item(id="story:s1", story="s1", data={})
    out = judge(Fake([{"checks": GOOD_SOUTH}]))
    sc = ev.score(item, out, {})
    assert sc["blindspot"] == 2 and sc["central"] == 1 and not sc["failed"]
    empty = ev.score(runner.Item(id="story:s2", story="s2", data={}), dict(sides(), blind_counts=dict(checked=0)), {})
    s = ev.summarize([item, item], [sc, empty])
    assert s["blindspots_per_story"] == 2.0 and s["reported_share"] == 0.25 and s["stories_checked"] == 1
    rows = ev.mistakes({"items_detail": [{"story": "s1", "output": out}]})
    assert {r["kind"] for r in rows} == {"reported", "blindspot", "told differently"} and len(rows) == 4


def test_rows_are_matched_by_id_then_claim_text_then_order():
    texts_ok = dict(GOOD_SOUTH[0], claim_id="Two supports cracked in the storm.")          # the claim's text, not its id
    out = judge(Fake([{"checks": [texts_ok, dict(GOOD_SOUTH[1], claim_id="c3"), GOOD_SOUTH[2]]}]))
    assert {r["claim"]: r["status"] for r in south(out)["checked"]} == {"C2": "reported", "C3": "blindspot", "C4": "told differently"}
    translated = [dict(r, claim_id=f"(translated) {i}") for i, r in enumerate(GOOD_SOUTH)]       # nothing matches: by order
    out = judge(Fake([{"checks": translated}]))
    assert {r["claim"]: r["status"] for r in south(out)["checked"]} == {"C2": "reported", "C3": "blindspot", "C4": "told differently"}


def test_claims_with_no_answer_get_one_retry_and_count_as_first_answers():
    fake = Fake([{"checks": []}, {"checks": GOOD_SOUTH}])
    out = judge(fake)
    assert {r["claim"]: r["status"] for r in south(out)["checked"]} == {"C2": "reported", "C3": "blindspot", "C4": "told differently"}
    assert south(out)["skipped_first"] == 3 and south(out)["calls"] == 2
    note = next(m for n, m, _ in fake.calls if n.endswith("retry"))[-1]["content"]
    assert "no answer for these claims: C2, C3, C4" in note
    out = judge(Fake([{"checks": [GOOD_SOUTH[0]]}, {"checks": [GOOD_SOUTH[0]]}]))          # still skipped: unchecked
    assert {r["claim"]: r["status"] for r in south(out)["checked"]} == {"C2": "reported", "C3": "unchecked", "C4": "unchecked"}


def test_missing_with_a_quote_found_in_the_article_is_unclear():
    hedged = row("C3", "missing", "Two of the bridge's supports cracked during the storm, engineers said", "S1")
    out = judge(Fake([{"checks": [GOOD_SOUTH[0], hedged, GOOD_SOUTH[2]]}]))
    assert {r["claim"]: r["status"] for r in south(out)["checked"]}["C3"] == "unclear"
    made_up = row("C3", "missing", "words that are nowhere in any of the articles", "S1")      # a bad quote: still missing
    out = judge(Fake([{"checks": [GOOD_SOUTH[0], made_up, GOOD_SOUTH[2]]}]))
    assert {r["claim"]: r["status"] for r in south(out)["checked"]}["C3"] == "blindspot"


def test_prompt_versions_stay_runnable():
    fake = Fake([{"checks": GOOD_SOUTH}])
    out = brief_blind.judge_blindspots(sides(), ARTS, EVENT, fake, model="deepseek-v4.1-flash", prompt="blind-5")
    assert out["blind_counts"]["version"] == "blind-5"
    assert all(m[0]["content"] == brief_blind.SYSTEM_2 and p["max_tokens"] == 8000 for _, m, p in fake.calls)
    assert "another speaker" in brief_blind.SYSTEM_2 and "main fact itself" in brief_blind.SYSTEM_2
    fake = Fake([{"checks": GOOD_SOUTH}])
    judge(fake)                                         # the default stays blind-4 (blind-5 had more wrong blindspots)
    assert brief_blind.VERSION == "blind-4"
    assert all(m[0]["content"] == brief_blind.SYSTEM and p["max_tokens"] == 16000 for _, m, p in fake.calls)
    assert brief_blind_eval.BriefBlindEval(prompt="blind-5").version.startswith("blind-5-")
    import pytest
    with pytest.raises(ValueError):
        brief_blind_eval.BriefBlindEval(prompt="blind-99")
