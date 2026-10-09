use serde::Serialize;
use std::collections::HashSet;
use std::f64::consts::PI;

use crate::assembly::triangle_gradients;
use crate::materials::MU_0;
use crate::mesh::{Region, TriMesh};
use crate::sparse::{pcg_solve, CooMatrix, CsrMatrix};

use super::{
    airgap_mid_radius, barycentric_weights, cartesian_to_polar_b, choose_az_contour_radial_step,
    collect_airgap_triangle_records, compute_filtered_nodal_b_field, compute_nodal_b_field,
    full_coverage_airgap_radii, project_field_to_polar, sample_contour_field_from_az,
    triangle_area, ElementField,
};

const ROBUST_CONTOUR_MAX_REL_SPREAD: f64 = 0.25;
const ROBUST_CONTOUR_MAX_ABS_SPREAD_NM: f64 = 2.0e-3;
const ROBUST_CONTOUR_REL_SPREAD_FLOOR_NM: f64 = 1.0e-3;

/// Per-element contribution used by the area-based airgap torque integral.
#[derive(Debug, Clone, Serialize)]
pub struct TorqueElementContribution {
    pub triangle_index: usize,
    pub centroid_x_mm: f64,
    pub centroid_y_mm: f64,
    pub radius_mm: f64,
    pub theta_mech_deg: f64,
    pub area_mm2: f64,
    pub b_r_t: f64,
    pub b_t_t: f64,
    pub modeled_contribution_nm: f64,
    pub scaled_contribution_nm: f64,
}

/// Structured debug payload for the area-based torque path.
#[derive(Debug, Clone, Serialize)]
pub struct TorqueDebug {
    pub airgap_element_count: usize,
    pub modeled_torque_nm: f64,
    pub scale_factor: f64,
    pub scaled_torque_nm: f64,
    pub airgap_elements: Vec<TorqueElementContribution>,
}

/// Per-sample contribution used by the mid-gap contour torque estimate.
#[derive(Debug, Clone, Serialize)]
pub struct ContourTorqueSample {
    pub sample_index: usize,
    pub triangle_index: usize,
    pub x_mm: f64,
    pub y_mm: f64,
    pub radius_mm: f64,
    pub theta_mech_deg: f64,
    pub b_r_t: f64,
    pub b_t_t: f64,
    pub modeled_contribution_nm: f64,
    pub scaled_contribution_nm: f64,
}

/// Per-quadrant bucketing of MST contour samples, emitted only for full-circle
/// runs. Used by the integrator-symmetry regression gate: a 4-fold
/// symmetric field integrated by a 4-fold symmetric sampling scheme should
/// give identical per-quadrant partial torques. If the partial torques drift
/// across quadrants, the integrator is injecting spurious k=2/k=4 content into
/// the cogging spectrum.
#[derive(Debug, Clone, Serialize)]
pub struct PerQuadrantContourStats {
    pub full_circle: bool,
    /// Number of samples whose mechanical angle lands in each 90° quadrant,
    /// indexed 0..3 counter-clockwise starting at θ ∈ [0, π/2).
    pub sample_count_per_quadrant: [usize; 4],
    /// First sample angle that landed in each quadrant, in degrees (mod 90°).
    /// Under 4-fold symmetry these should be identical across quadrants.
    pub first_sample_theta_mod90_deg_per_quadrant: [Option<f64>; 4],
    /// Sum of modeled torque contributions per quadrant (pre-scale_factor).
    pub partial_torque_nm_per_quadrant: [f64; 4],
    /// Worst-case |a-b| between any two quadrant counts.
    pub max_abs_diff_count: usize,
    /// Worst-case |a-b| / mean partial torque across quadrants.
    pub max_rel_diff_partial_torque: f64,
    /// Worst-case |a-b| modulo 90° between any two quadrants' first-sample
    /// angles, in radians. Should be 0 for a 4-fold-symmetric angular grid.
    pub max_abs_diff_first_sample_rad: f64,
}

/// Structured debug payload for the mid-gap contour torque path.
#[derive(Debug, Clone, Serialize)]
pub struct ContourTorqueDebug {
    pub status: String,
    pub error: Option<String>,
    pub radius_mm: f64,
    pub sample_count: usize,
    pub total_span_deg: f64,
    pub unique_triangle_count: usize,
    pub modeled_torque_nm: f64,
    pub scale_factor: f64,
    pub scaled_torque_nm: f64,
    pub samples: Vec<ContourTorqueSample>,
    /// Per-quadrant diagnostic bucketing (full-circle runs only).
    pub per_quadrant: Option<PerQuadrantContourStats>,
}

/// One member of the robust contour torque ensemble.
#[derive(Debug, Clone, Serialize)]
pub struct RobustContourTorqueCase {
    pub source: String,
    pub radius_mm: f64,
    pub offset_fraction: f64,
    pub sample_count: usize,
    pub status: String,
    pub error: Option<String>,
    pub torque_nm: f64,
    pub unique_triangle_count: usize,
}

/// Stability summary for all robust contour members from one field source.
#[derive(Debug, Clone, Serialize)]
pub struct RobustContourTorqueSourceStats {
    pub source: String,
    pub status: String,
    pub case_count: usize,
    pub ok_count: usize,
    pub selected_torque_nm: f64,
    pub mean_torque_nm: f64,
    pub min_torque_nm: f64,
    pub max_torque_nm: f64,
    pub spread_abs_nm: f64,
    pub spread_rel: Option<f64>,
}

/// Multi-radius, multi-offset contour torque diagnostic.
#[derive(Debug, Clone, Serialize)]
pub struct RobustContourTorqueDebug {
    pub status: String,
    pub error: Option<String>,
    pub selected_source: String,
    pub selected_torque_nm: f64,
    pub selected_reason: String,
    pub sample_count: usize,
    pub radius_count: usize,
    pub offset_count: usize,
    pub offsets: Vec<f64>,
    pub radii_mm: Vec<f64>,
    pub source_stats: Vec<RobustContourTorqueSourceStats>,
    pub cases: Vec<RobustContourTorqueCase>,
}

/// FEMM-like weighted-stress-tensor torque diagnostic.
///
/// FEMM's block integral 22 avoids choosing a single airgap contour. It solves
/// a scalar weighting function in the surrounding air and integrates the
/// Maxwell stress tensor against that virtual displacement field. This payload
/// records enough of the native version to compare it with FEMM before making
/// it the default torque path.
#[derive(Debug, Clone, Serialize)]
pub struct WeightedStressTorqueDebug {
    pub status: String,
    pub error: Option<String>,
    pub domain_regions: Vec<String>,
    pub airgap_element_count: usize,
    pub airgap_node_count: usize,
    pub boundary_inner_node_count: usize,
    pub boundary_outer_node_count: usize,
    pub airgap_r_inner_mm: f64,
    pub airgap_r_outer_mm: f64,
    pub weight_min: f64,
    pub weight_max: f64,
    pub modeled_torque_nm: f64,
    pub airgap_contribution_nm: f64,
    pub slot_winding_contribution_nm: f64,
    pub scale_factor: f64,
    pub scaled_torque_nm: f64,
    pub field_source: String,
    pub field_fallback_count: usize,
    pub boundary_wedge_sample_count: usize,
    pub boundary_wedge_sample_fallback_count: usize,
    pub boundary_wedge_taper_count: usize,
    pub boundary_wedge_taper_factor: f64,
    pub boundary_wedge_taper_removed_nm: f64,
    pub boundary_wedge_taper_applied: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub boundary_wedge_taper_gate_reason: Option<String>,
    // B2 (field-aware boundary classifier) instrumentation. Tracks how many
    // triangles match the topological "boundary wedge" set vs how many
    // additionally satisfy the contamination |B|^2 gradient threshold and
    // therefore actually get the taper applied. When field_gate is disabled
    // (default), topology_count == taper_count, preserving prior semantics.
    pub boundary_wedge_taper_topology_count: usize,
    pub boundary_wedge_taper_field_gate_enabled: bool,
    pub boundary_wedge_taper_field_threshold: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub contribution_localization: Option<WeightedStressContributionLocalization>,
}

/// Compact WST contribution breakdown for localizing parity errors without
/// exporting every element in normal solve reports.
#[derive(Debug, Clone, Serialize)]
pub struct WeightedStressContributionLocalization {
    pub field_source: String,
    pub total_abs_torque_nm: f64,
    pub positive_torque_nm: f64,
    pub negative_torque_nm: f64,
    pub radial_bins: Vec<WeightedStressContributionBin>,
    pub angular_bins: Vec<WeightedStressContributionBin>,
    pub interface_bins: Vec<WeightedStressContributionBin>,
    pub top_abs_contributors: Vec<WeightedStressContributionHotspot>,
}

#[derive(Debug, Clone, Serialize)]
pub struct WeightedStressContributionBin {
    pub label: String,
    pub element_count: usize,
    pub torque_nm: f64,
    pub abs_torque_nm: f64,
    pub positive_torque_nm: f64,
    pub negative_torque_nm: f64,
    pub max_abs_contribution_nm: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct WeightedStressContributionHotspot {
    pub triangle_index: usize,
    pub region: String,
    pub interface_class: String,
    pub centroid_x_mm: f64,
    pub centroid_y_mm: f64,
    pub radius_mm: f64,
    pub theta_mech_deg: f64,
    pub radial_fraction: f64,
    pub contribution_nm: f64,
    pub abs_contribution_nm: f64,
    pub b_r_t: f64,
    pub b_t_t: f64,
    pub weight_centroid: f64,
    pub grad_w_mag_per_m: f64,
}

mod env_flags;
mod localization;

use self::env_flags::{
    weighted_stress_airgap_only, weighted_stress_boundary_aware_b,
    weighted_stress_boundary_wedge_field_gate_enabled,
    weighted_stress_boundary_wedge_field_threshold,
    weighted_stress_boundary_wedge_fraction_threshold,
    weighted_stress_boundary_wedge_sample_fraction, weighted_stress_boundary_wedge_sampling,
    weighted_stress_boundary_wedge_taper, weighted_stress_boundary_wedge_taper_factor,
    weighted_stress_boundary_wedge_taper_outer_bulk, weighted_stress_domain,
    weighted_stress_excluded_boundary_side, weighted_stress_localization_enabled,
    weighted_stress_physical_bounds, weighted_stress_stator_boundary_layer,
    weighted_stress_triangle_in_domain, weighted_stress_use_az_field, weighted_stress_use_nodal_b,
};
use self::localization::{weighted_stress_interface_class, WeightedStressContributionAccumulator};

struct AirgapTriangleRecord {
    triangle_index: usize,
    tri_nodes: [usize; 3],
    tri_xy: [[f64; 2]; 3],
    bbox: [f64; 4],
}

struct AirgapTriangleLookup {
    records: Vec<AirgapTriangleRecord>,
    buckets: Vec<Vec<usize>>,
    xmin: f64,
    ymin: f64,
    cell_w: f64,
    cell_h: f64,
    nx: usize,
    ny: usize,
}

impl AirgapTriangleLookup {
    fn new(mesh: &TriMesh) -> Self {
        let records = collect_nodal_contour_airgap_records(mesh);
        let mut xmin = f64::INFINITY;
        let mut xmax = f64::NEG_INFINITY;
        let mut ymin = f64::INFINITY;
        let mut ymax = f64::NEG_INFINITY;
        for record in &records {
            xmin = xmin.min(record.bbox[0]);
            xmax = xmax.max(record.bbox[1]);
            ymin = ymin.min(record.bbox[2]);
            ymax = ymax.max(record.bbox[3]);
        }
        if records.is_empty() || !xmin.is_finite() || xmax <= xmin || ymax <= ymin {
            return Self {
                records,
                buckets: vec![Vec::new()],
                xmin: 0.0,
                ymin: 0.0,
                cell_w: 1.0,
                cell_h: 1.0,
                nx: 1,
                ny: 1,
            };
        }

        let pad = ((xmax - xmin).max(ymax - ymin) * 1.0e-9).max(1.0e-9);
        xmin -= pad;
        xmax += pad;
        ymin -= pad;
        ymax += pad;
        let nx = 128_usize;
        let ny = 128_usize;
        let cell_w = (xmax - xmin) / nx as f64;
        let cell_h = (ymax - ymin) / ny as f64;
        let mut buckets = vec![Vec::new(); nx * ny];
        for (record_idx, record) in records.iter().enumerate() {
            let ix0 = (((record.bbox[0] - xmin) / cell_w).floor() as isize)
                .clamp(0, nx as isize - 1) as usize;
            let ix1 = (((record.bbox[1] - xmin) / cell_w).floor() as isize)
                .clamp(0, nx as isize - 1) as usize;
            let iy0 = (((record.bbox[2] - ymin) / cell_h).floor() as isize)
                .clamp(0, ny as isize - 1) as usize;
            let iy1 = (((record.bbox[3] - ymin) / cell_h).floor() as isize)
                .clamp(0, ny as isize - 1) as usize;
            for iy in iy0..=iy1 {
                for ix in ix0..=ix1 {
                    buckets[iy * nx + ix].push(record_idx);
                }
            }
        }

        Self {
            records,
            buckets,
            xmin,
            ymin,
            cell_w,
            cell_h,
            nx,
            ny,
        }
    }

    fn cell(&self, point_xy_m: [f64; 2]) -> Option<(usize, usize)> {
        if self.records.is_empty() {
            return None;
        }
        let ix = ((point_xy_m[0] - self.xmin) / self.cell_w).floor() as isize;
        let iy = ((point_xy_m[1] - self.ymin) / self.cell_h).floor() as isize;
        if ix < 0 || iy < 0 || ix >= self.nx as isize || iy >= self.ny as isize {
            return None;
        }
        Some((ix as usize, iy as usize))
    }

    fn find(&self, point_xy_m: [f64; 2]) -> Option<(&AirgapTriangleRecord, [f64; 3])> {
        let (ix, iy) = self.cell(point_xy_m)?;
        let pad = 1.0e-9;
        for dy in -1_isize..=1 {
            for dx in -1_isize..=1 {
                let nx = ix as isize + dx;
                let ny = iy as isize + dy;
                if nx < 0 || ny < 0 || nx >= self.nx as isize || ny >= self.ny as isize {
                    continue;
                }
                for &record_idx in &self.buckets[ny as usize * self.nx + nx as usize] {
                    let record = &self.records[record_idx];
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
            }
        }
        None
    }

    fn sample_az(&self, az: &[f64], point_xy_m: [f64; 2]) -> Option<f64> {
        let (record, weights) = self.find(point_xy_m)?;
        Some(
            weights[0] * az[record.tri_nodes[0]]
                + weights[1] * az[record.tri_nodes[1]]
                + weights[2] * az[record.tri_nodes[2]],
        )
    }

    fn sample_b_from_az(
        &self,
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
        let (center_record, _) = self.find(point_xy_m)?;
        let a_r_plus = self.sample_az(
            az,
            [
                (radius + radial_step_m) * theta.cos(),
                (radius + radial_step_m) * theta.sin(),
            ],
        )?;
        let a_r_minus = self.sample_az(
            az,
            [
                (radius - radial_step_m) * theta.cos(),
                (radius - radial_step_m) * theta.sin(),
            ],
        )?;
        let a_theta_plus = self.sample_az(
            az,
            [
                radius * (theta + dtheta).cos(),
                radius * (theta + dtheta).sin(),
            ],
        )?;
        let a_theta_minus = self.sample_az(
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
}

/// Per-quadrant bucketing of Arkkio airgap triangles, emitted only for full-
/// circle runs. Used by the integrator-symmetry regression gate: on a
/// geometry with 4-fold rotor symmetry and a 4-fold symmetric mesh, each of
/// the four 90° quadrants should see identical triangle counts, area sums,
/// and partial torque integrals. Any drift is evidence that the triangle-
/// selection filter `r_inner_filtered ≤ r ≤ r_outer_filtered` is picking up
/// rounding jitter on borderline triangles and breaking the symmetry of the
/// integrator's sample set.
#[derive(Debug, Clone, Serialize)]
pub struct PerQuadrantArkkioStats {
    pub full_circle: bool,
    /// Number of airgap triangles whose centroid angle lands in each 90°
    /// quadrant, indexed 0..3 counter-clockwise starting at θ ∈ [0, π/2).
    pub triangle_count_per_quadrant: [usize; 4],
    /// Sum of triangle areas per quadrant (m²).
    pub area_m2_per_quadrant: [f64; 4],
    /// Sum of r·B_r·B_t·area per quadrant (pre μ₀/stack/band scaling).
    pub partial_integrand_per_quadrant: [f64; 4],
    /// Worst-case |a-b| between any two quadrant counts.
    pub max_abs_diff_count: usize,
    /// Worst-case |a-b| / mean area across quadrants.
    pub max_rel_diff_area: f64,
    /// Worst-case |a-b| / mean partial integrand across quadrants.
    pub max_rel_diff_partial_integrand: f64,
}

/// Structured debug payload for Arkkio's volume-averaged MST torque.
#[derive(Debug, Clone, Serialize)]
pub struct ArkkioTorqueDebug {
    pub status: String,
    pub error: Option<String>,
    pub airgap_element_count: usize,
    pub airgap_r_inner_mm: f64,
    pub airgap_r_outer_mm: f64,
    pub modeled_torque_nm: f64,
    pub scale_factor: f64,
    pub scaled_torque_nm: f64,
    /// Per-quadrant diagnostic bucketing (full-circle runs only).
    pub per_quadrant: Option<PerQuadrantArkkioStats>,
}
/// Compute torque using Maxwell Stress Tensor on a contour in the airgap.
///
/// Scale from modeled sector (n_pole_pitches) to full motor (pole_count pitches).
#[allow(dead_code)]
pub fn compute_torque(
    mesh: &TriMesh,
    fields: &[ElementField],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
) -> f64 {
    compute_torque_debug(mesh, fields, centroids, stack_length_mm, pole_count).scaled_torque_nm
}

/// Detect whether the mesh models the full 2π (full-circle) span. The
/// integrator-symmetry instrumentation only makes sense on full-circle runs;
/// sectored meshes need a different (sub-sector) symmetry definition.
fn is_full_circle(mesh: &TriMesh) -> bool {
    (mesh.info.total_span_deg.abs() - 360.0).abs() < 1e-6
}

fn contour_sample_count(mesh: &TriMesh) -> usize {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let span_fraction = (total_span_rad / (2.0 * PI)).abs();
    let default_count = ((720.0 * span_fraction).round() as usize).max(180);
    for name in [
        "COILEM_MAGNETO2D_CONTOUR_SAMPLES",
        "MAGNETO2D_CONTOUR_SAMPLES",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let Ok(requested) = raw.trim().parse::<usize>() else {
            continue;
        };
        if requested > 0 {
            return requested.max(16);
        }
    }
    default_count
}

fn robust_contour_sample_count(mesh: &TriMesh) -> usize {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let span_fraction = (total_span_rad / (2.0 * PI)).abs();
    let default_count = ((720.0 * span_fraction).round() as usize).max(180);
    for name in [
        "COILEM_MAGNETO2D_ROBUST_CONTOUR_SAMPLES",
        "MAGNETO2D_ROBUST_CONTOUR_SAMPLES",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let Ok(requested) = raw.trim().parse::<usize>() else {
            continue;
        };
        if requested > 0 {
            return requested.max(16);
        }
    }
    default_count
}

fn contour_sample_offset_fraction() -> f64 {
    for name in [
        "COILEM_MAGNETO2D_CONTOUR_SAMPLE_OFFSET",
        "MAGNETO2D_CONTOUR_SAMPLE_OFFSET",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let Ok(offset) = raw.trim().parse::<f64>() else {
            continue;
        };
        if offset.is_finite() {
            return offset.rem_euclid(1.0);
        }
    }
    0.0
}

/// Return the 90° quadrant index (0..3) for a mechanical angle, measured
/// counter-clockwise from +X. Quadrant 0 covers θ ∈ [0, π/2), quadrant 1
/// [π/2, π), etc.
#[inline]
fn quadrant_of_angle(theta_rad: f64) -> usize {
    let two_pi = 2.0 * PI;
    let mut t = theta_rad % two_pi;
    if t < 0.0 {
        t += two_pi;
    }
    let q = (t / (PI / 2.0)).floor() as isize;
    ((q.rem_euclid(4)) as usize).min(3)
}

/// Reduce an angle to [0, π/2), the natural "fundamental quadrant" for a
/// 4-fold symmetry test. Used to check that samples landing in different
/// quadrants are at the same angle mod 90°.
#[inline]
fn angle_mod_quadrant(theta_rad: f64) -> f64 {
    let q = PI / 2.0;
    let mut t = theta_rad % q;
    if t < 0.0 {
        t += q;
    }
    t
}

/// Check whether any environment variable in {`MAGNETO2D_ASSERT_SYMMETRY`,
/// `COILEM_MAGNETO2D_ASSERT_SYMMETRY`} is set to a truthy value. Cheap enough
/// to poll once per integrator call.
fn assert_symmetry_enabled() -> bool {
    for name in [
        "MAGNETO2D_ASSERT_SYMMETRY",
        "COILEM_MAGNETO2D_ASSERT_SYMMETRY",
    ] {
        match std::env::var(name) {
            Ok(v) => {
                let v = v.trim().to_ascii_lowercase();
                if !v.is_empty() && v != "0" && v != "false" && v != "no" && v != "off" {
                    return true;
                }
            }
            Err(_) => continue,
        }
    }
    false
}

/// Safe relative-diff over a 4-element bucket; returns 0 when the mean is
/// numerically zero to avoid NaN pollution on the zero-field edge case.
#[inline]
fn max_rel_diff4(values: [f64; 4]) -> f64 {
    let mut vmin = f64::INFINITY;
    let mut vmax = f64::NEG_INFINITY;
    for v in values {
        if v < vmin {
            vmin = v;
        }
        if v > vmax {
            vmax = v;
        }
    }
    let spread = vmax - vmin;
    let mean = (values[0] + values[1] + values[2] + values[3]) / 4.0;
    let denom = mean.abs().max(1e-30);
    spread / denom
}

#[inline]
fn max_abs_diff4_usize(values: [usize; 4]) -> usize {
    let vmin = *values.iter().min().unwrap();
    let vmax = *values.iter().max().unwrap();
    vmax - vmin
}

/// Compute torque using Arkkio's volume-averaged Maxwell Stress Tensor method.
///
/// Instead of integrating B_r·B_t on a single contour, this averages the stress
/// over the entire airgap cross-section (all airgap elements), weighted by radius.
/// This is far more robust against mesh irregularities than contour-based MST.
///
/// Formula (2D, per unit axial length):
///   T = (L / μ₀) · 1/(r_out - r_in) · Σ_elem [ r_c · B_r · B_t · A_elem ]
///
/// where r_c is the element centroid radius, A_elem is the element area,
/// and (r_out - r_in) is the radial extent of the airgap.
///
/// Reference: Arkkio, A. (1987), "Analysis of induction motors based on the
/// numerical solution of the magnetic field and circuit equations", Acta
/// Polytechnica Scandinavica.
#[allow(dead_code)]
pub fn compute_torque_arkkio(
    mesh: &TriMesh,
    fields: &[ElementField],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
) -> f64 {
    compute_torque_arkkio_debug(mesh, fields, centroids, stack_length_mm, pole_count)
        .scaled_torque_nm
}

/// Compute Arkkio torque with full debug payload.
///
/// Applies boundary margin filtering: airgap elements within the outermost
/// 10% of the radial band on each side are excluded. These boundary elements
/// carry B-field values contaminated by adjacent iron (stator teeth / magnet),
/// which causes massive cancellation errors in the area-based integral.
pub fn compute_torque_arkkio_debug(
    mesh: &TriMesh,
    fields: &[ElementField],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
) -> ArkkioTorqueDebug {
    let l_stack = stack_length_mm * 1e-3;
    let n_pole_pitches = mesh.info.n_pole_pitches;
    let scale_factor = pole_count as f64 / n_pole_pitches as f64;

    // First pass: find the radial extent of the airgap from element centroids.
    let mut r_min = f64::INFINITY;
    let mut r_max: f64 = 0.0;
    let mut airgap_count: usize = 0;

    for (idx, _) in mesh.triangles.iter().enumerate() {
        if mesh.regions[idx] != Region::Airgap {
            continue;
        }
        let cx = centroids[idx][0];
        let cy = centroids[idx][1];
        let r = (cx * cx + cy * cy).sqrt();
        r_min = r_min.min(r);
        r_max = r_max.max(r);
        airgap_count += 1;
    }

    if airgap_count == 0 || (r_max - r_min).abs() < 1e-12 {
        return ArkkioTorqueDebug {
            status: "error".to_string(),
            error: Some(format!(
                "cannot compute Arkkio torque: {} airgap elements, r_range={:.6}mm",
                airgap_count,
                (r_max - r_min) * 1e3,
            )),
            airgap_element_count: airgap_count,
            airgap_r_inner_mm: r_min * 1e3,
            airgap_r_outer_mm: r_max * 1e3,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            per_quadrant: None,
        };
    }

    // Prefer the physical airgap band resolved from mesh metadata: from the
    // actual rotor-side airgap boundary to the stator bore. This avoids the
    // prior bug where `Region::Airgap`-
    // tagged elements extended into the rotor magnet volume and contaminated
    // the volume-averaged stress integral with contributions from inside
    // magnetized material, where `r·B_r·B_t/μ₀` is not the real stress.
    //
    // Fall back to the auto-detected band (r_min..r_max with 10% margin) when
    // the mesh info doesn't carry the physical radii (e.g. synthetic tests).
    let airgap_band = mesh.info.airgap_band();
    let (r_inner_filtered, r_outer_filtered, band_source) = if let Some(airgap_band) = airgap_band {
        let inner_m = airgap_band.inner_radius_m();
        let bore_m = airgap_band.outer_radius_m();
        let gap_m = bore_m - inner_m;
        // Trim 25% off each end: tightening the band from 10%
        // to 25% localizes the slot-harmonic over-cogging bug — if k=6
        // drops proportionally, it's mesh mis-tagging near the boundary;
        // if it barely moves, it's mesh resolution at the slot openings.
        let margin = 0.25 * gap_m;
        (inner_m + margin, bore_m - margin, "physical")
    } else {
        let dr_full = r_max - r_min;
        let margin = 0.10 * dr_full;
        (r_min + margin, r_max - margin, "auto")
    };
    let dr = r_outer_filtered - r_inner_filtered;

    if dr < 1e-12 {
        // Airgap too thin for filtering — fall back to unfiltered.
        return compute_torque_arkkio_debug_unfiltered(
            mesh,
            fields,
            centroids,
            stack_length_mm,
            pole_count,
        );
    }

    // Build the nodal B used by the stress integrand from AIRGAP ELEMENTS
    // ONLY. The unfiltered all-region average smears stator-tooth
    // / rotor-iron / magnet element fields into nodes on the airgap
    // interfaces; on thin, few-layer unstructured (gmsh) airgaps the trimmed
    // band's triangles still touch those interface nodes, and the
    // contaminated B_r·B_t inflated Arkkio 1.5-3.2x vs contour/WST on the
    // Phase C distributed fixtures (see
    // docs/analysis/native_torque_method_reconciliation_20260703.md).
    // Region-filtering preserves the material-boundary discontinuity exactly
    // like WST's boundary-aware option; on structured meshes whose band
    // interior never touches interface nodes this is bit-identical to the
    // previous unfiltered reconstruction.
    let nodal_b = compute_filtered_nodal_b_field(mesh, fields, |region| region == Region::Airgap);

    // Diagnostic (environment-gated): record the legacy (unfiltered
    // nodal-B) and element-B variants plus the selected-area vs
    // annulus-band-area ratio, for band-policy forensics.
    let arkkio_diag = std::env::var("COILEM_MAGNETO2D_ARKKIO_DIAG")
        .map(|v| {
            let v = v.trim().to_ascii_lowercase();
            !v.is_empty() && v != "0" && v != "false"
        })
        .unwrap_or(false);
    let nodal_b_unfiltered = if arkkio_diag {
        Some(compute_nodal_b_field(mesh, fields))
    } else {
        None
    };
    let mut diag_area_sum_m2 = 0.0_f64;
    let mut diag_integral_element_b = 0.0_f64;
    let mut diag_integral_unfiltered_nodal_b = 0.0_f64;

    // Second pass: accumulate the volume-weighted stress integral
    // using only interior airgap elements.
    let mut torque_integral = 0.0_f64;
    let mut filtered_count: usize = 0;

    // Symmetry instrumentation: bucket the per-triangle Arkkio integrand
    // by 90° centroid-angle quadrant. On a 4-fold-symmetric field + mesh,
    // each quadrant should accumulate the same count, area sum, and partial
    // torque integral. Drift across quadrants means the triangle-selection
    // filter is picking up rounding jitter on borderline triangles and
    // injecting spurious k=2/k=4 content into the torque spectrum.
    let full_circle = is_full_circle(mesh);
    let mut q_count: [usize; 4] = [0; 4];
    let mut q_area_m2: [f64; 4] = [0.0; 4];
    let mut q_partial: [f64; 4] = [0.0; 4];

    for (idx, tri) in mesh.triangles.iter().enumerate() {
        if mesh.regions[idx] != Region::Airgap {
            continue;
        }

        let cx = centroids[idx][0];
        let cy = centroids[idx][1];
        let r = (cx * cx + cy * cy).sqrt();
        if r < 1e-12 {
            continue;
        }

        // Skip boundary elements.
        if r < r_inner_filtered || r > r_outer_filtered {
            continue;
        }

        // Barycentric weights at the centroid are (1/3, 1/3, 1/3),
        // so the nodal-averaged B at the centroid is the mean of its
        // three node values. This removes element-to-element jitter in
        // the element-constant B field.
        let [i, j, m] = *tri;
        let nb_i = nodal_b[i];
        let nb_j = nodal_b[j];
        let nb_m = nodal_b[m];
        let bx = (nb_i[0] + nb_j[0] + nb_m[0]) / 3.0;
        let by = (nb_i[1] + nb_j[1] + nb_m[1]) / 3.0;
        let Some((b_r, b_t)) = cartesian_to_polar_b(bx, by, [cx, cy]) else {
            continue;
        };

        let area = triangle_area(&mesh.nodes, i, j, m);

        // Arkkio weighting: r * B_r * B_t * area
        let partial = r * b_r * b_t * area;
        torque_integral += partial;
        filtered_count += 1;

        if arkkio_diag {
            diag_area_sum_m2 += area;
            if let Some((eb_r, eb_t)) =
                cartesian_to_polar_b(fields[idx].bx, fields[idx].by, [cx, cy])
            {
                diag_integral_element_b += r * eb_r * eb_t * area;
            }
            if let Some(unfiltered) = &nodal_b_unfiltered {
                let ub_i = unfiltered[i];
                let ub_j = unfiltered[j];
                let ub_m = unfiltered[m];
                let ubx = (ub_i[0] + ub_j[0] + ub_m[0]) / 3.0;
                let uby = (ub_i[1] + ub_j[1] + ub_m[1]) / 3.0;
                if let Some((ub_r, ub_t)) = cartesian_to_polar_b(ubx, uby, [cx, cy]) {
                    diag_integral_unfiltered_nodal_b += r * ub_r * ub_t * area;
                }
            }
        }

        if full_circle {
            let q = quadrant_of_angle(cy.atan2(cx));
            q_count[q] += 1;
            q_area_m2[q] += area;
            q_partial[q] += partial;
        }
    }

    let modeled_torque = (l_stack / MU_0) * torque_integral / dr;

    if arkkio_diag {
        let span_rad = mesh.info.total_span_deg.to_radians().abs();
        let r_mean = 0.5 * (r_inner_filtered + r_outer_filtered);
        let annulus_band_area_m2 = span_rad * r_mean * dr;
        let area_ratio = if annulus_band_area_m2 > 0.0 {
            diag_area_sum_m2 / annulus_band_area_m2
        } else {
            f64::NAN
        };
        let t_filtered = (l_stack / MU_0) * torque_integral / dr * scale_factor;
        let t_element_b = (l_stack / MU_0) * diag_integral_element_b / dr * scale_factor;
        let t_unfiltered = (l_stack / MU_0) * diag_integral_unfiltered_nodal_b / dr * scale_factor;
        let t_filtered_area_norm = if diag_area_sum_m2 > 0.0 {
            (l_stack / MU_0) * torque_integral * span_rad * r_mean / diag_area_sum_m2 * scale_factor
        } else {
            f64::NAN
        };
        let diag_line = format!(
            "arkkio_diag: area_sum={:.6e}m2 band_area={:.6e}m2 area_ratio={:.4} | scaled: filtered_nodal_b(default)={:.4} filtered_area_norm={:.4} element_b={:.4} legacy_unfiltered_nodal_b={:.4}",
            diag_area_sum_m2,
            annulus_band_area_m2,
            area_ratio,
            t_filtered,
            t_filtered_area_norm,
            t_element_b,
            t_unfiltered,
        );
        eprintln!("  {diag_line}");
        if let Ok(path) = std::env::var("COILEM_MAGNETO2D_ARKKIO_DIAG_FILE") {
            if !path.trim().is_empty() {
                use std::io::Write;
                if let Ok(mut file) = std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path.trim())
                {
                    let _ = writeln!(file, "{diag_line}");
                }
            }
        }
    }

    eprintln!(
        "  arkkio[{}]: r_band=[{:.3},{:.3}]mm dr={:.3}mm elems={} modeled={:.4}Nm scale={:.4} scaled={:.4}Nm",
        band_source,
        r_inner_filtered * 1e3,
        r_outer_filtered * 1e3,
        dr * 1e3,
        filtered_count,
        modeled_torque,
        scale_factor,
        modeled_torque * scale_factor,
    );

    let per_quadrant = if full_circle {
        let stats = PerQuadrantArkkioStats {
            full_circle,
            triangle_count_per_quadrant: q_count,
            area_m2_per_quadrant: q_area_m2,
            partial_integrand_per_quadrant: q_partial,
            max_abs_diff_count: max_abs_diff4_usize(q_count),
            max_rel_diff_area: max_rel_diff4(q_area_m2),
            max_rel_diff_partial_integrand: max_rel_diff4(q_partial),
        };
        eprintln!(
            "    arkkio per-quadrant: counts={:?} max_abs_diff_count={} max_rel_diff_area={:.3e} max_rel_diff_partial={:.3e}",
            stats.triangle_count_per_quadrant,
            stats.max_abs_diff_count,
            stats.max_rel_diff_area,
            stats.max_rel_diff_partial_integrand,
        );
        if assert_symmetry_enabled() {
            // Integrator-symmetry acceptance thresholds:
            // counts must match exactly, areas to 1e-9 rel, partial torque
            // integrand to 1e-6 rel. Geometric asymmetry must be zero before
            // we chase fix-A vs fix-B vs fix-C in Phase 2.
            assert!(
                stats.max_abs_diff_count == 0,
                "arkkio symmetry assert: triangle counts differ across quadrants: {:?}",
                stats.triangle_count_per_quadrant,
            );
            assert!(
                stats.max_rel_diff_area <= 1e-9,
                "arkkio symmetry assert: per-quadrant area rel-diff {:.3e} > 1e-9 (areas={:?})",
                stats.max_rel_diff_area,
                stats.area_m2_per_quadrant,
            );
            assert!(
                stats.max_rel_diff_partial_integrand <= 1e-6,
                "arkkio symmetry assert: per-quadrant partial-torque rel-diff {:.3e} > 1e-6 (partials={:?})",
                stats.max_rel_diff_partial_integrand,
                stats.partial_integrand_per_quadrant,
            );
        }
        Some(stats)
    } else {
        None
    };

    ArkkioTorqueDebug {
        status: "ok".to_string(),
        error: None,
        airgap_element_count: filtered_count,
        airgap_r_inner_mm: r_inner_filtered * 1e3,
        airgap_r_outer_mm: r_outer_filtered * 1e3,
        modeled_torque_nm: modeled_torque,
        scale_factor,
        scaled_torque_nm: modeled_torque * scale_factor,
        per_quadrant,
    }
}

/// Unfiltered Arkkio torque (fallback when airgap is too thin for margin).
fn compute_torque_arkkio_debug_unfiltered(
    mesh: &TriMesh,
    fields: &[ElementField],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
) -> ArkkioTorqueDebug {
    let l_stack = stack_length_mm * 1e-3;
    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches as f64;

    let mut r_min = f64::INFINITY;
    let mut r_max: f64 = 0.0;
    let mut torque_integral = 0.0_f64;
    let mut airgap_count: usize = 0;

    for (idx, tri) in mesh.triangles.iter().enumerate() {
        if mesh.regions[idx] != Region::Airgap {
            continue;
        }
        let cx = centroids[idx][0];
        let cy = centroids[idx][1];
        let r = (cx * cx + cy * cy).sqrt();
        if r < 1e-12 {
            continue;
        }
        r_min = r_min.min(r);
        r_max = r_max.max(r);
        airgap_count += 1;

        let Some((b_r, b_t)) = project_field_to_polar(&fields[idx], [cx, cy]) else {
            continue;
        };
        let [i, j, m] = *tri;
        let area = triangle_area(&mesh.nodes, i, j, m);
        torque_integral += r * b_r * b_t * area;
    }

    let dr = r_max - r_min;
    let modeled_torque = if dr.abs() > 1e-12 {
        (l_stack / MU_0) * torque_integral / dr
    } else {
        0.0
    };

    ArkkioTorqueDebug {
        status: "ok_unfiltered".to_string(),
        error: None,
        airgap_element_count: airgap_count,
        airgap_r_inner_mm: r_min * 1e3,
        airgap_r_outer_mm: r_max * 1e3,
        modeled_torque_nm: modeled_torque,
        scale_factor,
        scaled_torque_nm: modeled_torque * scale_factor,
        // The unfiltered path is only hit on degenerate/synthetic meshes;
        // per-quadrant symmetry instrumentation is not populated here.
        per_quadrant: None,
    }
}

fn weighted_stress_error(
    message: impl Into<String>,
    scale_factor: f64,
    airgap_element_count: usize,
    airgap_node_count: usize,
) -> WeightedStressTorqueDebug {
    WeightedStressTorqueDebug {
        status: "error".to_string(),
        error: Some(message.into()),
        domain_regions: vec!["Airgap".to_string()],
        airgap_element_count,
        airgap_node_count,
        boundary_inner_node_count: 0,
        boundary_outer_node_count: 0,
        airgap_r_inner_mm: 0.0,
        airgap_r_outer_mm: 0.0,
        weight_min: 0.0,
        weight_max: 0.0,
        modeled_torque_nm: 0.0,
        airgap_contribution_nm: 0.0,
        slot_winding_contribution_nm: 0.0,
        scale_factor,
        scaled_torque_nm: 0.0,
        field_source: "nodal_b_centroid".to_string(),
        field_fallback_count: 0,
        boundary_wedge_sample_count: 0,
        boundary_wedge_sample_fallback_count: 0,
        boundary_wedge_taper_count: 0,
        boundary_wedge_taper_factor: 1.0,
        boundary_wedge_taper_removed_nm: 0.0,
        boundary_wedge_taper_applied: false,
        boundary_wedge_taper_gate_reason: None,
        boundary_wedge_taper_topology_count: 0,
        boundary_wedge_taper_field_gate_enabled: false,
        boundary_wedge_taper_field_threshold: 0.0,
        contribution_localization: None,
    }
}

fn apply_dirichlet_values(
    matrix: &mut CsrMatrix,
    rhs: &mut [f64],
    boundary_values: &[Option<f64>],
) -> Result<(), String> {
    if matrix.nrows != boundary_values.len() || rhs.len() != boundary_values.len() {
        return Err("weighted stress Dirichlet dimensions do not match".to_string());
    }

    for row in 0..matrix.nrows {
        if let Some(value) = boundary_values[row] {
            let mut found_diag = false;
            for idx in matrix.row_ptr[row]..matrix.row_ptr[row + 1] {
                if matrix.col_idx[idx] == row {
                    matrix.values[idx] = 1.0;
                    found_diag = true;
                } else {
                    matrix.values[idx] = 0.0;
                }
            }
            if !found_diag {
                return Err(format!(
                    "weighted stress Dirichlet row {row} has no diagonal entry"
                ));
            }
            rhs[row] = value;
        } else {
            for idx in matrix.row_ptr[row]..matrix.row_ptr[row + 1] {
                if let Some(value) = boundary_values[matrix.col_idx[idx]] {
                    rhs[row] -= matrix.values[idx] * value;
                    matrix.values[idx] = 0.0;
                }
            }
        }
    }
    Ok(())
}

/// Compute FEMM-like weighted-stress torque over the native airgap.
///
/// This solves a Laplace weighting function on air nodes with w=1 on moving
/// rotor-body boundaries (rotor core and magnets) and w=0 on fixed stator
/// boundaries. The torque integral then uses the virtual rotation field
/// `u = z × r`, which reduces to Arkkio's radial averaging on a smooth annulus
/// but remains contour-free on a slotted airgap.
#[allow(dead_code)]
pub fn compute_torque_weighted_stress_debug(
    mesh: &TriMesh,
    fields: &[ElementField],
    stack_length_mm: f64,
    pole_count: u32,
) -> WeightedStressTorqueDebug {
    compute_torque_weighted_stress_debug_with_az(mesh, fields, None, stack_length_mm, pole_count)
}

pub fn compute_torque_weighted_stress_debug_with_az(
    mesh: &TriMesh,
    fields: &[ElementField],
    az: Option<&[f64]>,
    stack_length_mm: f64,
    pole_count: u32,
) -> WeightedStressTorqueDebug {
    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;
    if mesh.triangles.len() != fields.len() {
        return weighted_stress_error(
            format!(
                "field count {} does not match triangle count {}",
                fields.len(),
                mesh.triangles.len()
            ),
            scale_factor,
            0,
            0,
        );
    }

    let mut airgap_triangles = Vec::new();
    let mut global_to_local = vec![None; mesh.nodes.len()];
    let mut local_to_global = Vec::new();
    let include_slots = !weighted_stress_airgap_only();
    let physical_bounds = weighted_stress_physical_bounds(mesh, include_slots);
    let domain_regions = if include_slots {
        vec!["Airgap".to_string(), "SlotWinding".to_string()]
    } else {
        vec!["Airgap".to_string()]
    };

    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        if !weighted_stress_triangle_in_domain(mesh, tri_idx, include_slots, physical_bounds) {
            continue;
        }
        airgap_triangles.push(tri_idx);
        for &node_idx in tri {
            if global_to_local[node_idx].is_none() {
                global_to_local[node_idx] = Some(local_to_global.len());
                local_to_global.push(node_idx);
            }
        }
    }

    let airgap_element_count = airgap_triangles.len();
    let airgap_node_count = local_to_global.len();
    if airgap_element_count == 0 || airgap_node_count < 2 {
        return weighted_stress_error(
            format!(
                "cannot compute weighted stress torque: {airgap_element_count} airgap elements, {airgap_node_count} airgap nodes"
            ),
            scale_factor,
            airgap_element_count,
            airgap_node_count,
        );
    }

    let mut r_min = f64::INFINITY;
    let mut r_max = 0.0_f64;
    for &global_idx in &local_to_global {
        let [x, y] = mesh.nodes[global_idx];
        let radius = (x * x + y * y).sqrt();
        r_min = r_min.min(radius);
        r_max = r_max.max(radius);
    }
    let gap = r_max - r_min;
    if !gap.is_finite() || gap <= 1e-12 {
        return weighted_stress_error(
            format!("cannot compute weighted stress torque: invalid airgap radial span {gap:.6e}m"),
            scale_factor,
            airgap_element_count,
            airgap_node_count,
        );
    }

    let mut stiffness = CooMatrix::new(airgap_node_count);
    for &tri_idx in &airgap_triangles {
        let [i, j, k] = mesh.triangles[tri_idx];
        let [li, lj, lk] = [
            global_to_local[i].expect("airgap node mapped"),
            global_to_local[j].expect("airgap node mapped"),
            global_to_local[k].expect("airgap node mapped"),
        ];
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, k);
        if area <= 1e-18 {
            continue;
        }
        let local_nodes = [li, lj, lk];
        for a in 0..3 {
            for b in 0..3 {
                let dot = grad[a][0] * grad[b][0] + grad[a][1] * grad[b][1];
                let value = dot * area;
                if value.abs() > 1e-30 {
                    stiffness.add(local_nodes[a], local_nodes[b], value);
                }
            }
        }
    }

    let boundary_tol = (gap * 1.0e-6).max(1.0e-12);
    let mut boundary_values = vec![None; airgap_node_count];
    let mut touches_inner_body = vec![false; mesh.nodes.len()];
    let mut touches_outer_body = vec![false; mesh.nodes.len()];
    let mut touches_outer_slot = vec![false; mesh.nodes.len()];
    let mut touches_outer_tooth = vec![false; mesh.nodes.len()];
    let mut touches_outer_yoke = vec![false; mesh.nodes.len()];
    for (tri_idx, tri) in mesh.triangles.iter().enumerate() {
        if weighted_stress_triangle_in_domain(mesh, tri_idx, include_slots, physical_bounds) {
            continue;
        }
        let boundary_side =
            weighted_stress_excluded_boundary_side(mesh, tri_idx, include_slots, physical_bounds);
        for &node_idx in tri {
            if global_to_local[node_idx].is_none() {
                continue;
            }
            match boundary_side {
                Some(1.0) => touches_inner_body[node_idx] = true,
                Some(0.0) => {
                    touches_outer_body[node_idx] = true;
                    match mesh.regions[tri_idx] {
                        Region::SlotWinding => touches_outer_slot[node_idx] = true,
                        Region::StatorTooth => touches_outer_tooth[node_idx] = true,
                        Region::StatorYoke => touches_outer_yoke[node_idx] = true,
                        _ => {}
                    }
                }
                _ => {}
            }
        }
    }
    let mut inner_count = 0_usize;
    let mut outer_count = 0_usize;
    for (local_idx, &global_idx) in local_to_global.iter().enumerate() {
        let [x, y] = mesh.nodes[global_idx];
        let radius = (x * x + y * y).sqrt();
        if touches_inner_body[global_idx] || (radius - r_min).abs() <= boundary_tol {
            boundary_values[local_idx] = Some(1.0);
            inner_count += 1;
        } else if touches_outer_body[global_idx] || (radius - r_max).abs() <= boundary_tol {
            boundary_values[local_idx] = Some(0.0);
            outer_count += 1;
        }
    }
    if inner_count == 0 || outer_count == 0 {
        return weighted_stress_error(
            format!(
                "cannot compute weighted stress torque: inner/outer weighting boundaries have {inner_count}/{outer_count} nodes"
            ),
            scale_factor,
            airgap_element_count,
            airgap_node_count,
        );
    }

    let mut matrix = stiffness.to_csr();
    let mut rhs = vec![0.0_f64; airgap_node_count];
    if let Err(error) = apply_dirichlet_values(&mut matrix, &mut rhs, &boundary_values) {
        return weighted_stress_error(error, scale_factor, airgap_element_count, airgap_node_count);
    }

    let max_iter = (airgap_node_count * 4).max(500);
    let weights = match pcg_solve(&matrix, &rhs, max_iter, 1.0e-11) {
        Ok(solution) => solution,
        Err(error) => {
            return weighted_stress_error(
                format!("weighted stress weighting solve failed: {error}"),
                scale_factor,
                airgap_element_count,
                airgap_node_count,
            );
        }
    };
    let weight_min = weights.iter().copied().fold(f64::INFINITY, f64::min);
    let weight_max = weights.iter().copied().fold(f64::NEG_INFINITY, f64::max);

    let use_az_field = weighted_stress_use_az_field() && az.is_some() && !include_slots;
    let az_airgap_lookup = if use_az_field {
        Some(AirgapTriangleLookup::new(mesh))
    } else {
        None
    };
    let az_field_dtheta = (mesh.info.total_span_deg.to_radians()
        / mesh.info.angular_divisions.max(1) as f64)
        .abs()
        .max(1.0e-6);
    let az_field_radial_gap = physical_bounds
        .map(|(inner, bore, _slot_outer)| (bore - inner).abs())
        .unwrap_or(gap)
        .max(1.0e-12);
    let use_boundary_wedge_sampling = use_az_field && weighted_stress_boundary_wedge_sampling();
    let use_boundary_wedge_taper = use_az_field && weighted_stress_boundary_wedge_taper();
    let taper_outer_airgap_bulk =
        use_boundary_wedge_taper && weighted_stress_boundary_wedge_taper_outer_bulk();
    let boundary_wedge_sample_fraction = weighted_stress_boundary_wedge_sample_fraction();
    let boundary_wedge_fraction_threshold = weighted_stress_boundary_wedge_fraction_threshold();
    let boundary_wedge_taper_factor = if use_boundary_wedge_taper {
        weighted_stress_boundary_wedge_taper_factor()
    } else {
        1.0
    };
    // B2: field-aware classifier gate. Only meaningful when the topology-based
    // taper is active; otherwise the gate has nothing to gate.
    let use_field_gate =
        use_boundary_wedge_taper && weighted_stress_boundary_wedge_field_gate_enabled();
    let field_gate_threshold = if use_field_gate {
        weighted_stress_boundary_wedge_field_threshold()
    } else {
        0.0
    };
    let use_nodal_b = !use_az_field && weighted_stress_use_nodal_b();
    let use_boundary_aware_b = use_nodal_b && weighted_stress_boundary_aware_b();
    let field_source = if use_boundary_wedge_sampling {
        "az_airgap_boundary_wedge_interior"
    } else if use_az_field {
        "az_airgap_central_difference"
    } else if use_boundary_aware_b {
        "boundary_aware_domain_nodal_b_centroid"
    } else if use_nodal_b {
        "nodal_b_centroid"
    } else {
        "element_b"
    };
    // Compute nodal_b when the regular field source needs it OR when the B2
    // field gate is on (the gate needs per-node |B|^2 to score contamination,
    // even if the WST integration itself uses A_z-derived field).
    let nodal_b = if use_boundary_aware_b {
        Some(compute_filtered_nodal_b_field(mesh, fields, |region| {
            weighted_stress_domain(region, include_slots)
        }))
    } else if use_nodal_b || use_field_gate {
        Some(compute_nodal_b_field(mesh, fields))
    } else {
        None
    };
    let l_stack_m = stack_length_mm * 1e-3;
    let mut modeled_torque_nm = 0.0_f64;
    let mut airgap_contribution_nm = 0.0_f64;
    let mut slot_winding_contribution_nm = 0.0_f64;
    let mut field_fallback_count = 0_usize;
    let mut boundary_wedge_sample_count = 0_usize;
    let mut boundary_wedge_sample_fallback_count = 0_usize;
    let mut boundary_wedge_taper_count = 0_usize;
    // B2 (field-aware): track topology-only count separately from the actual
    // applied count so we can see how aggressively the contamination filter
    // trims the tagged set.
    let mut boundary_wedge_taper_topology_count = 0_usize;
    let mut boundary_wedge_taper_removed_nm = 0.0_f64;
    let mut contribution_localization = if weighted_stress_localization_enabled() {
        Some(WeightedStressContributionAccumulator::new(field_source))
    } else {
        None
    };
    let total_span_rad = mesh.info.total_span_deg.to_radians().abs().max(1.0e-12);

    for &tri_idx in &airgap_triangles {
        let [i, j, k] = mesh.triangles[tri_idx];
        let [li, lj, lk] = [
            global_to_local[i].expect("airgap node mapped"),
            global_to_local[j].expect("airgap node mapped"),
            global_to_local[k].expect("airgap node mapped"),
        ];
        let (area, grad) = triangle_gradients(&mesh.nodes, i, j, k);
        if area <= 1e-18 {
            continue;
        }

        let grad_w_x =
            weights[li] * grad[0][0] + weights[lj] * grad[1][0] + weights[lk] * grad[2][0];
        let grad_w_y =
            weights[li] * grad[0][1] + weights[lj] * grad[1][1] + weights[lk] * grad[2][1];

        let [x1, y1] = mesh.nodes[i];
        let [x2, y2] = mesh.nodes[j];
        let [x3, y3] = mesh.nodes[k];
        let cx = (x1 + x2 + x3) / 3.0;
        let cy = (y1 + y2 + y3) / 3.0;
        let centroid_radius = (cx * cx + cy * cy).sqrt();
        if centroid_radius <= 1e-12 {
            continue;
        }
        let radial_fraction = ((centroid_radius - r_min) / gap).clamp(0.0, 1.0);
        let tri_nodes = [i, j, k];
        let tri_touches_inner = tri_nodes.iter().any(|&node| touches_inner_body[node]);
        let tri_touches_slot = tri_nodes.iter().any(|&node| touches_outer_slot[node]);
        let tri_touches_tooth = tri_nodes.iter().any(|&node| touches_outer_tooth[node]);
        let tri_touches_yoke = tri_nodes.iter().any(|&node| touches_outer_yoke[node]);
        let interface_class = weighted_stress_interface_class(
            mesh.regions[tri_idx],
            radial_fraction,
            tri_touches_inner,
            tri_touches_slot,
            tri_touches_tooth,
            tri_touches_yoke,
        );
        let use_interior_boundary_wedge_sample = use_boundary_wedge_sampling
            && radial_fraction >= boundary_wedge_fraction_threshold
            && matches!(
                interface_class,
                "slot_mouth_boundary" | "tooth_tip_boundary" | "slot_mouth_tooth_tip_boundary"
            );

        let (bx, by) = if use_az_field {
            let lookup = az_airgap_lookup
                .as_ref()
                .expect("A_z field source requires airgap lookup");
            let az = az.expect("A_z field source enabled only when A_z is present");
            let theta = cy.atan2(cx);
            let sample_radius = if use_interior_boundary_wedge_sample {
                boundary_wedge_sample_count += 1;
                let clamped_fraction = radial_fraction.min(boundary_wedge_sample_fraction);
                r_min + clamped_fraction * gap
            } else {
                centroid_radius
            };
            let sample_point = [sample_radius * theta.cos(), sample_radius * theta.sin()];
            let radial_clearance = physical_bounds
                .map(|(inner, bore, _slot_outer)| (sample_radius - inner).min(bore - sample_radius))
                .unwrap_or(0.5 * az_field_radial_gap);
            let radial_step = (0.45 * radial_clearance)
                .min(0.25 * az_field_radial_gap)
                .max(az_field_radial_gap * 1.0e-4);
            let sample = lookup
                .sample_b_from_az(az, sample_point, az_field_dtheta, radial_step)
                .or_else(|| {
                    if use_interior_boundary_wedge_sample {
                        boundary_wedge_sample_fallback_count += 1;
                        let fallback_clearance = physical_bounds
                            .map(|(inner, bore, _slot_outer)| {
                                (centroid_radius - inner).min(bore - centroid_radius)
                            })
                            .unwrap_or(0.5 * az_field_radial_gap);
                        let fallback_step = (0.45 * fallback_clearance)
                            .min(0.25 * az_field_radial_gap)
                            .max(az_field_radial_gap * 1.0e-4);
                        lookup.sample_b_from_az(az, [cx, cy], az_field_dtheta, fallback_step)
                    } else {
                        None
                    }
                });
            if let Some((_sample_tri, b_r, b_t)) = sample {
                let cos_theta = sample_point[0] / sample_radius;
                let sin_theta = sample_point[1] / sample_radius;
                (
                    b_r * cos_theta - b_t * sin_theta,
                    b_r * sin_theta + b_t * cos_theta,
                )
            } else {
                field_fallback_count += 1;
                (fields[tri_idx].bx, fields[tri_idx].by)
            }
        } else if let Some(nodal_b) = &nodal_b {
            let nb_i = nodal_b[i];
            let nb_j = nodal_b[j];
            let nb_k = nodal_b[k];
            (
                (nb_i[0] + nb_j[0] + nb_k[0]) / 3.0,
                (nb_i[1] + nb_j[1] + nb_k[1]) / 3.0,
            )
        } else {
            (fields[tri_idx].bx, fields[tri_idx].by)
        };
        let b2 = bx * bx + by * by;
        let s_xx = (bx * bx - 0.5 * b2) / MU_0;
        let s_xy = (bx * by) / MU_0;
        let s_yy = (by * by - 0.5 * b2) / MU_0;

        let stress_grad_x = s_xx * grad_w_x + s_xy * grad_w_y;
        let stress_grad_y = s_xy * grad_w_x + s_yy * grad_w_y;
        let virtual_rotation_x = -cy;
        let virtual_rotation_y = cx;

        let raw_contribution_nm = -l_stack_m
            * area
            * (virtual_rotation_x * stress_grad_x + virtual_rotation_y * stress_grad_y);

        // B2 (field-aware): split the existing topology gate from the new
        // contamination check so we can count both populations independently
        // and only attenuate triangles that show the actual flux-discontinuity
        // signature.
        let topology_match = use_boundary_wedge_taper
            && weighted_stress_stator_boundary_layer(interface_class, taper_outer_airgap_bulk);
        if topology_match {
            boundary_wedge_taper_topology_count += 1;
        }

        // Per-triangle contamination score: relative spread of |B|^2 across
        // the three nodes. Contamination triangles straddle the iron/airgap
        // step in B and therefore have score ~ 1; legitimate-cogging triangles
        // sit in the airgap interior with smooth field and have score << 1.
        // Only computed when the field gate is on AND topology matched, so
        // there's no overhead for the default (gate off) configuration.
        let contamination_score = if use_field_gate && topology_match {
            if let Some(nb) = nodal_b.as_ref() {
                let b2_at = |idx: usize| -> f64 {
                    let v = nb[idx];
                    v[0] * v[0] + v[1] * v[1]
                };
                let b2_i = b2_at(i);
                let b2_j = b2_at(j);
                let b2_k = b2_at(k);
                let b2_max = b2_i.max(b2_j).max(b2_k);
                let b2_min = b2_i.min(b2_j).min(b2_k);
                if b2_max > 1.0e-20 {
                    (b2_max - b2_min) / b2_max
                } else {
                    0.0
                }
            } else {
                // Field gate enabled but nodal_b not available -- shouldn't
                // happen given the nodal_b setup above, but be conservative
                // and skip the gate (fall through to topology-only behavior).
                1.0
            }
        } else {
            // Field gate off OR topology didn't match -- score doesn't matter.
            0.0
        };

        let apply_taper =
            topology_match && (!use_field_gate || contamination_score >= field_gate_threshold);

        let contribution_nm = if apply_taper {
            boundary_wedge_taper_count += 1;
            let tapered = raw_contribution_nm * boundary_wedge_taper_factor;
            boundary_wedge_taper_removed_nm += raw_contribution_nm - tapered;
            tapered
        } else {
            raw_contribution_nm
        };
        modeled_torque_nm += contribution_nm;
        if let Some(localization) = &mut contribution_localization {
            let cos_theta = cx / centroid_radius;
            let sin_theta = cy / centroid_radius;
            let b_r_t = bx * cos_theta + by * sin_theta;
            let b_t_t = -bx * sin_theta + by * cos_theta;
            localization.add(
                tri_idx,
                mesh.regions[tri_idx],
                interface_class,
                cx,
                cy,
                centroid_radius,
                cy.atan2(cx).rem_euclid(total_span_rad),
                total_span_rad,
                radial_fraction,
                contribution_nm,
                b_r_t,
                b_t_t,
                (weights[li] + weights[lj] + weights[lk]) / 3.0,
                (grad_w_x * grad_w_x + grad_w_y * grad_w_y).sqrt(),
            );
        }
        match mesh.regions[tri_idx] {
            Region::Airgap => airgap_contribution_nm += contribution_nm,
            Region::SlotWinding => slot_winding_contribution_nm += contribution_nm,
            _ => {}
        }
    }

    eprintln!(
        "  weighted-stress: r_band=[{:.3},{:.3}]mm nodes={} elems={} modeled={:.4}Nm scale={:.4} scaled={:.4}Nm w=[{:.3},{:.3}]",
        r_min * 1e3,
        r_max * 1e3,
        airgap_node_count,
        airgap_element_count,
        modeled_torque_nm,
        scale_factor,
        modeled_torque_nm * scale_factor,
        weight_min,
        weight_max,
    );
    if use_field_gate {
        // B2 instrumentation: how many topology-tagged triangles passed the
        // contamination filter? Ratio close to 1.0 means the gate is letting
        // almost everything through (threshold too low or geometry has many
        // contaminated triangles); ratio near 0.0 means the gate is rejecting
        // most of them (threshold too high or the topology classifier is
        // catching mostly clean triangles).
        let pass_ratio = if boundary_wedge_taper_topology_count > 0 {
            boundary_wedge_taper_count as f64 / boundary_wedge_taper_topology_count as f64
        } else {
            0.0
        };
        eprintln!(
            "  weighted-stress field_gate: threshold={:.3} topology_count={} taper_applied_count={} pass_ratio={:.3} taper_removed={:.4}Nm",
            field_gate_threshold,
            boundary_wedge_taper_topology_count,
            boundary_wedge_taper_count,
            pass_ratio,
            boundary_wedge_taper_removed_nm,
        );
    }

    WeightedStressTorqueDebug {
        status: "ok".to_string(),
        error: None,
        domain_regions,
        airgap_element_count,
        airgap_node_count,
        boundary_inner_node_count: inner_count,
        boundary_outer_node_count: outer_count,
        airgap_r_inner_mm: r_min * 1e3,
        airgap_r_outer_mm: r_max * 1e3,
        weight_min,
        weight_max,
        modeled_torque_nm,
        airgap_contribution_nm,
        slot_winding_contribution_nm,
        scale_factor,
        scaled_torque_nm: modeled_torque_nm * scale_factor,
        field_source: field_source.to_string(),
        field_fallback_count,
        boundary_wedge_sample_count,
        boundary_wedge_sample_fallback_count,
        boundary_wedge_taper_count,
        boundary_wedge_taper_factor,
        boundary_wedge_taper_removed_nm,
        boundary_wedge_taper_applied: use_boundary_wedge_taper && boundary_wedge_taper_count > 0,
        boundary_wedge_taper_gate_reason: None,
        boundary_wedge_taper_topology_count,
        boundary_wedge_taper_field_gate_enabled: use_field_gate,
        boundary_wedge_taper_field_threshold: field_gate_threshold,
        contribution_localization: contribution_localization
            .map(WeightedStressContributionAccumulator::finish),
    }
}

/// Compute torque using a sampled mid-gap contour on the modeled airgap span.
#[allow(dead_code)]
pub fn compute_torque_midgap_contour(
    mesh: &TriMesh,
    fields: &[ElementField],
    stack_length_mm: f64,
    pole_count: u32,
) -> f64 {
    compute_torque_midgap_contour_debug(mesh, fields, stack_length_mm, pole_count).scaled_torque_nm
}

/// Compute torque and retain the exact airgap elements and contributions used.
pub fn compute_torque_debug(
    mesh: &TriMesh,
    fields: &[ElementField],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
) -> TorqueDebug {
    let l_stack = stack_length_mm * 1e-3;
    let n_pole_pitches = mesh.info.n_pole_pitches;
    let mut torque_sum_modeled = 0.0_f64;
    let scale_factor = pole_count as f64 / n_pole_pitches as f64;
    let mut airgap_elements = Vec::new();

    for (idx, (tri, field)) in mesh.triangles.iter().zip(fields.iter()).enumerate() {
        if mesh.regions[idx] != Region::Airgap {
            continue;
        }

        let cx = centroids[idx][0];
        let cy = centroids[idx][1];
        let r = (cx * cx + cy * cy).sqrt();
        if r < 1e-9 {
            continue;
        }

        let (b_r, b_t) = project_field_to_polar(field, [cx, cy])
            .expect("airgap centroids should never project from the origin");

        let [i, j, m] = *tri;
        let area = triangle_area(&mesh.nodes, i, j, m);
        let modeled_contribution = (l_stack / MU_0) * b_r * b_t * area;
        torque_sum_modeled += modeled_contribution;

        airgap_elements.push(TorqueElementContribution {
            triangle_index: idx,
            centroid_x_mm: cx * 1e3,
            centroid_y_mm: cy * 1e3,
            radius_mm: r * 1e3,
            theta_mech_deg: cy.atan2(cx).to_degrees(),
            area_mm2: area * 1e6,
            b_r_t: b_r,
            b_t_t: b_t,
            modeled_contribution_nm: modeled_contribution,
            scaled_contribution_nm: modeled_contribution * scale_factor,
        });
    }

    TorqueDebug {
        airgap_element_count: airgap_elements.len(),
        modeled_torque_nm: torque_sum_modeled,
        scale_factor,
        scaled_torque_nm: torque_sum_modeled * scale_factor,
        airgap_elements,
    }
}

fn robust_contour_radii(mesh: &TriMesh) -> Vec<f64> {
    let working = full_coverage_airgap_radii(mesh);
    let mut radii = Vec::new();
    if working.len() >= 3 {
        for idx in [
            working.len() / 4,
            working.len() / 2,
            (3 * working.len()) / 4,
        ] {
            radii.push(working[idx.min(working.len() - 1)]);
        }
    } else if !working.is_empty() {
        radii.extend(working);
    } else if let Some(radius) = airgap_mid_radius(mesh) {
        radii.push(radius);
    }
    radii.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    radii.dedup_by(|a, b| (*a - *b).abs() < 1e-9);
    radii
}

fn airgap_node_radius_extent(mesh: &TriMesh) -> Option<(f64, f64)> {
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
        Some((min_radius, max_radius))
    } else {
        None
    }
}

fn diagnostic_contour_candidate_radii(mesh: &TriMesh) -> Vec<f64> {
    let working = full_coverage_airgap_radii(mesh);
    let mut radii = Vec::new();
    if working.len() >= 2 {
        for idx in [
            0,
            working.len() / 4,
            working.len() / 2,
            (3 * working.len()) / 4,
            working.len() - 1,
        ] {
            radii.push(working[idx.min(working.len() - 1)]);
        }
        radii.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        radii.dedup_by(|a, b| (*a - *b).abs() < 1e-9);
        return radii;
    } else if let Some(radius) = working.first() {
        radii.push(*radius);
    }

    if let Some((inner_radius, outer_radius)) = airgap_node_radius_extent(mesh) {
        let span = outer_radius - inner_radius;
        for fraction in [0.20, 0.35, 0.50, 0.65, 0.80] {
            radii.push(inner_radius + fraction * span);
        }
    }

    radii.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    radii.dedup_by(|a, b| (*a - *b).abs() < 1e-9);
    radii
}

fn robust_contour_offsets() -> Vec<f64> {
    vec![0.125, 0.375, 0.625, 0.875]
}

fn collect_nodal_contour_airgap_records(mesh: &TriMesh) -> Vec<AirgapTriangleRecord> {
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

fn robust_error_case(
    source: &str,
    radius_m: f64,
    offset_fraction: f64,
    sample_count: usize,
    error: String,
) -> RobustContourTorqueCase {
    RobustContourTorqueCase {
        source: source.to_string(),
        radius_mm: radius_m * 1e3,
        offset_fraction,
        sample_count,
        status: "error".to_string(),
        error: Some(error),
        torque_nm: 0.0,
        unique_triangle_count: 0,
    }
}

fn robust_nodal_b_case(
    mesh: &TriMesh,
    records: &[AirgapTriangleRecord],
    nodal_b: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
    radius_m: f64,
    sample_count: usize,
    offset_fraction: f64,
) -> RobustContourTorqueCase {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    if records.is_empty() {
        return robust_error_case(
            "nodal_b",
            radius_m,
            offset_fraction,
            sample_count,
            "mesh has no airgap triangles for contour torque".to_string(),
        );
    }
    if sample_count == 0 || total_span_rad.abs() < 1e-12 {
        return robust_error_case(
            "nodal_b",
            radius_m,
            offset_fraction,
            sample_count,
            "invalid contour sample count or modeled span".to_string(),
        );
    }

    let l_stack = stack_length_mm * 1e-3;
    let dtheta = total_span_rad / sample_count as f64;
    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;
    let mut modeled_torque_nm = 0.0;
    let mut sampled_triangles = HashSet::new();

    for sample_index in 0..sample_count {
        let theta = total_span_rad * (sample_index as f64 + offset_fraction) / sample_count as f64;
        let x = radius_m * theta.cos();
        let y = radius_m * theta.sin();

        let mut matched: Option<(&AirgapTriangleRecord, [f64; 3])> = None;
        for record in records {
            let pad = 1e-9;
            if x < record.bbox[0] - pad
                || x > record.bbox[1] + pad
                || y < record.bbox[2] - pad
                || y > record.bbox[3] + pad
            {
                continue;
            }
            let Some(weights) = barycentric_weights([x, y], record.tri_xy) else {
                continue;
            };
            matched = Some((record, weights));
            break;
        }

        let Some((record, weights)) = matched else {
            return robust_error_case(
                "nodal_b",
                radius_m,
                offset_fraction,
                sample_count,
                format!(
                    "contour sample at theta={:.3}deg and r={:.6}mm did not land inside an airgap triangle",
                    theta.to_degrees(),
                    radius_m * 1e3,
                ),
            );
        };

        let mut bx = 0.0;
        let mut by = 0.0;
        for k in 0..3 {
            let nb = nodal_b[record.tri_nodes[k]];
            bx += weights[k] * nb[0];
            by += weights[k] * nb[1];
        }
        let Some((b_r, b_t)) = cartesian_to_polar_b(bx, by, [x, y]) else {
            return robust_error_case(
                "nodal_b",
                radius_m,
                offset_fraction,
                sample_count,
                "contour radius sampled the origin".to_string(),
            );
        };
        modeled_torque_nm += l_stack * radius_m * radius_m * b_r * b_t * dtheta / MU_0;
        sampled_triangles.insert(record.triangle_index);
    }

    RobustContourTorqueCase {
        source: "nodal_b".to_string(),
        radius_mm: radius_m * 1e3,
        offset_fraction,
        sample_count,
        status: "ok".to_string(),
        error: None,
        torque_nm: modeled_torque_nm * scale_factor,
        unique_triangle_count: sampled_triangles.len(),
    }
}

fn robust_az_case(
    mesh: &TriMesh,
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
    radius_m: f64,
    sample_count: usize,
    offset_fraction: f64,
) -> RobustContourTorqueCase {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    if !is_full_circle(mesh) {
        return robust_error_case(
            "az",
            radius_m,
            offset_fraction,
            sample_count,
            "A_z-derived contour torque currently requires a full 360° model".to_string(),
        );
    }
    if sample_count == 0 || total_span_rad.abs() < 1e-12 {
        return robust_error_case(
            "az",
            radius_m,
            offset_fraction,
            sample_count,
            "invalid contour sample count or modeled span".to_string(),
        );
    }

    let records = collect_airgap_triangle_records(mesh);
    if records.is_empty() {
        return robust_error_case(
            "az",
            radius_m,
            offset_fraction,
            sample_count,
            "mesh has no airgap triangles for contour torque".to_string(),
        );
    }

    let radial_step_m = choose_az_contour_radial_step(mesh, radius_m);
    let l_stack = stack_length_mm * 1e-3;
    let dtheta = total_span_rad / sample_count as f64;
    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;
    let mut modeled_torque_nm = 0.0;
    let mut sampled_triangles = HashSet::new();

    for sample_index in 0..sample_count {
        let theta = total_span_rad * (sample_index as f64 + offset_fraction) / sample_count as f64;
        let point_xy_m = [radius_m * theta.cos(), radius_m * theta.sin()];
        let Some((triangle_index, b_r, b_t)) =
            sample_contour_field_from_az(&records, az, point_xy_m, dtheta, radial_step_m)
        else {
            return robust_error_case(
                "az",
                radius_m,
                offset_fraction,
                sample_count,
                format!(
                    "A_z-derived contour sample at theta={:.3}deg and r={:.6}mm could not be reconstructed",
                    theta.to_degrees(),
                    radius_m * 1e3,
                ),
            );
        };
        modeled_torque_nm += l_stack * radius_m * radius_m * b_r * b_t * dtheta / MU_0;
        sampled_triangles.insert(triangle_index);
    }

    RobustContourTorqueCase {
        source: "az".to_string(),
        radius_mm: radius_m * 1e3,
        offset_fraction,
        sample_count,
        status: "ok".to_string(),
        error: None,
        torque_nm: modeled_torque_nm * scale_factor,
        unique_triangle_count: sampled_triangles.len(),
    }
}

fn median(values: &mut [f64]) -> f64 {
    values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let len = values.len();
    if len == 0 {
        return 0.0;
    }
    if len % 2 == 1 {
        values[len / 2]
    } else {
        0.5 * (values[len / 2 - 1] + values[len / 2])
    }
}

fn robust_source_stats(
    source: &str,
    cases: &[RobustContourTorqueCase],
) -> RobustContourTorqueSourceStats {
    let source_cases: Vec<&RobustContourTorqueCase> =
        cases.iter().filter(|case| case.source == source).collect();
    let ok_values: Vec<f64> = source_cases
        .iter()
        .filter(|case| case.status == "ok")
        .map(|case| case.torque_nm)
        .collect();
    if ok_values.is_empty() {
        return RobustContourTorqueSourceStats {
            source: source.to_string(),
            status: "error".to_string(),
            case_count: source_cases.len(),
            ok_count: 0,
            selected_torque_nm: 0.0,
            mean_torque_nm: 0.0,
            min_torque_nm: 0.0,
            max_torque_nm: 0.0,
            spread_abs_nm: 0.0,
            spread_rel: None,
        };
    }

    let mut sorted = ok_values.clone();
    let selected_torque_nm = median(&mut sorted);
    let mean_torque_nm = ok_values.iter().sum::<f64>() / ok_values.len() as f64;
    let min_torque_nm = ok_values.iter().copied().fold(f64::INFINITY, f64::min);
    let max_torque_nm = ok_values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let spread_abs_nm = max_torque_nm - min_torque_nm;
    let denom = selected_torque_nm
        .abs()
        .max(ROBUST_CONTOUR_REL_SPREAD_FLOOR_NM);
    let spread_rel = spread_abs_nm / denom;
    let stable = spread_abs_nm <= ROBUST_CONTOUR_MAX_ABS_SPREAD_NM
        || spread_rel <= ROBUST_CONTOUR_MAX_REL_SPREAD;

    RobustContourTorqueSourceStats {
        source: source.to_string(),
        status: if stable { "ok" } else { "unstable" }.to_string(),
        case_count: source_cases.len(),
        ok_count: ok_values.len(),
        selected_torque_nm,
        mean_torque_nm,
        min_torque_nm,
        max_torque_nm,
        spread_abs_nm,
        spread_rel: Some(spread_rel),
    }
}

/// Compute a robust contour torque ensemble across multiple radii and angular offsets.
pub fn compute_torque_robust_contour_debug(
    mesh: &TriMesh,
    fields: &[ElementField],
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
) -> RobustContourTorqueDebug {
    let radii = robust_contour_radii(mesh);
    let offsets = robust_contour_offsets();
    let sample_count = robust_contour_sample_count(mesh);
    if radii.is_empty() {
        return RobustContourTorqueDebug {
            status: "error".to_string(),
            error: Some("could not determine robust contour radii".to_string()),
            selected_source: "none".to_string(),
            selected_torque_nm: 0.0,
            selected_reason: "no airgap radii available".to_string(),
            sample_count,
            radius_count: 0,
            offset_count: offsets.len(),
            offsets,
            radii_mm: Vec::new(),
            source_stats: Vec::new(),
            cases: Vec::new(),
        };
    }

    let nodal_b = compute_nodal_b_field(mesh, fields);
    let nodal_records = collect_nodal_contour_airgap_records(mesh);
    let mut cases = Vec::new();
    for &radius_m in &radii {
        for &offset_fraction in &offsets {
            cases.push(robust_az_case(
                mesh,
                az,
                stack_length_mm,
                pole_count,
                radius_m,
                sample_count,
                offset_fraction,
            ));
            cases.push(robust_nodal_b_case(
                mesh,
                &nodal_records,
                &nodal_b,
                stack_length_mm,
                pole_count,
                radius_m,
                sample_count,
                offset_fraction,
            ));
        }
    }

    let source_stats = vec![
        robust_source_stats("az", &cases),
        robust_source_stats("nodal_b", &cases),
    ];
    let mut candidates: Vec<&RobustContourTorqueSourceStats> = source_stats
        .iter()
        .filter(|stats| stats.ok_count > 0)
        .collect();
    if candidates.is_empty() {
        return RobustContourTorqueDebug {
            status: "error".to_string(),
            error: Some("all robust contour cases failed".to_string()),
            selected_source: "none".to_string(),
            selected_torque_nm: 0.0,
            selected_reason: "all robust contour cases failed".to_string(),
            sample_count,
            radius_count: radii.len(),
            offset_count: offsets.len(),
            offsets,
            radii_mm: radii.iter().map(|r| r * 1e3).collect(),
            source_stats,
            cases,
        };
    }

    candidates.sort_by(|a, b| {
        let a_rank = if a.status == "ok" { 0 } else { 1 };
        let b_rank = if b.status == "ok" { 0 } else { 1 };
        a_rank.cmp(&b_rank).then_with(|| {
            a.spread_abs_nm
                .partial_cmp(&b.spread_abs_nm)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
    });
    let selected = candidates[0];
    let status = selected.status.clone();
    let selected_reason = if selected.status == "ok" {
        format!(
            "{} ensemble stable: median={:.6e} Nm spread={:.6e} Nm",
            selected.source, selected.selected_torque_nm, selected.spread_abs_nm,
        )
    } else {
        format!(
            "{} ensemble is least unstable: median={:.6e} Nm spread={:.6e} Nm",
            selected.source, selected.selected_torque_nm, selected.spread_abs_nm,
        )
    };

    RobustContourTorqueDebug {
        status,
        error: None,
        selected_source: selected.source.clone(),
        selected_torque_nm: selected.selected_torque_nm,
        selected_reason,
        sample_count,
        radius_count: radii.len(),
        offset_count: offsets.len(),
        offsets,
        radii_mm: radii.iter().map(|r| r * 1e3).collect(),
        source_stats,
        cases,
    }
}

/// Compute torque from a sampled mid-gap contour and retain the exact samples used.
pub fn compute_torque_midgap_contour_debug(
    mesh: &TriMesh,
    fields: &[ElementField],
    stack_length_mm: f64,
    pole_count: u32,
) -> ContourTorqueDebug {
    let sample_count = contour_sample_count(mesh);
    compute_torque_midgap_contour_debug_with_samples(
        mesh,
        fields,
        stack_length_mm,
        pole_count,
        sample_count,
    )
}

/// Compute torque from a sampled mid-gap contour with an explicit sample count.
pub fn compute_torque_midgap_contour_debug_with_samples(
    mesh: &TriMesh,
    fields: &[ElementField],
    stack_length_mm: f64,
    pole_count: u32,
    sample_count: usize,
) -> ContourTorqueDebug {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;
    let Some(radius_m) = airgap_mid_radius(mesh) else {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("could not determine airgap mid-radius".to_string()),
            radius_mm: 0.0,
            sample_count: 0,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    };
    if sample_count == 0 || total_span_rad.abs() < 1e-12 {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("invalid contour sample count or modeled span".to_string()),
            radius_mm: radius_m * 1e3,
            sample_count,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
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
        airgap_triangles.push((triangle_index, tri_xy, [xmin, xmax, ymin, ymax]));
    }

    if airgap_triangles.is_empty() {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("mesh has no airgap triangles for contour torque".to_string()),
            radius_mm: radius_m * 1e3,
            sample_count: 0,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    }

    let l_stack = stack_length_mm * 1e-3;
    let dtheta = total_span_rad / sample_count as f64;
    let sample_offset = contour_sample_offset_fraction();
    let mut modeled_torque_nm = 0.0;
    let mut sampled_triangles = HashSet::new();
    let mut samples = Vec::with_capacity(sample_count);

    // Interpolate nodal B at each contour sample via barycentric
    // weights. Using element-constant B gives O(1) jitter at triangle boundaries
    // and biases the mean torque on coarse airgap meshes.
    let nodal_b = compute_nodal_b_field(mesh, fields);

    // Symmetry instrumentation: bucket contour samples by 90° quadrant.
    // For full-circle sweeps with 360 samples the angular positions are
    // identical modulo 90° (per-quadrant first-sample drift should be 0),
    // so any per-quadrant drift in `partial_torque_nm_per_quadrant` is
    // inherited from the barycentric interpolation picking different
    // triangles (or different nodal-B values) for rotationally-equivalent
    // sample points.
    let full_circle = is_full_circle(mesh);
    let mut q_count: [usize; 4] = [0; 4];
    let mut q_first_theta_mod90: [Option<f64>; 4] = [None; 4];
    let mut q_partial_torque: [f64; 4] = [0.0; 4];

    eprintln!(
        "  contour MST: radius={:.3}mm span={:.2}° npp={} scale_factor={:.4} samples={}",
        radius_m * 1e3,
        mesh.info.total_span_deg,
        mesh.info.n_pole_pitches,
        scale_factor,
        sample_count,
    );

    for sample_index in 0..sample_count {
        let theta = total_span_rad * (sample_index as f64 + sample_offset) / sample_count as f64;
        let x = radius_m * theta.cos();
        let y = radius_m * theta.sin();

        let mut matched: Option<(usize, [f64; 3], [usize; 3])> = None;
        for &(triangle_index, tri_xy, bbox) in &airgap_triangles {
            let pad = 1e-9;
            if x < bbox[0] - pad || x > bbox[1] + pad || y < bbox[2] - pad || y > bbox[3] + pad {
                continue;
            }
            let Some(weights) = barycentric_weights([x, y], tri_xy) else {
                continue;
            };
            matched = Some((triangle_index, weights, mesh.triangles[triangle_index]));
            break;
        }

        let Some((triangle_index, weights, tri_nodes)) = matched else {
            return ContourTorqueDebug {
                status: "error".to_string(),
                error: Some(format!(
                    "contour sample at theta={:.3}deg and r={:.6}mm did not land inside an airgap triangle",
                    theta.to_degrees(),
                    radius_m * 1e3,
                )),
                radius_mm: radius_m * 1e3,
                sample_count,
                total_span_deg: mesh.info.total_span_deg,
                unique_triangle_count: sampled_triangles.len(),
                modeled_torque_nm,
                scale_factor,
                scaled_torque_nm: modeled_torque_nm * scale_factor,
                samples,
                per_quadrant: None,
            };
        };

        // Barycentric-interpolate nodal B at the sample point.
        let mut bx = 0.0;
        let mut by = 0.0;
        for k in 0..3 {
            let nb = nodal_b[tri_nodes[k]];
            bx += weights[k] * nb[0];
            by += weights[k] * nb[1];
        }
        let (b_r, b_t) = cartesian_to_polar_b(bx, by, [x, y])
            .expect("mid-gap contour radius should never sample the origin");
        let modeled_contribution_nm = l_stack * radius_m * radius_m * b_r * b_t * dtheta / MU_0;
        modeled_torque_nm += modeled_contribution_nm;
        sampled_triangles.insert(triangle_index);
        samples.push(ContourTorqueSample {
            sample_index,
            triangle_index,
            x_mm: x * 1e3,
            y_mm: y * 1e3,
            radius_mm: radius_m * 1e3,
            theta_mech_deg: theta.to_degrees(),
            b_r_t: b_r,
            b_t_t: b_t,
            modeled_contribution_nm,
            scaled_contribution_nm: modeled_contribution_nm * scale_factor,
        });

        if full_circle {
            let q = quadrant_of_angle(theta);
            q_count[q] += 1;
            if q_first_theta_mod90[q].is_none() {
                q_first_theta_mod90[q] = Some(angle_mod_quadrant(theta));
            }
            q_partial_torque[q] += modeled_contribution_nm;
        }
    }

    let per_quadrant = if full_circle {
        // Max pairwise diff of first-sample angles mod 90° across quadrants.
        // `None` means no sample landed in that quadrant — shouldn't happen
        // on a full-circle 360-sample sweep, but guard the arithmetic.
        let mut first_rads: Vec<f64> = Vec::with_capacity(4);
        for q in 0..4 {
            if let Some(a) = q_first_theta_mod90[q] {
                first_rads.push(a);
            }
        }
        let max_abs_diff_first = if first_rads.len() < 2 {
            0.0
        } else {
            let mut diff: f64 = 0.0;
            for i in 0..first_rads.len() {
                for j in (i + 1)..first_rads.len() {
                    diff = diff.max((first_rads[i] - first_rads[j]).abs());
                }
            }
            diff
        };
        let first_theta_mod90_deg: [Option<f64>; 4] = [
            q_first_theta_mod90[0].map(f64::to_degrees),
            q_first_theta_mod90[1].map(f64::to_degrees),
            q_first_theta_mod90[2].map(f64::to_degrees),
            q_first_theta_mod90[3].map(f64::to_degrees),
        ];
        let stats = PerQuadrantContourStats {
            full_circle,
            sample_count_per_quadrant: q_count,
            first_sample_theta_mod90_deg_per_quadrant: first_theta_mod90_deg,
            partial_torque_nm_per_quadrant: q_partial_torque,
            max_abs_diff_count: max_abs_diff4_usize(q_count),
            max_rel_diff_partial_torque: max_rel_diff4(q_partial_torque),
            max_abs_diff_first_sample_rad: max_abs_diff_first,
        };
        eprintln!(
            "    mst per-quadrant: counts={:?} max_abs_diff_count={} max_rel_diff_partial={:.3e} max_abs_diff_first_sample_rad={:.3e}",
            stats.sample_count_per_quadrant,
            stats.max_abs_diff_count,
            stats.max_rel_diff_partial_torque,
            stats.max_abs_diff_first_sample_rad,
        );
        if assert_symmetry_enabled() {
            // Integrator-symmetry acceptance thresholds.
            assert!(
                stats.max_abs_diff_count == 0,
                "mst symmetry assert: per-quadrant sample counts differ: {:?}",
                stats.sample_count_per_quadrant,
            );
            assert!(
                stats.max_abs_diff_first_sample_rad <= 1e-12,
                "mst symmetry assert: per-quadrant first-sample angles mod 90° differ by {:.3e} rad (deg={:?})",
                stats.max_abs_diff_first_sample_rad,
                stats.first_sample_theta_mod90_deg_per_quadrant,
            );
            assert!(
                stats.max_rel_diff_partial_torque <= 1e-6,
                "mst symmetry assert: per-quadrant partial-torque rel-diff {:.3e} > 1e-6 (partials={:?})",
                stats.max_rel_diff_partial_torque,
                stats.partial_torque_nm_per_quadrant,
            );
        }
        Some(stats)
    } else {
        None
    };

    ContourTorqueDebug {
        status: "ok".to_string(),
        error: None,
        radius_mm: radius_m * 1e3,
        sample_count,
        total_span_deg: mesh.info.total_span_deg,
        unique_triangle_count: sampled_triangles.len(),
        modeled_torque_nm,
        scale_factor,
        scaled_torque_nm: modeled_torque_nm * scale_factor,
        samples,
        per_quadrant,
    }
}

pub(super) fn compute_torque_midgap_contour_debug_from_az(
    mesh: &TriMesh,
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
) -> ContourTorqueDebug {
    let sample_count = contour_sample_count(mesh);
    compute_torque_midgap_contour_debug_with_samples_from_az(
        mesh,
        az,
        stack_length_mm,
        pole_count,
        sample_count,
    )
}

pub(super) fn compute_torque_midgap_contour_debug_with_samples_from_az(
    mesh: &TriMesh,
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
    sample_count: usize,
) -> ContourTorqueDebug {
    let Some(radius_m) = airgap_mid_radius(mesh) else {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("could not determine airgap mid-radius".to_string()),
            radius_mm: 0.0,
            sample_count: 0,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor: pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    };

    compute_torque_midgap_contour_debug_with_radius_from_az(
        mesh,
        az,
        stack_length_mm,
        pole_count,
        radius_m,
        sample_count,
    )
}

/// Compute contour torques at multiple airgap radii for validation.
///
/// This diagnostic function evaluates the MST torque at the mid-gap radius
/// and also computes it at two nearby radii (inner and outer boundaries)
/// to assess stability of the torque estimate across the airgap thickness.
/// Returns (mid_gap_torque_nm, inner_radius_torque_nm, outer_radius_torque_nm, diagnostics).
pub fn compute_torque_at_multiple_radii(
    mesh: &TriMesh,
    fields: &[ElementField],
    stack_length_mm: f64,
    pole_count: u32,
) -> (f64, f64, f64, String) {
    // Get mid-gap contour torque (standard)
    let contour_debug =
        compute_torque_midgap_contour_debug(mesh, fields, stack_length_mm, pole_count);
    let mid_gap_torque = contour_debug.scaled_torque_nm;

    let mut ok_debugs = Vec::new();
    let mut errors = Vec::new();
    let candidate_radii = diagnostic_contour_candidate_radii(mesh);
    for radius_m in candidate_radii.iter().copied() {
        let debug = compute_torque_midgap_contour_debug_with_radius(
            mesh,
            fields,
            stack_length_mm,
            pole_count,
            radius_m,
        );
        if debug.status == "ok" {
            ok_debugs.push(debug);
        } else if let Some(error) = debug.error.as_ref() {
            errors.push(format!("@{:.3}mm: {}", debug.radius_mm, error));
        }
    }

    let mut inner_torque = 0.0;
    let mut outer_torque = 0.0;
    let diagnostics = if !ok_debugs.is_empty() {
        ok_debugs.sort_by(|a, b| {
            a.radius_mm
                .partial_cmp(&b.radius_mm)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let inner_contour_debug = ok_debugs
            .first()
            .expect("non-empty ok_debugs has first debug");
        let outer_contour_debug = ok_debugs
            .last()
            .expect("non-empty ok_debugs has last debug");
        inner_torque = inner_contour_debug.scaled_torque_nm;
        outer_torque = outer_contour_debug.scaled_torque_nm;

        format!(
            "mid_gap={:.3}Nm @ {:.3}mm, inner={:.3}Nm @ {:.3}mm, outer={:.3}Nm @ {:.3}mm, spread={:.1}% (ok_radii={}/{})",
            mid_gap_torque,
            contour_debug.radius_mm,
            inner_torque,
            inner_contour_debug.radius_mm,
            outer_torque,
            outer_contour_debug.radius_mm,
            if mid_gap_torque.abs() > 1e-9 {
                100.0 * ((outer_torque - inner_torque).abs() / mid_gap_torque.abs())
            } else {
                0.0
            },
            ok_debugs.len(),
            candidate_radii.len(),
        )
    } else {
        format!(
            "no_working_airgap_radii_for_multi_radius_validation (candidates={}, errors={})",
            candidate_radii.len(),
            errors.join(" | "),
        )
    };

    (mid_gap_torque, inner_torque, outer_torque, diagnostics)
}

/// Compute torque from a mid-gap contour at a specific radius (internal helper).
fn compute_torque_midgap_contour_debug_with_radius(
    mesh: &TriMesh,
    fields: &[ElementField],
    stack_length_mm: f64,
    pole_count: u32,
    radius_m: f64,
) -> ContourTorqueDebug {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let sample_count = contour_sample_count(mesh);

    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;

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
        airgap_triangles.push((triangle_index, tri_xy, [xmin, xmax, ymin, ymax]));
    }

    if airgap_triangles.is_empty() {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("mesh has no airgap triangles for contour torque".to_string()),
            radius_mm: radius_m * 1e3,
            sample_count: 0,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    }

    let l_stack = stack_length_mm * 1e-3;
    let dtheta = total_span_rad / sample_count as f64;
    let sample_offset = contour_sample_offset_fraction();
    let mut modeled_torque_nm = 0.0;
    let mut sampled_triangles = HashSet::new();
    let mut samples = Vec::with_capacity(sample_count);

    let nodal_b = compute_nodal_b_field(mesh, fields);

    for sample_index in 0..sample_count {
        let theta = total_span_rad * (sample_index as f64 + sample_offset) / sample_count as f64;
        let x = radius_m * theta.cos();
        let y = radius_m * theta.sin();

        let mut matched: Option<(usize, [f64; 3], [usize; 3])> = None;
        for &(triangle_index, tri_xy, bbox) in &airgap_triangles {
            let pad = 1e-9;
            if x < bbox[0] - pad || x > bbox[1] + pad || y < bbox[2] - pad || y > bbox[3] + pad {
                continue;
            }
            let Some(weights) = barycentric_weights([x, y], tri_xy) else {
                continue;
            };
            matched = Some((triangle_index, weights, mesh.triangles[triangle_index]));
            break;
        }

        let Some((triangle_index, weights, tri_nodes)) = matched else {
            return ContourTorqueDebug {
                status: "error".to_string(),
                error: Some(format!(
                    "contour sample at theta={:.3}deg and r={:.6}mm did not land inside an airgap triangle",
                    theta.to_degrees(),
                    radius_m * 1e3,
                )),
                radius_mm: radius_m * 1e3,
                sample_count,
                total_span_deg: mesh.info.total_span_deg,
                unique_triangle_count: sampled_triangles.len(),
                modeled_torque_nm,
                scale_factor,
                scaled_torque_nm: modeled_torque_nm * scale_factor,
                samples,
                per_quadrant: None,
            };
        };

        let mut bx = 0.0;
        let mut by = 0.0;
        for k in 0..3 {
            let nb = nodal_b[tri_nodes[k]];
            bx += weights[k] * nb[0];
            by += weights[k] * nb[1];
        }
        let (b_r, b_t) = cartesian_to_polar_b(bx, by, [x, y])
            .expect("contour radius should not sample the origin");
        let modeled_contribution_nm = l_stack * radius_m * radius_m * b_r * b_t * dtheta / MU_0;
        modeled_torque_nm += modeled_contribution_nm;
        sampled_triangles.insert(triangle_index);
        samples.push(ContourTorqueSample {
            sample_index,
            triangle_index,
            x_mm: x * 1e3,
            y_mm: y * 1e3,
            radius_mm: radius_m * 1e3,
            theta_mech_deg: theta.to_degrees(),
            b_r_t: b_r,
            b_t_t: b_t,
            modeled_contribution_nm,
            scaled_contribution_nm: modeled_contribution_nm * scale_factor,
        });
    }

    ContourTorqueDebug {
        status: "ok".to_string(),
        error: None,
        radius_mm: radius_m * 1e3,
        sample_count,
        total_span_deg: mesh.info.total_span_deg,
        unique_triangle_count: sampled_triangles.len(),
        modeled_torque_nm,
        scale_factor,
        scaled_torque_nm: modeled_torque_nm * scale_factor,
        samples,
        per_quadrant: None,
    }
}

fn compute_torque_midgap_contour_debug_with_radius_from_az(
    mesh: &TriMesh,
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
    radius_m: f64,
    sample_count: usize,
) -> ContourTorqueDebug {
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let scale_factor = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;
    let full_circle = (mesh.info.total_span_deg - 360.0).abs() < 1e-6;

    if !full_circle {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some(
                "A_z-derived contour torque currently requires a full 360° model".to_string(),
            ),
            radius_mm: radius_m * 1e3,
            sample_count: 0,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    }

    if sample_count == 0 || total_span_rad.abs() < 1e-12 {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("invalid contour sample count or modeled span".to_string()),
            radius_mm: radius_m * 1e3,
            sample_count,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    }

    let airgap_triangles = collect_airgap_triangle_records(mesh);
    if airgap_triangles.is_empty() {
        return ContourTorqueDebug {
            status: "error".to_string(),
            error: Some("mesh has no airgap triangles for contour torque".to_string()),
            radius_mm: radius_m * 1e3,
            sample_count: 0,
            total_span_deg: mesh.info.total_span_deg,
            unique_triangle_count: 0,
            modeled_torque_nm: 0.0,
            scale_factor,
            scaled_torque_nm: 0.0,
            samples: Vec::new(),
            per_quadrant: None,
        };
    }

    let radial_step_m = choose_az_contour_radial_step(mesh, radius_m);
    let l_stack = stack_length_mm * 1e-3;
    let dtheta = total_span_rad / sample_count as f64;
    let sample_offset = contour_sample_offset_fraction();
    let mut modeled_torque_nm = 0.0;
    let mut sampled_triangles = HashSet::new();
    let mut samples = Vec::with_capacity(sample_count);

    // Symmetry instrumentation (A_z-derived variant — this is the hot path
    // for rotor sweeps). Same shape as the B-field variant: bucket the 360
    // contour samples into 4 quadrants by mechanical angle. Any per-quadrant
    // drift in partial torque is entirely attributable to the A_z → B_r/B_t
    // finite-difference reconstruction picking up different triangles for
    // rotationally-equivalent sample points.
    let mut q_count: [usize; 4] = [0; 4];
    let mut q_first_theta_mod90: [Option<f64>; 4] = [None; 4];
    let mut q_partial_torque: [f64; 4] = [0.0; 4];

    eprintln!(
        "  contour MST (A_z-derived): radius={:.3}mm span={:.2}° npp={} scale_factor={:.4} samples={} dr={:.3}mm",
        radius_m * 1e3,
        mesh.info.total_span_deg,
        mesh.info.n_pole_pitches,
        scale_factor,
        sample_count,
        radial_step_m * 1e3,
    );

    for sample_index in 0..sample_count {
        let theta = total_span_rad * (sample_index as f64 + sample_offset) / sample_count as f64;
        let point_xy_m = [radius_m * theta.cos(), radius_m * theta.sin()];
        let Some((triangle_index, b_r, b_t)) =
            sample_contour_field_from_az(&airgap_triangles, az, point_xy_m, dtheta, radial_step_m)
        else {
            return ContourTorqueDebug {
                status: "error".to_string(),
                error: Some(format!(
                    "A_z-derived contour sample at theta={:.3}deg and r={:.6}mm could not be reconstructed",
                    theta.to_degrees(),
                    radius_m * 1e3,
                )),
                radius_mm: radius_m * 1e3,
                sample_count,
                total_span_deg: mesh.info.total_span_deg,
                unique_triangle_count: sampled_triangles.len(),
                modeled_torque_nm,
                scale_factor,
                scaled_torque_nm: modeled_torque_nm * scale_factor,
                samples,
                per_quadrant: None,
            };
        };

        let modeled_contribution_nm = l_stack * radius_m * radius_m * b_r * b_t * dtheta / MU_0;
        modeled_torque_nm += modeled_contribution_nm;
        sampled_triangles.insert(triangle_index);
        samples.push(ContourTorqueSample {
            sample_index,
            triangle_index,
            x_mm: point_xy_m[0] * 1e3,
            y_mm: point_xy_m[1] * 1e3,
            radius_mm: radius_m * 1e3,
            theta_mech_deg: theta.to_degrees(),
            b_r_t: b_r,
            b_t_t: b_t,
            modeled_contribution_nm,
            scaled_contribution_nm: modeled_contribution_nm * scale_factor,
        });

        let q = quadrant_of_angle(theta);
        q_count[q] += 1;
        if q_first_theta_mod90[q].is_none() {
            q_first_theta_mod90[q] = Some(angle_mod_quadrant(theta));
        }
        q_partial_torque[q] += modeled_contribution_nm;
    }

    // Always emit per-quadrant stats here — this path already gated on
    // `full_circle` above, so `full_circle` is true whenever we reach this
    // point.
    let per_quadrant = {
        let mut first_rads: Vec<f64> = Vec::with_capacity(4);
        for q in 0..4 {
            if let Some(a) = q_first_theta_mod90[q] {
                first_rads.push(a);
            }
        }
        let max_abs_diff_first = if first_rads.len() < 2 {
            0.0
        } else {
            let mut diff: f64 = 0.0;
            for i in 0..first_rads.len() {
                for j in (i + 1)..first_rads.len() {
                    diff = diff.max((first_rads[i] - first_rads[j]).abs());
                }
            }
            diff
        };
        let first_theta_mod90_deg: [Option<f64>; 4] = [
            q_first_theta_mod90[0].map(f64::to_degrees),
            q_first_theta_mod90[1].map(f64::to_degrees),
            q_first_theta_mod90[2].map(f64::to_degrees),
            q_first_theta_mod90[3].map(f64::to_degrees),
        ];
        let stats = PerQuadrantContourStats {
            full_circle: true,
            sample_count_per_quadrant: q_count,
            first_sample_theta_mod90_deg_per_quadrant: first_theta_mod90_deg,
            partial_torque_nm_per_quadrant: q_partial_torque,
            max_abs_diff_count: max_abs_diff4_usize(q_count),
            max_rel_diff_partial_torque: max_rel_diff4(q_partial_torque),
            max_abs_diff_first_sample_rad: max_abs_diff_first,
        };
        eprintln!(
            "    mst(A_z) per-quadrant: counts={:?} max_abs_diff_count={} max_rel_diff_partial={:.3e} max_abs_diff_first_sample_rad={:.3e}",
            stats.sample_count_per_quadrant,
            stats.max_abs_diff_count,
            stats.max_rel_diff_partial_torque,
            stats.max_abs_diff_first_sample_rad,
        );
        if assert_symmetry_enabled() {
            assert!(
                stats.max_abs_diff_count == 0,
                "mst(A_z) symmetry assert: per-quadrant sample counts differ: {:?}",
                stats.sample_count_per_quadrant,
            );
            assert!(
                stats.max_abs_diff_first_sample_rad <= 1e-12,
                "mst(A_z) symmetry assert: per-quadrant first-sample angles mod 90° differ by {:.3e} rad (deg={:?})",
                stats.max_abs_diff_first_sample_rad,
                stats.first_sample_theta_mod90_deg_per_quadrant,
            );
            assert!(
                stats.max_rel_diff_partial_torque <= 1e-6,
                "mst(A_z) symmetry assert: per-quadrant partial-torque rel-diff {:.3e} > 1e-6 (partials={:?})",
                stats.max_rel_diff_partial_torque,
                stats.partial_torque_nm_per_quadrant,
            );
        }
        Some(stats)
    };

    ContourTorqueDebug {
        status: "ok".to_string(),
        error: None,
        radius_mm: radius_m * 1e3,
        sample_count,
        total_span_deg: mesh.info.total_span_deg,
        unique_triangle_count: sampled_triangles.len(),
        modeled_torque_nm,
        scale_factor,
        scaled_torque_nm: modeled_torque_nm * scale_factor,
        samples,
        per_quadrant,
    }
}

pub(super) fn compute_torque_at_multiple_radii_from_az(
    mesh: &TriMesh,
    az: &[f64],
    stack_length_mm: f64,
    pole_count: u32,
) -> (f64, f64, f64, String) {
    let contour_debug =
        compute_torque_midgap_contour_debug_from_az(mesh, az, stack_length_mm, pole_count);
    let mid_gap_torque = contour_debug.scaled_torque_nm;

    let mut ok_debugs = Vec::new();
    let mut errors = Vec::new();
    let candidate_radii = diagnostic_contour_candidate_radii(mesh);
    for radius_m in candidate_radii.iter().copied() {
        let debug = compute_torque_midgap_contour_debug_with_radius_from_az(
            mesh,
            az,
            stack_length_mm,
            pole_count,
            radius_m,
            contour_debug.sample_count.max(90),
        );
        if debug.status == "ok" {
            ok_debugs.push(debug);
        } else if let Some(error) = debug.error.as_ref() {
            errors.push(format!("@{:.3}mm: {}", debug.radius_mm, error));
        }
    }

    let mut inner_torque = 0.0;
    let mut outer_torque = 0.0;
    let diagnostics = if !ok_debugs.is_empty() {
        ok_debugs.sort_by(|a, b| {
            a.radius_mm
                .partial_cmp(&b.radius_mm)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let inner_contour_debug = ok_debugs
            .first()
            .expect("non-empty ok_debugs has first debug");
        let outer_contour_debug = ok_debugs
            .last()
            .expect("non-empty ok_debugs has last debug");
        inner_torque = inner_contour_debug.scaled_torque_nm;
        outer_torque = outer_contour_debug.scaled_torque_nm;

        format!(
            "mid_gap={:.3}Nm @ {:.3}mm, inner={:.3}Nm @ {:.3}mm, outer={:.3}Nm @ {:.3}mm, spread={:.1}% (ok_radii={}/{})",
            mid_gap_torque,
            contour_debug.radius_mm,
            inner_torque,
            inner_contour_debug.radius_mm,
            outer_torque,
            outer_contour_debug.radius_mm,
            if mid_gap_torque.abs() > 1e-9 {
                100.0 * ((outer_torque - inner_torque).abs() / mid_gap_torque.abs())
            } else {
                0.0
            },
            ok_debugs.len(),
            candidate_radii.len(),
        )
    } else {
        format!(
            "no_working_airgap_radii_for_multi_radius_validation (candidates={}, errors={})",
            candidate_radii.len(),
            errors.join(" | "),
        )
    };

    (mid_gap_torque, inner_torque, outer_torque, diagnostics)
}
