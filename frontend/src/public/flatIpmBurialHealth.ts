import type { MotorConfig } from './model';

export const PUBLIC_FLAT_IPM_HARD_INNER_WEB_MIN_MM = 0.5;
export const PUBLIC_FLAT_IPM_ADVISORY_INNER_WEB_MIN_MM = 1.5;
export const PUBLIC_FLAT_IPM_ADVISORY_RADIAL_BUILD_FRACTION = 0.05;

export interface PublicFlatIpmBurialHealth {
  severity: 'positive' | 'warning';
  title: string;
  copy: string;
  blocking: boolean;
  remainingInnerWebMm: number;
  advisoryInnerWebMm: number;
}

/**
 * Radial centerline of a straight flat-IPM magnet and its clearance pocket.
 * Keep this identical to backend.geometry_drawer.magnet_radial_center_mm so
 * the public 3D assembly, 2D solver geometry, and Design Health all show the
 * same configured minimum outer bridge.
 */
export function publicFlatIpmMagnetCenterRadiusMm(config: MotorConfig): number {
  const pocketClearanceMm = config.rotor.pocket_clearance_mm ?? 0;
  const pocketHalfWidthMm = config.rotor.magnet_width_mm / 2 + pocketClearanceMm;
  const pocketHalfDepthMm = config.rotor.magnet_thickness_mm / 2 + pocketClearanceMm;
  const outerCornerRadiusMm = config.rotor.OD_mm / 2 - config.rotor.bridge_thickness_mm;
  const centerOuterFaceRadiusMm = Math.sqrt(Math.max(
    0,
    outerCornerRadiusMm ** 2 - pocketHalfWidthMm ** 2,
  ));
  return centerOuterFaceRadiusMm - pocketHalfDepthMm;
}

/**
 * Screen a straight flat-IPM pocket against the rotor ID.
 *
 * This is deliberately a geometry check, not a rotor-stress claim. The hard
 * 0.5 mm margin matches backend geometry validation. The larger advisory
 * margin gives Design Health an early warning and scales modestly with the
 * rotor's radial build.
 */
export function publicFlatIpmBurialHealth(
  config: MotorConfig,
): PublicFlatIpmBurialHealth | null {
  if (
    config.topology !== 'IPM'
    || config.rotor.ipm_topology !== 'flat_buried'
    || config.rotor.flat_buried_magnet_shape !== 'straight'
  ) {
    return null;
  }

  const rotorOuterRadiusMm = config.rotor.OD_mm / 2;
  const rotorInnerRadiusMm = (config.rotor.ID_mm ?? 0) / 2;
  const radialBuildMm = Math.max(0, rotorOuterRadiusMm - rotorInnerRadiusMm);
  const pocketClearanceMm = config.rotor.pocket_clearance_mm ?? 0;
  const magnetCenterRadiusMm = publicFlatIpmMagnetCenterRadiusMm(config);
  const pocketInnerRadiusMm = magnetCenterRadiusMm
    - config.rotor.magnet_thickness_mm / 2
    - pocketClearanceMm;
  const remainingInnerWebMm = pocketInnerRadiusMm - rotorInnerRadiusMm;
  const advisoryInnerWebMm = Math.max(
    PUBLIC_FLAT_IPM_ADVISORY_INNER_WEB_MIN_MM,
    radialBuildMm * PUBLIC_FLAT_IPM_ADVISORY_RADIAL_BUILD_FRACTION,
  );
  const outerBridge = `${config.rotor.bridge_thickness_mm.toFixed(2)} mm outer bridge`;
  const remaining = `${remainingInnerWebMm.toFixed(2)} mm inner web`;

  if (config.rotor.bridge_thickness_mm <= 0) {
    return {
      severity: 'warning',
      title: 'Outer bridge must be positive',
      copy: 'Flat-buried IPM pockets require steel between the nearest pocket corner and the rotor surface. Increase Outer Bridge before solving.',
      blocking: true,
      remainingInnerWebMm,
      advisoryInnerWebMm,
    };
  }

  if (remainingInnerWebMm <= PUBLIC_FLAT_IPM_HARD_INNER_WEB_MIN_MM) {
    return {
      severity: 'warning',
      title: 'Outer bridge reaches the inner rotor margin',
      copy: `${outerBridge} leaves ${remaining}. Geometry requires more than ${PUBLIC_FLAT_IPM_HARD_INNER_WEB_MIN_MM.toFixed(2)} mm; reduce the outer bridge or magnet thickness.`,
      blocking: true,
      remainingInnerWebMm,
      advisoryInnerWebMm,
    };
  }

  if (remainingInnerWebMm < advisoryInnerWebMm) {
    return {
      severity: 'warning',
      title: 'Outer bridge leaves a narrow inner web',
      copy: `${outerBridge} leaves ${remaining}. The geometry review target is at least ${advisoryInnerWebMm.toFixed(2)} mm. This is not a structural-stress calculation.`,
      blocking: false,
      remainingInnerWebMm,
      advisoryInnerWebMm,
    };
  }

  return {
    severity: 'positive',
    title: 'Outer bridge fits the rotor',
    copy: `${outerBridge} leaves ${remaining}. Geometry screen passed; mechanical stress still depends on speed, materials, and pocket details.`,
    blocking: false,
    remainingInnerWebMm,
    advisoryInnerWebMm,
  };
}
