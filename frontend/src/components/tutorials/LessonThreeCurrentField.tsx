import React from 'react';
import type { CurrentFieldData } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { MeshViewer } from './MeshViewer';
import { CurrentConductor3D } from './CurrentConductor3D';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
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
type FieldDisplayMode = 'lines' | 'density';
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
        <span className="is-fem">2D FEM probe</span>
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
        <text className="current-field-axis-title" x={14} y={margin.top + plotHeight / 2} transform={`rotate(-90 14 ${margin.top + plotHeight / 2})`} textAnchor="middle">Signed Bθ at 15 mm (mT)</text>
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
          <span>Selected I = {activeRun.currentA > 0 ? '+' : ''}{activeRun.currentA.toFixed(0)} A</span>
          <strong>FEM {formatSignedMilliT(activeRun.probeBT)}</strong>
          <strong>Equation {formatSignedMilliT(activeModelBT)}</strong>
          <em>{differencePct > 0 ? '+' : ''}{differencePct.toFixed(2)}%</em>
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
  const solveInspectorRef = React.useRef<HTMLElement>(null);
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = React.useState<Prediction | null>(null);
  const [currentA, setCurrentA] = React.useState(DEFAULT_CURRENT_A);
  const [runs, setRuns] = React.useState<CurrentRun[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [fieldDisplayMode, setFieldDisplayMode] = React.useState<FieldDisplayMode>('lines');
  const [showMesh, setShowMesh] = React.useState(false);
  const [showThreeD, setShowThreeD] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(false);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const [comparisonReviewed, setComparisonReviewed] = React.useState(false);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();
  const lessonComplete = isLessonComplete('current-field');

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
  const activeProgressStepId: LessonThreeProgressStepId = quizOpen
    ? 'check'
    : lessonStage === 'design'
      ? 'predict'
      : hasDirectionComparison
        ? 'scale'
        : 'direction';

  const selectProgressStep = React.useCallback((stepId: string) => {
    const next = stepId as LessonThreeProgressStepId;
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    if (next === 'predict') {
      setQuizOpen(false);
      onStageChange?.('design');
    } else if (next === 'direction' && predictionCorrect) {
      setQuizOpen(false);
      onStageChange?.('solve');
    } else if (next === 'scale' && hasDirectionComparison) {
      setQuizOpen(false);
      onStageChange?.('solve');
    } else if (next === 'check' && comparisonReviewed) {
      onStageChange?.('solve');
      setQuizOpen(true);
    }
  }, [comparisonReviewed, hasDirectionComparison, onStageChange, predictionCorrect]);

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'direction', label: 'Direction', complete: hasDirectionComparison, available: predictionCorrect },
    { id: 'scale', label: 'Scale', complete: comparisonReviewed, available: hasDirectionComparison },
    { id: 'check', label: 'Check', complete: quizPassed, available: comparisonReviewed },
  ], [comparisonReviewed, hasDirectionComparison, predictionCorrect, quizPassed]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 3,
    lessonCount: 10,
    title: 'Make a Field with Current',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const currentGoal = LESSON_THREE_GOALS[activeProgressStepId];
  const completedStepCount = lessonProgressSteps.filter((item) => item.complete).length;

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('current-field', true);
  }, [quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  React.useEffect(() => {
    if (solveInspectorOpen) solveInspectorRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [runs, solveInspectorOpen]);

  const setStage = (next: 'design' | 'solve') => {
    setQuizOpen(false);
    setLabControlsOpen(next === 'solve');
    setSolveInspectorOpen(false);
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
      setComparisonReviewed(false);
      setLabControlsOpen(false);
      setSolveInspectorOpen(true);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The current-field solve failed.');
    } finally {
      setBusy(false);
    }
  };

  const nextGuidedCurrent = () => {
    if (!hasPositive) return DEFAULT_CURRENT_A;
    if (!hasNegative) return -DEFAULT_CURRENT_A;
    if (!hasScaleComparison) return DEFAULT_CURRENT_A * 2;
    return currentA;
  };

  const shownRun = currentRun ?? latestRun;
  const shownCurrentA = shownRun?.currentA ?? currentA;
  const currentDensityAmm2 = currentA / (Math.PI * WIRE_RADIUS_MM ** 2);
  const guidedCurrentA = nextGuidedCurrent();

  const continueExperiment = () => {
    const nextCurrentA = nextGuidedCurrent();
    setCurrentA(nextCurrentA);
    setSolveInspectorOpen(false);
    setLabControlsOpen(true);
  };

  const continueToCheck = () => {
    setComparisonReviewed(true);
    setLabControlsOpen(false);
    setSolveInspectorOpen(false);
    setQuizOpen(true);
  };

  const panelSolveLabel = busy
    ? 'Meshing + solving…'
    : currentRun
      ? `${currentA > 0 ? '+' : ''}${currentA.toFixed(0)} A solved`
      : `Solve ${currentA > 0 ? '+' : ''}${currentA.toFixed(0)} A`;

  const labInsight = !runs.length
    ? 'Current creates a circular field. Start with +8 A.'
    : !hasNegative
      ? 'Now reverse the current. The field should reverse with it.'
      : !hasScaleComparison
        ? 'Direction flipped. Double the current to test field strength.'
        : !comparisonReviewed
          ? 'Three frames reveal the rule. Review the evidence before the check.'
          : 'You reviewed the evidence. Now explain direction and scale.';

  return (
    <main
      className={`learning-shell learning-lesson-shell current-field-shell is-${lessonStage}-stage${quizOpen ? ' is-quiz-open' : ''}`}
    >
      {lessonStage === 'solve' && !quizOpen && labControlsOpen ? (
        <aside className="learning-control-panel current-field-control-panel" aria-label="Current experiment controls">
          <button type="button" className="current-field-drawer-close" onClick={() => setLabControlsOpen(false)} aria-label="Close current controls">×</button>
          <section className="learning-control-section">
            <p className="current-field-panel-kicker">Lab setup · {lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label}</p>
            <h2>Current lab</h2>
            <section className="current-field-lab-goal" aria-label="Current lesson goal">
              <span>{completedStepCount}/{lessonProgressSteps.length}</span>
              <div>
                <p>Current goal</p>
                <strong>{currentGoal.title}</strong>
                <small>{currentGoal.detail}</small>
              </div>
            </section>
            <section className="current-field-control-card">
              <label htmlFor="current-field-slider"><span>Conductor current</span><strong>{currentA > 0 ? '+' : ''}{currentA.toFixed(0)} A</strong></label>
              <input id="current-field-slider" type="range" min="-16" max="16" step="2" value={currentA} disabled={busy} aria-label={`Conductor current ${currentA} amperes`} onChange={(event) => setCurrentA(Number(event.currentTarget.value))} />
              <div className="current-field-scale"><span>−16 A</span><span>0</span><span>+16 A</span></div>
              <div className={`current-field-selection-state${currentRun ? ' is-solved' : ' is-pending'}`} aria-live="polite">
                <span>{currentRun ? 'Solved' : 'Pending'}</span>
                <p>{currentRun ? 'This current is already in the comparison.' : 'Solve this current to update the field view.'}</p>
              </div>
              {!comparisonReady && currentRun ? (
                <button type="button" className="current-field-guide-button" disabled={busy} onClick={() => void solveCurrent(guidedCurrentA)}>
                  {busy
                    ? `Solving ${guidedCurrentA > 0 ? '+' : ''}${guidedCurrentA.toFixed(0)} A…`
                    : `Solve recommended ${guidedCurrentA > 0 ? '+' : ''}${guidedCurrentA.toFixed(0)} A`}
                </button>
              ) : (
                <button type="button" className="current-field-panel-solve" disabled={busy || Boolean(currentRun)} onClick={() => void solveCurrent()}>
                  {panelSolveLabel}
                </button>
              )}
              {error ? <p className="current-field-error">{error}</p> : null}
            </section>
            <p className="current-field-rail-hint">
              {comparisonReady
                ? 'Optional: add another current after reviewing the three guided frames.'
                : !hasNegative
                  ? 'Reverse the current to reveal the direction change.'
                  : 'Double the positive current to test proportional scaling.'}
            </p>
          </section>
        </aside>
      ) : null}

      <section className="learning-main-stage current-field-main">
        {quizOpen ? (
          <section className="current-field-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you connect current to field?</h2>
            <p>Use the solved direction and scaling—not a memorized motor diagram.</p>
            <details className="learning-quiz-reference current-field-inline-quiz-reference">
              <summary>Review solved currents</summary>
              <div><strong>{runs.length} current frames captured</strong><p>Open this only when you need to recall the comparison.</p></div>
            </details>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </section>
        ) : lessonStage === 'design' ? (
          <section className="current-field-predict-experience" aria-label="Current field direction prediction">
            <div className="current-field-predict-heading">
              <p className="learning-kicker">Lesson 3 · Predict</p>
              <h1>Which way does the field turn?</h1>
              <p>Current points toward you. Predict its circulation before the solver reveals it.</p>
            </div>
            <div className="current-field-predict-visual"><CurrentPredictionDiagram /></div>
            <div className="current-field-predict-question">
              <strong>Follow your curled fingers. Which direction do they point?</strong>
              <div className="current-field-predictions" role="radiogroup" aria-label="Current field direction prediction">
                {([
                  ['ccw', 'Counterclockwise', 'Right thumb out; fingers curl this way.'],
                  ['cw', 'Clockwise', 'The opposite circulation direction.'],
                  ['none', 'No magnetic field', 'Current would leave the surrounding space unchanged.'],
                ] as Array<[Prediction, string, string]>).map(([value, label, detail], index) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={prediction === value}
                    className={`${prediction === value ? 'is-selected' : ''}${prediction === value && value === 'ccw' ? ' is-correct' : ''}`}
                    onClick={() => setPrediction(value)}
                  >
                    <span>{index + 1}</span><div><strong>{label}</strong><small>{detail}</small></div>
                  </button>
                ))}
              </div>
            </div>
            <div className="current-field-predict-response" aria-live="polite">
              {prediction ? (
                <p className={`current-field-feedback${predictionCorrect ? ' is-correct' : ''}`}>
                  {predictionCorrect
                    ? 'Exactly. Thumb toward you; curled fingers move counterclockwise.'
                    : 'Point your right thumb toward you, then follow the curl of your fingers.'}
                </p>
              ) : <p>Make a prediction before seeing the solved field.</p>}
            </div>
            <button type="button" className="learning-primary-button current-field-predict-primary" disabled={!predictionCorrect} onClick={() => setStage('solve')}>
              Reveal the current field →
            </button>
            <div className="current-field-predict-footer">
              <div><button type="button" onClick={onBackToCatalog}>← All lessons</button><button type="button" onClick={onBackHome}>Design start</button></div>
              <span>1 of 4 · Predict</span>
            </div>
          </section>
        ) : shownRun ? (
          <div className="current-field-viewer">
            <div className="mesh-viewer-header current-field-visual-header">
              <div className="mesh-viewer-title"><h3>Straight conductor in air</h3></div>
              <div className={`current-field-viewer-current${currentRun ? ' is-current' : ' is-pending'}`} aria-live="polite">
                <span>{currentRun ? 'Solved current' : 'Last solved'}</span>
                <strong>{shownCurrentA > 0 ? '+' : ''}{shownCurrentA.toFixed(0)} A</strong>
                {!currentRun ? <em>Pending {currentA > 0 ? '+' : ''}{currentA.toFixed(0)} A</em> : null}
              </div>
              <div className="current-field-view-toggle" role="group" aria-label="Field visualization">
                <button type="button" className={!showThreeD && fieldDisplayMode === 'lines' ? 'is-active' : ''} onClick={() => { setFieldDisplayMode('lines'); setShowThreeD(false); }} aria-pressed={!showThreeD && fieldDisplayMode === 'lines'}><span /> Flux lines</button>
                <button type="button" className={!showThreeD && fieldDisplayMode === 'density' ? 'is-active' : ''} onClick={() => { setFieldDisplayMode('density'); setShowThreeD(false); }} aria-pressed={!showThreeD && fieldDisplayMode === 'density'}><span className="is-density" /> |B| map</button>
                <button type="button" className={!showThreeD && showMesh ? 'is-active' : ''} onClick={() => { setShowMesh((visible) => showThreeD ? true : !visible); setShowThreeD(false); }} aria-pressed={!showThreeD && showMesh}><span className="is-mesh" /> Mesh</button>
                <button type="button" className={showThreeD ? 'is-active' : ''} onClick={() => setShowThreeD(true)} aria-pressed={showThreeD}><span className="is-three" /> 3D</button>
              </div>
            </div>
            {showThreeD ? (
              <CurrentConductor3D currentA={shownCurrentA} />
            ) : (
              <MeshViewer
                meshData={shownRun.data}
                embedded
                compactEmbedded
                toolbarMode="zoom-only"
                toolbarLabel={fieldDisplayMode === 'lines' ? 'Current field' : 'Flux density |B|'}
                showMeshEdges={showMesh}
                showFieldIntensity={fieldDisplayMode === 'density'}
                smoothFieldIntensity
                fieldLinesVisible={fieldDisplayMode === 'lines'}
                animateFieldArrows={fieldDisplayMode === 'lines'}
                viewportPanEnabled={false}
                pointLabels={[
                  { xMm: 0, yMm: 0, label: shownCurrentA >= 0 ? `⊙ +${shownCurrentA.toFixed(0)} A` : `⊗ ${shownCurrentA.toFixed(0)} A`, tone: 'neutral' },
                  { xMm: PROBE_RADIUS_MM, yMm: 0, label: 'probe 15 mm', tone: 'neutral' },
                ]}
              />
            )}
          </div>
        ) : (
          <section className="current-field-empty-stage">
            <CurrentPredictionDiagram />
            <div><p className="learning-kicker">Direction lab</p><h2>Start with +8 A.</h2><p>One solve reveals the circular field. Reversing current will test the rule.</p></div>
          </section>
        )}

        {lessonStage === 'solve' && !quizOpen ? (
          <div className="current-field-lesson-dock" aria-label="Current experiment controls">
            <div className="current-field-dock-insight"><span>{activeProgressStepId}</span><strong>{labInsight}</strong></div>
            <div className="current-field-dock-actions">
              <button type="button" className="current-field-dock-button" aria-expanded={labControlsOpen} onClick={() => { setLabControlsOpen((open) => !open); setSolveInspectorOpen(false); }}>{labControlsOpen ? 'Done' : 'Adjust current'}</button>
              <button type="button" className="current-field-dock-button" aria-expanded={solveInspectorOpen} onClick={() => { setSolveInspectorOpen((open) => !open); setLabControlsOpen(false); }}>Inspect results</button>
            </div>
          </div>
        ) : quizOpen && !quizPassed && !lessonComplete ? (
          <div className="current-field-lesson-dock current-field-quiz-dock" aria-label="Knowledge check controls">
            <div className="current-field-dock-insight"><span>Check</span><strong>Answer all three questions to complete Lesson 3.</strong></div>
            <div className="current-field-dock-actions">
              <button type="button" className="current-field-dock-button" onClick={() => setQuizOpen(false)}>Review experiment</button>
              <button type="button" className="current-field-dock-button" onClick={onBackToCatalog}>Lessons</button>
            </div>
          </div>
        ) : null}
      </section>

      {lessonStage === 'solve' && !quizOpen && solveInspectorOpen ? (
        <aside ref={solveInspectorRef} className="learning-context-panel current-field-context" aria-label="Lesson evidence and solved results">
          <button type="button" className="current-field-drawer-close" onClick={() => setSolveInspectorOpen(false)} aria-label="Close solved results">×</button>
          <header className="current-field-status-header">
            <p className="learning-kicker">Evidence · Lesson 3</p>
            <h1>Current comparison</h1>
            <p>Sign flips direction. Magnitude sets strength.</p>
            <div className="learning-progress" aria-label="Lesson completion"><span style={{ width: `${(completedStepCount / lessonProgressSteps.length) * 100}%` }} /></div>
          </header>
          {runs.length ? (
            <section className="current-field-results" aria-label="Solved current comparison">
              <header><div><p className="learning-kicker">Solved current sweep</p><h2>{comparisonReady ? 'The field follows the current.' : 'Build the three-frame comparison.'}</h2></div><span>{runs.length} run{runs.length === 1 ? '' : 's'}</span></header>
              <CurrentFieldPlot runs={runs} activeCurrentA={currentRun?.currentA ?? null} onSelect={setCurrentA} />
              {currentRun?.data.metrics ? (
                <section className="current-field-readout">
                  <div><span>FEM Bθ at 15 mm</span><strong>{formatSignedMilliT(currentRun.probeBT)}</strong></div>
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
          <section className="current-field-inspector-next" aria-label="Continue after reviewing the current plot">
            <span>{comparisonReady ? 'Evidence reviewed?' : 'Plot reviewed?'}</span>
            {comparisonReady ? (
              <button type="button" onClick={continueToCheck}>Continue to Check →</button>
            ) : (
              <button type="button" disabled={busy} onClick={continueExperiment}>
                Adjust next: {guidedCurrentA > 0 ? '+' : ''}{guidedCurrentA.toFixed(0)} A →
              </button>
            )}
          </section>
          <details className="current-field-inspector-details">
            <summary>Details · straight-wire equation</summary>
            <section className="current-field-equation-card">
              <header><span>STRAIGHT-WIRE CHECK</span><strong>probe r = 15 mm</strong></header>
              <div className="current-field-equation"><span>B</span><b>=</b><span className="current-field-fraction"><i>μ<sub>0</sub>I</i><i>2πr</i></span></div>
              <dl><div><dt>Current density J</dt><dd>{currentDensityAmm2 > 0 ? '+' : ''}{currentDensityAmm2.toFixed(3)} A/mm²</dd></div><div><dt>Predicted Bθ</dt><dd>{formatSignedMilliT(analyticProbeBT(currentA))}</dd></div></dl>
              <p>Positive Bθ is counterclockwise. Negative Bθ is clockwise.</p>
            </section>
          </details>
        </aside>
      ) : null}
    </main>
  );
};
