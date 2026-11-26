"""The follow-up round for short sides (stringer/balance.py) and live events (events.from_live).
All made up: invented outlets on .example domains and an invented event; Tavily is faked at the
HTTP layer, so saving, credit counting and merging run for real."""
import datetime as dt
import json

import pytest

from stringer import balance, pick
from stringer.events import from_live
from stringer.gather import clients
from stringer.outlets import Outlet, OutletTable

COLS = ["outlet_id", "name", "domains", "x_handles", "kind", "country", "us_lean", "us_lean_opinion",
        "opinion_paths", "allsides_name", "allsides_date", "allsides_confidence", "reliability",
        "reliability_domain", "state_media", "state_media_entity", "state_media_year", "wikidata", "notes"]
START = "2026-11-20T08:00:00Z"


def outlet(oid, country):
    r = {c: "" for c in COLS}
    r.update(outlet_id=oid, name=oid.capitalize(), domains=f"{oid}.example", kind="news", country=country,
             reliability="0.7")
    return Outlet.from_row(r)


@pytest.fixture()
def t():
    return OutletTable([outlet(o, c) for o, c in (("northa", "NA"), ("northb", "NA"), ("northc", "NA"),
                                                     ("southa", "SA"), ("southb", "SA"), ("bystander", "GB"))])


LENS = {"kind": "world", "sides": [{"side_id": "north", "label": "Northland outlets", "outlet_ids": ["northa", "northb", "northc"]},
                                   {"side_id": "south", "label": "Southland outlets", "outlet_ids": ["southa", "southb"]}],
        "local": None}


def art(i, outlet, status="full", verdict="same", role="new_coverage", rank=1):
    text = "T" * (3000 if status == "full" else 140)
    url = f"https://{outlet}.example/news/{i}"
    return {"id": f"a_{i}", "url": url, "url_key": f"{outlet}.example/news/{i}", "outlet": outlet,
            "labels": {"kind": "news", "section": "news"}, "text_status": status, "text_chars": len(text),
            "text": text, "role": role, "verdict": verdict, "found_by": ["tavily_search:q3b"], "best_rank": rank,
            "own_source": False}


def meta():
    return {"event": {"id": "00000000-0000-4000-8000-0000000000bb", "title": "Northland and Southland Trade Blame",
                      "summary": "Invented.", "category": "conflict", "subtype": "strike", "severity": "3",
                      "confidence": "55", "country": "Northland", "location_name": "", "lat": "", "lng": "",
                      "report_count": "9", "start": START, "created_at": START, "url": "https://example.invalid/e",
                      "source_urls": []},
            "lens": LENS, "window": {"start_date": "2026-11-20", "end_date": "2026-11-22"},
            "queries": {"core": "Northland and Southland Trade Blame", "reworded": "northland southland blame",
                        "sides": {"south": "Le Sud accuse le Nord"}}}


def pool():
    return [art(1, "northa"), art(2, "northb"), art(3, "northc"),                 # north: 3 usable
            art(4, "southa", status="snippet_only"),                                # south: on topic, no text
            art(5, "southb", status="snippet_only", verdict="different"),           # off topic: never read
            art(6, "southb", status="none", role="background")]                     # background: never read


class FakeTavily(clients.Tavily):
    def __init__(self, extract_text=3000, search_results=0, **kw):
        super().__init__(**kw)
        self.extract_text, self.search_results, self.calls = extract_text, search_results, []

    def _post(self, path, body, timeout=90):
        self.calls.append((path, body))
        if path == "/extract":
            res = [{"url": u, "raw_content": "X" * self.extract_text} for u in body["urls"]] if self.extract_text else []
            return 200, {"results": res, "failed_results": [], "usage": {"credits": 1}}, 0.01
        res = [{"url": f"https://southb.example/news/new{i}", "title": f"New {i}", "content": "c",
                "raw_content": "N" * 2500, "published_date": "Fri, 20 Nov 2026 12:00:00 GMT"}
               for i in range(self.search_results)]
        return 200, {"results": res, "usage": {"credits": 1}}, 0.01


def test_short_sides_lists_only_pages_worth_reading():
    s = balance.short_sides(LENS, pool())
    assert [x["side"]["side_id"] for x in s] == ["south"]
    assert s[0]["usable"] == 0 and [a["id"] for a in s[0]["to_read"]] == ["a_4"]


def test_estimate_counts_reading_and_a_search(t):
    e = balance.estimate(LENS, pool(), t)
    assert e["read_credits"] == 1 and e["search_credits_max"] == 1 and e["credits_max"] == 2


def test_second_query_switches_language_or_wording():
    q = meta()["queries"]
    assert balance.second_query(q, "south") == q["core"]          # first search was in French: try the title
    assert balance.second_query(q, "north") == q["reworded"]      # first search used the title: try other words


def test_reading_the_pages_can_fill_a_side_without_a_search(t, tmp_path):
    arts = pool() + [art(7, "southb", status="snippet_only")]
    tv = FakeTavily(raw_dir=str(tmp_path))
    rec = balance.followup(meta(), arts, t, tv)
    assert rec["before"] == {"north": 3, "south": 0} and rec["after"] == {"north": 3, "south": 2}
    assert [c[0] for c in tv.calls] == ["/extract"] and rec["credits"] == 1
    a4 = next(a for a in arts if a["id"] == "a_4")
    assert a4["text_status"] == "full" and "tavily_extract:q6_followup_read" in a4["found_by"]
    assert next(a for a in arts if a["id"] == "a_5")["text_status"] == "snippet_only"   # off topic, left alone
    p = pick.pick(arts, LENS)
    assert not any("empty side" in f for f in p["flags"])


def test_still_short_after_reading_searches_once(t, tmp_path):
    arts = pool()
    tv = FakeTavily(extract_text=0, search_results=2, raw_dir=str(tmp_path))
    rec = balance.followup(meta(), arts, t, tv)
    paths_called = [c[0] for c in tv.calls]
    assert paths_called == ["/extract", "/search"]
    body = tv.calls[1][1]
    assert body["query"] == meta()["queries"]["core"] and body["include_domains"] == ["southa.example", "southb.example"]
    assert body["max_results"] == balance.SEARCH_MAX and body["end_date"] == "2026-11-22"
    assert len(rec["added"]) == 2 and rec["credits"] == 2
    new = [a for a in arts if a["id"] in rec["added"]]
    assert all(a["verdict"] is None for a in new)          # no filter given: not judged, as Gather leaves them
    assert rec["after"]["south"] == 1                     # one new outlet (two articles from southb)
    # a second run reuses the saved responses: no new calls, no credits
    tv2 = FakeTavily(extract_text=0, search_results=2, raw_dir=str(tmp_path))
    rec2 = balance.followup(meta(), pool(), t, tv2)
    assert tv2.calls == [] and rec2["credits"] == 0


def test_a_side_with_enough_is_left_alone(t, tmp_path):
    arts = [art(1, "northa"), art(2, "northb"), art(4, "southa"), art(8, "southb")]
    tv = FakeTavily(raw_dir=str(tmp_path))
    rec = balance.followup(meta(), arts, t, tv)
    assert tv.calls == [] and rec["log"] == [] and rec["credits"] == 0


def test_live_event_start_is_its_first_source():
    e = {"id": "00000000-0000-4000-8000-0000000000cc", "title": "Invented Live Event", "summary": "s",
         "category": "political", "subtype": "statement", "severity": 2, "confidence": 85, "country": "Northland",
         "location_name": "Capital", "lat": 1.5, "lng": 2, "report_count": 9, "created_at": "2026-11-23T23:40:00.000Z",
         "url": "https://example.invalid/e2",
         "sources": [{"url": "https://northa.example/2", "published_at": "2026-11-24T00:24:09.000Z"},
                     {"url": "https://x.com/someone/status/1", "published_at": "2026-11-23T23:35:50.000Z"}]}
    ev = from_live(e)
    assert ev.start == dt.datetime(2026, 11, 23, 23, 35, 50, tzinfo=dt.timezone.utc)
    assert ev.source_urls == ["https://northa.example/2", "https://x.com/someone/status/1"]
    assert ev.severity == "2" and ev.lat == "1.5"
    e.pop("sources")
    assert from_live(e).start == dt.datetime(2026, 11, 23, 23, 40, tzinfo=dt.timezone.utc)
    json.dumps(ev.as_dict())
