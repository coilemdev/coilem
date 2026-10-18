"""The 2D Phases preview lights the phases the solver drives at each rotor position.

The frontend (frontend/src/public/phaseDrive.ts) computes the terminal currents in
the public clockwise-positive frame from the drive settings and phase A's axis,
which the preview reports. These tests pin both halves to the launch-surface solve
path: the axis the preview sends, and the sine vectors the frontend checks itself
against (scripts/test-phase-drive.mjs; six-step uses
bldc_six_step_golden_vectors.json).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.excitation import phase_axis_offset_deg, resolve_phase_current_sample
from backend.models import MotorConfig
from backend.preview import generate_preview
from backend.solver import _clockwise_excitation_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks/main-20261009-bad71d9/fixtures"
SINE_VECTORS = json.loads((ROOT / "tests/fixtures/public_sine_phase_current_vectors.json").read_text(encoding="utf-8"))
LAYOUTS = json.loads((ROOT / "tests/fixtures/phase_drive_winding_layouts.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> MotorConfig:
    return MotorConfig.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture", "axis_deg"),
    [
        ("spm_8p12s_concentrated__baseline.json", 30.0),
        ("bldc_spm_8p12s_reference.json", 30.0),
        ("spm_8p24s_distributed_femm_validation.json", 0.0),
        ("spm_8p48s_chorded_5_6.json", 0.0),
    ],
)
def test_preview_reports_the_axis_the_excitation_subtracts(fixture: str, axis_deg: float) -> None:
    config = _fixture(fixture)
    metadata = generate_preview(config).metadata
    assert metadata["phase_axis_offset_elec_deg"] == pytest.approx(phase_axis_offset_deg(config), abs=1e-9)
    assert metadata["phase_axis_offset_elec_deg"] == pytest.approx(axis_deg, abs=1e-9)


def _vector_id(vector: dict) -> str:
    return f"{vector['fixture'][:12]}-g{vector['current_angle_deg']}-t{vector['rotor_electrical_angle_deg']}"


@pytest.mark.parametrize("vector", SINE_VECTORS["vectors"], ids=_vector_id)
def test_sine_vectors_follow_the_launch_surface_solve(vector: dict) -> None:
    config = _fixture(vector["fixture"]).model_copy(deep=True)
    config.solve_params.current_angle_deg = vector["current_angle_deg"]
    config.solve_params.current_amplitude_convention = "peak"
    config.solve_params.current_amplitude_A = 1.0
    assert phase_axis_offset_deg(config) == pytest.approx(vector["phase_axis_offset_elec_deg"], abs=1e-9)
    # What a public solve applies at public rotor angle theta: the mirrored config
    # at the native angle -theta.
    sample = resolve_phase_current_sample(_clockwise_excitation_config(config), -vector["rotor_electrical_angle_deg"])
    assert sample.phase_current_a == pytest.approx(vector["phase_current"], abs=1e-9)
    # ...which is the closed form the frontend uses.
    source = 90.0 - vector["rotor_electrical_angle_deg"] - vector["current_angle_deg"] - vector["phase_axis_offset_elec_deg"]
    closed_form = [math.sin(math.radians(source - 120.0 * k)) for k in range(3)]
    assert closed_form == pytest.approx(vector["phase_current"], abs=1e-9)


@pytest.mark.parametrize("case", LAYOUTS["cases"], ids=lambda case: case["fixture"][:24])
def test_tooth_pole_layouts_match_the_preview(case: dict) -> None:
    """The layouts the frontend checks its tooth poles against are the preview's."""
    config = _fixture(case["fixture"])
    preview = generate_preview(config)
    assert case["slot_count"] == config.stator.slot_count
    assert case["pole_count"] == config.rotor.pole_count
    assert case["phase_axis_offset_elec_deg"] == pytest.approx(preview.metadata["phase_axis_offset_elec_deg"], abs=1e-9)
    assert case["winding_layout"] == [
        {"slot_index": side.slot_index, "layer": side.layer, "phase": side.phase, "direction": side.direction}
        for side in preview.winding_layout
    ]
    # Rotor N axis at rotor angle 0: the mean direction of the N magnets, electrically.
    pairs = config.rotor.pole_count // 2
    total = 0j
    for region in preview.regions:
        if region.region_type.startswith("magnet_n"):
            x = sum(point[0] for point in region.points) / len(region.points)
            y = sum(point[1] for point in region.points) / len(region.points)
            total += complex(math.cos(pairs * math.atan2(y, x)), math.sin(pairs * math.atan2(y, x)))
    assert math.degrees(math.atan2(total.imag, total.real)) % 360 == pytest.approx(case["rotor_n_axis_elec_deg"], abs=0.01)
