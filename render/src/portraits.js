// Portraits (decision 7): an approved photo of a public figure. Two ways to draw it:
//   - a cutout (Jan's pick, Nov 27): the person cut out of the photo (scripts/cut_portraits.py), as a sticker on
//     the hook and headlines and standing low in the frame on quotes, placed by placement.js so it never touches a
//     word (drawCutout, below);
//   - the older dotted badge, for a photo with no cutout: redrawn as ink dots in a paper disc (portraitBadge).
// Photos and their licenses are listed in stringer_private/video_assets/people/people.json (people.py); render.mjs
// copies the ones a plan uses next to the bundle and sets beat.broll.portrait.src (and .cutoutSrc). The credit goes
// on the sources card (plan.py).
import {K, PAL, clamp01, ctx2d, easeOut, makeCanvas, once, rng} from './style.js';
import {BORDER, BREATHE, TILT, faceBox, fitFree, fitStanding, shapeOf} from './placement.js';

// Loaded images by URL. Shot (Video.jsx) waits for loadPortrait() before its first frame, so drawing can
// read them without waiting.
const loaded = new Map();
const pending = new Map();

export function loadPortrait(url) {
  if (!pending.has(url)) {
    pending.set(url, new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => { loaded.set(url, img); resolve(img); };
      img.onerror = () => reject(new Error(`portrait failed to load: ${url}`));
      img.src = url;
    }));
  }
  return pending.get(url);
}

export const portraitImage = (url) => loaded.get(url) || null;

// The square of the photo the badge shows: as wide as the photo allows, centred across and placed near the
// top (in a head-and-shoulders photo the face sits in the upper half).
function crop(img) {
  const w = img.naturalWidth, h = img.naturalHeight;
  const side = Math.min(w, h);
  const sx = (w - side) / 2;
  const sy = h > w ? Math.min(h - side, h * 0.06) : 0;
  return [sx, sy, side, side];
}

// The badge, made once per photo and size: paper disc, halftone dots, dotted ring.
export const portraitBadge = (url, img, r) => once(`portrait-${url}-${r}`, () => {
  const px = Math.ceil(2 * r * K) + 4;
  const c = makeCanvas(px, px);
  const d = ctx2d(c);
  // read the photo at one sample per dot
  const n = Math.round(r * 1.5);
  const sample = makeCanvas(n, n);
  const sd = ctx2d(sample);
  sd.drawImage(img, ...crop(img), 0, 0, n, n);
  const pix = sd.getImageData(0, 0, n, n).data;
  // stretch the photo's own range so a pale or dark photo still uses every dot size
  const lum = [];
  for (let i = 0; i < pix.length; i += 4) lum.push((0.2126 * pix[i] + 0.7152 * pix[i + 1] + 0.0722 * pix[i + 2]) / 255);
  const sorted = [...lum].sort((a, b) => a - b);
  const lo = sorted[Math.floor(sorted.length * 0.04)], hi = sorted[Math.floor(sorted.length * 0.96)];
  const span = Math.max(0.08, hi - lo);

  d.translate(px / 2, px / 2);
  d.scale(K, K);
  d.fillStyle = PAL.paper;
  d.beginPath(); d.arc(0, 0, r, 0, 6.283); d.fill();
  const cell = (2 * r) / n;
  const rnd = rng(17);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const cx = -r + (x + 0.5) * cell, cy = -r + (y + 0.5) * cell;
      if (Math.hypot(cx, cy) > r - 2.6) continue;
      const dark = 1 - Math.min(1, Math.max(0, (lum[y * n + x] - lo) / span));
      if (dark < 0.06) continue;
      d.fillStyle = dark > 0.55 ? PAL.ink : dark > 0.28 ? PAL.cobalt : 'rgba(53,82,190,0.55)';
      d.beginPath();
      d.arc(cx + (rnd() - 0.5) * 0.25 * cell, cy + (rnd() - 0.5) * 0.25 * cell, 0.5 * cell * Math.sqrt(dark) * 1.05, 0, 6.283);
      d.fill();
    }
  }
  for (let a = 0; a < 6.283; a += 0.11) {
    d.fillStyle = 'rgba(26,42,134,0.55)';
    d.beginPath(); d.arc(Math.cos(a) * (r - 1.2), Math.sin(a) * (r - 1.2), 0.6, 0, 6.283); d.fill();
  }
  return c;
});

// ---- Cutout portraits (Jan's pick, Nov 27): a sticker on the hook and headlines, the person standing on quotes ----
// The cutout (scripts/cut_portraits.py) is the person cut out of the approved photo; beat.broll.portrait.face says
// where the face is in it. Where it goes comes from placement.js; nothing is drawn if no clear space is found.

export const STANDING = new Set(['quote']);

// a little print grain on the photo so it sits in the paper
function grain(d, w, h, seed, amount) {
  const img = d.getImageData(0, 0, w, h);
  const p = img.data;
  const r = rng(seed);
  for (let y = 0; y < h; y += 2) {
    for (let x = 0; x < w; x += 2) {
      const n = (r() - 0.5) * amount;
      for (let oy = 0; oy < 2 && y + oy < h; oy++) {
        for (let ox = 0; ox < 2 && x + ox < w; ox++) {
          const i = ((y + oy) * w + x + ox) * 4;
          p[i] += n; p[i + 1] += n; p[i + 2] += n;
        }
      }
    }
  }
  d.putImageData(img, 0, 0);
}

const grained = (url, img, wpx, hpx) => once(`cut-grain-${url}-${wpx}`, () => {
  const c = makeCanvas(wpx, hpx);
  const d = ctx2d(c);
  d.drawImage(img, 0, 0, wpx, hpx);
  grain(d, wpx, hpx, 5, 14);
  return c;
});

// below the chin, the photo's cut-off sides and bottom fade out, so its hard edges never show
function fadeEdges(c, chin) {
  const d = ctx2d(c);
  d.globalCompositeOperation = 'destination-out';
  const side = c.width * 0.16, y = c.height * chin;
  for (const [x0, x1] of [[0, side], [c.width, c.width - side]]) {
    const g = d.createLinearGradient(x0, 0, x1, 0);
    g.addColorStop(0, 'rgba(0,0,0,1)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    d.fillStyle = g;
    d.globalAlpha = 0.5;
    d.fillRect(Math.min(x0, x1), y, side, c.height * 0.06);
    d.globalAlpha = 1;
    d.fillRect(Math.min(x0, x1), y + c.height * 0.06, side, c.height);
  }
  d.globalCompositeOperation = 'destination-in';
  const g = d.createLinearGradient(0, c.height * 0.72, 0, c.height);
  g.addColorStop(0, 'rgba(0,0,0,1)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  d.fillStyle = g;
  d.fillRect(0, 0, c.width, c.height);
  d.globalCompositeOperation = 'source-over';
  return c;
}

const standingImage = (url, img, wpx, hpx, chin) => once(`cut-stand-${url}-${wpx}`, () => {
  const c = makeCanvas(wpx, hpx);
  ctx2d(c).drawImage(grained(url, img, wpx, hpx), 0, 0);
  return fadeEdges(c, chin);
});

const silhouette = (key, img, wpx, hpx, color) => once(`cut-sil-${key}-${wpx}-${color}`, () => {
  const c = makeCanvas(wpx, hpx);
  const d = ctx2d(c);
  d.drawImage(img, 0, 0, wpx, hpx);
  d.globalCompositeOperation = 'source-in';
  d.fillStyle = color;
  d.fillRect(0, 0, wpx, hpx);
  d.globalCompositeOperation = 'source-over';
  return c;
});

// a sticker: a paper border around the cut line
const stickerImage = (url, img, wpx, hpx, border) => once(`cut-sticker-${url}-${wpx}`, () => {
  const c = makeCanvas(wpx + 2 * border, hpx + 2 * border);
  const d = ctx2d(c);
  const sil = silhouette(url, img, wpx, hpx, PAL.paper);
  for (let a = 0; a < 6.283; a += 0.2) d.drawImage(sil, border + Math.cos(a) * border, border + Math.sin(a) * border);
  d.drawImage(grained(url, img, wpx, hpx), border, border);
  return c;
});

// a small bounce: at most about 4% past its size (placement.POP leaves room for it)
const backOut = (p) => { const c1 = 1.0, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); };

// Where the cutout goes on this beat (once per beat), or null.
export function cutoutSpot(s, url, img) {
  const {beat} = s;
  const face = beat.broll.portrait.face;
  const standing = STANDING.has(beat.shot);
  return once(`cut-spot-${s.plan?.story?.id}-${beat.n}-${beat.start}`, () => {
    const r = standing ? fitStanding(shapeOf(url, img), face, s.finished.boxes) : fitFree(shapeOf(url, img, TILT), s.finished.boxes, {edge: BORDER});
    return r && {...r, standing, face: faceBox(face, r)};
  });
}

// Draws the cutout portrait. Returns where it went (sketch units, for the layout check), or null if it didn't fit.
export function drawCutout(ctx, s, url, img) {
  const {beat, t} = s;
  const f = cutoutSpot(s, url, img);
  if (!f) return null;
  const face = beat.broll.portrait.face;
  const wpx = Math.round(f.w * K), hpx = Math.round(f.h * K);
  if (f.standing) {
    // fades in where it will stand, rising only a little, so the face never passes behind a caption
    const p = easeOut((t - 5) / 16);
    const breathe = 1 + (BREATHE - 1) * clamp01(t / 240);
    const w = f.w * breathe, h = f.h * breathe;
    ctx.globalAlpha = clamp01(p * 1.4);
    ctx.drawImage(standingImage(url, img, wpx, hpx, face[3]), f.x - (w - f.w) / 2, f.y - (h - f.h) + (1 - p) * 0.07 * f.h, w, h);
    ctx.globalAlpha = 1;
  } else {
    // pops in with a small bounce and settles at a slight tilt
    const p = clamp01((t - 6) / 13);
    if (p <= 0) return f;
    const sc = backOut(p);
    const rot = ((TILT - 6 + 6 * easeOut(p)) * Math.PI) / 180;
    const border = Math.round(BORDER * K);
    const im = stickerImage(url, img, wpx, hpx, border);
    const bw = im.width / K, bh = im.height / K;
    ctx.save();
    ctx.translate(f.x + f.w / 2, f.y + f.h);
    ctx.rotate(rot);
    ctx.scale(sc, sc);
    ctx.globalAlpha = 0.22 * clamp01(p * 2);
    ctx.drawImage(silhouette(`${url}-shadow`, im, im.width, im.height, PAL.ink), -bw / 2 + 3, -bh + border / K + 4, bw, bh);
    ctx.globalAlpha = clamp01(p * 3);
    ctx.drawImage(im, -bw / 2, -bh + border / K, bw, bh);
    ctx.restore();
  }
  return f;
}
