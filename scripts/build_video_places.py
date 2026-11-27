"""Builds module 8's place index from the free map files, once (settled Nov 26, decisions 9 and 10).

Standalone on purpose (standard library only, no stringer imports): it reads downloaded files, so it
runs with `python -I`:

    python -I scripts/build_video_places.py <raw folder> <out folder>

Reads from <raw folder> (all downloaded by hand, see the system map, module 8):
  ne_10m_admin_0_countries_deu.geojson   Natural Earth countries, Germany's point of view (Jan: "the western
                                         view of borders"; of the Western views it is the one that shows
                                         Crimea in Ukraine and leaves Kosovo, Western Sahara and the Golan
                                         Heights separate)
  ne_10m_admin_1_states_provinces.geojson  provinces and states
  ne_10m_geography_marine_polys.geojson  named seas, gulfs and straits
  cities15000.txt                        GeoNames towns over 15,000 people (CC BY 4.0)
  ne_10m_lakes/ne_10m_lakes.shp (+ .dbf) Natural Earth lakes (Jan's OK, Nov 26), so lakes are drawn as water
Writes to <out folder>:
  places.json   every country, province, sea and town with its names, label point and box
  shapes.json   each country, province and sea outline, simplified, coordinates rounded to 3 decimals
  lakes.json    every lake's rings (islands are inner rings), simplified, with its box
"""
from __future__ import annotations

import datetime as dt
import json
import struct
import sys
from pathlib import Path


def _dp(points: list, tol: float) -> list:
    """Douglas-Peucker simplification of one ring."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    x0, y0 = points[0]
    if abs(points[-1][0] - x0) + abs(points[-1][1] - y0) < 1e-9:        # a closed ring: split at its far point
        far = max(range(len(points)), key=lambda i: (points[i][0] - x0) ** 2 + (points[i][1] - y0) ** 2)
        keep[far] = True
        stack = [(0, far), (far, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, idx = -1.0, None
        for i in range(a + 1, b):
            x, y = points[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def simplify(geom: dict, tol: float) -> dict | None:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            r = [[round(x, 3), round(y, 3)] for x, y in _dp(ring, tol)]
            if len(r) >= 4:
                rings.append(r)
        if rings and len(rings[0]) >= 4:
            out.append(rings)
    if not out:
        return None
    return {"type": "MultiPolygon", "coordinates": out}


def bbox(geom: dict) -> list[float]:
    xs, ys = [], []
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        for x, y in poly[0]:
            xs.append(x)
            ys.append(y)
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def _names(*vals) -> list[str]:
    out = []
    for v in vals:
        for n in str(v or "").split("|"):
            n = n.strip()
            if n and n not in out and len(n) <= 60:
                out.append(n)
    return out


def _latin(s: str) -> bool:
    return all(ord(c) < 0x250 for c in s)


def read_shapefile(shp: Path) -> list[tuple[dict, list[list[list[float]]]]]:
    """(attributes, rings) for each polygon in a shapefile and its .dbf (standard library only)."""
    data, rows = shp.read_bytes(), []
    pos = 100
    while pos + 8 <= len(data):
        length = struct.unpack(">i", data[pos + 4:pos + 8])[0] * 2
        rec = data[pos + 8:pos + 8 + length]
        pos += 8 + length
        if struct.unpack("<i", rec[:4])[0] != 5:                       # 5 = polygon; null shapes are skipped
            rows.append(None)
            continue
        n_parts, n_points = struct.unpack("<2i", rec[36:44])
        parts = list(struct.unpack(f"<{n_parts}i", rec[44:44 + 4 * n_parts])) + [n_points]
        pts = struct.unpack(f"<{2 * n_points}d", rec[44 + 4 * n_parts:44 + 4 * n_parts + 16 * n_points])
        rows.append([[[pts[2 * k], pts[2 * k + 1]] for k in range(parts[i], parts[i + 1])] for i in range(n_parts)])
    dbf = shp.with_suffix(".dbf").read_bytes()
    n, head, size = struct.unpack("<IHH", dbf[4:12])
    fields, off = [], 32
    while dbf[off] != 0x0D:
        fields.append((dbf[off:off + 11].split(b"\0")[0].decode(), dbf[off + 16]))
        off += 32
    out = []
    for i in range(n):
        r = dbf[head + i * size + 1:head + (i + 1) * size]
        attrs, at = {}, 0
        for name, width in fields:
            attrs[name] = r[at:at + width].decode("utf-8", "replace").strip()
            at += width
        if i < len(rows) and rows[i]:
            out.append((attrs, rows[i]))
    return out


def lakes(raw: Path, out: Path) -> int:
    shp = raw / "ne_10m_lakes" / "ne_10m_lakes.shp"
    if not shp.exists():
        return 0
    rows = []
    for attrs, rings in read_shapefile(shp):
        g = simplify(dict(type="Polygon", coordinates=rings), 0.005)
        if not g:
            continue
        rs = [r for poly in g["coordinates"] for r in poly]
        xs, ys = [x for r in rs for x, _ in r], [y for r in rs for _, y in r]
        box = [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]
        rows.append(dict(name=attrs.get("name") or "", rank=int(attrs.get("scalerank") or 0), bbox=box, rings=rs))
    (out / "lakes.json").write_text(json.dumps(dict(version="lakes-1", source="Natural Earth 10m lakes (public domain)",
                                                    lakes=rows), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(rows)


def main(raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shapes, countries, provinces, seas, towns = {}, [], [], [], []

    for f in json.loads((raw / "ne_10m_admin_0_countries_deu.geojson").read_text(encoding="utf-8"))["features"]:
        p, g = f["properties"], f["geometry"]
        if not g:
            continue
        sid = f"c:{p.get('ADM0_A3') or p.get('ISO_A3')}:{p.get('NAME')}"
        s = simplify(g, 0.02)
        if not s:
            continue
        shapes[sid] = s
        b = bbox(g)
        countries.append(dict(id=sid, name=p.get("NAME_EN") or p.get("NAME"), iso2=p.get("ISO_A2_EH") or p.get("ISO_A2"),
                              names=_names(p.get("NAME"), p.get("NAME_EN"), p.get("NAME_LONG"), p.get("ADMIN"),
                                           p.get("FORMAL_EN"), p.get("BRK_NAME"), p.get("NAME_ALT"), p.get("NAME_SORT")),
                              lat=round(p.get("LABEL_Y") or (b[1] + b[3]) / 2, 4),
                              lng=round(p.get("LABEL_X") or (b[0] + b[2]) / 2, 4), bbox=b, area=p.get("POP_EST")))

    for f in json.loads((raw / "ne_10m_admin_1_states_provinces.geojson").read_text(encoding="utf-8"))["features"]:
        p, g = f["properties"], f["geometry"]
        if not g:
            continue
        sid = f"p:{p.get('adm1_code')}"
        s = simplify(g, 0.01)
        if not s:
            continue
        shapes[sid] = s
        names = _names(p.get("name"), p.get("name_en"), p.get("woe_name") if p.get("woe_name") == p.get("name") else "",
                       p.get("gn_name"), p.get("name_alt"))
        provinces.append(dict(id=sid, name=p.get("name_en") or p.get("name"), names=names, iso2=p.get("iso_a2"),
                              country=p.get("admin"), kind=p.get("type_en"), lat=round(p.get("latitude") or 0, 4),
                              lng=round(p.get("longitude") or 0, 4), bbox=bbox(g)))

    for f in json.loads((raw / "ne_10m_geography_marine_polys.geojson").read_text(encoding="utf-8"))["features"]:
        p, g = f["properties"], f["geometry"]
        if not g or not p.get("name"):
            continue
        sid = f"s:{p.get('ne_id')}"
        s = simplify(g, 0.03)
        if not s:
            continue
        shapes[sid] = s
        b = bbox(g)
        seas.append(dict(id=sid, name=p.get("name_en") or p.get("name"), names=_names(p.get("name"), p.get("name_en"),
                                                                                    p.get("namealt")),
                         kind=p.get("featurecla"), lat=round((b[1] + b[3]) / 2, 4), lng=round((b[0] + b[2]) / 2, 4), bbox=b))

    for line in (raw / "cities15000.txt").read_text(encoding="utf-8").splitlines():
        c = line.split("\t")
        if len(c) < 15:
            continue
        alts = [a for a in c[3].split(",") if a and _latin(a) and len(a) <= 40 and a not in (c[1], c[2])][:15]
        towns.append([c[1], c[2], alts, round(float(c[4]), 4), round(float(c[5]), 4), c[8], int(c[14] or 0), c[7]])

    meta = dict(version="places-1", built=dt.date.today().isoformat(),
                sources=dict(countries="Natural Earth 10m admin-0, Germany's point of view (public domain)",
                             provinces="Natural Earth 10m admin-1 (public domain)",
                             seas="Natural Earth 10m marine polygons (public domain)",
                             towns="GeoNames cities15000 (CC BY 4.0)"),
                towns_fields=["name", "ascii", "alternates", "lat", "lng", "iso2", "population", "feature_code"])
    (out / "places.json").write_text(json.dumps(dict(meta, countries=countries, provinces=provinces, seas=seas,
                                                     towns=towns), ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")
    (out / "shapes.json").write_text(json.dumps(shapes, separators=(",", ":")), encoding="utf-8")
    n_lakes = lakes(raw, out)
    print(f"{len(countries)} countries, {len(provinces)} provinces, {len(seas)} seas, {len(towns)} towns, "
          f"{len(shapes)} shapes, {n_lakes} lakes")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
