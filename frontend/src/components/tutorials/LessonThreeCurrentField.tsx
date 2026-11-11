import React from 'react';
import type { CurrentFieldData } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { oneOf, useLessonResume, useLessonSessionState } from './lessonSession';
import { MeshViewer } from './MeshViewer';
import { CurrentConductor3D } from './CurrentConductor3D';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
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
  LessonTerms,
} from './lab/LessonLab';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
import './learning.css';
import './current-field.css';

interface LearningLessonThreeCurrentFieldProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'ccw' | 'cw' | 'none';
/** The solved 2D field, or an illustrative 3D picture of the same wire. */
type CanvasView = '2d' | '3d';
type LessonThreeProgressStepId = 'predict' | 'direction' | 'scale' | 'check';

const LESSON_THREE_GOALS: Record<LessonThreeProgressStepId, { title: string; detail: string }> = {
  predict: {
    title: 'Predict the field direction',
    detail: 'Use the right-hand rule before looking at a solved field.',
  },
  direction: {
    title: 'Reverse the current',
    detail: 'Solve +8 A and −8 A to see the circulation direction reverse.',
  },
  scale: {
    title: 'Test proportional scaling',
    detail: 'Solve +16 A and compare the probe field with the +8 A frame.',
  },
  check: {
    title: 'Explain current-generated field',
    detail: 'Connect current sign, magnitude, and probe distance to the field.',
  },
};

interface CurrentRun {
  currentA: number;
  probeBT: number;
  data: CurrentFieldData;
}

const LESSON_ID = 'current-field';
const DEFAULT_CURRENT_A = 8;
const WIRE_RADIUS_MM = 5;
const PROBE_RADIUS_MM = 15;
const MU_0 = 4 * Math.PI * 1e-7;

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'current-direction',
    prompt: 'Current points into the screen. Which way does the magnetic field circulate?',
    options: ['Counterclockwise', 'Clockwise', 'Radially outward'],
    correctIndex: 1,
    explanation: 'Point your right thumb into the screen. Your curled fingers point clockwise.',
  },
  {
    id: 'current-scale',
    prompt: 'At the same probe radius, what happens to B when current doubles?',
    options: ['B doubles', 'B halves', 'B stays fixed'],
    correctIndex: 0,
    explanation: 'For a straight conductor, B = μ₀I/(2πr), so B is proportional to current.',
  },
  {
    id: 'current-radius',
    prompt: 'At fixed current, what happens as the probe moves farther from the wire?',
    options: ['B falls as 1/r', 'B rises as r', 'B reverses direction'],
    correctIndex: 0,
    explanation: 'The same field wraps a larger circumference, so its local density falls in proportion to 1/r.',
  },
];

const analyticProbeBT = (currentA: number) => (
  MU_0 * currentA / (2 * Math.PI * PROBE_RADIUS_MM * 1e-3)
);

const formatSignedMilliT = (valueT: number) => {
  const valueMilliT = valueT * 1e3;
  return `${valueMilliT > 0 ? '+' : ''}${valueMilliT.toFixed(3)} mT`;
};

const formatSignedAmps = (currentA: number) => `${currentA > 0 ? '+' : ''}${currentA.toFixed(0)} A`;

const directionForCurrent = (currentA: number) => {
  if (currentA > 0) return 'Counterclockwise';
  if (currentA < 0) return 'Clockwise';
  return 'No field';
};

const CurrentPredictionDiagram: React.FC = () => (
  <svg className="current-field-prediction" viewBox="0 0 820 520" role="img" aria-label="Straight conductor carrying current out of the screen">
    <defs>
      <marker id="currentPredictionArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#67e8f9" />
      </marker>
    </defs>
    <circle cx="410" cy="258" r="158" className="current-field-predict-orbit is-outer" />
    <circle cx="410" cy="258" r="112" className="current-field-predict-orbit" />
    <circle cx="410" cy="258" r="66" className="current-field-predict-orbit" />
    <path d="M568 258 A158 158 0 0 0 410 100" className="current-field-predict-hint" markerEnd="url(#currentPredictionArrow)" />
    <circle cx="410" cy="258" r="54" className="current-field-wire" />
    <circle cx="410" cy="258" r="9" className="current-field-current-dot" />
    <text x="410" y="343" className="current-field-wire-label">+I OUT OF SCREEN</text>
    <text x="410" y="45" className="current-field-loop-label">WHAT DIRECTION DOES B WRAP?</text>
  </svg>
);

interface CurrentPlotProps {
  runs: CurrentRun[];
  activeCurrentA: number | null;
  onSelect: (currentA: number) => void;
}

const CurrentFieldPlot: React.FC<CurrentPlotProps> = ({ runs, activeCurrentA, onSelect }) => {
  const sortedRuns = [...runs].sort((left, right) => left.currentA - right.currentA);
  const width = 360;
  const height = 250;
  const margin = { top: 28, right: 18, bottom: 52, left: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xMin = -16;
  const xMax = 16;
  const yMin = analyticProbeBT(xMin) * 1e3 * 1.12;
  const yMax = -yMin;
  const xTicks = [-16, -8, 0, 8, 16];
  const yTicks = [yMin, yMin / 2, 0, yMax / 2, yMax];
  const xFor = (currentA: number) => margin.left + ((currentA - xMin) / (xMax - xMin)) * plotWidth;
  const yFor = (fieldMilliT: number) => margin.top + plotHeight - ((fieldMilliT - yMin) / (yMax - yMin)) * plotHeight;
  const femPoints = sortedRuns.map((run) => `${xFor(run.currentA)},${yFor(run.probeBT * 1e3)}`).join(' ');
  const modelSamples = Array.from({ length: 33 }, (_, index) => xMin + index);
  const modelPoints = modelSamples.map((currentA) => `${xFor(currentA)},${yFor(analyticProbeBT(currentA) * 1e3)}`).join(' ');
  const activeRun = sortedRuns.find((run) => activeCurrentA !== null && Math.abs(run.currentA - activeCurrentA) < 0.01) ?? null;
  const activeModelBT = activeRun ? analyticProbeBT(activeRun.currentA) : null;
  const differencePct = activeRun && activeModelBT
    ? ((activeRun.probeBT - activeModelBT) / activeModelBT) * 100
    : 0;

  return (
    <div className="current-field-plot-wrap">
      <div className="current-field-plot-legend">
        <span className="is-fem">Solved (2D FEM)</span>
        <span className="is-model">Straight-wire equation</span>
      </div>
      <svg className="current-field-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Signed magnetic field versus conductor current">
        <g className="current-field-plot-grid">
          {yTicks.map((tick) => <line key={`y-${tick}`} x1={margin.left} y1={yFor(tick)} x2={width - margin.right} y2={yFor(tick)} />)}
          {xTicks.map((tick) => <line key={`x-${tick}`} x1={xFor(tick)} y1={margin.top} x2={xFor(tick)} y2={height - margin.bottom} />)}
        </g>
        <g className="current-field-plot-axes">
          <line x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
          <line x1={margin.left} y1={yFor(0)} x2={width - margin.right} y2={yFor(0)} />
        </g>
        <g className="current-field-plot-ticks">
          {yTicks.map((tick) => <text key={`yt-${tick}`} x={margin.left - 12} y={yFor(tick) + 4} textAnchor="end">{tick.toFixed(2)}</text>)}
          {xTicks.map((tick) => <text key={`xt-${tick}`} x={xFor(tick)} y={height - margin.bottom + 22} textAnchor="middle">{tick}</text>)}
        </g>
        <text className="current-field-axis-title" x={14} y={margin.top + plotHeight / 2} transform={`rotate(-90 14 ${margin.top + plotHeight / 2})`} textAnchor="middle">Bθ at 15 mm (mT)</text>
        <text className="current-field-axis-title" x={margin.left + plotWidth / 2} y={height - 10} textAnchor="middle">Current I (A)</text>
        <polyline className="current-field-model-line" points={modelPoints} />
        {sortedRuns.length > 1 ? <polyline className="current-field-fem-line" points={femPoints} /> : null}
        <g className="current-field-points">
          {sortedRuns.map((run) => {
            const active = activeCurrentA !== null && Math.abs(run.currentA - activeCurrentA) < 0.01;
            const x = xFor(run.currentA);
            const y = yFor(run.probeBT * 1e3);
            return (
              <g
                key={run.currentA}
                className={active ? 'is-active' : ''}
                role="button"
                tabIndex={0}
                aria-label={`${run.currentA} amperes, ${formatSignedMilliT(run.probeBT)}`}
                onClick={() => onSelect(run.currentA)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelect(run.currentA);
                }}
              >
                <circle className="current-field-point-hit" cx={x} cy={y} r="18" />
                <circle className="current-field-point-dot" cx={x} cy={y} r={active ? 7 : 5} />
                <text x={x} y={y - 13} textAnchor="middle">{formatSignedMilliT(run.probeBT)}</text>
              </g>
            );
          })}
        </g>
      </svg>
      {activeRun && activeModelBT !== null ? (
        <div className="current-field-plot-comparison">
          <span>Selected I = {formatSignedAmps(activeRun.currentA)}</span>
          <strong>Solved {formatSignedMilliT(activeRun.probeBT)}</strong>
          <strong>Equation {formatSignedMilliT(activeModelBT)}</strong>
          <em>Solved vs equation: {differencePct > 0 ? '+' : ''}{differencePct.toFixed(2)}%</em>
        </div>
      ) : null}
    </div>
  );
};

export const LearningLessonThreeCurrentField: React.FC<LearningLessonThreeCurrentFieldProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = useLessonSessionState<Prediction | null>(
    LESSON_ID, 'prediction', null, oneOf<Prediction>(['ccw', 'cw', 'none']),
  );
  // The currents solved so far (newest first). The fields are not stored; they
  // are solved again when the lesson is reopened.
  const [solvedCurrentsA, setSolvedCurrentsA] = useLessonSessionState<number[]>(
    LESSON_ID, 'solvedCurrentsA', [],
    (value) => Array.isArray(value) && value.length <= 17
      && value.every((current) => typeof current === 'number' && Math.abs(current) <= 16),
  );
  const [currentA, setCurrentA] = React.useState(DEFAULT_CURRENT_A);
  const [runs, setRuns] = React.useState<CurrentRun[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [showFieldLines, setShowFieldLines] = React.useState(true);
  const [showFluxDensity, setShowFluxDensity] = React.useState(false);
  const [showMesh, setShowMesh] = React.useState(false);
  const [canvasView, setCanvasView] = React.useState<CanvasView>('2d');
  // Both panels stay docked beside the canvas, as in the motor workspace.
  const inspectorRef = React.useRef<HTMLElement | null>(null);
  const [inspectorFlash, setInspectorFlash] = React.useState(false);
  const inspectorFlashTimerRef = React.useRef<number | null>(null);
  // The viewer draws its zoom buttons into the dock's title bar.
  const [zoomSlot, setZoomSlot] = React.useState<HTMLSpanElement | null>(null);
  const [comparisonReviewed, setComparisonReviewed] = React.useState(false);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();
  const lessonComplete = isLessonComplete(LESSON_ID);

  const predictionCorrect = prediction === 'ccw';
  const latestRun = runs[0] ?? null;
  const currentRun = runs.find((run) => Math.abs(run.currentA - currentA) < 0.01) ?? null;
  const hasPositive = runs.some((run) => run.currentA > 0);
  const hasNegative = runs.some((run) => run.currentA < 0);
  const solvedMagnitudes = [...new Set(runs.filter((run) => run.currentA !== 0).map((run) => Math.abs(run.currentA)))].sort((a, b) => a - b);
  const hasScaleComparison = solvedMagnitudes.length >= 2
    && solvedMagnitudes[solvedMagnitudes.length - 1] >= solvedMagnitudes[0] * 1.9;
  const hasDirectionComparison = hasPositive && hasNegative;
  const comparisonReady = hasDirectionComparison && hasScaleComparison;
  // A finished lesson reopens with every step available.
  const predictionDone = lessonComplete || predictionCorrect;
  const directionDone = lessonComplete || hasDirectionComparison;
  const comparisonDone = lessonComplete || comparisonReviewed;
  const activeProgressStepId: LessonThreeProgressStepId = quizOpen
    ? 'check'
    : lessonStage === 'design'
      ? 'predict'
      : hasDirectionComparison
        ? 'scale'
        : 'direction';

  const selectProgressStep = React.useCallback((stepId: string) => {
    const next = stepId as LessonThreeProgressStepId;
    if (next === 'predict') {
      setQuizOpen(false);
      onStageChange?.('design');
    } else if (next === 'direction' && predictionDone) {
      setQuizOpen(false);
      onStageChange?.('solve');
    } else if (next === 'scale' && directionDone) {
      setQuizOpen(false);
      onStageChange?.('solve');
    } else if (next === 'check' && comparisonDone) {
      onStageChange?.('solve');
      setQuizOpen(true);
    }
  }, [comparisonDone, directionDone, onStageChange, predictionDone]);

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'direction', label: 'Direction', complete: hasDirectionComparison, available: predictionDone },
    { id: 'scale', label: 'Scale', complete: comparisonReviewed, available: directionDone },
    { id: 'check', label: 'Check', complete: quizPassed, available: comparisonDone },
  ], [comparisonDone, comparisonReviewed, directionDone, hasDirectionComparison, predictionDone, quizPassed]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 3,
    lessonCount: 10,
    title: 'Make a Field with Current',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const currentGoal = LESSON_THREE_GOALS[activeProgressStepId];

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete(LESSON_ID, true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  // Do not leave the flash timer running after the lesson is closed.
  React.useEffect(() => () => {
    if (inspectorFlashTimerRef.current !== null) window.clearTimeout(inspectorFlashTimerRef.current);
  }, []);

  const setStage = (next: 'design' | 'solve') => {
    setQuizOpen(false);
    onStageChange?.(next);
  };

  const solveCurrent = async (requestedCurrentA = currentA) => {
    setBusy(true);
    setError(null);
    try {
      const data = await solveClient.fetchCurrentFieldSolve(requestedCurrentA);
      const probeBT = data.metrics?.probe_tangential_b_t;
      if (probeBT === null || probeBT === undefined) throw new Error('The solver returned no signed probe field.');
      const run: CurrentRun = { currentA: requestedCurrentA, probeBT, data };
      setCurrentA(requestedCurrentA);
      setRuns((previous) => [run, ...previous.filter((item) => Math.abs(item.currentA - requestedCurrentA) >= 0.01)]);
      // A new frame changes the comparison, so it has to be looked at again.
      setComparisonReviewed(false);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The current-field solve failed.');
    } finally {
      setBusy(false);
    }
  };

  React.useEffect(() => {
    if (runs.length > 0) setSolvedCurrentsA(runs.map((run) => run.currentA));
  }, [runs, setSolvedCurrentsA]);

  // Reopened after a reload or a trip to the catalog: back into the lab, with
  // the currents the student had solved solved again, oldest first (each takes
  // well under a second).
  useLessonResume(LESSON_ID, lessonStage, predictionDone ? () => {
    onStageChange?.('solve');
    const currentsA = [...solvedCurrentsA].reverse();
    void (async () => {
      for (const storedCurrentA of currentsA) {
        await solveCurrent(storedCurrentA);
      }
    })();
  } : null);

  // The guided path is +8 A, then −8 A, then +16 A.
  const nextGuidedCurrent = () => {
    if (!hasPositive) return DEFAULT_CURRENT_A;
    if (!hasNegative) return -DEFAULT_CURRENT_A;
    if (!hasScaleComparison) {
      // A student who went straight to 16 A still needs a current of about
      // half that size; recommending 16 A again would solve nothing new.
      const doubled = DEFAULT_CURRENT_A * 2;
      return runs.some((run) => Math.abs(run.currentA - doubled) < 0.01) ? DEFAULT_CURRENT_A : doubled;
    }
    return currentA;
  };

  const shownRun = currentRun ?? latestRun;
  const shownCurrentA = shownRun?.currentA ?? currentA;
  const currentDensityAmm2 = currentA / (Math.PI * WIRE_RADIUS_MM ** 2);
  const guidedCurrentA = nextGuidedCurrent();

  const handleLabPrimary = () => {
    if (!currentRun) {
      // The slider is on a current that has not been solved yet.
      void solveCurrent();
      return;
    }
    if (!comparisonReady) {
      void solveCurrent(guidedCurrentA);
      return;
    }
    if (!comparisonReviewed) {
      // The comparison is already on screen in the Inspect panel: draw the eye
      // to it, then let the next click move on to the check.
      setComparisonReviewed(true);
      inspectorRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      setInspectorFlash(true);
      if (inspectorFlashTimerRef.current !== null) window.clearTimeout(inspectorFlashTimerRef.current);
      inspectorFlashTimerRef.current = window.setTimeout(() => setInspectorFlash(false), 1_600);
      return;
    }
    setQuizOpen(true);
  };

  const labPrimaryLabel = busy
    ? 'Meshing + solving…'
    : !currentRun
      ? `Solve ${formatSignedAmps(currentA)}`
      : !comparisonReady
        ? `Solve recommended ${formatSignedAmps(guidedCurrentA)}`
        : !comparisonReviewed
          ? 'Review comparison'
          : 'Continue to Check';

  const labInsight = !runs.length
    ? 'Current creates a circular field. Start with +8 A.'
    : !hasNegative
      ? 'Now reverse the current. The field should reverse with it.'
      : !hasScaleComparison
        ? 'Direction flipped. Double the current to test field strength.'
        : !comparisonReviewed
          ? 'Three frames reveal the rule. Review the evidence before the check.'
          : 'You reviewed the evidence. Now explain direction and scale.';

  // The canvas controls, in the same dock as the motor workspace. Before the
  // first solve it is shown greyed out, so the canvas keeps its size. The
  // field and mesh layers belong to the 2D solve, so they are greyed out while
  // the 3D picture is shown.
  const renderViewDock = (unsolved: boolean) => {
    const threeD = !unsolved && canvasView === '3d';
    const layersOff = unsolved || threeD;
    const layerTitle = (title: string) => (threeD ? 'Switch to the 2D view to change this' : title);
    return (
      <LessonDock
        tabs={[
          { id: '2d', label: '2D' },
          { id: '3d', label: '3D', disabled: unsolved, title: unsolved ? 'Solve the field first' : 'The same wire and field drawn in 3D' },
        ]}
        tab={threeD ? '3d' : '2d'}
        onTab={setCanvasView}
        end={unsolved ? 'Solve to see the field' : <span ref={setZoomSlot} />}
      >
        <LessonDockGroup label="Show">
          <LessonDockToggle
            pressed={showFieldLines}
            onChange={setShowFieldLines}
            disabled={layersOff}
            title={layerTitle('Lines that follow the direction of the field')}
          >
            Field lines
          </LessonDockToggle>
          <LessonDockToggle
            pressed={showFluxDensity}
            onChange={setShowFluxDensity}
            disabled={layersOff}
            title={layerTitle('Colour by field strength, |B|')}
          >
            Flux density
          </LessonDockToggle>
          <LessonDockToggle
            pressed={showMesh}
            onChange={setShowMesh}
            disabled={layersOff}
            title={layerTitle('The triangles the solver divides the space into')}
          >
            Mesh
          </LessonDockToggle>
        </LessonDockGroup>
      </LessonDock>
    );
  };

  const renderSolvedViewer = (run: CurrentRun) => (
    <LessonLabCanvas className="current-field-viewer">
      <LessonLabViewport
        label={`Straight conductor in air · ${formatSignedAmps(run.currentA)} solved`}
        hint={currentRun ? undefined : `Slider is at ${formatSignedAmps(currentA)}, not solved yet`}
      >
        {canvasView === '3d' ? (
          <CurrentConductor3D currentA={run.currentA} />
        ) : (
          <MeshViewer
            meshData={run.data}
            embedded
            compactEmbedded
            toolbarMode="zoom-only"
            zoomControlsSlot={zoomSlot}
            showMeshEdges={showMesh}
            showFieldIntensity={showFluxDensity}
            smoothFieldIntensity
            fieldLinesVisible={showFieldLines}
            animateFieldArrows={showFieldLines}
            viewportPanEnabled={false}
            pointLabels={[
              { xMm: 0, yMm: 0, label: run.currentA >= 0 ? `⊙ +${run.currentA.toFixed(0)} A` : `⊗ ${run.currentA.toFixed(0)} A`, tone: 'neutral' },
              { xMm: PROBE_RADIUS_MM, yMm: 0, label: 'probe 15 mm', tone: 'neutral' },
            ]}
          />
        )}
      </LessonLabViewport>
      {renderViewDock(false)}
    </LessonLabCanvas>
  );

  const currentStepNumber = Math.max(1, lessonProgressSteps.findIndex((item) => item.id === activeProgressStepId) + 1);
  const goalCard = (
    <LessonGoal step={currentStepNumber} total={lessonProgressSteps.length} title={currentGoal.title} detail={currentGoal.detail} />
  );
  // The lesson's terms sit beside whatever is being read or measured.
  const termsBox = (
    <LessonTerms
      terms={[
        { term: 'Current, I', definition: 'The flow of electric charge along the wire, in amperes (A). ⊙ and a + sign mean it flows toward you, out of the screen; ⊗ and a − sign mean it flows away from you.' },
        { term: 'Right-hand rule', definition: 'Point your right thumb along the current. Your curled fingers show which way the field circles the wire.' },
        { term: 'Flux density, |B|', definition: 'How strong the magnetic field is at one spot, in tesla (T). The fields here are small, so they are shown in millitesla: 1 mT = 0.001 T.' },
        { term: <>B<sub>θ</sub></>, definition: 'The part of the field that points around the wire, along the circle. Positive means counterclockwise, negative means clockwise.' },
        { term: 'Probe', definition: 'The fixed point where the field is read: 15 mm from the centre of the wire.' },
        { term: <>μ<sub>0</sub></>, definition: <>The permeability of free space, 4π × 10<sup>−7</sup> T·m/A. It sets how much field a given current makes in air.</> },
        { term: 'Current density, J', definition: 'Current divided by the cross-section area of the wire, in A/mm². The wire here has a 5 mm radius.' },
        { term: 'FEM', definition: 'Finite element method. The solver divides the space into small triangles (the mesh) and works out the field in each one.' },
      ]}
    />
  );

  const inspectPanel = (
    <LessonLabPanel
      ref={inspectorRef}
      side="inspect"
      kicker="Inspect"
      title={lessonStage === 'design' ? 'Nothing solved yet' : 'Current comparison'}
      summary={lessonStage === 'design'
        ? 'Make your prediction first. The solver’s answer and its measurements appear here in the next step.'
        : 'Sign flips direction. Magnitude sets strength.'}
      label="Lesson evidence and solved results"
      flash={inspectorFlash}
      scrollTopKey={runs.length}
    >
      {lessonStage === 'design' ? (
        <LessonOutline
          steps={lessonProgressSteps.map((item) => ({
            id: item.id,
            label: item.label,
            detail: LESSON_THREE_GOALS[item.id as LessonThreeProgressStepId].detail,
          }))}
          currentId={activeProgressStepId}
        />
      ) : runs.length ? (
        <section className="current-field-results" aria-label="Solved current comparison">
          <header><div><p className="learning-kicker">Solved current sweep</p><h2>{comparisonReady ? 'The field follows the current.' : 'Build the three-frame comparison.'}</h2></div><span>{runs.length} run{runs.length === 1 ? '' : 's'}</span></header>
          <CurrentFieldPlot runs={runs} activeCurrentA={currentRun?.currentA ?? null} onSelect={setCurrentA} />
          {currentRun?.data.metrics ? (
            <section className="current-field-readout">
              <div><span>Solved Bθ at 15 mm</span><strong>{formatSignedMilliT(currentRun.probeBT)}</strong></div>
              <div><span>Field circulation</span><strong>{directionForCurrent(currentRun.currentA)}</strong></div>
              <div><span>Peak |B| near wire</span><strong>{(currentRun.data.metrics.peak_b_t * 1e3).toFixed(3)} mT</strong></div>
            </section>
          ) : null}
        </section>
      ) : (
        <section className="current-field-status-empty">
          <p className="learning-kicker">Solved currents</p><h2>Awaiting the +8 A frame</h2><p>Solve three deliberate currents to reveal direction and scale.</p>
          <ol><li><span>1</span> Solve +8 A</li><li><span>2</span> Reverse to −8 A</li><li><span>3</span> Double to +16 A</li></ol>
        </section>
      )}

      {termsBox}

      {lessonStage === 'solve' ? (
        <details className="current-field-inspector-details">
          <summary>Details · straight-wire equation</summary>
          <section className="current-field-equation-card">
            <header><span>STRAIGHT-WIRE CHECK</span><strong>probe r = 15 mm</strong></header>
            <div className="current-field-equation"><span>B</span><b>=</b><span className="current-field-fraction"><i>μ<sub>0</sub>I</i><i>2πr</i></span></div>
            <dl>
              <div><dt>Current density J at {formatSignedAmps(currentA)}</dt><dd>{currentDensityAmm2 > 0 ? '+' : ''}{currentDensityAmm2.toFixed(3)} A/mm²</dd></div>
              <div><dt>Equation Bθ at 15 mm</dt><dd>{formatSignedMilliT(analyticProbeBT(currentA))}</dd></div>
            </dl>
            <p>Positive Bθ is counterclockwise. Negative Bθ is clockwise.</p>
          </section>
        </details>
      ) : null}
    </LessonLabPanel>
  );

  if (quizOpen) {
    return (
      <LessonLab className="current-field-lab">
        {inspectPanel}
        <LessonLabStage className="is-tall">
          <LessonLabViewport label={`Knowledge check · ${QUIZ.length} questions`} className="is-scroll">
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Check"
          title="Can you connect current to field?"
          label="Knowledge check"
          footer={(
            <LessonNextStep hint={quizPassed ? 'Lesson complete. Continue when you are ready.' : 'Answer all three questions to complete Lesson 3.'}>
              {quizPassed || lessonComplete ? (
                <a className="learning-primary-button" href="/tutorials/lesson-4">Next lesson</a>
              ) : null}
              <div className="lesson-lab-next-row">
                <LessonLink onClick={() => setQuizOpen(false)}>← Review experiment</LessonLink>
                <LessonLink onClick={onBackToCatalog}>All lessons</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <p className="lesson-lab-note">Use the solved direction and scaling, shown on the right, not a memorized motor diagram.</p>
        </LessonLabPanel>
      </LessonLab>
    );
  }

  if (lessonStage === 'design') {
    return (
      <LessonLab className="current-field-lab">
        {inspectPanel}
        <LessonLabStage>
          <LessonLabViewport label="Straight conductor in air · not solved yet" className="is-centered">
            <CurrentPredictionDiagram />
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Predict"
          title="Which way does the field turn?"
          summary="Current points toward you. Predict its circulation before the solver reveals it."
          label="Current field direction prediction"
          footer={(
            <LessonNextStep
              tone={prediction ? (predictionCorrect ? 'good' : 'warn') : undefined}
              hint={prediction
                ? predictionCorrect
                  ? 'Exactly. Thumb toward you; curled fingers move counterclockwise.'
                  : 'Point your right thumb toward you, then follow the curl of your fingers.'
                : 'Make a prediction before seeing the solved field.'}
            >
              <button
                type="button"
                className="learning-primary-button"
                disabled={!predictionCorrect}
                onClick={() => setStage('solve')}
              >
                Reveal the current field →
              </button>
              <div className="lesson-lab-next-row">
                <LessonLink onClick={onBackToCatalog}>← All lessons</LessonLink>
                <LessonLink onClick={onBackHome}>Design start</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <p className="lesson-lab-note"><strong>Follow your curled fingers. Which direction do they point?</strong></p>
          <LessonChoices
            label="Current field direction prediction"
            value={prediction}
            onChange={setPrediction}
            correctId="ccw"
            options={[
              { id: 'ccw', label: 'Counterclockwise', detail: 'Right thumb out; fingers curl this way.' },
              { id: 'cw', label: 'Clockwise', detail: 'The opposite circulation direction.' },
              { id: 'none', label: 'No magnetic field', detail: 'Current would leave the surrounding space unchanged.' },
            ]}
          />
        </LessonLabPanel>
      </LessonLab>
    );
  }

  return (
    <LessonLab className="current-field-lab">
      {inspectPanel}
      <LessonLabStage>
        {shownRun ? (
          renderSolvedViewer(shownRun)
        ) : (
          <LessonLabCanvas>
            <LessonLabViewport label="Straight conductor in air" hint="Not solved yet" className="is-centered">
              <CurrentPredictionDiagram />
            </LessonLabViewport>
            {renderViewDock(true)}
          </LessonLabCanvas>
        )}
      </LessonLabStage>
      <LessonLabPanel
        side="do"
        kicker={`Experiment · ${lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label ?? ''}`}
        title="Current lab"
        label="Current experiment"
        footer={(
          <LessonNextStep hint={labInsight}>
            <button type="button" className="learning-primary-button" disabled={busy} onClick={handleLabPrimary}>
              {labPrimaryLabel}
            </button>
          </LessonNextStep>
        )}
      >
        {goalCard}
        <section className="current-field-control-card">
          <label htmlFor="current-field-slider"><span>Conductor current</span><strong>{formatSignedAmps(currentA)}</strong></label>
          <input id="current-field-slider" type="range" min="-16" max="16" step="2" value={currentA} disabled={busy} aria-label={`Conductor current ${currentA} amperes`} onChange={(event) => setCurrentA(Number(event.currentTarget.value))} />
          <div className="current-field-scale"><span>−16 A</span><span>0</span><span>+16 A</span></div>
          <div className={`current-field-selection-state${currentRun ? ' is-solved' : ' is-pending'}`} aria-live="polite">
            <span>{currentRun ? 'Solved' : 'Pending'}</span>
            <p>{currentRun ? 'This current is already in the comparison.' : 'Solve this current to update the field view.'}</p>
          </div>
        </section>
        <p className="lesson-lab-note">
          {!runs.length
            ? 'One solve reveals the circular field. Reversing current will test the rule.'
            : comparisonReady
              ? 'Optional: add another current after reviewing the three guided frames.'
              : !hasNegative
                ? 'Reverse the current to reveal the direction change.'
                : 'Double the positive current to test proportional scaling.'}
        </p>
        {error ? <p className="lesson-lab-error">{error}</p> : null}
      </LessonLabPanel>
    </LessonLab>
  );
};
