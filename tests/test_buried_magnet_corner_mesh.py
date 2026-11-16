"""The wider fine patch at buried-magnet corners (#285) applies to IPM only."""
from types import SimpleNamespace

import pytest

from backend import gmsh_solver


def _threshold_calls(monkeypatch, topology: str, corner_refinement: bool) -> list[dict]:
    calls: list[dict] = []

    def record(**kwargs):
        calls.append(kwargs)
        return len(calls)

    monkeypatch.setattr(gmsh_solver, "_add_threshold_field", record)
    monkeypatch.setattr(gmsh_solver.gmsh.model.mesh.field, "add", lambda *_a, **_k: 99)
    monkeypatch.setattr(gmsh_solver.gmsh.model.mesh.field, "setNumbers", lambda *_a, **_k: None)
    monkeypatch.setattr(gmsh_solver.gmsh.model.mesh.field, "setAsBackgroundMesh", lambda *_a, **_k: None)
    monkeypatch.setattr(gmsh_solver.gmsh.option, "setNumber", lambda *_a, **_k: None)
    builder = SimpleNamespace(base_lc_mm=1.87, points_by_feature={"magnet_corner": {1, 2, 3, 4}}, curves_by_feature={})
    geom = SimpleNamespace(magnets=[SimpleNamespace(outer_radius_mm=45.0)], rotor_OD_r=47.0, stator_ID_r=47.8, shaft_r=10.0)
    config = SimpleNamespace(topology=topology,
                             solve_params=SimpleNamespace(mesher="gmsh", corner_refinement=corner_refinement))
    gmsh_solver._apply_gmsh_physics_mesh_fields(builder, geom, config)
    return calls


def test_ipm_with_corner_refinement_gets_the_wider_fine_patch(monkeypatch):
    calls = _threshold_calls(monkeypatch, "IPM", True)
    section = gmsh_solver._gmsh_refined_mesh_profile()["buried_magnet_corner"]
    wide = [c for c in calls if c["size_min_mm"] == section["size_mm"]]
    assert len(wide) == 1 and wide[0]["points"] == [1, 2, 3, 4]
    assert wide[0]["dist_min_mm"] == section["core_radius_mm"]
    assert wide[0]["dist_max_mm"] == pytest.approx(section["core_radius_mm"] + section["transition_mm"])
    # The existing tight corner patch stays; the wide one is larger and coarser.
    tight = [c for c in calls if c is not wide[0]]
    assert len(tight) == 1 and tight[0]["size_min_mm"] < wide[0]["size_min_mm"]
    assert tight[0]["dist_min_mm"] < wide[0]["dist_min_mm"]


@pytest.mark.parametrize("topology,corner_refinement", [("SPM", True), ("IPM", False), ("SPM", False)])
def test_other_meshes_keep_one_magnet_corner_patch(monkeypatch, topology, corner_refinement):
    assert len(_threshold_calls(monkeypatch, topology, corner_refinement)) == 1
