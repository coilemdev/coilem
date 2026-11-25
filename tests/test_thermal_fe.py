"""The independent finite-element conduction reference, and the network's agreement with it."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from backend.benchmark_suite.thermal_conduction import cross_section_prediction, registration, request_for_case
from backend.benchmark_suite.thermal_fe import annulus_mean_rise, group_means, solve_conduction, stator_conduction_reference
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.models import MotorConfig
from backend.public_policy import parse_public_solve_request


def _ring(inner, outer, radial, around):
    radii = np.linspace(inner, outer, radial + 1)
    angles = np.linspace(0, 2 * math.pi, around, endpoint=False)
    nodes = np.array([[r * math.cos(t), r * math.sin(t)] for r in radii for t in angles])
    triangles = []
    for i in range(radial):
        for j in range(around):
            a, b = i * around + j, i * around + (j + 1) % around
            c, d = a + around, b + around
            triangles += [[a, c, d], [a, d, b]]
    return nodes, np.array(triangles)


@pytest.mark.parametrize("fixed", ["outer", "inner"])
def test_solver_reproduces_the_uniformly_heated_ring(fixed):
    """Closed form: one face fixed, the other insulated. The inner-fixed ring is the outer-rotor stator's case."""
    inner, outer, k, q = 0.03, 0.05, 20.0, 2.0e5
    errors = []
    for radial, around in ((8, 96), (16, 192)):
        nodes, triangles = _ring(inner, outer, radial, around)
        face = np.flatnonzero(np.abs(np.hypot(nodes[:, 0], nodes[:, 1]) - (outer if fixed == "outer" else inner)) < 1e-9)
        temperature, _ = solve_conduction(nodes, triangles, np.full(len(triangles), k), np.full(len(triangles), q),
                                          dict.fromkeys(face.tolist(), 20.0))
        mean = group_means(nodes, triangles, temperature, ["ring"] * len(triangles))["ring"]["mean_temperature_C"] - 20
        errors.append(abs(mean - annulus_mean_rise(inner, outer, k, q, fixed=fixed)) / annulus_mean_rise(inner, outer, k, q, fixed=fixed))
    assert errors[1] < 0.002
    assert errors[1] < errors[0] / 3, "Halving the element size cuts the error about four times"


def test_solver_refuses_a_problem_without_a_fixed_temperature():
    nodes, triangles = _ring(0.03, 0.05, 2, 12)
    with pytest.raises(ValueError, match="fixed temperature"):
        solve_conduction(nodes, triangles, np.ones(len(triangles)), np.ones(len(triangles)), {})


def test_the_layout_aware_prediction_is_the_registered_one_for_inner_rotors():
    spec = registration()
    for case in spec["cases"]:
        raw = json.loads(Path(case["fixture"]).read_text(encoding="utf-8"))
        config = MotorConfig.model_validate(raw.get("config", raw))
        prediction, _ = cross_section_prediction(config, case["heat_W"], spec["conductivity_W_mK"], spec["boundary_C"])
        registered = request_for_case(case)["prediction_C"]
        assert prediction == pytest.approx(registered, rel=1e-12, abs=1e-12)


def _compare(config, heat, *, outer):
    spec = registration()
    coarse = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"mesh_density": "coarse"})})
    reference = stator_conduction_reference(
        run_gmsh_mesh_preview(coarse, rotor_angle_deg=0.0), fixed_radius_mm=(config.stator.ID_mm if outer else config.stator.OD_mm) / 2,
        boundary_C=spec["boundary_C"], conductivity_W_mK=spec["conductivity_W_mK"], heat_W=heat, stack_length_m=config.stator.stack_length_mm * 1e-3)
    prediction, areas = cross_section_prediction(config, heat, spec["conductivity_W_mK"], spec["boundary_C"])
    rows = {row["node"]: row for row in reference["regions"]}
    for node, area in areas.items():
        # A coarse mesh draws the hub circle with few chords, so its areas are only close.
        assert rows[node]["area_m2"] == pytest.approx(area, rel=0.01), "The mesh and the geometry describe the same regions"
    return {node: (prediction[node] - rows[node]["mean_temperature_C"]) / (rows[node]["mean_temperature_C"] - spec["boundary_C"]) for node in areas}


def test_network_tracks_the_resolved_outer_rotor_cross_section():
    """Bundled outrunner example, combined heat. The limits are the measured differences with headroom, not targets."""
    example = Path("frontend/src/public/examples/spm_outrunner_14p12s.coilem")
    config, _, _ = parse_public_solve_request(json.loads(example.read_text(encoding="utf-8")))
    difference = _compare(config, {"winding": 10, "teeth": 3, "yoke": 7}, outer=True)
    assert -0.15 < difference["winding"] < 0.05
    assert -0.15 < difference["teeth"] < 0.05
    assert abs(difference["yoke"]) < 0.12


def test_network_tracks_the_resolved_inner_rotor_cross_section():
    """Registered concentrated stator, combined heat. Its wide slots are where the network reads hottest."""
    case = next(case for case in registration()["cases"] if case["id"] == "spm_concentrated_combined")
    raw = json.loads(Path(case["fixture"]).read_text(encoding="utf-8"))
    difference = _compare(MotorConfig.model_validate(raw.get("config", raw)), case["heat_W"], outer=False)
    assert 0.15 < difference["winding"] < 0.45, "The network ignores the slot-bottom path, so it reads high here"
    assert -0.20 < difference["teeth"] < 0.0
    assert abs(difference["yoke"]) < 0.08
