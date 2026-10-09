export const PUBLIC_FIELD_PLAYBACK_MIN_RPM = 1;
export const PUBLIC_FIELD_PLAYBACK_MAX_RPM = 100;
export const PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM = 18;

/**
 * Solved fields are discrete rasters, so presenting more than one new raster
 * per ordinary display refresh only wastes streaming and rasterization work.
 * The mechanical clock remains truthful above this rate; frame selection
 * deliberately skips intermediate solved angles.
 */
export const PUBLIC_FIELD_PLAYBACK_PRESENTATION_FPS = 60;

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
  const safeRpm = Math.min(
    PUBLIC_FIELD_PLAYBACK_MAX_RPM,
    Math.max(PUBLIC_FIELD_PLAYBACK_MIN_RPM, Number.isFinite(rpm) ? rpm : 0),
  );
  const safePolePairs = Math.max(1, Number.isFinite(polePairs) ? polePairs : 1);
  const electricalDegPerSecond = safeRpm * 6 * safePolePairs;
  return normalizePlaybackElectricalAngle(
    electricalAngleDeg + electricalDegPerSecond * (safeElapsedMs / 1000),
    cycleSpanDeg,
  );
}

/**
 * Predict the solved frames that the presentation clock will actually show.
 *
 * At low RPM this is the contiguous next-frame sequence. At high RPM it is a
 * sparse sequence sampled at the display budget, so lookahead and cache space
 * follow the frames users will see instead of loading angles that are skipped.
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

  const sampleMs = 1000 / PUBLIC_FIELD_PLAYBACK_PRESENTATION_FPS;
  const cycleSpanDeg = playbackCycleSpanDeg(frames);
  const indices: number[] = [];
  let sampleAngleDeg = normalizePlaybackElectricalAngle(
    electricalAngleDeg,
    cycleSpanDeg,
  );
  let previousIndex = nearestPlaybackFrameIndex(
    frames,
    sampleAngleDeg,
    cycleSpanDeg,
  );
  // One RPM with a fine angle grid may need hundreds of display samples
  // before the nearest solved frame changes. Keep the guard generous while
  // still making malformed/duplicate timelines terminate deterministically.
  const maxSamples = Math.max(1200, count * 1200);

  for (let sample = 0; sample < maxSamples && indices.length < count; sample += 1) {
    sampleAngleDeg = advancePlaybackElectricalAngle(
      sampleAngleDeg,
      sampleMs,
      rpm,
      polePairs,
      cycleSpanDeg,
    );
    const nextIndex = nearestPlaybackFrameIndex(
      frames,
      sampleAngleDeg,
      cycleSpanDeg,
    );
    if (nextIndex === previousIndex) continue;
    indices.push(nextIndex);
    previousIndex = nextIndex;
  }

  return indices;
}

export function publicFieldPlaybackBufferFrames(rpm: number): number {
  if (rpm >= 60) return 14;
  if (rpm >= 15) return 10;
  return 6;
}

export function publicFieldPlaybackCacheFrames(rpm: number): number {
  return publicFieldPlaybackBufferFrames(rpm) + 1;
}
