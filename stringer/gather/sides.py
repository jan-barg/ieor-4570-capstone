"""Which outlets each side's search covers.

US lens (left vs right) is derived from outlets.csv: US outlets with an AllSides lean.
Other lenses use the hand-made lists in stringer_private/outlets/side_lists.csv.

The search mode follows the settled rule: news mode for US outlets, general mode for the rest.
A side that mixes both is split into two searches."""
from __future__ import annotations

import csv
from dataclasses import dataclass

from .. import paths
from ..outlets import OutletTable

US_LEFT = {"Left", "Lean Left"}
US_RIGHT = {"Lean Right", "Right"}
RIGHT_TAIL_EXCLUDE = {"foxnews", "nypost", "foxbusiness"}   # what news mode already finds


@dataclass
class Side:
    side_id: str
    label: str
    outlet_ids: list[str]


@dataclass
class Lens:
    kind: str            # us | world | none
    sides: list[Side]
    source: str = ""
    local: Side | None = None   # one country's press: searched for coverage, never compared


def local_press(t: OutletTable, country: str) -> Side | None:
    """Every news or wire outlet in outlets.csv from one country (Nov 24). Used for stories with no
    real split, which have no side searches, so their local outlets would otherwise go unsearched
    (e.g. the Krakow shooting kept 0 of its 20 Polish articles)."""
    ids = [o.outlet_id for o in t.outlets if o.country == country and o.kind in ("news", "wire")]
    if not ids:
        return None
    return Side(f"local_{country.lower()}", f"{country} outlets (searched for coverage, not a side)", ids)


def us_sides(t: OutletTable) -> dict[str, Side]:
    us = [o for o in t.outlets if o.country == "US" and o.kind in ("news", "wire") and o.us_lean]
    left = [o.outlet_id for o in us if o.us_lean in US_LEFT]
    right = [o.outlet_id for o in us if o.us_lean in US_RIGHT]
    tail = [i for i in right if i not in RIGHT_TAIL_EXCLUDE]
    return {"us_left": Side("us_left", "US left-leaning outlets (AllSides Left, Lean Left)", left),
            "us_right": Side("us_right", "US right-leaning outlets (AllSides Lean Right, Right)", right),
            "us_right_tail": Side("us_right_tail", "US right outlets except Fox and the NY Post", tail)}


def side_lists(t: OutletTable) -> dict[str, Side]:
    out = dict(us_sides(t))
    with open(paths.SIDE_LISTS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ids = [i for i in r["outlet_ids"].split(";") if i]
            missing = [i for i in ids if i not in t.by_id]
            if missing:
                raise KeyError(f"side {r['side_id']}: outlets not in outlets.csv: {missing}")
            out[r["side_id"]] = Side(r["side_id"], r["label"], ids)
    return out


def fixture_lenses(t: OutletTable) -> dict[str, Lens]:
    sides = side_lists(t)
    out = {}
    with open(paths.FIXTURE_LENSES_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ss = [sides[s] for s in (r["side_a"], r["side_b"]) if s]
            cc = (r.get("local_press") or "").strip()
            out[r["event"]] = Lens(r["lens"], ss, r["source"], local_press(t, cc) if cc else None)
    return out


def split_by_mode(t: OutletTable, side: Side) -> list[tuple[str, list[str]]]:
    """[(topic, hosts)]: US outlets in news mode, all others in general mode."""
    us = [i for i in side.outlet_ids if t.by_id[i].country == "US"]
    other = [i for i in side.outlet_ids if t.by_id[i].country != "US"]
    out = []
    if us:
        out.append(("news", t.hosts(set(us), kinds=None)))
    if other:
        out.append(("general", t.hosts(set(other), kinds=None)))
    return out
