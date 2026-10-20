/**
 * The Performance view's numbers (#142): default drive limits, chart axes,
 * efficiency colour bands, the Ld/Lq table and the map CSV.
 *
 * Everything here reads the backend's records as they are
 * (backend/drive_performance.py, backend/flux_linkage_map.py): currents are
 * peak phase amperes, torque is electromagnetic, speed is shaft rpm.
 */

import type { DriveLimits, EfficiencyMap, FluxLinkageMap, TorqueSpeedCurve } from './performance';
import { rampColor } from './lossesView';

// Efficiency bands: the validated sequential blue, dark (less efficient) to light.
const EFFICIENCY_RAMP = ['#184f95', '#2a78d6', '#5598e7', '#9ec5f4', '#cde2fb'] as const;

/** Linear limit of space-vector modulation: peak phase voltage = Vdc / √3. */
export const SVPWM_MODULATION = 2 / Math.sqrt(3);

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function roundUp(value: number, step: number): number {
  return Math.ceil(value / step - 1e-9) * step;
}

export interface DriveDefaultsInput {
  ratedSpeedRpm: number;
  /** The solved operating point's rms phase current. */
  phaseCurrentRmsA: number | null | undefined;
  /** Rms line-to-neutral back-EMF fundamental at the rated speed. */
  backEmfRmsV: number | null | undefined;
  dcBusV?: number | null;
}

/**
 * Starting limits for a run: twice the solved current as the peak, the solved
 * current as the continuous limit, a bus that reaches the rated speed with
 * about 30% headroom over the back EMF, and three times the rated speed.
 */
export function defaultDriveLimits({ ratedSpeedRpm, phaseCurrentRmsA, backEmfRmsV, dcBusV }: DriveDefaultsInput): DriveLimits {
  const solvedPeak = finite(phaseCurrentRmsA) && phaseCurrentRmsA > 0 ? phaseCurrentRmsA * Math.SQRT2 : 10;
  const emfPeak = finite(backEmfRmsV) && backEmfRmsV > 0 ? backEmfRmsV * Math.SQRT2 : 10;
  const bus = finite(dcBusV) && dcBusV > 0 ? dcBusV : roundUp(Math.sqrt(3) * emfPeak * 1.3, 10);
  return {
    dc_bus_V: bus,
    modulation_index_max: SVPWM_MODULATION,
    peak_current_A: roundUp(2 * solvedPeak, 1),
    continuous_current_A: roundUp(solvedPeak, 0.5),
    max_speed_rpm: roundUp(3 * Math.max(ratedSpeedRpm, 100), 100),
  };
}

/** Round tick values from 0 to the first at or above max: steps of 1, 2 or 5 × 10ⁿ. */
export function niceTicks(max: number, count = 5): number[] {
  if (!(max > 0)) return [0];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((factor) => factor * magnitude).find((candidate) => candidate >= raw) ?? 10 * magnitude;
  const ticks = [0];
  while (ticks[ticks.length - 1] < max - step * 1e-9) ticks.push(Number((ticks.length * step).toPrecision(12)));
  return ticks;
}

/** The top tick of an axis covering [0, max]. */
export function axisTop(max: number, count = 5): number {
  const ticks = niceTicks(max, count);
  return ticks[ticks.length - 1] || 1;
}

/**
 * Efficiency bands of 2 points from a floor near the map's low end to its peak.
 * The floor stays within 16 points of the peak, so the region a drive runs in
 * gets its own bands; anything lower shares the darkest one.
 */
export function efficiencyBands(map: EfficiencyMap): { floor: number; top: number; step: number } {
  const values = map.efficiency_pct.flat().filter(finite).sort((a, b) => a - b);
  if (!values.length) return { floor: 0, top: 100, step: 2 };
  const low = values[Math.floor(0.05 * (values.length - 1))];
  const top = Math.min(100, Math.ceil(values[values.length - 1]));
  const floor = Math.max(0, top - 16, Math.min(top - 10, Math.floor(low / 2) * 2));
  return { floor, top, step: 2 };
}

/** Band colour for an efficiency: the sequential blue ramp, lighter is more efficient. */
export function efficiencyColor(eta: number, bands: { floor: number; top: number; step: number }): string {
  const banded = Math.floor((Math.max(eta, bands.floor) - bands.floor) / bands.step) * bands.step + bands.floor;
  return rampColor(EFFICIENCY_RAMP, (banded - bands.floor) / Math.max(bands.top - bands.floor, bands.step));
}

/** Value of a curve at a speed by linear interpolation; null outside its speeds. */
export function curveAt(curve: TorqueSpeedCurve, speedRpm: number): { torque: number; power: number; region: string } | null {
  const speeds = curve.speed_rpm;
  if (!speeds.length || speedRpm < speeds[0] || speedRpm > speeds[speeds.length - 1]) return null;
  let index = speeds.findIndex((speed) => speed >= speedRpm);
  if (index <= 0) index = 1;
  const t = (speedRpm - speeds[index - 1]) / Math.max(speeds[index] - speeds[index - 1], 1e-12);
  const lerp = (values: number[]) => values[index - 1] + Math.min(Math.max(t, 0), 1) * (values[index] - values[index - 1]);
  return { torque: lerp(curve.torque_Nm), power: lerp(curve.power_W), region: curve.region[t < 0.5 ? index - 1 : index] };
}

export interface InductanceRow {
  currentA: number;
  /** (λd − λpm) / id at γ = 90°, all d-axis current. */
  ldH: number | null;
  /** λq / iq at γ = 0°, all q-axis current. */
  lqH: number | null;
}

/** Apparent Ld and Lq against current, from the map's 90° and 0° points. */
export function inductanceTable(map: FluxLinkageMap): InductanceRow[] {
  const at = (current: number, gamma: number) => map.points.find((point) => point.current_peak_A === current && point.gamma_deg === gamma && point.status === 'ok');
  const zero = at(0, map.gamma_deg[0]);
  const lambdaPm = zero && finite(zero.lambda_d_Wb) ? zero.lambda_d_Wb : null;
  return map.current_peak_A.filter((current) => current > 0).map((current) => {
    const dAxis = at(current, 90);
    const qAxis = at(current, 0);
    const ldH = dAxis && lambdaPm !== null && finite(dAxis.lambda_d_Wb) && Math.abs(dAxis.i_d_A) > 1e-9
      ? (dAxis.lambda_d_Wb - lambdaPm) / dAxis.i_d_A : null;
    const lqH = qAxis && finite(qAxis.lambda_q_Wb) && Math.abs(qAxis.i_q_A) > 1e-9 ? qAxis.lambda_q_Wb / qAxis.i_q_A : null;
    return { currentA: current, ldH, lqH };
  });
}

const CSV_COLUMNS: Array<[string, (point: FluxLinkageMap['points'][number]) => unknown]> = [
  ['current_peak_A', (point) => point.current_peak_A],
  ['gamma_deg', (point) => point.gamma_deg],
  ['i_d_A', (point) => point.i_d_A],
  ['i_q_A', (point) => point.i_q_A],
  ['status', (point) => point.status],
  ['avg_torque_Nm', (point) => point.avg_torque_Nm],
  ['torque_ripple_pct', (point) => point.torque_ripple_pct],
  ['lambda_d_Wb', (point) => point.lambda_d_Wb],
  ['lambda_q_Wb', (point) => point.lambda_q_Wb],
  ['iron_loss_W', (point) => point.iron_loss_W],
  ['iron_hysteresis_loss_W', (point) => point.iron_hysteresis_loss_W],
  ['iron_eddy_loss_W', (point) => point.iron_eddy_loss_W],
  ['nonlinear_iterations_max', (point) => point.nonlinear_iterations_max],
  ['error', (point) => point.error],
];

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The map as CSV for drive-control work: a commented header with its conventions, then one row per point. */
export function mapCsv(map: FluxLinkageMap): string {
  const header = [
    `# coilEM flux-linkage map, scope ${map.scope_key}`,
    `# ${map.pole_pairs} pole pairs; currents are peak phase amperes; id = -I sin(gamma), iq = I cos(gamma); amplitude-invariant Park`,
    `# iron loss at ${map.reference_speed_rpm} rpm; ${map.rotor_positions} rotor positions per point; mesh ${map.mesh_density}`,
  ];
  const rows = map.points.map((point) => CSV_COLUMNS.map(([, read]) => csvCell(read(point))).join(','));
  return [...header, CSV_COLUMNS.map(([name]) => name).join(','), ...rows].join('\n') + '\n';
}

/** "about 6 min" style estimate for a number of seconds. */
export function formatDuration(seconds: number | null | undefined): string {
  if (!finite(seconds)) return '';
  if (seconds < 90) return `about ${Math.max(5, Math.round(seconds / 5) * 5)} s`;
  return `about ${Math.round(seconds / 60)} min`;
}
