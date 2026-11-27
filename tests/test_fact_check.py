"""Module 6: the fact check. Made-up stories only; the model is a fake."""
import json
import threading
from types import SimpleNamespace

from stringer import brief_read, fact_check

EVENT = {"id": "00000000-test", "title": "Storm shuts river bridge", "start": "2026-01-02T03:00:00Z",
         "summary": "A storm cracked two supports of the river bridge, which closed on Friday. No one was hurt."}

TEXTS = {
    "a_n1": ("The river bridge closed on Friday after the storm cracked two of its main supports. "
             "Engineers expect repairs to take at least three months. The mayor said the city ignored warnings for five years."),
    "a_n2": ("Police said a truck driver was hurt when the bridge closed. Photos suggest that a support may have fallen into the river."),
    "a_s1": ("Officials shut the river bridge on Friday after storm damage was found. Ferries will carry drivers across the river."),
    "a_w1": ("The bridge closed on Friday, the city said. Two of its supports cracked in the storm overnight."),
    "a_l1": ("Ферри перевезут водителей через реку. Мост закрыт."),
}
OUTLETS = {"a_n1": ("n_daily", "North Daily", "north", 0.8), "a_n2": ("n_post", "North Post", "north", 0.3),
           "a_s1": ("s_times", "South Times", "south", 0.9), "a_w1": ("wire", "The Wire", None, 0.95),
           "a_l1": ("s_state", "South State Radio", "south", None)}


def article(aid):
    return {"id": aid, "url": f"https://{OUTLETS[aid][0]}.test/{aid}", "title": f"Headline {aid}", "text": TEXTS[aid]}


ARTICLES = {a: article(a) for a in TEXTS}


class Table:
    def match_domain(self, url):
        host = url.split("/")[2]
        oid = host.split(".")[0]
        return (SimpleNamespace(outlet_id=oid) if oid in {o[0] for o in OUTLETS.values()} else None), host


def source(aid, **kw):
    oid, name, side, rel = OUTLETS[aid]
    s = dict(id=aid, url=f"https://{oid}.test/{aid}", outlet=oid, outlet_name=name, published_at="2026-01-02T06:00:00Z",
             side=side, reliability=rel, state_media="State-Controlled" if oid == "s_state" else None, read=True,
             lang="ru" if aid == "a_l1" else "en")
    s.update(kw)
    return s


def fact(aid, k, quote, quote_en="", who="the outlet"):
    t = brief_read.norm(brief_read.shown_text(ARTICLES[aid])[0])
    pos = t.find(brief_read.norm(quote).strip(" .,;:\"'"))
    assert pos >= 0, quote
    return dict(id=f"{aid}#{k}", article=aid, fact=quote, quote=quote, quote_en=quote_en, kind="event", who_says=who, pos=pos)


FACTS = [
    fact("a_n1", 1, "The river bridge closed on Friday after the storm cracked two of its main supports"),
    fact("a_n1", 2, "Engineers expect repairs to take at least three months"),
    fact("a_n1", 3, "the city ignored warnings for five years", who="the mayor"),
    fact("a_n2", 1, "Police said a truck driver was hurt when the bridge closed"),
    fact("a_n2", 2, "Photos suggest that a support may have fallen into the river"),
    fact("a_s1", 1, "Officials shut the river bridge on Friday after storm damage was found"),
    fact("a_s1", 2, "Ferries will carry drivers across the river"),
    fact("a_w1", 1, "The bridge closed on Friday, the city said"),
    fact("a_l1", 1, "Ферри перевезут водителей через реку", quote_en="Ferries will carry drivers across the river"),
]


def claim(cid, text, *fids, who="the outlet", conflicts=(), blindspot=None, independent=None, sides=None):
    arts = list(dict.fromkeys(f.split("#")[0] for f in fids))
    side_of = {a: OUTLETS.get(a, ("", "", None, None))[2] for a in arts}
    return dict(id=cid, claim=text, kind="event", who_says=who, facts=list(fids), articles=arts,
                conflicts_with=list(conflicts),
                sides=sides if sides is not None else [s for s in ("north", "south") if s in side_of.values()],
                neither=sum(v is None for v in side_of.values()),
                independent=independent if independent is not None else len(arts), independent_groups=[],
                flags=[], blindspot=blindspot, status=None, reason=None)


def story(claims, sources=None):
    return {"version": "sf-1", "event": EVENT,
            "sides": {"kind": "two sides", "A": {"side_id": "north", "label": "North"}, "B": {"side_id": "south", "label": "South"}},
            "sources": sources or [source(a) for a in TEXTS], "claims": claims,
            "blindspots": [{"silent_side": "south", "central": ["C4"], "detail": []}],
            "flags": [{"code": "developing", "detail": "x", "reader": "the script writer", "action": "hedges"}], "meta": {"steps": {}}}


def fake_judge(answers: dict, log=None, fail_first=0, skip=()):
    """A model that answers from `answers` {claim id: partial verdict}, for the claims in its prompt."""
    lock, n = threading.Lock(), [0]

    def complete(messages, name=None, **params):
        with lock:
            n[0] += 1
            k = n[0]
        if log is not None:
            log.append(dict(name=name, messages=messages, params=params))
        if k <= fail_first:
            return SimpleNamespace(text="not json")
        body = messages[-1]["content"]
        ids = params["response_format"]["json_schema"]["schema"]["properties"]["claims"]["items"]["properties"]["id"]["enum"]
        out = []
        for cid in ids:
            if cid in skip and k == 1:
                continue
            a = dict(verdict="backed", problem="none", speaker="", bad_cards=[], bad_translations=[], against_event=False, why="")
            a.update(answers.get(cid, {}))
            out.append(dict(id=cid, **a))
        assert "Event summary:" in body
        return SimpleNamespace(text=json.dumps({"claims": out}))
    return complete


def run(claims, answers=None, sources=None, **kw):
    sf = story(claims, sources)
    return fact_check.check_story(sf, FACTS, ARTICLES, fake_judge(answers or {}, **kw), model="fake", table=Table())


# ---- pass 1 --------------------------------------------------------------------------------------------

def test_paperwork_takes_off_bad_cards():
    bad_quote = dict(FACTS[1], id="a_n1#9", quote="Engineers expect repairs to take at least nine months")
    ghost = dict(FACTS[0], id="a_x#1", article="a_x")
    sources = [source(a) for a in TEXTS]
    sources[2] = source("a_s1", url="https://s-times-news.test/a_s1")            # a look-alike address
    sources[3] = source("a_w1", published_at="2025-12-01T00:00:00Z")             # a month before the event
    sf = story([claim("C1", "x", "a_n1#1", "a_n1#9", "a_x#1"), claim("C2", "y", "a_s1#1", "a_w1#1")], sources)
    pw = fact_check.paperwork(sf, FACTS + [bad_quote, ghost], ARTICLES, Table())
    assert pw["cards_off"]["a_n1#9"].startswith("quote not found")
    assert pw["cards_off"]["a_x#1"] == "article not in the file"
    assert "web address" in pw["cards_off"]["a_s1#1"]
    assert "days before the event" in pw["cards_off"]["a_w1#1"]
    assert "a_n1#1" not in pw["cards_off"] and pw["contexts"]["a_n1#1"]["quote"].startswith("The river bridge")
    assert set(pw["sources_off"]) == {"a_s1", "a_w1"}


def test_numbers_missing_reads_number_words():
    assert fact_check.numbers_missing("Repairs take 3 months and cost 40 million", ["at least three months"]) == ["40"]
    assert fact_check.numbers_missing("1,441 drones", ["downed 1441 drones"]) == []
    assert fact_check.numbers_missing("327-metre span", ["a 227-metre road arch"]) == ["327"]


def test_no_card_and_no_card_left_are_dropped_before_the_judge():
    log = []
    sf = story([claim("C1", "x"), claim("C2", "y", "a_x#1")])
    facts, out = fact_check.check_story(sf, FACTS, ARTICLES, fake_judge({}, log=log), model="fake", table=Table())
    st = {c["id"]: (c["status"], c["reason"]) for c in out["claims"]}
    assert st["C1"] == ("dropped", "no card")
    assert st["C2"][0] == "dropped" and st["C2"][1].startswith("no card left")
    assert log == []                                                             # nothing left to judge


# ---- the judge -----------------------------------------------------------------------------------------

def test_judge_sees_quotes_in_context_with_english_and_number_note():
    log = []
    run([claim("C1", "Repairs will take 4 months.", "a_n1#2"), claim("C2", "Ferries will carry drivers.", "a_l1#1")], log=log)
    body = log[0]["messages"][-1]["content"]
    assert "[[Engineers expect repairs to take at least three months]]" in body
    assert "The river bridge closed on Friday" in body                          # the sentence before
    assert "Note: 4 appears in none of the quotes." in body
    assert 'English of the [[quote]] (ru): "Ferries will carry drivers across the river"' in body
    assert "North Daily" not in body                                             # no outlet names
    p = log[0]["params"]
    assert p["max_tokens"] == fact_check.MAX_TOKENS
    labels = p["response_format"]["json_schema"]["schema"]["properties"]["claims"]["items"]["properties"]["bad_cards"]["items"]["enum"]
    assert labels == ["K1", "K2"]


def test_unusable_answer_is_asked_again_and_left_out_claims_once_more():
    log = []
    _, out = run([claim("C1", "a", "a_n1#1"), claim("C2", "b", "a_s1#1")], log=log, fail_first=1)
    assert [c["status"] for c in out["claims"]] == ["say with source", "say with source"]
    assert log[1]["messages"][-1]["content"] == brief_read.RETRY_JSON
    log2 = []
    _, out = run([claim("C1", "a", "a_n1#1"), claim("C2", "b", "a_s1#1")], log=log2, skip={"C2"})
    assert len(log2) == 2 and "C2 ·" in log2[1]["messages"][-1]["content"] and "C1 ·" not in log2[1]["messages"][-1]["content"]
    assert all(c["status"] != "unchecked" for c in out["claims"])


def test_claims_with_no_usable_answer_are_unchecked_and_flagged():
    _, out = run([claim("C1", "a", "a_n1#1")], fail_first=99)
    c = out["claims"][0]
    assert c["status"] == "unchecked" and c["reason"] == "no usable judge answer"
    assert any(f["code"] == "unchecked" for f in out["flags"])


def test_groups_are_fixed_by_position():
    log = []
    claims = [claim(f"C{i}", f"claim {i}", "a_n1#1") for i in range(1, 46)]
    run(claims, log=log)
    sizes = sorted(len(x["params"]["response_format"]["json_schema"]["schema"]["properties"]["claims"]["items"]["properties"]["id"]["enum"]) for x in log)
    assert sizes == [5, 20, 20]


# ---- pass 3: the rules -----------------------------------------------------------------------------------

def test_confirmed_needs_two_outlets_or_a_named_speaker():
    _, out = run([claim("C1", "The bridge closed on Friday.", "a_n1#1", "a_s1#1"),
                  claim("C2", "The mayor said the city ignored warnings for five years.", "a_n1#3", who="the mayor")])
    assert [(c["status"], c["attribute_to"]) for c in out["claims"]] == [("confirmed", None), ("confirmed", None)]


def test_rule_a_names_the_speaker_the_judge_found():
    _, out = run([claim("C1", "A truck driver was hurt.", "a_n2#1", "a_s1#1")],
                 {"C1": dict(verdict="needs a name", speaker="Police")})
    c = out["claims"][0]
    assert c["status"] == "say with source" and c["attribute_to"] == "Police" and c["check"]["rules"] == ["a"]


def test_rule_a_never_names_the_outlet_as_a_speaker():
    _, out = run([claim("C1", "Repairs will take at least three months.", "a_n1#2", "a_s1#1")],
                 {"C1": dict(verdict="needs a name", speaker="the outlet (unnamed in the quote)")})
    c = out["claims"][0]
    assert c["status"] == "say with source" and c["attribute_to"] == "North Daily and South Times"
    assert c["check"]["speaker"] == ""


def test_the_judge_gives_its_reason_first():
    props = fact_check.schema(["C1"], ["K1"])["json_schema"]["schema"]["properties"]["claims"]["items"]
    assert props["required"][:3] == ["id", "why", "verdict"] and list(props["properties"])[:3] == ["id", "why", "verdict"]


def test_check_5_cards_back_together_one_is_enough_when_they_disagree_and_reported_speech_is_fine():
    # check-4, from Haiku's check-3 wrong drops: a claim one card backs was dropped because another card
    # differed, and "we found out" reported as "they found out" counted as a change of speaker.
    # check-5, from the Kerch smoke: 3.8 Flash read "one card is enough" as "one card must say it all".
    s = fact_check.SYSTEM
    assert "Cards may back a claim together" in s and "When cards disagree, one is enough" in s
    assert "put the card that differs in bad_cards" in s and "the cards that back it" in s
    assert '"we" may become "he", "she" or "they"' in s
    assert fact_check.VERSION == "check-5"


def test_a_card_shows_who_the_reader_says_is_speaking_but_not_the_outlet():
    # Kerch C91: Zelenskyy is named a paragraph up, past a photo caption, out of the quote's window.
    f1 = dict(id="a_1#1", article="a_1", quote="Russia strikes our bridges", who_says="Zelenskyy")
    f2 = dict(id="a_2#1", article="a_2", quote="The bridge was hit", who_says="the outlet")
    ctx = dict(quote="", sentence="", before="", after="")
    items = [{"claim": dict(id="C1", claim="Zelenskyy said Russia strikes bridges.", who_says="Zelenskyy"),
              "cards": [(f1, dict(ctx, quote=f1["quote"], sentence=f1["quote"] + "."), "en"),
                        (f2, dict(ctx, quote=f2["quote"], sentence=f2["quote"] + "."), "en")]}]
    msgs, labels = fact_check.messages_for({"title": "t", "summary": "s"}, items)
    text = json.dumps(msgs)
    assert "K1 (said by: Zelenskyy): " in text and "K2: " in text and "said by: the outlet" not in text


def test_rule_b_low_and_unrated_sources_name_the_outlet():
    _, out = run([claim("C1", "A truck driver was hurt.", "a_n2#1"), claim("C2", "Ferries will run.", "a_l1#1")])
    a, b = out["claims"]
    assert a["status"] == "say with source" and a["attribute_to"] == "North Post" and "b" in a["check"]["rules"]
    assert b["attribute_to"] == "South State Radio (state-controlled media)" and "every source is unrated" in b["reason"]


def test_rule_c_one_outlet_in_its_own_voice():
    _, out = run([claim("C1", "Repairs will take at least three months.", "a_n1#2")])
    c = out["claims"][0]
    assert (c["status"], c["attribute_to"], c["check"]["rules"]) == ("say with source", "North Daily", ["c"])


def test_rule_d_conflicts_and_the_event_but_not_with_dropped_claims():
    claims = [claim("C1", "The bridge closed on Friday.", "a_n1#1", "a_s1#1", conflicts=["C2"]),
              claim("C2", "The bridge closed on Thursday.", "a_w1#1", "a_s1#1", conflicts=["C1"]),
              claim("C3", "A driver was hurt.", "a_n2#1", "a_s1#1", who="Police"),
              claim("C4", "The bridge closed.", "a_w1#1", "a_n1#1", conflicts=["C5"]),
              claim("C5", "The bridge stayed open.", "a_s1#1", "a_n1#1", conflicts=["C4"])]
    _, out = run(claims, {"C3": dict(against_event=True), "C5": dict(verdict="not backed", problem="not in the quotes")})
    st = {c["id"]: c for c in out["claims"]}
    assert st["C1"]["status"] == "say with source" and "conflicts with C2" in st["C1"]["reason"]
    assert st["C3"]["status"] == "say with source" and st["C3"]["attribute_to"] == "Police"
    assert st["C4"]["status"] == "confirmed"                                    # its conflict partner was dropped
    assert st["C5"]["status"] == "dropped" and st["C5"]["reason"].startswith("not backed: not in the quotes")
    assert next(f for f in out["flags"] if f["code"] == "against the event")["claims"] == ["C3"]


def test_bad_cards_come_off_and_sources_and_sides_are_counted_again():
    claims = [claim("C1", "Two supports cracked in the storm.", "a_n1#1", "a_s1#1", "a_w1#1")]
    _, out = run(claims, {"C1": dict(bad_cards=["K2", "K3"])})
    c = out["claims"][0]
    assert c["facts"] == ["a_n1#1"] and c["articles"] == ["a_n1"] and c["sides"] == ["north"] and c["independent"] == 1
    assert c["check"]["before"]["independent"] == 3 and set(c["check"]["cards_off"]) == {"a_s1#1", "a_w1#1"}
    assert c["status"] == "say with source" and c["attribute_to"] == "North Daily"   # now one outlet


def test_blindspot_marks_go_when_the_claim_changes_or_drops():
    bs = {"silent_side": "south", "status": "blindspot"}
    claims = [claim("C4", "Photos suggest a support fell.", "a_n2#2", "a_n1#1", blindspot=bs),
              claim("C6", "The bridge closed.", "a_n1#1", "a_s1#1", blindspot=dict(bs), sides=["north"])]
    _, out = run(claims, {"C4": dict(verdict="not backed", problem="more certain than the quotes")})
    c4, c6 = out["claims"]
    assert c4["blindspot"] is None and out["blindspots"][0]["central"] == []
    assert c6["sides"] == ["north", "south"] and c6["blindspot"] is None        # a wrong side mark is fixed


def test_translations_marked_and_many_drops_flagged():
    claims = [claim("C1", "Ferries will run.", "a_l1#1", "a_s1#2"), claim("C2", "x", "a_n1#1"), claim("C3", "y", "a_n1#2")]
    facts, out = run(claims, {"C1": dict(bad_translations=["K1"]), "C2": dict(verdict="not backed", problem="other")})
    assert next(f for f in facts if f["id"] == "a_l1#1")["translation_ok"] is False
    assert any(f["code"] == "many drops" for f in out["flags"]) and any(f["code"] == "developing" for f in out["flags"])
    n = out["fact_check"]["counts"]
    assert (n["dropped"], n["bad_translations"], n["claims"]) == (1, 1, 3)
    assert out["meta"]["steps"]["fact_check"]["version"] == fact_check.VERSION


def test_code_only_run_leaves_claims_unchecked_without_flag():
    sf = story([claim("C1", "a", "a_n1#1")])
    _, out = fact_check.check_story(sf, FACTS, ARTICLES, None, table=Table())
    assert out["claims"][0]["status"] == "unchecked" and out["claims"][0]["reason"] == "not judged"
    assert not any(f["code"] == "unchecked" for f in out["flags"]) and out["fact_check"]["model"] == "code"


def test_input_story_file_is_not_changed():
    sf = story([claim("C1", "a", "a_n1#1", "a_s1#1")])
    before = json.dumps(sf, sort_keys=True)
    fact_check.check_story(sf, FACTS, ARTICLES, fake_judge({"C1": dict(bad_cards=["K2"])}), model="fake", table=Table())
    assert json.dumps(sf, sort_keys=True) == before


def test_state_run_outlets_are_named_as_such_at_every_state_level():
    src = {"a": dict(outlet_name="Xin Wire", state_media="Captured Public"),
           "b": dict(outlet_name="Tas Agency", state_media="Captured Private"),
           "c": dict(outlet_name="Public Radio", state_media="Independent Public"),
           "d": dict(outlet_name="Daily", state_media=None)}
    assert fact_check._outlets(["a"], src) == "Xin Wire (state-controlled media)"
    assert fact_check._outlets(["b", "c"], src) == "Tas Agency (state-controlled media) and Public Radio"
    assert fact_check._outlets(["d"], src) == "Daily"


def test_a_judge_run_early_gives_the_same_checked_file_and_no_second_model_call():
    sf = story([claim("C1", "A truck driver was hurt.", "a_n2#1"), claim("C2", "Ferries will run.", "a_l1#1")])
    log = []
    answers = {"C1": dict(verdict="not backed", problem="number", why="no")}
    _, plain = fact_check.check_story(sf, FACTS, ARTICLES, fake_judge(answers), model="fake", table=Table())
    early = fact_check.judge_early(sf, FACTS, ARTICLES, fake_judge(answers, log=log), model="fake", table=Table())
    n = len(log)
    _, late = fact_check.check_story(sf, FACTS, ARTICLES, fake_judge(answers, log=log), model="fake", table=Table(),
                                     judged=early)
    assert len(log) == n and n >= 1                                    # check_story made no call of its own
    assert [(c["id"], c["status"], c["reason"]) for c in late["claims"]] == \
           [(c["id"], c["status"], c["reason"]) for c in plain["claims"]]
    assert late["fact_check"]["model"] == "fake" and late["fact_check"]["calls"] == plain["fact_check"]["calls"]
