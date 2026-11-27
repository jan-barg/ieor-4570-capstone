"""The script writer's eval, end to end through the runner. The made-up flood story and a fake model; no keys."""
import json
import re

import pytest

from stringer import models, shots, tracing
from stringer.evals import runner, script_eval as se, steps
from test_script_writer import ARTICLES, FACTS, answer, good_beats, pk, story

SID = "00000000"
GOOD = {shots.voice(b["say"]) for b in good_beats()}


@pytest.fixture(autouse=True)
def quiet_tracer(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "_TRACER", tracing.Tracer(log_dir=tmp_path / "log", enable_langfuse=False))


def made_up(tmp_path, live=False):
    root = tmp_path / "stories"
    for sid in [SID] + (["11111111"] if live else []):
        d = root / f"{sid}-flood"
        d.mkdir(parents=True)
        sf = story()
        (d / "checked_story_file.json").write_text(json.dumps(sf), encoding="utf-8")
        (d / "story_file.json").write_text(json.dumps(sf), encoding="utf-8")
        (d / "facts.jsonl").write_text("".join(json.dumps(f) + "\n" for f in FACTS), encoding="utf-8")
        (d / "articles.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ARTICLES.values()), encoding="utf-8")
    sheets = tmp_path / "sheets.json"
    sheets.write_text(json.dumps({"stories": [dict(
        short_id=SID, n=1, title="Flood closes bridge", who_says_so=True,
        facts=["Floodwater closed the Varsel river bridge.", "Officials give different counts of flooded homes."],
        note="The flooded-home counts are each side's own figures and should be attributed.")]}), encoding="utf-8")
    return se.ScriptEval(stories_dir=root, sheets=sheets)


class FakeModel:
    """The writer gives the good script; the line check backs the good script's lines and nothing else
    (so every planted line fails); the judges find everything."""

    def __init__(self):
        self.kinds = []

    def __call__(self, *, model, messages, trace_id=None, name=None, metadata=None, **params):
        kind = params["response_format"]["json_schema"]["name"]
        self.kinds.append(kind)
        body = messages[-1]["content"]
        if kind == "script":
            text = json.dumps(answer())
        elif kind == "line_check":
            out = []
            for n, line in re.findall(r"^L(\d+) · .*\nLine: (.*)$", body, flags=re.M):
                ok = shots.voice(line.replace("“", "").replace("”", "")) in GOOD or line in GOOD
                out.append(dict(id=f"L{n}", why="x", verdict="backed" if ok else "not backed",
                                problem="none" if ok else "number", claims_not_backing=[], alone=[]))
            text = json.dumps({"lines": out})
        elif kind == "wording":
            text = json.dumps({"flags": []})
        elif kind == "coverage":
            text = json.dumps({"results": [dict(id=m, found=True, cards=["L1"]) for m in re.findall(r"^(M\d+):", body, re.M)]})
        elif kind == "who_says":
            text = json.dumps({"points": [dict(point="flooded-home counts", mentioned=True, attributed=True, lines=["L3"])]})
        else:
            raise AssertionError(kind)
        n_in = runner.count_tokens(models.spec(model)["litellm"], messages)
        usage = dict(prompt=n_in, input_uncached=n_in, cached=0, cache_write=0, output=300, reasoning=0, total=n_in + 300)
        return models.Result(text=text, model=model, usage=usage, cost=models.cost_of(model, usage), latency_s=0.5)


def test_registered():
    assert "script" in steps.names() and isinstance(steps.get("script"), se.ScriptEval)


def test_splits_put_unsheeted_stories_in_live(tmp_path):
    step = made_up(tmp_path, live=True)
    assert [(i.story, i.split) for i in step.load(split="all")] == [(SID, "tune"), ("11111111", "live")]
    assert [i.story for i in step.load(split="live")] == ["11111111"]
    assert step.load(split="holdout") == []


def test_eval_runs_the_script_and_judges_with_no_plants_by_default(tmp_path):
    step = made_up(tmp_path)
    fake = FakeModel()
    rec = runner.run_eval(step, model="sonnet-5-5", cap_usd=2.0, out_dir=tmp_path / "evals", complete_fn=fake,
                          split="all", use_cache=False)
    assert rec["status"] == "done", rec["items_detail"][0]["error"]
    # the line check and the wording check run side by side, so either may come first; no planted-mistakes call
    assert fake.kinds[0] == "script" and sorted(fake.kinds[1:3]) == ["line_check", "wording"]
    assert fake.kinds[3:] == ["coverage", "who_says"]
    s = rec["summary"]
    assert s["first_clean"] == 1.0 and s["videos"] == 1.0 and s["failures"] == 0
    assert s["rules_final_ok"] == 1.0 and s["on_screen_final_ok"] == 1.0
    assert s["lines_backed_first"] == 1.0 and s["cut_beats"] == 0 and s["loaded_final"] == 0
    assert s["coverage"] == 1.0 and s["who_says"] == 1.0
    assert s["plants"] == 0 and "plants_caught" not in step.headline
    assert s["words"] == 151 and s["step_cost"] > 0 and s["step_seconds"] == 1.5     # writer, line check, wording
    assert step.mistakes(rec) == []
    est = runner.estimate(step, model="sonnet-5-5", split="all", out_dir=tmp_path / "nocache")
    assert est["calls"] == 8 and est["est_usd"] > 0          # writer, fix, line, words (x2), coverage, who-says


def test_plants_still_run_when_asked(tmp_path):
    step = made_up(tmp_path)
    step.plants = True
    fake = FakeModel()
    rec = runner.run_eval(step, model="sonnet-5-5", cap_usd=2.0, out_dir=tmp_path / "evals", complete_fn=fake,
                          split="all", use_cache=False)
    assert fake.kinds[0] == "script" and sorted(fake.kinds[1:3]) == ["line_check", "wording"]
    assert fake.kinds[3:] == ["coverage", "who_says", "line_check"]
    s = rec["summary"]
    assert s["plants"] == 2 and s["plants_caught"] == 1.0 and s["plants_reached"] == 0
    assert sum(s["confusion"].values()) == 2


def test_plants_change_one_thing_each():
    p = pk()
    from stringer import script_writer as sw
    beats = [sw.normalize_beat(b, p) for b in good_beats()]
    num = se.plant(beats[2], "number", p, beats)
    assert "340" not in num["say"] and "432" in num["say"]
    drop = se.plant(beats[2], "speaker dropped", p, beats)
    assert "Interior Ministry" not in drop["say"] and "[left 340.]" in drop["say"]
    hedge = se.plant(beats[2], "hedge dropped", p, beats)
    assert "about" not in hedge["say"] and "1,200" in hedge["say"]
    wrong = se.plant(beats[0], "wrong claims", p, beats)
    assert wrong["claims"] != beats[0]["claims"] and not set(wrong["claims"]) & {"C1"}
    half = se.plant(beats[2], "half a conflict", p, beats)
    assert half["shot"] == "headline" and half["claims"] == ["C2"] and "says" not in half["say"]
    assert se.plant(beats[0], "hedge dropped", p, beats) is None
    picked = se.plants_for(dict(_final_beats=beats), p, SID)
    assert len(picked) == 2 and len({x["beat"] for x in picked}) == 2
    assert picked == se.plants_for(dict(_final_beats=beats), p, SID)          # the same every run
