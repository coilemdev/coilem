import type { MotorConfig } from './model';

type SolveParams = MotorConfig['solve_params'];
export interface ExcitationDrafts {
  sinusoidal: { currentAmplitudeA: number; currentConvention: 'rms' | 'peak'; currentAngleDeg: number };
  sixStep: { currentAmplitudeA: number; commutationAdvanceDeg: number };
}

/** A loaded project's active mode owns its values; its other mode starts fresh. */
export function createExcitationDrafts(config: MotorConfig, defaults: MotorConfig): ExcitationDrafts {
  const sine = config.solve_params.excitation_mode === 'sinusoidal' ? config.solve_params : defaults.solve_params;
  const sixStep = config.solve_params.excitation_mode === 'ideal_six_step_120' ? config.solve_params : defaults.solve_params;
  return {
    sinusoidal: {
      currentAmplitudeA: sine.current_amplitude_A,
      currentConvention: sine.current_amplitude_convention === 'peak' ? 'peak' : 'rms',
      currentAngleDeg: sine.current_angle_deg,
    },
    sixStep: {
      currentAmplitudeA: sixStep.current_amplitude_A,
      commutationAdvanceDeg: config.solve_params.excitation_mode === 'ideal_six_step_120' ? sixStep.commutation_advance_deg : 0,
    },
  };
}

export function switchExcitationMode(config: MotorConfig, mode: SolveParams['excitation_mode'], drafts: ExcitationDrafts) {
  if (mode === config.solve_params.excitation_mode) return { config, drafts };
  const current = config.solve_params;
  if (mode === 'ideal_six_step_120') {
    return {
      drafts: { ...drafts, sinusoidal: {
        currentAmplitudeA: current.current_amplitude_A,
        currentConvention: current.current_amplitude_convention === 'peak' ? 'peak' as const : 'rms' as const,
        currentAngleDeg: current.current_angle_deg,
      } },
      config: { ...config, solve_params: { ...current,
        excitation_mode: mode, current_amplitude_A: drafts.sixStep.currentAmplitudeA,
        current_amplitude_convention: 'plateau' as const, current_angle_deg: 0,
        commutation_advance_deg: drafts.sixStep.commutationAdvanceDeg, phase_connection: 'wye' as const,
      } },
    };
  }
  return {
    drafts: { ...drafts, sixStep: {
      currentAmplitudeA: current.current_amplitude_A,
      commutationAdvanceDeg: current.commutation_advance_deg,
    } },
    config: { ...config, solve_params: { ...current,
      excitation_mode: mode, current_amplitude_A: drafts.sinusoidal.currentAmplitudeA,
      current_amplitude_convention: drafts.sinusoidal.currentConvention,
      current_angle_deg: drafts.sinusoidal.currentAngleDeg, commutation_advance_deg: 0,
    } },
  };
}
