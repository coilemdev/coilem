/**
 * Stator slot geometry that both the config mapper and the schema migration need.
 *
 * This module is deliberately dependency-free: it is shared with the public app
 * (registered in `scripts/test-public-boundary.mjs`), and `projectSchema.ts`
 * imports it so the v2 -> v3 tooth-width shift has exactly one definition
 * instead of a copy in the migration and another in the defaults.
 */

/** The subset of `FrontendParams['statorGeometry']` these helpers read. */
export interface StatorGeometryDefaults {
  outerDiameter: number;
  innerDiameter: number;
  slotCount: number;
  yokeThickness?: number;
  toothWidth?: number;
}

export function defaultYokeThicknessMm(statorGeometry: StatorGeometryDefaults): number {
  // Yoke ~ 45% of radial stator depth, clamped to a reasonable range.
  const radialDepth = (statorGeometry.outerDiameter - statorGeometry.innerDiameter) / 2;
  return Math.max(5, Math.min(40, Math.round(radialDepth * 0.45)));
}

/** Radial depth of the slot: stator radial depth less the yoke behind it. */
export function slotRadialDepthMm(statorGeometry: StatorGeometryDefaults): number {
  const yoke = statorGeometry.yokeThickness ?? defaultYokeThicknessMm(statorGeometry);
  const radialDepth = (statorGeometry.outerDiameter - statorGeometry.innerDiameter) / 2;
  return Math.max(0, radialDepth - yoke);
}

/**
 * How much wider the pitch arc is at the slot body than at the bore.
 *
 * `tooth_width_mm` used to be subtracted from the bore pitch even though the slot
 * body sits at `ID/2 + slot_depth`; schema v3 subtracts it at the body radius so
 * the field equals the tooth at the yoke-side slot body. This difference is what
 * the v2 -> v3 migration adds to a stored value to keep the drawn geometry
 * identical, and what the default below adds to keep the shipped motor identical.
 */
export function toothWidthBodyPitchShiftMm(statorGeometry: StatorGeometryDefaults): number {
  const slots = Number(statorGeometry.slotCount);
  if (!Number.isFinite(slots) || slots <= 0) return 0;
  return ((2 * Math.PI) / slots) * slotRadialDepthMm(statorGeometry);
}

/**
 * Default yoke-side tooth width, in schema v3 terms.
 *
 * The historical default was 45% of the *bore* pitch, which — read the old way —
 * drew a noticeably thicker tooth than the number suggested (14.1 drew 25.6 on
 * the 8p/12s example). Adding the body-pitch shift keeps that drawn tooth exactly,
 * so a design that never set the field explicitly does not change shape when the
 * schema bumps. It is not "45% of pitch" any more, and never really was.
 */
export function defaultToothWidthMm(statorGeometry: StatorGeometryDefaults): number {
  const bore = statorGeometry.innerDiameter;
  const boreToothPitch = (Math.PI * bore) / statorGeometry.slotCount;
  const legacyDefault = Math.round(boreToothPitch * 0.45 * 10) / 10;
  return Number((legacyDefault + toothWidthBodyPitchShiftMm(statorGeometry)).toFixed(4));
}
