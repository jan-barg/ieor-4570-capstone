// Scene kit (Nov 27, test-only): scene-size paper-cutout pieces for a side view: sky, sea, shore, a long
// bridge with an arch, traffic, a drone, a missile, a ship. Needs kit_fx.js first. Window pixels throughout.
KIT_EXT.push(function (k) {
  const { ctx, W, H, pal, rng, clamp01, fx } = k;
  const TAU = Math.PI * 2;
  const u = fx.unit;
  const INK = pal.ink;
  const STEEL = '#DCE2EC', STEEL_BACK = '#AEB6C8';

  const rect = (x, y, w, h, c, r = 0) => { ctx.fillStyle = c; ctx.beginPath(); if (r) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h); ctx.fill(); };
  const circle = (x, y, r, c) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill(); };
  const poly = (pts, c) => { ctx.fillStyle = c; ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill(); };
  const wrap = (v, m) => ((v % m) + m) % m;

  // Sky in three flat paper bands down to the horizon, with drifting cut-paper clouds.
  function sky(o = {}) {
    const hz = o.horizon ?? H * 0.5, time = o.time ?? 0;
    rect(-W, -H, W * 3, H + hz * 0.42, '#93BCE3');
    rect(-W, hz * 0.42, W * 3, hz * 0.36, pal.sky);
    rect(-W, hz * 0.78, W * 3, hz * 0.22 + 1, '#C9DDF0');
    const r = rng(o.seed ?? 21);
    const n = o.clouds ?? 3;
    for (let i = 0; i < n; i++) {
      const s = (55 + r() * 60) * u, y = hz * (0.12 + r() * 0.45);
      const x = wrap(r() * W + time * (12 + r() * 10) * u, W + s * 3) - s * 1.5;
      fx.cutout(() => {
        ctx.fillStyle = '#F7F3E8';
        ctx.beginPath();
        ctx.arc(x - s * 0.45, y, s * 0.32, 0, TAU);
        ctx.arc(x, y - s * 0.18, s * 0.45, 0, TAU);
        ctx.arc(x + s * 0.5, y + s * 0.02, s * 0.3, 0, TAU);
        ctx.fill();
        ctx.fillRect(x - s * 0.78, y, s * 1.58, s * 0.3);
      }, { lift: 0.5 });
    }
  }

  // Sea from the horizon down, with rows of moving wave marks that grow toward the viewer.
  function sea(o = {}) {
    const hz = o.horizon ?? H * 0.5, time = o.time ?? 0;
    rect(-W, hz, W * 3, H * 2, pal.sea);
    rect(-W, hz, W * 3, 4 * u, '#2A47B0');
    const rows = o.rows ?? 9;
    ctx.save();
    ctx.lineCap = 'round';
    for (let i = 0; i < rows; i++) {
      const d = (i + 0.7) / rows;
      const y = hz + (H - hz) * d ** 1.45;
      const len = (8 + 26 * d) * u, gap = (40 + 90 * d) * u;
      ctx.strokeStyle = i % 2 ? 'rgba(127,164,226,0.55)' : 'rgba(53,82,190,0.9)';
      ctx.lineWidth = (1.5 + 2.5 * d) * u;
      const off = wrap(time * (i % 2 ? 22 : -16) * u * (0.5 + d) + i * 37, gap);
      for (let x = -W - gap + off + (i % 3) * gap * 0.33; x < 2 * W + gap; x += gap) {
        ctx.beginPath(); ctx.moveTo(x, y); ctx.quadraticCurveTo(x + len / 2, y - 3 * u * (0.5 + d), x + len, y); ctx.stroke();
      }
    }
    ctx.restore();
  }

  // A shore at the left or right edge: two layers of low hills sitting on the horizon.
  function shore(o = {}) {
    const side = o.side || 'left', hz = o.horizon ?? H * 0.5, w = o.width ?? W * 0.22, h = o.height ?? H * 0.08;
    const r = rng(o.seed ?? (side === 'left' ? 31 : 37));
    const edge = side === 'left' ? 0 : W, dir = side === 'left' ? 1 : -1;
    const hills = (lift, color, scale) => {
      const pts = [[edge - dir * 10, hz + 12 * u]];
      const steps = 7;
      for (let i = 0; i <= steps; i++) {
        const f = i / steps;
        const x = edge + dir * (w * scale) * f;
        const y = hz - h * lift * (1 - f ** 1.6) * (0.75 + r() * 0.5);
        pts.push([x, y]);
      }
      pts.push([edge + dir * w * scale * 1.06, hz + 12 * u]);
      return pts;
    };
    fx.cutout(() => {
      poly(hills(1.4, '#1E5E34', 0.8), '#1E5E34');
      poly(hills(0.9, pal.land, 1), pal.land);
      rect(side === 'left' ? 0 : W - w * 1.06, hz - 2 * u, w * 1.06, 14 * u, '#CDBF94');   // the beach
    }, { lift: 0.6 });
  }

  // A long two-deck bridge in side view (the rail bridge behind, the road bridge in front) with a steel arch
  // over the ship channel. Returns anchors: {deckY, railY, archX, archTop, archLeft, archRight, water, hit}.
  function bridge(o = {}) {
    const y = o.y ?? H * 0.5;
    const water = o.water ?? y + H * 0.14;
    const x0 = o.from ?? -40 * u, x1 = o.to ?? W + 40 * u;
    const ax = o.archX ?? W * 0.55, aw = o.archWidth ?? W * 0.26, ah = o.archHeight ?? H * 0.17;
    const span = o.pierEvery ?? W * 0.08;
    const time = o.time ?? 0;
    const deck = 11 * u, railUp = 15 * u;
    const aL = ax - aw / 2, aR = ax + aw / 2;
    const piers = [];
    for (let x = aL; x > x0; x -= span) piers.push(x);
    for (let x = aR + span; x < x1; x += span) piers.push(x);

    const arch = (yDeck, height, color, edge, lw) => {
      ctx.save();
      ctx.fillStyle = color;
      ctx.strokeStyle = edge;
      ctx.lineWidth = lw;
      const t = 9 * u;
      ctx.beginPath();
      ctx.moveTo(aL, yDeck);
      ctx.quadraticCurveTo(ax, yDeck - height * 2, aR, yDeck);
      ctx.lineTo(aR - t * 1.4, yDeck);
      ctx.quadraticCurveTo(ax, yDeck - (height - t) * 2, aL + t * 1.4, yDeck);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.lineWidth = 1.6 * u;
      for (let i = 1; i < 9; i++) {
        const hx = aL + (aw * i) / 9;
        const f = (hx - ax) / (aw / 2);
        const top = yDeck - (height - t) * (1 - f * f);
        ctx.beginPath(); ctx.moveTo(hx, top); ctx.lineTo(hx, yDeck); ctx.stroke();
      }
      ctx.restore();
    };
    const pierShape = (x, top, w, front) => {
      rect(x - w / 2, top, w, water - top, front ? '#24337F' : '#3A4796');
      if (front) rect(x - w / 2, top, w * 0.35, water - top, '#3552BE');
      rect(x - w * 0.8, water - 4 * u, w * 1.6, 6 * u, front ? '#1A2A86' : '#2B3A8C');
    };

    // rail bridge, behind
    fx.cutout(() => {
      for (const x of piers) pierShape(x + 6 * u, y - railUp + deck, 9 * u, false);
      pierShape(aL + 6 * u, y - railUp + deck, 15 * u, false);
      pierShape(aR + 6 * u, y - railUp + deck, 15 * u, false);
      rect(x0, y - railUp, x1 - x0, deck * 0.8, '#C8C0AA');
    }, { lift: 0.6 });
    arch(y - railUp, ah * 1.12, STEEL_BACK, '#6C7593', 1.5 * u);
    if (o.train !== false && o.train != null) {
      const tx = x0 + (x1 - x0 + 320 * u) * clamp01(o.train) - 300 * u;
      fx.cutout(() => {
        for (let c = 0; c < 5; c++) {
          const cx = tx + c * 62 * u;
          rect(cx, y - railUp - 16 * u, 58 * u, 15 * u, pal.cobalt, 3 * u);
          rect(cx + 6 * u, y - railUp - 13 * u, 46 * u, 4 * u, '#F3EEE1', 1.5 * u);
        }
      }, { lift: 0.5 });
    }
    // road bridge, in front
    fx.cutout(() => {
      for (const x of piers) pierShape(x, y + deck, 11 * u, true);
      pierShape(aL, y + deck, 18 * u, true);
      pierShape(aR, y + deck, 18 * u, true);
      rect(x0, y, x1 - x0, deck, pal.paper);
      rect(x0, y + deck - 3 * u, x1 - x0, 3 * u, INK);
    });
    arch(y, ah, STEEL, INK, 2 * u);
    // traffic on the road deck
    const cars = o.traffic === false ? 0 : (o.traffic ?? 7);
    if (cars) {
      const r = rng(o.seed ?? 41), speed = o.trafficSpeed ?? 1;
      const colors = [pal.mustard, pal.vermilion, pal.paper, pal.cobalt, '#F0B347'];
      fx.cutout(() => {
        for (let i = 0; i < cars; i++) {
          const dirn = i % 2 ? 1 : -1;
          const cx = x0 + wrap(r() * (x1 - x0) + dirn * time * speed * 70 * u, x1 - x0);
          const cw = (20 + r() * 10) * u;
          rect(cx, y - 9 * u, cw, 9 * u, colors[i % colors.length], 3 * u);
          rect(cx + cw * 0.25, y - 7 * u, cw * 0.4, 3 * u, 'rgba(26,42,134,0.55)', 1 * u);
        }
      }, { lift: 0.3 });
    }
    // railing
    ctx.save(); ctx.strokeStyle = 'rgba(26,42,134,0.5)'; ctx.lineWidth = 1.3 * u;
    ctx.beginPath(); ctx.moveTo(x0, y - 4 * u); ctx.lineTo(x1, y - 4 * u); ctx.stroke(); ctx.restore();
    return { deckY: y, railY: y - railUp, archX: ax, archTop: y - ah, archLeft: aL, archRight: aR, water, hit: { x: ax, y: y - ah * 0.45 } };
  }

  // A generic fixed-wing drone seen from above, nose along `angle` (radians, 0 = right). size = length in px.
  function drone(x, y, size, o = {}) {
    const s = size / 100, time = o.time ?? 0;
    ctx.save();
    ctx.translate(x, y); ctx.rotate(o.angle ?? 0); ctx.scale(s, s);
    if (o.alpha != null) ctx.globalAlpha *= o.alpha;
    fx.cutout(() => {
      ctx.strokeStyle = INK; ctx.lineWidth = 2.2 / s * u;
      const body = '#C9CCD6';
      const shape = (pts) => { ctx.fillStyle = body; ctx.beginPath(); pts.forEach(([a, b], i) => (i ? ctx.lineTo(a, b) : ctx.moveTo(a, b))); ctx.closePath(); ctx.fill(); ctx.stroke(); };
      shape([[2, -46], [14, -46], [10, -4], [10, 4], [14, 46], [2, 46], [-6, 4], [-6, -4]]);        // wings
      shape([[-40, -16], [-34, -16], [-30, -3], [-30, 3], [-34, 16], [-40, 16], [-42, 3], [-42, -3]]); // tail
      ctx.fillStyle = body; ctx.beginPath(); ctx.roundRect(-46, -6, 96, 12, 6); ctx.fill(); ctx.stroke();  // body
    }, { lift: 1.6 });
    circle(42, 0, 3, pal.vermilion);
    // pusher propeller, spinning
    ctx.strokeStyle = 'rgba(26,42,134,0.75)'; ctx.lineWidth = 3;
    const a = time * 60;
    ctx.beginPath(); ctx.moveTo(-48, Math.sin(a) * 13); ctx.lineTo(-48, -Math.sin(a) * 13); ctx.stroke();
    ctx.restore();
  }

  // A generic cruise missile seen from the side/above, nose along `angle`, with a flickering exhaust.
  function missile(x, y, size, o = {}) {
    const s = size / 100, time = o.time ?? 0;
    ctx.save();
    ctx.translate(x, y); ctx.rotate(o.angle ?? 0); ctx.scale(s, s);
    if (o.alpha != null) ctx.globalAlpha *= o.alpha;
    if (o.flame !== false) {
      const f = 1 + 0.25 * Math.sin(time * 47) + 0.15 * Math.sin(time * 83);
      poly([[-50, -5], [-50 - 22 * f, 0], [-50, 5]], pal.mustard);
      poly([[-50, -3], [-50 - 12 * f, 0], [-50, 3]], '#FFF6DF');
    }
    fx.cutout(() => {
      ctx.strokeStyle = INK; ctx.lineWidth = 2 / s * u;
      poly([[-6, -5], [10, -26], [16, -26], [8, -5], [8, 5], [16, 26], [10, 26], [-6, 5]], '#B9BFCF');   // wings
      poly([[-50, -5], [-56, -16], [-44, -16], [-38, -5], [-38, 5], [-44, 16], [-56, 16], [-50, 5]], INK);  // fins
      ctx.fillStyle = '#E8EAF0'; ctx.beginPath(); ctx.moveTo(-50, -6); ctx.lineTo(34, -6); ctx.quadraticCurveTo(52, -4, 54, 0); ctx.quadraticCurveTo(52, 4, 34, 6); ctx.lineTo(-50, 6); ctx.closePath(); ctx.fill(); ctx.stroke();
    }, { lift: 1.6 });
    rect(-30, -6, 5, 12, pal.vermilion);
    ctx.restore();
  }

  // A cargo ship in side view, bobbing; size = length in px. Its waterline sits at y.
  function ship(x, y, size, o = {}) {
    const s = size / 100, time = o.time ?? 0;
    ctx.save();
    ctx.translate(x, y + Math.sin(time * 2.2) * 1.5 * u); ctx.rotate(Math.sin(time * 1.7) * 0.012); ctx.scale(o.flip ? -s : s, s);
    fx.cutout(() => {
      const cols = [pal.vermilion, pal.mustard, pal.cobalt, pal.mustard, pal.vermilion, pal.cobalt, pal.mustard, pal.cobalt];
      cols.forEach((c, i) => rect(-38 + (i % 4) * 15, -14 - Math.floor(i / 4) * 9, 14, 8, c, 1));   // on the deck
      rect(24, -32, 13, 26, pal.paper, 1.5); rect(27, -28, 7, 3, INK);
      // a rust-red hull with a pale waterline: the ink hull it had was the sea's own blue and vanished into it
      poly([[-48, -5], [48, -5], [40, 8], [-44, 8]], '#8A3426');
      rect(-48, -6, 96, 1.6, pal.paperDeep);
      rect(-45, 2, 88, 3, pal.paper);
    }, { lift: 0.8 });
    ctx.restore();
  }

  return { scene: Object.freeze({ sky, sea, shore, bridge, drone, missile, ship }) };
});
