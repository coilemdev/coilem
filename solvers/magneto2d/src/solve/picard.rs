use crate::materials::{MaterialProps, MU_0};
use std::time::Instant;

use crate::mesh::Region;
use crate::motor::MotorConfig;
use crate::postprocess::{compute_element_fields, ElementField};

use super::nonlinear::{
    nonlinear_iteration_diagnostic, NonlinearIterationDiagnostic, NonlinearLoopOutput,
    NonlinearSolveConfig, NonlinearUpdate, NonlinearWorstUpdate,
};
use super::types::SolveProfile;
use super::{
    elapsed_ms, emit_angle_iteration_progress, emit_angle_solve_context, solve_linear_system,
    AngleProgressContext, MotorLinearSolvePolicy, SolveMatrixPattern, LINEAR_SOLVE_TIGHT_TOL,
};

#[derive(Debug, Clone, Copy)]
pub(super) struct PicardRelaxationState {
    pub(super) relaxation: f64,
    pub(super) previous_raw_residual: Option<f64>,
    consecutive_raw_residual_drops: usize,
}

impl PicardRelaxationState {
    pub(super) fn new(config: NonlinearSolveConfig) -> Self {
        Self {
            relaxation: config.starting_relaxation(),
            previous_raw_residual: None,
            consecutive_raw_residual_drops: 0,
        }
    }

    pub(super) fn update_after_residual(
        &mut self,
        raw_max_residual: f64,
        config: NonlinearSolveConfig,
    ) {
        if let Some(previous_raw) = self.previous_raw_residual {
            if raw_max_residual > previous_raw * 1.05 {
                self.relaxation = (self.relaxation * 0.55).max(config.min_relaxation);
                self.consecutive_raw_residual_drops = 0;
            } else if raw_max_residual < previous_raw * 0.72 {
                self.consecutive_raw_residual_drops += 1;
                if self.consecutive_raw_residual_drops >= 2 {
                    self.relaxation = (self.relaxation * 1.25).min(config.max_relaxation);
                    self.consecutive_raw_residual_drops = 0;
                }
            } else {
                self.consecutive_raw_residual_drops = 0;
            }
        }
        self.previous_raw_residual = Some(raw_max_residual);
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn run_picard_nonlinear_loop(
    solve_mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
    _config: &MotorConfig,
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
    nonlinear_material_labels: &[String],
    j_z: &[f64],
    mut materials: Vec<MaterialProps>,
    magnet_fractions: Option<&[f64]>,
    az_warm_start: Option<&[f64]>,
    progress: Option<&AngleProgressContext<'_>>,
    rotor_angle_rad: f64,
    nonlinear_enabled: bool,
    nonlinear_config: NonlinearSolveConfig,
    diagnostics_enabled: bool,
    residual_history: &mut Vec<f64>,
    nonlinear_iteration_diagnostics: &mut Vec<NonlinearIterationDiagnostic>,
    linear_policy: MotorLinearSolvePolicy,
    matrix_pattern: Option<&SolveMatrixPattern>,
    mut profile: Option<&mut SolveProfile>,
) -> Result<NonlinearLoopOutput, String> {
    let mut picard_state = PicardRelaxationState::new(nonlinear_config);
    let mut total_assembly_ms = 0;
    let mut total_solve_ms = 0;
    let mut material_checkpoint = materials.clone();
    let mut last_az: Option<Vec<f64>> = az_warm_start
        .filter(|guess| guess.len() == solve_mesh.nodes.len())
        .map(|guess| guess.to_vec());
    let mut last_fields: Option<Vec<ElementField>> = None;

    // Adaptive inner tolerance: intermediate Picard solves only feed the
    // secant mu update (outer tolerance 0.05-0.075), so they run at a loose
    // PCG tolerance; one tight, warm-started solve after convergence
    // restores full field accuracy for postprocessing. Linear-material
    // solves (nonlinear disabled) are final by definition and stay tight.
    let loose_inner_tol = nonlinear_enabled && linear_policy.adaptive_inner_tolerance;
    let loose_tol_value = linear_policy.loose_tolerance;
    let mut converged = false;

    for iteration in 0..nonlinear_config.max_iterations {
        emit_angle_solve_context(progress, iteration + 1, nonlinear_config.max_iterations);
        let inner_tol = if loose_inner_tol {
            loose_tol_value
        } else {
            LINEAR_SOLVE_TIGHT_TOL
        };
        let (az, asm_ms, solve_ms) = solve_linear_system(
            solve_mesh,
            n_pole_pitches,
            &materials,
            j_z,
            last_az.as_deref(),
            magnet_fractions,
            matrix_pattern,
            inner_tol,
            linear_policy,
            profile.as_deref_mut(),
        )?;
        total_assembly_ms += asm_ms;
        total_solve_ms += solve_ms;
        eprintln!("  asm={asm_ms}ms solve={solve_ms}ms");

        let field_start = Instant::now();
        let fields = compute_element_fields(solve_mesh, &az);
        if let Some(profile) = profile.as_deref_mut() {
            profile.field_compute_ms += elapsed_ms(field_start);
        }

        if !nonlinear_enabled {
            last_az = Some(az);
            last_fields = Some(fields);
            break;
        }

        let current_materials = materials.clone();
        let mut probe_materials = materials.clone();
        let material_start = Instant::now();
        let probe_update = update_nonlinear_materials(
            &mut probe_materials,
            &fields,
            &solve_mesh.regions,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            nonlinear_material_labels,
            picard_state.relaxation,
            nonlinear_config.mu_rel_step_cap,
        );
        if let Some(profile) = profile.as_deref_mut() {
            profile.material_update_ms += elapsed_ms(material_start);
        }
        let (accepted_relaxation, backtracking_attempts) = backtracked_relaxation(
            picard_state.previous_raw_residual,
            probe_update.raw_max_residual,
            picard_state.relaxation,
            nonlinear_config,
        );
        if backtracking_attempts > 0 {
            eprintln!(
                "  nonlinear_backtrack_reject: raw_residual={:.6} previous={:.6} relax {:.4}->{:.4} attempts={}",
                probe_update.raw_max_residual,
                picard_state.previous_raw_residual.unwrap_or(0.0),
                picard_state.relaxation,
                accepted_relaxation,
                backtracking_attempts,
            );
            picard_state.relaxation = accepted_relaxation;
            materials = material_checkpoint.clone();
            continue;
        }

        let update = {
            material_checkpoint = current_materials;
            materials = probe_materials;
            probe_update
        };
        let convergence_residual = nonlinear_config.convergence_residual(update.raw_max_residual);
        residual_history.push(convergence_residual);
        if diagnostics_enabled {
            if let Some(diagnostic) = nonlinear_iteration_diagnostic(
                solve_mesh,
                j_z,
                &update,
                iteration + 1,
                rotor_angle_rad.to_degrees(),
                convergence_residual,
                nonlinear_config.convergence_threshold,
                accepted_relaxation,
                backtracking_attempts,
            ) {
                nonlinear_iteration_diagnostics.push(diagnostic);
            }
        }

        last_az = Some(az);
        last_fields = Some(fields);

        emit_angle_iteration_progress(
            progress,
            iteration + 1,
            nonlinear_config.max_iterations,
            asm_ms,
            solve_ms,
            convergence_residual,
            nonlinear_config.convergence_threshold,
            update.worst_element,
        );

        if convergence_residual <= nonlinear_config.convergence_threshold {
            converged = true;
            break;
        }

        if nonlinear_config.adaptive_picard {
            picard_state.update_after_residual(update.raw_max_residual, nonlinear_config);
        }

        if iteration + 1 == nonlinear_config.max_iterations {
            return Err(format!(
                "nonlinear solve failed to converge after {} iterations at rotor_angle_deg={:.3}; residual_history={:?}; worst_element={:?}",
                nonlinear_config.max_iterations,
                rotor_angle_rad.to_degrees(),
                residual_history,
                update.worst_element,
            ));
        }
    }

    // Final tight solve: the loop's last iterate was solved at the loose
    // tolerance, so polish it to LINEAR_SOLVE_TIGHT_TOL with the converged
    // A_z as warm start — typically a handful of PCG iterations — and
    // recompute fields so postprocess sees fully converged values.
    //
    // Use material_checkpoint (the materials the last loop solve actually
    // used), not `materials` (which already absorbed the final mu update):
    // the fixed-tight path returns fields consistent with the pre-update
    // materials, and matching that keeps loose-mode waveforms bit-comparable
    // instead of drifting by one extra Picard half-step.
    if loose_inner_tol && converged {
        let (az, asm_ms, solve_ms) = solve_linear_system(
            solve_mesh,
            n_pole_pitches,
            &material_checkpoint,
            j_z,
            last_az.as_deref(),
            magnet_fractions,
            matrix_pattern,
            LINEAR_SOLVE_TIGHT_TOL,
            linear_policy,
            profile.as_deref_mut(),
        )?;
        total_assembly_ms += asm_ms;
        total_solve_ms += solve_ms;
        eprintln!("  final_tight_solve: asm={asm_ms}ms solve={solve_ms}ms");

        let field_start = Instant::now();
        let fields = compute_element_fields(solve_mesh, &az);
        if let Some(profile) = profile.as_deref_mut() {
            profile.field_compute_ms += elapsed_ms(field_start);
        }
        last_az = Some(az);
        last_fields = Some(fields);
    }

    let az = last_az.ok_or_else(|| "solver did not produce an A_z solution".to_string())?;
    let fields = last_fields.ok_or_else(|| "solver did not produce element fields".to_string())?;
    Ok(NonlinearLoopOutput {
        materials,
        az,
        fields,
        residual_history: std::mem::take(residual_history),
        diagnostics: std::mem::take(nonlinear_iteration_diagnostics),
        assembly_time_ms: total_assembly_ms,
        solve_time_ms: total_solve_ms,
    })
}

pub(super) fn update_nonlinear_materials(
    materials: &mut [MaterialProps],
    fields: &[ElementField],
    regions: &[Region],
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
    nonlinear_material_labels: &[String],
    relaxation: f64,
    mu_rel_step_cap: f64,
) -> NonlinearUpdate {
    let mut raw_max_residual = 0.0;
    let mut applied_max_residual = 0.0;
    let mut worst_element = None;
    let mut worst_update = None;

    for (idx, (((material, field), region), curve_id)) in materials
        .iter_mut()
        .zip(fields.iter())
        .zip(regions.iter())
        .zip(nonlinear_curve_ids_by_element.iter())
        .enumerate()
    {
        let Some(curve_id) = *curve_id else {
            continue;
        };
        let Some(curve) = nonlinear_curves.get(curve_id) else {
            continue;
        };
        let steel_grade = nonlinear_material_labels
            .get(curve_id)
            .map(String::as_str)
            .unwrap_or("nonlinear_material");

        let previous_mu = material.mu_rel.max(1.0);
        let previous_nu = material.nu;
        let material_update = crate::field::secant_material_update(
            curve,
            field.b_mag,
            previous_mu,
            relaxation,
            mu_rel_step_cap,
        );
        if material_update.raw_residual > raw_max_residual {
            worst_element = Some(idx);
            worst_update = Some(NonlinearWorstUpdate {
                element_index: idx,
                region: *region,
                steel_grade: steel_grade.to_string(),
                b_x_t: field.bx,
                b_y_t: field.by,
                b_mag_t: field.b_mag,
                previous_mu_rel: previous_mu,
                target_mu_rel: material_update.target_mu_r,
                relaxed_mu_rel: material_update.relaxed_mu_r,
                previous_nu,
                target_nu: 1.0 / (MU_0 * material_update.target_mu_r.max(1.0)),
                relaxed_nu: 1.0 / (MU_0 * material_update.relaxed_mu_r),
                raw_residual: material_update.raw_residual,
                relaxation,
                mu_rel_step_cap,
                capped: material_update.capped,
            });
        }
        raw_max_residual = f64::max(raw_max_residual, material_update.raw_residual);
        applied_max_residual = f64::max(applied_max_residual, material_update.applied_residual);
        material.with_mu_rel(material_update.relaxed_mu_r);
    }

    NonlinearUpdate {
        raw_max_residual,
        applied_max_residual,
        worst_element,
        worst_update,
    }
}

pub(super) fn backtracked_relaxation(
    previous_raw_residual: Option<f64>,
    current_raw_residual: f64,
    current_relaxation: f64,
    config: NonlinearSolveConfig,
) -> (f64, usize) {
    if !config.backtracking_enabled {
        return (current_relaxation, 0);
    }
    let Some(previous_raw_residual) = previous_raw_residual else {
        return (current_relaxation, 0);
    };
    if current_raw_residual <= previous_raw_residual * config.backtracking_growth_limit {
        return (current_relaxation, 0);
    }

    let mut relaxation = current_relaxation;
    let mut attempts = 0;
    while relaxation > config.min_relaxation {
        let next = (relaxation * config.backtracking_shrink).max(config.min_relaxation);
        if (next - relaxation).abs() < 1.0e-15 {
            break;
        }
        relaxation = next;
        attempts += 1;
        if relaxation <= config.min_relaxation {
            break;
        }
    }
    (relaxation, attempts)
}

#[cfg(test)]
pub(super) fn cap_mu_rel_step(previous_mu: f64, candidate_mu: f64, step_cap: f64) -> f64 {
    let previous_mu = previous_mu.max(1.0);
    let step_cap = step_cap.max(1.0);
    candidate_mu
        .clamp(previous_mu / step_cap, previous_mu * step_cap)
        .max(1.0)
}
