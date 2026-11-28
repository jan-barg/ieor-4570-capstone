// The custom animation's window (stringer/animation/, off by default): a beat whose plan carries `anim` plays
// the frames the drawing model's code made in the locked box (render/anim/box.mjs), one JPEG per video frame,
// in a window under the beat's words. The shot draws its words compactly at the top (s.compact) and says how
// low they reach (s.textEnd); the window takes the room below, down to just above the "Illustration" tag.
//
// Two looks (plan beat.anim.frame, chosen with STRINGER_ANIMATION_FRAME):
//   card   a paper-edged card, tilted a hair, with a soft shadow: a cutout laid on the page (the default; Jan's pick, Nov 28)
//   plate  edge to edge, no border, a vermilion rule on top: the scene as a band across the video
// Both get the same gentle push-in over the beat (round 6: a scene held still after its last cue looked stuck).
import {staticFile} from 'remotion';
import {K, L, PAL, clamp01, easeInOut, easeOut} from './style.js';
import {sourceChip} from './cards.js';

export const WIN = {top: 190, bottom: L.bottom - 6, gap: 10, minH: 120, aspect: 1.5};   // clear of the "Illustration" tag below
const PUSH = 0.045;            // how far the picture pushes in over the beat (4.5%)

// The frame image for one video frame of the beat (loaded once per tab; Remotion renders frames in order per tab).
const cache = new Map();
export function animFrameSrc(beat, t) {
  const a = beat.anim;
  const i = Math.max(0, Math.min(a.frames - 1, t));
  return staticFile(`${a.src}/f${String(i).padStart(4, '0')}.jpg`);
}
export function loadAnimFrame(src) {
  if (!cache.has(src)) {
    cache.set(src, new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);       // a missing frame leaves the window empty, never a stalled render
      img.src = src;
    }));
    if (cache.size > 90) cache.delete(cache.keys().next().value);
  }
  return cache.get(src);
}

// Where the window goes, in sketch units: below the shot's words, at least minH tall, 3:2 (the card) or full width.
export function windowBox(s) {
  const style = s.beat.anim?.frame === 'plate' ? 'plate' : 'card';
  const top = Math.max(WIN.top, (s.textEnd || 0) + WIN.gap);
  const h = Math.max(WIN.minH, WIN.bottom - top);
  if (style === 'plate') return {style, x: 0, y: WIN.bottom - h, w: 324, h};
  const w = Math.min(L.right - L.left, h * WIN.aspect);
  const hh = w / WIN.aspect;
  return {style, x: (L.left + L.right) / 2 - w / 2, y: WIN.bottom - hh, w, h: hh};
}

// Draws the window (after the shot, before the b-roll layer's "Illustration" tag).
export function drawAnim(ctx, s, img) {
  const {beat, t} = s;
  const b = windowBox(s);
  const enter = easeOut(clamp01(t / 9));
  const z = 1 + PUSH * easeInOut(t / Math.max(1, beat.frames));
  ctx.save();
  ctx.scale(K, K);
  ctx.globalAlpha = enter;
  ctx.translate(0, (1 - enter) * 10);
  if (b.style === 'card') {
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
    ctx.translate(cx, cy);
    ctx.rotate(-0.013);
    ctx.translate(-cx, -cy);
    const e = 3.5;               // the paper edge
    ctx.fillStyle = 'rgba(26,42,134,0.16)';
    ctx.beginPath(); ctx.roundRect(b.x - e + 3, b.y - e + 4, b.w + 2 * e, b.h + 2 * e, 2.5); ctx.fill();
    ctx.fillStyle = '#FBF8EF';
    ctx.beginPath(); ctx.roundRect(b.x - e, b.y - e, b.w + 2 * e, b.h + 2 * e, 2.5); ctx.fill();
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(b.x, b.y, b.w, b.h);
  ctx.clip();
  if (img) {
    // the frame is 3:2; the card shows all of it, the plate a band across its middle; both push in slowly
    const sw = b.w * z, sh = (b.w / WIN.aspect) * z;
    ctx.drawImage(img, b.x + (b.w - sw) / 2, b.y + (b.h - sh) / 2, sw, sh);
  } else {
    ctx.fillStyle = PAL.paperDeep;
    ctx.fillRect(b.x, b.y, b.w, b.h);
  }
  ctx.restore();
  if (b.style === 'plate') {
    ctx.fillStyle = PAL.vermilion;
    ctx.fillRect(0, b.y - 3, 324 * enter, 3);
  }
  ctx.restore();
  // the "Source:" label sits over the picture's lower-left corner, as on a map
  ctx.save();
  ctx.scale(K, K);
  sourceChip(ctx, beat.label, t);
  ctx.restore();
  s.window = b;
}
