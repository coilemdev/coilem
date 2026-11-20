"""Mesh agreement cannot bypass changed physics, missing convergence or component errors."""

from copy import deepcopy

import pytest

from tools.rotor_matched_spatial_report import compare_cases


def cases():
    out = []
    for index in range(3):
        protocol = {"schema": "coilem.matched_rotor_reference/v1", "positions": 384,
            "speed_rpm": 3000, "native_protocol_sha256": "same-native", "mesh": str(index),
            "reference_identity": {"implementation_sha256": {"collector": "old" if index == 0 else "new"}}}
        loss = {"hysteresis_W": 0.0166-index*0.00001, "lamination_eddy_W": 0.048-index*0.0001,
                "total_W": 0.0646-index*0.00011}
        report = {"sampling_plan": {"positions": 384}, "material": {"steel": "M350-50A"}, "stack_m": 0.05,
            "protocol_sha256": str(index), "results": [{"positions": 384, "reference": loss,
                "production_sampling": loss.copy(), "reference_agreement_pass": True}],
            "angular_gate_pass": True, "closure_gate": "PASS", "mesh_invariance_gate": "PASS",
            "independent_endpoint_max_component_difference_T": 1e-11, "angular_convergence": []}
        mesh = {"mesh_geometry_sha256": str(index), "total_elements": 100*(index+1), "rotor_cells": 10*(index+1),
            "rotor_max_cell_area_mm2": 2/(index+1), "airgap_target_mm": 0.1/(index+1), "airgap_arc_step_deg": 0.2/(index+1)}
        out.append({"directory": str(index), "protocol": protocol, "analysis": report, "mesh": mesh, "source_audit": {}})
    return out


BRIDGE = {"pass": True, "refined_implementation_sha256": {"collector": "new"}}


def test_two_refinement_steps_require_all_history_and_component_gates():
    report = compare_cases(cases(), BRIDGE)
    assert report["femm_spatial_gate"] == "PASS" and not report["full_matrix_started"]
    assert report["tolerances"]["successive_steps_required"] == 2 and not report["mass_renormalization"]


@pytest.mark.parametrize("failure", ["excitation", "material", "collector", "sampling"])
def test_changed_scientific_inputs_or_unbridged_collector_are_rejected(failure):
    data = cases()
    if failure == "excitation":
        data[-1]["protocol"]["native_protocol_sha256"] = "different"
    elif failure == "material":
        data[-1]["analysis"]["stack_m"] = 0.06
    elif failure == "collector":
        data[-1]["protocol"]["reference_identity"]["implementation_sha256"] = {"collector": "unreviewed"}
    else:
        data[-1]["analysis"]["sampling_plan"]["positions"] = 192
    with pytest.raises(ValueError):
        compare_cases(data, BRIDGE)


@pytest.mark.parametrize("failure", ["closure_gate", "angular_gate_pass", "mesh_invariance_gate", "component", "cell_size"])
def test_failed_numerical_gate_cannot_be_hidden_by_total_agreement(failure):
    data = deepcopy(cases())
    if failure == "component":
        data[-1]["analysis"]["results"][0]["reference"]["lamination_eddy_W"] = 0.1
    elif failure == "cell_size":
        data[-1]["mesh"]["rotor_max_cell_area_mm2"] = 5
    else:
        data[-1]["analysis"][failure] = False if failure == "angular_gate_pass" else "FAIL"
    assert compare_cases(data, BRIDGE)["femm_spatial_gate"] == "FAIL"
