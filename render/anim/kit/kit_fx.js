// Shared effects for the custom-animation kits (Nov 27, test-only): paper-cutout shadows, smoke, flash,
// impact rings, flight paths and camera moves. Everything draws on k.ctx, in window pixels (k.W x k.H).
KIT_EXT.push(function (k) {
  const { ctx, W, H, pal, rng, clamp01, ease } = k;
  const TAU = Math.PI * 2;
  const unit = Math.min(W, H) / 600;                 // 1 in the 900 x 600 test window
  const SHADOW = 'rgba(14,22,74,0.32)';
  const SMOKE_BACK = ['#454A5E', '#53586E'];
  const SMOKE_FRONT = ['#8A8FA3', '#9DA2B4', '#B7BBC9'];

  const circle = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, Math.max(0, r), 0, TAU); ctx.fill(); };

  // Draw fn() with a crisp paper-cutout drop shadow under everything it fills or strokes.
  function cutout(fn, o = {}) {
    ctx.save();
    const lift = o.lift ?? 1;
    ctx.shadowColor = o.color || SHADOW;
    ctx.shadowOffsetX = 3 * unit * lift;
    ctx.shadowOffsetY = 5 * unit * lift;
    ctx.shadowBlur = 0;
    try { fn(ctx); } finally { ctx.restore(); }
  }

  // A column of paper smoke rising from (x, y). t 0..1 grows it; `time` (any number, e.g. p) keeps it moving
  // once grown. size = final width in px. It is dense at its base, so a target at (x, y) ends hidden.
  function smoke(x, y, t, o = {}) {
    t = clamp01(t);
    if (t <= 0) return;
    const size = o.size ?? 160;
    const n = o.puffs ?? 22;
    const r = rng(o.seed ?? 3);
    const time = o.time ?? t;
    const rise = o.rise ?? 1.0;
    const drift = o.drift ?? 0.25;
    const puffs = [];
    for (let i = 0; i < n; i++) {
      const start = r() * 0.4;
      const u = ease.out(clamp01((t - start) / (1 - start)));
      const h = r() ** 1.6;                               // 0 at the base, 1 at the top
      const spread = 0.5 + 0.7 * h;
      const jx = r() - 0.5, rad0 = 0.075 + r() * 0.07;
      if (u <= 0) continue;
      const climb = h * size * rise * u + Math.sin(time * 2.1 + i) * size * 0.012;
      puffs.push({
        x: x + jx * size * 0.62 * spread + drift * size * h * u + Math.sin(time * 1.3 + i * 2.1) * size * 0.015,
        y: y - climb,
        r: size * rad0 * (0.3 + 0.7 * u) * (1 + 0.6 * h) * (1 + 0.045 * Math.sin(time * 5 + i * 1.7)),
        i,
      });
    }
    ctx.save();
    if (o.alpha != null) ctx.globalAlpha *= o.alpha;
    cutout(() => { for (const q of puffs) { ctx.fillStyle = SMOKE_BACK[q.i % 2]; circle(q.x, q.y, q.r); } });
    for (const q of puffs) { ctx.fillStyle = SMOKE_FRONT[q.i % 3]; circle(q.x - q.r * 0.16, q.y - q.r * 0.2, q.r * 0.74); }
    ctx.restore();
  }

  // A cut-paper explosion flash at (x, y): fast bloom, then it shrinks away. t 0..1 over its life.
  function flash(x, y, t, o = {}) {
    t = clamp01(t);
    if (t <= 0 || t >= 1) return;
    const size = o.size ?? 120;
    const r = rng(o.seed ?? 5);
    const grow = ease.out(clamp01(t / 0.16));
    const fade = 1 - ease.in(clamp01((t - 0.16) / 0.84));
    const s = size * 0.5 * grow * (0.35 + 0.65 * fade);
    const spikes = 12, jit = Array.from({ length: spikes }, () => 0.7 + r() * 0.6), rot = r() * TAU + t * 0.6;
    const star = (R, inner, color) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      for (let i = 0; i < spikes * 2; i++) {
        const a = rot + (i / (spikes * 2)) * TAU;
        const rr = i % 2 ? R * inner : R * jit[i >> 1];
        if (i) ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); else ctx.moveTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
      }
      ctx.closePath();
      ctx.fill();
    };
    cutout(() => star(s, 0.55, pal.vermilion), { lift: 0.8 });
    star(s * 0.72, 0.6, pal.mustard);
    star(s * 0.4, 0.65, '#FFF6DF');
    // sparks
    ctx.save();
    ctx.strokeStyle = pal.mustard;
    ctx.lineCap = 'round';
    ctx.lineWidth = 3 * unit * fade;
    for (let i = 0; i < 9; i++) {
      const a = r() * TAU, d0 = s * (0.9 + grow * 0.5), d1 = d0 + size * 0.18 * fade;
      ctx.beginPath(); ctx.moveTo(x + Math.cos(a) * d0, y + Math.sin(a) * d0); ctx.lineTo(x + Math.cos(a) * d1, y + Math.sin(a) * d1); ctx.stroke();
    }
    ctx.restore();
  }

  // An expanding ring (a hit, or "here"). t 0..1.
  function pulse(x, y, t, o = {}) {
    t = clamp01(t);
    if (t <= 0 || t >= 1) return;
    ctx.save();
    ctx.globalAlpha *= 1 - t;
    ctx.strokeStyle = o.color || pal.vermilion;
    ctx.lineWidth = (o.width ?? 5) * unit * (1 - t * 0.6);
    ctx.beginPath(); ctx.arc(x, y, (o.size ?? 90) * ease.out(t), 0, TAU); ctx.stroke();
    ctx.restore();
  }

  // Points along a curve from a to b ({x, y}), bowed sideways by bend x its length (negative bows the other way).
  function curve(a, b, bend = 0.15, n = 40) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const cx = (a.x + b.x) / 2 - dy * bend, cy = (a.y + b.y) / 2 + dx * bend;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const u = i / n, v = 1 - u;
      pts.push({ x: v * v * a.x + 2 * v * u * cx + u * u * b.x, y: v * v * a.y + 2 * v * u * cy + u * u * b.y });
    }
    return pts;
  }

  // Where a path is at fraction t of its length: {x, y, angle}.
  function along(pts, t) {
    t = clamp01(t);
    let total = 0;
    const seg = [];
    for (let i = 1; i < pts.length; i++) { const l = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y); seg.push(l); total += l; }
    let want = total * t;
    for (let i = 1; i < pts.length; i++) {
      if (want <= seg[i - 1] || i === pts.length - 1) {
        const f = seg[i - 1] ? Math.min(1, want / seg[i - 1]) : 0;
        const a = pts[i - 1], b = pts[i];
        return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, angle: Math.atan2(b.y - a.y, b.x - a.x) };
      }
      want -= seg[i - 1];
    }
    const a = pts[0];
    return { x: a.x, y: a.y, angle: 0 };
  }

  // A flight path drawn up to fraction t (dashed by default). o.tail: only the last `tail` of the path
  // (0..1) stays drawn behind the head. Returns the head {x, y, angle}, for the thing that flies along it.
  function trail(pts, t, o = {}) {
    t = clamp01(t);
    const head = along(pts, t);
    if (t <= 0) return head;
    const from = o.tail != null ? Math.max(0, t - o.tail) : 0;
    const n = 48;
    ctx.save();
    ctx.strokeStyle = o.color || pal.paper;
    ctx.lineWidth = (o.width ?? 4) * unit;
    ctx.lineCap = 'round';
    if (o.dash !== false) ctx.setLineDash([10 * unit, 9 * unit]);
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const q = along(pts, from + ((t - from) * i) / n);
      if (i) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y);
    }
    if (o.casing !== false) {
      ctx.save(); ctx.setLineDash([]); ctx.strokeStyle = o.casingColor || 'rgba(14,22,74,0.35)'; ctx.lineWidth = ctx.lineWidth + 4 * unit; ctx.stroke(); ctx.restore();
    }
    ctx.stroke();
    ctx.restore();
    return head;
  }

  // Camera: put scene point (cx, cy) at the window's centre, zoomed. Wrap in ctx.save() / ctx.restore().
  function camera(cx, cy, zoom = 1, rotate = 0) {
    ctx.translate(W / 2, H / 2);
    ctx.scale(zoom, zoom);
    if (rotate) ctx.rotate(rotate);
    ctx.translate(-cx, -cy);
  }
  // Blend two camera views {x, y, zoom} (zoom blends evenly in scale, so a push-in feels steady).
  const mixView = (a, b, t) => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, zoom: a.zoom * (b.zoom / a.zoom) ** t });

  // A decaying shake offset {x, y}: amount in px at t = 0, gone by t = 1.
  function shake(t, amount = 8, seed = 1) {
    t = clamp01(t);
    if (t <= 0 || t >= 1) return { x: 0, y: 0 };
    const a = amount * unit * (1 - t) ** 2;
    return { x: a * Math.sin(t * 90 + seed), y: a * Math.cos(t * 71 + seed * 2.3) };
  }

  // A full-window paper-white flash (alpha 0..1), over everything.
  function whiteout(alpha) {
    if (alpha <= 0) return;
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = clamp01(alpha); ctx.fillStyle = '#FFF8E8'; ctx.fillRect(0, 0, W, H); ctx.restore();
  }

  return { fx: Object.freeze({ cutout, smoke, flash, pulse, curve, along, trail, camera, mixView, shake, whiteout, unit }) };
});
