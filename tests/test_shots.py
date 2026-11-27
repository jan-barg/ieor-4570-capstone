"""The shared shot catalog and the checks modules 7 and 8 both run. Made-up text only."""
from stringer import shots


def test_catalog_has_the_13_shots_and_consistent_marks():
    cat = shots.catalog()
    assert cat["version"] == "shots-2"
    assert list(cat["shots"]) == ["hook", "map_locate", "map_link", "map_spread", "quote", "claim_vs_claim", "big_number",
                                  "tally", "document", "timeline", "sides", "sources", "headline"]
    for name, s in cat["shots"].items():
        assert set(s["required_marks"]) <= set(s["marks"]), name
        assert isinstance(s["blanks"], dict) and s["use"]
    lim = shots.limits()
    assert (lim["words_min"], lim["words_max"], lim["beats_min"], lim["beats_max"]) == (135, 165, 7, 10)
    assert lim["beat_words_max"] == 30 and lim["hook_words_max"] == 14 and lim["angle_chars_max"] == 80
    assert (lim["words_hard_min"], lim["words_hard_max"], lim["hook_words_hard_max"]) == (115, 180, 18)   # refused outside
    assert set(cat["tones"]) == {"serious", "casual", "high-energy"}
    assert "drone" in cat["broll"]["props"] and len(cat["broll"]["props"]) == 21


def test_marks_voice_and_display():
    line = "Officials say [count 340 homes] flooded, and Ana Petrel said [quote repairs are under way]."
    assert shots.marks(line) == [("count", "340 homes"), ("quote", "repairs are under way")]
    assert shots.voice(line) == "Officials say 340 homes flooded, and Ana Petrel said repairs are under way."
    assert shots.display(line).endswith("said “repairs are under way”.")
    assert not shots.stray_brackets(line)
    assert shots.stray_brackets("a [count [step nested] mark]")
    assert shots.stray_brackets("a [count] mark with no words")


def test_spoken_words_reads_numbers_aloud():
    assert shots.int_words(1441) == 6            # one thousand four hundred forty one
    assert shots.int_words(1200) == 4            # one thousand two hundred
    assert shots.int_words(340) == 3
    assert shots.int_words(12) == 1
    assert shots.spoken_words("Officials say [count 1,441 homes] flooded.") == 2 + 6 + 2
    # in, twenty twenty six, it, cost, four hundred seventy four, dollars, million
    assert shots.spoken_words("In 2026 it cost $474 million.") == 1 + 3 + 2 + 4 + 1 + 1
    assert shots.spoken_words("In 2018 and 1900") == 1 + 2 + 1 + 2
    assert shots.spoken_words("50% of 2.5 tons") == 2 + 1 + 3 + 1
    assert shots.spoken_words("a 24-hour halt on the 17th") == 1 + 3 + 4


def test_on_screen_numbers_and_names_come_from_the_claims():
    allowed = "The Lorne Interior Ministry says 340 homes were flooded near the Varsel river."
    assert shots.on_screen_problems(["340 homes flooded", "Interior Ministry", "Varsel river"], allowed) == []
    probs = shots.on_screen_problems(["350 homes flooded", "Tormac Ministry"], allowed)
    assert any("350" in p for p in probs) and any("Tormac" in p for p in probs)
    assert shots.on_screen_problems(["Lorne's ministry"], allowed) == []            # possessives and case are fine
    assert shots.on_screen_problems(["Massive flooding"], allowed)                  # a word not in the claims, capitalised
    assert shots.on_screen_problems(["Later", "Earlier: homes flooded"], allowed) == []   # time words aren't names


def test_on_screen_names_may_come_from_the_whole_story_numbers_only_from_the_cited_claims():
    allowed = "Minister Ana Petrel said the Varsel-Ost bridge would reopen within a week."
    story = "Tormac Daily says sixteen homes flooded. The regional governor Ivo Brand-Kessel visited Lorne."
    assert shots.on_screen_problems(["Ivo Brand-Kessel", "Tormac Daily"], allowed)            # not in the cited claims
    assert shots.on_screen_problems(["Ivo Brand-Kessel", "Tormac Daily"], allowed, names=story) == []
    assert shots.on_screen_problems(["Varsel-Ost bridge", "Interior Minister"], allowed) == []   # hyphenated name; an office
    assert shots.on_screen_problems(["Lorne Defense Secretary", "Left-leaning outlets"], allowed, names=story) == []
    assert shots.on_screen_problems(["16 homes"], allowed, names=story)                       # numbers stay strict
    assert shots.on_screen_problems(["Massive flood"], allowed, names=story)                  # still not a name in the story
    assert shots.on_screen_problems(["US envoy"], allowed)                                    # the story never names the US
    assert shots.on_screen_problems(["US envoy"], allowed, names="The U.S. sent an envoy.") == []


def test_number_words_are_numbers():
    assert {"16", "21", "40", "12"} <= shots.numbers("Sixteen homes, twenty-one cars, forty boats and a dozen trucks")
    assert shots.on_screen_problems(["16 homes"], "Sixteen homes were flooded.") == []


def test_quotes_match_letter_for_letter():
    q = "The bridge will reopen within a week, and repairs are under way."
    assert shots.quote_matches("the bridge will reopen within a week", q)
    assert shots.quote_matches("“The bridge will reopen within a week, and repairs are under way.”", q)
    assert not shots.quote_matches("the bridge will reopen in a week", q)
    assert not shots.quote_matches("a week", q)                                    # too short to be a quote
    probs = shots.on_screen_problems([], "", quotes=[("the bridge reopens within a week", q)])
    assert probs and "letter for letter" in probs[0]
