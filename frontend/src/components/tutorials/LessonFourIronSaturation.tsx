import React from 'react';
import type {
  IronSaturationFieldData,
  IronSaturationSpmToothFieldData,
  IronSaturationToothFieldData,
  TeachingBhPoint,
} from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { MeshViewer } from './MeshViewer';
import { MotorTooth3D } from './MotorTooth3D';
import { CurrentConductor3D } from './CurrentConductor3D';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
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
} from './lab/LessonLab';
import type { LessonTerm } from './lab/LessonLab';
import './learning.css';
import './iron-saturation.css';

interface LearningLessonFourIronSaturationProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'linear' | 'knee' | 'fall';
type FieldDisplayMode = 'lines' | 'density';
type LessonFourProgressStepId =
  | 'predict'
  | 'low'
  | 'knee'
  | 'saturation'
  | 'tooth'
  | 'spm'
  | 'check';

const LESSON_FOUR_GOALS: Record<LessonFourProgressStepId, { title: string; detail: string }> = {
  predict: {
    title: 'Predict the nonlinear response',
    detail: 'Decide whether flux density can keep rising at the same rate.',
  },
  low: {
    title: 'Establish the low-field response',
    detail: 'Solve 10 A while the steel still has high effective permeability.',
  },
  knee: {
    title: 'Find the B–H knee',
    detail: 'Solve 100 A and watch the B–H curve begin to bend.',
  },
  saturation: {
    title: 'Drive the steel into saturation',
    detail: 'Solve 800 A and compare the extra H with the smaller gain in B.',
  },
  tooth: {
    title: 'Put the solenoid idea inside a motor',
    detail: 'Wrap a coil around one tooth and measure B in the tooth and the airgap flux.',
  },
  spm: {
    title: 'Add the permanent-magnet source',
    detail: 'Place an N42 magnet pole on curved rotor back iron, then compare airgap flux with the coil off and on.',
  },
  check: {
    title: 'Recognize saturation',
    detail: 'Explain the knee, diminishing B gain, and local saturated regions.',
  },
};

interface SaturationRun {
  currentA: number;
  meanBT: number;
  meanHApm: number;
  effectiveMuRel: number;
  saturatedFraction: number;
  data: IronSaturationFieldData;
}

interface ToothRun {
  currentA: number;
  toothMeanBT: number;
  toothTipMeanBT: number;
  toothSaturatedFraction: number;
  airgapMeanBT: number;
  airgapFluxPerDepthWbPerM: number;
  data: IronSaturationToothFieldData;
}

interface SpmToothRun extends Omit<ToothRun, 'data'> {
  data: IronSaturationSpmToothFieldData;
}

const LOW_CURRENT_A = 10;
const KNEE_CURRENT_A = 100;
const HIGH_CURRENT_A = 800;
const TOOTH_LOW_CURRENT_A = 1;
const TOOTH_HIGH_CURRENT_A = 20;
const SPM_BASELINE_CURRENT_A = 0;
const SPM_HIGH_CURRENT_A = 20;
const MU_0 = 4 * Math.PI * 1e-7;
// Flux density above which this lesson calls the steel saturated. The solver's
// "saturated fraction" measurements use the same 1.60 T threshold.
const SATURATION_B_T = 1.6;

const PREDICTION_OPTIONS: ReadonlyArray<{ id: Prediction; label: string; detail: string }> = [
  { id: 'linear', label: 'B keeps scaling linearly', detail: 'A single constant permeability works at every current.' },
  { id: 'knee', label: 'B bends toward a plateau', detail: 'Effective permeability falls after the material knee.' },
  { id: 'fall', label: 'B falls back to zero', detail: 'More H cancels the field in the ring.' },
];

// Every technical word the lesson leans on, defined before it is used.
const LESSON_FOUR_TERMS: readonly LessonTerm[] = [
  { term: 'Field strength, H', definition: 'The magnetising effort that current creates at a point, in amperes per metre (A/m). Around a straight wire, H = I / (2πr).' },
  { term: 'Flux density, B', definition: 'How strong the resulting magnetic field is at one spot, in tesla (T). |B| means its size, whatever its direction.' },
  { term: <>Permeability, μ<sub>r</sub></>, definition: 'How much B a material gives for the same H, compared with empty space. It has no unit. Unsaturated steel is in the thousands; air is 1.' },
  { term: 'B–H curve and knee', definition: 'The graph of B against H for a material. The knee is the bend, near 1.5 T for this steel, where the curve stops climbing steeply.' },
  { term: 'Saturation', definition: 'Past the knee, the steel is nearly “full”: a lot more H gives only a little more B. This lesson counts steel above 1.60 T as saturated.' },
  { term: 'MMF', definition: 'Magnetomotive force: what drives flux round a magnetic path. For a coil it is turns × current (N × I), in ampere-turns (A·turn).' },
  { term: 'Airgap flux', definition: 'The total field crossing the airgap, the thin space between the stator tooth and the rotor, where torque is made. Shown per metre of motor depth, in milliwebers per metre (mWb/m).' },
  { term: 'SPM pole', definition: 'Surface permanent magnet: a magnet fixed to the rotor surface, facing the tooth. N42 is a common strong grade of neodymium magnet.' },
];

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'saturation-meaning',
    prompt: 'What changes most dramatically after the electrical steel passes its B–H knee?',
    options: ['Its effective permeability collapses', 'The current disappears', 'The iron becomes an airgap'],
    correctIndex: 0,
    explanation: 'H can keep rising, but each additional ampere produces much less B because the incremental permeability has fallen.',
  },
  {
    id: 'saturation-current',
    prompt: 'If current doubles deep in saturation, what should you expect from B?',
    options: ['Much less than a 2× increase', 'Exactly a 2× increase', 'B must reverse'],
    correctIndex: 0,
    explanation: 'The linear B = μH shortcut no longer has a constant μ after the knee.',
  },
  {
    id: 'saturation-local',
    prompt: 'Why does the Flux density view show saturation locally instead of labeling the whole part saturated?',
    options: ['B varies from element to element', 'Only the mesh can saturate', 'Electrical steel has no B–H curve'],
    correctIndex: 0,
    explanation: 'Geometry concentrates flux. Each FEM element samples its own B and therefore its own point on the steel’s B–H curve.',
  },
  {
    id: 'saturation-motor',
    prompt: 'Why is a saturated tooth costly in a motor?',
    options: [
      'Copper loss keeps rising roughly with I² while airgap flux gains diminish',
      'The permanent magnets instantly demagnetize',
      'The airgap becomes electrically conductive',
    ],
    correctIndex: 0,
    explanation: 'Torque potential follows airgap flux, but winding heating grows rapidly with current. A saturated tooth therefore buys less torque per added ampere.',
  },
  {
    id: 'saturation-spm',
    prompt: 'Why does the SPM tooth fixture carry airgap flux even at 0 A?',
    options: [
      'The N42 magnet supplies flux before the winding adds MMF',
      'The electrical steel creates permanent flux by itself',
      'The mesh stores current from the previous solve',
    ],
    correctIndex: 0,
    explanation: 'The surface magnet establishes a baseline field. Reinforcing winding current can raise useful flux further, but the same steel tooth still becomes the bottleneck near saturation.',
  },
];

const runFromData = (data: IronSaturationFieldData): SaturationRun => {
  const metrics = data.metrics;
  if (
    !metrics
    || metrics.iron_mean_b_t === null
    || metrics.iron_mean_b_t === undefined
    || metrics.iron_mean_h_a_per_m === null
    || metrics.iron_mean_h_a_per_m === undefined
    || metrics.iron_effective_mu_rel === null
    || metrics.iron_effective_mu_rel === undefined
    || metrics.iron_saturated_fraction === null
    || metrics.iron_saturated_fraction === undefined
  ) {
    throw new Error('The nonlinear solver returned no iron B–H measurements.');
  }
  return {
    currentA: data.current_a,
    meanBT: metrics.iron_mean_b_t,
    meanHApm: metrics.iron_mean_h_a_per_m,
    effectiveMuRel: metrics.iron_effective_mu_rel,
    saturatedFraction: metrics.iron_saturated_fraction,
    data,
  };
};

const toothRunFromData = (data: IronSaturationToothFieldData): ToothRun => {
  const metrics = data.metrics;
  if (
    !metrics
    || metrics.tooth_mean_b_t === null
    || metrics.tooth_mean_b_t === undefined
    || metrics.tooth_tip_mean_b_t === null
    || metrics.tooth_tip_mean_b_t === undefined
    || metrics.tooth_saturated_fraction === null
    || metrics.tooth_saturated_fraction === undefined
    || metrics.airgap_mean_b_t === null
    || metrics.airgap_mean_b_t === undefined
    || metrics.airgap_flux_per_depth_wb_per_m === null
    || metrics.airgap_flux_per_depth_wb_per_m === undefined
  ) {
    throw new Error('The nonlinear tooth solve returned no tooth or airgap measurements.');
  }
  return {
    currentA: data.current_a,
    toothMeanBT: metrics.tooth_mean_b_t,
    toothTipMeanBT: metrics.tooth_tip_mean_b_t,
    toothSaturatedFraction: metrics.tooth_saturated_fraction,
    airgapMeanBT: metrics.airgap_mean_b_t,
    airgapFluxPerDepthWbPerM: metrics.airgap_flux_per_depth_wb_per_m,
    data,
  };
};

const spmToothRunFromData = (data: IronSaturationSpmToothFieldData): SpmToothRun => {
  const base = toothRunFromData(data as unknown as IronSaturationToothFieldData);
  return { ...base, data };
};

const SaturationPredictionDiagram: React.FC = () => (
  <svg className="iron-saturation-prediction" viewBox="0 0 760 500" role="img" aria-label="Current conductor passing through an electrical steel ring">
    <defs>
      <marker id="saturationPredictionArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#67e8f9" />
      </marker>
    </defs>
    <circle cx="380" cy="238" r="156" className="iron-saturation-ring" />
    <circle cx="380" cy="238" r="92" className="iron-saturation-ring-hole" />
    <path d="M380 82 A156 156 0 0 1 536 238" className="iron-saturation-orbit" markerEnd="url(#saturationPredictionArrow)" />
    <circle cx="380" cy="238" r="48" className="iron-saturation-wire" />
    <text x="380" y="250" className="iron-saturation-current-label">⊙</text>
    <text x="380" y="326" className="iron-saturation-current-direction-label">CURRENT OUT OF SCREEN · CIRCULAR H</text>
    <text x="380" y="430" className="iron-saturation-material-label">ELECTRICAL STEEL RING · WHAT HAPPENS AS CURRENT KEEPS RISING?</text>
  </svg>
);

const MotorToothDiagram: React.FC = () => (
  <svg className="iron-tooth-diagram" viewBox="0 0 760 500" role="img" aria-label="Concentrated winding around a motor tooth with a two millimeter airgap and rotor return">
    <defs>
      <marker id="ironToothFluxArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#67e8f9" />
      </marker>
    </defs>
    <path d="M120 92 Q380 52 640 92 L632 174 Q380 136 128 174 Z" className="iron-tooth-stator" />
    <path d="M195 164 L260 154 V360 L238 375 H217 L195 360 Z" className="iron-tooth-stator" />
    <path d="M335 145 Q380 139 425 145 V330 L407 344 H353 L335 330 Z" className="iron-tooth-stator" />
    <path d="M500 154 L565 164 V360 L543 375 H522 L500 360 Z" className="iron-tooth-stator" />
    <path d="M98 406 Q380 366 662 406 L656 462 Q380 422 104 462 Z" className="iron-tooth-rotor" />
    <rect x="267" y="190" width="58" height="118" rx="7" className="iron-tooth-coil" />
    <rect x="435" y="190" width="58" height="118" rx="7" className="iron-tooth-coil" />
    <text x="296" y="258" className="iron-tooth-current-glyph">⊙</text>
    <text x="464" y="258" className="iron-tooth-current-glyph">⊗</text>
    <text x="380" y="135" className="iron-tooth-label">CONTINUOUS STATOR YOKE</text>
    <text x="380" y="225" className="iron-tooth-label">ENERGIZED TOOTH</text>
    <text x="380" y="380" className="iron-tooth-gap-label">2 mm AIRGAP</text>
    <text x="380" y="430" className="iron-tooth-label">ROTOR RETURN</text>
    <path d="M380 170 V354 M380 390 V422 M380 422 H532 V360" className="iron-tooth-flux-path" markerEnd="url(#ironToothFluxArrow)" />
    <path d="M380 422 H228 V360" className="iron-tooth-flux-path" markerEnd="url(#ironToothFluxArrow)" />
  </svg>
);

const SpmToothDiagram: React.FC = () => (
  <svg className="iron-tooth-diagram iron-spm-tooth-diagram" viewBox="0 0 760 500" role="img" aria-label="Wound stator tooth facing an N42 surface magnet on curved rotor back iron">
    <defs>
      <marker id="ironSpmFluxArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#67e8f9" />
      </marker>
    </defs>
    <path d="M120 92 Q380 52 640 92 L632 174 Q380 136 128 174 Z" className="iron-tooth-stator" />
    <path d="M195 164 L260 154 V360 L238 375 H217 L195 360 Z" className="iron-tooth-stator" />
    <path d="M335 145 Q380 139 425 145 V330 L407 344 H353 L335 330 Z" className="iron-tooth-stator" />
    <path d="M500 154 L565 164 V360 L543 375 H522 L500 360 Z" className="iron-tooth-stator" />
    <path d="M98 428 Q380 388 662 428 L656 476 Q380 436 104 476 Z" className="iron-tooth-rotor" />
    <path d="M318 390 Q380 381 442 390 L440 428 Q380 419 320 428 Z" className="iron-spm-magnet" />
    <rect x="267" y="190" width="58" height="118" rx="7" className="iron-tooth-coil" />
    <rect x="435" y="190" width="58" height="118" rx="7" className="iron-tooth-coil" />
    <text x="296" y="258" className="iron-tooth-current-glyph">⊙</text>
    <text x="464" y="258" className="iron-tooth-current-glyph">⊗</text>
    <text x="380" y="135" className="iron-tooth-label">WOUND STEEL STATOR TOOTH</text>
    <text x="380" y="380" className="iron-tooth-gap-label">2 mm AIRGAP</text>
    <text x="380" y="410" className="iron-spm-pole-label">N · N42 SURFACE POLE</text>
    <text x="380" y="458" className="iron-tooth-label">CURVED STEEL ROTOR BACK IRON</text>
    <path d="M380 404 V354 M380 330 V170 M380 170 H532 V360" className="iron-tooth-flux-path" markerEnd="url(#ironSpmFluxArrow)" />
    <path d="M380 170 H228 V360" className="iron-tooth-flux-path" markerEnd="url(#ironSpmFluxArrow)" />
  </svg>
);

interface BhPlotProps {
  runs: SaturationRun[];
  curve: TeachingBhPoint[];
  activeCurrentA: number | null;
  onSelect: (currentA: number) => void;
}

const BhPlot: React.FC<BhPlotProps> = ({ runs, curve, activeCurrentA, onSelect }) => {
  // Sized for the Inspect card (about 280 px wide) so the axis text stays readable.
  const width = 310;
  const height = 250;
  const margin = { top: 24, right: 16, bottom: 50, left: 50 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const displayedCurve = curve.filter((point) => point.h_a_per_m <= 18_000 && point.b_t <= 1.92);
  const xMax = 18;
  const yMax = 2.0;
  const xTicks = [0, 6, 12, 18];
  const yTicks = [0, 0.5, 1.0, 1.5, 2.0];
  const xFor = (hApm: number) => margin.left + Math.min(hApm / 1000 / xMax, 1) * plotWidth;
  const yFor = (bT: number) => margin.top + plotHeight - Math.min(bT / yMax, 1) * plotHeight;
  const curvePoints = displayedCurve.map((point) => `${xFor(point.h_a_per_m)},${yFor(point.b_t)}`).join(' ');
  const initialPoint = curve.find((point) => point.b_t >= 0.05 && point.h_a_per_m > 0);
  const initialMuRel = initialPoint ? initialPoint.b_t / (MU_0 * initialPoint.h_a_per_m) : 2_500;
  const linearEndH = yMax / (MU_0 * initialMuRel);
  const sortedRuns = [...runs].sort((left, right) => left.meanHApm - right.meanHApm);
  const runPoints = sortedRuns.map((run) => `${xFor(run.meanHApm)},${yFor(run.meanBT)}`).join(' ');

  return (
    <div className="iron-saturation-plot-wrap">
      <div className="iron-saturation-plot-legend">
        <span className="is-curve">Steel B–H curve</span>
        <span className="is-linear">If μ stayed constant</span>
        <span className="is-fem">Your solved points</span>
      </div>
      <svg className="iron-saturation-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Flux density B of the steel versus field strength H">
        <g className="iron-saturation-plot-grid">
          {xTicks.map((tick) => <line key={`x-${tick}`} x1={xFor(tick * 1000)} y1={margin.top} x2={xFor(tick * 1000)} y2={height - margin.bottom} />)}
          {yTicks.map((tick) => <line key={`y-${tick}`} x1={margin.left} y1={yFor(tick)} x2={width - margin.right} y2={yFor(tick)} />)}
        </g>
        <g className="iron-saturation-plot-axes">
          <line x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
          <line x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
        </g>
        <g className="iron-saturation-plot-ticks">
          {xTicks.map((tick) => <text key={`xt-${tick}`} x={xFor(tick * 1000)} y={height - margin.bottom + 21} textAnchor="middle">{tick}</text>)}
          {yTicks.map((tick) => <text key={`yt-${tick}`} x={margin.left - 12} y={yFor(tick) + 4} textAnchor="end">{tick.toFixed(1)}</text>)}
        </g>
        <text className="iron-saturation-axis-title" x={14} y={margin.top + plotHeight / 2} transform={`rotate(-90 14 ${margin.top + plotHeight / 2})`} textAnchor="middle">Flux density B (T)</text>
        <text className="iron-saturation-axis-title" x={margin.left + plotWidth / 2} y={height - 8} textAnchor="middle">Field strength H (kA/m)</text>
        <polyline className="iron-saturation-material-curve" points={curvePoints} />
        <line className="iron-saturation-linear-line" x1={xFor(0)} y1={yFor(0)} x2={xFor(linearEndH)} y2={yFor(yMax)} />
        {sortedRuns.length > 1 ? <polyline className="iron-saturation-fem-line" points={runPoints} /> : null}
        <g className="iron-saturation-points">
          {sortedRuns.map((run) => {
            const active = activeCurrentA !== null && Math.abs(run.currentA - activeCurrentA) < 0.1;
            const x = xFor(run.meanHApm);
            const y = yFor(run.meanBT);
            return (
              <g
                key={run.currentA}
                className={active ? 'is-active' : ''}
                role="button"
                tabIndex={0}
                aria-label={`${run.currentA} amperes, ${run.meanBT.toFixed(2)} tesla`}
                onClick={() => onSelect(run.currentA)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelect(run.currentA);
                }}
              >
                <circle className="iron-saturation-point-hit" cx={x} cy={y} r="18" />
                <circle className="iron-saturation-point-dot" cx={x} cy={y} r={active ? 7 : 5} />
                <text x={x + 10} y={y - 10}>{run.meanBT.toFixed(2)} T</text>
              </g>
            );
          })}
        </g>
        <g className="iron-saturation-knee-callout">
          <circle cx={xFor(1_100)} cy={yFor(1.5)} r="18" />
          <text x={xFor(1_100) + 25} y={yFor(1.5) - 3}>THE KNEE</text>
        </g>
      </svg>
    </div>
  );
};

export const LearningLessonFourIronSaturation: React.FC<LearningLessonFourIronSaturationProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const inspectorRef = React.useRef<HTMLElement | null>(null);
  const inspectorFlashTimer = React.useRef<number | null>(null);
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = React.useState<Prediction | null>(null);
  const [currentA, setCurrentA] = React.useState(LOW_CURRENT_A);
  const [runs, setRuns] = React.useState<SaturationRun[]>([]);
  const [toothPhaseOpen, setToothPhaseOpen] = React.useState(false);
  const [toothCurrentA, setToothCurrentA] = React.useState(TOOTH_LOW_CURRENT_A);
  const [toothRuns, setToothRuns] = React.useState<ToothRun[]>([]);
  const [spmPhaseOpen, setSpmPhaseOpen] = React.useState(false);
  const [spmCurrentA, setSpmCurrentA] = React.useState(SPM_BASELINE_CURRENT_A);
  const [spmRuns, setSpmRuns] = React.useState<SpmToothRun[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  // Saturation is read off the flux-density colours, so that is the default drawing.
  const [fieldDisplayMode, setFieldDisplayMode] = React.useState<FieldDisplayMode>('density');
  const [showMesh, setShowMesh] = React.useState(false);
  // The ring and the tooth each have their own 3D model, so each remembers its own view.
  const [showTooth3D, setShowTooth3D] = React.useState(false);
  const [showRing3D, setShowRing3D] = React.useState(false);
  const [inspectorFlash, setInspectorFlash] = React.useState(false);
  // The mesh viewer draws its zoom buttons into this element in the dock.
  const [zoomSlot, setZoomSlot] = React.useState<HTMLSpanElement | null>(null);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();
  const lessonComplete = isLessonComplete('iron-saturation');

  const predictionCorrect = prediction === 'knee';
  const lowRun = runs.find((run) => run.currentA <= 20) ?? null;
  const kneeRun = runs.find((run) => run.currentA >= 80 && run.currentA <= 160) ?? null;
  const highRun = runs.find((run) => run.currentA >= 600) ?? null;
  const comparisonReady = Boolean(lowRun && kneeRun && highRun);
  const toothLowRun = toothRuns.find((run) => run.currentA <= 2) ?? null;
  const toothHighRun = toothRuns.find((run) => Math.abs(run.currentA - TOOTH_HIGH_CURRENT_A) < 0.1) ?? null;
  const toothComparisonReady = Boolean(toothLowRun && toothHighRun);
  const spmBaselineRun = spmRuns.find((run) => run.currentA <= 0.1) ?? null;
  const spmHighRun = spmRuns.find((run) => Math.abs(run.currentA - SPM_HIGH_CURRENT_A) < 0.1) ?? null;
  const spmComparisonReady = Boolean(spmBaselineRun && spmHighRun);
  const currentRun = runs.find((run) => Math.abs(run.currentA - currentA) < 0.1) ?? null;
  const shownRun = currentRun ?? runs[0] ?? null;
  const toothCurrentRun = toothRuns.find((run) => Math.abs(run.currentA - toothCurrentA) < 0.1) ?? null;
  const shownToothRun = toothCurrentRun ?? toothRuns[0] ?? null;
  const spmCurrentRun = spmRuns.find((run) => Math.abs(run.currentA - spmCurrentA) < 0.1) ?? null;
  const shownSpmRun = spmCurrentRun ?? spmRuns[0] ?? null;
  const toothCurrentMultiplier = toothLowRun && toothHighRun
    ? toothHighRun.currentA / toothLowRun.currentA
    : null;
  const toothFluxMultiplier = toothLowRun && toothHighRun
    ? toothHighRun.airgapFluxPerDepthWbPerM / toothLowRun.airgapFluxPerDepthWbPerM
    : null;
  const spmFluxGainPct = spmBaselineRun && spmHighRun
    ? (spmHighRun.airgapFluxPerDepthWbPerM / spmBaselineRun.airgapFluxPerDepthWbPerM - 1) * 100
    : null;
  const curve = runs.find((run) => run.data.bh_curve?.length)?.data.bh_curve ?? [];
  const activeProgressStepId: LessonFourProgressStepId = quizOpen
    ? 'check'
    : lessonStage === 'design'
      ? 'predict'
      : spmPhaseOpen
        ? 'spm'
        : toothPhaseOpen
          ? 'tooth'
          : !lowRun
            ? 'low'
            : !kneeRun
              ? 'knee'
              : 'saturation';

  const selectProgressStep = React.useCallback((stepId: string) => {
    const next = stepId as LessonFourProgressStepId;
    if (next === 'predict') {
      setQuizOpen(false);
      setToothPhaseOpen(false);
      setSpmPhaseOpen(false);
      onStageChange?.('design');
    } else if (next === 'low' && predictionCorrect) {
      setQuizOpen(false);
      setToothPhaseOpen(false);
      setSpmPhaseOpen(false);
      onStageChange?.('solve');
      setCurrentA(LOW_CURRENT_A);
    } else if (next === 'knee' && lowRun) {
      setQuizOpen(false);
      setToothPhaseOpen(false);
      setSpmPhaseOpen(false);
      onStageChange?.('solve');
      setCurrentA(KNEE_CURRENT_A);
    } else if (next === 'saturation' && kneeRun) {
      setQuizOpen(false);
      setToothPhaseOpen(false);
      setSpmPhaseOpen(false);
      onStageChange?.('solve');
      setCurrentA(HIGH_CURRENT_A);
    } else if (next === 'tooth' && comparisonReady) {
      setQuizOpen(false);
      setToothPhaseOpen(true);
      setSpmPhaseOpen(false);
      onStageChange?.('solve');
    } else if (next === 'spm' && toothComparisonReady) {
      setQuizOpen(false);
      setToothPhaseOpen(false);
      setSpmPhaseOpen(true);
      onStageChange?.('solve');
    } else if (next === 'check' && spmComparisonReady) {
      onStageChange?.('solve');
      setQuizOpen(true);
    }
  }, [
    comparisonReady,
    kneeRun,
    lowRun,
    onStageChange,
    predictionCorrect,
    spmComparisonReady,
    toothComparisonReady,
  ]);

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'low', label: 'Low field', complete: Boolean(lowRun), available: predictionCorrect },
    { id: 'knee', label: 'Knee', complete: Boolean(kneeRun), available: Boolean(lowRun) },
    { id: 'saturation', label: 'Saturation', complete: comparisonReady, available: Boolean(kneeRun) },
    { id: 'tooth', label: 'Motor tooth', complete: toothComparisonReady, available: comparisonReady },
    { id: 'spm', label: 'SPM pole', complete: spmComparisonReady, available: toothComparisonReady },
    { id: 'check', label: 'Check', complete: quizPassed, available: spmComparisonReady },
  ], [
    comparisonReady,
    kneeRun,
    lowRun,
    predictionCorrect,
    quizPassed,
    spmComparisonReady,
    toothComparisonReady,
  ]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 4,
    lessonCount: 10,
    title: 'When Iron Saturates',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const currentGoal = LESSON_FOUR_GOALS[activeProgressStepId];

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('iron-saturation', true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  React.useEffect(() => () => {
    if (inspectorFlashTimer.current !== null) window.clearTimeout(inspectorFlashTimer.current);
  }, []);

  // New measurements land in the Inspect panel, which is already on screen:
  // ring it briefly so the student looks there after a solve.
  const flashInspector = () => {
    inspectorRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    setInspectorFlash(true);
    if (inspectorFlashTimer.current !== null) window.clearTimeout(inspectorFlashTimer.current);
    inspectorFlashTimer.current = window.setTimeout(() => setInspectorFlash(false), 1_600);
  };

  const openLab = () => {
    setQuizOpen(false);
    onStageChange?.('solve');
  };

  const guidedCurrent = !lowRun ? LOW_CURRENT_A : !kneeRun ? KNEE_CURRENT_A : !highRun ? HIGH_CURRENT_A : currentA;

  const solveCurrent = async (requestedCurrentA = currentA) => {
    setBusy(true);
    setError(null);
    try {
      const run = runFromData(await solveClient.fetchIronSaturationSolve(requestedCurrentA));
      setCurrentA(requestedCurrentA);
      setRuns((previous) => [run, ...previous.filter((item) => Math.abs(item.currentA - requestedCurrentA) >= 0.1)].slice(0, 8));
      flashInspector();
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The nonlinear iron solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const solveToothCurrent = async (requestedCurrentA = toothCurrentA) => {
    setBusy(true);
    setError(null);
    try {
      const run = toothRunFromData(await solveClient.fetchIronSaturationToothSolve(requestedCurrentA));
      setToothCurrentA(requestedCurrentA);
      setToothRuns((previous) => [
        run,
        ...previous.filter((item) => Math.abs(item.currentA - requestedCurrentA) >= 0.1),
      ].slice(0, 6));
      flashInspector();
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The nonlinear tooth solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const solveSpmCurrent = async (requestedCurrentA = spmCurrentA) => {
    setBusy(true);
    setError(null);
    try {
      const run = spmToothRunFromData(
        await solveClient.fetchIronSaturationSpmToothSolve(requestedCurrentA),
      );
      setSpmCurrentA(requestedCurrentA);
      setSpmRuns((previous) => [
        run,
        ...previous.filter((item) => Math.abs(item.currentA - requestedCurrentA) >= 0.1),
      ].slice(0, 6));
      flashInspector();
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The nonlinear SPM tooth solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const advanceLab = () => {
    if (spmPhaseOpen && spmComparisonReady) {
      setQuizOpen(true);
    } else if (toothPhaseOpen && toothComparisonReady) {
      setToothPhaseOpen(false);
      setSpmPhaseOpen(true);
      setSpmCurrentA(SPM_BASELINE_CURRENT_A);
    } else if (!toothPhaseOpen && !spmPhaseOpen && comparisonReady) {
      setToothPhaseOpen(true);
      setSpmPhaseOpen(false);
      setToothCurrentA(TOOTH_LOW_CURRENT_A);
    }
  };

  // The one button at the foot of the left card. While a phase still needs its
  // guided solves it runs the next one; once they are done it moves the lesson on.
  // Extra points after that are plotted with the button inside the control card.
  const labPrimary: { label: string; onClick: () => void } = (() => {
    if (spmPhaseOpen) {
      if (spmComparisonReady) return { label: 'Continue to Check', onClick: advanceLab };
      const recommendedA = spmBaselineRun ? SPM_HIGH_CURRENT_A : SPM_BASELINE_CURRENT_A;
      return {
        label: busy
          ? 'Meshing N42 pole + nonlinear tooth…'
          : spmCurrentRun
            ? `Solve recommended ${recommendedA} A`
            : spmCurrentA === 0
              ? 'Solve magnet-only baseline'
              : `Solve SPM tooth at ${spmCurrentA.toFixed(0)} A`,
        onClick: () => void solveSpmCurrent(spmCurrentRun ? recommendedA : spmCurrentA),
      };
    }
    if (toothPhaseOpen) {
      if (toothComparisonReady) return { label: 'Continue: Add SPM pole', onClick: advanceLab };
      const recommendedA = toothLowRun ? TOOTH_HIGH_CURRENT_A : TOOTH_LOW_CURRENT_A;
      return {
        label: busy
          ? 'Meshing + nonlinear tooth solve…'
          : toothCurrentRun
            ? `Solve recommended ${recommendedA} A`
            : `Solve tooth at ${toothCurrentA.toFixed(0)} A`,
        onClick: () => void solveToothCurrent(toothCurrentRun ? recommendedA : toothCurrentA),
      };
    }
    if (comparisonReady) return { label: 'Continue: Motor tooth', onClick: advanceLab };
    return {
      label: busy
        ? 'Meshing + nonlinear solve…'
        : currentRun
          ? `Solve recommended ${guidedCurrent} A`
          : `Solve ${currentA.toFixed(0)} A`,
      onClick: () => void solveCurrent(currentRun ? guidedCurrent : currentA),
    };
  })();

  const labInsight = spmPhaseOpen
    ? spmComparisonReady
      ? 'The magnet sets the baseline; coil current pushes the shared tooth toward saturation.'
      : 'Compare magnet-only flux with the reinforced 20 A operating point.'
    : toothPhaseOpen
      ? toothComparisonReady
        ? 'The tooth turns added current into diminishing airgap-flux gains.'
        : 'Compare the efficient 1 A tooth with the saturated 20 A tooth.'
      : comparisonReady
        ? 'The B–H curve bends. Now put that material limit inside a motor tooth.'
        : !lowRun
          ? 'Start below the knee and establish the efficient low-field response.'
          : !kneeRun
            ? 'Move to the knee and watch effective permeability begin to fall.'
            : 'Drive the ring into saturation and compare extra H with the smaller B gain.';

  const motorPhase = toothPhaseOpen || spmPhaseOpen;
  const show3D = motorPhase ? showTooth3D : showRing3D;
  const setShow3D = motorPhase ? setShowTooth3D : setShowRing3D;

  // The canvas controls, in the same dock as the motor workspace. Before the
  // first solve it is shown greyed out, so the canvas keeps its size. The field
  // and mesh layers belong to the 2D solve, so they are greyed out in 3D.
  const renderViewDock = (unsolved: boolean) => {
    const layersDisabled = unsolved || show3D;
    return (
      <LessonDock
        tabs={[
          { id: '2d', label: '2D' },
          { id: '3d', label: '3D', disabled: unsolved, title: unsolved ? 'Solve the field first' : 'The same parts drawn with their depth' },
        ]}
        tab={!unsolved && show3D ? '3d' : '2d'}
        onTab={(tab) => setShow3D(tab === '3d')}
        end={unsolved ? 'Solve to see the field' : <span ref={setZoomSlot} />}
      >
        <LessonDockGroup label="Field">
          <LessonSegmented
            label="Field drawing"
            value={fieldDisplayMode}
            onChange={setFieldDisplayMode}
            options={[
              { id: 'lines', label: 'Field lines', disabled: layersDisabled, title: 'Lines that follow the direction of the field' },
              { id: 'density', label: 'Flux density', disabled: layersDisabled, title: 'Colour by field strength, |B|' },
            ]}
          />
        </LessonDockGroup>
        <LessonDockGroup label="Show">
          <LessonDockToggle
            pressed={showMesh}
            onChange={setShowMesh}
            disabled={layersDisabled}
            title="The triangles the solver divides the space into"
          >
            Mesh
          </LessonDockToggle>
        </LessonDockGroup>
      </LessonDock>
    );
  };

  // Display settings shared by the three solved 2D field pictures.
  const fieldViewerProps = {
    embedded: true,
    compactEmbedded: true,
    toolbarMode: 'zoom-only',
    zoomControlsSlot: zoomSlot,
    showMeshEdges: showMesh,
    showFieldIntensity: fieldDisplayMode === 'density',
    smoothFieldIntensity: true,
    fieldLinesVisible: fieldDisplayMode === 'lines',
    animateFieldArrows: fieldDisplayMode === 'lines',
    viewportPanEnabled: false,
  } as const;

  // Before a phase has a solve, the canvas shows the drawing of what will be solved.
  const renderUnsolvedCanvas = (label: string, picture: React.ReactNode, heading: string, body: React.ReactNode) => (
    <LessonLabCanvas className="iron-saturation-viewer">
      <LessonLabViewport label={label} hint="Not solved yet" className="is-centered">
        <div className="iron-saturation-stage-visual">
          {picture}
          <div className="iron-saturation-stage-copy">
            <h2>{heading}</h2>
            <p>{body}</p>
          </div>
        </div>
      </LessonLabViewport>
      {renderViewDock(true)}
    </LessonLabCanvas>
  );

  const renderSolvedCanvas = (label: string, view2D: React.ReactNode, view3D: React.ReactNode) => (
    <LessonLabCanvas className="iron-saturation-viewer">
      <LessonLabViewport label={label}>
        {show3D ? view3D : view2D}
      </LessonLabViewport>
      {renderViewDock(false)}
    </LessonLabCanvas>
  );

  const renderLabStage = () => {
    if (spmPhaseOpen) {
      if (!shownSpmRun) {
        return renderUnsolvedCanvas(
          'Wound steel tooth + N42 magnet pole',
          <SpmToothDiagram />,
          'The rotor now contributes its own field.',
          <>The N42 north face sits on curved rotor back iron and points across the same 2 mm airgap. Solve 0 A, then {SPM_HIGH_CURRENT_A} A, to separate permanent-magnet flux from the flux the coil adds.</>,
        );
      }
      const saturated = shownSpmRun.toothMeanBT >= SATURATION_B_T;
      return renderSolvedCanvas(
        `Wound steel tooth + N42 magnet pole · ${shownSpmRun.currentA.toFixed(0)} A`,
        <MeshViewer
          {...fieldViewerProps}
          meshData={shownSpmRun.data}
          pointLabels={[
            { xMm: -14.5, yMm: 5.5, label: '•', tone: 'neutral', textScale: 1.7 },
            { xMm: 14.5, yMm: 5.5, label: '×', tone: 'neutral', textScale: 1.7 },
            { xMm: 0, yMm: 4, label: saturated ? 'TOOTH · SATURATED' : 'STEEL TOOTH', tone: saturated ? 'north' : 'neutral', showBadge: false },
            { xMm: 0, yMm: -9, label: '2 mm airgap', tone: 'neutral', showBadge: false },
            { xMm: 0, yMm: -12.5, label: 'N42 · N', tone: 'north', showBadge: false },
          ]}
        />,
        <MotorTooth3D currentA={shownSpmRun.currentA} rotorMode="spm" saturated={saturated} />,
      );
    }
    if (toothPhaseOpen) {
      if (!shownToothRun) {
        return renderUnsolvedCanvas(
          'Wound steel motor tooth',
          <MotorToothDiagram />,
          'The solenoid idea becomes a tooth, yoke, airgap, and rotor.',
          <>The two slot-current regions are opposite sides of one coil around the center tooth. Solve 1 A, then {TOOTH_HIGH_CURRENT_A} A, to see the tooth become the bottleneck.</>,
        );
      }
      const saturated = shownToothRun.toothMeanBT >= SATURATION_B_T;
      return renderSolvedCanvas(
        `Wound steel motor tooth · ${shownToothRun.currentA.toFixed(0)} A`,
        <MeshViewer
          {...fieldViewerProps}
          meshData={shownToothRun.data}
          pointLabels={[
            { xMm: -14.5, yMm: 5.5, label: '•', tone: 'neutral', textScale: 1.7 },
            { xMm: 14.5, yMm: 5.5, label: '×', tone: 'neutral', textScale: 1.7 },
            { xMm: 0, yMm: 4, label: saturated ? 'TOOTH · SATURATED' : 'STEEL TOOTH', tone: saturated ? 'north' : 'neutral', showBadge: false },
            { xMm: 0, yMm: -9, label: '2 mm airgap', tone: 'neutral', showBadge: false },
          ]}
        />,
        <MotorTooth3D currentA={shownToothRun.currentA} saturated={saturated} />,
      );
    }
    if (!shownRun) {
      return renderUnsolvedCanvas(
        'Current-carrying wire in a steel ring',
        <SaturationPredictionDiagram />,
        'Start below the knee at 10 A.',
        'The out-of-screen conductor creates circular H; Magneto2D iterates each steel element on the B–H curve.',
      );
    }
    const saturated = shownRun.meanBT >= SATURATION_B_T;
    return renderSolvedCanvas(
      `Current-carrying wire in a steel ring · ${shownRun.currentA.toFixed(0)} A`,
      <MeshViewer
        {...fieldViewerProps}
        meshData={shownRun.data}
        pointLabels={[
          { xMm: 0, yMm: 0, label: `⊙ ${shownRun.currentA.toFixed(0)} A`, tone: 'neutral' },
          { xMm: 17, yMm: 0, label: saturated ? 'Steel · saturated' : 'Electrical steel', tone: saturated ? 'north' : 'neutral' },
        ]}
      />,
      <CurrentConductor3D currentA={shownRun.currentA} mode="iron-ring" saturated={saturated} />,
    );
  };

  const currentStepNumber = Math.max(1, lessonProgressSteps.findIndex((item) => item.id === activeProgressStepId) + 1);
  const currentStepLabel = lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label ?? '';
  const goalCard = (
    <LessonGoal step={currentStepNumber} total={lessonProgressSteps.length} title={currentGoal.title} detail={currentGoal.detail} />
  );

  // What the solves measured, for whichever experiment is open.
  const renderEvidence = () => {
    if (spmPhaseOpen) {
      if (!spmRuns.length) {
        return (
          <section className="iron-saturation-status-empty">
            <p className="learning-kicker">SPM operating point</p>
            <h2>Awaiting the magnet-only frame</h2>
            <p>This panel will separate the magnet’s baseline flux from the extra flux supplied by the coil.</p>
            <ol>
              <li><span>1</span> The N42 magnet drives flux at 0 A</li>
              <li><span>2</span> Coil MMF adds to it and raises the operating point</li>
              <li><span>3</span> Saturation of the steel tooth limits the gain</li>
            </ol>
          </section>
        );
      }
      return (
        <section className="iron-tooth-results iron-spm-results" aria-label="Solved SPM tooth response">
          <header>
            <div>
              <p className="learning-kicker">SPM operating point</p>
              <h2>The magnet sets the baseline; current moves it.</h2>
            </div>
            <span>{spmRuns.length} run{spmRuns.length === 1 ? '' : 's'}</span>
          </header>
          {shownSpmRun ? (
            <>
              <section className="iron-saturation-readout iron-tooth-readout">
                <div><span>Rotor magnet</span><strong>N42 · N toward stator</strong></div>
                <div><span>Coil MMF</span><strong>{(shownSpmRun.currentA * shownSpmRun.data.coil_turns).toLocaleString()} A·turn</strong></div>
                <div><span>Mean B in the tooth</span><strong>{shownSpmRun.toothMeanBT.toFixed(3)} T</strong></div>
                <div><span>Mean B in the airgap</span><strong>{shownSpmRun.airgapMeanBT.toFixed(3)} T</strong></div>
                <div><span>Airgap flux per metre of depth</span><strong>{(shownSpmRun.airgapFluxPerDepthWbPerM * 1e3).toFixed(2)} mWb/m</strong></div>
                <div><span>Tooth area above 1.60 T</span><strong className={shownSpmRun.toothSaturatedFraction > 0.05 ? 'is-hot' : ''}>{(shownSpmRun.toothSaturatedFraction * 100).toFixed(1)}%</strong></div>
              </section>
              <div className="iron-tooth-run-selector" aria-label="Solved SPM tooth currents">
                {spmRuns
                  .slice()
                  .sort((left, right) => left.currentA - right.currentA)
                  .map((run) => (
                    <button
                      key={run.currentA}
                      type="button"
                      className={Math.abs(run.currentA - shownSpmRun.currentA) < 0.1 ? 'is-active' : ''}
                      onClick={() => setSpmCurrentA(run.currentA)}
                    >
                      <span>{run.currentA.toFixed(0)} A</span>
                      <strong>{run.airgapMeanBT.toFixed(2)} T in airgap</strong>
                    </button>
                  ))}
              </div>
            </>
          ) : null}
          {spmBaselineRun && spmHighRun && spmFluxGainPct !== null ? (
            <section className="iron-tooth-insight iron-spm-insight">
              <p className="learning-kicker">Two sources, one saturated path</p>
              <h3>The magnet produces airgap flux before copper spends a watt.</h3>
              <div>
                <span><b>{(spmBaselineRun.airgapFluxPerDepthWbPerM * 1e3).toFixed(2)}</b> mWb/m airgap flux at 0 A</span>
                <span><b>{spmFluxGainPct >= 0 ? '+' : ''}{spmFluxGainPct.toFixed(0)}%</b> airgap flux, {SPM_HIGH_CURRENT_A} A vs 0 A</span>
                <span><b>{(spmHighRun.toothSaturatedFraction * 100).toFixed(0)}%</b> of tooth above 1.60 T at {SPM_HIGH_CURRENT_A} A</span>
              </div>
              <p>The N42 pole supplies the baseline airgap field. Coil MMF in the same direction adds flux until the steel tooth approaches its B–H knee, after which added current buys progressively less torque-producing field.</p>
            </section>
          ) : (
            <section className="iron-tooth-insight is-pending">
              <p className="learning-kicker">Separate the two field sources</p>
              <h3>Solve 0 A and {SPM_HIGH_CURRENT_A} A.</h3>
              <p>The first frame is magnet-only. The second adds coil MMF through the same airgap and tooth.</p>
            </section>
          )}
        </section>
      );
    }

    if (toothPhaseOpen) {
      if (!toothRuns.length) {
        return (
          <section className="iron-saturation-status-empty">
            <p className="learning-kicker">Motor consequence</p>
            <h2>Awaiting the 1 A tooth frame</h2>
            <p>This panel will separate what the coil spends from what the motor gets.</p>
            <ol>
              <li><span>1</span> Current × turns creates MMF</li>
              <li><span>2</span> The steel carries flux down the tooth</li>
              <li><span>3</span> That flux crosses the airgap</li>
            </ol>
          </section>
        );
      }
      return (
        <section className="iron-tooth-results" aria-label="Solved motor tooth response">
          <header>
            <div>
              <p className="learning-kicker">Motor consequence</p>
              <h2>The tooth becomes the bottleneck.</h2>
            </div>
            <span>{toothRuns.length} run{toothRuns.length === 1 ? '' : 's'}</span>
          </header>
          {shownToothRun ? (
            <>
              <section className="iron-saturation-readout iron-tooth-readout">
                <div><span>Coil MMF</span><strong>{(shownToothRun.currentA * shownToothRun.data.coil_turns).toLocaleString()} A·turn</strong></div>
                <div><span>Mean B in the tooth</span><strong>{shownToothRun.toothMeanBT.toFixed(3)} T</strong></div>
                <div><span>Mean B at the tooth tip</span><strong className={shownToothRun.toothTipMeanBT >= SATURATION_B_T ? 'is-hot' : ''}>{shownToothRun.toothTipMeanBT.toFixed(3)} T</strong></div>
                <div><span>Mean B in the airgap</span><strong>{shownToothRun.airgapMeanBT.toFixed(3)} T</strong></div>
                <div><span>Airgap flux per metre of depth</span><strong>{(shownToothRun.airgapFluxPerDepthWbPerM * 1e3).toFixed(2)} mWb/m</strong></div>
                <div><span>Tooth area above 1.60 T</span><strong className={shownToothRun.toothSaturatedFraction > 0.05 ? 'is-hot' : ''}>{(shownToothRun.toothSaturatedFraction * 100).toFixed(1)}%</strong></div>
              </section>
              <div className="iron-tooth-run-selector" aria-label="Solved motor tooth currents">
                {toothRuns
                  .slice()
                  .sort((left, right) => left.currentA - right.currentA)
                  .map((run) => (
                    <button
                      key={run.currentA}
                      type="button"
                      className={Math.abs(run.currentA - shownToothRun.currentA) < 0.1 ? 'is-active' : ''}
                      onClick={() => setToothCurrentA(run.currentA)}
                    >
                      <span>{run.currentA.toFixed(0)} A</span>
                      <strong>{run.airgapMeanBT.toFixed(2)} T in airgap</strong>
                    </button>
                  ))}
              </div>
            </>
          ) : null}
          {toothCurrentMultiplier && toothFluxMultiplier && toothLowRun && toothHighRun ? (
            <section className="iron-tooth-insight">
              <p className="learning-kicker">Why motors care · {toothHighRun.currentA.toFixed(0)} A vs {toothLowRun.currentA.toFixed(0)} A</p>
              <h3>More current stops buying proportional airgap flux.</h3>
              <div>
                <span><b>{toothCurrentMultiplier.toFixed(0)}×</b> the current</span>
                <span><b>{(toothCurrentMultiplier ** 2).toFixed(0)}×</b> the copper loss (I² trend)</span>
                <span><b>{toothFluxMultiplier.toFixed(1)}×</b> the airgap flux</span>
              </div>
              <p>The tooth approaches saturation, so extra MMF increasingly becomes copper heat instead of proportional airgap field. In a motor that means diminishing torque per added ampere.</p>
            </section>
          ) : (
            <section className="iron-tooth-insight is-pending">
              <p className="learning-kicker">Compare two operating points</p>
              <h3>Solve 1 A and {TOOTH_HIGH_CURRENT_A} A.</h3>
              <p>Then compare current, the I² copper-loss trend, local tooth saturation, and the flux crossing the airgap.</p>
            </section>
          )}
        </section>
      );
    }

    if (!runs.length) {
      return (
        <section className="iron-saturation-status-empty">
          <p className="learning-kicker">Solved material response</p>
          <h2>Awaiting the 10 A frame</h2>
          <p>The B–H curve, effective permeability, and the share of the steel that is saturated will appear here.</p>
          <ol>
            <li><span>1</span> Establish 10 A</li>
            <li><span>2</span> Approach the knee at 100 A</li>
            <li><span>3</span> Drive saturation at 800 A</li>
          </ol>
        </section>
      );
    }
    return (
      <section className="iron-saturation-results" aria-label="Solved material response">
        <header><div><p className="learning-kicker">Solved B–H sweep</p><h2>The steel’s B–H curve bends; constant μ does not survive the knee.</h2></div><span>{runs.length} run{runs.length === 1 ? '' : 's'}</span></header>
        <BhPlot runs={runs} curve={curve} activeCurrentA={currentRun?.currentA ?? shownRun?.currentA ?? null} onSelect={setCurrentA} />
        {shownRun ? (
          <section className="iron-saturation-readout">
            <div><span>Conductor current</span><strong>{shownRun.currentA.toFixed(0)} A</strong></div>
            <div><span>Mean H in the steel</span><strong>{(shownRun.meanHApm / 1000).toFixed(2)} kA/m</strong></div>
            <div><span>Mean B in the steel</span><strong>{shownRun.meanBT.toFixed(3)} T</strong></div>
            <div><span>Effective permeability μ<sub>r</sub></span><strong>{shownRun.effectiveMuRel.toFixed(0)}</strong></div>
            <div><span>Steel area above 1.60 T</span><strong className={shownRun.saturatedFraction > 0.05 ? 'is-hot' : ''}>{(shownRun.saturatedFraction * 100).toFixed(1)}%</strong></div>
            <div><span>Solver iterations</span><strong>{shownRun.data.metrics?.nonlinear_iterations ?? '—'}</strong></div>
          </section>
        ) : null}
      </section>
    );
  };

  const inspectPanel = (
    <LessonLabPanel
      ref={inspectorRef}
      side="inspect"
      kicker="Inspect"
      title={lessonStage === 'design'
        ? 'Nothing solved yet'
        : spmPhaseOpen
          ? 'Magnet + coil response'
          : toothPhaseOpen
            ? 'Motor tooth response'
            : 'Steel ring response'}
      summary={lessonStage === 'design'
        ? 'Make your prediction first. The solver’s answer and its measurements appear here in the next step.'
        : 'Drive electrical steel (grade M350-50A in every step) through its B–H knee and measure why additional current stops buying proportional flux.'}
      label="Lesson evidence and solved results"
      flash={inspectorFlash}
    >
      {lessonStage === 'design' ? (
        <LessonOutline
          steps={lessonProgressSteps.map((item) => ({
            id: item.id,
            label: item.label,
            detail: LESSON_FOUR_GOALS[item.id as LessonFourProgressStepId].detail,
          }))}
          currentId={activeProgressStepId}
        />
      ) : renderEvidence()}

      {/* The takeaway answers the check, so it waits until the check is passed. */}
      {quizOpen && (quizPassed || lessonComplete) ? (
        <section className="iron-saturation-takeaway"><p className="learning-kicker">Takeaway</p><h2>Motor teeth turn MMF into airgap flux—until they saturate.</h2><p>Before the knee, added current efficiently strengthens the airgap field. After the tooth tip saturates, copper loss rises much faster than airgap flux and torque potential.</p></section>
      ) : null}

      <LessonTerms terms={LESSON_FOUR_TERMS} />

      {lessonStage === 'solve' ? (
        <details className="iron-saturation-inspector-details">
          <summary>Details · {motorPhase ? 'MMF around the tooth' : 'H around the wire'}</summary>
          <div>
            {motorPhase ? (
              <section className="iron-saturation-equation-card iron-tooth-equation-card">
                <header><span>{spmPhaseOpen ? 'SPM MOTOR FIELD PATH' : 'MOTOR FIELD PATH'}</span><strong>N = 400 turns</strong></header>
                <div className="iron-saturation-equation">
                  <span>ℱ</span><b>=</b><span>{spmPhaseOpen ? 'ℱPM + NI' : 'NI'}</span>
                </div>
                <p>{spmPhaseOpen
                  ? 'The N42 pole supplies permanent-magnet MMF (ℱPM); coil MMF (NI) in the same direction raises the shared tooth and airgap operating point.'
                  : 'The coil supplies the MMF (ℱ = NI). The tooth and yoke carry flux; the airgap is where that field can act on the rotor.'}</p>
              </section>
            ) : (
              <section className="iron-saturation-equation-card">
                <header><span>AMPÈRE PATH</span><strong>probe r = 17 mm</strong></header>
                <div className="iron-saturation-equation"><span>H</span><b>≈</b><span className="iron-saturation-fraction"><i>I</i><i>2πr</i></span></div>
                <p>Current sets H around the ring. The steel’s B–H curve—not a constant μ—sets B.</p>
              </section>
            )}
            <p className="iron-saturation-inspector-material">The solver looks up the steel’s B–H curve separately in every mesh triangle, so each one can sit at a different point on the curve.</p>
          </div>
        </details>
      ) : null}
    </LessonLabPanel>
  );

  if (quizOpen) {
    return (
      <LessonLab className="iron-saturation-lab">
        {inspectPanel}
        <LessonLabStage className="is-tall">
          <LessonLabViewport label={`Knowledge check · ${QUIZ.length} questions`} className="is-scroll">
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Check"
          title="Can you recognize saturation?"
          label="Knowledge check"
          footer={(
            <LessonNextStep hint={quizPassed ? 'Lesson complete. Continue when you are ready.' : `Answer all ${QUIZ.length} questions to complete Lesson 4.`}>
              {quizPassed || lessonComplete ? (
                <a className="learning-primary-button" href="/tutorials/lesson-5">Next lesson</a>
              ) : null}
              <div className="lesson-lab-next-row">
                <LessonLink onClick={() => setQuizOpen(false)}>← Review experiment</LessonLink>
                <LessonLink onClick={onBackToCatalog}>All lessons</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <p className="lesson-lab-note">Use your solved B–H curve and flux-density pictures, not a fixed “2 T” rule. Your measurements stay on the right.</p>
        </LessonLabPanel>
      </LessonLab>
    );
  }

  if (lessonStage === 'design') {
    return (
      <LessonLab className="iron-saturation-lab">
        {inspectPanel}
        <LessonLabStage>
          <LessonLabViewport label="Current-carrying wire in a steel ring · not solved yet" className="is-centered">
            <div className="iron-saturation-stage-visual">
              <SaturationPredictionDiagram />
              <div className="iron-saturation-stage-copy">
                <h2>The limit of “iron makes flux easy”</h2>
                <p>A single conductor threads the ring—this is not a solenoid. Its circular H drives the steel’s response.</p>
              </div>
            </div>
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Predict"
          title="If current keeps rising, does B keep rising at the same rate?"
          summary="Current sets the field strength H. Flux density B is how the steel responds."
          label="Saturation prediction"
          footer={(
            <LessonNextStep
              tone={prediction ? (predictionCorrect ? 'good' : 'warn') : undefined}
              hint={prediction
                ? predictionCorrect
                  ? 'Correct. Solve three currents to locate the steel’s knee.'
                  : 'That assumes permeability never changes. Electrical steel has a nonlinear B–H curve.'
                : 'Make a prediction before seeing the solved field.'}
            >
              <button
                type="button"
                className="learning-primary-button"
                disabled={!predictionCorrect}
                onClick={openLab}
              >
                Next: Saturation lab →
              </button>
              <div className="lesson-lab-next-row">
                <LessonLink onClick={onBackToCatalog}>← All lessons</LessonLink>
                <LessonLink onClick={onBackHome}>Design start</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <LessonChoices
            label="What happens to B as current keeps increasing?"
            value={prediction}
            onChange={setPrediction}
            correctId="knee"
            options={PREDICTION_OPTIONS}
          />
        </LessonLabPanel>
      </LessonLab>
    );
  }

  return (
    <LessonLab className="iron-saturation-lab">
      {inspectPanel}
      <LessonLabStage>{renderLabStage()}</LessonLabStage>
      <LessonLabPanel
        side="do"
        kicker={`Experiment · ${currentStepLabel}`}
        title={spmPhaseOpen ? 'SPM pole lab' : toothPhaseOpen ? 'Motor-tooth lab' : 'Saturation lab'}
        label="Saturation experiment controls"
        footer={(
          <LessonNextStep hint={labInsight}>
            <button type="button" className="learning-primary-button" disabled={busy} onClick={labPrimary.onClick}>
              {labPrimary.label}
            </button>
          </LessonNextStep>
        )}
      >
        {goalCard}
        {spmPhaseOpen ? (
          <>
            <section className="iron-saturation-control-card iron-tooth-control-card iron-spm-control-card">
              <div className="iron-tooth-winding-summary">
                <span>SPM pole + wound stator tooth</span>
                <strong>N42 · 400 turns · 2 mm airgap</strong>
                <small>The magnet supplies baseline flux; positive current adds to it.</small>
              </div>
              <label htmlFor="iron-spm-current-slider"><span>Coil current</span><strong>{spmCurrentA.toFixed(0)} A</strong></label>
              <input
                id="iron-spm-current-slider"
                type="range"
                min="0"
                max={SPM_HIGH_CURRENT_A}
                step="1"
                value={spmCurrentA}
                disabled={busy}
                aria-label={`SPM tooth coil current ${spmCurrentA} amperes`}
                onChange={(event) => setSpmCurrentA(Number(event.currentTarget.value))}
              />
              <div className="iron-saturation-scale"><span>0 A · magnet only</span><span>0–8,000 A·turn</span><span>{SPM_HIGH_CURRENT_A} A</span></div>
              {spmComparisonReady ? (
                <div className="iron-saturation-explore-actions">
                  <button
                    type="button"
                    className="iron-saturation-plot-button"
                    disabled={busy || Boolean(spmCurrentRun)}
                    onClick={() => void solveSpmCurrent()}
                  >
                    {spmCurrentRun ? 'Move slider to plot another point' : `Plot ${spmCurrentA.toFixed(0)} A`}
                  </button>
                </div>
              ) : null}
            </section>
            <p className="iron-saturation-rail-hint">
              {!spmBaselineRun
                ? 'Start at 0 A: the N42 pole already sends flux across the airgap.'
                : !spmHighRun
                  ? `Now add ${SPM_HIGH_CURRENT_A} A in the direction that helps the magnet and watch the same steel tooth become the limiter.`
                  : 'The magnet establishes the baseline; coil current shifts the operating point toward tooth saturation.'}
            </p>
          </>
        ) : toothPhaseOpen ? (
          <>
            <section className="iron-saturation-control-card iron-tooth-control-card">
              <div className="iron-tooth-winding-summary">
                <span>Iron-core solenoid → motor tooth</span>
                <strong>400 turns · 2 mm airgap</strong>
                <small>⊙ current out of screen · ⊗ current into screen</small>
              </div>
              <label htmlFor="iron-tooth-current-slider"><span>Coil current</span><strong>{toothCurrentA.toFixed(0)} A</strong></label>
              <input
                id="iron-tooth-current-slider"
                type="range"
                min="1"
                max={TOOTH_HIGH_CURRENT_A}
                step="1"
                value={toothCurrentA}
                disabled={busy}
                aria-label={`Motor tooth coil current ${toothCurrentA} amperes`}
                onChange={(event) => setToothCurrentA(Number(event.currentTarget.value))}
              />
              <div className="iron-saturation-scale"><span>1 A</span><span>400–8,000 A·turn</span><span>{TOOTH_HIGH_CURRENT_A} A</span></div>
              {toothComparisonReady ? (
                <div className="iron-saturation-explore-actions">
                  <button
                    type="button"
                    className="iron-saturation-plot-button"
                    disabled={busy || Boolean(toothCurrentRun)}
                    onClick={() => void solveToothCurrent()}
                  >
                    {toothCurrentRun ? 'Move slider to plot another point' : `Plot ${toothCurrentA.toFixed(0)} A`}
                  </button>
                </div>
              ) : null}
            </section>
            <p className="iron-saturation-rail-hint">
              {!toothLowRun
                ? 'Start at 1 A to see the tooth carry flux efficiently below the knee.'
                : !toothHighRun
                  ? `Now drive ${TOOTH_HIGH_CURRENT_A} A. Compare the large copper-loss increase with the smaller airgap-flux gain.`
                  : 'The same B–H curve now acts locally. Next, add a real N42 rotor pole and separate magnet flux from coil flux.'}
            </p>
          </>
        ) : (
          <>
            <section className="iron-saturation-control-card">
              <label htmlFor="iron-saturation-slider"><span>Conductor current</span><strong>{currentA.toFixed(0)} A</strong></label>
              <input id="iron-saturation-slider" type="range" min="10" max="800" step="10" value={currentA} disabled={busy} aria-label={`Conductor current ${currentA} amperes`} onChange={(event) => setCurrentA(Number(event.currentTarget.value))} />
              <div className="iron-saturation-scale"><span>10 A</span><span>100 A knee</span><span>800 A</span></div>
              {comparisonReady ? (
                <div className="iron-saturation-explore-actions">
                  <button
                    type="button"
                    className="iron-saturation-plot-button"
                    disabled={busy || Boolean(currentRun)}
                    onClick={() => void solveCurrent()}
                  >
                    {busy
                      ? 'Meshing + nonlinear solve…'
                      : currentRun
                        ? 'Move slider to plot another point'
                        : `Plot ${currentA.toFixed(0)} A`}
                  </button>
                </div>
              ) : null}
            </section>
            <p className="iron-saturation-rail-hint">
              {comparisonReady
                ? 'The material rule is established. Next, use it in a real concentrated tooth winding.'
                : !lowRun
                  ? 'Start below the knee at 10 A.'
                  : !kneeRun
                    ? 'Now solve 100 A to approach the knee.'
                    : 'Now solve 800 A to expose saturation.'}
            </p>
          </>
        )}
        {error ? <p className="lesson-lab-error">{error}</p> : null}
      </LessonLabPanel>
    </LessonLab>
  );
};
