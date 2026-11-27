"""The landing page's world map data (the atlas, direction 3), built from the same Natural Earth shapes the
videos draw, so the site's borders match the videos' (Crimea inside Ukraine, and never labelled).

Ported from the design's tools/build_geo.py (Nov 27). Its inputs are not in this public repo:
    <private>/video_assets/geo/{shapes,places,lakes}.json   (Cloud Build copies them into /private)
    render/node_modules/world-atlas/land-50m.json           (npm ci in the image)
so the site builds the file once when it starts (about 940 KB, served gzipped, about 330 KB).

    text = geo.build()            # 'window.ATLAS_GEO = {...};' or None when the inputs are missing"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from stringer import paths

# world-atlas from the render project's packages (the image's npm ci; on the Mac, any checkout's render/)
ATLAS_DIRS = [Path(os.environ["STRINGER_WORLD_ATLAS"])] if os.environ.get("STRINGER_WORLD_ATLAS") else []
ATLAS_DIRS += [paths.CODE / "render" / "node_modules" / "world-atlas",
               paths.CODE.parent / "stringer" / "render" / "node_modules" / "world-atlas"]
# the design's own built copy, for a Mac checkout without the inputs (private folder, never in the repo)
PREBUILT = paths.PRIVATE / "frontend_designs" / "direction-3-atlas" / "js" / "data" / "geo.js"

PROVINCES = {   # the provinces a fly-to lights up (the video lights the named place's own land)
    'beni': ('BOL', 'Beni'), 'belgorod': ('RUS', 'Belgorod'), 'antwerp': ('BEL', 'Antwerp'),
    'brussels': ('BEL', 'Brussels Capital'), 'basra': ('IRQ', 'Basra'), 'gandaki': ('NPL', 'Gandaki Zone'),
    'valparaiso': ('CHL', 'Valparaíso'), 'kasai': ('COD', 'Kasaï-Occidental'), 'lilongwe': ('MWI', 'Lilongwe'),
    'muscat': ('OMN', 'Muscat'), 'washington': ('USA', 'Washington'), 'hokkaido': ('JPN', 'Hokkaidō'),
    'nairobi': ('KEN', 'Nairobi'), 'coast': ('KEN', 'Coast'), 'df': ('BRA', 'Federal'),
}
EXTRA_TOWNS = ['Trinidad', 'Riberalta', 'Santa Ana de Yacuma', 'Guayaramerín', 'Kushiro', 'Obihiro', 'Viña del Mar',
               'Belgorod', 'Kharkiv', 'Kursk', 'Voi', 'Mombasa', 'Gorkha', 'Pokhara', 'Tshikapa', 'Kananga', 'Basra',
               'Muscat', 'Lilongwe', 'Blantyre', 'Antwerp', 'Ghent', 'Rotterdam', 'Brasília', 'Goiânia', 'Sapporo',
               'Valparaíso', 'Nairobi', 'Machakos', 'Mzuzu', 'Sohar', 'Nizwa', 'Bandar Abbas', 'Kathmandu', 'Bharatpur',
               'Mbuji-Mayi', 'Cochabamba', 'Santa Cruz de la Sierra', 'Baltimore', 'Richmond', 'Philadelphia']
SKIP_TOWNS_NEAR_CRIMEA = (32.0, 44.2, 36.8, 46.3)   # never label anything on the peninsula


def perp(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(pts, tol):
    if len(pts) < 5:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, k = 0, -1
        for m in range(i + 1, j):
            d = perp(pts[m], pts[i], pts[j])
            if d > best:
                best, k = d, m
        if best > tol and k > 0:
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    return [p for p, f in zip(pts, keep) if f]


def ring_area(r):
    a = 0
    for i in range(len(r) - 1):
        a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
    return abs(a) / 2


def shrink(multi, tol, min_area):
    polys = []
    for poly in multi:
        outer = poly[0]
        if ring_area(outer) < min_area:
            continue
        rings = []
        for k, ring in enumerate(poly):
            s = simplify(ring, tol)
            if len(s) < 4:
                if k == 0:
                    break
                continue
            rings.append([[round(x, 2), round(y, 2)] for x, y in s])
        if rings:
            polys.append(rings)
    if not polys:      # a tiny country: keep its biggest piece
        big = max(multi, key=lambda p: ring_area(p[0]))
        polys = [[[[round(x, 2), round(y, 2)] for x, y in simplify(big[0], tol / 3)]]]
    return polys


def pack(polys):
    """Each ring as a flat list of whole hundredths of a degree, every point after the first as a step from the
    one before (js/atlas.js unpacks it). About a third of the size of plain coordinates."""
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            flat, px, py = [], 0, 0
            for x, y in ring:
                ix, iy = int(round(x * 100)), int(round(y * 100))
                flat += [ix - px, iy - py]
                px, py = ix, iy
            rings.append(flat)
        out.append(rings)
    return out


def build(geo_dir: Path | None = None, atlas_dir: Path | None = None) -> str | None:
    """The text of geo.js, or None when an input is missing."""
    GEO = Path(geo_dir or paths.PRIVATE / 'video_assets' / 'geo')
    ATLAS = Path(atlas_dir) if atlas_dir else next((p for p in ATLAS_DIRS if (p / 'land-50m.json').exists()), None)
    if ATLAS is None or not all((GEO / f).exists() for f in ('shapes.json', 'places.json', 'lakes.json')):
        return None
    shapes = json.loads((GEO / 'shapes.json').read_text(encoding='utf-8'))
    places = json.loads((GEO / 'places.json').read_text(encoding='utf-8'))
    lakes = json.loads((GEO / 'lakes.json').read_text(encoding='utf-8'))['lakes']
    land = json.loads((ATLAS / 'land-50m.json').read_text(encoding='utf-8'))

    label = {c['id']: c for c in places['countries']}
    countries = []
    for key, geom in shapes.items():
        if not key.startswith('c:'):
            continue
        _, iso, name = key.split(':', 2)
        if iso == 'ATA':
            continue
        c = label.get(key, {})
        countries.append({'iso': iso, 'name': name, 'lat': c.get('lat'), 'lng': c.get('lng'),
                          'area': c.get('area', 0), 'coords': pack(shrink(geom['coordinates'], 0.05, 0.02))})

    provinces = {}
    pmeta = {(p['iso2'], p['name']): p for p in places['provinces'] if p.get('name')}
    by_name = {}
    for p in places['provinces']:
        if p.get('name'):
            by_name.setdefault(p['name'], []).append(p)
    iso3_to_2 = {c['id'].split(':')[1]: c['iso2'] for c in places['countries']}
    for k, (iso3, name) in PROVINCES.items():
        cands = [p for p in by_name.get(name, []) if p['id'].startswith('p:' + iso3 + '-')]
        if not cands:
            continue
        p = cands[0]
        geom = shapes.get(p['id'])
        if not geom:
            continue
        provinces[k] = {'id': p['id'], 'name': name, 'lat': p['lat'], 'lng': p['lng'],
                        'coords': pack(shrink(geom['coordinates'], 0.006, 0.0005))}

    keep_lakes = []
    for lk in lakes:
        b = lk['bbox']
        if (b[2] - b[0]) * (b[3] - b[1]) < 1.6 and lk['name'] not in ('Lake Titicaca', 'Titicaca'):
            continue
        rings = [[[round(x, 2), round(y, 2)] for x, y in simplify(r, 0.04)] for r in lk['rings']]
        rings = [r for r in rings if len(r) >= 4]
        if rings:
            keep_lakes.append({'name': lk['name'], 'rings': pack([rings])[0]})

    fields = places['towns_fields']
    ix = {f: i for i, f in enumerate(fields)}
    towns, seen = [], set()
    w, s, e, n = SKIP_TOWNS_NEAR_CRIMEA
    for t in places['towns']:
        name, lat, lng, pop, code = t[ix['name']], t[ix['lat']], t[ix['lng']], t[ix['population']] or 0, t[ix['feature_code']]
        if w < lng < e and s < lat < n:
            continue
        if pop >= 900000 or code == 'PPLC' or name in EXTRA_TOWNS:
            k = (name, round(lat), round(lng))
            if k in seen:
                continue
            seen.add(k)
            towns.append([name, round(lat, 3), round(lng, 3), pop, t[ix['iso2']], 1 if code == 'PPLC' else 0])

    data = {'land': land, 'countries': countries, 'provinces': provinces, 'lakes': keep_lakes, 'towns': towns}
    txt = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return ('// Built by web/geo.py from world-atlas land-50m and the video\'s own Natural Earth shapes.\n'
            'window.ATLAS_GEO = ' + txt + ';\n')


def load() -> str | None:
    """Build it, or fall back to the design's prebuilt copy on the Mac."""
    try:
        text = build()
    except Exception:
        text = None
    if text is None and PREBUILT.exists():
        text = PREBUILT.read_text(encoding="utf-8")
    return text
