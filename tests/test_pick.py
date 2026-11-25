"""The pick step: at most 10 balanced articles per story. Made-up articles and outlets only."""
from stringer import pick

SIDES = {"kind": "world", "sides": [{"side_id": "left_x", "outlet_ids": [f"a{i}" for i in range(10)]},
                                    {"side_id": "right_x", "outlet_ids": [f"b{i}" for i in range(10)]}]}


def art(outlet, n=0, **kw):
    a = {"id": f"{outlet}_{n}", "outlet": outlet, "url_key": f"{outlet}.example/{n}", "role": "new_coverage",
         "text_status": "full", "text_chars": 3000, "own_source": False, "found_by": ["tavily_search:q1_core"],
         "best_rank": n, "verdict": None, "title": " ".join(f"t{outlet}{n}k{i}" for i in range(6)),
         "text": f"{outlet} {n} " + " ".join(f"w{outlet}{n}x{i}" for i in range(60)),
         "labels": {"kind": "news", "section": "news", "is_wire": False}}
    a.update(kw)
    return a


def wire(outlet, n=0):
    return art(outlet, n, labels={"kind": "wire", "section": "news", "is_wire": True})


def groups(r):
    out = {}
    for row in r["rows"]:
        out[row["group"]] = out.get(row["group"], 0) + 1
    return out


def test_two_sides_get_four_each_and_wires_fill():
    arts = [art(f"a{i}") for i in range(6)] + [art(f"b{i}") for i in range(6)] + \
           [wire(f"w{i}") for i in range(3)] + [art(f"o{i}") for i in range(5)]
    r = pick.pick(arts, SIDES)
    assert len(r["picked"]) == 10 and groups(r) == {"A": 4, "B": 4, "wire": 2}
    assert len({row["outlet"] for row in r["rows"]}) == 10 and r["flags"] == []


def test_thin_side_holds_the_other_side_back_and_is_flagged():
    arts = [art("a0")] + [art(f"b{i}") for i in range(8)] + [art(f"o{i}") for i in range(10)]
    r = pick.pick(arts, SIDES)
    assert groups(r) == {"A": 1, "B": 2, "other": 7}
    assert r["flags"] == ["thin side: left_x gave 1 of 4, so right_x was held to 2"]
    r = pick.pick([art(f"b{i}") for i in range(8)] + [art(f"o{i}") for i in range(10)], SIDES)
    assert groups(r) == {"B": 1, "other": 9}


def test_sides_grow_in_pairs_only_when_neutrals_run_out():
    arts = [art(f"a{i}") for i in range(7)] + [art(f"b{i}") for i in range(7)] + [art("o0")]
    r = pick.pick(arts, SIDES)
    g = groups(r)
    assert len(r["picked"]) == 10 and g["other"] == 1 and abs(g["A"] - g["B"]) <= 1


def test_one_per_outlet_and_no_near_copies():
    same_outlet = [art("o1", 0), art("o1", 1)]
    copy = art("o2", 0, title="Gunman kills six in city square shooting - Outlet Two")
    copy2 = art("o3", 0, title="Gunman kills six in city square shooting | Outlet Three")
    text_copy = art("o4", 0, text=copy["text"].replace("o2", "o4", 1))
    r = pick.pick(same_outlet + [copy, copy2, text_copy], {"kind": "none", "sides": []})
    assert [row["outlet"] for row in r["rows"]] == ["o1", "o2"]
    assert r["flags"] == ["only 2 usable articles"]


def test_unusable_articles_are_skipped():
    bad = [art("o1", text_status="snippet"), art("o2", role="background"), art("o3", verdict="different"),
           art("o4", labels={"kind": "x_account", "section": "news", "is_wire": False}),
           art("o5", labels={"kind": "news", "section": "opinion", "is_wire": False})]
    r = pick.pick(bad + [art("o6")], {"kind": "none", "sides": []})
    assert r["picked"] == ["o6_0"] and r["usable"] == 1


def test_no_split_takes_local_press_first_then_wires():
    lens = {"kind": "none", "sides": [], "local": {"side_id": "local_xx", "outlet_ids": [f"l{i}" for i in range(9)]}}
    arts = [art(f"l{i}") for i in range(6)] + [wire(f"w{i}") for i in range(2)] + [art(f"o{i}") for i in range(5)]
    r = pick.pick(arts, lens)
    assert groups(r) == {"local": 4, "wire": 2, "other": 4}


def test_cited_sources_and_multi_search_finds_rank_first():
    arts = [art("o1", 0), art("o2", 1, found_by=["a", "b", "c"]), art("o3", 2, own_source=True),
            art("o4", 3, role="unclear", own_source=True)]
    r = pick.pick(arts, {"kind": "none", "sides": []}, n=3)
    assert [row["outlet"] for row in r["rows"]] == ["o3", "o2", "o1"]
