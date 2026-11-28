"""The custom animation (stringer/animation/, off by default): its switch, its model steps' fallbacks, beat
picking, cue timing, the box's lock and the window in the render plan. Made-up data only: the flooded-bridge
story of module 7's tests (Lorne, the Varsel river)."""
import http.server
import json
import shutil
import socketserver
import threading
import time
from pathlib import Path

import pytest

from stringer import animation
from stringer.animation import box, guide, library, steps
from stringer.video import make, places, plan, voice

import test_video as tv
from test_video import geo, no_portraits  # noqa: F401  (module 8's fixtures: an invented country, no portraits)

HAS_FFMPEG = tv.HAS_FFMPEG
needs_box = pytest.mark.skipif(not box.available(), reason="no node or headless Chrome for the box")

CODE = """function draw(k, p, cues) {
  k.ctx.fillStyle = k.pal.sky; k.ctx.fillRect(0, 0, k.W, k.H);
  k.ctx.fillStyle = k.pal.vermilion; k.ctx.fillRect(100 + 600 * p, 250, 80, 80);
  k.stipple(0.3);
}"""

BOARD = dict(beat="7", show="Floodwater rises under a long bridge, then a train stops before it.",
             agreed="The bridge was closed by floodwater and rail traffic halted.", avoid="No count of flooded homes.",
             cues=[dict(name="water", what="the water rises"), dict(name="stop", what="the train stops")],
             needs=[dict(thing="bridge", piece="bridge"), dict(thing="train", piece="train"),
                    dict(thing="floodwater", piece="none")])


class R:
    def __init__(self, text, usd=0.001):
        self.text, self.cost = text, {"total": usd}


def fake_complete(board=BOARD, code=CODE, cue_pick=None, log=None, block: threading.Event | None = None, seen=None):
    """A stand-in for models.complete: answers each step from made-up data, and counts the calls (and, given a
    list `seen`, keeps each call's messages and parameters)."""
    def complete(messages, name=None, step=None, **params):
        if log is not None:
            log.append(step)
        if seen is not None:
            seen.append(dict(step=step, messages=messages, params=params))
        if step == steps.STORYBOARD:
            return R(json.dumps(board)) if board is not None else R("no json here")
        if step == steps.DRAWING:
            if block is not None:
                block.wait(5)
            return R(json.dumps(dict(plan="a square slides across", code=code)), usd=0.05)
        if step == steps.CUES:
            props = params["response_format"]["json_schema"]["schema"]["properties"]
            toks = props[next(iter(props))]["enum"]
            pick = cue_pick or (lambda names, toks: {n: toks[min(len(toks) - 1, 3 + 4 * i)] for i, n in enumerate(names)})
            return R(json.dumps(pick(list(props), toks)))
        raise AssertionError(step)
    return complete


# ---- the switch ------------------------------------------------------------------------------------------

def test_the_switch_is_off_by_default_and_an_explicit_flag_wins(monkeypatch):
    monkeypatch.delenv("STRINGER_ANIMATION", raising=False)
    assert animation.enabled() is False
    monkeypatch.setenv("STRINGER_ANIMATION", "1")
    assert animation.enabled() is True and animation.enabled(False) is False
    monkeypatch.setenv("STRINGER_ANIMATION", "off")
    assert animation.enabled() is False and animation.enabled(True) is True


def test_the_window_look_is_card_unless_plate_is_chosen(monkeypatch):
    monkeypatch.delenv("STRINGER_ANIMATION_FRAME", raising=False)
    assert animation.frame_style() == "card"
    monkeypatch.setenv("STRINGER_ANIMATION_FRAME", "plate")
    assert animation.frame_style() == "plate" and animation.frame_style("nonsense") == "card"


# ---- the storyboard ----------------------------------------------------------------------------------------

def test_every_thing_is_matched_to_a_catalogue_name_through_the_schema():
    sch = guide.storyboard_schema(["2", "7"])["json_schema"]["schema"]
    piece = sch["properties"]["needs"]["items"]["properties"]["piece"]
    assert piece["enum"] == library.pieces() and library.pieces()[-1] == library.NONE


def test_the_storyboard_writes_what_to_avoid_before_what_it_shows():
    """A model writes JSON in the schema's order: deciding what is disputed first keeps it out of the scene."""
    order = list(guide.storyboard_schema(["7"])["json_schema"]["schema"]["properties"])
    assert order.index("beat") < order.index("agreed") < order.index("avoid") < order.index("show") < order.index("cues")
    assert "avoid binds you" in guide.draw_system([])
    assert "Never pick a moment of violence done to people" in guide.STORYBOARD_SYSTEM


def test_a_storyboard_takes_its_beats_sentence_and_known_claims_and_plain_unique_cue_names():
    beats = [beat(1, "hook", ["C1"]), beat(7, "headline", ["C1", "C99", "C1"])]
    sb = steps.clean_storyboard(dict(BOARD, beat="7",
                                     cues=[dict(name="Water rises!", what="a"), dict(name="water rises", what="b"),
                                           dict(name="c", what=""), dict(name="d", what="")],
                                     needs=[dict(thing="ark", piece="a made-up piece")]), ["C1", "C4"], beats)
    assert (sb["index"], sb["beat"], sb["line"]) == (1, 7, beats[1]["voice"])
    assert sb["claims"] == ["C1"]
    assert [c["name"] for c in sb["cues"]] == ["waterrises", "waterrisesx", "c"]      # at most 3, in order
    assert sb["needs"] == [dict(thing="ark", piece="none")]
    assert steps.missing(sb) == ["ark"]


def test_a_storyboard_that_never_parses_is_asked_once_more_then_falls_back(tmp_path):
    log = []
    beats = tv.checked()["beats"]
    sb, rec = steps.storyboard(tv.packet()["text"], ["C1"], beats, steps.candidates(beats)[0],
                               fake_complete(board=None, log=log), cache=tmp_path)
    assert sb is None and rec["calls"] == 2 and log == [steps.STORYBOARD] * 2 and rec["error"]


# ---- one JSON answer -----------------------------------------------------------------------------------

def test_an_answer_is_cached_under_its_request_so_it_is_never_paid_for_twice(tmp_path):
    log = []
    msgs = [{"role": "user", "content": "made-up"}]
    a, r1 = steps.ask_json(steps.STORYBOARD, msgs, guide.storyboard_schema(["7"]), fake_complete(log=log), cache=tmp_path)
    b, r2 = steps.ask_json(steps.STORYBOARD, msgs, guide.storyboard_schema(["7"]), fake_complete(log=log), cache=tmp_path)
    assert a == b and len(log) == 1 and r1["cached"] is False and r2["cached"] is True and r2["usd"] == 0


def test_a_failed_call_is_retried_and_a_budget_stop_is_never_swallowed(tmp_path):
    calls = []

    def flaky(messages, name=None, step=None, **p):
        calls.append(name)
        if len(calls) == 1:
            raise TimeoutError("slow")
        return R(json.dumps(BOARD))
    d, rec = steps.ask_json(steps.STORYBOARD, [{"role": "user", "content": "x"}], guide.storyboard_schema(["7"]), flaky,
                            cache=None)
    assert d == BOARD and rec["calls"] == 2 and calls[1].endswith("retry")

    class BudgetExceeded(Exception):
        pass

    def broke(messages, **p):
        raise BudgetExceeded("over the cap")
    with pytest.raises(BudgetExceeded):
        steps.ask_json(steps.STORYBOARD, [{"role": "user", "content": "x"}], guide.storyboard_schema(["7"]), broke, cache=None)


# ---- the beat --------------------------------------------------------------------------------------------

def beat(n, shot, claims, words=12, **kw):
    return dict(n=n, shot=shot, claims=claims, voice=" ".join(["word"] * words), **kw)


def test_the_candidates_are_the_beats_a_window_fits_under_and_long_enough_to_play_in():
    beats = [beat(1, "hook", ["C1"]), beat(2, "claim_vs_claim", ["C1"]), beat(3, "headline", ["C1"]),
             beat(4, "map_locate", ["C4"]), beat(5, "headline", ["C4"], 6), beat(6, "sources", [])]
    assert steps.candidates(beats) == ([2, 3], "")


@pytest.mark.parametrize("b, why", [
    (beat(1, "claim_vs_claim", ["C1"]), "no beat is a shot a window fits under"),
    (beat(1, "quote", ["C1"]), "no beat is a shot a window fits under"),
    (beat(1, "big_number", ["C1"], blanks=dict(value="340", compare_value="1,200")), "no beat is a shot"),
    (beat(1, "tally", ["C1"], blanks=dict(rows=[dict(label=str(i), value="1") for i in range(4)])), "no beat is a shot"),
    (beat(1, "headline", ["C1"], 6), "too short"),
])
def test_no_candidate_means_the_normal_shots_and_says_why(b, why):
    idx, said = steps.candidates([b])
    assert idx == [] and why in said


def test_the_storyboard_reads_the_candidates_sentences_and_must_pick_one_of_them(tmp_path):
    seen = []
    beats = tv.checked()["beats"]
    idx, _ = steps.candidates(beats)
    sb, rec = steps.storyboard(tv.packet()["text"], tv.packet()["claims"], beats, idx, fake_complete(seen=seen), cache=None)
    nums = [str(beats[i]["n"]) for i in idx]
    assert nums == ["2", "6", "7"]                    # the map and the two headlines of the made-up script
    call = seen[0]
    assert call["params"]["response_format"]["json_schema"]["schema"]["properties"]["beat"]["enum"] == nums
    user = call["messages"][-1]["content"]
    assert all(f"Beat {n} (" in user for n in nums) and "Beat 3 (" not in user and beats[idx[2]]["voice"] in user
    assert sb["beat"] == 7 and sb["line"] == beats[idx[2]]["voice"] and sb["claims"] == ["C1", "C4"]


# ---- cue words and times ---------------------------------------------------------------------------------

def test_cue_words_are_picked_from_the_beats_numbered_words(tmp_path):
    b = dict(voice="The bridge was shut by floodwater on Tuesday, and trains stopped.")
    sb = steps.clean_storyboard(BOARD, ["C1", "C4"])
    pick = lambda names, toks: {"water": "05 floodwater", "stop": "10 stopped."}       # noqa: E731
    placed, rec = steps.place_cues(sb, b, fake_complete(cue_pick=pick), cache=tmp_path)
    assert placed == {"water": 5, "stop": 10} and rec["calls"] == 1


def test_cue_words_that_never_fit_leave_the_cues_spread_evenly(tmp_path):
    sb = steps.clean_storyboard(BOARD, ["C1", "C4"])
    bad = lambda names, toks: {n: "nope" for n in names}                                # noqa: E731
    placed, rec = steps.place_cues(sb, dict(voice="one two three four five"), fake_complete(cue_pick=bad), cache=None)
    assert placed == {} and rec["calls"] == 2
    times = steps.cue_times(placed, ["water", "stop"], [], 0.0, 3.0)
    assert times == {"water": 0.333, "stop": 0.667}


def test_cue_times_are_each_words_start_as_a_share_of_the_beat():
    words = [dict(w=w, start=10.0 + i, end=10.5 + i) for i, w in enumerate("a b c d e".split())]
    assert steps.cue_times({"x": 1, "y": 4}, ["x", "y"], words, 10.0, 15.0) == {"x": 0.2, "y": 0.8}


def test_cues_are_spaced_in_order_inside_the_beat():
    out = steps.space_cues({"a": 0.5, "b": 0.5, "c": 0.97}, ["a", "b", "c"])
    assert out["a"] < out["b"] < out["c"] <= steps.CUE_HI
    assert out["b"] - out["a"] >= steps.CUE_GAP - 1e-9 and out["c"] - out["b"] >= steps.CUE_GAP - 1e-9
    early = steps.space_cues({"a": 0.0}, ["a"])
    assert early["a"] == steps.CUE_LO


# ---- the static check and the verdict --------------------------------------------------------------------

@pytest.mark.parametrize("code, bad", [
    ("function draw(k){ fetch('x') }", ["fetch"]),
    ("function draw(k){ const w = globalThis; }", ["globalThis"]),
    ("function draw(k){ Math.random() }", ["Math.random"]),
    ("function draw(k){ k.prop('document', 1, 2, 3) } // window.fetch is fine in a comment", []),
    ("function draw(k){ /* eval */ k.fx.flash(1, 2, 0.5) }", []),
])
def test_code_naming_a_way_out_is_refused_before_the_box(code, bad):
    assert box.refused(code) == bad


@pytest.mark.parametrize("rec, ok, why", [
    (dict(status="drawn", frames=90, ms_p95=4.0), True, ""),
    (dict(status="drawn", frames=90, ms_p95=40.0), False, "too slow"),
    (dict(status="drawn", frames=90, frame_errors=2, errors=["frame 3: boom"]), False, "threw an error"),
    (dict(status="drawn", frames=90, blank_frames=5), False, "blank"),
    (dict(status="drawn", frames=60, ms_p95=4.0), False, "only 60 of 90"),
    (dict(status="too slow", frames=20), False, "too slow"),
    (dict(status="timeout"), False, "ran out of time"),
])
def test_the_verdict_keeps_only_frames_fit_for_the_video(rec, ok, why):
    got_ok, got_why = box.verdict(rec, 90)
    assert got_ok is ok and why in got_why


def test_a_scene_standing_still_at_the_end_is_measured():
    assert box.still_share([0.01] * 6 + [0.0] * 4) == 1.0
    assert box.still_share([0.01] * 10) == 0.0


# ---- the job ---------------------------------------------------------------------------------------------

def narration(beats, tmp_path):
    return voice.narrate(beats, voice.Paced(audio=False), cache_dir=tmp_path / "voice")


def fake_box(seen):
    def draw(code, out_dir, *, frames, cues, **kw):
        seen.append(dict(code=code, frames=frames, cues=cues))
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return dict(status="drawn", frames=frames, ok=True, why="", refused=[], still=0.0, ms_p95=3.0)
    return draw


def test_a_job_draws_its_beats_exact_frames_with_cues_timed_to_the_voice(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(animation.box, "draw", fake_box(seen))
    beats = tv.checked()["beats"]
    narr = narration(beats, tmp_path)
    job = animation.start(tv.packet()["text"], tv.packet()["claims"], complete=fake_complete(), cache=None)
    job.place(beats)
    win = job.finish(narr, tmp_path / "out")
    i = win["beat"]
    assert beats[i]["shot"] == "headline" and set(beats[i]["claims"]) == {"C1", "C4"}     # beat 7 of the made-up script
    bt = narr["beats"][i]
    assert win["frames"] == plan.fr(bt["end"]) - plan.fr(bt["start"]) == seen[0]["frames"]
    assert list(win["cues"]) == ["water", "stop"] and steps.CUE_LO <= win["cues"]["water"] < win["cues"]["stop"] <= steps.CUE_HI
    rec = json.loads((tmp_path / "out" / "animation.json").read_text())
    assert rec["status"] == "drawn" and rec["fallback"] is None and rec["missing"] == ["floodwater"]
    assert rec["usd"] == pytest.approx(0.052) and (tmp_path / "out" / "anim" / "code.js").exists()


@pytest.mark.parametrize("kw, why", [
    (dict(board=None), "no storyboard"),
    (dict(code="function draw(k) { fetch('https://example.test') }"), "refused: names fetch"),
])
def test_a_job_that_fails_leaves_the_beat_its_normal_shot_and_says_why(tmp_path, kw, why):
    beats = tv.checked()["beats"]
    job = animation.start(tv.packet()["text"], tv.packet()["claims"], complete=fake_complete(**kw), cache=None)
    job.place(beats)
    assert job.finish(narration(beats, tmp_path), tmp_path / "out") is None
    rec = json.loads((tmp_path / "out" / "animation.json").read_text())
    assert rec["status"] == "fallback" and why in rec["fallback"]


def test_nothing_runs_or_is_paid_until_the_beats_are_given_or_with_no_beat_to_hold_a_window(tmp_path):
    log = []
    beats = tv.checked()["beats"]
    job = animation.start(tv.packet()["text"], tv.packet()["claims"], complete=fake_complete(log=log), cache=None)
    time.sleep(0.05)
    assert log == []
    assert job.finish(narration(beats, tmp_path), tmp_path / "a") is None
    assert "never given" in json.loads((tmp_path / "a" / "animation.json").read_text())["fallback"]
    plain = [b for b in beats if not steps.window_fits(b)]
    job = animation.start(tv.packet()["text"], tv.packet()["claims"], complete=fake_complete(log=log), cache=None)
    job.place(plain)
    assert job.finish(narration(plain, tmp_path), tmp_path / "b") is None
    rec = json.loads((tmp_path / "b" / "animation.json").read_text())
    assert log == [] and rec["usd"] == 0 and "no beat is a shot a window fits under" in rec["fallback"]


def test_a_drawing_not_ready_by_the_deadline_is_late(tmp_path):
    hold = threading.Event()
    beats = tv.checked()["beats"]
    job = animation.start(tv.packet()["text"], tv.packet()["claims"], complete=fake_complete(block=hold), cache=None)
    job.place(beats)
    t0 = time.time()
    assert job.finish(narration(beats, tmp_path), tmp_path / "out", deadline_s=0.2) is None
    hold.set()
    assert time.time() - t0 < 3
    assert json.loads((tmp_path / "out" / "animation.json").read_text())["fallback"].startswith("late")


# ---- the render plan -------------------------------------------------------------------------------------

def test_the_plan_puts_the_window_on_its_beat_in_place_of_the_prop(tmp_path, geo, no_portraits):
    s = tv.script()
    res = tv.checked(s)
    n = tv.narrated(res["beats"], tmp_path)
    off = plan.build(res["beats"], n, s, tv.EVENT, swaps=res["swaps"], g=geo, p7=tv.packet())
    i = next(k for k, b in enumerate(off["beats"]) if b["shot"] == "timeline")          # it carries a prop
    win = dict(beat=i, frames=off["beats"][i]["frames"], dir="anim", cues={"a": 0.3}, frame="plate")
    on = plan.build(res["beats"], n, s, tv.EVENT, swaps=res["swaps"], g=geo, p7=tv.packet(), anim=win)
    b = on["beats"][i]
    assert b["anim"] == dict(dir="anim", frames=win["frames"], frame="plate", cues={"a": 0.3})
    assert b["broll"]["kind"] == "none" and b["broll"]["was"]["kind"] == "prop" and b["illustration"] is True
    assert on["animation"] == dict(beat=b["n"], frame="plate")
    # everything else is as it was
    assert [x for k, x in enumerate(on["beats"]) if k != i] == [x for k, x in enumerate(off["beats"]) if k != i]
    assert on["captions"] == off["captions"] and "animation" not in off


def test_a_window_whose_length_differs_from_its_beat_is_left_out(tmp_path, geo, no_portraits):
    s = tv.script()
    res = tv.checked(s)
    n = tv.narrated(res["beats"], tmp_path)
    pl = plan.build(res["beats"], n, s, tv.EVENT, swaps=res["swaps"], g=geo, p7=tv.packet(),
                    anim=dict(beat=1, frames=3, dir="anim", cues={}))
    assert "anim" not in pl["beats"][1] and "frames" in pl["animation"]["skipped"]


# ---- module 8 with the switch on and off ------------------------------------------------------------------

@pytest.fixture
def story(tmp_path, monkeypatch, geo, no_portraits):
    """make.prepare's inputs from made-up data (no story folder on disk)."""
    s = tv.script()
    monkeypatch.setattr(make, "inputs", lambda d: (s, {"event": tv.EVENT}, tv.packet()))
    monkeypatch.setattr(places, "default", lambda: geo)
    return tmp_path / "story"


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_switch_off_writes_the_same_plan_as_before(tmp_path, story, monkeypatch):
    monkeypatch.delenv("STRINGER_ANIMATION", raising=False)
    rec = make.prepare(story, voice.Paced(audio=True), tmp_path / "off", voice_cache=tmp_path / "v", direction=False)
    assert "animation" not in rec["steps"] and not (tmp_path / "off" / "animation.json").exists()
    pl = json.loads((tmp_path / "off" / "plan.json").read_text())
    assert "animation" not in pl and not any("anim" in b for b in pl["beats"])


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_switch_on_gives_one_beat_its_window_and_keeps_the_script(tmp_path, story, monkeypatch):
    seen = []
    monkeypatch.setattr(animation.box, "draw", fake_box(seen))
    off = make.prepare(story, voice.Paced(audio=True), tmp_path / "off", voice_cache=tmp_path / "v", direction=False)
    job = animation.start(tv.packet()["text"], tv.packet()["claims"], complete=fake_complete(), cache=None)
    on = make.prepare(story, voice.Paced(audio=True), tmp_path / "on", voice_cache=tmp_path / "v", direction=False,
                      anim=job)
    assert on["steps"]["animation"]["status"] == "drawn"
    a = json.loads((tmp_path / "off" / "plan.json").read_text())
    b = json.loads((tmp_path / "on" / "plan.json").read_text())
    animated = [k for k, x in enumerate(b["beats"]) if x.get("anim")]
    assert len(animated) == 1 and b["beats"][animated[0]]["anim"]["frames"] == seen[0]["frames"]
    # the same words, voice and timing: only the animated beat differs
    assert a["captions"] == b["captions"] and a["frames"] == b["frames"]
    assert [x for k, x in enumerate(b["beats"]) if k not in animated] == [x for k, x in enumerate(a["beats"]) if k not in animated]


# ---- the box (needs node and headless Chrome) -----------------------------------------------------------

@needs_box
def test_the_box_draws_every_frame_at_the_windows_size(tmp_path):
    rec = box.draw(CODE, tmp_path, frames=12, cues={"a": 0.5})
    assert rec["ok"], rec["why"]
    assert rec["frames"] == 12 and rec["sandbox"] is True and rec["blocked"] == []
    jpgs = sorted(tmp_path.glob("f*.jpg"))
    assert len(jpgs) == 12
    data = jpgs[0].read_bytes()
    assert data[:2] == b"\xff\xd8"                                   # a JPEG; its size is 1080 x 720:
    i = data.index(b"\xff\xc0")
    assert (int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")) == (720, 1080)


@needs_box
def test_the_box_reaches_nothing_outside_and_draws_no_words(tmp_path):
    """Hostile drawing code sent straight to the box (past the word check): every way out it tries finds
    nothing, a local server it aims at hears nothing, and its words never reach a frame."""
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{srv.server_address[1]}"
    code = """
const tried = [];
const probe = (name, f) => { try { if (f()) tried.push(name); } catch (e) {} };
probe('fetch', () => typeof fetch === 'function' && (fetch('http://HOST/fetch'), true));
probe('XMLHttpRequest', () => { const x = new XMLHttpRequest(); x.open('GET', 'http://HOST/xhr'); x.send(); return true; });
probe('WebSocket', () => !!new WebSocket('ws://HOST/ws'));
probe('importScripts', () => (importScripts('http://HOST/imp.js'), true));
probe('Worker', () => !!new Worker('http://HOST/w.js'));
probe('postMessage', () => (postMessage({type: 'done'}), true));
probe('the global', () => !!(globalThis || self || window));
probe('navigator', () => !!navigator.userAgent);
probe('Function', () => (0, (() => {}).constructor)('return 1')() === 1);
probe('eval', () => (0, eval)('1') === 1);
try { import('http://HOST/mod.js').catch(() => {}); } catch (e) {}
function draw(k, p, cues) {
  if (tried.length) throw new Error('reached: ' + tried.join(', '));
  if (k.ctx.canvas.ownerDocument) throw new Error('reached the page');
  k.ctx.fillStyle = '#fff'; k.ctx.fillRect(0, 0, k.W, k.H);
  k.ctx.fillStyle = '#000'; k.ctx.font = '120px serif'; k.ctx.fillText('WORDS', 100, 300);
}""".replace("HOST", host)
    job = dict(frames=6, cues={}, scale=box.SCALE, quality=0.9, limit_ms=box.limit_ms(), timeout_s=60)
    try:
        rec = box.run_box(dict(job, code=code), tmp_path / "hostile", 60)
        time.sleep(0.3)
    finally:
        srv.shutdown()
    assert rec["status"] == "drawn" and rec["frame_errors"] == 0, rec["errors"]
    assert hits == [] and rec["text_calls"] >= 6
    # the same drawing without its words gives the same frames: the word was never drawn
    plain = box.run_box(dict(job, code=code.replace("k.ctx.fillText('WORDS', 100, 300);", "")), tmp_path / "plain", 60)
    assert plain["status"] == "drawn"
    assert (tmp_path / "hostile" / "f0005.jpg").read_bytes() == (tmp_path / "plain" / "f0005.jpg").read_bytes()


@needs_box
def test_a_frame_that_never_ends_is_stopped(tmp_path):
    rec = box.draw("function draw(k, p) { if (p > 0.4) { for (;;) {} } k.ctx.fillRect(0, 0, 9, 9); }", tmp_path,
                   frames=10, cues={}, timeout_s=30)
    assert not rec["ok"] and rec["status"] != "drawn"


@needs_box
def test_a_government_building_takes_columns_as_a_count_true_or_false(tmp_path):
    """A model once passed columns: true (the kit wants a count), which drew no columns and left a dark block."""
    def frame(opt):
        code = ("function draw(k, p) { k.scene.ground({ground: 500, kind: 'plaza', time: 0}); "
                f"k.scene.government(450, 500, 460, {{columns: {opt}}}); }}")
        rec = box.draw(code, tmp_path / opt, frames=2, cues={})
        assert rec["ok"], rec["why"]
        return (tmp_path / opt / "f0000.jpg").read_bytes()
    six = frame("6")
    assert frame("true") == six and frame("undefined") == six
    assert frame("false") != six
