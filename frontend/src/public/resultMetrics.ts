/**
 * Derived values for the Results summary (#99 part B): the operating point,
 * electromagnetic power, the torque range and sparkline, and the magnetic
 * loading scale with the stator steel's saturation knee.
 */

import { formatSignificant } from './machineConstants';
import type { MaterialCatalog, SolveResult } from './model';

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

/** How the torque ripple reads: a percentage, or the peak-to-peak swing when a percentage means nothing. */
export interface TorqueRippleView {
  /** Ripple in %, or null when the average torque is too small for one. */
  ripplePct: number | null;
  /** Peak-to-peak torque in N·m when ripplePct is null, else null. */
  peakToPeakNm: number | null;
  /** The peak-to-peak row's name: cogging with no current, a plain swing otherwise. */
  peakToPeakLabel: string;
  /** Why the percentage is left out, for a tooltip; null when it is shown. */
  note: string | null;
}

// Below 1% of the swing the percentage would pass 10,000 % and says nothing.
const RIPPLE_MIN_AVERAGE_FRACTION = 0.01;

/**
 * The solver reports ripple as (max − min) / |average| × 100. With no current
 * the torque is cogging, which averages to zero, so a 16.7 N·m swing over a
 * 0.005 N·m residual read as 330,000 %. Then, and whenever the average is under
 * 1% of the swing, the percentage is left out and the swing shown instead.
 */
export function torqueRippleView(result: Pick<SolveResult, 'summary' | 'torque_waveform' | 'solve_metadata'>): TorqueRippleView {
  const range = torqueRange(result.torque_waveform?.torque_Nm ?? []);
  const peakToPeak = range ? range.max - range.min : null;
  const current = result.solve_metadata?.current_amplitude_A;
  const noLoad = typeof current === 'number' && Number.isFinite(current) && Math.abs(current) < 1e-9;
  const average = result.summary.avg_torque_Nm;
  const averageTooSmall = peakToPeak !== null && peakToPeak > 0 && Number.isFinite(average)
    && Math.abs(average) < RIPPLE_MIN_AVERAGE_FRACTION * peakToPeak;
  if (!noLoad && !averageTooSmall) {
    return { ripplePct: result.summary.torque_ripple_pct, peakToPeakNm: null, peakToPeakLabel: 'Torque p-p', note: null };
  }
  return {
    ripplePct: null,
    peakToPeakNm: peakToPeak,
    peakToPeakLabel: noLoad ? 'Cogging torque p-p' : 'Torque p-p',
    note: noLoad
      ? 'No current, so this torque is cogging: it averages to zero, and ripple as a percentage of the average has no meaning. The peak-to-peak swing is shown instead.'
      : 'The average torque is close to zero, so ripple as a percentage of it has no meaning. The peak-to-peak swing is shown instead.',
  };
}

/** An SVG path through the samples, scaled into width × height with a margin.
 * A shared scale draws several waveforms on one vertical axis. */
export function sparklinePath(
  samples: readonly number[],
  width: number,
  height: number,
  margin = 2,
  scale?: { low: number; high: number },
): string | null {
  const finite = samples.filter((value) => Number.isFinite(value));
  if (finite.length < 2) return null;
  const low = scale?.low ?? Math.min(...finite);
  const span = (scale?.high ?? Math.max(...finite)) - low || 1;
  const step = (width - 2 * margin) / (finite.length - 1);
  return finite
    .map((value, index) => {
      const x = margin + index * step;
      const y = height - margin - ((value - low) / span) * (height - 2 * margin);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
}

/** Sparkline paths for several waveforms on one shared scale, such as the
 * three back-EMF phases, so their relative amplitudes stay true (#110). */
export function sharedSparklinePaths(
  series: readonly (readonly number[])[],
  width: number,
  height: number,
  margin = 2,
): Array<string | null> {
  const finite = series.flatMap((samples) => samples.filter((value) => Number.isFinite(value)));
  if (finite.length < 2) return series.map(() => null);
  const scale = { low: Math.min(...finite), high: Math.max(...finite) };
  return series.map((samples) => sparklinePath(samples, width, height, margin, scale));
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
