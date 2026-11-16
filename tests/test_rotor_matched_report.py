"""Cross-solver component gates cannot hide mismatched inputs or reference errors."""

import json
from copy import deepcopy

import pytest

from tools.rotor_matched_report import compare_results, reference_source_audit
from tools.rotor_native_pilot import sha


def test_frozen_reference_source_must_match_its_original_identity(tmp_path):
    package = tmp_path / "tools/femm_reference"
    package.mkdir(parents=True)
    collector = package / "collector.py"
    collector.write_text("# original collector snapshot\n")
    manifest = package / "source-manifest.json"
    manifest.write_text(json.dumps({"files": {}}))
    protocol = {"schema": "coilem.matched_rotor_reference/v1", "reference_identity": {
        "source_manifest_sha256": sha(manifest), "implementation_sha256": {"collector.py": sha(collector)}}}
    audit = reference_source_audit(protocol, tmp_path)
    assert audit["explicit_frozen_source"] and audit["implementation_sha256"] == {"collector.py": sha(collector)}
    collector.write_text("# different collector cannot relabel the original data\n")
    with pytest.raises(ValueError, match="implementation changed"):
        reference_source_audit(protocol, tmp_path)


def test_frozen_manifest_identity_cannot_be_replaced(tmp_path):
    package = tmp_path / "tools/femm_reference"
    package.mkdir(parents=True)
    (package / "source-manifest.json").write_text(json.dumps({"files": {}}))
    protocol = {"schema": "coilem.matched_rotor_reference/v1", "reference_identity": {
        "source_manifest_sha256": "another manifest", "implementation_sha256": {}}}
    with pytest.raises(ValueError, match="manifest changed"):
        reference_source_audit(protocol, tmp_path)


def comparison():
    coefficients = {"kh": 0.02, "kc": 0.0003, "alpha": 2.1, "density_kg_m3": 7650}
    loss = {"hysteresis_W": 0.02, "lamination_eddy_W": 0.04, "total_W": 0.06}
    material = {"coefficients": coefficients, "stacking_factor": 1}
    ref = {"material": material, "sampling_plan": {"positions": 96},
           "results": [{"positions": 96, "reference": loss | {"mass_kg": 0.84, "share_loss_above_1kHz": 0.1},
                        "reference_agreement_pass": True}], "closure_gate": "PASS", "mesh_invariance_gate": "PASS",
           "angular_gate_pass": False, "stack_m": 0.05, "independent_endpoint_max_component_difference_T": 1e-12,
           "angular_convergence": [], "timing": {}, "protocol_sha256": "femm"}
    protocol = {"schema": "coilem.matched_rotor_reference/v1", "native_protocol_sha256": "native", "positions": 384,
                "gamma_deg": 180, "speed_rpm": 3000, "current_peak_A": 20}
    native = {"protocol_sha256": "native", "native_gamma_deg": 180, "speed_rpm": 3000, "current_peak_A": 20,
              "loss_material": material, "native_history_numerical_gates_pass": True,
              "results": [{"positions": 96, "production_sampling": loss | {"rotor_iron_mass_kg": 0.84}, "share_loss_above_1kHz": 0.1}]}
    return deepcopy(ref), deepcopy(protocol), deepcopy(native)


def test_matching_coarse_fields_pass_only_a_preliminary_gate():
    report = compare_results(*comparison())
    assert report["cross_solver_loss_gate"] == "PASS"
    assert report["progressive_subset"] and not report["femm_angular_gate_complete"]
    assert report["status"] == "PILOT_NOT_QUALIFIED" and not report["full_matrix_started"]


def test_agreeing_totals_cannot_hide_a_failed_hysteresis_component():
    ref, protocol, native = comparison()
    native["results"][0]["production_sampling"].update(hysteresis_W=0.023, lamination_eddy_W=0.037)
    report = compare_results(ref, protocol, native)
    assert report["component_gates"]["total_W"] and report["component_gates"]["lamination_eddy_W"]
    assert not report["component_gates"]["hysteresis_W"] and report["cross_solver_loss_gate"] == "FAIL"


@pytest.mark.parametrize("change", ["legacy", "gamma", "coefficients"])
def test_mismatched_physics_or_legacy_reference_is_rejected(change):
    ref, protocol, native = comparison()
    if change == "legacy":
        protocol["schema"] = "coilem.rotor_loss_pilot/v2"
    elif change == "gamma":
        native["native_gamma_deg"] = 0
    else:
        native["loss_material"]["coefficients"]["kc"] *= 2
    with pytest.raises(ValueError):
        compare_results(ref, protocol, native)


def test_failed_reference_math_or_closure_makes_agreement_ineligible():
    for failed_gate in ("math", "closure"):
        ref, protocol, native = comparison()
        if failed_gate == "math":
            ref["results"][0]["reference_agreement_pass"] = False
        else:
            ref["closure_gate"] = "FAIL"
        assert compare_results(ref, protocol, native)["cross_solver_loss_gate"] == "NOT_ELIGIBLE"


def test_full_grid_requires_reference_angular_convergence():
    ref, protocol, native = comparison()
    ref["sampling_plan"]["positions"] = 384
    ref["results"][0]["positions"] = native["results"][0]["positions"] = 384
    assert compare_results(ref, protocol, native)["cross_solver_loss_gate"] == "NOT_ELIGIBLE"
    ref["angular_gate_pass"] = True
    assert compare_results(ref, protocol, native)["cross_solver_loss_gate"] == "PASS"


def test_declared_absolute_tolerance_handles_zero_reference_without_division():
    ref, protocol, native = comparison()
    ref["results"][0]["reference"]["hysteresis_W"] = 0
    native["results"][0]["production_sampling"]["hysteresis_W"] = 0.0005
    report = compare_results(ref, protocol, native)
    assert report["relative_difference_of_femm"]["hysteresis_W"] is None
    assert report["component_gates"]["hysteresis_W"]
