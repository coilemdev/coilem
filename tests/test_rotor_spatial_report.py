"""Spatial convergence cannot hide changed physics, missing grids or oracle failures."""

from copy import deepcopy

import pytest

from tools.femm_reference.rotor_airgap import BOUNDARY, add_periodic_airgap
from tools.rotor_spatial_report import band_arc_step, compare_cases, markdown_report


def cases():
    result = []
    for index, mesh in enumerate(("normal", "fine", "very_fine")):
        protocol = {"mesh": mesh, "positions": 384, "motion_model": "periodic-air-gap", "speed_rpm": 3000,
                    "current_peak_A": 20, "fixture_sha256": "same-fixture", "airgap_arc_step_deg": 0.25/(2**index),
                    "reference_identity": {"femm_binaries": "same-binaries", "source_manifest_sha256": "same-seal",
                                           "implementation_sha256": {"rotor_airgap.py": str(index), "runtime.py": "same"}}}
        parts = {"hysteresis_W": 0.012+index*0.0001, "lamination_eddy_W": 0.035+index*0.0001,
                 "total_W": 0.047+index*0.0002, "rotor_iron_mass_kg": 0.84}
        rows = [{"positions": count, "production_sampling": deepcopy(parts),
                 "reference": dict(parts, share_loss_above_1kHz=0.13),
                 "difference_W": {key: 0 for key in ("hysteresis_W", "lamination_eddy_W", "total_W")},
                 "reference_agreement_pass": True} for count in (96, 192, 384)]
        analysis = {"material": {"steel_id": "M350-50A"}, "stack_m": 0.05, "analysis_sources_sha256": {"kernel": "same"},
                    "raw_coordinate_frame": "rotor_material", "distinct_triangle_meshes": 1,
                    "results": rows, "angular_gate_pass": True, "angular_convergence": [],
                    "closure_gate": "PASS", "mesh_invariance_gate": "PASS", "independent_endpoint_max_component_difference_T": 1e-12,
                    "independent_endpoint_rms_component_difference_T": 1e-13, "timing": {}, "protocol_sha256": str(index)}
        metrics = {"mesh_geometry_sha256": str(index), "total_elements": 100*(index+1), "rotor_cells": 20*(index+1),
                   "rotor_max_cell_area_mm2": 1/(index+1), "airgap_target_mm": 0.125/(2**index),
                   "airgap_arc_step_deg": protocol["airgap_arc_step_deg"]}
        result.append({"protocol": protocol, "analysis": analysis, "mesh_metrics": metrics, "data_directory": mesh})
    return result


def test_two_mesh_steps_pass_without_qualifying_release_matrix():
    report = compare_cases(cases())
    assert report["spatial_gate_pass"] and report["one_case_numerical_gates_pass"]
    assert report["status"] == "PILOT_NOT_QUALIFIED" and not report["full_matrix_started"]
    assert len(report["spatial_convergence"]) == 2
    assert "0.047" in markdown_report(report)


@pytest.mark.parametrize("field,value", [("current_peak_A", 21), ("speed_rpm", 6000), ("positions", 192),
                                       ("fixture_sha256", "other")])
def test_changed_physics_or_angles_cannot_be_called_mesh_convergence(field, value):
    data = cases()
    data[1]["protocol"][field] = value
    with pytest.raises(ValueError, match="physics or sampling"):
        compare_cases(data)


@pytest.mark.parametrize("field,value", [("material", {"steel_id": "other"}), ("stack_m", 0.06),
                                       ("analysis_sources_sha256", {"kernel": "different"})])
def test_changed_loss_law_or_analyser_is_rejected(field, value):
    data = cases()
    data[1]["analysis"][field] = value
    with pytest.raises(ValueError, match="loss assumptions or analysis sources"):
        compare_cases(data)


def test_unrelated_reference_change_is_rejected_but_mesh_helper_change_is_allowed():
    data = cases()
    data[2]["protocol"]["reference_identity"]["implementation_sha256"]["runtime.py"] = "changed"
    with pytest.raises(ValueError, match="unrelated implementation"):
        compare_cases(data)


def test_one_bad_mesh_step_fails_the_combined_gate():
    data = cases()
    for row in data[2]["analysis"]["results"]:
        for method in ("production_sampling", "reference"):
            row[method]["lamination_eddy_W"] = 0.05
            row[method]["total_W"] = row[method]["hysteresis_W"]+0.05
    report = compare_cases(data)
    assert report["spatial_convergence"][0]["pass"] and not report["spatial_convergence"][1]["pass"]
    assert not report["spatial_gate_pass"]


def test_independent_oracle_failure_cannot_be_hidden_by_production_agreement():
    data = cases()
    row = data[2]["analysis"]["results"][-1]
    row["reference"]["lamination_eddy_W"] = 0.06
    row["reference"]["total_W"] = 0.0722
    report = compare_cases(data)
    step = report["spatial_convergence"][-1]
    assert step["production_sampling"]["pass"] and not step["reference"]["pass"] and not step["pass"]


@pytest.mark.parametrize("field,value", [("angular_gate_pass", False), ("closure_gate", "FAIL"),
                                       ("mesh_invariance_gate", "FAIL")])
def test_spatial_agreement_cannot_hide_failed_history_gates(field, value):
    data = cases()
    data[1]["analysis"][field] = value
    report = compare_cases(data)
    assert report["spatial_gate_pass"] and not report["one_case_numerical_gates_pass"]


def test_repeating_the_same_mesh_is_rejected():
    data = cases()
    data[2]["mesh_metrics"]["mesh_geometry_sha256"] = data[1]["mesh_metrics"]["mesh_geometry_sha256"]
    with pytest.raises(ValueError, match="three different meshes"):
        compare_cases(data)


def test_refining_only_element_counts_is_insufficient():
    data = cases()
    data[2]["mesh_metrics"]["airgap_arc_step_deg"] = data[1]["mesh_metrics"]["airgap_arc_step_deg"]
    assert not compare_cases(data)["spatial_gate_pass"]


def test_missing_finest_angular_row_is_rejected():
    data = cases()
    data[1]["analysis"]["results"].pop()
    with pytest.raises(ValueError, match="complete angular"):
        compare_cases(data)


def model_text(steps):
    return (f'<BeginBdry>\n<BdryName> = "ZeroA"\n<EndBdry>\n<BeginBdry>\n<BdryName> = "{BOUNDARY}"\n<EndBdry>\n'
            f'[NumArcSegments] = {len(steps)}\n'+"".join(f'0 1 90 {step} 2 0 0 1\n' for step in steps))


def test_saved_band_segmentation_is_read_from_the_actual_arc_records():
    assert band_arc_step(model_text([0.125]*8)) == 0.125
    with pytest.raises(ValueError, match="consistent step"):
        band_arc_step(model_text([0.125]*7+[0.25]))
    with pytest.raises(ValueError, match="consistent step"):
        band_arc_step(model_text([0.125]*7))


@pytest.mark.parametrize("step", [0, -0.1, float("nan"), float("inf"), 181])
def test_invalid_band_step_is_rejected_before_femm_mutation(step):
    with pytest.raises(ValueError, match="air-gap arc step"):
        add_periodic_airgap(None, None, None, None, arc_step_deg=step)
