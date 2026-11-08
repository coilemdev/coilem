/**
 * A plain-language reading of the solver convergence report (the same backend
 * report the PDF and CSV carry): a verdict, four facts, a status per rotor
 * position, chart points and one table row per angle. The card renders these;
 * the backend's own rows stay under its technical details.
 */
import type { SolverConvergenceReport } from './model';

type Position = SolverConvergenceReport['positions'][number];
type Sweep = Position['sweep'];

export interface ConvergenceFact {
  key: string;
  label: string;
  value: string;
  hint?: string;
}

export interface ConvergenceOverview {
  tone: 'ok' | 'review' | 'muted';
  label: string;
  verdict: string;
  facts: ConvergenceFact[];
  /** How the loop's stopping test reads, e.g. "the steel changes by less than 1%". */
  stoppingRule: string;
  /** The allowed change as a percentage, when every position used one Picard tolerance. */
  allowedError: string | null;
  /** The largest total iteration limit recorded. */
  iterationLimit: number | null;
}

export type PositionStatusKind = 'converged' | 'slow' | 'stopped_early' | 'no_error' | 'linear' | 'not_recorded';

export interface PositionStatus {
  kind: PositionStatusKind;
  label: string;
  tone: 'ok' | 'review' | 'muted';
}

export interface ConvergenceCell {
  text: string;
  status: PositionStatus;
  title?: string;
}

export interface ConvergenceAngleRow {
  key: string;
  label: string;
  flagged: boolean;
  cells: Partial<Record<Sweep, ConvergenceCell>>;
}

export interface ConvergenceAngleTable {
  axis: 'angle' | 'position';
  sweeps: Sweep[];
  rows: ConvergenceAngleRow[];
}

export interface ConvergenceChartSeries {
  sweep: Sweep;
  points: Array<{ x: number; fraction: number; flagged: boolean; title: string }>;
}

export interface ConvergenceChart {
  axis: 'angle' | 'position';
  series: ConvergenceChartSeries[];
}

export const SWEEP_LABELS: Record<Sweep, string> = { no_load: 'No-load', loaded: 'Loaded' };
const SWEEP_ORDER: Sweep[] = ['no_load', 'loaded'];
const METHOD_LABELS = { picard: 'Picard', newton: 'Newton', linear: 'Linear' } as const;

const percent = (ratio: number) => `${Math.round(ratio * 100)}%`;
const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const rowValue = (report: SolverConvergenceReport, key: string) => report.summary.find((row) => row.key === key)?.value ?? null;
const angleLabel = (angle: number) => `${Number(angle.toFixed(2))}°`;

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** The backend's review rule, read per position: above the allowed error, or 80% of an iteration limit. */
export function positionStatus(position: Position): PositionStatus {
  const record = position.record;
  if (!record) return { kind: 'not_recorded', label: 'Not recorded', tone: 'muted' };
  if (record.method === 'linear') return { kind: 'linear', label: 'Linear', tone: 'ok' };
  if (position.stopping_ratio !== null && position.stopping_ratio > 1) return { kind: 'stopped_early', label: 'Stopped early', tone: 'review' };
  if (position.iteration_fraction !== null && position.iteration_fraction >= 0.8) return { kind: 'slow', label: 'Slow', tone: 'review' };
  if (position.stopping_ratio === null) return { kind: 'no_error', label: 'No error recorded', tone: 'muted' };
  return { kind: 'converged', label: 'Converged', tone: 'ok' };
}

function positionTitle(position: Position): string | undefined {
  const record = position.record;
  if (!record || record.method === 'linear') return undefined;
  const error = position.stopping_ratio === null ? 'final error not recorded' : `final error ${percent(position.stopping_ratio)} of allowed`;
  return `${METHOD_LABELS[record.method]}: ${record.iterations} of ${record.max_iterations} iterations, ${error}${record.solution_reused ? ', field reused' : ''}`;
}

function cell(position: Position): ConvergenceCell {
  const status = positionStatus(position);
  const record = position.record;
  if (!record || record.method === 'linear') return { text: status.label, status };
  const parts = [String(record.iterations)];
  if (record.solution_reused) parts.push('reused');
  if (status.kind === 'stopped_early') parts.push(`Stopped early, error ${percent(position.stopping_ratio!)}`);
  else if (status.kind !== 'converged') parts.push(status.label);
  return { text: parts.join(' · '), status, title: positionTitle(position) };
}

function usesAngles(report: SolverConvergenceReport): boolean {
  return report.positions.length > 0 && report.positions.every((position) => position.electrical_angle_deg !== null);
}

/** One row per electrical angle, sweeps side by side (rows per position index when angles are unknown). */
export function convergenceAngleTable(report?: SolverConvergenceReport | null): ConvergenceAngleTable {
  const positions = report?.positions ?? [];
  const axis = report && usesAngles(report) ? 'angle' : 'position';
  const sweeps = SWEEP_ORDER.filter((sweep) => positions.some((position) => position.sweep === sweep));
  const rows = new Map<string, ConvergenceAngleRow & { order: number }>();
  for (const position of positions) {
    const angle = axis === 'angle' ? position.electrical_angle_deg! : null;
    const key = angle !== null ? `a${angle.toFixed(6)}` : `p${position.index}`;
    const row = rows.get(key) ?? {
      key,
      label: angle !== null ? angleLabel(angle) : `Position ${position.index + 1}`,
      flagged: false,
      cells: {},
      order: angle ?? position.index,
    };
    row.cells[position.sweep] = cell(position);
    row.flagged ||= position.review;
    rows.set(key, row);
  }
  return {
    axis,
    sweeps,
    rows: [...rows.values()].sort((left, right) => left.order - right.order).map(({ order: _order, ...row }) => row),
  };
}

/** Share of the iteration limit each nonlinear position used, per sweep. */
export function convergenceChart(report?: SolverConvergenceReport | null): ConvergenceChart {
  const positions = report?.positions ?? [];
  const axis = report && usesAngles(report) ? 'angle' : 'position';
  const series = SWEEP_ORDER.map((sweep) => ({
    sweep,
    points: positions
      .filter((position) => position.sweep === sweep && position.record && position.record.method !== 'linear' && position.iteration_fraction !== null)
      .map((position) => ({
        x: axis === 'angle' ? position.electrical_angle_deg! : position.index + 1,
        fraction: position.iteration_fraction!,
        flagged: position.review,
        title: `${SWEEP_LABELS[sweep]} ${axis === 'angle' ? angleLabel(position.electrical_angle_deg!) : `position ${position.index + 1}`}: ${positionTitle(position) ?? ''}`,
      }))
      .sort((left, right) => left.x - right.x),
  })).filter((item) => item.points.length > 0);
  return { axis, series };
}

function allowedChange(nonlinear: Position[]): string | null {
  const methods = new Set(nonlinear.map((position) => position.record!.method));
  const tolerances = new Set(nonlinear.map((position) => position.record!.tolerance));
  if (methods.size !== 1 || !methods.has('picard') || tolerances.size !== 1) return null;
  const [tolerance] = tolerances;
  return `${Number((tolerance * 100).toPrecision(3))}%`;
}

export function convergenceOverview(report?: SolverConvergenceReport | null): ConvergenceOverview {
  if (!report || report.status === 'not_recorded') {
    return {
      tone: 'muted',
      label: 'Not recorded',
      verdict: "This run didn't record solver convergence, so it can't be checked. It cannot be recovered from iteration counts or current settings.",
      facts: [],
      stoppingRule: 'the change is under the allowed error',
      allowedError: null,
      iterationLimit: null,
    };
  }
  const recorded = report.positions.filter((position) => position.record);
  const nonlinear = recorded.filter((position) => position.record?.method !== 'linear');
  const solved = nonlinear.filter((position) => !position.record?.solution_reused);
  const reused = recorded.filter((position) => position.record?.solution_reused).length;
  const withError = nonlinear.filter((position) => position.stopping_ratio !== null);
  const aboveLimit = withError.filter((position) => position.stopping_ratio! > 1).length;
  const nearCap = nonlinear.filter((position) => position.iteration_fraction !== null && position.iteration_fraction >= 0.8).length;
  const missing = report.positions.length - recorded.length;
  const flagged = report.positions.filter((position) => position.review).length;
  const iterations = solved.map((position) => position.record!.iterations);
  const hardest = solved.reduce<Position | null>(
    (worst, position) => (!worst || position.record!.iterations > worst.record!.iterations ? position : worst),
    null,
  );
  const allowedError = allowedChange(nonlinear);
  const limits = nonlinear.map((position) => position.record!.max_iterations);

  const plan = rowValue(report, 'accuracy_plan');
  const density = rowValue(report, 'mesh_density');
  const elements = Number(rowValue(report, 'mesh_elements'));
  const facts: ConvergenceFact[] = [
    {
      key: 'positions',
      label: 'Rotor positions',
      value: `${recorded.length} of ${report.positions.length}`,
      hint: reused ? `${plural(reused, 'reused an earlier field', 'reused earlier fields')}` : undefined,
    },
  ];
  if (withError.length) {
    facts.push({
      key: 'under_error',
      label: 'Under the allowed error',
      value: `${withError.length - aboveLimit} of ${withError.length}`,
      hint: aboveLimit ? `${aboveLimit} stopped early` : undefined,
    });
  }
  if (hardest) {
    facts.push({
      key: 'iterations',
      label: 'Most iterations',
      value: `${hardest.record!.iterations} of ${hardest.record!.max_iterations}`,
      hint: `Median ${Math.round(median(iterations))}`,
    });
  }
  if (plan || density || Number.isFinite(elements)) {
    facts.push({
      key: 'mesh',
      label: 'Mesh',
      value: [density, Number.isFinite(elements) && elements > 0 ? `${elements.toLocaleString('en-US')} elements` : null].filter(Boolean).join(' · ') || 'Not recorded',
      hint: plan ? `${plan} accuracy plan` : undefined,
    });
  }

  const base = {
    facts,
    stoppingRule: allowedError ? `the steel changes by less than ${allowedError}` : 'the change is under the allowed error',
    allowedError,
    iterationLimit: limits.length ? Math.max(...limits) : null,
  };
  if (report.status === 'review') {
    const reasons = [
      aboveLimit ? `${aboveLimit} stopped above the allowed error` : null,
      nearCap ? `${nearCap} used 80% or more of the iteration limit` : null,
    ].filter(Boolean);
    return {
      ...base,
      tone: 'review',
      label: 'Needs review',
      verdict: `${flagged} of ${recorded.length} rotor positions need a look: ${reasons.join('; ')}. Check the waveforms at those angles.`,
    };
  }
  if (report.status === 'partial') {
    const missingResidual = nonlinear.length - withError.length;
    const gaps = [
      missing ? `${plural(missing, 'position has', 'positions have')} no convergence record` : null,
      missingResidual ? `${plural(missingResidual, 'position has', 'positions have')} no final error recorded` : null,
    ].filter(Boolean);
    return {
      ...base,
      tone: 'muted',
      label: 'Incomplete records',
      verdict: `${gaps.join('; ')}, so ${missing + missingResidual === 1 ? 'it' : 'they'} can't be checked. The rest are within their limits.`,
    };
  }
  if (!nonlinear.length) {
    return { ...base, tone: 'ok', label: 'Linear solves', verdict: 'Every position was solved in one step with linear materials, so there was nothing to iterate.' };
  }
  const reuseNote = reused ? ` (${reused} reused)` : '';
  const hardestNote = hardest ? `, using at most ${hardest.record!.iterations} of ${hardest.record!.max_iterations} iterations` : '';
  return { ...base, tone: 'ok', label: 'Converged', verdict: `All ${recorded.length} rotor positions converged${reuseNote}${hardestNote}.` };
}
