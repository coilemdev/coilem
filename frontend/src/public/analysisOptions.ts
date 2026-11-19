import type { MotorConfig, PublicSolverId, SolveResult, SolveValidation } from './model';
import { torqueSpeedSettings } from './torqueSpeedAnalysis';

export type AnalysisKey = 'torque_sweep' | 'back_emf' | 'cogging_torque' | 'losses_efficiency' | 'rotor_iron_loss' | 'torque_speed_envelope';

export const ANALYSIS_LABELS: Record<AnalysisKey, string> = {
  torque_sweep: 'Torque',
  back_emf: 'Back EMF',
  cogging_torque: 'Cogging',
  losses_efficiency: 'Losses & efficiency',
  rotor_iron_loss: 'Rotor iron loss',
  torque_speed_envelope: 'Torque–speed map',
};

/** Why rotor iron loss cannot be computed for this design, or null when it can.
 * Mirrors `unavailable_reason` in backend/rotor_loss_solver.py, in the same order, so the
 * option is only offered where a run would produce the number. */
export function rotorIronLossUnavailableReason(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): string | null {
  const params = config.solve_params;
  if (solver === 'elmer') return 'Rotor iron loss is available with Magneto2D.';
  if (!(params.rated_speed_rpm > 0)) return 'Rotor iron loss needs a speed above zero.';
  if (params.symmetry !== 'full') return 'Rotor iron loss needs the full motor. Set Solved region to Full motor.';
  if ((config.rotor_layout ?? 'inner') !== 'inner') return 'Rotor iron loss is not available for outer-rotor motors yet.';
  if (config.topology === 'IPM' && config.rotor.ipm_topology !== 'flat_buried') {
    return 'Rotor iron loss is not available for V-shape IPM rotors yet.';
  }
  if (config.geometry_reference) return 'Rotor iron loss is not available for reference geometries yet.';
  if (config.materials.rotor_steel !== 'M350-50A') return 'Rotor iron loss needs M350-50A rotor steel.';
  if (params.excitation_mode !== 'sinusoidal') return 'Rotor iron loss needs sinusoidal drive.';
  if (params.nonlinear_solver !== 'newton') {
    return 'Rotor iron loss needs the Newton solver. Change Nonlinear solver in Advanced options.';
  }
  return null;
}

/** Whether a run of this design will compute rotor iron loss: chosen, with losses, and supported. */
export function rotorIronLossSelected(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): boolean {
  return Boolean(config.solve_options.losses_efficiency && config.solve_options.rotor_iron_loss)
    && rotorIronLossUnavailableReason(config, solver) === null;
}

/** Files, saved setups and requests carry only a rotor-loss stage this design can run. */
export function effectiveRotorLossOptions(config: MotorConfig, solver: PublicSolverId) {
  const options = { ...config.solve_options };
  if (!rotorIronLossSelected(config, solver)) delete options.rotor_iron_loss;
  return options;
}

export function selectedAnalyses(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): AnalysisKey[] {
  return (Object.keys(ANALYSIS_LABELS) as AnalysisKey[]).filter((key) => (
    key === 'rotor_iron_loss' ? rotorIronLossSelected(config, solver)
      : config.solve_options[key] && (solver !== 'elmer' || key === 'torque_sweep' || key === 'back_emf')
  ));
}

export function analysisSummary(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): string {
  return selectedAnalyses(config, solver).map((key) => ANALYSIS_LABELS[key]).join(' · ') || 'Select analyses';
}

/** A stored map, or the points a cancelled one finished, are reused, so only the rest are solved. */
function mapSolves(map: SolveValidation['torque_speed_map']): string {
  if (!map) return 'Map — solves';
  const remaining = map.solves_remaining ?? map.solves;
  if (remaining === map.solves) return `Map ${map.solves} solves`;
  return remaining === 0 ? 'Map stored' : `Map ${remaining} of ${map.solves} solves`;
}

export function analysisPositions(config: MotorConfig, validation: SolveValidation, solver: PublicSolverId): string {
  if (!validation.analysis_positions) return `${validation.sweep_positions} rotor positions`;
  return selectedAnalyses(config, solver).map((key) => key === 'torque_speed_envelope'
    ? mapSolves(validation.torque_speed_map)
    : `${ANALYSIS_LABELS[key]} ${validation.analysis_positions?.[key] ?? '—'}`).join(' · ');
}

export function setAnalysisOption(config: MotorConfig, key: AnalysisKey, enabled: boolean): MotorConfig {
  const options = { ...config.solve_options, [key]: enabled };
  if (key === 'rotor_iron_loss' && enabled) options.losses_efficiency = true;
  if (key === 'losses_efficiency' && !enabled) delete options.rotor_iron_loss;
  options.thd_analysis = options.back_emf && (config.solve_params.solve_quality === 'standard' || config.solve_params.solve_quality === 'fine');
  return {
    ...config, solve_options: options,
    ...(key === 'torque_speed_envelope' && enabled ? { torque_speed_analysis: torqueSpeedSettings(config) } : {}),
  };
}

export function hasTorqueResult(result: Pick<SolveResult, 'summary' | 'solve_metadata'>): boolean {
  return result.solve_metadata.torque_sweep_computed !== false && typeof result.summary.avg_torque_Nm === 'number';
}

export function hasBackEmfResult(result: Pick<SolveResult, 'summary' | 'solve_metadata'>): boolean {
  return result.solve_metadata.back_emf_computed !== false && typeof result.summary.back_emf_fundamental_V === 'number';
}

export function defaultResultPlot(result: SolveResult): 'torque' | 'back-emf' | 'cogging' | 'field-map' | 'performance' {
  if (hasTorqueResult(result)) return 'torque';
  if (hasBackEmfResult(result)) return 'back-emf';
  if (result.summary.cogging && result.cogging_torque_waveform) return 'cogging';
  if (result.torque_speed_analysis) return 'performance';
  return 'field-map';
}
