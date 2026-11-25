import type { MotorConfig } from './model';

type SolveParams = MotorConfig['solve_params'];
type Mode = SolveParams['excitation_mode'];
export interface ExcitationDrafts {
  sinusoidal: { currentAmplitudeA: number; currentConvention: 'rms' | 'peak'; currentAngleDeg: number };
  sixStep: { currentAmplitudeA: number; commutationAdvanceDeg: number };
  /** The last switch: the drive it left and the current it set, so switching straight back returns the exact value. */
  last?: { from: Mode; setAmplitudeA: number };
}

/** Four significant figures for a converted current: 30 A rms is a 42.43 A peak, not 42.42640687. */
const tidy = (amps: number) => Number(amps.toPrecision(4));
/** The peak phase current of an operating point: a six-step plateau is its peak. */
const peakA = (params: SolveParams) => (params.current_amplitude_convention === 'rms' ? params.current_amplitude_A * Math.SQRT2 : params.current_amplitude_A);

/**
 * What each drive remembers for a project. Switching the drive keeps the current: the other
 * drive starts at the same peak current (a six-step plateau is a sinusoidal peak of the same
 * value). Each drive keeps its own angle or advance. Nothing is carried over from a project
 * that was open before.
 */
export function createExcitationDrafts(config: MotorConfig, _defaults: MotorConfig): ExcitationDrafts {
  const params = config.solve_params;
  const sixStep = params.excitation_mode === 'ideal_six_step_120';
  return {
    sinusoidal: sixStep
      ? { currentAmplitudeA: params.current_amplitude_A, currentConvention: 'peak', currentAngleDeg: 0 }
      : { currentAmplitudeA: params.current_amplitude_A, currentConvention: params.current_amplitude_convention === 'peak' ? 'peak' : 'rms', currentAngleDeg: params.current_angle_deg },
    sixStep: {
      currentAmplitudeA: sixStep ? params.current_amplitude_A : tidy(peakA(params)),
      commutationAdvanceDeg: sixStep ? params.commutation_advance_deg : 0,
    },
  };
}

export function switchExcitationMode(config: MotorConfig, mode: Mode, drafts: ExcitationDrafts) {
  if (mode === config.solve_params.excitation_mode) return { config, drafts };
  const current = config.solve_params;
  // Switching straight back with the current untouched returns the exact value it had, with no rounding
  // from the conversion there and back. Otherwise the present current carries over at the same peak.
  const untouched = drafts.last?.from === mode && drafts.last.setAmplitudeA === current.current_amplitude_A;
  if (mode === 'ideal_six_step_120') {
    const amplitude = untouched ? drafts.sixStep.currentAmplitudeA : tidy(peakA(current));
    return {
      drafts: { ...drafts, sinusoidal: {
        currentAmplitudeA: current.current_amplitude_A,
        currentConvention: current.current_amplitude_convention === 'peak' ? 'peak' as const : 'rms' as const,
        currentAngleDeg: current.current_angle_deg,
      }, last: { from: current.excitation_mode, setAmplitudeA: amplitude } },
      config: { ...config, solve_params: { ...current,
        excitation_mode: mode, current_amplitude_A: amplitude,
        current_amplitude_convention: 'plateau' as const, current_angle_deg: 0,
        commutation_advance_deg: drafts.sixStep.commutationAdvanceDeg, phase_connection: 'wye' as const,
      } },
    };
  }
  const convention = drafts.sinusoidal.currentConvention;
  const amplitude = untouched ? drafts.sinusoidal.currentAmplitudeA
    : convention === 'rms' ? tidy(current.current_amplitude_A / Math.SQRT2) : current.current_amplitude_A;
  return {
    drafts: { ...drafts, sixStep: {
      currentAmplitudeA: current.current_amplitude_A,
      commutationAdvanceDeg: current.commutation_advance_deg,
    }, last: { from: current.excitation_mode, setAmplitudeA: amplitude } },
    config: { ...config, solve_params: { ...current,
      excitation_mode: mode, current_amplitude_A: amplitude,
      current_amplitude_convention: convention,
      current_angle_deg: drafts.sinusoidal.currentAngleDeg, commutation_advance_deg: 0,
    } },
  };
}
