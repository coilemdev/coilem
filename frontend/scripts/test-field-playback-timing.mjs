import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  PUBLIC_FIELD_PLAYBACK_LOOP_CACHE_FRAMES,
  PUBLIC_FIELD_PLAYBACK_MAX_LOADED_FPS,
  advancePlaybackElectricalAngle,
  playbackFrameStride,
  playbackLookaheadFrameIndices,
  playbackStrideFrameIndex,
  publicFieldPlaybackCacheFrames,
} = await importTypeScriptModule(new URL('../src/public/fieldPlaybackTiming.ts', import.meta.url));

const frames = Array.from({ length: 48 }, (_, index) => ({ angle_deg: index * 7.5 }));
const solvedFramesPerSecond = (rpm, polePairs) => (rpm * 6 * polePairs) / 7.5;

// Each stride divides the frame count, and its loop either fits the decoded
// cache or needs no more new frames per second than the loader sustains.
for (const polePairs of [1, 4, 7, 12]) {
  for (const rpm of [1, 5, 8, 18, 30, 60, 100]) {
    const stride = playbackFrameStride(frames.length, 360, rpm, polePairs);
    assert.equal(frames.length % stride, 0, `stride ${stride} divides 48 (${rpm} rpm, ${polePairs} pole pairs)`);
    const loopFrames = frames.length / stride;
    assert.ok(
      loopFrames <= PUBLIC_FIELD_PLAYBACK_LOOP_CACHE_FRAMES
        || solvedFramesPerSecond(rpm, polePairs) / stride <= PUBLIC_FIELD_PLAYBACK_MAX_LOADED_FPS,
      `${rpm} rpm, ${polePairs} pole pairs: stride ${stride} is sustainable`,
    );
    if (stride > 1) {
      // The next-smaller divisor would be neither cached in full nor sustainable.
      const smaller = [...Array(stride - 1).keys()].map((value) => value + 1)
        .filter((value) => frames.length % value === 0)
        .at(-1);
      assert.ok(
        frames.length / smaller > PUBLIC_FIELD_PLAYBACK_LOOP_CACHE_FRAMES
          && solvedFramesPerSecond(rpm, polePairs) / smaller > PUBLIC_FIELD_PLAYBACK_MAX_LOADED_FPS,
        `${rpm} rpm, ${polePairs} pole pairs: stride ${stride} is the smallest that works`,
      );
    }
  }
}
assert.equal(playbackFrameStride(48, 360, 5, 4), 1);
assert.equal(playbackFrameStride(48, 360, 18, 4), 2);
assert.equal(playbackFrameStride(48, 360, 30, 4), 3);
assert.equal(playbackFrameStride(48, 360, 30, 7), 3);
assert.equal(playbackFrameStride(16, 360, 100, 12), 1, 'a 16-frame loop always fits the cache');

// Every frame the playback clock shows was preloaded, in order, whatever the
// display refresh rate. When the display is at least as fast as the stride
// grid, it shows exactly the preloaded frames, so no decode is wasted.
for (const [rpm, polePairs, refreshHz] of [[8, 4, 60], [30, 4, 60], [30, 7, 120], [30, 7, 34], [60, 7, 60]]) {
  const stride = playbackFrameStride(frames.length, 360, rpm, polePairs);
  const lookahead = playbackLookaheadFrameIndices(frames, 0, rpm, polePairs, 10);
  // Run the clock until the last preloaded frame would hand over to the next.
  const horizonDeg = frames[lookahead.at(-1)].angle_deg + (7.5 * stride) / 2;
  const tickDeg = advancePlaybackElectricalAngle(0, 1000 / refreshHz, rpm, polePairs);
  let shown = 0;
  const sequence = [];
  for (let unwrappedDeg = tickDeg; unwrappedDeg < horizonDeg; unwrappedDeg += tickDeg) {
    const index = playbackStrideFrameIndex(frames, unwrappedDeg % 360, 360, stride);
    if (index !== shown) {
      sequence.push(index);
      shown = index;
    }
  }
  const label = `${rpm} rpm, ${polePairs} pole pairs at ${refreshHz} Hz`;
  const positions = sequence.map((index) => lookahead.indexOf(index));
  assert.ok(positions.every((position) => position >= 0), `${label}: every shown frame was preloaded`);
  assert.ok(positions.every((position, i) => i === 0 || position > positions[i - 1]), `${label}: in order`);
  if (refreshHz >= solvedFramesPerSecond(rpm, polePairs) / stride) {
    assert.deepEqual(sequence, lookahead, `${label}: shows exactly the preloaded frames`);
  }
}

// A loop that fits is cached in full; a long one keeps the buffered window.
assert.equal(publicFieldPlaybackCacheFrames(30, 16), 16);
assert.equal(publicFieldPlaybackCacheFrames(30, 8), 11);
assert.equal(publicFieldPlaybackCacheFrames(30, 24), 11);
assert.equal(publicFieldPlaybackCacheFrames(8), 7);

console.log('field playback timing checks passed');
