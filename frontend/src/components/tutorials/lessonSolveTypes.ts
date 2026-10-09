/**
 * Solve/field payload shapes shared by the tutorial lessons and the private
 * workspace.
 *
 * These declarations were moved out of src/api/client.ts so the tutorial tree
 * owns them and can stay inside the public boundary. api/client.ts re-exports
 * every name below, so its other consumers import from exactly the same place
 * they always did.
 */

/** Solve progress event from SSE */
export interface SolveProgressDetail {
  parent_stage?: string;
  solve_kind?: string;
  timing_key?: string;
  timing_label?: string;
  timing_elapsed_ms?: number;
  position_index?: number;
  total_positions?: number;
  completed_positions?: number;
  elec_deg?: number;
  mtpa_gamma_deg?: number;
  mtpa_avg_torque_Nm?: number;
  mtpa_status?: string;
  message?: string;
  iteration?: number;
  max_iterations?: number;
  residual?: number;
  tol?: number;
  assembly_ms?: number;
  linear_solve_ms?: number;
  worst_element?: number | null;
  converged?: boolean;
  /** Gmsh remesh-per-step pipeline: solve meshes ready so far (base
   * builds + congruence-rotated derivations). Rides on `*_mesh` stage
   * ticks so the UI can show a live "Meshing N/M" step. */
  mesh_completed?: number;
  /** Gmsh remesh-per-step pipeline: total solve meshes the sweep needs. */
  mesh_total?: number;
}

export interface SolveProgress {
  position: number;
  total: number;
  torque_Nm?: number;
  angle_deg?: number;
  phase_a_V?: number;
  phase_b_V?: number;
  phase_c_V?: number;
  field_line_frame?: LiveFieldLineFrameData;
  solver_detail?: SolveProgressDetail;
  elapsed_s: number;
  stage?: string;
}

export interface TutorialLessonOneDesignOptions {
  airgapMm?: number;
  magnetArcPct?: number;
  magnetThicknessMm?: number;
  meshDensity?: 'coarse' | 'normal' | 'fine';
}

/**
 * Mesh preview data from magneto2d --mesh-only mode.
 */
export interface MeshRenderDataBase {
  config_summary: {
    topology: string;
    slots: number;
    poles: number;
    stator_od_mm: number;
    rotor_od_mm: number;
    magnet_thickness_mm: number;
    stack_length_mm: number;
  };
  mesh_info: {
    num_nodes: number;
    num_triangles: number;
    pole_pitch_deg: number;
    n_pole_pitches: number;
    total_span_deg: number;
    mesh_source_detail?: string;
    mesh_source?: string;
    mesh_density?: string;
    corner_refinement?: boolean;
    refinement_features?: string[];
    geometry_ir_version?: string;
    gmsh_base_lc_mm?: number;
    gmsh_far_lc_mm?: number;
  };
  nodes_mm: [number, number][];
  triangles: [number, number, number][];
  regions: string[];
  n_pole_pitches: number;
  total_span_deg: number;
}

export interface MeshPreviewData extends MeshRenderDataBase {
  generation_time_ms: number;
  solve_mesh_key?: string | null;
}

export interface FieldLineContourLevel {
  level: number;
  segments_mm: [number, number, number, number][];
  segment_b_mag_t?: number[];
  segment_bx_t?: number[];
  segment_by_t?: number[];
}

export interface AirgapBrBtBin {
  mech_angle_deg: number;
  b_magnitude_t?: number;
  br_t: number;
  bt_t: number;
  br_bt_t2: number;
  samples: number;
}

export interface AirgapBrBtProfile {
  span_deg: number;
  bin_count: number;
  sample_count: number;
  bins: AirgapBrBtBin[];
}

export interface AirgapFieldRecords {
  centroid_x_mm?: number[];
  centroid_y_mm?: number[];
  b_magnitude_t?: number[];
  b_radial_t?: number[];
  b_tangential_t?: number[];
}

export interface AirgapFieldStats {
  count: number;
  mean_t: number;
  p95_t: number;
  max_t: number;
}

export interface AirgapFieldArtifactRef {
  artifact_id: string;
  format: string;
  media_type: string;
  schema_version: string;
  record_count: number;
  byte_count?: number | null;
  relative_path?: string | null;
}

export interface FieldLineFrameArtifactRef {
  artifact_id: string;
  format: string;
  media_type: string;
  schema_version: string;
  record_count: number;
  byte_count?: number | null;
  relative_path?: string | null;
}

export interface FieldLinePlotData extends MeshRenderDataBase {
  /** Rotor/electrical sweep angle baked into this solved frame's geometry. */
  angle_deg?: number;
  element_b_mag_t?: number[];
  element_bx_t?: number[];
  element_by_t?: number[];
  airgap_brbt?: AirgapBrBtProfile | null;
  airgap_b_records?: AirgapFieldRecords | null;
  airgap_b_stats?: AirgapFieldStats | null;
  airgap_b_artifact?: AirgapFieldArtifactRef | null;
  field_frame_artifact?: FieldLineFrameArtifactRef | null;
  full_field_frame_artifact?: FieldLineFrameArtifactRef | null;
  contour_levels: FieldLineContourLevel[];
  az_min: number;
  az_max: number;
}

export interface FollowFluxMetrics {
  working_gap_mean_b_t: number;
  outside_field_mean_b_t: number;
  return_path_mean_b_t?: number | null;
  peak_b_t: number;
  teaching_depth_mm?: number;
  north_face_area_mm2?: number;
  north_face_mean_bn_t?: number;
  north_face_flux_wb?: number;
  south_face_flux_wb?: number;
  probe_tangential_b_t?: number | null;
  probe_radius_mm?: number | null;
  iron_mean_b_t?: number | null;
  iron_mean_h_a_per_m?: number | null;
  iron_effective_mu_rel?: number | null;
  iron_saturated_fraction?: number | null;
  iron_saturation_threshold_t?: number | null;
  nonlinear_iterations?: number | null;
  tooth_mean_b_t?: number | null;
  tooth_tip_mean_b_t?: number | null;
  tooth_saturated_fraction?: number | null;
  airgap_mean_b_t?: number | null;
  airgap_flux_per_depth_wb_per_m?: number | null;
  wire_mean_bx_t?: number | null;
  wire_mean_by_t?: number | null;
  wire_force_x_n?: number | null;
  wire_force_y_n?: number | null;
  wire_force_magnitude_n?: number | null;
  wire_force_bil_n?: number | null;
  center_bx_t?: number | null;
  center_by_t?: number | null;
  center_b_t?: number | null;
  center_field_angle_deg?: number | null;
}

export interface TeachingBhPoint {
  b_t: number;
  h_a_per_m: number;
}

export interface FollowFluxFieldData extends FieldLinePlotData {
  schema_version: string;
  fixture: 'follow_flux';
  steel_return: boolean;
  steel_shape: 'bar' | 'plate' | 'puck';
  steel_center_x_mm: number;
  steel_center_y_mm: number;
  magnet_center_x_mm: number;
  magnet_center_y_mm: number;
  magnet_angle_deg: number;
  /** Lesson 1's optional second magnet. Absent on the fixtures that never
   * offer one, so every reader has to treat it as optional. */
  magnet2_enabled?: boolean;
  magnet2_center_x_mm?: number;
  magnet2_center_y_mm?: number;
  magnet2_angle_deg?: number;
  steel_angle_deg: number;
  solved: boolean;
  generation_time_ms: number;
  metrics?: FollowFluxMetrics | null;
  bh_curve?: TeachingBhPoint[] | null;
}

export interface AirgapTaxFieldData extends Omit<FollowFluxFieldData, 'fixture' | 'steel_shape'> {
  fixture: 'magnetic_circuit';
  steel_shape: 'circuit';
  airgap_mm: number;
}

export interface CurrentFieldData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'current_wire';
  current_a: number;
  wire_current_a: number;
  wire_radius_mm: number;
}

export interface IronSaturationFieldData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'iron_saturation';
  current_a: number;
  wire_current_a: number;
  wire_radius_mm: number;
  iron_ring_inner_radius_mm: number;
  iron_ring_outer_radius_mm: number;
  bh_curve: TeachingBhPoint[];
}

export interface IronSaturationToothFieldData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'iron_saturation_tooth';
  current_a: number;
  wire_current_a: number;
  coil_turns: number;
  airgap_mm: number;
  tooth_width_mm: number;
  bh_curve: TeachingBhPoint[];
}

export interface IronSaturationSpmToothFieldData
  extends Omit<IronSaturationToothFieldData, 'fixture'> {
  fixture: 'iron_saturation_spm_tooth';
  surface_magnet: true;
  magnet_grade: 'N42';
  magnet_thickness_mm: number;
  magnet_width_mm: number;
}

export interface FieldForceData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'current_force';
  current_a: number;
  wire_current_a: number;
  wire_radius_mm: number;
  teaching_depth_mm: number;
  pole_gap_mm: number;
  magnet_inner_x_mm: number;
  magnet_outer_x_mm: number;
  magnet_half_height_mm: number;
}

export interface FieldForceMotorData extends Omit<FieldForceData, 'fixture'> {
  fixture: 'current_force_motor';
  motor_effect_solve: true;
  loop_angle_deg: number;
  fem_reference_angle_deg: 90;
  active_side_force_y_n: number;
  opposite_side_force_y_n: number;
  side_force_magnitude_n: number;
  side_force_bil_n: number;
  net_force_y_n: number;
  loop_active_side_spacing_mm: number;
  torque_max_nm: number;
  torque_nm: number;
  projection_method: 'fresh_2d_fem_side_force_plus_3d_lever_arm';
}

export interface FieldForceWireData extends Omit<FieldForceData, 'fixture'> {
  fixture: 'current_force_wire';
  wire_only: true;
  contour_reference_current_a: number;
  contour_interval_is_fixed: true;
}

export interface FieldForceMagnetData extends FieldForceData {
  magnet_only: true;
}

export interface LinearMotorCapstoneFieldData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'linear_motor_capstone';
  current_a: number;
  airgap_mm: number;
  magnet_orientations: [number, number, number, number];
  winding_signs: [1, -1, 1, -1];
  winding_spacing_mm: number;
  winding_turns: number;
  wire_radius_mm: number;
  wire_center_y_mm: number;
  teaching_depth_mm: number;
  net_force_x_n: number | null;
  net_force_y_n: number | null;
  net_force_magnitude_n: number | null;
  force_method: 'volume_lorentz_j_cross_b';
}

export type RotorChaseFieldSource = 'stator' | 'rotor' | 'combined';

export type RotorChaseSourceKind = 'pm' | 'electromagnet';

export interface RotorChaseFieldData extends Omit<FieldForceData, 'fixture'> {
  fixture:
    | 'rotor_chase_stator'
    | 'rotor_chase_rotor'
    | 'rotor_chase_combined'
    | 'rotor_chase_coil_stator'
    | 'rotor_chase_coil_rotor'
    | 'rotor_chase_coil_combined';
  field_source: RotorChaseFieldSource;
  magnet_only: boolean;
  source_kind: RotorChaseSourceKind;
  source_current_a: number;
  rotor_angle_deg: number;
  rotor_length_mm: number;
  rotor_thickness_mm: number;
  stator_magnet_width_mm: number;
  stator_magnet_half_height_mm: number;
  coil_radius_mm: number;
  coil_y_mm: number;
  coil_turns: number;
}

export interface RotatingFieldFrameData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'rotating_field';
  field_component: 'combined' | 'phase_a' | 'phase_b';
  electrical_angle_deg: number;
  peak_current_a: number;
  phase_a_current_a: number;
  phase_b_current_a: number;
  coil_radius_mm: number;
  coil_offset_mm: number;
}

export interface RotatingFieldSweepData {
  schema_version: string;
  fixture: 'rotating_field';
  peak_current_a: number;
  mesh_density: 'normal';
  frame_count: number;
  frames: RotatingFieldFrameData[];
  phase_a_frames: RotatingFieldFrameData[];
  phase_b_frames: RotatingFieldFrameData[];
}

export interface RotatingFieldMotorFrameData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'rotating_field_motor';
  field_component: 'combined' | 'stator' | 'rotor';
  electrical_angle_deg: number;
  field_target_angle_deg: number;
  rotor_angle_deg: number;
  torque_angle_deg: number;
  peak_current_a: number;
  phase_a_current_a: number;
  phase_b_current_a: number;
  rotor_radius_mm: number;
  core_inner_mm: number;
  core_outer_mm: number;
  core_half_width_mm: number;
  coil_radius_mm: number;
  coil_center_mm: number;
  coil_side_mm: number;
  coil_turns: number;
}

export interface RotatingFieldMotorSweepData {
  schema_version: string;
  fixture: 'rotating_field_motor';
  field_component: 'combined' | 'stator' | 'rotor';
  peak_current_a: number;
  frame_count: number;
  electrical_angles_deg: number[];
  rotor_motion_default: true;
  rotor_lag_deg: number;
  frames: RotatingFieldMotorFrameData[];
}

export type ThreePhaseMotorFieldComponent =
  | 'combined'
  | 'stator'
  | 'rotor'
  | 'phase_a'
  | 'phase_b'
  | 'phase_c'
  | 'open_c';

export interface ThreePhaseMotorFrameData extends Omit<FollowFluxFieldData, 'fixture'> {
  fixture: 'three_phase_motor';
  field_component: ThreePhaseMotorFieldComponent;
  electrical_angle_deg: number;
  field_target_angle_deg: number;
  rotor_angle_deg: number;
  torque_angle_deg: number;
  peak_current_a: number;
  phase_a_current_a: number;
  phase_b_current_a: number;
  phase_c_current_a: number;
  phase_current_sum_a: number;
  phase_c_open: boolean;
  rotor_radius_mm: number;
  core_inner_mm: number;
  core_outer_mm: number;
  core_half_width_mm: number;
  coil_radius_mm: number;
  coil_center_mm: number;
  coil_side_mm: number;
  coil_turns: number;
}

export interface ThreePhaseMotorSweepData {
  schema_version: string;
  fixture: 'three_phase_motor';
  field_component: ThreePhaseMotorFieldComponent;
  peak_current_a: number;
  frame_count: number;
  electrical_angles_deg: number[];
  rotor_motion_default: true;
  rotor_lag_deg: number;
  frames: ThreePhaseMotorFrameData[];
}

export interface LiveFieldLinePlotSnapshot {
  config_summary?: MeshRenderDataBase['config_summary'];
  mesh_info?: MeshRenderDataBase['mesh_info'];
  nodes_mm?: MeshRenderDataBase['nodes_mm'];
  triangles?: MeshRenderDataBase['triangles'];
  regions?: string[];
  n_pole_pitches?: number;
  total_span_deg?: number;
  element_b_mag_t?: number[];
  element_bx_t?: number[];
  element_by_t?: number[];
  airgap_brbt?: AirgapBrBtProfile | null;
  airgap_b_records?: AirgapFieldRecords | null;
  airgap_b_stats?: AirgapFieldStats | null;
  airgap_b_artifact?: AirgapFieldArtifactRef | null;
  field_frame_artifact?: FieldLineFrameArtifactRef | null;
  full_field_frame_artifact?: FieldLineFrameArtifactRef | null;
  contour_levels: FieldLineContourLevel[];
  az_min: number;
  az_max: number;
}

export interface LiveFieldLineFrameData extends LiveFieldLinePlotSnapshot {
  angle_deg: number;
  noload_plot?: LiveFieldLinePlotSnapshot | null;
}

export interface TorqueWaveformData {
  electrical_angle_deg: number[];
  torque_Nm: number[];
  torque_energy_fd_Nm?: number[] | null;
  torque_coenergy_fd_Nm?: number[] | null;
}

export interface TutorialLessonOneSolveResult {
  summary?: Record<string, unknown>;
  torque_waveform?: TorqueWaveformData | null;
  solve_metadata?: Record<string, unknown>;
  field_line_frames?: LiveFieldLineFrameData[];
  live_field_line_frames?: LiveFieldLineFrameData[];
  tutorial_solve?: {
    mode: string;
    sweep_range_deg: number;
    rotor_step_deg: number;
    positions: number;
    field_frame_count: number;
  };
}

export interface TutorialLessonOneSolveOptions extends TutorialLessonOneDesignOptions {
  phaseCurrentA?: number;
  currentAngleDeg?: number;
}

export type LessonOneFieldCompositionSource = 'pm' | 'armature';

/** Exact source-separated Lesson 9 field sweep, aligned to the balanced solve grid. */
export interface LessonOneFieldCompositionResult {
  schema_version: string;
  cache_key?: string;
  cache_hit: boolean;
  source: 'magneto2d_exact_zero_current' | 'magneto2d_exact_br_zero';
  magnet_remanence_scale?: number;
  current_amplitude_A?: number;
  current_angle_deg?: number;
  frame_count: number;
  elapsed_s?: number;
  frames: LiveFieldLineFrameData[];
}

export interface FollowFluxOptions {
  steelReturn?: boolean;
  steelShape?: 'bar' | 'plate' | 'puck';
  steelCenterXMm?: number;
  steelCenterYMm?: number;
  magnetCenterXMm?: number;
  magnetCenterYMm?: number;
  magnetAngleDeg?: number;
  /** Lesson 1's second magnet, off unless the lesson reaches the pair stage.
   * When false the backend keeps the exact single-magnet geometry. */
  magnet2Enabled?: boolean;
  magnet2CenterXMm?: number;
  magnet2CenterYMm?: number;
  magnet2AngleDeg?: number;
  steelAngleDeg?: number;
  meshDensity?: 'coarse' | 'normal' | 'fine';
}

export interface FieldLineFrameArtifactPayload {
  schema_version: string;
  position_index: number;
  electrical_angle_deg: number;
  record_count: number;
  field_line_frame: LiveFieldLineFrameData;
}
