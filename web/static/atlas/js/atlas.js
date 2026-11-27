// The atlas: the dotted map, drawn the way the videos draw theirs (stringer/render/src/map.js):
// green dotted land, deep-blue sea in short dashes with white and vermilion specks, white dotted borders,
// warm dots for the place being talked about, italic serif names, a vermilion pin.
// Heavy layers are painted once and reused; a camera move only scales the cached layer, and a sharp layer
// is painted when the camera comes to rest.
(function () {
  'use strict';

  const PAL = {
    paper: '#F3EEE1', paperDeep: '#E9E2CF', ink: '#1A2A86', inkSoft: 'rgba(26,42,134,0.76)', tag: '#B5401F',
    sea: '#1E3191', land: '#2A6E3A', vermilion: '#E8622C', mustard: '#E0A12A', cobalt: '#3552BE', sky: '#A8C9EA',
    sideA: '#3552BE', sideB: '#C2452D', other: '#9AA3B8', skyA: [121, 171, 219], skyB: [168, 201, 234],
  };
  const LAND = ['#1E5E34', '#2E7D3F', '#2E7D3F', '#4E9F4E', '#86BE5C', '#2B3F9E', '#163F26', '#5FA857'];
  const WARM = ['#E0A12A', '#E8743B', '#E8622C', '#F0B347', '#C9862A', '#E0A12A'];
  const SEA = ['#1A2A86', '#22389C', '#22389C', '#3552BE', '#1A2A86', '#2A47B0'];

  // Seeded random numbers (same generator as the videos), so a layer looks the same every time.
  function rng(seed) {
    let s = Math.abs(Math.floor(seed)) % 2147483647;
    if (s <= 0) s += 2147483646;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  }
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const easeOut = (v) => 1 - Math.pow(1 - clamp01(v), 3);
  const easeInOut = (v) => { const x = clamp01(v); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function canvas(w, h) {
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(w));
    c.height = Math.max(1, Math.round(h));
    return c;
  }

  // ---- the data (js/data/geo.js) ---------------------------------------------------------------------------
  let world = null;
  function unpack(flat) {
    const out = [];
    let x = 0, y = 0;
    for (let i = 0; i < flat.length; i += 2) { x += flat[i]; y += flat[i + 1]; out.push([x / 100, y / 100]); }
    return out;
  }
  function data() {
    if (world) return world;
    const G = window.ATLAS_GEO;
    if (!G || !window.d3 || !window.topojson) return null;
    // land: polygons wound the wrong way read as "the whole globe except this island"; turn those round (map.js)
    const fc = topojson.feature(G.land, G.land.objects.land);
    const polys = [];
    for (const f of fc.features || [fc]) {
      const g = f.geometry || f;
      for (const poly of g.type === 'Polygon' ? [g.coordinates] : g.coordinates) {
        const one = {type: 'Polygon', coordinates: poly};
        polys.push(d3.geoArea(one) > 2 * Math.PI ? poly.map((r) => r.slice().reverse()) : poly);
      }
    }
    const land = {type: 'MultiPolygon', coordinates: polys};
    const countries = G.countries.map((c) => {
      const coordinates = c.coords.map((poly) => poly.map(unpack));
      let w = 180, s = 90, e = -180, n = -90;
      for (const poly of coordinates) for (const [x, y] of poly[0]) { if (x < w) w = x; if (x > e) e = x; if (y < s) s = y; if (y > n) n = y; }
      return {iso: c.iso, name: c.name, lat: c.lat, lng: c.lng, area: c.area, bbox: [w, s, e, n], shape: {type: 'MultiPolygon', coordinates}};
    });
    const provinces = {};
    for (const [k, p] of Object.entries(G.provinces)) {
      provinces[k] = {name: p.name, lat: p.lat, lng: p.lng, shape: {type: 'MultiPolygon', coordinates: p.coords.map((poly) => poly.map(unpack))}};
    }
    const lakes = G.lakes.map((l) => ({name: l.name, rings: l.rings.map(unpack)}));
    const towns = G.towns.map(([name, lat, lng, pop, iso2, capital]) => ({name, lat, lng, pop, iso2, capital}));
    world = {land, countries, provinces, lakes, towns, byIso: Object.fromEntries(countries.map((c) => [c.iso, c]))};
    return world;
  }

  // ---- Mercator camera --------------------------------------------------------------------------------------
  // A camera is {x, y, s}: the Mercator point in the middle of the view focus (x = longitude in radians,
  // y = ln tan(pi/4 + lat/2)) and s, pixels per radian.
  const R = Math.PI / 180;
  const mx = (lng) => lng * R;
  const my = (lat) => Math.log(Math.tan(Math.PI / 4 + Math.max(-85, Math.min(85, lat)) * R / 2));
  const lngOf = (x) => x / R;
  const latOf = (y) => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / R;

  function projectionFor(cam, fx, fy) {
    return d3.geoMercator().scale(cam.s).translate([fx - cam.s * cam.x, fy + cam.s * cam.y]);
  }
  // The camera that fits [west, south, east, north] into a box {x, y, w, h} (CSS px) of the view.
  function fitCamera(bounds, box, maxS) {
    const [w, s, e, n] = bounds;
    const dx = mx(e) - mx(w), dy = my(n) - my(s);
    let sc = Math.min(box.w / Math.max(dx, 1e-6), box.h / Math.max(dy, 1e-6));
    if (maxS) sc = Math.min(sc, maxS);
    return {x: (mx(e) + mx(w)) / 2, y: (my(n) + my(s)) / 2, s: sc};
  }

  // Smooth zoom (van Wijk and Nuij, as d3.interpolateZoom): a = [x, y, width], b = [x, y, width].
  function interpolateZoom(a, b) {
    const rho = Math.SQRT2, rho2 = 2, rho4 = 4;
    const [ux0, uy0, w0] = a, [ux1, uy1, w1] = b;
    const dx = ux1 - ux0, dy = uy1 - uy0, d2 = dx * dx + dy * dy;
    let f, S;
    if (d2 < 1e-12) {
      S = Math.log(w1 / w0) / rho;
      f = (t) => [ux0 + t * dx, uy0 + t * dy, w0 * Math.exp(rho * t * S)];
    } else {
      const d1 = Math.sqrt(d2);
      const b0 = (w1 * w1 - w0 * w0 + rho4 * d2) / (2 * w0 * rho2 * d1);
      const b1 = (w1 * w1 - w0 * w0 - rho4 * d2) / (2 * w1 * rho2 * d1);
      const r0 = Math.log(Math.sqrt(b0 * b0 + 1) - b0), r1 = Math.log(Math.sqrt(b1 * b1 + 1) - b1);
      S = (r1 - r0) / rho;
      f = (t) => {
        const s = t * S, c0 = Math.cosh(r0);
        const u = (w0 / (rho2 * d1)) * (c0 * Math.tanh(rho * s + r0) - Math.sinh(r0));
        return [ux0 + u * dx, uy0 + u * dy, (w0 * c0) / Math.cosh(rho * s + r0)];
      };
    }
    f.duration = Math.max(0, S * 1000 * rho / Math.SQRT2);
    return f;
  }

  // ---- dot sprites ------------------------------------------------------------------------------------------
  const sprites = new Map();
  function sprite(color, rad) {      // rad in device px
    const key = color + rad.toFixed(2);
    let c = sprites.get(key);
    if (!c) {
      const size = Math.ceil(rad * 2 + 2);
      c = canvas(size, size);
      const x = c.getContext('2d');
      x.fillStyle = color;
      x.beginPath();
      x.arc(size / 2, size / 2, rad, 0, 6.2832);
      x.fill();
      sprites.set(key, c);
    }
    return c;
  }

  // ---- the paper sky: cream with blue halftone grain in 2 x 2 blocks, heavier at the top (style.js paintGrain)
  function paintGrain(c, seed, density) {
    const ctx = c.getContext('2d');
    const r = rng(seed);
    const W = c.width, H = c.height;
    const img = ctx.createImageData(W, H);
    const d = img.data;
    const blk = 2;
    for (let by = 0; by < H; by += blk) {
      const pb = density(by / H);
      for (let bx = 0; bx < W; bx += blk) {
        let c0 = 243, c1 = 238, c2 = 225;
        if (pb > 0 && r() < pb) { const s = r() < 0.55 ? PAL.skyA : PAL.skyB; c0 = s[0]; c1 = s[1]; c2 = s[2]; }
        const n = (r() - 0.5) * 12;
        for (let oy = 0; oy < blk && by + oy < H; oy++) {
          for (let ox = 0; ox < blk && bx + ox < W; ox++) {
            const i = ((by + oy) * W + bx + ox) * 4;
            d[i] = c0 + n; d[i + 1] = c1 + n; d[i + 2] = c2 + n; d[i + 3] = 255;
          }
        }
      }
    }
    ctx.putImageData(img, 0, 0);
    return c;
  }

  // ---- paths made once, at a fixed Mercator scale ------------------------------------------------------------
  const UNIT = 1000;
  let unit = null;
  const unitProj = () => d3.geoMercator().scale(UNIT).translate([0, 0]).precision(0);
  function unitPaths() {
    if (unit) return unit;
    const W = data();
    const P = unitProj();
    const land = new Path2D(d3.geoPath(P)(W.land));
    const lakes = new Path2D();
    for (const lk of W.lakes) for (const ring of lk.rings) {
      ring.forEach((pt, i) => { const q = P(pt); if (i) lakes.lineTo(q[0], q[1]); else lakes.moveTo(q[0], q[1]); });
      lakes.closePath();
    }
    // every country's rings as flat [x, y, x, y, ...] at the fixed scale, with its box, for the borders
    const rings = W.countries.map((c) => {
      const rs = [];
      for (const poly of c.shape.coordinates) for (const ring of poly) {
        const f = new Float32Array(ring.length * 2);
        ring.forEach((pt, i) => { const q = P(pt); f[2 * i] = q[0]; f[2 * i + 1] = q[1]; });
        rs.push(f);
      }
      const a = P([c.bbox[0], Math.min(84, c.bbox[3])]), b = P([c.bbox[2], Math.max(-84, c.bbox[1])]);
      return {rs, box: [a[0], a[1], b[0], b[1]]};
    });
    unit = {land, lakes, rings};
    return unit;
  }
  const regionPaths = new WeakMap();
  function unitPath(shape) {
    let p = regionPaths.get(shape);
    if (!p) {
      const P = unitProj();
      p = new Path2D();
      for (const poly of shape.coordinates) for (const ring of poly) {
        ring.forEach((pt, i) => { const q = P(pt); if (i) p.lineTo(q[0], q[1]); else p.moveTo(q[0], q[1]); });
        p.closePath();
      }
      regionPaths.set(shape, p);
    }
    return p;
  }

  // ---- the dotted map layer ---------------------------------------------------------------------------------
  // opts: {w, h (CSS px), dpr, proj (d3 projection in CSS px), seed, region (GeoJSON) | null, step, borders}
  // Returns {base, lit, outline}: the map, a copy of just the region's land in warm dots (to fade in), and the
  // region's outline as projected rings (to draw as dots, a bit more each frame).
  function paintLayer(opts) {
    const W = data();
    const {w, h, proj} = opts;
    const dpr = opts.dpr || 1;
    const step = opts.step || 3.4;
    const cw = Math.ceil(w), ch = Math.ceil(h);

    const T = [performance.now()];
    // land mask at CSS resolution, lakes cut back out (the video draws lakes as water). The land is one Path2D
    // made once at a fixed scale; each layer only sets a transform, so nothing is projected again.
    const U = unitPaths();
    const k = proj.scale() / UNIT, [tx, ty] = proj.translate();
    const m = canvas(cw, ch);
    const mc = m.getContext('2d', {willReadFrequently: true});
    mc.setTransform(k, 0, 0, k, tx, ty);
    mc.fillStyle = '#000';
    mc.fill(U.land);
    mc.globalCompositeOperation = 'destination-out';
    mc.fill(U.lakes, 'evenodd');
    const md = mc.getImageData(0, 0, cw, ch).data;
    const landAt = new Uint8Array(cw * ch);
    for (let i = 0, j = 3; i < landAt.length; i++, j += 4) landAt[i] = md[j] > 127 ? 1 : 0;
    const isLand = (x, y) => {
      const ix = x | 0, iy = y | 0;
      if (ix < 0 || iy < 0 || ix >= cw || iy >= ch) return false;
      return landAt[iy * cw + ix] === 1;
    };
    let inRegion = null;
    if (opts.region) {
      const rm = canvas(cw, ch);
      const rc = rm.getContext('2d', {willReadFrequently: true});
      rc.setTransform(k, 0, 0, k, tx, ty);
      rc.fillStyle = '#000';
      rc.fill(unitPath(opts.region), 'evenodd');
      const rd = rc.getImageData(0, 0, cw, ch).data;
      inRegion = (x, y) => {
        const ix = x | 0, iy = y | 0;
        if (ix < 0 || iy < 0 || ix >= cw || iy >= ch) return false;
        return rd[(iy * cw + ix) * 4 + 3] > 127 && landAt[iy * cw + ix] === 1;
      };
    }
    T.push(performance.now());

    // sea and land base colours straight into the pixels, then every dot stamped in (no canvas call per dot)
    const base = canvas(cw * dpr, ch * dpr);
    const bc = base.getContext('2d');
    const BW = base.width, BH = base.height;
    const img = new ImageData(BW, BH);
    const px8 = img.data;
    const u32 = new Uint32Array(px8.buffer);
    const abgr = (hex) => { const [r0, g0, b0] = rgbOf(hex); return (255 << 24) | (b0 << 16) | (g0 << 8) | r0; };
    const SEA32 = abgr(PAL.sea), LAND32 = abgr(PAL.land);
    for (let y = 0; y < BH; y++) {
      const row = ((y / dpr) | 0) * cw;
      const o = y * BW;
      for (let x = 0; x < BW; x++) u32[o + x] = landAt[row + ((x / dpr) | 0)] ? LAND32 : SEA32;
    }
    let lit = null, litImg = null;
    if (inRegion) { lit = canvas(BW, BH); litImg = new ImageData(BW, BH); }
    T.push(performance.now());

    const r = rng(opts.seed || 11);
    const sy = step * 0.9;
    const radii = [0.30, 0.36, 0.42, 0.47].map((k) => k * step * dpr);
    const landRGB = LAND.map(rgbOf), warmRGB = WARM.map(rgbOf), seaRGB = SEA.map(rgbOf);
    const rare1 = rgbOf('#E8743B'), rare2 = rgbOf('#C9DE8A');
    const sVer = rgbOf(PAL.vermilion), sWhite = rgbOf('#E9EEF6'), sLight = rgbOf('#7FA4E2');
    const dh = Math.max(1, 0.38 * sy * dpr);
    for (let y = 1; y < ch; y += sy) {
      for (let x = 0; x < cw; x += step) {
        const px = x + (r() - 0.5) * step * 0.7, py = y + (r() - 0.5) * sy * 0.6;
        const q = r();
        const ri = Math.floor(r() * radii.length);
        const pk = r();
        if (isLand(px, py)) {
          const col = q < 0.01 ? rare1 : q < 0.03 ? rare2 : landRGB[Math.floor(pk * landRGB.length)];
          stamp(px8, BW, BH, px * dpr, py * dpr, radii[ri], col);
          if (inRegion && inRegion(px, py)) stamp(litImg.data, BW, BH, px * dpr, py * dpr, radii[ri], warmRGB[Math.floor(pk * warmRGB.length)]);
        } else {
          const col = q < 0.01 ? sVer : q < 0.045 ? sWhite : q < 0.11 ? sLight : seaRGB[Math.floor(pk * seaRGB.length)];
          dash(px8, BW, BH, px * dpr, py * dpr, (step * 0.7 + r() * step * 1.2) * dpr, dh, col);
        }
      }
    }
    T.push(performance.now());
    bc.putImageData(img, 0, 0);
    if (lit) lit.getContext('2d').putImageData(litImg, 0, 0);

    if (opts.borders !== false) drawBorders(bc, k, tx, ty, cw, ch, dpr, isLand, opts.borderAlpha || 0.8, step);
    T.push(performance.now());
    paintLayer.last = T.map((t, i) => (i ? Math.round(t - T[i - 1]) : 0)).join(',');
    let outline = null;
    if (opts.region) outline = projectRings(proj, opts.region);
    return {base, lit, outline, proj, isLand};
  }

  function rgbOf(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  // An anti-aliased round dot blended into an RGBA buffer.
  function stamp(d, W, H, cx, cy, rad, col) {
    const x0 = Math.max(0, Math.floor(cx - rad - 1)), x1 = Math.min(W - 1, Math.ceil(cx + rad + 1));
    const y0 = Math.max(0, Math.floor(cy - rad - 1)), y1 = Math.min(H - 1, Math.ceil(cy + rad + 1));
    const [cr, cg, cb] = col;
    for (let y = y0; y <= y1; y++) {
      const dy = y + 0.5 - cy;
      for (let x = x0; x <= x1; x++) {
        const dx = x + 0.5 - cx;
        const a = rad + 0.5 - Math.sqrt(dx * dx + dy * dy);
        if (a <= 0) continue;
        const i = (y * W + x) * 4;
        if (a >= 1) { d[i] = cr; d[i + 1] = cg; d[i + 2] = cb; d[i + 3] = 255; continue; }
        const da = d[i + 3] / 255;
        const oa = a + da * (1 - a);
        d[i] = (cr * a + d[i] * da * (1 - a)) / oa;
        d[i + 1] = (cg * a + d[i + 1] * da * (1 - a)) / oa;
        d[i + 2] = (cb * a + d[i + 2] * da * (1 - a)) / oa;
        d[i + 3] = oa * 255;
      }
    }
  }
  // A short horizontal dash (the sea's texture), soft at its two ends.
  function dash(d, W, H, x, y, len, h, col) {
    const y0 = Math.max(0, Math.round(y)), y1 = Math.min(H - 1, Math.round(y + h) - 1);
    const xa = Math.max(0, Math.floor(x)), xb = Math.min(W - 1, Math.ceil(x + len));
    const [cr, cg, cb] = col;
    for (let yy = y0; yy <= Math.max(y0, y1); yy++) {
      for (let xx = xa; xx <= xb; xx++) {
        const a = Math.min(1, Math.max(0, Math.min(xx + 1 - x, x + len - xx)));
        if (a <= 0) continue;
        const i = (yy * W + xx) * 4;
        d[i] = d[i] + (cr - d[i]) * a; d[i + 1] = d[i + 1] + (cg - d[i + 1]) * a; d[i + 2] = d[i + 2] + (cb - d[i + 2]) * a;
      }
    }
  }

  function ringsPath(ctx, proj, rings) {
    for (const ring of rings) {
      let first = true;
      for (const pt of ring) {
        const p = proj(pt);
        if (!p) continue;
        if (first) { ctx.moveTo(p[0], p[1]); first = false; } else ctx.lineTo(p[0], p[1]);
      }
      ctx.closePath();
    }
  }

  function projectRings(proj, shape) {
    const out = [];
    for (const poly of shape.coordinates) {
      const ring = poly[0].map((p) => proj(p)).filter(Boolean);
      if (ring.length > 2) out.push(ring);
    }
    return out;
  }

  // White dotted borders between countries. The country rings come from the video's own shapes (Crimea is in
  // Ukraine there). Coastline stretches are skipped: a dot is kept only where there is land on both sides.
  function drawBorders(ctx, k, tx, ty, cw, ch, dpr, isLand, alpha, step) {
    const U = unitPaths();
    const gap = Math.max(3.6, step * 1.3);
    const rad = Math.max(0.6, step * 0.27) * dpr;
    const gw = Math.ceil(cw / 2);
    const occupied = new Uint8Array(gw * Math.ceil(ch / 2));
    ctx.fillStyle = `rgba(243,238,225,${alpha})`;
    ctx.beginPath();
    for (const c of U.rings) {
      const ax = k * c.box[0] + tx, ay = k * c.box[1] + ty, bx = k * c.box[2] + tx, by = k * c.box[3] + ty;
      if (bx < -20 || ax > cw + 20 || by < -20 || ay > ch + 20) continue;
      if (bx - ax < 6 && by - ay < 6) continue;
      for (const f of c.rs) {
        let carry = 0;
        let px = k * f[0] + tx, py = k * f[1] + ty;
        for (let i = 2; i < f.length; i += 2) {
          const x2 = k * f[i] + tx, y2 = k * f[i + 1] + ty;
          const dx = x2 - px, dy = y2 - py;
          const len = Math.hypot(dx, dy);
          const off = (px < -gap && x2 < -gap) || (py < -gap && y2 < -gap) || (px > cw + gap && x2 > cw + gap) || (py > ch + gap && y2 > ch + gap);
          if (len > 0 && len < cw && !off) {
            const nx = -dy / len, ny = dx / len;
            for (let d = carry; d < len; d += gap) {
              const x = px + (dx * d) / len, y = py + (dy * d) / len;
              if (x < 0 || y < 0 || x >= cw || y >= ch) continue;
              if (!isLand(x + nx * 3, y + ny * 3) || !isLand(x - nx * 3, y - ny * 3)) continue;
              const gi = ((y / 2) | 0) * gw + ((x / 2) | 0);
              if (occupied[gi]) continue;
              occupied[gi] = 1;
              ctx.moveTo(x * dpr + rad, y * dpr);
              ctx.arc(x * dpr, y * dpr, rad, 0, 6.2832);
            }
            carry = ((carry - len) % gap + gap) % gap;
          } else carry = 0;
          px = x2; py = y2;
        }
      }
    }
    ctx.fill();
  }

  // ---- small drawing helpers shared by the pages -------------------------------------------------------------
  // Dots along a projected polyline up to frac of its length (the outline that draws itself, map.js dottedOutline)
  function dottedRings(ctx, rings, frac, {color = PAL.paper, step = 4, rad = 1.1} = {}) {
    let total = 0;
    for (const ring of rings) for (let i = 1; i < ring.length; i++) total += Math.hypot(ring[i][0] - ring[i - 1][0], ring[i][1] - ring[i - 1][1]);
    const upto = total * clamp01(frac);
    let run = 0;
    ctx.fillStyle = color;
    for (const ring of rings) {
      let carry = 0;
      for (let i = 1; i < ring.length; i++) {
        const [x1, y1] = ring[i - 1], [x2, y2] = ring[i];
        const len = Math.hypot(x2 - x1, y2 - y1);
        for (let d = carry; d < len; d += step) {
          if (run + d > upto) return;
          ctx.beginPath();
          ctx.arc(x1 + ((x2 - x1) * d) / len, y1 + ((y2 - y1) * d) / len, rad, 0, 6.2832);
          ctx.fill();
        }
        carry = ((carry - len) % step + step) % step;
        run += len;
      }
    }
  }

  // A dotted arc from A to B (the video's map_link), up to frac.
  function dottedArc(ctx, A, B, frac, {color = PAL.vermilion, rad = 1.3, lift = 0.35, gap = 5} = {}) {
    const len = Math.hypot(B[0] - A[0], B[1] - A[1]);
    const Q = [(A[0] + B[0]) / 2, Math.min(A[1], B[1]) - Math.max(12, len * lift)];
    const n = Math.max(2, Math.round((len * 1.15) / gap));
    ctx.fillStyle = color;
    const upto = clamp01(frac);
    for (let i = 0; i <= n; i++) {
      const u = i / n;
      if (u > upto) break;
      const x = (1 - u) ** 2 * A[0] + 2 * (1 - u) * u * Q[0] + u * u * B[0];
      const y = (1 - u) ** 2 * A[1] + 2 * (1 - u) * u * Q[1] + u * u * B[1];
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, 6.2832);
      ctx.fill();
    }
    return Q;
  }
  function arcPoint(A, B, u, lift = 0.35) {
    const len = Math.hypot(B[0] - A[0], B[1] - A[1]);
    const Q = [(A[0] + B[0]) / 2, Math.min(A[1], B[1]) - Math.max(12, len * lift)];
    return [(1 - u) ** 2 * A[0] + 2 * (1 - u) * u * Q[0] + u * u * B[0], (1 - u) ** 2 * A[1] + 2 * (1 - u) * u * Q[1] + u * u * B[1]];
  }

  // ---- text that decodes from braille dots into letters (the videos' decode effect) ---------------------------
  // Every letter keeps its own width while it is still dots, so nothing jumps as it decodes.
  const BRAILLE = [];
  (function makeCells() {
    const r = rng(4242);
    for (let k = 0; k < 18; k++) {
      let dots = '';
      let any = false;
      for (let col = 0; col < 2; col++) for (let row = 0; row < 4; row++) {
        if (r() < 0.5) { any = true; dots += `<circle cx="${col ? 6.8 : 3.2}" cy="${2 + row * 4}" r="1.15"/>`; }
      }
      if (!any) dots += '<circle cx="3.2" cy="6" r="1.15"/>';
      BRAILLE.push(`url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 16'>${dots}</svg>`)}")`);
    }
  })();

  function decodeInto(el, text, {speed = 28, delay = 0, onDone} = {}) {
    if (el._decodeTimer) { clearTimeout(el._decodeTimer); cancelAnimationFrame(el._decodeRaf); }
    el.setAttribute('aria-label', text);
    if (reduced()) { el.textContent = text; el.removeAttribute('aria-label'); if (onDone) onDone(); return; }
    el.textContent = '';
    const frag = document.createDocumentFragment();
    const spans = [];
    // words stay whole on a line: one inline-block per word
    const words = String(text).split(/(\s+)/);
    for (const w of words) {
      if (/^\s+$/.test(w)) { frag.appendChild(document.createTextNode(w)); continue; }
      if (!w) continue;
      const wspan = document.createElement('span');
      wspan.className = 'dw';
      wspan.setAttribute('aria-hidden', 'true');
      for (const ch of w) {
        const s = document.createElement('span');
        s.className = 'dc';
        s.textContent = ch;
        s.style.setProperty('--m', BRAILLE[(Math.random() * BRAILLE.length) | 0]);
        wspan.appendChild(s);
        spans.push(s);
      }
      frag.appendChild(wspan);
    }
    el.appendChild(frag);
    const t0 = performance.now() + delay;
    let shuffle = 0;
    const tick = (now) => {
      const n = Math.floor((now - t0) / speed);
      for (let i = 0; i < spans.length; i++) {
        if (i < n) spans[i].classList.add('on');
      }
      if (++shuffle % 6 === 0) {
        for (let i = Math.max(0, n); i < spans.length; i++) spans[i].style.setProperty('--m', BRAILLE[(Math.random() * BRAILLE.length) | 0]);
      }
      if (n < spans.length) el._decodeRaf = requestAnimationFrame(tick);
      else { el.textContent = text; el.removeAttribute('aria-label'); if (onDone) onDone(); }
    };
    el._decodeRaf = requestAnimationFrame(tick);
  }

  window.Atlas = {
    PAL, LAND, WARM, SEA, rng, clamp01, easeOut, easeInOut, reduced, canvas, data,
    mx, my, lngOf, latOf, projectionFor, fitCamera, interpolateZoom,
    paintGrain, paintLayer, dottedRings, dottedArc, arcPoint, decodeInto, sprite,
  };
})();
