import React from 'react';
import type { AirgapTaxFieldData } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { MeshViewer } from './MeshViewer';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
import './learning.css';
import './airgap-tax.css';

interface LearningLessonTwoAirgapTaxProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'airgap' | 'steel' | 'magnet';
type FieldDisplayMode = 'lines' | 'density';
type LessonTwoProgressStepId = 'predict' | 'solve' | 'check';

const LESSON_TWO_GOALS: Record<LessonTwoProgressStepId, { title: string; detail: string }> = {
  predict: {
    title: 'Find the reluctance bottleneck',
    detail: 'Predict which section consumes most of the magnetic loop’s driving force.',
  },
  solve: {
    title: 'Measure the airgap tax',
    detail: 'Solve a wide gap, halve it, then compare total flux across both frames.',
  },
  check: {
    title: 'Explain the trend',
    detail: 'Use the solved frames to explain why a shorter airgap carries more flux.',
  },
};

interface SolveRun {
  gapMm: number;
  gapBT: number;
  fluxMicroWb: number;
  data: AirgapTaxFieldData;
}

interface AirgapFluxPlotProps {
  runs: SolveRun[];
  activeGapMm: number | null;
  onSelect: (gapMm: number) => void;
}

const DEFAULT_GAP_MM = 6;
const POLE_FACE_AREA_MM2 = 120;
const IRON_PATH_MM = 80;
const IRON_RELATIVE_PERMEABILITY = 1000;
const MAGNET_LENGTH_MM = 36;
const MAGNET_REMANENCE_T = 1.30;
const MAGNET_RELATIVE_PERMEABILITY = 1.05;

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'airgap-dominates',
    prompt: 'Why does a short airgap dominate the reluctance budget?',
    options: [
      'Air has far lower permeability than steel',
      'The airgap is physically the longest part',
      'Steel blocks magnetic flux',
    ],
    correctIndex: 0,
    explanation: 'Air has roughly the permeability of free space, while unsaturated steel is hundreds to thousands of times more permeable.',
  },
  {
    id: 'two-gaps',
    prompt: 'This loop crosses two equal airgaps. What gap length belongs in the series budget?',
    options: ['g', '2g', 'g / 2'],
    correctIndex: 1,
    explanation: 'The flux crosses both gaps in series, so their reluctances add: g + g = 2g.',
  },
  {
    id: 'shrink-gap',
    prompt: 'What should happen when the two airgaps are made smaller?',
    options: [
      'Loop reluctance falls and flux rises',
      'Loop reluctance rises and flux falls',
      'Only the mesh changes',
    ],
    correctIndex: 0,
    explanation: 'Because reluctance scales with path length, a smaller gap makes the magnetic loop easier to drive.',
  },
];

const formatMicroWb = (fluxWb: number) => `${(fluxWb * 1e6).toFixed(1)} µWb`;

const gapReluctance = (gapMm: number) => {
  const mu0 = 4 * Math.PI * 1e-7;
  const lengthM = 2 * gapMm * 1e-3;
  const areaM2 = POLE_FACE_AREA_MM2 * 1e-6;
  return lengthM / (mu0 * areaM2);
};

const gapMmfShare = (gapMm: number) => {
  const equivalentGapMm = 2 * gapMm;
  const equivalentIronMm = IRON_PATH_MM / IRON_RELATIVE_PERMEABILITY;
  return equivalentGapMm / (equivalentGapMm + equivalentIronMm);
};

const handModelFluxMicroWb = (gapMm: number) => {
  const equivalentMagnetMm = MAGNET_LENGTH_MM / MAGNET_RELATIVE_PERMEABILITY;
  const equivalentGapMm = 2 * gapMm;
  const equivalentIronMm = IRON_PATH_MM / IRON_RELATIVE_PERMEABILITY;
  const predictedBT = MAGNET_REMANENCE_T * equivalentMagnetMm
    / (equivalentMagnetMm + equivalentGapMm + equivalentIronMm);
  return predictedBT * POLE_FACE_AREA_MM2;
};

const AirgapFluxPlot: React.FC<AirgapFluxPlotProps> = ({ runs, activeGapMm, onSelect }) => {
  const sortedRuns = [...runs].sort((left, right) => left.gapMm - right.gapMm);
  const width = 360;
  const height = 250;
  const margin = { top: 28, right: 18, bottom: 52, left: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xMin = 0.5;
  const xMax = 8;
  const maxFlux = Math.max(
    ...sortedRuns.flatMap((run) => [run.fluxMicroWb, handModelFluxMicroWb(run.gapMm)]),
    1,
  );
  const yMax = Math.max(20, Math.ceil((maxFlux * 1.12) / 20) * 20);
  const xTicks = [0.5, 2, 4, 6, 8];
  const yTicks = Array.from({ length: 5 }, (_, index) => (yMax / 4) * index);
  const xFor = (gap: number) => margin.left + ((gap - xMin) / (xMax - xMin)) * plotWidth;
  const yFor = (flux: number) => margin.top + plotHeight - (flux / yMax) * plotHeight;
  const pointPath = sortedRuns.map((run) => `${xFor(run.gapMm)},${yFor(run.fluxMicroWb)}`).join(' ');
  const modelPointPath = sortedRuns.map((run) => `${xFor(run.gapMm)},${yFor(handModelFluxMicroWb(run.gapMm))}`).join(' ');
  const activeRun = sortedRuns.find((run) => activeGapMm !== null && Math.abs(activeGapMm - run.gapMm) < 0.01) ?? null;
  const activeModelFlux = activeRun ? handModelFluxMicroWb(activeRun.gapMm) : null;
  const activeDifferencePct = activeRun && activeModelFlux
    ? ((activeRun.fluxMicroWb - activeModelFlux) / activeModelFlux) * 100
    : null;

  return (
    <div className="airgap-tax-plot-wrap">
      <div className="airgap-tax-plot-legend" aria-label="Plot legend">
        <span className="is-fem">2D FEM solver</span>
        <span className="is-model">1D equation</span>
      </div>
      <svg
        className="airgap-tax-flux-plot"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Total flux through the north face plotted against airgap length"
      >
        <g className="airgap-tax-plot-grid">
          {yTicks.map((tick) => (
            <line key={`y-grid-${tick}`} x1={margin.left} y1={yFor(tick)} x2={width - margin.right} y2={yFor(tick)} />
          ))}
          {xTicks.map((tick) => (
            <line key={`x-grid-${tick}`} x1={xFor(tick)} y1={margin.top} x2={xFor(tick)} y2={height - margin.bottom} />
          ))}
        </g>
        <g className="airgap-tax-plot-axes">
          <line x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
          <line x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
        </g>
        <g className="airgap-tax-plot-ticks">
          {yTicks.map((tick) => (
            <text key={`y-tick-${tick}`} x={margin.left - 12} y={yFor(tick) + 4} textAnchor="end">{tick.toFixed(0)}</text>
          ))}
          {xTicks.map((tick) => (
            <text key={`x-tick-${tick}`} x={xFor(tick)} y={height - margin.bottom + 22} textAnchor="middle">{tick.toFixed(1)}</text>
          ))}
        </g>
        <text className="airgap-tax-plot-axis-title is-y" x={14} y={margin.top + plotHeight / 2} transform={`rotate(-90 14 ${margin.top + plotHeight / 2})`} textAnchor="middle">
          Total flux Φ (µWb)
        </text>
        <text className="airgap-tax-plot-axis-title" x={margin.left + plotWidth / 2} y={height - 10} textAnchor="middle">
          Each airgap g (mm)
        </text>
        {sortedRuns.length > 1 ? (
          <>
            <polyline className="airgap-tax-plot-line is-model" points={modelPointPath} />
            <polyline className="airgap-tax-plot-line is-fem" points={pointPath} />
          </>
        ) : null}
        <g className="airgap-tax-model-points" aria-hidden="true">
          {sortedRuns.map((run) => (
            <circle
              key={run.gapMm}
              cx={xFor(run.gapMm)}
              cy={yFor(handModelFluxMicroWb(run.gapMm))}
              r="4"
            />
          ))}
        </g>
        <g className="airgap-tax-plot-points">
          {sortedRuns.map((run) => {
            const active = activeGapMm !== null && Math.abs(activeGapMm - run.gapMm) < 0.01;
            const x = xFor(run.gapMm);
            const y = yFor(run.fluxMicroWb);
            return (
              <g
                key={run.gapMm}
                className={active ? 'is-active' : ''}
                role="button"
                tabIndex={0}
                aria-label={`${run.gapMm.toFixed(1)} millimeter airgap, ${run.fluxMicroWb.toFixed(1)} microwebers total flux`}
                onClick={() => onSelect(run.gapMm)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelect(run.gapMm);
                }}
              >
                <circle className="airgap-tax-plot-hit" cx={x} cy={y} r="18" />
                <circle className="airgap-tax-plot-dot" cx={x} cy={y} r={active ? 7 : 5} />
                <text className="airgap-tax-plot-value" x={x} y={y - 13} textAnchor="middle">{run.fluxMicroWb.toFixed(1)} µWb</text>
              </g>
            );
          })}
        </g>
      </svg>
      {activeRun && activeModelFlux !== null && activeDifferencePct !== null ? (
        <div className="airgap-tax-plot-comparison">
          <span>Selected g = {activeRun.gapMm.toFixed(1)} mm</span>
          <strong>FEM {activeRun.fluxMicroWb.toFixed(1)} µWb</strong>
          <strong>1D {activeModelFlux.toFixed(1)} µWb</strong>
          <em>{activeDifferencePct > 0 ? '+' : ''}{activeDifferencePct.toFixed(1)}%</em>
        </div>
      ) : null}
      <p>FEM includes leakage and fringing; the 1D equation assumes one uniform, leak-free flux tube. Click a FEM point to restore its field frame.</p>
    </div>
  );
};

const AirgapFixtureDiagram: React.FC<{ gapMm: number; highlight?: boolean }> = ({ gapMm, highlight = true }) => {
  const visualGap = 22 + gapMm * 4;
  const magnetLeft = 270;
  const magnetWidth = 300;
  const magnetRight = magnetLeft + magnetWidth;
  const leftInner = magnetLeft - visualGap;
  const rightInner = magnetRight + visualGap;
  return (
    <svg className="airgap-tax-fixture" viewBox="0 0 840 500" role="img" aria-label="Bar magnet inside a steel return path with two equal airgaps">
      <defs>
        <marker id="airgapDimensionArrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto-start-reverse">
          <path d="M8,0 L0,4 L8,8 Z" fill="#67e8f9" />
        </marker>
      </defs>
      <path
        className="airgap-tax-core"
        d={`M${leftInner - 75} 338 V105 H${rightInner + 75} V338 H${rightInner} V180 H${leftInner} V338 Z`}
        fillRule="evenodd"
      />
      <g className="airgap-tax-magnet">
        <rect x={magnetLeft} y="285" width={magnetWidth / 2} height="106" rx="5" className="is-south" />
        <rect x={magnetLeft + magnetWidth / 2} y="285" width={magnetWidth / 2} height="106" rx="5" className="is-north" />
        <text x={magnetLeft + 75} y="350">S</text>
        <text x={magnetLeft + 225} y="350">N</text>
      </g>
      <g className={`airgap-tax-gaps${highlight ? ' is-highlighted' : ''}`}>
        <rect x={leftInner} y="300" width={visualGap} height="74" />
        <line className="airgap-tax-gap-boundary" x1={leftInner} y1="292" x2={leftInner} y2="382" />
        <line className="airgap-tax-gap-boundary" x1={magnetLeft} y1="292" x2={magnetLeft} y2="382" />
        <line
          className="airgap-tax-gap-measure"
          x1={leftInner + 6}
          y1="337"
          x2={magnetLeft - 6}
          y2="337"
          markerStart="url(#airgapDimensionArrow)"
          markerEnd="url(#airgapDimensionArrow)"
        />
        <rect x={magnetRight} y="300" width={visualGap} height="74" />
        <line className="airgap-tax-gap-boundary" x1={magnetRight} y1="292" x2={magnetRight} y2="382" />
        <line className="airgap-tax-gap-boundary" x1={rightInner} y1="292" x2={rightInner} y2="382" />
        <line
          className="airgap-tax-gap-measure"
          x1={magnetRight + 6}
          y1="337"
          x2={rightInner - 6}
          y2="337"
          markerStart="url(#airgapDimensionArrow)"
          markerEnd="url(#airgapDimensionArrow)"
        />
      </g>
      <g className="airgap-tax-gap-labels">
        <text x={(leftInner + magnetLeft) / 2} y="420">
          <tspan x={(leftInner + magnetLeft) / 2}>airgap</tspan>
          <tspan x={(leftInner + magnetLeft) / 2} dy="22">g = {gapMm.toFixed(1)} mm</tspan>
        </text>
        <text x={(magnetRight + rightInner) / 2} y="420">
          <tspan x={(magnetRight + rightInner) / 2}>airgap</tspan>
          <tspan x={(magnetRight + rightInner) / 2} dy="22">g = {gapMm.toFixed(1)} mm</tspan>
        </text>
      </g>
      <path className="airgap-tax-loop-arrow" d={`M${magnetRight - 20} 270 H${rightInner + 30} V145 H${leftInner - 30} V270 H${magnetLeft + 20}`} />
      <text className="airgap-tax-loop-label" x="420" y="80">ONE CLOSED FLUX LOOP</text>
    </svg>
  );
};

export const LearningLessonTwoAirgapTax: React.FC<LearningLessonTwoAirgapTaxProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = React.useState<Prediction | null>(null);
  const [gapMm, setGapMm] = React.useState(DEFAULT_GAP_MM);
  const [runs, setRuns] = React.useState<SolveRun[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [fieldDisplayMode, setFieldDisplayMode] = React.useState<FieldDisplayMode>('lines');
  const [showMesh, setShowMesh] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(false);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const [comparisonReviewed, setComparisonReviewed] = React.useState(false);
  const previousRunCountRef = React.useRef(0);
  const comparisonWasReadyRef = React.useRef(false);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();
  const lessonComplete = isLessonComplete('airgap-tax');

  const predictionCorrect = prediction === 'airgap';
  const latestRun = runs[0] ?? null;
  const currentRun = runs.find((run) => Math.abs(run.gapMm - gapMm) < 0.01) ?? null;
  const distinctGaps = new Set(runs.map((run) => run.gapMm.toFixed(2)));
  const widestGap = runs.length ? Math.max(...runs.map((run) => run.gapMm)) : 0;
  const narrowestGap = runs.length ? Math.min(...runs.map((run) => run.gapMm)) : Infinity;
  const comparisonReady = distinctGaps.size >= 2 && narrowestGap <= widestGap / 2 + 0.01;
  const suggestedHalfGapMm = Math.max(0.5, (widestGap || DEFAULT_GAP_MM) / 2);
  const share = gapMmfShare(gapMm);
  const activeProgressStepId: LessonTwoProgressStepId = quizOpen
    ? 'check'
    : lessonStage === 'design' ? 'predict' : 'solve';

  const selectProgressStep = React.useCallback((stepId: string) => {
    const next = stepId as LessonTwoProgressStepId;
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    if (next === 'predict') {
      setQuizOpen(false);
      onStageChange?.('design');
    } else if (next === 'solve' && predictionCorrect) {
      setQuizOpen(false);
      onStageChange?.('solve');
    } else if (next === 'check' && comparisonReviewed) {
      onStageChange?.('solve');
      setQuizOpen(true);
    }
  }, [comparisonReviewed, onStageChange, predictionCorrect]);

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'solve', label: 'Airgap lab', complete: comparisonReviewed, available: predictionCorrect },
    { id: 'check', label: 'Check', complete: quizPassed, available: comparisonReviewed },
  ], [comparisonReviewed, predictionCorrect, quizPassed]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 2,
    lessonCount: 10,
    title: 'Close the Loop',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const currentGoal = LESSON_TWO_GOALS[activeProgressStepId];
  const completedStepCount = lessonProgressSteps.filter((item) => item.complete).length;

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('airgap-tax', true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  React.useEffect(() => {
    const previousRunCount = previousRunCountRef.current;
    if (lessonStage === 'solve' && previousRunCount === 0 && runs.length === 1) {
      setSolveInspectorOpen(false);
      setLabControlsOpen(true);
    }
    previousRunCountRef.current = runs.length;
  }, [lessonStage, runs.length]);

  React.useEffect(() => {
    if (comparisonReady && !comparisonWasReadyRef.current) {
      setComparisonReviewed(false);
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
    }
    comparisonWasReadyRef.current = comparisonReady;
  }, [comparisonReady]);

  const setStage = (next: 'design' | 'solve') => {
    setQuizOpen(false);
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    onStageChange?.(next);
  };

  const solveGap = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await solveClient.fetchAirgapTaxSolve(gapMm);
      const metrics = data.metrics;
      if (!metrics) throw new Error('The solver returned no magnetic-circuit measurements.');
      const run: SolveRun = {
        gapMm,
        gapBT: metrics.working_gap_mean_b_t,
        fluxMicroWb: (metrics.north_face_flux_wb ?? 0) * 1e6,
        data,
      };
      setRuns((previous) => [run, ...previous.filter((item) => Math.abs(item.gapMm - gapMm) >= 0.01)]);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The magnetic-field solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const choosePrediction = (value: Prediction) => {
    setPrediction(value);
  };

  const handleLabPrimary = () => {
    if (!runs.length) {
      void solveGap();
      return;
    }
    if (!comparisonReady) {
      if (currentRun) {
        setSolveInspectorOpen(false);
        setLabControlsOpen(true);
      }
      else void solveGap();
      return;
    }
    if (!comparisonReviewed) {
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
      return;
    }
    if (!currentRun) {
      void solveGap();
      return;
    }
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    setQuizOpen(true);
  };

  const labPrimaryLabel = busy
    ? 'Meshing + solving…'
    : !runs.length
      ? 'Solve wide-gap baseline'
      : !comparisonReady
        ? currentRun
          ? 'Adjust the airgap'
          : `Solve ${gapMm.toFixed(1)} mm gap`
        : !comparisonReviewed
          ? 'Review comparison'
          : currentRun
            ? 'Continue to Check'
          : `Plot ${gapMm.toFixed(1)} mm gap`;

  const labInsight = !runs.length
    ? 'Start wide, then halve the gap. Keep the magnet and steel unchanged.'
    : !comparisonReady
      ? 'One frame is evidence. A second frame reveals the airgap trend.'
      : !comparisonReviewed
        ? 'The smaller gap carries more flux. Review the comparison before the check.'
        : 'You reviewed the evidence. Now explain why the smaller gap carries more flux.';

  const continueToCheck = () => {
    setComparisonReviewed(true);
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    setQuizOpen(true);
  };

  const renderSolvedViewer = (run: SolveRun) => (
    <div className="airgap-tax-viewer">
      <div className="mesh-viewer-header airgap-tax-visual-header">
        <div className="mesh-viewer-title">
          <h3>Magnet + steel return path</h3>
        </div>
        <div className="airgap-tax-view-toggle" role="group" aria-label="Field visualization">
          <button
            type="button"
            className={fieldDisplayMode === 'lines' ? 'is-active' : ''}
            onClick={() => setFieldDisplayMode('lines')}
            aria-pressed={fieldDisplayMode === 'lines'}
          >
            <span className="is-line" aria-hidden="true" /> Flux lines
          </button>
          <button
            type="button"
            className={fieldDisplayMode === 'density' ? 'is-active' : ''}
            onClick={() => setFieldDisplayMode('density')}
            aria-pressed={fieldDisplayMode === 'density'}
          >
            <span className="is-density" aria-hidden="true" /> |B| map
          </button>
          <button
            type="button"
            className={showMesh ? 'is-active' : ''}
            onClick={() => setShowMesh((visible) => !visible)}
            aria-pressed={showMesh}
          >
            <span className="is-mesh" aria-hidden="true" /> Mesh
          </button>
        </div>
      </div>
      <MeshViewer
        meshData={run.data}
        embedded
        compactEmbedded
        toolbarMode="zoom-only"
        toolbarLabel={fieldDisplayMode === 'lines' ? 'Flux lines' : 'Flux density |B|'}
        showMeshEdges={showMesh}
        showFieldIntensity={fieldDisplayMode === 'density'}
        smoothFieldIntensity
        fieldLinesVisible={fieldDisplayMode === 'lines'}
        animateFieldArrows={fieldDisplayMode === 'lines'}
        viewportPanEnabled={false}
        pointLabels={[
          { xMm: -9, yMm: 0, label: 'S', tone: 'south' },
          { xMm: 9, yMm: 0, label: 'N', tone: 'north' },
        ]}
        measurementGates={[
          {
            x1Mm: 18 + run.gapMm / 2,
            y1Mm: -5,
            x2Mm: 18 + run.gapMm / 2,
            y2Mm: 5,
            labelXmm: 31 + run.gapMm,
            labelYmm: 0,
            label: 'Airgap',
            detail: `${run.gapMm.toFixed(1)} mm`,
          },
        ]}
      />
    </div>
  );

  return (
    <main
      className={`learning-shell learning-lesson-shell airgap-tax-shell is-${lessonStage}-stage${quizOpen ? ' is-quiz-open' : ''}`}
    >
      {lessonStage === 'solve' && !quizOpen && labControlsOpen ? (
      <aside
        className="learning-control-panel airgap-tax-control-panel"
      >
        <button
          type="button"
          className="airgap-tax-drawer-close"
          onClick={() => setLabControlsOpen(false)}
          aria-label="Close airgap controls"
        >
          ×
        </button>

        <section className="learning-control-section">
          <p className="airgap-tax-panel-kicker">
            Lab setup · {lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label}
          </p>
          <h2>Airgap lab</h2>
          <section className="airgap-tax-lab-goal" aria-label="Current lesson goal">
            <span>{completedStepCount}/{lessonProgressSteps.length}</span>
            <div>
              <p>Current goal</p>
              <strong>{currentGoal.title}</strong>
              <small>{currentGoal.detail}</small>
            </div>
          </section>

          {!quizOpen ? (
            <>
              <section className="airgap-tax-control-card">
                <label htmlFor="airgap-tax-slider">
                  <span>Each airgap</span><strong>{gapMm.toFixed(1)} mm</strong>
                </label>
                <input
                  id="airgap-tax-slider"
                  type="range"
                  min="0.5"
                  max="8"
                  step="0.5"
                  value={gapMm}
                  disabled={busy}
                  aria-label={`Each airgap ${gapMm.toFixed(1)} millimeters`}
                  onChange={(event) => setGapMm(Number(event.currentTarget.value))}
                />
                <div className="airgap-tax-gap-scale"><span>0.5</span><span>8 mm</span></div>
                <p className="airgap-tax-control-summary">
                  {currentRun
                    ? `${gapMm.toFixed(1)} mm is already solved.`
                    : `${gapMm.toFixed(1)} mm is ready for a new field solve.`}
                </p>
                {runs.length > 0 && !comparisonReady && currentRun ? (
                  <button
                    type="button"
                    className="airgap-tax-half-button"
                    onClick={() => setGapMm(suggestedHalfGapMm)}
                  >
                    Use the recommended {suggestedHalfGapMm.toFixed(1)} mm gap
                  </button>
                ) : null}
                {error ? <p className="airgap-tax-error">{error}</p> : null}
              </section>

              {lessonStage === 'solve' && comparisonReady ? (
                <p className="airgap-tax-rail-hint">
                  Optional: move the slider to any unplotted gap and add another FEM point before the check.
                </p>
              ) : lessonStage === 'solve' && runs.length > 0 ? (
                <p className="airgap-tax-rail-hint">
                  Set the gap to {suggestedHalfGapMm.toFixed(1)} mm or less, then solve again.
                </p>
              ) : null}

            </>
          ) : null}
        </section>

      </aside>
      ) : null}

      <section className="learning-main-stage airgap-tax-main">
        {quizOpen ? (
          <section className="airgap-tax-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you explain the airgap tax?</h2>
            <p>Use what changed between your solved frames—not a memorized slogan.</p>
            <details className="learning-quiz-reference airgap-tax-inline-quiz-reference">
              <summary>Review solved frames</summary>
              <div>
                <strong>{runs.length} airgap runs captured</strong>
                <p>Open this only when you need to recall the comparison.</p>
              </div>
            </details>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </section>
        ) : lessonStage === 'design' ? (
          <section className="airgap-tax-predict-experience" aria-label="Airgap reluctance prediction">
            <div className="airgap-tax-predict-heading">
              <p className="learning-kicker">Lesson 2 · Predict</p>
              <h1>Where does the magnetic push get spent?</h1>
              <p>Trace one closed loop, then choose its bottleneck.</p>
            </div>
            <div className="airgap-tax-predict-visual">
              <AirgapFixtureDiagram gapMm={DEFAULT_GAP_MM} />
            </div>
            <div className="airgap-tax-predict-question">
              <strong>Which part contributes most of the loop&apos;s reluctance?</strong>
              <div className="airgap-tax-predictions" role="radiogroup" aria-label="Reluctance bottleneck prediction">
                {([
                  ['airgap', 'The two airgaps', 'Short, but low permeability.'],
                  ['steel', 'The steel return path', 'Long, but high permeability.'],
                  ['magnet', 'The permanent magnet', 'The source that drives the loop.'],
                ] as Array<[Prediction, string, string]>).map(([value, label, detail], index) => (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={prediction === value}
                    key={value}
                    className={`${prediction === value ? 'is-selected' : ''}${prediction === value && value === 'airgap' ? ' is-correct' : ''}`}
                    onClick={() => choosePrediction(value)}
                  >
                    <span>{index + 1}</span><div><strong>{label}</strong><small>{detail}</small></div>
                  </button>
                ))}
              </div>
            </div>
            <div className="airgap-tax-predict-response" aria-live="polite">
              {prediction ? (
                <p className={`airgap-tax-feedback${predictionCorrect ? ' is-correct' : ''}`}>
                  {predictionCorrect
                    ? 'Exactly. The flux crosses two low-permeability airgaps in series.'
                    : 'Look past physical length. Compare the permeability of air and steel.'}
                </p>
              ) : <p>Make a prediction before seeing the solved field.</p>}
            </div>
            <button
              type="button"
              className="learning-primary-button airgap-tax-predict-primary"
              disabled={!predictionCorrect}
              onClick={() => setStage('solve')}
            >
              Reveal the airgap tax →
            </button>
            <div className="airgap-tax-predict-footer">
              <div><button type="button" onClick={onBackToCatalog}>← All lessons</button><button type="button" onClick={onBackHome}>Design start</button></div>
              <span>1 of 3 · Predict</span>
            </div>
          </section>
        ) : latestRun ? (
          renderSolvedViewer(currentRun ?? latestRun)
        ) : (
          <section className="airgap-tax-empty-stage">
            <div className="learning-stage-badge"><span>Solve</span><strong>Wide-gap baseline</strong></div>
            <AirgapFixtureDiagram gapMm={gapMm} />
            <div>
              <h2>Start with the wide gap.</h2>
              <p>Adjust the airgap, then run the first field solve.</p>
            </div>
          </section>
        )}

        {lessonStage === 'solve' && !quizOpen ? (
          <div className="airgap-tax-lesson-dock" aria-label="Current airgap experiment controls">
            <div className="airgap-tax-dock-insight">
              <span>Airgap lab</span>
              <strong>{labInsight}</strong>
            </div>
            <div className="airgap-tax-dock-actions">
              <button
                type="button"
                className="airgap-tax-dock-button"
                aria-expanded={labControlsOpen}
                onClick={() => {
                  setLabControlsOpen((open) => !open);
                  setSolveInspectorOpen(false);
                }}
              >
                {labControlsOpen ? 'Done' : 'Adjust airgap'}
              </button>
              <button
                type="button"
                className="airgap-tax-dock-button"
                aria-expanded={solveInspectorOpen}
                onClick={() => {
                  setSolveInspectorOpen((open) => !open);
                  setLabControlsOpen(false);
                }}
              >
                Inspect results
              </button>
              <button
                type="button"
                className="learning-primary-button airgap-tax-dock-primary"
                disabled={busy}
                onClick={handleLabPrimary}
              >
                {labPrimaryLabel}
              </button>
            </div>
          </div>
        ) : quizOpen ? (
          <div className="airgap-tax-lesson-dock airgap-tax-quiz-dock" aria-label="Knowledge check controls">
            <div className="airgap-tax-dock-insight">
              <span>Check</span>
              <strong>{quizPassed ? 'Lesson complete. Continue when you’re ready.' : 'Answer all three questions to complete Lesson 2.'}</strong>
            </div>
            <div className="airgap-tax-dock-actions">
              <button type="button" className="airgap-tax-dock-button" onClick={() => setQuizOpen(false)}>Review experiment</button>
              <button type="button" className="airgap-tax-dock-button" onClick={onBackToCatalog}>Lessons</button>
              {quizPassed || lessonComplete ? (
                <a className="learning-primary-button airgap-tax-dock-primary" href="/tutorials/lesson-3">Next lesson</a>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>
      {lessonStage === 'solve' && !quizOpen && solveInspectorOpen ? (
      <aside className="learning-context-panel airgap-tax-status-panel" aria-label="Lesson evidence and solved results">
        <button type="button" className="airgap-tax-drawer-close" onClick={() => setSolveInspectorOpen(false)} aria-label="Close solved results">×</button>
        <header className="airgap-tax-status-header">
          <p className="learning-kicker">Evidence · Lesson 2</p>
          <h1>Gap comparison</h1>
          <p>Same magnet. Same steel. One shorter air path.</p>
          <div className="learning-progress" aria-label="Lesson completion">
            <span style={{ width: `${(completedStepCount / lessonProgressSteps.length) * 100}%` }} />
          </div>
        </header>

        {runs.length ? (
          <section className="airgap-tax-results" aria-label="Solved gap comparison">
            <header>
              <div>
                <p className="learning-kicker">Solved frames</p>
                <h2>{comparisonReady ? 'The smaller gap carries more flux.' : 'Now halve the gap.'}</h2>
              </div>
              <span>{runs.length} run{runs.length === 1 ? '' : 's'}</span>
            </header>
            <AirgapFluxPlot
              runs={runs}
              activeGapMm={currentRun?.gapMm ?? null}
              onSelect={setGapMm}
            />
            {currentRun?.data.metrics ? (
              <section className="airgap-tax-readout">
                <div><span>Mean |B| in gaps</span><strong>{currentRun.gapBT.toFixed(3)} T</strong></div>
                <div><span>FEM total flux at N face</span><strong>{formatMicroWb(currentRun.data.metrics.north_face_flux_wb ?? 0)}</strong></div>
                <div><span>1D equation prediction</span><strong>{handModelFluxMicroWb(currentRun.gapMm).toFixed(1)} µWb</strong></div>
              </section>
            ) : null}
          </section>
        ) : (
          <section className="airgap-tax-status-empty">
            <p className="learning-kicker">Solved frames</p>
            <h2>Awaiting the wide-gap baseline</h2>
            <p>Solve the wide gap, then halve it. The comparison will appear here.</p>
            <ol>
              <li><span>1</span> Solve the 6.0 mm baseline</li>
              <li><span>2</span> Halve the gap and solve again</li>
            </ol>
          </section>
        )}

        {comparisonReady ? (
          <section className="airgap-tax-inspector-next" aria-label="Continue after reviewing the comparison">
            <span>Evidence reviewed?</span>
            <button type="button" onClick={continueToCheck}>Continue to Check →</button>
          </section>
        ) : null}

        <details className="airgap-tax-inspector-details">
          <summary>Details · reluctance model</summary>
          <div>
          <section className="airgap-tax-recipe">
            <header><span>RELUCTANCE RECIPE</span><strong>two gaps in series</strong></header>
            <div className="airgap-tax-equation">
              <span>ℜ<sub>gap</sub></span><b>=</b>
              <span className="airgap-tax-fraction"><i>2g</i><i>μ<sub>0</sub>A</i></span>
            </div>
            <div className="airgap-tax-flux-equation">
              <strong>Φ<sub>1D</sub> = B<sub>1D</sub>A</strong>
              <span>
                B<sub>1D</sub> = B<sub>r</sub>
                <span className="airgap-tax-inline-fraction">
                  <i>ℓ<sub>m</sub> / μ<sub>r,m</sub></i>
                  <i>ℓ<sub>m</sub> / μ<sub>r,m</sub> + 2g + ℓ<sub>Fe</sub> / μ<sub>r,Fe</sub></i>
                </span>
              </span>
            </div>
            <dl>
              <div><dt>Gap reluctance</dt><dd>{(gapReluctance(gapMm) / 1e6).toFixed(1)} MA/Wb</dd></div>
              <div><dt>Est. MMF spent in air</dt><dd>{(share * 100).toFixed(1)}%</dd></div>
            </dl>
            <div className="airgap-tax-share" aria-label={`${(share * 100).toFixed(1)} percent of MMF spent in air`}>
              <span style={{ width: `${share * 100}%` }}>air</span><i>steel</i>
            </div>
            <p>Model estimate uses an {IRON_PATH_MM} mm steel path at μ<sub>r</sub> ≈ {IRON_RELATIVE_PERMEABILITY}. The field solve includes leakage and fringing.</p>
          </section>
          <p className="airgap-tax-inspector-material">Steel: M350-50A, the same material model used by motor projects.</p>
          </div>
        </details>
      </aside>
      ) : null}
    </main>
  );
};
