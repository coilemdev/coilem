"""Check tutorial voltage conventions and reject incomplete reference evidence."""

import json
import math

import numpy as np
import pytest

from tools.compare_pyleecan_bemf import compare as compare_full_cycle
from tools.compare_pyleecan_tutorial import compare, half_cycle, metrics


def balanced_flux():
    theta = np.arange(100) * 2 * math.pi / 100
    return 0.2 * np.cos(theta[:, None] + [0, -2 * math.pi / 3, 2 * math.pi / 3])


def test_tutorial_anti_periodicity_and_voltage_derivative():
    flux = balanced_flux()
    assert half_cycle(flux[:50]) == pytest.approx(flux, abs=1e-15)
    result = metrics(half_cycle(flux[:50]))
    omega = 1000 * 2 * math.pi / 60 * 4
    stencil = math.sin(2 * math.pi / 100) / (2 * math.pi / 100)
    expected = 0.2 * omega * stencil * math.sqrt(3 / 2)
    assert result["line_rms_V"] == pytest.approx([expected] * 3)
    assert result["line_fundamental_rms_V"] == pytest.approx([expected] * 3)
    assert result["Ke_phase_peak_Vs_per_mech_rad"] == pytest.approx([0.8] * 3)
    assert metrics(flux, speed_rpm=2000)["line_rms_V"] == pytest.approx([2 * expected] * 3)
    voltage = np.asarray(result["phase_voltage_V"])
    theta = np.arange(100) * 2 * math.pi / 100
    assert voltage[:, 0] == pytest.approx(-0.2 * omega * stencil * np.sin(theta), abs=1e-12)


def test_dc_linkage_does_not_change_voltage():
    flux = balanced_flux()
    assert metrics(flux + [2, 3, 5])["line_rms_V"] == pytest.approx(metrics(flux)["line_rms_V"])


@pytest.mark.parametrize("flux", [np.zeros((49, 3)), np.zeros((50, 2)), np.full((50, 3), np.nan)])
def test_bad_half_cycles_rejected(flux):
    with pytest.raises(ValueError):
        half_cycle(flux)


def test_half_cycle_cannot_be_mislabeled_as_complete_actual_sweep(tmp_path):
    (tmp_path / "registration.json").write_text(json.dumps({"electrical_range_deg": 180}))
    with pytest.raises(ValueError, match="complete actual electrical cycle"):
        compare_full_cycle(tmp_path, tmp_path)


def test_incomplete_tutorial_comparison_is_rejected(tmp_path):
    paths = [tmp_path / name for name in ("tutorial", "femm", "native")]
    for path in paths:
        path.mkdir()
        (path / "registration.json").write_text("{}")
        (path / "waveform.json").write_text(json.dumps({"complete": False}) if path == paths[0] else "[]")
    with pytest.raises(ValueError, match="must be complete"):
        compare(*paths)
