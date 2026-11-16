"""The wider fine patch at V-shape magnet and pocket corners (#285)."""
from types import SimpleNamespace

import pytest

from backend import gmsh_solver

BASE_LC = 1.87


def _threshold_calls(monkeypatch, topology: str, ipm_topology: str | None, corner_refinement: bool) -> list[dict]:
    calls: list[dict] = []

    def record(**kwargs):
        calls.append(kwargs)
        return len(calls)

    monkeypatch.setattr(gmsh_solver, "_add_threshold_field", record)
    monkeypatch.setattr(gmsh_solver.gmsh.model.mesh.field, "add", lambda *_a, **_k: 99)
    monkeypatch.setattr(gmsh_solver.gmsh.model.mesh.field, "setNumbers", lambda *_a, **_k: None)
    monkeypatch.setattr(gmsh_solver.gmsh.model.mesh.field, "setAsBackgroundMesh", lambda *_a, **_k: None)
    monkeypatch.setattr(gmsh_solver.gmsh.option, "setNumber", lambda *_a, **_k: None)
    builder = SimpleNamespace(base_lc_mm=BASE_LC, points_by_feature={"magnet_corner": {1, 2, 3, 4}}, curves_by_feature={})
    geom = SimpleNamespace(magnets=[SimpleNamespace(outer_radius_mm=45.0)], rotor_OD_r=47.0, stator_ID_r=47.8, shaft_r=10.0)
    config = SimpleNamespace(topology=topology, rotor=SimpleNamespace(ipm_topology=ipm_topology),
                             solve_params=SimpleNamespace(mesher="gmsh", corner_refinement=corner_refinement))
    gmsh_solver._apply_gmsh_physics_mesh_fields(builder, geom, config)
    return calls


@pytest.mark.parametrize("corner_refinement", [False, True])
def test_v_shape_gets_the_wide_patch_with_or_without_corner_refinement(monkeypatch, corner_refinement):
    calls = _threshold_calls(monkeypatch, "IPM", "v_shape", corner_refinement)
    section = gmsh_solver._gmsh_refined_mesh_profile()["v_shape_magnet_corner"]
    assert len(calls) == 2  # the existing magnet-corner patch, then the wide one
    existing, wide = calls
    assert wide["points"] == [1, 2, 3, 4]
    assert wide["size_min_mm"] == section["size_mm"]
    assert wide["dist_min_mm"] == section["core_radius_mm"]
    assert wide["dist_max_mm"] == pytest.approx(section["core_radius_mm"] + section["transition_mm"])
    assert wide["dist_min_mm"] > existing["dist_min_mm"]
    # Away from the corners the mesh returns to the same size as the rest of the mesh.
    assert wide["size_max_mm"] == existing["size_max_mm"]
    if not corner_refinement:
        assert wide["size_max_mm"] == BASE_LC and wide["size_min_mm"] < existing["size_min_mm"]


@pytest.mark.parametrize("topology,ipm_topology", [("SPM", None), ("IPM", "flat_buried"), ("IPM", "pyleecan_holem50")])
@pytest.mark.parametrize("corner_refinement", [False, True])
def test_other_rotors_keep_one_magnet_corner_patch(monkeypatch, topology, ipm_topology, corner_refinement):
    assert len(_threshold_calls(monkeypatch, topology, ipm_topology, corner_refinement)) == 1


def test_v_shape_mesh_metadata_records_the_patch():
    config = SimpleNamespace(topology="IPM", rotor=SimpleNamespace(ipm_topology="v_shape"),
                             solve_params=SimpleNamespace(mesher="gmsh", corner_refinement=False))
    assert gmsh_solver._gmsh_mesh_size_metadata(config, BASE_LC)["gmsh_v_shape_corner_patch_mm"] == {"size": 0.15, "radius": 1.5}
    config.rotor.ipm_topology = "flat_buried"
    assert "gmsh_v_shape_corner_patch_mm" not in gmsh_solver._gmsh_mesh_size_metadata(config, BASE_LC)
