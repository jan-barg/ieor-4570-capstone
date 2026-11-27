// Landing: a dotted globe turns to Antwerp and zooms in as you scroll, then the seven steps of making a video play
// out on the flat map of the videos. One sticky canvas sits behind the text. Map layers are painted once per size and
// reused; the globe is drawn cell by cell into a pixel buffer (screen-fixed dot grid, like the videos' flat maps).
(function () {
  'use strict';
  const A = window.Atlas, S = window.Stories, P = window.Posters;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const RM = A.reduced();
  const DEG = Math.PI / 180;
  const W = A.data();
  const ANT = {lng: 4.40, lat: 51.22};
  const item = S.byId['v-antwerp'];
  const STEPS = S.D.steps;

  // Invented outlets, given invented home cities so their articles have somewhere to come from.
  const OUTLETS = [
    {name: 'Union Voice', side: 'a', lat: 40.42, lng: -3.70, n: 2},
    {name: 'Lantern Post', side: 'a', lat: 59.33, lng: 18.07, n: 2},
    {name: 'Market Ledger', side: 'b', lat: 40.71, lng: -74.0, n: 2},
    {name: 'Harbor Courier', side: 'b', lat: 1.35, lng: 103.82, n: 2},
    {name: 'Atlas Wire', side: 'o', lat: -1.29, lng: 36.82, n: 1},
    {name: 'Northbridge News', side: 'o', lat: 53.35, lng: -6.26, n: 1},
  ];
  const SIDE = {a: A.PAL.sideA, b: A.PAL.sideB, o: '#AEB6CB'};
  const TINT = {a: '#A9BDFF', b: '#FFA68C', o: '#DCE0EA'};      // lighter versions for lines drawn over the sea
  const ARTICLES = [];
  OUTLETS.forEach((o, i) => { for (let j = 0; j < o.n; j++) ARTICLES.push({o, i, j}); });

  const scene = $('#scene'), mapC = $('#map'), grainC = $('#grain'), placeEl = $('#place'), railEl = $('#rail');
  const ctx = mapC.getContext('2d');
  const stepEls = $$('.step');
  const phone = () => window.innerWidth < 900;
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (v) => { const x = A.clamp01(v); return x * x * (3 - 2 * x); };

  let VW = 0, VH = 0, dpr = 1, box = null, focal = null, cams = null, hero = null;
  const layers = {};

  // ---- layout ------------------------------------------------------------------------------------------------------
  function layout() {
    VW = scene.clientWidth; VH = scene.clientHeight;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    mapC.width = Math.round(VW * dpr); mapC.height = Math.round(VH * dpr);
    grainC.width = Math.round(VW * Math.min(dpr, 1.5)); grainC.height = Math.round(VH * Math.min(dpr, 1.5));
    A.paintGrain(grainC, 11, (y) => 0.34 * Math.pow(1 - y, 2.3) + 0.012);
    // keep the grain light behind the hero text, heavy only in the sky over it (as in the videos' sky band)
    const gx = grainC.getContext('2d');
    const fade = gx.createLinearGradient(0, 0, grainC.width * (phone() ? 1 : 0.62), 0);
    fade.addColorStop(0, 'rgba(243,238,225,0.82)'); fade.addColorStop(0.75, 'rgba(243,238,225,0.6)'); fade.addColorStop(1, 'rgba(243,238,225,0)');
    gx.fillStyle = fade;
    gx.fillRect(0, grainC.height * 0.1, grainC.width * (phone() ? 1 : 0.62), grainC.height * 0.9);
    box = phone() ? {x: 12, y: 104, w: VW - 24, h: VH * 0.54 - 104} : {x: VW * 0.4, y: 76, w: VW * 0.6 - 90, h: VH - 120};
    focal = {x: box.x + box.w / 2, y: box.y + box.h / 2};
    const ex = A.mx(ANT.lng), ey = A.my(ANT.lat);
    cams = {
      world: A.fitCamera([-80, -36, 110, 58], box),
      europe: {x: ex, y: ey, s: A.fitCamera([-5, 46.6, 14, 55.8], box).s},
      ant: {x: ex, y: ey, s: A.fitCamera([3.0, 50.55, 5.9, 51.75], box).s},
    };
    const R0t = Math.min(VW * 0.42, 340);
    hero = phone()
      ? (VW >= 560 ? {cx: VW / 2, cy: VH * 0.47 + R0t, R0: R0t} : {cx: VW / 2, cy: VH + Math.min(VW * 0.5, 230) * 0.18, R0: Math.min(VW * 0.62, 300)})
      : {cx: VW * 0.73, cy: VH * 0.55, R0: Math.min(VW * 0.25, VH * 0.39)};
    for (const k of Object.keys(layers)) delete layers[k];
    sizeGlobe();
    if (cur) cur.cam = camFor(cur.k);
  }

  // ---- flat map layers ---------------------------------------------------------------------------------------------
  function layer(key) {
    if (layers[key]) return layers[key];
    const cam = cams[key];
    const proj = A.projectionFor(cam, focal.x, focal.y);
    const region = key !== 'world' && W.provinces.antwerp ? W.provinces.antwerp.shape : null;
    const L = A.paintLayer({w: VW, h: VH, dpr, proj, seed: 23 + key.length * 7, region, step: 3.4});
    layers[key] = {cam, L};
    return layers[key];
  }
  // Where a layer painted for camera lc lands under camera cam: a plain scale and shift (both are Mercator).
  function placeOf(lc, cam) {
    const k = cam.s / lc.s;
    return {k, ox: focal.x - k * focal.x + cam.s * (lc.x - cam.x), oy: focal.y - k * focal.y - cam.s * (lc.y - cam.y)};
  }
  function drawImg(img, lc, cam, alpha) {
    if (!img || alpha <= 0) return;
    const {k, ox, oy} = placeOf(lc, cam);
    ctx.globalAlpha = alpha;
    ctx.drawImage(img, ox * dpr, oy * dpr, img.width * k, img.height * k);
    ctx.globalAlpha = 1;
  }
  function drawFlat(cam, alpha, litA, outlineFrac) {
    const need = (key) => {
      if (key === 'world') return 1;
      const k = cam.s / cams[key].s;
      return smooth((k - 0.45) / 0.4);
    };
    const nE = need('europe'), nA = need('ant');
    const kE = cam.s / cams.europe.s, kA = cam.s / cams.ant.s;
    ctx.globalAlpha = alpha; ctx.fillStyle = A.PAL.sea; ctx.fillRect(0, 0, mapC.width, mapC.height); ctx.globalAlpha = 1;
    if (!(nE >= 1 && kE >= 1) && !(nA >= 1 && kA >= 1)) drawImg(layer('world').L.base, cams.world, cam, alpha);
    if (nE > 0 && !(nA >= 1 && kA >= 1)) drawImg(layer('europe').L.base, cams.europe, cam, alpha * nE);
    if (nA > 0) drawImg(layer('ant').L.base, cams.ant, cam, alpha * nA);
    // the province lit warm, and its outline drawing itself (the video's map-locate shot)
    if (litA > 0 && kE > 0.5) {
      const src = nA > 0.5 ? 'ant' : 'europe';
      drawImg(layer(src).L.lit, cams[src], cam, alpha * litA);
    }
    if (outlineFrac > 0 && kA > 0.5) {
      const lc = cams.ant, {k, ox, oy} = placeOf(lc, cam);
      const L = layer('ant').L;
      if (L.outline) {
        ctx.save();
        ctx.setTransform(dpr * k, 0, 0, dpr * k, ox * dpr, oy * dpr);
        ctx.globalAlpha = alpha;
        A.dottedRings(ctx, L.outline, outlineFrac, {step: 4.4 / k, rad: 1.15 / k});
        ctx.restore();
      }
    }
  }
  const proj = (cam) => A.projectionFor(cam, focal.x, focal.y);

  // ---- the globe ---------------------------------------------------------------------------------------------------
  const MW = 2048, MH = 1024;
  let mask = null, gC = null, gCtx = null, gImg = null, g32 = null, gd = 1;
  function buildMask() {
    const c = A.canvas(MW, MH);
    const x = c.getContext('2d', {willReadFrequently: true});
    const pr = d3.geoEquirectangular().scale(MW / (2 * Math.PI)).translate([MW / 2, MH / 2]);
    x.fillStyle = '#000';
    x.beginPath(); d3.geoPath(pr, x)(W.land); x.fill();
    const d = x.getImageData(0, 0, MW, MH).data;
    mask = new Uint8Array(MW * MH);
    for (let i = 0, j = 3; i < mask.length; i++, j += 4) mask[i] = d[j] > 127 ? 1 : 0;
  }
  function sizeGlobe() {
    gd = Math.min(dpr, 1.5);
    gC = A.canvas(VW * gd, VH * gd);
    gCtx = gC.getContext('2d');
    gImg = new ImageData(gC.width, gC.height);
    g32 = new Uint32Array(gImg.data.buffer);
  }
  const rgbOf = (hex) => { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
  const u32 = (hex) => { const [r, g, b] = rgbOf(hex); return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0; };
  const LANDc = A.LAND.map(u32), SEAc = A.SEA.map(u32);
  const LAND0 = u32(A.PAL.land), SEA0 = u32(A.PAL.sea), SEA_LIGHT = [u32('#2A47B0'), u32('#3552BE')];
  const RARE_LAND = [u32('#E8743B'), u32('#C9DE8A')], RARE_SEA = [u32('#E9EEF6'), u32('#7FA4E2'), u32(A.PAL.vermilion)];
  function hash(i, j) {
    let h = (Math.imul(i, 374761393) + Math.imul(j, 668265263)) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  // an anti-aliased round dot blended into the buffer
  function stamp(cx, cy, r, col) {
    const GW = gC.width, GH = gC.height;
    const x0 = Math.max(0, Math.floor(cx - r - 1)), x1 = Math.min(GW - 1, Math.ceil(cx + r + 1));
    const y0 = Math.max(0, Math.floor(cy - r - 1)), y1 = Math.min(GH - 1, Math.ceil(cy + r + 1));
    const cr = col & 255, cg = (col >>> 8) & 255, cb = (col >>> 16) & 255;
    for (let y = y0; y <= y1; y++) {
      const dy = y + 0.5 - cy;
      for (let x = x0; x <= x1; x++) {
        const dx = x + 0.5 - cx;
        const a = r + 0.5 - Math.sqrt(dx * dx + dy * dy);
        if (a <= 0) continue;
        const i = y * GW + x;
        if (a >= 1) { g32[i] = col; continue; }
        const o = g32[i];
        const orr = o & 255, og = (o >>> 8) & 255, ob = (o >>> 16) & 255;
        g32[i] = ((255 << 24) | (((ob + (cb - ob) * a) | 0) << 16) | (((og + (cg - og) * a) | 0) << 8) | ((orr + (cr - orr) * a) | 0)) >>> 0;
      }
    }
  }
  function fillCell(x0, y0, x1, y1, col) {
    const GW = gC.width;
    for (let y = y0; y < y1; y++) g32.fill(col, y * GW + x0, y * GW + x1);
  }
  // Draw the globe centred at (cx, cy) CSS px with radius Rad, looking at (lam0, phi0) radians.
  function drawGlobe(cx, cy, Rad, lam0, phi0, alpha) {
    const GW = gC.width, GH = gC.height;
    g32.fill(0);
    const step = 3.4 * gd, Rd = Rad * gd, cxd = cx * gd, cyd = cy * gd;
    const sinp = Math.sin(phi0), cosp = Math.cos(phi0);
    const xa = Math.max(0, cxd - Rd * 1.03), xb = Math.min(GW, cxd + Rd * 1.03);
    const ya = Math.max(0, cyd - Rd * 1.03), yb = Math.min(GH, cyd + Rd * 1.03);
    if (xb <= xa || yb <= ya) return;
    const TWO_PI = Math.PI * 2;
    for (let gy = Math.floor(ya / step); gy * step < yb; gy++) {
      const py = gy * step + step / 2;
      const yy = -(py - cyd) / Rd;
      if (yy > 1.03 || yy < -1.03) continue;
      const Y0 = Math.max(0, Math.round(gy * step)), Y1 = Math.min(GH, Math.round((gy + 1) * step));
      for (let gx = Math.floor(xa / step); gx * step < xb; gx++) {
        const px = gx * step + step / 2;
        const xx = (px - cxd) / Rd;
        const r2 = xx * xx + yy * yy;
        if (r2 > 1.06) continue;
        const z = Math.sqrt(Math.max(0, 1 - r2));
        const s = Math.max(-1, Math.min(1, z * sinp + yy * cosp));
        const lat = Math.asin(s);
        const lon = lam0 + Math.atan2(xx, z * cosp - yy * sinp);
        let u = lon / TWO_PI + 0.5; u -= Math.floor(u);
        const v = 0.5 - lat / Math.PI;
        const land = mask[Math.min(MH - 1, Math.max(0, (v * MH) | 0)) * MW + Math.min(MW - 1, (u * MW) | 0)] === 1;
        const X0 = Math.max(0, Math.round(gx * step)), X1 = Math.min(GW, Math.round((gx + 1) * step));
        fillCell(X0, Y0, X1, Y1, land ? LAND0 : SEA0);
        const h = hash(gx, gy), h2 = hash(gy + 7, gx + 3);
        const shade = 0.62 + 0.38 * z;
        const jx = (h2 - 0.5) * step * 0.22, jy = (h - 0.5) * step * 0.22;
        if (land) {
          const col = h < 0.012 ? RARE_LAND[(h2 * 2) | 0] : LANDc[((h * 997) | 0) % LANDc.length];
          stamp(px + jx, py + jy, (0.3 + 0.17 * h2) * step * shade, col);
        } else if (h > 0.3) {
          const col = h > 0.993 ? RARE_SEA[(h2 * 3) | 0] : h2 > 0.55 ? SEA_LIGHT[(h * 2) | 0] : SEAc[((h * 991) | 0) % SEAc.length];
          const w = step * (0.6 + 0.4 * h2) * shade, hh = Math.max(1, step * 0.3);
          const xs = Math.max(0, Math.round(px + jx - w / 2)), xe = Math.min(GW, Math.round(px + jx + w / 2));
          const ys = Math.max(0, Math.round(py + jy - hh / 2)), ye = Math.min(GH, Math.max(ys + 1, Math.round(py + jy + hh / 2)));
          fillCell(xs, ys, xe, ye, col);
        }
      }
    }
    gCtx.putImageData(gImg, 0, 0);
    // trim the cells at the rim with a smooth circle, then shade the edge so it reads as a ball
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(cx * dpr, cy * dpr, Rad * dpr, 0, Math.PI * 2);
    if (Rad < Math.hypot(VW, VH)) {
      const sh = ctx.createRadialGradient(cx * dpr, cy * dpr + Rad * dpr * 0.04, Rad * dpr * 0.96, cx * dpr, cy * dpr + Rad * dpr * 0.04, Rad * dpr * 1.08);
      sh.addColorStop(0, 'rgba(16,27,99,0.22)'); sh.addColorStop(1, 'rgba(16,27,99,0)');
      ctx.fillStyle = sh; ctx.fillRect(0, 0, mapC.width, mapC.height);
    }
    ctx.clip();
    ctx.drawImage(gC, 0, 0, mapC.width, mapC.height);
    const g = ctx.createRadialGradient(cx * dpr, cy * dpr, Rad * dpr * 0.55, cx * dpr, cy * dpr, Rad * dpr);
    g.addColorStop(0, 'rgba(10,18,70,0)'); g.addColorStop(0.8, 'rgba(10,18,70,0.12)'); g.addColorStop(1, 'rgba(10,18,70,0.42)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, mapC.width, mapC.height);
    ctx.restore();
    if (Rad < Math.hypot(VW, VH)) {
      ctx.save(); ctx.globalAlpha = alpha;
      ctx.strokeStyle = 'rgba(26,42,134,0.55)'; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.arc(cx * dpr, cy * dpr, Rad * dpr, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }
  }
  // today's stories as pins on the globe
  function globePins(cx, cy, Rad, lam0, phi0, alpha) {
    const sinp = Math.sin(phi0), cosp = Math.cos(phi0);
    ctx.save(); ctx.scale(dpr, dpr); ctx.globalAlpha = alpha;
    for (const it of S.items) {
      const la = it.lat * DEG, lo = it.lng * DEG - lam0;
      const cosc = sinp * Math.sin(la) + cosp * Math.cos(la) * Math.cos(lo);
      if (cosc < 0.08) continue;
      const x = cx + Rad * Math.cos(la) * Math.sin(lo);
      const y = cy - Rad * (cosp * Math.sin(la) - sinp * Math.cos(la) * Math.cos(lo));
      const r = (it.video ? 2.6 + Math.min(2.6, it.hot * 0.28) : 2.6) * (0.6 + 0.4 * cosc) * Math.min(1.6, Math.max(1, Rad / 300));
      ctx.fillStyle = A.PAL.paper; ctx.beginPath(); ctx.arc(x, y, r + 1.6, 0, 6.2832); ctx.fill();
      ctx.fillStyle = it.state === 'done' ? A.PAL.vermilion : it.state === 'making' ? A.PAL.mustard : A.PAL.ink;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill();
    }
    ctx.restore();
  }

  // ---- the scroll ------------------------------------------------------------------------------------------------------
  function heroP() {
    const end = $('#hero').offsetHeight + $('.zoom-room').offsetHeight * 0.92;
    return A.clamp01(window.scrollY / end);
  }
  function activeStep() {
    let k = -1;
    const line = VH * (phone() ? 0.7 : 0.56);
    for (const el of stepEls) if (el.getBoundingClientRect().top < line) k = +el.dataset.k;
    return k;
  }
  const camFor = (k) => (k === 1 || k === 2 ? cams.world : k === 0 || k === 7 ? cams.ant : cams.europe);
  let cur = null;          // {k, cam, from, to, f, t0, dur, sp0}
  function goStep(k, now) {
    if (cur && cur.k === k) return;
    const target = camFor(k);
    const from = cur ? cur.cam : cams.europe;
    const f = A.interpolateZoom([from.x, from.y, box.w / from.s], [target.x, target.y, box.w / target.s]);
    const dur = RM ? 0 : Math.max(700, Math.min(1900, f.duration * 0.85));
    cur = {k, cam: from, f, t0: now, dur, target, sp0: now + dur * 0.55};
    stepEls.forEach((el) => el.classList.toggle('is-now', +el.dataset.k === k));
    railEl.querySelectorAll('li').forEach((li, i) => { li.className = i + 1 < k ? 'done' : i + 1 === k ? 'now' : ''; });
    if (k === 4) runClaims();
    showPlace(k === 0 || k === 3);
  }
  let placeShown = false;
  function showPlace(on) {
    if (on === placeShown) return;
    placeShown = on;
    placeEl.classList.toggle('is-on', on);
    if (on) A.decodeInto(placeEl, 'Antwerp', {speed: 55, delay: RM ? 0 : 350});
  }

  // ---- drawing each step on the map ------------------------------------------------------------------------------------------
  function pin(x, y, now, big) {
    const r = big ? 6 : 4.6;
    if (!RM) {
      const t = (now % 2200) / 2200;
      ctx.strokeStyle = `rgba(232,98,44,${0.55 * (1 - t)})`; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(x, y, r + 4 + t * 16, 0, 6.2832); ctx.stroke();
    }
    ctx.fillStyle = A.PAL.paper; ctx.beginPath(); ctx.arc(x, y, r + 2.2, 0, 6.2832); ctx.fill();
    ctx.fillStyle = A.PAL.vermilion; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill();
  }
  function label(text, x, y, size = 15, right = true, color = A.PAL.paper) {
    ctx.font = `italic 400 ${size}px StringerSerif, serif`;
    ctx.textAlign = right ? 'left' : 'right';
    ctx.lineJoin = 'round'; ctx.lineWidth = size * 0.24; ctx.strokeStyle = 'rgba(26,42,134,0.78)';
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color; ctx.fillText(text, x, y);
    ctx.textAlign = 'left';
  }
  function chip(x, y, w, h, col, alpha) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = 'rgba(16,27,99,0.35)';
    ctx.fillRect(x + 1, y + 2, w, h);
    ctx.fillStyle = A.PAL.paper; ctx.fillRect(x, y, w, h);
    ctx.fillStyle = col; ctx.fillRect(x, y, 3, h);
    ctx.fillStyle = A.PAL.ink;
    ctx.globalAlpha = alpha * 0.75;
    ctx.fillRect(x + 8, y + h * 0.3, w * 0.66, 2.2);
    ctx.fillRect(x + 8, y + h * 0.3 + 6, w * 0.44, 2.2);
    ctx.globalAlpha = 1;
  }
  // article slots around Antwerp: union-friendly on the left, business press on the right, wires below
  function slots(ax, ay, sc) {
    const out = [];
    let a = 0, b = 0, o = 0;
    for (const art of ARTICLES) {
      if (art.o.side === 'a') { out.push([ax - 150 * sc, ay - 70 * sc + a * 40 * sc]); a++; }
      else if (art.o.side === 'b') { out.push([ax + 92 * sc, ay - 70 * sc + b * 40 * sc]); b++; }
      else { out.push([ax - 58 * sc + o * 64 * sc, ay + 96 * sc]); o++; }
    }
    return out;
  }
  const CLAIM_CUT = new Set([11, 24]);
  const SCRIPT_SRC = [4, 0, 2, 1, 3, 0, 2];       // which article each script line points to (index in ARTICLES)

  function drawSteps(now) {
    const k = cur.k;
    // camera
    let flying = false;
    if (cur.dur > 0 && now - cur.t0 < cur.dur) {
      const t = A.easeInOut((now - cur.t0) / cur.dur);
      const [x, y, w] = cur.f(t);
      cur.cam = {x, y, s: box.w / w};
      flying = true;
    } else cur.cam = cur.target;
    const cam = cur.cam;
    const sp = RM ? 1 : A.clamp01((now - cur.sp0) / 1600);
    const litA = k === 0 ? smooth(sp * 2) : k === 7 ? 1 : k >= 3 ? 0.55 : 0;
    const outline = k === 0 ? A.clamp01(sp * 1.3) : k === 7 ? 1 : 0;
    drawFlat(cam, 1, litA, outline);
    const pr = proj(cam);
    const [ax, ay] = pr([ANT.lng, ANT.lat]);
    const sc = phone() ? 0.72 : 1.15;
    ctx.save(); ctx.scale(dpr, dpr);

    if (k === 1 || k === 2) {
      // outlets around the world, coloured by side
      // names keep off the Antwerp pin and off the other outlets' dots (Dublin, Madrid and Stockholm sit close on a phone)
      const placed = [[ax - 12, ay - 12, ax + 12, ay + 12]];
      const dots = OUTLETS.map((o) => { const [x, y] = pr([o.lng, o.lat]); return [x - 8, y - 8, x + 8, y + 8]; });
      OUTLETS.forEach((o, i) => {
        const [x, y] = pr([o.lng, o.lat]);
        const show = k === 2 ? 1 : smooth(sp * 2.2 - i * 0.22);
        if (show <= 0) return;
        if (k === 2) {
          const frac = RM ? 1 : A.clamp01(sp * 1.5 - i * 0.1);
          A.dottedArc(ctx, [x, y], [ax, ay], frac, {color: TINT[o.side], rad: 1.8, gap: 6.5, lift: 0.28});
        }
        ctx.globalAlpha = show;
        ctx.fillStyle = A.PAL.paper; ctx.beginPath(); ctx.arc(x, y, 6.5 * (0.6 + 0.4 * show), 0, 6.2832); ctx.fill();
        ctx.fillStyle = SIDE[o.side]; ctx.beginPath(); ctx.arc(x, y, 4.6 * (0.6 + 0.4 * show), 0, 6.2832); ctx.fill();
        // the label goes right of the pin, else left, else below or above: whichever clears the edges and the labels already drawn
        const fs = phone() ? 12.5 : 14.5;
        ctx.font = `italic 400 ${fs}px StringerSerif, serif`;
        const tw = ctx.measureText(o.name).width;
        const opts = [[x + 11, y + 5, true], [x - 11, y + 5, false], [x - tw / 2, y + 24, true], [x - tw / 2, y - 13, true]];
        const box = ([lx, ly, r]) => { const x0 = r ? lx : lx - tw; return [x0 - 3, ly - fs, x0 + tw + 3, ly + 4]; };
        const free = (q) => q[0] > 4 && q[2] < VW - 4 && ![...placed, ...dots.filter((_, j) => j !== i)].some((p) => !(q[2] < p[0] || q[0] > p[2] || q[3] < p[1] || q[1] > p[3]));
        const pick = opts.find((op) => free(box(op))) || opts[x < VW - 150 ? 0 : 1];
        placed.push(box(pick));
        label(o.name, pick[0], pick[1], fs, pick[2]);
        ctx.globalAlpha = 1;
      });
      if (k === 2) {
        // articles travelling in along the arcs, counted as they land
        let landed = 0;
        ARTICLES.forEach((art, n) => {
          const [x, y] = pr([art.o.lng, art.o.lat]);
          const u = RM ? 1 : A.clamp01((sp * 1.5 - art.i * 0.1 - art.j * 0.16 - 0.3) * 1.6);
          if (u <= 0) return;
          if (u >= 1) { landed++; return; }
          const q = A.arcPoint([x, y], [ax, ay], A.easeInOut(u), 0.28);
          ctx.fillStyle = A.PAL.paper; ctx.beginPath(); ctx.arc(q[0], q[1], 4.2, 0, 6.2832); ctx.fill();
          ctx.fillStyle = SIDE[art.o.side]; ctx.beginPath(); ctx.arc(q[0], q[1], 2.8, 0, 6.2832); ctx.fill();
          void n;
        });
        counter(ax, ay, landed, [...placed, ...dots]);
      }
      pin(ax, ay, now, false);
    }

    if (k >= 3 && k <= 6) {
      const sl = slots(ax, ay, sc);
      const cw = 54 * sc, ch = 32 * sc;
      const chipA = k === 3 ? 1 : k === 6 ? 0.16 : 0.42;
      ARTICLES.forEach((art, n) => {
        const t = k === 3 ? smooth(sp * 1.8 - n * 0.06) : 1;
        const x = lerp(ax - cw / 2, sl[n][0], t), y = lerp(ay - ch / 2, sl[n][1], t);
        chip(x, y, cw, ch, SIDE[art.o.side], chipA * Math.min(1, t * 3));
      });
      if (k === 3) {
        const t = smooth(sp * 2 - 0.6);
        ctx.globalAlpha = t;
        caps('Union-friendly', sl[0][0], sl[0][1] - 12 * sc, '#C9D5FF');
        caps('Business press', sl[4][0], sl[4][1] - 12 * sc, '#FFC7B8');
        caps('Wire services', sl[8][0], sl[8][1] + ch + 16 * sc, '#E3E7F1');
        ctx.globalAlpha = 1;
      }
      if (k === 4) drawClaimsRing(ax, ay, sp, sc);
      if (k === 5) drawScript(ax, ay, sp, sc, sl, cw, ch, 1);
      if (k === 6) drawVoice(ax, ay, now, sp, sc);
      pin(ax, ay, now, false);
    }

    if (k === 0) pin(ax, ay, now, true);
    if (k === 7) drawFrame(ax, ay, sp, flying);
    ctx.restore();
    placeAt(ax, ay, k);
  }
  function caps(text, x, y, color) {
    ctx.font = '600 10px StringerSans, sans-serif';
    ctx.fillStyle = color;
    let cx = x;
    for (const ch of text.toUpperCase()) { ctx.fillText(ch, cx, y); cx += ctx.measureText(ch).width + 1; }
  }
  function counter(ax, ay, n, avoid = []) {
    if (n <= 0) return;
    const text = `${n} article${n === 1 ? '' : 's'}`;
    ctx.font = '600 12.5px StringerSans, sans-serif';
    const w = ctx.measureText(text).width + 22;
    // the first spot near the pin that covers no outlet and no name; if none is free, the one that covers least
    const spots = phone() ? [[ax - w / 2, ay - 46], [ax + 16, ay - 12], [ax - w - 12, ay - 38], [ax + 14, ay - 44], [ax - w / 2, ay + 16], [ax + 16, ay + 14], [ax - w - 14, ay + 8]]
      : [[ax - w / 2, ay + 16], [ax - w / 2, ay - 46], [ax + 16, ay + 10], [ax - w - 16, ay + 10]];
    const cover = ([x, y]) => (x < 4 || x + w > VW - 4 ? 1e6 : 0) + avoid.reduce((sum, p) => {
      const ox = Math.min(x + w, p[2]) - Math.max(x, p[0]), oy = Math.min(y + 24, p[3]) - Math.max(y, p[1]);
      return sum + (ox > 0 && oy > 0 ? ox * oy : 0);
    }, 0);
    const [x, y] = spots.find((q) => cover(q) === 0) || spots.slice().sort((a, b) => cover(a) - cover(b))[0];
    ctx.fillStyle = A.PAL.paper;
    ctx.beginPath(); ctx.roundRect(x, y, w, 24, 12); ctx.fill();
    ctx.fillStyle = A.PAL.ink; ctx.fillText(text, x + 11, y + 16.5);
  }
  function drawClaimsRing(ax, ay, sp, sc) {
    const n = 31, R0 = 46 * sc;
    for (let i = 0; i < n; i++) {
      const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
      const t = RM ? 1 : A.clamp01(sp * 1.25 * n / 3 - i / 3);       // each claim gets checked in turn
      const cut = CLAIM_CUT.has(i);
      const drift = cut ? smooth((sp - 0.75) * 4) : 0;
      const r = R0 + drift * 26 * sc;
      const x = ax + Math.cos(a) * r, y = ay + Math.sin(a) * r;
      ctx.globalAlpha = cut ? 1 - drift * 0.65 : 1;
      ctx.fillStyle = A.PAL.paper; ctx.beginPath(); ctx.arc(x, y, 4.6 * sc, 0, 6.2832); ctx.fill();
      ctx.fillStyle = t < 1 ? 'rgba(26,42,134,0.25)' : cut ? A.PAL.vermilion : A.PAL.cobalt;
      ctx.beginPath(); ctx.arc(x, y, 3.2 * sc, 0, 6.2832); ctx.fill();
      if (cut && t >= 1) {
        ctx.strokeStyle = A.PAL.paper; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.moveTo(x - 6 * sc, y + 4 * sc); ctx.lineTo(x + 6 * sc, y - 4 * sc); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    const done = Math.min(31, Math.floor((RM ? 1 : sp * 1.25) * 31));
    const ok = Math.min(29, done - [...CLAIM_CUT].filter((i) => i < done).length);
    ctx.font = '600 12.5px StringerSans, sans-serif';
    const text = `${ok} backed${sp > 0.8 ? ' · 2 left out' : ''}`;
    const w = ctx.measureText(text).width + 22;
    ctx.fillStyle = A.PAL.paper; ctx.beginPath(); ctx.roundRect(ax - w / 2, ay + R0 + 22 * sc + 18, w, 24, 12); ctx.fill();
    ctx.fillStyle = A.PAL.ink; ctx.fillText(text, ax - w / 2 + 11, ay + R0 + 22 * sc + 34.5);
  }
  function drawScript(ax, ay, sp, sc, sl, cw, ch, alpha) {
    const pw = 132 * sc, ph = 168 * sc;
    const px = ax - pw / 2, py = ay - ph - 22 * sc;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = 'rgba(16,27,99,0.35)'; ctx.fillRect(px + 2, py + 3, pw, ph);
    ctx.fillStyle = A.PAL.paper; ctx.fillRect(px, py, pw, ph);
    ctx.globalAlpha = 1;
    const lines = SCRIPT_SRC.length;
    for (let i = 0; i < lines; i++) {
      const t = RM ? 1 : A.clamp01(sp * 1.4 * lines - i);
      if (t <= 0) break;
      const y = py + 18 * sc + i * 21 * sc;
      const lw = (pw - 34 * sc) * [0.92, 0.8, 0.95, 0.7, 0.86, 0.9, 0.6][i] * t;
      ctx.globalAlpha = alpha;
      ctx.fillStyle = A.PAL.ink; ctx.fillRect(px + 10 * sc, y, lw, 2.6 * sc);
      if (t >= 1) {
        const art = ARTICLES[SCRIPT_SRC[i]];
        const dx = px + pw - 14 * sc, dy = y + 1.3 * sc;
        // the line's source: a dot in its side's colour and a dotted thread back to the article it came from
        const [tx, ty] = sl[SCRIPT_SRC[i]];
        ctx.globalAlpha = alpha * 0.85;
        dotLine(dx, dy, tx + cw / 2, ty + ch / 2, SIDE[art.o.side]);
        ctx.globalAlpha = alpha;
        ctx.fillStyle = SIDE[art.o.side]; ctx.beginPath(); ctx.arc(dx, dy, 3.4 * sc, 0, 6.2832); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
  }
  function dotLine(x0, y0, x1, y1, color) {
    const len = Math.hypot(x1 - x0, y1 - y0), n = Math.max(2, Math.floor(len / 5));
    ctx.fillStyle = color;
    for (let i = 1; i < n; i++) { const u = i / n; ctx.beginPath(); ctx.arc(lerp(x0, x1, u), lerp(y0, y1, u), 1.1, 0, 6.2832); ctx.fill(); }
  }
  function drawVoice(ax, ay, now, sp, sc) {
    const cols = 44, w = 300 * sc, x0 = ax - w / 2, base = ay;
    const t = RM ? 0 : now / 1000;
    const reveal = RM ? 1 : smooth(sp * 2);
    ctx.fillStyle = A.PAL.paper;
    for (let i = 0; i < cols * reveal; i++) {
      const env = Math.sin((i / cols) * Math.PI);
      if (Math.abs(i - cols / 2) < 1.5) continue;     // leave room for the pin
      const hgt = Math.max(1, Math.round((2 + 7 * env * (0.55 + 0.45 * Math.sin(t * 7 + i * 1.7) * Math.sin(t * 3.1 + i * 0.6))) * sc));
      for (let j = -hgt; j <= hgt; j++) { ctx.beginPath(); ctx.arc(x0 + i * (w / cols), base + j * 4.2 * sc, 1.35, 0, 6.2832); ctx.fill(); }
    }
  }
  let posterC = null;
  function drawFrame(ax, ay, sp, flying) {
    const fh = Math.min(box.h * 0.9, 600), fw = fh * 9 / 16;
    const x = ax - fw / 2, y = Math.max(box.y, Math.min(ay - fh * 0.62, box.y + box.h - fh));
    const dim = flying ? 0 : smooth(sp * 2);
    // everything outside the frame dims, like a viewfinder
    ctx.fillStyle = `rgba(16,27,99,${0.55 * dim})`;
    ctx.beginPath(); ctx.rect(0, 0, VW, VH); ctx.roundRect(x, y, fw, fh, 10); ctx.fill('evenodd');
    if (flying) return;
    // the frame's edge, drawn as dots going round
    const per = 2 * (fw + fh), frac = RM ? 1 : A.clamp01(sp * 1.6);
    const n = Math.floor(per / 6);
    ctx.fillStyle = A.PAL.paper;
    for (let i = 0; i < n * frac; i++) {
      let d = (i / n) * per, px, py;
      if (d < fw) { px = x + d; py = y; } else if ((d -= fw) < fh) { px = x + fw; py = y + d; } else if ((d -= fh) < fw) { px = x + fw - d; py = y + fh; } else { d -= fw; px = x; py = y + fh - d; }
      ctx.beginPath(); ctx.arc(px, py, 1.6, 0, 6.2832); ctx.fill();
    }
    // the finished video's first frame fades in
    const pa = RM ? 1 : smooth((sp - 0.45) * 2.2);
    if (pa > 0) {
      const W2 = Math.round(fw), H2 = Math.round(fh);
      if (!posterC || posterC.w !== W2) posterC = {w: W2, c: P.make({...item, title: item.title}, 'player', W2, H2)};
      ctx.save();
      ctx.globalAlpha = pa;
      ctx.beginPath(); ctx.roundRect(x, y, fw, fh, 10); ctx.clip();
      ctx.drawImage(posterC.c, x, y, fw, fh);
      ctx.restore();
      ctx.globalAlpha = pa;
      ctx.font = '600 10px StringerSans, sans-serif';
      const tag = 'MADE WITH AI';
      let tw = 0; for (const ch of tag) tw += ctx.measureText(ch).width + 1.2;
      ctx.fillStyle = A.PAL.mustard; ctx.beginPath(); ctx.roundRect(x + 10, y + 10, tw + 16, 22, 11); ctx.fill();
      ctx.fillStyle = A.PAL.ink; let cx = x + 18; for (const ch of tag) { ctx.fillText(ch, cx, y + 25); cx += ctx.measureText(ch).width + 1.2; }
      ctx.globalAlpha = 1;
    }
  }
  function placeAt(ax, ay, k) {
    if (!placeShown) return;
    const off = k === 0 ? 16 : 12;
    placeEl.style.transform = `translate(${Math.round(ax + off)}px, ${Math.round(ay - (k === 0 ? 46 : 40))}px)`;
    placeEl.style.fontSize = k === 0 ? '' : '22px';
  }

  // ---- the frame loop ------------------------------------------------------------------------------------------------
  let raf = 0, t0 = performance.now();
  const request = () => { if (!raf) raf = requestAnimationFrame(frame); };
  function frame(now) {
    raf = 0;
    const p = heroP();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, mapC.width, mapC.height);
    let again = false;
    if (p < 1) {
      railEl.classList.remove('is-on');
      if (cur) { cur = null; stepEls.forEach((el) => el.classList.remove('is-now')); }
      showPlace(false);
      again = drawHero(RM ? (p < 0.5 ? 0 : 1) : p, now);
    } else {
      const k = activeStep();
      if (!cur) cur = {k: -1, cam: cams.europe, target: cams.europe, f: null, t0: now, dur: 0, sp0: now};
      if (k !== cur.k) {
        if (k >= 0) goStep(k, now);
        else { cur = {k: -1, cam: cams.europe, target: cams.europe, f: null, t0: now, dur: 0, sp0: now}; showPlace(false); stepEls.forEach((el) => el.classList.remove('is-now')); railEl.querySelectorAll('li').forEach((li) => { li.className = ''; }); }
      }
      railEl.classList.toggle('is-on', cur.k >= 0);
      if (cur.k < 0) {
        drawFlat(cams.europe, 1, 0, 0);
        const [ax, ay] = proj(cams.europe)([ANT.lng, ANT.lat]);
        ctx.save(); ctx.scale(dpr, dpr); pin(ax, ay, now, false); ctx.restore();
        again = !RM;
      } else {
        drawSteps(now);
        again = !RM;   // pins pulse, the voice moves
      }
    }
    if (again && !document.hidden && sceneVisible) request();
  }
  function drawHero(p, now) {
    const spinT = (now - t0) / 1000;
    const pr = A.easeInOut(A.clamp01(p / 0.42));
    const auto = -24 * DEG - (RM ? 0 : spinT * 5.5 * DEG) * (1 - pr);
    const target = ANT.lng * DEG;
    let d = target - auto; d = ((d + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
    const lam = auto + d * pr;
    const phi = lerp(16 * DEG, ANT.lat * DEG, pr);
    const pm = A.easeInOut(A.clamp01((p - 0.08) / 0.5));
    const cx = lerp(hero.cx, focal.x, pm), cy = lerp(hero.cy, focal.y, pm);
    const Rend = cams.europe.s / Math.cos(ANT.lat * DEG);
    const pz = A.clamp01((p - 0.2) / 0.8);
    const Rad = hero.R0 * Math.pow(Rend / hero.R0, Math.pow(pz, 1.15));
    const flatA = smooth((Rad - 0.5 * Rend) / (0.42 * Rend));
    if (flatA < 1) {
      drawGlobe(cx, cy, Rad, lam, phi, 1);
      globePins(cx, cy, Rad, lam, phi, 1 - smooth(pz * 3));
    }
    if (flatA > 0) {
      const s = Rad * Math.cos(ANT.lat * DEG);
      const cam = {x: A.mx(ANT.lng) - (cx - focal.x) / s, y: A.my(ANT.lat) + (cy - focal.y) / s, s};
      drawFlat(cam, flatA, 0, 0);
    }
    if (pz > 0.4) {
      ctx.save(); ctx.scale(dpr, dpr); pin(cx, cy, now, false); ctx.restore();
    }
    return !RM && p < 0.05;   // keep turning while the hero is in view
  }

  // ---- cards: the claims grid and the voice bars --------------------------------------------------------------------------
  const claimsEl = $('.claims');
  claimsEl.innerHTML = Array.from({length: 31}, () => '<i></i>').join('');
  let claimsTimer = 0;
  function runClaims() {
    clearInterval(claimsTimer);
    const dots = $$('i', claimsEl);
    dots.forEach((d) => { d.className = ''; });
    let i = 0;
    const tick = () => { if (i >= dots.length) { clearInterval(claimsTimer); return; } dots[i].className = CLAIM_CUT.has(i) ? 'cut' : 'ok'; i++; };
    if (RM) { while (i < dots.length) tick(); return; }
    claimsTimer = setInterval(tick, 55);
  }
  const waveEl = $('.wave');
  const r = A.rng(77);
  waveEl.innerHTML = Array.from({length: 44}, (_, i) => `<b style="--h:${Math.round(20 + 80 * Math.sin((i / 44) * Math.PI) * (0.4 + 0.6 * r()))};--i:${i}"></b>`).join('');
  railEl.innerHTML = STEPS.map((s) => `<li><span>${s.label}</span><i></i></li>`).join('');

  // "no real divide": 31 recent stories, 7 of them without two sides
  const NONE = new Set([2, 9, 13, 18, 22, 27, 30]);
  $('#divDots').innerHTML = Array.from({length: 31}, (_, i) => `<i class="${NONE.has(i) ? 'n' : ''}"></i>`).join('');

  // ---- the last band: today's map ----------------------------------------------------------------------------------------
  function paintLast() {
    const c = $('#lastMap');
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !h) return;
    const d = Math.min(2, window.devicePixelRatio || 1);
    c.width = Math.round(w * d); c.height = Math.round(h * d);
    const bx = phone() ? {x: 10, y: 10, w: w - 20, h: h * 0.55} : {x: w * 0.34, y: 30, w: w * 0.64, h: h - 60};
    const cam = A.fitCamera([-85, -32, 150, 60], bx);
    const pr = A.projectionFor(cam, bx.x + bx.w / 2, bx.y + bx.h / 2);
    const L = A.paintLayer({w, h, dpr: d, proj: pr, seed: 5, step: 3.4});
    const x = c.getContext('2d');
    x.drawImage(L.base, 0, 0);
    x.save(); x.scale(d, d);
    for (const it of S.items) {
      const [px, py] = pr([it.lng, it.lat]);
      const rr = it.video ? 3.4 + Math.min(3, it.hot * 0.35) : 3.2;
      x.fillStyle = A.PAL.paper; x.beginPath(); x.arc(px, py, rr + 2, 0, 6.2832); x.fill();
      x.fillStyle = it.state === 'done' ? A.PAL.vermilion : it.state === 'making' ? A.PAL.mustard : A.PAL.ink;
      x.beginPath(); x.arc(px, py, rr, 0, 6.2832); x.fill();
    }
    x.restore();
  }

  // ---- start -------------------------------------------------------------------------------------------------------------
  let sceneVisible = true;
  function start() {
    if (!W) { document.body.classList.add('no-map'); return; }
    buildMask();
    layout();
    request();
    // paint the flat layers while the visitor reads the hero
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 200));
    idle(() => { layer('europe'); idle(() => { layer('world'); idle(() => layer('ant')); }); });
    window.addEventListener('scroll', request, {passive: true});
    let rt = 0;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { layout(); request(); lastPainted = false; maybeLast(); }, 150); });
    new IntersectionObserver((es) => { sceneVisible = es[0].isIntersecting; if (sceneVisible) request(); }).observe($('#tour'));
    document.addEventListener('visibilitychange', request);
    maybeLast();
  }
  let lastPainted = false;
  function maybeLast() {
    const io = new IntersectionObserver((es) => {
      if (es[0].isIntersecting && !lastPainted) { lastPainted = true; paintLast(); io.disconnect(); }
    }, {rootMargin: '400px'});
    io.observe($('#lastMap'));
  }
  P.ready().then(start);
  window.__landing = {goTo: (k) => { const el = k < 0 ? $('#hero') : $(`.step[data-k="${k}"]`); window.scrollTo(0, k < 0 ? 0 : el.offsetTop + el.offsetHeight / 2 - window.innerHeight * (phone() ? 0.5 : 0.5)); }};
})();
