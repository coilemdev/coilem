use std::time::Instant;

use crate::assembly::{assemble_source, assemble_stiffness, triangle_gradients};
use crate::materials::{MaterialProps, MU_0};
use crate::motor::MotorConfig;
use crate::postprocess::{compute_element_fields, ElementField};
use crate::sparse::{
    pcg_solve_with_guess_options, pcg_solve_with_guess_options_profiled, CooMatrix,
    ElementCsrAssemblyPattern,
};

use super::nonlinear::{nonlinear_iteration_diagnostic, NonlinearLoopOutput, NonlinearSolveConfig};
use super::picard::update_nonlinear_materials;
use super::types::SolveProfile;
use super::{
    apply_model_constraints, elapsed_ms, emit_angle_iteration_progress, emit_angle_solve_context,
    solve_linear_system, AngleProgressContext, MotorLinearSolvePolicy, SolveMatrixPattern,
};

struct NewtonAcceptedStep {
    az: Vec<f64>,
    fields: Vec<ElementField>,
    materials: Vec<MaterialProps>,
    residual: f64,
    damping: f64,
    attempts: usize,
}

fn nonlinear_nu_and_tangent(curve: &crate::field::BhCurve, b_t: f64) -> (f64, f64) {
    let mu = curve.secant_mu_r(b_t);
    let nu = 1.0 / (MU_0 * mu.max(1.0));
    let delta = (b_t.abs() * 1.0e-3).max(1.0e-4);
    let b_low = (b_t - delta).max(0.0);
    let b_high = b_t + delta;
    if b_high <= b_low {
        return (nu, 0.0);
    }
    let mu_low = curve.secant_mu_r(b_low).max(1.0);
    let mu_high = curve.secant_mu_r(b_high).max(1.0);
    let nu_low = 1.0 / (MU_0 * mu_low);
    let nu_high = 1.0 / (MU_0 * mu_high);
    (nu, (nu_high - nu_low) / (b_high - b_low))
}

fn assemble_newton_tangent(
    mesh: &crate::mesh::TriMesh,
    materials: &[MaterialProps],
    fields: &[ElementField],
    az: &[f64],
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
) -> CooMatrix {
    let mut k = CooMatrix::new(mesh.nodes.len());

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let [i, j, m] = *tri;
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }

        let (nu, dnu_db) = nonlinear_curve_ids_by_element[tri_idx]
            .and_then(|curve_id| nonlinear_curves.get(curve_id))
            .map(|curve| nonlinear_nu_and_tangent(curve, fields[tri_idx].b_mag))
            .unwrap_or((materials[tri_idx].nu, 0.0));

        let da_dx = az[i] * grad[0][0] + az[j] * grad[1][0] + az[m] * grad[2][0];
        let da_dy = az[i] * grad[0][1] + az[j] * grad[1][1] + az[m] * grad[2][1];
        let b_mag = fields[tri_idx].b_mag.max(1.0e-12);
        let tangent_scale = dnu_db / b_mag;
        let grad_a_dot = [
            da_dx * grad[0][0] + da_dy * grad[0][1],
            da_dx * grad[1][0] + da_dy * grad[1][1],
            da_dx * grad[2][0] + da_dy * grad[2][1],
        ];
        let local_nodes = [i, j, m];
        for a in 0..3 {
            for b in 0..3 {
                let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                let val = area * (nu * dot + tangent_scale * grad_a_dot[a] * grad_a_dot[b]);
                if val.is_finite() && val.abs() > 1e-30 {
                    k.add(local_nodes[a], local_nodes[b], val);
                }
            }
        }
    }

    k
}

fn assemble_newton_tangent_with_pattern(
    pattern: &ElementCsrAssemblyPattern,
    mesh: &crate::mesh::TriMesh,
    materials: &[MaterialProps],
    fields: &[ElementField],
    az: &[f64],
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
) -> crate::sparse::CsrMatrix {
    let mut k = pattern.zero_matrix();

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let [i, j, m] = *tri;
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }

        let (nu, dnu_db) = nonlinear_curve_ids_by_element[tri_idx]
            .and_then(|curve_id| nonlinear_curves.get(curve_id))
            .map(|curve| nonlinear_nu_and_tangent(curve, fields[tri_idx].b_mag))
            .unwrap_or((materials[tri_idx].nu, 0.0));

        let da_dx = az[i] * grad[0][0] + az[j] * grad[1][0] + az[m] * grad[2][0];
        let da_dy = az[i] * grad[0][1] + az[j] * grad[1][1] + az[m] * grad[2][1];
        let b_mag = fields[tri_idx].b_mag.max(1.0e-12);
        let tangent_scale = dnu_db / b_mag;
        let grad_a_dot = [
            da_dx * grad[0][0] + da_dy * grad[0][1],
            da_dx * grad[1][0] + da_dy * grad[1][1],
            da_dx * grad[2][0] + da_dy * grad[2][1],
        ];
        let slots = pattern.element_slots(tri_idx);
        for a in 0..3 {
            for b in 0..3 {
                let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                let val = area * (nu * dot + tangent_scale * grad_a_dot[a] * grad_a_dot[b]);
                if val.is_finite() && val.abs() > 1e-30 {
                    k.values[slots[a][b]] += val;
                }
            }
        }
    }

    k
}

fn nonlinear_residual_norm(
    mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
    materials: &[MaterialProps],
    current_densities: &[f64],
    az: &[f64],
    magnet_fractions: Option<&[f64]>,
    matrix_pattern: Option<&SolveMatrixPattern>,
) -> f64 {
    let mut f = assemble_source(mesh, materials, current_densities, magnet_fractions);
    let k_csr = if let Some(matrix_pattern) = matrix_pattern {
        let mut k_csr = matrix_pattern.assemble_stiffness(mesh, materials);
        matrix_pattern.add_constraint_terms(&mut k_csr);
        matrix_pattern.apply_dirichlet(&mut k_csr, &mut f);
        k_csr
    } else {
        let mut k_coo = assemble_stiffness(mesh, materials);
        let bc_nodes = apply_model_constraints(&mut k_coo, &mut f, mesh, n_pole_pitches);
        let mut k_csr = k_coo.to_csr();
        k_csr.apply_dirichlet(&mut f, &bc_nodes);
        k_csr
    };
    let mut ka = vec![0.0; az.len()];
    k_csr.mul_vec(az, &mut ka);
    let residual_norm = ka
        .iter()
        .zip(f.iter())
        .map(|(lhs, rhs)| (lhs - rhs).powi(2))
        .sum::<f64>()
        .sqrt();
    let rhs_norm = f.iter().map(|value| value * value).sum::<f64>().sqrt();
    residual_norm / rhs_norm.max(1.0e-30)
}

fn solve_newton_correction(
    mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
    materials: &[MaterialProps],
    current_densities: &[f64],
    fields: &[ElementField],
    az: &[f64],
    magnet_fractions: Option<&[f64]>,
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
    matrix_pattern: Option<&SolveMatrixPattern>,
    linear_policy: MotorLinearSolvePolicy,
    mut profile: Option<&mut SolveProfile>,
) -> Result<(Vec<f64>, f64, u64, u64), String> {
    let asm_start = Instant::now();
    if let Some(profile) = profile.as_deref_mut() {
        profile.newton_correction_calls += 1;
    }

    let source_start = Instant::now();
    let mut f = assemble_source(mesh, materials, current_densities, magnet_fractions);
    if let Some(profile) = profile.as_deref_mut() {
        profile.linear_source_assembly_ms += elapsed_ms(source_start);
    }

    let mut residual_k = if let Some(matrix_pattern) = matrix_pattern {
        let stiffness_start = Instant::now();
        let residual_k = matrix_pattern.assemble_stiffness(mesh, materials);
        let stiffness_ms = elapsed_ms(stiffness_start);
        if let Some(profile) = profile.as_deref_mut() {
            profile.linear_stiffness_assembly_ms += stiffness_ms;
            profile.direct_csr_refill_ms += stiffness_ms;
        }
        residual_k
    } else {
        let stiffness_start = Instant::now();
        let mut residual_k = assemble_stiffness(mesh, materials);
        if let Some(profile) = profile.as_deref_mut() {
            profile.linear_stiffness_assembly_ms += elapsed_ms(stiffness_start);
        }

        let constraint_start = Instant::now();
        let bc_nodes = apply_model_constraints(&mut residual_k, &mut f, mesh, n_pole_pitches);
        if let Some(profile) = profile.as_deref_mut() {
            profile.constraint_apply_ms += elapsed_ms(constraint_start);
        }

        let csr_start = Instant::now();
        let mut residual_k = residual_k.to_csr();
        if let Some(profile) = profile.as_deref_mut() {
            profile.csr_conversion_ms += elapsed_ms(csr_start);
        }

        let dirichlet_start = Instant::now();
        residual_k.apply_dirichlet(&mut f, &bc_nodes);
        if let Some(profile) = profile.as_deref_mut() {
            profile.dirichlet_apply_ms += elapsed_ms(dirichlet_start);
        }
        residual_k
    };

    if let Some(matrix_pattern) = matrix_pattern {
        let constraint_start = Instant::now();
        matrix_pattern.add_constraint_terms(&mut residual_k);
        if let Some(profile) = profile.as_deref_mut() {
            profile.constraint_apply_ms += elapsed_ms(constraint_start);
        }

        let dirichlet_start = Instant::now();
        matrix_pattern.apply_dirichlet(&mut residual_k, &mut f);
        if let Some(profile) = profile.as_deref_mut() {
            profile.dirichlet_apply_ms += elapsed_ms(dirichlet_start);
        }
    }

    let residual_eval_start = Instant::now();
    let mut ka = vec![0.0; az.len()];
    residual_k.mul_vec(az, &mut ka);
    let mut rhs = vec![0.0; az.len()];
    for i in 0..az.len() {
        rhs[i] = f[i] - ka[i];
    }
    let residual_norm = rhs.iter().map(|value| value * value).sum::<f64>().sqrt()
        / f.iter()
            .map(|value| value * value)
            .sum::<f64>()
            .sqrt()
            .max(1.0e-30);
    if let Some(profile) = profile.as_deref_mut() {
        profile.residual_eval_ms += elapsed_ms(residual_eval_start);
    }

    let mut tangent_rhs = rhs;
    let mut tangent = if let Some(matrix_pattern) = matrix_pattern {
        let tangent_start = Instant::now();
        let tangent = assemble_newton_tangent_with_pattern(
            matrix_pattern.csr_pattern(),
            mesh,
            materials,
            fields,
            az,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
        );
        let tangent_ms = elapsed_ms(tangent_start);
        if let Some(profile) = profile.as_deref_mut() {
            profile.tangent_assembly_ms += tangent_ms;
            profile.direct_csr_refill_ms += tangent_ms;
        }
        tangent
    } else {
        let tangent_start = Instant::now();
        let mut tangent = assemble_newton_tangent(
            mesh,
            materials,
            fields,
            az,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
        );
        if let Some(profile) = profile.as_deref_mut() {
            profile.tangent_assembly_ms += elapsed_ms(tangent_start);
        }
        let tangent_constraint_start = Instant::now();
        let tangent_bc_nodes =
            apply_model_constraints(&mut tangent, &mut tangent_rhs, mesh, n_pole_pitches);
        if let Some(profile) = profile.as_deref_mut() {
            profile.constraint_apply_ms += elapsed_ms(tangent_constraint_start);
        }

        let tangent_csr_start = Instant::now();
        let mut tangent = tangent.to_csr();
        if let Some(profile) = profile.as_deref_mut() {
            profile.csr_conversion_ms += elapsed_ms(tangent_csr_start);
        }

        let tangent_dirichlet_start = Instant::now();
        tangent.apply_dirichlet(&mut tangent_rhs, &tangent_bc_nodes);
        if let Some(profile) = profile.as_deref_mut() {
            profile.dirichlet_apply_ms += elapsed_ms(tangent_dirichlet_start);
        }
        tangent
    };

    if let Some(matrix_pattern) = matrix_pattern {
        let tangent_constraint_start = Instant::now();
        matrix_pattern.add_constraint_terms(&mut tangent);
        if let Some(profile) = profile.as_deref_mut() {
            profile.constraint_apply_ms += elapsed_ms(tangent_constraint_start);
        }

        let tangent_dirichlet_start = Instant::now();
        matrix_pattern.apply_dirichlet(&mut tangent, &mut tangent_rhs);
        if let Some(profile) = profile.as_deref_mut() {
            profile.dirichlet_apply_ms += elapsed_ms(tangent_dirichlet_start);
        }
    }

    let asm_ms = asm_start.elapsed().as_millis() as u64;
    let solve_start = Instant::now();
    let delta = if let Some(profile) = profile.as_deref_mut() {
        let (delta, pcg_profile) = pcg_solve_with_guess_options_profiled(
            &tangent,
            &tangent_rhs,
            5000,
            1.0e-8,
            None,
            linear_policy.pcg,
        )?;
        profile.pcg.add_assign(&pcg_profile);
        delta
    } else {
        pcg_solve_with_guess_options(
            &tangent,
            &tangent_rhs,
            5000,
            1.0e-8,
            None,
            linear_policy.pcg,
        )?
    };
    let solve_ms = solve_start.elapsed().as_millis() as u64;
    Ok((delta, residual_norm, asm_ms, solve_ms))
}

fn scaled_current_densities(current_densities: &[f64], scale: f64) -> Vec<f64> {
    if (scale - 1.0).abs() < 1.0e-12 {
        current_densities.to_vec()
    } else {
        current_densities
            .iter()
            .map(|value| value * scale)
            .collect()
    }
}

fn line_search_step(
    solve_mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
    nonlinear_material_labels: &[String],
    j_z: &[f64],
    materials: &[MaterialProps],
    az: &[f64],
    delta: &[f64],
    magnet_fractions: Option<&[f64]>,
    residual: f64,
    nonlinear_config: NonlinearSolveConfig,
    matrix_pattern: Option<&SolveMatrixPattern>,
    mut profile: Option<&mut SolveProfile>,
) -> Result<NewtonAcceptedStep, String> {
    let line_search_start = Instant::now();
    let accept_below = residual * nonlinear_config.newton_line_search_accept_ratio;
    let mut damping = nonlinear_config.newton_initial_damping;
    let mut attempts = 0;
    let mut best_residual = f64::INFINITY;

    loop {
        if let Some(profile) = profile.as_deref_mut() {
            profile.line_search_candidate_count += 1;
        }
        let candidate_az: Vec<f64> = az
            .iter()
            .zip(delta.iter())
            .map(|(value, step)| value + damping * step)
            .collect();

        let field_start = Instant::now();
        let candidate_fields = compute_element_fields(solve_mesh, &candidate_az);
        if let Some(profile) = profile.as_deref_mut() {
            profile.line_search_field_compute_ms += elapsed_ms(field_start);
        }

        let mut candidate_materials = materials.to_vec();
        let material_start = Instant::now();
        update_nonlinear_materials(
            &mut candidate_materials,
            &candidate_fields,
            &solve_mesh.regions,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            nonlinear_material_labels,
            1.0,
            f64::MAX,
        );
        if let Some(profile) = profile.as_deref_mut() {
            profile.line_search_material_update_ms += elapsed_ms(material_start);
        }

        let residual_start = Instant::now();
        let candidate_residual = nonlinear_residual_norm(
            solve_mesh,
            n_pole_pitches,
            &candidate_materials,
            j_z,
            &candidate_az,
            magnet_fractions,
            matrix_pattern,
        );
        if let Some(profile) = profile.as_deref_mut() {
            profile.line_search_residual_eval_ms += elapsed_ms(residual_start);
        }
        if candidate_residual.is_finite() {
            best_residual = best_residual.min(candidate_residual);
            if candidate_residual <= accept_below {
                if let Some(profile) = profile.as_deref_mut() {
                    profile.line_search_total_ms += elapsed_ms(line_search_start);
                }
                return Ok(NewtonAcceptedStep {
                    az: candidate_az,
                    fields: candidate_fields,
                    materials: candidate_materials,
                    residual: candidate_residual,
                    damping,
                    attempts,
                });
            }
        }

        if damping <= nonlinear_config.newton_min_damping {
            break;
        }
        damping = (damping * nonlinear_config.newton_line_search_shrink)
            .max(nonlinear_config.newton_min_damping);
        if let Some(profile) = profile.as_deref_mut() {
            profile.line_search_attempt_count += 1;
        }
        attempts += 1;
    }

    if let Some(profile) = profile.as_deref_mut() {
        profile.line_search_total_ms += elapsed_ms(line_search_start);
    }
    Err(format!(
        "newton line search failed to reduce residual: residual={residual:.6}, best_candidate={best_residual:.6}, min_damping={:.6}",
        nonlinear_config.newton_min_damping,
    ))
}

fn run_newton_stage(
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
    nonlinear_config: NonlinearSolveConfig,
    stage_index: usize,
    stage_count: usize,
    current_scale: f64,
    iteration_offset: usize,
    linear_policy: MotorLinearSolvePolicy,
    matrix_pattern: Option<&SolveMatrixPattern>,
    mut profile: Option<&mut SolveProfile>,
) -> Result<NonlinearLoopOutput, String> {
    let mut total_assembly_ms = 0;
    let mut total_solve_ms = 0;
    let mut residual_history = Vec::new();
    let mut diagnostics = Vec::new();
    let convergence_threshold = nonlinear_config.newton_convergence_threshold;

    eprintln!(
        "  newton_continuation: stage={}/{} current_scale={:.3}",
        stage_index + 1,
        stage_count,
        current_scale,
    );

    let (mut az, asm_ms, solve_ms) = solve_linear_system(
        solve_mesh,
        n_pole_pitches,
        &materials,
        j_z,
        az_warm_start,
        magnet_fractions,
        matrix_pattern,
        super::LINEAR_SOLVE_TIGHT_TOL,
        linear_policy,
        profile.as_deref_mut(),
    )?;
    total_assembly_ms += asm_ms;
    total_solve_ms += solve_ms;
    let field_start = Instant::now();
    let mut fields = compute_element_fields(solve_mesh, &az);
    if let Some(profile) = profile.as_deref_mut() {
        profile.field_compute_ms += elapsed_ms(field_start);
    }

    for iteration in 0..nonlinear_config.max_iterations {
        emit_angle_solve_context(progress, iteration + 1, nonlinear_config.max_iterations);

        let mut target_materials = materials.clone();
        let material_start = Instant::now();
        let update = update_nonlinear_materials(
            &mut target_materials,
            &fields,
            &solve_mesh.regions,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            nonlinear_material_labels,
            1.0,
            f64::MAX,
        );
        if let Some(profile) = profile.as_deref_mut() {
            profile.material_update_ms += elapsed_ms(material_start);
        }
        materials = target_materials;

        let (delta, residual, asm_ms, solve_ms) = solve_newton_correction(
            solve_mesh,
            n_pole_pitches,
            &materials,
            j_z,
            &fields,
            &az,
            magnet_fractions,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            matrix_pattern,
            linear_policy,
            profile.as_deref_mut(),
        )?;
        total_assembly_ms += asm_ms;
        total_solve_ms += solve_ms;
        if residual <= convergence_threshold {
            residual_history.push(residual);
            return Ok(NonlinearLoopOutput {
                materials,
                az,
                fields,
                residual_history,
                diagnostics,
                assembly_time_ms: total_assembly_ms,
                solve_time_ms: total_solve_ms,
            });
        }

        let accepted = line_search_step(
            solve_mesh,
            n_pole_pitches,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            nonlinear_material_labels,
            j_z,
            &materials,
            &az,
            &delta,
            magnet_fractions,
            residual,
            nonlinear_config,
            matrix_pattern,
            profile.as_deref_mut(),
        )
        .map_err(|err| {
            format!(
                "{err}; stage={}/{} current_scale={:.3} iteration={}",
                stage_index + 1,
                stage_count,
                current_scale,
                iteration + 1,
            )
        })?;

        residual_history.push(accepted.residual);

        if let Some(diagnostic) = nonlinear_iteration_diagnostic(
            solve_mesh,
            j_z,
            &update,
            iteration_offset + iteration + 1,
            rotor_angle_rad.to_degrees(),
            accepted.residual,
            convergence_threshold,
            accepted.damping,
            accepted.attempts,
        ) {
            diagnostics.push(diagnostic);
        }

        emit_angle_iteration_progress(
            progress,
            iteration + 1,
            nonlinear_config.max_iterations,
            asm_ms,
            solve_ms,
            accepted.residual,
            convergence_threshold,
            update.worst_element,
        );

        eprintln!(
            "  newton: stage={}/{} iter={} residual={:.6} accepted_residual={:.6} damping={:.6} line_search_attempts={}",
            stage_index + 1,
            stage_count,
            iteration + 1,
            residual,
            accepted.residual,
            accepted.damping,
            accepted.attempts,
        );

        az = accepted.az;
        fields = accepted.fields;
        materials = accepted.materials;

        if accepted.residual <= convergence_threshold {
            return Ok(NonlinearLoopOutput {
                materials,
                az,
                fields,
                residual_history,
                diagnostics,
                assembly_time_ms: total_assembly_ms,
                solve_time_ms: total_solve_ms,
            });
        }
    }

    Err(format!(
        "newton nonlinear solve failed to converge after {} iterations at rotor_angle_deg={:.3}; stage={}/{} current_scale={:.3}; residual_history={:?}",
        nonlinear_config.max_iterations,
        rotor_angle_rad.to_degrees(),
        stage_index + 1,
        stage_count,
        current_scale,
        residual_history
    ))
}

pub(super) fn run_newton_nonlinear_loop(
    solve_mesh: &crate::mesh::TriMesh,
    n_pole_pitches: u32,
    config: &MotorConfig,
    nonlinear_curve_ids_by_element: &[Option<usize>],
    nonlinear_curves: &[crate::field::BhCurve],
    nonlinear_material_labels: &[String],
    j_z: &[f64],
    current_scales: &[f64],
    mut materials: Vec<MaterialProps>,
    magnet_fractions: Option<&[f64]>,
    az_warm_start: Option<&[f64]>,
    progress: Option<&AngleProgressContext<'_>>,
    rotor_angle_rad: f64,
    nonlinear_config: NonlinearSolveConfig,
    linear_policy: MotorLinearSolvePolicy,
    matrix_pattern: Option<&SolveMatrixPattern>,
    mut profile: Option<&mut SolveProfile>,
) -> Result<NonlinearLoopOutput, String> {
    let stage_count = current_scales.len();
    let mut total_assembly_ms = 0;
    let mut total_solve_ms = 0;
    let mut residual_history = Vec::new();
    let mut diagnostics = Vec::new();
    let mut az = az_warm_start.map(|guess| guess.to_vec());
    let mut fields = None;

    for (stage_index, current_scale) in current_scales.iter().copied().enumerate() {
        let stage_j_z = scaled_current_densities(j_z, current_scale);
        let stage_output = run_newton_stage(
            solve_mesh,
            n_pole_pitches,
            config,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            nonlinear_material_labels,
            &stage_j_z,
            materials,
            magnet_fractions,
            az.as_deref(),
            progress,
            rotor_angle_rad,
            nonlinear_config,
            stage_index,
            stage_count,
            current_scale,
            residual_history.len(),
            linear_policy,
            matrix_pattern,
            profile.as_deref_mut(),
        )?;
        total_assembly_ms += stage_output.assembly_time_ms;
        total_solve_ms += stage_output.solve_time_ms;
        residual_history.extend(stage_output.residual_history);
        diagnostics.extend(stage_output.diagnostics);
        materials = stage_output.materials;
        az = Some(stage_output.az);
        fields = Some(stage_output.fields);
    }

    let az = az.ok_or_else(|| "newton continuation did not produce an A_z solution".to_string())?;
    let fields =
        fields.ok_or_else(|| "newton continuation did not produce element fields".to_string())?;
    Ok(NonlinearLoopOutput {
        materials,
        az,
        fields,
        residual_history,
        diagnostics,
        assembly_time_ms: total_assembly_ms,
        solve_time_ms: total_solve_ms,
    })
}
