"""Mesh evidence hashes and rotated meshes are unchanged by sharing arrays between congruent positions."""

from __future__ import annotations

import copy
import hashlib
import json

from backend import mesh_evidence
from backend.gmsh_mesh_rotation import rotate_solve_mesh_artifact


def _artifact() -> dict:
    """A small 3-slot mesh artifact with enough elements for its arrays to be cached."""

    count = 600
    slot = [f"slot_winding_{index % 3}" for index in range(count)]
    return {
        "mesh": {
            "nodes": [[float(index) * 0.5, -0.0 if index % 7 == 0 else float(index) * 0.25] for index in range(count)],
            "length_units": "mm",
            "triangles": [[index, (index + 1) % count, (index + 2) % count] for index in range(count)],
            "regions": ["SlotWinding"] * count,
            "boundary_nodes": list(range(40)),
            "sector_edge_pairs": [],
            "info": {"num_nodes": count, "num_triangles": count, "rotor_angle_mech_deg": 0.0},
        },
        "element_region_ids": slot,
        "element_magnetization": [None] * count,
        "element_current_density_a_per_m2": [1.5e6 if name.endswith("0") else -0.0 for name in slot],
        "topology_provenance": {"topology": "SPM"},
        "rotor_angle_mech_deg": 0.0,
        "physics_contract": {
            "version": "magneto2d_imported_physics/v0",
            "motion": {"rotor_angle_mech_deg": 0.0, "rotor_state": "baked_in_mesh"},
            "regions": [
                {
                    "id": f"slot_winding_{index}",
                    "kind": "SlotWinding",
                    "source_group": f"winding:{phase}:in:slot{index}",
                    "current_density_a_per_m2": 1.5e6,
                    "winding": {"phase": phase, "direction": "in", "slot_index": index, "area_mm2": 12.0, "turn_fraction": 1.0},
                }
                for index, phase in enumerate("ABC")
            ],
            "provenance": {
                "mesh_source": "gmsh",
                "element_region_sources": ["gmsh_physical_surface"] * count,
                "element_material_sources": ["geometry_ir"] * count,
                "nested": {"é": [0.0, -0.0, 1.0], "empty": {}},
            },
        },
    }


def _rotate(artifact: dict, slots: int = 1) -> dict:
    return rotate_solve_mesh_artifact(
        artifact,
        slot_count=3,
        target_rotor_angle_mech_deg=120.0 * slots,
        phase_ampere_turns=lambda elec_deg: {"A": 10.0 + elec_deg, "B": -5.0, "C": -5.0},
        current_angle_elec_deg_for_mech=lambda mech_deg: 2.0 * mech_deg,
    )


def _plain_evidence(artifact: dict) -> dict:
    """Evidence with no text shared between calls: every hash from the whole payload."""

    return mesh_evidence.build_solve_mesh_evidence(copy.deepcopy(artifact))


def test_evidence_built_from_cached_pieces_matches_evidence_built_whole() -> None:
    base = _artifact()
    rotated = [_rotate(base, 1), _rotate(base, 2)]
    cache: dict = {}
    for artifact in (base, *rotated):
        shared = mesh_evidence.build_solve_mesh_evidence(artifact, canonical_cache=cache)
        assert shared == _plain_evidence(artifact)
    # The artifact hash is the hash of the artifact's canonical JSON, signed zeros normalized.
    text = json.dumps(
        mesh_evidence._normalize_canonical_json(base), allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert mesh_evidence.build_solve_mesh_evidence(base, canonical_cache={})["artifact_sha256"] == hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()
    # Arrays the rotations share with the base were serialized once.
    assert id(base["mesh"]["triangles"]) in cache
    assert sum(1 for value, _text in cache.values() if value == base["mesh"]["triangles"]) == 1


def test_rotation_shares_unchanged_arrays_and_leaves_the_base_alone() -> None:
    base = _artifact()
    before = copy.deepcopy(base)

    rotated = _rotate(base)

    assert base == before
    # The same values as rotating an independent copy.
    assert rotated == _rotate(copy.deepcopy(before))
    assert rotated["mesh"]["nodes"] != base["mesh"]["nodes"]
    assert rotated["rotor_angle_mech_deg"] == 120.0
    assert rotated["mesh"]["info"]["rotor_angle_mech_deg"] == 120.0 and base["mesh"]["info"]["rotor_angle_mech_deg"] == 0.0
    assert rotated["physics_contract"]["provenance"]["mesh_reuse"]["n_slot_pitches"] == 1
    assert "mesh_reuse" not in base["physics_contract"]["provenance"]
    assert rotated["physics_contract"]["regions"][0]["source_group"] != base["physics_contract"]["regions"][0]["source_group"]
    # What rotation does not change is the same object, not a copy.
    for path in (("mesh", "triangles"), ("mesh", "regions"), ("element_region_ids",)):
        ours, theirs = rotated, base
        for key in path:
            ours, theirs = ours[key], theirs[key]
        assert ours is theirs, path
    assert (
        rotated["physics_contract"]["provenance"]["element_region_sources"]
        is base["physics_contract"]["provenance"]["element_region_sources"]
    )
    # A rotation by no slot pitch is still an independent copy.
    same = _rotate(base, 0)
    assert same == base and same["mesh"]["triangles"] is not base["mesh"]["triangles"]
