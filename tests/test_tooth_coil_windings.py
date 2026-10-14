"""Fractional-slot concentrated windings are wound as real tooth coils (#91).

A coil on tooth t has its go side in slot t and its return side in slot t+1.
One layer winds every other tooth; two layers wind every tooth, half a slot's
conductors per coil side. Concentrated windings with q >= 1 keep the legacy
whole-slot map. Every layout measures gamma from phase A's own axis. tests/fixtures/tooth_coil_layouts.json is shared with the
Magneto2D test that holds the Rust slot map to the same layouts.
"""

from __future__ import annotations

import cmath
import json
import math
from pathlib import Path

import pytest

from backend.geometry import validate_geometry
from backend.geometry_drawer import current_angle_elec_deg_for_rotor_elec
from backend.models import MotorConfig
from backend.winding_utils import (
    concentrated_phase_phasors,
    concentrated_slot_layer_assignments,
    concentrated_uses_tooth_coils,
    concentrated_winding_factor,
    legacy_concentrated_slot_phase,
    tooth_coil_assignments,
    tooth_coil_layout_error,
    winding_phase_axis_offset_elec_deg,
)

pytestmark = pytest.mark.pr

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUTS = json.loads((FIXTURES / "tooth_coil_layouts.json").read_text(encoding="utf-8"))["cases"]


def _label(case: dict) -> str:
    return f"{case['slot_count']}s{case['pole_count']}p-L{case['layers']}"


def _config(slot_count: int, pole_count: int, layers: int, parallel_paths: int = 1) -> MotorConfig:
    data = json.loads((FIXTURES / "spm_8p12s_concentrated.json").read_text(encoding="utf-8"))
    data["materials"].update(stator_steel="M350-50A", rotor_steel="M350-50A")
    data["stator"]["slot_count"] = slot_count
    data["rotor"]["pole_count"] = pole_count
    data["winding"].update(layers=layers, parallel_paths=parallel_paths)
    return MotorConfig.model_validate(data)


@pytest.mark.parametrize("case", LAYOUTS, ids=_label)
def test_layouts_match_the_shared_fixture(case: dict) -> None:
    s, p, layers = case["slot_count"], case["pole_count"], case["layers"]
    actual = [
        [[side.phase, side.direction, side.turn_fraction] for side in concentrated_slot_layer_assignments(slot, s, p, layers)]
        for slot in range(s)
    ]
    assert actual == case["slots"]
    assert winding_phase_axis_offset_elec_deg("concentrated", s, p, layers) == pytest.approx(
        case["phase_axis_offset_elec_deg"], abs=1e-6
    )
    assert concentrated_winding_factor(s, p, layers) == pytest.approx(case["winding_factor"], abs=1e-9)


@pytest.mark.parametrize(
    ("slot_count", "pole_count", "layers", "expected"),
    [
        (12, 8, 1, 0.866),
        (12, 8, 2, 0.866),
        (24, 16, 2, 0.866),
        (9, 8, 2, 0.945),
        (12, 10, 1, 0.966),
        (12, 10, 2, 0.933),
        (36, 30, 1, 0.966),
        (36, 30, 2, 0.933),
    ],
)
def test_winding_factors_match_the_textbook_values(slot_count: int, pole_count: int, layers: int, expected: float) -> None:
    assert concentrated_winding_factor(slot_count, pole_count, layers) == pytest.approx(expected, abs=5e-4)


@pytest.mark.parametrize("case", LAYOUTS, ids=_label)
def test_every_coil_returns_through_the_next_slot(case: dict) -> None:
    s, p, layers = case["slot_count"], case["pole_count"], case["layers"]
    fraction = 0.5 if layers >= 2 else 1.0
    coils = tooth_coil_assignments(s, p, layers)
    assert len(coils) == (s if layers >= 2 else s // 2)
    for tooth, phase, direction in coils:
        back = "out" if direction == "in" else "in"
        go_sides = [(a.phase, a.direction, a.turn_fraction) for a in concentrated_slot_layer_assignments(tooth, s, p, layers)]
        return_sides = [(a.phase, a.direction, a.turn_fraction) for a in concentrated_slot_layer_assignments(tooth + 1, s, p, layers)]
        assert (phase, direction, fraction) in go_sides
        assert (phase, back, fraction) in return_sides
    # Go and return sides cancel per phase, so a common A_z offset never reaches the flux linkage.
    for phase in "ABC":
        signed = sum(
            (1.0 if side.direction == "in" else -1.0) * side.turn_fraction
            for slot in range(s)
            for side in concentrated_slot_layer_assignments(slot, s, p, layers)
            if side.phase == phase
        )
        assert signed == 0.0


@pytest.mark.parametrize("case", LAYOUTS, ids=_label)
def test_phases_are_balanced_in_the_distributed_sequence(case: dict) -> None:
    phasors = concentrated_phase_phasors(case["slot_count"], case["pole_count"], case["layers"])
    magnitude = abs(phasors["A"])
    assert abs(phasors["B"]) == pytest.approx(magnitude) and abs(phasors["C"]) == pytest.approx(magnitude)
    angle = {phase: math.degrees(cmath.phase(value)) for phase, value in phasors.items()}
    # B leads A by 120 electrical degrees in slot order, as in the distributed layouts.
    assert (angle["B"] - angle["A"]) % 360.0 == pytest.approx(120.0)
    assert (angle["C"] - angle["B"]) % 360.0 == pytest.approx(120.0)
    assert angle["A"] == pytest.approx(case["phase_axis_offset_elec_deg"], abs=1e-6)


def test_q_of_one_or_more_keeps_the_legacy_whole_slot_map() -> None:
    assert not concentrated_uses_tooth_coils(12, 4)
    assert winding_phase_axis_offset_elec_deg("concentrated", 12, 4, 1) == 0.0
    for slot in range(12):
        (side,) = concentrated_slot_layer_assignments(slot, 12, 4, 1)
        assert (side.phase, side.direction) == legacy_concentrated_slot_phase(slot, 12, 2)


@pytest.mark.parametrize(
    ("winding_type", "slot_count", "pole_count", "layers", "coil_span", "expected"),
    [
        ("distributed", 24, 8, 1, None, 0.0),
        ("distributed", 36, 12, 2, None, 0.0),
        ("distributed", 48, 8, 1, None, 15.0),
        ("distributed", 48, 8, 2, None, 15.0),
        ("distributed", 48, 8, 2, 5, 0.0),
        ("distributed", 72, 8, 1, None, 20.0),
        ("concentrated", 12, 4, 1, None, 0.0),
        ("concentrated", 12, 8, 1, None, 30.0),
    ],
)
def test_phase_axis_offset_sits_at_the_phase_belt_centre(
    winding_type: str, slot_count: int, pole_count: int, layers: int, coil_span: int | None, expected: float
) -> None:
    # Same table as Magneto2D's phase_axis_offset_sits_at_the_phase_belt_centre; exact, not approximate,
    # so a layout with its axis at 0 keeps its historical source angles bit for bit.
    assert winding_phase_axis_offset_elec_deg(winding_type, slot_count, pole_count, layers, coil_span) == expected


def test_slot_counts_the_phases_cannot_share_are_not_tooth_coils() -> None:
    assert not concentrated_uses_tooth_coils(10, 8)
    assert not concentrated_uses_tooth_coils(1, 2)


def test_a_single_layer_needs_an_even_slot_count() -> None:
    error = tooth_coil_layout_error(9, 8, 1)
    assert error is not None and "layers = 2" in error
    assert tooth_coil_layout_error(9, 8, 2) is None


def test_gamma_stays_measured_from_the_q_axis() -> None:
    # 12s8p tooth coils put phase A's axis at +30 electrical degrees; the source angle absorbs it.
    assert current_angle_elec_deg_for_rotor_elec(_config(12, 8, 1), 0.0) == pytest.approx(-120.0)
    assert current_angle_elec_deg_for_rotor_elec(_config(12, 4, 1), 0.0) == pytest.approx(-90.0)


@pytest.mark.parametrize(
    ("layers", "parallel_paths", "accepted"),
    [(1, 4, True), (1, 3, False), (2, 8, True), (2, 16, False)],
)
def test_parallel_paths_must_divide_the_tooth_coils_per_phase(layers: int, parallel_paths: int, accepted: bool) -> None:
    # 24s16p: 4 coils per phase on alternate teeth, 8 with every tooth wound (the 2005 Accord's 8 paths).
    errors = [e for e in validate_geometry(_config(24, 16, layers, parallel_paths)) if e.field == "winding.parallel_paths"]
    assert (not errors) == accepted, errors
