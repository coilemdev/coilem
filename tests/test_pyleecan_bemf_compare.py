"""Analytical voltage conventions and incomplete reference rejection."""

import json
import math

import numpy as np
import pytest

from tools.compare_pyleecan_bemf import compare, waveform_metrics


def test_balanced_flux_cycle_has_correct_line_voltage_and_speed_scaling():
    n = 48
    theta = np.arange(n) * 2 * np.pi / n
    flux = 0.2 * np.cos(theta[:, None] + np.array([0, -2 * np.pi / 3, 2 * np.pi / 3]))
    m = waveform_metrics(flux, speed_rpm=3000, pole_pairs=4)
    central_difference_factor = math.sin(2 * math.pi / n) / (2 * math.pi / n)
    expected = 0.2 * (3000 * 2 * math.pi / 60) * 4 * math.sqrt(3 / 2) * central_difference_factor
    assert m["LL_AB_RMS_V"] == pytest.approx(expected)
    assert m["LL_AB_fundamental_RMS_V"] == pytest.approx(expected)
    assert m["Ke_phase_peak_V_per_mech_rad_s_from_flux"] == pytest.approx([0.8] * 3)
    assert waveform_metrics(flux, speed_rpm=6000)["LL_AB_RMS_V"] == pytest.approx(2 * expected)
    assert waveform_metrics(2 * flux)["LL_AB_RMS_V"] == pytest.approx(2 * expected)


def test_flux_dc_offset_does_not_change_bemf():
    theta = np.arange(48) * 2 * np.pi / 48
    flux = np.cos(theta[:, None] + np.array([0, -2 * np.pi / 3, 2 * np.pi / 3]))
    assert waveform_metrics(flux + np.array([2, 3, 5]))["LL_AB_RMS_V"] == pytest.approx(waveform_metrics(flux)["LL_AB_RMS_V"])


@pytest.mark.parametrize("flux", [np.zeros((48, 2)), np.zeros((6, 3)), np.full((48, 3), np.nan)])
def test_invalid_flux_cycles_rejected(flux):
    with pytest.raises(ValueError):
        waveform_metrics(flux)


def test_partial_reference_is_not_a_completed_comparison(tmp_path):
    f, m = tmp_path / "femm", tmp_path / "native"
    f.mkdir()
    m.mkdir()
    (f / "registration.json").write_text(json.dumps({"points": 48}))
    for path, data in ((m / "registration.json", {}), (f / "waveform.json", []), (m / "waveform.json", [])):
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="complete"):
        compare(f, m)
