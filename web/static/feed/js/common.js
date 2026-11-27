// Stringer direction 2: helpers shared by the three pages (grain tiles, braille decoding, icons, dates, tags).
// Plain browser JS, no build step. Reads window.STRINGER_DEMO, which boot.js fetches from /api/site.
(function () {
  'use strict';
  const D = window.STRINGER_DEMO || {};
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- seeded random (the renderer's rng), so the grain and the braille cells are steady ----------
  function rng(seed) {
    let s = Math.abs(Math.floor(seed)) % 2147483647;
    if (s <= 0) s += 2147483646;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  }

  // ---- grain tiles: the video's halftone, as small repeating PNGs on fixed layers ----------------
  function tile({ size = 256, base, dots, density, block = 2, noise = 10, seed = 21, square = 0 }) {
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const x = c.getContext('2d');
    const img = x.createImageData(size, size);
    const d = img.data;
    const r = rng(seed);
    for (let by = 0; by < size; by += block) {
      for (let bx = 0; bx < size; bx += block) {
        let col = base, a = 255;
        if (r() < density) col = dots[Math.floor(r() * dots.length)];
        else if (square) a = 0;
        const n = (r() - 0.5) * noise;
        for (let oy = 0; oy < block; oy++) for (let ox = 0; ox < block; ox++) {
          const i = ((by + oy) * size + bx + ox) * 4;
          d[i] = col[0] + n; d[i + 1] = col[1] + n; d[i + 2] = col[2] + n; d[i + 3] = a;
        }
      }
    }
    x.putImageData(img, 0, 0);
    return c.toDataURL('image/png');
  }

  function grain() {
    const root = document.documentElement.style;
    try {
      // paper: cream with sky-blue blocks (paintGrain); transparent elsewhere so the layer can sit over paper
      root.setProperty('--tile-paper', `url(${tile({ base: [243, 238, 225], dots: [[121, 171, 219], [168, 201, 234]], density: 0.2, seed: 21, square: 1 })})`);
      // night: deep ink with cobalt squares (the headline card's posterLayer, darker)
      root.setProperty('--tile-night', `url(${tile({ base: [10, 16, 51], dots: [[20, 31, 104], [24, 38, 124], [17, 27, 92]], density: 0.16, seed: 77, block: 2, noise: 4, square: 1 })})`);
    } catch (e) { /* a canvas that can't export (rare on file://) just leaves the canvas plain */ }
  }

  // ---- braille cells: 8 patterns of 2 x 4 dots, made once as CSS classes -------------------------
  function brailleStyles() {
    if (document.getElementById('bc-styles')) return;
    const r = rng(1000);
    const xs = [32, 68], ys = [30, 44, 58, 72];
    let css = '';
    for (let k = 1; k <= 8; k++) {
      const g = [];
      for (const xx of xs) for (const yy of ys) if (r() < 0.5) g.push(`radial-gradient(circle at ${xx}% ${yy}%, currentColor 0 0.052em, transparent 0.064em)`);
      if (!g.length) g.push('radial-gradient(circle at 32% 44%, currentColor 0 0.052em, transparent 0.064em)');
      css += `.b${k}{--cell:${g.join(',')}}`;
    }
    const st = document.createElement('style');
    st.id = 'bc-styles';
    st.textContent = css;
    document.head.append(st);
  }

  // Text that decodes from braille dots into letters, left to right, like the video's words being spoken.
  // Keeps every letter's width (the letter is there, just unfilled), so nothing reflows.
  const running = new WeakMap();
  function decode(el, { delay = 0, perChar = 22, max = 1500, min = 380 } = {}) {
    if (!el) return;
    const text = el.dataset.text != null ? el.dataset.text : el.textContent;
    el.dataset.text = text;
    if (running.has(el)) cancelAnimationFrame(running.get(el));
    if (reduced() || !text.trim()) { el.textContent = text; return; }
    el.textContent = '';
    const sr = document.createElement('span');
    sr.className = 'sr-only';
    sr.textContent = text;
    const vis = document.createElement('span');
    vis.setAttribute('aria-hidden', 'true');
    vis.className = 'decoding';
    const cells = [];
    for (const tok of text.split(/(\s+)/)) {
      if (!tok) continue;
      if (/^\s+$/.test(tok)) { vis.append(tok); continue; }
      const w = document.createElement('span');
      w.className = 'w';
      for (const ch of tok) {
        const s = document.createElement('span');
        s.textContent = ch;
        s.className = 'bc b' + (1 + Math.floor(Math.random() * 8));
        w.append(s);
        cells.push(s);
      }
      vis.append(w);
    }
    el.append(sr, vis);
    const total = cells.length;
    const dur = Math.max(min, Math.min(max, total * perChar));
    const t0 = performance.now() + delay;
    let shown = 0, lastShuffle = 0;
    const step = (t) => {
      const p = Math.max(0, (t - t0) / dur);
      const n = Math.min(total, Math.floor(p * total));
      while (shown < n) { cells[shown].className = ''; shown++; }
      if (t - lastShuffle > 90) {               // the dots flicker as they wait, like the renderer's per-frame cells
        lastShuffle = t;
        for (let i = shown; i < total; i++) if (Math.random() < 0.35) cells[i].className = 'bc b' + (1 + Math.floor(Math.random() * 8));
      }
      if (shown < total) running.set(el, requestAnimationFrame(step));
      else { running.delete(el); el.textContent = text; }
    };
    running.set(el, requestAnimationFrame(step));
  }

  // ---- dates, in New York time --------------------------------------------------------------------
  const NOW = new Date(D.now || Date.now());
  const ny = (iso, opts) => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ...opts }).format(new Date(iso));
  const dayKey = (d) => ny(d, { year: 'numeric', month: '2-digit', day: '2-digit' });
  function clock(iso) { return ny(iso, { hour: 'numeric', minute: '2-digit' }).replace(' AM', ' am').replace(' PM', ' pm'); }
  function when(iso) {
    if (!iso) return '';
    const k = dayKey(iso);
    if (k === dayKey(NOW)) return `Today, ${clock(iso)}`;
    const y = new Date(NOW.getTime() - 864e5);
    if (k === dayKey(y)) return `Yesterday, ${clock(iso)}`;
    return `${ny(iso, { weekday: 'short' })} ${ny(iso, { day: 'numeric' })} ${ny(iso, { month: 'short' })}`;
  }
  function shortDay(iso) {
    if (!iso) return '';
    const k = dayKey(iso);
    if (k === dayKey(NOW)) return 'Today';
    if (k === dayKey(new Date(NOW.getTime() - 864e5))) return 'Yesterday';
    return `${ny(iso, { weekday: 'short' })} ${ny(iso, { day: 'numeric' })} ${ny(iso, { month: 'short' })}`;
  }
  function ago(iso) {
    const m = Math.round((NOW - new Date(iso)) / 60000);
    if (m < 60) return `${m} min ago`;
    const h = Math.round(m / 60);
    return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
  }

  // ---- tags: category, subtype, country, region, and the two sides (or "no real divide") ----------
  // the feed's words come as government_change; show them as words
  const cap = (s) => { const t = String(s || '').replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
  function tags(v) {
    const t = [
      { kind: 'category', label: cap(v.category) },
      { kind: 'subtype', label: cap(v.subtype) },
      { kind: 'country', label: v.country },
      { kind: 'region', label: v.region },
    ];
    if (v.sides && v.sides.kind === 'two sides') {
      t.push({ kind: 'side', side: 'A', label: v.sides.A.label });
      t.push({ kind: 'side', side: 'B', label: v.sides.B.label });
    } else t.push({ kind: 'nodivide', label: 'No real divide' });
    return t;
  }

  // ---- icons: plain strokes, 1.6 wide ------------------------------------------------------------
  const P = (d, extra = '') => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
  const ICON = {
    play: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>',
    pause: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="13.5" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>',
    soundOn: P('<path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6"/><path d="M18 6.5a7.6 7.6 0 0 1 0 11"/>'),
    soundOff: P('<path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>'),
    flag: P('<path d="M5.5 21V4.5"/><path d="M5.5 4.5h11.2l-2.4 4 2.4 4H5.5"/>'),
    up: P('<path d="M6 14.5l6-6 6 6"/>'),
    down: P('<path d="M6 9.5l6 6 6-6"/>'),
    left: P('<path d="M14.5 6l-6 6 6 6"/>'),
    right: P('<path d="M9.5 6l6 6-6 6"/>'),
    close: P('<path d="M6 6l12 12M18 6L6 18"/>'),
    check: P('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
    cross: P('<path d="M7 7l10 10M17 7L7 17"/>'),
    receipt: P('<path d="M6 3.5h12v17l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4-2 1.4z"/><path d="M9 8h6M9 11.5h6M9 15h3.5"/>'),
    list: P('<path d="M8.5 6.5h11M8.5 12h11M8.5 17.5h11"/><circle cx="4.5" cy="6.5" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="17.5" r="1"/>'),
    eyeOff: P('<path d="M3 3l18 18"/><path d="M10.6 5.6A9.9 9.9 0 0 1 12 5.5c5 0 8.5 4.8 9 6.5-.3.9-1.2 2.4-2.6 3.8M6.3 7.3C4.5 8.6 3.4 10.4 3 12c.5 1.7 4 6.5 9 6.5 1.6 0 3-.5 4.3-1.2"/><path d="M9.9 10a3 3 0 0 0 4.1 4.1"/>'),
    clock: P('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
    signout: P('<path d="M14 4.5H6.5v15H14"/><path d="M10.5 12H20.5M17 8.5l3.5 3.5-3.5 3.5"/>'),
    lock: P('<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3"/>'),
    arrowRight: P('<path d="M4.5 12h15M14 6.5l5.5 5.5-5.5 5.5"/>'),
    arrowDown: P('<path d="M12 4.5v15M6.5 14l5.5 5.5 5.5-5.5"/>'),
    redo: P('<path d="M19.5 8.5v5h-5"/><path d="M19.2 13.3A7.5 7.5 0 1 1 17 7"/>'),
    keyboard: P('<rect x="3" y="6.5" width="18" height="11" rx="2"/><path d="M7 10.5h.01M10 10.5h.01M13 10.5h.01M16 10.5h.01M8 14h8"/>'),
    info: P('<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>'),
    grip: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="10.5" width="10" height="3" rx="1.5" fill="currentColor"/></svg>',
    menu: P('<path d="M4.5 8h15M4.5 16h15"/>'),
    spark: P('<path d="M12 3.5v4M12 16.5v4M3.5 12h4M16.5 12h4"/>'),
    trace: P('<path d="M6 6v12"/><circle cx="6" cy="5" r="1.7" fill="currentColor"/><circle cx="6" cy="12" r="1.7" fill="currentColor"/><circle cx="6" cy="19" r="1.7"/><path d="M11 5h8.5M11 12h6.5M11 19h4"/>'),
  };

  // ---- small helpers -----------------------------------------------------------------------------
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // a video's own addresses on the site (/media/videos/<event>/<ticket>/...); no stand-in footage
  const media = (v) => (v && v.src) || '';
  const poster = (v) => (v && v.poster) || '';

  // A view transition when the browser has one; otherwise just do the change.
  function transition(change, types) {
    if (!document.startViewTransition || reduced()) { change(); return Promise.resolve(); }
    try {
      const vt = types && document.startViewTransition.length !== undefined
        ? document.startViewTransition({ update: change, types })
        : document.startViewTransition(change);
      return vt.finished.catch(() => {});
    } catch (e) {
      const vt = document.startViewTransition(change);
      return vt.finished.catch(() => {});
    }
  }

  function toast(html, { ms = 4200, action } = {}) {
    let host = $('#toasts');
    if (!host) { host = document.createElement('div'); host.id = 'toasts'; host.setAttribute('role', 'status'); host.setAttribute('aria-live', 'polite'); document.body.append(host); }
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = `<span class="knot"></span><span class="toast-text">${html}</span>`;
    if (action) {
      const b = document.createElement('button');
      b.className = 'toast-act';
      b.textContent = action.label;
      b.addEventListener('click', () => { action.run(); t.remove(); });
      t.append(b);
    }
    host.append(t);
    requestAnimationFrame(() => t.classList.add('in'));
    setTimeout(() => { t.classList.remove('in'); setTimeout(() => t.remove(), 400); }, ms);
    return t;
  }

  grain();
  brailleStyles();

  // The outlet labels (sides, reliability, state media) come from these; their licences ask for the credit
  // wherever the labels show. Same words as the README's Credits.
  const LABELS_CREDIT = 'Media bias ratings by AllSides.com (CC BY-NC 4.0). State Media Monitor 2026, MJRC (CC BY 4.0). '
    + 'Domain reliability from Lin et al. 2023, PNAS Nexus.';

  window.SG = { D, LABELS_CREDIT, rng, decode, when, shortDay, clock, ago, tags, ICON, $, $$, esc, media, poster, transition, toast, reduced, NOW, cap };
})();
