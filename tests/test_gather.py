"""Gather (module 1) tests. No network: Tavily and the Guardian are faked at the HTTP layer,
so caching, retries, credit counting and the budget stop are exercised for real."""
import datetime as dt
import json

import pytest

from stringer.events import Event
from stringer.gather import clients, merge, plan, queries, run, sides, store
from stringer.gather.merge import Hit
from stringer.outlets import OutletTable

UTC = dt.timezone.utc
START = dt.datetime(2026, 11, 17, 0, 25, tzinfo=UTC)


@pytest.fixture(scope="module")
def t():
    return OutletTable.load()


def x_post_id(when: dt.datetime) -> int:
    """A made-up X post id for a given time (X ids carry their creation time)."""
    return ((int(when.timestamp() * 1000) - plan.X_EPOCH_MS) << 22) | 5


X_POST = f"https://x.com/AP/status/{x_post_id(START + dt.timedelta(minutes=6))}"


def event(sources=None):
    """An invented test event (no Monitor the Situation data in this repo)."""
    return Event(id="00000000-0000-4000-8000-000000000001", title="Strike Brings Down Road Span of Kerch Bridge",
                 summary="A road span of the Kerch bridge was destroyed in a Ukrainian strike; traffic was halted.",
                 category="conflict", subtype="strike", severity="3", confidence="45", country="Ukraine",
                 location_name="Kerch", lat="45.3", lng="36.5", report_count="46", start=START,
                 created_at="2026-11-17T00:30:00Z", url="https://example.invalid/events/1",
                 source_urls=sources if sources is not None else [
                     "https://kyivindependent.com/bridge-collapses/",
                     "https://www.reuters.com/world/europe/kerch-1/",
                     "https://www.theguardian.com/world/2026/nov/17/kerch-bridge",
                     X_POST])


# --- merge rules --------------------------------------------------------------
def test_url_key_drops_tracking_keeps_article_ids():
    assert merge.url_key("https://www.bbc.co.uk/news/articles/c1?at_medium=RSS&at_campaign=rss") == \
        "bbc.co.uk/news/articles/c1"
    assert merge.url_key("https://example.com/story.php?id=42&utm_source=x") == "example.com/story.php?id=42"
    assert merge.url_key("https://cnn.com/a/b/") == merge.url_key("https://www.cnn.com/a/b")


def test_dates_and_roles():
    d, p = merge.parse_date("Tue, 17 Nov 2026 00:40:27 GMT")
    assert p == "time" and merge.role_for(d, p, START) == ("new_coverage", [])
    d, p = merge.parse_date("Mon, 16 Nov 2026 23:59:00 GMT")
    assert merge.role_for(d, p, START)[0] == "background"
    d, p = merge.parse_date("2026-11-17T00:00:00Z")
    assert p == "day" and merge.role_for(d, p, START) == ("unclear", ["day_only_on_start_day"])
    d, p = merge.parse_date("2026-11-18T00:00:00Z")
    assert merge.role_for(d, p, START) == ("new_coverage", ["day_only"])
    assert merge.role_for(None, None, START) == ("unclear", ["no_date"])


def test_text_status_threshold():
    assert merge.text_status("x" * 1500) == "full"
    assert merge.text_status("x" * 1499) == "snippet_only"
    assert merge.text_status("") == "none"


def test_merge_by_url_guardian_text_wins_and_noise_dropped(t):
    g_url = "https://www.theguardian.com/world/2026/nov/17/kerch-bridge"
    hits = [
        Hit(g_url + "?CMP=share", "tavily_search", "q1_core", 2, "Kerch", "short snippet",
            "Tue, 17 Nov 2026 09:00:00 GMT"),
        Hit(g_url, "guardian_api", "g1_title", 1, "Kerch bridge hit", "G" * 5000, "2026-11-17T07:42:26Z",
            {"type": "article", "section": "world"}),
        Hit("https://www.theguardian.com/world/live/2026/nov/17/ukraine-live", "guardian_api", "g1_title", 3,
            "live", "L" * 9000, "2026-11-17T08:00:00Z", {"type": "liveblog"}),
        Hit("https://www.foxnews.com/world/kerch", "tavily_search", "q3a", 1, "Fox", "F" * 3000,
            "Tue, 17 Nov 2026 03:00:00 GMT"),
        Hit("https://www.foxnews.com/world/kerch?utm_source=x", "tavily_search", "q1_core", 5, "Fox", "F" * 200,
            "Tue, 17 Nov 2026 03:00:00 GMT"),
    ]
    arts, dropped = merge.merge(hits, START, [g_url], t)
    assert dropped["guardian_noise"] == 1
    by = {a["outlet"]: a for a in arts}
    assert len(arts) == 2
    g = by["theguardian"]
    assert g["text_via"] == "guardian_api" and g["text_status"] == "full" and g["own_source"]
    assert g["published_at"] == "2026-11-17T07:42:26Z" and g["role"] == "new_coverage"
    fox = by["foxnews"]
    assert fox["text_chars"] == 3000 and len(fox["found_by"]) == 2
    assert fox["labels"]["us_lean"] == "Right" and fox["id"].startswith("a_")


def test_x_post_time_from_id():
    # build an id the way X does: (ms since X's epoch) << 22, plus worker/sequence bits
    when = dt.datetime(2026, 11, 17, 0, 31, 5, tzinfo=UTC)
    ms = int(when.timestamp() * 1000) - plan.X_EPOCH_MS
    post_id = (ms << 22) | 0b1011_0000_1111
    assert plan.x_post_time(f"https://x.com/AP/status/{post_id}") == "2026-11-17T00:31:05Z"
    assert plan.x_post_time("https://twitter.com/AP/statuses/" + str(post_id) + "?s=20").startswith("2026-11-17")
    assert plan.x_post_time("https://x.com/AP") is None


# --- the query plan -----------------------------------------------------------
def lens_for(t, kind, a=None, b=None):
    sl = sides.side_lists(t)
    return sides.Lens(kind, [sl[x] for x in (a, b) if x])


def qs_for(ev, lens):
    return queries.template_queries(ev, lens)


def test_us_lens_plan(t):
    ev, lens = event(), lens_for(t, "us", "us_left", "us_right")
    ss = plan.build_searches(ev, lens, qs_for(ev, lens), t, "2026-11-19")
    ids = [s.qid for s in ss]
    assert ids[:2] == ["q1_core", "q2_reworded"] and "q5_right_tail" in ids and ids[-1] == "q9_background"
    for s in ss:
        p = s.params
        assert p["include_domains"] and p["include_raw_content"] and p["search_depth"] == "basic"
        assert "include_domains_mode" not in p
        if p["topic"] == "general":
            assert p["include_published_date"]
    core = ss[0].params
    assert core["topic"] == "news" and len(core["include_domains"]) <= 300
    assert core["start_date"] == "2026-11-17" and core["end_date"] == "2026-11-19"
    sides_ = [s for s in ss if s.qid.startswith("q3")]
    assert all(s.params["topic"] == "news" for s in sides_)       # US outlets: news mode
    tail = next(s for s in ss if s.qid == "q5_right_tail").params
    assert tail["topic"] == "general" and "foxnews.com" not in tail["include_domains"]
    assert "nypost.com" not in tail["include_domains"] and "dailywire.com" in tail["include_domains"]
    bg = ss[-1].params
    assert bg["end_date"] == "2026-11-16" and "start_date" not in bg and bg["topic"] == "general"


def test_world_lens_general_mode_and_mixed_side_split(t):
    ev = event()
    lens = lens_for(t, "world", "ukraine", "russia")
    ss = plan.build_searches(ev, lens, qs_for(ev, lens), t, None)
    side = [s for s in ss if s.qid.startswith("q3")]
    assert [s.params["topic"] for s in side] == ["general", "general"]
    assert "q5_right_tail" not in [s.qid for s in ss] and "end_date" not in ss[0].params
    lens = lens_for(t, "world", "iran", "us_gulf")
    side = [s for s in plan.build_searches(ev, lens, qs_for(ev, lens), t, None) if s.qid.startswith("q3")]
    assert sorted(s.params["topic"] for s in side) == ["general", "general", "news"]


def test_no_divide_plan_has_no_side_searches(t):
    ev = event()
    lens = sides.Lens("none", [])
    assert [s.qid for s in plan.build_searches(ev, lens, qs_for(ev, lens), t, None)] == \
        ["q1_core", "q2_reworded", "q9_background"]


def test_template_queries_nonempty(t):
    ev = event()
    q = queries.template_queries(ev, lens_for(t, "world", "ukraine", "russia"))
    assert q.core == ev.title and q.reworded and q.background and set(q.sides) == {"ukraine", "russia"}
    assert "erbia" not in queries.entities("Protests in Serbia grew. Serbia's students marched.")


# --- clients, retries, budget -------------------------------------------------
def tavily_result(i, day="Tue, 17 Nov 2026 03:00:00 GMT", host="www.foxnews.com"):
    return {"url": f"https://{host}/world/story-{i}", "title": f"Story {i}", "content": "c",
            "raw_content": "R" * 2000, "published_date": day}


class FakeTavily(clients.Tavily):
    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script = script      # list of result counts per /search call, in order
        self.calls = []

    def _post(self, path, body, timeout=90):
        self.calls.append((path, body))
        if path == "/extract":
            res = [{"url": u, "title": "own", "raw_content": "E" * 3000,
                    "published_date": "Tue, 17 Nov 2026 01:00:00 GMT"} for u in body["urls"] if "reuters" not in u]
            failed = [{"url": u, "error": "403"} for u in body["urls"] if "reuters" in u]
            return 200, {"results": res, "failed_results": failed, "usage": {"credits": 1}}, 0.01
        n = self.script.pop(0) if self.script else 8
        return 200, {"results": [tavily_result(f"{len(self.calls)}-{i}") for i in range(n)],
                     "usage": {"credits": 1}}, 0.01


class FakeGuardian(clients.Guardian):
    def get(self, path, params, save_as, trace_id=None):
        if path == "search":
            res = [{"webUrl": f"https://www.theguardian.com/world/2026/nov/17/g{i}", "type": "article",
                    "sectionId": "world", "webTitle": f"G{i}",
                    "fields": {"bodyText": "B" * 6000, "firstPublicationDate": "2026-11-17T08:00:00Z"}}
                   for i in range(3)]
            return {"status": 200, "response": {"results": res}, "cached": False}
        return {"status": 200, "cached": False, "response": {"content": {
            "webUrl": "https://www.theguardian.com/" + path, "type": "article", "sectionId": "world",
            "fields": {"bodyText": "O" * 4000, "firstPublicationDate": "2026-11-17T06:00:00Z"}}}}


def test_thin_results_retry_then_stop(tmp_path):
    tv = FakeTavily([3, 8], raw_dir=str(tmp_path))
    s = plan.Search("q1_core", {"query": "x", "topic": "news", "include_domains": ["cnn.com"]})
    rec, log = plan.run_search(tv, event(), s, wait_s=0)
    assert [a["results"] for a in log.attempts] == [3, 8] and log.used_attempt == 1
    tv2 = FakeTavily([1, 2, 4], raw_dir=str(tmp_path / "b"))
    rec, log = plan.run_search(tv2, event(), s, wait_s=0)
    assert len(log.attempts) == 3 and log.results == 4
    # saved responses are reused: no new calls, no credits
    spent = tv.ledger.spent
    rec, log = plan.run_search(tv, event(), s, wait_s=0)
    assert tv.ledger.spent == spent and all(a["cached"] for a in log.attempts)


def test_budget_stops_before_overspending(tmp_path):
    tv = FakeTavily([], raw_dir=str(tmp_path), ledger=clients.CreditLedger(limit=2))
    tv.search("e/a", query="x")
    tv.search("e/b", query="x")
    with pytest.raises(clients.BudgetExceeded):
        tv.search("e/c", query="x")
    assert tv.ledger.spent == 2


def test_gather_event_end_to_end(tmp_path, monkeypatch, t):
    from stringer import paths
    monkeypatch.setattr(paths, "STORIES", tmp_path / "stories")
    monkeypatch.setenv("STRINGER_NO_LANGFUSE", "1")
    monkeypatch.setattr(run, "tracer", lambda: __import__("stringer.tracing", fromlist=["Tracer"]).Tracer(
        log_dir=str(tmp_path / "runs"), enable_langfuse=False))
    tv = FakeTavily([], raw_dir=str(tmp_path / "raw"))
    g = FakeGuardian(raw_dir=str(tmp_path / "raw"))
    cache = store.ArticleCache(root=str(tmp_path / "cache"))
    ev = event()
    lens = lens_for(t, "world", "ukraine", "russia")
    meta = run.gather_event(ev, lens, t, tv, g, writer="template", cache=cache, wait_s=0)
    rows = [json.loads(x) for x in (tmp_path / "stories" / ev.id / "articles.jsonl").read_text().splitlines()]
    assert meta["counts"]["articles"] == len(rows) > 10
    keys = {"id", "url", "outlet", "published_at", "labels", "text_status", "text", "role", "own_source"}
    assert all(keys <= set(r) for r in rows)
    own = {r["url_key"]: r for r in rows if r["own_source"]}
    assert own["kyivindependent.com/bridge-collapses"]["text_via"] == "tavily_extract"
    assert own["reuters.com/world/europe/kerch-1"]["text_status"] == "none"       # blocked, still listed
    assert own["theguardian.com/world/2026/nov/17/kerch-bridge"]["text_via"] == "guardian_api"
    xp = own[merge.url_key(X_POST)]
    assert xp["outlet"] == "ap" and xp["labels"]["matched_by"] == "x_account" and xp["date_source"] == "mts_source"
    assert meta["credits_this_run"] == len(tv.calls)       # every fake call reports 1 credit
    # a second story citing the same link: the cache has it in full, so Extract is skipped
    ev2 = event(["https://kyivindependent.com/bridge-collapses/"])
    ev2.id = "00000000-0000-4000-8000-000000000002"
    meta2 = run.gather_event(ev2, lens, t, tv, g, writer="template", cache=cache, wait_s=0)
    assert meta2["log"]["own"]["skipped_cached"] == 1 and meta2["log"]["own"]["credits"] is None


def test_coverage_report_on_fake_freeze(tmp_path, monkeypatch, t):
    from stringer import paths
    from stringer.tracing import Tracer
    from scripts import coverage_report
    monkeypatch.setattr(paths, "STORIES", tmp_path / "stories")
    monkeypatch.setattr(coverage_report, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(run, "tracer", lambda: Tracer(log_dir=str(tmp_path / "runs"), enable_langfuse=False))
    tv = FakeTavily([], raw_dir=str(tmp_path / "raw"))
    g = FakeGuardian(raw_dir=str(tmp_path / "raw"))
    run.gather_event(event(), lens_for(t, "world", "ukraine", "russia"), t, tv, g, writer="template",
                     cache=store.ArticleCache(root=str(tmp_path / "cache")), wait_s=0)
    coverage_report.main([])
    rep = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    ev = rep["events"][0]
    assert ev["lens"] == "world" and set(ev["sides"]) == {"ukraine", "russia"}
    assert ev["all"]["articles"] > 10 and rep["gather"][0]["credits"] == len(tv.calls)
    assert any((tmp_path / "reports").glob("*.md"))
