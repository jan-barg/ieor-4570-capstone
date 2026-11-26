"""Module 5: the Story File put together from the steps. Made-up stories only; models are fakes."""
import json
from types import SimpleNamespace

import pytest

from stringer import brief_blind, brief_framing, brief_merge, brief_read, brief_sides, story_brief, story_file

LENS = {"kind": "world", "sides": [
    {"side_id": "north", "label": "Northland outlets", "outlet_ids": ["n_daily", "n_post"]},
    {"side_id": "south", "label": "Southland outlets", "outlet_ids": ["s_times", "s_news"]}]}
EVENT = {"id": "00000000-test", "title": "Bridge closes after storm", "summary": "A storm shut the river bridge.",
         "confidence": "70", "category": "disaster", "start": "2026-01-02T03:04:00Z", "secret_field": "not copied"}
META = {"event": EVENT, "lens": LENS, "attribution": "Events by a made-up feed.", "gathered_at": "2026-01-02T05:00:00Z"}

N1 = ("The river bridge closed on Friday after the overnight storm cracked two of its main supports, officials said. "
      "Engineers expect the repairs to take at least three months before traffic can return. "
      "Southern sabotage is suspected by the defence minister.")
N2 = ("Two supports of the river bridge cracked in the storm and the crossing was closed on Friday morning by the city. "
      "The mayor said the city had ignored warnings about the supports for five years before the storm.")
S1 = ("Officials shut the river bridge on Friday after storm damage was found during an inspection of the structure. "
      "Two of the bridge's supports cracked during the storm, engineers said at a news conference on Friday.")
S2 = ("Ferries will carry drivers across the river while the damaged bridge stays closed for repairs, the operator said. "
      "Engineers blamed years of neglect by the northern government for the failure.")


def art(aid, outlet, text):
    return {"id": aid, "outlet": outlet, "url": f"https://example.test/{aid}", "published_at": "2026-01-02T03:04:00Z",
            "title": f"Headline {aid} - Outlet", "text": text, "text_status": "full",
            "labels": {"outlet_id": outlet, "outlet_name": outlet.replace("_", " ").title(), "reliability": 0.8,
                       "is_wire": False, "us_lean": None, "state_media": None}}


ARTS = [art("a_n1", "n_daily", N1), art("a_n2", "n_post", N2), art("a_s1", "s_times", S1), art("a_s2", "s_news", S2)]
GROUPS = {"a_n1": "A", "a_n2": "A", "a_s1": "B", "a_s2": "B"}


def fact(aid, k, text, quote, kind="event"):
    t = brief_read.norm(brief_read.shown_text(next(a for a in ARTS if a["id"] == aid))[0])
    return dict(id=f"{aid}#{k}", fact=text, quote=quote, quote_en="", kind=kind, who_says="the outlet",
                pos=brief_read.find_quote(quote, t))


STEP1 = {"version": "read-2", "articles": [
    {"article": "a_n1", "lang": "en", "checks": {"error": None}, "facts": [
        fact("a_n1", 1, "The bridge closed on Friday.", "The river bridge closed on Friday"),
        fact("a_n1", 2, "Repairs will take at least three months.", "repairs to take at least three months")]},
    {"article": "a_n2", "lang": "en", "checks": {"error": None}, "facts": [
        fact("a_n2", 1, "The city ignored warnings for five years.", "ignored warnings about the supports for five years")]},
    {"article": "a_s1", "lang": "en", "checks": {"error": None}, "facts": [
        fact("a_s1", 1, "The bridge was shut on Friday.", "Officials shut the river bridge on Friday")]},
    {"article": "a_s2", "lang": "en", "checks": {"error": None}, "facts": [
        fact("a_s2", 1, "Ferries will carry drivers.", "Ferries will carry drivers across the river")]}]}


def claim(cid, text, *fids, conflicts=()):
    arts = sorted({f.split("#")[0] for f in fids})
    return {"id": cid, "claim": text, "kind": "event", "who_says": "the outlet", "conflicts_with": list(conflicts),
            "facts": list(fids), "articles": arts,
            "sources": [{"fact": f, "article": f.split("#")[0], "quote": "q"} for f in fids]}


STEP2 = {"version": "merge-11", "checks": {"error": None},
         "claims": [claim("C1", "The bridge closed on Friday.", "a_n1#1", "a_s1#1"),
                    claim("C2", "Repairs will take at least three months.", "a_n1#2"),
                    claim("C3", "The city ignored warnings for five years.", "a_n2#1"),
                    claim("C4", "Ferries will carry drivers.", "a_s2#1")],
         "updates": [{"a": "C1", "b": "C2", "why": "made up"}]}
SIDES = brief_sides.add_sides(STEP2, STEP1, ARTS, GROUPS, LENS, EVENT)


def judged():
    """Step 3 plus a judge answer for the south side (C2 is the only 1-source candidate)."""
    out = dict(SIDES)
    out["blindspots"] = [dict(b, sources=dict(b["sources"], C3=2)) if b["silent_side"] == "south" else b
                         for b in SIDES["blindspots"]]
    out["blindspot_checks"] = [dict(silent_side="south", label="Southland outlets", reported_by="north", cut=0, error=None,
                                    checked=[dict(claim="C3", status="blindspot", matters="central", why="not there"),
                                             ])]
    out["blind_counts"] = dict(version="blind-4", checked=1)
    return out


FRAMING = {"version": "frame-2", "kind": "two sides", "skipped": [], "error": None, "sides": [
    dict(side_id="north", label="Northland outlets", articles=2, points=[
        dict(kind="blame or credit", point="North blames southern sabotage.", outlets=1, articles=["a_n1"],
             quotes=[dict(article="a_n1", outlet="N Daily", words="Southern sabotage", words_en="")])]),
    dict(side_id="south", label="Southland outlets", articles=2, points=[
        dict(kind="blame or credit", point="South blames northern neglect.", outlets=1, articles=["a_s2"],
             quotes=[dict(article="a_s2", outlet="S News", words="years of neglect", words_en="")])])]}


def build():
    return story_file.assemble(META, STEP1, STEP2, judged(), FRAMING, steps={"brief_read": {"version": "read-2"}},
                               cost_usd={"brief_read": None, "brief_merge": None, "brief_blind": 0.001,
                                         "brief_framing": 0.02}, now="2026-01-02T06:00:00+00:00")


def test_the_story_file_holds_together_and_claims_point_to_fact_ids():
    facts, sf = build()
    assert story_file.validate(sf, facts) == []
    assert [f["id"] for f in facts] == ["a_n1#1", "a_n1#2", "a_n2#1", "a_s1#1", "a_s2#1"]
    c1 = sf["claims"][0]
    assert c1["facts"] == ["a_n1#1", "a_s1#1"] and c1["sides"] == ["north", "south"] and "sources" not in c1
    assert c1["status"] is None and c1["reason"] is None                 # the fact check fills these
    assert "secret_field" not in sf["event"] and sf["event"]["title"] == EVENT["title"]
    assert sf["updates"] == STEP2["updates"] and sf["counts"]["facts"] == 5 and sf["counts"]["updates"] == 1
    assert sf["meta"]["cost_usd"]["total"] is None                      # steps 1 and 2 have no production cost here
    assert all("text" not in s for s in sf["sources"])                   # article text stays in articles.jsonl


def test_every_blindspot_candidate_gets_a_status_and_only_confirmed_ones_are_listed():
    facts, sf = build()
    by = {c["id"]: c for c in sf["claims"]}
    assert by["C3"]["blindspot"]["status"] == "blindspot" and by["C3"]["blindspot"]["matters"] == "central"
    assert by["C2"]["blindspot"]["status"] == "not checked" and "one independent source" in by["C2"]["blindspot"]["why"]
    assert by["C4"]["blindspot"]["silent_side"] == "north" and by["C1"]["blindspot"] is None
    south = next(b for b in sf["blindspots"] if b["silent_side"] == "south")
    assert south["central"] == ["C3"] and south["detail"] == [] and south["candidates"] == 2 and south["checked"] == 1
    assert sf["counts"]["blindspots_central"] == 1


def test_validate_names_broken_ids():
    facts, sf = build()
    sf["claims"][0]["facts"].append("a_n9#1")
    sf["claims"][1]["conflicts_with"] = ["C99"]
    sf["perspectives"][0]["points"][0]["quotes"][0]["article"] = "a_s1"          # the other side's article
    sf["blindspots"][0]["detail"].append("C1")
    bad = story_file.validate(sf, facts)
    assert any("fact a_n9#1 missing" in b for b in bad) and any("C99" in b for b in bad)
    assert any("not on this side" in b for b in bad) and any("blindspot C1" in b for b in bad)


def test_a_quote_reads_back_from_its_position_with_a_sentence_each_side():
    f = STEP1["articles"][0]["facts"][1]
    got = story_file.quote_at(ARTS[0], f)
    assert got["quote"] == "repairs to take at least three months"
    assert got["sentence"].startswith("Engineers expect the repairs") and got["before"].startswith("The river bridge closed")
    assert got["after"].startswith("Southern sabotage")
    assert story_file.quote_at(ARTS[0], dict(f, pos=f["pos"] + 3)) is None     # a wrong position is caught
    a = dict(ARTS[0], text='He said "the span fell." ### "It was completely destroyed," the SBU said. Traffic stopped.')
    w = "It was completely destroyed"
    q = dict(f, quote=w, pos=brief_read.find_quote(w, brief_read.norm(brief_read.shown_text(a)[0])))
    got = story_file.quote_at(a, q)
    assert got["sentence"] == '"It was completely destroyed," the SBU said.' and got["before"] == 'He said "the span fell."'


def test_no_real_divide_keeps_no_sides_or_perspectives():
    sides = brief_sides.add_sides(STEP2, STEP1, ARTS, {a: "other" for a in GROUPS}, {"kind": "none", "reason": "one country"}, EVENT)
    framing = {"kind": "no real divide", "sides": [], "skipped": [{"reason": "no real divide"}]}
    facts, sf = story_file.assemble(dict(META, lens={"kind": "none"}), STEP1, STEP2, sides, framing)
    assert sf["sides"]["kind"] == "no real divide" and sf["perspectives"] == [] and sf["blindspots"] == []
    assert sf["perspectives_skipped"] == [{"reason": "no real divide"}] and story_file.validate(sf, facts) == []


def test_files_round_trip(tmp_path):
    facts, sf = build()
    story_file.write(tmp_path, facts, sf)
    f2, sf2 = story_file.read(tmp_path)
    assert f2 == facts and sf2 == sf and len((tmp_path / "facts.jsonl").read_text().splitlines()) == 5


def test_the_brief_page_escapes_text_and_shows_each_part():
    facts, sf = build()
    sf["claims"][0]["claim"] = "<script>alert(1)</script>"
    page = story_brief.page([(facts, sf, [])], "Briefs", "intro")
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    assert "How each side tells it" in page and "Missing from Southland outlets" in page and "years of neglect" in page


def test_build_story_runs_every_step_in_order_and_adds_up_the_cost(monkeypatch):
    seen = []

    def step(name, result):
        def fn(*a, **k):
            seen.append((name, k.get("model")))
            complete = a[2] if name in ("read", "merge") else a[3] if name == "blind" else a[4]
            complete([{"role": "user", "content": "x"}], name=name)
            return result
        return fn
    monkeypatch.setattr(brief_read, "read_story", step("read", STEP1))
    monkeypatch.setattr(brief_merge, "merge_story", step("merge", STEP2))
    monkeypatch.setattr(brief_blind, "judge_blindspots", step("blind", judged()))
    monkeypatch.setattr(brief_framing, "frame_story", step("frame", dict(SIDES, framing=FRAMING)))
    monkeypatch.setattr(story_file, "picked", lambda meta, arts, n: (ARTS, GROUPS))
    fake = lambda step: (f"model-{step}", lambda m, name=None, **p: SimpleNamespace(text="", cost={"total": 0.01}))
    facts, sf = story_file.build_story(META, ARTS, fake)
    assert [s for s, _ in seen] == ["read", "merge", "blind", "frame"] and seen[0][1] == "model-brief_read"
    assert sf["meta"]["cost_usd"]["total"] == 0.04 and sf["meta"]["steps"]["brief_sides"]["model"] == "code"
    assert story_file.validate(sf, facts) == []


def test_the_spend_cap_stops_the_next_call():
    s = story_file.Spend(cap_usd=0.015)
    call = s.wrap("x", lambda m, name=None, **p: SimpleNamespace(cost={"total": 0.01}))
    call([]), call([])
    with pytest.raises(RuntimeError):
        call([])


def test_according_to_the_article_gets_the_outlets_name():
    claims = [dict(id="C1", claim="Ferries will run, according to the article.", articles=["a_s2"]),
              dict(id="C2", claim="The bridge reopened, according to the article's headline.", articles=["a_n1", "a_s1"]),
              dict(id="C3", claim="The bridge closed on Friday.", articles=["a_n1"]),
              dict(id="C4", claim="Tolls rose, according to the article.", articles=["a_x9"])]       # unknown source: left alone
    sources = [dict(id="a_n1", outlet_name="N Daily"), dict(id="a_s1", outlet_name="S Times"), dict(id="a_s2", outlet_name="S News")]
    assert story_file.name_outlets(claims, sources) == 2
    assert claims[0]["claim"] == "Ferries will run, according to S News." and claims[0]["claim_step2"].endswith("the article.")
    assert claims[1]["claim"] == "The bridge reopened, according to N Daily and S Times's headline."
    assert "claim_step2" not in claims[2] and claims[3]["claim"] == "Tolls rose, according to the article."
    _, sf = build()
    assert sf["counts"]["outlet_named"] == 0
