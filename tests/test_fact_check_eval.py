"""The fact check eval, end to end through the runner. A made-up story and a fake model; no keys."""
import json
import re

import pytest

from stringer import models, tracing
from stringer.evals import fact_check_eval as fce
from stringer.evals import runner
from test_fact_check import ARTICLES, FACTS, Table, claim, story

SID = "00000000"


@pytest.fixture(autouse=True)
def quiet_tracer(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "_TRACER", tracing.Tracer(log_dir=tmp_path / "log", enable_langfuse=False))


def made_up(tmp_path, monkeypatch):
    d = tmp_path / "stories" / f"{SID}-storm"
    d.mkdir(parents=True)
    claims = [claim(f"C{i}", f"Filler claim {i} about the bridge.", "a_w1#1", "a_s1#1") for i in range(1, 25)]
    claims[0] = claim("C1", "The bridge closed on Friday.", "a_n1#1", "a_s1#1")
    claims[2] = claim("C3", "Ferries will carry drivers.", "a_s1#2", who="the city")
    claims[21] = claim("C22", "Engineers expect repairs to take three months.", "a_n1#2")
    sf = story(claims)
    (d / "story_file.json").write_text(json.dumps(sf), encoding="utf-8")
    (d / "facts.jsonl").write_text("".join(json.dumps(f) + "\n" for f in FACTS), encoding="utf-8")
    (d / "articles.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ARTICLES.values()), encoding="utf-8")
    sheets = tmp_path / "sheets.json"
    sheets.write_text(json.dumps({"stories": [{"short_id": SID, "n": 1, "title": "Storm shuts bridge"}]}), encoding="utf-8")
    key = tmp_path / "planted.json"
    recs = [
        dict(id="P001", story=SID, copy="judge", kind="actors reversed", made_by="Claude", claim="C22",
             set=dict(claim="Engineers expect PLANTED repairs to take three months."), original={}, note="x"),
        dict(id="P002", story=SID, copy="code", kind="no card", made_by="script", claim="C3", set=dict(facts=[]),
             original={}, expect={}),
    ]
    key.write_text(json.dumps(dict(version="planted-test", records=recs)), encoding="utf-8")
    ws = tmp_path / "whosays.json"
    ws.write_text(json.dumps(dict(version="ws-test", stories={SID: dict(as_fact=["C1"], field_only=[], says_who=["C3"])})),
                  encoding="utf-8")
    monkeypatch.setattr(fce, "WHOSAYS", ws)
    step = fce.FactCheckEval(stories_dir=d.parent, sheets=sheets, key=key)
    step._table = Table()
    return step


class FakeJudge:
    """Backs every claim except a planted one; counts the calls it really gets."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *, model, messages, trace_id=None, name=None, metadata=None, **params):
        self.calls += 1
        body = messages[-1]["content"]
        ids = params["response_format"]["json_schema"]["schema"]["properties"]["claims"]["items"]["properties"]["id"]["enum"]
        blocks = dict(re.findall(r"^(C\d+) · .*\nClaim: (.*)$", body, flags=re.M))
        out = []
        for cid in ids:
            bad = "PLANTED" in blocks.get(cid, "")
            out.append(dict(id=cid, verdict="not backed" if bad else "backed", problem="who did what" if bad else "none",
                            speaker="", bad_cards=[], bad_translations=[], against_event=False, why="planted" if bad else ""))
        n_in = runner.count_tokens(models.spec(model)["litellm"], messages)
        usage = dict(prompt=n_in, input_uncached=n_in, cached=0, cache_write=0, output=50, reasoning=0, total=n_in + 50)
        return models.Result(text=json.dumps({"claims": out}), model=model, usage=usage,
                             cost=models.cost_of(model, usage), latency_s=0.01)


def test_eval_runs_three_copies_and_reuses_unchanged_groups(tmp_path, monkeypatch):
    step = made_up(tmp_path, monkeypatch)
    fake = FakeJudge()
    rec = runner.run_eval(step, model="haiku-5-5", cap_usd=1.0, out_dir=tmp_path / "evals", complete_fn=fake,
                          split="all", use_cache=False)
    assert rec["status"] == "done", rec["items_detail"][0]["error"]
    # two groups (C1-C20, C21-C24) in the clean copy; only the second changes in the planted copy
    assert fake.calls == 3
    s = rec["summary"]
    assert s["planted_right"] == 1.0 and s["critical_misses"] == 0
    assert s["code_right"] == 1.0
    assert s["claims"] == 24 and s["unchecked"] == 0
    assert s["same_twice"] == 1.0                         # C21, C23, C24 judged twice, same outcome
    assert s["confusion"] == {"dropped->dropped": 1}
    assert s["by_kind"]["actors reversed"]["right"] == 1
    assert s["says_who_kept"] == 1.0
    assert s["step_cost"] > 0
    # estimates plan the same calls the run makes
    est = runner.estimate(step, model="haiku-5-5", split="all", out_dir=tmp_path / "nocache")
    assert est["calls"] == 3


def test_eval_lists_misses_and_real_drops(tmp_path, monkeypatch):
    step = made_up(tmp_path, monkeypatch)

    class Lenient(FakeJudge):                              # backs everything, planted or not
        def __call__(self, **kw):
            kw["messages"] = [dict(m, content=m["content"].replace("PLANTED", "")) for m in kw["messages"]]
            return super().__call__(**kw)

    rec = runner.run_eval(step, model="haiku-5-5", cap_usd=1.0, out_dir=tmp_path / "evals", complete_fn=Lenient(),
                          split="all", use_cache=False)
    s = rec["summary"]
    assert s["planted_right"] == 0.0 and s["critical_misses"] == 1    # one outlet's claim, repeated as the outlet's
    rows = step.mistakes(rec)
    assert [r["kind"] for r in rows] == ["planted: actors reversed (critical)"]
    assert rows[0]["gold"] == "dropped" and rows[0]["pred"] == "named the outlet"
