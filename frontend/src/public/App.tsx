import { RunSetupControl } from './RunSetupControl';
import { BUILTIN_SOLVE_PROFILES } from './builtinSolveProfiles';
import { newProfileDocument, parseProfileDocument, profileProvenance } from './solveProfiles';
import { loadProfileDocument, storeProfileDocument } from './profileStorage';
import { savedResultPlayback } from './savedRunPlayback';
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
  type SolveSetupSection,
  type PublicWorkflowStep,
} from './CoilEmWorkspace';
import { PublicGuidedSetup } from './GuidedSetup';
import type { NewDesignEntrySnapshot } from './newDesignEntry';
import { coilsPerPhase, parallelPathsDividing, windingForType } from './guidedConfigRepair';
import { designErrorText } from './designErrors';
import { windingLayerWording } from './toothCoils';
import { PublicLanding } from './PublicLanding';
import { HalbachWorkspace } from './halbach/HalbachWorkspace';
import {
  changeTopologyPreservingAirgap,
  magneticAirgapMm,
} from './motorAirgap';
import { startPublicBackendMonitor } from './backendMonitor';
import { createExcitationDrafts, switchExcitationMode } from './excitationDrafts';
import type { TorqueSpeedAnalysisSettings, WireSpec } from './performance';
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
import { asPublicConfig } from './publicRequest';
import { setAnalysisOption, type AnalysisKey } from './analysisOptions';
import { projectMaterialCatalog, type CustomSteel, type SteelTarget } from './customSteel';
import { resetDesignViewMemory } from './designViewMemory';
import { acceptDesignSection, designPartsComplete, fitPoleMagnets, fitUnbuiltParts, newBuildConfig, revealEditedPart, type BuiltParts, type DesignIssue } from './progressiveDesign';
import { createPublicExampleDesign, type PublicExampleId } from './exampleDesigns';
import {
  cloneDefaultConfig,
  type GeometryPreview,
  type MaterialCatalog,
  type MeshPreview,
  type MotorConfig,
  type PublicArmatureFieldComposition,
  type PublicFieldFrameDescriptor,
  type PublicMotorComponentKind,
  type PublicElmerCapability,
  type PublicExperimentalRotorCapability,
  type PublicSavedRun,
  type PublicSolverId,
  type RotorLayout,
  type SolveResult,
  type SolveValidation,
} from './model';
import {
  applyPublicCustomSweep,
  applyPublicSolvePreset,
  capturePublicPresetSweep,
  PUBLIC_DEFAULT_PRESET_SWEEP,
  type PublicSolvePreset,
  type PublicSweepSampling,
} from './solvePlan';
import { EMPTY_PUBLIC_SOLVE_PROGRESS_BAR, nextPublicSolveProgressBar, withFirstPublicSolveFieldFrame } from './solveProgress';

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

const EXPERIMENTAL_ROTORS_OFF: PublicExperimentalRotorCapability = {
  enabled: false,
  families: [],
  switch: 'COILEM_EXPERIMENTAL_ROTORS',
};

function experimentalRotorsFromHealth(health: PublicJson): PublicExperimentalRotorCapability {
  const capabilities = health.capabilities;
  const payload = capabilities && typeof capabilities === 'object'
    ? (capabilities as PublicJson).experimental_rotors
    : null;
  if (!payload || typeof payload !== 'object') return EXPERIMENTAL_ROTORS_OFF;
  const data = payload as PublicJson;
  const enabled = data.enabled === true;
  return {
    enabled,
    families: enabled && Array.isArray(data.families)
      ? data.families.filter((family): family is 'pyleecan_holem50' => family === 'pyleecan_holem50')
      : [],
    switch: typeof data.switch === 'string' ? data.switch : EXPERIMENTAL_ROTORS_OFF.switch,
  };
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
  layers: 'Winding layers',
  turns_per_coil: 'Turns per coil',
  parallel_paths: 'Parallel paths',
  wire: 'Wire',
  winding_temperature_C: 'Winding temperature',
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
  winding_temperature_C: '°C',
};

interface DesignEditState extends PublicDesignEditFeedback {
  previousConfig: MotorConfig;
  previousBlankDesign: boolean;
  previousNewDesignParts?: BuiltParts | null;
}

function slotsPerPolePerPhase(config: MotorConfig): number {
  return config.stator.slot_count / Math.max(1, config.rotor.pole_count * 3);
}

function editableValue(config: MotorConfig, section: PublicEditableSection, field: string): unknown {
  return (config[section] as unknown as Record<string, unknown>)[field];
}

function formatEditValue(field: string, value: unknown): string {
  if (field === 'ipm_topology' && typeof value === 'string') {
    if (value === 'pyleecan_holem50') return 'HoleM50 (experimental)';
    return value === 'v_shape' ? 'V-shape' : 'Flat / buried';
  }
  if (field === 'magnet_embrace' && typeof value === 'number') {
    return `${Math.round(value * 100)}%`;
  }
  if (field === 'wire') {
    if (!value || typeof value !== 'object') return 'derived from the slot';
    const wire = value as WireSpec;
    return `${wire.strands_in_hand ?? 1} × ${wire.wire_bare_diameter_mm} mm`;
  }
  if (field === 'winding_temperature_C' && value == null) return '20 °C';
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
  // A layer change keeps the layout, so the previous design names both counts (#102).
  const layerWording = section === 'winding' && field === 'layers'
    ? windingLayerWording(previous.stator.slot_count, previous.rotor.pole_count, previous.winding.type)
    : null;
  const label = layerWording?.label ?? DESIGN_FIELD_LABELS[field] ?? field.replace(/_/g, ' ');
  const previousAirgap = magneticAirgapMm(previous);
  const nextAirgap = magneticAirgapMm(next);
  const previousQ = slotsPerPolePerPhase(previous);
  const nextQ = slotsPerPolePerPhase(next);
  let consequence: string | null = null;

  if (Math.abs(previousAirgap - nextAirgap) > 1e-6) {
    consequence = `Airgap ${previousAirgap.toFixed(2)} → ${nextAirgap.toFixed(2)} mm`;
  } else if (Math.abs(previousQ - nextQ) > 1e-6) {
    consequence = `Slots per pole per phase ${previousQ.toFixed(2)} → ${nextQ.toFixed(2)}`;
  } else if (layerWording) {
    const layerName = (layers: number) => layerWording.choice[layers === 2 ? 2 : 1];
    consequence = `${layerName(previous.winding.layers)} → ${layerName(next.winding.layers)}`;
  } else {
    const previousValue = editableValue(previous, section, field);
    const nextValue = editableValue(next, section, field);
    consequence = `${formatEditValue(field, previousValue)} → ${formatEditValue(field, nextValue)}`;
  }
  // A switch to a q >= 1 concentrated layout drops a second layer it cannot wind.
  if (
    section === 'winding'
    && field !== 'layers'
    && previous.winding.layers !== next.winding.layers
  ) {
    consequence = `${consequence} · layers ${previous.winding.layers} → ${next.winding.layers}`;
  }
  if (
    section === 'winding'
    && field !== 'parallel_paths'
    && previous.winding.parallel_paths !== next.winding.parallel_paths
  ) {
    consequence = `${consequence} · parallel paths ${previous.winding.parallel_paths} → ${next.winding.parallel_paths}`;
  }

  return {
    message: `${label} updated`,
    consequence,
    affectedKind: affectedComponentKind(section, field),
  };
}

const GUIDED_IPM_LAYOUT_PRESETS: Record<
  'flat_buried' | 'v_shape',
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

/** Keep an API error whole, so its field can be worded and placed; anything else becomes text. */
function requestFailure(error: unknown): PublicApiError | string {
  if (
    error
    && typeof error === 'object'
    && typeof (error as PublicApiError).error_code === 'string'
    && typeof (error as PublicApiError).message === 'string'
  ) {
    return error as PublicApiError;
  }
  return errorMessage(error);
}

export function App({ initialNewDesign = false }: { initialNewDesign?: boolean }) {
  const [showLanding, setShowLanding] = useState(!initialNewDesign);
  const [showHalbachWorkspace, setShowHalbachWorkspace] = useState(false);
  // The tutorials area is its own top-level surface. It is deliberately separate
  // state rather than a value folded into showLanding or PublicWorkflowStep,
  // because test-public-ui-contract.mjs pins both of those verbatim (:294, :52).
  const [tutorialsView, setTutorialsView] = useState<PublicTutorialsView | null>(
    () => (typeof window === 'undefined' ? null : tutorialsViewFromPathname(window.location.pathname)),
  );
  const [tutorialsStage, setTutorialsStage] = useState<LearningLessonStage>('design');
  const [tutorialHeaderProgress, setTutorialHeaderProgress] = useState<LearningLessonHeaderProgress | null>(null);
  const [config, setConfig] = useState<MotorConfig>(() => initialNewDesign ? newBuildConfig('inner') : cloneDefaultConfig());
  const [runSetups, setRunSetups] = useState(() => initialNewDesign ? newProfileDocument() : loadProfileDocument('starter:spm'));
  const [designName, setDesignName] = useState<string | null>(initialNewDesign ? 'New Design' : null);
  const [blankDesign, setBlankDesign] = useState(initialNewDesign);
  const [newDesignParts, setNewDesignParts] = useState<BuiltParts | null>(initialNewDesign ? {} : null);
  const [designSession, setDesignSession] = useState(0);
  const [designInputErrors, setDesignInputErrors] = useState<Record<string, DesignIssue | null>>({});
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
  const [guidedSolveSection, setGuidedSolveSection] = useState<SolveSetupSection | null>(null);
  const [busy, setBusy] = useState<PublicBusyAction>(null);
  // Development auto reload (COILEM_UI_AUTO_RELOAD=1): the page reloads when the launcher reports a rebuilt UI, but never under a running solve.
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const uiReloadTokenRef = useRef<string | null>(null);
  const [cancellingSolve, setCancellingSolve] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<PublicConnectionStatus>('checking');
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [selectedSolver, setSelectedSolver] = useState<PublicSolverId>('magneto2d');
  const [elmerCapability, setElmerCapability] = useState<PublicElmerCapability>(ELMER_CHECKING);
  const [experimentalRotors, setExperimentalRotors] = useState<PublicExperimentalRotorCapability>(EXPERIMENTAL_ROTORS_OFF);
  const [geometryStale, setGeometryStale] = useState(!initialNewDesign);
  const [previewNetworkFailed, setPreviewNetworkFailed] = useState(false);
  const [backendRecovery, setBackendRecovery] = useState(0);
  const previewRecoveryAttempt = useRef(0);
  // Keep API error codes for recovery UI; flattening to text loses the cause.
  const [errorDetails, setErrorDetails] = useState<PublicApiError | null>(null);
  const error = errorDetails ? designErrorText(errorDetails, config) : null;
  const setError = useCallback((value: string | PublicApiError | null) => {
    setErrorDetails(typeof value === 'string'
      ? { error_code: 'LOCAL_REQUEST_FAILED', message: value }
      : value);
  }, []);
  const [notice, setNotice] = useState<string | null>(initialNewDesign
    ? 'Choose the rotor arrangement and topology, then build the motor from outside inward.' : null);
  useEffect(() => {
    if (!storeProfileDocument(runSetups)) setNotice('Run setups could not be stored in this browser. Save the design file to keep them.');
  }, [runSetups]);
  const activeRunSetup = [...BUILTIN_SOLVE_PROFILES, ...runSetups.profiles].find(
    p => p.id === runSetups.activeId && p.version === runSetups.activeVersion,
  );
  const runSetupMetadata = profileProvenance(activeRunSetup, config, selectedSolver);

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

  // A stator-only field belongs to the result it was drawn for, so it goes when
  // that result does: below when the result clears, and from resetComputedState,
  // whose setResult(null) React batches with the next result when a saved run is
  // opened, so the effect never sees the null.
  const clearArmatureField = useCallback(() => {
    armatureFieldRequestId.current += 1;
    armatureFieldController.current?.abort();
    armatureFieldController.current = null;
    setArmatureField(null);
    setArmatureFieldError(null);
    setBusy((current) => current === 'field' ? null : current);
  }, []);

  useEffect(() => {
    if (result) return;
    clearArmatureField();
    setProgress(null);
  }, [result, clearArmatureField]);

  const resetComputedState = useCallback(() => {
    validationRequestId.current += 1;
    setMesh(null);
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    clearArmatureField();
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice(null);
    setView('design');
  }, [clearArmatureField]);

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
      return preparedMesh;
    } catch (requestError) {
      if (requestId !== meshRequestId.current) return null;
      setError(requestFailure(requestError));
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
    entrySnapshot?: NewDesignEntrySnapshot,
  ) => {
    if (config.geometry_reference && section !== "solve_params") return;
    const enteredFields = entrySnapshot?.fields;
    if (guidedActive && visitedSection) setGuidedDesignSection(visitedSection);
    const selectedIpmLayout = section === 'rotor'
      && field === 'ipm_topology'
      && (value === 'flat_buried' || value === 'v_shape')
      ? value
      : null;
    const enablingToothShoe = section === 'stator'
      && field === 'tooth_shoe_enabled'
      && value === true;
    // One layer winds half the tooth coils of two (8p/12s: 2 per phase, not 4),
    // so keep the parallel paths a divisor of what is left.
    const layerCount = section === 'winding' && field === 'layers' ? Number(value) : null;
    const layerCoilsPerPhase = layerCount === null
      ? 0
      : coilsPerPhase(config.stator.slot_count, config.rotor.pole_count, config.winding.type, layerCount);
    let nextConfig: MotorConfig = selectedIpmLayout
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
      : layerCount !== null
        ? {
          ...config,
          winding: {
            ...config.winding,
            layers: layerCount,
            parallel_paths: layerCoilsPerPhase > 0
              ? parallelPathsDividing(layerCoilsPerPhase, config.winding.parallel_paths)
              : config.winding.parallel_paths,
          },
        }
      : section === 'winding' && field === 'type'
        ? { ...config, winding: windingForType(config, value as MotorConfig['winding']['type']) }
      : {
        ...config,
        [section]: { ...config[section], [field]: value },
      };
    // Confirmation and this edit share one React event. Include the current
    // field before checking whether an unchanged default reveals another part.
    const magnetLabel = section === 'rotor' ? { magnet_thickness_mm: 'Magnet Thick.', magnet_width_mm: 'Magnet Width', v_angle_deg: 'V Angle', v_depth_mm: 'V Depth' }[field] : undefined;
    const confirmed = enteredFields && { ...enteredFields, ...(magnetLabel ? { [`rotor:${magnetLabel}`]: true } : {}) };
    let nextParts = newDesignParts ? revealEditedPart(newDesignParts, section, field) : null;
    if (nextParts && confirmed) nextParts = { ...nextParts,
      magnets: Boolean(confirmed['rotor:Magnet Thick.'] && confirmed['rotor:Magnet Width']
        && (nextConfig.topology !== 'IPM' || nextConfig.rotor.ipm_topology !== 'v_shape'
          || confirmed['rotor:V Angle'] && confirmed['rotor:V Depth'])),
    };
    const revealsPart = JSON.stringify(nextParts) !== JSON.stringify(newDesignParts);
    if (Object.is(editableValue(config, section, field), editableValue(nextConfig, section, field)) && !revealsPart) return;
    if (nextParts) {
      if (section === 'rotor' && field === 'pole_count') nextConfig = fitPoleMagnets(config, nextConfig, newDesignParts!, confirmed);
      nextConfig = fitUnbuiltParts(nextConfig, nextParts, confirmed);
      setNewDesignParts(nextParts);
    }
    setConfig(nextConfig);
    setEditFeedback({
      id: ++editFeedbackId.current,
      previousConfig: config,
      previousBlankDesign: blankDesign,
      previousNewDesignParts: newDesignParts,
      previousEntry: entrySnapshot,
      ...describeDesignEdit(config, nextConfig, section, field),
    });
    setBlankDesign(false);
    if (section !== 'solve_params') invalidateGeometryPreview();
    resetComputedState();
  }, [blankDesign, config, guidedActive, invalidateGeometryPreview, newDesignParts, resetComputedState]);

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

  const updateTopology = useCallback((topology: MotorConfig['topology'], entrySnapshot?: NewDesignEntrySnapshot) => {
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
    if (newDesignParts) setNewDesignParts({ ...newDesignParts, rotor: false, magnets: false });
    setEditFeedback({
      id: ++editFeedbackId.current,
      previousConfig: config,
      previousBlankDesign: blankDesign,
      previousNewDesignParts: newDesignParts,
      previousEntry: entrySnapshot,
      message: 'Motor topology updated',
      consequence: `${config.topology} → ${topology} · ${airgapConsequence}`,
      affectedKind: 'rotor',
    });
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
  }, [blankDesign, config, invalidateGeometryPreview, newDesignParts, resetComputedState]);

  const undoLastDesignEdit = useCallback(() => {
    if (!editFeedback) return;
    setConfig(editFeedback.previousConfig);
    setBlankDesign(editFeedback.previousBlankDesign);
    if (editFeedback.previousNewDesignParts !== undefined) setNewDesignParts(editFeedback.previousNewDesignParts);
    setEditFeedback(null);
    invalidateGeometryPreview();
    if (editFeedback.previousBlankDesign) {
      setGeometry(null);
      setGeometryStale(false);
    }
    resetComputedState();
  }, [editFeedback, invalidateGeometryPreview, resetComputedState]);

  const updateMeshSetting = useCallback((
    field: 'mesh_density' | 'corner_refinement' | 'mesh_build',
    value: MotorConfig['solve_params']['mesh_density'] | MotorConfig['solve_params']['mesh_build'] | boolean,
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
    field: 'current_amplitude_A' | 'rated_speed_rpm' | 'nonlinear_solver' | 'current_amplitude_convention' | 'current_angle_deg' | 'excitation_mode' | 'commutation_advance_deg' | 'mechanical_loss_W' | 'magnet_temperature_C' | 'max_nonlinear_iterations',
    value: MotorConfig['solve_params']['nonlinear_solver'] | MotorConfig['solve_params']['current_amplitude_convention'] | MotorConfig['solve_params']['excitation_mode'] | number,
  ) => {
    if (field === 'magnet_temperature_C' && config.geometry_reference === 'pyleecan_prius_2004') {
      if (value !== 20 && value !== 60) return;
      const next: MotorConfig = { ...config,
        reference_case: value === 60 ? 'prius-2004-loaded-torque-v1' : 'prius-2004-tutorial-bemf-v1',
        solve_params: { ...config.solve_params, magnet_temperature_C: value },
      };
      setConfig(next); resetComputedState(); void prepareMesh(next);
      return;
    }
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
          // No mechanical loss is stored as unset, not 0 W; a 20 °C magnet is the catalogue, also unset.
          [field]: (field === 'mechanical_loss_W' && !(Number(value) > 0)) || (field === 'magnet_temperature_C' && Number(value) === 20) ? null : value,
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
  }, [config, prepareMesh, resetComputedState]);

  const updateAnalysis = useCallback((key: AnalysisKey, enabled: boolean) => {
    validationRequestId.current += 1;
    setConfig((current) => setAnalysisOption(current, key, enabled));
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice('Analysis settings changed. Updating the run estimate.');
  }, []);

  const updateTorqueSpeed = useCallback((settings: TorqueSpeedAnalysisSettings) => {
    validationRequestId.current += 1;
    setConfig((current) => ({ ...current, torque_speed_analysis: settings }));
    setValidation(null);
    setValidationChecking(false);
    setValidationError(null);
    setResult(null);
    setProgress(null);
    setLiveSamples([]);
    setError(null);
    setNotice('Map settings changed. Updating the run estimate.');
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
    void prepareMesh(nextConfig);
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

  const constructionPreview = newDesignParts !== null && !designPartsComplete(newDesignParts);
  const statorOnlyPreview = constructionPreview && config.topology === 'IPM'
    && !newDesignParts?.rotor && config.rotor_layout !== 'outer';
  const diagnosticPreview = constructionPreview && config.topology === 'IPM'
    && Boolean(newDesignParts?.rotor) && config.rotor_layout !== 'outer';
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
      const payload = await generatePublicPreview(asPublicConfig(nextConfig), { construction: constructionPreview, statorOnly: statorOnlyPreview, diagnostic: diagnosticPreview });
      if (requestId !== previewRequestId.current) return;
      const nextGeometry = payload as unknown as GeometryPreview;
      setGeometry(nextGeometry);
      setGeometryStale(false);
      setConnectionStatus('online');
      const diagnosticIssue = nextGeometry.metadata?.diagnostic_only ? nextGeometry.validation_errors[0] : null;
      setError(diagnosticIssue ? { error_code: String(diagnosticIssue.error_code ?? 'INVALID_GEOMETRY'),
        message: String(diagnosticIssue.message ?? 'Review the rotor geometry.'),
        field: typeof diagnosticIssue.field === 'string' ? diagnosticIssue.field : null,
        suggestion: typeof diagnosticIssue.suggestion === 'string' ? diagnosticIssue.suggestion : null } : null);
    } catch (requestError) {
      if (requestId !== previewRequestId.current) return;
      setPreviewNetworkFailed(requestError instanceof TypeError);
      setError(requestFailure(requestError));
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
    } finally {
      if (requestId === previewRequestId.current) {
        setBusy((current) => current === 'geometry' ? null : current);
      }
    }
  }, [constructionPreview, statorOnlyPreview, diagnosticPreview]);

  const refreshSolveValidation = useCallback(async (nextConfig: MotorConfig) => {
    const requestId = ++validationRequestId.current;
    setValidationChecking(true);
    setValidationError(null);
    try {
      const request: PublicSolveRequest = {
        config: asPublicConfig(nextConfig, selectedSolver),
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
        const reloadToken = typeof health.ui_reload_token === 'string' ? health.ui_reload_token : null;
        if (reloadToken !== null) {
          if (uiReloadTokenRef.current === null) uiReloadTokenRef.current = reloadToken;
          else if (reloadToken !== uiReloadTokenRef.current && busyRef.current !== 'solve') {
            window.location.reload();
            return;
          }
        }
        const nextElmerCapability = elmerCapabilityFromHealth(health);
        setConnectionStatus('online');
        setAppVersion(typeof health.version === 'string' && health.version.trim() ? health.version.trim() : null);
        setElmerCapability((current) => (
          sameElmerCapability(current, nextElmerCapability) ? current : nextElmerCapability
        ));
        const nextExperimentalRotors = experimentalRotorsFromHealth(health);
        setExperimentalRotors((current) => (
          current.enabled === nextExperimentalRotors.enabled && current.switch === nextExperimentalRotors.switch
            ? current
            : nextExperimentalRotors
        ));
        refreshMaterials();
      },
      onOffline: () => {
        setConnectionStatus('offline');
        setElmerCapability(ELMER_API_UNAVAILABLE);
        setExperimentalRotors(EXPERIMENTAL_ROTORS_OFF);
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
    // The first solved field a run names stays on the progress for the Solve page to show.
    setProgress((previous) => withFirstPublicSolveFieldFrame(previous, nextProgress));
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
        config: asPublicConfig(config, selectedSolver),
        solver: selectedSolver,
        run_setup: runSetupMetadata,
        run_setups: runSetups,
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
          // The solved field replacing the progress view says the run is done.
          setNotice(null);
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
        // Shown beside the Stator control only: the completed run is unaffected,
        // so its status must not change to "Needs review" (#267).
        setArmatureFieldError(message);
        setProgress(null);
        if (streamError.error_code === 'LOCAL_API_UNREACHABLE') setConnectionStatus('offline');
        setBusy(null);
        armatureFieldController.current = null;
      },
    });
  };

  const cancelArmatureField = async () => {
    armatureFieldRequestId.current += 1;
    armatureFieldController.current?.abort();
    armatureFieldController.current = null;
    setArmatureField(null);
    setArmatureFieldError(null);
    setError(null);
    try {
      await cancelPublicSolve();
      setConnectionStatus('online');
      setNotice('Stator-only field canceled. The resultant field is still available.');
    } catch (requestError) {
      setError(errorMessage(requestError));
      setConnectionStatus(requestError instanceof TypeError ? 'offline' : 'online');
    } finally {
      setBusy((current) => current === 'field' ? null : current);
      setProgress(null);
    }
  };

  const cancelSolve = async () => {
    solveRequestId.current += 1;
    solveController.current?.abort();
    solveController.current = null;
    const retainedPreviousResult = restoreSolveResultBeforeRun();
    setError(null);
    // The request answers once the backend has released the solve, which can
    // take a few seconds while a mesh is being built. Run stays disabled until
    // then, so a rerun is never refused as "already running" (#266).
    setCancellingSolve(true);
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
      setCancellingSolve(false);
      setBusy(null);
      setProgress(null);
    }
  };

  const reset = () => {
    setNewDesignParts(null);
    setDesignInputErrors({});
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
    setRunSetups(loadProfileDocument('starter:spm'));
    setNotice('Design reset to the example motor.');
  };

  const beginNewDesign = (guided: boolean) => {
    setRunSetups(newProfileDocument());
    resetDesignViewMemory();
    solveRequestId.current += 1;
    meshRequestId.current += 1;
    armatureFieldRequestId.current += 1;
    solveController.current?.abort();
    solveController.current = null;
    armatureFieldController.current?.abort();
    armatureFieldController.current = null;
    solveResultBeforeRun.current = null;
    previewRequestId.current += 1;
    const nextConfig = newBuildConfig('inner');
    rememberPresetSweep(nextConfig);
    setConfig(nextConfig);
    setDesignName('New Design');
    setBlankDesign(true);
    setNewDesignParts({});
    setDesignInputErrors({});
    setDesignSession((session) => session + 1);
    setGeometry(null);
    setGeometryStale(false);
    setEditFeedback(null);
    resetComputedState();
    setGuidedActive(guided);
    setGuidedDesignSection(null);
    setGuidedSolveSection(null);
    setShowLanding(false);
    setTutorialsView(null);
    setView('design');
    setNotice('Choose the rotor arrangement and topology, then build the motor from outside inward.');
    if (typeof window !== 'undefined' && window.location.pathname !== '/') {
      window.history.pushState({}, '', '/');
    }
  };
  const startNewDesign = () => beginNewDesign(false);

  const openDesignFile = async (file: File) => {
    resetDesignViewMemory();
    try {
      const parsed = parseDesignFile(await file.text());
      setRunSetups(parsed.runSetups ?? newProfileDocument());
      setNewDesignParts(null);
      setDesignInputErrors({});
      rememberPresetSweep(parsed.config);
      setConfig(parsed.config);
      if (parsed.config.geometry_reference) setSelectedSolver("magneto2d");
      setGeometry(null);
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

  // The arrangement switch swaps designs rather than reinterpreting inrunner
  // dimensions as an outer rotor's; the last inrunner comes back on return.
  const lastInrunnerRef = useRef<{ name: string | null; config: MotorConfig } | null>(null);
  const updateRotorLayout = (layout: RotorLayout) => {
    if (newDesignParts) {
      const next = newBuildConfig(layout);
      rememberPresetSweep(next);
      setConfig(next);
      setNewDesignParts({});
      setDesignInputErrors({});
      setGeometry(null);
      setBlankDesign(true);
      setEditFeedback(null);
      invalidateGeometryPreview();
      resetComputedState();
      return;
    }
    if (layout === (config.rotor_layout ?? 'inner')) return;
    if (layout === 'outer') {
      lastInrunnerRef.current = { name: designName, config };
      loadExampleDesign('spm-outrunner-14p12s');
      return;
    }
    const previous = lastInrunnerRef.current;
    loadExampleDesign('spm-8p12s', previous ?? undefined);
  };

  const loadExampleDesign = (exampleId: PublicExampleId, restored?: { name: string | null; config: MotorConfig }) => {
    setNewDesignParts(null);
    setDesignInputErrors({});
    resetDesignViewMemory();
    const example = restored ?? createPublicExampleDesign(exampleId);
    setRunSetups(loadProfileDocument(`example:${exampleId}`));
    rememberPresetSweep(example.config);
    setConfig(example.config);
    if (example.config.geometry_reference) setSelectedSolver("magneto2d");
    setGeometry(null);
    setEditFeedback(null);
    setDesignName(example.name);
    setBlankDesign(false);
    invalidateGeometryPreview();
    resetComputedState();
    setGuidedActive(false);
    setGuidedDesignSection(null);
    setGuidedSolveSection(null);
    setShowLanding(false);
    setTutorialsView(null);
    setView('design');
    setNotice(`Loaded ${example.name ?? 'the previous inrunner'}.`);
    if (typeof window !== 'undefined' && window.location.pathname !== '/') {
      window.history.pushState({}, '', '/');
    }
  };

  const saveDesign = () => {
    void saveDesignFileAs(
      config,
      designName ?? `coilem-${config.topology.toLowerCase()}-${config.rotor.pole_count}p${config.stator.slot_count}s`,
      runSetups,
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
    destination: 'design' | 'solve' | 'results',
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
      setNewDesignParts(null);
      setDesignInputErrors({});
      const requestPayload = payload.request;
      const submittedRequest = requestPayload && typeof requestPayload === 'object'
        ? (requestPayload as PublicJson).submitted
        : null;
      setRunSetups(parsed.runSetups ?? parseProfileDocument(
        submittedRequest && typeof submittedRequest === 'object' ? (submittedRequest as PublicJson).run_setups : undefined,
      ) ?? newProfileDocument());
      const storedSolver = submittedRequest && typeof submittedRequest === 'object'
        ? (submittedRequest as PublicJson).solver
        : null;
      const replaySolver: PublicSolverId = storedSolver === 'elmer' && !parsed.config.geometry_reference ? 'elmer' : 'magneto2d';
      rememberPresetSweep(parsed.config);
      setConfig(parsed.config);
      setGeometry(null);
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
      if (destination === 'results') {
        // The stored result as the solve returned it; its field playback is
        // drawn again from the run's frames when the cache no longer has it.
        const storedResult = payload.result;
        if (!storedResult || typeof storedResult !== 'object') {
          throw new Error('The saved run does not contain a stored result.');
        }
        const provenance = (payload.manifest as PublicJson | undefined)?.provenance as PublicJson | undefined;
        setResult({
          ...savedResultPlayback(storedResult as unknown as SolveResult, payload.field_playback),
          saved_run: payload.saved_run,
          qualification: provenance?.qualification ?? null,
        } as unknown as SolveResult);
        setView('solve');
        const completedAt = typeof savedRun.completed_at === 'string' ? new Date(savedRun.completed_at).toLocaleString() : null;
        const playback = payload.field_playback as { available?: unknown } | undefined;
        setNotice([
          `Showing the saved result${completedAt ? ` from ${completedAt}` : ''}. It is stored evidence for these inputs; solve again for a current result.`,
          playback?.available === false ? 'Its field playback was removed to save disk space.' : null,
          parsed.solverSettingsNotice,
        ].filter(Boolean).join(' '));
        return;
      }
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
    if (guided) { beginNewDesign(true); return; }
    setNewDesignParts(null);
    setDesignInputErrors({});
    resetDesignViewMemory();
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
    setShowLanding(false);
    setView('design');
    setGuidedDesignSection(null);
    setGuidedSolveSection(null);
    setGuidedActive(guided);
    setNotice(null);
  };

  const visitGuidedDesignSection = useCallback((section: PublicParameterSection) => {
    if (guidedActive) setGuidedDesignSection(section);
  }, [guidedActive]);

  const revealGuidedDesignSection = useCallback((section: PublicParameterSection | null) => {
    setGuidedDesignSection(section);
  }, []);

  const acceptNewDesignSection = (section: PublicParameterSection) => {
    if (!newDesignParts || Object.values(designInputErrors).some(Boolean)) return;
    setNewDesignParts(acceptDesignSection(newDesignParts, section));
    setEditFeedback(null);
    setBlankDesign(false);
  };

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
    if (step === 'solve' && (!designPartsComplete(newDesignParts) || Object.values(designInputErrors).some(Boolean))) return;
    setView(step);
    if (step === 'solve' && guidedActive) setGuidedSolveSection('operating');
    if (step === 'solve' && !guidedActive && !mesh && busy !== 'mesh' && busy !== 'solve') {
      void generateMesh();
    }
  };

  // Meshing fills the first part of the bar and field solves the rest; it
  // never moves backwards within one solve (#53).
  const [progressBar, setProgressBar] = useState(EMPTY_PUBLIC_SOLVE_PROGRESS_BAR);
  useEffect(() => {
    setProgressBar((previous) => nextPublicSolveProgressBar(previous, progress));
  }, [progress]);
  const progressPercent = progressBar.percent;

  const meshElements = Number(mesh?.mesh_info.num_triangles || mesh?.triangles.length || 0);
  const meshQuality = Number(mesh?.mesh_qa.min_triangle_quality || 0);

  if (tutorialsView) {
    // Keep the shell and top bar, as the private app does across its lesson routes.
    // Without them the tutorials area loses the backend connection indicator, so a
    // perfectly healthy local API looks like it is not running.
    return (
      <div className="public-coilem-shell is-tutorials">
        <CoilEmTopBar
          appVersion={appVersion}
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
          onResetDesign={guidedActive ? () => beginNewDesign(true) : resetDesign}
          onLoadExample={loadExampleDesign}
          onOpenHalbach={() => setShowHalbachWorkspace(true)}
          onNewDesign={startNewDesign}
          experimentalRotors={experimentalRotors.enabled}
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
        appVersion={appVersion}
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
          appVersion={appVersion}
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
          onResetDesign={guidedActive ? () => beginNewDesign(true) : resetDesign}
          onLoadExample={loadExampleDesign}
          onOpenHalbach={() => setShowHalbachWorkspace(true)}
          onNewDesign={startNewDesign}
          experimentalRotors={experimentalRotors.enabled}
          workflowDisabled
          onOpenRunResults={(savedRun) => void restoreSavedRun(savedRun, 'results')}
        />
        <PublicLanding
          onStartGuided={() => openWorkspace(true)}
          onUseExample={() => openWorkspace(false)}
          onOpenTutorials={() => navigateTutorials('catalog')}
          onOpenHalbach={() => setShowHalbachWorkspace(true)}
          onLoadExample={loadExampleDesign}
        />
      </div>
    );
  }

  return (
    <>
    {/* Replace the whole workspace on New Design, including panel and viewport state. */}
    <CoilEmWorkspace
      runSetupControl={<RunSetupControl config={config} solver={selectedSolver} document={runSetups}
        builtins={BUILTIN_SOLVE_PROFILES} disabled={busy !== null} onChange={setRunSetups}
        onApply={(next, nextSolver) => {
          if ((nextSolver ?? selectedSolver) === 'elmer' && (next.solve_options.cogging_torque || next.solve_options.losses_efficiency || next.solve_options.torque_speed_envelope)) {
            setNotice('This setup requests analyses that require Magneto2D. Select Magneto2D before applying it.'); return false;
          }
          if ((nextSolver ?? selectedSolver) === 'elmer' && next.solve_params.excitation_mode === 'ideal_six_step_120') {
            setNotice('Six-step setups require Magneto2D. Select Magneto2D before applying this setup.'); return false;
          }
          if (nextSolver === 'elmer' && !elmerCapabilityIsReady(elmerCapability)) {
            setNotice('This setup requires the qualified Elmer runtime, which is not available.'); return false;
          }
          rememberPresetSweep(next);
          setConfig(next); if (nextSolver) setSelectedSolver(nextSolver);
          resetComputedState(); void prepareMesh(next);
          setNotice('Run setup applied. Review the values below before solving.');
          return true;
        }} />}
      key={designSession}
      appVersion={appVersion}
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
      guidedSolveSection={guidedSolveSection}
      guidedSetup={guidedActive ? <PublicGuidedSetup
        activeStep={view}
        activeDesignSection={guidedDesignSection}
        topology={config.topology}
        resultReady={Boolean(result)}
        meshReady={Boolean(mesh)}
        busy={busy !== null}
        onWorkflowStepChange={changeWorkflowStep}
        onDesignSectionChange={revealGuidedDesignSection}
        onSolveSectionChange={setGuidedSolveSection}
        onAcceptDesignSection={acceptNewDesignSection}
        onGenerateMesh={() => void generateMesh()}
        onStartSolve={() => void startSolve()}
        onExit={() => {
          setGuidedActive(false);
          setGuidedDesignSection(null);
          setGuidedSolveSection(null);
        }}
      /> : null}
      busy={busy}
      connectionStatus={connectionStatus}
      selectedSolver={selectedSolver}
      elmerCapability={elmerCapability}
      experimentalRotors={experimentalRotors}
      geometryStale={geometryStale}
      error={error}
      errorDetails={errorDetails}
      notice={notice}
      progressPercent={progressPercent}
      meshElements={meshElements}
      meshQuality={meshQuality}
      designName={designName}
      blankDesign={blankDesign}
      newDesignParts={newDesignParts}
      designInputInvalid={Object.values(designInputErrors).some(Boolean)}
      designInputIssue={Object.values(designInputErrors).find((issue) => issue !== null)}
      onDesignInputIssueChange={(field, issue) => setDesignInputErrors((current) => current[field]?.message === issue?.message ? current : { ...current, [field]: issue })}
      onAcceptDesignSection={acceptNewDesignSection}
      editFeedback={editFeedback}
      onOpenDesignFile={(file) => void openDesignFile(file)}
      onSaveDesign={saveDesign}
      onResetDesign={guidedActive ? () => beginNewDesign(true) : resetDesign}
      onLoadExample={loadExampleDesign}
      onOpenHalbach={() => setShowHalbachWorkspace(true)}
      onNewDesign={startNewDesign}
      onHome={() => {
        setGuidedActive(false);
        setGuidedDesignSection(null);
        setGuidedSolveSection(null);
        setShowLanding(true);
      }}
      onStepChange={changeWorkflowStep}
      onTopologyChange={updateTopology}
      onRotorLayoutChange={updateRotorLayout}
      onSectionChange={updateSection}
      onDesignSectionVisit={visitGuidedDesignSection}
      onConvertProjectSteelToM350={convertProjectSteelToM350}
      onImportSteel={importSteel}
      onMeshSettingChange={updateMeshSetting}
      onSolvePlanChange={updateSolvePlan}
      onCustomSweepChange={updateCustomSweep}
      onSolveSettingChange={updateSolveSetting}
      onAnalysisChange={updateAnalysis}
      onTorqueSpeedChange={updateTorqueSpeed}
      onSolverChange={selectSolver}
      onReset={guidedActive ? () => beginNewDesign(true) : reset}
      onRefreshGeometry={() => void refreshGeometry(config)}
      onGenerateMesh={() => void generateMesh()}
      onStartSolve={() => void startSolve()}
      onCancelSolve={() => void cancelSolve()}
      cancellingSolve={cancellingSolve}
      onRequestArmatureField={() => void loadArmatureField()}
      onCancelArmatureField={() => void cancelArmatureField()}
      onOpenRunFolder={openSavedRunFolder}
      onDownloadRunExport={downloadSavedRunExport}
      onOpenRunProject={(savedRun) => void restoreSavedRun(savedRun, 'design')}
      onRerun={(savedRun) => void restoreSavedRun(savedRun, 'solve')}
      onOpenRunResults={(savedRun) => void restoreSavedRun(savedRun, 'results')}
      onUndoDesignEdit={undoLastDesignEdit}
      onDismissDesignEdit={() => setEditFeedback(null)}
    />
    </>
  );
}
