import type { MotorConfig } from './model';
import { coilsPerPhase, concentratedUsesToothCoils } from './toothCoils';

// backend/models/config.py WindingConfig.parallel_paths le=32 (#91).
const MAX_PARALLEL_PATHS = 32;

export { coilsPerPhase, concentratedUsesToothCoils } from './toothCoils';

/** The largest parallel-path count up to `current` that divides the coils per phase; 1 when none does. */
export function parallelPathsDividing(coilsPerPhaseCount: number, current: number): number {
  return Array.from(
    { length: Math.min(MAX_PARALLEL_PATHS, coilsPerPhaseCount) },
    (_, index) => index + 1,
  )
    .filter((candidate) => coilsPerPhaseCount % candidate === 0)
    .reverse()
    .find((candidate) => candidate <= current) ?? 1;
}

/**
 * The winding after Winding → Type changes. Concentrated layouts with q >= 1 wind
 * one phase per slot in one layer only (backend/magneto2d_adapter rejects a second),
 * so the two layers a distributed winding carries over drop to one. The parallel
 * paths stay a divisor of the new coils per phase.
 */
export function windingForType(
  config: MotorConfig,
  type: MotorConfig['winding']['type'],
): MotorConfig['winding'] {
  const { slot_count: slotCount } = config.stator;
  const { pole_count: poleCount } = config.rotor;
  const layers = type === 'concentrated' && !concentratedUsesToothCoils(slotCount, poleCount)
    ? 1
    : config.winding.layers;
  const typeCoilsPerPhase = coilsPerPhase(slotCount, poleCount, type, layers);
  return {
    ...config.winding,
    type,
    layers,
    parallel_paths: typeCoilsPerPhase > 0
      ? parallelPathsDividing(typeCoilsPerPhase, config.winding.parallel_paths)
      : config.winding.parallel_paths,
  };
}
