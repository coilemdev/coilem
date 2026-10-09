import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  cancelPublicSolve,
  downloadPublicRunExport,
  generatePublicMesh,
  generatePublicPreview,
  getPublicHealth,
  getPublicMaterials,
  loadPublicRun,
  openPublicRunFolder,
  streamPublicArmatureField,
  streamPublicSolve,
  validatePublicSolve,
  type PublicApiError,
  type PublicJson,
  type PublicMotorConfig,
  type PublicRunExportKind,
  type PublicSolveProgress,
  type PublicSolveRequest,
} from './api';
import {
  CoilEmWorkspace,
  CoilEmTopBar,
  type PublicBusyAction,
  type PublicConnectionStatus,
  type PublicDesignEditFeedback,
  type PublicEditableSection,
  type PublicParameterSection,
  type PublicWorkflowStep,
} from './CoilEmWorkspace';
import { PublicGuidedSetup } from './GuidedSetup';
import { repairGuidedSection } from './guidedConfigRepair';
import { PublicLanding } from './PublicLanding';
import { HalbachWorkspace } from './halbach/HalbachWorkspace';
import {
  changeTopologyPreservingAirgap,
  magneticAirgapMm,
} from './motorAirgap';
import { startPublicBackendMonitor } from './backendMonitor';
import { createExcitationDrafts, switchExcitationMode } from './excitationDrafts';
// Lazy: the tutorials area carries the shared catalog and learning.css, so a
// static import puts ~15 kB gzip of lesson chrome on the landing page's critical
// path for visitors who never open a lesson.
const PublicTutorials = lazy(() =>
  import('./tutorials/PublicTutorials').then((m) => ({ default: m.PublicTutorials })));
import {
  pathForTutorialsView,
  tutorialsViewFromPathname,
  type PublicTutorialsView,
} from './tutorials/lessonRoutes';
import type {
  LearningLessonHeaderProgress,
  LearningLessonStage,
} from '../components/tutorials/lessonStage';
import { designFileBaseName, parseDesignFile, saveDesignFileAs } from './designFile';
import { projectMaterialCatalog, type CustomSteel, type SteelTarget } from './customSteel';
import { createPublicExampleDesign, type PublicExampleId } from './exampleDesigns';
import {
  cloneDefaultConfig,
  applyPublicSolverSettings,
  type GeometryPreview,
  type MaterialCatalog,
  type MeshPreview,
  type MotorConfig,
  type PublicArmatureFieldComposition,
  type PublicFieldFrameDescriptor,
  type PublicMotorComponentKind,
  type PublicElmerCapability,
  type PublicSavedRun,
  type PublicSolverId,
  type SolveResult,
  type SolveValidation,
} from './model';
import {
  applyPublicCustomSweep,
  applyPublicSolvePreset,
  capturePublicPresetSweep,
  PUBLIC_DEFAULT_PRESET_SWEEP,
  PUBLIC_SOLVE_PLAN_MESH_DENSITY,
  type PublicSolvePreset,
  type PublicSweepSampling,
} from './solvePlan';

const FALLBACK_MATERIALS: MaterialCatalog = {
  steels: ['M350-50A'],
  magnet_grades: ['N42'],
  conductors: ['copper'],
};

const ELMER_CHECKING: PublicElmerCapability = {
  feature_enabled: false,
  available: false,
  qualified: false,
  adapter_ready: false,
  reason: 'Checking this workstation for Elmer 26.2…',
};

const ELMER_API_UNAVAILABLE: PublicElmerCapability = {
  feature_enabled: false,
  available: false,
  qualified: false,
  adapter_ready: false,
  reason: 'The local API is unavailable, so Elmer could not be detected.',
};

function elmerCapabilityIsReady(capability: PublicElmerCapability): boolean {
  return capability.feature_enabled
    && capability.available
    && capability.qualified
    && capability.adapter_ready;
}

function sameElmerCapability(
  current: PublicElmerCapability,
  next: PublicElmerCapability,
): boolean {
  return current.feature_enabled === next.feature_enabled
    && current.available === next.available
    && current.qualified === next.qualified
    && current.adapter_ready === next.adapter_ready
    && current.gmsh_available === next.gmsh_available
    && current.meshio_available === next.meshio_available
    && current.solver_version === next.solver_version
    && current.grid_version === next.grid_version
    && current.reason === next.reason;
}

function elmerCapabilityFromHealth(health: PublicJson): PublicElmerCapability {
  const capabilities = health.capabilities;
  if (!capabilities || typeof capabilities !== 'object') {
    return { feature_enabled: false, available: false, qualified: false, adapter_ready: false, reason: 'Elmer capability was not reported by the local API.' };
  }
  const elmer = (capabilities as PublicJson).elmer;
  if (!elmer || typeof elmer !== 'object') {
    return { feature_enabled: false, available: false, qualified: false, adapter_ready: false, reason: 'Elmer capability was not reported by the local API.' };
  }
  const payload = elmer as PublicJson;
  return {
    feature_enabled: payload.feature_enabled === true,
    available: payload.available === true,
    qualified: payload.qualified === true,
    adapter_ready: payload.adapter_ready === true,
    gmsh_available: payload.gmsh_available === true,
    meshio_available: payload.meshio_available === true,
    solver_version: typeof payload.solver_version === 'string' ? payload.solver_version : null,
    grid_version: typeof payload.grid_version === 'string' ? payload.grid_version : null,
    reason: typeof payload.reason === 'string' ? payload.reason : null,
  };
}

const LESSON_ONE_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 1,
  lessonCount: 10,
  title: 'Follow the flux',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'air', label: 'Open air', complete: false, available: false },
    { id: 'steel', label: 'Add steel', complete: false, available: false },
    { id: 'pair', label: 'Two magnets', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_TWO_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 2,
  lessonCount: 10,
  title: 'Close the Loop',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'solve', label: 'Airgap lab', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_THREE_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 3,
  lessonCount: 10,
  title: 'Make a Field with Current',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'direction', label: 'Direction', complete: false, available: false },
    { id: 'scale', label: 'Scale', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_FOUR_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 4,
  lessonCount: 10,
  title: 'When Iron Saturates',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'low', label: 'Low field', complete: false, available: false },
    { id: 'knee', label: 'Knee', complete: false, available: false },
    { id: 'saturation', label: 'Saturation', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_FIVE_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 5,
  lessonCount: 10,
  title: 'Turn Field into Force',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'positive', label: '+8 A', complete: false, available: false },
    { id: 'reverse', label: 'Reverse', complete: false, available: false },
    { id: 'scale', label: 'Double', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const CHAPTER_ONE_CAPSTONE_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  eyebrow: 'Chapter 1 capstone',
  lessonNumber: 5,
  lessonCount: 5,
  title: 'Make It Move',
  currentStepId: 'build',
  steps: [
    { id: 'build', label: 'Build', complete: false, available: true },
    { id: 'move', label: 'Make it move', complete: false, available: false },
    { id: 'strengthen', label: 'Make it stronger', complete: false, available: false },
    { id: 'reveal', label: 'See it work', complete: false, available: false },
  ],
};

const LESSON_SIX_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 6,
  lessonCount: 10,
  title: 'Give the Rotor Something to Chase',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'release', label: 'Align', complete: false, available: false },
    { id: 'chase', label: 'New start', complete: false, available: false },
    { id: 'dc', label: 'Reverse DC', complete: false, available: false },
    { id: 'ac', label: 'One-phase AC', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_SEVEN_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 7,
  lessonCount: 10,
  title: 'Make the Field Rotate',
  currentStepId: 'predict',
  steps: [
    { id: 'predict', label: 'Predict', complete: false, available: true },
    { id: 'field', label: 'Rotate B', complete: false, available: false },
    { id: 'motor', label: 'Play cycle', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_EIGHT_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 8,
  lessonCount: 10,
  title: 'Three Wires, One Rotating Field',
  currentStepId: 'connect',
  steps: [
    { id: 'connect', label: 'Connect Wye', complete: false, available: true },
    { id: 'spin', label: 'Spin field', complete: false, available: true },
    { id: 'stress', label: 'Stress drive', complete: false, available: false },
    { id: 'check', label: 'Check', complete: false, available: false },
  ],
};

const LESSON_NINE_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 9,
  lessonCount: 10,
  title: 'Inside a Motor’s Magnetic Circuit',
  currentStepId: 'design',
  steps: [
    { id: 'design', label: 'Design', complete: false, available: true },
    { id: 'solve', label: 'Solve', complete: false, available: true },
  ],
};

const LESSON_TEN_HEADER_PLACEHOLDER: LearningLessonHeaderProgress = {
  lessonNumber: 10,
  lessonCount: 10,
  title: 'BEMF & Voltage Headroom',
  currentStepId: 'design',
  steps: [
    { id: 'design', label: 'Design', complete: false, available: true },
    { id: 'mesh', label: 'Spin Motor', complete: false, available: true },
    { id: 'solve', label: 'Voltage Limit', complete: false, available: false },
  ],
};

const SOLVE_PLAN_LABEL = {
  quick: 'Preview',
  standard: 'Standard',
  fine: 'High accuracy',
} as const;

const DESIGN_FIELD_LABELS: Record<string, string> = {
  OD_mm: 'Outer diameter',
  ID_mm: 'Inner diameter',
  slot_count: 'Slot count',
  stack_length_mm: 'Stack length',
  slot_opening_mm: 'Bore tooth width',
  tooth_width_mm: 'Yoke tooth width',
  yoke_thickness_mm: 'Yoke thickness',
  tooth_shoe_enabled: 'Tooth shoe',
  tooth_shoe_height_mm: 'Shoe height',
  tooth_shoe_overhang_mm: 'Shoe overhang',
  pole_count: 'Pole count',
  magnet_thickness_mm: 'Magnet thickness',
  magnet_width_mm: 'Magnet width',
  magnet_embrace: 'Magnet coverage',
  ipm_topology: 'IPM rotor layout',
  v_angle_deg: 'V angle',
  v_depth_mm: 'V depth',
  type: 'Winding type',
  turns_per_coil: 'Turns per coil',
  parallel_paths: 'Parallel paths',
  current_amplitude_A: 'Phase current',
  stator_steel: 'Stator steel',
  rotor_steel: 'Rotor steel',
  magnet_grade: 'Magnet grade',
  conductor: 'Conductor',
};

const DESIGN_FIELD_UNITS: Record<string, string> = {
  OD_mm: 'mm',
  ID_mm: 'mm',
  stack_length_mm: 'mm',
  slot_opening_mm: 'mm',
  tooth_width_mm: 'mm',
  yoke_thickness_mm: 'mm',
  tooth_shoe_height_mm: 'mm',
  tooth_shoe_overhang_mm: 'mm / side',
  magnet_thickness_mm: 'mm',
  magnet_width_mm: 'mm',
  v_angle_deg: '°',
  v_depth_mm: 'mm',
  current_amplitude_A: 'A rms',
};

interface DesignEditState extends PublicDesignEditFeedback {
  previousConfig: MotorConfig;
  previousBlankDesign: boolean;
}

function slotsPerPolePerPhase(config: MotorConfig): number {
  return config.stator.slot_count / Math.max(1, config.rotor.pole_count * 3);
}

function editableValue(config: MotorConfig, section: PublicEditableSection, field: string): unknown {
  return (config[section] as unknown as Record<string, unknown>)[field];
}

function formatEditValue(field: string, value: unknown): string {
  if (field === 'ipm_topology' && typeof value === 'string') {
    return value === 'v_shape' ? 'V-shape' : 'Flat / buried';
  }
  if (field === 'magnet_embrace' && typeof value === 'number') {
    return `${Math.round(value * 100)}%`;
  }
  if (typeof value === 'boolean') return value ? 'On' : 'Off';
  if (typeof value === 'number') {
    const formatted = Number.isInteger(value) ? String(value) : Number(value.toFixed(2)).toString();
    return `${formatted}${DESIGN_FIELD_UNITS[field] ? ` ${DESIGN_FIELD_UNITS[field]}` : ''}`;
  }
  return String(value);
}

function affectedComponentKind(
  section: PublicEditableSection,
  field: string,
): PublicMotorComponentKind | null {
  if (section === 'stator') return 'stator';
  if (section === 'winding' || section === 'solve_params') return 'winding';
  if (section === 'rotor') {
    return /magnet|v_angle|v_depth|ipm_topology/.test(field) ? 'magnet' : 'rotor';
  }
  if (section === 'materials') {
    if (field === 'stator_steel') return 'stator';
    if (field === 'rotor_steel') return 'rotor';
    if (field === 'magnet_grade') return 'magnet';
    if (field === 'conductor') return 'winding';
  }
  return null;
}

function describeDesignEdit(
  previous: MotorConfig,
  next: MotorConfig,
  section: PublicEditableSection,
  field: string,
): Pick<PublicDesignEditFeedback, 'message' | 'consequence' | 'affectedKind'> {
  const label = DESIGN_FIELD_LABELS[field] ?? field.replace(/_/g, ' ');
  const previousAirgap = magneticAirgapMm(previous);
  const nextAirgap = magneticAirgapMm(next);
  const previousQ = slotsPerPolePerPhase(previous);
  const nextQ = slotsPerPolePerPhase(next);
  let consequence: string | null = null;

  if (Math.abs(previousAirgap - nextAirgap) > 1e-6) {
    consequence = `Airgap ${previousAirgap.toFixed(2)} → ${nextAirgap.toFixed(2)} mm`;
  } else if (Math.abs(previousQ - nextQ) > 1e-6) {
    consequence = `Slots per pole per phase ${previousQ.toFixed(2)} → ${nextQ.toFixed(2)}`;
  } else {
    const previousValue = editableValue(previous, section, field);
    const nextValue = editableValue(next, section, field);
    consequence = `${formatEditValue(field, previousValue)} → ${formatEditValue(field, nextValue)}`;
  }

  return {
    message: `${label} updated`,
    consequence,
    affectedKind: affectedComponentKind(section, field),
  };
}

const GUIDED_IPM_LAYOUT_PRESETS: Record<
  MotorConfig['rotor']['ipm_topology'],
  Partial<MotorConfig['rotor']>
> = {
  flat_buried: {
    magnet_width_mm: 31.4,
    v_angle_deg: 60,
    v_depth_mm: 8,
    inner_web_thickness_mm: 2,
  },
  v_shape: {
    // Validated against the public backend for the guided 200 mm, 8p/12s
    // starter. Apply the pocket geometry atomically with the layout so the UI
    // never sends the invalid intermediate combination of a shallow V and the
    // wide surface-magnet slab.
    magnet_width_mm: 28,
    v_angle_deg: 40,
    v_depth_mm: 30,
    inner_web_thickness_mm: 6,
  },
};

function asPublicConfig(config: MotorConfig): PublicMotorConfig {
  const thdAnalysis = config.solve_params.solve_quality === 'standard'
    || config.solve_params.solve_quality === 'fine';
  return {
    ...applyPublicSolverSettings(config),
    solve_options: {
      ...config.solve_options,
      cogging_torque: false,
      thd_analysis: thdAnalysis,
    },
  } as unknown as PublicMotorConfig;
}

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const issue = error as { message?: unknown; suggestion?: unknown };
    if (issue.message) {
      return [String(issue.message), issue.suggestion ? String(issue.suggestion) : '']
        .filter(Boolean)
        .join(' ');
    }
  }
  return 'The local request could not be completed.';
}

export function App() {
  const [showLanding, setShowLanding] = useState(true);
  const [showHalbachWorkspace, setShowHalbachWorkspace] = useState(false);
  // The tutorials area is its own top-level surface. It is deliberately separate
  // state rather than a value folded into showLanding or PublicWorkflowStep,
  // because test-public-ui-contract.mjs pins both of those verbatim (:294, :52).
  const [tutorialsView, setTutorialsView] = useState<PublicTutorialsView | null>(
    () => (typeof window === 'undefined' ? null : tutorialsViewFromPathname(window.location.pathname)),
  );
  const [tutorialsStage, setTutorialsStage] = useState<LearningLessonStage>('design');
  const [tutorialHeaderProgress, setTutorialHeaderProgress] = useState<LearningLessonHeaderProgress | null>(null);
  const [config, setConfig] = useState<MotorConfig>(() => cloneDefaultConfig());
  const [designName, setDesignName] = useState<string | null>(null);
  const [blankDesign, setBlankDesign] = useState(false);
  const [materials, setMaterials] = useState<MaterialCatalog>(FALLBACK_MATERIALS);
  const [geometry, setGeometry] = useState<GeometryPreview | null>(null);
  const [mesh, setMesh] = useState<MeshPreview | null>(null);
  const [validation, setValidation] = useState<SolveValidation | null>(null);
  const [validationChecking, setValidationChecking] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [result, setResult] = useState<SolveResult | null>(null);
  const [armatureField, setArmatureField] = useState<PublicArmatureFieldComposition | null>(null);
  const [armatureFieldError, setArmatureFieldError] = useState<string | null>(null);
  const [progress, setProgress] = useState<PublicSolveProgress | null>(null);
  const [liveSamples, setLiveSamples] = useState<PublicSolveProgress[]>([]);
  const [view, setView] = useState<PublicWorkflowStep>('design');
  const [guidedActive, setGuidedActive] = useState(false);
  const [guidedDesignSection, setGuidedDesignSection] = useState<PublicParameterSection | null>(null);
  const [busy, setBusy] = useState<PublicBusyAction>(null);
  const [connectionStatus, setConnectionStatus] = useState<PublicConnectionStatus>('checking');
  const [selectedSolver, setSelectedSolver] = useState<PublicSolverId>('magneto2d');
  const [elmerCapability, setElmerCapability] = useState<PublicElmerCapability>(ELMER_CHECKING);
  const [geometryStale, setGeometryStale] = useState(true);
  const [previewNetworkFailed, setPreviewNetworkFailed] = useState(false);
  const [backendRecovery, setBackendRecovery] = useState(0);
  const previewRecoveryAttempt = useRef(0);
  // Keep API error codes for recovery UI; flattening to text loses the cause.
  const [errorDetails, setErrorDetails] = useState<PublicApiError | null>(null);
  const error = errorDetails ? errorMessage(errorDetails) : null;
  const setError = useCallback((value: string | PublicApiError | null) => {
    setErrorDetails(typeof value === 'string'
      ? { error_code: 'LOCAL_REQUEST_FAILED', message: value }
      : value);
  }, []);
  const [notice, setNotice] = useState<string | null>(null);
  const [editFeedback, setEditFeedback] = useState<DesignEditState | null>(null);
  const solveController = useRef<AbortController | null>(null);
  const armatureFieldController = useRef<AbortController | null>(null);
  const solveRequestId = useRef(0);
  const armatureFieldRequestId = useRef(0);
  const solveResultBeforeRun = useRef<{ value: SolveResult | null } | null>(null);
  const previewRequestId = useRef(0);
  const meshRequestId = useRef(0);
  const validationRequestId = useRef(0);
  const editFeedbackId = useRef(0);
  const guidedVisitedSectionsRef = useRef(new Set<PublicParameterSection>());
  const presetSweepRef = useRef<PublicSweepSampling>({ ...PUBLIC_DEFAULT_PRESET_SWEEP });
  const excitationDraftRef = useRef(createExcitationDrafts(config, cloneDefaultConfig()));

  const rememberPresetSweep = useCallback((nextConfig: MotorConfig) => {
    // All project replacement paths use this hook; ordinary edits keep drafts.
    excitationDraftRef.current = createExcitationDrafts(nextConfig, cloneDefaultConfig());
    presetSweepRef.current = nextConfig.solve_params.solve_quality === 'custom'
      ? { ...PUBLIC_DEFAULT_PRESET_SWEEP }
      : capturePublicPresetSweep(nextConfig);
  }, []);

  useEffect(() => {
    if (!editFeedback) return undefined;
    const timer = window.setTimeout(() => setEditFeedback(null), 8_000);
    return () => window.clearTimeout(timer);
  }, [editFeedback?.id]);

  const restoreSolveResultBeforeRun = useCallback((): boolean => {
    const snapshot = solveResultBeforeRun.current;
    if (!snapshot) return false;
    solveResultBeforeRun.current = null;
    setResult(snapshot.value);
    return snapshot.value !== null;
  }, []);

  useEffect(() => {
    if (result) return;
    armatureFieldRequestId.current += 1;
    armatureFieldController.current?.abort();
    armatureFieldController.current = null;
    setArmatureField(null);
    setArmatureFieldError(null);
    setProgress(null);
    setBusy((current) => current === 'field' ? null : current);
  }, [result]);

  const resetComputedState = useCallback(() => {
    validationRequestId.current += 1;
    setMesh(null);
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice(null);
    setView('design');
  }, []);

  const invalidateGeometryPreview = useCallback(() => {
    // Invalidate immediately, not when the debounced replacement request starts.
    // Otherwise an older in-flight response can land during the debounce window,
    // mark itself current, and leave its advisory text attached to the new inputs
    // if the replacement preview then fails.
    previewRequestId.current += 1;
    setGeometryStale(true);
    setPreviewNetworkFailed(false);
    setBusy((current) => current === 'geometry' ? null : current);
  }, []);

  const prepareMesh = useCallback(async (
    nextConfig: MotorConfig,
    successNotice = 'Native Gmsh mesh prepared. Inspect it here or run the analysis.',
  ): Promise<MeshPreview | null> => {
    const requestId = ++meshRequestId.current;
    setBusy('mesh');
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice(null);
    setView('solve');
    try {
      const payload = await generatePublicMesh(asPublicConfig(nextConfig));
      if (requestId !== meshRequestId.current) return null;
      const preparedMesh = payload as unknown as MeshPreview;
      setMesh(preparedMesh);
      setConnectionStatus('online');
      setNotice(successNotice);
      return preparedMesh;
    } catch (requestError) {
      if (requestId !== meshRequestId.current) return null;
      setError(errorMessage(requestError));
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
      return null;
    } finally {
      if (requestId === meshRequestId.current) setBusy(null);
    }
  }, []);

  const updateSection = useCallback((
    section: PublicEditableSection,
    field: string,
    value: unknown,
    visitedSection?: PublicParameterSection,
  ) => {
    // An edit is explicit ownership of the section, even if the submitted
    // value equals its current value. Never let a later coach stop silently
    // repair a section the user has already touched.
    if (guidedActive && visitedSection) {
      guidedVisitedSectionsRef.current.add(visitedSection);
    }
    const selectedIpmLayout = section === 'rotor'
      && field === 'ipm_topology'
      && (value === 'flat_buried' || value === 'v_shape')
      ? value
      : null;
    const enablingToothShoe = section === 'stator'
      && field === 'tooth_shoe_enabled'
      && value === true;
    const nextConfig: MotorConfig = selectedIpmLayout
      ? {
        ...config,
        rotor: {
          ...config.rotor,
          ...GUIDED_IPM_LAYOUT_PRESETS[selectedIpmLayout],
          ipm_topology: selectedIpmLayout,
        },
      }
      : enablingToothShoe
        ? {
          ...config,
          stator: {
            ...config.stator,
            tooth_shoe_enabled: true,
            tooth_shoe_height_mm: config.stator.tooth_shoe_height_mm ?? 1.5,
            // Legacy/no-shoe files can carry a 2 mm opening with no explicit
            // shoe values. Clamp the default before enabling so the public
            // toggle can never create overlapping adjacent shoe tips.
            tooth_shoe_overhang_mm: Math.min(
              config.stator.tooth_shoe_overhang_mm ?? 1.5,
              Math.max(0, (config.stator.slot_opening_mm - 0.1) / 2),
            ),
          },
        }
      : {
        ...config,
        [section]: { ...config[section], [field]: value },
      };
    if (Object.is(editableValue(config, section, field), editableValue(nextConfig, section, field))) return;
    setConfig(nextConfig);
    setEditFeedback({
      id: ++editFeedbackId.current,
      previousConfig: config,
      previousBlankDesign: blankDesign,
      ...describeDesignEdit(config, nextConfig, section, field),
    });
    setBlankDesign(false);
    if (section !== 'solve_params') invalidateGeometryPreview();
    resetComputedState();
  }, [blankDesign, config, guidedActive, invalidateGeometryPreview, resetComputedState]);

  const convertProjectSteelToM350 = useCallback(() => {
    setConfig((current) => ({
      ...current,
      materials: {
        ...current.materials,
        stator_steel: 'M350-50A',
        rotor_steel: 'M350-50A',
      },
    }));
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
    setNotice('Converted this working copy to M350-50A. The steel model and predicted results can change; save a new .coilem file to preserve the conversion.');
  }, [invalidateGeometryPreview, resetComputedState]);

  const importSteel = useCallback((material: CustomSteel, target: SteelTarget) => {
    if (Object.keys(config.materials.custom_steels ?? {}).length >= 16 && !config.materials.custom_steels?.[material.id]) {
      setError('This project already contains 16 custom steels. Start a new project to import more.');
      return;
    }
    setConfig((current) => ({ ...current, materials: {
      ...current.materials,
      custom_steels: { ...current.materials.custom_steels, [material.id]: material },
      ...(target !== 'rotor' ? { stator_steel: material.id } : {}),
      ...(target !== 'stator' ? { rotor_steel: material.id } : {}),
    } }));
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
    setNotice(`${material.name} imported and assigned. Save the design to keep its curve with the project.`);
  }, [config.materials.custom_steels, invalidateGeometryPreview, resetComputedState]);

  const updateTopology = useCallback((topology: MotorConfig['topology']) => {
    if (topology === config.topology) return;
    let nextConfig = changeTopologyPreservingAirgap(config, topology);
    if (topology !== 'SPM' && nextConfig.solve_params.excitation_mode === 'ideal_six_step_120') {
      const sine = excitationDraftRef.current.sinusoidal;
      nextConfig = {
        ...nextConfig,
        solve_params: {
          ...nextConfig.solve_params,
          excitation_mode: 'sinusoidal',
          current_amplitude_A: sine.currentAmplitudeA,
          current_amplitude_convention: sine.currentConvention,
          current_angle_deg: sine.currentAngleDeg,
          commutation_advance_deg: 0,
        },
      };
    }
    const previousAirgapMm = magneticAirgapMm(config);
    const nextAirgapMm = magneticAirgapMm(nextConfig);
    const airgapConsequence = Math.abs(previousAirgapMm - nextAirgapMm) < 1e-6
      ? `airgap held at ${nextAirgapMm.toFixed(2)} mm`
      : `airgap adjusted ${previousAirgapMm.toFixed(2)} → ${nextAirgapMm.toFixed(2)} mm to keep the geometry valid`;
    setConfig(nextConfig);
    setEditFeedback({
      id: ++editFeedbackId.current,
      previousConfig: config,
      previousBlankDesign: blankDesign,
      message: 'Motor topology updated',
      consequence: `${config.topology} → ${topology} · ${airgapConsequence}`,
      affectedKind: 'rotor',
    });
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
  }, [blankDesign, config, invalidateGeometryPreview, resetComputedState]);

  const undoLastDesignEdit = useCallback(() => {
    if (!editFeedback) return;
    setConfig(editFeedback.previousConfig);
    setBlankDesign(editFeedback.previousBlankDesign);
    setEditFeedback(null);
    invalidateGeometryPreview();
    if (editFeedback.previousBlankDesign) {
      setGeometry(null);
      setGeometryStale(false);
    }
    resetComputedState();
  }, [editFeedback, invalidateGeometryPreview, resetComputedState]);

  const updateMeshSetting = useCallback((
    field: 'mesh_density' | 'corner_refinement',
    value: MotorConfig['solve_params']['mesh_density'] | boolean,
  ) => {
    validationRequestId.current += 1;
    setConfig((current) => ({
      ...current,
      solve_params: { ...current.solve_params, [field]: value },
    }));
    setMesh(null);
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice('Mesh settings changed. Prepare a new mesh to apply them.');
  }, []);

  const updateSolveSetting = useCallback((
    field: 'current_amplitude_A' | 'rated_speed_rpm' | 'nonlinear_solver' | 'current_amplitude_convention' | 'current_angle_deg' | 'excitation_mode' | 'commutation_advance_deg',
    value: MotorConfig['solve_params']['nonlinear_solver'] | MotorConfig['solve_params']['current_amplitude_convention'] | MotorConfig['solve_params']['excitation_mode'] | number,
  ) => {
    validationRequestId.current += 1;
    if (field === 'excitation_mode' && value === 'ideal_six_step_120') {
      setSelectedSolver('magneto2d');
    }
    setConfig((current) => {
      if (field === 'excitation_mode') {
        const switched = switchExcitationMode(
          current, value as MotorConfig['solve_params']['excitation_mode'], excitationDraftRef.current,
        );
        excitationDraftRef.current = switched.drafts;
        return switched.config;
      }
      return {
        ...current,
        solve_params: {
          ...current.solve_params,
          [field]: value,
        },
      };
    });
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice('Analysis settings changed. Updating the run estimate.');
  }, []);

  const selectSolver = useCallback((solver: PublicSolverId) => {
    if (solver === 'elmer' && !elmerCapabilityIsReady(elmerCapability)) {
      setNotice(elmerCapability.reason || 'Install the qualified Elmer 26.2 runtime to enable this solver.');
      return;
    }
    validationRequestId.current += 1;
    setSelectedSolver(solver);
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice(solver === 'elmer'
      ? `Elmer FEM ${elmerCapability.solver_version || '26.2'} selected. The displayed mesh is a preview; Elmer remeshes each rotor position.`
      : 'Magneto2D selected. Updating the run estimate.');
  }, [elmerCapability]);

  useEffect(() => {
    if (connectionStatus !== 'online' || elmerCapability.feature_enabled || selectedSolver !== 'elmer') return;
    validationRequestId.current += 1;
    setSelectedSolver('magneto2d');
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice('Elmer is disabled for this launch. Magneto2D is selected.');
  }, [connectionStatus, elmerCapability.feature_enabled, selectedSolver]);

  const updateSolvePlan = useCallback((solvePlan: PublicSolvePreset) => {
    validationRequestId.current += 1;
    const presetSweep = config.solve_params.solve_quality === 'custom'
      ? presetSweepRef.current
      : capturePublicPresetSweep(config);
    presetSweepRef.current = presetSweep;
    const planMeshDensity = PUBLIC_SOLVE_PLAN_MESH_DENSITY[solvePlan];
    const meshLabel = planMeshDensity === 'normal' ? 'medium' : planMeshDensity;
    const nextConfig = applyPublicSolvePreset(config, solvePlan, presetSweep);
    setConfig(nextConfig);
    setMesh(null);
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    void prepareMesh(
      nextConfig,
      `${SOLVE_PLAN_LABEL[solvePlan]} plan ready with a ${meshLabel} mesh.`,
    );
  }, [config, prepareMesh]);

  const updateCustomSweep = useCallback((stepDeg: number) => {
    validationRequestId.current += 1;
    if (config.solve_params.solve_quality !== 'custom') {
      presetSweepRef.current = capturePublicPresetSweep(config);
    }
    setConfig(applyPublicCustomSweep(config, stepDeg));
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice('Custom full-cycle sweep selected. Updating the run estimate.');
  }, [config]);

  const refreshGeometry = useCallback(async (nextConfig: MotorConfig, clearExistingError = true) => {
    const requestId = ++previewRequestId.current;
    setGeometryStale(true);
    setPreviewNetworkFailed(false);
    // Debounced geometry previews are background reads. They must not replace
    // an active mesh operation or disable a solve-plan button during a click.
    if (clearExistingError) {
      setBusy((current) => current ?? 'geometry');
      setError(null);
    }
    try {
      const payload = await generatePublicPreview(asPublicConfig(nextConfig));
      if (requestId !== previewRequestId.current) return;
      setGeometry(payload as unknown as GeometryPreview);
      setGeometryStale(false);
      setConnectionStatus('online');
      setError(null);
    } catch (requestError) {
      if (requestId !== previewRequestId.current) return;
      setPreviewNetworkFailed(requestError instanceof TypeError);
      setError(errorMessage(requestError));
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
    } finally {
      if (requestId === previewRequestId.current) {
        setBusy((current) => current === 'geometry' ? null : current);
      }
    }
  }, []);

  const refreshSolveValidation = useCallback(async (nextConfig: MotorConfig) => {
    const requestId = ++validationRequestId.current;
    setValidationChecking(true);
    setValidationError(null);
    try {
      const request: PublicSolveRequest = {
        config: asPublicConfig(nextConfig),
        solver: selectedSolver,
        project_name: designName
          ?? `coilEM-${nextConfig.topology.toLowerCase()}-${nextConfig.rotor.pole_count}p${nextConfig.stator.slot_count}s`,
      };
      const checked = await validatePublicSolve(request) as unknown as SolveValidation;
      if (requestId !== validationRequestId.current) return;
      setValidation(checked);
      setConnectionStatus('online');
    } catch (requestError) {
      if (requestId !== validationRequestId.current) return;
      setValidation(null);
      setValidationError(errorMessage(requestError));
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
    } finally {
      if (requestId === validationRequestId.current) setValidationChecking(false);
    }
  }, [designName, selectedSolver]);

  useEffect(() => {
    let active = true;
    let materialsLoaded = false;
    let materialsRequestInFlight = false;

    const refreshMaterials = () => {
      if (materialsLoaded || materialsRequestInFlight) return;
      materialsRequestInFlight = true;
      void getPublicMaterials()
        .then((catalog) => {
          if (!active) return;
          materialsLoaded = true;
          setMaterials(catalog as unknown as MaterialCatalog);
        })
        .catch(() => {
          // Health owns connection status. Keep the safe fallback catalog and
          // retry this independent request after the next successful probe.
        })
        .finally(() => {
          materialsRequestInFlight = false;
        });
    };

    const stopBackendMonitor = startPublicBackendMonitor({
      probe: getPublicHealth,
      onOnline: (health) => {
        const nextElmerCapability = elmerCapabilityFromHealth(health);
        setConnectionStatus('online');
        setElmerCapability((current) => (
          sameElmerCapability(current, nextElmerCapability) ? current : nextElmerCapability
        ));
        refreshMaterials();
      },
      onOffline: () => {
        setConnectionStatus('offline');
        setElmerCapability(ELMER_API_UNAVAILABLE);
      },
      onReconnect: () => setBackendRecovery((current) => current + 1),
    });

    return () => {
      active = false;
      stopBackendMonitor();
    };
  }, []);

  const geometryConfig = useMemo(
    () => config,
    [config.topology, config.stator, config.rotor, config.winding, config.materials],
  );

  useEffect(() => {
    if (blankDesign) return undefined;
    const timer = window.setTimeout(() => {
      void refreshGeometry(geometryConfig, false);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [blankDesign, geometryConfig, refreshGeometry]);

  useEffect(() => {
    // Retry only transport failures, once per reconnect, with the latest draft.
    // Never interrupt another operation or replay a solve on backend recovery.
    if (blankDesign || !previewNetworkFailed || busy !== null
      || backendRecovery <= previewRecoveryAttempt.current) return;
    previewRecoveryAttempt.current = backendRecovery;
    void refreshGeometry(geometryConfig);
  }, [backendRecovery, blankDesign, busy, geometryConfig, previewNetworkFailed, refreshGeometry]);

  useEffect(() => {
    if (view !== 'solve' || busy !== null) return undefined;
    const timer = window.setTimeout(() => {
      void refreshSolveValidation(config);
    }, 140);
    return () => window.clearTimeout(timer);
  }, [busy, config, refreshSolveValidation, view]);

  const generateMesh = (): Promise<MeshPreview | null> => prepareMesh(config);

  const handleSolveProgress = useCallback((nextProgress: PublicSolveProgress) => {
    setProgress(nextProgress);
    const hasAngle = typeof nextProgress.angle_deg === 'number' && Number.isFinite(nextProgress.angle_deg);
    const hasTorque = typeof nextProgress.torque_Nm === 'number' && Number.isFinite(nextProgress.torque_Nm);
    const hasBackEmf = [nextProgress.phase_a_V, nextProgress.phase_b_V, nextProgress.phase_c_V]
      .every((value) => typeof value === 'number' && Number.isFinite(value));
    const isLoadedSweepSample = ['magneto2d_sweep', 'torque_sweep'].includes(nextProgress.stage)
      && hasAngle
      && (hasTorque || hasBackEmf);
    if (!isLoadedSweepSample) return;

    setLiveSamples((current) => {
      const matchingIndex = current.findIndex((sample) => sample.angle_deg === nextProgress.angle_deg);
      if (matchingIndex < 0) return [...current, nextProgress].sort((left, right) => (left.angle_deg ?? 0) - (right.angle_deg ?? 0));
      const updated = [...current];
      updated[matchingIndex] = { ...updated[matchingIndex], ...nextProgress };
      return updated;
    });
  }, []);

  const startSolve = async () => {
    let preparedMesh = mesh;
    if (!preparedMesh) {
      preparedMesh = await generateMesh();
      if (!preparedMesh) return;
    }
    const requestId = ++solveRequestId.current;
    const workflowStartedAt = performance.now();
    solveResultBeforeRun.current = { value: result };
    setBusy('solve');
    setView('solve');
    setResult(null);
    setLiveSamples([]);
    setProgress({ position: 0, total: 1, elapsed_s: 0, stage: 'Validating' });
    setError(null);
    setNotice(null);
    setValidationChecking(true);
    setValidationError(null);
    try {
      const solveRequest: PublicSolveRequest = {
        config: asPublicConfig(config),
        solver: selectedSolver,
        project_name: designName
          ?? `coilEM-${config.topology.toLowerCase()}-${config.rotor.pole_count}p${config.stator.slot_count}s`,
        ...(selectedSolver === 'magneto2d' && preparedMesh.solve_mesh_key
          ? { solve_mesh_key: preparedMesh.solve_mesh_key }
          : {}),
      };
      const checked = await validatePublicSolve(solveRequest) as unknown as SolveValidation;
      if (requestId !== solveRequestId.current) return;
      setValidation(checked);
      setValidationChecking(false);
      setConnectionStatus('online');
      if (!checked.valid) {
        const retainedPreviousResult = restoreSolveResultBeforeRun();
        setError(errorMessage(checked.errors[0] || new Error('The motor configuration is not valid.')));
        if (retainedPreviousResult) {
          setNotice('The new request was not valid. The previous completed result is still available.');
        }
        setProgress(null);
        setBusy(null);
        return;
      }
      solveController.current = streamPublicSolve(solveRequest, {
        onProgress: (nextProgress) => {
          if (requestId === solveRequestId.current) handleSolveProgress({
            ...nextProgress,
            elapsed_s: (performance.now() - workflowStartedAt) / 1000,
          });
        },
        onComplete: (payload) => {
          if (requestId !== solveRequestId.current) return;
          solveResultBeforeRun.current = null;
          setResult({
            ...payload,
            workflow_elapsed_s: (performance.now() - workflowStartedAt) / 1000,
          } as unknown as SolveResult);
          setView('solve');
          setNotice('Analysis complete. Inspect the solved field here or open the full report.');
          setBusy(null);
          solveController.current = null;
        },
        onError: (streamError: PublicApiError) => {
          if (requestId !== solveRequestId.current) return;
          const retainedPreviousResult = restoreSolveResultBeforeRun();
          setError(streamError);
          if (retainedPreviousResult) {
            setNotice('The new analysis stopped. The previous completed result is still available.');
          }
          if (streamError.error_code === 'LOCAL_API_UNREACHABLE') setConnectionStatus('offline');
          setBusy(null);
          solveController.current = null;
        },
      });
    } catch (requestError) {
      if (requestId !== solveRequestId.current) return;
      setValidationChecking(false);
      const retainedPreviousResult = restoreSolveResultBeforeRun();
      setError(errorMessage(requestError));
      if (retainedPreviousResult) {
        setNotice('The new analysis stopped. The previous completed result is still available.');
      }
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
      setBusy(null);
    }
  };

  const loadArmatureField = () => {
    if (armatureField || busy !== null) return;
    if (!mesh) {
      setArmatureFieldError('Prepare and solve the motor before requesting a stator-only field.');
      return;
    }
    const requestId = ++armatureFieldRequestId.current;
    setBusy('field');
    setArmatureField(null);
    setArmatureFieldError(null);
    setProgress(null);
    setError(null);
    setNotice('Computing the exact stator-current field with permanent-magnet remanence set to zero.');
    const request: PublicSolveRequest = mesh.solve_mesh_key
      ? { config: asPublicConfig(config), solve_mesh_key: mesh.solve_mesh_key, solver: 'magneto2d' }
      : { config: asPublicConfig(config), solver: 'magneto2d' };
    armatureFieldController.current = streamPublicArmatureField(request, {
      onProgress: (nextProgress) => {
        if (requestId !== armatureFieldRequestId.current) return;
        setProgress(nextProgress);
        const candidate = nextProgress.field_frame as unknown;
        if (!candidate || typeof candidate !== 'object') return;
        const descriptor = candidate as PublicFieldFrameDescriptor;
        const artifactId = descriptor.field_frame_artifact?.artifact_id;
        if (typeof artifactId !== 'string' || !artifactId) return;
        setArmatureField((current) => {
          const priorFrames = current?.frames ?? [];
          const frames = [
            ...priorFrames.filter((frame) => (
              frame.field_frame_artifact.artifact_id !== artifactId
              && Math.abs(frame.angle_deg - descriptor.angle_deg) > 1e-9
            )),
            descriptor,
          ].sort((left, right) => left.angle_deg - right.angle_deg);
          return {
            schema_version: 'coilem.public_field_composition.armature.v1',
            source: 'magneto2d_exact_br_zero',
            cache_hit: false,
            elapsed_s: nextProgress.elapsed_s,
            frame_count: frames.length,
            frames,
          };
        });
      },
      onComplete: (payload) => {
        if (requestId !== armatureFieldRequestId.current) return;
        setArmatureField(payload as unknown as PublicArmatureFieldComposition);
        setProgress(null);
        setConnectionStatus('online');
        setNotice('Exact stator-current field ready. The cached Br = 0 sweep follows the solved rotor positions.');
        setBusy(null);
        armatureFieldController.current = null;
      },
      onError: (streamError) => {
        if (requestId !== armatureFieldRequestId.current) return;
        const message = errorMessage(streamError);
        setArmatureField(null);
        setArmatureFieldError(message);
        setProgress(null);
        setError(message);
        if (streamError.error_code === 'LOCAL_API_UNREACHABLE') setConnectionStatus('offline');
        setBusy(null);
        armatureFieldController.current = null;
      },
    });
  };

  const cancelSolve = async () => {
    solveRequestId.current += 1;
    solveController.current?.abort();
    solveController.current = null;
    const retainedPreviousResult = restoreSolveResultBeforeRun();
    setError(null);
    try {
      await cancelPublicSolve();
      setConnectionStatus('online');
      setNotice(retainedPreviousResult
        ? 'Analysis canceled. The previous completed result is still available.'
        : 'Analysis canceled. The motor definition is unchanged.');
    } catch (requestError) {
      setError(errorMessage(requestError));
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
    } finally {
      setBusy(null);
      setProgress(null);
    }
  };

  const reset = () => {
    const next = cloneDefaultConfig();
    rememberPresetSweep(next);
    setConfig(next);
    setEditFeedback(null);
    invalidateGeometryPreview();
    resetComputedState();
  };

  const resetDesign = () => {
    reset();
    setBlankDesign(false);
    setDesignName(null);
    setNotice('Design reset to the example motor.');
  };

  const startNewDesign = () => {
    solveRequestId.current += 1;
    meshRequestId.current += 1;
    armatureFieldRequestId.current += 1;
    solveController.current?.abort();
    solveController.current = null;
    armatureFieldController.current?.abort();
    armatureFieldController.current = null;
    solveResultBeforeRun.current = null;
    previewRequestId.current += 1;
    const nextConfig = cloneDefaultConfig();
    rememberPresetSweep(nextConfig);
    setConfig(nextConfig);
    setDesignName('New Design');
    setBlankDesign(true);
    setGeometry(null);
    setGeometryStale(false);
    setEditFeedback(null);
    resetComputedState();
    setGuidedActive(false);
    setGuidedDesignSection(null);
    setShowLanding(false);
    setTutorialsView(null);
    setView('design');
    setNotice('Blank design ready. Change a design parameter to create its first preview.');
    if (typeof window !== 'undefined' && window.location.pathname !== '/') {
      window.history.pushState({}, '', '/');
    }
  };

  const openDesignFile = async (file: File) => {
    try {
      const parsed = parseDesignFile(await file.text());
      rememberPresetSweep(parsed.config);
      setConfig(parsed.config);
      setEditFeedback(null);
      setDesignName(parsed.name ?? designFileBaseName(file.name));
      setBlankDesign(false);
      invalidateGeometryPreview();
      resetComputedState();
      setShowLanding(false);
      setView('design');
      const loadedNotice = parsed.fromFuture
        ? `Loaded ${file.name} — saved by a newer schema, unrecognized settings were ignored.`
        : `Loaded design file ${file.name}.`;
      setNotice([loadedNotice, parsed.solverSettingsNotice].filter(Boolean).join(' '));
    } catch (error) {
      setNotice(`Could not open design file — ${error instanceof Error ? error.message : 'unrecognized format'}.`);
    }
  };

  const loadExampleDesign = (exampleId: PublicExampleId) => {
    const example = createPublicExampleDesign(exampleId);
    rememberPresetSweep(example.config);
    setConfig(example.config);
    setEditFeedback(null);
    setDesignName(example.name);
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
    setGuidedActive(false);
    setGuidedDesignSection(null);
    setShowLanding(false);
    setTutorialsView(null);
    setView('design');
    setNotice(`Loaded ${example.name}.`);
    if (typeof window !== 'undefined' && window.location.pathname !== '/') {
      window.history.pushState({}, '', '/');
    }
  };

  const saveDesign = () => {
    void saveDesignFileAs(
      config,
      designName ?? `coilem-${config.topology.toLowerCase()}-${config.rotor.pole_count}p${config.stator.slot_count}s`,
    );
  };

  const openSavedRunFolder = async (savedRun: PublicSavedRun) => {
    try {
      await openPublicRunFolder(savedRun.project_slug, savedRun.run_id);
      setNotice(`Opened the saved run folder at ${savedRun.path}.`);
    } catch (requestError) {
      setNotice(errorMessage(requestError));
      throw requestError;
    }
  };

  const downloadSavedRunExport = async (
    savedRun: PublicSavedRun,
    exportKind: PublicRunExportKind,
  ) => {
    try {
      await downloadPublicRunExport(
        savedRun.project_slug,
        savedRun.run_id,
        exportKind,
      );
      setNotice(exportKind === 'package'
        ? 'Saved the replayable run package.'
        : `Downloaded the stored ${exportKind.toUpperCase()} report.`);
    } catch (requestError) {
      setNotice(errorMessage(requestError));
      throw requestError;
    }
  };

  const restoreSavedRun = async (
    savedRun: PublicSavedRun,
    destination: 'design' | 'solve',
  ) => {
    try {
      const payload = await loadPublicRun(savedRun.project_slug, savedRun.run_id);
      const integrity = payload.integrity as { valid?: unknown } | undefined;
      if (integrity?.valid !== true) {
        throw new Error('The saved run failed its integrity check and cannot be replayed.');
      }
      const project = payload.project;
      if (!project || typeof project !== 'object') {
        throw new Error('The saved run does not contain a replayable project.');
      }
      const parsed = parseDesignFile(JSON.stringify(project));
      const requestPayload = payload.request;
      const submittedRequest = requestPayload && typeof requestPayload === 'object'
        ? (requestPayload as PublicJson).submitted
        : null;
      const storedSolver = submittedRequest && typeof submittedRequest === 'object'
        ? (submittedRequest as PublicJson).solver
        : null;
      const replaySolver: PublicSolverId = storedSolver === 'elmer' ? 'elmer' : 'magneto2d';
      rememberPresetSweep(parsed.config);
      setConfig(parsed.config);
      setSelectedSolver(
        replaySolver === 'elmer' && elmerCapabilityIsReady(elmerCapability)
          ? 'elmer'
          : 'magneto2d',
      );
      setEditFeedback(null);
      setDesignName(parsed.name);
      setBlankDesign(false);
      invalidateGeometryPreview();
      resetComputedState();
      setShowLanding(false);
      setView(destination);
      const restoredNotice = destination === 'solve'
        ? replaySolver === 'elmer' && !elmerCapabilityIsReady(elmerCapability)
          ? 'Saved Elmer settings restored, but Elmer is not currently available. Magneto2D remains selected.'
          : `Saved ${replaySolver === 'elmer' ? 'Elmer' : 'Magneto2D'} settings restored. Prepare the mesh, review them, then explicitly start a new analysis.`
        : 'Saved project opened. Its stored result remains immutable; edit or solve explicitly.';
      setNotice([restoredNotice, parsed.solverSettingsNotice].filter(Boolean).join(' '));
    } catch (requestError) {
      setNotice(errorMessage(requestError));
    }
  };

  const openWorkspace = (guided: boolean) => {
    if (blankDesign) {
      const nextConfig = cloneDefaultConfig();
      rememberPresetSweep(nextConfig);
      setConfig(nextConfig);
      setEditFeedback(null);
      setDesignName(null);
      invalidateGeometryPreview();
      resetComputedState();
    }
    setBlankDesign(false);
    if (guided) {
      // Begin from the valid 8-pole/12-slot starter. If an upstream choice
      // invalidates later defaults, the coach repairs only the still-unseen
      // section immediately before the user reaches it.
      const nextConfig = cloneDefaultConfig();
      rememberPresetSweep(nextConfig);
      setConfig(nextConfig);
      setEditFeedback(null);
      setDesignName(null);
      invalidateGeometryPreview();
      resetComputedState();
    }
    setShowLanding(false);
    setView('design');
    guidedVisitedSectionsRef.current = new Set();
    setGuidedDesignSection(null);
    setGuidedActive(guided);
    setNotice(null);
  };

  const prepareGuidedDesignSection = useCallback((
    section: PublicParameterSection,
  ): string | null => {
    if (!guidedActive || guidedVisitedSectionsRef.current.has(section)) return null;
    guidedVisitedSectionsRef.current.add(section);
    const repaired = repairGuidedSection(config, section);
    if (repaired.adjustments.length === 0) return null;
    setConfig(repaired.config);
    setEditFeedback(null);
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
    const summary = repaired.adjustments
      .map((adjustment) => `${adjustment.label} → ${adjustment.next ?? 'automatic'}`)
      .join(' · ');
    return `Adjusted upcoming defaults to fit your earlier choices: ${summary}.`;
  }, [config, guidedActive, invalidateGeometryPreview, resetComputedState]);

  const visitGuidedDesignSection = useCallback((section: PublicParameterSection) => {
    const adjustment = prepareGuidedDesignSection(section);
    if (adjustment) setNotice(adjustment);
  }, [prepareGuidedDesignSection]);

  const revealGuidedDesignSection = useCallback((section: PublicParameterSection | null) => {
    if (!section) {
      setGuidedDesignSection(null);
      return null;
    }
    const adjustment = prepareGuidedDesignSection(section);
    setGuidedDesignSection(section);
    return adjustment;
  }, [prepareGuidedDesignSection]);

  // Tutorials get real URLs so a lesson can be linked to and the browser back
  // button behaves. Paths match the private app's table, so a link shared out of
  // either build resolves in the other.
  const navigateTutorials = useCallback((next: PublicTutorialsView) => {
    setTutorialsView(next);
    setTutorialsStage('design');
    setNotice(null);
    const path = pathForTutorialsView(next);
    if (typeof window !== 'undefined' && window.location.pathname !== path) {
      window.history.pushState({}, '', path);
    }
  }, []);

  const exitTutorials = useCallback(() => {
    setTutorialsView(null);
    setTutorialsStage('design');
    if (typeof window !== 'undefined' && tutorialsViewFromPathname(window.location.pathname)) {
      window.history.pushState({}, '', '/');
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const handlePopState = () => {
      const next = tutorialsViewFromPathname(window.location.pathname);
      setTutorialsView(next);
      if (next) setTutorialsStage('design');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const changeWorkflowStep = (step: PublicWorkflowStep) => {
    setView(step);
    if (step === 'solve' && !mesh && busy !== 'mesh' && busy !== 'solve') {
      void generateMesh();
    }
  };

  const progressPercent = useMemo(() => {
    if (!progress || progress.total <= 0) return 0;
    return Math.min(100, Math.max(0, (progress.position / progress.total) * 100));
  }, [progress]);

  const meshElements = Number(mesh?.mesh_info.num_triangles || mesh?.triangles.length || 0);
  const meshQuality = Number(mesh?.mesh_qa.min_triangle_quality || 0);

  if (tutorialsView) {
    // Keep the shell and top bar, as the private app does across its lesson routes.
    // Without them the tutorials area loses the backend connection indicator, so a
    // perfectly healthy local API looks like it is not running.
    return (
      <div className="public-coilem-shell is-tutorials">
        <CoilEmTopBar
          config={config}
          activeStep="design"
          solveAvailable={false}
          resultReady={Boolean(result)}
          solveRunning={false}
          connectionStatus={connectionStatus}
          designName={designName}
          onHome={exitTutorials}
          onStepChange={(step) => {
            exitTutorials();
            setShowLanding(false);
            setView(step);
          }}
          onOpenDesignFile={(file) => void openDesignFile(file)}
          onSaveDesign={saveDesign}
          onResetDesign={resetDesign}
          onLoadExample={loadExampleDesign}
          onOpenHalbach={() => setShowHalbachWorkspace(true)}
          onNewDesign={startNewDesign}
          tutorialCatalog={tutorialsView === 'catalog'}
          tutorialProgress={tutorialsView === 'lesson-1'
            ? tutorialHeaderProgress?.lessonNumber === 1
              ? tutorialHeaderProgress
              : LESSON_ONE_HEADER_PLACEHOLDER
            : tutorialsView === 'lesson-2'
              ? tutorialHeaderProgress?.lessonNumber === 2
                ? tutorialHeaderProgress
                : LESSON_TWO_HEADER_PLACEHOLDER
              : tutorialsView === 'lesson-3'
                ? tutorialHeaderProgress?.lessonNumber === 3
                  ? tutorialHeaderProgress
                  : LESSON_THREE_HEADER_PLACEHOLDER
                : tutorialsView === 'lesson-4'
                  ? tutorialHeaderProgress?.lessonNumber === 4
                    ? tutorialHeaderProgress
                    : LESSON_FOUR_HEADER_PLACEHOLDER
                  : tutorialsView === 'lesson-5'
                    ? tutorialHeaderProgress?.lessonNumber === 5
                      ? tutorialHeaderProgress
                      : LESSON_FIVE_HEADER_PLACEHOLDER
                    : tutorialsView === 'chapter-1-capstone'
                      ? tutorialHeaderProgress?.eyebrow === 'Chapter 1 capstone'
                        ? tutorialHeaderProgress
                        : CHAPTER_ONE_CAPSTONE_HEADER_PLACEHOLDER
                      : tutorialsView === 'lesson-6'
                      ? tutorialHeaderProgress?.lessonNumber === 6
                        ? tutorialHeaderProgress
                        : LESSON_SIX_HEADER_PLACEHOLDER
                      : tutorialsView === 'lesson-7'
                        ? tutorialHeaderProgress?.lessonNumber === 7
                          ? tutorialHeaderProgress
                          : LESSON_SEVEN_HEADER_PLACEHOLDER
                        : tutorialsView === 'lesson-8'
                          ? tutorialHeaderProgress?.lessonNumber === 8
                            ? tutorialHeaderProgress
                            : LESSON_EIGHT_HEADER_PLACEHOLDER
                          : tutorialsView === 'lesson-9'
                            ? tutorialHeaderProgress?.lessonNumber === 9
                              ? tutorialHeaderProgress
                              : LESSON_NINE_HEADER_PLACEHOLDER
                            : tutorialsView === 'lesson-10'
                              ? tutorialHeaderProgress?.lessonNumber === 10
                                ? tutorialHeaderProgress
                                : LESSON_TEN_HEADER_PLACEHOLDER
                              : null}
          onTutorialCatalog={() => navigateTutorials('catalog')}
        />
        <Suspense fallback={<main className="template-selector-overlay public-landing" />}>
          <PublicTutorials
            view={tutorialsView}
            stage={tutorialsStage}
            onViewChange={navigateTutorials}
            onStageChange={setTutorialsStage}
            onHeaderProgressChange={setTutorialHeaderProgress}
            onExit={exitTutorials}
          />
        </Suspense>
      </div>
    );
  }

  if (showHalbachWorkspace) {
    return (
      <HalbachWorkspace
        connectionStatus={connectionStatus}
        onHome={() => {
          setShowHalbachWorkspace(false);
          setShowLanding(true);
        }}
      />
    );
  }

  if (showLanding) {
    return (
      <div className="public-coilem-shell">
        <CoilEmTopBar
          config={config}
          activeStep="design"
          solveAvailable={false}
          resultReady={Boolean(result)}
          solveRunning={false}
          connectionStatus={connectionStatus}
          designName={designName}
          onHome={() => undefined}
          onStepChange={(step) => {
            setShowLanding(false);
            setView(step);
          }}
          onOpenDesignFile={(file) => void openDesignFile(file)}
          onSaveDesign={saveDesign}
          onResetDesign={resetDesign}
          onLoadExample={loadExampleDesign}
          onOpenHalbach={() => setShowHalbachWorkspace(true)}
          onNewDesign={startNewDesign}
          workflowDisabled
        />
        <PublicLanding
          onStartGuided={() => openWorkspace(true)}
          onUseExample={() => openWorkspace(false)}
          onOpenTutorials={() => navigateTutorials('catalog')}
          onOpenHalbach={() => setShowHalbachWorkspace(true)}
        />
      </div>
    );
  }

  return (
    <>
    <CoilEmWorkspace
      config={config}
      materials={projectMaterialCatalog(materials, config)}
      geometry={geometry}
      mesh={mesh}
      validation={validation}
      validationChecking={validationChecking}
      validationError={validationError}
      result={result}
      armatureField={armatureField}
      armatureFieldError={armatureFieldError}
      progress={progress}
      liveSamples={liveSamples}
      activeStep={view}
      guidedActive={guidedActive}
      guidedDesignSection={guidedDesignSection}
      busy={busy}
      connectionStatus={connectionStatus}
      selectedSolver={selectedSolver}
      elmerCapability={elmerCapability}
      geometryStale={geometryStale}
      error={error}
      errorDetails={errorDetails}
      notice={notice}
      progressPercent={progressPercent}
      meshElements={meshElements}
      meshQuality={meshQuality}
      designName={designName}
      blankDesign={blankDesign}
      editFeedback={editFeedback}
      onOpenDesignFile={(file) => void openDesignFile(file)}
      onSaveDesign={saveDesign}
      onResetDesign={resetDesign}
      onLoadExample={loadExampleDesign}
      onOpenHalbach={() => setShowHalbachWorkspace(true)}
      onNewDesign={startNewDesign}
      onHome={() => {
        setGuidedActive(false);
        setGuidedDesignSection(null);
        setShowLanding(true);
      }}
      onStepChange={changeWorkflowStep}
      onTopologyChange={updateTopology}
      onSectionChange={updateSection}
      onDesignSectionVisit={visitGuidedDesignSection}
      onConvertProjectSteelToM350={convertProjectSteelToM350}
      onImportSteel={importSteel}
      onMeshSettingChange={updateMeshSetting}
      onSolvePlanChange={updateSolvePlan}
      onCustomSweepChange={updateCustomSweep}
      onSolveSettingChange={updateSolveSetting}
      onSolverChange={selectSolver}
      onReset={reset}
      onRefreshGeometry={() => void refreshGeometry(config)}
      onGenerateMesh={() => void generateMesh()}
      onStartSolve={() => void startSolve()}
      onCancelSolve={() => void cancelSolve()}
      onRequestArmatureField={() => void loadArmatureField()}
      onOpenRunFolder={openSavedRunFolder}
      onDownloadRunExport={downloadSavedRunExport}
      onOpenRunProject={(savedRun) => void restoreSavedRun(savedRun, 'design')}
      onRerun={(savedRun) => void restoreSavedRun(savedRun, 'solve')}
      onUndoDesignEdit={undoLastDesignEdit}
      onDismissDesignEdit={() => setEditFeedback(null)}
    />
    {guidedActive && (
      <PublicGuidedSetup
        activeStep={view}
        topology={config.topology}
        resultReady={Boolean(result)}
        busy={busy !== null}
        onWorkflowStepChange={changeWorkflowStep}
        onDesignSectionChange={revealGuidedDesignSection}
        onStartSolve={() => void startSolve()}
        onExit={() => {
          setGuidedActive(false);
          setGuidedDesignSection(null);
        }}
      />
    )}
    </>
  );
}
