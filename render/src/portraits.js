// Portraits (decision 7): an approved photo of a public figure, redrawn as ink dots in a paper disc, the same
// badge as the props. The photo never appears as it is: each dot's size follows how dark the photo is there
// (a halftone), so it reads as a drawing in the video's own style. Photos and their licenses are listed in
// stringer_private/video_assets/people/people.json (people.py); render.mjs copies the ones a plan uses next
// to the bundle and sets beat.broll.portrait.src. The credit goes on the sources card (plan.py).
import {K, PAL, ctx2d, makeCanvas, once, rng} from './style.js';

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
