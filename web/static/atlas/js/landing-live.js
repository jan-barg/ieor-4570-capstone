// The landing page's real figures (module 9): the daily limit, the per-person and at-once limits, the usual
// cost and the cap come from the Gate (/api/site), so the page never states an old number. The story the
// map plays stays the made-up one in landing-story.js.
(function () {
  'use strict';
  const set = (key, text) => document.querySelectorAll(`[data-live="${key}"]`).forEach((el) => { el.textContent = text; });
  const money = (u) => (u >= 1 && Math.abs(u - Math.round(u)) < 0.005 ? `$${Math.round(u)}` : `$${u.toFixed(2)}`);
  fetch('/api/site', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((d) => {
      const s = d.site || {};
      if (s.estimatePerVideo) set('estimate', money(s.estimatePerVideo));
      if (s.capPerVideo) set('cap', money(s.capPerVideo));
      if (s.videosPerDay) set('perDay', String(s.videosPerDay));
      if (s.perPersonPerHour) set('perHour', String(s.perPersonPerHour));
      if (s.atOnce) set('atOnce', String(s.atOnce));
      const left = Math.max(0, (s.videosPerDay || 0) - (s.videosToday || 0));
      const line = !s.open ? 'New videos are paused right now. You can still watch everything already made.'
        : left === 0 ? `Today's ${s.videosPerDay} videos are made. Pick a story and watch; new ones start at midnight, New York time.`
          : `${s.videosToday} of today's ${s.videosPerDay} videos are made. Pick a story and watch, or make the next one.`;
      set('todayLine', line);
    })
    .catch(() => { /* the page keeps its written figures */ });
})();
