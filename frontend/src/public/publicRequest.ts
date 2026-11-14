import type { PublicMotorConfig } from './api';
import { applyPublicSolverSettings, type MotorConfig, type PublicSolverId } from './model';
import { torqueSpeedSettings } from './torqueSpeedAnalysis';
import { ensureLossesFullCycle } from './solvePlan';

/** The design as the local API's solve routes take it, with the public solver settings. A request
 * also gets the full-cycle sweep losses need; a saved setup records the plan as chosen. */
export function asPublicConfig(config: MotorConfig, solver: PublicSolverId = 'magneto2d', { lossesSweep = true } = {}): PublicMotorConfig {
  const thdAnalysis = config.solve_options.back_emf && (config.solve_params.solve_quality === 'standard'
    || config.solve_params.solve_quality === 'fine');
  const request = {
    ...applyPublicSolverSettings(config),
    torque_speed_analysis: solver !== 'elmer' && config.solve_options.torque_speed_envelope
      ? torqueSpeedSettings(config) : null,
    solve_options: {
      ...config.solve_options,
      // Keep the project's Magneto2D choice while omitting the unsupported
      // option from Elmer validation and solve requests, including imported designs.
      cogging_torque: solver !== 'elmer' && Boolean(config.solve_options.cogging_torque),
      losses_efficiency: solver !== 'elmer' && Boolean(config.solve_options.losses_efficiency),
      torque_speed_envelope: solver !== 'elmer' && Boolean(config.solve_options.torque_speed_envelope),
      thd_analysis: thdAnalysis,
    },
  };
  return (lossesSweep ? ensureLossesFullCycle(request) : request) as unknown as PublicMotorConfig;
}
