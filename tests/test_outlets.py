"""Module 3 unit tests (map, module 3, "Success and evals", designed Nov 24). No network.

Tests 1-6 check the lookup rules on known links; 7 checks the real outlets.csv;
8 is a golden set copied by hand from the three sources (not from outlets.csv)."""
import csv
import re

import pytest

from stringer import paths
from stringer.outlets import KINDS, LEANS, STATE_LEVELS, OutletTable


@pytest.fixture(scope="module")
def t():
    return OutletTable.load()


def oid(t, url):
    return t.label(url)["outlet_id"]


# 1. Known links ---------------------------------------------------------------
@pytest.mark.parametrize("url,expected", [
    ("https://edition.cnn.com/2026/11/05/politics/senate-vote/index.html", "cnn"),
    ("https://abcnews.go.com/Politics/story?id=1", "abcnews"),
    ("https://abcnews.com/Politics/story?id=1", "abcnews"),
    ("https://www.bbc.co.uk/news/articles/abc", "bbc"),
    ("https://www.bbc.com/news/articles/abc", "bbc"),
    ("https://news.sky.com/story/x-123", "skynews"),
    ("https://english.elpais.com/international/2026-10-28/x.html", "elpais"),
    ("https://g1.globo.com/politica/noticia/2026/10/25/x.ghtml", "g1"),
    ("https://www1.folha.uol.com.br/poder/2026/10/x.shtml", "folha"),
    ("https://www.msnbc.com/top-stories/x", "msnow"),
    ("https://www.ms.now/news/x", "msnow"),
    ("https://m.cnn.com/2026/11/05/x", "cnn"),
    ("https://amp.theguardian.com/world/2026/nov/04/x", "theguardian"),
    ("https://www.foxnews.com/politics/x", "foxnews"),
])
def test_known_links(t, url, expected):
    assert oid(t, url) == expected


def test_folha_and_g1_are_different_outlets(t):
    assert oid(t, "https://g1.globo.com/x/y") != oid(t, "https://folha.uol.com.br/x/y")


def test_path_scoped_ratings(t):
    news_hour = t.label("https://www.pbs.org/newshour/politics/x")
    other_pbs = t.label("https://www.pbs.org/wgbh/nova/article/x/")
    assert news_hour["us_lean"] == "Lean Left" and news_hour["allsides_name"] == "PBS NewsHour"
    assert other_pbs["outlet_id"] == "pbs" and other_pbs["us_lean"] is None
    nr_news = t.label("https://www.nationalreview.com/news/x/")
    nr_other = t.label("https://www.nationalreview.com/2026/11/x/")
    assert (nr_news["section"], nr_news["us_lean"]) == ("news", "Lean Right")
    assert (nr_other["section"], nr_other["us_lean"]) == ("opinion", "Right")


# 2. Look-alikes stay unrated --------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://notfoxnews.com/politics/x",
    "https://foxnews.com.co/politics/x",
    "https://reuters.com.evil.net/world/x",
    "https://bbc-news.com/news/x",
])
def test_lookalikes_unrated(t, url):
    lab = t.label(url)
    assert lab["outlet_id"] is None and not lab["rated"] and lab["us_lean"] is None
    assert lab["reliability"] is None


# 3. Platforms stay unrated ----------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://www.google.com/url?rct=j&url=https://www.foxnews.com/x",
    "https://www.facebook.com/somepage/posts/1",
    "https://www.youtube.com/watch?v=abc",
    "https://news.yahoo.com/some-ap-story-123.html",
])
def test_platforms_unrated(t, url):
    lab = t.label(url)
    assert lab["kind"] == "platform" and not lab["rated"]
    assert lab["us_lean"] is None and lab["reliability"] is None


# 4. X posts -------------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://x.com/Reuters/status/1", "https://twitter.com/reuters/status/1"])
def test_outlet_x_account_takes_outlet_labels(t, url):
    lab = t.label(url)
    assert lab["outlet_id"] == "reuters" and lab["matched_by"] == "x_account" and lab["rated"]
    assert lab["reliability"] == t.by_id["reuters"].reliability


@pytest.mark.parametrize("url,handle", [("https://x.com/CENTCOM/status/1", "CENTCOM"),
                                        ("https://x.com/sentdefender/status/1", "sentdefender")])
def test_other_x_accounts_flagged_unrated(t, url, handle):
    lab = t.label(url)
    assert lab["outlet_id"] is None and lab["kind"] == "x_account" and lab["x_account"] == handle
    assert not lab["rated"] and lab["us_lean"] is None


# 5. Opinion -------------------------------------------------------------------
def test_opinion_by_path(t):
    nyt = t.label("https://www.nytimes.com/2026/11/05/opinion/democrats-midterms.html")
    assert nyt["section"] == "opinion" and nyt["us_lean"] == "Left"
    assert nyt["us_lean_basis"] == "opinion rating"
    assert t.label("https://www.theguardian.com/commentisfree/2026/nov/05/x")["section"] == "opinion"
    assert t.label("https://www.nbcnews.com/think/opinion/x-ncna1")["section"] == "opinion"
    assert t.label("https://www.nbcnews.com/think/x-ncna1")["section"] == "opinion"
    assert t.label("https://thehill.com/homenews/analysis/12345-x/")["section"] == "news"
    headline = t.label("https://www.cnn.com/2026/11/05/politics/opinion-poll-shows-lead/index.html")
    assert headline["section"] == "news"


# 6. Unknown outlets: unrated, never a guess -----------------------------------
def test_unknown_outlet_unrated(t):
    lab = t.label("https://www.some-local-paper-nobody-rated.com/2026/11/05/x")
    assert lab["outlet_id"] is None and lab["matched_by"] == "none"
    assert lab["us_lean"] is None and lab["reliability"] is None and not lab["rated"]


# 7. File checks on the real outlets.csv ---------------------------------------
def test_no_domain_or_handle_twice(t):
    doms, handles = {}, {}
    for o in t.outlets:
        for d in o.domains:
            assert d not in doms, f"{d} in {doms.get(d)} and {o.outlet_id}"
            doms[d] = o.outlet_id
        for h in o.x_handles:
            assert h.lower() not in handles, f"@{h} in {handles.get(h.lower())} and {o.outlet_id}"
            handles[h.lower()] = o.outlet_id
    assert len({o.outlet_id for o in t.outlets}) == len(t.outlets)


def test_allowed_values(t):
    for o in t.outlets:
        assert o.kind in KINDS, o.outlet_id
        assert o.us_lean in LEANS and o.us_lean_opinion in LEANS, o.outlet_id
        assert o.state_media == "" or o.state_media in STATE_LEVELS, o.outlet_id
        assert o.country == "" or re.fullmatch(r"[A-Z]{2}|INT", o.country), o.outlet_id
        if o.kind != "platform":
            assert o.country, f"{o.outlet_id} has no country"
        if o.reliability is not None:
            assert 0 <= o.reliability <= 1 and o.reliability_domain, o.outlet_id
        if o.is_platform:
            assert o.reliability is None and not o.us_lean and not o.state_media, o.outlet_id
        if o.state_media:
            assert o.state_media_entity and o.state_media_year, o.outlet_id


def test_every_lean_names_its_allsides_entry(t):
    for o in t.outlets:
        if o.us_lean or o.us_lean_opinion:
            assert o.allsides_name and o.allsides_date and o.allsides_confidence is not None, o.outlet_id


def mts_domains():
    with open(paths.OUTLET_SOURCES / "domains_all.csv", newline="") as f:
        return [r["domain"] for r in csv.DictReader(f) if int(r["mts_links"] or 0) > 0]


def test_every_mts_domain_has_country_and_kind(t):
    ds = mts_domains()
    assert len(ds) == 44
    for d in ds:
        lab = t.label(f"https://{d}/x/y")
        assert lab["outlet_id"], f"MtS domain {d} has no row"
        assert lab["country"] and lab["kind"], d


def test_core_search_domains_have_rows_and_fit(t):
    core = t.core_domains()
    assert 0 < len(core) <= 300
    for d in core:
        assert t.label(f"https://{d}/x/y")["outlet_id"], d


def test_side_lists_point_at_real_rows(t):
    with open(paths.SIDE_LISTS_CSV, newline="") as f:
        for r in csv.DictReader(f):
            for i in r["outlet_ids"].split(";"):
                assert i in t.by_id, f"side {r['side_id']}: unknown outlet {i}"


# 8. Golden set, copied by hand from AllSides pages (Nov 24), Lin et al. 2023 and SMM 2026 ----
# url, AllSides news lean (None = no rating), Lin score (None = not in Lin), SMM level
# An outlet with several addresses takes its LOWEST Lin score for every address (rule set Nov 24),
# so bbc.com, abcnews.go.com and presstv.ir below carry their sister address's score.
GOLDEN = [
    ("https://www.cnn.com/a/b", "Lean Left", 0.66, None),
    ("https://www.foxnews.com/a/b", "Right", 0.53, None),
    ("https://nypost.com/2026/11/05/a/", "Right", 0.64, None),
    ("https://www.nytimes.com/2026/11/05/us/a.html", "Lean Left", 0.86, None),
    ("https://apnews.com/article/a", "Lean Left", 1.00, None),
    ("https://www.reuters.com/world/a", "Center", 1.00, None),
    ("https://www.bbc.com/news/a", "Center", 0.72, "Independent Public"),         # bbc.co.uk
    ("https://www.theguardian.com/world/a/b", "Left", 0.75, None),
    ("https://www.aljazeera.com/news/a/b", "Lean Left", 0.78, "State-Controlled"),
    ("https://www.npr.org/2026/11/05/a", "Lean Left", 0.93, "Independent Public"),
    ("https://www.dw.com/en/a/b", "Center", 0.86, "Independent State-Funded"),
    ("https://www.straitstimes.com/world/a", None, 0.75, "Captured Public"),
    ("https://www.channelnewsasia.com/world/a", None, 0.87, "Captured Public"),
    ("https://www.globaltimes.cn/page/a/b", None, 0.54, "Captured Public"),
    ("https://tass.com/world/1", None, 0.34, "State-Controlled"),
    ("https://www.rt.com/news/a/", "Lean Right", 0.29, "State-Controlled"),
    ("https://www.aa.com.tr/en/world/a/1", "Center", 0.61, "State-Controlled"),
    ("https://www.france24.com/en/a/b", None, 0.88, "Independent State-Funded and State-Managed"),
    ("https://en.yna.co.kr/view/a", None, None, "Independent Public"),
    ("https://www.breitbart.com/politics/a/", "Right", 0.30, None),
    ("https://www.washingtonexaminer.com/news/a", "Lean Right", 0.51, None),
    ("https://www.wsj.com/politics/a", "Center", 0.80, None),
    ("https://www.bloomberg.com/news/articles/a", "Center", 0.84, None),
    ("https://www.cnbc.com/2026/11/05/a.html", "Lean Left", 0.85, None),
    ("https://abcnews.go.com/Politics/a", "Lean Left", 0.67, None),             # abcnews.com
    ("https://www.ms.now/news/a", "Left", 0.59, None),
    ("https://www.thefp.com/p/a", "Lean Right", None, None),
    ("https://kyivindependent.com/a/", "Center", 0.62, None),
    ("https://www.jpost.com/israel-news/a", "Center", 0.81, None),
    ("https://www.presstv.ir/Detail/2026/11/05/1/a", None, 0.23, "State-Controlled"),  # presstv.com
    ("https://www.tasnimnews.com/en/news/2026/11/05/1/a", None, 0.30, "Captured Private"),
    ("https://www.abc.net.au/news/a/1", None, 0.89, "Independent State-Funded"),
    ("https://www.pbs.org/newshour/politics/a", "Lean Left", 0.87, "Independent Public"),
    ("https://www.dailymail.co.uk/news/a.html", "Lean Right", 0.38, None),
    ("https://www.newsmax.com/politics/a/2026/11/05/id/1/", "Lean Right", 0.29, None),
]


@pytest.mark.parametrize("url,lean,rel,smm", GOLDEN)
def test_golden(t, url, lean, rel, smm):
    lab = t.label(url)
    assert lab["outlet_id"], url
    assert lab["us_lean"] == lean
    if rel is None:
        assert lab["reliability"] is None
    else:
        assert lab["reliability"] == pytest.approx(rel, abs=0.006)
    assert lab["state_media"] == smm
