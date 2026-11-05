import type { MotorConfig } from './model';
import { PYLEECAN_REFERENCE_NOTICE } from './pyleecanReferenceNotice';

// Saved with standalone LRK designs and regenerated on save.
export const LRK_REFERENCE_NOTICE = {
  source: 'Published LRK 12s/14p sliding-band benchmark model (WholeMotor.fem)',
  source_sha256: 'e69cce40a56f0c9840892a122cda86e5b3fa69d0b0c6ccc718d4d430b059253e',
  modification_notice: 'Adapted by coilEM: the stator is turned +15 degrees with circuits B and C relabelled so the published winding matches the generic 12s/14p tooth-coil map; arcs at the magnet face and slot bottom separate the air gap and stator teeth. Published geometry, winding, steel B-H points (lamination fill folded into B) and magnet properties are retained.',
  affiliation_notice: 'Adapted from a published LRK sliding-band benchmark model. No affiliation with or endorsement by its authors.',
} as const;

export type PublishedReferenceId = NonNullable<MotorConfig['geometry_reference']>;

/** What the UI says and keeps fixed for one pinned published design. */
export interface PublishedReference {
  /** Registered cases and the magnet temperature each one fixes (null: none). */
  cases: Record<string, { magnetTemperatureC: number | null }>;
  /** True when the reference also opens without a case, with its operating point set in Solve. */
  caseOptional: boolean;
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
    caseOptional: false,
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
  lrk_12s14p: {
    cases: { 'lrk-12s14p-fixed-current-v1': { magnetTemperatureC: null } },
    caseOptional: true,
    shortName: 'LRK',
    designNotice: 'Published LRK geometry, winding and materials are fixed. Change operating conditions and accuracy in Solve.',
    healthCopy: 'Exact published outer-rotor drawing; geometry is fixed for this software reference.',
    solveNotice: (config) => (config.reference_case
      ? 'LRK benchmark · fixed phase currents A/B/C = 0 / −4 / +4 A at every rotor position, as in the published comparison. The current settings below are not used.'
      : 'LRK software reference · outer rotor · operating point from the settings below. This model does not validate hardware.'),
    affiliationNotice: LRK_REFERENCE_NOTICE.affiliation_notice,
    fileNotice: LRK_REFERENCE_NOTICE,
    currentAngleLabel: 'Current angle',
    phaseCurrentConvention: 'q_axis',
    // The outer rotor reaches 1.2 stator radii.
    cameraOffset: (radius) => [radius * 2.95, radius * 2.15, radius * 3.25],
  },
};

export function publishedReference(config: Pick<MotorConfig, 'geometry_reference'> | null | undefined): PublishedReference | null {
  const id = config?.geometry_reference;
  return id ? PUBLISHED_REFERENCES[id] ?? null : null;
}
