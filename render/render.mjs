// Draws a render plan into stills or an MP4 (module 8, step 5).
//
//   node render.mjs video  <plan.json> <run folder> <out.mp4>  [--concurrency 8] [--crf 23]
//                                     [--range 626-943] [--scale 0.5]   (a preview: some frames, smaller)
//   node render.mjs stills <plan.json> <run folder> <out folder> [--frames 10,200|auto]
//   node render.mjs bundle                                     (bundle once, into .bundle/)
//
// <run folder> holds the plan's audio files (narration.mp3, the music bed) and an animated beat's frames (anim/). They and
// the beats' portrait photos (and cutouts) are copied next to the bundle into a folder of this render's own (public/run-<id>/, removed afterwards), so
// two renders at once never touch each other's files. Prints one JSON line at the end.
//
// Bundles live in .bundle/<hash of src and public>/. A bundle is built under a temporary name and renamed
// into place, so a render that is still using an older bundle is never disturbed by a rebundle.
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BUNDLE = path.join(HERE, '.bundle');

// macOS quirk (render test, Nov 24): headless Chrome stalls when its binary sits inside ~/Desktop, so on
// a Mac use the copy in ~/Library/Caches. On Linux / Cloud Run, Remotion's own download is used.
const COPY = path.join(os.homedir(), 'Library/Caches/stringer-render-test/chrome-headless-shell-mac-arm64/chrome-headless-shell');
const browserExecutable = process.platform === 'darwin' && fs.existsSync(COPY) ? COPY : null;

function args(argv) {
  const pos = [], opt = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) opt[argv[i].slice(2)] = argv[++i];
    else pos.push(argv[i]);
  }
  return {pos, opt};
}

// The bundle's name: a hash of every file in src/ (contents) and public/ (names, sizes, times).
function bundleName() {
  const h = crypto.createHash('sha1');
  for (const [dir, deep] of [['src', true], ['public', false]]) {
    const root = path.join(HERE, dir);
    if (!fs.existsSync(root)) continue;
    for (const f of fs.readdirSync(root, {recursive: true}).sort()) {
      const p = path.join(root, f);
      const st = fs.statSync(p);
      if (!st.isFile()) continue;
      h.update(`${dir}/${f}`);
      h.update(deep ? fs.readFileSync(p) : `${st.size}:${st.mtimeMs}`);
    }
  }
  return h.digest('hex').slice(0, 12);
}

const KEEP_BUNDLES = 4;

async function bundled(fresh) {
  fs.mkdirSync(BUNDLE, {recursive: true});
  const dir = path.join(BUNDLE, bundleName());
  if (!fresh && fs.existsSync(path.join(dir, 'index.html'))) return dir;
  const tmp = `${dir}.building-${process.pid}`;
  await bundle({entryPoint: path.join(HERE, 'src', 'index.jsx'), outDir: tmp});
  if (fresh) fs.rmSync(dir, {recursive: true, force: true});
  try {
    fs.renameSync(tmp, dir);
  } catch (e) {
    // another render finished the same bundle first: use theirs
    if (!fs.existsSync(path.join(dir, 'index.html'))) throw e;
    fs.rmSync(tmp, {recursive: true, force: true});
  }
  // keep the newest few bundles; older ones (and anything left from the old single-folder layout) go
  const entries = fs.readdirSync(BUNDLE).map((f) => ({f, p: path.join(BUNDLE, f), st: fs.statSync(path.join(BUNDLE, f))}));
  const bundles = entries.filter((e) => e.st.isDirectory() && /^[0-9a-f]{12}$/.test(e.f)).sort((a, b) => b.st.mtimeMs - a.st.mtimeMs);
  for (const e of bundles.slice(KEEP_BUNDLES)) fs.rmSync(e.p, {recursive: true, force: true});
  for (const e of entries.filter((x) => !/^[0-9a-f]{12}(\.building-\d+)?$/.test(x.f))) fs.rmSync(e.p, {recursive: true, force: true});
  return dir;
}

// This render's own folder next to the bundle: the audio (video only) and the beats' portrait photos.
// Returns the plan as the page should see it (file names in place of paths) and the folder, to remove after.
function stage(serveUrl, plan, runDir, withAudio) {
  const base = `run-${process.pid}-${Date.now().toString(36)}`;
  const dest = path.join(serveUrl, 'public', base);
  fs.mkdirSync(path.join(dest, 'portraits'), {recursive: true});
  const audio = {voice: null, music: null};
  if (withAudio) {
    for (const k of ['voice', 'music']) {
      const f = plan.audio?.[k];
      if (!f) continue;
      const from = path.isAbsolute(f) ? f : path.join(runDir, f);
      if (!fs.existsSync(from)) throw new Error(`audio file missing: ${from}`);
      fs.copyFileSync(from, path.join(dest, path.basename(f)));
      audio[k] = path.basename(f);
    }
  }
  const beats = plan.beats.map((b) => {
    if (b.anim?.dir) {
      // the beat's animation (stringer/animation/): one JPEG per frame, f0000.jpg on, made in the locked box
      const from = path.join(runDir, b.anim.dir);
      const sub = `anim-${b.n}`;
      fs.mkdirSync(path.join(dest, sub), {recursive: true});
      for (let i = 0; i < b.anim.frames; i++) {
        const f = `f${String(i).padStart(4, '0')}.jpg`;
        if (!fs.existsSync(path.join(from, f))) throw new Error(`animation frame missing: ${path.join(from, f)}`);
        fs.copyFileSync(path.join(from, f), path.join(dest, sub, f));
      }
      b = {...b, anim: {...b.anim, src: `${base}/${sub}`}};
    }
    const pt = b.broll?.portrait;
    if (!pt?.file) return b;
    if (!fs.existsSync(pt.file)) throw new Error(`portrait file missing: ${pt.file}`);
    const name = path.basename(pt.file);
    fs.copyFileSync(pt.file, path.join(dest, 'portraits', name));
    const cut = {};
    if (pt.cutout && fs.existsSync(pt.cutout)) {
      const cname = `cut-${path.basename(pt.cutout)}`;
      fs.copyFileSync(pt.cutout, path.join(dest, 'portraits', cname));
      cut.cutoutSrc = `${base}/portraits/${cname}`;
    }
    return {...b, broll: {...b.broll, portrait: {...pt, ...cut, src: `${base}/portraits/${name}`}}};
  });
  return {base, dest, plan: {...plan, beats, audio: {...plan.audio, ...audio}}};
}

// Stills: by default one frame per beat, taken 70% of the way in (marks have played, text is decoded).
const autoFrames = (plan) => plan.beats.map((b) => Math.min(b.end - 1, b.start + Math.round(0.7 * (b.end - b.start))));

async function main() {
  const {pos, opt} = args(process.argv.slice(2));
  const [mode, planPath, runDir, out] = pos;
  if (mode === 'bundle') { console.log(JSON.stringify({bundle: await bundled(true)})); return; }
  if (!['video', 'stills'].includes(mode) || !planPath || !runDir || !out) {
    console.error('usage: node render.mjs video|stills <plan.json> <run folder> <out> [--frames …]');
    process.exit(2);
  }
  const t0 = Date.now();
  const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  const serveUrl = await bundled(false);
  const tBundle = (Date.now() - t0) / 1000;
  const staged = stage(serveUrl, plan, runDir, mode === 'video');
  try {
    await draw(mode, staged.plan, out, opt, serveUrl, staged, t0, tBundle);
  } finally {
    fs.rmSync(staged.dest, {recursive: true, force: true});
  }
}

async function draw(mode, plan, out, opt, serveUrl, staged, t0, tBundle) {
  const inputProps = {plan, audioBase: staged.base};
  const logs = [], layout = [];
  const common = {
    serveUrl, inputProps, browserExecutable, chromiumOptions: {gl: 'swangle'}, timeoutInMilliseconds: 120000,
    onBrowserLog: (l) => {
      if (l.type === 'error') logs.push(l.text);
      else if (l.text.startsWith('LAYOUT ')) layout.push(JSON.parse(l.text.slice(7)));     // eval 7 (src/layout.js)
    },
  };
  const composition = await selectComposition({...common, id: 'Stringer'});
  if (mode === 'stills') {
    fs.mkdirSync(out, {recursive: true});
    const frames = !opt.frames || opt.frames === 'auto' ? autoFrames(plan) : opt.frames.split(',').map(Number);
    const files = [];
    for (const frame of frames) {
      const output = path.join(out, `${opt.prefix || 'frame'}-${String(frame).padStart(5, '0')}.png`);
      await renderStill({...common, composition, frame, output, imageFormat: 'png'});
      files.push(output);
    }
    console.log(JSON.stringify({mode, files, seconds: (Date.now() - t0) / 1000, bundle_seconds: tBundle, browser_errors: logs,
      ...(plan.debug_layout ? {layout} : {})}));
    return;
  }
  fs.mkdirSync(path.dirname(path.resolve(out)), {recursive: true});
  const t1 = Date.now();
  await renderMedia({
    ...common, composition, outputLocation: out, codec: 'h264', audioCodec: 'aac', crf: Number(opt.crf || 23),
    pixelFormat: 'yuv420p', concurrency: Number(opt.concurrency || Math.min(8, os.cpus().length)),
    x264Preset: opt.preset || 'medium', audioBitrate: '160k',
    ...(opt.range ? {frameRange: opt.range.split('-').map(Number)} : {}),
    ...(opt.scale ? {scale: Number(opt.scale)} : {}),
  });
  console.log(JSON.stringify({mode, file: out, frames: plan.frames, seconds: (Date.now() - t0) / 1000,
    render_seconds: (Date.now() - t1) / 1000, bundle_seconds: tBundle, browser_errors: logs}));
}

main().catch((e) => { console.error(e?.stack || String(e)); process.exit(1); });
