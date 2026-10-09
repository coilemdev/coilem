//! Motor-independent 2D magnetostatic finite-element contracts and solver.
//!
//! The core accepts a solve-ready P1 triangular mesh in metres. Geometry
//! creation, motor region classification, process environment, filesystem
//! diagnostics, torque, flux linkage, and report envelopes belong to adapters.

use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::assembly::triangle_gradients;
pub use crate::sparse::PcgProfile;
use crate::sparse::{
    pcg_solve_with_guess_options_profiled, CsrMatrix, DirectCholeskyCache, DirectCholeskyError,
    ElementCsrAssemblyPattern, PcgExecution, PcgOptions, PcgPreconditionerKind,
};

const MU_0: f64 = 4.0 * std::f64::consts::PI * 1.0e-7;
const FORMULATION_VERSION: u32 = 1;

/// Cartesian magnetic flux-density components for one triangle element.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ElementField {
    pub bx: f64,
    pub by: f64,
    pub b_mag: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FemMesh {
    /// Cartesian node coordinates, normalized to metres by the adapter.
    pub nodes_m: Vec<[f64; 2]>,
    /// Counter-clockwise or clockwise P1 triangle connectivity.
    pub triangles: Vec<[usize; 3]>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum MaterialModel {
    Linear { mu_r: f64 },
    Nonlinear { bh_curve: BhCurve },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BhCurve {
    pub points: Vec<BhPoint>,
    #[serde(default = "default_mu_r_min")]
    pub mu_r_min: f64,
    #[serde(default = "default_mu_r_max")]
    pub mu_r_max: f64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BhPoint {
    pub b_t: f64,
    pub h_a_per_m: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ElementPhysics {
    pub material_id: usize,
    #[serde(default)]
    pub current_density_z_a_per_m2: f64,
    #[serde(default)]
    pub remanence_t: [f64; 2],
    #[serde(default = "default_pm_source_scale")]
    pub pm_source_scale: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BoundarySet {
    pub dirichlet_az_zero_nodes: Vec<usize>,
    #[serde(default)]
    pub paired_nodes: Vec<PairedBoundary>,
    #[serde(default = "default_periodic_penalty")]
    pub periodic_penalty: f64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PairedBoundary {
    pub nodes: [usize; 2],
    pub kind: PairedBoundaryKind,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PairedBoundaryKind {
    Periodic,
    AntiPeriodic,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MagnetostaticProblem {
    pub mesh: FemMesh,
    pub materials: Vec<MaterialModel>,
    pub elements: Vec<ElementPhysics>,
    pub boundaries: BoundarySet,
    #[serde(default)]
    pub options: SolveOptions,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub warm_start: Option<FieldWarmStart>,
}

pub const MAGNETOSTATIC_PROBLEM_KIND: &str = "magnetostatic_problem";
pub const MAGNETOSTATIC_PROBLEM_VERSION: &str = "1.0";

/// Versioned JSON boundary for generic field solves. Unlike [`FemMesh`],
/// coordinates here are expressed in the declared `units.length`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FieldProblemDocument {
    pub kind: String,
    pub version: String,
    pub units: FieldUnits,
    pub mesh: FieldMeshDocument,
    pub materials: Vec<MaterialModel>,
    pub elements: Vec<ElementPhysics>,
    pub boundaries: BoundarySet,
    #[serde(default)]
    pub options: SolveOptions,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub warm_start: Option<FieldWarmStart>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FieldUnits {
    pub length: LengthUnit,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LengthUnit {
    M,
    Mm,
    Cm,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FieldMeshDocument {
    pub nodes: Vec<[f64; 2]>,
    pub triangles: Vec<[usize; 3]>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct FieldSolutionReport {
    pub problem_kind: String,
    pub problem_version: String,
    pub normalized_length_unit: String,
    pub solution: FieldSolution,
}

impl FieldProblemDocument {
    pub fn into_problem(self) -> Result<MagnetostaticProblem, String> {
        if self.kind != MAGNETOSTATIC_PROBLEM_KIND {
            return Err(format!(
                "field document kind must be '{MAGNETOSTATIC_PROBLEM_KIND}', got '{}'",
                self.kind
            ));
        }
        if self.version != MAGNETOSTATIC_PROBLEM_VERSION {
            return Err(format!(
                "unsupported magnetostatic_problem version '{}'; expected {MAGNETOSTATIC_PROBLEM_VERSION}",
                self.version
            ));
        }
        let length_scale = match self.units.length {
            LengthUnit::M => 1.0,
            LengthUnit::Mm => 1.0e-3,
            LengthUnit::Cm => 1.0e-2,
        };
        let problem = MagnetostaticProblem {
            mesh: FemMesh {
                nodes_m: self
                    .mesh
                    .nodes
                    .into_iter()
                    .map(|node| [node[0] * length_scale, node[1] * length_scale])
                    .collect(),
                triangles: self.mesh.triangles,
            },
            materials: self.materials,
            elements: self.elements,
            boundaries: self.boundaries,
            options: self.options,
            warm_start: self.warm_start,
        };
        problem.validate()?;
        Ok(problem)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FieldWarmStart {
    #[serde(default)]
    pub az_nodal: Vec<f64>,
    #[serde(default)]
    pub mu_r_by_element: Vec<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SolveOptions {
    #[serde(default)]
    pub linear: LinearSolveOptions,
    #[serde(default)]
    pub nonlinear: NonlinearSolveOptions,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct LinearSolveOptions {
    #[serde(default)]
    pub solver: LinearSolver,
    #[serde(default)]
    pub pcg_preconditioner: PcgPreconditioner,
    #[serde(default)]
    pub pcg_parallel: bool,
    #[serde(default = "default_pcg_residual_check_interval")]
    pub pcg_residual_check_interval: usize,
    #[serde(default = "default_linear_tolerance")]
    pub tolerance: f64,
    #[serde(default = "default_linear_max_iterations")]
    pub max_iterations: usize,
}

impl Default for LinearSolveOptions {
    fn default() -> Self {
        Self {
            solver: LinearSolver::Direct,
            pcg_preconditioner: PcgPreconditioner::IncompleteCholesky,
            pcg_parallel: false,
            pcg_residual_check_interval: default_pcg_residual_check_interval(),
            tolerance: default_linear_tolerance(),
            max_iterations: default_linear_max_iterations(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LinearSolver {
    #[default]
    Direct,
    Pcg,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PcgPreconditioner {
    #[default]
    IncompleteCholesky,
    Jacobi,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct NonlinearSolveOptions {
    #[serde(default)]
    pub algorithm: NonlinearAlgorithm,
    #[serde(default = "default_nonlinear_max_iterations")]
    pub max_iterations: usize,
    #[serde(default = "default_nonlinear_tolerance")]
    pub tolerance: f64,
    #[serde(default = "default_picard_relaxation")]
    pub relaxation: f64,
    #[serde(default = "default_mu_step_cap")]
    pub mu_r_step_cap: f64,
    #[serde(default = "default_newton_initial_damping")]
    pub newton_initial_damping: f64,
    #[serde(default = "default_newton_min_damping")]
    pub newton_min_damping: f64,
    #[serde(default = "default_newton_line_search_shrink")]
    pub newton_line_search_shrink: f64,
    #[serde(default = "default_newton_line_search_accept_ratio")]
    pub newton_line_search_accept_ratio: f64,
    #[serde(default = "default_newton_fallback_to_picard")]
    pub newton_fallback_to_picard: bool,
}

impl Default for NonlinearSolveOptions {
    fn default() -> Self {
        Self {
            algorithm: NonlinearAlgorithm::Picard,
            max_iterations: default_nonlinear_max_iterations(),
            tolerance: default_nonlinear_tolerance(),
            relaxation: default_picard_relaxation(),
            mu_r_step_cap: default_mu_step_cap(),
            newton_initial_damping: default_newton_initial_damping(),
            newton_min_damping: default_newton_min_damping(),
            newton_line_search_shrink: default_newton_line_search_shrink(),
            newton_line_search_accept_ratio: default_newton_line_search_accept_ratio(),
            newton_fallback_to_picard: default_newton_fallback_to_picard(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NonlinearAlgorithm {
    #[default]
    Picard,
    Newton,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct FieldSolution {
    pub az_nodal: Vec<f64>,
    pub element_fields: Vec<ElementField>,
    pub final_material_state: Vec<ElementMaterialState>,
    pub convergence: ConvergenceReport,
    pub timings: SolveTimings,
    pub profile: FieldSolveProfile,
    pub energy_per_unit_depth: FieldEnergyPerUnitDepth,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq)]
pub struct ElementMaterialState {
    pub material_id: usize,
    pub mu_r: f64,
    pub reluctivity_m_per_h: f64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ConvergenceReport {
    pub converged: bool,
    pub nonlinear: bool,
    pub nonlinear_algorithm: String,
    pub nonlinear_iterations: usize,
    pub nonlinear_residual_history: Vec<f64>,
    pub linear_solver: String,
}

#[derive(Debug, Clone, Copy, Default, Serialize, PartialEq, Eq)]
pub struct SolveTimings {
    pub total_ms: u64,
    pub preparation_ms: u64,
    pub assembly_ms: u64,
    pub linear_solve_ms: u64,
    pub field_recovery_ms: u64,
    pub material_update_ms: u64,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct FieldSolveProfile {
    pub csr_pattern_builds: u64,
    pub direct_symbolic_builds: u64,
    pub direct_numeric_factorizations: u64,
    pub direct_cache_hits: u64,
    pub direct_pattern_mismatches: u64,
    pub direct_pcg_fallbacks: u64,
    pub direct_successful_solves: u64,
    pub pcg: PcgProfile,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq)]
pub struct FieldEnergyPerUnitDepth {
    pub magnetic_field_j_per_m: f64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum SolveProgressEvent {
    Prepared {
        nodes: usize,
        triangles: usize,
    },
    NonlinearIteration {
        iteration: usize,
        max_iterations: usize,
        residual: f64,
        threshold: f64,
        worst_element: Option<usize>,
    },
    Complete {
        nonlinear_iterations: usize,
    },
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct NonlinearDiagnosticEvent {
    pub iteration: usize,
    pub element_id: usize,
    pub material_id: usize,
    pub centroid_m: [f64; 2],
    pub b_t: [f64; 2],
    pub b_mag_t: f64,
    pub previous_mu_r: f64,
    pub target_mu_r: f64,
    pub relaxed_mu_r: f64,
    pub residual: f64,
}

pub trait ProgressSink: Sync {
    fn on_event(&self, event: SolveProgressEvent);
}

pub trait DiagnosticsSink: Sync {
    fn on_nonlinear_diagnostic(&self, event: NonlinearDiagnosticEvent);
}

struct NoProgress;
impl ProgressSink for NoProgress {
    fn on_event(&self, _event: SolveProgressEvent) {}
}

struct NoDiagnostics;
impl DiagnosticsSink for NoDiagnostics {
    fn on_nonlinear_diagnostic(&self, _event: NonlinearDiagnosticEvent) {}
}

/// Non-cloneable owner of the topology-specific assembly and direct-solver
/// cache. One instance is created per mesh and reused across every nonlinear
/// refill.
pub struct PreparedFieldSystem {
    csr_assembly_pattern: ElementCsrAssemblyPattern,
    boundary_slots: Vec<(usize, f64)>,
    dirichlet_nodes: Vec<usize>,
    direct_cholesky: DirectCholeskyCache,
    formulation_version: u32,
}

#[derive(Clone, Copy)]
struct ElementState {
    mu_r: f64,
    nu: f64,
}

impl ElementState {
    fn new(mu_r: f64) -> Self {
        let mu_r = mu_r.max(1.0);
        Self {
            mu_r,
            nu: 1.0 / (MU_0 * mu_r),
        }
    }

    fn set_mu_r(&mut self, mu_r: f64) {
        *self = Self::new(mu_r);
    }
}

pub fn solve(problem: &MagnetostaticProblem) -> Result<FieldSolution, String> {
    solve_with_sinks(problem, &NoProgress, &NoDiagnostics)
}

pub fn solve_with_sinks(
    problem: &MagnetostaticProblem,
    progress: &dyn ProgressSink,
    diagnostics: &dyn DiagnosticsSink,
) -> Result<FieldSolution, String> {
    let total_start = Instant::now();
    let warnings = problem.validate()?;
    let preparation_start = Instant::now();
    let prepared = PreparedFieldSystem::new(&problem.mesh, &problem.boundaries)?;
    let preparation_ms = elapsed_ms(preparation_start);
    progress.on_event(SolveProgressEvent::Prepared {
        nodes: problem.mesh.nodes_m.len(),
        triangles: problem.mesh.triangles.len(),
    });

    let mut states = initial_element_states(problem);
    if let Some(warm_start) = problem.warm_start.as_ref() {
        if warm_start.mu_r_by_element.len() == states.len() {
            for (index, state) in states.iter_mut().enumerate() {
                if matches!(
                    problem.materials[problem.elements[index].material_id],
                    MaterialModel::Nonlinear { .. }
                ) && warm_start.mu_r_by_element[index].is_finite()
                {
                    state.set_mu_r(warm_start.mu_r_by_element[index]);
                }
            }
        }
    }
    let az_guess = problem
        .warm_start
        .as_ref()
        .map(|warm| warm.az_nodal.as_slice())
        .filter(|guess| guess.len() == problem.mesh.nodes_m.len())
        .map(<[f64]>::to_vec);

    let nonlinear = problem.elements.iter().any(|element| {
        matches!(
            problem.materials[element.material_id],
            MaterialModel::Nonlinear { .. }
        )
    });
    let mut timings = SolveTimings {
        preparation_ms,
        ..SolveTimings::default()
    };
    let mut profile = FieldSolveProfile {
        csr_pattern_builds: 1,
        ..FieldSolveProfile::default()
    };
    let run = if nonlinear {
        match problem.options.nonlinear.algorithm {
            NonlinearAlgorithm::Picard => run_picard(
                problem,
                &prepared,
                states,
                az_guess,
                &mut timings,
                &mut profile,
                progress,
                diagnostics,
            )?,
            NonlinearAlgorithm::Newton => {
                let fallback_states = states.clone();
                let fallback_az = az_guess.clone();
                match run_newton(
                    problem,
                    &prepared,
                    states,
                    az_guess,
                    &mut timings,
                    &mut profile,
                    progress,
                    diagnostics,
                ) {
                    Ok(run) => run,
                    Err(newton_error) if problem.options.nonlinear.newton_fallback_to_picard => {
                        let mut run = run_picard(
                            problem,
                            &prepared,
                            fallback_states,
                            fallback_az,
                            &mut timings,
                            &mut profile,
                            progress,
                            diagnostics,
                        )
                        .map_err(|picard_error| {
                            format!(
                                "Newton solve failed ({newton_error}); Picard fallback also failed ({picard_error})"
                            )
                        })?;
                        run.algorithm = "newton_to_picard";
                        run
                    }
                    Err(error) => return Err(error),
                }
            }
        }
    } else {
        run_linear_field(
            problem,
            &prepared,
            states,
            az_guess.as_deref(),
            &mut timings,
            &mut profile,
        )?
    };

    let direct = prepared.direct_cholesky.stats();
    profile.direct_symbolic_builds = direct.symbolic_builds;
    profile.direct_numeric_factorizations = direct.numeric_factorizations;
    profile.direct_cache_hits = direct.cache_hits;
    profile.direct_pattern_mismatches = direct.pattern_mismatches;
    profile.direct_pcg_fallbacks = direct.pcg_fallbacks;
    timings.total_ms = elapsed_ms(total_start);
    progress.on_event(SolveProgressEvent::Complete {
        nonlinear_iterations: run.residual_history.len(),
    });

    let material_state = run
        .states
        .iter()
        .enumerate()
        .map(|(index, state)| ElementMaterialState {
            material_id: problem.elements[index].material_id,
            mu_r: state.mu_r,
            reluctivity_m_per_h: state.nu,
        })
        .collect();
    let energy = magnetic_energy_per_unit_depth(problem, &run.states, &run.fields);

    Ok(FieldSolution {
        az_nodal: run.az,
        element_fields: run.fields,
        final_material_state: material_state,
        convergence: ConvergenceReport {
            converged: true,
            nonlinear,
            nonlinear_algorithm: run.algorithm.to_string(),
            nonlinear_iterations: run.residual_history.len(),
            nonlinear_residual_history: run.residual_history,
            linear_solver: match problem.options.linear.solver {
                LinearSolver::Direct => "direct_cholesky_with_pcg_fallback",
                LinearSolver::Pcg => "pcg",
            }
            .to_string(),
        },
        timings,
        profile,
        energy_per_unit_depth: FieldEnergyPerUnitDepth {
            magnetic_field_j_per_m: energy,
        },
        warnings,
    })
}

struct FieldRun {
    states: Vec<ElementState>,
    az: Vec<f64>,
    fields: Vec<ElementField>,
    residual_history: Vec<f64>,
    algorithm: &'static str,
}

fn run_linear_field(
    problem: &MagnetostaticProblem,
    prepared: &PreparedFieldSystem,
    states: Vec<ElementState>,
    initial_guess: Option<&[f64]>,
    timings: &mut SolveTimings,
    profile: &mut FieldSolveProfile,
) -> Result<FieldRun, String> {
    let assembly_start = Instant::now();
    let (mut matrix, mut rhs) = prepared.assemble(problem, &states);
    timings.assembly_ms += elapsed_ms(assembly_start);
    prepared.assert_pattern_identity(&matrix)?;
    prepared.apply_boundaries(&mut matrix, &mut rhs);

    let linear_start = Instant::now();
    let az = solve_prepared_linear(
        prepared,
        &matrix,
        &rhs,
        initial_guess,
        problem.options.linear,
        profile,
    )?;
    timings.linear_solve_ms += elapsed_ms(linear_start);
    let field_start = Instant::now();
    let fields = compute_element_fields(&problem.mesh, &az);
    timings.field_recovery_ms += elapsed_ms(field_start);
    Ok(FieldRun {
        states,
        az,
        fields,
        residual_history: Vec::new(),
        algorithm: "linear",
    })
}

fn run_picard(
    problem: &MagnetostaticProblem,
    prepared: &PreparedFieldSystem,
    mut states: Vec<ElementState>,
    mut az_guess: Option<Vec<f64>>,
    timings: &mut SolveTimings,
    profile: &mut FieldSolveProfile,
    progress: &dyn ProgressSink,
    diagnostics: &dyn DiagnosticsSink,
) -> Result<FieldRun, String> {
    let max_iterations = problem.options.nonlinear.max_iterations;
    let mut residual_history = Vec::new();

    for iteration in 0..max_iterations {
        let assembly_start = Instant::now();
        let (mut matrix, mut rhs) = prepared.assemble(problem, &states);
        timings.assembly_ms += elapsed_ms(assembly_start);
        prepared.assert_pattern_identity(&matrix)?;
        prepared.apply_boundaries(&mut matrix, &mut rhs);

        let linear_start = Instant::now();
        let az = solve_prepared_linear(
            prepared,
            &matrix,
            &rhs,
            az_guess.as_deref(),
            problem.options.linear,
            profile,
        )?;
        timings.linear_solve_ms += elapsed_ms(linear_start);

        let field_start = Instant::now();
        let fields = compute_element_fields(&problem.mesh, &az);
        timings.field_recovery_ms += elapsed_ms(field_start);
        let update_start = Instant::now();
        let update = update_nonlinear_states(problem, &mut states, &fields);
        timings.material_update_ms += elapsed_ms(update_start);
        let residual = update.as_ref().map(|value| value.residual).unwrap_or(0.0);
        residual_history.push(residual);
        emit_nonlinear_event(
            problem,
            diagnostics,
            iteration + 1,
            update,
            &fields,
            residual,
        );
        progress.on_event(SolveProgressEvent::NonlinearIteration {
            iteration: iteration + 1,
            max_iterations,
            residual,
            threshold: problem.options.nonlinear.tolerance,
            worst_element: update.map(|value| value.element_id),
        });
        if residual <= problem.options.nonlinear.tolerance {
            return Ok(FieldRun {
                states,
                az,
                fields,
                residual_history,
                algorithm: "picard",
            });
        }
        az_guess = Some(az);
    }

    Err(format!(
        "nonlinear field solve failed to converge after {max_iterations} iterations; residual_history={residual_history:?}"
    ))
}

#[allow(clippy::too_many_arguments)]
fn run_newton(
    problem: &MagnetostaticProblem,
    prepared: &PreparedFieldSystem,
    mut states: Vec<ElementState>,
    az_guess: Option<Vec<f64>>,
    timings: &mut SolveTimings,
    profile: &mut FieldSolveProfile,
    progress: &dyn ProgressSink,
    diagnostics: &dyn DiagnosticsSink,
) -> Result<FieldRun, String> {
    let initial = run_linear_field(
        problem,
        prepared,
        states.clone(),
        az_guess.as_deref(),
        timings,
        profile,
    )?;
    let mut az = initial.az;
    let mut fields = initial.fields;
    let max_iterations = problem.options.nonlinear.max_iterations;
    let mut residual_history = Vec::new();

    for iteration in 0..max_iterations {
        let material_start = Instant::now();
        let update =
            update_nonlinear_states_with_policy(problem, &mut states, &fields, 1.0, f64::MAX);
        timings.material_update_ms += elapsed_ms(material_start);

        let (delta, residual) =
            solve_newton_correction(problem, prepared, &states, &fields, &az, timings, profile)?;
        if residual <= problem.options.nonlinear.tolerance {
            residual_history.push(residual);
            emit_nonlinear_event(
                problem,
                diagnostics,
                iteration + 1,
                update,
                &fields,
                residual,
            );
            progress.on_event(SolveProgressEvent::NonlinearIteration {
                iteration: iteration + 1,
                max_iterations,
                residual,
                threshold: problem.options.nonlinear.tolerance,
                worst_element: update.map(|value| value.element_id),
            });
            return Ok(FieldRun {
                states,
                az,
                fields,
                residual_history,
                algorithm: "newton",
            });
        }

        let mut damping = problem.options.nonlinear.newton_initial_damping;
        let accept_below = residual * problem.options.nonlinear.newton_line_search_accept_ratio;
        let mut accepted = None;
        let mut best_residual = f64::INFINITY;
        loop {
            let candidate_az: Vec<f64> = az
                .iter()
                .zip(&delta)
                .map(|(value, step)| value + damping * step)
                .collect();
            let field_start = Instant::now();
            let candidate_fields = compute_element_fields(&problem.mesh, &candidate_az);
            timings.field_recovery_ms += elapsed_ms(field_start);
            let mut candidate_states = states.clone();
            let material_start = Instant::now();
            let candidate_update = update_nonlinear_states_with_policy(
                problem,
                &mut candidate_states,
                &candidate_fields,
                1.0,
                f64::MAX,
            );
            timings.material_update_ms += elapsed_ms(material_start);
            let candidate_residual = nonlinear_residual_norm(
                problem,
                prepared,
                &candidate_states,
                &candidate_az,
                timings,
            )?;
            if candidate_residual.is_finite() {
                best_residual = best_residual.min(candidate_residual);
                if candidate_residual <= accept_below {
                    accepted = Some((
                        candidate_az,
                        candidate_fields,
                        candidate_states,
                        candidate_update,
                        candidate_residual,
                    ));
                    break;
                }
            }
            if damping <= problem.options.nonlinear.newton_min_damping {
                break;
            }
            damping = (damping * problem.options.nonlinear.newton_line_search_shrink)
                .max(problem.options.nonlinear.newton_min_damping);
        }

        let Some((
            candidate_az,
            candidate_fields,
            candidate_states,
            accepted_update,
            accepted_residual,
        )) = accepted
        else {
            return Err(format!(
                "Newton line search failed to reduce residual: residual={residual:.6}, best_candidate={best_residual:.6}, min_damping={:.6}",
                problem.options.nonlinear.newton_min_damping
            ));
        };
        residual_history.push(accepted_residual);
        emit_nonlinear_event(
            problem,
            diagnostics,
            iteration + 1,
            accepted_update,
            &candidate_fields,
            accepted_residual,
        );
        progress.on_event(SolveProgressEvent::NonlinearIteration {
            iteration: iteration + 1,
            max_iterations,
            residual: accepted_residual,
            threshold: problem.options.nonlinear.tolerance,
            worst_element: accepted_update.map(|value| value.element_id),
        });
        az = candidate_az;
        fields = candidate_fields;
        states = candidate_states;
        if accepted_residual <= problem.options.nonlinear.tolerance {
            return Ok(FieldRun {
                states,
                az,
                fields,
                residual_history,
                algorithm: "newton",
            });
        }
    }

    Err(format!(
        "Newton field solve failed to converge after {max_iterations} iterations; residual_history={residual_history:?}"
    ))
}

fn solve_newton_correction(
    problem: &MagnetostaticProblem,
    prepared: &PreparedFieldSystem,
    states: &[ElementState],
    fields: &[ElementField],
    az: &[f64],
    timings: &mut SolveTimings,
    profile: &mut FieldSolveProfile,
) -> Result<(Vec<f64>, f64), String> {
    let assembly_start = Instant::now();
    let (mut residual_matrix, mut source) = prepared.assemble(problem, states);
    prepared.assert_pattern_identity(&residual_matrix)?;
    prepared.apply_boundaries(&mut residual_matrix, &mut source);
    let mut matrix_times_az = vec![0.0; az.len()];
    residual_matrix.mul_vec(az, &mut matrix_times_az);
    let mut correction_rhs: Vec<f64> = source
        .iter()
        .zip(matrix_times_az)
        .map(|(rhs, lhs)| rhs - lhs)
        .collect();
    let residual = vector_norm(&correction_rhs) / vector_norm(&source).max(1.0e-30);

    let mut tangent = assemble_newton_tangent(problem, prepared, states, fields, az);
    prepared.assert_pattern_identity(&tangent)?;
    prepared.add_boundary_terms(&mut tangent);
    prepared.apply_dirichlet(&mut tangent, &mut correction_rhs);
    timings.assembly_ms += elapsed_ms(assembly_start);

    let linear_start = Instant::now();
    let options = problem.options.linear;
    let pcg_options = PcgOptions {
        execution: if options.pcg_parallel {
            PcgExecution::Parallel
        } else {
            PcgExecution::Serial
        },
        preconditioner: match options.pcg_preconditioner {
            PcgPreconditioner::IncompleteCholesky => PcgPreconditionerKind::IncompleteCholesky,
            PcgPreconditioner::Jacobi => PcgPreconditionerKind::Jacobi,
        },
        residual_check_interval: options.pcg_residual_check_interval,
    };
    let (delta, pcg) = pcg_solve_with_guess_options_profiled(
        &tangent,
        &correction_rhs,
        options.max_iterations,
        options.tolerance,
        None,
        pcg_options,
    )?;
    profile.pcg.add_assign(&pcg);
    ensure_pcg_converged(
        &pcg,
        options.max_iterations,
        options.tolerance,
        "Newton tangent",
    )?;
    timings.linear_solve_ms += elapsed_ms(linear_start);
    Ok((delta, residual))
}

fn assemble_newton_tangent(
    problem: &MagnetostaticProblem,
    prepared: &PreparedFieldSystem,
    states: &[ElementState],
    fields: &[ElementField],
    az: &[f64],
) -> CsrMatrix {
    let mut tangent = prepared.csr_pattern().zero_matrix();
    for (element_index, triangle) in problem.mesh.triangles.iter().enumerate() {
        let [i, j, k] = *triangle;
        let (area, gradients) = triangle_gradients(&problem.mesh.nodes_m, i, j, k);
        let (nu, dnu_db) = match &problem.materials[problem.elements[element_index].material_id] {
            MaterialModel::Linear { .. } => (states[element_index].nu, 0.0),
            MaterialModel::Nonlinear { bh_curve } => {
                nonlinear_nu_and_tangent(bh_curve, fields[element_index].b_mag)
            }
        };
        let da_dx = az[i] * gradients[0][0] + az[j] * gradients[1][0] + az[k] * gradients[2][0];
        let da_dy = az[i] * gradients[0][1] + az[j] * gradients[1][1] + az[k] * gradients[2][1];
        let tangent_scale = dnu_db / fields[element_index].b_mag.max(1.0e-12);
        let grad_a_dot = [
            da_dx * gradients[0][0] + da_dy * gradients[0][1],
            da_dx * gradients[1][0] + da_dy * gradients[1][1],
            da_dx * gradients[2][0] + da_dy * gradients[2][1],
        ];
        let slots = prepared.csr_pattern().element_slots(element_index);
        for local_row in 0..3 {
            for local_col in 0..3 {
                let dot = gradients[local_row][0] * gradients[local_col][0]
                    + gradients[local_row][1] * gradients[local_col][1];
                let value = area
                    * (nu * dot + tangent_scale * grad_a_dot[local_row] * grad_a_dot[local_col]);
                if value.is_finite() && value.abs() > 1.0e-30 {
                    tangent.values[slots[local_row][local_col]] += value;
                }
            }
        }
    }
    tangent
}

fn nonlinear_nu_and_tangent(curve: &BhCurve, b_t: f64) -> (f64, f64) {
    let mu_r = curve.secant_mu_r(b_t);
    let nu = 1.0 / (MU_0 * mu_r.max(1.0));
    let delta = (b_t.abs() * 1.0e-3).max(1.0e-4);
    let b_low = (b_t - delta).max(0.0);
    let b_high = b_t + delta;
    let nu_low = 1.0 / (MU_0 * curve.secant_mu_r(b_low).max(1.0));
    let nu_high = 1.0 / (MU_0 * curve.secant_mu_r(b_high).max(1.0));
    (nu, (nu_high - nu_low) / (b_high - b_low).max(1.0e-12))
}

fn nonlinear_residual_norm(
    problem: &MagnetostaticProblem,
    prepared: &PreparedFieldSystem,
    states: &[ElementState],
    az: &[f64],
    timings: &mut SolveTimings,
) -> Result<f64, String> {
    let assembly_start = Instant::now();
    let (mut matrix, mut source) = prepared.assemble(problem, states);
    prepared.assert_pattern_identity(&matrix)?;
    prepared.apply_boundaries(&mut matrix, &mut source);
    let mut lhs = vec![0.0; az.len()];
    matrix.mul_vec(az, &mut lhs);
    timings.assembly_ms += elapsed_ms(assembly_start);
    let residual: Vec<f64> = lhs
        .into_iter()
        .zip(&source)
        .map(|(lhs, rhs)| lhs - rhs)
        .collect();
    Ok(vector_norm(&residual) / vector_norm(&source).max(1.0e-30))
}

fn vector_norm(values: &[f64]) -> f64 {
    values.iter().map(|value| value * value).sum::<f64>().sqrt()
}

fn emit_nonlinear_event(
    problem: &MagnetostaticProblem,
    diagnostics: &dyn DiagnosticsSink,
    iteration: usize,
    update: Option<WorstUpdate>,
    fields: &[ElementField],
    residual: f64,
) {
    if let Some(update) = update {
        diagnostics.on_nonlinear_diagnostic(NonlinearDiagnosticEvent {
            iteration,
            element_id: update.element_id,
            material_id: problem.elements[update.element_id].material_id,
            centroid_m: triangle_centroid(&problem.mesh, update.element_id),
            b_t: [fields[update.element_id].bx, fields[update.element_id].by],
            b_mag_t: fields[update.element_id].b_mag,
            previous_mu_r: update.previous_mu_r,
            target_mu_r: update.target_mu_r,
            relaxed_mu_r: update.relaxed_mu_r,
            residual,
        });
    }
}

impl MagnetostaticProblem {
    /// Validate the neutral contract. Successful validation returns
    /// non-fatal scale warnings for the adapter to report.
    pub fn validate(&self) -> Result<Vec<String>, String> {
        validate_mesh(&self.mesh)?;
        validate_materials(&self.materials)?;
        if self.elements.len() != self.mesh.triangles.len() {
            return Err(format!(
                "elements length {} does not match triangle count {}",
                self.elements.len(),
                self.mesh.triangles.len()
            ));
        }
        for (index, element) in self.elements.iter().enumerate() {
            if element.material_id >= self.materials.len() {
                return Err(format!(
                    "element {index} references material_id {} but only {} materials exist",
                    element.material_id,
                    self.materials.len()
                ));
            }
            if !element.current_density_z_a_per_m2.is_finite()
                || !element.remanence_t.iter().all(|value| value.is_finite())
                || !element.pm_source_scale.is_finite()
                || element.pm_source_scale < 0.0
            {
                return Err(format!("element {index} contains invalid source data"));
            }
        }
        validate_boundaries(&self.mesh, &self.boundaries)?;
        validate_options(&self.options)?;
        validate_warm_start(self)?;

        let (min, max) = bounding_box(&self.mesh.nodes_m);
        let span = (max[0] - min[0]).max(max[1] - min[1]);
        let mut warnings = Vec::new();
        if !(1.0e-4..=10.0).contains(&span) {
            warnings.push(format!(
                "mesh bounding-box span is {span:.6e} m; expected 1e-4 to 10 m; verify units.length"
            ));
        }
        Ok(warnings)
    }
}

impl PreparedFieldSystem {
    pub fn new(mesh: &FemMesh, boundaries: &BoundarySet) -> Result<Self, String> {
        validate_mesh(mesh)?;
        validate_boundaries(mesh, boundaries)?;
        let dirichlet: std::collections::HashSet<usize> =
            boundaries.dirichlet_az_zero_nodes.iter().copied().collect();
        let mut terms = Vec::new();
        for pair in &boundaries.paired_nodes {
            let [left, right] = pair.nodes;
            if dirichlet.contains(&left) || dirichlet.contains(&right) {
                continue;
            }
            let sign = match pair.kind {
                PairedBoundaryKind::Periodic => -1.0,
                PairedBoundaryKind::AntiPeriodic => 1.0,
            };
            let penalty = boundaries.periodic_penalty;
            terms.extend([
                (left, left, penalty),
                (left, right, sign * penalty),
                (right, left, sign * penalty),
                (right, right, penalty),
            ]);
        }
        let extra_entries: Vec<(usize, usize)> =
            terms.iter().map(|(row, col, _)| (*row, *col)).collect();
        let csr_assembly_pattern = ElementCsrAssemblyPattern::from_triangles(
            mesh.nodes_m.len(),
            &mesh.triangles,
            &extra_entries,
        );
        let boundary_slots = terms
            .into_iter()
            .map(|(row, col, value)| {
                csr_assembly_pattern
                    .slot(row, col)
                    .map(|slot| (slot, value))
                    .ok_or_else(|| format!("failed to prepare boundary matrix slot ({row}, {col})"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self {
            csr_assembly_pattern,
            boundary_slots,
            dirichlet_nodes: boundaries.dirichlet_az_zero_nodes.clone(),
            direct_cholesky: DirectCholeskyCache::new(),
            formulation_version: FORMULATION_VERSION,
        })
    }

    fn assemble(
        &self,
        problem: &MagnetostaticProblem,
        states: &[ElementState],
    ) -> (CsrMatrix, Vec<f64>) {
        let mut matrix = self.csr_assembly_pattern.zero_matrix();
        let mut rhs = vec![0.0; problem.mesh.nodes_m.len()];
        for (element_index, tri) in problem.mesh.triangles.iter().enumerate() {
            let [i, j, m] = *tri;
            let (area, grad) = triangle_gradients(&problem.mesh.nodes_m, i, j, m);
            if area <= 0.0 {
                continue;
            }
            let state = states[element_index];
            let slots = self.csr_assembly_pattern.element_slots(element_index);
            for a in 0..3 {
                for b in 0..3 {
                    let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                    let value = state.nu * dot * area;
                    if value.abs() > 1.0e-30 {
                        matrix.values[slots[a][b]] += value;
                    }
                }
            }

            let element = &problem.elements[element_index];
            let local_nodes = [i, j, m];
            let [br_x, br_y] = element.remanence_t;
            if element.pm_source_scale > 0.0 && (br_x != 0.0 || br_y != 0.0) {
                let scale = state.nu * element.pm_source_scale;
                for a in 0..3 {
                    let rotated = br_x * grad[a][1] - br_y * grad[a][0];
                    rhs[local_nodes[a]] += scale * rotated * area;
                }
            }
            if element.current_density_z_a_per_m2 != 0.0 {
                let contribution = element.current_density_z_a_per_m2 * area / 3.0;
                rhs[i] += contribution;
                rhs[j] += contribution;
                rhs[m] += contribution;
            }
        }
        (matrix, rhs)
    }

    pub(crate) fn assemble_reluctivity_from(
        &self,
        nodes_m: &[[f64; 2]],
        triangles: &[[usize; 3]],
        mut reluctivity_at: impl FnMut(usize) -> f64,
    ) -> CsrMatrix {
        let mut matrix = self.csr_assembly_pattern.zero_matrix();
        for (element_index, tri) in triangles.iter().enumerate() {
            let [i, j, m] = *tri;
            let (area, grad) = triangle_gradients(nodes_m, i, j, m);
            if area <= 0.0 {
                continue;
            }
            let nu = reluctivity_at(element_index);
            let slots = self.csr_assembly_pattern.element_slots(element_index);
            for a in 0..3 {
                for b in 0..3 {
                    let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                    let value = nu * dot * area;
                    if value.abs() > 1.0e-30 {
                        matrix.values[slots[a][b]] += value;
                    }
                }
            }
        }
        matrix
    }

    pub(crate) fn add_boundary_terms(&self, matrix: &mut CsrMatrix) {
        for &(slot, value) in &self.boundary_slots {
            matrix.values[slot] += value;
        }
    }

    pub(crate) fn apply_dirichlet(&self, matrix: &mut CsrMatrix, rhs: &mut [f64]) {
        matrix.apply_dirichlet(rhs, &self.dirichlet_nodes);
    }

    fn apply_boundaries(&self, matrix: &mut CsrMatrix, rhs: &mut [f64]) {
        self.add_boundary_terms(matrix);
        self.apply_dirichlet(matrix, rhs);
    }

    pub(crate) fn assert_pattern_identity(&self, matrix: &CsrMatrix) -> Result<(), String> {
        if self.formulation_version != FORMULATION_VERSION
            || !self.csr_assembly_pattern.matches_structure(matrix)
        {
            return Err("prepared field system CSR structure changed during refill".to_string());
        }
        Ok(())
    }

    pub(crate) fn csr_pattern(&self) -> &ElementCsrAssemblyPattern {
        &self.csr_assembly_pattern
    }

    pub(crate) fn direct_solve(
        &self,
        matrix: &CsrMatrix,
        rhs: &[f64],
    ) -> Result<Option<Vec<f64>>, DirectCholeskyError> {
        self.direct_cholesky.solve_checked(matrix, rhs)
    }

    pub(crate) fn direct_stats(&self) -> crate::sparse::DirectCholeskyStats {
        self.direct_cholesky.stats()
    }
}

fn solve_prepared_linear(
    prepared: &PreparedFieldSystem,
    matrix: &CsrMatrix,
    rhs: &[f64],
    initial_guess: Option<&[f64]>,
    options: LinearSolveOptions,
    profile: &mut FieldSolveProfile,
) -> Result<Vec<f64>, String> {
    if options.solver == LinearSolver::Direct {
        match prepared.direct_cholesky.solve_checked(matrix, rhs) {
            Ok(Some(solution)) => {
                profile.direct_successful_solves += 1;
                return Ok(solution);
            }
            Ok(None) => {}
            Err(DirectCholeskyError::PatternMismatch) => {
                return Err(
                    "direct Cholesky cache rejected a structurally different CSR matrix"
                        .to_string(),
                )
            }
        }
    }
    let pcg_options = PcgOptions {
        execution: if options.pcg_parallel {
            PcgExecution::Parallel
        } else {
            PcgExecution::Serial
        },
        preconditioner: match options.pcg_preconditioner {
            PcgPreconditioner::IncompleteCholesky => PcgPreconditionerKind::IncompleteCholesky,
            PcgPreconditioner::Jacobi => PcgPreconditionerKind::Jacobi,
        },
        residual_check_interval: options.pcg_residual_check_interval,
    };
    let (solution, pcg) = pcg_solve_with_guess_options_profiled(
        matrix,
        rhs,
        options.max_iterations,
        options.tolerance,
        initial_guess,
        pcg_options,
    )?;
    profile.pcg.add_assign(&pcg);
    ensure_pcg_converged(
        &pcg,
        options.max_iterations,
        options.tolerance,
        "field",
    )?;
    Ok(solution)
}

fn ensure_pcg_converged(
    profile: &PcgProfile,
    max_iterations: usize,
    tolerance: f64,
    context: &str,
) -> Result<(), String> {
    if profile.max_iter_calls == 0 {
        return Ok(());
    }
    Err(format!(
        "{context} PCG failed to converge within {max_iterations} iterations \
         at relative tolerance {tolerance:.3e}"
    ))
}

#[derive(Clone, Copy)]
struct WorstUpdate {
    element_id: usize,
    previous_mu_r: f64,
    target_mu_r: f64,
    relaxed_mu_r: f64,
    raw_residual: f64,
    residual: f64,
}

fn update_nonlinear_states(
    problem: &MagnetostaticProblem,
    states: &mut [ElementState],
    fields: &[ElementField],
) -> Option<WorstUpdate> {
    update_nonlinear_states_with_policy(
        problem,
        states,
        fields,
        problem.options.nonlinear.relaxation,
        problem.options.nonlinear.mu_r_step_cap,
    )
}

fn update_nonlinear_states_with_policy(
    problem: &MagnetostaticProblem,
    states: &mut [ElementState],
    fields: &[ElementField],
    relaxation: f64,
    mu_r_step_cap: f64,
) -> Option<WorstUpdate> {
    let mut worst = None;
    for (index, (element, field)) in problem.elements.iter().zip(fields).enumerate() {
        let MaterialModel::Nonlinear { bh_curve } = &problem.materials[element.material_id] else {
            continue;
        };
        let update = secant_material_update(
            bh_curve,
            field.b_mag,
            states[index].mu_r,
            relaxation,
            mu_r_step_cap,
        );
        states[index].set_mu_r(update.relaxed_mu_r);
        if worst
            .map(|current: WorstUpdate| update.raw_residual > current.raw_residual)
            .unwrap_or(true)
        {
            worst = Some(WorstUpdate {
                element_id: index,
                previous_mu_r: update.previous_mu_r,
                target_mu_r: update.target_mu_r,
                relaxed_mu_r: update.relaxed_mu_r,
                raw_residual: update.raw_residual,
                residual: update.raw_residual * relaxation,
            });
        }
    }
    worst
}

impl BhCurve {
    pub fn interpolate_h(&self, b_t: f64) -> f64 {
        let b_t = b_t.abs();
        for window in self.points.windows(2) {
            let p0 = window[0];
            let p1 = window[1];
            if b_t <= p1.b_t {
                let fraction = (b_t - p0.b_t) / (p1.b_t - p0.b_t).max(1.0e-12);
                return p0.h_a_per_m + fraction * (p1.h_a_per_m - p0.h_a_per_m);
            }
        }
        let p0 = self.points[self.points.len() - 2];
        let p1 = self.points[self.points.len() - 1];
        let slope = (p1.h_a_per_m - p0.h_a_per_m) / (p1.b_t - p0.b_t).max(1.0e-12);
        p1.h_a_per_m + slope * (b_t - p1.b_t)
    }

    pub fn secant_mu_r(&self, b_t: f64) -> f64 {
        let effective_b = b_t.abs().max(1.0e-4);
        let h = self.interpolate_h(effective_b).max(1.0e-9);
        (effective_b / (MU_0 * h)).clamp(self.mu_r_min, self.mu_r_max)
    }

    pub fn initial_mu_r(&self) -> f64 {
        self.points
            .iter()
            .skip(1)
            .find(|point| point.b_t > 0.0 && point.h_a_per_m > 0.0)
            .map(|point| (point.b_t / (MU_0 * point.h_a_per_m)).clamp(self.mu_r_min, self.mu_r_max))
            .unwrap_or(600.0)
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct SecantMaterialUpdate {
    pub previous_mu_r: f64,
    pub target_mu_r: f64,
    pub relaxed_mu_r: f64,
    pub raw_residual: f64,
    pub applied_residual: f64,
    pub capped: bool,
}

/// Shared nonlinear material law used by the generic field loop and motor
/// adapter. It is pure: curve, field, and policy arrive as explicit data.
pub(crate) fn secant_material_update(
    curve: &BhCurve,
    b_mag_t: f64,
    previous_mu_r: f64,
    relaxation: f64,
    mu_r_step_cap: f64,
) -> SecantMaterialUpdate {
    let previous_mu_r = previous_mu_r.max(1.0);
    let target_mu_r = curve.secant_mu_r(b_mag_t);
    let raw_residual = ((target_mu_r - previous_mu_r) / previous_mu_r).abs();
    let uncapped = previous_mu_r + relaxation * (target_mu_r - previous_mu_r);
    let step_cap = mu_r_step_cap.max(1.0);
    let relaxed_mu_r = uncapped.clamp(previous_mu_r / step_cap, previous_mu_r * step_cap);
    let capped = (relaxed_mu_r - uncapped).abs() > uncapped.abs().max(1.0) * 1.0e-12;
    let applied_residual = ((relaxed_mu_r - previous_mu_r) / previous_mu_r).abs();
    SecantMaterialUpdate {
        previous_mu_r,
        target_mu_r,
        relaxed_mu_r,
        raw_residual,
        applied_residual,
        capped,
    }
}

fn initial_element_states(problem: &MagnetostaticProblem) -> Vec<ElementState> {
    problem
        .elements
        .iter()
        .map(|element| match &problem.materials[element.material_id] {
            MaterialModel::Linear { mu_r } => ElementState::new(*mu_r),
            MaterialModel::Nonlinear { bh_curve } => ElementState::new(bh_curve.initial_mu_r()),
        })
        .collect()
}

fn compute_element_fields(mesh: &FemMesh, az: &[f64]) -> Vec<ElementField> {
    mesh.triangles
        .iter()
        .map(|tri| {
            let [i, j, m] = *tri;
            let (area, grad) = triangle_gradients(&mesh.nodes_m, i, j, m);
            if area <= 0.0 {
                return ElementField {
                    bx: 0.0,
                    by: 0.0,
                    b_mag: 0.0,
                };
            }
            let da_dx = az[i] * grad[0][0] + az[j] * grad[1][0] + az[m] * grad[2][0];
            let da_dy = az[i] * grad[0][1] + az[j] * grad[1][1] + az[m] * grad[2][1];
            let bx = da_dy;
            let by = -da_dx;
            ElementField {
                bx,
                by,
                b_mag: (bx * bx + by * by).sqrt(),
            }
        })
        .collect()
}

fn magnetic_energy_per_unit_depth(
    problem: &MagnetostaticProblem,
    states: &[ElementState],
    fields: &[ElementField],
) -> f64 {
    problem
        .mesh
        .triangles
        .iter()
        .enumerate()
        .map(|(index, tri)| {
            let [i, j, m] = *tri;
            let (area, _) = triangle_gradients(&problem.mesh.nodes_m, i, j, m);
            0.5 * states[index].nu * fields[index].b_mag.powi(2) * area
        })
        .sum()
}

fn triangle_centroid(mesh: &FemMesh, element_index: usize) -> [f64; 2] {
    let [i, j, m] = mesh.triangles[element_index];
    [
        (mesh.nodes_m[i][0] + mesh.nodes_m[j][0] + mesh.nodes_m[m][0]) / 3.0,
        (mesh.nodes_m[i][1] + mesh.nodes_m[j][1] + mesh.nodes_m[m][1]) / 3.0,
    ]
}

fn validate_mesh(mesh: &FemMesh) -> Result<(), String> {
    if mesh.nodes_m.len() < 3 {
        return Err("mesh must contain at least three nodes".to_string());
    }
    if mesh.triangles.is_empty() {
        return Err("mesh must contain at least one triangle".to_string());
    }
    for (index, node) in mesh.nodes_m.iter().enumerate() {
        if !node.iter().all(|coordinate| coordinate.is_finite()) {
            return Err(format!(
                "mesh node {index} contains a non-finite coordinate"
            ));
        }
    }
    let (min, max) = bounding_box(&mesh.nodes_m);
    if max[0] - min[0] <= 0.0 || max[1] - min[1] <= 0.0 {
        return Err("mesh must have finite nonzero span on both axes".to_string());
    }
    for (index, tri) in mesh.triangles.iter().enumerate() {
        if tri.iter().any(|node| *node >= mesh.nodes_m.len()) {
            return Err(format!(
                "triangle {index} contains an out-of-range node index"
            ));
        }
        if tri[0] == tri[1] || tri[1] == tri[2] || tri[0] == tri[2] {
            return Err(format!("triangle {index} repeats a node index"));
        }
        let (area, _) = triangle_gradients(&mesh.nodes_m, tri[0], tri[1], tri[2]);
        if !area.is_finite() || area <= 0.0 {
            return Err(format!("triangle {index} is degenerate"));
        }
    }
    Ok(())
}

fn validate_materials(materials: &[MaterialModel]) -> Result<(), String> {
    if materials.is_empty() {
        return Err("at least one material is required".to_string());
    }
    for (index, material) in materials.iter().enumerate() {
        match material {
            MaterialModel::Linear { mu_r } => {
                if !mu_r.is_finite() || *mu_r < 1.0 {
                    return Err(format!("linear material {index} requires finite mu_r >= 1"));
                }
            }
            MaterialModel::Nonlinear { bh_curve } => validate_bh_curve(index, bh_curve)?,
        }
    }
    Ok(())
}

fn validate_bh_curve(material_index: usize, curve: &BhCurve) -> Result<(), String> {
    if curve.points.len() < 2 {
        return Err(format!(
            "nonlinear material {material_index} B-H curve needs at least two points"
        ));
    }
    if curve.points[0]
        != (BhPoint {
            b_t: 0.0,
            h_a_per_m: 0.0,
        })
    {
        return Err(format!(
            "nonlinear material {material_index} B-H curve must start at B=0, H=0"
        ));
    }
    if !curve.mu_r_min.is_finite()
        || !curve.mu_r_max.is_finite()
        || curve.mu_r_min < 1.0
        || curve.mu_r_max < curve.mu_r_min
    {
        return Err(format!(
            "nonlinear material {material_index} has invalid permeability bounds"
        ));
    }
    for (point_index, point) in curve.points.iter().enumerate() {
        if !point.b_t.is_finite()
            || !point.h_a_per_m.is_finite()
            || point.b_t < 0.0
            || point.h_a_per_m < 0.0
        {
            return Err(format!(
                "nonlinear material {material_index} B-H point {point_index} is invalid"
            ));
        }
        if point_index > 0 {
            let previous = curve.points[point_index - 1];
            if point.b_t <= previous.b_t || point.h_a_per_m < previous.h_a_per_m {
                return Err(format!(
                    "nonlinear material {material_index} B-H curve must have strictly increasing B and non-decreasing H"
                ));
            }
        }
    }
    Ok(())
}

fn validate_boundaries(mesh: &FemMesh, boundaries: &BoundarySet) -> Result<(), String> {
    if boundaries.dirichlet_az_zero_nodes.is_empty() {
        return Err(
            "at least one A_z=0 Dirichlet node is required to anchor the system".to_string(),
        );
    }
    if !boundaries.periodic_penalty.is_finite() || boundaries.periodic_penalty <= 0.0 {
        return Err("periodic_penalty must be finite and positive".to_string());
    }
    let mut assigned = std::collections::HashSet::new();
    for &node in &boundaries.dirichlet_az_zero_nodes {
        if node >= mesh.nodes_m.len() {
            return Err(format!("Dirichlet node {node} is out of range"));
        }
        if !assigned.insert(node) {
            return Err(format!("Dirichlet node {node} is duplicated"));
        }
    }
    for (index, pair) in boundaries.paired_nodes.iter().enumerate() {
        let [left, right] = pair.nodes;
        if left >= mesh.nodes_m.len() || right >= mesh.nodes_m.len() {
            return Err(format!(
                "paired boundary {index} contains an out-of-range node"
            ));
        }
        if left == right {
            return Err(format!("paired boundary {index} pairs a node with itself"));
        }
        if !assigned.insert(left) || !assigned.insert(right) {
            return Err(format!(
                "paired boundary {index} overlaps another boundary assignment"
            ));
        }
    }
    Ok(())
}

fn validate_options(options: &SolveOptions) -> Result<(), String> {
    if !options.linear.tolerance.is_finite()
        || options.linear.tolerance <= 0.0
        || options.linear.tolerance >= 1.0
        || options.linear.max_iterations == 0
        || options.linear.pcg_residual_check_interval == 0
    {
        return Err("linear solver options are invalid".to_string());
    }
    if options.nonlinear.max_iterations == 0
        || !options.nonlinear.tolerance.is_finite()
        || options.nonlinear.tolerance <= 0.0
        || options.nonlinear.tolerance >= 1.0
        || !options.nonlinear.relaxation.is_finite()
        || options.nonlinear.relaxation <= 0.0
        || options.nonlinear.relaxation > 1.0
        || !options.nonlinear.mu_r_step_cap.is_finite()
        || options.nonlinear.mu_r_step_cap < 1.0
        || !options.nonlinear.newton_initial_damping.is_finite()
        || options.nonlinear.newton_initial_damping <= 0.0
        || options.nonlinear.newton_initial_damping > 1.0
        || !options.nonlinear.newton_min_damping.is_finite()
        || options.nonlinear.newton_min_damping <= 0.0
        || options.nonlinear.newton_min_damping > options.nonlinear.newton_initial_damping
        || !options.nonlinear.newton_line_search_shrink.is_finite()
        || options.nonlinear.newton_line_search_shrink <= 0.0
        || options.nonlinear.newton_line_search_shrink >= 1.0
        || !options
            .nonlinear
            .newton_line_search_accept_ratio
            .is_finite()
        || options.nonlinear.newton_line_search_accept_ratio <= 0.0
        || options.nonlinear.newton_line_search_accept_ratio > 1.0
    {
        return Err("nonlinear solver options are invalid".to_string());
    }
    Ok(())
}

fn validate_warm_start(problem: &MagnetostaticProblem) -> Result<(), String> {
    let Some(warm_start) = problem.warm_start.as_ref() else {
        return Ok(());
    };
    if !warm_start.az_nodal.is_empty() {
        if warm_start.az_nodal.len() != problem.mesh.nodes_m.len() {
            return Err(format!(
                "warm_start.az_nodal length {} does not match node count {}",
                warm_start.az_nodal.len(),
                problem.mesh.nodes_m.len()
            ));
        }
        if !warm_start.az_nodal.iter().all(|value| value.is_finite()) {
            return Err("warm_start.az_nodal must contain only finite values".to_string());
        }
    }
    if !warm_start.mu_r_by_element.is_empty() {
        if warm_start.mu_r_by_element.len() != problem.elements.len() {
            return Err(format!(
                "warm_start.mu_r_by_element length {} does not match element count {}",
                warm_start.mu_r_by_element.len(),
                problem.elements.len()
            ));
        }
        if !warm_start
            .mu_r_by_element
            .iter()
            .all(|value| value.is_finite() && *value >= 1.0)
        {
            return Err(
                "warm_start.mu_r_by_element must contain only finite values >= 1".to_string(),
            );
        }
    }
    Ok(())
}

fn bounding_box(nodes: &[[f64; 2]]) -> ([f64; 2], [f64; 2]) {
    let mut min = [f64::INFINITY; 2];
    let mut max = [f64::NEG_INFINITY; 2];
    for node in nodes {
        min[0] = min[0].min(node[0]);
        min[1] = min[1].min(node[1]);
        max[0] = max[0].max(node[0]);
        max[1] = max[1].max(node[1]);
    }
    (min, max)
}

fn elapsed_ms(start: Instant) -> u64 {
    start.elapsed().as_millis() as u64
}

const fn default_mu_r_min() -> f64 {
    1.0
}
const fn default_mu_r_max() -> f64 {
    10_000.0
}
const fn default_pm_source_scale() -> f64 {
    1.0
}
const fn default_periodic_penalty() -> f64 {
    1.0e10
}
const fn default_pcg_residual_check_interval() -> usize {
    8
}
const fn default_linear_tolerance() -> f64 {
    1.0e-8
}
const fn default_linear_max_iterations() -> usize {
    5_000
}
const fn default_nonlinear_max_iterations() -> usize {
    100
}
const fn default_nonlinear_tolerance() -> f64 {
    0.05
}
const fn default_picard_relaxation() -> f64 {
    0.1
}
const fn default_mu_step_cap() -> f64 {
    1.5
}
const fn default_newton_initial_damping() -> f64 {
    1.0
}
const fn default_newton_min_damping() -> f64 {
    0.015625
}
const fn default_newton_line_search_shrink() -> f64 {
    0.5
}
const fn default_newton_line_search_accept_ratio() -> f64 {
    0.999
}
const fn default_newton_fallback_to_picard() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    const TEST_HALF_SPAN_M: f64 = 1.0e-2;

    fn square_problem() -> MagnetostaticProblem {
        MagnetostaticProblem {
            mesh: FemMesh {
                nodes_m: vec![[0.0, 0.0], [1.0e-2, 0.0], [1.0e-2, 1.0e-2], [0.0, 1.0e-2]],
                triangles: vec![[0, 1, 2], [0, 2, 3]],
            },
            materials: vec![MaterialModel::Linear { mu_r: 1.0 }],
            elements: vec![
                ElementPhysics {
                    material_id: 0,
                    current_density_z_a_per_m2: 1.0e6,
                    remanence_t: [0.0, 0.0],
                    pm_source_scale: 1.0,
                },
                ElementPhysics {
                    material_id: 0,
                    current_density_z_a_per_m2: 1.0e6,
                    remanence_t: [0.0, 0.0],
                    pm_source_scale: 1.0,
                },
            ],
            boundaries: BoundarySet {
                dirichlet_az_zero_nodes: vec![0, 1, 2],
                paired_nodes: Vec::new(),
                periodic_penalty: 1.0e10,
            },
            options: SolveOptions::default(),
            warm_start: None,
        }
    }

    fn centered_square_problem(
        current_density_z_a_per_m2: f64,
        remanence_t: [f64; 2],
    ) -> MagnetostaticProblem {
        MagnetostaticProblem {
            mesh: FemMesh {
                nodes_m: vec![
                    [-TEST_HALF_SPAN_M, -TEST_HALF_SPAN_M],
                    [TEST_HALF_SPAN_M, -TEST_HALF_SPAN_M],
                    [TEST_HALF_SPAN_M, TEST_HALF_SPAN_M],
                    [-TEST_HALF_SPAN_M, TEST_HALF_SPAN_M],
                    [0.0, 0.0],
                ],
                triangles: vec![[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
            },
            materials: vec![MaterialModel::Linear { mu_r: 1.0 }],
            elements: (0..4)
                .map(|_| ElementPhysics {
                    material_id: 0,
                    current_density_z_a_per_m2,
                    remanence_t,
                    pm_source_scale: 1.0,
                })
                .collect(),
            boundaries: BoundarySet {
                dirichlet_az_zero_nodes: vec![0, 1, 2, 3],
                paired_nodes: Vec::new(),
                periodic_penalty: 1.0e10,
            },
            options: SolveOptions::default(),
            warm_start: None,
        }
    }

    fn paired_strip_problem(
        paired_kind: Option<PairedBoundaryKind>,
        anti_symmetric_source: bool,
    ) -> MagnetostaticProblem {
        let span = 2.0e-2;
        let nodes_m = vec![
            [0.0, 0.0],
            [0.5 * span, 0.0],
            [span, 0.0],
            [0.0, 0.5 * span],
            [0.5 * span, 0.5 * span],
            [span, 0.5 * span],
            [0.0, span],
            [0.5 * span, span],
            [span, span],
        ];
        let triangles = vec![
            [0, 1, 4],
            [0, 4, 3],
            [1, 2, 5],
            [1, 5, 4],
            [3, 4, 7],
            [3, 7, 6],
            [4, 5, 8],
            [4, 8, 7],
        ];
        let elements = triangles
            .iter()
            .map(|triangle| {
                let centroid_x = triangle.iter().map(|&node| nodes_m[node][0]).sum::<f64>() / 3.0;
                let sign = if anti_symmetric_source && centroid_x > 0.5 * span {
                    -1.0
                } else {
                    1.0
                };
                ElementPhysics {
                    material_id: 0,
                    current_density_z_a_per_m2: sign * 1.0e6,
                    remanence_t: [0.0, 0.0],
                    pm_source_scale: 1.0,
                }
            })
            .collect();
        MagnetostaticProblem {
            mesh: FemMesh { nodes_m, triangles },
            materials: vec![MaterialModel::Linear { mu_r: 1.0 }],
            elements,
            boundaries: BoundarySet {
                dirichlet_az_zero_nodes: vec![0, 1, 2, 6, 7, 8],
                paired_nodes: paired_kind
                    .map(|kind| {
                        vec![PairedBoundary {
                            nodes: [3, 5],
                            kind,
                        }]
                    })
                    .unwrap_or_default(),
                periodic_penalty: 1.0e10,
            },
            options: SolveOptions::default(),
            warm_start: None,
        }
    }

    #[test]
    fn validates_and_solves_linear_problem_without_environment() {
        let problem = square_problem();
        let solution = solve(&problem).unwrap();
        assert!(solution.convergence.converged);
        assert!(!solution.convergence.nonlinear);
        assert_eq!(solution.az_nodal.len(), 4);
        assert_eq!(solution.element_fields.len(), 2);
        assert!(solution.az_nodal[3].is_finite());
        assert_eq!(solution.profile.csr_pattern_builds, 1);
        assert_eq!(solution.profile.direct_symbolic_builds, 1);
        assert_eq!(solution.profile.direct_numeric_factorizations, 1);
    }

    #[test]
    fn current_driven_square_matches_discrete_analytic_solution() {
        let current_density = 1.0e6;
        let problem = centered_square_problem(current_density, [0.0, 0.0]);
        let solution = solve(&problem).unwrap();
        let expected_center_az = current_density * MU_0 * TEST_HALF_SPAN_M.powi(2) / 3.0;
        assert!(
            (solution.az_nodal[4] - expected_center_az).abs() < 1.0e-14,
            "center A_z={} expected={expected_center_az}",
            solution.az_nodal[4]
        );
    }

    #[test]
    fn one_element_pm_source_matches_discrete_analytic_solution() {
        let mut problem = centered_square_problem(0.0, [0.0, 0.0]);
        problem.elements[0].remanence_t = [1.0, 0.0];
        let solution = solve(&problem).unwrap();
        let expected_center_az = TEST_HALF_SPAN_M / 4.0;
        assert!(
            (solution.az_nodal[4] - expected_center_az).abs() < 1.0e-14,
            "center A_z={} expected={expected_center_az}",
            solution.az_nodal[4]
        );
    }

    #[test]
    fn periodic_strip_matches_equivalent_full_model() {
        let full = solve(&paired_strip_problem(None, false)).unwrap();
        let periodic = solve(&paired_strip_problem(
            Some(PairedBoundaryKind::Periodic),
            false,
        ))
        .unwrap();
        for (full_az, periodic_az) in full.az_nodal.iter().zip(&periodic.az_nodal) {
            assert!((full_az - periodic_az).abs() < 1.0e-12);
        }
        assert!((periodic.az_nodal[3] - periodic.az_nodal[5]).abs() < 1.0e-12);
    }

    #[test]
    fn anti_periodic_strip_matches_equivalent_full_model() {
        let full = solve(&paired_strip_problem(None, true)).unwrap();
        let anti_periodic = solve(&paired_strip_problem(
            Some(PairedBoundaryKind::AntiPeriodic),
            true,
        ))
        .unwrap();
        for (full_az, sector_az) in full.az_nodal.iter().zip(&anti_periodic.az_nodal) {
            assert!((full_az - sector_az).abs() < 1.0e-12);
        }
        assert!((anti_periodic.az_nodal[3] + anti_periodic.az_nodal[5]).abs() < 1.0e-12);
    }

    fn nonlinear_square_problem() -> MagnetostaticProblem {
        let mut problem = centered_square_problem(3.0e6, [0.0, 0.0]);
        problem.materials[0] = MaterialModel::Nonlinear {
            bh_curve: BhCurve {
                points: vec![
                    BhPoint {
                        b_t: 0.0,
                        h_a_per_m: 0.0,
                    },
                    BhPoint {
                        b_t: 0.2,
                        h_a_per_m: 80.0,
                    },
                    BhPoint {
                        b_t: 0.8,
                        h_a_per_m: 400.0,
                    },
                    BhPoint {
                        b_t: 1.4,
                        h_a_per_m: 2_000.0,
                    },
                    BhPoint {
                        b_t: 1.8,
                        h_a_per_m: 12_000.0,
                    },
                    BhPoint {
                        b_t: 2.1,
                        h_a_per_m: 60_000.0,
                    },
                ],
                mu_r_min: 1.0,
                mu_r_max: 10_000.0,
            },
        };
        problem
    }

    #[test]
    fn nonlinear_square_is_reproducible_and_reuses_prepared_cache() {
        let problem = nonlinear_square_problem();
        let first = solve(&problem).unwrap();
        let second = solve(&problem).unwrap();
        assert_eq!(first.az_nodal, second.az_nodal);
        assert_eq!(
            first.convergence.nonlinear_residual_history,
            second.convergence.nonlinear_residual_history
        );
        assert!(first.convergence.nonlinear_iterations > 1);
        assert_eq!(first.profile.csr_pattern_builds, 1);
        assert_eq!(first.profile.direct_symbolic_builds, 1);
        assert_eq!(
            first.profile.direct_numeric_factorizations,
            first.convergence.nonlinear_iterations as u64
        );
        assert_eq!(
            first.profile.direct_cache_hits + 1,
            first.profile.direct_numeric_factorizations
        );
    }

    #[test]
    fn newton_square_is_reproducible_and_uses_explicit_fallback_policy() {
        let mut problem = nonlinear_square_problem();
        problem.options.nonlinear.algorithm = NonlinearAlgorithm::Newton;
        problem.options.nonlinear.newton_fallback_to_picard = false;
        let first = solve(&problem).unwrap();
        let second = solve(&problem).unwrap();
        assert_eq!(first.az_nodal, second.az_nodal);
        assert_eq!(
            first.convergence.nonlinear_residual_history,
            second.convergence.nonlinear_residual_history
        );
        assert_eq!(first.convergence.nonlinear_algorithm, "newton");
        assert!(first.profile.pcg.solve_calls > 0);
        assert_eq!(first.profile.csr_pattern_builds, 1);
        assert_eq!(first.profile.direct_symbolic_builds, 1);
        assert_eq!(first.profile.direct_pattern_mismatches, 0);
    }

    #[derive(Default)]
    struct CapturingDiagnostics {
        events: Mutex<Vec<NonlinearDiagnosticEvent>>,
    }

    impl DiagnosticsSink for CapturingDiagnostics {
        fn on_nonlinear_diagnostic(&self, event: NonlinearDiagnosticEvent) {
            self.events.lock().unwrap().push(event);
        }
    }

    #[test]
    fn newton_diagnostics_describe_the_accepted_candidate_state() {
        let mut problem = nonlinear_square_problem();
        problem.options.nonlinear.algorithm = NonlinearAlgorithm::Newton;
        problem.options.nonlinear.newton_fallback_to_picard = false;
        let diagnostics = CapturingDiagnostics::default();

        solve_with_sinks(&problem, &NoProgress, &diagnostics).unwrap();

        let events = diagnostics.events.lock().unwrap();
        assert!(!events.is_empty());
        for event in events.iter() {
            let MaterialModel::Nonlinear { bh_curve } = &problem.materials[event.material_id]
            else {
                panic!("Newton diagnostics should identify a nonlinear material");
            };
            let expected_target = bh_curve.secant_mu_r(event.b_mag_t);
            assert!(
                (event.target_mu_r - expected_target).abs()
                    <= expected_target.abs().max(1.0) * 1.0e-12,
                "event target {} does not match B={} T target {}",
                event.target_mu_r,
                event.b_mag_t,
                expected_target
            );
        }
    }

    #[test]
    fn rejects_invalid_mesh_material_and_boundary_indices() {
        let mut problem = square_problem();
        problem.mesh.triangles[0][2] = 99;
        assert!(problem.validate().unwrap_err().contains("out-of-range"));

        let mut problem = square_problem();
        problem.elements[0].material_id = 2;
        assert!(problem.validate().unwrap_err().contains("material_id"));

        let mut problem = square_problem();
        problem.boundaries.paired_nodes.push(PairedBoundary {
            nodes: [1, 3],
            kind: PairedBoundaryKind::Periodic,
        });
        assert!(problem.validate().unwrap_err().contains("overlaps"));
    }

    #[test]
    fn rejects_non_monotonic_bh_curve() {
        let mut problem = square_problem();
        problem.materials[0] = MaterialModel::Nonlinear {
            bh_curve: BhCurve {
                points: vec![
                    BhPoint {
                        b_t: 0.0,
                        h_a_per_m: 0.0,
                    },
                    BhPoint {
                        b_t: 1.0,
                        h_a_per_m: 100.0,
                    },
                    BhPoint {
                        b_t: 0.8,
                        h_a_per_m: 200.0,
                    },
                ],
                mu_r_min: 1.0,
                mu_r_max: 10_000.0,
            },
        };
        assert!(problem
            .validate()
            .unwrap_err()
            .contains("strictly increasing B"));
    }

    #[test]
    fn rejects_unknown_units_and_unanchored_systems() {
        let invalid_units = r#"{
            "kind":"magnetostatic_problem",
            "version":"1.0",
            "units":{"length":"inch"},
            "mesh":{"nodes":[[0,0],[1,0],[0,1]],"triangles":[[0,1,2]]},
            "materials":[{"kind":"linear","mu_r":1}],
            "elements":[{"material_id":0}],
            "boundaries":{"dirichlet_az_zero_nodes":[0]}
        }"#;
        let error = serde_json::from_str::<FieldProblemDocument>(invalid_units)
            .unwrap_err()
            .to_string();
        assert!(error.contains("unknown variant `inch`"));

        let mut problem = square_problem();
        problem.boundaries.dirichlet_az_zero_nodes.clear();
        assert!(problem.validate().unwrap_err().contains("Dirichlet"));
    }

    #[test]
    fn rejects_json_properties_outside_the_versioned_schema() {
        let unknown_option = r#"{
            "kind":"magnetostatic_problem",
            "version":"1.0",
            "units":{"length":"m"},
            "mesh":{"nodes":[[0,0],[1,0],[0,1]],"triangles":[[0,1,2]]},
            "materials":[{"kind":"linear","mu_r":1}],
            "elements":[{"material_id":0}],
            "boundaries":{"dirichlet_az_zero_nodes":[0]},
            "options":{"linear":{"tolrance":1e-8}}
        }"#;
        let error = serde_json::from_str::<FieldProblemDocument>(unknown_option)
            .unwrap_err()
            .to_string();
        assert!(error.contains("unknown field `tolrance`"));

        let unknown_material_property = unknown_option
            .replace(
                r#""options":{"linear":{"tolrance":1e-8}}"#,
                r#""options":{}"#,
            )
            .replace(
                r#"{"kind":"linear","mu_r":1}"#,
                r#"{"kind":"linear","mu_r":1,"label":"air"}"#,
            );
        let error = serde_json::from_str::<FieldProblemDocument>(&unknown_material_property)
            .unwrap_err()
            .to_string();
        assert!(error.contains("unknown field `label`"));
    }

    #[test]
    fn rejects_invalid_warm_start_shapes_and_values() {
        let mut problem = square_problem();
        problem.warm_start = Some(FieldWarmStart {
            az_nodal: vec![0.0; 3],
            mu_r_by_element: Vec::new(),
        });
        assert!(problem
            .validate()
            .unwrap_err()
            .contains("az_nodal length 3 does not match node count 4"));

        let mut problem = square_problem();
        problem.warm_start = Some(FieldWarmStart {
            az_nodal: vec![0.0, f64::NAN, 0.0, 0.0],
            mu_r_by_element: Vec::new(),
        });
        assert!(problem.validate().unwrap_err().contains("finite values"));

        let mut problem = square_problem();
        problem.warm_start = Some(FieldWarmStart {
            az_nodal: Vec::new(),
            mu_r_by_element: vec![1.0],
        });
        assert!(problem
            .validate()
            .unwrap_err()
            .contains("mu_r_by_element length 1 does not match element count 2"));

        let mut problem = square_problem();
        problem.warm_start = Some(FieldWarmStart {
            az_nodal: Vec::new(),
            mu_r_by_element: vec![1.0, f64::INFINITY],
        });
        assert!(problem
            .validate()
            .unwrap_err()
            .contains("finite values >= 1"));
    }

    #[test]
    fn batch_core_contracts_are_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}

        assert_send_sync::<MagnetostaticProblem>();
        assert_send_sync::<PreparedFieldSystem>();
    }

    #[test]
    fn capped_pcg_is_not_reported_as_converged() {
        let profile = PcgProfile {
            solve_calls: 1,
            max_iter_calls: 1,
            ..PcgProfile::default()
        };

        let error = ensure_pcg_converged(&profile, 3, 1.0e-12, "field")
            .expect_err("iteration-capped PCG must fail the generic solve");
        assert!(error.contains("failed to converge within 3 iterations"));
        assert!(error.contains("1.000e-12"));
    }

    #[test]
    fn emits_scale_warning_but_rejects_zero_span() {
        let mut problem = square_problem();
        for node in &mut problem.mesh.nodes_m {
            node[0] *= 2.0e3;
            node[1] *= 2.0e3;
        }
        assert_eq!(problem.validate().unwrap().len(), 1);

        let mut problem = square_problem();
        problem.mesh.nodes_m[2][1] = 0.0;
        problem.mesh.nodes_m[3][1] = 0.0;
        assert!(problem.validate().unwrap_err().contains("nonzero span"));
    }

    #[test]
    fn finite_nonzero_sub_guardrail_mesh_warns_and_solves() {
        let mut problem = square_problem();
        for node in &mut problem.mesh.nodes_m {
            node[0] *= 1.0e-6;
            node[1] *= 1.0e-6;
        }

        let warnings = problem
            .validate()
            .expect("tiny finite mesh should validate");
        assert_eq!(warnings.len(), 1);
        assert!(warnings[0].contains("verify units.length"));
        let solution = solve(&problem).expect("tiny finite mesh should solve");
        assert!(solution.az_nodal.iter().all(|value| value.is_finite()));
    }
}
