import React from 'react';
import type {
  RotatingFieldFrameData,
  RotatingFieldMotorFrameData,
  RotatingFieldMotorSweepData,
  RotatingFieldSweepData,
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
import { RotatingFieldCoils3D } from './RotatingFieldCoils3D';
import { TwoPhaseMotor3D } from './TwoPhaseMotor3D';
import { BACK_EMF_PHASE_COLORS } from './phaseColors';
import './learning.css';
import './rotating-field.css';

interface LearningLessonSevenRotatingFieldProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'quadrature' | 'together' | 'one-phase';
type PhaseFieldMode = 'combined' | 'phase-a' | 'phase-b';
type MotorFieldMode = 'combined' | 'stator' | 'rotor';
type MotorViewMode = 'fem' | 'three';
type RotationDirection = 1 | -1;
type DesignDiagramMode = 'slice' | 'physical';
type LabPart = 'field' | 'motor';

const PEAK_CURRENT_A = 8;
const COIL_OFFSET_MM = 22;
const FIELD_VECTOR_LENGTH_MM = 16;
const RESULTANT_FIELD_COLOR = '#92ba65';
const FRAME_STEP_DEG = 45 / 4;
const FRAME_COUNT = Math.round(360 / FRAME_STEP_DEG);
const QUARTER_FRAME_INDEX = Math.round(90 / FRAME_STEP_DEG);
const PLAY_INTERVAL_MS = 240;

const QUIZ: KnowledgeCheckQuestion[] = [
  {
    id: 'rotate-source',
    prompt: 'What creates the rotating field in this two-phase fixture?',
    options: [
      'Two winding axes driven with exactly the same waveform',
      'Two perpendicular winding axes driven 90 electrical degrees apart',
      'One DC current held on a single axis',
    ],
    correctIndex: 1,
    explanation: 'Phase A follows cosine while Phase B follows sine. Their perpendicular field components add to a vector whose direction rotates.',
  },
  {
    id: 'rotate-rotor',
    prompt: 'Why does the center PM rotor keep turning instead of aligning once and stopping?',
    options: [
      'The permanent magnet loses its poles every half-cycle',
      'The four iron poles physically rotate around the rotor',
      'The two-phase field keeps advancing its alignment target',
    ],
    correctIndex: 2,
    explanation: 'The stator and windings stay fixed. Quadrature current moves the magnetic target, so PM alignment torque keeps pulling the rotor forward.',
  },
  {
    id: 'rotate-sequence',
    prompt: 'What happens if the phase sequence is reversed?',
    options: ['The field and rotor reverse rotation', 'The field becomes twice as strong', 'The field stops changing'],
    correctIndex: 0,
    explanation: 'Reversing the quadrature sequence reverses the direction in which the magnetic target advances.',
  },
  {
    id: 'rotate-single-phase',
    prompt: 'What does one sinusoidal phase make by itself?',
    options: [
      'A constant-speed rotating field',
      'A field that pulsates along a fixed axis',
      'No magnetic field',
    ],
    correctIndex: 1,
    explanation: 'One phase grows and reverses on one spatial axis. The perpendicular phase supplies the missing rotating component.',
  },
];

const normalizeAngle = (angleDeg: number) => ((angleDeg % 360) + 360) % 360;
const displayAngle = (angleDeg: number) => Number(normalizeAngle(angleDeg).toFixed(2)).toString();
const displayCycleAngle = (angleDeg: number) => (
  Math.abs(angleDeg - 360) < 0.1 ? '360' : displayAngle(angleDeg)
);
const signedCurrent = (currentA: number) => (
  `${currentA > 0 ? '+' : ''}${Math.abs(currentA) < 0.05 ? '0.0' : currentA.toFixed(1)} A`
);
const currentGlyph = (currentA: number) => (currentA > 0.05 ? '⊙' : currentA < -0.05 ? '⊗' : '○');
const currentLabel = (phase: string, currentA: number) => `${phase} ${currentGlyph(currentA)}`;
const fieldMilliTesla = (fieldT: number) => `${(fieldT * 1e3).toFixed(3)} mT`;
const frameAngle = (frame: RotatingFieldFrameData) => normalizeAngle(
  frame.metrics?.center_field_angle_deg ?? frame.electrical_angle_deg,
);

const RotatingFieldPredictionDiagram: React.FC = () => (
  <svg className="rotating-field-prediction" viewBox="0 0 860 500" role="img" aria-label="Two perpendicular winding axes and their rotating resultant field">
    <defs>
      <marker id="rotatingPredictionArrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
        <path d="M0,0 L9,4.5 L0,9 Z" fill="#67e8f9" />
      </marker>
    </defs>
    <circle cx="430" cy="250" r="170" className="rotating-field-orbit" />
    <circle cx="430" cy="250" r="82" className="rotating-field-rotor-ghost" />
    <g className="rotating-field-phase-a">
      <circle cx="430" cy="80" r="46" />
      <circle cx="430" cy="420" r="46" />
      <text x="430" y="70" className="rotating-field-conductor-phase">A+</text>
      <text x="430" y="104" className="rotating-field-current-glyph">⊙</text>
      <text x="430" y="410" className="rotating-field-conductor-phase">A−</text>
      <text x="430" y="444" className="rotating-field-current-glyph">⊗</text>
    </g>
    <g className="rotating-field-phase-b">
      <circle cx="260" cy="250" r="46" />
      <circle cx="600" cy="250" r="46" />
      <text x="260" y="240" className="rotating-field-conductor-phase">B+</text>
      <text x="260" y="274" className="rotating-field-current-glyph">⊙</text>
      <text x="600" y="240" className="rotating-field-conductor-phase">B−</text>
      <text x="600" y="274" className="rotating-field-current-glyph">⊗</text>
    </g>
    <path d="M430 250 L555 150" className="rotating-field-resultant" markerEnd="url(#rotatingPredictionArrow)" />
    <path d="M556 150 A205 205 0 0 1 665 250" className="rotating-field-arc" markerEnd="url(#rotatingPredictionArrow)" />
    <text x="430" y="22" className="rotating-field-diagram-label">TWO AXES · TWO CURRENTS · ONE ROTATING TARGET</text>
    <text x="570" y="132" className="rotating-field-vector-label">Resultant B</text>
    <text x="690" y="455" className="rotating-field-current-legend">⊙ OUT (+Z) · ⊗ INTO (−Z)</text>
  </svg>
);

const RotatingFieldMotorGeometryDiagram: React.FC = () => (
  <svg className="rotating-field-motor-geometry" viewBox="0 0 860 500" role="img" aria-label="Four wound M350-50A poles surrounding a permanent-magnet rotor">
    <circle cx="430" cy="250" r="205" className="rotating-field-motor-domain" />
    <g className="rotating-field-motor-cores">
      <rect x="392" y="48" width="76" height="154" />
      <rect x="392" y="298" width="76" height="154" />
      <rect x="178" y="212" width="214" height="76" />
      <rect x="468" y="212" width="214" height="76" />
      <text x="430" y="118">M350-50A</text>
      <text x="430" y="390">M350-50A</text>
      <text x="270" y="255">M350-50A</text>
      <text x="590" y="255">M350-50A</text>
    </g>
    <g className="rotating-field-motor-coils is-a">
      <circle cx="282" cy="184" r="24" />
      <circle cx="282" cy="316" r="24" />
      <circle cx="578" cy="184" r="24" />
      <circle cx="578" cy="316" r="24" />
      <text x="282" y="190">⊙</text>
      <text x="282" y="322">⊗</text>
      <text x="578" y="190">⊙</text>
      <text x="578" y="322">⊗</text>
    </g>
    <g className="rotating-field-motor-coils is-b">
      <circle cx="364" cy="128" r="24" />
      <circle cx="496" cy="128" r="24" />
      <circle cx="364" cy="372" r="24" />
      <circle cx="496" cy="372" r="24" />
      <text x="364" y="134">○</text>
      <text x="496" y="134">○</text>
      <text x="364" y="378">○</text>
      <text x="496" y="378">○</text>
    </g>
    <g className="rotating-field-motor-rotor" transform="rotate(-15 430 250)">
      <circle cx="430" cy="250" r="55" />
      <path d="M375 250 A55 55 0 0 1 430 195 L430 305 A55 55 0 0 1 375 250Z" className="is-south" />
      <path d="M430 195 A55 55 0 0 1 485 250 A55 55 0 0 1 430 305Z" className="is-north" />
      <text x="401" y="257">S</text>
      <text x="459" y="257">N</text>
    </g>
    <text x="430" y="28" className="rotating-field-motor-geometry-title">ACTUAL FOUR-POLE CROSS-SECTION · GMSH GEOMETRY LOADING</text>
    <text x="430" y="484" className="rotating-field-motor-geometry-caption">PHASE A · HORIZONTAL POLES  PHASE B · VERTICAL POLES  N42 PM ROTOR</text>
  </svg>
);

interface PhaseWaveformProps {
  angleDeg: number;
  phaseACurrentA: number;
  phaseBCurrentA: number;
  onSelectAngle: (angleDeg: number) => void;
}

const PhaseWaveform: React.FC<PhaseWaveformProps> = ({
  angleDeg,
  phaseACurrentA,
  phaseBCurrentA,
  onSelectAngle,
}) => {
  const width = 720;
  const height = 210;
  const margin = { top: 24, right: 24, bottom: 42, left: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xFor = (angle: number) => margin.left + (angle / 360) * plotWidth;
  const yFor = (current: number) => (
    margin.top + plotHeight / 2 - (current / PEAK_CURRENT_A) * (plotHeight * 0.42)
  );
  const angles = Array.from({ length: 73 }, (_, index) => index * 5);
  const phaseA = angles.map((angle) => (
    `${xFor(angle)},${yFor(PEAK_CURRENT_A * Math.cos(angle * Math.PI / 180))}`
  )).join(' ');
  const phaseB = angles.map((angle) => (
    `${xFor(angle)},${yFor(PEAK_CURRENT_A * Math.sin(angle * Math.PI / 180))}`
  )).join(' ');
  const selectedX = xFor(Math.abs(angleDeg - 360) < 0.1 ? 360 : normalizeAngle(angleDeg));

  return (
    <div className="rotating-field-waveform-wrap">
      <div className="rotating-field-waveform-legend">
        <span className="is-a">Phase A · cos θ</span>
        <span className="is-b">Phase B · sin θ</span>
      </div>
      <svg className="rotating-field-waveform" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Quadrature Phase A and Phase B current waveforms">
        <g className="rotating-field-waveform-grid">
          {[-PEAK_CURRENT_A, 0, PEAK_CURRENT_A].map((current) => (
            <line key={current} x1={margin.left} y1={yFor(current)} x2={width - margin.right} y2={yFor(current)} />
          ))}
          {[0, 90, 180, 270, 360].map((angle) => (
            <line key={angle} x1={xFor(angle)} y1={margin.top} x2={xFor(angle)} y2={height - margin.bottom} />
          ))}
        </g>
        <polyline className="is-a" points={phaseA} />
        <polyline className="is-b" points={phaseB} />
        <line className="rotating-field-waveform-cursor" x1={selectedX} y1={margin.top} x2={selectedX} y2={height - margin.bottom} />
        <circle className="is-a" cx={selectedX} cy={yFor(phaseACurrentA)} r="6" />
        <circle className="is-b" cx={selectedX} cy={yFor(phaseBCurrentA)} r="6" />
        <g className="rotating-field-waveform-ticks">
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
            className="rotating-field-waveform-hit"
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

export const LearningLessonSevenRotatingField: React.FC<LearningLessonSevenRotatingFieldProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const lessonStage: 'design' | 'solve' = stage === 'design' ? 'design' : 'solve';
  const [prediction, setPrediction] = React.useState<Prediction | null>(null);
  const [fieldSweep, setFieldSweep] = React.useState<RotatingFieldSweepData | null>(null);
  const [motorGeometry, setMotorGeometry] = React.useState<RotatingFieldMotorFrameData | null>(null);
  const [motorSweep, setMotorSweep] = React.useState<RotatingFieldMotorSweepData | null>(null);
  const [motorStatorSweep, setMotorStatorSweep] = React.useState<RotatingFieldMotorSweepData | null>(null);
  const [motorRotorSweep, setMotorRotorSweep] = React.useState<RotatingFieldMotorSweepData | null>(null);
  const [labPart, setLabPart] = React.useState<LabPart>('field');
  const [fieldFrameIndex, setFieldFrameIndex] = React.useState(0);
  const [motorFrameIndex, setMotorFrameIndex] = React.useState(0);
  // Match the public Solve player: clockwise is the default teaching sequence.
  // Reversing the sequence remains an explicit experiment in the lesson.
  const [direction, setDirection] = React.useState<RotationDirection>(-1);
  const [playing, setPlaying] = React.useState(false);
  const [playSteps, setPlaySteps] = React.useState(0);
  const [fieldCycleComplete, setFieldCycleComplete] = React.useState(false);
  const [motorCycleComplete, setMotorCycleComplete] = React.useState(false);
  const [visitedFieldFrames, setVisitedFieldFrames] = React.useState<Set<number>>(() => new Set());
  const [busyField, setBusyField] = React.useState(false);
  const [busyMotor, setBusyMotor] = React.useState(false);
  const [busyMotorFieldMode, setBusyMotorFieldMode] = React.useState<MotorFieldMode | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showFluxLines, setShowFluxLines] = React.useState(true);
  const [showFieldIntensity, setShowFieldIntensity] = React.useState(false);
  const [phaseFieldMode, setPhaseFieldMode] = React.useState<PhaseFieldMode>('combined');
  const [motorFieldMode, setMotorFieldMode] = React.useState<MotorFieldMode>('combined');
  const [motorViewMode, setMotorViewMode] = React.useState<MotorViewMode>('fem');
  const [showMesh, setShowMesh] = React.useState(false);
  const [showElectromagnets, setShowElectromagnets] = React.useState(true);
  const [showPmRotor, setShowPmRotor] = React.useState(true);
  const [designDiagramMode, setDesignDiagramMode] = React.useState<DesignDiagramMode>('physical');
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(false);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const motorGeometryRequest = React.useRef<Promise<void> | null>(null);
  const mainStageRef = React.useRef<HTMLElement | null>(null);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();

  const predictionCorrect = prediction === 'quadrature';
  const fieldFrames = fieldSweep?.frames ?? [];
  const phaseAFrames = fieldSweep?.phase_a_frames ?? [];
  const phaseBFrames = fieldSweep?.phase_b_frames ?? [];
  const motorFrames = motorSweep?.frames ?? [];
  const motorStatorFrames = motorStatorSweep?.frames ?? [];
  const motorRotorFrames = motorRotorSweep?.frames ?? [];
  const fieldFrame = fieldFrames[fieldFrameIndex] ?? null;
  const phaseViewerFrames = phaseFieldMode === 'phase-a'
    ? phaseAFrames
    : phaseFieldMode === 'phase-b'
      ? phaseBFrames
      : fieldFrames;
  const phaseViewerFrame = phaseViewerFrames[fieldFrameIndex] ?? fieldFrame;
  const motorFrameLookupIndex = motorFrames.length
    ? motorFrameIndex % motorFrames.length
    : 0;
  const motorFrame = motorFrames[motorFrameLookupIndex] ?? null;
  const motorViewerFrames = motorFieldMode === 'stator'
    ? motorStatorFrames
    : motorFieldMode === 'rotor'
      ? motorRotorFrames
      : motorFrames;
  const motorViewerFrame = motorViewerFrames[motorFrameLookupIndex] ?? motorFrame;
  const motorDisplayFrame = motorViewerFrame ?? motorGeometry;
  const motorElectricalAngle = motorFrames.length && motorFrameIndex === motorFrames.length
    ? 360
    : motorFrame?.field_target_angle_deg ?? motorDisplayFrame?.field_target_angle_deg ?? 0;
  const activeFrame = labPart === 'motor' ? motorDisplayFrame : phaseViewerFrame;
  const activeFrames = labPart === 'motor'
    ? motorViewerFrames.length > 0 ? motorViewerFrames : motorGeometry ? [motorGeometry] : []
    : phaseViewerFrames;
  const inspectedZero = visitedFieldFrames.has(0);
  const inspectedQuarter = visitedFieldFrames.has(QUARTER_FRAME_INDEX);
  const fieldLabComplete = inspectedZero && inspectedQuarter && fieldCycleComplete;
  const motorLabComplete = motorCycleComplete;

  React.useEffect(() => {
    if (stage === 'mesh') onStageChange?.('solve');
  }, [stage, onStageChange]);

  React.useEffect(() => {
    if (quizPassed) setLessonComplete('rotating-field', true);
  }, [quizPassed, setLessonComplete]);

  React.useLayoutEffect(() => {
    mainStageRef.current?.scrollTo({ top: 0 });
  }, [labPart, lessonStage, quizOpen]);

  React.useEffect(() => {
    if (!playing) return undefined;
    const frameCount = labPart === 'field' ? fieldFrames.length : motorFrames.length;
    if (!frameCount) return undefined;
    const timer = window.setInterval(() => {
      if (labPart === 'field') {
        setFieldFrameIndex((previous) => (
          direction === 1
            ? (previous + 1) % frameCount
            : (previous - 1 + frameCount) % frameCount
        ));
      } else {
        setMotorFrameIndex((previous) => (
          direction === 1
            ? previous >= frameCount ? 1 : previous + 1
            : previous <= 0 ? frameCount - 1 : previous - 1
        ));
      }
      setPlaySteps((previous) => {
        const next = previous + 1;
        if (next >= frameCount) {
          if (labPart === 'field') setFieldCycleComplete(true);
          else setMotorCycleComplete(true);
          setPlaying(false);
        }
        return next;
      });
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [
    direction,
    fieldFrames.length,
    labPart,
    motorFrames.length,
    playing,
  ]);

  React.useEffect(() => {
    if (!fieldFrame) return;
    setVisitedFieldFrames((previous) => {
      if (previous.has(fieldFrameIndex)) return previous;
      const next = new Set(previous);
      next.add(fieldFrameIndex);
      return next;
    });
  }, [fieldFrame, fieldFrameIndex]);

  const enterSolveStage = React.useCallback(() => {
    setQuizOpen(false);
    onStageChange?.('solve');
  }, [onStageChange]);

  const loadMotorGeometry = () => {
    if (motorGeometry || motorGeometryRequest.current) return motorGeometryRequest.current;
    const request = solveClient.fetchRotatingFieldMotorGeometry()
      .then((geometry) => {
        setMotorGeometry(geometry);
      })
      .catch(() => {
        // The accurate local cross-section remains visible while the solved
        // sweep retries the same Gmsh geometry.
      })
      .finally(() => {
        motorGeometryRequest.current = null;
      });
    motorGeometryRequest.current = request;
    return request;
  };

  const solveFieldSweep = async () => {
    setBusyField(true);
    setError(null);
    try {
      const result = await solveClient.fetchRotatingFieldSweep(PEAK_CURRENT_A);
      if (
        result.frames.length !== FRAME_COUNT
        || result.phase_a_frames.length !== FRAME_COUNT
        || result.phase_b_frames.length !== FRAME_COUNT
      ) {
        throw new Error('The solver did not return the complete 11.25° cycle.');
      }
      setFieldSweep(result);
      setFieldFrameIndex(0);
      setVisitedFieldFrames(new Set([0]));
      void loadMotorGeometry();
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The rotating-field sweep failed.');
    } finally {
      setBusyField(false);
    }
  };

  const solveMotorSweep = async () => {
    setBusyMotor(true);
    setError(null);
    try {
      const result = await solveClient.fetchRotatingFieldMotorSweep(PEAK_CURRENT_A, 'combined');
      if (result.frames.length !== FRAME_COUNT) {
        throw new Error('The solver did not return the complete four-pole motor cycle.');
      }
      setMotorSweep(result);
      setMotorFrameIndex(0);
      setPlaySteps(0);
      setPlaying(true);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : 'The four-pole motor sweep failed.');
    } finally {
      setBusyMotor(false);
    }
  };

  const selectMotorFieldMode = async (mode: MotorFieldMode) => {
    setPlaying(false);
    if (
      mode === 'combined'
      || (mode === 'stator' && motorStatorSweep)
      || (mode === 'rotor' && motorRotorSweep)
    ) {
      setMotorFieldMode(mode);
      return;
    }
    if (busyMotorFieldMode) return;
    setBusyMotorFieldMode(mode);
    setError(null);
    try {
      const result = await solveClient.fetchRotatingFieldMotorSweep(PEAK_CURRENT_A, mode);
      if (result.frames.length !== FRAME_COUNT || result.field_component !== mode) {
        throw new Error(`The solver did not return the complete ${mode}-only motor cycle.`);
      }
      if (mode === 'stator') setMotorStatorSweep(result);
      else setMotorRotorSweep(result);
      setMotorFieldMode(mode);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : `The ${mode}-only motor sweep failed.`);
    } finally {
      setBusyMotorFieldMode(null);
    }
  };

  const continueToMotor = () => {
    setPlaying(false);
    setQuizOpen(false);
    setPlaySteps(0);
    setLabPart('motor');
    if (!motorGeometry) void loadMotorGeometry();
    if (!motorSweep && !busyMotor) void solveMotorSweep();
  };

  const startPlaying = () => {
    setPlaySteps(0);
    setPlaying(true);
  };

  const selectActiveFrame = (index: number) => {
    setPlaying(false);
    const frameCount = labPart === 'field' ? fieldFrames.length : motorFrames.length;
    if (!frameCount) return;
    if (labPart === 'field') {
      setFieldFrameIndex((index + frameCount) % frameCount);
    } else if (index < 0) {
      setMotorFrameIndex(frameCount - 1);
    } else if (index > frameCount) {
      setMotorFrameIndex(1);
    } else {
      setMotorFrameIndex(index);
    }
  };

  const selectFieldAngle = (angleDeg: number) => {
    const index = fieldFrames.findIndex((item) => (
      Math.abs(normalizeAngle(item.electrical_angle_deg) - normalizeAngle(angleDeg)) < 0.1
    ));
    if (index >= 0) {
      setPlaying(false);
      setFieldFrameIndex(index);
    }
  };

  const selectPhaseContribution = (mode: PhaseFieldMode) => {
    setPlaying(false);
    setPhaseFieldMode(mode);
    if (mode === 'combined' || fieldFrames.length === 0) return;

    const phaseCurrent = (frame: RotatingFieldFrameData) => (
      mode === 'phase-a' ? frame.phase_a_current_a : frame.phase_b_current_a
    );
    const activeMagnitude = Math.abs(phaseCurrent(fieldFrames[fieldFrameIndex] ?? fieldFrames[0]));
    const peakIndex = fieldFrames.reduce((bestIndex, frame, index) => (
      Math.abs(phaseCurrent(frame)) > Math.abs(phaseCurrent(fieldFrames[bestIndex]))
        ? index
        : bestIndex
    ), 0);
    const peakMagnitude = Math.abs(phaseCurrent(fieldFrames[peakIndex]));

    // At a phase's zero crossing, a valid phase-only solve looks like an empty
    // field. Move to its strongest solved checkpoint so the contribution is
    // visible immediately; otherwise preserve the user's electrical angle.
    if (peakMagnitude > 0 && activeMagnitude <= peakMagnitude * 0.02) {
      setFieldFrameIndex(peakIndex);
    }
  };

  const selectMotorAngle = (angleDeg: number) => {
    if (Math.abs(angleDeg - 360) < 0.1 && motorFrames.length) {
      setPlaying(false);
      setMotorFrameIndex(motorFrames.length);
      return;
    }
    const index = motorFrames.findIndex((item) => (
      Math.abs(normalizeAngle(item.electrical_angle_deg) - normalizeAngle(angleDeg)) < 0.1
    ));
    if (index >= 0) {
      setPlaying(false);
      setMotorFrameIndex(index);
    }
  };

  const phaseMagnitudeSpreadPct = React.useMemo(() => {
    const magnitudes = fieldFrames
      .map((item) => item.metrics?.center_b_t)
      .filter((value): value is number => (
        value !== null && value !== undefined && Number.isFinite(value)
      ));
    if (!magnitudes.length) return null;
    const mean = magnitudes.reduce((sum, value) => sum + value, 0) / magnitudes.length;
    return mean > 0 ? ((Math.max(...magnitudes) - Math.min(...magnitudes)) / mean) * 100 : 0;
  }, [fieldFrames]);

  const intensityRange = React.useMemo(() => {
    const values = activeFrames
      .flatMap((item) => item.element_b_mag_t ?? [])
      .filter((value) => Number.isFinite(value) && value >= 0);
    if (!values.length) return undefined;
    const sorted = [...values].sort((left, right) => left - right);
    return {
      low: sorted[Math.floor(sorted.length * 0.03)],
      high: sorted[Math.floor(sorted.length * 0.98)],
    };
  }, [activeFrames]);

  const renderFrame = React.useMemo(() => {
    if (labPart !== 'motor' || !activeFrame) return activeFrame;
    return {
      ...activeFrame,
      regions: activeFrame.regions.map((region, triangleIndex) => {
        const hiddenElectromagnet = !showElectromagnets
          && (region === 'motor_stator_pole' || region.startsWith('phase_'));
        const hiddenRotor = !showPmRotor && region === 'motor_rotor_magnet';
        if (hiddenElectromagnet || hiddenRotor) return 'air';
        if (region === 'motor_rotor_magnet') return 'rotor_core';
        if (region === 'motor_stator_pole') {
          const triangle = activeFrame.triangles[triangleIndex];
          const nodes = triangle?.map((nodeIndex) => activeFrame.nodes_mm[nodeIndex]).filter(Boolean) ?? [];
          if (nodes.length === 3) {
            const centerX = nodes.reduce((sum, node) => sum + node[0], 0) / nodes.length;
            const centerY = nodes.reduce((sum, node) => sum + node[1], 0) / nodes.length;
            return Math.abs(centerX) >= Math.abs(centerY)
              ? 'two_phase_stator_tooth_a'
              : 'two_phase_stator_tooth_b';
          }
        }
        return region;
      }),
    };
  }, [activeFrame, labPart, showElectromagnets, showPmRotor]);

  const fieldPointLabels: MeshViewerPointLabel[] = phaseViewerFrame ? [
    { xMm: 0, yMm: COIL_OFFSET_MM, label: currentLabel('A+', phaseViewerFrame.phase_a_current_a), tone: 'neutral' },
    { xMm: 0, yMm: -COIL_OFFSET_MM, label: currentLabel('A−', -phaseViewerFrame.phase_a_current_a), tone: 'neutral' },
    { xMm: -COIL_OFFSET_MM, yMm: 0, label: currentLabel('B+', phaseViewerFrame.phase_b_current_a), tone: 'neutral' },
    { xMm: COIL_OFFSET_MM, yMm: 0, label: currentLabel('B−', -phaseViewerFrame.phase_b_current_a), tone: 'neutral' },
  ] : [];

  const motorPointLabels: MeshViewerPointLabel[] = motorDisplayFrame && showElectromagnets ? (() => {
    const a = motorDisplayFrame.phase_a_current_a;
    const b = motorDisplayFrame.phase_b_current_a;
    const center = motorDisplayFrame.coil_center_mm;
    const side = motorDisplayFrame.coil_side_mm;
    return [
      { xMm: -center, yMm: side, label: currentGlyph(a), tone: 'neutral' },
      { xMm: -center, yMm: -side, label: currentGlyph(-a), tone: 'neutral' },
      { xMm: center, yMm: side, label: currentGlyph(a), tone: 'neutral' },
      { xMm: center, yMm: -side, label: currentGlyph(-a), tone: 'neutral' },
      { xMm: -side, yMm: center, label: currentGlyph(b), tone: 'neutral' },
      { xMm: side, yMm: center, label: currentGlyph(-b), tone: 'neutral' },
      { xMm: -side, yMm: -center, label: currentGlyph(b), tone: 'neutral' },
      { xMm: side, yMm: -center, label: currentGlyph(-b), tone: 'neutral' },
    ];
  })() : [];

  const fieldDirectionAngle = phaseViewerFrame ? frameAngle(phaseViewerFrame) : 0;
  const fieldMagnitudeT = phaseViewerFrame?.metrics?.center_b_t ?? 0;
  const fieldMagnitudeScaleT = React.useMemo(() => Math.max(
    0,
    ...phaseViewerFrames.map((frame) => frame.metrics?.center_b_t ?? 0),
  ), [phaseViewerFrames]);
  const activeElectricalAngle = labPart === 'motor'
    ? motorElectricalAngle
    : fieldFrame?.electrical_angle_deg ?? 0;
  const directionVectors: MeshViewerDirectionVector[] = activeFrame ? (() => {
    const fieldAngleDeg = labPart === 'motor'
      ? motorFieldMode === 'rotor'
        ? motorDisplayFrame?.rotor_angle_deg ?? 0
        : motorDisplayFrame?.field_target_angle_deg ?? 0
      : fieldDirectionAngle;
    const fieldAngleRad = fieldAngleDeg * Math.PI / 180;
    const fieldVectorScale = fieldMagnitudeScaleT > 0
      ? Math.min(1, Math.max(0, fieldMagnitudeT / fieldMagnitudeScaleT))
      : 0;
    const fieldVectorLengthMm = FIELD_VECTOR_LENGTH_MM * fieldVectorScale;
    const fieldVectorLabel = phaseFieldMode === 'phase-a'
      ? `Bₐ ${fieldMilliTesla(fieldMagnitudeT)}`
      : phaseFieldMode === 'phase-b'
        ? `Bᵦ ${fieldMilliTesla(fieldMagnitudeT)}`
        : `B resultant ${fieldMilliTesla(fieldMagnitudeT)}`;
    const fieldVectorPalette = phaseFieldMode === 'phase-a'
      ? {
        colorStart: BACK_EMF_PHASE_COLORS.A,
        colorEnd: BACK_EMF_PHASE_COLORS.A,
        labelColor: BACK_EMF_PHASE_COLORS.A,
      }
      : phaseFieldMode === 'phase-b'
        ? {
          colorStart: BACK_EMF_PHASE_COLORS.B,
          colorEnd: BACK_EMF_PHASE_COLORS.B,
          labelColor: BACK_EMF_PHASE_COLORS.B,
        }
        : {
          colorStart: BACK_EMF_PHASE_COLORS.A,
          colorEnd: BACK_EMF_PHASE_COLORS.B,
          labelColor: RESULTANT_FIELD_COLOR,
        };
    const showFieldVector = labPart === 'motor' || fieldVectorScale >= 0.02;
    const fieldVectorLength = labPart === 'motor' ? FIELD_VECTOR_LENGTH_MM : fieldVectorLengthMm;
    const fieldVectorX = fieldVectorLength * Math.cos(fieldAngleRad);
    const fieldVectorY = fieldVectorLength * Math.sin(fieldAngleRad);
    const resultantVector: MeshViewerDirectionVector = {
      x1Mm: 0,
      y1Mm: 0,
      x2Mm: fieldVectorX,
      y2Mm: fieldVectorY,
      label: labPart === 'motor'
        ? motorFieldMode === 'rotor' ? 'PM field' : 'B target'
        : fieldVectorLabel,
      tone: 'cyan' as const,
      strokeScale: labPart === 'motor' ? 0.58 : 0.68,
      ...(labPart === 'field' ? fieldVectorPalette : {}),
      ...(labPart === 'field' && phaseFieldMode === 'combined'
        ? { orbitGuideRadiusMm: FIELD_VECTOR_LENGTH_MM }
        : {}),
    };
    const vectors: MeshViewerDirectionVector[] = [];
    if (showFieldVector) vectors.push(resultantVector);
    if (showFieldVector && labPart === 'field' && phaseFieldMode === 'combined') {
      const showPhaseALabel = Math.abs(fieldVectorX) >= 2;
      const showPhaseBLabel = Math.abs(fieldVectorY) >= 2;
      vectors.push(
        {
          x1Mm: 0,
          y1Mm: 0,
          x2Mm: fieldVectorX,
          y2Mm: 0,
          label: showPhaseALabel ? 'Bₐ' : undefined,
          labelXmm: fieldVectorX / 2,
          labelYmm: fieldVectorY >= 0 ? -1.8 : 1.8,
          tone: 'cyan',
          colorStart: BACK_EMF_PHASE_COLORS.A,
          colorEnd: BACK_EMF_PHASE_COLORS.A,
          labelColor: BACK_EMF_PHASE_COLORS.A,
          dashed: true,
          strokeScale: 0.48,
        },
        {
          x1Mm: fieldVectorX,
          y1Mm: 0,
          x2Mm: fieldVectorX,
          y2Mm: fieldVectorY,
          label: showPhaseBLabel ? 'Bᵦ' : undefined,
          labelXmm: fieldVectorX + (fieldVectorX >= 0 ? 1.8 : -1.8),
          labelYmm: fieldVectorY / 2,
          tone: 'cyan',
          colorStart: BACK_EMF_PHASE_COLORS.B,
          colorEnd: BACK_EMF_PHASE_COLORS.B,
          labelColor: BACK_EMF_PHASE_COLORS.B,
          dashed: true,
          strokeScale: 0.48,
        },
      );
    }
    if (labPart === 'motor' && motorDisplayFrame && showPmRotor) {
      const rotorAngleRad = motorDisplayFrame.rotor_angle_deg * Math.PI / 180;
      vectors.push({
        x1Mm: 0,
        y1Mm: 0,
        x2Mm: 10 * Math.cos(rotorAngleRad),
        y2Mm: 10 * Math.sin(rotorAngleRad),
        label: 'PM rotor',
        tone: 'amber',
        strokeScale: 0.64,
      });
    }
    return vectors;
  })() : [];

  const fieldModeLabel = phaseFieldMode === 'phase-a'
    ? 'PHASE A CONTRIBUTION'
    : phaseFieldMode === 'phase-b'
      ? 'PHASE B CONTRIBUTION'
      : 'A + B RESULTANT';
  const motorModeLabel = motorFieldMode === 'stator'
    ? 'STATOR FIELD ONLY'
    : motorFieldMode === 'rotor'
      ? 'ROTOR PM FIELD ONLY'
      : 'ROTATING FIELD → PM ROTOR';
  const progressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    {
      id: 'predict',
      label: 'Predict',
      complete: lessonStage !== 'design',
      available: true,
    },
    {
      id: 'field',
      label: 'Rotate B',
      complete: fieldLabComplete || labPart === 'motor',
      available: predictionCorrect,
    },
    {
      id: 'motor',
      label: 'Play cycle',
      complete: motorLabComplete,
      available: fieldLabComplete,
    },
    {
      id: 'check',
      label: 'Check',
      complete: quizPassed,
      available: motorLabComplete,
    },
  ], [
    fieldLabComplete,
    labPart,
    lessonStage,
    motorLabComplete,
    predictionCorrect,
    quizPassed,
  ]);
  const currentStepId = quizOpen
    ? 'check'
    : lessonStage === 'design'
      ? 'predict'
      : labPart === 'motor'
        ? 'motor'
        : 'field';
  const handleHeaderStepSelect = React.useCallback((stepId: string) => {
    setPlaying(false);
    if (stepId === 'predict') {
      setQuizOpen(false);
      setLabControlsOpen(false);
      setSolveInspectorOpen(false);
      onStageChange?.('design');
      return;
    }
    if (stepId === 'field' && predictionCorrect) {
      setQuizOpen(false);
      setLabPart('field');
      enterSolveStage();
      return;
    }
    if (stepId === 'motor' && fieldLabComplete) {
      continueToMotor();
      return;
    }
    if (stepId === 'check' && motorLabComplete) setQuizOpen(true);
  }, [
    enterSolveStage,
    fieldLabComplete,
    motorLabComplete,
    onStageChange,
    predictionCorrect,
  ]);
  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 7,
    lessonCount: 10,
    title: 'Make the Field Rotate',
    currentStepId,
    steps: progressSteps,
    onStepSelect: handleHeaderStepSelect,
  }), [currentStepId, handleHeaderStepSelect, progressSteps]);

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  return (
    <main className={`learning-shell learning-lesson-shell rotating-field-shell is-${lessonStage}-stage${quizOpen ? ' is-quiz-open' : ''}${labControlsOpen && !quizOpen && lessonStage !== 'design' ? ' has-lab-controls' : ''}${solveInspectorOpen && !quizOpen && lessonStage !== 'design' ? ' has-solve-inspector' : ''}`}>
      <header className="tutorial-studio-strip rotating-field-studio-strip">
        <div className="rotating-field-studio-context">
          <strong>{lessonStage === 'design' ? 'Two-phase field · prediction' : labPart === 'field' ? 'Two-phase field · live FEM' : 'Four-pole PM motor · live FEM'}</strong>
          <span>{lessonStage === 'design'
            ? 'Two fixed winding axes · one electrical target'
            : labPart === 'field'
              ? `${fieldFrames.length || 32} solved angles · ${direction === 1 ? 'A leads B' : 'B leads A'}`
              : `${motorFrames.length || 32} rotor checkpoints · ${motorFieldMode} field`}</span>
        </div>
        {lessonStage !== 'design' && !quizOpen && activeFrame && labPart === 'field' ? (
          <div className="rotating-field-strip-phase-console">
            <div className="rotating-field-phase-toggle" role="group" aria-label="Solved phase contribution">
              <button type="button" className={phaseFieldMode === 'phase-a' ? 'is-active is-a' : ''} onClick={() => selectPhaseContribution('phase-a')} aria-pressed={phaseFieldMode === 'phase-a'}>Phase A only</button>
              <button type="button" className={phaseFieldMode === 'phase-b' ? 'is-active is-b' : ''} onClick={() => selectPhaseContribution('phase-b')} aria-pressed={phaseFieldMode === 'phase-b'}>Phase B only</button>
              <button type="button" className={phaseFieldMode === 'combined' ? 'is-active' : ''} onClick={() => selectPhaseContribution('combined')} aria-pressed={phaseFieldMode === 'combined'}>A + B resultant</button>
            </div>
            <div className="rotating-field-live-vector">
              <span>{fieldModeLabel}</span>
              <strong>θe = {displayAngle(activeElectricalAngle)}°</strong>
              <em>|B| {fieldMilliTesla(fieldMagnitudeT)}</em>
            </div>
          </div>
        ) : null}
        {lessonStage !== 'design' && !quizOpen && activeFrame && labPart === 'motor' ? (
          <div className="rotating-field-strip-motor-console">
            <div className="rotating-field-strip-control-group">
              <span>Field</span>
              <div className="rotating-field-source-buttons" role="group" aria-label="Motor field source">
                <button type="button" disabled={Boolean(busyMotorFieldMode)} className={motorFieldMode === 'stator' ? 'is-active' : ''} onClick={() => void selectMotorFieldMode('stator')} aria-pressed={motorFieldMode === 'stator'}>Stator</button>
                <button type="button" disabled={Boolean(busyMotorFieldMode)} className={motorFieldMode === 'rotor' ? 'is-active' : ''} onClick={() => void selectMotorFieldMode('rotor')} aria-pressed={motorFieldMode === 'rotor'}>Rotor</button>
                <button type="button" disabled={Boolean(busyMotorFieldMode)} className={motorFieldMode === 'combined' ? 'is-active' : ''} onClick={() => void selectMotorFieldMode('combined')} aria-pressed={motorFieldMode === 'combined'}>Combined</button>
              </div>
            </div>
            <div className="rotating-field-strip-control-group">
              <span>Geometry</span>
              <div className="rotating-field-geometry-buttons" role="group" aria-label="Motor geometry visibility">
                <button type="button" className={showElectromagnets ? 'is-active' : ''} onClick={() => setShowElectromagnets((visible) => !visible)} aria-pressed={showElectromagnets}>Stator</button>
                <button type="button" className={showPmRotor ? 'is-active' : ''} onClick={() => setShowPmRotor((visible) => !visible)} aria-pressed={showPmRotor}>PM rotor</button>
                <button
                  type="button"
                  className={!showElectromagnets && !showPmRotor ? 'is-active is-fields-only' : ''}
                  onClick={() => {
                    setShowElectromagnets(false);
                    setShowPmRotor(false);
                  }}
                  aria-pressed={!showElectromagnets && !showPmRotor}
                >Fields only</button>
              </div>
            </div>
            {busyMotorFieldMode ? <small className="rotating-field-source-loading"><i /> Solving {busyMotorFieldMode}…</small> : null}
          </div>
        ) : null}
        {lessonStage !== 'design' && !quizOpen && activeFrame ? (
          <div className="rotating-field-view-toggle" role="group" aria-label="Field visualization">
            {labPart === 'motor' ? (
              <>
                <button type="button" className={motorViewMode === 'fem' ? 'is-active' : ''} onClick={() => setMotorViewMode('fem')} aria-pressed={motorViewMode === 'fem'}><span className="is-slice" /> 2D FEM</button>
                <button type="button" className={motorViewMode === 'three' ? 'is-active' : ''} onClick={() => setMotorViewMode('three')} aria-pressed={motorViewMode === 'three'}><span className="is-three" /> 3D motor</button>
              </>
            ) : null}
            {labPart !== 'motor' || motorViewMode === 'fem' ? (
              <>
                <button type="button" disabled={labPart === 'motor' && !motorFrame} className={showFluxLines ? 'is-active' : ''} onClick={() => setShowFluxLines((visible) => !visible)} aria-pressed={showFluxLines}><span /> Flux lines</button>
                <button type="button" disabled={labPart === 'motor' && !motorFrame} className={showFieldIntensity ? 'is-active' : ''} onClick={() => setShowFieldIntensity((visible) => !visible)} aria-pressed={showFieldIntensity}><span className="is-density" /> |B| map</button>
                <button type="button" className={showMesh ? 'is-active' : ''} onClick={() => setShowMesh((visible) => !visible)} aria-pressed={showMesh}><span className="is-mesh" /> Mesh</button>
              </>
            ) : null}
          </div>
        ) : null}
      </header>
      <section ref={mainStageRef} className="learning-main-stage rotating-field-main">
        {quizOpen ? (
          <section className="rotating-field-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you connect rotating B to continuous rotor motion?</h2>
            <p>Use the phase sequence, four solved poles, and PM alignment torque.</p>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </section>
        ) : lessonStage === 'design' ? (
          <section className="rotating-field-predict-stage rotating-field-predict-experience" aria-label="Rotating-field prediction">
            <header className="rotating-field-predict-heading">
              <p className="learning-kicker">Lesson 7 · Predict</p>
              <h1>What makes the field rotate?</h1>
              <p>Choose the current relationship that turns two fixed winding axes into one moving magnetic target.</p>
            </header>
            <div className="rotating-field-predict-visual">
              <div className="rotating-field-design-toggle" role="group" aria-label="Lesson diagram view">
                <button type="button" className={designDiagramMode === 'slice' ? 'is-active' : ''} onClick={() => setDesignDiagramMode('slice')} aria-pressed={designDiagramMode === 'slice'}>2D slice</button>
                <button type="button" className={designDiagramMode === 'physical' ? 'is-active' : ''} onClick={() => setDesignDiagramMode('physical')} aria-pressed={designDiagramMode === 'physical'}>Physical coils</button>
              </div>
              {designDiagramMode === 'slice' ? <RotatingFieldPredictionDiagram /> : <RotatingFieldCoils3D />}
            </div>
            <div className="rotating-field-predict-question">
              <div className="rotating-field-predict-options" role="radiogroup" aria-label="Current pattern prediction">
                {([
                  ['quadrature', '90°-shifted phases', 'A follows cosine; B follows sine.'],
                  ['together', 'Identical phases', 'Both axes rise and fall together.'],
                  ['one-phase', 'One phase only', 'One axis grows, reverses, and shrinks.'],
                ] as Array<[Prediction, string, string]>).map(([value, label, detail], index) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={prediction === value}
                    className={`${prediction === value ? 'is-selected' : ''}${prediction === value && value === 'quadrature' ? ' is-correct' : ''}`}
                    onClick={() => setPrediction(value)}
                  >
                    <span className="rotating-field-prediction-number">{index + 1}</span>
                    <span><strong>{label}</strong><small>{detail}</small></span>
                  </button>
                ))}
              </div>
              {prediction ? (
                <p className={`rotating-field-feedback${predictionCorrect ? ' is-correct' : ''}`} aria-live="polite">
                  {predictionCorrect
                    ? 'Exactly. Perpendicular cosine and sine components trace one smoothly rotating vector.'
                    : 'That pattern does not keep the direction advancing. Look for two perpendicular components separated by a quarter-cycle.'}
                </p>
              ) : null}
            </div>
          </section>
        ) : labPart === 'motor' && !motorDisplayFrame ? (
          <section className="rotating-field-empty-stage is-motor-loading">
            <div className="learning-stage-badge"><span>Part 3</span><strong>Four-pole PM motor</strong></div>
            <RotatingFieldMotorGeometryDiagram />
            <div>
              <h2>{busyMotor ? 'Loading the exact Gmsh cross-section.' : 'Build the four-pole motor frames.'}</h2>
              <p>The four M350-50A poles, eight winding sides, and N42 rotor are already in their real positions. The exact mesh replaces this cross-section as soon as Gmsh returns it.</p>
              {error ? <p className="rotating-field-error">{error}</p> : null}
            </div>
          </section>
        ) : activeFrame ? (
          <>
            <div className={`rotating-field-viewer${labPart === 'motor' ? ' is-motor' : ''}`}>
              {labPart === 'motor' && motorViewMode === 'fem' ? (
                <div className="rotating-field-part-badge"><span>PART 3</span><strong>Four wound poles + moving PM rotor</strong></div>
              ) : null}
              {labPart === 'motor' && motorViewMode === 'fem' ? (
                <div className="rotating-field-live-vector">
                  <span>{motorModeLabel}</span>
                  <strong>θe = {displayCycleAngle(activeElectricalAngle)}°</strong>
                  <em>{motorDisplayFrame ? `rotor ${displayAngle(motorDisplayFrame.rotor_angle_deg)}°` : 'rotor loading'}</em>
                </div>
              ) : null}
              {labPart === 'motor' && motorViewMode === 'three' && motorDisplayFrame ? (
                <TwoPhaseMotor3D
                  electricalAngleDeg={motorElectricalAngle}
                  rotorAngleDeg={motorDisplayFrame.rotor_angle_deg}
                  phaseACurrentA={motorDisplayFrame.phase_a_current_a}
                  phaseBCurrentA={motorDisplayFrame.phase_b_current_a}
                  fieldMode={motorFieldMode}
                  showStator={showElectromagnets}
                  showRotor={showPmRotor}
                  playing={playing}
                />
              ) : (
                <MeshViewer
                  meshData={renderFrame ?? activeFrame}
                  embedded
                  compactEmbedded
                  toolbarMode="zoom-only"
                  toolbarLabel={labPart === 'motor' && !motorFrame
                    ? 'actual Gmsh geometry · field solving'
                    : `${labPart === 'motor' ? `four-pole ${motorFieldMode}` : fieldModeLabel.toLowerCase()}${showFieldIntensity ? ' |B| map' : ''}${showFluxLines ? ' + flux lines' : ''}`}
                  showMeshEdges={showMesh || (labPart === 'motor' && !motorFrame)}
                  showFieldIntensity={showFieldIntensity && Boolean(motorFrame || labPart === 'field')}
                  fieldIntensityRange={intensityRange}
                  smoothFieldIntensity
                  fieldLinesVisible={showFluxLines && Boolean(motorFrame || labPart === 'field')}
                  animateFieldArrows={playing && showFluxLines}
                  preserveViewportOnMeshChange
                  viewportPanEnabled={false}
                  pointLabels={labPart === 'motor' ? motorPointLabels : fieldPointLabels}
                  directionVectors={directionVectors}
                  dipoleMarkers={labPart === 'motor' && motorDisplayFrame && showPmRotor ? [{
                    xMm: 0,
                    yMm: 0,
                    angleDeg: motorDisplayFrame.rotor_angle_deg,
                    lengthMm: motorDisplayFrame.rotor_radius_mm * 1.7,
                    thicknessMm: motorDisplayFrame.rotor_radius_mm * 0.72,
                    shape: 'surface-arcs',
                    rotorRadiusMm: motorDisplayFrame.rotor_radius_mm,
                    poleArcDeg: 132,
                    poleThicknessMm: motorDisplayFrame.rotor_radius_mm * 0.19,
                    animateTorque: playing,
                    torqueDirection: direction === 1 ? 'ccw' : 'cw',
                  }] : []}
                />
              )}
            </div>
          </>
        ) : (
          <section className="rotating-field-empty-stage">
            <div className="learning-stage-badge"><span>Part 2</span><strong>Two-phase field fixture</strong></div>
            <RotatingFieldPredictionDiagram />
            <div><h2>Solve one electrical cycle.</h2><p>The right panel starts all FEM work and advances the lab.</p></div>
          </section>
        )}
      </section>

      {labControlsOpen && !quizOpen && lessonStage !== 'design' ? <aside className="learning-control-panel rotating-field-control-panel">
        <button type="button" className="tutorial-studio-panel-close" aria-label="Close lab controls" onClick={() => setLabControlsOpen(false)}>×</button>
        <section className="tutorial-studio-goal">
          <span>{currentStepId === 'predict' ? '1' : currentStepId === 'field' ? '2' : currentStepId === 'motor' ? '3' : '4'}/4</span>
          <div>
            <p className="learning-kicker">Current goal</p>
            <h2>{currentStepId === 'predict'
              ? 'Choose the current pattern'
              : currentStepId === 'field'
                ? 'Build one rotating field'
                : currentStepId === 'motor'
                  ? 'Let the PM rotor chase it'
                  : 'Explain why it keeps turning'}</h2>
          </div>
        </section>
        {quizOpen ? (
          <>
            <section className="rotating-field-takeaway">
              <p className="learning-kicker">Takeaway</p>
              <h2>Two phases keep moving the rotor’s alignment target.</h2>
              <p>A single phase flips on one axis. Two perpendicular phases in quadrature create a rotating field, so the PM rotor can keep chasing instead of aligning once.</p>
            </section>
            <div className="rotating-field-context-footer">
              <button type="button" className="learning-ghost-button" onClick={() => setQuizOpen(false)}>Back to the motor lab</button>
            </div>
          </>
        ) : labPart === 'field' ? (
          <>
            <h2>Rotating-field lab</h2>
            {!fieldSweep ? (
              <section className="rotating-field-solve-card">
                <span>ONE SHARED NORMAL MESH</span>
                <h3>32 angles × 3 field views</h3>
                <p>Magneto2D solves Phase A, Phase B, and their combined field on one Gmsh mesh.</p>
                {error ? <p className="rotating-field-error">{error}</p> : null}
              </section>
            ) : (
              <>
                <section className="rotating-field-playback-card">
                  <header><span>Electrical angle</span><strong>{displayAngle(fieldFrame?.electrical_angle_deg ?? 0)}°</strong></header>
                  <input
                    type="range"
                    min="0"
                    max={Math.max(0, fieldFrames.length - 1)}
                    step="1"
                    value={fieldFrameIndex}
                    onChange={(event) => selectActiveFrame(Number(event.currentTarget.value))}
                    aria-label="Solved electrical angle frame"
                  />
                  <div className="rotating-field-playback-buttons">
                    <button type="button" className={`rotating-field-playback-primary${playing ? ' is-active' : ''}`} onClick={() => (playing ? setPlaying(false) : startPlaying())}>{playing ? 'Pause' : 'Play cycle'}</button>
                  </div>
                  <button type="button" className="rotating-field-reverse-button" onClick={() => setDirection((previous) => previous === 1 ? -1 : 1)}>
                    {direction === 1 ? 'A leads B · CCW' : 'B leads A · CW'}
                  </button>
                </section>
                <section className="rotating-field-current-card">
                  <header><span>QUADRATURE CURRENTS</span><strong>90° apart</strong></header>
                  <div><span>Phase A · Ipk cos θ</span><b>{signedCurrent(fieldFrame?.phase_a_current_a ?? 0)}</b></div>
                  <div><span>Phase B · Ipk sin θ</span><b>{signedCurrent(fieldFrame?.phase_b_current_a ?? 0)}</b></div>
                </section>
                <section className="rotating-field-checklist is-in-panel">
                  <span className={inspectedZero ? 'is-done' : ''}>{inspectedZero ? '✓' : '1'} Inspect θ = 0°</span>
                  <span className={inspectedQuarter ? 'is-done' : ''}>{inspectedQuarter ? '✓' : '2'} Inspect θ = 90°</span>
                  <span className={fieldCycleComplete ? 'is-done' : ''}>{fieldCycleComplete ? '✓' : '3'} Play one full field cycle</span>
                </section>
                <section className="rotating-field-bridge-card">
                  <span>NEXT · APPLY THE FIELD</span>
                  <h3>Add four wound poles and the PM rotor.</h3>
                  <p>The next FEM fixture replaces the abstract conductor pairs with four M350-50A pole cores 90° apart.</p>
                </section>
              </>
            )}
            <section className="rotating-field-concept-card">
              <span>RESULTANT</span>
              <div><b>B<sub>x</sub></b><em>∝ I<sub>A</sub> = I<sub>pk</sub> cos θ</em></div>
              <div><b>B<sub>y</sub></b><em>∝ I<sub>B</sub> = I<sub>pk</sub> sin θ</em></div>
              <p>The ideal vector keeps its magnitude while its angle advances.</p>
            </section>
          </>
        ) : (
          <>
            <h2>Four-pole PM motor lab</h2>
            {busyMotor || !motorSweep ? (
              <section className="rotating-field-solve-card">
                <span>SCREEN LOADED · SOLVER RUNNING</span>
                <h3>Four wound poles + one PM rotor</h3>
                <p>Gmsh and Magneto2D are solving the angle-dependent motor frames in the background.</p>
                {!busyMotor ? <button type="button" onClick={() => void solveMotorSweep()}>Retry motor FEM sweep</button> : <div className="rotating-field-solving-indicator"><i /> Solving the combined motor FEM frames…</div>}
                {error ? <p className="rotating-field-error">{error}</p> : null}
              </section>
            ) : motorFrame ? (
              <>
                <section className="rotating-field-motor-view-card">
                  <span>SOLVED FIELD SOURCE</span>
                  <div className="rotating-field-source-buttons" role="group" aria-label="Motor field source">
                    <button type="button" disabled={Boolean(busyMotorFieldMode)} className={motorFieldMode === 'stator' ? 'is-active' : ''} onClick={() => void selectMotorFieldMode('stator')} aria-pressed={motorFieldMode === 'stator'}>Stator only</button>
                    <button type="button" disabled={Boolean(busyMotorFieldMode)} className={motorFieldMode === 'rotor' ? 'is-active' : ''} onClick={() => void selectMotorFieldMode('rotor')} aria-pressed={motorFieldMode === 'rotor'}>Rotor only</button>
                    <button type="button" disabled={Boolean(busyMotorFieldMode)} className={motorFieldMode === 'combined' ? 'is-active' : ''} onClick={() => void selectMotorFieldMode('combined')} aria-pressed={motorFieldMode === 'combined'}>Combined</button>
                  </div>
                  {busyMotorFieldMode ? <small className="rotating-field-source-loading"><i /> Solving {busyMotorFieldMode}-only frames…</small> : null}
                  {!busyMotorFieldMode && error ? <p className="rotating-field-error">{error}</p> : null}
                  <span>VISIBLE GEOMETRY</span>
                  <div className="rotating-field-geometry-buttons" role="group" aria-label="Motor geometry visibility">
                    <button type="button" className={showElectromagnets ? 'is-active' : ''} onClick={() => setShowElectromagnets((visible) => !visible)} aria-pressed={showElectromagnets}>Electromagnets</button>
                    <button type="button" className={showPmRotor ? 'is-active' : ''} onClick={() => setShowPmRotor((visible) => !visible)} aria-pressed={showPmRotor}>PM rotor</button>
                    <button
                      type="button"
                      className={!showElectromagnets && !showPmRotor ? 'is-active is-fields-only' : ''}
                      onClick={() => {
                        const showGeometry = !showElectromagnets && !showPmRotor;
                        setShowElectromagnets(showGeometry);
                        setShowPmRotor(showGeometry);
                      }}
                      aria-pressed={!showElectromagnets && !showPmRotor}
                    >
                      {!showElectromagnets && !showPmRotor ? 'Show all' : 'Fields only'}
                    </button>
                  </div>
                </section>
                <section className="rotating-field-playback-card">
                  <header><span>Electrical angle</span><strong>{displayCycleAngle(motorElectricalAngle)}°</strong></header>
                  <input
                    type="range"
                    min="0"
                    max={motorFrames.length}
                    step="1"
                    value={motorFrameIndex}
                    onChange={(event) => selectActiveFrame(Number(event.currentTarget.value))}
                    aria-label="Solved motor angle frame"
                  />
                  <div className="rotating-field-playback-buttons">
                    <button type="button" className={`rotating-field-playback-primary${playing ? ' is-active' : ''}`} onClick={() => (playing ? setPlaying(false) : startPlaying())}>{playing ? 'Pause cycle' : 'Play cycle'}</button>
                  </div>
                  <button type="button" className="rotating-field-reverse-button" onClick={() => setDirection((previous) => previous === 1 ? -1 : 1)}>
                    {direction === 1 ? 'A leads B · CCW' : 'B leads A · CW'}
                  </button>
                </section>
                <section className="rotating-field-rotor-card">
                  <span>SYNCHRONOUS CHASE</span>
                  <div className="rotating-field-angle-readout">
                    <p><span>Field target</span><b>{displayCycleAngle(motorElectricalAngle)}°</b></p>
                    <p><span>PM rotor</span><b>{displayAngle(motorFrame.rotor_angle_deg)}°</b></p>
                    <p><span>Torque angle</span><b>{motorFrame.torque_angle_deg.toFixed(1)}°</b></p>
                  </div>
                  <strong className="rotating-field-torque-equation">τ ∝ sin(δ)</strong>
                  <small>The 15° teaching lag keeps the rotor behind the moving target. Each displayed state is a solved Magneto2D checkpoint, not a transient mechanical solve.</small>
                </section>
              </>
            ) : null}
          </>
        )}
        <footer className="learning-panel-footer">
          {isLessonComplete('rotating-field') ? (
            <a className="learning-primary-button learning-next-lesson" href="/tutorials/lesson-8">Next lesson: Three-Phase Motor</a>
          ) : null}
          <div className="learning-panel-nav">
            <button type="button" className="learning-ghost-button" onClick={onBackToCatalog}>Lessons</button>
            <button type="button" className="learning-ghost-button" onClick={onBackHome}>Design start</button>
          </div>
        </footer>
      </aside> : null}

      {solveInspectorOpen && !quizOpen ? <aside className="learning-context-panel rotating-field-results-panel" aria-label="Lesson guidance and solved results">
        <button type="button" className="tutorial-studio-panel-close" aria-label="Close solved results" onClick={() => setSolveInspectorOpen(false)}>×</button>
        <p className="learning-kicker">Solved output</p>
        {quizOpen ? (
          <section className="rotating-field-takeaway">
            <h2>Two phases keep moving the rotor’s alignment target.</h2>
            <p>A single phase flips on one axis. Two perpendicular phases in quadrature create a rotating field, so the PM rotor can keep chasing instead of aligning once.</p>
          </section>
        ) : lessonStage === 'design' ? (
          <section className="rotating-field-meaning-card">
            <span>LESSON 6 → LESSON 7</span>
            <strong>One phase flipped the target. Two spatially separated phases can rotate it.</strong>
            <p>Make a prediction on the left; the solved angle and phase comparison will appear here.</p>
          </section>
        ) : labPart === 'field' && fieldFrame ? (
          <section className="rotating-field-results">
            <header>
              <div><p className="learning-kicker">Conductor field</p><h2>A and B add into one rotating vector.</h2></div>
              <span>{phaseMagnitudeSpreadPct === null ? '—' : `${phaseMagnitudeSpreadPct.toFixed(2)}%`} |B| spread</span>
            </header>
            <PhaseWaveform
              angleDeg={fieldFrame.electrical_angle_deg}
              phaseACurrentA={fieldFrame.phase_a_current_a}
              phaseBCurrentA={fieldFrame.phase_b_current_a}
              onSelectAngle={selectFieldAngle}
            />
            <section className="rotating-field-concept-card">
              <span>RESULTANT</span>
              <div><b>B<sub>x</sub></b><em>∝ I<sub>A</sub> = I<sub>pk</sub> cos θ</em></div>
              <div><b>B<sub>y</sub></b><em>∝ I<sub>B</sub> = I<sub>pk</sub> sin θ</em></div>
              <p>The ideal vector keeps its magnitude while its angle advances.</p>
            </section>
          </section>
        ) : motorDisplayFrame ? (
          <section className="rotating-field-motor-results">
            <header>
              <div><p className="learning-kicker">PM rotor chase</p><h2>The target advances; the rotor follows.</h2></div>
              <span>θe = {displayCycleAngle(motorElectricalAngle)}°</span>
            </header>
            <div className="rotating-field-angle-readout">
              <p><span>Field target</span><b>{displayCycleAngle(motorElectricalAngle)}°</b></p>
              <p><span>PM rotor</span><b>{displayAngle(motorDisplayFrame.rotor_angle_deg)}°</b></p>
              <p><span>Torque angle</span><b>{(motorDisplayFrame.torque_angle_deg ?? 0).toFixed(1)}°</b></p>
            </div>
            <PhaseWaveform
              angleDeg={motorElectricalAngle}
              phaseACurrentA={motorDisplayFrame.phase_a_current_a}
              phaseBCurrentA={motorDisplayFrame.phase_b_current_a}
              onSelectAngle={motorFrame ? selectMotorAngle : () => undefined}
            />
          </section>
        ) : (
          <section className="rotating-field-meaning-card">
            <span>WAITING FOR SOLVE</span>
            <strong>Solved phase currents, field angle, and rotor lag will appear here.</strong>
          </section>
        )}
      </aside> : null}

      <section className={`tutorial-studio-dock rotating-field-studio-dock${!quizOpen && lessonStage !== 'design' && (fieldSweep || motorSweep) ? ' has-playback' : ''}`} aria-label="Lesson controls">
        <div className="rotating-field-dock-context">
          <span>{quizOpen ? 'CHECK' : lessonStage === 'design' ? 'PREDICT' : labPart === 'field' ? 'ROTATE B' : 'SPIN ROTOR'}</span>
          <strong>{quizOpen
            ? 'Explain why the PM rotor keeps following the field.'
            : lessonStage === 'design'
              ? 'Choose the current pattern that creates a moving target.'
              : labPart === 'field'
                ? fieldLabComplete ? 'The field rotates. Put a PM rotor inside it.' : 'Inspect two angles and play one complete electrical cycle.'
                : motorLabComplete ? 'The rotor completed a full synchronous chase.' : 'Let the rotor follow one full revolution.'}</strong>
          {!quizOpen && lessonStage !== 'design' && labPart === 'field' && fieldFrame ? (
            <small>A {signedCurrent(fieldFrame.phase_a_current_a)} · B {signedCurrent(fieldFrame.phase_b_current_a)}</small>
          ) : !quizOpen && lessonStage !== 'design' && labPart === 'motor' && motorDisplayFrame ? (
            <small>Field {displayCycleAngle(motorElectricalAngle)}° · rotor {displayAngle(motorDisplayFrame.rotor_angle_deg)}° · δ {(motorDisplayFrame.torque_angle_deg ?? 0).toFixed(1)}°</small>
          ) : null}
        </div>
        {!quizOpen && lessonStage !== 'design' && labPart === 'field' && fieldSweep ? (
          <div className="rotating-field-dock-playback">
            <label>
              <span>Electrical angle</span>
              <strong>{displayAngle(fieldFrame?.electrical_angle_deg ?? 0)}°</strong>
              <input
                type="range"
                min="0"
                max={Math.max(0, fieldFrames.length - 1)}
                step="1"
                value={fieldFrameIndex}
                onChange={(event) => selectActiveFrame(Number(event.currentTarget.value))}
                aria-label="Solved electrical angle frame"
              />
            </label>
            <div className="rotating-field-dock-playback-buttons">
              <button type="button" className={`rotating-field-dock-play-primary${playing ? ' is-active' : ''}`} onClick={() => (playing ? setPlaying(false) : startPlaying())}>{playing ? 'Pause' : 'Play cycle'}</button>
              <button type="button" className="rotating-field-dock-sequence" onClick={() => setDirection((previous) => previous === 1 ? -1 : 1)}>{direction === 1 ? 'A leads B · CCW' : 'B leads A · CW'}</button>
            </div>
          </div>
        ) : !quizOpen && lessonStage !== 'design' && labPart === 'motor' && motorSweep ? (
          <div className="rotating-field-dock-playback">
            <label>
              <span>Electrical angle</span>
              <strong>{displayCycleAngle(motorElectricalAngle)}°</strong>
              <input
                type="range"
                min="0"
                max={motorFrames.length}
                step="1"
                value={motorFrameIndex}
                onChange={(event) => selectActiveFrame(Number(event.currentTarget.value))}
                aria-label="Solved motor angle frame"
              />
            </label>
            <div className="rotating-field-dock-playback-buttons">
              <button type="button" className={`rotating-field-dock-play-primary${playing ? ' is-active' : ''}`} onClick={() => (playing ? setPlaying(false) : startPlaying())}>{playing ? 'Pause' : 'Play cycle'}</button>
              <button type="button" className="rotating-field-dock-sequence" onClick={() => setDirection((previous) => previous === 1 ? -1 : 1)}>{direction === 1 ? 'A leads B · CCW' : 'B leads A · CW'}</button>
            </div>
          </div>
        ) : null}
        <div className="tutorial-studio-dock-actions">
          {!quizOpen && lessonStage !== 'design' ? <button type="button" className={solveInspectorOpen ? 'is-active' : ''} disabled={!fieldFrame && !motorDisplayFrame} onClick={() => {
            setSolveInspectorOpen((open) => {
              const nextOpen = !open;
              if (nextOpen) setLabControlsOpen(false);
              return nextOpen;
            });
          }}>Inspect results</button> : quizOpen ? <button type="button" onClick={() => setQuizOpen(false)}>Review experiment</button> : null}
          {quizOpen ? (
            quizPassed
              ? <a className="learning-primary-button" href="/tutorials/lesson-8">Next lesson</a>
              : <button type="button" className="learning-primary-button" disabled>Pass the check</button>
          ) : lessonStage === 'design' ? (
            <button type="button" className="learning-primary-button" disabled={!predictionCorrect} onClick={() => {
              setLabControlsOpen(false);
              enterSolveStage();
              void solveFieldSweep();
            }}>Solve rotating field</button>
          ) : labPart === 'field' && !fieldSweep ? (
            <button type="button" className="learning-primary-button" disabled={busyField} onClick={() => void solveFieldSweep()}>{busyField ? 'Solving…' : 'Run field sweep'}</button>
          ) : labPart === 'field' && fieldLabComplete ? (
            <button type="button" className="learning-primary-button" onClick={() => {
              setSolveInspectorOpen(false);
              continueToMotor();
            }}>Add PM rotor</button>
          ) : labPart === 'motor' && !motorSweep ? (
            <button type="button" className="learning-primary-button" disabled={busyMotor} onClick={() => void solveMotorSweep()}>{busyMotor ? 'Solving…' : 'Run motor sweep'}</button>
          ) : labPart === 'motor' && motorLabComplete ? (
            <button type="button" className="learning-primary-button" onClick={() => {
              setPlaying(false);
              setLabControlsOpen(false);
              setSolveInspectorOpen(false);
              setQuizOpen(true);
            }}>Continue to check</button>
          ) : null}
        </div>
      </section>
    </main>
  );
};
