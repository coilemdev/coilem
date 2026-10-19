"""Phase resistance, mean turn length and slot fill (#136)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.models import MotorConfig
from backend.preview import generate_preview
from backend.winding_resistance import CONDUCTORS, DEFAULT_COPPER_FILL_LIMIT, winding_resistance

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks" / "main-20261009-bad71d9" / "fixtures"
ACCORD = ROOT / "docs" / "hardware-validation" / "honda-accord-2005"


def _load(path: Path, **winding) -> MotorConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["winding"].update(winding)
    return MotorConfig.model_validate(raw)


def _distributed(**winding) -> MotorConfig:
    return _load(FIXTURES / "spm_8p24s_distributed_femm_validation.json", **winding)


def _accord_as_built(**winding) -> MotorConfig:
    # The real Accord winding (#91): a coil on every tooth, 52 turns per coil,
    # so 104 conductors per slot, and 8 parallel circuits per phase.
    return _load(ACCORD / "request.json", layers=2, turns_per_coil=104, parallel_paths=8, **winding)


def _with_temperature(config: MotorConfig, temperature_c: float) -> MotorConfig:
    return config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"winding_temperature_C": temperature_c})})


def test_accord_matches_its_measured_phase_resistance():
    provenance = json.loads((ACCORD / "input-provenance.json").read_text(encoding="utf-8"))["table_2_3"]
    config = _with_temperature(_accord_as_built(wire={"wire_bare_diameter_mm": provenance["wire_diameter_mm"]}), 21.0)
    result = winding_resistance(config)
    assert result.series_turns_per_phase == pytest.approx(provenance["stator_turns_per_coil"] * 8)
    assert result.parallel_paths == provenance["parallel_circuits_per_phase"]
    # ORNL/TM-2006/535 Table 2.3: 0.0097 Ohm per phase at 21 C.
    assert result.phase_resistance_ohm == pytest.approx(provenance["phase_resistance_ohm_21C"], rel=0.02)


@pytest.mark.parametrize(
    "config",
    [
        _distributed(wire={"wire_bare_diameter_mm": 0.8, "strands_in_hand": 3}),
        _accord_as_built(wire={"wire_bare_diameter_mm": 1.55}),
    ],
    ids=["distributed", "tooth_coil"],
)
def test_resistance_matches_the_hand_calculation(config):
    result = winding_resistance(config)
    wire = config.winding.wire
    turns = config.stator.slot_count * config.winding.turns_per_coil / 6
    area_m2 = wire.strands_in_hand * math.pi * (wire.wire_bare_diameter_mm * 1e-3) ** 2 / 4
    mean_turn_m = 2 * config.stator.stack_length_mm * 1e-3 + 2 * result.end_turn_length_mm * 1e-3
    expected = CONDUCTORS["copper"].resistivity_20c_ohm_m * turns * mean_turn_m / (area_m2 * config.winding.parallel_paths**2)
    assert result.phase_resistance_20C_ohm == pytest.approx(expected, rel=1e-9)
    assert result.mean_turn_length_mm == pytest.approx(mean_turn_m * 1e3)
    assert result.active_fraction == pytest.approx(2 * config.stator.stack_length_mm / result.mean_turn_length_mm)


def test_distributed_end_turn_spans_the_coil_pitch():
    full = winding_resistance(_distributed(wire={"wire_bare_diameter_mm": 0.8}))
    chorded_config = _load(FIXTURES / "spm_8p48s_chorded_5_6.json", wire={"wire_bare_diameter_mm": 0.8})
    chorded = winding_resistance(chorded_config)
    full_pitch = winding_resistance(chorded_config.model_copy(update={"winding": chorded_config.winding.model_copy(update={"coil_span": 6})}))
    # A half circle across the coil's arc scales with its span: 5 of 6 slots.
    assert chorded.end_turn_length_mm == pytest.approx(full_pitch.end_turn_length_mm * 5 / 6, rel=1e-6)
    assert full.end_turn_length_mm > 0


def test_resistance_follows_wire_turns_paths_and_temperature():
    base_config = _distributed(wire={"wire_bare_diameter_mm": 1.0})
    base = winding_resistance(base_config).phase_resistance_20C_ohm

    def resistance(**winding):
        return winding_resistance(base_config.model_copy(update={"winding": base_config.winding.model_copy(update=winding)})).phase_resistance_20C_ohm

    wire = base_config.winding.wire
    assert resistance(wire=wire.model_copy(update={"wire_bare_diameter_mm": 2.0})) == pytest.approx(base / 4)
    assert resistance(wire=wire.model_copy(update={"strands_in_hand": 2})) == pytest.approx(base / 2)
    assert resistance(parallel_paths=1) == pytest.approx(base * base_config.winding.parallel_paths**2)
    assert resistance(turns_per_coil=base_config.winding.turns_per_coil * 2) == pytest.approx(base * 2)

    hot = winding_resistance(_with_temperature(base_config, 120.0))
    assert hot.winding_temperature_C == 120.0
    assert hot.phase_resistance_ohm == pytest.approx(base * (1 + 0.00393 * 100.0))
    aluminium = winding_resistance(base_config.model_copy(update={"materials": base_config.materials.model_copy(update={"conductor": "aluminum"})}))
    assert aluminium.phase_resistance_20C_ohm == pytest.approx(base * 0.028264 * 58)


def test_end_turn_extension_adds_four_straight_lengths_per_turn():
    plain = winding_resistance(_distributed(wire={"wire_bare_diameter_mm": 1.0}))
    extended = winding_resistance(_distributed(wire={"wire_bare_diameter_mm": 1.0, "end_turn_extension_mm": 10.0}))
    assert extended.mean_turn_length_mm == pytest.approx(plain.mean_turn_length_mm + 40.0)


def test_slot_fill_and_its_limit():
    config = _distributed(wire={"wire_bare_diameter_mm": 1.0, "insulation_build_mm": 0.07})
    result = winding_resistance(config)
    copper = config.winding.turns_per_coil * math.pi * 1.0**2 / 4
    assert result.copper_fill == pytest.approx(copper / result.slot_area_mm2)
    assert result.wire_fill == pytest.approx(config.winding.turns_per_coil * math.pi * 1.07**2 / 4 / result.slot_area_mm2)
    assert result.copper_fill_limit == DEFAULT_COPPER_FILL_LIMIT

    crowded = winding_resistance(_distributed(wire={"wire_bare_diameter_mm": 1.0, "slot_fill_limit": result.copper_fill / 2}))
    assert not crowded.fits
    assert any("above the" in note for note in crowded.notes)
    too_big = winding_resistance(_distributed(wire={"wire_bare_diameter_mm": 6.0, "insulation_build_mm": 0.1, "slot_fill_limit": 0.99}))
    assert not too_big.fits
    assert any("cannot fit" in note for note in too_big.notes)


def test_a_design_without_wire_gets_a_derived_wire_and_says_so():
    result = winding_resistance(_distributed())
    assert result.wire_source == "derived"
    assert result.copper_fill == pytest.approx(DEFAULT_COPPER_FILL_LIMIT)
    assert result.fits
    assert any("derived" in note for note in result.notes)
    assert result.winding_temperature_C == 20.0


def test_preview_reports_resistance_and_the_exact_fill():
    preview = generate_preview(_distributed(wire={"wire_bare_diameter_mm": 1.0}))
    record = preview.metadata["winding_resistance"]
    assert record["wire_source"] == "specified"
    assert preview.metadata["fill_factor"] == pytest.approx(record["copper_fill"])
    assert record["phase_resistance_ohm"] > 0


def test_wire_round_trips_through_a_design_file():
    config = _distributed(wire={"wire_bare_diameter_mm": 0.9, "strands_in_hand": 4, "end_turn_extension_mm": 12.0})
    reloaded = MotorConfig.model_validate_json(config.model_dump_json())
    assert reloaded.winding.wire == config.winding.wire
