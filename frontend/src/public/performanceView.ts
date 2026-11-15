/**
 * The Performance view's numbers (#142): default drive limits, chart axes,
 * efficiency colour bands, the Ld/Lq table and the map CSV.
 *
 * Everything here reads the backend's records as they are
 * (backend/drive_performance.py, backend/flux_linkage_map.py): currents are
 * peak phase amperes, torque is electromagnetic, speed is shaft rpm.
 */

import type { DqFluxLinkage, DriveLimits, EfficiencyMap, FluxLinkageMap, TorqueSpeedCurve, TorqueSpeedEnvelope } from './performance';
import { rampColor } from './lossesView';
import { formatSignificant } from './numberFormat';
import { FLUX_LINKAGE_MAP_STATUS_REASON } from './outputStatus';

// Efficiency bands: the validated sequential blue, dark (less efficient) to light.
const EFFICIENCY_RAMP = ['#184f95', '#2a78d6', '#5598e7', '#9ec5f4', '#cde2fb'] as const;

/** Linear limit of space-vector modulation: peak phase voltage = Vdc / √3. */
export const SVPWM_MODULATION = 2 / Math.sqrt(3);

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function roundUp(value: number, step: number): number {
  return Math.ceil(value / step - 1e-9) * step;
}

/** Phase-current units the drive inputs are shown in; the API and the map work in peak amperes. */
export interface CurrentUnits {
  unit: 'A rms' | 'A peak';
  fromPeak: (peakA: number) => number;
  toPeak: (value: number) => number;
}

/** The Solve page's convention: peak when the design is set to peak, rms otherwise (six-step plateau included). */
export function currentUnits(convention: string | null | undefined): CurrentUnits {
  if (convention === 'peak') return { unit: 'A peak', fromPeak: (value) => value, toPeak: (value) => value };
  return { unit: 'A rms', fromPeak: (value) => value / Math.SQRT2, toPeak: (value) => value * Math.SQRT2 };
}

export interface DriveDefaultsInput {
  ratedSpeedRpm: number;
  /** The solved operating point's rms phase current. */
  phaseCurrentRmsA: number | null | undefined;
  /** Rms line-to-neutral back-EMF fundamental at the rated speed. */
  backEmfRmsV: number | null | undefined;
  dcBusV?: number | null;
  /** Peak amperes per unit the inputs are shown in (√2 for rms), so defaults round in that unit. */
  shownUnitPeakA?: number;
}

/**
 * Starting limits for a run: the solved current as the continuous limit, twice
 * that as the peak, a bus that reaches the rated speed with about 30% headroom
 * over the back EMF, and three times the rated speed. Currents are returned in
 * peak amperes, rounded in the unit they are shown in.
 */
export function defaultDriveLimits({ ratedSpeedRpm, phaseCurrentRmsA, backEmfRmsV, dcBusV, shownUnitPeakA = 1 }: DriveDefaultsInput): DriveLimits {
  const solvedPeak = finite(phaseCurrentRmsA) && phaseCurrentRmsA > 0 ? phaseCurrentRmsA * Math.SQRT2 : 10;
  const emfPeak = finite(backEmfRmsV) && backEmfRmsV > 0 ? backEmfRmsV * Math.SQRT2 : 10;
  const bus = finite(dcBusV) && dcBusV > 0 ? dcBusV : roundUp(Math.sqrt(3) * emfPeak * 1.3, 10);
  const continuousShown = roundUp(solvedPeak / shownUnitPeakA, 0.5);
  return {
    dc_bus_V: bus,
    modulation_index_max: SVPWM_MODULATION,
    peak_current_A: 2 * continuousShown * shownUnitPeakA,
    continuous_current_A: continuousShown * shownUnitPeakA,
    max_speed_rpm: roundUp(3 * Math.max(ratedSpeedRpm, 100), 100),
  };
}

/** Efficiency of the map cell nearest a point, or null when the point is off the map or above the envelope. */
export function efficiencyAt(map: EfficiencyMap, speedRpm: number, torqueNm: number): number | null {
  const { speed_rpm: speeds, torque_Nm: torques } = map;
  if (speeds.length < 2 || torques.length < 2) return null;
  const column = Math.round((speedRpm - speeds[0]) / (speeds[1] - speeds[0]));
  const row = Math.round((torqueNm - torques[0]) / (torques[1] - torques[0]));
  if (row < 0 || row >= torques.length || column < 0 || column >= speeds.length) return null;
  const value = map.efficiency_pct[row][column];
  return finite(value) ? value : null;
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

export interface CurvePoint {
  torque: number;
  power: number;
  region: string;
  /** Phase current magnitude, peak amperes, and its angle γ (0° all q-axis). */
  currentPeakA: number;
  gammaDeg: number;
}

/** Value of a curve at a speed by linear interpolation; null outside its speeds. */
export function curveAt(curve: TorqueSpeedCurve, speedRpm: number): CurvePoint | null {
  const speeds = curve.speed_rpm;
  if (!speeds.length || speedRpm < speeds[0] || speedRpm > speeds[speeds.length - 1]) return null;
  let index = speeds.findIndex((speed) => speed >= speedRpm);
  if (index <= 0) index = 1;
  const t = (speedRpm - speeds[index - 1]) / Math.max(speeds[index] - speeds[index - 1], 1e-12);
  const lerp = (values: number[]) => values[index - 1] + Math.min(Math.max(t, 0), 1) * (values[index] - values[index - 1]);
  const iD = lerp(curve.i_d_A);
  const iQ = lerp(curve.i_q_A);
  return {
    torque: lerp(curve.torque_Nm),
    power: lerp(curve.power_W),
    region: curve.region[t < 0.5 ? index - 1 : index],
    currentPeakA: Math.hypot(iD, iQ),
    gammaDeg: (Math.atan2(-iD, iQ) * 180) / Math.PI,
  };
}

// The peak curve is a polyline through interpolated map values, so a point
// this little above it still counts as on it.
const OUTSIDE_TORQUE_SHARE = 0.01;

export interface SolvedPointMapInput {
  envelope: TorqueSpeedEnvelope;
  /** The map's pole pairs, for the electrical speed. */
  polePairs: number;
  speedRpm: number;
  torqueNm: number;
  /** The run's loaded d/q record at the solved point; pass it for sinusoidal current only. */
  dq?: Pick<DqFluxLinkage, 'i_d_A' | 'i_q_A' | 'lambda_d_Wb' | 'lambda_q_Wb'> | null;
}

export interface SolvedPointOutsideMap {
  speedRpm: number;
  torqueNm: number;
  limits: DriveLimits;
  aboveTopSpeed: boolean;
  /** DC bus the point needs at its own current and angle; null without a d/q record. */
  busNeededV: number | null;
  /** The point's peak phase current, when it is above the map's Peak current. */
  currentAbovePeakA: number | null;
}

/**
 * The limits that keep the run's solved point outside the map's peak envelope,
 * or null when it lies on or under the peak curve (within 1%).
 *
 * The bus the point needs applies the map's own voltage model
 * (backend/drive_performance.py) to the run's loaded d/q record, which comes
 * from the same routine as every map point:
 * |v| = |(R·id − ωe·λq, R·iq + ωe·λd)| ≤ m·Vdc / 2, with the envelope's phase
 * resistance and modulation limit. That is the bus at the point's own current
 * and angle; field weakening at more current may reach the same torque with
 * less. When the record shows the point within every limit, it is outside only
 * by the map's interpolation, and null is returned too.
 */
export function solvedPointOutsideMap({ envelope, polePairs, speedRpm, torqueNm, dq }: SolvedPointMapInput): SolvedPointOutsideMap | null {
  const peak = envelope.curves.find((curve) => curve.limit === 'peak') ?? envelope.curves[0];
  if (!peak || !peak.speed_rpm.length || !finite(speedRpm) || !finite(torqueNm) || speedRpm < 0 || torqueNm <= 0) return null;
  const at = curveAt(peak, speedRpm);
  if (at !== null && torqueNm <= at.torque * (1 + OUTSIDE_TORQUE_SHARE)) return null;
  const { limits } = envelope;
  const aboveTopSpeed = speedRpm > limits.max_speed_rpm * (1 + 1e-9);
  if (!dq || ![dq.i_d_A, dq.i_q_A, dq.lambda_d_Wb, dq.lambda_q_Wb, polePairs, limits.modulation_index_max].every(finite) || polePairs <= 0) {
    return { speedRpm, torqueNm, limits, aboveTopSpeed, busNeededV: null, currentAbovePeakA: null };
  }
  const omegaE = ((speedRpm * 2 * Math.PI) / 60) * polePairs;
  const resistance = finite(envelope.phase_resistance_ohm) ? envelope.phase_resistance_ohm : 0;
  const volts = Math.hypot(resistance * dq.i_d_A - omegaE * dq.lambda_q_Wb, resistance * dq.i_q_A + omegaE * dq.lambda_d_Wb);
  const busNeededV = (2 * volts) / limits.modulation_index_max;
  const current = Math.hypot(dq.i_d_A, dq.i_q_A);
  const currentAbovePeakA = current > limits.peak_current_A * (1 + 1e-6) ? current : null;
  if (!aboveTopSpeed && busNeededV <= limits.dc_bus_V && currentAbovePeakA === null) return null;
  return { speedRpm, torqueNm, limits, aboveTopSpeed, busNeededV, currentAbovePeakA };
}

const listed = (items: string[]) => (items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`);

/** The Torque–speed tab's note for a solved point outside the map, naming the settings that would take it in. */
export function solvedPointOutsideNote(outside: SolvedPointOutsideMap, formatCurrent: (peakA: number) => string): string {
  const { limits, busNeededV, currentAbovePeakA } = outside;
  const point = `The solved point (${formatSignificant(outside.speedRpm)} rpm, ${formatSignificant(outside.torqueNm)} N·m)`;
  const bus = `${limits.dc_bus_V.toLocaleString()} V DC bus`;
  const peak = `${formatCurrent(limits.peak_current_A)} Peak current`;
  const where = 'in Solve → Analysis → Torque–speed map to include it.';
  const busShort = busNeededV !== null && busNeededV > limits.dc_bus_V;
  if (!outside.aboveTopSpeed && !busShort && currentAbovePeakA === null) {
    // No d/q record to tell the voltage limit from the current limit.
    return `${point} is outside this map at the ${bus} and ${peak}. Raise DC bus or Peak current ${where}`;
  }
  const limitsHit = [
    ...(outside.aboveTopSpeed ? [{ at: `${limits.max_speed_rpm.toLocaleString()} rpm Top speed`, setting: 'Top speed' }] : []),
    ...(busShort ? [{ at: bus, setting: 'DC bus' }] : []),
    ...(currentAbovePeakA !== null ? [{ at: peak, setting: 'Peak current' }] : []),
  ];
  const volts = busShort ? (busNeededV >= 10 ? Math.ceil(busNeededV) : Math.ceil(busNeededV * 10) / 10).toLocaleString() : '';
  const detail = busShort && currentAbovePeakA !== null ? `It was solved at ${formatCurrent(currentAbovePeakA)}, where it needs about ${volts} V; raise`
    : busShort ? `At its solved current it needs about ${volts} V; raise`
      : currentAbovePeakA !== null ? `It was solved at ${formatCurrent(currentAbovePeakA)}; raise`
        : 'Raise';
  return `${point} is outside this map at the ${listed(limitsHit.map((limit) => limit.at))}. ${detail} ${listed(limitsHit.map((limit) => limit.setting))} ${where}`;
}

/** The least-loss current at the map cell nearest a point, rms and angle, or null. */
export function currentAt(map: EfficiencyMap, speedRpm: number, torqueNm: number): { rmsA: number; gammaDeg: number | null } | null {
  const { speed_rpm: speeds, torque_Nm: torques } = map;
  if (!map.phase_current_rms_A || speeds.length < 2 || torques.length < 2) return null;
  const column = Math.round((speedRpm - speeds[0]) / (speeds[1] - speeds[0]));
  const row = Math.round((torqueNm - torques[0]) / (torques[1] - torques[0]));
  if (row < 0 || row >= torques.length || column < 0 || column >= speeds.length) return null;
  const rms = map.phase_current_rms_A[row]?.[column];
  const gamma = map.current_angle_deg?.[row]?.[column];
  return finite(rms) ? { rmsA: rms, gammaDeg: finite(gamma) ? gamma : null } : null;
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
    `# experimental: ${FLUX_LINKAGE_MAP_STATUS_REASON}`,
  ];
  const rows = map.points.map((point) => CSV_COLUMNS.map(([, read]) => csvCell(read(point))).join(','));
  return [...header, CSV_COLUMNS.map(([name]) => name).join(','), ...rows].join('\n') + '\n';
}

export interface MapEstimateInput {
  /** The run's own solve time and loaded rotor positions. */
  runSolveSeconds: number | null | undefined;
  runPositions: number | null | undefined;
  /** Rotor positions each map point solves. */
  pointPositions: number;
  solves: number;
  /** The zero-current point is still to solve; it also runs the no-load sweep. */
  zeroPointPending: boolean;
}

// A map point costs about this much of the run's per-position solve time, setup
// included (measured 2026-10-20: 4p12s, 8p12s and 6p36s at 12 positions per point).
const MAP_POINT_COST = 1.25;
const ZERO_POINT_COST = 3;

/** Rough seconds a map will take, scaled from the run's own solve time; null without one. */
export function estimateMapSeconds({ runSolveSeconds, runPositions, pointPositions, solves, zeroPointPending }: MapEstimateInput): number | null {
  if (!finite(runSolveSeconds) || !finite(runPositions) || runSolveSeconds <= 0 || runPositions <= 0 || solves <= 0) return null;
  const perPoint = Math.max(2, MAP_POINT_COST * runSolveSeconds * (pointPositions / runPositions));
  return perPoint * (solves + (zeroPointPending ? ZERO_POINT_COST - 1 : 0));
}

/** "about 6 min" style estimate for a number of seconds. */
export function formatDuration(seconds: number | null | undefined): string {
  if (!finite(seconds)) return '';
  if (seconds < 90) return `about ${Math.max(5, Math.round(seconds / 5) * 5)} s`;
  return `about ${Math.round(seconds / 60)} min`;
}
