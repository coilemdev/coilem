//! FEM stiffness matrix and source vector assembly for 2D magnetostatics.
//!
//! Solves: -div(ν · grad(A_z)) = J_z + (curl M)_z
//!
//! where A_z is the z-component of the magnetic vector potential,
//! ν = 1/(μ₀·μᵣ) is the reluctivity, J_z is the current density,
//! and M is the magnetization from permanent magnets.
//!
//! Using linear triangular (P1) elements with nodal basis functions.
//! Assembles into sparse COO format → CSR for fast solve.

use crate::materials::MaterialProps;
use crate::mesh::TriMesh;
use crate::sparse::{CooMatrix, CsrMatrix, ElementCsrAssemblyPattern};

/// Assemble the global stiffness matrix K in sparse COO format.
///
/// K_ij = Σ_e ∫_Ωe ν · (∇φ_i · ∇φ_j) dΩ
///
/// For linear triangles, the gradients are constant per element,
/// so the integral simplifies to: ν_e · (∇φ_i · ∇φ_j) · Area_e
pub fn assemble_stiffness(mesh: &TriMesh, materials: &[MaterialProps]) -> CooMatrix {
    let n = mesh.nodes.len();
    let mut k = CooMatrix::new(n);

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let nu = materials[tri_idx].nu;
        let [i, j, m] = *tri;

        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue; // degenerate triangle
        }

        // Local stiffness: K_ab = ν * (∇φ_a · ∇φ_b) * Area
        let local_nodes = [i, j, m];
        for a in 0..3 {
            for b in 0..3 {
                let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                let val = nu * dot * area;
                if val.abs() > 1e-30 {
                    k.add(local_nodes[a], local_nodes[b], val);
                }
            }
        }
    }

    k
}

pub fn stiffness_csr_pattern(
    mesh: &TriMesh,
    extra_entries: &[(usize, usize)],
) -> ElementCsrAssemblyPattern {
    ElementCsrAssemblyPattern::from_triangles(mesh.nodes.len(), &mesh.triangles, extra_entries)
}

#[allow(dead_code)]
pub fn assemble_stiffness_with_pattern(
    pattern: &ElementCsrAssemblyPattern,
    mesh: &TriMesh,
    materials: &[MaterialProps],
) -> CsrMatrix {
    let mut k = pattern.zero_matrix();

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let nu = materials[tri_idx].nu;
        let [i, j, m] = *tri;

        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }

        let slots = pattern.element_slots(tri_idx);
        for a in 0..3 {
            for b in 0..3 {
                let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                let val = nu * dot * area;
                if val.abs() > 1e-30 {
                    k.values[slots[a][b]] += val;
                }
            }
        }
    }

    k
}

/// Assemble the global source vector f from permanent magnet sources
/// and current density sources.
///
/// PM source: f_i = ν · (B_r × ∇φ_i)_z · Area
/// Current source: f_i = J_z · Area / 3
///
/// `magnet_fractions` (sub-element integration): when `Some`,
/// each triangle's PM source contribution is scaled by `magnet_fractions[idx]`
/// ∈ [0, 1]. This is the smoothness-preserving path that eliminates the
/// flux-linkage step changes from triangle-classification flips during
/// rotor sweeps (see `magnet_fraction.rs`). When `None`, the legacy all-
/// or-nothing source term is used (unchanged byte-for-byte).
pub fn assemble_source(
    mesh: &TriMesh,
    materials: &[MaterialProps],
    current_densities: &[f64],
    magnet_fractions: Option<&[f64]>,
) -> Vec<f64> {
    let n = mesh.nodes.len();
    let mut f = vec![0.0; n];

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        let mat = &materials[tri_idx];
        let [i, j, m] = *tri;
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
        if area <= 0.0 {
            continue;
        }

        // PM source term.
        //
        // In 2D with A = A_z z-hat and B_r = (B_rx, B_ry), the magnet term
        // enters the weak form as:
        //
        //   ∫ ν (B_rx dφ/dy - B_ry dφ/dx) dΩ
        //
        // not ν (B_r · ∇φ). Using the unrotated gradient suppresses the
        // physically useful working harmonic even when local peak |B| looks
        // plausible.
        //
        // When sub-element integration is active, scale by the per-triangle
        // magnet fill fraction. fraction = 0 turns off the contribution
        // (triangle is fully outside the rotated magnet sector); fraction =
        // 1 leaves it unchanged (fully inside). Triangles not flagged as
        // magnet by the classifier still get fraction = 0, so we can apply
        // the fraction unconditionally without affecting non-magnet
        // triangles. We still gate on `mat.br > 0` because triangles
        // *outside* the magnet band carry br = 0 from material assignment.
        if mat.br > 0.0 {
            let fraction = magnet_fractions.map(|fr| fr[tri_idx]).unwrap_or(1.0);
            if fraction > 0.0 {
                let mag_dir_x = mat.mag_angle_rad.cos();
                let mag_dir_y = mat.mag_angle_rad.sin();
                let local_nodes = [i, j, m];
                let scale = mat.nu * mat.br * fraction;
                for a in 0..3 {
                    let rotated = mag_dir_x * grad[a][1] - mag_dir_y * grad[a][0];
                    f[local_nodes[a]] += scale * rotated * area;
                }
            }
        }

        // Current density source: f_i += J_z · Area / 3.
        //
        // The solver expects mesh coordinates in SI meters so that element
        // areas are m^2 and the supplied current density remains A/m^2.
        let jz = current_densities[tri_idx];
        if jz.abs() > 1e-12 {
            let contrib = jz * area / 3.0;
            f[i] += contrib;
            f[j] += contrib;
            f[m] += contrib;
        }
    }

    f
}

/// Apply Dirichlet boundary conditions (A_z = 0 on boundary).
/// Uses penalty method on the COO matrix.
#[allow(dead_code)]
pub fn apply_dirichlet_bc(k: &mut CsrMatrix, f: &mut [f64], boundary_nodes: &[usize]) {
    k.apply_dirichlet(f, boundary_nodes);
}

/// Apply anti-periodic boundary conditions on sector edges.
///
/// For a pole-pitch sector: A_z(θ=0) = -A_z(θ=pole_pitch).
/// Constraint: A_z[left] + A_z[right] = 0
/// Penalty method: add P*(A_left + A_right)^2 to energy.
/// → K[left,left] += P, K[left,right] += P, K[right,left] += P, K[right,right] += P
#[allow(dead_code)]
pub fn apply_antiperiodic_bc(
    k: &mut CooMatrix,
    _f: &mut [f64],
    sector_edge_pairs: &[(usize, usize)],
    boundary_nodes: &[usize],
) {
    // Use moderate penalty (~stiffness diagonal magnitude) for PCG conditioning.
    let penalty = 1e10;

    // Don't apply anti-periodic BC on nodes that are already Dirichlet (boundary).
    let mut is_boundary = vec![false; k.nrows];
    for &node in boundary_nodes {
        if node < is_boundary.len() {
            is_boundary[node] = true;
        }
    }

    for &(left, right) in sector_edge_pairs {
        if is_boundary.get(left).copied().unwrap_or(false)
            || is_boundary.get(right).copied().unwrap_or(false)
        {
            continue; // skip nodes already fixed by Dirichlet
        }
        // Constraint: A_z[left] + A_z[right] = 0
        k.add(left, left, penalty);
        k.add(left, right, penalty);
        k.add(right, left, penalty);
        k.add(right, right, penalty);
        // RHS contribution is zero (target = 0).
    }
}

/// Compute gradient of linear basis functions for a triangle.
///
/// Returns (area, [[dφ1/dx, dφ1/dy], [dφ2/dx, dφ2/dy], [dφ3/dx, dφ3/dy]]).
pub fn triangle_gradients(
    nodes: &[[f64; 2]],
    i: usize,
    j: usize,
    m: usize,
) -> (f64, [[f64; 2]; 3]) {
    let [x1, y1] = nodes[i];
    let [x2, y2] = nodes[j];
    let [x3, y3] = nodes[m];

    let twice_area = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1);
    let area = twice_area.abs() / 2.0;

    if !twice_area.is_finite() || twice_area == 0.0 {
        return (0.0, [[0.0; 2]; 3]);
    }

    let inv_2a = 1.0 / twice_area;
    let grad = [
        [(y2 - y3) * inv_2a, (x3 - x2) * inv_2a],
        [(y3 - y1) * inv_2a, (x1 - x3) * inv_2a],
        [(y1 - y2) * inv_2a, (x2 - x1) * inv_2a],
    ];

    (area, grad)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::materials::MaterialProps;
    use crate::mesh::{MeshInfo, Region, TriMesh};
    use crate::postprocess::{
        compute_element_fields, compute_flux_linkage, project_field_to_polar,
    };
    use crate::sparse::pcg_solve;
    use std::f64::consts::PI;

    #[derive(Clone, Copy)]
    struct TestRadialLayerSpec {
        r_outer_mm: f64,
        n_radial: usize,
        region: Region,
        material: MaterialProps,
        current_density_a_per_m2: f64,
    }

    #[test]
    fn test_triangle_gradients_unit() {
        // Right triangle: (0,0), (1,0), (0,1)
        let nodes = vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]];
        let (area, grad) = triangle_gradients(&nodes, 0, 1, 2);

        assert!((area - 0.5).abs() < 1e-10);
        assert!((grad[0][0] - (-1.0)).abs() < 1e-10);
        assert!((grad[0][1] - (-1.0)).abs() < 1e-10);
        assert!((grad[1][0] - 1.0).abs() < 1e-10);
        assert!((grad[1][1] - 0.0).abs() < 1e-10);
        assert!((grad[2][0] - 0.0).abs() < 1e-10);
        assert!((grad[2][1] - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_gradients_sum_to_zero() {
        let nodes = vec![[1.0, 2.0], [4.0, 1.0], [2.0, 5.0]];
        let (_area, grad) = triangle_gradients(&nodes, 0, 1, 2);
        let sum_x: f64 = grad.iter().map(|g| g[0]).sum();
        let sum_y: f64 = grad.iter().map(|g| g[1]).sum();
        assert!(sum_x.abs() < 1e-10);
        assert!(sum_y.abs() < 1e-10);
    }

    #[test]
    fn test_pm_source_uses_rotated_gradient() {
        let mesh = TriMesh {
            nodes: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            triangles: vec![[0, 1, 2]],
            regions: vec![Region::Magnet],
            boundary_nodes: vec![],
            sector_edge_pairs: vec![],
            info: MeshInfo {
                num_nodes: 3,
                num_triangles: 1,
                pole_pitch_deg: 90.0,
                n_pole_pitches: 1,
                total_span_deg: 90.0,
                angular_divisions: 1,
                radial_rings: 1,
                mesh_density: "synthetic".to_string(),
                radial_layers: vec!["magnet".to_string()],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: None,
                magnet_outer_radius_mm: 0.0,
                magnet_embrace: 1.0,
                stator_inner_radius_mm: 0.0,
                stator_slot_outer_radius_mm: 0.0,
                stator_outer_radius_mm: 0.0,
            },
        };
        let materials = vec![MaterialProps::new(1.0, 2.0, 0.0)];
        let sources = assemble_source(&mesh, &materials, &[0.0], None);

        // For a unit right triangle and B_r along +x:
        // grad(phi_0)=(-1,-1), grad(phi_1)=(1,0), grad(phi_2)=(0,1)
        // rotated term = B_rx * dphi/dy - B_ry * dphi/dx = dphi/dy
        // so the local source should be proportional to [-1, 0, 1].
        let scale = materials[0].nu * materials[0].br * 0.5;
        assert!((sources[0] + scale).abs() < 1e-12);
        assert!(sources[1].abs() < 1e-12);
        assert!((sources[2] - scale).abs() < 1e-12);
    }

    #[test]
    fn test_direct_csr_stiffness_matches_coo_assembly() {
        let mesh = TriMesh {
            nodes: vec![[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            triangles: vec![[0, 1, 2], [0, 2, 3]],
            regions: vec![Region::Airgap, Region::Airgap],
            boundary_nodes: vec![0, 1, 2, 3],
            sector_edge_pairs: vec![],
            info: MeshInfo {
                num_nodes: 4,
                num_triangles: 2,
                pole_pitch_deg: 90.0,
                n_pole_pitches: 1,
                total_span_deg: 90.0,
                angular_divisions: 1,
                radial_rings: 1,
                mesh_density: "synthetic".to_string(),
                radial_layers: vec!["air".to_string()],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: None,
                magnet_outer_radius_mm: 0.0,
                magnet_embrace: 1.0,
                stator_inner_radius_mm: 0.0,
                stator_slot_outer_radius_mm: 0.0,
                stator_outer_radius_mm: 1.0,
            },
        };
        let materials = vec![MaterialProps::new(1.0, 0.0, 0.0); mesh.triangles.len()];

        let coo = assemble_stiffness(&mesh, &materials).to_csr();
        let pattern = stiffness_csr_pattern(&mesh, &[]);
        let direct = assemble_stiffness_with_pattern(&pattern, &mesh, &materials);

        let x = vec![0.25, -0.5, 0.75, 1.25];
        let mut coo_y = vec![0.0; mesh.nodes.len()];
        let mut direct_y = vec![0.0; mesh.nodes.len()];
        coo.mul_vec(&x, &mut coo_y);
        direct.mul_vec(&x, &mut direct_y);
        for (lhs, rhs) in coo_y.iter().zip(direct_y.iter()) {
            assert!((lhs - rhs).abs() < 1.0e-12, "{lhs} != {rhs}");
        }
    }

    fn build_concentric_test_mesh_with_span(
        layers: &[TestRadialLayerSpec],
        n_theta: usize,
        total_span_rad: f64,
    ) -> (TriMesh, Vec<MaterialProps>, Vec<f64>) {
        fn ring_start(ring_idx: usize, n_theta: usize) -> usize {
            if ring_idx == 0 {
                0
            } else {
                1 + (ring_idx - 1) * n_theta
            }
        }

        assert!(
            !layers.is_empty(),
            "concentric test mesh needs at least one layer"
        );
        let full_circle = (total_span_rad - 2.0 * PI).abs() < 1e-12;
        let n_theta_nodes = if full_circle { n_theta } else { n_theta + 1 };

        let total_radial_divisions: usize = layers.iter().map(|layer| layer.n_radial).sum();
        let mut radii = Vec::with_capacity(total_radial_divisions);
        let mut annulus_regions = Vec::with_capacity(total_radial_divisions);
        let mut annulus_materials = Vec::with_capacity(total_radial_divisions);
        let mut annulus_currents = Vec::with_capacity(total_radial_divisions);
        let mut previous_outer_mm = 0.0;
        for layer in layers {
            for idx in 1..=layer.n_radial {
                let radius_mm = previous_outer_mm
                    + (layer.r_outer_mm - previous_outer_mm) * idx as f64 / layer.n_radial as f64;
                radii.push(radius_mm);
                annulus_regions.push(layer.region);
                annulus_materials.push(layer.material);
                annulus_currents.push(layer.current_density_a_per_m2);
            }
            previous_outer_mm = layer.r_outer_mm;
        }

        let mut nodes = Vec::with_capacity(1 + radii.len() * n_theta_nodes);
        nodes.push([0.0, 0.0]);
        for radius_mm in &radii {
            let radius_m = radius_mm * 1e-3;
            for sector in 0..n_theta_nodes {
                let theta = total_span_rad * sector as f64 / n_theta as f64;
                nodes.push([radius_m * theta.cos(), radius_m * theta.sin()]);
            }
        }

        let mut triangles = Vec::new();
        let mut regions = Vec::new();
        let mut materials = Vec::new();
        let mut current_densities = Vec::new();

        for sector in 0..n_theta {
            let next = if full_circle {
                (sector + 1) % n_theta_nodes
            } else {
                sector + 1
            };
            triangles.push([
                0,
                ring_start(1, n_theta_nodes) + sector,
                ring_start(1, n_theta_nodes) + next,
            ]);
            regions.push(annulus_regions[0]);
            materials.push(annulus_materials[0]);
            current_densities.push(annulus_currents[0]);
        }

        for ring_idx in 1..radii.len() {
            let inner_start = ring_start(ring_idx, n_theta_nodes);
            let outer_start = ring_start(ring_idx + 1, n_theta_nodes);
            let region = annulus_regions[ring_idx];
            let material = annulus_materials[ring_idx];
            let jz = annulus_currents[ring_idx];

            for sector in 0..n_theta {
                let next = if full_circle {
                    (sector + 1) % n_theta_nodes
                } else {
                    sector + 1
                };
                triangles.push([
                    inner_start + sector,
                    outer_start + sector,
                    inner_start + next,
                ]);
                regions.push(region);
                materials.push(material);
                current_densities.push(jz);

                triangles.push([inner_start + next, outer_start + sector, outer_start + next]);
                regions.push(region);
                materials.push(material);
                current_densities.push(jz);
            }
        }

        let outer_ring_start = ring_start(radii.len(), n_theta_nodes);
        let boundary_nodes = (0..n_theta_nodes)
            .map(|sector| outer_ring_start + sector)
            .collect();
        let num_triangles = triangles.len();
        let sector_edge_pairs = if full_circle {
            vec![]
        } else {
            (1..=radii.len())
                .map(|ring_idx| {
                    let start = ring_start(ring_idx, n_theta_nodes);
                    (start, start + n_theta)
                })
                .collect()
        };

        let mesh = TriMesh {
            nodes,
            triangles,
            regions,
            boundary_nodes,
            sector_edge_pairs,
            info: MeshInfo {
                num_nodes: 1 + radii.len() * n_theta_nodes,
                num_triangles,
                pole_pitch_deg: total_span_rad.to_degrees(),
                n_pole_pitches: 1,
                total_span_deg: total_span_rad.to_degrees(),
                angular_divisions: n_theta,
                radial_rings: 1 + radii.len(),
                mesh_density: "synthetic".to_string(),
                radial_layers: vec!["test_layers".to_string()],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: None,
                magnet_outer_radius_mm: 0.0,
                magnet_embrace: 1.0,
                stator_inner_radius_mm: 0.0,
                stator_slot_outer_radius_mm: 0.0,
                stator_outer_radius_mm: 0.0,
            },
        };

        (mesh, materials, current_densities)
    }

    fn build_concentric_test_mesh(
        layers: &[TestRadialLayerSpec],
        n_theta: usize,
    ) -> (TriMesh, Vec<MaterialProps>, Vec<f64>) {
        build_concentric_test_mesh_with_span(layers, n_theta, 2.0 * PI)
    }

    fn build_uniform_current_cylinder_mesh(
        conductor_radius_mm: f64,
        outer_radius_mm: f64,
        current_density_a_per_m2: f64,
        n_radial_conductor: usize,
        n_radial_air: usize,
        n_theta: usize,
    ) -> (TriMesh, Vec<MaterialProps>, Vec<f64>) {
        build_concentric_test_mesh(
            &[
                TestRadialLayerSpec {
                    r_outer_mm: conductor_radius_mm,
                    n_radial: n_radial_conductor,
                    region: Region::SlotWinding,
                    material: MaterialProps::air(),
                    current_density_a_per_m2,
                },
                TestRadialLayerSpec {
                    r_outer_mm: outer_radius_mm,
                    n_radial: n_radial_air,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
            ],
            n_theta,
        )
    }

    fn build_single_slot_flux_mesh(
        bore_radius_mm: f64,
        slot_outer_radius_mm: f64,
        outer_radius_mm: f64,
        slot_half_width_rad: f64,
        steel_mu_rel: f64,
        current_density_a_per_m2: f64,
        n_radial_bore: usize,
        n_radial_slot: usize,
        n_radial_yoke: usize,
        n_theta: usize,
    ) -> (TriMesh, Vec<MaterialProps>, Vec<f64>) {
        fn ring_start(ring_idx: usize, n_theta: usize) -> usize {
            if ring_idx == 0 {
                0
            } else {
                1 + (ring_idx - 1) * n_theta
            }
        }

        let total_radial_divisions = n_radial_bore + n_radial_slot + n_radial_yoke;
        let mut radii_mm = Vec::with_capacity(total_radial_divisions);
        for idx in 1..=n_radial_bore {
            radii_mm.push(bore_radius_mm * idx as f64 / n_radial_bore as f64);
        }
        for idx in 1..=n_radial_slot {
            radii_mm.push(
                bore_radius_mm
                    + (slot_outer_radius_mm - bore_radius_mm) * idx as f64 / n_radial_slot as f64,
            );
        }
        for idx in 1..=n_radial_yoke {
            radii_mm.push(
                slot_outer_radius_mm
                    + (outer_radius_mm - slot_outer_radius_mm) * idx as f64 / n_radial_yoke as f64,
            );
        }

        let mut nodes = Vec::with_capacity(1 + radii_mm.len() * n_theta);
        nodes.push([0.0, 0.0]);
        for radius_mm in &radii_mm {
            let radius_m = radius_mm * 1e-3;
            for sector in 0..n_theta {
                let theta = 2.0 * PI * sector as f64 / n_theta as f64;
                nodes.push([radius_m * theta.cos(), radius_m * theta.sin()]);
            }
        }

        let mut triangles = Vec::new();
        let mut regions = Vec::new();
        let mut materials = Vec::new();
        let mut current_densities = Vec::new();

        let classify_annulus = |inner_r_mm: f64, outer_r_mm: f64, theta_center: f64| {
            let r_mid_mm = 0.5 * (inner_r_mm + outer_r_mm);
            if r_mid_mm <= bore_radius_mm {
                return (Region::Airgap, MaterialProps::air(), 0.0);
            }
            if r_mid_mm <= slot_outer_radius_mm {
                let wrapped_theta = (theta_center + PI).rem_euclid(2.0 * PI) - PI;
                if wrapped_theta.abs() <= slot_half_width_rad {
                    return (
                        Region::SlotWinding,
                        MaterialProps::air(),
                        current_density_a_per_m2,
                    );
                }
                return (
                    Region::StatorTooth,
                    MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                    0.0,
                );
            }
            (
                Region::StatorYoke,
                MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                0.0,
            )
        };

        for sector in 0..n_theta {
            let next = (sector + 1) % n_theta;
            let theta_center = 2.0 * PI * (sector as f64 + 0.5) / n_theta as f64;
            let (region, material, current_density) =
                classify_annulus(0.0, radii_mm[0], theta_center);
            triangles.push([
                0,
                ring_start(1, n_theta) + sector,
                ring_start(1, n_theta) + next,
            ]);
            regions.push(region);
            materials.push(material);
            current_densities.push(current_density);
        }

        for ring_idx in 1..radii_mm.len() {
            let inner_start = ring_start(ring_idx, n_theta);
            let outer_start = ring_start(ring_idx + 1, n_theta);
            let inner_r_mm = radii_mm[ring_idx - 1];
            let outer_r_mm = radii_mm[ring_idx];

            for sector in 0..n_theta {
                let next = (sector + 1) % n_theta;
                let theta_center = 2.0 * PI * (sector as f64 + 0.5) / n_theta as f64;
                let (region, material, current_density) =
                    classify_annulus(inner_r_mm, outer_r_mm, theta_center);

                triangles.push([
                    inner_start + sector,
                    outer_start + sector,
                    inner_start + next,
                ]);
                regions.push(region);
                materials.push(material);
                current_densities.push(current_density);

                triangles.push([inner_start + next, outer_start + sector, outer_start + next]);
                regions.push(region);
                materials.push(material);
                current_densities.push(current_density);
            }
        }

        let outer_ring_start = ring_start(radii_mm.len(), n_theta);
        let boundary_nodes = (0..n_theta)
            .map(|sector| outer_ring_start + sector)
            .collect();
        let num_triangles = triangles.len();

        let mesh = TriMesh {
            nodes,
            triangles,
            regions,
            boundary_nodes,
            sector_edge_pairs: vec![],
            info: MeshInfo {
                num_nodes: 1 + radii_mm.len() * n_theta,
                num_triangles,
                pole_pitch_deg: 180.0,
                n_pole_pitches: 2,
                total_span_deg: 360.0,
                angular_divisions: n_theta,
                radial_rings: 1 + radii_mm.len(),
                mesh_density: "synthetic".to_string(),
                radial_layers: vec![
                    "bore_air".to_string(),
                    "slot_ring".to_string(),
                    "stator_yoke".to_string(),
                ],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: None,
                magnet_outer_radius_mm: 0.0,
                magnet_embrace: 1.0,
                stator_inner_radius_mm: 0.0,
                stator_slot_outer_radius_mm: 0.0,
                stator_outer_radius_mm: 0.0,
            },
        };

        (mesh, materials, current_densities)
    }

    fn triangle_centroids(mesh: &TriMesh) -> Vec<[f64; 2]> {
        mesh.triangles
            .iter()
            .map(|tri| {
                let [i, j, k] = *tri;
                let [x1, y1] = mesh.nodes[i];
                let [x2, y2] = mesh.nodes[j];
                let [x3, y3] = mesh.nodes[k];
                [(x1 + x2 + x3) / 3.0, (y1 + y2 + y3) / 3.0]
            })
            .collect()
    }

    fn barycentric_weights(point_xy_m: [f64; 2], tri_xy_m: [[f64; 2]; 3]) -> Option<[f64; 3]> {
        let [px, py] = point_xy_m;
        let [[x1, y1], [x2, y2], [x3, y3]] = tri_xy_m;
        let det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3);
        if det.abs() < 1e-18 {
            return None;
        }
        let w1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / det;
        let w2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / det;
        let w3 = 1.0 - w1 - w2;
        let tol = 1e-9;
        if w1 < -tol || w2 < -tol || w3 < -tol {
            return None;
        }
        Some([w1, w2, w3])
    }

    fn triangle_area_local(nodes: &[[f64; 2]], i: usize, j: usize, k: usize) -> f64 {
        let [x1, y1] = nodes[i];
        let [x2, y2] = nodes[j];
        let [x3, y3] = nodes[k];
        ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)).abs() / 2.0
    }

    fn interpolate_az_at_point(mesh: &TriMesh, az: &[f64], point_xy_m: [f64; 2]) -> Option<f64> {
        for tri in &mesh.triangles {
            let [i, j, k] = *tri;
            let tri_xy_m = [mesh.nodes[i], mesh.nodes[j], mesh.nodes[k]];
            let Some(weights) = barycentric_weights(point_xy_m, tri_xy_m) else {
                continue;
            };
            return Some(weights[0] * az[i] + weights[1] * az[j] + weights[2] * az[k]);
        }
        None
    }

    fn single_slot_sample_points(
        bore_radius_mm: f64,
        slot_outer_radius_mm: f64,
        slot_half_width_rad: f64,
    ) -> Vec<[f64; 2]> {
        let radial_fracs = [0.25, 0.5, 0.75];
        let angular_fracs = [-0.6, 0.0, 0.6];
        let effective_half_width = slot_half_width_rad * 0.8;
        let radial_span_mm = slot_outer_radius_mm - bore_radius_mm;
        let mut points = Vec::new();
        for radial_frac in radial_fracs {
            let radius_m = (bore_radius_mm + radial_span_mm * radial_frac) * 1e-3;
            for angular_frac in angular_fracs {
                let theta = effective_half_width * angular_frac;
                points.push([radius_m * theta.cos(), radius_m * theta.sin()]);
            }
        }
        points
    }

    fn area_weighted_region_average_az(
        mesh: &TriMesh,
        az: &[f64],
        target_region: Region,
    ) -> Option<(f64, f64)> {
        let mut az_area_sum = 0.0;
        let mut area_sum = 0.0;
        for (idx, tri) in mesh.triangles.iter().enumerate() {
            if mesh.regions[idx] != target_region {
                continue;
            }
            let [i, j, k] = *tri;
            let area = triangle_area_local(&mesh.nodes, i, j, k);
            let az_avg = (az[i] + az[j] + az[k]) / 3.0;
            az_area_sum += az_avg * area;
            area_sum += area;
        }
        if area_sum < 1e-18 {
            None
        } else {
            Some((az_area_sum / area_sum, area_sum))
        }
    }

    fn annulus_average_b_theta(
        centroids: &[[f64; 2]],
        fields: &[crate::postprocess::ElementField],
        target_radius_mm: f64,
        band_half_width_mm: f64,
    ) -> Option<f64> {
        let mut sum = 0.0;
        let mut count = 0usize;

        for (centroid, field) in centroids.iter().zip(fields.iter()) {
            let r_m = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
            let r_mm = r_m * 1e3;
            if (r_mm - target_radius_mm).abs() > band_half_width_mm || r_mm < 1e-9 {
                continue;
            }
            let cos_theta = centroid[0] / r_m;
            let sin_theta = centroid[1] / r_m;
            let b_theta = -field.bx * sin_theta + field.by * cos_theta;
            sum += b_theta;
            count += 1;
        }

        if count == 0 {
            None
        } else {
            Some(sum / count as f64)
        }
    }

    fn annulus_average_field_vector(
        centroids: &[[f64; 2]],
        fields: &[crate::postprocess::ElementField],
        target_radius_mm: f64,
        band_half_width_mm: f64,
    ) -> Option<(f64, f64)> {
        let mut sum_bx = 0.0;
        let mut sum_by = 0.0;
        let mut count = 0usize;

        for (centroid, field) in centroids.iter().zip(fields.iter()) {
            let r_m = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
            let r_mm = r_m * 1e3;
            if (r_mm - target_radius_mm).abs() > band_half_width_mm {
                continue;
            }
            sum_bx += field.bx;
            sum_by += field.by;
            count += 1;
        }

        if count == 0 {
            None
        } else {
            Some((sum_bx / count as f64, sum_by / count as f64))
        }
    }

    fn theoretical_b_theta_t(
        radius_mm: f64,
        conductor_radius_mm: f64,
        current_density_a_per_m2: f64,
    ) -> f64 {
        let radius_m = radius_mm * 1e-3;
        let conductor_radius_m = conductor_radius_mm * 1e-3;
        if radius_m < conductor_radius_m {
            crate::materials::MU_0 * current_density_a_per_m2 * radius_m / 2.0
        } else {
            crate::materials::MU_0
                * current_density_a_per_m2
                * conductor_radius_m
                * conductor_radius_m
                / (2.0 * radius_m)
        }
    }

    fn theoretical_two_material_coaxial_b_theta_t(
        radius_mm: f64,
        conductor_radius_mm: f64,
        steel_outer_radius_mm: f64,
        steel_mu_rel: f64,
        current_density_a_per_m2: f64,
    ) -> f64 {
        let radius_m = radius_mm * 1e-3;
        let conductor_radius_m = conductor_radius_mm * 1e-3;
        if radius_m < conductor_radius_m {
            return crate::materials::MU_0 * current_density_a_per_m2 * radius_m / 2.0;
        }

        let base_h =
            current_density_a_per_m2 * conductor_radius_m * conductor_radius_m / (2.0 * radius_m);
        if radius_mm < steel_outer_radius_mm {
            crate::materials::MU_0 * steel_mu_rel * base_h
        } else {
            crate::materials::MU_0 * base_h
        }
    }

    fn halbach_dipole_theoretical_bore_field_t(
        magnet_br_t: f64,
        bore_radius_mm: f64,
        magnet_outer_radius_mm: f64,
    ) -> f64 {
        magnet_br_t * (magnet_outer_radius_mm / bore_radius_mm).ln()
    }

    fn radial_pm_ring_with_steel_return_path_bore_field_t(
        bore_radius_mm: f64,
        magnet_outer_radius_mm: f64,
        steel_outer_radius_mm: f64,
        steel_mu_rel: f64,
        magnet_br_t: f64,
    ) -> f64 {
        let a_over_b = bore_radius_mm / magnet_outer_radius_mm;
        let a2_over_b2 = a_over_b * a_over_b;
        let c_over_b = steel_outer_radius_mm / magnet_outer_radius_mm;
        let s = c_over_b * c_over_b;
        let delta = 0.5 * magnet_br_t * (1.0 - a2_over_b2) / ((1.0 - s) - (1.0 + s) / steel_mu_rel);
        let alpha = delta * (1.0 - s)
            + magnet_br_t
                * (0.25 * a2_over_b2 - 0.25 + 0.5 * (magnet_outer_radius_mm / bore_radius_mm).ln());
        alpha.abs()
    }

    #[test]
    fn uniform_current_cylinder_benchmark_reports_theory_error() {
        let conductor_radius_mm = 10.0;
        let outer_radius_mm = 40.0;
        let current_density_a_per_m2 = 5.0e6;
        let sample_radii_mm = [5.0, 8.0, 15.0, 25.0];

        let (mesh, materials, current_densities) = build_uniform_current_cylinder_mesh(
            conductor_radius_mm,
            outer_radius_mm,
            current_density_a_per_m2,
            10,
            30,
            96,
        );

        let mut stiffness = assemble_stiffness(&mesh, &materials).to_csr();
        let mut rhs = assemble_source(&mesh, &materials, &current_densities, None);
        stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
        let az = pcg_solve(&stiffness, &rhs, 5000, 1e-10)
            .expect("uniform current cylinder should solve");

        let max_boundary_abs = mesh
            .boundary_nodes
            .iter()
            .map(|&node| az[node].abs())
            .fold(0.0_f64, f64::max);
        assert!(
            max_boundary_abs < 1e-10,
            "Dirichlet boundary drifted: {max_boundary_abs:e}"
        );

        let fields = compute_element_fields(&mesh, &az);
        let centroids = triangle_centroids(&mesh);

        let mut max_rel_err_pct: f64 = 0.0;
        for radius_mm in sample_radii_mm {
            let modeled_b_theta = annulus_average_b_theta(&centroids, &fields, radius_mm, 0.45)
                .unwrap_or_else(|| panic!("no sampled elements near r={radius_mm}mm"));
            let theory_b_theta =
                theoretical_b_theta_t(radius_mm, conductor_radius_mm, current_density_a_per_m2);
            let rel_err_pct = ((modeled_b_theta - theory_b_theta) / theory_b_theta).abs() * 100.0;
            max_rel_err_pct = max_rel_err_pct.max(rel_err_pct);

            eprintln!(
                "current-cylinder benchmark: r={radius_mm:.1}mm theory={theory_b_theta:.6e}T magneto2d={modeled_b_theta:.6e}T rel_err={rel_err_pct:.2}%"
            );

            assert!(modeled_b_theta.is_finite());
            assert!(modeled_b_theta > 0.0);
        }

        eprintln!(
            "current-cylinder benchmark: max relative error vs theory = {max_rel_err_pct:.2}%"
        );
        assert!(
            max_rel_err_pct < 5.0,
            "current cylinder benchmark drifted too far from theory"
        );
    }

    #[test]
    fn two_material_coaxial_ring_matches_piecewise_theory() {
        let conductor_radius_mm = 5.0;
        let steel_outer_radius_mm = 15.0;
        let outer_radius_mm = 40.0;
        let steel_mu_rel = 100.0;
        let current_density_a_per_m2 = 5.0e6;
        let sample_radii_mm = [2.5, 8.0, 12.0, 20.0, 30.0];

        let (mesh, materials, current_densities) = build_concentric_test_mesh(
            &[
                TestRadialLayerSpec {
                    r_outer_mm: conductor_radius_mm,
                    n_radial: 8,
                    region: Region::SlotWinding,
                    material: MaterialProps::air(),
                    current_density_a_per_m2,
                },
                TestRadialLayerSpec {
                    r_outer_mm: steel_outer_radius_mm,
                    n_radial: 16,
                    region: Region::StatorYoke,
                    material: MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: outer_radius_mm,
                    n_radial: 24,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
            ],
            192,
        );

        let mut stiffness = assemble_stiffness(&mesh, &materials).to_csr();
        let mut rhs = assemble_source(&mesh, &materials, &current_densities, None);
        stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
        let az = pcg_solve(&stiffness, &rhs, 5000, 1e-10)
            .expect("two-material coaxial ring should solve");

        let fields = compute_element_fields(&mesh, &az);
        let centroids = triangle_centroids(&mesh);

        let mut max_rel_err_pct: f64 = 0.0;
        for radius_mm in sample_radii_mm {
            let modeled_b_theta = annulus_average_b_theta(&centroids, &fields, radius_mm, 0.35)
                .unwrap_or_else(|| panic!("no sampled elements near r={radius_mm}mm"));
            let theory_b_theta = theoretical_two_material_coaxial_b_theta_t(
                radius_mm,
                conductor_radius_mm,
                steel_outer_radius_mm,
                steel_mu_rel,
                current_density_a_per_m2,
            );
            let rel_err_pct = ((modeled_b_theta - theory_b_theta) / theory_b_theta).abs() * 100.0;
            max_rel_err_pct = max_rel_err_pct.max(rel_err_pct);

            eprintln!(
                "two-material coaxial benchmark: r={radius_mm:.1}mm theory={theory_b_theta:.6e}T magneto2d={modeled_b_theta:.6e}T rel_err={rel_err_pct:.2}%"
            );
        }

        eprintln!(
            "two-material coaxial benchmark: max relative error vs theory = {max_rel_err_pct:.2}%"
        );
        assert!(
            max_rel_err_pct < 5.0,
            "two-material coaxial benchmark drifted too far from theory"
        );
    }

    #[test]
    fn halbach_pm_ring_matches_uniform_bore_field_theory() {
        let bore_radius_mm = 10.0;
        let magnet_outer_radius_mm = 20.0;
        let outer_radius_mm = 80.0;
        let magnet_br_t = 1.0;
        let bore_sample_radii_mm = [2.0, 5.0, 8.0];
        let outside_sample_radii_mm = [30.0, 50.0];

        let (mesh, _materials_unused, current_densities) = build_concentric_test_mesh(
            &[
                TestRadialLayerSpec {
                    r_outer_mm: bore_radius_mm,
                    n_radial: 12,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: magnet_outer_radius_mm,
                    n_radial: 14,
                    region: Region::Magnet,
                    material: MaterialProps::new(1.0, magnet_br_t, 0.0),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: outer_radius_mm,
                    n_radial: 40,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
            ],
            288,
        );

        let centroids = triangle_centroids(&mesh);
        let materials: Vec<MaterialProps> = mesh
            .regions
            .iter()
            .enumerate()
            .map(|(idx, region)| match region {
                Region::Magnet => {
                    let theta = centroids[idx][1].atan2(centroids[idx][0]);
                    // Ideal p=1 internal-field Halbach: global magnetization angle = 2θ.
                    MaterialProps::new(1.0, magnet_br_t, 2.0 * theta)
                }
                _ => MaterialProps::air(),
            })
            .collect();

        let mut stiffness = assemble_stiffness(&mesh, &materials).to_csr();
        let mut rhs = assemble_source(&mesh, &materials, &current_densities, None);
        stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
        let az = pcg_solve(&stiffness, &rhs, 6000, 1e-10).expect("Halbach PM ring should solve");

        let fields = compute_element_fields(&mesh, &az);
        let theory_bore_t = halbach_dipole_theoretical_bore_field_t(
            magnet_br_t,
            bore_radius_mm,
            magnet_outer_radius_mm,
        );

        let mut max_bore_rel_err_pct: f64 = 0.0;
        for radius_mm in bore_sample_radii_mm {
            let (bx, by) = annulus_average_field_vector(&centroids, &fields, radius_mm, 0.35)
                .unwrap_or_else(|| panic!("no sampled elements near Halbach bore r={radius_mm}mm"));
            let b_mag = (bx * bx + by * by).sqrt();
            let rel_err_pct = ((b_mag - theory_bore_t) / theory_bore_t).abs() * 100.0;
            max_bore_rel_err_pct = max_bore_rel_err_pct.max(rel_err_pct);
            eprintln!(
                "halbach benchmark bore: r={radius_mm:.1}mm theory={theory_bore_t:.6e}T Bx={bx:.6e}T By={by:.6e}T |B|={b_mag:.6e}T rel_err={rel_err_pct:.2}%"
            );
            assert!(
                rel_err_pct < 5.0,
                "Halbach bore field drifted too far from theory"
            );
        }

        for radius_mm in outside_sample_radii_mm {
            let (bx, by) = annulus_average_field_vector(&centroids, &fields, radius_mm, 0.5)
                .unwrap_or_else(|| {
                    panic!("no sampled elements near Halbach outside r={radius_mm}mm")
                });
            let b_mag = (bx * bx + by * by).sqrt();
            eprintln!(
                "halbach benchmark outside: r={radius_mm:.1}mm Bx={bx:.6e}T By={by:.6e}T |B|={b_mag:.6e}T"
            );
            assert!(
                b_mag < theory_bore_t * 0.05,
                "Halbach external field cancellation regressed"
            );
        }

        eprintln!(
            "halbach benchmark: max bore relative error vs theory = {max_bore_rel_err_pct:.2}%"
        );
    }

    #[test]
    fn halbach_pm_ring_bore_projection_matches_theoretical_br_bt_waveform() {
        let bore_radius_mm = 10.0;
        let magnet_outer_radius_mm = 20.0;
        let outer_radius_mm = 80.0;
        let magnet_br_t = 1.0;

        let (mesh, _materials_unused, current_densities) = build_concentric_test_mesh(
            &[
                TestRadialLayerSpec {
                    r_outer_mm: bore_radius_mm,
                    n_radial: 12,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: magnet_outer_radius_mm,
                    n_radial: 14,
                    region: Region::Magnet,
                    material: MaterialProps::new(1.0, magnet_br_t, 0.0),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: outer_radius_mm,
                    n_radial: 40,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
            ],
            288,
        );

        let centroids = triangle_centroids(&mesh);
        let materials: Vec<MaterialProps> = mesh
            .regions
            .iter()
            .enumerate()
            .map(|(idx, region)| match region {
                Region::Magnet => {
                    let theta = centroids[idx][1].atan2(centroids[idx][0]);
                    MaterialProps::new(1.0, magnet_br_t, 2.0 * theta)
                }
                _ => MaterialProps::air(),
            })
            .collect();

        let mut stiffness = assemble_stiffness(&mesh, &materials).to_csr();
        let mut rhs = assemble_source(&mesh, &materials, &current_densities, None);
        stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
        let az = pcg_solve(&stiffness, &rhs, 6000, 1e-10).expect("Halbach PM ring should solve");

        let fields = compute_element_fields(&mesh, &az);
        let theory_bore_t = halbach_dipole_theoretical_bore_field_t(
            magnet_br_t,
            bore_radius_mm,
            magnet_outer_radius_mm,
        );

        let bore_radius_m = bore_radius_mm * 1e-3;
        let sample_band_m = 0.8e-3;
        let mut br_sq_error = 0.0;
        let mut bt_sq_error = 0.0;
        let mut sample_count = 0usize;

        for (idx, centroid) in centroids.iter().enumerate() {
            if mesh.regions[idx] != Region::Airgap {
                continue;
            }
            let r = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
            if r > bore_radius_m - sample_band_m {
                continue;
            }

            let theta = centroid[1].atan2(centroid[0]);
            let (b_r, b_t) = project_field_to_polar(&fields[idx], *centroid)
                .expect("bore centroids should be away from origin");
            let theory_br = theory_bore_t * theta.cos();
            let theory_bt = -theory_bore_t * theta.sin();

            br_sq_error += (b_r - theory_br) * (b_r - theory_br);
            bt_sq_error += (b_t - theory_bt) * (b_t - theory_bt);
            sample_count += 1;
        }

        assert!(sample_count > 0, "expected to sample bore-region centroids");
        let br_rms_rel_pct = (br_sq_error / sample_count as f64).sqrt() / theory_bore_t * 100.0;
        let bt_rms_rel_pct = (bt_sq_error / sample_count as f64).sqrt() / theory_bore_t * 100.0;
        eprintln!(
            "halbach bore projection benchmark: Br RMS error={br_rms_rel_pct:.2}% Bt RMS error={bt_rms_rel_pct:.2}% over {sample_count} bore elements"
        );

        assert!(
            br_rms_rel_pct < 5.0,
            "Halbach Br projection drifted too far from theory"
        );
        assert!(
            bt_rms_rel_pct < 5.0,
            "Halbach Bt projection drifted too far from theory"
        );
    }

    #[test]
    fn radial_pm_ring_with_steel_return_path_matches_bore_field_theory() {
        let bore_radius_mm = 10.0;
        let magnet_outer_radius_mm = 20.0;
        let steel_outer_radius_mm = 40.0;
        let steel_mu_rel = 100.0;
        let magnet_br_t = 1.0;
        let bore_sample_radii_mm = [2.0, 5.0, 8.0];

        let (mesh, _materials_unused, current_densities) = build_concentric_test_mesh(
            &[
                TestRadialLayerSpec {
                    r_outer_mm: bore_radius_mm,
                    n_radial: 12,
                    region: Region::Airgap,
                    material: MaterialProps::air(),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: magnet_outer_radius_mm,
                    n_radial: 14,
                    region: Region::Magnet,
                    material: MaterialProps::new(1.0, magnet_br_t, 0.0),
                    current_density_a_per_m2: 0.0,
                },
                TestRadialLayerSpec {
                    r_outer_mm: steel_outer_radius_mm,
                    n_radial: 24,
                    region: Region::StatorYoke,
                    material: MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                    current_density_a_per_m2: 0.0,
                },
            ],
            288,
        );

        let centroids = triangle_centroids(&mesh);
        let materials: Vec<MaterialProps> = mesh
            .regions
            .iter()
            .enumerate()
            .map(|(idx, region)| match region {
                Region::Magnet => {
                    let theta = centroids[idx][1].atan2(centroids[idx][0]);
                    let radial_harmonic = theta.cos();
                    let br = magnet_br_t * radial_harmonic.abs();
                    let mag_angle = if radial_harmonic >= 0.0 {
                        theta
                    } else {
                        theta + PI
                    };
                    MaterialProps::new(1.0, br, mag_angle)
                }
                Region::StatorYoke => MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                _ => MaterialProps::air(),
            })
            .collect();

        let mut stiffness = assemble_stiffness(&mesh, &materials).to_csr();
        let mut rhs = assemble_source(&mesh, &materials, &current_densities, None);
        stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
        let az = pcg_solve(&stiffness, &rhs, 6000, 1e-10)
            .expect("PM ring with steel return path should solve");

        let fields = compute_element_fields(&mesh, &az);
        let theory_bore_t = radial_pm_ring_with_steel_return_path_bore_field_t(
            bore_radius_mm,
            magnet_outer_radius_mm,
            steel_outer_radius_mm,
            steel_mu_rel,
            magnet_br_t,
        );

        let mut max_bore_rel_err_pct: f64 = 0.0;
        for radius_mm in bore_sample_radii_mm {
            let (bx, by) = annulus_average_field_vector(&centroids, &fields, radius_mm, 0.35)
                .unwrap_or_else(|| {
                    panic!("no sampled elements near steel-return bore r={radius_mm}mm")
                });
            let b_mag = (bx * bx + by * by).sqrt();
            let rel_err_pct = ((b_mag - theory_bore_t) / theory_bore_t).abs() * 100.0;
            max_bore_rel_err_pct = max_bore_rel_err_pct.max(rel_err_pct);
            eprintln!(
                "steel-return PM benchmark bore: r={radius_mm:.1}mm theory={theory_bore_t:.6e}T Bx={bx:.6e}T By={by:.6e}T |B|={b_mag:.6e}T rel_err={rel_err_pct:.2}%"
            );
            assert!(bx > 0.0, "steel-return bore field should point along +x");
            assert!(
                by.abs() < theory_bore_t * 0.05,
                "steel-return bore field drifted off-axis"
            );
            assert!(
                rel_err_pct < 5.0,
                "steel-return bore field drifted too far from theory"
            );
        }

        eprintln!(
            "steel-return PM benchmark: max bore relative error vs theory = {max_bore_rel_err_pct:.2}%"
        );
    }

    #[test]
    fn single_slot_flux_linkage_benchmark_reports_area_and_sample_averages() {
        let bore_radius_mm = 20.0;
        let slot_outer_radius_mm = 34.0;
        let outer_radius_mm = 55.0;
        let slot_half_width_rad = 8.0_f64.to_radians();
        let steel_mu_rel = 100.0;
        let current_density_a_per_m2 = 5.0e6;
        let stack_length_mm = 100.0;
        let turns_per_coil = 1;
        let slot_count = 1;
        let pole_count = 2;

        let (mesh, materials, current_densities) = build_single_slot_flux_mesh(
            bore_radius_mm,
            slot_outer_radius_mm,
            outer_radius_mm,
            slot_half_width_rad,
            steel_mu_rel,
            current_density_a_per_m2,
            10,
            14,
            18,
            360,
        );

        let mut stiffness = assemble_stiffness(&mesh, &materials).to_csr();
        let mut rhs = assemble_source(&mesh, &materials, &current_densities, None);
        stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
        let az = pcg_solve(&stiffness, &rhs, 6000, 1e-10)
            .expect("single-slot flux benchmark should solve");

        let centroids = triangle_centroids(&mesh);
        let (slot_area_avg_az, slot_area_m2) =
            area_weighted_region_average_az(&mesh, &az, Region::SlotWinding)
                .expect("single-slot benchmark should contain slot elements");

        let slot_sample_points =
            single_slot_sample_points(bore_radius_mm, slot_outer_radius_mm, slot_half_width_rad);
        let slot_sample_az: Vec<f64> = slot_sample_points
            .iter()
            .map(|point_xy_m| {
                interpolate_az_at_point(&mesh, &az, *point_xy_m)
                    .expect("slot sample point should land inside the mesh")
            })
            .collect();
        let slot_sample_avg_az = slot_sample_az.iter().sum::<f64>() / slot_sample_az.len() as f64;

        let (phase_flux, slot_contributions) = compute_flux_linkage(
            &mesh,
            &az,
            &centroids,
            stack_length_mm,
            "concentrated",
            slot_count,
            pole_count,
            turns_per_coil,
            1,
            None,
            1.0,
            false,
        );

        let expected_flux_wb = turns_per_coil as f64 * stack_length_mm * 1e-3 * slot_area_avg_az;
        let rel_sample_vs_area_pct =
            ((slot_sample_avg_az - slot_area_avg_az) / slot_area_avg_az).abs() * 100.0;
        let rel_flux_vs_area_pct =
            ((phase_flux[0] - expected_flux_wb) / expected_flux_wb).abs() * 100.0;

        eprintln!(
            "single-slot flux benchmark: slot_area={slot_area_m2:.6e}m^2 area_avg_Az={slot_area_avg_az:.6e}Wb/m sample_avg_Az={slot_sample_avg_az:.6e}Wb/m sample_vs_area={rel_sample_vs_area_pct:.2}% psi_A={:.6e}Wb expected_from_area={expected_flux_wb:.6e}Wb flux_vs_area={rel_flux_vs_area_pct:.3}%",
            phase_flux[0],
        );

        assert!(phase_flux[0].is_finite());
        assert!(phase_flux[0] > 0.0);
        assert_eq!(slot_contributions.len(), 1);
        assert_eq!(slot_contributions[0].phase, "A");
        assert_eq!(slot_contributions[0].direction, "in");
        assert!(phase_flux[1].abs() < 1e-12);
        assert!(phase_flux[2].abs() < 1e-12);
        assert!(rel_flux_vs_area_pct < 1e-9);
        assert!(rel_sample_vs_area_pct < 25.0);
    }

    #[test]
    fn radial_pm_ring_sector_antiperiodic_bc_matches_full_circle_bore_field() {
        let bore_radius_mm = 10.0;
        let magnet_outer_radius_mm = 20.0;
        let steel_outer_radius_mm = 40.0;
        let steel_mu_rel = 100.0;
        let magnet_br_t = 1.0;
        let sample_radii_mm = [2.0, 5.0, 8.0];
        let theory_bore_t = radial_pm_ring_with_steel_return_path_bore_field_t(
            bore_radius_mm,
            magnet_outer_radius_mm,
            steel_outer_radius_mm,
            steel_mu_rel,
            magnet_br_t,
        );

        let layer_specs = [
            TestRadialLayerSpec {
                r_outer_mm: bore_radius_mm,
                n_radial: 12,
                region: Region::Airgap,
                material: MaterialProps::air(),
                current_density_a_per_m2: 0.0,
            },
            TestRadialLayerSpec {
                r_outer_mm: magnet_outer_radius_mm,
                n_radial: 14,
                region: Region::Magnet,
                material: MaterialProps::new(1.0, magnet_br_t, 0.0),
                current_density_a_per_m2: 0.0,
            },
            TestRadialLayerSpec {
                r_outer_mm: steel_outer_radius_mm,
                n_radial: 24,
                region: Region::StatorYoke,
                material: MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                current_density_a_per_m2: 0.0,
            },
        ];

        let (full_mesh, _materials_unused, current_densities) =
            build_concentric_test_mesh(&layer_specs, 288);
        let full_centroids = triangle_centroids(&full_mesh);
        let full_materials: Vec<MaterialProps> = full_mesh
            .regions
            .iter()
            .enumerate()
            .map(|(idx, region)| match region {
                Region::Magnet => {
                    let theta = full_centroids[idx][1].atan2(full_centroids[idx][0]);
                    let radial_harmonic = theta.cos();
                    let br = magnet_br_t * radial_harmonic.abs();
                    let mag_angle = if radial_harmonic >= 0.0 {
                        theta
                    } else {
                        theta + PI
                    };
                    MaterialProps::new(1.0, br, mag_angle)
                }
                Region::StatorYoke => MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                _ => MaterialProps::air(),
            })
            .collect();

        let mut full_stiffness = assemble_stiffness(&full_mesh, &full_materials).to_csr();
        let mut full_rhs = assemble_source(&full_mesh, &full_materials, &current_densities, None);
        full_stiffness.apply_dirichlet(&mut full_rhs, &full_mesh.boundary_nodes);
        let full_az = pcg_solve(&full_stiffness, &full_rhs, 6000, 1e-10)
            .expect("full-circle PM ring should solve");
        let full_fields = compute_element_fields(&full_mesh, &full_az);

        let (sector_mesh, _materials_unused, sector_current_densities) =
            build_concentric_test_mesh_with_span(&layer_specs, 144, PI);
        let sector_centroids = triangle_centroids(&sector_mesh);
        let sector_materials: Vec<MaterialProps> = sector_mesh
            .regions
            .iter()
            .enumerate()
            .map(|(idx, region)| match region {
                Region::Magnet => {
                    let theta = sector_centroids[idx][1].atan2(sector_centroids[idx][0]);
                    let radial_harmonic = theta.cos();
                    let br = magnet_br_t * radial_harmonic.abs();
                    let mag_angle = if radial_harmonic >= 0.0 {
                        theta
                    } else {
                        theta + PI
                    };
                    MaterialProps::new(1.0, br, mag_angle)
                }
                Region::StatorYoke => MaterialProps::new(steel_mu_rel, 0.0, 0.0),
                _ => MaterialProps::air(),
            })
            .collect();

        let mut sector_stiffness = assemble_stiffness(&sector_mesh, &sector_materials);
        let mut sector_rhs = assemble_source(
            &sector_mesh,
            &sector_materials,
            &sector_current_densities,
            None,
        );
        apply_antiperiodic_bc(
            &mut sector_stiffness,
            &mut sector_rhs,
            &sector_mesh.sector_edge_pairs,
            &sector_mesh.boundary_nodes,
        );
        let mut sector_stiffness = sector_stiffness.to_csr();
        sector_stiffness.apply_dirichlet(&mut sector_rhs, &sector_mesh.boundary_nodes);
        let sector_az = pcg_solve(&sector_stiffness, &sector_rhs, 6000, 1e-10)
            .expect("anti-periodic sector PM ring should solve");
        let sector_fields = compute_element_fields(&sector_mesh, &sector_az);

        let mut max_pair_violation = 0.0_f64;
        let is_boundary: std::collections::HashSet<usize> =
            sector_mesh.boundary_nodes.iter().copied().collect();
        for &(left, right) in &sector_mesh.sector_edge_pairs {
            if is_boundary.contains(&left) || is_boundary.contains(&right) {
                continue;
            }
            max_pair_violation = max_pair_violation.max((sector_az[left] + sector_az[right]).abs());
        }
        eprintln!(
            "anti-periodic PM benchmark: max paired-edge violation = {max_pair_violation:.6e}"
        );
        assert!(
            max_pair_violation < 1e-6,
            "anti-periodic coupling drifted on sector edge pairs"
        );

        let mut max_rel_vs_full_pct = 0.0_f64;
        let mut max_rel_vs_theory_pct = 0.0_f64;
        for radius_mm in sample_radii_mm {
            let (full_bx, full_by) =
                annulus_average_field_vector(&full_centroids, &full_fields, radius_mm, 0.35)
                    .unwrap_or_else(|| panic!("no full-circle bore sample near r={radius_mm}mm"));
            let (sector_bx, sector_by) =
                annulus_average_field_vector(&sector_centroids, &sector_fields, radius_mm, 0.35)
                    .unwrap_or_else(|| panic!("no sector bore sample near r={radius_mm}mm"));

            let rel_vs_full_pct =
                ((sector_bx - full_bx).hypot(sector_by - full_by) / full_bx.hypot(full_by)) * 100.0;
            let rel_vs_theory_pct =
                ((sector_bx.hypot(sector_by) - theory_bore_t) / theory_bore_t).abs() * 100.0;
            max_rel_vs_full_pct = max_rel_vs_full_pct.max(rel_vs_full_pct);
            max_rel_vs_theory_pct = max_rel_vs_theory_pct.max(rel_vs_theory_pct);
            eprintln!(
                "anti-periodic PM benchmark: r={radius_mm:.1}mm full=({full_bx:.6e},{full_by:.6e})T sector=({sector_bx:.6e},{sector_by:.6e})T rel_vs_full={rel_vs_full_pct:.2}% rel_vs_theory={rel_vs_theory_pct:.2}%"
            );
        }

        eprintln!(
            "anti-periodic PM benchmark: max bore rel_vs_full={max_rel_vs_full_pct:.2}% rel_vs_theory={max_rel_vs_theory_pct:.2}%"
        );
        assert!(
            max_rel_vs_full_pct < 1.0,
            "anti-periodic sector bore field drifted too far from full-circle benchmark"
        );
        assert!(
            max_rel_vs_theory_pct < 5.0,
            "anti-periodic sector bore field drifted too far from theory"
        );
    }
}
