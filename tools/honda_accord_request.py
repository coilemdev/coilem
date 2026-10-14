"""Build the frozen 2005 Honda Accord coilEM request from ORNL/TM-2006/535 (Phase A, #92).

    python tools/honda_accord_request.py   # writes docs/hardware-validation/honda-accord-2005/request.json

Inputs come only from the report's design data (Table 2.3, Fig. 2.5, Fig. 2.4 photos) and the
owner-approved assumptions (N35 magnets, one flat magnet per pole, M350-50A steel). The winding
is coilEM's concentrated map with the #91 emulation; currents and linkages are transformed outside
coilEM. The real winding is 24 bobbin coils of 52 turns, 8 in parallel per phase. coilEM allows at most
6 parallel paths, so the request uses the exact field equivalent with 1 path: 13 conductors per slot.
Real slot ampere-turns 52 (iA - iC)/8 = 13 i'A with i'A = (iA - iC)/2, and the re-paired linkage
(l'A - l'B)/2 = 8 x 13 L dA / 2 = 52 L dA, one real coil's (= the phase's, 8 identical coils in parallel).
"""
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/hardware-validation/honda-accord-2005/request.json"

ID, OD, SLOTS, DEPTH = 232.0, 315.5, 24, 30.6
BORE_R = ID / 2
pitch_rad = 2 * math.pi / SLOTS

# Fig. 2.5, read at the drawing's scale (30.6 mm = slot depth): tooth angle 8.884 deg at the top of the
# 20-degree wedge (r = 118.03 mm, slot body 12.61 mm wide) and 7.505 deg at the slot-bottom corners
# (r = 145.73 mm, slot bottom 19.05 mm wide). coilEM draws a linear angular taper from the bore to the
# yoke, so extrapolate that line to the bore (r = 116) and to the yoke radius (r = 116 + 30.6).
def tooth_angle_deg(r):
    return 8.884 + (7.505 - 8.884) * (r - 118.03) / (145.73 - 118.03)

tooth_bore = BORE_R * math.radians(tooth_angle_deg(BORE_R))
yoke_r = BORE_R + DEPTH
tooth_yoke = yoke_r * math.radians(tooth_angle_deg(yoke_r))
slot_opening = math.pi * ID / SLOTS - tooth_bore          # slot body width behind the shoes
overhang = (slot_opening - 4.75) / 2                      # mouth 4.75 mm (Fig. 2.5, Table 2.3)
# Shoe: 0.66 mm tip plus a 20-degree wedge up to 2.03 mm over (12.61 - 4.75)/2 = 3.93 mm. coilEM draws a
# rectangular shoe, so keep the same steel area per side.
wedge_run = (12.61 - 4.75) / 2
shoe_area = wedge_run * 0.66 + 0.5 * wedge_run * (2.03 - 0.66)
shoe_height = shoe_area / overhang

request = {
    "schema_version": "1.0",
    "topology": "IPM",
    "stator": {
        "OD_mm": OD, "ID_mm": ID, "slot_count": SLOTS, "stack_length_mm": 40.1,
        "yoke_thickness_mm": round((OD - ID) / 2 - DEPTH, 3),
        "tooth_width_mm": round(tooth_yoke, 3),
        "slot_opening_mm": round(slot_opening, 3),
        "tooth_shoe_enabled": True,
        "tooth_shoe_height_mm": round(shoe_height, 3),
        "tooth_shoe_overhang_mm": round(overhang, 3),
    },
    "rotor": {
        "OD_mm": 230.0, "ID_mm": 188.0, "pole_count": 16,
        "ipm_topology": "flat_buried", "flat_buried_magnet_shape": "straight",
        # Two 18.45 x 4.46 mm magnets per pole with a ~1.5 mm rib (Fig. 2.4d) -> one 36.9 mm bar per pole.
        "magnet_width_mm": 36.9, "magnet_thickness_mm": 4.46,
        "bridge_thickness_mm": 1.0,       # Fig. 2.4d: magnets ~1 mm under the surface (photo estimate)
        "pocket_clearance_mm": 0.25,      # coilEM default; not resolvable from the photos
        "magnet_angle_deg": 0.0,
    },
    "winding": {"type": "concentrated", "layers": 1, "turns_per_coil": 13, "parallel_paths": 1},
    "materials": {"stator_steel": "M350-50A", "rotor_steel": "M350-50A", "magnet_grade": "N35", "conductor": "copper"},
    "solve_params": {
        "solve_quality": "custom", "rotor_sweep_range_deg": 360.0, "rotor_step_deg": 2.0,
        "mesh_density": "normal", "mesh_source": "native", "mesher": "gmsh",
        "rotor_rotation_model": "remesh_per_step", "torque_method": "weighted_stress",
        "nonlinear_solver": "newton", "max_nonlinear_iterations": 200, "linear_solver_preconditioner": "direct",
        "current_amplitude_A": 0.0, "current_amplitude_convention": "peak", "current_angle_deg": 0.0,
        "rated_speed_rpm": 1000,
    },
    "solve_options": {"torque_sweep": True, "back_emf": True, "flux_density": False, "cogging_torque": False,
                      "thd_analysis": False, "torque_speed_envelope": False},
}


def main() -> None:
    OUT.write_text(json.dumps(request, indent=1) + "\n", encoding="utf-8")
    print(f"tooth at the bore {tooth_bore:.3f} mm; wrote {OUT}")


if __name__ == "__main__":
    main()
