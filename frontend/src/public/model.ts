import type { AirgapBrBtProfile } from '../components/tutorials/lessonSolveTypes';
import type { CustomSteel } from './customSteel';

export type Topology = 'SPM' | 'IPM';
export type IpMTopology = 'flat_buried' | 'v_shape';
export type SolveQuality = 'quick' | 'standard' | 'fine' | 'custom';
export type MeshDensity = 'coarse' | 'normal' | 'fine' | 'very_fine';

export const PUBLIC_MAGNETO2D_SETTINGS = {
  torque_method: 'weighted_stress',
  linear_solver_preconditioner: 'direct',
} as const;

/** Keep public requests and saved projects aligned with the fixed UI profile. */
export function applyPublicSolverSettings(config: MotorConfig): MotorConfig {
  return {
    ...config,
    solve_params: { ...config.solve_params, ...PUBLIC_MAGNETO2D_SETTINGS },
  };
}
export type PublicSolverId = 'magneto2d' | 'elmer';

export interface PublicElmerCapability {
  feature_enabled: boolean;
  available: boolean;
  qualified: boolean;
  adapter_ready: boolean;
  gmsh_available?: boolean;
  meshio_available?: boolean;
  solver_version?: string | null;
  grid_version?: string | null;
  reason?: string | null;
}

// `bearing` and `endcap` are drawn by the 3D viewer only. They are illustrative
// housing, never solver regions, so they carry no region index and their facts
// say as much.
export type PublicMotorComponentKind = 'stator' | 'rotor' | 'magnet' | 'winding' | 'harness' | 'shaft' | 'airgap' | 'bearing' | 'endcap';

export interface PublicMotorComponentSelection {
  id: string;
  kind: PublicMotorComponentKind;
  label: string;
  role: string;
  regionType?: string;
  regionIndex?: number;
  slotIndex?: number;
  toothIndex?: number;
  poleIndex?: number;
  phase?: 'A' | 'B' | 'C';
  direction?: '+' | '-';
  windingModel?: string;
}

export interface MotorConfig {
  schema_version: '1.0';
  topology: Topology;
  stator: {
    OD_mm: number;
    ID_mm: number;
    slot_count: number;
    stack_length_mm: number;
    slot_opening_mm: number;
    tooth_width_mm: number;
    yoke_thickness_mm: number;
    tooth_shoe_enabled?: boolean;
    tooth_shoe_height_mm?: number;
    tooth_shoe_overhang_mm?: number;
  };
  rotor: {
    OD_mm: number;
    ID_mm: number | null;
    magnet_thickness_mm: number;
    magnet_width_mm: number;
    pole_count: number;
    magnet_embrace: number;
    bridge_thickness_mm: number;
    ipm_topology: IpMTopology;
    flat_buried_magnet_shape: 'straight' | 'legacy_arc';
    side_bridge_thickness_mm: number;
    pocket_clearance_mm: number;
    magnet_angle_deg: number;
    v_angle_deg: number;
    v_depth_mm: number;
    inner_web_thickness_mm: number;
    outer_bridge_thickness_mm: number;
  };
  winding: {
    type: 'concentrated' | 'distributed';
    turns_per_coil: number;
    layers: number;
    parallel_paths: number;
    coil_span?: number | null;
  };
  materials: {
    stator_steel: string;
    rotor_steel: string;
    magnet_grade: string;
    conductor: string;
    custom_steels?: Record<string, CustomSteel>;
  };
  solve_params: {
    solve_quality: SolveQuality;
    rotor_sweep_range_deg: number;
    rotor_step_deg: number;
    mesh_density: MeshDensity;
    mesh_source: 'native';
    mesher: 'gmsh';
    corner_refinement: boolean;
    rotor_rotation_model: 'remesh_per_step';
    torque_method: 'contour' | 'arkkio' | 'weighted_stress';
    nonlinear_solver: 'picard' | 'newton';
    linear_solver_preconditioner: 'direct' | 'ic0' | 'jacobi';
    current_amplitude_A: number;
    current_amplitude_convention: 'rms' | 'peak' | 'plateau';
    current_angle_deg: number;
    excitation_mode: 'sinusoidal' | 'ideal_six_step_120';
    commutation_advance_deg: number;
    phase_connection: 'wye';
    rated_speed_rpm: number;
  };
  solve_options: {
    torque_sweep: boolean;
    back_emf: boolean;
    flux_density: boolean;
    cogging_torque: boolean;
    torque_speed_envelope: false;
    thd_analysis: boolean;
  };
}

export interface PreviewRegion {
  region_type: string;
  points: Array<[number, number]>;
  fill?: string | null;
  label?: string | null;
}

/** One conductor bundle in one slot, as the backend lays the winding out. */
export interface PublicWindingSlot {
  slot_index: number;
  phase: 'A' | 'B' | 'C';
  direction: 'in' | 'out';
  layer: number;
}

/** One coil and the two slots its sides sit in. */
export interface PublicWindingCoil {
  coil_index: number;
  phase: 'A' | 'B' | 'C';
  polarity: number;
  slot_in: number;
  slot_out: number;
  tooth_wound: boolean;
  layer: number;
}

export interface GeometryPreview {
  regions: PreviewRegion[];
  /** Both were already sent by /preview; the Layout view is the first reader. */
  winding_layout?: PublicWindingSlot[];
  winding_coils?: PublicWindingCoil[];
  metadata: Record<string, unknown>;
  validation_errors: Array<Record<string, unknown>>;
  generation_time_ms: number;
}

export interface MeshPreview {
  nodes_mm: Array<[number, number]>;
  triangles: Array<[number, number, number]>;
  regions: string[];
  mesh_info: Record<string, unknown>;
  mesh_qa: Record<string, unknown>;
  generation_time_ms: number;
  solve_mesh_key?: string;
}

export interface SolveValidation {
  valid: boolean;
  errors: Array<{ code?: string; message: string; suggestion?: string }>;
  warnings: Array<{ code?: string; message: string; suggestion?: string }>;
  estimated_solve_time_s: number;
  estimated_mesh_elements: number;
  sweep_positions: number;
}

export interface FieldLineContourLevel {
  level: number;
  segments_mm: number[][];
  segment_b_mag_t?: number[];
  segment_bx_t?: number[];
  segment_by_t?: number[];
}

export interface PublicFieldLinePlot {
  angle_deg?: number;
  nodes_mm: number[][];
  triangles: number[][];
  regions: string[];
  element_b_mag_t: number[];
  element_bx_t?: number[];
  element_by_t?: number[];
  contour_levels: FieldLineContourLevel[];
  az_min: number;
  az_max: number;
  n_pole_pitches: number;
  total_span_deg: number;
  airgap_brbt?: AirgapBrBtProfile | null;
  noload_plot?: PublicFieldLinePlot | null;
}

export interface PublicFieldFrameDescriptor {
  angle_deg: number;
  field_frame_artifact: { artifact_id: string };
  has_pm_only?: boolean;
  airgap_brbt?: AirgapBrBtProfile | null;
  playback_frame?: PublicFieldPlaybackFrame;
}

export interface PublicAirgapProfileDescriptor {
  angle_deg: number;
  airgap_brbt: AirgapBrBtProfile;
}

export type PublicFieldPlaybackMediaType = 'image/png' | 'image/webp';

export interface PublicFieldPlaybackArtifact {
  artifact_id: string;
  media_type: PublicFieldPlaybackMediaType;
  byte_count: number;
}

export interface PublicFieldNumericalArtifact {
  artifact_id: string;
  media_type: 'application/json+gzip';
}

export interface PublicFieldVectorCue {
  x: number;
  y: number;
  dx: number;
  dy: number;
  magnitude?: number;
}

export interface PublicFieldPlaybackComposition {
  base: PublicFieldPlaybackArtifact;
  flux_density: PublicFieldPlaybackArtifact;
  mesh?: PublicFieldPlaybackArtifact;
  field_lines: PublicFieldPlaybackArtifact;
  detail?: {
    base: PublicFieldPlaybackArtifact;
    flux_density: PublicFieldPlaybackArtifact;
    mesh?: PublicFieldPlaybackArtifact;
    field_lines: PublicFieldPlaybackArtifact;
  };
  view_box: string;
  min_b_t: number;
  max_b_t: number;
  triangle_count: number;
  contour_level_count: number;
  contour_segment_count: number;
  vector_cues?: PublicFieldVectorCue[];
}

export interface PublicFieldPlaybackFrame {
  index: number;
  angle_deg: number;
  compositions: Record<string, PublicFieldPlaybackComposition>;
  numerical_artifact?: PublicFieldNumericalArtifact;
}

export interface PublicFieldPlaybackManifestV1 {
  schema_version: 'coilem.field_playback.v1';
  encoding: 'layered-webp-v1';
  width_px: number;
  height_px: number;
  frame_count: number;
  frames: PublicFieldPlaybackFrame[];
  numerical_snapshots: PublicFieldNumericalArtifact[];
  manifest_artifact_id?: string;
}

export type PublicFieldPlaybackTimelineKind = 'angle' | 'time' | 'phase' | 'step';
export type PublicFieldPlaybackLayerRole = 'geometry' | 'scalar' | 'contours' | 'vectors' | 'annotations';

export interface PublicFieldPlaybackTimeline {
  kind: PublicFieldPlaybackTimelineKind;
  unit: string;
  loop: boolean;
  direction?: 'increasing' | 'decreasing';
}

export interface PublicFieldPlaybackLayerDefinition {
  id: string;
  label: string;
  role: PublicFieldPlaybackLayerRole;
  media_type: PublicFieldPlaybackMediaType;
  default_visible: boolean;
  quantity?: string;
  unit?: string;
}

export interface PublicFieldPlaybackCompositionDefinition {
  id: string;
  label: string;
  description?: string;
}

export interface PublicFieldPlaybackVisualV2 {
  layers: Record<string, PublicFieldPlaybackArtifact>;
  detail_layers?: Record<string, PublicFieldPlaybackArtifact>;
  view_box: string;
  vector_cues?: PublicFieldVectorCue[];
  legend?: {
    label: string;
    quantity?: string;
    unit: string;
    min: number;
    max: number;
  };
  statistics?: Record<string, string | number | boolean | null>;
}

export interface PublicFieldPlaybackFrameV2 {
  index: number;
  coordinate: number;
  duration_ms?: number;
  compositions: Record<string, PublicFieldPlaybackVisualV2>;
}

export interface PublicFieldPlaybackAnnotation {
  id: string;
  label: string;
  frame_start?: number;
  frame_end?: number;
  body?: string;
  target_ids?: string[];
}

export interface PublicFieldPlaybackManifestV2 {
  schema_version: 'coilem.field_playback.v2';
  encoding: 'layered-raster-v1' | 'layered-webp-v1';
  width_px: number;
  height_px: number;
  detail_width_px?: number;
  detail_height_px?: number;
  frame_count: number;
  timeline: PublicFieldPlaybackTimeline;
  layers: PublicFieldPlaybackLayerDefinition[];
  compositions: PublicFieldPlaybackCompositionDefinition[];
  frames: PublicFieldPlaybackFrameV2[];
  annotations?: PublicFieldPlaybackAnnotation[];
  numerical_snapshots: PublicFieldNumericalArtifact[];
  manifest_artifact_id?: string;
}

export type PublicFieldPlaybackManifest =
  | PublicFieldPlaybackManifestV1
  | PublicFieldPlaybackManifestV2;

export interface PublicArmatureFieldComposition {
  schema_version: 'coilem.public_field_composition.armature.v1';
  source: 'magneto2d_exact_br_zero';
  cache_hit: boolean;
  elapsed_s: number;
  frame_count: number;
  frames: PublicFieldFrameDescriptor[];
  airgap_profiles?: PublicAirgapProfileDescriptor[];
  field_playback?: PublicFieldPlaybackManifest | null;
}

export interface SolveResult {
  summary: {
    avg_torque_Nm: number;
    torque_ripple_pct: number;
    back_emf_fundamental_V: number;
    back_emf_thd_pct?: number | null;
    back_emf_thd_h6_pct?: number | null;
    back_emf_thd_h12_pct?: number | null;
    back_emf_thd_h24_pct?: number | null;
    back_emf_line_thd_h12_pct?: number | null;
    back_emf_line_thd_h24_pct?: number | null;
    Kt_Nm_per_A?: number | null;
    peak_flux_density_teeth_T: number;
    peak_flux_density_yoke_T: number;
    solve_time_s: number;
  };
  torque_waveform: {
    electrical_angle_deg: number[];
    torque_Nm: number[];
  };
  phase_current_waveform?: {
    electrical_angle_deg: number[];
    phase_a_A: number[];
    phase_b_A: number[];
    phase_c_A: number[];
  } | null;
  cogging_torque_waveform?: {
    electrical_angle_deg: number[];
    torque_Nm: number[];
  } | null;
  back_emf_waveform: {
    electrical_angle_deg: number[];
    phase_a_V: number[];
    phase_b_V: number[];
    phase_c_V: number[];
    line_ab_V?: number[] | null;
    line_bc_V?: number[] | null;
    line_ca_V?: number[] | null;
  };
  back_emf_harmonic_analysis?: {
    schema_version: string;
    method: string;
    source: string;
    amplitude_convention: string;
    sample_count: number;
    electrical_fundamental_frequency_Hz: number;
    headline_harmonic_max: number;
    extended_harmonic_max: number;
    phase_a_thd_h6_pct?: number | null;
    phase_a_thd_h12_pct?: number | null;
    phase_a_thd_h24_pct?: number | null;
    line_ab_thd_h12_pct?: number | null;
    line_ab_thd_h24_pct?: number | null;
    harmonics: Array<{
      order: number;
      frequency_Hz: number;
      phase_a_rms_V: number;
      phase_b_rms_V: number;
      phase_c_rms_V: number;
      line_ab_rms_V: number;
      line_bc_rms_V: number;
      line_ca_rms_V: number;
      phase_a_pct_fundamental?: number | null;
      line_ab_pct_fundamental?: number | null;
    }>;
  } | null;
  solve_metadata: {
    solver_name: string;
    mesh_element_count: number;
    rotor_positions: number;
    topology?: string;
    current_amplitude_A?: number | null;
    current_angle_deg?: number | null;
    excitation_mode?: string | null;
    current_amplitude_convention?: string | null;
    commutation_advance_deg?: number | null;
    phase_connection?: string | null;
    excitation_convention_version?: string | null;
    loaded_cycle_complete?: boolean | null;
    rated_speed_rpm?: number | null;
    mesher?: string | null;
    mesh_density?: string;
    mesh_source?: string | null;
    mesh_source_detail?: string | null;
    geometry_ir_version?: string | null;
    rotor_rotation_model?: string | null;
    torque_method?: string | null;
    nonlinear_tolerance?: number | null;
    physics_contract_version?: string | null;
  };
  field_line_plot?: PublicFieldLinePlot | null;
  field_line_frames?: PublicFieldFrameDescriptor[] | null;
  field_playback?: PublicFieldPlaybackManifest | null;
  saved_run?: PublicSavedRun | null;
  /** Browser wall time from Run through receipt of the saved result; absent on older/reloaded runs. */
  workflow_elapsed_s?: number;
}

export interface PublicSavedRun {
  schema_version: 'coilem.solve_run.v2';
  project_slug: string;
  run_id: string;
  path: string;
  completed_at?: string | null;
}

export interface MaterialCatalog {
  steels: string[];
  magnet_grades: string[];
  conductors: string[];
  models?: Record<string, PublicMaterialModel>;
}

export interface PublicMaterialCapabilities {
  material_curve: boolean;
  saturation_visualization: boolean;
  hysteresis_loop: boolean;
  demagnetization_assessment: boolean;
  temperature_dependence: boolean;
  core_loss: boolean;
}

export interface PublicMaterialCurve {
  x_quantity: 'field_strength';
  x_unit: 'A/m';
  x_scale: 'log1p' | 'linear';
  y_quantity: 'flux_density';
  y_unit: 'T';
  points: Array<[number, number]>;
}

export interface PublicMaterialModel {
  id: string;
  display_name: string;
  kind: 'electrical_steel' | 'permanent_magnet' | 'conductor';
  model_kind: 'nonlinear_bh' | 'linear_recoil' | 'electromagnetic_region';
  model_revision: string;
  model_hash: string;
  properties: Record<string, number | string | number[]>;
  capabilities: PublicMaterialCapabilities;
  curve?: PublicMaterialCurve | null;
  limitations: string[];
  source?: {
    label: string;
    url: string;
  } | null;
}

export const DEFAULT_CONFIG: MotorConfig = {
  schema_version: '1.0',
  topology: 'SPM',
  stator: {
    OD_mm: 200,
    ID_mm: 120,
    slot_count: 12,
    stack_length_mm: 100,
    // A 6 mm body opening plus 1.5 mm shoe overhang per side leaves a 3 mm
    // physical mouth. The 26.2 mm yoke-side tooth leaves a 16.7 mm slot body,
    // replacing the old full-depth 2-to-17.3 mm triangular winding pocket.
    slot_opening_mm: 6,
    tooth_width_mm: 26.2,
    yoke_thickness_mm: 18,
    tooth_shoe_enabled: true,
    tooth_shoe_height_mm: 2.5,
    tooth_shoe_overhang_mm: 1.5,
  },
  rotor: {
    OD_mm: 110,
    ID_mm: 30,
    magnet_thickness_mm: 4,
    magnet_width_mm: 31.4,
    pole_count: 8,
    magnet_embrace: 0.7,
    bridge_thickness_mm: 1,
    ipm_topology: 'flat_buried',
    flat_buried_magnet_shape: 'straight',
    side_bridge_thickness_mm: 1.2,
    pocket_clearance_mm: 0.25,
    magnet_angle_deg: 0,
    v_angle_deg: 60,
    v_depth_mm: 8,
    inner_web_thickness_mm: 2,
    outer_bridge_thickness_mm: 1.5,
  },
  winding: {
    type: 'concentrated',
    turns_per_coil: 15,
    layers: 1,
    parallel_paths: 2,
  },
  materials: {
    stator_steel: 'M350-50A',
    rotor_steel: 'M350-50A',
    magnet_grade: 'N42',
    conductor: 'copper',
  },
  solve_params: {
    solve_quality: 'standard',
    rotor_sweep_range_deg: 60,
    rotor_step_deg: 15,
    mesh_density: 'normal',
    mesh_source: 'native',
    mesher: 'gmsh',
    corner_refinement: true,
    rotor_rotation_model: 'remesh_per_step',
    torque_method: 'weighted_stress',
    nonlinear_solver: 'picard',
    linear_solver_preconditioner: 'direct',
    current_amplitude_A: 30,
    current_amplitude_convention: 'rms',
    current_angle_deg: 0,
    excitation_mode: 'sinusoidal',
    commutation_advance_deg: 0,
    phase_connection: 'wye',
    rated_speed_rpm: 2400,
  },
  solve_options: {
    torque_sweep: true,
    back_emf: true,
    flux_density: true,
    cogging_torque: false,
    torque_speed_envelope: false,
    thd_analysis: true,
  },
};

export function cloneDefaultConfig(): MotorConfig {
  return structuredClone(DEFAULT_CONFIG);
}
