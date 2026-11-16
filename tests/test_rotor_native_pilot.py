"""Native pilot checks the actual excitation and global/material field conversion."""

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from backend.models import MotorConfig
from backend.solver import _clockwise_excitation_config
from tools.rotor_native_pilot import audit_excitation, field_sample, query_sample, validate_convergence

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def current_fixture(angle):
    config = _clockwise_excitation_config(MotorConfig.model_validate(json.loads(FIXTURE.read_text())))
    # Independent sine source: 4 pole pairs, public gamma=0 -> native gamma=180,
    # phase-A winding axis=30 degrees. N I = 12 * 20 * sin(4 theta + 60 - phase).
    currents = {p: 240*np.sin(np.deg2rad(4*angle+60-offset)) for p, offset in zip("ABC", (0, 120, 240))}
    regions = []
    for i in range(12):
        phase, sign, area = "ABC"[i % 3], (1 if i % 2 else -1), 80+i
        regions.append({"id": f"slot_{i}", "kind": "SlotWinding", "winding": {"phase": phase,
                        "direction": "in" if sign == 1 else "out", "area_mm2": area, "turn_fraction": 1,
                        "current_density_a_per_m2": currents[phase]*sign/area*1e6}})
    return config, {"rotor_angle_mech_deg": angle,
                    "physics_contract": {"motion": {"rotor_angle_mech_deg": angle}, "regions": regions}}


@pytest.mark.parametrize("angle", [0, -0.9375, -22.5, -360])
def test_public_gamma_is_mirrored_once_and_ampere_turns_match_an_independent_sine(angle):
    config, artifact = current_fixture(angle)
    result = audit_excitation(artifact, config, angle)
    assert result["gate"] == "PASS" and result["native_gamma_deg"] == 180


def test_opposite_current_and_wrong_pose_cannot_pass():
    config, artifact = current_fixture(-22.5)
    wrong = deepcopy(artifact)
    wrong["physics_contract"]["regions"][0]["winding"]["current_density_a_per_m2"] *= -1
    with pytest.raises(ValueError, match="ampere-turns"):
        audit_excitation(wrong, config, -22.5)
    with pytest.raises(ValueError, match="mesh pose"):
        audit_excitation(artifact, config, 22.5)


@pytest.mark.parametrize("angle", [-360, -22.5, 0, 33])
def test_native_nodal_potential_gives_the_prescribed_material_field(angle):
    material = np.array([[5.0, 0.0], [6.0, 0.0], [5.0, 1.0]])
    a = np.deg2rad(angle)
    rotation = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    nodes = material @ rotation.T
    desired = np.array([0.2, -0.1])
    global_b = desired @ rotation.T
    az = (global_b[0]*nodes[:, 1]-global_b[1]*nodes[:, 0])*1e-3
    report = {"mesh_info": {"total_span_deg": 360}, "field_plot": {"total_span_deg": 360,
              "nodes_mm": nodes.tolist(), "triangles": [[0, 1, 2]], "regions": ["RotorCore"], "az_nodal": az.tolist()}}
    sample = field_sample(report, angle)
    assert np.allclose(sample.corners_mm[0], material, atol=1e-12, rtol=0)
    assert np.allclose(query_sample(sample, [[5.2, 0.2]])[0], desired, atol=1e-12, rtol=0)
    with pytest.raises(ValueError, match="left the laminated"):
        query_sample(sample, [[50, 50]])
    report["mesh_info"]["total_span_deg"] = 180
    with pytest.raises(ValueError, match="full-machine"):
        field_sample(report, angle)


def test_unforwarded_tolerance_or_reused_solution_is_rejected():
    convergence = {"tolerance": 1e-5, "scaled_residual": 3e-6, "rhs_scaled_residual": 8e-8,
                   "absolute_residual_floor": 1e-8, "solution_reused": False}
    validate_convergence(convergence, 1e-5)
    with pytest.raises(ValueError, match="expected stopping tolerance"):
        validate_convergence(convergence, 1e-6)
    convergence["solution_reused"] = True
    with pytest.raises(ValueError, match="reused"):
        validate_convergence(convergence, 1e-5)
