"""DC bench gate: calibration isolation, held-out failures and claim boundary."""

import copy
import hashlib
import json

import pytest

from backend.benchmark_suite.thermal_bench import check_bench, registration, winding_temperature


def fixture():
    spec = copy.deepcopy(registration())
    spec["owner_registration"] = dict(motor_id="synthetic", geometry_sha256="a"*64, cooling_id="test still air",
        thermal_inputs_sha256="b"*64, prediction_identity="c"*64)
    points = []
    for registered, rise in zip(spec["points"], (20, 30, 40, 50)):
        # True multiplier=2, same lead correction at both temperatures.
        hot = 1 * (1 + spec["alpha20_per_K"] * rise)
        points.append(dict(id=registered["id"], role=registered["role"], ambient_C=20,
            resistance=dict(cold_C=20, cold_ohm=1.1, hot_ohm=hot+0.1, cold_lead_ohm=0.1, hot_lead_ohm=0.1),
            predicted_active_C=20 + rise/2, predicted_end_C=20 + rise/2, active_fraction=0.75, measured_copper_W=registered["target_heat_W"],
            model_copper_W=registered["target_heat_W"], winding_uncertainty_K=0.2, steady_drift_K_per_min=0.01))
    bundle = dict(**spec["owner_registration"],
                  registration_sha256=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(",", ":")).encode()).hexdigest(),
                  evidence_kind="synthetic", raw_data_sha256="d"*64, points=points)
    return spec, bundle


def test_missing_owner_or_data_stays_not_compared():
    assert check_bench()["status"] == "NOT_COMPARED"
    spec = registration()
    bundle = dict(registration_sha256=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(",", ":")).encode()).hexdigest())
    assert check_bench(bundle)["status"] == "NOT_COMPARED"


def test_resistance_method_refers_alpha_to_20_not_cold_temperature():
    alpha = 0.00393
    assert winding_temperature(30, 1+alpha*10, 1+alpha*80, alpha) == pytest.approx(100)
    with pytest.raises(ValueError):
        winding_temperature(20, -1, 1, alpha)


def test_fit_uses_only_calibration_and_never_qualifies_synthetic_data():
    spec, bundle = fixture()
    verdict = check_bench(bundle, spec=spec)
    assert verdict["status"] == "PASS"
    assert verdict["calibration_multiplier"] == pytest.approx(2)
    assert "Fitted thermal-resistance multiplier: 2." in verdict["status_reason"]
    assert "cannot identify several uncertain heat paths" in verdict["status_reason"]
    assert verdict["output_status"] == "experimental"
    bundle["points"][-1]["predicted_active_C"] += 20/0.75
    failed = check_bench(bundle, spec=spec)
    assert failed["status"] == "FAIL"
    assert failed["calibration_multiplier"] == verdict["calibration_multiplier"]
    assert len(failed["metrics"]) == 3


@pytest.mark.parametrize("error,status", [(2, "PASS"), (4, "YELLOW"), (8, "FAIL")])
def test_uncertainty_aware_frozen_bands(error, status):
    spec, bundle = fixture()
    bundle["points"][-1]["predicted_active_C"] += error/2/0.75
    assert check_bench(bundle, spec=spec)["status"] == status


def test_physical_pass_is_narrowly_qualified_and_carries_exact_identity():
    spec, bundle = fixture()
    bundle["evidence_kind"] = "physical_measurement"  # Synthetic test of branch, not stored measurement evidence.
    verdict = check_bench(bundle, spec=spec)
    assert verdict["output_status"] == "qualified"
    assert verdict["qualification_identity"] == spec["owner_registration"]
    assert "magnets" in verdict["exclusions"]
    bundle["cooling_id"] = "another cooling setup"
    with pytest.raises(ValueError, match="cooling_id"):
        check_bench(bundle, spec=spec)


def test_roles_heat_steady_state_and_identity_are_enforced():
    spec, bundle = fixture()
    for key, value in (("role", "calibration"), ("model_copper_W", 0), ("steady_drift_K_per_min", 1), ("winding_uncertainty_K", float("nan"))):
        changed = copy.deepcopy(bundle)
        changed["points"][-1][key] = value
        with pytest.raises(ValueError):
            check_bench(changed, spec=spec)



def test_terminal_resistance_compares_both_active_and_end_copper():
    from backend.benchmark_suite.thermal_bench import _measurement
    spec, bundle = fixture()
    point = bundle["points"][0]
    point.update(predicted_active_C=40, predicted_end_C=80, active_fraction=0.75)
    assert _measurement(point, spec)["predicted_rise_K"] == 30
    point["active_fraction"] = 1.1
    with pytest.raises(ValueError, match="active fraction"):
        _measurement(point, spec)
