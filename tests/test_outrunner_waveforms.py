"""Angle, derivative, and provenance invariants for the experimental sweep."""
import math

import numpy as np
import pytest

from backend.experimental.outrunner_sweep import PERIOD_DEG, SweepCase, bemf, fundamental, initial_cases, periodic_derivative


def test_bemf_uses_mechanical_speed_pole_pairs_and_induced_voltage_sign():
    angle_electrical = np.arange(48)*2*math.pi/48
    phase = np.array([0, -2*math.pi/3, 2*math.pi/3])
    linkage = 0.001*np.sin(angle_electrical[:, None]+phase)
    expected = -1000*2*math.pi/60*7*0.001*np.cos(angle_electrical[:, None]+phase)
    np.testing.assert_allclose(bemf(linkage), expected, atol=8e-15)
    np.testing.assert_allclose(bemf(linkage, 2000), 2*expected, atol=2e-14)
    np.testing.assert_allclose(bemf(linkage+0.123), expected, atol=5e-13)
    np.testing.assert_allclose(np.asarray(fundamental(expected)["peak"]), 1000*2*math.pi/60*7*0.001, atol=1e-15)
    line_to_line = expected-np.roll(expected, -1, axis=1)
    np.testing.assert_allclose(np.asarray(fundamental(line_to_line)["peak"]), math.sqrt(3)*np.asarray(fundamental(expected)["peak"]))


def test_finite_difference_derivative_converges_without_filtering():
    errors = []
    for count in (24, 48):
        theta = np.arange(count)*2*math.pi/count
        expected = np.cos(theta)
        approximate = periodic_derivative(np.sin(theta), 2*math.pi, "central4")
        errors.append(np.linalg.norm(expected-approximate))
    assert errors[1] < errors[0]/10


def test_sweep_keeps_independent_closure_and_negative_current_requests():
    cases = initial_cases(48)
    assert len({x.id for x in cases}) == len(cases)
    for family in ("loaded", "noload"):
        selected = [x for x in cases if x.family == family]
        assert len(selected) == 49
        assert selected[0].angle_ccw_deg == 0
        assert selected[-1].angle_ccw_deg == pytest.approx(PERIOD_DEG, abs=1e-13)
        assert selected[0].id != selected[-1].id
    assert any(x.currents_A == (0, -6, 6) for x in cases)
    assert cases[-1].angle_ccw_deg == 360
    assert cases[-1].currents_A == (0, 0, 0)


@pytest.mark.parametrize("changes", [{"angle_ccw_deg": math.nan}, {"currents_A": (1, 2, 3)}, {"id": "../escape"}, {"reference_model": "guessed"}])
def test_invalid_case_is_rejected(changes):
    with pytest.raises(ValueError):
        SweepCase(**{**dict(id="valid", angle_ccw_deg=0, currents_A=(0, 0, 0), family="test"), **changes})
