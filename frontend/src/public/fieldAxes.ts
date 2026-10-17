/**
 * Field axes for the Stator + PM view (#120): where each field's working
 * (pole-pair) harmonic carries flux outward across the air gap, and the
 * electrical angle by which the stator field leads the magnets.
 */

export interface PolarizedMagnet {
  center: [number, number];
  polarity: 'north' | 'south';
}

/** Mechanical angle (counterclockwise) of one rotor north-pole centre, from the magnets' polarity pattern. */
export function rotorNorthAxisDeg(magnets: readonly PolarizedMagnet[], polePairs: number): number | null {
  let x = 0;
  let y = 0;
  for (const magnet of magnets) {
    const angle = Math.atan2(magnet.center[1], magnet.center[0]) * polePairs;
    const sign = magnet.polarity === 'north' ? 1 : -1;
    x += sign * Math.cos(angle);
    y += sign * Math.sin(angle);
  }
  if (Math.hypot(x, y) < 1e-9) return null;
  return ((Math.atan2(y, x) * 180) / Math.PI / polePairs + 360) % (360 / polePairs);
}

/**
 * Electrical degrees by which the stator axis is ahead of the rotor axis in
 * the direction of rotation, in (-180, 180]. Negative means it lags.
 */
export function statorLeadElecDeg(
  statorAxisDeg: number,
  rotorAxisDeg: number,
  polePairs: number,
  rotation: 'clockwise' | 'counterclockwise',
): number {
  const aheadMechDeg = rotation === 'clockwise'
    ? rotorAxisDeg - statorAxisDeg
    : statorAxisDeg - rotorAxisDeg;
  const wrapped = ((aheadMechDeg * polePairs) % 360 + 360) % 360;
  return wrapped > 180 ? wrapped - 360 : wrapped;
}
