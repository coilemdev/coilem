import { CustomSteelImport } from './CustomSteelImport';
import { steelDisplayName, type CustomSteel, type SteelTarget } from './customSteel';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type Ref,
} from 'react';
import type { PublicApiError } from './api';
import { DESIGN_FILE_ACCEPT, DESIGN_FILE_EXTENSION } from './designFile';

import {
  MotorCanvas,
  type PublicCanvasLayer,
  type PublicMagnetPolarityView,
  type PublicMeshDisplayMode,
  type PublicMeshElementSelection,
} from './MotorCanvas';
import { WindingLayoutView } from './WindingLayoutView';
import {
  buildDimensionAnnotations,
  deriveStatorSectionWidths,
  type DimensionAnnotation,
  type DimensionId,
} from './dimensionAnnotations';
import { FieldResultPlot } from './FieldResultPlot';
import {
  MaterialAssignmentStrip,
  MaterialBehaviorView,
  materialTargetKind,
  type PublicMaterialSubview,
  type PublicMaterialTarget,
} from './MaterialWorkspace';
import { PublicMotor3D } from './PublicMotor3D';
import { SolvedFieldViewer } from './SolvedFieldViewer';
import { WaveformChart } from './WaveformChart';
import { BldcTorqueCurrentChart } from './BldcTorqueCurrentChart';
import { PublicRunComparison } from './PublicRunComparison';
import { PUBLIC_EXAMPLE_OPTIONS, type PublicExampleId } from './exampleDesigns';
import {
  magneticAirgapMm,
  PUBLIC_AIRGAP_LAUNCH_MIN_MM,
  publicAirgapHealth,
} from './motorAirgap';
import { publicFlatIpmBurialHealth } from './flatIpmBurialHealth';
import type {
  GeometryPreview,
  MaterialCatalog,
  MeshPreview,
  MotorConfig,
  PublicArmatureFieldComposition,
  PublicElmerCapability,
  PublicMotorComponentKind,
  PublicMotorComponentSelection,
  PublicSavedRun,
  PublicSolverId,
  SolveResult,
  SolveValidation,
} from './model';
import type { PublicRunExportKind } from './api';
import type { PublicSolveProgress } from './api';
import { LessonProgressStepper } from '../components/tutorials/LessonProgressStepper';
import type { LearningLessonHeaderProgress } from '../components/tutorials/lessonStage';
import {
  publicMeshQualityBand,
  summarizePublicMeshQuality,
  type PublicMeshQualitySummary,
} from './meshQuality';
import {
  PUBLIC_CUSTOM_SWEEP_DEFAULT_STEP_DEG,
  PUBLIC_CUSTOM_SWEEP_MAX_STEP_DEG,
  PUBLIC_CUSTOM_SWEEP_MIN_STEP_DEG,
  type PublicSolvePreset,
} from './solvePlan';
import {
  isPublicSolveFinalizing,
  projectedPublicSolveElapsedSeconds,
} from './solveProgress';

export type PublicWorkflowStep = 'design' | 'solve' | 'report';
export type PublicBusyAction = 'geometry' | 'mesh' | 'solve' | 'field' | null;
export type PublicConnectionStatus = 'checking' | 'online' | 'offline';
export type PublicEditableSection = 'stator' | 'rotor' | 'winding' | 'materials' | 'solve_params';
export type PublicParameterSection = 'stator' | 'rotor' | 'advanced' | 'winding' | 'materials';

export interface PublicDesignEditFeedback {
  id: number;
  message: string;
  consequence: string | null;
  affectedKind: PublicMotorComponentKind | null;
}

interface CoilEmWorkspaceProps {
  config: MotorConfig;
  materials: MaterialCatalog;
  geometry: GeometryPreview | null;
  mesh: MeshPreview | null;
  validation: SolveValidation | null;
  validationChecking: boolean;
  validationError: string | null;
  result: SolveResult | null;
  armatureField: PublicArmatureFieldComposition | null;
  armatureFieldError: string | null;
  progress: PublicSolveProgress | null;
  liveSamples: PublicSolveProgress[];
  activeStep: PublicWorkflowStep;
  guidedActive?: boolean;
  guidedDesignSection?: PublicParameterSection | null;
  busy: PublicBusyAction;
  connectionStatus: PublicConnectionStatus;
  selectedSolver: PublicSolverId;
  elmerCapability: PublicElmerCapability;
  geometryStale: boolean;
  error: string | null;
  errorDetails?: PublicApiError | null;
  notice: string | null;
  progressPercent: number;
  meshElements: number;
  meshQuality: number;
  designName?: string | null;
  blankDesign?: boolean;
  editFeedback?: PublicDesignEditFeedback | null;
  onNewDesign?: () => void;
  onOpenDesignFile?: (file: File) => void;
  onSaveDesign?: () => void;
  onResetDesign?: () => void;
  onLoadExample?: (exampleId: PublicExampleId) => void;
  onOpenHalbach?: () => void;
  onHome: () => void;
  onStepChange: (step: PublicWorkflowStep) => void;
  onTopologyChange: (topology: MotorConfig['topology']) => void;
  onSectionChange: (
    section: PublicEditableSection,
    field: string,
    value: unknown,
    visitedSection?: PublicParameterSection,
  ) => void;
  onDesignSectionVisit: (section: PublicParameterSection) => void;
  onConvertProjectSteelToM350: () => void;
  onImportSteel: (material: CustomSteel, target: SteelTarget) => void;
  onMeshSettingChange: (
    field: 'mesh_density' | 'corner_refinement',
    value: MotorConfig['solve_params']['mesh_density'] | boolean,
  ) => void;
  onSolvePlanChange: (solvePlan: PublicSolvePreset) => void;
  onCustomSweepChange: (stepDeg: number) => void;
  onSolveSettingChange: (
    field: 'current_amplitude_A' | 'rated_speed_rpm' | 'nonlinear_solver' | 'current_amplitude_convention' | 'current_angle_deg' | 'excitation_mode' | 'commutation_advance_deg',
    value: MotorConfig['solve_params']['nonlinear_solver'] | MotorConfig['solve_params']['current_amplitude_convention'] | MotorConfig['solve_params']['excitation_mode'] | number,
  ) => void;
  onSolverChange: (solver: PublicSolverId) => void;
  onReset: () => void;
  onRefreshGeometry: () => void;
  onGenerateMesh: () => void;
  onStartSolve: () => void;
  onCancelSolve: () => void;
  onRequestArmatureField: () => void;
  onOpenRunFolder: (savedRun: PublicSavedRun) => Promise<void>;
  onDownloadRunExport: (
    savedRun: PublicSavedRun,
    exportKind: PublicRunExportKind,
  ) => Promise<void>;
  onOpenRunProject: (savedRun: PublicSavedRun) => void;
  onRerun: (savedRun: PublicSavedRun) => void;
  onUndoDesignEdit?: () => void;
  onDismissDesignEdit?: () => void;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

const RUN_PLAN_WAVEFORM_WIDTH = 264;
const RUN_PLAN_WAVEFORM_HEIGHT = 74;
const RUN_PLAN_WAVEFORM_CENTER_Y = RUN_PLAN_WAVEFORM_HEIGHT / 2;
const RUN_PLAN_WAVEFORM_AMPLITUDE = 22;
const RUN_PLAN_SIX_STEP_TABLE = [
  [1, -1, 0],
  [0, -1, 1],
  [-1, 0, 1],
  [-1, 1, 0],
  [0, 1, -1],
  [1, 0, -1],
] as const;

function runPlanSinePath(phaseOffsetRad: number): string {
  return Array.from({ length: 49 }, (_, index) => {
    const ratio = index / 48;
    const x = ratio * RUN_PLAN_WAVEFORM_WIDTH;
    const y = RUN_PLAN_WAVEFORM_CENTER_Y
      - Math.sin(ratio * Math.PI * 2 + phaseOffsetRad) * RUN_PLAN_WAVEFORM_AMPLITUDE;
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(' ');
}

function runPlanSixStepPath(phaseIndex: 0 | 1 | 2): string {
  const sectorWidth = RUN_PLAN_WAVEFORM_WIDTH / RUN_PLAN_SIX_STEP_TABLE.length;
  const yFor = (value: number) => RUN_PLAN_WAVEFORM_CENTER_Y
    - value * RUN_PLAN_WAVEFORM_AMPLITUDE;
  let path = `M 0 ${yFor(RUN_PLAN_SIX_STEP_TABLE[0][phaseIndex])}`;
  RUN_PLAN_SIX_STEP_TABLE.forEach((sector, index) => {
    const nextX = (index + 1) * sectorWidth;
    path += ` L ${nextX} ${yFor(sector[phaseIndex])}`;
    if (index < RUN_PLAN_SIX_STEP_TABLE.length - 1) {
      path += ` L ${nextX} ${yFor(RUN_PLAN_SIX_STEP_TABLE[index + 1][phaseIndex])}`;
    }
  });
  return path;
}

function ExcitationRunPlanPreview({ config }: { config: MotorConfig }) {
  const sixStep = config.solve_params.excitation_mode === 'ideal_six_step_120';
  const currentConvention = sixStep
    ? 'plateau'
    : config.solve_params.current_amplitude_convention === 'rms'
      ? 'RMS'
      : 'peak';
  const operatingIdentity = sixStep
    ? `${formatNumber(config.solve_params.current_amplitude_A, 1)} A ${currentConvention} · ${formatNumber(config.solve_params.commutation_advance_deg, 1)}° advance`
    : `${formatNumber(config.solve_params.current_amplitude_A, 1)} A ${currentConvention} · ${formatNumber(config.solve_params.current_angle_deg, 1)}° current angle`;
  const accessibleDescription = sixStep
    ? 'Ideal six-step BLDC phase currents. Two phases conduct at positive and negative plateau current while one phase floats in each of six sectors.'
    : 'Balanced sinusoidal phase currents. Phase A, B, and C are shifted by 120 electrical degrees.';
  const paths = sixStep
    ? [runPlanSixStepPath(0), runPlanSixStepPath(1), runPlanSixStepPath(2)]
    : [
      runPlanSinePath(0),
      runPlanSinePath(-2 * Math.PI / 3),
      runPlanSinePath(2 * Math.PI / 3),
    ];

  return (
    <section className={`public-excitation-preview ${sixStep ? 'six-step' : 'sinusoidal'}`} aria-label={`Excitation: ${accessibleDescription}`}>
      <div className="public-excitation-preview-heading">
        <div>
          <span>Excitation</span>
          <strong>{sixStep ? 'Six-step BLDC' : 'Sinusoidal current'}</strong>
        </div>
        <small>{sixStep ? '120° conduction' : 'Three-phase'}</small>
      </div>
      <svg
        className="public-excitation-preview-plot"
        viewBox={`0 0 ${RUN_PLAN_WAVEFORM_WIDTH} ${RUN_PLAN_WAVEFORM_HEIGHT}`}
        role="img"
        aria-label={accessibleDescription}
      >
        <title>{accessibleDescription}</title>
        <line className="axis" x1="0" y1={RUN_PLAN_WAVEFORM_CENTER_Y} x2={RUN_PLAN_WAVEFORM_WIDTH} y2={RUN_PLAN_WAVEFORM_CENTER_Y} />
        {sixStep && Array.from({ length: 7 }, (_, index) => (
          <line
            className="sector"
            x1={index * RUN_PLAN_WAVEFORM_WIDTH / 6}
            y1="6"
            x2={index * RUN_PLAN_WAVEFORM_WIDTH / 6}
            y2={RUN_PLAN_WAVEFORM_HEIGHT - 6}
            key={index}
          />
        ))}
        {paths.map((path, index) => (
          <path className={`phase phase-${String.fromCharCode(97 + index)}`} d={path} key={index} />
        ))}
      </svg>
      <div className="public-excitation-preview-footer">
        <span className="public-excitation-preview-legend" aria-label="Phase colors">
          <i className="phase-a" />A <i className="phase-b" />B <i className="phase-c" />C
        </span>
        <strong>{operatingIdentity}</strong>
      </div>
      {sixStep && <small className="public-excitation-preview-state">Two phases on · one phase floating · wye</small>}
    </section>
  );
}

function resultUsesSixStep(result: SolveResult, config?: MotorConfig): boolean {
  return result.solve_metadata.excitation_mode === 'ideal_six_step_120'
    || config?.solve_params.excitation_mode === 'ideal_six_step_120';
}

function lineBackEmf(result: SolveResult): { ab: number[]; bc: number[]; ca: number[] } {
  const waveform = result.back_emf_waveform;
  return {
    ab: waveform.line_ab_V ?? waveform.phase_a_V.map((value, index) => value - waveform.phase_b_V[index]),
    bc: waveform.line_bc_V ?? waveform.phase_b_V.map((value, index) => value - waveform.phase_c_V[index]),
    ca: waveform.line_ca_V ?? waveform.phase_c_V.map((value, index) => value - waveform.phase_a_V[index]),
  };
}

function IdealSixStepCommand() {
  const states = [
    ['S1', 'A+', 'B−', 'C open'],
    ['S2', 'C+', 'B−', 'A open'],
    ['S3', 'C+', 'A−', 'B open'],
    ['S4', 'B+', 'A−', 'C open'],
    ['S5', 'B+', 'C−', 'A open'],
    ['S6', 'A+', 'C−', 'B open'],
  ];
  return <section className="public-six-step-command" aria-label="Ideal six-step command states"><div><span>Drive interpretation</span><strong>Ideal six-step command</strong><p>Each 60° sector commands one positive phase, one negative phase, and one open phase. This is an ideal current boundary condition, not an ESC switching simulation.</p></div><ol>{states.map(([sector, positive, negative, open]) => <li key={sector}><strong>{sector}</strong><span>{positive}</span><span>{negative}</span><span>{open}</span></li>)}</ol></section>;
}

function needsRunStorageRecovery(message: string | null): boolean {
  if (!message) return false;
  return /saved-run workspace is full|solve workspace size limit|not have enough free disk space/i.test(message);
}

function StatusGlyph({ tone = 'good' }: { tone?: 'good' | 'info' | 'warning' }) {
  return (
    <span className={`public-status-glyph ${tone}`} aria-hidden="true">
      {tone === 'good' ? '✓' : tone === 'info' ? 'i' : '!'}
    </span>
  );
}

function WorkflowStepper({
  activeStep,
  solveAvailable,
  resultReady,
  solveRunning,
  workflowDisabled = false,
  onStepChange,
}: {
  activeStep: PublicWorkflowStep;
  solveAvailable: boolean;
  resultReady: boolean;
  solveRunning: boolean;
  workflowDisabled?: boolean;
  onStepChange: (step: PublicWorkflowStep) => void;
}) {
  const steps: Array<{ id: PublicWorkflowStep; label: string; available: boolean }> = [
    { id: 'design', label: 'Design', available: true },
    { id: 'solve', label: 'Solve', available: solveAvailable },
    { id: 'report', label: 'Results', available: resultReady },
  ];
  const activeIndex = steps.findIndex((step) => step.id === activeStep);

  return (
    <nav className="workflow-stepper workflow-stepper-inline" aria-label="Motor workflow">
      {steps.map((step, index) => {
        const active = !workflowDisabled && step.id === activeStep;
        const done = !workflowDisabled && index < activeIndex;
        const disabled = workflowDisabled || (!step.available && !active);
        return (
          <span className="public-step-wrap" key={step.id}>
            <button
              type="button"
              className={`stepper-step${active ? ' active' : ''}${done ? ' done' : ''}${disabled ? ' disabled' : ''}`}
              disabled={disabled}
              aria-current={active ? 'step' : undefined}
              onClick={() => onStepChange(step.id)}
            >
              <span className="stepper-step-num">{done ? '✓' : index + 1}</span>
              <span>{step.label}</span>
              {active && solveRunning && step.id === 'solve' && (
                <span className="stepper-step-chip running">Running</span>
              )}
            </button>
            {index < steps.length - 1 && <span className="stepper-arrow" aria-hidden="true" />}
          </span>
        );
      })}
    </nav>
  );
}

export function CoilEmTopBar({
  config,
  activeStep,
  solveAvailable,
  resultReady,
  solveRunning,
  connectionStatus,
  designName = null,
  onHome,
  onStepChange,
  onOpenDesignFile,
  onSaveDesign,
  onResetDesign,
  onLoadExample,
  onOpenHalbach,
  onNewDesign,
  workflowDisabled = false,
  tutorialProgress = null,
  tutorialCatalog = false,
  onTutorialCatalog,
  runHistoryOpen: controlledRunHistoryOpen,
  onRunHistoryOpenChange,
}: Pick<CoilEmWorkspaceProps, 'config' | 'activeStep' | 'connectionStatus' | 'onHome' | 'onStepChange'> & {
  solveAvailable: boolean;
  resultReady: boolean;
  solveRunning: boolean;
  designName?: string | null;
  onOpenDesignFile?: (file: File) => void;
  onSaveDesign?: () => void;
  onResetDesign?: () => void;
  onLoadExample?: (exampleId: PublicExampleId) => void;
  onOpenHalbach?: () => void;
  onNewDesign?: () => void;
  workflowDisabled?: boolean;
  tutorialProgress?: LearningLessonHeaderProgress | null;
  tutorialCatalog?: boolean;
  onTutorialCatalog?: () => void;
  runHistoryOpen?: boolean;
  onRunHistoryOpenChange?: (open: boolean) => void;
}) {
  const [designMenuOpen, setDesignMenuOpen] = useState(false);
  const [examplesMenuOpen, setExamplesMenuOpen] = useState(false);
  const [internalRunHistoryOpen, setInternalRunHistoryOpen] = useState(false);
  const runHistoryOpen = controlledRunHistoryOpen ?? internalRunHistoryOpen;
  const setRunHistoryOpen = (open: boolean) => {
    setInternalRunHistoryOpen(open);
    onRunHistoryOpenChange?.(open);
  };
  const designMenuRef = useRef<HTMLDivElement>(null);
  const designFileInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!designMenuOpen) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (designMenuRef.current && !designMenuRef.current.contains(event.target as Node)) {
        setDesignMenuOpen(false);
        setExamplesMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (examplesMenuOpen) setExamplesMenuOpen(false);
      else setDesignMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [designMenuOpen, examplesMenuOpen]);
  useEffect(() => {
    if (!runHistoryOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setRunHistoryOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [runHistoryOpen]);
  const closeMenuThen = (action?: () => void) => () => {
    setDesignMenuOpen(false);
    setExamplesMenuOpen(false);
    action?.();
  };
  return (
    <>
    <header className={`topbar public-coilem-topbar${tutorialCatalog ? ' is-tutorial-catalog' : ''}`}>
      <div className="topbar-left">
        <button className="logo public-logo-button" type="button" onClick={onHome} aria-label="Return to coilEM home">
          <img className="logo-mark" src="/brand/coilem-mark.svg" alt="" aria-hidden="true" />
          <span className="logo-word">coil<span className="logo-em">EM</span><sup className="logo-stage">Beta</sup></span>
        </button>
        {tutorialProgress ? (
          <button
            type="button"
            className="tutorial-context-chip"
            onClick={onTutorialCatalog}
            title="Back to all lessons"
          >
            <span>Tutorials</span>
            <strong>{tutorialProgress.eyebrow ?? `Lesson ${tutorialProgress.lessonNumber} of ${tutorialProgress.lessonCount}`}</strong>
            <em>{tutorialProgress.title}</em>
          </button>
        ) : tutorialCatalog ? (
          <button
            type="button"
            className="tutorial-context-chip is-catalog"
            onClick={onHome}
            title="Back to coilEM home"
          >
            <span>‹ Home</span>
            <strong>Tutorials</strong>
            <em>Motor fundamentals</em>
          </button>
        ) : (
        <div className="public-project-chip-wrap" ref={designMenuRef}>
          <button
            className="project-chip"
            type="button"
            onClick={() => setDesignMenuOpen((open) => {
              if (open) setExamplesMenuOpen(false);
              return !open;
            })}
            aria-haspopup="menu"
            aria-expanded={designMenuOpen}
            aria-label="Design file menu"
          >
            <span className="project-save-indicator autosaved" aria-hidden="true" />
            <span className="project-name">{designName ?? `Example ${config.topology} ${config.rotor.pole_count}p/${config.stator.slot_count}s`}</span>
            <span className="caret" aria-hidden="true">▾</span>
          </button>
          {designMenuOpen && (
            <div className="public-project-menu" role="menu" aria-label="Design file actions">
              <button type="button" role="menuitem" disabled={!onNewDesign} onClick={closeMenuThen(onNewDesign)}>
                New Design
              </button>
              <div
                className="public-project-submenu"
                onMouseEnter={() => setExamplesMenuOpen(true)}
                onMouseLeave={() => setExamplesMenuOpen(false)}
              >
                <button
                  className="public-project-submenu-trigger"
                  type="button"
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={examplesMenuOpen}
                  onClick={() => setExamplesMenuOpen((open) => !open)}
                >
                  <span>Examples</span><span aria-hidden="true">›</span>
                </button>
                {examplesMenuOpen && (
                  <div className="public-project-examples-menu" role="menu" aria-label="Example designs">
                    <span className="public-project-example-group-label" role="presentation">Motor examples</span>
                    {PUBLIC_EXAMPLE_OPTIONS.map((example) => (
                      <button
                        type="button"
                        role="menuitem"
                        key={example.id}
                        onClick={closeMenuThen(() => onLoadExample?.(example.id))}
                      >
                        <strong>{example.label}</strong>
                        <small>{example.detail}</small>
                      </button>
                    ))}
                    {onOpenHalbach && (
                      <>
                        <span className="menu-divider" role="presentation" />
                        <span className="public-project-example-group-label" role="presentation">Field examples</span>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={closeMenuThen(onOpenHalbach)}
                        >
                          <strong>Halbach arrays</strong>
                          <small>Cylindrical &amp; linear</small>
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
              <span className="menu-divider" aria-hidden="true" />
              <button type="button" role="menuitem" onClick={closeMenuThen(() => designFileInputRef.current?.click())}>
                Open design file… ({DESIGN_FILE_EXTENSION})
              </button>
              <button type="button" role="menuitem" disabled={!onSaveDesign} onClick={closeMenuThen(onSaveDesign)}>
                Save design file ({DESIGN_FILE_EXTENSION})
              </button>
              <span className="menu-divider" aria-hidden="true" />
              <button type="button" role="menuitem" disabled={!onResetDesign} onClick={closeMenuThen(onResetDesign)}>
                Reset to example design
              </button>
              <button type="button" role="menuitem" onClick={closeMenuThen(onHome)}>
                Back to home
              </button>
              <span className="menu-note">Design files stay on this computer.</span>
            </div>
          )}
          <input
            ref={designFileInputRef}
            type="file"
            accept={DESIGN_FILE_ACCEPT}
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) onOpenDesignFile?.(file);
            }}
          />
        </div>
        )}
      </div>
      <div className="topbar-workflow">
        {tutorialCatalog ? (
          <span className="tutorial-catalog-title">Motor fundamentals</span>
        ) : tutorialProgress ? (
          <LessonProgressStepper progress={tutorialProgress} />
        ) : (
          <WorkflowStepper
            activeStep={activeStep}
            solveAvailable={solveAvailable}
            resultReady={resultReady}
            solveRunning={solveRunning}
            workflowDisabled={workflowDisabled}
            onStepChange={onStepChange}
          />
        )}
      </div>
      <div className="topbar-right">
        {!tutorialCatalog && <button
          type="button"
          className="public-run-history-button"
          aria-label="Previous runs"
          title="Previous runs"
          aria-haspopup="dialog"
          onClick={() => setRunHistoryOpen(true)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4.5 7.5V3.8m0 0H8m-3.5 0 2.7 2.7A8 8 0 1 1 4 12" />
            <path d="M12 7.5V12l3 1.8" />
          </svg>
        </button>}
        <div className="topbar-utility-panel">
          <span className="public-backend-select">Local backend</span>
          <span className={`backend-status ${connectionStatus === 'online' ? 'connected' : connectionStatus === 'checking' ? 'checking' : 'disconnected'}`} role="status">
            <span className="status-dot" aria-hidden="true" />
            <span className="status-text">Local: {connectionStatus === 'online' ? 'ready' : connectionStatus === 'checking' ? 'checking' : 'not running'}</span>
          </span>
        </div>
      </div>
    </header>
    {runHistoryOpen && (
        <div
          className="public-run-history-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setRunHistoryOpen(false);
          }}
        >
          <section className="public-run-history-dialog" role="dialog" aria-modal="true" aria-labelledby="public-run-history-title">
            <header>
              <div><span className="eyebrow">Local results</span><h1 id="public-run-history-title">Previous runs</h1><p>Review or compare completed analyses without starting another solve.</p></div>
              <button type="button" onClick={() => setRunHistoryOpen(false)} aria-label="Close previous runs">×</button>
            </header>
            <div className="public-run-history-content">
              <PublicRunComparison manageRuns />
            </div>
          </section>
        </div>
      )}
    </>
  );
}

interface NumberRowProps {
  label: string;
  value: number;
  unit?: string;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}

function NumberRow({ label, value, unit = '', hint, min, max, step = 1, disabled, onChange }: NumberRowProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [draftValue, setDraftValue] = useState(() => String(value));

  useEffect(() => {
    if (inputRef.current !== document.activeElement) {
      setDraftValue(String(value));
    }
  }, [value]);

  const commitDraft = () => {
    const parsed = Number(draftValue);
    if (!Number.isFinite(parsed)) {
      setDraftValue(String(value));
      return;
    }
    setDraftValue(String(parsed));
    if (!Object.is(parsed, value)) onChange(parsed);
  };

  return (
    <label className="param-row public-param-row" title={hint}>
      <span className="param-label">{label}{unit && <small>{unit}</small>}</span>
      <span className="param-control">
        <input
          ref={inputRef}
          className="param-number-input"
          type="number"
          value={draftValue}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => setDraftValue(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              event.currentTarget.blur();
            } else if (event.key === 'Escape') {
              setDraftValue(String(value));
              event.currentTarget.blur();
            }
          }}
        />
      </span>
    </label>
  );
}

function ToggleRow({ label, checked, hint, disabled, onChange }: {
  label: string;
  checked: boolean;
  hint?: string;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="param-row public-param-row public-toggle-row" title={hint}>
      <span className="param-label">{label}</span>
      <button
        type="button"
        className={`public-param-switch${checked ? ' is-on' : ''}`}
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span className="public-param-switch-track" aria-hidden="true"><i /></span>
        <span>{checked ? 'On' : 'Off'}</span>
      </button>
    </div>
  );
}

function SelectRow({ label, value, choices, disabled, onChange, selectRef }: {
  label: string;
  value: string;
  choices: Array<{ value: string; label: string; disabled?: boolean }>;
  disabled?: boolean;
  selectRef?: Ref<HTMLSelectElement>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="param-row public-param-row">
      <span className="param-label">{label}</span>
      <select ref={selectRef} className="param-select" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {choices.map((choice) => <option value={choice.value} disabled={choice.disabled} key={choice.value}>{choice.label}</option>)}
      </select>
    </label>
  );
}

function componentFacts(
  selection: PublicMotorComponentSelection,
  config: MotorConfig,
  geometry: GeometryPreview | null,
): Array<[string, string]> {
  const airgap = Math.max(0, (config.stator.ID_mm - config.rotor.OD_mm) / 2 - (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0));
  switch (selection.kind) {
    case 'stator': {
      // A tooth is picked as a stator part; the 2D canvas names it in region_type,
      // the 3D viewer only in the label, so check both.
      const isTooth = /tooth/i.test(`${selection.regionType ?? ''} ${selection.label}`);
      const statorWidths = deriveStatorSectionWidths(config, geometry);
      return [
        ['Material', steelDisplayName(config, config.materials.stator_steel)],
        ['Outer diameter', `${config.stator.OD_mm} mm`],
        ['Inner diameter', `${config.stator.ID_mm} mm`],
        ...(isTooth
          ? ([
            ['Bore tooth', `${statorWidths.boreToothWidthMm.toFixed(1)} mm`],
            ['Yoke tooth', `${statorWidths.toothWidthAtYokeMm.toFixed(1)} mm`],
            ['Bore slot opening', `${config.stator.slot_opening_mm} mm`],
            ['Slot at yoke', `${statorWidths.slotWidthAtYokeMm.toFixed(1)} mm`],
            ['Yoke thickness', `${config.stator.yoke_thickness_mm} mm`],
          ] as Array<[string, string]>)
          : []),
        ['Stack length', `${config.stator.stack_length_mm} mm`],
      ];
    }
    case 'rotor':
      return [
        ['Material', config.materials.rotor_steel],
        ['Outer diameter', `${config.rotor.OD_mm} mm`],
        ['Poles', String(config.rotor.pole_count)],
        ['Stack length', `${config.stator.stack_length_mm} mm`],
      ];
    case 'magnet':
      return [
        ['Material', config.materials.magnet_grade],
        ['Thickness', `${config.rotor.magnet_thickness_mm} mm`],
        ['Width', `${config.rotor.magnet_width_mm} mm`],
        ...(config.topology === 'IPM' && config.rotor.ipm_topology === 'flat_buried'
          ? ([['Outer bridge', `${config.rotor.bridge_thickness_mm} mm`]] as Array<[string, string]>)
          : []),
        ['Pole coverage', `${Math.round(config.rotor.magnet_embrace * 100)}%`],
      ];
    case 'winding': {
      const facts: Array<[string, string]> = [
        ['Conductor', config.materials.conductor],
        ['Turns / coil', String(config.winding.turns_per_coil)],
        ['Winding', config.winding.type],
        ['Phase current', `${config.solve_params.current_amplitude_A} A rms`],
      ];
      if (selection.windingModel) facts.push(['3D coil model', selection.windingModel]);
      return facts;
    }
    case 'harness':
      return [
        ['Connection', 'Wye (star)'],
        ['Conductor', config.materials.conductor],
        ['Parallel paths', String(config.winding.parallel_paths)],
        ['Phase current', `${config.solve_params.current_amplitude_A} A rms`],
      ];
    case 'shaft':
      return [
        ['Material', 'Not assigned'],
        ['Diameter', config.rotor.ID_mm ? `${config.rotor.ID_mm} mm` : 'Derived preview'],
        ['Stack reference', `${config.stator.stack_length_mm} mm`],
      ];
    case 'airgap':
      return [
        ['Material', 'Air'],
        ['Radial clearance', `${airgap.toFixed(2)} mm`],
        ['Stator bore', `${config.stator.ID_mm} mm`],
        ['Rotor diameter', `${config.rotor.OD_mm} mm`],
      ];
    // The housing parts are drawn from the solved radii but are not solved
    // themselves — the first fact says so before any dimension is read.
    case 'bearing':
      return [
        ['Model role', 'Illustrative · not part of the EM model'],
        ['Type', 'Deep-groove ball bearing'],
        ['Bore reference', config.rotor.ID_mm ? `${config.rotor.ID_mm} mm shaft` : 'Derived preview shaft'],
        ['Stack reference', `${config.stator.stack_length_mm} mm`],
      ];
    case 'endcap':
      return [
        ['Model role', 'Illustrative · not part of the EM model'],
        ['Type', 'Bolted end housing'],
        ['Outer diameter', `${config.stator.OD_mm} mm`],
        ['Stack reference', `${config.stator.stack_length_mm} mm`],
      ];
  }
}

function ComponentDetailCard({ selection, config, geometry, onClose }: {
  selection: PublicMotorComponentSelection;
  config: MotorConfig;
  geometry: GeometryPreview | null;
  onClose: () => void;
}) {
  return (
    <section className={`public-component-detail-card kind-${selection.kind}`} aria-live="polite">
      <div className="public-component-detail-heading">
        <div>
          <span className="public-section-kicker">Selected component</span>
          <h3>{selection.label}</h3>
        </div>
        <button type="button" onClick={onClose} aria-label="Close component details">×</button>
      </div>
      <p>{selection.role}</p>
      <dl>
        {componentFacts(selection, config, geometry).map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      <span className="public-component-detail-hint">Click another motor part to inspect it.</span>
    </section>
  );
}

function ParameterSectionBlock({
  id,
  label,
  summary,
  active,
  onToggle,
  children,
  nextLabel,
  onNext,
}: {
  id: PublicParameterSection;
  label: string;
  summary: string;
  active: boolean;
  onToggle: (id: PublicParameterSection) => void;
  children: ReactNode;
  nextLabel?: string;
  onNext?: () => void;
}) {
  return (
    <section className="param-group" data-guide={`section-${id}`} data-guide-active={active ? 'true' : 'false'}>
      <button
        type="button"
        className={`param-group-header status-complete${active ? '' : ' collapsed'}`}
        // The chevron is aria-hidden, so without this the header gave no clue
        // that it opens and closes anything.
        aria-expanded={active}
        aria-controls={`param-group-content-${id}`}
        onClick={() => onToggle(id)}
      >
        <StatusGlyph />
        <span className="param-group-titles">
          <span className="param-group-label">{label}</span>
          {!active && <span className="param-group-chip">{summary}</span>}
        </span>
        <span className="chevron" aria-hidden="true">▼</span>
      </button>
      <div id={`param-group-content-${id}`} className={`param-group-content${active ? '' : ' collapsed'}`}>
        {children}
        {nextLabel && onNext && <button className="param-section-advance" type="button" onClick={onNext}>Continue Setup: {nextLabel} →</button>}
      </div>
    </section>
  );
}

function ParameterPanel({ config, materials, geometry, geometryStale, busy, error, notice, blankDesign = false, guidedActive, guidedDesignSection, selectedComponent, onTopologyChange, onSectionChange, onDesignSectionVisit, onConvertProjectSteelToM350, onImportSteel, onReset, onRefreshGeometry, onNext, onClearComponent }: Pick<CoilEmWorkspaceProps,
  'config' | 'materials' | 'geometry' | 'geometryStale' | 'busy' | 'error' | 'notice' | 'blankDesign' | 'onTopologyChange' | 'onSectionChange' | 'onDesignSectionVisit' | 'onConvertProjectSteelToM350' | 'onImportSteel' | 'onReset' | 'onRefreshGeometry'
> & {
  guidedActive?: boolean;
  guidedDesignSection?: PublicParameterSection | null;
  selectedComponent: PublicMotorComponentSelection | null;
  onNext: () => void;
  onClearComponent: () => void;
}) {
  // null = every section collapsed. Clicking the open section's header used to be
  // a no-op: the toggle tested `current === section` and then returned `section`
  // from both branches, so a group could be opened but never closed.
  const [activeSection, setActiveSection] = useState<PublicParameterSection | null>(
    guidedActive ? null : 'stator',
  );
  const [searchQuery, setSearchQuery] = useState('');
  const setNext = (section: PublicParameterSection) => () => {
    onDesignSectionVisit(section);
    setActiveSection(section);
  };
  const toggle = (section: PublicParameterSection) => setActiveSection((current) => {
    const next = current === section ? null : section;
    if (next) onDesignSectionVisit(next);
    return next;
  });
  const disabled = busy !== null;
  const set = (
    section: PublicEditableSection,
    field: string,
    visitedSection?: PublicParameterSection,
  ) => (value: unknown) => onSectionChange(section, field, value, visitedSection);
  // Advisory notes from the backend: drawable and solvable, but one tooth section
  // can become narrower than the other. They travel in metadata rather than
  // validation_errors precisely so they cannot block a solve.
  // Only describe the geometry currently on screen. Editing a field flips
  // geometryStale while the previous payload is still held, and a failed re-preview
  // leaves it held indefinitely — so an unsuppressed note would keep explaining a
  // shape the user has already changed.
  const geometryWarnings = currentGeometryWarnings(geometry, geometryStale);
  const statorWidths = deriveStatorSectionWidths(
    config,
    geometryStale ? null : geometry,
  );
  const minimumBoreSlotOpeningMm = Math.max(
    2,
    config.stator.tooth_shoe_enabled
      ? 2 * (config.stator.tooth_shoe_overhang_mm ?? 0) + 0.1
      : 2,
  );
  const toothShoeAdditionMm = config.stator.tooth_shoe_enabled
    ? 2 * Math.max(0, config.stator.tooth_shoe_overhang_mm ?? 0)
    : 0;
  const toothShoeOverhangMm = Math.max(0, config.stator.tooth_shoe_overhang_mm ?? 1.5);
  const maximumToothShoeOverhangMm = Math.max(
    0,
    Math.min(
      15,
      Math.floor(((config.stator.slot_opening_mm - 0.1) / 2) * 10) / 10,
    ),
  );
  const physicalSlotMouthMm = Math.max(
    0,
    config.stator.slot_opening_mm
      - (config.stator.tooth_shoe_enabled ? 2 * toothShoeOverhangMm : 0),
  );
  const minimumBoreToothWidthMm = Math.max(
    2,
    Math.ceil(
      (statorWidths.borePitchMm - 50 + toothShoeAdditionMm) * 10,
    ) / 10,
  );
  const maximumBoreToothWidthMm = Math.max(
    minimumBoreToothWidthMm,
    Math.floor(
      (
        statorWidths.borePitchMm
        - minimumBoreSlotOpeningMm
        + toothShoeAdditionMm
      ) * 10,
    ) / 10,
  );
  const setBoreToothWidth = (requestedWidthMm: number) => {
    const boundedWidthMm = Math.min(
      maximumBoreToothWidthMm,
      Math.max(minimumBoreToothWidthMm, requestedWidthMm),
    );
    const boreSlotOpeningMm = Math.min(
      50,
      Math.max(
        minimumBoreSlotOpeningMm,
        Math.round(
          (
            statorWidths.borePitchMm
            + toothShoeAdditionMm
            - boundedWidthMm
          ) * 10,
        ) / 10,
      ),
    );
    set('stator', 'slot_opening_mm', 'advanced')(boreSlotOpeningMm);
  };
  const airgap = Math.max(0, (config.stator.ID_mm - config.rotor.OD_mm) / 2 - (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0));
  const coverage = Math.round(config.rotor.magnet_embrace * 100);
  const steelChoices = (current: string) => [
    ...(!materials.steels.includes(current)
      ? [{ value: current, label: 'Choose a supported steel', disabled: true }]
      : []),
    ...materials.steels.map((value) => ({ value, label: `${steelDisplayName(config, value)}${value.startsWith('custom:') ? ` · Custom ${value.slice(7, 13)}` : ''}` })),
  ];
  const unsupportedSteels = Array.from(new Set([
    config.materials.stator_steel,
    config.materials.rotor_steel,
  ].filter((value) => !materials.steels.includes(value))));
  const hasUnsupportedSteel = unsupportedSteels.length > 0;
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const searchTerms: Record<PublicParameterSection | 'topology', string> = {
    topology: 'topology spm ipm surface permanent magnet flat buried v shape',
    stator: 'stator geometry outer diameter inner diameter slot count stack length bore pitch',
    rotor: 'rotor magnets pole count rotor od air gap magnet thickness magnet width burial depth outer bridge bridge thickness magnet position coverage magnet grade',
    advanced: 'advanced geometry bore tooth width tooth width at yoke bore slot opening physical slot mouth slot width at yoke yoke thickness tooth shoe shoulder height overhang rotor layout v angle v depth',
    winding: 'winding type turns coil parallel paths phase current amp rms',
    materials: 'materials stator steel rotor steel magnet grade conductor',
  };
  const matchesSearch = (section: PublicParameterSection | 'topology') => (
    !normalizedSearch || searchTerms[section].includes(normalizedSearch)
  );
  const visibleSections = (['stator', 'rotor', 'advanced', 'winding', 'materials'] as const)
    .filter(matchesSearch);

  useEffect(() => {
    if (!selectedComponent) return;
    const section = selectedComponent.kind === 'stator'
      ? 'stator'
      : selectedComponent.kind === 'winding'
        ? 'winding'
        : 'rotor';
    onDesignSectionVisit(section);
    setActiveSection(section);
  }, [onDesignSectionVisit, selectedComponent]);

  useEffect(() => {
    if (guidedActive) setActiveSection(guidedDesignSection ?? null);
  }, [guidedActive, guidedDesignSection]);

  return (
    <aside className="panel-left public-parameter-panel" data-tour="parameter-panel">
      {/* Title and selected-component card are pinned; everything from the search
          box down through the parameter accordion is one scroll region.
          Previously the accordion and footer were fixed-height siblings that
          claimed most of the panel, leaving the scroller about a third of its
          height — a selected component's card landed in a ~300px window and had
          to be scrolled to be read. Measured at 848px the panel holds 980px of
          content once a card is open, so something has to scroll; the accordion
          is the right thing to give up, not the card or the topology selector.
          With nothing selected the content fits and nothing scrolls at all. */}
      <div className="panel-header">
        <span className="panel-header-title">Design</span>
        <button className="public-panel-reset" type="button" disabled={disabled} onClick={onReset}>Reset</button>
      </div>
      {selectedComponent && (
        <ComponentDetailCard
          selection={selectedComponent}
          config={config}
          geometry={geometry ?? null}
          onClose={onClearComponent}
        />
      )}
      <div className="panel-left-scroll">
        <div className="param-search-section" role="search">
          <label className="param-search-input-wrap">
            <span className="param-search-icon" aria-hidden="true">⌕</span>
            <input
              className="param-search-input"
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search slot, magnet, turns…"
              aria-label="Search design parameters"
            />
          </label>
        </div>
        {matchesSearch('topology') && <div className="param-section param-primary-section" data-guide="topology-selector">
          <div className="param-section-label">Topology</div>
          <div className="topology-cards">
            {(['SPM', 'IPM'] as const).map((topology) => (
              <button
                type="button"
                className={`topo-card${config.topology === topology ? ' active' : ''}`}
                aria-pressed={config.topology === topology}
                disabled={disabled}
                onClick={() => onTopologyChange(topology)}
                key={topology}
              >
                <span className="topo-icon" aria-hidden="true">◉</span>
                <span className="topo-text"><span className="topo-name">{topology}</span><span className="topo-sub">{topology === 'SPM' ? 'Surface PM' : 'Flat / V'}</span></span>
                <span className="topo-badge topo-badge-guided">Guided</span>
              </button>
            ))}
          </div>
          {config.topology === 'IPM' && (
            <div className="ipm-layout-selector" data-guide="ipm-layout-selector">
              <div className="param-section-label">IPM rotor layout</div>
              <div className="ipm-layout-cards" role="group" aria-label="IPM rotor layout">
                {([
                  {
                    value: 'flat_buried',
                    label: 'Flat / buried',
                    description: 'Parallel magnets inside the rotor',
                  },
                  {
                    value: 'v_shape',
                    label: 'V-shape',
                    description: 'Angled magnet pairs for saliency',
                  },
                ] as const).map((layout) => (
                  <button
                    type="button"
                    className={`ipm-layout-card${config.rotor.ipm_topology === layout.value ? ' active' : ''}`}
                    aria-pressed={config.rotor.ipm_topology === layout.value}
                    disabled={disabled}
                    onClick={() => set('rotor', 'ipm_topology')(layout.value)}
                    key={layout.value}
                  >
                    <span>{layout.label}</span>
                    <small>{layout.description}</small>
                  </button>
                ))}
              </div>
              <p className="ipm-layout-note">Fine-tune V-angle and depth later in Advanced Geometry.</p>
            </div>
          )}
        </div>}

      {matchesSearch('stator') && <ParameterSectionBlock id="stator" label="Stator Geometry" active={Boolean(normalizedSearch) || activeSection === 'stator'} onToggle={toggle} summary={`${config.stator.OD_mm} mm OD · ${config.stator.slot_count} slots · ${config.stator.stack_length_mm} mm stack`} nextLabel={normalizedSearch ? undefined : 'Rotor & Magnets'} onNext={normalizedSearch ? undefined : setNext('rotor')}>
        <NumberRow label="Outer Diameter" value={config.stator.OD_mm} unit="mm" min={30} step={1} disabled={disabled} onChange={set('stator', 'OD_mm', 'stator')} />
        <NumberRow label="Inner Diameter" value={config.stator.ID_mm} unit="mm" min={20} step={1} disabled={disabled} onChange={set('stator', 'ID_mm', 'stator')} />
        <NumberRow label="Slot Count" value={config.stator.slot_count} min={6} step={1} disabled={disabled} onChange={set('stator', 'slot_count', 'stator')} />
        <NumberRow label="Stack Length" value={config.stator.stack_length_mm} unit="mm" min={10} step={1} disabled={disabled} onChange={set('stator', 'stack_length_mm', 'stator')} />
        <div className="fable-derived"><span className="fable-derived-fx">ƒ</span><span>slot pitch {(360 / config.stator.slot_count).toFixed(1)}° · bore pitch {(Math.PI * config.stator.ID_mm / config.stator.slot_count).toFixed(1)} mm</span></div>
      </ParameterSectionBlock>}

      {matchesSearch('rotor') && <ParameterSectionBlock id="rotor" label="Rotor & Magnets" active={Boolean(normalizedSearch) || activeSection === 'rotor'} onToggle={toggle} summary={`${config.rotor.pole_count} poles · ${config.rotor.OD_mm} mm rotor · ${config.rotor.magnet_thickness_mm} mm magnet`} nextLabel={normalizedSearch ? undefined : 'Advanced Geometry'} onNext={normalizedSearch ? undefined : setNext('advanced')}>
        <NumberRow label="Pole Count" value={config.rotor.pole_count} min={2} max={32} step={2} disabled={disabled} onChange={set('rotor', 'pole_count', 'rotor')} />
        <NumberRow label="Rotor OD" value={config.rotor.OD_mm} unit="mm" min={15} step={1} disabled={disabled} onChange={set('rotor', 'OD_mm', 'rotor')} />
        <div className="param-row public-param-row public-derived-row"><span className="param-label">Air Gap<small>mm</small></span><strong>{airgap.toFixed(2)}</strong></div>
        <NumberRow label="Magnet Thick." value={config.rotor.magnet_thickness_mm} unit="mm" min={2} step={0.5} disabled={disabled} onChange={set('rotor', 'magnet_thickness_mm', 'rotor')} />
        <NumberRow label="Magnet Width" value={config.rotor.magnet_width_mm} unit="mm" min={1} step={0.1} disabled={disabled} onChange={set('rotor', 'magnet_width_mm', 'rotor')} />
        {config.topology === 'IPM' && config.rotor.ipm_topology === 'flat_buried' && (
          <NumberRow
            label="Outer Bridge"
            value={config.rotor.bridge_thickness_mm}
            unit="mm"
            hint="Minimum radial steel between the rotor outer surface and the nearest magnet-pocket corner."
            min={0}
            max={20}
            step={0.1}
            disabled={disabled}
            onChange={set('rotor', 'bridge_thickness_mm', 'rotor')}
          />
        )}
        <div className="param-row public-param-row public-derived-row"><span className="param-label">Coverage<small>%</small></span><strong>{coverage}</strong></div>
        <SelectRow label="Magnet Grade" value={config.materials.magnet_grade} choices={materials.magnet_grades.map((value) => ({ value, label: value }))} disabled={disabled} onChange={set('materials', 'magnet_grade', 'rotor')} />
      </ParameterSectionBlock>}

      {matchesSearch('advanced') && <ParameterSectionBlock id="advanced" label="Advanced Geometry" active={Boolean(normalizedSearch) || activeSection === 'advanced'} onToggle={toggle} summary={`bore tooth ${statorWidths.boreToothWidthMm.toFixed(1)} · yoke tooth ${config.stator.tooth_width_mm} · yoke ${config.stator.yoke_thickness_mm}`} nextLabel={normalizedSearch ? undefined : 'Winding'} onNext={normalizedSearch ? undefined : setNext('winding')}>
        <NumberRow label="Bore Tooth Width" value={Number(statorWidths.boreToothWidthMm.toFixed(1))} unit="mm" hint="Tangential tooth width at the stator bore. Bore slot opening is calculated from the remaining pitch." min={minimumBoreToothWidthMm} max={maximumBoreToothWidthMm} step={0.1} disabled={disabled} onChange={setBoreToothWidth} />
        <NumberRow label="Yoke Tooth Width" value={config.stator.tooth_width_mm} unit="mm" hint="Tangential tooth-body width where the slot terminates beside the yoke." min={2} step={0.1} disabled={disabled} onChange={set('stator', 'tooth_width_mm', 'advanced')} />
        <NumberRow label="Yoke Thick." value={config.stator.yoke_thickness_mm} unit="mm" min={1} step={0.1} disabled={disabled} onChange={set('stator', 'yoke_thickness_mm', 'advanced')} />
        <ToggleRow
          label="Tooth Shoe"
          checked={Boolean(config.stator.tooth_shoe_enabled)}
          hint="Adds a widened tooth tip at the bore, leaving a narrower physical slot mouth ahead of the winding pocket."
          disabled={disabled}
          onChange={set('stator', 'tooth_shoe_enabled', 'advanced')}
        />
        {config.stator.tooth_shoe_enabled && <>
          <NumberRow
            label="Shoe Height"
            value={config.stator.tooth_shoe_height_mm ?? 1.5}
            unit="mm"
            hint="Radial distance from the bore to the tooth-body shoulder."
            min={0.5}
            max={10}
            step={0.1}
            disabled={disabled}
            onChange={(value) => set('stator', 'tooth_shoe_height_mm', 'advanced')(Math.min(10, Math.max(0.5, value)))}
          />
          <NumberRow
            label="Shoe Overhang"
            value={toothShoeOverhangMm}
            unit="mm / side"
            hint="Tangential extension on each side of the tooth body. Two overhangs are subtracted from the body opening to give the physical slot mouth."
            min={0}
            max={maximumToothShoeOverhangMm}
            step={0.1}
            disabled={disabled}
            onChange={(value) => set('stator', 'tooth_shoe_overhang_mm', 'advanced')(
              Math.min(maximumToothShoeOverhangMm, Math.max(0, value)),
            )}
          />
        </>}
        <div className="public-stator-derived-measures" aria-label="Calculated stator slot widths">
          <div className="param-row public-param-row public-derived-row" title="Remaining open mouth after subtracting the tooth-shoe overhang on both sides.">
            <span className="param-label">Physical Slot Mouth<small>mm · calc</small></span>
            <strong>{physicalSlotMouthMm.toFixed(1)}</strong>
          </div>
          <div className="param-row public-param-row public-derived-row" title="Slot opening at the underlying tooth body before the optional shoe overhang.">
            <span className="param-label">Tooth Body Opening<small>mm · calc</small></span>
            <strong>{config.stator.slot_opening_mm.toFixed(1)}</strong>
          </div>
          <div className="param-row public-param-row public-derived-row" title="Yoke-side pitch minus the tooth width at the yoke.">
            <span className="param-label">Slot Width at Yoke<small>mm · calc</small></span>
            <strong>{statorWidths.slotWidthAtYokeMm.toFixed(1)}</strong>
          </div>
        </div>
        {config.topology === 'IPM' && config.rotor.ipm_topology === 'v_shape' && <>
          <NumberRow label="V Angle" value={config.rotor.v_angle_deg} unit="deg" min={0} max={120} step={1} disabled={disabled} onChange={set('rotor', 'v_angle_deg', 'advanced')} />
          <NumberRow label="V Depth" value={config.rotor.v_depth_mm} unit="mm" min={0} step={0.1} disabled={disabled} onChange={set('rotor', 'v_depth_mm', 'advanced')} />
        </>}
      </ParameterSectionBlock>}

      {matchesSearch('winding') && <ParameterSectionBlock id="winding" label="Winding" active={Boolean(normalizedSearch) || activeSection === 'winding'} onToggle={toggle} summary={`${config.winding.type} · ${config.winding.turns_per_coil} turns × ${config.winding.parallel_paths}p`} nextLabel={normalizedSearch ? undefined : 'Materials'} onNext={normalizedSearch ? undefined : setNext('materials')}>
        <SelectRow label="Type" value={config.winding.type} choices={[{ value: 'concentrated', label: 'Concentrated' }, { value: 'distributed', label: 'Distributed' }]} disabled={disabled} onChange={set('winding', 'type', 'winding')} />
        <NumberRow label="Turns / Coil" value={config.winding.turns_per_coil} min={1} step={1} disabled={disabled} onChange={set('winding', 'turns_per_coil', 'winding')} />
        <NumberRow label="Parallel Paths" value={config.winding.parallel_paths} min={1} step={1} disabled={disabled} onChange={set('winding', 'parallel_paths', 'winding')} />
        <NumberRow label="Phase Current" value={config.solve_params.current_amplitude_A} unit="A rms" min={0} step={0.5} disabled={disabled} onChange={set('solve_params', 'current_amplitude_A', 'winding')} />
      </ParameterSectionBlock>}

      {matchesSearch('materials') && <ParameterSectionBlock id="materials" label="Materials" active={Boolean(normalizedSearch) || activeSection === 'materials'} onToggle={toggle} summary={`${steelDisplayName(config, config.materials.stator_steel)} stator · ${steelDisplayName(config, config.materials.rotor_steel)} rotor`}>
        <SelectRow label="Stator Steel" value={config.materials.stator_steel} choices={steelChoices(config.materials.stator_steel)} disabled={disabled} onChange={set('materials', 'stator_steel', 'materials')} />
        <SelectRow label="Rotor Steel" value={config.materials.rotor_steel} choices={steelChoices(config.materials.rotor_steel)} disabled={disabled} onChange={set('materials', 'rotor_steel', 'materials')} />
        {hasUnsupportedSteel && (
          <div className="public-material-compat-warning" role="alert">
            <strong>This project uses an unavailable steel</strong>
            <span>Select M350-50A or import the curve for your steel. Converting changes the material model and predicted results; it does not rewrite the original file.</span>
            <button type="button" disabled={disabled} onClick={onConvertProjectSteelToM350}>Convert project to M350-50A</button>
          </div>
        )}
        <CustomSteelImport disabled={disabled} onImport={onImportSteel} />
        <p className="public-fixed-output-note">
          M350-50A is an open reference model. Import measured supplier data to model your own steel.{' '}
          <a className="public-material-source-link" href="https://github.com/coilemdev/coilem/blob/main/MATERIALS.md#electrical-steel" target="_blank" rel="noreferrer">
            Review source and limitations
          </a>.
        </p>
      </ParameterSectionBlock>}

      {normalizedSearch && visibleSections.length === 0 && !matchesSearch('topology') && (
        <div className="public-search-empty" role="status">No design parameters match “{searchQuery}”.</div>
      )}
      </div>

      <div className="panel-footer-cta" data-guide="design-continue">
        {notice && <div className="public-design-notice" role="status">{notice}</div>}
        {/* Names which part is wrong. "Fix validation errors" left the reader to
            work out whether it was the geometry or the winding, and a winding fault
            used to leave this reading "Geometry valid — ready to solve" outright,
            because nothing validated parallel paths on a concentrated layout. */}
        {error && (
          <div className="validation-ok has-error">
            <StatusGlyph tone="warning" />
            {/material|steel|M350-50A/i.test(error)
              ? 'Material not supported'
              : /winding|parallel_path|turns|coil|phase/i.test(error)
                ? 'Winding needs attention'
                : 'Geometry needs attention'}
          </div>
        )}
        <button type="button" className={`panel-next-btn ${error || blankDesign ? 'is-blocked' : 'is-ready'}`} disabled={Boolean(error) || blankDesign || disabled} onClick={onNext}>Continue to Solve</button>
        {blankDesign && <div className="panel-next-feedback">Change a design parameter to enable Solve.</div>}
        {error && <div className="panel-next-feedback is-error">{error}</div>}
        {error && geometryStale && !blankDesign && <button type="button" className="public-back-link" disabled={busy !== null} onClick={onRefreshGeometry}>Retry geometry preview</button>}
        {/* Geometry that draws and solves, but whose bore or tooth-shoe shoulder is
            narrower than the yoke-side tooth. Advisory on purpose: the FEM mesh is
            still complete and the condition never blocks the solve. */}
        {geometryWarnings.map((warning) => (
          <div key={warning} className="panel-next-feedback is-warning">{warning}</div>
        ))}
      </div>
    </aside>
  );
}

/**
 * The Dims layer's numbers, read from the same annotation list the canvas draws
 * from so a value and its line cannot disagree.
 *
 * An overlay rather than canvas paint: the motor is fitted to the viewport and
 * leaves only the corners free, and a corner is not tall enough for this many rows
 * before it runs into the stator circle. Each row's swatch repeats its line's dash
 * rhythm, and selecting either the row or the line highlights both.
 */
function DimensionReadout({ annotations, activeDimension, onSelect, onHover }: {
  annotations: DimensionAnnotation[];
  activeDimension: DimensionId | null;
  onSelect: (dimension: DimensionId | null) => void;
  onHover: (dimension: DimensionId | null) => void;
}) {
  return (
    <div className="public-dimension-readout" aria-label="Main component dimensions">
      {annotations.map((annotation) => {
        const isActive = annotation.id === activeDimension;
        const hasLine = annotation.shapes.length > 0;
        return (
          <button
            type="button"
            key={annotation.id}
            className={`dim-row${isActive ? ' is-active' : ''}${hasLine ? '' : ' is-lineless'}`}
            aria-pressed={isActive}
            title={hasLine
              ? (annotation.note
                ? `${annotation.label}, ${annotation.note} — click to highlight it`
                : 'Click to highlight this dimension on the motor')
              : `${annotation.label} is ${annotation.note ?? 'not shown in cross-section'}`}
            onClick={() => onSelect(isActive ? null : annotation.id)}
            onPointerEnter={() => onHover(hasLine ? annotation.id : null)}
            onPointerLeave={() => onHover(null)}
            onFocus={() => onHover(hasLine ? annotation.id : null)}
            onBlur={() => onHover(null)}
          >
            <span className="dim-swatch" aria-hidden="true" style={hasLine ? undefined : { borderTopColor: 'transparent' }} />
            <span className="dim-label">{annotation.label}</span>
            <span className="dim-value">{annotation.value}</span>
          </button>
        );
      })}
    </div>
  );
}

type PublicViewportMode = '2d' | '3d' | 'materials' | 'layout';
/**
 * The one-off 3D-to-cross-section reveal when a design first opens. Down from
 * 5.2 s: past a couple of seconds it stops reading as an establishing shot and
 * starts reading as the app being slow to load, since the panels are already
 * interactive behind it.
 */
const DESIGN_INTRO_DURATION_MS = 2_000;
const DESIGN_INTRO_CROSSFADE_START = 0.68;

function ViewportExpandButton({
  expanded,
  inline = false,
  onToggle,
}: {
  expanded: boolean;
  inline?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={`public-viewport-expand${inline ? ' is-inline' : ''}`}
      aria-label={expanded ? 'Restore side panels' : 'Expand motor view'}
      aria-pressed={expanded}
      aria-keyshortcuts={expanded ? 'Escape' : undefined}
      title={expanded ? 'Restore the side panels (Esc)' : 'Hide the side panels and expand the motor view'}
      onClick={onToggle}
    >
      <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        {expanded ? (
          <path d="M8 3v5H3m9 9v-5h5m0-4h-5V3M3 12h5v5" />
        ) : (
          <path d="M3 7V3h4m6 0h4v4m0 6v4h-4m-6 0H3v-4" />
        )}
      </svg>
    </button>
  );
}

function ViewportChrome({
  config,
  materials,
  geometry,
  mesh,
  mode,
  stale,
  busy,
  showConfigurationLabel = true,
  enableDesignIntro = true,
  isExpanded = false,
  onExpandToggle,
  selectedComponent = null,
  highlightComponentKind = null,
  onComponentSelect,
  meshDisplayMode = 'geometry',
  showMeshEdges = true,
  meshQualitySummary,
  focusedMeshElementIndex = null,
  onMeshDisplayModeChange,
  onShowMeshEdgesChange,
  onFocusedMeshElementChange,
}: Pick<CoilEmWorkspaceProps, 'config' | 'materials' | 'geometry' | 'mesh' | 'geometryStale' | 'busy' | 'meshElements' | 'meshQuality'> & {
  mode: 'geometry' | 'mesh';
  stale: boolean;
  showConfigurationLabel?: boolean;
  enableDesignIntro?: boolean;
  isExpanded?: boolean;
  onExpandToggle?: () => void;
  selectedComponent?: PublicMotorComponentSelection | null;
  highlightComponentKind?: PublicMotorComponentKind | null;
  onComponentSelect?: (component: PublicMotorComponentSelection | null) => void;
  meshDisplayMode?: PublicMeshDisplayMode;
  showMeshEdges?: boolean;
  meshQualitySummary?: PublicMeshQualitySummary;
  focusedMeshElementIndex?: number | null;
  onMeshDisplayModeChange?: (mode: PublicMeshDisplayMode) => void;
  onShowMeshEdgesChange?: (show: boolean) => void;
  onFocusedMeshElementChange?: (elementIndex: number | null) => void;
}) {
  const designIntroEnabled = enableDesignIntro && mode === 'geometry';
  const [viewportMode, setViewportMode] = useState<PublicViewportMode>(() => (
    designIntroEnabled ? '3d' : '2d'
  ));
  const [introProgress, setIntroProgress] = useState(() => (designIntroEnabled ? 0 : 1));
  const [canvasLayer, setCanvasLayer] = useState<PublicCanvasLayer>('none');
  const [materialSubview, setMaterialSubview] = useState<PublicMaterialSubview>('assignment');
  const [materialTarget, setMaterialTarget] = useState<PublicMaterialTarget>('stator');
  const [previewMaterialTarget, setPreviewMaterialTarget] = useState<PublicMaterialTarget | null>(null);
  const [magnetPolarityView, setMagnetPolarityView] = useState<PublicMagnetPolarityView>('dominant');
  const [activeDimension, setActiveDimension] = useState<DimensionId | null>(null);
  const [hoveredDimension, setHoveredDimension] = useState<DimensionId | null>(null);
  const [isAnimating, setIsAnimating] = useState(false);
  const [animationRpm, setAnimationRpm] = useState(18);
  const [rotorAngleDeg, setRotorAngleDeg] = useState(0);
  const [explodedAmount, setExplodedAmount] = useState(0);
  const [threeResetSignal, setThreeResetSignal] = useState(0);
  const [hoveredMeshElement, setHoveredMeshElement] = useState<PublicMeshElementSelection | null>(null);
  const [showMeshNavigationHint, setShowMeshNavigationHint] = useState(false);
  const animationFrameRef = useRef(0);
  const introAnimationFrameRef = useRef(0);
  const introCompleteRef = useRef(!designIntroEnabled);
  const previousFrameRef = useRef<number | null>(null);

  const finishDesignIntro = useCallback((finalMode: PublicViewportMode) => {
    introCompleteRef.current = true;
    window.cancelAnimationFrame(introAnimationFrameRef.current);
    setIntroProgress(1);
    setViewportMode(finalMode);
  }, []);

  /**
   * Only the 2D canvas draws mesh elements; the 3D viewer always shows the solid
   * model. The mount-time state above already starts the mesh view in 2D, but
   * switching to the Mesh tab later only changes `mode` — so the mesh landed
   * behind an unchanged 3D model, complete with a triangle count in the status
   * bar, which read as "the mesh built and looks like the motor".
   */
  useEffect(() => {
    if (mode !== 'mesh') return;
    setViewportMode((current) => (current === '3d' ? '2d' : current));
  }, [mode]);

  useEffect(() => {
    if (mode !== 'mesh') {
      setShowMeshNavigationHint(false);
      return undefined;
    }
    setShowMeshNavigationHint(true);
    const timer = window.setTimeout(() => setShowMeshNavigationHint(false), 4_200);
    return () => window.clearTimeout(timer);
  }, [mode]);

  useEffect(() => {
    if (!designIntroEnabled || introCompleteRef.current) return undefined;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      finishDesignIntro('2d');
      return undefined;
    }

    let startedAt: number | null = null;
    const animateIntro = (timestamp: number) => {
      startedAt ??= timestamp;
      const progress = Math.min(1, (timestamp - startedAt) / DESIGN_INTRO_DURATION_MS);
      setIntroProgress(progress);
      if (progress >= 1) {
        introCompleteRef.current = true;
        setViewportMode('2d');
        return;
      }
      introAnimationFrameRef.current = window.requestAnimationFrame(animateIntro);
    };
    introAnimationFrameRef.current = window.requestAnimationFrame(animateIntro);
    return () => window.cancelAnimationFrame(introAnimationFrameRef.current);
  }, [designIntroEnabled, finishDesignIntro]);

  useEffect(() => {
    if (!isAnimating) {
      previousFrameRef.current = null;
      return undefined;
    }
    const animate = (timestamp: number) => {
      const previous = previousFrameRef.current ?? timestamp;
      previousFrameRef.current = timestamp;
      const elapsedSeconds = Math.min((timestamp - previous) / 1_000, 0.1);
      setRotorAngleDeg((angle) => (angle + animationRpm * 6 * elapsedSeconds) % 360);
      animationFrameRef.current = window.requestAnimationFrame(animate);
    };
    animationFrameRef.current = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrameRef.current);
  }, [animationRpm, isAnimating]);

  const selectViewportMode = (nextMode: PublicViewportMode) => {
    finishDesignIntro(nextMode);
    if (nextMode === 'materials') setCanvasLayer('materials');
    if (nextMode === 'layout') setCanvasLayer('windings');
    if (nextMode === 'materials' || nextMode === 'layout') setIsAnimating(false);
    if (nextMode === '2d' && (canvasLayer === 'materials' || canvasLayer === 'windings')) {
      setCanvasLayer('none');
    }
  };
  const introActive = designIntroEnabled && introProgress < 1;
  const introCrossfade = Math.max(
    0,
    Math.min(
      1,
      (introProgress - DESIGN_INTRO_CROSSFADE_START)
        / (1 - DESIGN_INTRO_CROSSFADE_START),
    ),
  );
  const introCameraProgress = Math.min(
    1,
    introProgress / DESIGN_INTRO_CROSSFADE_START,
  );

  const displayLayer: PublicCanvasLayer = viewportMode === 'materials'
    ? 'materials'
    : viewportMode === 'layout'
      ? 'windings'
      : canvasLayer;
  const showDimensionReadout = viewportMode === '2d' && displayLayer === 'dimensions';
  // Layout is no longer a recolour of the cross-section: it unrolls the winding,
  // which is the only place slot order, coil spans and parallel paths are legible.
  const showWindingLayout = viewportMode === 'layout' && mode === 'geometry';
  const showPlayback = mode === 'geometry'
    && (viewportMode === '2d' || viewportMode === '3d');
  const showMaterialAssignment = viewportMode === 'materials'
    && materialSubview === 'assignment'
    && mode === 'geometry';
  const showMaterialBehavior = viewportMode === 'materials'
    && materialSubview === 'behavior'
    && mode === 'geometry';
  const materialHighlightKind = materialTargetKind(previewMaterialTarget ?? materialTarget);
  const effectiveHighlightKind = showMaterialAssignment
    ? materialHighlightKind
    : highlightComponentKind;
  const dimensionAnnotations = useMemo(
    () => (showDimensionReadout ? buildDimensionAnnotations(config, geometry ?? null) : []),
    [showDimensionReadout, config, geometry],
  );
  const focusedMeshElement = useMemo<PublicMeshElementSelection | null>(() => {
    if (
      mode !== 'mesh'
      || !mesh
      || !meshQualitySummary
      || focusedMeshElementIndex === null
      || focusedMeshElementIndex < 0
      || focusedMeshElementIndex >= mesh.triangles.length
    ) return null;
    const quality = meshQualitySummary.qualities[focusedMeshElementIndex] ?? 0;
    return {
      index: focusedMeshElementIndex,
      quality,
      band: publicMeshQualityBand(quality, meshQualitySummary.threshold),
      region: mesh.regions[focusedMeshElementIndex] || 'mesh',
    };
  }, [focusedMeshElementIndex, mesh, meshQualitySummary, mode]);
  const activeMeshElement = hoveredMeshElement ?? focusedMeshElement;

  return (
    <section className={`viewport viewport-cad viewport-cad-grid public-motor-viewport${onExpandToggle ? ' is-expandable' : ''}${viewportMode === 'materials' ? ' is-materials-view' : ''}${showMaterialAssignment ? ' is-material-assignment' : ''}${showMaterialBehavior ? ' is-material-behavior' : ''}`}>
      {showConfigurationLabel && (
        <div className="viewport-label viewport-label-cad">{config.topology} {config.rotor.pole_count}p/{config.stator.slot_count}s</div>
      )}
      {onExpandToggle && <ViewportExpandButton expanded={isExpanded} onToggle={onExpandToggle} />}
      {showDimensionReadout && (
        <DimensionReadout
          annotations={dimensionAnnotations}
          activeDimension={activeDimension}
          onSelect={setActiveDimension}
          onHover={setHoveredDimension}
        />
      )}
      {(viewportMode === '3d' || introActive) && (
        <div
          className="public-viewport-stage public-viewport-stage-3d"
          style={{
            opacity: introActive ? 1 - introCrossfade : 1,
            pointerEvents: introActive && introCrossfade > 0.5 ? 'none' : 'auto',
          }}
        >
          <PublicMotor3D
            config={config}
            resetSignal={threeResetSignal}
            rotorAngleDeg={rotorAngleDeg}
            explodedAmount={explodedAmount}
            introProgress={introActive ? introCameraProgress : null}
            onInteraction={() => finishDesignIntro('3d')}
            onComponentSelect={onComponentSelect}
          />
        </div>
      )}
      {(viewportMode !== '3d' || introActive) && (
        <div
          className="public-viewport-stage public-viewport-stage-2d"
          style={{
            opacity: introActive ? introCrossfade : 1,
            pointerEvents: introActive && introCrossfade <= 0.5 ? 'none' : 'auto',
          }}
        >
          {showMaterialBehavior ? (
            <MaterialBehaviorView
              config={config}
              catalog={materials}
              activeTarget={materialTarget}
              onTargetChange={setMaterialTarget}
            />
          ) : showWindingLayout ? (
            <WindingLayoutView config={config} geometry={geometry ?? null} />
          ) : (
            <MotorCanvas
              geometry={geometry}
              mesh={mesh}
              mode={mode}
              layer={displayLayer}
              rotorAngleDeg={rotorAngleDeg}
              windingType={config.winding.type}
              selectedComponent={selectedComponent}
              highlightComponentKind={effectiveHighlightKind}
              onComponentSelect={mode === 'geometry' ? onComponentSelect : undefined}
              config={config}
              activeDimension={showDimensionReadout ? activeDimension : null}
              hoveredDimension={showDimensionReadout ? hoveredDimension : null}
              onDimensionSelect={showDimensionReadout ? setActiveDimension : undefined}
              magnetPolarityView={magnetPolarityView}
              meshDisplayMode={meshDisplayMode}
              showMeshEdges={showMeshEdges}
              meshQualities={meshQualitySummary?.qualities}
              meshQualityThreshold={meshQualitySummary?.threshold}
              focusedMeshElementIndex={focusedMeshElementIndex}
              onMeshElementHover={mode === 'mesh' ? setHoveredMeshElement : undefined}
              onMeshElementSelect={mode === 'mesh'
                ? (element) => onFocusedMeshElementChange?.(
                  element?.index === focusedMeshElementIndex ? null : element?.index ?? null,
                )
                : undefined}
            />
          )}
        </div>
      )}
      {showMaterialAssignment && (
        <MaterialAssignmentStrip
          config={config}
          activeTarget={materialTarget}
          previewTarget={previewMaterialTarget}
          onTargetChange={setMaterialTarget}
          onPreviewTargetChange={setPreviewMaterialTarget}
        />
      )}
      {introActive && (
        <div className="public-design-intro-status" aria-live="polite">
          <span style={{ transform: `scaleX(${Math.max(0.04, introProgress)})` }} />
          <strong>{introCrossfade > 0 ? 'Cross-section' : '3D assembly'}</strong>
          <em>{introCrossfade > 0 ? 'Opening the engineering view' : 'Turning to the front plane'}</em>
        </div>
      )}
      {!geometry && mode === 'geometry' && viewportMode !== '3d' && <div className="public-viewport-message">Start the local backend to load geometry.</div>}
      {!mesh && mode === 'mesh' && viewportMode === '2d' && <div className="public-viewport-message">Generate the mesh to inspect its elements.</div>}
      {mode === 'geometry' && stale && viewportMode !== '3d' && <div className="viewport-preview-note">Updating preview…</div>}
      {busy === 'mesh' && <div className="public-canvas-progress"><span>Building native Gmsh mesh…</span><i /></div>}
      {/* The floating layout card is gone: WindingLayoutView states the same slots,
          poles, type, turns and paths in its own header, and the card sat on top of
          the chips row. Its phase legend moved into that header instead. */}
      {selectedComponent && viewportMode !== 'materials' && (
        <div className="public-component-canvas-label" aria-live="polite">
          <i aria-hidden="true" />
          <strong>{selectedComponent.label}</strong>
          <span>
            {selectedComponent.kind === 'stator'
              ? steelDisplayName(config, config.materials.stator_steel)
              : selectedComponent.kind === 'rotor'
                ? steelDisplayName(config, config.materials.rotor_steel)
                : selectedComponent.kind === 'magnet'
                  ? config.materials.magnet_grade
                  : selectedComponent.kind === 'winding' || selectedComponent.kind === 'harness'
                    ? config.materials.conductor
                    : selectedComponent.kind === 'airgap'
                      ? 'Air'
                      : selectedComponent.role}
          </span>
        </div>
      )}
      {mode === 'mesh' && showMeshNavigationHint && (
        <div className="public-mesh-navigation-hint" role="status">
          <span>Scroll to zoom · drag once zoomed</span>
          <button type="button" aria-label="Dismiss mesh navigation hint" onClick={() => setShowMeshNavigationHint(false)}>×</button>
        </div>
      )}
      {mode === 'mesh' && meshQualitySummary && meshDisplayMode !== 'geometry' && (
        <div className="public-mesh-quality-legend" aria-label="Mesh element quality legend">
          <div className="public-quality-legend-heading">
            <strong>Element quality</strong>
            <span className="public-quality-help">
              <button
                type="button"
                aria-label="What does element quality mean?"
                aria-describedby="public-mesh-quality-tooltip"
              >
                ?
              </button>
              <span className="public-quality-tooltip" id="public-mesh-quality-tooltip" role="tooltip">
                <strong>Triangle shape, not accuracy</strong>
                <span
                  className="public-quality-shape-scale"
                  role="img"
                  aria-label="Element quality ranges from 1 for an ideal equilateral triangle to 0 for a collapsed triangle whose points form a straight line."
                >
                  <span className="public-quality-shape-sample is-ideal">
                    <svg viewBox="0 0 56 42" aria-hidden="true">
                      <polygon points="28,4 51,38 5,38" />
                      <circle cx="28" cy="4" r="2.5" />
                      <circle cx="51" cy="38" r="2.5" />
                      <circle cx="5" cy="38" r="2.5" />
                    </svg>
                    <span><b>1</b> · ideal</span>
                  </span>
                  <span className="public-quality-shape-arrow" aria-hidden="true">→</span>
                  <span className="public-quality-shape-sample is-collapsed">
                    <svg viewBox="0 0 56 42" aria-hidden="true">
                      <line x1="5" y1="22" x2="51" y2="22" />
                      <circle cx="5" cy="22" r="2.5" />
                      <circle cx="28" cy="22" r="2.5" />
                      <circle cx="51" cy="22" r="2.5" />
                    </svg>
                    <span><b>0</b> · collapsed</span>
                  </span>
                </span>
                <span>The minimum is the worst element. The mesh passes when every element stays above the solver requirement.</span>
                <em>Marginal elements can solve, but inspect them. Result accuracy also depends on element size, local refinement, and mesh convergence.</em>
              </span>
            </span>
          </div>
          <span><i className="good" />Good <em>≥ 0.30</em></span>
          <span><i className="acceptable" />Acceptable <em>0.10–0.30</em></span>
          <span><i className="marginal" />Marginal <em>{meshQualitySummary.threshold.toFixed(3)}–0.10</em></span>
          <span><i className="failing" />Failing <em>&lt; {meshQualitySummary.threshold.toFixed(3)}</em></span>
        </div>
      )}
      {mode === 'mesh' && activeMeshElement && meshDisplayMode !== 'geometry' && (
        <div className={`public-mesh-element-card ${activeMeshElement.band}`} aria-live="polite">
          <span>{activeMeshElement.band} element</span>
          <strong>#{activeMeshElement.index + 1} · {activeMeshElement.quality.toFixed(3)}</strong>
          <small>{activeMeshElement.region.replace(/[_-]+/g, ' ')}</small>
        </div>
      )}
      <div className="viewport-bottom-bar">
        <div className="viewport-controls viewport-controls-cad" aria-label="Motor view and overlay controls">
          {mode === 'mesh' && (
            <span className="vc-group public-mesh-inspection-controls" role="group" aria-label="Mesh inspection controls">
              <button
                type="button"
                className={meshDisplayMode === 'geometry' ? 'is-active' : ''}
                aria-pressed={meshDisplayMode === 'geometry'}
                onClick={() => onMeshDisplayModeChange?.('geometry')}
              >
                Geometry overlay
              </button>
              <button
                type="button"
                className={showMeshEdges ? 'is-active' : ''}
                aria-pressed={showMeshEdges}
                onClick={() => onShowMeshEdgesChange?.(!showMeshEdges)}
              >
                Element edges
              </button>
              <button
                type="button"
                className={meshDisplayMode === 'quality' ? 'is-active' : ''}
                aria-pressed={meshDisplayMode === 'quality'}
                onClick={() => onMeshDisplayModeChange?.(meshDisplayMode === 'quality' ? 'geometry' : 'quality')}
              >
                Quality heatmap
              </button>
              <button
                type="button"
                className={meshDisplayMode === 'problems' ? 'is-active' : ''}
                aria-pressed={meshDisplayMode === 'problems'}
                disabled={!meshQualitySummary?.weakElementIndices.length}
                onClick={() => {
                  const nextMode = meshDisplayMode === 'problems' ? 'geometry' : 'problems';
                  onMeshDisplayModeChange?.(nextMode);
                  if (nextMode === 'problems') {
                    onFocusedMeshElementChange?.(meshQualitySummary?.weakElementIndices[0] ?? null);
                  }
                }}
              >
                Weak elements{meshQualitySummary ? ` ${meshQualitySummary.weakElementIndices.length}` : ''}
              </button>
            </span>
          )}
          {mode === 'geometry' && <span className="vc-group public-primary-view-modes" role="group" aria-label="Motor view mode">
            {(['2d', '3d', 'materials', 'layout'] as const).map((viewMode) => {
              return (
                <button
                  type="button"
                  className={viewportMode === viewMode ? 'is-active' : ''}
                  aria-label={`Show ${viewMode === '2d' ? '2D motor' : viewMode === '3d' ? '3D motor' : viewMode} view`}
                  aria-pressed={viewportMode === viewMode}
                  onClick={() => selectViewportMode(viewMode)}
                  key={viewMode}
                >
                  {viewMode === '2d' ? '2D' : viewMode === '3d' ? '3D' : viewMode === 'materials' ? 'Materials' : 'Layout'}
                </button>
              );
            })}
          </span>}
          {viewportMode === 'materials' && mode === 'geometry' && (
            <span className="vc-group public-material-subview-controls" role="group" aria-label="Materials view mode">
              {([
                ['assignment', 'Assignment'],
                ['behavior', 'Behavior'],
              ] as Array<[PublicMaterialSubview, string]>).map(([value, label]) => (
                <button
                  type="button"
                  className={materialSubview === value ? 'is-active' : ''}
                  aria-pressed={materialSubview === value}
                  onClick={() => setMaterialSubview(value)}
                  key={value}
                >
                  {label}
                </button>
              ))}
            </span>
          )}
          {viewportMode === '2d' && mode === 'geometry' && (
            <span className="vc-group public-view-modes" role="group" aria-label="2D display layers">
              {([
                ['dimensions', 'Dims'],
                ['slots', 'Slots'],
                ['windings', 'Winding'],
                ['phases', 'Phases'],
              ] as Array<[PublicCanvasLayer, string]>).map(([layer, label]) => (
                <button
                  type="button"
                  className={canvasLayer === layer ? 'is-active' : ''}
                  aria-pressed={canvasLayer === layer}
                  title={canvasLayer === layer ? `Hide the ${label.toLowerCase()} overlay` : `Show ${label.toLowerCase()}`}
                  // Clicking the active layer turns it off, which is the only way to
                  // get the bare cross-section: these read as toggles, and Dims in
                  // particular puts a legend and dashed lines over the motor.
                  onClick={() => setCanvasLayer((current) => (current === layer ? 'none' : layer))}
                  key={layer}
                >
                  {label}
                </button>
              ))}
            </span>
          )}
          {viewportMode === '2d'
            && mode === 'geometry'
            && (config.topology === 'SPM'
              || (config.topology === 'IPM' && config.rotor.ipm_topology === 'v_shape')) && (
            <span className="vc-group public-polarity-view" role="group" aria-label="Magnet polarity display">
              {([
                ['dominant', 'Pole', 'Dominant pole', 'Color each magnet by the pole facing the airgap.'],
                ['split', 'Split', 'Split view', 'Show both poles for orientation. The FEM magnet remains one region.'],
              ] as Array<[PublicMagnetPolarityView, string, string, string]>).map(([value, label, ariaLabel, title]) => (
                <button
                  type="button"
                  className={magnetPolarityView === value ? 'is-active' : ''}
                  aria-pressed={magnetPolarityView === value}
                  aria-label={ariaLabel}
                  title={title}
                  onClick={() => setMagnetPolarityView(value)}
                  key={value}
                >
                  {label}
                </button>
              ))}
            </span>
          )}
          {viewportMode === '2d' && mode === 'geometry' && (
            <span className="public-winding-key" aria-label="Winding phase and current direction legend">
              <span><i className="phase-a" />A</span>
              <span><i className="phase-b" />B</span>
              <span><i className="phase-c" />C</span>
              <span className="direction-key">⊙ out · ⊗ in</span>
            </span>
          )}
          {viewportMode === '3d' && (
            <>
              <span className="vc-group"><button type="button" onClick={() => setThreeResetSignal((value) => value + 1)}>Reset view</button></span>
              <span className="vc-group public-explode-controls">
                <button
                  type="button"
                  className={explodedAmount > 0.04 ? 'is-active' : ''}
                  aria-pressed={explodedAmount > 0.04}
                  onClick={() => setExplodedAmount((value) => (value > 0.04 ? 0 : 1))}
                >
                  {explodedAmount > 0.04 ? 'Assemble' : 'Explode'}
                </button>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={Math.round(explodedAmount * 100)}
                  aria-label="Exploded view amount"
                  title={`Exploded view: ${Math.round(explodedAmount * 100)}%`}
                  onChange={(event) => setExplodedAmount(Number(event.target.value) / 100)}
                />
                <output aria-live="polite">{Math.round(explodedAmount * 100)}%</output>
              </span>
            </>
          )}
          {showPlayback && <span className="vc-group public-playback">
            <button type="button" className={isAnimating ? 'is-active' : ''} aria-label={isAnimating ? 'Pause preview' : 'Play preview'} onClick={() => setIsAnimating((value) => !value)}>{isAnimating ? 'Ⅱ' : '▶'}</button>
            <button type="button" aria-label="Stop and reset preview" onClick={() => { setIsAnimating(false); setRotorAngleDeg(0); }}>■</button>
            <input type="range" min="1" max="100" value={animationRpm} onChange={(event) => setAnimationRpm(Number(event.target.value))} aria-label="Preview speed (RPM)" />
            <span>{animationRpm} RPM</span>
          </span>}
        </div>
        {mode === 'geometry' && viewportMode !== 'materials' && (
          <div className="viewport-cad-status">
            {geometry?.regions.length ?? 0} regions · {geometry ? formatNumber(geometry.generation_time_ms, 0) : '—'} ms
          </div>
        )}
      </div>
    </section>
  );
}

function currentGeometryWarnings(
  geometry: GeometryPreview | null,
  geometryStale: boolean,
): string[] {
  if (geometryStale || !Array.isArray(geometry?.metadata?.geometry_warnings)) return [];
  return (geometry.metadata.geometry_warnings as unknown[]).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

interface ToothWidthAdvisory {
  severity: 'info' | 'warning';
  kind: 'bore_tooth' | 'tooth_shoe_shoulder';
  relativeNarrowing: number;
}

function currentToothWidthAdvisory(
  geometry: GeometryPreview | null,
  geometryStale: boolean,
): ToothWidthAdvisory | null {
  if (geometryStale || !geometry?.metadata) return null;
  const raw = geometry.metadata.tooth_width_advisory;
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  if (
    (value.severity !== 'info' && value.severity !== 'warning')
    || (value.kind !== 'bore_tooth' && value.kind !== 'tooth_shoe_shoulder')
    || typeof value.relative_narrowing !== 'number'
    || !Number.isFinite(value.relative_narrowing)
  ) return null;
  return {
    severity: value.severity,
    kind: value.kind,
    relativeNarrowing: value.relative_narrowing,
  };
}

type DesignHealthSeverity = 'positive' | 'info' | 'warning';

interface DesignHealthIssue {
  severity: DesignHealthSeverity;
  title: string;
  copy: string;
}

function HealthPanel({
  config,
  error,
  geometry,
  mesh,
  geometryStale,
  blankDesign = false,
}: Pick<CoilEmWorkspaceProps, 'config' | 'error' | 'geometry' | 'mesh' | 'geometryStale' | 'blankDesign'>) {
  if (blankDesign) {
    return (
      <aside className="design-health-panel tone-updating">
        <div className="design-health-header">
          <div>
            <div className="design-health-eyebrow">Design Health</div>
            <div className="design-health-caption">Checks begin after the first design change.</div>
          </div>
        </div>
        <div className="public-health-status-card updating" role="status">
          <div className="public-health-status-icon" aria-hidden="true">○</div>
          <div>
            <div className="design-health-score-label tone-updating">Blank design</div>
            <p>No geometry, mesh, or results yet.</p>
          </div>
        </div>
      </aside>
    );
  }
  const airgap = magneticAirgapMm(config);
  const airgapHealth = publicAirgapHealth(airgap);
  const coverage = Math.round(config.rotor.magnet_embrace * 100);
  const burialHealth = publicFlatIpmBurialHealth(config);
  const statorWidths = deriveStatorSectionWidths(config, geometryStale ? null : geometry);
  const toothWidthAdvisory = currentToothWidthAdvisory(geometry, geometryStale);
  const issues: DesignHealthIssue[] = [
    ...(error ? [{
      severity: 'warning' as const,
      title: 'Current design needs attention',
      copy: error,
    }] : []),
    airgapHealth,
    ...(burialHealth ? [burialHealth] : []),
    { severity: coverage >= 55 && coverage <= 90 ? 'positive' : 'warning', title: coverage >= 55 && coverage <= 90 ? 'Magnet coverage is in a practical range' : 'Magnet coverage needs review', copy: `${coverage}% pole coverage for the current rotor.` },
    { severity: config.stator.slot_count % 3 === 0 ? 'positive' : 'warning', title: config.stator.slot_count % 3 === 0 ? 'Slot count supports three phases' : 'Slot count does not divide across three phases', copy: `${config.stator.slot_count} stator slots across three phases.` },
    { severity: geometry && !geometryStale ? 'positive' : 'info', title: geometry && !geometryStale ? 'Geometry preview is current' : 'Updating geometry preview', copy: geometry && !geometryStale ? `${geometry.regions.length} regions returned by the local backend.` : 'The preview will refresh after the local backend responds.' },
    ...(mesh ? [{ severity: 'positive' as const, title: 'Mesh quality gate passed', copy: `${mesh.triangles.length.toLocaleString()} generated triangles.` }] : []),
    ...(toothWidthAdvisory ? [{
      severity: toothWidthAdvisory.severity,
      title: toothWidthAdvisory.kind === 'tooth_shoe_shoulder'
        ? toothWidthAdvisory.severity === 'warning' ? 'Tooth-shoe shoulder is much narrower' : 'Tooth-shoe shoulder is slightly narrower'
        : toothWidthAdvisory.severity === 'warning' ? 'Bore tooth is much narrower' : 'Bore tooth is slightly narrower',
      copy: toothWidthAdvisory.kind === 'tooth_shoe_shoulder'
        ? `Narrowest section ${statorWidths.narrowestToothWidthMm.toFixed(1)} mm · yoke tooth ${statorWidths.toothWidthAtYokeMm.toFixed(1)} mm (${(toothWidthAdvisory.relativeNarrowing * 100).toFixed(1)}%).`
        : `Bore ${statorWidths.boreToothWidthMm.toFixed(1)} mm · yoke ${statorWidths.toothWidthAtYokeMm.toFixed(1)} mm (${(toothWidthAdvisory.relativeNarrowing * 100).toFixed(1)}%). ${toothWidthAdvisory.severity === 'warning' ? 'Review peak tooth flux after solving.' : 'This mild taper is usually acceptable.'}`,
    }] : []),
  ];
  const positiveCount = issues.filter((issue) => issue.severity === 'positive').length;
  const infoCount = issues.filter((issue) => issue.severity === 'info').length;
  const warningCount = issues.filter((issue) => issue.severity === 'warning').length;
  const tone = warningCount > 0 ? 'warning' : infoCount > 0 ? 'updating' : 'good';
  const ready = tone === 'good';
  const validToSolve = !error
    && airgap >= PUBLIC_AIRGAP_LAUNCH_MIN_MM
    && burialHealth?.blocking !== true
    && config.stator.slot_count % 3 === 0;
  const statusLabel = ready
    ? 'Ready to solve'
    : tone === 'updating'
      ? 'Updating preview'
      : validToSolve
        ? 'Valid to solve · review design'
        : 'Review before solving';

  return (
    <aside className={`design-health-panel tone-${tone}`}>
      <div className="design-health-header"><div><div className="design-health-eyebrow">Design Health</div><div className="design-health-caption">Basic heuristic checks for the current draft.</div></div></div>
      <div className={`public-health-status-card ${tone}`} role="status">
        <div className="public-health-status-icon" aria-hidden="true">{ready ? '✓' : tone === 'updating' ? '↻' : '!'}</div>
        <div>
          <div className={`design-health-score-label tone-${tone}`}>{statusLabel}</div>
          <p>{positiveCount} checks passed · {warningCount} {warningCount === 1 ? 'warning' : 'warnings'}{infoCount > 0 ? ` · ${infoCount} updating` : ''}</p>
        </div>
      </div>
      <div className="design-health-metrics">
        <div className="design-health-metric"><span>Airgap</span><strong>{airgap.toFixed(2)} mm</strong></div>
        <div className="design-health-metric"><span>Coverage</span><strong>{coverage}%</strong></div>
        <div className="design-health-metric"><span>Q</span><strong>{config.stator.slot_count / Math.max(1, config.rotor.pole_count * 3)} </strong></div>
      </div>
      <div className="public-check-heading"><span>Pre-solve checks</span><strong>{positiveCount} ✓{infoCount > 0 ? ` · ${infoCount} i` : ''}{warningCount > 0 ? ` · ${warningCount} △` : ''}</strong></div>
      <div className="design-health-issue-list">
        {issues.map((issue) => (
          <div className={`design-health-issue severity-${issue.severity}`} key={issue.title}>
            <span className="design-health-issue-icon"><StatusGlyph tone={issue.severity === 'positive' ? 'good' : issue.severity} /></span>
            <span className="design-health-issue-body"><span className="design-health-issue-title">{issue.title}</span><span className="design-health-issue-copy">{issue.copy}</span></span>
          </div>
        ))}
      </div>
    </aside>
  );
}

interface CompactLiveSeries {
  label: string;
  values: number[];
  color: string;
}

function formatCompactAxisValue(value: number, span: number): string {
  const digits = span >= 50 ? 0 : span >= 5 ? 1 : span >= 0.5 ? 2 : span >= 0.05 ? 3 : 4;
  const zeroThreshold = 0.5 * (10 ** -digits);
  return (Math.abs(value) < zeroThreshold ? 0 : value).toFixed(digits);
}

const RUN_PLAN_MIN_WIDTH = 312;
const RUN_PLAN_MAX_WIDTH = 640;
const RUN_PLAN_RESIZE_STEP = 32;
const RUN_PLAN_COMFORT_MAX_WIDTH = 368;
const RUN_PLAN_ACTIVE_WIDTH = 440;
const RUN_PLAN_COMFORT_VIEWPORT = '(min-width: 1800px) and (min-height: 900px)';

function defaultRunPlanWidth(): number {
  if (typeof window === 'undefined' || !window.matchMedia(RUN_PLAN_COMFORT_VIEWPORT).matches) {
    return RUN_PLAN_MIN_WIDTH;
  }
  return Math.min(RUN_PLAN_COMFORT_MAX_WIDTH, Math.max(RUN_PLAN_MIN_WIDTH, Math.round(window.innerWidth * 0.175)));
}

function solveStageLabel(progress: PublicSolveProgress | null, busy: PublicBusyAction): string {
  if (busy === 'mesh') return 'Preparing mesh';
  const stage = progress?.stage;
  if (!stage) return 'Starting analysis';
  const labels: Record<string, string> = {
    Validating: 'Validating setup',
    starting: 'Starting solver',
    magneto2d_sweep: 'Solving rotor sweep',
    magneto2d_iteration: 'Solving field system',
    magneto2d_single: 'Final field solve',
    magneto2d_complete: 'Finalizing results',
    torque_sweep: 'Elmer loaded-torque sweep',
    noload_sweep: 'Elmer back-EMF sweep',
    postprocess: 'Elmer post-processing',
    solver_timing: 'Finalizing results',
    packaging_results: 'Building waveforms and metrics',
    saving_run: 'Saving completed run',
  };
  if (labels[stage]) return labels[stage];
  if (stage.toLowerCase().includes('mesh')) return 'Meshing rotor positions';
  if (stage.toLowerCase().includes('no_load')) return 'Computing back EMF';
  return stage.replace(/_/g, ' ');
}

function CompactLiveChart({
  label,
  unit,
  angles,
  series,
  state = 'live',
  emptyStatus = '0 samples',
  emptyMessage = 'Waiting for samples',
  emptyWorking = false,
}: {
  label: string;
  unit: string;
  angles: number[];
  series: CompactLiveSeries[];
  state?: 'live' | 'complete';
  emptyStatus?: string;
  emptyMessage?: string;
  emptyWorking?: boolean;
}) {
  const plottedSeries = series.filter((item) => item.values.length === angles.length);
  if (angles.length === 0 || plottedSeries.length === 0) {
    return (
      <div className={`public-live-chart waiting${emptyWorking ? ' is-processing' : ''}`} aria-label={`${label}: ${emptyMessage}`}>
        <div className="public-live-chart-heading"><strong>{label}</strong><span>{emptyStatus}</span></div>
        <div className="public-live-chart-waiting"><i />{emptyMessage}</div>
      </div>
    );
  }

  const width = 272;
  const height = 92;
  const padding = { top: 10, right: 8, bottom: 12, left: 38 };
  const minX = Math.min(...angles);
  const maxX = Math.max(...angles);
  const allValues = plottedSeries.flatMap((item) => item.values);
  const rawMinY = Math.min(...allValues);
  const rawMaxY = Math.max(...allValues);
  const yPadding = Math.max((rawMaxY - rawMinY) * 0.12, Math.abs(rawMaxY) * 0.04, 0.01);
  const minY = rawMinY - yPadding;
  const maxY = rawMaxY + yPadding;
  const ySpan = maxY - minY;
  const yMiddle = minY < 0 && maxY > 0 ? 0 : (maxY + minY) / 2;
  const yTickValues = [maxY, yMiddle, minY];
  const x = (value: number) => angles.length === 1
    ? width / 2
    : padding.left + ((value - minX) / Math.max(maxX - minX, 1)) * (width - padding.left - padding.right);
  const y = (value: number) => padding.top + ((maxY - value) / ySpan) * (height - padding.top - padding.bottom);
  const pathFor = (values: number[]) => values
    .map((value, index) => `${index === 0 ? 'M' : 'L'} ${x(angles[index]).toFixed(2)} ${y(value).toFixed(2)}`)
    .join(' ');

  return (
    <div className="public-live-chart">
      <div className="public-live-chart-heading"><strong>{label}</strong><span>{angles.length} {angles.length === 1 ? 'sample' : 'samples'}</span></div>
      {plottedSeries.length > 1 && <div className="public-live-chart-legend">{plottedSeries.map((item) => <span key={item.label}><i style={{ backgroundColor: item.color }} />{item.label}</span>)}</div>}
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${state === 'live' ? 'Live' : 'Completed'} ${label} curve from ${angles.length} solver samples`}>
        {yTickValues.map((tickValue) => (
          <g key={tickValue}>
            <line x1={padding.left} x2={width - padding.right} y1={y(tickValue)} y2={y(tickValue)} />
            <text className="public-live-chart-y-value" x={padding.left - 5} y={y(tickValue) + 2.5} textAnchor="end">{formatCompactAxisValue(tickValue, ySpan)}</text>
          </g>
        ))}
        {plottedSeries.map((item) => {
          const lastIndex = item.values.length - 1;
          return <g key={item.label}><path d={pathFor(item.values)} fill="none" stroke={item.color} /><circle cx={x(angles[lastIndex])} cy={y(item.values[lastIndex])} r="2.5" fill={item.color} /></g>;
        })}
        <text x={padding.left} y={height - 2}>{formatNumber(minX, 0)}°</text>
        <text x={width - padding.right} y={height - 2} textAnchor="end">{formatNumber(maxX, 0)}° · {unit}</text>
      </svg>
    </div>
  );
}

function LiveSolveMonitor({ busy, progress, liveSamples, progressPercent }: Pick<CoilEmWorkspaceProps, 'busy' | 'progress' | 'liveSamples' | 'progressPercent'>) {
  const [displayElapsedSeconds, setDisplayElapsedSeconds] = useState(progress?.elapsed_s ?? 0);
  const torqueSamples = liveSamples.filter((sample) => typeof sample.angle_deg === 'number' && typeof sample.torque_Nm === 'number');
  const backEmfSamples = liveSamples.filter((sample) => typeof sample.angle_deg === 'number'
    && typeof sample.phase_a_V === 'number'
    && typeof sample.phase_b_V === 'number'
    && typeof sample.phase_c_V === 'number');
  const currentPosition = progress?.position ?? 0;
  const totalPositions = progress?.total ?? 0;
  const finalizing = busy === 'solve' && isPublicSolveFinalizing(progress);
  const sweepComplete = finalizing
    && totalPositions > 0
    && currentPosition >= totalPositions - 1;

  useEffect(() => {
    const observedAtMs = Date.now();
    setDisplayElapsedSeconds(progress?.elapsed_s ?? 0);
    if (busy !== 'solve') return undefined;
    const intervalId = window.setInterval(() => {
      setDisplayElapsedSeconds(projectedPublicSolveElapsedSeconds(
        progress?.elapsed_s,
        observedAtMs,
        Date.now(),
      ));
    }, 250);
    return () => window.clearInterval(intervalId);
  }, [busy, progress?.elapsed_s]);

  return (
    <section className={`public-live-monitor${finalizing ? ' is-finalizing' : ''}`} aria-label="Live solve status" aria-busy={busy === 'solve'}>
      <div className="public-live-monitor-heading"><span className="public-section-kicker">Live solve</span><strong>{solveStageLabel(progress, busy)}</strong></div>
      <div
        className={`progress-track${finalizing ? ' indeterminate' : ''}`}
        role="progressbar"
        aria-label={finalizing ? 'Post-processing solved field data' : 'Rotor sweep progress'}
        aria-valuenow={finalizing ? undefined : progressPercent}
      >
        <span style={{ width: finalizing ? '28%' : currentPosition > 0 && totalPositions > 0 ? `${progressPercent}%` : '24%' }} />
      </div>
      {finalizing && (
        <div className="public-finalization-status">
          <i aria-hidden="true" />
          <div>
            <strong>Analysis is still running</strong>
            <span>The field sweep is complete. Building torque, Back-EMF, field plots, and the local run package.</span>
          </div>
        </div>
      )}
      <dl className="public-live-stats">
        <div><dt>Total elapsed</dt><dd>{formatNumber(displayElapsedSeconds, 1)} s</dd></div>
        <div><dt>{finalizing ? 'Sweep' : 'Positions'}</dt><dd>{sweepComplete ? 'Complete' : `${currentPosition} / ${totalPositions > 0 ? totalPositions : '—'}`}</dd></div>
      </dl>
      <CompactLiveChart
        label="Torque"
        unit="N·m"
        angles={torqueSamples.map((sample) => sample.angle_deg as number)}
        series={[{ label: 'Torque', values: torqueSamples.map((sample) => sample.torque_Nm as number), color: '#f59e0b' }]}
      />
      <CompactLiveChart
        label="Three-phase back EMF"
        unit="V"
        angles={backEmfSamples.map((sample) => sample.angle_deg as number)}
        series={[
          { label: 'A', values: backEmfSamples.map((sample) => sample.phase_a_V as number), color: '#f87171' },
          { label: 'B', values: backEmfSamples.map((sample) => sample.phase_b_V as number), color: '#4ade80' },
          { label: 'C', values: backEmfSamples.map((sample) => sample.phase_c_V as number), color: '#60a5fa' },
        ]}
        emptyStatus={finalizing ? 'Post-processing' : '0 samples'}
        emptyMessage={finalizing ? 'Building waveform from solved fields' : 'Waiting for samples'}
        emptyWorking={finalizing}
      />
    </section>
  );
}

function CompletedResultMonitor({ result, onOpenReport }: { result: SolveResult; onOpenReport: () => void }) {
  const [activePlot, setActivePlot] = useState<'torque' | 'back-emf'>('torque');
  const sixStep = resultUsesSixStep(result);
  const completeCycle = result.solve_metadata.loaded_cycle_complete === true;
  const thdLabel = result.back_emf_harmonic_analysis
    ? 'Back EMF THD H12'
    : 'Back EMF THD legacy';

  return (
    <section className="public-completed-results" aria-label="Completed solver results">
      <div className="public-completed-results-heading">
        <div><span className="public-section-kicker">Completed results</span><strong>Solver waveforms</strong></div>
        <button type="button" data-guide="open-report" onClick={onOpenReport}>Full results →</button>
      </div>
      <dl className="public-result-metrics">
        <div><dt>Average torque{sixStep && !completeCycle ? ' · preview' : ''}</dt><dd>{formatNumber(result.summary.avg_torque_Nm)} N·m</dd></div>
        <div><dt>Torque ripple{sixStep && !completeCycle ? ' · preview' : ''}</dt><dd>{formatNumber(result.summary.torque_ripple_pct)} %</dd></div>
        <div><dt>Back EMF</dt><dd>{formatNumber(result.summary.back_emf_fundamental_V)} V</dd></div>
        <div><dt>{thdLabel}</dt><dd>{formatNumber(result.summary.back_emf_thd_pct)} %</dd></div>
        <div><dt>Peak tooth B</dt><dd>{formatNumber(result.summary.peak_flux_density_teeth_T)} T</dd></div>
        <div><dt>Peak yoke B</dt><dd>{formatNumber(result.summary.peak_flux_density_yoke_T)} T</dd></div>
        <div><dt>Solver time</dt><dd>{formatNumber(result.summary.solve_time_s, 1)} s</dd></div>
        {result.workflow_elapsed_s != null && <div><dt>Total elapsed</dt><dd>{formatNumber(result.workflow_elapsed_s, 1)} s</dd></div>}
      </dl>
      <div className="public-compact-result-tabs" role="tablist" aria-label="Completed result plots">
        <button type="button" role="tab" aria-selected={activePlot === 'torque'} className={activePlot === 'torque' ? 'active' : ''} onClick={() => setActivePlot('torque')}>Torque</button>
        <button type="button" role="tab" aria-selected={activePlot === 'back-emf'} className={activePlot === 'back-emf' ? 'active' : ''} onClick={() => setActivePlot('back-emf')}>Back EMF</button>
      </div>
      {activePlot === 'torque' && sixStep && result.phase_current_waveform
        ? <BldcTorqueCurrentChart angles={result.torque_waveform.electrical_angle_deg} torqueNm={result.torque_waveform.torque_Nm} phaseA={result.phase_current_waveform.phase_a_A} phaseB={result.phase_current_waveform.phase_b_A} phaseC={result.phase_current_waveform.phase_c_A} commutationAdvanceDeg={result.solve_metadata.commutation_advance_deg ?? 0} cycleComplete={completeCycle} />
        : activePlot === 'torque' && <CompactLiveChart state="complete" label="Torque" unit="N·m" angles={result.torque_waveform.electrical_angle_deg} series={[{ label: 'Torque', values: result.torque_waveform.torque_Nm, color: '#f59e0b' }]} />}
      {activePlot === 'back-emf' && <>
        <CompactLiveChart state="complete" label="Three-phase back EMF" unit="V" angles={result.back_emf_waveform.electrical_angle_deg} series={[{ label: 'A', values: result.back_emf_waveform.phase_a_V, color: '#f87171' }, { label: 'B', values: result.back_emf_waveform.phase_b_V, color: '#4ade80' }, { label: 'C', values: result.back_emf_waveform.phase_c_V, color: '#60a5fa' }]} />
        {result.back_emf_harmonic_analysis && <BackEMFHarmonicSpectrum analysis={result.back_emf_harmonic_analysis} compact />}
      </>}
      <p>Spatial flux density and field lines remain visible in the solved-field viewport.</p>
    </section>
  );
}

function BackEMFHarmonicSpectrum({
  analysis,
  compact = false,
}: {
  analysis: NonNullable<SolveResult['back_emf_harmonic_analysis']>;
  compact?: boolean;
}) {
  const thdMetrics = [
    ['Phase THD H6', analysis.phase_a_thd_h6_pct],
    ['Phase THD H12', analysis.phase_a_thd_h12_pct],
    ['Phase THD H24', analysis.phase_a_thd_h24_pct],
    ['Line AB THD H12', analysis.line_ab_thd_h12_pct],
    ['Line AB THD H24', analysis.line_ab_thd_h24_pct],
  ].filter((metric): metric is [string, number] => typeof metric[1] === 'number');

  return (
    <section className={`public-harmonic-spectrum${compact ? ' compact' : ''}`} aria-label="Back EMF harmonic spectrum">
      <div className="public-harmonic-spectrum-heading">
        <div><span>Back EMF spectrum</span><strong>H1–H{analysis.extended_harmonic_max}</strong></div>
        <small>{analysis.sample_count} samples · {formatNumber(analysis.electrical_fundamental_frequency_Hz, 1)} Hz fundamental</small>
      </div>
      <dl className="public-harmonic-thd-metrics">
        {thdMetrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{formatNumber(value)}%</dd></div>)}
      </dl>
      <div className="public-harmonic-table" role="table" aria-label="Harmonic order, frequency, and RMS voltage">
        <div className="public-harmonic-row header" role="row"><span>Order</span><span>Frequency</span><span>Phase A / H1</span><span>Phase A</span><span>Line AB</span></div>
        {analysis.harmonics.map((harmonic) => {
          const phasePct = harmonic.phase_a_pct_fundamental ?? 0;
          return (
            <div className="public-harmonic-row" role="row" key={harmonic.order}>
              <strong>H{harmonic.order}</strong>
              <span>{formatNumber(harmonic.frequency_Hz, harmonic.frequency_Hz < 100 ? 1 : 0)} Hz</span>
              <span className="public-harmonic-bar"><i style={{ width: `${Math.min(100, Math.max(phasePct > 0 ? 2 : 0, phasePct))}%` }} /><em>{formatNumber(phasePct, 2)}%</em></span>
              <span>{formatNumber(harmonic.phase_a_rms_V, 3)} V</span>
              <span>{formatNumber(harmonic.line_ab_rms_V, 3)} V</span>
            </div>
          );
        })}
      </div>
      <p>All electrical orders are retained, including even and triplen harmonics. Line-to-line values show natural triplen cancellation. RMS values come from a periodic no-load flux-linkage DFT.</p>
    </section>
  );
}

function SolveStage({ config, materials, geometry, mesh, validation, validationChecking, validationError, result, armatureField, armatureFieldError, progress, liveSamples, busy, error, errorDetails, notice, progressPercent, meshElements, meshQuality, selectedSolver, elmerCapability, onBack, onOpenReport, onGenerateMesh, onStartSolve, onCancelSolve, onRequestArmatureField, onMeshSettingChange, onSolvePlanChange, onCustomSweepChange, onSolveSettingChange, onSolverChange, onManageRuns }: Pick<CoilEmWorkspaceProps,
  'config' | 'materials' | 'geometry' | 'mesh' | 'validation' | 'validationChecking' | 'validationError' | 'result' | 'armatureField' | 'armatureFieldError' | 'progress' | 'liveSamples' | 'busy' | 'error' | 'errorDetails' | 'notice' | 'progressPercent' | 'meshElements' | 'meshQuality' | 'selectedSolver' | 'elmerCapability' | 'onGenerateMesh' | 'onStartSolve' | 'onCancelSolve' | 'onRequestArmatureField' | 'onMeshSettingChange' | 'onSolvePlanChange' | 'onCustomSweepChange' | 'onSolveSettingChange' | 'onSolverChange'
> & { onBack: () => void; onOpenReport: () => void; onManageRuns?: () => void }) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [customSweepOpen, setCustomSweepOpen] = useState(
    () => config.solve_params.solve_quality === 'custom',
  );
  const [solveView, setSolveView] = useState<'geometry' | 'mesh' | 'field'>(mesh ? 'mesh' : 'geometry');
  const [solveViewportExpanded, setSolveViewportExpanded] = useState(false);
  const [meshDisplayMode, setMeshDisplayMode] = useState<PublicMeshDisplayMode>('geometry');
  const [showMeshEdges, setShowMeshEdges] = useState(true);
  const [focusedMeshElementIndex, setFocusedMeshElementIndex] = useState<number | null>(null);
  const [transientNotice, setTransientNotice] = useState<string | null>(null);
  const [analysisDetailsOpen, setAnalysisDetailsOpen] = useState(() => !result);
  const [elementQualityDetailsOpen, setElementQualityDetailsOpen] = useState(() => !result);
  const [runPlanWidth, setRunPlanWidth] = useState(defaultRunPlanWidth);
  const [resizingRunPlan, setResizingRunPlan] = useState(false);
  const completedResultAvailableRef = useRef(Boolean(result));
  const advancedOptionsRef = useRef<HTMLDetailsElement>(null);
  const nonlinearSolverRef = useRef<HTMLSelectElement>(null);
  const fineMeshRef = useRef<HTMLButtonElement>(null);
  const recoveryFocusTargetRef = useRef<HTMLElement | null>(null);
  const [recoveryFocusRequest, setRecoveryFocusRequest] = useState(0);
  const runPlanScrollRef = useRef<HTMLDivElement>(null);
  const runPlanAutoExpandedRef = useRef(false);
  const runPlanUserSizedRef = useRef(false);
  const runPlanDragRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const solvePlans: Array<{ value: PublicSolvePreset; label: string; meshLabel: string; tradeoff: string; recommended?: boolean }> = [
    { value: 'quick', label: 'Preview', meshLabel: 'Coarse mesh', tradeoff: 'Fast iteration' },
    { value: 'standard', label: 'Standard', meshLabel: 'Medium mesh', tradeoff: 'Balanced', recommended: true },
    { value: 'fine', label: 'High accuracy', meshLabel: 'Fine mesh', tradeoff: 'Finer detail' },
  ];
  const elmerAvailable = elmerCapability.available
    && elmerCapability.qualified
    && elmerCapability.adapter_ready;
  const selectedSolverAvailable = selectedSolver === 'magneto2d' || elmerAvailable;
  const sixStepSelected = config.solve_params.excitation_mode === 'ideal_six_step_120';
  const sixStepSupported = config.topology === 'SPM' && selectedSolver === 'magneto2d';
  const solverLabel = selectedSolver === 'elmer' ? 'Elmer FEM' : 'Magneto2D';
  const solverCaption = selectedSolver === 'elmer'
    ? `External Elmer ${elmerCapability.solver_version || '26.2'} · native Gmsh · remesh per position.`
    : 'Built-in field solver using the prepared native Gmsh mesh.';
  const densityChoices: Array<{ value: 'coarse' | 'normal' | 'fine'; label: string }> = [
    { value: 'coarse', label: 'Coarse' },
    { value: 'normal', label: 'Medium' },
    { value: 'fine', label: 'Fine' },
  ];
  const appliedRefinement = mesh?.mesh_info.corner_refinement === true;
  const meshQualitySummary = useMemo(() => summarizePublicMeshQuality(mesh), [mesh]);
  const qualityPasses = Boolean(mesh) && meshQualitySummary.minimum >= meshQualitySummary.threshold;
  const weakElementCount = meshQualitySummary.weakElementIndices.length;
  const qualityElementCount = Math.max(1, meshQualitySummary.qualities.length);
  const planLabel = config.solve_params.solve_quality === 'custom'
    ? `Custom · ${config.solve_params.rotor_step_deg}° elec`
    : solvePlans.find((plan) => plan.value === config.solve_params.solve_quality)?.label
      ?? config.solve_params.solve_quality;
  const estimatedTimeText = validation
    ? `~${formatNumber(validation.estimated_solve_time_s, 0)} s solver`
    : validationChecking
      ? 'Calculating…'
      : 'Estimate unavailable';
  const positionsText = validation
    ? `${validation.sweep_positions} rotor positions`
    : validationChecking
      ? 'Calculating positions…'
      : 'Positions unavailable';
  const electricalFrequencyHz = config.solve_params.rated_speed_rpm * config.rotor.pole_count / 120;
  const outputLabels = [
    'Torque sweep',
    'Three-phase back EMF',
    'Flux-density field map',
  ];
  const torqueMethodLabel = selectedSolver === 'elmer'
    ? 'Arkkio'
    : config.solve_params.torque_method === 'weighted_stress'
    ? 'WST'
    : config.solve_params.torque_method === 'contour'
      ? 'Contour MST'
      : 'Arkkio';
  const nonlinearSolverLabel = selectedSolver === 'elmer'
    ? 'Elmer nonlinear'
    : config.solve_params.nonlinear_solver === 'picard' ? 'Picard' : 'Newton';
  const linearSolverLabel = selectedSolver === 'elmer'
    ? 'UMFPACK'
    : config.solve_params.linear_solver_preconditioner === 'direct'
    ? 'Direct'
    : config.solve_params.linear_solver_preconditioner === 'ic0'
      ? 'IC(0)'
      : 'Jacobi';
  const meshDensityLabel = config.solve_params.mesh_density === 'normal'
    ? 'Medium'
    : config.solve_params.mesh_density.replace('_', ' ');
  const runReady = Boolean(mesh)
    && Boolean(validation?.valid)
    && selectedSolverAvailable
    && !validationChecking
    && !validationError
    && qualityPasses
    && (!sixStepSelected || sixStepSupported);
  const solveInProgress = busy === 'solve';
  const convergenceFailed = Boolean(error) && errorDetails?.error_code === 'NONLINEAR_CONVERGENCE_FAILED';
  const reviewDesignForConvergence = config.solve_params.nonlinear_solver === 'newton'
    && ['fine', 'very_fine'].includes(config.solve_params.mesh_density);
  const convergenceTip = config.solve_params.nonlinear_solver === 'picard'
    ? 'In Advanced options, change Nonlinear solver to Newton (experimental), then run the analysis again.'
    : reviewDesignForConvergence
      ? 'Newton and a fine mesh are already selected. Review the geometry and steel B–H curve, especially near saturation, before retrying.'
      : 'Try a finer mesh: in Advanced options, choose Fine under Mesh preparation, click Prepare mesh, then rerun. If it still fails, review the geometry and steel B–H curve.';
  const openConvergenceSettings = () => {
    recoveryFocusTargetRef.current = config.solve_params.nonlinear_solver === 'picard'
      ? nonlinearSolverRef.current
      : fineMeshRef.current;
    setAdvancedOpen(true);
    setRecoveryFocusRequest((request) => request + 1);
  };
  const completedAnalysisAvailable = Boolean(result) && busy === null;
  const finalizingResults = solveInProgress && isPublicSolveFinalizing(progress);
  const runDisabled = busy === 'mesh'
    || busy === 'field'
    || (busy !== 'solve' && !runReady);
  const runReadinessTitle = solveInProgress
    ? finalizingResults
      ? 'Finalizing results'
      : 'Analysis in progress'
    : busy === 'mesh'
      ? 'Preparing mesh'
      : validationChecking
        ? 'Checking setup'
        : runReady
          ? 'Ready to run'
          : 'Review before running';
  const runReadinessCopy = validationError
    ? validationError
    : solveInProgress
      ? finalizingResults
        ? 'The rotor sweep is complete. The solver is assembling waveforms, metrics, field plots, and the saved run.'
        : 'The local solver is active. Live position and waveform progress appears below.'
      : !selectedSolverAvailable
        ? elmerCapability.reason || 'Install the qualified Elmer 26.2 runtime to enable this solver.'
      : sixStepSelected && !sixStepSupported
        ? 'Ideal six-step excitation requires an inner-rotor SPM design and the built-in Magneto2D solver.'
      : runReady
      ? `${planLabel} · ${positionsText} · ${estimatedTimeText}`
      : validation?.errors[0]?.message ?? 'Complete the mesh and input checks to enable the analysis.';
  const actionTone: 'good' | 'info' | 'warning' = error || validationError || validation?.valid === false
    ? 'warning'
    : runReady
      ? 'good'
      : 'info';
  const actionStatus = error
    ? convergenceFailed ? 'Convergence failed — review solver settings' : 'Review the request details before running'
    : busy === 'solve'
      ? finalizingResults ? 'Preparing playback and saving results' : 'Analysis running locally'
      : busy === 'mesh'
        ? 'Preparing the native mesh'
        : busy === 'field'
          ? 'Computing the stator-only field'
          : result
            ? 'Analysis complete — view your results'
            : validationError
              ? 'Run estimate unavailable — check the local backend'
              : validationChecking
                ? 'Checking inputs and estimating the run'
                : runReady
                  ? 'Ready to run'
                  : mesh
                    ? 'Review the setup before running'
              : 'Prepare a mesh to continue';

  useEffect(() => {
    if (!notice) return undefined;
    setTransientNotice(notice);
    const timer = window.setTimeout(() => setTransientNotice(null), 4_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!advancedOpen) return undefined;
    const animationFrame = window.requestAnimationFrame(() => {
      const recoveryTarget = recoveryFocusTargetRef.current;
      recoveryFocusTargetRef.current = null;
      recoveryTarget?.focus({ preventScroll: true });
      (recoveryTarget ?? advancedOptionsRef.current)?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: recoveryTarget ? 'center' : 'start',
      });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [advancedOpen, recoveryFocusRequest]);

  useEffect(() => {
    if (config.solve_params.solve_quality === 'custom') setCustomSweepOpen(true);
  }, [config.solve_params.solve_quality]);

  useEffect(() => {
    setFocusedMeshElementIndex(null);
    setMeshDisplayMode('geometry');
  }, [mesh]);

  useEffect(() => {
    if (!result && mesh) setSolveView('mesh');
  }, [mesh, result]);

  useEffect(() => {
    if (result) setSolveView('field');
  }, [result]);

  useEffect(() => {
    const resultAvailable = Boolean(result);
    if (resultAvailable === completedResultAvailableRef.current) return;
    setAnalysisDetailsOpen(!resultAvailable);
    setElementQualityDetailsOpen(!resultAvailable);
    completedResultAvailableRef.current = resultAvailable;
  }, [result]);

  useEffect(() => {
    // A failed retry may restore an earlier result. Keep the new failure visible
    // even when completed results normally collapse this section.
    if (error) setAnalysisDetailsOpen(true);
  }, [error, result]);

  useEffect(() => {
    if (!solveViewportExpanded) return undefined;
    const restoreOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setSolveViewportExpanded(false);
    };
    window.addEventListener('keydown', restoreOnEscape);
    return () => window.removeEventListener('keydown', restoreOnEscape);
  }, [solveViewportExpanded]);

  const maxRunPlanWidth = () => typeof window === 'undefined'
    ? RUN_PLAN_MAX_WIDTH
    : Math.max(RUN_PLAN_MIN_WIDTH, Math.min(RUN_PLAN_MAX_WIDTH, window.innerWidth - 680));
  const clampRunPlanWidth = (value: number) => Math.max(RUN_PLAN_MIN_WIDTH, Math.min(maxRunPlanWidth(), value));

  useEffect(() => {
    const syncAutomaticRunPlanWidth = () => {
      if (runPlanUserSizedRef.current) return;
      setRunPlanWidth(runPlanAutoExpandedRef.current
        ? clampRunPlanWidth(RUN_PLAN_ACTIVE_WIDTH)
        : defaultRunPlanWidth());
    };
    window.addEventListener('resize', syncAutomaticRunPlanWidth);
    return () => window.removeEventListener('resize', syncAutomaticRunPlanWidth);
  }, []);

  const handleRunPlanResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    runPlanAutoExpandedRef.current = false;
    runPlanUserSizedRef.current = true;
    runPlanDragRef.current = { startX: event.clientX, startWidth: runPlanWidth };
    setResizingRunPlan(true);
  };
  const handleRunPlanResizeKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const keyWidths: Partial<Record<string, number>> = {
      ArrowLeft: runPlanWidth + RUN_PLAN_RESIZE_STEP,
      ArrowRight: runPlanWidth - RUN_PLAN_RESIZE_STEP,
      Home: RUN_PLAN_MIN_WIDTH,
      End: maxRunPlanWidth(),
    };
    const nextWidth = keyWidths[event.key];
    if (nextWidth === undefined) return;
    event.preventDefault();
    runPlanAutoExpandedRef.current = false;
    runPlanUserSizedRef.current = true;
    setRunPlanWidth(clampRunPlanWidth(nextWidth));
  };

  const resetRunPlanWidth = () => {
    runPlanAutoExpandedRef.current = false;
    runPlanUserSizedRef.current = false;
    setRunPlanWidth(defaultRunPlanWidth());
  };

  const handleStartSolve = () => {
    runPlanAutoExpandedRef.current = true;
    setAnalysisDetailsOpen(true);
    setRunPlanWidth((currentWidth) => Math.max(
      currentWidth,
      clampRunPlanWidth(RUN_PLAN_ACTIVE_WIDTH),
    ));
    window.requestAnimationFrame(() => {
      runPlanScrollRef.current?.scrollTo({
        top: 0,
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      });
    });
    onStartSolve();
  };

  useEffect(() => {
    if (!resizingRunPlan) return undefined;
    const handlePointerMove = (event: PointerEvent) => {
      if (!runPlanDragRef.current) return;
      const { startX, startWidth } = runPlanDragRef.current;
      setRunPlanWidth(clampRunPlanWidth(startWidth + startX - event.clientX));
    };
    const handlePointerUp = () => {
      runPlanDragRef.current = null;
      setResizingRunPlan(false);
    };
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerUp);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerUp);
    };
  }, [resizingRunPlan]);

  const solveViewportSwitch = (
    <div className="public-solve-view-switch" role="group" aria-label="Solve viewport">
      <button type="button" aria-pressed={solveView === 'geometry'} onClick={() => setSolveView('geometry')}>Geometry</button>
      <button type="button" aria-pressed={solveView === 'mesh'} disabled={!mesh} onClick={() => setSolveView('mesh')}>Mesh</button>
      <button type="button" aria-pressed={solveView === 'field'} disabled={!result?.field_line_plot} onClick={() => setSolveView('field')}>Field solution</button>
    </div>
  );

  return (
    <div className={`public-solve-workspace${resizingRunPlan ? ' is-resizing-run-plan' : ''}${solveInProgress ? ' is-run-plan-focused' : ''}${solveViewportExpanded ? ' is-viewport-expanded' : ''}`}>
      <aside className="public-solve-setup">
        <div className="mesh-panel-header"><span className="mesh-panel-header-title">Analysis setup</span></div>
        <div className="public-solve-setup-scroll">
        {elmerCapability.feature_enabled && <div className="public-setup-section public-solver-section">
          <span className="public-section-kicker">Solver</span>
          <div className="public-solver-selector" role="radiogroup" aria-label="Electromagnetic solver">
            <button
              type="button"
              role="radio"
              aria-checked={selectedSolver === 'magneto2d'}
              className={selectedSolver === 'magneto2d' ? 'active' : ''}
              disabled={busy !== null}
              onClick={() => onSolverChange('magneto2d')}
            >
              <span><strong>Magneto2D</strong><em>Built in</em></span>
              <small>Fast native field solve</small>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={selectedSolver === 'elmer'}
              aria-disabled={!elmerAvailable || busy !== null || sixStepSelected}
              className={selectedSolver === 'elmer' ? 'active' : ''}
              disabled={!elmerAvailable || busy !== null || sixStepSelected}
              title={sixStepSelected
                ? 'Ideal six-step excitation uses Magneto2D in the MVP.'
                : !elmerAvailable
                  ? elmerCapability.reason || 'Qualified Elmer 26.2 runtime not detected.'
                  : undefined}
              onClick={() => onSolverChange('elmer')}
            >
              <span><strong>Elmer FEM</strong><em>{elmerAvailable ? 'Detected' : 'Not detected'}</em></span>
              <small>{elmerAvailable ? `Version ${elmerCapability.solver_version || '26.2'}` : 'Install Elmer 26.2 to enable'}</small>
            </button>
          </div>
          {!elmerAvailable && <p className="public-solver-diagnostic">{elmerCapability.reason || 'Qualified Elmer 26.2 runtime not detected.'}</p>}
        </div>}
        <div className="public-setup-section">
          <span className="public-section-kicker">Operating point</span>
          <div className="public-excitation-selector" role="radiogroup" aria-label="Stator excitation">
            <button
              type="button"
              role="radio"
              aria-checked={!sixStepSelected}
              className={!sixStepSelected ? 'active' : ''}
              disabled={busy !== null}
              onClick={() => onSolveSettingChange('excitation_mode', 'sinusoidal')}
            >
              <strong>Sinusoidal</strong>
              <small>Three-phase rotating field</small>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={sixStepSelected}
              aria-disabled={config.topology !== 'SPM' || busy !== null}
              className={sixStepSelected ? 'active' : ''}
              disabled={config.topology !== 'SPM' || busy !== null}
              title={config.topology !== 'SPM' ? 'Choose an SPM topology to enable ideal six-step excitation.' : undefined}
              onClick={() => onSolveSettingChange('excitation_mode', 'ideal_six_step_120')}
            >
              <strong>Ideal six-step (120°)</strong>
              <small>Two phases conduct per sector</small>
            </button>
          </div>
          <NumberRow label={sixStepSelected ? 'Conducting phase current' : 'Phase Current'} value={config.solve_params.current_amplitude_A} unit={sixStepSelected ? 'A plateau' : `A ${config.solve_params.current_amplitude_convention}`} min={0} max={1000} step={0.5} disabled={busy !== null} onChange={(value) => onSolveSettingChange('current_amplitude_A', value)} />
          {sixStepSelected && <NumberRow label="Commutation advance" value={config.solve_params.commutation_advance_deg} unit="electrical degrees" min={-180} max={180} step={1} disabled={busy !== null} onChange={(value) => onSolveSettingChange('commutation_advance_deg', value)} />}
          <NumberRow label="Rated Speed" value={config.solve_params.rated_speed_rpm} unit="rpm" min={0} max={30000} step={50} disabled={busy !== null} onChange={(value) => onSolveSettingChange('rated_speed_rpm', value)} />
          <div className="public-derived-operating-point" aria-label="Derived operating point">
            <span>{formatNumber(electricalFrequencyHz, 0)} Hz electrical</span>
            <span>{sixStepSelected ? `${config.solve_params.commutation_advance_deg.toFixed(0)}° commutation advance` : `${config.solve_params.current_angle_deg.toFixed(0)}° current angle`}</span>
            <span>{sixStepSelected ? 'Wye · plateau current' : `${config.solve_params.current_amplitude_convention.toUpperCase()} phase current`}</span>
          </div>
          {sixStepSelected && <div className="public-six-step-limitation" role="note"><strong>Phase connection: Wye (MVP)</strong><span>Ideal current excitation only — no PWM, switching ripple, Hall timing, dead time, or ESC dynamics.</span></div>}
        </div>
        <div className="public-setup-section" data-guide="solve-plan">
          <span className="public-section-kicker">Accuracy plan</span>
          <div className="public-choice-row public-solve-plan-choices">
            {solvePlans.map((plan) => (
              <button
                type="button"
                className={config.solve_params.solve_quality === plan.value ? 'active' : ''}
                aria-pressed={config.solve_params.solve_quality === plan.value}
                disabled={busy !== null}
                onClick={() => {
                  setCustomSweepOpen(false);
                  onSolvePlanChange(plan.value);
                }}
                key={plan.value}
              >
                {plan.recommended && <em>Recommended</em>}
                <span>{plan.label}</span>
                <small>{plan.meshLabel}</small>
                <small>{config.solve_params.solve_quality === plan.value && validation
                  ? estimatedTimeText
                  : plan.tradeoff}</small>
              </button>
            ))}
          </div>
          <div className={`public-custom-sweep${config.solve_params.solve_quality === 'custom' ? ' active' : ''}`}>
            <button
              type="button"
              className="public-custom-sweep-toggle"
              aria-expanded={customSweepOpen}
              aria-controls="public-custom-sweep-controls"
              disabled={busy !== null}
              onClick={() => {
                const nextOpen = !customSweepOpen;
                setCustomSweepOpen(nextOpen);
                if (nextOpen && config.solve_params.solve_quality !== 'custom') {
                  onCustomSweepChange(PUBLIC_CUSTOM_SWEEP_DEFAULT_STEP_DEG);
                }
              }}
            >
              <span>Custom...</span>
              <small>Choose the electrical-angle step</small>
              <i aria-hidden="true">{customSweepOpen ? '▴' : '▾'}</i>
            </button>
            {customSweepOpen && (
              <div className="public-custom-sweep-body" id="public-custom-sweep-controls">
                <NumberRow
                  label="Step Size (° elec)"
                  value={config.solve_params.solve_quality === 'custom'
                    ? config.solve_params.rotor_step_deg
                    : PUBLIC_CUSTOM_SWEEP_DEFAULT_STEP_DEG}
                  min={PUBLIC_CUSTOM_SWEEP_MIN_STEP_DEG}
                  max={PUBLIC_CUSTOM_SWEEP_MAX_STEP_DEG}
                  step={0.5}
                  disabled={busy !== null}
                  onChange={onCustomSweepChange}
                />
                <div className="public-custom-sweep-estimate" aria-live="polite">
                  <strong>{validation
                    ? `${validation.sweep_positions} positions`
                    : validationChecking
                      ? 'Calculating…'
                      : 'Unavailable'}</strong>
                  <span>{estimatedTimeText}</span>
                  <small>360° electrical sweep</small>
                </div>
              </div>
            )}
          </div>
          {config.solve_params.solve_quality === 'quick' && (
            <p className="public-plan-advisory">Preview is intended for iteration, not final result sign-off.</p>
          )}
        </div>
        <p className="public-timing-note">Solver estimate only. Playback and saving add time; total duration varies by computer.</p>
        <details ref={advancedOptionsRef} className="public-advanced-options" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
          <summary>
            <span>Advanced options</span>
            <small>{torqueMethodLabel} · {nonlinearSolverLabel} · {linearSolverLabel} · {validation ? `${validation.sweep_positions}p` : '…'} · {meshDensityLabel}</small>
          </summary>
          <div className="public-advanced-body">
            <section className="public-advanced-section public-advanced-mesh-section" aria-labelledby="public-mesh-preparation-heading">
              <span className="public-section-kicker" id="public-mesh-preparation-heading">Mesh preparation</span>
              <div className="mesh-segmented-control">{densityChoices.map((choice) => <button ref={choice.value === 'fine' ? fineMeshRef : undefined} type="button" className={config.solve_params.mesh_density === choice.value ? 'active' : ''} aria-pressed={config.solve_params.mesh_density === choice.value} disabled={busy !== null} onClick={() => onMeshSettingChange('mesh_density', choice.value)} key={choice.value}>{choice.label}</button>)}</div>
              <label className="public-check-row"><input type="checkbox" checked={config.solve_params.corner_refinement} disabled={busy !== null} onChange={(event) => onMeshSettingChange('corner_refinement', event.target.checked)} /> Corner refinement</label>
              <button className="public-prepare-mesh-btn" type="button" disabled={busy !== null} onClick={onGenerateMesh}>{busy === 'mesh' ? 'Preparing mesh…' : mesh ? 'Regenerate mesh' : 'Prepare mesh'}</button>
            </section>
            <section className="public-advanced-section public-advanced-controls-section" aria-labelledby="public-electromagnetic-controls-heading">
              <span className="public-section-kicker" id="public-electromagnetic-controls-heading">Electromagnetic controls</span>
              {selectedSolver === 'elmer' ? (
                <div className="public-elmer-profile-note">
                  <strong>Qualified Elmer 26.2 profile</strong>
                  <span>Arkkio torque · nonlinear relaxation · direct UMFPACK · remesh per rotor position</span>
                  <small>These numerical controls are fixed so Elmer and Magneto2D comparisons remain reproducible.</small>
                </div>
              ) : <>
                <dl className="public-solver-settings" aria-label="Solver settings">
                  <div><dt>Torque method</dt><dd>WST</dd></div>
                  <div><dt>Linear solver</dt><dd>Direct Cholesky</dd></div>
                </dl>
                <SelectRow selectRef={nonlinearSolverRef} label="Nonlinear solver" value={config.solve_params.nonlinear_solver} disabled={busy !== null} choices={[{ value: 'picard', label: 'Picard (recommended)' }, { value: 'newton', label: 'Newton (experimental)' }]} onChange={(value) => onSolveSettingChange('nonlinear_solver', value as MotorConfig['solve_params']['nonlinear_solver'])} />
                <p className="public-solver-help">Picard is the default. Try Newton if a run fails to converge.</p>
              </>}
              {!sixStepSelected && <SelectRow label="Current convention" value={config.solve_params.current_amplitude_convention} disabled={busy !== null} choices={[{ value: 'rms', label: 'RMS' }, { value: 'peak', label: 'Peak' }]} onChange={(value) => onSolveSettingChange('current_amplitude_convention', value as MotorConfig['solve_params']['current_amplitude_convention'])} />}
              {!sixStepSelected && <NumberRow label="Current angle" value={config.solve_params.current_angle_deg} unit="deg" min={-180} max={180} step={1} disabled={busy !== null} onChange={(value) => onSolveSettingChange('current_angle_deg', value)} />}
            </section>
            <section className="public-advanced-section public-advanced-output-section" aria-labelledby="public-generated-outputs-heading">
              <span className="public-section-kicker" id="public-generated-outputs-heading">Generated outputs</span>
              <div className="public-output-chips">
                {outputLabels.map((label) => <span key={label}><i aria-hidden="true">✓</i>{label}</span>)}
              </div>
            </section>
          </div>
        </details>
        </div>
        <div className="public-solve-footer">
          <div className={`validation-ok${actionTone === 'warning' ? ' has-error' : ''}`}><StatusGlyph tone={actionTone} />{actionStatus}</div>
          <div className="public-run-consequence">
            <span>{positionsText}</span>
            <span>{outputLabels.length} outputs</span>
            <strong>{estimatedTimeText}</strong>
          </div>
          {completedAnalysisAvailable ? (
            <>
              <button className="public-run-btn" type="button" data-guide="open-report" onClick={onOpenReport}>View Results →</button>
              <button className="public-run-again-btn" type="button" data-guide="solve-run" disabled={runDisabled} onClick={handleStartSolve}>Run again</button>
            </>
          ) : (
            <button className={busy === 'solve' ? 'public-cancel-btn' : 'public-run-btn'} type="button" data-guide="solve-run" disabled={runDisabled} onClick={busy === 'solve' ? onCancelSolve : handleStartSolve}>{busy === 'solve' ? '■ Cancel solve' : busy === 'mesh' ? 'Preparing mesh…' : busy === 'field' ? 'Computing stator field…' : validationChecking ? 'Checking setup…' : '▶ Run analysis'}</button>
          )}
          <button className="public-back-link" type="button" onClick={onBack}>← Back to Design</button>
        </div>
      </aside>
      <div className="public-live-stage">
        {transientNotice && (
          <div className="public-solve-toast" role="status">
            <StatusGlyph tone="good" />
            <span>{transientNotice}</span>
            <button type="button" aria-label="Dismiss update" onClick={() => setTransientNotice(null)}>×</button>
          </div>
        )}
        {solveView !== 'field' && solveViewportSwitch}
        {solveView === 'field' && result
          ? (
            <SolvedFieldViewer
              viewControls={solveViewportSwitch}
              expandControl={(
                <ViewportExpandButton
                  expanded={solveViewportExpanded}
                  inline
                  onToggle={() => setSolveViewportExpanded((expanded) => !expanded)}
                />
              )}
              config={config}
              geometry={geometry}
              result={result}
              armature={armatureField}
              armatureBusy={busy === 'field'}
              armatureError={armatureFieldError}
              armatureProgress={busy === 'field' ? progress : null}
              magnetoCompositionAvailable={selectedSolver === 'magneto2d'}
              onRequestArmature={onRequestArmatureField}
            />
          )
          : (
            <ViewportChrome
              config={config}
              materials={materials}
              geometry={geometry}
              mesh={mesh}
              mode={solveView === 'mesh' && mesh ? 'mesh' : 'geometry'}
              stale={false}
              geometryStale={false}
              busy={busy}
              meshElements={meshElements}
              meshQuality={meshQuality}
              showConfigurationLabel={false}
              enableDesignIntro={false}
              isExpanded={solveViewportExpanded}
              onExpandToggle={() => setSolveViewportExpanded((expanded) => !expanded)}
              meshDisplayMode={meshDisplayMode}
              showMeshEdges={showMeshEdges}
              meshQualitySummary={meshQualitySummary}
              focusedMeshElementIndex={focusedMeshElementIndex}
              onMeshDisplayModeChange={setMeshDisplayMode}
              onShowMeshEdgesChange={setShowMeshEdges}
              onFocusedMeshElementChange={setFocusedMeshElementIndex}
            />
          )}
      </div>
      <aside className="public-run-plan" style={{ width: runPlanWidth, minWidth: runPlanWidth }}>
        <div
          className="public-run-plan-resizer"
          role="separator"
          aria-label="Resize completed results panel"
          aria-orientation="vertical"
          aria-valuemin={RUN_PLAN_MIN_WIDTH}
          aria-valuemax={maxRunPlanWidth()}
          aria-valuenow={Math.round(runPlanWidth)}
          tabIndex={0}
          title="Drag to resize results panel"
          onDoubleClick={resetRunPlanWidth}
          onKeyDown={handleRunPlanResizeKey}
          onPointerDown={handleRunPlanResizeStart}
        />
        <div ref={runPlanScrollRef} className="public-run-plan-scroll">
        <div className="mesh-panel-header"><span className="mesh-panel-header-title">Run plan</span></div>
        <details
          className="public-run-plan-section public-run-analysis"
          open={analysisDetailsOpen}
          onToggle={(event) => setAnalysisDetailsOpen(event.currentTarget.open)}
        >
          <summary className="public-run-copy">
            <span className="eyebrow">Analysis</span>
            <strong className="public-run-plan-title">{solverLabel}</strong>
            <small className="public-run-plan-caption">{solverCaption}</small>
          </summary>
          <div className="public-run-analysis-body">
            {error && <div className="error-banner" role="alert">
              <strong>{convergenceFailed ? 'Convergence failed' : 'Request stopped'}</strong>
              <span>{convergenceFailed ? errorDetails?.message : error}</span>
              {convergenceFailed && <>
                <span>No completed results were produced for this run.</span>
                <div className="public-convergence-tip"><strong>Try this next</strong><span>{convergenceTip}</span></div>
                <button type="button" disabled={busy !== null} onClick={reviewDesignForConvergence ? onBack : openConvergenceSettings}>
                  {reviewDesignForConvergence ? 'Review design' : 'Open Advanced options'}
                </button>
              </>}
              {onManageRuns && <button type="button" onClick={onManageRuns}>Manage previous runs</button>}
            </div>}
            {!error && <div className={`public-run-readiness${runReady && !solveInProgress ? ' is-ready' : ''}${solveInProgress ? ' is-running' : ''}${validationError || validation?.valid === false ? ' needs-review' : ''}`} role="status" aria-busy={solveInProgress}>
              <StatusGlyph tone={runReady && !solveInProgress ? 'good' : validationError || validation?.valid === false ? 'warning' : 'info'} />
              <div><strong>{runReadinessTitle}</strong><span>{runReadinessCopy}</span></div>
            </div>}
            <ExcitationRunPlanPreview config={config} />
            {(busy === 'mesh' || busy === 'solve') && <LiveSolveMonitor busy={busy} progress={progress} liveSamples={liveSamples} progressPercent={progressPercent} />}
            <dl className="public-quality-list">
              <div><dt>Solver</dt><dd>{solverLabel}</dd></div>
              <div><dt>Accuracy plan</dt><dd>{planLabel}</dd></div>
              <div><dt>Mesh</dt><dd>{mesh ? `${meshElements.toLocaleString()} elements` : 'Preparing…'}</dd></div>
              <div className="public-minimum-quality-row">
                <dt>Minimum quality</dt>
                <dd>
                  {mesh ? (
                    <button
                      type="button"
                      className={qualityPasses ? 'pass' : 'fail'}
                      onClick={() => {
                        setSolveView('mesh');
                        setMeshDisplayMode('quality');
                        setFocusedMeshElementIndex(meshQualitySummary.minimumElementIndex);
                      }}
                    >
                      <strong>{formatNumber(meshQualitySummary.minimum, 3)} · {qualityPasses ? 'Pass' : 'Fail'}</strong>
                      <small>Required ≥ {formatNumber(meshQualitySummary.threshold, 3)} · inspect</small>
                    </button>
                  ) : 'Pending'}
                </dd>
              </div>
              <div><dt>Corner refinement</dt><dd className={mesh && appliedRefinement ? 'pass' : ''}>{mesh ? (appliedRefinement ? 'Applied' : 'Off') : 'Pending'}</dd></div>
              <div><dt>Positions</dt><dd>{validationChecking ? 'Calculating…' : validation?.sweep_positions ?? 'Unavailable'}</dd></div>
              <div><dt>Solver estimate</dt><dd>{estimatedTimeText}</dd></div>
            </dl>
          </div>
        </details>
        {mesh && (
          <details
            className="public-run-plan-section public-mesh-quality-summary"
            aria-label="Mesh quality distribution"
            open={elementQualityDetailsOpen}
            onToggle={(event) => setElementQualityDetailsOpen(event.currentTarget.open)}
          >
            <summary className="public-mesh-quality-heading">
              <div><span className="public-section-kicker">Element quality</span><strong>{qualityPasses ? 'Solver gate passed' : 'Solver gate failed'}</strong></div>
              <span className="public-mesh-quality-meta">{weakElementCount > 0 ? `${weakElementCount} weak` : 'No weak elements'}</span>
            </summary>
            <div className="public-mesh-quality-body">
              {weakElementCount > 0 && (
                <div className="public-mesh-quality-actions">
                  <button
                    className="public-mesh-quality-action"
                    type="button"
                    onClick={() => {
                      setSolveView('mesh');
                      setMeshDisplayMode('problems');
                      setFocusedMeshElementIndex(meshQualitySummary.weakElementIndices[0] ?? null);
                    }}
                  >
                    Inspect {weakElementCount} weak
                  </button>
                </div>
              )}
              <div className="public-quality-distribution" aria-hidden="true">
                {(['good', 'acceptable', 'marginal', 'failing'] as const).map((band) => (
                  <i
                    className={band}
                    style={{ width: `${meshQualitySummary.counts[band] / qualityElementCount * 100}%` }}
                    key={band}
                  />
                ))}
              </div>
              <div className="public-quality-counts">
                <span><i className="good" />Good <strong>{meshQualitySummary.counts.good.toLocaleString()}</strong></span>
                <span><i className="acceptable" />Acceptable <strong>{meshQualitySummary.counts.acceptable.toLocaleString()}</strong></span>
                <span><i className="marginal" />Marginal <strong>{meshQualitySummary.counts.marginal.toLocaleString()}</strong></span>
                <span><i className="failing" />Failing <strong>{meshQualitySummary.counts.failing.toLocaleString()}</strong></span>
              </div>
              <p>{qualityPasses
                ? weakElementCount > 0
                  ? `${weakElementCount.toLocaleString()} marginal elements pass the solver threshold but merit inspection.`
                  : 'All elements are comfortably above the solver threshold.'
                : 'One or more elements must be improved before solving.'}</p>
            </div>
          </details>
        )}
        {result && <CompletedResultMonitor result={result} onOpenReport={onOpenReport} />}
        </div>
      </aside>
    </div>
  );
}

function ReportStage({
  result,
  config,
  designName,
  onBack,
  onOpenRunFolder,
  onDownloadRunExport,
  onOpenRunProject,
  onRerun,
}: {
  result: SolveResult;
  config: MotorConfig;
  designName: string | null;
  onBack: () => void;
  onOpenRunFolder: (savedRun: PublicSavedRun) => Promise<void>;
  onDownloadRunExport: (
    savedRun: PublicSavedRun,
    exportKind: PublicRunExportKind,
  ) => Promise<void>;
  onOpenRunProject: (savedRun: PublicSavedRun) => void;
  onRerun: (savedRun: PublicSavedRun) => void;
}) {
  const [reportMode, setReportMode] = useState<'single' | 'compare'>('single');
  const [activePlot, setActivePlot] = useState<'torque' | 'back-emf' | 'field-map'>('torque');
  const [backEmfView, setBackEmfView] = useState<'phase-neutral' | 'line-line'>('phase-neutral');
  const [exportState, setExportState] = useState<{
    action: string;
    tone: 'working' | 'success' | 'error';
    message: string;
  } | null>(null);
  const fieldPlot = result.field_line_plot;
  const sixStep = resultUsesSixStep(result, config);
  const completeLoadedCycle = result.solve_metadata.loaded_cycle_complete === true;
  const backEmfLine = lineBackEmf(result);
  const resultUsesElmer = result.solve_metadata.solver_name.toLowerCase().startsWith('elmer');
  const reportSolverLabel = resultUsesElmer ? 'Elmer FEM' : 'Magneto2D';
  const reportThdLabel = result.back_emf_harmonic_analysis
    ? 'Back EMF THD H12'
    : 'Back EMF THD legacy';
  const torqueMethod = resultUsesElmer
    ? 'Arkkio'
    : config.solve_params.torque_method === 'weighted_stress'
      ? 'WST'
      : config.solve_params.torque_method === 'contour'
        ? 'Contour MST'
        : 'Arkkio';
  const nonlinearSolver = resultUsesElmer
    ? 'Elmer nonlinear profile'
    : config.solve_params.nonlinear_solver === 'picard'
      ? 'Picard'
      : 'Newton';
  const requestedLinearSolver = resultUsesElmer
    ? 'Direct UMFPACK'
    : config.solve_params.linear_solver_preconditioner === 'direct'
      ? 'Direct Cholesky'
      : config.solve_params.linear_solver_preconditioner === 'ic0'
        ? 'IC(0) PCG'
        : 'Jacobi PCG';
  const projectName = designName ?? `Example ${config.topology} ${config.rotor.pole_count}p/${config.stator.slot_count}s`;
  const materialName = config.materials.stator_steel === config.materials.rotor_steel
    ? steelDisplayName(config, config.materials.stator_steel)
    : `${steelDisplayName(config, config.materials.stator_steel)} stator / ${steelDisplayName(config, config.materials.rotor_steel)} rotor`;
  const runSavedAction = async (
    action: string,
    workingMessage: string,
    successMessage: string,
    operation: () => Promise<void>,
  ) => {
    setExportState({ action, tone: 'working', message: workingMessage });
    try {
      await operation();
      setExportState({ action, tone: 'success', message: successMessage });
    } catch (actionError) {
      const message = actionError && typeof actionError === 'object' && 'message' in actionError
        ? String(actionError.message)
        : 'The stored run action could not be completed.';
      setExportState({ action, tone: 'error', message });
    }
  };
  const exportBusy = exportState?.tone === 'working';
  const savedRunPanel = result.saved_run ? (
    <section className="public-saved-run" aria-label="Saved solve run">
      <div>
        <span>Saved locally</span>
        <strong>{result.saved_run.path}</strong>
        <small>
          Run {result.saved_run.run_id}
          {result.saved_run.completed_at ? ` · completed ${result.saved_run.completed_at}` : ''}.
          Stored results are immutable; replay loads inputs without solving.
        </small>
      </div>
      <div className="public-saved-run-actions">
        <button type="button" disabled={exportBusy} onClick={() => void runSavedAction('pdf', 'Preparing stored PDF…', 'Downloaded the immutable PDF report.', () => onDownloadRunExport(result.saved_run!, 'pdf'))}>Download PDF</button>
        <button type="button" disabled={exportBusy} onClick={() => void runSavedAction('csv', 'Preparing stored CSV…', 'Downloaded the immutable CSV data.', () => onDownloadRunExport(result.saved_run!, 'csv'))}>Download CSV</button>
        <button type="button" disabled={exportBusy} onClick={() => void runSavedAction('folder', 'Opening result folder…', 'Opened the local result folder.', () => onOpenRunFolder(result.saved_run!))}>Open result folder</button>
        <button type="button" disabled={exportBusy} onClick={() => void runSavedAction('package', 'Preparing replay package…', 'Saved the replayable run package.', () => onDownloadRunExport(result.saved_run!, 'package'))}>Save replayable run package</button>
        <button type="button" onClick={() => onOpenRunProject(result.saved_run!)}>Open project</button>
        <button type="button" onClick={() => onRerun(result.saved_run!)}>Rerun settings</button>
      </div>
      {exportState && (
        <div
          className={`public-export-status ${exportState.tone}`}
          role={exportState.tone === 'error' ? 'alert' : 'status'}
        >
          {exportState.message}
        </div>
      )}
    </section>
  ) : null;
  return (
    <div className="results-dashboard public-report-stage">
      <div className="public-report-header"><div><span className="eyebrow">Completed analysis</span><h1>Electromagnetic performance</h1><p>Local {reportSolverLabel} result for the current motor definition.</p></div><div className="public-report-header-actions"><div className="public-report-mode" role="group" aria-label="Results view"><button type="button" className={reportMode === 'single' ? 'active' : ''} onClick={() => setReportMode('single')}>This run</button><button type="button" className={reportMode === 'compare' ? 'active' : ''} onClick={() => setReportMode('compare')}>Compare runs</button></div><button type="button" onClick={onBack}>← Back to Solve</button></div></div>
      {reportMode === 'compare' ? <PublicRunComparison currentResult={result} /> : <>
      {savedRunPanel}
      <div className="metric-grid wide">
        <article><span>Average torque{sixStep && !completeLoadedCycle ? ' · preview only' : ''}</span><strong>{formatNumber(result.summary.avg_torque_Nm)} <small>N·m</small></strong></article>
        <article><span>Torque ripple{sixStep && !completeLoadedCycle ? ' · preview only' : ''}</span><strong>{formatNumber(result.summary.torque_ripple_pct)} <small>%</small></strong></article>
        <article><span>Back EMF</span><strong>{formatNumber(result.summary.back_emf_fundamental_V)} <small>V</small></strong></article>
        <article><span>Peak tooth B</span><strong>{formatNumber(result.summary.peak_flux_density_teeth_T)} <small>T</small></strong></article>
        <article><span>Peak yoke B</span><strong>{formatNumber(result.summary.peak_flux_density_yoke_T)} <small>T</small></strong></article>
        <article><span>Torque constant</span><strong>{formatNumber(result.summary.Kt_Nm_per_A)} <small>N·m/A</small></strong></article>
        <article><span>{reportThdLabel}</span><strong>{formatNumber(result.summary.back_emf_thd_pct)} <small>%</small></strong></article>
        <article><span>Solver time</span><strong>{formatNumber(result.summary.solve_time_s, 1)} <small>s</small></strong></article>
        {result.workflow_elapsed_s != null && <article><span>Total elapsed</span><strong>{formatNumber(result.workflow_elapsed_s, 1)} <small>s</small></strong></article>}
      </div>
      <p className="public-timing-note">Solver time excludes playback and saving and may sum parallel tasks. Total elapsed measures this run in the browser through receipt of the saved result.</p>
      <div className="public-report-provenance"><span>Project</span><strong>{projectName}</strong><span>Material</span><strong>{materialName}</strong>{sixStep ? <span>Conducting phase current</span> : <span>Phase current</span>}<strong>{formatNumber(config.solve_params.current_amplitude_A)} A {sixStep ? 'plateau' : config.solve_params.current_amplitude_convention}</strong><span>Excitation</span><strong>{sixStep ? 'Ideal six-step (120°)' : 'Sinusoidal'}</strong>{sixStep && <><span>Commutation advance</span><strong>{formatNumber(result.solve_metadata.commutation_advance_deg ?? config.solve_params.commutation_advance_deg)}° electrical</strong><span>Phase connection</span><strong>Wye (MVP)</strong></>}<span>Rated speed</span><strong>{formatNumber(config.solve_params.rated_speed_rpm, 0)} rpm</strong><span>Solver</span><strong>{result.solve_metadata.solver_name}</strong><span>Torque method</span><strong>{torqueMethod}</strong><span>Nonlinear solver</span><strong>{nonlinearSolver}</strong><span>Requested linear solver</span><strong>{requestedLinearSolver}</strong><span>Mesh elements</span><strong>{result.solve_metadata.mesh_element_count.toLocaleString()}</strong><span>Rotor positions</span><strong>{result.solve_metadata.rotor_positions}</strong><span>Mesh density</span><strong>{result.solve_metadata.mesh_density || 'native'}</strong></div>
      <div className="public-report-assumptions" role="note">
        <details>
          <summary>Model assumptions</summary>
          <div className="public-report-assumptions-body">
            <span>{sixStep ? 'Ideal current excitation only — no PWM, switching ripple, Hall timing, dead time, ESC dynamics, switching loss, or startup behavior. ' : ''}This is an electromagnetic result only. {config.materials.stator_steel.startsWith('custom:') || config.materials.rotor_steel.startsWith('custom:') ? 'Custom steel uses your imported B-H data.' : 'M350-50A is an open reference B-H model;'} Supplier-specific loss data and temperature prediction are not included.</span>
            <a href="https://github.com/coilemdev/coilem/blob/main/MATERIALS.md#electrical-steel" target="_blank" rel="noreferrer">Review material provenance</a>
          </div>
        </details>
      </div>
      <div className="public-report-plot-tabs" role="tablist" aria-label="Result plots">
        <button type="button" role="tab" aria-selected={activePlot === 'torque'} className={activePlot === 'torque' ? 'active' : ''} onClick={() => setActivePlot('torque')}>Torque</button>
        <button type="button" role="tab" aria-selected={activePlot === 'back-emf'} className={activePlot === 'back-emf' ? 'active' : ''} onClick={() => setActivePlot('back-emf')}>Back EMF</button>
        {fieldPlot && <button type="button" role="tab" aria-selected={activePlot === 'field-map'} className={activePlot === 'field-map' ? 'active' : ''} onClick={() => setActivePlot('field-map')}>Field map</button>}
      </div>
      {activePlot === 'torque' && sixStep && result.phase_current_waveform
        ? <><BldcTorqueCurrentChart angles={result.torque_waveform.electrical_angle_deg} torqueNm={result.torque_waveform.torque_Nm} phaseA={result.phase_current_waveform.phase_a_A} phaseB={result.phase_current_waveform.phase_b_A} phaseC={result.phase_current_waveform.phase_c_A} commutationAdvanceDeg={result.solve_metadata.commutation_advance_deg ?? config.solve_params.commutation_advance_deg} cycleComplete={completeLoadedCycle} /><IdealSixStepCommand /></>
        : activePlot === 'torque' && <WaveformChart angles={result.torque_waveform.electrical_angle_deg} values={result.torque_waveform.torque_Nm} label="Torque waveform" unit="N·m" />}
      {activePlot === 'back-emf' && <>
        <div className="public-back-emf-view" role="group" aria-label="Back EMF voltage reference"><button type="button" className={backEmfView === 'phase-neutral' ? 'active' : ''} aria-pressed={backEmfView === 'phase-neutral'} onClick={() => setBackEmfView('phase-neutral')}>Phase-neutral</button><button type="button" className={backEmfView === 'line-line' ? 'active' : ''} aria-pressed={backEmfView === 'line-line'} onClick={() => setBackEmfView('line-line')}>Line-line</button></div>
        {backEmfView === 'phase-neutral'
          ? <WaveformChart angles={result.back_emf_waveform.electrical_angle_deg} series={[{ label: 'Phase A', values: result.back_emf_waveform.phase_a_V, color: '#f87171' }, { label: 'Phase B', values: result.back_emf_waveform.phase_b_V, color: '#4ade80' }, { label: 'Phase C', values: result.back_emf_waveform.phase_c_V, color: '#60a5fa' }]} label="Back EMF · phase-neutral" unit="V" />
          : <WaveformChart angles={result.back_emf_waveform.electrical_angle_deg} series={[{ label: 'Vab · line-line', values: backEmfLine.ab, color: '#f87171' }, { label: 'Vbc · line-line', values: backEmfLine.bc, color: '#4ade80' }, { label: 'Vca · line-line', values: backEmfLine.ca, color: '#60a5fa' }]} label="Back EMF · line-line" unit="V" />}
        {result.back_emf_harmonic_analysis && <BackEMFHarmonicSpectrum analysis={result.back_emf_harmonic_analysis} />}
      </>}
      {activePlot === 'field-map' && fieldPlot && <FieldResultPlot plot={fieldPlot} />}
      </>}
    </div>
  );
}

export function CoilEmWorkspace(props: CoilEmWorkspaceProps) {
  const reportAvailable = Boolean(props.result);
  const designHealth = useMemo(() => ({ geometry: props.geometry, mesh: props.mesh }), [props.geometry, props.mesh]);
  const [selectedComponent, setSelectedComponent] = useState<PublicMotorComponentSelection | null>(null);
  const [designViewportExpanded, setDesignViewportExpanded] = useState(false);
  const [liveEditHighlight, setLiveEditHighlight] = useState<PublicMotorComponentKind | null>(null);
  const [runHistoryOpen, setRunHistoryOpen] = useState(false);

  useEffect(() => {
    setSelectedComponent(null);
  }, [props.config.topology]);

  useEffect(() => {
    if (props.activeStep !== 'design' || props.guidedActive) {
      setDesignViewportExpanded(false);
    }
  }, [props.activeStep, props.guidedActive]);

  useEffect(() => {
    if (!designViewportExpanded) return undefined;
    const restoreOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setDesignViewportExpanded(false);
    };
    window.addEventListener('keydown', restoreOnEscape);
    return () => window.removeEventListener('keydown', restoreOnEscape);
  }, [designViewportExpanded]);

  useEffect(() => {
    if (!props.editFeedback?.affectedKind) {
      setLiveEditHighlight(null);
      return undefined;
    }
    setLiveEditHighlight(props.editFeedback.affectedKind);
    const timer = window.setTimeout(() => setLiveEditHighlight(null), 1_100);
    return () => window.clearTimeout(timer);
  }, [props.editFeedback?.id, props.editFeedback?.affectedKind]);

  return (
    <div className="public-coilem-shell">
      <CoilEmTopBar
        config={props.config}
        activeStep={props.activeStep}
        solveAvailable={!props.blankDesign}
        resultReady={reportAvailable}
        solveRunning={props.busy === 'solve'}
        connectionStatus={props.connectionStatus}
        designName={props.designName ?? null}
        onHome={props.onHome}
        onStepChange={props.onStepChange}
        onOpenDesignFile={props.onOpenDesignFile}
        onSaveDesign={props.onSaveDesign}
        onResetDesign={props.onResetDesign}
        onLoadExample={props.onLoadExample}
        onOpenHalbach={props.onOpenHalbach}
        onNewDesign={props.onNewDesign}
        runHistoryOpen={runHistoryOpen}
        onRunHistoryOpenChange={setRunHistoryOpen}
      />
      <main className="workflow-stage-shell">
        <div className="workflow-stage-content">
          {props.activeStep === 'design' && (
            <div className={`design-workspace workflow-stage-content${designViewportExpanded ? ' is-viewport-expanded' : ''}`}>
              <div className="design-workspace-main">
                <ParameterPanel
                  config={props.config}
                  materials={props.materials}
                  geometry={props.geometry}
                  geometryStale={props.geometryStale}
                  busy={props.busy}
                  error={props.error}
                  notice={props.notice}
                  blankDesign={props.blankDesign}
                  guidedActive={props.guidedActive}
                  guidedDesignSection={props.guidedDesignSection}
                  selectedComponent={selectedComponent}
                  onTopologyChange={(topology) => { setSelectedComponent(null); props.onTopologyChange(topology); }}
                  onSectionChange={props.onSectionChange}
                  onDesignSectionVisit={props.onDesignSectionVisit}
                  onConvertProjectSteelToM350={props.onConvertProjectSteelToM350}
                  onImportSteel={props.onImportSteel}
                  onReset={() => { setSelectedComponent(null); props.onReset(); }}
                  onRefreshGeometry={props.onRefreshGeometry}
                  onClearComponent={() => setSelectedComponent(null)}
                  onNext={() => props.onStepChange('solve')}
                />
                {props.blankDesign ? (
                  <section className="viewport viewport-cad viewport-cad-grid public-motor-viewport public-blank-design" aria-label="Blank design canvas">
                    <div className="public-blank-design-copy">
                      <span>New Design</span>
                      <strong>Start with a design parameter</strong>
                      <p>The motor preview will appear after your first change.</p>
                    </div>
                  </section>
                ) : (
                  <ViewportChrome
                    config={props.config}
                    materials={props.materials}
                    geometry={props.geometry}
                    mesh={props.mesh}
                    mode="geometry"
                    stale={props.geometryStale}
                    geometryStale={props.geometryStale}
                    busy={props.busy}
                    meshElements={props.meshElements}
                    meshQuality={props.meshQuality}
                    isExpanded={designViewportExpanded}
                    onExpandToggle={props.guidedActive ? undefined : () => setDesignViewportExpanded((expanded) => !expanded)}
                    selectedComponent={selectedComponent}
                    highlightComponentKind={liveEditHighlight}
                    onComponentSelect={setSelectedComponent}
                  />
                )}
              </div>
              <div className="design-workspace-health"><div className="design-workspace-health-scroll"><HealthPanel config={props.config} error={props.error} geometry={designHealth.geometry} mesh={designHealth.mesh} geometryStale={props.geometryStale} blankDesign={props.blankDesign} /></div></div>
              {props.editFeedback && (
                <div className="public-design-edit-toast" role="status" aria-live="polite">
                  <span className="public-design-edit-toast-icon" aria-hidden="true">✓</span>
                  <span className="public-design-edit-toast-copy">
                    <strong>{props.editFeedback.message}</strong>
                    {props.editFeedback.consequence && <small>{props.editFeedback.consequence}</small>}
                  </span>
                  {props.onUndoDesignEdit && <button type="button" className="public-design-edit-undo" onClick={props.onUndoDesignEdit}>Undo</button>}
                  {props.onDismissDesignEdit && <button type="button" className="public-design-edit-dismiss" aria-label="Dismiss edit confirmation" onClick={props.onDismissDesignEdit}>×</button>}
                </div>
              )}
            </div>
          )}
          {props.activeStep === 'solve' && <SolveStage config={props.config} materials={props.materials} geometry={props.geometry} mesh={props.mesh} validation={props.validation} validationChecking={props.validationChecking} validationError={props.validationError} result={props.result} armatureField={props.armatureField} armatureFieldError={props.armatureFieldError} progress={props.progress} liveSamples={props.liveSamples} busy={props.busy} error={props.error} errorDetails={props.errorDetails} notice={props.notice} progressPercent={props.progressPercent} meshElements={props.meshElements} meshQuality={props.meshQuality} selectedSolver={props.selectedSolver} elmerCapability={props.elmerCapability} onBack={() => props.onStepChange('design')} onOpenReport={() => props.onStepChange('report')} onGenerateMesh={props.onGenerateMesh} onStartSolve={props.onStartSolve} onCancelSolve={props.onCancelSolve} onRequestArmatureField={props.onRequestArmatureField} onMeshSettingChange={props.onMeshSettingChange} onSolvePlanChange={props.onSolvePlanChange} onCustomSweepChange={props.onCustomSweepChange} onSolveSettingChange={props.onSolveSettingChange} onSolverChange={props.onSolverChange} onManageRuns={needsRunStorageRecovery(props.error) ? () => setRunHistoryOpen(true) : undefined} />}
          {props.activeStep === 'report' && props.result && <ReportStage result={props.result} config={props.config} designName={props.designName ?? null} onBack={() => props.onStepChange('solve')} onOpenRunFolder={props.onOpenRunFolder} onDownloadRunExport={props.onDownloadRunExport} onOpenRunProject={props.onOpenRunProject} onRerun={props.onRerun} />}
        </div>
      </main>
    </div>
  );
}
