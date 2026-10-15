/**
 * Derived values for the Results summary (#99 part B): the operating point,
 * electromagnetic power, the torque range and sparkline, and the magnetic
 * loading scale with the stator steel's saturation knee.
 */

import { formatSignificant } from './machineConstants';
import type { MaterialCatalog } from './model';

/** Electrical frequency in Hz: f = rpm · poles / 120. */
export function electricalFrequencyHz(rpm: number, poleCount: number): number {
  return (rpm * poleCount) / 120;
}

export function formatFrequencyHz(hz: number): string {
  return Number.isInteger(hz) ? String(hz) : hz.toFixed(1);
}

/** Air-gap power before losses, T · ω, as a value and unit (W below 1 kW). */
export function electromagneticPower(avgTorqueNm: number, rpm: number): { text: string; unit: 'W' | 'kW' } | null {
  if (!Number.isFinite(avgTorqueNm) || !Number.isFinite(rpm)) return null;
  const watts = avgTorqueNm * rpm * 2 * Math.PI / 60;
  return Math.abs(watts) >= 1000
    ? { text: formatSignificant(watts / 1000).replace(/^-/, '−'), unit: 'kW' }
    : { text: formatSignificant(watts).replace(/^-/, '−'), unit: 'W' };
}

/** Lowest and highest finite torque sample, or null without two samples. */
export function torqueRange(samples: readonly number[]): { min: number; max: number } | null {
  const finite = samples.filter((value) => Number.isFinite(value));
  return finite.length < 2 ? null : { min: Math.min(...finite), max: Math.max(...finite) };
}

/** An SVG path through the samples, scaled into width × height with a margin. */
export function sparklinePath(samples: readonly number[], width: number, height: number, margin = 2): string | null {
  const finite = samples.filter((value) => Number.isFinite(value));
  if (finite.length < 2) return null;
  const low = Math.min(...finite);
  const span = Math.max(...finite) - low || 1;
  const step = (width - 2 * margin) / (finite.length - 1);
  return finite
    .map((value, index) => {
      const x = margin + index * step;
      const y = height - margin - ((value - low) / span) * (height - 2 * margin);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
}

/** The flux-density scale's top: 2 T, or the next 0.5 T above a higher peak. */
export function loadingScaleMaxT(peaks: readonly number[]): number {
  const highest = Math.max(0, ...peaks.filter((value) => Number.isFinite(value)));
  return Math.max(2, Math.ceil(highest * 2) / 2);
}

/** The saturation knee range a steel's model declares, or null (custom steels declare none). */
export function saturationKneeRangeT(catalog: MaterialCatalog, steelId: string): [number, number] | null {
  const value = catalog.models?.[steelId]?.properties?.saturation_knee_range_T;
  return Array.isArray(value)
    && value.length === 2
    && value.every((entry) => typeof entry === 'number' && Number.isFinite(entry))
    && value[0] < value[1]
    ? [value[0], value[1]]
    : null;
}
