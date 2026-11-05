"""Source-axis commutation, legacy preservation and actual sweep conventions."""
import cmath
import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from backend.excitation import resolve_public_current_profile
from backend.experimental.femm_outrunner import source
from backend.experimental.outrunner_excitation import currents_at, sweep_cases
from backend.experimental.outrunner_project import OutrunnerAnalysis, OutrunnerProject
from backend.experimental.outrunner_runtime import _curves


def settings(mode, **overrides):
    return OutrunnerAnalysis(excitation_mode=mode, current_amplitude_convention="plateau" if mode == "ideal_six_step_120" else "peak", **overrides)


def test_legacy_reference_inputs_and_cases_remain_fixed():
    legacy = OutrunnerAnalysis.model_validate({"loaded_currents_A": [0., 4., -4.]})
    assert legacy.excitation_mode == "fixed_phase_currents"
    cases = sweep_cases(legacy, "both")
    assert len(cases) == 98
    assert cases[1].angle_ccw_deg == pytest.approx((360/7)/48)
    assert all(case.currents_A == (0, 4, -4) for case in cases[:49])
    assert all(case.currents_A == (0, 0, 0) for case in cases[49:])
    assert currents_at(legacy, 40) == (0, 4, -4)


def test_source_winding_axes_are_derived_from_geometry_not_field_fitting():
    for phase, expected in zip("ABC", [-90, 150, 30], strict=True):
        phasor = sum(label["signed_turns"]*cmath.exp(7j*math.radians(15+30*(round((label["theta_deg"]-15)/30) % 12)))
                     for label in source()["labels"] if label["circuit"] == phase)
        assert math.degrees(cmath.phase(phasor)) == pytest.approx(expected)


def test_clockwise_six_step_sectors_plateau_advance_and_boundary():
    configuration = settings("ideal_six_step_120")
    expected = [(0, 4, -4), (-4, 4, 0), (-4, 0, 4), (0, -4, 4), (4, -4, 0), (4, 0, -4)]
    for index, currents in enumerate(expected):
        assert currents_at(configuration, -index*60/7) == currents
    assert currents_at(configuration, -(30-1e-9)/7) == expected[0]
    assert currents_at(configuration, -30/7) == expected[1]
    assert currents_at(configuration, -(30+1e-9)/7) == expected[1]
    advanced = settings("ideal_six_step_120", commutation_advance_deg=10)
    assert currents_at(advanced, -20/7) == expected[1]
    assert currents_at(configuration, -360/7) == expected[0]


def test_sinusoidal_peak_rms_zero_current_and_current_angle():
    sine = settings("sinusoidal")
    assert currents_at(sine, 0) == pytest.approx([0, 2*math.sqrt(3), -2*math.sqrt(3)])
    rms = sine.model_copy(update={"current_amplitude_convention": "rms"})
    assert currents_at(rms, -15/7) == pytest.approx(np.asarray(currents_at(sine, -15/7))*math.sqrt(2))
    for angle in range(0, 360, 11):
        assert sum(currents_at(sine, -angle/7)) == pytest.approx(0, abs=1e-12)
    assert currents_at(sine.model_copy(update={"current_amplitude_A": 0}), -15/7) == (0, 0, 0)
    assert currents_at(sine.model_copy(update={"current_angle_deg": 30}), 0) == pytest.approx(currents_at(sine, -30/7))
    assert settings("sinusoidal", current_amplitude_A=20).current_amplitude_A == 20  # peak is allowed
    with pytest.raises(ValidationError):
        OutrunnerAnalysis(excitation_mode="sinusoidal", current_amplitude_A=20, current_amplitude_convention="rms")


@pytest.mark.parametrize("mode", ["sinusoidal", "ideal_six_step_120"])
def test_actual_cases_currents_curve_signs_noload_and_emf_follow_clockwise_motion(mode):
    configuration = settings(mode)
    cases = sweep_cases(configuration, "both")
    assert all(case.angle_ccw_deg <= 0 for case in cases)
    assert cases[1].angle_ccw_deg < cases[0].angle_ccw_deg
    rows = []
    for case in cases:
        theta_ccw = math.radians(7*case.angle_ccw_deg)
        # Analytic source-aligned flux and its virtual-work torque.
        flux = np.cos(theta_ccw+np.array([0, 2*math.pi/3, -2*math.pi/3]))*.001
        derivative = -7*np.sin(theta_ccw+np.array([0, 2*math.pi/3, -2*math.pi/3]))*.001
        torque_ccw = float(np.dot(case.currents_A, derivative))
        if case.family == "loaded":
            assert torque_ccw < 0
        else:
            assert case.currents_A == (0, 0, 0)
        rows.append({"case": case.to_dict(), "outer_rotor_torque_Nm": torque_ccw, "phase_linkage_Wb": flux.tolist()})
    curves = _curves(rows, OutrunnerProject(analysis=configuration))
    assert curves["loaded"]["positive_direction"] == "clockwise"
    assert curves["loaded"]["angles_electrical_deg"] == pytest.approx(np.linspace(0, 360, 49))
    assert min(curves["loaded"]["torque_Nm"]) > 0
    assert len(curves["noload"]["bemf_phase_V"]) == 48
    # e_A=-omega_CW*d(lambda_A)/d(theta_CW) is positive at 90° CW.
    assert curves["noload"]["bemf_phase_V"][12][0] > 0


def test_explicit_profile_preserves_existing_inrunner_golden_vectors():
    root = Path(__file__).parent/"fixtures"
    six = json.loads((root/"bldc_six_step_golden_vectors.json").read_text())
    for vector in six["vectors"]:
        sample = resolve_public_current_profile("ideal_six_step_120", six["plateau_current_A"], "plateau",
                                                vector["rotor_electrical_angle_deg"], advance_deg=vector["commutation_advance_deg"])
        assert sample.phase_current_a == pytest.approx(vector["phase_current_A"])
    for vector in json.loads((root/"public_sine_phase_current_vectors.json").read_text())["vectors"]:
        sample = resolve_public_current_profile("sinusoidal", 1, "peak", vector["rotor_electrical_angle_deg"],
                                                axis_offset_deg=vector["phase_axis_offset_elec_deg"], current_angle_deg=vector["current_angle_deg"])
        assert sample.phase_current_a == pytest.approx(vector["phase_current"], abs=1e-12)
