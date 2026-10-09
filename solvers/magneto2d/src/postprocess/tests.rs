use std::f64::consts::PI;

use super::{
    choose_az_contour_radial_step, compute_filtered_nodal_b_field, compute_nodal_b_field,
    compute_stator_core_loss, compute_torque, compute_torque_arkkio_debug,
    compute_torque_at_multiple_radii, compute_torque_at_multiple_radii_from_az,
    compute_torque_midgap_contour_debug_with_samples,
    compute_torque_midgap_contour_debug_with_samples_from_az, compute_torque_robust_contour_debug,
    compute_torque_weighted_stress_debug, compute_torque_weighted_stress_debug_with_az,
    project_field_to_polar, CoreLossSummary, ElementField,
};
use crate::materials::{assign_materials, SteinmetzCoefficients, MU_0};
use crate::mesh::{MeshInfo, Region, TriMesh};

fn simple_mesh(region: Region) -> TriMesh {
    TriMesh {
        nodes: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        triangles: vec![[0, 1, 2]],
        regions: vec![region],
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
            radial_layers: vec![],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 0.0,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 0.0,
            stator_slot_outer_radius_mm: 0.0,
            stator_outer_radius_mm: 0.0,
        },
    }
}

struct EnvVarGuard {
    name: &'static str,
    previous: Option<String>,
}

impl EnvVarGuard {
    fn set(name: &'static str, value: &str) -> Self {
        let previous = std::env::var(name).ok();
        std::env::set_var(name, value);
        Self { name, previous }
    }
}

impl Drop for EnvVarGuard {
    fn drop(&mut self) {
        if let Some(previous) = &self.previous {
            std::env::set_var(self.name, previous);
        } else {
            std::env::remove_var(self.name);
        }
    }
}

fn annulus_airgap_mesh(
    inner_radius_m: f64,
    outer_radius_m: f64,
    n_radial: usize,
    n_angular: usize,
    pole_count: u32,
    n_pole_pitches: u32,
) -> TriMesh {
    assert!(inner_radius_m > 0.0);
    assert!(outer_radius_m > inner_radius_m);
    assert!(n_radial >= 1);
    assert!(n_angular >= 8);
    assert!(pole_count >= 1);
    assert!(n_pole_pitches >= 1);

    let total_span_rad = 2.0 * PI * n_pole_pitches as f64 / pole_count as f64;
    let full_circle = (total_span_rad - 2.0 * PI).abs() < 1e-12;
    let n_theta = if full_circle {
        n_angular
    } else {
        n_angular + 1
    };

    let mut radii = Vec::with_capacity(n_radial + 1);
    for idx in 0..=n_radial {
        let t = idx as f64 / n_radial as f64;
        radii.push(inner_radius_m + (outer_radius_m - inner_radius_m) * t);
    }

    let mut nodes = Vec::with_capacity((n_radial + 1) * n_theta);
    for radius in &radii {
        for sector in 0..n_theta {
            let theta = sector as f64 / n_angular as f64 * total_span_rad;
            nodes.push([radius * theta.cos(), radius * theta.sin()]);
        }
    }

    let ring_start = |ring_idx: usize| ring_idx * n_theta;
    let mut triangles = Vec::with_capacity(n_radial * n_theta * 2);
    let mut regions = Vec::with_capacity(n_radial * n_theta * 2);
    for ring_idx in 0..n_radial {
        let inner_start = ring_start(ring_idx);
        let outer_start = ring_start(ring_idx + 1);
        for sector in 0..n_angular {
            let next = if full_circle {
                (sector + 1) % n_theta
            } else {
                sector + 1
            };
            triangles.push([
                inner_start + sector,
                outer_start + sector,
                inner_start + next,
            ]);
            regions.push(Region::Airgap);
            triangles.push([inner_start + next, outer_start + sector, outer_start + next]);
            regions.push(Region::Airgap);
        }
    }

    let mut boundary_nodes = Vec::with_capacity(2 * n_theta);
    boundary_nodes.extend(0..n_theta);
    let outer_start = ring_start(n_radial);
    boundary_nodes.extend((0..n_theta).map(|sector| outer_start + sector));

    let sector_edge_pairs = if full_circle {
        vec![]
    } else {
        (0..=n_radial)
            .map(|ring_idx| {
                let start = ring_start(ring_idx);
                (start, start + n_angular)
            })
            .collect()
    };

    let num_triangles = triangles.len();
    TriMesh {
        nodes,
        triangles,
        regions,
        boundary_nodes,
        sector_edge_pairs,
        info: MeshInfo {
            num_nodes: (n_radial + 1) * n_theta,
            num_triangles,
            pole_pitch_deg: 360.0 / pole_count as f64,
            n_pole_pitches,
            total_span_deg: total_span_rad.to_degrees(),
            angular_divisions: n_angular,
            radial_rings: n_radial + 1,
            mesh_density: "synthetic".to_string(),
            radial_layers: vec!["synthetic_airgap".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: inner_radius_m * 1e3,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: outer_radius_m * 1e3,
            stator_slot_outer_radius_mm: outer_radius_m * 1e3,
            stator_outer_radius_mm: outer_radius_m * 1e3,
        },
    }
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

#[test]
fn cartesian_field_projection_matches_expected_polar_components() {
    let field = ElementField {
        bx: 1.2,
        by: -0.4,
        b_mag: (1.2_f64 * 1.2 + 0.4_f64 * 0.4).sqrt(),
    };
    let point = [1.0 / 2.0_f64.sqrt(), 1.0 / 2.0_f64.sqrt()];
    let (b_r, b_t) = project_field_to_polar(&field, point).expect("point is away from origin");

    let expected_br = (field.bx + field.by) / 2.0_f64.sqrt();
    let expected_bt = (-field.bx + field.by) / 2.0_f64.sqrt();
    assert!((b_r - expected_br).abs() < 1e-12);
    assert!((b_t - expected_bt).abs() < 1e-12);
}

#[test]
fn az_contour_radial_step_uses_mesh_info_radii_as_millimeters() {
    let mut mesh = simple_mesh(Region::RotorCore);
    mesh.info.magnet_outer_radius_mm = 64.0;
    mesh.info.stator_inner_radius_mm = 65.0;

    let step_m = choose_az_contour_radial_step(&mesh, 64.5e-3);

    assert!((step_m - (1.0 - 1e-6) * 0.5e-3).abs() < 1e-12);
}

#[test]
fn az_contour_recovers_small_torque_on_staggered_airgap_mesh() {
    // A harmonic potential satisfies Laplace's equation throughout the gap.
    // Unequal growing/decaying modes produce a small known torque amid much
    // larger local stresses. Staggering the interior rings exercises the P1
    // interpolation bias that a short radial stencil can turn into torque.
    let inner = 0.0295;
    let outer = 0.030;
    let mid = 0.5 * (inner + outer);
    let n_angular = 360;
    let n_radial = 2;
    let mut mesh = annulus_airgap_mesh(inner, outer, n_radial, n_angular, 8, 8);
    for (index, node) in mesh.nodes.iter_mut().enumerate() {
        let ring = index / n_angular;
        let theta_shift =
            0.4 * (PI * ring as f64 / n_radial as f64).sin() * 2.0 * PI / n_angular as f64;
        let radius = node[0].hypot(node[1]);
        let theta = node[1].atan2(node[0]) + theta_shift;
        *node = [radius * theta.cos(), radius * theta.sin()];
    }
    let step = choose_az_contour_radial_step(&mesh, mid);
    let inscribed_outer = outer * (PI / n_angular as f64).cos();
    assert!(mid + step < inscribed_outer);
    assert!(mid - step > inner);
    for phase in [0.0_f64, 0.37, 1.1] {
        let az: Vec<f64> = mesh
            .nodes
            .iter()
            .map(|node| {
                let r = node[0].hypot(node[1]);
                let theta = node[1].atan2(node[0]);
                let angle = 4.0 * theta + phase;
                0.005 * (r / mid).powi(4) * angle.cos() + 0.00001 * (mid / r).powi(4) * angle.sin()
            })
            .collect();
        let debug =
            compute_torque_midgap_contour_debug_with_samples_from_az(&mesh, &az, 50.0, 8, 1440);
        let expected = -2.0 * PI * 0.05 * 16.0 * 0.005 * 0.00001 / MU_0;
        assert_eq!(debug.status, "ok", "{:?}", debug.error);
        assert!(
            (debug.scaled_torque_nm / expected - 1.0).abs() < 0.03,
            "phase={phase}: {} versus {expected}",
            debug.scaled_torque_nm
        );
    }
}

#[test]
fn filtered_nodal_b_preserves_material_boundary_discontinuity() {
    let mesh = TriMesh {
        nodes: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
        triangles: vec![[0, 1, 2], [1, 3, 2]],
        regions: vec![Region::Airgap, Region::StatorTooth],
        boundary_nodes: vec![],
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
            radial_layers: vec![],
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
    let fields = vec![
        ElementField {
            bx: 1.0,
            by: 2.0,
            b_mag: 5.0_f64.sqrt(),
        },
        ElementField {
            bx: 101.0,
            by: 202.0,
            b_mag: (101.0_f64 * 101.0 + 202.0 * 202.0).sqrt(),
        },
    ];

    let all_region_b = compute_nodal_b_field(&mesh, &fields);
    let air_only_b =
        compute_filtered_nodal_b_field(&mesh, &fields, |region| region == Region::Airgap);

    assert!((all_region_b[1][0] - 51.0).abs() < 1e-12);
    assert!((all_region_b[1][1] - 102.0).abs() < 1e-12);
    assert!((all_region_b[2][0] - 51.0).abs() < 1e-12);
    assert!((all_region_b[2][1] - 102.0).abs() < 1e-12);
    assert!((air_only_b[1][0] - 1.0).abs() < 1e-12);
    assert!((air_only_b[1][1] - 2.0).abs() < 1e-12);
    assert!((air_only_b[2][0] - 1.0).abs() < 1e-12);
    assert!((air_only_b[2][1] - 2.0).abs() < 1e-12);
}

fn synthetic_airgap_fields(
    centroids: &[[f64; 2]],
    b1_t: f64,
    harmonic_order: u32,
    alpha_rad: f64,
) -> Vec<ElementField> {
    centroids
        .iter()
        .map(|centroid| {
            let theta = centroid[1].atan2(centroid[0]);
            let br = b1_t * (harmonic_order as f64 * theta).cos();
            let bt = b1_t * (harmonic_order as f64 * theta + alpha_rad).sin();
            let cos_theta = theta.cos();
            let sin_theta = theta.sin();
            let bx = br * cos_theta - bt * sin_theta;
            let by = br * sin_theta + bt * cos_theta;
            ElementField {
                bx,
                by,
                b_mag: (bx * bx + by * by).sqrt(),
            }
        })
        .collect()
}

fn synthetic_airgap_az(mesh: &TriMesh, a_t: f64, b_t_per_m: f64, harmonic_order: u32) -> Vec<f64> {
    mesh.nodes
        .iter()
        .map(|node| {
            let r = (node[0] * node[0] + node[1] * node[1]).sqrt();
            let theta = node[1].atan2(node[0]);
            a_t * r * (harmonic_order as f64 * theta).sin()
                + b_t_per_m * r * r * (harmonic_order as f64 * theta).cos()
        })
        .collect()
}

fn synthetic_area_mst_torque_theory_nm(
    inner_radius_m: f64,
    outer_radius_m: f64,
    stack_length_m: f64,
    b1_t: f64,
    alpha_rad: f64,
) -> f64 {
    PI * stack_length_m
        * (outer_radius_m * outer_radius_m - inner_radius_m * inner_radius_m)
        * b1_t
        * b1_t
        * alpha_rad.sin()
        / (2.0 * MU_0)
}

fn synthetic_contour_mst_torque_theory_nm(
    radius_m: f64,
    stack_length_m: f64,
    b1_t: f64,
    alpha_rad: f64,
) -> f64 {
    PI * stack_length_m * radius_m * radius_m * b1_t * b1_t * alpha_rad.sin() / MU_0
}

fn synthetic_weighted_stress_torque_theory_nm(
    inner_radius_m: f64,
    outer_radius_m: f64,
    stack_length_m: f64,
    b1_t: f64,
    alpha_rad: f64,
) -> f64 {
    PI * stack_length_m
        * b1_t
        * b1_t
        * alpha_rad.sin()
        * (outer_radius_m * outer_radius_m - inner_radius_m * inner_radius_m)
        / (2.0 * (outer_radius_m / inner_radius_m).ln() * MU_0)
}

#[test]
fn waveform_based_core_loss_matches_hand_computed_single_harmonic() {
    let mesh = simple_mesh(Region::StatorTooth);
    let field_history = vec![
        vec![ElementField {
            bx: 0.0,
            by: 0.0,
            b_mag: 0.0,
        }],
        vec![ElementField {
            bx: 1.0,
            by: 0.0,
            b_mag: 1.0,
        }],
        vec![ElementField {
            bx: 0.0,
            by: 0.0,
            b_mag: 0.0,
        }],
        vec![ElementField {
            bx: -1.0,
            by: 0.0,
            b_mag: 1.0,
        }],
    ];

    let coeffs = SteinmetzCoefficients {
        kh: 0.1,
        ke: 0.01,
        alpha: 2.0,
        density_kg_m3: 4.0,
    };

    let loss = compute_stator_core_loss(&mesh, &field_history, 1000.0, 1, coeffs, 50.0);

    assert!((loss.stator_core_mass_kg - 2.0).abs() < 1e-9);
    assert!((loss.hysteresis_loss_w - 10.0).abs() < 1e-9);
    assert!((loss.eddy_current_loss_w - 50.0).abs() < 1e-9);
    assert!((loss.core_loss_w - 60.0).abs() < 1e-9);
    let density = loss.core_loss_density_w_per_m3.expect("density map");
    assert_eq!(density.len(), 1);
    // q * A * L = sector loss; scale=1 so totals == sector watts.
    // simple_mesh is the unit right triangle with area 0.5; stack_length_mm=1000 → L=1.
    let area = 0.5;
    let stack = 1.0;
    assert!((density[0] * area * stack - 60.0).abs() < 1e-6);
}

#[test]
fn rotor_elements_are_excluded_from_stator_core_loss() {
    let mesh = simple_mesh(Region::RotorCore);
    let field_history = vec![
        vec![ElementField {
            bx: 1.0,
            by: 0.0,
            b_mag: 1.0
        }];
        4
    ];
    let coeffs = SteinmetzCoefficients {
        kh: 0.1,
        ke: 0.01,
        alpha: 2.0,
        density_kg_m3: 4.0,
    };

    let loss = compute_stator_core_loss(&mesh, &field_history, 1000.0, 1, coeffs, 50.0);
    assert_eq!(loss.core_loss_w, 0.0);
    assert_eq!(loss.hysteresis_loss_w, 0.0);
    assert_eq!(loss.eddy_current_loss_w, 0.0);
    assert_eq!(loss.stator_core_mass_kg, 0.0);
    let density = loss.core_loss_density_w_per_m3.expect("density map");
    assert!(density.iter().all(|q| *q == 0.0));
}

#[test]
fn flux_barrier_semantics_are_air_and_excluded_from_wst_and_core_loss() {
    let materials = assign_materials(
        &[Region::FluxBarrier, Region::MagnetPocketAir],
        &[[1.0, 0.0], [0.0, 1.0]],
        "M19",
        "M19",
        "N42",
        4,
        0.0,
    );
    for material in materials {
        assert!((material.mu_rel - 1.0).abs() < 1e-12);
        assert_eq!(material.br, 0.0);
        assert_eq!(material.mag_angle_rad, 0.0);
    }

    let mut mesh = annulus_airgap_mesh(10.0e-3, 12.0e-3, 4, 96, 4, 1);
    let base_mesh = mesh.clone();
    let base_centroids = triangle_centroids(&base_mesh);
    let base_fields = synthetic_airgap_fields(&base_centroids, 0.8, 2, PI / 6.0);
    let base_debug = compute_torque_weighted_stress_debug(&base_mesh, &base_fields, 50.0, 4);
    assert_eq!(base_debug.status, "ok");

    let flux_node_start = mesh.nodes.len();
    mesh.nodes
        .extend([[2.0e-3, 0.0], [3.0e-3, 0.0], [2.0e-3, 1.0e-3]]);
    mesh.triangles
        .push([flux_node_start, flux_node_start + 1, flux_node_start + 2]);
    mesh.regions.push(Region::FluxBarrier);
    mesh.info.num_nodes = mesh.nodes.len();
    mesh.info.num_triangles = mesh.triangles.len();

    let mut fields = base_fields.clone();
    fields.push(ElementField {
        bx: 100.0,
        by: -80.0,
        b_mag: (100.0_f64 * 100.0 + 80.0 * 80.0).sqrt(),
    });
    let debug = compute_torque_weighted_stress_debug(&mesh, &fields, 50.0, 4);

    assert_eq!(debug.status, "ok");
    assert_eq!(debug.airgap_element_count, base_debug.airgap_element_count);
    assert_eq!(debug.airgap_node_count, base_debug.airgap_node_count);
    assert!(!debug
        .domain_regions
        .iter()
        .any(|region| { region == "FluxBarrier" || region == "MagnetPocketAir" }));
    assert!(
        (debug.scaled_torque_nm - base_debug.scaled_torque_nm).abs() < 1e-9,
        "buried flux-barrier field must not enter WST torque"
    );

    let flux_mesh = simple_mesh(Region::FluxBarrier);
    let high_field = ElementField {
        bx: 9.0,
        by: -7.0,
        b_mag: (9.0_f64 * 9.0 + 7.0 * 7.0).sqrt(),
    };
    let field_history = vec![vec![high_field.clone()]; 4];
    let coeffs = SteinmetzCoefficients {
        kh: 0.1,
        ke: 0.01,
        alpha: 2.0,
        density_kg_m3: 4.0,
    };
    let loss = compute_stator_core_loss(&flux_mesh, &field_history, 1000.0, 1, coeffs, 50.0);
    assert_eq!(loss.core_loss_w, 0.0);
    assert_eq!(loss.hysteresis_loss_w, 0.0);
    assert_eq!(loss.eddy_current_loss_w, 0.0);
    assert_eq!(loss.stator_core_mass_kg, 0.0);
    let density = loss.core_loss_density_w_per_m3.expect("density map");
    assert!(density.iter().all(|q| *q == 0.0));
}

#[test]
fn core_loss_defaults_when_field_history_is_not_mesh_aligned() {
    let mut mesh = simple_mesh(Region::StatorTooth);
    mesh.nodes.push([1.0, 1.0]);
    mesh.triangles.push([1, 3, 2]);
    mesh.regions.push(Region::StatorTooth);
    mesh.info.num_nodes = mesh.nodes.len();
    mesh.info.num_triangles = mesh.triangles.len();

    let field = ElementField {
        bx: 1.0,
        by: 0.0,
        b_mag: 1.0,
    };
    let field_history = vec![vec![field.clone()], vec![field.clone(), field]];
    let coeffs = SteinmetzCoefficients {
        kh: 1.0,
        ke: 1.0,
        alpha: 2.0,
        density_kg_m3: 1.0,
    };

    let loss = compute_stator_core_loss(&mesh, &field_history, 1000.0, 1, coeffs, 50.0);
    assert_eq!(loss, CoreLossSummary::default());
}

#[test]
fn synthetic_airgap_fields_validate_area_mst_torque_and_sign() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 12.0e-3;
    let stack_length_mm = 50.0;
    let stack_length_m = stack_length_mm * 1e-3;
    let b1_t = 0.8;
    let harmonic_order = 3;
    let alpha_pos = PI / 6.0;
    let alpha_zero = 0.0;
    let alpha_neg = -PI / 6.0;

    let mesh = annulus_airgap_mesh(inner_radius_m, outer_radius_m, 12, 720, 1, 1);
    let centroids = triangle_centroids(&mesh);

    let fields_zero = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_zero);
    let torque_zero = compute_torque(&mesh, &fields_zero, &centroids, stack_length_mm, 1);
    eprintln!("synthetic MST torque: alpha=0 torque={torque_zero:.6e}Nm");
    assert!(
        torque_zero.abs() < 1e-6,
        "in-phase Br/Bt should produce zero net torque"
    );

    let fields_pos = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_pos);
    let torque_pos = compute_torque(&mesh, &fields_pos, &centroids, stack_length_mm, 1);
    let expected_pos = synthetic_area_mst_torque_theory_nm(
        inner_radius_m,
        outer_radius_m,
        stack_length_m,
        b1_t,
        alpha_pos,
    );
    let rel_err_pos = ((torque_pos - expected_pos) / expected_pos).abs();
    eprintln!(
            "synthetic MST torque: alpha=+30deg modeled={torque_pos:.6e}Nm theory={expected_pos:.6e}Nm rel_err={:.3}%",
            rel_err_pos * 100.0
        );
    assert!(torque_pos > 0.0);
    assert!(
        rel_err_pos < 0.01,
        "positive synthetic MST torque drifted from exact area integral"
    );

    let fields_neg = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_neg);
    let torque_neg = compute_torque(&mesh, &fields_neg, &centroids, stack_length_mm, 1);
    let expected_neg = synthetic_area_mst_torque_theory_nm(
        inner_radius_m,
        outer_radius_m,
        stack_length_m,
        b1_t,
        alpha_neg,
    );
    let rel_err_neg = ((torque_neg - expected_neg) / expected_neg).abs();
    eprintln!(
            "synthetic MST torque: alpha=-30deg modeled={torque_neg:.6e}Nm theory={expected_neg:.6e}Nm rel_err={:.3}%",
            rel_err_neg * 100.0
        );
    assert!(torque_neg < 0.0);
    assert!(
        rel_err_neg < 0.01,
        "negative synthetic MST torque drifted from exact area integral"
    );
    assert!((torque_neg + torque_pos).abs() < expected_pos.abs() * 0.01);
}

#[test]
fn synthetic_airgap_fields_validate_midgap_contour_torque_and_sign() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 12.0e-3;
    let mid_radius_m = 0.5 * (inner_radius_m + outer_radius_m);
    let stack_length_mm = 50.0;
    let stack_length_m = stack_length_mm * 1e-3;
    let b1_t = 0.8;
    let harmonic_order = 3;
    let alpha_pos = PI / 6.0;
    let alpha_zero = 0.0;
    let alpha_neg = -PI / 6.0;

    let mesh = annulus_airgap_mesh(inner_radius_m, outer_radius_m, 12, 720, 1, 1);
    let centroids = triangle_centroids(&mesh);

    let fields_zero = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_zero);
    let torque_zero_debug = compute_torque_midgap_contour_debug_with_samples(
        &mesh,
        &fields_zero,
        stack_length_mm,
        1,
        1440,
    );
    let torque_zero = torque_zero_debug.scaled_torque_nm;
    eprintln!("synthetic contour torque: alpha=0 modeled={torque_zero:.6e}Nm");
    assert!(
        torque_zero.abs() < 5e-4,
        "in-phase Br/Bt should produce near-zero contour torque"
    );

    let fields_pos = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_pos);
    let torque_pos = compute_torque_midgap_contour_debug_with_samples(
        &mesh,
        &fields_pos,
        stack_length_mm,
        1,
        1440,
    )
    .scaled_torque_nm;
    let expected_pos =
        synthetic_contour_mst_torque_theory_nm(mid_radius_m, stack_length_m, b1_t, alpha_pos);
    let rel_err_pos = ((torque_pos - expected_pos) / expected_pos).abs();
    eprintln!(
            "synthetic contour torque: alpha=+30deg modeled={torque_pos:.6e}Nm theory={expected_pos:.6e}Nm rel_err={:.3}%",
            rel_err_pos * 100.0
        );
    assert!(torque_pos > 0.0);
    assert!(
        rel_err_pos < 0.02,
        "positive synthetic contour torque drifted from theory"
    );

    let fields_neg = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_neg);
    let torque_neg = compute_torque_midgap_contour_debug_with_samples(
        &mesh,
        &fields_neg,
        stack_length_mm,
        1,
        1440,
    )
    .scaled_torque_nm;
    let expected_neg =
        synthetic_contour_mst_torque_theory_nm(mid_radius_m, stack_length_m, b1_t, alpha_neg);
    let rel_err_neg = ((torque_neg - expected_neg) / expected_neg).abs();
    eprintln!(
            "synthetic contour torque: alpha=-30deg modeled={torque_neg:.6e}Nm theory={expected_neg:.6e}Nm rel_err={:.3}%",
            rel_err_neg * 100.0
        );
    assert!(torque_neg < 0.0);
    assert!(
        rel_err_neg < 0.02,
        "negative synthetic contour torque drifted from theory"
    );
    assert!((torque_neg + torque_pos).abs() < expected_pos.abs() * 0.02);
}

#[test]
fn az_derived_midgap_contour_matches_theory_for_mixed_radial_potential() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 12.0e-3;
    let mid_radius_m = 0.5 * (inner_radius_m + outer_radius_m);
    let stack_length_mm = 50.0;
    let stack_length_m = stack_length_mm * 1e-3;
    let pole_count = 4;
    let harmonic_order = 2;
    let a_t = 0.35;
    let b_t_per_m = -12.0;

    let mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        12,
        720,
        pole_count,
        pole_count,
    );
    let az = synthetic_airgap_az(&mesh, a_t, b_t_per_m, harmonic_order);

    let contour_debug = compute_torque_midgap_contour_debug_with_samples_from_az(
        &mesh,
        &az,
        stack_length_mm,
        pole_count,
        1440,
    );
    assert_eq!(contour_debug.status, "ok");

    let modeled_torque = contour_debug.scaled_torque_nm;
    let expected_torque =
        -PI * stack_length_m * harmonic_order as f64 * a_t * b_t_per_m * mid_radius_m.powi(3)
            / MU_0;
    let rel_err = ((modeled_torque - expected_torque) / expected_torque).abs();
    eprintln!(
            "synthetic A_z-derived contour torque: modeled={modeled_torque:.6e}Nm theory={expected_torque:.6e}Nm rel_err={:.3}%",
            rel_err * 100.0
        );
    assert!(
        rel_err < 0.03,
        "A_z-derived contour torque drifted from mixed-radial-potential theory"
    );
}

#[test]
fn multi_radius_contour_diagnostics_are_not_zero_placeholders() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 12.0e-3;
    let stack_length_mm = 50.0;
    let pole_count = 4;
    let harmonic_order = 2;

    let mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        12,
        720,
        pole_count,
        pole_count,
    );
    let centroids = triangle_centroids(&mesh);
    let fields = synthetic_airgap_fields(&centroids, 0.8, harmonic_order, PI / 6.0);
    let (_mid, inner, outer, diagnostics) =
        compute_torque_at_multiple_radii(&mesh, &fields, stack_length_mm, pole_count);
    assert!(diagnostics.contains("ok_radii="), "{diagnostics}");
    assert!(
        inner.abs() > 1e-9 && outer.abs() > 1e-9,
        "B-field multi-radius diagnostics should not export zero placeholders: {diagnostics}"
    );

    let az = synthetic_airgap_az(&mesh, 0.35, -12.0, harmonic_order);
    let (_az_mid, az_inner, az_outer, az_diagnostics) =
        compute_torque_at_multiple_radii_from_az(&mesh, &az, stack_length_mm, pole_count);
    assert!(az_diagnostics.contains("ok_radii="), "{az_diagnostics}");
    assert!(
        az_inner.abs() > 1e-9 && az_outer.abs() > 1e-9,
        "A_z multi-radius diagnostics should not export zero placeholders: {az_diagnostics}"
    );
}

#[test]
fn robust_contour_reports_stable_on_smooth_thin_airgap() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 10.2e-3;
    let stack_length_mm = 50.0;
    let pole_count = 4;
    let harmonic_order = 2;

    let mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        6,
        720,
        pole_count,
        pole_count,
    );
    let centroids = triangle_centroids(&mesh);
    let fields = synthetic_airgap_fields(&centroids, 0.8, harmonic_order, PI / 6.0);
    let az = synthetic_airgap_az(&mesh, 0.35, -12.0, harmonic_order);

    let debug =
        compute_torque_robust_contour_debug(&mesh, &fields, &az, stack_length_mm, pole_count);

    assert_eq!(debug.status, "ok");
    assert_eq!(debug.radius_count, 3);
    assert_eq!(debug.offset_count, 4);
    assert_eq!(debug.source_stats.len(), 2);
    assert!(debug.source_stats.iter().all(|stats| stats.status == "ok"));
    assert!(debug.selected_torque_nm.is_finite());
}

#[test]
fn weighted_stress_matches_log_weighted_annulus_theory() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 10.2e-3;
    let stack_length_mm = 50.0;
    let stack_length_m = stack_length_mm * 1e-3;
    let b1_t = 0.8;
    let pole_count = 4;
    let harmonic_order = 2;
    let alpha_rad = PI / 6.0;

    let mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        8,
        720,
        pole_count,
        pole_count,
    );
    let centroids = triangle_centroids(&mesh);
    let fields = synthetic_airgap_fields(&centroids, b1_t, harmonic_order, alpha_rad);

    let debug = compute_torque_weighted_stress_debug(&mesh, &fields, stack_length_mm, pole_count);

    assert_eq!(debug.status, "ok");
    assert!(debug.scaled_torque_nm > 0.0);
    assert!((debug.weight_min - 0.0).abs() < 1.0e-8);
    assert!((debug.weight_max - 1.0).abs() < 1.0e-8);

    let expected = synthetic_weighted_stress_torque_theory_nm(
        inner_radius_m,
        outer_radius_m,
        stack_length_m,
        b1_t,
        alpha_rad,
    );
    let rel_err = ((debug.scaled_torque_nm - expected) / expected).abs();
    eprintln!(
        "synthetic weighted-stress torque: modeled={:.6e}Nm theory={:.6e}Nm rel_err={:.3}%",
        debug.scaled_torque_nm,
        expected,
        rel_err * 100.0
    );
    assert!(
        rel_err < 0.03,
        "weighted-stress torque drifted from log-weighted annulus theory"
    );
}

#[test]
fn weighted_stress_can_recover_b_from_az_without_element_fallback() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 10.2e-3;
    let stack_length_mm = 50.0;
    let pole_count = 4;
    let harmonic_order = 2;

    let _az_guard = EnvVarGuard::set("COILEM_MAGNETO2D_WEIGHTED_STRESS_AZ_FIELD", "1");
    let _airgap_guard = EnvVarGuard::set("COILEM_MAGNETO2D_WEIGHTED_STRESS_AIRGAP_ONLY", "1");
    let _localization_guard =
        EnvVarGuard::set("COILEM_MAGNETO2D_WEIGHTED_STRESS_LOCALIZATION", "1");

    let mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        8,
        720,
        pole_count,
        pole_count,
    );
    let fields = vec![
        ElementField {
            bx: 0.0,
            by: 0.0,
            b_mag: 0.0,
        };
        mesh.triangles.len()
    ];
    let az = synthetic_airgap_az(&mesh, 0.35, -12.0, harmonic_order);

    let debug = compute_torque_weighted_stress_debug_with_az(
        &mesh,
        &fields,
        Some(&az),
        stack_length_mm,
        pole_count,
    );

    assert_eq!(debug.status, "ok");
    assert_eq!(debug.field_source, "az_airgap_central_difference");
    assert_eq!(debug.field_fallback_count, 0);
    assert_eq!(debug.boundary_wedge_sample_count, 0);
    assert_eq!(debug.boundary_wedge_sample_fallback_count, 0);
    assert_eq!(debug.boundary_wedge_taper_count, 0);
    assert_eq!(debug.boundary_wedge_taper_factor, 1.0);
    assert_eq!(debug.boundary_wedge_taper_removed_nm, 0.0);
    assert!(!debug.boundary_wedge_taper_applied);
    assert!(debug.boundary_wedge_taper_gate_reason.is_none());
    assert_eq!(debug.domain_regions, vec!["Airgap".to_string()]);
    assert!(
        debug.scaled_torque_nm.abs() > 1.0e-9,
        "A_z-derived WST should not silently use zero element fields"
    );
    let localization = debug
        .contribution_localization
        .expect("localization env should export WST contribution bins");
    assert_eq!(localization.field_source, "az_airgap_central_difference");
    assert_eq!(localization.radial_bins.len(), 5);
    assert_eq!(localization.angular_bins.len(), 24);
    assert!(!localization.top_abs_contributors.is_empty());
    assert!(localization.total_abs_torque_nm >= debug.scaled_torque_nm.abs());
    assert_eq!(
        localization
            .interface_bins
            .iter()
            .map(|bin| bin.element_count)
            .sum::<usize>(),
        debug.airgap_element_count
    );

    let _taper_guard =
        EnvVarGuard::set("COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER", "1");
    let tapered = compute_torque_weighted_stress_debug_with_az(
        &mesh,
        &fields,
        Some(&az),
        stack_length_mm,
        pole_count,
    );
    assert_eq!(tapered.status, "ok");
    assert_eq!(tapered.boundary_wedge_taper_count, 0);
    assert_eq!(tapered.boundary_wedge_taper_factor, 0.0);
    assert_eq!(tapered.boundary_wedge_taper_removed_nm, 0.0);
    assert!(!tapered.boundary_wedge_taper_applied);

    let _outer_bulk_guard = EnvVarGuard::set(
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_OUTER_BULK",
        "1",
    );
    let outer_bulk_tapered = compute_torque_weighted_stress_debug_with_az(
        &mesh,
        &fields,
        Some(&az),
        stack_length_mm,
        pole_count,
    );
    assert_eq!(outer_bulk_tapered.status, "ok");
    assert!(outer_bulk_tapered.boundary_wedge_taper_count > 0);
    assert_eq!(outer_bulk_tapered.boundary_wedge_taper_factor, 0.0);
    assert!(outer_bulk_tapered.boundary_wedge_taper_applied);
    assert!(
        outer_bulk_tapered.boundary_wedge_taper_removed_nm.abs() > 1.0e-12,
        "outer-bulk taper diagnostic should report the removed WST contribution"
    );
}

#[test]
fn synthetic_airgap_fields_preserve_torque_under_sector_scaling() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 12.0e-3;
    let stack_length_mm = 50.0;
    let stack_length_m = stack_length_mm * 1e-3;
    let b1_t = 0.8;
    let pole_count = 8;
    let harmonic_order = pole_count / 2;
    let alpha_rad = PI / 6.0;

    let full_mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        12,
        720,
        pole_count,
        pole_count,
    );
    let full_centroids = triangle_centroids(&full_mesh);
    let full_fields = synthetic_airgap_fields(&full_centroids, b1_t, harmonic_order, alpha_rad);
    let full_torque = compute_torque(
        &full_mesh,
        &full_fields,
        &full_centroids,
        stack_length_mm,
        pole_count,
    );

    let expected_torque = synthetic_area_mst_torque_theory_nm(
        inner_radius_m,
        outer_radius_m,
        stack_length_m,
        b1_t,
        alpha_rad,
    );
    let rel_err_full = ((full_torque - expected_torque) / expected_torque).abs();
    eprintln!(
            "synthetic sector scaling: full annulus modeled={full_torque:.6e}Nm theory={expected_torque:.6e}Nm rel_err={:.3}%",
            rel_err_full * 100.0
        );
    assert!(rel_err_full < 0.01);

    for &n_pole_pitches in &[1_u32, 3_u32] {
        let sector_mesh = annulus_airgap_mesh(
            inner_radius_m,
            outer_radius_m,
            12,
            720 / pole_count as usize * n_pole_pitches as usize,
            pole_count,
            n_pole_pitches,
        );
        let sector_centroids = triangle_centroids(&sector_mesh);
        let sector_fields =
            synthetic_airgap_fields(&sector_centroids, b1_t, harmonic_order, alpha_rad);
        let sector_torque = compute_torque(
            &sector_mesh,
            &sector_fields,
            &sector_centroids,
            stack_length_mm,
            pole_count,
        );
        let rel_vs_full = ((sector_torque - full_torque) / full_torque).abs();
        let rel_vs_theory = ((sector_torque - expected_torque) / expected_torque).abs();
        eprintln!(
                "synthetic sector scaling: npp={n_pole_pitches} modeled={sector_torque:.6e}Nm rel_vs_full={:.3}% rel_vs_theory={:.3}%",
                rel_vs_full * 100.0,
                rel_vs_theory * 100.0
            );
        assert!(
            rel_vs_full < 0.01,
            "sector-scaled MST torque for npp={n_pole_pitches} drifted from full-annulus result"
        );
        assert!(
            rel_vs_theory < 0.01,
            "sector-scaled MST torque for npp={n_pole_pitches} drifted from theory"
        );
    }
}

#[test]
fn synthetic_midgap_contour_preserves_torque_under_sector_scaling() {
    let inner_radius_m = 10.0e-3;
    let outer_radius_m = 12.0e-3;
    let mid_radius_m = 0.5 * (inner_radius_m + outer_radius_m);
    let stack_length_mm = 50.0;
    let stack_length_m = stack_length_mm * 1e-3;
    let b1_t = 0.8;
    let pole_count = 8;
    let harmonic_order = pole_count / 2;
    let alpha_rad = PI / 6.0;

    let full_mesh = annulus_airgap_mesh(
        inner_radius_m,
        outer_radius_m,
        12,
        720,
        pole_count,
        pole_count,
    );
    let full_centroids = triangle_centroids(&full_mesh);
    let full_fields = synthetic_airgap_fields(&full_centroids, b1_t, harmonic_order, alpha_rad);
    let full_debug = compute_torque_midgap_contour_debug_with_samples(
        &full_mesh,
        &full_fields,
        stack_length_mm,
        pole_count,
        1440,
    );
    assert_eq!(full_debug.status, "ok");
    let full_torque = full_debug.scaled_torque_nm;

    let expected_torque =
        synthetic_contour_mst_torque_theory_nm(mid_radius_m, stack_length_m, b1_t, alpha_rad);
    let rel_err_full = ((full_torque - expected_torque) / expected_torque).abs();
    eprintln!(
            "synthetic contour scaling: full annulus modeled={full_torque:.6e}Nm theory={expected_torque:.6e}Nm rel_err={:.3}%",
            rel_err_full * 100.0
        );
    assert!(rel_err_full < 0.02);

    for &n_pole_pitches in &[1_u32, 3_u32] {
        let sector_mesh = annulus_airgap_mesh(
            inner_radius_m,
            outer_radius_m,
            12,
            720 / pole_count as usize * n_pole_pitches as usize,
            pole_count,
            n_pole_pitches,
        );
        let sector_centroids = triangle_centroids(&sector_mesh);
        let sector_fields =
            synthetic_airgap_fields(&sector_centroids, b1_t, harmonic_order, alpha_rad);
        let sector_debug = compute_torque_midgap_contour_debug_with_samples(
            &sector_mesh,
            &sector_fields,
            stack_length_mm,
            pole_count,
            1440 / pole_count as usize * n_pole_pitches as usize,
        );
        assert_eq!(sector_debug.status, "ok");
        let sector_torque = sector_debug.scaled_torque_nm;
        let rel_vs_full = ((sector_torque - full_torque) / full_torque).abs();
        let rel_vs_theory = ((sector_torque - expected_torque) / expected_torque).abs();
        eprintln!(
                "synthetic contour scaling: npp={n_pole_pitches} modeled={sector_torque:.6e}Nm rel_vs_full={:.3}% rel_vs_theory={:.3}%",
                rel_vs_full * 100.0,
                rel_vs_theory * 100.0
            );
        assert!(
                rel_vs_full < 0.02,
                "sector-scaled contour torque for npp={n_pole_pitches} drifted from full-annulus result"
            );
        assert!(
            rel_vs_theory < 0.02,
            "sector-scaled contour torque for npp={n_pole_pitches} drifted from theory"
        );
    }
}

/// Regression property: the Arkkio band integrand must be built
/// from AIRGAP-element fields only. Nodes on the airgap/iron interface are
/// shared with stator-tooth elements; an unfiltered nodal-B average smears
/// the iron field into the band and inflated Arkkio 1.5-3.2x vs contour/WST
/// on the Phase C distributed fixtures (thin, few-layer gmsh airgaps). The
/// property: Arkkio torque is IDENTICAL whether the adjacent iron elements
/// carry zero field or a saturated one, because neither may enter the
/// integrand.
#[test]
fn arkkio_torque_is_insensitive_to_adjacent_iron_field() {
    let inner_radius_m = 10.0e-3;
    let iron_outer_radius_m = 12.0e-3;
    let stack_length_mm = 50.0;
    let pole_count = 4;
    let harmonic_order = 2;
    let alpha_rad = PI / 6.0;

    // Three structured rings; the outermost is re-tagged as stator iron so
    // it shares interface nodes with the airgap band below it.
    let mut mesh = annulus_airgap_mesh(
        inner_radius_m,
        iron_outer_radius_m,
        3,
        720,
        pole_count,
        pole_count,
    );
    let airgap_outer_radius_m = inner_radius_m + (iron_outer_radius_m - inner_radius_m) * 2.0 / 3.0;
    for idx in 0..mesh.triangles.len() {
        let max_node_radius = mesh.triangles[idx]
            .iter()
            .map(|&node| {
                let [x, y] = mesh.nodes[node];
                (x * x + y * y).sqrt()
            })
            .fold(0.0_f64, f64::max);
        if max_node_radius > airgap_outer_radius_m + 1.0e-9 {
            mesh.regions[idx] = Region::StatorTooth;
        }
    }
    mesh.info.airgap_inner_radius_mm = Some(inner_radius_m * 1e3);
    mesh.info.airgap_outer_radius_mm = Some(airgap_outer_radius_m * 1e3);
    mesh.info.stator_inner_radius_mm = airgap_outer_radius_m * 1e3;

    let centroids = triangle_centroids(&mesh);
    let base_fields = synthetic_airgap_fields(&centroids, 0.8, harmonic_order, alpha_rad);

    let mut fields_iron_quiet = base_fields.clone();
    let mut fields_iron_saturated = base_fields;
    for (idx, region) in mesh.regions.iter().enumerate() {
        if *region == Region::StatorTooth {
            fields_iron_quiet[idx] = ElementField {
                bx: 0.0,
                by: 0.0,
                b_mag: 0.0,
            };
            fields_iron_saturated[idx] = ElementField {
                bx: 5.0,
                by: -3.0,
                b_mag: (34.0_f64).sqrt(),
            };
        }
    }

    let quiet = compute_torque_arkkio_debug(
        &mesh,
        &fields_iron_quiet,
        &centroids,
        stack_length_mm,
        pole_count,
    );
    let saturated = compute_torque_arkkio_debug(
        &mesh,
        &fields_iron_saturated,
        &centroids,
        stack_length_mm,
        pole_count,
    );

    assert_eq!(quiet.status, "ok");
    assert_eq!(saturated.status, "ok");
    assert!(
        quiet.airgap_element_count > 0,
        "band selection must keep interior airgap elements"
    );
    assert!(
        quiet.scaled_torque_nm.abs() > 1.0e-6,
        "synthetic airgap field must produce non-zero Arkkio torque, got {:.3e}Nm",
        quiet.scaled_torque_nm
    );
    let abs_diff = (quiet.scaled_torque_nm - saturated.scaled_torque_nm).abs();
    let tolerance = 1.0e-9 * quiet.scaled_torque_nm.abs().max(1.0);
    assert!(
        abs_diff <= tolerance,
        "Arkkio torque leaked adjacent iron field into the band integrand: \
         quiet={:.9e}Nm saturated={:.9e}Nm diff={:.3e}Nm",
        quiet.scaled_torque_nm,
        saturated.scaled_torque_nm,
        abs_diff
    );
}
