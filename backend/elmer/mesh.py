"""Deterministic Gmsh 2.2 export and ElmerGrid conversion validation."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import ElmerMeshConversionError, ElmerMeshExportError

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")
_MESH_NAME_RE = re.compile(r"^\s*\$?\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(\d+)\s*$")


@dataclass(frozen=True)
class ElmerMeshManifest:
    schema_version: str
    gmsh_path: str
    length_units: str
    node_count: int
    triangle_count: int
    boundary_element_count: int
    region_physical_ids: dict[str, int]
    region_physical_names: dict[str, str]
    outer_boundary_physical_id: int
    outer_boundary_physical_name: str

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    clean = _SAFE_NAME_RE.sub("_", value).strip("_")
    if not clean:
        raise ElmerMeshExportError(f"Physical name {value!r} has no safe characters")
    return clean


def _outer_boundary_edges(
    triangles: list[list[int]],
    boundary_nodes: list[int],
) -> list[tuple[int, int]]:
    boundary_set = {int(index) for index in boundary_nodes}
    counts: Counter[tuple[int, int]] = Counter()
    for triangle in triangles:
        if len(triangle) != 3:
            raise ElmerMeshExportError("Only first-order triangles are supported")
        a, b, c = (int(index) for index in triangle)
        for left, right in ((a, b), (b, c), (c, a)):
            edge = (left, right) if left <= right else (right, left)
            counts[edge] += 1
    return sorted(
        edge
        for edge, count in counts.items()
        if count == 1 and edge[0] in boundary_set and edge[1] in boundary_set
    )


def _airgap_radial_layer_counts(
    *,
    nodes: list[list[float]],
    triangles: list[list[int]],
    element_region_ids: list[object],
    airgap_ids: set[str],
    inner_radius_mm: float,
    outer_radius_mm: float,
    ray_count: int = 96,
) -> tuple[int, int]:
    """Return conservative topology- and ray-based air-gap layer counts.

    The topology count is the shortest element path from the inner to outer
    air-gap boundary. The ray count is the minimum number of mesh-edge
    intervals crossed by a deterministic set of radial probes. Taking the
    lower value prevents a dense patch elsewhere in the annulus from hiding a
    locally under-resolved air gap.
    """

    airgap_triangles: list[tuple[int, int, int]] = []
    for raw_triangle, region_id in zip(triangles, element_region_ids, strict=True):
        if str(region_id) not in airgap_ids:
            continue
        if len(raw_triangle) != 3:
            raise ElmerMeshExportError("Only first-order triangles are supported")
        indices = (
            int(raw_triangle[0]),
            int(raw_triangle[1]),
            int(raw_triangle[2]),
        )
        if any(index < 0 or index >= len(nodes) for index in indices):
            raise ElmerMeshExportError("Airgap triangle references an unavailable node")
        airgap_triangles.append(indices)
    if not airgap_triangles:
        raise ElmerMeshExportError("Airgap mesh is unavailable for radial-layer validation")

    airgap_node_ids = {node_id for triangle in airgap_triangles for node_id in triangle}
    radii = {
        node_id: math.hypot(float(nodes[node_id][0]), float(nodes[node_id][1]))
        for node_id in airgap_node_ids
    }
    thickness = outer_radius_mm - inner_radius_mm
    boundary_tolerance = max(thickness * 1.0e-4, 1.0e-7)
    inner_nodes = {
        node_id
        for node_id, radius in radii.items()
        if abs(radius - inner_radius_mm) <= boundary_tolerance
    }
    outer_nodes = {
        node_id
        for node_id, radius in radii.items()
        if abs(radius - outer_radius_mm) <= boundary_tolerance
    }
    if not inner_nodes or not outer_nodes:
        raise ElmerMeshExportError(
            "Airgap topology does not reach both declared radial boundaries"
        )

    edge_owners: dict[tuple[int, int], list[int]] = {}
    inner_triangles: list[int] = []
    outer_triangles: set[int] = set()
    for triangle_index, airgap_triangle in enumerate(airgap_triangles):
        triangle_nodes = set(airgap_triangle)
        if triangle_nodes.intersection(inner_nodes):
            inner_triangles.append(triangle_index)
        if triangle_nodes.intersection(outer_nodes):
            outer_triangles.add(triangle_index)
        a, b, c = airgap_triangle
        for left, right in ((a, b), (b, c), (c, a)):
            edge = (left, right) if left <= right else (right, left)
            edge_owners.setdefault(edge, []).append(triangle_index)

    adjacency: list[set[int]] = [set() for _ in airgap_triangles]
    for owners in edge_owners.values():
        if len(owners) == 2:
            left, right = owners
            adjacency[left].add(right)
            adjacency[right].add(left)
    queue = deque((triangle_index, 1) for triangle_index in inner_triangles)
    visited = set(inner_triangles)
    topology_layers: int | None = None
    while queue:
        triangle_index, distance = queue.popleft()
        if triangle_index in outer_triangles:
            topology_layers = distance
            break
        for neighbor in adjacency[triangle_index]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))
    if topology_layers is None:
        raise ElmerMeshExportError(
            "Airgap topology has no connected inner-to-outer element path"
        )

    edge_points = [
        (
            (float(nodes[left][0]), float(nodes[left][1])),
            (float(nodes[right][0]), float(nodes[right][1])),
        )
        for left, right in edge_owners
    ]
    intersection_tolerance = max(thickness * 1.0e-7, 1.0e-9)
    ray_layers: list[int] = []
    for ray_index in range(ray_count):
        angle = 2.0 * math.pi * (ray_index + 0.371) / ray_count
        dx, dy = math.cos(angle), math.sin(angle)
        intersections: list[float] = []
        for (px, py), (qx, qy) in edge_points:
            ex, ey = qx - px, qy - py
            denominator = ex * dy - ey * dx
            if abs(denominator) <= 1.0e-14:
                continue
            fraction = -(px * dy - py * dx) / denominator
            if fraction < -1.0e-10 or fraction > 1.0 + 1.0e-10:
                continue
            x = px + fraction * ex
            y = py + fraction * ey
            radial_distance = x * dx + y * dy
            if radial_distance > 0.0:
                intersections.append(radial_distance)
        intersections.sort()
        unique_intersections: list[float] = []
        for radial_distance in intersections:
            if (
                not unique_intersections
                or radial_distance - unique_intersections[-1] > intersection_tolerance
            ):
                unique_intersections.append(radial_distance)
        if len(unique_intersections) >= 2:
            ray_layers.append(len(unique_intersections) - 1)
    if len(ray_layers) < ray_count:
        raise ElmerMeshExportError(
            "Airgap radial probes do not all cross a connected annular mesh"
        )
    return topology_layers, min(ray_layers)


def write_gmsh22(
    solve_mesh_artifact: dict[str, Any],
    path: str | Path,
    *,
    expected_rotor_angle_mech_deg: float | None = None,
    minimum_airgap_radial_layers: int = 0,
) -> ElmerMeshManifest:
    """Write a canonical solve artifact as deterministic SI Gmsh 2.2 ASCII."""

    target = Path(path)
    mesh = solve_mesh_artifact.get("mesh") or {}
    nodes = mesh.get("nodes") or []
    triangles = mesh.get("triangles") or []
    element_region_ids = solve_mesh_artifact.get("element_region_ids") or []
    if not nodes or not triangles:
        raise ElmerMeshExportError("Solve mesh artifact has no nodes or triangles")
    if len(triangles) != len(element_region_ids):
        raise ElmerMeshExportError("Triangle and element_region_ids counts differ")
    if mesh.get("length_units") not in {None, "mm"}:
        raise ElmerMeshExportError(
            f"Expected millimetre source mesh, got {mesh.get('length_units')!r}"
        )
    if expected_rotor_angle_mech_deg is not None:
        actual_angle = solve_mesh_artifact.get("rotor_angle_mech_deg")
        if actual_angle is None or not math.isclose(
            float(actual_angle),
            float(expected_rotor_angle_mech_deg),
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ElmerMeshExportError(
                "Solve mesh rotor angle is stale: "
                f"expected {expected_rotor_angle_mech_deg:g} deg, got {actual_angle!r}"
            )

    contract_regions = ((solve_mesh_artifact.get("physics_contract") or {}).get("regions") or [])
    contract_ids = [str(region.get("id")) for region in contract_regions if region.get("id")]
    used_ids = {str(region_id) for region_id in element_region_ids}
    missing_contract = used_ids.difference(contract_ids)
    if missing_contract:
        raise ElmerMeshExportError(
            f"Element regions are absent from the physics contract: {sorted(missing_contract)}"
        )
    ordered_ids = [region_id for region_id in contract_ids if region_id in used_ids]
    if minimum_airgap_radial_layers > 0:
        airgap_ids = {
            str(region["id"])
            for region in contract_regions
            if (region.get("geometry_ir_kind") or region.get("kind")) == "Airgap"
        }
        info = mesh.get("info") or {}
        inner = float(info.get("airgap_inner_radius_mm", 0.0))
        outer = float(info.get("airgap_outer_radius_mm", 0.0))
        if not 0.0 < inner < outer:
            raise ElmerMeshExportError("Airgap mesh/radii are unavailable for radial-layer validation")
        topology_layers, ray_layers = _airgap_radial_layer_counts(
            nodes=nodes,
            triangles=triangles,
            element_region_ids=element_region_ids,
            airgap_ids=airgap_ids,
            inner_radius_mm=inner,
            outer_radius_mm=outer,
        )
        observed_layers = min(topology_layers, ray_layers)
        if observed_layers < minimum_airgap_radial_layers:
            raise ElmerMeshExportError(
                "Airgap has fewer than "
                f"{minimum_airgap_radial_layers} radial element layers "
                f"(topology={topology_layers}, ray={ray_layers})"
            )
    region_physical_ids = {region_id: index + 100 for index, region_id in enumerate(ordered_ids)}
    region_physical_names = {
        region_id: f"body_{index + 1:04d}_{_slug(region_id)}"
        for index, region_id in enumerate(ordered_ids)
    }
    outer_boundary_name = "outer_boundary"
    outer_boundary_id = 1
    boundary_edges = _outer_boundary_edges(triangles, mesh.get("boundary_nodes") or [])
    if len(boundary_edges) < 3:
        raise ElmerMeshExportError(
            f"Outer boundary produced only {len(boundary_edges)} line elements"
        )

    lines = [
        "$MeshFormat",
        "2.2 0 8",
        "$EndMeshFormat",
        "$PhysicalNames",
        str(len(ordered_ids) + 1),
        f'1 {outer_boundary_id} "{outer_boundary_name}"',
    ]
    lines.extend(
        f'2 {region_physical_ids[region_id]} "{region_physical_names[region_id]}"'
        for region_id in ordered_ids
    )
    lines.extend(("$EndPhysicalNames", "$Nodes", str(len(nodes))))
    for index, point in enumerate(nodes, start=1):
        if len(point) < 2:
            raise ElmerMeshExportError(f"Node {index - 1} has fewer than two coordinates")
        x_m = float(point[0]) * 1.0e-3
        y_m = float(point[1]) * 1.0e-3
        if not math.isfinite(x_m) or not math.isfinite(y_m):
            raise ElmerMeshExportError(f"Node {index - 1} is non-finite")
        lines.append(f"{index} {x_m:.17e} {y_m:.17e} 0.00000000000000000e+00")
    lines.extend(("$EndNodes", "$Elements", str(len(boundary_edges) + len(triangles))))
    element_id = 1
    for left, right in boundary_edges:
        lines.append(
            f"{element_id} 1 2 {outer_boundary_id} {outer_boundary_id} {left + 1} {right + 1}"
        )
        element_id += 1
    for triangle, region_id in zip(triangles, element_region_ids, strict=True):
        physical_id = region_physical_ids[str(region_id)]
        a, b, c = (int(index) + 1 for index in triangle)
        lines.append(f"{element_id} 2 2 {physical_id} {physical_id} {a} {b} {c}")
        element_id += 1
    lines.extend(("$EndElements", ""))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")

    manifest = ElmerMeshManifest(
        schema_version="openem.elmer_mesh_manifest/v1",
        gmsh_path=str(target),
        length_units="m",
        node_count=len(nodes),
        triangle_count=len(triangles),
        boundary_element_count=len(boundary_edges),
        region_physical_ids=region_physical_ids,
        region_physical_names=region_physical_names,
        outer_boundary_physical_id=outer_boundary_id,
        outer_boundary_physical_name=outer_boundary_name,
    )
    manifest.write(target.with_suffix(".manifest.json"))
    return manifest


def parse_mesh_names(path: str | Path) -> dict[str, int]:
    """Parse ElmerGrid's post-conversion logical name assignments."""

    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ElmerMeshConversionError(f"Could not read {source}: {exc}") from exc
    names: dict[str, int] = {}
    for line in lines:
        match = _MESH_NAME_RE.match(line)
        if match:
            names[match.group(1)] = int(match.group(2))
    if not names:
        raise ElmerMeshConversionError(f"No logical entity names found in {source}")
    return names


def validate_converted_mesh(
    mesh_dir: str | Path,
    manifest: ElmerMeshManifest,
) -> dict[str, int]:
    """Require complete Elmer native files and resolve every converted name."""

    root = Path(mesh_dir)
    required = ("mesh.header", "mesh.nodes", "mesh.elements", "mesh.boundary", "mesh.names")
    missing = [name for name in required if not (root / name).is_file() or (root / name).stat().st_size == 0]
    if missing:
        raise ElmerMeshConversionError(
            f"Converted mesh is incomplete under {root}: {', '.join(missing)}"
        )
    names = parse_mesh_names(root / "mesh.names")
    expected = [manifest.outer_boundary_physical_name, *manifest.region_physical_names.values()]
    absent = [name for name in expected if name not in names]
    if absent:
        raise ElmerMeshConversionError(
            f"ElmerGrid lost required physical names: {', '.join(absent)}"
        )
    try:
        header = [int(value) for value in (root / "mesh.header").read_text(encoding="utf-8").splitlines()[0].split()]
    except (OSError, ValueError, IndexError) as exc:
        raise ElmerMeshConversionError(f"Invalid Elmer mesh header under {root}") from exc
    if len(header) < 3:
        raise ElmerMeshConversionError(f"Elmer mesh header under {root} has fewer than three counts")
    node_count, triangle_count, boundary_count = header[:3]
    expected_counts = (manifest.node_count, manifest.triangle_count, manifest.boundary_element_count)
    actual_counts = (node_count, triangle_count, boundary_count)
    if actual_counts != expected_counts:
        raise ElmerMeshConversionError(
            "ElmerGrid changed mesh counts: "
            f"expected nodes/elements/boundaries={expected_counts}, got {actual_counts}"
        )
    expected_body_ids = {names[name] for name in manifest.region_physical_names.values()}
    try:
        actual_body_ids = {
            int(line.split()[1])
            for line in (root / "mesh.elements").read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except (OSError, ValueError, IndexError) as exc:
        raise ElmerMeshConversionError(f"Invalid Elmer element inventory under {root}") from exc
    orphan_body_ids = actual_body_ids.difference(expected_body_ids)
    missing_body_ids = expected_body_ids.difference(actual_body_ids)
    if orphan_body_ids or missing_body_ids:
        raise ElmerMeshConversionError(
            "Elmer body inventory differs from the canonical mesh: "
            f"orphan={sorted(orphan_body_ids)}, missing={sorted(missing_body_ids)}"
        )
    return names
