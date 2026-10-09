import type { MotorConfig, Topology } from './model';

export const PUBLIC_AIRGAP_LAUNCH_MIN_MM = 0.3;
export const PUBLIC_AIRGAP_PRACTICAL_MIN_MM = 0.5;
export const PUBLIC_AIRGAP_PRACTICAL_MAX_MM = 1.5;
export const PUBLIC_AIRGAP_LARGE_MM = 2;
const PUBLIC_MIN_ROTOR_OD_MM = 15;
const PUBLIC_MAX_ROTOR_OD_MM = 450;
const PUBLIC_MIN_MAGNET_THICKNESS_MM = 2;
const PUBLIC_MAX_MAGNET_THICKNESS_MM = 50;

export interface PublicAirgapHealth {
  severity: 'positive' | 'warning';
  title: string;
  copy: string;
}

/**
 * Radius of the rotating surface that faces the stator bore.
 *
 * Surface magnets extend beyond the rotor steel. Buried magnets do not, so an
 * IPM's mechanical airgap starts at the rotor-steel OD.
 */
export function rotorAirgapBoundaryRadiusMm(config: MotorConfig): number {
  return config.rotor.OD_mm / 2
    + (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0);
}

export function magneticAirgapMm(config: MotorConfig): number {
  return Math.max(0, config.stator.ID_mm / 2 - rotorAirgapBoundaryRadiusMm(config));
}

/**
 * Change topology without silently converting a practical SPM clearance into
 * an oversized IPM clearance (or vice versa).
 */
export function changeTopologyPreservingAirgap(
  config: MotorConfig,
  topology: Topology,
): MotorConfig {
  if (topology === config.topology) return config;
  const airgapMm = magneticAirgapMm(config);
  const desiredBoundaryOdMm = config.stator.ID_mm - 2 * airgapMm;
  const maximumBoundaryOdMm = Math.min(
    PUBLIC_MAX_ROTOR_OD_MM,
    config.stator.ID_mm - 2 * PUBLIC_AIRGAP_LAUNCH_MIN_MM,
  );
  let magnetThicknessMm = Math.min(
    PUBLIC_MAX_MAGNET_THICKNESS_MM,
    Math.max(PUBLIC_MIN_MAGNET_THICKNESS_MM, config.rotor.magnet_thickness_mm),
  );
  let rotorOdMm: number;
  if (topology === 'SPM') {
    const minimumBoundaryOdMm = PUBLIC_MIN_ROTOR_OD_MM
      + 2 * PUBLIC_MIN_MAGNET_THICKNESS_MM;
    const boundaryOdMm = Math.min(
      maximumBoundaryOdMm,
      Math.max(minimumBoundaryOdMm, desiredBoundaryOdMm),
    );
    const maximumThicknessMm = Math.min(
      PUBLIC_MAX_MAGNET_THICKNESS_MM,
      (boundaryOdMm - PUBLIC_MIN_ROTOR_OD_MM) / 2,
      boundaryOdMm / 6,
    );
    magnetThicknessMm = Math.min(magnetThicknessMm, maximumThicknessMm);
    rotorOdMm = boundaryOdMm - 2 * magnetThicknessMm;
  } else {
    rotorOdMm = Math.min(
      maximumBoundaryOdMm,
      Math.max(PUBLIC_MIN_ROTOR_OD_MM, desiredBoundaryOdMm),
    );
    magnetThicknessMm = Math.min(magnetThicknessMm, rotorOdMm / 4);
  }
  const rotorIdMm = config.rotor.ID_mm === null
    ? null
    : Math.min(config.rotor.ID_mm, Math.max(0, rotorOdMm - 0.1));
  return {
    ...config,
    topology,
    rotor: {
      ...config.rotor,
      OD_mm: Number(rotorOdMm.toFixed(6)),
      ID_mm: rotorIdMm === null ? null : Number(rotorIdMm.toFixed(6)),
      magnet_thickness_mm: Number(magnetThicknessMm.toFixed(6)),
    },
  };
}

export function publicAirgapHealth(airgapMm: number): PublicAirgapHealth {
  const measured = `Calculated magnetic airgap is ${airgapMm.toFixed(2)} mm.`;
  if (airgapMm < PUBLIC_AIRGAP_LAUNCH_MIN_MM) {
    return {
      severity: 'warning',
      title: 'Airgap is below the launch minimum',
      copy: `${measured} At least ${PUBLIC_AIRGAP_LAUNCH_MIN_MM.toFixed(2)} mm is required.`,
    };
  }
  if (airgapMm < PUBLIC_AIRGAP_PRACTICAL_MIN_MM) {
    return {
      severity: 'warning',
      title: 'Airgap is tighter than recommended',
      copy: `${measured} The current practical range is ${PUBLIC_AIRGAP_PRACTICAL_MIN_MM.toFixed(2)}–${PUBLIC_AIRGAP_PRACTICAL_MAX_MM.toFixed(2)} mm.`,
    };
  }
  if (airgapMm <= PUBLIC_AIRGAP_PRACTICAL_MAX_MM) {
    return {
      severity: 'positive',
      title: 'Airgap is in the practical range',
      copy: `${measured} Recommended range ${PUBLIC_AIRGAP_PRACTICAL_MIN_MM.toFixed(2)}–${PUBLIC_AIRGAP_PRACTICAL_MAX_MM.toFixed(2)} mm.`,
    };
  }
  if (airgapMm <= PUBLIC_AIRGAP_LARGE_MM) {
    return {
      severity: 'warning',
      title: 'Airgap is larger than typical',
      copy: `${measured} Expect lower airgap flux and torque per ampere; review the mechanical need.`,
    };
  }
  return {
    severity: 'warning',
    title: 'Airgap is substantially oversized',
    copy: `${measured} It can solve, but expect a material reduction in airgap flux and torque per ampere.`,
  };
}
