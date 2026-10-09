//! Thermal stiffness / source assembly for steady-state conduction.
//!
//! Weak form of -div(k grad T) = q:
//!   Σ_e ∫ k ∇φ_i · ∇φ_j dΩ  T_j  =  Σ_e ∫ q φ_i dΩ

use crate::assembly::triangle_gradients;
use crate::mesh::TriMesh;
use crate::sparse::{CooMatrix, CsrMatrix, ElementCsrAssemblyPattern};

use super::materials::ThermalMaterialProps;

/// Assemble thermal stiffness K_ij = Σ k (∇φ_i · ∇φ_j) Area.
///
/// `mesh.nodes` are expected in metres (caller converts from mm).
/// Convenience wrapper; the solve path uses [`assemble_thermal_stiffness_with_pattern`].
#[allow(dead_code)]
pub fn assemble_thermal_stiffness(
    mesh: &TriMesh,
    materials: &[ThermalMaterialProps],
) -> CooMatrix {
    let n = mesh.nodes.len();
    let mut k = CooMatrix::new(n);

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let [kxx, kyy] = materials[tri_idx].tensor();
        let [i, j, m] = *tri;
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }
        let local_nodes = [i, j, m];
        for a in 0..3 {
            for b in 0..3 {
                let val = (kxx * grad[a][0] * grad[b][0] + kyy * grad[a][1] * grad[b][1]) * area;
                if val.abs() > 1e-30 {
                    k.add(local_nodes[a], local_nodes[b], val);
                }
            }
        }
    }
    k
}

pub fn assemble_thermal_stiffness_with_pattern(
    pattern: &ElementCsrAssemblyPattern,
    mesh: &TriMesh,
    materials: &[ThermalMaterialProps],
) -> CsrMatrix {
    let mut k = pattern.zero_matrix();
    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let [kxx, kyy] = materials[tri_idx].tensor();
        let [i, j, m] = *tri;
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }
        let slots = pattern.element_slots(tri_idx);
        for a in 0..3 {
            for b in 0..3 {
                let val = (kxx * grad[a][0] * grad[b][0] + kyy * grad[a][1] * grad[b][1]) * area;
                if val.abs() > 1e-30 {
                    k.values[slots[a][b]] += val;
                }
            }
        }
    }
    k
}

/// Assemble volumetric source f_i = Σ q · Area / 3.
pub fn assemble_thermal_source(mesh: &TriMesh, q_w_per_m3: &[f64]) -> Vec<f64> {
    let n = mesh.nodes.len();
    let mut f = vec![0.0; n];
    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let q = q_w_per_m3.get(tri_idx).copied().unwrap_or(0.0);
        if q.abs() < 1e-30 {
            continue;
        }
        let [i, j, m] = *tri;
        let (area, _) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }
        let contrib = q * area / 3.0;
        f[i] += contrib;
        f[j] += contrib;
        f[m] += contrib;
    }
    f
}

/// Element areas [m²] for energy-balance bookkeeping.
pub fn element_areas_m2(mesh: &TriMesh) -> Vec<f64> {
    mesh.triangles
        .iter()
        .map(|tri| {
            let [i, j, m] = *tri;
            let (area, _) = triangle_gradients(&mesh.nodes, i, j, m);
            area
        })
        .collect()
}

/// Extra CSR pattern entries needed for convection/radiation edge terms.
pub fn boundary_pattern_extras(n_nodes: usize, edges: &[[usize; 2]]) -> Vec<(usize, usize)> {
    let mut extras = Vec::new();
    for edge in edges {
        let [a, b] = *edge;
        if a < n_nodes {
            extras.push((a, a));
        }
        if b < n_nodes {
            extras.push((b, b));
        }
    }
    extras
}
