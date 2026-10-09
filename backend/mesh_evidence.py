"""Compact, deterministic evidence for a mesh artifact actually sent to a solver."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize_canonical_json(payload: Any) -> Any:
    """Normalize JSON-equivalent values before hashing solver evidence.

    IEEE-754 signed zero is useful during numerical calculations, but ``-0.0``
    and ``0.0`` describe the same physical source value. Python equality
    already treats them as equal while JSON preserves the sign, which made
    independently generated zero-current artifacts hash differently.
    """

    if isinstance(payload, float) and payload == 0.0:
        return 0.0
    if isinstance(payload, dict):
        return {key: _normalize_canonical_json(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_normalize_canonical_json(value) for value in payload]
    return payload


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        _normalize_canonical_json(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_solve_mesh_evidence(solve_mesh_artifact: dict[str, Any]) -> dict[str, Any]:
    """Return hashes/counts/inventories without retaining the full mesh arrays."""

    mesh = solve_mesh_artifact.get("mesh")
    if not isinstance(mesh, dict):
        raise ValueError("solve mesh artifact has no mesh object")
    nodes = mesh.get("nodes")
    triangles = mesh.get("triangles")
    region_ids = solve_mesh_artifact.get("element_region_ids")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("solve mesh artifact has no nodes")
    if not isinstance(triangles, list) or not triangles:
        raise ValueError("solve mesh artifact has no triangles")
    if not isinstance(region_ids, list) or len(region_ids) != len(triangles):
        mesh_regions = mesh.get("regions")
        region_ids = (
            list(mesh_regions)
            if isinstance(mesh_regions, list) and len(mesh_regions) == len(triangles)
            else ["unknown"] * len(triangles)
        )

    physics_contract = solve_mesh_artifact.get("physics_contract")
    regions = physics_contract.get("regions") if isinstance(physics_contract, dict) else None
    contract_complete = bool(isinstance(regions, list) and regions)
    if not isinstance(physics_contract, dict):
        physics_contract = {}
    if not isinstance(regions, list) or not regions:
        regions = [
            {"id": region_id, "kind": region_id}
            for region_id in dict.fromkeys(str(value) for value in region_ids)
        ]

    region_inventory: list[dict[str, Any]] = []
    source_inventory: list[dict[str, Any]] = []
    material_inventory: list[dict[str, Any]] = []
    for raw_region in regions:
        if not isinstance(raw_region, dict):
            raise ValueError("solve mesh physics-contract region is not an object")
        region_id = str(raw_region.get("id") or "")
        if not region_id:
            raise ValueError("solve mesh physics-contract region has no id")
        region_inventory.append(
            {
                "id": region_id,
                "kind": raw_region.get("kind"),
                "geometry_ir_kind": raw_region.get("geometry_ir_kind"),
                "motion_group": raw_region.get("motion_group"),
            }
        )
        material_inventory.append(
            {
                "id": region_id,
                "material": raw_region.get("material"),
            }
        )
        source_inventory.append(
            {
                "id": region_id,
                "source_group": raw_region.get("source_group"),
                "current_density_a_per_m2": raw_region.get("current_density_a_per_m2"),
                "magnetization_angle_deg": raw_region.get("magnetization_angle_deg"),
            }
        )

    geometry_payload = {
        "mesh": mesh,
        "element_region_ids": region_ids,
        "rotor_angle_mech_deg": solve_mesh_artifact.get("rotor_angle_mech_deg"),
    }
    return {
        "schema_version": "openem.solve_mesh_evidence/v1",
        "contract_complete": contract_complete,
        "artifact_sha256": _sha256_json(solve_mesh_artifact),
        "geometry_sha256": _sha256_json(geometry_payload),
        "physics_contract_sha256": _sha256_json(physics_contract),
        "region_inventory_sha256": _sha256_json(region_inventory),
        "source_inventory_sha256": _sha256_json(source_inventory),
        "material_inventory_sha256": _sha256_json(material_inventory),
        "node_count": len(nodes),
        "triangle_count": len(triangles),
        "region_count": len(region_inventory),
        "rotor_angle_mech_deg": solve_mesh_artifact.get("rotor_angle_mech_deg"),
    }
