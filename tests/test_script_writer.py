"""Module 7: the script writer. A made-up story (a flooded river bridge in a made-up country) and a fake
model that answers as the writer, the line check and the wording check. No keys, no real stories."""
import copy
import json
import re
from types import SimpleNamespace

import pytest

from stringer import brief_read, script_writer as sw, shots

EVENT = {"id": "00000000-test", "title": "Floodwater closes the Varsel river bridge", "start": "2026-01-02T03:00:00Z",
         "summary": "Floodwater closed the Varsel river bridge in Lorne on Tuesday and halted rail traffic.",
         "location_name": "Varsel river, Lorne", "country": "Lorne", "url": "https://mts.test/e/00000000"}

TEXTS = {
    "a_g1": ("Floodwater closed the Varsel river bridge on Tuesday. The Lorne Interior Ministry says 340 homes were flooded. "
             "Interior Minister Ana Petrel said: \"The bridge will reopen within a week, and repairs are under way.\" "
             "Rail traffic across the Varsel river was halted."),
    "a_o1": ("Floodwater closed the Varsel river bridge on Tuesday. The regional governor's office says about 1,200 homes were "
             "flooded. Trains restarted on one track on Wednesday. Two people died in the flooding, police said."),
    "a_w1": ("The Varsel river bridge was closed by floodwater on Tuesday. Rail traffic across the river was halted. "
             "Trains were running on one track by Wednesday. No one was killed in the flooding, the Lorne Red Cross said."),
    "a_r1": "Die Brücke bleibt geschlossen, sagte der Sprecher: \"Wir arbeiten Tag und Nacht an der Reparatur der Brücke.\"",
}
OUTLETS = {"a_g1": ("Lorne State News", "lorne_gov", "A", 0.6, "en"), "a_o1": ("Tormac Daily", "lorne_opp", "B", 0.8, "en"),
           "a_w1": ("Lorne Wire", None, "wire", 0.9, "en"), "a_r1": ("Nordblatt", "lorne_opp", "B", None, "de")}


def source(aid):
    name, side, group, rel, lang = OUTLETS[aid]
    return dict(id=aid, url=f"https://{aid}.test/x", outlet=aid, outlet_name=name, side=side, group=group, lean=None,
                reliability=rel, state_media=None, read=True, lang=lang)


def article(aid):
    return {"id": aid, "url": f"https://{aid}.test/x", "title": f"Headline {aid}", "text": TEXTS[aid]}


ARTICLES = {a: article(a) for a in TEXTS}


def fact(aid, k, quote, quote_en="", who="the outlet", kind="event"):
    t = brief_read.norm(brief_read.shown_text(ARTICLES[aid])[0])
    pos = t.find(brief_read.norm(quote).strip(" .,;:\"'"))
    assert pos >= 0, quote
    return dict(id=f"{aid}#{k}", article=aid, fact=quote, quote=quote, quote_en=quote_en, kind=kind, who_says=who, pos=pos)


FACTS = [
    fact("a_g1", 1, "Floodwater closed the Varsel river bridge on Tuesday"),
    fact("a_g1", 2, "The Lorne Interior Ministry says 340 homes were flooded", who="the Lorne Interior Ministry"),
    fact("a_g1", 3, "Interior Minister Ana Petrel said: \"The bridge will reopen within a week, and repairs are under way.\"",
         who="Interior Minister Ana Petrel", kind="statement"),
    fact("a_g1", 4, "Rail traffic across the Varsel river was halted"),
    fact("a_o1", 1, "Floodwater closed the Varsel river bridge on Tuesday"),
    fact("a_o1", 2, "The regional governor's office says about 1,200 homes were flooded", who="the regional governor's office"),
    fact("a_o1", 3, "Trains restarted on one track on Wednesday"),
    fact("a_o1", 4, "Two people died in the flooding, police said", who="police"),
    fact("a_w1", 1, "The Varsel river bridge was closed by floodwater on Tuesday"),
    fact("a_w1", 2, "Rail traffic across the river was halted"),
    fact("a_w1", 3, "Trains were running on one track by Wednesday"),
    fact("a_w1", 4, "No one was killed in the flooding, the Lorne Red Cross said", who="the Lorne Red Cross"),
    fact("a_r1", 1, "sagte der Sprecher: \"Wir arbeiten Tag und Nacht an der Reparatur der Brücke.\"",
         quote_en="the spokesman said: \"We are working day and night on repairing the bridge.\"", who="a spokesman",
         kind="statement"),
]


def claim(cid, text, *fids, status="confirmed", attribute_to=None, rules=(), kind="event", conflicts=(), blindspot=None,
          who="the outlet", sides=None):
    arts = list(dict.fromkeys(f.split("#")[0] for f in fids))
    side_of = {a: OUTLETS[a][1] for a in arts}
    return dict(id=cid, claim=text, kind=kind, who_says=who, facts=list(fids), articles=arts, conflicts_with=list(conflicts),
                sides=sides if sides is not None else [s for s in ("lorne_gov", "lorne_opp") if s in side_of.values()],
                neither=sum(v is None for v in side_of.values()), independent=len(arts), independent_groups=[], flags=[],
                blindspot=blindspot, status=status, reason="", check={"rules": list(rules), "against_event": False},
                attribute_to=attribute_to)


def claims():
    return [
        claim("C1", "Floodwater closed the Varsel river bridge on Tuesday.", "a_g1#1", "a_o1#1", "a_w1#1"),
        claim("C2", "The Lorne Interior Ministry says 340 homes were flooded.", "a_g1#2", status="say with source",
              attribute_to="the Lorne Interior Ministry", rules=["a", "d"], kind="number", conflicts=["C3"]),
        claim("C3", "The regional governor's office says about 1,200 homes were flooded.", "a_o1#2", status="say with source",
              attribute_to="the regional governor's office", rules=["a", "d"], kind="number", conflicts=["C2"],
              blindspot={"silent_side": "lorne_gov", "status": "checked"}),
        claim("C4", "Rail traffic across the Varsel river was halted.", "a_g1#4", "a_w1#2"),
        claim("C5", "Trains restarted on one track on Wednesday.", "a_o1#3", status="say with source",
              attribute_to="Tormac Daily", rules=["c"]),
        claim("C6", "Trains were running on one track by Wednesday.", "a_w1#3", status="say with source",
              attribute_to="Lorne Wire", rules=["c"]),
        claim("C7", "Interior Minister Ana Petrel said the bridge would reopen within a week.", "a_g1#3",
              status="say with source", attribute_to="Interior Minister Ana Petrel", rules=["a"], kind="statement",
              who="Interior Minister Ana Petrel"),
        claim("C8", "Two people died in the flooding, police said.", "a_o1#4", who="police"),
        claim("C9", "No one was killed in the flooding, the Lorne Red Cross said.", "a_w1#4", status="say with source",
              attribute_to="the Lorne Red Cross", rules=["a"], who="the Lorne Red Cross"),
        claim("C10", "The bridge collapsed into the river.", "a_w1#1", status="dropped"),
        claim("C11", "A second bridge closed.", "a_w1#1", status="unchecked"),
        claim("C12", "A spokesman said crews are repairing the bridge.", "a_r1#1", kind="statement", who="a spokesman"),
    ]


LABELS = {"A": "Pro-government (Lorne state outlets)", "B": "Opposition (independent Lorne outlets)"}


def story(variant: str = "two sides") -> dict:
    sf = {"version": "sf-1", "event": EVENT, "attribution": "Events by Monitor the Situation (monitor-the-situation.com)",
          "sides": {"kind": "two sides", "A": {"side_id": "lorne_gov", "label": LABELS["A"], "articles": 1},
                    "B": {"side_id": "lorne_opp", "label": LABELS["B"], "articles": 2}},
          "sources": [source(a) for a in TEXTS], "claims": claims(),
          "updates": [{"a": "C4", "b": "C5", "why": "rail traffic: halted, then one track"}],
          "perspectives": [
              {"side_id": "lorne_gov", "label": LABELS["A"], "articles": ["a_g1"], "points": [
                  {"kind": "emphasis", "point": "Government outlets lead with the repair plan and the minister's promise.",
                   "outlets": 1, "articles": ["a_g1"],
                   "quotes": [{"article": "a_g1", "outlet": "Lorne State News", "words": "The bridge will reopen within a week",
                               "words_en": ""}]}]},
              {"side_id": "lorne_opp", "label": LABELS["B"], "articles": ["a_o1", "a_r1"], "points": [
                  {"kind": "emphasis", "point": "Opposition outlets lead with the flooded homes and the deaths.",
                   "outlets": 1, "articles": ["a_o1"],
                   "quotes": [{"article": "a_o1", "outlet": "Tormac Daily", "words": "about 1,200 homes were flooded",
                               "words_en": ""}]}]}],
          "perspectives_skipped": [],
          "blindspots": [{"silent_side": "lorne_gov", "label": LABELS["A"], "central": ["C3"], "detail": []}],
          "flags": [{"code": "developing", "detail": "event confidence 40", "reader": "the script writer",
                     "action": "hedges: details may still change"}],
          "counts": {"claims": 12, "articles_read": 4, "read_A": 1, "read_B": 2},
          "fact_check": {"version": "check-5", "bad_translation_facts": ["a_r1#1"]}}
    if variant == "no divide":
        sf["sides"] = {"kind": "no real divide", "reason": "outlets agree"}
        sf["perspectives"], sf["perspectives_skipped"] = [], [{"reason": "no real divide"}]
        sf["blindspots"], sf["counts"] = [], {"claims": 12, "articles_read": 4}
        for s in sf["sources"]:
            s["side"], s["group"] = None, "local" if s["id"] != "a_w1" else "wire"
        for c in sf["claims"]:
            c["sides"], c["blindspot"] = [], None
        sf["flags"] = []
    if variant == "empty side":
        sf["perspectives"] = sf["perspectives"][:1]
        sf["perspectives_skipped"] = [{"side": "lorne_opp", "label": LABELS["B"], "reason": "empty side"}]
        for s in sf["sources"]:
            if s["side"] == "lorne_opp":
                s["side"], s["group"] = None, "other"
        sf["counts"] = {"claims": 12, "articles_read": 4, "read_A": 1, "read_B": 0}
        sf["blindspots"] = []
        sf["flags"].append({"code": "empty side", "detail": "no article read", "reader": "step 4 and the video",
                            "action": "the video says the side had no coverage"})
    return sf


def pk(variant="two sides", **kw):
    return sw.packet(story(variant), FACTS, sw.contexts_for(FACTS, ARTICLES), **kw)


# ---- a good script for the made-up story -------------------------------------------------------------

def good_beats():
    return [
        dict(shot="hook", say="Floodwater has closed the Varsel river bridge in Lorne.", claims=["C1"],
             title="Floodwater closes Varsel river bridge", broll_kind="prop", broll="bridge"),
        dict(shot="map_locate", say="The bridge was shut by floodwater on Tuesday, [place on the Varsel river.]",
             claims=["C1"], places=["Varsel river"], place_kind="point"),
        dict(shot="claim_vs_claim", say="How many homes flooded? [left The Lorne Interior Ministry says 340.] "
                                        "[right The regional governor's office says about 1,200.]", claims=["C2", "C3"],
             accounts=[{"who": "Interior Ministry", "says": "340 homes flooded", "claim": "C2"},
                       {"who": "Governor's office", "says": "About 1,200 homes flooded", "claim": "C3"}]),
        dict(shot="timeline", say="[step Rail traffic across the Varsel river was halted,] then [step trains restarted on "
                                  "one track on Wednesday.]", claims=["C4", "C5", "C6"],
             steps=[{"when": "", "what": "Rail traffic halted"}, {"when": "Wednesday", "what": "Trains back on one track"}],
             broll_kind="prop", broll="train"),
        dict(shot="quote", say="Interior Minister Ana Petrel said [quote the bridge will reopen within a week, and repairs "
                               "are under way.]", claims=["C7"], card="Q1", speaker="Ana Petrel", role="Interior Minister",
             broll_kind="portrait", broll="Ana Petrel"),
        dict(shot="headline", say="The Lorne Interior Ministry and the regional governor's office give different counts of "
                                  "the flooded homes.", claims=["C2", "C3"], title="Two counts of flooded homes"),
        dict(shot="headline", say="Floodwater closed the bridge on Tuesday, and rail traffic across the Varsel river was "
                                  "halted the same week.", claims=["C1", "C4"], title="Bridge and rail line closed"),
        dict(shot="sides", say="[sideA Government outlets lead with the repair plan and the minister's promise.] "
                               "[sideB Opposition outlets lead with the flooded homes and the deaths.]", points=["A1", "B1"]),
        dict(shot="sources", say="We read 4 articles: 1 from government outlets, 2 from the opposition and 1 from "
                                 "elsewhere. Details may still change."),
    ]


def answer(beats=None, **kw):
    return dict(plan="Lead with the closure; show both counts.", beats=beats if beats is not None else good_beats(),
                caption="Floodwater has closed the Varsel river bridge.", **kw)


class Fake:
    """One fake model for the writer (answers in order), the line check and the wording check.
    lines: {words in a line: verdict fields}; words: {words in a line: flag fields}."""

    def __init__(self, writer=(), lines=None, words=None):
        self.writer = list(writer)
        self.lines = lines or {}
        self.words = words or {}
        self.calls = []

    def __call__(self, messages, name=None, model=None, **params):
        kind = params["response_format"]["json_schema"]["name"]
        self.calls.append(dict(name=name, model=model, kind=kind, messages=messages, params=params))
        body = messages[-1]["content"]
        if kind == "script":
            a = self.writer.pop(0)
            text = a if isinstance(a, str) else json.dumps(a)
        elif kind == "line_check":
            out = []
            for n, line in re.findall(r"^L(\d+) · .*\nLine: (.*)$", body, flags=re.M):
                v = dict(id=f"L{n}", why="matches", verdict="backed", problem="none", claims_not_backing=[], alone=[])
                for k, over in self.lines.items():
                    if k in line:
                        v.update(over)
                out.append(v)
            text = json.dumps({"lines": out})
        elif kind == "wording":
            out = []
            for n, line in re.findall(r"^L(\d+): (.*)$", body, flags=re.M):
                for k, over in self.words.items():
                    if k in line:
                        out.append(dict(dict(id=f"L{n}", words=k, why="judges", neutral="x", level="loaded"), **over))
            text = json.dumps({"flags": out})
        else:
            raise AssertionError(kind)
        return SimpleNamespace(text=text, cost={"total": 0.001})

    def kinds(self):
        return [c["kind"] for c in self.calls]


def write(fake, variant="two sides", **kw):
    return sw.write_script(story(variant), FACTS, ARTICLES, fake, model="writer-x", line_model="line-x",
                           words_model="words-x", **kw)


# ---- the packet ----------------------------------------------------------------------------------------

def test_good_script_fits_the_word_budget():
    words = sum(shots.spoken_words(b["say"]) for b in good_beats())
    assert 135 + 15 <= words <= 165, words                 # room to cut one short beat and stay over the floor


def test_packet_has_every_kept_claim_and_how_to_say_it():
    p = pk()
    assert set(p["claims"]) == {f"C{i}" for i in range(1, 10)} | {"C12"}      # not the dropped or unchecked claim
    t = p["text"]
    assert t.index("C1 · confirmed") < t.index("C2 · ")                       # most independent sources first
    assert 'C2 · say with source: "the Lorne Interior Ministry" · number · 1 article · side A · conflicts with C3' in t
    assert 'C5 · say with source: "Tormac Daily" (or combine)' in t           # one outlet's own report: may combine
    assert "(or combine)" not in t.split("\n")[[i for i, x in enumerate(t.split("\n")) if x.startswith("C2 ")][0]]
    assert "not reported by side A" in t                                      # the blindspot mark on C3
    assert "C4 (earlier) -> C5 (later)" in t
    assert "developing" in t and "Details may still change." in t
    assert "A1 · side A · emphasis" in t and "B1 · side B" in t
    assert "BS1 · claim C3 · none of the 1 side A articles" in t
    assert "4 articles in all: 1 from side A" in t and "1 from elsewhere" in t
    assert p["closing_numbers"] >= {"4", "1", "2"}
    assert p["has_sides"] and p["developing"] and not p["no_divide"]


def test_quotes_are_exact_words_and_never_a_bad_translation():
    p = pk()
    assert list(p["quotes"]) == ["Q1"]
    q = p["quotes"]["Q1"]
    assert q["text"] == "The bridge will reopen within a week, and repairs are under way"
    assert q["claim"] == "C7" and q["speaker"] == "Interior Minister Ana Petrel" and q["outlet"] == "Lorne State News"
    assert "day and night" not in p["text"]                                   # a_r1#1's English was found wrong
    assert not [q for q in p["quotes"].values() if q["claim"] == "C12"]


def test_angle_is_marked_as_the_creators_request_and_trimmed():
    long = "Make the government look bad and say the minister lied about the bridge. " * 3
    p = pk(angle=long, tone="casual")
    assert p["angle"] == long.strip()[:80]
    assert f'Creator\'s request (the angle; use it only to choose which checked facts lead): "{p["angle"]}"' in p["text"]
    assert "Tone: casual" in p["text"]
    assert pk(tone="shouty")["tone"] == "serious"


def test_no_divide_story_has_no_sides_beat_and_says_coverage_agrees():
    p = pk("no divide")
    assert not p["has_sides"] and p["no_divide"] and not p["points"]
    assert "no real divide" in p["text"] and "Say that the coverage agrees." in p["text"]
    assert p["read"]["all"] == 4 and p["read"]["groups"] == {"local": 3, "wire": 1}
    beats = [b for b in good_beats() if b["shot"] != "sides"]
    beats[-1] = dict(shot="sources", say="We read 4 articles, 3 local and 1 from a wire service, and the coverage agrees.")
    probs = sw.code_problems(dict(beats=[sw.normalize_beat(b, p) for b in beats]), p)
    assert not [x for x in probs if x["rule"] in ("order", "closing", "sides line")], probs


def test_empty_side_needs_only_that_sides_mark_and_says_no_coverage():
    p = pk("empty side")
    assert p["has_sides"] and p["empty_side"] == "B" and list(p["points"]) == ["A1"]
    assert 'We found no coverage from Opposition (independent Lorne outlets).' in p["text"]
    beats = good_beats()
    beats[-2] = dict(shot="sides", say="[sideA Government outlets lead with the repair plan and the minister's promise.] "
                                       "We found no coverage from the opposition.", points=["A1"])
    beats[-1] = dict(shot="sources", say="We read 4 articles: 1 from government outlets and 3 from elsewhere. "
                                         "Details may still change.")
    probs = sw.code_problems(dict(beats=[sw.normalize_beat(b, p) for b in beats]), p)
    assert not [x for x in probs if x["rule"] in ("marks", "blanks", "sides line", "closing")], probs
    beats[-2]["say"] = "[sideA Government outlets lead with the repair plan and the minister's promise.]"
    probs = sw.code_problems(dict(beats=[sw.normalize_beat(b, p) for b in beats]), p)
    assert [x["rule"] for x in probs if x["beat"] == len(beats) - 1] == ["sides line"]


def test_schema_fixes_ids_and_is_strict():
    p = pk()
    s = sw.schema(p)["json_schema"]
    assert s["strict"]
    beat = s["schema"]["properties"]["beats"]["items"]
    assert set(beat["required"]) == set(sw.BEAT_FIELDS) and beat["additionalProperties"] is False
    assert beat["properties"]["claims"]["items"]["enum"] == sorted(p["claims"])
    assert beat["properties"]["card"]["enum"] == ["", "Q1"]
    assert beat["properties"]["points"]["items"]["enum"] == ["A1", "B1"]
    assert beat["properties"]["blindspot"]["enum"] == ["", "BS1"]
    assert len(beat["properties"]["shot"]["enum"]) == 13


def test_prompt_has_the_catalog_rules_and_a_made_up_example():
    t = sw.system_prompt()
    for shot in shots.shot_names():
        assert f"- {shot}:" in t
    assert "never claims, admits or insists" in t and "(or combine)" in t and "Floodwater closes the Varsel" in t
    msgs = sw.messages_for(pk())
    assert msgs[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert msgs[1]["content"].startswith("Event (from Monitor the Situation)")


# ---- the code rules ------------------------------------------------------------------------------------

def check(beats, variant="two sides"):
    p = pk(variant)
    return sw.code_problems(dict(beats=[sw.normalize_beat(b, p) for b in beats]), p)


def test_good_script_breaks_no_rule():
    assert check(good_beats()) == []


def test_order_and_repeat_rules():
    b = good_beats()
    probs = check([b[1], b[0]] + b[2:])
    assert any(x["rule"] == "order" and x["what"] == "beat 1 must be the hook" for x in probs)
    probs = check(b[:-2] + [b[-1], b[-2]])
    assert any(x["rule"] == "order" and "last beat" in x["what"] for x in probs)
    triple = b[:5] + [b[5], dict(b[5]), dict(b[6])] + b[7:]
    assert any(x["rule"] == "repeat" for x in check(triple))


def test_word_budget_and_hook_length():
    b = good_beats()
    probs = check(b[:3] + b[-2:])
    assert any(x["rule"] == "beats" for x in probs) and any(x["rule"] == "words" for x in probs)
    b[0] = dict(b[0], say="Floodwater has closed the Varsel river bridge in Lorne, and rail traffic across the river was halted.")
    assert not any(x["rule"] == "hook words" for x in check(b))         # 17 words: over the aim of 14, under 18
    b[0] = dict(b[0], say=b[0]["say"][:-1] + " on Tuesday morning after the storm.")
    assert any(x["rule"] == "hook words" for x in check(b))             # 22 words


def test_a_short_story_may_run_115_words():
    b = good_beats()
    short = b[:5] + b[7:]                                                 # the two headline beats left out
    assert sum(shots.spoken_words(x["say"]) for x in short) == 117
    assert not any(x["rule"] == "words" for x in check(short))
    short[1] = dict(short[1], say="The bridge was shut [place on the Varsel river.]")
    assert sum(shots.spoken_words(x["say"]) for x in short) == 113
    assert any(x["rule"] == "words" and "at least 115" in x["what"] for x in check(short))


def test_a_script_a_little_over_165_words_passes_and_over_180_fails():
    b = good_beats()
    b[1] = dict(b[1], say=b[1]["say"] + " Engineers closed the road to all traffic and set up a short detour south of the town.")
    b[5] = dict(b[5], say=b[5]["say"] + " The count may change as crews reach more streets.")
    words = sum(shots.spoken_words(x["say"]) for x in b)
    assert 165 < words <= 180 and not any(x["rule"] in ("words", "beat words") for x in check(b)), words
    b[6] = dict(b[6], say=b[6]["say"] + " Crews were still at the bridge late on Tuesday night.")
    assert sum(shots.spoken_words(x["say"]) for x in b) > 180
    assert any(x["rule"] == "words" and "at most 180" in x["what"] for x in check(b))


def test_say_with_source_must_name_the_source():
    b = good_beats()
    b[5] = dict(b[5], say="The ministry and the governor's office give different counts of the flooded homes.")
    probs = [x for x in check(b) if x["rule"] == "source named"]
    assert {x["what"].split()[0] for x in probs} == {"C2", "C3"}
    b[5] = dict(b[5], say="The Lorne Interior Ministry claims 340 homes flooded; the regional governor's office says more.")
    assert any("claims" in x["what"] for x in check(b) if x["rule"] == "source named")


def test_combining_two_outlets_lets_a_fact_be_said_plainly():
    p = pk()
    c = p["claims"]
    assert sw.plain_allowed([c["C5"], c["C6"]], p)                 # two outlets, one rated 0.5 or more
    assert not sw.plain_allowed([c["C5"]], p)                      # one outlet alone
    assert not sw.plain_allowed([c["C2"], c["C5"]], p)             # C2 is disputed
    copy_ = copy.deepcopy(c["C6"])
    copy_["independent_groups"] = [["a_o1", "a_w1"]]               # a copy of the same report counts once
    copy_["articles"] = ["a_w1"]
    c5 = dict(c["C5"], independent_groups=[["a_o1", "a_w1"]])
    assert not sw.plain_allowed([c5, copy_], p)
    b = good_beats()
    b[3] = dict(b[3], claims=["C5"], say="[step Trains restarted on one track on Wednesday,] then [step rail traffic resumed.]")
    assert any(x["rule"] == "source named" and "C5" in x["what"] for x in check(b))


def test_names_source_matching():
    assert sw.names_source("Lorne's Ministry of Defense says it downed drones", "Lorne's Defense Ministry")
    assert sw.names_source("Palace spokesman Varga said", "Palace spokesman Teo Varga")
    assert not sw.names_source("Varga said", "Palace spokesman Teo Varga")
    assert sw.names_source("Tormac Daily reports", "Lorne Wire and Tormac Daily")
    assert sw.names_source("Lorne State Radio, a state media outlet, reports", "Lorne State Radio (state-controlled media)")
    assert not sw.names_source("Lorne Radio reports", "Lorne State Radio (state-controlled media)")   # not called state media
    assert not sw.names_source("Lorne state media report", "Lorne State Radio (state-controlled media)")  # nor named
    assert sw.names_source("Varga said", "Palace spokesman Teo Varga", earlier="Palace spokesman Teo Varga spoke first.")
    assert not sw.names_source("Varga said", "Palace spokesman Teo Varga", earlier="The palace spoke first.")
    assert sw.names_source("Ana Petrel said", "Lorne Interior Minister Dr. Ana Petrel")       # titles aren't needed
    assert sw.names_source("Outlets say the bridge closed", "the outlet; the government")     # nothing code can check


def test_claims_as_a_noun_is_fine_as_a_verb_of_saying_is_not():
    assert sw.banned_verb("Tormac Daily reports no immediate claim for the attack.") is None
    assert sw.banned_verb("Two people were admitted to a regional hospital.") is None
    assert sw.banned_verb("The ministry claimed the bridge was safe.") == "claimed"
    assert sw.banned_verb("Police insist no one was hurt.") == "insist"


def test_surname_passes_after_the_full_name():
    b = good_beats()
    b[6] = dict(shot="headline", say="Petrel said the bridge would reopen within a week.", claims=["C7"],
                title="Bridge to reopen within a week")
    assert not [x for x in check(b) if x["rule"] == "source named"]                  # beat 5 named Ana Petrel in full
    b[4] = dict(b[4], say="The minister said [quote the bridge will reopen within a week, and repairs are under way.]")
    assert any(x["rule"] == "source named" and x["beat"] == 7 for x in check(b))


def test_tally_total_and_place_count_may_be_worked_out():
    p = pk()
    tally = sw.normalize_beat(dict(shot="tally", say="[count 340 and 1,200 homes] flooded, by each count.", claims=["C2", "C3"],
                                   rows=[{"label": "Ministry", "value": "340"}, {"label": "Governor", "value": "1,200"}],
                                   total="1540 by both counts"), p)
    assert not [x for x in sw._on_screen(tally, p) if "number" in x]
    assert any("1541" in x for x in sw._on_screen(dict(tally, total="1541"), p))
    spread = sw.normalize_beat(dict(shot="map_spread", say="Flooding reached [spread two places.]", claims=["C1", "C4"],
                                    places=["Varsel river", "Lorne"], label="2 places", place_kind="area"), p)
    assert sw._on_screen(spread, p) == []


def test_line_check_gets_our_counts_for_sides_and_blindspot_lines():
    p = pk("empty side")
    sides = sw.normalize_beat(dict(shot="sides", say="[sideA Government outlets lead with the repair plan.] We found no "
                                                    "coverage from the opposition.", points=["A1"]), p)
    msgs, _ = sw.line_messages(dict(beats=[sides]), p, FACTS, sw.contexts_for(FACTS, ARTICLES), [1])
    assert "Our counts: we read 1 article from side A" in msgs[1]["content"]
    assert "we found no coverage from Opposition (independent Lorne outlets)" in msgs[1]["content"]
    assert "Our counts" in msgs[0]["content"]
    p = pk()
    bs = sw.normalize_beat(dict(shot="headline", say="None of the government articles we read report the governor's count.",
                                claims=[], blindspot="BS1", title="One count went unreported"), p)
    msgs, _ = sw.line_messages(dict(beats=[bs]), p, FACTS, sw.contexts_for(FACTS, ARTICLES), [1])
    assert "Our counts: none of the 1 side A" in msgs[1]["content"] and "report C3" in msgs[1]["content"]


def test_line_check_takes_the_checked_claims_wording_as_backed():
    p = pk()
    b = sw.normalize_beat(good_beats()[0], p)
    msgs, _ = sw.line_messages(dict(beats=[b]), p, FACTS, sw.contexts_for(FACTS, ARTICLES), [1])
    assert "was already checked against its cards" in msgs[0]["content"]          # module 6 checked the claim
    c = p["claims"][b["claims"][0]]
    assert f"{c['id']} (" in msgs[1]["content"] and c["claim"] in msgs[1]["content"]   # its wording is shown


def test_closing_line_numbers_and_developing_hedge():
    b = good_beats()
    b[-1] = dict(shot="sources", say="We read 5 articles from all sides.")
    whats = [x["what"] for x in check(b) if x["rule"] == "closing"]
    assert any("5" in w and "counts" in w for w in whats) and any("we read 4" in w for w in whats)
    assert any("developing" in w for w in whats)


def test_on_screen_text_must_come_from_the_cited_claims():
    b = good_beats()
    b[2] = dict(b[2], accounts=[{"who": "Interior Ministry", "says": "350 homes flooded", "claim": "C2"},
                                {"who": "Governor's office", "says": "About 1,200 homes flooded", "claim": "C3"}])
    assert any(x["rule"] == "on screen" and "350" in x["what"] for x in check(b))
    b = good_beats()
    b[4] = dict(b[4], say="Interior Minister Ana Petrel said [quote the bridge reopens within a week.]")
    assert any(x["rule"] == "on screen" and "letter for letter" in x["what"] for x in check(b))
    b = good_beats()
    b[0] = dict(b[0], title="Catastrophic flood shuts bridge")
    assert any(x["rule"] == "on screen" and "Catastrophic" in x["what"] for x in check(b))


def test_marks_must_belong_to_the_shot():
    b = good_beats()
    b[1] = dict(b[1], say="The bridge was shut on Tuesday, [count on the Varsel river.]")
    whats = [x["what"] for x in check(b) if x["rule"] == "marks"]
    assert any("can't use the mark [count]" in w for w in whats)
    b = good_beats()
    b[2] = dict(b[2], say="How many homes flooded? The Lorne Interior Ministry says 340. The regional governor's office says about 1,200.")
    assert {w for w in (x["what"] for x in check(b) if x["rule"] == "marks")} == {
        "the claim_vs_claim shot needs a [left ...] mark", "the claim_vs_claim shot needs a [right ...] mark"}


def test_normalize_adds_the_quotes_and_accounts_claims():
    p = pk()
    b = sw.normalize_beat(dict(shot="quote", say="x", card="Q1", claims=["C99"], accounts="nonsense"), p)
    assert b["claims"] == ["C7"] and b["accounts"] == [] and b["broll_kind"] == "none"


def test_tolls_that_differ_give_a_warning():
    p = pk()
    b = good_beats()
    b[6] = dict(b[6], claims=["C1", "C4", "C8"], say=b[6]["say"] + " Police say two people died.")
    w = sw.warnings(dict(beats=[sw.normalize_beat(x, p) for x in b]), p)
    assert w and w[0]["beat"] == 7 and "C9" in w[0]["what"]


# ---- the whole script: checks, fix round, cuts -----------------------------------------------------------

def test_good_script_is_written_once_and_checked_by_the_other_models():
    fake = Fake([answer()])
    s = write(fake)
    assert s["status"] == "ok" and not s["fix_round"], s["checks"]["first"]["problems"]
    assert fake.kinds() == ["script", "line_check", "wording"]
    assert [c["model"] for c in fake.calls] == ["writer-x", "line-x", "words-x"]
    assert s["beats"][0]["blanks"]["tag"] == "Developing"                     # code adds it
    assert s["beats"][4]["blanks"]["quote"]["text"].startswith("The bridge will reopen")
    assert s["beats"][2]["named"] == ["the Lorne Interior Ministry", "the regional governor's office"]
    assert s["sources_card"]["read"] == 4 and s["sources_card"]["sides"][1]["read"] == 2
    assert s["credits"] == ["Events by Monitor the Situation (monitor-the-situation.com)", "https://mts.test/e/00000000"]
    assert s["caption"].endswith("https://mts.test/e/00000000")
    assert 135 <= s["words"] <= 165 and s["voice"].startswith("Floodwater has closed")
    line_msg = fake.calls[1]["messages"][-1]["content"]
    assert "[[" in line_msg and "L3 · claim_vs_claim" in line_msg and "L9" not in line_msg   # the closing isn't judged
    assert "“the bridge will reopen" in fake.calls[2]["messages"][-1]["content"]          # quotes shown as quotes


def test_fix_round_sends_the_problems_back_and_rechecks_only_changed_lines():
    bad = good_beats()
    bad[5] = dict(bad[5], say="The ministry and the governor's office give different counts of the flooded homes.")
    fake = Fake([answer(bad), answer()], lines={"The ministry and the governor's office": dict(verdict="needs a name")})
    s = write(fake)
    assert s["status"] == "ok" and s["fix_round"]
    first = s["checks"]["first"]
    assert {x["rule"] for x in first["problems"]} == {"source named", "line check"}
    fix_msg = fake.calls[3]["messages"][-1]["content"]
    assert fake.calls[3]["name"] == "script fix" and "beat 6 (source named)" in fix_msg
    assert fake.calls[3]["messages"][-2]["role"] == "assistant"
    # second round: only the changed line goes to the line check and the wording check
    second_line = fake.calls[4]["messages"][-1]["content"]
    assert "L6 · headline" in second_line and "L1 · hook" not in second_line
    assert s["checks"]["final"]["problems"] == []


def test_a_beat_that_still_fails_is_cut():
    fake = Fake([answer(), answer()], lines={"shut by floodwater on Tuesday":
                                             dict(verdict="not backed", problem="place or date", why="no such place")})
    s = write(fake)
    assert s["status"] == "ok with cuts" and s["fix_round"]
    assert [c["beat"] for c in s["checks"]["cuts"]] == [2] and s["checks"]["cuts"][0]["became"] == "cut"
    assert len(s["beats"]) == 8 and s["beats"][1]["shot"] == "claim_vs_claim" and s["beats"][1]["was"] == 3
    assert s["beats"][1]["line"]["verdict"] == "backed" and s["words"] == 151 - 12


def test_on_screen_only_problem_becomes_a_headline_card():
    p = pk()
    b = [sw.normalize_beat(x, p) for x in good_beats()]
    b[3]["steps"][1]["what"] = "Trains back on 2 tracks"
    probs = sw.code_problems(dict(beats=b), p)
    assert [x["rule"] for x in probs] == ["on screen"]
    out, cuts, why = sw.cut(dict(beats=b), p, probs)
    assert why is None and cuts[0]["became"] == "headline"
    h = out["beats"][3]
    assert h["shot"] == "headline" and h["title"] == "Rail traffic across the Varsel river was halted, then trains"
    assert "[" not in h["say"]


def test_failing_hook_means_no_video():
    fake = Fake([answer(), answer()], lines={"has closed the Varsel": dict(verdict="not backed", problem="other", why="x")})
    s = write(fake)
    assert s["status"] == "no video" and "hook" in s["reason"] and s["beats"] == []


def test_loaded_words_fail_and_are_fixed():
    loaded = good_beats()
    loaded[6] = dict(loaded[6], say="Catastrophic floodwater closed the bridge on Tuesday, and rail traffic across the "
                                    "Varsel river was halted the same week.")
    fake = Fake([answer(loaded), answer()], words={"Catastrophic": {}})
    s = write(fake)
    assert any(x["rule"] == "loaded words" for x in s["checks"]["first"]["problems"])
    assert s["status"] == "ok"


def test_unusable_answers_mean_no_video_never_a_guess():
    fake = Fake(["not json", "{\"beats\": []}"])
    s = write(fake)
    assert s["status"] == "no video" and s["reason"] == "no usable answer from the writer"
    assert fake.kinds() == ["script", "script"] and fake.calls[1]["name"] == "script retry json"


def test_one_retry_rescues_a_broken_answer():
    fake = Fake(["```json\n{broken", answer()])
    assert write(fake)["status"] == "ok"


def test_budget_errors_pass_through():
    class BudgetExceeded(RuntimeError):
        pass

    def broke(messages, **kw):
        raise BudgetExceeded("cap")

    with pytest.raises(BudgetExceeded):
        write(broke)


def test_script_file_is_written_whole(tmp_path):
    s = write(Fake([answer()]))
    p = sw.write_file(tmp_path, s)
    assert p.name == "script.json" and sw.read_script(tmp_path)["beats"][0]["shot"] == "hook"
    assert not [x for x in tmp_path.iterdir() if x.name.startswith(".")]
