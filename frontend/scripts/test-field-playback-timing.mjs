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

// #59: a Preview run solves only a window of the cycle.
const {
  PUBLIC_FIELD_PLAYBACK_MAX_WINDOW_FPS,
  advanceWindowPlaybackAngle,
  playbackSpanOf,
  positionSliderFrameIndex,
  positionSliderRange,
  positionSliderValue,
  scrubNeighbourIndices,
  windowLookaheadFrameIndices,
  windowPlaybackFrameIndex,
} = await importTypeScriptModule(new URL('../src/public/fieldPlaybackTiming.ts', import.meta.url));

const ipmPreview = Array.from({ length: 13 }, (_, index) => ({ angle_deg: index * 3.75 }));
const spmPreview = Array.from({ length: 17 }, (_, index) => ({ angle_deg: index * 3.75 }));
const windowSpan = playbackSpanOf(ipmPreview);
assert.deepEqual(windowSpan, { windowed: true, startDeg: 0, endDeg: 45, stepDeg: 3.75 });
assert.equal(playbackSpanOf(frames).windowed, false, 'a 48-position run covers the full cycle');
assert.deepEqual(positionSliderRange(windowSpan), { min: 0, max: 45 }, 'the slider covers the 45° window once');
assert.deepEqual(positionSliderRange(playbackSpanOf(frames)), { min: 0, max: 360 }, 'a full cycle keeps 0–360°');

// Dragging the slider across a window visits every position once, in order,
// and reaches the last one. It never jumps back to the first.
const visited = [];
for (let value = 0; value <= 45; value += 0.5) {
  const index = positionSliderFrameIndex(ipmPreview, value, windowSpan);
  if (index !== visited.at(-1)) visited.push(index);
}
assert.deepEqual(visited, [...Array(13).keys()], 'positions 1–13 in order, no wrap');
assert.equal(positionSliderFrameIndex(spmPreview, 60, playbackSpanOf(spmPreview)), 16, 'the last of 17 positions is reachable');
assert.equal(positionSliderValue(windowSpan, 47), 45, 'a playback angle past the last position stays at the slider end');
assert.equal(positionSliderValue(playbackSpanOf(frames), 370), 10, 'a full cycle wraps the slider');
// Full-cycle runs map the slider as before, wrapping 360° to the first position.
assert.equal(positionSliderFrameIndex(frames, 359, playbackSpanOf(frames)), 0);
assert.equal(positionSliderFrameIndex(frames, 181, playbackSpanOf(frames)), 24);

// Playing a window shows every position in order, each once per loop, then
// loops, at no more than the window frame rate, whatever the RPM.
for (const [rpm, polePairs] of [[18, 7], [100, 7], [1, 4], [18, 4]]) {
  const span = polePairs === 7 ? windowSpan : playbackSpanOf(spmPreview);
  const windowFrames = polePairs === 7 ? ipmPreview : spmPreview;
  let angle = span.startDeg;
  const shown = [windowPlaybackFrameIndex(windowFrames, angle, span)];
  let elapsedMs = 0;
  while (shown.length < windowFrames.length * 2 + 1) {
    angle = advanceWindowPlaybackAngle(angle, 1000 / 60, rpm, polePairs, span);
    elapsedMs += 1000 / 60;
    const index = windowPlaybackFrameIndex(windowFrames, angle, span);
    if (index !== shown.at(-1)) shown.push(index);
  }
  const expected = [...[...Array(windowFrames.length).keys()], ...[...Array(windowFrames.length).keys()], 0];
  assert.deepEqual(shown, expected, `${rpm} rpm, ${polePairs} pole pairs: every position in order, then a loop`);
  const positionsPerSecond = (shown.length - 1) / (elapsedMs / 1000);
  assert.ok(positionsPerSecond <= PUBLIC_FIELD_PLAYBACK_MAX_WINDOW_FPS + 1, `${rpm} rpm: ${positionsPerSecond.toFixed(1)} positions/s is capped`);
}
assert.deepEqual(windowLookaheadFrameIndices(13, 11, 4), [12, 0, 1, 2], 'the window lookahead loops to the start');

// Resting slider: three ahead in the drag direction, two behind; windows stop at their ends.
assert.deepEqual(scrubNeighbourIndices(48, 10, 1, true), [11, 12, 13, 9, 8]);
assert.deepEqual(scrubNeighbourIndices(48, 10, -1, true), [9, 8, 7, 11, 12]);
assert.deepEqual(scrubNeighbourIndices(48, 0, -1, true), [47, 46, 45, 1, 2], 'a full cycle wraps');
assert.deepEqual(scrubNeighbourIndices(13, 12, 1, false), [11, 10], 'a window stops at its last position');
assert.deepEqual(scrubNeighbourIndices(13, 0, -1, false), [1, 2]);

// #59: only the newest slider position loads; superseded requests resolve null.
const { LatestFrameLoader } = await importTypeScriptModule(new URL('../src/public/latestFrameLoader.ts', import.meta.url));
const deferred = () => { const started = []; const finish = new Map(); return { started, finish, load: (name) => () => new Promise((resolve) => { started.push(name); finish.set(name, resolve); }) }; };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
{
  // Two loads run at once; requests made meanwhile replace each other.
  const loader = new LatestFrameLoader();
  const { started, finish, load } = deferred();
  const first = loader.request(load('p1'));
  const second = loader.request(load('p2'));
  const passed = [3, 4, 5].map((position) => loader.request(load(`p${position}`)));
  assert.deepEqual(started, ['p1', 'p2'], 'two loads at a time');
  assert.deepEqual(await Promise.all(passed.slice(0, 2)), [null, null], 'positions the slider passed are dropped');
  finish.get('p1')('frame 1');
  assert.equal(await first, 'frame 1');
  await tick();
  assert.deepEqual(started, ['p1', 'p2', 'p5'], 'the newest position starts when a load finishes; p3 and p4 never load');
  finish.get('p2')('frame 2');
  finish.get('p5')('frame 5');
  assert.deepEqual([await second, await passed[2]], ['frame 2', 'frame 5']);
}
{
  // One at a time, if asked.
  const loader = new LatestFrameLoader(1);
  const { started, finish, load } = deferred();
  loader.request(load('a'));
  loader.request(load('b'));
  const newest = loader.request(load('c'));
  assert.deepEqual(started, ['a']);
  finish.get('a')('A');
  await tick();
  assert.deepEqual(started, ['a', 'c']);
  finish.get('c')('C');
  assert.equal(await newest, 'C');
}
{
  const loader = new LatestFrameLoader();
  const failing = loader.request(() => Promise.reject(new Error('HTTP 500')));
  await assert.rejects(failing, /HTTP 500/, 'a failed load reports its error');
  assert.equal(await loader.request(() => Promise.resolve('recovered')), 'recovered', 'the loader keeps working after a failure');
  const { load } = deferred();
  loader.request(load('x'));
  loader.request(load('y'));
  const waiting = loader.request(load('z'));
  loader.clear();
  assert.equal(await waiting, null, 'clear() drops the waiting request');
}

console.log('field playback timing checks passed');
