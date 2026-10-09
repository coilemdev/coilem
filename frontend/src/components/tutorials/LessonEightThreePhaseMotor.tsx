import React from 'react';
import type {
  ThreePhaseMotorFieldComponent,
  ThreePhaseMotorFrameData,
  ThreePhaseMotorSweepData,
} from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import {
  MeshViewer,
  type MeshViewerDirectionVector,
  type MeshViewerPointLabel,
} from './MeshViewer';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
import { ThreePhaseMotor3D } from './ThreePhaseMotor3D';
import './learning.css';
import './rotating-field.css';
import './three-phase-motor.css';

interface LearningLessonEightThreePhaseMotorProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type RotationDirection = 1 | -1;

const PEAK_CURRENT_A = 8;
const FRAME_STEP_DEG = 11.25;
const FRAME_COUNT = 32;
const PLAY_INTERVAL_MS = 240;
const FIELD_VECTOR_LENGTH_MM = 16;

const PHASE_COLORS = {
  A: '#22d3ee',
  B: '#f59e0b',
  C: '#a78bfa',
} as const;

const STATOR_POLE_PHASES = ['A', 'C', 'B', 'A', 'C', 'B'] as const;

const FIELD_MODES: Array<{ mode: ThreePhaseMotorFieldComponent; label: string }> = [
  { mode: 'phase_a', label: 'Phase A' },
  { mode: 'phase_b', label: 'Phase B' },
  { mode: 'phase_c', label: 'Phase C' },
  { mode: 'stator', label: 'Stator only' },
  { mode: 'rotor', label: 'Rotor only' },
  { mode: 'combined', label: 'Combined' },
];

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'three-phase-neutral',
    prompt: 'An ideal two-phase winding can also make a smooth rotating field. Why use three-phase Wye here?',
    options: [
      'Two phases cannot create continuous rotation',
      'It produces smooth rotation with three motor leads and a six-switch inverter because current returns through the other phases',
      'The permanent-magnet rotor becomes the neutral conductor',
    ],
    correctIndex: 1,
    explanation: 'Ideal two-phase and three-phase drives can both create a constant rotating field. Three-phase Wye does it with three motor leads and six inverter switches because the balanced phase currents sum to zero.',
  },
  {
    id: 'three-phase-poles',
    prompt: 'What magnetic field do six wound teeth create in this lesson?',
    options: [
      'A six-pole stationary field',
      'Three unrelated one-phase fields',
      'One rotating two-pole field',
    ],
    correctIndex: 2,
    explanation: 'The six teeth are grouped into three opposing phase pairs. Their 120°-shifted currents combine into one rotating two-pole field.',
  },
  {
    id: 'three-phase-reverse',
    prompt: 'What reverses the rotating field and PM rotor?',
    options: [
      'Swapping any two phase connections',
      'Adding an external neutral wire',
      'Increasing all three currents equally',
    ],
    correctIndex: 0,
    explanation: 'Swapping any two phases reverses phase sequence, so the field advances in the opposite direction.',
  },
  {
    id: 'three-phase-open',
    prompt: 'What changes when Phase C is opened?',
    options: [
      'The remaining phases automatically become an ideal balanced set',
      'The balanced rotating field collapses into an unbalanced, pulsating field',
      'The rotor becomes a six-pole permanent magnet',
    ],
    correctIndex: 1,
    explanation: 'With one line open, the floating-star winding carries equal and opposite current in the two remaining phases. The smooth three-phase rotating field is lost.',
  },
];

const normalizeAngle = (angleDeg: number) => ((angleDeg % 360) + 360) % 360;
const displayAngle = (angleDeg: number) => Number(normalizeAngle(angleDeg).toFixed(2)).toString();
const displayCycleAngle = (angleDeg: number) => (
  Math.abs(angleDeg - 360) < 0.1 ? '360' : displayAngle(angleDeg)
);
const signedCurrent = (currentA: number) => (
  `${currentA > 0.04 ? '+' : ''}${Math.abs(currentA) < 0.04 ? '0.00' : currentA.toFixed(2)} A`
);
const currentGlyph = (currentA: number) => (
  currentA > 0.05 ? '⊙' : currentA < -0.05 ? '⊗' : '○'
);

interface ThreePhaseWaveformProps {
  angleDeg: number;
  phaseACurrentA: number;
  phaseBCurrentA: number;
  phaseCCurrentA: number;
  phaseCOpen: boolean;
  onSelectAngle: (angleDeg: number) => void;
}

const ThreePhaseWaveform: React.FC<ThreePhaseWaveformProps> = ({
  angleDeg,
  phaseACurrentA,
  phaseBCurrentA,
  phaseCCurrentA,
  phaseCOpen,
  onSelectAngle,
}) => {
  const width = 960;
  const height = 230;
  const margin = { top: 30, right: 28, bottom: 42, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xFor = (angle: number) => margin.left + angle / 360 * plotWidth;
  const yFor = (current: number) => (
    margin.top + plotHeight / 2 - current / PEAK_CURRENT_A * plotHeight * 0.42
  );
  const angles = Array.from({ length: 145 }, (_, index) => index * 2.5);
  const phasePath = (offsetDeg: number) => angles.map((angle) => (
    `${xFor(angle)},${yFor(PEAK_CURRENT_A * Math.cos((angle + offsetDeg) * Math.PI / 180))}`
  )).join(' ');
  const selectedX = xFor(Math.abs(angleDeg - 360) < 0.1 ? 360 : normalizeAngle(angleDeg));

  return (
    <div className="three-phase-waveform-wrap">
      <div className="three-phase-waveform-legend">
        <span style={{ color: PHASE_COLORS.A }}>Phase A · cos θ</span>
        <span style={{ color: PHASE_COLORS.B }}>Phase B · cos(θ − 120°)</span>
        <span className={phaseCOpen ? 'is-open' : ''} style={{ color: PHASE_COLORS.C }}>
          Phase C · {phaseCOpen ? 'OPEN' : 'cos(θ + 120°)'}
        </span>
      </div>
      <svg className="three-phase-waveform" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Three phase currents separated by 120 electrical degrees">
        <g className="three-phase-waveform-grid">
          {[-PEAK_CURRENT_A, 0, PEAK_CURRENT_A].map((current) => (
            <line key={current} x1={margin.left} y1={yFor(current)} x2={width - margin.right} y2={yFor(current)} />
          ))}
          {[0, 90, 180, 270, 360].map((angle) => (
            <line key={angle} x1={xFor(angle)} y1={margin.top} x2={xFor(angle)} y2={height - margin.bottom} />
          ))}
        </g>
        <polyline className="is-a" points={phasePath(0)} />
        <polyline className="is-b" points={phaseCOpen ? phasePath(180) : phasePath(-120)} />
        {!phaseCOpen ? <polyline className="is-c" points={phasePath(120)} /> : null}
        <line className="three-phase-waveform-cursor" x1={selectedX} y1={margin.top} x2={selectedX} y2={height - margin.bottom} />
        <circle className="is-a" cx={selectedX} cy={yFor(phaseACurrentA)} r="6" />
        <circle className="is-b" cx={selectedX} cy={yFor(phaseBCurrentA)} r="6" />
        {!phaseCOpen ? <circle className="is-c" cx={selectedX} cy={yFor(phaseCCurrentA)} r="6" /> : null}
        <g className="three-phase-waveform-ticks">
          {[0, 90, 180, 270, 360].map((angle) => (
            <text key={angle} x={xFor(angle)} y={height - 14} textAnchor="middle">{angle}°</text>
          ))}
          <text x={18} y={yFor(PEAK_CURRENT_A) + 4}>+8</text>
          <text x={28} y={yFor(0) + 4}>0</text>
          <text x={18} y={yFor(-PEAK_CURRENT_A) + 4}>−8</text>
        </g>
        {Array.from({ length: FRAME_COUNT + 1 }, (_, index) => index * FRAME_STEP_DEG).map((angle) => (
          <rect
            key={angle}
            className="three-phase-waveform-hit"
            x={xFor(angle) - plotWidth / FRAME_COUNT / 2}
            y={margin.top}
            width={plotWidth / FRAME_COUNT}
            height={plotHeight}
            role="button"
            tabIndex={0}
            aria-label={`Show solved ${displayCycleAngle(angle)} degree frame`}
            onClick={() => onSelectAngle(angle)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') onSelectAngle(angle);
            }}
          />
        ))}
      </svg>
    </div>
  );
};

type DriveComparisonMode = 'two-phase' | 'three-phase';

interface DriveComparisonProps {
  angleDeg: number;
  phaseACurrentA: number;
  phaseBCurrentA: number;
  phaseCCurrentA: number;
}

const currentPathOpacity = (currentA: number) => 0.34 + Math.abs(currentA) / PEAK_CURRENT_A * 0.66;

const DriveComparison: React.FC<DriveComparisonProps> = ({
  angleDeg,
  phaseACurrentA,
  phaseBCurrentA,
  phaseCCurrentA,
}) => {
  const [mode, setMode] = React.useState<DriveComparisonMode>('three-phase');
  const angleRad = normalizeAngle(angleDeg) * Math.PI / 180;
  const twoPhaseCurrentA = PEAK_CURRENT_A * Math.cos(angleRad);
  const twoPhaseCurrentB = PEAK_CURRENT_A * Math.sin(angleRad);
  const normalizedAngle = Math.abs(angleDeg - 360) < 0.1 ? 360 : normalizeAngle(angleDeg);
  const cursorX = 18 + normalizedAngle / 360 * 404;
  const isTwoPhase = mode === 'two-phase';
  const leadCount = isTwoPhase ? 4 : 3;
  const switchCount = isTwoPhase ? 8 : 6;

  return (
    <section className="three-phase-drive-comparison">
      <header>
        <div>
          <span>WHY ADD PHASE C?</span>
          <h3>The third phase makes smooth rotation practical.</h3>
        </div>
        <strong>same ideal field · less hardware</strong>
      </header>
      <p>Two ideal phases at 90° already rotate smoothly. Three-phase Wye reaches the same magnetic outcome with a simpler power connection.</p>

      <div className="three-phase-comparison-tabs" role="tablist" aria-label="Compare two-phase and three-phase drives">
        <button
          type="button"
          role="tab"
          aria-selected={isTwoPhase}
          className={isTwoPhase ? 'is-active' : ''}
          onClick={() => setMode('two-phase')}
        >
          <span>2-phase</span>
          <strong>4 leads · 8 switches</strong>
          <small>Lesson 7</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={!isTwoPhase}
          className={!isTwoPhase ? 'is-active' : ''}
          onClick={() => setMode('three-phase')}
        >
          <span>3-phase Wye</span>
          <strong>3 leads · 6 switches</strong>
          <small>This lesson</small>
        </button>
      </div>

      <div className={`three-phase-comparison-topology is-${mode}`} role="tabpanel">
        <svg viewBox="0 0 320 164" role="img" aria-label={isTwoPhase
          ? 'Two isolated phase windings with four external motor leads'
          : 'Three phase windings joined at an internal Wye point with three external motor leads'}>
          {isTwoPhase ? (
            <>
              <g className="three-phase-comparison-path is-a" style={{ opacity: currentPathOpacity(twoPhaseCurrentA) }}>
                <path d="M 34 48 H 88 C 96 28 108 68 116 48 C 124 28 136 68 144 48 C 152 28 164 68 172 48 H 286" />
                <circle cx="30" cy="48" r="5" /><circle cx="290" cy="48" r="5" />
                <text x="17" y="30">A+</text><text x="278" y="30">A−</text>
                <text x="126" y="26">Iₐ {signedCurrent(twoPhaseCurrentA)}</text>
              </g>
              <g className="three-phase-comparison-path is-b" style={{ opacity: currentPathOpacity(twoPhaseCurrentB) }}>
                <path d="M 34 116 H 88 C 96 96 108 136 116 116 C 124 96 136 136 144 116 C 152 96 164 136 172 116 H 286" />
                <circle cx="30" cy="116" r="5" /><circle cx="290" cy="116" r="5" />
                <text x="17" y="146">B+</text><text x="278" y="146">B−</text>
                <text x="126" y="94">Iᵦ {signedCurrent(twoPhaseCurrentB)}</text>
              </g>
              <text className="three-phase-comparison-note" x="160" y="157" textAnchor="middle">two isolated return paths</text>
            </>
          ) : (
            <>
              <g className="three-phase-comparison-path is-a" style={{ opacity: currentPathOpacity(phaseACurrentA) }}>
                <path d="M 34 34 H 82 C 90 16 100 52 108 34 C 116 16 126 52 134 34 H 164 L 236 82" />
                <circle cx="30" cy="34" r="5" /><text x="17" y="18">U</text>
                <text x="82" y="22">Iₐ {signedCurrent(phaseACurrentA)}</text>
              </g>
              <g className="three-phase-comparison-path is-b" style={{ opacity: currentPathOpacity(phaseBCurrentA) }}>
                <path d="M 34 82 H 82 C 90 64 100 100 108 82 C 116 64 126 100 134 82 H 236" />
                <circle cx="30" cy="82" r="5" /><text x="17" y="70">V</text>
                <text x="82" y="70">Iᵦ {signedCurrent(phaseBCurrentA)}</text>
              </g>
              <g className="three-phase-comparison-path is-c" style={{ opacity: currentPathOpacity(phaseCCurrentA) }}>
                <path d="M 34 130 H 82 C 90 112 100 148 108 130 C 116 112 126 148 134 130 H 164 L 236 82" />
                <circle cx="30" cy="130" r="5" /><text x="17" y="151">W</text>
                <text x="82" y="118">I꜀ {signedCurrent(phaseCCurrentA)}</text>
              </g>
              <circle className="three-phase-comparison-star" cx="238" cy="82" r="17" />
              <text className="three-phase-comparison-star-label" x="238" y="86" textAnchor="middle">N*</text>
              <text className="three-phase-comparison-note" x="268" y="116" textAnchor="middle">internal</text>
              <text className="three-phase-comparison-note is-sum" x="238" y="145" textAnchor="middle">Iₐ + Iᵦ + I꜀ = 0</text>
            </>
          )}
        </svg>

        <div className="three-phase-comparison-facts">
          <article>
            <span>Motor leads</span>
            <strong>{leadCount}</strong>
            <small>{isTwoPhase ? 'A+ · A− · B+ · B−' : 'U · V · W · no neutral'}</small>
          </article>
          <article>
            <span>Power switches</span>
            <strong>{switchCount}</strong>
            <div className="three-phase-switch-count" aria-hidden="true">
              {Array.from({ length: switchCount }, (_, index) => <i key={index} />)}
            </div>
            <small>{isTwoPhase ? 'two full H-bridges' : 'one three-leg inverter'}</small>
          </article>
        </div>
      </div>

      <div className="three-phase-comparison-field">
        <header><span>Normalized rotating-field magnitude</span><strong>both constant</strong></header>
        <svg viewBox="0 0 440 70" role="img" aria-label="Overlapping flat traces show constant ideal rotating field magnitude for both two-phase and three-phase drives">
          <line className="is-grid" x1="18" y1="34" x2="422" y2="34" />
          <line className="is-two" x1="18" y1="34" x2="422" y2="34" />
          <line className="is-three" x1="18" y1="34" x2="422" y2="34" />
          <line className="is-cursor" x1={cursorX} y1="14" x2={cursorX} y2="52" />
          <circle className="is-cursor-dot" cx={cursorX} cy="34" r="4" />
          <text x="18" y="64">0°</text><text x="400" y="64">360°</text>
        </svg>
        <div><span className="is-two">2φ ideal</span><span className="is-three">3φ ideal</span></div>
      </div>

      <footer><strong>The third phase doesn’t make rotation possible.</strong> It removes one motor lead and two power switches.</footer>
    </section>
  );
};

const WyeConnectionCard: React.FC = () => (
  <section className="three-phase-wye-card">
    <header><span>THREE EXTERNAL WIRES</span><strong>Internal Wye connection</strong></header>
    <svg
      className="three-phase-wye-diagram"
      viewBox="0 0 320 144"
      role="img"
      aria-label="Three motor phase windings connected to one internal star point with no external neutral"
    >
      <g className="three-phase-wye-labels">
        <text className="is-a" x="16" y="32">L1 → U</text>
        <text className="is-b" x="16" y="76">L2 → V</text>
        <text className="is-c" x="16" y="120">L3 → W</text>
      </g>
      <g className="three-phase-wye-paths">
        <path className="is-a" d="M 90 28 L 226 72" />
        <path className="is-b" d="M 90 72 L 226 72" />
        <path className="is-c" d="M 90 116 L 226 72" />
      </g>
      <circle className="three-phase-wye-node" cx="238" cy="72" r="22" />
      <text className="three-phase-wye-node-label" x="238" y="77" textAnchor="middle">N*</text>
    </svg>
    <p><strong>N*</strong> is the motor’s internal star point—not a fourth supply wire.</p>
    <code>I<sub>A</sub> + I<sub>B</sub> + I<sub>C</sub> = 0</code>
    <small>Balanced current leaving one phase returns through the other two, so no external neutral conductor is required.</small>
  </section>
);

export const LearningLessonEightThreePhaseMotor: React.FC<LearningLessonEightThreePhaseMotorProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [geometry, setGeometry] = React.useState<ThreePhaseMotorFrameData | null>(null);
  const [sweeps, setSweeps] = React.useState<Partial<Record<ThreePhaseMotorFieldComponent, ThreePhaseMotorSweepData>>>({});
  const [fieldMode, setFieldMode] = React.useState<ThreePhaseMotorFieldComponent>('combined');
  const [frameIndex, setFrameIndex] = React.useState(0);
  // Match the public Solve player: start with the clockwise A-C-B sequence,
  // then let the learner swap two phases to observe the reversal.
  const [direction, setDirection] = React.useState<RotationDirection>(-1);
  const [playing, setPlaying] = React.useState(false);
  const [playSteps, setPlaySteps] = React.useState(0);
  const [cycleComplete, setCycleComplete] = React.useState(false);
  const [inspectedOpenPhase, setInspectedOpenPhase] = React.useState(false);
  const [reversedSequence, setReversedSequence] = React.useState(false);
  const [busyMode, setBusyMode] = React.useState<ThreePhaseMotorFieldComponent | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showFluxLines, setShowFluxLines] = React.useState(true);
  const [showFieldIntensity, setShowFieldIntensity] = React.useState(false);
  const [showMesh, setShowMesh] = React.useState(false);
  const [showThreeD, setShowThreeD] = React.useState(false);
  const [showElectromagnets, setShowElectromagnets] = React.useState(true);
  const [showPmRotor, setShowPmRotor] = React.useState(true);
  const [rotorMotionAllowed, setRotorMotionAllowed] = React.useState(true);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(true);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const geometryRequest = React.useRef<Promise<void> | null>(null);
  const mainStageRef = React.useRef<HTMLElement | null>(null);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();

  const activeSweep = sweeps[fieldMode];
  const frames = activeSweep?.frames ?? [];
  const lookupIndex = frames.length ? frameIndex % frames.length : 0;
  const solvedFrame = frames[lookupIndex] ?? null;
  const displayFrame = solvedFrame ?? geometry;
  const electricalAngle = frames.length && frameIndex === frames.length
    ? 360
    : solvedFrame?.electrical_angle_deg ?? 0;
  const phaseCOpen = fieldMode === 'open_c';
  const labComplete = cycleComplete && inspectedOpenPhase && reversedSequence;
  const showDockPlayback = !quizOpen
    && lessonStage === 'solve'
    && Boolean(sweeps.combined)
    && !labControlsOpen;

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [onStageChange, stage]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('three-phase-motor', true);
  }, [quizPassed, setLessonComplete]);

  React.useLayoutEffect(() => {
    mainStageRef.current?.scrollTo({ top: 0 });
  }, [lessonStage, quizOpen]);

  const loadGeometry = React.useCallback(() => {
    if (geometry || geometryRequest.current) return geometryRequest.current;
    const request = solveClient.fetchThreePhaseMotorGeometry()
      .then(setGeometry)
      .catch((geometryError) => {
        setError(geometryError instanceof Error ? geometryError.message : 'The three-phase geometry failed to load.');
      })
      .finally(() => {
        geometryRequest.current = null;
      });
    geometryRequest.current = request;
    return request;
  }, [geometry]);

  React.useEffect(() => {
    void loadGeometry();
  }, [loadGeometry]);

  React.useEffect(() => {
    if (!playing || !frames.length || !rotorMotionAllowed) return undefined;
    const timer = window.setInterval(() => {
      setFrameIndex((previous) => (
        direction === 1
          ? previous >= frames.length ? 1 : previous + 1
          : previous <= 0 ? frames.length - 1 : previous - 1
      ));
      setPlaySteps((previous) => {
        const next = previous + 1;
        if (next >= frames.length) {
          setCycleComplete(true);
          setPlaying(false);
        }
        return next;
      });
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [direction, frames.length, playing, rotorMotionAllowed]);

  const loadSweep = React.useCallback(async (
    mode: ThreePhaseMotorFieldComponent,
    options: { autoPlay?: boolean } = {},
  ) => {
    setPlaying(false);
    setError(null);
    const cached = sweeps[mode];
    if (cached) {
      setFieldMode(mode);
      if (options.autoPlay) {
        setFrameIndex(direction === 1 ? 0 : cached.frames.length);
        setPlaySteps(0);
        setLabControlsOpen(false);
        setSolveInspectorOpen(true);
        setPlaying(true);
      }
      return;
    }
    if (busyMode) return;
    setBusyMode(mode);
    try {
      const result = await solveClient.fetchThreePhaseMotorSweep(PEAK_CURRENT_A, mode);
      if (result.frames.length !== FRAME_COUNT || result.field_component !== mode) {
        throw new Error(`The solver did not return the complete ${mode} field cycle.`);
      }
      setSweeps((previous) => ({ ...previous, [mode]: result }));
      setFieldMode(mode);
      setFrameIndex(direction === 1 ? 0 : result.frames.length);
      if (mode === 'open_c') setInspectedOpenPhase(true);
      if (options.autoPlay) {
        setPlaySteps(0);
        setRotorMotionAllowed(true);
        setLabControlsOpen(false);
        setSolveInspectorOpen(true);
        setPlaying(true);
      }
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The three-phase FEM sweep failed.');
    } finally {
      setBusyMode(null);
    }
  }, [busyMode, direction, solveClient, sweeps]);

  const enterLab = React.useCallback(() => {
    setQuizOpen(false);
    onStageChange?.('solve');
    void loadGeometry();
    void loadSweep('combined', { autoPlay: true });
  }, [loadGeometry, loadSweep, onStageChange]);

  const selectFrame = (nextIndex: number) => {
    if (!frames.length) return;
    setPlaying(false);
    if (nextIndex < 0) setFrameIndex(frames.length - 1);
    else if (nextIndex > frames.length) setFrameIndex(1);
    else setFrameIndex(nextIndex);
  };

  const selectAngle = (angleDeg: number) => {
    if (!frames.length) return;
    setPlaying(false);
    if (Math.abs(angleDeg - 360) < 0.1) {
      setFrameIndex(frames.length);
      return;
    }
    const index = frames.findIndex((frame) => (
      Math.abs(normalizeAngle(frame.electrical_angle_deg) - normalizeAngle(angleDeg)) < 0.1
    ));
    if (index >= 0) setFrameIndex(index);
  };

  const playCycle = () => {
    if (!frames.length || !rotorMotionAllowed) return;
    setFrameIndex(direction === 1 ? 0 : frames.length);
    setPlaySteps(0);
    setPlaying(true);
  };

  const swapTwoPhases = () => {
    setPlaying(false);
    setDirection((previous) => previous === 1 ? -1 : 1);
    setReversedSequence(true);
    setFrameIndex(direction === 1 ? frames.length : 0);
  };

  const advanceDriveChecks = () => {
    setSolveInspectorOpen(false);
    if (!cycleComplete) {
      setLabControlsOpen(false);
      playCycle();
      return;
    }
    setLabControlsOpen(true);
    if (!inspectedOpenPhase) {
      void loadSweep('open_c');
      return;
    }
    if (phaseCOpen) {
      void loadSweep('combined');
      return;
    }
    if (!reversedSequence) swapTwoPhases();
  };

  const driveCheckActionLabel = playing && !cycleComplete
    ? 'Completing cycle…'
    : !cycleComplete
      ? 'Play full cycle'
      : !inspectedOpenPhase
        ? 'Open Phase C'
        : phaseCOpen
          ? 'Restore Phase C'
          : 'Swap B/C to reverse';

  const intensityRange = React.useMemo(() => {
    const values = frames
      .flatMap((frame) => frame.element_b_mag_t ?? [])
      .filter((value) => Number.isFinite(value) && value >= 0)
      .sort((left, right) => left - right);
    if (!values.length) return undefined;
    return {
      low: values[Math.floor(values.length * 0.03)],
      high: values[Math.floor(values.length * 0.98)],
    };
  }, [frames]);

  const renderFrame = React.useMemo(() => {
    if (!displayFrame) return null;
    return {
      ...displayFrame,
      regions: displayFrame.regions.map((region, triangleIndex) => {
        if (!showElectromagnets && (region === 'three_phase_stator_pole' || region.startsWith('phase_'))) {
          return 'air';
        }
        if (!showPmRotor && region === 'three_phase_rotor_magnet') return 'air';
        if (region === 'three_phase_stator_pole') {
          const triangle = displayFrame.triangles[triangleIndex];
          const nodes = triangle?.map((nodeIndex) => displayFrame.nodes_mm[nodeIndex]).filter(Boolean) ?? [];
          if (nodes.length === 3) {
            const centerX = nodes.reduce((sum, node) => sum + node[0], 0) / nodes.length;
            const centerY = nodes.reduce((sum, node) => sum + node[1], 0) / nodes.length;
            const angleDeg = normalizeAngle(Math.atan2(centerY, centerX) * 180 / Math.PI);
            const poleIndex = Math.round(angleDeg / 60) % STATOR_POLE_PHASES.length;
            return `stator_tooth_${STATOR_POLE_PHASES[poleIndex].toLowerCase()}`;
          }
          return 'stator_tooth';
        }
        if (region === 'three_phase_rotor_magnet') return 'magnet';
        if (region.startsWith('phase_a')) return 'slot_winding_a';
        if (region.startsWith('phase_b')) return 'slot_winding_b';
        if (region.startsWith('phase_c')) return 'slot_winding_c';
        return region;
      }),
    };
  }, [displayFrame, showElectromagnets, showPmRotor]);

  const pointLabels: MeshViewerPointLabel[] = React.useMemo(() => {
    if (!displayFrame || !showElectromagnets) return [];
    const currents = {
      A: displayFrame.phase_a_current_a,
      B: displayFrame.phase_b_current_a,
      C: displayFrame.phase_c_current_a,
    };
    const axes: Array<{ phase: keyof typeof currents; angle: number }> = [
      { phase: 'A', angle: 0 },
      { phase: 'B', angle: 120 },
      { phase: 'C', angle: 240 },
    ];
    const labels: MeshViewerPointLabel[] = [];
    axes.forEach(({ phase, angle }) => {
      const radians = angle * Math.PI / 180;
      const axisX = Math.cos(radians);
      const axisY = Math.sin(radians);
      const normalX = -axisY;
      const normalY = axisX;
      [-1, 1].forEach((poleSign) => {
        [-1, 1].forEach((sideSign) => {
          labels.push({
            xMm: poleSign * displayFrame.coil_center_mm * axisX + sideSign * displayFrame.coil_side_mm * normalX,
            yMm: poleSign * displayFrame.coil_center_mm * axisY + sideSign * displayFrame.coil_side_mm * normalY,
            label: `${phase} ${currentGlyph(sideSign * currents[phase])}`,
            tone: 'neutral',
            scale: 0.84,
          });
        });
        labels.push({
          xMm: poleSign * 9.2 * axisX,
          yMm: poleSign * 9.2 * axisY,
          label: `${phase}${poleSign > 0 ? '+' : '−'}`,
          tone: 'neutral',
          scale: 0.72,
        });
      });
    });
    return labels;
  }, [displayFrame, showElectromagnets]);

  const directionVectors: MeshViewerDirectionVector[] = React.useMemo(() => {
    if (!displayFrame) return [];
    const fieldAngle = fieldMode === 'rotor'
      ? displayFrame.rotor_angle_deg
      : displayFrame.field_target_angle_deg;
    const fieldRadians = fieldAngle * Math.PI / 180;
    const vectors: MeshViewerDirectionVector[] = [{
      x1Mm: 0,
      y1Mm: 0,
      x2Mm: FIELD_VECTOR_LENGTH_MM * Math.cos(fieldRadians),
      y2Mm: FIELD_VECTOR_LENGTH_MM * Math.sin(fieldRadians),
      label: phaseCOpen ? 'unbalanced B' : fieldMode === 'rotor' ? 'PM field' : 'B target',
      tone: phaseCOpen ? 'amber' : 'cyan',
    }];
    if (fieldMode !== 'rotor' && showPmRotor) {
      const rotorRadians = displayFrame.rotor_angle_deg * Math.PI / 180;
      vectors.push({
        x1Mm: 0,
        y1Mm: 0,
        x2Mm: 10 * Math.cos(rotorRadians),
        y2Mm: 10 * Math.sin(rotorRadians),
        label: 'PM rotor',
        tone: 'amber',
        strokeScale: 0.82,
      });
    }
    return vectors;
  }, [displayFrame, fieldMode, phaseCOpen, showPmRotor]);

  const progressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    {
      id: 'connect',
      label: 'Connect Wye',
      complete: lessonStage !== 'design',
      available: true,
    },
    {
      id: 'spin',
      label: 'Spin field',
      complete: cycleComplete,
      available: true,
    },
    {
      id: 'stress',
      label: 'Stress drive',
      complete: labComplete,
      available: cycleComplete,
    },
    {
      id: 'check',
      label: 'Check',
      complete: quizPassed,
      available: labComplete,
    },
  ], [cycleComplete, labComplete, lessonStage, quizPassed]);
  const currentStepId = quizOpen
    ? 'check'
    : lessonStage === 'design'
      ? 'connect'
      : cycleComplete
        ? 'stress'
        : 'spin';
  const handleHeaderStepSelect = React.useCallback((stepId: string) => {
    setPlaying(false);
    if (stepId === 'connect') {
      setQuizOpen(false);
      onStageChange?.('design');
      return;
    }
    if (stepId === 'spin') {
      setQuizOpen(false);
      if (sweeps.combined) onStageChange?.('solve');
      else enterLab();
      return;
    }
    if (stepId === 'stress' && cycleComplete) {
      setQuizOpen(false);
      onStageChange?.('solve');
      return;
    }
    if (stepId === 'check' && labComplete) setQuizOpen(true);
  }, [cycleComplete, enterLab, labComplete, onStageChange, sweeps.combined]);
  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 8,
    lessonCount: 10,
    title: 'Three Wires, One Rotating Field',
    currentStepId,
    steps: progressSteps,
    onStepSelect: handleHeaderStepSelect,
  }), [currentStepId, handleHeaderStepSelect, progressSteps]);

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  const modeLabel = fieldMode === 'open_c'
    ? 'OPEN PHASE C · UNBALANCED FIELD'
    : FIELD_MODES.find((item) => item.mode === fieldMode)?.label.toUpperCase() ?? 'COMBINED';
  const viewerControls = (
    <div className="rotating-field-view-toggle" role="group" aria-label="Field visualization">
      <button
        type="button"
        disabled={!solvedFrame}
        className={!showThreeD && showFluxLines ? 'is-active' : ''}
        onClick={() => {
          setShowFluxLines((visible) => showThreeD ? true : !visible);
          setShowThreeD(false);
        }}
        aria-pressed={!showThreeD && showFluxLines}
      ><span /> Flux lines</button>
      <button
        type="button"
        disabled={!solvedFrame}
        className={showFieldIntensity ? 'is-active' : ''}
        onClick={() => setShowFieldIntensity((visible) => !visible)}
        aria-pressed={showFieldIntensity}
      ><span className="is-density" /> |B| map</button>
      <button
        type="button"
        className={!showThreeD && showMesh ? 'is-active' : ''}
        onClick={() => {
          setShowMesh((visible) => showThreeD ? true : !visible);
          setShowThreeD(false);
        }}
        aria-pressed={!showThreeD && showMesh}
      ><span className="is-mesh" /> Mesh</button>
      <button
        type="button"
        className={showThreeD ? 'is-active' : ''}
        onClick={() => setShowThreeD(true)}
        aria-pressed={showThreeD}
      ><span className="is-three" /> 3D</button>
    </div>
  );

  return (
    <main
      className={`learning-shell learning-lesson-shell rotating-field-shell three-phase-shell is-${lessonStage}-stage${quizOpen ? ' is-quiz-open' : ''}${lessonStage === 'solve' && labControlsOpen && !quizOpen ? ' has-lab-controls' : ''}${solveInspectorOpen && !quizOpen ? ' has-solve-inspector' : ''}`}
    >
      <header className="tutorial-studio-strip three-phase-studio-strip">
        <div className="three-phase-studio-context">
          <strong>{lessonStage === 'design' ? 'Three-phase Wye motor · connection' : phaseCOpen ? 'Three-phase motor · open Phase C' : 'Three-phase motor · balanced drive'}</strong>
          <span>{lessonStage === 'design'
            ? 'Six wound teeth · three supply conductors · one internal neutral'
            : `${frames.length || 32} solved angles · ${direction === 1 ? 'A–B–C' : 'A–C–B'} sequence`}</span>
        </div>
        {lessonStage === 'solve' && !quizOpen && displayFrame ? (
          <div className="three-phase-strip-source-console">
            <div className="three-phase-strip-source-buttons" role="group" aria-label="Motor field source">
              {FIELD_MODES.filter(({ mode }) => mode === 'stator' || mode === 'rotor' || mode === 'combined').map(({ mode, label }) => (
                <button
                  key={mode}
                  type="button"
                  disabled={Boolean(busyMode)}
                  className={fieldMode === mode ? 'is-active' : ''}
                  onClick={() => void loadSweep(mode)}
                >{label}</button>
              ))}
            </div>
            <div className="three-phase-strip-readout">
              <span>{modeLabel}</span>
              <strong>θe {displayCycleAngle(electricalAngle)}°</strong>
            </div>
          </div>
        ) : null}
        {lessonStage === 'solve' && !quizOpen && displayFrame ? viewerControls : null}
      </header>
      <section ref={mainStageRef} className="learning-main-stage rotating-field-main">
        {quizOpen ? (
          <section className="rotating-field-quiz-stage three-phase-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you connect the supply, rotating field, and PM rotor?</h2>
            <p>Use the balanced currents, phase sequence, and open-phase experiment.</p>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </section>
        ) : lessonStage === 'design' ? (
          <section className="three-phase-connect-experience">
            <header className="three-phase-connect-heading">
              <span>LESSON 8 · CONNECT WYE</span>
              <h1>How do three wires create one rotating field?</h1>
              <p>Trace each supply line to its winding, then find the connection they share inside the motor.</p>
            </header>
            <div className="three-phase-connect-stage">
              <WyeConnectionCard />
              <div className="three-phase-connect-motor">
                {renderFrame ? (
                  <MeshViewer
                    meshData={renderFrame}
                    embedded
                    compactEmbedded
                    toolbarMode="zoom-only"
                    toolbarLabel="six wound teeth · PM rotor"
                    showMeshEdges
                    viewportPanEnabled={false}
                    pointLabels={pointLabels}
                    dipoleMarkers={showPmRotor && displayFrame ? [{
                      xMm: 0,
                      yMm: 0,
                      angleDeg: displayFrame.rotor_angle_deg,
                      lengthMm: displayFrame.rotor_radius_mm * 1.7,
                      thicknessMm: displayFrame.rotor_radius_mm * 0.72,
                      shape: 'surface-arcs',
                      rotorRadiusMm: displayFrame.rotor_radius_mm,
                      poleArcDeg: 132,
                      poleThicknessMm: displayFrame.rotor_radius_mm * 0.19,
                    }] : []}
                  />
                ) : (
                  <div className="rotating-field-solving-indicator"><i /> Loading the exact six-tooth geometry…</div>
                )}
              </div>
            </div>
            <section className="three-phase-connect-pole-order">
              <span>SIX WOUND TEETH · THREE PHASE PAIRS</span>
              <strong>A+ · C− · B+ · A− · C+ · B−</strong>
              <p>The shared star point stays inside the motor. Only L1, L2, and L3 leave the enclosure.</p>
            </section>
          </section>
        ) : renderFrame ? (
          <>
            <div className="rotating-field-viewer is-motor three-phase-viewer">
              {showThreeD ? (
                <div className="mesh-viewer-container mesh-viewer-container-embedded three-phase-three-shell">
                  <div className="three-phase-three-viewport">
                    <ThreePhaseMotor3D
                      frameData={displayFrame}
                      fieldMode={fieldMode}
                      showFieldIntensity={showFieldIntensity && Boolean(solvedFrame)}
                      fieldIntensityRange={intensityRange}
                      playing={playing}
                    />
                  </div>
                </div>
              ) : (
                <MeshViewer
                  meshData={renderFrame}
                  embedded
                  compactEmbedded
                  toolbarMode="zoom-only"
                  toolbarLabel={solvedFrame
                    ? `${modeLabel.toLowerCase()}${showFieldIntensity ? ' |B| map' : ''}${showFluxLines ? ' + flux lines' : ''}`
                    : 'actual Gmsh geometry · ready to energize'}
                  showMeshEdges={showMesh || !solvedFrame}
                  showFieldIntensity={showFieldIntensity && Boolean(solvedFrame)}
                  fieldIntensityRange={intensityRange}
                  smoothFieldIntensity
                  fieldLinesVisible={showFluxLines && Boolean(solvedFrame)}
                  animateFieldArrows={playing && showFluxLines}
                  viewportPanEnabled={false}
                  pointLabels={pointLabels}
                  directionVectors={solvedFrame ? directionVectors : []}
                  dipoleMarkers={showPmRotor && displayFrame ? [{
                    xMm: 0,
                    yMm: 0,
                    angleDeg: displayFrame.rotor_angle_deg,
                    lengthMm: displayFrame.rotor_radius_mm * 1.7,
                    thicknessMm: displayFrame.rotor_radius_mm * 0.72,
                    shape: 'surface-arcs',
                    rotorRadiusMm: displayFrame.rotor_radius_mm,
                    poleArcDeg: 132,
                    poleThicknessMm: displayFrame.rotor_radius_mm * 0.19,
                    animateTorque: playing,
                    torqueDirection: direction === 1 ? 'ccw' : 'cw',
                  }] : []}
                />
              )}
            </div>
          </>
        ) : (
          <section className="rotating-field-empty-stage">
            <div className="learning-stage-badge"><span>Part 1</span><strong>Three-phase PM motor</strong></div>
            <div className="rotating-field-solving-indicator"><i /> Loading the exact six-tooth Gmsh geometry…</div>
            {error ? <p className="rotating-field-error">{error}</p> : null}
          </section>
        )}
      </section>

      {lessonStage === 'solve' && labControlsOpen && !quizOpen ? <aside className="learning-control-panel rotating-field-control-panel three-phase-control-panel">
        <button type="button" className="tutorial-studio-panel-close" aria-label="Close lab controls" onClick={() => setLabControlsOpen(false)}>×</button>
        <section className="tutorial-studio-goal">
          <span>{currentStepId === 'connect' ? '1' : currentStepId === 'spin' ? '2' : currentStepId === 'stress' ? '3' : '4'}/4</span>
          <div>
            <p className="learning-kicker">Current goal</p>
            <h2>{currentStepId === 'connect'
              ? 'Connect the three windings'
              : currentStepId === 'spin'
                ? 'Spin the balanced field'
                : currentStepId === 'stress'
                  ? 'Break and reverse the drive'
                  : 'Explain the practical three-phase motor'}</h2>
          </div>
        </section>
        <section className="three-phase-lab-part-card">
          <span>PART 2</span>
          <strong>Six wound teeth + freely moving PM rotor</strong>
        </section>
        <h2>Three-phase PM motor lab</h2>
            {!sweeps.combined && busyMode ? (
              <section className="rotating-field-solve-card">
                <span>SCREEN LOADED · SOLVER RUNNING</span>
                <h3>32 angle-dependent FEM checkpoints</h3>
                <p>The exact Gmsh geometry stays visible while Magneto2D solves one full three-phase cycle.</p>
                <div className="rotating-field-solving-indicator"><i /> Solving balanced A + B + C frames…</div>
              </section>
            ) : !sweeps.combined ? (
              <section className="rotating-field-solve-card">
                <span>EXACT GEOMETRY READY</span>
                <h3>Energize all three phases</h3>
                <p>Solve one electrical cycle and release the PM rotor by default.</p>
              </section>
            ) : (
              <>
                <section className="rotating-field-follower-card">
                  <label>
                    <input
                      type="checkbox"
                      checked={rotorMotionAllowed}
                      onChange={(event) => {
                        const allowed = event.currentTarget.checked;
                        setRotorMotionAllowed(allowed);
                        if (!allowed) setPlaying(false);
                      }}
                    />
                    Allow rotor motion
                  </label>
                  <p>{rotorMotionAllowed
                    ? phaseCOpen ? 'On, but the open-phase FEM frames hold the rotor so you can inspect the failed rotating field.' : 'On · the PM rotor follows the rotating two-pole target.'
                    : 'Off · the solved rotor checkpoint is held for inspection.'}</p>
                </section>
                {displayFrame ? (
                  <section className="three-phase-current-card">
                    <header><span>{phaseCOpen ? 'OPEN-PHASE CURRENTS' : 'BALANCED CURRENTS'}</span><strong>{phaseCOpen ? 'fault' : '120° apart'}</strong></header>
                    <div className="is-a"><span>I<sub>A</sub></span><b>{signedCurrent(displayFrame.phase_a_current_a)}</b></div>
                    <div className="is-b"><span>I<sub>B</sub></span><b>{signedCurrent(displayFrame.phase_b_current_a)}</b></div>
                    <div className="is-c"><span>I<sub>C</sub></span><b>{phaseCOpen ? 'OPEN' : signedCurrent(displayFrame.phase_c_current_a)}</b></div>
                    <footer><span>I<sub>A</sub> + I<sub>B</sub> + I<sub>C</sub></span><strong>{signedCurrent(displayFrame.phase_current_sum_a)}</strong></footer>
                  </section>
                ) : null}
                <section className="three-phase-fault-card">
                  <span>PRACTICAL DRIVE CHECKS</span>
                  <button type="button" disabled={Boolean(busyMode)} className={phaseCOpen ? 'is-active' : ''} onClick={() => void loadSweep(phaseCOpen ? 'combined' : 'open_c')}>
                    {phaseCOpen ? 'Restore Phase C' : 'Open Phase C'}
                  </button>
                  <p>{phaseCOpen
                    ? 'C carries no current. A and B become equal and opposite, so the smooth rotating field is gone.'
                    : 'Open one motor lead to compare the healthy rotating field with a single-phasing fault.'}</p>
                </section>
                <section className="rotating-field-checklist is-in-panel">
                  <span className={cycleComplete ? 'is-done' : ''}>{cycleComplete ? '✓' : '1'} Spin through 0° → 360°</span>
                  <span className={inspectedOpenPhase ? 'is-done' : ''}>{inspectedOpenPhase ? '✓' : '2'} Inspect open Phase C</span>
                  <span className={reversedSequence ? 'is-done' : ''}>{reversedSequence ? '✓' : '3'} Swap B/C to reverse</span>
                </section>
              </>
            )}
        {error ? <p className="rotating-field-error">{error}</p> : null}
        <footer className="learning-panel-footer">
          {quizOpen && isLessonComplete('three-phase-motor') ? (
            <a className="learning-primary-button learning-next-lesson" href="/tutorials/lesson-9">Next lesson: Build the 2p/6s Motor</a>
          ) : null}
          <div className="learning-panel-nav">
            <button type="button" className="learning-ghost-button" onClick={onBackToCatalog}>Lessons</button>
            <button type="button" className="learning-ghost-button" onClick={onBackHome}>Design start</button>
          </div>
        </footer>
      </aside> : null}

      {solveInspectorOpen && !quizOpen ? <aside className="learning-context-panel rotating-field-results-panel three-phase-results-panel" aria-label="Lesson guidance and solved results">
        <button type="button" className="tutorial-studio-panel-close" aria-label="Close solved results" onClick={() => setSolveInspectorOpen(false)}>×</button>
        <p className="learning-kicker">Solved output</p>
        {quizOpen ? (
          <section className="rotating-field-takeaway">
            <h2>Three lines create a smooth rotating target.</h2>
            <p>Balanced phase currents sum to zero at the internal Wye point while their six tooth fields combine into one rotating two-pole field.</p>
          </section>
        ) : lessonStage === 'design' ? (
          <>
            <WyeConnectionCard />
            <section className="three-phase-pole-order">
              <span>SIX TEETH · TWO MAGNETIC POLES</span>
              <strong>A+ · C− · B+ · A− · C+ · B−</strong>
              <p>Each phase owns two opposing teeth. The “six” counts electromagnets, not magnetic poles.</p>
            </section>
          </>
        ) : displayFrame ? (
          <section className="three-phase-results">
            <header>
              <div><p className="learning-kicker">Three-phase drive</p><h2>{phaseCOpen ? 'Opening Phase C breaks the smooth rotating field.' : 'Balanced currents stay 120° apart.'}</h2></div>
              <span>θe = {displayCycleAngle(electricalAngle)}°</span>
            </header>
            {!phaseCOpen ? (
              <DriveComparison
                angleDeg={electricalAngle}
                phaseACurrentA={displayFrame.phase_a_current_a}
                phaseBCurrentA={displayFrame.phase_b_current_a}
                phaseCCurrentA={displayFrame.phase_c_current_a}
              />
            ) : null}
            <ThreePhaseWaveform
              angleDeg={electricalAngle}
              phaseACurrentA={displayFrame.phase_a_current_a}
              phaseBCurrentA={displayFrame.phase_b_current_a}
              phaseCCurrentA={displayFrame.phase_c_current_a}
              phaseCOpen={phaseCOpen}
              onSelectAngle={selectAngle}
            />
            <section className="three-phase-current-card">
              <header><span>{phaseCOpen ? 'OPEN-PHASE CURRENTS' : 'BALANCED CURRENTS'}</span><strong>{phaseCOpen ? 'fault' : '120° apart'}</strong></header>
              <div className="is-a"><span>I<sub>A</sub></span><b>{signedCurrent(displayFrame.phase_a_current_a)}</b></div>
              <div className="is-b"><span>I<sub>B</sub></span><b>{signedCurrent(displayFrame.phase_b_current_a)}</b></div>
              <div className="is-c"><span>I<sub>C</sub></span><b>{phaseCOpen ? 'OPEN' : signedCurrent(displayFrame.phase_c_current_a)}</b></div>
              <footer><span>I<sub>A</sub> + I<sub>B</sub> + I<sub>C</sub></span><strong>{signedCurrent(displayFrame.phase_current_sum_a)}</strong></footer>
            </section>
          </section>
        ) : (
          <section className="rotating-field-meaning-card">
            <span>WAITING FOR SOLVE</span>
            <strong>The phase waveform, current balance, and fault comparison will appear here.</strong>
          </section>
        )}
      </aside> : null}

      <section className={`tutorial-studio-dock rotating-field-studio-dock three-phase-studio-dock${showDockPlayback ? ' has-playback' : ''}`} aria-label="Lesson controls">
        <div className="rotating-field-dock-context">
          <span>{quizOpen ? 'CHECK' : lessonStage === 'design' ? 'CONNECT WYE' : cycleComplete ? 'STRESS DRIVE' : 'SPIN FIELD'}</span>
          <strong>{quizOpen
            ? 'Explain why three wires can create one smooth rotating field.'
            : lessonStage === 'design'
              ? 'Connect three windings around one internal neutral.'
              : labComplete
                ? 'You spun, faulted, and reversed the practical drive.'
                : 'Run one balanced cycle, open a phase, then reverse the sequence.'}</strong>
        </div>
        {showDockPlayback ? (
          <div className="rotating-field-dock-playback">
            <label>
              <span>Electrical angle</span>
              <strong>{displayCycleAngle(electricalAngle)}°</strong>
              <input
                type="range"
                min="0"
                max={frames.length}
                step="1"
                value={frameIndex}
                onChange={(event) => selectFrame(Number(event.currentTarget.value))}
                aria-label="Solved three-phase electrical angle frame"
              />
            </label>
            <div className="rotating-field-dock-playback-buttons">
              <button
                type="button"
                disabled={!rotorMotionAllowed || phaseCOpen}
                className={`rotating-field-dock-play-primary${playing ? ' is-active' : ''}`}
                onClick={() => (playing ? setPlaying(false) : playCycle())}
              >
                {playing ? 'Pause cycle' : 'Play cycle'}
              </button>
              <button type="button" className="rotating-field-dock-sequence" onClick={swapTwoPhases}>
                {direction === 1 ? 'A–B–C · CCW' : 'A–C–B · CW'}
              </button>
            </div>
          </div>
        ) : null}
        <div className="tutorial-studio-dock-actions">
          {!quizOpen && lessonStage === 'solve' && !sweeps.combined ? <button type="button" className={labControlsOpen ? 'is-active' : ''} onClick={() => setLabControlsOpen((open) => !open)}>{labControlsOpen ? 'Done' : 'Adjust experiment'}</button> : null}
          {!quizOpen && lessonStage === 'solve' ? <button type="button" className={solveInspectorOpen ? 'is-active' : ''} disabled={!displayFrame} onClick={() => setSolveInspectorOpen((open) => !open)}>Inspect results</button> : null}
          {quizOpen ? <button type="button" onClick={() => setQuizOpen(false)}>Review experiment</button> : null}
          {quizOpen ? (
            quizPassed
              ? <a className="learning-primary-button" href="/tutorials/lesson-9">Next lesson</a>
              : <button type="button" className="learning-primary-button" disabled>Pass the check</button>
          ) : lessonStage === 'design' ? (
            <button type="button" className="learning-primary-button" disabled={Boolean(busyMode)} onClick={() => {
              setLabControlsOpen(false);
              enterLab();
            }}>{busyMode ? 'Solving…' : 'Energize motor'}</button>
          ) : !sweeps.combined ? (
            <button type="button" className="learning-primary-button" disabled={Boolean(busyMode)} onClick={() => void loadSweep('combined', { autoPlay: true })}>{busyMode ? 'Solving…' : 'Solve + spin rotor'}</button>
          ) : labComplete ? (
            <button type="button" className="learning-primary-button" onClick={() => {
              setPlaying(false);
              setLabControlsOpen(false);
              setSolveInspectorOpen(false);
              setQuizOpen(true);
            }}>Continue to check</button>
          ) : (
            <button
              type="button"
              className="learning-primary-button"
              disabled={Boolean(busyMode) || (playing && !cycleComplete)}
              onClick={advanceDriveChecks}
            >{busyMode ? 'Solving…' : driveCheckActionLabel}</button>
          )}
        </div>
      </section>
    </main>
  );
};
