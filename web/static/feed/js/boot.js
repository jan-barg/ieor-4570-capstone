// Stringer (module 9): load a page's data as JSON from the site, then the page's own scripts in order.
// The design pages were drawn on window.STRINGER_DEMO and window.STRINGER_RUN (made-up files); the site
// serves the same shapes from real records, so the page code reads them the same way.
//   <script src="/static/feed/js/boot.js" data-load="STRINGER_DEMO=/api/site STRINGER_RUN=/api/progress"
//           data-query data-scripts="/static/feed/js/common.js /static/feed/js/progress.js"></script>
// data-query: the page's own ?query (the progress page's ?event=) goes on every data address.
(function () {
  'use strict';
  const me = document.currentScript;
  const loads = (me.dataset.load || '').split(/\s+/).filter(Boolean).map((x) => x.split('='));
  const scripts = (me.dataset.scripts || '').split(/\s+/).filter(Boolean);
  const query = me.hasAttribute('data-query') ? location.search : '';

  function getJSON(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then((r) => {
      if (r.ok) return r.json();
      return r.json().catch(() => ({})).then((b) => { const e = new Error(b.error || `HTTP ${r.status}`); e.status = r.status; e.body = b; throw e; });
    });
  }
  function load(src) {
    return new Promise((ok, no) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = ok;
      s.onerror = () => no(new Error('could not load ' + src));
      document.body.append(s);
    });
  }
  function trouble(err) {
    const box = document.createElement('div');
    box.className = 'boot-trouble';
    box.setAttribute('role', 'alert');
    box.style.cssText = 'position:fixed;inset:0;display:grid;place-items:center;z-index:99;background:var(--night,#0A1033);color:var(--paper,#F3EEE1);font:16px/1.5 StringerSans,system-ui,sans-serif;padding:24px;text-align:center';
    const msg = err && err.status === 404 ? (err.body && err.body.error ? err.body.error.charAt(0).toUpperCase() + err.body.error.slice(1) + '.' : 'There is nothing here.')
      : "Stringer couldn't load right now. Try again in a minute.";
    box.innerHTML = `<div style="max-width:420px"><p style="font-family:StringerSerif,Georgia,serif;font-size:22px;margin:0 0 10px">${msg.replace(/</g, '&lt;')}</p>
      <p style="margin:0 0 18px;opacity:.75">${location.pathname === '/progress' ? 'The run may not have started yet.' : ''}</p>
      <a href="/feed" style="color:inherit;margin-right:18px">Back to the feed</a><button type="button" style="font:inherit;color:inherit;background:none;border:1px solid currentColor;border-radius:999px;padding:6px 16px;cursor:pointer">Try again</button></div>`;
    box.querySelector('button').addEventListener('click', () => location.reload());
    document.body.append(box);
  }

  window.STRINGER_GET = getJSON;
  Promise.all(loads.map(([name, url]) => getJSON(url + query).then((d) => { window[name] = d; })))
    .then(() => scripts.reduce((p, src) => p.then(() => load(src)), Promise.resolve()))
    .catch((e) => { console.error(e); trouble(e); });
})();
