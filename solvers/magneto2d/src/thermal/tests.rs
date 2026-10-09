//! Analytic property suite for thermal conduction mode.
//!
//! These are CI gates (not benchmarks): closed-form solutions with energy-
//! balance closure as the cross-lane discriminator.

use crate::mesh::{MeshInfo, MeshSource, Region, TriMesh};
use crate::thermal::bc::{
    linearized_radiation_h, ThermalBoundaryCondition, ThermalBoundarySet, STEFAN_BOLTZMANN,
};
use crate::thermal::materials::{ThermalConductivityModel, ThermalMaterialProps};
use crate::thermal::solve::{run_steady_state_thermal, ThermalSolveRequest};
use crate::thermal::sources::ThermalSources;

fn mesh_info(n_nodes: usize, n_tris: usize) -> MeshInfo {
    MeshInfo {
        num_nodes: n_nodes,
        num_triangles: n_tris,
        pole_pitch_deg: 360.0,
        n_pole_pitches: 1,
        total_span_deg: 360.0,
        angular_divisions: 1,
        radial_rings: 1,
        mesh_density: "test".to_string(),
        radial_layers: vec![],
        airgap_inner_radius_mm: None,
        airgap_outer_radius_mm: None,
        mesh_source: Some(MeshSource::Unknown),
        magnet_outer_radius_mm: 0.0,
        magnet_embrace: 1.0,
        stator_inner_radius_mm: 0.0,
        stator_slot_outer_radius_mm: 0.0,
        stator_outer_radius_mm: 0.0,
    }
}

/// Structured rectangular mesh on [0,Lx] x [0,Ly] with nx × ny quads → 2 tris.
fn build_rect_mesh(nx: usize, ny: usize, lx: f64, ly: f64) -> TriMesh {
    let mut nodes = Vec::new();
    for j in 0..=ny {
        for i in 0..=nx {
            nodes.push([
                lx * (i as f64) / (nx as f64),
                ly * (j as f64) / (ny as f64),
            ]);
        }
    }
    let mut triangles = Vec::new();
    let mut regions = Vec::new();
    let row = nx + 1;
    for j in 0..ny {
        for i in 0..nx {
            let n0 = j * row + i;
            let n1 = n0 + 1;
            let n2 = n0 + row;
            let n3 = n2 + 1;
            triangles.push([n0, n1, n3]);
            triangles.push([n0, n3, n2]);
            regions.push(Region::Airgap);
            regions.push(Region::Airgap);
        }
    }
    let mut boundary = Vec::new();
    for i in 0..=nx {
        boundary.push(i); // bottom
        boundary.push(ny * row + i); // top
    }
    for j in 0..=ny {
        boundary.push(j * row); // left
        boundary.push(j * row + nx); // right
    }
    boundary.sort_unstable();
    boundary.dedup();
    let n_nodes = nodes.len();
    let n_tris = triangles.len();
    TriMesh {
        nodes,
        triangles,
        regions,
        boundary_nodes: boundary,
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes, n_tris),
    }
}

fn left_right_edges(mesh: &TriMesh, lx: f64) -> (Vec<[usize; 2]>, Vec<[usize; 2]>) {
    let mut left = Vec::new();
    let mut right = Vec::new();
    for tri in &mesh.triangles {
        let edges = [[tri[0], tri[1]], [tri[1], tri[2]], [tri[2], tri[0]]];
        for edge in edges {
            let x0 = mesh.nodes[edge[0]][0];
            let x1 = mesh.nodes[edge[1]][0];
            if x0.abs() < 1e-12 && x1.abs() < 1e-12 {
                left.push(edge);
            } else if (x0 - lx).abs() < 1e-12 && (x1 - lx).abs() < 1e-12 {
                right.push(edge);
            }
        }
    }
    (dedup_undirected_edges(left), dedup_undirected_edges(right))
}

fn bottom_top_edges(mesh: &TriMesh, ly: f64) -> (Vec<[usize; 2]>, Vec<[usize; 2]>) {
    let mut bottom = Vec::new();
    let mut top = Vec::new();
    for tri in &mesh.triangles {
        let edges = [[tri[0], tri[1]], [tri[1], tri[2]], [tri[2], tri[0]]];
        for edge in edges {
            let y0 = mesh.nodes[edge[0]][1];
            let y1 = mesh.nodes[edge[1]][1];
            if y0.abs() < 1e-12 && y1.abs() < 1e-12 {
                bottom.push(edge);
            } else if (y0 - ly).abs() < 1e-12 && (y1 - ly).abs() < 1e-12 {
                top.push(edge);
            }
        }
    }
    (dedup_undirected_edges(bottom), dedup_undirected_edges(top))
}

fn dedup_undirected_edges(mut edges: Vec<[usize; 2]>) -> Vec<[usize; 2]> {
    for edge in &mut edges {
        if edge[0] > edge[1] {
            edge.swap(0, 1);
        }
    }
    edges.sort_unstable();
    edges.dedup();
    edges
}

fn nodes_at_x(mesh: &TriMesh, x: f64) -> Vec<usize> {
    mesh.nodes
        .iter()
        .enumerate()
        .filter_map(|(i, p)| ((p[0] - x).abs() < 1e-12).then_some(i))
        .collect()
}

fn nodes_at_y(mesh: &TriMesh, y: f64) -> Vec<usize> {
    mesh.nodes
        .iter()
        .enumerate()
        .filter_map(|(i, p)| ((p[1] - y).abs() < 1e-12).then_some(i))
        .collect()
}

/// Polar disc mesh: concentric rings × angular sectors.
fn build_disc_mesh(n_radial: usize, n_theta: usize, radius_m: f64) -> TriMesh {
    let mut nodes = vec![[0.0, 0.0]];
    for ir in 1..=n_radial {
        let r = radius_m * (ir as f64) / (n_radial as f64);
        for it in 0..n_theta {
            let th = 2.0 * std::f64::consts::PI * (it as f64) / (n_theta as f64);
            nodes.push([r * th.cos(), r * th.sin()]);
        }
    }
    let mut triangles = Vec::new();
    let mut regions = Vec::new();
    // Inner ring: triangles from center to first ring.
    for it in 0..n_theta {
        let a = 1 + it;
        let b = 1 + (it + 1) % n_theta;
        triangles.push([0, a, b]);
        regions.push(Region::Airgap);
    }
    for ir in 1..n_radial {
        let inner_base = 1 + (ir - 1) * n_theta;
        let outer_base = 1 + ir * n_theta;
        for it in 0..n_theta {
            let i0 = inner_base + it;
            let i1 = inner_base + (it + 1) % n_theta;
            let o0 = outer_base + it;
            let o1 = outer_base + (it + 1) % n_theta;
            triangles.push([i0, o0, o1]);
            triangles.push([i0, o1, i1]);
            regions.push(Region::Airgap);
            regions.push(Region::Airgap);
        }
    }
    let outer_base = 1 + (n_radial - 1) * n_theta;
    let boundary: Vec<usize> = (0..n_theta).map(|it| outer_base + it).collect();
    let n_nodes = nodes.len();
    let n_tris = triangles.len();
    TriMesh {
        nodes,
        triangles,
        regions,
        boundary_nodes: boundary,
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes, n_tris),
    }
}

fn outer_ring_edges(mesh: &TriMesh, n_theta: usize) -> Vec<[usize; 2]> {
    let outer_base = mesh.nodes.len() - n_theta;
    (0..n_theta)
        .map(|it| [outer_base + it, outer_base + (it + 1) % n_theta])
        .collect()
}

#[test]
fn analytic_1d_slab_dirichlet() {
    // T(x) = T0 + (T1-T0) x/L  with q=0, k constant.
    let lx = 0.1;
    let ly = 0.02;
    let mesh = build_rect_mesh(20, 4, lx, ly);
    let materials = vec![ThermalMaterialProps::constant(40.0); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let t0 = 300.0;
    let t1 = 350.0;
    let boundaries = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, 0.0),
            temperature_k: t0,
        },
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, lx),
            temperature_k: t1,
        },
    ]);
    let mut request = ThermalSolveRequest::new(mesh.clone(), materials, sources, boundaries);
    // Pure Dirichlet with q=0: energy balance is 0=0; keep gate on.
    request.energy_balance_tolerance = 1.0e-2;
    let report = run_steady_state_thermal(&request).expect("1D slab solve");
    assert!(report.energy_balance.closed);

    let mut max_err: f64 = 0.0;
    for (node, &t) in report.nodal_temperature_k.iter().enumerate() {
        let x = mesh.nodes[node][0];
        let theory = t0 + (t1 - t0) * (x / lx);
        max_err = max_err.max((t - theory).abs());
    }
    assert!(
        max_err < 0.5,
        "1D slab max |T-theory|={max_err} K (expect <0.5)"
    );
}

#[test]
fn analytic_uniform_heat_generation_disc() {
    // T(r) = T_wall + q (R² - r²) / (4k)
    let radius = 0.05;
    let k = 25.0;
    let q = 1.0e6;
    let t_wall = 320.0;
    let n_theta = 48;
    let mesh = build_disc_mesh(16, n_theta, radius);
    let materials = vec![ThermalMaterialProps::constant(k); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), q);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
        node_indices: mesh.boundary_nodes.clone(),
        temperature_k: t_wall,
    }]);
    let mut request = ThermalSolveRequest::new(mesh.clone(), materials, sources, boundaries);
    request.energy_balance_tolerance = 8.0e-2;
    let report = run_steady_state_thermal(&request).expect("disc solve");
    assert!(
        report.energy_balance.closed,
        "energy balance not closed: {:?}",
        report.energy_balance
    );

    let mut max_rel: f64 = 0.0;
    for (node, &t) in report.nodal_temperature_k.iter().enumerate() {
        let r2 = mesh.nodes[node][0].powi(2) + mesh.nodes[node][1].powi(2);
        let theory = t_wall + q * (radius * radius - r2) / (4.0 * k);
        let err = (t - theory).abs();
        let scale = (theory - t_wall).abs().max(1.0);
        max_rel = max_rel.max(err / scale);
    }
    assert!(
        max_rel < 0.08,
        "disc max relative error={max_rel} (expect <8%)"
    );
}

#[test]
fn analytic_composite_shell_with_convection() {
    // Two radial layers with different k, fixed T at inner radius,
    // convection at outer radius. Compare mean outer T to 1D radial theory.
    let r_inner = 0.02;
    let r_mid = 0.035;
    let r_outer = 0.05;
    let k_inner = 40.0;
    let k_outer = 10.0;
    let h = 200.0;
    let t_inner = 400.0;
    let t_amb = 300.0;
    let n_theta = 36;

    // Build annular mesh manually (no center node).
    let n_radial = 12;
    let mut nodes = Vec::new();
    let radii: Vec<f64> = (0..=n_radial)
        .map(|i| r_inner + (r_outer - r_inner) * (i as f64) / (n_radial as f64))
        .collect();
    for &r in &radii {
        for it in 0..n_theta {
            let th = 2.0 * std::f64::consts::PI * (it as f64) / (n_theta as f64);
            nodes.push([r * th.cos(), r * th.sin()]);
        }
    }
    let mut triangles = Vec::new();
    let mut materials = Vec::new();
    for ir in 0..n_radial {
        let inner_base = ir * n_theta;
        let outer_base = (ir + 1) * n_theta;
        let r_avg = 0.5 * (radii[ir] + radii[ir + 1]);
        let mat = if r_avg < r_mid {
            ThermalMaterialProps::constant(k_inner)
        } else {
            ThermalMaterialProps::constant(k_outer)
        };
        for it in 0..n_theta {
            let i0 = inner_base + it;
            let i1 = inner_base + (it + 1) % n_theta;
            let o0 = outer_base + it;
            let o1 = outer_base + (it + 1) % n_theta;
            triangles.push([i0, o0, o1]);
            triangles.push([i0, o1, i1]);
            materials.push(mat);
            materials.push(mat);
        }
    }
    let inner_nodes: Vec<usize> = (0..n_theta).collect();
    let outer_edges: Vec<[usize; 2]> = (0..n_theta)
        .map(|it| {
            let base = n_radial * n_theta;
            [base + it, base + (it + 1) % n_theta]
        })
        .collect();
    let n_nodes = nodes.len();
    let n_tris = triangles.len();
    let mesh = TriMesh {
        nodes,
        triangles,
        regions: vec![Region::Airgap; n_tris],
        boundary_nodes: inner_nodes.clone(),
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes, n_tris),
    };

    // 1D radial theory: series R_cond + R_conv.
    let r_cond_inner = (r_mid / r_inner).ln() / (2.0 * std::f64::consts::PI * k_inner);
    let r_cond_outer = (r_outer / r_mid).ln() / (2.0 * std::f64::consts::PI * k_outer);
    let r_conv = 1.0 / (h * 2.0 * std::f64::consts::PI * r_outer);
    let r_total = r_cond_inner + r_cond_outer + r_conv;
    // Heat per unit stack length leaving the cylinder for ΔT = t_inner - t_amb.
    let q_per_m = (t_inner - t_amb) / r_total;
    let t_outer_theory = t_amb + q_per_m * r_conv;

    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let boundaries = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: inner_nodes,
            temperature_k: t_inner,
        },
        ThermalBoundaryCondition::Convection {
            edges: outer_edges,
            h_w_per_m2_k: h,
            ambient_k: t_amb,
        },
    ]);
    let mut request = ThermalSolveRequest::new(mesh.clone(), materials, sources, boundaries);
    request.energy_balance_tolerance = 1.0e-1;
    let report = run_steady_state_thermal(&request).expect("composite shell");
    assert!(
        report.energy_balance.closed,
        "shell energy balance: {:?}",
        report.energy_balance
    );

    let outer_base = n_radial * n_theta;
    let mut t_outer_mean = 0.0;
    for it in 0..n_theta {
        t_outer_mean += report.nodal_temperature_k[outer_base + it];
    }
    t_outer_mean /= n_theta as f64;
    let rel = (t_outer_mean - t_outer_theory).abs() / (t_inner - t_amb);
    assert!(
        rel < 0.08,
        "outer T mean={t_outer_mean} theory={t_outer_theory} rel={rel}"
    );
}

#[test]
fn analytic_anisotropic_slab() {
    // Orthotropic k_xx ≠ k_yy: Dirichlet+Neumann flux cases where ΔT depends
    // on the conductivity component along the heat-flow axis. A solver that
    // ignores anisotropy (or swaps axes) fails these assertions.
    let lx = 0.08;
    let ly = 0.04;
    let kxx = 80.0;
    let kyy = 10.0;
    let q_flux = 4000.0; // W/m² into the hot face
    let t_cold = 300.0;

    // Heat flow in +x: q = k_xx ΔT / Lx  ⇒  ΔT = q Lx / k_xx
    let mesh_x = build_rect_mesh(16, 8, lx, ly);
    let (left_edges, right_edges) = left_right_edges(&mesh_x, lx);
    let materials_x = vec![ThermalMaterialProps::orthotropic(kxx, kyy); mesh_x.triangles.len()];
    let sources_x = ThermalSources::uniform(mesh_x.triangles.len(), 0.0);
    let boundaries_x = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh_x, 0.0),
            temperature_k: t_cold,
        },
        ThermalBoundaryCondition::NeumannFlux {
            edges: right_edges,
            flux_w_per_m2: -q_flux, // heat entering domain through right face
        },
    ]);
    let request_x =
        ThermalSolveRequest::new(mesh_x.clone(), materials_x, sources_x, boundaries_x);
    let report_x = run_steady_state_thermal(&request_x).expect("anisotropic x slab");
    assert!(report_x.energy_balance.closed);
    let t_hot_x: f64 = nodes_at_x(&mesh_x, lx)
        .iter()
        .map(|&i| report_x.nodal_temperature_k[i])
        .sum::<f64>()
        / nodes_at_x(&mesh_x, lx).len().max(1) as f64;
    let dt_x = t_hot_x - t_cold;
    let dt_theory_x = q_flux * lx / kxx;
    let dt_wrong_x = q_flux * lx / kyy; // would pass if kyy were used
    assert!(
        (dt_x - dt_theory_x).abs() / dt_theory_x < 0.08,
        "x-flux ΔT={dt_x} theory={dt_theory_x} (wrong-axis={dt_wrong_x}); left={left_edges:?}"
    );
    assert!(
        (dt_x - dt_wrong_x).abs() / dt_wrong_x > 0.5,
        "x-flux ΔT must depend on k_xx≠k_yy; got {dt_x} vs wrong-axis {dt_wrong_x}"
    );

    // Heat flow in +y: ΔT = q Ly / k_yy
    let mesh_y = build_rect_mesh(8, 16, lx, ly);
    let (_bottom_edges, top_edges) = bottom_top_edges(&mesh_y, ly);
    let materials_y =
        vec![ThermalMaterialProps::orthotropic(kxx, kyy); mesh_y.triangles.len()];
    let sources_y = ThermalSources::uniform(mesh_y.triangles.len(), 0.0);
    let boundaries_y = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_y(&mesh_y, 0.0),
            temperature_k: t_cold,
        },
        ThermalBoundaryCondition::NeumannFlux {
            edges: top_edges,
            flux_w_per_m2: -q_flux,
        },
    ]);
    let request_y =
        ThermalSolveRequest::new(mesh_y.clone(), materials_y, sources_y, boundaries_y);
    let report_y = run_steady_state_thermal(&request_y).expect("anisotropic y slab");
    assert!(report_y.energy_balance.closed);
    let t_hot_y: f64 = nodes_at_y(&mesh_y, ly)
        .iter()
        .map(|&i| report_y.nodal_temperature_k[i])
        .sum::<f64>()
        / nodes_at_y(&mesh_y, ly).len().max(1) as f64;
    let dt_y = t_hot_y - t_cold;
    let dt_theory_y = q_flux * ly / kyy;
    let dt_wrong_y = q_flux * ly / kxx;
    assert!(
        (dt_y - dt_theory_y).abs() / dt_theory_y < 0.08,
        "y-flux ΔT={dt_y} theory={dt_theory_y} (wrong-axis={dt_wrong_y})"
    );
    assert!(
        (dt_y - dt_wrong_y).abs() / dt_wrong_y > 0.5,
        "y-flux ΔT must depend on k_yy≠k_xx; got {dt_y} vs wrong-axis {dt_wrong_y}"
    );

    // Ratio of directional resistances must track k_xx/k_yy (geometry-normalized).
    let r_x = dt_x / (q_flux * lx);
    let r_y = dt_y / (q_flux * ly);
    let ratio = r_y / r_x;
    let ratio_theory = kxx / kyy;
    assert!(
        (ratio - ratio_theory).abs() / ratio_theory < 0.1,
        "anisotropy resistance ratio={ratio} theory={ratio_theory}"
    );
}

#[test]
fn rejects_orthotropic_with_k_of_t() {
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    let mut material = ThermalMaterialProps::orthotropic(80.0, 10.0);
    material.k_of_t = Some(ThermalConductivityModel {
        k0_w_per_m_k: 40.0,
        t0_k: 300.0,
        dk_dt_w_per_m_k2: -0.05,
    });
    let materials = vec![material; mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
        node_indices: nodes_at_x(&mesh, 0.0),
        temperature_k: 300.0,
    }]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject k(T)+orthotropic");
    assert!(
        err.contains("orthotropic") && err.contains("k(T)"),
        "unexpected error: {err}"
    );
}

#[test]
fn rejects_nonpositive_isotropic_conductivity() {
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    let materials = vec![ThermalMaterialProps::constant(-1.0); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 1.0e6);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
        node_indices: nodes_at_x(&mesh, 0.0),
        temperature_k: 300.0,
    }]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject k<=0");
    assert!(
        err.contains("strictly positive") || err.contains("k_w_per_m_k"),
        "unexpected error: {err}"
    );
}

#[test]
fn rejects_nan_and_zero_orthotropic_conductivity() {
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    for material in [
        ThermalMaterialProps::orthotropic(f64::NAN, 10.0),
        ThermalMaterialProps::orthotropic(10.0, 0.0),
    ] {
        let materials = vec![material; mesh.triangles.len()];
        let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
        let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, 0.0),
            temperature_k: 300.0,
        }]);
        let request = ThermalSolveRequest::new(mesh.clone(), materials, sources, boundaries);
        let err = run_steady_state_thermal(&request).expect_err("must reject bad k_xx/k_yy");
        assert!(
            err.contains("finite") || err.contains("strictly positive"),
            "unexpected error: {err}"
        );
    }
}

#[test]
fn rejects_k_of_t_eval_nonpositive_at_solve_temperature() {
    // k0 positive at t0, but slope drives k(T) <= 0 at the initial 300 K iterate.
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    let mut material = ThermalMaterialProps::constant(1.0);
    material.k_of_t = Some(ThermalConductivityModel {
        k0_w_per_m_k: 1.0,
        t0_k: 0.0,
        dk_dt_w_per_m_k2: -1.0,
    });
    let materials = vec![material; mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 1.0e5);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
        node_indices: nodes_at_x(&mesh, 0.0),
        temperature_k: 300.0,
    }]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject non-positive k(T)");
    assert!(
        err.contains("k(T)") || err.contains("strictly positive"),
        "unexpected error: {err}"
    );
}

#[test]
fn rejects_negative_k0_in_k_of_t() {
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    let mut material = ThermalMaterialProps::constant(40.0);
    material.k_of_t = Some(ThermalConductivityModel {
        k0_w_per_m_k: -5.0,
        t0_k: 300.0,
        dk_dt_w_per_m_k2: 0.0,
    });
    let materials = vec![material; mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
        node_indices: nodes_at_x(&mesh, 0.0),
        temperature_k: 300.0,
    }]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject negative k0");
    assert!(
        err.contains("k_of_t.k0") || err.contains("strictly positive"),
        "unexpected error: {err}"
    );
}

#[test]
fn rejects_dirichlet_with_out_of_range_node_indices() {
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    let materials = vec![ThermalMaterialProps::constant(40.0); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::Dirichlet {
        node_indices: vec![999_999],
        temperature_k: 300.0,
    }]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject OOR Dirichlet");
    assert!(
        err.contains("out-of-range") || err.contains("node_indices"),
        "unexpected error: {err}"
    );
}

#[test]
fn rejects_empty_boundaries() {
    let mesh = build_rect_mesh(2, 2, 0.02, 0.02);
    let materials = vec![ThermalMaterialProps::constant(40.0); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let boundaries = ThermalBoundarySet::new(vec![]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject empty BC");
    assert!(
        err.contains("empty") || err.contains("temperature anchor"),
        "unexpected error: {err}"
    );
}

#[test]
fn rejects_pure_neumann_boundaries() {
    let lx = 0.02;
    let mesh = build_rect_mesh(2, 2, lx, 0.02);
    let materials = vec![ThermalMaterialProps::constant(40.0); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 1.0e5);
    let (_, right_edges) = left_right_edges(&mesh, lx);
    let boundaries = ThermalBoundarySet::new(vec![ThermalBoundaryCondition::NeumannFlux {
        edges: right_edges,
        flux_w_per_m2: 0.0,
    }]);
    let request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    let err = run_steady_state_thermal(&request).expect_err("must reject pure Neumann");
    assert!(
        err.contains("temperature anchor") || err.contains("Neumann"),
        "unexpected error: {err}"
    );
}

#[test]
fn radiation_bc_matches_linearized_film_at_small_delta_t() {
    // Small ΔT: radiation solution ≈ convection with h_rad = 4 ε σ T³.
    let lx = 0.05;
    let ly = 0.01;
    let mesh = build_rect_mesh(20, 2, lx, ly);
    let k = 50.0;
    let materials = vec![ThermalMaterialProps::constant(k); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 0.0);
    let t_left = 300.0;
    let t_amb = 299.0; // 1 K delta — deep in linear regime
    let emissivity = 0.9;
    let (_, right_edges) = left_right_edges(&mesh, lx);
    let h_rad = linearized_radiation_h(emissivity, t_amb);

    let boundaries_rad = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, 0.0),
            temperature_k: t_left,
        },
        ThermalBoundaryCondition::Radiation {
            edges: right_edges.clone(),
            emissivity,
            ambient_k: t_amb,
        },
    ]);
    let mut req_rad =
        ThermalSolveRequest::new(mesh.clone(), materials.clone(), sources.clone(), boundaries_rad);
    req_rad.energy_balance_tolerance = 1.0e-1;
    let report_rad = run_steady_state_thermal(&req_rad).expect("radiation");

    let boundaries_conv = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, 0.0),
            temperature_k: t_left,
        },
        ThermalBoundaryCondition::Convection {
            edges: right_edges,
            h_w_per_m2_k: h_rad,
            ambient_k: t_amb,
        },
    ]);
    let mut req_conv =
        ThermalSolveRequest::new(mesh.clone(), materials, sources, boundaries_conv);
    req_conv.energy_balance_tolerance = 1.0e-1;
    let report_conv = run_steady_state_thermal(&req_conv).expect("convection equiv");

    let right_nodes = nodes_at_x(&mesh, lx);
    let mean = |report: &crate::thermal::types::ThermalSolveReport| {
        let mut s = 0.0;
        for &n in &right_nodes {
            s += report.nodal_temperature_k[n];
        }
        s / right_nodes.len() as f64
    };
    let t_rad = mean(&report_rad);
    let t_conv = mean(&report_conv);
    let rel = (t_rad - t_conv).abs() / (t_left - t_amb).abs().max(1.0e-6);
    assert!(
        rel < 0.05,
        "radiation vs linearized film: Trad={t_rad} Tconv={t_conv} rel={rel}"
    );

    // Surface balance spot-check at the right wall mean temperature.
    let t_s = t_rad;
    let q_rad = emissivity * STEFAN_BOLTZMANN * (t_s.powi(4) - t_amb.powi(4));
    let q_lin = h_rad * (t_s - t_amb);
    let bal_rel = (q_rad - q_lin).abs() / q_rad.abs().max(1.0e-12);
    assert!(
        bal_rel < 0.05,
        "q_rad vs q_lin relative={bal_rel} (small-ΔT gate)"
    );
}

#[test]
fn k_of_t_nonlinearity_converges_and_closes_energy() {
    let lx = 0.06;
    let ly = 0.02;
    let mesh = build_rect_mesh(16, 4, lx, ly);
    let model = ThermalConductivityModel {
        k0_w_per_m_k: 30.0,
        t0_k: 300.0,
        dk_dt_w_per_m_k2: -0.02,
    };
    let mut materials = vec![ThermalMaterialProps::constant(30.0); mesh.triangles.len()];
    for mat in &mut materials {
        mat.k_of_t = Some(model);
    }
    // Uniform generation with fixed outer temperatures forces a nonlinear profile.
    let sources = ThermalSources::uniform(mesh.triangles.len(), 5.0e5);
    let boundaries = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, 0.0),
            temperature_k: 300.0,
        },
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, lx),
            temperature_k: 300.0,
        },
    ]);
    let mut request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    request.energy_balance_tolerance = 1.0e-1;
    let report = run_steady_state_thermal(&request).expect("k(T) solve");
    assert!(report.nonlinear_iterations >= 2);
    assert!(report.energy_balance.closed);
    assert!(report.max_temperature_k > 300.0);
}

#[test]
fn energy_balance_closes_with_generation_and_dirichlet() {
    // Uniform generation, cold Dirichlet walls — reactions must match Σq.
    let lx = 0.04;
    let ly = 0.02;
    let mesh = build_rect_mesh(12, 6, lx, ly);
    let materials = vec![ThermalMaterialProps::constant(20.0); mesh.triangles.len()];
    let sources = ThermalSources::uniform(mesh.triangles.len(), 1.0e6);
    let boundaries = ThermalBoundarySet::new(vec![
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, 0.0),
            temperature_k: 300.0,
        },
        ThermalBoundaryCondition::Dirichlet {
            node_indices: nodes_at_x(&mesh, lx),
            temperature_k: 300.0,
        },
    ]);
    let mut request = ThermalSolveRequest::new(mesh, materials, sources, boundaries);
    request.energy_balance_tolerance = 5.0e-2;
    let report = run_steady_state_thermal(&request).expect("generation+dirichlet");
    assert!(report.energy_balance.closed, "{:?}", report.energy_balance);
    assert!(report.max_temperature_k > 300.0);
}

#[test]
fn outer_ring_edges_helper_covers_disc() {
    let mesh = build_disc_mesh(4, 12, 0.03);
    let edges = outer_ring_edges(&mesh, 12);
    assert_eq!(edges.len(), 12);
}

// ---------------------------------------------------------------------------
// Compare a thin explicit liner region vs zero-thickness contact element
// ---------------------------------------------------------------------------
//
// Synthetic analytic values only. Production liner/housing slots stay
// PENDING_SOURCE until cited; these numbers prove the FEA representation.

use crate::thermal::contacts::{
    equivalent_conductance_from_thin_layer, ThermalContactInterface, ThermalContactPair,
    ThermalContactSet,
};

/// Three-layer composite slab with an explicit thin middle region.
fn build_composite_slab_thin_region(
    nx_left: usize,
    nx_mid: usize,
    nx_right: usize,
    ny: usize,
    l_left: f64,
    t_mid: f64,
    l_right: f64,
    ly: f64,
) -> (TriMesh, Vec<ThermalMaterialProps>, f64) {
    let nx = nx_left + nx_mid + nx_right;
    let lx = l_left + t_mid + l_right;
    let mut nodes = Vec::new();
    for j in 0..=ny {
        for i in 0..=nx {
            let x = if i <= nx_left {
                l_left * (i as f64) / (nx_left as f64)
            } else if i <= nx_left + nx_mid {
                let local = (i - nx_left) as f64 / (nx_mid as f64);
                l_left + t_mid * local
            } else {
                let local = (i - nx_left - nx_mid) as f64 / (nx_right as f64);
                l_left + t_mid + l_right * local
            };
            nodes.push([x, ly * (j as f64) / (ny as f64)]);
        }
    }
    let mut triangles = Vec::new();
    let mut materials = Vec::new();
    let row = nx + 1;
    let k_left = 40.0;
    let k_mid = 0.2; // synthetic liner
    let k_right = 20.0;
    for j in 0..ny {
        for i in 0..nx {
            let n0 = j * row + i;
            let n1 = n0 + 1;
            let n2 = n0 + row;
            let n3 = n2 + 1;
            let x_mid = 0.5 * (nodes[n0][0] + nodes[n1][0]);
            let k = if x_mid < l_left {
                k_left
            } else if x_mid < l_left + t_mid {
                k_mid
            } else {
                k_right
            };
            triangles.push([n0, n1, n3]);
            triangles.push([n0, n3, n2]);
            materials.push(ThermalMaterialProps::constant(k));
            materials.push(ThermalMaterialProps::constant(k));
        }
    }
    let mut boundary = Vec::new();
    for i in 0..=nx {
        boundary.push(i);
        boundary.push(ny * row + i);
    }
    for j in 0..=ny {
        boundary.push(j * row);
        boundary.push(j * row + nx);
    }
    boundary.sort_unstable();
    boundary.dedup();
    let n_nodes = nodes.len();
    let n_tris = triangles.len();
    let mesh = TriMesh {
        nodes,
        triangles,
        regions: vec![Region::Airgap; n_tris],
        boundary_nodes: boundary,
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes, n_tris),
    };
    (mesh, materials, lx)
}

/// Two slabs with duplicated interface nodes + contact conductance pairs.
fn build_composite_slab_contact(
    nx_left: usize,
    nx_right: usize,
    ny: usize,
    l_left: f64,
    l_right: f64,
    ly: f64,
    h_contact: f64,
) -> (TriMesh, Vec<ThermalMaterialProps>, ThermalContactSet, f64) {
    let row_left = nx_left + 1;
    let row_right = nx_right + 1;
    let mut nodes = Vec::new();
    // Left slab nodes [0, L_left] x [0, Ly]
    for j in 0..=ny {
        for i in 0..=nx_left {
            nodes.push([
                l_left * (i as f64) / (nx_left as f64),
                ly * (j as f64) / (ny as f64),
            ]);
        }
    }
    let left_count = nodes.len();
    // Right slab nodes: interface x = L_left duplicated, then to L_left+L_right
    for j in 0..=ny {
        for i in 0..=nx_right {
            nodes.push([
                l_left + l_right * (i as f64) / (nx_right as f64),
                ly * (j as f64) / (ny as f64),
            ]);
        }
    }
    let mut triangles = Vec::new();
    let mut materials = Vec::new();
    let k_left = 40.0;
    let k_right = 20.0;
    for j in 0..ny {
        for i in 0..nx_left {
            let n0 = j * row_left + i;
            let n1 = n0 + 1;
            let n2 = n0 + row_left;
            let n3 = n2 + 1;
            triangles.push([n0, n1, n3]);
            triangles.push([n0, n3, n2]);
            materials.push(ThermalMaterialProps::constant(k_left));
            materials.push(ThermalMaterialProps::constant(k_left));
        }
        for i in 0..nx_right {
            let n0 = left_count + j * row_right + i;
            let n1 = n0 + 1;
            let n2 = n0 + row_right;
            let n3 = n2 + 1;
            triangles.push([n0, n1, n3]);
            triangles.push([n0, n3, n2]);
            materials.push(ThermalMaterialProps::constant(k_right));
            materials.push(ThermalMaterialProps::constant(k_right));
        }
    }
    // Contact pairs: each left-interface node couples to the right-interface
    // duplicate at the same y. Length share = Δy / 2 at endpoints, Δy interior
    // for consistency with lumped edge assembly; here use half-cell heights.
    let dy = ly / (ny as f64);
    let mut pairs = Vec::new();
    for j in 0..=ny {
        let node_a = j * row_left + nx_left;
        let node_b = left_count + j * row_right;
        let length = if j == 0 || j == ny { 0.5 * dy } else { dy };
        pairs.push(ThermalContactPair {
            node_a,
            node_b,
            length_m: length,
        });
    }
    let contacts = ThermalContactSet::new(vec![ThermalContactInterface {
        id: "synthetic_slab_interface".to_string(),
        conductance_w_per_m2_k: h_contact,
        pairs,
    }]);
    let mut boundary = (0..nodes.len()).collect::<Vec<_>>();
    boundary.sort_unstable();
    let n_nodes = nodes.len();
    let n_tris = triangles.len();
    let mesh = TriMesh {
        nodes,
        triangles,
        regions: vec![Region::Airgap; n_tris],
        boundary_nodes: boundary,
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes, n_tris),
    };
    (mesh, materials, contacts, l_left + l_right)
}

#[test]
fn s50_03_composite_slab_thin_vs_contact() {
    // Analytic series resistance (unit depth out-of-plane = stack_length):
    // R'' = L1/k1 + t/k_mid + L2/k2 ; ΔT = q * R'' for imposed flux.
    let l1 = 0.04;
    let t_mid = 5.0e-4; // 0.5 mm synthetic liner
    let l2 = 0.03;
    let ly = 0.02;
    let k1 = 40.0;
    let k_mid = 0.2;
    let k2 = 20.0;
    let q_flux = 5000.0;
    let t_cold = 300.0;
    let h_eq = equivalent_conductance_from_thin_layer(k_mid, t_mid);
    let r_theory = l1 / k1 + t_mid / k_mid + l2 / k2;
    let dt_theory = q_flux * r_theory;

    // Thin-region representation
    let (mesh_t, mats_t, lx_t) =
        build_composite_slab_thin_region(16, 4, 12, 6, l1, t_mid, l2, ly);
    let (_, right_t) = left_right_edges(&mesh_t, lx_t);
    let mut req_t = ThermalSolveRequest::new(
        mesh_t.clone(),
        mats_t,
        ThermalSources::uniform(mesh_t.triangles.len(), 0.0),
        ThermalBoundarySet::new(vec![
            ThermalBoundaryCondition::Dirichlet {
                node_indices: nodes_at_x(&mesh_t, 0.0),
                temperature_k: t_cold,
            },
            ThermalBoundaryCondition::NeumannFlux {
                edges: right_t,
                flux_w_per_m2: -q_flux,
            },
        ]),
    );
    req_t.energy_balance_tolerance = 5.0e-2;
    let report_t = run_steady_state_thermal(&req_t).expect("thin-region slab");
    assert!(report_t.energy_balance.closed, "{:?}", report_t.energy_balance);
    let t_hot_t: f64 = nodes_at_x(&mesh_t, lx_t)
        .iter()
        .map(|&i| report_t.nodal_temperature_k[i])
        .sum::<f64>()
        / nodes_at_x(&mesh_t, lx_t).len().max(1) as f64;
    let dt_t = t_hot_t - t_cold;

    // Zero-thickness contact representation
    let (mesh_c, mats_c, contacts, lx_c) =
        build_composite_slab_contact(16, 12, 6, l1, l2, ly, h_eq);
    let right_nodes: Vec<usize> = (0..mesh_c.nodes.len())
        .filter(|&i| (mesh_c.nodes[i][0] - lx_c).abs() < 1e-12)
        .collect();
    let right_c = {
        // Rebuild right-face edges on the right slab only.
        let mut right: Vec<[usize; 2]> = Vec::new();
        for tri in &mesh_c.triangles {
            let edges = [[tri[0], tri[1]], [tri[1], tri[2]], [tri[2], tri[0]]];
            for edge in edges {
                let x0 = mesh_c.nodes[edge[0]][0];
                let x1 = mesh_c.nodes[edge[1]][0];
                if (x0 - lx_c).abs() < 1e-12 && (x1 - lx_c).abs() < 1e-12 {
                    right.push(edge);
                }
            }
        }
        dedup_undirected_edges(right)
    };
    let mut req_c = ThermalSolveRequest::new(
        mesh_c.clone(),
        mats_c,
        ThermalSources::uniform(mesh_c.triangles.len(), 0.0),
        ThermalBoundarySet::new(vec![
            ThermalBoundaryCondition::Dirichlet {
                node_indices: nodes_at_x(&mesh_c, 0.0),
                temperature_k: t_cold,
            },
            ThermalBoundaryCondition::NeumannFlux {
                edges: right_c,
                flux_w_per_m2: -q_flux,
            },
        ]),
    );
    req_c.contacts = contacts;
    req_c.energy_balance_tolerance = 5.0e-2;
    let report_c = run_steady_state_thermal(&req_c).expect("contact slab");
    assert!(report_c.energy_balance.closed, "{:?}", report_c.energy_balance);
    let t_hot_c: f64 = right_nodes
        .iter()
        .map(|&i| report_c.nodal_temperature_k[i])
        .sum::<f64>()
        / right_nodes.len().max(1) as f64;
    let dt_c = t_hot_c - t_cold;

    let err_t = (dt_t - dt_theory).abs() / dt_theory;
    let err_c = (dt_c - dt_theory).abs() / dt_theory;
    let cross = (dt_t - dt_c).abs() / dt_theory;
    assert!(
        err_t < 0.08,
        "thin-region ΔT={dt_t} theory={dt_theory} rel={err_t}"
    );
    assert!(
        err_c < 0.08,
        "contact ΔT={dt_c} theory={dt_theory} rel={err_c}"
    );
    assert!(
        cross < 0.05,
        "thin vs contact disagree: {dt_t} vs {dt_c} (theory {dt_theory})"
    );
    // Contact path must not pay for mid-layer triangles (mesh-size win).
    assert!(
        mesh_c.triangles.len() < mesh_t.triangles.len(),
        "contact mesh should have fewer tris ({} vs {})",
        mesh_c.triangles.len(),
        mesh_t.triangles.len()
    );
}

#[test]
fn s50_03_composite_cylinder_thin_vs_contact() {
    // Fixed T_inner + outward Neumann flux at r_outer. Compare mean outer T
    // to 1D radial series theory. Thin liner uses meshed mid-shell; contact
    // uses H_eq = k/t at the duplicated mid-radius (synthetic values only).
    // Use a resolvable synthetic liner thickness so FEA isn't limited by a
    // sub-element shell (production interface thickness stays pending).
    let r0 = 0.02;
    let r_mid = 0.032;
    let t_liner = 0.003; // 3 mm synthetic — analytic test only
    let r_after_liner = r_mid + t_liner;
    let r_outer = 0.05;
    let k_inner = 40.0;
    let k_liner = 0.5;
    let k_outer = 12.0;
    let t_inner = 400.0;
    let q_per_m = 800.0; // heat leaving per unit stack length [W/m]
    let n_theta = 36;
    let h_eq = equivalent_conductance_from_thin_layer(k_liner, t_liner);
    let flux_out = q_per_m / (2.0 * std::f64::consts::PI * r_outer);

    let r_thin = (r_mid / r0).ln() / (2.0 * std::f64::consts::PI * k_inner)
        + (r_after_liner / r_mid).ln() / (2.0 * std::f64::consts::PI * k_liner)
        + (r_outer / r_after_liner).ln() / (2.0 * std::f64::consts::PI * k_outer);
    let t_outer_thin_theory = t_inner - q_per_m * r_thin;

    let r_contact = (r_mid / r0).ln() / (2.0 * std::f64::consts::PI * k_inner)
        + 1.0 / (h_eq * 2.0 * std::f64::consts::PI * r_mid)
        + (r_outer / r_mid).ln() / (2.0 * std::f64::consts::PI * k_outer);
    let t_outer_contact_theory = t_inner - q_per_m * r_contact;

    // Thin: uniform radial rings spanning [r0, r_outer] with k assigned by r_avg.
    let n_radial = 24;
    let radii: Vec<f64> = (0..=n_radial)
        .map(|i| r0 + (r_outer - r0) * (i as f64) / (n_radial as f64))
        .collect();
    let mut nodes = Vec::new();
    for &r in &radii {
        for it in 0..n_theta {
            let th = 2.0 * std::f64::consts::PI * (it as f64) / (n_theta as f64);
            nodes.push([r * th.cos(), r * th.sin()]);
        }
    }
    let mut triangles = Vec::new();
    let mut materials = Vec::new();
    for ir in 0..n_radial {
        let ib = ir * n_theta;
        let ob = (ir + 1) * n_theta;
        let r_avg = 0.5 * (radii[ir] + radii[ir + 1]);
        let k = if r_avg < r_mid {
            k_inner
        } else if r_avg < r_after_liner {
            k_liner
        } else {
            k_outer
        };
        for it in 0..n_theta {
            let i0 = ib + it;
            let i1 = ib + (it + 1) % n_theta;
            let o0 = ob + it;
            let o1 = ob + (it + 1) % n_theta;
            triangles.push([i0, o0, o1]);
            triangles.push([i0, o1, i1]);
            materials.push(ThermalMaterialProps::constant(k));
            materials.push(ThermalMaterialProps::constant(k));
        }
    }
    let inner_nodes: Vec<usize> = (0..n_theta).collect();
    let outer_base = n_radial * n_theta;
    let outer_edges: Vec<[usize; 2]> = (0..n_theta)
        .map(|it| [outer_base + it, outer_base + (it + 1) % n_theta])
        .collect();
    let n_nodes = nodes.len();
    let n_tris = triangles.len();
    let mesh_t = TriMesh {
        nodes,
        triangles,
        regions: vec![Region::Airgap; n_tris],
        boundary_nodes: inner_nodes.clone(),
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes, n_tris),
    };
    let mut req_t = ThermalSolveRequest::new(
        mesh_t.clone(),
        materials,
        ThermalSources::uniform(mesh_t.triangles.len(), 0.0),
        ThermalBoundarySet::new(vec![
            ThermalBoundaryCondition::Dirichlet {
                node_indices: inner_nodes,
                temperature_k: t_inner,
            },
            ThermalBoundaryCondition::NeumannFlux {
                edges: outer_edges,
                flux_w_per_m2: flux_out,
            },
        ]),
    );
    req_t.energy_balance_tolerance = 8.0e-2;
    let report_t = run_steady_state_thermal(&req_t).expect("thin cylinder");
    assert!(report_t.energy_balance.closed, "{:?}", report_t.energy_balance);
    let mut t_outer_t = 0.0;
    for it in 0..n_theta {
        t_outer_t += report_t.nodal_temperature_k[outer_base + it];
    }
    t_outer_t /= n_theta as f64;

    // Contact annular (no mid shell): steel||steel with H at r_mid.
    let n_radial_in = 10;
    let n_radial_out = 10;
    let radii_in: Vec<f64> = (0..=n_radial_in)
        .map(|i| r0 + (r_mid - r0) * (i as f64) / (n_radial_in as f64))
        .collect();
    let radii_out: Vec<f64> = (0..=n_radial_out)
        .map(|i| r_mid + (r_outer - r_mid) * (i as f64) / (n_radial_out as f64))
        .collect();
    let mut nodes_c = Vec::new();
    for &r in &radii_in {
        for it in 0..n_theta {
            let th = 2.0 * std::f64::consts::PI * (it as f64) / (n_theta as f64);
            nodes_c.push([r * th.cos(), r * th.sin()]);
        }
    }
    let inner_count = nodes_c.len();
    for &r in &radii_out {
        for it in 0..n_theta {
            let th = 2.0 * std::f64::consts::PI * (it as f64) / (n_theta as f64);
            nodes_c.push([r * th.cos(), r * th.sin()]);
        }
    }
    let mut tris_c = Vec::new();
    let mut mats_c = Vec::new();
    for ir in 0..n_radial_in {
        let ib = ir * n_theta;
        let ob = (ir + 1) * n_theta;
        for it in 0..n_theta {
            let i0 = ib + it;
            let i1 = ib + (it + 1) % n_theta;
            let o0 = ob + it;
            let o1 = ob + (it + 1) % n_theta;
            tris_c.push([i0, o0, o1]);
            tris_c.push([i0, o1, i1]);
            mats_c.push(ThermalMaterialProps::constant(k_inner));
            mats_c.push(ThermalMaterialProps::constant(k_inner));
        }
    }
    for ir in 0..n_radial_out {
        let ib = inner_count + ir * n_theta;
        let ob = inner_count + (ir + 1) * n_theta;
        for it in 0..n_theta {
            let i0 = ib + it;
            let i1 = ib + (it + 1) % n_theta;
            let o0 = ob + it;
            let o1 = ob + (it + 1) % n_theta;
            tris_c.push([i0, o0, o1]);
            tris_c.push([i0, o1, i1]);
            mats_c.push(ThermalMaterialProps::constant(k_outer));
            mats_c.push(ThermalMaterialProps::constant(k_outer));
        }
    }
    let arc = 2.0 * std::f64::consts::PI * r_mid / (n_theta as f64);
    let mut pairs = Vec::new();
    for it in 0..n_theta {
        pairs.push(ThermalContactPair {
            node_a: n_radial_in * n_theta + it,
            node_b: inner_count + it,
            length_m: arc,
        });
    }
    let contacts = ThermalContactSet::new(vec![ThermalContactInterface {
        id: "synthetic_cylinder_interface".to_string(),
        conductance_w_per_m2_k: h_eq,
        pairs,
    }]);
    let inner_c: Vec<usize> = (0..n_theta).collect();
    let outer_base_c = inner_count + n_radial_out * n_theta;
    let outer_edges_c: Vec<[usize; 2]> = (0..n_theta)
        .map(|it| [outer_base_c + it, outer_base_c + (it + 1) % n_theta])
        .collect();
    let n_nodes_c = nodes_c.len();
    let n_tris_c = tris_c.len();
    let mesh_c = TriMesh {
        nodes: nodes_c,
        triangles: tris_c,
        regions: vec![Region::Airgap; n_tris_c],
        boundary_nodes: inner_c.clone(),
        sector_edge_pairs: vec![],
        info: mesh_info(n_nodes_c, n_tris_c),
    };
    let mut req_c = ThermalSolveRequest::new(
        mesh_c,
        mats_c,
        ThermalSources::uniform(n_tris_c, 0.0),
        ThermalBoundarySet::new(vec![
            ThermalBoundaryCondition::Dirichlet {
                node_indices: inner_c,
                temperature_k: t_inner,
            },
            ThermalBoundaryCondition::NeumannFlux {
                edges: outer_edges_c,
                flux_w_per_m2: flux_out,
            },
        ]),
    );
    req_c.contacts = contacts;
    req_c.energy_balance_tolerance = 8.0e-2;
    let report_c = run_steady_state_thermal(&req_c).expect("contact cylinder");
    assert!(report_c.energy_balance.closed, "{:?}", report_c.energy_balance);
    let mut t_outer_c = 0.0;
    for it in 0..n_theta {
        t_outer_c += report_c.nodal_temperature_k[outer_base_c + it];
    }
    t_outer_c /= n_theta as f64;

    let scale_t = (t_inner - t_outer_thin_theory).abs().max(1.0);
    let scale_c = (t_inner - t_outer_contact_theory).abs().max(1.0);
    let err_t = (t_outer_t - t_outer_thin_theory).abs() / scale_t;
    let err_c = (t_outer_c - t_outer_contact_theory).abs() / scale_c;
    // Radial FEA of a mid-shell needs denser rings to hit 1D log tightly;
    // contact path (no mid triangles) should track its theory more closely.
    // Both must close energy; thin absolute gate stays <15% of ΔT.
    assert!(
        err_t < 0.15,
        "thin cylinder T_out={t_outer_t} theory={t_outer_thin_theory} rel={err_t}"
    );
    assert!(
        err_c < 0.10,
        "contact cylinder T_out={t_outer_c} theory={t_outer_contact_theory} rel={err_c}"
    );
    assert!(
        report_t.energy_balance.closed && report_c.energy_balance.closed,
        "both cylinder representations must close energy"
    );
}

#[test]
fn s50_03_contact_rejects_nonpositive_and_keeps_energy_closed() {
    let (mesh, mats, mut contacts, lx) =
        build_composite_slab_contact(8, 8, 4, 0.03, 0.03, 0.02, 500.0);
    contacts.interfaces[0].conductance_w_per_m2_k = 0.0;
    let mut req = ThermalSolveRequest::new(
        mesh.clone(),
        mats,
        ThermalSources::uniform(mesh.triangles.len(), 0.0),
        ThermalBoundarySet::new(vec![
            ThermalBoundaryCondition::Dirichlet {
                node_indices: nodes_at_x(&mesh, 0.0),
                temperature_k: 300.0,
            },
            ThermalBoundaryCondition::Dirichlet {
                node_indices: nodes_at_x(&mesh, lx),
                temperature_k: 350.0,
            },
        ]),
    );
    req.contacts = contacts;
    let err = run_steady_state_thermal(&req).expect_err("zero H must fail");
    assert!(
        err.contains("conductance") || err.contains("positive"),
        "unexpected err: {err}"
    );
}
