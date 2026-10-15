"""The tooth shoe is part of the mesh signature, so cached meshes never cross it."""

from __future__ import annotations

from pathlib import Path

import pytest

import backend.solver as solver
from backend.models import MotorConfig
from backend.topology_provenance import (
    MAGNETO2D_MESH_SIGNATURE_VERSION,
    build_mesh_signature_payload,
    build_topology_provenance,
)

pytestmark = pytest.mark.pr

FIXTURE = Path(__file__).parent / "fixtures/spm_4p12s_simple.json"


def _config(**stator_changes) -> MotorConfig:
    config = MotorConfig.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    payload = config.model_dump(mode="json")
    payload["stator"].update(stator_changes)
    return MotorConfig.model_validate(payload)


# The fixture's 2.5 mm slot opening leaves room for at most 1.25 mm per side.
SHOE = {"tooth_shoe_enabled": True, "tooth_shoe_overhang_mm": 1.0}
# (reference, changed) pairs that differ in one tooth-shoe setting only.
SHOE_VARIANTS = {
    "enabled": ({**SHOE, "tooth_shoe_enabled": False}, SHOE),
    "height": (SHOE, {**SHOE, "tooth_shoe_height_mm": 2.0}),
    "overhang": (SHOE, {**SHOE, "tooth_shoe_overhang_mm": 0.75}),
}


def test_tooth_shoe_settings_are_recorded_in_provenance():
    stator = build_topology_provenance(_config(**SHOE, tooth_shoe_height_mm=2.0))["geometry"]["stator"]
    assert stator["tooth_shoe_enabled"] is True
    assert stator["tooth_shoe_height_mm"] == 2.0
    assert stator["tooth_shoe_overhang_mm"] == 1.0
    assert MAGNETO2D_MESH_SIGNATURE_VERSION == "magneto2d_mesh_signature/v5"


@pytest.mark.parametrize("variant", sorted(SHOE_VARIANTS))
def test_tooth_shoe_only_change_moves_signature_and_cache_scope(variant):
    reference_stator, changed_stator = SHOE_VARIANTS[variant]
    reference = _config(**reference_stator)
    changed = _config(**changed_stator)
    # Only the stator tooth shoe differs between the two configs.
    assert reference.model_dump(exclude={"stator"}) == changed.model_dump(exclude={"stator"})
    assert build_mesh_signature_payload(reference) != build_mesh_signature_payload(changed)
    for clockwise_positive in (False, True):
        assert solver._angle_mesh_cache_scope_key(
            reference, clockwise_positive=clockwise_positive
        ) != solver._angle_mesh_cache_scope_key(changed, clockwise_positive=clockwise_positive)


def test_tooth_shoe_only_change_does_not_reuse_a_cached_mesh():
    solver.clear_per_angle_gmsh_mesh_cache()
    try:
        plain = _config()
        shoe = _config(**SHOE)
        plain_scope = solver._angle_mesh_cache_scope_key(plain)
        solver._angle_mesh_cache_store(plain_scope, 0, {"mesh": {"nodes": [[0.0, 0.0]]}})
        assert solver._angle_mesh_cache_take_all(plain_scope, [0]) is not None
        assert solver._angle_mesh_cache_take_all(solver._angle_mesh_cache_scope_key(shoe), [0]) is None
    finally:
        solver.clear_per_angle_gmsh_mesh_cache()


def test_tooth_shoe_changes_the_gmsh_mesh_it_keys():
    """The signature fix matters: Gmsh builds a different mesh with a shoe."""
    pytest.importorskip("gmsh")
    plain = _config()
    shoe = _config(**SHOE)
    for config in (plain, shoe):
        config.solve_params.mesh_density = "coarse"
    plain_artifact, _ = solver._GmshMeshProducer.build(plain, 7.5)
    shoe_artifact, _ = solver._GmshMeshProducer.build(shoe, 7.5)
    assert plain_artifact["mesh"]["nodes"] != shoe_artifact["mesh"]["nodes"]
    assert shoe_artifact["topology_provenance"]["geometry"]["stator"]["tooth_shoe_enabled"] is True
    assert plain_artifact["topology_provenance"]["geometry"]["stator"]["tooth_shoe_enabled"] is False
