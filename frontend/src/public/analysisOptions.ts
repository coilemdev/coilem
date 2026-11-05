import type { MotorConfig, PublicSolverId, SolveResult, SolveValidation } from './model';
import { torqueSpeedSettings } from './torqueSpeedAnalysis';

export type AnalysisKey = 'torque_sweep' | 'back_emf' | 'cogging_torque' | 'losses_efficiency' | 'torque_speed_envelope';

export const ANALYSIS_LABELS: Record<AnalysisKey, string> = {
  torque_sweep: 'Torque',
  back_emf: 'Back EMF',
  cogging_torque: 'Cogging',
  losses_efficiency: 'Losses & efficiency',
  torque_speed_envelope: 'Torque–speed map',
};

export function selectedAnalyses(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): AnalysisKey[] {
  return (Object.keys(ANALYSIS_LABELS) as AnalysisKey[]).filter((key) => (
    config.solve_options[key] && (solver !== 'elmer' || key === 'torque_sweep' || key === 'back_emf')
  ));
}

export function analysisSummary(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): string {
  return selectedAnalyses(config, solver).map((key) => ANALYSIS_LABELS[key]).join(' · ') || 'Select analyses';
}

export function analysisPositions(config: MotorConfig, validation: SolveValidation, solver: PublicSolverId): string {
  if (!validation.analysis_positions) return `${validation.sweep_positions} rotor positions`;
  return selectedAnalyses(config, solver).map((key) => key === 'torque_speed_envelope'
    ? `Map ${validation.torque_speed_map?.solves ?? '—'} solves`
    : `${ANALYSIS_LABELS[key]} ${validation.analysis_positions?.[key] ?? '—'}`).join(' · ');
}

export function setAnalysisOption(config: MotorConfig, key: AnalysisKey, enabled: boolean): MotorConfig {
  const options = { ...config.solve_options, [key]: enabled };
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
