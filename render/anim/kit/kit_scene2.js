// Scene kit, part 2 (Nov 27, test-only): the most-needed pieces the library lacked (analysis/props/match_library.json):
// people (politician, police officer, soldier, protester, judge, a plain person) and a crowd, a podium with microphones,
// a reporter's microphone, a meeting table, a classical government building, fire, and two settings (a room, a street).
// People are faceless paper cutouts. Needs kit_fx.js and kit_scene.js first. Window pixels throughout.
KIT_EXT.push(function (k) {
  const { ctx, W, H, pal, rng, clamp01, fx, scene } = k;
  const TAU = Math.PI * 2;
  const u = fx.unit;
  const SKIN = '#E8D2B8', SKIN_SHADE = '#D4B999';
  const HAIRS = ['#2B2A3A', '#4A3A2E', '#7A6250', '#9A9AA6', '#2B2A3A'];
  const CASUAL = [pal.vermilion, pal.mustard, pal.cobalt, '#3E8E5A', '#8E4A7A', '#D9CBA8', '#E8743B'];
  const SUITS = ['#2A3566', '#3B3F4E', '#283A52', '#4A3B48'];

  const rect = (x, y, w, h, c, r = 0) => { ctx.fillStyle = c; ctx.beginPath(); if (r) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h); ctx.fill(); };
  const circle = (x, y, r, c) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x, y, Math.max(0, r), 0, TAU); ctx.fill(); };
  const poly = (pts, c) => { ctx.fillStyle = c; ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill(); };
  const line = (pts, w, c) => { ctx.strokeStyle = c; ctx.lineWidth = w; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); };
  const wrap = (v, m) => ((v % m) + m) % m;

  // ---------- people ----------
  const STYLE = {
    politician: { top: null, suit: true, legs: null, shoes: '#16182A' },
    police: { top: '#1F2B57', legs: '#1B254D', shoes: '#111526', hat: 'cap' },
    soldier: { top: '#5A6640', legs: '#4E5937', shoes: '#2E2A22', hat: 'helmet' },
    protester: { top: null, legs: '#3A4A7A', shoes: '#2A2A33' },
    judge: { top: '#1C1C2A', legs: '#1C1C2A', shoes: '#111111', robe: true },
    person: { top: null, legs: '#4A4F6E', shoes: '#2A2A33' },
    diplomat: { top: null, suit: true, legs: null, shoes: '#16182A', carry: 'briefcase' },
    lawyer: { top: null, suit: true, legs: null, shoes: '#16182A', carry: 'folder' },
  };

  function hairOrHat(S, R, hy, hair, style) {
    if (S.hat === 'cap') {
      rect(-R * 1.02, hy - R * 1.05, R * 2.04, R * 0.75, '#1A2348', R * 0.25);
      poly([[R * 0.2, hy - R * 0.32], [R * 1.45, hy - R * 0.22], [R * 1.4, hy - R * 0.08], [R * 0.2, hy - R * 0.16]], '#111833');
      rect(-R * 1.02, hy - R * 0.42, R * 2.04, R * 0.16, '#111833');
      circle(R * 0.35, hy - R * 0.72, R * 0.17, pal.mustard);
      return;
    }
    if (S.hat === 'helmet') {
      ctx.fillStyle = '#4B5533'; ctx.beginPath(); ctx.ellipse(-R * 0.05, hy - R * 0.25, R * 1.22, R * 1.05, 0, Math.PI, TAU); ctx.fill();
      rect(-R * 1.3, hy - R * 0.32, R * 2.5, R * 0.2, '#414A2C', R * 0.1);
      line([[R * 0.75, hy - R * 0.2], [R * 0.55, hy + R * 0.75]], R * 0.12, '#2E3420');
      return;
    }
    if (style === 2) return;                                   // very short hair: none drawn
    ctx.fillStyle = hair;
    if (style === 1) { ctx.beginPath(); ctx.roundRect(-R * 1.12, hy - R * 0.55, R * 1.7, R * 1.75, R * 0.6); ctx.fill(); }
    if (style === 3) circle(-R * 0.85, hy - R * 0.75, R * 0.38, hair);
    ctx.beginPath(); ctx.ellipse(-R * 0.12, hy - R * 0.42, R * 1.05, R * 0.72, 0, Math.PI * 0.98, TAU * 1.01); ctx.fill();
  }

  // A standing person, feet at (x, y), h px tall, turned toward `facing` (1 right, -1 left). No face is drawn.
  // o: {seed, time, gesture 0..1 (raises the arm on the facing side), walk (true: steps in place), color, sign, alpha}
  function person(kind, x, y, h, o = {}) {
    const S = STYLE[kind] || STYLE.person;
    const seed = o.seed ?? 1, r = rng(seed * 7 + 3), time = o.time ?? 0;
    const top = o.color || (S.suit ? SUITS[Math.floor(r() * SUITS.length)] : S.top) || CASUAL[Math.floor(r() * CASUAL.length)];
    const legs = S.legs || (S.suit ? top : '#3A4A7A');
    const hair = HAIRS[Math.floor(r() * HAIRS.length)], style = Math.floor(r() * 4);
    const f = o.facing ?? 1;
    const bob = Math.sin(time * 2.2 + seed) * 0.004 * h;
    const step = o.walk ? Math.sin(time * 6 + seed) : 0;
    const sign = kind === 'protester' && o.sign !== false;
    const g = sign ? 1 : clamp01(o.gesture ?? 0);
    const sy = -0.80 * h + bob, hip = -0.47 * h, sw = 0.12 * h, R = 0.074 * h, hy = -0.895 * h + bob;
    const arm = (side, gg) => {
      const sx = side * (sw - 0.03 * h), y0 = sy + 0.05 * h;
      const a1 = 0.12 + gg * 1.0, a2 = 0.06 + gg * 2.45;
      const ex = sx + side * Math.sin(a1) * 0.17 * h, ey = y0 + Math.cos(a1) * 0.17 * h;
      const hx = ex + side * Math.sin(a2) * 0.15 * h, hy2 = ey + Math.cos(a2) * 0.15 * h;
      line([[sx, y0], [ex, ey], [hx, hy2]], 0.066 * h, top);
      circle(hx, hy2, 0.032 * h, SKIN);
      return { x: hx, y: hy2 };
    };
    ctx.save();
    ctx.translate(x, y); ctx.scale(f, 1);
    if (o.alpha != null) ctx.globalAlpha *= clamp01(o.alpha);
    fx.cutout(() => {
      const back = arm(-1, 0);
      const st = step * 0.06 * h;
      line([[-0.045 * h, hip], [-0.05 * h - st, -0.035 * h]], 0.088 * h, legs);
      line([[0.045 * h, hip], [0.05 * h + st, -0.035 * h]], 0.088 * h, legs);
      rect(-0.085 * h - st, -0.045 * h, 0.1 * h, 0.045 * h, S.shoes, 0.018 * h);
      rect(0.02 * h + st, -0.045 * h, 0.1 * h, 0.045 * h, S.shoes, 0.018 * h);
      if (S.carry === 'briefcase') {                               // hangs from the back hand
        line([[back.x - 0.035 * h, back.y + 0.03 * h], [back.x - 0.03 * h, back.y - 0.005 * h], [back.x + 0.03 * h, back.y - 0.005 * h], [back.x + 0.035 * h, back.y + 0.03 * h]], 0.012 * h, '#4A3222');
        rect(back.x - 0.08 * h, back.y + 0.025 * h, 0.16 * h, 0.115 * h, '#6B4A32', 0.012 * h);
        rect(back.x - 0.08 * h, back.y + 0.05 * h, 0.16 * h, 0.012 * h, '#4A3222');
        rect(back.x - 0.012 * h, back.y + 0.045 * h, 0.024 * h, 0.022 * h, pal.mustard, 0.004 * h);
        circle(back.x, back.y, 0.032 * h, SKIN);
      }
      if (S.robe) poly([[-sw, sy + 0.035 * h], [sw, sy + 0.035 * h], [0.16 * h, -0.06 * h], [-0.16 * h, -0.06 * h]], top);
      else poly([[-sw, sy + 0.035 * h], [sw, sy + 0.035 * h], [0.095 * h, hip + 0.03 * h], [-0.095 * h, hip + 0.03 * h]], top);
      circle(-sw + 0.035 * h, sy + 0.05 * h, 0.036 * h, top);
      circle(sw - 0.035 * h, sy + 0.05 * h, 0.036 * h, top);
      if (S.suit) {
        poly([[-0.04 * h, sy + 0.035 * h], [0.04 * h, sy + 0.035 * h], [0, sy + 0.15 * h]], '#F3EEE1');
        poly([[-0.012 * h, sy + 0.05 * h], [0.012 * h, sy + 0.05 * h], [0.017 * h, sy + 0.19 * h], [0, sy + 0.215 * h], [-0.017 * h, sy + 0.19 * h]], r() < 0.5 ? pal.vermilion : pal.cobalt);
      }
      if (kind === 'police') {
        circle(0.05 * h, sy + 0.11 * h, 0.017 * h, pal.mustard);
        rect(-0.098 * h, hip - 0.005 * h, 0.196 * h, 0.03 * h, '#111A3A');
        rect(-0.015 * h, hip - 0.003 * h, 0.03 * h, 0.026 * h, pal.mustard, 0.005 * h);
      }
      if (kind === 'soldier') {
        rect(-0.092 * h, sy + 0.07 * h, 0.184 * h, 0.21 * h, '#47512F', 0.02 * h);
        rect(-0.07 * h, sy + 0.17 * h, 0.05 * h, 0.05 * h, '#3D4628', 0.008 * h);
        rect(0.02 * h, sy + 0.17 * h, 0.05 * h, 0.05 * h, '#3D4628', 0.008 * h);
      }
      if (kind === 'judge') { rect(-0.03 * h, sy + 0.04 * h, 0.025 * h, 0.07 * h, '#F3EEE1'); rect(0.005 * h, sy + 0.04 * h, 0.025 * h, 0.07 * h, '#F3EEE1'); }
      rect(-0.026 * h, sy - 0.035 * h, 0.052 * h, 0.06 * h, SKIN_SHADE);
      ctx.fillStyle = hair;                                       // long hair falls behind the head
      if (!S.hat && style === 1) { ctx.beginPath(); ctx.roundRect(-R * 1.12, hy - R * 0.55, R * 1.7, R * 1.75, R * 0.6); ctx.fill(); }
      circle(0, hy, R, SKIN);
      hairOrHat(S, R, hy, hair, style === 1 ? 0 : style);
      if (S.carry === 'folder') {                                  // held against the side, under the front arm
        ctx.save(); ctx.translate(0.09 * h, sy + 0.2 * h); ctx.rotate(0.12);
        rect(-0.06 * h, -0.085 * h, 0.12 * h, 0.17 * h, '#F7F3E8', 0.006 * h);
        rect(-0.065 * h, -0.075 * h, 0.12 * h, 0.17 * h, '#2F4AA8', 0.008 * h);
        rect(-0.065 * h, -0.075 * h, 0.02 * h, 0.17 * h, '#1A2A86');
        ctx.restore();
      }
      const hand = arm(1, g);
      if (sign) {
        const sb = Math.sin(time * 4 + seed * 1.3) * 0.025 * h;
        const tx = hand.x + 0.01 * h, ty = hand.y - 0.36 * h + sb;
        line([[hand.x, hand.y + 0.03 * h], [tx, ty]], 0.02 * h, '#8A6A45');
        ctx.save(); ctx.translate(tx, ty); ctx.rotate(Math.sin(time * 3 + seed) * 0.05);
        rect(-0.2 * h, -0.24 * h, 0.4 * h, 0.26 * h, o.signColor || '#F7F3E8', 0.01 * h);
        ctx.strokeStyle = 'rgba(26,42,134,0.35)'; ctx.lineWidth = 0.008 * h; ctx.strokeRect(-0.17 * h, -0.21 * h, 0.34 * h, 0.2 * h);
        ctx.restore();
      }
    }, { lift: 0.7 });
    ctx.restore();
  }

  // A crowd standing along y from x0 to x1, h px tall (front row). o: {kind, count, rows, time, seed, facing, walk}
  function crowd(x0, x1, y, h, o = {}) {
    const kind = o.kind || 'protester';
    const n = o.count ?? Math.max(3, Math.round((x1 - x0) / (h * 0.3)));
    const rows = o.rows ?? 2, seed = o.seed ?? 5;
    for (let row = rows - 1; row >= 0; row--) {
      const r = rng(seed * 13 + row * 7);
      const s = 1 - row * 0.1, yy = y - row * h * 0.09;
      for (let i = 0; i < n; i++) {
        const xx = x0 + (x1 - x0) * ((i + 0.5 + (row % 2) * 0.5 + (r() - 0.5) * 0.35) / (n + (row % 2) * 0.5));
        person(kind, xx, yy, h * s * (0.92 + r() * 0.14), {
          seed: seed * 31 + i * 7 + row * 101, time: o.time, walk: o.walk,
          facing: o.facing ?? (r() < 0.5 ? 1 : -1), sign: kind === 'protester' ? r() < 0.55 : undefined,
          gesture: kind === 'protester' ? 0 : o.gesture,
        });
      }
    }
  }

  // ---------- things ----------
  // A lectern with microphones; y is the floor, size its height.
  // o: {speaker: a kind of person ('politician', 'judge', 'soldier', 'police', 'person', 'diplomat', 'lawyer',
  //     'protester') drawn standing behind it, about 1.75 x size tall (Nov 28: a court's president at the podium
  //     wore a suit because only a suit could stand there), gesture (0..1), time, seed, mics, color}
  // Without o.speaker, draw your own person first at the returned speaker point, then the podium over their legs.
  function podium(x, y, size, o = {}) {
    const top = y - size, tw = size * 0.66, bw = size * 0.52;
    if (o.speaker) person(STYLE[o.speaker] ? o.speaker : 'politician', x, y - size * 0.02, size * 1.75,
      { gesture: o.gesture ?? 0.5, time: o.time ?? 0, seed: o.seed ?? 5, facing: o.facing ?? 1 });
    fx.cutout(() => {
      poly([[x - tw / 2, top + size * 0.06], [x + tw / 2, top + size * 0.06], [x + bw / 2, y - size * 0.04], [x - bw / 2, y - size * 0.04]], o.color || '#2F4AA8');
      poly([[x - tw / 2, top + size * 0.06], [x - tw / 2 + size * 0.09, top + size * 0.06], [x - bw / 2 + size * 0.075, y - size * 0.04], [x - bw / 2, y - size * 0.04]], '#3D5BC4');
      rect(x - tw / 2 - size * 0.04, top, tw + size * 0.08, size * 0.075, pal.paperDeep, 3 * u);
      rect(x - bw / 2 - size * 0.05, y - size * 0.05, bw + size * 0.1, size * 0.05, '#1A2A86', 2 * u);
      circle(x, top + size * 0.38, size * 0.12, pal.paper);
      ctx.strokeStyle = pal.mustard; ctx.lineWidth = size * 0.02; ctx.beginPath(); ctx.arc(x, top + size * 0.38, size * 0.085, 0, TAU); ctx.stroke();
    });
    const n = o.mics ?? 3, flags = [pal.vermilion, pal.mustard, pal.cobalt, '#3E8E5A'];
    fx.cutout(() => {
      for (let i = 0; i < n; i++) {
        const off = i - (n - 1) / 2;
        const bx = x + off * size * 0.05, mx = x + off * size * 0.1, my = top - size * (0.3 + (i % 2) * 0.05);
        line([[bx, top + size * 0.02], [bx + (mx - bx) * 0.3, top - size * 0.12], [mx, my]], size * 0.018, '#22233A');
        rect(mx - size * 0.03, my - size * 0.07, size * 0.06, size * 0.09, '#22233A', size * 0.03);
        if (i % 2 === 0) rect(mx - size * 0.045, my + size * 0.025, size * 0.09, size * 0.06, flags[i % flags.length], size * 0.008);
      }
    }, { lift: 0.5 });
    return { speaker: { x, y: y - size * 0.02 }, top, mics: { x, y: top - size * 0.33 } };
  }

  // A reporter's handheld microphone: the head at (x, y), pointing along angle (radians; -PI/2 = up). size = length.
  // o: {arm: true draws a sleeve reaching in from beyond it, color (the mic flag), seed}
  function microphone(x, y, size, o = {}) {
    const a = o.angle ?? -Math.PI / 2, r = rng(o.seed ?? 3);
    ctx.save(); ctx.translate(x, y); ctx.rotate(a + Math.PI / 2);
    fx.cutout(() => {
      if (o.arm) { rect(-size * 0.11, size * 0.62, size * 0.22, size * 1.6, CASUAL[Math.floor(r() * CASUAL.length)], size * 0.06); rect(-size * 0.1, size * 0.48, size * 0.2, size * 0.2, SKIN, size * 0.08); }
      rect(-size * 0.06, size * 0.1, size * 0.12, size * 0.6, '#2C2C3A', size * 0.04);
      rect(-size * 0.17, size * 0.12, size * 0.34, size * 0.24, o.color || [pal.vermilion, pal.mustard, pal.cobalt][Math.floor(r() * 3)], size * 0.03);
      circle(0, 0, size * 0.16, '#22233A');
      circle(-size * 0.05, -size * 0.05, size * 0.04, '#4A4B66');
    }, { lift: 0.9 });
    ctx.restore();
  }

  // A meeting table seen from the front, people seated behind it. y is the floor, width its width.
  // o: {seats (1..20; past 9 they sit in two rows, the back row raised and between the front row's heads),
  //     kind ('politician' suits by default; 'judge' robes behind a wooden bench; 'soldier', 'police', 'person',
  //     'diplomat', 'lawyer'), time, seed, speaker (index of the one gesturing, or -1), color (the table's skirt)}
  // Returns {top, seats: [{x, y}] (the heads: front row first)}.
  function table(x, y, width, o = {}) {
    const n = Math.max(1, Math.min(Math.round(o.seats ?? 4), 20)), time = o.time ?? 0, seed = o.seed ?? 9;
    const kind = STYLE[o.kind] ? o.kind : 'politician', S = STYLE[kind];
    const front = n > 9 ? Math.ceil(n / 2) : n, back = n - front;
    const ty = y - width * 0.2, h = Math.min(width / front * 2.1, width * 0.5);   // chairs are 0.3 h wide, so they never overlap
    const heads = [];
    const sit = (i, cx, baseY, hh) => {
      const r = rng(seed * 17 + i * 5);
      const pick = SUITS[Math.floor(r() * SUITS.length)];
      const suit = S.suit ? pick : (S.top || CASUAL[Math.floor(r() * CASUAL.length)]), hair = HAIRS[Math.floor(r() * HAIRS.length)], style = Math.floor(r() * 4);
      const talk = i === (o.speaker ?? -1) ? 0.5 + 0.5 * Math.sin(time * 5) : 0;
      const bob = Math.sin(time * 2 + i * 1.7) * 0.004 * hh;
      const shy = baseY - 0.25 * hh + bob, R = 0.074 * hh, hy = shy - 0.12 * hh;
      heads[i] = { x: cx, y: baseY - 0.37 * hh };
      fx.cutout(() => {
        rect(cx - 0.15 * hh, shy - 0.2 * hh, 0.3 * hh, 0.5 * hh, '#3A3A52', 0.04 * hh);           // chair back
        poly([[cx - 0.13 * hh, shy], [cx + 0.13 * hh, shy], [cx + 0.115 * hh, baseY + 0.02 * hh], [cx - 0.115 * hh, baseY + 0.02 * hh]], suit);
        circle(cx - 0.1 * hh, shy + 0.02 * hh, 0.035 * hh, suit); circle(cx + 0.1 * hh, shy + 0.02 * hh, 0.035 * hh, suit);
        if (S.suit) poly([[cx - 0.035 * hh, shy], [cx + 0.035 * hh, shy], [cx, shy + 0.1 * hh]], '#F3EEE1');
        if (kind === 'judge') { rect(cx - 0.026 * hh, shy - 0.005 * hh, 0.022 * hh, 0.065 * hh, '#F3EEE1'); rect(cx + 0.004 * hh, shy - 0.005 * hh, 0.022 * hh, 0.065 * hh, '#F3EEE1'); }
        if (kind === 'police') circle(cx + 0.06 * hh, shy + 0.07 * hh, 0.016 * hh, pal.mustard);
        rect(cx - 0.024 * hh, shy - 0.05 * hh, 0.048 * hh, 0.06 * hh, SKIN_SHADE);
        if (S.hat) { circle(cx, hy, R, SKIN); ctx.save(); ctx.translate(cx, 0); hairOrHat(S, R, hy, hair, style); ctx.restore(); }
        else {
          if (style === 1) { ctx.fillStyle = hair; ctx.beginPath(); ctx.roundRect(cx - R * 1.05, hy - R * 0.5, R * 2.1, R * 1.7, R * 0.6); ctx.fill(); }
          circle(cx, hy, R, SKIN);
          if (style !== 2) { ctx.fillStyle = hair; ctx.beginPath(); ctx.ellipse(cx, hy - R * 0.45, R * 1.04, R * 0.66, 0, Math.PI * 0.98, TAU * 1.01); ctx.fill(); }
        }
        line([[cx - 0.11 * hh, shy + 0.04 * hh], [cx - 0.15 * hh, baseY - 0.02 * hh], [cx - 0.05 * hh, baseY - 0.01 * hh]], 0.06 * hh, suit);
        line([[cx + 0.11 * hh, shy + 0.04 * hh], [cx + 0.15 * hh - talk * 0.02 * hh, baseY - 0.02 * hh - talk * 0.12 * hh], [cx + 0.06 * hh + talk * 0.05 * hh, baseY - 0.01 * hh - talk * 0.22 * hh]], 0.06 * hh, suit);
        circle(cx - 0.05 * hh, baseY - 0.01 * hh, 0.03 * hh, SKIN);
        circle(cx + 0.06 * hh + talk * 0.05 * hh, baseY - 0.01 * hh - talk * 0.22 * hh, 0.03 * hh, SKIN);
      }, { lift: 0.6 });
    };
    // the back row first (raised, a little smaller, each between two front-row heads), then the front row
    for (let j = 0; j < back; j++) sit(front + j, x - width / 2 + width * (j + 1) / (back + 1), ty - 0.2 * h, h * 0.9);
    for (let i = 0; i < front; i++) sit(i, x - width / 2 + width * (i + 0.5) / front, ty, h);
    fx.cutout(() => {
      rect(x - width / 2 - width * 0.02, ty - width * 0.012, width * 1.04, width * 0.03, pal.paper, 2 * u);
      const skirt = o.color || (kind === 'judge' ? '#6B4A32' : '#2F4AA8');
      rect(x - width / 2, ty + width * 0.018, width, y - ty - width * 0.018, skirt);
      rect(x - width / 2, ty + width * 0.018, width, width * 0.02, kind === 'judge' && !o.color ? '#8A6446' : '#3D5BC4');
      if (kind === 'judge' && !o.color) for (let i = 1; i < 5; i++) rect(x - width / 2 + width * i / 5 - 2 * u, ty + width * 0.04, 4 * u, y - ty - width * 0.06, '#5A3E2A');
    });
    for (let i = 0; i < front; i++) {
      const cx = x - width / 2 + width * (i + 0.5) / front, s = Math.min(width / front, width / 6);
      fx.cutout(() => {
        poly([[cx - s * 0.16, ty - width * 0.012], [cx - s * 0.12, ty - width * 0.012 - s * 0.1], [cx + s * 0.08, ty - width * 0.012 - s * 0.1], [cx + s * 0.12, ty - width * 0.012]], '#F7F3E8');
        rect(cx + s * 0.22, ty - width * 0.012 - s * 0.2, s * 0.06, s * 0.2, 'rgba(168,201,234,0.95)', s * 0.015);
        rect(cx + s * 0.225, ty - width * 0.012 - s * 0.23, s * 0.05, s * 0.035, pal.cobalt, s * 0.01);
        line([[cx - s * 0.3, ty - width * 0.012], [cx - s * 0.26, ty - width * 0.012 - s * 0.16], [cx - s * 0.18, ty - width * 0.012 - s * 0.22]], s * 0.012, '#22233A');
      }, { lift: 0.4 });
    }
    return { top: ty, seats: heads };
  }

  // A classical government building (parliament, ministry, court): steps, columns, a pediment, and a dome unless
  // o.dome === false. y is the ground, width its width. Returns {top, door: {x, y}, dome: {x, y}, and, for an
  // effect that happens TO the building: roof: {x, y, w} (the line along its roof), front: {x, y, w, h} (its
  // facade, y its middle), windows: [{x, y}] (the wings' windows)}.
  function government(x, y, width, o = {}) {
    // columns: a count (2 to 12), true for the usual 6, false for a plain wall with a door (a model once passed
    // true, which drew no columns and left the porch a dark block)
    const n = Number(o.columns), plain = o.columns === false;
    const w = width, h = w * 0.42, cols = plain ? 0 : Number.isFinite(n) && typeof o.columns === 'number' ? Math.max(2, Math.min(12, Math.round(n))) : 6;
    const base = y - w * 0.06, roof = base - h * 0.72;
    const STONE = '#F1EADB', SHADE = '#D9CFB8', DEEP = '#C9BEA4';
    if (o.dome !== false) {
      fx.cutout(() => {
        rect(x - w * 0.16, roof - h * 0.62, w * 0.32, h * 0.34, SHADE);
        for (let i = 0; i < 7; i++) rect(x - w * 0.14 + i * w * 0.045, roof - h * 0.58, w * 0.018, h * 0.28, STONE);
        ctx.fillStyle = '#DCE2EC'; ctx.beginPath(); ctx.ellipse(x, roof - h * 0.62, w * 0.18, h * 0.5, 0, Math.PI, TAU); ctx.fill();
        ctx.strokeStyle = '#B9C2D3'; ctx.lineWidth = 2 * u;
        for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.ellipse(x, roof - h * 0.62, Math.abs(i) * w * 0.07 + 0.001, h * 0.5, 0, Math.PI, TAU); ctx.stroke(); }
        rect(x - w * 0.02, roof - h * 1.22, w * 0.04, h * 0.12, STONE);
        circle(x, roof - h * 1.24, w * 0.022, '#DCE2EC');
      }, { lift: 0.6 });
    }
    fx.cutout(() => {
      if (o.wings !== false) {
        for (const side of [-1, 1]) {
          const wx = side < 0 ? x - w * 0.5 : x + w * 0.22;
          rect(wx, roof + h * 0.12, w * 0.28, base - roof - h * 0.12, STONE);
          rect(wx, roof + h * 0.08, w * 0.28, h * 0.06, SHADE);
          for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) rect(wx + w * (0.03 + i * 0.065), roof + h * (0.25 + j * 0.24), w * 0.03, h * 0.14, '#3B4466', 2 * u);
        }
      }
      rect(x - w * 0.24, roof, w * 0.48, base - roof, plain ? STONE : '#3B4466');
      if (plain) rect(x - w * 0.05, base - h * 0.42, w * 0.1, h * 0.42, '#3B4466', 2 * u);
      for (let i = 0; i < cols; i++) {
        const cx = x - w * 0.22 + (w * 0.44 * i) / (cols - 1);
        rect(cx - w * 0.018, roof + h * 0.06, w * 0.036, base - roof - h * 0.06, STONE);
        rect(cx - w * 0.018, roof + h * 0.06, w * 0.01, base - roof - h * 0.06, SHADE);
        rect(cx - w * 0.026, roof + h * 0.04, w * 0.052, h * 0.04, STONE);
      }
      rect(x - w * 0.26, roof - h * 0.02, w * 0.52, h * 0.08, SHADE);
      poly([[x - w * 0.27, roof - h * 0.02], [x, roof - h * 0.3], [x + w * 0.27, roof - h * 0.02]], STONE);
      poly([[x - w * 0.2, roof - h * 0.05], [x, roof - h * 0.24], [x + w * 0.2, roof - h * 0.05]], SHADE);
      for (let s = 0; s < 3; s++) rect(x - w * (0.3 + s * 0.04), base + s * w * 0.02, w * (0.6 + s * 0.08), w * 0.02, s % 2 ? SHADE : DEEP);
    });
    const windows = [];
    if (o.wings !== false) {
      for (const side of [-1, 1]) {
        const wx = side < 0 ? x - w * 0.5 : x + w * 0.22;
        for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) windows.push({ x: wx + w * (0.045 + i * 0.065), y: roof + h * (0.32 + j * 0.24) });
      }
    }
    return { top: roof - (o.dome !== false ? h * 1.25 : h * 0.3), door: { x, y: base }, dome: { x, y: roof - h * 0.85 },
      roof: { x, y: roof - h * 0.02, w: w * (o.wings !== false ? 1 : 0.54) },
      front: { x, y: (roof + base) / 2, w: w * (o.wings !== false ? 1 : 0.48), h: base - roof }, windows };
  }

  // Fire: paper flames at (x, y) (their base), size = width; they reach about 1.3 x size high. time: p * 8.
  function fire(x, y, size, o = {}) {
    const time = o.time ?? 0, r = rng(o.seed ?? 11), n = o.tongues ?? 7, grow = clamp01(o.t ?? 1);
    if (grow <= 0) return;
    const tongues = [];
    for (let i = 0; i < n; i++) {
      const f = n > 1 ? i / (n - 1) : 0.5;
      tongues.push({ bx: x + (f - 0.5) * size * 0.8, w: size * (0.22 + r() * 0.14), h: size * (0.55 + r() * 0.75) * (1 - Math.abs(f - 0.5) * 0.9), ph: r() * TAU });
    }
    const layer = (scale, color) => {
      ctx.fillStyle = color;
      for (const t of tongues) {
        const hh = t.h * scale * grow * (0.86 + 0.14 * Math.sin(time * 9 + t.ph));
        const tip = t.bx + Math.sin(time * 6 + t.ph) * size * 0.06;
        const ww = t.w * (0.55 + 0.45 * scale);
        ctx.beginPath(); ctx.moveTo(t.bx - ww / 2, y);
        ctx.quadraticCurveTo(t.bx - ww * 0.75, y - hh * 0.45, tip, y - hh);
        ctx.quadraticCurveTo(t.bx + ww * 0.75, y - hh * 0.45, t.bx + ww / 2, y);
        ctx.closePath(); ctx.fill();
      }
    };
    fx.cutout(() => layer(1, pal.vermilion), { lift: 0.5 });
    layer(0.72, pal.mustard);
    layer(0.4, '#FFF6DF');
    for (let i = 0; i < 6; i++) {
      const life = wrap(time * 0.6 + i / 6, 1);
      circle(x + (r() - 0.5) * size * 0.8 + Math.sin(time * 3 + i) * size * 0.05, y - size * (0.4 + life * 1.2), size * 0.018 * (1 - life), pal.mustard);
    }
  }

  // ---------- settings ----------
  // An indoor room: wall and floor. o: {floor (y), backdrop: 'panel' | 'curtain' | 'windows' | null, wall, time}
  function room(o = {}) {
    const fl = o.floor ?? H * 0.8;
    rect(-W, -H, W * 3, fl + H, o.wall || '#E4DCC8');
    ctx.save(); ctx.strokeStyle = 'rgba(26,42,134,0.07)'; ctx.lineWidth = 2 * u;
    for (let x = -W; x < 2 * W; x += 60 * u) { ctx.beginPath(); ctx.moveTo(x, -H); ctx.lineTo(x, fl); ctx.stroke(); }
    ctx.restore();
    if (o.backdrop === 'panel') {
      const pw = W * 0.76, ph = fl * 0.86, px = W / 2 - pw / 2, py = fl - ph;
      fx.cutout(() => rect(px, py, pw, ph, '#2F4AA8'), { lift: 0.5 });
      ctx.save(); ctx.globalAlpha = 0.22; ctx.strokeStyle = pal.paper; ctx.lineWidth = 3 * u;
      for (let gx = px + 50 * u; gx < px + pw; gx += 100 * u) for (let gy = py + 45 * u; gy < fl; gy += 90 * u) { ctx.beginPath(); ctx.arc(gx, gy, 16 * u, 0, TAU); ctx.stroke(); }
      ctx.restore();
    } else if (o.backdrop === 'curtain') {
      for (let x = -W, i = 0; x < 2 * W; x += 34 * u, i++) rect(x, -H, 34 * u, fl + H, i % 2 ? '#B5401F' : '#C9512E');
    } else if (o.backdrop === 'windows') {
      for (const wx of [W * 0.12, W * 0.56]) {
        fx.cutout(() => { rect(wx, fl * 0.12, W * 0.32, fl * 0.56, '#F7F3E8'); rect(wx + 8 * u, fl * 0.12 + 8 * u, W * 0.32 - 16 * u, fl * 0.56 - 16 * u, pal.sky); }, { lift: 0.4 });
        rect(wx + W * 0.16 - 3 * u, fl * 0.12, 6 * u, fl * 0.56, '#F7F3E8'); rect(wx, fl * 0.4 - 3 * u, W * 0.32, 6 * u, '#F7F3E8');
      }
    }
    rect(-W, fl, W * 3, H * 2, o.floorColor || '#B89F78');
    rect(-W, fl, W * 3, 6 * u, '#8F7856');
    ctx.save(); ctx.strokeStyle = 'rgba(80,60,30,0.18)'; ctx.lineWidth = 2 * u;
    for (let y = fl + 22 * u, i = 1; y < H * 2; y += 22 * u * (1 + i * 0.25), i++) { ctx.beginPath(); ctx.moveTo(-W, y); ctx.lineTo(2 * W, y); ctx.stroke(); }
    ctx.restore();
    return { floor: fl };
  }

  // A city street: sky, a row of buildings, a pavement and the road. o: {ground (y of the pavement), time, seed}
  function street(o = {}) {
    const g = o.ground ?? H * 0.74, time = o.time ?? 0, r = rng(o.seed ?? 23);
    scene.sky({ horizon: g, time, clouds: o.clouds ?? 2 });
    ctx.save(); ctx.globalAlpha = 0.55;
    for (let x = -W * 0.2; x < W * 1.2;) { const w = (50 + r() * 70) * u, h = H * (0.25 + r() * 0.3); rect(x, g - h, w, h, '#8FA6C8'); x += w + 6 * u; }
    ctx.restore();
    const FRONT = ['#E2D3B5', '#D98E5F', '#C9B79A', '#9FB3D6', '#E0A86A', '#B8C2A0'];
    for (let x = -W * 0.2; x < W * 1.2;) {
      const w = (80 + r() * 90) * u, h = H * (0.22 + r() * 0.3), c = FRONT[Math.floor(r() * FRONT.length)];
      fx.cutout(() => {
        rect(x, g - h, w, h, c);
        rect(x - 3 * u, g - h - 6 * u, w + 6 * u, 8 * u, 'rgba(26,42,134,0.25)');
        for (let wy = g - h + 16 * u; wy < g - 34 * u; wy += 30 * u) for (let wx = x + 12 * u; wx < x + w - 20 * u; wx += 26 * u) rect(wx, wy, 13 * u, 17 * u, r() < 0.15 ? '#F0D58A' : '#3B4466', 2 * u);
      }, { lift: 0.5 });
      x += w + (4 + r() * 10) * u;
    }
    rect(-W, g, W * 3, H * 0.07, '#D8CDB4');
    rect(-W, g + H * 0.07, W * 3, 5 * u, '#A99D84');
    rect(-W, g + H * 0.07 + 5 * u, W * 3, H * 2, '#454C6B');
    ctx.save(); ctx.strokeStyle = 'rgba(243,238,225,0.75)'; ctx.lineWidth = 5 * u; ctx.setLineDash([40 * u, 34 * u]);
    ctx.beginPath(); ctx.moveTo(-W, g + H * 0.18); ctx.lineTo(2 * W, g + H * 0.18); ctx.stroke(); ctx.restore();
    return { ground: g + H * 0.035, road: g + H * 0.15 };
  }

  return {
    fx: Object.freeze(Object.assign({}, fx, { fire })),
    scene: Object.freeze(Object.assign({}, scene, { person, crowd, podium, microphone, table, government, room, street })),
  };
});
