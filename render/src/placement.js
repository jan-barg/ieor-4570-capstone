// Where a portrait may go (Jan's pick, Nov 27: a sticker on the hook and headlines, the person standing on quotes).
// The rule, for every look:
//   1. draw the beat's LAST frame out of sight once and note where every word, map label, line and pin lands;
//   2. put the person in the biggest space that touches none of it, with the face clear of the captions, TikTok's
//      top bar and its buttons on the right. A standing person's body may run behind the captions; the bottom of
//      the photo fades out there.
// All boxes are in sketch units (324 x 576), as [x0, y0, x1, y1, gap to keep from it].
import {H, K, L, W, ctx2d, makeCanvas, once} from './style.js';

// The clear space kept around the person grows with the size of the words (Jan, Nov 27: 7 units read as touching
// the big headline; a flat 16 left no room on a map full of small place names). In sketch units; one unit is
// 3.3 px of the 1080 x 1920 frame.
export const GAP = 16;            // the most: around big words (a headline), lines and chips (about 53 px)
export const MIN_GAP = 6;         // the least: around small words (map labels) and pins (about 20 px)
export const gapFor = (height) => Math.max(MIN_GAP, Math.min(GAP, 0.6 * height));   // a line of a quote: about 12
export const CAPTION_GAP = 12;    // from the top of the captions (about 40 px)
export const POP = 1.04;          // the sticker's bounce grows it this much for a moment; the fit leaves room for it
export const BORDER = 4.5;        // the sticker's paper edge, outside the cut line; the gaps count from its outside
export const TILT = -3;           // the sticker's resting tilt in degrees, about its bottom middle; the fit uses it
export const BREATHE = 1.03;      // the standing person slowly grows this much, upward; the fit leaves room for it
export const STICKER_H = 96;      // the sticker height a headline keeps room for under its bar (about 320 px)

// Does this beat draw a cutout portrait? (the plan's photo, staged by render.mjs, with a face box)
export const hasCutout = (beat) => beat.broll?.kind === 'portrait' && !!(beat.broll?.portrait?.cutoutSrc && beat.broll?.portrait?.face);
// The free band a sticker of height h needs between words above it and the captions: its gaps, its paper edge
// top and bottom, and its bounce.
export const stickerBand = (h = STICKER_H) => GAP + 2 * BORDER + POP * h + CAPTION_GAP;

// The box a fillText call covers, in the canvas's own pixels.
export function textBox(ctx, text, x, y, maxWidth) {
  const m = ctx.measureText(text);
  const w = maxWidth !== undefined ? Math.min(m.width, maxWidth) : m.width;
  const al = ctx.textAlign;
  const x0 = al === 'center' ? x - w / 2 : al === 'right' || al === 'end' ? x - w : x;
  const y0 = y - m.actualBoundingBoxAscent, y1 = y + m.actualBoundingBoxDescent;
  const t = ctx.getTransform();
  const pts = [[x0, y0], [x0 + w, y0], [x0, y1], [x0 + w, y1]].map(([px, py]) => [t.a * px + t.c * py + t.e, t.b * px + t.d * py + t.f]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

// A layer drawn once and reused (the map) keeps a list of the words on it, so the fit sees them whoever drew it first.
export function recordTexts(canvas, ctx) {
  canvas.texts = [];
  const fill = ctx.fillText;
  ctx.fillText = function (text, x, y, maxWidth) {
    const s = String(text);
    if (s.trim() && ctx.globalAlpha > 0.05) canvas.texts.push(textBox(ctx, s, x, y, maxWidth));
    return maxWidth === undefined ? fill.call(ctx, text, x, y) : fill.call(ctx, text, x, y, maxWidth);
  };
}

// ---- 1. what the finished beat keeps clear ------------------------------------------------------------------

export function finishedLayout(beat, plan, draw, extra) {
  return once(`finished-${plan.story?.id}-${beat.n}-${beat.start}`, () => {
    const c = makeCanvas();
    const ctx = ctx2d(c);
    const boxes = [];
    const toSketch = (b) => b.map((v) => v / K);
    const fill = ctx.fillText, rect = ctx.fillRect, image = ctx.drawImage;
    ctx.fillText = function (text, x, y, maxWidth) {
      const s = String(text);
      if (s.trim() && ctx.globalAlpha > 0.05) {
        const b = toSketch(textBox(ctx, s, x, y, maxWidth));
        boxes.push([...b, gapFor(b[3] - b[1])]);
      }
      return maxWidth === undefined ? fill.call(ctx, text, x, y) : fill.call(ctx, text, x, y, maxWidth);
    };
    // small filled shapes count too (underlines, rules, chips); backgrounds don't
    ctx.fillRect = function (x, y, w, h) {
      const t = ctx.getTransform();
      const x0 = (t.a * x + t.e) / K, y0 = (t.d * y + t.f) / K, x1 = (t.a * (x + w) + t.e) / K, y1 = (t.d * (y + h) + t.f) / K;
      const bw = Math.abs(x1 - x0), bh = Math.abs(y1 - y0);
      if (bw > 0 && bh > 0 && bw * bh < 0.08 * W * H && ctx.globalAlpha > 0.05) boxes.push([Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1), GAP]);
      return rect.call(ctx, x, y, w, h);
    };
    // words on a reused layer, moved to where the layer is drawn
    ctx.drawImage = function (img, ...a) {
      if (img && img.texts && a.length === 2) {
        const t = ctx.getTransform();
        for (const [x0, y0, x1, y1] of img.texts) {
          const b = [(t.a * (a[0] + x0) + t.e) / K, (t.d * (a[1] + y0) + t.f) / K, (t.a * (a[0] + x1) + t.e) / K, (t.d * (a[1] + y1) + t.f) / K];
          boxes.push([...b, gapFor(b[3] - b[1])]);
        }
      }
      return image.call(ctx, img, ...a);
    };
    const st = {beat, t: beat.frames - 1, frame: beat.start + beat.frames - 1, plan};
    draw(ctx, st);
    if (extra) extra(ctx, st);
    for (const [ax, ay] of st.avoid || []) boxes.push([ax - 9, ay - 9, ax + 9, ay + 9, MIN_GAP]);
    return {boxes};
  });
}

// ---- 2. the person's outline, and the biggest clear space -------------------------------------------------

// The cutout's outline as a grid of filled cells (fractions of its box), so a word beside the head but clear of
// it doesn't count. `tilt` turns the outline about the box's bottom middle (degrees), the way the sticker rests;
// a turned cell may poke a little outside the 0-1 box. `bottom` is the outline's lowest point.
export const shapeOf = (key, img, tilt = 0) => once(`shape-${key}-${tilt}`, () => {
  const cols = 30;
  const rows = Math.max(1, Math.round((cols * img.naturalHeight) / img.naturalWidth));
  const c = makeCanvas(cols, rows);
  const d = ctx2d(c);
  d.drawImage(img, 0, 0, cols, rows);
  const px = d.getImageData(0, 0, cols, rows).data;
  const aspect = img.naturalWidth / img.naturalHeight;
  const a = (tilt * Math.PI) / 180, cos = Math.cos(a), sin = Math.sin(a);
  // a point of the box (fractions) turned about the bottom middle; the box is 1 wide and 1/aspect tall here
  const turn = (u, v) => {
    const x = u - 0.5, y = (v - 1) / aspect;
    return [x * cos - y * sin + 0.5, (x * sin + y * cos) * aspect + 1];
  };
  const cells = [];
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      if (px[(y * cols + x) * 4 + 3] <= 60) continue;
      const pts = [[x, y], [x + 1, y], [x, y + 1], [x + 1, y + 1]].map(([u, v]) => turn(u / cols, v / rows));
      const us = pts.map((p) => p[0]), vs = pts.map((p) => p[1]);
      cells.push([Math.min(...us), Math.min(...vs), Math.max(...us), Math.max(...vs)]);
    }
  }
  const bottom = Math.max(1, ...cells.map((q) => q[3]));
  return {cells, aspect, bottom};
});

// does the outline come closer to any box than that box's gap (or `pad`, for a box without one)? `edge` is drawn
// around the outline (a sticker's paper), so it adds to every gap.
export function clash(cells, x, y, w, h, boxes, pad, edge = 0) {
  for (const [a, b, c, d] of cells) {
    const x0 = x + a * w, y0 = y + b * h, x1 = x + c * w, y1 = y + d * h;
    for (const [p, q, r, s, g] of boxes) {
      const k = (g ?? pad) + edge;
      if (x0 < r + k && x1 > p - k && y0 < s + k && y1 > q - k) return true;
    }
  }
  return false;
}

export const faceBox = (f, {x, y, w, h}) => [x + f[0] * w, y + f[1] * h, x + f[2] * w, y + f[3] * h];
const faceClear = (f, r) => {
  const [x0, y0, x1, y1] = faceBox(f, r);
  return x0 >= 6 && x1 <= L.right && y0 >= L.top && y1 <= L.captionTop - CAPTION_GAP;
};

// the middle of the longest run of good positions
function middle(xs) {
  let best = null, run = [];
  for (const [x, ok] of [...xs, [null, false]]) {
    if (ok) run.push(x);
    else {
      if (run.length && (!best || run.length >= best.length)) best = run;
      run = [];
    }
  }
  return best ? best[Math.floor(best.length / 2)] : null;
}

// Standing low in the frame: the chin just above the captions, the photo's bottom fading out behind them. The
// words are checked against the person at their biggest (BREATHE, grown upward from the bottom middle).
export function fitStanding(shape, face, boxes, grow = BREATHE) {
  for (let h = 0.62 * H; h >= 0.2 * H; h -= 5) {
    let w = h * shape.aspect;
    if (w > 0.8 * W) { w = 0.8 * W; h = w / shape.aspect; }
    const y = L.captionTop - CAPTION_GAP - face[3] * h;
    if (y + h < L.captionTop + 30) continue;
    const xs = [];
    for (let x = -0.22 * w; x <= W - 0.78 * w; x += 3) {
      const big = {x: x - ((grow - 1) * w) / 2, y: y - (grow - 1) * h, w: w * grow, h: h * grow};
      xs.push([x, faceClear(face, {x, y, w, h}) && faceClear(face, big) && !clash(shape.cells, big.x, big.y, big.w, big.h, boxes, GAP)]);
    }
    const x = middle(xs);
    if (x !== null) return {x, y, w, h};
  }
  return null;
}

// Anywhere above the captions and inside the safe area, as big as fits with the gaps all round, counted from the
// outside of `edge` (the sticker's paper) and even at the top of its bounce (POP, grown from its bottom middle);
// then dropped as low as it still fits, so it sits by the words it belongs to instead of floating.
export function fitFree(shape, boxes, {pad = GAP, maxW = 0.62 * W, minW = 0.2 * W, grow = POP, edge = 0} = {}) {
  const bottom = L.captionTop - CAPTION_GAP - edge;
  const hits = (x, y, w, h) => clash(shape.cells, x - ((grow - 1) * w) / 2, y - (grow - 1) * h, w * grow, h * grow, boxes, pad, edge);
  for (let w = maxW; w >= minW; w -= 4) {
    const h = w / shape.aspect;
    const low = bottom - (shape.bottom - 1) * h;   // the lowest the box may reach, so the tilted outline's foot stays clear
    let found = null;
    for (let y = L.top + 4 + edge + (grow - 1) * h; y + h <= low && !found; y += 3) {
      const xs = [];
      for (let x = L.left - 6; x + w <= L.right + 4; x += 3) xs.push([x, !hits(x, y, w, h)]);
      const x = middle(xs);
      if (x !== null) found = {x, y, w, h};
    }
    if (found) {
      let {x, y} = found;
      while (y + h + 3 <= low && !hits(x, y + 3, w, h)) y += 3;
      return {x, y, w, h};
    }
  }
  return null;
}
