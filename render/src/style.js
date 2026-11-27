// Shared look, from the approved render test (Nov 24): drawing is done in "sketch units" (324 x 576,
// the size of the approved sketch) and scaled by K to the 1080 x 1920 video. Every canvas is
// processor-backed (willReadFrequently) and heavy dot layers are made once and reused (render test rules).
import {staticFile} from 'remotion';
import {loadFont} from '@remotion/fonts';

export const W = 324;
export const H = 576;
export const K = 1080 / W;
export const PX_W = 1080;
export const PX_H = 1920;

// Layout in sketch units. TikTok's own buttons and text cover the top ~150 px, the right ~150 px and the
// bottom ~480 px, so text stays between TOP and BOTTOM and left of RIGHT.
export const L = {
  top: 50, tags: 56, content: 74, bottom: 362, right: 276, left: 24,
  captionTop: 381, // 1270 px
};

export const PAL = {
  paper: '#F3EEE1',
  paperDeep: '#E9E2CF',
  ink: '#1A2A86',
  inkSoft: 'rgba(26,42,134,0.76)',     // 0.62 read at 3.8:1 on the grain (layout eval, Nov 26); 0.76 is over 5:1
  tag: '#B5401F',                      // a deeper vermilion: paper letters on it read at 4.9:1 (vermilion: 2.9)
  sea: '#1E3191',
  landBase: '#2A6E3A',
  vermilion: '#E8622C',
  mustard: '#E0A12A',
  cobalt: '#3552BE',
  sky: '#A8C9EA',
  sideA: '#3552BE',
  sideB: '#C2452D',
  other: '#9AA3B8',
  skyA: [121, 171, 219],
  skyB: [168, 201, 234],
};

export const SERIF = 'StringerSerif';
export const SANS = 'StringerSans';

export const fontsLoaded = Promise.all([
  loadFont({family: SERIF, url: staticFile('fonts/serif-400.woff2'), weight: '400'}),
  loadFont({family: SERIF, url: staticFile('fonts/serif-400-italic.woff2'), weight: '400', style: 'italic'}),
  loadFont({family: SANS, url: staticFile('fonts/sans-500.woff2'), weight: '500'}),
  loadFont({family: SANS, url: staticFile('fonts/sans-600.woff2'), weight: '600'}),
]);

// Seeded random numbers, so every frame is reproducible (Remotion needs that).
export function rng(seed) {
  let s = Math.abs(Math.floor(seed)) % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

export function hash(str) {
  let h = 2166136261;
  for (const ch of String(str)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return Math.abs(h) || 1;
}

export const clamp01 = (v) => Math.max(0, Math.min(1, v));
export const easeOut = (v) => 1 - Math.pow(1 - clamp01(v), 3);
export const easeInOut = (v) => { const x = clamp01(v); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };

export const ctx2d = (c) => c.getContext('2d', {willReadFrequently: true});

export function makeCanvas(w = PX_W, h = PX_H) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

// Layers made once per browser tab, reused on every frame.
const cache = {};
export const once = (key, build) => (cache[key] ||= build());

// Cream paper with blue halftone grain, in 2 x 2 pixel blocks so H.264 keeps it.
// density(yPx) returns the chance that a block is blue.
export function paintGrain(ctx, seed, density) {
  const r = rng(seed);
  const img = ctx.createImageData(PX_W, PX_H);
  const d = img.data;
  for (let by = 0; by < PX_H; by += 2) {
    const pb = density(by);
    for (let bx = 0; bx < PX_W; bx += 2) {
      let c0 = 243, c1 = 238, c2 = 225;
      if (pb > 0 && r() < pb) {
        const s = r() < 0.55 ? PAL.skyA : PAL.skyB;
        c0 = s[0]; c1 = s[1]; c2 = s[2];
      }
      const n = (r() - 0.5) * 12;
      for (let oy = 0; oy < 2; oy++) {
        for (let ox = 0; ox < 2; ox++) {
          const i = ((by + oy) * PX_W + bx + ox) * 4;
          d[i] = c0 + n; d[i + 1] = c1 + n; d[i + 2] = c2 + n; d[i + 3] = 255;
        }
      }
    }
  }
  ctx.putImageData(img, 0, 0);
}

// The plain paper background most cards use: grain heavier at the top, fading down.
export const paperLayer = (seed = 21, top = 0.36) => once(`paper-${seed}-${top}`, () => {
  const c = makeCanvas();
  paintGrain(ctx2d(c), seed, (y) => top * Math.pow(1 - y / PX_H, 1.5) + 0.025);
  return c;
});

// A braille cell (2 x 4 dots) standing in for a letter that hasn't decoded yet.
function brailleCell(ctx, x, baseline, w, size, r, color) {
  const top = baseline - size * 0.7;
  const step = (size * 0.7) / 4;
  const rad = size * 0.05;
  ctx.fillStyle = color;
  for (let col = 0; col < 2; col++) {
    for (let row = 0; row < 4; row++) {
      if (r() < 0.5) {
        ctx.beginPath();
        ctx.arc(x + w * (col ? 0.68 : 0.32), top + step * (row + 0.5), rad, 0, 6.283);
        ctx.fill();
      }
    }
  }
}

// Text that decodes from braille dots into letters, left to right.
// lines: strings; revealed: how many characters are letters so far. colorOf(k) may color a character.
export function drawDecodingText(ctx, lines, {x, y, size, lineHeight, font, color, revealed, frame, colorOf, align = 'left'}) {
  const r = rng(1000 + frame * 7);
  ctx.font = font;
  let k = 0;
  lines.forEach((line, li) => {
    const lw = ctx.measureText(line).width;
    let cx = align === 'center' ? x - lw / 2 : x;
    const baseline = y + li * lineHeight;
    for (const ch of line) {
      const w = ctx.measureText(ch).width;
      const col = colorOf ? colorOf(k) || color : color;
      if (ch === ' ' || k < revealed) {
        ctx.fillStyle = col;
        ctx.fillText(ch, cx, baseline);
      } else {
        brailleCell(ctx, cx, baseline, w, size, r, col);
      }
      cx += w;
      k++;
    }
    k++; // the line break counts as one character, like a space
  });
}

// Greedy word wrap with the current font; returns lines.
export function wrap(ctx, text, maxWidth) {
  const words = String(text || '').split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (ctx.measureText(next).width <= maxWidth || !cur) cur = next;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  return lines;
}

// No line wider than the box (a single long word can't wrap, so the size has to come down instead).
const fitsWidth = (ctx, lines, maxWidth) => lines.every((l) => ctx.measureText(l).width <= maxWidth + 0.5);

// The largest font size (from max down to min) at which text fits in maxLines lines.
export function fit(ctx, text, {maxWidth, maxLines, max, min, family = SERIF, weight = 400, style = ''}) {
  for (let size = max; size >= min; size -= 1) {
    ctx.font = `${style} ${weight} ${size}px ${family}`.trim();
    const lines = wrap(ctx, text, maxWidth);
    if (lines.length <= maxLines && fitsWidth(ctx, lines, maxWidth)) return {size, lines};
  }
  ctx.font = `${style} ${weight} ${min}px ${family}`.trim();
  return {size: min, lines: wrap(ctx, text, maxWidth)};
}

// The largest size (max down to min) at which text fits in a box maxWidth wide and maxHeight tall.
export function fitBox(ctx, text, {maxWidth, maxHeight, max, min, lh = 1.2, family = SERIF, weight = 400, style = ''}) {
  for (let size = max; size >= min; size -= 1) {
    ctx.font = `${style} ${weight} ${size}px ${family}`.trim();
    const lines = wrap(ctx, text, maxWidth);
    if (lines.length * size * lh <= maxHeight && fitsWidth(ctx, lines, maxWidth)) return {size, lines};
  }
  ctx.font = `${style} ${weight} ${min}px ${family}`.trim();
  return {size: min, lines: wrap(ctx, text, maxWidth)};
}

// Word wrap for letter-spaced small caps (the spacing counts toward the width).
export function wrapCaps(ctx, text, maxWidth, {size = 9.5, spacing = 0.9, weight = 600} = {}) {
  ctx.font = `${weight} ${size}px ${SANS}`;
  const width = (t) => ctx.measureText(t).width + t.length * spacing;
  const words = String(text || '').toUpperCase().split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (width(next) <= maxWidth || !cur) cur = next;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  return lines;
}

export const dot = (ctx, x, y, rad, color) => {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, rad, 0, 6.283);
  ctx.fill();
};

// A bar made of fine dots (rows x columns), filled to frac.
export function dotBar(ctx, x, y, width, frac, color, {rows = 4, step = 1.7, rad = 0.85, seed = 3} = {}) {
  const r = rng(seed);
  const n = Math.floor(width / step);
  const upto = Math.floor(n * clamp01(frac));
  for (let i = 0; i < upto; i++) {
    for (let row = 0; row < rows; row++) dot(ctx, x + i * step + (r() - 0.5) * 0.5, y + row * step * 1.1, rad, color);
  }
}

export function smallCaps(ctx, text, x, y, {size = 9.5, color = PAL.ink, align = 'left', spacing = 0.9, weight = 600} = {}) {
  ctx.font = `${weight} ${size}px ${SANS}`;
  ctx.fillStyle = color;
  const t = String(text || '').toUpperCase();
  let cx = x;
  if (align !== 'left') {
    let w = 0;
    for (const ch of t) w += ctx.measureText(ch).width + spacing;
    cx = align === 'right' ? x - w : x - w / 2;
  }
  for (const ch of t) {
    ctx.fillText(ch, cx, y);
    cx += ctx.measureText(ch).width + spacing;
  }
}

export function pill(ctx, text, x, y, {bg = PAL.tag, fg = PAL.paper, size = 9, pad = 5} = {}) {
  ctx.font = `600 ${size}px ${SANS}`;
  const t = String(text).toUpperCase();
  const w = ctx.measureText(t).width + t.length * 0.8 + pad * 2;
  ctx.fillStyle = bg;
  ctx.beginPath();
  ctx.roundRect(x, y - size - 3, w, size + 8, (size + 8) / 2);
  ctx.fill();
  smallCaps(ctx, t, x + pad, y + 1, {size, color: fg, spacing: 0.8});
  return w;
}

// Initials in a dotted circle: the stand-in when a person has no approved portrait.
export function initialsBadge(ctx, name, cx, cy, rad, seed = 7) {
  const r = rng(seed + hash(name));
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, rad, 0, 6.283);
  ctx.clip();
  for (let y = cy - rad; y < cy + rad; y += 1.5) {
    for (let x = cx - rad; x < cx + rad; x += 1.6) {
      const q = r();
      dot(ctx, x + (r() - 0.5), y + (r() - 0.5), 0.55, q < 0.5 ? '#2A47B0' : q < 0.8 ? '#1A2A86' : '#7FA4E2');
    }
  }
  ctx.restore();
  const ini = String(name || '?').split(/\s+/).filter((w) => /^[A-ZÀ-Ž]/.test(w)).slice(0, 2).map((w) => w[0]).join('') || '?';
  ctx.font = `400 ${rad * 0.9}px ${SERIF}`;
  ctx.fillStyle = PAL.paper;
  ctx.textAlign = 'center';
  ctx.fillText(ini, cx, cy + rad * 0.32);
  ctx.textAlign = 'left';
}

// How many characters of text have been spoken by time t (frames from the shot's start), given the
// marked words with their frames: each word decodes in the first 60% of the time it is spoken.
export function spokenChars(t, words) {
  let done = 0;
  for (const w of words) {
    const full = w.start + 0.6 * Math.max(1, w.end - w.start);
    if (t >= full) { done += w.w.length + 1; continue; }
    if (t >= w.start) return done + Math.floor((w.w.length * (t - w.start)) / Math.max(1, full - w.start));
    break;
  }
  return done;
}

// Numbers in a value ("$6.3 billion", "1,441") split so they can count up: prefix, number, decimals, suffix.
export function parseValue(v) {
  const m = String(v || '').match(/^(\D*?)(\d[\d,]*)(\.\d+)?(.*)$/);
  if (!m) return null;
  return {prefix: m[1], n: Number(m[2].replace(/,/g, '')), commas: m[2].includes(','), dec: m[3] ? m[3].length - 1 : 0,
    decimals: m[3] ? Number(m[3]) : 0, suffix: m[4]};
}

export function formatCount(p, frac) {
  const total = p.n + p.decimals;
  const v = total * clamp01(frac);
  let s = p.dec ? v.toFixed(p.dec) : String(Math.round(v));
  if (p.commas) {
    const [a, b] = s.split('.');
    s = a.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (b ? `.${b}` : '');
  }
  return `${p.prefix}${s}${p.suffix}`;
}
