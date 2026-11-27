// Progress: a video being made, one agent at a time, on the site's real run record (module 9).
// window.STRINGER_RUN comes from /api/progress?event= (boot.js). While the run is live the page asks again every
// 2.5 s and the clock is the run's own (the server's elapsed time, counted on between answers). A finished run
// opens at its end and can be replayed from its recorded times. Built like one slot of the feed: the card in the
// middle fills in as the agents work. On desktop the left rail lists the steps and the right rail shows the chosen
// agent's model calls, searches and hand-on. On tablets the right rail holds the whole trace; on phones it's a
// pull-up sheet. URL: ?event=<id> (required), ?at=<seconds> (a finished run: replay from there), ?speed=1,
// ?still (frozen), ?step=key, ?sheet.
(function () {
  'use strict';
  const { $, $$, esc, decode, reduced, toast, LABELS_CREDIT } = window.SG;
  const GET = window.STRINGER_GET;
  const qs = new URLSearchParams(location.search);
  const EVENT_ID = qs.get('event') || '';
  const pg = $('#pg');
  let SR = window.STRINGER_RUN;

  // ================================================================================================
  // DATA: the run record, with every call and search placed on the run's clock
  // ================================================================================================
  let RUN, STEPS, BY, N, END, KIND, STOP, ALL_CALLS, ALL_SEARCHES, MODELS, EVENT, SIDES, VIDEO_TITLE;
  function build(sr) {
    const steps = (sr.steps || []).map((s, i) => ({
      ...s, i, skipped: s.status === 'skipped', counts: s.counts || {}, hands_on: s.hands_on || null,
      calls: (s.calls || []).map((c) => ({ ...c })), searches: (s.searches || []).map((q) => ({ ...q })), parts: (s.parts || []).map((p) => ({ ...p })),
    }));
    for (const s of steps) {
      if (s.start == null) continue;
      // searches and calls saved without a time sit evenly across their (finished) step
      const spread = (list) => {
        const un = list.filter((x) => x.t == null);
        if (!un.length || s.end == null) return;
        un.forEach((x, k) => { x.t = s.start + (s.end - s.start) * (k + 1) / (un.length + 1); });
      };
      spread(s.searches);
      spread(s.calls);
      s.calls.sort((a, b) => a.t - b.t);
      s.searches.sort((a, b) => a.t - b.t);
      if (s.key === 'video' && s.parts.length) { let a = s.start; s.parts.forEach((p) => { p.from = a; a += p.seconds || 0; p.to = a; }); }
    }
    STEPS = steps;
    BY = Object.fromEntries(STEPS.map((s) => [s.key, s]));
    N = STEPS.length;
    KIND = sr.live ? 'running' : sr.outcome === 'done' ? 'done' : sr.outcome === 'no_video' ? 'novideo' : 'failed';
    const ran = STEPS.filter((s) => s.start != null);
    STOP = KIND === 'novideo' || KIND === 'failed' ? (ran.length ? ran[ran.length - 1].key : null) : null;
    END = sr.live ? Infinity : (sr.seconds != null ? +sr.seconds : Math.max(0, ...ran.map((s) => s.end || 0)));
    ALL_CALLS = STEPS.flatMap((s) => s.calls);
    ALL_SEARCHES = STEPS.flatMap((s) => s.searches);
    MODELS = sr.models || {};
    EVENT = sr.event_meta || {};
    SIDES = BY.sides && BY.sides.hands_on && BY.sides.hands_on.side_a ? BY.sides.hands_on : null;
    VIDEO_TITLE = (BY.script && BY.script.hands_on && BY.script.hands_on.title) || sr.event || '';
    RUN = sr;
  }
  build(SR);
  const nextOf = (s) => STEPS[s.i + 1];
  const isDone = () => KIND === 'done';
  const isLive = () => KIND === 'running';
  const stopped = () => KIND === 'novideo' || KIND === 'failed';

  // ================================================================================================
  // FORMATTING, for people
  // ================================================================================================
  const clock = (t) => { t = Math.max(0, Math.floor(t)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
  const secs = (s) => { s = +s || 0; if (s < 10) return `${s.toFixed(1)} s`; const r = s < 59.5 ? Math.round(s) : Math.floor(s); return r < 60 ? `${r} s` : `${Math.floor(r / 60)} min ${r % 60} s`; };
  const usd = (u) => { u = +u || 0; return u >= 0.1 ? `$${u.toFixed(2)}` : u >= 0.001 ? `$${u.toFixed(3)}` : u > 0 ? 'under $0.001' : '$0'; };
  const money = (u) => (u >= 1 && Math.abs(u - Math.round(u)) < 0.005 ? `$${Math.round(u)}` : `$${(+u || 0).toFixed(2)}`);
  const tok = (n) => n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n || 0);
  const tokens = (tin, tout) => `${tok(tin)} in · ${tok(tout)} out`;
  const up = (s) => (s ? String(s)[0].toUpperCase() + String(s).slice(1) : s);
  const num = (n) => Number(n || 0).toLocaleString('en-US');
  const model = (m) => MODELS[m] || m || '';
  const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many || one + 's'}`;
  const sum = (arr, f) => arr.reduce((a, x) => a + (+f(x) || 0), 0);
  const isWarn = (note) => /fix|again|retry|wrong|too little|not backed|didn't|short|failed/i.test(note || '');
  const shortSide = (label) => String(label || '').split(/[\s(]/)[0] || 'One';
  const sideLabel = (k) => (k === 'A' ? (SIDES ? SIDES.side_a.label : 'Side A') : k === 'B' ? (SIDES ? SIDES.side_b.label : 'Side B') : k);
  // the script's "why" for a stop, in plain words: drop the checker's prefixes
  const plainWhy = (w) => up(String(w || '').replace(/^script:\s*/i, '').replace(/^the hook beat still fails:\s*/i, '').replace(/^not backed(\s*\([^)]*\))?:\s*/i, '').trim());

  const SVG = (d, cls = 'icon') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const I = {
    check: SVG('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'icon icon-s'),
    cross: SVG('<path d="M7 7l10 10M17 7L7 17"/>', 'icon icon-s'),
    redo: SVG('<path d="M19.5 8.5v5h-5"/><path d="M19.2 13.3A7.5 7.5 0 1 1 17 7"/>', 'icon icon-s'),
    info: SVG('<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>', 'icon icon-s'),
    play: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>',
    pause: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="13.5" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>',
    soundOn: SVG('<path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6"/><path d="M18 6.5a7.6 7.6 0 0 1 0 11"/>'),
    soundOff: SVG('<path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>'),
    arrow: SVG('<path d="M4.5 12h15M14 6.5l5.5 5.5-5.5 5.5"/>', 'icon icon-s'),
    replay: SVG('<path d="M4.5 8.5v5h5"/><path d="M4.8 13.3A7.5 7.5 0 1 0 7 7"/>', 'icon icon-s'),
    skip: SVG('<path d="M5 6l7 6-7 6zM13 6l7 6-7 6z"/>', 'icon icon-s'),
    live: '<span class="live-dot" aria-hidden="true"></span>',
  };
  // small drawings for the storyboard's shot kinds (the script's names, and the design's)
  const SHOT = {
    hook: SVG('<path d="M12 3.5v4M12 16.5v4M3.5 12h4M16.5 12h4"/><circle cx="12" cy="12" r="1.6"/>'),
    map: SVG('<path d="M12 20s6-5.4 6-10a6 6 0 0 0-12 0c0 4.6 6 10 6 10z"/><circle cx="12" cy="10" r="2"/>'),
    'big number': SVG('<path d="M9 4.5L7 19.5M17 4.5l-2 15M4.5 9h15M3.5 15h15"/>'),
    timeline: SVG('<path d="M3.5 12h17"/><circle cx="7" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="17" cy="12" r="1.8"/>'),
    quote: SVG('<path d="M10 7.5c-2.5.8-4 2.8-4 5.6V17h4.5v-4.5H8M18.5 7.5c-2.5.8-4 2.8-4 5.6V17H19v-4.5h-2.5"/>'),
    'two sides': SVG('<rect x="3.5" y="5" width="7" height="14" rx="1.5"/><rect x="13.5" y="5" width="7" height="14" rx="1.5"/>'),
    "what's missing": SVG('<rect x="4" y="5" width="16" height="14" rx="1.5" stroke-dasharray="2.6 2.6"/><path d="M12 9.5v3.5M12 15.6h.01"/>'),
    sources: SVG('<path d="M8 6.5h12M8 12h12M8 17.5h12"/><circle cx="4.5" cy="6.5" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="17.5" r="1"/>'),
  };
  const SHOT_ALIAS = { headline: 'hook', map_locate: 'map', map_route: 'map', map_zoom: 'map', locate: 'map', claim_vs_claim: 'two sides', two_sides: 'two sides',
    number: 'big number', big_number: 'big number', stat: 'big number', whats_missing: "what's missing", missing: "what's missing", source_card: 'sources', sources_card: 'sources' };
  const shotIcon = (k) => SHOT[k] || SHOT[SHOT_ALIAS[k]] || (/map/.test(k || '') ? SHOT.map : '');
  const shotName = (k) => String(k || '').replace(/_/g, ' ');

  // ================================================================================================
  // DETERMINISTIC PICTURES: which articles were the same story, which claims held up (from the counts)
  // ================================================================================================
  let SAME_V = [], CHECK_V = [], ARTICLES = 0, CLAIMS_N = 0, PICKED = [];
  function pictures() {
    const rnd = window.SG.rng(String(RUN.event_id || 'x').split('').reduce((a, c) => a + c.charCodeAt(0), 7));
    const shuffled = (list) => { const a = list.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    const SS = (BY.same_story && BY.same_story.counts) || {};
    SAME_V = shuffled([...Array(+SS.same || 0).fill('same'), ...Array(+SS.different || 0).fill('diff'), ...Array(+SS.follow_up || 0).fill('fu')]);
    const FC = (BY.fact_check && BY.fact_check.counts) || {};
    CHECK_V = shuffled([...Array(+FC.confirmed || 0).fill('ok'), ...Array(+FC.say_with_source || 0).fill('say'), ...Array(+FC.dropped || 0).fill('drop')]);
    ARTICLES = +((BY.gather && (BY.gather.counts.articles || (BY.gather.hands_on || {}).articles)) || SAME_V.length || 0);
    CLAIMS_N = +((BY.story_file && BY.story_file.counts.claims) || FC.claims || CHECK_V.length || 0);
    const order = { A: 0, B: 1, wire: 2, other: 3 };
    PICKED = (((BY.balance_pick || {}).hands_on || {}).picked || []).slice().sort((a, b) => (order[a.side] ?? 4) - (order[b.side] ?? 4));
  }
  pictures();

  // ================================================================================================
  // STATE AT TIME t (pure: everything is worked out from t, so replaying and skipping just work)
  // ================================================================================================
  function status(s, t) {
    if (s.skipped) return t >= END ? 'skipped' : 'waiting';
    if (s.start == null || t < s.start) return 'waiting';
    if (s.end == null || t < s.end) return 'running';
    return s.key === STOP ? 'stopped' : 'done';
  }
  function currentStep(t) {
    for (const s of STEPS) if (status(s, t) === 'running') return s;
    return null;
  }
  const arrived = (list, t) => list.filter((x) => x.t != null && x.t <= t);
  // how far through a step the replay is: known for finished steps, unknown (null) for a live one
  function frac(s, t) {
    if (s.start == null || t < s.start) return 0;
    if (s.end != null && t >= s.end) return 1;
    if (s.end == null) return null;
    if (s.calls.length) return arrived(s.calls, t).length / s.calls.length;
    return (t - s.start) / Math.max(0.001, s.end - s.start);
  }
  function spentAt(t) {
    if (isLive()) return +RUN.usd || 0;
    let u = 0;
    for (const s of STEPS) {
      if (s.skipped || s.start == null || t < s.start) continue;
      if (s.end != null && t >= s.end) { u += +s.usd || 0; continue; }
      u += spentInStep(s, t);
    }
    return Math.min(u, +RUN.usd || u);
  }
  function spentInStep(s, t) {
    if (s.end == null) return sum(arrived(s.calls, t), (c) => c.usd);
    if (s.key === 'video') return (+s.usd || 0) * Math.max(0, t - s.start) / Math.max(0.001, s.end - s.start);
    const items = [...s.calls, ...s.searches].filter((x) => x.t != null);
    return items.length ? (+s.usd || 0) * arrived(items, t).length / items.length : (+s.usd || 0) * Math.max(0, t - s.start) / Math.max(0.001, s.end - s.start);
  }
  // a run made before each call was kept has only its total: that shows at the end, a dash on the way
  const callsAt = (t) => (isLive() ? Math.max(ALL_CALLS.length, +RUN.model_calls || 0) : t >= END && RUN.model_calls != null ? +RUN.model_calls : !ALL_CALLS.length && RUN.model_calls ? '–' : arrived(ALL_CALLS, t).length);
  const searchesAt = (t) => arrived(ALL_SEARCHES, t).length;
  function foundAt(t) {
    const s = BY.gather;
    if (!s || s.start == null) return 0;
    if (s.end != null && t >= s.end) return ARTICLES;
    const all = sum(s.searches, (q) => q.results);
    return all ? Math.round(ARTICLES * sum(arrived(s.searches, t), (q) => q.results) / all) : 0;
  }
  const portion = (s, n, t) => { const f = s ? frac(s, t) : 0; return f == null ? 0 : Math.round(n * f); };
  const judgedAt = (t) => portion(BY.same_story, SAME_V.length, t);
  const checkedAt = (t) => portion(BY.fact_check, CHECK_V.length, t);
  function readAt(t) {
    const s = BY.story_file;
    if (!s || s.start == null || t < s.start) return 0;
    if (s.end != null && t >= s.end) return PICKED.length;
    const reads = arrived(s.calls.filter((c) => /read an article|read article/.test(c.purpose || '')), t).length;
    return Math.min(PICKED.length, reads || portion(s, PICKED.length, t));
  }
  const mergedAt = (t) => { const s = BY.story_file; if (!s) return false; if (s.end != null && t >= s.end) return true; return arrived(s.calls, t).some((c) => /merge facts/.test(c.purpose || '')); };
  function partAt(t) {
    const s = BY.video;
    if (!s || s.skipped || s.start == null || t < s.start || !s.parts.length) return null;
    return s.parts.find((p) => t < p.to) || s.parts[s.parts.length - 1];
  }
  function framesAt(t) {
    const s = BY.video, h = (s && s.hands_on) || {}, r = s && s.parts.find((p) => p.part === 'render');
    if (!h.frames || !r || t < r.from) return 0;
    return t >= r.to ? h.frames : Math.round(h.frames * (t - r.from) / Math.max(0.001, r.to - r.from));
  }
  // what the running agent is doing: on a replay, the next call or search still out; live, the latest one
  function nowDoing(s, t) {
    if (s.key === 'video') { const p = partAt(t); if (p) return p.part === 'render' && s.hands_on && s.hands_on.frames ? `Drawing frame ${num(framesAt(t))} of ${num(s.hands_on.frames)}` : p.label; }
    if (s.end == null) {
      const last = arrived(s.calls, t).slice(-1)[0];
      if (!last) return s.key === 'gather' ? 'Searching the news' : 'Starting';
      return `${up(last.purpose)} · ${model(last.model)}`;
    }
    const pend = [...s.calls.map((c) => ({ c })), ...s.searches.map((q) => ({ q }))]
      .filter((x) => (x.c || x.q).t > t).sort((a, b) => (a.c || a.q).t - (b.c || b.q).t)[0];
    if (!pend) return 'Wrapping up';
    return pend.c ? `${up(pend.c.purpose)} · ${model(pend.c.model)}` : `Searching “${pend.q.query}”`;
  }
  // the counts in words, live while running and final when done
  function words(s, t) {
    const st = status(s, t), c = s.counts || {}, h = s.hands_on || {};
    if (st === 'waiting') return '';
    if (st === 'skipped') return "Didn't run, because the run stopped";
    if (st === 'stopped' && s.key !== 'script') return 'Stopped here';
    const fin = st !== 'running';
    const calls = arrived(s.calls, t).length;
    switch (s.key) {
      case 'sides':
        if (!fin) return 'Reading the event';
        return h.side_a ? `2 sides, ${num((h.side_a.n || h.side_a.outlets.length) + (h.side_b.n || h.side_b.outlets.length))} outlets named` : 'No real divide, so one group';
      case 'gather':
        if (fin) return `${num(c.articles || h.articles)} articles from ${num(h.outlets)} outlets`;
        return arrived(s.searches, t).length ? `${num(foundAt(t))} articles so far, from ${plural(arrived(s.searches, t).length, 'search', 'searches')}` : 'Searching the news';
      case 'same_story':
        if (fin) return `${num(c.same)} about this event, ${num(c.different)} set aside${c.follow_up ? `, ${c.follow_up} follow-up` : ''}`;
        return frac(s, t) == null ? `Judging ${ARTICLES ? plural(ARTICLES, 'article') : 'the articles'}${calls ? `, ${plural(calls, 'answer')} back` : ''}` : `${judgedAt(t)} of ${num(SAME_V.length)} articles judged`;
      case 'balance_pick': {
        if (!fin) return arrived(s.searches, t).length || calls > 1 ? 'One side was short, so it searched again' : 'Picking about ten articles';
        const by = (k) => (h.picked || []).filter((p) => p.side === k).length;
        const n = c.picked || (h.picked || []).length;
        return SIDES ? `${n} picked: ${by('A')} ${shortSide(SIDES.side_a.label)}, ${by('B')} ${shortSide(SIDES.side_b.label)}, ${n - by('A') - by('B')} from elsewhere` : `${n} picked`;
      }
      case 'story_file':
        if (fin) return `${num(c.facts)} facts merged into ${num(c.claims)} claims`;
        return mergedAt(t) ? 'Facts merged into claims, still checking' : `Read ${readAt(t)} of ${PICKED.length || 'the'} articles`;
      case 'fact_check':
        if (fin) return `${num(c.claims)} claims: ${num(c.confirmed)} confirmed, ${num(c.say_with_source)} say who said it, ${num(c.dropped)} dropped`;
        return frac(s, t) == null ? `Checking ${CLAIMS_N ? plural(CLAIMS_N, 'claim') : 'the claims'}` : `${checkedAt(t)} of ${num(CHECK_V.length)} claims checked`;
      case 'script': {
        const fb = h.failed_beat;
        if (st === 'stopped') return fb ? (fb.n === 1 ? 'The opening line wasn’t backed, so it stopped' : `Beat ${fb.n} wasn’t backed, so it stopped`) : 'It stopped here';
        if (fin) return `${num(c.words || h.words)} words in ${(h.beats || []).length} beats`;
        const last = arrived(s.calls, t).slice(-1)[0];
        return last ? up(last.purpose) : 'Writing the script';
      }
      case 'video':
        if (fin) return [h.length ? `${h.length} long` : '', h.frames ? `${num(h.frames)} frames` : '', h.captions ? `${h.captions} captions` : ''].filter(Boolean).join(', ') || 'Recorded and drawn';
        return nowDoing(s, t);
      default: return '';
    }
  }

  // ================================================================================================
  // HAND-ONS: what each agent passes to the next, drawn as readable things (never as JSON)
  // ================================================================================================
  const sideCls = (k) => (k === 'A' ? 'a' : k === 'B' ? 'b' : 'n');
  const dotsN = (n, max = 8) => `<span class="slip-dots" aria-hidden="true">${'<i></i>'.repeat(Math.min(max, n || 0))}</span>`;
  let CLAIMS = {}, VERDICT = {};
  function index() {
    CLAIMS = Object.fromEntries((((BY.story_file || {}).hands_on || {}).claims_sample || []).map((c) => [c.id, c]));
    VERDICT = Object.fromEntries((((BY.fact_check || {}).hands_on || {}).verdicts || []).map((v) => [v.id, v]));
  }
  index();
  const vClass = (status) => (status === 'confirmed' ? 'ok' : status === 'dropped' ? 'drop' : 'say');
  const vWord = (status) => (status === 'confirmed' ? 'Confirmed' : status === 'dropped' ? 'Dropped' : 'Say who said it');
  const badge = (status) => `<span class="vb v-${vClass(status)}">${vClass(status) === 'ok' ? I.check : vClass(status) === 'drop' ? I.cross : '<b aria-hidden="true">“</b>'}${vWord(status)}</span>`;
  function claimChip(id) {
    const v = VERDICT[id];
    return `<span class="cid${v ? ' v-' + vClass(v.status) : ''}" title="${v ? esc(vWord(v.status)) : 'Claim'}">${esc(id)}</span>`;
  }

  function hoSides(h) {
    if (!h.side_a) {
      return `<p class="ho-lede serif">${esc(h.reason || '')}</p>
        <div class="slip n"><div class="slip-head"><span class="caps slip-label">No real divide</span></div><p class="slip-meta">The articles are read as one group.</p></div>
        <p class="ho-fine">${h.chosen_by === 'model' ? 'The model decided.' : ''}</p>`;
    }
    const slip = (side, cls) => `<div class="slip ${cls}"><div class="slip-head"><span class="caps slip-label">${esc(side.label)}</span>${dotsN(side.n || side.outlets.length)}</div>
      <p class="slip-meta">${plural(side.n || side.outlets.length, 'outlet')}${(side.n || 0) > side.outlets.length ? `, the first ${side.outlets.length} shown` : ''}</p><p class="slip-list">${side.outlets.map(esc).join('<i>·</i>')}</p></div>`;
    return `<p class="ho-lede serif">${esc(h.reason || '')}</p>${slip(h.side_a, 'a')}${slip(h.side_b, 'b')}
      <p class="ho-fine">${h.kind === 'world' ? 'A world story, so the sides are outlets from different countries, not left and right.' : ''} ${h.chosen_by === 'model' ? 'The model chose them.' : 'Picked from the outlet table.'}</p>`;
  }
  function hoGather(h) {
    const by = h.by_side || {};
    const keys = Object.keys(by);
    const col = (k) => (SIDES && k === SIDES.side_a.label ? 'var(--side-a)' : SIDES && k === SIDES.side_b.label ? 'var(--side-b)' : 'var(--other)');
    const langs = h.languages && Object.keys(h.languages).length ? h.languages : null;
    const langMax = langs ? Math.max(...Object.values(langs)) : 1;
    return `<p class="ho-big"><b>${num(h.articles)}</b> articles from <b>${num(h.outlets)}</b> outlets</p>
      <div class="dotbar ho-bar" aria-hidden="true">${keys.filter((k) => by[k] > 0).map((k) => `<span style="--n:${by[k]};--c:${col(k)}"></span>`).join('')}</div>
      <ul class="legend">${keys.map((k) => `<li><i style="--c:${col(k)}"></i><b>${by[k]}</b><span class="lg-l">${k === 'elsewhere' ? 'elsewhere <span>(wire services and others)</span>' : esc(k)}</span></li>`).join('')}</ul>
      ${h.full_text != null ? `<p class="ho-fine">${plural(h.full_text, 'article')} came with the full text.</p>` : ''}
      ${langs ? `<p class="ho-sub caps">In ${plural(Object.keys(langs).length, 'language')}</p>
      <ul class="langs">${Object.entries(langs).map(([l, n]) => `<li><span>${esc(l)}</span><span class="lbar"><i style="width:${(n / langMax * 100).toFixed(1)}%"></i></span><b>${n}</b></li>`).join('')}</ul>` : ''}`;
  }
  function hoSame(h) {
    const vw = { same: 'Same event', different: 'Set aside', 'follow-up': 'Follow-up', follow_up: 'Follow-up' };
    const vc = { same: 'same', different: 'diff', 'follow-up': 'fu', follow_up: 'fu' };
    const ex = h.examples || [];
    const c = { ...h, ...((BY.same_story && BY.same_story.counts) || {}) };     // the step's own counts win
    return `<div class="tally"><div><b>${num(c.same)}</b><span>about this event</span></div><div><b>${num(c.different)}</b><span>set aside</span></div><div><b>${num(c.follow_up)}</b><span>follow-up</span></div></div>
      ${ex.length ? `<p class="ho-sub caps">How it decided, ${ex.length === 1 ? 'one example' : ex.length === 2 ? 'two examples' : 'three examples'}</p>
      <ul class="judged">${ex.map((e) => `<li class="jd j-${vc[e.verdict] || 'diff'}"><div class="jd-h"><span class="caps">${esc(e.outlet)}</span><span class="jb">${vw[e.verdict] || esc(e.verdict)}</span></div><p>${esc(e.why)}</p></li>`).join('')}</ul>` : ''}`;
  }
  function hoPick(h) {
    const lab = (k) => (k === 'A' || k === 'B' ? shortSide(sideLabel(k)) : k === 'wire' ? 'Wire' : 'Other');
    return `<ol class="picked">${PICKED.map((p) => `<li class="pk ${sideCls(p.side)}"><span class="pk-o caps">${esc(p.outlet)}<em>${esc(lab(p.side))}</em></span><span class="pk-t serif">${esc(p.title)}</span></li>`).join('')}</ol>
      ${(h.flags || []).map((f) => `<p class="flag">${I.redo}<span>${esc(f)}</span></p>`).join('')}
      <p class="ho-fine">${esc(LABELS_CREDIT)}</p>`;
  }
  function hoBrief(h) {
    const sidesOf = (c) => (c.sides || []).map((k) => `<i class="sd ${sideCls(k)}" title="${esc(sideLabel(k))}"></i>`).join('');
    const ways = Object.entries(h.how_each_side_tells_it || {}).map(([lab, lines]) => [lab, Array.isArray(lines) ? lines : [lines]]);
    const sample = h.claims_sample || [];
    return `${sample.length ? `<p class="ho-sub caps">Claims it found, ${sample.length} of ${num((BY.story_file.counts || {}).claims || sample.length)}</p>
      <ul class="claims">${sample.map((c) => `<li class="cl"><span class="cid">${esc(c.id)}</span><div><p class="serif">${esc(c.claim)}</p><p class="cl-m">${esc(c.who_says)} · ${plural(c.articles, 'article')} <span class="sds">${sidesOf(c)}</span></p></div></li>`).join('')}</ul>` : ''}
      ${ways.length ? `<p class="ho-sub caps">How each side tells it</p>${ways.map(([lab, lines], i) => `<div class="slip ${SIDES && lab === SIDES.side_b.label ? 'b' : SIDES && lab === SIDES.side_a.label ? 'a' : i ? 'b' : 'a'}"><div class="slip-head"><span class="caps slip-label">${esc(lab)}</span></div><ul class="ways">${lines.map((l) => `<li class="serif">${esc(l)}</li>`).join('')}</ul></div>`).join('')}` : ''}
      ${(h.left_out || []).map((l) => `<div class="leftout"><p class="caps">Left out</p><p class="serif">${esc(typeof l === 'string' ? l : l.text || l.what || JSON.stringify(l))}</p></div>`).join('')}`;
  }
  function hoCheck(h) {
    const c = BY.fact_check.counts || {};
    const vs = h.verdicts || [];
    return `<div class="vsum"><div class="vbar" aria-hidden="true"><span class="v-ok" style="--n:${+c.confirmed || 0}"></span><span class="v-say" style="--n:${+c.say_with_source || 0}"></span><span class="v-drop" style="--n:${+c.dropped || 0}"></span></div>
      <ul class="vleg"><li>${badge('confirmed')}<b>${num(c.confirmed)}</b></li><li>${badge('say who said it')}<b>${num(c.say_with_source)}</b></li><li>${badge('dropped')}<b>${num(c.dropped)}</b></li></ul></div>
      ${vs.length ? `<p class="ho-sub caps">${vs.length === 4 ? 'Four' : up(num(vs.length))} of the verdicts</p>
      <ul class="verdicts">${vs.map((v) => `<li class="vd"><div class="vd-h"><span class="cid">${esc(v.id)}</span>${badge(v.status)}</div>${v.claim || CLAIMS[v.id] ? `<p class="serif vd-c">${esc(v.claim || CLAIMS[v.id].claim)}</p>` : ''}<p class="vd-w">${esc(v.why)}</p></li>`).join('')}</ul>` : ''}`;
  }
  function hoScript(h) {
    if (h.failed_beat) return hoFailed(h.failed_beat);
    return `<p class="ho-title serif">${esc(h.title)}</p>
      <ol class="board">${(h.beats || []).map((b) => `<li class="beat"><div class="bt-h"><span class="bn">${b.n}</span>${shotIcon(b.shot)}<span class="caps">${esc(shotName(b.shot))}</span></div><p class="serif">${esc(b.say)}</p><p class="bt-c">${(b.claims || []).length ? b.claims.map(claimChip).join('') : '<span class="none">No claim needed</span>'}</p></li>`).join('')}</ol>
      <p class="ho-fine">Each beat is one shot. Chips starting with C are the checked claims it rests on, coloured by the fact check. The others point to how each side tells it.</p>`;
  }
  function hoFailed(b) {
    return `<div class="failed"><div class="bt-h"><span class="bn">${b.n}</span>${shotIcon(b.shot)}<span class="caps">${esc(shotName(b.shot))}</span><span class="vb v-drop">${I.cross}Not backed</span></div>
      <p class="serif">${esc(b.say)}</p><p class="bt-c">${(b.claims || []).map(claimChip).join('')}</p>${b.why ? `<p class="why">${esc(plainWhy(b.why))}</p>` : ''}</div>`;
  }
  function hoVideo(h) {
    const parts = BY.video.parts, total = sum(parts, (p) => p.seconds);
    const fact = (k, v, extra = '') => (v != null && v !== '' ? `<div><dt>${k}</dt><dd>${esc(v)}${extra}</dd></div>` : '');
    return `<dl class="facts">
        ${fact('Length', h.length)}${fact('Frames drawn', h.frames != null ? num(h.frames) : null)}
        ${fact('Beats', h.beats)}${fact('Captions', h.captions)}
        ${fact('Voice', h.voice)}${h.loudness ? fact('Loudness', h.loudness, ' <span>the usual level for streaming</span>') : ''}</dl>
      ${parts.length ? `<p class="ho-sub caps">Where the ${secs(total)} went</p>
      <div class="ptime" aria-hidden="true">${parts.map((p) => `<span style="--n:${Math.max(p.seconds, 0.6)}" class="pt-${p.part}"></span>`).join('')}</div>
      <ul class="vplist">${parts.map((p) => `<li><i class="pt-${p.part}"></i><span>${esc(p.label)}</span><b>${secs(p.seconds)}</b></li>`).join('')}</ul>` : ''}
      ${(h.files || []).length ? `<p class="ho-sub caps">Files</p><p class="files">${h.files.map((f) => `<span>${esc(f)}</span>`).join('')}</p>` : ''}`;
  }
  const HANDON = { sides: hoSides, gather: hoGather, same_story: hoSame, balance_pick: hoPick, story_file: hoBrief, fact_check: hoCheck, script: hoScript, video: hoVideo };

  // ================================================================================================
  // THE TRACE: step rows (left rail / accordion) and one detail pane per step
  // ================================================================================================
  function stepRowHTML(s) {
    return `<li class="st" data-key="${s.key}" data-status="waiting">
      <button type="button" class="st-row" aria-controls="pane-${s.key}" aria-expanded="false">
        <span class="nd" aria-hidden="true"></span>
        <span class="when caps" data-when>Waiting</span>
        <span class="h">${esc(s.label)}</span>
        <span class="ag">${esc(s.agent)}</span>
        <span class="cw" data-cw></span>
        <span class="chev" aria-hidden="true"></span>
      </button>
      <div class="st-body" data-body></div>
    </li>`;
  }
  function endRowHTML() {
    return `<li class="st st-end" data-key="summary" data-status="waiting">
      <button type="button" class="st-row" aria-controls="pane-summary" aria-expanded="false">
        <span class="nd" aria-hidden="true"></span>
        <span class="when caps" data-when>The video</span>
        <span class="h" data-h>Goes to the top of Hot right now</span>
        <span class="cw" data-cw>When every step is done</span>
      </button>
    </li>`;
  }
  function callsHTML(s) {
    const maxU = Math.max(0.000001, ...s.calls.map((c) => +c.usd || 0));
    return `<details class="pn-sec pn-calls" data-sec="calls">
      <summary><span class="pn-h caps">Model calls</span><span class="sumline num" data-csum></span>
        <span class="cstrip" aria-hidden="true">${s.calls.map((c, k) => `<i data-k="${k}" style="--h:${Math.max(16, Math.round((+c.usd || 0) / maxU * 100))}%"></i>`).join('')}</span><span class="chev" aria-hidden="true"></span></summary>
      <ol class="calls">${s.calls.map((c, k) => `<li class="call" data-k="${k}">
        <div class="c1"><span class="cp">${esc(up(c.purpose))}</span><span class="cu num">${usd(c.usd)}</span></div>
        <div class="c2"><span class="cm">${esc(model(c.model))}</span><span class="ct num">${tokens(c.tokens_in, c.tokens_out)}</span><span class="cs num">${secs(c.seconds)}</span></div>
        ${c.note ? `<p class="cn${isWarn(c.note) ? ' warn' : ''}">${isWarn(c.note) ? I.redo : I.info}<span>${esc(up(c.note))}</span></p>` : ''}
        <p class="c-wait">Waiting for the answer<span class="dots3" aria-hidden="true"><i></i><i></i><i></i></span></p>
      </li>`).join('')}</ol>
    </details>`;
  }
  function searchesHTML(s) {
    return `<details class="pn-sec pn-searches" data-sec="searches">
      <summary><span class="pn-h caps">News searches</span><span class="sumline num" data-qsum></span><span class="chev" aria-hidden="true"></span></summary>
      <ol class="searches">${s.searches.map((q, k) => `<li class="srch" data-k="${k}">
        <div class="q1"><span class="qn caps">${esc(String(q.name || '').replace(/_/g, ' '))}</span><span class="qr num">${plural(q.results, 'result')}</span></div>
        <p class="qq serif">“${esc(q.query)}”</p>
        <p class="q2 num">${plural(q.credits, 'credit')}${q.seconds ? ` · ${secs(q.seconds)}` : ''}${q.note ? `<span class="qnote${isWarn(q.note) ? ' warn' : ''}">${isWarn(q.note) ? I.redo : I.info}${esc(up(q.note))}</span>` : ''}</p>
        <p class="c-wait">Searching<span class="dots3" aria-hidden="true"><i></i><i></i><i></i></span></p>
      </li>`).join('')}</ol>
    </details>`;
  }
  // When a step costs more than its model calls, say what the rest was (searches, the voice, or other work)
  function costNote(s) {
    if (s.skipped || s.end == null) return '';
    const calls = sum(s.calls, (c) => c.usd), rest = (+s.usd || 0) - calls;
    if (rest < 0.001) return '';
    const what = s.searches.length || s.key === 'gather' || (s.counts || {}).tavily_credits ? 'news searches' : s.key === 'video' ? 'the voice and the drawing' : RUN.calls_recorded ? 'other costs' : 'model calls';
    const txt = calls > 0 ? `Model calls ${usd(calls)} · ${what} ${usd(rest)}` : `${up(what)} ${usd(rest)}`;
    return `<p class="pn-cost num" data-costnote hidden>${txt}</p>`;
  }
  function paneHTML(s) {
    const next = nextOf(s), prev = STEPS[s.i - 1];
    const hoTitle = s.key === 'video' ? 'The finished video' : s.key === STOP ? (s.key === 'script' ? 'The line that failed' : 'Where it stopped') : next ? `What it hands the ${next.agent}` : 'What it made';
    const noCalls = s.end != null && !s.calls.length && !s.skipped;
    return `<section class="pane" id="pane-${s.key}" data-key="${s.key}" data-status="waiting" aria-labelledby="pt-${s.key}" hidden>
      <header class="pn-head">
        <div class="pn-top"><p class="pn-kick caps"><span class="stchip" data-chip>Waiting</span><span>Step ${s.i + 1} of ${N} · ${esc(s.agent)}</span></p>
          <button type="button" class="tolive" data-tolive hidden>${I.live}Back to ${isLive() ? 'live' : 'the replay'}</button></div>
        <h2 class="pn-title serif" id="pt-${s.key}">${esc(s.label)}</h2>
        <p class="pn-does">${esc(s.does)}</p>
        <p class="pn-now" data-now hidden></p>
        <dl class="pn-stats" data-stats>
          <div><dt>Time</dt><dd class="num" data-secs></dd></div>
          <div><dt>Cost</dt><dd class="num" data-usd></dd></div>
          <div><dt>Model calls</dt><dd class="num" data-ncalls></dd></div>
          ${s.searches.length ? '<div><dt>Searches</dt><dd class="num" data-nq></dd></div>' : ''}
        </dl>
        ${costNote(s)}
        <p class="pn-words serif" data-words></p>
      </header>
      <p class="pn-wait" data-waitnote>${s.skipped ? 'This step never started. The run stopped before it, so there is no voice and no video.' : prev ? `Starts when the ${esc(prev.agent)} is done.` : 'Starts right away.'}</p>
      <div class="pn-flow">
        ${s.skipped ? '' : `<section class="pn-sec pn-ho" aria-label="${esc(hoTitle)}">
          <h3 class="pn-h caps">${esc(hoTitle)}</h3>
          <div class="ho">${HANDON[s.key] && s.hands_on ? HANDON[s.key](s.hands_on) : s.end != null ? '<p class="ho-fine">This run didn’t save what this step handed on.</p>' : ''}</div>
          <div class="ho-wait" aria-hidden="true"><span class="sk"></span><span class="sk"></span><span class="sk s2"></span><p>You'll see it here when the step is done.</p></div>
        </section>`}
        ${s.calls.length ? callsHTML(s) : s.skipped ? '' : noCalls ? `<p class="pn-none">${RUN.calls_recorded ? 'This step made no model calls.' : 'This run was made before Stringer kept each model call, so only the step’s total is shown.'}</p>` : ''}
        ${s.searches.length ? searchesHTML(s) : ''}
      </div>
    </section>`;
  }

  // the end: a summary pane (done, stopped, or failed)
  function wentHTML() {
    const ran = STEPS.filter((s) => !s.skipped && s.end != null);
    const maxS = Math.max(0.001, ...ran.map((s) => +s.seconds || 0));
    const maxU = Math.max(0.000001, ...ran.map((s) => +s.usd || 0));
    return `<p class="ho-sub caps">Where the time and money went</p>
      <ul class="went">${ran.map((s) => `<li><span class="w-l">${esc(s.label)}</span>
        <span class="w-b"><i class="wt" style="width:${((+s.seconds || 0) / maxS * 100).toFixed(1)}%"></i><b class="num">${secs(s.seconds)}</b></span>
        <span class="w-b"><i class="wu" style="width:${((+s.usd || 0) / maxU * 100).toFixed(1)}%"></i><b class="num">${usd(s.usd)}</b></span></li>`).join('')}</ul>
      <p class="went-key"><span><i class="wt"></i>Time</span><span><i class="wu"></i>Money</span></p>`;
  }
  function summaryHTML() {
    const est = RUN.estimate_usd ? ` <span>of a ${usd(RUN.estimate_usd)} estimate</span>` : '';
    const nModels = new Set(ALL_CALLS.map((c) => c.model).filter(Boolean)).size;
    if (isDone()) {
      const h = (BY.video && BY.video.hands_on) || {}, fc = (BY.fact_check && BY.fact_check.counts) || {}, pk = (BY.balance_pick && BY.balance_pick.counts) || {};
      const hidden = RUN.record_state === 'hidden';
      return `<section class="pane pane-sum" id="pane-summary" data-key="summary" aria-labelledby="pt-summary" hidden>
        <div class="pn-top"><p class="pn-kick caps"><span class="stchip up">${hidden ? 'Hidden' : 'Up'}</span><span>Done in ${secs(RUN.seconds)}</span></p></div>
        <h2 class="pn-title serif big" id="pt-summary">${hidden ? 'It’s hidden for now.' : 'It’s up.'}</h2>
        <p class="sum-lede">${hidden ? `“${esc(VIDEO_TITLE)}” is hidden while we check a report.` : `“${esc(VIDEO_TITLE)}” is in Hot right now.`}</p>
        <div class="sum-act"><a class="btn btn-paper btn-sm" href="/feed">Watch in the feed ${I.arrow}</a><button type="button" class="btn btn-line btn-sm" data-replay>${I.replay}Replay the run</button></div>
        <dl class="facts sum-facts">
          ${h.length ? `<div><dt>Length</dt><dd>${esc(h.length)}</dd></div>` : ''}
          <div><dt>Read</dt><dd>${num(pk.picked || PICKED.length)} articles, ${SIDES ? '2 sides' : 'one group'}</dd></div>
          <div class="wide"><dt>Claims</dt><dd>${num(fc.confirmed)} confirmed, ${num(fc.say_with_source)} say who said it, ${num(fc.dropped)} dropped</dd></div>
          <div><dt>Cost</dt><dd>${usd(RUN.usd)}${est}</dd></div>
          <div><dt>Model calls</dt><dd>${num(RUN.model_calls ?? ALL_CALLS.length)}${nModels ? ` <span>using ${plural(nModels, 'model')}</span>` : ''}</dd></div>
        </dl>
        ${wentHTML()}
      </section>`;
    }
    const fb = BY.script && BY.script.hands_on && STOP === 'script' ? BY.script.hands_on.failed_beat : null;
    const why = fb ? `${fb.n === 1 ? 'The opening line' : `Beat ${fb.n}`} wasn’t backed by the articles, and the rewrite failed the same check, so Stringer stopped.` : plainWhy(RUN.why || RUN.no_video_reason) || 'The run stopped before the video.';
    const failed = KIND === 'failed';
    return `<section class="pane pane-sum stop" id="pane-summary" data-key="summary" aria-labelledby="pt-summary" hidden>
      <div class="pn-top"><p class="pn-kick caps"><span class="stchip stop">No video</span><span>Stopped after ${secs(RUN.seconds)}</span></p></div>
      <h2 class="pn-title serif big" id="pt-summary">${failed ? 'The run stopped.' : 'No video this time.'}</h2>
      <p class="sum-lede">${esc(failed ? (RUN.why ? 'Something went wrong while it was being made. Nothing went up, and it can be made again.' : why) : why)}</p>
      ${fb ? hoFailed(fb) : ''}
      <p class="sum-note">Nothing went up. Getting this far cost ${usd(RUN.usd)}${RUN.estimate_usd ? ` of the ${usd(RUN.estimate_usd)} estimate` : ''}.</p>
      <div class="sum-act"><a class="btn btn-paper btn-sm" href="/feed">Back to the feed ${I.arrow}</a><button type="button" class="btn btn-line btn-sm" data-replay>${I.replay}Replay the run</button></div>
      ${wentHTML()}
    </section>`;
  }

  // ================================================================================================
  // THE CARD IN THE MIDDLE: it fills in as the agents work, like the landing page's phone
  // ================================================================================================
  function frameHTML() {
    const g = BY.gather || { hands_on: null, searches: [] }, sf = BY.story_file || { counts: {}, hands_on: null }, sc = BY.script || { hands_on: null, counts: {} };
    const gh = g.hands_on || {}, sh = (BY.sides && BY.sides.hands_on) || {}, sch = sc.hands_on || {};
    const beats = sch.beats || [];
    const fb = sch.failed_beat;
    const byKeys = Object.keys(gh.by_side || {});
    const sideCl = (k, i) => (SIDES && k === SIDES.side_a.label ? 'a' : SIDES && k === SIDES.side_b.label ? 'b' : k === 'elsewhere' ? 'n' : i === 0 ? 'a' : i === 1 ? 'b' : 'n');
    const video = RUN.video;
    return `
      <div class="fr-top"><span class="caps" data-fr-kick>Being made</span><span class="caps fr-step" data-fr-step></span></div>
      <h1 class="fr-head serif">${esc(RUN.event)}</h1>
      <div class="fr-stage">
        <section class="ly ly-sides" data-ly="sides">
          <p class="ly-k caps">Who tells it differently</p>
          ${SIDES ? `<div class="fs a"><span class="caps">${esc(SIDES.side_a.label)}</span><p class="serif" data-dec>${SIDES.side_a.outlets.map(esc).join(', ')}</p></div>
          <div class="fs b"><span class="caps">${esc(SIDES.side_b.label)}</span><p class="serif" data-dec>${SIDES.side_b.outlets.map(esc).join(', ')}</p></div>`
          : `<div class="fs n"><span class="caps">No real divide</span><p class="serif" data-dec>${sh.reason ? 'The articles are read as one group.' : ''}</p></div>`}
          <p class="ly-note serif" data-dec>${esc(sh.reason || '')}</p>
        </section>
        <section class="ly ly-gather" data-ly="gather">
          <p class="big"><b data-g-n>0</b><i>articles found</i></p>
          <div class="gbar" aria-hidden="true">${byKeys.map((k, i) => `<span class="${sideCl(k, i)}" data-g-s="${i}" style="--w:0%"></span>`).join('')}</div>
          <p class="gkey">${SIDES ? `<span class="a">${esc(shortSide(SIDES.side_a.label))}</span><span class="b">${esc(shortSide(SIDES.side_b.label))}</span>` : ''}<span class="n">Elsewhere</span></p>
          <ol class="qlist">${g.searches.map((q, k) => `<li data-k="${k}"><span class="caps">${esc(String(q.name || '').replace(/_/g, ' '))}</span><span class="qq serif">${esc(q.query)}</span><b class="num">${q.results}</b></li>`).join('')}</ol>
        </section>
        <section class="ly ly-same_story" data-ly="same_story">
          <p class="ly-k caps">Is each article about this event?</p>
          <div class="dgrid">${SAME_V.map((v, i) => `<i data-i="${i}" data-v="${v}"></i>`).join('')}</div>
          <ul class="lg"><li class="same"><i></i><b data-s="same">0</b> about this event</li><li class="diff"><i></i><b data-s="diff">0</b> set aside</li><li class="fu"><i></i><b data-s="fu">0</b> follow-up</li></ul>
        </section>
        <section class="ly ly-balance_pick" data-ly="balance_pick">
          <p class="ly-k caps">About ten articles, ${SIDES ? 'both sides heard' : 'from many outlets'}</p>
          <ol class="plist">${PICKED.map((p, i) => `<li class="${sideCls(p.side)}" style="--i:${i}"><span class="caps">${esc(p.outlet)}</span><span class="serif">${esc(p.title)}</span></li>`).join('')}</ol>
          <p class="pflag" data-pflag>${I.redo}<span>One side was short, so it searched once more.</span></p>
        </section>
        <section class="ly ly-story_file" data-ly="story_file">
          <div class="rd">
            <div class="ly-row"><p class="ly-k caps">Reading each article in full</p><p class="caps rn num"><b data-r-n>0</b> of ${PICKED.length || '…'}</p></div>
            <ol class="rlist">${PICKED.map((p, i) => `<li class="${sideCls(p.side)}" data-i="${i}"><span class="caps">${esc(p.outlet)}</span><span class="serif">${esc(p.title)}</span><span class="tk">${I.check}</span></li>`).join('')}</ol>
            <p class="rcount num"><b data-r-f>0</b> facts noted, each with its exact quote</p>
          </div>
          <div class="merged" data-merged>
            <p class="ly-k caps">Merged into claims</p>
            <p class="big"><b>${num(sf.counts.claims)}</b><i>claims from ${num(sf.counts.facts)} facts</i></p>
            <ul class="mclaims">${((sf.hands_on || {}).claims_sample || []).map((c) => `<li><span class="cid">${esc(c.id)}</span><div><p class="serif">${esc(c.claim)}</p><p class="who">${esc(c.who_says)} · ${plural(c.articles, 'article')}</p></div></li>`).join('')}</ul>
          </div>
        </section>
        <section class="ly ly-fact_check" data-ly="fact_check">
          <p class="ly-k caps">Every claim, checked against the articles</p>
          <div class="cgrid">${CHECK_V.map((v, i) => `<i data-i="${i}" data-v="${v}"></i>`).join('')}</div>
          <ul class="lg"><li class="ok"><i></i><b data-c="ok">0</b> confirmed</li><li class="say"><i></i><b data-c="say">0</b> say who said it</li><li class="drop"><i></i><b data-c="drop">0</b> dropped</li></ul>
        </section>
        <section class="ly ly-script" data-ly="script">
          <div class="ly-row"><p class="ly-k caps">The script, beat by beat</p><p class="caps wc" data-wc></p></div>
          <ol class="sboard">${(beats.length ? beats : fb ? [fb] : []).map((b) => `<li data-n="${b.n}"${fb && b.n === fb.n ? ' class="flagged-beat"' : ''}>
              <div class="sb-h"><span class="bn">${b.n}</span>${shotIcon(b.shot)}<span class="caps">${esc(shotName(b.shot))}</span><span class="sb-flag">${I.cross}</span><span class="sb-ok">${I.check}</span></div>
              <p class="serif">${esc(b.say || '')}</p></li>`).join('')}</ol>
        </section>
        <section class="ly ly-video" data-ly="video">
          <p class="vt serif" data-dec>${esc(isDone() ? VIDEO_TITLE : '')}</p>
          <div class="thumb">${video && video.poster ? `<img src="${esc(video.poster)}" alt="" data-reveal onerror="this.remove()">` : ''}<span class="scan"></span></div>
          <ol class="vparts">${((BY.video || {}).parts || []).map((p) => `<li data-part="${p.part}"><i></i><span>${esc(p.label)}</span></li>`).join('')}</ol>
          ${(((BY.video || {}).hands_on) || {}).frames ? `<p class="frames num"><b data-v-f>0</b> of ${num(BY.video.hands_on.frames)} frames</p>` : ''}
        </section>
        <section class="ly ly-stop" data-ly="stop">
          ${stopped() ? `<p class="ly-k caps stopk">${I.cross}Stopped at ${esc(STOP ? BY[STOP].label.toLowerCase() : 'the start')}</p>
          ${fb ? `<div class="stopcard"><div class="sb-h"><span class="bn">${fb.n}</span>${shotIcon(fb.shot)}<span class="caps">${esc(shotName(fb.shot))}</span></div>
            <p class="serif"><s>${esc(fb.say)}</s></p><p class="stamp">Not backed</p></div>` : ''}
          <p class="stopwhy serif">${esc(fb && fb.why ? plainWhy(fb.why) : plainWhy(RUN.why || RUN.no_video_reason) || 'The run stopped.')}</p>
          <p class="stopnote">${KIND === 'failed' ? 'Nothing went up. The video can be made again.' : 'Stringer only says what the articles back up, so it didn’t make this video.'}</p>
          <p class="stopspent num">${STEPS.filter((s) => s.start != null).length} of ${N} steps ran · ${usd(RUN.usd)} spent</p>` : ''}
        </section>
      </div>
      <ol class="fr-bar" aria-hidden="true">${STEPS.map((s) => `<li data-key="${s.key}"><i></i></li>`).join('')}</ol>
      ${isDone() && video && video.src ? `<div class="fr-video" data-frvideo>${video.poster ? `<img class="poster" src="${esc(video.poster)}" alt="" onerror="this.remove()">` : ''}<video muted playsinline loop preload="none" data-src="${esc(video.src)}" aria-label="Video: ${esc(VIDEO_TITLE)}. Made with AI."></video></div>` : ''}`
;
  }

  // ================================================================================================
  // BUILD (again, whenever the record changes: a step ends, calls arrive, the run finishes)
  // ================================================================================================
  const frame = $('#frame');
  const steps = document.createElement('ol');
  steps.className = 'steps-tl';
  steps.id = 'steps';
  steps.setAttribute('aria-label', 'The steps');
  steps.innerHTML = STEPS.map(stepRowHTML).join('') + endRowHTML();
  const ROWS = Object.fromEntries($$('.st', steps).map((r) => [r.dataset.key, r]));
  const PANES = {};
  const SIG = {};
  const sigOf = (s) => `${s.status}|${s.start}|${s.end}|${s.calls.length}|${s.searches.length}|${s.hands_on ? 1 : 0}|${KIND}`;
  function swapPane(key, html) {
    const host = document.createElement('div');
    host.innerHTML = html;
    const el = host.firstElementChild;
    const old = PANES[key];
    if (old) {
      // keep which sections were opened by hand
      $$('details.pn-sec', old).forEach((d) => { const n = $(`details[data-sec="${d.dataset.sec}"]`, el); if (n && d.dataset.touched) { n.open = d.open; n.dataset.touched = '1'; } });
      el.hidden = old.hidden;
      old.replaceWith(el);
    }
    PANES[key] = el;
    $$('details.pn-sec', el).forEach((d) => d.addEventListener('toggle', () => { d.dataset.touched = '1'; }));
    return el;
  }
  let frameSig = '';
  function paint() {
    for (const s of STEPS) {
      const sg = sigOf(s);
      if (SIG[s.key] !== sg) { SIG[s.key] = sg; swapPane(s.key, paneHTML(s)); }
    }
    const ss = `${KIND}|${RUN.seconds}|${RUN.usd}|${RUN.record_state}`;
    if (SIG.summary !== ss) { SIG.summary = ss; swapPane('summary', summaryHTML()); }
    const fs = STEPS.map((s) => `${s.end}|${s.hands_on ? 1 : 0}|${s.searches.length}`).join(',') + KIND + !!RUN.video;
    if (fs !== frameSig) {
      frameSig = fs;
      frame.innerHTML = frameHTML();
      for (const k in prev) prev[k] = undefined;      // settle without one-off effects
      wireVideo();
    }
    // the event and its money
    $('#story-head').innerHTML = `<p class="rs-kicker caps"><span class="pill pill-mk" data-headpill>Being made</span><span>${esc(window.SG.cap(EVENT.category || ''))} · ${esc(window.SG.cap(EVENT.subtype || ''))} · ${esc(EVENT.country || '')}</span></p>
      <p class="rs-headline serif">${esc(RUN.event)}</p>
      <p class="rs-meta">${RUN.by === 'you' ? 'You started it' : RUN.by ? 'Another student started it' : 'Started'}${RUN.started ? ` at ${esc(window.SG.clock(RUN.started))}` : ''}${!isLive() && RUN.started ? `, ${esc(window.SG.shortDay(RUN.started).toLowerCase())}` : ''}.<span class="rs-usual"> Most runs take ${esc((window.STRINGER_DEMO.site || {}).minutesPerVideo || '4–5')} minutes.</span> Events by <b>Monitor the Situation</b>.</p>`;
    const est = RUN.estimate_usd ? usd(RUN.estimate_usd) : null, cap = money(RUN.cap_usd || 5);
    setText($('.b-money .of-l'), est ? `of ${est} estimate` : '');
    setText($('.b-money .of-s'), est ? `of ${est} est. · stops at ${cap}` : `stops at ${cap}`);
    setText($('.b-money .k'), `Stops by itself at ${cap}`);
    setText($('.b-time .k-l'), ` · usually ${((window.STRINGER_DEMO.site || {}).minutesPerVideo || '4–5').replace('–', ' to ')} min`);
    pg.dataset.run = isDone() ? 'done' : stopped() ? 'novideo' : 'running';
    pg.toggleAttribute('data-live', isLive());
    setText($('.b-demo .demo-tag'), 'Replay');
    force = true;
  }

  // lip dots
  $('#lip-dots').innerHTML = STEPS.map((s) => `<i data-key="${s.key}"></i>`).join('');

  // ================================================================================================
  // LAYOUT: desktop rails, tablet accordion, phone sheet. The same nodes move between slots.
  // ================================================================================================
  const mqDesk = window.matchMedia('(min-width: 1180px)');
  const mqPhone = window.matchMedia('(max-width: 759.98px)');
  const layout = () => (mqDesk.matches ? 'desk' : mqPhone.matches ? 'phone' : 'tab');
  let L = '';
  function place() {
    const nl = layout();
    if (nl === L) return;
    L = nl;
    pg.dataset.layout = L;
    $(L === 'desk' ? '#steps-slot-l' : L === 'tab' ? '#steps-slot-r' : '#steps-slot-s').append(steps);
    for (const s of STEPS) (L === 'desk' ? $('#detail') : $('[data-body]', ROWS[s.key])).append(PANES[s.key]);
    (L === 'desk' ? $('#detail') : $(L === 'tab' ? '#sum-slot-r' : '#sum-slot-s')).append(PANES.summary);
    if (L !== 'phone') closeSheet(true);
    force = true;
  }
  // a pane swapped while placed keeps its slot (replaceWith); a new one goes where its step's panes go
  function placePanes() {
    for (const s of STEPS) { const p = PANES[s.key]; if (!p.isConnected) (L === 'desk' ? $('#detail') : $('[data-body]', ROWS[s.key])).append(p); }
    if (!PANES.summary.isConnected) (L === 'desk' ? $('#detail') : $(L === 'tab' ? '#sum-slot-r' : '#sum-slot-s')).append(PANES.summary);
  }

  // ================================================================================================
  // SELECTION: desktop follows the running step until you pick another; narrow screens open the running one
  // ================================================================================================
  let follow = true;
  let sel = qs.get('step') && (BY[qs.get('step')] || qs.get('step') === 'summary') ? qs.get('step') : null;
  if (sel) follow = false;
  const opened = new Set();        // steps opened by hand (narrow layouts)
  const shut = new Set();          // running steps closed by hand (they'd otherwise open on their own)
  if (sel && sel !== 'summary') opened.add(sel);
  const isOpen = (key, cur) => opened.has(key) || (!!cur && cur.key === key && !shut.has(key));

  function liveKey(t) {
    const c = currentStep(t);
    if (c) return c.key;
    if (t >= END) return 'summary';
    const started = STEPS.filter((s) => s.start != null && t >= s.start);
    return started.length ? started[started.length - 1].key : STEPS[0].key;
  }
  function select(key, byHand) {
    sel = key;
    follow = !byHand || key === liveKey(t);
    force = true;
    render();
    if (L === 'desk') { const p = PANES[key]; if (p) { $('#drail').scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' }); } }
  }
  steps.addEventListener('click', (e) => {
    const row = e.target.closest('.st-row');
    if (!row) return;
    const key = row.closest('.st').dataset.key;
    if (L === 'desk') { select(key, true); return; }
    if (key === 'summary') { PANES.summary.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' }); return; }
    const cur = currentStep(t);
    if (isOpen(key, cur)) { opened.delete(key); if (cur && cur.key === key) shut.add(key); }
    else { opened.add(key); shut.delete(key); }
    force = true; render();
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-tolive]')) { follow = true; force = true; render(); }
    if (e.target.closest('[data-replay]')) replay();
  });

  // ================================================================================================
  // THE CLOCK: a live run follows the server's clock; a finished run sits at its end or replays at 1x or 10x
  // ================================================================================================
  let fetchedAt = performance.now();
  let liveBase = +RUN.elapsed || 0;
  const liveT = () => liveBase + (performance.now() - fetchedAt) / 1000;
  const atParam = qs.get('at');
  let t = isLive() ? liveT() : atParam != null && atParam !== 'end' ? Math.max(0, Math.min(END, parseFloat(atParam) || 0)) : END;
  let speed = qs.get('speed') === '1' ? 1 : 10;
  let paused = qs.has('still');
  let ended = t >= END;
  let force = true;
  let last = performance.now();
  const prev = {};                 // last status per step, to fire one-off effects

  function loop(now) {
    const dt = Math.min(0.25, (now - last) / 1000);
    last = now;
    if (isLive()) { if (!qs.has('still')) { t = liveT(); force = true; } }
    else if (!paused && t < END) { t = Math.min(END, t + dt * speed); force = true; }
    if (force) render();
    requestAnimationFrame(loop);
  }

  // ================================================================================================
  // RENDER: write only what changed
  // ================================================================================================
  function setText(el, v) { if (el && el.textContent !== v) el.textContent = v; }
  const setAttr = (el, k, v) => { if (el && el.getAttribute(k) !== v) el.setAttribute(k, v); };
  const tog = (el, cls, on) => { if (el && el.classList.contains(cls) !== on) el.classList.toggle(cls, on); };
  const band = {
    no: $('#b-no'), label: $('#b-label'), time: $('#b-time'), timeK: $('#b-time-k'), usd: $('#b-usd'),
    fill: $('#spend-fill'), calls: $('#b-calls'), credits: $('#b-credits'),
  };
  let lastAnnounced = '';
  let ctlState = '';

  function render() {
    force = false;
    const cur = currentStep(t);
    const atEnd = t >= END;
    const state = atEnd ? (isDone() ? 'done' : 'novideo') : 'running';
    if (pg.dataset.state !== state) pg.dataset.state = state;
    if (atEnd && !ended) { ended = true; onEnd(false); }
    if (!atEnd && ended) ended = false;
    const key = liveKey(t);
    if (follow) sel = key;

    // ---- band ----
    const stepNo = cur ? cur.i + 1 : atEnd ? N : Math.max(1, STEPS.filter((s) => s.start != null && t >= s.start).length);
    setText(band.no, atEnd ? (isDone() ? 'Done' : 'Stopped') : `Step ${stepNo} of ${N}`);
    const lab = atEnd ? (isDone() ? 'It’s up' : KIND === 'failed' ? 'The run stopped' : 'No video this time') : cur ? cur.label : (BY[key] || STEPS[0]).label;
    if (lab !== lastAnnounced) { setText(band.label, lab); lastAnnounced = lab; }
    setText(band.time, clock(atEnd ? END : t));
    setText(band.timeK, atEnd ? (isDone() ? 'Took' : 'Ran for') : 'Elapsed');
    const u = spentAt(t);
    setText(band.usd, u >= 0.1 ? usd(u) : u < 0.0005 ? '$0' : `$${u.toFixed(3)}`);
    band.fill.style.setProperty('--p', `${Math.min(100, u / (RUN.estimate_usd || RUN.cap_usd || 5) * 100).toFixed(2)}%`);
    setText(band.calls, String(callsAt(t)));
    setText(band.credits, String(searchesAt(t)));

    // ---- steps, rows and panes ----
    for (const s of STEPS) {
      const st = status(s, t), row = ROWS[s.key], pane = PANES[s.key];
      if (prev[s.key] !== st) { onStatus(s, st, prev[s.key]); prev[s.key] = st; }
      setAttr(row, 'data-status', st);
      setAttr(pane, 'data-status', st);
      tog(row, 'is-sel', L === 'desk' && sel === s.key);
      const fin = st === 'done' || st === 'stopped';
      const when = st === 'waiting' ? 'Waiting' : st === 'running' ? `Running · ${clock(t - s.start)}` : st === 'skipped' ? 'Didn’t run' : `${st === 'stopped' ? 'Stopped' : 'Done'} · ${secs(s.seconds)} · ${usd(s.usd)}`;
      setText($('[data-when]', row), when);
      setText($('[data-cw]', row), words(s, t));
      if (st === 'running') setAttr($('.st-row', row), 'aria-current', 'step'); else $('.st-row', row).removeAttribute('aria-current');
      // pane header
      setText($('[data-chip]', pane), { waiting: 'Waiting', running: 'Running', done: 'Done', stopped: 'Stopped', skipped: 'Didn’t run' }[st]);
      const callsIn = arrived(s.calls, t), qIn = arrived(s.searches, t);
      const known = s.end != null;                        // a finished step: its totals are known
      setText($('[data-secs]', pane), st === 'waiting' || st === 'skipped' ? 'not yet' : fin ? secs(s.seconds) : clock(t - s.start));
      setText($('[data-usd]', pane), st === 'waiting' || st === 'skipped' ? 'not yet' : fin ? usd(s.usd) : usd(spentInStep(s, t)));
      setText($('[data-ncalls]', pane), st === 'waiting' || st === 'skipped' ? 'not yet' : fin && !s.calls.length && !RUN.calls_recorded ? 'not kept' : `${callsIn.length}${!fin && known ? ` of ${s.calls.length}` : ''}`);
      const nq = $('[data-nq]', pane);
      if (nq) setText(nq, st === 'waiting' ? 'not yet' : `${qIn.length}${!fin && known ? ` of ${s.searches.length}` : ''}`);
      setText($('[data-words]', pane), words(s, t));
      const cn = $('[data-costnote]', pane);
      if (cn) cn.hidden = !fin;
      const nowEl = $('[data-now]', pane);
      if (st === 'running') { nowEl.hidden = false; const nd = nowDoing(s, t); if (nowEl.dataset.v !== nd) { nowEl.dataset.v = nd; nowEl.innerHTML = `${I.live}<span>${isLive() ? 'Latest' : 'Now'}: ${esc(nd)}</span>`; } }
      else if (!nowEl.hidden) nowEl.hidden = true;
      const tl = $('[data-tolive]', pane);
      if (tl) tl.hidden = !(L === 'desk' && !follow && sel === s.key && !atEnd);
      // calls and searches
      $$('.call', pane).forEach((li, k) => {
        const c = s.calls[k], inn = c.t != null && c.t <= t;
        tog(li, 'in', inn);
        tog(li, 'pending', !inn && st === 'running' && (k === 0 || s.calls[k - 1].t <= t));
      });
      $$('.cstrip i', pane).forEach((i, k) => tog(i, 'on', s.calls[k].t != null && s.calls[k].t <= t));
      const csum = $('[data-csum]', pane);
      if (csum) setText(csum, callsIn.length ? `${callsIn.length} · ${tokens(sum(callsIn, (c) => c.tokens_in), sum(callsIn, (c) => c.tokens_out))} · ${usd(sum(callsIn, (c) => c.usd))}` : st === 'running' ? 'First answer on its way' : 'None yet');
      $$('.srch', pane).forEach((li, k) => {
        const q = s.searches[k], inn = q.t != null && q.t <= t;
        tog(li, 'in', inn);
        tog(li, 'pending', !inn && st === 'running' && arrived(s.searches, t).length === k);
      });
      const qsum = $('[data-qsum]', pane);
      if (qsum) setText(qsum, qIn.length ? `${qIn.length} · ${plural(sum(qIn, (q) => q.results), 'result')} · ${plural(sum(qIn, (q) => q.credits), 'credit')}` : 'None yet');
      // the calls list is open while the step runs, then folds so the hand-on leads
      const det = $('.pn-calls', pane), det2 = $('.pn-searches', pane);
      if (st !== pane.dataset.lastSt) {
        if (det && !det.dataset.touched) det.open = st === 'running';
        if (det2 && !det2.dataset.touched) det2.open = st === 'running';
        pane.dataset.lastSt = st;
      }
      // visibility
      const open = L === 'desk' ? sel === s.key : isOpen(s.key, cur);
      if (pane.hidden === open) pane.hidden = !open;
      setAttr($('.st-row', row), 'aria-expanded', String(L !== 'desk' && open));
      if (L === 'desk') setAttr($('.st-row', row), 'aria-pressed', String(sel === s.key)); else $('.st-row', row).removeAttribute('aria-pressed');
      tog(row, 'open', L !== 'desk' && open);
    }
    // the end row and the summary pane
    const endRow = ROWS.summary;
    setAttr(endRow, 'data-status', atEnd ? (isDone() ? 'up' : 'novideo') : 'waiting');
    setText($('[data-when]', endRow), atEnd ? (isDone() ? `Up · ${window.SG.shortDay(RUN.updated || RUN.started)}` : 'No video') : 'The video');
    setText($('[data-h]', endRow), atEnd && isDone() ? VIDEO_TITLE : atEnd ? 'Nothing went up' : 'Goes to the top of Hot right now');
    const vh = (BY.video && BY.video.hands_on) || {};
    setText($('[data-cw]', endRow), atEnd ? (isDone() ? (vh.length ? `${vh.length} long` : 'In Hot right now') : words(BY[STOP] || STEPS[0], END) || 'Stopped') : 'When every step is done');
    tog(endRow, 'is-sel', L === 'desk' && sel === 'summary');
    const showSum = atEnd && (L !== 'desk' || sel === 'summary');
    if (PANES.summary.hidden === showSum) PANES.summary.hidden = !showSum;
    setText($('[data-headpill]'), atEnd ? (isDone() ? (RUN.record_state === 'hidden' ? 'Hidden' : 'Up') : 'No video') : 'Being made');

    renderFrame(t, cur, atEnd);
    renderUnder(atEnd);
    renderLip(t, atEnd);
    const pk = isLive() ? 'live' : atEnd ? 'end' : paused ? 'paused' : 'playing';
    if (ctlState !== pk) {
      ctlState = pk;
      $('#b-pause').innerHTML = pk === 'playing' ? I.pause : pk === 'paused' ? I.play : I.replay;
      $('#b-pause').setAttribute('aria-label', pk === 'end' ? 'Replay from the start' : pk === 'paused' ? 'Resume the replay' : 'Pause the replay');
      $('#b-skip').innerHTML = pk === 'end' ? `${I.replay}<span>Replay</span>` : `${I.skip}<span>Skip to end</span>`;
      $('#b-skip').hidden = pk === 'end';
    }
  }

  // one-off effects when a step changes state
  function onStatus(s, st, was) {
    if (st === 'running' && L === 'desk' && follow && was !== undefined) {
      const r = ROWS[s.key], rail = $('#srail');
      const rb = r.getBoundingClientRect(), cb = rail.getBoundingClientRect();
      if (rb.bottom > cb.bottom - 24 || rb.top < cb.top) rail.scrollTo({ top: rail.scrollTop + rb.top - cb.top - cb.height * 0.35, behavior: reduced() ? 'auto' : 'smooth' });
    }
    if (was === undefined) {                         // first paint: no effects, just settle
      if (st !== 'waiting') $$(`.ly-${s.key} [data-dec]`, frame).forEach((el) => { el.textContent = el.dataset.text || el.textContent; });
      return;
    }
    if (s.key === 'sides' && st === 'done') $$('.ly-sides [data-dec]', frame).forEach((el, i) => decode(el, { delay: i * 160, perChar: 14, max: 900 }));
    if (s.key === 'video' && st === 'running') $$('.ly-video [data-dec]', frame).forEach((el) => decode(el, { delay: 200, perChar: 28 }));
  }

  // ---- the card ---------------------------------------------------------------------------------
  function renderFrame(t, cur, atEnd) {
    const startedKeys = STEPS.filter((s) => s.start != null && t >= s.start);
    const stage = atEnd ? (isDone() ? 'video' : 'stop') : cur ? cur.key : startedKeys.length ? startedKeys[startedKeys.length - 1].key : 'sides';
    setAttr(frame, 'data-stage', stage);
    setAttr(frame, 'data-end', atEnd ? (isDone() ? 'up' : 'stop') : '');
    setText($('[data-fr-kick]', frame), atEnd ? (isDone() ? 'Made with AI' : 'No video') : isLive() ? 'Being made · live' : 'Being made · replay');
    setText($('[data-fr-step]', frame), atEnd ? '' : (cur || BY[stage] || STEPS[0]).agent);
    $$('.fr-bar li', frame).forEach((li) => {
      const s = BY[li.dataset.key], st = status(s, t);
      setAttr(li, 'class', st);
      if (st === 'running') {
        const f = frac(s, t);
        const p = f != null ? f : Math.min(0.92, (t - s.start) / Math.max(1, s.typical_s || 30));   // live: against the step's usual time
        li.style.setProperty('--p', `${(p * 100).toFixed(1)}%`);
      }
    });
    // sides: skeleton until done
    if (BY.sides) tog($('.ly-sides', frame), 'filled', status(BY.sides, t) !== 'running' && status(BY.sides, t) !== 'waiting');
    // gather
    const g = BY.gather, found = foundAt(t);
    setText($('[data-g-n]', frame), num(found));
    if (g && g.hands_on) {
      const totals = Object.values(g.hands_on.by_side || {});
      $$('[data-g-s]', frame).forEach((el, i) => el.style.setProperty('--w', `${ARTICLES ? (totals[i] * found / ARTICLES / ARTICLES * 100).toFixed(2) : 0}%`));
    }
    const qIn = g ? arrived(g.searches, t).length : 0;
    $$('.qlist li', frame).forEach((li, k) => { tog(li, 'in', k < qIn); tog(li, 'new', k === qIn - 1 && g.end != null && t < g.end); });
    // same story
    const judged = judgedAt(t), cnt = { same: 0, diff: 0, fu: 0 };
    $$('.dgrid i', frame).forEach((el, i) => { const on = i < judged; tog(el, 'on', on); if (on) cnt[el.dataset.v]++; });
    for (const k in cnt) setText($(`[data-s="${k}"]`, frame), String(cnt[k]));
    // balance
    const bp = BY.balance_pick;
    if (bp) {
      tog($('.ly-balance_pick', frame), 'filled', bp.end != null && t >= bp.end);
      const short = +(bp.counts || {}).short_sides || 0;          // a side came up short: it searched once more
      tog($('[data-pflag]', frame), 'in', short > 0 && bp.end != null && t >= bp.start + (bp.end - bp.start) / 2);
    }
    // reading
    const rn = readAt(t), sf = BY.story_file;
    $$('.rlist li', frame).forEach((li, i) => { tog(li, 'done', i < rn); tog(li, 'now', !!sf && i === rn && sf.start != null && t >= sf.start && (sf.end == null || t < sf.end) && rn < PICKED.length); });
    setText($('[data-r-n]', frame), String(rn));
    setText($('[data-r-f]', frame), num(sf && PICKED.length ? Math.round((+sf.counts.facts || 0) * rn / PICKED.length) : 0));
    tog($('.ly-story_file', frame), 'is-merged', !!mergedAt(t));
    // fact check
    const checked = checkedAt(t), cc = { ok: 0, say: 0, drop: 0 };
    $$('.cgrid i', frame).forEach((el, i) => { const on = i < checked; tog(el, 'on', on); if (on) cc[el.dataset.v]++; });
    for (const k in cc) setText($(`[data-c="${k}"]`, frame), String(cc[k]));
    // script
    const sc = BY.script;
    if (sc) {
      const board = $('.sboard', frame);
      const f = frac(sc, t);
      const written = sc.end != null && t >= sc.end;
      tog(board, 'written', written || (f != null && f > 0.25));
      if (isDone()) { tog(board, 'is-flag', false); tog(board, 'is-fixed', written); setText($('[data-wc]', frame), written ? `${num(sc.counts.words || (sc.hands_on || {}).words)} words` : ''); }
      else if (stopped() && STOP === 'script') { tog(board, 'is-flag', f != null && f > 0.4); setText($('[data-wc]', frame), f != null && f > 0.6 ? 'A line isn’t backed' : ''); }
    }
    // video
    const v = BY.video;
    if (v && isDone() && v.parts.length) {
      const p = partAt(t), fr = framesAt(t);
      $$('.vparts li', frame).forEach((li) => { const part = v.parts.find((x) => x.part === li.dataset.part); tog(li, 'done', t >= part.to); tog(li, 'now', !!p && p.part === part.part && t < part.to); });
      setText($('[data-v-f]', frame), num(fr));
      const r = $('[data-reveal]', frame);
      const rp = v.parts.find((x) => x.part === 'render');
      if (r) r.style.setProperty('--r', `${(v.hands_on && v.hands_on.frames ? fr / v.hands_on.frames : rp ? Math.max(0, Math.min(1, (t - rp.from) / Math.max(0.001, rp.to - rp.from))) : 1) * 100}%`);
    }
  }

  // ---- under the card (desktop and tablet) ---------------------------------------------------------
  let underState = '';
  function renderUnder(atEnd) {
    const st = atEnd ? (isDone() ? 'up' : 'stop') : 'running';
    if (st === underState) { if (st === 'up') syncVideoBtns(); return; }
    underState = st;
    const u = $('#under');
    if (st === 'running') {
      u.innerHTML = `<div class="ub"><span class="ub-node mk" aria-hidden="true"></span><p><b>Part 1 of 1</b> · being made</p></div><p class="ub-note">${isLive() ? 'Live' : 'Replay'}</p>`;
    } else if (st === 'up') {
      u.innerHTML = `${vid ? `<button type="button" class="ctl" data-vplay aria-label="Pause the video">${I.pause}</button><button type="button" class="ctl" data-vsound aria-label="Turn the sound on">${I.soundOff}</button>` : ''}
        <div class="ub"><span class="ub-node up" aria-hidden="true"></span><p><b>Part 1 of 1</b></p></div><a class="ub-link" href="/feed">Watch in the feed ${I.arrow}</a>`;
      syncVideoBtns();
    } else {
      u.innerHTML = `<div class="ub"><span class="ub-node stop" aria-hidden="true"></span><p><b>No video</b> · nothing went up</p></div><a class="ub-link" href="/feed">Back to the feed ${I.arrow}</a>`;
    }
  }

  // ---- the lip (phone) ---------------------------------------------------------------------------
  function renderLip(t, atEnd) {
    $$('#lip-dots i').forEach((i) => { const s = BY[i.dataset.key]; setAttr(i, 'class', status(s, t)); });
    const sp = $('#lip-speed');
    sp.hidden = atEnd || isLive();
    setText(sp, `${speed}×`);
    setAttr(sp, 'aria-label', speed === 10 ? 'Replay speed: 10 times. Switch to normal speed' : 'Replay speed: normal. Switch to 10 times');
    const sk = $('#lip-skip'), lk = isLive() ? 'none' : atEnd ? (isDone() ? 'icon' : 'Replay') : 'Skip';
    if (sk.dataset.k !== lk) {
      sk.dataset.k = lk;
      sk.hidden = lk === 'none';
      sk.innerHTML = lk === 'icon' ? I.replay : lk === 'none' ? '' : lk;
      if (lk === 'icon') sk.setAttribute('aria-label', 'Replay the run'); else sk.removeAttribute('aria-label');
    }
    $('#lip-feed').hidden = !(atEnd && isDone());
    tog($('#lip'), 'is-up', atEnd && isDone());
    setText($('#sheet-sub'), atEnd ? (isDone() ? `Done in ${secs(RUN.seconds)} · ${callsAt(END)} model calls · ${usd(RUN.usd)}` : `Stopped after ${secs(RUN.seconds)} · ${usd(RUN.usd)} spent`) : `${callsAt(t) === '–' ? 'Replaying' : `${callsAt(t)} model calls so far`} · ${usd(spentAt(t))}`);
  }

  // ================================================================================================
  // THE VIDEO (done) and THE END
  // ================================================================================================
  let vwrap = null, vid = null;
  function wireVideo() {
    vwrap = $('[data-frvideo]', frame);
    vid = vwrap ? $('video', vwrap) : null;
    underState = '';
    if (!vid) return;
    vid.addEventListener('play', () => { vwrap.classList.add('playing'); syncVideoBtns(); });
    vid.addEventListener('pause', syncVideoBtns);
    vwrap.addEventListener('click', () => { if (vid.paused) { if (!vid.getAttribute('src')) vid.src = vid.dataset.src; vid.play().catch(() => {}); } else vid.pause(); });
  }
  function playVideo() {
    if (!vid) return;
    if (!vid.getAttribute('src')) vid.src = vid.dataset.src;
    if (reduced() || qs.has('still')) return;
    vid.play().then(() => vwrap.classList.add('playing')).catch(() => {});
  }
  function stopVideo() { if (vid && vid.getAttribute('src')) { vid.pause(); vwrap.classList.remove('playing'); } }
  function syncVideoBtns() {
    const p = $('[data-vplay]'), s = $('[data-vsound]');
    if (!p || !vid) return;
    const playing = !vid.paused && !!vid.getAttribute('src');
    if (p.dataset.v !== String(playing)) { p.dataset.v = String(playing); p.innerHTML = playing ? I.pause : I.play; p.setAttribute('aria-label', playing ? 'Pause the video' : 'Play the video'); }
    if (s.dataset.v !== String(vid.muted)) { s.dataset.v = String(vid.muted); s.innerHTML = vid.muted ? I.soundOff : I.soundOn; s.setAttribute('aria-label', vid.muted ? 'Turn the sound on' : 'Turn the sound off'); }
  }
  document.addEventListener('click', (e) => {
    if (!vid) return;
    if (e.target.closest('[data-vplay]')) { if (vid.paused) { if (!vid.getAttribute('src')) vid.src = vid.dataset.src; vid.play().catch(() => {}); } else vid.pause(); }
    if (e.target.closest('[data-vsound]')) { vid.muted = !vid.muted; syncVideoBtns(); }
  });

  function onEnd(live) {
    if (follow) sel = 'summary';
    if (isDone()) {
      playVideo();
      if (live && !qs.has('still')) toast(`It's up: “${esc(VIDEO_TITLE)}” is at the top of Hot right now.`, { ms: 7000, action: { label: 'Watch', run: () => { location.href = '/feed'; } } });
    } else if (live && !qs.has('still')) {
      toast(KIND === 'failed' ? 'The run stopped before the video. Nothing went up.' : 'No video this time. Stringer couldn’t back up what it would say.', { ms: 6000 });
    }
  }
  function replay() {
    if (isLive()) return;
    t = 0; paused = false; ended = false; follow = true; opened.clear(); shut.clear();
    stopVideo();
    if (vwrap) vwrap.classList.remove('playing');
    force = true;
  }
  function skip() {
    if (isLive()) return;
    if (t >= END) { replay(); return; }
    t = END; force = true;
  }

  // ================================================================================================
  // LIVE: ask the site again every 2.5 s until the run ends
  // ================================================================================================
  let pollT = null;
  function poll() {
    clearTimeout(pollT);
    if (!isLive() || qs.has('still')) return;
    pollT = setTimeout(async () => {
      if (document.hidden) { poll(); return; }
      try {
        const sr = await GET(`/api/progress?event=${encodeURIComponent(EVENT_ID)}`);
        const was = KIND;
        SR = sr;
        build(sr);
        pictures();
        index();
        fetchedAt = performance.now();
        liveBase = +sr.elapsed || liveBase;
        paint();
        placePanes();
        if (was === 'running' && !isLive()) {
          // the run just ended: jump to its end and say so
          t = END; ended = true; follow = true; sel = 'summary';
          render();
          onEnd(true);
          return;
        }
      } catch (err) { /* keep the last record; try again */ }
      poll();
    }, 2500);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && isLive()) poll(); });

  // ================================================================================================
  // CONTROLS
  // ================================================================================================
  function setSpeed(v) {
    speed = v;
    $$('[data-speed]').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.speed === v)));
    force = true;
  }
  $$('[data-speed]').forEach((b) => b.addEventListener('click', () => setSpeed(+b.dataset.speed)));
  $('#b-pause').addEventListener('click', () => { if (isLive()) return; if (t >= END) { replay(); return; } paused = !paused; force = true; });
  $('#b-skip').addEventListener('click', skip);
  $('#lip-skip').addEventListener('click', skip);
  $('#lip-speed').addEventListener('click', () => setSpeed(speed === 10 ? 1 : 10));
  setSpeed(speed);

  // ---- the phone sheet ------------------------------------------------------------------------------
  const sheet = $('#sheet');
  function openSheet() {
    sheet.style.setProperty('--top', `${Math.round($('#band').getBoundingClientRect().bottom)}px`);
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add('in'));
    $('#lip-open').setAttribute('aria-expanded', 'true');
    pg.classList.add('sheet-open');
    const cur = $('.st[data-status="running"] .st-row', sheet) || $('#sheet-close');
    setTimeout(() => { $('#sheet-close').focus({ preventScroll: true }); if (cur && cur !== $('#sheet-close')) cur.scrollIntoView({ block: 'center' }); }, reduced() ? 0 : 60);
  }
  function closeSheet(instant) {
    if (sheet.hidden) return;
    sheet.classList.remove('in');
    $('#lip-open').setAttribute('aria-expanded', 'false');
    pg.classList.remove('sheet-open');
    const done = () => { sheet.hidden = true; };
    if (instant || reduced()) done(); else setTimeout(done, 380);
    if (!instant) $('#lip-open').focus({ preventScroll: true });
  }
  $('#lip-open').addEventListener('click', openSheet);
  $('#sheet-close').addEventListener('click', () => closeSheet());
  // swipe the lip up to open, the sheet's top down to close
  let y0 = null;
  $('#lip').addEventListener('pointerdown', (e) => { y0 = e.clientY; });
  $('#lip').addEventListener('pointerup', (e) => { if (y0 != null && y0 - e.clientY > 24) openSheet(); y0 = null; });
  const shTop = $('.sh-top', sheet);
  shTop.addEventListener('pointerdown', (e) => { y0 = e.clientY; });
  shTop.addEventListener('pointerup', (e) => { if (y0 != null && e.clientY - y0 > 40) closeSheet(); y0 = null; });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !sheet.hidden) { closeSheet(); return; }
    const tag = (e.target.tagName || '').toLowerCase();
    if (e.key === ' ' && !isLive() && !['button', 'a', 'summary', 'input', 'textarea', 'select'].includes(tag)) {
      e.preventDefault();
      if (t >= END) replay(); else { paused = !paused; force = true; }
    }
  });

  // ---- the account chip -------------------------------------------------------------------------------
  const user = (window.STRINGER_DEMO || {}).user || {};
  const me = $('.top .me');
  if (me) {
    me.setAttribute('aria-label', user.email ? `Signed in as ${user.email}` : 'Not signed in');
    $('.initials', me).innerHTML = user.initials ? esc(user.initials) : '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true" style="width:18px;height:18px"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/></svg>';
  }
  document.title = `Stringer · ${isLive() ? 'Being made' : isDone() ? 'How it was made' : 'No video'}: ${RUN.event}`;

  // ================================================================================================
  // START
  // ================================================================================================
  paint();
  place();
  mqDesk.addEventListener?.('change', place);
  mqPhone.addEventListener?.('change', place);
  if (ended) { if (follow) sel = 'summary'; }
  render();
  if (ended) onEnd(false);
  if (qs.has('sheet') && L === 'phone') openSheet();
  requestAnimationFrame(loop);
  poll();
  window.PROGRESS = { seek: (x) => { if (isLive()) return; t = x === 'end' ? END : x; force = true; render(); }, select: (k) => select(k, true), openSheet, closeSheet, setSpeed, pause: (v = true) => { paused = v; }, get t() { return t; }, get END() { return END; }, get KIND() { return KIND; } };
})();
