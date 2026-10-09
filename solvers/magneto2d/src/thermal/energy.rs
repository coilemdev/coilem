//! Energy-balance closure — blocking gate on every thermal solve.
//!
//! Discriminator: Σ volumetric sources = Σ boundary heat rates.
//! Dirichlet heat rates use FEM reaction forces (exact discrete balance).

use serde::{Deserialize, Serialize};

use crate::assembly::{stiffness_csr_pattern, triangle_gradients};
use crate::mesh::TriMesh;

use super::assembly::{
    assemble_thermal_source, assemble_thermal_stiffness_with_pattern,
};
use super::bc::{ThermalBoundaryCondition, ThermalBoundarySet, STEFAN_BOLTZMANN};
use super::contacts::ThermalContactSet;
use super::materials::ThermalMaterialProps;

/// Closure report: Σ volumetric sources ≈ Σ boundary outflow.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThermalEnergyBalance {
    pub volumetric_source_w: f64,
    pub boundary_outflow_w: f64,
    pub residual_w: f64,
    pub relative_residual: f64,
    pub closed: bool,
    pub tolerance: f64,
}

impl ThermalEnergyBalance {
    #[allow(dead_code)] // thin-wrapper retained for callers without contacts
    pub fn evaluate(
        mesh: &TriMesh,
        materials: &[ThermalMaterialProps],
        q_w_per_m3: &[f64],
        temperature_k: &[f64],
        boundaries: &ThermalBoundarySet,
        stack_length_m: f64,
        tolerance: f64,
    ) -> Self {
        Self::evaluate_with_contacts(
            mesh,
            materials,
            q_w_per_m3,
            temperature_k,
            boundaries,
            &ThermalContactSet::default(),
            stack_length_m,
            tolerance,
        )
    }

    pub fn evaluate_with_contacts(
        mesh: &TriMesh,
        materials: &[ThermalMaterialProps],
        q_w_per_m3: &[f64],
        temperature_k: &[f64],
        boundaries: &ThermalBoundarySet,
        contacts: &ThermalContactSet,
        stack_length_m: f64,
        tolerance: f64,
    ) -> Self {
        let volumetric = volumetric_source_power(mesh, q_w_per_m3, stack_length_m);
        let mut outflow = prescribed_boundary_outflow(temperature_k, boundaries, mesh, stack_length_m);
        outflow += dirichlet_reaction_outflow(
            mesh,
            materials,
            q_w_per_m3,
            temperature_k,
            boundaries,
            contacts,
            stack_length_m,
        );

        let residual = volumetric - outflow;
        let scale = volumetric.abs().max(outflow.abs()).max(1.0e-12);
        let relative = residual.abs() / scale;
        // Absolute floor catches q=0 cases where both sides are numerical noise.
        let absolute_tol = 1.0e-3 * stack_length_m.max(1.0);
        let closed = residual.abs() <= absolute_tol || relative <= tolerance;
        Self {
            volumetric_source_w: volumetric,
            boundary_outflow_w: outflow,
            residual_w: residual,
            relative_residual: relative,
            closed,
            tolerance,
        }
    }
}

fn volumetric_source_power(mesh: &TriMesh, q_w_per_m3: &[f64], stack_length_m: f64) -> f64 {
    mesh.triangles
        .iter()
        .enumerate()
        .map(|(idx, tri)| {
            let q = q_w_per_m3.get(idx).copied().unwrap_or(0.0);
            let [i, j, m] = *tri;
            let (area, _) = triangle_gradients(&mesh.nodes, i, j, m);
            q * area * stack_length_m
        })
        .sum()
}

fn edge_length_m(nodes: &[[f64; 2]], a: usize, b: usize) -> f64 {
    let dx = nodes[b][0] - nodes[a][0];
    let dy = nodes[b][1] - nodes[a][1];
    (dx * dx + dy * dy).sqrt()
}

fn prescribed_boundary_outflow(
    temperature_k: &[f64],
    boundaries: &ThermalBoundarySet,
    mesh: &TriMesh,
    stack_length_m: f64,
) -> f64 {
    let mut outflow = 0.0;
    for condition in &boundaries.conditions {
        match condition {
            ThermalBoundaryCondition::NeumannFlux {
                edges,
                flux_w_per_m2,
            } => {
                for edge in edges {
                    let length = edge_length_m(&mesh.nodes, edge[0], edge[1]);
                    outflow += flux_w_per_m2 * length * stack_length_m;
                }
            }
            ThermalBoundaryCondition::Convection {
                edges,
                h_w_per_m2_k,
                ambient_k,
            } => {
                for edge in edges {
                    let length = edge_length_m(&mesh.nodes, edge[0], edge[1]);
                    let t_edge = 0.5 * (temperature_k[edge[0]] + temperature_k[edge[1]]);
                    outflow += h_w_per_m2_k * (t_edge - ambient_k) * length * stack_length_m;
                }
            }
            ThermalBoundaryCondition::Radiation {
                edges,
                emissivity,
                ambient_k,
            } => {
                let eps = (*emissivity).max(0.0).min(1.0);
                let tamb4 = ambient_k.powi(4);
                for edge in edges {
                    let length = edge_length_m(&mesh.nodes, edge[0], edge[1]);
                    let t_edge = 0.5 * (temperature_k[edge[0]] + temperature_k[edge[1]]);
                    outflow += eps
                        * STEFAN_BOLTZMANN
                        * (t_edge.powi(4) - tamb4)
                        * length
                        * stack_length_m;
                }
            }
            ThermalBoundaryCondition::Dirichlet { .. } => {}
        }
    }
    outflow
}

/// Heat leaving through Dirichlet nodes via FEM reactions on the
/// conduction operator only (no Robin/Neumann terms in K/f).
/// Prescribed convection/Neumann/radiation outflows are counted separately
/// so we do not double-count.
fn dirichlet_reaction_outflow(
    mesh: &TriMesh,
    materials: &[ThermalMaterialProps],
    q_w_per_m3: &[f64],
    temperature_k: &[f64],
    boundaries: &ThermalBoundarySet,
    contacts: &ThermalContactSet,
    stack_length_m: f64,
) -> f64 {
    let dirichlet = boundaries.dirichlet_values(mesh.nodes.len());
    if dirichlet.iter().all(Option::is_none) {
        return 0.0;
    }

    let extras = contacts.pattern_extras();
    let pattern = stiffness_csr_pattern(mesh, &extras);
    let mut k = assemble_thermal_stiffness_with_pattern(&pattern, mesh, materials);
    for value in &mut k.values {
        *value *= stack_length_m;
    }
    if let Err(err) = contacts.apply(&mut k, stack_length_m) {
        // Energy bookkeeping must not panic; treat as unclosed if pattern failed.
        eprintln!("thermal energy contact assemble failed: {err}");
        return f64::NAN;
    }
    let mut f = assemble_thermal_source(mesh, q_w_per_m3);
    for value in &mut f {
        *value *= stack_length_m;
    }

    let mut kt = vec![0.0; mesh.nodes.len()];
    k.mul_vec(temperature_k, &mut kt);

    // R = f - K T at Dirichlet nodes: positive ⇒ heat leaves the domain
    // into the Dirichlet reservoir (matches Σq for generation+cold walls).
    let mut outflow = 0.0;
    for (i, maybe_t) in dirichlet.iter().enumerate() {
        if maybe_t.is_some() {
            outflow += f[i] - kt[i];
        }
    }
    outflow
}
