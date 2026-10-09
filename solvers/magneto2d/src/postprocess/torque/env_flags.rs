// Environment-variable readers + weighted-stress helper
// utilities, lifted from postprocess/torque.rs (3554 lines) to keep the
// entrypoint module focused on torque computations. Behaviour is verbatim
// — no logic edits, only visibility (`pub(super)`) so the parent module
// can call these from compute_torque_weighted_stress_debug et al.

use crate::mesh::{Region, TriMesh};

pub(super) fn weighted_stress_airgap_only() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_AIRGAP_ONLY",
        "MAGNETO2D_WEIGHTED_STRESS_AIRGAP_ONLY",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_domain(region: Region, include_slots: bool) -> bool {
    // FluxBarrier and MagnetPocketAir are air material, but they are buried
    // rotor pockets, not the physical rotor/stator airgap integration band.
    region == Region::Airgap || (include_slots && region == Region::SlotWinding)
}

pub(super) fn weighted_stress_inner_boundary_region(region: Region) -> bool {
    matches!(region, Region::RotorCore | Region::Magnet)
}

pub(super) fn weighted_stress_outer_boundary_region(region: Region, include_slots: bool) -> bool {
    matches!(region, Region::StatorTooth | Region::StatorYoke)
        || (!include_slots && region == Region::SlotWinding)
}

pub(super) fn weighted_stress_physical_bounds(
    mesh: &TriMesh,
    include_slots: bool,
) -> Option<(f64, f64, f64)> {
    let airgap_band = mesh.info.airgap_band()?;
    let inner = airgap_band.inner_radius_m();
    let bore = airgap_band.outer_radius_m();
    if inner <= 0.0 || bore <= inner {
        return None;
    }
    let slot_outer = if include_slots && mesh.info.stator_slot_outer_radius_mm > bore * 1e3 {
        mesh.info.stator_slot_outer_radius_mm * 1e-3
    } else {
        bore
    };
    Some((inner, bore, slot_outer))
}

pub(super) fn triangle_centroid_radius(mesh: &TriMesh, tri: &[usize; 3]) -> f64 {
    let [i, j, k] = *tri;
    let [x1, y1] = mesh.nodes[i];
    let [x2, y2] = mesh.nodes[j];
    let [x3, y3] = mesh.nodes[k];
    let cx = (x1 + x2 + x3) / 3.0;
    let cy = (y1 + y2 + y3) / 3.0;
    (cx * cx + cy * cy).sqrt()
}

pub(super) fn weighted_stress_triangle_in_domain(
    mesh: &TriMesh,
    tri_idx: usize,
    include_slots: bool,
    physical_bounds: Option<(f64, f64, f64)>,
) -> bool {
    let region = mesh.regions[tri_idx];
    if !weighted_stress_domain(region, include_slots) {
        return false;
    }
    let Some((magnet_outer, bore, slot_outer)) = physical_bounds else {
        return true;
    };
    let radius = triangle_centroid_radius(mesh, &mesh.triangles[tri_idx]);
    let tol = ((bore - magnet_outer).abs() * 1.0e-6).max(1.0e-12);
    match region {
        Region::Airgap => radius >= magnet_outer - tol && radius <= bore + tol,
        Region::SlotWinding => include_slots && radius >= bore - tol && radius <= slot_outer + tol,
        _ => false,
    }
}

pub(super) fn weighted_stress_excluded_boundary_side(
    mesh: &TriMesh,
    tri_idx: usize,
    include_slots: bool,
    physical_bounds: Option<(f64, f64, f64)>,
) -> Option<f64> {
    let region = mesh.regions[tri_idx];
    if weighted_stress_inner_boundary_region(region) {
        return Some(1.0);
    }
    if weighted_stress_outer_boundary_region(region, include_slots) {
        return Some(0.0);
    }
    let Some((magnet_outer, bore, _slot_outer)) = physical_bounds else {
        return None;
    };
    if region == Region::Airgap {
        let radius = triangle_centroid_radius(mesh, &mesh.triangles[tri_idx]);
        let tol = ((bore - magnet_outer).abs() * 1.0e-6).max(1.0e-12);
        if radius < magnet_outer - tol {
            return Some(1.0);
        }
        if radius > bore + tol {
            return Some(0.0);
        }
    }
    None
}

pub(super) fn weighted_stress_use_nodal_b() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_ELEMENT_B",
        "MAGNETO2D_WEIGHTED_STRESS_ELEMENT_B",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return false;
        }
    }
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_NODAL_B",
        "MAGNETO2D_WEIGHTED_STRESS_NODAL_B",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    true
}

pub(super) fn weighted_stress_boundary_aware_b() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_AWARE_B",
        "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_AWARE_B",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_use_az_field() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_AZ_FIELD",
        "MAGNETO2D_WEIGHTED_STRESS_AZ_FIELD",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_boundary_wedge_sampling() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_SAMPLING",
        "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_SAMPLING",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_boundary_wedge_taper() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER",
        "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_env_f64(names: &[&str], default: f64, min: f64, max: f64) -> f64 {
    for name in names {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let Ok(value) = raw.trim().parse::<f64>() else {
            continue;
        };
        if value.is_finite() {
            return value.clamp(min, max);
        }
    }
    default
}

pub(super) fn weighted_stress_boundary_wedge_sample_fraction() -> f64 {
    weighted_stress_env_f64(
        &[
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_SAMPLE_FRACTION",
            "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_SAMPLE_FRACTION",
        ],
        0.75,
        0.50,
        0.95,
    )
}

pub(super) fn weighted_stress_boundary_wedge_fraction_threshold() -> f64 {
    weighted_stress_env_f64(
        &[
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_FRACTION_THRESHOLD",
            "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_FRACTION_THRESHOLD",
        ],
        0.70,
        0.0,
        0.95,
    )
}

pub(super) fn weighted_stress_boundary_wedge_taper_factor() -> f64 {
    weighted_stress_env_f64(
        &[
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FACTOR",
            "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FACTOR",
        ],
        0.0,
        0.0,
        1.0,
    )
}

// Cogging boundary-wedge correction: the topological boundary-wedge
// classifier in `weighted_stress_interface_class` cannot tell numerical
// contamination triangles (sharp |B|^2 step at iron/airgap interface) from
// legitimate-cogging triangles (smooth field at the slot mouth). On 8p12s the
// tagged set is mostly contamination so factor=0.0 is correct; on 4p12s the
// tagged set is mostly legitimate signal so factor=0.0 over-shaves cogging.
// Adding a field-aware criterion gates the taper to only triangles whose per-
// node |B|^2 actually shows the contamination signature: relative spread
// (b2_max - b2_min) / b2_max above a threshold. Disabled by default; set
// COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FIELD_GATE=1 to enable.
// Field gating distinguishes sharp contamination from smooth cogging fields.
pub(super) fn weighted_stress_boundary_wedge_field_gate_enabled() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FIELD_GATE",
        "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FIELD_GATE",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_boundary_wedge_field_threshold() -> f64 {
    weighted_stress_env_f64(
        &[
            "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FIELD_THRESHOLD",
            "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_FIELD_THRESHOLD",
        ],
        0.5, // default: high-B^2 node must be at least 2x the low-B^2 node
        0.0,
        1.0,
    )
}

pub(super) fn weighted_stress_boundary_wedge_taper_outer_bulk() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_OUTER_BULK",
        "MAGNETO2D_WEIGHTED_STRESS_BOUNDARY_WEDGE_TAPER_OUTER_BULK",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}

pub(super) fn weighted_stress_stator_boundary_layer(
    interface_class: &str,
    include_outer_bulk: bool,
) -> bool {
    matches!(
        interface_class,
        "slot_mouth_boundary" | "tooth_tip_boundary" | "slot_mouth_tooth_tip_boundary"
    ) || (include_outer_bulk && interface_class == "outer_airgap_bulk")
}

pub(super) fn weighted_stress_localization_enabled() -> bool {
    for name in [
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_LOCALIZATION",
        "MAGNETO2D_WEIGHTED_STRESS_LOCALIZATION",
    ] {
        let Ok(raw) = std::env::var(name) else {
            continue;
        };
        let normalized = raw.trim().to_ascii_lowercase();
        if !normalized.is_empty()
            && normalized != "0"
            && normalized != "false"
            && normalized != "no"
            && normalized != "off"
        {
            return true;
        }
    }
    false
}
