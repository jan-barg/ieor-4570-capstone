"""The same-story filter (module 2) and its eval. Made-up events, outlets and articles only."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from stringer import models, same_story, tracing
from stringer.evals import runner
from stringer.evals.same_story_eval import SameStoryEval, metrics

START = "2030-03-02T10:00:00Z"
EVENT = {"id": "11111111-aaaa-bbbb-cccc-000000000001", "title": "Dam Bursts Flooding Three Valley Towns",
         "summary": "A dam in the Varo valley burst, flooding three towns.", "start": START,
         "location_name": "Varo valley", "url": "https://example.org/e1"}


def art(i, title, text="", hours=2.0, outlet="dailyx", own=False, prec="time"):
    t = datetime(2030, 3, 2, 10, tzinfo=timezone.utc).timestamp() + hours * 3600
    return {"id": f"a_{i}", "url": f"https://{outlet}.example/{i}", "outlet": outlet, "outlet_name": "Daily X",
            "published_at": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date_precision": prec, "title": title, "text": text, "own_source": own, "labels": {"outlet_name": "Daily X"}}


class Scripted:
    """A fake model: answers each article from a {headline word: verdict} script, and can drop ids."""

    def __init__(self, rules, drop=(), fail_first=False):
        self.rules, self.drop, self.calls, self.fail_first = rules, set(drop), [], fail_first

    def __call__(self, messages, name=None, max_tokens=None, **kw):
        self.calls.append(name)
        if self.fail_first and len(self.calls) == 1:
            return NS(text="sorry, no JSON here")
        body = messages[0]["content"][1]["text"]
        rows = [json.loads(line) for line in body.splitlines() if line.startswith("{")]
        out = []
        for r in rows:
            if r["id"] in self.drop:
                continue
            v = next((v for w, v in self.rules.items() if w in r["headline"].lower()), "different")
            out.append({"id": r["id"], "verdict": v, "reason": "scripted"})
        self.drop = set()                       # the retry gets everything
        return NS(text="```json\n" + json.dumps({"verdicts": out}) + "\n```")


def test_outlet_name_is_cut_from_headline_and_text():
    names = ["Daily X"]
    assert same_story.strip_outlet("Dam bursts in Varo - Daily X", names) == "Dam bursts in Varo"
    assert same_story.strip_outlet("Dam bursts | DAILY X", names) == "Dam bursts"
    assert same_story.strip_outlet("Rescue - day two", names) == "Rescue - day two"
    assert same_story.mask_names("Daily X reports the dam broke", names) == "[outlet] reports the dam broke"
    p = same_story.article_packet(art(1, "Dam bursts - Daily X", "Daily X has learned the dam broke."),
                                  same_story.parse_ts(START), "A1")
    assert "Daily X" not in json.dumps(p) and p["when"] == "published 2.0 hours after the event started"


def test_publish_time_is_told_relative_to_the_start():
    s = same_story.parse_ts(START)
    assert same_story.when("2030-03-02T07:30:00Z", "time", s) == "published 2.5 hours before the event started"
    assert same_story.when("2030-03-06T10:00:00Z", "time", s) == "published 4.0 days after the event started"
    assert same_story.when("2030-03-02T00:00:00Z", "day", s) == "published the same day the event started, time unknown"
    assert same_story.when(None, None, s) == "published: date unknown"


def test_parse_accepts_fences_aliases_and_reports_problems():
    text = '```json\n{"verdicts":[{"id":"A1","verdict":"Same story","reason":"r"},' \
           '{"id":"A2","verdict":"follow-up"},{"id":"A9","verdict":"same"},{"id":"A3","verdict":"maybe"}]}\n```'
    got, problems = same_story.parse_verdicts(text, ["A1", "A2", "A3"])
    assert got["A1"]["verdict"] == "same" and got["A2"]["verdict"] == "follow_up" and "A3" not in got
    assert any("A9" in p for p in problems) and any("bad verdict" in p for p in problems)
    assert same_story.parse_verdicts("no json", ["A1"]) == ({}, ["answer is not JSON"])


def test_filter_story_batches_rules_and_retries():
    arts = [art(1, "Dam bursts in Varo"), art(2, "Rescuers search flooded towns"),
            art(3, "Inquiry ordered into dam collapse", hours=150), art(4, "Football final tonight"),
            art(5, "Cited by the event", own=True), {"id": "a_6", "url": "https://x.example/6", "title": "", "text": ""}]
    fake = Scripted({"dam bursts": "same", "rescuers": "same", "inquiry": "follow_up"}, drop={"A2"})
    out = same_story.filter_story(EVENT, arts, fake, batch=2)
    v = out["verdicts"]
    assert v["a_5"] == {"verdict": "same", "reason": "the event cites it", "by": "rule"}
    assert v["a_6"]["verdict"] is None and v["a_6"]["reason"] == "nothing to judge"
    assert v["a_1"]["verdict"] == "same" and v["a_3"]["verdict"] == "follow_up" and v["a_4"]["verdict"] == "different"
    assert v["a_2"]["verdict"] == "same"                   # dropped once, came back on the retry
    assert fake.calls.count("same_story") == 2 and fake.calls.count("same_story retry") == 1
    assert out["counts"] == {"same": 3, "follow_up": 1, "different": 1, "None": 1} and out["flags"] == []


def test_article_with_no_answer_after_retry_is_flagged():
    class Silent:
        def __call__(self, messages, **kw):
            return NS(text='{"verdicts": []}')
    out = same_story.filter_story(EVENT, [art(1, "Dam bursts")], Silent())
    assert out["verdicts"]["a_1"]["verdict"] is None and out["no_verdict"] == ["a_1"]
    assert out["flags"] == ["1 articles got no verdict"]


def test_side_drop_check_flags_a_lopsided_filter():
    lens = {"sides": [{"side_id": "left_x", "outlet_ids": ["l1"]}, {"side_id": "right_x", "outlet_ids": ["r1"]}]}
    arts = [art(i, f"dam story {i}", outlet="l1") for i in range(5)] + \
           [art(10 + i, f"other news {i}", outlet="r1") for i in range(5)]
    out = same_story.filter_story(EVENT, arts, Scripted({"dam": "same"}), lens=lens)
    assert out["sides"]["right_x"] == {"judged": 5, "different": 5, "share": 1.0}
    assert any(f.startswith("side drop: right_x lost 5 of 5") for f in out["flags"])


def test_compare_events_uses_the_same_call():
    other = dict(EVENT, id="22222222-aaaa", title="Dam Inquiry Opens", start="2030-03-09T10:00:00Z")
    out = same_story.compare_events(EVENT, [other], Scripted({"inquiry": "follow_up"}))
    assert out["verdicts"]["22222222-aaaa"]["verdict"] == "follow_up"
    p = same_story.event_packet(other, same_story.parse_ts(START), "E1")
    assert p["when"] == "started 7.0 days after the first event started"


def test_keyword_baseline():
    out = same_story.keyword_story(EVENT, [art(1, "Dam bursts, towns flooded in valley"), art(2, "Football final")])
    assert out["verdicts"]["a_1"]["verdict"] == "same" and out["verdicts"]["a_2"]["verdict"] == "different"


def test_metrics_treat_different_as_the_positive_class():
    pairs = [["x1", "different", "different"], ["x2", "different", "same"], ["x3", "same", "different"],
             ["x4", "same", "same"], ["x5", "follow_up", "follow_up"], ["x6", "same", "none"]]
    m = metrics(pairs)
    assert m["drop_precision"] == 0.5 and m["drop_recall"] == 0.5 and m["drop_f1"] == 0.5
    assert m["accuracy"] == pytest.approx(0.5) and m["no_verdict"] == 1 and m["follow_up_f1"] == 1.0
    assert m["confusion"]["different->same"] == 1


# ---- the eval end to end, on a made-up frozen story -------------------------------------------

@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "_TRACER", tracing.Tracer(log_dir=tmp_path / "log", enable_langfuse=False))
    stories = tmp_path / "stories"
    other = dict(EVENT, id="22222222-aaaa-bbbb-cccc-000000000002", title="Dam Inquiry Opens",
                 start="2030-03-09T10:00:00Z")
    for ev, arts in ((EVENT, [art(1, "Dam bursts in Varo"), art(2, "Football final tonight"),
                              art(3, "Dam inquiry ordered", hours=150)]), (other, [art(9, "Dam inquiry opens")])):
        d = stories / ev["id"]
        d.mkdir(parents=True)
        (d / "gather.json").write_text(json.dumps({"event": ev, "lens": {"kind": "none", "sides": []}}))
        (d / "articles.jsonl").write_text("\n".join(json.dumps(a) for a in arts) + "\n")
    sample = {"splits": {"tune": ["11111111", "22222222"], "holdout": []}, "items": [
        {"id": "a:11111111:a_1", "kind": "article", "story": "11111111"},
        {"id": "a:11111111:a_2", "kind": "article", "story": "11111111"},
        {"id": "a:11111111:a_3", "kind": "article", "story": "11111111"},
        {"id": "e:11111111:22222222", "kind": "event_pair", "story": "11111111", "other": {"short": "22222222"}}]}
    labels = {"version": "test", "labels": {"a:11111111:a_1": {"label": "same"},
                                            "a:11111111:a_2": {"label": "different", "source": "claude"},
                                            "a:11111111:a_3": {"label": "follow_up"},
                                            "e:11111111:22222222": {"label": "follow_up"}}}
    (tmp_path / "sample.json").write_text(json.dumps(sample))
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    return SameStoryEval(stories_dir=stories, sample=tmp_path / "sample.json", labels=tmp_path / "labels.json")


def fake_complete(rules):
    s = Scripted(rules)

    def call(*, model, messages, trace_id=None, name=None, metadata=None, **params):
        text = s(messages, name=name).text
        usage = dict(prompt=500, input_uncached=500, cached=0, cache_write=0, output=60, reasoning=0, total=560)
        return models.Result(text=text, model=model, usage=usage, cost=models.cost_of(model, usage), latency_s=0.01)
    call.script = s
    return call


def test_eval_runs_whole_pools_and_scores_the_labeled_ones(world, tmp_path):
    items = world.load(split="tune")
    assert [i.id for i in items] == ["articles:11111111", "events:11111111"]   # unsampled story left out
    assert len(SameStoryEval(all_stories=True, stories_dir=world.stories_dir, sample=world.sample_path).load()) == 3
    fake = fake_complete({"dam bursts": "same", "inquiry": "follow_up"})
    rec = runner.run_eval(world, model="haiku-5-5", out_dir=tmp_path / "evals", complete_fn=fake)
    s = rec["summary"]
    assert rec["status"] == "done" and s["labeled"] == 3 and s["accuracy"] == 1.0
    assert s["drop_precision"] == 1.0 and s["drop_recall"] == 1.0 and s["events_accuracy"] == 1.0
    assert s["stories"] == {"11111111": 1.0}
    assert s["labeled_jan"] == 2 and s["accuracy_jan"] == 1.0 and s["drop_f1_jan"] is None   # Jan's two: no "different"
    est = runner.estimate(world, model="haiku-5-5", out_dir=tmp_path / "evals")
    assert est["calls"] == 2 and est["cached_calls"] == 2          # everything already in the cache


def test_keyword_baseline_runs_through_the_runner_for_free(world, tmp_path):
    rec = runner.run_eval(world, model="code:keywords", out_dir=tmp_path / "evals", complete_fn=None)
    assert rec["cost_usd"] == 0 and rec["summary"]["labeled"] == 3
    assert rec["summary"]["follow_up_f1"] in (0.0, None)            # it never says follow_up


def test_broken_json_is_read_object_by_object():
    text = ('{"verdicts": [\n{"id": "A1", "verdict": "same", "reason": "the dam"},\n'
            '{"id": "A2", "verdict": "different", "a football match"},\n'
            '{"id": "A3", "verdict": "follow_up", "reason": "the \\"inquiry\\" later"}\n]}')
    got, problems = same_story.parse_verdicts(text, ["A1", "A2", "A3"])
    assert {k: v["verdict"] for k, v in got.items()} == {"A1": "same", "A2": "different", "A3": "follow_up"}
    assert any("not valid JSON" in p for p in problems)


def test_retry_is_a_different_call():
    ev = {"title": "Dam bursts", "start": "2026-01-01T00:00:00Z"}
    pk = [{"id": "A1", "headline": "x"}]
    assert same_story.messages_for(ev, pk) != same_story.messages_for(ev, pk, retry=True)
