/**
 * American Wire Gauge sizes for the Winding section's gauge list. The design
 * stores the bare diameter in millimetres; a gauge is a way to pick one.
 */

export const AWG_THICKEST = 8;
export const AWG_THINNEST = 36;
/** A typed diameter this close to a gauge's counts as that gauge: the field keeps two or three decimals. */
const MATCH_TOLERANCE_MM = 0.006;

/** Bare diameter of an AWG size, by the standard's own rule: 0.127 mm at AWG 36, 92 times that 39 sizes thicker. */
export function awgDiameterMm(gauge: number): number {
  return 0.127 * 92 ** ((36 - gauge) / 39);
}

/** The diameter a gauge is stored and shown as. */
export function awgStoredDiameterMm(gauge: number): number {
  return Number(awgDiameterMm(gauge).toFixed(3));
}

export const AWG_SIZES: ReadonlyArray<{ gauge: number; diameterMm: number }> = Array.from(
  { length: AWG_THINNEST - AWG_THICKEST + 1 },
  (_, index) => ({ gauge: AWG_THICKEST + index, diameterMm: awgStoredDiameterMm(AWG_THICKEST + index) }),
);

/** The gauge a diameter is, or null when it is not a standard size. */
export function awgFor(diameterMm: number): number | null {
  const match = AWG_SIZES.find((size) => Math.abs(size.diameterMm - diameterMm) <= MATCH_TOLERANCE_MM);
  return match ? match.gauge : null;
}

/** The thickest gauge no thicker than a diameter, or null when even AWG 36 is thicker. */
export function thickestAwgWithin(diameterMm: number): number | null {
  const fit = AWG_SIZES.find((size) => size.diameterMm <= diameterMm + MATCH_TOLERANCE_MM);
  return fit ? fit.gauge : null;
}

/** Where a diameter sits among the gauges, short enough for a readout: "AWG 18", "AWG 15–16", "> AWG 8". */
export function awgNote(diameterMm: number): string {
  const exact = awgFor(diameterMm);
  if (exact !== null) return `AWG ${exact}`;
  if (diameterMm > AWG_SIZES[0].diameterMm) return `> AWG ${AWG_THICKEST}`;
  if (diameterMm < AWG_SIZES[AWG_SIZES.length - 1].diameterMm) return `< AWG ${AWG_THINNEST}`;
  const thinner = AWG_SIZES.find((size) => size.diameterMm < diameterMm)!.gauge;
  return `AWG ${thinner - 1}–${thinner}`;
}
