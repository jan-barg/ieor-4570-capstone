// The map shots: locate (one place), link (from A to B) and spread (many places). The render plan already
// found the places, their outline and the frame; a link or spread with fewer than 2 found places arrives
// here as a locate (plan.py). The highlight, the outline, the pins and the arc are pinned to the beat's
// marked words: "place", "link" or "count".
import {K, L, PAL, SERIF, clamp01, drawDecodingText, easeInOut, easeOut, fit} from './style.js';
import {dottedOutline, mapLayer, mapLayerLit, pin, projectionFor} from './map.js';
import {aiMark, sourceChip} from './cards.js';

const MARK = {map_locate: 'place', map_link: 'link', map_spread: 'count'};
const typed = (t, delay = 2, perChar = 1.0) => Math.max(0, Math.floor((t - delay) / perChar));

export function drawMap(ctx, s) {
  const {beat, t} = s;
  const m = beat.map;
  const bl = beat.blanks || {};
  const kind = beat.shot;
  const mk = beat.marks.find((x) => x.mark === MARK[kind]);
  const at = mk ? Math.max(0, mk.start - 4) : 12;            // when the place is said (or soon after the cut)
  const names = m.places.map((p) => p.name);
  // The title is the writer's label; with no label it is the place's name (then the pin goes unlabelled).
  const title = bl.label || (kind === 'map_locate' ? names[0] : names.join(' · '));
  const pinLabels = !!bl.label || kind !== 'map_locate';

  ctx.save();
  ctx.scale(K, K);
  const {size, lines} = fit(ctx, title, {maxWidth: L.right - L.left, maxLines: 2, max: s.compact ? 26 : 30, min: 21});
  const lh = size * 1.2;
  const titleY = L.content + (s.compact ? 20 : 26);
  const top = Math.round(titleY + (lines.length - 1) * lh + (s.compact ? 14 : 20));
  ctx.restore();
  // With an animation (s.compact, anim.js) the map is a strip under the title, a locator above the window.
  const bottom = s.compact ? top + 78 : undefined;
  if (s.compact) s.textEnd = bottom;

  const proj = projectionFor(m.frame, top, bottom);
  const pts = m.places.map((p) => proj([p.lng, p.lat]));
  const focus = kind === 'map_link' ? [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2] : pts[0];
  const z = 1 + 0.05 * easeInOut(t / Math.max(1, beat.frames));
  const font = `italic 400 13px ${SERIF}`;
  const area = kind === 'map_locate' && m.outline && m.places[0].kind !== 'point';
  // what the map's town and country names must keep clear of (map.js, drawContext)
  const keep = area
    ? (pinLabels ? [{x: pts[0][0], y: pts[0][1], label: names[0], font, centred: true}] : [])
    : pts.map((P, i) => ({x: P[0], y: P[1], label: kind === 'map_locate' && !pinLabels ? '' : names[i], font}));
  s.avoid = pts;
  s.mapTop = top;

  ctx.save();
  ctx.translate(focus[0] * K, focus[1] * K);
  ctx.scale(z, z);
  ctx.translate(-focus[0] * K, -focus[1] * K);
  ctx.drawImage(mapLayer(m.frame, top, {...m.context, lakes: m.lakes}, keep, bottom), 0, 0);
  if (m.outline) {
    // the place's own land turns warm as it is said
    ctx.globalAlpha = clamp01((t - at) / 10);
    ctx.drawImage(mapLayerLit(m.frame, top, m.outline, `${s.plan.story.id}-${beat.n}`, {...m.context, lakes: m.lakes}, keep, bottom), 0, 0);
    ctx.globalAlpha = 1;
  }
  ctx.scale(K, K);
  if (m.outline) dottedOutline(ctx, proj, m.outline, easeOut((t - at) / 26), PAL.paper);

  if (kind === 'map_link' && pts.length >= 2) {
    // a dotted arc from A to B, drawn while the link words are spoken
    const [A, B] = pts;
    const Q = [(A[0] + B[0]) / 2, Math.min(A[1], B[1]) - Math.max(24, Math.hypot(B[0] - A[0], B[1] - A[1]) * 0.35)];
    const end = mk ? mk.end : at + 30;
    const p = clamp01((t - at) / Math.max(8, end - at));
    for (let u = 0; u <= p; u += 0.012) {
      const x = (1 - u) ** 2 * A[0] + 2 * (1 - u) * u * Q[0] + u * u * B[0];
      const y = (1 - u) ** 2 * A[1] + 2 * (1 - u) * u * Q[1] + u * u * B[1];
      ctx.fillStyle = PAL.vermilion;
      ctx.beginPath();
      ctx.arc(x, y, 0.95, 0, 6.283);
      ctx.fill();
    }
    pin(ctx, A[0], A[1], -1, names[0], {font});
    if (p >= 1) pin(ctx, B[0], B[1], (t - end) / 30, names[1], {font});
  } else if (kind === 'map_spread') {
    // pins pop in one after another while the count is said
    const end = mk ? mk.end : at + 30;
    pts.forEach((P, i) => {
      const when = at + ((end - at) * i) / Math.max(1, pts.length);
      if (t >= when) pin(ctx, P[0], P[1], (t - when) / 30, names[i], {font});
    });
  } else if (!area) {
    if (t >= Math.min(at, 15)) pin(ctx, pts[0][0], pts[0][1], (t - at) / 30, pinLabels ? names[0] : '', {font});
  } else if (pinLabels && t >= at) {
    // a province, country or sea: its name on its outline, no pin
    ctx.globalAlpha = clamp01((t - at) / 8);
    ctx.font = font;
    ctx.textAlign = 'center';
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(26,42,134,0.55)';
    ctx.strokeText(names[0], pts[0][0], pts[0][1]);
    ctx.fillStyle = PAL.paper;
    ctx.fillText(names[0], pts[0][0], pts[0][1]);
    ctx.textAlign = 'left';
    ctx.globalAlpha = 1;
  }
  ctx.restore();

  ctx.save();
  ctx.scale(K, K);
  drawDecodingText(ctx, lines, {x: L.left, y: titleY, size, lineHeight: lh, font: `400 ${size}px ${SERIF}`, color: PAL.ink,
    revealed: typed(t), frame: s.frame});
  aiMark(ctx, false);
  if (!s.compact) sourceChip(ctx, beat.label, t);
  ctx.restore();
}
