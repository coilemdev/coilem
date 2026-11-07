import type { MotorConfig } from './model';
import { PYLEECAN_REFERENCE_NOTICE } from './pyleecanReferenceNotice';

export type PublishedReferenceId = NonNullable<MotorConfig['geometry_reference']>;

/** What the UI says and keeps fixed for one pinned published design. */
export interface PublishedReference {
  /** Registered cases and the magnet temperature each one fixes (null: none). */
  cases: Record<string, { magnetTemperatureC: number | null }>;
  /** Shown where the design-health card would otherwise show magnet coverage. */
  shortName: string;
  designNotice: string;
  healthCopy: string;
  solveNotice: (config: MotorConfig) => string;
  /** Upstream attribution shown in Design and Solve, or null. */
  affiliationNotice: string | null;
  /** Notice regenerated into every saved design file, or null. */
  fileNotice: object | null;
  currentAngleLabel: string;
  phaseCurrentConvention: 'pyleecan_d_axis' | 'q_axis';
  /** 3D camera offset for the reference's own proportions, or null for the default framing. */
  cameraOffset: ((radiusMm: number) => [number, number, number]) | null;
}

export const PUBLISHED_REFERENCES: Record<PublishedReferenceId, PublishedReference> = {
  pyleecan_prius_2004: {
    cases: {
      'prius-2004-tutorial-bemf-v1': { magnetTemperatureC: 20 },
      'prius-2004-loaded-torque-v1': { magnetTemperatureC: 60 },
    },
    shortName: 'Pyleecan',
    designNotice: 'Published Pyleecan geometry, winding and materials are fixed. Change operating conditions and accuracy in Solve.',
    healthCopy: 'Analytic SlotW11 and HoleM50 curves; geometry is fixed for this software reference.',
    solveNotice: (config) => `Pyleecan software reference · ${config.solve_params.magnet_temperature_C}°C magnets · sinusoidal phase current. Φ₀ uses the published d-axis convention. This case does not validate ORNL hardware.`,
    affiliationNotice: PYLEECAN_REFERENCE_NOTICE.affiliation_notice,
    fileNotice: PYLEECAN_REFERENCE_NOTICE,
    currentAngleLabel: 'Pyleecan Φ₀ (d-axis)',
    phaseCurrentConvention: 'pyleecan_d_axis',
    cameraOffset: (radius) => [radius * 1.35, -radius * 1.65, radius * 3.6],
  },
};

export function publishedReference(config: Pick<MotorConfig, 'geometry_reference'> | null | undefined): PublishedReference | null {
  const id = config?.geometry_reference;
  return id ? PUBLISHED_REFERENCES[id] ?? null : null;
}
