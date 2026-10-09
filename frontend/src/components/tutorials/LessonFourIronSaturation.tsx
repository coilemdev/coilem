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
    detail: 'Solve 10 A while M350-50A still has high effective permeability.',
  },
  knee: {
    title: 'Find the B–H knee',
    detail: 'Solve 100 A and watch the material curve begin to bend.',
  },
  saturation: {
    title: 'Drive the steel into saturation',
    detail: 'Solve 800 A and compare the extra H with the smaller gain in B.',
  },
  tooth: {
    title: 'Put the solenoid idea inside a motor',
    detail: 'Wrap a concentrated winding around one tooth and measure tooth B and useful airgap flux.',
  },
  spm: {
    title: 'Add the permanent-magnet source',
    detail: 'Place an N42 surface pole on curved rotor back iron, then compare magnet-only and energized airgap flux.',
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

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'saturation-meaning',
    prompt: 'What changes most dramatically after M350-50A passes its B–H knee?',
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
    prompt: 'Why does the |B| map show saturation locally instead of labeling the whole part saturated?',
    options: ['B varies from element to element', 'Only the mesh can saturate', 'M350-50A has no B–H curve'],
    correctIndex: 0,
    explanation: 'Geometry concentrates flux. Each FEM element samples its own B and therefore its own point on the M350-50A curve.',
  },
  {
    id: 'saturation-motor',
    prompt: 'Why is a saturated tooth costly in a motor?',
    options: [
      'Copper loss keeps rising roughly with I² while useful airgap flux gains diminish',
      'The permanent magnets instantly demagnetize',
      'The airgap becomes electrically conductive',
    ],
    correctIndex: 0,
    explanation: 'Torque potential follows useful airgap flux, but winding heating grows rapidly with current. A saturated tooth therefore buys less torque per added ampere.',
  },
  {
    id: 'saturation-spm',
    prompt: 'Why does the SPM tooth fixture carry airgap flux even at 0 A?',
    options: [
      'The N42 magnet supplies flux before the winding adds magnetomotive force',
      'The M350-50A steel creates permanent flux by itself',
      'The mesh stores current from the previous solve',
    ],
    correctIndex: 0,
    explanation: 'The surface magnet establishes a baseline field. Reinforcing winding current can raise useful flux further, but the same M350-50A tooth still becomes the bottleneck near saturation.',
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
  <svg className="iron-saturation-prediction" viewBox="0 0 760 500" role="img" aria-label="Current conductor passing through an M350-50A steel ring">
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
    <text x="380" y="430" className="iron-saturation-material-label">M350-50A STEEL · WHAT HAPPENS AS CURRENT KEEPS RISING?</text>
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
    <text x="380" y="135" className="iron-tooth-label">WOUND M350-50A STATOR TOOTH</text>
    <text x="380" y="380" className="iron-tooth-gap-label">2 mm AIRGAP</text>
    <text x="380" y="410" className="iron-spm-pole-label">N · N42 SURFACE POLE</text>
    <text x="380" y="458" className="iron-tooth-label">CURVED M350-50A ROTOR BACK IRON</text>
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
  const width = 370;
  const height = 260;
  const margin = { top: 28, right: 18, bottom: 52, left: 56 };
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
        <span className="is-curve">M350-50A material curve</span>
        <span className="is-linear">If μ stayed constant</span>
        <span className="is-fem">Nonlinear FEM</span>
      </div>
      <svg className="iron-saturation-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="M350-50A flux density B versus magnetic field strength H">
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
  const solveInspectorRef = React.useRef<HTMLElement>(null);
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
  const [showBMap, setShowBMap] = React.useState(true);
  const [showFluxLines, setShowFluxLines] = React.useState(false);
  const [showMesh, setShowMesh] = React.useState(false);
  const [showTooth3D, setShowTooth3D] = React.useState(false);
  const [showRing3D, setShowRing3D] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(false);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
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
  const fieldToolbarLabel = showBMap
    ? showFluxLines ? 'Flux density |B| + flux lines' : 'Flux density |B|'
    : showFluxLines ? 'Flux lines' : showMesh ? 'Mesh' : 'Geometry';
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
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
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
  const completedStepCount = lessonProgressSteps.filter((item) => item.complete).length;

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('iron-saturation', true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  React.useEffect(() => {
    if (solveInspectorOpen) solveInspectorRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [runs, solveInspectorOpen, spmRuns, toothRuns]);

  const setStage = (next: 'design' | 'solve') => {
    setQuizOpen(false);
    setLabControlsOpen(next === 'solve');
    setSolveInspectorOpen(false);
    if (next === 'design') {
      setToothPhaseOpen(false);
      setSpmPhaseOpen(false);
    }
    onStageChange?.(next);
  };

  const guidedCurrent = !lowRun ? LOW_CURRENT_A : !kneeRun ? KNEE_CURRENT_A : !highRun ? HIGH_CURRENT_A : currentA;

  const solveCurrent = async (requestedCurrentA = currentA) => {
    setBusy(true);
    setError(null);
    try {
      const run = runFromData(await solveClient.fetchIronSaturationSolve(requestedCurrentA));
      setCurrentA(requestedCurrentA);
      setRuns((previous) => [run, ...previous.filter((item) => Math.abs(item.currentA - requestedCurrentA) >= 0.1)].slice(0, 8));
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
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
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
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
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The nonlinear SPM tooth solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const advanceLab = () => {
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    if (spmPhaseOpen && spmComparisonReady) {
      setQuizOpen(true);
    } else if (toothPhaseOpen && toothComparisonReady) {
      setToothPhaseOpen(false);
      setSpmPhaseOpen(true);
      setSpmCurrentA(SPM_BASELINE_CURRENT_A);
      setLabControlsOpen(true);
    } else if (!toothPhaseOpen && !spmPhaseOpen && comparisonReady) {
      setToothPhaseOpen(true);
      setSpmPhaseOpen(false);
      setToothCurrentA(TOOTH_LOW_CURRENT_A);
      setLabControlsOpen(true);
    }
  };

  const labAdvanceLabel = spmPhaseOpen
    ? spmComparisonReady ? 'Continue to Check' : null
    : toothPhaseOpen
      ? toothComparisonReady ? 'Continue: Add SPM pole' : null
      : comparisonReady ? 'Continue: Motor tooth' : null;

  const labInsight = spmPhaseOpen
    ? spmComparisonReady
      ? 'The magnet sets the baseline; winding current pushes the shared tooth toward saturation.'
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

  return (
    <main
      className={`learning-shell learning-lesson-shell iron-saturation-shell is-${lessonStage}-stage${quizOpen ? ' is-quiz-open' : ''}`}
    >
      {(lessonStage === 'design' || (lessonStage === 'solve' && !quizOpen && labControlsOpen)) ? (
      <aside className={`learning-control-panel iron-saturation-control-panel${quizOpen ? ' is-quiz-open' : ''}`} aria-label="Saturation experiment controls">
        {lessonStage === 'solve' ? <button type="button" className="iron-saturation-drawer-close" onClick={() => setLabControlsOpen(false)} aria-label="Close saturation controls">×</button> : null}
        {quizOpen ? (
          <details className="learning-quiz-reference">
            <summary>Review the solved B–H sweep</summary>
            <div>
              <strong>{runs.length} ring · {toothRuns.length} steel-rotor · {spmRuns.length} SPM frames</strong>
              <p>The right panel keeps the motor consequence visible while you answer.</p>
            </div>
          </details>
        ) : null}

        <section className="learning-control-section">
          <p className="iron-saturation-panel-kicker">Lab setup · {lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label}</p>
          <h2>{lessonStage === 'design' ? 'Make a prediction' : quizOpen ? 'Knowledge check' : spmPhaseOpen ? 'SPM pole lab' : toothPhaseOpen ? 'Motor-tooth lab' : 'Saturation lab'}</h2>
          <section className="iron-saturation-lab-goal" aria-label="Current lesson goal">
            <span>{completedStepCount}/{lessonProgressSteps.length}</span>
            <div>
              <p>Current goal</p>
              <strong>{currentGoal.title}</strong>
              <small>{currentGoal.detail}</small>
            </div>
          </section>

          {lessonStage === 'design' ? (
            <>
              <p className="iron-saturation-control-intro">What happens to B as current keeps increasing?</p>
              <div className="iron-saturation-predictions">
                {([
                  ['linear', 'B keeps scaling linearly', 'A single constant permeability works at every current.'],
                  ['knee', 'B bends toward a plateau', 'Effective permeability falls after the material knee.'],
                  ['fall', 'B falls back to zero', 'More H cancels the field in the ring.'],
                ] as Array<[Prediction, string, string]>).map(([value, label, detail]) => (
                  <button key={value} type="button" className={`${prediction === value ? 'is-selected' : ''}${prediction === value && value === 'knee' ? ' is-correct' : ''}`} onClick={() => setPrediction(value)}>
                    <strong>{label}</strong><span>{detail}</span>
                  </button>
                ))}
              </div>
              {prediction ? <p className={`iron-saturation-feedback${predictionCorrect ? ' is-correct' : ''}`}>{predictionCorrect ? 'Correct. Solve three currents to locate the M350-50A knee.' : 'That assumes permeability never changes. M350-50A has a nonlinear B–H curve.'}</p> : null}
              <section className="iron-saturation-vocabulary"><strong>B is not H</strong><p><b>H</b> is supplied by current. <b>B</b> is the material response.</p></section>
            </>
          ) : !quizOpen ? (
            spmPhaseOpen ? (
              <>
                <section className="iron-saturation-control-card iron-tooth-control-card iron-spm-control-card">
                  <div className="iron-tooth-winding-summary">
                    <span>SPM pole + wound stator tooth</span>
                    <strong>N42 · 400 turns · 2 mm airgap</strong>
                    <small>The magnet supplies baseline flux; positive current reinforces it.</small>
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
                  <div className="iron-saturation-scale"><span>0 A · magnet only</span><span>reinforcing NI</span><span>{SPM_HIGH_CURRENT_A} A</span></div>
                  {!spmComparisonReady ? (
                    <button
                      type="button"
                      className="iron-saturation-guide-button"
                      disabled={busy}
                      onClick={() => void solveSpmCurrent(spmCurrentRun ? (spmBaselineRun ? SPM_HIGH_CURRENT_A : SPM_BASELINE_CURRENT_A) : spmCurrentA)}
                    >
                      {busy
                        ? 'Meshing N42 pole + nonlinear tooth…'
                        : spmCurrentRun
                          ? `Solve recommended ${spmBaselineRun ? SPM_HIGH_CURRENT_A : SPM_BASELINE_CURRENT_A} A`
                          : spmCurrentA === 0
                            ? 'Solve magnet-only baseline'
                            : `Solve SPM tooth at ${spmCurrentA.toFixed(0)} A`}
                    </button>
                  ) : (
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
                  )}
                  {error ? <p className="iron-saturation-error">{error}</p> : null}
                </section>
                <p className="iron-saturation-rail-hint">
                  {!spmBaselineRun
                    ? 'Start at 0 A: the N42 pole already sends flux across the airgap.'
                    : !spmHighRun
                      ? `Now reinforce the magnet with ${SPM_HIGH_CURRENT_A} A and watch the same M350-50A tooth become the limiter.`
                      : 'The magnet establishes the baseline; winding current shifts the operating point toward tooth saturation.'}
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
                  {!toothComparisonReady ? (
                    <button
                      type="button"
                      className="iron-saturation-guide-button"
                      disabled={busy}
                      onClick={() => void solveToothCurrent(toothCurrentRun ? (toothLowRun ? TOOTH_HIGH_CURRENT_A : TOOTH_LOW_CURRENT_A) : toothCurrentA)}
                    >
                      {busy
                        ? 'Meshing + nonlinear tooth solve…'
                        : toothCurrentRun
                          ? `Solve recommended ${toothLowRun ? TOOTH_HIGH_CURRENT_A : TOOTH_LOW_CURRENT_A} A`
                          : `Solve tooth at ${toothCurrentA.toFixed(0)} A`}
                    </button>
                  ) : (
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
                  )}
                  {error ? <p className="iron-saturation-error">{error}</p> : null}
                </section>
                <p className="iron-saturation-rail-hint">
                  {!toothLowRun
                    ? 'Start at 1 A to see the tooth carry flux efficiently below the knee.'
                    : !toothHighRun
                      ? `Now drive ${TOOTH_HIGH_CURRENT_A} A. Compare the large copper-loss increase with the smaller useful airgap-flux gain.`
                      : 'The same M350-50A curve now acts locally. Next, add a real N42 rotor pole and separate magnet flux from winding flux.'}
                </p>
              </>
            ) : (
              <>
                <section className="iron-saturation-control-card">
                  <label htmlFor="iron-saturation-slider"><span>Conductor current</span><strong>{currentA.toFixed(0)} A</strong></label>
                  <input id="iron-saturation-slider" type="range" min="10" max="800" step="10" value={currentA} disabled={busy} aria-label={`Coil current ${currentA} amperes`} onChange={(event) => setCurrentA(Number(event.currentTarget.value))} />
                  <div className="iron-saturation-scale"><span>10 A</span><span>100 A knee</span><span>800 A</span></div>
                  {!comparisonReady ? (
                    <button
                      type="button"
                      className="iron-saturation-guide-button"
                      disabled={busy}
                      onClick={() => void solveCurrent(currentRun ? guidedCurrent : currentA)}
                    >
                      {busy
                        ? 'Meshing + nonlinear solve…'
                        : currentRun
                          ? `Solve recommended ${guidedCurrent} A`
                          : `Solve ${currentA.toFixed(0)} A`}
                    </button>
                  ) : (
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
                  )}
                  {error ? <p className="iron-saturation-error">{error}</p> : null}
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
            )
          ) : null}
        </section>

        <div className="learning-panel-actions is-single">
          {lessonStage === 'design' ? <button type="button" className="learning-primary-button" disabled={!predictionCorrect} onClick={() => setStage('solve')}>Next: Saturation lab</button> : null}
        </div>

        {lessonStage === 'design' ? <footer className="learning-panel-footer">
          <div className="learning-panel-nav">
            <button type="button" className="learning-ghost-button" onClick={onBackToCatalog}>Lessons</button>
            <button type="button" className="learning-ghost-button" onClick={onBackHome}>Design start</button>
          </div>
        </footer> : null}
      </aside>
      ) : null}

      <section className="learning-main-stage iron-saturation-main">
        {quizOpen ? (
          <section className="iron-saturation-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you recognize saturation?</h2>
            <p>Use the solved B–H curve and element map, not a fixed “2 T” rule.</p>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </section>
        ) : lessonStage === 'design' ? (
          <section className="iron-saturation-predict-stage">
            <div className="learning-stage-badge"><span>Predict</span><strong>One conductor + one steel ring</strong></div>
            <SaturationPredictionDiagram />
            <div className="iron-saturation-stage-copy">
              <p className="learning-kicker">The limit of “iron makes flux easy”</p>
              <h2>If current keeps rising, does B keep rising at the same rate?</h2>
              <p>A single conductor threads the ring—this is not a solenoid. Its circular H drives the M350-50A material response.</p>
            </div>
          </section>
        ) : spmPhaseOpen ? (
          shownSpmRun ? (
            <div className="iron-saturation-viewer iron-tooth-viewer iron-spm-tooth-viewer">
              <div className="mesh-viewer-header iron-saturation-visual-header">
                <div className="mesh-viewer-title"><h3>Wound M350-50A tooth + N42 surface pole</h3></div>
                <div className="iron-saturation-view-toggle" role="group" aria-label="Field visualization">
                  <button type="button" className={!showTooth3D && showBMap ? 'is-active' : ''} onClick={() => { setShowBMap((visible) => showTooth3D ? true : !visible); setShowTooth3D(false); }} aria-pressed={!showTooth3D && showBMap}><span className="is-density" /> |B| map</button>
                  <button type="button" className={!showTooth3D && showFluxLines ? 'is-active' : ''} onClick={() => { setShowFluxLines((visible) => showTooth3D ? true : !visible); setShowTooth3D(false); }} aria-pressed={!showTooth3D && showFluxLines}><span /> Flux lines</button>
                  <button type="button" className={!showTooth3D && showMesh ? 'is-active' : ''} onClick={() => { setShowMesh((visible) => showTooth3D ? true : !visible); setShowTooth3D(false); }} aria-pressed={!showTooth3D && showMesh}><span className="is-mesh" /> Mesh</button>
                  <button type="button" className={showTooth3D ? 'is-active' : ''} onClick={() => setShowTooth3D(true)} aria-pressed={showTooth3D}><span className="is-three" /> 3D</button>
                </div>
              </div>
              {showTooth3D ? (
                <MotorTooth3D
                  currentA={shownSpmRun.currentA}
                  rotorMode="spm"
                  saturated={shownSpmRun.toothMeanBT >= 1.6}
                />
              ) : (
                <MeshViewer
                  meshData={shownSpmRun.data}
                  embedded
                  compactEmbedded
                  toolbarMode="zoom-only"
                  toolbarLabel={fieldToolbarLabel}
                  showMeshEdges={showMesh}
                  showFieldIntensity={showBMap}
                  smoothFieldIntensity
                  fieldLinesVisible={showFluxLines}
                  animateFieldArrows={showFluxLines}
                  viewportPanEnabled={false}
                  pointLabels={[
                    { xMm: -14.5, yMm: 5.5, label: '•', tone: 'neutral', textScale: 1.7 },
                    { xMm: 14.5, yMm: 5.5, label: '×', tone: 'neutral', textScale: 1.7 },
                    { xMm: 0, yMm: 4, label: shownSpmRun.toothMeanBT >= 1.6 ? 'TOOTH · SATURATED' : 'M350-50A TOOTH', tone: shownSpmRun.toothMeanBT >= 1.6 ? 'north' : 'neutral', showBadge: false },
                    { xMm: 0, yMm: -9, label: '2 mm airgap', tone: 'neutral', showBadge: false },
                    { xMm: 0, yMm: -12.5, label: 'N42 · N', tone: 'north', showBadge: false },
                  ]}
                />
              )}
            </div>
          ) : (
            <section className="iron-saturation-empty-stage iron-tooth-empty-stage iron-spm-empty-stage">
              <div className="learning-stage-badge"><span>SPM pole</span><strong>Magnet source + wound tooth</strong></div>
              <SpmToothDiagram />
              <div>
                <h2>The rotor now contributes its own field.</h2>
                <p>The N42 north face sits on curved rotor back iron and points across the same 2 mm airgap. Solve 0 A, then {SPM_HIGH_CURRENT_A} A, to separate permanent-magnet flux from reinforcing winding flux.</p>
              </div>
            </section>
          )
        ) : toothPhaseOpen ? (
          shownToothRun ? (
            <div className="iron-saturation-viewer iron-tooth-viewer">
              <div className="mesh-viewer-header iron-saturation-visual-header">
                <div className="mesh-viewer-title"><h3>Wound M350-50A motor tooth</h3></div>
                <div className="iron-saturation-view-toggle" role="group" aria-label="Field visualization">
                  <button type="button" className={!showTooth3D && showBMap ? 'is-active' : ''} onClick={() => { setShowBMap((visible) => showTooth3D ? true : !visible); setShowTooth3D(false); }} aria-pressed={!showTooth3D && showBMap}><span className="is-density" /> |B| map</button>
                  <button type="button" className={!showTooth3D && showFluxLines ? 'is-active' : ''} onClick={() => { setShowFluxLines((visible) => showTooth3D ? true : !visible); setShowTooth3D(false); }} aria-pressed={!showTooth3D && showFluxLines}><span /> Flux lines</button>
                  <button type="button" className={!showTooth3D && showMesh ? 'is-active' : ''} onClick={() => { setShowMesh((visible) => showTooth3D ? true : !visible); setShowTooth3D(false); }} aria-pressed={!showTooth3D && showMesh}><span className="is-mesh" /> Mesh</button>
                  <button type="button" className={showTooth3D ? 'is-active' : ''} onClick={() => setShowTooth3D(true)} aria-pressed={showTooth3D}><span className="is-three" /> 3D</button>
                </div>
              </div>
              {showTooth3D ? (
                <MotorTooth3D
                  currentA={shownToothRun.currentA}
                  saturated={shownToothRun.toothMeanBT >= 1.6}
                />
              ) : (
                <MeshViewer
                  meshData={shownToothRun.data}
                  embedded
                  compactEmbedded
                  toolbarMode="zoom-only"
                  toolbarLabel={fieldToolbarLabel}
                  showMeshEdges={showMesh}
                  showFieldIntensity={showBMap}
                  smoothFieldIntensity
                  fieldLinesVisible={showFluxLines}
                  animateFieldArrows={showFluxLines}
                  viewportPanEnabled={false}
                  pointLabels={[
                    { xMm: -14.5, yMm: 5.5, label: '•', tone: 'neutral', textScale: 1.7 },
                    { xMm: 14.5, yMm: 5.5, label: '×', tone: 'neutral', textScale: 1.7 },
                    { xMm: 0, yMm: 4, label: shownToothRun.toothMeanBT >= 1.6 ? 'TOOTH · SATURATED' : 'M350-50A TOOTH', tone: shownToothRun.toothMeanBT >= 1.6 ? 'north' : 'neutral', showBadge: false },
                    { xMm: 0, yMm: -9, label: '2 mm airgap', tone: 'neutral', showBadge: false },
                  ]}
                />
              )}
            </div>
          ) : (
            <section className="iron-saturation-empty-stage iron-tooth-empty-stage">
              <div className="learning-stage-badge"><span>Motor tooth</span><strong>Concentrated winding</strong></div>
              <MotorToothDiagram />
              <div>
                <h2>The solenoid idea becomes a tooth, yoke, airgap, and rotor.</h2>
                <p>The two slot-current regions are opposite sides of one coil around the center tooth. Solve 1 A, then {TOOTH_HIGH_CURRENT_A} A, to see the tooth become the bottleneck.</p>
              </div>
            </section>
          )
        ) : shownRun ? (
          <div className="iron-saturation-viewer">
            <div className="mesh-viewer-header iron-saturation-visual-header">
              <div className="mesh-viewer-title"><h3>Current-driven M350-50A ring</h3></div>
              <div className="iron-saturation-view-toggle" role="group" aria-label="Field visualization">
                <button type="button" className={!showRing3D && showBMap ? 'is-active' : ''} onClick={() => { setShowBMap((visible) => showRing3D ? true : !visible); setShowRing3D(false); }} aria-pressed={!showRing3D && showBMap}><span className="is-density" /> |B| map</button>
                <button type="button" className={!showRing3D && showFluxLines ? 'is-active' : ''} onClick={() => { setShowFluxLines((visible) => showRing3D ? true : !visible); setShowRing3D(false); }} aria-pressed={!showRing3D && showFluxLines}><span /> Flux lines</button>
                <button type="button" className={!showRing3D && showMesh ? 'is-active' : ''} onClick={() => { setShowMesh((visible) => showRing3D ? true : !visible); setShowRing3D(false); }} aria-pressed={!showRing3D && showMesh}><span className="is-mesh" /> Mesh</button>
                <button type="button" className={showRing3D ? 'is-active' : ''} onClick={() => setShowRing3D(true)} aria-pressed={showRing3D}><span className="is-three" /> 3D</button>
              </div>
            </div>
            {showRing3D ? (
              <CurrentConductor3D
                currentA={shownRun.currentA}
                mode="iron-ring"
                saturated={shownRun.meanBT >= 1.6}
              />
            ) : (
              <MeshViewer
                meshData={shownRun.data}
                embedded
                compactEmbedded
                toolbarMode="zoom-only"
                toolbarLabel={fieldToolbarLabel}
                showMeshEdges={showMesh}
                showFieldIntensity={showBMap}
                smoothFieldIntensity
                fieldLinesVisible={showFluxLines}
                animateFieldArrows={showFluxLines}
                viewportPanEnabled={false}
                pointLabels={[
                  { xMm: 0, yMm: 0, label: `⊙ ${shownRun.currentA.toFixed(0)} A`, tone: 'neutral' },
                  { xMm: 17, yMm: 0, label: shownRun.meanBT >= 1.6 ? 'M350-50A · saturated' : 'M350-50A steel', tone: shownRun.meanBT >= 1.6 ? 'north' : 'neutral' },
                ]}
              />
            )}
          </div>
        ) : (
          <section className="iron-saturation-empty-stage">
            <div className="learning-stage-badge"><span>Low field</span><strong>Nonlinear material</strong></div>
            <SaturationPredictionDiagram />
            <div><h2>Start below the knee at 10 A.</h2><p>The out-of-screen conductor creates circular H; Magneto2D iterates each steel element on the M350-50A B–H curve.</p></div>
          </section>
        )}

        {lessonStage === 'solve' && !quizOpen ? (
          <div className="iron-saturation-lesson-dock" aria-label="Saturation experiment controls">
            <div className="iron-saturation-dock-insight"><span>{activeProgressStepId}</span><strong>{labInsight}</strong></div>
            <div className="iron-saturation-dock-actions">
              <button type="button" className="iron-saturation-dock-button" aria-expanded={labControlsOpen} onClick={() => { setLabControlsOpen((open) => !open); setSolveInspectorOpen(false); }}>{labControlsOpen ? 'Done' : 'Adjust experiment'}</button>
              <button type="button" className="iron-saturation-dock-button" aria-expanded={solveInspectorOpen} onClick={() => { setSolveInspectorOpen((open) => !open); setLabControlsOpen(false); }}>Inspect results</button>
              {labAdvanceLabel ? <button type="button" className="learning-primary-button iron-saturation-dock-primary" onClick={advanceLab}>{labAdvanceLabel}</button> : null}
            </div>
          </div>
        ) : quizOpen && !quizPassed && !lessonComplete ? (
          <div className="iron-saturation-lesson-dock iron-saturation-quiz-dock" aria-label="Knowledge check controls">
            <div className="iron-saturation-dock-insight"><span>Check</span><strong>Answer all five questions to complete Lesson 4.</strong></div>
            <div className="iron-saturation-dock-actions">
              <button type="button" className="iron-saturation-dock-button" onClick={() => { setQuizOpen(false); setSolveInspectorOpen(true); }}>Review experiment</button>
              <button type="button" className="iron-saturation-dock-button" onClick={onBackToCatalog}>Lessons</button>
            </div>
          </div>
        ) : null}
      </section>

      {lessonStage === 'solve' && !quizOpen && solveInspectorOpen ? (
      <aside ref={solveInspectorRef} className="learning-context-panel iron-saturation-context" aria-label="Lesson guidance and solved results">
        <button type="button" className="iron-saturation-drawer-close" onClick={() => setSolveInspectorOpen(false)} aria-label="Close saturation results">×</button>
        <header className="iron-saturation-status-header">
          <p className="learning-kicker">Lesson 4 of 10</p>
          <h1>When Iron Saturates</h1>
          <p>Drive M350-50A through its B–H knee and measure why additional current stops buying proportional flux.</p>
          <div className="learning-progress" aria-label="Lesson completion">
            <span style={{ width: `${(completedStepCount / lessonProgressSteps.length) * 100}%` }} />
          </div>
        </header>

        {spmPhaseOpen ? (
          spmRuns.length ? (
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
                    <div><span>Rotor source</span><strong>N42 · N toward stator</strong></div>
                    <div><span>Winding magnetomotive force</span><strong>{(shownSpmRun.currentA * shownSpmRun.data.coil_turns).toLocaleString()} A·turn</strong></div>
                    <div><span>Mean B in energized tooth</span><strong>{shownSpmRun.toothMeanBT.toFixed(3)} T</strong></div>
                    <div><span>Mean B across airgap</span><strong>{shownSpmRun.airgapMeanBT.toFixed(3)} T</strong></div>
                    <div><span>Useful airgap flux / depth</span><strong>{(shownSpmRun.airgapFluxPerDepthWbPerM * 1e3).toFixed(2)} mWb/m</strong></div>
                    <div><span>Tooth area ≥ 1.60 T</span><strong className={shownSpmRun.toothSaturatedFraction > 0.05 ? 'is-hot' : ''}>{(shownSpmRun.toothSaturatedFraction * 100).toFixed(1)}%</strong></div>
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
                          <strong>{run.airgapMeanBT.toFixed(2)} T gap</strong>
                        </button>
                      ))}
                  </div>
                </>
              ) : null}
              {spmBaselineRun && spmHighRun && spmFluxGainPct !== null ? (
                <section className="iron-tooth-insight iron-spm-insight">
                  <p className="learning-kicker">Two sources, one saturated path</p>
                  <h3>The magnet produces useful flux before copper spends a watt.</h3>
                  <div>
                    <span><b>{(spmBaselineRun.airgapFluxPerDepthWbPerM * 1e3).toFixed(2)}</b> mWb/m at 0 A</span>
                    <span><b>+{spmFluxGainPct.toFixed(0)}%</b> flux at {SPM_HIGH_CURRENT_A} A</span>
                    <span><b>{(spmHighRun.toothSaturatedFraction * 100).toFixed(0)}%</b> tooth saturated</span>
                  </div>
                  <p>The N42 pole supplies the baseline airgap field. Reinforcing ampere-turns add flux until the M350-50A tooth approaches its B–H knee, after which added current buys progressively less torque-producing field.</p>
                </section>
              ) : (
                <section className="iron-tooth-insight is-pending">
                  <p className="learning-kicker">Separate the two field sources</p>
                  <h3>Solve 0 A and {SPM_HIGH_CURRENT_A} A.</h3>
                  <p>The first frame is magnet-only. The second adds reinforcing winding MMF through the same airgap and tooth.</p>
                </section>
              )}
            </section>
          ) : (
            <section className="iron-saturation-status-empty">
              <p className="learning-kicker">SPM operating point</p>
              <h2>Awaiting the magnet-only frame</h2>
              <p>The right panel will separate permanent-magnet baseline flux from the extra field supplied by copper.</p>
              <ol>
                <li><span>1</span> N42 drives flux at 0 A</li>
                <li><span>2</span> Reinforcing NI raises the operating point</li>
                <li><span>3</span> M350-50A tooth saturation limits the gain</li>
              </ol>
            </section>
          )
        ) : toothPhaseOpen ? (
          toothRuns.length ? (
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
                    <div><span>Coil magnetomotive force</span><strong>{(shownToothRun.currentA * shownToothRun.data.coil_turns).toLocaleString()} A·turn</strong></div>
                    <div><span>Mean B in energized tooth</span><strong>{shownToothRun.toothMeanBT.toFixed(3)} T</strong></div>
                    <div><span>Mean B at tooth tip</span><strong className={shownToothRun.toothTipMeanBT >= 1.6 ? 'is-hot' : ''}>{shownToothRun.toothTipMeanBT.toFixed(3)} T</strong></div>
                    <div><span>Mean B across airgap</span><strong>{shownToothRun.airgapMeanBT.toFixed(3)} T</strong></div>
                    <div><span>Useful airgap flux / depth</span><strong>{(shownToothRun.airgapFluxPerDepthWbPerM * 1e3).toFixed(2)} mWb/m</strong></div>
                    <div><span>Tooth area ≥ 1.60 T</span><strong className={shownToothRun.toothSaturatedFraction > 0.05 ? 'is-hot' : ''}>{(shownToothRun.toothSaturatedFraction * 100).toFixed(1)}%</strong></div>
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
                          <strong>{run.airgapMeanBT.toFixed(2)} T gap</strong>
                        </button>
                      ))}
                  </div>
                </>
              ) : null}
              {toothCurrentMultiplier && toothFluxMultiplier && toothLowRun && toothHighRun ? (
                <section className="iron-tooth-insight">
                  <p className="learning-kicker">Why motors care</p>
                  <h3>More current stops buying proportional useful flux.</h3>
                  <div>
                    <span><b>{toothCurrentMultiplier.toFixed(0)}×</b> current</span>
                    <span><b>{(toothCurrentMultiplier ** 2).toFixed(0)}×</b> copper-loss trend</span>
                    <span><b>{toothFluxMultiplier.toFixed(1)}×</b> airgap flux</span>
                  </div>
                  <p>The tooth approaches saturation, so extra ampere-turns increasingly become copper heat instead of proportional airgap field. In a motor that means diminishing torque per added ampere.</p>
                </section>
              ) : (
                <section className="iron-tooth-insight is-pending">
                  <p className="learning-kicker">Compare two operating points</p>
                  <h3>Solve 1 A and {TOOTH_HIGH_CURRENT_A} A.</h3>
                  <p>Then compare current, the I² copper-loss trend, local tooth saturation, and useful flux crossing the airgap.</p>
                </section>
              )}
            </section>
          ) : (
            <section className="iron-saturation-status-empty">
              <p className="learning-kicker">Motor consequence</p>
              <h2>Awaiting the 1 A tooth frame</h2>
              <p>The right panel will separate what the winding spends from what the motor gets.</p>
              <ol>
                <li><span>1</span> Current × turns creates magnetomotive force</li>
                <li><span>2</span> M350-50A carries flux down the tooth</li>
                <li><span>3</span> Useful flux crosses the airgap</li>
              </ol>
            </section>
          )
        ) : runs.length ? (
          <section className="iron-saturation-results" aria-label="Solved material response">
            <header><div><p className="learning-kicker">Solved B–H sweep</p><h2>The M350-50A curve bends; constant μ does not survive the knee.</h2></div><span>{runs.length} run{runs.length === 1 ? '' : 's'}</span></header>
            <BhPlot runs={runs} curve={curve} activeCurrentA={currentRun?.currentA ?? shownRun?.currentA ?? null} onSelect={setCurrentA} />
            {shownRun ? (
              <section className="iron-saturation-readout">
                <div><span>Mean H in M350-50A</span><strong>{(shownRun.meanHApm / 1000).toFixed(2)} kA/m</strong></div>
                <div><span>Mean B in M350-50A</span><strong>{shownRun.meanBT.toFixed(3)} T</strong></div>
                <div><span>Effective μ<sub>r</sub></span><strong>{shownRun.effectiveMuRel.toFixed(0)}</strong></div>
                <div><span>Iron area ≥ 1.60 T</span><strong className={shownRun.saturatedFraction > 0.05 ? 'is-hot' : ''}>{(shownRun.saturatedFraction * 100).toFixed(1)}%</strong></div>
                <div><span>Nonlinear iterations</span><strong>{shownRun.data.metrics?.nonlinear_iterations ?? '—'}</strong></div>
              </section>
            ) : null}
          </section>
        ) : (
          <section className="iron-saturation-status-empty">
            <p className="learning-kicker">Solved material response</p>
            <h2>Awaiting the 10 A frame</h2>
            <p>The B–H curve, effective permeability, and local saturated fraction will appear here without covering the field view.</p>
            <ol>
              <li><span>1</span> Establish 10 A</li>
              <li><span>2</span> Approach the knee at 100 A</li>
              <li><span>3</span> Drive saturation at 800 A</li>
            </ol>
          </section>
        )}

        {lessonStage === 'solve' && !toothPhaseOpen && !spmPhaseOpen ? (
          <section className="iron-saturation-equation-card">
            <header><span>AMPÈRE PATH</span><strong>probe r = 17 mm</strong></header>
            <div className="iron-saturation-equation"><span>H</span><b>≈</b><span className="iron-saturation-fraction"><i>I</i><i>2πr</i></span></div>
            <p>Current sets H around the ring. M350-50A’s B–H curve—not a constant μ—sets B.</p>
          </section>
        ) : null}

        {lessonStage === 'solve' && (toothPhaseOpen || spmPhaseOpen) ? (
          <section className="iron-saturation-equation-card iron-tooth-equation-card">
            <header><span>{spmPhaseOpen ? 'SPM MOTOR FIELD PATH' : 'MOTOR FIELD PATH'}</span><strong>N = 400 turns</strong></header>
            <div className="iron-saturation-equation">
              <span>ℱ</span><b>=</b><span>{spmPhaseOpen ? 'ℱPM + NI' : 'NI'}</span>
            </div>
            <p>{spmPhaseOpen
              ? 'The N42 pole supplies permanent-magnet MMF; reinforcing winding MMF raises the shared tooth and airgap operating point.'
              : 'The winding supplies magnetomotive force. The tooth and yoke carry flux; the airgap is where that field can act on the rotor.'}</p>
          </section>
        ) : null}

        {quizOpen ? (
          <section className="iron-saturation-takeaway"><p className="learning-kicker">Takeaway</p><h2>Motor teeth turn ampere-turns into useful airgap flux—until they saturate.</h2><p>Before the knee, added current efficiently strengthens the airgap field. After the tooth tip saturates, copper loss rises much faster than useful flux and torque potential.</p></section>
        ) : null}
      </aside>
      ) : null}
    </main>
  );
};
