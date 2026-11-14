import type { SolveResult } from './model';

/** The comparison route omits fields, playback and other heavy results. */
export type ComparisonResult = Pick<SolveResult, 'summary' | 'solve_metadata' | 'torque_waveform' | 'back_emf_waveform'>;

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
  return {
    ...result,
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
