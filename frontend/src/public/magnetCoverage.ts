import { publicFlatIpmMagnetCenterRadiusMm } from './flatIpmBurialHealth';
import type { MotorConfig } from './model';

/**
 * The fraction of each pole that the magnets cover, as the geometry builds them.
 *
 * A surface (SPM) or flat-buried IPM magnet's width is taken at its radial
 * centre (backend geometry_drawer `magnet_radial_center_mm`), so its coverage
 * follows from the width alone: `magnet_embrace` shapes neither rotor, and the
 * backend notes a saved value that differs (input_advisories.py). Other rotors
 * keep their stored coverage.
 */
export function magnetPoleCoverage(
  config: Pick<MotorConfig, 'topology' | 'rotor' | 'rotor_layout'>,
): number {
  const flatIpm = config.topology === 'IPM' && config.rotor.ipm_topology === 'flat_buried';
  if (config.topology !== 'SPM' && !flatIpm) return config.rotor.magnet_embrace;
  const centreRadiusMm = flatIpm
    ? config.rotor.flat_buried_magnet_shape === 'legacy_arc'
      ? config.rotor.OD_mm / 2 - config.rotor.bridge_thickness_mm - (config.rotor.pocket_clearance_mm ?? 0) - config.rotor.magnet_thickness_mm / 2
      : publicFlatIpmMagnetCenterRadiusMm(config as MotorConfig)
    // An outer rotor's magnets sit inside its seat (rotor ID), not outside its OD.
    : config.rotor_layout === 'outer'
      ? (config.rotor.ID_mm ?? 0) / 2 - config.rotor.magnet_thickness_mm / 2
      : config.rotor.OD_mm / 2 + config.rotor.magnet_thickness_mm / 2;
  const polePitchMm = config.rotor.pole_count > 0
    ? (2 * Math.PI * centreRadiusMm) / config.rotor.pole_count
    : 0;
  return polePitchMm > 0 ? config.rotor.magnet_width_mm / polePitchMm : 0;
}

/** Whole-percent coverage for labels. */
export function magnetPoleCoveragePct(config: Pick<MotorConfig, 'topology' | 'rotor' | 'rotor_layout'>): number {
  return Math.round(magnetPoleCoverage(config) * 100);
}

/** V-shape coverage needs the slab geometry; its saved embrace is not an estimate. */
export function hasPoleCoverageEstimate(config: Pick<MotorConfig, 'topology' | 'rotor'>): boolean {
  return config.topology !== 'IPM' || config.rotor.ipm_topology !== 'v_shape';
}
