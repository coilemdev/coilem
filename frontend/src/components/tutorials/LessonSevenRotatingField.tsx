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
type FieldDisplayMode = 'lines' | 'density';
type LessonSevenStepId = 'predict' | 'field' | 'motor' | 'check';

const PEAK_CURRENT_A = 8;
const COIL_OFFSET_MM = 22;
const FIELD_VECTOR_LENGTH_MM = 16;
const RESULTANT_FIELD_COLOR = '#92ba65';
const FRAME_STEP_DEG = 45 / 4;
const FRAME_COUNT = Math.round(360 / FRAME_STEP_DEG);
const QUARTER_FRAME_INDEX = Math.round(90 / FRAME_STEP_DEG);
const PLAY_INTERVAL_MS = 240;
// The angles offered as one-click presets beside the slider.
const LANDMARK_ANGLES_DEG = [0, 90, 180, 270];

const LESSON_SEVEN_GOALS: Record<LessonSevenStepId, { title: string; detail: string }> = {
  predict: {
    title: 'Choose the current pattern',
    detail: 'Two fixed winding axes must make one moving magnetic target.',
  },
  field: {
    title: 'Build one rotating field',
    detail: 'Inspect θ = 0° and θ = 90°, then play one full field cycle.',
  },
  motor: {
    title: 'Let the PM rotor chase it',
    detail: 'Play one full cycle and watch the rotor follow the field target.',
  },
  check: {
    title: 'Explain why it keeps turning',
    detail: 'Use the phase sequence, four solved poles, and PM alignment torque.',
  },
};

// The lesson's vocabulary, shown in the Inspect card on every step.
const LESSON_SEVEN_TERMS = [
  { term: 'Phase', definition: 'One winding and the current that drives it. This fixture has two, A and B, set at right angles. ⊙ means the current flows toward you, ⊗ away from you.' },
  { term: <>Electrical angle, θ<sub>e</sub></>, definition: 'Where the currents are in their repeating cycle, in degrees. 360° is one full cycle.' },
  { term: 'Quadrature', definition: 'Two currents a quarter of a cycle (90°) apart. Here Phase A follows cos θ and Phase B follows sin θ, each with an 8 A peak.' },
  { term: 'Flux density, |B|', definition: 'How strong the magnetic field is at one spot, in tesla (T). The fields in air here are small, so they are shown in millitesla: 1 mT = 0.001 T.' },
  { term: 'Resultant field', definition: 'The field from Phase A and the field from Phase B added together as arrows (vectors). It is read at the centre of the fixture.' },
  { term: 'Phase sequence', definition: 'Which phase reaches its peak first. A leading B turns the field counterclockwise (CCW); B leading A turns it clockwise (CW).' },
  { term: 'Torque angle, δ', definition: 'How far the permanent-magnet (PM) rotor trails the direction the field is pulling it toward, in degrees. Torque grows with sin δ.' },
  { term: 'Electrical steel', definition: 'Thin sheet steel made to carry magnetic flux easily. The four wound poles of the motor here are grade M350-50A.' },
];

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
  <svg className="rotating-field-motor-geometry" viewBox="0 0 860 500" role="img" aria-label="Four wound electrical-steel poles surrounding a permanent-magnet rotor">
    <circle cx="430" cy="250" r="205" className="rotating-field-motor-domain" />
    <g className="rotating-field-motor-cores">
      <rect x="392" y="48" width="76" height="154" />
      <rect x="392" y="298" width="76" height="154" />
      <rect x="178" y="212" width="214" height="76" />
      <rect x="468" y="212" width="214" height="76" />
      <text x="430" y="118">Steel</text>
      <text x="430" y="390">Steel</text>
      <text x="270" y="255">Steel</text>
      <text x="590" y="255">Steel</text>
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
  // Drawn at about the width of the Inspect card, so the tick labels are
  // shown close to their real size instead of being scaled down.
  const width = 260;
  const height = 168;
  const margin = { top: 10, right: 16, bottom: 26, left: 28 };
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
        <circle className="is-a" cx={selectedX} cy={yFor(phaseACurrentA)} r="4.5" />
        <circle className="is-b" cx={selectedX} cy={yFor(phaseBCurrentA)} r="4.5" />
        <g className="rotating-field-waveform-ticks">
          {[0, 90, 180, 270, 360].map((angle) => (
            <text key={angle} x={xFor(angle)} y={height - 8} textAnchor="middle">{angle}°</text>
          ))}
          <text x={margin.left - 6} y={yFor(PEAK_CURRENT_A) + 4} textAnchor="end">+8</text>
          <text x={margin.left - 6} y={yFor(0) + 4} textAnchor="end">0</text>
          <text x={margin.left - 6} y={yFor(-PEAK_CURRENT_A) + 4} textAnchor="end">−8</text>
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
  const [fieldDisplayMode, setFieldDisplayMode] = React.useState<FieldDisplayMode>('lines');
  const [phaseFieldMode, setPhaseFieldMode] = React.useState<PhaseFieldMode>('combined');
  const [motorFieldMode, setMotorFieldMode] = React.useState<MotorFieldMode>('combined');
  const [motorViewMode, setMotorViewMode] = React.useState<MotorViewMode>('fem');
  const [showMesh, setShowMesh] = React.useState(false);
  const [showElectromagnets, setShowElectromagnets] = React.useState(true);
  const [showPmRotor, setShowPmRotor] = React.useState(true);
  const [designDiagramMode, setDesignDiagramMode] = React.useState<DesignDiagramMode>('physical');
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  // Where the mesh viewer draws its zoom buttons: the right end of the dock.
  const [zoomSlot, setZoomSlot] = React.useState<HTMLSpanElement | null>(null);
  const motorGeometryRequest = React.useRef<Promise<void> | null>(null);
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
    ? 'Phase A only'
    : phaseFieldMode === 'phase-b'
      ? 'Phase B only'
      : 'A + B resultant';
  const motorModeLabel = motorFieldMode === 'stator'
    ? 'stator field only'
    : motorFieldMode === 'rotor'
      ? 'rotor PM field only'
      : 'combined field';
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
  const currentStepId: LessonSevenStepId = quizOpen
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


  const lessonComplete = isLessonComplete('rotating-field');
  const currentGoal = LESSON_SEVEN_GOALS[currentStepId];
  const currentStepNumber = Math.max(1, progressSteps.findIndex((item) => item.id === currentStepId) + 1);
  const goalCard = (
    <LessonGoal step={currentStepNumber} total={progressSteps.length} title={currentGoal.title} detail={currentGoal.detail} />
  );
  const stepKicker = `Experiment · ${progressSteps.find((item) => item.id === currentStepId)?.label ?? ''}`;

  // The primary button of the field step walks the three checklist items in
  // order, then moves on to the motor.
  const fieldPrimaryLabel = busyField
    ? 'Solving…'
    : !fieldSweep
      ? 'Run field sweep'
      : !inspectedZero
        ? 'Show θ = 0°'
        : !inspectedQuarter
          ? 'Show θ = 90°'
          : !fieldCycleComplete
            ? playing ? 'Playing…' : 'Play one full cycle'
            : 'Add PM rotor';
  const handleFieldPrimary = () => {
    if (!fieldSweep) {
      void solveFieldSweep();
      return;
    }
    if (!inspectedZero || !inspectedQuarter) {
      // A single phase is at zero current at one of these two angles, so show
      // the combined field: the picture is never empty.
      setPhaseFieldMode('combined');
      selectFieldAngle(inspectedZero ? 90 : 0);
      return;
    }
    if (!fieldCycleComplete) {
      startPlaying();
      return;
    }
    continueToMotor();
  };

  const motorPrimaryLabel = busyMotor
    ? 'Solving…'
    : !motorSweep
      ? 'Run motor sweep'
      : !motorLabComplete
        ? playing ? 'Playing…' : 'Play one full cycle'
        : 'Continue to check';
  const handleMotorPrimary = () => {
    if (!motorSweep) {
      void solveMotorSweep();
      return;
    }
    if (!motorLabComplete) {
      startPlaying();
      return;
    }
    setPlaying(false);
    setQuizOpen(true);
  };

  // The canvas controls of the two experiment steps, in the same dock as the
  // motor workspace. Before the first solve the dock is shown greyed out, so
  // the canvas keeps its size. The field and mesh layers belong to the 2D
  // solve, so they are greyed out while the 3D motor is shown; the stator and
  // rotor can be hidden in both views.
  const renderViewDock = (unsolved: boolean) => {
    const motor = labPart === 'motor';
    const threeD = motor && Boolean(motorDisplayFrame) && motorViewMode === 'three';
    const layersOff = unsolved || threeD;
    const layerTitle = (title: string) => (threeD ? 'Switch to the 2D view to change this' : title);
    // The motor's cross-section is drawn (and can be zoomed) while its field
    // is still being solved.
    const zoomAvailable = !unsolved || (motor && Boolean(motorDisplayFrame));
    return (
      <LessonDock<MotorViewMode>
        tabs={motor
          ? [
            { id: 'fem', label: '2D' },
            { id: 'three', label: '3D', disabled: !motorDisplayFrame, title: motorDisplayFrame ? 'The same motor drawn in 3D' : 'The motor geometry is still loading' },
          ]
          : [{ id: 'fem', label: '2D' }]}
        tab={threeD ? 'three' : 'fem'}
        onTab={setMotorViewMode}
        end={(
          <>
            {unsolved ? 'Solve to see the field' : null}
            {zoomAvailable ? <span ref={setZoomSlot} /> : null}
          </>
        )}
      >
        <LessonDockGroup label="Field">
          <LessonSegmented
            label="Field drawing"
            value={layersOff ? null : fieldDisplayMode}
            onChange={setFieldDisplayMode}
            options={[
              { id: 'lines', label: 'Field lines', disabled: layersOff, title: layerTitle('Lines that follow the direction of the field') },
              { id: 'density', label: 'Flux density', disabled: layersOff, title: layerTitle('Colour by field strength, |B|') },
            ]}
          />
        </LessonDockGroup>
        <LessonDockGroup label="Show">
          {motor ? (
            <>
              <LessonDockToggle pressed={showElectromagnets} onChange={setShowElectromagnets} disabled={!motorDisplayFrame} title="The four wound poles and their coils">
                Stator
              </LessonDockToggle>
              <LessonDockToggle pressed={showPmRotor} onChange={setShowPmRotor} disabled={!motorDisplayFrame} title="The permanent-magnet rotor">
                PM rotor
              </LessonDockToggle>
            </>
          ) : null}
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

  // Angle slider, landmark presets, play and phase sequence: the same four
  // controls drive the field step and the motor step.
  const renderPlaybackControls = (options: {
    sliderId: string;
    sliderLabel: string;
    angleText: string;
    angleDeg: number;
    max: number;
    value: number;
    onSelectAngle: (angleDeg: number) => void;
  }) => {
    const landmark = LANDMARK_ANGLES_DEG.find((angleDeg) => (
      Math.abs(normalizeAngle(options.angleDeg) - angleDeg) < 0.1
    ));
    return (
      <>
        <label className="rotating-field-control-row" htmlFor={options.sliderId}>
          <span>Electrical angle</span><strong>{options.angleText}°</strong>
        </label>
        <input
          id={options.sliderId}
          type="range"
          min="0"
          max={options.max}
          step="1"
          value={options.value}
          onChange={(event) => selectActiveFrame(Number(event.currentTarget.value))}
          aria-label={options.sliderLabel}
        />
        <LessonSegmented
          stretch
          label="Electrical angle presets"
          value={landmark === undefined ? null : String(landmark)}
          onChange={(value) => options.onSelectAngle(Number(value))}
          options={LANDMARK_ANGLES_DEG.map((angleDeg) => ({ id: String(angleDeg), label: `${angleDeg}°` }))}
        />
        <button
          type="button"
          className="rotating-field-play"
          aria-pressed={playing}
          onClick={() => (playing ? setPlaying(false) : startPlaying())}
        >
          {playing ? 'Pause' : 'Play cycle'}
        </button>
        <div className="rotating-field-control-row">
          <span>Phase sequence</span><strong>{direction === 1 ? 'CCW' : 'CW'}</strong>
        </div>
        <LessonSegmented
          stretch
          label="Phase sequence"
          value={direction === 1 ? 'ccw' : 'cw'}
          onChange={(value) => setDirection(value === 'ccw' ? 1 : -1)}
          options={[
            { id: 'ccw', label: 'A leads B · CCW' },
            { id: 'cw', label: 'B leads A · CW' },
          ]}
        />
      </>
    );
  };

  const fieldEvidence = fieldFrame ? (
    <>
      <div className="rotating-field-angle-readout" aria-label="Solved two-phase field at this angle">
        <p><span>Electrical angle θ<sub>e</sub></span><b>{displayAngle(fieldFrame.electrical_angle_deg)}°</b></p>
        <p><span>Phase A current · I<sub>pk</sub> cos θ</span><b>{signedCurrent(fieldFrame.phase_a_current_a)}</b></p>
        <p><span>Phase B current · I<sub>pk</sub> sin θ</span><b>{signedCurrent(fieldFrame.phase_b_current_a)}</b></p>
        <p><span>|B| at the centre · {fieldModeLabel}</span><b>{fieldMilliTesla(fieldMagnitudeT)}</b></p>
        <p><span>|B| spread over the cycle (A + B)</span><b>{phaseMagnitudeSpreadPct === null ? '—' : `${phaseMagnitudeSpreadPct.toFixed(2)}%`}</b></p>
      </div>
      <PhaseWaveform
        angleDeg={fieldFrame.electrical_angle_deg}
        phaseACurrentA={fieldFrame.phase_a_current_a}
        phaseBCurrentA={fieldFrame.phase_b_current_a}
        onSelectAngle={selectFieldAngle}
      />
      <section className="lesson-lab-card rotating-field-recipe" aria-label="How the two phases add">
        <h3>Resultant</h3>
        <div><b>B<sub>x</sub></b><em>∝ I<sub>A</sub> = I<sub>pk</sub> cos θ</em></div>
        <div><b>B<sub>y</sub></b><em>∝ I<sub>B</sub> = I<sub>pk</sub> sin θ</em></div>
        <p>The ideal vector keeps its magnitude while its angle advances.</p>
      </section>
      <section className="lesson-lab-card" aria-label="Field step checklist">
        <h3>Checklist</h3>
        <div className="rotating-field-checklist">
          <span className={inspectedZero ? 'is-done' : ''}>{inspectedZero ? '✓' : '1'} Inspect θ = 0°</span>
          <span className={inspectedQuarter ? 'is-done' : ''}>{inspectedQuarter ? '✓' : '2'} Inspect θ = 90°</span>
          <span className={fieldCycleComplete ? 'is-done' : ''}>{fieldCycleComplete ? '✓' : '3'} Play one full field cycle</span>
        </div>
      </section>
      <section className="lesson-lab-card rotating-field-recipe" aria-label="Next step">
        <h3>Next · apply the field</h3>
        <p><strong>Add four wound poles and the PM rotor.</strong> The next FEM fixture replaces the abstract conductor pairs with four electrical-steel pole cores 90° apart.</p>
      </section>
    </>
  ) : null;

  const motorEvidence = motorDisplayFrame ? (
    <>
      <div className="rotating-field-angle-readout" aria-label="Field target and rotor at this angle">
        <p><span>Field target θ<sub>e</sub></span><b>{displayCycleAngle(motorElectricalAngle)}°</b></p>
        <p><span>PM rotor</span><b>{displayAngle(motorDisplayFrame.rotor_angle_deg)}°</b></p>
        <p><span>Torque angle δ</span><b>{(motorDisplayFrame.torque_angle_deg ?? 0).toFixed(1)}°</b></p>
        <p><span>Phase A current</span><b>{signedCurrent(motorDisplayFrame.phase_a_current_a)}</b></p>
        <p><span>Phase B current</span><b>{signedCurrent(motorDisplayFrame.phase_b_current_a)}</b></p>
      </div>
      <PhaseWaveform
        angleDeg={motorElectricalAngle}
        phaseACurrentA={motorDisplayFrame.phase_a_current_a}
        phaseBCurrentA={motorDisplayFrame.phase_b_current_a}
        onSelectAngle={motorFrame ? selectMotorAngle : () => undefined}
      />
      <section className="lesson-lab-card rotating-field-recipe" aria-label="Why the rotor follows">
        <h3>Synchronous chase</h3>
        <strong className="rotating-field-torque-equation">τ ∝ sin(δ)</strong>
        <p>The 15° teaching lag keeps the rotor behind the moving target. Each displayed state is a solved Magneto2D checkpoint, not a transient mechanical solve.</p>
      </section>
    </>
  ) : (
    <section className="lesson-lab-card rotating-field-recipe" aria-label="Motor geometry">
      <h3>Four-pole PM motor</h3>
      <p>The four electrical-steel poles, eight winding sides, and N42 rotor are already in their real positions. The exact mesh replaces this cross-section as soon as Gmsh returns it.</p>
    </section>
  );

  // Shown only while the solver is working; a finished solve needs no banner.
  const solveStatus = busyField
    ? 'Solving 32 angles × 3 field views on one shared mesh…'
    : busyMotor
      ? 'Solving the combined motor FEM frames…'
      : busyMotorFieldMode
        ? `Solving ${busyMotorFieldMode}-only frames…`
        : null;
  const showingMotorEvidence = lessonStage !== 'design' && labPart === 'motor';

  const inspectPanel = (
    <LessonLabPanel
      side="inspect"
      kicker="Inspect"
      title={lessonStage === 'design' ? 'Nothing solved yet' : showingMotorEvidence ? 'PM rotor chase' : 'Rotating field'}
      summary={lessonStage === 'design'
        ? 'One phase flipped the target. Two spatially separated phases can rotate it.'
        : showingMotorEvidence
          ? 'The target advances; the rotor follows.'
          : 'A and B add into one rotating vector.'}
      label="Lesson evidence and solved results"
      scrollTopKey={`${currentStepId}:${fieldSweep ? 1 : 0}:${motorSweep ? 1 : 0}`}
    >
      {lessonStage === 'design' ? (
        <LessonOutline
          steps={progressSteps.map((item) => ({
            id: item.id,
            label: item.label,
            detail: LESSON_SEVEN_GOALS[item.id as LessonSevenStepId].detail,
          }))}
          currentId={currentStepId}
        />
      ) : (
        <>
          {solveStatus ? (
            <p className="rotating-field-solving-indicator" role="status"><i /> {solveStatus}</p>
          ) : null}
          {showingMotorEvidence ? motorEvidence : fieldEvidence ?? (
            <section className="lesson-lab-card rotating-field-recipe" aria-label="Waiting for the solve">
              <h3>Waiting for solve</h3>
              <p>Solved phase currents, field angle, and rotor lag will appear here.</p>
            </section>
          )}
        </>
      )}
      <LessonTerms terms={LESSON_SEVEN_TERMS} />
    </LessonLabPanel>
  );

  if (quizOpen) {
    return (
      <LessonLab className="rotating-field-lab">
        {inspectPanel}
        <LessonLabStage className="is-tall">
          <LessonLabViewport label={`Knowledge check · ${QUIZ.length} questions`} className="is-scroll">
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
          </LessonLabViewport>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Check"
          title="Can you connect rotating B to continuous rotor motion?"
          label="Knowledge check"
          footer={(
            <LessonNextStep hint={quizPassed ? 'Lesson complete. Continue when you are ready.' : `Answer all ${QUIZ.length} questions to complete Lesson 7.`}>
              {quizPassed || lessonComplete ? (
                <a className="learning-primary-button" href="/tutorials/lesson-8">Next lesson</a>
              ) : null}
              <div className="lesson-lab-next-row">
                <LessonLink onClick={() => setQuizOpen(false)}>← Review experiment</LessonLink>
                <LessonLink onClick={onBackToCatalog}>All lessons</LessonLink>
              </div>
            </LessonNextStep>
          )}
        >
          {goalCard}
          <p className="lesson-lab-note">Explain why the PM rotor keeps following the field. Your solved frames stay on the right.</p>
        </LessonLabPanel>
      </LessonLab>
    );
  }

  if (lessonStage === 'design') {
    const physical = designDiagramMode === 'physical';
    return (
      <LessonLab className="rotating-field-lab">
        {inspectPanel}
        <LessonLabStage>
          <LessonLabCanvas className="rotating-field-canvas">
            {/* The flat diagram is centred; the 3D scene fills the canvas. */}
            <LessonLabViewport label="Two-phase coil pairs · not solved yet" className={physical ? '' : 'is-centered'}>
              {physical ? <RotatingFieldCoils3D /> : <RotatingFieldPredictionDiagram />}
            </LessonLabViewport>
            <LessonDock<DesignDiagramMode>
              tabs={[
                { id: 'slice', label: '2D', title: 'The cross-section the solver works on' },
                { id: 'physical', label: '3D', title: 'The two physical coils' },
              ]}
              tab={designDiagramMode}
              onTab={setDesignDiagramMode}
            />
          </LessonLabCanvas>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker="Experiment · Predict"
          title="What makes the field rotate?"
          summary="Choose the current relationship that turns two fixed winding axes into one moving magnetic target."
          label="Rotating-field prediction"
          footer={(
            <LessonNextStep
              tone={prediction ? (predictionCorrect ? 'good' : 'warn') : undefined}
              hint={prediction
                ? predictionCorrect
                  ? 'Exactly. Perpendicular cosine and sine components trace one smoothly rotating vector.'
                  : 'That pattern does not keep the direction advancing. Look for two perpendicular components separated by a quarter-cycle.'
                : 'Choose the current pattern that creates a moving target.'}
            >
              <button
                type="button"
                className="learning-primary-button"
                disabled={!predictionCorrect}
                onClick={() => {
                  enterSolveStage();
                  void solveFieldSweep();
                }}
              >
                Solve rotating field
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
            label="Current pattern prediction"
            value={prediction}
            onChange={setPrediction}
            correctId="quadrature"
            options={[
              { id: 'quadrature', label: '90°-shifted phases', detail: 'A follows cosine; B follows sine.' },
              { id: 'together', label: 'Identical phases', detail: 'Both axes rise and fall together.' },
              { id: 'one-phase', label: 'One phase only', detail: 'One axis grows, reverses, and shrinks.' },
            ]}
          />
        </LessonLabPanel>
      </LessonLab>
    );
  }

  if (labPart === 'motor') {
    const threeD = Boolean(motorDisplayFrame) && motorViewMode === 'three';
    return (
      <LessonLab className="rotating-field-lab">
        {inspectPanel}
        <LessonLabStage>
          <LessonLabCanvas className="rotating-field-canvas">
            {motorDisplayFrame ? (
              <LessonLabViewport
                label={`Four-pole PM motor · ${motorModeLabel}`}
                hint={motorFrame ? <>θ<sub>e</sub> = {displayCycleAngle(activeElectricalAngle)}°</> : 'Geometry only, field not solved yet'}
              >
                {threeD ? (
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
                    meshData={renderFrame ?? motorDisplayFrame}
                    embedded
                    compactEmbedded
                    toolbarMode="zoom-only"
                    zoomControlsSlot={zoomSlot}
                    // Until the field is solved there is nothing but the
                    // geometry to look at, so its mesh is always drawn.
                    showMeshEdges={showMesh || !motorFrame}
                    showFieldIntensity={fieldDisplayMode === 'density' && Boolean(motorFrame)}
                    fieldIntensityRange={intensityRange}
                    smoothFieldIntensity
                    fieldLinesVisible={fieldDisplayMode === 'lines' && Boolean(motorFrame)}
                    animateFieldArrows={playing && fieldDisplayMode === 'lines'}
                    preserveViewportOnMeshChange
                    viewportPanEnabled={false}
                    pointLabels={motorPointLabels}
                    directionVectors={directionVectors}
                    dipoleMarkers={showPmRotor ? [{
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
              </LessonLabViewport>
            ) : (
              <LessonLabViewport label="Four-pole PM motor" hint="Loading the geometry" className="is-centered">
                <RotatingFieldMotorGeometryDiagram />
              </LessonLabViewport>
            )}
            {renderViewDock(!motorFrame)}
          </LessonLabCanvas>
        </LessonLabStage>
        <LessonLabPanel
          side="do"
          kicker={stepKicker}
          title="Four-pole PM motor lab"
          label="Four-pole PM motor experiment"
          footer={(
            <LessonNextStep hint={motorLabComplete ? 'The rotor completed a full synchronous chase.' : 'Let the rotor follow one full revolution.'}>
              <button
                type="button"
                className="learning-primary-button"
                disabled={busyMotor || (Boolean(motorSweep) && !motorLabComplete && playing)}
                onClick={handleMotorPrimary}
              >
                {motorPrimaryLabel}
              </button>
            </LessonNextStep>
          )}
        >
          {goalCard}
          {motorFrame ? (
            <section className="rotating-field-controls" aria-label="Motor controls">
              <div className="rotating-field-control-row">
                <span>Field source</span><strong>{motorFieldMode === 'combined' ? 'Stator + rotor' : `${motorFieldMode === 'stator' ? 'Stator' : 'Rotor'} only`}</strong>
              </div>
              <LessonSegmented<MotorFieldMode>
                stretch
                label="Motor field source"
                value={motorFieldMode}
                onChange={(mode) => void selectMotorFieldMode(mode)}
                options={[
                  { id: 'stator', label: 'Stator', disabled: Boolean(busyMotorFieldMode), title: 'The field of the winding currents alone' },
                  { id: 'rotor', label: 'Rotor', disabled: Boolean(busyMotorFieldMode), title: 'The field of the permanent magnet alone' },
                  { id: 'combined', label: 'Combined', disabled: Boolean(busyMotorFieldMode), title: 'Both sources together' },
                ]}
              />
              {renderPlaybackControls({
                sliderId: 'rotating-field-motor-angle',
                sliderLabel: 'Solved motor angle frame',
                angleText: displayCycleAngle(motorElectricalAngle),
                angleDeg: motorElectricalAngle,
                max: motorFrames.length,
                value: motorFrameIndex,
                onSelectAngle: selectMotorAngle,
              })}
            </section>
          ) : (
            <p className="lesson-lab-note">
              {busyMotor
                ? 'Gmsh and Magneto2D are solving the angle-dependent motor frames in the background.'
                : 'Run the motor sweep to solve four wound poles and one PM rotor.'}
            </p>
          )}
          {error ? <p className="lesson-lab-error">{error}</p> : null}
        </LessonLabPanel>
      </LessonLab>
    );
  }

  return (
    <LessonLab className="rotating-field-lab">
      {inspectPanel}
      <LessonLabStage>
        <LessonLabCanvas className="rotating-field-canvas">
          {phaseViewerFrame ? (
            <LessonLabViewport
              label={`Two-phase coil pairs · ${fieldModeLabel}`}
              hint={<>θ<sub>e</sub> = {displayAngle(activeElectricalAngle)}°</>}
            >
              <MeshViewer
                meshData={phaseViewerFrame}
                embedded
                compactEmbedded
                toolbarMode="zoom-only"
                zoomControlsSlot={zoomSlot}
                showMeshEdges={showMesh}
                showFieldIntensity={fieldDisplayMode === 'density'}
                fieldIntensityRange={intensityRange}
                smoothFieldIntensity
                fieldLinesVisible={fieldDisplayMode === 'lines'}
                animateFieldArrows={playing && fieldDisplayMode === 'lines'}
                preserveViewportOnMeshChange
                viewportPanEnabled={false}
                pointLabels={fieldPointLabels}
                directionVectors={directionVectors}
              />
            </LessonLabViewport>
          ) : (
            <LessonLabViewport label="Two-phase coil pairs" hint="Not solved yet" className="is-centered">
              <RotatingFieldPredictionDiagram />
            </LessonLabViewport>
          )}
          {renderViewDock(!phaseViewerFrame)}
        </LessonLabCanvas>
      </LessonLabStage>
      <LessonLabPanel
        side="do"
        kicker={stepKicker}
        title="Rotating-field lab"
        label="Rotating-field experiment"
        footer={(
          <LessonNextStep hint={fieldLabComplete ? 'The field rotates. Put a PM rotor inside it.' : 'Inspect two angles and play one complete electrical cycle.'}>
            <button
              type="button"
              className="learning-primary-button"
              disabled={busyField || (Boolean(fieldSweep) && inspectedZero && inspectedQuarter && !fieldCycleComplete && playing)}
              onClick={handleFieldPrimary}
            >
              {fieldPrimaryLabel}
            </button>
          </LessonNextStep>
        )}
      >
        {goalCard}
        {fieldSweep ? (
          <section className="rotating-field-controls" aria-label="Field controls">
            <div className="rotating-field-control-row">
              <span>Field shown</span><strong>{fieldModeLabel}</strong>
            </div>
            <LessonSegmented<PhaseFieldMode>
              stretch
              label="Solved phase contribution"
              value={phaseFieldMode}
              onChange={selectPhaseContribution}
              options={[
                { id: 'phase-a', label: 'Phase A', title: 'The field of Phase A alone' },
                { id: 'phase-b', label: 'Phase B', title: 'The field of Phase B alone' },
                { id: 'combined', label: 'A + B', title: 'Both phases together' },
              ]}
            />
            {renderPlaybackControls({
              sliderId: 'rotating-field-angle',
              sliderLabel: 'Solved electrical angle frame',
              angleText: displayAngle(fieldFrame?.electrical_angle_deg ?? 0),
              angleDeg: fieldFrame?.electrical_angle_deg ?? 0,
              max: Math.max(0, fieldFrames.length - 1),
              value: fieldFrameIndex,
              onSelectAngle: selectFieldAngle,
            })}
          </section>
        ) : (
          <p className="lesson-lab-note">Magneto2D solves Phase A, Phase B, and their combined field on one Gmsh mesh.</p>
        )}
        {error ? <p className="lesson-lab-error">{error}</p> : null}
      </LessonLabPanel>
    </LessonLab>
  );
};
