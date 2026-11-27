import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Video} from './Video.jsx';
// Made-up plan for Remotion Studio only; real plans come in as inputProps.plan (render.mjs).
import SAMPLE from './sample_plan.json';

// The video is as long as its plan says: the narration sets the timing.
const Root = () => (
  <Composition
    id="Stringer"
    component={Video}
    fps={30}
    width={1080}
    height={1920}
    durationInFrames={SAMPLE.frames}
    defaultProps={{plan: SAMPLE, audioBase: 'run'}}
    calculateMetadata={({props}) => ({durationInFrames: Math.max(1, props.plan.frames), fps: props.plan.fps || 30})}
  />
);

registerRoot(Root);
