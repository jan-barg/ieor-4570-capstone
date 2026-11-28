// How one beat gives way to the next (stringer/video/transitions.py decides which; off by default, every change a cut).
// A beat with `enter` ({kind, frames, pre}) comes in over `frames` frames, the first `pre` of them before its first
// word (it shows its first frame until then), while the beat before it plays out and then holds its last frame
// (Video.jsx keeps both up that long). Each beat's canvas is wrapped in a div moved, faded or clipped here:
//   dissolve  the new picture fades in over the old;
//   slide     a new sheet slides in from the right over the old, which drifts left and dims a little;
//   push      both move left together, as if the camera travelled along one long sheet;
//   tear      the old sheet is torn away to the left along a ragged edge with a pale torn fringe, the new one beneath;
//   wipe      a vermilion band sweeps left to right, the new picture behind it.
// The captions are drawn above all of this, so they never move.
import React from 'react';
import {useCurrentFrame} from 'remotion';
import {PAL} from './style.js';

const clamp01 = (x) => Math.max(0, Math.min(1, x));
const easeOut = (x) => 1 - Math.pow(1 - x, 3);
const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const easeInOutQuad = (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const EASE = {dissolve: (x) => x, slide: easeOut, push: easeInOut, tear: easeInOutQuad, wipe: easeInOut};

// how far along the change is on frame k of it (0 on the frame before it, 1 on the frame after it)
const along = (k, frames) => clamp01((k + 1) / (frames + 1));

// a small seeded random, so a beat's torn edge is the same on every frame and every render
function rng(seed) {
  let a = (seed * 2654435761) >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The torn edge: x offsets (px) every STEP px down the frame, ragged with an occasional deeper nick.
const STEP = 36;
const edges = new Map();
function tornEdge(seed, h) {
  const key = `${seed}-${h}`;
  if (!edges.has(key)) {
    const r = rng(seed);
    const xs = [];
    for (let y = 0; y <= h + STEP; y += STEP) xs.push((r() - 0.5) * 26 + (r() < 0.12 ? -(10 + r() * 22) : 0));
    edges.set(key, xs);
  }
  return edges.get(key);
}

// The part of the old sheet still standing: left of an edge at x (px), leaning so the top leads.
function tornPolygon(seed, x, w, h, grow = 0) {
  const xs = tornEdge(seed, h);
  const lean = 0.16 * w;
  const pts = ['0px 0px'];
  xs.forEach((dx, i) => {
    const y = Math.min(h, i * STEP);
    pts.push(`${(x + dx + grow + lean * (0.5 - y / h)).toFixed(1)}px ${y}px`);
  });
  pts.push(`0px ${h}px`);
  return `polygon(${pts.join(', ')})`;
}

// The incoming beat: how it looks on frame k of its entrance.
function enterStyle(kind, e, w) {
  switch (kind) {
    case 'dissolve': return {opacity: e};
    case 'slide': return {transform: `translateX(${((1 - e) * w).toFixed(1)}px)`, boxShadow: '-18px 0 36px rgba(26,42,134,0.30)'};
    case 'push': return {transform: `translateX(${((1 - e) * w).toFixed(1)}px)`};
    default: return {};                                // tear and wipe: the old sheet does the moving, on top
  }
}

// The outgoing beat while the next one comes in. Returns {style, zIndex, sheet, extra}.
function exitLook(kind, e, w, h, seed) {
  switch (kind) {
    case 'slide': return {style: {transform: `translateX(${(-0.22 * e * w).toFixed(1)}px)`, filter: `brightness(${(1 - 0.12 * e).toFixed(3)})`}};
    case 'push': return {style: {transform: `translateX(${(-e * w).toFixed(1)}px)`}};
    case 'tear': {
      // the edge runs from just past the right side to just past the left (its lean is 0.16 w, its nicks under 40 px);
      // the torn-off piece is pulled a little left and up
      const reach = 0.08 * w + 40;
      const x = w + reach - e * (w + 2 * reach);
      return {
        zIndex: 2,
        style: {transform: `translate(${(-0.05 * e * w).toFixed(1)}px, ${(-0.012 * e * h).toFixed(1)}px) rotate(${(-1.6 * e).toFixed(2)}deg)`,
          filter: 'drop-shadow(10px 0 14px rgba(26,42,134,0.35))'},
        sheet: {clipPath: tornPolygon(seed, x, w, h)},
        fringe: {clipPath: tornPolygon(seed, x, w, h, 9), background: '#FBF8EF'},
      };
    }
    case 'wipe': {
      // the band's leading edge runs from the left side to past the right; the old picture stays right of its trailing edge
      const band = 0.24 * w, lean = 0.10 * w;
      const lead = -lean + e * (w + band + 2 * lean);
      const trail = lead - band;
      const poly = (x) => `polygon(${(x + lean).toFixed(1)}px 0px, ${w}px 0px, ${w}px ${h}px, ${(x - lean).toFixed(1)}px ${h}px)`;
      return {
        zIndex: 2,
        sheet: {clipPath: poly(lead)},
        band: {clipPath: `polygon(${(trail + lean).toFixed(1)}px 0px, ${(lead + lean).toFixed(1)}px 0px, ${(lead - lean).toFixed(1)}px ${h}px, ${(trail - lean).toFixed(1)}px ${h}px)`},
      };
    }
    default: return {};                                // dissolve: the new picture fades in on top
  }
}

const FILL = {position: 'absolute', left: 0, top: 0, width: '100%', height: '100%'};

// Wraps one beat's canvas. With no change at either end it gives the canvas back as it is.
// lead: how many frames before its first frame the beat is up (its own change's `pre`).
export function Moving({beat, next, lead = 0, width, height, children}) {
  const f = useCurrentFrame();                                         // from `lead` frames before the beat's first frame
  const out = lead + (beat.end - beat.start) - (next?.enter?.pre || 0);  // where the next beat's change starts
  const enter = beat.enter && f < beat.enter.frames ? beat.enter : null;
  const exit = next?.enter && f >= out ? next.enter : null;
  if (!beat.enter && !next?.enter) return children;
  let style = {}, zIndex = 1, sheet = null, fringe = null, band = null;
  if (enter) {
    style = enterStyle(enter.kind, (EASE[enter.kind] || easeOut)(along(f, enter.frames)), width);
  } else if (exit) {
    const look = exitLook(exit.kind, (EASE[exit.kind] || easeOut)(along(f - out, exit.frames)), width, height, next.n * 7919 + beat.n);
    style = look.style || {};
    zIndex = look.zIndex || 1;
    ({sheet = null, fringe = null, band = null} = look);
  }
  return (
    <div style={{...FILL, zIndex, ...style}}>
      {fringe ? <div style={{...FILL, ...fringe}} /> : null}
      <div style={{...FILL, ...(sheet || {})}}>{children}</div>
      {band ? <div style={{...FILL, background: PAL.vermilion, ...band}} /> : null}
    </div>
  );
}
