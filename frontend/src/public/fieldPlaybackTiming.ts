export const PUBLIC_FIELD_PLAYBACK_MIN_RPM = 1;
export const PUBLIC_FIELD_PLAYBACK_MAX_RPM = 100;
export const PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM = 18;

/**
 * New solved frames per second that playback can load while it keeps up. Each
 * frame decodes four 1536 px layers; a 10-core Mac sustained about 30 frames/s
 * next to rendering. Faster playback shows every n-th solved frame instead.
 */
export const PUBLIC_FIELD_PLAYBACK_MAX_LOADED_FPS = 30;

/**
 * Longest playback loop held decoded in full (each frame is ~38 MB of
 * bitmaps). A loop this short plays from memory after its first pass.
 */
export const PUBLIC_FIELD_PLAYBACK_LOOP_CACHE_FRAMES = 16;

const FULL_ELECTRICAL_CYCLE_DEG = 360;

export interface PublicFieldPlaybackAngleFrame {
  angle_deg: number;
}

export function playbackCycleSpanDeg(
  frames: readonly PublicFieldPlaybackAngleFrame[],
): number {
  if (frames.length < 2) return FULL_ELECTRICAL_CYCLE_DEG;
  const orderedAngles = frames
    .map((frame) => frame.angle_deg)
    .filter(Number.isFinite)
    .sort((left, right) => left - right);
  if (orderedAngles.length < 2) return FULL_ELECTRICAL_CYCLE_DEG;

  const spacings = orderedAngles
    .slice(1)
    .map((angle, index) => angle - orderedAngles[index])
    .filter((spacing) => spacing > Number.EPSILON)
    .sort((left, right) => left - right);
  if (spacings.length === 0) return FULL_ELECTRICAL_CYCLE_DEG;

  const medianSpacing = spacings[Math.floor(spacings.length / 2)];
  const observedSpan = orderedAngles[orderedAngles.length - 1] - orderedAngles[0];
  return observedSpan + medianSpacing >= FULL_ELECTRICAL_CYCLE_DEG - 0.5
    ? FULL_ELECTRICAL_CYCLE_DEG
    : Math.max(medianSpacing, observedSpan);
}

export function normalizePlaybackElectricalAngle(
  angleDeg: number,
  cycleSpanDeg = FULL_ELECTRICAL_CYCLE_DEG,
): number {
  const safeSpanDeg = Math.max(
    Number.EPSILON,
    Number.isFinite(cycleSpanDeg) ? cycleSpanDeg : FULL_ELECTRICAL_CYCLE_DEG,
  );
  const normalized = angleDeg % safeSpanDeg;
  return normalized < 0 ? normalized + safeSpanDeg : normalized;
}

function periodicAngleDistanceDeg(
  leftDeg: number,
  rightDeg: number,
  cycleSpanDeg: number,
): number {
  const delta = Math.abs(
    normalizePlaybackElectricalAngle(leftDeg, cycleSpanDeg)
      - normalizePlaybackElectricalAngle(rightDeg, cycleSpanDeg),
  );
  return Math.min(delta, cycleSpanDeg - delta);
}

export function nearestPlaybackFrameIndex(
  frames: readonly PublicFieldPlaybackAngleFrame[],
  electricalAngleDeg: number,
  cycleSpanDeg = FULL_ELECTRICAL_CYCLE_DEG,
): number {
  if (frames.length === 0) return 0;
  const targetAngleDeg = normalizePlaybackElectricalAngle(
    electricalAngleDeg,
    cycleSpanDeg,
  );
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  let nearestDirectDistance = Number.POSITIVE_INFINITY;
  frames.forEach((frame, index) => {
    const distance = periodicAngleDistanceDeg(
      frame.angle_deg,
      targetAngleDeg,
      cycleSpanDeg,
    );
    const directDistance = Math.abs(frame.angle_deg - targetAngleDeg);
    if (
      distance < nearestDistance
      || (Math.abs(distance - nearestDistance) < Number.EPSILON
        && directDistance < nearestDirectDistance)
    ) {
      nearestDistance = distance;
      nearestDirectDistance = directDistance;
      nearestIndex = index;
    }
  });
  return nearestIndex;
}

export function advancePlaybackElectricalAngle(
  electricalAngleDeg: number,
  elapsedMs: number,
  rpm: number,
  polePairs: number,
  cycleSpanDeg = FULL_ELECTRICAL_CYCLE_DEG,
): number {
  const safeElapsedMs = Math.max(0, Number.isFinite(elapsedMs) ? elapsedMs : 0);
  return normalizePlaybackElectricalAngle(
    electricalAngleDeg
      + playbackElectricalDegPerSecond(rpm, polePairs) * (safeElapsedMs / 1000),
    cycleSpanDeg,
  );
}

function playbackElectricalDegPerSecond(rpm: number, polePairs: number): number {
  const safeRpm = Math.min(
    PUBLIC_FIELD_PLAYBACK_MAX_RPM,
    Math.max(PUBLIC_FIELD_PLAYBACK_MIN_RPM, Number.isFinite(rpm) ? rpm : 0),
  );
  const safePolePairs = Math.max(1, Number.isFinite(polePairs) ? polePairs : 1);
  return safeRpm * 6 * safePolePairs;
}

/**
 * Playback shows every `stride`-th solved frame. It picks the smallest stride
 * whose loop either fits the decoded cache, so playback runs from memory after
 * one pass, or needs no more new frames per second than the loader sustains.
 * Strides divide the frame count, so every loop shows the same frames.
 */
export function playbackFrameStride(
  frameCount: number,
  cycleSpanDeg: number,
  rpm: number,
  polePairs: number,
): number {
  if (frameCount < 2) return 1;
  const stepDeg = cycleSpanDeg / frameCount;
  const solvedFramesPerSecond = playbackElectricalDegPerSecond(rpm, polePairs) / stepDeg;
  for (let stride = 1; stride < frameCount; stride += 1) {
    if (frameCount % stride !== 0) continue;
    if (
      frameCount / stride <= PUBLIC_FIELD_PLAYBACK_LOOP_CACHE_FRAMES
      || solvedFramesPerSecond / stride <= PUBLIC_FIELD_PLAYBACK_MAX_LOADED_FPS
    ) return stride;
  }
  return frameCount;
}

/** The solved frame on the playback stride grid nearest to an angle. */
export function playbackStrideFrameIndex(
  frames: readonly PublicFieldPlaybackAngleFrame[],
  electricalAngleDeg: number,
  cycleSpanDeg: number,
  stride: number,
): number {
  if (frames.length === 0) return 0;
  const originDeg = frames[0].angle_deg;
  const gridDeg = (cycleSpanDeg / frames.length) * Math.max(1, stride);
  const snappedDeg = originDeg
    + Math.round((electricalAngleDeg - originDeg) / gridDeg) * gridDeg;
  return nearestPlaybackFrameIndex(frames, snappedDeg, cycleSpanDeg);
}

/**
 * The solved frames playback will show next, in order: the following frames
 * on the stride grid. They do not depend on the display's refresh rate, so the
 * preloaded frames are exactly the ones shown.
 */
export function playbackLookaheadFrameIndices(
  frames: readonly PublicFieldPlaybackAngleFrame[],
  electricalAngleDeg: number,
  rpm: number,
  polePairs: number,
  requestedCount: number,
): number[] {
  const count = Math.min(
    Math.max(0, frames.length - 1),
    Math.max(0, Math.floor(requestedCount)),
  );
  if (frames.length < 2 || count === 0) return [];

  const cycleSpanDeg = playbackCycleSpanDeg(frames);
  const stride = playbackFrameStride(frames.length, cycleSpanDeg, rpm, polePairs);
  const gridDeg = (cycleSpanDeg / frames.length) * stride;
  const currentIndex = playbackStrideFrameIndex(
    frames,
    electricalAngleDeg,
    cycleSpanDeg,
    stride,
  );
  const currentAngleDeg = frames[currentIndex].angle_deg;
  const indices: number[] = [];
  for (let step = 1; indices.length < count && step < frames.length; step += 1) {
    const nextIndex = nearestPlaybackFrameIndex(
      frames,
      currentAngleDeg + step * gridDeg,
      cycleSpanDeg,
    );
    // Stop once the loop wraps back to frames already listed.
    if (nextIndex === currentIndex || indices.includes(nextIndex)) break;
    indices.push(nextIndex);
  }
  return indices;
}

export function publicFieldPlaybackBufferFrames(rpm: number): number {
  if (rpm >= 60) return 14;
  if (rpm >= 15) return 10;
  return 6;
}

export function publicFieldPlaybackCacheFrames(rpm: number, loopFrames = 0): number {
  const bufferedFrames = publicFieldPlaybackBufferFrames(rpm) + 1;
  // Hold a short loop in full so it plays from memory after its first pass.
  return loopFrames <= PUBLIC_FIELD_PLAYBACK_LOOP_CACHE_FRAMES
    ? Math.max(bufferedFrames, loopFrames)
    : bufferedFrames;
}

/**
 * Playback rate cap for a solved window (#59): a Preview run solves only part
 * of a cycle, so its positions loop as a sweep. At the RPM-based rate a 45°
 * window would loop about 17 times a second and show scattered positions.
 */
export const PUBLIC_FIELD_PLAYBACK_MAX_WINDOW_FPS = 12;

/** How the position slider and playback cover a run's solved positions. */
export interface PublicFieldPlaybackSpan {
  /** True when the positions cover only part of an electrical cycle (Preview). */
  windowed: boolean;
  startDeg: number;
  endDeg: number;
  stepDeg: number;
}

export function playbackSpanOf(
  frames: readonly PublicFieldPlaybackAngleFrame[],
): PublicFieldPlaybackSpan {
  const angles = frames.map((frame) => frame.angle_deg).filter(Number.isFinite).sort((left, right) => left - right);
  if (angles.length < 2) {
    return { windowed: false, startDeg: angles[0] ?? 0, endDeg: angles[0] ?? 0, stepDeg: FULL_ELECTRICAL_CYCLE_DEG };
  }
  const spacings = angles.slice(1).map((angle, index) => angle - angles[index]).filter((spacing) => spacing > Number.EPSILON);
  const stepDeg = spacings.sort((left, right) => left - right)[Math.floor(spacings.length / 2)] ?? FULL_ELECTRICAL_CYCLE_DEG;
  return {
    windowed: playbackCycleSpanDeg(frames) < FULL_ELECTRICAL_CYCLE_DEG,
    startDeg: angles[0],
    endDeg: angles[angles.length - 1],
    stepDeg,
  };
}

/** The slider covers a solved window once; a full cycle keeps 0–360°. */
export function positionSliderRange(span: PublicFieldPlaybackSpan): { min: number; max: number } {
  return span.windowed
    ? { min: span.startDeg, max: span.endDeg }
    : { min: 0, max: FULL_ELECTRICAL_CYCLE_DEG };
}

/** The slider value that shows a playback angle. */
export function positionSliderValue(span: PublicFieldPlaybackSpan, electricalAngleDeg: number): number {
  return span.windowed
    ? Math.min(span.endDeg, Math.max(span.startDeg, electricalAngleDeg))
    : normalizePlaybackElectricalAngle(electricalAngleDeg);
}

/** The solved position a slider value selects: within a window, without wrapping. */
export function positionSliderFrameIndex(
  frames: readonly PublicFieldPlaybackAngleFrame[],
  valueDeg: number,
  span: PublicFieldPlaybackSpan,
): number {
  if (!span.windowed) return nearestPlaybackFrameIndex(frames, valueDeg, playbackCycleSpanDeg(frames));
  let nearest = 0;
  frames.forEach((frame, index) => {
    if (Math.abs(frame.angle_deg - valueDeg) < Math.abs(frames[nearest].angle_deg - valueDeg)) nearest = index;
  });
  return nearest;
}

/**
 * Advance playback through a solved window and loop back to its start. Each
 * position shows for one step, the last one included, and the rate is capped
 * at PUBLIC_FIELD_PLAYBACK_MAX_WINDOW_FPS positions a second.
 */
export function advanceWindowPlaybackAngle(
  electricalAngleDeg: number,
  elapsedMs: number,
  rpm: number,
  polePairs: number,
  span: PublicFieldPlaybackSpan,
): number {
  const loopDeg = span.endDeg - span.startDeg + span.stepDeg;
  if (!(loopDeg > 0)) return span.startDeg;
  const degPerSecond = Math.min(
    playbackElectricalDegPerSecond(rpm, polePairs),
    span.stepDeg * PUBLIC_FIELD_PLAYBACK_MAX_WINDOW_FPS,
  );
  const safeElapsedMs = Math.max(0, Number.isFinite(elapsedMs) ? elapsedMs : 0);
  const offset = (electricalAngleDeg - span.startDeg + degPerSecond * (safeElapsedMs / 1000)) % loopDeg;
  return span.startDeg + (offset < 0 ? offset + loopDeg : offset);
}

/** The window position a playback angle shows: the last solved angle at or before it. */
export function windowPlaybackFrameIndex(
  frames: readonly PublicFieldPlaybackAngleFrame[],
  electricalAngleDeg: number,
  span: PublicFieldPlaybackSpan,
): number {
  const steps = Math.floor((electricalAngleDeg - span.startDeg) / span.stepDeg + 1e-9);
  return positionSliderFrameIndex(frames, span.startDeg + Math.max(0, steps) * span.stepDeg, span);
}

/** The window positions playback shows next, in order, looping to the start. */
export function windowLookaheadFrameIndices(frameCount: number, currentIndex: number, count: number): number[] {
  const indices: number[] = [];
  for (let step = 1; step <= Math.min(count, frameCount - 1); step += 1) indices.push((currentIndex + step) % frameCount);
  return indices;
}

/**
 * Positions to preload once the slider rests: `ahead` in the direction it was
 * last dragged and `behind` the other way, so the next drag starts on decoded
 * frames either way. A full cycle wraps around; a window stops at its ends.
 */
export function scrubNeighbourIndices(
  frameCount: number,
  currentIndex: number,
  direction: 1 | -1,
  wraps: boolean,
  ahead = 3,
  behind = 2,
): number[] {
  const indices: number[] = [];
  const add = (offset: number) => {
    let index = currentIndex + offset;
    if (wraps) index = ((index % frameCount) + frameCount) % frameCount;
    else if (index < 0 || index >= frameCount) return;
    if (index !== currentIndex && !indices.includes(index)) indices.push(index);
  };
  for (let step = 1; step <= ahead; step += 1) add(direction * step);
  for (let step = 1; step <= behind; step += 1) add(-direction * step);
  return indices;
}
