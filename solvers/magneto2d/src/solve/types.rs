use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::mesh::{MeshInfo, TriMesh};
use crate::postprocess::{EnergyByRegionSummary, FieldSummary, MagnetFieldEnergyDetailSummary};
use crate::sources::SlotExcitationContribution;
use crate::sparse::PcgProfile;

/// Full solve report (single angle).
#[derive(Debug, Serialize)]
pub struct SolveReport {
    pub config_summary: ConfigSummary,
    pub operating_point: OperatingPointSummary,
    pub mesh_info: MeshInfo,
    pub solve_info: SolveInfo,
    pub results: FieldSummary,
    pub field_plot: FieldPlotData,
}

/// Rotor sweep report with torque waveform and back-EMF.
#[derive(Debug, Serialize)]
pub struct SweepReport {
    pub config_summary: ConfigSummary,
    pub operating_point: OperatingPointSummary,
    pub mesh_info: MeshInfo,
    pub sweep: SweepData,
}

/// Batch of imported per-angle solve meshes for Python-owned remesh sweeps.
#[derive(Debug, Deserialize)]
pub struct ImportedMeshBatchInput {
    #[serde(default)]
    pub keep_first_field_plot: bool,
    #[serde(default)]
    pub keep_all_field_plots: bool,
    pub jobs: Vec<ImportedMeshBatchJob>,
}

#[derive(Debug, Deserialize)]
pub struct ImportedMeshBatchJob {
    pub rotor_angle_deg: f64,
    pub solve_mesh_artifact: SolveMeshArtifact,
}

#[derive(Debug, Serialize)]
pub struct ImportedMeshBatchReport {
    pub reports: Vec<Value>,
}

#[derive(Debug, Serialize)]
pub struct SweepData {
    pub rotor_positions_elec_deg: Vec<f64>,
    #[serde(rename = "phase_current_a_A", skip_serializing_if = "Option::is_none")]
    pub phase_current_a_a: Option<Vec<f64>>,
    #[serde(rename = "phase_current_b_A", skip_serializing_if = "Option::is_none")]
    pub phase_current_b_a: Option<Vec<f64>>,
    #[serde(rename = "phase_current_c_A", skip_serializing_if = "Option::is_none")]
    pub phase_current_c_a: Option<Vec<f64>>,
    pub torque_nm: Vec<f64>,
    pub torque_contour_centered_nm: Option<Vec<f64>>,
    pub avg_torque_contour_centered_nm: Option<f64>,
    pub torque_mst_nm: Vec<f64>,
    pub torque_arkkio_nm: Vec<f64>,
    pub avg_torque_arkkio_nm: f64,
    pub energy_potential_j: Vec<f64>,
    pub energy_coenergy_j: Vec<f64>,
    pub energy_field_j: Vec<f64>,
    pub energy_field_by_region_j: Vec<EnergyByRegionSummary>,
    pub energy_field_magnet_detail_j: Vec<MagnetFieldEnergyDetailSummary>,
    pub energy_current_source_work_j: Vec<f64>,
    pub energy_pm_source_work_j: Vec<f64>,
    pub energy_pm_source_work_magnet_detail_j: Vec<MagnetFieldEnergyDetailSummary>,
    pub energy_pm_self_j: Vec<f64>,
    pub energy_potential_with_pm_self_j: Vec<f64>,
    pub energy_coenergy_by_region_j: Vec<EnergyByRegionSummary>,
    pub energy_coenergy_magnet_detail_j: Vec<MagnetFieldEnergyDetailSummary>,
    pub torque_energy_fd_nm: Vec<f64>,
    pub torque_coenergy_fd_nm: Vec<f64>,
    pub avg_torque_energy_fd_nm: f64,
    pub avg_torque_coenergy_fd_nm: f64,
    pub torque_weighted_stress_nm: Option<Vec<f64>>,
    pub avg_torque_weighted_stress_nm: Option<f64>,
    pub torque_weighted_stress_centered_nm: Option<Vec<f64>>,
    pub avg_torque_weighted_stress_centered_nm: Option<f64>,
    pub flux_linkage_a_wb: Vec<f64>,
    pub flux_linkage_b_wb: Vec<f64>,
    pub flux_linkage_c_wb: Vec<f64>,
    pub back_emf_a_v: Vec<f64>,
    pub back_emf_b_v: Vec<f64>,
    pub back_emf_c_v: Vec<f64>,
    pub avg_torque_nm: f64,
    pub avg_torque_mst_nm: f64,
    pub torque_crosscheck_delta_nm: f64,
    pub torque_crosscheck_delta_pct: Option<f64>,
    pub torque_ripple_pct: f64,
    pub back_emf_peak_v: f64,
    /// `Option<f64>` rather than `f64`: serializes to JSON `null` when
    /// the sweep is shorter than one full electrical cycle and the
    /// fundamental can't be extracted via DFT. Mirrors the Python-side
    /// fallback in `backend/solver.py`. Before this change, partial
    /// sweeps silently emitted 0.0 for the fundamental, producing
    /// phantom -100% deltas vs FEMM in the Phase A Test Results table.
    pub back_emf_fundamental_v: Option<f64>,
    pub back_emf_peak_physical_v: f64,
    pub back_emf_fundamental_peak_physical_v: Option<f64>,
    pub back_emf_fundamental_rms_v: Option<f64>,
    pub back_emf_thd_pct: Option<f64>,
    pub cogging_torque_nm: Option<f64>,
    pub cogging_torque_method: Option<String>,
    pub cogging_rotor_positions_elec_deg: Option<Vec<f64>>,
    pub cogging_torque_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_contour_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_area_mst_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_arkkio_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_weighted_stress_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_weighted_stress_centered_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_contour_inner_waveform_nm: Option<Vec<f64>>,
    pub cogging_torque_contour_outer_waveform_nm: Option<Vec<f64>>,
    pub total_time_ms: u64,
    pub rated_speed_rpm: u32,
    pub loaded_flux_linkage_a_wb: Vec<f64>,
    pub loaded_flux_linkage_b_wb: Vec<f64>,
    pub loaded_flux_linkage_c_wb: Vec<f64>,
    pub loaded_back_emf_a_v: Vec<f64>,
    pub loaded_back_emf_b_v: Vec<f64>,
    pub loaded_back_emf_c_v: Vec<f64>,
    pub no_load_flux_linkage_a_wb: Vec<f64>,
    pub no_load_flux_linkage_b_wb: Vec<f64>,
    pub no_load_flux_linkage_c_wb: Vec<f64>,
    pub no_load_back_emf_a_v: Vec<f64>,
    pub no_load_back_emf_b_v: Vec<f64>,
    pub no_load_back_emf_c_v: Vec<f64>,
    pub no_load_back_emf_a_physical_v: Vec<f64>,
    pub no_load_back_emf_b_physical_v: Vec<f64>,
    pub no_load_back_emf_c_physical_v: Vec<f64>,
    pub slot_excitation_frames: Vec<SlotExcitationFrame>,
    pub loaded_nonlinear_iterations: Vec<usize>,
    pub no_load_nonlinear_iterations: Vec<usize>,
    pub core_loss_w: f64,
    pub hysteresis_loss_w: f64,
    pub eddy_current_loss_w: f64,
    pub stator_core_mass_kg: f64,
    /// Per-triangle stator core-loss density [W/m³] for thermal coupling.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub core_loss_density_w_per_m3: Option<Vec<f64>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SlotExcitationFrame {
    pub angle_deg: f64,
    pub source_current_angle_deg: f64,
    pub phase_current_a: [f64; 3],
    pub contributions: Vec<SlotExcitationContribution>,
}

#[derive(Debug, Serialize, Clone)]
pub struct ConfigSummary {
    pub topology: String,
    pub slots: u32,
    pub poles: u32,
    pub stator_od_mm: f64,
    pub rotor_od_mm: f64,
    pub magnet_thickness_mm: f64,
    pub stack_length_mm: f64,
    pub current_amplitude_a: f64,
    pub current_angle_deg: f64,
    /// Echo of the resolved rotor_rotation_model so downstream tooling
    /// (QA dashboard, parity diagnostics) can tell which mesh-rotation
    /// path actually ran from the output JSON alone. Always "fixed_mesh"
    /// or "remesh_per_step" -- matches `rotor_rotation_model_label()`.
    pub rotor_rotation_model: String,
}

#[derive(Debug, Serialize, Clone)]
pub struct OperatingPointSummary {
    pub requested_current_amplitude_a: Option<f64>,
    pub resolved_current_amplitude_a: f64,
    pub current_amplitude_convention: String,
    pub resolved_phase_current_peak_a: f64,
    pub current_amplitude_rule: String,
    pub requested_current_angle_deg: Option<f64>,
    pub resolved_current_angle_deg: f64,
    pub current_angle_reference: String,
    pub resolution_rule: String,
    pub sweep_current_rule: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub excitation_mode: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub commutation_advance_deg: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase_connection: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub excitation_convention_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved_conducting_phase_plateau_a: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct SolveInfo {
    pub num_dofs: usize,
    pub assembly_time_ms: u64,
    pub solve_time_ms: u64,
    pub total_time_ms: u64,
    pub solver_method: String,
    pub max_az: f64,
    pub min_az: f64,
    pub nonlinear_enabled: bool,
    pub nonlinear_iterations: usize,
    pub nonlinear_residual_history: Vec<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub profile: Option<SolveProfile>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct SolveProfile {
    pub direct_csr_enabled: bool,
    pub linear_solve_calls: u64,
    pub newton_correction_calls: u64,
    pub csr_pattern_build_ms: u64,
    pub direct_csr_refill_ms: u64,
    pub linear_stiffness_assembly_ms: u64,
    pub linear_source_assembly_ms: u64,
    pub constraint_apply_ms: u64,
    pub csr_conversion_ms: u64,
    pub dirichlet_apply_ms: u64,
    pub residual_eval_ms: u64,
    pub tangent_assembly_ms: u64,
    pub field_compute_ms: u64,
    pub material_update_ms: u64,
    pub line_search_total_ms: u64,
    pub line_search_candidate_count: u64,
    pub line_search_attempt_count: u64,
    pub line_search_field_compute_ms: u64,
    pub line_search_material_update_ms: u64,
    pub line_search_residual_eval_ms: u64,
    pub postprocess_summary_ms: u64,
    pub slot_excitation_summary_ms: u64,
    pub energy_summary_ms: u64,
    pub direct_cholesky_solves: u64,
    pub direct_cholesky_solve_ms: u64,
    pub direct_symbolic_builds: u64,
    pub direct_numeric_factorizations: u64,
    pub direct_cache_hits: u64,
    pub direct_pattern_mismatches: u64,
    pub direct_pcg_fallbacks: u64,
    pub pcg: PcgProfile,
}

pub type MagnetizationAngle = f64;
pub type CurrentDensity = f64;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportedPhysicsContract {
    pub version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub topology_hint: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub units: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub motion: Option<ImportedPhysicsMotion>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub boundary_policy: Option<ImportedBoundaryPolicy>,
    #[serde(default)]
    pub regions: Vec<ImportedPhysicsRegion>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportedPhysicsMotion {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rotor_angle_mech_deg: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rotor_state: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportedBoundaryPolicy {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outer_boundary: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sector_edges: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportedPhysicsRegion {
    pub id: String,
    pub kind: String,
    pub material: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub motion_group: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_group: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub magnetization_angle_deg: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub current_density_a_per_m2: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub winding: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SolveMeshArtifact {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub physics_contract: Option<ImportedPhysicsContract>,
    pub mesh: TriMesh,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rotor_angle_mech_deg: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub element_region_ids: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub element_magnetization: Option<Vec<Option<MagnetizationAngle>>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub element_current_density_a_per_m2: Option<Vec<Option<CurrentDensity>>>,
}

impl SolveMeshArtifact {
    pub fn from_mesh(mesh: TriMesh) -> Self {
        Self {
            physics_contract: None,
            mesh,
            rotor_angle_mech_deg: None,
            element_region_ids: None,
            element_magnetization: None,
            element_current_density_a_per_m2: None,
        }
    }
}

/// Mesh preview report: geometry only, no field solve.
#[derive(Debug, Serialize)]
pub struct MeshPreviewReport {
    pub config_summary: ConfigSummary,
    pub mesh_info: MeshInfo,
    /// Node coordinates [x, y] in mm (not meters -- for frontend rendering).
    pub nodes_mm: Vec<[f64; 2]>,
    /// Triangle connectivity: 3 node indices per element.
    pub triangles: Vec<[usize; 3]>,
    /// Region tag per triangle (string for JSON readability).
    pub regions: Vec<String>,
    /// Number of pole pitches modeled.
    pub n_pole_pitches: u32,
    /// Total angular span in degrees.
    pub total_span_deg: f64,
    /// Generation time in milliseconds.
    pub generation_time_ms: u64,
    /// Full solve-ready mesh artifact used to skip remeshing on solve startup.
    pub solve_mesh_artifact: SolveMeshArtifact,
}

/// Solved mesh data for contour-based field-line rendering.
#[derive(Debug, Serialize)]
pub struct FieldPlotData {
    /// Node coordinates [x, y] in mm for frontend rendering.
    pub nodes_mm: Vec<[f64; 2]>,
    /// Triangle connectivity: 3 node indices per element.
    pub triangles: Vec<[usize; 3]>,
    /// Region tag per triangle (string for JSON readability).
    pub regions: Vec<String>,
    /// Solved nodal magnetic vector potential A_z.
    pub az_nodal: Vec<f64>,
    /// Number of pole pitches modeled.
    pub n_pole_pitches: u32,
    /// Total angular span in degrees.
    pub total_span_deg: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct AirgapBrBtProfile {
    pub span_deg: f64,
    pub bin_count: usize,
    pub sample_count: usize,
    pub bins: Vec<AirgapBrBtBin>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AirgapBrBtBin {
    pub mech_angle_deg: f64,
    pub br_t: f64,
    pub bt_t: f64,
    pub br_bt_t2: f64,
    pub samples: usize,
}
