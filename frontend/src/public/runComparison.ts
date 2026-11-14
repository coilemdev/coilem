import type { SolveResult } from './model';
import { isSolveTimeBreakdown } from './solveTime';

/** The comparison route omits fields, playback and other heavy results. */
export type ComparisonResult = Pick<SolveResult, 'summary' | 'solve_metadata' | 'torque_waveform' | 'back_emf_waveform' | 'cogging_torque_waveform'>;

interface RecordedRun {
  project_slug: string;
  run_id: string;
  status: string;
  solver_name?: string | null;
  completed_at?: string | null;
}

/** Never select a newer run, a partial run, or another project's run as the baseline. */
export function previousCompletedRun<T extends RecordedRun>(runs: T[], current: Pick<RecordedRun, 'project_slug' | 'run_id' | 'completed_at'>): T | undefined {
  const completed = Date.parse(current.completed_at ?? '');
  if (!Number.isFinite(completed)) return undefined;
  return runs.filter(run => run.project_slug === current.project_slug && run.run_id !== current.run_id
    && run.status === 'complete' && run.solver_name?.toLowerCase().startsWith('magneto2d')
    && Date.parse(run.completed_at ?? '') < completed)
    .sort((a, b) => Date.parse(b.completed_at!) - Date.parse(a.completed_at!))[0];
}

const samples = (value: unknown): number[] => Array.isArray(value) ? value : [];

/** Older comparison responses use {} when an analysis has no CSV rows. */
export function normalizeComparisonResult(result: ComparisonResult): ComparisonResult {
  const cogging = result.cogging_torque_waveform;
  const coggingAngles = samples(cogging?.electrical_angle_deg);
  const coggingValues = samples(cogging?.torque_Nm);
  const hasCogging = coggingAngles.length >= 2 && coggingAngles.length === coggingValues.length
    && coggingAngles.every(Number.isFinite) && coggingValues.every(Number.isFinite);
  return {
    ...result,
    cogging_torque_waveform: hasCogging ? { ...cogging, electrical_angle_deg: coggingAngles, torque_Nm: coggingValues } : null,
    torque_waveform: {
      ...result.torque_waveform,
      electrical_angle_deg: samples(result.torque_waveform?.electrical_angle_deg),
      torque_Nm: samples(result.torque_waveform?.torque_Nm),
    },
    back_emf_waveform: {
      ...result.back_emf_waveform,
      electrical_angle_deg: samples(result.back_emf_waveform?.electrical_angle_deg),
      phase_a_V: samples(result.back_emf_waveform?.phase_a_V),
      phase_b_V: samples(result.back_emf_waveform?.phase_b_V),
      phase_c_V: samples(result.back_emf_waveform?.phase_c_V),
    },
  };
}

export interface ComparisonTimingRow {
  key: string;
  label: string;
  group: 'Elapsed time' | 'Work performed';
  unit: 's' | '';
  before: number | null;
  after: number | null;
}

const nonnegative = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const count = (value: unknown): number | null => Number.isInteger(value) ? nonnegative(value) : null;

/** Compare elapsed partitions, never the overlapping sums of worker stage times. */
export function compareRunTiming(before: ComparisonResult, after: ComparisonResult) {
  const a = isSolveTimeBreakdown(before.solve_metadata.time_breakdown) ? before.solve_metadata.time_breakdown : null;
  const b = isSolveTimeBreakdown(after.solve_metadata.time_breakdown) ? after.solve_metadata.time_breakdown : null;
  const rows: ComparisonTimingRow[] = [];
  if (a || b) {
    rows.push({ key: 'elapsed', label: 'Total elapsed', group: 'Elapsed time', unit: 's', before: nonnegative(a?.elapsed_s), after: nonnegative(b?.elapsed_s) });
    for (const [key, label] of [['meshing', 'Meshing'], ['field_solve', 'Field solve'], ['packaging', 'Packaging results']]) {
      rows.push({ key, label, group: 'Elapsed time', unit: 's',
        before: nonnegative(a?.elapsed_steps.find(step => step?.key === key)?.seconds),
        after: nonnegative(b?.elapsed_steps.find(step => step?.key === key)?.seconds) });
    }
  }
  const work = [
    ['mesh_elements', 'Mesh elements', before.solve_metadata.mesh_element_count, after.solve_metadata.mesh_element_count],
    ['rotor_positions', 'Rotor positions', before.solve_metadata.rotor_positions, after.solve_metadata.rotor_positions],
    ['meshes_built', 'Meshes generated', a?.counts?.meshes_built, b?.counts?.meshes_built],
    ['meshes_rotated', 'Meshes rotated', a?.counts?.meshes_rotated, b?.counts?.meshes_rotated],
    ['solves', 'Field solves', a?.counts?.solves, b?.counts?.solves],
    ['field_frames', 'Field frames', a?.counts?.field_frames, b?.counts?.field_frames],
  ] as const;
  for (const [key, label, left, right] of work) {
    if (count(left) !== null || count(right) !== null) rows.push({ key, label, group: 'Work performed', unit: '', before: count(left), after: count(right) });
  }
  return { recordedBefore: Boolean(a), recordedAfter: Boolean(b), rows };
}
