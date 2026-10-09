import React from 'react';
import type {
  FieldLinePlotData,
  LessonOneFieldCompositionResult,
  LiveFieldLineFrameData,
  MeshPreviewData,
  SolveProgress,
  TorqueWaveformData,
  TutorialLessonOneDesignOptions,
  TutorialLessonOneSolveResult,
} from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { MeshViewer } from './MeshViewer';
import { LessonMotorDiagram } from './LessonMotorDiagram';
import { KnowledgeCheck } from './KnowledgeCheck';
import { useLearningProgress } from './useLearningProgress';
import { PublicMotor3D } from '../../public/PublicMotor3D';
import { DEFAULT_CONFIG, type MotorConfig } from '../../public/model';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
} from './lessonStage';
import {
  MAGNETIC_CIRCUIT_DEFAULT_DESIGN,
  MAGNETIC_CIRCUIT_DESIGN_FIELDS,
  MAGNETIC_CIRCUIT_KNOWLEDGE_CHECK,
  MAGNETIC_CIRCUIT_PHASE_CURRENT,
  LESSON_TWO_SHAFT_RADIUS_MM,
  LESSON_TWO_SOLVE_POSITIONS,
  clampNumber,
  circularAngleDistance,
  designSettingsEqual,
  peakAirgapRadialB,
  type MagneticCircuitDesignKey,
  type MagneticCircuitDesignSettings,
  type MagneticCircuitStage,
} from './magneticCircuit';
import './learning.css';
import './lesson-two.css';

interface LearningMotorMagneticCircuitProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: MagneticCircuitStage;
  onStageChange?: (stage: MagneticCircuitStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type LessonNineStage = Exclude<MagneticCircuitStage, 'mesh'>;
type LessonNineFieldSource = 'stator' | 'rotor' | 'combined';

// The generic `normal` profile produces ~89k triangles for this large 2p/6s
// teaching motor, nearly the same as `fine` (~96k). The physics-aware coarse
// profile still resolves the airgap and material boundaries while keeping the
// tutorial's medium-detail mesh near 18k triangles.
const LESSON_NINE_TEACHING_MESH_DENSITY = 'coarse' as const;

const LESSON_NINE_FIELD_SOURCES: Array<{ id: LessonNineFieldSource; label: string }> = [
  { id: 'stator', label: 'Stator only' },
  { id: 'rotor', label: 'Rotor only' },
  { id: 'combined', label: 'Combined' },
];

const LESSON_TWO_STAGES: Array<{ id: LessonNineStage; title: string; summary: string }> = [
  { id: 'design', title: 'Design', summary: 'Identify the 2p/6s SPM geometry.' },
  { id: 'solve', title: 'Solve', summary: 'Mesh the motor, solve the field, and compare torque across rotor angle.' },
];

function tutorialDesignOptions(settings: MagneticCircuitDesignSettings): TutorialLessonOneDesignOptions {
  return {
    airgapMm: settings.airgapMm,
    magnetArcPct: settings.magnetArcPct,
    magnetThicknessMm: settings.magnetThicknessMm,
    meshDensity: LESSON_NINE_TEACHING_MESH_DENSITY,
  };
}

// MeshViewer reads nodes_mm.map(...) directly, so never hand it
// a frame whose geometry hasn't been merged in yet.
function hasRenderableGeometry(
  data: { nodes_mm?: unknown; triangles?: unknown } | null | undefined,
): boolean {
  return Boolean(
    data
    && Array.isArray(data.nodes_mm) && data.nodes_mm.length > 0
    && Array.isArray(data.triangles) && data.triangles.length > 0,
  );
}

function stageOrder(stage: LessonNineStage): number {
  return LESSON_TWO_STAGES.findIndex((item) => item.id === stage);
}

function solveProgressPercent(
  progress: SolveProgress | null,
  status: 'idle' | 'running' | 'complete' | 'error',
): number {
  if (status === 'complete' || status === 'error') return 100;
  if (status !== 'running') return 0;
  if (!progress || progress.total <= 0) return 6;
  return Math.max(6, Math.min(99, (progress.position / progress.total) * 100));
}

function solveProgressLabel(
  progress: SolveProgress | null,
  status: 'idle' | 'running' | 'complete' | 'error',
): string {
  if (status === 'complete') return `${LESSON_TWO_SOLVE_POSITIONS} / ${LESSON_TWO_SOLVE_POSITIONS} positions complete`;
  if (status === 'error') return 'Solve stopped';
  if (status !== 'running') return 'Not run';
  if (!progress || progress.total <= 0) return 'Starting Magneto2D';
  const stage = progress.stage;
  if (stage === 'gmsh_mesh') return 'Building Gmsh mesh';
  if (stage === 'magneto2d_sweep' || stage === 'torque_sweep') {
    const completed = Math.max(0, Math.min(LESSON_TWO_SOLVE_POSITIONS, progress.position));
    return `${completed} / ${LESSON_TWO_SOLVE_POSITIONS} sweep positions`;
  }
  if (stage === 'magneto2d_single') return 'Solving the selected field frame';
  return `${Math.max(0, progress.position)} / ${Math.max(1, progress.total)} solve steps`;
}

function torquePreview(
  currentMagnitude: number,
  designSettings: MagneticCircuitDesignSettings,
): TorqueWaveformData {
  const scale = Math.pow(1 / Math.max(designSettings.airgapMm, 0.4), 0.65)
    * Math.pow(designSettings.magnetThicknessMm / 4, 0.55)
    * Math.sin((designSettings.magnetArcPct / 100) * Math.PI / 2);
  const electrical_angle_deg = Array.from({ length: 49 }, (_, index) => index * 7.5);
  return {
    electrical_angle_deg,
    torque_Nm: electrical_angle_deg.map((angle) => (
      currentMagnitude * 0.32 * scale * Math.sin((angle * Math.PI) / 180)
    )),
  };
}

function lessonNineMotorConfig(
  designSettings: MagneticCircuitDesignSettings,
  currentMagnitude: number,
): MotorConfig {
  const rotorCoreOdMm = 120 - (2 * (designSettings.airgapMm + designSettings.magnetThicknessMm));
  return {
    ...DEFAULT_CONFIG,
    stator: {
      ...DEFAULT_CONFIG.stator,
      slot_count: 6,
      slot_opening_mm: 4,
      tooth_width_mm: 42,
      yoke_thickness_mm: 20,
    },
    rotor: {
      ...DEFAULT_CONFIG.rotor,
      OD_mm: rotorCoreOdMm,
      pole_count: 2,
      magnet_thickness_mm: designSettings.magnetThicknessMm,
      magnet_width_mm: Math.PI * (rotorCoreOdMm + designSettings.magnetThicknessMm)
        * (designSettings.magnetArcPct / 100) / 2,
      magnet_embrace: designSettings.magnetArcPct / 100,
    },
    winding: {
      ...DEFAULT_CONFIG.winding,
      turns_per_coil: 24,
      layers: 1,
      parallel_paths: 1,
    },
    solve_params: {
      ...DEFAULT_CONFIG.solve_params,
      current_amplitude_A: currentMagnitude,
      current_angle_deg: 0,
    },
  };
}

function TrendChart({
  waveform,
  selectedAngleDeg,
  preview,
}: {
  waveform?: TorqueWaveformData | null;
  selectedAngleDeg: number;
  preview: TorqueWaveformData;
}) {
  const hasSolvedWaveform = Boolean(
    waveform
    && waveform.electrical_angle_deg.length === waveform.torque_Nm.length
    && waveform.electrical_angle_deg.length > 2,
  );
  const source = hasSolvedWaveform ? waveform as TorqueWaveformData : preview;
  const points = source.electrical_angle_deg
    .map((angle, index) => ({ angle, torque: source.torque_Nm[index] }))
    .filter((point) => Number.isFinite(point.angle) && Number.isFinite(point.torque));
  const width = 430;
  const height = 250;
  const left = 52;
  const right = width - 18;
  const top = 24;
  const bottom = height - 42;
  const maxAbs = Math.max(0.5, ...points.map((point) => Math.abs(point.torque)));
  const x = (angle: number) => left + (Math.max(0, Math.min(360, angle)) / 360) * (right - left);
  const y = (torque: number) => top + ((maxAbs - torque) / (maxAbs * 2)) * (bottom - top);
  const path = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(point.angle).toFixed(1)} ${y(point.torque).toFixed(1)}`)
    .join(' ');
  const selected = points.reduce((nearest, point) => (
    Math.abs(point.angle - selectedAngleDeg) < Math.abs(nearest.angle - selectedAngleDeg) ? point : nearest
  ), points[0] ?? { angle: selectedAngleDeg, torque: 0 });
  const peak = Math.max(...points.map((point) => point.torque), 0);
  const minimum = Math.min(...points.map((point) => point.torque), 0);

  return (
    <section className="lesson-nine-torque-panel">
      <div className="lesson-nine-torque-heading">
        <div>
          <span>Solved output</span>
          <h2>Torque vs rotor angle</h2>
        </div>
        <em className={waveform ? 'is-solved' : ''}>{waveform ? 'FEM sweep' : 'concept preview'}</em>
      </div>
      <p className="lesson-nine-torque-intro">
        The torque changes sign as the rotor crosses the stator-field alignment target.
      </p>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Torque versus electrical rotor angle" className="lesson-nine-torque-chart">
        <line x1={left} y1={y(0)} x2={right} y2={y(0)} className="lesson-nine-chart-zero" />
        <line x1={left} y1={top} x2={left} y2={bottom} className="lesson-nine-chart-axis" />
        {[0, 90, 180, 270, 360].map((angle) => (
          <g key={angle}>
            <line x1={x(angle)} y1={top} x2={x(angle)} y2={bottom} className="lesson-nine-chart-grid" />
            <text x={x(angle)} y={height - 17} textAnchor="middle">{angle}°</text>
          </g>
        ))}
        <text x={left - 8} y={top + 4} textAnchor="end">+{maxAbs.toFixed(1)}</text>
        <text x={left - 8} y={y(0) + 4} textAnchor="end">0</text>
        <text x={left - 8} y={bottom + 4} textAnchor="end">−{maxAbs.toFixed(1)}</text>
        <path d={path} className="lesson-nine-torque-line" />
        <line x1={x(selected.angle)} y1={top} x2={x(selected.angle)} y2={bottom} className="lesson-nine-chart-cursor" />
        <circle cx={x(selected.angle)} cy={y(selected.torque)} r="6" className="lesson-nine-chart-point" />
      </svg>
      <div className="lesson-nine-torque-readout">
        <div><span>Selected angle</span><strong>{selected.angle.toFixed(1)}°</strong></div>
        <div><span>Torque</span><strong>{selected.torque >= 0 ? '+' : ''}{selected.torque.toFixed(2)} N·m</strong></div>
        <div><span>Positive peak</span><strong>{peak.toFixed(2)} N·m</strong></div>
        <div><span>Negative peak</span><strong>{minimum.toFixed(2)} N·m</strong></div>
      </div>
      <p className="lesson-nine-torque-note">
        Positive and negative torque are the two rotational directions; zero torque marks field alignment.
      </p>
    </section>
  );
}

function ElectricalCycleChart({
  selectedAngleDeg,
  currentMagnitude,
}: {
  selectedAngleDeg: number;
  currentMagnitude: number;
}) {
  const width = 430;
  const height = 210;
  const left = 44;
  const right = width - 18;
  const top = 28;
  const bottom = height - 36;
  const amplitude = Math.max(1, currentMagnitude);
  const cursorAngle = Math.max(0, Math.min(360, selectedAngleDeg));
  const x = (angle: number) => left + (angle / 360) * (right - left);
  const y = (current: number) => top + ((amplitude - current) / (amplitude * 2)) * (bottom - top);
  const phaseDefinitions = [
    { id: 'a', label: 'Iₐ', offsetDeg: 0 },
    { id: 'b', label: 'Iᵦ', offsetDeg: -120 },
    { id: 'c', label: 'I꜀', offsetDeg: 120 },
  ];
  // Keep the plot on the same q-axis convention as the FEM solve:
  // source angle = rotor electrical angle - 90 degrees at gamma = 0.
  const currentAt = (angleDeg: number, offsetDeg: number) => (
    currentMagnitude * Math.sin(((angleDeg - 90 + offsetDeg) * Math.PI) / 180)
  );
  const pathFor = (offsetDeg: number) => Array.from({ length: 73 }, (_, index) => index * 5)
    .map((angle, index) => `${index === 0 ? 'M' : 'L'} ${x(angle).toFixed(1)} ${y(currentAt(angle, offsetDeg)).toFixed(1)}`)
    .join(' ');
  const signedCurrent = (value: number) => `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(2)} A`;

  return (
    <section className="lesson-nine-cycle-panel">
      <div className="lesson-nine-torque-heading">
        <div>
          <span>Electrical cycle</span>
          <h2>Balanced phase currents</h2>
        </div>
        <em>120° apart</em>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Three-phase current electrical cycle" className="lesson-nine-cycle-chart">
        <line x1={left} y1={y(0)} x2={right} y2={y(0)} className="lesson-nine-chart-zero" />
        <line x1={left} y1={top} x2={left} y2={bottom} className="lesson-nine-chart-axis" />
        {[0, 90, 180, 270, 360].map((angle) => (
          <g key={angle}>
            <line x1={x(angle)} y1={top} x2={x(angle)} y2={bottom} className="lesson-nine-chart-grid" />
            <text x={x(angle)} y={height - 13} textAnchor="middle">{angle}°</text>
          </g>
        ))}
        <text x={left - 7} y={top + 4} textAnchor="end">+{amplitude.toFixed(0)}</text>
        <text x={left - 7} y={y(0) + 4} textAnchor="end">0</text>
        <text x={left - 7} y={bottom + 4} textAnchor="end">−{amplitude.toFixed(0)}</text>
        {phaseDefinitions.map((phase) => (
          <path key={phase.id} d={pathFor(phase.offsetDeg)} className={`lesson-nine-current-line is-${phase.id}`} />
        ))}
        <line x1={x(cursorAngle)} y1={top} x2={x(cursorAngle)} y2={bottom} className="lesson-nine-chart-cursor" />
        {phaseDefinitions.map((phase) => (
          <circle
            key={phase.id}
            cx={x(cursorAngle)}
            cy={y(currentAt(cursorAngle, phase.offsetDeg))}
            r="4.5"
            className={`lesson-nine-current-point is-${phase.id}`}
          />
        ))}
      </svg>
      <div className="lesson-nine-current-readout">
        {phaseDefinitions.map((phase) => (
          <div key={phase.id} className={`is-${phase.id}`}>
            <span>{phase.label}</span>
            <strong>{signedCurrent(currentAt(cursorAngle, phase.offsetDeg))}</strong>
          </div>
        ))}
      </div>
      <p className="lesson-nine-cycle-note">
        The balanced source currents follow the rotor q-axis through the solved sweep.
      </p>
    </section>
  );
}

export const LearningMotorMagneticCircuit: React.FC<LearningMotorMagneticCircuitProps> = ({
  stage,
  onStageChange,
  onHeaderProgressChange,
}) => {
  const [internalStage, setInternalStage] = React.useState<MagneticCircuitStage>('design');
  const [designSettings, setDesignSettings] = React.useState<MagneticCircuitDesignSettings>(MAGNETIC_CIRCUIT_DEFAULT_DESIGN);
  const [currentMagnitude, setCurrentMagnitude] = React.useState(MAGNETIC_CIRCUIT_PHASE_CURRENT.default);
  const [showFluxLines, setShowFluxLines] = React.useState(true);
  const [showBMap, setShowBMap] = React.useState(false);
  const [showMeshOverlay, setShowMeshOverlay] = React.useState(false);
  const [showThreeD, setShowThreeD] = React.useState(false);
  const [settingsDrawerOpen, setSettingsDrawerOpen] = React.useState(false);
  const [meshStatus, setMeshStatus] = React.useState<'idle' | 'meshing' | 'complete' | 'error'>('idle');
  const [meshData, setMeshData] = React.useState<MeshPreviewData | null>(null);
  const [meshDesignSettings, setMeshDesignSettings] = React.useState<MagneticCircuitDesignSettings | null>(null);
  const [meshError, setMeshError] = React.useState<string | null>(null);
  const [solveStatus, setSolveStatus] = React.useState<'idle' | 'running' | 'complete' | 'error'>('idle');
  const [solveResult, setSolveResult] = React.useState<TutorialLessonOneSolveResult | null>(null);
  const [solveProgress, setSolveProgress] = React.useState<SolveProgress | null>(null);
  const [solveError, setSolveError] = React.useState<string | null>(null);
  const [fieldSource, setFieldSource] = React.useState<LessonNineFieldSource>('combined');
  const [fieldSourceSweeps, setFieldSourceSweeps] = React.useState<{
    stator: LessonOneFieldCompositionResult | null;
    rotor: LessonOneFieldCompositionResult | null;
  }>({ stator: null, rotor: null });
  const [fieldSourceStatus, setFieldSourceStatus] = React.useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [fieldSourceError, setFieldSourceError] = React.useState<string | null>(null);
  const [hasSolvedOnce, setHasSolvedOnce] = React.useState(false);
  const [activeFieldFrameData, setActiveFieldFrameData] = React.useState<FieldLinePlotData | null>(null);
  const [fieldFrameStatus, setFieldFrameStatus] = React.useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [inspectionAngle, setInspectionAngle] = React.useState<number | null>(null);
  const [playing, setPlaying] = React.useState(false);
  const [lessonCheckOpen, setLessonCheckOpen] = React.useState(false);
  const [knowledgePassed, setKnowledgePassed] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(true);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const { setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();

  React.useEffect(() => {
    if (knowledgePassed) setLessonComplete('motor-magnetic-circuit', true);
  }, [knowledgePassed, setLessonComplete]);

  const meshRequestIdRef = React.useRef(0);
  const solveRequestIdRef = React.useRef(0);
  const fieldFrameRequestIdRef = React.useRef(0);
  const fieldSourceRequestIdRef = React.useRef(0);
  const fieldFrameCacheRef = React.useRef(new Map<string, FieldLinePlotData>());
  const solveAbortRef = React.useRef<AbortController | null>(null);
  const mountedRef = React.useRef(true);

  const requestedStage = stage ?? internalStage;
  // Lesson 9 intentionally folds its former Mesh stop into Solve. Treat any
  // persisted/legacy mesh stage as Solve so old sessions cannot reopen the
  // removed intermediate screen.
  const lessonStage: LessonNineStage = requestedStage === 'design' ? 'design' : 'solve';
  const currentStageOrder = stageOrder(lessonStage);
  const activeStageItem = LESSON_TWO_STAGES[currentStageOrder] ?? LESSON_TWO_STAGES[0];
  const meshMatchesDesign = designSettingsEqual(meshDesignSettings, designSettings);
  const meshComplete = meshStatus === 'complete' && meshData !== null && meshMatchesDesign;

  const solvedFieldFrames = React.useMemo(() => {
    const frames = fieldSource === 'combined'
      ? solveResult?.field_line_frames ?? solveResult?.live_field_line_frames ?? []
      : fieldSourceSweeps[fieldSource]?.frames ?? [];
    return frames.filter((frame): frame is LiveFieldLineFrameData => (
      typeof frame?.angle_deg === 'number' && Number.isFinite(frame.angle_deg)
    ));
  }, [fieldSource, fieldSourceSweeps, solveResult]);

  const playbackAngles = React.useMemo(() => {
    const sorted = solvedFieldFrames
      .map((frame) => ((frame.angle_deg % 360) + 360) % 360)
      .sort((a, b) => a - b);
    return sorted.filter((angle, index) => index === 0 || Math.abs(angle - sorted[index - 1]) > 0.05);
  }, [solvedFieldFrames]);

  // The frame with the strongest airgap flux best shows the closed loop.
  const bestFrame = React.useMemo(() => {
    if (solvedFieldFrames.length === 0) return null;
    return solvedFieldFrames.reduce((best, frame) => {
      const framePeak = peakAirgapRadialB(frame.airgap_brbt, frame.airgap_b_stats) ?? -1;
      const bestPeak = peakAirgapRadialB(best.airgap_brbt, best.airgap_b_stats) ?? -1;
      return framePeak > bestPeak ? frame : best;
    }, solvedFieldFrames[0]);
  }, [solvedFieldFrames]);

  const activeFieldFrame = React.useMemo(() => {
    if (solvedFieldFrames.length === 0) return null;
    const target = inspectionAngle ?? bestFrame?.angle_deg ?? solvedFieldFrames[0].angle_deg;
    return solvedFieldFrames.reduce((nearest, frame) => (
      circularAngleDistance(frame.angle_deg, target) < circularAngleDistance(nearest.angle_deg, target)
        ? frame
        : nearest
    ), solvedFieldFrames[0]);
  }, [bestFrame, inspectionAngle, solvedFieldFrames]);

  const activeFieldFrameArtifactId = activeFieldFrame?.full_field_frame_artifact?.artifact_id
    ?? activeFieldFrame?.field_frame_artifact?.artifact_id
    ?? null;

  const setLessonStage = React.useCallback((nextStage: LessonNineStage) => {
    setLessonCheckOpen(false);
    if (nextStage === 'design') {
      setPlaying(false);
      setShowThreeD(false);
    }
    setInternalStage(nextStage);
    onStageChange?.(nextStage);
  }, [onStageChange]);

  const resetSolveForReSolve = React.useCallback(() => {
    setPlaying(false);
    fieldSourceRequestIdRef.current += 1;
    fieldFrameCacheRef.current.clear();
    setSolveResult(null);
    setFieldSource('combined');
    setFieldSourceSweeps({ stator: null, rotor: null });
    setFieldSourceStatus('idle');
    setFieldSourceError(null);
    setActiveFieldFrameData(null);
    setFieldFrameStatus('idle');
    setInspectionAngle(null);
    if (solveStatus !== 'running') {
      setSolveStatus('idle');
      setSolveProgress(null);
      setSolveError(null);
    }
  }, [solveStatus]);

  const resetMeshAndSolve = React.useCallback(() => {
    setPlaying(false);
    meshRequestIdRef.current += 1;
    solveRequestIdRef.current += 1;
    fieldFrameRequestIdRef.current += 1;
    fieldSourceRequestIdRef.current += 1;
    fieldFrameCacheRef.current.clear();
    void solveClient.cancelSolve().catch(() => undefined);
    solveAbortRef.current?.abort();
    solveAbortRef.current = null;
    setMeshData(null);
    setMeshDesignSettings(null);
    setMeshStatus('idle');
    setMeshError(null);
    setSolveResult(null);
    setSolveStatus('idle');
    setSolveProgress(null);
    setSolveError(null);
    setFieldSource('combined');
    setFieldSourceSweeps({ stator: null, rotor: null });
    setFieldSourceStatus('idle');
    setFieldSourceError(null);
    setActiveFieldFrameData(null);
    setFieldFrameStatus('idle');
    setInspectionAngle(null);
  }, [solveClient]);

  const handleDesignSettingChange = React.useCallback((key: MagneticCircuitDesignKey, value: number) => {
    if (!Number.isFinite(value)) return;
    const field = MAGNETIC_CIRCUIT_DESIGN_FIELDS.find((item) => item.key === key);
    if (!field) return;
    const nextValue = clampNumber(value, field.min, field.max);
    if (Math.abs(designSettings[key] - nextValue) < 1e-9) return;
    setLessonCheckOpen(false);
    resetMeshAndSolve();
    setDesignSettings((current) => ({ ...current, [key]: nextValue }));
  }, [designSettings, resetMeshAndSolve]);

  const handlePhaseCurrentChange = React.useCallback((value: number) => {
    if (!Number.isFinite(value)) return;
    setLessonCheckOpen(false);
    resetSolveForReSolve();
    setCurrentMagnitude(clampNumber(value, MAGNETIC_CIRCUIT_PHASE_CURRENT.min, MAGNETIC_CIRCUIT_PHASE_CURRENT.max));
  }, [resetSolveForReSolve]);

  const runMesh = React.useCallback(async (): Promise<MeshPreviewData | null> => {
    const requestId = meshRequestIdRef.current + 1;
    const requestDesign = { ...designSettings };
    meshRequestIdRef.current = requestId;
    setMeshStatus('meshing');
    setMeshError(null);
    setMeshDesignSettings(null);
    try {
      const mesh = await solveClient.fetchTutorialLessonOneMeshPreview(tutorialDesignOptions(requestDesign));
      if (!mountedRef.current || meshRequestIdRef.current !== requestId) return null;
      setMeshData(mesh);
      setMeshDesignSettings(requestDesign);
      setMeshStatus('complete');
      return mesh;
    } catch (error) {
      if (!mountedRef.current || meshRequestIdRef.current !== requestId) return null;
      setMeshData(null);
      setMeshDesignSettings(null);
      setMeshStatus('error');
      const message = error instanceof Error ? error.message : 'Gmsh mesh preview failed.';
      setMeshError(message);
      throw error instanceof Error ? error : new Error(message);
    }
  }, [designSettings, solveClient]);

  const startSolveStream = React.useCallback((requestId: number) => {
    if (!mountedRef.current || solveRequestIdRef.current !== requestId) return;
    setSolveProgress({ position: 0, total: 0, stage: 'starting', elapsed_s: 0 });

    const controller = solveClient.solveTutorialLessonOneStream(
      {
        phaseCurrentA: currentMagnitude,
        currentAngleDeg: 0,
        ...tutorialDesignOptions(designSettings),
      },
      (progress) => {
        if (!mountedRef.current || solveRequestIdRef.current !== requestId) return;
        setSolveProgress(progress);
      },
      (result) => {
        if (!mountedRef.current || solveRequestIdRef.current !== requestId) return;
        const completedPositions = result.tutorial_solve?.positions ?? LESSON_TWO_SOLVE_POSITIONS;
        setSolveResult(result);
        setSolveProgress({ position: completedPositions, total: completedPositions, stage: 'complete', elapsed_s: 0 });
        setSolveStatus('complete');
        setFieldSource('combined');
        setFieldSourceStatus('ready');
        setHasSolvedOnce(true);
        setLabControlsOpen(false);
        solveAbortRef.current = null;
      },
      (error) => {
        if (!mountedRef.current || solveRequestIdRef.current !== requestId) return;
        setSolveResult(null);
        setSolveStatus('error');
        setSolveError(error.message || 'Lesson solve failed.');
        solveAbortRef.current = null;
      },
    );
    solveAbortRef.current = controller;
  }, [currentMagnitude, designSettings, solveClient]);

  const runSolvePipeline = React.useCallback(async () => {
    const requestId = solveRequestIdRef.current + 1;
    solveRequestIdRef.current = requestId;
    solveAbortRef.current?.abort();
    solveAbortRef.current = null;
    setLessonStage('solve');
    setPlaying(false);
    fieldFrameCacheRef.current.clear();
    setLessonCheckOpen(false);
    setSolveStatus('running');
    setSolveProgress({ position: 0, total: 1, stage: 'gmsh_mesh', elapsed_s: 0 });
    setSolveError(null);
    setFieldSource('combined');
    setFieldSourceSweeps({ stator: null, rotor: null });
    setFieldSourceStatus('idle');
    setFieldSourceError(null);
    setSolveResult(null);
    setActiveFieldFrameData(null);
    setFieldFrameStatus('idle');
    setInspectionAngle(null);

    try {
      const mesh = meshComplete && meshData ? meshData : await runMesh();
      if (!mountedRef.current || solveRequestIdRef.current !== requestId || !mesh) return;
      startSolveStream(requestId);
    } catch (error) {
      if (!mountedRef.current || solveRequestIdRef.current !== requestId) return;
      setSolveStatus('error');
      setSolveProgress(null);
      setSolveError(error instanceof Error ? error.message : 'Gmsh mesh generation failed.');
    }
  }, [meshComplete, meshData, runMesh, setLessonStage, startSolveStream]);

  const handleCancelSolve = React.useCallback(() => {
    if (solveStatus !== 'running') return;
    meshRequestIdRef.current += 1;
    solveRequestIdRef.current += 1;
    fieldFrameRequestIdRef.current += 1;
    fieldSourceRequestIdRef.current += 1;
    void solveClient.cancelSolve().catch(() => undefined);
    solveAbortRef.current?.abort();
    solveAbortRef.current = null;
    setSolveResult(null);
    setPlaying(false);
    setSolveStatus('idle');
    setSolveProgress(null);
    setSolveError(null);
    setFieldSource('combined');
    setFieldSourceSweeps({ stator: null, rotor: null });
    setFieldSourceStatus('idle');
    setFieldSourceError(null);
    setActiveFieldFrameData(null);
    setFieldFrameStatus('idle');
    if (meshStatus === 'meshing') {
      setMeshData(null);
      setMeshDesignSettings(null);
      setMeshStatus('idle');
      setMeshError(null);
    }
  }, [meshStatus, solveClient, solveStatus]);

  const handlePrimaryAdvance = React.useCallback(() => {
    if (solveStatus === 'running') {
      handleCancelSolve();
      return;
    }
    void runSolvePipeline();
  }, [handleCancelSolve, runSolvePipeline, solveStatus]);

  const selectFieldSource = React.useCallback(async (nextSource: LessonNineFieldSource) => {
    if (solveStatus !== 'complete' || showThreeD || fieldSourceStatus === 'loading') return;
    const cachedSweep = nextSource === 'combined' ? null : fieldSourceSweeps[nextSource];
    if (nextSource === fieldSource && (nextSource === 'combined' || cachedSweep)) return;

    setPlaying(false);
    fieldFrameRequestIdRef.current += 1;
    setActiveFieldFrameData(null);
    setFieldSourceError(null);
    setFieldSource(nextSource);

    if (nextSource === 'combined' || cachedSweep) {
      setFieldSourceStatus('ready');
      setFieldFrameStatus('loading');
      return;
    }

    const requestId = fieldSourceRequestIdRef.current + 1;
    fieldSourceRequestIdRef.current = requestId;
    setFieldSourceStatus('loading');
    setFieldFrameStatus('loading');
    try {
      const result = await solveClient.fetchLessonOneFieldComposition(
        nextSource === 'stator' ? 'armature' : 'pm',
        {
          phaseCurrentA: currentMagnitude,
          currentAngleDeg: 0,
          ...tutorialDesignOptions(designSettings),
        },
      );
      if (!mountedRef.current || fieldSourceRequestIdRef.current !== requestId) return;
      setFieldSourceSweeps((current) => ({ ...current, [nextSource]: result }));
      setFieldSourceStatus('ready');
    } catch (error) {
      if (!mountedRef.current || fieldSourceRequestIdRef.current !== requestId) return;
      setFieldSourceStatus('error');
      setFieldFrameStatus('error');
      setFieldSourceError(
        error instanceof Error ? error.message : `The ${nextSource}-only field solve failed.`,
      );
    }
  }, [
    currentMagnitude,
    designSettings,
    fieldSource,
    fieldSourceStatus,
    fieldSourceSweeps,
    showThreeD,
    solveClient,
    solveStatus,
  ]);

  // Mount / unmount lifecycle.
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      meshRequestIdRef.current += 1;
      solveRequestIdRef.current += 1;
      fieldFrameRequestIdRef.current += 1;
      fieldSourceRequestIdRef.current += 1;
      solveAbortRef.current?.abort();
      solveAbortRef.current = null;
    };
  }, []);

  // Default-select the strongest-flux frame once a solve completes.
  React.useEffect(() => {
    if (solveStatus === 'complete' && bestFrame) {
      setInspectionAngle((prev) => (prev ?? bestFrame.angle_deg));
    }
  }, [bestFrame, solveStatus]);

  // Fetch the full field-frame artifact for the selected frame (carries
  // element_b_mag_t + airgap stats), merging in the mesh geometry like Lesson 1.
  React.useEffect(() => {
    if (lessonStage !== 'solve' || solveStatus !== 'complete' || !activeFieldFrameArtifactId) {
      if (solveStatus !== 'complete') {
        setActiveFieldFrameData(null);
        setFieldFrameStatus('idle');
      }
      return undefined;
    }
    const cachedFrame = fieldFrameCacheRef.current.get(activeFieldFrameArtifactId);
    if (cachedFrame) {
      setActiveFieldFrameData(cachedFrame);
      setFieldFrameStatus('ready');
      return undefined;
    }
    const requestId = fieldFrameRequestIdRef.current + 1;
    fieldFrameRequestIdRef.current = requestId;
    setFieldFrameStatus('loading');

    solveClient.fetchSolveFieldFrameArtifact(activeFieldFrameArtifactId)
      .then((payload) => {
        if (!mountedRef.current || fieldFrameRequestIdRef.current !== requestId) return;
        const frame = payload.field_line_frame;
        const frameData = {
          ...(meshData ?? {}),
          ...frame,
          // Full field artifacts carry geometry at the solved rotor position.
          // Preserve the frame metadata so the viewer never pairs a newly
          // selected angle with the preceding artifact while the next loads.
          angle_deg: frame.angle_deg ?? activeFieldFrame?.angle_deg,
          config_summary: frame.config_summary ?? meshData?.config_summary,
          mesh_info: frame.mesh_info ?? meshData?.mesh_info,
          nodes_mm: frame.nodes_mm?.length ? frame.nodes_mm : meshData?.nodes_mm,
          triangles: frame.triangles?.length ? frame.triangles : meshData?.triangles,
          regions: frame.regions?.length ? frame.regions : meshData?.regions,
          n_pole_pitches: frame.n_pole_pitches ?? meshData?.n_pole_pitches,
          total_span_deg: frame.total_span_deg ?? meshData?.total_span_deg,
        } as FieldLinePlotData;

        // Geometry is supplied by the mesh; if it hasn't arrived yet, wait for
        // it rather than handing MeshViewer a frame with no nodes. This effect
        // re-runs when meshData lands (it's a dependency).
        if (!hasRenderableGeometry(frameData)) {
          setFieldFrameStatus('loading');
          return;
        }
        fieldFrameCacheRef.current.set(activeFieldFrameArtifactId, frameData);
        setActiveFieldFrameData(frameData);
        setFieldFrameStatus('ready');
      })
      .catch(() => {
        if (!mountedRef.current || fieldFrameRequestIdRef.current !== requestId) return;
        setPlaying(false);
        setActiveFieldFrameData(null);
        setFieldFrameStatus('error');
      });

    return () => {
      fieldFrameRequestIdRef.current += 1;
    };
  }, [activeFieldFrame, activeFieldFrameArtifactId, lessonStage, meshData, solveClient, solveStatus]);

  const stageTitle = activeStageItem.title;
  const solveStale = lessonStage === 'solve' && solveStatus === 'idle' && hasSolvedOnce;
  const primaryActionLabel = lessonStage === 'design'
    ? 'Solve motor'
      : solveStatus === 'running'
        ? 'Cancel Solve'
        : solveStatus === 'complete'
          ? 'Re-run solve'
          : solveStatus === 'error'
            ? 'Retry solve'
            : solveStale
              ? 'Re-solve'
              : 'Solve motor';
  const primaryDisabled = false;

  const progressSteps = React.useMemo<LearningLessonProgressStep[]>(() => (
    LESSON_TWO_STAGES.map((item, index) => ({
      id: item.id,
      label: item.title,
      complete: index < currentStageOrder || (item.id === 'solve' && knowledgePassed),
      available: true,
    }))
  ), [currentStageOrder, knowledgePassed]);
  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 9,
    lessonCount: 10,
    title: 'Inside a Motor’s Magnetic Circuit',
    currentStepId: lessonStage,
    steps: progressSteps,
    onStepSelect: (stepId) => {
      if (stepId === 'design') {
        if (solveStatus === 'running') handleCancelSolve();
        setLessonStage('design');
      } else if (stepId === 'solve') {
        if (lessonStage === 'design' && solveStatus !== 'complete') {
          void runSolvePipeline();
        } else {
          setLessonStage('solve');
        }
      }
    },
  }), [handleCancelSolve, lessonStage, progressSteps, runSolvePipeline, setLessonStage, solveStatus]);

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  const selectedFrameAngle = inspectionAngle ?? activeFieldFrame?.angle_deg ?? 0;
  const renderedFrameAngle = activeFieldFrameData?.angle_deg ?? selectedFrameAngle;
  const playbackFrameIndex = selectedFrameAngle >= 359.9
    ? playbackAngles.length
    : playbackAngles.reduce((nearestIndex, angle, index) => (
      circularAngleDistance(angle, selectedFrameAngle)
        < circularAngleDistance(playbackAngles[nearestIndex] ?? angle, selectedFrameAngle)
        ? index
        : nearestIndex
    ), 0);

  const selectPlaybackFrame = React.useCallback((nextIndex: number) => {
    if (!playbackAngles.length) return;
    setPlaying(false);
    setInspectionAngle(nextIndex >= playbackAngles.length ? 360 : playbackAngles[Math.max(0, nextIndex)]);
  }, [playbackAngles]);

  const playCycle = React.useCallback(() => {
    if (!playbackAngles.length) return;
    setInspectionAngle(playbackAngles[0]);
    setPlaying(true);
  }, [playbackAngles]);

  React.useEffect(() => {
    if (
      !playing
      || solveStatus !== 'complete'
      || fieldFrameStatus !== 'ready'
      || !playbackAngles.length
    ) return undefined;
    const timer = window.setTimeout(() => {
      setInspectionAngle((currentAngle) => {
        const target = currentAngle ?? playbackAngles[0];
        const currentIndex = target >= 359.9
          ? playbackAngles.length
          : playbackAngles.reduce((nearestIndex, angle, index) => (
            circularAngleDistance(angle, target)
              < circularAngleDistance(playbackAngles[nearestIndex] ?? angle, target)
              ? index
              : nearestIndex
          ), 0);
        if (currentIndex >= playbackAngles.length - 1) {
          setPlaying(false);
          return 360;
        }
        return playbackAngles[currentIndex + 1];
      });
    }, 140);
    return () => window.clearTimeout(timer);
  }, [fieldFrameStatus, playbackAngles, playing, selectedFrameAngle, solveStatus]);

  const threeDRotorViewAngle = selectedFrameAngle - 90;
  const previewTorqueWaveform = torquePreview(currentMagnitude, designSettings);
  const threeDMotorConfig = React.useMemo(
    () => lessonNineMotorConfig(designSettings, currentMagnitude),
    [currentMagnitude, designSettings],
  );
  const machineSettings: Array<[string, string]> = [
    ['Machine', '2p/6s SPM'],
    ['Airgap', designSettings.airgapMm.toFixed(1) + ' mm'],
    ['Magnet thick.', designSettings.magnetThicknessMm.toFixed(1) + ' mm'],
    ['Magnet arc', designSettings.magnetArcPct.toFixed(0) + '%'],
    ['Phase current', currentMagnitude.toFixed(1) + ' A'],
    ['Sweep', '0–360 elec deg, 48 positions'],
  ];
  const canShowSolvedField = Boolean(
    activeFieldFrameData && hasRenderableGeometry(activeFieldFrameData),
  );
  const fieldSourceLabel = LESSON_NINE_FIELD_SOURCES.find((item) => item.id === fieldSource)?.label
    ?? 'Combined';

  return (
    <main className={'learning-shell learning-lesson-shell lesson-two-shell lesson-nine-shell is-' + lessonStage + '-stage' + (lessonCheckOpen ? ' is-quiz-open' : '') + (labControlsOpen && !lessonCheckOpen ? ' has-lab-controls' : '') + (solveInspectorOpen && !lessonCheckOpen ? ' has-solve-inspector' : '') + (solveStatus === 'running' ? ' is-solve-running' : '')}>
      <header className="tutorial-studio-strip lesson-nine-studio-strip">
        <div className="lesson-nine-studio-context">
          <strong>{lessonStage === 'design' ? '2p/6s SPM · geometry' : '2p/6s SPM · balanced field solve'}</strong>
          <span>{lessonStage === 'design'
            ? 'Six winding sides · two rotor magnets'
            : solveStatus === 'running'
              ? solveProgressLabel(solveProgress, solveStatus)
              : fieldSourceStatus === 'loading'
                ? `Solving exact ${fieldSourceLabel.toLowerCase()} FEM field`
                : `${fieldSourceLabel} · ${currentMagnitude.toFixed(1)} A · ${selectedFrameAngle.toFixed(0)}° electrical`}</span>
        </div>
        {!lessonCheckOpen ? (
          <div className="lesson-nine-strip-center-controls">
            {lessonStage === 'solve' ? (
              <div
                className="lesson-nine-field-source-toggle"
                role="group"
                aria-label="Magnetic field source"
                aria-busy={fieldSourceStatus === 'loading'}
              >
                {LESSON_NINE_FIELD_SOURCES.map((source) => (
                  <button
                    key={source.id}
                    type="button"
                    className={fieldSource === source.id ? 'is-active' : ''}
                    aria-pressed={fieldSource === source.id}
                    disabled={showThreeD || solveStatus !== 'complete' || fieldSourceStatus === 'loading'}
                    onClick={() => { void selectFieldSource(source.id); }}
                  >{source.label}</button>
                ))}
              </div>
            ) : null}
            <div className="lesson-nine-strip-view-toggle" role="group" aria-label="Motor view">
              <button
                type="button"
                className={!showThreeD ? 'is-active' : ''}
                aria-pressed={!showThreeD}
                onClick={() => setShowThreeD(false)}
              >2D cross-section</button>
              <button
                type="button"
                className={showThreeD ? 'is-active' : ''}
                aria-pressed={showThreeD}
                onClick={() => setShowThreeD(true)}
              >3D machine</button>
            </div>
          </div>
        ) : null}
        {!lessonCheckOpen ? (
          <div className="lesson-nine-view-toolbar" role="group" aria-label="Motor visual layers">
            <button
              type="button"
              className={showFluxLines ? 'is-active' : ''}
              aria-pressed={showFluxLines}
              disabled={showThreeD || lessonStage !== 'solve' || !canShowSolvedField}
              onClick={() => setShowFluxLines((visible) => !visible)}
            >
              <i className="is-flux" aria-hidden="true" /> Flux lines
            </button>
            <button
              type="button"
              className={showBMap ? 'is-active' : ''}
              aria-pressed={showBMap}
              disabled={showThreeD || lessonStage !== 'solve' || !canShowSolvedField}
              onClick={() => setShowBMap((visible) => !visible)}
            >
              <i className="is-map" aria-hidden="true" /> |B| map
            </button>
            <button
              type="button"
              className={showMeshOverlay ? 'is-active' : ''}
              aria-pressed={showMeshOverlay}
              disabled={showThreeD || lessonStage === 'design'}
              onClick={() => setShowMeshOverlay((visible) => !visible)}
            >
              <i className="is-mesh" aria-hidden="true" /> Mesh
            </button>
          </div>
        ) : null}
      </header>
      {!lessonCheckOpen && lessonStage === 'solve' && solveStatus === 'running' ? (
        <div className="learning-solve-progress lesson-nine-solve-progress">
          <div className="learning-solve-progress-copy">
            <span>Mesh + balanced solve</span>
            <div className="learning-solve-progress-status">
              <strong>{solveProgressLabel(solveProgress, solveStatus)}</strong>
              <button type="button" className="learning-solve-cancel-button" onClick={handleCancelSolve}>Cancel</button>
            </div>
          </div>
          <div
            className="learning-solve-progress-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(solveProgressPercent(solveProgress, solveStatus))}
          >
            <span style={{ width: solveProgressPercent(solveProgress, solveStatus) + '%' }} />
          </div>
        </div>
      ) : null}
      <section className={'learning-main-stage is-' + lessonStage + '-stage'}>
        {lessonCheckOpen ? (
          <section className="lesson-nine-quiz-stage">
            <p className="learning-kicker">Final check</p>
            <h2>Can you connect the motor geometry to its torque waveform?</h2>
            <p>Use the six winding sides, resolved magnetic circuit, and solved rotor-angle sweep.</p>
            <KnowledgeCheck questions={MAGNETIC_CIRCUIT_KNOWLEDGE_CHECK} onPassedChange={setKnowledgePassed} />
          </section>
        ) : <div className="learning-motor-viewport lesson-nine-viewport">
          <div className="lesson-nine-visual-body">
            {showThreeD ? (
              <PublicMotor3D
                config={threeDMotorConfig}
                resetSignal={0}
                rotorAngleDeg={threeDRotorViewAngle}
                explodedAmount={0}
              />
            ) : lessonStage === 'solve' ? (
              fieldSourceStatus === 'loading' ? (
                <div className="learning-mesh-placeholder">
                  <div className="learning-spinner" />
                  <strong>Solving {fieldSourceLabel.toLowerCase()} field…</strong>
                  <span>Running the source-separated FEM sweep once, then caching all 48 positions.</span>
                </div>
              ) : fieldSourceStatus === 'error' ? (
                <div className="learning-mesh-placeholder is-error">
                  <strong>{fieldSourceLabel} field solve failed</strong>
                  <span>{fieldSourceError ?? 'Select the field source again to retry.'}</span>
                </div>
              ) : canShowSolvedField && activeFieldFrameData ? (
                <MeshViewer
                  meshData={activeFieldFrameData}
                  embedded
                  compactEmbedded
                  minScale={0.2}
                  title="2p/6s solved field"
                  subtitle={'Electrical angle ' + renderedFrameAngle.toFixed(1) + '°'}
                  // Each solved artifact already bakes the rotor at its sweep
                  // angle. A second SVG rotation would double the motion and
                  // make the physical magnet arcs jump between frames.
                  rotorAngleDeg={0}
                  // The A-C-B winding belt maps increasing source angle to a
                  // clockwise field in this SVG convention. At 0° electrical,
                  // the stator N axis is approximately +90° mechanical.
                  statorFieldAngleDeg={90 - renderedFrameAngle}
                  statorPoleLabelsFromField={fieldSource === 'stator'}
                  // Permanent-magnet polarity belongs to the rotor, not to the
                  // instantaneous combined B field. The solved mesh is already
                  // rotated, so anchor N to that baked rotor angle every frame.
                  // Solver mesh +angle is opposite the displayed electrical
                  // direction, hence the negative sign.
                  magnetPolarityHintDeg={-renderedFrameAngle}
                  tutorialOverlayMode="flux"
                  showMagnetizationLabels
                  shaftRadiusMm={LESSON_TWO_SHAFT_RADIUS_MM}
                  splitConcentratedSlotWindings
                  toolbarMode="zoom-only"
                  toolbarLabel={showBMap ? '|B| map' : showFluxLines ? 'flux lines' : 'geometry'}
                  showMeshEdges={showMeshOverlay}
                  showFieldIntensity={showBMap}
                  smoothFieldIntensity
                  fieldLinesVisible={showFluxLines}
                />
              ) : solveStatus === 'complete' && fieldFrameStatus === 'loading' ? (
                <div className="learning-mesh-placeholder">
                  <div className="learning-spinner" />
                  <strong>Loading solved field frame…</strong>
                  <span>Fetching the field at the selected rotor angle.</span>
                </div>
              ) : solveStatus === 'complete' && fieldFrameStatus === 'error' ? (
                <div className="learning-mesh-placeholder is-error">
                  <strong>Field frame could not be loaded</strong>
                  <span>Select another angle or field source to retry.</span>
                </div>
              ) : solveStatus === 'error' ? (
                <div className="learning-mesh-placeholder is-error">
                  <strong>Motor solve failed</strong>
                  <span>{solveError ?? meshError ?? 'Try the mesh and solve again.'}</span>
                </div>
              ) : meshData ? (
                <MeshViewer
                  meshData={meshData}
                  embedded
                  compactEmbedded
                  minScale={0.2}
                  title={solveStatus === 'running' ? 'Solving balanced motor' : 'Motor solve mesh'}
                  subtitle={solveStatus === 'running' ? solveProgressLabel(solveProgress, solveStatus) : 'Mesh generated with the solve'}
                  shaftRadiusMm={LESSON_TWO_SHAFT_RADIUS_MM}
                  splitConcentratedSlotWindings
                  showMeshEdges={showMeshOverlay}
                  toolbarMode="zoom-only"
                  toolbarLabel="solve mesh"
                />
              ) : (
                <div className="learning-mesh-placeholder">
                  {solveStatus === 'running' ? <div className="learning-spinner" /> : null}
                  <strong>{solveStatus === 'running' ? 'Generating Gmsh mesh…' : 'Ready to solve'}</strong>
                  <span>{solveStatus === 'running'
                    ? 'Meshing the full motor before the balanced field sweep starts automatically.'
                    : 'One solve builds the mesh, traces the field, and computes the torque waveform.'}</span>
                </div>
              )
            ) : (
              <LessonMotorDiagram
                stage={lessonStage}
                rotorAngle={inspectionAngle ?? 90}
                currentMagnitude={currentMagnitude}
                designSettings={designSettings}
                sweepProgress={0}
              />
            )}
          </div>
        </div>}
      </section>

      {labControlsOpen && !lessonCheckOpen ? <aside className="learning-control-panel lesson-nine-control-panel">
        <button type="button" className="tutorial-studio-panel-close" aria-label="Close motor controls" onClick={() => setLabControlsOpen(false)}>×</button>
        <section className="tutorial-studio-goal">
          <span>{currentStageOrder + 1}/2</span>
          <div>
            <p className="learning-kicker">Current goal</p>
            <h2>{lessonStage === 'design'
              ? 'Assign every winding side'
              : lessonCheckOpen
                ? 'Explain the torque waveform'
                : 'Connect field alignment to torque'}</h2>
          </div>
        </section>

        <section className="lesson-nine-phase-card" aria-label="Concentrated tooth-coil phase assignment">
          <div>
            <span>Winding topology</span>
            <strong>One phase coil per tooth</strong>
          </div>
          <ol>
            <li><b className="is-a">A+</b><em>tooth coil</em><b className="is-a">A−</b><em>tooth coil</em></li>
            <li><b className="is-b">B+</b><em>tooth coil</em><b className="is-b">B−</b><em>tooth coil</em></li>
            <li><b className="is-c">C+</b><em>tooth coil</em><b className="is-c">C−</b><em>tooth coil</em></li>
          </ol>
          <p>The stator teeth stay steel gray. Phase colors identify only the copper coil sides in the slots: each tooth coil places one side in each neighboring slot, so every slot is split between two adjacent coils; ⊙/⊗ show current direction.</p>
        </section>

        <section className="learning-control-section">
            <h2>{lessonStage === 'design' ? 'Design controls' : 'Field controls'}</h2>
            {lessonStage === 'solve' ? (
              <>
                <label className="learning-slider">
                  <span><strong>Phase current</strong><em>{currentMagnitude.toFixed(1)} A</em></span>
                  <input
                    type="range"
                    aria-label="Phase current"
                    min={MAGNETIC_CIRCUIT_PHASE_CURRENT.min}
                    max={MAGNETIC_CIRCUIT_PHASE_CURRENT.max}
                    step={MAGNETIC_CIRCUIT_PHASE_CURRENT.step}
                    value={currentMagnitude}
                    onChange={(event) => handlePhaseCurrentChange(Number(event.target.value))}
                    disabled={solveStatus === 'running'}
                  />
                </label>
                <p className="lesson-nine-control-note">
                  Use the electrical-angle player in the bottom dock after a solve to inspect every FEM frame and its torque.
                </p>
                {solveStale ? <p className="tutorial-stale-note">Inputs changed — re-solve to refresh the field.</p> : null}
              </>
            ) : (
              <div className="learning-stage-copy">
                <strong>2p/6s SPM baseline</strong>
                <p>The gray sectors are electrical-steel teeth. A/B/C colors mark the copper sides sharing each of the six slots, matching the 3D machine and the main motor designer.</p>
              </div>
            )}
        </section>

        <section className={'learning-settings-drawer' + (settingsDrawerOpen ? ' is-open' : '')}>
          <button
            type="button"
            className="learning-settings-drawer-toggle"
            onClick={() => setSettingsDrawerOpen((open) => !open)}
            aria-expanded={settingsDrawerOpen}
          >
            <span><strong>Machine settings</strong><em>2p/6s SPM</em></span>
            <i aria-hidden="true">{settingsDrawerOpen ? '−' : '+'}</i>
          </button>
          {settingsDrawerOpen ? (
            <dl className="learning-settings-list">
              {machineSettings.map(([label, value]) => (
                <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
              ))}
            </dl>
          ) : null}
        </section>

        {lessonStage === 'design' ? (
          <section className="learning-rail-design-settings" aria-label="Design settings">
            <h2>Design settings</h2>
            {MAGNETIC_CIRCUIT_DESIGN_FIELDS.map((field) => (
              <label key={field.key} className="learning-setting-field">
                <span>{field.label}</span>
                <div>
                  <input
                    type="number"
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    value={designSettings[field.key]}
                    onChange={(event) => handleDesignSettingChange(field.key, event.currentTarget.valueAsNumber)}
                    disabled={meshStatus === 'meshing' || solveStatus === 'running'}
                  />
                  <em>{field.unit}</em>
                </div>
                <input
                  className="learning-setting-range"
                  type="range"
                  aria-label={`${field.label} slider`}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={designSettings[field.key]}
                  onChange={(event) => handleDesignSettingChange(field.key, Number(event.currentTarget.value))}
                  disabled={meshStatus === 'meshing' || solveStatus === 'running'}
                />
              </label>
            ))}
          </section>
        ) : null}

        {lessonStage === 'solve' && solveError ? <p className="learning-nav-error">{solveError}</p> : null}

      </aside> : null}

      {solveInspectorOpen && !lessonCheckOpen ? <aside className="learning-context-panel lesson-nine-context" aria-label="Motor solved results">
        <button type="button" className="tutorial-studio-panel-close" aria-label="Close solved results" onClick={() => setSolveInspectorOpen(false)}>×</button>
        <div className="lesson-nine-results-stack">
          <TrendChart
            waveform={solveResult?.torque_waveform}
            selectedAngleDeg={selectedFrameAngle}
            preview={previewTorqueWaveform}
          />
          <ElectricalCycleChart
            selectedAngleDeg={selectedFrameAngle}
            currentMagnitude={currentMagnitude}
          />
        </div>
      </aside> : null}

      <section className={`tutorial-studio-dock lesson-nine-studio-dock${!lessonCheckOpen && solveStatus === 'complete' ? ' has-playback' : ''}`} aria-label="Lesson controls">
        <div className="lesson-nine-dock-context">
          <span>{lessonCheckOpen ? 'CHECK' : lessonStage.toUpperCase()}</span>
          <strong>{lessonCheckOpen
            ? 'Explain how field alignment becomes positive and negative torque.'
            : lessonStage === 'design'
              ? 'Set the geometry, then solve—the mesh is generated automatically.'
              : solveStatus === 'complete' ? 'The field and torque waveform are ready to inspect.' : 'Build the mesh and sweep one balanced electrical cycle.'}</strong>
        </div>
        {!lessonCheckOpen && solveStatus === 'complete' ? (
          <div className="lesson-nine-dock-playback">
            <label>
              <span>Electrical angle</span>
              <strong>{selectedFrameAngle.toFixed(1)}°</strong>
              <input
                type="range"
                min={0}
                max={playbackAngles.length}
                step={1}
                value={playbackFrameIndex}
                onChange={(event) => selectPlaybackFrame(Number(event.currentTarget.value))}
                aria-label="Solved motor electrical angle frame"
                disabled={!playbackAngles.length || fieldSourceStatus === 'loading'}
              />
            </label>
            <button
              type="button"
              className={`lesson-nine-play-cycle${playing ? ' is-active' : ''}`}
              disabled={!playbackAngles.length || fieldSourceStatus === 'loading'}
              onClick={() => (playing ? setPlaying(false) : playCycle())}
            >{playing ? 'Pause cycle' : 'Play cycle'}</button>
          </div>
        ) : null}
        <div className="tutorial-studio-dock-actions">
          {!lessonCheckOpen ? <button type="button" className={labControlsOpen ? 'is-active' : ''} disabled={fieldSourceStatus === 'loading'} onClick={() => setLabControlsOpen((open) => !open)}>{labControlsOpen ? 'Done' : 'Adjust experiment'}</button> : <button type="button" onClick={() => setLessonCheckOpen(false)}>Review experiment</button>}
          {!lessonCheckOpen ? <button
            type="button"
            className={solveInspectorOpen ? 'is-active' : ''}
            aria-expanded={solveInspectorOpen}
            disabled={solveStatus !== 'complete'}
            onClick={() => {
              setSolveInspectorOpen((open) => {
                if (!open) setLabControlsOpen(false);
                return !open;
              });
            }}
          >Inspect results</button> : null}
          {lessonCheckOpen ? (
            knowledgePassed
              ? <a className="learning-primary-button" href="/tutorials/lesson-10">Next lesson</a>
              : <button type="button" className="learning-primary-button" disabled>Pass the check</button>
          ) : lessonStage === 'solve' && solveStatus === 'complete' ? (
            <button type="button" className="learning-primary-button" disabled={fieldSourceStatus === 'loading'} onClick={() => {
              setPlaying(false);
              setLabControlsOpen(false);
              setSolveInspectorOpen(false);
              setLessonCheckOpen(true);
            }}>Continue to check</button>
          ) : (
            <button type="button" className="learning-primary-button" onClick={handlePrimaryAdvance} disabled={primaryDisabled}>{primaryActionLabel}</button>
          )}
        </div>
      </section>
    </main>
  );
};
