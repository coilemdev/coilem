"""Shared performance contracts: conventions, consistency checks and inert inputs."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.machine_constants import compute_machine_constants
from backend.models import (
    DqFluxLinkage,
    DriveLimits,
    EfficiencyMap,
    FluxLinkageMap,
    FluxLinkageMapPoint,
    LossBreakdown,
    MotorConfig,
    SolveMetadata,
    SolveSummary,
    TorqueSpeedCurve,
    TorqueSpeedEnvelope,
    WindingConfig,
)
from backend.models.performance import SVPWM_LINEAR_MODULATION_LIMIT, dq_currents, dq_torque_Nm
from backend.public_routes import solve as public_solve

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_CONFIG = json.loads((REPO_ROOT / "tests" / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8"))
SCOPE_KEY = "0123456789abcdef0123456789abcdef"


def _loss_breakdown(**overrides) -> dict:
    values = {
        "phase_resistance_ohm": 0.05,
        "winding_temperature_C": 20.0,
        "copper_loss_W": 150.0,
        "copper_active_loss_W": 90.0,
        "copper_end_winding_loss_W": 60.0,
        "iron_loss_W": 40.0,
        "iron_hysteresis_loss_W": 30.0,
        "iron_eddy_loss_W": 10.0,
        "iron_loss_status": "experimental",
        "mechanical_loss_W": 10.0,
        "total_loss_W": 200.0,
        "shaft_power_W": 1800.0,
        "input_power_W": 2000.0,
        "efficiency_pct": 90.0,
    }
    values.update(overrides)
    return values


def _map_point(current: float, gamma: float, **overrides) -> dict:
    i_d, i_q = dq_currents(current, gamma)
    values = {
        "current_peak_A": current,
        "gamma_deg": gamma,
        "i_d_A": i_d,
        "i_q_A": i_q,
        "status": "ok",
        "avg_torque_Nm": 1.0,
        "lambda_d_Wb": 0.05,
        "lambda_q_Wb": 0.01,
    }
    values.update(overrides)
    return values


def _flux_map(points: list[dict], **overrides) -> dict:
    values = {
        "scope_key": SCOPE_KEY,
        "pole_pairs": 2,
        "current_peak_A": [10.0, 20.0],
        "gamma_deg": [0.0, 30.0],
        "reference_speed_rpm": 3000.0,
        "rotor_positions": 12,
        "mesh_density": "normal",
        "points": points,
    }
    values.update(overrides)
    return values


def test_current_angle_convention_matches_solve_params():
    assert dq_currents(10.0, 0.0) == pytest.approx((0.0, 10.0))
    # Positive gamma advances toward flux weakening: negative d-axis current.
    i_d, i_q = dq_currents(10.0, 30.0)
    assert i_d == pytest.approx(-5.0)
    assert i_q == pytest.approx(10.0 * math.cos(math.radians(30.0)))
    assert dq_currents(10.0, 90.0) == pytest.approx((-10.0, 0.0), abs=1e-12)
    description = MotorConfig.model_fields["solve_params"].annotation.__args__[0].model_fields["current_angle_deg"].description
    assert "q-axis" in description and "flux weakening" in description


def test_dq_torque_matches_machine_constants_for_a_non_salient_motor():
    # At id = 0 with Ld = Lq the d/q torque reduces to Kt = 1.5 · Ke: the identity
    # backend.machine_constants documents for the amplitude-invariant frame.
    pole_pairs, lambda_pm, current = 4, 0.02, 30.0
    torque = dq_torque_Nm(pole_pairs, lambda_pm, 0.0, 0.0, current)
    rpm = 3000.0
    emf_rms = lambda_pm * pole_pairs * 2 * math.pi * rpm / 60 / math.sqrt(2)
    kt, ke, lambda_back = compute_machine_constants(
        avg_torque_Nm=torque,
        current_amplitude_A=current,
        back_emf_fundamental_V_rms_LN=emf_rms,
        rated_speed_rpm=rpm,
        pole_count=2 * pole_pairs,
    )
    assert kt == pytest.approx(1.5 * ke)
    assert lambda_back == pytest.approx(lambda_pm)


def test_dq_flux_linkage_round_trips_with_its_conventions():
    i_d, i_q = dq_currents(20.0, 45.0)
    value = DqFluxLinkage(
        i_d_A=i_d,
        i_q_A=i_q,
        lambda_d_Wb=0.04,
        lambda_q_Wb=0.02,
        torque_dq_Nm=dq_torque_Nm(3, 0.04, 0.02, i_d, i_q),
        torque_agreement_pct=99.6,
    )
    dumped = value.model_dump(mode="json")
    assert dumped["current_angle_convention"] == "q_axis_gamma_flux_weakening_positive"
    assert dumped["transform"] == "amplitude_invariant_park"
    assert DqFluxLinkage.model_validate(dumped) == value


def test_loss_breakdown_accepts_a_balanced_record():
    record = LossBreakdown.model_validate(_loss_breakdown())
    assert record.input_power_W == pytest.approx(record.shaft_power_W + record.total_loss_W)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"copper_end_winding_loss_W": 50.0}, "copper_loss_W"),
        ({"iron_eddy_loss_W": 5.0}, "iron_loss_W"),
        ({"total_loss_W": 190.0, "input_power_W": 1990.0}, "total_loss_W"),
        ({"input_power_W": 2100.0}, "input_power_W"),
        ({"efficiency_pct": 101.0}, "less than or equal"),
    ],
)
def test_loss_breakdown_rejects_records_that_do_not_add_up(overrides, message):
    with pytest.raises(ValidationError, match=message):
        LossBreakdown.model_validate(_loss_breakdown(**overrides))


def test_missing_iron_loss_must_say_unavailable():
    no_iron = {"iron_loss_W": None, "iron_hysteresis_loss_W": None, "iron_eddy_loss_W": None, "total_loss_W": 160.0, "input_power_W": 1960.0}
    with pytest.raises(ValidationError, match="unavailable"):
        LossBreakdown.model_validate(_loss_breakdown(**no_iron))
    record = LossBreakdown.model_validate(_loss_breakdown(**no_iron, iron_loss_status="unavailable"))
    assert record.iron_loss_W is None


def test_flux_linkage_map_round_trips():
    points = [_map_point(current, gamma) for current in (10.0, 20.0) for gamma in (0.0, 30.0)]
    points[-1] = _map_point(20.0, 30.0, status="pending", avg_torque_Nm=None, lambda_d_Wb=None, lambda_q_Wb=None)
    value = FluxLinkageMap.model_validate(_flux_map(points))
    assert value.kind == "flux_linkage_map"
    assert FluxLinkageMap.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    ("points", "overrides", "message"),
    [
        ([_map_point(15.0, 0.0)], {}, "not on the grid"),
        ([_map_point(10.0, 0.0), _map_point(10.0, 0.0)], {}, "more than once"),
        ([], {"gamma_deg": [30.0, 0.0]}, "strictly increasing"),
    ],
)
def test_flux_linkage_map_rejects_points_off_the_grid(points, overrides, message):
    with pytest.raises(ValidationError, match=message):
        FluxLinkageMap.model_validate(_flux_map(points, **overrides))


def test_map_point_currents_must_follow_the_convention():
    with pytest.raises(ValidationError, match="iq = I"):
        FluxLinkageMapPoint.model_validate(_map_point(10.0, 30.0, i_d_A=5.0))


def test_map_point_status_needs_its_data():
    with pytest.raises(ValidationError, match="'ok' map point"):
        FluxLinkageMapPoint.model_validate(_map_point(10.0, 0.0, lambda_q_Wb=None))
    with pytest.raises(ValidationError, match="error message"):
        FluxLinkageMapPoint.model_validate(_map_point(10.0, 0.0, status="failed"))


def test_drive_limits_default_to_the_linear_svpwm_limit():
    limits = DriveLimits(dc_bus_V=400.0, peak_current_A=200.0, continuous_current_A=100.0, max_speed_rpm=12000.0)
    assert limits.modulation_index_max == pytest.approx(2.0 / math.sqrt(3.0))
    assert SVPWM_LINEAR_MODULATION_LIMIT == limits.modulation_index_max
    with pytest.raises(ValidationError, match="continuous_current_A"):
        DriveLimits(dc_bus_V=400.0, peak_current_A=100.0, continuous_current_A=200.0, max_speed_rpm=12000.0)


def test_torque_speed_envelope_round_trips_and_checks_sample_lengths():
    curve = {
        "limit": "peak",
        "speed_rpm": [0.0, 3000.0, 6000.0],
        "torque_Nm": [10.0, 10.0, 5.0],
        "power_W": [0.0, 3141.6, 3141.6],
        "i_d_A": [0.0, 0.0, -40.0],
        "i_q_A": [50.0, 50.0, 30.0],
        "phase_voltage_peak_V": [5.0, 230.0, 230.0],
        "region": ["mtpa", "mtpa", "field_weakening"],
        "base_speed_rpm": 3000.0,
        "max_speed_rpm": 6000.0,
        "peak_power_W": 3141.6,
    }
    envelope = TorqueSpeedEnvelope(
        map_scope_key=SCOPE_KEY,
        limits=DriveLimits(dc_bus_V=400.0, peak_current_A=50.0, max_speed_rpm=6000.0),
        phase_resistance_ohm=0.05,
        winding_temperature_C=120.0,
        curves=[TorqueSpeedCurve.model_validate(curve)],
        status="experimental",
    )
    assert TorqueSpeedEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    with pytest.raises(ValidationError, match="one value per speed_rpm"):
        TorqueSpeedCurve.model_validate({**curve, "region": ["mtpa", "mtpa"]})
    with pytest.raises(ValidationError, match="strictly increasing"):
        TorqueSpeedCurve.model_validate({**curve, "speed_rpm": [0.0, 6000.0, 3000.0]})


def test_efficiency_map_matrices_follow_the_axes():
    values = {
        "map_scope_key": SCOPE_KEY,
        "speed_rpm": [1000.0, 2000.0, 3000.0],
        "torque_Nm": [5.0, 10.0],
        "efficiency_pct": [[88.0, 91.0, 92.5], [85.0, 89.0, None]],
        "copper_loss_W": [[20.0, 20.0, 20.0], [80.0, 80.0, None]],
        "iron_loss_W": [[5.0, 11.0, 18.0], [6.0, 12.0, None]],
        "winding_temperature_C": 120.0,
    }
    efficiency = EfficiencyMap.model_validate(values)
    assert efficiency.status == "experimental"
    with pytest.raises(ValidationError, match="2 rows of 3 values"):
        EfficiencyMap.model_validate({**values, "iron_loss_W": [[5.0, 11.0], [6.0, 12.0]]})
    with pytest.raises(ValidationError, match="between 0 and 100"):
        EfficiencyMap.model_validate({**values, "efficiency_pct": [[88.0, 91.0, 120.0], [85.0, 89.0, None]]})


def test_existing_designs_and_results_load_unchanged():
    config = MotorConfig.model_validate(VALID_CONFIG)
    assert config.winding.wire is None
    assert config.solve_params.winding_temperature_C is None
    assert config.solve_params.mechanical_loss_W is None
    assert "wire" in WindingConfig.model_fields
    summary_fields = SolveSummary.model_fields
    assert summary_fields["dq_flux_linkage"].default is None
    assert summary_fields["loss_breakdown"].default is None
    for name in ("magnet_temperature_C", "magnet_remanence_T", "magnet_intrinsic_coercivity_kA_m", "winding_temperature_C"):
        assert SolveMetadata.model_fields[name].default is None


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("winding", "wire", {"wire_bare_diameter_mm": 0.8}),
        ("solve_params", "winding_temperature_C", 120.0),
        ("solve_params", "mechanical_loss_W", 15.0),
    ],
)
def test_performance_inputs_are_refused_until_a_solve_uses_them(section, field, value):
    raw = deepcopy(VALID_CONFIG)
    raw[section][field] = value
    with pytest.raises(ValidationError, match="not supported by this preview yet"):
        MotorConfig.model_validate(raw)


def test_loss_breakdown_stays_out_of_public_results_until_losses_ship():
    assert "loss_breakdown" in public_solve._EXCLUDED_SUMMARY_FIELDS
    assert "efficiency_pct" in public_solve._EXCLUDED_SUMMARY_FIELDS
