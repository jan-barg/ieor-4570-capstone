// The locked box for a model-written animation (custom animation, Nov 28). The drawing code is untrusted model
// output: it runs here, never in the Remotion render page, and only its frames (JPEG files) come out.
//
//   node anim/box.mjs <job.json> <out folder>
//   job.json: {code, frames, cues: {name: 0..1}, scale (1.2), quality (0.9), limit_ms (20), timeout_s (120)}
//   out: f0000.jpg, f0001.jpg, ... and one JSON line on stdout: {status, frames, ms, errors, blank, change, ...}
//
// What locks it, outermost first:
//   1. its own headless Chrome (the same binary as the render), started with a fresh throwaway profile, the OS
//      sandbox left on where the system allows it, no extensions, no background services, every host name
//      resolving to nothing and every connection sent to a dead proxy (loopback included);
//   2. driven over a pipe (--remote-debugging-pipe): no debugging port that anything else on the machine could reach;
//   3. the page is served from memory at a made-up https address, and every other request, from the page or the
//      worker, is refused by the browser's request interception (each refusal is counted and reported); the page is
//      also set offline (a worker can't be: Chrome refuses the setting for it, so the worker relies on the others);
//   4. the page's content security policy: nothing may load or connect (default-src 'none'), no eval or
//      new Function, scripts only with this run's nonce, workers only from blob: (the one the page makes);
//   5. the model's code runs in a Web Worker: no page, no DOM, no document to reach. runtime.js locks the worker
//      before the code loads (network, storage, timers, messages, other workers, decoders, raw pixels, text);
//   6. a watchdog: a frame that never finishes (an endless loop) ends the worker; the whole run has a time limit.
import {spawn} from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KIT = ['kit.js', 'kit_fx.js', 'kit_scene.js', 'kit_scene2.js', 'kit_scene3.js'];
const PAGE_URL = 'https://box.stringer.invalid/';
// The names the model's code sees as undefined (its wrapper's parameters), on top of runtime.js's lock. (eval can't
// be a parameter in strict code; the page's policy blocks it.)
const SHADOWED = ['window', 'document', 'globalThis', 'self', 'fetch', 'XMLHttpRequest', 'WebSocket', 'Worker', 'importScripts',
  'postMessage', 'localStorage', 'sessionStorage', 'indexedDB', 'navigator', 'location', 'setTimeout', 'setInterval',
  'requestAnimationFrame', 'Function', 'performance', 'Date', '__setDraw', 'caches', 'close', 'OffscreenCanvas',
  'createImageBitmap', 'Blob'];
const WATCHDOG_MS = 4000;          // no frame for this long: the worker is stopped

// The browser: on a Mac the copy render.mjs uses (Chrome stalls when its binary is inside ~/Desktop); elsewhere
// Remotion's own downloaded headless shell (Cloud Run); BOX_CHROME overrides both.
export function browserPath() {
  if (process.env.BOX_CHROME) return process.env.BOX_CHROME;
  const mac = path.join(os.homedir(), 'Library/Caches/stringer-render-test/chrome-headless-shell-mac-arm64/chrome-headless-shell');
  if (process.platform === 'darwin' && fs.existsSync(mac)) return mac;
  try {
    const require = createRequire(import.meta.url);
    const f = require('@remotion/renderer/dist/browser/BrowserFetcher.js');
    const p = f.getRevisionInfo('headless-shell').executablePath;
    if (p && fs.existsSync(p)) return p;
  } catch (e) { /* fall through */ }
  return null;
}

function chromeArgs(profile, sandbox) {
  return [
    '--headless', '--remote-debugging-pipe', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--disable-background-networking', '--disable-component-update', '--disable-default-apps',
    '--disable-sync', '--disable-domain-reliability', '--disable-breakpad', '--no-pings', '--mute-audio',
    '--disable-gpu', '--deny-permission-prompts', '--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication',
    '--host-resolver-rules=MAP * ~NOTFOUND', '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=<-loopback>',
    ...(sandbox ? [] : ['--no-sandbox']),
    'about:blank',
  ];
}

// A tiny DevTools-protocol client over the pipe: messages are JSON, each ended by a NUL byte.
function pipeClient(child) {
  const out = child.stdio[3], inp = child.stdio[4];
  let id = 0, buf = '';
  const waiting = new Map(), handlers = [];
  inp.setEncoding('utf8');
  inp.on('data', (chunk) => {
    buf += chunk;
    let at;
    while ((at = buf.indexOf('\0')) >= 0) {
      const msg = JSON.parse(buf.slice(0, at));
      buf = buf.slice(at + 1);
      if (msg.id && waiting.has(msg.id)) {
        const {ok, fail} = waiting.get(msg.id);
        waiting.delete(msg.id);
        if (msg.error) fail(new Error(`${msg.error.message} (${msg.error.code})`)); else ok(msg.result || {});
      } else if (msg.method) {
        for (const h of handlers) h(msg);
      }
    }
  });
  const send = (method, params = {}, sessionId) => new Promise((ok, fail) => {
    const m = {id: ++id, method, params};
    if (sessionId) m.sessionId = sessionId;
    waiting.set(m.id, {ok, fail});
    out.write(JSON.stringify(m) + '\0');
  });
  return {send, on: (h) => handlers.push(h)};
}

// The worker's script: the kit, the runtime (which locks the worker), then the model's code in a wrapper that hides
// the names above and hands its draw function over once.
export function workerSource(code, scale) {
  const kit = KIT.map((f) => fs.readFileSync(path.join(HERE, 'kit', f), 'utf8')).join('\n;\n');
  const runtime = fs.readFileSync(path.join(HERE, 'runtime.js'), 'utf8');
  return `'use strict';\nconst BOX_SCALE = ${Number(scale) || 1};\n${kit}\n;\n${runtime}\n;\n` +
    `__setDraw((function (${SHADOWED.join(', ')}) {\n'use strict';\n${code}\n;\nreturn (typeof draw === 'function') ? draw : null;\n})());\n`;
}

// The page: a nonce'd script that makes the worker from the source (kept as JSON data, never run in the page),
// passes the frames on to the box through a binding, and stops the worker if a frame never finishes.
function pageHtml(src, job, nonce) {
  const data = JSON.stringify({src, frames: job.frames, cues: job.cues || {}, quality: job.quality || 0.9,
    limitMs: job.limit_ms || 20, scale: job.scale || 1}).replace(/</g, '\\u003c');
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp(nonce)}">
</head><body>
<script type="application/json" id="job">${data}</script>
<script nonce="${nonce}">
(function () {
  const out = window.__boxOut;
  const job = JSON.parse(document.getElementById('job').textContent);
  const say = (m) => out(JSON.stringify(m));
  let chain = Promise.resolve(), timer = null, over = false;
  const finish = (m) => { if (over) return; over = true; clearTimeout(timer); chain.then(() => say(m)); };
  const worker = new Worker(URL.createObjectURL(new Blob([job.src], {type: 'text/javascript'})));
  const watch = () => { clearTimeout(timer); timer = setTimeout(() => { worker.terminate(); finish({type: 'fatal', error: 'a frame never finished'}); }, ${WATCHDOG_MS}); };
  worker.onerror = (e) => { e.preventDefault(); worker.terminate(); finish({type: 'fatal', error: 'error: ' + e.message + (e.lineno ? ' (line ' + e.lineno + ')' : '')}); };
  worker.onmessage = (e) => {
    const m = e.data || {};
    if (over || typeof m !== 'object') return;
    watch();
    if (m.type === 'frame') {
      const meta = {type: 'frame', i: m.i, ms: m.ms, error: m.error, magenta: m.magenta, change: m.change};
      chain = chain.then(() => new Promise((ok) => {
        const r = new FileReader();
        r.onload = () => { say(Object.assign(meta, {jpeg: String(r.result).split(',')[1]})); ok(); };
        r.onerror = () => { say(Object.assign(meta, {jpeg: null})); ok(); };
        r.readAsDataURL(m.blob);
      }));
    } else if (m.type === 'done' || m.type === 'fatal') {
      worker.terminate();
      finish(m);
    }
  };
  watch();
  worker.postMessage({cmd: 'run', frames: job.frames, cues: job.cues, quality: job.quality, limitMs: job.limitMs});
})();
</script></body></html>`;
}

const csp = (nonce) => `default-src 'none'; script-src 'nonce-${nonce}'; worker-src blob:; img-src 'none'; connect-src 'none'; style-src 'none'; base-uri 'none'; form-action 'none'`;

function launch(exe, sandbox) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'stringer-box-'));
  const child = spawn(exe, chromeArgs(profile, sandbox), {stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe']});
  let stderr = '';
  child.stderr.on('data', (d) => { stderr = (stderr + d).slice(-4000); });
  return {child, profile, stderr: () => stderr};
}

export async function runBox(job, outDir) {
  const exe = browserPath();
  if (!exe) return {status: 'no browser', errors: ['no headless Chrome found (render/anim/box.mjs browserPath)']};
  fs.mkdirSync(outDir, {recursive: true});
  const t0 = Date.now();
  const nonce = crypto.randomBytes(16).toString('base64');
  const html = pageHtml(workerSource(job.code, job.scale || 1), job, nonce);
  const rec = {status: null, frames: 0, ms: [], errors: [], frame_errors: 0, blocked: [], blank_frames: 0, change: [],
    sandbox: true, browser: path.basename(exe)};
  let b = launch(exe, true);
  // where the system can't run Chrome's OS sandbox (some containers), say so and go on without it; every other
  // layer still holds
  const early = await new Promise((ok) => {
    const t = setTimeout(() => ok(null), 1500);
    b.child.once('exit', (c) => { clearTimeout(t); ok(c); });
  });
  if (early !== null) {
    rec.sandbox = false;
    rec.sandbox_error = b.stderr().slice(-300);
    fs.rmSync(b.profile, {recursive: true, force: true});
    b = launch(exe, false);
  }
  const cdp = pipeClient(b.child);
  const limit = setTimeout(() => { rec.errors.push('the box ran out of time'); finish('timeout'); }, (job.timeout_s || 120) * 1000);
  let done;
  const ended = new Promise((ok) => { done = ok; });
  let finished = false;
  function finish(status) {
    if (finished) return;
    finished = true;
    rec.status = rec.status || status;
    done();
  }
  cdp.on(async (msg) => {
    const sid = msg.sessionId;
    try {
      if (msg.method === 'Fetch.requestPaused') {
        const {requestId, request} = msg.params;
        if (request.url === PAGE_URL && !rec.served) {
          rec.served = true;
          await cdp.send('Fetch.fulfillRequest', {requestId, responseCode: 200, responseHeaders: [
            {name: 'Content-Type', value: 'text/html; charset=utf-8'}, {name: 'Content-Security-Policy', value: csp(nonce)},
            {name: 'Cache-Control', value: 'no-store'}], body: Buffer.from(html).toString('base64')}, sid);
        } else {
          rec.blocked.push(String(request.url).slice(0, 120));
          await cdp.send('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'}, sid);
        }
      } else if (msg.method === 'Target.attachedToTarget' && sid) {
        // the worker (or anything else the page starts): block its requests too, then let it run
        const child = msg.params.sessionId;
        await cdp.send('Fetch.enable', {patterns: [{urlPattern: '*'}]}, child).catch(() => {});
        await cdp.send('Runtime.runIfWaitingForDebugger', {}, child).catch(() => {});
      } else if (msg.method === 'Runtime.bindingCalled' && msg.params.name === '__boxOut') {
        const m = JSON.parse(msg.params.payload);
        if (m.type === 'frame') {
          if (m.jpeg) fs.writeFileSync(path.join(outDir, `f${String(m.i).padStart(4, '0')}.jpg`), Buffer.from(m.jpeg, 'base64'));
          rec.frames += 1;
          rec.ms.push(m.ms);
          rec.change.push(m.change);
          if (m.magenta > 0.5) rec.blank_frames += 1;
          if (m.error) { rec.frame_errors += 1; if (rec.errors.length < 5) rec.errors.push(`frame ${m.i}: ${m.error}`); }
        } else if (m.type === 'done') {
          rec.text_calls = m.counts?.text || 0;
          rec.pixel_calls = m.counts?.pixels || 0;
          if (m.stopped) { rec.errors.push(`stopped: ${m.stopped}`); finish('too slow'); } else finish('drawn');
        } else if (m.type === 'fatal') {
          rec.errors.push(m.error);
          finish('failed');
        }
      } else if (msg.method === 'Runtime.exceptionThrown') {
        rec.errors.push('page: ' + String(msg.params.exceptionDetails?.exception?.description || msg.params.exceptionDetails?.text).slice(0, 200));
      }
    } catch (e) {
      rec.errors.push('box: ' + String(e.message).slice(0, 200));
    }
  });
  b.child.on('exit', () => { if (!finished) { rec.errors.push('the browser stopped: ' + b.stderr().slice(-300)); finish('failed'); } });
  try {
    await cdp.send('Fetch.enable', {patterns: [{urlPattern: '*'}]});           // the browser's own requests
    const {targetId} = await cdp.send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await cdp.send('Target.attachToTarget', {targetId, flatten: true});
    await cdp.send('Fetch.enable', {patterns: [{urlPattern: '*'}]}, sessionId);
    await cdp.send('Network.enable', {}, sessionId);
    await cdp.send('Network.setCacheDisabled', {cacheDisabled: true}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Runtime.addBinding', {name: '__boxOut'}, sessionId);
    await cdp.send('Target.setAutoAttach', {autoAttach: true, waitForDebuggerOnStart: true, flatten: true}, sessionId);
    await cdp.send('Page.enable', {}, sessionId);
    // offline emulation would stop the page's own (served-from-memory) load, so it is turned on right after it
    await cdp.send('Page.navigate', {url: PAGE_URL}, sessionId);
    await cdp.send('Network.emulateNetworkConditions', {offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0}, sessionId);
    await ended;
  } catch (e) {
    rec.errors.push('box: ' + String(e.message).slice(0, 200));
    rec.status = rec.status || 'failed';
  } finally {
    clearTimeout(limit);
    try { await Promise.race([cdp.send('Browser.close'), new Promise((ok) => setTimeout(ok, 1500))]); } catch (e) { /* closing anyway */ }
    b.child.kill('SIGKILL');
    fs.rmSync(b.profile, {recursive: true, force: true});
  }
  const ms = rec.ms.slice().sort((x, y) => x - y);
  rec.ms_median = ms.length ? ms[ms.length >> 1] : null;
  rec.ms_p95 = ms.length ? ms[Math.min(ms.length - 1, Math.floor(ms.length * 0.95))] : null;
  rec.ms_max = ms.length ? ms[ms.length - 1] : null;
  rec.seconds = (Date.now() - t0) / 1000;
  rec.wanted = job.frames;
  return rec;
}

async function main() {
  const [jobPath, outDir] = process.argv.slice(2);
  if (!jobPath || !outDir) {
    console.error('usage: node anim/box.mjs <job.json> <out folder>');
    process.exit(2);
  }
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
  const rec = await runBox(job, outDir);
  console.log(JSON.stringify(rec));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => { console.error(e?.stack || String(e)); process.exit(1); });
}
