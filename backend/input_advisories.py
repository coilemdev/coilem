"""Describe interpreted inputs and sampled outputs without changing solved physics."""
from __future__ import annotations

import math

from backend.geometry_drawer import compute_v_shape_magnet_placements
from backend.models import MotorConfig


def vshape_input_facts(config: MotorConfig) -> dict[str, float]:
    if config.geometry_reference or config.topology != "IPM" or config.rotor.ipm_topology != "v_shape":
        return {}
    magnets = compute_v_shape_magnet_placements(config)
    radii = [math.hypot(x, y) for m in magnets for x, y in (m.pocket_corners_mm or m.corners_mm or ())]
    if not radii:
        return {}
    return {
        "minimum_outer_bridge_mm": config.rotor.outer_bridge_thickness_mm,
        "actual_outer_bridge_mm": config.rotor.OD_mm / 2 - max(radii),
    }


def geometry_input_advisories(config: MotorConfig) -> list[str]:
    facts = vshape_input_facts(config)
    if not facts:
        return []
    return [
        f"V-shape outer bridge is a minimum clearance: requested {facts['minimum_outer_bridge_mm']:.3g} mm; "
        f"actual nearest pocket-to-surface clearance {facts['actual_outer_bridge_mm']:.3g} mm. "
        "V Depth, V Angle and magnet dimensions determine the actual bridge.",
        "Saved magnet coverage is not used for V-shape rotors. "
        "Magnet coverage is determined by the slab dimensions and V geometry.",
    ]


def geometry_mesh_advisories(config: MotorConfig) -> list[str]:
    if not vshape_input_facts(config):
        return []
    return [
        "V-shape results are mesh-sensitive, especially cogging torque. Compare progressively refined meshes "
        "for this design before relying on the values; a Fine mesh alone does not establish convergence.",
    ]


def partial_sweep_advisory(complete: bool | None) -> str | None:
    if complete is not False:
        return None
    return ("Partial electrical sweep: average torque and d/q flux linkage describe only the sampled angular window, "
            "not a full-cycle average. Use a full 360-degree electrical sweep for cycle-average comparisons.")
