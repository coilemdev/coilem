import type { MotorConfig, SolveQuality } from './model';

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
  solvePlan: PublicSolvePreset,
  presetSweep: PublicSweepSampling,
): MotorConfig {
  return {
    ...config,
    solve_options: {
      ...config.solve_options,
      thd_analysis: solvePlan === 'standard' || solvePlan === 'fine',
    },
    solve_params: {
      ...config.solve_params,
      solve_quality: solvePlan,
      mesh_density: PUBLIC_SOLVE_PLAN_MESH_DENSITY[solvePlan],
      ...presetSweep,
    },
  };
}
