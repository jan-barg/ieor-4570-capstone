// The box's worker runtime (custom animation, Nov 28). It runs inside a Web Worker, after the kit files and before
// the model's code, and is the only thing in the worker that can talk to the page. It:
//   1. keeps private copies of what it needs (postMessage, a clock, a canvas maker), out of reach of the model's code;
//   2. builds the kit `k` on a canvas of its own (the paper grain is made here, before anything is locked);
//   3. locks the worker: every way out (network, storage, timers, messages, other workers, decoders, raw pixels,
//      text) is deleted from the global scope and its prototypes, Math.random becomes a seeded random;
//   4. takes the model's draw function (once), then draws every frame when the page asks, timing each one, and
//      sends back a JPEG of each frame with a few measurements: magenta left (blank), change from the last frame
//      (still), how long the draw took.
// The page (box.mjs builds it) never runs the model's code itself. Text calls are made harmless no-ops (counted):
// the pictures may hold no words, and that is now a property of the box, not only a rule in the guide.
/* global makeKit, BOX_SCALE */
(function runtime() {
  'use strict';
  const G = self;
  const send = G.postMessage.bind(G);
  const listen = G.addEventListener.bind(G);
  const now = G.performance.now.bind(G.performance);
  const Canvas = G.OffscreenCanvas;
  const W = 900, H = 600;                         // the window the model draws in (its own units)
  let job = null;                                 // the page's one 'run' message
  let drawFn = null, given = false;
  const counts = {text: 0, pixels: 0};

  // ---- the canvas and the kit, made before the lock ----
  // S: the device scale. The model draws in 900 x 600 units; the frames come out S times larger (1080 x 720 at
  // 1.2), so they stay sharp on the 1080-wide video. Every transform the model or the kit sets is scaled by S.
  let S = 1, scene = null, ctx = null, k = null;
  function setup(scale) {
    S = scale;
    scene = new Canvas(Math.round(W * S), Math.round(H * S));
    ctx = scene.getContext('2d', {willReadFrequently: true});
    const P = Object.getPrototypeOf(ctx);
    const setT = P.setTransform, getT = P.getTransform;
    ctx.setTransform = function (a, b, c, d, e, f) {
      if (a && typeof a === 'object') return setT.call(this, a.a * S, a.b * S, a.c * S, a.d * S, a.e * S, a.f * S);
      return setT.call(this, a * S, b * S, c * S, d * S, e * S, f * S);
    };
    ctx.resetTransform = function () { return setT.call(this, S, 0, 0, S, 0, 0); };
    ctx.getTransform = function () {
      const m = getT.call(this);
      return new DOMMatrix([m.a / S, m.b / S, m.c / S, m.d / S, m.e / S, m.f / S]);
    };
    ctx.resetTransform();
    k = makeKit(ctx, W, H, {canvas: (w, h) => new Canvas(w, h)});
  }

  // ---- the lock ----
  const GONE = ['fetch', 'XMLHttpRequest', 'WebSocket', 'WebSocketStream', 'WebTransport', 'EventSource', 'importScripts',
    'postMessage', 'close', 'Worker', 'SharedWorker', 'BroadcastChannel', 'MessageChannel', 'MessagePort', 'indexedDB',
    'IDBFactory', 'caches', 'CacheStorage', 'navigator', 'location', 'setTimeout', 'setInterval', 'clearTimeout',
    'clearInterval', 'queueMicrotask', 'requestAnimationFrame', 'cancelAnimationFrame', 'Request', 'Response', 'Headers',
    'FileReader', 'FileReaderSync', 'WebAssembly', 'createImageBitmap', 'Blob', 'File', 'atob', 'btoa', 'OffscreenCanvas',
    'ImageData', 'ImageDecoder', 'VideoDecoder', 'VideoEncoder', 'VideoFrame', 'AudioDecoder', 'AudioEncoder',
    'EncodedVideoChunk', 'Notification', 'performance', 'Date', 'FontFace', 'fonts', 'StorageManager', 'LockManager',
    'reportError', 'addEventListener', 'removeEventListener', 'dispatchEvent', 'onmessage', 'onerror'];

  function remove(obj, name) {
    for (let o = obj; o && o !== Object.prototype; o = Object.getPrototypeOf(o)) {
      try { delete o[name]; } catch (e) { /* not configurable: covered below */ }
    }
    if (name in obj) {
      try { Object.defineProperty(obj, name, {value: undefined, writable: false, configurable: false}); } catch (e) { /* stays */ }
    }
  }

  function lock() {
    for (const name of GONE) remove(G, name);
    const P = Object.getPrototypeOf(ctx);
    // no words in the pictures, and no raw pixels (a picture smuggled in as numbers): both become counted no-ops
    const noop = (what) => function () { counts[what]++; };
    for (const name of ['fillText', 'strokeText']) Object.defineProperty(P, name, {value: noop('text'), writable: false, configurable: false});
    Object.defineProperty(P, 'putImageData', {value: noop('pixels'), writable: false, configurable: false});
    Object.defineProperty(P, 'measureText', {value: () => ({width: 0}), writable: false, configurable: false});
    if (G.URL) { remove(G.URL, 'createObjectURL'); remove(G.URL, 'revokeObjectURL'); }
    // a seeded random, so every frame is reproducible (the guide asks for k.rng; this covers a slip)
    let s = 1234567;
    Object.defineProperty(Math, 'random', {value: () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; },
      writable: false, configurable: false});
  }

  // The model's draw function, given once by the wrapper around its code.
  Object.defineProperty(G, '__setDraw', {
    value: (fn) => { if (!given) { given = true; drawFn = typeof fn === 'function' ? fn : null; } },
    writable: false, configurable: false,
  });

  // ---- drawing the frames ----
  const MAGENTA = '#ff00ff';
  function sample(data, step) {                     // every step-th pixel's red, green and blue, as numbers
    const out = [];
    for (let i = 0; i < data.length; i += 4 * step) out.push(data[i], data[i + 1], data[i + 2]);
    return out;
  }

  async function run(j) {
    const N = j.frames, cues = Object.freeze(Object.assign({}, j.cues || {}));
    let last = null;
    for (let f = 0; f < N; f++) {
      const p = N > 1 ? f / (N - 1) : 0;
      ctx.save();
      ctx.resetTransform();
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = MAGENTA;
      ctx.fillRect(0, 0, W, H);
      ctx.restore();
      ctx.save();
      ctx.resetTransform();
      let error = null;
      const t0 = now();
      try { drawFn(k, p, cues); } catch (e) { error = String((e && e.message) || e).slice(0, 200); }
      ctx.restore();
      // an offscreen canvas only records the calls; reading one pixel makes it draw them, so the time is real
      ctx.getImageData(0, 0, 1, 1);
      const ms = now() - t0;
      // blank: most of the window still magenta; still: almost no change since the last frame
      const px = sample(ctx.getImageData(0, 0, scene.width, scene.height).data, 97);
      let magenta = 0, diff = 0;
      for (let i = 0; i < px.length; i += 3) {
        if (px[i] > 250 && px[i + 1] < 5 && px[i + 2] > 250) magenta++;
        if (last) diff += Math.abs(px[i] - last[i]) + Math.abs(px[i + 1] - last[i + 1]) + Math.abs(px[i + 2] - last[i + 2]);
      }
      const n = px.length / 3;
      const blob = await scene.convertToBlob({type: 'image/jpeg', quality: j.quality || 0.9});
      send({type: 'frame', i: f, ms: +ms.toFixed(2), error, magenta: +(magenta / n).toFixed(4),
        change: last ? +(diff / (n * 3 * 255)).toFixed(5) : null, blob});
      last = px;
      if (j.limitMs && f >= 20 && ms > j.limitMs * 12) {          // hopeless: stop early, the page reports why
        send({type: 'done', stopped: 'too slow', counts});
        return;
      }
    }
    send({type: 'done', counts});
  }

  // Set up and lock now, while the worker script loads: the model's code comes after this file in the same
  // script, so not even its top-level statements run before the lock. BOX_SCALE comes from box.mjs.
  try { setup(BOX_SCALE); } catch (err) { send({type: 'fatal', error: 'kit: ' + String(err && err.message)}); }
  lock();

  listen('message', (e) => {
    const m = e.data || {};
    if (m.cmd !== 'run' || job) return;
    job = m;
    if (!k) return;                                   // the kit failed: already reported
    if (!drawFn) { send({type: 'fatal', error: given ? 'the code has no draw function' : 'the code never ran'}); return; }
    run(m).catch((err) => send({type: 'fatal', error: String(err && err.message)}));
  });
})();
