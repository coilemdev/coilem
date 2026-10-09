"""HAL-03 conforming Gmsh and generic field-problem lowering gates."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.gmsh_solver import GMSH_AVAILABLE
from backend.halbach.geometry import build_planar_geometry
from backend.halbach.gmsh_adapter import (
    build_magnetostatic_problem,
    canonical_json_bytes,
    generate_halbach_mesh,
)
from backend.halbach.materials import resolve_magnet_material
from backend.halbach.models import HalbachArrayConfig

ROOT = Path(__file__).parents[1]
EXAMPLE = json.loads(
    (
        ROOT / "schemas" / "v1" / "examples" / "halbach_array_16_segment.json"
    ).read_text(encoding="utf-8")
)
PROBLEM_SCHEMA = json.loads(
    (ROOT / "schemas" / "v1" / "magnetostatic_problem.schema.json").read_text(
        encoding="utf-8"
    )
)

requires_gmsh = pytest.mark.skipif(not GMSH_AVAILABLE, reason="Gmsh is required")


def _lower(payload: dict):
    config = HalbachArrayConfig.model_validate(payload)
    material = resolve_magnet_material(config.magnet)
    geometry = build_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    mesh = generate_halbach_mesh(config, geometry)
    problem, problem_hash = build_magnetostatic_problem(
        config, geometry, mesh, magnet_mu_r=material.relative_permeability
    )
    return config, material, geometry, mesh, problem, problem_hash


@requires_gmsh
@pytest.mark.parametrize("segment_count", [5, 8, 9, 16])
@pytest.mark.parametrize("gap_angle", [0.0, 0.35])
def test_full_360_mesh_maps_every_triangle_once(
    segment_count: int, gap_angle: float
) -> None:
    payload = copy.deepcopy(EXAMPLE)
    payload["geometry"]["segment_count"] = segment_count
    payload["geometry"]["segment_gap_angle"] = gap_angle
    _config, _material, geometry, mesh, problem, _hash = _lower(payload)
    assert mesh.mesh_qa["all_triangles_mapped_once"] is True
    assert len(mesh.triangles) == len(mesh.element_region_ids)
    assert len(problem["elements"]) == len(mesh.triangles)
    assert set(mesh.element_region_ids) == {region.id for region in geometry.regions}
    assert mesh.outer_boundary_nodes
    assert mesh.physical_groups["az_zero"]["name"] == "boundary::az_zero"
    if gap_angle:
        assert "critical_gap" in mesh.feature_physical_groups


@requires_gmsh
def test_problem_validates_and_assigns_correct_element_physics() -> None:
    _config, material, _geometry, mesh, problem, problem_hash = _lower(
        copy.deepcopy(EXAMPLE)
    )
    Draft202012Validator(PROBLEM_SCHEMA).validate(problem)
    assert len(problem_hash) == 64
    for region_id, element in zip(mesh.element_region_ids, problem["elements"]):
        if region_id.startswith("magnet_"):
            assert element["material_id"] == 1
            assert element["pm_source_scale"] == 1.0
            assert sum(component**2 for component in element["remanence_t"]) ** 0.5 == pytest.approx(
                material.remanence_t
            )
        else:
            assert element == {
                "material_id": 0,
                "current_density_z_a_per_m2": 0.0,
                "remanence_t": [0.0, 0.0],
                "pm_source_scale": 1.0,
            }


@requires_gmsh
@pytest.mark.weekly
def test_canonical_geometry_hash_is_frozen_and_solver_hashes_are_consistent() -> None:
    _config, _material, geometry, mesh, problem, problem_hash = _lower(
        copy.deepcopy(EXAMPLE)
    )
    assert geometry.geometry_hash == (
        "8dddee68d77137885dd75c46b832227b0b699dfa0b69a174d5ab9ca961697857"
    )
    assert len(mesh.mesh_hash) == 64
    assert len(problem_hash) == 64
    assert hashlib.sha256(canonical_json_bytes(problem)).hexdigest() == problem_hash


@requires_gmsh
def test_field_problem_and_mesh_are_independent_of_axial_length() -> None:
    first = copy.deepcopy(EXAMPLE)
    second = copy.deepcopy(EXAMPLE)
    second["geometry"]["axial_length"] = first["geometry"]["axial_length"] * 2.0
    first_result = _lower(first)
    second_result = _lower(second)
    assert first_result[3].mesh_hash == second_result[3].mesh_hash
    assert first_result[5] == second_result[5]
    assert first_result[4] == second_result[4]


@requires_gmsh
def test_tag_driven_sizing_policy_has_no_segment_index_keys() -> None:
    _config, _material, _geometry, mesh, _problem, _hash = _lower(
        copy.deepcopy(EXAMPLE)
    )
    keys = mesh.mesh_info["sizing_keys"]
    assert "critical_curve" in keys
    assert "critical_corner" in keys
    assert "far_field" in keys
    assert not any("segment_" in key for key in keys)
    assert mesh.mesh_info["corner_refinement"] is True
    assert mesh.mesh_info["corner_size_mm"] < mesh.mesh_info["interface_size_mm"]


@requires_gmsh
def test_missing_or_unknown_region_mapping_fails_closed() -> None:
    config, material, geometry, mesh, _problem, _hash = _lower(
        copy.deepcopy(EXAMPLE)
    )
    tampered = copy.copy(mesh)
    object.__setattr__(
        tampered,
        "element_region_ids",
        ("unknown_physical_group", *mesh.element_region_ids[1:]),
    )
    with pytest.raises(ValueError, match="unknown physical region"):
        build_magnetostatic_problem(
            config, geometry, tampered, magnet_mu_r=material.relative_permeability
        )


@requires_gmsh
def test_numerical_sliver_gap_is_rejected() -> None:
    payload = copy.deepcopy(EXAMPLE)
    payload["geometry"]["segment_gap_angle"] = 1.0e-7
    config = HalbachArrayConfig.model_validate(payload)
    material = resolve_magnet_material(config.magnet)
    geometry = build_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    with pytest.raises(ValueError, match="numerical sliver"):
        generate_halbach_mesh(config, geometry)
