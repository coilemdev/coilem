"""Registered 0.5.9 reduced rotor-loss matrix; no field or loss solver imports."""
from __future__ import annotations

import math

import numpy as np

SPEEDS_RPM = (1500.0, 3000.0)
SPM_FIXTURE = "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"
IPM_FIXTURE = "benchmarks/windows-v3-20261015-738d951/fixtures/ipm_flat_8p12s_fsae_contract__native.json"
CASES = {
    "spm-no-load": {"fixture": SPM_FIXTURE, "current_peak_A": 0.0, "native_base_lc_mm": None,
        "native_airgap_divisions": 1536, "native_airgap_layers": 4,
        "femm_mesh": "fine", "femm_airgap_target_mm": 0.1, "femm_arc_step_deg": 0.2},
    "ipm-loaded": {"fixture": IPM_FIXTURE, "current_peak_A": 50.0, "native_base_lc_mm": None,
        "native_airgap_divisions": 1536, "native_airgap_layers": 4,
        "femm_mesh": "normal", "femm_airgap_target_mm": 0.125, "femm_arc_step_deg": 0.25},
    "ipm-loaded-finer": {"fixture": IPM_FIXTURE, "current_peak_A": 50.0, "native_base_lc_mm": 1.5,
        "native_airgap_divisions": 2304, "native_airgap_layers": 5,
        "femm_mesh": "fine", "femm_airgap_target_mm": 0.1, "femm_arc_step_deg": 0.2},
    "ipm-no-load": {"fixture": IPM_FIXTURE, "current_peak_A": 0.0, "native_base_lc_mm": None,
        "native_airgap_divisions": 1536, "native_airgap_layers": 4,
        "femm_mesh": "normal", "femm_airgap_target_mm": 0.125, "femm_arc_step_deg": 0.25},
}


def excitation_parameters(config):
    """Limit the golden sine to the two explicitly registered winding layouts."""
    if (config.rotor.pole_count != 8 or config.stator.slot_count != 12
            or config.winding.type != "concentrated" or config.winding.layers != 1
            or config.winding.parallel_paths != 1 or config.winding.coil_span is not None
            or config.solve_params.phase_connection != "wye"
            or config.solve_params.excitation_mode != "sinusoidal"
            or config.solve_params.current_angle_deg != 180
            or config.materials.magnet_grade != "N42"
            or config.materials.rotor_steel != "M350-50A"
            or config.materials.stator_steel != "M350-50A"
            or config.solve_params.magnet_temperature_C is not None):
        raise ValueError("Outside the registered matrix excitation/material contract")
    return {"pole_pairs": 4, "phase_offset_deg": 60.0,
        "peak_ampere_turns": config.solve_params.current_amplitude_A * config.winding.turns_per_coil,
        "native_gamma_deg": 180.0, "phase_offsets_deg": {"A": 0, "B": 120, "C": 240}}


def validate_excitation(excitation, angle, parameters):
    if (excitation["gate"] != "PASS" or excitation["native_rotor_mechanical_deg"] != angle
            or excitation["native_gamma_deg"] != parameters["native_gamma_deg"]):
        raise ValueError("Excitation pose, gamma or source audit differs")
    if set(excitation["phase_ampere_turns"]) != set("ABC"):
        raise ValueError("Matrix excitation requires exactly three phases")
    for phase, offset in parameters["phase_offsets_deg"].items():
        expected = parameters["peak_ampere_turns"] * math.sin(math.radians(
            parameters["pole_pairs"] * angle + parameters["phase_offset_deg"] - offset))
        actual = excitation["phase_ampere_turns"][phase]
        if not math.isfinite(actual) or abs(actual - expected) > 1e-8:
            raise ValueError("Native ampere-turns differ from independent matrix sine")


def material_query_points(template):
    mesh = template["mesh"]
    ids = [r["id"] for r in template["physics_contract"]["regions"] if r["kind"] == "RotorCore"]
    corners = np.asarray(mesh["nodes"])[np.asarray(mesh["triangles"], dtype=int)]
    cells = corners[np.isin(template["element_region_ids"], ids)]
    if not len(cells):
        raise ValueError("The matrix template has no rotor steel")
    return cells.mean(axis=1)[np.linspace(0, len(cells)-1, min(384, len(cells)), dtype=int)]
