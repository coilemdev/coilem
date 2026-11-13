"""Explicit winding-side identities make rotated solution reports unambiguous."""

from __future__ import annotations

import copy
import math
import random
from typing import Any

import pytest

from backend.gmsh_mesh_rotation import derive_congruent_solve_report, slot_current_pattern_matches

pytestmark = pytest.mark.pr

SLOTS = 6
POLES = 4
TURNS = 8
STACK_M = 0.125
REFERENCE_AZ = 0.03125
PHASES = "ABC"


def _currents(angle: float, amplitude: float = 2.0) -> list[float]:
    theta = math.radians(angle)
    return [amplitude * math.sin(theta - phase * 2.0 * math.pi / 3.0) for phase in range(3)]


def _labels(slot: int, layer: int) -> tuple[str, str]:
    phase = PHASES[(slot + 2 * (layer - 1)) % 3]
    direction = "in" if (slot < 3) == (layer == 1) else "out"
    return phase, direction


def _effective_az(slot: int, layer: int) -> float:
    return (2 * slot + layer) / 64.0


def _direct_contribution(slot: int, layer: int, field_slot: int) -> float:
    # Independent physical formula; the report's stored contribution is never
    # used by the oracle. All coefficients are binary fractions or integers.
    _, direction = _labels(slot, layer)
    sign = 1.0 if direction == "in" else -1.0
    return sign * 0.5 * TURNS * STACK_M * _effective_az(field_slot, layer)


def _report() -> dict[str, Any]:
    rows = []
    phase_flux = [0.0, 0.0, 0.0]
    excitation = []
    for slot in range(SLOTS):
        for layer in (1, 2):
            phase, direction = _labels(slot, layer)
            contribution = _direct_contribution(slot, layer, slot)
            phase_flux[PHASES.index(phase)] += contribution
            rows.append({
                "slot_index_modeled": slot,
                "slot_index_global": slot,
                "slot_layer": layer,
                "turn_fraction": 0.5,
                "phase": phase,
                "direction": direction,
                "center_angle_mech_deg": slot * 360.0 / SLOTS,
                "az_reference_wb_per_m": REFERENCE_AZ,
                "az_avg_wb_per_m": REFERENCE_AZ + _effective_az(slot, layer),
                "az_effective_wb_per_m": _effective_az(slot, layer),
                "slot_area_m2": (slot + layer) / 128.0,
                "turns_per_coil": TURNS,
                "contribution_wb": contribution,
            })
        phase, direction = _labels(slot, 1)
        area = (2 * slot + 3) / 128.0
        density = float((-1) ** slot * (slot + 1))
        amp_turns = area * density
        excitation.append({
            "slot_index_modeled": slot,
            "slot_index_global": slot,
            "phase": phase,
            "direction": direction,
            "center_angle_mech_deg": slot * 360.0 / SLOTS,
            "slot_area_m2": area,
            "effective_current_density_a_per_m2": density,
            "integrated_amp_turns_a": amp_turns,
            "slot_current_a": amp_turns / TURNS,
            "phase_current_a": _currents(0.0)[PHASES.index(phase)],
            "turns_per_coil": TURNS,
        })
    return {
        "config_summary": {"slots": SLOTS, "poles": POLES, "stack_length_mm": 1000.0 * STACK_M},
        "results": {
            "source_current_angle_deg": 0.0,
            "phase_current_a": _currents(0.0),
            "slot_flux_linkage_contributions": rows,
            "slot_excitation_contributions": excitation,
            **{f"flux_linkage_{phase.lower()}_wb": phase_flux[index] for index, phase in enumerate(PHASES)},
            "torque_nm": 0.375,
            "energy_j": 0.0625,
        },
        "field_plot": {"nodes_mm": [[1.0, 0.0], [0.0, 2.0]], "az": [0.125, -0.25]},
        "solve_info": {"total_time_ms": 15, "nonlinear_iterations": 3},
    }


def _derive(report: dict[str, Any], shift: int = 1, **overrides: Any) -> dict[str, Any]:
    mechanical = shift * 360.0 / SLOTS
    arguments = {
        "slot_count": SLOTS,
        "n_slot_pitches": shift,
        "rotation_delta_deg": mechanical,
        "elec_delta_deg": mechanical * POLES / 2,
        **overrides,
    }
    return derive_congruent_solve_report(report, **arguments)


def test_derived_report_copies_what_it_changes_and_shares_the_field_arrays() -> None:
    base = _report()
    original = copy.deepcopy(base)

    derived = _derive(base, 1)

    assert base == original
    # Unchanged per-element field data is shared, not copied once per derived position.
    assert derived["field_plot"]["az"] is base["field_plot"]["az"]
    assert derived["field_plot"] is not base["field_plot"] and derived["field_plot"]["nodes_mm"] != base["field_plot"]["nodes_mm"]
    assert derived["results"] is not base["results"] and derived["solve_info"] is not base["solve_info"]
    assert derived["solve_info"]["total_time_ms"] == 0 and base["solve_info"]["total_time_ms"] == 15


@pytest.mark.parametrize("shift", [0, 1, -1, 2, SLOTS + 1, -SLOTS - 1])
def test_layer_permutation_matches_direct_physical_sum_and_keeps_base_unchanged(shift: int) -> None:
    base = _report()
    random.Random(29).shuffle(base["results"]["slot_flux_linkage_contributions"])
    random.Random(17).shuffle(base["results"]["slot_excitation_contributions"])
    original = copy.deepcopy(base)

    derived = _derive(base, shift)

    assert base == original
    rows = derived["results"]["slot_flux_linkage_contributions"]
    assert [(row["slot_index_global"], row["slot_layer"]) for row in rows] == [
        (slot, layer) for slot in range(SLOTS) for layer in (1, 2)
    ]
    original_rows = {(row["slot_index_global"], row["slot_layer"]): row for row in original["results"]["slot_flux_linkage_contributions"]}
    expected_flux = [0.0, 0.0, 0.0]
    for row in rows:
        slot, layer = row["slot_index_global"], row["slot_layer"]
        source_slot = (slot - shift) % SLOTS
        source = original_rows[source_slot, layer]
        target = original_rows[slot, layer]
        assert row["phase"] == target["phase"]
        assert row["direction"] == target["direction"]
        assert row["turn_fraction"] == 0.5
        assert row["turns_per_coil"] == TURNS
        for field in ("az_reference_wb_per_m", "az_avg_wb_per_m", "az_effective_wb_per_m", "slot_area_m2"):
            assert row[field] == source[field]
        expected = _direct_contribution(slot, layer, source_slot)
        assert row["contribution_wb"] == expected
        expected_flux[PHASES.index(target["phase"])] += expected
    assert [derived["results"][f"flux_linkage_{phase.lower()}_wb"] for phase in PHASES] == expected_flux
    assert derived["results"]["torque_nm"] == original["results"]["torque_nm"]
    assert derived["results"]["energy_j"] == original["results"]["energy_j"]
    assert derived["field_plot"]["az"] == original["field_plot"]["az"]
    angle = math.radians(shift * 360.0 / SLOTS)
    for actual, (x, y) in zip(derived["field_plot"]["nodes_mm"], original["field_plot"]["nodes_mm"], strict=True):
        assert actual == pytest.approx([x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)])


@pytest.mark.parametrize("shift", [1, -1, SLOTS + 1])
def test_excitation_stays_whole_slot_and_moves_signed_integrals_without_direction_flip(shift: int) -> None:
    base = _report()
    original_rows = base["results"]["slot_excitation_contributions"]

    derived = _derive(base, shift)

    currents = derived["results"]["phase_current_a"]
    assert currents == pytest.approx(_currents(shift * 360.0 / SLOTS * POLES / 2))
    rows = derived["results"]["slot_excitation_contributions"]
    assert len(rows) == SLOTS
    assert [row["slot_index_global"] for row in rows] == list(range(SLOTS))
    for slot, row in enumerate(rows):
        source, target = original_rows[(slot - shift) % SLOTS], original_rows[slot]
        assert row.keys() == target.keys()
        assert row["phase"] == target["phase"]
        assert row["direction"] == target["direction"]
        assert row["phase_current_a"] == currents[PHASES.index(target["phase"])]
        for field in ("slot_area_m2", "effective_current_density_a_per_m2", "integrated_amp_turns_a", "slot_current_a"):
            assert row[field] == source[field]


def test_zero_current_two_layer_report_can_reuse_a_no_load_field() -> None:
    base = _report()
    base["results"]["phase_current_a"] = [0.0, 0.0, 0.0]
    for row in base["results"]["slot_excitation_contributions"]:
        for field in ("effective_current_density_a_per_m2", "integrated_amp_turns_a", "slot_current_a", "phase_current_a"):
            row[field] = 0.0

    derived = _derive(base)

    assert derived["results"]["phase_current_a"] == [0.0, 0.0, 0.0]
    assert all(row["phase_current_a"] == 0.0 for row in derived["results"]["slot_excitation_contributions"])


def test_legacy_one_row_reports_need_no_new_fields_or_turns_metadata() -> None:
    base = _report()
    rows = [row for row in base["results"]["slot_flux_linkage_contributions"] if row["slot_layer"] == 1]
    for row in rows:
        for field in ("slot_layer", "turn_fraction", "turns_per_coil"):
            del row[field]
    base["results"]["slot_flux_linkage_contributions"] = rows
    base["results"].pop("slot_excitation_contributions")

    derived = _derive(base)

    assert len(derived["results"]["slot_flux_linkage_contributions"]) == SLOTS
    for slot, row in enumerate(derived["results"]["slot_flux_linkage_contributions"]):
        assert not ({"slot_layer", "turn_fraction", "turns_per_coil"} & row.keys())
        assert row["contribution_wb"] == _direct_contribution(slot, 1, (slot - 1) % SLOTS)


@pytest.mark.parametrize("damage", ["missing-ids", "mixed-ids", "duplicate-layer", "missing-side", "missing-slot", "only-one-layer"])
def test_ambiguous_or_incomplete_side_coverage_falls_back(damage: str) -> None:
    base = _report()
    rows = base["results"]["slot_flux_linkage_contributions"]
    if damage in ("missing-ids", "mixed-ids"):
        for row in rows if damage == "missing-ids" else rows[:1]:
            row.pop("slot_layer")
    elif damage == "duplicate-layer":
        rows[1]["slot_layer"] = 1
    elif damage == "missing-side":
        rows.pop()
    elif damage == "missing-slot":
        del rows[-2:]
    else:
        base["results"]["slot_flux_linkage_contributions"] = rows[::2]

    with pytest.raises(ValueError):
        _derive(base)


@pytest.mark.parametrize(("field", "value"), [
    ("slot_index_global", True), ("slot_index_global", -1), ("slot_index_global", SLOTS),
    ("slot_layer", 0), ("slot_layer", 3), ("slot_layer", True), ("slot_layer", "1"),
    ("turns_per_coil", 0), ("turns_per_coil", True), ("turns_per_coil", 8.5), ("turns_per_coil", TURNS + 1),
    ("turn_fraction", 0.0), ("turn_fraction", True), ("turn_fraction", "0.5"), ("turn_fraction", 0.25),
    ("turn_fraction", math.nan), ("turn_fraction", math.inf),
    ("phase", "D"), ("direction", "IN"), ("slot_area_m2", 0.0), ("slot_area_m2", -1.0),
])
def test_invalid_side_identity_coefficients_and_labels_fall_back(field: str, value: Any) -> None:
    base = _report()
    base["results"]["slot_flux_linkage_contributions"][0][field] = value

    with pytest.raises(ValueError):
        _derive(base)


@pytest.mark.parametrize("field", [
    "az_reference_wb_per_m", "az_avg_wb_per_m", "az_effective_wb_per_m", "slot_area_m2", "contribution_wb",
])
@pytest.mark.parametrize("value", [math.nan, math.inf, True])
def test_nonfinite_or_boolean_side_measurements_fall_back(field: str, value: float | bool) -> None:
    base = _report()
    base["results"]["slot_flux_linkage_contributions"][0][field] = value

    with pytest.raises(ValueError):
        _derive(base)


@pytest.mark.parametrize("field", ["az_reference_wb_per_m", "az_avg_wb_per_m", "az_effective_wb_per_m", "contribution_wb"])
def test_inconsistent_gauge_or_terminal_coefficient_falls_back(field: str) -> None:
    base = _report()
    base["results"]["slot_flux_linkage_contributions"][0][field] += 1.0 / 1024.0

    with pytest.raises(ValueError):
        _derive(base)


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("damage", ["incorrect", "missing", "nonfinite"])
def test_base_phase_flux_must_match_the_complete_side_sum(phase: str, damage: str) -> None:
    base = _report()
    results = base["results"]
    key = f"flux_linkage_{phase.lower()}_wb"
    if damage == "incorrect":
        results[key] += 1.0 / 1024.0
    elif damage == "missing":
        del results[key]
    else:
        results[key] = math.inf

    with pytest.raises(ValueError):
        _derive(base)


@pytest.mark.parametrize("change", ["base-angle", "mechanical-angle", "electrical-angle", "fractional-shift", "wrong-mechanical", "wrong-electrical"])
def test_invalid_or_inconsistent_rotation_metadata_falls_back(change: str) -> None:
    base = _report()
    overrides = {}
    if change == "base-angle":
        base["results"]["source_current_angle_deg"] = math.nan
    elif change == "mechanical-angle":
        overrides["rotation_delta_deg"] = math.nan
    elif change == "electrical-angle":
        overrides["elec_delta_deg"] = math.inf
    elif change == "fractional-shift":
        overrides["n_slot_pitches"] = 1.5
    elif change == "wrong-mechanical":
        overrides["rotation_delta_deg"] = 61.0
    else:
        overrides["elec_delta_deg"] = 121.0

    with pytest.raises(ValueError):
        _derive(base, **overrides)


@pytest.mark.parametrize("currents", [[1.0, 1.0, 1.0], [3.0, 0.0, -3.0], [1.0, -1.0], [0.0] * 4, [math.nan, 0.0, 0.0]])
def test_phase_currents_must_match_the_reported_base_sinusoid(currents: list[float]) -> None:
    base = _report()
    base["results"]["phase_current_a"] = currents

    with pytest.raises(ValueError):
        _derive(base)


@pytest.mark.parametrize(("base", "derived", "expected"), [
    ([None, 2.0, -3.0], [None, 2.0, -3.0], True),
    ([None, 2.0, -3.0], [None, 2.0 + 1e-10, -3.0], True),
    ([None, 2.0, -3.0], [None, -2.0, -3.0], False),
    ([None, 2.0], [0.0, 2.0], False),
    ([0.0, None, 0.0], [0.0, None, 0.0], True),
    ([1.0], [1.0, 1.0], False),
    (None, [1.0], False),
    ([1.0], None, False),
])
def test_existing_rhs_equivalence_gate_remains_required(base: Any, derived: Any, expected: bool) -> None:
    first = {} if base is None else {"element_current_density_a_per_m2": base}
    second = {} if derived is None else {"element_current_density_a_per_m2": derived}

    assert slot_current_pattern_matches(first, second) is expected
