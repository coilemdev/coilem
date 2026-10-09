//! Steady-state thermal solve orchestration.

use serde::{Deserialize, Serialize};

use crate::assembly::stiffness_csr_pattern;
use crate::mesh::TriMesh;
use crate::sparse::pcg_solve;

use super::assembly::{
    assemble_thermal_source, assemble_thermal_stiffness_with_pattern, boundary_pattern_extras,
    element_areas_m2,
};
use super::bc::ThermalBoundarySet;
use super::contacts::ThermalContactSet;
use super::energy::ThermalEnergyBalance;
use super::materials::ThermalMaterialProps;
use super::sources::ThermalSources;
use super::types::ThermalSolveReport;

pub const DEFAULT_ENERGY_BALANCE_TOLERANCE: f64 = 5.0e-2;
pub const DEFAULT_NONLINEAR_TOLERANCE: f64 = 1.0e-6;
pub const DEFAULT_MAX_NONLINEAR_ITERS: usize = 40;

/// JSON input for `magneto2d --mode thermal`.
///
/// Node coordinates must be in metres. Callers convert EM mm meshes at the
/// Python boundary and set `length_units: "m"`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThermalCliInput {
    pub mesh: TriMesh,
    pub materials: Vec<ThermalMaterialProps>,
    pub q_w_per_m3: Vec<f64>,
    pub boundaries: ThermalBoundarySet,
    /// Optional zero-thickness internal contacts. Absent/empty is OK.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub contacts: Option<ThermalContactSet>,
    #[serde(default = "default_stack_length")]
    pub stack_length_m: f64,
    #[serde(default = "default_energy_tol")]
    pub energy_balance_tolerance: f64,
    #[serde(default = "default_true")]
    pub require_energy_balance: bool,
    /// Length units for `mesh.nodes`. Must be metres (`"m"`).
    #[serde(default = "default_length_units")]
    pub length_units: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub openem_convention_tag: Option<String>,
}

fn default_stack_length() -> f64 {
    1.0
}
fn default_energy_tol() -> f64 {
    DEFAULT_ENERGY_BALANCE_TOLERANCE
}
fn default_true() -> bool {
    true
}
fn default_length_units() -> String {
    "m".to_string()
}

impl ThermalCliInput {
    pub fn into_request(self) -> Result<ThermalSolveRequest, String> {
        if self.length_units != "m" {
            return Err(format!(
                "thermal input length_units={:?} must be \"m\" \
                 (convert EM mm meshes before invoking --mode thermal)",
                self.length_units
            ));
        }
        Ok(ThermalSolveRequest {
            mesh: self.mesh,
            materials: self.materials,
            sources: ThermalSources::from_values(self.q_w_per_m3),
            boundaries: self.boundaries,
            contacts: self.contacts.unwrap_or_default(),
            stack_length_m: self.stack_length_m,
            energy_balance_tolerance: self.energy_balance_tolerance,
            require_energy_balance: self.require_energy_balance,
            max_nonlinear_iters: DEFAULT_MAX_NONLINEAR_ITERS,
            nonlinear_tolerance: DEFAULT_NONLINEAR_TOLERANCE,
        })
    }
}

#[derive(Debug, Clone)]
pub struct ThermalSolveRequest {
    pub mesh: TriMesh,
    pub materials: Vec<ThermalMaterialProps>,
    pub sources: ThermalSources,
    pub boundaries: ThermalBoundarySet,
    pub contacts: ThermalContactSet,
    pub stack_length_m: f64,
    pub energy_balance_tolerance: f64,
    pub require_energy_balance: bool,
    pub max_nonlinear_iters: usize,
    pub nonlinear_tolerance: f64,
}

impl ThermalSolveRequest {
    #[allow(dead_code)] // used by thermal unit tests / future callers
    pub fn new(
        mesh: TriMesh,
        materials: Vec<ThermalMaterialProps>,
        sources: ThermalSources,
        boundaries: ThermalBoundarySet,
    ) -> Self {
        Self {
            mesh,
            materials,
            sources,
            boundaries,
            contacts: ThermalContactSet::default(),
            stack_length_m: 1.0,
            energy_balance_tolerance: DEFAULT_ENERGY_BALANCE_TOLERANCE,
            require_energy_balance: true,
            max_nonlinear_iters: DEFAULT_MAX_NONLINEAR_ITERS,
            nonlinear_tolerance: DEFAULT_NONLINEAR_TOLERANCE,
        }
    }
}

pub fn run_steady_state_thermal(
    request: &ThermalSolveRequest,
) -> Result<ThermalSolveReport, String> {
    if request.materials.len() != request.mesh.triangles.len() {
        return Err("thermal materials length must match triangle count".to_string());
    }
    if request.sources.q_w_per_m3.len() != request.mesh.triangles.len() {
        return Err("thermal sources length must match triangle count".to_string());
    }
    if request.stack_length_m <= 0.0 {
        return Err("stack_length_m must be positive".to_string());
    }
    for (idx, material) in request.materials.iter().enumerate() {
        material
            .validate()
            .map_err(|err| format!("thermal material[{idx}]: {err}"))?;
    }
    request
        .boundaries
        .validate_temperature_anchor(request.mesh.nodes.len())
        .map_err(|err| format!("thermal boundaries: {err}"))?;
    request
        .contacts
        .validate(request.mesh.nodes.len())
        .map_err(|err| format!("thermal contacts: {err}"))?;

    let mut materials = request.materials.clone();
    let needs_nonlinear = request.boundaries.has_radiation()
        || materials.iter().any(|m| m.k_of_t.is_some());

    let edge_extras: Vec<[usize; 2]> = request
        .boundaries
        .conditions
        .iter()
        .flat_map(|c| match c {
            super::bc::ThermalBoundaryCondition::Convection { edges, .. }
            | super::bc::ThermalBoundaryCondition::Radiation { edges, .. }
            | super::bc::ThermalBoundaryCondition::NeumannFlux { edges, .. } => edges.clone(),
            super::bc::ThermalBoundaryCondition::Dirichlet { .. } => Vec::new(),
        })
        .collect();
    let mut extras = boundary_pattern_extras(request.mesh.nodes.len(), &edge_extras);
    extras.extend(request.contacts.pattern_extras());
    let pattern = stiffness_csr_pattern(&request.mesh, &extras);

    let mut temperature = vec![300.0; request.mesh.nodes.len()];
    let mut iterations = 0usize;

    if !needs_nonlinear {
        temperature = solve_linear_thermal(
            &request.mesh,
            &materials,
            &request.sources.q_w_per_m3,
            &request.boundaries,
            &request.contacts,
            request.stack_length_m,
            &pattern,
            None,
        )?;
        iterations = 1;
    } else {
        for iter in 0..request.max_nonlinear_iters {
            iterations = iter + 1;
            update_materials_from_temperature(&request.mesh, &mut materials, &temperature)?;

            let next = solve_linear_thermal(
                &request.mesh,
                &materials,
                &request.sources.q_w_per_m3,
                &request.boundaries,
                &request.contacts,
                request.stack_length_m,
                &pattern,
                Some(&temperature),
            )?;

            let rel = relative_change(&temperature, &next);
            temperature = next;
            if rel < request.nonlinear_tolerance {
                break;
            }
            if iter + 1 == request.max_nonlinear_iters {
                return Err(format!(
                    "thermal nonlinear iteration failed to converge in {} iters (rel={rel:.3e})",
                    request.max_nonlinear_iters
                ));
            }
        }
    }

    let energy = ThermalEnergyBalance::evaluate_with_contacts(
        &request.mesh,
        &materials,
        &request.sources.q_w_per_m3,
        &temperature,
        &request.boundaries,
        &request.contacts,
        request.stack_length_m,
        request.energy_balance_tolerance,
    );

    if request.require_energy_balance && !energy.closed {
        return Err(format!(
            "thermal energy-balance gate failed: residual_rel={:.3e} (tol={:.3e}); \
             volumetric_w={:.6e} outflow_w={:.6e}",
            energy.relative_residual,
            energy.tolerance,
            energy.volumetric_source_w,
            energy.boundary_outflow_w
        ));
    }

    let _areas = element_areas_m2(&request.mesh);
    Ok(ThermalSolveReport::from_solution(
        temperature,
        energy,
        iterations,
        "pcg",
        request.stack_length_m,
    ))
}

fn solve_linear_thermal(
    mesh: &TriMesh,
    materials: &[ThermalMaterialProps],
    q_w_per_m3: &[f64],
    boundaries: &ThermalBoundarySet,
    contacts: &ThermalContactSet,
    stack_length_m: f64,
    pattern: &crate::sparse::ElementCsrAssemblyPattern,
    radiation_linearization_t: Option<&[f64]>,
) -> Result<Vec<f64>, String> {
    let mut k = assemble_thermal_stiffness_with_pattern(pattern, mesh, materials);
    for value in &mut k.values {
        *value *= stack_length_m;
    }
    let mut f = assemble_thermal_source(mesh, q_w_per_m3);
    for value in &mut f {
        *value *= stack_length_m;
    }

    contacts.apply(&mut k, stack_length_m)?;

    if let Some(t_star) = radiation_linearization_t {
        boundaries.apply_radiation_linearized(
            &mut k,
            &mut f,
            &mesh.nodes,
            t_star,
            stack_length_m,
        )?;
    }

    boundaries.apply_linear(&mut k, &mut f, &mesh.nodes, stack_length_m)?;

    pcg_solve(&k, &f, 20_000, 1.0e-10)
}

fn update_materials_from_temperature(
    mesh: &TriMesh,
    materials: &mut [ThermalMaterialProps],
    temperature_k: &[f64],
) -> Result<(), String> {
    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        if materials[tri_idx].k_of_t.is_none() {
            continue;
        }
        let [i, j, m] = *tri;
        let t_avg = (temperature_k[i] + temperature_k[j] + temperature_k[m]) / 3.0;
        materials[tri_idx].k_w_per_m_k = materials[tri_idx]
            .conductivity_at(t_avg)
            .map_err(|err| format!("thermal material[{tri_idx}]: {err}"))?;
    }
    Ok(())
}

fn relative_change(prev: &[f64], next: &[f64]) -> f64 {
    let mut num = 0.0;
    let mut den = 0.0;
    for (a, b) in prev.iter().zip(next.iter()) {
        num += (b - a).abs();
        den += b.abs();
    }
    num / den.max(1.0e-12)
}
