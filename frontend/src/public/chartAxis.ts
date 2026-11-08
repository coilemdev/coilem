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

/** A value axis with round-number ticks that span the data. */
export interface ValueAxis {
  min: number;
  max: number;
  ticks: number[];
  /** Decimals that keep every tick label distinct: 0.0025 needs 4, 0.5 needs 1. */
  decimals: number;
}

const VALUE_TICK_MANTISSAS = [1, 2, 2.5, 5];

/**
 * Round-number ticks (1, 2, 2.5 or 5 times a power of ten) covering
 * `dataMin`…`dataMax`: the finest step that needs at most `maxIntervals`
 * intervals, with a little headroom so the trace does not sit on the frame.
 * A flat trace gets a band around it.
 */
export function valueAxis(dataMin: number, dataMax: number, maxIntervals = 6): ValueAxis {
  let low = Math.min(dataMin, dataMax);
  let high = Math.max(dataMin, dataMax);
  if (!Number.isFinite(low) || !Number.isFinite(high)) {
    low = 0;
    high = 1;
  }
  const scale = Math.max(Math.abs(low), Math.abs(high));
  if (high - low <= scale * 1e-9) {
    const band = scale > 0 ? scale * 0.1 : 1;
    low -= band;
    high += band;
  } else {
    const headroom = (high - low) * 0.05;
    low -= headroom;
    high += headroom;
  }
  const smallest = 10 ** Math.floor(Math.log10((high - low) / maxIntervals));
  let step = smallest;
  let mantissa = 1;
  search: for (let magnitude = smallest; ; magnitude *= 10) {
    for (const candidate of VALUE_TICK_MANTISSAS) {
      const intervals = Math.ceil(high / (candidate * magnitude) - 1e-9) - Math.floor(low / (candidate * magnitude) + 1e-9);
      if (intervals <= maxIntervals) {
        step = candidate * magnitude;
        mantissa = candidate;
        break search;
      }
    }
  }
  const first = Math.floor(low / step + 1e-9);
  const last = Math.ceil(high / step - 1e-9);
  const decimals = Math.max(0, -Math.floor(Math.log10(step) + 1e-9) + (mantissa === 2.5 ? 1 : 0));
  const ticks: number[] = [];
  for (let index = first; index <= last; index += 1) ticks.push(Number((index * step).toFixed(decimals + 2)));
  return { min: first * step, max: last * step, ticks, decimals };
}

/** A value tick label at the axis's own precision, never "-0.00". */
export function formatValueTick(value: number, decimals: number): string {
  const text = value.toFixed(decimals);
  return Number(text) === 0 ? (0).toFixed(decimals) : text;
}

/**
 * Small readings in milli-units, so a few mN·m of cogging reads as 3.2 mN·m
 * rather than 0.00 N·m. Larger readings keep their unit.
 */
export function displayUnitScale(unit: string, maxAbs: number): { unit: string; factor: number } {
  if (Number.isFinite(maxAbs) && maxAbs > 0 && maxAbs < 0.1 && ['N·m', 'V', 'A', 'Wb'].includes(unit)) {
    return { unit: `m${unit}`, factor: 1000 };
  }
  return { unit, factor: 1 };
}
