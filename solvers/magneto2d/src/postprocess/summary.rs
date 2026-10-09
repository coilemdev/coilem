use serde::Serialize;
use std::{env, f64::consts::PI};

use crate::materials::SteinmetzCoefficients;
use crate::mesh::{Region, TriMesh};
use crate::sources::{
    flux_linkage_slot_side_turn_factor, phase_slot_side_phasor_magnitudes, slot_center_angle_rad,
    slot_index_from_theta, slot_winding_layers, SlotExcitationContribution,
};

use super::{
    barycentric_weights, compute_nodal_b_field, compute_torque_arkkio_debug,
    compute_torque_at_multiple_radii, compute_torque_at_multiple_radii_from_az,
    compute_torque_debug, compute_torque_midgap_contour_debug,
    compute_torque_midgap_contour_debug_from_az, compute_torque_robust_contour_debug,
    compute_torque_weighted_stress_debug_with_az, triangle_area, ArkkioTorqueDebug,
    ContourTorqueDebug, ElementField, RobustContourTorqueDebug, TorqueDebug,
    WeightedStressTorqueDebug,
};

const AZ_CONTOUR_MAX_REL_SPLIT: f64 = 0.50;
const AZ_CONTOUR_ABS_SPLIT_FLOOR_NM: f64 = 1.0e-3;

#[derive(Debug, Clone, PartialEq)]
struct ContourTorqueSelection {
    use_az: bool,
    split_rel: Option<f64>,
    path: String,
    reason: String,
}

fn truthy_flag_value(value: &str) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    !normalized.is_empty()
        && normalized != "0"
        && normalized != "false"
        && normalized != "no"
        && normalized != "off"
}

fn field_spectrum_diagnostics_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_FIELD_DIAGNOSTICS",
        "MAGNETO2D_FIELD_DIAGNOSTICS",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn contour_torque_guard_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_CONTOUR_TORQUE_GUARD",
        "MAGNETO2D_CONTOUR_TORQUE_GUARD",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn robust_contour_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_ROBUST_CONTOUR",
        "MAGNETO2D_ROBUST_CONTOUR",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn robust_contour_primary_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_ROBUST_CONTOUR_PRIMARY",
        "MAGNETO2D_ROBUST_CONTOUR_PRIMARY",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn weighted_stress_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_TORQUE",
        "MAGNETO2D_WEIGHTED_STRESS_TORQUE",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn weighted_stress_primary_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_PRIMARY",
        "MAGNETO2D_WEIGHTED_STRESS_PRIMARY",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn weighted_stress_taper_residual_gate_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_RESIDUAL_GATE",
        "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_RESIDUAL_GATE",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn fast_arkkio_only_enabled() -> bool {
    [
        "COILEM_MAGNETO2D_FAST_ARKKIO_ONLY",
        "MAGNETO2D_FAST_ARKKIO_ONLY",
    ]
    .iter()
    .any(|name| {
        env::var(name)
            .map(|value| truthy_flag_value(&value))
            .unwrap_or(false)
    })
}

fn skipped_contour_debug(reason: &str, fallback_torque_nm: f64) -> ContourTorqueDebug {
    ContourTorqueDebug {
        status: "skipped".to_string(),
        error: Some(reason.to_string()),
        radius_mm: 0.0,
        sample_count: 0,
        total_span_deg: 0.0,
        unique_triangle_count: 0,
        modeled_torque_nm: fallback_torque_nm,
        scale_factor: 1.0,
        scaled_torque_nm: fallback_torque_nm,
        samples: Vec::new(),
        per_quadrant: None,
    }
}

fn apply_weighted_stress_taper_residual_gate(
    debug: &mut WeightedStressTorqueDebug,
    target_torque_nm: Option<f64>,
) {
    if !weighted_stress_taper_residual_gate_enabled()
        || !debug.boundary_wedge_taper_applied
        || debug.boundary_wedge_taper_removed_nm.abs() <= f64::EPSILON
    {
        return;
    }
    let Some(target_torque_nm) = target_torque_nm else {
        return;
    };
    if !target_torque_nm.is_finite() {
        return;
    }

    let tapered_scaled_nm = debug.scaled_torque_nm;
    let raw_modeled_nm = debug.modeled_torque_nm + debug.boundary_wedge_taper_removed_nm;
    let raw_scaled_nm = raw_modeled_nm * debug.scale_factor;
    let raw_residual_nm = (raw_scaled_nm - target_torque_nm).abs();
    let tapered_residual_nm = (tapered_scaled_nm - target_torque_nm).abs();

    if raw_residual_nm <= tapered_residual_nm {
        debug.modeled_torque_nm = raw_modeled_nm;
        debug.scaled_torque_nm = raw_scaled_nm;
        debug.boundary_wedge_taper_applied = false;
        debug.boundary_wedge_taper_gate_reason = Some(format!(
            "residual gate kept raw WST: raw_residual={raw_residual_nm:.6e} Nm <= tapered_residual={tapered_residual_nm:.6e} Nm against contour target {target_torque_nm:.6e} Nm"
        ));
    } else {
        debug.boundary_wedge_taper_gate_reason = Some(format!(
            "residual gate kept tapered WST: tapered_residual={tapered_residual_nm:.6e} Nm < raw_residual={raw_residual_nm:.6e} Nm against contour target {target_torque_nm:.6e} Nm"
        ));
    }
}

fn select_contour_torque_path(
    az_debug: Option<&ContourTorqueDebug>,
    nodal_b_debug: &ContourTorqueDebug,
) -> ContourTorqueSelection {
    let Some(az_debug) = az_debug else {
        return ContourTorqueSelection {
            use_az: false,
            split_rel: None,
            path: "nodal_b".to_string(),
            reason: "A_z contour unavailable for this model span".to_string(),
        };
    };

    if az_debug.status != "ok" {
        return ContourTorqueSelection {
            use_az: false,
            split_rel: None,
            path: "nodal_b".to_string(),
            reason: format!(
                "A_z contour status={} ({})",
                az_debug.status,
                az_debug.error.as_deref().unwrap_or("no detail")
            ),
        };
    }

    if nodal_b_debug.status != "ok" {
        return ContourTorqueSelection {
            use_az: true,
            split_rel: None,
            path: "az".to_string(),
            reason: format!(
                "nodal-B contour status={} ({})",
                nodal_b_debug.status,
                nodal_b_debug.error.as_deref().unwrap_or("no detail")
            ),
        };
    }

    let az_nm = az_debug.scaled_torque_nm;
    let nodal_b_nm = nodal_b_debug.scaled_torque_nm;
    let split_abs = (az_nm - nodal_b_nm).abs();
    let denom = az_nm
        .abs()
        .max(nodal_b_nm.abs())
        .max(AZ_CONTOUR_ABS_SPLIT_FLOOR_NM);
    let split_rel = split_abs / denom;
    let agrees =
        split_abs <= AZ_CONTOUR_ABS_SPLIT_FLOOR_NM || split_rel <= AZ_CONTOUR_MAX_REL_SPLIT;

    if agrees {
        ContourTorqueSelection {
            use_az: true,
            split_rel: Some(split_rel),
            path: "az".to_string(),
            reason: format!(
                "A_z/nodal-B contour split {:.1}% within guard (az={:.6e} Nm, nodal_b={:.6e} Nm)",
                100.0 * split_rel,
                az_nm,
                nodal_b_nm
            ),
        }
    } else {
        ContourTorqueSelection {
            use_az: false,
            split_rel: Some(split_rel),
            path: "nodal_b".to_string(),
            reason: format!(
                "A_z/nodal-B contour split {:.1}% exceeds guard (az={:.6e} Nm, nodal_b={:.6e} Nm)",
                100.0 * split_rel,
                az_nm,
                nodal_b_nm
            ),
        }
    }
}

/// Per-slot contribution used to build phase flux linkage.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SlotFluxLinkageContribution {
    pub slot_index_modeled: usize,
    pub slot_index_global: usize,
    pub phase: String,
    pub direction: String,
    pub center_angle_mech_deg: f64,
    pub az_reference_wb_per_m: f64,
    pub az_avg_wb_per_m: f64,
    pub az_effective_wb_per_m: f64,
    pub slot_area_m2: f64,
    pub turns_per_coil: u32,
    pub contribution_wb: f64,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct EnergyByRegionSummary {
    pub rotor_core_j: f64,
    pub magnet_j: f64,
    pub airgap_j: f64,
    pub stator_tooth_j: f64,
    pub stator_yoke_j: f64,
    pub slot_winding_j: f64,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct MagnetFieldEnergyDetailSummary {
    pub radial_inner_j: f64,
    pub radial_middle_j: f64,
    pub radial_outer_j: f64,
    pub angular_edge_j: f64,
    pub angular_interior_j: f64,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct PmSidewallQuadratureDiagnosticSummary {
    pub enabled: bool,
    pub pm_source_scale: f64,
    pub field_scale: f64,
    pub coenergy_scale: f64,
    pub side_window_mm: f64,
    pub radial_depth_mm: f64,
    pub selected_count: usize,
    pub selected_area_mm2: f64,
    pub base_field_energy_j: f64,
    pub scaled_field_energy_j: f64,
    pub field_energy_delta_j: f64,
    pub base_pm_source_work_j: f64,
    pub scaled_pm_source_work_j: f64,
    pub pm_source_work_delta_j: f64,
    pub base_coenergy_j: f64,
    pub scaled_coenergy_j: f64,
    pub coenergy_delta_j: f64,
    pub selected_elements: Vec<PmSidewallQuadratureSelectedElement>,
}

#[derive(Debug, Clone, Serialize)]
pub struct PmSidewallQuadratureSelectedElement {
    pub tri_idx: usize,
    pub region: String,
    pub centroid_x_mm: f64,
    pub centroid_y_mm: f64,
    pub centroid_r_mm: f64,
    pub centroid_theta_deg: f64,
    pub area_mm2: f64,
    pub radial_delta_mm: f64,
    pub side_distance_mm: f64,
    pub pole_offset_deg: f64,
    pub nominal_side_pole_offset_deg: f64,
    pub base_field_energy_j: f64,
    pub scaled_field_energy_j: f64,
    pub base_pm_source_work_j: f64,
    pub scaled_pm_source_work_j: f64,
    pub base_coenergy_j: f64,
    pub scaled_coenergy_j: f64,
    pub coenergy_delta_j: f64,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct EnergyFunctionalSummary {
    pub field_energy_j: f64,
    pub field_energy_by_region_j: EnergyByRegionSummary,
    pub field_energy_magnet_detail_j: MagnetFieldEnergyDetailSummary,
    pub current_source_work_j: f64,
    pub pm_source_work_j: f64,
    pub pm_source_work_magnet_detail_j: MagnetFieldEnergyDetailSummary,
    pub pm_self_energy_j: f64,
    pub potential_energy_j: f64,
    pub potential_energy_with_pm_self_j: f64,
    pub coenergy_j: f64,
    pub coenergy_by_region_j: EnergyByRegionSummary,
    pub coenergy_magnet_detail_j: MagnetFieldEnergyDetailSummary,
    pub scale_factor: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pm_sidewall_quadrature_diagnostic: Option<PmSidewallQuadratureDiagnosticSummary>,
}

/// Summary of electromagnetic results.
#[derive(Debug, Clone, Serialize)]
pub struct FieldSummary {
    pub peak_b_airgap_t: f64,
    pub mean_b_airgap_t: f64,
    pub peak_b_tooth_t: f64,
    pub peak_b_yoke_t: f64,
    /// FEMM-like point-sampled tooth peak B at the tooth midpoint radius.
    pub peak_b_tooth_point_t: f64,
    /// FEMM-like point-sampled yoke peak B at the yoke midpoint radius.
    pub peak_b_yoke_point_t: f64,
    /// Primary torque value — uses the mid-gap contour MST method.
    pub torque_nm: f64,
    /// Legacy area-based MST torque (unreliable on real motor geometry
    /// due to boundary element contamination; kept for diagnostics).
    pub torque_area_mst_nm: f64,
    pub torque_debug: TorqueDebug,
    pub torque_contour_nm: f64,
    pub torque_contour_inner_nm: f64,
    pub torque_contour_outer_nm: f64,
    pub torque_contour_multi_radius_diagnostics: String,
    pub torque_contour_selection: String,
    pub torque_contour_selection_reason: String,
    pub torque_contour_guard_enabled: bool,
    pub torque_contour_az_nm: Option<f64>,
    pub torque_contour_nodal_b_nm: f64,
    pub torque_contour_az_nodal_b_split_rel: Option<f64>,
    pub torque_contour_robust_nm: Option<f64>,
    pub torque_contour_robust_primary_enabled: bool,
    pub torque_contour_robust_debug: Option<RobustContourTorqueDebug>,
    pub torque_weighted_stress_nm: Option<f64>,
    pub torque_weighted_stress_primary_enabled: bool,
    pub torque_weighted_stress_debug: Option<WeightedStressTorqueDebug>,
    pub torque_contour_debug: ContourTorqueDebug,
    pub torque_arkkio_nm: f64,
    pub torque_arkkio_debug: ArkkioTorqueDebug,
    pub energy_functional: EnergyFunctionalSummary,
    pub source_current_angle_deg: f64,
    pub phase_current_a: [f64; 3],
    pub slot_excitation_contributions: Vec<SlotExcitationContribution>,
    pub flux_linkage_a_wb: f64,
    pub flux_linkage_b_wb: f64,
    pub flux_linkage_c_wb: f64,
    pub slot_flux_linkage_contributions: Vec<SlotFluxLinkageContribution>,
    pub num_elements_solved: usize,
}

/// Integrated stator iron loss from per-element B-field history.
#[derive(Debug, Clone, Serialize, Default, PartialEq)]
pub struct CoreLossSummary {
    pub core_loss_w: f64,
    pub hysteresis_loss_w: f64,
    pub eddy_current_loss_w: f64,
    pub stator_core_mass_kg: f64,
    /// Per-triangle volumetric core-loss density [W/m³] (same length as
    /// `mesh.triangles`). Non-stator elements are 0. Used by thermal
    /// loss-map export; omitted from older callers that only need totals.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub core_loss_density_w_per_m3: Option<Vec<f64>>,
}
/// Compute flux linkage per phase from A_z solution.
///
/// For multi-pole-pitch models, all slots in the sector are included.
/// Scale by (pole_count / n_pole_pitches) to get full motor.
pub fn compute_flux_linkage(
    mesh: &TriMesh,
    az: &[f64],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    winding_type: &str,
    slot_count: u32,
    pole_count: u32,
    turns_per_coil: u32,
    winding_layers: u32,
    coil_span: Option<u32>,
    slot_side_turn_factor: f64,
    subtract_slot_az_reference: bool,
) -> ([f64; 3], Vec<SlotFluxLinkageContribution>) {
    let l_stack = stack_length_mm * 1e-3;
    let n_pole_pitches = mesh.info.n_pole_pitches;
    let pole_pitch_rad = 2.0 * PI / pole_count as f64;
    let slots_per_pole = slot_count as f64 / pole_count as f64;
    let slot_pitch_rad = pole_pitch_rad / slots_per_pole;

    // Total number of slots in the modeled sector.
    let total_slots_in_span = (slots_per_pole * n_pole_pitches as f64).ceil() as usize;

    let mut slot_az_integral = vec![0.0_f64; total_slots_in_span];
    let mut slot_area_total = vec![0.0_f64; total_slots_in_span];
    let mut slot_phase = vec![0usize; total_slots_in_span];
    let mut slot_direction = vec![1.0_f64; total_slots_in_span];
    let mut slot_assigned = vec![false; total_slots_in_span];

    for (idx, (tri, region)) in mesh.triangles.iter().zip(mesh.regions.iter()).enumerate() {
        // Align slot/tooth filtering with the canonical FEMM convention.
        // Instead of relying solely on pre-classified region tags (which use cell-center angles),
        // we now verify based on actual centroid angle whether the triangle is in a slot or tooth.
        // This ensures consistency with how slots are extracted via slot_index_from_theta().

        if *region != Region::SlotWinding {
            continue;
        }

        let [i, j, m] = *tri;
        let area = triangle_area(&mesh.nodes, i, j, m);
        let az_avg = (az[i] + az[j] + az[m]) / 3.0;

        let cx = centroids[idx][0];
        let cy = centroids[idx][1];
        let theta = cy.atan2(cx);
        let theta_pos = if theta < 0.0 { theta + 2.0 * PI } else { theta };
        let slot_local = slot_index_from_theta(theta_pos, slot_pitch_rad, total_slots_in_span);
        let slot_idx = slot_local;

        slot_az_integral[slot_idx] += az_avg * area;
        slot_area_total[slot_idx] += area;

        if !slot_assigned[slot_idx] {
            let slot_global = slot_local % slot_count as usize;
            // Dispatch on the payload winding type so distributed
            // configs group slot flux linkages with the distributed phase-belt
            // layout instead of silently reusing the concentrated map.
            let (phase, dir, _) = slot_winding_layers(
                winding_type,
                slot_global,
                slot_count,
                pole_count,
                winding_layers,
                coil_span,
            )[0];
            slot_phase[slot_idx] = phase;
            slot_direction[slot_idx] = if dir { 1.0 } else { -1.0 };
            slot_assigned[slot_idx] = true;
        }
    }

    let diagnostics_enabled = field_spectrum_diagnostics_enabled();
    if diagnostics_enabled {
        // Debug: check 4-fold symmetry of A_z.
        // For 8-pole (4 pole pairs), A_z should repeat every 90° mech.
        let full_circle = (mesh.info.total_span_deg - 360.0).abs() < 1e-6;
        let n_theta_ring = if full_circle {
            mesh.info.angular_divisions
        } else {
            mesh.info.angular_divisions + 1
        };
        eprintln!("  A_z symmetry check (quarter-machine should repeat):");
        // Pick a mid-radius ring using the actual mesh metadata.
        let ring_idx = mesh.info.radial_rings / 2;
        let quarter = n_theta_ring / 4; // nodes per quarter
        if quarter > 2 {
            // Print A_z at the mid-radius for angles 0, 90, 180, 270.
            let ring_start = ring_idx * n_theta_ring;
            for q in 0..4 {
                let node = ring_start + q * quarter;
                if node < az.len() {
                    let nx = mesh.nodes[node][0];
                    let ny = mesh.nodes[node][1];
                    let theta_deg = ny.atan2(nx).to_degrees();
                    eprintln!("    node[{}] @{:.1}°: az={:.6e}", node, theta_deg, az[node]);
                }
            }
        }

        // Debug: also compute A_z average in each tooth for reference.
        let tooth_slots_per_pole = slot_count as f64 / pole_count as f64;
        let tooth_slot_pitch = pole_pitch_rad / tooth_slots_per_pole;
        let n_teeth_total = total_slots_in_span + 1;
        let mut tooth_az_sum = vec![0.0_f64; n_teeth_total];
        let mut tooth_area_sum = vec![0.0_f64; n_teeth_total];
        for (idx, (tri, region)) in mesh.triangles.iter().zip(mesh.regions.iter()).enumerate() {
            if *region != Region::StatorTooth {
                continue;
            }
            let [i, j, m] = *tri;
            let area = triangle_area(&mesh.nodes, i, j, m);
            let az_avg = (az[i] + az[j] + az[m]) / 3.0;
            let cx = centroids[idx][0];
            let cy = centroids[idx][1];
            let theta = cy.atan2(cx);
            let theta_pos = if theta < 0.0 { theta + 2.0 * PI } else { theta };
            // Teeth are at multiples of slot_pitch; find nearest tooth.
            let tooth_idx = (theta_pos / tooth_slot_pitch + 0.5).floor() as usize;
            let tooth_idx = tooth_idx.min(n_teeth_total - 1);
            tooth_az_sum[tooth_idx] += az_avg * area;
            tooth_area_sum[tooth_idx] += area;
        }
        eprintln!("  TOOTH A_z pattern (first 13 teeth):");
        for t in 0..n_teeth_total.min(13) {
            if tooth_area_sum[t] > 1e-15 {
                let az_t = tooth_az_sum[t] / tooth_area_sum[t];
                let theta_deg = t as f64 * tooth_slot_pitch * 180.0 / PI;
                eprintln!(
                    "    tooth[{}] @{:.1}°mech: az_avg={:.6e}",
                    t, theta_deg, az_t
                );
            }
        }
    }

    let mut phase_flux = [0.0_f64; 3];
    let mut slot_contributions = Vec::new();
    let total_slot_area: f64 = slot_area_total.iter().sum();
    let occupied_slot_count = slot_area_total
        .iter()
        .filter(|area| **area >= 1e-15)
        .count();
    let slot_az_reference =
        if subtract_slot_az_reference && occupied_slot_count > 1 && total_slot_area > 1e-15 {
            slot_az_integral.iter().sum::<f64>() / total_slot_area
        } else {
            0.0
        };

    if diagnostics_enabled {
        eprintln!(
            "  SLOT flux linkage breakdown: az_reference={:.6e} Wb/m",
            slot_az_reference
        );
    }
    for s in 0..total_slots_in_span {
        if slot_area_total[s] < 1e-15 {
            continue;
        }
        let az_avg_slot = slot_az_integral[s] / slot_area_total[s];
        let az_effective_slot = az_avg_slot - slot_az_reference;
        let slot_global = s % slot_count as usize;
        if winding_type == "distributed" && coil_span.is_some() {
            let theta_deg = slot_center_angle_rad(s, slot_pitch_rad).to_degrees();
            for (phase, direction, turn_fraction) in slot_winding_layers(
                winding_type,
                slot_global,
                slot_count,
                pole_count,
                winding_layers,
                coil_span,
            ) {
                let dir_sign = if direction { 1.0 } else { -1.0 };
                let contrib = dir_sign
                    * turn_fraction
                    * slot_side_turn_factor
                    * turns_per_coil as f64
                    * l_stack
                    * az_effective_slot;
                phase_flux[phase] += contrib;
                if diagnostics_enabled {
                    eprintln!(
                        "    slot[{}] @{:.1}deg mech: phase={} dir={:+.0} turn_fraction={:.3} az_avg={:.6e} az_eff={:.6e} contrib={:.6e}",
                        s,
                        theta_deg,
                        ["A", "B", "C"][phase],
                        dir_sign,
                        turn_fraction,
                        az_avg_slot,
                        az_effective_slot,
                        contrib,
                    );
                }
                slot_contributions.push(SlotFluxLinkageContribution {
                    slot_index_modeled: s,
                    slot_index_global: slot_global,
                    phase: ["A", "B", "C"][phase].to_string(),
                    direction: if direction {
                        "in".to_string()
                    } else {
                        "out".to_string()
                    },
                    center_angle_mech_deg: theta_deg,
                    az_reference_wb_per_m: slot_az_reference,
                    az_avg_wb_per_m: az_avg_slot,
                    az_effective_wb_per_m: az_effective_slot,
                    slot_area_m2: slot_area_total[s],
                    turns_per_coil,
                    contribution_wb: contrib,
                });
            }
            continue;
        }
        let phase = slot_phase[s];
        let contrib = slot_direction[s]
            * slot_side_turn_factor
            * turns_per_coil as f64
            * l_stack
            * az_effective_slot;
        phase_flux[phase] += contrib;
        let theta_deg = slot_center_angle_rad(s, slot_pitch_rad).to_degrees();
        let slot_global = s % slot_count as usize;
        if diagnostics_enabled {
            eprintln!(
                "    slot[{}] @{:.1}°mech: phase={} dir={:+.0} az_avg={:.6e} az_eff={:.6e} contrib={:.6e}",
                s,
                theta_deg,
                ["A", "B", "C"][phase],
                slot_direction[s],
                az_avg_slot,
                az_effective_slot,
                contrib,
            );
        }
        slot_contributions.push(SlotFluxLinkageContribution {
            slot_index_modeled: s,
            slot_index_global: slot_global,
            phase: ["A", "B", "C"][phase].to_string(),
            direction: if slot_direction[s] > 0.0 {
                "in".to_string()
            } else {
                "out".to_string()
            },
            center_angle_mech_deg: theta_deg,
            az_reference_wb_per_m: slot_az_reference,
            az_avg_wb_per_m: az_avg_slot,
            az_effective_wb_per_m: az_effective_slot,
            slot_area_m2: slot_area_total[s],
            turns_per_coil,
            contribution_wb: contrib,
        });
    }

    // Scale from modeled sector to full motor.
    let scale = pole_count as f64 / n_pole_pitches as f64;
    for pf in &mut phase_flux {
        *pf *= scale;
    }
    for contribution in &mut slot_contributions {
        contribution.contribution_wb *= scale;
    }

    (phase_flux, slot_contributions)
}

/// Summarize field results by region.
pub fn summarize_fields(
    mesh: &TriMesh,
    fields: &[ElementField],
    az: &[f64],
    centroids: &[[f64; 2]],
    stack_length_mm: f64,
    pole_count: u32,
    slot_count: u32,
    turns_per_coil: u32,
    winding_type: &str,
    winding_layers: u32,
    parallel_paths: u32,
    coil_span: Option<u32>,
) -> FieldSummary {
    // Collect (b_mag, area) per region so peak-B reporting can
    // filter out sliver triangles (which pile up at reentrant corners and
    // report unphysical field magnitudes like 17 T / 28 T).
    let mut airgap_b: Vec<(f64, f64)> = Vec::new();
    let mut tooth_b: Vec<(f64, f64)> = Vec::new();
    let mut yoke_b: Vec<(f64, f64)> = Vec::new();

    for (idx, tri) in mesh.triangles.iter().enumerate() {
        let [i, j, m] = *tri;
        let area = triangle_area(&mesh.nodes, i, j, m);
        let b = fields[idx].b_mag;
        match mesh.regions[idx] {
            Region::Airgap => airgap_b.push((b, area)),
            Region::StatorTooth => tooth_b.push((b, area)),
            Region::StatorYoke => yoke_b.push((b, area)),
            _ => {}
        }
    }

    // === Diagnostic: A_z radial profile and Fourier analysis ===
    if field_spectrum_diagnostics_enabled() {
        // Group nodes by approximate radius to understand A_z spatial distribution.
        let mut radial_bins: std::collections::BTreeMap<i32, Vec<(f64, f64)>> =
            std::collections::BTreeMap::new();
        for (ni, node) in mesh.nodes.iter().enumerate() {
            let r = (node[0] * node[0] + node[1] * node[1]).sqrt();
            let r_mm = r * 1000.0;
            let bin = (r_mm * 2.0_f64).round() as i32; // 0.5mm bins
            radial_bins
                .entry(bin)
                .or_default()
                .push((node[1].atan2(node[0]), az[ni]));
        }

        eprintln!("  A_z RADIAL PROFILE (max |A_z| by radius):");
        for (&bin, nodes_at_r) in &radial_bins {
            let r_mm = bin as f64 / 2.0;
            let max_az = nodes_at_r
                .iter()
                .map(|(_, a)| a.abs())
                .fold(0.0_f64, f64::max);
            if max_az > 1e-8 && (bin % 4 == 0 || r_mm > 63.0 && r_mm < 67.0) {
                eprintln!("    r={:.1}mm: max|A_z|={:.6e}", r_mm, max_az);
            }
        }

        // Fourier analysis at the airgap mid-radius.
        // Find nodes closest to r = (magnet_outer + stator_inner) / 2.
        // We estimate this from the mesh node radii.
        let target_r_mm: f64 = 64.5; // approximate airgap center
        let target_bin = (target_r_mm * 2.0_f64).round() as i32;
        // Try nearby bins too.
        let mut airgap_nodes: Vec<(f64, f64)> = Vec::new();
        for db in -1..=1 {
            if let Some(nodes) = radial_bins.get(&(target_bin + db)) {
                airgap_nodes.extend_from_slice(nodes);
            }
        }
        if !airgap_nodes.is_empty() {
            airgap_nodes.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
            // Compute Fourier coefficients for harmonics p=1,2,3,4,5,8,12.
            eprintln!(
                "  A_z FOURIER at airgap (r≈{:.1}mm, {} nodes):",
                target_r_mm,
                airgap_nodes.len()
            );
            // Print a few A_z values at the airgap for debugging.
            eprintln!("    First 13 nodes:");
            for &(theta, az_val) in airgap_nodes.iter().take(13) {
                eprintln!("      θ={:.1}° az={:.6e}", theta.to_degrees(), az_val);
            }
            for p in &[1, 2, 3, 4, 5, 8, 12] {
                let pf = *p as f64;
                let mut cos_sum = 0.0_f64;
                let mut sin_sum = 0.0_f64;
                for &(theta, az_val) in &airgap_nodes {
                    cos_sum += az_val * (pf * theta).cos();
                    sin_sum += az_val * (pf * theta).sin();
                }
                let n = airgap_nodes.len() as f64;
                let amp = 2.0 * (cos_sum * cos_sum + sin_sum * sin_sum).sqrt() / n;
                let r_m = target_r_mm * 1e-3;
                eprintln!(
                    "    p={:2}: amp={:.6e} Wb/m → B_p={:.4}T",
                    p,
                    amp,
                    pf * amp / r_m
                );
            }
        }

        // Also compute max |A_z| per region.
        let mut max_az_by_region = [0.0_f64; 6]; // RotorCore, Magnet, Airgap, Tooth, Yoke, Slot
        for (idx, tri) in mesh.triangles.iter().enumerate() {
            let [i, j, m] = *tri;
            let max_tri = az[i].abs().max(az[j].abs()).max(az[m].abs());
            let ri = match mesh.regions[idx] {
                Region::RotorCore => 0,
                Region::Magnet => 1,
                Region::Airgap => 2,
                Region::StatorTooth => 3,
                Region::StatorYoke => 4,
                Region::SlotWinding => 5,
                Region::FluxBarrier | Region::MagnetPocketAir => 2,
            };
            max_az_by_region[ri] = max_az_by_region[ri].max(max_tri);
        }
        eprintln!("  Max |A_z| by region: rotor={:.4e} magnet={:.4e} airgap={:.4e} tooth={:.4e} yoke={:.4e} slot={:.4e}",
            max_az_by_region[0], max_az_by_region[1], max_az_by_region[2],
            max_az_by_region[3], max_az_by_region[4], max_az_by_region[5]);

        // Compute dynamic airgap radius range from mesh regions (not hardcoded).
        let mut airgap_r_min_mm = f64::INFINITY;
        let mut airgap_r_max_mm: f64 = 0.0;
        for (centroid, region) in centroids.iter().zip(mesh.regions.iter()) {
            if *region != Region::Airgap {
                continue;
            }
            let r_mm = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt() * 1000.0;
            airgap_r_min_mm = airgap_r_min_mm.min(r_mm);
            airgap_r_max_mm = airgap_r_max_mm.max(r_mm);
        }
        let airgap_mid_r_mm = (airgap_r_min_mm + airgap_r_max_mm) / 2.0;
        let airgap_half_band = (airgap_r_max_mm - airgap_r_min_mm) / 2.0 * 0.6;
        let airgap_filter_lo = airgap_mid_r_mm - airgap_half_band;
        let airgap_filter_hi = airgap_mid_r_mm + airgap_half_band;

        // Check B-field at specific airgap angles to understand distribution.
        eprintln!(
            "  B-field at specific airgap elements (under magnets, r={:.1}-{:.1}mm):",
            airgap_filter_lo, airgap_filter_hi
        );
        for angle_deg in &[10.0_f64, 22.5, 35.0, 55.0, 67.5, 80.0] {
            let target_theta = angle_deg.to_radians();
            let mut best_idx = 0usize;
            let mut best_dist = f64::MAX;
            for (idx, (centroid, region)) in centroids.iter().zip(mesh.regions.iter()).enumerate() {
                if *region != Region::Airgap {
                    continue;
                }
                let r_mm = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt() * 1000.0;
                if r_mm < airgap_filter_lo || r_mm > airgap_filter_hi {
                    continue;
                }
                let theta = centroid[1].atan2(centroid[0]);
                let dist = (theta - target_theta).abs();
                if dist < best_dist {
                    best_dist = dist;
                    best_idx = idx;
                }
            }
            if best_dist < 0.1 {
                let r = (centroids[best_idx][0].powi(2) + centroids[best_idx][1].powi(2)).sqrt();
                let theta_act = centroids[best_idx][1]
                    .atan2(centroids[best_idx][0])
                    .to_degrees();
                eprintln!(
                    "    θ={:.1}° (actual {:.1}°, r={:.1}mm): B_mag={:.4}T Bx={:.4} By={:.4}",
                    angle_deg,
                    theta_act,
                    r * 1000.0,
                    fields[best_idx].b_mag,
                    fields[best_idx].bx,
                    fields[best_idx].by
                );
            }
        }

        // Fourier of B_r at airgap elements.
        eprintln!("  B_r FOURIER at airgap elements:");
        let mut br_data: Vec<(f64, f64)> = Vec::new();
        for (idx, (centroid, region)) in centroids.iter().zip(mesh.regions.iter()).enumerate() {
            if *region != Region::Airgap {
                continue;
            }
            let r = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
            let r_mm = r * 1000.0;
            if r_mm < airgap_filter_lo || r_mm > airgap_filter_hi {
                continue;
            }
            let theta = centroid[1].atan2(centroid[0]);
            let cos_t = centroid[0] / r;
            let sin_t = centroid[1] / r;
            let b_r = fields[idx].bx * cos_t + fields[idx].by * sin_t;
            br_data.push((theta, b_r));
        }
        for p in &[1, 2, 3, 4, 5, 8, 12] {
            let pf = *p as f64;
            let mut cos_sum = 0.0_f64;
            let mut sin_sum = 0.0_f64;
            for &(theta, b_r) in &br_data {
                cos_sum += b_r * (pf * theta).cos();
                sin_sum += b_r * (pf * theta).sin();
            }
            let n = br_data.len() as f64;
            let amp = 2.0 * (cos_sum * cos_sum + sin_sum * sin_sum).sqrt() / n;
            eprintln!(
                "    p={:2}: B_r_amp={:.4}T ({} elements)",
                p,
                amp,
                br_data.len()
            );
        }
    }

    let torque_debug = compute_torque_debug(mesh, fields, centroids, stack_length_mm, pole_count);
    let torque_arkkio_debug =
        compute_torque_arkkio_debug(mesh, fields, centroids, stack_length_mm, pole_count);
    let full_circle_model = (mesh.info.total_span_deg - 360.0).abs() < 1e-6;
    let (
        torque_contour_debug,
        torque_contour_az_nm,
        torque_contour_nodal_b_nm,
        contour_selection,
        contour_guard_enabled,
        robust_primary_enabled,
        robust_debug,
        weighted_stress_primary_enabled,
        weighted_stress_debug,
        torque_contour_selection,
        torque_contour_selection_reason,
        selected_torque_nm,
        torque_contour_inner_nm,
        torque_contour_outer_nm,
        torque_contour_multi_radius_diagnostics,
    ) = if fast_arkkio_only_enabled() {
        let reason = "skipped contour diagnostics because fast Arkkio-only mode is enabled";
        (
            skipped_contour_debug(reason, torque_arkkio_debug.scaled_torque_nm),
            None,
            0.0,
            ContourTorqueSelection {
                use_az: false,
                split_rel: None,
                path: "arkkio".to_string(),
                reason: reason.to_string(),
            },
            false,
            false,
            None,
            false,
            None,
            "arkkio".to_string(),
            reason.to_string(),
            torque_arkkio_debug.scaled_torque_nm,
            torque_arkkio_debug.scaled_torque_nm,
            torque_arkkio_debug.scaled_torque_nm,
            reason.to_string(),
        )
    } else {
        let nodal_b_contour_debug =
            compute_torque_midgap_contour_debug(mesh, fields, stack_length_mm, pole_count);
        let az_contour_debug = if full_circle_model {
            Some(compute_torque_midgap_contour_debug_from_az(
                mesh,
                az,
                stack_length_mm,
                pole_count,
            ))
        } else {
            None
        };
        let torque_contour_az_nm = az_contour_debug
            .as_ref()
            .map(|debug| debug.status == "ok")
            .unwrap_or(false)
            .then(|| az_contour_debug.as_ref().unwrap().scaled_torque_nm);
        let torque_contour_nodal_b_nm = nodal_b_contour_debug.scaled_torque_nm;
        let contour_selection =
            select_contour_torque_path(az_contour_debug.as_ref(), &nodal_b_contour_debug);
        let contour_guard_enabled = contour_torque_guard_enabled();
        let robust_primary_enabled = robust_contour_primary_enabled();
        let robust_enabled = robust_primary_enabled || robust_contour_enabled();
        let robust_debug = if full_circle_model && robust_enabled {
            Some(compute_torque_robust_contour_debug(
                mesh,
                fields,
                az,
                stack_length_mm,
                pole_count,
            ))
        } else {
            None
        };
        let robust_ready = robust_debug
            .as_ref()
            .map(|debug| debug.status == "ok")
            .unwrap_or(false);
        let weighted_stress_primary_enabled = weighted_stress_primary_enabled();
        let weighted_stress_enabled = weighted_stress_primary_enabled || weighted_stress_enabled();
        let mut weighted_stress_debug = if weighted_stress_enabled {
            Some(compute_torque_weighted_stress_debug_with_az(
                mesh,
                fields,
                Some(az),
                stack_length_mm,
                pole_count,
            ))
        } else {
            None
        };
        if let Some(debug) = &mut weighted_stress_debug {
            apply_weighted_stress_taper_residual_gate(
                debug,
                torque_contour_az_nm.or(Some(torque_contour_nodal_b_nm)),
            );
        }
        let weighted_stress_ready = weighted_stress_debug
            .as_ref()
            .map(|debug| debug.status == "ok")
            .unwrap_or(false);
        let use_weighted_stress = weighted_stress_primary_enabled && weighted_stress_ready;
        let use_robust_contour = robust_primary_enabled && robust_ready;
        let az_contour_ready = torque_contour_az_nm.is_some();
        let use_az_contour = if contour_guard_enabled {
            contour_selection.use_az
        } else {
            az_contour_ready
        };
        let torque_contour_selection = if use_weighted_stress {
            "weighted_stress".to_string()
        } else if use_robust_contour {
            let robust = robust_debug
                .as_ref()
                .expect("robust contour selected only when ready");
            format!("robust_{}", robust.selected_source)
        } else if contour_guard_enabled {
            contour_selection.path.clone()
        } else if use_az_contour {
            "az".to_string()
        } else {
            "nodal_b".to_string()
        };
        let torque_contour_selection_reason = if use_weighted_stress {
            let debug = weighted_stress_debug
                .as_ref()
                .expect("weighted stress selected only when ready");
            format!(
                "weighted stress primary enabled; using FEMM-like volume MST torque ({:.6e} Nm)",
                debug.scaled_torque_nm
            )
        } else if weighted_stress_primary_enabled {
            let weighted_reason = weighted_stress_debug
                .as_ref()
                .and_then(|debug| debug.error.clone())
                .unwrap_or_else(|| {
                    "weighted stress primary requested but not computed".to_string()
                });
            format!(
                "{}; using standard contour ({})",
                weighted_reason, contour_selection.reason
            )
        } else if use_robust_contour {
            robust_debug
                .as_ref()
                .expect("robust contour selected only when ready")
                .selected_reason
                .clone()
        } else if robust_primary_enabled {
            let robust_reason = robust_debug
                .as_ref()
                .map(|debug| {
                    format!(
                        "robust primary requested but status={} ({})",
                        debug.status, debug.selected_reason
                    )
                })
                .unwrap_or_else(|| "robust primary requested but not computed".to_string());
            format!(
                "{}; using standard contour ({})",
                robust_reason, contour_selection.reason
            )
        } else if contour_guard_enabled {
            contour_selection.reason.clone()
        } else if az_contour_ready {
            format!(
                "A_z contour guard disabled; diagnostic split only ({})",
                contour_selection.reason
            )
        } else {
            contour_selection.reason.clone()
        };
        let torque_contour_debug = if use_az_contour {
            az_contour_debug.expect("A_z contour selected only when it exists and is ok")
        } else {
            nodal_b_contour_debug
        };
        let selected_torque_nm = if use_weighted_stress {
            weighted_stress_debug
                .as_ref()
                .expect("weighted stress selected only when ready")
                .scaled_torque_nm
        } else if use_robust_contour {
            robust_debug
                .as_ref()
                .expect("robust contour selected only when ready")
                .selected_torque_nm
        } else {
            torque_contour_debug.scaled_torque_nm
        };
        let (
            _torque_contour_mid_nm,
            torque_contour_inner_nm,
            torque_contour_outer_nm,
            torque_contour_multi_radius_diagnostics,
        ) = if full_circle_model && use_az_contour {
            compute_torque_at_multiple_radii_from_az(mesh, az, stack_length_mm, pole_count)
        } else {
            compute_torque_at_multiple_radii(mesh, fields, stack_length_mm, pole_count)
        };
        (
            torque_contour_debug,
            torque_contour_az_nm,
            torque_contour_nodal_b_nm,
            contour_selection,
            contour_guard_enabled,
            robust_primary_enabled,
            robust_debug,
            weighted_stress_primary_enabled,
            weighted_stress_debug,
            torque_contour_selection,
            torque_contour_selection_reason,
            selected_torque_nm,
            torque_contour_inner_nm,
            torque_contour_outer_nm,
            torque_contour_multi_radius_diagnostics,
        )
    };
    let slot_side_turn_factor =
        flux_linkage_slot_side_turn_factor(winding_type, winding_layers, parallel_paths);
    if winding_type == "concentrated" && field_spectrum_diagnostics_enabled() {
        let phasor_magnitudes = phase_slot_side_phasor_magnitudes(slot_count, pole_count);
        let effective_turns = [
            phasor_magnitudes[0] * turns_per_coil as f64 * slot_side_turn_factor,
            phasor_magnitudes[1] * turns_per_coil as f64 * slot_side_turn_factor,
            phasor_magnitudes[2] * turns_per_coil as f64 * slot_side_turn_factor,
        ];
        eprintln!(
            "  WINDING diagnostic: slot-side phasor |sum| A/B/C = {:.4}/{:.4}/{:.4}, slot-side turn factor = {:.3}, effective turns/phase A/B/C = {:.2}/{:.2}/{:.2}",
            phasor_magnitudes[0],
            phasor_magnitudes[1],
            phasor_magnitudes[2],
            slot_side_turn_factor,
            effective_turns[0],
            effective_turns[1],
            effective_turns[2],
        );
    }

    let subtract_slot_az_reference =
        winding_type == "concentrated" && winding_layers == 1 && slot_count > 1;
    let (flux, slot_flux_linkage_contributions) = compute_flux_linkage(
        mesh,
        az,
        centroids,
        stack_length_mm,
        winding_type,
        slot_count,
        pole_count,
        turns_per_coil,
        winding_layers,
        coil_span,
        slot_side_turn_factor,
        subtract_slot_az_reference,
    );
    let nodal_b = compute_nodal_b_field(mesh, fields);
    let (peak_b_tooth_point_t, peak_b_yoke_point_t) =
        compute_point_sampled_peak_b(mesh, &nodal_b, slot_count);

    // Use contour torque as the primary value.
    // The area MST (torque_debug) is unreliable on real motor geometry due to
    // boundary element contamination from adjacent iron. Keep it in the payload
    // for diagnostics only.
    FieldSummary {
        peak_b_airgap_t: peak_b_robust(&airgap_b),
        mean_b_airgap_t: mean_b_area_weighted(&airgap_b),
        peak_b_tooth_t: peak_b_robust(&tooth_b),
        peak_b_yoke_t: peak_b_robust(&yoke_b),
        peak_b_tooth_point_t,
        peak_b_yoke_point_t,
        torque_nm: selected_torque_nm,
        torque_area_mst_nm: torque_debug.scaled_torque_nm,
        torque_debug,
        torque_contour_nm: selected_torque_nm,
        torque_contour_inner_nm,
        torque_contour_outer_nm,
        torque_contour_multi_radius_diagnostics,
        torque_contour_selection,
        torque_contour_selection_reason,
        torque_contour_guard_enabled: contour_guard_enabled,
        torque_contour_az_nm,
        torque_contour_nodal_b_nm,
        torque_contour_az_nodal_b_split_rel: contour_selection.split_rel,
        torque_contour_robust_nm: robust_debug.as_ref().map(|debug| debug.selected_torque_nm),
        torque_contour_robust_primary_enabled: robust_primary_enabled,
        torque_contour_robust_debug: robust_debug,
        torque_weighted_stress_nm: weighted_stress_debug
            .as_ref()
            .map(|debug| debug.scaled_torque_nm),
        torque_weighted_stress_primary_enabled: weighted_stress_primary_enabled,
        torque_weighted_stress_debug: weighted_stress_debug,
        torque_contour_debug,
        torque_arkkio_nm: torque_arkkio_debug.scaled_torque_nm,
        torque_arkkio_debug,
        energy_functional: EnergyFunctionalSummary::default(),
        source_current_angle_deg: 0.0,
        phase_current_a: [0.0, 0.0, 0.0],
        slot_excitation_contributions: Vec::new(),
        flux_linkage_a_wb: flux[0],
        flux_linkage_b_wb: flux[1],
        flux_linkage_c_wb: flux[2],
        slot_flux_linkage_contributions,
        num_elements_solved: fields.len(),
    }
}

/// Compute stator core loss from the B-field waveform of each stator iron element.
///
/// The rotor sweep is assumed to span one electrical period with uniform angle spacing.
/// For each stator tooth/yoke element we extract harmonic amplitudes of Bx and By, combine
/// them into a vector amplitude per harmonic, and apply a harmonic Steinmetz sum:
///
/// P_hyst = sum_h (k_h * f_h * B_h^alpha * m_elem)
/// P_eddy = sum_h (k_e * f_h^2 * B_h^2 * m_elem)
///
/// Also returns per-element volumetric density `q = (P_hyst + P_eddy)_sector / (A·L)`
/// so thermal FEA can inject the same map. Sector→full-machine scaling
/// is applied only to the integrated watt totals / mass, matching prior behavior.
#[allow(dead_code)]
pub fn compute_stator_core_loss(
    mesh: &TriMesh,
    field_history: &[Vec<ElementField>],
    stack_length_mm: f64,
    pole_count: u32,
    coeffs: SteinmetzCoefficients,
    electrical_frequency_hz: f64,
) -> CoreLossSummary {
    if field_history.len() < 2 {
        return CoreLossSummary::default();
    }
    if field_history
        .iter()
        .any(|sample_fields| sample_fields.len() != mesh.triangles.len())
    {
        return CoreLossSummary::default();
    }

    let n_samples = field_history.len();
    let l_stack_m = stack_length_mm * 1e-3;
    let scale = pole_count as f64 / mesh.info.n_pole_pitches.max(1) as f64;
    let max_harmonic = n_samples / 2;
    let mut hysteresis_loss_w = 0.0;
    let mut eddy_current_loss_w = 0.0;
    let mut stator_core_mass_kg = 0.0;
    let mut density_w_per_m3 = vec![0.0_f64; mesh.triangles.len()];

    for elem_idx in 0..mesh.triangles.len() {
        let region = mesh.regions[elem_idx];
        if region != Region::StatorTooth && region != Region::StatorYoke {
            continue;
        }

        let [i, j, m] = mesh.triangles[elem_idx];
        let area_m2 = triangle_area(&mesh.nodes, i, j, m);
        if area_m2 <= 1e-15 {
            continue;
        }
        let elem_mass_kg = area_m2 * l_stack_m * coeffs.density_kg_m3 * scale;
        stator_core_mass_kg += elem_mass_kg;

        let mut q_w_per_m3 = 0.0;
        for harmonic in 1..=max_harmonic {
            let mut re_x = 0.0;
            let mut im_x = 0.0;
            let mut re_y = 0.0;
            let mut im_y = 0.0;

            for (sample_idx, sample_fields) in field_history.iter().enumerate() {
                let theta = 2.0 * PI * harmonic as f64 * sample_idx as f64 / n_samples as f64;
                let field = &sample_fields[elem_idx];
                re_x += field.bx * theta.cos();
                im_x -= field.bx * theta.sin();
                re_y += field.by * theta.cos();
                im_y -= field.by * theta.sin();
            }

            let scale_amp = 2.0 / n_samples as f64;
            let amp_bx = scale_amp * (re_x * re_x + im_x * im_x).sqrt();
            let amp_by = scale_amp * (re_y * re_y + im_y * im_y).sqrt();
            let b_h = (amp_bx * amp_bx + amp_by * amp_by).sqrt();
            if b_h <= 1e-9 {
                continue;
            }

            let f_h = electrical_frequency_hz * harmonic as f64;
            let hyst_w_per_kg = coeffs.kh * f_h * b_h.powf(coeffs.alpha);
            let eddy_w_per_kg = coeffs.ke * f_h * f_h * b_h * b_h;
            hysteresis_loss_w += hyst_w_per_kg * elem_mass_kg;
            eddy_current_loss_w += eddy_w_per_kg * elem_mass_kg;
            // Volumetric density on the mesh (sector); totals above include scale.
            q_w_per_m3 += (hyst_w_per_kg + eddy_w_per_kg) * coeffs.density_kg_m3;
        }
        density_w_per_m3[elem_idx] = q_w_per_m3;
    }

    CoreLossSummary {
        core_loss_w: hysteresis_loss_w + eddy_current_loss_w,
        hysteresis_loss_w,
        eddy_current_loss_w,
        stator_core_mass_kg,
        // Always computed (intensive, sector-safe). Report emission is
        // opt-in at SweepData assembly — see emit_core_loss_density_enabled().
        core_loss_density_w_per_m3: Some(density_w_per_m3),
    }
}

/// Whether fixed-mesh sweep reports should attach ``core_loss_density_w_per_m3``.
///
/// Off by default to keep EM report payloads lean (~N_tri floats); thermal /
/// Export opts in via ``COILEM_MAGNETO2D_EMIT_CORE_LOSS_DENSITY`` or
/// ``COILEM_THERMAL_ENABLED``.


fn interpolate_nodal_b_in_regions(
    mesh: &TriMesh,
    nodal_b: &[[f64; 2]],
    point_xy_m: [f64; 2],
    allowed_regions: &[Region],
) -> Option<(f64, f64)> {
    for (triangle_index, tri) in mesh.triangles.iter().enumerate() {
        if !allowed_regions.contains(&mesh.regions[triangle_index]) {
            continue;
        }
        let tri_xy = [mesh.nodes[tri[0]], mesh.nodes[tri[1]], mesh.nodes[tri[2]]];
        let xs = [tri_xy[0][0], tri_xy[1][0], tri_xy[2][0]];
        let ys = [tri_xy[0][1], tri_xy[1][1], tri_xy[2][1]];
        let pad = 1e-9;
        if point_xy_m[0] < xs.iter().copied().fold(f64::INFINITY, f64::min) - pad
            || point_xy_m[0] > xs.iter().copied().fold(f64::NEG_INFINITY, f64::max) + pad
            || point_xy_m[1] < ys.iter().copied().fold(f64::INFINITY, f64::min) - pad
            || point_xy_m[1] > ys.iter().copied().fold(f64::NEG_INFINITY, f64::max) + pad
        {
            continue;
        }
        let Some(weights) = barycentric_weights(point_xy_m, tri_xy) else {
            continue;
        };
        let mut bx = 0.0;
        let mut by = 0.0;
        for k in 0..3 {
            let nb = nodal_b[tri[k]];
            bx += weights[k] * nb[0];
            by += weights[k] * nb[1];
        }
        return Some((bx, by));
    }
    None
}

fn compute_point_sampled_peak_b(
    mesh: &TriMesh,
    nodal_b: &[[f64; 2]],
    slot_count: u32,
) -> (f64, f64) {
    if slot_count == 0 {
        return (0.0, 0.0);
    }

    let stator_inner_r = mesh.info.stator_inner_radius_mm * 1e-3;
    let slot_outer_r = mesh.info.stator_slot_outer_radius_mm * 1e-3;
    let stator_outer_r = mesh.info.stator_outer_radius_mm * 1e-3;
    if stator_inner_r <= 0.0 || slot_outer_r <= stator_inner_r || stator_outer_r <= slot_outer_r {
        return (0.0, 0.0);
    }

    let tooth_r = 0.5 * (stator_inner_r + slot_outer_r);
    let yoke_r = 0.5 * (slot_outer_r + stator_outer_r);
    let total_span_rad = mesh.info.total_span_deg.to_radians();
    let slot_pitch_rad = 2.0 * PI / slot_count as f64;

    let mut peak_tooth = 0.0_f64;
    for s in 0..slot_count as usize {
        let theta = slot_center_angle_rad(s, slot_pitch_rad) + 0.5 * slot_pitch_rad;
        if theta >= total_span_rad - 1e-9 {
            continue;
        }
        let point = [tooth_r * theta.cos(), tooth_r * theta.sin()];
        if let Some((bx, by)) =
            interpolate_nodal_b_in_regions(mesh, nodal_b, point, &[Region::StatorTooth])
        {
            peak_tooth = peak_tooth.max((bx * bx + by * by).sqrt());
        }
    }

    let yoke_samples = ((36.0 * (mesh.info.total_span_deg / 360.0)).round() as usize).max(4);
    let mut peak_yoke = 0.0_f64;
    for sample_index in 0..yoke_samples {
        let theta = total_span_rad * sample_index as f64 / yoke_samples as f64;
        let point = [yoke_r * theta.cos(), yoke_r * theta.sin()];
        if let Some((bx, by)) =
            interpolate_nodal_b_in_regions(mesh, nodal_b, point, &[Region::StatorYoke])
        {
            peak_yoke = peak_yoke.max((bx * bx + by * by).sqrt());
        }
    }

    (peak_tooth, peak_yoke)
}
/// Robust peak |B| for a region: drop sliver triangles (area < 0.25 × median
/// area), then return the area-weighted 99th percentile of |B| over what's
/// left. This suppresses both mesh slivers at reentrant corners and isolated
/// rogue elements, yielding a physically meaningful peak rather than the raw
/// max over an unfiltered set.
fn peak_b_robust(data: &[(f64, f64)]) -> f64 {
    if data.is_empty() {
        return 0.0;
    }
    let mut areas: Vec<f64> = data.iter().map(|&(_, a)| a).collect();
    areas.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median_area = areas[areas.len() / 2];
    let min_area = 0.25 * median_area;
    let mut filtered: Vec<(f64, f64)> = data
        .iter()
        .copied()
        .filter(|&(_, a)| a >= min_area)
        .collect();
    if filtered.is_empty() {
        return 0.0;
    }
    // Sort by |B| descending, accumulate area until we reach the top 1% by area.
    filtered.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let total_area: f64 = filtered.iter().map(|&(_, a)| a).sum();
    let target = total_area * 0.01;
    let mut cum = 0.0;
    for &(b, a) in &filtered {
        cum += a;
        if cum >= target {
            return b;
        }
    }
    filtered.last().map(|&(b, _)| b).unwrap_or(0.0)
}

/// Area-weighted mean |B| over a region, ignoring slivers.
fn mean_b_area_weighted(data: &[(f64, f64)]) -> f64 {
    let total_area: f64 = data.iter().map(|&(_, a)| a).sum();
    if total_area <= 0.0 {
        return 0.0;
    }
    let sum_ba: f64 = data.iter().map(|&(b, a)| b * a).sum();
    sum_ba / total_area
}

#[cfg(test)]
mod tests {
    use crate::mesh::{MeshInfo, Region, TriMesh};

    use super::{
        compute_flux_linkage, contour_torque_guard_enabled, select_contour_torque_path,
        truthy_flag_value, ContourTorqueDebug,
    };

    fn synthetic_slot_flux_mesh(slot_count: usize, pole_count: u32) -> (TriMesh, Vec<[f64; 2]>) {
        let slot_pitch_rad = 2.0 * std::f64::consts::PI / slot_count as f64;
        let radius_m = 0.036;
        let dr_m = 0.001;
        let half_angle = 0.004;
        let mut nodes = Vec::new();
        let mut triangles = Vec::new();
        let mut regions = Vec::new();
        let mut centroids = Vec::new();

        for slot in 0..slot_count {
            let theta = slot as f64 * slot_pitch_rad;
            let points = [
                [radius_m * theta.cos(), radius_m * theta.sin()],
                [
                    (radius_m + dr_m) * (theta + half_angle).cos(),
                    (radius_m + dr_m) * (theta + half_angle).sin(),
                ],
                [
                    (radius_m + dr_m) * (theta - half_angle).cos(),
                    (radius_m + dr_m) * (theta - half_angle).sin(),
                ],
            ];
            let start = nodes.len();
            nodes.extend(points);
            triangles.push([start, start + 1, start + 2]);
            regions.push(Region::SlotWinding);
            centroids.push([
                (points[0][0] + points[1][0] + points[2][0]) / 3.0,
                (points[0][1] + points[1][1] + points[2][1]) / 3.0,
            ]);
        }

        let mesh = TriMesh {
            nodes,
            triangles,
            regions,
            boundary_nodes: Vec::new(),
            sector_edge_pairs: Vec::new(),
            info: MeshInfo {
                num_nodes: slot_count * 3,
                num_triangles: slot_count,
                pole_pitch_deg: 360.0 / pole_count as f64,
                n_pole_pitches: pole_count,
                total_span_deg: 360.0,
                angular_divisions: slot_count,
                radial_rings: 1,
                mesh_density: "synthetic".to_string(),
                radial_layers: vec!["slot_winding".to_string()],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: None,
                magnet_outer_radius_mm: 27.0,
                magnet_embrace: 0.8,
                stator_inner_radius_mm: 30.0,
                stator_slot_outer_radius_mm: 42.0,
                stator_outer_radius_mm: 50.0,
            },
        };

        (mesh, centroids)
    }

    fn contour_debug(status: &str, scaled_torque_nm: f64) -> ContourTorqueDebug {
        ContourTorqueDebug {
            status: status.to_string(),
            error: (status != "ok").then(|| "synthetic contour failure".to_string()),
            radius_mm: 1.0,
            sample_count: 1,
            total_span_deg: 360.0,
            unique_triangle_count: 1,
            modeled_torque_nm: scaled_torque_nm,
            scale_factor: 1.0,
            scaled_torque_nm,
            samples: Vec::new(),
            per_quadrant: None,
        }
    }

    #[test]
    fn concentrated_flux_linkage_reference_removes_common_az_offset() {
        let (mesh, centroids) = synthetic_slot_flux_mesh(12, 8);
        let base_az: Vec<f64> = (0..mesh.nodes.len())
            .map(|node_idx| {
                let slot = node_idx / 3;
                1.0e-4 * slot as f64
            })
            .collect();
        let offset_az: Vec<f64> = base_az.iter().map(|value| value + 0.0123).collect();

        let (flux, contributions) = compute_flux_linkage(
            &mesh,
            &base_az,
            &centroids,
            100.0,
            "concentrated",
            12,
            8,
            10,
            1,
            None,
            0.5,
            true,
        );
        let (offset_flux, offset_contributions) = compute_flux_linkage(
            &mesh,
            &offset_az,
            &centroids,
            100.0,
            "concentrated",
            12,
            8,
            10,
            1,
            None,
            0.5,
            true,
        );

        for phase in 0..3 {
            assert!(
                (offset_flux[phase] - flux[phase]).abs() < 1e-12,
                "phase {phase} changed under common A_z offset: {} -> {}",
                flux[phase],
                offset_flux[phase],
            );
        }
        assert_eq!(contributions.len(), 12);
        assert_eq!(offset_contributions.len(), 12);
        assert!(offset_contributions[0].az_reference_wb_per_m > 0.012);

        let (raw_flux, _) = compute_flux_linkage(
            &mesh,
            &base_az,
            &centroids,
            100.0,
            "concentrated",
            12,
            8,
            10,
            1,
            None,
            0.5,
            false,
        );
        let (raw_offset_flux, _) = compute_flux_linkage(
            &mesh,
            &offset_az,
            &centroids,
            100.0,
            "concentrated",
            12,
            8,
            10,
            1,
            None,
            0.5,
            false,
        );
        assert!(
            (raw_offset_flux[0] - raw_flux[0]).abs() > 0.02,
            "unreferenced phase flux should expose the synthetic common-mode sensitivity"
        );
    }

    #[test]
    fn distributed_flux_linkage_uses_distributed_phase_assignment() {
        // Winding propagation contract: the payload winding type must reach the
        // flux-linkage phase grouping (it was hardcoded to the concentrated
        // map before this fix, so distributed back-EMF phases were grouped
        // wrong).
        //
        // Use the same star-of-slots primitive for valid distributed
        // rows in both source excitation and flux-linkage grouping. The
        // 12s/8p q < 1 case is intentionally only a low-level plumbing probe:
        // it is rejected upstream for distributed windings, but still proves
        // this function dispatches through distributed_winding_assignment.
        use crate::sources::{concentrated_winding_assignment, distributed_winding_assignment};

        let (mesh, centroids) = synthetic_slot_flux_mesh(12, 8);
        let az: Vec<f64> = (0..mesh.nodes.len())
            .map(|node_idx| 1.0e-4 * (node_idx / 3) as f64)
            .collect();

        let (_, contributions) = compute_flux_linkage(
            &mesh,
            &az,
            &centroids,
            100.0,
            "distributed",
            12,
            8,
            10,
            1,
            None,
            1.0,
            false,
        );

        assert_eq!(contributions.len(), 12);
        let phase_names = ["A", "B", "C"];
        for contribution in &contributions {
            let slot = contribution.slot_index_global;
            let (expected_phase, expected_dir) = distributed_winding_assignment(slot, 12, 8);
            assert_eq!(
                contribution.phase, phase_names[expected_phase],
                "slot {slot} phase should follow the distributed assignment"
            );
            assert_eq!(
                contribution.direction,
                if expected_dir { "in" } else { "out" },
                "slot {slot} direction should follow the distributed assignment"
            );
            let (concentrated_phase, concentrated_dir) =
                concentrated_winding_assignment(slot, 12, 8);
            assert_eq!(
                (concentrated_phase, concentrated_dir),
                (expected_phase, expected_dir)
            );
        }

        // On the permitted subset (integer q) the two maps agree by
        // construction; pin that equivalence so a future map change that
        // breaks it is a deliberate decision, not an accident.
        for (slot_count, pole_count) in [(24u32, 8u32), (48, 8), (36, 12)] {
            for slot in 0..slot_count as usize {
                assert_eq!(
                    distributed_winding_assignment(slot, slot_count, pole_count),
                    concentrated_winding_assignment(slot, slot_count, pole_count),
                    "integer-q {slot_count}s/{pole_count}p slot {slot}: belt map should equal phasor-star map",
                );
            }
        }
    }

    #[test]
    fn distributed_chorded_flux_linkage_emits_weighted_layer_contributions() {
        let (mesh, centroids) = synthetic_slot_flux_mesh(48, 8);
        let az: Vec<f64> = (0..mesh.nodes.len())
            .map(|node_idx| 1.0e-4 * (node_idx / 3) as f64)
            .collect();

        let (_, full_pitch_contributions) = compute_flux_linkage(
            &mesh,
            &az,
            &centroids,
            100.0,
            "distributed",
            48,
            8,
            6,
            2,
            None,
            1.0,
            false,
        );
        let (_, chorded_contributions) = compute_flux_linkage(
            &mesh,
            &az,
            &centroids,
            100.0,
            "distributed",
            48,
            8,
            6,
            2,
            Some(5),
            1.0,
            false,
        );

        assert_eq!(full_pitch_contributions.len(), 48);
        assert_eq!(chorded_contributions.len(), 96);
        let slot5: Vec<_> = chorded_contributions
            .iter()
            .filter(|row| row.slot_index_global == 5)
            .map(|row| (row.phase.as_str(), row.direction.as_str()))
            .collect();
        assert_eq!(slot5, vec![("B", "in"), ("A", "out")]);
    }

    #[test]
    fn truthy_flag_value_accepts_common_enabled_values() {
        for value in ["1", "true", "yes", "on", "debug", " TRUE "] {
            assert!(truthy_flag_value(value), "{value:?} should be truthy");
        }
    }

    #[test]
    fn truthy_flag_value_rejects_common_disabled_values() {
        for value in ["", "0", "false", "no", "off", " OFF "] {
            assert!(!truthy_flag_value(value), "{value:?} should be falsey");
        }
    }

    #[test]
    fn contour_torque_guard_defaults_off() {
        std::env::remove_var("COILEM_MAGNETO2D_CONTOUR_TORQUE_GUARD");
        std::env::remove_var("MAGNETO2D_CONTOUR_TORQUE_GUARD");

        assert!(!contour_torque_guard_enabled());
    }

    #[test]
    fn contour_torque_selection_keeps_az_when_paths_agree() {
        let az = contour_debug("ok", 0.010);
        let nodal_b = contour_debug("ok", 0.009);

        let selection = select_contour_torque_path(Some(&az), &nodal_b);

        assert!(selection.use_az);
        assert_eq!(selection.path, "az");
        assert!(selection.split_rel.unwrap() < 0.5);
    }

    #[test]
    fn contour_torque_selection_falls_back_when_az_diverges() {
        let az = contour_debug("ok", 0.150);
        let nodal_b = contour_debug("ok", -0.002);

        let selection = select_contour_torque_path(Some(&az), &nodal_b);

        assert!(!selection.use_az);
        assert_eq!(selection.path, "nodal_b");
        assert!(selection.split_rel.unwrap() > 0.5);
        assert!(selection.reason.contains("exceeds guard"));
    }

    #[test]
    fn contour_torque_selection_uses_az_when_nodal_b_is_unavailable() {
        let az = contour_debug("ok", 0.010);
        let nodal_b = contour_debug("error", 0.0);

        let selection = select_contour_torque_path(Some(&az), &nodal_b);

        assert!(selection.use_az);
        assert_eq!(selection.path, "az");
    }
}
