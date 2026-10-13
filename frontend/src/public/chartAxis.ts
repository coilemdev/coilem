/** Steps for electrical-angle axis labels, smallest first. */
const ELECTRICAL_ANGLE_TICK_STEPS_DEG = [1, 2, 2.5, 3.75, 5, 7.5, 10, 15, 22.5, 30, 45, 60, 90, 180];

/**
 * Labelled angles for an electrical-angle axis: multiples of the smallest step
 * that leaves at most `maxIntervals` intervals, so a full 0–360° cycle is
 * labelled every 45° and a 45° or 60° Preview window every 7.5°.
 */
export function electricalAngleTicks(minDeg: number, maxDeg: number, maxIntervals = 8): number[] {
  const span = maxDeg - minDeg;
  if (!Number.isFinite(span) || span <= 0) return Number.isFinite(minDeg) ? [minDeg] : [];
  const step = ELECTRICAL_ANGLE_TICK_STEPS_DEG.find((candidate) => span / candidate <= maxIntervals + 1e-9)
    ?? span / maxIntervals;
  const ticks: number[] = [];
  for (let index = Math.ceil(minDeg / step - 1e-9); index * step <= maxDeg + 1e-9; index += 1) {
    ticks.push(Number((index * step).toFixed(6)));
  }
  return ticks;
}

/** An axis angle label: 0°, 7.5°, 45°. */
export function formatElectricalAngleTick(angleDeg: number): string {
  return `${Number(angleDeg.toFixed(2))}°`;
}
