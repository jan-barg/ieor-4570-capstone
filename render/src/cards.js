// The first four shots: hook, headline, sides and sources, plus the
// small marks every frame carries. Each draw function gets the canvas and a state object:
//   s = {beat, t (frames since the beat started), frame (frames since the video started), plan}
// and draws in sketch units (324 x 576).
import {
  H, K, L, PAL, PX_H, PX_W, SANS, SERIF, W, clamp01, ctx2d, dot, drawDecodingText, easeInOut, easeOut, fit, fitBox,
  makeCanvas, once, paperLayer, pill, rng, smallCaps, spokenChars, wrap, wrapCaps,
} from './style.js';
import {mapLayer, pin, projectionFor} from './map.js';

// ---- marks on every frame ------------------------------------------------------------------------------

// The two small marks sit on busy drawings (sky grain, land dots), so they use full ink or full paper:
// at 80% paper or soft ink they read at 4.0-4.5:1 (layout eval, Nov 26).
export function aiMark(ctx, dark) {
  smallCaps(ctx, 'Made with AI', L.right, L.top + 8, {size: 7.5, color: dark ? PAL.paper : PAL.ink, align: 'right', spacing: 0.7});
}

export function illustrationTag(ctx, dark) {
  ctx.font = `500 9px ${SANS}`;
  ctx.fillStyle = dark ? PAL.paper : PAL.ink;
  ctx.textAlign = 'right';
  ctx.fillText('Illustration', L.right, L.bottom + 10);
  ctx.textAlign = 'left';
}

// How tall the "Source:" chip will be (0 with no label), so a shot can keep its text clear of it.
export function chipHeight(ctx, label) {
  if (!label) return 0;
  ctx.font = `500 9.5px ${SANS}`;
  return Math.min(2, wrap(ctx, label, L.right - L.left - 14).length) * 12 + 8;
}

// "Source: …" while a line that names its source plays: a paper chip at the bottom of the picture.
export function sourceChip(ctx, label, t) {
  if (!label) return;
  ctx.save();
  ctx.globalAlpha = clamp01((t - 4) / 8);
  ctx.font = `500 9.5px ${SANS}`;
  const lines = wrap(ctx, label, L.right - L.left - 14).slice(0, 2);
  const h = lines.length * 12 + 8;
  const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 14;
  const y = L.bottom - h;
  ctx.fillStyle = 'rgba(243,238,225,0.96)';
  ctx.beginPath();
  ctx.roundRect(L.left, y, w, h, 5);
  ctx.fill();
  ctx.fillStyle = PAL.vermilion;
  ctx.fillRect(L.left, y + 4, 2, h - 8);
  ctx.fillStyle = PAL.ink;
  lines.forEach((l, i) => ctx.fillText(l, L.left + 8, y + 13 + i * 12));
  ctx.restore();
}

// ---- words of a title matched to the spoken words, so a look can react as each one is said ------------

const stem = (w) => String(w).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]/g, '').replace(/(ing|ed|es|s)$/, '');

export function matchSpoken(titleWords, spoken) {
  let from = 0;
  return titleWords.map((tw) => {
    const st = stem(tw);
    if (st.length < 2) return null;
    for (let k = from; k < spoken.length; k++) {
      if (stem(spoken[k].w) === st) { from = k + 1; return spoken[k]; }
    }
    return null;
  });
}

// Each word's box on the lines of a title, with its character range (spaces count, as in drawDecodingText).
export function layoutWords(ctx, lines, x, y, lineHeight, align = 'left') {
  const out = [];
  let k = 0;
  lines.forEach((line, li) => {
    const lw = ctx.measureText(line).width;
    let cx = align === 'center' ? x - lw / 2 : x;
    for (const word of line.split(' ')) {
      const w = ctx.measureText(word).width;
      out.push({word, x: cx, y: y + li * lineHeight, w, k0: k, k1: k + word.length});
      cx += w + ctx.measureText(' ').width;
      k += word.length + 1;
    }
  });
  return out;
}

const typed = (t, delay = 3, perChar = 1.1) => Math.max(0, Math.floor((t - delay) / perChar));

// ---- the hook: the headline over the event's place, in dots ------------------------------------------

export function drawHook(ctx, s) {
  const {beat, t, plan} = s;
  const title = beat.blanks.title || plan.story.title || '';
  const m = beat.map;
  ctx.save();
  ctx.scale(K, K);
  const {size, lines} = fit(ctx, title, {maxWidth: L.right - L.left, maxLines: 3, max: 31, min: 22});
  const lh = size * 1.2;
  const titleY = L.content + 30;
  const top = Math.round(titleY + (lines.length - 1) * lh + 22);
  ctx.restore();

  if (m?.frame) {
    const proj = projectionFor(m.frame, top);
    const p = proj([m.places[0].lng, m.places[0].lat]);
    const z = 1 + 0.05 * easeInOut(t / Math.max(1, beat.frames));
    ctx.save();
    ctx.translate(p[0] * K, p[1] * K);
    ctx.scale(z, z);
    ctx.translate(-p[0] * K, -p[1] * K);
    const name = String(m.places[0].name || '').split(',')[0].trim();
    const font = `italic 400 13px ${SERIF}`;
    ctx.drawImage(mapLayer(m.frame, top, {...m.context, lakes: m.lakes}, [{x: p[0], y: p[1], label: name, font}]), 0, 0);
    ctx.scale(K, K);
    s.avoid = [p];
    s.mapTop = top;
    pin(ctx, p[0], p[1], (t - 10) / 30, t > 14 ? name : '', {font});
    ctx.restore();
  } else {
    ctx.drawImage(paperLayer(), 0, 0);
  }

  ctx.save();
  ctx.scale(K, K);
  drawDecodingText(ctx, lines, {x: L.left, y: titleY, size, lineHeight: lh, font: `400 ${size}px ${SERIF}`, color: PAL.ink,
    revealed: typed(t, 2, 1.0), frame: s.frame});
  if (beat.blanks.tag || plan.story.developing) pill(ctx, beat.blanks.tag || 'Developing', L.left, L.tags - 4, {size: 8});
  aiMark(ctx, false);
  sourceChip(ctx, beat.label, t);
  ctx.restore();
}

// ---- headline: the poster (Jan picked it Nov 26). Huge type on blue; each word lands, and lights when spoken

const posterLayer = () => once('poster', () => {
  const c = makeCanvas();
  const ctx = ctx2d(c);
  ctx.fillStyle = PAL.ink;
  ctx.fillRect(0, 0, PX_W, PX_H);
  const r = rng(77);
  for (let y = 0; y < PX_H; y += 6) {
    const d = 0.08 + 0.32 * Math.pow(1 - y / PX_H, 2);
    for (let x = 0; x < PX_W; x += 6) {
      if (r() < d) {
        ctx.fillStyle = r() < 0.6 ? '#2A47B0' : '#3552BE';
        ctx.fillRect(x, y, 4, 4);
      }
    }
  }
  return c;
});

export function drawHeadline(ctx, s) {
  const {beat, t} = s;
  const title = beat.blanks.title || '';
  ctx.drawImage(posterLayer(), 0, 0);
  ctx.save();
  ctx.scale(K, K);
  // fit the title above the red bar, the "Source:" label and (when there is one) the prop's badge
  const prop = beat.broll?.kind === 'prop' && !beat.broll?.skipped;
  const room = L.bottom - chipHeight(ctx, beat.label) - (prop ? 70 : 0) - 34 - (L.content + 20);
  const {size, lines} = fitBox(ctx, title, {maxWidth: L.right - L.left, maxHeight: room, max: 54, min: 24, lh: 1.04});
  const lh = size * 1.04;
  const y0 = L.content + 20 + size * 0.8;
  ctx.font = `400 ${size}px ${SERIF}`;
  const boxes = layoutWords(ctx, lines, L.left, y0, lh);
  const said = matchSpoken(boxes.map((b) => b.word), beat.words);
  boxes.forEach((b, i) => {
    const appear = 2 + i * 3;
    const p = easeOut((t - appear) / 6);
    if (p <= 0) return;
    const w = said[i];
    const lit = w && t >= w.start;
    ctx.globalAlpha = p;
    ctx.fillStyle = lit ? PAL.mustard : PAL.paper;
    ctx.fillText(b.word, b.x, b.y + (1 - p) * 10);
  });
  ctx.globalAlpha = 1;
  // a vermilion bar under the type that runs the length of the beat
  const by = y0 + (lines.length - 1) * lh + 22;
  ctx.fillStyle = PAL.vermilion;
  ctx.fillRect(L.left, by, (L.right - L.left) * clamp01(t / Math.max(1, beat.frames - 10)), 3);
  aiMark(ctx, true);
  sourceChip(ctx, beat.label, t);
  ctx.restore();
}

// ---- sides: how each side tells it. One panel per side; each fills in as its sentence is spoken --------

const sideParts = (label) => {
  const m = String(label || '').match(/^([^(]+?)\s*\(([^)]*)\)\s*$/);
  return m ? [m[1].trim(), m[2].trim()] : [String(label || '').trim(), ''];
};

export function drawSides(ctx, s) {
  const {beat, t, plan} = s;
  ctx.drawImage(paperLayer(27, 0.28), 0, 0);
  ctx.save();
  ctx.scale(K, K);
  const marks = Object.fromEntries(beat.marks.map((m) => [m.mark, m]));
  const bySide = {};
  for (const p of beat.blanks.points || []) (bySide[p.side] ||= p);
  // A side the narrator speaks about with no point of its own (most often "we found no coverage from ...")
  // still gets its panel, with the spoken line and the side's name from the sources card.
  // (plan.py's caption rule counts every spoken side line as on screen, so each one must get a panel.)
  for (const k of ['A', 'B']) {
    if (bySide[k] || !marks[`side${k}`]) continue;
    const sd = (plan.sources_card?.sides || []).find((x) => x.side === k) || {};
    bySide[k] = {side: k, label: sd.label || '', outlets: sd.read || 0, none: !sd.read};
  }
  const sides = ['A', 'B'].filter((k) => bySide[k]);
  const gap = 14;
  const top = L.content + 6, bottom = L.bottom - 4;
  const ph = sides.length > 1 ? (bottom - top - gap) / 2 : Math.min(170, bottom - top);
  const bStart = marks.sideB ? marks.sideB.start : Infinity;
  sides.forEach((k, i) => {
    const p = bySide[k];
    const mk = marks[`side${k}`];
    const color = k === 'A' ? PAL.sideA : PAL.sideB;
    const y = top + i * (ph + gap);
    const open = easeOut((t - (k === 'A' ? 0 : Math.min(bStart - 8, 12))) / 10);
    const dim = k === 'A' && t > bStart ? 0.9 : 1;      // recedes a little; at 0.55 its words read at 2.5:1
    ctx.save();
    ctx.globalAlpha = open * dim;
    ctx.fillStyle = '#FBF8EF';
    ctx.beginPath(); ctx.roundRect(L.left - 4, y, L.right - L.left + 8, ph, 6); ctx.fill();
    ctx.fillStyle = color;
    ctx.fillRect(L.left - 4, y, 4, ph);
    // the side's name: smaller when long, two lines at most, never under the outlet dots
    const [main, sub] = sideParts(p.label);
    const dotsW = (p.outlets || 0) ? 6 + (p.outlets - 1) * 7 + 8 : 0;
    const room = L.right - L.left - 14 - dotsW;
    let capSize = 10, capLines = wrapCaps(ctx, main, room, {size: capSize});
    while (capLines.length > 1 && capSize > 8) capLines = wrapCaps(ctx, main, room, {size: (capSize -= 0.5)});
    capLines = capLines.slice(0, 2);
    capLines.forEach((ln, j) => smallCaps(ctx, ln, L.left + 10, y + 20 + j * (capSize + 3), {size: capSize, color}));
    const shift = (capLines.length - 1) * (capSize + 3);
    ctx.font = `500 9px ${SANS}`;
    ctx.fillStyle = PAL.inkSoft;
    const count = p.none ? 'no coverage found' : p.outlets ? `${p.outlets} outlet${p.outlets === 1 ? '' : 's'}` : '';
    const meta = [sub, count].filter(Boolean).join(' · ');
    ctx.fillText(meta, L.left + 10, y + 33 + shift);
    for (let d = 0; d < (p.outlets || 0); d++) dot(ctx, L.right - 6 - d * 7, y + 16, 2.4, color);
    if (mk) {
      const {size, lines} = fit(ctx, mk.text, {maxWidth: L.right - L.left - 22, maxLines: Math.max(1, Math.floor((ph - 50 - shift) / 19)), max: 17, min: 13});
      drawDecodingText(ctx, lines, {x: L.left + 10, y: y + 56 + shift, size, lineHeight: size * 1.22, font: `400 ${size}px ${SERIF}`,
        color: PAL.ink, revealed: spokenChars(t, mk.words), frame: s.frame});
    }
    ctx.restore();
  });
  aiMark(ctx, false);
  ctx.restore();
}

// ---- sources: the card code draws from the script's numbers --------------------------------------------

export function drawSources(ctx, s) {
  const {t, plan} = s;
  const sc = plan.sources_card || {};
  ctx.drawImage(paperLayer(29, 0.34), 0, 0);
  ctx.save();
  ctx.scale(K, K);
  const x = L.left, w = L.right - L.left;
  const fade = (a, d = 8) => clamp01((t - a) / d);

  ctx.globalAlpha = fade(0);
  smallCaps(ctx, 'Where this came from', x, L.content + 6, {size: 8.5, color: PAL.inkSoft});
  const read = sc.read || 0;
  ctx.font = `400 56px ${SERIF}`;
  ctx.fillStyle = PAL.ink;
  ctx.fillText(String(Math.round(read * easeOut((t - 2) / 22))), x - 2, L.content + 56);
  const nw = ctx.measureText(String(read)).width;
  ctx.font = `italic 400 16px ${SERIF}`;
  ctx.fillText(read === 1 ? 'news article read' : 'news articles read', x + nw + 8, L.content + 54);

  // the balance bar: each side, then everything else
  const sides = sc.sides || [];
  const segs = [
    ...sides.map((sd) => ({n: sd.read || 0, color: sd.side === 'A' ? PAL.sideA : PAL.sideB, label: sideParts(sd.label)[0], sub: sideParts(sd.label)[1]})),
    {n: sc.elsewhere || 0, color: PAL.other, label: 'Elsewhere', sub: sc.groups?.wire ? `including ${sc.groups.wire} wire service${sc.groups.wire === 1 ? '' : 's'}` : ''},
  ].filter((g) => g.n > 0);
  const total = segs.reduce((a, g) => a + g.n, 0) || 1;
  const by = L.content + 70;
  const grow = easeOut((t - 10) / 26);
  let cx = x;
  ctx.globalAlpha = 1;
  segs.forEach((g, i) => {
    const sw = (w * g.n) / total;
    const r = rng(90 + i);
    const upto = Math.max(0, Math.min(sw - 2, w * grow - (cx - x)));
    for (let xx = 0; xx < upto; xx += 1.8) {
      for (let row = 0; row < 5; row++) dot(ctx, cx + xx + (r() - 0.5) * 0.4, by + row * 2.1, 0.8, g.color);
    }
    cx += sw;
  });
  segs.forEach((g, i) => {
    const y = by + 28 + i * 18;
    ctx.globalAlpha = fade(18 + i * 8);
    dot(ctx, x + 4, y - 3.5, 3.4, g.color);
    ctx.font = `600 10.5px ${SANS}`;
    ctx.fillStyle = PAL.ink;
    ctx.fillText(String(g.n), x + 14, y);
    ctx.font = `500 10.5px ${SANS}`;
    ctx.fillText(g.label, x + 30, y);
    if (g.sub) {
      const lw = ctx.measureText(g.label).width;
      ctx.font = `500 8.5px ${SANS}`;
      ctx.fillStyle = PAL.inkSoft;
      ctx.fillText(g.sub, x + 36 + lw, y);
    }
  });

  // the outlets, decoding
  const oy = by + 28 + (segs.length - 1) * 18 + 20;
  ctx.globalAlpha = fade(40);
  smallCaps(ctx, 'Outlets', x, oy, {size: 7.5, color: PAL.inkSoft});
  ctx.font = `500 9px ${SANS}`;
  const outLines = wrap(ctx, (sc.outlets || []).join(' · '), w).slice(0, 5);
  drawDecodingText(ctx, outLines, {x, y: oy + 13, size: 9, lineHeight: 11.5, font: `500 9px ${SANS}`, color: PAL.ink,
    revealed: typed(t, 44, 0.25), frame: s.frame});

  // credits (the site's name; full links go in the post's caption), then the AI mark right under them
  const cy = oy + 13 + (outLines.length - 1) * 11.5 + 16;
  ctx.globalAlpha = fade(70);
  ctx.font = `500 7.5px ${SANS}`;      // 7.5 units = 25 px, the smallest size the layout eval allows
  ctx.fillStyle = PAL.inkSoft;
  const credLines = [];
  for (const c of sc.credits || []) credLines.push(...wrap(ctx, c, w));
  const shown = credLines.slice(0, 6);
  shown.forEach((l, i) => ctx.fillText(l, x, cy + i * 9.3));
  ctx.globalAlpha = fade(84);
  if (sc.ai_mark) pill(ctx, sc.ai_mark, x, Math.min(L.bottom + 4, cy + (shown.length - 1) * 9.3 + 22), {bg: PAL.mustard, fg: PAL.ink, size: 8.5});
  ctx.globalAlpha = 1;
  ctx.restore();
}
