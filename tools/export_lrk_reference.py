"""Write the LRK reference design, backend/reference_models/lrk_12s14p_config.json.

The solved geometry comes from the hash-checked source drawing. These sections
describe it for the design panel, health checks, winding and resistance models,
and pin it: the reference rejects any edit to them.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from backend.models import MotorConfig
from backend.reference_models import lrk

ROOT = Path(__file__).resolve().parents[1]
SOLVE_DEFAULTS = ROOT / "benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json"


def reference_config() -> dict:
    steels = lrk.custom_steels()
    stator_steel, rotor_steel = steels["M-19 Steel"], steels["1018 Steel"]
    pole_pitch_deg = 360 / 14
    magnet_span_deg = 20.0
    magnet_mid_radius = lrk.MAGNET_INNER_RADIUS_MM + 0.5
    solve_params = json.loads(SOLVE_DEFAULTS.read_text(encoding="utf-8"))["solve_params"]
    solve_params.update(
        excitation_mode="ideal_six_step_120", current_amplitude_convention="plateau", current_amplitude_A=4.0,
        commutation_advance_deg=0.0, current_angle_deg=0.0, rated_speed_rpm=1000, magnet_temperature_C=None,
        rotor_rotation_model="remesh_per_step",
        # References load with an explicit iteration cap (designFile.ts); pin the same one.
        max_nonlinear_iterations=200,
    )
    config = {
        "schema_version": "1.0",
        "topology": "SPM",
        "rotor_layout": "outer",
        "stator": {
            "OD_mm": 2 * lrk.TOOTH_TIP_RADIUS_MM,
            "ID_mm": 2 * lrk.BORE_RADIUS_MM,
            "slot_count": 12,
            "stack_length_mm": 10.0,
            # Gap-side mouth between the tooth tips, and the tooth body at the slot bottom.
            "slot_opening_mm": round(lrk.TOOTH_TIP_RADIUS_MM * math.radians(18.809 - 11.191), 4),
            "tooth_width_mm": round(lrk.SLOT_BOTTOM_RADIUS_MM * math.radians(39.066 - 20.934), 4),
            "yoke_thickness_mm": lrk.SLOT_BOTTOM_RADIUS_MM - lrk.BORE_RADIUS_MM,
            "tooth_shoe_enabled": False,
        },
        "rotor": {
            "OD_mm": 2 * lrk.ROTOR_OUTER_RADIUS_MM,
            # The magnet seat: magnets are 1 mm thick on a 13 mm gap face.
            "ID_mm": 2 * (lrk.MAGNET_INNER_RADIUS_MM + 1.0),
            "magnet_thickness_mm": 1.0,
            "magnet_width_mm": round(magnet_mid_radius * math.radians(magnet_span_deg), 4),
            "pole_count": 14,
            "magnet_embrace": round(magnet_span_deg / pole_pitch_deg, 6),
        },
        "winding": {"type": "concentrated", "turns_per_coil": 15, "layers": 1, "parallel_paths": 1},
        "materials": {
            "stator_steel": stator_steel.id,
            "rotor_steel": rotor_steel.id,
            "magnet_grade": lrk.MAGNET_GRADE,
            "conductor": "copper",
            "custom_steels": {steel.id: steel.model_dump(mode="json") for steel in (stator_steel, rotor_steel)},
        },
        "solve_params": solve_params,
    }
    # Validated as an ordinary design: the reference check reads the file this writes.
    validated = MotorConfig.model_validate(config).model_dump(mode="json")
    return {**validated, "geometry_reference": lrk.REFERENCE, "reference_case": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "backend/reference_models/lrk_12s14p_config.json")
    args = parser.parse_args()
    args.out.write_text(json.dumps(reference_config(), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
