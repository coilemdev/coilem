"""Write Phase F, the outer-rotor benchmark (protocol 1.8.0): its requests and suite.

Every request is the registered Phase A request `spm_8p12s_concentrated__baseline`
with its motor replaced by an outer-rotor SPM design and its current set per case.
Solve settings, materials, speed and the angle grid stay Phase A's, so Phase F
grades against FEMM with Phase A's gates.

    python -m tools.make_outrunner_phase_f          # rewrite benchmarks/abcd-v1.8
"""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path

from backend.benchmark_suite.contract import canonical, read, sha, write

ROOT = Path(__file__).resolve().parents[1]
SUITE = "benchmarks/abcd-v1.8"
BASE_SUITE = "benchmarks/abcd-v1.6/benchmark_spec.json"
TEMPLATE_CASE = "spm_8p12s_concentrated__baseline"
MAGNET_COVERAGE = 0.85


def _shoed(stator, *, mouth_mm, height_mm):
    """Parallel teeth with tooth shoes: the slot body opens to the full pitch minus the tooth
    width at the stator OD, and each shoe's two overhangs narrow it to ``mouth_mm``."""
    body_opening = round(math.pi * stator["OD_mm"] / stator["slot_count"] - stator["tooth_width_mm"], 2)
    return {**stator, "slot_opening_mm": body_opening, "tooth_shoe_enabled": True, "tooth_shoe_height_mm": height_mm,
            "tooth_shoe_overhang_mm": round((body_opening - mouth_mm) / 2, 3)}


def _rotor(stator_od_mm, *, airgap_mm, magnet_mm, back_iron_mm, poles):
    """An outer rotor whose magnets cover 85% of the pole pitch at their mid radius."""
    seat_r = stator_od_mm / 2 + airgap_mm + magnet_mm
    mid_r = seat_r - magnet_mm / 2
    return {
        "ID_mm": round(2 * seat_r, 3),
        "OD_mm": round(2 * (seat_r + back_iron_mm), 3),
        "magnet_thickness_mm": magnet_mm,
        "magnet_width_mm": round(MAGNET_COVERAGE * 2 * math.pi * mid_r / poles, 2),
        "magnet_embrace": MAGNET_COVERAGE,
        "pole_count": poles,
    }


# Hobby outer-rotor sizes, 18 mm to 100 mm stators. Stator OD is the air-gap face
# and stator ID the hub bore; rotor ID is the magnet seat (docs/OUTRUNNER.md).
# Four motors have parallel teeth with tooth shoes, as most real outrunners do;
# the 12/10 single-layer motor keeps plain tapered teeth, so both stators are covered.
DESIGNS = {
    # The app's starter outrunner: a 2806-class drone motor, tooth coils.
    "14p12s_drone": {
        "stator": _shoed({"OD_mm": 28.0, "ID_mm": 10.0, "slot_count": 12, "stack_length_mm": 6.0,
                          "tooth_width_mm": 2.0, "yoke_thickness_mm": 2.0}, mouth_mm=2.0, height_mm=0.6),
        "rotor": _rotor(28.0, airgap_mm=0.4, magnet_mm=1.5, back_iron_mm=1.6, poles=14),
        "winding": {"layers": 2, "turns_per_coil": 12},
    },
    # An 1806-class micro drone motor, tooth coils.
    "12p9s_micro": {
        "stator": _shoed({"OD_mm": 18.0, "ID_mm": 6.0, "slot_count": 9, "stack_length_mm": 6.0,
                          "tooth_width_mm": 1.8, "yoke_thickness_mm": 1.5}, mouth_mm=1.5, height_mm=0.5),
        "rotor": _rotor(18.0, airgap_mm=0.35, magnet_mm=1.2, back_iron_mm=1.3, poles=12),
        "winding": {"layers": 2, "turns_per_coil": 14},
    },
    # A 42 mm 12-slot / 10-pole outrunner with a single-layer winding (alternate teeth).
    "10p12s_single_layer": {
        "stator": {"OD_mm": 42.0, "ID_mm": 20.0, "slot_count": 12, "stack_length_mm": 15.0,
                   "slot_opening_mm": 3.0, "tooth_width_mm": 4.0, "yoke_thickness_mm": 3.0},
        "rotor": _rotor(42.0, airgap_mm=0.4, magnet_mm=2.0, back_iron_mm=2.5, poles=10),
        "winding": {"layers": 1, "turns_per_coil": 20},
    },
    # A 5010-class heavy-lift multirotor motor, tooth coils.
    "28p24s_multirotor": {
        "stator": _shoed({"OD_mm": 50.0, "ID_mm": 30.0, "slot_count": 24, "stack_length_mm": 10.0,
                          "tooth_width_mm": 2.6, "yoke_thickness_mm": 2.5}, mouth_mm=2.0, height_mm=0.7),
        "rotor": _rotor(50.0, airgap_mm=0.35, magnet_mm=2.0, back_iron_mm=2.5, poles=28),
        "winding": {"layers": 2, "turns_per_coil": 10},
    },
    # A hub-motor-class 27-slot / 30-pole outrunner, 100 mm stator, tooth coils.
    "30p27s_hub": {
        "stator": _shoed({"OD_mm": 100.0, "ID_mm": 70.0, "slot_count": 27, "stack_length_mm": 25.0,
                          "tooth_width_mm": 5.0, "yoke_thickness_mm": 3.5}, mouth_mm=3.0, height_mm=1.0),
        "rotor": _rotor(100.0, airgap_mm=0.5, magnet_mm=2.5, back_iron_mm=3.5, poles=30),
        "winding": {"layers": 2, "turns_per_coil": 12},
    },
}

# (case id, design, peak phase current A, current angle deg, rotor overrides)
CASES = (
    ("spm_outer_14p12s_drone__baseline", "14p12s_drone", 10.0, 0.0, {}),
    ("spm_outer_14p12s_drone__high_current", "14p12s_drone", 15.0, 0.0, {}),
    # Only the air gap closes, 0.4 mm to 0.25 mm: the magnets and the rotor OD stay.
    ("spm_outer_14p12s_drone__tight_airgap", "14p12s_drone", 10.0, 0.0, {"ID_mm": 31.5}),
    ("spm_outer_14p12s_drone__angle30", "14p12s_drone", 10.0, 30.0, {}),
    ("spm_outer_14p12s_drone_noload__baseline", "14p12s_drone", 0.0, 0.0, {}),
    ("spm_outer_12p9s_micro__baseline", "12p9s_micro", 5.0, 0.0, {}),
    ("spm_outer_12p9s_micro_noload__baseline", "12p9s_micro", 0.0, 0.0, {}),
    ("spm_outer_10p12s_single_layer__baseline", "10p12s_single_layer", 15.0, 0.0, {}),
    ("spm_outer_28p24s_multirotor__baseline", "28p24s_multirotor", 10.0, 0.0, {}),
    ("spm_outer_30p27s_hub__baseline", "30p27s_hub", 20.0, 0.0, {}),
)


def _template():
    base = read(ROOT / BASE_SUITE)
    case = next(case for case in base["cases"] if case["id"] == TEMPLATE_CASE)
    job = case["jobs"][0]
    request = read(ROOT / job["fixture"])
    if canonical(request) != job["input_sha256"]:
        raise ValueError("The Phase A template request changed")
    return request


def requests():
    """Each case's request, keyed by case id."""
    template = _template()
    out = {}
    for case_id, design_id, current_A, angle_deg, rotor_overrides in CASES:
        design = DESIGNS[design_id]
        request = deepcopy(template)
        request["rotor_layout"] = "outer"
        request["stator"].update(design["stator"])
        request["rotor"].update(design["rotor"], **rotor_overrides)
        request["winding"].update(design["winding"])
        request["solve_params"].update(current_amplitude_A=current_A, current_angle_deg=angle_deg)
        out[case_id] = dict(sorted(request.items()))
    return out


def suite(fixtures):
    """The protocol 1.8.0 suite for these requests."""
    base = read(ROOT / BASE_SUITE)
    cases = []
    for case_id, design_id, current_A, angle_deg, _ in CASES:
        request = fixtures[case_id]
        path = f"{SUITE}/fixtures/{case_id}.json"
        cases.append({
            "id": case_id,
            "phase": "F",
            "design": design_id,
            "slots": request["stator"]["slot_count"],
            "poles": request["rotor"]["pole_count"],
            "jobs": [{
                "stage": "native",
                "fixture": path,
                "fixture_sha256": sha(ROOT / path) if (ROOT / path).is_file() else None,
                "input_sha256": canonical(request),
            }],
        })
    return {
        "schema": base["schema"],
        "protocol_version": "1.8.0",
        "convention": base["convention"],
        "material_contract": base["material_contract"],
        "golden": base["golden"],
        "golden_sha256": base["golden_sha256"],
        "cases": cases,
        "phase_f": {
            "status": "PROPOSED_NOT_REGISTERED",
            "base_suite": BASE_SUITE,
            "base_suite_sha256": sha(ROOT / BASE_SUITE),
            "derivation": f"the Phase A request {TEMPLATE_CASE} with an outer-rotor SPM motor and the case's current",
            "gates": "Phase A's (benchmark_suite/abc_metrics.py): mean torque 8%/15% (0.01/0.02 N m when the reference "
                     "is under 0.01 N m), back-EMF fundamental and peak 10%/15%, WST, native mesh, matching angle grids",
            "reference_bundle": None,
        },
    }


def main():
    fixtures = requests()
    for case_id, request in fixtures.items():
        write(ROOT / SUITE / "fixtures" / f"{case_id}.json", request)
    write(ROOT / SUITE / "benchmark_spec.json", suite(fixtures))
    print(f"wrote {len(fixtures)} requests and {SUITE}/benchmark_spec.json")


if __name__ == "__main__":
    main()
