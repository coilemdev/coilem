import type { MotorConfig } from './model';

/**
 * The fraction of each pole that the magnets cover, as the geometry builds them.
 *
 * A surface (SPM) magnet's width is an arc at its radial centre, the rotor
 * radius plus half the magnet thickness (backend geometry_drawer
 * `magnet_radial_center_mm`), so its coverage follows from the width alone:
 * `magnet_embrace` does not shape an SPM rotor. Other rotors keep their
 * stored coverage.
 */
export function magnetPoleCoverage(
  config: Pick<MotorConfig, 'topology' | 'rotor'>,
): number {
  if (config.topology !== 'SPM') return config.rotor.magnet_embrace;
  const centreRadiusMm = config.rotor.OD_mm / 2 + config.rotor.magnet_thickness_mm / 2;
  const polePitchMm = config.rotor.pole_count > 0
    ? (2 * Math.PI * centreRadiusMm) / config.rotor.pole_count
    : 0;
  return polePitchMm > 0 ? config.rotor.magnet_width_mm / polePitchMm : 0;
}

/** Whole-percent coverage for labels. */
export function magnetPoleCoveragePct(config: Pick<MotorConfig, 'topology' | 'rotor'>): number {
  return Math.round(magnetPoleCoverage(config) * 100);
}
