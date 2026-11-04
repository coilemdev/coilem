import type { SolveResult } from './model';

/** The comparison route omits fields, playback and other heavy results. */
export type ComparisonResult = Pick<SolveResult, 'summary' | 'solve_metadata' | 'torque_waveform' | 'back_emf_waveform'>;

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
