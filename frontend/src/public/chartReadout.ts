/**
 * Click-to-read values on the result waveform plots (#54). The readout snaps
 * to a solved position and shows its stored samples; it never interpolates.
 */

/** Two stored angles closer than this are the same solved position. */
export const WAVEFORM_READOUT_ANGLE_TOLERANCE_DEG = 1e-6;

export interface WaveformReadoutSeries {
  key: string;
  label: string;
  color: string;
  unit: string;
  angles: readonly number[];
  values: readonly number[];
}

export interface WaveformReadoutValue {
  key: string;
  label: string;
  color: string;
  unit: string;
  /** The stored sample, or null when the series has no solved position at this angle. */
  value: number | null;
}

/** A difference between two series' samples, shown as `minuend − subtrahend`. */
export interface WaveformReadoutDifference {
  minuendKey: string;
  subtrahendKey: string;
  label: string;
}

/** The distinct solved angles of the given series, in increasing order. */
export function waveformReadoutAngles(series: readonly WaveformReadoutSeries[]): number[] {
  const sorted = series
    .flatMap((item) => item.angles)
    .filter(Number.isFinite)
    .sort((left, right) => left - right);
  const distinct: number[] = [];
  for (const angle of sorted) {
    if (distinct.length === 0 || angle - distinct[distinct.length - 1] > WAVEFORM_READOUT_ANGLE_TOLERANCE_DEG) {
      distinct.push(angle);
    }
  }
  return distinct;
}

/** Index of the solved angle nearest to `angleDeg`, or -1 when there is none. */
export function nearestWaveformReadoutIndex(angles: readonly number[], angleDeg: number): number {
  if (angles.length === 0 || !Number.isFinite(angleDeg)) return -1;
  let nearest = 0;
  for (let index = 1; index < angles.length; index += 1) {
    if (Math.abs(angles[index] - angleDeg) < Math.abs(angles[nearest] - angleDeg)) nearest = index;
  }
  return nearest;
}

/** The solved-angle index an arrow, Home or End key selects; null for other keys. */
export function steppedWaveformReadoutIndex(
  current: number | null,
  count: number,
  key: string,
): number | null {
  if (count <= 0) return null;
  const last = count - 1;
  switch (key) {
    case 'ArrowRight':
    case 'ArrowUp':
      return current === null ? 0 : Math.min(last, current + 1);
    case 'ArrowLeft':
    case 'ArrowDown':
      return current === null ? last : Math.max(0, current - 1);
    case 'Home':
      return 0;
    case 'End':
      return last;
    default:
      return null;
  }
}

/** Each series' stored sample at a solved angle, or null where it has no sample there. */
export function waveformReadoutValues(
  series: readonly WaveformReadoutSeries[],
  angleDeg: number,
): WaveformReadoutValue[] {
  return series.map((item) => {
    const index = item.angles.findIndex(
      (angle) => Math.abs(angle - angleDeg) <= WAVEFORM_READOUT_ANGLE_TOLERANCE_DEG,
    );
    const sample = index >= 0 ? item.values[index] : undefined;
    return {
      key: item.key,
      label: item.label,
      color: item.color,
      unit: item.unit,
      value: typeof sample === 'number' && Number.isFinite(sample) ? sample : null,
    };
  });
}

/** `minuend − subtrahend` when both series are shown and solved at this angle. */
export function waveformReadoutDifferenceValue(
  values: readonly WaveformReadoutValue[],
  difference: WaveformReadoutDifference,
): number | null {
  const minuend = values.find((item) => item.key === difference.minuendKey)?.value;
  const subtrahend = values.find((item) => item.key === difference.subtrahendKey)?.value;
  return typeof minuend === 'number' && typeof subtrahend === 'number' ? minuend - subtrahend : null;
}

/** A solved angle at its stored precision: 0°, 3.75°, 352.5°. */
export function formatWaveformReadoutAngle(angleDeg: number): string {
  return `${Number(angleDeg.toFixed(3))}°`;
}

/** The result cards' two-decimal format, for example `12.23 N·m`. */
export function formatWaveformReadoutValue(value: number, unit: string): string {
  return `${value.toFixed(2)} ${unit}`;
}

/** A signed difference in the Compare cards' format, for example `+0.12 N·m`. */
export function formatWaveformReadoutDifference(value: number, unit: string): string {
  const rounded = Number(value.toFixed(2));
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(2)} ${unit}`;
}
