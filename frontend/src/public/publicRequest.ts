import type { PublicMotorConfig } from './api';
import { applyPublicSolverSettings, type MotorConfig, type PublicSolverId } from './model';

/** The design as the local API's solve routes take it, with the public solver settings. */
export function asPublicConfig(config: MotorConfig, solver: PublicSolverId = 'magneto2d'): PublicMotorConfig {
  const thdAnalysis = config.solve_params.solve_quality === 'standard'
    || config.solve_params.solve_quality === 'fine';
  return {
    ...applyPublicSolverSettings(config),
    solve_options: {
      ...config.solve_options,
      // Keep the project's Magneto2D choice while omitting the unsupported
      // option from Elmer validation and solve requests, including imported designs.
      cogging_torque: solver !== 'elmer' && Boolean(config.solve_options.cogging_torque),
      thd_analysis: thdAnalysis,
    },
  } as unknown as PublicMotorConfig;
}
