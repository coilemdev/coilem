//! Top-level solve orchestrator: mesh → assemble → solve → postprocess.
//! Supports single-angle and multi-angle rotor sweep for torque/back-EMF.
//!
//! Multi-pole-pitch: automatically computes n_pole_pitches = lcm(S,P)/P
//! so fractional-slot motors (e.g. 12s/8p → 3 pole pitches) model the
//! minimum repeating unit, allowing flux closure through the stator yoke.

use std::f64::consts::PI;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use rayon::prelude::*;
use serde::Serialize;

use crate::assembly::{assemble_source, assemble_stiffness, triangle_gradients};
use crate::field::{
    BoundarySet, ConvergenceReport, ElementMaterialState, FieldEnergyPerUnitDepth, FieldSolution,
    FieldSolveProfile, LinearSolveOptions, LinearSolver, MagnetostaticProblem, NonlinearAlgorithm,
    NonlinearSolveOptions, PairedBoundary, PairedBoundaryKind, PcgPreconditioner,
    PreparedFieldSystem, SolveOptions, SolveTimings,
};
use crate::materials::MaterialProps;
use crate::mesh::{AirgapBand, MeshInfo, Region};
use crate::motor::{MotorConfig, SolveParams};
use crate::postprocess::{
    summarize_fields, CoreLossSummary,
    ElementField, EnergyByRegionSummary, EnergyFunctionalSummary, FieldSummary,
    MagnetFieldEnergyDetailSummary, PmSidewallQuadratureDiagnosticSummary,
    PmSidewallQuadratureSelectedElement,
};
use crate::sources::{
    compute_current_densities_from_phase_currents,
    compute_slot_excitation_summary_from_phase_currents, phase_currents_for_excitation,
    source_phase_currents_for_excitation,
};
use crate::sparse::{
    pcg_solve_with_guess_options, pcg_solve_with_guess_options_profiled, CooMatrix,
    ElementCsrAssemblyPattern, PcgExecution, PcgOptions, PcgPreconditionerKind,
};

mod context;
mod mesh_metadata;
mod metrics;
mod model;
mod newton;
mod nonlinear;
mod picard;
mod problem;
mod types;

use self::context::{
    config_summary_for, generate_solve_mesh_at_angle, remesh_ctx_for_angle, setup_context,
    single_angle_context_artifact, SolveContext,
};
use self::metrics::{
    assemble_back_emf_sweep_metrics, assemble_torque_sweep_metrics,
    centered_endpoint_period_waveform, cogging_period_electrical_deg, finite_difference_waveform,
    torque_metric_centering_span_deg, waveform_mean,
};
#[cfg(test)]
use self::metrics::{
    back_emf_from_flux_linkage, back_emf_thd_pct, centered_no_load_cogging_waveform,
    covers_integer_cogging_period, first_harmonic_peak, harmonic_peak, torque_ripple_pct,
};
pub(crate) use self::model::effective_magnet_embrace;
use self::model::MachineModel;
use self::newton::run_newton_nonlinear_loop;
use self::nonlinear::{
    apply_nonlinear_warm_start, build_nonlinear_warm_start, nonlinear_diagnostics_path,
    resolve_newton_current_scales, resolve_nonlinear_solve_config,
    write_nonlinear_diagnostics_artifact, NonlinearDiagnosticsArtifact, NonlinearSolverKind,
    NonlinearWarmStart,
};
#[cfg(test)]
use self::nonlinear::{default_nonlinear_tol_for_quality, NonlinearSolveConfig};
use self::picard::run_picard_nonlinear_loop;
#[cfg(test)]
use self::picard::{backtracked_relaxation, cap_mu_rel_step, PicardRelaxationState};
use self::problem::SolveProblem;
pub use self::types::{
    AirgapBrBtBin, AirgapBrBtProfile, ConfigSummary, FieldPlotData, ImportedMeshBatchInput,
    ImportedMeshBatchReport, MeshPreviewReport, OperatingPointSummary, SlotExcitationFrame,
    SolveInfo, SolveMeshArtifact, SolveProfile, SolveReport, SweepData, SweepReport,
};

#[derive(Debug, Clone)]
struct AngleSolveDiagnostics {
    assembly_time_ms: u64,
    solve_time_ms: u64,
    solver_method: String,
    nonlinear_enabled: bool,
    nonlinear_iterations: usize,
    nonlinear_residual_history: Vec<f64>,
    profile: Option<SolveProfile>,
}

pub(super) struct SolveMatrixPattern {
    prepared: PreparedFieldSystem,
}

struct AngleProgressContext<'a> {
    parent_stage: &'static str,
    solve_kind: &'static str,
    position_index: usize,
    total_positions: usize,
    completed_positions: &'a AtomicUsize,
    elec_deg: f64,
}

/// Compute GCD of two positive integers.
fn gcd(a: u32, b: u32) -> u32 {
    let (mut a, mut b) = (a, b);
    while b != 0 {
        let t = b;
        b = a % b;
        a = t;
    }
    a
}

/// Compute LCM of two positive integers.
fn lcm(a: u32, b: u32) -> u32 {
    a / gcd(a, b) * b
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CoggingTorqueMethod {
    Arkkio,
    Contour,
    AreaMst,
    WeightedStress,
    WeightedStressCentered,
}

struct CoggingPositionOutcome {
    elec_deg: f64,
    contour_nm: f64,
    area_mst_nm: f64,
    arkkio_nm: f64,
    weighted_stress_nm: Option<f64>,
    contour_inner_nm: f64,
    contour_outer_nm: f64,
}

impl CoggingTorqueMethod {
    fn label(self) -> &'static str {
        match self {
            CoggingTorqueMethod::Arkkio => "arkkio",
            CoggingTorqueMethod::Contour => "contour",
            CoggingTorqueMethod::AreaMst => "mst",
            CoggingTorqueMethod::WeightedStress => "weighted_stress",
            CoggingTorqueMethod::WeightedStressCentered => "weighted_stress_centered",
        }
    }

    fn select(self, outcome: &CoggingPositionOutcome) -> f64 {
        match self {
            CoggingTorqueMethod::Arkkio => outcome.arkkio_nm,
            CoggingTorqueMethod::Contour => outcome.contour_nm,
            CoggingTorqueMethod::AreaMst => outcome.area_mst_nm,
            CoggingTorqueMethod::WeightedStress | CoggingTorqueMethod::WeightedStressCentered => {
                outcome.weighted_stress_nm.unwrap_or(outcome.arkkio_nm)
            }
        }
    }
}

fn cogging_torque_method_override() -> Option<CoggingTorqueMethod> {
    let method = std::env::var("MAGNETO2D_COGGING_TORQUE_METHOD").ok()?;
    match method.trim().to_ascii_lowercase().as_str() {
        "" | "auto" | "default" | "product" => None,
        "arkkio" => Some(CoggingTorqueMethod::Arkkio),
        "contour" | "primary" | "primary_contour" => Some(CoggingTorqueMethod::Contour),
        "mst" | "area_mst" | "area_mst_torque" => Some(CoggingTorqueMethod::AreaMst),
        "weighted_stress" | "wst" => Some(CoggingTorqueMethod::WeightedStress),
        "weighted_stress_centered" | "wst_centered" | "centered_wst" => {
            Some(CoggingTorqueMethod::WeightedStressCentered)
        }
        _ => None,
    }
}

fn cogging_torque_method(_config: &MotorConfig) -> CoggingTorqueMethod {
    cogging_torque_method_override().unwrap_or(CoggingTorqueMethod::Arkkio)
}

fn resolve_operating_point(sp: Option<&SolveParams>) -> Result<OperatingPointSummary, String> {
    let requested_current_amplitude_a = sp.and_then(SolveParams::requested_current_a);
    let resolved_current_amplitude_a = sp.map(SolveParams::current_a).unwrap_or(50.0);
    let excitation_mode = sp
        .map(SolveParams::excitation_mode_label)
        .unwrap_or("sinusoidal");
    if !matches!(excitation_mode, "sinusoidal" | "ideal_six_step_120") {
        return Err(format!(
            "unsupported solve_params.excitation_mode '{excitation_mode}'; expected 'sinusoidal' or 'ideal_six_step_120'"
        ));
    }
    let phase_connection = sp.map(SolveParams::phase_connection_label).unwrap_or("wye");
    if phase_connection != "wye" {
        return Err(format!(
            "unsupported solve_params.phase_connection '{phase_connection}'; BLDC MVP supports wye only"
        ));
    }
    let requested_convention = sp
        .and_then(|params| params.current_amplitude_convention.as_deref())
        .unwrap_or("peak");
    let current_amplitude_convention = requested_convention.to_ascii_lowercase();
    if excitation_mode == "ideal_six_step_120" && current_amplitude_convention != "plateau" {
        return Err(format!(
            "ideal_six_step_120 requires current_amplitude_convention='plateau'; received '{current_amplitude_convention}'"
        ));
    }
    if excitation_mode == "sinusoidal" && current_amplitude_convention == "plateau" {
        return Err(
            "current_amplitude_convention='plateau' requires excitation_mode='ideal_six_step_120'"
                .to_string(),
        );
    }
    let resolved_phase_current_peak_a = match current_amplitude_convention.as_str() {
        "peak" | "plateau" => resolved_current_amplitude_a,
        "rms" => resolved_current_amplitude_a * 2.0_f64.sqrt(),
        other => {
            return Err(format!(
                "unsupported solve_params.current_amplitude_convention '{other}'; expected 'peak', 'rms', or 'plateau'"
            ))
        }
    };
    let current_amplitude_rule = if current_amplitude_convention == "plateau" {
        if requested_current_amplitude_a.is_some() {
            "current_amplitude_A is the conducting-phase plateau current for ideal 120-degree six-step excitation"
                .to_string()
        } else {
            "current_amplitude_A missing; defaulting to 50 A conducting-phase plateau current for ideal 120-degree six-step excitation"
                .to_string()
        }
    } else {
        match (
            requested_current_amplitude_a,
            sp.and_then(|params| params.current_amplitude_convention.as_deref()),
            current_amplitude_convention.as_str(),
        ) {
        (Some(_), Some(_), "peak") => {
            "current_amplitude_A is interpreted as peak phase current and used directly"
                .to_string()
        }
        (Some(_), Some(_), "rms") => {
            "current_amplitude_A is interpreted as RMS phase current and converted to peak with sqrt(2) before waveform synthesis"
                .to_string()
        }
        (Some(_), None, _) => {
            "current_amplitude_A provided without current_amplitude_convention; defaulting to peak phase current for backward compatibility"
                .to_string()
        }
        (None, Some(_), "peak") => {
            "current_amplitude_A missing; defaulting to 50 A peak phase current".to_string()
        }
        (None, Some(_), "rms") => {
            "current_amplitude_A missing; defaulting to 50 A RMS phase current and converting to peak with sqrt(2)"
                .to_string()
        }
        (None, None, _) => {
            "current_amplitude_A missing; defaulting to 50 A peak phase current for backward compatibility"
                .to_string()
        }
        _ => unreachable!(),
        }
    };

    let requested_angle = sp.and_then(|s| s.current_angle_deg);
    let resolved_angle = requested_angle.unwrap_or(0.0);

    let (current_angle_reference, resolution_rule, sweep_current_rule) = if excitation_mode
        == "ideal_six_step_120"
    {
        (
                "six-step sectors use public clockwise-positive rotor electrical angle plus commutation_advance_deg; current_angle_deg is ignored"
                    .to_string(),
                "ideal six-step excitation resolves the exact two-on/one-off phase-current triple from rotor position"
                    .to_string(),
                "for rotor sweeps, each sample resolves the lower-inclusive 60-degree commutation sector from rotor electrical angle plus advance"
                    .to_string(),
            )
    } else {
        let resolution_rule = match requested_angle {
            Some(_) => {
                "explicit current_angle_deg from solve_params; gamma is measured from the q-axis"
                    .to_string()
            }
            None => {
                "current_angle_deg missing; defaulting to gamma=0 degrees from q-axis".to_string()
            }
        };
        (
                "gamma from q-axis; positive gamma is flux-weakening advance; theta_e = pp*mech - 90 + gamma"
                    .to_string(),
                resolution_rule,
                "for rotor sweeps, source current angle is theta_e = pp*mech - 90 + gamma"
                    .to_string(),
            )
    };

    Ok(OperatingPointSummary {
        requested_current_amplitude_a,
        resolved_current_amplitude_a,
        current_amplitude_convention,
        resolved_phase_current_peak_a,
        current_amplitude_rule,
        requested_current_angle_deg: requested_angle,
        resolved_current_angle_deg: resolved_angle,
        current_angle_reference,
        resolution_rule,
        sweep_current_rule,
        excitation_mode: (excitation_mode == "ideal_six_step_120")
            .then(|| excitation_mode.to_string()),
        commutation_advance_deg: (excitation_mode == "ideal_six_step_120")
            .then(|| sp.map(SolveParams::commutation_advance_deg).unwrap_or(0.0)),
        phase_connection: (excitation_mode == "ideal_six_step_120")
            .then(|| phase_connection.to_string()),
        excitation_convention_version: (excitation_mode == "ideal_six_step_120")
            .then(|| "openem.bldc_six_step/v1".to_string()),
        resolved_conducting_phase_plateau_a: (excitation_mode == "ideal_six_step_120")
            .then_some(resolved_current_amplitude_a),
    })
}

/// Returns true if the config has opted into the per-step remesh rotation
/// model. Default / missing / any unknown label → `false` (legacy
/// fixed-mesh behaviour, byte-identical to pre-remesh implementation).
fn uses_remesh_per_step(config: &MotorConfig) -> bool {
    config
        .solve_params
        .as_ref()
        .map(|sp| sp.rotor_rotation_model_label())
        .unwrap_or("fixed_mesh")
        == "remesh_per_step"
}

fn cogging_rotation_policy_override() -> Option<bool> {
    let policy = std::env::var("MAGNETO2D_COGGING_ROTATION_POLICY").ok()?;
    match policy.trim().to_ascii_lowercase().as_str() {
        "" | "auto" | "default" | "product" => None,
        "fixed" | "fixed_mesh" | "force_fixed" | "force_fixed_mesh" => Some(false),
        "remesh" | "remesh_per_step" | "force_remesh" | "force_remesh_per_step" => Some(true),
        _ => None,
    }
}

/// Product cogging policy for SPM benchmarks.
///
/// Remeshing the zero-current cogging sweep fixes the 50 mm small-motor
/// k_phys gap, but the same all-remesh policy over-predicts the 100 mm
/// 8p/12s fixture. Keep the loaded-sweep opt-in authoritative, and otherwise
/// only promote the small-motor class where the benchmark showed a win.
fn uses_cogging_remesh_per_step(config: &MotorConfig) -> bool {
    if let Some(force_remesh) = cogging_rotation_policy_override() {
        return force_remesh;
    }
    uses_remesh_per_step(config) || config.stator.od_mm <= 75.0
}

fn applied_current_angle_deg(rotor_electrical_angle_deg: f64, gamma_deg: f64) -> f64 {
    // Positive gamma ADDS to the source
    // angle so that positive gamma is flux-weakening advance, mirroring
    // backend.geometry_drawer.current_angle_elec_deg_for_rotor_elec exactly.
    // The earlier convention of subtracting gamma retarded the phasor and
    // mirrored the advance axis on both lanes.
    rotor_electrical_angle_deg - 90.0 + gamma_deg
}

fn rotor_electrical_angle_deg(rotor_angle_rad: f64, pole_pairs: usize) -> f64 {
    rotor_angle_rad.to_degrees() * pole_pairs as f64
}

fn synced_current_angle_deg(rotor_angle_rad: f64, pole_pairs: usize, advance_deg: f64) -> f64 {
    applied_current_angle_deg(
        rotor_electrical_angle_deg(rotor_angle_rad, pole_pairs),
        advance_deg,
    )
}

// ── Sextant sweep symmetry (MAGNETO2D_SWEEP_SEXTANT=1) ──────────────────────
//
// For a balanced 3-phase machine with identical poles, advancing one sixth of
// an electrical cycle maps the machine state onto itself up to a phase
// relabel with sign flip: with the sin convention i_a = I·sin(γ),
// i_b = I·sin(γ−120°), i_c = I·sin(γ−240°) (sources.rs), the +60° map is
// (a, b, c) → (−b, −c, −a). Torque and all scalar energies are invariant;
// the three phase flux linkages permute by the same map. A full-cycle sweep
// can therefore solve only [0°, 60°) electrical and reconstruct the rest —
// exact in the continuum, mesh-discretization-accurate on a fixed mesh
// (the unstructured mesh is not 60°-congruent with itself, so reconstructed
// samples differ from directly solved ones by mesh noise; validate parity
// before relying on it, which is why the mode is opt-in).

fn gcd_u32(mut a: u32, mut b: u32) -> u32 {
    while b != 0 {
        let r = a % b;
        a = b;
        b = r;
    }
    a
}

/// A symmetrical 3-phase winding exists iff slots/(3·gcd(slots, pole_pairs))
/// is an integer. This is the precondition for the 60°-electrical waveform
/// symmetry the sextant sweep relies on (e.g. true for 12s8p, false for the
/// 4-slot lesson motor).
fn balanced_three_phase_winding(slot_count: u32, pole_count: u32) -> bool {
    let pole_pairs = (pole_count / 2).max(1);
    if slot_count == 0 || slot_count % 3 != 0 {
        return false;
    }
    (slot_count / gcd_u32(slot_count, pole_pairs)) % 3 == 0
}

/// Apply the +60°-electrical phase map `sextant` times to an (a, b, c)
/// triple: one step maps (a, b, c) → (−b, −c, −a); three steps give the
/// half-wave −(a, b, c); six steps are the identity.
fn sextant_phase_map(mut triple: [f64; 3], sextant: usize) -> [f64; 3] {
    for _ in 0..(sextant % 6) {
        triple = [-triple[1], -triple[2], -triple[0]];
    }
    triple
}

fn sweep_sextant_requested() -> bool {
    env_flag_enabled("MAGNETO2D_SWEEP_SEXTANT", false)
}

fn rotated_rotor_regions(
    mesh: &crate::mesh::TriMesh,
    centroids: &[[f64; 2]],
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Result<Vec<Region>, String> {
    MachineModel::from_config(config)
        .rotated_rotor_regions(mesh, centroids, rotor_angle_rad)
        .map_err(|err| err.to_string())
}

impl SolveMatrixPattern {
    fn new(problem: &MagnetostaticProblem) -> Result<Self, String> {
        Ok(Self {
            prepared: PreparedFieldSystem::new(&problem.mesh, &problem.boundaries)?,
        })
    }

    fn assemble_stiffness(
        &self,
        mesh: &crate::mesh::TriMesh,
        materials: &[MaterialProps],
    ) -> crate::sparse::CsrMatrix {
        self.prepared
            .assemble_reluctivity_from(&mesh.nodes, &mesh.triangles, |element_index| {
                materials[element_index].nu
            })
    }

    fn add_constraint_terms(&self, matrix: &mut crate::sparse::CsrMatrix) {
        self.prepared.add_boundary_terms(matrix);
    }

    fn apply_dirichlet(&self, matrix: &mut crate::sparse::CsrMatrix, rhs: &mut [f64]) {
        self.prepared.apply_dirichlet(matrix, rhs);
    }

    pub(super) fn csr_pattern(&self) -> &ElementCsrAssemblyPattern {
        self.prepared.csr_pattern()
    }

    fn direct_solve(
        &self,
        matrix: &crate::sparse::CsrMatrix,
        rhs: &[f64],
    ) -> Result<Option<Vec<f64>>, crate::sparse::DirectCholeskyError> {
        self.prepared
            .assert_pattern_identity(matrix)
            .map_err(|_| crate::sparse::DirectCholeskyError::PatternMismatch)?;
        self.prepared.direct_solve(matrix, rhs)
    }

    fn direct_stats(&self) -> crate::sparse::DirectCholeskyStats {
        self.prepared.direct_stats()
    }
}

fn motor_boundary_set(mesh: &crate::mesh::TriMesh, n_pole_pitches: u32) -> BoundarySet {
    let mut dirichlet_az_zero_nodes = outer_dirichlet_boundary_nodes(mesh);
    let mut seen_dirichlet = std::collections::HashSet::new();
    dirichlet_az_zero_nodes.retain(|node| seen_dirichlet.insert(*node));
    let paired_nodes = if n_pole_pitches > 1 {
        let dirichlet: std::collections::HashSet<usize> =
            dirichlet_az_zero_nodes.iter().copied().collect();
        let kind = if n_pole_pitches % 2 == 1 {
            PairedBoundaryKind::AntiPeriodic
        } else {
            PairedBoundaryKind::Periodic
        };
        mesh.sector_edge_pairs
            .iter()
            .copied()
            .filter(|(left, right)| !dirichlet.contains(left) && !dirichlet.contains(right))
            .map(|nodes| PairedBoundary {
                nodes: [nodes.0, nodes.1],
                kind,
            })
            .collect()
    } else {
        for &(left, right) in &mesh.sector_edge_pairs {
            dirichlet_az_zero_nodes.push(left);
            dirichlet_az_zero_nodes.push(right);
        }
        dirichlet_az_zero_nodes.sort_unstable();
        dirichlet_az_zero_nodes.dedup();
        Vec::new()
    };
    BoundarySet {
        dirichlet_az_zero_nodes,
        paired_nodes,
        periodic_penalty: 1.0e10,
    }
}

/// Relative residual the final (and any standalone) linear solve uses.
pub(super) const LINEAR_SOLVE_TIGHT_TOL: f64 = 1e-8;

/// Linear solver selection. Default is the faer sparse direct Cholesky
/// ("direct"): the symbolic factorization is cached per mesh pattern in
/// SolveMatrixPattern, so each Picard/Newton iteration costs one numeric
/// refactor + two triangular solves, with PCG as the transparent fallback if
/// a factorization is unavailable. Benchmarked on the 8p12s fine-density
/// 48-position Gmsh sweep at 8.3x over Jacobi PCG and 5.0x over IC(0) PCG
/// with torque-waveform parity 7.1e-8 relative (exact-solver class).
/// Set MAGNETO2D_LINEAR_SOLVER=pcg to restore the iterative path.
#[derive(Debug, Clone, Copy)]
pub(super) struct MotorLinearSolvePolicy {
    direct: bool,
    pcg: PcgOptions,
    adaptive_inner_tolerance: bool,
    loose_tolerance: f64,
}

fn resolve_motor_linear_solve_policy() -> MotorLinearSolvePolicy {
    let direct = std::env::var("MAGNETO2D_LINEAR_SOLVER")
        .map(|value| !value.trim().eq_ignore_ascii_case("pcg"))
        .unwrap_or(true);
    let preconditioner = std::env::var("MAGNETO2D_PCG_PRECONDITIONER")
        .map(|value| {
            if value.trim().eq_ignore_ascii_case("jacobi") {
                PcgPreconditionerKind::Jacobi
            } else {
                PcgPreconditionerKind::IncompleteCholesky
            }
        })
        .unwrap_or(PcgPreconditionerKind::IncompleteCholesky);
    let execution = if env_flag_enabled("MAGNETO2D_PCG_PARALLEL", false)
        || env_flag_enabled("COILEM_MAGNETO2D_PCG_PARALLEL", false)
    {
        PcgExecution::Parallel
    } else {
        PcgExecution::Serial
    };
    let residual_check_interval = std::env::var("MAGNETO2D_PCG_RESIDUAL_CHECK_INTERVAL")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(8);
    let adaptive_inner_tolerance = env_flag_enabled("MAGNETO2D_PCG_ADAPTIVE_TOL", false);
    let loose_tolerance = std::env::var("MAGNETO2D_PCG_LOOSE_TOL")
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .filter(|tol| tol.is_finite() && *tol > 0.0 && *tol < 1.0)
        .unwrap_or(1.0e-5);
    MotorLinearSolvePolicy {
        direct,
        pcg: PcgOptions {
            execution,
            preconditioner,
            residual_check_interval,
        },
        adaptive_inner_tolerance,
        loose_tolerance,
    }
}

#[allow(clippy::too_many_arguments)]
fn solve_linear_system(
    mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
    materials: &[MaterialProps],
    current_densities: &[f64],
    initial_az_guess: Option<&[f64]>,
    magnet_fractions: Option<&[f64]>,
    matrix_pattern: Option<&SolveMatrixPattern>,
    linear_tol: f64,
    linear_policy: MotorLinearSolvePolicy,
    mut profile: Option<&mut SolveProfile>,
) -> Result<(Vec<f64>, u64, u64), String> {
    let asm_start = Instant::now();

    if let Some(profile) = profile.as_deref_mut() {
        profile.linear_solve_calls += 1;
    }

    let source_start = Instant::now();
    let mut f = assemble_source(mesh, materials, current_densities, magnet_fractions);
    if let Some(profile) = profile.as_deref_mut() {
        profile.linear_source_assembly_ms += elapsed_ms(source_start);
    }

    let mut k_csr = if let Some(matrix_pattern) = matrix_pattern {
        let stiffness_start = Instant::now();
        let k_csr = matrix_pattern.assemble_stiffness(mesh, materials);
        let stiffness_ms = elapsed_ms(stiffness_start);
        if let Some(profile) = profile.as_deref_mut() {
            profile.linear_stiffness_assembly_ms += stiffness_ms;
            profile.direct_csr_refill_ms += stiffness_ms;
        }
        k_csr
    } else {
        let stiffness_start = Instant::now();
        let mut k_coo = assemble_stiffness(mesh, materials);
        if let Some(profile) = profile.as_deref_mut() {
            profile.linear_stiffness_assembly_ms += elapsed_ms(stiffness_start);
        }

        let constraint_start = Instant::now();
        let bc_nodes = apply_model_constraints(&mut k_coo, &mut f, mesh, n_pole_pitches);
        if let Some(profile) = profile.as_deref_mut() {
            profile.constraint_apply_ms += elapsed_ms(constraint_start);
        }

        let csr_start = Instant::now();
        let mut k_csr = k_coo.to_csr();
        if let Some(profile) = profile.as_deref_mut() {
            profile.csr_conversion_ms += elapsed_ms(csr_start);
        }

        let dirichlet_start = Instant::now();
        k_csr.apply_dirichlet(&mut f, &bc_nodes);
        if let Some(profile) = profile.as_deref_mut() {
            profile.dirichlet_apply_ms += elapsed_ms(dirichlet_start);
        }
        k_csr
    };

    if let Some(matrix_pattern) = matrix_pattern {
        let constraint_start = Instant::now();
        matrix_pattern.add_constraint_terms(&mut k_csr);
        if let Some(profile) = profile.as_deref_mut() {
            profile.constraint_apply_ms += elapsed_ms(constraint_start);
        }

        let dirichlet_start = Instant::now();
        matrix_pattern.apply_dirichlet(&mut k_csr, &mut f);
        if let Some(profile) = profile.as_deref_mut() {
            profile.dirichlet_apply_ms += elapsed_ms(dirichlet_start);
        }
    }

    let asm_ms = asm_start.elapsed().as_millis() as u64;
    let solve_start = Instant::now();

    // Direct path: faer sparse Cholesky with the symbolic factorization
    // cached on the matrix pattern. Only available when the pattern object
    // exists (direct-CSR assembly, the default); falls back to PCG when the
    // factorization is unavailable or the env flag is off.
    if linear_policy.direct {
        if let Some(matrix_pattern) = matrix_pattern {
            match matrix_pattern.direct_solve(&k_csr, &f) {
                Ok(Some(az)) => {
                    let solve_ms = solve_start.elapsed().as_millis() as u64;
                    if let Some(profile) = profile.as_deref_mut() {
                        profile.direct_cholesky_solves += 1;
                        profile.direct_cholesky_solve_ms += solve_ms;
                    }
                    return Ok((az, asm_ms, solve_ms));
                }
                Ok(None) => {}
                Err(crate::sparse::DirectCholeskyError::PatternMismatch) => {
                    return Err(
                        "prepared motor field system CSR pattern changed during refill".to_string(),
                    );
                }
            }
        }
    }

    let max_linear_iterations = if n_pole_pitches > 1 { 5000 } else { 2000 };
    let az = if let Some(profile) = profile.as_deref_mut() {
        let (az, pcg_profile) = pcg_solve_with_guess_options_profiled(
            &k_csr,
            &f,
            max_linear_iterations,
            linear_tol,
            initial_az_guess,
            linear_policy.pcg,
        )?;
        profile.pcg.add_assign(&pcg_profile);
        az
    } else {
        pcg_solve_with_guess_options(
            &k_csr,
            &f,
            max_linear_iterations,
            linear_tol,
            initial_az_guess,
            linear_policy.pcg,
        )?
    };
    let solve_ms = solve_start.elapsed().as_millis() as u64;
    Ok((az, asm_ms, solve_ms))
}

fn apply_model_constraints(
    k_coo: &mut CooMatrix,
    f: &mut [f64],
    mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
) -> Vec<usize> {
    let (bc_nodes, terms) = model_constraint_terms(mesh, n_pole_pitches);
    for (row, col, value) in terms {
        k_coo.add(row, col, value);
    }
    // Constraint targets are zero, so the RHS is unchanged.
    let _ = f;
    bc_nodes
}

fn model_constraint_terms(
    mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
) -> (Vec<usize>, Vec<(usize, usize, f64)>) {
    let dirichlet_nodes = outer_dirichlet_boundary_nodes(mesh);
    if n_pole_pitches > 1 {
        let mut terms = Vec::new();
        let penalty = 1e10;
        let mut is_boundary = vec![false; mesh.nodes.len()];
        for &node in &dirichlet_nodes {
            if node < is_boundary.len() {
                is_boundary[node] = true;
            }
        }
        if n_pole_pitches % 2 == 1 {
            for &(left, right) in &mesh.sector_edge_pairs {
                if is_boundary.get(left).copied().unwrap_or(false)
                    || is_boundary.get(right).copied().unwrap_or(false)
                {
                    continue;
                }
                terms.push((left, left, penalty));
                terms.push((left, right, penalty));
                terms.push((right, left, penalty));
                terms.push((right, right, penalty));
            }
        } else {
            for &(left, right) in &mesh.sector_edge_pairs {
                if is_boundary.get(left).copied().unwrap_or(false)
                    || is_boundary.get(right).copied().unwrap_or(false)
                {
                    continue;
                }
                terms.push((left, left, penalty));
                terms.push((left, right, -penalty));
                terms.push((right, left, -penalty));
                terms.push((right, right, penalty));
            }
        }
        (dirichlet_nodes, terms)
    } else {
        let mut all_bc_nodes: Vec<usize> = dirichlet_nodes;
        for &(left, right) in &mesh.sector_edge_pairs {
            all_bc_nodes.push(left);
            all_bc_nodes.push(right);
        }
        all_bc_nodes.sort_unstable();
        all_bc_nodes.dedup();
        (all_bc_nodes, Vec::new())
    }
}

fn outer_dirichlet_boundary_nodes(mesh: &crate::mesh::TriMesh) -> Vec<usize> {
    let outer_radius_m = mesh.info.stator_outer_radius_mm * 1e-3;
    let tolerance_m = (outer_radius_m.abs() * 1e-8).max(2.0e-9);
    let outer_nodes: Vec<usize> = mesh
        .boundary_nodes
        .iter()
        .copied()
        .filter(|&node_index| {
            mesh.nodes
                .get(node_index)
                .map(|node| {
                    let radius_m = (node[0] * node[0] + node[1] * node[1]).sqrt();
                    (radius_m - outer_radius_m).abs() <= tolerance_m
                })
                .unwrap_or(false)
        })
        .collect();

    if outer_nodes.is_empty() {
        mesh.boundary_nodes.clone()
    } else {
        outer_nodes
    }
}

fn summarize_angle_solution(
    mesh: &crate::mesh::TriMesh,
    solution: &FieldSolution,
    centroids: &[[f64; 2]],
    config: &MotorConfig,
) -> FieldSummary {
    let machine = MachineModel::from_config(config);
    summarize_fields(
        mesh,
        &solution.element_fields,
        &solution.az_nodal,
        centroids,
        machine.stack_length_mm(),
        machine.pole_count(),
        machine.slot_count(),
        machine.winding_turns_per_coil(),
        machine.winding_type(),
        machine.winding_layers(),
        machine.winding_parallel_paths(),
        config.winding.coil_span,
    )
}

fn field_energy_per_unit_depth(
    mesh: &crate::mesh::TriMesh,
    materials: &[MaterialProps],
    fields: &[ElementField],
) -> f64 {
    mesh.triangles
        .iter()
        .enumerate()
        .map(|(index, triangle)| {
            let [i, j, k] = *triangle;
            let (area, _) = triangle_gradients(&mesh.nodes, i, j, k);
            0.5 * materials[index].nu * fields[index].b_mag.powi(2) * area
        })
        .sum()
}

fn compute_energy_functional_summary(
    mesh: &crate::mesh::TriMesh,
    materials: &[MaterialProps],
    current_densities: &[f64],
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
) -> EnergyFunctionalSummary {
    let l_stack = stack_length_mm * 1e-3;
    let n_pole_pitches = mesh.info.n_pole_pitches.max(1);
    let scale_factor = pole_count as f64 / n_pole_pitches as f64;
    let scale = l_stack * scale_factor;
    let pm_source_work_scale = pm_source_work_scale();
    let magnet_extents = magnet_energy_extents(mesh, materials, pole_count);
    let pm_sidewall_quadrature = pm_sidewall_quadrature_diagnostic_config();
    let mut pm_sidewall_quadrature_diagnostic =
        pm_sidewall_quadrature
            .enabled
            .then(|| PmSidewallQuadratureDiagnosticSummary {
                enabled: true,
                pm_source_scale: pm_sidewall_quadrature.pm_source_scale,
                field_scale: pm_sidewall_quadrature.field_scale,
                coenergy_scale: pm_sidewall_quadrature.coenergy_scale,
                side_window_mm: pm_sidewall_quadrature.side_window_m * 1.0e3,
                radial_depth_mm: pm_sidewall_quadrature.radial_depth_m * 1.0e3,
                ..Default::default()
            });

    let mut field_energy_per_m = 0.0_f64;
    let mut field_energy_by_region_per_m = EnergyByRegionSummary::default();
    let mut field_energy_magnet_detail_per_m = MagnetFieldEnergyDetailSummary::default();
    let mut current_source_work_per_m = 0.0_f64;
    let mut pm_source_work_per_m = 0.0_f64;
    let mut pm_source_work_magnet_detail_per_m = MagnetFieldEnergyDetailSummary::default();
    let mut pm_self_energy_per_m = 0.0_f64;
    let mut coenergy_by_region_per_m = EnergyByRegionSummary::default();
    let mut coenergy_magnet_detail_per_m = MagnetFieldEnergyDetailSummary::default();

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let [i, j, m] = *tri;
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }

        let da_dx = az[i] * grad[0][0] + az[j] * grad[1][0] + az[m] * grad[2][0];
        let da_dy = az[i] * grad[0][1] + az[j] * grad[1][1] + az[m] * grad[2][1];
        let bx = da_dy;
        let by = -da_dx;
        let b2 = bx * bx + by * by;

        let material = materials[tri_idx];
        let base_field_energy_element_per_m = 0.5 * material.nu * b2 * area;
        let mut field_energy_element_per_m = base_field_energy_element_per_m;
        let mut pm_source_work_element_per_m = 0.0_f64;
        let mut base_pm_source_work_element_per_m = 0.0_f64;
        let mut current_source_work_element_per_m = 0.0_f64;
        let mut magnet_centroid: Option<[f64; 2]> = None;
        let mut pm_sidewall_metrics: Option<PmSidewallQuadratureSelectionMetrics> = None;
        let mut apply_pm_sidewall_quadrature = false;

        if material.br.abs() > 0.0 {
            let centroid = triangle_centroid(&mesh.nodes, i, j, m);
            pm_sidewall_metrics = magnet_extents.as_ref().and_then(|extents| {
                pm_sidewall_quadrature.selection_metrics(
                    extents,
                    pole_count,
                    material.mag_angle_rad,
                    centroid,
                )
            });
            apply_pm_sidewall_quadrature = pm_sidewall_metrics
                .as_ref()
                .map(|metrics| metrics.selected)
                .unwrap_or(false);
            if apply_pm_sidewall_quadrature {
                field_energy_element_per_m *= pm_sidewall_quadrature.field_scale;
            }
            magnet_centroid = Some(centroid);
        }

        field_energy_per_m += field_energy_element_per_m;
        if let Some(region) = mesh.regions.get(tri_idx).copied() {
            add_energy_by_region(
                &mut field_energy_by_region_per_m,
                region,
                field_energy_element_per_m,
            );
        }

        if material.br.abs() > 0.0 {
            let centroid =
                magnet_centroid.unwrap_or_else(|| triangle_centroid(&mesh.nodes, i, j, m));
            if let Some(extents) = magnet_extents {
                add_magnet_field_energy_detail(
                    &mut field_energy_magnet_detail_per_m,
                    &extents,
                    pole_count,
                    material.mag_angle_rad,
                    centroid,
                    field_energy_element_per_m,
                );
            }
            let br_x = material.br * material.mag_angle_rad.cos();
            let br_y = material.br * material.mag_angle_rad.sin();
            base_pm_source_work_element_per_m =
                pm_source_work_scale * material.nu * (br_x * bx + br_y * by) * area;
            pm_source_work_element_per_m = base_pm_source_work_element_per_m;
            if apply_pm_sidewall_quadrature {
                pm_source_work_element_per_m *= pm_sidewall_quadrature.pm_source_scale;
            }
            pm_self_energy_per_m += 0.5 * material.nu * material.br * material.br * area;
        }

        let jz = current_densities.get(tri_idx).copied().unwrap_or(0.0);
        if jz.abs() > 0.0 {
            let az_avg = (az[i] + az[j] + az[m]) / 3.0;
            current_source_work_element_per_m = jz * az_avg * area;
            current_source_work_per_m += current_source_work_element_per_m;
        }

        if material.br.abs() > 0.0 {
            let centroid =
                magnet_centroid.unwrap_or_else(|| triangle_centroid(&mesh.nodes, i, j, m));
            if apply_pm_sidewall_quadrature
                && (pm_sidewall_quadrature.coenergy_scale - 1.0).abs() > 1.0e-12
            {
                let base_coenergy_element_per_m = pm_source_work_element_per_m
                    + current_source_work_element_per_m
                    - field_energy_element_per_m;
                let scaled_coenergy_element_per_m =
                    pm_sidewall_quadrature.coenergy_scale * base_coenergy_element_per_m;
                pm_source_work_element_per_m = scaled_coenergy_element_per_m
                    - current_source_work_element_per_m
                    + field_energy_element_per_m;
            }
            pm_source_work_per_m += pm_source_work_element_per_m;
            if let Some(extents) = magnet_extents {
                add_magnet_field_energy_detail(
                    &mut pm_source_work_magnet_detail_per_m,
                    &extents,
                    pole_count,
                    material.mag_angle_rad,
                    centroid,
                    pm_source_work_element_per_m,
                );
            }
        }

        let base_coenergy_element_per_m = base_pm_source_work_element_per_m
            + current_source_work_element_per_m
            - base_field_energy_element_per_m;
        let coenergy_element_per_m = pm_source_work_element_per_m
            + current_source_work_element_per_m
            - field_energy_element_per_m;
        if apply_pm_sidewall_quadrature {
            if let (Some(metrics), Some(diagnostic)) = (
                pm_sidewall_metrics,
                pm_sidewall_quadrature_diagnostic.as_mut(),
            ) {
                let selected_area_mm2 = area * 1.0e6;
                let base_field_energy_j = base_field_energy_element_per_m * scale;
                let scaled_field_energy_j = field_energy_element_per_m * scale;
                let base_pm_source_work_j = base_pm_source_work_element_per_m * scale;
                let scaled_pm_source_work_j = pm_source_work_element_per_m * scale;
                let base_coenergy_j = base_coenergy_element_per_m * scale;
                let scaled_coenergy_j = coenergy_element_per_m * scale;

                diagnostic.selected_count += 1;
                diagnostic.selected_area_mm2 += selected_area_mm2;
                diagnostic.base_field_energy_j += base_field_energy_j;
                diagnostic.scaled_field_energy_j += scaled_field_energy_j;
                diagnostic.field_energy_delta_j += scaled_field_energy_j - base_field_energy_j;
                diagnostic.base_pm_source_work_j += base_pm_source_work_j;
                diagnostic.scaled_pm_source_work_j += scaled_pm_source_work_j;
                diagnostic.pm_source_work_delta_j +=
                    scaled_pm_source_work_j - base_pm_source_work_j;
                diagnostic.base_coenergy_j += base_coenergy_j;
                diagnostic.scaled_coenergy_j += scaled_coenergy_j;
                diagnostic.coenergy_delta_j += scaled_coenergy_j - base_coenergy_j;

                if let Some(centroid) = magnet_centroid {
                    diagnostic
                        .selected_elements
                        .push(PmSidewallQuadratureSelectedElement {
                            tri_idx,
                            region: region_string(mesh.regions.get(tri_idx).copied()),
                            centroid_x_mm: centroid[0] * 1.0e3,
                            centroid_y_mm: centroid[1] * 1.0e3,
                            centroid_r_mm: metrics.radius_m * 1.0e3,
                            centroid_theta_deg: centroid[1].atan2(centroid[0]).to_degrees(),
                            area_mm2: selected_area_mm2,
                            radial_delta_mm: metrics.radial_delta_m * 1.0e3,
                            side_distance_mm: metrics.side_distance_m * 1.0e3,
                            pole_offset_deg: metrics.pole_offset_rad.to_degrees(),
                            nominal_side_pole_offset_deg: metrics
                                .nominal_side_pole_offset_rad
                                .to_degrees(),
                            base_field_energy_j,
                            scaled_field_energy_j,
                            base_pm_source_work_j,
                            scaled_pm_source_work_j,
                            base_coenergy_j,
                            scaled_coenergy_j,
                            coenergy_delta_j: scaled_coenergy_j - base_coenergy_j,
                        });
                }
            }
        }
        if let Some(region) = mesh.regions.get(tri_idx).copied() {
            add_energy_by_region(
                &mut coenergy_by_region_per_m,
                region,
                coenergy_element_per_m,
            );
        }
        if material.br.abs() > 0.0 {
            if let Some(extents) = magnet_extents {
                let centroid = triangle_centroid(&mesh.nodes, i, j, m);
                add_magnet_field_energy_detail(
                    &mut coenergy_magnet_detail_per_m,
                    &extents,
                    pole_count,
                    material.mag_angle_rad,
                    centroid,
                    coenergy_element_per_m,
                );
            }
        }
    }

    let potential_per_m = field_energy_per_m - pm_source_work_per_m - current_source_work_per_m;
    let potential_with_pm_self_per_m = potential_per_m + pm_self_energy_per_m;

    EnergyFunctionalSummary {
        field_energy_j: field_energy_per_m * scale,
        field_energy_by_region_j: scale_energy_by_region(field_energy_by_region_per_m, scale),
        field_energy_magnet_detail_j: scale_magnet_field_energy_detail(
            field_energy_magnet_detail_per_m,
            scale,
        ),
        current_source_work_j: current_source_work_per_m * scale,
        pm_source_work_j: pm_source_work_per_m * scale,
        pm_source_work_magnet_detail_j: scale_magnet_field_energy_detail(
            pm_source_work_magnet_detail_per_m,
            scale,
        ),
        pm_self_energy_j: pm_self_energy_per_m * scale,
        potential_energy_j: potential_per_m * scale,
        potential_energy_with_pm_self_j: potential_with_pm_self_per_m * scale,
        coenergy_j: -potential_per_m * scale,
        coenergy_by_region_j: scale_energy_by_region(coenergy_by_region_per_m, scale),
        coenergy_magnet_detail_j: scale_magnet_field_energy_detail(
            coenergy_magnet_detail_per_m,
            scale,
        ),
        scale_factor,
        pm_sidewall_quadrature_diagnostic,
    }
}

#[derive(Debug, Clone, Copy)]
struct MagnetEnergyExtents {
    min_radius_m: f64,
    max_radius_m: f64,
    max_pole_offset_rad: f64,
    nominal_outer_radius_m: f64,
    nominal_side_pole_offset_rad: f64,
}

#[derive(Debug, Clone, Copy)]
struct PmSidewallQuadratureDiagnosticConfig {
    enabled: bool,
    pm_source_scale: f64,
    field_scale: f64,
    coenergy_scale: f64,
    side_window_m: f64,
    radial_depth_m: f64,
}

#[derive(Debug, Clone, Copy)]
struct PmSidewallQuadratureSelectionMetrics {
    radius_m: f64,
    radial_delta_m: f64,
    pole_offset_rad: f64,
    nominal_side_pole_offset_rad: f64,
    side_distance_m: f64,
    selected: bool,
}

impl PmSidewallQuadratureDiagnosticConfig {
    fn disabled() -> Self {
        Self {
            enabled: false,
            pm_source_scale: 1.0,
            field_scale: 1.0,
            coenergy_scale: 1.0,
            side_window_m: 0.0,
            radial_depth_m: 0.0,
        }
    }

    fn selection_metrics(
        &self,
        extents: &MagnetEnergyExtents,
        pole_count: u32,
        pole_axis_rad: f64,
        centroid: [f64; 2],
    ) -> Option<PmSidewallQuadratureSelectionMetrics> {
        if !self.enabled {
            return None;
        }
        let radius_m = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
        if radius_m <= 1.0e-12 {
            return None;
        }
        let radial_delta_m = radius_m - extents.nominal_outer_radius_m;

        let theta = centroid[1].atan2(centroid[0]);
        let pole_offset = pole_axis_offset_rad(theta, pole_axis_rad, pole_count).abs();
        let distance_from_side_m = (extents.nominal_side_pole_offset_rad - pole_offset).abs()
            * extents.nominal_outer_radius_m;
        Some(PmSidewallQuadratureSelectionMetrics {
            radius_m,
            radial_delta_m,
            pole_offset_rad: pole_offset,
            nominal_side_pole_offset_rad: extents.nominal_side_pole_offset_rad,
            side_distance_m: distance_from_side_m,
            selected: radial_delta_m >= -self.radial_depth_m
                && radial_delta_m <= 1.0e-9
                && distance_from_side_m <= self.side_window_m,
        })
    }
}

fn triangle_centroid(nodes: &[[f64; 2]], i: usize, j: usize, m: usize) -> [f64; 2] {
    [
        (nodes[i][0] + nodes[j][0] + nodes[m][0]) / 3.0,
        (nodes[i][1] + nodes[j][1] + nodes[m][1]) / 3.0,
    ]
}

fn pole_axis_offset_rad(theta: f64, pole_axis_rad: f64, pole_count: u32) -> f64 {
    let pole_pitch = 2.0 * PI / pole_count.max(1) as f64;
    (theta - pole_axis_rad + 0.5 * pole_pitch).rem_euclid(pole_pitch) - 0.5 * pole_pitch
}

fn magnet_energy_extents(
    mesh: &crate::mesh::TriMesh,
    materials: &[MaterialProps],
    pole_count: u32,
) -> Option<MagnetEnergyExtents> {
    let mut min_radius_m = f64::INFINITY;
    let mut max_radius_m = 0.0_f64;
    let mut max_pole_offset_rad = 0.0_f64;
    let mut count = 0usize;

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let Some(material) = materials.get(tri_idx).copied() else {
            continue;
        };
        if material.br.abs() <= 0.0 {
            continue;
        }
        let [i, j, m] = *tri;
        let centroid = triangle_centroid(&mesh.nodes, i, j, m);
        let radius_m = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
        let theta = centroid[1].atan2(centroid[0]);
        let pole_offset = pole_axis_offset_rad(theta, material.mag_angle_rad, pole_count).abs();
        min_radius_m = min_radius_m.min(radius_m);
        max_radius_m = max_radius_m.max(radius_m);
        max_pole_offset_rad = max_pole_offset_rad.max(pole_offset);
        count += 1;
    }

    if count == 0 || !min_radius_m.is_finite() || max_radius_m <= 0.0 {
        return None;
    }

    let pole_pitch_rad = 2.0 * PI / pole_count.max(1) as f64;
    let nominal_outer_radius_m = mesh.info.magnet_outer_radius_mm * 1.0e-3;
    let nominal_side_pole_offset_rad =
        0.5 * mesh.info.magnet_embrace.clamp(0.0, 1.0) * pole_pitch_rad;

    Some(MagnetEnergyExtents {
        min_radius_m,
        max_radius_m,
        max_pole_offset_rad,
        nominal_outer_radius_m,
        nominal_side_pole_offset_rad,
    })
}

fn add_energy_by_region(summary: &mut EnergyByRegionSummary, region: Region, value_j: f64) {
    match region {
        Region::RotorCore => summary.rotor_core_j += value_j,
        Region::Magnet => summary.magnet_j += value_j,
        Region::Airgap | Region::FluxBarrier | Region::MagnetPocketAir => {
            summary.airgap_j += value_j
        }
        Region::StatorTooth => summary.stator_tooth_j += value_j,
        Region::StatorYoke => summary.stator_yoke_j += value_j,
        Region::SlotWinding => summary.slot_winding_j += value_j,
    }
}

fn add_magnet_field_energy_detail(
    summary: &mut MagnetFieldEnergyDetailSummary,
    extents: &MagnetEnergyExtents,
    pole_count: u32,
    pole_axis_rad: f64,
    centroid: [f64; 2],
    value_j: f64,
) {
    let radius_m = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
    let radius_span_m = extents.max_radius_m - extents.min_radius_m;
    let radial_t = if radius_span_m > 1.0e-12 {
        ((radius_m - extents.min_radius_m) / radius_span_m).clamp(0.0, 1.0)
    } else {
        0.5
    };
    if radial_t < 1.0 / 3.0 {
        summary.radial_inner_j += value_j;
    } else if radial_t < 2.0 / 3.0 {
        summary.radial_middle_j += value_j;
    } else {
        summary.radial_outer_j += value_j;
    }

    let theta = centroid[1].atan2(centroid[0]);
    let pole_offset = pole_axis_offset_rad(theta, pole_axis_rad, pole_count).abs();
    let edge_threshold = 0.75 * extents.max_pole_offset_rad;
    if extents.max_pole_offset_rad > 1.0e-12 && pole_offset >= edge_threshold {
        summary.angular_edge_j += value_j;
    } else {
        summary.angular_interior_j += value_j;
    }
}

fn scale_energy_by_region(summary: EnergyByRegionSummary, scale: f64) -> EnergyByRegionSummary {
    EnergyByRegionSummary {
        rotor_core_j: summary.rotor_core_j * scale,
        magnet_j: summary.magnet_j * scale,
        airgap_j: summary.airgap_j * scale,
        stator_tooth_j: summary.stator_tooth_j * scale,
        stator_yoke_j: summary.stator_yoke_j * scale,
        slot_winding_j: summary.slot_winding_j * scale,
    }
}

fn scale_magnet_field_energy_detail(
    summary: MagnetFieldEnergyDetailSummary,
    scale: f64,
) -> MagnetFieldEnergyDetailSummary {
    MagnetFieldEnergyDetailSummary {
        radial_inner_j: summary.radial_inner_j * scale,
        radial_middle_j: summary.radial_middle_j * scale,
        radial_outer_j: summary.radial_outer_j * scale,
        angular_edge_j: summary.angular_edge_j * scale,
        angular_interior_j: summary.angular_interior_j * scale,
    }
}

fn parse_pm_source_work_scale(raw: Option<&str>) -> f64 {
    raw.and_then(|value| value.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value >= 0.0)
        .unwrap_or(1.0)
}

fn pm_source_work_scale() -> f64 {
    parse_pm_source_work_scale(
        std::env::var("COILEM_MAGNETO2D_PM_SOURCE_WORK_SCALE")
            .ok()
            .as_deref(),
    )
}

fn env_flag_any_enabled(names: &[&str]) -> bool {
    names.iter().any(|name| env_flag_enabled(name, false))
}

fn parse_positive_env_or_default(names: &[&str], default: f64) -> f64 {
    parse_positive_env(names).unwrap_or(default)
}

fn parse_positive_env(names: &[&str]) -> Option<f64> {
    for name in names {
        let Some(value) = std::env::var(name)
            .ok()
            .and_then(|raw| raw.trim().parse::<f64>().ok())
            .filter(|value| value.is_finite() && *value > 0.0)
        else {
            continue;
        };
        return Some(value);
    }
    None
}

fn pm_sidewall_quadrature_diagnostic_config() -> PmSidewallQuadratureDiagnosticConfig {
    if !env_flag_any_enabled(&[
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC",
        "MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC",
    ]) {
        return PmSidewallQuadratureDiagnosticConfig::disabled();
    }

    let coenergy_scale = parse_positive_env(&[
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_COENERGY_SCALE",
        "MAGNETO2D_PM_SIDEWALL_QUADRATURE_COENERGY_SCALE",
    ])
    .unwrap_or(1.0);
    let default_term_scale = if (coenergy_scale - 1.0).abs() > 1.0e-12 {
        1.0
    } else {
        1.4667
    };
    let pm_source_scale = parse_positive_env_or_default(
        &[
            "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_PM_SOURCE_SCALE",
            "MAGNETO2D_PM_SIDEWALL_QUADRATURE_PM_SOURCE_SCALE",
        ],
        default_term_scale,
    );
    let field_scale = parse_positive_env_or_default(
        &[
            "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_FIELD_SCALE",
            "MAGNETO2D_PM_SIDEWALL_QUADRATURE_FIELD_SCALE",
        ],
        default_term_scale,
    );
    let side_window_m = parse_positive_env_or_default(
        &[
            "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_SIDE_WINDOW_MM",
            "MAGNETO2D_PM_SIDEWALL_QUADRATURE_SIDE_WINDOW_MM",
        ],
        0.6,
    ) * 1.0e-3;
    let corner_window_mm = parse_positive_env_or_default(
        &[
            "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_CORNER_WINDOW_MM",
            "MAGNETO2D_PM_SIDEWALL_QUADRATURE_CORNER_WINDOW_MM",
        ],
        0.45,
    );
    let radial_depth_m = parse_positive_env_or_default(
        &[
            "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_RADIAL_DEPTH_MM",
            "MAGNETO2D_PM_SIDEWALL_QUADRATURE_RADIAL_DEPTH_MM",
        ],
        corner_window_mm,
    ) * 1.0e-3;

    PmSidewallQuadratureDiagnosticConfig {
        enabled: true,
        pm_source_scale,
        field_scale,
        coenergy_scale,
        side_window_m,
        radial_depth_m,
    }
}

fn env_flag_enabled(name: &str, default: bool) -> bool {
    match std::env::var(name) {
        Ok(value) => {
            let normalized = value.trim().to_ascii_lowercase();
            !(normalized.is_empty()
                || normalized == "0"
                || normalized == "false"
                || normalized == "no"
                || normalized == "off")
        }
        Err(_) => default,
    }
}

fn solve_profile_enabled() -> bool {
    env_flag_enabled("MAGNETO2D_PROFILE", false)
        || env_flag_enabled("COILEM_MAGNETO2D_PROFILE", false)
}

fn direct_csr_enabled() -> bool {
    env_flag_enabled("MAGNETO2D_DIRECT_CSR", true)
        && env_flag_enabled("COILEM_MAGNETO2D_DIRECT_CSR", true)
}

fn elapsed_ms(started: Instant) -> u64 {
    started.elapsed().as_millis() as u64
}

fn emit_angle_iteration_progress(
    progress: Option<&AngleProgressContext<'_>>,
    iteration: usize,
    max_iterations: usize,
    assembly_ms: u64,
    linear_solve_ms: u64,
    residual: f64,
    convergence_threshold: f64,
    worst_element: Option<usize>,
) {
    let Some(progress) = progress else {
        return;
    };

    // Keep the stream informative without flooding SSE. Position-completion
    // ticks still carry the authoritative torque/back-EMF samples; these
    // iteration ticks only answer "what is the field solver doing right now?"
    let is_first = iteration == 1;
    let is_interval = iteration % 5 == 0;
    let is_converged = residual <= convergence_threshold;
    let is_last = iteration == max_iterations;
    if !(is_first || is_interval || is_converged || is_last) {
        return;
    }

    let payload = serde_json::json!({
        "parent_stage": progress.parent_stage,
        "solve_kind": progress.solve_kind,
        "position_index": progress.position_index,
        "total_positions": progress.total_positions,
        "completed_positions": progress.completed_positions.load(Ordering::Relaxed),
        "elec_deg": progress.elec_deg,
        "iteration": iteration,
        "max_iterations": max_iterations,
        "residual": residual,
        "tol": convergence_threshold,
        "assembly_ms": assembly_ms,
        "linear_solve_ms": linear_solve_ms,
        "worst_element": worst_element,
        "converged": is_converged,
    });
    eprintln!("COILEM_SOLVE_ITER {payload}");
}

fn emit_angle_solve_context(
    progress: Option<&AngleProgressContext<'_>>,
    iteration: usize,
    max_iterations: usize,
) {
    let Some(progress) = progress else {
        return;
    };

    let payload = serde_json::json!({
        "parent_stage": progress.parent_stage,
        "solve_kind": progress.solve_kind,
        "position_index": progress.position_index,
        "total_positions": progress.total_positions,
        "completed_positions": progress.completed_positions.load(Ordering::Relaxed),
        "elec_deg": progress.elec_deg,
        "iteration": iteration,
        "max_iterations": max_iterations,
    });
    eprintln!("COILEM_SOLVE_CONTEXT {payload}");
}

/// Solve at one rotor angle. Returns (FieldSummary, az_solution, diagnostics).
///
/// `current_angle_deg` is the fully resolved source-current electrical angle.
/// For synchronized operation in a sweep, pass
/// `applied_current_angle_deg(theta_elec, gamma)`.
fn solve_at_angle(
    ctx: &SolveContext,
    config: &MotorConfig,
    rotor_angle_rad: f64,
    current_angle_deg: f64,
    current_a: f64,
    rotor_baked_in_mesh: bool,
    material_warm_start: Option<&NonlinearWarmStart>,
    az_warm_start: Option<&[f64]>,
    progress: Option<&AngleProgressContext<'_>>,
) -> Result<
    (
        Vec<ElementField>,
        FieldSummary,
        Vec<f64>,
        AngleSolveDiagnostics,
        NonlinearWarmStart,
    ),
    String,
> {
    let mut solve_mesh = ctx.mesh.clone();
    // In `remesh_per_step` mode the mesh handed to us already has the rotor
    // physically rotated — pole / airgap / magnet regions are placed at the
    // rotated angles by the mesher. Re-tagging via rotated_rotor_regions
    // would be a no-op on a well-formed mesh and only risks round-off
    // artifacts near the embrace edges, so we skip it. The legacy fixed-
    // mesh path still retags per step (the mesh is shared across steps so
    // regions *must* be recomputed each call).
    if !rotor_baked_in_mesh {
        solve_mesh.regions =
            rotated_rotor_regions(&ctx.mesh, &ctx.centroids, config, rotor_angle_rad)?;
    }

    // Sub-element magnet integration. Opt-in via
    // COILEM_MAGNETO2D_MAGNET_SUBELEMENT=1. When enabled, compute a per-
    // triangle magnet area fraction once per rotor angle and pass it to
    // every Picard iteration so the PM source term blends smoothly with
    // rotor rotation. Default off → byte-identical behavior to prior runs.
    //
    // CRITICAL: this MUST run before assign_materials. For triangles
    // whose centroid is just outside the wedge but whose vertices straddle
    // the embrace edge, fraction > 0 but the centroid-based classifier
    // tagged them Airgap (Br = 0). We upgrade those to Magnet here so
    // assign_materials gives them the correct Br + mag_angle, and the
    // fraction multiplier in assemble_source then scales the contribution.
    //
    // Only meaningful for fixed_mesh rotation: when the mesh is rebuilt
    // per step (`rotor_baked_in_mesh`), embrace edges already land on real
    // mesh edges and no triangle straddles the boundary, so the fractions
    // would all be 0 or 1 anyway. We still compute and pass them so that
    // any floating-point noise at the boundary gets the same smoothing
    // treatment, which is harmless on already-clean meshes.
    let magnet_fractions: Option<Vec<f64>> = if env_flag_enabled(
        "COILEM_MAGNETO2D_MAGNET_SUBELEMENT",
        false,
    ) {
        if let Some(fractions) = crate::magnet_fraction::magnet_fill_fractions(
            &solve_mesh,
            &ctx.centroids,
            config,
            rotor_angle_rad,
        ) {
            // Upgrade Airgap → Magnet for any straddling triangle so material
            // assignment gives it Br > 0. Without this the fraction would be
            // multiplied by mat.br = 0 and contribute nothing — defeating the
            // whole point. We do not downgrade fraction==0 Magnet triangles:
            // their contribution is already 0 from the multiplier, and the
            // region tag is read by other code (postprocess, JSON) where we
            // want the centroid-based truth preserved.
            let mut upgraded = 0_usize;
            for (idx, fr) in fractions.iter().enumerate() {
                if *fr > 0.0 && solve_mesh.regions[idx] == Region::Airgap {
                    solve_mesh.regions[idx] = Region::Magnet;
                    upgraded += 1;
                }
            }
            // One-line per-angle diagnostic: total weighted magnet area (mm^2)
            // and how many border triangles got upgraded. Weighted area should
            // vary smoothly with rotor_angle; the upgraded count tells us how
            // many triangles are in the transition band.
            let total_weighted_area_m2: f64 = fractions
                .iter()
                .zip(solve_mesh.triangles.iter())
                .map(|(fr, tri)| {
                    if *fr <= 0.0 {
                        0.0
                    } else {
                        let [i, j, m] = *tri;
                        let (a, _) = triangle_gradients(&solve_mesh.nodes, i, j, m);
                        fr * a
                    }
                })
                .sum();
            eprintln!(
                    "  magnet_subelement: rotor_angle_deg={:.4} weighted_area_mm2={:.6} upgraded_airgap={}",
                    rotor_angle_rad.to_degrees(),
                    total_weighted_area_m2 * 1.0e6,
                    upgraded,
                );
            Some(fractions)
        } else {
            None
        }
    } else {
        None
    };

    let source_current_angle_deg = current_angle_deg;
    let problem = SolveProblem::from_prepared_mesh(
        ctx,
        config,
        solve_mesh,
        rotor_angle_rad,
        source_current_angle_deg,
        current_a,
    )
    .map_err(|err| err.to_string())?;
    let nonlinear_enabled = !problem.nonlinear_curves.is_empty();
    let nonlinear_config = resolve_nonlinear_solve_config(config, nonlinear_enabled);
    eprintln!(
        "  nonlinear_cfg: solver={} tol={:.5} max_iter={} relax={:.2} adaptive={} range=[{:.2},{:.2}] mu_step_cap={:.2} backtracking={}",
        nonlinear_config.solver_kind.label(),
        nonlinear_config.convergence_threshold,
        nonlinear_config.max_iterations,
        nonlinear_config.starting_relaxation(),
        nonlinear_config.adaptive_picard,
        nonlinear_config.min_relaxation,
        nonlinear_config.max_relaxation,
        nonlinear_config.mu_rel_step_cap,
        nonlinear_config.backtracking_enabled,
    );

    let mut materials = problem.materials.clone();
    apply_nonlinear_warm_start(&mut materials, &problem.mesh.regions, material_warm_start);
    let mut last_az: Option<Vec<f64>> = az_warm_start
        .filter(|guess| guess.len() == problem.mesh.nodes.len())
        .map(|guess| guess.to_vec());
    let linear_policy = resolve_motor_linear_solve_policy();
    let field_options = SolveOptions {
        linear: LinearSolveOptions {
            solver: if linear_policy.direct {
                LinearSolver::Direct
            } else {
                LinearSolver::Pcg
            },
            pcg_preconditioner: match linear_policy.pcg.preconditioner {
                PcgPreconditionerKind::IncompleteCholesky => PcgPreconditioner::IncompleteCholesky,
                PcgPreconditionerKind::Jacobi => PcgPreconditioner::Jacobi,
            },
            pcg_parallel: linear_policy.pcg.execution == PcgExecution::Parallel,
            pcg_residual_check_interval: linear_policy.pcg.residual_check_interval,
            tolerance: LINEAR_SOLVE_TIGHT_TOL,
            max_iterations: if ctx.n_pole_pitches > 1 { 5_000 } else { 2_000 },
        },
        nonlinear: NonlinearSolveOptions {
            algorithm: NonlinearAlgorithm::Picard,
            max_iterations: nonlinear_config.max_iterations,
            tolerance: nonlinear_config.convergence_threshold,
            relaxation: nonlinear_config.initial_relaxation,
            mu_r_step_cap: nonlinear_config.mu_rel_step_cap,
            ..NonlinearSolveOptions::default()
        },
    };
    let neutral_problem = problem.to_field_problem(
        &materials,
        motor_boundary_set(&problem.mesh, ctx.n_pole_pitches),
        field_options,
        magnet_fractions.as_deref(),
        last_az.as_deref(),
    );
    neutral_problem.validate()?;

    let mut total_assembly_ms = 0;
    let mut total_solve_ms = 0;
    let mut residual_history = Vec::new();
    let mut nonlinear_iteration_diagnostics = Vec::new();
    let nonlinear_diagnostics_path = nonlinear_diagnostics_path();
    let mut last_fields: Option<Vec<ElementField>> = None;
    let mut solved_with_newton = false;
    let mut solve_profile = solve_profile_enabled().then(SolveProfile::default);
    let direct_csr = direct_csr_enabled();
    let matrix_pattern = if direct_csr {
        let pattern_start = Instant::now();
        let pattern = SolveMatrixPattern::new(&neutral_problem)?;
        if let Some(profile) = solve_profile.as_mut() {
            profile.direct_csr_enabled = true;
            profile.csr_pattern_build_ms += elapsed_ms(pattern_start);
        }
        Some(pattern)
    } else {
        None
    };
    let neutral_material_ids = neutral_problem
        .elements
        .iter()
        .map(|element| element.material_id)
        .collect::<Vec<_>>();
    drop(neutral_problem);

    let SolveProblem {
        mesh: solve_mesh,
        materials: _,
        base_materials,
        current_densities_a_per_m2: j_z,
        nonlinear_curve_ids_by_element,
        nonlinear_curves,
        nonlinear_material_labels,
    } = problem;

    if nonlinear_enabled && nonlinear_config.solver_kind == NonlinearSolverKind::Newton {
        eprintln!("  nonlinear_solver: newton requested");
        let newton_current_scales = resolve_newton_current_scales(&j_z);
        match run_newton_nonlinear_loop(
            &solve_mesh,
            ctx.n_pole_pitches,
            config,
            &nonlinear_curve_ids_by_element,
            &nonlinear_curves,
            &nonlinear_material_labels,
            &j_z,
            &newton_current_scales,
            materials.clone(),
            magnet_fractions.as_deref(),
            last_az.as_deref(),
            progress,
            rotor_angle_rad,
            nonlinear_config,
            linear_policy,
            matrix_pattern.as_ref(),
            solve_profile.as_mut(),
        ) {
            Ok(output) => {
                total_assembly_ms += output.assembly_time_ms;
                total_solve_ms += output.solve_time_ms;
                residual_history = output.residual_history;
                nonlinear_iteration_diagnostics = output.diagnostics;
                materials = output.materials;
                last_az = Some(output.az);
                last_fields = Some(output.fields);
                solved_with_newton = true;
            }
            Err(err) => {
                eprintln!("  nonlinear_solver: newton failed; falling back to picard ({err})");
                materials = base_materials.clone();
                apply_nonlinear_warm_start(
                    &mut materials,
                    &solve_mesh.regions,
                    material_warm_start,
                );
            }
        }
    }

    if !solved_with_newton {
        let output = run_picard_nonlinear_loop(
            &solve_mesh,
            ctx.n_pole_pitches,
            config,
            &nonlinear_curve_ids_by_element,
            &nonlinear_curves,
            &nonlinear_material_labels,
            &j_z,
            materials,
            magnet_fractions.as_deref(),
            last_az.as_deref(),
            progress,
            rotor_angle_rad,
            nonlinear_enabled,
            nonlinear_config,
            nonlinear_diagnostics_path.is_some(),
            &mut residual_history,
            &mut nonlinear_iteration_diagnostics,
            linear_policy,
            matrix_pattern.as_ref(),
            solve_profile.as_mut(),
        );
        let output = match output {
            Ok(output) => output,
            Err(err) => {
                if let Some(path) = nonlinear_diagnostics_path.as_ref() {
                    let artifact = NonlinearDiagnosticsArtifact {
                        status: "FAIL".to_string(),
                        reason: "nonlinear solve failed to converge".to_string(),
                        rotor_angle_deg: rotor_angle_rad.to_degrees(),
                        nonlinear_enabled,
                        max_iterations: nonlinear_config.max_iterations,
                        convergence_threshold: nonlinear_config.convergence_threshold,
                        residual_history: residual_history.clone(),
                        iterations: nonlinear_iteration_diagnostics.clone(),
                    };
                    if let Err(write_err) = write_nonlinear_diagnostics_artifact(path, &artifact) {
                        eprintln!("warning: {write_err}");
                    }
                }
                return Err(err);
            }
        };
        total_assembly_ms += output.assembly_time_ms;
        total_solve_ms += output.solve_time_ms;
        residual_history = output.residual_history;
        nonlinear_iteration_diagnostics = output.diagnostics;
        materials = output.materials;
        last_az = Some(output.az);
        last_fields = Some(output.fields);
    }

    if let Some(path) = nonlinear_diagnostics_path.as_ref() {
        let artifact = NonlinearDiagnosticsArtifact {
            status: "PASS".to_string(),
            reason: "nonlinear solve converged".to_string(),
            rotor_angle_deg: rotor_angle_rad.to_degrees(),
            nonlinear_enabled,
            max_iterations: nonlinear_config.max_iterations,
            convergence_threshold: nonlinear_config.convergence_threshold,
            residual_history: residual_history.clone(),
            iterations: nonlinear_iteration_diagnostics.clone(),
        };
        if let Err(err) = write_nonlinear_diagnostics_artifact(path, &artifact) {
            eprintln!("warning: {err}");
        }
    }

    let last_az = last_az.ok_or_else(|| "solver did not produce an A_z solution".to_string())?;
    let fields = last_fields.ok_or_else(|| "solver did not produce element fields".to_string())?;
    let nonlinear_iterations = if nonlinear_enabled {
        residual_history.len().max(1)
    } else {
        1
    };
    let solver_method = if nonlinear_enabled {
        if solved_with_newton {
            "sparse_pcg_jacobi+damped_newton"
        } else {
            "sparse_pcg_jacobi+picard"
        }
    } else {
        "sparse_pcg_jacobi"
    }
    .to_string();
    let direct_cache = matrix_pattern
        .as_ref()
        .map(SolveMatrixPattern::direct_stats)
        .unwrap_or_default();
    if let Some(profile) = solve_profile.as_mut() {
        profile.direct_symbolic_builds = direct_cache.symbolic_builds;
        profile.direct_numeric_factorizations = direct_cache.numeric_factorizations;
        profile.direct_cache_hits = direct_cache.cache_hits;
        profile.direct_pattern_mismatches = direct_cache.pattern_mismatches;
        profile.direct_pcg_fallbacks = direct_cache.pcg_fallbacks;
    }
    let field_energy_j_per_m = field_energy_per_unit_depth(&solve_mesh, &materials, &fields);
    let field_solution = FieldSolution {
        az_nodal: last_az,
        element_fields: fields,
        final_material_state: materials
            .iter()
            .zip(neutral_material_ids)
            .map(|(material, material_id)| ElementMaterialState {
                material_id,
                mu_r: material.mu_rel,
                reluctivity_m_per_h: material.nu,
            })
            .collect(),
        convergence: ConvergenceReport {
            converged: true,
            nonlinear: nonlinear_enabled,
            nonlinear_algorithm: if solved_with_newton {
                "newton"
            } else {
                "picard"
            }
            .to_string(),
            nonlinear_iterations,
            nonlinear_residual_history: residual_history.clone(),
            linear_solver: if linear_policy.direct {
                "direct_cholesky_with_pcg_fallback"
            } else {
                "pcg"
            }
            .to_string(),
        },
        timings: SolveTimings {
            total_ms: total_assembly_ms + total_solve_ms,
            assembly_ms: total_assembly_ms,
            linear_solve_ms: total_solve_ms,
            ..SolveTimings::default()
        },
        profile: FieldSolveProfile {
            csr_pattern_builds: u64::from(matrix_pattern.is_some()),
            direct_symbolic_builds: direct_cache.symbolic_builds,
            direct_numeric_factorizations: direct_cache.numeric_factorizations,
            direct_cache_hits: direct_cache.cache_hits,
            direct_pattern_mismatches: direct_cache.pattern_mismatches,
            direct_pcg_fallbacks: direct_cache.pcg_fallbacks,
            direct_successful_solves: direct_cache
                .numeric_factorizations
                .saturating_sub(direct_cache.pcg_fallbacks),
            pcg: solve_profile
                .as_ref()
                .map(|profile| profile.pcg.clone())
                .unwrap_or_default(),
        },
        energy_per_unit_depth: FieldEnergyPerUnitDepth {
            magnetic_field_j_per_m: field_energy_j_per_m,
        },
        warnings: Vec::new(),
    };
    let summary_start = Instant::now();
    let mut summary =
        summarize_angle_solution(&solve_mesh, &field_solution, &ctx.centroids, config);
    if let Some(profile) = solve_profile.as_mut() {
        profile.postprocess_summary_ms += elapsed_ms(summary_start);
    }

    let excitation_start = Instant::now();
    let phase_currents =
        phase_currents_for_excitation(config, rotor_angle_rad, current_a, source_current_angle_deg);
    let excitation_summary = compute_slot_excitation_summary_from_phase_currents(
        &solve_mesh,
        &ctx.centroids,
        &config.winding.winding_type,
        config.stator.slot_count,
        config.rotor.pole_count,
        config.winding.turns_per_coil,
        source_current_angle_deg,
        phase_currents,
        &j_z,
    );
    if let Some(profile) = solve_profile.as_mut() {
        profile.slot_excitation_summary_ms += elapsed_ms(excitation_start);
    }
    summary.source_current_angle_deg = excitation_summary.source_current_angle_deg;
    summary.phase_current_a = excitation_summary.phase_current_a;
    summary.slot_excitation_contributions = excitation_summary.slot_excitation_contributions;
    let energy_start = Instant::now();
    summary.energy_functional = compute_energy_functional_summary(
        &solve_mesh,
        &materials,
        &j_z,
        &field_solution.az_nodal,
        config.stator.stack_length_mm,
        config.rotor.pole_count,
    );
    if let Some(profile) = solve_profile.as_mut() {
        profile.energy_summary_ms += elapsed_ms(energy_start);
    }
    Ok((
        field_solution.element_fields,
        summary,
        field_solution.az_nodal,
        AngleSolveDiagnostics {
            assembly_time_ms: total_assembly_ms,
            solve_time_ms: total_solve_ms,
            solver_method,
            nonlinear_enabled,
            nonlinear_iterations,
            nonlinear_residual_history: residual_history,
            profile: solve_profile,
        },
        build_nonlinear_warm_start(&materials),
    ))
}

#[derive(Debug, Serialize)]
struct LiveFieldMesh {
    pub config_summary: ConfigSummary,
    pub mesh_info: MeshInfo,
    /// Node coordinates [x, y] in mm for frontend rendering.
    pub nodes_mm: Vec<[f64; 2]>,
    /// Triangle connectivity: 3 node indices per element.
    pub triangles: Vec<[usize; 3]>,
    /// Static region tag per triangle for the shared fixed mesh.
    pub regions: Vec<String>,
    /// Number of pole pitches modeled.
    pub n_pole_pitches: u32,
    /// Total angular span in degrees.
    pub total_span_deg: f64,
}

#[derive(Debug, Serialize)]
struct LiveFieldPlotData {
    /// Solved nodal magnetic vector potential A_z.
    pub az_nodal: Vec<f64>,
    /// Number of pole pitches modeled.
    pub n_pole_pitches: u32,
    /// Total angular span in degrees.
    pub total_span_deg: f64,
}

#[derive(Debug, Serialize)]
struct LiveFieldFrame<Plot> {
    pub position: usize,
    pub total: usize,
    pub angle_deg: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config_summary: Option<ConfigSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mesh_info: Option<MeshInfo>,
    pub field_plot: Plot,
    pub airgap_brbt: Option<AirgapBrBtProfile>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub noload_field_plot: Option<Plot>,
}

fn region_strings(regions: &[Region]) -> Vec<String> {
    regions
        .iter()
        .map(|region| region_string(Some(*region)))
        .collect()
}

fn region_string(region: Option<Region>) -> String {
    match region {
        Some(Region::RotorCore) => "rotor_core".to_string(),
        Some(Region::Magnet) => "magnet".to_string(),
        Some(Region::Airgap) => "airgap".to_string(),
        Some(Region::StatorTooth) => "stator_tooth".to_string(),
        Some(Region::StatorYoke) => "stator_yoke".to_string(),
        Some(Region::SlotWinding) => "slot_winding".to_string(),
        Some(Region::FluxBarrier) => "flux_barrier".to_string(),
        Some(Region::MagnetPocketAir) => "magnet_pocket_air".to_string(),
        None => "unknown".to_string(),
    }
}

fn live_field_mesh_for_context(ctx: &SolveContext) -> LiveFieldMesh {
    LiveFieldMesh {
        config_summary: ctx.config_summary.clone(),
        mesh_info: ctx.mesh.info.clone(),
        nodes_mm: ctx
            .mesh
            .nodes
            .iter()
            .map(|node| [node[0] * 1e3, node[1] * 1e3])
            .collect(),
        triangles: ctx.mesh.triangles.clone(),
        regions: region_strings(&ctx.mesh.regions),
        n_pole_pitches: ctx.n_pole_pitches,
        total_span_deg: ctx.mesh.info.total_span_deg,
    }
}

fn field_plot_data_for_context(
    ctx: &SolveContext,
    regions: Vec<Region>,
    az_nodal: Vec<f64>,
) -> FieldPlotData {
    FieldPlotData {
        nodes_mm: ctx
            .mesh
            .nodes
            .iter()
            .map(|node| [node[0] * 1e3, node[1] * 1e3])
            .collect(),
        triangles: ctx.mesh.triangles.clone(),
        regions: region_strings(&regions),
        az_nodal,
        n_pole_pitches: ctx.n_pole_pitches,
        total_span_deg: ctx.mesh.info.total_span_deg,
    }
}

fn live_field_plot_data_for_context(ctx: &SolveContext, az_nodal: Vec<f64>) -> LiveFieldPlotData {
    LiveFieldPlotData {
        az_nodal,
        n_pole_pitches: ctx.n_pole_pitches,
        total_span_deg: ctx.mesh.info.total_span_deg,
    }
}

fn stream_noload_live_field_enabled() -> bool {
    std::env::var("COILEM_MAGNETO2D_STREAM_NOLOAD_FIELD")
        .ok()
        .map(|value| {
            matches!(
                value.to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

fn stream_live_field_frames_enabled() -> bool {
    std::env::var("COILEM_MAGNETO2D_STREAM_FIELD_FRAMES")
        .ok()
        .map(|value| {
            matches!(
                value.to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(true)
}

fn live_field_frame_stride(n_positions: usize) -> usize {
    std::env::var("COILEM_MAGNETO2D_FIELD_FRAME_STRIDE")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|stride| *stride > 0)
        .unwrap_or_else(|| ((n_positions + 31) / 32).max(1))
}

fn build_airgap_brbt_profile(
    mesh: &crate::mesh::TriMesh,
    fields: &[ElementField],
    regions: &[Region],
    airgap_band: AirgapBand,
) -> Option<AirgapBrBtProfile> {
    eprintln!(
        "DEBUG_AIRGAP: triangles.len()={}, fields.len()={}, regions.len()={}, airgap_band={:?}",
        mesh.triangles.len(),
        fields.len(),
        regions.len(),
        airgap_band
    );
    if mesh.triangles.is_empty() || fields.len() != mesh.triangles.len() {
        eprintln!(
            "DEBUG_AIRGAP: Early exit because empty or len mismatch (fields={} vs triangles={})",
            fields.len(),
            mesh.triangles.len()
        );
        return None;
    }

    let span_deg = mesh.info.total_span_deg.clamp(1.0, 360.0);
    let bin_count = ((span_deg * 0.75).round() as usize).clamp(48, 144);
    let mut bins = vec![(0.0_f64, 0.0_f64, 0.0_f64, 0_usize); bin_count];

    let airgap_inner_radius_m = airgap_band.inner_radius_m();
    let airgap_outer_radius_m = airgap_band.outer_radius_m();
    let airgap_padding_m = if airgap_outer_radius_m > airgap_inner_radius_m {
        ((airgap_outer_radius_m - airgap_inner_radius_m) * 0.12).max(0.02e-3)
    } else {
        0.0
    };

    let mut sample_count = 0_usize;
    for (index, tri) in mesh.triangles.iter().enumerate() {
        if regions.get(index).copied().unwrap_or(mesh.regions[index]) != Region::Airgap {
            continue;
        }
        let Some(field) = fields.get(index) else {
            continue;
        };
        let [i, j, k] = *tri;
        let cx = (mesh.nodes[i][0] + mesh.nodes[j][0] + mesh.nodes[k][0]) / 3.0;
        let cy = (mesh.nodes[i][1] + mesh.nodes[j][1] + mesh.nodes[k][1]) / 3.0;
        let radius_m = (cx * cx + cy * cy).sqrt();
        if radius_m <= 1e-12 {
            continue;
        }
        if airgap_outer_radius_m > airgap_inner_radius_m
            && (radius_m < airgap_inner_radius_m - airgap_padding_m
                || radius_m > airgap_outer_radius_m + airgap_padding_m)
        {
            continue;
        }

        let cos_theta = cx / radius_m;
        let sin_theta = cy / radius_m;
        let br_t = field.bx * cos_theta + field.by * sin_theta;
        let bt_t = -field.bx * sin_theta + field.by * cos_theta;
        if !br_t.is_finite() || !bt_t.is_finite() {
            continue;
        }

        let mut angle_deg = cy.atan2(cx).to_degrees() % 360.0;
        if angle_deg < 0.0 {
            angle_deg += 360.0;
        }
        if span_deg < 359.5 {
            angle_deg %= span_deg;
        }
        let bin_index =
            (((angle_deg / span_deg) * bin_count as f64).floor() as usize).min(bin_count - 1);
        let bin = &mut bins[bin_index];
        bin.0 += br_t;
        bin.1 += bt_t;
        bin.2 += br_t * bt_t;
        bin.3 += 1;
        sample_count += 1;
    }

    if sample_count == 0 {
        return None;
    }

    let profile_bins = bins
        .into_iter()
        .enumerate()
        .filter_map(|(index, (sum_br, sum_bt, sum_br_bt, count))| {
            if count == 0 {
                return None;
            }
            let inv_count = 1.0 / count as f64;
            Some(AirgapBrBtBin {
                mech_angle_deg: ((index as f64 + 0.5) / bin_count as f64) * span_deg,
                br_t: sum_br * inv_count,
                bt_t: sum_bt * inv_count,
                br_bt_t2: sum_br_bt * inv_count,
                samples: count,
            })
        })
        .collect();

    Some(AirgapBrBtProfile {
        span_deg,
        bin_count,
        sample_count,
        bins: profile_bins,
    })
}

/// Generate mesh geometry without running any field solve.
/// Used by the frontend "View Mesh" button for instant geometry preview.
#[allow(dead_code)]
pub fn generate_mesh_preview(config: &MotorConfig) -> Result<MeshPreviewReport, String> {
    generate_mesh_preview_at_angle(config, 0.0)
}

/// Generate mesh geometry with rotor features baked at `rotor_angle_rad`.
/// This mirrors the remesh-per-step path and lets mesh-only diagnostics inspect
/// the exact geometry used at a rotor position.
pub fn generate_mesh_preview_at_angle(
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Result<MeshPreviewReport, String> {
    let start = Instant::now();
    let mesh = generate_solve_mesh_at_angle(config, rotor_angle_rad)?;
    let n_pole_pitches = mesh.info.n_pole_pitches;
    let total_span_deg = mesh.info.total_span_deg;

    // Keep coordinates in mm for frontend rendering (no SI conversion).
    let nodes_mm: Vec<[f64; 2]> = mesh.nodes.clone();

    let region_strings = region_strings(&mesh.regions);

    let config_summary = config_summary_for(config, 0.0, 0.0);
    let solve_mesh_artifact = SolveMeshArtifact::from_mesh(mesh.clone());

    let generation_time_ms = start.elapsed().as_millis() as u64;

    eprintln!(
        "magneto2d: mesh-only preview: {} nodes, {} triangles, rotor_angle={:.3}deg mech in {}ms",
        mesh.info.num_nodes,
        mesh.info.num_triangles,
        rotor_angle_rad.to_degrees(),
        generation_time_ms,
    );

    Ok(MeshPreviewReport {
        config_summary,
        mesh_info: mesh.info,
        nodes_mm,
        triangles: mesh.triangles,
        regions: region_strings,
        n_pole_pitches,
        total_span_deg,
        generation_time_ms,
        solve_mesh_artifact,
    })
}

/// Run a single-angle magnetostatic solve.
#[allow(dead_code)]
pub fn run_magnetostatic_solve(config: &MotorConfig) -> Result<SolveReport, String> {
    run_magnetostatic_solve_at_angle(config, 0.0)
}

/// Single-angle solve with an explicit rotor mechanical angle (radians).
/// Used by the no-load B-field diagnostic — lets the CLI snapshot the
/// field at a non-zero rotor offset without running a full sweep.
#[allow(dead_code)]
pub fn run_magnetostatic_solve_at_angle(
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Result<SolveReport, String> {
    run_magnetostatic_solve_at_angle_with_mesh(config, rotor_angle_rad, None)
}

pub fn run_magnetostatic_solve_at_angle_with_mesh(
    config: &MotorConfig,
    rotor_angle_rad: f64,
    solve_mesh_artifact: Option<SolveMeshArtifact>,
) -> Result<SolveReport, String> {
    let total_start = Instant::now();
    let (context_artifact, rotor_baked_in_mesh) =
        single_angle_context_artifact(config, rotor_angle_rad, solve_mesh_artifact)?;
    let ctx = setup_context(config, context_artifact)?;
    let pole_pairs = ((config.rotor.pole_count / 2).max(1)) as usize;
    let synced_current_angle =
        synced_current_angle_deg(rotor_angle_rad, pole_pairs, ctx.current_angle);

    eprintln!(
        "magneto2d: mesh {} nodes, {} triangles, {} pole pitches, rotor_angle={:.3}deg mech",
        ctx.solve_mesh_artifact.mesh.info.num_nodes,
        ctx.solve_mesh_artifact.mesh.info.num_triangles,
        ctx.n_pole_pitches,
        rotor_angle_rad.to_degrees(),
    );

    let (_fields, summary, az_slice, diagnostics, _warm_start) = solve_at_angle(
        &ctx,
        config,
        rotor_angle_rad,
        synced_current_angle,
        ctx.current_a,
        rotor_baked_in_mesh,
        None,
        None,
        None,
    )?;

    let max_az = az_slice.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let min_az = az_slice.iter().copied().fold(f64::INFINITY, f64::min);

    eprintln!(
        "magneto2d: peak B airgap={:.4}T, torque(contour)={:.4}Nm, torque(Arkkio)={:.4}Nm, torque(area_mst)={:.4}Nm",
        summary.peak_b_airgap_t, summary.torque_nm, summary.torque_arkkio_nm, summary.torque_area_mst_nm,
    );
    let solve_regions = if rotor_baked_in_mesh {
        ctx.mesh.regions.clone()
    } else {
        rotated_rotor_regions(&ctx.mesh, &ctx.centroids, config, rotor_angle_rad)?
    };
    let field_plot = field_plot_data_for_context(&ctx, solve_regions, az_slice);

    Ok(SolveReport {
        config_summary: ctx.config_summary,
        operating_point: ctx.operating_point,
        mesh_info: ctx.mesh.info.clone(),
        solve_info: SolveInfo {
            num_dofs: ctx.mesh.nodes.len(),
            assembly_time_ms: diagnostics.assembly_time_ms,
            solve_time_ms: diagnostics.solve_time_ms,
            total_time_ms: total_start.elapsed().as_millis() as u64,
            solver_method: diagnostics.solver_method,
            max_az,
            min_az,
            nonlinear_enabled: diagnostics.nonlinear_enabled,
            nonlinear_iterations: diagnostics.nonlinear_iterations,
            nonlinear_residual_history: diagnostics.nonlinear_residual_history,
            profile: diagnostics.profile,
        },
        results: summary,
        field_plot,
    })
}

fn compact_batch_solve_report(
    report: SolveReport,
    keep_field_plot: bool,
) -> Result<serde_json::Value, String> {
    let mut value = serde_json::to_value(report)
        .map_err(|err| format!("failed to serialize batch solve report: {err}"))?;
    if !keep_field_plot {
        if let Some(object) = value.as_object_mut() {
            object.remove("field_plot");
        }
    }
    Ok(value)
}

/// Run independent imported-mesh single-angle solves inside one Rayon pool.
///
/// Python still owns Gmsh remeshing per angle, but this path avoids launching
/// one Rust process per angle and lets Magneto2D use the host cores across the
/// imported solve jobs. Output order follows input order.
pub fn run_imported_mesh_batch_with_workers(
    config: &MotorConfig,
    batch: ImportedMeshBatchInput,
    workers: Option<usize>,
) -> Result<ImportedMeshBatchReport, String> {
    let total = batch.jobs.len();
    if total == 0 {
        return Err("imported mesh batch must include at least one job".to_string());
    }
    let host_cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let run_batch = move || -> Result<ImportedMeshBatchReport, String> {
        let completed = AtomicUsize::new(0);
        let pole_pairs = ((config.rotor.pole_count / 2).max(1)) as f64;
        let keep_first_field_plot = batch.keep_first_field_plot;
        let keep_all_field_plots = batch.keep_all_field_plots;
        let mut reports = batch
            .jobs
            .into_par_iter()
            .enumerate()
            .map(|(idx, job)| {
                let rotor_angle_deg = job.rotor_angle_deg;
                let report = run_magnetostatic_solve_at_angle_with_mesh(
                    config,
                    rotor_angle_deg.to_radians(),
                    Some(job.solve_mesh_artifact),
                )?;
                let done = completed.fetch_add(1, Ordering::SeqCst) + 1;
                let elec_deg = rotor_angle_deg * pole_pairs;
                let torque_nm = report.results.torque_nm;
                eprintln!("[{done}/{total}] elec={elec_deg:.3}° contour={torque_nm:.6}Nm");
                let keep_field_plot = keep_all_field_plots || (keep_first_field_plot && idx == 0);
                let value = compact_batch_solve_report(report, keep_field_plot)?;
                Ok::<(usize, serde_json::Value), String>((idx, value))
            })
            .collect::<Result<Vec<_>, String>>()?;
        reports.sort_by_key(|(idx, _)| *idx);
        Ok(ImportedMeshBatchReport {
            reports: reports.into_iter().map(|(_, report)| report).collect(),
        })
    };

    if let Some(n_threads) = workers {
        let n_threads = n_threads.max(1);
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(n_threads)
            .build()
            .map_err(|e| format!("failed to build rayon pool with {n_threads} thread(s): {e}"))?;
        eprintln!(
            "magneto2d: imported-mesh batch rayon pool sized to {n_threads} thread(s) \
             (host has {host_cores} logical core(s), jobs={total})"
        );
        return pool.install(run_batch);
    }
    eprintln!(
        "magneto2d: imported-mesh batch using default rayon thread count \
         ({} thread(s) available, host has {host_cores} logical core(s), jobs={total})",
        rayon::current_num_threads()
    );
    run_batch()
}

/// Run a rotor sweep: solve at multiple angles, compute torque waveform and back-EMF.
#[allow(dead_code)]
pub fn run_rotor_sweep(
    config: &MotorConfig,
    n_positions: usize,
    serial: bool,
) -> Result<SweepReport, String> {
    run_rotor_sweep_with_mesh(config, n_positions, None, serial, None)
}

/// Full-cycle (360°) sweep with an explicit mesh. Back-compat wrapper that
/// forwards `None` for the partial-sweep span so existing callers keep
/// their behaviour. Routes through `run_rotor_sweep_with_mesh_and_workers`
/// so the `serial` flag and the new `--workers N` CLI surface share the
/// same rayon-pool sizing logic.
#[allow(dead_code)]
pub fn run_rotor_sweep_with_mesh(
    config: &MotorConfig,
    n_positions: usize,
    sweep_span_deg: Option<f64>,
    serial: bool,
    solve_mesh_artifact: Option<SolveMeshArtifact>,
) -> Result<SweepReport, String> {
    let workers = if serial { Some(1) } else { None };
    run_rotor_sweep_with_mesh_and_workers(
        config,
        n_positions,
        sweep_span_deg,
        workers,
        solve_mesh_artifact,
    )
}

/// Full-cycle (or partial-span) sweep with an explicit mesh AND an explicit
/// rayon worker count. This is the canonical entry point:
///
/// * `workers == Some(1)`  → 1-thread rayon pool (equivalent to the legacy
///   `--serial` A/B harness).
/// * `workers == Some(N)`  → N-thread rayon pool. Used by the parity-check
///   path to pick a worker count that matches operator hardware (operator
///   sets `COILEM_MAGNETO2D_WORKERS=N` or passes `--workers N`).
/// * `workers == None`     → rayon's default (all available host cores).
///
/// The per-position parallelism inside `run_rotor_sweep_inner` is
/// unchanged — `pool.install(...)` just pins the parallel iterators
/// inside to the requested pool size. The numerical output is invariant
/// across pool sizes (per-position solves are independent and rayon's
/// reduction is associative for the sums we accumulate).
pub fn run_rotor_sweep_with_mesh_and_workers(
    config: &MotorConfig,
    n_positions: usize,
    sweep_span_deg: Option<f64>,
    workers: Option<usize>,
    solve_mesh_artifact: Option<SolveMeshArtifact>,
) -> Result<SweepReport, String> {
    let host_cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    if let Some(n_threads) = workers {
        let n_threads = n_threads.max(1);
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(n_threads)
            .build()
            .map_err(|e| format!("failed to build rayon pool with {n_threads} thread(s): {e}"))?;
        eprintln!(
            "magneto2d: rayon pool sized to {n_threads} thread(s) \
             (host has {host_cores} logical core(s))"
        );
        return pool.install(|| {
            run_rotor_sweep_inner(config, n_positions, sweep_span_deg, solve_mesh_artifact)
        });
    }
    eprintln!(
        "magneto2d: rayon pool using default thread count \
         ({} thread(s) available, host has {host_cores} logical core(s))",
        rayon::current_num_threads()
    );
    run_rotor_sweep_inner(config, n_positions, sweep_span_deg, solve_mesh_artifact)
}

fn run_rotor_sweep_inner(
    config: &MotorConfig,
    n_positions: usize,
    sweep_span_deg: Option<f64>,
    solve_mesh_artifact: Option<SolveMeshArtifact>,
) -> Result<SweepReport, String> {
    let total_start = Instant::now();
    let imported_solve_mesh = solve_mesh_artifact.is_some();
    let ctx = setup_context(config, solve_mesh_artifact)?;
    let pole_pairs = ((config.rotor.pole_count / 2).max(1)) as usize;
    let solve_options = config.solve_options.as_ref();
    let run_cogging = solve_options
        .and_then(|opts| opts.cogging_torque)
        .unwrap_or(false);
    let run_thd = solve_options
        .and_then(|opts| opts.thd_analysis)
        .unwrap_or(false);
    let run_back_emf = solve_options.and_then(|opts| opts.back_emf).unwrap_or(true);
    let run_main_no_load = run_back_emf || run_thd;

    // Sweep span defaults to one full electrical period (360°); when the
    // caller passes an explicit partial span we distribute the same N
    // positions over [0°, span). This is what 2×-nested Native-FEM
    // quick-tier presets use to mirror FEMM's 60° quick sweep without
    // having to burn a full-cycle solve.
    let sweep_span_deg = sweep_span_deg.unwrap_or(360.0);
    let elec_step = sweep_span_deg / n_positions as f64;

    let requested_remesh = uses_remesh_per_step(config);
    let remesh = requested_remesh && !imported_solve_mesh;
    if requested_remesh && imported_solve_mesh {
        eprintln!(
            "magneto2d: imported mesh input is fixed; ignoring rotor_rotation_model=remesh_per_step"
        );
    }
    eprintln!(
        "magneto2d: rotor sweep with {} positions over {} elec deg ({} pole pitches), rotor_rotation_model={}",
        n_positions,
        sweep_span_deg,
        ctx.n_pole_pitches,
        if remesh { "remesh_per_step" } else { "fixed_mesh" },
    );
    eprintln!(
        "magneto2d: mesh {} nodes, {} triangles",
        ctx.solve_mesh_artifact.mesh.info.num_nodes,
        ctx.solve_mesh_artifact.mesh.info.num_triangles
    );

    // ── Sextant symmetry mode (opt-in, MAGNETO2D_SWEEP_SEXTANT=1) ────────
    //
    // Solve only [0°, 60°) electrical with n/6 positions and reconstruct the
    // full cycle from balanced-3-phase symmetry (see sextant_phase_map).
    // Fixed-mesh sweeps only: remesh-per-step would need a mesh per
    // reconstructed angle. Imported fixed meshes (Gmsh/FEMM artifacts swept
    // internally) are fine: the artifact's baked current densities are only
    // consumed at the artifact's own angle (mesh_metadata.rs), every other
    // step already uses the same native current synthesis the reconstruction
    // relies on, and the 60° verification position guards the rest.
    let sextant_active = if sweep_sextant_requested() {
        let full_cycle = (sweep_span_deg - 360.0).abs() <= 1e-9;
        let divisible = n_positions >= 6 && n_positions % 6 == 0;
        let balanced =
            balanced_three_phase_winding(config.stator.slot_count, config.rotor.pole_count);
        let six_step = config
            .solve_params
            .as_ref()
            .map(|sp| sp.excitation_mode_label() == "ideal_six_step_120")
            .unwrap_or(false);
        let eligible = full_cycle && divisible && balanced && !remesh && !six_step;
        if eligible {
            eprintln!(
                "magneto2d: sextant symmetry active — solving {} positions over 60 elec deg \
                 plus one verification position, reconstructing {} positions over 360 elec deg \
                 (stator core loss is skipped in this mode; MAGNETO2D_SWEEP_SEXTANT=0 to disable)",
                n_positions / 6,
                n_positions,
            );
        } else {
            eprintln!(
                "magneto2d: sextant symmetry requested but not eligible \
                 (full_cycle={full_cycle} positions_divisible_by_6={divisible} \
                 balanced_winding={balanced} remesh={remesh} six_step={six_step}); \
                 running the full sweep",
            );
        }
        eligible
    } else {
        false
    };
    // Window positions plus one verification position at 60° elec: the first
    // reconstructed angle is also solved for real and compared against its
    // reconstruction, so a machine whose simulated symmetry is broken (or a
    // wrong phase-relabel convention) demotes the run to a full sweep instead
    // of silently producing tiled garbage.
    let n_solve_positions = if sextant_active {
        n_positions / 6 + 1
    } else {
        n_positions
    };

    // Per-position outcome bundle; produced in parallel, then stitched into
    // the per-waveform Vecs downstream so post-sweep code is untouched.
    struct PositionOutcome {
        elec_deg: f64,
        loaded_summary: FieldSummary,
        noload_summary: FieldSummary,
        loaded_fields: Vec<ElementField>,
        loaded_nonlinear_iters: usize,
        noload_nonlinear_iters: usize,
    }

    // Gamma is measured from the q-axis; positive gamma is flux-weakening advance.
    let advance_deg = ctx.current_angle;

    // ── Parallel rotor sweep ────────────────────────────────────
    //
    // Each position is an independent magnetostatic solve. Back-EMF/THD runs
    // also solve a no-load companion field at the same angle; torque-only
    // parity diagnostics skip that leg to keep the field cache fast.
    //
    // Ordering: rayon may finish positions out of index order. Results are
    // collect()ed back into input order for downstream processing, but the
    // backend progress parser (backend/magneto2d_adapter.py) needs a live
    // [N/total] ... contour=XNm tick per worker completion so the UI bar
    // advances smoothly. We emit that line from inside the worker using an
    // AtomicUsize for the N counter — N is monotonic in completion order
    // (not index order), which is exactly what a progress bar wants.
    let completed = AtomicUsize::new(0);
    let live_field_frame_stride = live_field_frame_stride(n_solve_positions);

    if !remesh {
        match serde_json::to_string(&live_field_mesh_for_context(&ctx)) {
            Ok(payload) => eprintln!("COILEM_FIELD_MESH {payload}"),
            Err(err) => eprintln!("warning: failed to serialize live field mesh: {err}"),
        }
    }

    // ── Cross-position warm-start seed ────────────────────────────────────
    //
    // Each rotor position used to cold-start its Picard loop even though the
    // rotor has only moved a few electrical degrees from the previous one,
    // burning ~30-50 outer iterations to walk the iron μ field back to a
    // fixed point we already had. Compute one seed solve at angle 0 with the
    // loaded current applied and reuse its converged (A_z, μ) for every
    // parallel worker; Picard then typically converges in ~5-10 iterations
    // per position instead.
    //
    // Position 0 of the par_iter below re-solves the same point we used as
    // the seed, but with a perfect warm-start it converges in 1-2 iterations
    // so the redundancy is essentially free.
    //
    // In remesh_per_step mode each position has its own mesh with a different
    // node count and ordering, so cross-position A_z warm-starting would
    // require mesh-to-mesh projection — out of scope here. Skip the seed in
    // that mode and keep the existing cold-start behaviour.
    let cross_position_seed: Option<(NonlinearWarmStart, Vec<f64>)> =
        if !remesh && n_solve_positions > 1 {
            let seed_progress = AngleProgressContext {
                parent_stage: "magneto2d_sweep",
                solve_kind: "warm_start_seed",
                position_index: 0,
                total_positions: n_solve_positions,
                completed_positions: &completed,
                elec_deg: 0.0,
            };
            let synced_at_zero = synced_current_angle_deg(0.0, pole_pairs, advance_deg);
            let seed_started = Instant::now();
            let (_seed_fields, _seed_summary, seed_az, _seed_diag, seed_warm) = solve_at_angle(
                &ctx,
                config,
                0.0,
                synced_at_zero,
                ctx.current_a,
                false,
                None,
                None,
                Some(&seed_progress),
            )?;
            eprintln!(
                "magneto2d: cross-position warm-start seed ready ({} A_z DOFs, {} ms)",
                seed_az.len(),
                seed_started.elapsed().as_millis(),
            );
            Some((seed_warm, seed_az))
        } else {
            None
        };
    let cross_position_seed_ref = cross_position_seed.as_ref();

    let sweep_start = Instant::now();
    // Shared per-position solve body. `progress_total` is the denominator of
    // the live "[N/total]" progress lines: the solved window in sextant mode,
    // the full grid otherwise (and again the full grid when a failed sextant
    // verification demotes the run and the remaining positions are solved).
    let solve_position = |i: usize, progress_total: usize| -> Result<PositionOutcome, String> {
        {
            let elec_deg = i as f64 * elec_step;
            let mech_rad = elec_deg.to_radians() / pole_pairs as f64;
            let synced_current_angle = synced_current_angle_deg(mech_rad, pole_pairs, advance_deg);

            // In remesh_per_step mode rebuild the mesh (and derived
            // centroids) with the rotor baked at mech_rad. The rest of
            // the solve context (operating point, slot areas, rated
            // speed, etc.) is mesh-independent and reused. In fixed_mesh
            // mode this branch is skipped and `&ctx` is shared across
            // all positions, as today.
            let step_ctx_storage;
            let step_ctx: &SolveContext = if remesh {
                step_ctx_storage = remesh_ctx_for_angle(&ctx, config, mech_rad)?;
                &step_ctx_storage
            } else {
                &ctx
            };

            let loaded_progress = AngleProgressContext {
                parent_stage: "magneto2d_sweep",
                solve_kind: "loaded",
                position_index: i + 1,
                total_positions: progress_total,
                completed_positions: &completed,
                elec_deg,
            };
            // Pull the loaded warm-start seed (if available — only in fixed-mesh
            // sweeps; remesh_per_step has a different mesh per position so a
            // shared A_z seed would be meaningless without mesh projection).
            let seed_material = cross_position_seed_ref.map(|(warm, _)| warm);
            let seed_az = cross_position_seed_ref.map(|(_, az)| az.as_slice());
            let (loaded_fields, loaded_summary, loaded_az, loaded_diagnostics, loaded_warm_start) =
                solve_at_angle(
                    step_ctx,
                    config,
                    mech_rad,
                    synced_current_angle,
                    ctx.current_a,
                    remesh,
                    seed_material,
                    seed_az,
                    Some(&loaded_progress),
                )?;

            let (noload_summary, noload_az, noload_solve_ms, noload_nonlinear_iters) =
                if run_main_no_load {
                    let noload_progress = AngleProgressContext {
                        parent_stage: "magneto2d_sweep",
                        solve_kind: "no_load",
                        position_index: i + 1,
                        total_positions: progress_total,
                        completed_positions: &completed,
                        elec_deg,
                    };
                    let (
                        _noload_fields,
                        noload_summary,
                        noload_az,
                        noload_diagnostics,
                        _noload_warm_start,
                    ) = solve_at_angle(
                        step_ctx,
                        config,
                        mech_rad,
                        0.0,
                        0.0,
                        remesh,
                        Some(&loaded_warm_start),
                        Some(&loaded_az),
                        Some(&noload_progress),
                    )?;
                    (
                        noload_summary,
                        noload_az,
                        noload_diagnostics.solve_time_ms,
                        noload_diagnostics.nonlinear_iterations,
                    )
                } else {
                    let mut skipped_summary = loaded_summary.clone();
                    skipped_summary.flux_linkage_a_wb = 0.0;
                    skipped_summary.flux_linkage_b_wb = 0.0;
                    skipped_summary.flux_linkage_c_wb = 0.0;
                    skipped_summary.slot_flux_linkage_contributions.clear();
                    (skipped_summary, loaded_az.clone(), 0, 0)
                };

            // Live progress tick — backend regex matches this line.
            let done = completed.fetch_add(1, Ordering::Relaxed) + 1;
            if run_main_no_load {
                eprintln!(
                    "  [{}/{}] elec={:.1}° contour={:.4}Nm arkkio={:.4}Nm Ψa_noload={:.6}Wb Ψb_noload={:.6}Wb Ψc_noload={:.6}Wb (loaded={}ms noload={}ms)",
                    done,
                    progress_total,
                    elec_deg,
                    loaded_summary.torque_nm,
                    loaded_summary.torque_arkkio_nm,
                    noload_summary.flux_linkage_a_wb,
                    noload_summary.flux_linkage_b_wb,
                    noload_summary.flux_linkage_c_wb,
                    loaded_diagnostics.solve_time_ms,
                    noload_solve_ms,
                );
            } else {
                eprintln!(
                    "  [{}/{}] elec={:.1}° contour={:.4}Nm arkkio={:.4}Nm (loaded={}ms noload=skipped)",
                    done,
                    progress_total,
                    elec_deg,
                    loaded_summary.torque_nm,
                    loaded_summary.torque_arkkio_nm,
                    loaded_diagnostics.solve_time_ms,
                );
            }

            let should_emit_live_field_frame =
                i == 0 || i + 1 == progress_total || i % live_field_frame_stride == 0;
            if should_emit_live_field_frame {
                let live_regions = if remesh {
                    step_ctx.mesh.regions.clone()
                } else {
                    rotated_rotor_regions(&step_ctx.mesh, &step_ctx.centroids, config, mech_rad)?
                };
                let airgap_brbt = build_airgap_brbt_profile(
                    &step_ctx.mesh,
                    &loaded_fields,
                    &live_regions,
                    step_ctx.airgap_band,
                );
                if stream_live_field_frames_enabled() && remesh {
                    let noload_field_plot =
                        if run_main_no_load && stream_noload_live_field_enabled() {
                            Some(field_plot_data_for_context(
                                step_ctx,
                                live_regions.clone(),
                                noload_az,
                            ))
                        } else {
                            None
                        };
                    let live_frame = LiveFieldFrame {
                        position: done,
                        total: progress_total,
                        angle_deg: elec_deg,
                        config_summary: Some(step_ctx.config_summary.clone()),
                        mesh_info: Some(step_ctx.mesh.info.clone()),
                        field_plot: field_plot_data_for_context(step_ctx, live_regions, loaded_az),
                        airgap_brbt,
                        noload_field_plot,
                    };
                    match serde_json::to_string(&live_frame) {
                        Ok(payload) => eprintln!("COILEM_FIELD_FRAME {payload}"),
                        Err(err) => {
                            eprintln!("warning: failed to serialize live field frame: {err}")
                        }
                    }
                } else if stream_live_field_frames_enabled() {
                    let noload_field_plot =
                        if run_main_no_load && stream_noload_live_field_enabled() {
                            Some(live_field_plot_data_for_context(step_ctx, noload_az))
                        } else {
                            None
                        };
                    let live_frame = LiveFieldFrame {
                        position: done,
                        total: progress_total,
                        angle_deg: elec_deg,
                        config_summary: None,
                        mesh_info: None,
                        field_plot: live_field_plot_data_for_context(step_ctx, loaded_az),
                        airgap_brbt,
                        noload_field_plot,
                    };
                    match serde_json::to_string(&live_frame) {
                        Ok(payload) => eprintln!("COILEM_FIELD_FRAME {payload}"),
                        Err(err) => {
                            eprintln!("warning: failed to serialize live field frame: {err}")
                        }
                    }
                }
            }

            Ok::<PositionOutcome, String>(PositionOutcome {
                elec_deg,
                loaded_summary,
                noload_summary,
                loaded_fields,
                loaded_nonlinear_iters: loaded_diagnostics.nonlinear_iterations,
                noload_nonlinear_iters,
            })
        }
    };

    let mut outcomes: Vec<PositionOutcome> = (0..n_solve_positions)
        .into_par_iter()
        .map(|i| solve_position(i, n_solve_positions))
        .collect::<Result<Vec<_>, String>>()?;

    // ── Sextant verification ─────────────────────────────────────────────
    //
    // outcomes[window_len] was solved at 60° elec — the first reconstructed
    // angle. Compare it against its reconstruction from outcomes[0]: torque
    // must repeat and the flux triples must follow the +60° phase map. A
    // mismatch (broken machine symmetry, e.g. excitation counter-rotating
    // against the winding's spatial phase sequence, or a wrong relabel
    // convention) demotes the run to a full sweep instead of returning
    // tiled garbage.
    let mut sextant_in_effect = sextant_active;
    if sextant_active {
        let window_len = n_positions / 6;
        // Flux is the decisive symmetry discriminator: global integrals sit
        // at mesh-noise level (~5e-4 observed on spade/fine 8p12s) when the
        // symmetry holds, vs O(1) when it doesn't (e.g. a winding/current
        // sequence mismatch). Torque is a local airgap-stress integral and
        // carries a few percent of angle-dependent mesh noise even with the
        // symmetry intact (~5e-2 worst pair observed, identical across
        // contour and Arkkio methods), so it gets a looser default bound.
        let flux_tol = std::env::var("MAGNETO2D_SWEEP_SEXTANT_TOL")
            .ok()
            .and_then(|raw| raw.parse::<f64>().ok())
            .filter(|value| value.is_finite() && *value > 0.0)
            .unwrap_or(0.01);
        let torque_tol = std::env::var("MAGNETO2D_SWEEP_SEXTANT_TORQUE_TOL")
            .ok()
            .and_then(|raw| raw.parse::<f64>().ok())
            .filter(|value| value.is_finite() && *value > 0.0)
            .unwrap_or(0.08);
        let base = &outcomes[0];
        let verify = &outcomes[window_len];

        let torque_scale = outcomes[..=window_len]
            .iter()
            .map(|o| o.loaded_summary.torque_nm.abs())
            .fold(1e-9_f64, f64::max);
        let torque_dev =
            (verify.loaded_summary.torque_nm - base.loaded_summary.torque_nm).abs() / torque_scale;

        let recon_loaded = sextant_phase_map(
            [
                base.loaded_summary.flux_linkage_a_wb,
                base.loaded_summary.flux_linkage_b_wb,
                base.loaded_summary.flux_linkage_c_wb,
            ],
            1,
        );
        let solved_loaded = [
            verify.loaded_summary.flux_linkage_a_wb,
            verify.loaded_summary.flux_linkage_b_wb,
            verify.loaded_summary.flux_linkage_c_wb,
        ];
        let recon_noload = sextant_phase_map(
            [
                base.noload_summary.flux_linkage_a_wb,
                base.noload_summary.flux_linkage_b_wb,
                base.noload_summary.flux_linkage_c_wb,
            ],
            1,
        );
        let solved_noload = [
            verify.noload_summary.flux_linkage_a_wb,
            verify.noload_summary.flux_linkage_b_wb,
            verify.noload_summary.flux_linkage_c_wb,
        ];
        let flux_dev = |recon: &[f64; 3], solved: &[f64; 3]| -> f64 {
            let scale = recon
                .iter()
                .chain(solved.iter())
                .map(|value| value.abs())
                .fold(1e-12_f64, f64::max);
            recon
                .iter()
                .zip(solved.iter())
                .map(|(r, s)| (r - s).abs() / scale)
                .fold(0.0_f64, f64::max)
        };
        let loaded_flux_dev = flux_dev(&recon_loaded, &solved_loaded);
        let noload_flux_dev = if run_main_no_load {
            flux_dev(&recon_noload, &solved_noload)
        } else {
            0.0
        };

        if torque_dev <= torque_tol && loaded_flux_dev <= flux_tol && noload_flux_dev <= flux_tol {
            eprintln!(
                "magneto2d: sextant verification PASSED at 60 elec deg — \
                 torque dev {:.2e} (tol {:.1e}), loaded flux dev {:.2e}, \
                 no-load flux dev {:.2e} (tol {:.1e})",
                torque_dev, torque_tol, loaded_flux_dev, noload_flux_dev, flux_tol,
            );
        } else {
            eprintln!(
                "magneto2d: sextant verification FAILED at 60 elec deg — \
                 torque dev {:.2e} (tol {:.1e}), loaded flux dev {:.2e}, \
                 no-load flux dev {:.2e} (tol {:.1e}). The simulated machine does not \
                 repeat under a 60 elec deg advance with the (a,b,c)->(-b,-c,-a) \
                 relabel — check the winding phase sequence vs the applied current \
                 sequence. Falling back to the full sweep.",
                torque_dev, torque_tol, loaded_flux_dev, noload_flux_dev, flux_tol,
            );
            sextant_in_effect = false;
            let remaining: Vec<PositionOutcome> = (window_len + 1..n_positions)
                .into_par_iter()
                .map(|i| solve_position(i, n_positions))
                .collect::<Result<Vec<_>, String>>()?;
            outcomes.extend(remaining);
        }
    }
    let outcomes = outcomes;
    let sweep_wall_ms = sweep_start.elapsed().as_millis();

    eprintln!(
        "magneto2d: parallel sweep completed {} positions in {} ms wall ({} rayon threads)",
        n_solve_positions,
        sweep_wall_ms,
        rayon::current_num_threads(),
    );

    // ── Sextant reconstruction: expand the 60° window to the full cycle ──
    //
    // Torque and scalar energies repeat with 60° elec period (copied);
    // flux linkages and phase currents follow sextant_phase_map; the slot
    // excitation summary is recomputed exactly for each reconstructed angle
    // (it is a pure function of the excitation, no field solve involved).
    // Element field history is only kept for the solved window — stator
    // core loss needs per-element B over the full cycle, which a 60° window
    // cannot reconstruct (per-element waveforms are 360°-periodic with
    // half-wave symmetry, not 60°-periodic), so core loss is skipped.
    let outcomes: Vec<PositionOutcome> = if sextant_in_effect {
        let window = outcomes;
        let window_len = n_positions / 6;
        (0..n_positions)
            .map(|i| {
                // Positions inside the solved window — including the solved
                // verification position at 60° elec — are passed through.
                if i <= window_len {
                    let src = &window[i];
                    return PositionOutcome {
                        elec_deg: src.elec_deg,
                        loaded_summary: src.loaded_summary.clone(),
                        noload_summary: src.noload_summary.clone(),
                        loaded_fields: src.loaded_fields.clone(),
                        loaded_nonlinear_iters: src.loaded_nonlinear_iters,
                        noload_nonlinear_iters: src.noload_nonlinear_iters,
                    };
                }
                let src = &window[i % window_len];
                let sextant = i / window_len;
                let elec_deg = i as f64 * elec_step;

                let mut loaded_summary = src.loaded_summary.clone();
                let mut noload_summary = src.noload_summary.clone();
                let loaded_psi = sextant_phase_map(
                    [
                        src.loaded_summary.flux_linkage_a_wb,
                        src.loaded_summary.flux_linkage_b_wb,
                        src.loaded_summary.flux_linkage_c_wb,
                    ],
                    sextant,
                );
                loaded_summary.flux_linkage_a_wb = loaded_psi[0];
                loaded_summary.flux_linkage_b_wb = loaded_psi[1];
                loaded_summary.flux_linkage_c_wb = loaded_psi[2];
                let noload_psi = sextant_phase_map(
                    [
                        src.noload_summary.flux_linkage_a_wb,
                        src.noload_summary.flux_linkage_b_wb,
                        src.noload_summary.flux_linkage_c_wb,
                    ],
                    sextant,
                );
                noload_summary.flux_linkage_a_wb = noload_psi[0];
                noload_summary.flux_linkage_b_wb = noload_psi[1];
                noload_summary.flux_linkage_c_wb = noload_psi[2];

                // Exact slot excitation at the reconstructed angle: pure
                // current synthesis on the shared fixed mesh, no solve.
                let mech_rad = elec_deg.to_radians() / pole_pairs as f64;
                let source_current_angle_deg =
                    synced_current_angle_deg(mech_rad, pole_pairs, advance_deg);
                let phase_currents = phase_currents_for_excitation(
                    config,
                    mech_rad,
                    ctx.current_a,
                    source_current_angle_deg,
                );
                let source_phase_currents = source_phase_currents_for_excitation(
                    config,
                    mech_rad,
                    ctx.current_a,
                    source_current_angle_deg,
                );
                let j_z = compute_current_densities_from_phase_currents(
                    &ctx.mesh,
                    &ctx.centroids,
                    &config.winding.winding_type,
                    config.stator.slot_count,
                    config.rotor.pole_count,
                    config.winding.turns_per_coil,
                    config.winding.layers,
                    config.winding.coil_span,
                    source_phase_currents,
                    &ctx.slot_areas,
                );
                let excitation = compute_slot_excitation_summary_from_phase_currents(
                    &ctx.mesh,
                    &ctx.centroids,
                    &config.winding.winding_type,
                    config.stator.slot_count,
                    config.rotor.pole_count,
                    config.winding.turns_per_coil,
                    source_current_angle_deg,
                    phase_currents,
                    &j_z,
                );
                loaded_summary.source_current_angle_deg = excitation.source_current_angle_deg;
                loaded_summary.phase_current_a = excitation.phase_current_a;
                loaded_summary.slot_excitation_contributions =
                    excitation.slot_excitation_contributions;

                PositionOutcome {
                    elec_deg,
                    loaded_summary,
                    noload_summary,
                    loaded_fields: Vec::new(),
                    loaded_nonlinear_iters: src.loaded_nonlinear_iters,
                    noload_nonlinear_iters: src.noload_nonlinear_iters,
                }
            })
            .collect()
    } else {
        outcomes
    };

    let mut positions_elec = Vec::with_capacity(n_positions);
    let mut torques_contour = Vec::with_capacity(n_positions);
    let mut torques_area_mst = Vec::with_capacity(n_positions);
    let mut torques_arkkio = Vec::with_capacity(n_positions);
    let mut torques_weighted_stress = Vec::with_capacity(n_positions);
    let mut loaded_potential_energy_j = Vec::with_capacity(n_positions);
    let mut loaded_coenergy_j = Vec::with_capacity(n_positions);
    let mut loaded_field_energy_j = Vec::with_capacity(n_positions);
    let mut loaded_field_energy_by_region_j = Vec::with_capacity(n_positions);
    let mut loaded_field_energy_magnet_detail_j = Vec::with_capacity(n_positions);
    let mut loaded_current_source_work_j = Vec::with_capacity(n_positions);
    let mut loaded_pm_source_work_j = Vec::with_capacity(n_positions);
    let mut loaded_pm_source_work_magnet_detail_j = Vec::with_capacity(n_positions);
    let mut loaded_pm_self_energy_j = Vec::with_capacity(n_positions);
    let mut loaded_potential_with_pm_self_j = Vec::with_capacity(n_positions);
    let mut loaded_coenergy_by_region_j = Vec::with_capacity(n_positions);
    let mut loaded_coenergy_magnet_detail_j = Vec::with_capacity(n_positions);
    let mut saw_weighted_stress = false;
    let mut missing_weighted_stress = false;
    let mut loaded_psi_a = Vec::with_capacity(n_positions);
    let mut loaded_psi_b = Vec::with_capacity(n_positions);
    let mut loaded_psi_c = Vec::with_capacity(n_positions);
    let mut noload_psi_a = Vec::with_capacity(n_positions);
    let mut noload_psi_b = Vec::with_capacity(n_positions);
    let mut noload_psi_c = Vec::with_capacity(n_positions);
    let mut loaded_nonlinear_iterations = Vec::with_capacity(n_positions);
    let mut no_load_nonlinear_iterations = Vec::with_capacity(n_positions);
    let mut loaded_field_history = Vec::with_capacity(n_positions);
    let mut slot_excitation_frames = Vec::with_capacity(n_positions);
    let mut phase_current_a_a = Vec::with_capacity(n_positions);
    let mut phase_current_b_a = Vec::with_capacity(n_positions);
    let mut phase_current_c_a = Vec::with_capacity(n_positions);

    // Per-position log lines are emitted live from inside the par_iter above
    // (in completion order, not index order) so the backend progress parser
    // can tick the UI bar smoothly. This loop just stitches results into the
    // downstream Vecs in index order.
    for outcome in outcomes.into_iter() {
        positions_elec.push(outcome.elec_deg);
        torques_contour.push(outcome.loaded_summary.torque_nm);
        torques_area_mst.push(outcome.loaded_summary.torque_area_mst_nm);
        torques_arkkio.push(outcome.loaded_summary.torque_arkkio_nm);
        loaded_potential_energy_j.push(outcome.loaded_summary.energy_functional.potential_energy_j);
        loaded_coenergy_j.push(outcome.loaded_summary.energy_functional.coenergy_j);
        loaded_field_energy_j.push(outcome.loaded_summary.energy_functional.field_energy_j);
        loaded_field_energy_by_region_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .field_energy_by_region_j
                .clone(),
        );
        loaded_field_energy_magnet_detail_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .field_energy_magnet_detail_j
                .clone(),
        );
        loaded_current_source_work_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .current_source_work_j,
        );
        loaded_pm_source_work_j.push(outcome.loaded_summary.energy_functional.pm_source_work_j);
        loaded_pm_source_work_magnet_detail_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .pm_source_work_magnet_detail_j
                .clone(),
        );
        loaded_pm_self_energy_j.push(outcome.loaded_summary.energy_functional.pm_self_energy_j);
        loaded_potential_with_pm_self_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .potential_energy_with_pm_self_j,
        );
        loaded_coenergy_by_region_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .coenergy_by_region_j
                .clone(),
        );
        loaded_coenergy_magnet_detail_j.push(
            outcome
                .loaded_summary
                .energy_functional
                .coenergy_magnet_detail_j
                .clone(),
        );
        if let Some(torque_weighted_stress_nm) = outcome.loaded_summary.torque_weighted_stress_nm {
            saw_weighted_stress = true;
            torques_weighted_stress.push(torque_weighted_stress_nm);
        } else {
            missing_weighted_stress = true;
        }
        loaded_psi_a.push(outcome.loaded_summary.flux_linkage_a_wb);
        loaded_psi_b.push(outcome.loaded_summary.flux_linkage_b_wb);
        loaded_psi_c.push(outcome.loaded_summary.flux_linkage_c_wb);
        noload_psi_a.push(outcome.noload_summary.flux_linkage_a_wb);
        noload_psi_b.push(outcome.noload_summary.flux_linkage_b_wb);
        noload_psi_c.push(outcome.noload_summary.flux_linkage_c_wb);
        slot_excitation_frames.push(SlotExcitationFrame {
            angle_deg: outcome.elec_deg,
            source_current_angle_deg: outcome.loaded_summary.source_current_angle_deg,
            phase_current_a: outcome.loaded_summary.phase_current_a,
            contributions: outcome.loaded_summary.slot_excitation_contributions.clone(),
        });
        phase_current_a_a.push(outcome.loaded_summary.phase_current_a[0]);
        phase_current_b_a.push(outcome.loaded_summary.phase_current_a[1]);
        phase_current_c_a.push(outcome.loaded_summary.phase_current_a[2]);
        loaded_field_history.push(outcome.loaded_fields);
        loaded_nonlinear_iterations.push(outcome.loaded_nonlinear_iters);
        no_load_nonlinear_iterations.push(outcome.noload_nonlinear_iters);
    }

    // Compute back-EMF from the flux-linkage waveform sampled over electrical angle.
    // The reporting path uses mechanical-speed scaling to match the current FEMM
    // baseline convention, while the power-balance torque path uses the physical
    // electrical-speed derivative.
    let omega_mech = 2.0 * PI * ctx.rated_speed_rpm as f64 / 60.0;
    let omega_elec = omega_mech * pole_pairs as f64;
    let d_theta_elec = elec_step.to_radians();
    let d_theta_mech = d_theta_elec / pole_pairs as f64;
    let full_cycle_waveform = (sweep_span_deg - 360.0).abs() <= 1e-9 && n_positions >= 3;
    let torque_energy_fd_nm: Vec<f64> = finite_difference_waveform(
        &loaded_potential_energy_j,
        d_theta_mech,
        full_cycle_waveform,
    )
    .into_iter()
    .map(|d_energy_dtheta| -d_energy_dtheta)
    .collect();
    let torque_coenergy_fd_nm =
        finite_difference_waveform(&loaded_coenergy_j, d_theta_mech, full_cycle_waveform);
    let avg_torque_energy_fd_nm = waveform_mean(&torque_energy_fd_nm);
    let avg_torque_coenergy_fd_nm = waveform_mean(&torque_coenergy_fd_nm);

    let back_emf_metrics = assemble_back_emf_sweep_metrics(
        &loaded_psi_a,
        &loaded_psi_b,
        &loaded_psi_c,
        &noload_psi_a,
        &noload_psi_b,
        &noload_psi_c,
        d_theta_elec,
        omega_mech,
        omega_elec,
        full_cycle_waveform,
        run_thd,
    );

    // Power-balance torque: T = Σ(e_phase × i_phase) / ω_mech
    // Phase currents synchronized with rotor at each position.
    let _torques_pb: Vec<f64> = (0..n_positions)
        .map(|i| {
            let current_rad =
                applied_current_angle_deg(positions_elec[i], advance_deg).to_radians();
            let i_a = ctx.current_a * current_rad.sin();
            let i_b = ctx.current_a * (current_rad - 2.0 * PI / 3.0).sin();
            let i_c = ctx.current_a * (current_rad - 4.0 * PI / 3.0).sin();

            let power = back_emf_metrics.loaded_power_balance_a_v[i] * i_a
                + back_emf_metrics.loaded_power_balance_b_v[i] * i_b
                + back_emf_metrics.loaded_power_balance_c_v[i] * i_c;
            if omega_mech.abs() > 1e-6 {
                -power / omega_mech
            } else {
                0.0
            }
        })
        .collect();

    let torque_centering_span_deg =
        torque_metric_centering_span_deg(&positions_elec, sweep_span_deg);
    let torque_metrics = assemble_torque_sweep_metrics(
        &torques_contour,
        &torques_area_mst,
        &torques_arkkio,
        torques_weighted_stress,
        saw_weighted_stress,
        missing_weighted_stress,
        n_positions,
        ctx.current_a,
        torque_centering_span_deg,
        config.stator.slot_count,
        config.rotor.pole_count,
    );
    let (
        cogging_torque_nm,
        cogging_torque_method_label,
        cogging_positions_elec,
        cogging_waveform_nm,
        cogging_contour_waveform_nm,
        cogging_area_mst_waveform_nm,
        cogging_arkkio_waveform_nm,
        cogging_weighted_stress_waveform_nm,
        cogging_weighted_stress_centered_waveform_nm,
        cogging_contour_inner_waveform_nm,
        cogging_contour_outer_waveform_nm,
    ) = if run_cogging {
        let cogging_period_elec =
            cogging_period_electrical_deg(config.stator.slot_count, config.rotor.pole_count);
        let cogging_step_deg = std::env::var("MAGNETO2D_COGGING_STEP_DEG")
            .ok()
            .and_then(|raw| raw.parse::<f64>().ok())
            .filter(|value| value.is_finite() && *value > 0.0)
            .unwrap_or(1.0);
        let cogging_positions = (cogging_period_elec / cogging_step_deg).ceil() as usize + 1;
        let requested_cogging_remesh = uses_cogging_remesh_per_step(config);
        let cogging_remesh = requested_cogging_remesh && !imported_solve_mesh;
        if requested_cogging_remesh && imported_solve_mesh {
            eprintln!(
                "magneto2d: imported mesh input is fixed; ignoring cogging remesh_per_step request — \
                 fixed-mesh magnet re-tagging is only valid on internally meshed structured/spade grids; \
                 drive imported-mesh (Gmsh/FEMM) cogging sweeps per angle from the caller"
            );
        }
        let cogging_rotation_model = if cogging_remesh {
            "remesh_per_step"
        } else {
            "fixed_mesh"
        };
        let production_torque_method = cogging_torque_method(config);
        // Cogging is dominated by magnet/slot edge alignment. The fixed-mesh
        // rotation path re-tags magnet regions on a stationary grid, which
        // under-predicts the 50 mm 4p/12s k_phys amplitude by ~13%; remeshing
        // closes that case to ~5%. The 100 mm fixture over-predicts when all
        // cogging positions remesh, so remesh is defaulted only for the small
        // OD class unless the fixture explicitly opts into remesh_per_step.
        eprintln!(
            "magneto2d: cogging sweep enabled over {:.1} elec deg with {} positions at nominal {:.3}° step (rotor_rotation_model={}, torque_method={})",
            cogging_period_elec, cogging_positions, cogging_step_deg, cogging_rotation_model, production_torque_method.label(),
        );

        // Parallel cogging sweep — same safety argument as the
        // main torque sweep: each position is an independent no-load solve.
        // Progress ticks emit in completion order via an atomic counter so
        // the backend parser picks them up live.
        let cogging_completed = AtomicUsize::new(0);

        // Cross-position warm-start seed for cogging (mirrors the loaded sweep
        // path above). Cogging steps are typically 1° elec apart, so the
        // no-load A_z field changes very little between positions and a single
        // shared seed lets every parallel worker skip most of its Picard cost.
        // Skipped under remesh_per_step for the same mesh-projection reason.
        let cogging_cross_position_seed: Option<(NonlinearWarmStart, Vec<f64>)> =
            if !cogging_remesh && cogging_positions > 1 {
                let seed_progress = AngleProgressContext {
                    parent_stage: "magneto2d_cogging",
                    solve_kind: "warm_start_seed",
                    position_index: 0,
                    total_positions: cogging_positions,
                    completed_positions: &cogging_completed,
                    elec_deg: 0.0,
                };
                let seed_started = Instant::now();
                let (_seed_fields, _seed_summary, seed_az, _seed_diag, seed_warm) = solve_at_angle(
                    &ctx,
                    config,
                    0.0,
                    0.0,
                    0.0,
                    false,
                    None,
                    None,
                    Some(&seed_progress),
                )?;
                eprintln!(
                    "magneto2d: cogging warm-start seed ready ({} A_z DOFs, {} ms)",
                    seed_az.len(),
                    seed_started.elapsed().as_millis(),
                );
                Some((seed_warm, seed_az))
            } else {
                None
            };
        let cogging_seed_ref = cogging_cross_position_seed.as_ref();

        let cogging_outcomes: Vec<CoggingPositionOutcome> = (0..cogging_positions)
            .into_par_iter()
            .map(|i| {
                let elec_deg = if cogging_positions <= 1 {
                    0.0
                } else {
                    i as f64 * (cogging_period_elec / (cogging_positions - 1) as f64)
                };
                let mech_rad = elec_deg.to_radians() / pole_pairs as f64;
                let step_ctx_storage;
                let step_ctx: &SolveContext = if cogging_remesh {
                    step_ctx_storage = remesh_ctx_for_angle(&ctx, config, mech_rad)?;
                    &step_ctx_storage
                } else {
                    &ctx
                };
                let cogging_progress = AngleProgressContext {
                    parent_stage: "magneto2d_cogging",
                    solve_kind: "cogging",
                    position_index: i + 1,
                    total_positions: cogging_positions,
                    completed_positions: &cogging_completed,
                    elec_deg,
                };
                let cogging_seed_material = cogging_seed_ref.map(|(warm, _)| warm);
                let cogging_seed_az = cogging_seed_ref.map(|(_, az)| az.as_slice());
                let (_fields, summary, _az, _diagnostics, _warm_start) = solve_at_angle(
                    step_ctx,
                    config,
                    mech_rad,
                    0.0,
                    0.0,
                    cogging_remesh,
                    cogging_seed_material,
                    cogging_seed_az,
                    Some(&cogging_progress),
                )?;
                let done = cogging_completed.fetch_add(1, Ordering::Relaxed) + 1;
                eprintln!(
                    "  cogging [{}/{}] elec={:.2}° arkkio={:.6}Nm contour={:.6}Nm",
                    done, cogging_positions, elec_deg, summary.torque_arkkio_nm, summary.torque_nm,
                );
                Ok::<CoggingPositionOutcome, String>(CoggingPositionOutcome {
                    elec_deg,
                    contour_nm: summary.torque_nm,
                    area_mst_nm: summary.torque_area_mst_nm,
                    arkkio_nm: summary.torque_arkkio_nm,
                    weighted_stress_nm: summary.torque_weighted_stress_nm,
                    contour_inner_nm: summary.torque_contour_inner_nm,
                    contour_outer_nm: summary.torque_contour_outer_nm,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;

        let mut cogging_positions_elec = Vec::with_capacity(cogging_positions);
        let mut cogging_torques = Vec::with_capacity(cogging_positions);
        let mut cogging_contour_torques = Vec::with_capacity(cogging_positions);
        let mut cogging_area_mst_torques = Vec::with_capacity(cogging_positions);
        let mut cogging_arkkio_torques = Vec::with_capacity(cogging_positions);
        let mut cogging_weighted_stress_torques = Vec::with_capacity(cogging_positions);
        let mut missing_cogging_weighted_stress = false;
        let mut cogging_contour_inner_torques = Vec::with_capacity(cogging_positions);
        let mut cogging_contour_outer_torques = Vec::with_capacity(cogging_positions);
        for outcome in cogging_outcomes {
            cogging_positions_elec.push(outcome.elec_deg);
            cogging_torques.push(production_torque_method.select(&outcome));
            cogging_contour_torques.push(outcome.contour_nm);
            cogging_area_mst_torques.push(outcome.area_mst_nm);
            cogging_arkkio_torques.push(outcome.arkkio_nm);
            if let Some(weighted_stress_nm) = outcome.weighted_stress_nm {
                cogging_weighted_stress_torques.push(weighted_stress_nm);
            } else {
                missing_cogging_weighted_stress = true;
            }
            cogging_contour_inner_torques.push(outcome.contour_inner_nm);
            cogging_contour_outer_torques.push(outcome.contour_outer_nm);
        }

        let cogging_weighted_stress_waveform = if !missing_cogging_weighted_stress
            && cogging_weighted_stress_torques.len() == cogging_positions
        {
            Some(cogging_weighted_stress_torques)
        } else {
            None
        };
        let cogging_weighted_stress_centered_waveform = cogging_weighted_stress_waveform
            .as_ref()
            .and_then(|values| centered_endpoint_period_waveform(values));
        if production_torque_method == CoggingTorqueMethod::WeightedStress {
            if let Some(values) = cogging_weighted_stress_waveform.as_ref() {
                cogging_torques = values.clone();
            } else {
                cogging_torques = cogging_arkkio_torques.clone();
            }
        } else if production_torque_method == CoggingTorqueMethod::WeightedStressCentered {
            if let Some(values) = cogging_weighted_stress_centered_waveform.as_ref() {
                cogging_torques = values.clone();
            } else {
                cogging_torques = cogging_arkkio_torques.clone();
            }
        }

        let peak = cogging_torques
            .iter()
            .copied()
            .fold(f64::NEG_INFINITY, f64::max);
        let trough = cogging_torques
            .iter()
            .copied()
            .fold(f64::INFINITY, f64::min);

        (
            Some(peak - trough),
            Some(production_torque_method.label().to_string()),
            Some(cogging_positions_elec),
            Some(cogging_torques),
            Some(cogging_contour_torques),
            Some(cogging_area_mst_torques),
            Some(cogging_arkkio_torques),
            cogging_weighted_stress_waveform,
            cogging_weighted_stress_centered_waveform,
            Some(cogging_contour_inner_torques),
            Some(cogging_contour_outer_torques),
        )
    } else {
        (
            None, None, None, None, None, None, None, None, None, None, None,
        )
    };
    // Grade-specific loss coefficients are deliberately absent from the
    // public launch snapshot. A zero-valued summary preserves the schema, but
    // must not be interpreted as a prediction; see MATERIALS.md.
    eprintln!("magneto2d: core-loss prediction unavailable in this build");
    let core_loss = CoreLossSummary::default();

    let total_ms = total_start.elapsed().as_millis() as u64;
    eprintln!(
        "magneto2d: sweep done in {total_ms}ms — torque(PB)={:.3}Nm, torque(MST)={:.3}Nm, torque(Arkkio)={:.3}Nm, peak_emf={:.2}V",
        torque_metrics.avg_torque_nm,
        torque_metrics.avg_area_mst_nm,
        torque_metrics.avg_arkkio_nm,
        back_emf_metrics.peak_v,
    );

    Ok(SweepReport {
        config_summary: ctx.config_summary,
        operating_point: ctx.operating_point,
        mesh_info: ctx.mesh.info.clone(),
        sweep: SweepData {
            rotor_positions_elec_deg: positions_elec,
            phase_current_a_a: (config
                .solve_params
                .as_ref()
                .map(|sp| sp.excitation_mode_label() == "ideal_six_step_120")
                .unwrap_or(false))
            .then_some(phase_current_a_a),
            phase_current_b_a: (config
                .solve_params
                .as_ref()
                .map(|sp| sp.excitation_mode_label() == "ideal_six_step_120")
                .unwrap_or(false))
            .then_some(phase_current_b_a),
            phase_current_c_a: (config
                .solve_params
                .as_ref()
                .map(|sp| sp.excitation_mode_label() == "ideal_six_step_120")
                .unwrap_or(false))
            .then_some(phase_current_c_a),
            torque_nm: torques_contour,
            torque_contour_centered_nm: torque_metrics.contour_centered_nm,
            avg_torque_contour_centered_nm: torque_metrics.avg_contour_centered_nm,
            torque_mst_nm: torques_area_mst,
            torque_arkkio_nm: torques_arkkio,
            avg_torque_arkkio_nm: torque_metrics.avg_arkkio_nm,
            energy_potential_j: loaded_potential_energy_j,
            energy_coenergy_j: loaded_coenergy_j,
            energy_field_j: loaded_field_energy_j,
            energy_field_by_region_j: loaded_field_energy_by_region_j,
            energy_field_magnet_detail_j: loaded_field_energy_magnet_detail_j,
            energy_current_source_work_j: loaded_current_source_work_j,
            energy_pm_source_work_j: loaded_pm_source_work_j,
            energy_pm_source_work_magnet_detail_j: loaded_pm_source_work_magnet_detail_j,
            energy_pm_self_j: loaded_pm_self_energy_j,
            energy_potential_with_pm_self_j: loaded_potential_with_pm_self_j,
            energy_coenergy_by_region_j: loaded_coenergy_by_region_j,
            energy_coenergy_magnet_detail_j: loaded_coenergy_magnet_detail_j,
            torque_energy_fd_nm,
            torque_coenergy_fd_nm,
            avg_torque_energy_fd_nm,
            avg_torque_coenergy_fd_nm,
            torque_weighted_stress_nm: torque_metrics.weighted_stress_nm,
            avg_torque_weighted_stress_nm: torque_metrics.avg_weighted_stress_nm,
            torque_weighted_stress_centered_nm: torque_metrics.weighted_stress_centered_nm,
            avg_torque_weighted_stress_centered_nm: torque_metrics.avg_weighted_stress_centered_nm,
            flux_linkage_a_wb: noload_psi_a.clone(),
            flux_linkage_b_wb: noload_psi_b.clone(),
            flux_linkage_c_wb: noload_psi_c.clone(),
            back_emf_a_v: back_emf_metrics.no_load_a_v.clone(),
            back_emf_b_v: back_emf_metrics.no_load_b_v.clone(),
            back_emf_c_v: back_emf_metrics.no_load_c_v.clone(),
            avg_torque_nm: torque_metrics.avg_torque_nm,
            avg_torque_mst_nm: torque_metrics.avg_area_mst_nm,
            torque_crosscheck_delta_nm: torque_metrics.crosscheck_delta_nm,
            torque_crosscheck_delta_pct: torque_metrics.crosscheck_delta_pct,
            torque_ripple_pct: torque_metrics.ripple_pct,
            back_emf_peak_v: back_emf_metrics.peak_v,
            back_emf_fundamental_v: back_emf_metrics.fundamental_v,
            back_emf_peak_physical_v: back_emf_metrics.peak_physical_v,
            back_emf_fundamental_peak_physical_v: back_emf_metrics.fundamental_peak_physical_v,
            back_emf_fundamental_rms_v: back_emf_metrics.fundamental_rms_v,
            back_emf_thd_pct: back_emf_metrics.thd_pct,
            cogging_torque_nm,
            cogging_torque_method: cogging_torque_method_label,
            cogging_rotor_positions_elec_deg: cogging_positions_elec,
            cogging_torque_waveform_nm: cogging_waveform_nm,
            cogging_torque_contour_waveform_nm: cogging_contour_waveform_nm,
            cogging_torque_area_mst_waveform_nm: cogging_area_mst_waveform_nm,
            cogging_torque_arkkio_waveform_nm: cogging_arkkio_waveform_nm,
            cogging_torque_weighted_stress_waveform_nm: cogging_weighted_stress_waveform_nm,
            cogging_torque_weighted_stress_centered_waveform_nm:
                cogging_weighted_stress_centered_waveform_nm,
            cogging_torque_contour_inner_waveform_nm: cogging_contour_inner_waveform_nm,
            cogging_torque_contour_outer_waveform_nm: cogging_contour_outer_waveform_nm,
            total_time_ms: total_ms,
            rated_speed_rpm: ctx.rated_speed_rpm,
            loaded_flux_linkage_a_wb: loaded_psi_a,
            loaded_flux_linkage_b_wb: loaded_psi_b,
            loaded_flux_linkage_c_wb: loaded_psi_c,
            loaded_back_emf_a_v: back_emf_metrics.loaded_a_v,
            loaded_back_emf_b_v: back_emf_metrics.loaded_b_v,
            loaded_back_emf_c_v: back_emf_metrics.loaded_c_v,
            no_load_flux_linkage_a_wb: noload_psi_a,
            no_load_flux_linkage_b_wb: noload_psi_b,
            no_load_flux_linkage_c_wb: noload_psi_c,
            no_load_back_emf_a_v: back_emf_metrics.no_load_a_v,
            no_load_back_emf_b_v: back_emf_metrics.no_load_b_v,
            no_load_back_emf_c_v: back_emf_metrics.no_load_c_v,
            no_load_back_emf_a_physical_v: back_emf_metrics.no_load_a_physical_v,
            no_load_back_emf_b_physical_v: back_emf_metrics.no_load_b_physical_v,
            no_load_back_emf_c_physical_v: back_emf_metrics.no_load_c_physical_v,
            slot_excitation_frames,
            loaded_nonlinear_iterations,
            no_load_nonlinear_iterations,
            core_loss_w: core_loss.core_loss_w,
            hysteresis_loss_w: core_loss.hysteresis_loss_w,
            eddy_current_loss_w: core_loss.eddy_current_loss_w,
            stator_core_mass_kg: core_loss.stator_core_mass_kg,
            core_loss_density_w_per_m3: None,
        },
    })
}

#[cfg(test)]
mod tests;
