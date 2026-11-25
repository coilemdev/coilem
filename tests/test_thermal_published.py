"""The thermal network against the published Prius measurements (ORNL/TM-2005/33)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.benchmark_suite.thermal_published import DATA, compare, fitted_contact, part_temperatures, published
from tests._private_evidence import requires_private_evidence

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks/thermal-v0.6/published-prius-results.json"


@pytest.fixture(scope="module")
def result():
    return compare()


def test_the_published_data_is_complete():
    data = published()
    assert len(data["points"]) == 4
    for point in data["points"]:
        assert set(point["thermocouples"]) == {"W1", "W2", "W3"}
        # Copper, core and mechanical loss add up to the measured total; the rotor estimate is the report's addition.
        parts = point["copper_W"] + point["stator_iron_W"] + point["mechanical_loss_W"]
        assert parts == pytest.approx(point["total_loss_W"], abs=1)
        for couple in point["thermocouples"].values():
            low, high = couple["source_model_C"]
            assert couple["casing_C"] < low < high
            assert couple["casing_C"] < couple["measured_C"] <= 170


def test_the_contact_resistance_reproduces_the_report_model_at_the_stator_face():
    data = published()
    parts = data["source_model_parts"]
    point = next(p for p in data["points"] if p["coolant_C"] == parts["coolant_C"])
    casing = point["thermocouples"][parts["thermocouple"]]["casing_C"]
    temperatures = part_temperatures(point, casing, contact_m2K_W=fitted_contact())
    assert temperatures["stator_outer"] == pytest.approx(parts["stator_iron_C"][0], abs=1e-6)
    # The tool's starter value is the same order: the fitted one is not an outlier chosen to make this work.
    assert 0.0005 < fitted_contact() < 0.002


def test_the_network_stays_close_to_the_measured_end_turns_and_on_the_warm_side(result):
    summary = result["summary"]
    assert summary["points"] == 12
    # The network has no oil cooling, so averaged over the three thermocouples it reads warm, by a bounded margin.
    assert 0 < summary["mean_difference_K"]["min"]
    assert summary["mean_difference_K"]["max"] < 10
    assert 1.0 < summary["mean_rise_ratio"]["min"] and summary["mean_rise_ratio"]["max"] < 1.15
    # Single thermocouples scatter more, as they do for the report's own model.
    assert -8 < summary["difference_K"]["min"] and summary["difference_K"]["max"] < 20


def test_the_excess_shrinks_as_the_oil_warms(result):
    # The network has no oil. Its excess should be largest where the oil is coldest against the winding.
    excess = [row["difference_K"] for row in result["thermocouple_means"]]
    assert excess == sorted(excess, reverse=True)


def test_the_dominant_inputs_are_the_ones_reported(result):
    shifts = {row["change"]: row["shift_K"] for row in result["sensitivity"]["rows"]}
    large = {change for change, shift in shifts.items() if abs(shift) > 15}
    assert large == {"Contact resistance halved", "Contact resistance doubled", "Tool's default steel conductivity, 20 W/mK"}


@requires_private_evidence("benchmarks/thermal-v0.6/published-prius-results.json")
def test_the_stored_results_match_a_fresh_run(result):
    stored = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert stored["data"] == DATA
    assert stored["fitted_contact_m2K_W"] == pytest.approx(result["fitted_contact_m2K_W"], rel=1e-3)
    for fresh, saved in zip(result["rows"], stored["rows"], strict=True):
        assert saved["network_C"] == pytest.approx(fresh["network_C"], abs=0.01)
        assert saved["network_range_C"] == pytest.approx(fresh["network_range_C"], abs=0.01)
    for fresh, saved in zip(result["sensitivity"]["rows"], stored["sensitivity"]["rows"], strict=True):
        assert saved["shift_K"] == pytest.approx(fresh["shift_K"], abs=0.01)
