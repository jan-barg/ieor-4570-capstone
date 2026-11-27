// Admin: Jan's review desk, on the site's real records (module 9).
// The lock screen's password is the site's admin token (GATE_ADMIN_TOKEN). It is kept for this tab only
// (sessionStorage) and sent as the X-Admin-Token header: GET /admin/api for the desk's data, and
// POST /admin/api/<take_down|restore|remake|pause|open> for Jan's actions. The desk reloads every 15 s.
(function () {
  'use strict';
  const { ICON, $, $$, esc, clock, when, transition, toast, reduced, cap } = window.SG;
  const params = new URLSearchParams(location.search);
  const STILL = params.has('still');
  const phone = window.matchMedia('(max-width: 759.98px)');
  const TOKEN_KEY = 'stringer-admin-token';

  ICON.gauge = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 16.5a7.5 7.5 0 1 1 15 0"/><path d="M12 16.5l3.5-4.5"/></svg>';
  ICON.playSm = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>';

  // ---- talking to the site --------------------------------------------------------------------------
  let token = '';
  try { token = sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { /* private mode: ask each time */ }
  async function api(path, body) {
    const r = await fetch(path, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Admin-Token': token, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let out = {};
    try { out = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) { const err = new Error(out.error || `HTTP ${r.status}`); err.status = r.status; throw err; }
    return out;
  }

  // ---- state, from /admin/api -------------------------------------------------------------------------
  let A = null;                 // the last answer
  const S = { queue: [], logFilter: 'all', fresh: new Set() };
  let REASON = {};
  let videos = [];
  const vById = (id) => videos.find((v) => v.id === id);

  function load(data) {
    A = data;
    REASON = Object.fromEntries((data.reportReasons || []).map((r) => [r.key, r.label]));
    videos = (data.videos || []).map((v) => ({ ...v, status: v.status === 'up' && v.keptUp ? 'kept' : v.status }));
    const site = data.site || {};
    Object.assign(S, {
      open: site.open, today: site.videosToday, perDay: site.videosPerDay, atOnce: site.atOnce, perHour: site.perPersonPerHour,
      making: data.making || [], credits: site.searchCreditsLeft, pauseAt: site.searchCreditsPauseAt,
      spent: (data.spend || {}).today || 0, inProgress: (data.spend || {}).inProgressEstimate || 0,
      est: site.estimatePerVideo, capUsd: site.capPerVideo,
      week: ((data.spend || {}).last7days || []), perStep: (data.spend || {}).perStep || {},
      reports: (data.reports || []).map((r) => ({ ...r })),
      modeBy: site.modeBy, modeAt: site.modeAt,
    });
    // the queue: videos the first report hid, oldest first (Jan's own take-downs aren't waiting for anyone)
    const waiting = (data.hidden || []).filter((h) => h.by === 'reports').sort((a, b) => new Date(a.since) - new Date(b.since)).map((h) => h.video);
    const keep = S.queue.filter((id) => waiting.includes(id));             // keep Jan's order (Next one)
    S.queue = [...keep, ...waiting.filter((id) => !keep.includes(id))];
    S.log = (data.log || []).map((l, i) => ({ ...l, t: new Date(l.at), i, fresh: S.fresh.has(l.at + l.kind) }));
    S.fresh.clear();
  }

  const KIND = {
    start: ['Started', 'k-start'], video_done: ['Made', 'k-done'], video_no_video: ['No video', 'k-novideo'],
    video_failed: ['Failed', 'k-failed'], report: ['Report', 'k-report'], hidden: ['Hidden', 'k-hidden'],
    taken_down: ['Taken down', 'k-down'], restored: ['Back up', 'k-restored'], remake: ['Remake', 'k-remake'],
    paused: ['Paused', 'k-down'], opened: ['Opened', 'k-restored'],
  };
  const STATUS = {
    up: ['Up', 's-up'], kept: ['Up · stays up', 's-kept'], hidden: ['Hidden · waiting', 's-hidden'],
    down: ['Taken down', 's-down'], remake: ['Remake ordered', 's-remake'], making: ['Being made', 's-remake'],
    no_video: ['No video', 's-down'],
  };
  const money = (n) => '$' + (+n || 0).toFixed(2);
  const stepLabel = (key) => ((A.steps || []).find((s) => s.key === key) || {}).label || 'Starting';

  // ---- header ----------------------------------------------------------------------------------------
  function renderHeader() {
    $('#site-state').innerHTML = S.open
      ? `<span class="dot on"></span><b>Open</b><span class="ss"><span class="sep">·</span>${S.today} of ${S.perDay} today</span><span class="ss ss-2"><span class="sep">·</span>${S.making.length} being made</span>`
      : `<span class="dot off"></span><b>Paused</b><span class="ss"><span class="sep">·</span>no new videos</span><span class="ss ss-2"><span class="sep">·</span>${S.making.length} finishing</span>`;
    $('#closed-band').hidden = S.open;
    document.body.classList.toggle('is-closed', !S.open);
    const n = S.queue.length;
    $('#tb-badge').textContent = n || '';
    $('#tb-badge').hidden = !n;
  }

  // ---- status ----------------------------------------------------------------------------------------
  const STEP_C = { sides: 'var(--other)', gather: 'var(--cobalt)', same_story: 'var(--side-a)', balance_pick: 'var(--land)', story_file: 'var(--ink)', fact_check: 'var(--side-b)', script: 'var(--mustard)', video: 'var(--vermilion)' };
  function renderStatus() {
    const done = Math.max(0, S.today - S.making.length);
    const dots = Array.from({ length: S.perDay }, (_, i) => `<i class="${i < done ? 'full' : i < S.today ? 'mid' : ''}"></i>`).join('');
    const known = S.credits != null;
    const low = known && S.credits < S.pauseAt + 20;
    const creditScale = Math.max(100, S.pauseAt * 3);   // the bar shows the last credits, where the pause line lives
    const wk = S.week.map((d, i) => ({ v: d.usd || 0, n: d.videos || 0, label: i === S.week.length - 1 ? 'Today' : new Intl.DateTimeFormat('en-US', { weekday: 'short', timeZone: 'UTC' }).format(new Date(d.day + 'T12:00:00Z')) }));
    const wmax = Math.max(...wk.map((d) => d.v), 0.01);
    const stepKeys = Object.keys(S.perStep).filter((k) => S.perStep[k] > 0);
    const stepTotal = stepKeys.reduce((a, k) => a + S.perStep[k], 0);
    const modeNote = S.modeBy ? ` Last switched by ${esc(S.modeBy)}${S.modeAt ? `, ${esc(when(S.modeAt))}` : ''}.` : '';

    $('#status').innerHTML = `
      <div class="st st-site">
        <button type="button" role="switch" class="switch" id="site-switch" aria-checked="${S.open}" aria-label="New videos">
          <span class="sw-track"><span class="sw-knob"></span></span>
          <span class="sw-text"><b>${S.open ? 'Open' : 'Paused'}</b><span>${S.open ? 'People can start new videos.' : "People can watch, but can't start new videos."}${modeNote}</span></span>
        </button>
      </div>

      <div class="st">
        <p class="caps st-k">Videos today</p>
        <p class="st-big num">${S.today}<small> of ${S.perDay}</small></p>
        <div class="dayline" role="img" aria-label="${done} made, ${S.making.length} being made, ${Math.max(0, S.perDay - S.today)} left">${dots}</div>
        <p class="st-note">Back to 0 at midnight, New York time. Each person can start ${S.perHour} an hour.</p>
      </div>

      <div class="st">
        <p class="caps st-k">Being made</p>
        <p class="st-big num">${S.making.length}<small> of ${S.atOnce} at once</small></p>
        <ul class="mk-list">${S.making.map((m) => `
          <li><p class="mk-t"><a href="/progress?event=${encodeURIComponent(m.id)}" style="color:inherit">${esc(m.title)}</a></p>
            <div class="mk-bar"><span style="--p:${(+m.pct || 0).toFixed(1)}%"></span></div>
            <p class="mk-s"><span>${esc(stepLabel(m.step))}</span><span class="num">${Math.floor(+m.pct || 0)}%</span></p></li>`).join('') || '<li class="mk-none">Nothing being made right now.</li>'}
        </ul>
      </div>

      <div class="st ${low ? 'is-low' : ''}">
        <p class="caps st-k">Searches${low ? '<span class="low-chip">Running low</span>' : ''}</p>
        ${known ? `<p class="st-big num">${S.credits}<small> left this month</small></p>
        <div class="credit-bar" role="img" aria-label="${S.credits} search credits left. New videos pause below ${S.pauseAt}.">
          <span class="fill" style="--p:${Math.min(100, S.credits / creditScale * 100)}%"></span>
          <span class="line" style="--p:${S.pauseAt / creditScale * 100}%"><em>pause at ${S.pauseAt}</em></span>
        </div>
        <p class="st-note">New videos stop by themselves below ${S.pauseAt}, which is ${Math.max(0, S.credits - S.pauseAt)} searches away.</p>`
        : `<p class="st-big num">–<small> left this month</small></p><p class="st-note">Tavily didn't say how many are left just now. New videos stop by themselves below ${S.pauseAt}.</p>`}
      </div>

      <div class="st">
        <p class="caps st-k">Money</p>
        <p class="st-big num">${money(S.spent)}<small> spent today</small></p>
        <dl class="money">
          <div><dt>Being made now</dt><dd class="num">about ${money(S.inProgress)}</dd></div>
          <div><dt>A video, usually</dt><dd class="num">about ${money(S.est)}</dd></div>
          <div><dt>Cap for one video</dt><dd class="num">${money(S.capUsd)}</dd></div>
        </dl>
      </div>

      <div class="st">
        <p class="caps st-k">Last 7 days</p>
        <div class="week" role="img" aria-label="Spending over the last 7 days: ${wk.map((d) => d.label + ' ' + money(d.v)).join(', ')}">
          ${wk.map((d, i) => `<div class="wk${i === wk.length - 1 ? ' today' : ''}"><span class="wv num">${money(d.v).replace('$', '')}</span><span class="wb" style="--h:${(d.v / wmax * 100).toFixed(1)}%"></span><span class="wd">${d.label}</span></div>`).join('')}
        </div>
        <p class="st-note num">${money(wk.reduce((a, d) => a + d.v, 0))} this week, ${wk.reduce((a, d) => a + d.n, 0)} runs.</p>
      </div>

      <div class="st">
        <p class="caps st-k">Where today's ${money(stepTotal)} went</p>
        ${stepKeys.length ? `<div class="dotbar steps-bar" role="img" aria-label="${stepKeys.map((k) => stepLabel(k) + ' ' + money(S.perStep[k])).join(', ')}">
          ${stepKeys.map((k) => `<span style="--n:${Math.max(0.002, S.perStep[k])};--c:${STEP_C[k] || 'var(--other)'}"></span>`).join('')}
        </div>
        <ul class="steps-key">${stepKeys.map((k) => `<li><i style="--c:${STEP_C[k] || 'var(--other)'}"></i>${esc(stepLabel(k))}<span class="num">${S.perStep[k] < 0.01 ? '<$0.01' : money(S.perStep[k])}</span></li>`).join('')}</ul>`
        : '<p class="st-note">Nothing spent yet today.</p>'}
      </div>`;
    $('#site-switch').addEventListener('click', toggleSite);
  }

  function toggleSite() {
    if (S.open) {
      ask({
        title: 'Pause new videos?',
        body: `<p>People can still watch every video. The event list will say “${esc((A.gateMessages || {}).closed || 'New videos are paused right now.')}”</p><p>The ${S.making.length} being made now will finish.</p>`,
        note: { label: 'Why', hint: 'for the log, optional' },
        confirm: 'Pause new videos', danger: true,
        run: (note) => doAct('pause', { note }, 'New videos are paused.'),
      });
    } else {
      doAct('open', {}, 'Open again. People can start new videos.');
    }
  }

  // ---- the queue --------------------------------------------------------------------------------------
  function reportsFor(id) { return S.reports.filter((r) => r.video === id).sort((a, b) => new Date(a.at) - new Date(b.at)); }

  function qcardHTML(id, i, n) {
    const v = vById(id) || { id, headline: ((A.hidden || []).find((h) => h.video === id) || {}).headline || id };
    const h = (A.hidden || []).find((x) => x.video === id) || {};
    const reps = reportsFor(id);
    const facts = [v.made ? `Made ${esc(when(v.made))}` : '', v.articles ? `${v.articles} articles from ${v.outlets} outlets` : '',
      v.claims ? `${v.claimsBacked} of ${v.claims} claims backed` : '', v.cost != null ? money(v.cost) : ''].filter(Boolean).join(' · ');
    return `<article class="qcard" data-id="${esc(id)}" style="view-transition-name:q-${esc(String(id).replace(/[^A-Za-z0-9_-]/g, ''))}" aria-labelledby="qh-${esc(id)}">
      <div class="q-left"><div class="q-video">
        ${v.poster ? `<img src="${esc(v.poster)}" alt="" onerror="this.remove()">` : ''}
        <video playsinline preload="none" data-src="${esc(v.src || '')}" aria-label="The hidden video: ${esc(v.headline)}"></video>
        <span class="pill q-hidden">${ICON.eyeOff}Hidden</span>
        ${v.src ? `<button class="q-play" type="button" aria-label="Play the video">${ICON.playSm}<span>${esc(v.duration || '')}</span></button>` : ''}
      </div></div>
      <div class="q-body">
        <p class="q-pos caps"><span>${i + 1} of ${n}</span>${h.since ? `<span>Hidden ${esc(when(h.since))}</span>` : ''}${n > 1 ? '<button class="q-skip" type="button" data-skip>Next one</button>' : ''}</p>
        <h3 id="qh-${esc(id)}">${esc(v.headline)}</h3>
        <p class="q-sub">${facts}</p>
        ${v.eventTitle && v.eventTitle !== v.headline ? `<p class="q-ev"><span class="caps">The event</span>${esc(v.eventTitle)}</p>` : ''}
        <p class="caps q-rk">${reps.length === 1 ? '1 report' : reps.length + ' reports'}</p>
        <ol class="q-reports">${reps.map((r, k) => `
          <li class="rslip">
            <p class="rs-top"><span class="reason">${esc(REASON[r.reason] || r.reason)}</span>${k === 0 ? '<span class="first">This one hid it</span>' : ''}</p>
            ${r.note ? `<p class="rs-note">“${esc(r.note)}”</p>` : '<p class="rs-note none">No note.</p>'}
            <p class="rs-from">${esc(r.visitor)} · ${esc(when(r.at))}</p>
          </li>`).join('')}
        </ol>
        <div class="q-actions">
          <label class="stay"><input type="checkbox" data-stay> <span>Keep it up even if it gets reported again</span></label>
          <div class="q-btns">
            <button class="btn btn-ink" type="button" data-act="keep">${ICON.check}Keep up</button>
            <button class="btn btn-red" type="button" data-act="down">${ICON.cross}Take down</button>
            <button class="btn btn-line" type="button" data-act="remake">${ICON.redo}Remake</button>
          </div>
        </div>
      </div>
    </article>`;
  }

  function renderQueue() {
    const n = S.queue.length;
    $('#q-count').innerHTML = n ? `<b class="num">${n}</b> hidden, oldest first` : 'All clear';
    $('#queue').innerHTML = n ? S.queue.map((id, i) => qcardHTML(id, i, n)).join('') : `
      <div class="q-empty">
        <span class="q-empty-mark" aria-hidden="true">${ICON.check}</span>
        <h3>Nothing waiting.</h3>
        <p>When someone reports a video, it comes off the site right away and shows up here.</p>
        <button class="btn btn-line btn-sm" type="button" data-goto="log">See what happened today</button>
      </div>`;
    $$('.qcard').forEach((card) => {
      const id = card.dataset.id;
      $$('[data-act]', card).forEach((b) => b.addEventListener('click', () => act(b.dataset.act, id, card)));
      const vid = $('video', card), play = $('.q-play', card);
      if (play) {
        play.addEventListener('click', () => {
          if (!vid.getAttribute('src')) vid.src = vid.dataset.src;
          if (vid.paused) { vid.play().then(() => card.classList.add('playing')).catch(() => {}); play.setAttribute('aria-label', 'Pause the video'); }
          else { vid.pause(); card.classList.remove('playing'); play.setAttribute('aria-label', 'Play the video'); }
        });
        vid.addEventListener('click', () => play.click());
      }
      const skip = $('[data-skip]', card);
      if (skip) skip.addEventListener('click', () => transition(() => { S.queue.push(S.queue.shift()); renderQueue(); }));
    });
    const g = $('[data-goto]', $('#queue'));
    if (g) g.addEventListener('click', () => setTab(g.dataset.goto));
  }

  function act(kind, id, card) {
    const v = vById(id) || { headline: id };
    if (kind === 'keep') {
      const stay = card ? $('[data-stay]', card).checked : false;
      doAct('restore', { event: id, keep_up: stay, note: stay ? 'marked to stay up' : '' }, `Back up: <b>${esc(v.headline)}</b>.`);
    }
    if (kind === 'down') {
      ask({
        title: 'Take this video down?',
        body: `<p class="dlg-vid">“${esc(v.headline)}”</p><p>It stays off the site, and nobody can make a new video of this event until you restore it.</p>`,
        note: { label: 'Why', hint: 'for the log, optional' },
        confirm: 'Take it down', danger: true,
        run: (note) => doAct('take_down', { event: id, note }, `Taken down: <b>${esc(v.headline)}</b>.`),
      });
    }
    if (kind === 'remake') {
      ask({
        title: 'Have it made again?',
        body: `<p class="dlg-vid">“${esc(v.headline)}”</p><p>This video comes off the site for good. Its event goes back on the list as ready, and the next person who picks it starts a new video. That one counts toward the day's ${S.perDay}.</p>`,
        note: { label: 'What should change', hint: 'goes in the log', required: true },
        confirm: 'Clear it for a remake', danger: false,
        run: (note) => doAct('remake', { event: id, note }, `Cleared for a remake: <b>${esc(v.headline)}</b>.`),
      });
    }
  }
  // one of Jan's actions: tell the site, then show what the site now says
  async function doAct(action, body, said) {
    try {
      const out = await api(`/admin/api/${action}`, body);
      if (out.ok === false) { toast(esc(out.message || "That didn't work.")); return; }
      await reload(true);
      toast(said);
    } catch (e) {
      if (e.status === 401) { lock("That password isn't right any more. Unlock again."); return; }
      toast("Couldn't reach the site. Try again.");
    }
  }

  // ---- all reports -------------------------------------------------------------------------------------
  function renderReports() {
    const rows = S.reports.slice().sort((a, b) => new Date(b.at) - new Date(a.at));
    $('#reports-meta').textContent = `${rows.length} saved. Each visitor can send ${(A.site || {}).reportsPerDay || 5} a day.`;
    $('#reports').innerHTML = `<div class="rt-row rt-head" role="row">
        <span role="columnheader">When</span><span role="columnheader">Reason</span><span role="columnheader">Video and note</span><span role="columnheader">Where it stands</span></div>` +
      (rows.map((r) => {
        const waiting = /waiting/.test(r.status);
        return `<div class="rt-row${waiting ? ' waiting' : ''}" role="row">
          <span role="cell" class="rt-when num">${esc(when(r.at))}<small>${esc(r.visitor)}</small></span>
          <span role="cell"><span class="reason">${esc(REASON[r.reason] || r.reason)}</span></span>
          <span role="cell" class="rt-what"><b>${esc(r.headline || (vById(r.video) || {}).headline || r.video)}</b>${r.note ? `<span class="rt-note">“${esc(r.note)}”</span>` : '<span class="rt-note none">No note.</span>'}</span>
          <span role="cell" class="rt-status">${waiting ? `<button class="btn btn-sm btn-ink" type="button" data-review="${esc(r.video)}">Review</button>` : esc(cap(r.status))}</span>
        </div>`;
      }).join('') || '<div class="rt-row" role="row"><span role="cell" class="rt-what" style="grid-column:1/-1"><span class="rt-note none">No reports yet.</span></span></div>');
    $$('[data-review]', $('#reports')).forEach((b) => b.addEventListener('click', () => review(b.dataset.review)));
  }

  function review(id) {
    if (phone.matches) {
      S.queue = [id, ...S.queue.filter((q) => q !== id)];
      setTab('queue');
      renderQueue();
    } else {
      const card = $(`.qcard[data-id="${CSS.escape(id)}"]`);
      if (card) { card.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'center' }); card.classList.add('flash'); setTimeout(() => card.classList.remove('flash'), 1400); $('[data-act="keep"]', card).focus({ focusVisible: true }); }
    }
  }

  // ---- all videos ------------------------------------------------------------------------------------
  function renderVideos() {
    const up = videos.filter((v) => v.status === 'up' || v.status === 'kept').length;
    $('#videos-meta').textContent = `${videos.length} videos · ${up} up`;
    $('#videos').innerHTML = videos.map((v) => {
      const [label, cls] = STATUS[v.status] || [cap(v.status), 's-down'];
      let btns = '';
      if (v.status === 'up' || v.status === 'kept') btns = `<button class="btn btn-sm btn-line" type="button" data-vact="down" data-id="${esc(v.id)}">Take down</button><button class="btn btn-sm btn-ghost" type="button" data-vact="remake" data-id="${esc(v.id)}">Remake</button>`;
      else if (v.status === 'hidden') btns = `<button class="btn btn-sm btn-ink" type="button" data-vact="review" data-id="${esc(v.id)}">Review</button>`;
      else if (v.status === 'down') btns = `<button class="btn btn-sm btn-line" type="button" data-vact="restore" data-id="${esc(v.id)}">Restore</button>`;
      else if (v.status === 'no_video') btns = `<a class="btn btn-sm btn-ghost" href="/progress?event=${encodeURIComponent(v.id)}">See why</a><button class="btn btn-sm btn-ghost" type="button" data-vact="remake" data-id="${esc(v.id)}">Remake</button>`;
      else btns = '<span class="vl-wait">Waiting for a new video</span>';
      const meta = [v.made ? esc(when(v.made)) : '', v.duration ? esc(v.duration) : '', v.cost != null ? money(v.cost) : ''].filter(Boolean).join(' · ');
      return `<li class="vl ${cls}">
        <span class="vl-pic">${v.poster && v.status !== 'no_video' ? `<img src="${esc(v.poster)}" alt="" onerror="this.remove()">` : `<span class="vl-gone">${ICON.eyeOff}</span>`}</span>
        <div class="vl-main">
          <p class="vl-h"><a href="/progress?event=${encodeURIComponent(v.id)}" style="color:inherit;text-decoration:none">${esc(v.headline || v.eventTitle)}</a></p>
          <p class="vl-m">${meta}${v.reports ? ` · <span class="vl-rep">${v.reports === 1 ? '1 report' : v.reports + ' reports'}</span>` : ''}${v.status === 'no_video' && v.noVideoReason ? ` · ${esc(String(v.noVideoReason).slice(0, 90))}${String(v.noVideoReason).length > 90 ? '…' : ''}` : ''}</p>
        </div>
        <span class="vl-status"><span class="schip">${esc(label)}</span></span>
        <span class="vl-acts">${btns}</span>
      </li>`;
    }).join('') || '<li class="vl"><div class="vl-main"><p class="vl-m">No videos yet.</p></div></li>';
    $$('[data-vact]', $('#videos')).forEach((b) => b.addEventListener('click', () => {
      const id = b.dataset.id, v = vById(id), k = b.dataset.vact;
      if (k === 'review') return review(id);
      if (k === 'restore') return doAct('restore', { event: id }, `Back up: <b>${esc(v.headline)}</b>.`);
      act(k, id, null);
    }));
  }

  // ---- the log --------------------------------------------------------------------------------------
  const FILTER = {
    all: () => true,
    reports: (l) => l.kind === 'report' || l.kind === 'hidden',
    videos: (l) => /^(start|video_)/.test(l.kind),
    jan: (l) => ['taken_down', 'restored', 'remake', 'paused', 'opened'].includes(l.kind),
  };
  const nyDay = (d) => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  function renderLog() {
    const items = (S.log || []).filter(FILTER[S.logFilter]);
    const today = nyDay(new Date()), yesterday = nyDay(new Date(Date.now() - 864e5));
    let lastDay = '';
    const dayName = (t) => { const k = nyDay(t); return k === today ? 'Today' : k === yesterday ? 'Yesterday' : new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'long' }).format(t); };
    $('#log').innerHTML = items.map((l) => {
      let head = '';
      const dn = dayName(l.t);
      if (dn !== lastDay) { head = `<li class="lg-day caps">${dn}</li>`; lastDay = dn; }
      const [label, cls] = KIND[l.kind] || [cap(String(l.kind).replace(/_/g, ' ')), ''];
      return head + `<li class="lg${l.fresh ? ' fresh' : ''}">
        <span class="lg-t num">${esc(clock(l.at))}</span>
        <span class="kchip ${cls}">${esc(label)}</span>
        <div class="lg-body"><p class="lg-w">${esc(l.what || l.event || '')}</p><p class="lg-d">${esc(l.who)}${l.detail ? ' · ' + esc(l.detail) : ''}</p></div>
      </li>`;
    }).join('') || '<li class="lg-none">Nothing of that kind in the last 3 days.</li>';
  }
  $$('.log-filter .chip').forEach((b) => b.addEventListener('click', () => {
    S.logFilter = b.dataset.f;
    $$('.log-filter .chip').forEach((c) => c.setAttribute('aria-pressed', String(c === b)));
    renderLog();
  }));

  // ---- confirm dialogs --------------------------------------------------------------------------------
  const dlg = $('#dlg');
  function ask({ title, body, note, confirm, danger, run }) {
    const max = 1000;
    $('#dlg-card').innerHTML = `
      <button class="sheet-x" value="cancel" formnovalidate aria-label="Close">${ICON.close}</button>
      <h2 class="dlg-title" id="dlg-title">${esc(title)}</h2>
      <div class="dlg-body">${body}</div>
      ${note ? `<div class="field">
        <label for="dlg-note">${esc(note.label)} <span>(${esc(note.hint)}${note.required ? ', needed' : ''})</span></label>
        <textarea id="dlg-note" maxlength="${max}" rows="3"${note.required ? ' required' : ''}></textarea>
        <p class="help"><span id="dlg-err" role="alert"></span><span id="dlg-count" class="num">0 / ${max}</span></p>
      </div>` : ''}
      <div class="dlg-btns">
        <button class="btn ${danger ? 'btn-red' : 'btn-ink'}" value="ok" id="dlg-ok">${esc(confirm)}</button>
        <button class="btn btn-line" value="cancel" formnovalidate>Cancel</button>
      </div>`;
    const ta = $('#dlg-note');
    if (ta) ta.addEventListener('input', () => { $('#dlg-count').textContent = `${ta.value.length} / ${max}`; $('#dlg-err').textContent = ''; });
    $('#dlg-ok').addEventListener('click', (e) => {
      if (note && note.required && !ta.value.trim()) { e.preventDefault(); $('#dlg-err').textContent = 'Write a note first. Stringer needs to know what to fix.'; ta.focus(); }
    });
    dlg.onclose = () => { if (dlg.returnValue === 'ok') run(ta ? ta.value.trim() : ''); };
    dlg.returnValue = '';
    dlg.showModal();
    (ta || $('#dlg-ok')).focus({ focusVisible: false });
  }
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close('cancel'); });

  // ---- phone tabs ------------------------------------------------------------------------------------
  const desk = $('#desk');
  $$('.tb-ic').forEach((s) => { s.innerHTML = ICON[s.dataset.ic] || ''; });
  $('.lock-ic').innerHTML = ICON.lock;
  function setTab(tab) {
    if (desk.dataset.tab === tab) return;
    transition(() => {
      desk.dataset.tab = tab;
      $$('.tabbar button').forEach((b) => (b.dataset.tab === tab ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current')));
      window.scrollTo(0, 0);
    });
  }
  $$('.tabbar button').forEach((b) => b.addEventListener('click', () => setTab(b.dataset.tab)));

  // ---- lock --------------------------------------------------------------------------------------------
  const lockErr = $('#pw-help');
  const helpText = lockErr.textContent;
  function showDesk() { document.body.dataset.locked = 'false'; desk.inert = false; $('#lock').inert = true; }
  async function unlock(pw) {
    token = pw;
    try {
      const data = await api('/admin/api');
      try { sessionStorage.setItem(TOKEN_KEY, token); } catch (e) { /* private mode: ask again next time */ }
      load(data);
      refresh();
      transition(showDesk);
      startPolling();
      setTimeout(() => $('#queue-title').focus({ focusVisible: false }), 60);
      return true;
    } catch (e) {
      token = '';
      lockErr.textContent = e.status === 401 ? "That isn't the admin password." : e.status === 503 ? "The admin password isn't set up on this site yet (GATE_ADMIN_TOKEN)." : "Couldn't reach the site. Try again.";
      lockErr.classList.add('err');
      $('#pw').setAttribute('aria-invalid', 'true');
      return false;
    }
  }
  function lock(msg) {
    transition(() => { document.body.dataset.locked = 'true'; desk.inert = true; $('#lock').inert = false; });
    token = '';
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* nothing */ }
    clearInterval(pollT);
    $('#pw').value = '';
    lockErr.textContent = typeof msg === 'string' ? msg : helpText;
    setTimeout(() => $('#pw').focus(), 60);
  }
  $('#pw').addEventListener('input', () => { lockErr.textContent = helpText; lockErr.classList.remove('err'); $('#pw').removeAttribute('aria-invalid'); });
  $('#queue-title').tabIndex = -1;
  $('#lock-form').addEventListener('submit', (e) => { e.preventDefault(); const pw = $('#pw').value.trim(); if (pw) unlock(pw); else $('#pw').focus(); });
  $('#lock-btn').addEventListener('click', () => lock());
  $('#reopen').addEventListener('click', toggleSite);

  // ---- live: the desk reloads every 15 s while it's open ----------------------------------------------------
  let pollT = null;
  async function reload(markNew) {
    const before = new Set((S.log || []).map((l) => l.at + l.kind));
    const data = await api('/admin/api');
    if (markNew) (data.log || []).forEach((l) => { if (!before.has(l.at + l.kind)) S.fresh.add(l.at + l.kind); });
    load(data);
    refresh();
  }
  function startPolling() {
    clearInterval(pollT);
    if (STILL) return;
    pollT = setInterval(() => {
      if (document.hidden || dlg.open || document.body.dataset.locked === 'true') return;
      reload(true).catch((e) => { if (e.status === 401) lock("That password isn't right any more. Unlock again."); });
    }, 15000);
  }

  function refresh() { if (!A) return; renderHeader(); renderStatus(); renderQueue(); renderReports(); renderVideos(); renderLog(); }
  if (token) unlock(token).then((ok) => { if (!ok) lock(); });
  window.ADMIN = { unlock, lock, setTab, act: (k, id) => act(k, id, $(`.qcard[data-id="${CSS.escape(id)}"]`)), ask, toggleSite, S, refresh, reload };
})();
