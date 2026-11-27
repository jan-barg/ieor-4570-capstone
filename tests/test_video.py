"""Module 8, the animation module, on made-up data: module 7's made-up river-bridge story (tests/test_script_
writer.py), a tiny invented gazetteer, the evenly paced stand-in voice and a generated test clip. No keys, no
real stories, no Remotion (the drawing is checked by rendering stills, see the system map)."""
import copy
import json
import re
import shutil
import subprocess

import pytest

from stringer import paths, shots
from stringer.video import check, direct, evals, files, people, places, plan, voice

import test_script_writer as t7

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# ---- made-up inputs ------------------------------------------------------------------------------------

def script(**over):
    """The made-up script.json module 7's tests write, with overrides."""
    s = copy.deepcopy(t7.write(t7.Fake([t7.answer()])))
    s.update(over)
    return s


def packet():
    return t7.pk()


EVENT = dict(t7.EVENT, lat=51.45, lng=12.1)


def square(w, s, e, n):
    return {"type": "MultiPolygon", "coordinates": [[[[w, s], [e, s], [e, n], [w, n], [w, s]]]]}


@pytest.fixture
def geo(tmp_path):
    """An invented country (Lorne), a province, a sea and four towns."""
    shapes = {"c:LRN:Lorne": square(10, 50, 14, 53), "c:TRM:Tormac": square(14, 50, 18, 53),
              "p:LRN-1": square(11, 51, 13, 52), "s:1": square(14, 46, 16, 49.5)}
    data = dict(version="places-1",
                countries=[dict(id="c:LRN:Lorne", name="Lorne", iso2="LR", names=["Lorne", "Republic of Lorne"],
                                lat=51.5, lng=12.0, bbox=[10, 50, 14, 53], area=5_000_000),
                           dict(id="c:TRM:Tormac", name="Tormac", iso2="TM", names=["Tormac"], lat=51.5, lng=16.0,
                                bbox=[14, 50, 18, 53], area=2_000_000)],
                provinces=[dict(id="p:LRN-1", name="Upper Varsel", names=["Upper Varsel"], iso2="LR", country="Lorne",
                                kind="Province", lat=51.5, lng=12.0, bbox=[11, 51, 13, 52])],
                seas=[dict(id="s:1", name="Gulf of Tormac", names=["Gulf of Tormac"], kind="gulf", lat=47.7, lng=15.0,
                           bbox=[14, 46, 16, 49.5])],
                towns=[["Varsel", "Varsel", ["Warsel"], 51.5, 12.0, "LR", 200_000, "PPLA"],
                       ["Kessa", "Kessa", [], 52.6, 13.6, "LR", 500_000, "PPLC"],
                       ["Nordby", "Nordby", [], 50.7, 10.9, "LR", 150_000, "PPL"],
                       ["Orrin", "Orrin", [], 51.55, 12.5, "LR", 120_000, "PPL"],
                       ["Little Varsel", "Little Varsel", [], 51.3, 11.4, "LR", 20_000, "PPL"]])
    (tmp_path / "places.json").write_text(json.dumps(data))
    (tmp_path / "shapes.json").write_text(json.dumps(shapes))
    return places.Gazetteer(tmp_path)


@pytest.fixture
def no_portraits(tmp_path, monkeypatch):
    monkeypatch.setattr(people, "FOLDER", tmp_path / "people")
    people._load.cache_clear()


def narrated(beats, tmp_path, audio=False):
    return voice.narrate(beats, voice.Paced(audio=audio), cache_dir=tmp_path / "voice")


def checked(s=None):
    res = check.check_script(s or script(), packet())
    assert res["stop"] is None, res["stop"]
    return res


# ---- step 1: the check ---------------------------------------------------------------------------------

def test_good_script_passes_with_no_swaps():
    res = checked()
    assert res["swaps"] == [] and len(res["beats"]) == 9
    text = check.voice_text(res["beats"])
    assert "[" not in text and "]" not in text and text.count("\n") == 8


def test_beat_that_cant_be_drawn_becomes_a_headline_card_and_is_listed():
    s = script()
    tl = next(b for b in s["beats"] if b["shot"] == "timeline")
    tl["blanks"]["steps"][0]["what"] = "17 trains halted"            # 17 is in no cited claim
    res = checked(s)
    nb = next(b for b in res["beats"] if b.get("swapped_from") == "timeline")
    assert nb["shot"] == "headline" and "[" not in nb["say"]
    assert res["swaps"] == [dict(beat=tl["n"], shot="timeline", became="headline", title_kept=False,
                                 why=res["swaps"][0]["why"])]
    assert "17" in res["swaps"][0]["why"]


def test_a_hook_that_cant_be_drawn_stops_the_video():
    s = script()
    s["beats"][0]["blanks"]["title"] = "Floodwater closes 9 bridges"
    res = check.check_script(s, packet())
    assert res["stop"].startswith("the hook beat can't be drawn")


@pytest.mark.parametrize("change, stop", [
    (dict(status="no video", reason="one source only"), "module 7 wrote no video: one source only"),
    (dict(sources_card=None), "the script has no sources card"),
])
def test_stops_before_any_cost(change, stop):
    assert check.check_script(script(**change), packet())["stop"] == stop


def test_the_script_must_open_with_the_hook_and_end_with_sources():
    s = script()
    s["beats"] = s["beats"][1:]
    assert "must open with the hook" in check.check_script(s, packet())["stop"]


def test_the_quote_drawn_must_be_the_cards_evidence_quote():
    s = script()
    q = next(b for b in s["beats"] if b["shot"] == "quote")
    assert check.beat_problems(q, packet()) == []
    q["blanks"]["quote"] = dict(q["blanks"]["quote"], text=q["blanks"]["quote"]["text"] + " and much more")
    assert "the quote on screen isn't the evidence quote letter for letter" in check.beat_problems(q, packet())


def test_voice_text_with_a_bracket_or_not_matching_the_line_is_a_problem():
    b = copy.deepcopy(script()["beats"][1])
    b["voice"] = b["voice"] + " [oops]"
    probs = check.beat_problems(b, packet())
    assert any("bracket" in p for p in probs) and any("marks taken out" in p for p in probs)


# ---- step 2: the voice ---------------------------------------------------------------------------------

def test_voice_spans_strip_the_marks_and_remember_their_words():
    text, spans = voice.voice_spans("Shut on Tuesday, [place on the Varsel river.] Then [quote it will reopen].")
    assert text == shots.voice("Shut on Tuesday, [place on the Varsel river.] Then [quote it will reopen].")
    assert [(m, text[a:b]) for m, a, b in spans] == [("place", "on the Varsel river."), ("quote", "it will reopen")]


def test_narration_times_every_word_beat_and_mark(tmp_path):
    res = checked()
    n = narrated(res["beats"], tmp_path)
    starts = [w["start"] for w in n["words"]]
    assert starts == sorted(starts) and len(n["words"]) == sum(len(b["voice"].split()) for b in res["beats"])
    assert [b["n"] for b in n["beats"]] == [b["n"] for b in res["beats"]]
    for a, b in zip(n["beats"], n["beats"][1:]):
        assert a["start"] < a["end"] <= b["start"] + 1e-6
    assert n["duration"] == pytest.approx(n["seconds"] + voice.HOLD)
    sides = next(i for i, b in enumerate(res["beats"]) if b["shot"] == "sides")
    mk = {m["mark"]: m for m in n["marks"] if m["beat"] == sides}
    assert mk["sideA"]["text"].startswith("Government outlets") and mk["sideB"]["start"] > mk["sideA"]["end"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_a_recording_is_reused_for_the_same_text_and_voice(tmp_path):
    beats = checked()["beats"]
    first, again = narrated(beats, tmp_path, audio=True), narrated(beats, tmp_path, audio=True)
    assert not first["reused"] and again["reused"] and again["credits_now"] == 0
    faster = voice.narrate(beats, voice.Paced(audio=True).with_speed(1.1), cache_dir=tmp_path / "voice")
    assert not faster["reused"] and faster["seconds"] < first["seconds"]


# ---- step 1b: the voice director (proposed Nov 26, off by default) --------------------------------------

class Answer:
    def __init__(self, text):
        self.text = text


def director(lines=None, fail=False):
    """A stand-in model: answers with the given tagged lines (by line number), or fails."""
    calls = []

    def complete(messages, name=None, **params):
        calls.append(dict(messages=messages, name=name, **params))
        if fail:
            raise TimeoutError("no answer")
        return Answer(json.dumps({"lines": [{"n": n, "line": t} for n, t in (lines or {}).items()]}))
    complete.calls = calls
    return complete


class Letters:
    """A stand-in voice that reads tags: every letter (tags too, as ElevenLabs does) 0.05 s after the last."""
    engine, tags = "letters", True

    def key(self):
        return dict(engine=self.engine)

    def speak(self, text, out):
        out.write_bytes(b"")
        return dict(chars=[(c, i * 0.05, i * 0.05 + 0.05) for i, c in enumerate(text)], seconds=len(text) * 0.05,
                    credits=len(text))


def test_untag_gives_back_the_line_and_where_each_letter_was():
    tagged = "[calm] The bridge shut. [serious] Then it reopened."
    plain, keep = direct.untag(tagged)
    assert plain == "The bridge shut. Then it reopened."
    assert "".join(tagged[i] for i in keep) == plain
    assert direct.tags_in(tagged) == ["calm", "serious"]


def test_the_director_may_add_tags_but_never_change_a_word():
    beats = checked()["beats"]
    v = {b["n"]: b["voice"] for b in beats}
    side = next(b["n"] for b in beats if b["shot"] == "sides")
    lines = {1: "[serious] " + v[1],                                    # fine
             2: "[calm] " + v[2].replace("Tuesday", "Wednesday"),       # a word changed
             3: "[thoughtful] " + v[3],                                 # claim vs claim: a neutral tag is fine
             6: "[angry] " + v[6],                                      # not on the list
             4: v[4] + " [calm]",                                       # a tag at the end
             5: "[calm] [serious] " + v[5],                             # two in a row
             side: "[somber] " + v[side]}                               # a side's line gets neutral tags only
    d = direct.direct(beats, "Bridge closed", director(lines))
    by = {x["n"]: x for x in d["lines"]}
    assert by[1]["ok"] and by[1]["tagged"] == lines[1] and by[1]["tags"] == ["serious"]
    assert by[2]["problems"] == ["the words changed"] and by[2]["tagged"] == v[2]
    assert by[3]["ok"] and by[3]["tags"] == ["thoughtful"]
    assert by[6]["problems"] == ["tags not on the list: angry"]
    assert by[4]["problems"] == ["a tag at the end of the line"]
    assert "two tags in a row" in by[5]["problems"]
    assert by[side]["problems"] == ["a side's line may only have the neutral tags"]
    assert all(x["tagged"] == x["voice"] for x in d["lines"] if not x["ok"])
    untouched = [x for x in d["lines"] if x["n"] not in lines]               # lines it left out are read as they were
    assert untouched and all(x["ok"] and x["tagged"] == x["voice"] for x in untouched)
    assert d["tags"] == 2 and d["refused"] == 5


def test_a_director_that_fails_leaves_every_line_as_it_was():
    beats = checked()["beats"]
    c = director(fail=True)
    d = direct.direct(beats, "Bridge closed", c)
    assert not d["answered"] and d["calls"] == 2 and len(c.calls) == 2
    assert all(x["ok"] and x["tagged"] == x["voice"] and not x["tags"] for x in d["lines"])
    sent = json.loads(c.calls[0]["messages"][1]["content"].split("Lines:\n", 1)[1])
    assert [x["line"] for x in sent] == [b["voice"] for b in beats]          # the lines exactly, the label apart
    assert [x["side"] for x in sent] == [b["shot"] in ("sides", "claim_vs_claim") for b in beats]


def test_tagged_lines_time_the_same_words_and_marks(tmp_path):
    beats = checked()["beats"]
    tagged = ["[serious] " + b["voice"] if i % 2 == 0 else b["voice"] for i, b in enumerate(beats)]
    plain = voice.narrate(beats, Letters(), cache_dir=tmp_path / "v")
    told = voice.narrate(beats, Letters(), cache_dir=tmp_path / "v", directed=tagged)
    assert not told["reused"] and told["spoken_text"].startswith("[serious] ") and plain["spoken_text"] is None
    assert [w["w"] for w in told["words"]] == [w["w"] for w in plain["words"]]
    assert [m["text"] for m in told["marks"]] == [m["text"] for m in plain["marks"]]
    assert told["words"][0]["start"] == pytest.approx(len("[serious] ") * 0.05)   # the tag's own time is skipped
    assert told["chars"] == len(told["spoken_text"]) > plain["chars"]              # tags are paid for as letters
    paced = voice.narrate(beats, voice.Paced(audio=False), cache_dir=tmp_path / "p", directed=tagged)
    assert paced["spoken_text"] is None                                            # a voice that can't read tags ignores them
    with pytest.raises(voice.VoiceError):
        voice.narrate(beats, Letters(), cache_dir=tmp_path / "v", directed=tagged[:-1])


def test_the_direction_for_the_same_lines_is_reused_so_the_recording_is_too(tmp_path):
    beats = checked()["beats"]
    lines = {1: "[serious] " + beats[0]["voice"]}
    f = tmp_path / "direction.json"
    f.write_text(json.dumps(direct.direct(beats, "Bridge closed", director(lines), model="m")))
    again = direct.reuse(f, beats, model="m")
    assert again["reused"] and again["lines"][0]["tagged"] == lines[1]
    changed = [dict(b, voice=b["voice"] + " Still.") if i == 2 else b for i, b in enumerate(beats)]
    assert direct.reuse(f, changed, model="m") is None                  # a line changed: ask again
    assert direct.reuse(f, beats, model="other") is None                # another model or style: ask again
    assert direct.reuse(f, beats, model="m", style="steady") is None
    f.write_text(json.dumps(direct.direct(beats, "Bridge closed", director(fail=True), model="m")))
    assert direct.reuse(f, beats, model="m") is None                    # it never answered: ask again
    assert direct.reuse(tmp_path / "missing.json", beats, model="m") is None


class QuietLetters(Letters):
    """Letters, with a real (silent) recording as long as its timings."""
    def speak(self, text, out):
        got = super().speak(text, out)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                        "-t", str(got["seconds"]), "-b:a", "64k", str(out)], check=True)
        return got


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_the_silence_before_the_first_word_is_cut_for_free(tmp_path):
    beats = checked()["beats"]
    tagged = ["[serious] " + beats[0]["voice"]] + [b["voice"] for b in beats[1:]]     # the tag takes 0.5 s here
    whole = voice.narrate(beats, QuietLetters(), cache_dir=tmp_path / "v", directed=tagged)
    cut = voice.narrate(beats, QuietLetters(), cache_dir=tmp_path / "v", directed=tagged, trim_opening=True)
    assert cut["reused"] and cut["credits_now"] == 0                                    # the same recording
    assert whole["words"][0]["start"] == pytest.approx(0.5) and cut["words"][0]["start"] == pytest.approx(voice.LEAD)
    gap = 0.5 - voice.LEAD
    assert [w["start"] for w in cut["words"]] == pytest.approx([w["start"] - gap for w in whole["words"]], abs=1e-3)
    assert cut["seconds"] == pytest.approx(whole["seconds"] - gap, abs=1e-3)
    got = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                cut["audio"]], capture_output=True, text=True, check=True).stdout)
    assert got == pytest.approx(cut["seconds"], abs=0.1)                                # the audio itself starts later
    plain = voice.narrate(beats, QuietLetters(), cache_dir=tmp_path / "v", trim_opening=True)
    assert plain["words"][0]["start"] == 0.0                                            # no silence: nothing cut


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_a_long_narration_is_sped_up_from_the_same_recording_for_free(tmp_path):
    beats = checked()["beats"]
    first = narrated(beats, tmp_path, audio=True)
    fast = voice.narrate(beats, voice.Paced(audio=True), cache_dir=tmp_path / "voice", tempo=1.1)
    assert fast["reused"] and fast["credits_now"] == 0 and fast["tempo"] == 1.1     # no new recording
    assert fast["seconds"] == pytest.approx(first["seconds"] / 1.1, abs=0.01)
    assert fast["duration"] == pytest.approx(fast["seconds"] + voice.HOLD)            # the sources card keeps its hold
    assert [w["w"] for w in fast["words"]] == [w["w"] for w in first["words"]]
    assert [w["start"] for w in fast["words"]] == pytest.approx([w["start"] / 1.1 for w in first["words"]], abs=0.01)
    got = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                fast["audio"]], capture_output=True, text=True, check=True).stdout)
    assert got == pytest.approx(first["seconds"] / 1.1, abs=0.15)                     # the audio itself is shorter


# ---- step 3: places and portraits ----------------------------------------------------------------------

@pytest.mark.parametrize("name, kind, how, found", [
    ("Varsel", "point", "as given", "Varsel"),
    ("Upper Varsel", "point", "as another kind", "Upper Varsel"),          # sent as a point, found as a province
    ("Varsel railway station", "point", "part: Varsel", "Varsel"),         # a site pins its town
    ("Warsel", "point", "as given", "Varsel"),                             # an alternate name
])
def test_place_lookup_order(geo, name, kind, how, found):
    p = places.find(name, kind, EVENT, geo)
    assert (p["how"], p["found"], p["name"]) == (how, found, name)


def test_place_named_in_the_event_location_falls_back_to_the_event(geo):
    p = places.find("Varsel river", "point", dict(EVENT, location_name="Bend of the Varsel river, Lorne"), geo)
    assert p["how"] == "part: Varsel"
    q = places.find("Grey Ford", "point", dict(EVENT, location_name="Grey Ford, Lorne"), geo)
    assert q["how"] == "the event's coordinates" and (q["lat"], q["lng"]) == (EVENT["lat"], EVENT["lng"])
    assert places.find("Grey Ford", "point", EVENT, geo) is None


def test_a_part_far_from_the_event_is_not_used(geo):
    far = dict(EVENT, lat=-30.0, lng=150.0)
    assert places.find("Varsel railway station", "point", far, geo) is None


def test_a_word_that_is_never_a_place_alone_is_not_pinned(geo):
    assert "station" not in places._parts("Varsel railway station")
    assert places._parts("Space Center") == []


def test_frames_for_a_point_a_province_and_two_places(geo):
    pt = places.find("Varsel", "point", EVENT, geo)
    w, s, e, n = places.frame([pt], geo)
    assert places.km(s, 12.0, n, 12.0) == pytest.approx(2 * places.POINT_HALF_KM, rel=0.02)
    prov = places.find("Upper Varsel", "province", EVENT, geo)
    b = places.frame([prov], geo)
    assert b[0] < 11 and b[2] > 13 and b[1] < 51 and b[3] > 52
    two = places.frame([pt, places.find("Kessa", "point", EVENT, geo)], geo)
    assert places.in_box(two, 12.0, 51.5) and places.in_box(two, 13.6, 52.6)


def test_context_gives_borders_country_names_and_big_towns_clear_of_the_pin(geo):
    box = [10.5, 50.3, 13.9, 52.9]
    c = places.context(box, geo, skip=[(12.0, 51.5)])
    names = [t["name"] for t in c["towns"]]
    assert "Varsel" not in names                      # the pinned place itself
    assert "Orrin" not in names                       # on the row the pin's label runs along
    assert "Little Varsel" not in names               # under 100,000 people
    assert "Kessa" in names and "Nordby" in names
    assert [x["name"] for x in c["countries"]] == ["Lorne"]
    assert c["borders"] and all(len(run) > 1 for run in c["borders"])


def test_contains_and_in_box():
    sh = square(0, 0, 2, 2)
    assert places.contains(sh, 1, 1) and not places.contains(sh, 3, 1)
    assert places.in_box([0, 0, 2, 2], 2, 2) and not places.in_box([0, 0, 2, 2], 2.1, 1)


def test_only_approved_portraits_whose_photo_exists(tmp_path):
    folder = tmp_path / "people"
    folder.mkdir()
    (folder / "petrel.png").write_bytes(b"png")
    (folder / "people.json").write_text(json.dumps({"version": "people-1", "people": [
        dict(name="Ana Petrel", aliases=["Minister Petrel"], file="petrel.png", author="A. Photographer",
             license="CC BY 4.0", approved=True),
        dict(name="Ivo Brand", file="brand.png", approved=True),                      # no photo on disk
        dict(name="Mara Sund", file="petrel.png", approved=False)]}))
    people._load.cache_clear()
    p = people.portrait("minister petrel", folder)
    assert p["name"] == "Ana Petrel" and p["file"].endswith("petrel.png") and "CC BY 4.0" in p["credit"]
    assert people.portrait("Ivo Brand", folder) is None and people.portrait("Mara Sund", folder) is None



def test_a_cutout_on_disk_makes_a_cutout_portrait_with_its_face_box(tmp_path):
    folder = tmp_path / "people"
    (folder / "photos").mkdir(parents=True)
    (folder / "cutouts").mkdir()
    for f in ("photos/petrel.jpg", "photos/brand.jpg", "photos/sund.jpg", "cutouts/petrel.png"):
        (folder / f).write_bytes(b"img")
    (folder / "people.json").write_text(json.dumps({"version": "people-2", "people": [
        dict(name="Ana Petrel", file="photos/petrel.jpg", author="A. Photographer", license="CC BY 4.0", approved=True,
             cutout="cutouts/petrel.png", face=[0.2, 0.1, 0.7, 0.55]),
        dict(name="Ivo Brand", file="photos/brand.jpg", author="B. Lens", license="CC0", approved=True,
             cutout="cutouts/brand.png", face=[0.2, 0.1, 0.7, 0.55]),                 # cutout missing on disk
        dict(name="Mara Sund", file="photos/sund.jpg", author="C. Shutter", license="CC0", approved=True,
             cutout="cutouts/petrel.png", face=[0.2, 0.1])]}))                        # broken face box
    people._load.cache_clear()
    p = people.portrait("Ana Petrel", folder)
    assert p["cutout"] == str(folder / "cutouts/petrel.png") and p["face"] == [0.2, 0.1, 0.7, 0.55]
    assert p["credit"] == "Portrait of Ana Petrel cut out from a photo by A. Photographer, CC BY 4.0"
    for name in ("Ivo Brand", "Mara Sund"):           # no usable cutout: the dotted badge, credited as redrawn
        q = people.portrait(name, folder)
        assert "cutout" not in q and "face" not in q and " redrawn from a photo by " in q["credit"]
    people._load.cache_clear()


def _cut_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cut_portraits", paths.CODE / "scripts" / "cut_portraits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cutter_results_go_into_people_json_and_a_stale_cutout_is_dropped():
    doc = {"version": "people-1", "people": [
        dict(name="Ana Petrel", file="photos/ana-petrel.jpg", approved=True),
        dict(name="Ivo Brand", file="photos/ivo-brand.png", approved=True, cutout="cutouts/ivo-brand.png", face=[0, 0, 1, 1]),
        dict(name="Mara Sund", file="photos/mara-sund.jpg", approved=False)]}
    results = [{"file": "ana-petrel", "w": 600, "h": 800, "face": [0.21234, 0.1, 0.7, 0.5]},
               {"file": "ivo-brand", "error": "no person found"},
               {"file": "mara-sund", "w": 600, "h": 800}]                                 # no face found
    new = _cut_script().merge(doc, results)
    rows = {p["name"]: p for p in new["people"]}
    assert new["version"] == "people-2" and doc["version"] == "people-1"                  # the input is not changed
    assert rows["Ana Petrel"]["cutout"] == "cutouts/ana-petrel.png" and rows["Ana Petrel"]["face"] == [0.212, 0.1, 0.7, 0.5]
    assert "cutout" not in rows["Ivo Brand"] and "face" not in rows["Ivo Brand"]          # failed now: old file not used
    assert "cutout" not in rows["Mara Sund"] and rows["Mara Sund"]["approved"] is False


def test_the_renderer_draws_cutouts_by_the_shot_jan_picked():
    js = (paths.CODE / "render" / "src" / "portraits.js").read_text(encoding="utf-8")
    assert "export const STANDING = new Set(['quote']);" in js          # standing on quotes, a sticker elsewhere
    lay = (paths.CODE / "render" / "src" / "layout.js").read_text(encoding="utf-8")
    assert all(k in lay for k in ("'face over text'", "'face under captions'", "'face outside safe area'", "'portrait left out'"))
    cards = (paths.CODE / "render" / "src" / "cards.js").read_text(encoding="utf-8")
    assert "hasCutout(beat)" in cards and "stickerBand()" in cards      # a headline keeps room for the person's sticker

# ---- step 4: the render plan ---------------------------------------------------------------------------

def built(tmp_path, geo, s=None, beats=None):
    s = s or script()
    res = checked(s)
    beats = beats or res["beats"]
    n = narrated(beats, tmp_path)
    return plan.build(beats, n, s, EVENT, swaps=res["swaps"], g=geo, p7=packet()), n


@pytest.mark.parametrize("named, label", [
    (["the outlet; two regional officials; a regional official"], "Source: Two regional officials"),
    (["RIA Novosti (state-controlled media)"], "Source: RIA Novosti (state-controlled media)"),
    (["Lorne Interior Ministry", "the Interior Ministry", "Kessa police", "Red Cross"],
     "Sources: Lorne Interior Ministry · Kessa police"),
    (["the outlet"], ""),
    ([], ""),
])
def test_source_label(named, label):
    assert plan.source_label(named) == label


def test_plan_frames_follow_the_voice(tmp_path, geo, no_portraits):
    pl, n = built(tmp_path, geo)
    assert pl["version"] == plan.VERSION and (pl["width"], pl["height"], pl["fps"]) == (1080, 1920, 30)
    assert pl["frames"] == round(n["duration"] * 30)
    assert all(b["frames"] == b["end"] - b["start"] > 0 for b in pl["beats"])
    for a, b in zip(pl["beats"], pl["beats"][1:]):
        assert a["end"] <= b["start"] + 1
    q = next(b for b in pl["beats"] if b["shot"] == "quote")
    m = q["marks"][0]
    assert m["mark"] == "quote" and 0 <= m["start"] < m["end"] <= q["frames"]


def test_a_map_gets_the_lakes_in_its_frame_big_enough_to_see(tmp_path, geo, no_portraits):
    ring = lambda w, s_, e, n: [[w, s_], [e, s_], [e, n], [w, n], [w, s_]]
    lakes = [dict(name="Lake Orrin", bbox=[12.2, 51.6, 12.9, 52.1], rings=[ring(12.2, 51.6, 12.9, 52.1), ring(12.4, 51.7, 12.5, 51.8)]),
             dict(name="Pond", bbox=[11.0, 50.5, 11.01, 50.51], rings=[ring(11.0, 50.5, 11.01, 50.51)]),        # too small
             dict(name="Far Lake", bbox=[40.0, 10.0, 41.0, 11.0], rings=[ring(40.0, 10.0, 41.0, 11.0)])]         # elsewhere
    (geo.folder / "lakes.json").write_text(json.dumps(dict(version="lakes-1", lakes=lakes)))
    geo._lakes = None
    got = geo.lakes([10.0, 50.0, 14.0, 53.0])
    assert got == lakes[0]["rings"]                                   # the island's ring comes too (cut out, even-odd)
    pl, _ = built(tmp_path, geo)
    mb = next(b for b in pl["beats"] if b["shot"] == "map_locate")
    assert mb["map"]["lakes"] == lakes[0]["rings"]                    # Varsel's map holds Lake Orrin, not the pond


def test_map_beat_gets_its_place_frame_and_context(tmp_path, geo, no_portraits):
    pl, _ = built(tmp_path, geo)
    mb = next(b for b in pl["beats"] if b["shot"] == "map_locate")
    p = mb["map"]["places"][0]
    assert (p["name"], p["how"]) == ("Varsel river", "part: Varsel")
    assert places.in_box(mb["map"]["frame"], p["lng"], p["lat"])
    assert "Varsel" not in [t["name"] for t in mb["map"]["context"]["towns"]]
    assert mb["illustration"] and pl["beats"][0]["map"]["frame"]


def test_map_beat_whose_place_isnt_found_becomes_a_headline(tmp_path, geo, no_portraits):
    s = script()
    mb = next(b for b in s["beats"] if b["shot"] == "map_locate")
    far = dict(EVENT, lat=-30.0, lng=150.0, location_name="Nowhere")      # "Varsel" is now too far to pin
    res = checked(s)
    n = narrated(res["beats"], tmp_path)
    pl = plan.build(res["beats"], n, s, far, g=geo, p7=packet())
    nb = next(b for b in pl["beats"] if b["n"] == mb["n"])
    assert nb["shot"] == "headline" and nb["swapped_from"] == "map_locate" and "map" not in nb
    assert pl["swaps"][-1]["why"] == "place not found: Varsel river"


def test_a_link_with_one_found_place_is_drawn_as_a_locate(tmp_path, geo, no_portraits):
    s = script()
    res = checked(s)
    beats = copy.deepcopy(res["beats"])
    mb = next(b for b in beats if b["shot"] == "map_locate")
    mb.update(shot="map_link", blanks=dict(places=["Varsel", "Atlantis"], label=""))
    n = narrated(beats, tmp_path)
    pl = plan.build(beats, n, s, EVENT, g=geo, p7=packet())
    out = next(b for b in pl["beats"] if b["n"] == mb["n"])
    assert out["shot"] == "map_locate" and [p["name"] for p in out["map"]["places"]] == ["Varsel"]
    assert out["map"]["missing"] == ["Atlantis"]


def test_captions_never_cross_a_cut_and_hold_at_most_4_words(tmp_path, geo, no_portraits):
    pl, n = built(tmp_path, geo)
    for c in pl["captions"] + pl["subtitles"]:
        assert 1 <= len(c["words"]) <= plan.CAPTION_WORDS and c["start"] < c["end"]
    beat_of = {i: b for i, b in enumerate(pl["beats"])}
    for c in pl["subtitles"]:
        b = beat_of[c["beat"]]
        assert b["start"] - 1 <= c["start"] and c["words"][-1]["end"] <= b["end"] + 1
    assert sum(len(c["words"]) for c in pl["subtitles"]) == len(n["words"])


def test_words_already_on_screen_get_no_burned_in_caption(tmp_path, geo, no_portraits):
    pl, n = built(tmp_path, geo)
    sides = next(i for i, b in enumerate(pl["beats"]) if b["shot"] == "sides")
    assert not [c for c in pl["captions"] if c["beat"] == sides]              # both sides' lines are on screen
    assert [c for c in pl["subtitles"] if c["beat"] == sides]                 # the captions file keeps them
    q = next(i for i, b in enumerate(pl["beats"]) if b["shot"] == "quote")
    shown = " ".join(w["w"] for c in pl["captions"] if c["beat"] == q for w in c["words"])
    assert "reopen" not in shown and "said" in shown


@pytest.mark.parametrize("field, spoken, hidden", [
    ("Road and rail traffic suspended", "The ministry said road and rail traffic were suspended after the attack.",
     "road and rail traffic were suspended"),                       # no stray "were suspended" caption left over
    ("Kerch Bridge: conflicting damage accounts", "Ukrainian strike on Kerch Bridge: Ukraine says a span collapsed.", ""),
    ("Guilty", "The court found him guilty.", ""),                  # a one-word field never hides a caption word
    ("Dmitry Peskov", "Kremlin spokesperson Dmitry Peskov said it.", "dmitry peskov"),
])
def test_read_on_screen(field, spoken, hidden):
    toks = plan._tokens(spoken)
    assert " ".join(toks[i] for i in sorted(plan.read_on_screen(field, toks))) == hidden


def test_credits_on_screen_name_the_site_and_links_go_to_the_post(tmp_path, geo, no_portraits):
    pl, _ = built(tmp_path, geo)
    assert not [c for c in pl["sources_card"]["credits"] if c.startswith("http")]
    assert pl["post"]["links"] and all(x.startswith("http") for x in pl["post"]["links"])
    assert "Narration voice by ElevenLabs" not in pl["sources_card"]["credits"]      # paced voice, no credit


def test_broll_props_portraits_and_illustration_tags(tmp_path, geo, no_portraits):
    s = script()
    s["beats"][5]["broll"] = {"kind": "prop", "name": "gavel"}                        # not drawn yet
    pl, _ = built(tmp_path, geo, s=s)
    by = {b["shot"]: b for b in pl["beats"]}
    assert by["timeline"]["broll"] == dict(kind="prop", name="train") and by["timeline"]["illustration"]
    assert by["quote"]["broll"]["skipped"] == "no approved portrait" and not by["quote"]["illustration"]
    gavel = pl["beats"][5]
    assert gavel["broll"]["skipped"] == "prop not drawn yet" and not gavel["illustration"]
    assert by["sources"]["illustration"] is False


def test_an_approved_portrait_reaches_the_plan_and_the_credits(tmp_path, geo, monkeypatch):
    folder = tmp_path / "people"
    folder.mkdir()
    monkeypatch.setattr(people, "FOLDER", folder)
    people._load.cache_clear()
    name = next(b for b in built(tmp_path, geo)[0]["beats"] if b["shot"] == "quote")["broll"]["name"]
    (folder / "face.png").write_bytes(b"png")
    (folder / "cut.png").write_bytes(b"png")
    (folder / "people.json").write_text(json.dumps({"version": "people-2", "people": [
        dict(name=name, file="face.png", author="A. Photographer", license="CC BY 4.0", approved=True,
             cutout="cut.png", face=[0.25, 0.1, 0.75, 0.5])]}))
    people._load.cache_clear()
    pl, _ = built(tmp_path, geo)
    q = next(b for b in pl["beats"] if b["shot"] == "quote")
    assert q["broll"]["portrait"]["file"] == str(folder / "face.png") and "skipped" not in q["broll"]
    assert q["broll"]["portrait"]["cutout"] == str(folder / "cut.png") and q["broll"]["portrait"]["face"] == [0.25, 0.1, 0.75, 0.5]
    assert any("cut out from a photo by A. Photographer" in c and "CC BY 4.0" in c for c in pl["sources_card"]["credits"])
    people._load.cache_clear()


def test_portrait_credits_take_one_line_per_photo_source():
    def pt(name, how="cut out from", author="The White House", lic="Public domain"):
        return dict(name=name, credit=f"Portrait of {name} …", photo=dict(how=how, author=author, license=lic))
    assert people.credits([pt("Ana Petrel"), pt("Ivo Brand"), pt("Ana Petrel"), pt("Mara Sund", author="C. Shutter", lic="CC0"),
                           pt("Lea Moss", how="redrawn from"), dict(name="Old", credit="Portrait of Old by X")]) == [
        "Portrait of Lea Moss redrawn from a photo by The White House, Public domain",
        "Portrait of Mara Sund cut out from a photo by C. Shutter, CC0",
        "Portrait of Old by X",                                                     # an older plan's portrait: as it was
        "Portraits of Ana Petrel and Ivo Brand cut out from photos by The White House, Public domain"]
    assert people.credits([pt("A"), pt("B"), pt("C")]) == ["Portraits of A, B and C cut out from photos by The White House, Public domain"]


def test_a_rerender_gets_todays_credits(tmp_path, monkeypatch):
    from stringer.video import make
    (tmp_path / "script.json").write_text(json.dumps({"title": "t", "credits": ["Media bias ratings by AllSides"]}))
    monkeypatch.setattr(make.story_file, "read", lambda d: ([], None))
    monkeypatch.setattr(make.fact_check, "read_checked", lambda d: {"event": {"url": "https://mts.test/e/1"}})
    monkeypatch.setattr(make.fact_check, "read_articles", lambda d: [])
    monkeypatch.setattr(make.sw, "contexts_for", lambda facts, arts: {})
    monkeypatch.setattr(make.sw, "packet", lambda sf, facts, ctx: {"two_sided": True, "letters": {"us_left": "A", "us_right": "B"}})
    script, _, _ = make.inputs(tmp_path)
    assert script["title"] == "t" and "Media bias ratings by AllSides (CC BY-NC 4.0)" in script["credits"]
    assert "Media bias ratings by AllSides" not in script["credits"]


def test_props_list_matches_the_drawing_code():
    js = (paths.CODE / "render" / "src" / "props.js").read_text(encoding="utf-8")
    body = js[js.index("const DRAW = {"):js.index("export const PROPS")]
    drawn = set(re.findall(r"^  '?([a-z ]+)'?: \(d\) =>", body, flags=re.M))
    assert drawn == set(plan.PROPS) and set(plan.PROPS) <= set(shots.catalog()["broll"]["props"])


# ---- step 6: the files ---------------------------------------------------------------------------------

def test_caption_files_use_each_format_s_time_stamps():
    subs = [dict(start=0, end=45, words=[dict(w="Floodwater"), dict(w="closed")]),
            dict(start=3600 * 30 + 1, end=3600 * 30 + 31, words=[dict(w="it.")])]
    v, s = files.vtt(subs, 30), files.srt(subs, 30)
    assert v.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nFloodwater closed\n")
    assert "01:00:00.033 --> 01:00:01.033\nit." in v
    assert s.startswith("1\n00:00:00,000 --> 00:00:01,500\nFloodwater closed\n\n2\n01:00:00,033 --> 01:00:01,033")


def test_file_problems_against_the_plan():
    p = dict(width=1080, height=1920, fps=30, frames=1800)
    good = dict(width=1080, height=1920, fps=30.0, video_codec="h264", audio_codec="aac", seconds=60.02)
    loud = dict(lufs=-14.2, true_peak=-1.6)
    assert files.problems(good, loud, p) == []
    bad = files.problems(dict(good, width=720, seconds=58.0, audio_codec="mp3"), dict(lufs=-20.0, true_peak=0.0), p)
    assert len(bad) == 5


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_finish_sets_loudness_and_writes_every_file(tmp_path):
    raw = tmp_path / "render.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1A2A86:s=108x192:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-af", "volume=0.05", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(raw)], check=True)
    pl = dict(version="plan-1", catalog="shots-2", width=108, height=192, fps=30, frames=60,
              beats=[dict(n=1, shot="hook", start=0, end=60, broll=dict(kind="none", name=""))],
              subtitles=[dict(start=0, end=30, words=[dict(w="Made-up")])], swaps=[], post=dict(links=[]),
              sources_card=dict(credits=["Made-up credit"]))
    rec = files.finish(raw, pl, tmp_path, dict(story="00000000-test", status="rendered"))
    assert rec["problems"] == [] and abs(rec["loudness"]["lufs"] - files.LUFS) <= files.LUFS_TOLERANCE
    assert rec["loudness"]["before_lufs"] < -20
    for f in ("video.mp4", "poster.jpg", "captions.vtt", "captions.srt", "render.json"):
        assert (tmp_path / f).exists()
    assert not raw.exists()


# ---- the evals (evals.py) ------------------------------------------------------------------------------

def test_evals_pass_on_a_good_plan(tmp_path, geo, no_portraits):
    pl, _ = built(tmp_path, geo)
    assert evals.on_screen(pl, packet()) == []
    assert evals.required(pl, script()) == []
    sy = evals.sync(pl)
    assert sy["problems"] == [] and sy["caption_ms"] == 0
    assert evals.maps(pl, EVENT, geo)["problems"] == []
    ch = evals.shot_choice(pl)
    assert ch["swaps"] == 0 and ch["triples"] == []


def test_required_parts_catch_what_is_missing(tmp_path, geo, no_portraits):
    pl, _ = built(tmp_path, geo)
    pl["sources_card"] = dict(pl["sources_card"], credits=[], ai_mark="",
                              sides=[dict(side="A", side_id="us_left", read=2)], elsewhere=0)
    pl["beats"][0]["blanks"] = dict(pl["beats"][0]["blanks"], title="x" * 70)
    probs = evals.required(pl, script())
    assert "no credit for Monitor the Situation" in probs and "the AI mark is missing" in probs
    assert "a side comes from AllSides ratings, but AllSides isn't credited" in probs
    assert any(p.startswith("the hook title is fully on screen only after") for p in probs)


def test_shot_choice_finds_three_in_a_row():
    pl = dict(beats=[dict(shot=x) for x in ["hook", "headline", "headline", "headline", "sources"]], swaps=[])
    assert evals.shot_choice(pl)["triples"] == [2]


def test_flashes_count_pairs_of_big_opposite_changes():
    calm = [100.0] * 90
    assert evals.flashes(calm) == 0
    strobe = [100.0 if (i // 3) % 2 else 200.0 for i in range(90)]      # 5 light/dark swaps a second
    assert evals.flashes(strobe) >= 4
    one_cut = [100.0] * 45 + [30.0] * 45
    assert evals.flashes(one_cut) <= 1


def test_broken_script_outcomes_and_confusion(tmp_path, geo, no_portraits):
    s, p7 = script(), packet()
    base = evals.baseline(s, p7, EVENT, geo, tmp_path)
    s2 = copy.deepcopy(s)
    s2["beats"][1]["shot"] = "hologram"
    assert evals.outcome(s2, p7, EVENT, base, geo, tmp_path)[0] == "swap"
    s3 = copy.deepcopy(s)
    s3["sources_card"] = None
    assert evals.outcome(s3, p7, EVENT, base, geo, tmp_path)[0] == "stop"
    m = evals.confusion([dict(expected="swap", actual="swap"), dict(expected="ok", actual="crash")])
    assert m["swap"]["swap"] == 1 and m["ok"]["crash"] == 1


def test_layout_bars_match_the_drawing_code():
    js = (paths.CODE / "render" / "src" / "layout.js").read_text(encoding="utf-8")
    safe = re.search(r"SAFE = \{left: (\d+), top: (\d+), right: (\d+), bottom: (\d+)\}", js)
    assert tuple(int(x) for x in safe.groups()) == evals.LAYOUT_SAFE
    assert int(re.search(r"MIN_PX = (\d+)", js).group(1)) == evals.LAYOUT_MIN_PX
