// Eval 7 (layout), only when a plan asks for it (plan.debug_layout; the eval run renders stills that way).
// Every text drawn on a beat's canvas is logged with its box in output pixels, its size and the colour behind
// it, then checked:
//   - inside the safe area (clear of TikTok's buttons and caption at the right and bottom, and the top bar);
//   - inside the frame (nothing cut off);
//   - at least the minimum size;
//   - contrast of at least 4.5:1 against what is behind it (3:1 for large text, as WCAG allows);
//   - no two different texts overlapping.
// The findings go to the browser console as one "LAYOUT {...}" line per frame; render.mjs collects them.
import {PX_H, PX_W} from './style.js';

export const SAFE = {left: 60, top: 150, right: 960, bottom: 1440};   // output pixels on the 1080 x 1920 frame
export const MIN_PX = 24;
const OVERLAP = 0.2;

function parseColor(c) {
  if (typeof c !== 'string') return null;
  let m = c.match(/^#([0-9a-f]{6})$/i);
  if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), 1];
  m = c.match(/^rgba?\(([^)]+)\)$/i);
  if (m) {
    const p = m[1].split(',').map((x) => parseFloat(x));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  return null;
}

const lin = (v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const over = (fg, a, bg) => [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));

function boxOf(ctx, text, x, y, maxWidth) {
  const m = ctx.measureText(text);
  const w = maxWidth !== undefined ? Math.min(m.width, maxWidth) : m.width;
  const al = ctx.textAlign;
  const x0 = al === 'center' ? x - w / 2 : al === 'right' || al === 'end' ? x - w : x;
  const y0 = y - m.actualBoundingBoxAscent, y1 = y + m.actualBoundingBoxDescent;
  const t = ctx.getTransform();
  const pts = [[x0, y0], [x0 + w, y0], [x0, y1], [x0 + w, y1]].map(([px, py]) => [t.a * px + t.c * py + t.e, t.b * px + t.d * py + t.f]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const size = parseFloat((ctx.font.match(/([\d.]+)px/) || [0, 0])[1]) * Math.hypot(t.a, t.b);
  return {x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys), size, base: t.b * x + t.d * y + t.f};
}

function behind(ctx, b) {
  const x = Math.max(0, Math.floor(b.x0)), y = Math.max(0, Math.floor(b.y0));
  const w = Math.min(PX_W, Math.ceil(b.x1)) - x, h = Math.min(PX_H, Math.ceil(b.y1)) - y;
  if (w <= 0 || h <= 0) return null;
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const d = ctx.getImageData(x, y, w, h).data;
  ctx.restore();
  // the median of each channel: grain and stray dots don't move it
  const ch = [[], [], []];
  for (let i = 0; i < d.length; i += 16) for (let k = 0; k < 3; k++) ch[k].push(d[i + k]);
  return ch.map((a) => a.sort((p, q) => p - q)[a.length >> 1]);
}

// Wraps the canvas's text calls for one frame. Call report() after the frame is drawn.
export function layoutProbe(ctx) {
  const texts = [];
  let lastStroke = null;
  const fill = ctx.fillText, stroke = ctx.strokeText;
  ctx.strokeText = function (text, x, y, maxWidth) {
    lastStroke = {text: String(text), x, y, color: parseColor(ctx.strokeStyle), alpha: ctx.globalAlpha};
    return maxWidth === undefined ? stroke.call(ctx, text, x, y) : stroke.call(ctx, text, x, y, maxWidth);
  };
  ctx.fillText = function (text, x, y, maxWidth) {
    const s = String(text);
    const color = parseColor(ctx.fillStyle);
    const alpha = ctx.globalAlpha * (color ? color[3] : 1);
    if (s.trim() && color && alpha >= 0.5) {
      const b = boxOf(ctx, s, x, y, maxWidth);
      let bg = behind(ctx, b);
      // a halo drawn under the same text (map labels) is what the letters are read against
      if (bg && lastStroke && lastStroke.text === s && lastStroke.x === x && lastStroke.y === y && lastStroke.color) {
        bg = over(lastStroke.color, lastStroke.color[3] * lastStroke.alpha, bg);
      }
      texts.push({text: s, ...b, contrast: bg ? ratio(over(color, alpha, bg), bg) : null});
    }
    lastStroke = null;
    return maxWidth === undefined ? fill.call(ctx, text, x, y) : fill.call(ctx, text, x, y, maxWidth);
  };
  return {
    report(beat, frame) {
      ctx.fillText = fill;
      ctx.strokeText = stroke;
      // letters drawn one by one (small caps, decoding text) are joined back into their line
      const lines = [];
      for (const t of texts) {
        const prev = lines[lines.length - 1];
        if (prev && t.text.length <= 2 && Math.abs(t.base - prev.base) < 2 && t.x0 - prev.x1 < t.size * 0.6 && t.x0 >= prev.x0) {
          prev.text += (t.x0 - prev.x1 > t.size * 0.22 ? ' ' : '') + t.text;
          prev.x1 = Math.max(prev.x1, t.x1); prev.y0 = Math.min(prev.y0, t.y0); prev.y1 = Math.max(prev.y1, t.y1);
          prev.contrast = Math.min(prev.contrast ?? 99, t.contrast ?? 99);
        } else lines.push({...t});
      }
      const problems = [];
      const where = (t) => `"${t.text.slice(0, 40)}" at ${Math.round(t.x0)},${Math.round(t.y0)}`;
      for (const t of lines) {
        if (t.x0 < 0 || t.y0 < 0 || t.x1 > PX_W || t.y1 > PX_H) problems.push({kind: 'cut off', text: where(t)});
        else if (t.x0 < SAFE.left || t.y0 < SAFE.top || t.x1 > SAFE.right || t.y1 > SAFE.bottom) problems.push({kind: 'outside safe area', text: where(t)});
        if (t.size < MIN_PX) problems.push({kind: 'small', text: where(t), size: Math.round(t.size)});
        const need = t.size >= 56 ? 3 : 4.5;
        const ornament = /^[“”"‘’«»]$/.test(t.text.trim());     // the big quotation mark is decoration, not words to read
        if (t.contrast !== null && t.contrast < need && !ornament) problems.push({kind: 'low contrast', text: where(t), contrast: Math.round(t.contrast * 10) / 10});
      }
      for (let i = 0; i < lines.length; i++) {
        for (let j = i + 1; j < lines.length; j++) {
          const a = lines[i], b = lines[j];
          if (a.text === b.text) continue;
          const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0), h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
          if (w <= 0 || h <= 0) continue;
          const small = Math.min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0));
          if (small > 0 && (w * h) / small > OVERLAP) problems.push({kind: 'overlap', text: `${where(a)} / ${where(b)}`});
        }
      }
      console.log(`LAYOUT ${JSON.stringify({beat: beat.n, shot: beat.shot, frame, texts: lines.length,
        smallest: Math.round(Math.min(...lines.map((t) => t.size), 999)), problems})}`);
    },
  };
}
