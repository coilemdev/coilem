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

// Field-axis arrow heads: a chevron a quarter of the shaft long, about 23
// degrees either side of it, so the head keeps one fine shape on the rotor
// and on the larger stator ring.
const FIELD_AXIS_HEAD_LENGTH = 0.24;
const FIELD_AXIS_HEAD_HALF_WIDTH = 0.42;

export interface FieldAxisArrowPaths {
  /** Tail to tip; drawn dashed. */
  shaft: string;
  /** The solid chevron at the tip. */
  head: string;
}

/**
 * SVG paths of one radial field-axis arrow from `fromRadius` to `toRadius` at
 * `angleDeg` (mechanical, counterclockwise), in screen space, y down.
 */
export function fieldAxisArrowPaths(fromRadius: number, toRadius: number, angleDeg: number): FieldAxisArrowPaths {
  const angleRad = (angleDeg * Math.PI) / 180;
  const ux = Math.cos(angleRad);
  const uy = -Math.sin(angleRad);
  const head = (toRadius - fromRadius) * FIELD_AXIS_HEAD_LENGTH;
  const halfWidth = head * FIELD_AXIS_HEAD_HALF_WIDTH;
  const baseX = (toRadius - head) * ux;
  const baseY = (toRadius - head) * uy;
  // (-uy, ux) is the shaft direction turned a quarter turn.
  const sideX = -uy * halfWidth;
  const sideY = ux * halfWidth;
  return {
    shaft: `M ${fromRadius * ux} ${fromRadius * uy} L ${toRadius * ux} ${toRadius * uy}`,
    head: `M ${baseX + sideX} ${baseY + sideY} L ${toRadius * ux} ${toRadius * uy} L ${baseX - sideX} ${baseY - sideY}`,
  };
}

function formatDegrees(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/**
 * The "?" tooltip on the lead-angle label. On a multi-pole motor the two centre
 * lines sit only lead / polePairs mechanical degrees apart, so 90 deg elec does
 * not look like a right angle; this says why, and what the angle means.
 */
export function leadAngleExplanation(leadElecDeg: number, polePairs: number): string {
  const elec = Math.round(Math.abs(leadElecDeg));
  const meaning = 'Electrical degrees measure position within one N–S pole pair: at 90° elec the stator field sits '
    + 'halfway between magnet poles, where the magnet torque per amp is largest.';
  const lag = leadElecDeg < 0 ? ' Here the stator field is behind the magnets, so it holds them back.' : '';
  const dq = ' The magnets\' axis is the d-axis and the q-axis is 90° elec ahead of it. The stator field sits at 90° + γ: '
    + 'on the q-axis at a current angle γ of 0°, and turned further toward field weakening as γ grows. The drawn stator '
    + 'axis is measured from the air-gap field at this rotor position, so with slots it steps a few degrees either side '
    + 'of 90° + γ as the rotor turns.';
  if (polePairs <= 1) {
    return `On a 2-pole motor one turn is 360° elec, so the two lines are ${elec}° apart. ${meaning}${lag}${dq}`;
  }
  const mech = formatDegrees(elec / polePairs);
  const pitch = formatDegrees(360 / polePairs);
  const product = Math.abs(Number(mech) * polePairs - elec) < 1e-9 ? '=' : '≈';
  return `Why ${elec}° elec when the lines are only ${mech}° apart? With ${polePairs} pole pairs the field pattern `
    + `repeats every ${pitch}° around the motor, so 360° elec is ${pitch}° of rotation and `
    + `${mech}° × ${polePairs} ${product} ${elec}° elec. ${meaning}${lag}${dq}`;
}

/** Mechanical degrees from the d-axis to the q-axis: 90° elec ahead in the direction of rotation. */
export function qAxisOffsetDeg(polePairs: number, rotation: 'clockwise' | 'counterclockwise'): number {
  return ((rotation === 'clockwise' ? -1 : 1) * 90) / Math.max(1, polePairs);
}

/**
 * The second line under the lead angle: the run's current angle γ, which the
 * stator field leads the d-axis by on top of 90°. None without one (six-step).
 */
export function currentAngleNote(currentAngleDeg: number | null | undefined): string | null {
  if (typeof currentAngleDeg !== 'number' || !Number.isFinite(currentAngleDeg)) return null;
  const gamma = Math.round(currentAngleDeg);
  return `90° + γ, γ = ${gamma < 0 ? '−' : ''}${Math.abs(gamma)}° set`;
}
