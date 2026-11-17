"""Public rotor-loss accounting preserves legacy results and includes new watts once."""

import json
import math
from pathlib import Path

import pytest

from backend.loss_breakdown import operating_point_losses
from backend.models import IronLoss, MotorConfig, RotorIronLoss, SolveOptionsConfig

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def config():
    raw = json.loads(FIXTURE.read_text())
    raw["winding"]["wire"] = {"wire_bare_diameter_mm": 0.8, "strands_in_hand": 2}
    raw["solve_params"].update(rated_speed_rpm=3000, mechanical_loss_W=5)
    return MotorConfig.model_validate(raw)


def stator():
    return IronLoss(status="experimental", steel="M350-50A", electrical_frequency_Hz=200,
                    iron_loss_W=40, iron_hysteresis_loss_W=30, iron_eddy_loss_W=10, stator_iron_mass_kg=1,
                    validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)


def rotor(h=2., e=3., **changes):
    return RotorIronLoss(**({"status": "experimental", "steel": "M350-50A", "coefficient_source": "grade limits",
        "coefficients": {"kh": 0.02, "kc": 0.0001, "alpha": 2.1, "density_kg_m3": 7650}, "stacking_factor": 1,
        "speed_rpm": 3000, "mechanical_frequency_Hz": 50, "samples_per_mechanical_turn": 384,
        "rotor_iron_loss_W": h+e, "rotor_hysteresis_loss_W": h, "rotor_lamination_eddy_loss_W": e,
        "rotor_iron_mass_kg": 0.84, "endpoint_max_component_difference_T": 0,
        "endpoint_rms_component_difference_T": 0, "history_sha256": "0"*64} | changes))


def test_rotor_watts_reduce_shaft_power_once_without_changing_electromagnetic_power():
    cfg = config()
    _, legacy = operating_point_losses(cfg, 2., stator())
    _, combined = operating_point_losses(cfg, 2., stator(), rotor_iron_loss=rotor())
    assert combined.electromagnetic_power_W == pytest.approx(2*3000*2*math.pi/60)
    assert combined.input_power_W == legacy.input_power_W
    assert combined.total_loss_W == pytest.approx(legacy.total_loss_W+5)
    assert combined.shaft_power_W == pytest.approx(legacy.shaft_power_W-5)
    assert combined.shaft_torque_Nm == pytest.approx(2-50/(3000*2*math.pi/60))
    assert combined.iron_loss_W == 40 and combined.rotor_iron_loss_W == 5
    assert combined.rotor_hysteresis_loss_W == 2 and combined.rotor_lamination_eddy_loss_W == 3
    assert combined.loss_scope == "stator_and_rotor"
    assert combined.input_power_W == pytest.approx(combined.shaft_power_W+combined.total_loss_W)


def test_available_zero_rotor_loss_is_not_confused_with_missing_rotor_loss():
    _, value = operating_point_losses(config(), 2., stator(), rotor_iron_loss=rotor(0, 0))
    assert value.rotor_iron_loss_W == 0 and value.loss_scope == "stator_and_rotor"
    assert value.efficiency_pct is not None


def test_requested_unavailable_rotor_loss_is_explicit_and_withholds_efficiency():
    missing = RotorIronLoss(status="unavailable", steel="M350-50A", solved_region="sector", status_reason="Sector rotor loss is deferred.")
    _, value = operating_point_losses(config(), 2., stator(), rotor_iron_loss=missing)
    assert value.rotor_iron_loss_W is None and value.rotor_iron_loss_status == "unavailable"
    assert value.loss_scope == "stator_only" and value.efficiency_pct is None
    assert "requested rotor" in value.efficiency_status_reason


def test_legacy_call_preserves_stator_only_values_and_reason():
    _, value = operating_point_losses(config(), 2., stator())
    assert value.shaft_power_W == pytest.approx(2*3000*2*math.pi/60-45)
    assert value.rotor_iron_loss_W is None and value.rotor_iron_loss_status is None
    assert value.efficiency_status_reason == "Uses the experimental iron loss."


@pytest.mark.parametrize("change", [{"rotor_iron_loss_W": 6}, {"solved_region": "sector"},
                                    {"mechanical_frequency_Hz": 200}, {"speed_rpm": float("inf")},
                                    {"history_sha256": None}, {"endpoint_max_component_difference_T": 1e-3},
                                    {"validated_max_frequency_Hz": float("inf")}])
def test_inconsistent_or_nonfinite_available_records_are_rejected(change):
    with pytest.raises(ValueError):
        rotor(**change)


def test_new_option_is_opt_in_and_disabled_flag_does_not_change_old_config_dumps():
    assert not SolveOptionsConfig().rotor_iron_loss
    assert "rotor_iron_loss" not in SolveOptionsConfig().model_dump(mode="json")
    assert SolveOptionsConfig(rotor_iron_loss=False).model_dump() == SolveOptionsConfig().model_dump()
    assert SolveOptionsConfig(rotor_iron_loss=True).model_dump()["rotor_iron_loss"]
    with pytest.raises(ValueError, match="requires losses_efficiency"):
        SolveOptionsConfig(losses_efficiency=False, rotor_iron_loss=True)
