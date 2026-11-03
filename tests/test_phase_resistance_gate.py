"""Protocol 1.6.0 phase-resistance gate: coilEM's phase resistance against hand calculations (public issue 143).

The hand calculations are written out in benchmarks/abcd-v1.6/PHASE-RESISTANCE.md
and registered with their results in phase_resistance_gate.json. These tests
run the gate, and re-derive every registered hand value from the fixture's raw
parameters with the document's formulas, using exact arcs and no coilEM
geometry, so the registration cannot drift from the document.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.benchmark_suite.abc_metrics import band
from backend.benchmark_suite.contract import read, sha
from backend.benchmark_suite.references import load_suite
from backend.benchmark_suite.resistance_metrics import PHASE_RESISTANCE_PCT, REGISTRATION, gate_config, phase_resistance_gates
from backend.models.performance import PHASE_RESISTANCE_DERIVED_WIRE_STATUS_REASON, PHASE_RESISTANCE_STATUS_REASON, WindingResistance
from backend.winding_resistance import winding_resistance

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"
DOCUMENT = ROOT / "benchmarks/abcd-v1.6/PHASE-RESISTANCE.md"
# PHASE-RESISTANCE.md, "Conductor data": IEC 60028 and IEC 60889 at 20 °C, ρ in Ω·mm²/m.
CONDUCTORS = {"copper": (1.0 / 58.0, 0.00393), "aluminum": (0.028264, 0.00403)}


def _registration():
    return read(ROOT / REGISTRATION)


def _cases():
    return _registration()["cases"]


def _segment(radius, half_angle):
    """Area of a circular segment and its centroid's distance from the circle's centre."""
    area = radius**2 * (half_angle - math.sin(half_angle) * math.cos(half_angle))
    return area, 4 * radius * math.sin(half_angle) ** 3 / (3 * (2 * half_angle - math.sin(2 * half_angle)))


def _hand(case):
    """PHASE-RESISTANCE.md, "Method", steps 1-7, from the fixture's raw parameters."""
    fixture = read(ROOT / case["fixture"])
    stator, winding, wire = fixture["stator"], fixture["winding"], case["wire"]
    slots, poles = stator["slot_count"], fixture["rotor"]["pole_count"]

    # 1-2: series turns and turn copper area.
    turns = slots * winding["turns_per_coil"] / 6
    area = wire["strands_in_hand"] * math.pi * wire["wire_bare_diameter_mm"] ** 2 / 4

    # 3: the unshoed slot, as a trapezoid plus the outer segment less the inner one.
    bore_r = stator["ID_mm"] / 2
    mouth = stator["slot_opening_mm"] / 2 / bore_r
    bottom_r = stator["OD_mm"] / 2 - stator["yoke_thickness_mm"]
    body = (2 * math.pi * bottom_r / slots - stator["tooth_width_mm"]) / (2 * bottom_r)
    x1, chord_a = bore_r * math.cos(mouth), 2 * bore_r * math.sin(mouth)
    x2, chord_b = bottom_r * math.cos(body), 2 * bottom_r * math.sin(body)
    height = x2 - x1
    trapezoid = height * (chord_a + chord_b) / 2
    trapezoid_x = x1 + height * (chord_a + 2 * chord_b) / (3 * (chord_a + chord_b))
    outer, outer_x = _segment(bottom_r, body)
    inner, inner_x = _segment(bore_r, mouth)
    slot_area = trapezoid + outer - inner
    radius = (trapezoid * trapezoid_x + outer * outer_x - inner * inner_x) / slot_area

    # 4-5: coil-side angle, half-circle end turn and mean turn length.
    span = 1 if winding["type"] == "concentrated" else winding["coil_span"] or slots // poles
    angle_deg = span * 360 / slots
    half_circle = math.pi / 2 * math.radians(angle_deg) * radius
    end_turn = half_circle + 2 * wire["end_turn_extension_mm"]
    mean_turn = 2 * stator["stack_length_mm"] + 2 * end_turn

    # 6-7: resistance at 20 °C and at the winding temperature.
    resistivity, coefficient = CONDUCTORS[case["conductor"]]
    paths = winding["parallel_paths"]
    resistance_20c = resistivity * turns * mean_turn * 1e-3 / (area * paths**2)
    factor = 1 + coefficient * (case["winding_temperature_C"] - 20)
    return {
        "slot_area_mm2": slot_area,
        "coil_side_radius_mm": radius,
        "coil_side_angle_deg": angle_deg,
        "end_turn_half_circle_mm": half_circle,
        "end_turn_length_mm": end_turn,
        "mean_turn_length_mm": mean_turn,
        "turn_copper_area_mm2": area,
        "series_turns_per_phase": turns,
        "parallel_paths": paths,
        "phase_resistance_20C_ohm": resistance_20c,
        "temperature_factor": factor,
        "phase_resistance_ohm": resistance_20c * factor,
    }


def test_the_gate_is_registered_with_its_document_and_bands():
    registration = _registration()
    assert registration["schema"] == "coilem.phase_resistance_gate/v1" and registration["protocol_version"] == "1.6.0"
    assert ROOT / registration["hand_calculation"] == DOCUMENT and DOCUMENT.is_file()
    gate = registration["gate"]
    assert (gate["quantity"], gate["pass_pct"], gate["yellow_pct"]) == ("phase_resistance_ohm", *PHASE_RESISTANCE_PCT)
    winding_types = {read(ROOT / case["fixture"])["winding"]["type"] for case in registration["cases"]}
    assert winding_types == {"concentrated", "distributed"}
    assert {case["conductor"] for case in registration["cases"]} == set(CONDUCTORS)


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["id"])
def test_each_case_is_a_registered_suite_fixture_with_a_declared_wire(case):
    job = next(item for item in load_suite(SUITE)["cases"] if item["id"] == case["suite_case"])["jobs"][0]
    assert (job["fixture"], job["fixture_sha256"]) == (case["fixture"], case["fixture_sha256"])
    assert sha(ROOT / case["fixture"]) == case["fixture_sha256"]

    # The fixtures carry no wire and no winding temperature, so the declared ones are all the case adds.
    fixture = read(ROOT / case["fixture"])
    assert "wire" not in fixture["winding"] and fixture["solve_params"].get("winding_temperature_C") is None
    config = gate_config(case, ROOT)
    assert config.winding.wire.model_dump(exclude_none=True) == case["wire"]
    assert config.solve_params.winding_temperature_C == case["winding_temperature_C"]
    assert config.materials.conductor == case["conductor"]
    # Every term of the calculation is exercised.
    assert case["wire"]["strands_in_hand"] > 1 and case["wire"]["end_turn_extension_mm"] > 0
    assert case["winding_temperature_C"] > 20


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["id"])
def test_registered_hand_values_follow_from_the_fixture(case):
    derived = _hand(case)
    assert case["hand"].keys() == derived.keys()
    for key, value in derived.items():
        assert case["hand"][key] == pytest.approx(value, rel=1e-6), key


def test_coilem_passes_the_phase_resistance_gate():
    rows = phase_resistance_gates(ROOT)
    assert [row["id"] for row in rows] == [case["id"] for case in _cases()]
    for row in rows:
        assert row["status"] == "PASS", row
        assert row["phase_resistance_error_pct"] < PHASE_RESISTANCE_PCT[0]
        # The turns, strands, paths and conductor data are exact; only the tessellated slot arcs differ.
        assert row["coilem"]["series_turns_per_phase"] == row["hand"]["series_turns_per_phase"]
        assert row["coilem"]["turn_copper_area_mm2"] == pytest.approx(row["hand"]["turn_copper_area_mm2"], rel=1e-6)
        assert row["coilem"]["end_turn_length_mm"] == pytest.approx(row["hand"]["end_turn_length_mm"], rel=1e-4)


def test_the_bands_flag_a_real_slip():
    assert band(0.5, *PHASE_RESISTANCE_PCT) == "PASS"
    assert band(2.0, *PHASE_RESISTANCE_PCT) == "YELLOW"
    case = _cases()[0]
    # Counting the straight extension twice per turn instead of four times.
    short = case["hand"]["phase_resistance_ohm"] * (1 - 2 * case["wire"]["end_turn_extension_mm"] / case["hand"]["mean_turn_length_mm"])
    error = abs(short - case["hand"]["phase_resistance_ohm"]) / case["hand"]["phase_resistance_ohm"] * 100
    assert band(error, *PHASE_RESISTANCE_PCT) == "FAIL"


def test_a_record_with_a_wire_is_qualified_by_the_gate():
    assert WindingResistance.model_fields["status"].default == "qualified"
    assert WindingResistance.model_fields["status_reason"].default == PHASE_RESISTANCE_STATUS_REASON
    assert "phase-resistance gate" in PHASE_RESISTANCE_STATUS_REASON and "1.6.0" in PHASE_RESISTANCE_STATUS_REASON
    record = winding_resistance(gate_config(_cases()[0], ROOT))
    assert (record.wire_source, record.status, record.status_reason) == ("specified", "qualified", PHASE_RESISTANCE_STATUS_REASON)


def test_a_derived_wire_stays_experimental():
    case = _cases()[0]
    config = gate_config(case, ROOT)
    record = winding_resistance(config.model_copy(update={"winding": config.winding.model_copy(update={"wire": None})}))
    assert record.wire_source == "derived"
    assert (record.status, record.status_reason) == ("experimental", PHASE_RESISTANCE_DERIVED_WIRE_STATUS_REASON)
