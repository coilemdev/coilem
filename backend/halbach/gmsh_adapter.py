"""Schedule-safe, tag-driven Gmsh lowering for the Halbach application."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from backend.gmsh_solver import _GMSH_API_LOCK, GMSH_AVAILABLE, gmsh
from backend.solver_environment import ISOLATED_RUNTIME

from .geometry import PlanarEmGeometryArtifact, PlanarRegion
from .models import HalbachArrayConfig


class HalbachMeshError(ValueError):
    """A Halbach geometry could not be lowered to a complete conforming mesh."""


@dataclass(frozen=True)
class HalbachMeshArtifact:
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
            "kind": "halbach_mesh_preview",
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


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize a retained solver artifact exactly as its identity is hashed."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _triangle_quality(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> tuple[float, float]:
    twice_area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    area = 0.5 * abs(twice_area)
    lengths2 = (
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2,
        (b[0] - c[0]) ** 2 + (b[1] - c[1]) ** 2,
        (c[0] - a[0]) ** 2 + (c[1] - a[1]) ** 2,
    )
    denominator = sum(lengths2)
    quality = 0.0 if denominator <= 0.0 else 4.0 * math.sqrt(3.0) * area / denominator
    return area, quality


class _PlanarCadBuilder:
    def __init__(self, *, characteristic_length_mm: float) -> None:
        self.characteristic_length_mm = characteristic_length_mm
        self.center = gmsh.model.geo.addPoint(
            0.0, 0.0, 0.0, characteristic_length_mm
        )
        self._points: dict[tuple[int, int], int] = {}
        self._point_sizes: dict[int, float] = {}
        self._lines: dict[tuple[int, int], int] = {}
        self._arcs: dict[tuple[int, int, int], int] = {}

    def point(self, radius_mm: float, angle_deg: float, size_mm: float) -> int:
        radians = math.radians(angle_deg)
        x = radius_mm * math.cos(radians)
        y = radius_mm * math.sin(radians)
        key = (round(x * 1.0e9), round(y * 1.0e9))
        existing = self._points.get(key)
        if existing is not None:
            self._point_sizes[existing] = min(self._point_sizes[existing], size_mm)
            return existing
        tag = gmsh.model.geo.addPoint(x, y, 0.0, size_mm)
        self._points[key] = tag
        self._point_sizes[tag] = size_mm
        return tag

    def line(self, start: int, end: int) -> int:
        key = (start, end)
        if key in self._lines:
            return self._lines[key]
        reverse = (end, start)
        if reverse in self._lines:
            return -self._lines[reverse]
        tag = gmsh.model.geo.addLine(start, end)
        self._lines[key] = tag
        return tag

    def arc(self, start: int, end: int) -> int:
        key = (start, self.center, end)
        if key in self._arcs:
            return self._arcs[key]
        reverse = (end, self.center, start)
        if reverse in self._arcs:
            return -self._arcs[reverse]
        tag = gmsh.model.geo.addCircleArc(start, self.center, end)
        self._arcs[key] = tag
        return tag

    @property
    def point_sizes(self) -> dict[int, float]:
        return self._point_sizes


def _ordered_annular_regions(
    geometry: PlanarEmGeometryArtifact,
) -> list[PlanarRegion]:
    wedges = [
        region
        for region in geometry.regions
        if region.start_angle_deg is not None and region.end_angle_deg is not None
    ]
    if not wedges:
        raise HalbachMeshError("Halbach geometry contains no annular regions")
    return wedges


def generate_halbach_mesh(
    config: HalbachArrayConfig,
    geometry: PlanarEmGeometryArtifact,
) -> HalbachMeshArtifact:
    if not GMSH_AVAILABLE or gmsh is None:
        raise RuntimeError(
            "Gmsh is required for Halbach meshing. Install the pinned gmsh Python package."
        )
    started = time.perf_counter()
    with _GMSH_API_LOCK:
        # FastAPI executes synchronous mesh routes in a worker thread.  Gmsh's
        # default initializer installs a SIGINT handler, which Python permits
        # only on the main thread; the shared motor adapter uses the same
        # non-interruptible mode for this reason.
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            # Delaunay is substantially more robust than Frontal-Delaunay for
            # the long, narrow air wedges created by small manufacturing gaps.
            gmsh.option.setNumber("Mesh.Algorithm", 5)
            gmsh.option.setNumber("Mesh.Optimize", 0)
            gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 1)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
            gmsh.model.add("halbach_array_v1")

            thickness = geometry.outer_radius_mm - geometry.inner_radius_mm
            density_factor = {
                # Density may refine the requested radial minimum but must
                # never coarsen below minimum_elements_across_magnet.
                "coarse": 1.0,
                "normal": 1.0,
                "fine": 0.65,
            }[config.solve.mesh.density]
            interface_size = (
                thickness
                / config.solve.mesh.minimum_elements_across_magnet
                * density_factor
            )
            corner_size = (
                interface_size * 0.55
                if config.solve.mesh.corner_refinement
                else interface_size
            )
            far_size = min(
                geometry.outer_boundary_radius_mm / 8.0,
                max(interface_size * 5.0, geometry.outer_radius_mm / 8.0),
            )
            builder = _PlanarCadBuilder(characteristic_length_mm=far_size)
            annular_regions = _ordered_annular_regions(geometry)
            surface_by_region: dict[str, int] = {}
            inner_arcs: list[int] = []
            outer_arcs: list[int] = []
            magnet_outer_arcs: set[int] = set()
            magnet_radial_lines: set[int] = set()
            gap_surfaces: set[int] = set()
            gap_transfinite: list[tuple[int, int, int, int, int]] = []

            for region in annular_regions:
                assert region.start_angle_deg is not None
                assert region.end_angle_deg is not None
                is_gap = region.kind == "gap_air"
                radial_size = interface_size
                if is_gap:
                    gap_width = geometry.inner_radius_mm * math.radians(
                        region.end_angle_deg - region.start_angle_deg
                    )
                    if gap_width <= 1.0e-4:
                        raise HalbachMeshError(
                            f"{region.id} is a numerical sliver ({gap_width:g} mm at the bore)"
                        )
                    # Resolve the two gap faces without propagating a
                    # sub-millimetre isotropic point size through the entire
                    # radial magnet thickness.  The narrow angular width is
                    # represented by the conforming curves themselves; this
                    # bounded floor prevents a valid manufacturing clearance
                    # from exploding the global triangle budget.
                    radial_size = max(
                        interface_size * 0.4,
                        min(interface_size, gap_width * 2.0),
                    )
                start_inner = builder.point(
                    geometry.inner_radius_mm,
                    region.start_angle_deg,
                    min(corner_size, radial_size),
                )
                end_inner = builder.point(
                    geometry.inner_radius_mm,
                    region.end_angle_deg,
                    min(corner_size, radial_size),
                )
                start_outer = builder.point(
                    geometry.outer_radius_mm,
                    region.start_angle_deg,
                    min(corner_size, radial_size),
                )
                end_outer = builder.point(
                    geometry.outer_radius_mm,
                    region.end_angle_deg,
                    min(corner_size, radial_size),
                )
                inner_arc = builder.arc(start_inner, end_inner)
                outer_arc = builder.arc(start_outer, end_outer)
                radial_start = builder.line(start_inner, start_outer)
                radial_end = builder.line(end_inner, end_outer)
                loop = gmsh.model.geo.addCurveLoop(
                    [outer_arc, -radial_end, -inner_arc, radial_start]
                )
                surface = gmsh.model.geo.addPlaneSurface([loop])
                surface_by_region[region.id] = surface
                inner_arcs.append(inner_arc)
                outer_arcs.append(outer_arc)
                if region.kind == "permanent_magnet":
                    magnet_outer_arcs.add(abs(outer_arc))
                    magnet_radial_lines.update((abs(radial_start), abs(radial_end)))
                elif region.kind == "gap_air":
                    gap_surfaces.add(surface)
                    gap_transfinite.append(
                        (
                            surface,
                            abs(inner_arc),
                            abs(outer_arc),
                            abs(radial_start),
                            abs(radial_end),
                        )
                    )

            bore_loop = gmsh.model.geo.addCurveLoop(inner_arcs)
            surface_by_region["bore_air"] = gmsh.model.geo.addPlaneSurface([bore_loop])

            outer_boundary_arcs: list[int] = []
            outer_boundary_points: list[int] = []
            for start_deg, end_deg in ((0.0, 90.0), (90.0, 180.0), (180.0, 270.0), (270.0, 360.0)):
                start = builder.point(
                    geometry.outer_boundary_radius_mm, start_deg, far_size
                )
                end = builder.point(
                    geometry.outer_boundary_radius_mm, end_deg, far_size
                )
                outer_boundary_points.extend((start, end))
                outer_boundary_arcs.append(builder.arc(start, end))
            exterior_outer_loop = gmsh.model.geo.addCurveLoop(outer_boundary_arcs)
            exterior_inner_loop = gmsh.model.geo.addCurveLoop(outer_arcs)
            surface_by_region["exterior_air"] = gmsh.model.geo.addPlaneSurface(
                [exterior_outer_loop, exterior_inner_loop]
            )
            gmsh.model.geo.synchronize()

            for point_tag, size in builder.point_sizes.items():
                gmsh.model.mesh.setSize([(0, point_tag)], size)
            radial_divisions = max(
                2,
                int(
                    math.ceil(
                        thickness
                        / max(interface_size, 1.0e-9)
                    )
                )
                + 1,
            )
            for (
                surface,
                inner_arc,
                outer_arc,
                radial_start,
                radial_end,
            ) in gap_transfinite:
                # A one-element angular strip is intentional: the gap is a
                # real conforming air region, while a transfinite strip avoids
                # asking an isotropic unstructured mesher to chase aspect
                # ratio in a long sub-degree wedge.
                gmsh.model.mesh.setTransfiniteCurve(inner_arc, 2)
                gmsh.model.mesh.setTransfiniteCurve(outer_arc, 2)
                gmsh.model.mesh.setTransfiniteCurve(
                    radial_start, radial_divisions
                )
                gmsh.model.mesh.setTransfiniteCurve(
                    radial_end, radial_divisions
                )
                gmsh.model.mesh.setTransfiniteSurface(surface)

            physical_group_tags: dict[str, int] = {}
            for region in geometry.regions:
                surface = surface_by_region.get(region.id)
                if surface is None:
                    raise HalbachMeshError(
                        f"missing Gmsh surface for physical region {region.id}"
                    )
                physical_tag = gmsh.model.addPhysicalGroup(2, [surface])
                gmsh.model.setPhysicalName(2, physical_tag, f"region::{region.id}")
                physical_group_tags[region.id] = physical_tag

            outer_boundary_group = gmsh.model.addPhysicalGroup(
                1, sorted(set(map(abs, outer_boundary_arcs)))
            )
            gmsh.model.setPhysicalName(
                1, outer_boundary_group, "boundary::az_zero"
            )

            feature_entities: dict[str, tuple[int, set[int]]] = {
                "bore_roi_boundary": (1, set(map(abs, inner_arcs))),
                "critical_curve": (
                    1,
                    set(map(abs, inner_arcs)) | set(map(abs, magnet_outer_arcs)),
                ),
                "material_interface": (
                    1,
                    set(map(abs, inner_arcs))
                    | set(map(abs, outer_arcs))
                    | magnet_radial_lines,
                ),
                "permanent_magnet_edge": (1, magnet_radial_lines),
                "critical_corner": (1, magnet_radial_lines),
                "critical_gap": (2, gap_surfaces),
                "far_field": (
                    1,
                    set(map(abs, outer_boundary_arcs)),
                ),
                "dirichlet_boundary": (
                    1,
                    set(map(abs, outer_boundary_arcs)),
                ),
            }
            feature_group_tags: dict[str, tuple[int, int]] = {}
            for feature, (dimension, entities) in feature_entities.items():
                if not entities:
                    continue
                tag = gmsh.model.addPhysicalGroup(dimension, sorted(entities))
                gmsh.model.setPhysicalName(dimension, tag, f"feature::{feature}")
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
                tag: index for index, (tag, _coordinate) in enumerate(node_records)
            }
            nodes = tuple(coordinate for _tag, coordinate in node_records)

            element_records: list[tuple[int, tuple[int, int, int], str]] = []
            seen_element_tags: set[int] = set()
            for region_id, surface in surface_by_region.items():
                element_types, element_tag_blocks, node_tag_blocks = (
                    gmsh.model.mesh.getElements(2, surface)
                )
                for element_type, element_tags, connectivity in zip(
                    element_types, element_tag_blocks, node_tag_blocks
                ):
                    _name, _dim, _order, node_count, _local, _primary = (
                        gmsh.model.mesh.getElementProperties(element_type)
                    )
                    if int(node_count) != 3:
                        raise HalbachMeshError(
                            f"unexpected non-P1 triangle element type {element_type}"
                        )
                    for offset, element_tag in enumerate(element_tags):
                        tag = int(element_tag)
                        if tag in seen_element_tags:
                            raise HalbachMeshError(
                                f"triangle {tag} appears in more than one physical region"
                            )
                        seen_element_tags.add(tag)
                        raw_nodes = connectivity[offset * 3 : offset * 3 + 3]
                        try:
                            triangle = (
                                node_index[int(raw_nodes[0])],
                                node_index[int(raw_nodes[1])],
                                node_index[int(raw_nodes[2])],
                            )
                        except KeyError as exc:
                            raise HalbachMeshError(
                                f"triangle {tag} references an unknown node"
                            ) from exc
                        element_records.append((tag, triangle, region_id))

            all_types, all_tag_blocks, _ = gmsh.model.mesh.getElements(2)
            all_triangle_tags = {
                int(tag)
                for element_type, tags in zip(all_types, all_tag_blocks)
                if int(gmsh.model.mesh.getElementProperties(element_type)[3]) == 3
                for tag in tags
            }
            if seen_element_tags != all_triangle_tags:
                missing = sorted(all_triangle_tags - seen_element_tags)
                duplicate_or_unknown = sorted(seen_element_tags - all_triangle_tags)
                raise HalbachMeshError(
                    "triangle-to-region mapping is incomplete: "
                    f"missing={missing[:8]}, unknown={duplicate_or_unknown[:8]}"
                )
            element_records.sort(key=lambda record: record[0])
            triangles = tuple(record[1] for record in element_records)
            element_region_ids = tuple(record[2] for record in element_records)

            boundary_node_tags, _boundary_coordinates = (
                gmsh.model.mesh.getNodesForPhysicalGroup(1, outer_boundary_group)
            )
            outer_boundary_nodes = tuple(
                sorted({node_index[int(tag)] for tag in boundary_node_tags})
            )
            if not outer_boundary_nodes:
                raise HalbachMeshError("outer az_zero physical group has no mesh nodes")

            region_counts: dict[str, int] = {}
            areas: list[float] = []
            qualities: list[float] = []
            triangle_area_by_region: dict[str, float] = {}
            for triangle, region_id in zip(triangles, element_region_ids):
                area, quality = _triangle_quality(
                    nodes[triangle[0]], nodes[triangle[1]], nodes[triangle[2]]
                )
                if area <= 1.0e-14 or quality <= 0.0:
                    raise HalbachMeshError(
                        f"degenerate triangle mapped to region {region_id}"
                    )
                areas.append(area)
                qualities.append(quality)
                region_counts[region_id] = region_counts.get(region_id, 0) + 1
                triangle_area_by_region[region_id] = (
                    triangle_area_by_region.get(region_id, 0.0) + area
                )
            missing_regions = sorted(
                region.id for region in geometry.regions if region_counts.get(region.id, 0) == 0
            )
            if missing_regions:
                raise HalbachMeshError(
                    f"physical regions contain no triangles: {missing_regions}"
                )
            total_mesh_area = sum(areas)
            expected_area = math.pi * geometry.outer_boundary_radius_mm**2
            area_relative_error = abs(total_mesh_area - expected_area) / expected_area
            if area_relative_error > 2.5e-3:
                raise HalbachMeshError(
                    "mesh area closure exceeds tolerance: "
                    f"{area_relative_error:.3%}"
                )

            physical_groups = {
                region_id: {
                    "dimension": 2,
                    "tag": tag,
                    "name": f"region::{region_id}",
                    "entity_tags": [surface_by_region[region_id]],
                    "triangle_count": region_counts[region_id],
                }
                for region_id, tag in physical_group_tags.items()
            }
            physical_groups["az_zero"] = {
                "dimension": 1,
                "tag": outer_boundary_group,
                "name": "boundary::az_zero",
                "entity_tags": sorted(set(map(abs, outer_boundary_arcs))),
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
            gmsh_version = getattr(gmsh, "__version__", "unknown")
            return HalbachMeshArtifact(
                nodes_mm=nodes,
                triangles=triangles,
                element_region_ids=element_region_ids,
                outer_boundary_nodes=outer_boundary_nodes,
                physical_groups=physical_groups,
                feature_physical_groups=feature_physical_groups,
                mesh_info={
                    "mesh_source": "gmsh",
                    "gmsh_version": gmsh_version,
                    "num_nodes": len(nodes),
                    "num_triangles": len(triangles),
                    "mesh_density": config.solve.mesh.density,
                    "minimum_elements_across_magnet": (
                        config.solve.mesh.minimum_elements_across_magnet
                    ),
                    "corner_refinement": config.solve.mesh.corner_refinement,
                    "outer_boundary_radius_mm": geometry.outer_boundary_radius_mm,
                    "interface_size_mm": interface_size,
                    "corner_size_mm": corner_size,
                    "far_field_size_mm": far_size,
                    "sizing_policy": "halbach_tag_driven_v1",
                    "sizing_keys": sorted(feature_physical_groups),
                },
                mesh_qa={
                    "all_triangles_mapped_once": True,
                    "region_triangle_counts": region_counts,
                    "triangle_area_by_region_mm2": triangle_area_by_region,
                    "total_mesh_area_mm2": total_mesh_area,
                    "expected_domain_area_mm2": expected_area,
                    "area_relative_error": area_relative_error,
                    "minimum_triangle_area_mm2": min(areas),
                    "minimum_triangle_quality": min(qualities),
                    "mean_triangle_quality": sum(qualities) / len(qualities),
                    "physical_group_count": len(physical_groups),
                    "feature_group_count": len(feature_physical_groups),
                },
                mesh_hash=_canonical_hash(mesh_identity),
                gmsh_time_ms=(mesh_finished - started) * 1000.0,
                cad_time_ms=(cad_finished - started) * 1000.0,
                mesh_generation_time_ms=(mesh_finished - cad_finished) * 1000.0,
            )
        finally:
            gmsh.finalize()


def build_magnetostatic_problem(
    config: HalbachArrayConfig,
    geometry: PlanarEmGeometryArtifact,
    mesh: HalbachMeshArtifact,
    *,
    magnet_mu_r: float,
) -> tuple[dict[str, Any], str]:
    """Freeze the downstream application-neutral field-problem boundary."""

    regions = {region.id: region for region in geometry.regions}
    elements: list[dict[str, Any]] = []
    for region_id in mesh.element_region_ids:
        region = regions.get(region_id)
        if region is None:
            raise HalbachMeshError(
                f"mesh references unknown physical region {region_id!r}"
            )
        if region.kind == "permanent_magnet":
            if region.magnetization_xy is None:
                raise HalbachMeshError(
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
                "pcg_preconditioner": config.solve.linear.pcg_preconditioner,
                "pcg_parallel": False,
                "pcg_residual_check_interval": 8,
                "tolerance": config.solve.linear.tolerance,
                "max_iterations": config.solve.linear.max_iterations,
            }
        },
    }
    return problem, _canonical_hash(problem)
