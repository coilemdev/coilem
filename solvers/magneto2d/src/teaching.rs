//! Small solver-backed teaching fixtures that introduce field physics before a motor.

use serde::{Deserialize, Serialize};
use std::time::Instant;

use crate::assembly::{assemble_source, assemble_stiffness};
use crate::materials::{get_bh_curve, nonlinear_steel_mu_rel, MaterialProps, MU_0};
use crate::mesh::{MeshInfo, MeshSource, Region, TriMesh};
use crate::postprocess::compute_element_fields;
use crate::sparse::pcg_solve;

const DOMAIN_X_MIN_MM: f64 = -50.0;
const DOMAIN_X_MAX_MM: f64 = 50.0;
const DOMAIN_Y_MIN_MM: f64 = -34.0;
const DOMAIN_Y_MAX_MM: f64 = 34.0;
const WIRE_RADIUS_MM: f64 = 5.0;
const WIRE_PROBE_RADIUS_MM: f64 = 15.0;
const IRON_RING_INNER_RADIUS_MM: f64 = 11.0;
const IRON_RING_OUTER_RADIUS_MM: f64 = 23.0;
const IRON_RING_PROBE_RADIUS_MM: f64 = 17.0;
const IRON_SATURATION_THRESHOLD_T: f64 = 1.6;
const IRON_TOOTH_HALF_WIDTH_MM: f64 = 6.0;
const IRON_TOOTH_TIP_Y_MM: f64 = -8.0;
const IRON_TOOTH_YOKE_Y_MM: f64 = 16.0;
const IRON_TOOTH_YOKE_TOP_MM: f64 = 26.0;
const IRON_TOOTH_YOKE_SAG_MM: f64 = 1.8;
const IRON_TOOTH_RETURN_INNER_X_MM: f64 = 24.0;
const IRON_TOOTH_RETURN_OUTER_X_MM: f64 = 32.0;
const IRON_TOOTH_ROTOR_TOP_MM: f64 = -10.0;
const IRON_TOOTH_ROTOR_BOTTOM_MM: f64 = -20.0;
const IRON_TOOTH_ROTOR_SAG_MM: f64 = 1.6;
const IRON_TOOTH_SPM_MAGNET_HALF_WIDTH_MM: f64 = 9.0;
const IRON_TOOTH_SPM_MAGNET_TOP_MM: f64 = -10.0;
const IRON_TOOTH_SPM_MAGNET_BOTTOM_MM: f64 = -15.0;
const IRON_TOOTH_SPM_MAGNET_SAG_MM: f64 = IRON_TOOTH_ROTOR_SAG_MM
    * (IRON_TOOTH_SPM_MAGNET_HALF_WIDTH_MM / (IRON_TOOTH_RETURN_OUTER_X_MM + 2.0))
    * (IRON_TOOTH_SPM_MAGNET_HALF_WIDTH_MM / (IRON_TOOTH_RETURN_OUTER_X_MM + 2.0));
const IRON_TOOTH_SPM_ROTOR_TOP_MM: f64 = IRON_TOOTH_SPM_MAGNET_BOTTOM_MM;
const IRON_TOOTH_SPM_ROTOR_BOTTOM_MM: f64 = -23.0;
const IRON_TOOTH_COIL_X_MIN_MM: f64 = 9.0;
const IRON_TOOTH_COIL_X_MAX_MM: f64 = 20.0;
const IRON_TOOTH_COIL_Y_MIN_MM: f64 = -2.0;
const IRON_TOOTH_COIL_Y_MAX_MM: f64 = 13.0;
const IRON_TOOTH_COIL_TURNS: f64 = 400.0;
const FORCE_WIRE_RADIUS_MM: f64 = 4.0;
const FORCE_DEFAULT_POLE_GAP_MM: f64 = 8.0;
const FORCE_MAGNET_WIDTH_MM: f64 = 24.0;
const FORCE_MAGNET_HALF_HEIGHT_MM: f64 = 6.0;
const FORCE_TEACHING_DEPTH_MM: f64 = 10.0;
const LINEAR_CAPSTONE_MAGNET_CENTERS_MM: [f64; 4] = [-27.0, -9.0, 9.0, 27.0];
const LINEAR_CAPSTONE_MAGNET_HALF_WIDTH_MM: f64 = 7.0;
const LINEAR_CAPSTONE_MAGNET_BOTTOM_MM: f64 = -8.0;
const LINEAR_CAPSTONE_MAGNET_TOP_MM: f64 = 0.0;
const LINEAR_CAPSTONE_BACK_IRON_BOTTOM_MM: f64 = -14.0;
const LINEAR_CAPSTONE_BACK_IRON_TOP_MM: f64 = -8.0;
const LINEAR_CAPSTONE_BACK_IRON_HALF_WIDTH_MM: f64 = 39.0;
const LINEAR_CAPSTONE_WIRE_RADIUS_MM: f64 = 3.0;
const LINEAR_CAPSTONE_WINDING_TURNS: f64 = 3.0;
const ROTOR_CHASE_ROTOR_HALF_LENGTH_MM: f64 = 7.0;
const ROTOR_CHASE_ROTOR_HALF_HEIGHT_MM: f64 = 3.0;
const ROTOR_CHASE_COIL_RADIUS_MM: f64 = 3.0;
const ROTOR_CHASE_COIL_Y_MM: f64 = 10.0;
const ROTOR_CHASE_COIL_TURNS: f64 = 1008.0;
const ROTATING_FIELD_COIL_RADIUS_MM: f64 = 5.0;
const ROTATING_FIELD_COIL_OFFSET_MM: f64 = 22.0;
const ROTATING_FIELD_CENTER_PROBE_RADIUS_MM: f64 = 6.0;
const ROTATING_FIELD_DOMAIN_HALF_MM: f64 = 42.0;
const ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM: f64 = 7.0;
const ROTATING_FIELD_MOTOR_CORE_INNER_MM: f64 = 11.0;
const ROTATING_FIELD_MOTOR_CORE_OUTER_MM: f64 = 34.0;
const ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM: f64 = 5.5;
const ROTATING_FIELD_MOTOR_COIL_RADIUS_MM: f64 = 2.4;
const ROTATING_FIELD_MOTOR_COIL_CENTER_MM: f64 = 22.0;
const ROTATING_FIELD_MOTOR_COIL_SIDE_MM: f64 = 9.0;
const THREE_PHASE_MOTOR_CORE_INNER_MM: f64 = 11.0;
const THREE_PHASE_MOTOR_CORE_OUTER_MM: f64 = 35.0;
const THREE_PHASE_MOTOR_CORE_HALF_WIDTH_MM: f64 = 4.2;
const THREE_PHASE_MOTOR_COIL_RADIUS_MM: f64 = 2.1;
const THREE_PHASE_MOTOR_COIL_CENTER_MM: f64 = 23.0;
const THREE_PHASE_MOTOR_COIL_SIDE_MM: f64 = 7.2;

fn is_rotating_field_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "rotating_field" | "rotating_field_phase_a" | "rotating_field_phase_b"
    )
}

fn is_rotating_field_motor_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "rotating_field_motor" | "rotating_field_motor_stator" | "rotating_field_motor_rotor"
    )
}

fn is_three_phase_motor_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "three_phase_motor"
            | "three_phase_motor_stator"
            | "three_phase_motor_rotor"
            | "three_phase_motor_phase_a"
            | "three_phase_motor_phase_b"
            | "three_phase_motor_phase_c"
            | "three_phase_motor_open_c"
    )
}

fn is_any_rotating_field_fixture(fixture: &str) -> bool {
    is_rotating_field_fixture(fixture)
        || is_rotating_field_motor_fixture(fixture)
        || is_three_phase_motor_fixture(fixture)
}

fn is_iron_saturation_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "iron_saturation" | "iron_saturation_tooth" | "iron_saturation_spm_tooth"
    )
}

fn teaching_iron_grade() -> &'static str {
    "M350-50A"
}

fn is_iron_tooth_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "iron_saturation_tooth" | "iron_saturation_spm_tooth"
    )
}

fn in_iron_tooth_curved_band(
    x_mm: f64,
    y_mm: f64,
    half_width_mm: f64,
    lower_y_mm: f64,
    upper_y_mm: f64,
    sag_mm: f64,
) -> bool {
    if x_mm.abs() > half_width_mm {
        return false;
    }
    let normalized_x = x_mm / half_width_mm;
    let curve_offset = sag_mm * normalized_x * normalized_x;
    (lower_y_mm - curve_offset..=upper_y_mm - curve_offset).contains(&y_mm)
}

fn is_rotor_chase_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "rotor_chase_stator"
            | "rotor_chase_rotor"
            | "rotor_chase_combined"
            | "rotor_chase_coil_stator"
            | "rotor_chase_coil_rotor"
            | "rotor_chase_coil_combined"
    )
}

fn is_rotor_chase_coil_fixture(fixture: &str) -> bool {
    matches!(
        fixture,
        "rotor_chase_coil_stator" | "rotor_chase_coil_rotor" | "rotor_chase_coil_combined"
    )
}

#[derive(Debug, Clone, Deserialize)]
pub struct TeachingRequest {
    #[serde(default = "default_fixture")]
    pub fixture: String,
    #[serde(default)]
    pub steel_return: bool,
    #[serde(default = "default_steel_shape")]
    pub steel_shape: String,
    #[serde(default = "default_steel_center_x_mm")]
    pub steel_center_x_mm: f64,
    #[serde(default)]
    pub steel_center_y_mm: f64,
    #[serde(default)]
    pub magnet_center_x_mm: f64,
    #[serde(default)]
    pub magnet_center_y_mm: f64,
    #[serde(default)]
    pub magnet_angle_deg: f64,
    /// Lesson 1's optional second magnet. Off by default so every existing
    /// single-magnet request keeps its exact geometry and field.
    #[serde(default)]
    pub magnet2_enabled: bool,
    #[serde(default = "default_magnet2_center_x_mm")]
    pub magnet2_center_x_mm: f64,
    #[serde(default)]
    pub magnet2_center_y_mm: f64,
    #[serde(default = "default_magnet2_angle_deg")]
    pub magnet2_angle_deg: f64,
    #[serde(default)]
    pub steel_angle_deg: f64,
    #[serde(default)]
    pub wire_current_a: f64,
    /// Chapter 1 capstone magnet directions. +1 points the N face toward the
    /// moving winding (+Y); -1 reverses that magnet. Other fixtures ignore it.
    #[serde(default = "default_capstone_magnet_orientations")]
    pub capstone_magnet_orientations: Vec<i8>,
    /// Center-to-center pitch between adjacent capstone winding sections.
    #[serde(default = "default_capstone_winding_spacing_mm")]
    pub capstone_winding_spacing_mm: f64,
    #[serde(default = "default_mesh_density")]
    pub mesh_density: String,
    #[serde(default)]
    pub imported_mesh: Option<TeachingMeshInput>,
    #[serde(default = "default_true")]
    pub solve: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TeachingMeshInput {
    pub nodes_mm: Vec<[f64; 2]>,
    pub triangles: Vec<[usize; 3]>,
    pub boundary_nodes: Vec<usize>,
    pub source_detail: String,
    #[serde(default)]
    pub corner_refinement: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct TeachingConfigSummary {
    pub topology: String,
    pub slots: usize,
    pub poles: usize,
    pub stator_od_mm: f64,
    pub rotor_od_mm: f64,
    pub magnet_thickness_mm: f64,
    pub stack_length_mm: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TeachingMeshInfo {
    pub num_nodes: usize,
    pub num_triangles: usize,
    pub pole_pitch_deg: f64,
    pub n_pole_pitches: usize,
    pub total_span_deg: f64,
    pub mesh_source_detail: String,
    pub mesh_source: String,
    pub corner_refinement: bool,
    pub mesh_density: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct TeachingMetrics {
    pub working_gap_mean_b_t: f64,
    pub outside_field_mean_b_t: f64,
    pub return_path_mean_b_t: Option<f64>,
    pub peak_b_t: f64,
    pub probe_tangential_b_t: Option<f64>,
    pub probe_radius_mm: Option<f64>,
    pub iron_mean_b_t: Option<f64>,
    pub iron_mean_h_a_per_m: Option<f64>,
    pub iron_effective_mu_rel: Option<f64>,
    pub iron_saturated_fraction: Option<f64>,
    pub iron_saturation_threshold_t: Option<f64>,
    pub nonlinear_iterations: Option<usize>,
    pub tooth_mean_b_t: Option<f64>,
    pub tooth_tip_mean_b_t: Option<f64>,
    pub tooth_saturated_fraction: Option<f64>,
    pub airgap_mean_b_t: Option<f64>,
    pub airgap_flux_per_depth_wb_per_m: Option<f64>,
    pub wire_mean_bx_t: Option<f64>,
    pub wire_mean_by_t: Option<f64>,
    pub wire_force_x_n: Option<f64>,
    pub wire_force_y_n: Option<f64>,
    pub wire_force_magnitude_n: Option<f64>,
    pub wire_force_bil_n: Option<f64>,
    pub teaching_depth_mm: Option<f64>,
    pub center_bx_t: Option<f64>,
    pub center_by_t: Option<f64>,
    pub center_b_t: Option<f64>,
    pub center_field_angle_deg: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TeachingBhPoint {
    pub b_t: f64,
    pub h_a_per_m: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TeachingReport {
    pub schema_version: String,
    pub fixture: String,
    pub steel_return: bool,
    pub steel_shape: String,
    pub steel_center_x_mm: f64,
    pub steel_center_y_mm: f64,
    pub magnet_center_x_mm: f64,
    pub magnet_center_y_mm: f64,
    pub magnet_angle_deg: f64,
    pub magnet2_enabled: bool,
    pub magnet2_center_x_mm: f64,
    pub magnet2_center_y_mm: f64,
    pub magnet2_angle_deg: f64,
    pub steel_angle_deg: f64,
    pub wire_current_a: f64,
    pub solved: bool,
    pub config_summary: TeachingConfigSummary,
    pub mesh_info: TeachingMeshInfo,
    pub nodes_mm: Vec<[f64; 2]>,
    pub triangles: Vec<[usize; 3]>,
    pub regions: Vec<String>,
    pub n_pole_pitches: usize,
    pub total_span_deg: f64,
    pub generation_time_ms: u128,
    pub az_nodal: Vec<f64>,
    pub element_b_mag_t: Vec<f64>,
    pub element_bx_t: Vec<f64>,
    pub element_by_t: Vec<f64>,
    pub metrics: Option<TeachingMetrics>,
    pub bh_curve: Option<Vec<TeachingBhPoint>>,
}

fn default_fixture() -> String {
    "follow_flux".to_string()
}

fn default_mesh_density() -> String {
    "normal".to_string()
}

/// The second magnet starts clear of the first (18 mm half-length each, so 44 mm
/// of separation leaves an 8 mm air gap).
fn default_magnet2_center_x_mm() -> f64 {
    44.0
}

/// Parallel magnetization, which is the ATTRACTING arrangement for two magnets
/// laid end to end: magnet 1's north faces magnet 2's south, so the pair forms one
/// continuous flux path. Anti-parallel (180 deg) is the repelling case — verified
/// by follow_flux_second_magnet_adds_its_own_poles_and_couples_the_pair, which
/// measures 0.57 T across the gap parallel against 0.19 T anti-parallel.
fn default_magnet2_angle_deg() -> f64 {
    0.0
}

fn default_steel_shape() -> String {
    "bar".to_string()
}

fn default_steel_center_x_mm() -> f64 {
    28.0
}

fn default_true() -> bool {
    true
}

fn default_capstone_magnet_orientations() -> Vec<i8> {
    vec![1, 1, 1, 1]
}

fn default_capstone_winding_spacing_mm() -> f64 {
    18.0
}

fn linear_capstone_winding_centers_mm(spacing_mm: f64) -> [f64; 4] {
    [
        -1.5 * spacing_mm,
        -0.5 * spacing_mm,
        0.5 * spacing_mm,
        1.5 * spacing_mm,
    ]
}

fn density_step_mm(mesh_density: &str) -> Result<f64, String> {
    match mesh_density.trim().to_ascii_lowercase().as_str() {
        "coarse" => Ok(4.0),
        "normal" | "standard" => Ok(2.0),
        "fine" => Ok(1.0),
        other => Err(format!(
            "unknown teaching mesh density '{other}' (expected coarse|normal|fine)"
        )),
    }
}

fn in_rect(x_mm: f64, y_mm: f64, x0: f64, x1: f64, y0: f64, y1: f64) -> bool {
    x_mm >= x0 && x_mm <= x1 && y_mm >= y0 && y_mm <= y1
}

fn to_local(
    x_mm: f64,
    y_mm: f64,
    center_x_mm: f64,
    center_y_mm: f64,
    angle_deg: f64,
) -> (f64, f64) {
    let angle_rad = angle_deg.to_radians();
    let cos_angle = angle_rad.cos();
    let sin_angle = angle_rad.sin();
    let dx = x_mm - center_x_mm;
    let dy = y_mm - center_y_mm;
    (
        cos_angle * dx + sin_angle * dy,
        -sin_angle * dx + cos_angle * dy,
    )
}

fn rotated_rect_extents(half_width_mm: f64, half_height_mm: f64, angle_deg: f64) -> (f64, f64) {
    let angle_rad = angle_deg.to_radians();
    let cos_angle = angle_rad.cos().abs();
    let sin_angle = angle_rad.sin().abs();
    (
        cos_angle * half_width_mm + sin_angle * half_height_mm,
        sin_angle * half_width_mm + cos_angle * half_height_mm,
    )
}

#[derive(Clone, Copy)]
struct OrientedRect {
    center_x_mm: f64,
    center_y_mm: f64,
    half_width_mm: f64,
    half_height_mm: f64,
    angle_deg: f64,
}

fn oriented_rectangles_overlap(
    first: OrientedRect,
    second: OrientedRect,
    clearance_mm: f64,
) -> bool {
    let first_angle = first.angle_deg.to_radians();
    let second_angle = second.angle_deg.to_radians();
    let first_axes = [
        [first_angle.cos(), first_angle.sin()],
        [-first_angle.sin(), first_angle.cos()],
    ];
    let second_axes = [
        [second_angle.cos(), second_angle.sin()],
        [-second_angle.sin(), second_angle.cos()],
    ];
    let center_delta = [
        second.center_x_mm - first.center_x_mm,
        second.center_y_mm - first.center_y_mm,
    ];

    first_axes.into_iter().chain(second_axes).all(|axis| {
        let center_distance = (center_delta[0] * axis[0] + center_delta[1] * axis[1]).abs();
        let first_radius = first.half_width_mm
            * (first_axes[0][0] * axis[0] + first_axes[0][1] * axis[1]).abs()
            + first.half_height_mm
                * (first_axes[1][0] * axis[0] + first_axes[1][1] * axis[1]).abs();
        let second_radius = second.half_width_mm
            * (second_axes[0][0] * axis[0] + second_axes[0][1] * axis[1]).abs()
            + second.half_height_mm
                * (second_axes[1][0] * axis[0] + second_axes[1][1] * axis[1]).abs();
        center_distance < first_radius + second_radius + clearance_mm
    })
}

fn steel_shape_dimensions(shape: &str) -> Result<(f64, f64), String> {
    match shape {
        "bar" => Ok((8.0, 28.0)),
        "plate" => Ok((28.0, 8.0)),
        "puck" => Ok((16.0, 16.0)),
        "circuit" => Ok((68.0, 26.0)),
        other => Err(format!(
            "unknown steel shape '{other}' (expected bar|plate|puck|circuit)"
        )),
    }
}

fn is_steel_shape(
    x_mm: f64,
    y_mm: f64,
    shape: &str,
    center_x_mm: f64,
    center_y_mm: f64,
    angle_deg: f64,
) -> bool {
    let (local_x, local_y) = to_local(x_mm, y_mm, center_x_mm, center_y_mm, angle_deg);
    match shape {
        "bar" => local_x.abs() <= 4.0 && local_y.abs() <= 14.0,
        "plate" => local_x.abs() <= 14.0 && local_y.abs() <= 4.0,
        "puck" => local_x * local_x + local_y * local_y <= 8.0 * 8.0,
        // For the circuit fixture, center_x_mm carries the adjustable gap.
        // The three rectangles form an inverted U around the bar magnet.
        "circuit" => {
            let gap_mm = center_x_mm;
            let outer_x_mm = 26.0 + gap_mm;
            let inner_x_mm = 18.0 + gap_mm;
            let in_left_leg = in_rect(x_mm, y_mm, -outer_x_mm, -inner_x_mm, -6.0, 20.0);
            let in_right_leg = in_rect(x_mm, y_mm, inner_x_mm, outer_x_mm, -6.0, 20.0);
            let in_top_bar = in_rect(x_mm, y_mm, -outer_x_mm, outer_x_mm, 12.0, 20.0);
            in_left_leg || in_right_leg || in_top_bar
        }
        _ => false,
    }
}

fn validate_fixture_placement(
    shape: &str,
    steel_center_x_mm: f64,
    steel_center_y_mm: f64,
    magnet_center_x_mm: f64,
    magnet_center_y_mm: f64,
    magnet_angle_deg: f64,
    steel_angle_deg: f64,
) -> Result<(), String> {
    if shape == "circuit" {
        if !(0.5..=8.0).contains(&steel_center_x_mm) {
            return Err("magnetic-circuit airgap must be between 0.5 and 8.0 mm".to_string());
        }
        if magnet_center_x_mm.abs() > 1.0e-9
            || magnet_center_y_mm.abs() > 1.0e-9
            || magnet_angle_deg.abs() > 1.0e-9
        {
            return Err(
                "magnetic-circuit fixture keeps the magnet centered and horizontal".to_string(),
            );
        }
        return Ok(());
    }

    let (magnet_extent_x, magnet_extent_y) = rotated_rect_extents(18.0, 6.0, magnet_angle_deg);
    if magnet_center_x_mm.abs() + magnet_extent_x > DOMAIN_X_MAX_MM - 2.0
        || magnet_center_y_mm.abs() + magnet_extent_y > DOMAIN_Y_MAX_MM - 2.0
    {
        return Err("permanent magnet must remain inside the field domain".to_string());
    }

    let (width_mm, height_mm) = steel_shape_dimensions(shape)?;
    let (steel_extent_x, steel_extent_y) = if shape == "puck" {
        (8.0, 8.0)
    } else {
        rotated_rect_extents(width_mm / 2.0, height_mm / 2.0, steel_angle_deg)
    };
    if steel_center_x_mm.abs() + steel_extent_x > DOMAIN_X_MAX_MM - 2.0
        || steel_center_y_mm.abs() + steel_extent_y > DOMAIN_Y_MAX_MM - 2.0
    {
        return Err("steel object must remain inside the field domain".to_string());
    }

    let overlaps_magnet = if shape == "puck" {
        let (local_x, local_y) = to_local(
            steel_center_x_mm,
            steel_center_y_mm,
            magnet_center_x_mm,
            magnet_center_y_mm,
            magnet_angle_deg,
        );
        let dx = (local_x.abs() - 18.0).max(0.0);
        let dy = (local_y.abs() - 6.0).max(0.0);
        dx.hypot(dy) < 8.5
    } else {
        oriented_rectangles_overlap(
            OrientedRect {
                center_x_mm: magnet_center_x_mm,
                center_y_mm: magnet_center_y_mm,
                half_width_mm: 18.0,
                half_height_mm: 6.0,
                angle_deg: magnet_angle_deg,
            },
            OrientedRect {
                center_x_mm: steel_center_x_mm,
                center_y_mm: steel_center_y_mm,
                half_width_mm: width_mm / 2.0,
                half_height_mm: height_mm / 2.0,
                angle_deg: steel_angle_deg,
            },
            0.5,
        )
    };
    if overlaps_magnet {
        return Err("steel object must not overlap the permanent magnet".to_string());
    }
    Ok(())
}

fn build_follow_flux_mesh(
    fixture: &str,
    mesh_density: &str,
    steel_return: bool,
    steel_shape: &str,
    steel_center_x_mm: f64,
    steel_center_y_mm: f64,
    magnet_center_x_mm: f64,
    magnet_center_y_mm: f64,
    magnet_angle_deg: f64,
    magnet2_enabled: bool,
    magnet2_center_x_mm: f64,
    magnet2_center_y_mm: f64,
    magnet2_angle_deg: f64,
    steel_angle_deg: f64,
    wire_current_a: f64,
    capstone_magnet_orientations: &[i8],
    capstone_winding_spacing_mm: f64,
    imported_mesh: Option<&TeachingMeshInput>,
) -> Result<(TriMesh, Vec<MaterialProps>, Vec<f64>, Vec<String>), String> {
    let step_mm = density_step_mm(mesh_density)?;
    let is_rotating_field_fixture = is_rotating_field_fixture(fixture);
    let is_rotating_field_motor = is_rotating_field_motor_fixture(fixture);
    let is_three_phase_motor = is_three_phase_motor_fixture(fixture);
    let (nodes, triangles, boundary_nodes, angular_divisions, radial_rings, mesh_source) =
        if let Some(imported) = imported_mesh {
            if imported.nodes_mm.len() < 3 || imported.triangles.is_empty() {
                return Err("imported teaching mesh is empty".to_string());
            }
            if imported.boundary_nodes.is_empty() {
                return Err("imported teaching mesh has no outer boundary nodes".to_string());
            }
            if imported
                .nodes_mm
                .iter()
                .flatten()
                .any(|coordinate| !coordinate.is_finite())
            {
                return Err("imported teaching mesh contains non-finite coordinates".to_string());
            }
            if imported
                .triangles
                .iter()
                .flatten()
                .any(|&node| node >= imported.nodes_mm.len())
                || imported
                    .boundary_nodes
                    .iter()
                    .any(|&node| node >= imported.nodes_mm.len())
            {
                return Err("imported teaching mesh references an unknown node".to_string());
            }
            (
                imported
                    .nodes_mm
                    .iter()
                    .map(|node| [node[0] * 1.0e-3, node[1] * 1.0e-3])
                    .collect(),
                imported.triangles.clone(),
                imported.boundary_nodes.clone(),
                0,
                0,
                MeshSource::Gmsh,
            )
        } else {
            // Standalone Rust tests retain this deterministic fallback. The lesson API
            // always supplies the Gmsh mesh above.
            let (x_min_mm, x_max_mm, y_min_mm, y_max_mm) =
                if is_rotating_field_fixture || is_rotating_field_motor || is_three_phase_motor {
                    (
                        -ROTATING_FIELD_DOMAIN_HALF_MM,
                        ROTATING_FIELD_DOMAIN_HALF_MM,
                        -ROTATING_FIELD_DOMAIN_HALF_MM,
                        ROTATING_FIELD_DOMAIN_HALF_MM,
                    )
                } else {
                    (
                        DOMAIN_X_MIN_MM,
                        DOMAIN_X_MAX_MM,
                        DOMAIN_Y_MIN_MM,
                        DOMAIN_Y_MAX_MM,
                    )
                };
            let nx = ((x_max_mm - x_min_mm) / step_mm).round() as usize;
            let ny = ((y_max_mm - y_min_mm) / step_mm).round() as usize;
            let node_index = |ix: usize, iy: usize| iy * (nx + 1) + ix;
            let mut nodes = Vec::with_capacity((nx + 1) * (ny + 1));
            for iy in 0..=ny {
                let y_mm = y_min_mm + iy as f64 * step_mm;
                for ix in 0..=nx {
                    let x_mm = x_min_mm + ix as f64 * step_mm;
                    nodes.push([x_mm * 1.0e-3, y_mm * 1.0e-3]);
                }
            }
            let mut triangles = Vec::with_capacity(nx * ny * 2);
            for iy in 0..ny {
                for ix in 0..nx {
                    let a = node_index(ix, iy);
                    let b = node_index(ix + 1, iy);
                    let c = node_index(ix + 1, iy + 1);
                    let d = node_index(ix, iy + 1);
                    triangles.push([a, b, c]);
                    triangles.push([a, c, d]);
                }
            }
            let mut boundary_nodes = Vec::with_capacity(2 * (nx + ny));
            for ix in 0..=nx {
                boundary_nodes.push(node_index(ix, 0));
                boundary_nodes.push(node_index(ix, ny));
            }
            for iy in 1..ny {
                boundary_nodes.push(node_index(0, iy));
                boundary_nodes.push(node_index(nx, iy));
            }
            (nodes, triangles, boundary_nodes, nx, ny, MeshSource::Native)
        };

    let mut regions = Vec::with_capacity(triangles.len());
    let mut materials = Vec::with_capacity(triangles.len());
    let mut current_densities = Vec::with_capacity(triangles.len());
    let mut region_labels = Vec::with_capacity(triangles.len());
    let is_force_wire_fixture = fixture == "current_force_wire";
    let is_force_fixture = fixture == "current_force" || is_force_wire_fixture;
    let is_linear_capstone = fixture == "linear_motor_capstone";
    let is_rotor_chase = is_rotor_chase_fixture(fixture);
    let is_rotor_chase_coil = is_rotor_chase_coil_fixture(fixture);
    let rotating_motor_stator_enabled = fixture != "rotating_field_motor_rotor";
    let rotating_motor_rotor_enabled = fixture != "rotating_field_motor_stator";
    let three_phase_stator_enabled = fixture != "three_phase_motor_rotor";
    let three_phase_rotor_enabled = matches!(
        fixture,
        "three_phase_motor" | "three_phase_motor_rotor" | "three_phase_motor_open_c"
    );
    let rotor_source_enabled = !matches!(fixture, "rotor_chase_stator" | "rotor_chase_coil_stator");
    let stator_source_enabled = !matches!(fixture, "rotor_chase_rotor" | "rotor_chase_coil_rotor");
    let rotor_chase_coil_current_a = if stator_source_enabled {
        wire_current_a
    } else {
        0.0
    };
    let electrical_angle_rad = if is_rotating_field_motor || is_three_phase_motor {
        steel_angle_deg.to_radians()
    } else {
        magnet_angle_deg.to_radians()
    };
    let quadrature_phase_a_current_a = wire_current_a * electrical_angle_rad.cos();
    let quadrature_phase_b_current_a = wire_current_a * electrical_angle_rad.sin();
    let phase_a_current_a = if fixture == "rotating_field_phase_b"
        || (is_rotating_field_motor && !rotating_motor_stator_enabled)
    {
        0.0
    } else {
        quadrature_phase_a_current_a
    };
    let phase_b_current_a = if fixture == "rotating_field_phase_a"
        || (is_rotating_field_motor && !rotating_motor_stator_enabled)
    {
        0.0
    } else {
        quadrature_phase_b_current_a
    };
    let three_phase_a_base_a = wire_current_a * electrical_angle_rad.cos();
    let three_phase_b_base_a =
        wire_current_a * (electrical_angle_rad - 2.0 * std::f64::consts::PI / 3.0).cos();
    let three_phase_c_base_a =
        wire_current_a * (electrical_angle_rad + 2.0 * std::f64::consts::PI / 3.0).cos();
    let open_c_phase_a_current_a = wire_current_a * electrical_angle_rad.cos();
    let open_c_phase_b_current_a = -open_c_phase_a_current_a;
    let three_phase_a_current_a = if !three_phase_stator_enabled
        || matches!(
            fixture,
            "three_phase_motor_phase_b" | "three_phase_motor_phase_c"
        ) {
        0.0
    } else if fixture == "three_phase_motor_open_c" {
        open_c_phase_a_current_a
    } else {
        three_phase_a_base_a
    };
    let three_phase_b_current_a = if !three_phase_stator_enabled
        || matches!(
            fixture,
            "three_phase_motor_phase_a" | "three_phase_motor_phase_c"
        ) {
        0.0
    } else if fixture == "three_phase_motor_open_c" {
        open_c_phase_b_current_a
    } else {
        three_phase_b_base_a
    };
    let three_phase_c_current_a = if !three_phase_stator_enabled
        || matches!(
            fixture,
            "three_phase_motor_phase_a" | "three_phase_motor_phase_b" | "three_phase_motor_open_c"
        ) {
        0.0
    } else {
        three_phase_c_base_a
    };
    let rotating_coil_area_m2 =
        std::f64::consts::PI * (ROTATING_FIELD_COIL_RADIUS_MM * 1.0e-3).powi(2);
    let rotor_chase_coil_area_m2 =
        std::f64::consts::PI * (ROTOR_CHASE_COIL_RADIUS_MM * 1.0e-3).powi(2);
    let rotating_motor_coil_area_m2 =
        std::f64::consts::PI * (ROTATING_FIELD_MOTOR_COIL_RADIUS_MM * 1.0e-3).powi(2);
    let three_phase_motor_coil_area_m2 =
        std::f64::consts::PI * (THREE_PHASE_MOTOR_COIL_RADIUS_MM * 1.0e-3).powi(2);
    let force_pole_gap_mm = if (is_force_fixture || is_rotor_chase) && steel_center_x_mm > 0.0 {
        steel_center_x_mm
    } else {
        FORCE_DEFAULT_POLE_GAP_MM
    };
    let force_magnet_inner_x_mm = if is_rotor_chase {
        ROTOR_CHASE_ROTOR_HALF_LENGTH_MM + force_pole_gap_mm
    } else {
        FORCE_WIRE_RADIUS_MM + force_pole_gap_mm
    };
    let force_magnet_outer_x_mm = force_magnet_inner_x_mm + FORCE_MAGNET_WIDTH_MM;
    let rotor_chase_coil_x_mm = 0.5 * (force_magnet_inner_x_mm + force_magnet_outer_x_mm);
    let capstone_gap_mm = if is_linear_capstone && steel_center_x_mm > 0.0 {
        steel_center_x_mm
    } else {
        8.0
    };
    let capstone_wire_center_y_mm =
        LINEAR_CAPSTONE_MAGNET_TOP_MM + capstone_gap_mm + LINEAR_CAPSTONE_WIRE_RADIUS_MM;
    let capstone_wire_area_m2 =
        std::f64::consts::PI * (LINEAR_CAPSTONE_WIRE_RADIUS_MM * 1.0e-3).powi(2);
    for triangle in &triangles {
        let x_mm = triangle.iter().map(|&index| nodes[index][0]).sum::<f64>() / 3.0 * 1.0e3;
        let y_mm = triangle.iter().map(|&index| nodes[index][1]).sum::<f64>() / 3.0 * 1.0e3;

        let (magnet_local_x, magnet_local_y) = to_local(
            x_mm,
            y_mm,
            magnet_center_x_mm,
            magnet_center_y_mm,
            magnet_angle_deg,
        );
        let (magnet2_local_x, magnet2_local_y) = to_local(
            x_mm,
            y_mm,
            magnet2_center_x_mm,
            magnet2_center_y_mm,
            magnet2_angle_deg,
        );
        let radius_mm = x_mm.hypot(y_mm);
        let is_current_fixture = fixture == "current_wire" || is_iron_saturation_fixture(fixture);
        let iron_tooth_coil = if is_iron_tooth_fixture(fixture) {
            if in_rect(
                x_mm,
                y_mm,
                -IRON_TOOTH_COIL_X_MAX_MM,
                -IRON_TOOTH_COIL_X_MIN_MM,
                IRON_TOOTH_COIL_Y_MIN_MM,
                IRON_TOOTH_COIL_Y_MAX_MM,
            ) {
                Some(("tooth_coil_out", wire_current_a))
            } else if in_rect(
                x_mm,
                y_mm,
                IRON_TOOTH_COIL_X_MIN_MM,
                IRON_TOOTH_COIL_X_MAX_MM,
                IRON_TOOTH_COIL_Y_MIN_MM,
                IRON_TOOTH_COIL_Y_MAX_MM,
            ) {
                Some(("tooth_coil_in", -wire_current_a))
            } else {
                None
            }
        } else {
            None
        };
        let iron_tooth_spm_magnet = fixture == "iron_saturation_spm_tooth"
            && in_iron_tooth_curved_band(
                x_mm,
                y_mm,
                IRON_TOOTH_SPM_MAGNET_HALF_WIDTH_MM,
                IRON_TOOTH_SPM_MAGNET_BOTTOM_MM,
                IRON_TOOTH_SPM_MAGNET_TOP_MM,
                IRON_TOOTH_SPM_MAGNET_SAG_MM,
            );
        let iron_tooth_region = if is_iron_tooth_fixture(fixture) {
            if in_rect(
                x_mm,
                y_mm,
                -IRON_TOOTH_HALF_WIDTH_MM,
                IRON_TOOTH_HALF_WIDTH_MM,
                IRON_TOOTH_TIP_Y_MM,
                IRON_TOOTH_YOKE_Y_MM,
            ) {
                Some("iron_tooth")
            } else if in_iron_tooth_curved_band(
                x_mm,
                y_mm,
                IRON_TOOTH_RETURN_OUTER_X_MM,
                IRON_TOOTH_YOKE_Y_MM,
                IRON_TOOTH_YOKE_TOP_MM,
                IRON_TOOTH_YOKE_SAG_MM,
            ) {
                Some("iron_yoke")
            } else if in_rect(
                x_mm,
                y_mm,
                -IRON_TOOTH_RETURN_OUTER_X_MM,
                -IRON_TOOTH_RETURN_INNER_X_MM,
                IRON_TOOTH_TIP_Y_MM,
                IRON_TOOTH_YOKE_Y_MM,
            ) || in_rect(
                x_mm,
                y_mm,
                IRON_TOOTH_RETURN_INNER_X_MM,
                IRON_TOOTH_RETURN_OUTER_X_MM,
                IRON_TOOTH_TIP_Y_MM,
                IRON_TOOTH_YOKE_Y_MM,
            ) {
                Some("iron_return_tooth")
            } else if fixture == "iron_saturation_spm_tooth"
                && in_iron_tooth_curved_band(
                    x_mm,
                    y_mm,
                    IRON_TOOTH_RETURN_OUTER_X_MM + 2.0,
                    IRON_TOOTH_SPM_ROTOR_BOTTOM_MM,
                    IRON_TOOTH_SPM_ROTOR_TOP_MM,
                    IRON_TOOTH_ROTOR_SAG_MM,
                )
            {
                Some("iron_rotor")
            } else if fixture == "iron_saturation_tooth"
                && in_iron_tooth_curved_band(
                    x_mm,
                    y_mm,
                    IRON_TOOTH_RETURN_OUTER_X_MM + 2.0,
                    IRON_TOOTH_ROTOR_BOTTOM_MM,
                    IRON_TOOTH_ROTOR_TOP_MM,
                    IRON_TOOTH_ROTOR_SAG_MM,
                )
            {
                Some("iron_rotor")
            } else {
                None
            }
        } else {
            None
        };
        let three_phase_motor_coil = if is_three_phase_motor {
            let phases = [
                ("a", 0.0_f64, three_phase_a_current_a),
                ("b", 120.0_f64, three_phase_b_current_a),
                ("c", 240.0_f64, three_phase_c_current_a),
            ];
            let mut match_coil = None;
            'phase: for (phase, axis_deg, phase_current_a) in phases {
                let axis_rad = axis_deg.to_radians();
                let axis_x = axis_rad.cos();
                let axis_y = axis_rad.sin();
                let normal_x = -axis_y;
                let normal_y = axis_x;
                for pole_sign in [-1.0_f64, 1.0_f64] {
                    for side_sign in [-1.0_f64, 1.0_f64] {
                        let center_x_mm = pole_sign * THREE_PHASE_MOTOR_COIL_CENTER_MM * axis_x
                            + side_sign * THREE_PHASE_MOTOR_COIL_SIDE_MM * normal_x;
                        let center_y_mm = pole_sign * THREE_PHASE_MOTOR_COIL_CENTER_MM * axis_y
                            + side_sign * THREE_PHASE_MOTOR_COIL_SIDE_MM * normal_y;
                        if (x_mm - center_x_mm).hypot(y_mm - center_y_mm)
                            <= THREE_PHASE_MOTOR_COIL_RADIUS_MM
                        {
                            let pole = if pole_sign > 0.0 {
                                "positive"
                            } else {
                                "negative"
                            };
                            let side = if side_sign > 0.0 {
                                "positive"
                            } else {
                                "negative"
                            };
                            match_coil = Some((
                                format!("phase_{phase}_{pole}_{side}"),
                                side_sign * phase_current_a,
                            ));
                            break 'phase;
                        }
                    }
                }
            }
            match_coil
        } else {
            None
        };
        let three_phase_motor_core = if is_three_phase_motor {
            [0.0_f64, 120.0_f64, 240.0_f64].into_iter().any(|axis_deg| {
                let axis_rad = axis_deg.to_radians();
                let axial_mm = x_mm * axis_rad.cos() + y_mm * axis_rad.sin();
                let transverse_mm = -x_mm * axis_rad.sin() + y_mm * axis_rad.cos();
                (THREE_PHASE_MOTOR_CORE_INNER_MM..=THREE_PHASE_MOTOR_CORE_OUTER_MM)
                    .contains(&axial_mm.abs())
                    && transverse_mm.abs() <= THREE_PHASE_MOTOR_CORE_HALF_WIDTH_MM
            })
        } else {
            false
        };
        let rotating_motor_coil = if is_rotating_field_motor {
            [
                (
                    "phase_a_left_top",
                    -ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    phase_a_current_a,
                ),
                (
                    "phase_a_left_bottom",
                    -ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    -ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    -phase_a_current_a,
                ),
                (
                    "phase_a_right_top",
                    ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    phase_a_current_a,
                ),
                (
                    "phase_a_right_bottom",
                    ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    -ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    -phase_a_current_a,
                ),
                (
                    "phase_b_top_left",
                    -ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    phase_b_current_a,
                ),
                (
                    "phase_b_top_right",
                    ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    -phase_b_current_a,
                ),
                (
                    "phase_b_bottom_left",
                    -ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    -ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    phase_b_current_a,
                ),
                (
                    "phase_b_bottom_right",
                    ROTATING_FIELD_MOTOR_COIL_SIDE_MM,
                    -ROTATING_FIELD_MOTOR_COIL_CENTER_MM,
                    -phase_b_current_a,
                ),
            ]
            .into_iter()
            .find(|(_, center_x_mm, center_y_mm, _)| {
                (x_mm - center_x_mm).hypot(y_mm - center_y_mm)
                    <= ROTATING_FIELD_MOTOR_COIL_RADIUS_MM
            })
        } else {
            None
        };
        let rotating_coil = if is_rotating_field_fixture {
            [
                (
                    "phase_a_positive",
                    0.0,
                    ROTATING_FIELD_COIL_OFFSET_MM,
                    phase_a_current_a,
                ),
                (
                    "phase_a_negative",
                    0.0,
                    -ROTATING_FIELD_COIL_OFFSET_MM,
                    -phase_a_current_a,
                ),
                (
                    "phase_b_positive",
                    -ROTATING_FIELD_COIL_OFFSET_MM,
                    0.0,
                    phase_b_current_a,
                ),
                (
                    "phase_b_negative",
                    ROTATING_FIELD_COIL_OFFSET_MM,
                    0.0,
                    -phase_b_current_a,
                ),
            ]
            .into_iter()
            .find(|(_, center_x_mm, center_y_mm, _)| {
                (x_mm - center_x_mm).hypot(y_mm - center_y_mm) <= ROTATING_FIELD_COIL_RADIUS_MM
            })
        } else {
            None
        };
        let capstone_winding = if is_linear_capstone {
            linear_capstone_winding_centers_mm(capstone_winding_spacing_mm)
                .iter()
                .enumerate()
                .find(|(_, center_x_mm)| {
                    (x_mm - **center_x_mm).hypot(y_mm - capstone_wire_center_y_mm)
                        <= LINEAR_CAPSTONE_WIRE_RADIUS_MM
                })
                .map(|(index, _)| {
                    let winding_sign = if index % 2 == 0 { 1.0 } else { -1.0 };
                    let current_a = winding_sign * wire_current_a;
                    let label = if winding_sign < 0.0 {
                        "capstone_winding_in"
                    } else {
                        "capstone_winding_out"
                    };
                    (label, current_a)
                })
        } else {
            None
        };
        let capstone_magnet = if is_linear_capstone {
            LINEAR_CAPSTONE_MAGNET_CENTERS_MM
                .iter()
                .enumerate()
                .find(|(_, center_x_mm)| {
                    in_rect(
                        x_mm,
                        y_mm,
                        **center_x_mm - LINEAR_CAPSTONE_MAGNET_HALF_WIDTH_MM,
                        **center_x_mm + LINEAR_CAPSTONE_MAGNET_HALF_WIDTH_MM,
                        LINEAR_CAPSTONE_MAGNET_BOTTOM_MM,
                        LINEAR_CAPSTONE_MAGNET_TOP_MM,
                    )
                })
                .map(|(index, _)| capstone_magnet_orientations[index])
        } else {
            None
        };
        let capstone_back_iron = is_linear_capstone
            && in_rect(
                x_mm,
                y_mm,
                -LINEAR_CAPSTONE_BACK_IRON_HALF_WIDTH_MM,
                LINEAR_CAPSTONE_BACK_IRON_HALF_WIDTH_MM,
                LINEAR_CAPSTONE_BACK_IRON_BOTTOM_MM,
                LINEAR_CAPSTONE_BACK_IRON_TOP_MM,
            );
        if let Some((label, current_a)) = capstone_winding {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push(label.to_string());
            current_densities
                .push(current_a * LINEAR_CAPSTONE_WINDING_TURNS / capstone_wire_area_m2);
            continue;
        } else if let Some(orientation) = capstone_magnet {
            regions.push(Region::Magnet);
            let magnetization_angle = if orientation > 0 {
                std::f64::consts::FRAC_PI_2
            } else {
                -std::f64::consts::FRAC_PI_2
            };
            materials.push(MaterialProps::magnet("N42", magnetization_angle));
            region_labels.push(if orientation > 0 {
                "capstone_magnet_n".to_string()
            } else {
                "capstone_magnet_s".to_string()
            });
        } else if capstone_back_iron {
            regions.push(Region::StatorYoke);
            materials.push(MaterialProps::steel(teaching_iron_grade()));
            region_labels.push("capstone_back_iron".to_string());
        } else if let Some((label, current_a)) = iron_tooth_coil {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push(label.to_string());
            let coil_area_m2 = (IRON_TOOTH_COIL_X_MAX_MM - IRON_TOOTH_COIL_X_MIN_MM)
                * (IRON_TOOTH_COIL_Y_MAX_MM - IRON_TOOTH_COIL_Y_MIN_MM)
                * 1.0e-6;
            current_densities.push(current_a * IRON_TOOTH_COIL_TURNS / coil_area_m2);
            continue;
        } else if iron_tooth_spm_magnet {
            regions.push(Region::Magnet);
            // The SPM north face points toward the stator tooth (+y).
            materials.push(MaterialProps::magnet("N42", std::f64::consts::FRAC_PI_2));
            region_labels.push("spm_magnet_n".to_string());
        } else if let Some(label) = iron_tooth_region {
            regions.push(Region::StatorYoke);
            materials.push(MaterialProps::steel(teaching_iron_grade()));
            region_labels.push(label.to_string());
        } else if let Some((label, current_a)) = three_phase_motor_coil {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push(label);
            current_densities
                .push(current_a * ROTOR_CHASE_COIL_TURNS / three_phase_motor_coil_area_m2);
            continue;
        } else if is_three_phase_motor && radius_mm <= ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM {
            regions.push(Region::Magnet);
            materials.push(if three_phase_rotor_enabled {
                MaterialProps::magnet("N42", magnet_angle_deg.to_radians())
            } else {
                MaterialProps::new(1.05, 0.0, 0.0)
            });
            region_labels.push("three_phase_rotor_magnet".to_string());
        } else if three_phase_motor_core {
            regions.push(Region::StatorYoke);
            materials.push(MaterialProps::steel(teaching_iron_grade()));
            region_labels.push("three_phase_stator_pole".to_string());
        } else if let Some((label, _, _, current_a)) = rotating_motor_coil {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push(label.to_string());
            current_densities
                .push(current_a * ROTOR_CHASE_COIL_TURNS / rotating_motor_coil_area_m2);
            continue;
        } else if is_rotating_field_motor && radius_mm <= ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM {
            regions.push(Region::Magnet);
            materials.push(if rotating_motor_rotor_enabled {
                MaterialProps::magnet("N42", magnet_angle_deg.to_radians())
            } else {
                MaterialProps::new(1.05, 0.0, 0.0)
            });
            region_labels.push("motor_rotor_magnet".to_string());
        } else if is_rotating_field_motor
            && (in_rect(
                x_mm,
                y_mm,
                -ROTATING_FIELD_MOTOR_CORE_OUTER_MM,
                -ROTATING_FIELD_MOTOR_CORE_INNER_MM,
                -ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
                ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            ) || in_rect(
                x_mm,
                y_mm,
                ROTATING_FIELD_MOTOR_CORE_INNER_MM,
                ROTATING_FIELD_MOTOR_CORE_OUTER_MM,
                -ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
                ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            ) || in_rect(
                x_mm,
                y_mm,
                -ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
                ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
                ROTATING_FIELD_MOTOR_CORE_INNER_MM,
                ROTATING_FIELD_MOTOR_CORE_OUTER_MM,
            ) || in_rect(
                x_mm,
                y_mm,
                -ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
                ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
                -ROTATING_FIELD_MOTOR_CORE_OUTER_MM,
                -ROTATING_FIELD_MOTOR_CORE_INNER_MM,
            ))
        {
            regions.push(Region::StatorYoke);
            materials.push(MaterialProps::steel(teaching_iron_grade()));
            region_labels.push("motor_stator_pole".to_string());
        } else if let Some((label, _, _, current_a)) = rotating_coil {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push(label.to_string());
            current_densities.push(current_a / rotating_coil_area_m2);
            continue;
        } else if is_rotor_chase
            && in_rect(
                magnet_local_x,
                magnet_local_y,
                -ROTOR_CHASE_ROTOR_HALF_LENGTH_MM,
                ROTOR_CHASE_ROTOR_HALF_LENGTH_MM,
                -ROTOR_CHASE_ROTOR_HALF_HEIGHT_MM,
                ROTOR_CHASE_ROTOR_HALF_HEIGHT_MM,
            )
        {
            regions.push(Region::Magnet);
            materials.push(if rotor_source_enabled {
                MaterialProps::magnet("N42", electrical_angle_rad)
            } else {
                MaterialProps::new(1.05, 0.0, 0.0)
            });
            region_labels.push(if magnet_local_x < 0.0 {
                "magnet_s".to_string()
            } else {
                "magnet_n".to_string()
            });
        } else if is_rotor_chase_coil {
            let coil = [
                (
                    "electromagnet_left_top",
                    -rotor_chase_coil_x_mm,
                    ROTOR_CHASE_COIL_Y_MM,
                    rotor_chase_coil_current_a,
                ),
                (
                    "electromagnet_left_bottom",
                    -rotor_chase_coil_x_mm,
                    -ROTOR_CHASE_COIL_Y_MM,
                    -rotor_chase_coil_current_a,
                ),
                (
                    "electromagnet_right_top",
                    rotor_chase_coil_x_mm,
                    ROTOR_CHASE_COIL_Y_MM,
                    rotor_chase_coil_current_a,
                ),
                (
                    "electromagnet_right_bottom",
                    rotor_chase_coil_x_mm,
                    -ROTOR_CHASE_COIL_Y_MM,
                    -rotor_chase_coil_current_a,
                ),
            ]
            .into_iter()
            .find(|(_, center_x_mm, center_y_mm, _)| {
                (x_mm - center_x_mm).hypot(y_mm - center_y_mm) <= ROTOR_CHASE_COIL_RADIUS_MM
            });
            if let Some((_, _, _, current_a)) = coil {
                regions.push(Region::SlotWinding);
                materials.push(MaterialProps::air());
                region_labels.push("wire".to_string());
                current_densities
                    .push(current_a * ROTOR_CHASE_COIL_TURNS / rotor_chase_coil_area_m2);
                continue;
            }
            if in_rect(
                x_mm,
                y_mm,
                -force_magnet_outer_x_mm,
                -force_magnet_inner_x_mm,
                -FORCE_MAGNET_HALF_HEIGHT_MM,
                FORCE_MAGNET_HALF_HEIGHT_MM,
            ) {
                regions.push(Region::StatorYoke);
                materials.push(MaterialProps::steel(teaching_iron_grade()));
                region_labels.push("stator_yoke".to_string());
            } else if in_rect(
                x_mm,
                y_mm,
                force_magnet_inner_x_mm,
                force_magnet_outer_x_mm,
                -FORCE_MAGNET_HALF_HEIGHT_MM,
                FORCE_MAGNET_HALF_HEIGHT_MM,
            ) {
                regions.push(Region::StatorYoke);
                materials.push(MaterialProps::steel(teaching_iron_grade()));
                region_labels.push("stator_yoke".to_string());
            } else {
                regions.push(Region::Airgap);
                materials.push(MaterialProps::air());
                region_labels.push("air".to_string());
            }
        } else if is_rotor_chase
            && in_rect(
                x_mm,
                y_mm,
                -force_magnet_outer_x_mm,
                -force_magnet_inner_x_mm,
                -FORCE_MAGNET_HALF_HEIGHT_MM,
                FORCE_MAGNET_HALF_HEIGHT_MM,
            )
        {
            regions.push(Region::Magnet);
            materials.push(if stator_source_enabled {
                MaterialProps::magnet("N42", 0.0)
            } else {
                MaterialProps::new(1.05, 0.0, 0.0)
            });
            region_labels.push("force_magnet_n".to_string());
        } else if is_rotor_chase
            && in_rect(
                x_mm,
                y_mm,
                force_magnet_inner_x_mm,
                force_magnet_outer_x_mm,
                -FORCE_MAGNET_HALF_HEIGHT_MM,
                FORCE_MAGNET_HALF_HEIGHT_MM,
            )
        {
            regions.push(Region::Magnet);
            materials.push(if stator_source_enabled {
                MaterialProps::magnet("N42", 0.0)
            } else {
                MaterialProps::new(1.05, 0.0, 0.0)
            });
            region_labels.push("force_magnet_s".to_string());
        } else if is_force_fixture && radius_mm <= FORCE_WIRE_RADIUS_MM {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push("wire".to_string());
            let wire_area_m2 = std::f64::consts::PI * (FORCE_WIRE_RADIUS_MM * 1.0e-3).powi(2);
            current_densities.push(wire_current_a / wire_area_m2);
            continue;
        } else if is_force_fixture
            && in_rect(
                x_mm,
                y_mm,
                -force_magnet_outer_x_mm,
                -force_magnet_inner_x_mm,
                -FORCE_MAGNET_HALF_HEIGHT_MM,
                FORCE_MAGNET_HALF_HEIGHT_MM,
            )
        {
            regions.push(Region::Magnet);
            materials.push(if is_force_wire_fixture {
                MaterialProps::new(1.05, 0.0, 0.0)
            } else {
                MaterialProps::magnet("N42", 0.0)
            });
            region_labels.push("force_magnet_n".to_string());
        } else if is_force_fixture
            && in_rect(
                x_mm,
                y_mm,
                force_magnet_inner_x_mm,
                force_magnet_outer_x_mm,
                -FORCE_MAGNET_HALF_HEIGHT_MM,
                FORCE_MAGNET_HALF_HEIGHT_MM,
            )
        {
            regions.push(Region::Magnet);
            materials.push(if is_force_wire_fixture {
                MaterialProps::new(1.05, 0.0, 0.0)
            } else {
                MaterialProps::magnet("N42", 0.0)
            });
            region_labels.push("force_magnet_s".to_string());
        } else if is_current_fixture && radius_mm <= WIRE_RADIUS_MM {
            regions.push(Region::SlotWinding);
            materials.push(MaterialProps::air());
            region_labels.push("wire".to_string());
            let wire_area_m2 = std::f64::consts::PI * (WIRE_RADIUS_MM * 1.0e-3).powi(2);
            current_densities.push(wire_current_a / wire_area_m2);
            continue;
        } else if fixture == "iron_saturation"
            && (IRON_RING_INNER_RADIUS_MM..=IRON_RING_OUTER_RADIUS_MM).contains(&radius_mm)
        {
            regions.push(Region::StatorYoke);
            materials.push(MaterialProps::steel(teaching_iron_grade()));
            region_labels.push("iron_ring".to_string());
        } else if !is_linear_capstone
            && !is_current_fixture
            && !is_force_fixture
            && !is_rotor_chase
            && !is_rotating_field_fixture
            && !is_rotating_field_motor
            && !is_three_phase_motor
            && in_rect(magnet_local_x, magnet_local_y, -18.0, 18.0, -6.0, 6.0)
        {
            regions.push(Region::Magnet);
            materials.push(MaterialProps::magnet("N42", magnet_angle_deg.to_radians()));
            region_labels.push(if magnet_local_x < 0.0 {
                "magnet_s".to_string()
            } else {
                "magnet_n".to_string()
            });
        } else if magnet2_enabled
            && !is_linear_capstone
            && !is_current_fixture
            && !is_force_fixture
            && !is_rotor_chase
            && !is_rotating_field_fixture
            && !is_rotating_field_motor
            && !is_three_phase_motor
            && in_rect(magnet2_local_x, magnet2_local_y, -18.0, 18.0, -6.0, 6.0)
        {
            // Same body as the first magnet but carrying its own magnetization
            // direction, so the pair can be set up attracting or repelling.
            regions.push(Region::Magnet);
            materials.push(MaterialProps::magnet("N42", magnet2_angle_deg.to_radians()));
            region_labels.push(if magnet2_local_x < 0.0 {
                "magnet2_s".to_string()
            } else {
                "magnet2_n".to_string()
            });
        } else if steel_return
            && is_steel_shape(
                x_mm,
                y_mm,
                steel_shape,
                steel_center_x_mm,
                steel_center_y_mm,
                steel_angle_deg,
            )
        {
            regions.push(Region::StatorYoke);
            materials.push(MaterialProps::new(1_000.0, 0.0, 0.0));
            region_labels.push("steel_return".to_string());
        } else {
            regions.push(Region::Airgap);
            materials.push(MaterialProps::air());
            region_labels.push("air".to_string());
        }
        current_densities.push(0.0);
    }

    let num_nodes = nodes.len();
    let num_triangles = triangles.len();
    let mesh = TriMesh {
        nodes,
        triangles,
        regions,
        boundary_nodes,
        sector_edge_pairs: vec![],
        info: MeshInfo {
            num_nodes,
            num_triangles,
            pole_pitch_deg: 360.0,
            n_pole_pitches: 1,
            total_span_deg: 360.0,
            angular_divisions,
            radial_rings,
            mesh_density: mesh_density.to_string(),
            radial_layers: vec![
                "air".to_string(),
                "magnet".to_string(),
                "steel_return".to_string(),
                "iron_ring".to_string(),
                "iron_tooth".to_string(),
                "iron_yoke".to_string(),
                "iron_return_tooth".to_string(),
                "iron_rotor".to_string(),
                "spm_magnet_n".to_string(),
                "wire".to_string(),
                "tooth_coil_out".to_string(),
                "tooth_coil_in".to_string(),
                "capstone_magnet_n".to_string(),
                "capstone_magnet_s".to_string(),
                "capstone_back_iron".to_string(),
                "capstone_winding_out".to_string(),
                "capstone_winding_in".to_string(),
                "phase_a_positive".to_string(),
                "phase_a_negative".to_string(),
                "phase_b_positive".to_string(),
                "phase_b_negative".to_string(),
                "magnet_s".to_string(),
                "magnet_n".to_string(),
            ],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: Some(mesh_source),
            magnet_outer_radius_mm: 0.0,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 0.0,
            stator_slot_outer_radius_mm: 0.0,
            stator_outer_radius_mm: 0.0,
        },
    };
    Ok((mesh, materials, current_densities, region_labels))
}

fn element_centroid_mm(mesh: &TriMesh, index: usize) -> [f64; 2] {
    let triangle = mesh.triangles[index];
    let mut x = 0.0;
    let mut y = 0.0;
    for node in triangle {
        x += mesh.nodes[node][0];
        y += mesh.nodes[node][1];
    }
    [x / 3.0 * 1.0e3, y / 3.0 * 1.0e3]
}

fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f64>() / values.len() as f64
    }
}

fn element_area_m2(mesh: &TriMesh, index: usize) -> f64 {
    let triangle = mesh.triangles[index];
    let a = mesh.nodes[triangle[0]];
    let b = mesh.nodes[triangle[1]];
    let c = mesh.nodes[triangle[2]];
    0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])).abs()
}

fn weighted_mean(samples: &[(f64, f64)]) -> f64 {
    let weight = samples.iter().map(|(_, weight)| weight).sum::<f64>();
    if weight <= 0.0 {
        0.0
    } else {
        samples
            .iter()
            .map(|(value, weight)| value * weight)
            .sum::<f64>()
            / weight
    }
}

fn solve_linear_teaching_field(
    mesh: &TriMesh,
    materials: &[MaterialProps],
    current_densities: &[f64],
) -> Result<(Vec<f64>, Vec<crate::postprocess::ElementField>), String> {
    let mut stiffness = assemble_stiffness(mesh, materials).to_csr();
    let mut rhs = assemble_source(mesh, materials, current_densities, None);
    stiffness.apply_dirichlet(&mut rhs, &mesh.boundary_nodes);
    let az = pcg_solve(&stiffness, &rhs, 8_000, 1.0e-10)?;
    let fields = compute_element_fields(mesh, &az);
    Ok((az, fields))
}

fn solve_nonlinear_iron_field(
    mesh: &TriMesh,
    mut materials: Vec<MaterialProps>,
    current_densities: &[f64],
    region_labels: &[String],
) -> Result<
    (
        Vec<f64>,
        Vec<crate::postprocess::ElementField>,
        Vec<MaterialProps>,
        usize,
    ),
    String,
> {
    const MAX_ITERATIONS: usize = 60;
    const RELAXATION: f64 = 0.18;
    const CONVERGENCE: f64 = 0.025;

    for iteration in 1..=MAX_ITERATIONS {
        let (az, fields) = solve_linear_teaching_field(mesh, &materials, current_densities)?;
        let mut max_residual = 0.0_f64;
        let mut next_materials = materials.clone();
        for (index, field) in fields.iter().enumerate() {
            if !region_labels[index].starts_with("iron_") {
                continue;
            }
            let Some(target_mu_rel) = nonlinear_steel_mu_rel(teaching_iron_grade(), field.b_mag)
            else {
                continue;
            };
            let previous = materials[index].mu_rel.max(1.0);
            let bounded_target = target_mu_rel.clamp(previous * 0.65, previous * 1.55);
            let updated = previous + RELAXATION * (bounded_target - previous);
            let residual = ((target_mu_rel - previous) / previous).abs();
            max_residual = max_residual.max(residual);
            next_materials[index].with_mu_rel(updated);
        }
        if max_residual <= CONVERGENCE {
            return Ok((az, fields, materials, iteration));
        }
        materials = next_materials;
    }

    let (az, fields) = solve_linear_teaching_field(mesh, &materials, current_densities)?;
    Ok((az, fields, materials, MAX_ITERATIONS))
}

fn solve_metrics(
    mesh: &TriMesh,
    region_labels: &[String],
    fields: &[crate::postprocess::ElementField],
    materials: &[MaterialProps],
    current_densities: &[f64],
    magnet_center_x_mm: f64,
    magnet_center_y_mm: f64,
    magnet_angle_deg: f64,
    steel_shape: &str,
    circuit_gap_mm: f64,
    fixture: &str,
    nonlinear_iterations: Option<usize>,
    wire_current_a: f64,
) -> TeachingMetrics {
    let mut working_gap = Vec::new();
    let mut probe_tangential = Vec::new();
    let mut outside = Vec::new();
    let mut return_path = Vec::new();
    let mut iron_b = Vec::new();
    let mut iron_h = Vec::new();
    let mut iron_mu = Vec::new();
    let mut iron_area = 0.0;
    let mut saturated_area = 0.0;
    let mut tooth_b = Vec::new();
    let mut tooth_tip_b = Vec::new();
    let mut tooth_area = 0.0;
    let mut tooth_saturated_area = 0.0;
    let mut tooth_airgap_by = Vec::new();
    let mut wire_bx = Vec::new();
    let mut wire_by = Vec::new();
    let mut center_bx = Vec::new();
    let mut center_by = Vec::new();
    let mut wire_force_x_n = 0.0;
    let mut wire_force_y_n = 0.0;
    for (index, field) in fields.iter().enumerate() {
        let [x_mm, y_mm] = element_centroid_mm(mesh, index);
        let (local_x_mm, local_y_mm) = to_local(
            x_mm,
            y_mm,
            magnet_center_x_mm,
            magnet_center_y_mm,
            magnet_angle_deg,
        );
        let gap_mm = if steel_shape == "circuit" {
            circuit_gap_mm
        } else {
            4.0
        };
        if (is_any_rotating_field_fixture(fixture) || is_rotor_chase_fixture(fixture))
            && x_mm.hypot(y_mm) <= ROTATING_FIELD_CENTER_PROBE_RADIUS_MM
            && region_labels[index] == "air"
        {
            let area_m2 = element_area_m2(mesh, index);
            center_bx.push((field.bx, area_m2));
            center_by.push((field.by, area_m2));
            working_gap.push(field.b_mag);
        } else if is_iron_tooth_fixture(fixture)
            && region_labels[index] == "air"
            && x_mm.abs() <= IRON_TOOTH_HALF_WIDTH_MM
            && (IRON_TOOTH_ROTOR_TOP_MM..=IRON_TOOTH_TIP_Y_MM).contains(&y_mm)
        {
            let area_m2 = element_area_m2(mesh, index);
            working_gap.push(field.b_mag);
            tooth_airgap_by.push((field.by.abs(), area_m2));
        } else if fixture == "current_wire" || fixture == "iron_saturation" {
            let radius_mm = x_mm.hypot(y_mm);
            let probe_radius_mm = if fixture == "iron_saturation" {
                IRON_RING_PROBE_RADIUS_MM
            } else {
                WIRE_PROBE_RADIUS_MM
            };
            if (radius_mm - probe_radius_mm).abs() <= 1.0 && radius_mm > 0.0 {
                working_gap.push(field.b_mag);
                let tangent_x = -y_mm / radius_mm;
                let tangent_y = x_mm / radius_mm;
                probe_tangential.push(field.bx * tangent_x + field.by * tangent_y);
            }
        } else {
            let in_right_gap =
                (18.0..=18.0 + gap_mm).contains(&local_x_mm) && local_y_mm.abs() <= 5.0;
            let in_left_gap =
                (-18.0 - gap_mm..=-18.0).contains(&local_x_mm) && local_y_mm.abs() <= 5.0;
            if in_right_gap || in_left_gap {
                working_gap.push(field.b_mag);
            }
        }
        if x_mm.abs() >= 36.0 || y_mm.abs() >= 27.0 {
            outside.push(field.b_mag);
        }
        if region_labels[index] == "steel_return" {
            return_path.push(field.b_mag);
        }
        if region_labels[index].starts_with("iron_") {
            let area = element_area_m2(mesh, index);
            let h = field.b_mag / (MU_0 * materials[index].mu_rel.max(1.0));
            iron_b.push((field.b_mag, area));
            iron_h.push((h, area));
            iron_mu.push((materials[index].mu_rel, area));
            iron_area += area;
            if field.b_mag >= IRON_SATURATION_THRESHOLD_T {
                saturated_area += area;
            }
            return_path.push(field.b_mag);
            if region_labels[index] == "iron_tooth" {
                tooth_b.push((field.b_mag, area));
                tooth_area += area;
                if field.b_mag >= IRON_SATURATION_THRESHOLD_T {
                    tooth_saturated_area += area;
                }
                if y_mm <= IRON_TOOTH_TIP_Y_MM + 5.0 {
                    tooth_tip_b.push((field.b_mag, area));
                }
            }
        }
        let is_current_force_wire = fixture == "current_force" && region_labels[index] == "wire";
        let is_capstone_winding = fixture == "linear_motor_capstone"
            && region_labels[index].starts_with("capstone_winding_");
        if is_current_force_wire || is_capstone_winding {
            let area_m2 = element_area_m2(mesh, index);
            let current_density_a_per_m2 = if is_current_force_wire {
                let wire_area_m2 = std::f64::consts::PI * (FORCE_WIRE_RADIUS_MM * 1.0e-3).powi(2);
                wire_current_a / wire_area_m2
            } else {
                current_densities[index]
            };
            let depth_m = FORCE_TEACHING_DEPTH_MM * 1.0e-3;
            wire_bx.push((field.bx, area_m2));
            wire_by.push((field.by, area_m2));
            wire_force_x_n += -current_density_a_per_m2 * field.by * area_m2 * depth_m;
            wire_force_y_n += current_density_a_per_m2 * field.bx * area_m2 * depth_m;
        }
    }
    let is_iron_saturation = is_iron_saturation_fixture(fixture);
    let is_iron_tooth = is_iron_tooth_fixture(fixture);
    let is_current_force = fixture == "current_force";
    let has_winding_force_integral = is_current_force || fixture == "linear_motor_capstone";
    let is_center_field_fixture =
        is_any_rotating_field_fixture(fixture) || is_rotor_chase_fixture(fixture);
    let wire_mean_bx_t = weighted_mean(&wire_bx);
    let wire_mean_by_t = weighted_mean(&wire_by);
    let center_bx_t = weighted_mean(&center_bx);
    let center_by_t = weighted_mean(&center_by);
    let center_b_t = center_bx_t.hypot(center_by_t);
    TeachingMetrics {
        working_gap_mean_b_t: mean(&working_gap),
        outside_field_mean_b_t: mean(&outside),
        return_path_mean_b_t: (!return_path.is_empty()).then(|| mean(&return_path)),
        peak_b_t: fields
            .iter()
            .map(|field| field.b_mag)
            .fold(0.0_f64, f64::max),
        probe_tangential_b_t: (fixture == "current_wire" || is_iron_saturation)
            .then(|| mean(&probe_tangential)),
        probe_radius_mm: if is_iron_saturation {
            Some(IRON_RING_PROBE_RADIUS_MM)
        } else if fixture == "current_wire" {
            Some(WIRE_PROBE_RADIUS_MM)
        } else {
            None
        },
        iron_mean_b_t: is_iron_saturation.then(|| weighted_mean(&iron_b)),
        iron_mean_h_a_per_m: is_iron_saturation.then(|| weighted_mean(&iron_h)),
        iron_effective_mu_rel: is_iron_saturation.then(|| weighted_mean(&iron_mu)),
        iron_saturated_fraction: is_iron_saturation.then(|| {
            if iron_area > 0.0 {
                saturated_area / iron_area
            } else {
                0.0
            }
        }),
        iron_saturation_threshold_t: is_iron_saturation.then_some(IRON_SATURATION_THRESHOLD_T),
        nonlinear_iterations: is_iron_saturation.then(|| nonlinear_iterations.unwrap_or(0)),
        tooth_mean_b_t: is_iron_tooth.then(|| weighted_mean(&tooth_b)),
        tooth_tip_mean_b_t: is_iron_tooth.then(|| weighted_mean(&tooth_tip_b)),
        tooth_saturated_fraction: is_iron_tooth.then(|| {
            if tooth_area > 0.0 {
                tooth_saturated_area / tooth_area
            } else {
                0.0
            }
        }),
        airgap_mean_b_t: is_iron_tooth.then(|| weighted_mean(&tooth_airgap_by)),
        airgap_flux_per_depth_wb_per_m: is_iron_tooth
            .then(|| weighted_mean(&tooth_airgap_by) * 2.0 * IRON_TOOTH_HALF_WIDTH_MM * 1.0e-3),
        wire_mean_bx_t: has_winding_force_integral.then_some(wire_mean_bx_t),
        wire_mean_by_t: has_winding_force_integral.then_some(wire_mean_by_t),
        wire_force_x_n: has_winding_force_integral.then_some(wire_force_x_n),
        wire_force_y_n: has_winding_force_integral.then_some(wire_force_y_n),
        wire_force_magnitude_n: has_winding_force_integral
            .then_some(wire_force_x_n.hypot(wire_force_y_n)),
        wire_force_bil_n: is_current_force
            .then_some(wire_mean_bx_t * wire_current_a * FORCE_TEACHING_DEPTH_MM * 1.0e-3),
        teaching_depth_mm: has_winding_force_integral.then_some(FORCE_TEACHING_DEPTH_MM),
        center_bx_t: is_center_field_fixture.then_some(center_bx_t),
        center_by_t: is_center_field_fixture.then_some(center_by_t),
        center_b_t: is_center_field_fixture.then_some(center_b_t),
        center_field_angle_deg: is_center_field_fixture.then_some(
            center_by_t
                .atan2(center_bx_t)
                .to_degrees()
                .rem_euclid(360.0),
        ),
    }
}

pub fn run(request: TeachingRequest) -> Result<TeachingReport, String> {
    let fixture = request.fixture.trim().to_ascii_lowercase();
    let is_current_wire = fixture == "current_wire";
    let is_iron_saturation = is_iron_saturation_fixture(&fixture);
    let is_iron_tooth = is_iron_tooth_fixture(&fixture);
    let is_current_force = fixture == "current_force";
    let is_current_force_wire = fixture == "current_force_wire";
    let is_linear_capstone = fixture == "linear_motor_capstone";
    let is_rotating_field = is_rotating_field_fixture(&fixture);
    let is_rotating_field_motor = is_rotating_field_motor_fixture(&fixture);
    let is_three_phase_motor = is_three_phase_motor_fixture(&fixture);
    let is_any_rotating_field =
        is_rotating_field || is_rotating_field_motor || is_three_phase_motor;
    let is_rotor_chase = is_rotor_chase_fixture(&fixture);
    if fixture != "follow_flux"
        && fixture != "magnetic_circuit"
        && fixture != "current_wire"
        && !is_current_force
        && !is_current_force_wire
        && !is_linear_capstone
        && !is_iron_saturation
        && !is_any_rotating_field
        && !is_rotor_chase
    {
        return Err(format!("unknown teaching fixture '{}'", request.fixture));
    }
    if is_current_wire && !(-20.0..=20.0).contains(&request.wire_current_a) {
        return Err("current-wire fixture current must be between -20 and 20 A".to_string());
    }
    if (is_current_force || is_current_force_wire)
        && !(-20.0..=20.0).contains(&request.wire_current_a)
    {
        return Err("current-force fixture current must be between -20 and 20 A".to_string());
    }
    if (is_current_force || is_current_force_wire)
        && request.steel_center_x_mm != 0.0
        && !(0.5..=16.0).contains(&request.steel_center_x_mm)
    {
        return Err("current-force pole gap must be between 0.5 and 16 mm".to_string());
    }
    if is_linear_capstone && !(-20.0..=20.0).contains(&request.wire_current_a) {
        return Err("linear-capstone current must be between -20 and 20 A".to_string());
    }
    if is_linear_capstone
        && request.steel_center_x_mm != 0.0
        && !(2.0..=10.0).contains(&request.steel_center_x_mm)
    {
        return Err("linear-capstone airgap must be between 2 and 10 mm".to_string());
    }
    if is_linear_capstone
        && (request.capstone_magnet_orientations.len() != 4
            || request
                .capstone_magnet_orientations
                .iter()
                .any(|orientation| !matches!(orientation, -1 | 1)))
    {
        return Err("linear-capstone requires four magnet orientations of -1 or 1".to_string());
    }
    if is_linear_capstone && !(12.0..=22.0).contains(&request.capstone_winding_spacing_mm) {
        return Err("linear-capstone winding spacing must be between 12 and 22 mm".to_string());
    }
    if fixture == "iron_saturation" && !(0.0..=1_200.0).contains(&request.wire_current_a) {
        return Err("iron-saturation ring current must be between 0 and 1200 A".to_string());
    }
    if is_iron_tooth && !(0.0..=20.0).contains(&request.wire_current_a) {
        return Err("iron-saturation tooth current must be between 0 and 20 A".to_string());
    }
    if is_any_rotating_field && !(0.0..=20.0).contains(&request.wire_current_a) {
        return Err("rotating-field peak current must be between 0 and 20 A".to_string());
    }
    if is_rotor_chase_coil_fixture(&fixture) && !(-20.0..=20.0).contains(&request.wire_current_a) {
        return Err("rotor-chase electromagnet current must be between -20 and 20 A".to_string());
    }
    if is_rotor_chase
        && request.steel_center_x_mm != 0.0
        && !(2.0..=16.0).contains(&request.steel_center_x_mm)
    {
        return Err("rotor-chase pole gap must be between 2 and 16 mm".to_string());
    }
    let steel_shape = request.steel_shape.trim().to_ascii_lowercase();
    if !is_current_wire
        && !is_iron_saturation
        && !is_current_force
        && !is_current_force_wire
        && !is_linear_capstone
        && !is_any_rotating_field
        && !is_rotor_chase
    {
        if request.steel_return {
            validate_fixture_placement(
                &steel_shape,
                request.steel_center_x_mm,
                request.steel_center_y_mm,
                request.magnet_center_x_mm,
                request.magnet_center_y_mm,
                request.magnet_angle_deg,
                request.steel_angle_deg,
            )?;
        } else {
            steel_shape_dimensions(&steel_shape)?;
            let (magnet_extent_x, magnet_extent_y) =
                rotated_rect_extents(18.0, 6.0, request.magnet_angle_deg);
            if request.magnet_center_x_mm.abs() + magnet_extent_x > DOMAIN_X_MAX_MM - 2.0
                || request.magnet_center_y_mm.abs() + magnet_extent_y > DOMAIN_Y_MAX_MM - 2.0
            {
                return Err("permanent magnet must remain inside the field domain".to_string());
            }
        }
    }
    let started = Instant::now();
    let (mesh, materials, current_densities, region_labels) = build_follow_flux_mesh(
        &fixture,
        &request.mesh_density,
        request.steel_return,
        &steel_shape,
        request.steel_center_x_mm,
        request.steel_center_y_mm,
        request.magnet_center_x_mm,
        request.magnet_center_y_mm,
        request.magnet_angle_deg,
        request.magnet2_enabled,
        request.magnet2_center_x_mm,
        request.magnet2_center_y_mm,
        request.magnet2_angle_deg,
        request.steel_angle_deg,
        request.wire_current_a,
        &request.capstone_magnet_orientations,
        request.capstone_winding_spacing_mm,
        request.imported_mesh.as_ref(),
    )?;

    let (az_nodal, element_b_mag_t, element_bx_t, element_by_t, metrics) = if request.solve {
        let (az, fields, solved_materials, nonlinear_iterations) = if is_iron_saturation {
            let (az, fields, solved_materials, iterations) = solve_nonlinear_iron_field(
                &mesh,
                materials.clone(),
                &current_densities,
                &region_labels,
            )?;
            (az, fields, solved_materials, Some(iterations))
        } else {
            let (az, fields) = solve_linear_teaching_field(&mesh, &materials, &current_densities)?;
            (az, fields, materials.clone(), None)
        };
        let metrics = solve_metrics(
            &mesh,
            &region_labels,
            &fields,
            &solved_materials,
            &current_densities,
            request.magnet_center_x_mm,
            request.magnet_center_y_mm,
            request.magnet_angle_deg,
            &steel_shape,
            request.steel_center_x_mm,
            &fixture,
            nonlinear_iterations,
            request.wire_current_a,
        );
        let b_mag = fields.iter().map(|field| field.b_mag).collect();
        let bx = fields.iter().map(|field| field.bx).collect();
        let by = fields.iter().map(|field| field.by).collect();
        (az, b_mag, bx, by, Some(metrics))
    } else {
        (vec![], vec![], vec![], vec![], None)
    };

    Ok(TeachingReport {
        schema_version: "openem.teaching_field.v1".to_string(),
        fixture: fixture.clone(),
        steel_return: request.steel_return,
        steel_shape,
        steel_center_x_mm: request.steel_center_x_mm,
        steel_center_y_mm: request.steel_center_y_mm,
        magnet_center_x_mm: request.magnet_center_x_mm,
        magnet_center_y_mm: request.magnet_center_y_mm,
        magnet_angle_deg: request.magnet_angle_deg,
        magnet2_enabled: request.magnet2_enabled,
        magnet2_center_x_mm: request.magnet2_center_x_mm,
        magnet2_center_y_mm: request.magnet2_center_y_mm,
        magnet2_angle_deg: request.magnet2_angle_deg,
        steel_angle_deg: request.steel_angle_deg,
        wire_current_a: request.wire_current_a,
        solved: request.solve,
        config_summary: TeachingConfigSummary {
            topology: if is_iron_saturation {
                if is_iron_tooth {
                    if fixture == "iron_saturation_spm_tooth" {
                        "Concentrated winding facing an N42 SPM pole".to_string()
                    } else {
                        "Concentrated winding around an M350-50A motor tooth".to_string()
                    }
                } else {
                    "Current-driven M350-50A iron ring".to_string()
                }
            } else if is_rotor_chase_coil_fixture(&fixture) {
                "Wound M350-50A stator poles with a free PM rotor".to_string()
            } else if is_rotor_chase {
                "Fixed permanent-magnet stator with a free PM rotor".to_string()
            } else if is_rotating_field_motor {
                "Two-phase four-pole M350-50A stator with a PM rotor".to_string()
            } else if is_three_phase_motor {
                "Three-phase six-tooth M350-50A stator with a PM rotor".to_string()
            } else if is_rotating_field {
                "Two-phase quadrature field fixture".to_string()
            } else if is_current_force_wire {
                "Straight conductor field with permanent-magnet sources disabled".to_string()
            } else if is_linear_capstone {
                "Four-pole moving-coil linear actuator with M350-50A back iron".to_string()
            } else if is_current_force {
                "Straight conductor between permanent-magnet poles".to_string()
            } else if is_current_wire {
                "Straight current conductor".to_string()
            } else {
                "Teaching field fixture".to_string()
            },
            slots: if is_iron_tooth { 2 } else { 0 },
            poles: if is_current_wire || is_iron_saturation {
                0
            } else if is_linear_capstone {
                4
            } else if is_rotor_chase {
                4
            } else if is_three_phase_motor {
                2
            } else if is_any_rotating_field {
                4
            } else {
                2
            },
            stator_od_mm: if is_any_rotating_field {
                2.0 * ROTATING_FIELD_DOMAIN_HALF_MM
            } else {
                DOMAIN_X_MAX_MM - DOMAIN_X_MIN_MM
            },
            rotor_od_mm: if is_rotating_field_motor || is_three_phase_motor {
                2.0 * ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM
            } else if is_rotor_chase {
                2.0 * ROTOR_CHASE_ROTOR_HALF_LENGTH_MM
            } else {
                0.0
            },
            magnet_thickness_mm: if fixture == "iron_saturation_spm_tooth" {
                IRON_TOOTH_SPM_MAGNET_TOP_MM - IRON_TOOTH_SPM_MAGNET_BOTTOM_MM
            } else if is_current_wire || is_iron_saturation || is_rotating_field {
                0.0
            } else if is_rotating_field_motor || is_three_phase_motor {
                2.0 * ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM
            } else if is_rotor_chase {
                2.0 * ROTOR_CHASE_ROTOR_HALF_HEIGHT_MM
            } else if is_current_force || is_current_force_wire {
                FORCE_MAGNET_WIDTH_MM
            } else if is_linear_capstone {
                LINEAR_CAPSTONE_MAGNET_TOP_MM - LINEAR_CAPSTONE_MAGNET_BOTTOM_MM
            } else {
                12.0
            },
            stack_length_mm: if is_iron_tooth
                || is_current_force
                || is_current_force_wire
                || is_linear_capstone
                || is_rotor_chase
                || is_rotating_field_motor
                || is_three_phase_motor
            {
                FORCE_TEACHING_DEPTH_MM
            } else {
                1.0
            },
        },
        mesh_info: TeachingMeshInfo {
            num_nodes: mesh.nodes.len(),
            num_triangles: mesh.triangles.len(),
            pole_pitch_deg: 360.0,
            n_pole_pitches: 1,
            total_span_deg: 360.0,
            mesh_source_detail: request
                .imported_mesh
                .as_ref()
                .map(|mesh| mesh.source_detail.clone())
                .unwrap_or_else(|| "magneto2d teaching fallback mesh".to_string()),
            mesh_source: if request.imported_mesh.is_some() {
                "gmsh".to_string()
            } else {
                "native".to_string()
            },
            corner_refinement: request
                .imported_mesh
                .as_ref()
                .is_some_and(|mesh| mesh.corner_refinement),
            mesh_density: request.mesh_density,
        },
        nodes_mm: mesh
            .nodes
            .iter()
            .map(|node| [node[0] * 1.0e3, node[1] * 1.0e3])
            .collect(),
        triangles: mesh.triangles,
        regions: region_labels,
        n_pole_pitches: 1,
        total_span_deg: 360.0,
        generation_time_ms: started.elapsed().as_millis(),
        az_nodal,
        element_b_mag_t,
        element_bx_t,
        element_by_t,
        metrics,
        bh_curve: is_iron_saturation.then(|| {
            get_bh_curve(teaching_iron_grade())
                .map(|curve| {
                    curve
                        .points
                        .iter()
                        .map(|&(b_t, h_a_per_m)| TeachingBhPoint { b_t, h_a_per_m })
                        .collect()
                })
                .unwrap_or_default()
        }),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn generic_problem_from_teaching_mesh(
        mesh: &TriMesh,
        materials: &[MaterialProps],
        current_densities: &[f64],
        region_labels: &[String],
        nonlinear_iron: bool,
    ) -> crate::field::MagnetostaticProblem {
        let mut field_materials = Vec::new();
        let mut linear_ids = HashMap::<u64, usize>::new();
        let nonlinear_curve = nonlinear_iron.then(|| {
            crate::materials::resolved_field_bh_curve(teaching_iron_grade())
                .expect("teaching iron B-H curve")
        });
        let nonlinear_id = nonlinear_curve.as_ref().map(|curve| {
            let id = field_materials.len();
            field_materials.push(crate::field::MaterialModel::Nonlinear {
                bh_curve: curve.clone(),
            });
            id
        });
        let elements = materials
            .iter()
            .enumerate()
            .map(|(index, material)| {
                let material_id = if nonlinear_iron && region_labels[index].starts_with("iron_") {
                    nonlinear_id.expect("nonlinear material id")
                } else {
                    *linear_ids
                        .entry(material.mu_rel.to_bits())
                        .or_insert_with(|| {
                            let id = field_materials.len();
                            field_materials.push(crate::field::MaterialModel::Linear {
                                mu_r: material.mu_rel,
                            });
                            id
                        })
                };
                crate::field::ElementPhysics {
                    material_id,
                    current_density_z_a_per_m2: current_densities[index],
                    remanence_t: [
                        material.br * material.mag_angle_rad.cos(),
                        material.br * material.mag_angle_rad.sin(),
                    ],
                    pm_source_scale: 1.0,
                }
            })
            .collect();
        crate::field::MagnetostaticProblem {
            mesh: crate::field::FemMesh {
                nodes_m: mesh.nodes.clone(),
                triangles: mesh.triangles.clone(),
            },
            materials: field_materials,
            elements,
            boundaries: crate::field::BoundarySet {
                dirichlet_az_zero_nodes: mesh.boundary_nodes.clone(),
                paired_nodes: Vec::new(),
                periodic_penalty: 1.0e10,
            },
            options: crate::field::SolveOptions {
                linear: crate::field::LinearSolveOptions {
                    solver: crate::field::LinearSolver::Direct,
                    tolerance: 1.0e-10,
                    max_iterations: 8_000,
                    ..crate::field::LinearSolveOptions::default()
                },
                nonlinear: if nonlinear_iron {
                    crate::field::NonlinearSolveOptions {
                        algorithm: crate::field::NonlinearAlgorithm::Picard,
                        max_iterations: 200,
                        // The generic residual is the raw material residual
                        // multiplied by relaxation. A 0.005 gate therefore
                        // freezes a 5% raw-material residual for this
                        // cross-policy calibration.
                        tolerance: 0.005,
                        relaxation: 0.1,
                        mu_r_step_cap: 1.1,
                        ..crate::field::NonlinearSolveOptions::default()
                    }
                } else {
                    crate::field::NonlinearSolveOptions::default()
                },
            },
            warm_start: None,
        }
    }

    fn relative_field_rms(
        reference: &[crate::postprocess::ElementField],
        candidate: &[crate::postprocess::ElementField],
    ) -> f64 {
        let squared_error = reference
            .iter()
            .zip(candidate)
            .map(|(reference, candidate)| {
                (candidate.bx - reference.bx).powi(2) + (candidate.by - reference.by).powi(2)
            })
            .sum::<f64>();
        let squared_reference = reference
            .iter()
            .map(|field| field.bx.powi(2) + field.by.powi(2))
            .sum::<f64>();
        (squared_error / squared_reference.max(1.0e-30)).sqrt()
    }

    fn area_weighted_iron_b(
        mesh: &TriMesh,
        region_labels: &[String],
        fields: &[crate::postprocess::ElementField],
    ) -> f64 {
        let mut weighted = 0.0;
        let mut area = 0.0;
        for (index, field) in fields.iter().enumerate() {
            if !region_labels[index].starts_with("iron_") {
                continue;
            }
            let element_area = element_area_m2(mesh, index);
            weighted += field.b_mag * element_area;
            area += element_area;
        }
        weighted / area
    }

    #[test]
    fn follow_flux_generic_linear_path_matches_teaching_path() {
        let (mesh, materials, current_densities, region_labels) = build_follow_flux_mesh(
            "follow_flux",
            "coarse",
            true,
            "bar",
            28.0,
            0.0,
            0.0,
            0.0,
            0.0,
            false,
            44.0,
            0.0,
            0.0,
            0.0,
            0.0,
            &[],
            18.0,
            None,
        )
        .expect("follow-flux mesh");
        let (_teaching_az, teaching_fields) =
            solve_linear_teaching_field(&mesh, &materials, &current_densities)
                .expect("teaching solve");
        let generic_problem = generic_problem_from_teaching_mesh(
            &mesh,
            &materials,
            &current_densities,
            &region_labels,
            false,
        );
        let generic = crate::field::solve(&generic_problem).expect("generic field solve");
        let relative_rms = relative_field_rms(&teaching_fields, &generic.element_fields);
        eprintln!("follow-flux generic/teaching relative field RMS={relative_rms:.6e}");
        // Frozen after the first shared-mesh calibration measured
        // 1.591265e-13. The gate leaves numerical-solver headroom without
        // becoming a percent-level physics tolerance.
        assert!(relative_rms < 1.0e-10);
    }

    #[test]
    fn iron_saturation_generic_path_stays_within_calibrated_percent_threshold() {
        let (mesh, materials, current_densities, region_labels) = build_follow_flux_mesh(
            "iron_saturation",
            "coarse",
            false,
            "bar",
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            false,
            44.0,
            0.0,
            0.0,
            0.0,
            100.0,
            &[],
            18.0,
            None,
        )
        .expect("iron-saturation mesh");
        let (_teaching_az, teaching_fields, _materials, _iterations) = solve_nonlinear_iron_field(
            &mesh,
            materials.clone(),
            &current_densities,
            &region_labels,
        )
        .expect("teaching nonlinear solve");
        let generic_problem = generic_problem_from_teaching_mesh(
            &mesh,
            &materials,
            &current_densities,
            &region_labels,
            true,
        );
        let generic = crate::field::solve(&generic_problem).expect("generic nonlinear solve");
        let teaching_mean_b = area_weighted_iron_b(&mesh, &region_labels, &teaching_fields);
        let generic_mean_b = area_weighted_iron_b(&mesh, &region_labels, &generic.element_fields);
        let delta_pct =
            ((generic_mean_b - teaching_mean_b) / teaching_mean_b.max(1.0e-12)).abs() * 100.0;
        eprintln!(
            "iron-saturation generic/teaching: teaching={teaching_mean_b:.6e}T generic={generic_mean_b:.6e}T delta={delta_pct:.3}%"
        );
        // The private grade measured 0.092%. The public snapshot's approved
        // M350-50A material transform measured 2.331%.
        let limit_pct = if teaching_iron_grade() == "M350-50A" {
            3.0
        } else {
            1.0
        };
        assert!(
            delta_pct < limit_pct,
            "cross-path delta {delta_pct:.3}% exceeds {limit_pct:.3}% for {}",
            teaching_iron_grade()
        );
    }

    #[test]
    fn follow_flux_second_magnet_adds_its_own_poles_and_couples_the_pair() {
        let base = |magnet2_enabled: bool, magnet2_angle_deg: f64| TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: false,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 28.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: -22.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled,
            magnet2_center_x_mm: 22.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: true,
        };

        let single = run(base(false, 0.0)).expect("single magnet should solve");
        assert!(
            !single
                .regions
                .iter()
                .any(|label| label.starts_with("magnet2_")),
            "a disabled second magnet must not tag any elements"
        );

        // Parallel magnetization attracts: both point +x, so magnet 1's north faces
        // magnet 2's south and the pair forms one continuous flux path across the gap.
        let attract = run(base(true, 0.0)).expect("attracting pair should solve");
        assert!(
            attract.regions.iter().any(|label| label == "magnet2_n"),
            "second magnet must contribute a north region"
        );
        assert!(
            attract.regions.iter().any(|label| label == "magnet2_s"),
            "second magnet must contribute a south region"
        );

        // Anti-parallel puts north against north; the fields oppose in the gap.
        let repel = run(base(true, 180.0)).expect("repelling pair should solve");

        let gap_mean = |report: &TeachingReport| {
            let mut total = 0.0;
            let mut count = 0usize;
            for (index, triangle) in report.triangles.iter().enumerate() {
                let x_mm = triangle.iter().map(|&i| report.nodes_mm[i][0]).sum::<f64>() / 3.0;
                let y_mm = triangle.iter().map(|&i| report.nodes_mm[i][1]).sum::<f64>() / 3.0;
                if x_mm.abs() <= 3.0 && y_mm.abs() <= 3.0 {
                    total += report.element_b_mag_t[index];
                    count += 1;
                }
            }
            assert!(
                count > 0,
                "expected elements in the gap between the magnets"
            );
            total / count as f64
        };

        let attract_gap = gap_mean(&attract);
        let repel_gap = gap_mean(&repel);
        assert!(
            attract_gap > repel_gap * 1.5,
            "attracting pair should drive far more flux across the gap than a repelling pair \
             (attract {attract_gap:.4} T vs repel {repel_gap:.4} T)"
        );
        assert!(
            attract_gap > gap_mean(&single),
            "adding an attracting second magnet should raise the gap field above one magnet alone"
        );
    }

    #[test]
    fn follow_flux_fixture_meshes_and_solves() {
        let air = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: false,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 28.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: true,
        })
        .expect("air fixture should solve");
        let steel = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: true,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 28.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: true,
        })
        .expect("steel fixture should solve");

        assert_eq!(air.nodes_mm.len(), air.mesh_info.num_nodes);
        assert_eq!(air.triangles.len(), air.mesh_info.num_triangles);
        assert_eq!(air.element_b_mag_t.len(), air.triangles.len());
        assert!(steel.regions.iter().any(|region| region == "steel_return"));
        assert!(steel
            .metrics
            .as_ref()
            .unwrap()
            .return_path_mean_b_t
            .is_some());
        assert!(
            steel.metrics.as_ref().unwrap().working_gap_mean_b_t
                > air.metrics.as_ref().unwrap().working_gap_mean_b_t
        );
    }

    #[test]
    fn magnetic_circuit_gap_changes_solved_flux() {
        let solve_gap = |gap_mm: f64| {
            run(TeachingRequest {
                fixture: "magnetic_circuit".to_string(),
                steel_return: true,
                steel_shape: "circuit".to_string(),
                steel_center_x_mm: gap_mm,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a: 0.0,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("magnetic-circuit fixture should solve")
        };

        let narrow = solve_gap(2.0);
        let wide = solve_gap(6.0);
        assert_eq!(narrow.fixture, "magnetic_circuit");
        assert!(narrow.regions.iter().any(|region| region == "steel_return"));
        assert!(
            narrow.metrics.as_ref().unwrap().working_gap_mean_b_t
                > wide.metrics.as_ref().unwrap().working_gap_mean_b_t
        );
    }

    #[test]
    fn current_wire_reverses_and_scales_probe_field() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "current_wire".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("current-wire fixture should solve")
        };

        let positive = solve_current(8.0);
        let negative = solve_current(-8.0);
        let doubled = solve_current(16.0);
        let positive_probe = positive
            .metrics
            .as_ref()
            .unwrap()
            .probe_tangential_b_t
            .unwrap();
        let negative_probe = negative
            .metrics
            .as_ref()
            .unwrap()
            .probe_tangential_b_t
            .unwrap();
        let doubled_probe = doubled
            .metrics
            .as_ref()
            .unwrap()
            .probe_tangential_b_t
            .unwrap();

        assert!(positive.regions.iter().any(|region| region == "wire"));
        assert!(positive_probe * negative_probe < 0.0);
        assert!((positive_probe.abs() - negative_probe.abs()).abs() < 1.0e-8);
        assert!((doubled_probe.abs() / positive_probe.abs() - 2.0).abs() < 0.08);
        let analytic_probe = crate::materials::MU_0 * 8.0 / (2.0 * std::f64::consts::PI * 0.015);
        assert!((positive_probe / analytic_probe - 1.0).abs() < 0.05);
    }

    #[test]
    fn current_force_reverses_and_scales_with_current() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "current_force".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("current-force fixture should solve")
        };

        let positive = solve_current(8.0);
        let negative = solve_current(-8.0);
        let doubled = solve_current(16.0);
        let positive_metrics = positive.metrics.as_ref().unwrap();
        let negative_metrics = negative.metrics.as_ref().unwrap();
        let doubled_metrics = doubled.metrics.as_ref().unwrap();
        let positive_force = positive_metrics.wire_force_y_n.unwrap();
        let negative_force = negative_metrics.wire_force_y_n.unwrap();
        let doubled_force = doubled_metrics.wire_force_y_n.unwrap();

        assert!(positive
            .regions
            .iter()
            .any(|region| region == "force_magnet_n"));
        assert!(positive
            .regions
            .iter()
            .any(|region| region == "force_magnet_s"));
        assert!(positive_metrics.wire_mean_bx_t.unwrap() > 0.0);
        assert!(positive_force > 0.0);
        assert!(negative_force < 0.0);
        assert!((positive_force.abs() - negative_force.abs()).abs() < 1.0e-6);
        assert!((doubled_force.abs() / positive_force.abs() - 2.0).abs() < 0.08);
        assert!((positive_force / positive_metrics.wire_force_bil_n.unwrap() - 1.0).abs() < 0.08);
    }

    #[test]
    fn linear_capstone_integrates_signed_winding_force_and_reverses_with_current() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "linear_motor_capstone".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 8.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, -1, 1, -1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "coarse".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("linear capstone solve")
        };

        let positive = solve_current(8.0);
        let negative = solve_current(-8.0);
        let positive_metrics = positive.metrics.expect("positive capstone metrics");
        let negative_metrics = negative.metrics.expect("negative capstone metrics");
        let positive_fx = positive_metrics.wire_force_x_n.expect("positive Fx");
        let negative_fx = negative_metrics.wire_force_x_n.expect("negative Fx");

        assert!(
            positive_fx < -1.0e-4,
            "expected +I force to point left: {positive_fx}"
        );
        assert!(
            negative_fx > 1.0e-4,
            "expected -I force to point right: {negative_fx}"
        );
        assert!((positive_fx.abs() - negative_fx.abs()).abs() / negative_fx.abs() < 0.05);
        assert_eq!(
            positive_metrics.teaching_depth_mm,
            Some(FORCE_TEACHING_DEPTH_MM)
        );
    }

    #[test]
    fn current_force_drops_as_symmetric_pole_gap_grows() {
        let solve_gap = |pole_gap_mm: f64| {
            run(TeachingRequest {
                fixture: "current_force".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                // The force fixture uses this otherwise-unused coordinate for the
                // symmetric surface gap between each pole and the wire.
                steel_center_x_mm: pole_gap_mm,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a: 8.0,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("adjustable pole-gap fixture should solve")
        };

        let close = solve_gap(0.5);
        let far = solve_gap(14.0);
        let close_metrics = close.metrics.as_ref().unwrap();
        let far_metrics = far.metrics.as_ref().unwrap();

        assert!(close_metrics.wire_mean_bx_t.unwrap() > far_metrics.wire_mean_bx_t.unwrap());
        assert!(close_metrics.wire_force_y_n.unwrap() > far_metrics.wire_force_y_n.unwrap());
    }

    #[test]
    fn current_force_wire_only_disables_permanent_magnet_sources() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "current_force_wire".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("wire-only force fixture should solve")
        };

        let energized = solve_current(8.0);
        let deenergized = solve_current(0.0);
        assert!(energized.regions.iter().any(|region| region == "wire"));
        assert!(energized
            .regions
            .iter()
            .any(|region| region == "force_magnet_n"));
        assert!(energized.metrics.as_ref().unwrap().peak_b_t > 1.0e-5);
        assert!(deenergized.metrics.as_ref().unwrap().peak_b_t < 1.0e-10);
        assert!(energized.metrics.as_ref().unwrap().wire_force_y_n.is_none());
    }

    #[test]
    fn quadrature_currents_rotate_the_center_field() {
        let solve_angle = |electrical_angle_deg: f64| {
            run(TeachingRequest {
                fixture: "rotating_field".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: electrical_angle_deg,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a: 8.0,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("rotating-field fixture should solve")
        };

        let horizontal = solve_angle(0.0);
        let vertical = solve_angle(90.0);
        let diagonal = solve_angle(45.0);
        let horizontal_metrics = horizontal.metrics.as_ref().unwrap();
        let vertical_metrics = vertical.metrics.as_ref().unwrap();
        let diagonal_metrics = diagonal.metrics.as_ref().unwrap();
        assert!(horizontal
            .regions
            .iter()
            .any(|region| region == "phase_a_positive"));
        assert!(horizontal_metrics.center_bx_t.unwrap() > 0.0);
        assert!(
            horizontal_metrics.center_by_t.unwrap().abs()
                < horizontal_metrics.center_bx_t.unwrap() * 1.0e-3
        );
        assert!(vertical_metrics.center_by_t.unwrap() > 0.0);
        assert!(
            vertical_metrics.center_bx_t.unwrap().abs()
                < vertical_metrics.center_by_t.unwrap() * 1.0e-3
        );
        assert!((diagonal_metrics.center_field_angle_deg.unwrap() - 45.0).abs() < 1.0);

        let horizontal_b = horizontal_metrics.center_b_t.unwrap();
        let vertical_b = vertical_metrics.center_b_t.unwrap();
        let diagonal_b = diagonal_metrics.center_b_t.unwrap();
        assert!((vertical_b / horizontal_b - 1.0).abs() < 0.04);
        assert!((diagonal_b / horizontal_b - 1.0).abs() < 0.04);
    }

    #[test]
    fn rotating_field_motor_contains_four_pole_windings_and_pm_rotor() {
        let report = run(TeachingRequest {
            fixture: "rotating_field_motor".to_string(),
            steel_return: false,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 0.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 345.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 8.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "fine".to_string(),
            imported_mesh: None,
            solve: false,
        })
        .expect("four-pole rotating-field motor fixture should build");

        assert!(report
            .regions
            .iter()
            .any(|region| region == "motor_rotor_magnet"));
        assert!(report
            .regions
            .iter()
            .any(|region| region == "motor_stator_pole"));
        assert!(report
            .regions
            .iter()
            .any(|region| region == "phase_a_left_top"));
        assert!(report
            .regions
            .iter()
            .any(|region| region == "phase_b_top_left"));
        assert_eq!(report.config_summary.poles, 4);
        assert!((report.config_summary.rotor_od_mm - 14.0).abs() < 1.0e-9);
    }

    #[test]
    fn rotating_field_motor_source_views_keep_the_same_geometry() {
        for fixture in ["rotating_field_motor_stator", "rotating_field_motor_rotor"] {
            let report = run(TeachingRequest {
                fixture: fixture.to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 345.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a: 8.0,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "coarse".to_string(),
                imported_mesh: None,
                solve: false,
            })
            .expect("motor source view should build");

            assert!(report
                .regions
                .iter()
                .any(|region| region == "motor_rotor_magnet"));
            assert!(report
                .regions
                .iter()
                .any(|region| region == "motor_stator_pole"));
            assert!(report
                .regions
                .iter()
                .any(|region| region == "phase_a_left_top"));
        }
    }

    #[test]
    fn three_phase_motor_contains_six_wound_teeth_and_pm_rotor() {
        let report = run(TeachingRequest {
            fixture: "three_phase_motor".to_string(),
            steel_return: false,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 0.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 345.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 8.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "coarse".to_string(),
            imported_mesh: None,
            solve: false,
        })
        .expect("three-phase motor fixture should build");

        assert!(report
            .regions
            .iter()
            .any(|region| region == "three_phase_rotor_magnet"));
        assert!(report
            .regions
            .iter()
            .any(|region| region == "three_phase_stator_pole"));
        let unique_regions: std::collections::HashSet<&str> =
            report.regions.iter().map(String::as_str).collect();
        for phase in ["a", "b", "c"] {
            let prefix = format!("phase_{phase}_");
            assert_eq!(
                unique_regions
                    .iter()
                    .filter(|region| region.starts_with(&prefix))
                    .count(),
                4
            );
        }
        assert_eq!(report.config_summary.poles, 2);
    }

    #[test]
    fn iron_ring_follows_the_m350_50a_saturation_knee() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "iron_saturation".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "fine".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("iron-saturation fixture should solve")
        };

        let low = solve_current(10.0);
        let medium = solve_current(100.0);
        let high = solve_current(800.0);
        let low_metrics = low.metrics.as_ref().unwrap();
        let medium_metrics = medium.metrics.as_ref().unwrap();
        let high_metrics = high.metrics.as_ref().unwrap();

        assert!(low.regions.iter().any(|region| region == "iron_ring"));
        assert!(low.bh_curve.as_ref().is_some_and(|curve| curve.len() > 30));
        assert!(medium_metrics.iron_mean_b_t.unwrap() > low_metrics.iron_mean_b_t.unwrap());
        assert!(high_metrics.iron_mean_b_t.unwrap() > medium_metrics.iron_mean_b_t.unwrap());
        assert!(
            high_metrics.iron_effective_mu_rel.unwrap()
                < medium_metrics.iron_effective_mu_rel.unwrap()
        );
        assert!(high_metrics.iron_saturated_fraction.unwrap() > 0.05);
        assert!(high_metrics.nonlinear_iterations.unwrap() > 1);
    }

    #[test]
    fn concentrated_tooth_reports_local_saturation_and_useful_airgap_flux() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "iron_saturation_tooth".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "coarse".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("iron-tooth fixture should solve")
        };

        let low = solve_current(1.0);
        let high = solve_current(20.0);
        let low_metrics = low.metrics.as_ref().unwrap();
        let high_metrics = high.metrics.as_ref().unwrap();

        for region in [
            "iron_tooth",
            "iron_yoke",
            "iron_return_tooth",
            "iron_rotor",
            "tooth_coil_out",
            "tooth_coil_in",
        ] {
            assert!(low.regions.iter().any(|candidate| candidate == region));
        }
        assert!(high_metrics.tooth_mean_b_t.unwrap() > low_metrics.tooth_mean_b_t.unwrap());
        assert!(
            high_metrics.airgap_flux_per_depth_wb_per_m.unwrap()
                > low_metrics.airgap_flux_per_depth_wb_per_m.unwrap()
        );
        assert!(high_metrics.tooth_saturated_fraction.unwrap() > 0.05);
        assert!(high_metrics.nonlinear_iterations.unwrap() > 1);
    }

    #[test]
    fn spm_tooth_separates_magnet_baseline_from_reinforcing_current() {
        let solve_current = |wire_current_a: f64| {
            run(TeachingRequest {
                fixture: "iron_saturation_spm_tooth".to_string(),
                steel_return: false,
                steel_shape: "bar".to_string(),
                steel_center_x_mm: 0.0,
                steel_center_y_mm: 0.0,
                magnet_center_x_mm: 0.0,
                magnet_center_y_mm: 0.0,
                magnet_angle_deg: 0.0,
                magnet2_enabled: false,
                magnet2_center_x_mm: 44.0,
                magnet2_center_y_mm: 0.0,
                magnet2_angle_deg: 0.0,
                steel_angle_deg: 0.0,
                wire_current_a,
                capstone_magnet_orientations: vec![1, 1, 1, 1],
                capstone_winding_spacing_mm: 18.0,
                mesh_density: "coarse".to_string(),
                imported_mesh: None,
                solve: true,
            })
            .expect("SPM-tooth fixture should solve")
        };

        let baseline = solve_current(0.0);
        let reinforced = solve_current(20.0);
        let baseline_metrics = baseline.metrics.as_ref().unwrap();
        let reinforced_metrics = reinforced.metrics.as_ref().unwrap();

        assert!(baseline
            .regions
            .iter()
            .any(|region| region == "spm_magnet_n"));
        assert!(baseline_metrics.airgap_mean_b_t.unwrap() > 0.1);
        assert!(
            reinforced_metrics.airgap_flux_per_depth_wb_per_m.unwrap()
                > baseline_metrics.airgap_flux_per_depth_wb_per_m.unwrap()
        );
        assert!(reinforced_metrics.tooth_saturated_fraction.unwrap() > 0.05);
        assert_eq!(reinforced.config_summary.magnet_thickness_mm, 5.0);
    }

    #[test]
    fn movable_steel_shapes_change_the_field_and_reject_overlap() {
        let plate = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: true,
            steel_shape: "plate".to_string(),
            steel_center_x_mm: 0.0,
            steel_center_y_mm: 16.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: true,
        })
        .expect("plate fixture should solve");
        let puck = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: true,
            steel_shape: "puck".to_string(),
            steel_center_x_mm: 31.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: true,
        })
        .expect("puck fixture should solve");
        let overlapping = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: true,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 12.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: false,
        });

        assert_eq!(plate.steel_shape, "plate");
        assert_eq!(puck.steel_shape, "puck");
        assert_ne!(
            plate.metrics.as_ref().unwrap().outside_field_mean_b_t,
            puck.metrics.as_ref().unwrap().outside_field_mean_b_t,
        );
        assert!(overlapping
            .expect_err("overlapping steel should be rejected")
            .contains("must not overlap"));

        let moved_magnet = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: true,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 28.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: -8.0,
            magnet_center_y_mm: 10.0,
            magnet_angle_deg: 25.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: -20.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: None,
            solve: true,
        })
        .expect("independently moved magnet should solve");
        assert_eq!(moved_magnet.magnet_center_x_mm, -8.0);
        assert_eq!(moved_magnet.magnet_center_y_mm, 10.0);
        assert_eq!(moved_magnet.magnet_angle_deg, 25.0);
        assert_eq!(moved_magnet.steel_angle_deg, -20.0);
    }

    #[test]
    fn imported_gmsh_mesh_provenance_is_preserved() {
        let report = run(TeachingRequest {
            fixture: "follow_flux".to_string(),
            steel_return: false,
            steel_shape: "bar".to_string(),
            steel_center_x_mm: 28.0,
            steel_center_y_mm: 0.0,
            magnet_center_x_mm: 0.0,
            magnet_center_y_mm: 0.0,
            magnet_angle_deg: 0.0,
            magnet2_enabled: false,
            magnet2_center_x_mm: 44.0,
            magnet2_center_y_mm: 0.0,
            magnet2_angle_deg: 0.0,
            steel_angle_deg: 0.0,
            wire_current_a: 0.0,
            capstone_magnet_orientations: vec![1, 1, 1, 1],
            capstone_winding_spacing_mm: 18.0,
            mesh_density: "normal".to_string(),
            imported_mesh: Some(TeachingMeshInput {
                nodes_mm: vec![[-50.0, -34.0], [50.0, -34.0], [50.0, 34.0], [-50.0, 34.0]],
                triangles: vec![[0, 1, 2], [0, 2, 3]],
                boundary_nodes: vec![0, 1, 2, 3],
                source_detail: "gmsh test mesh".to_string(),
                corner_refinement: true,
            }),
            solve: false,
        })
        .expect("imported Gmsh teaching mesh should load");

        assert_eq!(report.mesh_info.mesh_source, "gmsh");
        assert_eq!(report.mesh_info.mesh_source_detail, "gmsh test mesh");
        assert!(report.mesh_info.corner_refinement);
        assert_eq!(report.mesh_info.num_triangles, 2);
    }
}
