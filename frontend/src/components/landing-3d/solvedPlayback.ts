export interface LandingSolvedPlayback {
  displayedMechanicalDeg: number;
  frameA: number;
  frameB: number;
  blend: number;
  rigidSectorDeg: number;
}

/**
 * Map the clockwise Three.js rotor angle onto the solver's increasing
 * mechanical-angle sweep. Field contours and the |B| heatmap must consume the
 * same returned playback state; deriving either layer with another sign makes
 * it counter-rotate relative to the magnets.
 */
export function resolveLandingSolvedPlayback(
  rotorAngleRad: number,
  periodDeg: number,
  stepDeg: number,
  frameCount: number,
): LandingSolvedPlayback {
  const safePeriodDeg = Math.max(Number.EPSILON, periodDeg);
  const safeStepDeg = Math.max(Number.EPSILON, stepDeg);
  const safeFrameCount = Math.max(1, Math.floor(frameCount));
  const displayedMechanicalDeg = -(rotorAngleRad * 180) / Math.PI;
  const wrappedDeg = ((displayedMechanicalDeg % safePeriodDeg) + safePeriodDeg) % safePeriodDeg;
  const rigidSectorDeg = displayedMechanicalDeg - wrappedDeg;
  const framePosition = wrappedDeg / safeStepDeg;
  const frameA = Math.floor(framePosition) % safeFrameCount;

  return {
    displayedMechanicalDeg,
    frameA,
    frameB: (frameA + 1) % safeFrameCount,
    blend: framePosition - Math.floor(framePosition),
    rigidSectorDeg,
  };
}
