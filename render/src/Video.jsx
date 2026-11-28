// The whole video from one render plan (stringer/video/plan.py, version plan-1): one canvas per beat,
// the captions on top, the narration and the music bed underneath.
import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {AbsoluteFill, Audio, Sequence, continueRender, delayRender, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {K, L, PAL, PX_H, PX_W, SANS, fontsLoaded, paperLayer, smallCaps} from './style.js';
import {aiMark, drawHeadline, drawHook, drawSides, drawSources, illustrationTag} from './cards.js';
import {drawMap} from './mapshots.js';
import {drawBroll} from './props.js';
import {loadPortrait} from './portraits.js';
import {finishedLayout} from './placement.js';
import {layoutProbe} from './layout.js';
import {animFrameSrc, drawAnim, loadAnimFrame} from './anim.js';
import {drawBigNumber, drawClaims, drawDocument, drawQuote, drawTally, drawTimeline} from './datashots.js';
import {Moving} from './transitions.js';

function drawNotYet(ctx, s) {
  ctx.drawImage(paperLayer(), 0, 0);
  ctx.save();
  ctx.scale(K, K);
  smallCaps(ctx, `${s.beat.shot} · not drawn yet`, L.left, L.content + 20, {size: 9, color: PAL.inkSoft});
  aiMark(ctx, false);
  ctx.restore();
}

export const SHOTS = {
  hook: drawHook,
  headline: drawHeadline,
  sides: drawSides,
  sources: drawSources,
  map_locate: drawMap,
  map_link: drawMap,
  map_spread: drawMap,
  big_number: drawBigNumber,
  timeline: drawTimeline,
  quote: drawQuote,
  claim_vs_claim: drawClaims,
  document: drawDocument,
  tally: drawTally,
};

// One canvas for one beat. The first frame waits (delayRender) until the fonts and the beat's portrait are ready.
// With transitions (transitions.js) a beat's canvas is up a little before its first frame (`lead` frames, showing that
// first frame) and after its last (showing the last), while the change between two beats plays.
function Shot({beat, plan, from, lead = 0}) {
  const frame = Math.min(Math.max(0, useCurrentFrame() - lead), Math.max(0, beat.end - beat.start - 1));
  const ref = useRef(null);
  const [handle] = useState(() => delayRender(`beat ${beat.n}`));
  const released = useRef(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const src = beat.broll?.portrait?.src;
    // a portrait that fails to load is left out (drawBroll finds no image), never a stalled render
    const photo = src ? loadPortrait(staticFile(src)).catch(() => null) : null;
    const cut = beat.broll?.portrait?.cutoutSrc ? loadPortrait(staticFile(beat.broll.portrait.cutoutSrc)).catch(() => null) : null;
    Promise.all([fontsLoaded, photo, cut]).then(() => setReady(true));
  }, [beat]);
  useLayoutEffect(() => {
    if (!ready || !ref.current) return;
    const paint = (animImg) => {
      const ctx = ref.current.getContext('2d', {willReadFrequently: true});
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, PX_W, PX_H);
      // a beat with an animation (anim.js) draws its words compactly at the top and the window below them
      const st = {beat, t: frame, frame: from + frame, plan, compact: !!beat.anim};
      // a cutout portrait needs to know where the finished beat's words will be (placement.js)
      if (beat.broll?.portrait?.cutoutSrc) {
        st.finished = finishedLayout(beat, plan, SHOTS[beat.shot] || drawNotYet, (c) => {
          if (beat.illustration) { c.save(); c.scale(K, K); illustrationTag(c, true); c.restore(); }
        });
      }
      const probe = plan.debug_layout ? layoutProbe(ctx) : null;      // eval 7 only (layout.js)
      (SHOTS[beat.shot] || drawNotYet)(ctx, st);
      if (beat.anim) drawAnim(ctx, st, animImg);
      drawBroll(ctx, st);
      if (probe) probe.report(beat, from + frame, st);
    };
    const release = () => {
      if (!released.current) {
        released.current = true;
        continueRender(handle);
      }
    };
    if (!beat.anim) {
      paint(null);
      release();
      return;
    }
    // the animation's frame for this video frame is an image file: wait for it
    const wait = delayRender(`beat ${beat.n} animation frame ${frame}`);
    let live = true;
    loadAnimFrame(animFrameSrc(beat, frame)).then((img) => {
      if (live && ref.current) paint(img);
      release();
      continueRender(wait);
    });
    return () => { live = false; };
  }, [frame, ready, beat, plan, from, handle]);
  return <canvas ref={ref} width={PX_W} height={PX_H} style={{position: 'absolute', width: '100%', height: '100%'}} />;
}

// Word-by-word captions: chunks of up to 4 words that never cross a cut, with the spoken word lit.
function Captions({captions}) {
  const frame = useCurrentFrame();
  const chunk = captions.find((c) => c.start <= frame && frame < c.end);
  if (!chunk) return null;
  let lit = -1;
  chunk.words.forEach((w, i) => { if (w.start <= frame) lit = i; });
  return (
    <div style={{
      position: 'absolute', top: L.captionTop * K, left: L.left * K, width: (L.right - L.left) * K,
      display: 'flex', justifyContent: 'center',
    }}>
      <div style={{
        background: 'rgba(243,238,225,0.94)', borderRadius: 18, padding: '12px 26px',
        fontFamily: SANS, fontWeight: 600, fontSize: 50, color: PAL.ink, lineHeight: 1.18, textAlign: 'center',
      }}>
        {chunk.words.map((w, i) => (
          <span key={i} style={{color: i === lit ? PAL.vermilion : PAL.ink}}>{w.w}{i < chunk.words.length - 1 ? ' ' : ''}</span>
        ))}
      </div>
    </div>
  );
}

const fromDb = (db) => Math.pow(10, db / 20);

export const Video = ({plan, audioBase = 'run'}) => {
  const music = plan.audio?.music;
  const gain = fromDb(plan.audio?.music_db ?? -20);
  // with transitions on, a beat stays up while the next one comes in, and the beats share a layer of their own
  // (so a sheet on top during a change is still under the captions)
  const moving = plan.beats.some((b) => b.enter);
  const pre = (b) => (b?.enter ? b.enter.pre || 0 : 0);
  const beats = plan.beats.map((beat, i) => {
    const next = plan.beats[i + 1];
    const lead = pre(beat);                                           // up before its first frame
    const hold = next?.enter ? next.enter.frames - pre(next) : 0;     // up after its last
    return (
      <Sequence key={beat.n} from={beat.start - lead} durationInFrames={Math.max(1, beat.end - beat.start + lead + hold)}>
        <Moving beat={beat} next={next} lead={lead} width={plan.width} height={plan.height}>
          <Shot beat={beat} plan={plan} from={beat.start} lead={lead} />
        </Moving>
      </Sequence>
    );
  });
  return (
    <AbsoluteFill style={{backgroundColor: PAL.paper}}>
      {moving ? <AbsoluteFill style={{isolation: 'isolate'}}>{beats}</AbsoluteFill> : beats}
      <Captions captions={plan.captions || []} />
      {plan.audio?.voice ? <Audio src={staticFile(`${audioBase}/${plan.audio.voice}`)} /> : null}
      {music ? (
        <Audio src={staticFile(`${audioBase}/${music}`)} loop
          volume={(f) => gain * interpolate(f, [0, 30, plan.frames - 45, plan.frames], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})} />
      ) : null}
    </AbsoluteFill>
  );
};
