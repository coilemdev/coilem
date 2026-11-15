"""Fixed-geometry moving-air-gap helpers for the bounded #306 reference pilot.

FEMM displays the rotor at its drawn pose. Its rotor mesh and B vectors remain
in rotor-material axes; motion is represented by boundary property 10, not by
moving geometry. These helpers do not modify the sealed E/F implementations.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

BOUNDARY = "RotorLossPeriodicAirGap"


def band_radii(rotor_surface_mm, stator_bore_mm):
    if not all(math.isfinite(v) and v > 0 for v in (rotor_surface_mm, stator_bore_mm)):
        raise ValueError("air-gap radii must be positive and finite")
    gap = stator_bore_mm - rotor_surface_mm
    if gap <= 0:
        raise ValueError("a free circular air gap is required")
    return rotor_surface_mm + gap/3, rotor_surface_mm + 2*gap/3


def add_periodic_airgap(femm, solver, config, geom):
    """Insert an unmeshed circular band wholly inside this full-machine air gap."""
    from backend.femm_geometry import _femm_airgap_inner_radius_mm

    inner, outer = band_radii(_femm_airgap_inner_radius_mm(geom), geom.stator_ID_r)
    femm.mi_addboundprop(BOUNDARY, 0, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0)
    for radius in (inner, outer):
        solver._draw_circle(femm, radius)
        for degrees in (45, 135, 225, 315):
            angle = math.radians(degrees)
            femm.mi_selectarcsegment(radius*math.cos(angle), radius*math.sin(angle))
        femm.mi_setarcsegmentprop(0.25, BOUNDARY, 0, 0)
        femm.mi_clearselected()
    # The original inter-magnet air label remains on the rotor side.
    for radius, material in (((inner+outer)/2, "<No Mesh>"), ((outer+geom.stator_ID_r)/2, "Air")):
        femm.mi_addblocklabel(radius, 0)
        femm.mi_selectlabel(radius, 0)
        if material == "Air":
            solver._set_femm_blockprop(femm, material, config, geom, "airgap")
        else:
            femm.mi_setblockprop(material, 1, 0, "<None>", 0, 0, 0)
        femm.mi_clearselected()
    return {"inner_radius_mm": inner, "outer_radius_mm": outer, "arc_step_deg": 0.25}


def update_pose_and_currents(femm, adapter, config, geom, mechanical_angle_deg):
    from backend.geometry_drawer import compute_3phase_current_density_for_rotor_elec

    if not math.isfinite(mechanical_angle_deg):
        raise ValueError("the native mechanical angle must be finite")
    # Preserve -360 as -360. Do not canonicalise the closure endpoint to zero.
    femm.mi_modifyboundprop(BOUNDARY, 10, mechanical_angle_deg)
    currents = compute_3phase_current_density_for_rotor_elec(config, -mechanical_angle_deg*config.rotor.pole_count/2)
    for region in adapter.winding_regions(config, geom):
        slot, layer, phase, direction = adapter.assignment(region)
        density = currents[phase] * (1 if direction == "in" else -1)
        femm.mi_modifymaterial(f"Coil_v3_s{slot}_l{layer}", 4, density)


def mesh_signature(answer_path):
    """Hash all triangular mesh coordinates/connectivity, excluding the solution.

    The A_z solution changes with pose. The raw triangular mesh must not.
    Air-gap interpolation data after the triangles is intentionally excluded.
    """
    lines = Path(answer_path).read_text(encoding="latin-1").splitlines()
    cursor = lines.index("[Solution]") + 1
    node_count = int(lines[cursor])
    cursor += 1
    nodes = np.asarray([[float(x) for x in line.split()[:2]] for line in lines[cursor:cursor+node_count]], dtype="<f8")
    cursor += node_count
    triangle_count = int(lines[cursor])
    cursor += 1
    triangles = np.asarray([[int(x) for x in line.split()[:5]] for line in lines[cursor:cursor+triangle_count]], dtype="<i8")
    if nodes.shape != (node_count, 2) or triangles.shape != (triangle_count, 5):
        raise ValueError("malformed FEMM mesh in answer file")
    return hashlib.sha256(nodes.tobytes()+triangles.tobytes()).hexdigest()
