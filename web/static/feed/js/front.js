// Front page: the two-way feed, on the site's real records (module 9).
// window.STRINGER_DEMO comes from /api/site (boot.js): the finished videos, the event list with each event's
// state, the Gate's numbers and messages. "Make the video" is POST /make?event=, a report is POST /report.
// While a video is being made the page asks /api/site again every few seconds; otherwise once a minute.
(function () {
  'use strict';
  const { D, decode, when, shortDay, ICON, $, $$, esc, transition, toast, reduced, cap, tags } = window.SG;
  const GET = window.STRINGER_GET;
  const app = $('#app');
  const feed = $('#feed');
  const mqDesk = window.matchMedia('(min-width: 900px)');
  const mqLaneCol = window.matchMedia('(min-width: 1680px)');
  const still = new URLSearchParams(location.search).has('still');   // the screenshot script: no polling

  // ================================================================================================
  // DATA
  // ================================================================================================
  const state = {
    sound: false,
    site: { ...D.site },
    story: 0,
    reported: new Set(),
    events: (D.events || []).map((e) => ({ ...e, progress: e.progress ? { ...e.progress } : null })),
    mine: new Set(),            // events this page started
  };
  const evById = (id) => state.events.find((e) => e.id === id);
  const videoById = (id) => (D.videos || []).find((v) => v.id === id);

  // One story per video for now; D.chains (follow-ups of one story, oldest first) is empty until the
  // follow-up step is built, but the chain code below is the design's and works when it fills in.
  function partOf(c, i, n) {
    const making = c.kind === 'making' || c.state === 'making';
    return { ...c, part: i + 1, of: n, kind: making ? 'making' : 'video', start: 0 };
  }
  function storyOf(v) {
    const chain = D.chains && D.chains[v.chain];
    const parts = chain && chain.length ? chain.map((c, i) => partOf(c, i, chain.length)) : [partOf(v, 0, 1)];
    return { key: v.chain || v.id, lead: v, parts, at: Math.max(0, parts.findIndex((p) => p.id === v.id)), event: v.event };
  }
  const stories = (D.videos || []).filter((v) => !v.hidden).map(storyOf);
  const empty = () => stories.length === 0;

  const stepIndex = (key) => Math.max(0, D.steps.findIndex((s) => s.key === key));
  const stepAt = (pct) => {
    let acc = 0;
    for (let i = 0; i < D.steps.length; i++) { acc += D.steps[i].share * 100; if (pct < acc) return i; }
    return D.steps.length - 1;
  };
  const tagsHTML = (v, cls = 'tag') => tags(v).filter((t) => t.label).map((t) => {
    const sw = t.kind === 'side' ? `<span class="sw" style="background:${t.side === 'A' ? 'var(--sa, var(--side-a))' : 'var(--sb, var(--side-b))'}"></span>` : '';
    return `<span class="${cls}" title="${esc(t.label)}">${sw}<span class="tl">${esc(t.label)}</span></span>`;
  }).join('');
  const progressURL = (e) => `/progress?event=${encodeURIComponent(e.id || e)}`;
  const minutes = (s) => Math.max(1, Math.ceil((+s || 0) / 60));

  // ================================================================================================
  // FEED
  // ================================================================================================
  function frameHTML(p, si, pi) {
    if (p.kind === 'making') return makingCardHTML(p);
    return `<div class="frame" data-peek="${pi < stories[si].at ? 'Earlier' : pi > stories[si].at ? 'Later' : ''}">
      ${p.poster ? `<img class="poster" src="${esc(p.poster)}" alt="" loading="${si < 2 ? 'eager' : 'lazy'}" decoding="async" onerror="this.remove()">` : ''}
      <video muted playsinline loop preload="none" data-src="${esc(p.src || '')}${p.start ? '#t=' + p.start : ''}" aria-label="Video: ${esc(p.headline)}. Made with AI."></video>
      <button class="tapzone" aria-label="Play or pause"></button>
      <span class="playflash" aria-hidden="true">${ICON.play}</span><span class="scrim" aria-hidden="true"></span>
      <div class="hiddenwrap" role="status">${ICON.eyeOff}<p class="serif">Hidden while we check a report.</p><p class="small">Thanks for telling us. It comes back if it holds up.</p></div>
    </div>`;
  }

  function makingCardHTML(p) {
    const ev = evById(p.event);
    const pg = ev && ev.progress ? ev.progress : { pct: 0 };
    return `<div class="frame making paper" data-peek="Later · being made">
      <span class="scrim" aria-hidden="true"></span><div class="making-card">
        <p class="caps mk-kicker">Follow-up · being made</p>
        <h3 class="serif">${esc(p.headline)}</h3>
        ${stepsHTML(pg)}
        <div class="mkbar"><span class="track"><span class="fill" style="--p:${pg.pct}%"></span></span><span class="pct">${Math.round(pg.pct)}%</span></div>
        <p class="mk-note">${pg.by === 'you' ? 'You started this one.' : 'Another student started this one.'} It joins this story when it's done.</p>
        <a class="mk-watch" href="${progressURL(p.event)}">${ICON.trace}<span>Watch it being made</span></a>
      </div>
    </div>`;
  }

  // the eight steps, with the one running now; pg is an event's progress ({step, pct}) or a stop
  function stepsHTML(pg, stopAt = -1) {
    const pct = pg.pct || 0;
    const now = pg.step ? stepIndex(pg.step) : stepAt(pct);
    return `<ol class="steps">${D.steps.map((s, i) => {
      const cls = stopAt === i ? 'stop' : stopAt >= 0 && i > stopAt ? '' : pct >= 100 || i < now ? 'done' : i === now ? 'now' : '';
      return `<li class="${cls}"><span class="nd"></span><span>${esc(s.label)}</span></li>`;
    }).join('')}</ol>`;
  }

  function overHTML(p, s) {
    const nodiv = !(p.sides && p.sides.kind === 'two sides');
    const ev = s.event ? evById(s.event) : null;
    const dev = (ev ? ev.confidence : p.confidence) === 'Developing' && p.id === s.lead.id;
    if (p.kind === 'making') {
      return `<div class="part-over"><p class="po-kicker caps"><span class="pill pill-paper">Being made</span>${esc(cap(p.subtype))} · ${esc(p.country)}</p>
        <p class="po-note">This follow-up joins the story when it's done.</p>
        <a class="po-watch" href="${progressURL(p.event)}">${ICON.trace}<span>Watch it being made</span></a></div>`;
    }
    return `<div class="part-over">
      <p class="po-kicker caps">${dev ? '<span class="pill pill-dev">Developing</span>' : ''}${esc(cap(p.subtype))} · ${esc(p.country)}</p>
      <h2 class="po-head" data-decode>${esc(p.headline)}</h2>
      <p class="po-meta"><span>${esc(when(p.made))}</span><span>${nodiv ? 'No real divide' : '2 sides'} · ${p.articles} articles</span><span class="ai">Made with AI</span></p>
    </div>`;
  }

  function chainbarHTML(s) {
    const n = s.parts.length;
    if (n === 1) {
      return `<div class="chainbar single" role="group" aria-label="This story so far: one video">
        <span class="cb-label caps">Part 1 <span class="dim">of 1</span></span>
        <div class="cb-string"><span class="cb-node" aria-hidden="true" style="background:var(--vermilion);box-shadow:0 0 0 3px var(--night),0 0 0 4.5px rgba(232,98,44,.55)"></span>
          <span class="cb-solo">&nbsp;&nbsp;No follow-ups yet</span></div>
        <span class="cb-when caps">${esc(shortDay(s.parts[0].made))}</span></div>`;
    }
    const nodes = s.parts.map((p, i) => `<button class="cb-node${p.kind === 'making' ? ' mk' : ''}" data-go-part="${i}" aria-label="Part ${i + 1} of ${n}: ${esc(p.headline)}${p.kind === 'making' ? ', being made' : ', ' + esc(shortDay(p.made))}"></button>`).join('');
    return `<div class="chainbar" role="group" aria-label="This story over time">
      <span class="cb-label caps">Part <span class="cb-n">${s.at + 1}</span> <span class="dim">of ${n}</span></span>
      <div class="cb-string">${nodes}<span class="cb-ride"><i></i></span></div>
      <span class="cb-when caps">${esc(s.parts[s.at].kind === 'making' ? 'Being made' : shortDay(s.parts[s.at].made))}</span>
    </div>`;
  }

  function storyHTML(s, si) {
    return `<section class="story" data-si="${si}" aria-roledescription="story" aria-label="Story ${si + 1} of ${stories.length}: ${esc(s.lead.headline)}">
      <div class="chain" data-si="${si}" tabindex="-1" aria-label="Videos of this story, oldest on the left">
        ${s.parts.map((p, pi) => `<article class="part ${pi > s.at ? 'later' : pi < s.at ? 'earlier' : ''} ${p.kind === 'making' ? 'making' : ''}" data-pi="${pi}" aria-label="Part ${pi + 1} of ${s.parts.length}">
          ${frameHTML(p, si, pi)}${overHTML(p, s)}</article>`).join('')}
      </div>
      <div class="side-actions"><button data-sound aria-label="Sound on">${ICON.soundOff}</button><button data-report aria-label="Report this video">${ICON.flag}</button></div>
      <div class="under">
        <button class="ctl" data-play aria-label="Pause">${ICON.pause}</button>
        <button class="ctl" data-sound aria-label="Sound on">${ICON.soundOff}</button>
        ${chainbarHTML(s)}
        <button class="report-mini" data-report>${ICON.flag}<span>Report</span></button>
      </div>
      <button class="lip paper" data-receipts aria-label="Receipts: how each side tells it, and the sources">
        <span class="caps">${ICON.up}Receipts</span>
        <span class="cr">Events by <b>Monitor the Situation</b></span>
      </button>
      ${si === 0 && s.parts.length > 1 ? `<span class="hint" id="hint" style="left:16px;bottom:calc(var(--lipH) + 52px + var(--safe-b) + 120px)">${ICON.left}${s.at} earlier videos of this story</span>` : ''}
    </section>`;
  }

  // no finished videos yet: one card that sends you to the event list
  function emptyHTML() {
    return `<section class="story is-active feed-empty" data-si="0" aria-label="No videos yet">
      <div class="chain" data-si="0"><article class="part is-active" data-pi="0"><div class="frame making paper"><span class="scrim" aria-hidden="true"></span>
        <div class="making-card"><p class="caps mk-kicker">Hot right now</p>
          <h3 class="serif">No videos yet today.</h3>
          <p class="mk-note">Pick a story from the news right now and make the first one. It takes about ${esc(state.site.minutesPerVideo || '4–5')} minutes.</p>
          <button class="mk-watch" data-open-lane>${ICON.list}<span>See the news right now</span></button></div></div></article></div>
    </section>`;
  }

  function renderIndex() {
    let r = $('#storyrail');
    if (!r) { r = document.createElement('nav'); r.id = 'storyrail'; r.className = 'storyrail'; r.setAttribute('aria-label', 'Stories in Hot right now'); app.append(r); }
    r.innerHTML = `<span class="lbl" aria-hidden="true">Hot right now</span>` + stories.map((s, i) => `<button data-go-story="${i}" class="${s.mine ? 'mine' : ''}" aria-current="${i === state.story}" aria-label="Story ${i + 1}: ${esc(s.lead.headline)}"><i></i><span class="tip">${esc(s.lead.headline)}</span></button>`).join('');
  }
  let railShowT;
  function showIndex() {
    const r = $('#storyrail');
    if (!r || mqDesk.matches) return;
    r.classList.add('show');
    clearTimeout(railShowT);
    railShowT = setTimeout(() => r.classList.remove('show'), 1100);
  }

  function wireChain(c) {
    c.addEventListener('scroll', () => onChainScroll(+c.dataset.si), { passive: true });
    if ('onscrollend' in window) c.addEventListener('scrollend', () => settleChain(+c.dataset.si));
  }
  function renderFeed() {
    if (empty()) { feed.innerHTML = emptyHTML(); $('#hot-pos').textContent = '0 of 0'; return; }
    feed.innerHTML = stories.map(storyHTML).join('');
    $$('.chain', feed).forEach((c) => {
      const si = +c.dataset.si;
      requestAnimationFrame(() => scrollChainTo(si, stories[si].at, false));
      wireChain(c);
    });
    sizeRides();
  }

  // ---- the chain marker rides the sideways scroll (CSS scroll timeline; JS where unsupported) ------
  const sdScroll = CSS.supports && CSS.supports('animation-timeline: scroll()');
  function sizeRides() {
    $$('.story').forEach((st) => {
      const ride = $('.cb-ride', st);
      if (!ride) return;
      if (sdScroll) ride.classList.add('sd');
    });
  }
  const chainTimers = {};
  function onChainScroll(si) {
    if (empty()) return;
    const st = storyEl(si);
    const c = $('.chain', st);
    const max = c.scrollWidth - c.clientWidth;
    const p = max > 0 ? c.scrollLeft / max : 0;
    const ride = $('.cb-ride', st);
    if (ride && !sdScroll) $('i', ride).style.transform = `translateX(${(p - 1) * 100}%)`;
    const idx = Math.round(p * (stories[si].parts.length - 1));
    if (idx !== stories[si].cur) markPart(si, idx);
    clearTimeout(chainTimers[si]);
    chainTimers[si] = setTimeout(() => settleChain(si), 140);
    const h = $('#hint');
    if (h && si === 0 && Math.abs(c.scrollLeft - (stories[0].scrolled0 ?? c.scrollLeft)) > 30) h.classList.add('gone');
    if (stories[si].scrolled0 == null) stories[si].scrolled0 = c.scrollLeft;
  }
  function settleChain(si) { if (si === state.story) activate(); }

  function scrollChainTo(si, pi, smooth = true) {
    if (empty()) return;
    const st = storyEl(si);
    const c = $('.chain', st);
    const n = stories[si].parts.length;
    pi = Math.max(0, Math.min(n - 1, pi));
    const max = c.scrollWidth - c.clientWidth;
    const left = n > 1 ? (max * pi) / (n - 1) : 0;
    c.scrollTo({ left, behavior: smooth && !reduced() ? 'smooth' : 'auto' });
    if (!smooth) { stories[si].scrolled0 = left; onChainScroll(si); }
  }

  function markPart(si, pi) {
    const s = stories[si];
    s.cur = pi;
    const st = storyEl(si);
    $$('.part', st).forEach((el, i) => {
      el.classList.toggle('is-active', i === pi);
      el.classList.toggle('earlier', i < pi);
      el.classList.toggle('later', i > pi);
      const fr = $('.frame', el);
      if (fr) fr.dataset.peek = i < pi ? `Earlier · ${shortDay(s.parts[i].made)}` : i > pi ? (s.parts[i].kind === 'making' ? 'Later · being made' : `Later · ${shortDay(s.parts[i].made)}`) : '';
    });
    const n = $('.cb-n', st);
    if (n) n.textContent = pi + 1;
    const w = $('.cb-when', st);
    if (w) w.textContent = s.parts[pi].kind === 'making' ? 'Being made' : shortDay(s.parts[pi].made);
    st.classList.toggle('on-making', s.parts[pi].kind === 'making');
    if (si === state.story) renderRails();
  }

  // ================================================================================================
  // WHICH STORY IS IN VIEW
  // ================================================================================================
  const storyEl = (si) => feed.children[si];
  function currentStoryFromScroll() {
    const r = feed.getBoundingClientRect();
    const mid = r.top + r.height / 2;
    let best = 0, bd = Infinity;
    [...feed.children].forEach((el, i) => {
      const b = el.getBoundingClientRect();
      const d = Math.abs(b.top + b.height / 2 - mid);
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  }
  let feedTimer;
  feed.addEventListener('scroll', () => {
    if (empty()) return;
    const si = currentStoryFromScroll();
    if (si !== state.story) setStory(si);
    showIndex();
    clearTimeout(feedTimer);
    feedTimer = setTimeout(activate, 120);
  }, { passive: true });
  if ('onscrollend' in window) feed.addEventListener('scrollend', activate);

  function setStory(si) {
    if (empty()) { renderRails(); return; }
    const dir = si > state.story ? 1 : -1;
    state.story = si;
    $$('.story', feed).forEach((el, i) => el.classList.toggle('is-active', i === si));
    $('#hot-pos').textContent = `${si + 1} of ${stories.length}`;
    $$('#storyrail button').forEach((b, i) => b.setAttribute('aria-current', String(i === si)));
    stories[si].parts.some((p) => p.kind === 'making') && storyEl(si).classList.toggle('on-making', stories[si].parts[stories[si].cur ?? stories[si].at].kind === 'making');
    if (stories[si].cur == null) markPart(si, stories[si].at);
    renderRails(dir);
    loadNear(si);
  }

  function loadNear(si) {
    [si - 1, si, si + 1].forEach((k) => {
      const st = storyEl(k);
      if (!st) return;
      $$('video', st).forEach((v) => { if (!v.getAttribute('src') && v.dataset.src) { v.src = v.dataset.src; v.preload = k === si ? 'auto' : 'metadata'; } });
    });
  }

  // play the video in view, pause every other one
  let userPaused = false;
  function activeVideo() {
    if (empty()) return null;
    const st = storyEl(state.story);
    if (!st) return null;
    const part = $$('.part', st)[stories[state.story].cur ?? stories[state.story].at];
    return part ? $('video', part) : null;
  }
  function activate() {
    const v = activeVideo();
    $$('video', feed).forEach((x) => { if (x !== v && !x.paused) x.pause(); });
    $$('.frame', feed).forEach((f) => f.classList.remove('playing'));
    if (!v) return;
    if (!v.getAttribute('src') && v.dataset.src) v.src = v.dataset.src;
    v.muted = !state.sound;
    const fr = v.closest('.frame');
    if (v.closest('.part').classList.contains('is-hidden')) { v.pause(); return; }
    if (reduced() || userPaused || still) { fr.classList.add('paused'); syncPlayButtons(false); return; }
    const pr = v.play();
    fr.classList.remove('paused');
    if (pr && pr.then) pr.then(() => { fr.classList.add('playing'); syncPlayButtons(true); }).catch(() => { fr.classList.add('paused'); syncPlayButtons(false); });
    else fr.classList.add('playing');
  }
  function syncPlayButtons(playing) {
    const st = storyEl(state.story);
    if (!st) return;
    const b = $('[data-play]', st);
    if (b) { b.innerHTML = playing ? ICON.pause : ICON.play; b.setAttribute('aria-label', playing ? 'Pause' : 'Play'); }
  }
  function togglePlay() {
    const v = activeVideo();
    if (!v) return;
    const fr = v.closest('.frame');
    const flash = $('.playflash', fr);
    if (v.paused) { userPaused = false; v.play().catch(() => {}); fr.classList.remove('paused'); fr.classList.add('playing'); flash.innerHTML = ICON.play; syncPlayButtons(true); }
    else { userPaused = true; v.pause(); fr.classList.add('paused'); flash.innerHTML = ICON.pause; syncPlayButtons(false); }
    flash.classList.add('flash');
    setTimeout(() => flash.classList.remove('flash'), 500);
  }
  function toggleSound() {
    state.sound = !state.sound;
    $$('video', feed).forEach((v) => { v.muted = !state.sound; });
    $$('[data-sound]').forEach((b) => { b.innerHTML = state.sound ? ICON.soundOn : ICON.soundOff; b.setAttribute('aria-label', state.sound ? 'Sound off' : 'Sound on'); });
    const v = activeVideo();
    if (v && state.sound && v.paused && !userPaused) v.play().catch(() => {});
    toast(state.sound ? 'Sound on' : 'Sound off', { ms: 1400 });
  }

  // ================================================================================================
  // RAILS (desktop): the story and its chain on the left, the receipts on the right
  // ================================================================================================
  function curPart() { const s = stories[state.story]; return s ? s.parts[s.cur ?? s.at] : null; }

  function storyRailHTML() {
    const s = stories[state.story];
    const p = curPart();
    const ev = s.event ? evById(s.event) : null;
    const dev = (ev ? ev.confidence : p.confidence) === 'Developing';
    const next = stories[state.story + 1];
    const n = s.parts.length;
    const making = p.kind === 'making';
    const tl = n > 1 ? `<ol class="tl">${s.parts.map((q, i) => `<li class="${i === (s.cur ?? s.at) ? 'cur' : ''} ${q.kind === 'making' ? 'mk' : ''}">
        <button data-go-part="${i}" aria-current="${i === (s.cur ?? s.at)}"><span class="nd"></span>
        <span class="when">${q.kind === 'making' ? 'Being made now' : esc(shortDay(q.made))}${i === n - 1 && q.kind !== 'making' ? ' · latest' : ''}</span>
        <span class="h">${esc(q.headline)}</span></button></li>`).join('')}</ol>`
      : `<p class="tl-empty">This is the story's first video. Follow-ups will line up here, oldest first.</p>`;
    return `<div class="swap">
        <p class="rs-kicker caps"><span class="rank">No. ${state.story + 1}</span><span>${esc(cap(p.category))} · ${esc(cap(p.subtype))}</span>${dev && !making ? '<span class="pill pill-dev">Developing</span>' : ''}${making ? '<span class="pill pill-paper">Being made</span>' : ''}</p>
        <h1 class="rs-headline serif" data-decode>${esc(p.headline)}</h1>
        <p class="rs-dek">${esc(p.dek || '')}</p>
        ${making ? '' : `<p class="rs-meta"><span>${esc(when(p.made))}</span><span>${esc(p.duration || '')}</span><span>${esc(p.place || p.country)}</span><span class="ai">Made with AI</span></p>`}
        ${making ? '' : `<div class="rs-tags">${tagsHTML(p)}</div>`}
      </div>
      <div class="timeline swap"><p class="caps"><span>This story over time</span><span>${n} video${n === 1 ? '' : 's'}</span></p>${tl}</div>
      <div class="rs-foot">
        ${next ? `<button class="rs-next" data-go-story="${state.story + 1}">${ICON.arrowDown}<span class="caps">Next story</span><span class="h">${esc(next.lead.headline)}</span></button>` : `<p class="rs-next"><span class="caps">That's every video for now.</span></p>`}
        <p class="kbd-legend"><span><kbd>↑</kbd><kbd>↓</kbd> next story</span><span><kbd>←</kbd><kbd>→</kbd> same story over time</span></p>
      </div>`;
  }

  function receiptsHTML(p, { head = false } = {}) {
    if (p.kind === 'making') {
      const ev = evById(p.event);
      return `<div class="rc">${head ? rcHead(p) : ''}
        <section class="rc-sec"><p class="caps">A follow-up, being made</p>
          <p class="claims-line">Stringer spotted this event as the same story moving on, so its video joins the chain when it's done.</p></section>
        <section class="rc-sec"><p class="caps">The event</p>
          <p class="slip-text" style="margin:0;color:var(--t)">${esc(ev ? ev.title : p.headline)}</p>
          <p class="claims-line" style="margin-top:8px">${ev ? `${ev.reports} reports · latest ${esc(ev.lastReport)} · ${esc(ev.confidence)}` : ''}</p>
          <p class="rc-credit" style="margin-top:6px">Events by Monitor the Situation</p></section>
        <section class="rc-sec"><p class="caps">Receipts</p>
          <p class="claims-line">They show up here when the video is done: how each side tells it, every article read and every claim checked.</p></section></div>`;
    }
    const how = `<a class="report-link" href="${progressURL(p.event || p.id)}">${ICON.trace}How it was made</a>`;
    if (!p.receipts) {
      return `<div class="rc">${head ? rcHead(p) : ''}
        <section class="rc-sec"><p class="caps">Receipts</p>
          <p class="claims-line">The receipts for this video aren't saved, so there's nothing to show here yet.</p></section>
        <section class="rc-sec"><div class="rc-foot"><span class="pill pill-ai">Made with AI</span>
          <button class="report-link" data-report>${ICON.flag}Report this video</button></div>
          <p class="rc-credit" style="margin-top:12px">Events by Monitor the Situation</p></section></div>`;
    }
    const two = p.sides && p.sides.kind === 'two sides';
    const A = two ? p.sides.A : null, B = two ? p.sides.B : null;
    const elsewhere = two ? (p.elsewhere != null ? p.elsewhere : Math.max(0, p.articles - A.articles - B.articles)) : 0;
    const dots = (k) => `<span class="slip-dots" aria-hidden="true">${'<i></i>'.repeat(Math.min(8, k))}</span>`;
    const names = (x) => (x.outlets || []).join(', ');
    const sides = two ? `
      <div class="slip a"><div class="slip-head"><span class="caps slip-label">${esc(A.label)}</span>${dots(A.articles)}</div>
        <p class="slip-meta">${A.articles} article${A.articles === 1 ? '' : 's'}${names(A) ? ' · ' + esc(names(A)) : ''}</p><p class="slip-text" data-decode>${esc(p.sides.howA || '')}</p></div>
      <div class="slip b"><div class="slip-head"><span class="caps slip-label">${esc(B.label)}</span>${dots(B.articles)}</div>
        <p class="slip-meta">${B.articles} article${B.articles === 1 ? '' : 's'}${names(B) ? ' · ' + esc(names(B)) : ''}</p><p class="slip-text" data-decode>${esc(p.sides.howB || '')}</p></div>`
      : `<div class="slip n"><div class="slip-head"><span class="caps slip-label">No real divide</span>${dots(p.outlets)}</div>
        <p class="slip-meta">${p.articles} articles from ${p.outlets} outlets, read as one group</p><p class="slip-text" data-decode>${esc((p.sides && p.sides.reason) || '')}</p></div>`;
    const segs = two ? [[A.articles, 'var(--sa)'], [B.articles, 'var(--sb)'], [elsewhere, 'var(--so)']] : [[p.articles, 'var(--so)']];
    const legend = two ? `<ul class="legend">
        <li style="--c:var(--sa)"><span class="sw"></span><b>${A.articles}</b><span>${esc(A.label)}</span></li>
        <li style="--c:var(--sb)"><span class="sw"></span><b>${B.articles}</b><span>${esc(B.label)}</span></li>
        ${elsewhere ? `<li style="--c:var(--so)"><span class="sw"></span><b>${elsewhere}</b><span>Elsewhere <span class="s">wire services and others</span></span></li>` : ''}</ul>`
      : `<ul class="legend"><li style="--c:var(--so)"><span class="sw"></span><b>${p.articles}</b><span>From ${p.outlets} outlets <span class="s">read as one group</span></span></li></ul>`;
    const unbacked = Math.max(0, p.claims - p.claimsBacked);
    return `<div class="rc">${head ? rcHead(p) : ''}
      <section class="rc-sec"><p class="caps"><span>How each side tells it</span><span class="q">${two ? '2 sides' : 'one story, told alike'}</span></p>${sides}</section>
      <section class="rc-sec"><p class="caps">Where this came from</p>
        <div class="big"><span class="n">${p.articles}</span><span class="l">news articles read</span></div>
        <div class="dotbar balance" aria-hidden="true">${segs.filter((x) => x[0] > 0).map(([n, c]) => `<span style="--n:${n};--c:${c}"></span>`).join('')}</div>
        ${legend}</section>
      <section class="rc-sec"><p class="caps"><span>Claims checked</span><span class="q">${p.claimsBacked} of ${p.claims}</span></p>
        <p class="claims-line"><b>${p.claimsBacked} of ${p.claims} claims</b> were backed by a source. ${unbacked ? `The other ${unbacked} ${unbacked === 1 ? 'was' : 'were'} left out of the script.` : 'Nothing had to be left out.'}</p>
        <div class="claims" aria-hidden="true">${'<i></i>'.repeat(p.claimsBacked)}${'<i class="x"></i>'.repeat(unbacked)}</div></section>
      <section class="rc-sec rc-tags-sec"><p class="caps">Tags</p><div class="rc-tags">${tagsHTML(p)}</div></section>
      <section class="rc-sec"><div class="rc-foot"><span class="pill pill-ai">${esc(p.aiMark || `Made with AI from ${p.articles} news articles`)}</span>
        ${how}<button class="report-link" data-report>${ICON.flag}Report this video</button></div>
        <p class="rc-credit" style="margin-top:12px">Events by Monitor the Situation</p></section>
    </div>`;
  }
  const rcHead = (p) => `<div class="rc-head"><p class="caps">Receipts · part ${p.part} of ${p.of}</p><p class="h">${esc(p.headline)}</p></div>`;

  let railKey = '';
  function renderRails(dir = 1) {
    if (!mqDesk.matches) return;
    const L = $('#rail-story'), R = $('#rail-receipts');
    if (empty()) {
      if (railKey === 'empty') return;
      railKey = 'empty';
      L.innerHTML = `<div class="swap"><p class="rs-kicker caps"><span class="rank">Hot right now</span></p>
        <h1 class="rs-headline serif">Nothing here yet.</h1>
        <p class="rs-dek">Every video on Stringer starts with a student picking a story. Pick one from the news right now and make the first.</p></div>`;
      R.innerHTML = `<div class="rc"><section class="rc-sec"><p class="caps">Receipts</p>
        <p class="claims-line">Each video's receipts show up here: how each side tells it, every article read and every claim checked.</p>
        <p class="rc-credit" style="margin-top:12px">Events by Monitor the Situation</p></section></div>`;
      return;
    }
    const s = stories[state.story];
    const key = `${s.key}:${s.cur ?? s.at}:${curPart().kind}`;
    if (key === railKey) return;
    const first = !railKey || railKey === 'empty';
    railKey = key;
    const fill = () => {
      L.innerHTML = storyRailHTML();
      R.innerHTML = receiptsHTML(curPart(), { head: true });
      $$('[data-decode]', L).forEach((el) => decode(el, { perChar: 18 }));
      $$('.slip-text[data-decode]', R).forEach((el, i) => decode(el, { delay: 220 + i * 260, perChar: 12, max: 1100 }));
      $$('.swap', L).forEach((el) => { el.classList.add('pre'); el.style.setProperty('--in-y', `${dir * 18}px`); });
      R.firstElementChild && R.firstElementChild.classList.add('swap', 'pre');
      requestAnimationFrame(() => requestAnimationFrame(() => $$('.rail .swap.pre').forEach((el, i) => { el.style.transitionDelay = `${i * 50}ms`; el.classList.remove('pre'); })));
    };
    if (first) { fill(); return; }
    $$('.rail .swap').forEach((el) => { el.style.setProperty('--out-y', `${-dir * 14}px`); el.style.transitionDelay = '0ms'; el.classList.add('out'); });
    clearTimeout(renderRails.t);
    renderRails.t = setTimeout(fill, 150);
  }

  // ================================================================================================
  // EVENTS (lane on desktop, tab on phone)
  // ================================================================================================
  // The Gate's limits, said with the site's real numbers (the same words as the design)
  function limitText(lim, extra = {}) {
    const s = state.site;
    const wait = extra.retry_after_s != null ? extra.retry_after_s : s.retryAfterS;
    const m = minutes(wait);
    return {
      day_full: { t: `Today's ${s.videosPerDay} videos are made`, b: 'New ones start at midnight, New York time. You can still watch everything already made.' },
      visitor_pace: { t: `You've started ${s.perPersonPerHour} video${s.perPersonPerHour === 1 ? '' : 's'} this hour`, b: wait ? `You can start another in ${m} minute${m === 1 ? '' : 's'}.` : 'You can start another soon.' },
      busy: { t: `${s.atOnce} videos are being made right now`, b: "That's the most at once. Try again in a few minutes." },
      closed: { t: 'New videos are paused right now', b: 'You can still watch everything already made.' },
      searches_low: { t: 'New videos are paused for now', b: "This month's news searches are almost used up. You can still watch everything already made." },
    }[lim];
  }
  const LIMIT_CODES = ['closed', 'searches_low', 'day_full', 'busy', 'visitor_pace'];
  const makingCount = () => Math.max(state.site.beingMade || 0, state.events.filter((e) => e.state === 'making').length);
  function liveLimit() {
    const s = state.site;
    if (!s.open) return 'closed';
    if (s.searchesLow) return 'searches_low';
    if (s.videosToday >= s.videosPerDay) return 'day_full';
    if (makingCount() >= s.atOnce) return 'busy';
    if (s.youThisHour >= s.perPersonPerHour) return 'visitor_pace';
    return 'none';
  }
  function siteNumbers() {
    return { today: Math.min(state.site.videosToday, state.site.videosPerDay), you: Math.min(state.site.youThisHour, state.site.perPersonPerHour), mk: Math.min(makingCount(), state.site.atOnce) };
  }
  const dotsHTML = (n, of, mkFrom = Infinity) => Array.from({ length: of }, (_, i) => `<i class="${i < n ? (i >= mkFrom ? 'mk' : 'on') : ''}"></i>`).join('');

  function renderLimits() {
    const { today, you, mk } = siteNumbers();
    $('#limits').innerHTML = `
      <div class="lim"><span>Videos today, whole site</span><span class="dots">${dotsHTML(today, state.site.videosPerDay)}</span><b>${today} of ${state.site.videosPerDay}</b></div>
      <div class="lim"><span>Being made right now</span><span class="dots">${dotsHTML(mk, state.site.atOnce, 0)}</span><b>${mk} of ${state.site.atOnce}</b></div>
      <div class="lim"><span>Started by you this hour</span><span class="dots">${dotsHTML(you, state.site.perPersonPerHour)}</span><b>${you} of ${state.site.perPersonPerHour}</b></div>`;
    const lim = liveLimit();
    const note = $('#limit-note');
    note.classList.toggle('show', lim !== 'none');
    note.innerHTML = lim !== 'none' ? `<b>${esc(limitText(lim).t)}</b>${esc(limitText(lim).b)}` : '';
    $('#meter-dots').innerHTML = dotsHTML(today, state.site.videosPerDay);
    $('#meter-val').textContent = `${today} of ${state.site.videosPerDay}`;
  }

  function evThumb(e) {
    if (e.state === 'has_video') { const v = videoById(e.video) || {}; return v.poster ? `<img src="${esc(v.poster)}" alt="" loading="lazy" onerror="this.remove()">` : ''; }
    if (e.state === 'making') { const p = e.progress ? e.progress.pct : 0; const c = 2 * Math.PI * 14; return `<svg class="ring" viewBox="0 0 34 34" aria-hidden="true"><circle cx="17" cy="17" r="14" fill="none" stroke="rgba(243,238,225,.18)" stroke-width="2.4"/><circle cx="17" cy="17" r="14" fill="none" stroke="var(--mustard)" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p / 100)}" transform="rotate(-90 17 17)"/></svg>`; }
    if (e.state === 'ready') return '<span class="plus" aria-hidden="true">+</span>';
    if (e.state === 'no_video') return ICON.cross;
    if (e.state === 'hidden') return ICON.eyeOff;
    return '';
  }
  function evStatus(e) {
    if (e.state === 'has_video') return `<span class="st">Has a video</span><span class="ev-go go">Watch</span>`;
    if (e.state === 'making') {
      const p = e.progress || { pct: 0 };
      const step = D.steps[p.step ? stepIndex(p.step) : stepAt(p.pct)].label;
      return `<span class="st">Being made</span><span>${p.by === 'you' ? 'by you' : 'by another student'}</span>
        <span class="ev-prog" style="width:100%"><span class="track"><span class="fill" style="--p:${p.pct}%"></span></span><span class="lbl"><span>${esc(step)}</span><span>${Math.round(p.pct)}%</span></span></span>`;
    }
    if (e.state === 'ready') return `<span class="st">No video yet</span><span class="ev-go go">Make the video</span>`;
    if (e.state === 'no_video') return `No video. ${esc(e.reason)}`;
    if (e.state === 'hidden') return esc(e.hiddenNote || 'Hidden while we check a report.');
    return '';
  }
  function evLabel(e) {
    const s = { has_video: 'has a video', making: 'being made', ready: 'no video yet, you can make one', no_video: 'no video: ' + (e.reason || ''), hidden: 'hidden while we check a report' }[e.state];
    return `${e.title}. ${s}`;
  }
  function renderEvents() {
    $('#events').innerHTML = state.events.length ? state.events.map((e) => `<li class="ev" data-state="${e.state}" data-ev="${esc(e.id)}">
      <button class="ev-main" data-open-ev="${esc(e.id)}" aria-label="${esc(evLabel(e))}" style="view-transition-name: ev-${esc(String(e.id).replace(/[^A-Za-z0-9_-]/g, ''))}">
        <span class="ev-thumb">${evThumb(e)}</span>
        <span class="ev-body">
          <span class="ev-kicker caps">${e.confidence === 'Developing' ? '<span class="pill pill-dev">Developing</span>' : ''}<span>${esc(cap(e.category))} · ${esc(e.country)}</span></span>
          <span class="ev-title">${esc(e.title)}</span>
          <span class="ev-meta">${e.reports} reports · latest ${esc(e.lastReport)}</span>
          <span class="ev-status">${evStatus(e)}</span>
        </span>
      </button></li>`).join('')
      : `<li class="ev"><p class="ev-meta" style="padding:14px 4px">${D.listError ? "Monitor the Situation's list can't be reached right now. Try again in a few minutes." : 'No stories right now. The list updates every few minutes.'}</p></li>`;
    $('#lane-dots').innerHTML = state.events.map((e) => `<i class="${e.state}"></i>`).join('');
    const ready = state.events.filter((e) => e.state === 'ready').length;
    $('#lane-ready').innerHTML = `<span class="n">${state.events.length}</span><br>events<br>${ready} ready`;
    $('#tab-count').textContent = ready;
    const credit = $('.lane-credit');
    if (credit) credit.innerHTML = `Events by <b>Monitor the Situation</b>. The ${state.events.length} biggest stories that can become a video.`;
    renderLimits();
  }

  // ---- the lane drawer and the phone tab ----------------------------------------------------------
  function openLane(open) {
    if (!mqDesk.matches) return setTab(open ? 'events' : 'videos');
    if (mqLaneCol.matches) { if (open) $('#events').focus?.(); return; }
    app.dataset.lane = open ? 'open' : 'closed';
    $('#lane-strip').setAttribute('aria-expanded', String(open));
    if (open) setTimeout(() => $('.ev-main', $('#events'))?.focus({ preventScroll: true }), 300);
    else $('#lane-strip').focus({ preventScroll: true });
  }
  function setTab(tab) {
    transition(() => {
      app.dataset.tab = tab;
      $('#tab-videos').setAttribute('aria-selected', String(tab === 'videos'));
      $('#tab-events').setAttribute('aria-selected', String(tab === 'events'));
    });
    if (tab === 'videos') activate(); else { const v = activeVideo(); if (v) v.pause(); }
  }

  // ================================================================================================
  // DIALOGS: confirm, making, no video, hidden, report, receipts
  // ================================================================================================
  function openDialog(d) {
    if (!d.open) { if (d.showModal) d.showModal(); else d.setAttribute('open', ''); }
  }
  function closeDialog(d) { if (d.open) d.close(); }
  $$('dialog').forEach((d) => {
    d.addEventListener('click', (e) => { if (e.target === d || e.target.closest('[data-close]')) closeDialog(d); });
  });
  // drag a sheet down by its top to close it (phone)
  $$('dialog.sheet .sheet-card').forEach((card) => {
    let y0 = null;
    card.addEventListener('pointerdown', (e) => { if (e.clientY - card.getBoundingClientRect().top < 44 && !mqDesk.matches) { y0 = e.clientY; card.setPointerCapture(e.pointerId); } });
    card.addEventListener('pointermove', (e) => { if (y0 == null) return; const dy = Math.max(0, e.clientY - y0); card.style.transform = `translateY(${dy}px)`; });
    const end = (e) => { if (y0 == null) return; const dy = e.clientY - y0; y0 = null; card.style.transform = ''; if (dy > 90) closeDialog(card.closest('dialog')); };
    card.addEventListener('pointerup', end);
    card.addEventListener('pointercancel', end);
  });

  function fillEventDialog(e, note) {
    const d = $('#dlg-confirm');
    const body = $('#cf-body');
    if (note) body.innerHTML = stopHTML(e, note);
    else if (e.state === 'ready') body.innerHTML = confirmHTML(e);
    else if (e.state === 'making') body.innerHTML = makingHTML(e);
    else if (e.state === 'no_video') body.innerHTML = noVideoHTML(e);
    else if (e.state === 'hidden') body.innerHTML = hiddenHTML(e);
    d.dataset.ev = e.id;
  }
  function openEvent(id) {
    const e = evById(id);
    if (!e) return;
    if (e.state === 'has_video') return watch(e);
    const d = $('#dlg-confirm');
    fillEventDialog(e);
    openDialog(d);
    const go = $('[data-confirm]', $('#cf-body'));
    (go && !go.disabled ? go : $('.sh-actions [data-close]', d) || $('[data-close]', d)).focus({ focusVisible: false });
  }

  const confirmHead = (e, kicker = 'Make a video of this story?') => `<p class="caps sh-kicker">${esc(kicker)}</p>
      <h2 class="sh-title" id="cf-title">${esc(e.title)}</h2>
      <p class="sh-meta">${esc(cap(e.category))} · ${esc(cap(e.subtype))} · ${esc(e.country)} · ${e.reports} reports, latest ${esc(e.lastReport)}</p>`;
  // a stop: one of the Gate's limits, or its answer that this story can't become a video
  function stopHTML(e, note) {
    return `${confirmHead(e)}
        <div class="stop-note">${note.icon || ICON.clock}<div><b>${esc(note.t)}${/[.!?]$/.test(note.t) ? '' : '.'}</b><span>${esc(note.b || '')}</span></div></div>
        <div class="sh-actions"><button class="btn btn-ink" data-close>OK</button></div>`;
  }
  function confirmHTML(e) {
    const lim = liveLimit();
    const { today, you } = siteNumbers();
    if (lim !== 'none') return stopHTML(e, limitText(lim));
    return `${confirmHead(e)}
      <ul class="terms sh-body">
        <li><span class="tic">${ICON.clock}</span><div><b>Takes about ${esc(state.site.minutesPerVideo || '4–5')} minutes.</b>Keep watching other videos, and we'll tell you when it's ready.</div></li>
        <li><span class="tic"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="7" cy="12" r="2.2" fill="currentColor"/><circle cx="12" cy="12" r="2.2" fill="currentColor"/><circle cx="17" cy="12" r="2.2" fill="none" stroke="currentColor" stroke-width="1.4"/></svg></span><div><b>Uses 1 of today's ${state.site.videosPerDay} videos.</b>${today} made so far today, across the whole site.<span class="dots" aria-hidden="true">${dotsHTML(today, state.site.videosPerDay).replace(`<i class=""></i>`, '<i class="me"></i>')}</span></div></li>
        <li><span class="tic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/></svg></span><div><b>You've started ${you} of your ${state.site.perPersonPerHour} this hour.</b>This would be number ${you + 1}.</div></li>
      </ul>
      <p class="sh-fine">Stringer reads how each side's outlets cover this, checks the claims, then writes and draws the video. If the claims don't hold up, it stops and tells you why.</p>
      <div class="sh-actions"><button class="btn btn-line" data-close>Not now</button><button class="btn btn-ink" data-confirm="${esc(e.id)}">Make the video</button></div>`;
  }

  function makingHTML(e) {
    const p = e.progress || { pct: 0 };
    const mine = p.by === 'you';
    return `<p class="caps sh-kicker">Being made</p>
      <h2 class="sh-title" id="cf-title">${esc(e.title)}</h2>
      <div class="mk-head"><span class="caps">${mine ? 'You started this one' : 'Another student started this one'}</span>${p.startedAgo ? `<span class="caps">${esc(p.startedAgo)} ago</span>` : ''}</div>
      <div class="mk-live">${stepsHTML(p)}</div>
      <div class="mkbar" style="margin-top:14px"><span class="track"><span class="fill" style="--p:${p.pct}%"></span></span><span class="pct">${Math.round(p.pct)}%</span></div>
      <p class="sh-fine">${mine ? "You can close this and keep watching. The new video goes to the top of Hot right now when it's done." : `When it's done, it joins Hot right now. That's usually ${esc(state.site.minutesPerVideo || '4–5')} minutes after it starts.`}</p>
      <div class="sh-actions"><a class="btn btn-line" href="${progressURL(e)}">${ICON.trace}Watch it being made</a><button class="btn btn-ink" data-close>Keep watching</button></div>`;
  }
  function noVideoHTML(e) {
    return `<p class="caps sh-kicker">No video for this story</p>
      <h2 class="sh-title" id="cf-title">${esc(e.title)}</h2>
      <div class="stop-note">${ICON.cross}<div><b>${esc(e.reason || 'Stringer stopped before the video.')}</b><span>Stringer stops when it can't back up what the video would say, so nothing went up.</span></div></div>
      <div class="sh-actions"><a class="btn btn-line" href="${progressURL(e)}">${ICON.trace}See what happened</a><button class="btn btn-ink" data-close>OK</button></div>`;
  }
  function hiddenHTML(e) {
    return `<p class="caps sh-kicker">Hidden</p>
      <h2 class="sh-title" id="cf-title">${esc(e.title)}</h2>
      <div class="stop-note">${ICON.eyeOff}<div><b>Hidden while we check a report.</b><span>Someone reported this video, so it's hidden until we check it. Then it goes back up or comes down for good.</span></div></div>
      <div class="sh-actions"><button class="btn btn-ink" data-close>OK</button></div>`;
  }

  // ---- after Confirm: the Gate says yes or no, then the page follows the run ------------------------
  async function postJSON(url, body) {
    const r = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body || {}) });
    let out = {};
    try { out = await r.json(); } catch (err) { /* an empty answer */ }
    if (!r.ok && out.ok == null) out = { ok: false, message: out.error || "Stringer couldn't do that right now. Try again in a minute." };
    return out;
  }
  let confirming = false;
  async function confirm(id) {
    const e = evById(id);
    if (!e || e.state !== 'ready' || confirming) return;
    if (liveLimit() !== 'none') { fillEventDialog(e); return; }
    const btn = $(`[data-confirm="${CSS.escape(id)}"]`);
    if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
    confirming = true;
    let out;
    try { out = await postJSON(`/make?event=${encodeURIComponent(id)}`); }
    catch (err) { out = { ok: false, code: 'offline', message: "Couldn't reach Stringer. Check your connection and try again." }; }
    confirming = false;
    const d = $('#dlg-confirm');
    const here = d.open && d.dataset.ev === id;
    if (out.ok) {
      state.mine.add(id);
      e.state = 'making';
      e.progress = { pct: 0, step: 'sides', by: 'you', startedAgo: '' };
      state.site.videosToday += 1;
      state.site.youThisHour += 1;
      state.site.beingMade = (state.site.beingMade || 0) + 1;
      transition(() => { if (here) $('#cf-body').innerHTML = makingHTML(e); renderEvents(); });
      poll(1500);
      return;
    }
    if (out.code === 'has_video') { closeDialog(d); await refresh(); const e2 = evById(id); if (e2 && e2.state === 'has_video') watch(e2); return; }
    if (out.code === 'making') { e.state = 'making'; e.progress = e.progress || { pct: 0, by: 'another student' }; if (here) $('#cf-body').innerHTML = makingHTML(e); renderEvents(); poll(1500); return; }
    let note;
    if (LIMIT_CODES.includes(out.code)) {
      if (out.code === 'closed') state.site.open = false;
      if (out.code === 'searches_low') state.site.searchesLow = true;
      if (out.code === 'day_full') state.site.videosToday = state.site.videosPerDay;
      if (out.code === 'visitor_pace') { state.site.youThisHour = state.site.perPersonPerHour; if (out.retry_after_s != null) state.site.retryAfterS = out.retry_after_s; }
      if (out.code === 'busy') state.site.beingMade = state.site.atOnce;
      note = limitText(out.code, out);
      renderLimits();
    } else {
      note = { t: out.message || D.gateMessages.unavailable, b: out.code === 'offline' ? '' : "Nothing was spent. You can pick another story.", icon: ICON.cross };
    }
    if (here) transition(() => { $('#cf-body').innerHTML = stopHTML(e, note); });
    else toast(esc(note.t));
    refresh();
  }

  // the being-made views follow the event's progress; called after every refresh
  function tickUI(e) {
    const d = $('#dlg-confirm');
    if (d.open && d.dataset.ev === e.id && e.progress) {
      const live = $('.mk-live', d);
      if (live) {
        live.innerHTML = stepsHTML(e.progress);
        $('.mkbar .fill', d).style.setProperty('--p', e.progress.pct + '%');
        $('.mkbar .pct', d).textContent = Math.round(e.progress.pct) + '%';
      }
    }
    // a follow-up being made inside a chain
    $$(`.part.making`).forEach((part) => {
      const st = part.closest('.story');
      const s = stories[+st.dataset.si];
      if (!s) return;
      const p = s.parts[+part.dataset.pi];
      if (!p || p.event !== e.id || !e.progress) return;
      const card = $('.making-card', part);
      $('.steps', card).outerHTML = stepsHTML(e.progress);
      $('.mkbar .fill', card).style.setProperty('--p', e.progress.pct + '%');
      $('.mkbar .pct', card).textContent = Math.round(e.progress.pct) + '%';
    });
  }

  // a new finished video goes to the top of Hot right now, without moving what you're watching
  function addStory(v, mine) {
    const s = storyOf(v);
    s.mine = mine;
    if (empty()) {
      stories.push(s);
      railKey = '';
      renderFeed();
      renderIndex();
      requestAnimationFrame(() => { setStory(0); activate(); });
      return;
    }
    stories.unshift(s);
    const wrap = document.createElement('div');
    wrap.innerHTML = storyHTML(s, 0);
    const el = wrap.firstElementChild;
    feed.prepend(el);
    [...feed.children].forEach((x, i) => { x.dataset.si = i; $('.chain', x).dataset.si = i; x.setAttribute('aria-label', `Story ${i + 1} of ${stories.length}: ${stories[i].lead.headline}`); });
    wireChain($('.chain', el));
    sizeRides();
    renderIndex();
    state.story += 1;
    feed.scrollTop += el.getBoundingClientRect().height;
    $('#hot-pos').textContent = `${state.story + 1} of ${stories.length}`;
    $$('#storyrail button').forEach((b, i) => b.setAttribute('aria-current', String(i === state.story)));
  }
  function hideStory(id) {
    stories.forEach((s, si) => s.parts.forEach((p, pi) => {
      if (p.id !== id) return;
      const part = $$('.part', storyEl(si))[pi];
      if (part && !part.classList.contains('is-hidden')) { part.classList.add('is-hidden'); const v = $('video', part); if (v) v.pause(); }
    }));
  }

  function watch(e) {
    const si = stories.findIndex((s) => s.parts.some((p) => p.id === e.video));
    if (si < 0) return;
    const pi = stories[si].parts.findIndex((p) => p.id === e.video);
    closeDialog($('#dlg-confirm'));
    if (!mqDesk.matches) setTab('videos');
    openLane(false);
    goStory(si).then(() => { if (pi !== (stories[si].cur ?? stories[si].at)) scrollChainTo(si, pi); });
  }

  // ---- report ----------------------------------------------------------------------------------
  function reportsMaxHTML() {
    return `<p class="caps sh-kicker">Report this video</p><h2 class="sh-title" id="rp-title">You've sent ${state.site.reportsPerDay} reports today.</h2>
        <p class="sh-fine" style="font-size:15px">That's the most for one day. Thanks for helping. You can send more tomorrow.</p>
        <div class="sh-actions"><button class="btn btn-ink" data-close>OK</button></div>`;
  }
  function openReport() {
    const p = curPart();
    if (!p) return;
    if (p.kind === 'making') { toast("This one isn't finished yet. You can report it once it's up."); return; }
    const d = $('#dlg-report');
    const body = $('#rp-body');
    if (state.reported.has(p.id)) {
      body.innerHTML = `<p class="caps sh-kicker">Report this video</p><h2 class="sh-title" id="rp-title">You've reported this one.</h2>
        <p class="sh-fine" style="font-size:15px">Thanks. We'll take a look.</p><div class="sh-actions"><button class="btn btn-ink" data-close>OK</button></div>`;
      openDialog(d);
      return;
    }
    if (state.site.reportsToday >= state.site.reportsPerDay) { body.innerHTML = reportsMaxHTML(); openDialog(d); return; }
    body.innerHTML = `<p class="caps sh-kicker">Report this video</p>
      <h2 class="sh-title" id="rp-title">What's wrong with it?</h2>
      <p class="sh-meta">${esc(p.headline)}</p>
      <form id="rp-form" novalidate>
        <div class="reasons sh-body" role="radiogroup" aria-labelledby="rp-title">
          ${D.reportReasons.map((r) => `<label class="reason"><input type="radio" name="reason" value="${esc(r.key)}">${esc(r.label)}</label>`).join('')}
        </div>
        <div class="field"><label for="rp-note">Anything we should know? <span>(optional)</span></label>
          <textarea id="rp-note" maxlength="1000" placeholder="What's wrong, and where in the video"></textarea>
          <div class="help"><span>Up to 1,000 characters</span><span id="rp-count">0 of 1,000</span></div></div>
        <p class="sh-fine">Sending a report hides this video for everyone until we've checked it.</p>
        <p class="form-err" id="rp-err" role="alert"></p>
        <div class="sh-actions"><button type="button" class="btn btn-line" data-close>Cancel</button><button type="submit" class="btn btn-ink">Send report</button></div>
      </form>`;
    openDialog(d);
    const ta = $('#rp-note');
    ta.addEventListener('input', () => {
      const n = ta.value.length;
      const c = $('#rp-count');
      c.textContent = `${n.toLocaleString('en-US')} of 1,000`;
      c.classList.toggle('warn', n > 900);
    });
    $('#rp-form').addEventListener('change', () => { $('#rp-err').textContent = ''; });
    $('#rp-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const r = $('input[name=reason]:checked', d);
      if (!r) { $('#rp-err').textContent = 'Pick a reason first.'; $('input[name=reason]', d).focus(); return; }
      sendReport(p, r.value, ta.value);
    });
    $('input[name=reason]', d).focus({ focusVisible: false });
  }
  async function sendReport(p, reason, note) {
    const send = $('#rp-form button[type=submit]');
    if (send) { send.disabled = true; send.textContent = 'Sending…'; }
    let out;
    try { out = await postJSON('/report', { event: p.event || p.id, reason, note }); }
    catch (err) { out = { ok: false, message: "Couldn't reach Stringer. Check your connection and try again." }; }
    if (!out.ok) {
      if (out.code === 'report_limit') { state.site.reportsToday = state.site.reportsPerDay; transition(() => { $('#rp-body').innerHTML = reportsMaxHTML(); }); return; }
      if (send) { send.disabled = false; send.textContent = 'Send report'; }
      $('#rp-err').textContent = out.message || "That didn't send. Try again.";
      return;
    }
    state.reported.add(p.id);
    state.site.reportsToday = (state.site.reportsToday || 0) + 1;
    const st = storyEl(state.story);
    const part = $$('.part', st)[stories[state.story].cur ?? stories[state.story].at];
    transition(() => {
      $('#rp-body').innerHTML = `<div class="thanks"><span class="seal">${ICON.check}</span>
        <h2 class="sh-title" id="rp-title">${esc(out.message || D.gateMessages.report_thanks)}</h2>
        <p class="sh-fine" style="font-size:15px">${out.hidden ? 'The video is hidden until we do. You can keep watching the rest.' : 'You can keep watching the rest.'}</p>
        <div class="sh-actions"><button class="btn btn-ink" data-close>Back to the videos</button></div></div>`;
      if (part && out.hidden) part.classList.add('is-hidden');
    });
    const v = part && $('video', part);
    if (v && out.hidden) v.pause();
    $('[data-close]', $('#rp-body')).focus();
  }

  // ---- receipts (phone sheet) --------------------------------------------------------------------
  function openReceipts() {
    const p = curPart();
    if (!p) return;
    $('#rc-sheet').innerHTML = receiptsHTML(p, { head: true });
    const d = $('#dlg-receipts');
    openDialog(d);
    $$('.slip-text[data-decode]', d).forEach((el, i) => decode(el, { delay: 250 + i * 300, perChar: 12, max: 1100 }));
  }

  // ================================================================================================
  // NAVIGATION
  // ================================================================================================
  function goStory(si) {
    if (empty()) return Promise.resolve();
    si = Math.max(0, Math.min(stories.length - 1, si));
    const el = storyEl(si);
    const top = el.offsetTop - (feed.clientHeight - el.offsetHeight) / 2;
    feed.scrollTo({ top, behavior: reduced() ? 'auto' : 'smooth' });
    return new Promise((res) => setTimeout(res, reduced() ? 30 : 520));
  }
  function stepPart(d) {
    if (empty()) return;
    const s = stories[state.story];
    const cur = s.cur ?? s.at;
    const to = cur + d;
    if (to < 0 || to >= s.parts.length) { nudge(d); return; }
    scrollChainTo(state.story, to);
  }
  function nudge(d) {
    const c = $('.chain', storyEl(state.story));
    if (!c || reduced()) return;
    c.animate([{ transform: 'translateX(0)' }, { transform: `translateX(${-d * 14}px)` }, { transform: 'translateX(0)' }], { duration: 320, easing: 'cubic-bezier(.16,1,.3,1)' });
    toast(d < 0 ? 'This is the first video of this story.' : 'This is the latest video of this story.', { ms: 1600 });
  }

  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if ($('dialog[open]')) return;
    if (app.dataset.tab === 'events' && !mqDesk.matches) return;
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); goStory(state.story + 1); break;
      case 'ArrowUp': case 'k': e.preventDefault(); goStory(state.story - 1); break;
      case 'ArrowRight': e.preventDefault(); stepPart(1); break;
      case 'ArrowLeft': e.preventDefault(); stepPart(-1); break;
      case ' ': if (t && t.tagName === 'BUTTON') return; e.preventDefault(); togglePlay(); break;
      case 'm': case 'M': toggleSound(); break;
      case 'e': case 'E': openLane(app.dataset.lane !== 'open'); break;
      case 'r': case 'R': openReport(); break;
      case 'Escape': if (app.dataset.lane === 'open') openLane(false); break;
      default:
    }
  });

  document.addEventListener('click', (e) => {
    const b = e.target.closest('button, a');
    if (!b) return;
    if (b.matches('.tapzone')) {
      const part = b.closest('.part');
      const st = b.closest('.story');
      const si = +st.dataset.si, pi = +part.dataset.pi;
      if (si !== state.story) { goStory(si); return; }
      if (pi !== (stories[si].cur ?? stories[si].at)) { scrollChainTo(si, pi); return; }
      togglePlay();
      return;
    }
    if (b.dataset.goPart != null) { scrollChainTo(state.story, +b.dataset.goPart); return; }
    if (b.dataset.goStory != null) { goStory(+b.dataset.goStory); return; }
    if (b.hasAttribute('data-play')) { togglePlay(); return; }
    if (b.hasAttribute('data-sound')) { toggleSound(); return; }
    if (b.hasAttribute('data-report')) { const d = $('#dlg-receipts'); if (d.open) d.close(); openReport(); return; }
    if (b.hasAttribute('data-receipts')) { openReceipts(); return; }
    if (b.hasAttribute('data-open-lane')) { openLane(true); return; }
    if (b.dataset.openEv) { openEvent(b.dataset.openEv); return; }
    if (b.dataset.confirm) { confirm(b.dataset.confirm); return; }
    if (b.hasAttribute('data-watch-new')) { closeDialog($('#dlg-confirm')); setTab('videos'); openLane(false); goStory(0); return; }
    if (b.dataset.tab) { setTab(b.dataset.tab); return; }
  });

  // the receipts lip also opens on a swipe up
  feed.addEventListener('pointerdown', (e) => {
    const lip = e.target.closest('.lip');
    if (!lip) return;
    const y0 = e.clientY;
    const up = (ev) => { if (y0 - ev.clientY > 24) openReceipts(); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointerup', up);
  });

  $('#lane-strip').addEventListener('click', () => openLane(true));
  $('#lane-close').addEventListener('click', () => openLane(false));
  $('#lane-scrim').addEventListener('click', () => openLane(false));

  // ---- the account menu: who's signed in (Columbia through Google's sign-in in front of the site) ----
  function renderUser() {
    const u = D.user || {};
    const person = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true" style="width:18px;height:18px"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/></svg>';
    $$('.initials').forEach((el) => { el.innerHTML = u.initials ? esc(u.initials) : person; });
    $('#me-btn').setAttribute('aria-label', `Your account: ${u.email || u.name || 'you'}`);
    const who = $('#menu-me .who div');
    if (who) who.innerHTML = `<b>${esc(u.email ? u.name : 'Not signed in')}</b><span>${esc(u.email || 'Running on this computer')}</span>`;
    const fine = $('#menu-me .fine');
    if (fine && !u.iap) fine.textContent = 'On the website you sign in with your Columbia account. For now, only Columbia accounts can use Stringer.';
    const out = $('#sign-out');
    if (out && !u.signOut) out.closest('li').remove();
  }
  renderUser();
  $('#sign-out')?.addEventListener('click', () => {
    $('#menu-me').hidePopover?.();
    const v = activeVideo(); if (v) v.pause();
    location.href = D.user.signOut;
  });
  $('#sign-in').addEventListener('click', () => { location.href = '/feed'; });

  // ================================================================================================
  // LIVE: ask the site again (every 3 s while a video is being made, else every minute)
  // ================================================================================================
  let pollT = null;
  function poll(ms) {
    if (still) return;
    clearTimeout(pollT);
    pollT = setTimeout(async () => { await refresh(); poll(nextWait()); }, ms);
  }
  const nextWait = () => (state.events.some((e) => e.state === 'making') || state.mine.size ? 3000 : 60000);
  let refreshing = false;
  async function refresh() {
    if (refreshing || document.hidden) return;
    refreshing = true;
    try { apply(await GET('/api/site')); }
    catch (err) { /* keep what's on the page; try again next time */ }
    finally { refreshing = false; }
  }
  function apply(nd) {
    const before = new Map(state.events.map((e) => [e.id, e]));
    D.now = nd.now; D.site = nd.site; D.videos = nd.videos || []; D.chains = nd.chains || {}; D.listError = nd.listError;
    state.site = { ...nd.site };
    state.events = (nd.events || []).map((e) => ({ ...e, progress: e.progress ? { ...e.progress } : null }));
    // runs this page started stay "mine" until they end, even if the event drops off the list
    const have = new Set(stories.flatMap((s) => s.parts.map((p) => p.id)));
    const shown = new Set(D.videos.map((v) => v.id));
    for (const v of D.videos.slice().reverse()) {          // oldest first, so the newest ends on top
      if (v.hidden || have.has(v.id)) continue;
      const mine = state.mine.has(v.event);
      addStory(v, mine);
      if (mine) {
        state.mine.delete(v.event);
        const d = $('#dlg-confirm');
        if (d.open && d.dataset.ev === v.event) {
          transition(() => {
            $('#cf-body').innerHTML = `<p class="caps sh-kicker">Done</p><h2 class="sh-title" id="cf-title">${esc(v.eventTitle || v.headline)}</h2>
              <p class="sh-fine" style="font-size:15px">Your video is ready. It's at the top of Hot right now.</p>
              <div class="sh-actions"><button class="btn btn-line" data-close>Later</button><button class="btn btn-ink" data-watch-new>Watch it</button></div>`;
          });
        } else toast(`Your video is ready: ${esc(v.headline)}`, { ms: 7000, action: { label: 'Watch', run: () => { setTab('videos'); openLane(false); goStory(0); } } });
      } else if (before.get(v.event) && before.get(v.event).state === 'making') {
        toast(`A new video is up: ${esc(v.headline)}`, { ms: 6000, action: { label: 'Watch', run: () => { setTab('videos'); openLane(false); goStory(0); } } });
      }
    }
    // videos taken down or hidden since the page loaded
    stories.forEach((s) => s.parts.forEach((p) => { if (p.kind === 'video' && !shown.has(p.id)) hideStory(p.id); }));
    // runs that ended without a video
    for (const id of [...before.keys()]) {
      const was = before.get(id);
      const now = evById(id);
      if (was.state !== 'making' || !now || now.state === 'making' || now.state === 'has_video') continue;
      const mine = state.mine.has(id) || (was.progress && was.progress.by === 'you');
      state.mine.delete(id);
      const d = $('#dlg-confirm');
      const open = d.open && d.dataset.ev === id;
      if (now.state === 'no_video') {
        if (open) transition(() => { $('#cf-body').innerHTML = noVideoHTML(now); });
        else if (mine) toast(`No video for “${esc(now.title)}”. ${esc(now.reason || '')}`, { ms: 8000, action: { label: 'See why', run: () => { location.href = progressURL(now); } } });
      } else if (now.state === 'ready' && mine) {
        const note = { t: "The video didn't finish", b: 'Something went wrong while it was being made. Nothing went up. You can try again.', icon: ICON.cross };
        if (open) transition(() => { $('#cf-body').innerHTML = stopHTML(now, note); });
        else toast(`The video for “${esc(now.title)}” didn't finish. You can try again.`, { ms: 8000 });
      }
    }
    for (const id of state.mine) if (!evById(id)) state.mine.delete(id);
    renderEvents();
    state.events.forEach((e) => { if (e.state === 'making') tickUI(e); });
    // a dialog about a ready event re-reads the limits
    const d = $('#dlg-confirm');
    if (d.open) { const e = evById(d.dataset.ev); if (e && e.state === 'ready' && $('[data-confirm]', d) && liveLimit() !== 'none') $('#cf-body').innerHTML = confirmHTML(e); }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { refresh().then(() => poll(nextWait())); } });

  // ================================================================================================
  // START
  // ================================================================================================
  renderFeed();
  renderIndex();
  renderEvents();
  if (CSS.supports && CSS.supports('animation-timeline: view()')) document.documentElement.classList.add('sd-on');
  requestAnimationFrame(() => {
    setStory(0);
    if (!empty()) $$('.story', feed)[0].classList.add('is-active');
    activate();
  });
  window.addEventListener('resize', () => { sizeRides(); railKey = ''; renderRails(); });
  mqDesk.addEventListener?.('change', () => { railKey = ''; renderRails(); });
  poll(nextWait());
  // hide the swipe hint after a few seconds
  setTimeout(() => { const h = $('#hint'); if (h) h.classList.add('gone'); }, 9000);

  // ---- how big the neighbouring parts can be: they must fit beside the playing video ----------------
  function fitPeek() {
    const f = $('#feed'), p = $('.part.is-active .frame') || $('.part .frame');
    if (!f || !p) return;
    const inset = parseFloat(getComputedStyle(f).getPropertyValue('--peek-inset')) || 0;   // room taken by the story index
    const pw = p.offsetWidth, room = (f.clientWidth - pw) / 2 - 22 - 20 - inset;
    const k = Math.max(0.16, Math.min(0.46, room / pw));
    f.style.setProperty('--peek', k.toFixed(3));
    f.classList.toggle('peek-small', k < 0.25);   // too small for the "Earlier · date" label
  }
  fitPeek();
  if (window.ResizeObserver) new ResizeObserver(fitPeek).observe($('#feed'));

  // for the screenshot script
  window.FEED = {
    stories, state, goStory, stepPart, scrollChainTo, openReceipts, openReport, openEvent, confirm, setTab, openLane, toggleSound, togglePlay, refresh, evById,
    instant: (si, pi) => { if (empty()) return; const h = $('#hint'); if (h && pi != null) h.classList.add('gone'); const el = storyEl(si); feed.scrollTop = el.offsetTop - (feed.clientHeight - el.offsetHeight) / 2; setStory(si); if (pi != null) scrollChainTo(si, pi, false); activate(); },
  };
})();
