"""Step 3a: places in the script become coordinates, an outline and a map frame (settled Nov 26, decision 9).

The data is built once by scripts/build_video_places.py from Natural Earth (countries in Germany's point
of view, provinces, seas) and GeoNames (towns over 15,000 people), into paths.PRIVATE/video_assets/geo/.

The look-up tries, in order:
  1. the name as the kind the writer gave (point = town, province, country, sea);
  2. the name as any kind ("Crimea" sent as a point is found as a province);
  3. the longest part of the name that is a known place ("Novi Sad railway station" pins Novi Sad; the
     label still says the full name), only within about 1,500 km of the event;
  4. the event's own coordinates, only when the event's location name contains the place;
otherwise nothing, and the beat becomes a headline card.

    g = Gazetteer()
    find("Novi Sad railway station", "point", event, g)
      -> {"name": "Novi Sad railway station", "lat": 45.25, "lng": 19.84, "kind": "point", "how": "part: Novi Sad", ...}
"""
from __future__ import annotations

import functools
import json
import math
import re
import unicodedata
from pathlib import Path

from .. import paths

GEO = paths.PRIVATE / "video_assets" / "geo"
KINDS = ("point", "province", "country", "sea")
PART_MAX_KM = 1500
POINT_HALF_KM = 150            # a point is framed with about 300 km across
LAKE_MIN_FRACTION = 120        # a lake narrower than 1/120 of the map's width (under ~3 dots) is left out
# Words that are never a place on their own (so "Space Center" never pins a town called Center).
NOT_ALONE = set("""center centre station railway square main space port airport base river bridge city north south
east west new old saint st lake mount island islands sea gulf strait bay coast region province state district
county oblast valley national park palace hall house court market street road avenue tower plant factory
power nuclear military camp prison hospital school university church cathedral mosque temple monastery
lavra embassy""".split())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = re.sub(r"[’'`\-–—./,()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^the ", "", s)


def km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


class Gazetteer:
    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder or GEO)
        data = json.loads((self.folder / "places.json").read_text(encoding="utf-8"))
        self.version = data.get("version")
        self.index: dict[str, dict[str, list[dict]]] = {k: {} for k in KINDS}
        for kind, rows in (("country", data["countries"]), ("province", data["provinces"]), ("sea", data["seas"])):
            for r in rows:
                e = dict(r, kind=kind, pop=r.get("area") or 0)
                for n in {norm(x) for x in [r["name"]] + r.get("names", [])}:
                    if n:
                        self.index[kind].setdefault(n, []).append(e)
        for name, ascii_, alts, lat, lng, iso2, pop, fcode in data["towns"]:
            e = dict(id=f"t:{name}:{iso2}", name=name, iso2=iso2, lat=lat, lng=lng, pop=pop, kind="point", fcode=fcode)
            for n in {norm(x) for x in [name, ascii_] + alts}:
                if n:
                    self.index["point"].setdefault(n, []).append(e)
        self.countries = list({e["id"]: e for hits in self.index["country"].values() for e in hits}.values())
        self.towns = [e for e in {id(e): e for hits in self.index["point"].values() for e in hits}.values()]
        self._shapes = None
        self._lakes = None

    def shape(self, sid: str) -> dict | None:
        if not sid or sid.startswith("t:"):
            return None
        if self._shapes is None:
            self._shapes = json.loads((self.folder / "shapes.json").read_text(encoding="utf-8"))
        return self._shapes.get(sid)

    def lakes(self, box: list[float]) -> list[list[list[float]]]:
        """The rings of every lake inside the map's box, big enough to see (lakes.json, Natural Earth). Drawn
        with the even-odd rule, so an island's ring cuts it back out of its lake."""
        if self._lakes is None:
            f = self.folder / "lakes.json"
            self._lakes = json.loads(f.read_text(encoding="utf-8"))["lakes"] if f.exists() else []
        w, s_, e, n = box
        tiny = (e - w) / LAKE_MIN_FRACTION
        out = []
        for lk in self._lakes:
            b = lk["bbox"]
            if b[2] < w or b[0] > e or b[3] < s_ or b[1] > n or max(b[2] - b[0], b[3] - b[1]) < tiny:
                continue
            out += [r for r in lk["rings"] if len(r) >= 4]
        return out

    def iso2_of(self, country: str) -> str | None:
        hits = self.index["country"].get(norm(country))
        return hits[0].get("iso2") if hits else None

    def lookup(self, name: str, kinds, iso2: str | None) -> dict | None:
        n = norm(name)
        hits = [e for k in kinds for e in self.index[k].get(n, [])]
        if not hits:
            return None
        order = {k: i for i, k in enumerate(kinds)}
        return min(hits, key=lambda e: (e.get("iso2") != iso2 if iso2 else 0, order[e["kind"]], -(e.get("pop") or 0)))


@functools.lru_cache(maxsize=1)
def default() -> Gazetteer:
    return Gazetteer()


def _event_point(ev: dict) -> tuple[float, float] | None:
    try:
        return float(ev["lat"]), float(ev["lng"])
    except (KeyError, TypeError, ValueError):
        return None


def _parts(name: str) -> list[str]:
    words = norm(name).split()
    out = []
    for size in range(len(words) - 1, 0, -1):
        for i in range(len(words) - size + 1):
            part = words[i:i + size]
            if size == 1 and (part[0] in NOT_ALONE or len(part[0]) < 4):
                continue
            if all(w in NOT_ALONE for w in part):
                continue
            out.append(" ".join(part))
    return out


def find(name: str, kind: str, event: dict, g: Gazetteer | None = None) -> dict | None:
    """One place of a map beat, found as the design says, or None."""
    g = g or default()
    iso2 = g.iso2_of(str(event.get("country") or ""))
    kinds = [kind] if kind in KINDS else []
    base = dict(name=name, given_kind=kind)
    hit = g.lookup(name, kinds, iso2) if kinds else None
    how = "as given"
    if hit is None:
        hit = g.lookup(name, kinds + [k for k in ("province", "country", "sea", "point") if k not in kinds], iso2)
        how = "as another kind"
    if hit is None:
        ep = _event_point(event)
        for part in _parts(name):
            h = g.lookup(part, ["point", "province", "country", "sea"], iso2)
            if h and (ep is None or km(ep[0], ep[1], h["lat"], h["lng"]) <= PART_MAX_KM):
                hit, how = h, f"part: {h['name']}"
                break
    if hit is None:
        ep = _event_point(event)
        if ep and norm(name) and norm(name) in norm(str(event.get("location_name") or "")):
            return dict(base, kind="sea" if kind == "sea" else "point", lat=ep[0], lng=ep[1], shape=None,
                        bbox=None, how="the event's coordinates", found=str(event.get("location_name")))
        return None
    found_kind = hit["kind"]
    return dict(base, kind=found_kind, lat=hit["lat"], lng=hit["lng"], shape=hit.get("id") if found_kind != "point" else None,
                bbox=hit.get("bbox"), how=how, found=hit["name"], iso2=hit.get("iso2"))


# ---- framing -----------------------------------------------------------------------------------------

def _pad(b, frac, min_km=0):
    w, s, e, n = b
    lat = (s + n) / 2
    half_w = max((e - w) / 2 * (1 + frac), min_km / 2 / (111 * max(0.2, math.cos(math.radians(lat)))))
    half_h = max((n - s) / 2 * (1 + frac), min_km / 2 / 111)
    cx, cy = (w + e) / 2, lat
    return [round(cx - half_w, 4), round(max(-85, cy - half_h), 4), round(cx + half_w, 4), round(min(85, cy + half_h), 4)]


def _main_bbox(shape: dict | None, b):
    """Countries across the date line (Russia, Fiji) get the box of their biggest polygon."""
    if not b or b[2] - b[0] <= 180 or not shape:
        return b
    best = max(shape["coordinates"], key=lambda poly: len(poly[0]))
    xs = [x for x, _ in best[0]]
    ys = [y for _, y in best[0]]
    return [min(xs), min(ys), max(xs), max(ys)]


def point_box(lat, lng, half_km=POINT_HALF_KM):
    dlat = half_km / 111
    dlng = half_km / (111 * max(0.2, math.cos(math.radians(lat))))
    return [round(lng - dlng, 4), round(lat - dlat, 4), round(lng + dlng, 4), round(lat + dlat, 4)]


def frame(found: list[dict], g: Gazetteer | None = None) -> list[float]:
    """The map's box [west, south, east, north] for one, two or many found places."""
    g = g or default()
    if len(found) == 1:
        p = found[0]
        if p["kind"] in ("province", "country", "sea") and p.get("bbox"):
            b = _main_bbox(g.shape(p.get("shape")), p["bbox"])
            return _pad(b, {"province": 0.25, "country": 0.15, "sea": 0.3}[p["kind"]], min_km=150)
        return point_box(p["lat"], p["lng"], 250 if p["kind"] == "sea" else POINT_HALF_KM)
    xs = [p["lng"] for p in found]
    ys = [p["lat"] for p in found]
    return _pad([min(xs), min(ys), max(xs), max(ys)], 0.35, min_km=200)


# ---- context: what else the map shows, so a pin is never alone on blank land -------------------------

CONTEXT_TOWNS = 4
TOWN_MIN_POP = 100_000


def _grow(b, frac):
    dx, dy = (b[2] - b[0]) * frac, (b[3] - b[1]) * frac
    return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy]


def _overlaps(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def context(box: list[float], g: Gazetteer | None = None, *, skip: list[tuple[float, float]] = ()) -> dict:
    """Country borders inside the frame (as dotted-line runs), the names of countries whose label point is in
    it, and up to 4 big towns (over 100,000 people, spread out, not on top of a place the beat names)."""
    g = g or default()
    big = _grow(box, 0.15)
    borders, names = [], []
    for c in g.countries:
        if not c.get("bbox") or not _overlaps(c["bbox"], big):
            continue
        sh = g.shape(c["id"])
        for poly in (sh or {}).get("coordinates", []):
            for ring in poly[:1]:
                run = []
                for x, y in ring:
                    if in_box(big, x, y):
                        run.append([x, y])
                    elif run:
                        if len(run) > 1:
                            borders.append(run)
                        run = []
                if len(run) > 1:
                    borders.append(run)
        if in_box(_grow(box, -0.08), c["lng"], c["lat"]):
            names.append(dict(name=c["name"], lat=c["lat"], lng=c["lng"]))
    inner = _grow(box, -0.06)
    cands = sorted((t for t in g.towns if t.get("pop", 0) >= TOWN_MIN_POP and in_box(inner, t["lng"], t["lat"])),
                   key=lambda t: -t["pop"])
    bw, bh = box[2] - box[0], box[3] - box[1]
    gap = max(bw, bh) * 0.18
    towns: list[dict] = []
    for t in cands:
        # not on top of a named place, and not on the row its label runs along
        if any((abs(t["lng"] - x) < gap / 2 and abs(t["lat"] - y) < gap / 2)
               or (abs(t["lng"] - x) < 0.3 * bw and abs(t["lat"] - y) < 0.1 * bh) for x, y in skip):
            continue
        if any(abs(t["lng"] - o["lng"]) < gap and abs(t["lat"] - o["lat"]) < gap * 0.6 for o in towns):
            continue
        towns.append(dict(name=t["name"], lat=t["lat"], lng=t["lng"], pop=t["pop"]))
        if len(towns) == CONTEXT_TOWNS:
            break
    return dict(borders=borders, countries=names, towns=towns)


# ---- checks (eval 8) -----------------------------------------------------------------------------------

def _in_ring(x, y, ring) -> bool:
    inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def contains(shape: dict, lng: float, lat: float) -> bool:
    for poly in shape["coordinates"]:
        if _in_ring(lng, lat, poly[0]) and not any(_in_ring(lng, lat, h) for h in poly[1:]):
            return True
    return False


def in_box(b, lng, lat) -> bool:
    return b[0] <= lng <= b[2] and b[1] <= lat <= b[3]
