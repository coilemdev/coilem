"""Strict configuration and rectangular-geometry contract gates."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.halbach.linear_geometry import (
    LINEAR_MODEL_NOTICE,
    block_magnetization_angle_deg,
    build_linear_planar_geometry,
)
from backend.halbach.linear_models import (
    LinearHalbachArrayConfig,
    canonical_linear_halbach_config,
)
from backend.halbach.materials import resolve_magnet_material

ROOT = Path(__file__).parents[1]
EXAMPLE_PATH = (
    ROOT
    / "schemas"
    / "v1"
    / "examples"
    / "linear_halbach_array_4_period.json"
)
SCHEMA = json.loads(
    (
        ROOT
        / "schemas"
        / "v1"
        / "linear_halbach_array_config.schema.json"
    ).read_text(encoding="utf-8")
)


def _payload() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def test_checked_in_example_validates_against_schema_and_runtime() -> None:
    payload = _payload()
    Draft202012Validator(SCHEMA).validate(payload)
    config = LinearHalbachArrayConfig.model_validate(payload)
    assert config.geometry.block_count == 16
    assert config.geometry.wavelength == pytest.approx(40.0)
    assert config.geometry.active_length == pytest.approx(160.0)


def test_period_dependent_defaults_leave_a_complete_probe_period() -> None:
    payload = {
        "geometry": {
            "block_width": 10.0,
            "magnet_height": 10.0,
            "out_of_plane_depth": 100.0,
            "period_count": 1,
        },
        "magnet": {"source": "catalog"},
    }
    config = LinearHalbachArrayConfig.model_validate(payload)
    assert config.sample_region.edge_exclusion_periods == 0
    assert config.sample_region.samples_per_period == 64


def test_unknown_and_invalid_cross_fields_fail_closed() -> None:
    unknown = _payload()
    unknown["geometry"]["inner_radius"] = 25.0
    assert list(Draft202012Validator(SCHEMA).iter_errors(unknown))
    with pytest.raises(ValidationError):
        LinearHalbachArrayConfig.model_validate(unknown)

    excluded = _payload()
    excluded["sample_region"]["edge_exclusion_periods"] = 2
    with pytest.raises(ValidationError, match="leave at least one"):
        LinearHalbachArrayConfig.model_validate(excluded)

    outside = _payload()
    outside["solve"]["quality"] = "custom"
    outside["solve"]["mesh"]["outer_padding_factor"] = 0.5
    outside["sample_region"]["probe_offset"] = 20.0
    with pytest.raises(ValidationError, match="inside the modeled outer boundary"):
        LinearHalbachArrayConfig.model_validate(outside)


def test_geometry_has_four_left_to_right_blocks_per_period() -> None:
    config = canonical_linear_halbach_config()
    material = resolve_magnet_material(config.magnet)
    geometry = build_linear_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    magnets = [
        region
        for region in geometry.regions
        if region.kind == "permanent_magnet"
    ]
    assert len(magnets) == 4 * config.geometry.period_count
    assert all(
        left.bounds_mm[2] <= right.bounds_mm[0]
        for left, right in zip(magnets, magnets[1:])
    )
    assert geometry.area_closure_error_mm2 == pytest.approx(0.0)
    assert geometry.metadata["model_notice"] == LINEAR_MODEL_NOTICE
    assert [block_magnetization_angle_deg(config, index) for index in range(4)] == [
        0.0,
        90.0,
        180.0,
        270.0,
    ]


def test_gapped_probe_span_contains_complete_center_periods() -> None:
    config = canonical_linear_halbach_config().model_copy(deep=True)
    config.solve.quality = "custom"
    config.geometry.block_gap = 2.0
    material = resolve_magnet_material(config.magnet)
    geometry = build_linear_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    probes = geometry.metadata["probe_lines"]
    expected_span = probes["retained_periods"] * config.geometry.wavelength

    assert probes["x_min_mm"] == pytest.approx(-0.5 * expected_span)
    assert probes["x_max_mm"] == pytest.approx(0.5 * expected_span)
    assert probes["x_max_mm"] - probes["x_min_mm"] == pytest.approx(
        expected_span
    )


def test_geometry_identity_excludes_source_side_phase_and_depth() -> None:
    first = canonical_linear_halbach_config()
    second = copy.deepcopy(first)
    second.array.strong_side = "negative_y"
    second.array.phase_deg = 31.0
    second.geometry.out_of_plane_depth *= 2.0
    first_material = resolve_magnet_material(first.magnet)
    second_material = resolve_magnet_material(second.magnet)
    first_geometry = build_linear_planar_geometry(
        first,
        remanence_t=first_material.remanence_t,
        material_key=first_material.name,
    )
    second_geometry = build_linear_planar_geometry(
        second,
        remanence_t=second_material.remanence_t,
        material_key=second_material.name,
    )
    assert first_geometry.geometry_hash == second_geometry.geometry_hash
    assert (
        first_geometry.regions[0].magnetization_xy
        != second_geometry.regions[0].magnetization_xy
    )
