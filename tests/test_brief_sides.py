"""Module 5, step 3 (code adds sides, blindspots, independent sources, flags). Made-up stories only."""
import json

from stringer import brief_sides
from stringer.evals import brief_sides_eval, runner

LENS = {"kind": "world", "sides": [
    {"side_id": "north", "label": "Northland outlets", "outlet_ids": ["n_daily", "n_post"]},
    {"side_id": "south", "label": "Southland outlets", "outlet_ids": ["s_times", "s_news"]}]}
NO_DIVIDE = {"kind": "none", "sides": []}
EVENT = {"title": "Bridge closes after storm", "confidence": "70"}


def art(aid, outlet, rel, wire=False, text="", title=""):
    return {"id": aid, "outlet": outlet, "url": f"https://example.test/{aid}", "published_at": "2026-01-02T03:04:00Z",
            "title": title or f"Headline {aid} - Outlet", "text": text,
            "labels": {"outlet_id": outlet, "outlet_name": outlet.title(), "reliability": rel, "is_wire": wire,
                       "us_lean": None, "state_media": None}}


ARTS = [art("a_n1", "n_daily", 0.8), art("a_n2", "n_post", None), art("a_s1", "s_times", 0.3),
        art("a_s2", "s_news", 0.4), art("a_w1", "wirecorp", 0.95, wire=True), art("a_x1", "blog", None)]
GROUPS = {"a_n1": "A", "a_n2": "A", "a_s1": "B", "a_s2": "B", "a_w1": "wire", "a_x1": "other"}


def step1(ids=("a_n1", "a_n2", "a_s1", "a_s2", "a_w1", "a_x1")):
    return {"articles": [{"article": i, "lang": "en", "facts": []} for i in ids]}


def claim(cid, *sources):
    return {"id": cid, "claim": f"Claim {cid}.", "kind": "event", "who_says": "the outlet", "conflicts_with": [],
            "sources": [{"fact": f"{a}#1", "article": a, "quote": q} for a, q in sources],
            "articles": sorted({a for a, _ in sources})}


STEP2 = {"claims": [
    claim("C1", ("a_n1", "the bridge closed on Friday"), ("a_s1", "officials shut the bridge on Friday")),
    claim("C2", ("a_n1", "two supports cracked in the storm"), ("a_n2", "the storm cracked two supports")),
    claim("C3", ("a_s1", "northern engineers built it badly")),
    claim("C4", ("a_w1", "Ferries will carry drivers across the river until it reopens."),
          ("a_x1", "ferries will carry drivers across the river until it reopens")),
    claim("C5", ("a_x1", "a local blog says the mayor knew")),
    claim("C6", ("a_s1", "repairs will take a month"), ("a_s2", "a month of repairs is expected"))]}


def run(step2=STEP2, s1=None, arts=ARTS, groups=GROUPS, lens=LENS, event=EVENT):
    return brief_sides.add_sides(step2, s1 or step1(), arts, groups, lens, event)


def test_each_claim_gets_the_sides_that_report_it():
    out = run()
    c = {x["id"]: x for x in out["claims"]}
    assert c["C1"]["sides"] == ["north", "south"] and c["C2"]["sides"] == ["north"] and c["C3"]["sides"] == ["south"]
    assert c["C4"]["sides"] == [] and c["C4"]["neither"] == 2
    assert out["sides"]["kind"] == "two sides" and out["sides"]["A"]["articles"] == 2 and out["sides"]["B"]["label"] == "Southland outlets"
    cnt = out["counts"]
    assert (cnt["both_sides"], cnt["one_side"], cnt["neither_only"]) == (1, 3, 2)


def test_blindspots_are_claims_one_side_reports_against_a_side_with_two_articles():
    out = run()
    b = {x["silent_side"]: x for x in out["blindspots"]}
    assert b["south"]["claims"] == ["C2"] and b["south"]["reported_by"] == "north"
    assert b["north"]["claims"] == ["C6", "C3"] and b["north"]["sources"] == {"C6": 2, "C3": 1}   # strongest first
    assert {x["id"]: x["blindspot_of"] for x in out["claims"]} == {"C1": None, "C2": "south", "C3": "north", "C4": None,
                                                                    "C5": None, "C6": "north"}


def test_a_thin_side_gets_no_blindspots_and_a_flag():
    out = run(s1=step1(("a_n1", "a_n2", "a_s1", "a_w1", "a_x1")))       # only one southern article read
    assert [b["silent_side"] for b in out["blindspots"]] == ["north"]
    f = [x for x in out["flags"] if x["code"] == "thin side"]
    assert len(f) == 1 and f[0]["side"] == "south" and f[0]["reader"] == "step 3" and "1 article" in f[0]["detail"]


def test_an_article_step_1_failed_on_does_not_count_as_read():
    s1 = step1()
    s1["articles"][3]["checks"] = {"error": "no usable answer after one retry"}        # a_s2: sent, not read
    out = run(s1=s1)
    src = {x["id"]: x for x in out["sources"]}
    assert src["a_s2"]["read"] is False and src["a_s1"]["read"] is True
    assert out["counts"]["articles_read"] == 5 and out["counts"]["read_B"] == 1
    assert [x["side"] for x in out["flags"] if x["code"] == "thin side"] == ["south"]


def test_an_empty_side_is_flagged_for_step_4_and_the_video():
    out = run(s1=step1(("a_n1", "a_n2", "a_w1", "a_x1", "a_s9")))
    codes = [x["code"] for x in out["flags"]]
    assert "empty side" in codes and "too few articles" in codes
    assert out["blindspots"] == [] or all(b["silent_side"] != "south" for b in out["blindspots"])


WIRE = " ".join(f"wire{i}" for i in range(80))           # 80 words of shared wire text


def test_the_same_sentence_counts_once_only_between_articles_sharing_wire_text():
    arts = [a if a["id"] not in ("a_w1", "a_x1") else dict(a, text=WIRE + " " + " ".join(f"{a['id']}{i}" for i in range(400)))
            for a in ARTS]
    out = run(arts=arts)
    c = {x["id"]: x for x in out["claims"]}
    assert c["C4"]["independent"] == 1 and c["C4"]["independent_groups"] == [["a_w1", "a_x1"]]
    assert c["C1"]["independent"] == 2 and c["C1"]["independent_groups"] == []
    assert out["counts"]["same_sentence_joined"] == 1 and out["counts"]["shared_text_pairs"] == 1
    assert out["counts"]["copy_pairs"] == 0
    out = run()                                          # no shared text: two outlets quoting the same words stay two
    assert {x["id"]: x for x in out["claims"]}["C4"]["independent"] == 2
    assert brief_sides.same_sentence("The bridge closed on Friday after the storm.", "the bridge closed on Friday after the storm")
    assert brief_sides.same_sentence("officials said the bridge closed on Friday after the storm, cracking supports",
                                     "the bridge closed on Friday after the storm")
    assert not brief_sides.same_sentence("closed on Friday", "the bridge closed on Friday after the storm")   # under 6 words


def test_wire_copies_count_once_even_with_different_quotes():
    long = " ".join(f"word{i}" for i in range(60))
    arts = ARTS + [art("a_c1", "copyco", 0.7, text=long), art("a_c2", "copyco2", 0.7, text=long)]
    groups = dict(GROUPS, a_c1="other", a_c2="other")
    step2 = {"claims": [claim("C1", ("a_c1", "one way to say it here"), ("a_c2", "a different way of saying it"))]}
    out = run(step2=step2, arts=arts, groups=groups, s1=step1(("a_n1", "a_n2", "a_s1", "a_s2", "a_c1", "a_c2")))
    assert out["claims"][0]["independent"] == 1 and out["counts"]["copy_pairs"] == 1


def test_unrated_and_low_reliability_claims_are_flagged_for_the_fact_check():
    out = run()
    c = {x["id"]: x for x in out["claims"]}
    assert c["C5"]["flags"] == ["unrated only"] and c["C6"]["flags"] == ["low reliability"]
    assert c["C1"]["flags"] == [] and c["C2"]["flags"] == [] and c["C4"]["flags"] == []
    f = {x["code"]: x for x in out["flags"]}
    assert f["unrated only"]["claims"] == ["C5"] and f["low reliability"]["claims"] == ["C3", "C6"]   # C3: one source at 0.3
    assert f["low reliability"]["reader"] == "the fact check"


def test_story_flags_developing_and_too_few_articles():
    out = run(event={"confidence": "45"}, s1=step1(("a_n1", "a_s1", "a_w1")))
    codes = {x["code"]: x for x in out["flags"]}
    assert "developing" in codes and "45" in codes["developing"]["detail"] and codes["developing"]["reader"] == "the script writer"
    assert codes["too few articles"]["detail"].startswith("3 articles read") and "still made" in codes["too few articles"]["action"]
    assert "developing" not in {x["code"] for x in run()["flags"]}


def test_no_real_divide_has_no_sides_or_blindspots():
    out = run(lens=NO_DIVIDE)
    assert out["sides"]["kind"] == "no real divide" and out["blindspots"] == []
    assert all(c["sides"] == [] and c["blindspot_of"] is None for c in out["claims"])
    assert not any(x["code"] in ("thin side", "empty side") for x in out["flags"])


def test_sources_are_slim_with_side_and_labels_but_no_text():
    out = run()
    s = {x["id"]: x for x in out["sources"]}
    assert s["a_n1"]["side"] == "north" and s["a_w1"]["side"] is None and s["a_w1"]["wire"] is True
    assert s["a_n1"]["headline"] == "Headline a_n1" and s["a_n2"]["rated"] is False and s["a_n1"]["read"] is True
    assert all("text" not in x for x in out["sources"])


def test_the_eval_reads_the_latest_step_2_run_per_story_and_sums_counts(tmp_path):
    runs = tmp_path / "runs"
    (runs / "brief_merge").mkdir(parents=True)
    old = {"run_id": "m-old", "items_detail": [{"story": "s1", "output": {"claims": [claim("C1", ("a_n1", "x"))], "checks": {}}}]}
    new = {"run_id": "m-new", "items_detail": [{"story": "s1", "output": {"claims": [claim("C9", ("a_n1", "y"))], "checks": {}}},
                                               {"story": "s2", "output": {"claims": [], "checks": {"error": "failed"}}}]}
    (runs / "brief_merge" / "brief_merge-20260101T000000-m-merge-x-n10.json").write_text(json.dumps(old))
    (runs / "brief_merge" / "brief_merge-20260102T000000-m-merge-x-n10.json").write_text(json.dumps(new))
    ev = brief_sides_eval.BriefSidesEval(merge=",".join(str(p) for p in sorted((runs / "brief_merge").glob("*.json"))),
                                         merge_version="merge-x", runs_dir=runs)
    s2 = ev.step2()
    assert s2["s1"][1] == "m-new" and s2["s1"][0]["claims"][0]["id"] == "C9" and "s2" not in s2
    assert ev.version == f"{brief_sides.VERSION}-merge-x-n10"
    item = runner.Item(id="story:s1", story="s1", data={})
    out = run()
    sc = ev.score(item, out, {})
    assert sc["two_sides"] and sc["can_blind"] and sc["blindspots"] == 3
    summ = ev.summarize([item], [sc])
    assert summ["blindspots_per_story"] == 3.0 and summ["one_side_share"] == 0.5 and summ["stories_failed"] == 0


def test_outlets_reprinting_the_same_statement_dont_count_as_shared_wire_text():
    statement = "“" + " ".join(f"said{i}" for i in range(80)) + ".”"
    arts = [a if a["id"] not in ("a_w1", "a_x1") else dict(a, text=statement + " " + " ".join(f"{a['id']}{i}" for i in range(100)))
            for a in ARTS]
    step2 = {"claims": [claim("C1", ("a_w1", " ".join(f"said{i}" for i in range(10))), ("a_x1", " ".join(f"said{i}" for i in range(10))))]}
    out = run(step2=step2, arts=arts)
    assert out["claims"][0]["independent"] == 2 and out["counts"]["shared_text_pairs"] == 0
    assert brief_sides.prose_runs('He said "' + " ".join(f"q{i}" for i in range(20)) + '" today.') == set()
