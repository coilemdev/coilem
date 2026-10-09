// Tier 1 — Lesson 2: The Magnetic Circuit & the Airgap.
//
// Shared constants, lightweight math helpers, and the lesson manifest for the
// magnetic-circuit lesson. This lesson reuses Lesson 1's mesh/solve pipeline
// (see frontend/src/components/LearningLessons.tsx) and adds no backend work;
// everything here is teaching metadata + analysis of solved field frames.

import type {
  AirgapBrBtProfile,
  AirgapFieldStats,
} from './lessonSolveTypes';

export type MagneticCircuitStage = 'design' | 'mesh' | 'solve';
export type MagneticCircuitOverlay = 'flux-path' | 'budget' | 'airgap-flux' | 'saturation';

export type MagneticCircuitDesignKey = 'airgapMm' | 'magnetArcPct' | 'magnetThicknessMm';

export interface MagneticCircuitDesignSettings {
  airgapMm: number;
  magnetArcPct: number;
  magnetThicknessMm: number;
}

export interface MagneticCircuitDesignField {
  key: MagneticCircuitDesignKey;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
}

// Iron is "cheap" reluctance until the teeth/back-iron approach ~1.9 T, where
// the B-H curve rolls over and reluctance shoots up. Highlight elements at or
// above this band as "saturating".
export const SATURATION_THRESHOLD_T = 1.9;

export const LESSON_TWO_SOLVE_POSITIONS = 48;
export const LESSON_TWO_SHAFT_RADIUS_MM = 9;

// Same shared 2p/6s SPM baseline + the same design knobs as Lesson 1, so the
// lesson can reuse the exact mesh/solve path.
export const MAGNETIC_CIRCUIT_DEFAULT_DESIGN: MagneticCircuitDesignSettings = {
  airgapMm: 1,
  magnetArcPct: 74,
  magnetThicknessMm: 4,
};

export const MAGNETIC_CIRCUIT_DESIGN_FIELDS: MagneticCircuitDesignField[] = [
  { key: 'airgapMm', label: 'Airgap', unit: 'mm', min: 0.5, max: 2.5, step: 0.1 },
  { key: 'magnetThicknessMm', label: 'Magnet Thickness', unit: 'mm', min: 2.5, max: 6, step: 0.1 },
  { key: 'magnetArcPct', label: 'Magnet Arc', unit: '%', min: 55, max: 90, step: 1 },
];

export const MAGNETIC_CIRCUIT_PHASE_CURRENT = {
  min: 0,
  max: 12,
  step: 0.1,
  default: 6,
};

export const clampNumber = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

export const normalizeAngleDeg = (angleDeg: number): number =>
  ((angleDeg % 360) + 360) % 360;

export const circularAngleDistance = (a: number, b: number): number => {
  const delta = Math.abs(normalizeAngleDeg(a) - normalizeAngleDeg(b));
  return Math.min(delta, 360 - delta);
};

export const designSettingsEqual = (
  a: MagneticCircuitDesignSettings | null,
  b: MagneticCircuitDesignSettings,
): boolean => {
  if (!a) return false;
  return Math.abs(a.airgapMm - b.airgapMm) < 1e-9
    && Math.abs(a.magnetArcPct - b.magnetArcPct) < 1e-9
    && Math.abs(a.magnetThicknessMm - b.magnetThicknessMm) < 1e-9;
};

export const formatTesla = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value.toFixed(2)} T`;
};

export const formatMillimeters = (value: number): string => `${value.toFixed(1)} mm`;

export const formatPercent = (fraction: number): string => `${Math.round(fraction * 100)}%`;

// Peak radial airgap B from the binned Br/Bt profile, falling back to the
// summary |B| stats when the profile is unavailable.
export const peakAirgapRadialB = (
  profile: AirgapBrBtProfile | null | undefined,
  stats: AirgapFieldStats | null | undefined,
): number | null => {
  const bins = profile?.bins;
  if (Array.isArray(bins) && bins.length > 0) {
    const peak = bins.reduce((max, bin) => Math.max(max, Math.abs(bin.br_t)), 0);
    if (Number.isFinite(peak) && peak > 0) return peak;
  }
  if (stats && Number.isFinite(stats.max_t)) return stats.max_t;
  return null;
};

export const meanAirgapB = (stats: AirgapFieldStats | null | undefined): number | null => {
  if (stats && Number.isFinite(stats.mean_t)) return stats.mean_t;
  return null;
};

export interface SaturationSummary {
  fraction: number;
  saturatedCount: number;
  totalCount: number;
  maxT: number;
  saturatedAreaMm2: number;
  steelAreaMm2: number;
}

export const isSaturationSteelRegion = (region: string | null | undefined): boolean => {
  const normalized = String(region ?? '').replace(/[^a-z]/gi, '').toLowerCase();
  return normalized === 'statortooth'
    || normalized === 'statoryoke'
    || normalized === 'rotorcore';
};

// Area-weighted fraction of steel at/above the saturation threshold. Air,
// copper, magnets, and other non-ferromagnetic regions are excluded.
export const summarizeSaturation = (
  nodesMm: [number, number][] | null | undefined,
  triangles: [number, number, number][] | null | undefined,
  regions: string[] | null | undefined,
  elementBMagT: number[] | null | undefined,
  threshold = SATURATION_THRESHOLD_T,
): SaturationSummary | null => {
  if (!Array.isArray(nodesMm)
    || !Array.isArray(triangles)
    || !Array.isArray(regions)
    || !Array.isArray(elementBMagT)
    || triangles.length === 0
    || regions.length !== triangles.length
    || elementBMagT.length !== triangles.length) return null;
  let saturatedCount = 0;
  let totalCount = 0;
  let maxT = 0;
  let saturatedAreaMm2 = 0;
  let steelAreaMm2 = 0;
  for (let index = 0; index < triangles.length; index += 1) {
    if (!isSaturationSteelRegion(regions[index])) continue;
    const triangle = triangles[index];
    const a = nodesMm[triangle[0]];
    const b = nodesMm[triangle[1]];
    const c = nodesMm[triangle[2]];
    if (!a || !b || !c) continue;
    const areaMm2 = Math.abs(
      a[0] * (b[1] - c[1])
      + b[0] * (c[1] - a[1])
      + c[0] * (a[1] - b[1]),
    ) / 2;
    const value = elementBMagT[index];
    if (!Number.isFinite(areaMm2) || areaMm2 <= 0) continue;
    if (!Number.isFinite(value)) continue;
    totalCount += 1;
    steelAreaMm2 += areaMm2;
    if (value > maxT) maxT = value;
    if (value >= threshold) {
      saturatedCount += 1;
      saturatedAreaMm2 += areaMm2;
    }
  }
  if (totalCount === 0 || steelAreaMm2 <= 0) return null;
  return {
    fraction: saturatedAreaMm2 / steelAreaMm2,
    saturatedCount,
    totalCount,
    maxT,
    saturatedAreaMm2,
    steelAreaMm2,
  };
};

export interface MagneticCircuitStep {
  id: string;
  overlay: MagneticCircuitOverlay;
  title: string;
  instruction: string;
  observe: string;
}

// The three teaching steps all live inside the Solve stage and are driven by
// the overlay toggle, matching the spec's "Design -> Mesh -> Solve" reuse.
export const MAGNETIC_CIRCUIT_STEPS: MagneticCircuitStep[] = [
  {
    id: 'trace-the-loop',
    overlay: 'flux-path',
    title: 'Trace the loop',
    instruction: 'Run the baseline solve and follow one closed flux loop through its four series reluctances.',
    observe: 'Almost the entire MMF drop happens across the two tiny airgaps — not the iron.',
  },
  {
    id: 'budget-the-loop',
    overlay: 'budget',
    title: 'Budget the loop',
    instruction: 'Hand-calc B_gap from the givens (calculator allowed) and enter your value. Then run the balanced solve and compare your prediction against the FEM frame.',
    observe: 'A one-line circuit model lands within ~10–20% of the FEM frame — the miss is fringing, leakage, and slotting.',
  },
  {
    id: 'shrink-the-airgap',
    overlay: 'airgap-flux',
    title: 'Shrink the airgap',
    instruction: 'Drag the Airgap slider down and re-solve. Watch the airgap-flux gauge climb.',
    observe: 'Halving the airgap roughly doubles airgap flux — reluctance is proportional to gap length.',
  },
  {
    id: 'saturate-the-iron',
    overlay: 'saturation',
    title: 'Saturate the iron',
    instruction: 'Increase magnet thickness and/or phase current and re-solve. Watch the teeth light up.',
    observe: 'Iron is "free" reluctance only until it saturates — then it becomes the bottleneck and flux stops scaling.',
  },
];

export interface KnowledgeCheckQuestion {
  id: string;
  prompt: string;
  options: string[];
  correctIndex: number;
  explanation: string;
}

export const MAGNETIC_CIRCUIT_KNOWLEDGE_CHECK: KnowledgeCheckQuestion[] = [
  {
    id: 'opposite-slot-sides',
    prompt: 'Why are the two sides of one phase labeled with opposite current directions?',
    options: [
      'They cancel all of the phase field',
      'They are the two active sides of one coil loop',
      'One side is a permanent magnet',
      'Only one side is connected during a solve',
    ],
    correctIndex: 1,
    explanation: 'Current leaves the screen on one active side and returns through the other, so the pair forms one coil loop around the stator teeth.',
  },
  {
    id: 'zero-torque-alignment',
    prompt: 'What does a zero crossing on the torque-versus-angle curve mean?',
    options: [
      'The rotor field is aligned with the stator-field target',
      'All three phase currents are zero',
      'The permanent magnets have demagnetized',
      'The mesh contains no airgap elements',
    ],
    correctIndex: 0,
    explanation: 'At magnetic alignment there is no angular error to correct, so the electromagnetic torque momentarily reaches zero.',
  },
  {
    id: 'torque-sign',
    prompt: 'Why does the torque curve change sign after the rotor passes alignment?',
    options: [
      'The airgap changes size',
      'The phase labels swap colors',
      'The restoring rotation direction reverses',
      'The rotor gains another pole',
    ],
    correctIndex: 2,
    explanation: 'On the other side of the alignment target, the shortest rotation back toward alignment is in the opposite direction, so torque changes sign.',
  },
];

// --- Reluctance budget hand-calc (crash-course Day 1 lab) -------------------
// One-pole-pair loop for the Lesson-1 motor (lesson1_spm_2p6s.openem): the flux
// crosses two magnets and two airgaps in series, plus an iron path that stays
// nearly free while the steel is unsaturated. Magnet constants match N42 in
// solvers/magneto2d/src/materials.rs (Br = 1.30 T, mu_r = 1.05).
export const LESSON_TWO_MAGNET_BR_T = 1.3;
export const LESSON_TWO_MAGNET_MU_R = 1.05;
// Rough iron loop for the 2p/6s teaching motor: up one tooth, around the yoke,
// down the opposite tooth, and across the rotor core.
export const LESSON_TWO_IRON_PATH_MM = 150;
export const LESSON_TWO_IRON_MU_R = 2000;

const MU_0_H_PER_M = 4 * Math.PI * 1e-7;

export interface ReluctanceBudgetResult {
  /** Total magnet MMF driving the loop: 2 * Hc * hm, in ampere-turns. */
  magnetMmfAt: number;
  /** Series reluctance per unit area, expressed as mm of equivalent air path. */
  magnetEquivMm: number;
  airgapEquivMm: number;
  ironEquivMm: number;
  totalEquivMm: number;
  /** Share of the total MMF each element drops. */
  magnetFraction: number;
  airgapFraction: number;
  ironFraction: number;
  /** Predicted airgap flux density: B = F / (R * A) with iron included. */
  predictedAirgapBT: number;
  /** Iron term as it appears inside the simplified denominator (mm). */
  ironDenominatorTermMm: number;
}

export const computeReluctanceBudget = (
  airgapMm: number,
  magnetThicknessMm: number,
): ReluctanceBudgetResult => {
  const hcAm = LESSON_TWO_MAGNET_BR_T / (MU_0_H_PER_M * LESSON_TWO_MAGNET_MU_R);
  const magnetMmfAt = 2 * hcAm * (magnetThicknessMm / 1000);
  const magnetEquivMm = (2 * magnetThicknessMm) / LESSON_TWO_MAGNET_MU_R;
  const airgapEquivMm = 2 * airgapMm;
  const ironEquivMm = LESSON_TWO_IRON_PATH_MM / LESSON_TWO_IRON_MU_R;
  const totalEquivMm = magnetEquivMm + airgapEquivMm + ironEquivMm;
  // B = F / (R*A) = [2 * Br * hm / mu_r] / totalEquivMm (all lengths in mm).
  const predictedAirgapBT =
    ((2 * LESSON_TWO_MAGNET_BR_T * magnetThicknessMm) / LESSON_TWO_MAGNET_MU_R) / totalEquivMm;
  return {
    magnetMmfAt,
    magnetEquivMm,
    airgapEquivMm,
    ironEquivMm,
    totalEquivMm,
    magnetFraction: magnetEquivMm / totalEquivMm,
    airgapFraction: airgapEquivMm / totalEquivMm,
    ironFraction: ironEquivMm / totalEquivMm,
    predictedAirgapBT,
    ironDenominatorTermMm: (LESSON_TWO_MAGNET_MU_R * ironEquivMm) / 2,
  };
};
