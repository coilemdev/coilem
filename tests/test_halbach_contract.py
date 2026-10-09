"""HAL-01/HAL-02 configuration, material, and geometry contract gates."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.halbach.geometry import (
    AXIAL_END_EFFECTS_NOTICE,
    _canonical_hash,
    build_planar_geometry,
    magnetization_angle_deg,
    signed_polygon_area,
    tessellated_region_loop,
)
from backend.halbach.materials import (
    CATALOG_COERCIVITY_AUDIT,
    resolve_magnet_material,
)
from backend.halbach.models import QUALITY_PRESETS, HalbachArrayConfig
from backend.material_catalog import MAGNET_PROPERTIES

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads(
    (ROOT / "schemas" / "v1" / "halbach_array_config.schema.json").read_text(
        encoding="utf-8"
    )
)
CANONICAL_PATH = ROOT / "schemas" / "v1" / "examples" / "halbach_array_16_segment.json"
CUSTOM_PATH = ROOT / "schemas" / "v1" / "examples" / "halbach_array_custom_magnet.json"
INVALID_PATH = (
    ROOT
    / "schemas"
    / "v1"
    / "examples"
    / "invalid"
    / "halbach_gap_too_large.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [CANONICAL_PATH, CUSTOM_PATH], ids=lambda path: path.stem)
def test_valid_examples_validate_against_schema_and_pydantic(path: Path) -> None:
    payload = _load(path)
    Draft202012Validator(SCHEMA).validate(payload)
    assert HalbachArrayConfig.model_validate(payload).version == "1.0"


def test_minimal_schema_and_runtime_config_expand_the_same_defaults() -> None:
    payload = {
        "geometry": {
            "inner_radius": 25.0,
            "outer_radius": 50.0,
            "axial_length": 100.0,
        },
        "magnet": {"source": "catalog"},
    }
    Draft202012Validator(SCHEMA).validate(payload)
    config = HalbachArrayConfig.model_validate(payload)
    assert config.geometry.segment_count == 16
    assert config.sample_region.radius == pytest.approx(20.0)
    assert config.sample_region.leakage_probe_radius == pytest.approx(75.0)
    assert config.sample_region.radial_samples == 31
    assert config.sample_region.angular_samples == 96
    assert config.magnet.grade == "N42"
    assert config.solve.quality == "standard"


@pytest.mark.parametrize("quality", ["quick", "standard", "fine"])
def test_quality_presets_are_expanded_server_side(quality: str) -> None:
    payload = _load(CANONICAL_PATH)
    payload["solve"]["quality"] = quality
    payload["solve"]["mesh"]["outer_boundary_radius_factor"] = 11.0
    payload["solve"]["mesh"]["minimum_elements_across_magnet"] = 2
    payload["solve"]["linear"]["tolerance"] = 1.0e-4
    payload["sample_region"]["radial_samples"] = 5
    payload["sample_region"]["angular_samples"] = 16
    config = HalbachArrayConfig.model_validate(payload)
    preset = QUALITY_PRESETS[quality]
    assert config.solve.mesh.density == preset["density"]
    assert config.solve.mesh.outer_boundary_radius_factor == (
        preset["outer_boundary_radius_factor"]
    )
    assert config.solve.mesh.minimum_elements_across_magnet == (
        preset["minimum_elements_across_magnet"]
    )
    assert config.solve.linear.tolerance == preset["tolerance"]
    assert config.sample_region.radial_samples == preset["radial_samples"]
    assert config.sample_region.angular_samples == preset["angular_samples"]


def test_custom_quality_preserves_advanced_settings() -> None:
    payload = _load(CANONICAL_PATH)
    payload["solve"]["quality"] = "custom"
    payload["solve"]["mesh"]["outer_boundary_radius_factor"] = 5.0
    payload["sample_region"]["radial_samples"] = 19
    config = HalbachArrayConfig.model_validate(payload)
    assert config.solve.mesh.outer_boundary_radius_factor == 5.0
    assert config.sample_region.radial_samples == 19


def test_unknown_fields_are_rejected_by_schema_and_runtime() -> None:
    payload = _load(CANONICAL_PATH)
    payload["geometry"]["invented_motor_poles"] = 2
    errors = list(Draft202012Validator(SCHEMA).iter_errors(payload))
    assert errors
    assert "Additional properties are not allowed" in errors[0].message
    with pytest.raises(ValidationError) as exc:
        HalbachArrayConfig.model_validate(payload)
    assert exc.value.errors()[0]["loc"] == ("geometry", "invented_motor_poles")


def test_invalid_cross_field_fixture_returns_field_addressable_error() -> None:
    with pytest.raises(ValidationError) as exc:
        HalbachArrayConfig.model_validate(_load(INVALID_PATH))
    message = str(exc.value)
    assert "geometry.segment_gap_angle" in message
    assert "half the segment pitch" in message


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("outer_radius", 24.0, "geometry.outer_radius"),
        ("segment_count", 3, "greater than or equal to 4"),
        ("segment_gap_angle", 11.25, "geometry.segment_gap_angle"),
    ],
)
def test_geometry_relationship_validation(field: str, value: float, expected: str) -> None:
    payload = _load(CANONICAL_PATH)
    payload["geometry"][field] = value
    with pytest.raises(ValidationError, match=expected):
        HalbachArrayConfig.model_validate(payload)


def test_roi_and_leakage_relationships_are_validated() -> None:
    payload = _load(CANONICAL_PATH)
    payload["sample_region"]["radius"] = 24.0
    with pytest.raises(ValidationError, match="sample_region.radius"):
        HalbachArrayConfig.model_validate(payload)
    payload = _load(CANONICAL_PATH)
    payload["sample_region"]["leakage_probe_radius"] = 200.0
    with pytest.raises(ValidationError, match="inside the modeled outer boundary"):
        HalbachArrayConfig.model_validate(payload)


def test_every_selectable_catalog_grade_has_an_explicit_coercivity_audit() -> None:
    assert set(CATALOG_COERCIVITY_AUDIT) == set(MAGNET_PROPERTIES)
    for grade, audit in CATALOG_COERCIVITY_AUDIT.items():
        assert audit.grade == grade
        assert audit.classification in {"intrinsic", "normal", "unknown"}
        assert audit.original_unit == "kA/m"
        assert audit.normalized_a_per_m > 0.0
        assert audit.catalog_revision
        assert audit.provenance
        assert audit.eligible_for_margin is (audit.classification == "intrinsic")


def test_legacy_catalog_coercivity_is_metadata_only_until_intrinsic_provenance_exists() -> None:
    material = resolve_magnet_material(
        HalbachArrayConfig.model_validate(_load(CANONICAL_PATH)).magnet
    )
    assert material.coercivity_classification == "unknown"
    assert material.coercivity_margin_eligible is False
    assert material.coercivity_a_per_m == pytest.approx(955_000.0)
    assert material.coercivity_ineligible_reason == (
        "catalog_coercivity_not_audited_as_intrinsic"
    )


def test_custom_intrinsic_coercivity_is_margin_eligible_and_derates_independently() -> None:
    config = HalbachArrayConfig.model_validate(_load(CUSTOM_PATH))
    material = resolve_magnet_material(config.magnet)
    delta = 60.0
    assert material.remanence_t == pytest.approx(1.31 * (1 - 0.0012 * delta))
    assert material.coercivity_a_per_m == pytest.approx(
        955_000.0 * (1 - 0.0055 * delta)
    )
    assert material.br_temperature["coefficient_per_k"] == -0.0012
    assert material.hcj_temperature["coefficient_per_k"] == -0.0055
    assert material.br_temperature["reference_temperature_c"] == 20.0
    assert material.hcj_temperature["reference_temperature_c"] == 20.0
    assert material.coercivity_classification == "intrinsic"
    assert material.coercivity_margin_eligible is True
    assert material.provenance["source_note"] == "Supplier datasheet revision 3"


def test_catalog_temperature_range_error_is_field_addressable() -> None:
    payload = _load(CANONICAL_PATH)
    payload["magnet"]["grade"] = "N42"
    payload["magnet"]["temperature_c"] = 200.0
    with pytest.raises(ValidationError) as exc:
        HalbachArrayConfig.model_validate(payload)
    assert exc.value.errors()[0]["loc"] == ("magnet", "catalog", "temperature_c")


@pytest.mark.parametrize("segment_count", [4, 5, 8, 9, 16, 32])
def test_magnetization_formula_is_frozen_for_odd_and_even_counts(
    segment_count: int,
) -> None:
    payload = _load(CANONICAL_PATH)
    payload["geometry"]["segment_count"] = segment_count
    payload["geometry"]["segment_gap_angle"] = 0.0
    payload["array"]["field_direction"] = 17.0
    config = HalbachArrayConfig.model_validate(payload)
    pitch = 360.0 / segment_count
    for index in range(segment_count):
        theta = (index + 0.5) * pitch
        assert magnetization_angle_deg(config, index) == pytest.approx(
            2.0 * theta - 17.0
        )


@pytest.mark.parametrize("segment_count", [5, 8, 9, 16])
@pytest.mark.parametrize("gap_angle", [0.0, 0.4])
def test_geometry_area_closure_orientation_and_region_inventory(
    segment_count: int,
    gap_angle: float,
) -> None:
    payload = _load(CANONICAL_PATH)
    payload["geometry"]["segment_count"] = segment_count
    payload["geometry"]["segment_gap_angle"] = gap_angle
    config = HalbachArrayConfig.model_validate(payload)
    material = resolve_magnet_material(config.magnet)
    geometry = build_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    assert abs(geometry.area_closure_error_mm2) <= 1.0e-9
    kinds = [region.kind for region in geometry.regions]
    assert kinds.count("bore_air") == 1
    assert kinds.count("permanent_magnet") == segment_count
    assert kinds.count("gap_air") == (segment_count if gap_angle else 0)
    assert kinds.count("exterior_air") == 1
    for region in geometry.regions:
        if region.kind in {"permanent_magnet", "gap_air"}:
            loop = tessellated_region_loop(geometry, region.id, arc_steps=64)
            assert signed_polygon_area(loop) > 0.0
            assert signed_polygon_area(loop) == pytest.approx(
                region.area_mm2, rel=5.0e-4
            )


def test_geometry_emits_application_neutral_feature_tags() -> None:
    config = HalbachArrayConfig.model_validate(_load(CANONICAL_PATH))
    material = resolve_magnet_material(config.magnet)
    geometry = build_planar_geometry(
        config, remanence_t=material.remanence_t, material_key=material.name
    )
    flattened = {
        tag for tags in geometry.feature_tags.values() for tag in tags
    }
    assert {
        "critical_curve",
        "critical_corner",
        "material_interface",
        "permanent_magnet_edge",
        "far_field",
        "dirichlet_boundary",
        "bore_roi_boundary",
    } <= flattened
    serialized = json.dumps(geometry.as_dict()).lower()
    for forbidden in ("stator", "rotor", "slot_count", "pole_count", "winding"):
        assert forbidden not in serialized


def test_axial_length_does_not_change_geometry_or_2d_contract_identity() -> None:
    first_payload = _load(CANONICAL_PATH)
    second_payload = copy.deepcopy(first_payload)
    second_payload["geometry"]["axial_length"] *= 3.0
    first = HalbachArrayConfig.model_validate(first_payload)
    second = HalbachArrayConfig.model_validate(second_payload)
    first_material = resolve_magnet_material(first.magnet)
    second_material = resolve_magnet_material(second.magnet)
    first_geometry = build_planar_geometry(
        first,
        remanence_t=first_material.remanence_t,
        material_key=first_material.name,
    )
    second_geometry = build_planar_geometry(
        second,
        remanence_t=second_material.remanence_t,
        material_key=second_material.name,
    )
    assert first_geometry.geometry_hash == second_geometry.geometry_hash
    assert first_geometry.metadata["axial_length_mm"] * 3.0 == (
        second_geometry.metadata["axial_length_mm"]
    )
    assert first_geometry.metadata["model_notice"] == AXIAL_END_EFFECTS_NOTICE


def test_segmented_analytical_formula_reference() -> None:
    config = HalbachArrayConfig.model_validate(_load(CANONICAL_PATH))
    material = resolve_magnet_material(config.magnet)
    ideal = material.remanence_t * math.log(2.0)
    factor = math.sin(2 * math.pi / 16) / (2 * math.pi / 16)
    assert ideal * factor == pytest.approx(0.8781093231908217)


def test_geometry_hash_ignores_platform_level_float_noise() -> None:
    first = {"coordinate": 0.12345678901231, "nested": [1.0, -1.0e-16]}
    second = {"coordinate": 0.12345678901239, "nested": [1.0, 1.0e-16]}
    materially_different = {"coordinate": 0.123456789014, "nested": [1.0, 0.0]}

    assert _canonical_hash(first) == _canonical_hash(second)
    assert _canonical_hash(first) != _canonical_hash(materially_different)
