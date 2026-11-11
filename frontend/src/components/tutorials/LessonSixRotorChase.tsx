import React from 'react';
import type { RotorChaseFieldData, RotorChaseFieldSource } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { oneOf, useLessonResume, useLessonSessionState } from './lessonSession';
import {
  MeshViewer,
  type MeshViewerDipoleMarker,
  type MeshViewerDirectionVector,
  type MeshViewerForceVector,
  type MeshViewerPointLabel,
} from './MeshViewer';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
import { RotorChase3D } from './RotorChase3D';
import {
  LessonChoices,
  LessonDock,
  LessonDockGroup,
  LessonDockToggle,
  LessonGoal,
  LessonLab,
  LessonLabCanvas,
  LessonLabPanel,
  LessonLabStage,
  LessonLabViewport,
  LessonLink,
  LessonNextStep,
  LessonOutline,
  LessonSegmented,
  LessonTerms,
  type LessonTerm,
} from './lab/LessonLab';
import './learning.css';
import './rotor-chase.css';

interface LearningLessonSixRotorChaseProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'align-once' | 'spin-forever' | 'unaffected';
type LabPart = 'release' | 'chase' | 'dc' | 'ac';
type LessonSixProgressStepId = 'predict' | 'release' | 'chase' | 'dc' | 'ac' | 'check';

const LESSON_SIX_GOALS: Record<
  LessonSixProgressStepId,
  { title: string; detail: string }
> = {
  predict: {
    title: 'Predict what a fixed field does',
    detail: 'Decide whether one stationary field can keep a permanent-magnet rotor turning.',
  },
  release: {
    title: 'Release the rotor from 90°',
    detail: 'Watch torque fall to zero as the rotor reaches the fixed magnetic target.',
  },
  chase: {
    title: 'Try a different starting angle',
    detail: 'Move only the rotor and verify that the destination does not move with it.',
  },
  dc: {
    title: 'Reverse the wound-pole field',
    detail: 'Compare +8 A and −8 A to see current swap the N/S faces and alignment target.',
  },
  ac: {
    title: 'Drive one fixed axis with AC',
    detail: 'Play a full cycle and observe a target that reverses instead of rotating.',
  },
  check: {
    title: 'Explain what continuous rotation needs',
    detail: 'Connect the solved alignment behavior to the need for an advancing field direction.',
  },
};

const SOURCE_POLE_GAP_MM = 8;
const LESSON_ID = 'rotor-chase';
const LAB_PARTS: readonly LabPart[] = ['release', 'chase', 'dc', 'ac'];
const ROTOR_START_ANGLE_DEG = 90;
const MANUAL_STEP_DEG = 15;
const FIELD_VECTOR_LENGTH_MM = 17;
const ELECTROMAGNET_PEAK_CURRENT_A = 8;
const ELECTROMAGNET_TURNS = 1008;
const AC_STEP_DEG = 11.25;
const MU_ZERO_H_PER_M = 4 * Math.PI * 1e-7;
const N42_REMANENCE_T = 1.30;
const N42_RELATIVE_PERMEABILITY = 1.05;
const TEACHING_DEPTH_MM = 10;
const FEM_CHECKPOINT_ANGLES = [0, 15, 30, 45, 60, 75, 90] as const;
const POSITIVE_DC_ANGLES = [0, 15, 30, 45, 60, 75, 90] as const;
const NEGATIVE_DC_ANGLES = [90, 105, 120, 135, 150, 165, 180] as const;
const AC_ROTOR_ANGLES = [
  0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180,
] as const;
const AC_POSITIVE_EXTRA_ANGLES = [105, 120, 135, 150, 165, 180] as const;
const AC_NEGATIVE_EXTRA_ANGLES = [0, 15, 30, 45, 60, 75] as const;
const ELECTROMAGNET_INITIAL_SOLVE_COUNT = (
  POSITIVE_DC_ANGLES.length
  + NEGATIVE_DC_ANGLES.length
  + 5
);

type RotorChaseFrameSet = Partial<Record<
  RotorChaseFieldSource,
  Record<number, RotorChaseFieldData>
>>;

type ElectromagnetPolarity = 'positive' | 'zero' | 'negative';
type ElectromagnetFrameSet = Partial<Record<
  RotorChaseFieldSource,
  Partial<Record<ElectromagnetPolarity, RotorChaseFieldData>>
>>;
type DcReleasePolarity = Exclude<ElectromagnetPolarity, 'zero'>;
type DcReleaseFrameSet = Partial<Record<
  DcReleasePolarity,
  Partial<Record<number, RotorChaseFieldData>>
>>;

interface TorqueSample {
  misalignmentDeg: number;
  torqueNm: number;
}

interface ForceCurrentSample {
  currentA: number;
  northForceN: number;
  southForceN: number;
}

const FIELD_SOURCE_OPTIONS: ReadonlyArray<{ id: RotorChaseFieldSource; label: string; title: string }> = [
  { id: 'combined', label: 'Combined', title: 'The stator source and the rotor magnet together' },
  { id: 'stator', label: 'Stator', title: 'The stator source on its own' },
  { id: 'rotor', label: 'Rotor', title: 'The rotor magnet on its own' },
];

// The lesson's vocabulary, shown beside whatever is being read or measured.
const LESSON_SIX_TERMS: readonly LessonTerm[] = [
  { term: <>Torque, &tau;</>, definition: 'The turning effect of a force about the shaft, in newton-metres (N·m). This small rotor is measured in mN·m, thousandths of a newton-metre.' },
  { term: <>Torque angle, &delta;</>, definition: 'The angle between the field direction and the rotor’s N–S axis, in degrees. Torque is largest near 90° and zero at 0°.' },
  { term: 'Alignment target', definition: 'The direction the rotor’s N pole settles toward. Once the rotor points there, the torque is zero.' },
  { term: 'Force couple', definition: 'Two equal and opposite forces, in newtons (N), acting at the two ends of the rotor. They do not push it sideways; together they turn it.' },
  { term: '|B|', definition: 'Flux density: how strong the field is at one spot, in tesla (T). Here it is shown in millitesla (mT).' },
  { term: 'MMF, NI', definition: 'Magnetomotive force: the coil’s "push" on the field. It is the number of turns N times the current I, in ampere-turns (A-turn).' },
  { term: <>Electrical angle, &theta;</>, definition: 'How far the alternating current is through one cycle, in degrees: 0° to 360° is one full cycle.' },
  { term: 'FEM', definition: 'Finite element method: the solver splits the space into small triangles (the mesh) and works out the field in each one.' },
];

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'fixed-field-result',
    prompt: 'What can a fixed magnetic field do to a freely rotating permanent-magnet rotor?',
    options: [
      'Turn it toward alignment once',
      'Keep it spinning forever at constant speed',
      'Apply no torque at any angle',
    ],
    correctIndex: 0,
    explanation: 'A fixed field supplies one alignment target. Once the rotor reaches it, the torque falls to zero.',
  },
  {
    id: 'torque-at-alignment',
    prompt: 'Why does the rotor stop accelerating when its N-S axis aligns with the field?',
    options: [
      'The torque angle is zero, so alignment torque is zero',
      'The permanent magnet loses its magnetization',
      'The airgap becomes infinitely large',
    ],
    correctIndex: 0,
    explanation: 'The teaching model uses torque proportional to sin(field angle - rotor angle). At alignment, sin(0) = 0.',
  },
  {
    id: 'same-fixed-target',
    prompt: 'If you turn the rotor away from alignment and release it again, what does it chase?',
    options: ['The same fixed field direction', 'A new field created by the rotor angle', 'No magnetic target'],
    correctIndex: 0,
    explanation: 'The stator magnets never moved. Every release returns the rotor toward the same fixed alignment target.',
  },
  {
    id: 'reverse-dc',
    prompt: 'What happens when the DC current in both wound poles reverses?',
    options: [
      'The pole faces swap N/S and the fixed field target flips 180 deg',
      'The field keeps the same direction but doubles',
      'The iron permanently becomes a new magnet',
    ],
    correctIndex: 0,
    explanation: 'Current direction sets electromagnet polarity. Reversing every turn reverses the field and swaps the pole faces.',
  },
  {
    id: 'single-phase-ac',
    prompt: 'What field does one sinusoidal AC phase create in this fixture?',
    options: [
      'A field that grows, collapses, and reverses on one fixed axis',
      'A constant-strength field rotating continuously through 360 deg',
      'No magnetic field because the average current is zero',
    ],
    correctIndex: 0,
    explanation: 'One AC phase alternates on one axis. Lesson 7 adds a perpendicular phase, shifted by 90 deg, to make the resultant direction rotate.',
  },
];

const normalizeAngle = (angleDeg: number) => ((angleDeg % 360) + 360) % 360;

const shortestAngle = (targetDeg: number, actualDeg: number) => {
  const delta = normalizeAngle(targetDeg) - normalizeAngle(actualDeg);
  return ((delta + 540) % 360) - 180;
};

const displayAngle = (angleDeg: number) => `${normalizeAngle(angleDeg).toFixed(1)} deg`;

const interpolateOptional = (
  start: number | null | undefined,
  end: number | null | undefined,
  amount: number,
): number | undefined => (
  start == null || end == null ? undefined : start + (end - start) * amount
);

const interpolateArray = (
  start: number[] | undefined,
  end: number[] | undefined,
  amount: number,
): number[] | undefined => {
  if (!start || !end || start.length !== end.length) return end;
  return start.map((value, index) => value + (end[index] - value) * amount);
};

const interpolateElectromagnetFrame = (
  zeroFrame: RotorChaseFieldData,
  energizedFrame: RotorChaseFieldData,
  amount: number,
  currentA: number,
): RotorChaseFieldData => {
  const elementBx = interpolateArray(
    zeroFrame.element_bx_t,
    energizedFrame.element_bx_t,
    amount,
  );
  const elementBy = interpolateArray(
    zeroFrame.element_by_t,
    energizedFrame.element_by_t,
    amount,
  );
  const centerBx = interpolateOptional(
    zeroFrame.metrics?.center_bx_t,
    energizedFrame.metrics?.center_bx_t,
    amount,
  );
  const centerBy = interpolateOptional(
    zeroFrame.metrics?.center_by_t,
    energizedFrame.metrics?.center_by_t,
    amount,
  );

  return {
    ...energizedFrame,
    source_current_a: currentA,
    element_b_mag_t: elementBx && elementBy
      ? elementBx.map((bx, index) => Math.hypot(bx, elementBy[index]))
      : interpolateArray(
        zeroFrame.element_b_mag_t,
        energizedFrame.element_b_mag_t,
        amount,
      ),
    element_bx_t: elementBx,
    element_by_t: elementBy,
    contour_levels: energizedFrame.contour_levels.map((level, index) => {
      const zeroLevel = zeroFrame.contour_levels[index];
      const segmentBx = interpolateArray(
        zeroLevel?.segment_bx_t,
        level.segment_bx_t,
        amount,
      );
      const segmentBy = interpolateArray(
        zeroLevel?.segment_by_t,
        level.segment_by_t,
        amount,
      );
      return {
        ...level,
        level: zeroLevel
          ? zeroLevel.level + (level.level - zeroLevel.level) * amount
          : level.level,
        segment_b_mag_t: segmentBx && segmentBy
          ? segmentBx.map((bx, segmentIndex) => Math.hypot(bx, segmentBy[segmentIndex]))
          : level.segment_b_mag_t,
        segment_bx_t: segmentBx,
        segment_by_t: segmentBy,
      };
    }),
    az_min: zeroFrame.az_min + (energizedFrame.az_min - zeroFrame.az_min) * amount,
    az_max: zeroFrame.az_max + (energizedFrame.az_max - zeroFrame.az_max) * amount,
    metrics: energizedFrame.metrics && zeroFrame.metrics ? {
      ...energizedFrame.metrics,
      working_gap_mean_b_t: (
        zeroFrame.metrics.working_gap_mean_b_t
        + (
          energizedFrame.metrics.working_gap_mean_b_t
          - zeroFrame.metrics.working_gap_mean_b_t
        ) * amount
      ),
      outside_field_mean_b_t: (
        zeroFrame.metrics.outside_field_mean_b_t
        + (
          energizedFrame.metrics.outside_field_mean_b_t
          - zeroFrame.metrics.outside_field_mean_b_t
        ) * amount
      ),
      return_path_mean_b_t: interpolateOptional(
        zeroFrame.metrics.return_path_mean_b_t,
        energizedFrame.metrics.return_path_mean_b_t,
        amount,
      ),
      peak_b_t: zeroFrame.metrics.peak_b_t
        + (energizedFrame.metrics.peak_b_t - zeroFrame.metrics.peak_b_t) * amount,
      north_face_mean_bn_t: interpolateOptional(
        zeroFrame.metrics.north_face_mean_bn_t,
        energizedFrame.metrics.north_face_mean_bn_t,
        amount,
      ),
      north_face_flux_wb: interpolateOptional(
        zeroFrame.metrics.north_face_flux_wb,
        energizedFrame.metrics.north_face_flux_wb,
        amount,
      ),
      south_face_flux_wb: interpolateOptional(
        zeroFrame.metrics.south_face_flux_wb,
        energizedFrame.metrics.south_face_flux_wb,
        amount,
      ),
      iron_mean_b_t: interpolateOptional(
        zeroFrame.metrics.iron_mean_b_t,
        energizedFrame.metrics.iron_mean_b_t,
        amount,
      ),
      center_bx_t: centerBx,
      center_by_t: centerBy,
      center_b_t: centerBx == null || centerBy == null
        ? interpolateOptional(
          zeroFrame.metrics.center_b_t,
          energizedFrame.metrics.center_b_t,
          amount,
        )
        : Math.hypot(centerBx, centerBy),
      center_field_angle_deg: centerBx == null || centerBy == null
        ? energizedFrame.metrics.center_field_angle_deg
        : normalizeAngle(Math.atan2(centerBy, centerBx) * 180 / Math.PI),
    } : energizedFrame.metrics,
  };
};

const mirrorFieldDataAcrossX = (
  data: RotorChaseFieldData,
): RotorChaseFieldData => ({
  ...data,
  nodes_mm: data.nodes_mm.map(([x, y]) => [x, -y]),
  contour_levels: data.contour_levels.map((level) => ({
    ...level,
    segments_mm: level.segments_mm.map(
      ([x1, y1, x2, y2]) => [x1, -y1, x2, -y2] as [number, number, number, number],
    ),
    segment_by_t: level.segment_by_t?.map((by) => -by),
  })),
  element_by_t: data.element_by_t?.map((by) => -by),
  magnet_center_y_mm: -(data.magnet_center_y_mm ?? 0),
  magnet_angle_deg: normalizeAngle(-(data.magnet_angle_deg ?? 0)),
  metrics: data.metrics ? {
    ...data.metrics,
    center_by_t: -(data.metrics.center_by_t ?? 0),
    center_field_angle_deg: normalizeAngle(
      -(data.metrics.center_field_angle_deg ?? 0),
    ),
  } : data.metrics,
});

const nearestAngle = <Angle extends number>(
  angleDeg: number,
  angles: readonly Angle[],
) => angles.reduce(
  (nearest, candidate) => (
    Math.abs(candidate - angleDeg) < Math.abs(nearest - angleDeg)
      ? candidate
      : nearest
  ),
  angles[0],
);

const nearestCheckpoint = (angleDeg: number) => nearestAngle(
  angleDeg,
  FEM_CHECKPOINT_ANGLES,
);

const triangleAreaMm2 = (
  [first, second, third]: [number, number, number],
  nodes: [number, number][],
) => {
  const [x1, y1] = nodes[first];
  const [x2, y2] = nodes[second];
  const [x3, y3] = nodes[third];
  return Math.abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2;
};

const estimateFieldEnergyJ = (frame: RotorChaseFieldData) => {
  const bMagnitudes = frame.element_b_mag_t
    ?? frame.element_bx_t?.map((bx, index) => Math.hypot(bx, frame.element_by_t?.[index] ?? 0));
  if (!bMagnitudes?.length) return null;

  const depthM = TEACHING_DEPTH_MM * 1e-3;
  return frame.triangles.reduce((energyJ, triangle, index) => {
    const bTesla = bMagnitudes[index];
    if (!Number.isFinite(bTesla)) return energyJ;
    const relativePermeability = frame.regions[index]?.includes('magnet')
      ? N42_RELATIVE_PERMEABILITY
      : 1;
    const volumeM3 = triangleAreaMm2(triangle, frame.nodes_mm) * 1e-6 * depthM;
    return energyJ + ((bTesla * bTesla) / (2 * MU_ZERO_H_PER_M * relativePermeability)) * volumeM3;
  }, 0);
};

const buildFemTorqueSamples = (
  frames: Record<number, RotorChaseFieldData> | undefined,
): TorqueSample[] => {
  if (!frames) return [];
  const energyByAngle = new Map<number, number>();
  FEM_CHECKPOINT_ANGLES.forEach((angleDeg) => {
    const energyJ = estimateFieldEnergyJ(frames[angleDeg]);
    if (energyJ !== null) energyByAngle.set(angleDeg, energyJ);
  });
  if (energyByAngle.size !== FEM_CHECKPOINT_ANGLES.length) return [];

  const stepRad = 15 * Math.PI / 180;
  const positiveRotorSamples = FEM_CHECKPOINT_ANGLES.map((rotorAngleDeg, index) => {
    let torqueNm = 0;
    if (index > 0 && index < FEM_CHECKPOINT_ANGLES.length - 1) {
      const previousAngle = FEM_CHECKPOINT_ANGLES[index - 1];
      const nextAngle = FEM_CHECKPOINT_ANGLES[index + 1];
      torqueNm = (
        (energyByAngle.get(nextAngle) ?? 0) - (energyByAngle.get(previousAngle) ?? 0)
      ) / (2 * stepRad);
    } else if (index === FEM_CHECKPOINT_ANGLES.length - 1) {
      const energy90 = energyByAngle.get(90) ?? 0;
      const energy75 = energyByAngle.get(75) ?? 0;
      const energy60 = energyByAngle.get(60) ?? 0;
      torqueNm = (3 * energy90 - 4 * energy75 + energy60) / (2 * stepRad);
    }
    return {
      misalignmentDeg: -rotorAngleDeg,
      torqueNm,
    };
  });

  return positiveRotorSamples.flatMap((sample) => (
    sample.misalignmentDeg === 0
      ? [sample]
      : [
        sample,
        {
          misalignmentDeg: -sample.misalignmentDeg,
          torqueNm: -sample.torqueNm,
        },
      ]
  )).sort((left, right) => left.misalignmentDeg - right.misalignmentDeg);
};

const interpolateTorqueNm = (samples: TorqueSample[], misalignmentDeg: number) => {
  if (!samples.length) return null;
  const clampedAngle = Math.max(samples[0].misalignmentDeg, Math.min(
    samples[samples.length - 1].misalignmentDeg,
    misalignmentDeg,
  ));
  const upperIndex = samples.findIndex((sample) => sample.misalignmentDeg >= clampedAngle);
  if (upperIndex <= 0) return samples[0].torqueNm;
  const lower = samples[upperIndex - 1];
  const upper = samples[upperIndex];
  const span = upper.misalignmentDeg - lower.misalignmentDeg;
  const ratio = span === 0 ? 0 : (clampedAngle - lower.misalignmentDeg) / span;
  return lower.torqueNm + (upper.torqueNm - lower.torqueNm) * ratio;
};

const formatTorqueMnM = (torqueNm: number | null) => {
  if (torqueNm === null) return '—';
  if (Math.abs(torqueNm) < 5e-5) return '0.0 mN·m';
  return `${torqueNm >= 0 ? '+' : '−'}${Math.abs(torqueNm * 1e3).toFixed(1)} mN·m`;
};

const PredictionDiagram: React.FC<{ rotorAngleDeg?: number; sourceAngleDeg?: number }> = ({
  rotorAngleDeg = ROTOR_START_ANGLE_DEG,
  sourceAngleDeg = 0,
}) => (
  <svg
    className="rotor-chase-prediction"
    viewBox="0 0 920 560"
    role="img"
    aria-label="A permanent magnet rotor misaligned with a fixed permanent-magnet source field"
  >
    <defs>
      <marker id="rotorChasePredictionArrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
        <path d="M0,0 L9,4.5 L0,9 Z" fill="#67e8f9" />
      </marker>
      <marker id="rotorChaseTorqueArrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
        <path d="M0,0 L9,4.5 L0,9 Z" fill="#f59e0b" />
      </marker>
    </defs>
    <g transform={`rotate(${-sourceAngleDeg} 460 280)`}>
      <path d="M118 165 H210 V395 H118 Q110 395 110 387 V173 Q110 165 118 165 Z" className="rotor-chase-source-s" />
      <path d="M210 165 H302 Q310 165 310 173 V387 Q310 395 302 395 H210 Z" className="rotor-chase-source-n" />
      <rect x="110" y="165" width="200" height="230" rx="8" className="rotor-chase-source-outline" />
      <text x="160" y="292" className="rotor-chase-source-label is-s">S</text>
      <text x="260" y="292" className="rotor-chase-source-label is-n">N</text>
      <path d="M618 165 H710 V395 H618 Q610 395 610 387 V173 Q610 165 618 165 Z" className="rotor-chase-source-s" />
      <path d="M710 165 H802 Q810 165 810 173 V387 Q810 395 802 395 H710 Z" className="rotor-chase-source-n" />
      <rect x="610" y="165" width="200" height="230" rx="8" className="rotor-chase-source-outline" />
      <text x="660" y="292" className="rotor-chase-source-label is-s">S</text>
      <text x="760" y="292" className="rotor-chase-source-label is-n">N</text>
      <path d="M315 280 L605 280" className="rotor-chase-field-arrow" markerEnd="url(#rotorChasePredictionArrow)" />
    </g>
    <g transform={`rotate(${-rotorAngleDeg} 460 280)`}>
      <rect x="382" y="248" width="78" height="64" rx="7" className="rotor-chase-rotor-s" />
      <rect x="460" y="248" width="78" height="64" rx="7" className="rotor-chase-rotor-n" />
      <text x="421" y="288" className="rotor-chase-rotor-label">S</text>
      <text x="499" y="288" className="rotor-chase-rotor-label">N</text>
    </g>
    <path d="M458 186 A94 94 0 0 1 548 272" className="rotor-chase-torque-arc" markerEnd="url(#rotorChaseTorqueArrow)" />
    <text x="460" y="70" className="rotor-chase-diagram-title">FIXED SOURCE FIELD · FREE PM ROTOR</text>
    <text x="460" y="500" className="rotor-chase-diagram-caption">Will the rotor align once, spin forever, or stay put?</text>
  </svg>
);

interface TorquePlotProps {
  misalignmentDeg: number;
  analyticPeakTorqueNm: number | null;
  femSamples: TorqueSample[];
}

const TorquePlot: React.FC<TorquePlotProps> = ({
  misalignmentDeg,
  analyticPeakTorqueNm,
  femSamples,
}) => {
  // Drawn at the width of the Inspect card, so its labels are not scaled down.
  const width = 288;
  const height = 200;
  const margin = { top: 30, right: 26, bottom: 34, left: 40 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xFor = (angle: number) => margin.left + ((angle + 180) / 360) * plotWidth;
  const analyticSamples = Array.from({ length: 73 }, (_, index) => -180 + index * 5);
  const analyticPeak = analyticPeakTorqueNm ?? 0;
  const liveAnalyticTorqueNm = analyticPeakTorqueNm === null
    ? null
    : analyticPeakTorqueNm * Math.sin(misalignmentDeg * Math.PI / 180);
  const liveFemTorqueNm = interpolateTorqueNm(femSamples, misalignmentDeg);
  const maxTorqueNm = Math.max(
    Math.abs(analyticPeak),
    ...femSamples.map((sample) => Math.abs(sample.torqueNm)),
    1e-3,
  ) * 1.18;
  const yFor = (torqueNm: number) => (
    margin.top + plotHeight / 2 - (torqueNm / maxTorqueNm) * (plotHeight / 2)
  );
  const analyticPoints = analyticSamples.map((angle) => (
    `${xFor(angle)},${yFor(analyticPeak * Math.sin(angle * Math.PI / 180))}`
  )).join(' ');
  const femPoints = femSamples.map((sample) => (
    `${xFor(sample.misalignmentDeg)},${yFor(sample.torqueNm)}`
  )).join(' ');
  const yTicks = [-maxTorqueNm, 0, maxTorqueNm];

  return (
    <svg className="rotor-chase-torque-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="FEM virtual-work and analytic alignment torque versus rotor-field misalignment">
      <line x1={margin.left} y1={yFor(0)} x2={width - margin.right} y2={yFor(0)} />
      {yTicks.map((torqueNm) => (
        <g key={torqueNm}>
          <line x1={margin.left} y1={yFor(torqueNm)} x2={width - margin.right} y2={yFor(torqueNm)} />
          <text className="rotor-chase-y-tick" x={margin.left - 6} y={yFor(torqueNm) + 4}>
            {(torqueNm * 1e3).toFixed(0)}
          </text>
        </g>
      ))}
      {[-180, -90, 0, 90, 180].map((angle) => (
        <g key={angle}>
          <line x1={xFor(angle)} y1={margin.top} x2={xFor(angle)} y2={height - margin.bottom} />
          <text x={xFor(angle)} y={height - 14}>{angle} deg</text>
        </g>
      ))}
      <polyline className="is-analytic" points={analyticPoints} />
      <polyline className="is-fem" points={femPoints} />
      {femSamples.map((sample) => (
        <circle
          key={sample.misalignmentDeg}
          className="is-fem-sample"
          cx={xFor(sample.misalignmentDeg)}
          cy={yFor(sample.torqueNm)}
          r="3.5"
        />
      ))}
      {liveAnalyticTorqueNm !== null ? (
        <circle className="is-live-analytic" cx={xFor(misalignmentDeg)} cy={yFor(liveAnalyticTorqueNm)} r="5" />
      ) : null}
      {liveFemTorqueNm !== null ? (
        <circle className="is-live-fem" cx={xFor(misalignmentDeg)} cy={yFor(liveFemTorqueNm)} r="5" />
      ) : null}
      <text className="rotor-chase-axis-label" transform={`translate(11 ${margin.top + plotHeight / 2}) rotate(-90)`}>Torque (mN·m)</text>
      {/* The live torque values are in the readout under the plot. */}
      <text className="rotor-chase-plot-label is-analytic" x={margin.left} y={16}>analytic mB sin δ</text>
      <text className="rotor-chase-plot-label is-fem" x={margin.left + 124} y={16}>FEM virtual work</text>
    </svg>
  );
};

const TorquePlotPanel: React.FC<TorquePlotProps> = ({
  misalignmentDeg,
  analyticPeakTorqueNm,
  femSamples,
}) => {
  const analyticTorqueNm = analyticPeakTorqueNm === null
    ? null
    : analyticPeakTorqueNm * Math.sin(misalignmentDeg * Math.PI / 180);
  const femTorqueNm = interpolateTorqueNm(femSamples, misalignmentDeg);

  return (
    <div className="rotor-chase-torque-panel">
      <TorquePlot
        misalignmentDeg={misalignmentDeg}
        analyticPeakTorqueNm={analyticPeakTorqueNm}
        femSamples={femSamples}
      />
      <div className="rotor-chase-inline-torque-readout">
        <div className="is-angle">
          <span>TORQUE ANGLE</span>
          <b>&delta; = field - rotor</b>
          <strong>{misalignmentDeg.toFixed(1)} deg</strong>
        </div>
        <div className="is-analytic">
          <span>ANALYTIC DIPOLE</span>
          <b>&tau; = mB sin &delta;</b>
          <strong>{formatTorqueMnM(analyticTorqueNm)}</strong>
        </div>
        <div className="is-fem">
          <span>FEM VIRTUAL WORK</span>
          <b>&tau; &asymp; dW<sub>field</sub> / d&theta;</b>
          <strong>{formatTorqueMnM(femTorqueNm)}</strong>
        </div>
      </div>
    </div>
  );
};

interface ForceCoupleCardProps {
  fieldActive: boolean;
  fieldDirection: string;
  southForceDirection: string;
  torqueAngleDeg: number;
  torqueDirection: string;
  reverseDc?: boolean;
}

const ForceCoupleCard: React.FC<ForceCoupleCardProps> = ({
  fieldActive,
  fieldDirection,
  southForceDirection,
  torqueAngleDeg,
  torqueDirection,
  reverseDc = false,
}) => (
  <section className="rotor-chase-force-couple-card">
    <header>
      <span>FORCE COUPLE → TORQUE</span>
      <strong>{fieldActive ? torqueDirection : 'Field off'}</strong>
    </header>
    <h3>
      {fieldActive && Math.abs(torqueAngleDeg) >= 1
        ? 'The forces cancel as a push, but add as a turn.'
        : fieldActive
          ? 'The force lines now pass through the shaft, so torque is zero.'
        : 'With the coil field off, this force couple disappears.'}
    </h3>
    <div className="rotor-chase-force-couple-equation" aria-label="Two pole forces create rotor torque">
      <article>
        <small>N pole</small>
        <b>F<sub>N</sub> → {fieldDirection}</b>
        <i>along B</i>
      </article>
      <span aria-hidden="true">+</span>
      <article>
        <small>S pole</small>
        <b>F<sub>S</sub> → {southForceDirection}</b>
        <i>opposite B</i>
      </article>
      <span aria-hidden="true">=</span>
      <article className="is-torque">
        <small>Rotor result</small>
        <b>
          τ {fieldActive && Math.abs(torqueAngleDeg) >= 1
            ? torqueDirection === 'Counter-clockwise'
              ? 'CCW'
              : torqueDirection === 'Clockwise'
                ? 'CW'
                : torqueDirection
            : '0'}
        </b>
        <i>δ = {torqueAngleDeg.toFixed(1)}°</i>
      </article>
    </div>
    <div className="rotor-chase-force-balance">
      <span>
        <b>{fieldActive ? 'Net force ≈ 0' : 'Pole forces = 0'}</b>
        <small>{fieldActive ? 'equal + opposite' : 'coil field off'}</small>
      </span>
      <span>
        <b>
          Torque = {fieldActive
            ? `${Math.round(Math.abs(Math.sin(torqueAngleDeg * Math.PI / 180)) * 100)}% peak`
            : '0'}
        </b>
        <small>|τ| / τmax = |sin δ|</small>
      </span>
    </div>
    <p>
      {reverseDc
        ? 'Reverse current flips B, so both pole-force arrows reverse. Their force couple reverses the torque and makes the rotor chase the new 180° target.'
        : 'The N- and S-pole forces act at opposite ends of the rotor. Their linear pushes cancel, while their moments about the shaft add until the rotor aligns.'}
    </p>
  </section>
);

interface ForceCurrentPlotProps {
  currentA: number;
  peakForceN: number | null;
  peakTorqueNm: number | null;
  leverArmMm: number | null;
  plottedCurrentsA: number[];
}

const ForceCurrentPlot: React.FC<ForceCurrentPlotProps> = ({
  currentA,
  peakForceN,
  peakTorqueNm,
  leverArmMm,
  plottedCurrentsA,
}) => {
  // Drawn at the width of its card in the Inspect panel.
  const width = 262;
  const height = 236;
  const margin = { top: 42, right: 14, bottom: 44, left: 52 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxForceN = Math.max(peakForceN ?? 0, 0.1);
  const xFor = (sampleCurrentA: number) => (
    margin.left
    + ((sampleCurrentA + ELECTROMAGNET_PEAK_CURRENT_A)
      / (2 * ELECTROMAGNET_PEAK_CURRENT_A)) * plotWidth
  );
  const yFor = (forceN: number) => (
    margin.top + plotHeight / 2 - (forceN / maxForceN) * (plotHeight / 2)
  );
  const forceAt = (sampleCurrentA: number) => (
    peakForceN === null
      ? 0
      : peakForceN * sampleCurrentA / ELECTROMAGNET_PEAK_CURRENT_A
  );
  const samples: ForceCurrentSample[] = plottedCurrentsA
    .slice()
    .sort((left, right) => left - right)
    .map((sampleCurrentA) => ({
      currentA: sampleCurrentA,
      northForceN: forceAt(sampleCurrentA),
      southForceN: -forceAt(sampleCurrentA),
    }));
  const northPoints = samples.map((sample) => (
    `${xFor(sample.currentA)},${yFor(sample.northForceN)}`
  )).join(' ');
  const southPoints = samples.map((sample) => (
    `${xFor(sample.currentA)},${yFor(sample.southForceN)}`
  )).join(' ');
  const liveNorthForceN = forceAt(currentA);
  const liveSouthForceN = -liveNorthForceN;
  const forceReady = peakForceN !== null && peakTorqueNm !== null && leverArmMm !== null;

  return (
    <section className="rotor-chase-force-current-panel">
      <header>
        <div>
          <span>FEM-CALIBRATED FORCE SWEEP</span>
          <h3>Two pole forces mirror each other as current reverses.</h3>
        </div>
        <strong>{plottedCurrentsA.length} plotted</strong>
      </header>
      {forceReady ? (
        <>
          <svg
            className="rotor-chase-force-current-plot"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Rightward north-pole force and leftward south-pole force plotted against winding current"
          >
            {[-maxForceN, 0, maxForceN].map((forceN) => (
              <g key={forceN}>
                <line
                  x1={margin.left}
                  y1={yFor(forceN)}
                  x2={width - margin.right}
                  y2={yFor(forceN)}
                />
                <text className="is-y-tick" x={margin.left - 7} y={yFor(forceN) + 4}>
                  {Math.abs(forceN) < 1e-8 ? '0' : forceN.toFixed(2)}
                </text>
              </g>
            ))}
            {[-8, -4, 0, 4, 8].map((sampleCurrentA) => (
              <g key={sampleCurrentA}>
                <line
                  x1={xFor(sampleCurrentA)}
                  y1={margin.top}
                  x2={xFor(sampleCurrentA)}
                  y2={height - margin.bottom}
                />
                <text x={xFor(sampleCurrentA)} y={height - 18}>
                  {sampleCurrentA > 0 ? `+${sampleCurrentA}` : sampleCurrentA}
                </text>
              </g>
            ))}
            <line
              className="is-guide is-north"
              x1={xFor(-ELECTROMAGNET_PEAK_CURRENT_A)}
              y1={yFor(-maxForceN)}
              x2={xFor(ELECTROMAGNET_PEAK_CURRENT_A)}
              y2={yFor(maxForceN)}
            />
            <line
              className="is-guide is-south"
              x1={xFor(-ELECTROMAGNET_PEAK_CURRENT_A)}
              y1={yFor(maxForceN)}
              x2={xFor(ELECTROMAGNET_PEAK_CURRENT_A)}
              y2={yFor(-maxForceN)}
            />
            {samples.length > 1 ? (
              <>
                <polyline className="is-north" points={northPoints} />
                <polyline className="is-south" points={southPoints} />
              </>
            ) : null}
            {samples.flatMap((sample) => [
              <circle
                key={`north-${sample.currentA}`}
                className="is-sample is-north"
                cx={xFor(sample.currentA)}
                cy={yFor(sample.northForceN)}
                r="4.5"
              />,
              <circle
                key={`south-${sample.currentA}`}
                className="is-sample is-south"
                cx={xFor(sample.currentA)}
                cy={yFor(sample.southForceN)}
                r="4.5"
              />,
            ])}
            <line
              className="is-live-current"
              x1={xFor(currentA)}
              y1={margin.top}
              x2={xFor(currentA)}
              y2={height - margin.bottom}
            />
            <circle
              className="is-live is-north"
              cx={xFor(currentA)}
              cy={yFor(liveNorthForceN)}
              r="6"
            />
            <circle
              className="is-live is-south"
              cx={xFor(currentA)}
              cy={yFor(liveSouthForceN)}
              r="6"
            />
            <text className="is-axis-label" transform={`translate(11 ${margin.top + plotHeight / 2}) rotate(-90)`}>
              Tangential force Fx (N)
            </text>
            <text className="is-axis-label" x={margin.left + plotWidth / 2} y={height - 4}>
              Winding current I (A)
            </text>
            <text className="is-legend is-north" x={margin.left} y={15}>
              N pole · rightward +Fx
            </text>
            <text className="is-legend is-south" x={margin.left} y={30}>
              S pole · leftward −Fx
            </text>
          </svg>
          <div className="rotor-chase-force-current-readout">
            <article className="is-north">
              <span>N-pole force</span>
              <strong>{liveNorthForceN >= 0 ? '+' : '−'}{Math.abs(liveNorthForceN).toFixed(2)} N</strong>
              <small>{liveNorthForceN >= 0 ? 'right (+X)' : 'left (−X)'}</small>
            </article>
            <article className="is-south">
              <span>S-pole force</span>
              <strong>{liveSouthForceN >= 0 ? '+' : '−'}{Math.abs(liveSouthForceN).toFixed(2)} N</strong>
              <small>{liveSouthForceN >= 0 ? 'right (+X)' : 'left (−X)'}</small>
            </article>
          </div>
          <div className="rotor-chase-force-current-method">
            <b>τ<sub>FEM @ 8 A</sub> = {formatTorqueMnM(peakTorqueNm)}</b>
            <span>→</span>
            <b>F = |τ| / (2r) = {peakForceN.toFixed(2)} N at 8 A</b>
          </div>
          <p>
            Rotor held at 90° · r = {leverArmMm.toFixed(1)} mm. The 8 A endpoint
            comes from FEM virtual work; intermediate samples use F ∝ I. The
            forces cancel linearly, but their opposite lever arms make torque add.
          </p>
        </>
      ) : (
        <div className="rotor-chase-force-current-loading">
          <strong>Force calibration is waiting for the rotor-angle FEM frames.</strong>
          <p>The plot will use virtual-work torque from the solved +8 A sweep.</p>
        </div>
      )}
    </section>
  );
};

const OnePhaseWaveform: React.FC<{ angleDeg: number; currentA: number }> = ({
  angleDeg,
  currentA,
}) => {
  // Drawn at the width of the Inspect card.
  const width = 288;
  const height = 184;
  const margin = { top: 30, right: 26, bottom: 32, left: 30 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xFor = (angle: number) => margin.left + (angle / 360) * plotWidth;
  const yFor = (current: number) => (
    margin.top + plotHeight / 2 - (current / ELECTROMAGNET_PEAK_CURRENT_A) * (plotHeight / 2)
  );
  const sinePoints = Array.from({ length: 145 }, (_, index) => {
    const sampleAngle = index * 2.5;
    const sampleCurrent = ELECTROMAGNET_PEAK_CURRENT_A
      * Math.sin(sampleAngle * Math.PI / 180);
    return `${xFor(sampleAngle)},${yFor(sampleCurrent)}`;
  }).join(' ');

  return (
    <svg
      className="rotor-chase-ac-plot"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="One sinusoidal current grows, crosses zero, and reverses over one electrical cycle"
    >
      {[-ELECTROMAGNET_PEAK_CURRENT_A, 0, ELECTROMAGNET_PEAK_CURRENT_A].map((tick) => (
        <g key={tick}>
          <line x1={margin.left} y1={yFor(tick)} x2={width - margin.right} y2={yFor(tick)} />
          <text x={margin.left - 14} y={yFor(tick) + 4}>{tick > 0 ? `+${tick}` : tick}</text>
        </g>
      ))}
      {[0, 90, 180, 270, 360].map((tick) => (
        <g key={tick}>
          <line x1={xFor(tick)} y1={margin.top} x2={xFor(tick)} y2={height - margin.bottom} />
          <text x={xFor(tick)} y={height - 14}>{tick} deg</text>
        </g>
      ))}
      <polyline points={sinePoints} />
      <line
        className="is-live"
        x1={xFor(angleDeg)}
        y1={margin.top}
        x2={xFor(angleDeg)}
        y2={height - margin.bottom}
      />
      <circle className="is-live" cx={xFor(angleDeg)} cy={yFor(currentA)} r="6" />
      <text className="is-equation" x={margin.left} y={18}>I(t) = Ipk sin(theta)</text>
      <text className="is-live-value" x={width - margin.right} y={18}>
        {currentA >= 0 ? '+' : ''}{currentA.toFixed(2)} A
      </text>
    </svg>
  );
};

export const LearningLessonSixRotorChase: React.FC<LearningLessonSixRotorChaseProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  // The current presets, so the primary action can point the student at them.
  const dcCurrentChoiceRef = React.useRef<HTMLDivElement | null>(null);
  // The viewer draws its zoom buttons into the dock's title bar.
  const [zoomSlot, setZoomSlot] = React.useState<HTMLSpanElement | null>(null);
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = useLessonSessionState<Prediction | null>(
    LESSON_ID, 'prediction', null, oneOf<Prediction>(['align-once', 'spin-forever', 'unaffected']),
  );
  // The part of the lab the student was in. Kept apart from labPart, which
  // only moves on once the frames that part needs are solved again.
  const [storedLabPart, setStoredLabPart] = useLessonSessionState<LabPart>(
    LESSON_ID, 'labPart', 'release', oneOf<LabPart>(LAB_PARTS),
  );
  const [fieldFrames, setFieldFrames] = React.useState<RotorChaseFrameSet>({});
  const [statorReferenceFrame, setStatorReferenceFrame] = React.useState<RotorChaseFieldData | null>(null);
  const [electromagnetFrames, setElectromagnetFrames] = React.useState<ElectromagnetFrameSet>({});
  const [dcReleaseFrames, setDcReleaseFrames] = React.useState<DcReleaseFrameSet>({});
  const [electromagnetBusy, setElectromagnetBusy] = React.useState(false);
  const [electromagnetSolveProgress, setElectromagnetSolveProgress] = React.useState(0);
  const [dcCurrentA, setDcCurrentA] = React.useState(ELECTROMAGNET_PEAK_CURRENT_A);
  const [plottedForceCurrentsA, setPlottedForceCurrentsA] = React.useState<number[]>([
    ELECTROMAGNET_PEAK_CURRENT_A,
  ]);
  // Progress flags are kept for the tab, so a reload does not lock the later
  // steps again. The solved frames are not kept; they are solved again.
  const [sawPositiveDc, setSawPositiveDc] = useLessonSessionState(LESSON_ID, 'sawPositiveDc', false);
  const [sawNegativeDc, setSawNegativeDc] = useLessonSessionState(LESSON_ID, 'sawNegativeDc', false);
  const [acAngleDeg, setAcAngleDeg] = React.useState(0);
  const [playingAc, setPlayingAc] = React.useState(false);
  const [playedAc, setPlayedAc] = useLessonSessionState(LESSON_ID, 'playedAc', false);
  const [allowAcRotorMotion, setAllowAcRotorMotion] = React.useState(false);
  const [acRotorMotionBusy, setAcRotorMotionBusy] = React.useState(false);
  const [fieldSource, setFieldSource] = React.useState<RotorChaseFieldSource>('combined');
  const [loadingSource, setLoadingSource] = React.useState<RotorChaseFieldSource | null>(null);
  const sourceAngleDeg = 0;
  const [rotorAngleDeg, setRotorAngleDeg] = React.useState(ROTOR_START_ANGLE_DEG);
  const [labPart, setLabPart] = React.useState<LabPart>('release');
  const [releasing, setReleasing] = React.useState(false);
  const [alignedOnce, setAlignedOnce] = useLessonSessionState(LESSON_ID, 'alignedOnce', false);
  const [secondAlignmentComplete, setSecondAlignmentComplete] = useLessonSessionState(LESSON_ID, 'secondAlignmentComplete', false);
  const [showFieldLines, setShowFieldLines] = React.useState(true);
  const [showFluxDensity, setShowFluxDensity] = React.useState(false);
  const [showMesh, setShowMesh] = React.useState(false);
  const [showThreeD, setShowThreeD] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const lessonComplete = isLessonComplete(LESSON_ID);
  const solveClient = useLessonSolveClient();
  // Set once enterAc exists; the step buttons defined above it call it.
  const enterAcRef = React.useRef<() => Promise<void>>(async () => undefined);

  const predictionCorrect = prediction === 'align-once';
  const misalignmentDeg = shortestAngle(sourceAngleDeg, rotorAngleDeg);
  const movingTargetComplete = secondAlignmentComplete;
  const dcComplete = sawPositiveDc && sawNegativeDc;
  // A finished lesson reopens with every step available.
  const predictionDone = lessonComplete || predictionCorrect;
  const alignedDone = lessonComplete || alignedOnce;
  const movingTargetDone = lessonComplete || movingTargetComplete;
  const dcDone = lessonComplete || dcComplete;
  const acDone = lessonComplete || playedAc;
  const hasSolvedField = Boolean(fieldFrames.combined);
  const hasElectromagnetField = Boolean(
    electromagnetFrames.stator?.positive
    && electromagnetFrames.stator.zero
    && electromagnetFrames.stator.negative
    && electromagnetFrames.rotor?.zero
    && electromagnetFrames.combined?.positive
    && electromagnetFrames.combined.zero
    && electromagnetFrames.combined.negative
    && POSITIVE_DC_ANGLES.every((angleDeg) => dcReleaseFrames.positive?.[angleDeg])
    && NEGATIVE_DC_ANGLES.every((angleDeg) => dcReleaseFrames.negative?.[angleDeg]),
  );
  const hasAcRotorMotionFrames = AC_ROTOR_ANGLES.every(
    (angleDeg) => dcReleaseFrames.positive?.[angleDeg]
      && dcReleaseFrames.negative?.[angleDeg],
  );
  const electromagnetActive = labPart === 'dc' || labPart === 'ac';
  const acCurrentA = ELECTROMAGNET_PEAK_CURRENT_A
    * Math.sin(acAngleDeg * Math.PI / 180);
  const electromagnetCurrentA = labPart === 'dc' ? dcCurrentA : acCurrentA;
  const acRotorTargetAngleDeg = Math.abs(acCurrentA) < 0.01
    ? null
    : acCurrentA > 0
      ? 0
      : 180;
  const dcReleasePolarity: DcReleasePolarity | null = dcCurrentA > 0.01
    ? 'positive'
    : dcCurrentA < -0.01
      ? 'negative'
      : null;
  const dcTargetAngleDeg = dcReleasePolarity === 'positive'
    ? 0
    : dcReleasePolarity === 'negative'
      ? 180
      : null;
  const releaseTargetAngleDeg = labPart === 'dc'
    ? dcTargetAngleDeg
    : sourceAngleDeg;
  const dcRotorAtTarget = dcTargetAngleDeg !== null
    && Math.abs(shortestAngle(dcTargetAngleDeg, rotorAngleDeg)) < 0.45;
  const femTorqueSamples = React.useMemo(
    () => buildFemTorqueSamples(fieldFrames.combined),
    [fieldFrames.combined],
  );
  const dcPositiveTorqueSamples = React.useMemo(
    () => buildFemTorqueSamples(dcReleaseFrames.positive as
      | Record<number, RotorChaseFieldData>
      | undefined),
    [dcReleaseFrames.positive],
  );
  const dcPeakTorqueNm = React.useMemo(() => {
    const torqueAtNinetyNm = interpolateTorqueNm(dcPositiveTorqueSamples, -90);
    return torqueAtNinetyNm === null ? null : Math.abs(torqueAtNinetyNm);
  }, [dcPositiveTorqueSamples]);
  const dcRotorLengthMm = electromagnetFrames.combined?.positive?.rotor_length_mm ?? null;
  const dcForceLeverArmMm = dcRotorLengthMm === null ? null : dcRotorLengthMm * 0.46;
  const dcPeakPoleForceN = dcPeakTorqueNm === null || dcForceLeverArmMm === null
    ? null
    : dcPeakTorqueNm / (2 * dcForceLeverArmMm * 1e-3);
  const forceCurrentAlreadyPlotted = plottedForceCurrentsA.some(
    (sampleCurrentA) => Math.abs(sampleCurrentA - dcCurrentA) < 0.01,
  );
  const sourceCenterFieldT = statorReferenceFrame?.metrics?.center_b_t ?? null;
  const analyticPeakTorqueNm = React.useMemo(() => {
    const rotorFrame = fieldFrames.combined?.[0];
    if (!rotorFrame || sourceCenterFieldT === null) return null;
    const rotorVolumeM3 = (
      rotorFrame.rotor_length_mm
      * rotorFrame.rotor_thickness_mm
      * TEACHING_DEPTH_MM
    ) * 1e-9;
    const magnetizationApm = N42_REMANENCE_T / (
      MU_ZERO_H_PER_M * N42_RELATIVE_PERMEABILITY
    );
    return magnetizationApm * rotorVolumeM3 * sourceCenterFieldT;
  }, [fieldFrames.combined, sourceCenterFieldT]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete(LESSON_ID, true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (!releasing || releaseTargetAngleDeg === null) return undefined;
    const timer = window.setInterval(() => {
      setRotorAngleDeg((previous) => {
        const delta = shortestAngle(releaseTargetAngleDeg, previous);
        if (Math.abs(delta) < 0.45) {
          setReleasing(false);
          if (labPart === 'release') {
            setAlignedOnce(true);
          } else if (labPart === 'chase') {
            setSecondAlignmentComplete(true);
          }
          return normalizeAngle(releaseTargetAngleDeg);
        }
        return normalizeAngle(previous + delta * 0.16);
      });
    }, 36);
    return () => window.clearInterval(timer);
  }, [labPart, releaseTargetAngleDeg, releasing]);

  React.useEffect(() => {
    if (!playingAc) return undefined;
    const timer = window.setInterval(() => {
      setAcAngleDeg((previous) => {
        const next = Math.min(360, previous + AC_STEP_DEG);
        if (next >= 360) {
          setPlayingAc(false);
          setPlayedAc(true);
        }
        return next;
      });
    }, 110);
    return () => window.clearInterval(timer);
  }, [playingAc]);

  React.useEffect(() => {
    if (
      labPart !== 'ac'
      || !allowAcRotorMotion
      || acRotorTargetAngleDeg === null
    ) return undefined;
    const fieldStrength = Math.min(
      1,
      Math.abs(acCurrentA) / ELECTROMAGNET_PEAK_CURRENT_A,
    );
    const moveRotorTowardTarget = (response: number) => {
      setRotorAngleDeg((previous) => {
        const boundedPrevious = Math.max(0, Math.min(180, previous));
        const delta = acRotorTargetAngleDeg - boundedPrevious;
        if (Math.abs(delta) < 0.35) return acRotorTargetAngleDeg;
        return Math.max(
          0,
          Math.min(180, boundedPrevious + delta * response),
        );
      });
    };
    if (playingAc) {
      moveRotorTowardTarget(0.3 + fieldStrength * 0.18);
      return undefined;
    }
    const timer = window.setInterval(
      () => moveRotorTowardTarget(0.055 + fieldStrength * 0.12),
      36,
    );
    return () => window.clearInterval(timer);
  }, [
    acCurrentA,
    acRotorTargetAngleDeg,
    allowAcRotorMotion,
    labPart,
    playingAc,
  ]);

  const signedRelativeRotorAngleDeg = Math.max(
    -90,
    Math.min(90, shortestAngle(rotorAngleDeg, sourceAngleDeg)),
  );
  const checkpointAngleDeg = nearestCheckpoint(Math.abs(signedRelativeRotorAngleDeg));
  const activeFrame = fieldFrames[fieldSource]?.[checkpointAngleDeg]
    ?? fieldFrames.combined?.[checkpointAngleDeg]
    ?? null;
  const permanentMagnetData = React.useMemo(
    () => {
      if (!activeFrame) return null;
      return signedRelativeRotorAngleDeg < 0
        ? mirrorFieldDataAcrossX(activeFrame)
        : activeFrame;
    },
    [activeFrame, signedRelativeRotorAngleDeg],
  );
  const electromagnetData = React.useMemo(() => {
    if (!electromagnetActive) return null;
    const sourceFrames = electromagnetFrames[fieldSource];
    if (labPart === 'ac' && allowAcRotorMotion && fieldSource === 'combined') {
      if (
        Math.abs(electromagnetCurrentA) < 0.01
        && Math.abs(rotorAngleDeg - ROTOR_START_ANGLE_DEG) < 0.45
      ) return sourceFrames?.zero ?? null;
      const framePolarity: DcReleasePolarity = acAngleDeg > 180
        ? 'negative'
        : 'positive';
      const frameAngleDeg = nearestAngle(rotorAngleDeg, AC_ROTOR_ANGLES);
      const frame = dcReleaseFrames[framePolarity]?.[frameAngleDeg];
      return frame
        ? { ...frame, source_current_a: electromagnetCurrentA }
        : sourceFrames?.zero ?? null;
    }
    if (labPart === 'dc' && fieldSource === 'combined' && dcReleasePolarity) {
      const releaseAngles = dcReleasePolarity === 'positive'
        ? POSITIVE_DC_ANGLES
        : NEGATIVE_DC_ANGLES;
      const frameAngleDeg = nearestAngle(rotorAngleDeg, releaseAngles);
      return dcReleaseFrames[dcReleasePolarity]?.[frameAngleDeg] ?? null;
    }
    if (fieldSource === 'rotor') return sourceFrames?.zero ?? null;
    const magnitude = Math.abs(electromagnetCurrentA);
    if (magnitude < 0.01) return sourceFrames?.zero ?? null;
    const frame = electromagnetCurrentA > 0
      ? sourceFrames?.positive
      : sourceFrames?.negative;
    return frame && sourceFrames?.zero
      ? interpolateElectromagnetFrame(
        sourceFrames.zero,
        frame,
        magnitude / ELECTROMAGNET_PEAK_CURRENT_A,
        electromagnetCurrentA,
      )
      : null;
  }, [
    acAngleDeg,
    allowAcRotorMotion,
    dcReleaseFrames,
    dcReleasePolarity,
    electromagnetActive,
    electromagnetCurrentA,
    electromagnetFrames,
    fieldSource,
    labPart,
    rotorAngleDeg,
  ]);
  const electromagnetCenterFieldT = electromagnetData?.metrics?.center_b_t ?? 0;
  const woundSourceCenterFieldT = (
    electromagnetFrames.stator?.positive?.metrics?.center_b_t
    ?? null
  );
  const woundSourceMatchPercent = (
    sourceCenterFieldT !== null
    && sourceCenterFieldT > 0
    && woundSourceCenterFieldT !== null
  )
    ? ((woundSourceCenterFieldT / sourceCenterFieldT) - 1) * 100
    : null;
  const electromagnetFieldDirection = Math.abs(electromagnetCurrentA) < 0.01
    ? 'Coil target off'
    : electromagnetCurrentA > 0
      ? 'Right (+X)'
      : 'Left (-X)';
  const electromagnetPoleFaces = Math.abs(electromagnetCurrentA) < 0.01
    ? 'No active poles'
    : electromagnetCurrentA > 0
      ? 'Left N · right S'
      : 'Left S · right N';
  const displayedData = electromagnetActive ? electromagnetData : permanentMagnetData;
  const displayedRotorAngleDeg = electromagnetActive
    ? displayedData?.rotor_angle_deg ?? ROTOR_START_ANGLE_DEG
    : signedRelativeRotorAngleDeg < 0
      ? -checkpointAngleDeg
      : checkpointAngleDeg;

  const intensityRange = React.useMemo(() => {
    const selectedElectromagnetFrames = electromagnetFrames[fieldSource];
    const dcReleaseValues = fieldSource === 'combined'
      ? [
        ...AC_ROTOR_ANGLES.flatMap(
          (angleDeg) => dcReleaseFrames.positive?.[angleDeg]?.element_b_mag_t ?? [],
        ),
        ...AC_ROTOR_ANGLES.flatMap(
          (angleDeg) => dcReleaseFrames.negative?.[angleDeg]?.element_b_mag_t ?? [],
        ),
      ]
      : [];
    const sourceValues = electromagnetActive
      ? [
        ...(selectedElectromagnetFrames?.positive?.element_b_mag_t ?? []),
        ...(selectedElectromagnetFrames?.zero?.element_b_mag_t ?? []),
        ...(selectedElectromagnetFrames?.negative?.element_b_mag_t ?? []),
        ...dcReleaseValues,
      ]
      : (displayedData?.element_b_mag_t ?? []);
    const values = sourceValues.filter((value) => Number.isFinite(value) && value >= 0);
    if (!values.length) return undefined;
    const sorted = [...values].sort((left, right) => left - right);
    return {
      low: sorted[Math.floor(sorted.length * 0.03)],
      high: sorted[Math.floor(sorted.length * 0.98)],
    };
  }, [
    dcReleaseFrames,
    displayedData,
    electromagnetActive,
    electromagnetFrames,
    fieldSource,
  ]);

  const vectorAngleDeg = electromagnetActive && fieldSource === 'rotor'
    ? displayedRotorAngleDeg
    : electromagnetActive
      ? (electromagnetCurrentA >= 0 ? 0 : 180)
    : fieldSource === 'rotor'
      ? displayedRotorAngleDeg
      : sourceAngleDeg;
  const vectorAngleRad = vectorAngleDeg * Math.PI / 180;
  const vectorStrength = electromagnetActive && fieldSource === 'rotor'
    ? 1
    : electromagnetActive
    ? Math.min(1, Math.abs(electromagnetCurrentA) / ELECTROMAGNET_PEAK_CURRENT_A)
    : 1;
  const torqueTargetAngleDeg = labPart === 'dc'
    ? dcTargetAngleDeg
    : labPart === 'release' || labPart === 'chase'
      ? sourceAngleDeg
      : null;
  const torqueMechanismVisible = Boolean(
    displayedData
    && fieldSource === 'combined'
    && torqueTargetAngleDeg !== null,
  );
  const torqueErrorDeg = torqueTargetAngleDeg === null
    ? 0
    : shortestAngle(torqueTargetAngleDeg, displayedRotorAngleDeg);
  const torqueDirection = Math.abs(torqueErrorDeg) < 1
    ? undefined
    : torqueErrorDeg > 0
      ? 'ccw' as const
      : 'cw' as const;
  const torqueDirectionLabel = torqueDirection === 'ccw'
    ? 'Counter-clockwise'
    : torqueDirection === 'cw'
      ? 'Clockwise'
      : torqueTargetAngleDeg === null
        ? 'No applied field'
        : 'Zero at alignment';
  const fieldDirectionLabel = torqueTargetAngleDeg === null
    ? 'off'
    : Math.cos(torqueTargetAngleDeg * Math.PI / 180) >= 0
      ? 'right (+X)'
      : 'left (−X)';
  const southForceDirectionLabel = torqueTargetAngleDeg === null
    ? 'off'
    : Math.cos(torqueTargetAngleDeg * Math.PI / 180) >= 0
      ? 'left (−X)'
      : 'right (+X)';
  const baseDirectionVectors: MeshViewerDirectionVector[] = displayedData && vectorStrength > 0.015 ? [{
    x1Mm: 0,
    y1Mm: 0,
    x2Mm: FIELD_VECTOR_LENGTH_MM * vectorStrength * Math.cos(vectorAngleRad),
    y2Mm: FIELD_VECTOR_LENGTH_MM * vectorStrength * Math.sin(vectorAngleRad),
    label: electromagnetActive && fieldSource === 'rotor'
      ? 'Rotor N axis'
      : electromagnetActive
      ? (labPart === 'dc' ? 'DC field target' : 'Alternating B')
      : fieldSource === 'rotor'
        ? 'Rotor N axis'
        : fieldSource === 'stator'
          ? 'Stator B'
          : 'B target',
    labelXmm: FIELD_VECTOR_LENGTH_MM * 0.58 * vectorStrength * Math.cos(vectorAngleRad),
    labelYmm: FIELD_VECTOR_LENGTH_MM * 0.58 * vectorStrength * Math.sin(vectorAngleRad) + 3,
    tone: 'cyan',
    strokeScale: 0.25,
  }] : [];

  const rotorAngleRad = displayedRotorAngleDeg * Math.PI / 180;
  const rotorAxisLengthMm = displayedData
    ? displayedData.rotor_length_mm * 0.78
    : FIELD_VECTOR_LENGTH_MM * 0.5;
  const directionVectors: MeshViewerDirectionVector[] = torqueMechanismVisible
    ? [
      ...baseDirectionVectors,
      {
        x1Mm: 0,
        y1Mm: 0,
        x2Mm: rotorAxisLengthMm * Math.cos(rotorAngleRad),
        y2Mm: rotorAxisLengthMm * Math.sin(rotorAngleRad),
        label: 'rotor m',
        labelXmm: rotorAxisLengthMm * 0.62 * Math.cos(rotorAngleRad),
        labelYmm: rotorAxisLengthMm * 0.62 * Math.sin(rotorAngleRad) - 2.4,
        tone: 'amber',
        dashed: true,
        strokeScale: 0.2,
      },
    ]
    : baseDirectionVectors;
  const forceVectors: MeshViewerForceVector[] = torqueMechanismVisible && displayedData
    && torqueTargetAngleDeg !== null
    ? (() => {
      const halfRotorLengthMm = displayedData.rotor_length_mm * 0.46;
      const forceLengthMm = 7.4 * Math.max(0.45, vectorStrength);
      const fieldAngleRad = torqueTargetAngleDeg * Math.PI / 180;
      const rotorEndX = halfRotorLengthMm * Math.cos(rotorAngleRad);
      const rotorEndY = halfRotorLengthMm * Math.sin(rotorAngleRad);
      const forceX = forceLengthMm * Math.cos(fieldAngleRad);
      const forceY = forceLengthMm * Math.sin(fieldAngleRad);
      return [
        {
          x1Mm: rotorEndX,
          y1Mm: rotorEndY,
          x2Mm: rotorEndX + forceX,
          y2Mm: rotorEndY + forceY,
          label: 'F_N',
        },
        {
          x1Mm: -rotorEndX,
          y1Mm: -rotorEndY,
          x2Mm: -rotorEndX - forceX,
          y2Mm: -rotorEndY - forceY,
          label: 'F_S',
        },
      ];
    })()
    : [];
  const dipoleMarkers: MeshViewerDipoleMarker[] = torqueMechanismVisible && displayedData
    ? [{
      xMm: 0,
      yMm: 0,
      angleDeg: displayedRotorAngleDeg,
      lengthMm: displayedData.rotor_length_mm,
      thicknessMm: displayedData.rotor_thickness_mm,
      torqueDirection,
      animateTorque: releasing,
    }]
    : [];
  const rotorLabels: MeshViewerPointLabel[] = displayedData ? [
    {
      xMm: -3.6 * Math.cos(rotorAngleRad),
      yMm: -3.6 * Math.sin(rotorAngleRad),
      label: 'S',
      tone: 'south',
      scale: 0.25,
    },
    {
      xMm: 3.6 * Math.cos(rotorAngleRad),
      yMm: 3.6 * Math.sin(rotorAngleRad),
      label: 'N',
      tone: 'north',
      scale: 0.25,
    },
  ] : [];
  const electromagnetCurrentSign = electromagnetCurrentA > 0.01
    ? 1
    : electromagnetCurrentA < -0.01
      ? -1
      : 0;
  const electromagnetTopCue = electromagnetCurrentSign > 0
    ? '•'
    : electromagnetCurrentSign < 0
      ? '×'
      : '0';
  const electromagnetBottomCue = electromagnetCurrentSign > 0
    ? '×'
    : electromagnetCurrentSign < 0
      ? '•'
      : '0';
  const electromagnetTopDirection = electromagnetCurrentSign === 0
    ? 'current off'
    : electromagnetCurrentSign > 0
      ? 'out of screen (+Z)'
      : 'into screen (-Z)';
  const electromagnetBottomDirection = electromagnetCurrentSign === 0
    ? 'current off'
    : electromagnetCurrentSign > 0
      ? 'into screen (-Z)'
      : 'out of screen (+Z)';
  const electromagnetLabels: MeshViewerPointLabel[] = React.useMemo(() => {
    const frame = electromagnetData;
    if (!frame) return [];
    const statorInnerX = 0.5 * frame.rotor_length_mm + frame.pole_gap_mm;
    const coilX = statorInnerX + 0.5 * frame.stator_magnet_width_mm;
    const coilY = frame.coil_y_mm;
    const faceLabels: MeshViewerPointLabel[] = electromagnetCurrentSign === 0 ? [] : [
      {
        xMm: -statorInnerX,
        yMm: 0,
        label: electromagnetCurrentSign > 0 ? 'N' : 'S',
        tone: electromagnetCurrentSign > 0 ? 'north' : 'south',
        scale: 0.8,
      },
      {
        xMm: statorInnerX,
        yMm: 0,
        label: electromagnetCurrentSign > 0 ? 'S' : 'N',
        tone: electromagnetCurrentSign > 0 ? 'south' : 'north',
        scale: 0.8,
      },
    ];
    return [
      ...faceLabels,
      ...[-coilX, coilX].flatMap((xMm): MeshViewerPointLabel[] => [
        { xMm, yMm: coilY, label: electromagnetTopCue, tone: 'neutral', scale: 0.68 },
        { xMm, yMm: -coilY, label: electromagnetBottomCue, tone: 'neutral', scale: 0.68 },
      ]),
    ];
  }, [
    electromagnetBottomCue,
    electromagnetCurrentSign,
    electromagnetData,
    electromagnetTopCue,
  ]);

  const setStage = React.useCallback((next: 'design' | 'solve') => {
    setQuizOpen(false);
    onStageChange?.(next);
  }, [onStageChange]);

  const solveFrameSet = async (source: RotorChaseFieldSource) => {
    // The checkpoints are independent solves, so ask for them together.
    const entries = await Promise.all(FEM_CHECKPOINT_ANGLES.map(async (angleDeg) => {
      const frame = await solveClient.fetchRotorChaseSolve(source, angleDeg, SOURCE_POLE_GAP_MM);
      return [angleDeg, frame] as const;
    }));
    return Object.fromEntries(entries) as Record<number, RotorChaseFieldData>;
  };

  const solveDcReleaseFrameSet = async (
    polarity: DcReleasePolarity,
    angles: readonly number[],
    onFrameSolved?: () => void,
  ) => {
    const currentA = polarity === 'positive'
      ? ELECTROMAGNET_PEAK_CURRENT_A
      : -ELECTROMAGNET_PEAK_CURRENT_A;
    const entries = await Promise.all(angles.map(async (angleDeg) => {
      const frame = await solveClient.fetchRotorChaseSolve(
        'combined',
        angleDeg,
        SOURCE_POLE_GAP_MM,
        'electromagnet',
        currentA,
      );
      onFrameSolved?.();
      return [angleDeg, frame] as const;
    }));
    return Object.fromEntries(entries) as Record<number, RotorChaseFieldData>;
  };

  const solveElectromagnetFrameSet = async () => {
    setElectromagnetBusy(true);
    setElectromagnetSolveProgress(0);
    setError(null);
    try {
      const markFrameSolved = () => {
        setElectromagnetSolveProgress((previous) => Math.min(
          ELECTROMAGNET_INITIAL_SOLVE_COUNT,
          previous + 1,
        ));
      };
      const solveTrackedFrame = async (
        fieldSourceToSolve: RotorChaseFieldSource,
        currentA: number,
      ) => {
        const frame = await solveClient.fetchRotorChaseSolve(
          fieldSourceToSolve,
          ROTOR_START_ANGLE_DEG,
          SOURCE_POLE_GAP_MM,
          'electromagnet',
          currentA,
        );
        markFrameSolved();
        return frame;
      };
      const [
        combinedPositiveFrames,
        combinedNegativeFrames,
        combinedZero,
        statorPositive,
        statorZero,
        statorNegative,
        rotorZero,
      ] = await Promise.all([
        solveDcReleaseFrameSet('positive', POSITIVE_DC_ANGLES, markFrameSolved),
        solveDcReleaseFrameSet('negative', NEGATIVE_DC_ANGLES, markFrameSolved),
        solveTrackedFrame('combined', 0),
        solveTrackedFrame('stator', ELECTROMAGNET_PEAK_CURRENT_A),
        solveTrackedFrame('stator', 0),
        solveTrackedFrame('stator', -ELECTROMAGNET_PEAK_CURRENT_A),
        solveTrackedFrame('rotor', 0),
      ]);
      setElectromagnetFrames({
        combined: {
          positive: combinedPositiveFrames[ROTOR_START_ANGLE_DEG],
          zero: combinedZero,
          negative: combinedNegativeFrames[ROTOR_START_ANGLE_DEG],
        },
        stator: {
          positive: statorPositive,
          zero: statorZero,
          negative: statorNegative,
        },
        rotor: { zero: rotorZero },
      });
      setDcReleaseFrames({
        positive: combinedPositiveFrames,
        negative: combinedNegativeFrames,
      });
      setFieldSource('combined');
      return true;
    } catch (solveError) {
      setError(solveError instanceof Error
        ? solveError.message
        : 'The wound-pole field solves failed.');
      return false;
    } finally {
      setElectromagnetBusy(false);
    }
  };

  const solveSourceField = async () => {
    setBusy(true);
    setError(null);
    try {
      const [combined, statorReference] = await Promise.all([
        solveFrameSet('combined'),
        solveClient.fetchRotorChaseSolve('stator', 0, SOURCE_POLE_GAP_MM),
      ]);
      setFieldFrames({ combined });
      setStatorReferenceFrame(statorReference);
      setFieldSource('combined');
      setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
      // The step and its progress are left as they are: on a first solve they
      // are still at their start, and a reopened lesson keeps what it restored.
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The permanent-magnet source-field solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const selectFieldSource = async (nextSource: RotorChaseFieldSource) => {
    if (electromagnetActive && electromagnetFrames[nextSource]) {
      setFieldSource(nextSource);
      return;
    }
    if (fieldFrames[nextSource]) {
      setFieldSource(nextSource);
      return;
    }
    setLoadingSource(nextSource);
    setError(null);
    try {
      const frames = await solveFrameSet(nextSource);
      setFieldFrames((previous) => ({ ...previous, [nextSource]: frames }));
      setFieldSource(nextSource);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : `The ${nextSource} field solve failed.`);
    } finally {
      setLoadingSource(null);
    }
  };

  const releaseRotor = () => {
    if (labPart === 'dc') {
      if (dcTargetAngleDeg === null) return;
      setFieldSource('combined');
      setReleasing(true);
      return;
    }
    setReleasing(true);
  };

  const resetRelease = () => {
    setReleasing(false);
    setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
  };

  const enterChase = () => {
    if (labPart === 'chase') {
      return;
    }
    setLabPart('chase');
    setReleasing(false);
    setRotorAngleDeg(60);
    setSecondAlignmentComplete(false);
  };

  const enterDc = async () => {
    setPlayingAc(false);
    setLabPart('dc');
    setDcCurrentA(ELECTROMAGNET_PEAK_CURRENT_A);
    setSawPositiveDc(true);
    setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
    setReleasing(false);
    if (!hasElectromagnetField) {
      await solveElectromagnetFrameSet();
    }
  };

  const setDcTarget = (currentA: number) => {
    setReleasing(false);
    setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
    setDcCurrentA(currentA);
    if (currentA > 0) setSawPositiveDc(true);
    if (currentA < 0) setSawNegativeDc(true);
  };

  const plotCurrentForcePair = () => {
    const roundedCurrentA = Math.round(dcCurrentA * 2) / 2;
    setPlottedForceCurrentsA((previous) => (
      previous.some((sampleCurrentA) => Math.abs(sampleCurrentA - roundedCurrentA) < 0.01)
        ? previous
        : [...previous, roundedCurrentA].sort((left, right) => left - right)
    ));
  };

  const enterAc = async () => {
    if (!hasElectromagnetField) {
      const solved = await solveElectromagnetFrameSet();
      if (!solved) return;
    }
    setLabPart('ac');
    setReleasing(false);
    setPlayingAc(false);
    setAcAngleDeg(0);
    setAllowAcRotorMotion(false);
    setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
  };

  const toggleAcRotorMotion = async () => {
    if (allowAcRotorMotion) {
      setAllowAcRotorMotion(false);
      setPlayingAc(false);
      setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
      return;
    }

    setPlayingAc(false);
    setFieldSource('combined');
    setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
    if (!hasAcRotorMotionFrames) {
      setAcRotorMotionBusy(true);
      setError(null);
      try {
        const [positiveExtraFrames, negativeExtraFrames] = await Promise.all([
          solveDcReleaseFrameSet('positive', AC_POSITIVE_EXTRA_ANGLES),
          solveDcReleaseFrameSet('negative', AC_NEGATIVE_EXTRA_ANGLES),
        ]);
        setDcReleaseFrames((previous) => ({
          positive: {
            ...previous.positive,
            ...positiveExtraFrames,
          },
          negative: {
            ...previous.negative,
            ...negativeExtraFrames,
          },
        }));
      } catch (solveError) {
        setError(solveError instanceof Error
          ? solveError.message
          : 'The free-rotor angle solves failed.');
        return;
      } finally {
        setAcRotorMotionBusy(false);
      }
    }
    setAllowAcRotorMotion(true);
  };

  enterAcRef.current = enterAc;

  React.useEffect(() => {
    if (lessonStage === 'solve' && hasSolvedField) setStoredLabPart(labPart);
  }, [hasSolvedField, labPart, lessonStage, setStoredLabPart]);

  // Reopened after a reload or a trip to the catalog: solve the fixed-field
  // frames again, then go back to the part of the lab the student was in
  // (the wound-pole parts solve their own frames on the way).
  useLessonResume(LESSON_ID, lessonStage, predictionDone ? () => {
    const part = storedLabPart;
    setStage('solve');
    void (async () => {
      await solveSourceField();
      if (part === 'chase') {
        setLabPart('chase');
        setReleasing(false);
      } else if (part === 'dc') {
        await enterDc();
      } else if (part === 'ac') {
        await enterAc();
      }
    })();
  } : null);

  const playAcCycle = () => {
    setAcAngleDeg(0);
    if (allowAcRotorMotion) setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
    setPlayingAc(true);
  };

  const stepAc = (direction: 1 | -1) => {
    setPlayingAc(false);
    setAcAngleDeg((previous) => Math.max(
      0,
      Math.min(360, previous + direction * AC_STEP_DEG),
    ));
  };

  const setRotorOffset = (angleDeg: number) => {
    setReleasing(false);
    setSecondAlignmentComplete(false);
    const clampedAngle = Math.max(-90, Math.min(90, angleDeg));
    setRotorAngleDeg(normalizeAngle(clampedAngle));
  };

  const stepRotor = (stepDirection: 1 | -1) => {
    setRotorOffset(signedRelativeRotorAngleDeg + stepDirection * MANUAL_STEP_DEG);
  };

  const activeProgressStepId: LessonSixProgressStepId = quizOpen
    ? 'check'
    : lessonStage === 'design'
      ? 'predict'
      : labPart;

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'release', label: 'Align', complete: alignedOnce, available: predictionDone },
    { id: 'chase', label: 'New start', complete: movingTargetComplete, available: alignedDone },
    { id: 'dc', label: 'Reverse DC', complete: dcComplete, available: movingTargetDone },
    { id: 'ac', label: 'One-phase AC', complete: playedAc, available: dcDone },
    { id: 'check', label: 'Check', complete: quizPassed, available: acDone },
  ], [
    acDone,
    alignedDone,
    alignedOnce,
    dcComplete,
    dcDone,
    movingTargetComplete,
    movingTargetDone,
    playedAc,
    predictionCorrect,
    predictionDone,
    quizPassed,
  ]);

  const selectProgressStep = React.useCallback((stepId: string) => {
    const nextStep = stepId as LessonSixProgressStepId;
    if (nextStep === 'predict') {
      setStage('design');
      return;
    }
    if (nextStep === 'release' && predictionDone) {
      setStage('solve');
      setLabPart('release');
      return;
    }
    if (nextStep === 'chase' && alignedDone) {
      setStage('solve');
      setLabPart('chase');
      setReleasing(false);
      return;
    }
    if (nextStep === 'dc' && movingTargetDone) {
      setStage('solve');
      setPlayingAc(false);
      setLabPart('dc');
      setDcCurrentA(ELECTROMAGNET_PEAK_CURRENT_A);
      setSawPositiveDc(true);
      setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
      setReleasing(false);
      return;
    }
    if (nextStep === 'ac' && dcDone) {
      setStage('solve');
      if (!hasElectromagnetField) {
        // Reopened without its solved frames: the wound poles are solved
        // first, then the step opens.
        void enterAcRef.current();
        return;
      }
      setLabPart('ac');
      setReleasing(false);
      setPlayingAc(false);
      setAllowAcRotorMotion(false);
      setRotorAngleDeg(ROTOR_START_ANGLE_DEG);
      return;
    }
    if (nextStep === 'check' && acDone) {
      onStageChange?.('solve');
      setQuizOpen(true);
    }
  }, [
    acDone,
    alignedDone,
    dcDone,
    hasElectromagnetField,
    movingTargetDone,
    onStageChange,
    predictionDone,
    setStage,
  ]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 6,
    lessonCount: 10,
    title: 'Give the Rotor Something to Chase',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const currentGoal = LESSON_SIX_GOALS[activeProgressStepId];
  const evidenceTitle = labPart === 'release'
    ? 'Fixed-field torque'
    : labPart === 'chase'
      ? 'One target, two starts'
      : labPart === 'dc'
        ? 'Current reverses the target'
        : 'One phase only oscillates';
  const labInsight = !hasSolvedField
    ? 'Solve one fixed field, then let the rotor reveal its only stable target.'
    : labPart === 'release'
      ? alignedOnce
        ? 'The rotor aligned once and torque fell to zero.'
        : 'Release the rotor from 90°. Watch torque disappear at alignment.'
      : labPart === 'chase'
        ? secondAlignmentComplete
          ? 'A different start reached the same target. Now move the target electrically.'
          : 'Choose a new starting angle; the fixed field still owns the destination.'
        : labPart === 'dc'
          ? dcComplete
            ? 'Reversing DC reversed the magnetic target.'
            : 'Change polarity, then release the rotor toward the new target.'
          : playedAc
            ? 'One AC phase flips the target; it never advances around the stator.'
            : 'Play one cycle and watch the rotor reverse every half-cycle.';
  const dockPrimaryLabel = !hasSolvedField
    ? busy ? 'Solving fixed field…' : 'Solve fixed field'
    : labPart === 'release'
      ? alignedOnce ? 'Next: New start' : releasing ? 'Aligning…' : 'Release rotor'
      : labPart === 'chase'
        ? secondAlignmentComplete
          ? electromagnetBusy ? 'Solving wound poles…' : 'Next: Reverse DC'
          : releasing ? 'Aligning…' : 'Release from this angle'
        : labPart === 'dc'
          ? !hasElectromagnetField
            ? electromagnetBusy ? 'Solving wound poles…' : 'Retry wound-pole solve'
            : dcComplete
              ? 'Next: One-phase AC'
              : releasing
                ? 'Aligning…'
                : dcRotorAtTarget
                  ? 'Choose opposite current'
                  : 'Release rotor'
          : playedAc ? 'Continue to Check' : playingAc ? 'Playing one cycle…' : 'Play one AC cycle';
  const dockPrimaryDisabled = busy
    || releasing
    || (labPart === 'chase' && secondAlignmentComplete && electromagnetBusy)
    || (labPart === 'dc' && electromagnetBusy)
    || (labPart === 'ac' && (playingAc || acRotorMotionBusy));

  const runDockPrimaryAction = () => {
    if (!hasSolvedField) {
      void solveSourceField();
      return;
    }
    if (labPart === 'release') {
      if (alignedOnce) enterChase();
      else releaseRotor();
      return;
    }
    if (labPart === 'chase') {
      if (secondAlignmentComplete) void enterDc();
      else releaseRotor();
      return;
    }
    if (labPart === 'dc') {
      if (!hasElectromagnetField) {
        void solveElectromagnetFrameSet();
      } else if (dcComplete) {
        void enterAc();
      } else if (dcRotorAtTarget || dcTargetAngleDeg === null) {
        // Nothing to release yet: point the student at the current presets.
        // Entering this step counts +8 A as seen, so the polarity still
        // missing is -8 A, the last preset.
        const choice = dcCurrentChoiceRef.current;
        choice?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        const presets = choice?.querySelectorAll('button');
        presets?.[presets.length - 1]?.focus();
      } else {
        releaseRotor();
      }
      return;
    }
    if (playedAc) {
      setQuizOpen(true);
    } else {
      playAcCycle();
    }
  };

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  const currentStepNumber = Math.max(1, lessonProgressSteps.findIndex((item) => item.id === activeProgressStepId) + 1);
  const currentStepLabel = lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label ?? '';
  const goalCard = (
    <LessonGoal step={currentStepNumber} total={lessonProgressSteps.length} title={currentGoal.title} detail={currentGoal.detail} />
  );
  const signedCurrentLabel = `${electromagnetCurrentA >= 0 ? '+' : ''}${electromagnetCurrentA.toFixed(2)} A`;

  // The chip on the canvas names what is drawn: the selected source, then the
  // one number that changes while the student works.
  const drawnSourceName = electromagnetActive
    ? fieldSource === 'stator'
      ? labPart === 'dc' ? 'DC electromagnet' : 'One-phase electromagnet'
      : fieldSource === 'rotor'
        ? 'PM rotor'
        : labPart === 'dc' ? 'DC electromagnet + PM rotor' : 'One-phase field + PM rotor'
    : fieldSource === 'stator'
      ? 'PM stator'
      : fieldSource === 'rotor' ? 'PM rotor' : 'PM stator + rotor';
  const viewportLabel = `${drawnSourceName} · ${electromagnetActive ? signedCurrentLabel : `rotor ${displayAngle(rotorAngleDeg)}`}`;

  // The canvas controls, in the same dock as the motor workspace. Until a
  // field is solved the dock is shown greyed out, so the canvas keeps its size.
  const renderViewDock = (unsolved: boolean) => {
    // The 3D view is an illustrative extrusion: it has no field layers or mesh.
    const layersOff = unsolved || showThreeD;
    return (
      <LessonDock
        tabs={[
          { id: '2d', label: '2D' },
          { id: '3d', label: '3D', disabled: unsolved, title: unsolved ? 'Solve the field first' : undefined },
        ]}
        tab={showThreeD && !unsolved ? '3d' : '2d'}
        onTab={(id) => setShowThreeD(id === '3d')}
        // The 3D scene shows its own orbit hint, so its dock end stays empty.
        end={unsolved ? 'Solve to see the field' : showThreeD ? null : <span ref={setZoomSlot} />}
      >
        <LessonDockGroup label="Source">
          <LessonSegmented
            label="Magnetic field source selection"
            value={unsolved ? null : fieldSource}
            onChange={(source) => void selectFieldSource(source)}
            options={FIELD_SOURCE_OPTIONS.map((option) => ({
              id: option.id,
              label: loadingSource === option.id ? 'Solving…' : option.label,
              disabled: unsolved || loadingSource !== null,
              title: option.title,
            }))}
          />
        </LessonDockGroup>
        <LessonDockGroup label="Show">
          <LessonDockToggle
            pressed={showFieldLines && !layersOff}
            onChange={setShowFieldLines}
            disabled={layersOff}
            title="Lines that follow the direction of the field"
          >
            Field lines
          </LessonDockToggle>
          <LessonDockToggle
            pressed={showFluxDensity && !layersOff}
            onChange={setShowFluxDensity}
            disabled={layersOff}
            title="Colour by field strength, |B|"
          >
            Flux density
          </LessonDockToggle>
          <LessonDockToggle
            pressed={showMesh && !layersOff}
            onChange={setShowMesh}
            disabled={layersOff}
            title="The triangles the solver divides the space into"
          >
            Mesh
          </LessonDockToggle>
        </LessonDockGroup>
      </LessonDock>
    );
  };

  const renderSolvedCanvas = (data: RotorChaseFieldData) => (
    <LessonLabCanvas className="rotor-chase-canvas">
      <LessonLabViewport label={viewportLabel} hint={loadingSource ? 'Solving the selected source…' : undefined}>
        {showThreeD ? (
          <RotorChase3D
            fieldData={data}
            fieldSource={fieldSource}
            rotorAngleDeg={displayedRotorAngleDeg}
            sourceCurrentA={electromagnetActive ? electromagnetCurrentA : N42_REMANENCE_T}
          />
        ) : (
          <MeshViewer
            meshData={data}
            embedded
            compactEmbedded
            toolbarMode="zoom-only"
            zoomControlsSlot={zoomSlot}
            showMeshEdges={showMesh}
            showFieldIntensity={showFluxDensity}
            fieldIntensityRange={intensityRange}
            smoothFieldIntensity
            fieldLinesVisible={showFieldLines}
            animateFieldArrows={(releasing || playingAc) && showFieldLines}
            viewportPanEnabled={false}
            splitForceMagnetPolarity={!electromagnetActive}
            forceMagnetPolarityAxisDeg={electromagnetActive ? undefined : sourceAngleDeg}
            directionVectors={directionVectors}
            forceVectors={forceVectors}
            dipoleMarkers={dipoleMarkers}
            pointLabels={torqueMechanismVisible
              ? electromagnetActive
                ? electromagnetLabels
                : []
              : electromagnetActive
                ? fieldSource === 'stator'
                  ? electromagnetLabels
                  : fieldSource === 'rotor'
                    ? rotorLabels
                    : [...electromagnetLabels, ...rotorLabels]
                : rotorLabels}
          />
        )}
      </LessonLabViewport>
      {renderViewDock(false)}
    </LessonLabCanvas>
  );

  // Shown in place of the picture while the wound-pole frames are solved (or
  // after that solve failed). The retry is the primary button on the left.
  const renderWoundPoleLoading = () => (
    <LessonLabCanvas className="rotor-chase-canvas">
      <LessonLabViewport
        label="DC electromagnet + PM rotor"
        hint={electromagnetBusy ? 'Solving…' : 'Not solved yet'}
        className="is-centered"
      >
        <div className="rotor-chase-electromagnet-loading-body" aria-live="polite">
          <i className={electromagnetBusy ? 'is-spinning' : 'has-error'} aria-hidden="true" />
          <p className="learning-kicker">Part 3 · current sets polarity</p>
          <h2>
            {electromagnetBusy
              ? 'Building the reversible wound-pole field...'
              : 'The wound-pole solve did not finish.'}
          </h2>
          <p>
            {electromagnetBusy
              ? 'The lab is already on Part 3. Magneto2D is solving both current polarities and the rotor-angle checkpoints needed for release.'
              : 'The permanent-magnet work is preserved. Retry the wound-pole frames from the experiment panel.'}
          </p>
          <div
            className="rotor-chase-solve-progress"
            role="progressbar"
            aria-label="Wound-pole FEM frame progress"
            aria-valuemin={0}
            aria-valuemax={ELECTROMAGNET_INITIAL_SOLVE_COUNT}
            aria-valuenow={electromagnetSolveProgress}
          >
            <b style={{
              width: `${(
                electromagnetSolveProgress
                / ELECTROMAGNET_INITIAL_SOLVE_COUNT
              ) * 100}%`,
            }}
            />
          </div>
          <strong>
            {electromagnetSolveProgress} / {ELECTROMAGNET_INITIAL_SOLVE_COUNT} FEM frames ready
          </strong>
        </div>
      </LessonLabViewport>
      {renderViewDock(true)}
    </LessonLabCanvas>
  );

  const renderUnsolvedCanvas = () => (
    <LessonLabCanvas className="rotor-chase-canvas">
      <LessonLabViewport
        label="Permanent-magnet source fixture"
        hint={busy ? 'Solving…' : 'Not solved yet'}
        className="is-centered"
      >
        <section className="rotor-chase-empty-stage">
          <PredictionDiagram />
          <div><h2>Solve the fixed source field first.</h2><p>Gmsh builds a corner-refined normal mesh. Magneto2D solves the permanent-magnet field that the rotor will try to follow.</p></div>
        </section>
      </LessonLabViewport>
      {renderViewDock(true)}
    </LessonLabCanvas>
  );

  const inspectPanel = (
    <LessonLabPanel
      side="inspect"
      kicker="Inspect"
      title={lessonStage === 'design' ? 'Nothing solved yet' : evidenceTitle}
      summary={lessonStage === 'design'
        ? 'Make your prediction first. The solved field and its measurements appear here in the next step.'
        : undefined}
      label="Lesson evidence and solved results"
      // New evidence appears at the top of the card: bring it back into view
      // when the step changes or a solve finishes.
      scrollTopKey={`${activeProgressStepId}:${hasSolvedField}:${hasElectromagnetField}`}
    >
      {lessonStage === 'design' ? (
        <LessonOutline
          steps={lessonProgressSteps.map((item) => ({
            id: item.id,
            label: item.label,
            detail: LESSON_SIX_GOALS[item.id as LessonSixProgressStepId].detail,
          }))}
          currentId={activeProgressStepId}
        />
      ) : !hasSolvedField ? (
        <section className="rotor-chase-status-empty">
          <p className="learning-kicker">Solved alignment response</p>
          <h2>{busy ? 'Building eight FEM checkpoints' : 'Awaiting the source-field solve'}</h2>
          <p>Torque, angle, and the analytic-versus-FEM comparison will appear here when the fixed-field frames are ready.</p>
        </section>
      ) : electromagnetActive && !displayedData ? (
        <section className="rotor-chase-status-empty" aria-live="polite">
          <p className="learning-kicker">Wound-pole source</p>
          <h2>{electromagnetBusy ? 'Solving reversible-field frames' : 'Wound-pole frames need attention'}</h2>
          <p>{electromagnetSolveProgress} of {ELECTROMAGNET_INITIAL_SOLVE_COUNT} frames are ready. The permanent-magnet alignment results remain preserved.</p>
        </section>
      ) : (
        <section className="rotor-chase-results">
          {labPart === 'release' || labPart === 'chase' ? (
            <>
              <div className="rotor-chase-result-copy">
                <p className="learning-kicker">
                  {labPart === 'release' ? 'Part 1 · fixed target' : 'Part 2 · another starting angle'}
                </p>
                <h2>
                  {labPart === 'release'
                    ? 'The rotor turns only until it aligns.'
                    : 'Different starts, same fixed destination.'}
                </h2>
                <p>
                  {labPart === 'release'
                    ? 'Torque peaks near a 90° error and falls to zero at alignment.'
                    : 'Only the PM rotor moved. The stator field stayed fixed, so the destination did not follow the starting angle.'}
                </p>
              </div>
              <ForceCoupleCard
                fieldActive
                fieldDirection={fieldDirectionLabel}
                southForceDirection={southForceDirectionLabel}
                torqueAngleDeg={misalignmentDeg}
                torqueDirection={torqueDirectionLabel}
              />
              <TorquePlotPanel
                misalignmentDeg={misalignmentDeg}
                analyticPeakTorqueNm={analyticPeakTorqueNm}
                femSamples={femTorqueSamples}
              />
              {/* The torque angle and both torque values are read once, in the
                  readout under the plot; this card adds what the plot does not show. */}
              <section className="rotor-chase-readout-card">
                <header><span>SOURCE FIELD</span><strong>{displayAngle(sourceAngleDeg)}</strong></header>
                <div><span>Rotor N–S axis</span><b>{displayAngle(rotorAngleDeg)}</b></div>
                <div><span>Displayed FEM frame</span><b>{checkpointAngleDeg}°</b></div>
                <div className="rotor-chase-equation">τz = (m × B)z = mB sin(field − rotor)</div>
              </section>
              <section className="rotor-chase-concept-card rotor-chase-torque-derivation">
                <span>WHY THE CURVE IS A SINE</span>
                <h3>Torque is the slope of magnetic energy.</h3>
                <div><b>U(δ) = −mB cos δ</b><i>lowest energy at alignment</i></div>
                <div><b>τ = −∂U/∂θᵣ = mB sin δ</b><i>turning component of m × B</i></div>
                <p>The cyan curve is the ideal dipole law. Amber FEM points include finite magnet size and fringing.</p>
              </section>
            </>
          ) : (
            <>
              <div className="rotor-chase-result-copy">
                <p className="learning-kicker">
                  {labPart === 'dc' ? 'Part 3 · current sets polarity' : 'Part 4 · one sinusoidal phase'}
                </p>
                <h2>
                  {labPart === 'dc'
                    ? 'Reverse DC, reverse the magnetic target.'
                    : 'The rotor flips back and forth; it does not spin.'}
                </h2>
                <p>
                  {labPart === 'dc'
                    ? 'The copper does not move. Reversing current swaps the wound-pole N/S faces and flips the fixed target by 180°.'
                    : 'Each half-cycle selects the opposite direction on the same fixed axis, so the rotor reverses instead of accumulating rotation.'}
                </p>
              </div>
              {labPart === 'dc' ? (
                <>
                  <ForceCoupleCard
                    fieldActive={dcTargetAngleDeg !== null}
                    fieldDirection={fieldDirectionLabel}
                    southForceDirection={southForceDirectionLabel}
                    torqueAngleDeg={torqueErrorDeg}
                    torqueDirection={torqueDirectionLabel}
                    reverseDc
                  />
                  <ForceCurrentPlot
                    currentA={dcCurrentA}
                    peakForceN={dcPeakPoleForceN}
                    peakTorqueNm={dcPeakTorqueNm}
                    leverArmMm={dcForceLeverArmMm}
                    plottedCurrentsA={plottedForceCurrentsA}
                  />
                  <div className="rotor-chase-dc-comparison">
                    <article className={dcCurrentA > 0 ? 'is-active' : ''}>
                      <span>+8 A</span><strong>Field points right</strong><p>Left pole N · right pole S</p>
                    </article>
                    <article className={Math.abs(dcCurrentA) < 0.01 ? 'is-active' : ''}>
                      <span>0 A</span><strong>Coil field switches off</strong><p>PM rotor field remains</p>
                    </article>
                    <article className={dcCurrentA < 0 ? 'is-active' : ''}>
                      <span>−8 A</span><strong>Field points left</strong><p>Left pole S · right pole N</p>
                    </article>
                  </div>
                </>
              ) : (
                <OnePhaseWaveform angleDeg={acAngleDeg} currentA={acCurrentA} />
              )}
              <section className="rotor-chase-readout-card">
                <header>
                  <span>WOUND-POLE SOURCE</span>
                  <strong>{signedCurrentLabel}</strong>
                </header>
                <div><span>Coil MMF · NI</span><b>{(ELECTROMAGNET_TURNS * electromagnetCurrentA).toFixed(0)} A-turn</b></div>
                <div><span>Inner pole faces</span><b>{electromagnetPoleFaces}</b></div>
                <div><span>Field target</span><b>{electromagnetFieldDirection}</b></div>
                <div><span>PM rotor N–S axis</span><b>{displayAngle(rotorAngleDeg)}</b></div>
                {labPart === 'dc' ? (
                  <>
                    <div><span>Alignment target</span><b>{dcTargetAngleDeg === null ? 'Off at 0 A' : displayAngle(dcTargetAngleDeg)}</b></div>
                    <div><span>Displayed FEM rotor frame</span><b>{displayAngle(displayedRotorAngleDeg)}</b></div>
                  </>
                ) : null}
                <div>
                  <span>Displayed field</span>
                  <b>{fieldSource === 'combined' ? 'Wound poles + PM rotor' : fieldSource === 'stator' ? 'Wound poles only' : 'PM rotor only'}</b>
                </div>
                <div><span>Earlier PM source at center |B|</span><b>{sourceCenterFieldT === null ? '—' : `${(sourceCenterFieldT * 1e3).toFixed(2)} mT`}</b></div>
                <div><span>Wound source at center |B|</span><b>{woundSourceCenterFieldT === null ? '—' : `${(woundSourceCenterFieldT * 1e3).toFixed(2)} mT`}</b></div>
                <div>
                  <span>Wound source vs earlier PM source</span>
                  <b>{woundSourceMatchPercent === null ? '—' : `${woundSourceMatchPercent >= 0 ? '+' : ''}${woundSourceMatchPercent.toFixed(1)}%`}</b>
                </div>
                <div><span>Displayed selection at center |B|</span><b>{(electromagnetCenterFieldT * 1e3).toFixed(2)} mT</b></div>
                <div className="rotor-chase-equation">magnetomotive force = N I</div>
                <p className="rotor-chase-source-match-note">
                  This equivalent {ELECTROMAGNET_TURNS.toLocaleString()}-turn teaching winding matches the earlier fixed-PM source near the center. Its large NI reflects the air-path tax, not a copper-loss or temperature design.
                </p>
              </section>
              {/* What the colours and the current marks on the canvas mean. */}
              <section className="lesson-lab-card rotor-chase-key-card" aria-label="Electromagnet cross-section key">
                <h3>Electromagnet cross-section</h3>
                <div className="rotor-chase-material-key">
                  <span><i className="is-copper" />Copper winding</span>
                  <span><i className="is-iron" />Electrical steel core</span>
                </div>
                <div className="rotor-chase-current-key">
                  <span><i>{electromagnetTopCue}</i>Top: {electromagnetTopDirection}</span>
                  <span><i>{electromagnetBottomCue}</i>Bottom: {electromagnetBottomDirection}</span>
                </div>
              </section>
              <section className="rotor-chase-concept-card">
                <span>{labPart === 'dc' ? 'PERMANENT MAGNET → ELECTROMAGNET' : 'WHY ONE PHASE IS NOT ENOUGH'}</span>
                <h3>
                  {labPart === 'dc'
                    ? 'The field can now be commanded electrically.'
                    : 'One winding alternates; it does not create a rotating field.'}
                </h3>
                <p>
                  {labPart === 'dc'
                    ? 'The electrical steel cores (grade M350-50A) guide the coil field around the N42 rotor. Reversing current swaps both current directions and the inner pole faces.'
                    : 'Positive and negative current select opposite directions on the same axis. Lesson 7 adds a second spatially shifted phase so the resultant direction can advance.'}
                </p>
              </section>
            </>
          )}
        </section>
      )}

      <LessonTerms terms={LESSON_SIX_TERMS} />
    </LessonLabPanel>
  );

  if (quizOpen) {
    return (
      <LessonLab className="rotor-chase-lab">
        {inspectPanel}
        <LessonLabStage className="is-tall">
          <LessonLabViewport label={`Knowledge check · ${QUIZ.length} questions`} className="is-scroll">
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Check"
          title="Why does a motor need a moving magnetic target?"
          label="Knowledge check"
          footer={(
            <LessonNextStep hint={quizPassed
              ? 'Lesson complete. The missing ingredient is a field that keeps advancing.'
              : 'Explain why one fixed axis cannot sustain rotation.'}
            >
              {quizPassed || lessonComplete ? (
                <a className="learning-primary-button" href="/tutorials/lesson-7">Next lesson</a>
              ) : null}
              <div className="lesson-lab-next-row">
                <LessonLink onClick={() => { setQuizOpen(false); setLabPart('ac'); }}>← Review experiment</LessonLink>
                <LessonLink onClick={onBackToCatalog}>All lessons</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <p className="lesson-lab-note">Separate the solver-backed magnetic checkpoints from the teaching motion model and identify where the energy comes from.</p>
        </LessonLabPanel>
      </LessonLab>
    );
  }

  if (lessonStage === 'design') {
    return (
      <LessonLab className="rotor-chase-lab">
        {inspectPanel}
        <LessonLabStage>
          <LessonLabViewport label="Permanent magnets · no coils yet" className="is-centered">
            <div className="rotor-chase-predict-picture"><PredictionDiagram /></div>
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Predict"
          title="What does a fixed field actually do?"
          summary="A permanent-magnet rotor begins 90° away. Decide what happens after release."
          label="Fixed-field rotor prediction"
          footer={(
            <LessonNextStep
              tone={prediction ? (predictionCorrect ? 'good' : 'warn') : undefined}
              hint={prediction
                ? predictionCorrect
                  ? 'Exactly. A fixed field creates one stable destination, not continuous rotation.'
                  : 'Watch the torque angle: what remains after the two magnetic axes line up?'
                : 'Make a prediction. The solver will reveal the torque path next.'}
            >
              <button
                type="button"
                className="learning-primary-button"
                disabled={!predictionCorrect}
                onClick={() => setStage('solve')}
              >
                Reveal the fixed field →
              </button>
              <div className="lesson-lab-next-row">
                <LessonLink onClick={onBackToCatalog}>← All lessons</LessonLink>
                <LessonLink onClick={onBackHome}>Design start</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <p className="rotor-chase-predict-prompt">Once the rotor reaches the field direction, what happens next?</p>
          <LessonChoices
            label="Fixed field rotor prediction"
            value={prediction}
            onChange={setPrediction}
            correctId="align-once"
            options={[
              { id: 'align-once', label: 'It aligns once', detail: 'Torque disappears when the axes line up.' },
              { id: 'spin-forever', label: 'It spins forever', detail: 'A fixed field would somehow sustain rotation.' },
              { id: 'unaffected', label: 'It is unaffected', detail: 'Permanent magnets would apply no alignment torque.' },
            ]}
          />
        </LessonLabPanel>
      </LessonLab>
    );
  }

  // The left card holds controls only; what they produce is read on the right.
  const experimentControls = electromagnetActive ? (
    labPart === 'dc' && !hasElectromagnetField ? (
      <p className="lesson-lab-note" role="status" aria-live="polite">
        {electromagnetBusy
          ? 'Controls will unlock as soon as the positive, zero, and negative-current FEM frames are ready.'
          : 'Retry the solve to restore the reversible-electromagnet controls.'}
      </p>
    ) : labPart === 'dc' ? (
      <section className="rotor-chase-control-card" aria-label="Winding current and rotor controls">
        <label htmlFor="rotor-chase-dc-current">
          <span>Winding current</span>
          <strong>{dcCurrentA >= 0 ? '+' : '−'}{Math.abs(dcCurrentA).toFixed(1)} A</strong>
        </label>
        <div ref={dcCurrentChoiceRef}>
          <LessonSegmented
            stretch
            label="Winding current presets"
            value={[8, 0, -8].find((presetA) => Math.abs(dcCurrentA - presetA) < 0.01)?.toString() ?? null}
            onChange={(value) => setDcTarget(Number(value))}
            options={[
              { id: String(ELECTROMAGNET_PEAK_CURRENT_A), label: '+8 A' },
              { id: '0', label: '0 A' },
              { id: String(-ELECTROMAGNET_PEAK_CURRENT_A), label: '-8 A' },
            ]}
          />
        </div>
        <input
          id="rotor-chase-dc-current"
          type="range"
          min={-ELECTROMAGNET_PEAK_CURRENT_A}
          max={ELECTROMAGNET_PEAK_CURRENT_A}
          step={0.5}
          value={dcCurrentA}
          aria-label="Current for pole force sweep"
          onChange={(event) => setDcTarget(Number(event.target.value))}
        />
        <div className="rotor-chase-control-scale" aria-hidden="true">
          <span>−8 A</span>
          <span>0</span>
          <span>+8 A</span>
        </div>
        <button
          type="button"
          className="rotor-chase-control-button"
          disabled={dcPeakPoleForceN === null || forceCurrentAlreadyPlotted}
          title="Set winding current, then add the calculated left/right force pair to the plot."
          onClick={plotCurrentForcePair}
        >
          {forceCurrentAlreadyPlotted
            ? `Current plotted · ${plottedForceCurrentsA.length} point${plottedForceCurrentsA.length === 1 ? '' : 's'}`
            : 'Plot left + right force'}
        </button>
        <div className="rotor-chase-control-row">
          <button type="button" className="rotor-chase-control-button" onClick={resetRelease}>Reset rotor 90°</button>
          {/* Until both polarities are seen, releasing is the primary button below. */}
          {dcComplete ? (
            <button
              type="button"
              className="rotor-chase-control-button"
              disabled={releasing || dcTargetAngleDeg === null || dcRotorAtTarget}
              onClick={releaseRotor}
            >
              {releasing ? 'Aligning...' : 'Release rotor'}
            </button>
          ) : null}
        </div>
        <p className="lesson-lab-note">Changing current resets the PM rotor to 90 deg. Release it to see the solved rotor-angle frames converge on the polarity-dependent target.</p>
      </section>
    ) : (
      <section className="rotor-chase-control-card" aria-label="One-phase AC controls">
        <button
          type="button"
          role="switch"
          aria-checked={allowAcRotorMotion}
          className={`rotor-chase-motion-toggle${allowAcRotorMotion ? ' is-active' : ''}`}
          disabled={acRotorMotionBusy}
          onClick={() => void toggleAcRotorMotion()}
        >
          <i aria-hidden="true"><b /></i>
          <span>
            <strong>
              {acRotorMotionBusy
                ? 'Preparing solved rotor angles...'
                : 'Allow rotor motion'}
            </strong>
            <small>
              {allowAcRotorMotion
                ? 'On · PM rotor is free to follow the active pole'
                : 'Off · PM rotor stays fixed at 90°'}
            </small>
          </span>
        </button>
        <label htmlFor="rotor-chase-ac-angle">
          <span>Electrical angle θ</span>
          <strong>{acAngleDeg.toFixed(2)} deg</strong>
        </label>
        <input
          id="rotor-chase-ac-angle"
          type="range"
          min="0"
          max="360"
          step={AC_STEP_DEG}
          value={acAngleDeg}
          onChange={(event) => {
            setPlayingAc(false);
            setAcAngleDeg(Number(event.currentTarget.value));
          }}
          aria-label="Single-phase AC electrical angle"
        />
        <div className="rotor-chase-control-row">
          <button type="button" className="rotor-chase-control-button" onClick={() => stepAc(-1)}>-11.25 deg</button>
          {/* Before the first full cycle, playing is the primary button below. */}
          {playedAc ? (
            <button type="button" className="rotor-chase-control-button" onClick={playAcCycle}>
              {playingAc ? 'Playing...' : 'Play one cycle'}
            </button>
          ) : null}
          <button type="button" className="rotor-chase-control-button" onClick={() => stepAc(1)}>+11.25 deg</button>
        </div>
        <p className="lesson-lab-note">
          {allowAcRotorMotion
            ? 'Motion follows the nearest solved 15° FEM checkpoint. This is a 180° flip: the rotor reverses direction each half-cycle instead of continuing to spin.'
            : 'Step through one electrical cycle. The same fixed axis points right for positive current and left for negative current.'}
        </p>
      </section>
    )
  ) : !hasSolvedField ? (
    <p className="lesson-lab-note">Magneto2D solves seven combined rotor-angle checkpoints plus one stator-only reference for the analytic torque estimate.</p>
  ) : labPart === 'release' ? (
    <section className="rotor-chase-control-card" aria-label="Rotor release controls">
      <div className="rotor-chase-control-row">
        <button type="button" className="rotor-chase-control-button" onClick={resetRelease}>Reset 90 deg</button>
        {/* Before the first alignment, releasing is the primary button below. */}
        {alignedOnce ? (
          <button type="button" className="rotor-chase-control-button" disabled={releasing} onClick={releaseRotor}>
            {releasing ? 'Aligning...' : 'Release rotor'}
          </button>
        ) : null}
      </div>
      <p className="lesson-lab-note">Reset to a 90 deg error, release the rotor, and watch its torque indicator disappear at alignment.</p>
    </section>
  ) : (
    <section className="rotor-chase-control-card" aria-label="Rotor start angle controls">
      <label htmlFor="rotor-chase-start-angle">
        <span>Rotor start angle</span>
        <strong>{signedRelativeRotorAngleDeg.toFixed(0)} deg</strong>
      </label>
      <input
        id="rotor-chase-start-angle"
        type="range"
        min="-90"
        max="90"
        step={MANUAL_STEP_DEG}
        value={signedRelativeRotorAngleDeg}
        onChange={(event) => {
          setRotorOffset(Number(event.currentTarget.value));
        }}
        aria-label="Central permanent-magnet rotor angle"
      />
      <div className="rotor-chase-control-row">
        <button type="button" className="rotor-chase-control-button" onClick={() => stepRotor(-1)}>-15 deg</button>
        <button type="button" className="rotor-chase-control-button" onClick={() => stepRotor(1)}>+15 deg</button>
      </div>
      <p className="lesson-lab-note">The stator magnets and source field remain fixed at 0 deg. Set another rotor angle, then release it.</p>
    </section>
  );

  return (
    <LessonLab className="rotor-chase-lab">
      {inspectPanel}
      <LessonLabStage>
        {electromagnetActive && !displayedData
          ? renderWoundPoleLoading()
          : displayedData
            ? renderSolvedCanvas(displayedData)
            : renderUnsolvedCanvas()}
      </LessonLabStage>
      <LessonLabPanel
        side="do"
        kicker={`Experiment · ${currentStepLabel}`}
        title="Rotor field lab"
        label="Lesson lab controls"
        scrollTopKey={activeProgressStepId}
        footer={(
          <LessonNextStep hint={labInsight}>
            <button
              type="button"
              className="learning-primary-button"
              disabled={dockPrimaryDisabled}
              onClick={runDockPrimaryAction}
            >
              {dockPrimaryLabel}
            </button>
          </LessonNextStep>
        )}
      >
        {goalCard}
        {experimentControls}
        {error ? <p className="lesson-lab-error">{error}</p> : null}
      </LessonLabPanel>
    </LessonLab>
  );
};
