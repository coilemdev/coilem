import React from 'react';
import type {
  FieldForceData,
  FieldForceMagnetData,
  FieldForceMotorData,
  FieldForceWireData,
} from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import {
  MeshViewer,
  type MeshViewerDirectionVector,
  type MeshViewerPointLabel,
} from './MeshViewer';
import { FieldForce3D } from './FieldForce3D';
import { MotorEffectLoop3D } from './MotorEffectLoop3D';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
import './learning.css';
import './field-force.css';

interface LearningLessonFiveFieldForceProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'up' | 'down' | 'none';
type FieldDisplayMode = 'pressure' | 'field';
type FieldSourceMode = 'combined' | 'magnet' | 'wire';
type LessonFiveProgressStepId = 'predict' | 'positive' | 'reverse' | 'scale' | 'angle' | 'motor' | 'check';

const LESSON_FIVE_GOALS: Record<LessonFiveProgressStepId, { title: string; detail: string }> = {
  predict: {
    title: 'Predict I × B',
    detail: 'Use the current and field directions to predict which way the conductor moves.',
  },
  positive: {
    title: 'Establish the +8 A force',
    detail: 'Solve the baseline operating point and compare the FEM force with BIL.',
  },
  reverse: {
    title: 'Reverse current, reverse force',
    detail: 'Keep the magnet field fixed, switch to −8 A, and watch the force change sign.',
  },
  scale: {
    title: 'Double current, double force',
    detail: 'Solve +16 A at the same gap to test the proportional BIL sin θ model.',
  },
  angle: {
    title: 'Turn current away from the field',
    detail: 'Run FEM checkpoints across θ and compare the solved wire force with BIL sin θ.',
  },
  motor: {
    title: 'Energize a horizontal motor loop',
    detail: 'Calibrate the side force with FEM, then sweep one full turn to reveal the torque cycle.',
  },
  check: {
    title: 'Connect field to motion',
    detail: 'Explain force direction, reversal, and scaling from the solved frames.',
  },
};

interface ForceRun {
  currentA: number;
  poleGapMm: number;
  meanBxT: number;
  forceXN: number;
  forceYN: number;
  forceBilN: number;
  data: FieldForceData;
}

interface ForceAngleRun {
  angleDeg: number;
  effectiveCurrentA: number;
  run: ForceRun;
}

const DEFAULT_CURRENT_A = 8;
const DEFAULT_POLE_GAP_MM = 8;
const MIN_POLE_GAP_MM = 0.5;
const MAX_POLE_GAP_MM = 16;
const POLE_GAP_STEP_MM = 0.5;
const TEACHING_DEPTH_M = 0.01;
const MOTOR_SOLVE_TIMEOUT_MS = 30_000;
const FORCE_ANGLE_SWEEP_DEGREES = [
  0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360,
] as const;
const MOTOR_TORQUE_SWEEP_DEGREES = [
  0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360,
] as const;

const forceRunKey = (currentA: number, poleGapMm: number) => `${currentA.toFixed(3)}:${poleGapMm.toFixed(3)}`;
const forceAngleRunKey = (angleDeg: number, poleGapMm: number) => `${angleDeg.toFixed(3)}:${poleGapMm.toFixed(3)}`;
const effectiveAngleCurrentA = (currentA: number, angleDeg: number) => {
  const projectedCurrentA = currentA * Math.sin((angleDeg * Math.PI) / 180);
  return Math.abs(projectedCurrentA) < 1e-9 ? 0 : projectedCurrentA;
};

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'force-direction',
    prompt: 'B points left to right (+X) and current points out of the screen (+Z). Which way is the force?',
    options: ['Up (+Y)', 'Down (−Y)', 'Into the screen (−Z)'],
    correctIndex: 0,
    explanation: 'Use the right-hand cross-product rule: index along I, middle along B, and thumb along F. +Z × +X = +Y, so the conductor is pushed upward.',
  },
  {
    id: 'force-reversal',
    prompt: 'What happens when the current reverses but the magnet field stays fixed?',
    options: ['Force reverses', 'Force stays upward', 'Force becomes zero'],
    correctIndex: 0,
    explanation: 'Reversing I reverses the cross product, so the force changes sign.',
  },
  {
    id: 'force-scale',
    prompt: 'With B and conductor length fixed, what should doubling current do?',
    options: ['Double force', 'Halve force', 'Square force'],
    correctIndex: 0,
    explanation: 'The conductor model is F = BIL sin θ. Here I is perpendicular to B, so θ = 90° and sin θ = 1.',
  },
  {
    id: 'force-angle',
    prompt: 'What happens to magnetic force when current becomes parallel to B, so θ = 0°?',
    options: ['Force falls to zero', 'Force stays at its maximum', 'Force doubles'],
    correctIndex: 0,
    explanation: 'The cross-product magnitude is F = BIL sin θ. Parallel current gives sin 0° = 0, so there is no transverse magnetic force.',
  },
  {
    id: 'motor-effect',
    prompt: 'A closed loop has equal opposite forces on its two active sides. Why can it still turn?',
    options: ['The separated forces form a torque couple', 'One force is secretly larger', 'The end turns pull it around'],
    correctIndex: 0,
    explanation: 'The two forces cancel as a net translation, but act at different lever arms. Their torques add and rotate the loop.',
  },
];

const runFromData = (data: FieldForceData): ForceRun => {
  const metrics = data.metrics;
  if (
    !metrics
    || metrics.wire_mean_bx_t === null
    || metrics.wire_mean_bx_t === undefined
    || metrics.wire_force_x_n === null
    || metrics.wire_force_x_n === undefined
    || metrics.wire_force_y_n === null
    || metrics.wire_force_y_n === undefined
    || metrics.wire_force_bil_n === null
    || metrics.wire_force_bil_n === undefined
  ) {
    throw new Error('The solver returned no conductor-force integral.');
  }
  return {
    currentA: data.current_a,
    poleGapMm: data.pole_gap_mm,
    meanBxT: metrics.wire_mean_bx_t,
    forceXN: metrics.wire_force_x_n,
    forceYN: metrics.wire_force_y_n,
    forceBilN: metrics.wire_force_bil_n,
    data,
  };
};

const signed = (value: number, digits = 1) => `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
const forceDirection = (forceYN: number) => (forceYN > 0 ? 'Up (+Y)' : forceYN < 0 ? 'Down (−Y)' : 'No vertical force');
const currentSymbol = (currentA: number) => (currentA > 0 ? '⊙' : currentA < 0 ? '⊗' : '○');
const currentAxisLabel = (currentA: number) => (currentA > 0 ? 'out (+Z)' : currentA < 0 ? 'into (−Z)' : 'off');
const forceAxisLabel = (forceYN: number) => (forceYN > 0 ? '↑ up (+Y)' : forceYN < 0 ? '↓ down (−Y)' : 'no force');
const formatMilliTesla = (tesla: number) => {
  const milliTesla = tesla * 1e3;
  return milliTesla < 0.1 ? milliTesla.toFixed(3) : milliTesla.toFixed(2);
};

const quantileRange = (values: number[]): { low: number; high: number } | undefined => {
  const sorted = values.filter((value) => Number.isFinite(value) && value >= 0).sort((a, b) => a - b);
  if (sorted.length === 0) return undefined;
  const at = (fraction: number) => {
    const index = (sorted.length - 1) * fraction;
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    if (lower === upper) return sorted[lower];
    return sorted[lower] * (upper - index) + sorted[upper] * (index - lower);
  };
  const low = at(0.04);
  const high = at(0.96);
  return high > low ? { low, high } : undefined;
};

interface ForceDirectionGuideProps {
  currentA: number;
  forceYN: number;
}

const ForceDirectionGuide: React.FC<ForceDirectionGuideProps> = ({ currentA, forceYN }) => {
  const currentSign = Math.sign(currentA);
  const currentGlyph = currentSymbol(currentA);
  const currentDirection = currentSign > 0 ? 'Out (+Z)' : currentSign < 0 ? 'Into (−Z)' : 'Off';
  const wireFieldDirection = currentSign > 0 ? 'counterclockwise' : currentSign < 0 ? 'clockwise' : 'zero';
  const aboveWireField = currentSign > 0 ? '←' : currentSign < 0 ? '→' : '—';
  const belowWireField = currentSign > 0 ? '→' : currentSign < 0 ? '←' : '—';
  const aboveStrength = currentSign > 0 ? 'weaker' : currentSign < 0 ? 'stronger' : 'unchanged';
  const belowStrength = currentSign > 0 ? 'stronger' : currentSign < 0 ? 'weaker' : 'unchanged';
  const forceGlyph = forceYN > 0 ? '↑' : forceYN < 0 ? '↓' : '—';
  const strongerSide = currentSign > 0 ? 'below' : currentSign < 0 ? 'above' : 'neither side';
  const weakerSide = currentSign > 0 ? 'above' : currentSign < 0 ? 'below' : 'neither side';

  return (
    <section className="field-force-direction-card">
      <header><span>RIGHT-HAND SANITY CHECK</span><strong>Index I × middle B = thumb F</strong></header>
      <div className="field-force-vector-proof" aria-label={`Magnetic field points right, current points ${currentDirection}, and force points ${forceDirection(forceYN)}`}>
        <div><small>INDEX · CURRENT</small><b>{currentGlyph} {currentDirection}</b><em>I {signed(currentA, 0)} A</em></div>
        <span className="field-force-proof-operator">×</span>
        <div><small>MIDDLE · FIELD</small><b>N → S</b><em>B = +X</em></div>
        <span className="field-force-proof-operator">=</span>
        <div className="is-force"><small>THUMB · FORCE</small><b>{forceGlyph} {forceDirection(forceYN)}</b><em>I × B</em></div>
      </div>
      <p className="field-force-hand-instruction">Point your right index <b>{currentDirection}</b>, then your middle finger <b>N → S</b>. Your thumb gives <b>{forceDirection(forceYN)}</b>.</p>
      <div className="field-force-balance" aria-label={`The wire's ${wireFieldDirection} field changes the field strength above and below it`}>
        <div><span>Above wire</span><code>B → + wire {aboveWireField}</code><strong className={`is-${aboveStrength}`}>{aboveStrength} |B|</strong></div>
        <div className="field-force-wire-field"><span>{currentGlyph}</span><p>Current makes a <b>{wireFieldDirection}</b> field around the wire.</p></div>
        <div><span>Below wire</span><code>B → + wire {belowWireField}</code><strong className={`is-${belowStrength}`}>{belowStrength} |B|</strong></div>
      </div>
      <p className="field-force-stress-note">{currentSign === 0
        ? 'With no current, the wire adds no circular field, so there is no magnetic force.'
        : <>The field is stronger {strongerSide}, so magnetic stress pushes the wire toward the weaker field {weakerSide}: <b>{forceDirection(forceYN)}</b>.</>}</p>
    </section>
  );
};

interface FieldPressureOverlayProps {
  currentA: number;
  forceYN: number;
}

const FieldPressureOverlay: React.FC<FieldPressureOverlayProps> = ({ currentA, forceYN }) => {
  const currentSign = Math.sign(currentA);
  const forceSign = Math.sign(forceYN);
  const pressureCurrentGlyph = currentSign > 0 ? '•' : currentSign < 0 ? '×' : '○';
  const upperStrength = forceSign < 0 ? 'strong' : forceSign > 0 ? 'weak' : 'equal';
  const lowerStrength = forceSign > 0 ? 'strong' : forceSign < 0 ? 'weak' : 'equal';
  const aboveWireField = currentSign > 0 ? '←' : currentSign < 0 ? '→' : '—';
  const belowWireField = currentSign > 0 ? '→' : currentSign < 0 ? '←' : '—';
  const forceGlyph = forceSign > 0 ? '↑' : forceSign < 0 ? '↓' : '—';
  const forceLabel = forceSign > 0 ? 'NET FORCE UP' : forceSign < 0 ? 'NET FORCE DOWN' : 'FORCES BALANCE';
  const elementForceStartY = forceSign < 0 ? 315 : 365;
  const elementForceEndY = forceSign < 0 ? 365 : 315;

  return (
    <div className="field-force-pressure-overlay" aria-label={`Magnetic field pressure is ${upperStrength} above the conductor and ${lowerStrength} below it, producing ${forceDirection(forceYN)}`}>
      <div className="field-force-pressure-explainer">
        <span>FIELD PRESSURE VIEW</span>
        <strong>Stronger |B| pushes harder</strong>
        <small>Relative stress shown · in air, p = B² / 2μ₀</small>
      </div>
      <svg viewBox="0 0 1000 680" role="img" aria-label="Relative magnetic pressure above and below the current-carrying conductor">
        <defs>
          <marker id="fieldPressureStrongArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
          <marker id="fieldPressureWeakArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
          <marker id="fieldPressureNetArrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
            <path d="M0,0 L9,4.5 L0,9 Z" />
          </marker>
          <marker id="fieldPressureElementArrow" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
            <path d="M0,0 L7,3.5 L0,7 Z" />
          </marker>
        </defs>

        <g className={`field-force-pressure-zone is-${upperStrength}`}>
          <rect x="390" y="176" width="220" height="112" rx="42" />
          {[438, 475, 512, 549].map((x) => (
            <line key={`upper-${x}`} x1={x} y1="205" x2={x} y2="279" />
          ))}
          <text x="500" y="159" className="field-force-pressure-zone-title">
            {upperStrength === 'strong' ? 'HIGHER PRESSURE' : upperStrength === 'weak' ? 'LOWER PRESSURE' : 'BALANCED PRESSURE'}
          </text>
          <text x="500" y="245" className="field-force-pressure-zone-value">
            {upperStrength === 'strong' ? 'STRONGER |B|' : upperStrength === 'weak' ? 'WEAKER |B|' : 'SAME |B|'}
          </text>
        </g>

        <g className="field-force-pressure-wire">
          <circle className="field-force-conductor-body" cx="500" cy="340" r="64" />
          <text className="field-force-conductor-heading" x="500" y="304">FIELD ACTS ON CURRENT</text>
          <g className={`field-force-current-elements is-${forceSign > 0 ? 'up' : forceSign < 0 ? 'down' : 'zero'}`}>
            {[476, 500, 524].map((x) => (
              <g key={`current-element-${x}`}>
                {forceSign !== 0 ? <line x1={x} y1={elementForceStartY} x2={x} y2={elementForceEndY} /> : null}
                <circle cx={x} cy="340" r="11" />
                <text x={x} y="346">{pressureCurrentGlyph}</text>
              </g>
            ))}
          </g>
          <text className="field-force-current-direction" x="500" y="387">f = J × B · I {currentAxisLabel(currentA).toUpperCase()}</text>
        </g>

        <g className={`field-force-pressure-zone is-${lowerStrength}`}>
          <rect x="390" y="392" width="220" height="112" rx="42" />
          {[438, 475, 512, 549].map((x) => (
            <line key={`lower-${x}`} x1={x} y1="475" x2={x} y2="401" />
          ))}
          <text x="500" y="531" className="field-force-pressure-zone-title">
            {lowerStrength === 'strong' ? 'HIGHER PRESSURE' : lowerStrength === 'weak' ? 'LOWER PRESSURE' : 'BALANCED PRESSURE'}
          </text>
          <text x="500" y="461" className="field-force-pressure-zone-value">
            {lowerStrength === 'strong' ? 'STRONGER |B|' : lowerStrength === 'weak' ? 'WEAKER |B|' : 'SAME |B|'}
          </text>
        </g>

        <g className={`field-force-pressure-combination is-${upperStrength}`}>
          <rect x="74" y="190" width="270" height="68" rx="10" />
          <text x="94" y="217">ABOVE THE WIRE</text>
          <text x="94" y="243">Bₘₐg →  +  Bwire {aboveWireField}</text>
        </g>
        <g className={`field-force-pressure-combination is-${lowerStrength}`}>
          <rect x="74" y="422" width="270" height="68" rx="10" />
          <text x="94" y="449">BELOW THE WIRE</text>
          <text x="94" y="475">Bₘₐg →  +  Bwire {belowWireField}</text>
        </g>

        <g className={`field-force-pressure-net is-${forceSign > 0 ? 'up' : forceSign < 0 ? 'down' : 'zero'}`}>
          <line x1="676" y1={forceSign < 0 ? 270 : 410} x2="676" y2={forceSign < 0 ? 410 : 270} />
          <text x="702" y="330">{forceGlyph} {forceLabel}</text>
          <text x="702" y="354">sum of J × B → motion</text>
        </g>
      </svg>
      <p className="field-force-pressure-caption">
        <b>Inside copper:</b> B acts on the current density J. <b>Outside copper:</b> the unequal pressure bands account for that same force through the field.
        {currentSign === 0 ? ' With no current, there is no J × B force.' : ` The wire field ${currentSign > 0 ? 'adds below and subtracts above' : 'adds above and subtracts below'}.`}
      </p>
    </div>
  );
};

interface FieldForcePredictionDiagramProps {
  currentA?: number;
  poleGapMm?: number;
  setupPreview?: boolean;
}

const FieldForcePredictionDiagram: React.FC<FieldForcePredictionDiagramProps> = ({
  currentA = DEFAULT_CURRENT_A,
  poleGapMm = DEFAULT_POLE_GAP_MM,
  setupPreview = false,
}) => {
  const gapProgress = (poleGapMm - MIN_POLE_GAP_MM) / (MAX_POLE_GAP_MM - MIN_POLE_GAP_MM);
  const visualGap = 12 + Math.min(1, Math.max(0, gapProgress)) * 98;
  const wireRadius = 48;
  const poleWidth = 235;
  const leftInnerX = 430 - wireRadius - visualGap;
  const rightInnerX = 430 + wireRadius + visualGap;
  const leftPoleX = leftInnerX - poleWidth;
  const currentMagnitude = Math.min(1, Math.abs(currentA) / 16);
  const fieldOpacity = 0.42 + (1 - gapProgress) * 0.5;
  const currentLabel = currentA > 0
    ? `I = ${signed(currentA, 0)} A · OUT OF SCREEN`
    : currentA < 0
      ? `I = ${signed(currentA, 0)} A · INTO SCREEN`
      : 'I = 0 A · CURRENT OFF';

  return (
  <svg className={`field-force-prediction${setupPreview ? ' is-setup-preview' : ''}`} viewBox="0 0 860 500" role="img" aria-label={`Conductor between poles with ${poleGapMm.toFixed(1)} millimeter gaps and ${signed(currentA, 0)} amperes current`}>
    <defs>
      <marker id="fieldForceBArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#67e8f9" />
      </marker>
    </defs>
    <rect x={leftPoleX} y="105" width={poleWidth} height="285" rx="6" className="field-force-pole is-north" />
    <rect x={rightInnerX} y="105" width={poleWidth} height="285" rx="6" className="field-force-pole is-south" />
    <text x={leftPoleX + poleWidth / 2} y="270" className="field-force-pole-label">N</text>
    <text x={rightInnerX + poleWidth / 2} y="270" className="field-force-pole-label">S</text>
    {[185, 250, 315].map((y) => (
      <line key={y} x1={leftInnerX + 8} y1={y} x2={rightInnerX - 8} y2={y} className="field-force-b-line" markerEnd="url(#fieldForceBArrow)" style={{ opacity: fieldOpacity }} />
    ))}
    <circle cx="430" cy="250" r={wireRadius} className="field-force-wire" style={{ opacity: 0.64 + currentMagnitude * 0.36 }} />
    {currentA > 0 ? <circle cx="430" cy="250" r={5 + currentMagnitude * 6} className="field-force-dot" /> : null}
    {currentA < 0 ? <g className="field-force-cross"><line x1="419" y1="239" x2="441" y2="261" /><line x1="441" y1="239" x2="419" y2="261" /></g> : null}
    {currentA === 0 ? <circle cx="430" cy="250" r="11" className="field-force-zero" /> : null}
    <rect x="322" y="330" width="216" height="36" rx="6" className="field-force-current-pill" />
    <text x="430" y="354" className="field-force-current-label">{currentLabel}</text>
    <text x="430" y="72" className="field-force-question">{setupPreview ? `LIVE SETUP · ${poleGapMm.toFixed(1)} mm EACH SIDE` : 'B IS +X. WHICH WAY IS I × B?'}</text>
  </svg>
  );
};

interface MotorEffectLoopDiagramProps {
  currentA: number;
  fieldT: number;
  sideForceN: number;
  torqueNm: number;
  loopAngleDeg: number;
}

const MotorEffectLoopDiagram: React.FC<MotorEffectLoopDiagramProps> = ({
  currentA,
  fieldT,
  sideForceN,
  torqueNm,
  loopAngleDeg,
}) => {
  const positive = currentA >= 0;
  const leftCurrent = positive ? '+Z ↑' : '−Z ↓';
  const rightCurrent = positive ? '−Z ↓' : '+Z ↑';
  const leftForce = positive ? '⊙' : '⊗';
  const rightForce = positive ? '⊗' : '⊙';
  const torqueDirection = Math.abs(torqueNm) < 1e-9 ? '0' : torqueNm > 0 ? '+Z' : '−Z';
  const areaDirection = positive ? '+Y' : '−Y';
  const projectedWidth = Math.sin((loopAngleDeg * Math.PI) / 180);
  const projectedLoopTransform = `translate(500 0) scale(${projectedWidth.toFixed(4)} 1) translate(-500 0)`;

  return (
    <div className="motor-effect-diagram">
      <svg viewBox="0 0 1000 680" role="img" aria-label={`Projected top view of a rectangular motor loop at torque angle ${loopAngleDeg} degrees between north and south poles. Two separated feed leads apply voltage to the loop. The active sides carry opposite Z-direction currents and experience opposite Y-direction forces that create torque about the ${torqueDirection} axis.`}>
        <defs>
          <marker id="motorEffectFieldArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
          <marker id="motorEffectCurrentArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
          <marker id="motorEffectTorqueArrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
            <path d="M0,0 L9,4.5 L0,9 Z" />
          </marker>
        </defs>

        <g className="motor-effect-pole is-north">
          <rect x="40" y="126" width="235" height="380" rx="10" />
          <text x="158" y="335">N</text>
        </g>
        <g className="motor-effect-pole is-south">
          <rect x="725" y="126" width="235" height="380" rx="10" />
          <text x="842" y="335">S</text>
        </g>

        <g className="motor-effect-field">
          {[205, 275, 345, 415].map((y) => (
            <line key={y} x1="292" y1={y} x2="708" y2={y} markerEnd="url(#motorEffectFieldArrow)" />
          ))}
          <text x="500" y="175">B = {fieldT.toFixed(3)} T · N → S (+X)</text>
        </g>

        <text className="motor-effect-plane-label" x="500" y="95">PROJECTED TOP VIEW · δ = {loopAngleDeg}° · REFERENCE AREA A {areaDirection}</text>
        <g className="motor-effect-loop" transform={projectedLoopTransform}>
          <path d="M470 555 L470 520 L423 520 Q390 520 390 487 L390 165 Q390 132 423 132 L577 132 Q610 132 610 165 L610 487 Q610 520 577 520 L530 520 L530 555" />
          <circle cx="390" cy="320" r="33" />
          <circle cx="610" cy="320" r="33" />
          <text className="motor-effect-force-glyph" x="390" y="331">{leftForce}</text>
          <text className="motor-effect-force-glyph" x="610" y="331">{rightForce}</text>
          <text className="motor-effect-point-label" x="370" y="542">A</text>
          <text className="motor-effect-point-label" x="370" y="118">B</text>
          <text className="motor-effect-point-label" x="630" y="118">C</text>
          <text className="motor-effect-point-label" x="630" y="542">D</text>
          <g className="motor-effect-voltage-source">
            <rect x="448" y="556" width="52" height="42" rx="5" className={positive ? 'is-positive' : 'is-negative'} />
            <rect x="500" y="556" width="52" height="42" rx="5" className={positive ? 'is-negative' : 'is-positive'} />
            <text x="474" y="584">{positive ? '+V' : '−'}</text>
            <text x="526" y="584">{positive ? '−' : '+V'}</text>
          </g>
        </g>

        <g className={`motor-effect-current ${positive ? 'is-positive' : 'is-negative'}`} transform={projectedLoopTransform}>
          <line x1="355" y1={positive ? 420 : 220} x2="355" y2={positive ? 220 : 420} markerEnd="url(#motorEffectCurrentArrow)" />
          <line x1="645" y1={positive ? 220 : 420} x2="645" y2={positive ? 420 : 220} markerEnd="url(#motorEffectCurrentArrow)" />
          <text x="332" y="320">I {leftCurrent}</text>
          <text x="668" y="320">I {rightCurrent}</text>
        </g>

        <g className="motor-effect-force-labels">
          <text x="300" y="625">F<tspan baselineShift="sub">AB</tspan> {leftForce} {(sideForceN * 1e3).toFixed(1)} mN · {positive ? 'UP +Y' : 'DOWN −Y'}</text>
          <text x="700" y="625">F<tspan baselineShift="sub">CD</tspan> {rightForce} {(sideForceN * 1e3).toFixed(1)} mN · {positive ? 'DOWN −Y' : 'UP +Y'}</text>
        </g>

        {Math.abs(torqueNm) >= 1e-9 ? (
          <path
            className={`motor-effect-torque-arrow ${torqueNm < 0 ? 'is-negative-z' : 'is-positive-z'}`}
            d={torqueNm < 0 ? 'M428 350 C455 305 545 305 572 350' : 'M572 350 C545 395 455 395 428 350'}
            markerEnd="url(#motorEffectTorqueArrow)"
          />
        ) : null}
        <text className="motor-effect-torque-label" x="500" y="662">NET FORCE ≈ 0 · TORQUE ABOUT {torqueDirection} = {(torqueNm * 1e3).toFixed(2)} mN·m</text>
      </svg>
      <div className="motor-effect-diagram-key">
        <span><b>⊙</b> force up (+Y, above loop plane)</span>
        <span><b>⊗</b> force down (−Y, below loop plane)</span>
        <span>Voltage is applied across two separated feed leads.</span>
        <span>AB and CD are the active sides; BC and DA close the circuit.</span>
      </div>
    </div>
  );
};

interface MotorTorqueAnglePlotProps {
  sampledAnglesDeg: number[];
  activeAngleDeg: number;
  torqueMaxNm: number;
  currentA: number;
  onSelect: (angleDeg: number) => void;
}

const MotorTorqueAnglePlot: React.FC<MotorTorqueAnglePlotProps> = ({
  sampledAnglesDeg,
  activeAngleDeg,
  torqueMaxNm,
  currentA,
  onSelect,
}) => {
  const width = 680;
  const height = 265;
  const margin = { top: 26, right: 30, bottom: 52, left: 76 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const directionSign = currentA >= 0 ? -1 : 1;
  const peakMN = Math.max(torqueMaxNm * 1e3, 0.01);
  const torqueAt = (angleDeg: number) => directionSign * peakMN * Math.sin((angleDeg * Math.PI) / 180);
  const xFor = (angleDeg: number) => margin.left + (angleDeg / 360) * plotWidth;
  const yFor = (torqueMN: number) => margin.top + ((peakMN - torqueMN) / (2 * peakMN)) * plotHeight;
  const curve = Array.from({ length: 73 }, (_, index) => index * 5)
    .map((angleDeg) => `${xFor(angleDeg)},${yFor(torqueAt(angleDeg))}`)
    .join(' ');
  const xTicks = [0, 90, 180, 270, 360];
  const yTicks = [-peakMN, 0, peakMN];
  const activeTorqueMN = torqueAt(activeAngleDeg);

  return (
    <section className="motor-torque-plot-card" aria-label="Loop torque versus torque angle">
      <header>
        <div>
          <p className="learning-kicker">Torque-angle sweep · FEM-calibrated</p>
          <h3>One turn reveals the complete torque cycle.</h3>
        </div>
        <span>{sampledAnglesDeg.length} angles</span>
      </header>
      <svg className="motor-torque-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Signed loop torque versus angle. The active point is ${activeAngleDeg} degrees and ${activeTorqueMN.toFixed(2)} millinewton meters.`}>
        {xTicks.map((tick) => (
          <g key={`x-${tick}`}>
            <line className="motor-torque-grid" x1={xFor(tick)} y1={margin.top} x2={xFor(tick)} y2={margin.top + plotHeight} />
            <text className="motor-torque-tick" x={xFor(tick)} y={height - 24} textAnchor="middle">{tick}°</text>
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line className={`motor-torque-grid${Math.abs(tick) < 1e-6 ? ' is-zero' : ''}`} x1={margin.left} y1={yFor(tick)} x2={margin.left + plotWidth} y2={yFor(tick)} />
            <text className="motor-torque-tick" x={margin.left - 12} y={yFor(tick) + 4} textAnchor="end">{tick.toFixed(2)}</text>
          </g>
        ))}
        <polyline className="motor-torque-curve" points={curve} />
        {sampledAnglesDeg.map((angleDeg) => {
          const active = Math.abs(angleDeg - activeAngleDeg) < 0.1;
          return (
            <circle
              key={angleDeg}
              className={`motor-torque-point${active ? ' is-active' : ''}`}
              cx={xFor(angleDeg)}
              cy={yFor(torqueAt(angleDeg))}
              r={active ? 7 : 4.5}
              role="button"
              tabIndex={0}
              aria-label={`Select ${angleDeg} degrees, torque ${torqueAt(angleDeg).toFixed(2)} millinewton meters`}
              onClick={() => onSelect(angleDeg)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') onSelect(angleDeg);
              }}
            />
          );
        })}
        <line className="motor-torque-active-guide" x1={xFor(activeAngleDeg)} y1={yFor(0)} x2={xFor(activeAngleDeg)} y2={yFor(activeTorqueMN)} />
        <text className="motor-torque-axis-label" x={margin.left + plotWidth / 2} y={height - 3} textAnchor="middle">Reference loop-normal angle δA from B</text>
        <text className="motor-torque-axis-label" transform={`translate(16 ${margin.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Signed torque τ (mN·m)</text>
      </svg>
      <div className="motor-torque-plot-readout">
        <span>δ <b>{activeAngleDeg}°</b></span>
        <span>sin δ <b>{Math.sin((activeAngleDeg * Math.PI) / 180).toFixed(3)}</b></span>
        <span>τ <b>{signed(activeTorqueMN, 2)} mN·m</b></span>
      </div>
      <p>Zero at alignment, maximum a quarter-turn away, then equal negative torque over the second half-cycle.</p>
    </section>
  );
};

interface ForcePlotProps {
  runs: ForceRun[];
  activeCurrentA: number | null;
  onSelect: (currentA: number) => void;
}

interface ForceAnglePlotProps {
  activeAngleDeg: number;
  runs: ForceAngleRun[];
  forceAt90N: number;
  bilForceAt90N: number;
  onSelect: (angleDeg: number) => void;
}

const ForceAnglePlot: React.FC<ForceAnglePlotProps> = ({
  activeAngleDeg,
  runs,
  forceAt90N,
  bilForceAt90N,
  onSelect,
}) => {
  const sortedRuns = [...runs].sort((left, right) => left.angleDeg - right.angleDeg);
  const width = 780;
  const height = 320;
  const margin = { top: 30, right: 34, bottom: 54, left: 76 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const forceMaxMN = Math.max(
    Math.abs(forceAt90N),
    Math.abs(bilForceAt90N),
    ...sortedRuns.map((item) => Math.abs(item.run.forceYN)),
  ) * 1e3;
  const yMax = Math.max(1, forceMaxMN * 1.15);
  const xTicks = [0, 60, 120, 180, 240, 300, 360];
  const yTicks = [-yMax, -yMax / 2, 0, yMax / 2, yMax];
  const xFor = (angleDeg: number) => margin.left + (angleDeg / 360) * plotWidth;
  const yFor = (forceMN: number) => (
    margin.top + plotHeight - ((forceMN + yMax) / (2 * yMax)) * plotHeight
  );
  const forceAt = (force90N: number, angleDeg: number) => (
    force90N * Math.sin((angleDeg * Math.PI) / 180)
  );
  const bilPoints = Array.from({ length: 145 }, (_, index) => index * 2.5)
    .map((angleDeg) => `${xFor(angleDeg)},${yFor(forceAt(bilForceAt90N, angleDeg) * 1e3)}`)
    .join(' ');
  const femCalibratedPoints = Array.from({ length: 361 }, (_, angleDeg) => angleDeg)
    .map((angleDeg) => `${xFor(angleDeg)},${yFor(forceAt(forceAt90N, angleDeg) * 1e3)}`)
    .join(' ');
  const activeRun = sortedRuns.find((item) => Math.abs(item.angleDeg - activeAngleDeg) < 0.01) ?? null;
  const activeForceMN = (activeRun?.run.forceYN ?? forceAt(forceAt90N, activeAngleDeg)) * 1e3;
  const activeBilMN = forceAt(bilForceAt90N, activeAngleDeg) * 1e3;
  const rawSinTheta = Math.sin((activeAngleDeg * Math.PI) / 180);
  const sinTheta = Math.abs(rawSinTheta) < 1e-9 ? 0 : rawSinTheta;

  return (
    <div className="field-force-angle-plot-wrap">
      <div className="field-force-plot-legend">
        <span className="is-fem-curve">FEM-calibrated sin θ</span>
        <span className="is-checkpoint">13 FEM checkpoints</span>
        <span className="is-model">BIL sin θ model</span>
      </div>
      <svg
        className="field-force-angle-plot"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Complete signed 360 degree FEM-calibrated sine cycle for conductor force versus current phase, validated by ${sortedRuns.length} solved FEM checkpoints. The active phase is ${activeAngleDeg} degrees and its ${activeRun ? 'solved' : 'calibrated'} force is ${activeForceMN.toFixed(1)} millinewtons.`}
      >
        <g className="field-force-plot-grid">
          {yTicks.map((tick) => <line key={`y-${tick}`} x1={margin.left} y1={yFor(tick)} x2={width - margin.right} y2={yFor(tick)} />)}
          {xTicks.map((tick) => <line key={`x-${tick}`} x1={xFor(tick)} y1={margin.top} x2={xFor(tick)} y2={height - margin.bottom} />)}
        </g>
        <g className="field-force-plot-axes">
          <line x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
          <line x1={margin.left} y1={yFor(0)} x2={width - margin.right} y2={yFor(0)} />
        </g>
        <g className="field-force-plot-ticks">
          {yTicks.map((tick) => <text key={`yt-${tick}`} x={margin.left - 12} y={yFor(tick) + 4} textAnchor="end">{tick.toFixed(0)}</text>)}
          {xTicks.map((tick) => <text key={`xt-${tick}`} x={xFor(tick)} y={height - margin.bottom + 22} textAnchor="middle">{tick}°</text>)}
        </g>
        <text className="field-force-axis-title" x="18" y={margin.top + plotHeight / 2} transform={`rotate(-90 18 ${margin.top + plotHeight / 2})`} textAnchor="middle">Wire force Fθ (mN)</text>
        <text className="field-force-axis-title" x={margin.left + plotWidth / 2} y={height - 10} textAnchor="middle">Signed current phase θ from B</text>
        <polyline className="field-force-model-line" points={bilPoints} />
        <polyline className="field-force-angle-fem-curve" points={femCalibratedPoints} />
        <g className="field-force-points field-force-angle-points">
          {sortedRuns.map((item) => {
            const active = Math.abs(item.angleDeg - activeAngleDeg) < 0.01;
            const x = xFor(item.angleDeg);
            const y = yFor(item.run.forceYN * 1e3);
            return (
              <g
                key={item.angleDeg}
                className={active ? 'is-active' : ''}
                role="button"
                tabIndex={0}
                aria-label={`Select solved ${item.angleDeg} degree FEM checkpoint, force ${(item.run.forceYN * 1e3).toFixed(1)} millinewtons`}
                onClick={() => onSelect(item.angleDeg)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelect(item.angleDeg);
                }}
              >
                <circle className="field-force-point-hit" cx={x} cy={y} r="18" />
                <circle className="field-force-point-dot" cx={x} cy={y} r={active ? 7 : 5} />
                {(active || item.angleDeg % 90 === 0) ? (
                  <text
                    x={x}
                    y={y - 13}
                    textAnchor="middle"
                  >
                    {signed(item.run.forceYN * 1e3)} mN
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
        <line className="field-force-angle-active-guide" x1={xFor(activeAngleDeg)} y1={yFor(0)} x2={xFor(activeAngleDeg)} y2={yFor(activeForceMN)} />
        {!activeRun ? <circle className="field-force-angle-active-point is-projected" cx={xFor(activeAngleDeg)} cy={yFor(activeForceMN)} r="7" /> : null}
      </svg>
      <div className="field-force-angle-plot-readout">
        <span>θ <b>{activeAngleDeg}°</b></span>
        <span>sin θ <b>{sinTheta.toFixed(3)}</b></span>
        <span>{activeRun ? 'FEM checkpoint' : 'FEM-calibrated'} <b>{activeForceMN.toFixed(1)} mN</b></span>
        <span>BIL <b>{activeBilMN.toFixed(1)} mN</b></span>
      </div>
    </div>
  );
};

const ForcePlot: React.FC<ForcePlotProps> = ({ runs, activeCurrentA, onSelect }) => {
  const sortedRuns = [...runs].sort((left, right) => left.currentA - right.currentA);
  const width = 780;
  const height = 270;
  const margin = { top: 30, right: 34, bottom: 54, left: 76 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xMin = -16;
  const xMax = 16;
  const referenceBxT = sortedRuns[0]?.meanBxT ?? 0.239;
  const modelForceMN = (currentA: number) => referenceBxT * currentA * TEACHING_DEPTH_M * 1e3;
  const yMax = Math.max(45, ...sortedRuns.map((run) => Math.abs(run.forceYN * 1e3) * 1.18));
  const xTicks = [-16, -8, 0, 8, 16];
  const yTicks = [-yMax, -yMax / 2, 0, yMax / 2, yMax];
  const xFor = (currentA: number) => margin.left + ((currentA - xMin) / (xMax - xMin)) * plotWidth;
  const yFor = (forceMN: number) => margin.top + plotHeight - ((forceMN + yMax) / (2 * yMax)) * plotHeight;
  const modelPoints = Array.from({ length: 33 }, (_, index) => xMin + index)
    .map((currentA) => `${xFor(currentA)},${yFor(modelForceMN(currentA))}`).join(' ');
  const femPoints = sortedRuns.map((run) => `${xFor(run.currentA)},${yFor(run.forceYN * 1e3)}`).join(' ');
  const activeRun = sortedRuns.find((run) => activeCurrentA !== null && Math.abs(run.currentA - activeCurrentA) < 0.01) ?? null;
  const deltaPct = activeRun && activeRun.forceBilN !== 0
    ? ((activeRun.forceYN - activeRun.forceBilN) / activeRun.forceBilN) * 100
    : 0;

  return (
    <div className="field-force-plot-wrap">
      <div className="field-force-plot-legend"><span className="is-fem">FEM ∫J × B dV</span><span className="is-model">BIL sin θ model · θ = 90°</span></div>
      <svg className="field-force-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Vertical conductor force versus current">
        <g className="field-force-plot-grid">
          {yTicks.map((tick) => <line key={`y-${tick}`} x1={margin.left} y1={yFor(tick)} x2={width - margin.right} y2={yFor(tick)} />)}
          {xTicks.map((tick) => <line key={`x-${tick}`} x1={xFor(tick)} y1={margin.top} x2={xFor(tick)} y2={height - margin.bottom} />)}
        </g>
        <g className="field-force-plot-axes"><line x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} /><line x1={margin.left} y1={yFor(0)} x2={width - margin.right} y2={yFor(0)} /></g>
        <g className="field-force-plot-ticks">
          {yTicks.map((tick) => <text key={`yt-${tick}`} x={margin.left - 12} y={yFor(tick) + 4} textAnchor="end">{tick.toFixed(0)}</text>)}
          {xTicks.map((tick) => <text key={`xt-${tick}`} x={xFor(tick)} y={height - margin.bottom + 22} textAnchor="middle">{tick}</text>)}
        </g>
        <text className="field-force-axis-title" x="18" y={margin.top + plotHeight / 2} transform={`rotate(-90 18 ${margin.top + plotHeight / 2})`} textAnchor="middle">Vertical force Fᵧ (mN)</text>
        <text className="field-force-axis-title" x={margin.left + plotWidth / 2} y={height - 10} textAnchor="middle">Current I (A)</text>
        <polyline className="field-force-model-line" points={modelPoints} />
        {sortedRuns.length > 1 ? <polyline className="field-force-fem-line" points={femPoints} /> : null}
        <g className="field-force-points">
          {sortedRuns.map((run) => {
            const active = activeCurrentA !== null && Math.abs(run.currentA - activeCurrentA) < 0.01;
            const x = xFor(run.currentA);
            const y = yFor(run.forceYN * 1e3);
            return (
              <g key={run.currentA} className={active ? 'is-active' : ''} role="button" tabIndex={0} onClick={() => onSelect(run.currentA)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelect(run.currentA); }}>
                <circle className="field-force-point-hit" cx={x} cy={y} r="18" />
                <circle className="field-force-point-dot" cx={x} cy={y} r={active ? 7 : 5} />
                <text x={x} y={y - 13} textAnchor="middle">{signed(run.forceYN * 1e3)} mN</text>
              </g>
            );
          })}
        </g>
      </svg>
      {activeRun ? (
        <div className="field-force-plot-comparison">
          <span>I = {signed(activeRun.currentA, 0)} A</span>
          <strong>FEM {signed(activeRun.forceYN * 1e3)} mN</strong>
          <strong>BIL {signed(activeRun.forceBilN * 1e3)} mN</strong>
          <em>{signed(deltaPct, 2)}%</em>
        </div>
      ) : null}
    </div>
  );
};

export const LearningLessonFiveFieldForce: React.FC<LearningLessonFiveFieldForceProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const solveInspectorRef = React.useRef<HTMLElement>(null);
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = React.useState<Prediction | null>(null);
  const [currentA, setCurrentA] = React.useState(DEFAULT_CURRENT_A);
  const [poleGapMm, setPoleGapMm] = React.useState(DEFAULT_POLE_GAP_MM);
  const [runs, setRuns] = React.useState<ForceRun[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [forceAngleOpen, setForceAngleOpen] = React.useState(false);
  const [forceAngleDeg, setForceAngleDeg] = React.useState(90);
  const [forceAngleReviewed, setForceAngleReviewed] = React.useState(false);
  const [forceAngleRuns, setForceAngleRuns] = React.useState<ForceAngleRun[]>([]);
  const [forceAngleSolveBusy, setForceAngleSolveBusy] = React.useState(false);
  const [forceAngleSolveError, setForceAngleSolveError] = React.useState<string | null>(null);
  const [forceAngleSolveProgress, setForceAngleSolveProgress] = React.useState({ complete: 0, total: 0 });
  const [motorEffectOpen, setMotorEffectOpen] = React.useState(false);
  const [motorLoopCurrentA, setMotorLoopCurrentA] = React.useState(8);
  const [motorLoopAngleDeg, setMotorLoopAngleDeg] = React.useState(90);
  const [motorTorqueAnglesDeg, setMotorTorqueAnglesDeg] = React.useState<number[]>([]);
  const [motorEffectReviewed, setMotorEffectReviewed] = React.useState(false);
  const [motorSolve, setMotorSolve] = React.useState<FieldForceMotorData | null>(null);
  const [motorSolveBusy, setMotorSolveBusy] = React.useState(false);
  const [motorSolveError, setMotorSolveError] = React.useState<string | null>(null);
  const [motorSolveCount, setMotorSolveCount] = React.useState(0);
  const [motorSolveNonce, setMotorSolveNonce] = React.useState(0);
  const [fieldDisplayMode, setFieldDisplayMode] = React.useState<FieldDisplayMode>('pressure');
  const [showFluxLines, setShowFluxLines] = React.useState(true);
  const [showFieldIntensity, setShowFieldIntensity] = React.useState(false);
  const [showField3D, setShowField3D] = React.useState(false);
  const [fieldSourceMode, setFieldSourceMode] = React.useState<FieldSourceMode>('combined');
  const [wireFieldRuns, setWireFieldRuns] = React.useState<Record<string, FieldForceWireData>>({});
  const [wireFieldLoadingKey, setWireFieldLoadingKey] = React.useState<string | null>(null);
  const [wireFieldError, setWireFieldError] = React.useState<string | null>(null);
  const [magnetFieldRuns, setMagnetFieldRuns] = React.useState<Record<string, FieldForceMagnetData>>({});
  const [magnetFieldLoadingKey, setMagnetFieldLoadingKey] = React.useState<string | null>(null);
  const [magnetFieldError, setMagnetFieldError] = React.useState<string | null>(null);
  const [showMesh, setShowMesh] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(false);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const [angleEvidenceReviewed, setAngleEvidenceReviewed] = React.useState(false);
  const [motorEvidenceReviewed, setMotorEvidenceReviewed] = React.useState(false);
  const motorSolveRequestIdRef = React.useRef(0);
  const motorSolveStartedKeyRef = React.useRef<string | null>(null);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();

  const predictionCorrect = prediction === 'up';
  const runsAtGap = runs.filter((run) => Math.abs(run.poleGapMm - poleGapMm) < 0.01);
  const positiveRun = runsAtGap.find((run) => Math.abs(run.currentA - 8) < 0.01) ?? null;
  const negativeRun = runsAtGap.find((run) => Math.abs(run.currentA + 8) < 0.01) ?? null;
  const doubledRun = runsAtGap.find((run) => Math.abs(run.currentA - 16) < 0.01) ?? null;
  const solvedGaps = [...new Set(runs.map((run) => run.poleGapMm.toFixed(3)))];
  const positiveRunAny = runs.find((run) => Math.abs(run.currentA - 8) < 0.01) ?? null;
  const reversePairGapKey = solvedGaps.find((gapKey) => {
    const gapRuns = runs.filter((run) => run.poleGapMm.toFixed(3) === gapKey);
    return [8, -8].every((target) => gapRuns.some((run) => Math.abs(run.currentA - target) < 0.01));
  }) ?? null;
  const comparisonGapKey = solvedGaps.find((gapKey) => {
    const gapRuns = runs.filter((run) => run.poleGapMm.toFixed(3) === gapKey);
    return [8, -8, 16].every((target) => gapRuns.some((run) => Math.abs(run.currentA - target) < 0.01));
  }) ?? null;
  const comparisonReady = Boolean(comparisonGapKey);
  const angleReferenceRun = comparisonGapKey
    ? runs.find((run) => (
        run.poleGapMm.toFixed(3) === comparisonGapKey
        && Math.abs(run.currentA - 16) < 0.01
      )) ?? null
    : null;
  const currentRun = runsAtGap.find((run) => Math.abs(run.currentA - currentA) < 0.01) ?? null;
  const shownRun = currentRun ?? runsAtGap[0] ?? runs[0] ?? null;
  const motorReferenceRun = positiveRun ?? positiveRunAny ?? shownRun;
  const motorSolveMatchesControls = Boolean(
    motorSolve
    && motorReferenceRun
    && Math.abs(motorSolve.current_a - motorLoopCurrentA) < 0.01
    && Math.abs(motorSolve.loop_angle_deg - motorLoopAngleDeg) < 0.01
    && Math.abs(motorSolve.pole_gap_mm - motorReferenceRun.poleGapMm) < 0.01,
  );
  const activeMotorSolve = motorSolveMatchesControls ? motorSolve : null;
  const motorSideForceN = activeMotorSolve?.side_force_magnitude_n ?? 0;
  const motorTorqueMaxNm = activeMotorSolve?.torque_max_nm ?? 0;
  const motorTorqueNm = activeMotorSolve?.torque_nm ?? 0;
  const motorFieldT = activeMotorSolve?.metrics?.wire_mean_bx_t ?? 0;
  const motorSolvePending = motorEffectOpen && (motorSolveBusy || !activeMotorSolve);
  const motorTorqueDirection = Math.abs(motorTorqueNm) < 1e-9 ? '0' : motorTorqueNm > 0 ? '+Z' : '−Z';
  const rawForceAngleSin = Math.sin((forceAngleDeg * Math.PI) / 180);
  const forceAngleSin = Math.abs(rawForceAngleSin) < 1e-9 ? 0 : rawForceAngleSin;
  const storedForceAngleRunsAtReference = angleReferenceRun
    ? forceAngleRuns.filter((item) => (
        Math.abs(item.run.poleGapMm - angleReferenceRun.poleGapMm) < 0.01
      ))
    : [];
  const forceAngleRunsAtReference = angleReferenceRun
    ? storedForceAngleRunsAtReference.some((item) => Math.abs(item.angleDeg - 90) < 0.01)
      ? storedForceAngleRunsAtReference
      : [
          ...storedForceAngleRunsAtReference,
          {
            angleDeg: 90,
            effectiveCurrentA: angleReferenceRun.currentA,
            run: angleReferenceRun,
          },
        ]
    : [];
  const activeForceAngleRun = forceAngleRunsAtReference.find((item) => (
    Math.abs(item.angleDeg - forceAngleDeg) < 0.01
  )) ?? null;
  const forceAngleEffectiveCurrentA = effectiveAngleCurrentA(
    angleReferenceRun?.currentA ?? 0,
    forceAngleDeg,
  );
  const forceAngleProjectedFEMN = (angleReferenceRun?.forceYN ?? 0) * forceAngleSin;
  const forceAngleFEMN = activeForceAngleRun?.run.forceYN ?? forceAngleProjectedFEMN;
  const forceAngleBilN = activeForceAngleRun?.run.forceBilN
    ?? (angleReferenceRun?.forceBilN ?? 0) * forceAngleSin;
  const forceAngleSweepSolvedCount = FORCE_ANGLE_SWEEP_DEGREES.filter((angleDeg) => (
    forceAngleRunsAtReference.some((item) => Math.abs(item.angleDeg - angleDeg) < 0.01)
  )).length;
  const forceAngleSweepComplete = forceAngleSweepSolvedCount === FORCE_ANGLE_SWEEP_DEGREES.length;
  const forceAngleFieldRun = activeForceAngleRun?.run ?? angleReferenceRun;
  const forceAngleFieldCurrentA = activeForceAngleRun?.effectiveCurrentA
    ?? angleReferenceRun?.currentA
    ?? 0;
  const forceAngleShowFluxLayer = !showField3D
    && fieldDisplayMode === 'field'
    && showFluxLines;
  const forceAngleShowDensityLayer = !showField3D
    && fieldDisplayMode === 'field'
    && showFieldIntensity;
  const forceAngleIntensityRange = quantileRange(
    forceAngleFieldRun?.data.element_b_mag_t ?? [],
  );
  const forceAngleArrowLength = Math.min(18, 7 + Math.abs(forceAngleFEMN) * 280);
  const forceAngleForceVectors = Math.abs(forceAngleFEMN) > 1e-9
    ? [{
        x1Mm: 0,
        y1Mm: 0,
        x2Mm: 0,
        y2Mm: forceAngleFEMN > 0 ? forceAngleArrowLength : -forceAngleArrowLength,
        label: `F ${forceDirection(forceAngleFEMN)}`,
      }]
    : [];
  const requestedRunPending = Boolean(shownRun && !currentRun);
  const shownWireField = shownRun ? wireFieldRuns[forceRunKey(shownRun.currentA, shownRun.poleGapMm)] ?? null : null;
  const shownMagnetField = shownRun ? magnetFieldRuns[shownRun.poleGapMm.toFixed(3)] ?? null : null;
  const sourceField = fieldSourceMode === 'wire'
    ? shownWireField
    : fieldSourceMode === 'magnet'
      ? shownMagnetField
      : shownRun?.data ?? null;
  const sourceFieldReady = fieldSourceMode === 'combined' || Boolean(sourceField);
  const showFluxLayer = fieldDisplayMode === 'field' && showFluxLines && sourceFieldReady;
  const showDensityLayer = fieldDisplayMode === 'field' && showFieldIntensity && sourceFieldReady;
  const combinedIntensityRange = quantileRange(
    runsAtGap.flatMap((run) => run.data.element_b_mag_t ?? []),
  );
  const wireIntensityRange = shownWireField && Math.abs(shownRun?.currentA ?? 0) > 1e-6
    ? (() => {
        const range = quantileRange(shownWireField.element_b_mag_t ?? []);
        if (!range) return undefined;
        return {
          low: 0,
          high: range.high * (16 / Math.abs(shownRun?.currentA ?? 16)),
        };
      })()
    : undefined;
  const fieldIntensityRange = fieldSourceMode === 'combined'
    ? combinedIntensityRange
    : fieldSourceMode === 'wire'
      ? wireIntensityRange
      : undefined;
  const sameCurrentGapRuns = shownRun
    ? runs.filter((run) => Math.abs(run.currentA - shownRun.currentA) < 0.01).sort((left, right) => left.poleGapMm - right.poleGapMm)
    : [];
  const guidedCurrent = !positiveRun ? 8 : !negativeRun ? -8 : !doubledRun ? 16 : currentA;

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('field-force', true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  const setStage = React.useCallback((next: 'design' | 'solve') => {
    setQuizOpen(false);
    setLabControlsOpen(next === 'solve');
    setSolveInspectorOpen(false);
    if (next === 'design') {
      setForceAngleOpen(false);
      setMotorEffectOpen(false);
    }
    onStageChange?.(next);
  }, [onStageChange]);

  const selectForceAngle = React.useCallback((angleDeg: number) => {
    const normalized = Math.min(360, Math.max(0, Math.round(angleDeg)));
    setForceAngleDeg(normalized);
    if (Math.abs(normalized - 90) >= 1) setForceAngleReviewed(true);
  }, []);

  const selectMotorLoopAngle = React.useCallback((angleDeg: number) => {
    const normalized = Math.min(360, Math.max(0, Math.round(angleDeg)));
    setMotorLoopAngleDeg(normalized);
  }, []);

  React.useEffect(() => {
    if (!motorEffectOpen || !motorReferenceRun) {
      motorSolveRequestIdRef.current += 1;
      motorSolveStartedKeyRef.current = null;
      setMotorSolveBusy(false);
      return undefined;
    }

    // Keep Magneto2D on a single local lane. Controls stay responsive while a
    // solve is running; when it settles, the busy-state change reruns this
    // effect with the newest current/angle and launches only that latest request.
    if (motorSolveBusy) return undefined;

    const requestKey = [
      motorLoopCurrentA.toFixed(3),
      motorLoopAngleDeg.toFixed(3),
      motorReferenceRun.poleGapMm.toFixed(3),
      motorSolveNonce,
    ].join(':');
    if (motorSolveStartedKeyRef.current === requestKey) return undefined;
    motorSolveStartedKeyRef.current = requestKey;
    const requestId = motorSolveRequestIdRef.current + 1;
    motorSolveRequestIdRef.current = requestId;
    const requestedCurrentA = motorLoopCurrentA;
    const requestedAngleDeg = motorLoopAngleDeg;
    const requestedPoleGapMm = motorReferenceRun.poleGapMm;

    const timeoutId = window.setTimeout(() => {
      setMotorSolveBusy(true);
      setMotorSolveError(null);

      let solveDeadlineId: number | undefined;
      const solveTimeout = new Promise<never>((_, reject) => {
        solveDeadlineId = window.setTimeout(() => {
          reject(new Error('The motor-effect FEM solve took longer than 30 seconds. Retry when the local solver is ready.'));
        }, MOTOR_SOLVE_TIMEOUT_MS);
      });

      void Promise.race([
        solveClient.fetchFieldForceMotorSolve(
          requestedCurrentA,
          requestedAngleDeg,
          requestedPoleGapMm,
        ),
        solveTimeout,
      ]).then((result) => {
        if (motorSolveRequestIdRef.current !== requestId) return;
        setMotorSolve(result);
        setMotorSolveCount((count) => count + 1);
        setMotorTorqueAnglesDeg((previous) => (
          previous.includes(result.loop_angle_deg)
            ? previous
            : [...previous, result.loop_angle_deg].sort((left, right) => left - right)
        ));
        setMotorSolveBusy(false);
      }).catch((solveError) => {
        if (motorSolveRequestIdRef.current !== requestId) return;
        setMotorSolveError(
          solveError instanceof Error
            ? solveError.message
            : 'The motor-effect FEM solve failed.',
        );
        setMotorSolveBusy(false);
      }).finally(() => {
        if (solveDeadlineId !== undefined) window.clearTimeout(solveDeadlineId);
      });
    }, 280);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [
    motorEffectOpen,
    motorLoopAngleDeg,
    motorLoopCurrentA,
    motorReferenceRun,
    motorSolveBusy,
    motorSolveNonce,
    solveClient,
  ]);

  const loadWireField = async (runCurrentA: number, runPoleGapMm: number) => {
    const key = forceRunKey(runCurrentA, runPoleGapMm);
    if (wireFieldRuns[key] || wireFieldLoadingKey !== null) return;
    setWireFieldLoadingKey(key);
    setWireFieldError(null);
    try {
      const wireField = await solveClient.fetchFieldForceWireSolve(runCurrentA, runPoleGapMm);
      setWireFieldRuns((previous) => ({ ...previous, [key]: wireField }));
    } catch (wireSolveError) {
      setWireFieldError(wireSolveError instanceof Error ? wireSolveError.message : 'The wire-only FEM solve failed.');
    } finally {
      setWireFieldLoadingKey(null);
    }
  };

  const loadMagnetField = async (runPoleGapMm: number) => {
    const key = runPoleGapMm.toFixed(3);
    if (magnetFieldRuns[key] || magnetFieldLoadingKey !== null) return;
    setMagnetFieldLoadingKey(key);
    setMagnetFieldError(null);
    try {
      const magnetField = await solveClient.fetchFieldForceMagnetSolve(runPoleGapMm);
      setMagnetFieldRuns((previous) => ({ ...previous, [key]: magnetField }));
    } catch (magnetSolveError) {
      setMagnetFieldError(magnetSolveError instanceof Error ? magnetSolveError.message : 'The magnet-only FEM solve failed.');
    } finally {
      setMagnetFieldLoadingKey(null);
    }
  };

  const selectFieldSource = (source: FieldSourceMode) => {
    setFieldSourceMode(source);
    if (source !== 'combined' && fieldDisplayMode === 'pressure') {
      setFieldDisplayMode('field');
      setShowFluxLines(true);
      setShowFieldIntensity(false);
    }
    if (source === 'wire' && shownRun) void loadWireField(shownRun.currentA, shownRun.poleGapMm);
    if (source === 'magnet' && shownRun) void loadMagnetField(shownRun.poleGapMm);
  };

  const toggleFieldLayer = (layer: 'lines' | 'density') => {
    if (fieldDisplayMode === 'pressure') {
      setFieldDisplayMode('field');
      setShowFluxLines(layer === 'lines');
      setShowFieldIntensity(layer === 'density');
      return;
    }
    if (layer === 'lines') {
      setShowFluxLines((visible) => !visible);
    } else {
      setShowFieldIntensity((visible) => !visible);
    }
  };

  const selectSolvedCurrent = (nextCurrentA: number) => {
    setCurrentA(nextCurrentA);
    if (fieldSourceMode === 'wire') void loadWireField(nextCurrentA, poleGapMm);
    if (fieldSourceMode === 'magnet') void loadMagnetField(poleGapMm);
  };

  const selectSolvedRun = (run: ForceRun) => {
    setCurrentA(run.currentA);
    setPoleGapMm(run.poleGapMm);
    if (fieldSourceMode === 'wire') void loadWireField(run.currentA, run.poleGapMm);
    if (fieldSourceMode === 'magnet') void loadMagnetField(run.poleGapMm);
  };

  const solveCurrent = async (
    requestedCurrentA = currentA,
    requestedPoleGapMm = poleGapMm,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const run = runFromData(await solveClient.fetchFieldForceSolve(requestedCurrentA, requestedPoleGapMm));
      setCurrentA(requestedCurrentA);
      setPoleGapMm(requestedPoleGapMm);
      setRuns((previous) => [run, ...previous.filter((item) => forceRunKey(item.currentA, item.poleGapMm) !== forceRunKey(requestedCurrentA, requestedPoleGapMm))].slice(0, 16));
      if (fieldSourceMode === 'wire') void loadWireField(run.currentA, run.poleGapMm);
      if (fieldSourceMode === 'magnet') void loadMagnetField(run.poleGapMm);
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The conductor-force solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const solveForceAngles = async (anglesDeg: number[]) => {
    if (!angleReferenceRun || forceAngleSolveBusy || anglesDeg.length === 0) return;
    setForceAngleSolveBusy(true);
    setForceAngleSolveError(null);
    setForceAngleSolveProgress({ complete: 0, total: anglesDeg.length });

    const referenceGapMm = angleReferenceRun.poleGapMm;
    const solvedByCurrent = new Map<string, ForceRun>();
    runs
      .filter((run) => Math.abs(run.poleGapMm - referenceGapMm) < 0.01)
      .forEach((run) => solvedByCurrent.set(forceRunKey(run.currentA, referenceGapMm), run));
    forceAngleRunsAtReference.forEach((item) => {
      solvedByCurrent.set(forceRunKey(item.effectiveCurrentA, referenceGapMm), item.run);
    });

    try {
      for (let index = 0; index < anglesDeg.length; index += 1) {
        const angleDeg = Math.min(360, Math.max(0, Math.round(anglesDeg[index])));
        const effectiveCurrentA = effectiveAngleCurrentA(angleReferenceRun.currentA, angleDeg);
        const currentKey = forceRunKey(effectiveCurrentA, referenceGapMm);
        let run = solvedByCurrent.get(currentKey);
        if (!run) {
          run = runFromData(
            await solveClient.fetchFieldForceSolve(effectiveCurrentA, referenceGapMm),
          );
          solvedByCurrent.set(currentKey, run);
        }
        const nextAngleRun: ForceAngleRun = { angleDeg, effectiveCurrentA, run };
        setForceAngleRuns((previous) => [
          nextAngleRun,
          ...previous.filter((item) => (
            forceAngleRunKey(item.angleDeg, item.run.poleGapMm)
            !== forceAngleRunKey(angleDeg, referenceGapMm)
          )),
        ].slice(0, 48));
        setForceAngleSolveProgress({ complete: index + 1, total: anglesDeg.length });
      }
      setForceAngleReviewed(true);
      setAngleEvidenceReviewed(false);
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
    } catch (angleSolveError) {
      setForceAngleSolveError(
        angleSolveError instanceof Error
          ? angleSolveError.message
          : 'The FEM angle checkpoint solve failed.',
      );
    } finally {
      setForceAngleSolveBusy(false);
    }
  };

  const positiveComplete = Boolean(positiveRunAny);
  const reverseComplete = Boolean(reversePairGapKey);
  const angleSolved = forceAngleReviewed && forceAngleSweepComplete;
  const angleComplete = angleSolved && angleEvidenceReviewed;
  const motorEffectSolved = motorEffectReviewed && Boolean(activeMotorSolve) && !motorSolveBusy;
  const motorEffectComplete = motorEffectSolved && motorEvidenceReviewed;
  const activeProgressStepId: LessonFiveProgressStepId = quizOpen
    ? 'check'
    : motorEffectOpen
      ? 'motor'
      : forceAngleOpen
        ? 'angle'
        : lessonStage === 'design'
          ? 'predict'
          : !positiveComplete
            ? 'positive'
            : !reverseComplete
              ? 'reverse'
              : !comparisonReady
                ? 'scale'
                : 'angle';

  const selectProgressStep = React.useCallback((stepId: string) => {
    const nextStep = stepId as LessonFiveProgressStepId;
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    if (nextStep === 'predict') {
      setStage('design');
      return;
    }
    if (nextStep === 'positive' && predictionCorrect) {
      setStage('solve');
      setForceAngleOpen(false);
      setMotorEffectOpen(false);
      setCurrentA(8);
      if (positiveRunAny) setPoleGapMm(positiveRunAny.poleGapMm);
      return;
    }
    if (nextStep === 'reverse' && positiveRunAny) {
      setStage('solve');
      setForceAngleOpen(false);
      setMotorEffectOpen(false);
      setPoleGapMm(positiveRunAny.poleGapMm);
      setCurrentA(-8);
      return;
    }
    if (nextStep === 'scale' && reversePairGapKey) {
      setStage('solve');
      setForceAngleOpen(false);
      setMotorEffectOpen(false);
      setPoleGapMm(Number(reversePairGapKey));
      setCurrentA(16);
      return;
    }
    if (nextStep === 'angle' && angleReferenceRun) {
      setQuizOpen(false);
      onStageChange?.('solve');
      setMotorEffectOpen(false);
      setForceAngleOpen(true);
      setCurrentA(angleReferenceRun.currentA);
      setPoleGapMm(angleReferenceRun.poleGapMm);
      setShowField3D(true);
      setLabControlsOpen(true);
      return;
    }
    if (nextStep === 'motor' && angleComplete) {
      setQuizOpen(false);
      onStageChange?.('solve');
      setForceAngleOpen(false);
      setMotorEffectOpen(true);
      setShowField3D(false);
      setLabControlsOpen(true);
      return;
    }
    if (nextStep === 'check' && motorEffectComplete) {
      onStageChange?.('solve');
      setQuizOpen(true);
    }
  }, [
    angleComplete,
    angleReferenceRun,
    motorEffectComplete,
    onStageChange,
    positiveRunAny,
    predictionCorrect,
    reversePairGapKey,
    setStage,
  ]);

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'positive', label: '+8 A', complete: positiveComplete, available: predictionCorrect },
    { id: 'reverse', label: 'Reverse', complete: reverseComplete, available: positiveComplete },
    { id: 'scale', label: 'Double', complete: comparisonReady, available: reverseComplete },
    { id: 'angle', label: 'θ angle', complete: angleComplete, available: comparisonReady },
    { id: 'motor', label: 'Motor effect', complete: motorEffectComplete, available: angleComplete },
    { id: 'check', label: 'Check', complete: quizPassed, available: motorEffectComplete },
  ], [
    angleComplete,
    comparisonReady,
    motorEffectComplete,
    positiveComplete,
    predictionCorrect,
    quizPassed,
    reverseComplete,
  ]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 5,
    lessonCount: 10,
    title: 'Turn Field into Force',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const completedStepCount = lessonProgressSteps.filter((item) => item.complete).length;
  const currentGoal = LESSON_FIVE_GOALS[activeProgressStepId];

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (solveInspectorOpen) solveInspectorRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [activeProgressStepId, solveInspectorOpen]);

  const forceArrowLength = shownRun ? Math.min(18, 7 + Math.abs(shownRun.forceYN) * 280) : 10;
  const forceVectors = shownRun && Math.abs(shownRun.forceYN) > 1e-9
    ? [{ x1Mm: 0, y1Mm: 0, x2Mm: 0, y2Mm: shownRun.forceYN > 0 ? forceArrowLength : -forceArrowLength, label: `F ${forceDirection(shownRun.forceYN)}` }]
    : [];
  const showMagnetPathGuide = Boolean(shownRun && fieldSourceMode === 'magnet' && showFluxLayer);
  const magnetHalfHeightMm = shownRun?.data.magnet_half_height_mm ?? 6;
  const internalArrowYmm = -magnetHalfHeightMm * 0.42;
  const gapArrowYmm = magnetHalfHeightMm - 1;
  const outerReturnYmm = magnetHalfHeightMm + 8;
  const poleFaceLabels: MeshViewerPointLabel[] = shownRun && fieldSourceMode !== 'wire'
    ? [
        { xMm: -shownRun.data.magnet_outer_x_mm + 2.5, yMm: 0, label: 'S', tone: 'south' },
        { xMm: -shownRun.data.magnet_inner_x_mm - 2.5, yMm: 0, label: 'N', tone: 'north' },
        { xMm: shownRun.data.magnet_inner_x_mm + 2.5, yMm: 0, label: 'S', tone: 'south' },
        { xMm: shownRun.data.magnet_outer_x_mm - 2.5, yMm: 0, label: 'N', tone: 'north' },
      ]
    : [];
  const magnetPathVectors: MeshViewerDirectionVector[] = shownRun && showMagnetPathGuide
    ? [
        {
          x1Mm: -shownRun.data.magnet_outer_x_mm + 4,
          y1Mm: internalArrowYmm,
          x2Mm: -shownRun.data.magnet_inner_x_mm - 4,
          y2Mm: internalArrowYmm,
          label: 'inside S → N',
          labelYmm: -magnetHalfHeightMm * 0.78,
          tone: 'slate',
        },
        {
          x1Mm: shownRun.data.magnet_inner_x_mm + 4,
          y1Mm: internalArrowYmm,
          x2Mm: shownRun.data.magnet_outer_x_mm - 4,
          y2Mm: internalArrowYmm,
          label: 'inside S → N',
          labelYmm: -magnetHalfHeightMm * 0.78,
          tone: 'slate',
        },
        {
          x1Mm: -shownRun.data.magnet_inner_x_mm + 0.8,
          y1Mm: gapArrowYmm,
          x2Mm: shownRun.data.magnet_inner_x_mm - 0.8,
          y2Mm: gapArrowYmm,
          label: 'useful gap field N → S',
          labelYmm: magnetHalfHeightMm + 2,
          tone: 'cyan',
        },
        {
          x1Mm: shownRun.data.magnet_outer_x_mm - 1,
          y1Mm: outerReturnYmm,
          x2Mm: -shownRun.data.magnet_outer_x_mm + 1,
          y2Mm: outerReturnYmm,
          label: 'outer return N → S',
          labelYmm: outerReturnYmm + 2.5,
          tone: 'blue',
          dashed: true,
        },
      ]
    : [];

  const openAngleLab = () => {
    if (!angleReferenceRun) return;
    setQuizOpen(false);
    onStageChange?.('solve');
    setMotorEffectOpen(false);
    setForceAngleOpen(true);
    setCurrentA(angleReferenceRun.currentA);
    setPoleGapMm(angleReferenceRun.poleGapMm);
    setShowField3D(true);
    setSolveInspectorOpen(false);
    setLabControlsOpen(true);
  };

  const openMotorLab = () => {
    setAngleEvidenceReviewed(true);
    setForceAngleOpen(false);
    setMotorEffectOpen(true);
    setShowField3D(false);
    setSolveInspectorOpen(false);
    setLabControlsOpen(true);
  };

  const runMotorTorqueSweep = () => {
    if (!activeMotorSolve || motorSolveBusy || motorSolveError) return;
    setMotorTorqueAnglesDeg([...MOTOR_TORQUE_SWEEP_DEGREES]);
    setMotorEffectReviewed(true);
    setMotorEvidenceReviewed(false);
    setLabControlsOpen(false);
    setSolveInspectorOpen(true);
  };

  const continueToCheck = () => {
    setMotorEvidenceReviewed(true);
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    setQuizOpen(true);
  };

  const labInsight = motorEffectOpen
    ? !motorEffectReviewed
      ? 'One FEM side-force solve calibrates the loop. Run the full torque-angle sweep.'
      : !motorEvidenceReviewed
        ? 'Torque rises, reverses, and returns to zero. Inspect the full-cycle evidence.'
        : 'Force becomes useful motion when opposite forces act through a lever arm.'
    : forceAngleOpen
      ? !forceAngleSweepComplete
        ? 'Rotate current through a full cycle, then solve the thirteen signed FEM checkpoints.'
        : !angleEvidenceReviewed
          ? 'The curve reveals sin θ. Inspect the evidence before moving to a loop.'
          : 'Only the current perpendicular to B produces force.'
      : !positiveComplete
        ? 'Start at +8 A and reveal the force direction.'
        : !reverseComplete
          ? 'Reverse current. The force should reverse with it.'
          : !comparisonReady
            ? 'Double current. The force should double too.'
            : 'Direction and scale are established. Now change the vector angle.';

  return (
    <main
      className={`learning-shell learning-lesson-shell field-force-shell is-${lessonStage}-stage${quizOpen ? ' is-quiz-open' : ''}`}
    >
      {lessonStage === 'solve' && !quizOpen && labControlsOpen ? (
      <aside className={`learning-control-panel field-force-control-panel${!motorEffectOpen && !forceAngleOpen ? ' is-baseline' : ''}${forceAngleOpen ? ' is-theta' : ''}${motorEffectOpen ? ' is-motor' : ''}`} aria-label="Force experiment controls">
        <button type="button" className="field-force-drawer-close" onClick={() => setLabControlsOpen(false)} aria-label="Close force controls">×</button>

        <section className="learning-control-section">
          <p className="field-force-panel-kicker">Lab setup · {lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label}</p>
          <h2>Force lab</h2>
          <section className="field-force-lab-goal is-compact" aria-label="Current lesson goal">
            <span>{completedStepCount}/{lessonProgressSteps.length}</span>
            <div>
              <p>Current goal</p>
              <strong>{currentGoal.title}</strong>
              <small>{currentGoal.detail}</small>
            </div>
          </section>

          {motorEffectOpen && !quizOpen ? (
            <>
              <section className="field-force-control-card motor-effect-control-card">
                <div className="motor-effect-control-summary">
                  <span>ONE ENERGIZED TURN · LIVE FEM</span>
                  <strong>Horizontal loop · two separated voltage leads</strong>
                </div>
                <div className={`motor-effect-solve-status${motorSolveError ? ' is-error' : motorSolvePending ? ' is-solving' : ' is-solved'}`} role="status" aria-live="polite">
                  <span>{motorSolveError ? 'FEM ERROR' : motorSolvePending ? 'MAGNETO2D SOLVING' : `FEM SOLVE #${motorSolveCount}`}</span>
                  <strong>
                    {motorSolveError
                      ? motorSolveError
                      : motorSolvePending
                        ? `${signed(motorLoopCurrentA, 0)} A · δ ${motorLoopAngleDeg}°`
                        : `${signed(activeMotorSolve?.current_a ?? 0, 0)} A · δ ${activeMotorSolve?.loop_angle_deg ?? 0}° · ${activeMotorSolve?.generation_time_ms.toFixed(0) ?? 0} ms`}
                  </strong>
                  {motorSolveError ? (
                    <button type="button" onClick={() => setMotorSolveNonce((nonce) => nonce + 1)}>Retry FEM solve</button>
                  ) : (
                    <small>
                      {motorSolvePending
                        ? 'Meshing the pole gap and integrating J × B in the active conductor…'
                        : 'Fresh 2D FEM side force · 3D loop-angle lever arm'}
                    </small>
                  )}
                </div>
                <label><span>Loop current</span><strong>{signed(motorLoopCurrentA, 0)} A</strong></label>
                <div className="motor-effect-current-switch" role="group" aria-label="Motor loop current direction">
                  {[8, -8].map((loopCurrent) => (
                    <button
                      key={loopCurrent}
                      type="button"
                      className={motorLoopCurrentA === loopCurrent ? 'is-active' : ''}
                      onClick={() => setMotorLoopCurrentA(loopCurrent)}
                    >
                      {signed(loopCurrent, 0)} A
                    </button>
                  ))}
                </div>
                <div className="motor-effect-angle-control">
                  <label htmlFor="motor-effect-angle">
                    <span>Loop-normal angle δ<sub>A</sub> from B</span>
                    <strong>{motorLoopAngleDeg}°</strong>
                  </label>
                  <input
                    id="motor-effect-angle"
                    type="range"
                    min="0"
                    max="360"
                    step="5"
                    value={motorLoopAngleDeg}
                    aria-label={`Reference loop-normal angle from the field ${motorLoopAngleDeg} degrees`}
                    onChange={(event) => selectMotorLoopAngle(Number(event.currentTarget.value))}
                  />
                  <div className="motor-effect-angle-scale">
                    <span>0° aligned</span>
                    <span>90° peak</span>
                    <span>180° aligned</span>
                    <span>270° reverse peak</span>
                  </div>
                  <div className="motor-effect-angle-presets" role="group" aria-label="Torque angle presets">
                    {[0, 90, 180, 270].map((angleDeg) => (
                      <button
                        key={angleDeg}
                        type="button"
                        className={motorLoopAngleDeg === angleDeg ? 'is-active' : ''}
                        onClick={() => selectMotorLoopAngle(angleDeg)}
                      >
                        {angleDeg}°
                      </button>
                    ))}
                  </div>
                </div>
                <div className="motor-effect-side-readout">
                  <div><span>AB force</span><strong>{activeMotorSolve ? `${motorLoopCurrentA >= 0 ? '⊙ up +Y' : '⊗ down −Y'} · ${(motorSideForceN * 1e3).toFixed(1)} mN` : 'Awaiting FEM'}</strong></div>
                  <div><span>CD force</span><strong>{activeMotorSolve ? `${motorLoopCurrentA >= 0 ? '⊗ down −Y' : '⊙ up +Y'} · ${(motorSideForceN * 1e3).toFixed(1)} mN` : 'Awaiting FEM'}</strong></div>
                </div>
                {!motorEffectReviewed ? (
                  <button
                    type="button"
                    className="field-force-guide-button"
                    disabled={motorSolvePending || Boolean(motorSolveError)}
                    onClick={runMotorTorqueSweep}
                  >
                    {motorSolvePending ? 'Wait for FEM solve…' : 'Run motor sweep'}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="field-force-guide-button"
                    disabled={motorSolvePending || Boolean(motorSolveError)}
                    onClick={() => {
                      setLabControlsOpen(false);
                      setSolveInspectorOpen(true);
                    }}
                  >
                    {motorSolvePending ? 'Wait for FEM solve…' : 'Review torque evidence'}
                  </button>
                )}
              </section>
            </>
          ) : forceAngleOpen && angleReferenceRun && !quizOpen ? (
            <>
              <section className="field-force-control-card field-force-theta-card">
                <div className="motor-effect-control-summary">
                  <span>ANGLE SWEEP · LIVE 2D FEM</span>
                  <strong>Solve wire force versus θ</strong>
                </div>
                <div className="motor-effect-angle-control field-force-theta-control">
                  <label htmlFor="field-force-angle-slider">
                    <span>Signed current phase θ from B</span>
                    <strong>{forceAngleDeg}°</strong>
                  </label>
                  <input
                    id="field-force-angle-slider"
                    type="range"
                    min="0"
                    max="360"
                    step="5"
                    value={forceAngleDeg}
                    disabled={forceAngleSolveBusy}
                    aria-label={`Signed current phase from magnetic field ${forceAngleDeg} degrees`}
                    onChange={(event) => selectForceAngle(Number(event.currentTarget.value))}
                  />
                  <div className="field-force-theta-scale">
                    <span>0° zero</span>
                    <span>180° zero</span>
                    <span>360° full cycle</span>
                  </div>
                  <div className="field-force-theta-presets" role="group" aria-label="Current-to-field angle presets">
                    {FORCE_ANGLE_SWEEP_DEGREES.map((angleDeg) => (
                      <button
                        key={angleDeg}
                        type="button"
                        disabled={forceAngleSolveBusy}
                        className={forceAngleDeg === angleDeg ? 'is-active' : ''}
                        onClick={() => selectForceAngle(angleDeg)}
                      >
                        {angleDeg}°
                      </button>
                    ))}
                  </div>
                </div>
                <div className="field-force-theta-readout">
                  <div><span>sin θ</span><strong>{forceAngleSin.toFixed(3)}</strong></div>
                  <div><span>2D FEM current I<sub>⊥</sub></span><strong>{signed(forceAngleEffectiveCurrentA, 2)} A</strong></div>
                  <div><span>{activeForceAngleRun ? 'Solved FEM force' : 'Projected preview'}</span><strong>{signed(forceAngleFEMN * 1e3)} mN</strong></div>
                  <div><span>BIL estimate</span><strong>{signed(forceAngleBilN * 1e3)} mN</strong></div>
                </div>
                <div
                  className={`field-force-angle-solve-status${forceAngleSolveBusy ? ' is-solving' : ''}${forceAngleSolveError ? ' is-error' : ''}${forceAngleSweepComplete ? ' is-complete' : ''}`}
                  role="status"
                  aria-live="polite"
                >
                  <span>
                    {forceAngleSolveError
                      ? 'FEM ANGLE SOLVE FAILED'
                      : forceAngleSolveBusy
                        ? 'MAGNETO2D ANGLE SWEEP'
                        : forceAngleSweepComplete
                          ? 'FEM ANGLE SWEEP COMPLETE'
                          : 'FEM CHECKPOINTS READY'}
                  </span>
                  <strong>
                    {forceAngleSolveError
                      ?? (forceAngleSolveBusy
                        ? `${forceAngleSolveProgress.complete} / ${forceAngleSolveProgress.total} checkpoints`
                        : `${forceAngleSweepSolvedCount} / ${FORCE_ANGLE_SWEEP_DEGREES.length} solved`)}
                  </strong>
                </div>
                <p className="field-force-gap-hint">
                  0–180° produces upward force. From 180–360°, current and force reverse.
                </p>
              </section>
            </>
          ) : !quizOpen ? (
            <>
              <section className="field-force-control-card field-force-baseline-controls">
                <label><span>Current</span><strong>{signed(currentA, 0)} A</strong></label>
                <div className="field-force-current-presets" role="group" aria-label="Conductor current">
                  {[-8, 8, 16].map((presetCurrent) => (
                    <button
                      key={presetCurrent}
                      type="button"
                      className={currentA === presetCurrent ? 'is-active' : ''}
                      disabled={busy}
                      onClick={() => setCurrentA(presetCurrent)}
                    >
                      {signed(presetCurrent, 0)} A
                    </button>
                  ))}
                </div>
                <div className="field-force-control-divider" />
                <label htmlFor="field-force-gap-slider"><span>Pole gap · each side</span><strong>{poleGapMm.toFixed(1)} mm</strong></label>
                <input
                  id="field-force-gap-slider"
                  type="range"
                  min={MIN_POLE_GAP_MM}
                  max={MAX_POLE_GAP_MM}
                  step={POLE_GAP_STEP_MM}
                  value={poleGapMm}
                  disabled={busy}
                  aria-label={`Magnet-to-wire gap on each side ${poleGapMm.toFixed(1)} millimeters`}
                  onChange={(event) => setPoleGapMm(Number(event.currentTarget.value))}
                />
                <div className="field-force-scale"><span>0.5 mm</span><span>both poles move</span><span>16 mm</span></div>
                <div className="field-force-gap-presets" role="group" aria-label="Pole gap presets">
                  {[
                    { label: 'Close', value: 2 },
                    { label: 'Baseline', value: 8 },
                    { label: 'Wide', value: 16 },
                  ].map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      className={Math.abs(poleGapMm - preset.value) < 0.01 ? 'is-active' : ''}
                      disabled={busy}
                      onClick={() => setPoleGapMm(preset.value)}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <div className={`field-force-live-setup-state${requestedRunPending || !shownRun ? ' is-preview' : ' is-solved'}`} role="status" aria-live="polite">
                  <span>{requestedRunPending || !shownRun ? 'LIVE PREVIEW' : 'SOLVED'}</span>
                  <strong>{requestedRunPending || !shownRun ? 'Geometry updates instantly' : 'FEM matches this setup'}</strong>
                  <small>{requestedRunPending || !shownRun ? 'Use the orange action below when the setup looks right.' : 'Move either control to create another comparison.'}</small>
                </div>
                {error ? <p className="field-force-error">{error}</p> : null}
              </section>
            </>
          ) : null}
        </section>

      </aside>
      ) : null}

      <section className="learning-main-stage field-force-main">
        {quizOpen ? (
          <section className="field-force-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you turn I and B into force?</h2>
            <p>Use the vector directions and solved scaling—not a memorized motor diagram.</p>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </section>
        ) : lessonStage === 'design' ? (
          <section className="field-force-predict-experience" aria-label="Lorentz force direction prediction">
            <div className="field-force-predict-heading">
              <p className="learning-kicker">Lesson 5 · Predict</p>
              <h1>Which way does the wire move?</h1>
              <p>Current crosses a magnetic field. Predict the force before the solver reveals it.</p>
            </div>
            <div className="field-force-predict-visual"><FieldForcePredictionDiagram /></div>
            <div className="field-force-predict-question">
              <strong>B points +X. Current points +Z, toward you. Where does I × B point?</strong>
              <div className="field-force-predictions" role="radiogroup" aria-label="Wire force direction prediction">
                {([
                  ['up', 'Up (+Y)', '+Z × +X points upward.'],
                  ['down', 'Down (−Y)', 'This is the force for reversed current.'],
                  ['none', 'No force', 'Perpendicular I and B produce the largest cross product.'],
                ] as Array<[Prediction, string, string]>).map(([value, label, detail], index) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={prediction === value}
                    className={`${prediction === value ? 'is-selected' : ''}${prediction === value && value === 'up' ? ' is-correct' : ''}`}
                    onClick={() => setPrediction(value)}
                  >
                    <span>{index + 1}</span><div><strong>{label}</strong><small>{detail}</small></div>
                  </button>
                ))}
              </div>
            </div>
            <div className="field-force-predict-response" aria-live="polite">
              {prediction ? (
                <p className={`field-force-feedback${predictionCorrect ? ' is-correct' : ''}`}>
                  {predictionCorrect
                    ? 'Exactly. +Z × +X = +Y. Now let the FEM solve verify it.'
                    : 'Point your index finger with current (+Z), your middle finger with B (+X), and your thumb gives force.'}
                </p>
              ) : <p>Make a prediction before seeing the solved force.</p>}
            </div>
            <button type="button" className="learning-primary-button field-force-predict-primary" disabled={!predictionCorrect} onClick={() => setStage('solve')}>
              Reveal the force →
            </button>
            <div className="field-force-predict-footer">
              <div><button type="button" onClick={onBackToCatalog}>← All lessons</button><button type="button" onClick={onBackHome}>Design start</button></div>
              <span>1 of 7 · Predict</span>
            </div>
          </section>
        ) : forceAngleOpen && angleReferenceRun ? (
          <div className="field-force-viewer field-force-angle-viewer">
            <div className="mesh-viewer-header field-force-visual-header">
              <div className="mesh-viewer-title">
                <h3>Current phase · rotate I through one full cycle</h3>
                <span>
                  +16 A current vector · θ = {forceAngleDeg}° · {activeForceAngleRun
                    ? `FEM solved with I⊥ ${signed(activeForceAngleRun.effectiveCurrentA, 2)} A`
                    : 'projected preview awaiting FEM'}
                </span>
              </div>
              <div className="field-force-header-tools">
                <div className="field-force-view-toggle field-force-angle-view-toggle" role="group" aria-label="Angle checkpoint visualization">
                  <button
                    type="button"
                    className={forceAngleShowFluxLayer ? 'is-active' : ''}
                    onClick={() => {
                      if (showField3D) {
                        setShowField3D(false);
                        setFieldDisplayMode('field');
                        setShowFluxLines(true);
                      } else {
                        toggleFieldLayer('lines');
                      }
                    }}
                    aria-pressed={forceAngleShowFluxLayer}
                  >
                    <span /> Flux lines
                  </button>
                  <button
                    type="button"
                    className={forceAngleShowDensityLayer ? 'is-active' : ''}
                    onClick={() => {
                      if (showField3D) {
                        setShowField3D(false);
                        setFieldDisplayMode('field');
                        setShowFieldIntensity(true);
                      } else {
                        toggleFieldLayer('density');
                      }
                    }}
                    aria-pressed={forceAngleShowDensityLayer}
                  >
                    <span className="is-density" /> |B| map
                  </button>
                  <button
                    type="button"
                    className={!showField3D && showMesh ? 'is-active' : ''}
                    onClick={() => {
                      setShowMesh((visible) => showField3D ? true : !visible);
                      setShowField3D(false);
                    }}
                    aria-pressed={!showField3D && showMesh}
                  >
                    <span className="is-mesh" /> Mesh
                  </button>
                  <button
                    type="button"
                    className={showField3D ? 'is-active' : ''}
                    onClick={() => setShowField3D(true)}
                    aria-pressed={showField3D}
                  >
                    <span className="is-three" /> 3D
                  </button>
                </div>
              </div>
            </div>
            <div className="field-force-canvas">
              {showField3D ? (
                <FieldForce3D
                  angleDeg={forceAngleDeg}
                  currentA={angleReferenceRun.currentA}
                  fieldSource="combined"
                  forceYN={forceAngleFEMN}
                  poleGapMm={angleReferenceRun.poleGapMm}
                />
              ) : (
                <>
                  <MeshViewer
                    meshData={forceAngleFieldRun?.data ?? angleReferenceRun.data}
                    embedded
                    compactEmbedded
                    toolbarMode="zoom-only"
                    toolbarLabel={`${activeForceAngleRun ? `θ ${forceAngleDeg}° solved FEM` : 'θ 90° reference FEM'}${
                      forceAngleShowFluxLayer && forceAngleShowDensityLayer
                        ? ' · |B| map + flux lines'
                        : forceAngleShowFluxLayer
                          ? ' · flux lines'
                          : forceAngleShowDensityLayer
                            ? ' · |B| map'
                            : ' · geometry'
                    }`}
                    splitForceMagnetPolarity
                    showMeshEdges={showMesh}
                    showFieldIntensity={forceAngleShowDensityLayer}
                    fieldIntensityRange={forceAngleIntensityRange}
                    smoothFieldIntensity
                    fieldLinesVisible={forceAngleShowFluxLayer}
                    animateFieldArrows={forceAngleShowFluxLayer}
                    viewportPanEnabled={false}
                    pointLabels={[
                      ...poleFaceLabels,
                      {
                        xMm: 0,
                        yMm: 0,
                        label: currentSymbol(forceAngleFieldCurrentA),
                        tone: 'neutral',
                      } as MeshViewerPointLabel,
                    ]}
                    forceVectors={forceAngleForceVectors}
                  />
                  {!activeForceAngleRun ? (
                    <div className="field-force-angle-reference-note" role="status">
                      Showing the θ = 90° reference field. Run θ = {forceAngleDeg}° FEM to replace it.
                    </div>
                  ) : null}
                </>
              )}
              {forceAngleSolveBusy ? (
                <div className="field-force-angle-solve-overlay" role="status">
                  <strong>Running Magneto2D angle sweep…</strong>
                  <span>{forceAngleSolveProgress.complete} / {forceAngleSolveProgress.total} checkpoints · current view θ {forceAngleDeg}°</span>
                </div>
              ) : null}
            </div>
          </div>
        ) : motorEffectOpen && motorReferenceRun ? (
          <div className="field-force-viewer motor-effect-viewer">
            <div className="mesh-viewer-header field-force-visual-header">
              <div className="mesh-viewer-title">
                <h3>Motor effect · horizontal energized loop</h3>
                <span>Separated voltage leads · area ±Y · equal opposite force pair</span>
              </div>
              <div className="field-force-header-tools">
                <div className="field-force-view-toggle motor-effect-view-toggle" role="group" aria-label="Motor effect view">
                  <button type="button" className={!showField3D ? 'is-active' : ''} onClick={() => setShowField3D(false)} aria-pressed={!showField3D}><span className="is-loop" /> 2D loop</button>
                  <button type="button" className={showField3D ? 'is-active' : ''} onClick={() => setShowField3D(true)} aria-pressed={showField3D}><span className="is-three" /> 3D</button>
                </div>
              </div>
            </div>
            <div className="field-force-canvas motor-effect-canvas">
              {showField3D ? (
                <MotorEffectLoop3D
                  currentA={motorLoopCurrentA}
                  fieldT={motorFieldT}
                  sideForceN={motorSideForceN}
                  loopAngleDeg={motorLoopAngleDeg}
                  torqueNm={motorTorqueNm}
                />
              ) : (
                <MotorEffectLoopDiagram
                  currentA={motorLoopCurrentA}
                  fieldT={motorFieldT}
                  sideForceN={motorSideForceN}
                  torqueNm={motorTorqueNm}
                  loopAngleDeg={motorLoopAngleDeg}
                />
              )}
              {motorSolvePending || motorSolveError ? (
                <div className={`motor-effect-solve-overlay${motorSolveError ? ' is-error' : ''}`} role="status">
                  <strong>{motorSolveError ? 'Motor-effect FEM solve failed' : 'Running Magneto2D FEM solve…'}</strong>
                  <span>
                    {motorSolveError
                      ? motorSolveError
                      : `${signed(motorLoopCurrentA, 0)} A · δ ${motorLoopAngleDeg}° · ${motorReferenceRun.poleGapMm.toFixed(1)} mm gap`}
                  </span>
                  {motorSolveError ? (
                    <button type="button" onClick={() => setMotorSolveNonce((nonce) => nonce + 1)}>Retry</button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        ) : shownRun && !requestedRunPending ? (
          <div className="field-force-viewer">
            <div className="mesh-viewer-header field-force-visual-header">
              <div className="mesh-viewer-title">
                <h3>{fieldSourceMode === 'combined' ? 'Field + current → force' : fieldSourceMode === 'magnet' ? 'Permanent-magnet field' : 'Conductor field'}</h3>
                <span>{fieldSourceMode === 'magnet' ? 'I = 0 A' : `${signed(shownRun.currentA, 0)} A`} · {shownRun.poleGapMm.toFixed(1)} mm gap each side</span>
              </div>
              <div className="field-force-header-tools">
                <div className="field-force-source-toggle" role="group" aria-label="Field source">
                  <button type="button" aria-label="Combined FEM" className={fieldSourceMode === 'combined' ? 'is-active' : ''} onClick={() => selectFieldSource('combined')} aria-pressed={fieldSourceMode === 'combined'}>Combined</button>
                  <button type="button" aria-label="Magnet-only FEM" className={fieldSourceMode === 'magnet' ? 'is-active' : ''} onClick={() => selectFieldSource('magnet')} aria-pressed={fieldSourceMode === 'magnet'}>Magnets</button>
                  <button type="button" aria-label="Wire-only FEM" className={fieldSourceMode === 'wire' ? 'is-active' : ''} onClick={() => selectFieldSource('wire')} aria-pressed={fieldSourceMode === 'wire'}>Wire</button>
                </div>
                <div className="field-force-view-toggle" role="group" aria-label="Field visualization">
                  <button type="button" disabled={fieldSourceMode !== 'combined'} className={!showField3D && fieldDisplayMode === 'pressure' ? 'is-active' : ''} onClick={() => { setShowField3D(false); setFieldDisplayMode('pressure'); }} aria-pressed={!showField3D && fieldDisplayMode === 'pressure'}><span className="is-pressure" /> Field pressure</button>
                  <button type="button" disabled={!sourceFieldReady} className={!showField3D && showFluxLayer ? 'is-active' : ''} onClick={() => { setShowField3D(false); toggleFieldLayer('lines'); }} aria-pressed={!showField3D && showFluxLayer}><span /> Flux lines</button>
                  <button type="button" disabled={!sourceFieldReady} className={!showField3D && showDensityLayer ? 'is-active' : ''} onClick={() => { setShowField3D(false); toggleFieldLayer('density'); }} aria-pressed={!showField3D && showDensityLayer}><span className="is-density" /> |B| map</button>
                  <button type="button" className={!showField3D && showMesh ? 'is-active' : ''} onClick={() => { setShowMesh((visible) => showField3D ? true : !visible); setShowField3D(false); }} aria-pressed={!showField3D && showMesh}><span className="is-mesh" /> Mesh</button>
                  <button type="button" className={showField3D ? 'is-active' : ''} onClick={() => setShowField3D(true)} aria-pressed={showField3D}><span className="is-three" /> 3D</button>
                </div>
              </div>
            </div>
            <div className="field-force-canvas">
              {showField3D ? (
                <FieldForce3D
                  currentA={shownRun.currentA}
                  fieldSource={fieldSourceMode}
                  forceYN={shownRun.forceYN}
                  poleGapMm={shownRun.poleGapMm}
                />
              ) : (
                <>
              {fieldSourceMode === 'combined' && fieldDisplayMode !== 'pressure' ? (
                <div className="field-force-vector-key" aria-label="Local vector directions at the conductor">
                  <span><small>FIELD</small><b>B: N → S (+X)</b></span>
                  <span><small>CURRENT</small><b>I: {currentSymbol(shownRun.currentA)} {currentAxisLabel(shownRun.currentA)}</b></span>
                  <span className="is-force"><small>RESULT</small><b>F: {forceAxisLabel(shownRun.forceYN)}</b></span>
                </div>
              ) : null}
              {fieldSourceMode === 'wire' && shownWireField ? (
                <div className="field-force-wire-strength-key" aria-label={`Wire field strength at ${signed(shownRun.currentA, 0)} amperes`}>
                  <span>WIRE FIELD STRENGTH</span>
                  <strong>|I| {Math.abs(shownRun.currentA).toFixed(0)} A · {shownWireField.contour_levels.length} ring{shownWireField.contour_levels.length === 1 ? '' : 's'}</strong>
                  <small>Fixed contour spacing: more rings = stronger field · peak {formatMilliTesla(shownWireField.metrics?.peak_b_t ?? 0)} mT</small>
                </div>
              ) : null}
              {showMagnetPathGuide ? (
                <div className="field-force-magnet-path-key" aria-label="How the permanent-magnet field closes its loop">
                  <span>EVERY MAGNET HAS BOTH POLE FACES</span>
                  <strong>Gap: left magnet N → right magnet S</strong>
                  <small>Inside each magnet: S → N · outer air and leakage close the loop</small>
                </div>
              ) : null}
              <MeshViewer
                meshData={sourceField ?? shownRun.data}
                embedded
                compactEmbedded
                toolbarMode="zoom-only"
                toolbarLabel={fieldDisplayMode === 'pressure'
                  ? 'Magnetic field pressure'
                  : `${fieldSourceMode === 'wire'
                    ? 'Wire-only'
                    : fieldSourceMode === 'magnet'
                      ? 'Magnet-only'
                      : 'Combined field'}${
                    showFluxLayer && showDensityLayer
                      ? ' |B| map + flux lines'
                      : showFluxLayer
                        ? ' flux lines'
                        : showDensityLayer
                          ? ' |B| map'
                          : ' geometry'
                  }`}
                splitForceMagnetPolarity
                showMeshEdges={showMesh}
                showFieldIntensity={showDensityLayer}
                fieldIntensityRange={fieldIntensityRange}
                smoothFieldIntensity
                fieldLinesVisible={showFluxLayer}
                animateFieldArrows={showFluxLayer}
                viewportPanEnabled={false}
                pointLabels={[
                  ...poleFaceLabels,
                  ...(fieldDisplayMode === 'pressure' ? [] : [{ xMm: 0, yMm: 0, label: fieldSourceMode === 'magnet' ? 'I=0' : currentSymbol(shownRun.currentA), tone: 'neutral' } as MeshViewerPointLabel]),
                ]}
                directionVectors={magnetPathVectors}
                forceVectors={fieldSourceMode === 'combined' && fieldDisplayMode !== 'pressure' ? forceVectors : []}
              />
              {fieldSourceMode === 'combined' && fieldDisplayMode === 'pressure' ? (
                <FieldPressureOverlay currentA={shownRun.currentA} forceYN={shownRun.forceYN} />
              ) : null}
              {fieldSourceMode === 'wire' && !shownWireField ? (
                <div className={`field-force-wire-load${wireFieldError ? ' is-error' : ''}`} role="status">
                  <strong>{wireFieldError ? 'Wire-only solve failed' : 'Solving the conductor field…'}</strong>
                  <span>{wireFieldError ?? 'Permanent-magnet sources are disabled; Gmsh and Magneto2D are solving the same geometry.'}</span>
                  {wireFieldError ? <button type="button" onClick={() => void loadWireField(shownRun.currentA, shownRun.poleGapMm)}>Retry</button> : null}
                </div>
              ) : null}
              {fieldSourceMode === 'magnet' && !shownMagnetField ? (
                <div className={`field-force-wire-load${magnetFieldError ? ' is-error' : ''}`} role="status">
                  <strong>{magnetFieldError ? 'Magnet-only solve failed' : 'Solving the permanent-magnet field…'}</strong>
                  <span>{magnetFieldError ?? 'The conductor current is set to zero; Gmsh and Magneto2D are solving the same pole geometry.'}</span>
                  {magnetFieldError ? <button type="button" onClick={() => void loadMagnetField(shownRun.poleGapMm)}>Retry</button> : null}
                </div>
              ) : null}
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="field-force-viewer field-force-empty-viewer">
            <div className="mesh-viewer-header field-force-visual-header">
              <div className="mesh-viewer-title">
                <h3>{requestedRunPending ? 'Previewing a new setup' : 'Wire between magnetic poles'}</h3>
                <span>{signed(currentA, 0)} A · {poleGapMm.toFixed(1)} mm each side · {requestedRunPending ? 'FEM pending' : 'ready for FEM'}</span>
              </div>
            </div>
            <section className="field-force-empty-stage">
              <FieldForcePredictionDiagram currentA={currentA} poleGapMm={poleGapMm} setupPreview />
              <div>
                <h2>{requestedRunPending ? 'The setup moved with you.' : 'Start at +8 A.'}</h2>
                <p>{requestedRunPending ? 'Solve once to replace this geometry preview with the new FEM field and force.' : 'Magneto2D solves B, then integrates J × B over the conductor’s 10 mm depth.'}</p>
              </div>
            </section>
          </div>
        )}

        {lessonStage === 'solve' && !quizOpen ? (
          <div className="field-force-lesson-dock" aria-label="Force experiment controls">
            <div className="field-force-dock-insight"><span>{activeProgressStepId}</span><strong>{labInsight}</strong></div>
            <div className="field-force-dock-actions">
              <button type="button" className="field-force-dock-button" aria-expanded={labControlsOpen} onClick={() => { setLabControlsOpen((open) => !open); setSolveInspectorOpen(false); }}>{labControlsOpen ? 'Done' : motorEffectOpen ? 'Adjust loop' : forceAngleOpen ? 'Adjust angle' : 'Adjust experiment'}</button>
              <button type="button" className="field-force-dock-button" aria-expanded={solveInspectorOpen} onClick={() => { setSolveInspectorOpen((open) => !open); setLabControlsOpen(false); }}>Inspect results</button>
              {!forceAngleOpen && !motorEffectOpen && requestedRunPending ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" disabled={busy} onClick={() => void solveCurrent(currentA, poleGapMm)}>
                  {busy ? 'Solving…' : `Solve ${signed(currentA, 0)} A · ${poleGapMm.toFixed(1)} mm`}
                </button>
              ) : !forceAngleOpen && !motorEffectOpen && !comparisonReady ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" disabled={busy} onClick={() => void solveCurrent(currentRun ? guidedCurrent : currentA, positiveRunAny?.poleGapMm ?? poleGapMm)}>
                  {busy ? 'Solving…' : `Solve ${signed(currentRun ? guidedCurrent : currentA, 0)} A · ${(positiveRunAny?.poleGapMm ?? poleGapMm).toFixed(1)} mm`}
                </button>
              ) : !forceAngleOpen && !motorEffectOpen ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" onClick={openAngleLab}>Continue: Change θ</button>
              ) : forceAngleOpen && !forceAngleSweepComplete ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" disabled={forceAngleSolveBusy} onClick={() => void solveForceAngles([...FORCE_ANGLE_SWEEP_DEGREES])}>
                  {forceAngleSolveBusy ? `Solving ${forceAngleSolveProgress.complete}/${forceAngleSolveProgress.total}…` : 'Run angle sweep'}
                </button>
              ) : forceAngleOpen && !angleEvidenceReviewed ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" onClick={() => { setLabControlsOpen(false); setSolveInspectorOpen(true); }}>Review angle evidence</button>
              ) : forceAngleOpen ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" onClick={openMotorLab}>Continue: Motor effect</button>
              ) : motorEffectOpen && !motorEffectReviewed ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" disabled={motorSolvePending || Boolean(motorSolveError)} onClick={runMotorTorqueSweep}>{motorSolvePending ? 'Solving FEM reference…' : 'Run motor sweep'}</button>
              ) : motorEffectOpen && !motorEvidenceReviewed ? (
                <button type="button" className="learning-primary-button field-force-dock-primary" onClick={() => { setLabControlsOpen(false); setSolveInspectorOpen(true); }}>Review torque evidence</button>
              ) : (
                <button type="button" className="learning-primary-button field-force-dock-primary" onClick={continueToCheck}>Continue to Check</button>
              )}
            </div>
          </div>
        ) : quizOpen && !quizPassed && !isLessonComplete('field-force') ? (
          <div className="field-force-lesson-dock field-force-quiz-dock" aria-label="Knowledge check controls">
            <div className="field-force-dock-insight"><span>Check</span><strong>Answer all questions to complete Lesson 5.</strong></div>
            <div className="field-force-dock-actions"><button type="button" className="field-force-dock-button" onClick={() => { setQuizOpen(false); setSolveInspectorOpen(true); }}>Review experiment</button><button type="button" className="field-force-dock-button" onClick={onBackToCatalog}>Lessons</button></div>
          </div>
        ) : null}
      </section>

      {lessonStage === 'solve' && !quizOpen && solveInspectorOpen ? (
      <aside ref={solveInspectorRef} className={`learning-context-panel field-force-context${!motorEffectOpen && !forceAngleOpen ? ' is-force-evidence' : ''}`} aria-label="Lesson evidence and solved results">
        <button type="button" className="field-force-drawer-close" onClick={() => setSolveInspectorOpen(false)} aria-label="Close solved results">×</button>
        <header className="field-force-status-header is-chart-first">
          <p className="learning-kicker">Lesson 5 · Evidence</p>
          <h1>{motorEffectOpen ? 'Motor torque' : forceAngleOpen ? 'Force vs angle' : 'Force vs current'}</h1>
          <div className="learning-progress" aria-label="Lesson completion">
            <span style={{ width: `${(completedStepCount / lessonProgressSteps.length) * 100}%` }} />
          </div>
        </header>

        {forceAngleOpen && angleReferenceRun ? (
          <section
            className="field-force-results field-force-angle-results"
            aria-label="Current-to-field angle FEM force sweep"
            aria-busy={forceAngleSolveBusy}
          >
            <header>
              <div>
                <p className="learning-kicker">Full phase · signed FEM checkpoints</p>
                <h2>Force rises, reverses, and returns to zero.</h2>
              </div>
              <span>θ {forceAngleDeg}°</span>
            </header>
            <ForceAnglePlot
              activeAngleDeg={forceAngleDeg}
              runs={forceAngleRunsAtReference}
              forceAt90N={angleReferenceRun.forceYN}
              bilForceAt90N={angleReferenceRun.forceBilN}
              onSelect={selectForceAngle}
            />
            <section className="field-force-readout">
              <div><span>Solved checkpoints</span><strong>{forceAngleSweepSolvedCount} / {FORCE_ANGLE_SWEEP_DEGREES.length}</strong></div>
              <div><span>2D solver current I<sub>⊥</sub></span><strong>{signed(forceAngleEffectiveCurrentA, 2)} A</strong></div>
              <div><span>{activeForceAngleRun ? 'FEM wire force' : 'Projected preview'}</span><strong>{signed(forceAngleFEMN * 1e3)} mN</strong></div>
              <div><span>BIL sin θ</span><strong>{signed(forceAngleBilN * 1e3)} mN</strong></div>
            </section>
            <p className="field-force-angle-insight">
              The solid cyan curve uses the 90° FEM force as its amplitude and evaluates F(θ) = F<sub>90</sub> sin θ through 360°. Thirteen signed Magneto2D checkpoints validate both halves of the cycle; the dashed amber curve is the independent BIL estimate.
            </p>
          </section>
        ) : motorEffectOpen && motorReferenceRun ? (
          <section className="field-force-results motor-effect-results" aria-label="Motor effect force and torque result" aria-busy={motorSolvePending}>
            <header>
              <div>
                <p className="learning-kicker">Motor effect · live FEM side solve</p>
                <h2>Turn the loop through the field.</h2>
              </div>
              <span>{activeMotorSolve ? `τ ${motorTorqueDirection}` : 'FEM…'}</span>
            </header>
            <div className={`motor-effect-context-solve${motorSolveError ? ' is-error' : motorSolvePending ? ' is-solving' : ''}`}>
              <span>{motorSolveError ? 'SOLVE FAILED' : motorSolvePending ? 'MESH + SOLVE IN PROGRESS' : `MAGNETO2D FEM #${motorSolveCount}`}</span>
              <strong>
                {motorSolveError
                  ? motorSolveError
                  : motorSolvePending
                    ? `${signed(motorLoopCurrentA, 0)} A · δ ${motorLoopAngleDeg}°`
                    : `${activeMotorSolve?.generation_time_ms.toFixed(0) ?? 0} ms · θ(I,B) = ${activeMotorSolve?.fem_reference_angle_deg ?? 90}°`}
              </strong>
            </div>
            <section className="motor-effect-equation-flow">
              <div><small>EACH ACTIVE SIDE · FRESH 2D FEM</small><strong>∫ J × B dV</strong><span>{activeMotorSolve ? `${(motorSideForceN * 1e3).toFixed(1)} mN` : 'awaiting solve'}</span></div>
              <b>×</b>
              <div><small>PROJECTED LEVER ARM · δ = {motorLoopAngleDeg}°</small><strong>2r sin δ</strong><span>{(24 * Math.sin((motorLoopAngleDeg * Math.PI) / 180)).toFixed(1)} mm</span></div>
              <b>=</b>
              <div className="is-result"><small>SIGNED LOOP TORQUE · F FROM FEM</small><strong>τ = 2rF sin δ</strong><span>{activeMotorSolve ? `${signed(motorTorqueNm * 1e3, 2)} mN·m` : 'awaiting solve'}</span></div>
            </section>
            <section className="motor-effect-force-pair">
              <div>
                <span>AB · left active side</span>
                <strong>{motorLoopCurrentA >= 0 ? '⊙ up (+Y)' : '⊗ down (−Y)'}</strong>
                <small>{activeMotorSolve ? `${(motorSideForceN * 1e3).toFixed(1)} mN` : 'FEM pending'}</small>
              </div>
              <div>
                <span>CD · right active side</span>
                <strong>{motorLoopCurrentA >= 0 ? '⊗ down (−Y)' : '⊙ up (+Y)'}</strong>
                <small>{activeMotorSolve ? `${(motorSideForceN * 1e3).toFixed(1)} mN` : 'FEM pending'}</small>
              </div>
            </section>
            <div className="motor-effect-balance">
              <span><b>Net force ≈ 0</b> · equal + opposite</span>
              <span><b>Torque follows sin δ</b> · projected lever arms</span>
            </div>
            {activeMotorSolve ? (
              <MotorTorqueAnglePlot
                sampledAnglesDeg={motorTorqueAnglesDeg}
                activeAngleDeg={motorLoopAngleDeg}
                torqueMaxNm={motorTorqueMaxNm}
                currentA={motorLoopCurrentA}
                onSelect={selectMotorLoopAngle}
              />
            ) : null}
            <p className="motor-effect-insight">
              Magneto2D solves the active-side force once. The full-cycle sweep projects that FEM force through the rotating lever arm, so torque is zero at alignment, peaks a quarter-turn away, and reverses over the second half-cycle.
            </p>
          </section>
        ) : runs.length ? (
          <section className="field-force-results is-chart-first" aria-label="Solved force comparison">
            <header>
              <div>
                <p className="learning-kicker">{shownRun?.poleGapMm.toFixed(1) ?? poleGapMm.toFixed(1)} mm each side</p>
                <h2>Current sets direction and strength.</h2>
              </div>
              <span>{runsAtGap.length} run{runsAtGap.length === 1 ? '' : 's'}</span>
            </header>
            <ForcePlot runs={runsAtGap} activeCurrentA={currentRun?.currentA ?? shownRun?.currentA ?? null} onSelect={selectSolvedCurrent} />
            {shownRun ? (
              <>
                <details className="field-force-evidence-details">
                  <summary>Why this result?</summary>
                  <section className="field-force-readout">
                    <div><span>Mean B<sub>x</sub> in wire</span><strong>{shownRun.meanBxT.toFixed(3)} T</strong></div>
                    <div><span>Vertical force</span><strong>{signed(shownRun.forceYN * 1e3)} mN</strong></div>
                    <div><span>Residual horizontal force</span><strong>{Math.abs(shownRun.forceXN * 1e3).toFixed(3)} mN</strong></div>
                  </section>
                  <ForceDirectionGuide currentA={shownRun.currentA} forceYN={shownRun.forceYN} />
                  <section className="field-force-equation-card">
                    <header><span>UNIFORM-FIELD CHECK</span><strong>L = 10 mm · θ = 90°</strong></header>
                    <div className="field-force-equation"><span>F</span><b>=</b><span>B I L sin θ</span></div>
                  </section>
                  {sameCurrentGapRuns.length > 1 ? (
                    <section className="field-force-gap-history">
                      <header><span>SAME CURRENT · DISTANCE</span><strong>{signed(shownRun.currentA, 0)} A</strong></header>
                      <div>
                        {sameCurrentGapRuns.map((run) => (
                          <button
                            key={forceRunKey(run.currentA, run.poleGapMm)}
                            type="button"
                            className={forceRunKey(run.currentA, run.poleGapMm) === forceRunKey(shownRun.currentA, shownRun.poleGapMm) ? 'is-active' : ''}
                            onClick={() => selectSolvedRun(run)}
                          >
                            <span>{run.poleGapMm.toFixed(1)} mm</span>
                            <strong>{Math.abs(run.forceYN * 1e3).toFixed(1)} mN</strong>
                          </button>
                        ))}
                      </div>
                    </section>
                  ) : null}
                </details>
              </>
            ) : null}
          </section>
        ) : (
          <section className="field-force-status-empty">
            <p className="learning-kicker">Solved forces</p>
            <h2>Awaiting the +8 A frame</h2>
            <p>The force sweep and numerical readout will appear here without covering the field view.</p>
            <ol>
              <li><span>1</span> Solve +8 A</li>
              <li><span>2</span> Reverse to −8 A</li>
              <li><span>3</span> Double to +16 A</li>
            </ol>
          </section>
        )}

        {quizOpen ? (
          <section className="field-force-takeaway">
            <p className="learning-kicker">Takeaway</p>
            <h2>Force needs both current and field.</h2>
            <p>The solver uses the local field everywhere in the wire. BIL is the compact uniform-field model.</p>
          </section>
        ) : null}

        <section className="field-force-inspector-next" aria-label="Continue after reviewing the force evidence">
          {motorEffectOpen ? (
            <>
              <span>{motorEffectSolved ? 'Torque evidence reviewed?' : 'Run the full motor sweep first.'}</span>
              <button type="button" disabled={!motorEffectSolved} onClick={continueToCheck}>Continue to Check →</button>
            </>
          ) : forceAngleOpen ? (
            <>
              <span>{forceAngleSweepComplete ? 'Angle evidence reviewed?' : 'Complete the FEM angle sweep first.'}</span>
              <button type="button" disabled={!forceAngleSweepComplete} onClick={openMotorLab}>Continue: Motor effect →</button>
            </>
          ) : comparisonReady ? (
            <>
              <span>Current evidence reviewed?</span>
              <button type="button" onClick={openAngleLab}>Continue: Change θ →</button>
            </>
          ) : (
            <>
              <span>Plot reviewed?</span>
              <button type="button" onClick={() => { setSolveInspectorOpen(false); setLabControlsOpen(true); }}>Adjust next current →</button>
            </>
          )}
        </section>
      </aside>
      ) : null}
    </main>
  );
};
