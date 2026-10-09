"""Conforming OCC mesh and neutral field-problem gates."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.gmsh_solver import GMSH_AVAILABLE
from backend.halbach.linear_geometry import build_linear_planar_geometry
from backend.halbach.linear_gmsh_adapter import (
    build_linear_magnetostatic_problem,
    generate_linear_halbach_mesh,
)
from backend.halbach.linear_models import canonical_linear_halbach_config
from backend.halbach.materials import resolve_magnet_material

ROOT = Path(__file__).parents[1]
PROBLEM_SCHEMA = json.loads(
    (
        ROOT / "schemas" / "v1" / "magnetostatic_problem.schema.json"
    ).read_text(encoding="utf-8")
)
requires_gmsh = pytest.mark.skipif(not GMSH_AVAILABLE, reason="Gmsh is required")


def _quick_config():
    config = canonical_linear_halbach_config()
    config.solve.quality = "custom"
    config.solve.mesh.density = "coarse"
    config.solve.mesh.outer_padding_factor = 1.0
    config.solve.mesh.minimum_elements_across_magnet = 3
    config.sample_region.samples_per_period = 16
    return config


def _lower(config):
    material = resolve_magnet_material(config.magnet)
    geometry = build_linear_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    mesh = generate_linear_halbach_mesh(config, geometry)
    problem, problem_hash = build_linear_magnetostatic_problem(
        config,
        geometry,
        mesh,
        magnet_mu_r=material.relative_permeability,
    )
    return material, geometry, mesh, problem, problem_hash


@requires_gmsh
@pytest.mark.parametrize("block_gap", [0.0, 0.2])
def test_mesh_maps_every_triangle_and_physical_region_once(
    block_gap: float,
) -> None:
    config = _quick_config()
    config.geometry.block_gap = block_gap
    _material, geometry, mesh, problem, _hash = _lower(config)
    assert mesh.mesh_qa["all_triangles_mapped_once"] is True
    assert mesh.mesh_qa["area_relative_error"] <= 2.5e-6
    assert len(mesh.triangles) == len(mesh.element_region_ids)
    assert len(problem["elements"]) == len(mesh.triangles)
    assert set(mesh.element_region_ids) == {
        region.id for region in geometry.regions
    }
    assert mesh.outer_boundary_nodes
    assert mesh.physical_groups["az_zero"]["name"] == "boundary::az_zero"
    assert {
        "material_interface",
        "critical_corner",
        "far_field",
    } <= set(mesh.feature_physical_groups)


@requires_gmsh
def test_problem_is_generic_and_assigns_each_block_remanence() -> None:
    config = _quick_config()
    material, _geometry, mesh, problem, problem_hash = _lower(config)
    Draft202012Validator(PROBLEM_SCHEMA).validate(problem)
    assert len(problem_hash) == 64
    assert problem["boundaries"]["paired_nodes"] == []
    for region_id, element in zip(mesh.element_region_ids, problem["elements"]):
        if region_id.startswith("magnet_"):
            assert element["material_id"] == 1
            assert (
                sum(component**2 for component in element["remanence_t"])
                ** 0.5
            ) == pytest.approx(material.remanence_t)
        else:
            assert element["material_id"] == 0
            assert element["remanence_t"] == [0.0, 0.0]


@requires_gmsh
def test_mesh_identity_is_invariant_to_side_phase_and_depth() -> None:
    first = _quick_config()
    second = copy.deepcopy(first)
    second.array.strong_side = "negative_y"
    second.array.phase_deg = 23.0
    second.geometry.out_of_plane_depth *= 2.5
    first_result = _lower(first)
    second_result = _lower(second)
    assert first_result[1].geometry_hash == second_result[1].geometry_hash
    assert first_result[2].mesh_hash == second_result[2].mesh_hash
    assert first_result[4] != second_result[4]

    depth_only = copy.deepcopy(first)
    depth_only.geometry.out_of_plane_depth *= 3.0
    depth_result = _lower(depth_only)
    assert first_result[2].mesh_hash == depth_result[2].mesh_hash
    assert first_result[4] == depth_result[4]
