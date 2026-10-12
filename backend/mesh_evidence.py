"""Compact, deterministic evidence for a mesh artifact actually sent to a solver."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# In compact JSON a -0.0 number is always a list item or a dict value, so it
# sits between one of "[,:" and one of ",]}". Inside a string the pattern can
# also match; that only sends the payload down the exact slow path.
_NEGATIVE_ZERO_TOKEN = re.compile(r"(?<=[\[,:])-0\.0(?=[,\]}])")


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


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


CanonicalTextCache = dict[int, tuple[Any, str]]


def _normalized_canonical_json(payload: Any) -> str:
    # Normalizing only changes a payload that holds -0.0, but it walks every
    # value in Python: ~60 million calls per solve. Serialize first and
    # normalize only when the text shows a -0.0, so the text is the same
    # either way.
    encoded = _canonical_json(payload)
    if isinstance(payload, float) or _NEGATIVE_ZERO_TOKEN.search(encoded):
        encoded = _canonical_json(_normalize_canonical_json(payload))
    return encoded


def _sha256_json(payload: Any, cache: CanonicalTextCache | None = None) -> str:
    """Hash the normalized canonical JSON of ``payload``.

    With ``cache``, a dict with string keys is hashed from its values' texts,
    which are reused for values (by identity) already serialized in this
    cache. The bytes are those of the whole-payload text: sorted
    ``"key":value`` pieces joined by commas inside braces.
    """

    if cache is None or not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return hashlib.sha256(_normalized_canonical_json(payload).encode("utf-8")).hexdigest()
    digest = hashlib.sha256(b"{")
    for index, key in enumerate(sorted(payload)):
        value = payload[key]
        cached = cache.get(id(value))
        if cached is not None and cached[0] is value:
            text = cached[1]
        else:
            text = _normalized_canonical_json(value)
            cache[id(value)] = (value, text)
        if index:
            digest.update(b",")
        digest.update(json.dumps(key, ensure_ascii=False).encode("utf-8"))
        digest.update(b":")
        digest.update(text.encode("utf-8"))
    digest.update(b"}")
    return digest.hexdigest()


def build_solve_mesh_evidence(
    solve_mesh_artifact: dict[str, Any],
    *,
    geometry_sha256: str | None = None,
    canonical_cache: CanonicalTextCache | None = None,
) -> dict[str, Any]:
    """Return hashes/counts/inventories without retaining the full mesh arrays.

    ``geometry_sha256`` may carry the geometry hash of an artifact with the same
    mesh, element region ids and rotor angle, so hashing the mesh arrays again
    is skipped. ``canonical_cache`` shares serialized top-level values, such as
    the mesh, between calls on artifacts that hold the same objects.
    """

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
        "artifact_sha256": _sha256_json(solve_mesh_artifact, canonical_cache),
        "geometry_sha256": geometry_sha256 or _sha256_json(geometry_payload, canonical_cache),
        "physics_contract_sha256": _sha256_json(physics_contract),
        "region_inventory_sha256": _sha256_json(region_inventory),
        "source_inventory_sha256": _sha256_json(source_inventory),
        "material_inventory_sha256": _sha256_json(material_inventory),
        "node_count": len(nodes),
        "triangle_count": len(triangles),
        "region_count": len(region_inventory),
        "rotor_angle_mech_deg": solve_mesh_artifact.get("rotor_angle_mech_deg"),
    }
