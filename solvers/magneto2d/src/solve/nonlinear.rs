use std::fs;
use std::path::PathBuf;

use serde::Serialize;

use crate::materials::MaterialProps;
use crate::mesh::Region;
use crate::motor::MotorConfig;
use crate::postprocess::ElementField;

use super::env_flag_enabled;

#[derive(Debug, Clone)]
pub(super) struct NonlinearWarmStart {
    mu_rel_by_element: Vec<f64>,
}

#[derive(Debug, Clone)]
pub(super) struct NonlinearUpdate {
    pub(super) raw_max_residual: f64,
    pub(super) applied_max_residual: f64,
    pub(super) worst_element: Option<usize>,
    pub(super) worst_update: Option<NonlinearWorstUpdate>,
}

#[derive(Debug, Clone, Serialize)]
pub(super) struct NonlinearWorstUpdate {
    pub(super) element_index: usize,
    pub(super) region: Region,
    pub(super) steel_grade: String,
    pub(super) b_x_t: f64,
    pub(super) b_y_t: f64,
    pub(super) b_mag_t: f64,
    pub(super) previous_mu_rel: f64,
    pub(super) target_mu_rel: f64,
    pub(super) relaxed_mu_rel: f64,
    pub(super) previous_nu: f64,
    pub(super) target_nu: f64,
    pub(super) relaxed_nu: f64,
    pub(super) raw_residual: f64,
    pub(super) relaxation: f64,
    pub(super) mu_rel_step_cap: f64,
    pub(super) capped: bool,
}

#[derive(Debug, Clone, Serialize)]
struct NonlinearElementGeometryDiagnostic {
    triangle_nodes: [usize; 3],
    triangle_xy_mm: [[f64; 2]; 3],
    centroid_mm: [f64; 2],
    area_mm2: f64,
    signed_area_mm2: f64,
    edge_lengths_mm: [f64; 3],
    min_edge_mm: f64,
    max_edge_mm: f64,
    min_angle_deg: f64,
    max_angle_deg: f64,
    aspect_ratio_longest_edge_to_shortest_altitude: f64,
}

#[derive(Debug, Clone, Serialize)]
pub(super) struct NonlinearIterationDiagnostic {
    iteration: usize,
    rotor_angle_deg: f64,
    convergence_residual: f64,
    convergence_threshold: f64,
    raw_max_residual: f64,
    applied_max_residual: f64,
    accepted_relaxation: f64,
    backtracking_attempts: usize,
    current_density_a_per_m2: f64,
    worst_update: NonlinearWorstUpdate,
    geometry: NonlinearElementGeometryDiagnostic,
}

#[derive(Debug, Clone, Serialize)]
pub(super) struct NonlinearDiagnosticsArtifact {
    pub(super) status: String,
    pub(super) reason: String,
    pub(super) rotor_angle_deg: f64,
    pub(super) nonlinear_enabled: bool,
    pub(super) max_iterations: usize,
    pub(super) convergence_threshold: f64,
    pub(super) residual_history: Vec<f64>,
    pub(super) iterations: Vec<NonlinearIterationDiagnostic>,
}

pub(super) struct NonlinearLoopOutput {
    pub(super) materials: Vec<MaterialProps>,
    pub(super) az: Vec<f64>,
    pub(super) fields: Vec<ElementField>,
    pub(super) residual_history: Vec<f64>,
    pub(super) diagnostics: Vec<NonlinearIterationDiagnostic>,
    pub(super) assembly_time_ms: u64,
    pub(super) solve_time_ms: u64,
}

#[derive(Debug, Clone, Copy)]
pub(super) struct NonlinearSolveConfig {
    pub(super) max_iterations: usize,
    pub(super) convergence_threshold: f64,
    pub(super) initial_relaxation: f64,
    pub(super) adaptive_picard: bool,
    pub(super) min_relaxation: f64,
    pub(super) max_relaxation: f64,
    pub(super) mu_rel_step_cap: f64,
    pub(super) backtracking_enabled: bool,
    pub(super) backtracking_growth_limit: f64,
    pub(super) backtracking_shrink: f64,
    pub(super) solver_kind: NonlinearSolverKind,
    pub(super) newton_initial_damping: f64,
    pub(super) newton_min_damping: f64,
    pub(super) newton_line_search_shrink: f64,
    pub(super) newton_line_search_accept_ratio: f64,
    pub(super) newton_convergence_threshold: f64,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub(super) enum NonlinearSolverKind {
    Picard,
    Newton,
}

impl NonlinearSolverKind {
    fn from_config(config: &MotorConfig) -> Self {
        let configured = config
            .solve_params
            .as_ref()
            .and_then(|params| params.nonlinear_solver.as_deref())
            .map(str::to_string)
            .or_else(|| std::env::var("MAGNETO2D_NONLINEAR_SOLVER").ok());
        match configured
            .as_deref()
            .map(str::trim)
            .map(str::to_ascii_lowercase)
            .as_deref()
        {
            Some("newton") | Some("damped_newton") => Self::Newton,
            _ => Self::Picard,
        }
    }

    pub(super) fn label(self) -> &'static str {
        match self {
            Self::Picard => "picard",
            Self::Newton => "newton",
        }
    }
}

impl NonlinearSolveConfig {
    pub(super) fn starting_relaxation(self) -> f64 {
        self.initial_relaxation
            .clamp(self.min_relaxation, self.max_relaxation)
    }

    pub(super) fn convergence_residual(self, raw_max_residual: f64) -> f64 {
        raw_max_residual * self.initial_relaxation
    }
}

fn triangle_geometry_diagnostic(
    mesh: &crate::mesh::TriMesh,
    element_index: usize,
) -> Option<NonlinearElementGeometryDiagnostic> {
    let tri = *mesh.triangles.get(element_index)?;
    let xy = [
        *mesh.nodes.get(tri[0])?,
        *mesh.nodes.get(tri[1])?,
        *mesh.nodes.get(tri[2])?,
    ];
    let signed_twice_area = (xy[1][0] - xy[0][0]) * (xy[2][1] - xy[0][1])
        - (xy[2][0] - xy[0][0]) * (xy[1][1] - xy[0][1]);
    let signed_area = 0.5 * signed_twice_area;
    let area = signed_area.abs();
    let edge = |a: [f64; 2], b: [f64; 2]| -> f64 {
        let dx = b[0] - a[0];
        let dy = b[1] - a[1];
        (dx * dx + dy * dy).sqrt()
    };
    let edges = [edge(xy[0], xy[1]), edge(xy[1], xy[2]), edge(xy[2], xy[0])];
    let min_edge = edges.iter().copied().fold(f64::INFINITY, f64::min);
    let max_edge = edges.iter().copied().fold(0.0, f64::max);
    let angle = |a: f64, b: f64, c: f64| -> f64 {
        if a <= 0.0 || b <= 0.0 {
            return 0.0;
        }
        let cos_theta = ((a * a + b * b - c * c) / (2.0 * a * b)).clamp(-1.0, 1.0);
        cos_theta.acos().to_degrees()
    };
    let angles = [
        angle(edges[2], edges[0], edges[1]),
        angle(edges[0], edges[1], edges[2]),
        angle(edges[1], edges[2], edges[0]),
    ];
    let min_angle = angles.iter().copied().fold(f64::INFINITY, f64::min);
    let max_angle = angles.iter().copied().fold(0.0, f64::max);
    let shortest_altitude = if max_edge > 0.0 {
        2.0 * area / max_edge
    } else {
        0.0
    };
    let aspect_ratio = if shortest_altitude > 0.0 {
        max_edge / shortest_altitude
    } else {
        f64::INFINITY
    };

    Some(NonlinearElementGeometryDiagnostic {
        triangle_nodes: tri,
        triangle_xy_mm: xy.map(|point| [point[0] * 1.0e3, point[1] * 1.0e3]),
        centroid_mm: [
            (xy[0][0] + xy[1][0] + xy[2][0]) / 3.0 * 1.0e3,
            (xy[0][1] + xy[1][1] + xy[2][1]) / 3.0 * 1.0e3,
        ],
        area_mm2: area * 1.0e6,
        signed_area_mm2: signed_area * 1.0e6,
        edge_lengths_mm: edges.map(|edge| edge * 1.0e3),
        min_edge_mm: min_edge * 1.0e3,
        max_edge_mm: max_edge * 1.0e3,
        min_angle_deg: min_angle,
        max_angle_deg: max_angle,
        aspect_ratio_longest_edge_to_shortest_altitude: aspect_ratio,
    })
}

pub(super) fn nonlinear_iteration_diagnostic(
    mesh: &crate::mesh::TriMesh,
    j_z: &[f64],
    update: &NonlinearUpdate,
    iteration: usize,
    rotor_angle_deg: f64,
    convergence_residual: f64,
    convergence_threshold: f64,
    accepted_relaxation: f64,
    backtracking_attempts: usize,
) -> Option<NonlinearIterationDiagnostic> {
    let worst_update = update.worst_update.clone()?;
    let geometry = triangle_geometry_diagnostic(mesh, worst_update.element_index)?;
    let current_density_a_per_m2 = j_z.get(worst_update.element_index).copied().unwrap_or(0.0);
    Some(NonlinearIterationDiagnostic {
        iteration,
        rotor_angle_deg,
        convergence_residual,
        convergence_threshold,
        raw_max_residual: update.raw_max_residual,
        applied_max_residual: update.applied_max_residual,
        accepted_relaxation,
        backtracking_attempts,
        current_density_a_per_m2,
        worst_update,
        geometry,
    })
}

pub(super) fn nonlinear_diagnostics_path() -> Option<PathBuf> {
    std::env::var("MAGNETO2D_NONLINEAR_DIAGNOSTICS_PATH")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

pub(super) fn write_nonlinear_diagnostics_artifact(
    path: &PathBuf,
    artifact: &NonlinearDiagnosticsArtifact,
) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|err| format!("failed to create nonlinear diagnostics dir: {err}"))?;
        }
    }
    let raw = serde_json::to_string_pretty(artifact)
        .map_err(|err| format!("failed to serialize nonlinear diagnostics: {err}"))?;
    fs::write(path, raw).map_err(|err| {
        format!(
            "failed to write nonlinear diagnostics {}: {err}",
            path.display()
        )
    })
}

fn is_steel_region(region: Region) -> bool {
    matches!(
        region,
        Region::RotorCore | Region::StatorTooth | Region::StatorYoke
    )
}

pub(super) fn build_nonlinear_warm_start(materials: &[MaterialProps]) -> NonlinearWarmStart {
    NonlinearWarmStart {
        mu_rel_by_element: materials.iter().map(|material| material.mu_rel).collect(),
    }
}

pub(super) fn apply_nonlinear_warm_start(
    materials: &mut [MaterialProps],
    regions: &[Region],
    warm_start: Option<&NonlinearWarmStart>,
) {
    let Some(warm_start) = warm_start else {
        return;
    };
    if warm_start.mu_rel_by_element.len() != materials.len() {
        return;
    }

    for ((material, region), warm_mu_rel) in materials
        .iter_mut()
        .zip(regions.iter())
        .zip(warm_start.mu_rel_by_element.iter())
    {
        if is_steel_region(*region) && warm_mu_rel.is_finite() {
            material.with_mu_rel(*warm_mu_rel);
        }
    }
}

pub(super) fn default_nonlinear_tol_for_quality(solve_quality: Option<&str>) -> f64 {
    match solve_quality {
        Some("quick") | Some("standard") => 0.075,
        Some("fine") => 0.05,
        _ => 0.05,
    }
}

fn default_nonlinear_tol(config: &MotorConfig) -> f64 {
    default_nonlinear_tol_for_quality(
        config
            .solve_params
            .as_ref()
            .and_then(|params| params.solve_quality.as_deref()),
    )
}

pub(super) fn resolve_nonlinear_solve_config(
    config: &MotorConfig,
    nonlinear_enabled: bool,
) -> NonlinearSolveConfig {
    let configured_max_nonlinear_iterations = config
        .solve_params
        .as_ref()
        .and_then(|params| params.max_nonlinear_iterations)
        .unwrap_or(100)
        .max(1);
    let max_iterations = if nonlinear_enabled {
        // Default 100 (was 60, was 20). With RELAX=0.1 the real M-19 curve
        // converges in ~30-50 Picard iterations on 4p12s tooth-tip elements
        // (q=1 distributed), but higher-pole-count concentrated-winding
        // geometries (8p12s, q=0.5) hit tighter local saturation patches
        // and routinely need 60-90 iters. MAGNETO2D_NONLINEAR_MAX_ITER
        // overrides for probe sweeps.
        let env_max = std::env::var("MAGNETO2D_NONLINEAR_MAX_ITER")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .filter(|&n| n >= 1);
        env_max.unwrap_or(configured_max_nonlinear_iterations)
    } else {
        1
    };
    let convergence_threshold = std::env::var("MAGNETO2D_NONLINEAR_TOL")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&t| t > 0.0 && t < 1.0)
        .unwrap_or_else(|| default_nonlinear_tol(config));
    let initial_relaxation = std::env::var("MAGNETO2D_NONLINEAR_RELAX")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&r| r > 0.0 && r <= 1.0)
        .unwrap_or(0.1);
    let adaptive_picard =
        nonlinear_enabled && env_flag_enabled("MAGNETO2D_NONLINEAR_ADAPTIVE_PICARD", false);
    let min_relaxation = std::env::var("MAGNETO2D_NONLINEAR_MIN_RELAX")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&r| r > 0.0 && r <= initial_relaxation)
        .unwrap_or(0.05_f64.min(initial_relaxation));
    let max_relaxation = std::env::var("MAGNETO2D_NONLINEAR_MAX_RELAX")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&r| r >= initial_relaxation && r <= 1.0)
        .unwrap_or(0.2_f64.max(initial_relaxation));
    let mu_rel_step_cap = std::env::var("MAGNETO2D_NONLINEAR_MU_STEP_CAP")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&cap| cap.is_finite() && cap >= 1.0)
        .unwrap_or(1.5);
    let backtracking_enabled =
        nonlinear_enabled && env_flag_enabled("MAGNETO2D_NONLINEAR_BACKTRACKING", false);
    let backtracking_growth_limit = std::env::var("MAGNETO2D_NONLINEAR_BACKTRACK_GROWTH")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&limit| limit.is_finite() && limit >= 1.0)
        .unwrap_or(1.05);
    let backtracking_shrink = std::env::var("MAGNETO2D_NONLINEAR_BACKTRACK_SHRINK")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&shrink| shrink.is_finite() && shrink > 0.0 && shrink < 1.0)
        .unwrap_or(0.5);
    let solver_kind = NonlinearSolverKind::from_config(config);
    let newton_initial_damping = std::env::var("MAGNETO2D_NEWTON_DAMPING")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&damping| damping.is_finite() && damping > 0.0 && damping <= 1.0)
        .unwrap_or(1.0);
    let newton_min_damping = std::env::var("MAGNETO2D_NEWTON_MIN_DAMPING")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&damping| {
            damping.is_finite() && damping > 0.0 && damping <= newton_initial_damping
        })
        .unwrap_or((1.0 / 1024.0_f64).min(newton_initial_damping));
    let newton_line_search_shrink = std::env::var("MAGNETO2D_NEWTON_LINE_SEARCH_SHRINK")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|&shrink| shrink.is_finite() && shrink > 0.0 && shrink < 1.0)
        .unwrap_or(0.5);
    let newton_line_search_accept_ratio =
        std::env::var("MAGNETO2D_NEWTON_LINE_SEARCH_ACCEPT_RATIO")
            .ok()
            .and_then(|value| value.parse::<f64>().ok())
            .filter(|ratio| ratio.is_finite() && *ratio > 0.0 && *ratio <= 1.0)
            .unwrap_or(0.999);
    let newton_convergence_threshold = std::env::var("MAGNETO2D_NEWTON_TOL")
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .filter(|tol| tol.is_finite() && *tol > 0.0 && *tol <= convergence_threshold)
        .unwrap_or(convergence_threshold * 0.8);

    NonlinearSolveConfig {
        max_iterations,
        convergence_threshold,
        initial_relaxation,
        adaptive_picard,
        min_relaxation,
        max_relaxation,
        mu_rel_step_cap,
        backtracking_enabled,
        backtracking_growth_limit,
        backtracking_shrink,
        solver_kind,
        newton_initial_damping,
        newton_min_damping,
        newton_line_search_shrink,
        newton_line_search_accept_ratio,
        newton_convergence_threshold,
    }
}

/// Resolve Newton current-continuation policy once in the motor adapter.
/// The returned values are ordinary solve data; the Newton loop itself does
/// not read process-global environment state.
pub(super) fn resolve_newton_current_scales(current_densities: &[f64]) -> Vec<f64> {
    if let Ok(raw) = std::env::var("MAGNETO2D_NEWTON_CURRENT_STAGES") {
        let mut stages: Vec<f64> = raw
            .split(',')
            .filter_map(|part| part.trim().parse::<f64>().ok())
            .filter(|scale| scale.is_finite() && *scale > 0.0 && *scale <= 1.0)
            .collect();
        stages.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        stages.dedup_by(|a, b| (*a - *b).abs() < 1.0e-12);
        if !stages.iter().any(|scale| (*scale - 1.0).abs() < 1.0e-12) {
            stages.push(1.0);
        }
        if !stages.is_empty() {
            return stages;
        }
    }

    let continuation_disabled = std::env::var("MAGNETO2D_NEWTON_CURRENT_CONTINUATION")
        .ok()
        .map(|value| {
            let normalized = value.trim().to_ascii_lowercase();
            normalized == "0" || normalized == "false" || normalized == "no" || normalized == "off"
        })
        .unwrap_or(false);
    let has_current = current_densities.iter().any(|value| value.abs() > 0.0);
    if continuation_disabled || !has_current {
        vec![1.0]
    } else {
        vec![0.25, 0.5, 0.75, 1.0]
    }
}
