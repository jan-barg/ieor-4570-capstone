// The props: 10 small drawings made by code (decision 8), each in a paper badge in the corner of the shot,
// with the same stippled finish as the render test's drone. They show the kind of thing, never the event
// itself. A prop that isn't drawn yet is skipped. The flag is a plain flag with no country's colours.
// Also here: the portrait badge (portraits.js) and the "Illustration" tag, drawn once for every beat the plan
// marks as an illustration.
import {K, L, PAL, clamp01, ctx2d, easeOut, makeCanvas, once, rng} from './style.js';
import {chipHeight, illustrationTag} from './cards.js';
import {drawCutout, portraitBadge, portraitImage} from './portraits.js';
import {staticFile} from 'remotion';

const INK = PAL.ink, COB = PAL.cobalt, MUS = PAL.mustard, VER = PAL.vermilion, PAP = PAL.paper;

const rr = (d, x, y, w, h, r, color) => { d.fillStyle = color; d.beginPath(); d.roundRect(x, y, w, h, r); d.fill(); };
const poly = (d, pts, color) => { d.fillStyle = color; d.beginPath(); pts.forEach(([x, y], i) => (i ? d.lineTo(x, y) : d.moveTo(x, y))); d.closePath(); d.fill(); };
const circ = (d, x, y, r, color) => { d.fillStyle = color; d.beginPath(); d.arc(x, y, r, 0, 6.283); d.fill(); };

// Each draws in a 100 x 100 box centred on 0, 0.
const DRAW = {
  'ballot box': (d) => {
    rr(d, -24, -34, 40, 34, 2, '#FFFFFF');
    d.strokeStyle = INK; d.lineWidth = 2;
    d.strokeRect(-24, -34, 40, 34);
    d.lineWidth = 3;
    d.beginPath(); d.moveTo(-14, -24); d.lineTo(0, -10); d.moveTo(0, -24); d.lineTo(-14, -10); d.stroke();
    rr(d, -36, -6, 72, 44, 5, MUS);
    rr(d, -26, -9, 52, 7, 3, INK);
    rr(d, -36, 30, 72, 8, 3, '#C9862A');
  },
  bridge: (d) => {
    d.strokeStyle = VER; d.lineWidth = 5;
    d.beginPath(); d.moveTo(-44, 6); d.quadraticCurveTo(0, -56, 44, 6); d.stroke();
    d.lineWidth = 2;
    for (let x = -30; x <= 30; x += 10) {
      const y = -50 * (1 - (x / 44) ** 2) * 0.5 + 6;
      d.beginPath(); d.moveTo(x, y); d.lineTo(x, 6); d.stroke();
    }
    rr(d, -48, 4, 96, 8, 2, INK);
    rr(d, -40, 12, 8, 22, 1, INK); rr(d, 32, 12, 8, 22, 1, INK);
    d.strokeStyle = COB; d.lineWidth = 2.5;
    for (const y of [26, 34]) { d.beginPath(); d.moveTo(-30, y); d.quadraticCurveTo(-15, y - 4, 0, y); d.quadraticCurveTo(15, y + 4, 30, y); d.stroke(); }
  },
  train: (d) => {
    rr(d, -30, -40, 60, 66, 14, COB);
    rr(d, -22, -32, 44, 24, 5, PAP);
    rr(d, -30, -2, 60, 6, 0, INK);
    circ(d, -17, 14, 5, MUS); circ(d, 17, 14, 5, MUS);
    rr(d, -10, 10, 20, 8, 2, INK);
    d.strokeStyle = INK; d.lineWidth = 3;
    d.beginPath(); d.moveTo(-22, 26); d.lineTo(-34, 42); d.moveTo(22, 26); d.lineTo(34, 42); d.stroke();
    d.lineWidth = 2.5;
    for (const y of [34, 42]) { d.beginPath(); d.moveTo(-36 + (42 - y) * 0.2, y); d.lineTo(36 - (42 - y) * 0.2, y); d.stroke(); }
  },
  document: (d) => {
    poly(d, [[-28, -40], [16, -40], [30, -26], [30, 40], [-28, 40]], PAP);
    poly(d, [[16, -40], [30, -26], [16, -26]], '#E9E2CF');
    d.strokeStyle = INK; d.lineWidth = 2;
    d.beginPath(); d.moveTo(-28, -40); d.lineTo(16, -40); d.lineTo(30, -26); d.lineTo(30, 40); d.lineTo(-28, 40); d.closePath(); d.stroke();
    for (let y = -22; y <= 20; y += 8) rr(d, -20, y, y === 20 ? 22 : 40, 2.5, 1, 'rgba(26,42,134,0.45)');
    circ(d, 16, 28, 9, VER);
  },
  plane: (d) => {
    rr(d, -6, -44, 12, 88, 6, INK);
    poly(d, [[-46, 4], [-4, -14], [4, -14], [46, 4], [46, 10], [4, 2], [-4, 2], [-46, 10]], COB);
    poly(d, [[-18, 38], [-3, 30], [3, 30], [18, 38], [18, 42], [-18, 42]], COB);
    circ(d, 0, -38, 4, PAP);
  },
  drone: (d) => {
    rr(d, -40, -5, 80, 10, 5, MUS);
    rr(d, -6, -40, 12, 80, 6, MUS);
    rr(d, -40, -16, 10, 32, 5, MUS);
    circ(d, 0, 0, 5, INK);
  },
  flag: (d) => {
    rr(d, -34, -44, 5, 90, 2, INK);
    circ(d, -31.5, -45, 4, INK);
    d.fillStyle = MUS;
    d.beginPath();
    d.moveTo(-29, -40);
    d.bezierCurveTo(-10, -50, 10, -30, 36, -40);
    d.lineTo(36, 2);
    d.bezierCurveTo(10, 12, -10, -8, -29, 2);
    d.closePath();
    d.fill();
  },
  missile: (d) => {
    d.save();
    d.rotate(-0.75);
    rr(d, -40, -7, 70, 14, 3, COB);
    poly(d, [[30, -7], [46, 0], [30, 7]], VER);
    poly(d, [[-40, -7], [-48, -18], [-30, -7]], INK);
    poly(d, [[-40, 7], [-48, 18], [-30, 7]], INK);
    rr(d, -6, -9, 4, 18, 1, PAP);
    d.restore();
  },
  'computer chip': (d) => {
    for (let k = -3; k <= 3; k++) {
      rr(d, k * 9 - 2, -44, 4, 10, 1, MUS); rr(d, k * 9 - 2, 34, 4, 10, 1, MUS);
      rr(d, -44, k * 9 - 2, 10, 4, 1, MUS); rr(d, 34, k * 9 - 2, 10, 4, 1, MUS);
    }
    rr(d, -34, -34, 68, 68, 6, INK);
    rr(d, -18, -18, 36, 36, 3, COB);
    circ(d, -26, -26, 3, PAP);
  },
  'cargo ship': (d) => {
    const cols = [VER, MUS, COB, MUS, VER, COB];
    cols.forEach((c, i) => rr(d, -40 + (i % 3) * 18, -12 - Math.floor(i / 3) * 12, 16, 10, 1, c));
    rr(d, 18, -34, 14, 30, 2, PAP);
    rr(d, 21, -30, 8, 4, 1, INK);
    poly(d, [[-48, -2], [46, -2], [38, 22], [-42, 22]], INK);
    rr(d, -44, 12, 86, 4, 1, VER);
    d.strokeStyle = COB; d.lineWidth = 2.5;
    d.beginPath(); d.moveTo(-50, 32); d.quadraticCurveTo(-25, 26, 0, 32); d.quadraticCurveTo(25, 38, 50, 32); d.stroke();
  },
};

export const PROPS = Object.keys(DRAW);

// The badge, made once per prop and size: paper disc, dotted ring, the prop with a stippled finish.
const badge = (name, r) => once(`prop-${name}-${r}`, () => {
  const px = Math.ceil(2 * r * K) + 4;
  const c = makeCanvas(px, px);
  const d = ctx2d(c);
  d.translate(px / 2, px / 2);
  d.scale(K, K);
  circ(d, 0, 0, r, PAP);
  d.save();
  d.scale((r * 0.72) / 50, (r * 0.72) / 50);
  DRAW[name](d);
  d.restore();
  const img = d.getImageData(0, 0, px, px);
  const p = img.data;
  const rnd = rng(5 + name.length);
  for (let i = 0; i < p.length; i += 4) {
    if (p[i + 3] === 0) continue;
    const paperish = p[i] > 230 && p[i + 1] > 225;
    if (!paperish && rnd() < 0.08) { p[i] = 243; p[i + 1] = 238; p[i + 2] = 225; continue; }
    const n = (rnd() - 0.5) * (paperish ? 14 : 50);
    p[i] += n; p[i + 1] += n; p[i + 2] += n * 0.6;
  }
  d.putImageData(img, 0, 0);
  d.setTransform(1, 0, 0, 1, 0, 0);
  d.translate(px / 2, px / 2);
  d.scale(K, K);
  d.fillStyle = 'rgba(26,42,134,0.55)';
  for (let a = 0; a < 6.283; a += 0.11) circ(d, Math.cos(a) * (r - 1.6), Math.sin(a) * (r - 1.6), 0.6, 'rgba(26,42,134,0.55)');
  return c;
});

const DARK = new Set(['hook', 'map_locate', 'map_link', 'map_spread', 'headline']);

// Draws the beat's prop or portrait (if it has one we can draw) and the "Illustration" tag (if the plan says so).
// A portrait with a cutout is drawn by drawCutout where placement.js finds room (s.portraitDrawn says where, for
// the layout check); with no room it is left out rather than put over words. Without a cutout: the dotted badge.
export function drawBroll(ctx, s) {
  const {beat, t} = s;
  const br = beat.broll || {};
  const dark = DARK.has(beat.shot);
  ctx.save();
  ctx.scale(K, K);
  const name = br.kind === 'prop' && DRAW[br.name] && !(beat.shot === 'document' && br.name === 'document') ? br.name : null;
  const url = br.kind === 'portrait' && br.portrait?.src ? staticFile(br.portrait.src) : null;
  const photo = url ? portraitImage(url) : null;
  const cutUrl = br.kind === 'portrait' && br.portrait?.cutoutSrc && br.portrait?.face ? staticFile(br.portrait.cutoutSrc) : null;
  const cut = cutUrl ? portraitImage(cutUrl) : null;
  if (cut && s.finished) {
    s.portraitDrawn = drawCutout(ctx, s, cutUrl, cut);
  } else if (name || photo) {
    const r = photo && s.portraitAt ? 26 : 30;
    const low = L.bottom - chipHeight(ctx, beat.label) - r - 22;
    // the corner farthest from anything the shot asked to keep clear (a map's pins and their labels);
    // a quote puts the portrait beside the speaker's name (s.portraitAt)
    const high = Math.max(low - 96, (s.mapTop || 0) + r + 12);
    const spots = s.avoid?.length ? [[L.right - r, low], [L.right - r, high], [L.left + r + 4, high]] : [[L.right - r, low]];
    const clear = ([x, y]) => Math.min(...(s.avoid || []).map(([ax, ay]) => Math.hypot(x - (ax + 30), y - ay)), 1e9);
    const [cx, cy] = photo && s.portraitAt ? s.portraitAt : spots.reduce((a, b) => (clear(b) > clear(a) + 8 ? b : a));
    const pop = easeOut(clamp01((t - 10) / 9));
    if (pop > 0) {
      const sc = 0.6 + 0.4 * pop;
      ctx.globalAlpha = pop;
      const img = photo ? portraitBadge(url, photo, r) : badge(name, r);
      const size = img.width / K;
      ctx.drawImage(img, cx - (size * sc) / 2, cy - (size * sc) / 2, size * sc, size * sc);
      ctx.globalAlpha = 1;
    }
  }
  if (beat.illustration) illustrationTag(ctx, dark);
  ctx.restore();
}
