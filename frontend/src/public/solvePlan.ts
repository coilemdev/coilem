import type { MotorConfig, PublicSolverId, SolveQuality } from './model';

export type PublicSolvePreset = Exclude<SolveQuality, 'custom'>;

export interface PublicSweepSampling {
  rotor_sweep_range_deg: number;
  rotor_step_deg: number;
}

export const PUBLIC_CUSTOM_SWEEP_DEFAULT_STEP_DEG = 2;
export const PUBLIC_CUSTOM_SWEEP_MIN_STEP_DEG = 0.5;
export const PUBLIC_CUSTOM_SWEEP_MAX_STEP_DEG = 30;
export const PUBLIC_CUSTOM_SWEEP_RANGE_DEG = 360;

export const PUBLIC_DEFAULT_PRESET_SWEEP: PublicSweepSampling = {
  rotor_sweep_range_deg: 60,
  rotor_step_deg: 15,
};

export const PUBLIC_SOLVE_PLAN_MESH_DENSITY = {
  quick: 'coarse',
  standard: 'normal',
  fine: 'fine',
} as const satisfies Record<PublicSolvePreset, MotorConfig['solve_params']['mesh_density']>;

/** The Accuracy plan buttons: the three preset grids, and Maximum accuracy, which is High accuracy's grid
 * on the Very fine mesh. A plan is only these two settings, so saved setups, design files and the
 * backend need no new value. */
export type PublicSolvePlanChoice = PublicSolvePreset | 'very_fine';
export const PUBLIC_SOLVE_PLAN_SETTINGS = {
  quick: { solve_quality: 'quick', mesh_density: 'coarse' },
  standard: { solve_quality: 'standard', mesh_density: 'normal' },
  fine: { solve_quality: 'fine', mesh_density: 'fine' },
  very_fine: { solve_quality: 'fine', mesh_density: 'very_fine' },
} as const satisfies Record<PublicSolvePlanChoice, { solve_quality: PublicSolvePreset; mesh_density: MotorConfig['solve_params']['mesh_density'] }>;

/** The plan button a design's settings light up: Very fine for High accuracy's grid on the Very fine mesh. */
export function selectedSolvePlan(config: MotorConfig): PublicSolvePlanChoice | 'custom' {
  const { solve_quality: quality, mesh_density: mesh } = config.solve_params;
  return quality === 'fine' && mesh === 'very_fine' ? 'very_fine' : quality;
}

/** The step of a loss sweep whose plan does not already solve a full cycle: Preview keeps a
 * quick 15° grid and Standard its own 7.5°. High accuracy always solves a full cycle. */
const LOSSES_FULL_CYCLE_STEP_DEG: Record<PublicSolvePreset, number> = { quick: 15, standard: 7.5, fine: 3.75 };

/** Whether the backend already solves this plan's loaded sweep as a uniform 360° electrical
 * cycle: High accuracy always, and Standard with Back EMF (and its harmonics) or six-step drive. */
function planSolvesFullCycle(config: MotorConfig): boolean {
  const { solve_quality: quality, excitation_mode: mode } = config.solve_params;
  return quality === 'fine' || (quality === 'standard' && (config.solve_options.back_emf || mode === 'ideal_six_step_120'));
}

/**
 * Loss estimates need a uniform full cycle. A plan that already solves one is kept, with its own
 * step and harmonic analysis; any other plan is requested as 360° at its own step. This shapes
 * requests only, so the plan the user chose is never rewritten.
 */
export function ensureLossesFullCycle(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): MotorConfig {
  if (solver === 'elmer' || !config.solve_options.losses_efficiency || planSolvesFullCycle(config)) return config;
  const params = config.solve_params;
  const step = params.solve_quality !== 'custom' ? LOSSES_FULL_CYCLE_STEP_DEG[params.solve_quality]
    : Number.isFinite(params.rotor_step_deg) ? params.rotor_step_deg : PUBLIC_DEFAULT_PRESET_SWEEP.rotor_step_deg;
  const rotorStepDeg = Math.min(PUBLIC_CUSTOM_SWEEP_MAX_STEP_DEG, Math.max(PUBLIC_CUSTOM_SWEEP_MIN_STEP_DEG, step));
  if (params.solve_quality === 'custom' && params.rotor_sweep_range_deg === PUBLIC_CUSTOM_SWEEP_RANGE_DEG && params.rotor_step_deg === rotorStepDeg && !config.solve_options.thd_analysis) return config;
  return { ...config, solve_options: { ...config.solve_options, thd_analysis: false }, solve_params: { ...params, solve_quality: 'custom',
    rotor_sweep_range_deg: PUBLIC_CUSTOM_SWEEP_RANGE_DEG, rotor_step_deg: rotorStepDeg } };
}

export function capturePublicPresetSweep(config: MotorConfig): PublicSweepSampling {
  return {
    rotor_sweep_range_deg: config.solve_params.rotor_sweep_range_deg,
    rotor_step_deg: config.solve_params.rotor_step_deg,
  };
}

export function applyPublicCustomSweep(config: MotorConfig, requestedStepDeg: number): MotorConfig {
  const rotorStepDeg = Math.min(
    PUBLIC_CUSTOM_SWEEP_MAX_STEP_DEG,
    Math.max(PUBLIC_CUSTOM_SWEEP_MIN_STEP_DEG, requestedStepDeg),
  );
  return {
    ...config,
    solve_options: {
      ...config.solve_options,
      thd_analysis: false,
    },
    solve_params: {
      ...config.solve_params,
      solve_quality: 'custom',
      rotor_sweep_range_deg: PUBLIC_CUSTOM_SWEEP_RANGE_DEG,
      rotor_step_deg: rotorStepDeg,
    },
  };
}

export function applyPublicSolvePreset(
  config: MotorConfig,
  solvePlan: PublicSolvePlanChoice,
  presetSweep: PublicSweepSampling,
): MotorConfig {
  const settings = PUBLIC_SOLVE_PLAN_SETTINGS[solvePlan];
  return {
    ...config,
    solve_options: {
      ...config.solve_options,
      thd_analysis: config.solve_options.back_emf && (settings.solve_quality === 'standard' || settings.solve_quality === 'fine'),
    },
    solve_params: {
      ...config.solve_params,
      ...settings,
      ...presetSweep,
    },
  };
}
