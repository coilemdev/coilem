/**
 * The Cogging torque card (#185): one cogging period solved with no current,
 * its peak-to-peak and peak, the harmonic spectrum in cycles per mechanical
 * revolution, its share of the loaded torque, the extraction method and the
 * output's status. backend/cogging.py computes every number and the run PDF
 * and CSV print the same record, so this module only formats it.
 */

import { COGGING_TORQUE_STATUS_REASON, recordStatus, type OutputStatus } from './outputStatus';
import type { CoggingTorqueRecord, SolveResult } from './model';

export const COGGING_METHOD_LABELS: Record<string, string> = {
  arkkio: 'Arkkio',
  contour: 'Contour MST',
  mst: 'Area MST',
  weighted_stress: 'WST',
  weighted_stress_centered: 'WST, mean removed',
};

/** Harmonic bars the card draws: the fundamental and its next multiples. */
export const COGGING_HARMONIC_BARS = 8;

export interface CoggingRow {
  key: string;
  label: string;
  value: string;
  unit: string;
  hint?: string;
}

export interface CoggingHarmonicBar {
  order: number;
  multiple: number;
  value: string;
  /** Amplitude over the largest shown, 0 to 1. */
  share: number;
}

export interface CoggingView {
  rows: CoggingRow[];
  /** Two numbers an exact solve makes zero, so their size against the peak-to-peak is the mesh noise. */
  noise: CoggingRow[];
  harmonics: CoggingHarmonicBar[];
  waveform: { electricalDeg: number[]; mechanicalDeg: number[]; torqueNm: number[] } | null;
  /** One cogging period in both angle units, "60° elec · 15° mech". */
  period: string;
  status: OutputStatus;
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function significant(value: number, digits = 3): string {
  if (value === 0) return '0';
  const rounded = Number(value.toPrecision(digits));
  const magnitude = Math.floor(Math.log10(Math.abs(rounded)));
  return value.toFixed(Math.max(0, digits - 1 - magnitude)).replace(/^-/, '−');
}

const show = (value: unknown, digits = 3) => (finite(value) ? significant(value, digits) : '—');
const degrees = (value: number) => `${Number(value.toFixed(3))}°`;

/** One cogging period of a design: (electrical degrees, mechanical degrees, cycles per revolution). */
export function coggingPeriod(slotCount: number, poleCount: number): { elecDeg: number; mechDeg: number; order: number } | null {
  if (!(slotCount > 0) || !(poleCount > 0) || !Number.isInteger(slotCount) || !Number.isInteger(poleCount)) return null;
  const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
  const order = (slotCount * poleCount) / gcd(slotCount, poleCount);
  const mechDeg = 360 / order;
  return { elecDeg: (mechDeg * poleCount) / 2, mechDeg, order };
}

/**
 * What the Solve page says the Cogging torque option adds. Without corner
 * refinement the magnet and slot corners are meshed coarsely, and on the
 * 8p/12s example the cogging noise rose from 0.4% to 10% of the peak-to-peak
 * (docs/COGGING_CONVERGENCE.md).
 */
export function coggingPlanNote(
  slotCount: number,
  poleCount: number,
  positionsPerPeriod?: number | null,
  cornerRefinement = true,
): string {
  const period = coggingPeriod(slotCount, poleCount);
  const positions = finite(positionsPerPeriod) && positionsPerPeriod > 0 ? positionsPerPeriod : null;
  const span = period ? ` (${degrees(period.elecDeg)} electrical, ${degrees(period.mechDeg)} mechanical)` : '';
  const sampling = positions !== null ? `, at ${positions} positions plus the repeated end` : '';
  const corners = cornerRefinement ? '' : ' Corner refinement is off, which makes cogging much noisier; turn it on under Advanced options.';
  const preview = positions === 12
    ? ' Preview is for iteration: 12 positions can miss peaks and higher harmonics. Check convergence with Standard or High accuracy.' : '';
  return `Adds a no-current sweep over one cogging period${span}${sampling}.${preview}${corners}`;
}

/** The card's content, or null for a run without a cogging sweep. */
export function coggingView(
  result: { summary: Pick<SolveResult['summary'], 'cogging'>; cogging_torque_waveform?: SolveResult['cogging_torque_waveform'] },
  poleCount: number,
): CoggingView | null {
  const record: CoggingTorqueRecord | null | undefined = result.summary.cogging;
  if (!record) return null;
  const method = COGGING_METHOD_LABELS[record.method] ?? record.method;
  const ratio = record.peak_to_peak_of_loaded_pct;
  const rows: CoggingRow[] = [
    { key: 'peak-to-peak', label: 'Peak to peak', value: show(record.peak_to_peak_Nm), unit: 'N·m',
      hint: 'Largest minus smallest cogging torque over one cogging period.' },
    { key: 'peak', label: 'Peak', value: show(record.peak_Nm), unit: 'N·m', hint: 'Largest |cogging torque| over the period.' },
    { key: 'first-harmonic', label: `Fundamental, ${record.fundamental_order}/rev`, value: show(record.first_harmonic_Nm), unit: 'N·m',
      hint: `Peak amplitude at the fundamental cogging order, LCM(slots, poles) = ${record.fundamental_order} cycles per mechanical revolution.` },
    { key: 'loaded-share', label: 'Of loaded torque', value: show(ratio, 3), unit: finite(ratio) ? '%' : '',
      hint: finite(ratio)
        ? `Peak to peak as a share of this run's mean loaded torque, ${show(record.loaded_mean_torque_Nm)} N·m.`
        : record.loaded_comparison_reason ?? 'Loaded torque comparison unavailable.' },
    { key: 'method', label: 'Method', value: method, unit: '', hint: 'Torque extraction method of the cogging waveform.' },
    { key: 'positions', label: 'Positions', value: String(record.positions_per_period), unit: 'per period',
      hint: 'Sampled positions per cogging period, plus the repeated end. Congruent positions may share a mesh and solution.' },
  ];
  const noise: CoggingRow[] = [
    { key: 'mean', label: 'Mean', value: show(record.mean_Nm), unit: 'N·m',
      hint: 'Cogging averages to zero over a period; what is left is numerical noise. Compare it with the peak to peak.' },
    { key: 'end-mismatch', label: 'End mismatch', value: show(record.endpoint_mismatch_Nm), unit: 'N·m',
      hint: finite(record.endpoint_mismatch_Nm)
        ? 'The torque at the end of the period minus the start, from independently meshed endpoints.'
        : 'Unavailable: the closing endpoint is missing, its independence was not recorded, or the endpoints share a mesh or solution.' },
  ];
  const shown = record.harmonics.slice(0, COGGING_HARMONIC_BARS);
  const largest = Math.max(0, ...shown.map((harmonic) => harmonic.amplitude_Nm).filter(finite));
  const harmonics = shown.map((harmonic) => ({
    order: harmonic.order,
    multiple: harmonic.multiple,
    value: show(harmonic.amplitude_Nm),
    share: largest > 0 && finite(harmonic.amplitude_Nm) ? harmonic.amplitude_Nm / largest : 0,
  }));
  const wave = result.cogging_torque_waveform;
  const polePairs = poleCount / 2;
  const waveform = wave && wave.electrical_angle_deg.length >= 2 && wave.electrical_angle_deg.length === wave.torque_Nm.length && polePairs > 0
    ? {
      electricalDeg: wave.electrical_angle_deg,
      mechanicalDeg: wave.electrical_angle_deg.map((angle) => angle / polePairs),
      torqueNm: wave.torque_Nm,
    }
    : null;
  return {
    rows,
    noise,
    harmonics,
    waveform,
    period: `${degrees(record.period_elec_deg)} elec · ${degrees(record.period_mech_deg)} mech`,
    status: recordStatus(record, COGGING_TORQUE_STATUS_REASON),
  };
}
