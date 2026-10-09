"""OCC/Gmsh lowering for finite rectangular linear Halbach arrays."""

from __future__ import annotations

import concurrent.futures
import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any

from backend.gmsh_solver import _GMSH_API_LOCK, GMSH_AVAILABLE, gmsh
from backend.solver_environment import ISOLATED_RUNTIME

from .gmsh_adapter import canonical_json_bytes
from .linear_geometry import (
    LinearPlanarGeometryArtifact,
    LinearPlanarRegion,
)
from .linear_models import LinearHalbachArrayConfig


class LinearHalbachMeshError(ValueError):
    """A linear Halbach geometry could not be lowered to a valid mesh."""


_LINEAR_GMSH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="linear-halbach-gmsh",
)


@dataclass(frozen=True)
class LinearHalbachMeshArtifact:
    nodes_mm: tuple[tuple[float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    element_region_ids: tuple[str, ...]
    outer_boundary_nodes: tuple[int, ...]
    physical_groups: dict[str, dict[str, Any]]
    feature_physical_groups: dict[str, dict[str, Any]]
    mesh_info: dict[str, Any]
    mesh_qa: dict[str, Any]
    mesh_hash: str
    gmsh_time_ms: float
    cad_time_ms: float
    mesh_generation_time_ms: float

    def preview_payload(self) -> dict[str, Any]:
        return {
            "kind": "linear_halbach_mesh_preview",
            "version": "1.0",
            "nodes_mm": [list(node) for node in self.nodes_mm],
            "triangles": [list(triangle) for triangle in self.triangles],
            "regions": list(self.element_region_ids),
            "outer_boundary_nodes": list(self.outer_boundary_nodes),
            "physical_groups": self.physical_groups,
            "feature_physical_groups": self.feature_physical_groups,
            "mesh_info": self.mesh_info,
            "mesh_qa": self.mesh_qa,
            "mesh_hash": self.mesh_hash,
            "timings_ms": {
                "gmsh_total": self.gmsh_time_ms,
                "cad": self.cad_time_ms,
                "mesh_generation": self.mesh_generation_time_ms,
            },
        }


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _triangle_quality(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> tuple[float, float]:
    twice_area = (
        (b[0] - a[0]) * (c[1] - a[1])
        - (b[1] - a[1]) * (c[0] - a[0])
    )
    area = 0.5 * abs(twice_area)
    lengths2 = (
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2,
        (b[0] - c[0]) ** 2 + (b[1] - c[1]) ** 2,
        (c[0] - a[0]) ** 2 + (c[1] - a[1]) ** 2,
    )
    denominator = sum(lengths2)
    quality = (
        0.0
        if denominator <= 0.0
        else 4.0 * math.sqrt(3.0) * area / denominator
    )
    return area, quality


def _entity_boundaries(
    surfaces: list[int],
    *,
    dimension: int,
) -> set[int]:
    if not surfaces:
        return set()
    curves = {
        abs(tag)
        for dim, tag in gmsh.model.getBoundary(
            [(2, surface) for surface in surfaces],
            combined=False,
            oriented=False,
            recursive=False,
        )
        if dim == 1
    }
    if dimension == 1:
        return curves
    if dimension != 0:
        raise ValueError(f"unsupported boundary dimension {dimension}")
    return {
        abs(tag)
        for dim, tag in gmsh.model.getBoundary(
            [(1, curve) for curve in curves],
            combined=False,
            oriented=False,
            recursive=False,
        )
        if dim == 0
    }


def _outer_rectangle_curves(
    air_surfaces: list[int],
    bounds: tuple[float, float, float, float],
) -> set[int]:
    xmin, ymin, xmax, ymax = bounds
    span = max(xmax - xmin, ymax - ymin)
    tolerance = max(1.0e-8, span * 1.0e-9)
    curves = _entity_boundaries(air_surfaces, dimension=1)
    outer: set[int] = set()
    for curve in curves:
        bx0, by0, _bz0, bx1, by1, _bz1 = gmsh.model.getBoundingBox(1, curve)
        on_left = abs(bx0 - xmin) <= tolerance and abs(bx1 - xmin) <= tolerance
        on_right = abs(bx0 - xmax) <= tolerance and abs(bx1 - xmax) <= tolerance
        on_bottom = abs(by0 - ymin) <= tolerance and abs(by1 - ymin) <= tolerance
        on_top = abs(by0 - ymax) <= tolerance and abs(by1 - ymax) <= tolerance
        if on_left or on_right or on_bottom or on_top:
            outer.add(curve)
    return outer


def generate_linear_halbach_mesh(
    config: LinearHalbachArrayConfig,
    geometry: LinearPlanarGeometryArtifact,
) -> LinearHalbachMeshArtifact:
    """Run all OCC calls on one stable thread across API and direct callers."""

    return _LINEAR_GMSH_EXECUTOR.submit(
        _generate_linear_halbach_mesh,
        config,
        geometry,
    ).result()


def _generate_linear_halbach_mesh(
    config: LinearHalbachArrayConfig,
    geometry: LinearPlanarGeometryArtifact,
) -> LinearHalbachMeshArtifact:
    """Generate a conforming full-domain P1 triangular mesh."""

    if not GMSH_AVAILABLE or gmsh is None:
        raise RuntimeError(
            "Gmsh is required for linear Halbach meshing. Install the pinned "
            "gmsh Python package."
        )
    started = time.perf_counter()
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.Algorithm", 5)
            gmsh.option.setNumber("Mesh.Optimize", 0)
            gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
            gmsh.model.add("linear_halbach_array_v1")

            xmin, ymin, xmax, ymax = geometry.domain_bounds_mm
            outer = gmsh.model.occ.addRectangle(
                xmin,
                ymin,
                0.0,
                xmax - xmin,
                ymax - ymin,
            )
            magnet_regions = [
                region
                for region in geometry.regions
                if region.kind == "permanent_magnet"
            ]
            magnet_objects: list[tuple[int, int]] = []
            for region in magnet_regions:
                rx0, ry0, rx1, ry1 = region.bounds_mm
                tag = gmsh.model.occ.addRectangle(
                    rx0,
                    ry0,
                    0.0,
                    rx1 - rx0,
                    ry1 - ry0,
                )
                magnet_objects.append((2, tag))

            fragmented, source_map = gmsh.model.occ.fragment(
                [(2, outer)],
                magnet_objects,
                removeObject=True,
                removeTool=True,
            )
            gmsh.model.occ.synchronize()
            all_surfaces = {
                int(tag) for dim, tag in fragmented if int(dim) == 2
            }
            if len(source_map) != 1 + len(magnet_regions):
                raise LinearHalbachMeshError(
                    "OCC fragment did not retain source-to-surface provenance"
                )

            surfaces_by_region: dict[str, list[int]] = {}
            claimed_magnet_surfaces: set[int] = set()
            for region, mapped in zip(magnet_regions, source_map[1:]):
                surfaces = sorted(
                    {
                        int(tag)
                        for dim, tag in mapped
                        if int(dim) == 2
                    }
                )
                if not surfaces:
                    raise LinearHalbachMeshError(
                        f"OCC fragment produced no surface for {region.id}"
                    )
                overlap = claimed_magnet_surfaces & set(surfaces)
                if overlap:
                    raise LinearHalbachMeshError(
                        f"magnet OCC surfaces overlap for {region.id}: "
                        f"{sorted(overlap)}"
                    )
                claimed_magnet_surfaces.update(surfaces)
                surfaces_by_region[region.id] = surfaces
            air_surfaces = sorted(all_surfaces - claimed_magnet_surfaces)
            if not air_surfaces:
                raise LinearHalbachMeshError(
                    "OCC fragment produced no exterior-air surface"
                )
            surfaces_by_region["exterior_air"] = air_surfaces

            smaller_magnet_dimension = min(
                config.geometry.block_width,
                config.geometry.magnet_height,
            )
            density_factor = {
                "coarse": 1.0,
                "normal": 1.0,
                "fine": 0.65,
            }[config.solve.mesh.density]
            interface_size = (
                smaller_magnet_dimension
                / config.solve.mesh.minimum_elements_across_magnet
                * density_factor
            )
            corner_size = (
                0.55 * interface_size
                if config.solve.mesh.corner_refinement
                else interface_size
            )
            domain_span = max(xmax - xmin, ymax - ymin)
            far_size = min(
                geometry.metadata["wavelength_mm"] / 2.0,
                max(interface_size * 6.0, domain_span / 24.0),
            )
            all_points = [tag for dim, tag in gmsh.model.getEntities(0) if dim == 0]
            gmsh.model.mesh.setSize([(0, tag) for tag in all_points], far_size)
            magnet_surfaces = sorted(claimed_magnet_surfaces)
            magnet_curves = _entity_boundaries(magnet_surfaces, dimension=1)
            magnet_points = _entity_boundaries(magnet_surfaces, dimension=0)
            if magnet_points:
                gmsh.model.mesh.setSize(
                    [(0, tag) for tag in sorted(magnet_points)],
                    corner_size,
                )
            if magnet_curves:
                distance_field = gmsh.model.mesh.field.add("Distance")
                gmsh.model.mesh.field.setNumbers(
                    distance_field,
                    "CurvesList",
                    sorted(magnet_curves),
                )
                gmsh.model.mesh.field.setNumber(
                    distance_field,
                    "Sampling",
                    60,
                )
                threshold_field = gmsh.model.mesh.field.add("Threshold")
                gmsh.model.mesh.field.setNumber(
                    threshold_field,
                    "InField",
                    distance_field,
                )
                gmsh.model.mesh.field.setNumber(
                    threshold_field,
                    "SizeMin",
                    interface_size,
                )
                gmsh.model.mesh.field.setNumber(
                    threshold_field,
                    "SizeMax",
                    far_size,
                )
                gmsh.model.mesh.field.setNumber(
                    threshold_field,
                    "DistMin",
                    smaller_magnet_dimension,
                )
                gmsh.model.mesh.field.setNumber(
                    threshold_field,
                    "DistMax",
                    max(
                        2.0 * smaller_magnet_dimension,
                        geometry.metadata["wavelength_mm"],
                    ),
                )
                gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)

            physical_group_tags: dict[str, int] = {}
            for region in geometry.regions:
                region_surfaces = surfaces_by_region.get(region.id)
                if not region_surfaces:
                    raise LinearHalbachMeshError(
                        f"missing Gmsh surfaces for physical region {region.id}"
                    )
                tag = gmsh.model.addPhysicalGroup(2, region_surfaces)
                gmsh.model.setPhysicalName(2, tag, f"region::{region.id}")
                physical_group_tags[region.id] = tag

            outer_curves = _outer_rectangle_curves(
                air_surfaces,
                geometry.domain_bounds_mm,
            )
            if len(outer_curves) < 4:
                raise LinearHalbachMeshError(
                    "failed to identify all four outer rectangular boundaries"
                )
            outer_boundary_group = gmsh.model.addPhysicalGroup(
                1,
                sorted(outer_curves),
            )
            gmsh.model.setPhysicalName(
                1,
                outer_boundary_group,
                "boundary::az_zero",
            )

            feature_entities: dict[str, tuple[int, set[int]]] = {
                "material_interface": (1, magnet_curves),
                "permanent_magnet_edge": (1, magnet_curves),
                "critical_corner": (0, magnet_points),
                "far_field": (1, outer_curves),
                "dirichlet_boundary": (1, outer_curves),
            }
            feature_group_tags: dict[str, tuple[int, int]] = {}
            for feature, (dimension, entities) in feature_entities.items():
                if not entities:
                    continue
                tag = gmsh.model.addPhysicalGroup(
                    dimension,
                    sorted(entities),
                )
                gmsh.model.setPhysicalName(
                    dimension,
                    tag,
                    f"feature::{feature}",
                )
                feature_group_tags[feature] = (dimension, tag)

            cad_finished = time.perf_counter()
            gmsh.model.mesh.generate(2)
            mesh_finished = time.perf_counter()

            node_tags_raw, coordinates_raw, _ = gmsh.model.mesh.getNodes()
            node_records = sorted(
                (
                    int(tag),
                    (
                        float(coordinates_raw[3 * index]),
                        float(coordinates_raw[3 * index + 1]),
                    ),
                )
                for index, tag in enumerate(node_tags_raw)
            )
            node_index = {
                tag: index
                for index, (tag, _coordinate) in enumerate(node_records)
            }
            nodes = tuple(coordinate for _tag, coordinate in node_records)

            element_records: list[
                tuple[int, tuple[int, int, int], str]
            ] = []
            seen_element_tags: set[int] = set()
            for region_id, surfaces in surfaces_by_region.items():
                for surface in surfaces:
                    (
                        element_types,
                        element_tag_blocks,
                        node_tag_blocks,
                    ) = gmsh.model.mesh.getElements(2, surface)
                    for element_type, element_tags, connectivity in zip(
                        element_types,
                        element_tag_blocks,
                        node_tag_blocks,
                    ):
                        (
                            _name,
                            _dimension,
                            _order,
                            node_count,
                            _local,
                            _primary,
                        ) = gmsh.model.mesh.getElementProperties(element_type)
                        if int(node_count) != 3:
                            raise LinearHalbachMeshError(
                                "unexpected non-P1 triangle element type "
                                f"{element_type}"
                            )
                        for offset, element_tag in enumerate(element_tags):
                            tag = int(element_tag)
                            if tag in seen_element_tags:
                                raise LinearHalbachMeshError(
                                    f"triangle {tag} appears in multiple regions"
                                )
                            seen_element_tags.add(tag)
                            raw_nodes = connectivity[
                                offset * 3 : offset * 3 + 3
                            ]
                            try:
                                triangle = (
                                    node_index[int(raw_nodes[0])],
                                    node_index[int(raw_nodes[1])],
                                    node_index[int(raw_nodes[2])],
                                )
                            except KeyError as exc:
                                raise LinearHalbachMeshError(
                                    f"triangle {tag} references an unknown node"
                                ) from exc
                            element_records.append(
                                (tag, triangle, region_id)
                            )

            all_types, all_tag_blocks, _ = gmsh.model.mesh.getElements(2)
            all_triangle_tags = {
                int(tag)
                for element_type, tags in zip(all_types, all_tag_blocks)
                if int(
                    gmsh.model.mesh.getElementProperties(element_type)[3]
                )
                == 3
                for tag in tags
            }
            if seen_element_tags != all_triangle_tags:
                missing = sorted(all_triangle_tags - seen_element_tags)
                unknown = sorted(seen_element_tags - all_triangle_tags)
                raise LinearHalbachMeshError(
                    "triangle-to-region mapping is incomplete: "
                    f"missing={missing[:8]}, unknown={unknown[:8]}"
                )
            element_records.sort(key=lambda record: record[0])
            triangles = tuple(record[1] for record in element_records)
            element_region_ids = tuple(
                record[2] for record in element_records
            )

            boundary_node_tags, _ = gmsh.model.mesh.getNodesForPhysicalGroup(
                1,
                outer_boundary_group,
            )
            outer_boundary_nodes = tuple(
                sorted(
                    {
                        node_index[int(tag)]
                        for tag in boundary_node_tags
                    }
                )
            )
            if not outer_boundary_nodes:
                raise LinearHalbachMeshError(
                    "outer az_zero physical group has no mesh nodes"
                )

            region_counts: dict[str, int] = {}
            triangle_area_by_region: dict[str, float] = {}
            areas: list[float] = []
            qualities: list[float] = []
            for triangle, region_id in zip(
                triangles,
                element_region_ids,
            ):
                area, quality = _triangle_quality(
                    nodes[triangle[0]],
                    nodes[triangle[1]],
                    nodes[triangle[2]],
                )
                if area <= 1.0e-14 or quality <= 0.0:
                    raise LinearHalbachMeshError(
                        f"degenerate triangle mapped to {region_id}"
                    )
                areas.append(area)
                qualities.append(quality)
                region_counts[region_id] = (
                    region_counts.get(region_id, 0) + 1
                )
                triangle_area_by_region[region_id] = (
                    triangle_area_by_region.get(region_id, 0.0) + area
                )
            missing_regions = sorted(
                region.id
                for region in geometry.regions
                if region_counts.get(region.id, 0) == 0
            )
            if missing_regions:
                raise LinearHalbachMeshError(
                    "physical regions contain no triangles: "
                    f"{missing_regions}"
                )
            total_mesh_area = sum(areas)
            expected_area = (xmax - xmin) * (ymax - ymin)
            area_relative_error = (
                abs(total_mesh_area - expected_area) / expected_area
            )
            if area_relative_error > 2.5e-6:
                raise LinearHalbachMeshError(
                    "mesh area closure exceeds tolerance: "
                    f"{area_relative_error:.3%}"
                )

            physical_groups = {
                region_id: {
                    "dimension": 2,
                    "tag": physical_group_tags[region_id],
                    "name": f"region::{region_id}",
                    "entity_tags": surfaces,
                    "triangle_count": region_counts[region_id],
                }
                for region_id, surfaces in surfaces_by_region.items()
            }
            physical_groups["az_zero"] = {
                "dimension": 1,
                "tag": outer_boundary_group,
                "name": "boundary::az_zero",
                "entity_tags": sorted(outer_curves),
                "node_count": len(outer_boundary_nodes),
            }
            feature_physical_groups = {
                feature: {
                    "dimension": dimension,
                    "tag": tag,
                    "name": f"feature::{feature}",
                    "entity_tags": sorted(feature_entities[feature][1]),
                }
                for feature, (dimension, tag) in feature_group_tags.items()
            }
            mesh_identity = {
                "nodes_mm": nodes,
                "triangles": triangles,
                "element_region_ids": element_region_ids,
                "outer_boundary_nodes": outer_boundary_nodes,
            }
            return LinearHalbachMeshArtifact(
                nodes_mm=nodes,
                triangles=triangles,
                element_region_ids=element_region_ids,
                outer_boundary_nodes=outer_boundary_nodes,
                physical_groups=physical_groups,
                feature_physical_groups=feature_physical_groups,
                mesh_info={
                    "mesh_source": "gmsh_occ",
                    "gmsh_version": getattr(gmsh, "__version__", "unknown"),
                    "num_nodes": len(nodes),
                    "num_triangles": len(triangles),
                    "mesh_density": config.solve.mesh.density,
                    "minimum_elements_across_magnet": (
                        config.solve.mesh.minimum_elements_across_magnet
                    ),
                    "corner_refinement": (
                        config.solve.mesh.corner_refinement
                    ),
                    "domain_bounds_mm": list(geometry.domain_bounds_mm),
                    "outer_padding_factor": (
                        config.solve.mesh.outer_padding_factor
                    ),
                    "interface_size_mm": interface_size,
                    "corner_size_mm": corner_size,
                    "far_field_size_mm": far_size,
                    "sizing_policy": "linear_halbach_tag_driven_v1",
                    "sizing_keys": sorted(feature_physical_groups),
                },
                mesh_qa={
                    "all_triangles_mapped_once": True,
                    "region_triangle_counts": region_counts,
                    "triangle_area_by_region_mm2": (
                        triangle_area_by_region
                    ),
                    "total_mesh_area_mm2": total_mesh_area,
                    "expected_domain_area_mm2": expected_area,
                    "area_relative_error": area_relative_error,
                    "minimum_triangle_area_mm2": min(areas),
                    "minimum_triangle_quality": min(qualities),
                    "mean_triangle_quality": (
                        sum(qualities) / len(qualities)
                    ),
                    "physical_group_count": len(physical_groups),
                    "feature_group_count": len(feature_physical_groups),
                },
                mesh_hash=_canonical_hash(mesh_identity),
                gmsh_time_ms=(mesh_finished - started) * 1000.0,
                cad_time_ms=(cad_finished - started) * 1000.0,
                mesh_generation_time_ms=(
                    mesh_finished - cad_finished
                )
                * 1000.0,
            )
        finally:
            gmsh.finalize()


def build_linear_magnetostatic_problem(
    config: LinearHalbachArrayConfig,
    geometry: LinearPlanarGeometryArtifact,
    mesh: LinearHalbachMeshArtifact,
    *,
    magnet_mu_r: float,
) -> tuple[dict[str, Any], str]:
    """Lower the mesh to the unchanged generic field-problem v1 contract."""

    regions: dict[str, LinearPlanarRegion] = {
        region.id: region for region in geometry.regions
    }
    elements: list[dict[str, Any]] = []
    for region_id in mesh.element_region_ids:
        region = regions.get(region_id)
        if region is None:
            raise LinearHalbachMeshError(
                f"mesh references unknown physical region {region_id!r}"
            )
        if region.kind == "permanent_magnet":
            if region.magnetization_xy is None:
                raise LinearHalbachMeshError(
                    f"permanent-magnet region {region_id!r} lacks remanence"
                )
            elements.append(
                {
                    "material_id": 1,
                    "current_density_z_a_per_m2": 0.0,
                    "remanence_t": list(region.magnetization_xy),
                    "pm_source_scale": 1.0,
                }
            )
        else:
            elements.append(
                {
                    "material_id": 0,
                    "current_density_z_a_per_m2": 0.0,
                    "remanence_t": [0.0, 0.0],
                    "pm_source_scale": 1.0,
                }
            )
    problem = {
        "kind": "magnetostatic_problem",
        "version": "1.0",
        "units": {"length": "mm"},
        "mesh": {
            "nodes": [list(node) for node in mesh.nodes_mm],
            "triangles": [list(triangle) for triangle in mesh.triangles],
        },
        "materials": [
            {"kind": "linear", "mu_r": 1.0},
            {"kind": "linear", "mu_r": magnet_mu_r},
        ],
        "elements": elements,
        "boundaries": {
            "dirichlet_az_zero_nodes": list(mesh.outer_boundary_nodes),
            "paired_nodes": [],
            "periodic_penalty": 10_000_000_000.0,
        },
        "options": {
            "linear": {
                "solver": config.solve.linear.solver,
                "pcg_preconditioner": (
                    config.solve.linear.pcg_preconditioner
                ),
                "pcg_parallel": False,
                "pcg_residual_check_interval": 8,
                "tolerance": config.solve.linear.tolerance,
                "max_iterations": config.solve.linear.max_iterations,
            }
        },
    }
    return problem, _canonical_hash(problem)
