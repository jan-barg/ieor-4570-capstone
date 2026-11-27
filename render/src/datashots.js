// The paper shots that carry facts: big number, timeline, quote, two accounts, document and tally.
// Each animation is pinned to the beat's marked words (beat.marks, frames from the beat's start); when a
// mark is missing, the step falls back to an even spread over the beat. Each shot measures its block
// first and centres it between the top marks and the captions.
import {
  K, L, PAL, SANS, SERIF, clamp01, dot, drawDecodingText, easeOut, fit, fitBox, formatCount, paperLayer,
  parseValue, rng, smallCaps, spokenChars, wrap, wrapCaps,
} from './style.js';
import {aiMark, chipHeight, sourceChip} from './cards.js';

const W_TEXT = L.right - L.left;
const TOP = L.content + 4;
const BOTTOM = L.bottom - 22;                    // room for a one-line "Source:" label under the block
const marksOf = (beat, name) => beat.marks.filter((m) => m.mark === name);
const centred = (h, bottom = BOTTOM) => TOP + Math.max(0, (bottom - TOP - h) * 0.45);
const bottomFor = (ctx, beat) => L.bottom - Math.max(16, chipHeight(ctx, beat.label)) - 8;

// How far a mark has been read: 0 before it starts, 1 once 60% of it has been spoken.
const readFrac = (t, m) => (m ? clamp01((t - m.start) / Math.max(4, 0.6 * (m.end - m.start))) : 0);

// The k-th of n things: its own mark if there is one, else an even slot in the beat.
function slot(beat, marks, k, n) {
  if (marks[k]) return marks[k];
  if (marks.length === 1 && n > 1) return marks[0];
  const span = beat.frames - 20;
  return {start: 8 + (span * k) / n, end: 8 + (span * (k + 0.8)) / n, words: []};
}

function begin(ctx, seed, top = 0.32) {
  ctx.drawImage(paperLayer(seed, top), 0, 0);
  ctx.save();
  ctx.scale(K, K);
}

function end(ctx, s, {chip = true} = {}) {
  aiMark(ctx, false);
  if (chip) sourceChip(ctx, s.beat.label, s.t);
  ctx.restore();
}

const same = (a, b) => String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase();

// ---- big number: the figure is there from the start, faint, and inks in while it is said (Jan's pick,
// Nov 27: a card that waits for its number looked empty for seconds); a second figure gets a bar each ------

export function drawBigNumber(ctx, s) {
  const {beat, t} = s;
  const bl = beat.blanks || {};
  begin(ctx, 31, 0.38);
  const count = marksOf(beat, 'count')[0] || {start: 6, end: 30};
  const compare = marksOf(beat, 'compare')[0];
  const value = String(bl.value || '');
  const pv = parseValue(value);
  const cv = parseValue(bl.compare_value);
  const withCompare = !!(bl.compare_value && pv && cv);
  const label = same(bl.label, bl.unit) ? '' : bl.label;

  // measure
  const unitLines = wrapCaps(ctx, bl.unit, W_TEXT, {size: 11}).slice(0, 2);
  const {size, lines} = fit(ctx, value, {maxWidth: W_TEXT, maxLines: 2, max: value.length <= 4 ? 132 : 96, min: 40});
  ctx.font = `italic 400 19px ${SERIF}`;
  const labelLines = label ? wrap(ctx, label, W_TEXT).slice(0, 2) : [];
  const vh = size * 0.78 + (lines.length - 1) * size * 1.0;
  const h = unitLines.length * 14 + 14 + vh + 22 + labelLines.length * 23 + (withCompare ? 84 : 0);
  let y = centred(h);

  ctx.globalAlpha = clamp01(t / 8);
  unitLines.forEach((u, i) => smallCaps(ctx, u, L.left, y + 10 + i * 14, {size: 11}));
  ctx.globalAlpha = 1;
  y += unitLines.length * 14 + 14;

  // the whole figure from the start (never a number it isn't), at 40% ink until it is said
  const pc = easeOut((t - count.start) / Math.max(8, count.end - count.start));   // the bar below grows with it
  const spoken = clamp01((t - count.start + 6) / 6);
  ctx.globalAlpha = clamp01(t / 8) * (0.4 + 0.6 * spoken);
  ctx.font = `400 ${size}px ${SERIF}`;
  ctx.fillStyle = PAL.ink;
  lines.forEach((l, i) => ctx.fillText(l, L.left - 2, y + size * 0.78 + i * size));
  ctx.globalAlpha = 1;
  y += vh + 12;

  // a mustard dotted rule sweeps under the figure as the count finishes
  const r = rng(33);
  const sweep = easeOut((t - count.end + 4) / 12);
  for (let x = 0; x < W_TEXT * sweep; x += 1.8) dot(ctx, L.left + x + (r() - 0.5) * 0.4, y, 0.9, PAL.mustard);
  y += 10;
  if (labelLines.length) {
    ctx.globalAlpha = clamp01((t - 4) / 10);
    ctx.font = `italic 400 19px ${SERIF}`;
    ctx.fillStyle = PAL.ink;
    labelLines.forEach((l, i) => ctx.fillText(l, L.left, y + 18 + i * 23));
    ctx.globalAlpha = 1;
    y += labelLines.length * 23;
  }

  // the comparison: two bars made of dots
  if (withCompare) {
    y += 30;
    const at = compare ? compare.start : count.end + 20;
    const g = easeOut((t - at) / Math.max(10, compare ? compare.end - compare.start : 24));
    const a = pv.n + pv.decimals, b = cv.n + cv.decimals;
    const most = Math.max(a, b) || 1;
    ctx.globalAlpha = clamp01((t - at + 4) / 6);
    const bar = (yy, frac, color, text, seed) => {
      const rr = rng(seed);
      for (let x = 0; x < W_TEXT * frac; x += 1.8) {
        for (let row = 0; row < 5; row++) dot(ctx, L.left + x + (rr() - 0.5) * 0.4, yy + row * 2.2, 0.85, color);
      }
      ctx.font = `500 10.5px ${SANS}`;
      ctx.fillStyle = PAL.ink;
      ctx.fillText(text, L.left, yy - 5);
    };
    bar(y, (a / most) * pc, PAL.mustard, value, 40);
    bar(y + 34, (b / most) * g, PAL.cobalt, `${bl.compare_value}${bl.compare_label ? ` · ${bl.compare_label}` : ''}`, 41);
    ctx.globalAlpha = 1;
  }
  end(ctx, s);
}

// ---- timeline: a dotted line down the left; each step lands on its node as it is said ----------------

export function drawTimeline(ctx, s) {
  const {beat, t} = s;
  const steps = ((beat.blanks || {}).steps || []).slice(0, 4);
  begin(ctx, 35, 0.3);
  const marks = marksOf(beat, 'step');
  const n = Math.max(1, steps.length);
  const x0 = L.left + 8, tx = L.left + 32;
  const gap = n > 1 ? Math.min(112, (BOTTOM - TOP - 70) / (n - 1)) : 0;
  const texts = steps.map((st) => fitBox(ctx, st.what || '', {maxWidth: L.right - tx, maxHeight: gap ? gap - 26 : 120, max: 26, min: 15, lh: 1.16}));
  const lastH = texts.length ? texts[n - 1].lines.length * texts[n - 1].size * 1.16 + 14 : 0;
  const top = centred((n - 1) * gap + lastH) + 8;
  const times = steps.map((_, k) => slot(beat, marks, k, n));
  // the line between nodes grows from one step to the next
  const r = rng(36);
  for (let k = 0; k < n - 1; k++) {
    const ya = top + k * gap, yb = top + (k + 1) * gap;
    const g = clamp01((t - times[k].start) / Math.max(8, times[k + 1].start - times[k].start));
    for (let y = ya + 9; y < ya + 9 + (yb - ya - 18) * g; y += 2.4) dot(ctx, x0 + (r() - 0.5) * 0.4, y, 0.85, PAL.inkSoft);
  }
  steps.forEach((st, k) => {
    const y = top + k * gap;
    const m = times[k];
    const on = t >= m.start - 3;
    ctx.strokeStyle = PAL.ink;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.arc(x0, y, 6, 0, 6.283);
    ctx.stroke();
    if (on) dot(ctx, x0, y, 6 * easeOut((t - m.start + 3) / 6), PAL.vermilion);
    let ty = y + 5;
    if (st.when) {
      ctx.globalAlpha = clamp01((t - m.start + 3) / 6);
      smallCaps(ctx, st.when, tx, y - 6, {size: 9.5, color: PAL.tag});
      ctx.globalAlpha = 1;
      ty = y + 14;
    }
    const {size, lines} = texts[k];
    drawDecodingText(ctx, lines, {x: tx, y: ty + size * 0.4, size, lineHeight: size * 1.16, font: `400 ${size}px ${SERIF}`,
      color: on ? PAL.ink : 'rgba(26,42,134,0.35)', revealed: Math.floor(lines.join(' ').length * readFrac(t, m)),
      frame: s.frame + k * 13});
  });
  end(ctx, s);
}

// ---- quote: who says it, then their exact words, decoding as they are read -------------------------

export function drawQuote(ctx, s) {
  const {beat, t} = s;
  const bl = beat.blanks || {};
  const q = bl.quote || {};
  const text = typeof q === 'string' ? q : q.text || '';
  begin(ctx, 41, 0.3);
  const mk = marksOf(beat, 'quote')[0];
  const full = `${text}”`;
  const head = bl.role ? 34 : 20;
  const bottom = bottomFor(ctx, beat);
  const room = bottom - TOP - 14 - head - 62 - (q.translated_from ? 16 : 0);
  // a cutout portrait stands below the words (Jan's pick, Nov 27), so they start at the top and keep to a smaller box
  const standing = !!(beat.broll?.portrait?.cutoutSrc && beat.broll?.portrait?.face);
  const {size, lines} = fitBox(ctx, full, {maxWidth: W_TEXT, maxHeight: standing ? Math.min(96, room) : Math.min(170, room),
    max: standing ? 26 : 32, min: 16, lh: 1.26});
  const h = head + 62 + lines.length * size * 1.26 + (q.translated_from ? 16 : 0);
  const y0 = standing ? TOP + 10 : centred(h, bottom) + 14;
  s.portraitAt = [L.right - 26, y0 + 2];
  ctx.globalAlpha = clamp01(t / 8);
  ctx.font = `600 16px ${SANS}`;
  ctx.fillStyle = PAL.ink;
  const nameW = beat.broll?.portrait?.src && !standing ? L.right - L.left - 62 : L.right - L.left;   // clear of the badge
  ctx.fillText(bl.speaker || q.speaker || '', L.left, y0, nameW);
  if (bl.role) {
    ctx.font = `500 11.5px ${SANS}`;
    ctx.fillStyle = PAL.inkSoft;
    ctx.fillText(bl.role, L.left, y0 + 16, nameW);
  }
  ctx.globalAlpha = clamp01((t - 4) / 8);
  ctx.font = `400 96px ${SERIF}`;
  ctx.fillStyle = PAL.vermilion;
  ctx.fillText('“', L.left - 4, y0 + head + 66);
  ctx.globalAlpha = 1;
  // the closing mark arrives with the last word
  const said = mk ? spokenChars(t, mk.words) : Math.floor(full.length * clamp01((t - 10) / Math.max(10, beat.frames - 30)));
  const ty = y0 + head + 62 + size * 0.8;
  drawDecodingText(ctx, lines, {x: L.left, y: ty, size, lineHeight: size * 1.26, font: `400 ${size}px ${SERIF}`,
    color: PAL.ink, revealed: said >= text.length ? full.length : said, frame: s.frame});
  if (q.translated_from) {
    ctx.font = `500 9.5px ${SANS}`;
    ctx.fillStyle = PAL.inkSoft;
    ctx.fillText(`Translated from ${q.translated_from}`, L.left, ty + (lines.length - 1) * size * 1.26 + 18);
  }
  end(ctx, s);
}

// ---- two accounts that disagree: two slips and a "vs" between them. Each slip names its source, so the
// "Source:" label is left off this shot.

export function drawClaims(ctx, s) {
  const {beat, t} = s;
  const acc = ((beat.blanks || {}).accounts || []).slice(0, 2);
  begin(ctx, 43, 0.3);
  const top = L.content + 6, bottom = L.bottom - 2, gap = 30;
  const ph = (bottom - top - gap) / 2;
  const ms = [marksOf(beat, 'left')[0], marksOf(beat, 'right')[0]];
  acc.forEach((a, i) => {
    const m = ms[i] || slot(beat, [], i, 2);
    const y = top + i * (ph + gap);
    const open = easeOut((t - (i === 0 ? 0 : Math.min(m.start - 6, 14))) / 10);
    ctx.save();
    ctx.globalAlpha = open * (i === 0 && ms[1] && t > ms[1].start ? 0.86 : 1);   // at 0.6 its words read at 3.7:1
    ctx.fillStyle = '#FBF8EF';
    ctx.beginPath(); ctx.roundRect(L.left - 4, y, W_TEXT + 8, ph, 6); ctx.fill();
    ctx.fillStyle = PAL.ink;
    ctx.fillRect(L.left - 4, y, W_TEXT + 8, 2.5);
    const who = wrapCaps(ctx, a.who, W_TEXT - 16, {size: 9.5, spacing: 0.6}).slice(0, 3);
    who.forEach((l, k) => smallCaps(ctx, l, L.left + 8, y + 20 + k * 12, {size: 9.5, spacing: 0.6}));
    const says = a.says || a.what || '';
    const room = ph - (24 + who.length * 12) - 12;
    const {size, lines} = fitBox(ctx, says, {maxWidth: W_TEXT - 16, maxHeight: room, max: 26, min: 14, lh: 1.18});
    drawDecodingText(ctx, lines, {x: L.left + 8, y: y + 24 + who.length * 12 + size * 0.95, size, lineHeight: size * 1.18,
      font: `400 ${size}px ${SERIF}`, color: PAL.ink, revealed: Math.floor(says.length * readFrac(t, m)), frame: s.frame + i * 17});
    ctx.restore();
  });
  // the "vs" coin between the two slips
  const cy = top + ph + gap / 2;
  const pop = easeOut((t - 6) / 8);
  if (pop > 0) {
    dot(ctx, L.left + W_TEXT / 2, cy, 13 * pop, PAL.tag);
    ctx.globalAlpha = pop;
    ctx.font = `italic 400 14px ${SERIF}`;
    ctx.fillStyle = PAL.paper;
    ctx.textAlign = 'center';
    ctx.fillText('vs', L.left + W_TEXT / 2, cy + 4.5);
    ctx.textAlign = 'left';
    ctx.globalAlpha = 1;
  }
  end(ctx, s, {chip: false});
}

// ---- document: a sheet with its kind, name and issuer; the outcome is stamped on when it is said -----

export function drawDocument(ctx, s) {
  const {beat, t} = s;
  const bl = beat.blanks || {};
  begin(ctx, 47, 0.34);
  const x = L.left + 6, w = W_TEXT - 12, y = L.content + 4, h = BOTTOM - L.content - 4;
  const slide = easeOut(t / 10);
  ctx.save();
  ctx.translate(0, (1 - slide) * 20);
  ctx.globalAlpha = slide;
  ctx.fillStyle = 'rgba(26,42,134,0.10)';
  ctx.beginPath(); ctx.roundRect(x + 4, y + 5, w, h, 3); ctx.fill();
  ctx.fillStyle = '#FBF8EF';
  ctx.beginPath(); ctx.roundRect(x, y, w, h, 3); ctx.fill();
  const kind = bl.doc_kind && bl.doc_kind !== 'other' ? bl.doc_kind : '';
  if (kind) smallCaps(ctx, kind, x + 16, y + 26, {size: 9.5, color: PAL.tag});
  const {size, lines} = fit(ctx, bl.title || '', {maxWidth: w - 32, maxLines: 3, max: 26, min: 16});
  drawDecodingText(ctx, lines, {x: x + 16, y: y + 36 + size, size, lineHeight: size * 1.18, font: `400 ${size}px ${SERIF}`,
    color: PAL.ink, revealed: Math.max(0, Math.floor((t - 6) / 1.1)), frame: s.frame});
  let ly = y + 36 + size + (lines.length - 1) * size * 1.18 + 18;
  if (bl.issued_by) {
    ctx.font = `500 11px ${SANS}`;
    ctx.fillStyle = PAL.inkSoft;
    wrap(ctx, bl.issued_by, w - 32).slice(0, 2).forEach((l, i) => ctx.fillText(l, x + 16, ly + i * 14));
    ly += 32;
  }
  // grey lines of "text", made of dots
  const r = rng(48);
  for (let row = 0; ly + row * 11 < y + h - 18; row++) {
    const len = (w - 32) * (row % 4 === 3 ? 0.55 : 0.85 + r() * 0.15);
    for (let xx = 0; xx < len; xx += 2.2) dot(ctx, x + 16 + xx, ly + row * 11, 0.7, 'rgba(26,42,134,0.22)');
  }
  ctx.restore();

  // the stamp: the outcome in a rotated box (sized to fit the sheet), or a plain seal with no outcome
  const mk = marksOf(beat, 'stamp')[0];
  const at = mk ? mk.start : Math.round(beat.frames * 0.55);
  const p = clamp01((t - at) / 5);
  if (p > 0) {
    const sc = 1 + 0.6 * (1 - easeOut(p));
    ctx.save();
    ctx.translate(x + w * 0.5, y + h * 0.7);
    ctx.rotate(-0.14);
    ctx.scale(sc, sc);
    ctx.globalAlpha = 0.9 * p;
    ctx.strokeStyle = PAL.tag;
    if (bl.outcome) {
      const label = String(bl.outcome).toUpperCase();
      let fs = 17;
      const width = () => { ctx.font = `600 ${fs}px ${SANS}`; return ctx.measureText(label).width + label.length * 1.2; };
      while (fs > 9 && width() > w * 0.72) fs -= 0.5;
      const tw = width();
      ctx.lineWidth = 2.2;
      ctx.strokeRect(-tw / 2 - 10, -fs - 2, tw + 20, fs * 2);
      smallCaps(ctx, label, 0, fs * 0.36, {size: fs, color: PAL.tag, align: 'center', spacing: 1.2});
    } else {
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(0, 0, 24, 0, 6.283); ctx.stroke();
      ctx.beginPath(); ctx.arc(0, 0, 17, 0, 6.283); ctx.stroke();
      const rr = rng(49);
      for (let a = 0; a < 6.283; a += 0.2) dot(ctx, Math.cos(a) * 20.5, Math.sin(a) * 20.5, 0.9, PAL.vermilion);
      for (let k = 0; k < 40; k++) dot(ctx, (rr() - 0.5) * 22, (rr() - 0.5) * 22, 0.7, PAL.vermilion);
    }
    ctx.restore();
  }
  end(ctx, s);
}

// ---- tally: one dotted bar per row, counting up as each number is said; a marker at the total --------

export function drawTally(ctx, s) {
  const {beat, t} = s;
  const bl = beat.blanks || {};
  const rows = (bl.rows || []).slice(0, 6);
  begin(ctx, 53, 0.32);
  const marks = marksOf(beat, 'count');
  const vals = rows.map((r) => parseValue(r.value));
  const total = parseValue(bl.total);
  const nums = vals.map((v) => (v ? v.n + v.decimals : 0));
  const scale = Math.max(1, ...nums, total ? total.n + total.decimals : 0) * 1.08;
  const rowH = Math.min(76, (BOTTOM - TOP - 30) / Math.max(1, rows.length));
  const y0 = centred(rows.length * rowH + (total ? 18 : 0)) + 28;
  const times = rows.map((_, k) => slot(beat, marks, k, rows.length));
  rows.forEach((row, k) => {
    const m = times[k];
    const g = easeOut((t - m.start) / Math.max(8, m.end - m.start));
    const y = y0 + k * rowH;
    ctx.globalAlpha = clamp01((t - 2 - k * 3) / 6);
    ctx.font = `500 13px ${SANS}`;
    ctx.fillStyle = PAL.ink;
    ctx.fillText(row.label || '', L.left, y);
    ctx.font = `400 30px ${SERIF}`;
    ctx.textAlign = 'right';
    ctx.fillText(vals[k] ? formatCount(vals[k], g) : String(row.value || ''), L.right, y + 4);
    ctx.textAlign = 'left';
    ctx.globalAlpha = 1;
    const color = [PAL.cobalt, PAL.mustard, PAL.vermilion, PAL.sky, PAL.other, PAL.ink][k];
    const rr = rng(60 + k);
    const len = W_TEXT * (nums[k] / scale) * g;
    for (let x = 0; x < len; x += 1.8) {
      for (let r2 = 0; r2 < 7; r2++) dot(ctx, L.left + x + (rr() - 0.5) * 0.4, y + 12 + r2 * 2.2, 0.9, color);
    }
  });
  if (total) {
    const tx = L.left + W_TEXT * ((total.n + total.decimals) / scale);
    const after = Math.max(...times.map((m) => m.end));
    ctx.globalAlpha = clamp01((t - after) / 10);
    const yEnd = y0 + (rows.length - 1) * rowH + 30;
    for (let y = y0 - 4; y < yEnd; y += 3) dot(ctx, tx, y, 0.9, PAL.vermilion);
    smallCaps(ctx, String(bl.total), tx, yEnd + 14, {size: 11, color: PAL.tag, align: 'center'});
    ctx.globalAlpha = 1;
  }
  end(ctx, s);
}
