//! Current density sources for stator winding slots.
//!
//! Computes J_z [A/m²] for each element based on the winding layout,
//! phase currents, and slot assignment.

use crate::mesh::{Region, TriMesh};
use crate::motor::MotorConfig;
use serde::Serialize;
use std::f64::consts::PI;

/// Per-slot excitation summary derived from the native J_z distribution.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SlotExcitationContribution {
    pub slot_index_modeled: usize,
    pub slot_index_global: usize,
    pub phase: String,
    pub direction: String,
    pub center_angle_mech_deg: f64,
    pub slot_area_m2: f64,
    pub effective_current_density_a_per_m2: f64,
    pub integrated_amp_turns_a: f64,
    pub slot_current_a: f64,
    pub phase_current_a: f64,
    pub turns_per_coil: u32,
}

/// Native current synthesis summary for a single operating point.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ExcitationSummary {
    pub source_current_angle_deg: f64,
    pub phase_current_a: [f64; 3],
    pub slot_excitation_contributions: Vec<SlotExcitationContribution>,
}

pub(crate) fn phase_currents_from_angle(
    current_amplitude_a: f64,
    current_angle_deg: f64,
) -> [f64; 3] {
    let angle_rad = current_angle_deg * PI / 180.0;
    let i_a = current_amplitude_a * angle_rad.sin();
    let i_b = current_amplitude_a * (angle_rad - 2.0 * PI / 3.0).sin();
    let i_c = current_amplitude_a * (angle_rad - 4.0 * PI / 3.0).sin();
    [i_a, i_b, i_c]
}

const NATIVE_SIX_STEP_TABLE: [[f64; 3]; 6] = [
    [-1.0, 0.0, 1.0],
    [0.0, -1.0, 1.0],
    [1.0, -1.0, 0.0],
    [1.0, 0.0, -1.0],
    [0.0, 1.0, -1.0],
    [-1.0, 1.0, 0.0],
];

const PUBLIC_SIX_STEP_TABLE: [[f64; 3]; 6] = [
    [1.0, -1.0, 0.0],
    [0.0, -1.0, 1.0],
    [-1.0, 0.0, 1.0],
    [-1.0, 1.0, 0.0],
    [0.0, 1.0, -1.0],
    [1.0, 0.0, -1.0],
];

fn wrap_360(angle_deg: f64) -> f64 {
    angle_deg.rem_euclid(360.0)
}

fn normalize_commutation_boundary(angle_deg: f64) -> f64 {
    let wrapped = wrap_360(angle_deg);
    let nearest_boundary = (wrapped / 60.0).round() * 60.0;
    // Rotor positions arrive as radians, so an exact degree boundary can
    // return from the radian round-trip a few ulps below the boundary. Snap
    // only floating representation noise; the frozen +/-1e-9 degree probes
    // remain on their respective sides and preserve lower-inclusive sectors.
    if (wrapped - nearest_boundary).abs() <= 1.0e-12 {
        wrap_360(nearest_boundary)
    } else {
        wrapped
    }
}

pub(crate) fn phase_currents_for_excitation(
    config: &MotorConfig,
    rotor_angle_rad: f64,
    current_amplitude_a: f64,
    source_current_angle_deg: f64,
) -> [f64; 3] {
    let Some(sp) = config.solve_params.as_ref() else {
        // The operating-point resolver supplies the legacy sinusoidal
        // default current when solve_params is absent.
        return phase_currents_from_angle(current_amplitude_a, source_current_angle_deg);
    };
    if sp.excitation_mode_label() != "ideal_six_step_120" {
        return phase_currents_from_angle(current_amplitude_a, source_current_angle_deg);
    }

    let pole_pairs = ((config.rotor.pole_count / 2).max(1)) as f64;
    let rotor_elec_deg = rotor_angle_rad.to_degrees() * pole_pairs;
    let advance_deg = sp.commutation_advance_deg();
    let (effective_deg, table) =
        if sp.excitation_rotation_convention_label() == "clockwise_positive_ui" {
            (
                normalize_commutation_boundary(-rotor_elec_deg + advance_deg),
                &PUBLIC_SIX_STEP_TABLE,
            )
        } else {
            (
                normalize_commutation_boundary(rotor_elec_deg + advance_deg),
                &NATIVE_SIX_STEP_TABLE,
            )
        };
    let sector = ((effective_deg / 60.0).floor() as usize).min(5);
    table[sector].map(|value| value * current_amplitude_a)
}

/// Convert public terminal currents to the homogenized slot-side source.
///
/// Single-layer concentrated flux linkage uses the historical 0.5 slot-side
/// turn normalization. The BLDC plateau is a terminal phase current, so its
/// source uses the same normalization for electromechanical reciprocity.
/// Legacy sinusoidal excitation remains unchanged.
pub(crate) fn source_phase_currents_for_excitation(
    config: &MotorConfig,
    rotor_angle_rad: f64,
    current_amplitude_a: f64,
    source_current_angle_deg: f64,
) -> [f64; 3] {
    let currents = phase_currents_for_excitation(
        config,
        rotor_angle_rad,
        current_amplitude_a,
        source_current_angle_deg,
    );
    let scale = if config
        .solve_params
        .as_ref()
        .map(|sp| sp.excitation_mode_label() == "ideal_six_step_120")
        .unwrap_or(false)
        && config.winding.winding_type == "concentrated"
        && config.winding.layers == 1
    {
        0.5
    } else {
        1.0
    };
    currents.map(|current| current * scale)
}

pub fn compute_current_densities_from_phase_currents(
    mesh: &TriMesh,
    centroids: &[[f64; 2]],
    winding_type: &str,
    slot_count: u32,
    pole_count: u32,
    turns_per_coil: u32,
    winding_layers: u32,
    coil_span: Option<u32>,
    phase_currents: [f64; 3],
    slot_areas_mm2: &[f64],
) -> Vec<f64> {
    let n_tri = mesh.triangles.len();
    let mut j_z = vec![0.0_f64; n_tri];

    if phase_currents.iter().all(|current| current.abs() < 1e-12) {
        return j_z;
    }

    let pole_pitch_rad = 2.0 * PI / pole_count as f64;
    let slots_per_pole = slot_count as f64 / pole_count as f64;
    let slot_pitch_rad = pole_pitch_rad / slots_per_pole;
    let total_slots_in_span = (slots_per_pole * mesh.info.n_pole_pitches as f64).ceil() as usize;

    for (tri_idx, (region, centroid)) in mesh.regions.iter().zip(centroids.iter()).enumerate() {
        if *region != Region::SlotWinding {
            continue;
        }

        let theta = centroid[1].atan2(centroid[0]);
        let theta_positive = if theta < 0.0 { theta + 2.0 * PI } else { theta };
        let slot_local = slot_index_from_theta(theta_positive, slot_pitch_rad, total_slots_in_span);
        let slot_global = slot_local % slot_count as usize;
        let slot_current_sum: f64 = slot_winding_layers(
            winding_type,
            slot_global,
            slot_count,
            pole_count,
            winding_layers,
            coil_span,
        )
        .into_iter()
        .map(|(phase_idx, direction, turn_fraction)| {
            let dir_sign = if direction { 1.0 } else { -1.0 };
            turn_fraction * phase_currents[phase_idx] * dir_sign
        })
        .sum();
        let slot_idx = slot_local.min(slot_areas_mm2.len().saturating_sub(1));
        let a_slot_m2 = slot_areas_mm2.get(slot_idx).copied().unwrap_or(1.0) * 1e-6;
        if a_slot_m2 > 1e-12 {
            j_z[tri_idx] = turns_per_coil as f64 * slot_current_sum / a_slot_m2;
        }
    }
    j_z
}

/// Compute current density J_z for each triangle element.
///
/// For a concentrated winding SPM motor:
/// - Each slot carries one phase coil
/// - Current density J = N_turns * I_phase / A_slot
/// - Phase assignment follows standard 3-phase pattern
///
/// For now: no-load (J=0 everywhere) for PM-only field comparison,
/// or loaded with specified phase current.
#[allow(dead_code)]
pub fn compute_current_densities(
    mesh: &TriMesh,
    centroids: &[[f64; 2]],
    winding_type: &str,
    slot_count: u32,
    pole_count: u32,
    turns_per_coil: u32,
    winding_layers: u32,
    coil_span: Option<u32>,
    current_amplitude_a: f64,
    current_angle_deg: f64,
    slot_areas_mm2: &[f64],
) -> Vec<f64> {
    let phase_currents = phase_currents_from_angle(current_amplitude_a, current_angle_deg);
    compute_current_densities_from_phase_currents(
        mesh,
        centroids,
        winding_type,
        slot_count,
        pole_count,
        turns_per_coil,
        winding_layers,
        coil_span,
        phase_currents,
        slot_areas_mm2,
    )
}

/// Return per-slot winding areas from the already-converted solve mesh.
///
/// `setup_context` converts mesh coordinates from mm to m before current
/// synthesis. This helper therefore integrates triangle areas in m^2, then
/// returns mm^2 to match the analytical `slot_areas_mm2` convention consumed by
/// `compute_current_densities`.
pub(crate) fn mesh_slot_areas_mm2(
    mesh: &TriMesh,
    centroids: &[[f64; 2]],
    slot_count: u32,
    pole_count: u32,
) -> Vec<f64> {
    let pole_pitch_rad = 2.0 * PI / pole_count as f64;
    let slots_per_pole = slot_count as f64 / pole_count as f64;
    let slot_pitch_rad = pole_pitch_rad / slots_per_pole;
    let total_slots_in_span = (slots_per_pole * mesh.info.n_pole_pitches as f64).ceil() as usize;
    let mut slot_area_total_m2 = vec![0.0_f64; total_slots_in_span];

    for (tri_idx, (region, centroid)) in mesh.regions.iter().zip(centroids.iter()).enumerate() {
        if *region != Region::SlotWinding {
            continue;
        }

        let theta = centroid[1].atan2(centroid[0]);
        let theta_positive = if theta < 0.0 { theta + 2.0 * PI } else { theta };
        let slot_local = slot_index_from_theta(theta_positive, slot_pitch_rad, total_slots_in_span);
        let [i, j, k] = mesh.triangles[tri_idx];
        slot_area_total_m2[slot_local] += triangle_area(&mesh.nodes, i, j, k);
    }

    slot_area_total_m2
        .into_iter()
        .map(|area_m2| area_m2 * 1.0e6)
        .collect()
}

/// Summarize the actual slot excitation injected on the native mesh.
#[allow(dead_code)]
pub fn compute_slot_excitation_summary(
    mesh: &TriMesh,
    centroids: &[[f64; 2]],
    winding_type: &str,
    slot_count: u32,
    pole_count: u32,
    turns_per_coil: u32,
    current_amplitude_a: f64,
    current_angle_deg: f64,
    current_densities: &[f64],
) -> ExcitationSummary {
    let phase_currents = phase_currents_from_angle(current_amplitude_a, current_angle_deg);

    compute_slot_excitation_summary_from_phase_currents(
        mesh,
        centroids,
        winding_type,
        slot_count,
        pole_count,
        turns_per_coil,
        current_angle_deg,
        phase_currents,
        current_densities,
    )
}

pub fn compute_slot_excitation_summary_from_phase_currents(
    mesh: &TriMesh,
    centroids: &[[f64; 2]],
    winding_type: &str,
    slot_count: u32,
    pole_count: u32,
    turns_per_coil: u32,
    source_current_angle_deg: f64,
    phase_currents: [f64; 3],
    current_densities: &[f64],
) -> ExcitationSummary {
    let pole_pitch_rad = 2.0 * PI / pole_count as f64;
    let slots_per_pole = slot_count as f64 / pole_count as f64;
    let slot_pitch_rad = pole_pitch_rad / slots_per_pole;
    let total_slots_in_span = (slots_per_pole * mesh.info.n_pole_pitches as f64).ceil() as usize;

    let mut slot_area_total = vec![0.0_f64; total_slots_in_span];
    let mut slot_amp_turns = vec![0.0_f64; total_slots_in_span];
    let mut slot_phase = vec![0usize; total_slots_in_span];
    let mut slot_direction = vec![1.0_f64; total_slots_in_span];
    let mut slot_assigned = vec![false; total_slots_in_span];

    for (tri_idx, (region, centroid)) in mesh.regions.iter().zip(centroids.iter()).enumerate() {
        if *region != Region::SlotWinding {
            continue;
        }

        let theta = centroid[1].atan2(centroid[0]);
        let theta_positive = if theta < 0.0 { theta + 2.0 * PI } else { theta };
        let slot_local = slot_index_from_theta(theta_positive, slot_pitch_rad, total_slots_in_span);
        let slot_global = slot_local % slot_count as usize;

        let [i, j, k] = mesh.triangles[tri_idx];
        let area_m2 = triangle_area(&mesh.nodes, i, j, k);
        let integrated_amp_turns = current_densities.get(tri_idx).copied().unwrap_or(0.0) * area_m2;

        slot_area_total[slot_local] += area_m2;
        slot_amp_turns[slot_local] += integrated_amp_turns;

        if !slot_assigned[slot_local] {
            let (phase, dir) =
                winding_assignment(winding_type, slot_global, slot_count, pole_count);
            slot_phase[slot_local] = phase;
            slot_direction[slot_local] = if dir { 1.0 } else { -1.0 };
            slot_assigned[slot_local] = true;
        }
    }

    let mut slot_excitation_contributions = Vec::new();
    for slot_local in 0..total_slots_in_span {
        if !slot_assigned[slot_local] || slot_area_total[slot_local] <= 1e-18 {
            continue;
        }

        let slot_global = slot_local % slot_count as usize;
        let phase_idx = slot_phase[slot_local];
        let effective_current_density = slot_amp_turns[slot_local] / slot_area_total[slot_local];
        let slot_current_a = slot_amp_turns[slot_local] / turns_per_coil as f64;
        slot_excitation_contributions.push(SlotExcitationContribution {
            slot_index_modeled: slot_local,
            slot_index_global: slot_global,
            phase: ["A", "B", "C"][phase_idx].to_string(),
            direction: if slot_direction[slot_local] > 0.0 {
                "in".to_string()
            } else {
                "out".to_string()
            },
            center_angle_mech_deg: slot_center_angle_rad(slot_local, slot_pitch_rad).to_degrees(),
            slot_area_m2: slot_area_total[slot_local],
            effective_current_density_a_per_m2: effective_current_density,
            integrated_amp_turns_a: slot_amp_turns[slot_local],
            slot_current_a,
            phase_current_a: phase_currents[phase_idx],
            turns_per_coil,
        });
    }

    ExcitationSummary {
        source_current_angle_deg,
        phase_current_a: phase_currents,
        slot_excitation_contributions,
    }
}

/// Determine phase index (0=A, 1=B, 2=C) and direction (+/-) for a
/// concentrated winding slot using the same 60° sector mapping as the Python
/// geometry/FEMM path.
///
/// The electrical angle of slot k: α_k = k × (P/2) × 360° / S
///   (using pole PAIRS, not pole count!)
///
/// Phase belts (canonical positive-sequence phasor-star order A, -C, B,
/// -A, C, -B):
///   0°-60°   -> A+
///   60°-120° -> C-
///   120°-180°-> B+
///   180°-240°-> A-
///   240°-300°-> C+
///   300°-360°-> B-
///
/// This mirrors `backend.geometry_drawer._compute_slot_placements()` so the
/// native solver uses the same slot/phase/direction conventions as FEMM and
/// the frontend geometry. The previous B/C-swapped belt order mirrored the
/// winding (spatial sequence A,C,B), making the sin(γ), sin(γ−120°),
/// sin(γ−240°) currents counter-rotate against the rotor — loaded torque
/// averaged ~0 over a full electrical cycle.
pub fn concentrated_winding_assignment(
    slot: usize,
    slot_count: u32,
    pole_count: u32,
) -> (usize, bool) {
    // Electrical angle using pole PAIRS (P/2), not pole count.
    let pole_pairs = pole_count as f64 / 2.0;
    let elec_slot_pitch_deg = pole_pairs * 360.0 / slot_count as f64;
    let theta_elec = (slot as f64 * elec_slot_pitch_deg) % 360.0;

    let t = ((theta_elec % 360.0) + 360.0) % 360.0;
    let sector = (t / 60.0).floor() as usize % 6;
    let (phase, direction) = match sector {
        0 => (0, true),  // A+
        1 => (2, false), // C-
        2 => (1, true),  // B+
        3 => (0, false), // A-
        4 => (2, true),  // C+
        _ => (1, false), // B-
    };

    (phase, direction)
}

/// Determine phase index (0=A, 1=B, 2=C) and direction (+/-) for an
/// integer-slot full-pitch DISTRIBUTED winding slot using the block
/// phase-belt layout.
///
/// This is the analytical FALLBACK synthesis for distributed windings:
/// explicit per-slot winding metadata carried on the solve-mesh artifact
/// (the winding excitation contract) is the preferred source of
/// slot assignments when present; this closed form is only consulted when
/// the artifact carries no per-slot excitation.
///
/// Mirrors `backend.winding_utils.distributed_slot_assignment()` exactly
/// (the shared Python source consumed by geometry_drawer and preview):
///   q     = max(1, slot_count // (3 * pole_count))    (integer slots per pole per phase)
///   belt  = slot // q                                 (q consecutive slots per belt)
///   phase = [A, C, B][belt % 3]                       (belt sequence A+, C-, B+, A-, C+, B-)
///   dir   = "in" if belt % 2 == 0                     (sign alternates per BELT)
/// This is the integer-slot FULL-PITCH 60-degree phase-belt layout: phase A
/// repeats with flipped sign exactly one pole pitch (3q slots) later, and
/// the fundamental winding factor equals the textbook distribution factor
/// kd = sin(q*g/2)/(q*sin(g/2)) with g = 2*pi*pole_pairs/slot_count.
/// Python producers emit separate upper/lower slot regions for
/// distributed two-layer windings. In the full-pitch layout both regions carry
/// the same (phase, direction) pair, so this fallback assignment remains
/// layer-independent; chorded placement uses the explicit contract.
pub fn distributed_winding_assignment(
    slot: usize,
    slot_count: u32,
    pole_count: u32,
) -> (usize, bool) {
    let sector = (slot * 3 * (pole_count as usize).max(1)) / (slot_count as usize).max(1) % 6;
    // Belt phase order A, C, B (phase indices 0, 2, 1).
    let phase = [0usize, 2, 1][sector % 3];
    let direction_in = sector % 2 == 0;

    (phase, direction_in)
}

pub fn distributed_full_pitch_slots(slot_count: u32, pole_count: u32) -> u32 {
    let q = (slot_count / (3 * pole_count.max(1))).max(1);
    3 * q
}

pub fn resolve_distributed_coil_span(
    slot_count: u32,
    pole_count: u32,
    coil_span: Option<u32>,
) -> u32 {
    coil_span.unwrap_or_else(|| distributed_full_pitch_slots(slot_count, pole_count))
}

pub fn distributed_layer_winding_assignment(
    slot: usize,
    slot_count: u32,
    pole_count: u32,
    layer: u32,
    layers: u32,
    coil_span: Option<u32>,
) -> (usize, bool, f64) {
    let n_layers = if layers >= 2 { 2 } else { 1 };
    let full_pitch = distributed_full_pitch_slots(slot_count, pole_count);
    let span = resolve_distributed_coil_span(slot_count, pole_count, coil_span);
    let shift = full_pitch.saturating_sub(span) as usize;
    let source_slot = if n_layers >= 2 && layer == 2 {
        (slot + shift) % (slot_count.max(1) as usize)
    } else {
        slot
    };
    let (phase, direction) = distributed_winding_assignment(source_slot, slot_count, pole_count);
    (phase, direction, 1.0 / n_layers as f64)
}

#[cfg(test)]
pub fn distributed_distribution_factor(slot_count: u32, pole_count: u32, harmonic: u32) -> f64 {
    let q = (slot_count / (3 * pole_count.max(1))).max(1) as f64;
    let pole_pairs = (pole_count / 2).max(1) as f64;
    let g = 2.0 * PI * pole_pairs / slot_count as f64;
    let h = harmonic.max(1) as f64;
    let denominator = q * (h * g / 2.0).sin();
    if denominator.abs() < 1e-12 {
        1.0
    } else {
        ((h * q * g / 2.0).sin() / denominator).abs()
    }
}

#[cfg(test)]
pub fn distributed_pitch_factor(
    slot_count: u32,
    pole_count: u32,
    harmonic: u32,
    coil_span: Option<u32>,
) -> f64 {
    let full_pitch = distributed_full_pitch_slots(slot_count, pole_count) as f64;
    let span = resolve_distributed_coil_span(slot_count, pole_count, coil_span) as f64;
    let h = harmonic.max(1) as f64;
    (h * PI * span / (2.0 * full_pitch)).sin().abs()
}

#[cfg(test)]
pub fn distributed_winding_factor(
    slot_count: u32,
    pole_count: u32,
    harmonic: u32,
    coil_span: Option<u32>,
) -> f64 {
    distributed_distribution_factor(slot_count, pole_count, harmonic)
        * distributed_pitch_factor(slot_count, pole_count, harmonic, coil_span)
}

pub(crate) fn slot_winding_layers(
    winding_type: &str,
    slot: usize,
    slot_count: u32,
    pole_count: u32,
    winding_layers: u32,
    coil_span: Option<u32>,
) -> Vec<(usize, bool, f64)> {
    if winding_type == "distributed" && coil_span.is_some() {
        let n_layers = if winding_layers >= 2 { 2 } else { 1 };
        return (1..=n_layers)
            .map(|layer| {
                distributed_layer_winding_assignment(
                    slot,
                    slot_count,
                    pole_count,
                    layer,
                    winding_layers,
                    coil_span,
                )
            })
            .collect();
    }

    let (phase, direction) = winding_assignment(winding_type, slot, slot_count, pole_count);
    vec![(phase, direction, 1.0)]
}

/// Dispatch slot assignment on the config winding type. Anything other than
/// an explicit "distributed" keeps the concentrated path (the historical
/// default for every existing payload).
pub(crate) fn winding_assignment(
    winding_type: &str,
    slot: usize,
    slot_count: u32,
    pole_count: u32,
) -> (usize, bool) {
    if winding_type == "distributed" {
        distributed_winding_assignment(slot, slot_count, pole_count)
    } else {
        concentrated_winding_assignment(slot, slot_count, pole_count)
    }
}

pub fn phase_slot_side_phasor_magnitudes(slot_count: u32, pole_count: u32) -> [f64; 3] {
    let pole_pairs = pole_count as f64 / 2.0;
    let elec_slot_pitch_rad = pole_pairs * 2.0 * PI / slot_count as f64;
    let mut re = [0.0_f64; 3];
    let mut im = [0.0_f64; 3];

    for slot in 0..slot_count as usize {
        let theta_elec = slot as f64 * elec_slot_pitch_rad;
        let (phase, direction) = concentrated_winding_assignment(slot, slot_count, pole_count);
        let sign = if direction { 1.0 } else { -1.0 };
        re[phase] += sign * theta_elec.cos();
        im[phase] += sign * theta_elec.sin();
    }

    [
        (re[0] * re[0] + im[0] * im[0]).sqrt(),
        (re[1] * re[1] + im[1] * im[1]).sqrt(),
        (re[2] * re[2] + im[2] * im[2]).sqrt(),
    ]
}

pub fn flux_linkage_slot_side_turn_factor(
    winding_type: &str,
    layers: u32,
    parallel_paths: u32,
) -> f64 {
    let slot_side_normalization = if winding_type == "concentrated" && layers == 1 {
        // Single-layer FSCW configs are represented as slot sides.
        // Back-EMF / flux linkage should use series turns per coil branch,
        // not the raw sum over both sides of every turn.
        0.5
    } else {
        1.0
    };

    slot_side_normalization / parallel_paths.max(1) as f64
}

pub(crate) fn slot_index_from_theta(
    theta_positive: f64,
    slot_pitch_rad: f64,
    total_slots_in_span: usize,
) -> usize {
    let slot_float = theta_positive / slot_pitch_rad;
    let slot_nearest = (slot_float + 0.5).floor() as isize;
    slot_nearest.rem_euclid(total_slots_in_span as isize) as usize
}

pub(crate) fn slot_center_angle_rad(slot_index: usize, slot_pitch_rad: f64) -> f64 {
    slot_index as f64 * slot_pitch_rad
}

fn triangle_area(nodes: &[[f64; 2]], i: usize, j: usize, k: usize) -> f64 {
    let [x1, y1] = nodes[i];
    let [x2, y2] = nodes[j];
    let [x3, y3] = nodes[k];
    ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)).abs() / 2.0
}

/// Compute approximate slot areas for each slot in a pole pitch.
pub fn estimate_slot_areas(
    stator_inner_r_mm: f64,
    stator_outer_r_mm: f64,
    yoke_thickness_mm: f64,
    slot_count: u32,
    tooth_width_mm: f64,
    slot_opening_mm: f64,
) -> Vec<f64> {
    // Match the backend/FEMM tapered slot-mouth convention: the configured
    // slot opening is the bore mouth, and tooth width determines the body.
    let slot_depth = yoke_thickness_mm;
    let bore_pitch_mm = 2.0 * PI * stator_inner_r_mm / slot_count as f64;
    // The body width is subtracted from the pitch at the radius the body sits at,
    // not at the bore. See backend/geometry_drawer.py::_slot_body_width_mm: taking
    // it at the bore left the tooth wider than tooth_width_mm everywhere, and the
    // two paths have to agree or the same design meshes differently here than it
    // does through Gmsh/FEMM.
    let body_radius_mm = (stator_inner_r_mm
        + (stator_outer_r_mm - stator_inner_r_mm - yoke_thickness_mm).max(0.0))
    .max(stator_inner_r_mm);
    let body_pitch_mm = 2.0 * PI * body_radius_mm / slot_count as f64;
    let body_width = (body_pitch_mm - tooth_width_mm).max(0.5);
    let mouth_width = slot_opening_mm.max(0.5).min(bore_pitch_mm * 0.998);
    let area_mm2 = 0.5 * (mouth_width + body_width) * slot_depth;

    // Enough entries for any sector size (generous allocation).
    let slots_per_pole = slot_count as f64 / 4.0; // fallback
    vec![area_mm2; (slots_per_pole.ceil() as usize + 1) * 8]
}

#[cfg(test)]
mod tests {
    use super::{
        concentrated_winding_assignment, distributed_layer_winding_assignment,
        distributed_pitch_factor, distributed_winding_assignment, distributed_winding_factor,
        estimate_slot_areas, flux_linkage_slot_side_turn_factor, mesh_slot_areas_mm2,
        phase_currents_for_excitation, phase_slot_side_phasor_magnitudes, slot_center_angle_rad,
        slot_index_from_theta, source_phase_currents_for_excitation, winding_assignment,
    };
    use crate::mesh::{MeshInfo, Region, TriMesh};
    use crate::motor::MotorConfig;
    use serde::Deserialize;
    use std::f64::consts::PI;

    #[derive(Deserialize)]
    struct SixStepGoldenContract {
        #[serde(rename = "plateau_current_A")]
        plateau_current_a: f64,
        vectors: Vec<SixStepGoldenVector>,
    }

    #[derive(Deserialize)]
    struct SixStepGoldenVector {
        id: String,
        rotor_electrical_angle_deg: f64,
        commutation_advance_deg: f64,
        #[serde(rename = "phase_current_A")]
        phase_current_a: [f64; 3],
    }

    fn six_step_config(advance_deg: f64) -> MotorConfig {
        let mut value: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/spm_8p12s_concentrated.json"
        ))
        .expect("8p/12s fixture JSON");
        let solve_params = value["solve_params"]
            .as_object_mut()
            .expect("solve_params object");
        solve_params.insert(
            "excitation_mode".to_string(),
            serde_json::json!("ideal_six_step_120"),
        );
        solve_params.insert(
            "current_amplitude_convention".to_string(),
            serde_json::json!("plateau"),
        );
        solve_params.insert("phase_connection".to_string(), serde_json::json!("wye"));
        solve_params.insert(
            "excitation_rotation_convention".to_string(),
            serde_json::json!("clockwise_positive_ui"),
        );
        solve_params.insert(
            "commutation_advance_deg".to_string(),
            serde_json::json!(advance_deg),
        );
        serde_json::from_value(value).expect("six-step fixture config")
    }

    #[test]
    fn six_step_public_golden_vectors_match_shared_contract() {
        let golden: SixStepGoldenContract = serde_json::from_str(include_str!(
            "../../../tests/fixtures/bldc_six_step_golden_vectors.json"
        ))
        .expect("shared six-step golden vectors");

        for vector in golden.vectors {
            let config = six_step_config(vector.commutation_advance_deg);
            let pole_pairs = (config.rotor.pole_count / 2) as f64;
            // The solver rotates counterclockwise internally. Its adapter marks
            // the public clockwise convention and mirrors the public angle.
            let native_mechanical_rad =
                (-vector.rotor_electrical_angle_deg / pole_pairs).to_radians();
            let actual = phase_currents_for_excitation(
                &config,
                native_mechanical_rad,
                golden.plateau_current_a,
                123.0,
            );
            assert_eq!(
                actual, vector.phase_current_a,
                "golden vector {}",
                vector.id
            );
            assert_eq!(actual.iter().sum::<f64>(), 0.0, "zero sum {}", vector.id);
            assert_eq!(
                actual.iter().filter(|value| value.abs() > 0.0).count(),
                2,
                "two conducting phases {}",
                vector.id,
            );
        }
    }

    #[test]
    fn six_step_terminal_current_uses_single_layer_slot_side_scale() {
        let config = six_step_config(0.0);
        let terminal = phase_currents_for_excitation(&config, 0.0, 10.0, 0.0);
        let source = source_phase_currents_for_excitation(&config, 0.0, 10.0, 0.0);
        assert_eq!(source, terminal.map(|current| current * 0.5));

        let mut sine_config = config;
        sine_config.solve_params.as_mut().unwrap().excitation_mode = None;
        let sine_terminal = phase_currents_for_excitation(&sine_config, 0.0, 10.0, 0.0);
        let sine_source = source_phase_currents_for_excitation(&sine_config, 0.0, 10.0, 0.0);
        assert_eq!(sine_source, sine_terminal);
    }

    #[test]
    fn absent_solve_params_preserve_sinusoidal_operating_current() {
        let mut config = six_step_config(0.0);
        config.solve_params = None;
        // Include the legacy default 50 A, an explicitly supplied amplitude,
        // and the no-load case. The resolved source angle must still apply.
        for amplitude in [50.0, 17.0, 0.0] {
            for source_angle in [-90.0, 0.0, 37.0, 180.0] {
                let expected = [0.0_f64, -120.0, -240.0]
                    .map(|offset| amplitude * (source_angle + offset).to_radians().sin());
                let terminal =
                    phase_currents_for_excitation(&config, 0.123, amplitude, source_angle);
                let source =
                    source_phase_currents_for_excitation(&config, 0.123, amplitude, source_angle);
                for phase in 0..3 {
                    assert!((terminal[phase] - expected[phase]).abs() < 1e-12);
                    assert!((source[phase] - expected[phase]).abs() < 1e-12);
                }
            }
        }
    }

    #[test]
    fn six_step_is_periodic_and_has_half_wave_symmetry() {
        let config = six_step_config(10.0);
        let pole_pairs = (config.rotor.pole_count / 2) as f64;
        for public_elec_deg in [-355.0, -1.0, 0.0, 49.0, 50.0, 179.0, 301.0, 720.0] {
            let current_at = |angle_deg: f64| {
                phase_currents_for_excitation(
                    &config,
                    (-angle_deg / pole_pairs).to_radians(),
                    10.0,
                    0.0,
                )
            };
            let base = current_at(public_elec_deg);
            assert_eq!(current_at(public_elec_deg + 360.0), base);
            assert_eq!(
                current_at(public_elec_deg + 180.0),
                base.map(|value| -value)
            );
        }
    }

    fn independent_phase_axis_phasors(slot_count: u32, pole_count: u32) -> [(f64, f64); 3] {
        let pole_pairs = pole_count as f64 / 2.0;
        let mut phasors = [(0.0, 0.0); 3];

        for slot in 0..slot_count as usize {
            let (phase, direction_in) =
                concentrated_winding_assignment(slot, slot_count, pole_count);
            let sign = if direction_in { 1.0 } else { -1.0 };
            let theta = slot as f64 * pole_pairs * 2.0 * PI / slot_count as f64;

            phasors[phase].0 += sign * theta.cos();
            phasors[phase].1 += sign * theta.sin();
        }

        phasors
    }

    fn phasor_magnitude((re, im): (f64, f64)) -> f64 {
        re.hypot(im)
    }

    fn phasor_angle_deg((re, im): (f64, f64)) -> f64 {
        im.atan2(re).to_degrees().rem_euclid(360.0)
    }

    fn angle_delta_deg(from: f64, to: f64) -> f64 {
        (to - from).rem_euclid(360.0)
    }

    fn circular_angle_error_deg(actual: f64, expected: f64) -> f64 {
        (actual - expected + 180.0).rem_euclid(360.0) - 180.0
    }

    #[test]
    fn slot_index_binning_uses_nearest_slot_center() {
        let slot_pitch = 2.0 * PI / 12.0;
        assert_eq!(slot_index_from_theta(0.0, slot_pitch, 12), 0);
        assert_eq!(slot_index_from_theta(0.1 * slot_pitch, slot_pitch, 12), 0);
        assert_eq!(slot_index_from_theta(0.9 * slot_pitch, slot_pitch, 12), 1);
        assert_eq!(slot_index_from_theta(11.9 * slot_pitch, slot_pitch, 12), 0);
    }

    #[test]
    fn slot_center_angles_match_python_geometry_for_12s8p() {
        let slot_pitch = 2.0 * PI / 12.0;
        let expected_deg = [
            0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0, 240.0, 270.0, 300.0, 330.0,
        ];

        for (slot, expected) in expected_deg.into_iter().enumerate() {
            assert!(
                (slot_center_angle_rad(slot, slot_pitch).to_degrees() - expected).abs() < 1e-9,
                "slot {slot} center angle drifted",
            );
        }
    }

    #[test]
    fn slot_index_round_trips_through_slot_centers() {
        let slot_pitch = 2.0 * PI / 12.0;

        for slot in 0..12 {
            let theta = slot_center_angle_rad(slot, slot_pitch);
            assert_eq!(slot_index_from_theta(theta, slot_pitch, 12), slot);
        }
    }

    #[test]
    fn mesh_slot_areas_use_actual_imported_slot_triangles() {
        let mesh = TriMesh {
            // Already SI coordinates: 2 mm x 1 mm rectangle.
            nodes: vec![[0.001, 0.0], [0.003, 0.0], [0.001, 0.001], [0.003, 0.001]],
            triangles: vec![[0, 1, 2], [1, 3, 2]],
            regions: vec![Region::SlotWinding, Region::SlotWinding],
            boundary_nodes: vec![],
            sector_edge_pairs: vec![],
            info: MeshInfo {
                num_nodes: 4,
                num_triangles: 2,
                pole_pitch_deg: 360.0,
                n_pole_pitches: 1,
                total_span_deg: 360.0,
                angular_divisions: 0,
                radial_rings: 0,
                mesh_density: "gmsh_import".to_string(),
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
        let centroids = vec![[0.001667, 0.000333], [0.002333, 0.000667]];

        let areas = mesh_slot_areas_mm2(&mesh, &centroids, 1, 1);

        assert_eq!(areas.len(), 1);
        assert!((areas[0] - 2.0).abs() < 1e-12);
    }

    #[test]
    fn concentrated_winding_assignment_matches_python_geometry_for_12s8p() {
        // Canonical phasor-star belts: slot elec angles cycle 0°/120°/240°,
        // landing in the A+/B+/C+ sectors — spatial sequence A,B,C so the
        // positive-sequence currents co-rotate with the rotor.
        let expected = [
            (0, true), // A+
            (1, true), // B+
            (2, true), // C+
            (0, true), // A+
            (1, true), // B+
            (2, true), // C+
            (0, true), // A+
            (1, true), // B+
            (2, true), // C+
            (0, true), // A+
            (1, true), // B+
            (2, true), // C+
        ];

        for (slot, expected_assignment) in expected.into_iter().enumerate() {
            assert_eq!(
                concentrated_winding_assignment(slot, 12, 8),
                expected_assignment,
                "slot {slot} assignment mismatch",
            );
        }
    }

    #[test]
    fn concentrated_winding_assignment_matches_python_geometry_for_36s30p() {
        let expected = [
            (0, true),  // A+
            (1, true),  // B+
            (1, false), // B-
            (2, false), // C-
            (2, true),  // C+
            (0, true),  // A+
            (0, false), // A-
            (1, false), // B-
            (1, true),  // B+
            (2, true),  // C+
            (2, false), // C-
            (0, false), // A-
        ];

        for slot in 0..36 {
            assert_eq!(
                concentrated_winding_assignment(slot, 36, 30),
                expected[slot % expected.len()],
                "slot {slot} assignment mismatch",
            );
        }
    }

    // Authoritative table dumped from the FIXED Python reference layout
    // (`backend.geometry_drawer._compute_slot_placements`, distributed
    // branch, backed by `backend.winding_utils.distributed_slot_assignment`)
    // for 48s/8p: q = 48 // (3 * 8) = 2, belts of 2 slots in the sequence
    // A+, C-, B+, A-, C+, B-. Phase: 0=A, 1=B, 2=C; direction: true = "in".
    // The full-pitch dump is identical for layers=1 and layers=2: the producer
    // splits the physical slot into per-layer regions, but both layers carry
    // the same (phase, dir). Chording changes layer 2.
    #[test]
    fn distributed_winding_assignment_matches_python_geometry_for_48s8p() {
        let expected = [
            (0, true),  // slot  0: A+
            (0, true),  // slot  1: A+
            (2, false), // slot  2: C-
            (2, false), // slot  3: C-
            (1, true),  // slot  4: B+
            (1, true),  // slot  5: B+
            (0, false), // slot  6: A-
            (0, false), // slot  7: A-
            (2, true),  // slot  8: C+
            (2, true),  // slot  9: C+
            (1, false), // slot 10: B-
            (1, false), // slot 11: B-
            (0, true),  // slot 12: A+
            (0, true),  // slot 13: A+
            (2, false), // slot 14: C-
            (2, false), // slot 15: C-
            (1, true),  // slot 16: B+
            (1, true),  // slot 17: B+
            (0, false), // slot 18: A-
            (0, false), // slot 19: A-
            (2, true),  // slot 20: C+
            (2, true),  // slot 21: C+
            (1, false), // slot 22: B-
            (1, false), // slot 23: B-
            (0, true),  // slot 24: A+
            (0, true),  // slot 25: A+
            (2, false), // slot 26: C-
            (2, false), // slot 27: C-
            (1, true),  // slot 28: B+
            (1, true),  // slot 29: B+
            (0, false), // slot 30: A-
            (0, false), // slot 31: A-
            (2, true),  // slot 32: C+
            (2, true),  // slot 33: C+
            (1, false), // slot 34: B-
            (1, false), // slot 35: B-
            (0, true),  // slot 36: A+
            (0, true),  // slot 37: A+
            (2, false), // slot 38: C-
            (2, false), // slot 39: C-
            (1, true),  // slot 40: B+
            (1, true),  // slot 41: B+
            (0, false), // slot 42: A-
            (0, false), // slot 43: A-
            (2, true),  // slot 44: C+
            (2, true),  // slot 45: C+
            (1, false), // slot 46: B-
            (1, false), // slot 47: B-
        ];

        for (slot, expected_assignment) in expected.into_iter().enumerate() {
            assert_eq!(
                distributed_winding_assignment(slot, 48, 8),
                expected_assignment,
                "slot {slot} assignment mismatch",
            );
        }
    }

    // Authoritative table dumped from the FIXED Python reference layout for
    // 36s/12p: q = 36 // (3 * 12) = 1, single-slot belts in the sequence
    // A+, C-, B+, A-, C+, B- (also layer-independent).
    #[test]
    fn distributed_winding_assignment_matches_python_geometry_for_36s12p() {
        let expected = [
            (0, true),  // slot  0: A+
            (2, false), // slot  1: C-
            (1, true),  // slot  2: B+
            (0, false), // slot  3: A-
            (2, true),  // slot  4: C+
            (1, false), // slot  5: B-
            (0, true),  // slot  6: A+
            (2, false), // slot  7: C-
            (1, true),  // slot  8: B+
            (0, false), // slot  9: A-
            (2, true),  // slot 10: C+
            (1, false), // slot 11: B-
            (0, true),  // slot 12: A+
            (2, false), // slot 13: C-
            (1, true),  // slot 14: B+
            (0, false), // slot 15: A-
            (2, true),  // slot 16: C+
            (1, false), // slot 17: B-
            (0, true),  // slot 18: A+
            (2, false), // slot 19: C-
            (1, true),  // slot 20: B+
            (0, false), // slot 21: A-
            (2, true),  // slot 22: C+
            (1, false), // slot 23: B-
            (0, true),  // slot 24: A+
            (2, false), // slot 25: C-
            (1, true),  // slot 26: B+
            (0, false), // slot 27: A-
            (2, true),  // slot 28: C+
            (1, false), // slot 29: B-
            (0, true),  // slot 30: A+
            (2, false), // slot 31: C-
            (1, true),  // slot 32: B+
            (0, false), // slot 33: A-
            (2, true),  // slot 34: C+
            (1, false), // slot 35: B-
        ];

        for (slot, expected_assignment) in expected.into_iter().enumerate() {
            assert_eq!(
                distributed_winding_assignment(slot, 36, 12),
                expected_assignment,
                "slot {slot} assignment mismatch",
            );
        }
    }

    #[test]
    fn distributed_winding_assignment_balances_phases_and_directions() {
        for (slot_count, pole_count) in [(48u32, 8u32), (36, 12)] {
            let mut phase_slots = [0usize; 3];
            let mut net_direction = [0isize; 3];

            for slot in 0..slot_count as usize {
                let (phase, direction_in) =
                    distributed_winding_assignment(slot, slot_count, pole_count);
                phase_slots[phase] += 1;
                net_direction[phase] += if direction_in { 1 } else { -1 };
            }

            for phase in 0..3 {
                assert_eq!(
                    phase_slots[phase],
                    slot_count as usize / 3,
                    "{slot_count}s/{pole_count}p phase {phase} slot count imbalance",
                );
                assert_eq!(
                    net_direction[phase], 0,
                    "{slot_count}s/{pole_count}p phase {phase} net direction imbalance",
                );
            }
        }
    }

    #[test]
    fn distributed_fractional_q_36s8p_keeps_balanced_phase_axes() {
        let slot_count = 36u32;
        let pole_count = 8u32;
        let pole_pairs = pole_count as f64 / 2.0;
        let mut re = [0.0_f64; 3];
        let mut im = [0.0_f64; 3];
        let mut phase_slots = [0usize; 3];

        for slot in 0..slot_count as usize {
            let (phase, direction_in) =
                distributed_winding_assignment(slot, slot_count, pole_count);
            let sign = if direction_in { 1.0 } else { -1.0 };
            let theta_elec = 2.0 * PI * pole_pairs * slot as f64 / slot_count as f64;
            re[phase] += sign * theta_elec.cos();
            im[phase] += sign * theta_elec.sin();
            phase_slots[phase] += 1;
        }

        assert_eq!(phase_slots, [12, 12, 12]);
        let phasors = [(re[0], im[0]), (re[1], im[1]), (re[2], im[2])];
        let magnitudes = phasors.map(phasor_magnitude);
        let angles = phasors.map(phasor_angle_deg);

        for magnitude in magnitudes {
            let kw = magnitude / 12.0;
            assert!(
                (kw - 0.9597950805239389).abs() < 1e-12,
                "36s/8p q=1.5 winding factor drifted: {kw}"
            );
        }
        assert!(
            circular_angle_error_deg(angle_delta_deg(angles[0], angles[1]), 120.0).abs() < 1e-9
        );
        assert!(
            circular_angle_error_deg(angle_delta_deg(angles[1], angles[2]), 120.0).abs() < 1e-9
        );
        assert!(
            circular_angle_error_deg(angle_delta_deg(angles[2], angles[0]), 120.0).abs() < 1e-9
        );
    }

    // The regression test that would have caught the original defect: the
    // fundamental slot-phasor winding factor of the generated map must equal
    // the textbook distribution factor kd = sin(q*g/2)/(q*sin(g/2)) with
    // g = 2*pi*pole_pairs/slot_count (full pitch, kp = 1). The old map
    // measured 0.224 at q=2 (48s/8p) and 0.50 at q=1 (36s/12p).
    #[test]
    fn distributed_winding_fundamental_phasor_factor_equals_kd() {
        for (slot_count, pole_count) in [(48u32, 8u32), (36, 12)] {
            let pole_pairs = (pole_count / 2).max(1) as f64;
            let q = (slot_count / (3 * pole_count)).max(1) as f64;
            let g = 2.0 * PI * pole_pairs / slot_count as f64;
            let kd = (q * g / 2.0).sin().abs() / (q * (g / 2.0).sin());

            for target_phase in 0..3usize {
                let mut re = 0.0_f64;
                let mut im = 0.0_f64;
                let mut sides = 0usize;
                for slot in 0..slot_count as usize {
                    let (phase, direction_in) =
                        distributed_winding_assignment(slot, slot_count, pole_count);
                    if phase != target_phase {
                        continue;
                    }
                    let sign = if direction_in { 1.0 } else { -1.0 };
                    let theta_elec = 2.0 * PI * pole_pairs * slot as f64 / slot_count as f64;
                    re += sign * theta_elec.cos();
                    im += sign * theta_elec.sin();
                    sides += 1;
                }
                let kw = (re * re + im * im).sqrt() / sides as f64;
                assert!(
                    (kw - kd).abs() < 1e-6,
                    "{slot_count}s/{pole_count}p phase {target_phase}: phasor kw {kw} != kd {kd}",
                );
            }
        }
    }

    #[test]
    fn distributed_chorded_layer_phasor_factor_equals_kd_times_kp() {
        for (slot_count, pole_count, span) in [
            (48u32, 8u32, 5u32),
            (48u32, 8u32, 4u32),
            (24u32, 8u32, 2u32),
            (36u32, 12u32, 2u32),
        ] {
            let expected_kw = distributed_winding_factor(slot_count, pole_count, 1, Some(span));
            let pole_pairs = (pole_count / 2).max(1) as f64;

            for target_phase in 0..3usize {
                let mut re = 0.0_f64;
                let mut im = 0.0_f64;
                let mut sides = 0usize;
                for slot in 0..slot_count as usize {
                    for layer in 1..=2u32 {
                        let (phase, direction_in, turn_fraction) =
                            distributed_layer_winding_assignment(
                                slot,
                                slot_count,
                                pole_count,
                                layer,
                                2,
                                Some(span),
                            );
                        if phase != target_phase {
                            continue;
                        }
                        let sign = if direction_in { 1.0 } else { -1.0 };
                        let theta_elec = 2.0 * PI * pole_pairs * slot as f64 / slot_count as f64;
                        re += turn_fraction * sign * theta_elec.cos();
                        im += turn_fraction * sign * theta_elec.sin();
                        sides += 1;
                    }
                }
                let kw = (re * re + im * im).sqrt() / (sides as f64 / 2.0);
                assert!(
                    (kw - expected_kw).abs() < 1e-6,
                    "{slot_count}s/{pole_count}p span={span} phase {target_phase}: \
                     phasor kw {kw} != kd*kp {expected_kw}",
                );
            }
        }

        let kp_5_6 = distributed_pitch_factor(48, 8, 1, Some(5));
        assert!((kp_5_6 - 0.9659258262890683).abs() < 1e-12);
    }

    #[test]
    fn winding_assignment_dispatches_on_winding_type() {
        for slot in 0..48 {
            assert_eq!(
                winding_assignment("distributed", slot, 48, 8),
                distributed_winding_assignment(slot, 48, 8),
            );
            // Anything that is not explicitly distributed stays concentrated.
            assert_eq!(
                winding_assignment("concentrated", slot, 48, 8),
                concentrated_winding_assignment(slot, 48, 8),
            );
            assert_eq!(
                winding_assignment("hairpin", slot, 48, 8),
                concentrated_winding_assignment(slot, 48, 8),
            );
        }
    }

    #[test]
    fn independent_winding_phasor_test_keeps_positive_phase_sequence() {
        for (slot_count, pole_count) in [(12, 8), (36, 30)] {
            let phasors = independent_phase_axis_phasors(slot_count, pole_count);
            let magnitudes = phasors.map(phasor_magnitude);
            let angles = phasors.map(phasor_angle_deg);

            assert!(
                magnitudes.iter().all(|magnitude| *magnitude > 1e-9),
                "{slot_count}s/{pole_count}p produced a missing phase-axis phasor: {magnitudes:?}",
            );

            for phase in 1..magnitudes.len() {
                assert!(
                    (magnitudes[phase] - magnitudes[0]).abs() < 1e-9,
                    "{slot_count}s/{pole_count}p phase {phase} phasor magnitude drifted: {magnitudes:?}",
                );
            }

            let deltas = [
                ("A->B", angle_delta_deg(angles[0], angles[1])),
                ("B->C", angle_delta_deg(angles[1], angles[2])),
                ("C->A", angle_delta_deg(angles[2], angles[0])),
            ];

            for (label, delta) in deltas {
                assert!(
                    circular_angle_error_deg(delta, 120.0).abs() < 1e-9,
                    "{slot_count}s/{pole_count}p {label} phase-axis delta should be +120 deg; got {delta} deg from angles {angles:?}",
                );
            }
        }
    }

    #[test]
    fn slot_area_matches_backend_tapered_slot_block_convention() {
        let areas = estimate_slot_areas(65.0, 100.0, 24.0, 12, 15.315264186250243, 2.5);
        // The body width comes off the pitch at the body radius (bore + slot depth),
        // matching backend/geometry_drawer.py::_slot_body_width_mm. This expectation
        // used to recompute it from the bore pitch, which is the same duplication
        // that let the two paths drift apart in the first place.
        let body_radius_mm = 65.0 + (100.0 - 65.0 - 24.0);
        let body_pitch_mm = 2.0 * PI * body_radius_mm / 12.0;
        let body_width = body_pitch_mm - 15.315264186250243;
        let expected_area = 0.5 * (2.5 + body_width) * 24.0;

        assert!(areas.iter().all(|area| (area - expected_area).abs() < 1e-9));
    }

    #[test]
    fn single_layer_fscw_flux_linkage_uses_half_slot_side_turns() {
        assert!((flux_linkage_slot_side_turn_factor("concentrated", 1, 1) - 0.5).abs() < 1e-12);
        assert!((flux_linkage_slot_side_turn_factor("concentrated", 2, 1) - 1.0).abs() < 1e-12);
        assert!((flux_linkage_slot_side_turn_factor("distributed", 1, 1) - 1.0).abs() < 1e-12);
        assert!((flux_linkage_slot_side_turn_factor("concentrated", 1, 2) - 0.25).abs() < 1e-12);
    }

    #[test]
    fn distributed_flux_linkage_credit_is_layers_invariant_and_matches_analytical_turns() {
        // Cross-lane bookkeeping (twin of
        // tests/test_winding_bookkeeping_crosslane.py): turns_per_coil is the
        // conductor count of one slot's homogenized bundle, so `layers` must
        // never change the flux-linkage credit, and the peak credit of the
        // per-slot signed sum against the fundamental A_z(theta) =
        // A_hat*cos(p*theta) must equal the analytical series turns per path
        // N = kw * S * t / (6 * a) times Phi_hat = 2 * A_hat * L.
        for layers in [1u32, 2u32] {
            for paths in [1u32, 2u32] {
                let factor = flux_linkage_slot_side_turn_factor("distributed", layers, paths);
                assert!(
                    (factor - 1.0 / paths as f64).abs() < 1e-15,
                    "distributed factor must be layers-invariant 1/paths; \
                     got {factor} for layers={layers} paths={paths}"
                );
            }
        }

        // 24s/8p q=1 (spm_8p24s smoke) and 48s/8p q=2 (ORNL Prius, layers=1).
        for (slot_count, pole_count, turns, paths) in
            [(24u32, 8u32, 12.0_f64, 2u32), (48, 8, 9.0, 1)]
        {
            let pole_pairs = pole_count as f64 / 2.0;
            let (mut re, mut im) = (0.0_f64, 0.0_f64);
            for slot in 0..slot_count as usize {
                let (phase, direction_in) =
                    distributed_winding_assignment(slot, slot_count, pole_count);
                if phase != 0 {
                    continue;
                }
                let sign = if direction_in { 1.0 } else { -1.0 };
                let theta_elec = pole_pairs * slot as f64 * 2.0 * PI / slot_count as f64;
                re += sign * theta_elec.cos();
                im += sign * theta_elec.sin();
            }
            let phasor_mag = (re * re + im * im).sqrt();

            // kd = sin(q*g/2)/(q*sin(g/2)), full pitch so kw = kd.
            let q = slot_count as f64 / (3.0 * pole_count as f64);
            let g = 2.0 * PI * pole_pairs / slot_count as f64;
            let kw = (q * g / 2.0).sin() / (q * (g / 2.0).sin());

            for layers in [1u32, 2u32] {
                let paths_f = paths as f64;
                let factor = flux_linkage_slot_side_turn_factor("distributed", layers, paths);
                // Extraction peak credit per unit (A_hat * L): factor * t * |phasor|.
                let credit = factor * turns * phasor_mag;
                // Analytical: N_path * Phi_hat / (A_hat * L) = N_path * 2.
                let n_path = kw * slot_count as f64 * turns / (6.0 * paths_f);
                assert!(
                    (credit - 2.0 * n_path).abs() < 1e-9,
                    "{slot_count}s/{pole_count}p layers={layers} paths={paths}: \
                     extraction credit {credit} != 2*N_path {}",
                    2.0 * n_path
                );
            }
        }
    }

    #[test]
    fn slot_side_phasor_diagnostic_matches_36s30p_fscw_reference() {
        let mags = phase_slot_side_phasor_magnitudes(36, 30);
        let expected = 11.59110991546882;

        for mag in mags {
            assert!((mag - expected).abs() < 1e-9);
        }

        let effective_turns =
            mags[0] * 18.0 * flux_linkage_slot_side_turn_factor("concentrated", 1, 1);
        assert!((effective_turns - 104.3199892392194).abs() < 1e-9);
    }
}
