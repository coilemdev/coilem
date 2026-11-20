"""Spatial agreement needs genuine refinement and both component-wise steps."""

from copy import deepcopy

import pytest

from tools.rotor_native_spatial_report import CONTROL_DRIVER, compare_levels, require_same_problem


def levels():
    loss = {"hysteresis_W": 0.02, "lamination_eddy_W": 0.04, "total_W": 0.06}
    return [{"data_directory": str(k), "mesh": {"base_lc_mm": 1/(k+1), "rotor_cells": 10*(k+1),
             "rotor_max_cell_area_mm2": 1/(k+1), "total_elements": 100*(k+1), "material_template_sha256": str(k),
             "airgap_angular_divisions": 32*(k+1), "airgap_radial_layers": 4+k},
             "production_sampling": deepcopy(loss), "independent_loss_math": deepcopy(loss),
             "native_history_numerical_gates_pass": True} for k in range(3)]


def test_both_steps_must_pass_and_spatial_success_is_not_release_qualification():
    report = compare_levels(levels())
    assert report["native_spatial_gate"] == "PASS"
    assert report["status"] == "PILOT_NOT_QUALIFIED" and not report["full_matrix_started"]
    assert report["corrected_femm_spatial_gate"] == "NOT_RUN"


def test_same_total_cannot_hide_opposite_component_errors_on_either_step():
    for k in (0, 2):
        data = levels()
        data[k]["production_sampling"].update(hysteresis_W=0.024, lamination_eddy_W=0.036)
        report = compare_levels(data)
        assert report["native_spatial_gate"] == "FAIL"
        assert all(s["production_sampling"]["component_gates"]["total_W"] for s in report["spatial_convergence"])


def test_more_cells_without_smaller_rotor_cells_fails_the_mesh_design_gate():
    data = levels()
    data[1]["mesh"]["rotor_max_cell_area_mm2"] = 1.1
    report = compare_levels(data)
    assert not report["spatial_convergence"][0]["refinement_design_pass"]
    assert report["native_spatial_gate"] == "FAIL"


def test_unconverged_history_cannot_qualify_spatial_agreement():
    data = levels()
    data[1]["native_history_numerical_gates_pass"] = False
    assert compare_levels(data)["native_spatial_gate"] == "FAIL"


def test_identical_meshes_are_not_three_refinement_levels():
    data = levels()
    data[2]["mesh"]["material_template_sha256"] = data[1]["mesh"]["material_template_sha256"]
    with pytest.raises(ValueError, match="distinct"):
        compare_levels(data)


def problems():
    shared = {key: "identical" for key in ("fixture_sha256", "mechanical_angles_deg", "current_peak_A", "speed_rpm",
              "requested_gamma_deg", "native_gamma_deg", "excitation_frame", "expected_native_nonlinear_tolerance",
              "native_field_frame", "export_frame", "fresh_field_solves")}
    case = {"protocol": shared | {"positions": 384, "motion_model": "fixed-material", "identity": {
        "binary_sha256": "binary", "source_sha256": {"backend/physics.py": "physics", "tools/rotor_native_pilot.py": "collector"}}},
        "config": {"solve_params": {"mesh_density": "normal", "current": 20}}, "analysis": {"loss_material": "material"}}
    cases = [deepcopy(case) for _ in range(3)]
    for case in cases[1:]:
        case["protocol"]["identity"]["source_sha256"][CONTROL_DRIVER] = "recorded-driver"
    return cases


def test_only_mesh_control_driver_and_preset_may_differ_among_native_levels():
    cases = problems()
    cases[1]["config"]["solve_params"]["mesh_density"] = "fine"
    require_same_problem(cases)
    cases[1]["protocol"]["identity"]["source_sha256"]["backend/physics.py"] = "changed-physics"
    with pytest.raises(ValueError, match="sources differ"):
        require_same_problem(cases)


def test_different_operating_point_or_control_driver_cannot_be_a_refinement():
    cases = problems()
    cases[2]["config"]["solve_params"]["current"] = 10
    with pytest.raises(ValueError, match="operating points"):
        require_same_problem(cases)
    cases = problems()
    cases[2]["protocol"]["identity"]["source_sha256"][CONTROL_DRIVER] = "another-driver"
    with pytest.raises(ValueError, match="driver changed"):
        require_same_problem(cases)
