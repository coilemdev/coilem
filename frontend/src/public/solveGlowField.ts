/**
 * The colours the Mesh view's element edges take while the field is solved.
 *
 * This is an illustration, not a result: a smooth pattern with the look of a
 * flux-density plot (strong where teeth face a pole, strong in the yoke
 * between poles, weak towards the shaft), made from the pole count and the
 * air-gap radius alone. The solved field replaces it in the Field view.
 */
export interface SolveGlowShape {
  /** Radius of the air gap, mm. */
  gapRadiusMm: number;
  /** Largest radius of the model, mm. */
  outerRadiusMm: number;
  polePairs: number;
}

function clampUnit(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** The illustrative field strength (0..1) at a point of the cross-section. */
export function solveGlowValue(xMm: number, yMm: number, shape: SolveGlowShape): number {
  const radius = Math.hypot(xMm, yMm);
  const outer = Math.max(shape.outerRadiusMm, 1e-9);
  const gap = Math.min(Math.max(shape.gapRadiusMm, 1e-9), outer);
  const pole = Math.cos(Math.max(1, shape.polePairs) * Math.atan2(yMm, xMm));
  // Near the gap the flux crosses radially under each pole; away from it the
  // flux turns along the back iron and is strongest between poles.
  const nearGap = Math.exp(-Math.abs(radius - gap) / (0.16 * outer));
  const crossing = Math.abs(pole);
  const turning = Math.sqrt(Math.max(0, 1 - pole * pole));
  const strength = nearGap * (0.3 + 0.7 * crossing) + (1 - nearGap) * (0.18 + 0.62 * turning);
  // Little flux reaches the shaft.
  const towardsShaft = radius < gap ? clampUnit((radius / gap - 0.25) / 0.45) : 1;
  return clampUnit(strength * (0.25 + 0.75 * towardsShaft));
}

/** Which of `binCount` colours a point takes; `level` (0..1) is how far up the scale the pattern reaches. */
export function solveGlowBin(value: number, level: number, binCount: number): number {
  const lifted = clampUnit(value) * (0.5 + 0.5 * clampUnit(level));
  return Math.min(binCount - 1, Math.floor(lifted * binCount));
}
