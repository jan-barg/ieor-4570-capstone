// Scene kit, part 3 (Nov 27, test-only): the next ten most-needed pieces (analysis/props/match_library.json), minus the
// two people kinds that live in kit_scene2.js (diplomat, lawyer): a fighter jet, a building (office, apartment, house),
// an oil refinery, a computer (laptop, desktop, server), an airport with a side-view airliner, a military base, a
// warship, an ambulance, and a plain outdoor setting (ground: grass, plaza or sand) for buildings that stand alone.
// All generic: no markings, no flags, no emblems. Needs kit_fx.js, kit_scene.js and kit_scene2.js first. Window pixels.
KIT_EXT.push(function (k) {
  const { ctx, W, H, pal, rng, clamp01, fx, scene } = k;
  const TAU = Math.PI * 2;
  const u = fx.unit;
  const INK = pal.ink;
  const PANE = '#3B4466', LIT = '#F0D58A', GLASS = '#2B3A66';

  const rect = (x, y, w, h, c, r = 0) => { ctx.fillStyle = c; ctx.beginPath(); if (r) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h); ctx.fill(); };
  const circle = (x, y, r, c) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x, y, Math.max(0, r), 0, TAU); ctx.fill(); };
  const poly = (pts, c) => { ctx.fillStyle = c; ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill(); };
  const line = (pts, w, c) => { ctx.strokeStyle = c; ctx.lineWidth = w; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); };
  const withAlpha = (o, fn) => { ctx.save(); if (o.alpha != null) ctx.globalAlpha *= clamp01(o.alpha); fn(); ctx.restore(); };

  // ---------- aircraft ----------
  // A generic fighter jet in side view, nose along `angle` (radians, 0 = right). size = length in px.
  // o: {angle, time, afterburner (true by default), flip, alpha}
  function fighterJet(x, y, size, o = {}) {
    const s = size / 100, time = o.time ?? 0;
    withAlpha(o, () => {
      ctx.translate(x, y); ctx.rotate(o.angle ?? 0); ctx.scale(o.flip ? -s : s, s);
      if (o.afterburner !== false) {
        const f = 1 + 0.22 * Math.sin(time * 41) + 0.12 * Math.sin(time * 77);
        poly([[-53, -4], [-53 - 28 * f, 0], [-53, 4]], pal.mustard);
        poly([[-53, -2.5], [-53 - 14 * f, 0], [-53, 2.5]], '#FFF6DF');
      }
      fx.cutout(() => {
        ctx.strokeStyle = INK; ctx.lineWidth = 2 / s * u; ctx.lineJoin = 'round';
        const shape = (pts, c) => { poly(pts, c); ctx.stroke(); };
        shape([[-30, -5], [-47, -5], [-52, -25], [-43, -25]], '#8E97AA');                 // tail fin
        shape([[12, 2], [-30, 2], [-40, 11], [-26, 11]], '#7D879B');                       // swept wing
        ctx.fillStyle = '#A3ABBC'; ctx.beginPath();                                       // fuselage, pointed nose
        ctx.moveTo(-50, -5); ctx.lineTo(18, -6); ctx.quadraticCurveTo(40, -5, 56, 1); ctx.quadraticCurveTo(38, 5, 18, 5); ctx.lineTo(-50, 5); ctx.closePath(); ctx.fill(); ctx.stroke();
        shape([[-38, 2], [-52, 2], [-56, 8], [-47, 8]], '#7D879B');                        // tailplane
        rect(-55, -4, 6, 8, '#5A6070', 1);                                               // nozzle
        poly([[4, 0], [14, -1], [14, 4], [6, 4]], '#4A5266');                              // intake
        ctx.fillStyle = GLASS; ctx.beginPath(); ctx.ellipse(26, -6, 11, 4.5, -0.05, Math.PI, TAU); ctx.fill(); ctx.stroke();
        ctx.fillStyle = 'rgba(168,201,234,0.7)'; ctx.beginPath(); ctx.ellipse(28, -8, 4, 1.4, -0.1, 0, TAU); ctx.fill();
      }, { lift: 1.6 });
    });
  }

  // A passenger airliner in side view, nose along `angle` (0 = right); size = length in px; y is the fuselage centre.
  // o: {angle, time, flip, gear (wheels down: true when parked or landing), tail (fin colour), alpha}
  function airliner(x, y, size, o = {}) {
    const s = size / 100;
    withAlpha(o, () => {
      ctx.translate(x, y); ctx.rotate(o.angle ?? 0); ctx.scale(o.flip ? -s : s, s);
      fx.cutout(() => {
        ctx.strokeStyle = INK; ctx.lineWidth = 1.8 / s * u; ctx.lineJoin = 'round';
        poly([[-32, -7], [-46, -7], [-54, -31], [-45, -31]], o.tail || pal.cobalt); ctx.stroke();      // fin
        poly([[8, 2], [-14, 2], [-26, 13], [-15, 13]], '#C9CCD6'); ctx.stroke();                      // far wing
        if (o.gear) {
          line([[30, 6], [30, 12]], 2.2, '#4A5266'); line([[-8, 6], [-8, 12]], 2.6, '#4A5266');
          circle(30, 13.5, 2.6, '#22233A'); circle(-10, 13.5, 3, '#22233A'); circle(-6, 13.5, 3, '#22233A');
        }
        ctx.fillStyle = '#F7F3E8'; ctx.beginPath();                                                  // fuselage
        ctx.moveTo(-46, -7); ctx.lineTo(36, -7); ctx.quadraticCurveTo(50, -6, 52, 1); ctx.quadraticCurveTo(50, 7, 36, 7);
        ctx.lineTo(-36, 7); ctx.quadraticCurveTo(-48, 5, -53, -4); ctx.closePath(); ctx.fill(); ctx.stroke();
        rect(-44, 1.5, 88, 2.4, pal.cobalt);                                                         // cheat line
        for (let px = -38; px < 32; px += 4.6) circle(px, -2.2, 1.15, PANE);                         // passenger panes
        poly([[41, -5], [47, -3.2], [46, -1.2], [40, -2]], GLASS);                                    // cockpit
        poly([[-38, -1], [-51, -1], [-57, 3], [-48, 3]], '#C9CCD6'); ctx.stroke();                    // tailplane
        ctx.fillStyle = '#B9BFCF'; ctx.beginPath(); ctx.roundRect(-8, 7.5, 17, 7, 3.5); ctx.fill(); ctx.stroke();   // engine
        circle(8.5, 11, 2.6, '#4A5266');
      }, { lift: 1.3 });
    });
  }

  // ---------- buildings ----------
  // One building standing on the ground at y, centred on x. o: {kind: 'office' (glass tower) | 'apartment' | 'house',
  // color, roof (house), seed, lit (share of lit panes, 0..1)}. height defaults by kind. Returns {top, left, right, door,
  // roof: {x, y, w} and front: {x, y, w, h} (where an effect that happens TO the building goes)}.
  function building(x, y, width, height, o = {}) {
    const kind = o.kind || 'office', r = rng(o.seed ?? 31), w = width, lit = o.lit ?? 0.15;
    const h = height ?? (kind === 'house' ? w * 0.85 : kind === 'apartment' ? w * 1.25 : w * 2.2);
    const left = x - w / 2, top = y - h;
    // roof: the line along the roof, front: the facade (y its middle), for an effect that happens TO the building
    const on = (roofY, wallTop) => ({ roof: { x, y: roofY, w }, front: { x, y: (wallTop + y) / 2, w, h: y - wallTop } });
    if (kind === 'house') {
      const wallH = h * 0.58;
      fx.cutout(() => {
        rect(left + w * 0.64, top + h * 0.1, w * 0.1, h * 0.3, '#8E4A3A');                      // chimney
        rect(left, y - wallH, w, wallH, o.color || '#E2D3B5');
        poly([[left - w * 0.08, y - wallH + 2 * u], [x, top], [left + w * 1.08, y - wallH + 2 * u]], o.roof || '#B5401F');
        rect(x - w * 0.09, y - wallH * 0.56, w * 0.18, wallH * 0.56, '#6B4A32', 2 * u);          // door
        circle(x + w * 0.05, y - wallH * 0.28, w * 0.012, pal.mustard);
        for (const px of [left + w * 0.1, left + w * 0.7]) {
          rect(px, y - wallH * 0.78, w * 0.2, wallH * 0.34, '#F7F3E8');
          rect(px + w * 0.015, y - wallH * 0.78 + w * 0.015, w * 0.17, wallH * 0.34 - w * 0.03, r() < lit * 2 ? LIT : PANE);
        }
      }, { lift: 0.6 });
      return { top, left, right: left + w, door: { x, y }, ...on(y - wallH, y - wallH) };
    }
    if (kind === 'apartment') {
      const c = o.color || ['#D98E5F', '#C9B79A', '#E0A86A', '#B8C2A0'][Math.floor(r() * 4)];
      const cols = Math.max(3, Math.round(w / (38 * u))), rows = Math.max(3, Math.round(h / (44 * u)));
      const cw = w * 0.84 / cols, rh = (h * 0.86) / rows;
      fx.cutout(() => {
        rect(left, top, w, h, c);
        rect(left - w * 0.03, top - 6 * u, w * 1.06, 8 * u, 'rgba(26,42,134,0.3)');
        for (let j = 0; j < rows - 1; j++) for (let i = 0; i < cols; i++) {
          const px = left + w * 0.08 + i * cw + cw * 0.18, py = top + h * 0.05 + j * rh + rh * 0.15;
          rect(px, py, cw * 0.64, rh * 0.52, r() < lit ? LIT : PANE, 2 * u);
          if (j % 2 === 1) rect(px - cw * 0.08, py + rh * 0.52, cw * 0.8, rh * 0.09, '#F3EEE1');   // balcony rail
        }
        rect(x - w * 0.1, y - rh * 0.8, w * 0.2, rh * 0.8, '#3B3F4E', 2 * u);
      }, { lift: 0.6 });
      return { top, left, right: left + w, door: { x, y }, ...on(top, top) };
    }
    const c = o.color || '#9FB3D6';                                                              // office tower
    const band = Math.max(14 * u, h / 20);
    fx.cutout(() => {
      rect(left, top, w, h, c);
      rect(left + w * 0.88, top, w * 0.12, h, 'rgba(26,42,134,0.18)');
      rect(left - w * 0.03, top - h * 0.025, w * 1.06, h * 0.03, '#5E6E8F');
      rect(x - w * 0.04, top - h * 0.08, w * 0.02, h * 0.06, '#5E6E8F');                         // roof antenna
      for (let yy = top + h * 0.04; yy < y - h * 0.1; yy += band) {
        rect(left + w * 0.07, yy, w * 0.86, band * 0.58, GLASS);
        for (let xx = left + w * 0.07; xx < left + w * 0.92; xx += w * 0.143) if (r() < lit) rect(xx + 2 * u, yy + 2 * u, w * 0.13, band * 0.58 - 4 * u, LIT);
        for (let xx = left + w * 0.07 + w * 0.143; xx < left + w * 0.92; xx += w * 0.143) rect(xx - u, yy, 2 * u, band * 0.58, c);
      }
      rect(x - w * 0.16, y - h * 0.08, w * 0.32, h * 0.08, '#22233A', 2 * u);
    }, { lift: 0.6 });
    return { top: top - h * 0.08, left, right: left + w, door: { x, y }, ...on(top, top) };
  }

  // An oil refinery on the ground at y, centred on x: storage tanks, distillation towers, a pipe rack and a flare stack.
  // o: {time, flare (0..1, the flare's flame; 1 by default)}. Returns {flare: {x, y}, tanks: {x, y}, top, left, right}.
  function refinery(x, y, width, o = {}) {
    const w = width, left = x - w / 2, time = o.time ?? 0;
    const STEEL = '#C9CCD6', DARK = '#7D879B';
    const fl = { x: left + w * 0.92, y: y - w * 0.72 };
    fx.cutout(() => {
      rect(fl.x - w * 0.012, fl.y, w * 0.024, y - fl.y, '#8A8FA3');                              // flare stack
      for (let i = 0; i < 3; i++) rect(fl.x - w * 0.014, fl.y + w * (0.02 + i * 0.05), w * 0.028, w * 0.025, i % 2 ? pal.paper : pal.vermilion);
      line([[fl.x - w * 0.05, y], [fl.x, fl.y + w * 0.3], [fl.x + w * 0.05, y]], w * 0.005, '#8A8FA3');
      [[0.42, 0.62, 0.07], [0.53, 0.46, 0.055], [0.62, 0.68, 0.05]].forEach(([fx_, th, tw]) => {    // towers
        const cx = left + w * fx_, tt = y - w * th;
        rect(cx - w * tw / 2, tt, w * tw, w * th, STEEL, w * 0.01);
        rect(cx - w * tw / 2, tt, w * tw * 0.3, w * th, 'rgba(26,42,134,0.12)');
        for (let yy = tt + w * 0.05; yy < y - w * 0.03; yy += w * 0.07) rect(cx - w * tw * 0.58, yy, w * tw * 1.16, w * 0.01, DARK);
        line([[cx + w * tw * 0.62, tt + w * 0.03], [cx + w * tw * 0.62, y]], w * 0.004, DARK);
        rect(cx - w * 0.005, tt - w * 0.05, w * 0.01, w * 0.05, DARK);
      });
      for (const yy of [y - w * 0.16, y - w * 0.11]) rect(left + w * 0.3, yy, w * 0.6, w * 0.012, DARK);   // pipe rack
      for (let i = 0; i < 6; i++) rect(left + w * (0.32 + i * 0.11), y - w * 0.16, w * 0.01, w * 0.16, '#6B7286');
    }, { lift: 0.7 });
    fx.fire(fl.x, fl.y + w * 0.01, w * 0.07, { time, t: o.flare ?? 1, seed: 17, tongues: 5 });
    fx.cutout(() => {                                                                              // tanks in front
      [[0.07, 0.15, 0.17], [0.24, 0.12, 0.15]].forEach(([fx_, th, tw]) => {
        const cx = left + w * fx_, tt = y - w * th, rw = w * tw / 2;
        rect(cx - rw, tt, rw * 2, w * th, '#E9E2CF');
        rect(cx - rw, tt, rw * 0.4, w * th, 'rgba(26,42,134,0.1)');
        rect(cx - rw, tt + w * th * 0.3, rw * 2, w * 0.012, pal.vermilion);
        ctx.fillStyle = '#F7F3E8'; ctx.beginPath(); ctx.ellipse(cx, tt, rw, w * 0.018, 0, 0, TAU); ctx.fill();
        line([[cx - rw * 0.7, tt + w * 0.01], [cx - rw * 0.3, y]], w * 0.004, DARK);               // stair
      });
    }, { lift: 0.6 });
    return { flare: fl, tanks: { x: left + w * 0.15, y: y - w * 0.15 }, top: fl.y - w * 0.1, left, right: left + w };
  }

  // ---------- things ----------
  // A computer. o.kind: 'laptop' (y = the desk under it, size = width), 'desktop' (monitor and keyboard on the desk at y),
  // 'server' (a rack standing on the floor at y, size = width, about 2.2 x size tall, with blinking lights).
  // o: {time, glow (0..1, how bright the screen is)}. Screens are blank. Returns {screen: {x, y, w, h}, top}.
  function computer(x, y, size, o = {}) {
    const kind = o.kind || 'laptop', time = o.time ?? 0, glow = clamp01(o.glow ?? 1), s = size;
    const screenFace = (sx, sy, sw, sh) => {
      rect(sx, sy, sw, sh, GLASS, 2 * u);
      ctx.save(); ctx.globalAlpha *= 0.25 + 0.5 * glow; rect(sx, sy, sw, sh * 0.45, pal.cobalt, 2 * u); ctx.restore();
      if (Math.sin(time * 6) > 0) rect(sx + sw * 0.1, sy + sh * 0.72, sw * 0.06, sh * 0.06, pal.mustard);   // blinking cursor
      return { x: sx, y: sy, w: sw, h: sh };
    };
    let screen = null, top = y;
    if (kind === 'server') {
      const h = s * 2.2;
      top = y - h;
      fx.cutout(() => {
        rect(x - s / 2, top, s, h, '#2C2C3A', 3 * u);
        rect(x - s * 0.44, top + s * 0.06, s * 0.88, h - s * 0.12, '#22233A', 2 * u);
        const units = 11, uh = (h - s * 0.16) / units;
        for (let i = 0; i < units; i++) {
          const uy = top + s * 0.08 + i * uh;
          rect(x - s * 0.4, uy + uh * 0.1, s * 0.8, uh * 0.8, '#3B3F4E', 2 * u);
          for (let v = 0; v < 4; v++) rect(x - s * 0.34 + v * s * 0.07, uy + uh * 0.3, s * 0.04, uh * 0.4, '#2C2C3A');
          for (let j = 0; j < 3; j++) {
            const on = Math.sin(time * (5 + j * 2.3) + i * 1.7 + j * 2.1) > 0.15;
            circle(x + s * (0.18 + j * 0.08), uy + uh * 0.5, Math.max(1.5 * u, uh * 0.13), on ? (j === 2 && i % 4 === 1 ? pal.mustard : '#5FD17A') : '#2E4A3A');
          }
        }
      }, { lift: 0.6 });
      return { screen: null, top };
    }
    if (kind === 'desktop') {
      const mw = s, mh = s * 0.6, my = y - s * 0.13 - mh;
      top = my;
      fx.cutout(() => {
        rect(x - s * 0.04, y - s * 0.14, s * 0.08, s * 0.12, '#3B3F4E');
        ctx.fillStyle = '#3B3F4E'; ctx.beginPath(); ctx.ellipse(x, y - s * 0.02, s * 0.16, s * 0.025, 0, 0, TAU); ctx.fill();
        rect(x - mw / 2, my, mw, mh, '#2C2C3A', 4 * u);
        screen = screenFace(x - mw / 2 + s * 0.035, my + s * 0.035, mw - s * 0.07, mh - s * 0.07);
      }, { lift: 0.6 });
      fx.cutout(() => {
        rect(x - s * 0.42 + s * 0.6, y - s * 0.035, s * 0.36, s * 0.035, '#C9CCD6', 2 * u);
        for (let i = 0; i < 9; i++) rect(x + s * 0.2 + i * s * 0.037, y - s * 0.028, s * 0.026, s * 0.01, '#9AA3B5');
      }, { lift: 0.3 });
      return { screen, top };
    }
    const lh = s * 0.62, ly = y - s * 0.05 - lh;                                                  // laptop
    top = ly;
    fx.cutout(() => {
      rect(x - s * 0.42, ly, s * 0.84, lh, '#3B3F4E', 4 * u);
      screen = screenFace(x - s * 0.385, ly + s * 0.035, s * 0.77, lh - s * 0.07);
      poly([[x - s / 2, y], [x + s / 2, y], [x + s * 0.44, y - s * 0.05], [x - s * 0.44, y - s * 0.05]], '#B9BFCF');
      rect(x - s * 0.1, y - s * 0.02, s * 0.2, s * 0.012, '#9AA3B5');
    }, { lift: 0.6 });
    return { screen, top };
  }

  // An airport on the ground at y, centred on x: a terminal, a control tower, the apron in front and a parked airliner.
  // o: {time, plane (false: no parked plane)}. Returns {tower: {x, y}, gate: {x, y}, apron (y of the apron's middle), top}.
  function airport(x, y, width, o = {}) {
    const w = width, left = x - w / 2, time = o.time ?? 0, tx = left + w * 0.86;
    rect(left - w * 0.3, y, w * 1.6, w * 0.13, '#6E7489');                                        // apron
    ctx.save(); ctx.strokeStyle = pal.mustard; ctx.lineWidth = 3 * u; ctx.setLineDash([18 * u, 14 * u]);
    ctx.beginPath(); ctx.moveTo(left - w * 0.3, y + w * 0.09); ctx.lineTo(left + w * 1.3, y + w * 0.09); ctx.stroke(); ctx.restore();
    fx.cutout(() => {
      rect(tx - w * 0.022, y - w * 0.42, w * 0.044, w * 0.42, '#E9E2CF');                         // control tower
      rect(tx - w * 0.022, y - w * 0.42, w * 0.012, w * 0.42, 'rgba(26,42,134,0.12)');
      poly([[tx - w * 0.05, y - w * 0.42], [tx + w * 0.05, y - w * 0.42], [tx + w * 0.068, y - w * 0.5], [tx - w * 0.068, y - w * 0.5]], GLASS);
      for (let i = -2; i <= 2; i++) line([[tx + i * w * 0.022, y - w * 0.42], [tx + i * w * 0.028, y - w * 0.5]], 1.6 * u, '#E9E2CF');
      rect(tx - w * 0.075, y - w * 0.52, w * 0.15, w * 0.022, '#E9E2CF', 2 * u);
      line([[tx, y - w * 0.52], [tx, y - w * 0.57]], 2 * u, '#8A8FA3');
      if (Math.sin(time * 4) > 0) circle(tx, y - w * 0.575, 3.5 * u, pal.vermilion);
      rect(left + w * 0.02, y - w * 0.14, w * 0.68, w * 0.14, '#E9E2CF');                          // terminal
      rect(left + w * 0.04, y - w * 0.115, w * 0.64, w * 0.08, '#9FB3D6');
      for (let xx = left + w * 0.04; xx <= left + w * 0.68; xx += w * 0.04) rect(xx - u, y - w * 0.115, 2 * u, w * 0.08, '#E9E2CF');
      ctx.fillStyle = '#C9CCD6'; ctx.beginPath(); ctx.moveTo(left, y - w * 0.14);
      ctx.quadraticCurveTo(left + w * 0.36, y - w * 0.22, left + w * 0.72, y - w * 0.14); ctx.closePath(); ctx.fill();
      rect(left + w * 0.5, y - w * 0.06, w * 0.12, w * 0.025, '#C9CCD6');                          // jet bridge
    }, { lift: 0.6 });
    if (o.plane !== false) airliner(left + w * 0.38, y + w * 0.075 - w * 0.4 * 0.135, w * 0.4, { gear: true, time });
    return { tower: { x: tx, y: y - w * 0.52 }, gate: { x: left + w * 0.56, y }, apron: y + w * 0.065, top: y - w * 0.58 };
  }

  // A military base on the ground at y, centred on x: an arched hangar, barracks, a watchtower, a radar dome, and a
  // fence with a gate barrier in front. o: {time, open (0..1, the gate barrier lifting)}.
  // Returns {hangar: {x, y}, tower: {x, y}, gate: {x, y}, top}.
  function militaryBase(x, y, width, o = {}) {
    const w = width, left = x - w / 2, time = o.time ?? 0;
    const OLIVE = '#5A6640', OLIVE_D = '#4E5937', SAND = '#C9B98E';
    const hx = left + w * 0.32, hw = w * 0.38, hh = w * 0.19;
    const wt = { x: left + w * 0.06, y: y - w * 0.26 };
    const rd = { x: left + w * 0.9, y: y - w * 0.12 };
    fx.cutout(() => {
      for (const dx of [-1, 1]) line([[wt.x + dx * w * 0.03, y], [wt.x + dx * w * 0.018, wt.y]], 2.5 * u, '#6B6A55');   // watchtower
      line([[wt.x - w * 0.028, y - w * 0.08], [wt.x + w * 0.024, wt.y + w * 0.04]], 1.6 * u, '#6B6A55');
      rect(wt.x - w * 0.035, wt.y - w * 0.05, w * 0.07, w * 0.05, OLIVE_D);
      rect(wt.x - w * 0.025, wt.y - w * 0.042, w * 0.05, w * 0.022, GLASS);
      poly([[wt.x - w * 0.045, wt.y - w * 0.05], [wt.x, wt.y - w * 0.075], [wt.x + w * 0.045, wt.y - w * 0.05]], OLIVE);
      ctx.fillStyle = OLIVE; ctx.beginPath(); ctx.ellipse(hx, y, hw / 2, hh, 0, Math.PI, TAU); ctx.fill();   // hangar
      ctx.strokeStyle = OLIVE_D; ctx.lineWidth = 2 * u;
      for (let i = 1; i < 6; i++) { ctx.beginPath(); ctx.ellipse(hx, y, hw / 2 * (1 - i * 0.0), hh * (1 - i * 0.14), 0, Math.PI, TAU); ctx.stroke(); }
      ctx.fillStyle = '#2E3420'; ctx.beginPath(); ctx.ellipse(hx, y, hw * 0.3, hh * 0.62, 0, Math.PI, TAU); ctx.fill();
      rect(left + w * 0.55, y - w * 0.085, w * 0.27, w * 0.085, SAND);                             // barracks
      rect(left + w * 0.54, y - w * 0.1, w * 0.29, w * 0.018, OLIVE_D);
      for (let i = 0; i < 5; i++) rect(left + w * (0.57 + i * 0.05), y - w * 0.065, w * 0.025, w * 0.025, PANE, u);
      rect(rd.x - w * 0.035, rd.y + w * 0.04, w * 0.07, y - rd.y - w * 0.04, SAND);                 // radar dome
      circle(rd.x, rd.y, w * 0.055, '#F1EADB');
      ctx.strokeStyle = '#D9CFB8'; ctx.lineWidth = 1.5 * u;
      for (const a of [-0.5, 0, 0.5]) { ctx.beginPath(); ctx.ellipse(rd.x, rd.y, w * 0.055 * Math.abs(Math.cos(a + time * 0.0)), w * 0.055, 0, 0, TAU); ctx.stroke(); }
      const dish = Math.cos(time * 1.6);                                                            // turning dish on the barracks
      line([[left + w * 0.78, y - w * 0.1], [left + w * 0.78, y - w * 0.14]], 2 * u, '#6B6A55');
      ctx.fillStyle = '#E9E2CF'; ctx.beginPath(); ctx.ellipse(left + w * 0.78, y - w * 0.155, Math.max(1, w * 0.03 * Math.abs(dish)), w * 0.02, 0, 0, TAU); ctx.fill();
    }, { lift: 0.6 });
    const gx = x + w * 0.02, gw = w * 0.1, lift = clamp01(o.open ?? 0);
    ctx.save(); ctx.strokeStyle = 'rgba(70,74,90,0.75)'; ctx.lineWidth = 1.4 * u;                 // fence
    for (const yy of [y - w * 0.055, y - w * 0.035, y - w * 0.015]) {
      ctx.beginPath(); ctx.moveTo(left - w * 0.05, yy); ctx.lineTo(gx - gw / 2, yy); ctx.moveTo(gx + gw / 2, yy); ctx.lineTo(left + w * 1.05, yy); ctx.stroke();
    }
    ctx.globalAlpha *= 0.35;
    for (let xx = left - w * 0.05; xx < left + w * 1.05; xx += w * 0.014) {
      if (xx > gx - gw / 2 && xx < gx + gw / 2) continue;
      ctx.beginPath(); ctx.moveTo(xx, y - w * 0.06); ctx.lineTo(xx + w * 0.014, y); ctx.moveTo(xx + w * 0.014, y - w * 0.06); ctx.lineTo(xx, y); ctx.stroke();
    }
    ctx.restore();
    fx.cutout(() => {
      for (let xx = left - w * 0.05; xx <= left + w * 1.05; xx += w * 0.07) if (xx < gx - gw / 2 || xx > gx + gw / 2) rect(xx - 1.5 * u, y - w * 0.07, 3 * u, w * 0.07, '#6B7286');
      rect(gx - gw / 2 - 4 * u, y - w * 0.06, 8 * u, w * 0.06, '#5A6070');
      ctx.save(); ctx.translate(gx - gw / 2, y - w * 0.045); ctx.rotate(-lift * 1.3);
      for (let i = 0; i < 6; i++) rect(i * gw / 6, -2.5 * u, gw / 6, 5 * u, i % 2 ? pal.paper : pal.vermilion);
      ctx.restore();
    }, { lift: 0.4 });
    return { hangar: { x: hx, y: y - hh * 0.3 }, tower: wt, gate: { x: gx, y }, top: y - Math.max(hh, w * 0.34) };
  }

  // A generic grey warship in side view, bobbing; size = length in px; its waterline sits at y. o: {time, flip, alpha}
  // Returns {gun: {x, y} (the forward gun's muzzle), mast: {x, y}, deck (y)} in window pixels.
  function warship(x, y, size, o = {}) {
    const s = size / 100, time = o.time ?? 0, f = o.flip ? -1 : 1;
    const bob = Math.sin(time * 2) * 1.5 * u, rot = Math.sin(time * 1.5) * 0.01;
    const HULL = '#7D879B', TOP = '#9AA3B5', DARK = '#5A6070';
    withAlpha(o, () => {
      ctx.translate(x, y + bob); ctx.rotate(rot); ctx.scale(f * s, s);
      fx.cutout(() => {
        line([[-2, -30], [-2, -50]], 1.6, DARK);                                                    // mast and radar
        line([[-8, -44], [4, -44]], 1.4, DARK);
        const spin = Math.cos(time * 3);
        rect(-2 - 6 * Math.abs(spin), -53, 12 * Math.abs(spin) + 0.5, 2.5, DARK);
        rect(-30, -18, 9, 12, '#6B7286', 1);                                                       // funnel
        rect(-31, -19, 11, 2.5, DARK);
        rect(-20, -20, 32, 14, TOP, 1);                                                             // superstructure
        rect(-13, -30, 20, 10, TOP, 1);
        for (let i = 0; i < 5; i++) rect(-11 + i * 3.8, -27.5, 2.4, 2.2, GLASS);
        rect(20, -12, 10, 6, TOP, 2);                                                               // forward gun
        line([[28, -10], [44, -12.5]], 1.6, DARK);
        rect(-44, -11, 7, 5, TOP, 1.5);                                                             // aft gun
        line([[-44, -9], [-52, -10]], 1.3, DARK);
        poly([[-50, -6], [53, -9], [44, 6], [-46, 6]], HULL);                                       // hull
        poly([[-47.5, 2.5], [46.5, 2.5], [44, 6], [-46, 6]], DARK);
        rect(-48, -7, 98, 1.2, '#B9BFCF');
      }, { lift: 0.8 });
    });
    const T = (lx, ly) => ({ x: x + f * s * (lx * Math.cos(rot) - ly * Math.sin(rot)), y: y + bob + s * (lx * Math.sin(rot) + ly * Math.cos(rot)) });
    return { gun: T(44, -12.5), mast: T(-2, -50), deck: y + bob - 7 * s };
  }

  // A generic ambulance in side view, wheels on the ground at y; size = length in px. o: {time, lights (true: the light bar
  // flashes), moving (wheels turn and the body rocks), facing (1 right, -1 left), alpha}. No emblem.
  // Returns {top, back: {x, y}} (the rear doors) in window pixels.
  function ambulance(x, y, size, o = {}) {
    const s = size / 100, time = o.time ?? 0, f = o.facing ?? 1;
    const rock = o.moving ? Math.sin(time * 18) * 0.5 : 0;
    withAlpha(o, () => {
      ctx.translate(x, y); ctx.scale(f * s, s);
      ctx.save(); ctx.translate(0, rock);
      fx.cutout(() => {
        rect(-50, -46, 70, 40, '#F7F3E8', 3);                                                     // box
        poly([[18, -36], [33, -36], [45, -20], [48, -10], [48, -6], [18, -6]], '#F7F3E8');          // cab
        poly([[23, -33], [32, -33], [41, -21], [23, -21]], GLASS);
        rect(-50, -27, 98, 4, pal.vermilion);
        for (let i = 0, xx = -50; xx < 47; i++, xx += 5) {                                         // checkered band
          rect(xx, -21, 5, 4, i % 2 ? pal.paper : pal.vermilion);
          rect(xx, -17, 5, 4, i % 2 ? pal.vermilion : pal.paper);
        }
        rect(-8, -41, 14, 10, GLASS, 1.5);
        line([[-49, -44], [-49, -8]], 0.8, 'rgba(26,42,134,0.35)');
        line([[20, -32], [20, -8]], 0.8, 'rgba(26,42,134,0.35)');
        rect(-52, -9, 103, 4, '#B9BFCF', 1.5);
        circle(46, -12, 1.8, pal.mustard);
        const on = o.lights !== false && Math.sin(time * 14) > 0;
        rect(-6, -50, 11, 4, on ? pal.cobalt : '#6E7FB8', 1);
        rect(5, -50, 11, 4, on ? '#A9B6E0' : pal.vermilion, 1);
      }, { lift: 0.8 });
      if (o.lights !== false) {
        const on = Math.sin(time * 14) > 0;
        ctx.save(); ctx.globalAlpha *= 0.35;
        circle(on ? -0.5 : 10.5, -48, 9, on ? pal.cobalt : pal.vermilion);
        ctx.restore();
      }
      ctx.restore();
      for (const wx of [-32, 32]) {                                                                // wheels
        circle(wx, -7, 8, '#22233A');
        circle(wx, -7, 3.6, '#B9BFCF');
        const a = o.moving ? time * 9 : 0;
        line([[wx + Math.cos(a) * 3.4, -7 + Math.sin(a) * 3.4], [wx - Math.cos(a) * 3.4, -7 - Math.sin(a) * 3.4]], 1, '#22233A');
      }
    });
    return { top: y - 50 * s, back: { x: x - f * 50 * s, y: y - 20 * s } };
  }

  // ---------- settings ----------
  // Open ground under a sky, for buildings and bases that stand alone (never put a building on the sea).
  // o: {ground (y of the horizon line where the ground starts), kind: 'grass' | 'plaza' | 'sand', time, seed, clouds}
  function ground(o = {}) {
    const g = o.ground ?? H * 0.72, kind = o.kind || 'grass', r = rng(o.seed ?? 41), time = o.time ?? 0;
    scene.sky({ horizon: g, time, clouds: o.clouds ?? 3, seed: o.seed });
    if (kind === 'grass') {
      ctx.save(); ctx.globalAlpha *= 0.7;
      ctx.fillStyle = '#7FAE72'; ctx.beginPath(); ctx.moveTo(-W, g + 2 * u);
      for (let xx = -W; xx <= 2 * W; xx += 60 * u) ctx.lineTo(xx, g - (14 + r() * 26) * u);
      ctx.lineTo(2 * W, g + 2 * u); ctx.closePath(); ctx.fill(); ctx.restore();
      rect(-W, g, W * 3, H * 2, '#6FA25E');
      for (let i = 1, yy = g + 14 * u; yy < H * 1.2; i++, yy += 14 * u * (1 + i * 0.35)) rect(-W, yy, W * 3, (3 + i) * u, '#62944F');
    } else if (kind === 'sand') {
      ctx.fillStyle = '#EAD7A8'; ctx.beginPath(); ctx.moveTo(-W, g + 2 * u);
      for (let xx = -W; xx <= 2 * W; xx += 90 * u) ctx.quadraticCurveTo(xx + 45 * u, g - (10 + r() * 22) * u, xx + 90 * u, g);
      ctx.lineTo(2 * W, g + 2 * u); ctx.closePath(); ctx.fill();
      rect(-W, g, W * 3, H * 2, '#E3C98E');
      ctx.save(); ctx.strokeStyle = 'rgba(150,110,50,0.25)'; ctx.lineWidth = 2 * u;
      for (let i = 0; i < 14; i++) { const yy = g + (H - g) * ((i + 0.5) / 14) ** 1.3, xx = r() * W; ctx.beginPath(); ctx.moveTo(xx - 40 * u, yy); ctx.quadraticCurveTo(xx, yy - 5 * u, xx + 40 * u, yy); ctx.stroke(); }
      ctx.restore();
    } else {
      ctx.save(); ctx.globalAlpha *= 0.45;                                                          // plaza: a faint city behind
      for (let xx = -W * 0.2; xx < W * 1.2;) { const bw = (50 + r() * 70) * u, bh = H * (0.12 + r() * 0.22); rect(xx, g - bh, bw, bh, '#8FA6C8'); xx += bw + 6 * u; }
      ctx.restore();
      rect(-W, g, W * 3, H * 2, '#D8CDB4');
      ctx.save(); ctx.strokeStyle = 'rgba(120,100,70,0.28)'; ctx.lineWidth = 2 * u;
      for (let i = 1, yy = g + 10 * u; yy < H * 1.2; i++, yy += 10 * u * (1 + i * 0.45)) { ctx.beginPath(); ctx.moveTo(-W, yy); ctx.lineTo(2 * W, yy); ctx.stroke(); }
      for (let i = -14; i <= 14; i++) { ctx.beginPath(); ctx.moveTo(W / 2 + i * 40 * u, g); ctx.lineTo(W / 2 + i * 160 * u, H * 1.2); ctx.stroke(); }
      ctx.restore();
    }
    rect(-W, g, W * 3, 3 * u, 'rgba(26,42,134,0.18)');
    return { ground: g };
  }

  return {
    scene: Object.freeze(Object.assign({}, scene, { fighterJet, airliner, building, refinery, computer, airport, militaryBase, warship, ambulance, ground })),
  };
});
