//! Post-processing: B-field extraction and torque computation from A_z solution.

mod summary;
#[cfg(test)]
mod tests;
mod torque;

#[cfg(test)]
pub use summary::compute_flux_linkage;
#[cfg(test)]
pub use summary::compute_stator_core_loss;
pub use summary::{
    summarize_fields, CoreLossSummary,
    EnergyByRegionSummary, EnergyFunctionalSummary, FieldSummary, MagnetFieldEnergyDetailSummary,
    PmSidewallQuadratureDiagnosticSummary, PmSidewallQuadratureSelectedElement,
};
#[cfg(test)]
use torque::compute_torque_midgap_contour_debug_with_samples_from_az;
#[cfg(test)]
pub use torque::{
    compute_torque, compute_torque_midgap_contour_debug_with_samples,
    compute_torque_weighted_stress_debug,
};
pub use torque::{
    compute_torque_arkkio_debug, compute_torque_at_multiple_radii, compute_torque_debug,
    compute_torque_midgap_contour_debug, compute_torque_robust_contour_debug,
    compute_torque_weighted_stress_debug_with_az, ArkkioTorqueDebug, ContourTorqueDebug,
    RobustContourTorqueDebug, TorqueDebug, WeightedStressTorqueDebug,
};
use torque::{
    compute_torque_at_multiple_radii_from_az, compute_torque_midgap_contour_debug_from_az,
};

pub use crate::field::ElementField;
use crate::mesh::{Region, TriMesh};

#[derive(Debug, Clone, Copy)]
struct AirgapTriangleRecord {
    triangle_index: usize,
    tri_nodes: [usize; 3],
    tri_xy: [[f64; 2]; 3],
    bbox: [f64; 4],
}
pub fn compute_element_fields(mesh: &TriMesh, az: &[f64]) -> Vec<ElementField> {
    mesh.triangles
        .iter()
        .map(|tri| {
            let [i, j, m] = *tri;
            let (area, grad) = triangle_gradients(&mesh.nodes, i, j, m);
            if area < 1e-15 {
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
            let b_mag = (bx * bx + by * by).sqrt();

            ElementField { bx, by, b_mag }
        })
        .collect()
}

/// Compute node-averaged (B_x, B_y) from element-constant B fields.
///
/// Each node's B is the area-weighted average of B from all triangles incident
/// to the node. Interpolating this nodal field via barycentric weights produces
/// a C⁰-continuous B across triangle boundaries, eliminating the piecewise-
/// constant jitter that biases contour-based MST torque on coarse airgap meshes.
pub fn compute_nodal_b_field(mesh: &TriMesh, fields: &[ElementField]) -> Vec<[f64; 2]> {
    compute_filtered_nodal_b_field(mesh, fields, |_| true)
}

/// Compute node-averaged B using only incident elements accepted by `include_region`.
///
/// This preserves material-boundary discontinuities for diagnostics that sample
/// B on one side of a steel/air interface. For example, WST torque can average
/// only airgap/slot-winding elements at shared tooth-tip nodes instead of
/// smearing in stator-tooth gradients.
pub(crate) fn compute_filtered_nodal_b_field<F>(
    mesh: &TriMesh,
    fields: &[ElementField],
    include_region: F,
) -> Vec<[f64; 2]>
where
    F: Fn(Region) -> bool,
{
    let n_nodes = mesh.nodes.len();
    let mut sum_bx = vec![0.0_f64; n_nodes];
    let mut sum_by = vec![0.0_f64; n_nodes];
    let mut sum_w = vec![0.0_f64; n_nodes];
    for (idx, tri) in mesh.triangles.iter().enumerate() {
        if idx >= fields.len() || !include_region(mesh.regions[idx]) {
            continue;
        }
        let [i, j, m] = *tri;
        let area = triangle_area(&mesh.nodes, i, j, m);
        if area < 1e-15 {
            continue;
        }
        let f = &fields[idx];
        for &n in &[i, j, m] {
            sum_bx[n] += f.bx * area;
            sum_by[n] += f.by * area;
            sum_w[n] += area;
        }
    }
    (0..n_nodes)
        .map(|n| {
            if sum_w[n] > 0.0 {
                [sum_bx[n] / sum_w[n], sum_by[n] / sum_w[n]]
            } else {
                [0.0, 0.0]
            }
        })
        .collect()
}

/// Project a Cartesian (bx, by) pair into radial and tangential components at a point.
fn cartesian_to_polar_b(bx: f64, by: f64, point_xy_m: [f64; 2]) -> Option<(f64, f64)> {
    let r = (point_xy_m[0] * point_xy_m[0] + point_xy_m[1] * point_xy_m[1]).sqrt();
    if r < 1e-12 {
        return None;
    }
    let cos_theta = point_xy_m[0] / r;
    let sin_theta = point_xy_m[1] / r;
    let b_r = bx * cos_theta + by * sin_theta;
    let b_t = -bx * sin_theta + by * cos_theta;
    Some((b_r, b_t))
}

/// Project a Cartesian element field into radial and tangential components at a point.
///
/// Returns `(B_r, B_t)` using the same sign convention as the torque postprocess:
/// positive `B_t` points in the increasing-`theta` direction.
pub fn project_field_to_polar(field: &ElementField, point_xy_m: [f64; 2]) -> Option<(f64, f64)> {
    let r = (point_xy_m[0] * point_xy_m[0] + point_xy_m[1] * point_xy_m[1]).sqrt();
    if r < 1e-12 {
        return None;
    }

    let cos_theta = point_xy_m[0] / r;
    let sin_theta = point_xy_m[1] / r;
    let b_r = field.bx * cos_theta + field.by * sin_theta;
    let b_t = -field.bx * sin_theta + field.by * cos_theta;
    Some((b_r, b_t))
}

fn collect_airgap_triangle_records(mesh: &TriMesh) -> Vec<AirgapTriangleRecord> {
    let mut records = Vec::new();
    for (triangle_index, tri) in mesh.triangles.iter().enumerate() {
        if mesh.regions[triangle_index] != Region::Airgap {
            continue;
        }
        let [i, j, k] = *tri;
        let tri_xy = [mesh.nodes[i], mesh.nodes[j], mesh.nodes[k]];
        let xs = [tri_xy[0][0], tri_xy[1][0], tri_xy[2][0]];
        let ys = [tri_xy[0][1], tri_xy[1][1], tri_xy[2][1]];
        records.push(AirgapTriangleRecord {
            triangle_index,
            tri_nodes: *tri,
            tri_xy,
            bbox: [
                xs.iter().copied().fold(f64::INFINITY, f64::min),
                xs.iter().copied().fold(f64::NEG_INFINITY, f64::max),
                ys.iter().copied().fold(f64::INFINITY, f64::min),
                ys.iter().copied().fold(f64::NEG_INFINITY, f64::max),
            ],
        });
    }
    records
}

fn find_airgap_triangle_match<'a>(
    records: &'a [AirgapTriangleRecord],
    point_xy_m: [f64; 2],
) -> Option<(&'a AirgapTriangleRecord, [f64; 3])> {
    for record in records {
        let pad = 1e-9;
        if point_xy_m[0] < record.bbox[0] - pad
            || point_xy_m[0] > record.bbox[1] + pad
            || point_xy_m[1] < record.bbox[2] - pad
            || point_xy_m[1] > record.bbox[3] + pad
        {
            continue;
        }
        let Some(weights) = barycentric_weights(point_xy_m, record.tri_xy) else {
            continue;
        };
        return Some((record, weights));
    }
    None
}

fn interpolate_az_from_record(az: &[f64], record: &AirgapTriangleRecord, weights: [f64; 3]) -> f64 {
    weights[0] * az[record.tri_nodes[0]]
        + weights[1] * az[record.tri_nodes[1]]
        + weights[2] * az[record.tri_nodes[2]]
}

fn sample_az_on_airgap(
    records: &[AirgapTriangleRecord],
    az: &[f64],
    point_xy_m: [f64; 2],
) -> Option<f64> {
    let (record, weights) = find_airgap_triangle_match(records, point_xy_m)?;
    Some(interpolate_az_from_record(az, record, weights))
}

fn choose_az_contour_radial_step(mesh: &TriMesh, contour_radius_m: f64) -> f64 {
    let (mut inner_radius, mut outer_radius) = mesh
        .info
        .airgap_band()
        .map(|band| (band.inner_radius_m(), band.outer_radius_m()))
        .unwrap_or((0.0, 0.0));
    if !(outer_radius > inner_radius
        && contour_radius_m > inner_radius
        && outer_radius > contour_radius_m)
    {
        let working_radii = full_coverage_airgap_radii(mesh);
        if let (Some(first), Some(last)) = (working_radii.first(), working_radii.last()) {
            inner_radius = *first;
            outer_radius = *last;
        }
    }

    // Use the widest centered stencil contained in the source-free air gap.
    // A short stencil differentiates the P1 interpolation inside individual
    // triangles, making the small tangential field depend strongly on their
    // diagonals. Spanning the gap suppresses that interpolation bias.
    // The outer circular boundary is represented by straight mesh edges: its
    // inscribed radius, rather than the nominal radius, bounds a safe circle.
    let nominal_outer_radius = outer_radius;
    let radius_tolerance = nominal_outer_radius * 1e-8;
    for (tri, region) in mesh.triangles.iter().zip(&mesh.regions) {
        if *region != Region::Airgap {
            continue;
        }
        for (a, b) in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])] {
            let p = mesh.nodes[a];
            let q = mesh.nodes[b];
            let rp = p[0].hypot(p[1]);
            let rq = q[0].hypot(q[1]);
            if (rp - nominal_outer_radius).abs() <= radius_tolerance
                && (rq - nominal_outer_radius).abs() <= radius_tolerance
            {
                let chord_radius = 0.5 * (p[0] + q[0]).hypot(p[1] + q[1]);
                outer_radius = outer_radius.min(chord_radius);
            }
        }
    }

    let clearance = (contour_radius_m - inner_radius).min(outer_radius - contour_radius_m);
    if clearance > 1e-9 {
        // Stay strictly inside the polygon despite floating-point roundoff.
        (1.0 - 1e-6) * clearance
    } else {
        1e-4
    }
}

fn sample_contour_field_from_az(
    records: &[AirgapTriangleRecord],
    az: &[f64],
    point_xy_m: [f64; 2],
    dtheta: f64,
    radial_step_m: f64,
) -> Option<(usize, f64, f64)> {
    let radius = (point_xy_m[0] * point_xy_m[0] + point_xy_m[1] * point_xy_m[1]).sqrt();
    if radius < 1e-12 {
        return None;
    }

    let theta = point_xy_m[1].atan2(point_xy_m[0]);
    let (center_record, _) = find_airgap_triangle_match(records, point_xy_m)?;
    let a_r_plus = sample_az_on_airgap(
        records,
        az,
        [
            (radius + radial_step_m) * theta.cos(),
            (radius + radial_step_m) * theta.sin(),
        ],
    )?;
    let a_r_minus = sample_az_on_airgap(
        records,
        az,
        [
            (radius - radial_step_m) * theta.cos(),
            (radius - radial_step_m) * theta.sin(),
        ],
    )?;
    let a_theta_plus = sample_az_on_airgap(
        records,
        az,
        [
            radius * (theta + dtheta).cos(),
            radius * (theta + dtheta).sin(),
        ],
    )?;
    let a_theta_minus = sample_az_on_airgap(
        records,
        az,
        [
            radius * (theta - dtheta).cos(),
            radius * (theta - dtheta).sin(),
        ],
    )?;

    let b_t = -(a_r_plus - a_r_minus) / (2.0 * radial_step_m);
    let b_r = (a_theta_plus - a_theta_minus) / (2.0 * dtheta * radius);
    Some((center_record.triangle_index, b_r, b_t))
}
fn full_coverage_airgap_radii(mesh: &TriMesh) -> Vec<f64> {
    let mut unique_airgap_radii = Vec::new();
    for (triangle_index, tri) in mesh.triangles.iter().enumerate() {
        if mesh.regions[triangle_index] != Region::Airgap {
            continue;
        }
        for node_index in tri {
            let [x, y] = mesh.nodes[*node_index];
            unique_airgap_radii.push((x * x + y * y).sqrt());
        }
    }
    unique_airgap_radii.sort_by(|a, b| a.partial_cmp(b).unwrap());
    unique_airgap_radii.dedup_by(|a, b| (*a - *b).abs() < 1e-9);

    if unique_airgap_radii.len() < 2 {
        return Vec::new();
    }

    let mut airgap_triangles = Vec::new();
    for (triangle_index, tri) in mesh.triangles.iter().enumerate() {
        if mesh.regions[triangle_index] != Region::Airgap {
            continue;
        }
        let [i, j, k] = *tri;
        let tri_xy = [mesh.nodes[i], mesh.nodes[j], mesh.nodes[k]];
        let xs = [tri_xy[0][0], tri_xy[1][0], tri_xy[2][0]];
        let ys = [tri_xy[0][1], tri_xy[1][1], tri_xy[2][1]];
        let xmin = xs.iter().copied().fold(f64::INFINITY, f64::min);
        let xmax = xs.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let ymin = ys.iter().copied().fold(f64::INFINITY, f64::min);
        let ymax = ys.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        airgap_triangles.push((tri_xy, [xmin, xmax, ymin, ymax]));
    }

    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let coverage_samples = 180usize;
    let mut working_radii = Vec::new();
    for window in unique_airgap_radii.windows(2) {
        let candidate_radius = 0.5 * (window[0] + window[1]);
        let mut covered = true;
        'sample_loop: for sample_index in 0..coverage_samples {
            let theta = total_span_rad * sample_index as f64 / coverage_samples as f64;
            let x = candidate_radius * theta.cos();
            let y = candidate_radius * theta.sin();
            let mut matched = false;
            for &(tri_xy, bbox) in &airgap_triangles {
                let pad = 1e-9;
                if x < bbox[0] - pad || x > bbox[1] + pad || y < bbox[2] - pad || y > bbox[3] + pad
                {
                    continue;
                }
                if barycentric_weights([x, y], tri_xy).is_none() {
                    continue;
                }
                matched = true;
                break;
            }
            if !matched {
                covered = false;
                break 'sample_loop;
            }
        }
        if covered {
            working_radii.push(candidate_radius);
        }
    }

    working_radii
}
fn airgap_mid_radius(mesh: &TriMesh) -> Option<f64> {
    if let Some(band) = mesh.info.airgap_band() {
        return Some(0.5 * (band.inner_radius_m() + band.outer_radius_m()));
    }

    let triangle_centroid_radius = |tri: &[usize; 3]| -> f64 {
        let [i, j, k] = *tri;
        let [x1, y1] = mesh.nodes[i];
        let [x2, y2] = mesh.nodes[j];
        let [x3, y3] = mesh.nodes[k];
        let cx = (x1 + x2 + x3) / 3.0;
        let cy = (y1 + y2 + y3) / 3.0;
        (cx * cx + cy * cy).sqrt()
    };

    let mut edge_to_triangle: std::collections::HashMap<(usize, usize), usize> =
        std::collections::HashMap::new();
    let mut inner_boundary_radius_max = 0.0_f64;
    let mut outer_boundary_radius_min = f64::INFINITY;

    for (triangle_index, tri) in mesh.triangles.iter().enumerate() {
        let edges = [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])];
        for (a, b) in edges {
            let edge = if a < b { (a, b) } else { (b, a) };
            if let Some(other_triangle_index) = edge_to_triangle.remove(&edge) {
                let region_a = mesh.regions[triangle_index];
                let region_b = mesh.regions[other_triangle_index];
                let one_airgap = region_a == Region::Airgap || region_b == Region::Airgap;
                let both_airgap = region_a == Region::Airgap && region_b == Region::Airgap;
                if !one_airgap || both_airgap {
                    continue;
                }

                let airgap_triangle_index = if region_a == Region::Airgap {
                    triangle_index
                } else {
                    other_triangle_index
                };
                let other_triangle_index = if airgap_triangle_index == triangle_index {
                    other_triangle_index
                } else {
                    triangle_index
                };

                let airgap_radius =
                    triangle_centroid_radius(&mesh.triangles[airgap_triangle_index]);
                let other_radius = triangle_centroid_radius(&mesh.triangles[other_triangle_index]);
                let [x1, y1] = mesh.nodes[edge.0];
                let [x2, y2] = mesh.nodes[edge.1];
                let edge_mid_radius =
                    (((x1 + x2) * 0.5).powi(2) + ((y1 + y2) * 0.5).powi(2)).sqrt();
                if other_radius < airgap_radius {
                    inner_boundary_radius_max = inner_boundary_radius_max.max(edge_mid_radius);
                } else {
                    outer_boundary_radius_min = outer_boundary_radius_min.min(edge_mid_radius);
                }
            } else {
                edge_to_triangle.insert(edge, triangle_index);
            }
        }
    }

    if outer_boundary_radius_min.is_finite()
        && outer_boundary_radius_min > inner_boundary_radius_max
    {
        return Some(0.5 * (inner_boundary_radius_max + outer_boundary_radius_min));
    }

    let working_radii = full_coverage_airgap_radii(mesh);
    if let (Some(first), Some(last)) = (working_radii.first(), working_radii.last()) {
        return Some(0.5 * (first + last));
    }

    let mut min_radius = f64::INFINITY;
    let mut max_radius = 0.0_f64;
    for (triangle_index, tri) in mesh.triangles.iter().enumerate() {
        if mesh.regions[triangle_index] != Region::Airgap {
            continue;
        }
        for node_index in tri {
            let [x, y] = mesh.nodes[*node_index];
            let radius = (x * x + y * y).sqrt();
            min_radius = min_radius.min(radius);
            max_radius = max_radius.max(radius);
        }
    }
    if min_radius.is_finite() && max_radius > min_radius {
        Some(0.5 * (min_radius + max_radius))
    } else {
        None
    }
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

fn triangle_gradients(nodes: &[[f64; 2]], i: usize, j: usize, m: usize) -> (f64, [[f64; 2]; 3]) {
    let [x1, y1] = nodes[i];
    let [x2, y2] = nodes[j];
    let [x3, y3] = nodes[m];

    let twice_area = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1);
    let area = twice_area.abs() / 2.0;

    if area < 1e-15 {
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
fn triangle_area(nodes: &[[f64; 2]], i: usize, j: usize, m: usize) -> f64 {
    let [x1, y1] = nodes[i];
    let [x2, y2] = nodes[j];
    let [x3, y3] = nodes[m];
    ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)).abs() / 2.0
}
