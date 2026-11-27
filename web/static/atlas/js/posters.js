// Posters for the made-up stories, drawn with the same map code as the page: paper sky with grain and the
// headline on top, the place's map below with its land lit warm and a vermilion pin (the video's hook frame).
// The real clips used as stand-in footage show other stories; these posters match the invented headlines.
(function () {
  'use strict';
  const A = window.Atlas;
  const cache = new Map();
  let fontsReady = null;

  function ready() {
    if (!fontsReady) {
      fontsReady = Promise.all([
        document.fonts.load('400 20px StringerSerif'), document.fonts.load('italic 400 20px StringerSerif'),
        document.fonts.load('600 10px StringerSans'), document.fonts.load('500 10px StringerSans'),
      ]).catch(() => null);
    }
    return fontsReady;
  }

  function wrap(ctx, text, maxW) {
    const words = String(text).split(/\s+/);
    const lines = [];
    let cur = '';
    for (const w of words) {
      const next = cur ? cur + ' ' + w : w;
      if (ctx.measureText(next).width <= maxW || !cur) cur = next; else { lines.push(cur); cur = w; }
    }
    if (cur) lines.push(cur);
    return lines;
  }

  function caps(ctx, text, x, y, size, color, align = 'left', spacing = 0.9) {
    ctx.font = `600 ${size}px StringerSans, sans-serif`;
    ctx.fillStyle = color;
    const t = String(text).toUpperCase();
    let w = 0;
    for (const ch of t) w += ctx.measureText(ch).width + spacing;
    let cx = align === 'right' ? x - w : x;
    for (const ch of t) { ctx.fillText(ch, cx, y); cx += ctx.measureText(ch).width + spacing; }
  }

  function pin(ctx, x, y, s) {
    ctx.fillStyle = A.PAL.paper;
    ctx.beginPath(); ctx.arc(x, y, 4.4 * s, 0, 6.2832); ctx.fill();
    ctx.fillStyle = A.PAL.vermilion;
    ctx.beginPath(); ctx.arc(x, y, 3.3 * s, 0, 6.2832); ctx.fill();
  }

  function label(ctx, text, x, y, size, right = true) {
    ctx.font = `italic 400 ${size}px StringerSerif, serif`;
    ctx.textAlign = right ? 'left' : 'right';
    ctx.lineJoin = 'round';
    ctx.lineWidth = size * 0.22;
    ctx.strokeStyle = 'rgba(26,42,134,0.6)';
    ctx.strokeText(text, x, y);
    ctx.fillStyle = A.PAL.paper;
    ctx.fillText(text, x, y);
    ctx.textAlign = 'left';
  }

  // kind: 'tag' (tiny, no words), 'thumb' (small, headline as ink bars), 'lead' (wide, real headline),
  // 'player' (9:16, real headline, the size of the video player)
  function make(it, kind, w, h) {
    const key = `${it.id}|${kind}|${w}x${h}`;
    if (cache.has(key)) return cache.get(key);
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const c = A.canvas(w * dpr, h * dpr);
    const ctx = c.getContext('2d');
    const W = A.data();
    // 'scene' is the video's map-locate shot: the place's name on the sky, its land lit below
    const words = kind === 'lead' || kind === 'player' || kind === 'scene';
    const headline = kind === 'scene' ? it.short : it.title;

    // headline band height
    let band = Math.round(h * (kind === 'lead' ? 0.42 : kind === 'scene' ? 0.2 : 0.36));
    let lines = [], size = 0;
    if (words) {
      size = kind === 'lead' ? Math.round(w * 0.066) : kind === 'scene' ? Math.round(Math.min(h * 0.12, w * 0.08)) : Math.round(w * 0.092);
      ctx.font = `400 ${size}px StringerSerif, serif`;
      const maxW = w * (kind === 'lead' ? 0.86 : 0.84);
      lines = wrap(ctx, headline, maxW);
      while (lines.length > 3 && size > 10) { size -= 1; ctx.font = `400 ${size}px StringerSerif, serif`; lines = wrap(ctx, headline, maxW); }
      const top = kind === 'lead' ? h * 0.16 : kind === 'scene' ? h * 0.07 : h * 0.12;
      band = Math.round(Math.max(band, top + lines.length * size * 1.16 + size * 0.6));
    }

    // sky: paper with blue halftone grain, heavier at the top
    const sky = A.canvas(w * dpr, band * dpr);
    A.paintGrain(sky, 3 + it.id.length, (y) => 0.5 * Math.pow(1 - y, 1.2) + 0.04);
    ctx.drawImage(sky, 0, 0);

    // map
    if (W) {
      const mh = h - band;
      const f = it.frame || [it.lng - 4, it.lat - 3, it.lng + 4, it.lat + 3];
      const widen = kind === 'tag' ? 2.4 : kind === 'thumb' ? 1.8 : kind === 'scene' ? 1.55 : 1.25;
      const cx = (f[0] + f[2]) / 2, cy = (f[1] + f[3]) / 2;
      const hw = ((f[2] - f[0]) / 2) * widen, hh = ((f[3] - f[1]) / 2) * widen;
      const cam = A.fitCamera([cx - hw, cy - hh, cx + hw, cy + hh], {w, h: mh});
      // keep the pin in the frame's middle third
      cam.x = A.mx(it.lng) * 0.6 + cam.x * 0.4;
      cam.y = A.my(it.lat) * 0.6 + cam.y * 0.4;
      const proj = A.projectionFor(cam, w / 2, mh / 2);
      const region = it.region && W.provinces[it.region] ? W.provinces[it.region].shape : null;
      const step = kind === 'tag' ? 1.6 : kind === 'thumb' ? 1.9 : 2.6;
      const L = A.paintLayer({w, h: mh, dpr, proj, region, step, seed: 7 + it.id.length, borderAlpha: 0.75});
      ctx.drawImage(L.base, 0, band * dpr);
      if (L.lit) ctx.drawImage(L.lit, 0, band * dpr);
      ctx.fillStyle = 'rgba(233,238,246,0.6)';
      ctx.fillRect(0, band * dpr, w * dpr, Math.max(1, dpr * 0.8));
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.translate(0, band);
      if (L.outline && kind !== 'tag') A.dottedRings(ctx, L.outline, 1, {step: kind === 'thumb' ? 2.6 : 3.6, rad: kind === 'thumb' ? 0.55 : 0.85});
      const p = proj([it.lng, it.lat]);
      const s = kind === 'tag' ? 0.75 : kind === 'thumb' ? 0.95 : 1.35;
      pin(ctx, p[0], p[1], s);
      if (words && kind !== 'scene') {
        let ls = kind === 'lead' ? 15 : 17;
        ctx.font = `italic 400 ${ls}px StringerSerif, serif`;
        let tw = ctx.measureText(it.short).width;
        const right = p[0] + 10 + tw < w - 8, left = p[0] - 10 - tw > 8;
        if (right || left) label(ctx, it.short, right ? p[0] + 10 : p[0] - 10, p[1] - 8, ls, right);
        else {
          // a narrow poster: the name sits centred under the pin, a little smaller if it must
          while (tw > w - 16 && ls > 10) { ls -= 1; ctx.font = `italic 400 ${ls}px StringerSerif, serif`; tw = ctx.measureText(it.short).width; }
          label(ctx, it.short, Math.max(8, Math.min(w - 8 - tw, p[0] - tw / 2)), p[1] + ls + 7, ls, true);
        }
      }
      ctx.restore();
    }

    // words on the sky
    ctx.save();
    ctx.scale(dpr, dpr);
    if (words) {
      const x = kind === 'lead' || kind === 'scene' ? Math.max(14, w * 0.055) : w * 0.08;
      let y = (kind === 'lead' ? h * 0.16 : kind === 'scene' ? h * 0.07 : h * 0.12) + size * 0.85;
      ctx.font = `400 ${size}px StringerSerif, serif`;
      ctx.fillStyle = A.PAL.ink;
      for (const ln of lines) { ctx.fillText(ln, x, y); y += size * 1.16; }
      if (kind === 'scene') caps(ctx, 'Made with AI', w - x, h * 0.07 + size * 0.55, 7.5, A.PAL.ink, 'right', 0.7);
      else caps(ctx, 'Made with AI', w - x * 0.9, kind === 'lead' ? h * 0.09 : h * 0.065, kind === 'lead' ? 7.5 : 7, A.PAL.ink, 'right', 0.7);
    } else {
      // the headline as ink bars
      ctx.fillStyle = A.PAL.ink;
      const x = w * 0.12;
      const bh = Math.max(2, h * 0.032);
      const widths = kind === 'tag' ? [0.74, 0.5] : [0.78, 0.62, 0.42];
      let y = band * (kind === 'tag' ? 0.42 : 0.34);
      for (const fw of widths) { ctx.globalAlpha = 0.88; ctx.fillRect(x, y, w * fw, bh); y += bh * 2.1; }
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    cache.set(key, c);
    return c;
  }

  function into(el, it, kind, w, h) {
    const c = make(it, kind, w, h);
    const copy = A.canvas(c.width, c.height);
    copy.getContext('2d').drawImage(c, 0, 0);
    copy.setAttribute('aria-hidden', 'true');
    el.appendChild(copy);
    return copy;
  }

  window.Posters = {make, into, ready};
})();
