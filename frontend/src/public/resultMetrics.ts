/**
 * Derived values for the Results summary (#99 part B): the operating point,
 * electromagnetic power, the torque range and sparkline, and the magnetic
 * loading scale with the stator steel's saturation knee.
 */

import { formatSignificant } from './machineConstants';
import type { MaterialCatalog, MotorConfig, SolveResult } from './model';

/** Actual field current; native sinusoidal metadata is in peak A. */
export function solvedPhaseCurrent(config: MotorConfig, result: SolveResult): number {
  const actual = result.solve_metadata.current_amplitude_A;
  if (typeof actual !== 'number' || !Number.isFinite(actual)) return config.solve_params.current_amplitude_A;
  return config.solve_params.current_amplitude_convention === 'rms' && result.solve_metadata.current_amplitude_convention !== 'rms'
    ? actual / Math.SQRT2 : actual;
}

/** Electrical frequency in Hz: f = rpm · poles / 120. */
export function electricalFrequencyHz(rpm: number, poleCount: number): number {
  return (rpm * poleCount) / 120;
}

export function formatFrequencyHz(hz: number): string {
  return Number.isInteger(hz) ? String(hz) : hz.toFixed(1);
}

/** Air-gap power before losses, T · ω, as a value and unit (W below 1 kW). */
export function electromagneticPower(avgTorqueNm: number | null, rpm: number): { text: string; unit: 'W' | 'kW' } | null {
  if (typeof avgTorqueNm !== 'number' || !Number.isFinite(avgTorqueNm) || !Number.isFinite(rpm)) return null;
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

/** One row of the Back EMF readings, in volts at the run's speed. */
export interface BackEmfReading {
  label: 'Phase' | 'Line (wye)';
  /** The fundamental's rms, the headline's convention. */
  rmsV: number;
  /** The solved waveform's largest magnitude; null without a whole electrical cycle. */
  peakV: number | null;
  /** The solved waveform's max − min; null without a whole electrical cycle. */
  peakToPeakV: number | null;
}

// A Preview run solves only part of a cycle, which can miss the peak.
function coversElectricalCycle(anglesDeg: readonly number[]): boolean {
  const angles = anglesDeg.filter(Number.isFinite).sort((left, right) => left - right);
  if (angles.length < 3) return false;
  const steps = angles.slice(1).map((angle, index) => angle - angles[index]).sort((left, right) => left - right);
  return angles[angles.length - 1] - angles[0] + steps[Math.floor(steps.length / 2)] >= 359.5;
}

function waveformExtremes(samples: readonly number[]): { peak: number; peakToPeak: number } | null {
  const finite = samples.filter(Number.isFinite);
  if (finite.length < 3) return null;
  const max = Math.max(...finite);
  const min = Math.min(...finite);
  return { peak: Math.max(max, -min), peakToPeak: max - min };
}

/**
 * The Back EMF card's readings: phase (line-to-neutral) and line-to-line, each as
 * the fundamental's rms and the solved waveform's peak and peak-to-peak. Papers and
 * datasheets often quote a peak and a scope reads peak-to-peak, and with harmonics
 * the peak is not √2 × rms. The line voltage is phase A − B, the terminal voltage of
 * a wye connection; its fundamental is √3 times the phase's.
 */
export function backEmfReadings(
  waveform: SolveResult['back_emf_waveform'],
  phaseFundamentalRmsV: number | null,
): BackEmfReading[] | null {
  if (typeof phaseFundamentalRmsV !== 'number' || !Number.isFinite(phaseFundamentalRmsV)) return null;
  const angles = waveform.electrical_angle_deg;
  const line = waveform.line_ab_V?.length
    ? waveform.line_ab_V
    : waveform.phase_a_V.map((value, index) => value - (waveform.phase_b_V[index] ?? Number.NaN));
  const row = (label: BackEmfReading['label'], rmsV: number, samples: readonly number[]): BackEmfReading => ({
    label,
    rmsV,
    peakV: waveformMeasure(angles, samples, 'peak'),
    peakToPeakV: waveformMeasure(angles, samples, 'pk-pk'),
  });
  return [row('Phase', phaseFundamentalRmsV, waveform.phase_a_V), row('Line (wye)', Math.sqrt(3) * phaseFundamentalRmsV, line)];
}

/** How a waveform's size is read: the fundamental's rms, the peak, or the peak-to-peak swing. */
export type WaveformMeasure = 'rms' | 'peak' | 'pk-pk';

/**
 * A solved waveform's fundamental rms, peak or peak-to-peak, or null without a whole
 * electrical cycle of samples (a Preview window). The rms is the fundamental's, the
 * convention of the Back EMF headline; peak and peak-to-peak include the harmonics.
 */
export function waveformMeasure(anglesDeg: readonly number[], values: readonly number[], measure: WaveformMeasure): number | null {
  if (values.length !== anglesDeg.length || !coversElectricalCycle(anglesDeg)) return null;
  if (measure === 'rms') {
    let cosine = 0;
    let sine = 0;
    let count = 0;
    anglesDeg.forEach((angle, index) => {
      const value = values[index];
      if (!Number.isFinite(angle) || !Number.isFinite(value)) return;
      cosine += value * Math.cos((angle * Math.PI) / 180);
      sine += value * Math.sin((angle * Math.PI) / 180);
      count += 1;
    });
    return count < 3 ? null : ((2 / count) * Math.hypot(cosine, sine)) / Math.SQRT2;
  }
  const extremes = waveformExtremes(values);
  return extremes === null ? null : measure === 'peak' ? extremes.peak : extremes.peakToPeak;
}

/** Volts to three figures: "6.36", "17.4", "231". */
export function formatVolts(volts: number | null): string {
  if (volts === null || !Number.isFinite(volts)) return '—';
  const magnitude = Math.abs(volts);
  return volts.toFixed(magnitude < 10 ? 2 : magnitude < 100 ? 1 : 0);
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
 *
 * With no current and a cogging sweep (#185), the row is the sweep's
 * peak-to-peak, so Results never shows two cogging numbers.
 */
export function torqueRippleView(result: Pick<SolveResult, 'summary' | 'torque_waveform' | 'solve_metadata'>): TorqueRippleView {
  const range = torqueRange(result.torque_waveform?.torque_Nm ?? []);
  const peakToPeak = range ? range.max - range.min : null;
  const current = result.solve_metadata?.current_amplitude_A;
  const noLoad = typeof current === 'number' && Number.isFinite(current) && Math.abs(current) <= 1e-6;
  const average = result.summary.avg_torque_Nm;
  const averageTooSmall = peakToPeak !== null && peakToPeak > 0 && typeof average === 'number' && Number.isFinite(average)
    && Math.abs(average) < RIPPLE_MIN_AVERAGE_FRACTION * peakToPeak;
  if (!noLoad && !averageTooSmall) {
    return { ripplePct: result.summary.torque_ripple_pct, peakToPeakNm: null, peakToPeakLabel: 'Torque p-p', note: null };
  }
  const cogging = noLoad ? result.summary.cogging : null;
  if (cogging && Number.isFinite(cogging.peak_to_peak_Nm)) {
    return {
      ripplePct: null,
      peakToPeakNm: cogging.peak_to_peak_Nm,
      peakToPeakLabel: 'Cogging torque p-p',
      note: `No current, so this torque is cogging. The value is the cogging sweep's: one cogging period at ${cogging.positions_per_period} positions, shown under Cogging torque.`,
    };
  }
  return {
    ripplePct: null,
    peakToPeakNm: peakToPeak,
    peakToPeakLabel: noLoad ? 'Cogging torque p-p' : 'Torque p-p',
    note: noLoad
      ? 'No current, so this torque is cogging: it averages to zero, and ripple as a percentage of the average has no meaning. The peak-to-peak swing is shown instead. '
        + "It comes from this sweep's positions, which are not sized to the cogging period; turn on Cogging torque on Solve for a cogging sweep."
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
