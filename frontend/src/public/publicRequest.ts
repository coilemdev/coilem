import type { PublicMotorConfig } from './api';
import { applyPublicSolverSettings, type MotorConfig } from './model';

/** The design as the local API's solve routes take it, with the public solver settings. */
export function asPublicConfig(config: MotorConfig): PublicMotorConfig {
  const thdAnalysis = config.solve_params.solve_quality === 'standard'
    || config.solve_params.solve_quality === 'fine';
  return {
    ...applyPublicSolverSettings(config),
    solve_options: {
      ...config.solve_options,
      cogging_torque: Boolean(config.solve_options.cogging_torque),
      thd_analysis: thdAnalysis,
    },
  } as unknown as PublicMotorConfig;
}
