"""Parse Elmer scalar and VTU outputs into solver-neutral position fields."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.field_lines import generate_element_b_components
from backend.mesh_evidence import build_solve_mesh_evidence
from backend.models import MotorConfig
from backend.winding_utils import flux_linkage_slot_side_turn_factor

from .case import ElmerCaseManifest
from .errors import ElmerNonConvergenceError, ElmerResultParseError

_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_TORQUE_RE = re.compile(rf"Air\s+gap\s+torque\s*:\s*({_FLOAT})", re.IGNORECASE)
_NODAL_TORQUE_RE = re.compile(
    rf"Magnetic\s+torque\s+reduced\s*:.*?:\s*({_FLOAT})",
    re.IGNORECASE,
)
_NONCONVERGENCE = re.compile(r"not\s+converged|failed\s+convergence|diverg", re.IGNORECASE)


@dataclass(frozen=True)
class ElmerPositionResult:
    torque_nm: float
    torque_per_length_n: float
    nodal_force_torque_nm: float | None
    nodes_mm: list[list[float]]
    triangles: list[list[int]]
    regions: list[str]
    element_region_ids: list[str]
    az_nodal: list[float]
    element_bx_t: list[float]
    element_by_t: list[float]
    element_b_magnitude_t: list[float]
    nodal_b_magnitude_t: list[float]
    flux_linkage_a_wb: float
    flux_linkage_b_wb: float
    flux_linkage_c_wb: float
    slot_flux_linkage_contributions: list[dict[str, Any]]
    peak_b_tooth_t: float
    peak_b_yoke_t: float
    solve_mesh_evidence: dict[str, Any]


def _normal_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _as_scalar_list(values: Any, *, label: str) -> list[float]:
    raw = values.tolist() if hasattr(values, "tolist") else list(values)
    out: list[float] = []
    for item in raw:
        if isinstance(item, (list, tuple)):
            if len(item) != 1:
                raise ElmerResultParseError(f"{label} is not scalar nodal data")
            item = item[0]
        value = float(item)
        if not math.isfinite(value):
            raise ElmerResultParseError(f"{label} contains a non-finite value")
        out.append(value)
    return out


def parse_arkkio_torque(stdout: str, *, stack_length_m: float) -> tuple[float, float]:
    if _NONCONVERGENCE.search(stdout):
        raise ElmerNonConvergenceError("Elmer reported nonlinear non-convergence")
    matches = _TORQUE_RE.findall(stdout)
    if not matches:
        raise ElmerResultParseError("Elmer output did not contain `Air gap torque`")
    per_length = float(matches[-1].replace("D", "E").replace("d", "e"))
    if not math.isfinite(per_length):
        raise ElmerResultParseError("Elmer Arkkio torque is non-finite")
    return per_length * stack_length_m, per_length


def parse_nodal_force_torque(stdout: str, *, stack_length_m: float) -> float | None:
    matches = _NODAL_TORQUE_RE.findall(stdout)
    if not matches:
        return None
    per_length = float(matches[-1].replace("D", "E").replace("d", "e"))
    if not math.isfinite(per_length):
        raise ElmerResultParseError("Elmer nodal-force torque is non-finite")
    return per_length * stack_length_m


def _read_vtu(path: Path) -> tuple[Any, list[list[float]], list[list[int]], list[float], list[int] | None]:
    try:
        import meshio  # type: ignore
    except ImportError as exc:
        raise ElmerResultParseError(
            "Reading Elmer VTU output requires the optional `meshio` dependency"
        ) from exc
    try:
        mesh = meshio.read(path)
    except Exception as exc:
        raise ElmerResultParseError(f"Could not read Elmer VTU {path}: {exc}") from exc
    points = mesh.points.tolist()
    nodes_mm = [[float(point[0]) * 1.0e3, float(point[1]) * 1.0e3] for point in points]
    triangle_blocks = [block for block in mesh.cells if block.type == "triangle"]
    if not triangle_blocks:
        raise ElmerResultParseError(f"Elmer VTU {path} has no linear triangles")
    triangles = [
        [int(index) for index in triangle]
        for block in triangle_blocks
        for triangle in block.data.tolist()
    ]
    az_values = None
    for key, values in mesh.point_data.items():
        normalized = _normal_key(key)
        if normalized in {"a", "az", "magneticvectorpotential", "magneticvectorpotential1"}:
            az_values = _as_scalar_list(values, label=key)
            break
    if az_values is None:
        available = ", ".join(sorted(mesh.point_data))
        raise ElmerResultParseError(
            f"Elmer VTU has no nodal A_z field; available point arrays: {available}"
        )
    if len(az_values) != len(nodes_mm):
        raise ElmerResultParseError("Elmer A_z length does not match VTU node count")

    geometry_ids: list[int] | None = None
    for key, blocks in mesh.cell_data.items():
        if _normal_key(key) not in {"geometryids", "geometryid", "bodyid", "bodyids"}:
            continue
        collected: list[int] = []
        for cell_block, values in zip(mesh.cells, blocks, strict=False):
            if cell_block.type == "triangle":
                raw_values = values.tolist() if hasattr(values, "tolist") else list(values)
                collected.extend(int(value[0] if isinstance(value, (list, tuple)) else value) for value in raw_values)
        if len(collected) == len(triangles):
            geometry_ids = collected
            break
    return mesh, nodes_mm, triangles, az_values, geometry_ids


def phase_flux_linkage_from_az(
    *,
    config: MotorConfig,
    triangles: list[list[int]],
    element_region_ids: list[str],
    nodes_mm: list[list[float]],
    az_nodal: list[float],
    region_contracts: list[dict[str, Any]],
) -> tuple[tuple[float, float, float], list[dict[str, Any]]]:
    """Area-average A_z per winding region with gauge-invariant reduction."""

    if len(triangles) != len(element_region_ids):
        raise ElmerResultParseError("Triangle and region counts differ during flux linkage")
    contracts = {str(region["id"]): region for region in region_contracts}
    integrals: dict[str, float] = {}
    areas: dict[str, float] = {}
    for triangle, region_id in zip(triangles, element_region_ids, strict=True):
        contract = contracts.get(region_id)
        if not contract or (contract.get("geometry_ir_kind") or contract.get("kind")) != "SlotWinding":
            continue
        i, j, k = triangle
        x1, y1 = nodes_mm[i]
        x2, y2 = nodes_mm[j]
        x3, y3 = nodes_mm[k]
        area_m2 = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) * 0.5e-6
        az_avg = (az_nodal[i] + az_nodal[j] + az_nodal[k]) / 3.0
        integrals[region_id] = integrals.get(region_id, 0.0) + az_avg * area_m2
        areas[region_id] = areas.get(region_id, 0.0) + area_m2
    if not areas:
        raise ElmerResultParseError("No solved winding regions were available for flux linkage")
    total_area = sum(areas.values())
    az_reference = sum(integrals.values()) / total_area if len(areas) > 1 else 0.0
    turn_factor = flux_linkage_slot_side_turn_factor(
        config.winding.type,
        config.winding.layers,
        config.winding.parallel_paths,
    )
    stack_m = float(config.stator.stack_length_mm) * 1.0e-3
    phase_flux = {"A": 0.0, "B": 0.0, "C": 0.0}
    contributions: list[dict[str, Any]] = []
    for region_id in sorted(areas):
        contract = contracts[region_id]
        winding = contract.get("winding") or {}
        phase = str(winding.get("phase") or "")
        direction = str(winding.get("direction") or "")
        if phase not in phase_flux or direction not in {"in", "out"}:
            raise ElmerResultParseError(f"Incomplete winding metadata for {region_id}")
        sign = 1.0 if direction == "in" else -1.0
        turn_fraction = float(winding.get("turn_fraction", 1.0))
        az_avg = integrals[region_id] / areas[region_id]
        az_effective = az_avg - az_reference
        contribution = (
            sign
            * turn_fraction
            * turn_factor
            * float(config.winding.turns_per_coil)
            * stack_m
            * az_effective
        )
        phase_flux[phase] += contribution
        contributions.append(
            {
                "region_id": region_id,
                "slot_index": int(winding.get("slot_index", 0)),
                "layer": int(winding.get("layer", 1)),
                "phase": phase,
                "direction": direction,
                "turn_fraction": turn_fraction,
                "slot_area_m2": areas[region_id],
                "az_reference_wb_per_m": az_reference,
                "az_avg_wb_per_m": az_avg,
                "az_effective_wb_per_m": az_effective,
                "flux_linkage_contribution_wb": contribution,
            }
        )
    return (phase_flux["A"], phase_flux["B"], phase_flux["C"]), contributions


def parse_position_result(
    *,
    config: MotorConfig,
    solve_mesh_artifact: dict[str, Any],
    case_manifest: ElmerCaseManifest,
    stdout: str,
    vtu_path: str | Path,
) -> ElmerPositionResult:
    stack_m = float(config.stator.stack_length_mm) * 1.0e-3
    torque_nm, torque_per_length = parse_arkkio_torque(stdout, stack_length_m=stack_m)
    nodal_force_torque_nm = parse_nodal_force_torque(stdout, stack_length_m=stack_m)
    _, nodes_mm, triangles, az_nodal, geometry_ids = _read_vtu(Path(vtu_path))
    contract_regions = ((solve_mesh_artifact.get("physics_contract") or {}).get("regions") or [])
    kind_by_region = {
        str(region["id"]): str(region.get("geometry_ir_kind") or region.get("kind"))
        for region in contract_regions
    }
    region_by_geometry_id: dict[int, str] = {}
    for body in case_manifest.bodies:
        for geometry_id in (body.target_body_id, body.body_number):
            existing_region = region_by_geometry_id.get(geometry_id)
            if existing_region is not None and existing_region != body.region_id:
                raise ElmerResultParseError(
                    f"Conflicting Elmer geometry id {geometry_id} maps to both "
                    f"{existing_region!r} and {body.region_id!r}"
                )
            region_by_geometry_id[geometry_id] = body.region_id
    if geometry_ids is None:
        raise ElmerResultParseError(
            "VTU omitted GeometryIds; element regions cannot be mapped safely after ElmerGrid conversion"
        )
    try:
        element_region_ids = [region_by_geometry_id[value] for value in geometry_ids]
    except KeyError as exc:
        raise ElmerResultParseError(f"Unknown VTU geometry id {exc.args[0]}") from exc
    preview_region = {
        "Shaft": "shaft",
        "RotorCore": "rotor_core",
        "Magnet": "magnet",
        "MagnetPocketAir": "magnet_pocket_air",
        "Airgap": "airgap",
        "FluxBarrier": "flux_barrier",
        "SlotWinding": "slot_winding",
        "StatorTooth": "stator_tooth",
        "StatorYoke": "stator_yoke",
        "ExteriorAir": "air",
    }
    regions = [preview_region.get(kind_by_region[region_id], kind_by_region[region_id].lower()) for region_id in element_region_ids]
    bx, by = generate_element_b_components(nodes_mm, triangles, az_nodal)
    b_magnitude = [math.hypot(x, y) for x, y in zip(bx, by, strict=True)]
    nodal_sums = [0.0] * len(nodes_mm)
    nodal_counts = [0] * len(nodes_mm)
    for triangle, value in zip(triangles, b_magnitude, strict=True):
        for index in triangle:
            nodal_sums[index] += value
            nodal_counts[index] += 1
    nodal_b = [value / count if count else 0.0 for value, count in zip(nodal_sums, nodal_counts, strict=True)]
    phase_flux, contributions = phase_flux_linkage_from_az(
        config=config,
        triangles=triangles,
        element_region_ids=element_region_ids,
        nodes_mm=nodes_mm,
        az_nodal=az_nodal,
        region_contracts=contract_regions,
    )
    tooth_values = [value for value, region in zip(b_magnitude, regions, strict=True) if region == "stator_tooth"]
    yoke_values = [value for value, region in zip(b_magnitude, regions, strict=True) if region == "stator_yoke"]
    if not tooth_values or not yoke_values:
        raise ElmerResultParseError("Solved field has no stator tooth/yoke elements")
    return ElmerPositionResult(
        torque_nm=torque_nm,
        torque_per_length_n=torque_per_length,
        nodal_force_torque_nm=nodal_force_torque_nm,
        nodes_mm=nodes_mm,
        triangles=triangles,
        regions=regions,
        element_region_ids=element_region_ids,
        az_nodal=az_nodal,
        element_bx_t=bx,
        element_by_t=by,
        element_b_magnitude_t=b_magnitude,
        nodal_b_magnitude_t=nodal_b,
        flux_linkage_a_wb=phase_flux[0],
        flux_linkage_b_wb=phase_flux[1],
        flux_linkage_c_wb=phase_flux[2],
        slot_flux_linkage_contributions=contributions,
        peak_b_tooth_t=max(tooth_values),
        peak_b_yoke_t=max(yoke_values),
        solve_mesh_evidence=build_solve_mesh_evidence(solve_mesh_artifact),
    )
