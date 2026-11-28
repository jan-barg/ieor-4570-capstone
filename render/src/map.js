// The dotted map behind the hook and the map shots. Coastlines come from world-atlas (Natural Earth):
// 10m for close frames, 50m for wide ones. Outlines come from the render plan (Natural Earth, Germany's
// point of view) and are drawn by projecting each point ourselves, so ring direction never matters.
import {geoArea, geoMercator, geoPath} from 'd3-geo';
import {feature} from 'topojson-client';
import land50Topo from 'world-atlas/land-50m.json';
import land10Topo from 'world-atlas/land-10m.json';
import {H, K, L, PAL, PX_H, PX_W, SANS, W, ctx2d, makeCanvas, once, paintGrain, rng, smallCaps} from './style.js';
import {recordTexts} from './placement.js';

// Some polygons in land-10m are wound the wrong way, so d3 reads them as "the whole globe except this
// island" and fills the sea. Any polygon covering more than half the globe gets its rings reversed.
function rewound(topo) {
  const fc = feature(topo, topo.objects.land);
  const polys = [];
  for (const f of fc.features || [fc]) {
    const g = f.geometry || f;
    for (const poly of g.type === 'Polygon' ? [g.coordinates] : g.coordinates) {
      const one = {type: 'Polygon', coordinates: poly};
      polys.push(geoArea(one) > 2 * Math.PI ? poly.map((ring) => ring.slice().reverse()) : poly);
    }
  }
  return {type: 'MultiPolygon', coordinates: polys};
}

let land50, land10;
const landFor = (frame) => {
  const wide = frame[2] - frame[0] > 14 || frame[3] - frame[1] > 10;
  if (wide) return (land50 ||= rewound(land50Topo));
  return (land10 ||= rewound(land10Topo));
};

// The projection that puts the plan's frame [west, south, east, north] in the visible part of the map:
// below the title, above the captions, left of TikTok's buttons.
export function projectionFor(frame, top, bottom = L.bottom) {
  const [w, s, e, n] = frame;
  // No clipExtent: with it, d3 fills the whole box with land (Antarctica's ring around the pole).
  return geoMercator()
    .fitExtent([[L.left, top + 18], [L.right, bottom - 6]], {
      type: 'MultiPoint', coordinates: [[w, s], [e, n], [w, n], [e, s]],
    });
}

// A region (GeoJSON MultiPolygon) as a canvas path, projected point by point.
export function regionPath(ctx, proj, shape) {
  ctx.beginPath();
  for (const poly of shape?.coordinates || []) {
    for (const ring of poly) {
      ring.forEach(([x, y], i) => {
        const p = proj([x, y]);
        if (!p) return;
        if (i === 0) ctx.moveTo(p[0], p[1]);
        else ctx.lineTo(p[0], p[1]);
      });
      ctx.closePath();
    }
  }
}

const LAND = ['#1E5E34', '#2E7D3F', '#2E7D3F', '#4E9F4E', '#86BE5C', '#2B3F9E', '#163F26', '#5FA857'];
const WARM = ['#E0A12A', '#E8743B', '#E8622C', '#F0B347', '#C9862A', '#E0A12A'];
const SEA = ['#1A2A86', '#22389C', '#22389C', '#3552BE', '#1A2A86', '#2A47B0'];

// The lakes inside the frame (plan.py puts them on the map as context.lakes: rings, islands included),
// traced as one path for the even-odd rule.
function lakesPath(ctx, proj, lakes) {
  ctx.beginPath();
  for (const ring of lakes || []) {
    ring.forEach(([x, y], i) => {
      const p = proj([x, y]);
      if (!p) return;
      if (i === 0) ctx.moveTo(p[0], p[1]);
      else ctx.lineTo(p[0], p[1]);
    });
    ctx.closePath();
  }
}

function maskOf(paint) {
  const m = makeCanvas();
  const mc = ctx2d(m);
  mc.scale(K, K);
  mc.fillStyle = '#000';
  paint(mc);
  const d = mc.getImageData(0, 0, PX_W, PX_H).data;
  return (x, y) => {
    const ix = Math.round(x * K), iy = Math.round(y * K);
    if (ix < 0 || iy < 0 || ix >= PX_W || iy >= PX_H) return false;
    return d[(iy * PX_W + ix) * 4 + 3] > 128;
  };
}

// Where a pin's label sits (the same rule pin() draws by): right of the pin, or left when it would run off.
export function pinLabelAt(ctx, x, y, label, font) {
  ctx.font = font;
  const w = ctx.measureText(label).width;
  const right = x + 9 + w <= L.right;
  const lx = right ? x + 9 : Math.max(L.left + w, x - 9);
  return {right, lx, y: y - 7, w, box: right ? [lx, y - 18, lx + w, y - 3] : [lx - w, y - 18, lx, y - 3]};
}

// What the context must keep clear of: each pin's dot and label, or an area's centred name.
function keepBoxes(ctx, pins) {
  const boxes = [];
  for (const k of pins || []) {
    boxes.push([k.x - 7, k.y - 7, k.x + 7, k.y + 7]);
    if (!k.label) continue;
    if (k.centred) {
      ctx.font = k.font;
      const w = ctx.measureText(k.label).width;
      boxes.push([k.x - w / 2, k.y - 11, k.x + w / 2, k.y + 3]);
    } else boxes.push(pinLabelAt(ctx, k.x, k.y, k.label, k.font).box);
  }
  return boxes;
}

const hits = (a, b, pad = 2) => a[0] < b[2] + pad && b[0] < a[2] + pad && a[1] < b[3] + pad && b[1] < a[3] + pad;
const norm = (x) => String(x || '').toLowerCase().replace(/[^a-z]/g, '');

// Borders, country names and a few big towns (plan.py, places.context), so a pin is never alone. A name
// that would touch a pin, its label or a name already placed is left out (pins first, then countries,
// then towns), and a country already named by a pin is not named twice.
function drawContext(ctx, proj, top, context, pins, bottom = L.bottom) {
  if (!context) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, top, W, H - top);
  ctx.clip();
  ctx.fillStyle = 'rgba(243,238,225,0.72)';
  for (const run of context.borders || []) {
    let carry = 0;
    for (let i = 1; i < run.length; i++) {
      const a = proj(run[i - 1]), b = proj(run[i]);
      if (!a || !b) continue;
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      for (let d = carry; d < len; d += 2.6) {
        ctx.beginPath();
        ctx.arc(a[0] + ((b[0] - a[0]) * d) / len, a[1] + ((b[1] - a[1]) * d) / len, 0.65, 0, 6.283);
        ctx.fill();
      }
      carry = ((carry - len) % 2.6 + 2.6) % 2.6;
    }
  }
  const placed = keepBoxes(ctx, pins);
  const named = new Set((pins || []).map((k) => norm(k.label)).filter(Boolean));
  const free = (box) => box[0] >= 2 && box[2] <= W - 2 && box[1] >= top + 2 && !placed.some((b) => hits(b, box));
  for (const c of context.countries || []) {
    const p = proj([c.lng, c.lat]);
    if (!p || p[1] < top + 12 || p[1] > bottom || named.has(norm(c.name))) continue;
    ctx.font = `600 8px ${SANS}`;
    const w = ctx.measureText(String(c.name).toUpperCase()).width + String(c.name).length * 1.6;
    const box = [p[0] - w / 2, p[1] - 7, p[0] + w / 2, p[1] + 1];
    if (!free(box)) continue;
    placed.push(box);
    smallCaps(ctx, c.name, p[0], p[1], {size: 8, color: 'rgba(243,238,225,0.78)', align: 'center', spacing: 1.6});
  }
  for (const t of context.towns || []) {
    const p = proj([t.lng, t.lat]);
    if (!p || p[1] < top + 8 || p[0] < 6 || p[0] > W - 6) continue;
    ctx.font = `500 8px ${SANS}`;
    const w = ctx.measureText(t.name).width;
    const dotBox = [p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2];
    const sides = [[p[0] + 4, p[0] + 4 + w], [p[0] - 4 - w, p[0] - 4]]
      .map(([a, b]) => [a, p[1] - 4, b, p[1] + 4]).filter(free);
    if (!sides.length || !free(dotBox)) continue;
    const box = sides[0];
    const right = box[0] > p[0];
    placed.push(dotBox, box);
    ctx.fillStyle = PAL.paper;
    ctx.beginPath(); ctx.arc(p[0], p[1], 1.4, 0, 6.283); ctx.fill();
    ctx.strokeStyle = 'rgba(26,42,134,0.7)';
    ctx.lineWidth = 0.6;
    ctx.stroke();
    ctx.textAlign = right ? 'left' : 'right';
    ctx.lineWidth = 2.4;
    ctx.strokeStyle = 'rgba(26,42,134,0.5)';
    ctx.strokeText(t.name, p[0] + (right ? 4 : -4), p[1] + 3);
    ctx.fillStyle = 'rgba(243,238,225,0.92)';
    ctx.fillText(t.name, p[0] + (right ? 4 : -4), p[1] + 3);
    ctx.textAlign = 'left';
  }
  ctx.restore();
}

// The still map: paper sky with grain above `top`, then stippled land and sea, then the context. With
// `region`, the land dots inside it are warm (the "highlighted" copy that fades in when the place is said).
function buildLayer(frame, top, region, context, pins, bottom) {
  const proj = projectionFor(frame, top, bottom);
  const c = makeCanvas();
  const ctx = ctx2d(c);
  recordTexts(c, ctx);           // its place names, so a portrait can keep clear of them (placement.js)
  paintGrain(ctx, 7, (y) => (y < top * K ? 0.5 * Math.pow(1 - y / (top * K), 1.15) + 0.04 : 0));
  const land = landFor(frame);
  const lakes = context?.lakes || [];
  // land, with the lakes cut back out of it (Natural Earth lakes, Jan's OK Nov 26): a lake is drawn as water
  const isLand = maskOf((mc) => {
    mc.beginPath(); geoPath(proj, mc)(land); mc.fill();
    if (lakes.length) { mc.globalCompositeOperation = 'destination-out'; lakesPath(mc, proj, lakes); mc.fill('evenodd'); }
  });
  const inRegion = region ? maskOf((mc) => { regionPath(mc, proj, region); mc.fill('evenodd'); }) : null;

  ctx.save();
  ctx.scale(K, K);
  ctx.fillStyle = PAL.sea;
  ctx.fillRect(0, top, W, H - top);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, top, W, H - top);
  ctx.clip();
  ctx.fillStyle = PAL.landBase;
  ctx.beginPath();
  geoPath(proj, ctx)(land);
  ctx.fill();
  if (lakes.length) { ctx.fillStyle = PAL.sea; lakesPath(ctx, proj, lakes); ctx.fill('evenodd'); }
  ctx.restore();

  const r = rng(11);
  const pick = (a) => a[Math.floor(r() * a.length)];
  for (let y = top + 1; y < H; y += 1.8) {
    for (let x = 0; x < W; x += 2) {
      const px = x + (r() - 0.5) * 1.4, py = y + (r() - 0.5) * 1.1;
      const q = r();
      if (isLand(px, py)) {
        const warm = inRegion && inRegion(px, py);
        ctx.fillStyle = warm ? pick(WARM) : q < 0.01 ? '#E8743B' : q < 0.03 ? '#C9DE8A' : pick(LAND);
        ctx.beginPath();
        ctx.arc(px, py, 0.5 + r() * 0.45, 0, 6.283);
        ctx.fill();
      } else {
        ctx.fillStyle = q < 0.01 ? PAL.vermilion : q < 0.045 ? '#E9EEF6' : q < 0.11 ? '#7FA4E2' : pick(SEA);
        ctx.fillRect(px, py, 1.4 + r() * 2.4, 0.75);
      }
    }
  }
  ctx.fillStyle = 'rgba(233,238,246,0.55)';
  ctx.fillRect(0, top, W, 0.8);
  drawContext(ctx, proj, top, context, pins, bottom);
  ctx.restore();
  return c;
}

// The cache key includes the pins, since the context's names are placed around them.
const pinKey = (pins) => (pins || []).map((k) => `${Math.round(k.x)}:${Math.round(k.y)}:${k.label || ''}`).join('|');
// `bottom`: the lowest the map's frame reaches (a strip above an animation's window; anim.js), else L.bottom.
const keyOf = (frame, top, tag, pins, bottom) => `map-${frame.join(',')}-${top}-${tag}-${pinKey(pins)}${bottom ? `-${bottom}` : ''}`;
export const mapLayer = (frame, top, context, pins, bottom) =>
  once(keyOf(frame, top, 'base', pins, bottom), () => buildLayer(frame, top, null, context, pins, bottom));
export const mapLayerLit = (frame, top, region, id, context, pins, bottom) =>
  once(keyOf(frame, top, `lit-${id}`, pins, bottom), () => buildLayer(frame, top, region, context, pins, bottom));

// The region's outline as a dotted line, drawn up to `frac` of its length (in sketch units).
export function dottedOutline(ctx, proj, shape, frac, color = PAL.paper) {
  ctx.fillStyle = color;
  const rings = [];
  for (const poly of shape?.coordinates || []) rings.push(poly[0]);
  let total = 0;
  const pts = rings.map((ring) => ring.map((p) => proj(p)).filter(Boolean));
  for (const ring of pts) for (let i = 1; i < ring.length; i++) total += Math.hypot(ring[i][0] - ring[i - 1][0], ring[i][1] - ring[i - 1][1]);
  const upto = total * Math.max(0, Math.min(1, frac));
  let run = 0;
  const step = 2.1;
  let carry = 0;
  for (const ring of pts) {
    for (let i = 1; i < ring.length; i++) {
      const [x1, y1] = ring[i - 1], [x2, y2] = ring[i];
      const len = Math.hypot(x2 - x1, y2 - y1);
      for (let d = carry; d < len; d += step) {
        if (run + d > upto) return;
        ctx.beginPath();
        ctx.arc(x1 + ((x2 - x1) * d) / len, y1 + ((y2 - y1) * d) / len, 0.75, 0, 6.283);
        ctx.fill();
      }
      carry = (carry - len) % step;
      if (carry < 0) carry += step;
      run += len;
    }
  }
}

// A pin: a pulsing ring, a dot, and its label in italic serif, kept inside the frame.
export function pin(ctx, x, y, since, label, {font, color = PAL.paper} = {}) {
  const u = (Math.max(0, since) % 3) / 1.8;
  if (since >= 0 && u < 1) {
    ctx.strokeStyle = `rgba(232,98,44,${(1 - u).toFixed(3)})`;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.arc(x, y, 5 + u * 26, 0, 6.283);
    ctx.stroke();
  }
  ctx.fillStyle = PAL.paper;
  ctx.beginPath();
  ctx.arc(x, y, 4.4, 0, 6.283);
  ctx.fill();
  ctx.fillStyle = PAL.vermilion;
  ctx.beginPath();
  ctx.arc(x, y, 3.3, 0, 6.283);
  ctx.fill();
  if (!label) return;
  const at = pinLabelAt(ctx, x, y, label, font);
  ctx.textAlign = at.right ? 'left' : 'right';
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(26,42,134,0.55)';
  ctx.strokeText(label, at.lx, at.y);
  ctx.fillStyle = color;
  ctx.fillText(label, at.lx, at.y);
  ctx.textAlign = 'left';
}
