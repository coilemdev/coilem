"""Losses and efficiency at the operating point, and their report sections (#138, #113)."""

from __future__ import annotations

import csv
import io
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from backend.loss_breakdown import iron_loss_density_on_plot, operating_point_losses, phase_current_rms_a
from backend.models import IronLoss, MotorConfig
from backend.public_report import build_public_run_csv, build_public_run_pdf

pypdf = pytest.importorskip("pypdf")

RAW = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))


def _config(**solve_params) -> MotorConfig:
    raw = deepcopy(RAW)
    raw["winding"]["wire"] = {"wire_bare_diameter_mm": 0.8, "strands_in_hand": 2}
    raw["solve_params"].update(solve_params)
    return MotorConfig.model_validate(raw)


def _iron(watts: float = 40.0) -> IronLoss:
    return IronLoss(
        status="experimental", status_reason="Grade limits.", steel="M350-50A", electrical_frequency_Hz=100.0,
        iron_loss_W=watts, iron_hysteresis_loss_W=watts * 0.75, iron_eddy_loss_W=watts * 0.25,
        iron_teeth_loss_W=watts * 0.6, iron_yoke_loss_W=watts * 0.4, stator_iron_mass_kg=1.0,
        share_above_validated_frequency=0.01, share_above_validated_flux_density=0.3,
        validated_max_frequency_Hz=1000.0, validated_max_flux_density_T=1.5,
    )


def test_power_balance_keeps_the_solved_torque_and_drags_the_shaft():
    config = _config(current_amplitude_A=10.0, current_amplitude_convention="rms", rated_speed_rpm=3000, mechanical_loss_W=5.0)
    winding, loss = operating_point_losses(config, 2.0, _iron(40.0))
    omega = 3000 * 2 * math.pi / 60
    copper = 3 * 10.0**2 * winding.phase_resistance_ohm
    assert loss.electromagnetic_torque_Nm == 2.0
    assert loss.copper_loss_W == pytest.approx(copper)
    assert loss.copper_active_loss_W == pytest.approx(copper * winding.active_fraction)
    assert loss.shaft_power_W == pytest.approx(2.0 * omega - 45.0)
    assert loss.shaft_torque_Nm == pytest.approx(2.0 - 45.0 / omega)
    assert loss.input_power_W == pytest.approx(2.0 * omega + copper)
    assert loss.efficiency_pct == pytest.approx(100 * (2.0 * omega - 45.0) / (2.0 * omega + copper))
    assert loss.efficiency_status == "experimental"


@pytest.mark.parametrize(
    ("convention", "amplitude", "rms"),
    [("rms", 10.0, 10.0), ("peak", 10.0, 10.0 / math.sqrt(2)), ("plateau", 9.0, 9.0 * math.sqrt(2 / 3))],
)
def test_copper_loss_uses_the_rms_of_the_solved_current(convention, amplitude, rms):
    raw = deepcopy(RAW)
    raw["solve_params"].update(current_amplitude_A=amplitude, current_amplitude_convention=convention)
    if convention == "plateau":
        raw["solve_params"]["excitation_mode"] = "ideal_six_step_120"
    assert phase_current_rms_a(MotorConfig.model_validate(raw)) == pytest.approx(rms)


@pytest.mark.parametrize(
    ("torque", "speed", "iron", "reason"),
    [
        (2.0, 0, _iron(), "nonzero speed"),
        (-2.0, 3000, _iron(), "motoring"),
        (2.0, 3000, None, "needs the iron loss"),
        (0.01, 3000, _iron(400.0), "exceed the electromagnetic power"),
    ],
)
def test_efficiency_says_why_it_is_unavailable(torque, speed, iron, reason):
    _, loss = operating_point_losses(_config(rated_speed_rpm=speed), torque, iron)
    assert loss.efficiency_pct is None
    assert loss.efficiency_status == "unavailable"
    assert reason in loss.efficiency_status_reason


def test_density_spreads_onto_the_stored_mesh_only_when_it_matches():
    regions = ["stator_tooth", "airgap", "stator_yoke"]
    triangles = [[0, 1, 2]] * 3
    spread = iron_loss_density_on_plot({"element_index": [0, 2], "w_per_kg": [4.0, 9.0]}, triangles, regions)
    assert spread == ([4.0, None, 9.0], 9.0)
    assert iron_loss_density_on_plot({"element_index": [1], "w_per_kg": [4.0]}, triangles, regions) is None
    assert iron_loss_density_on_plot({"element_index": [5], "w_per_kg": [4.0]}, triangles, regions) is None
    assert iron_loss_density_on_plot(None, triangles, regions) is None
    parts = {"element_index": [0, 2], "w_per_kg": [4.0, 9.0], "eddy_w_per_kg": [1.0, 2.0]}
    assert iron_loss_density_on_plot(parts, triangles, regions, key="eddy_w_per_kg") == ([1.0, None, 2.0], 2.0)
    assert iron_loss_density_on_plot(parts, triangles, regions, key="hysteresis_w_per_kg") is None


def _stored_result() -> dict:
    config = _config(current_amplitude_A=10.0, current_amplitude_convention="rms", rated_speed_rpm=3000)
    winding, loss = operating_point_losses(config, 2.0, _iron(40.0))
    return {
        "summary": {
            "avg_torque_Nm": 2.0,
            "torque_ripple_pct": 2.5,
            "back_emf_fundamental_V": 18.75,
            "peak_flux_density_teeth_T": 1.62,
            "peak_flux_density_yoke_T": 1.34,
            "solve_time_s": 12.5,
            "winding_resistance": winding.model_dump(mode="json"),
            "loss_breakdown": loss.model_dump(mode="json"),
            "iron_loss": _iron(40.0).model_dump(mode="json"),
            "dq_flux_linkage": {
                "current_angle_convention": "q_axis_gamma_flux_weakening_positive", "transform": "amplitude_invariant_park",
                "i_d_A": -5.0, "i_q_A": 8.66, "lambda_d_Wb": 0.01102, "lambda_q_Wb": 0.000416, "torque_dq_Nm": 0.2926,
                "torque_agreement_pct": 100.3, "current_angle_deg": 30.0, "lambda_pm_Wb": 0.011257,
                "apparent_L_d_H": 4.72e-5, "apparent_L_q_H": 4.80e-5, "positions": 48,
            },
        },
        "field_line_plot": {
            "nodes_mm": [[-2, -1], [2, -1], [2, 1], [-2, 1], [0, 0]],
            "triangles": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
            "regions": ["stator_yoke", "slot_winding", "stator_tooth", "rotor_core"],
            "element_b_mag_t": [0.0, 1.0, 2.0, 3.0],
            "contour_levels": [],
        },
        "iron_loss_density": {"mesh": "field_line_plot", "element_w_per_kg": [3.0, None, 6.0, None], "max_w_per_kg": 6.0},
        "field_line_frames": [{"angle_deg": 0.0}],
        "torque_waveform": {"electrical_angle_deg": [0.0, 90.0], "torque_Nm": [2.0, 2.0]},
        "back_emf_waveform": {"electrical_angle_deg": [0.0, 90.0], "phase_a_V": [0, 1], "phase_b_V": [0, 1], "phase_c_V": [0, 1]},
        "solve_metadata": {"solver_name": "magneto2d", "mesh_element_count": 4, "rotor_positions": 2},
    }


def test_pdf_reports_winding_losses_breakdown_and_density():
    pdf = build_public_run_pdf(project=RAW, request={"resolved_config": RAW}, result=_stored_result(), material={}, manifest={})
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    for heading in (
        "d/q operating point", "Winding", "Losses and efficiency", "Loss breakdown",
        "Where the iron loss is", "Iron-loss density", "Iron loss (W/kg)", "Cream: not modelled",
    ):
        assert heading in text
    assert "0.0472 mH" in text and "100.3%" in text
    assert "Saliency Lq/Ld" in text and "1.02" in text and "Characteristic current" in text
    assert "2 x 0.8 mm" in text
    assert "Shaft torque" in text and "Efficiency" in text
    assert "Iron loss is experimental" in text
    assert "the solved torque is unchanged" in text


def test_csv_flattens_the_winding_and_loss_records_with_units():
    rows = list(csv.reader(io.StringIO(build_public_run_csv(
        project=RAW, request={"resolved_config": RAW}, result=_stored_result(), material={}, manifest={},
    ).decode("utf-8"))))
    by_key = {(row[0], row[1]): row for row in rows if len(row) >= 4}
    assert by_key[("winding", "phase_resistance_ohm")][2] == "Ohm"
    assert by_key[("losses", "copper_loss_W")][2] == "W"
    assert by_key[("losses", "shaft_torque_Nm")][2] == "N m"
    assert by_key[("losses", "efficiency_pct")][2] == "%"
    assert by_key[("iron_loss", "iron_teeth_loss_W")][2] == "W"
    assert ("summary", "loss_breakdown") not in by_key
    assert by_key[("dq", "lambda_d_Wb")][2] == "Wb"
    assert by_key[("dq", "apparent_L_q_H")][2] == "H"
    assert by_key[("dq", "current_angle_deg")][2] == "deg"
    assert by_key[("dq", "i_d_A")][2] == "A"
