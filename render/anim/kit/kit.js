// The drawing kit for the custom animation (tested Nov 27 in rounds 3-6, moved into the repo Nov 28). The model's
// draw(k, p, cues) gets this `k` and nothing else. It runs inside the box's worker (render/anim/runtime.js), so it
// never touches a page: canvases come from tools.canvas. Palette and props are copied from render/src (style.js,
// props.js) so a custom scene looks like Stringer.
// The other kit files (kit_fx.js, kit_scene*.js) push functions here; each gets the kit and adds a namespace.
var KIT_EXT = [];
function makeKit(ctx, W, H, tools) {
  const PAL = {
    paper: '#F3EEE1', paperDeep: '#E9E2CF', ink: '#1A2A86', cobalt: '#3552BE', vermilion: '#E8622C',
    mustard: '#E0A12A', sea: '#1E3191', land: '#2A6E3A', sky: '#A8C9EA', smoke: '#8A8FA3', white: '#FFFFFF',
  };
  const INK = PAL.ink, COB = PAL.cobalt, MUS = PAL.mustard, VER = PAL.vermilion, PAP = PAL.paper;
  const rr = (d, x, y, w, h, r, color) => { d.fillStyle = color; d.beginPath(); d.roundRect(x, y, w, h, r); d.fill(); };
  const poly = (d, pts, color) => { d.fillStyle = color; d.beginPath(); pts.forEach(([x, y], i) => (i ? d.lineTo(x, y) : d.moveTo(x, y))); d.closePath(); d.fill(); };
  const circ = (d, x, y, r, color) => { d.fillStyle = color; d.beginPath(); d.arc(x, y, r, 0, 6.283); d.fill(); };
  const DRAW = {
    'ballot box': (d) => { rr(d, -24, -34, 40, 34, 2, '#FFFFFF'); d.strokeStyle = INK; d.lineWidth = 2; d.strokeRect(-24, -34, 40, 34); d.lineWidth = 3; d.beginPath(); d.moveTo(-14, -24); d.lineTo(0, -10); d.moveTo(0, -24); d.lineTo(-14, -10); d.stroke(); rr(d, -36, -6, 72, 44, 5, MUS); rr(d, -26, -9, 52, 7, 3, INK); rr(d, -36, 30, 72, 8, 3, '#C9862A'); },
    bridge: (d) => { d.strokeStyle = VER; d.lineWidth = 5; d.beginPath(); d.moveTo(-44, 6); d.quadraticCurveTo(0, -56, 44, 6); d.stroke(); d.lineWidth = 2; for (let x = -30; x <= 30; x += 10) { const y = -50 * (1 - (x / 44) ** 2) * 0.5 + 6; d.beginPath(); d.moveTo(x, y); d.lineTo(x, 6); d.stroke(); } rr(d, -48, 4, 96, 8, 2, INK); rr(d, -40, 12, 8, 22, 1, INK); rr(d, 32, 12, 8, 22, 1, INK); d.strokeStyle = COB; d.lineWidth = 2.5; for (const y of [26, 34]) { d.beginPath(); d.moveTo(-30, y); d.quadraticCurveTo(-15, y - 4, 0, y); d.quadraticCurveTo(15, y + 4, 30, y); d.stroke(); } },
    train: (d) => { rr(d, -30, -40, 60, 66, 14, COB); rr(d, -22, -32, 44, 24, 5, PAP); rr(d, -30, -2, 60, 6, 0, INK); circ(d, -17, 14, 5, MUS); circ(d, 17, 14, 5, MUS); rr(d, -10, 10, 20, 8, 2, INK); d.strokeStyle = INK; d.lineWidth = 3; d.beginPath(); d.moveTo(-22, 26); d.lineTo(-34, 42); d.moveTo(22, 26); d.lineTo(34, 42); d.stroke(); d.lineWidth = 2.5; for (const y of [34, 42]) { d.beginPath(); d.moveTo(-36 + (42 - y) * 0.2, y); d.lineTo(36 - (42 - y) * 0.2, y); d.stroke(); } },
    document: (d) => { poly(d, [[-28, -40], [16, -40], [30, -26], [30, 40], [-28, 40]], PAP); poly(d, [[16, -40], [30, -26], [16, -26]], '#E9E2CF'); d.strokeStyle = INK; d.lineWidth = 2; d.beginPath(); d.moveTo(-28, -40); d.lineTo(16, -40); d.lineTo(30, -26); d.lineTo(30, 40); d.lineTo(-28, 40); d.closePath(); d.stroke(); for (let y = -22; y <= 20; y += 8) rr(d, -20, y, y === 20 ? 22 : 40, 2.5, 1, 'rgba(26,42,134,0.45)'); circ(d, 16, 28, 9, VER); },
    plane: (d) => { rr(d, -6, -44, 12, 88, 6, INK); poly(d, [[-46, 4], [-4, -14], [4, -14], [46, 4], [46, 10], [4, 2], [-4, 2], [-46, 10]], COB); poly(d, [[-18, 38], [-3, 30], [3, 30], [18, 38], [18, 42], [-18, 42]], COB); circ(d, 0, -38, 4, PAP); },
    drone: (d) => { rr(d, -40, -5, 80, 10, 5, MUS); rr(d, -6, -40, 12, 80, 6, MUS); rr(d, -40, -16, 10, 32, 5, MUS); circ(d, 0, 0, 5, INK); },
    flag: (d) => { rr(d, -34, -44, 5, 90, 2, INK); circ(d, -31.5, -45, 4, INK); d.fillStyle = MUS; d.beginPath(); d.moveTo(-29, -40); d.bezierCurveTo(-10, -50, 10, -30, 36, -40); d.lineTo(36, 2); d.bezierCurveTo(10, 12, -10, -8, -29, 2); d.closePath(); d.fill(); },
    missile: (d) => { d.save(); d.rotate(-0.75); rr(d, -40, -7, 70, 14, 3, COB); poly(d, [[30, -7], [46, 0], [30, 7]], VER); poly(d, [[-40, -7], [-48, -18], [-30, -7]], INK); poly(d, [[-40, 7], [-48, 18], [-30, 7]], INK); rr(d, -6, -9, 4, 18, 1, PAP); d.restore(); },
    'computer chip': (d) => { for (let k = -3; k <= 3; k++) { rr(d, k * 9 - 2, -44, 4, 10, 1, MUS); rr(d, k * 9 - 2, 34, 4, 10, 1, MUS); rr(d, -44, k * 9 - 2, 10, 4, 1, MUS); rr(d, 34, k * 9 - 2, 10, 4, 1, MUS); } rr(d, -34, -34, 68, 68, 6, INK); rr(d, -18, -18, 36, 36, 3, COB); circ(d, -26, -26, 3, PAP); },
    'cargo ship': (d) => { const cols = [VER, MUS, COB, MUS, VER, COB]; cols.forEach((c, i) => rr(d, -40 + (i % 3) * 18, -12 - Math.floor(i / 3) * 12, 16, 10, 1, c)); rr(d, 18, -34, 14, 30, 2, PAP); rr(d, 21, -30, 8, 4, 1, INK); poly(d, [[-48, -2], [46, -2], [38, 22], [-42, 22]], INK); rr(d, -44, 12, 86, 4, 1, VER); d.strokeStyle = COB; d.lineWidth = 2.5; d.beginPath(); d.moveTo(-50, 32); d.quadraticCurveTo(-25, 26, 0, 32); d.quadraticCurveTo(25, 38, 50, 32); d.stroke(); },
  };
  const clamp01 = (t) => Math.max(0, Math.min(1, t));
  const rng = (seed) => {
    let s = Math.abs(Math.floor(seed * 9973 + 17)) % 2147483647;
    if (s <= 0) s += 2147483646;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  };
  // paper grain, made once (before the box locks raw pixels) and laid over the window
  let grainCanvas = null;
  const grain = () => {
    if (grainCanvas) return grainCanvas;
    grainCanvas = tools.canvas(W, H);
    const g = grainCanvas.getContext('2d');
    const img = g.createImageData(W, H);
    const r = rng(7);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = r();
      if (v < 0.12) { img.data[i] = 243; img.data[i + 1] = 238; img.data[i + 2] = 225; img.data[i + 3] = 90; }
      else if (v > 0.94) { img.data[i] = 26; img.data[i + 1] = 42; img.data[i + 2] = 134; img.data[i + 3] = 40; }
    }
    g.putImageData(img, 0, 0);
    return grainCanvas;
  };
  const k = {
    ctx, W, H, pal: Object.freeze(PAL),
    props: Object.freeze(Object.keys(DRAW)),
    clamp01,
    lerp: (a, b, t) => a + (b - a) * t,
    seg: (p, a, b) => clamp01((p - a) / Math.max(1e-6, b - a)),
    ease: Object.freeze({
      in: (t) => t * t * t,
      out: (t) => 1 - (1 - t) ** 3,
      inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
    }),
    rng,
    prop: (name, x, y, size, o = {}) => {
      const f = DRAW[name];
      if (!f) return false;
      ctx.save();
      ctx.translate(x, y);
      if (o.rotate) ctx.rotate(o.rotate);
      const s = size / 100;
      ctx.scale(o.flip ? -s : s, s);
      if (o.alpha != null) ctx.globalAlpha = o.alpha;
      f(ctx);
      ctx.restore();
      return true;
    },
    stipple: (alpha = 1) => { ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = alpha; ctx.drawImage(grain(), 0, 0); ctx.restore(); },
  };
  grain();
  for (const ext of KIT_EXT) Object.assign(k, ext(k));
  return Object.freeze(k);
}
