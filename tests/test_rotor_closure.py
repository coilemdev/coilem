"""Mesh/pose/coordinate integrity for the bounded FEMM closure check."""

import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from tools.femm_reference.rotor_airgap import BOUNDARY, band_radii, inner_air_label_points, mesh_signature
from tools.rotor_closure_report import POSES, analyse_closure, closure_metrics
from tools.rotor_loss_pilot_report import analyse


def make_probe(directory):
    protocol = {"collection_kind": "closure_probe", "motion_model": "periodic-air-gap",
                "mechanical_angles_deg": POSES, "independent_base_reload": True,
                "raw_mesh_frame": "rotor_material", "raw_field_frame": "rotor_material",
                "closure_tolerances": {"max_component_T": 1e-6, "rms_component_T": 1e-7}}
    (directory / "protocol.json").write_text(json.dumps(protocol))
    corners = np.array([[[10, 0], [12, 0], [11, 2]]], dtype=float)
    point = corners.mean(axis=1)
    np.savetxt(directory / "reference-points.csv", point, delimiter=",")
    for index, angle in enumerate(POSES):
        folder = directory / f"position-{index:04d}"
        folder.mkdir()
        field = np.array([[1+0.1*np.cos(np.deg2rad(angle)), 0.2*np.sin(np.deg2rad(angle))]])
        np.savetxt(folder / "rotor.csv", np.concatenate([corners.reshape(1, 6), field], axis=1), delimiter=",")
        np.savetxt(folder / "points.csv", field, delimiter=",")
        (folder / "model.fem").write_text(f'[PrevSoln] = ""\n<BeginBdry>\n<BdryName> = "{BOUNDARY}"\n<BdryType> = 6\n'
                                          f'<innerangle> = {angle}\n<outerangle> = 0\n<EndBdry>\n')
        (folder / "model.ans").write_text(f'[Solution]\n3\n10 0 {index} 0\n12 0 0 0\n11 2 0 0\n1\n0 1 2 0 10 0\n')
        (folder / "point-export.lua").write_text(f'mo_getpointvalues({point[0, 0]:.17g},{point[0, 1]:.17g})')
        (folder / "mesh-export.lua").write_text("synthetic analytical test export")
        record = {"index": index, "mechanical_angle_deg": angle, "total_elements": 1, "wall_s": 0.1,
                  "mesh_geometry_sha256": mesh_signature(folder / "model.ans"),
                  "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}}
        (folder / "position.json").write_text(json.dumps(record))


def refresh_checkpoint(folder):
    path = folder / "position.json"
    record = json.loads(path.read_text())
    record["sha256"] = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in record["sha256"]}
    path.write_text(json.dumps(record))


def test_probe_checks_mesh_and_real_motion_without_qualifying_losses(tmp_path):
    make_probe(tmp_path)
    result = analyse_closure(tmp_path)
    assert result["closure_probe_gate"] == result["mesh_invariance_gate"] == "PASS"
    assert result["distinct_triangle_meshes"] == 1 and result["interior_motion_changed"]
    assert result["closure"]["max_component_difference_T"] < 1e-14
    assert result["loss_watts"] is None and result["status"] == "PILOT_NOT_QUALIFIED"


def test_changed_field_fails_closure_even_with_valid_artifact_hashes(tmp_path):
    make_probe(tmp_path)
    folder = tmp_path / "position-0003"
    np.savetxt(folder / "points.csv", [[1.0, 0.5]], delimiter=",")
    refresh_checkpoint(folder)
    assert analyse_closure(tmp_path)["closure_probe_gate"] == "FAIL"


def test_endpoint_must_retain_unwrapped_minus_360_pose(tmp_path):
    make_probe(tmp_path)
    folder = tmp_path / "position-0003"
    path = folder / "model.fem"
    path.write_text(path.read_text().replace("-360.0", "0.0"))
    refresh_checkpoint(folder)
    with pytest.raises(ValueError, match="unwrapped"):
        analyse_closure(tmp_path)


def test_a_previous_solution_cannot_masquerade_as_fresh_closure(tmp_path):
    make_probe(tmp_path)
    folder = tmp_path / "position-0003"
    path = folder / "model.fem"
    path.write_text(path.read_text().replace('[PrevSoln] = ""', '[PrevSoln] = "first.ans"'))
    refresh_checkpoint(folder)
    with pytest.raises(ValueError, match="previous-solution seed"):
        analyse_closure(tmp_path)


def test_queries_must_stay_in_femms_drawn_rotor_coordinates(tmp_path):
    make_probe(tmp_path)
    folder = tmp_path / "position-0001"
    (folder / "point-export.lua").write_text("mo_getpointvalues(0,0)")
    refresh_checkpoint(folder)
    with pytest.raises(ValueError, match="drawn rotor-material"):
        analyse_closure(tmp_path)


def test_partial_probe_is_rejected(tmp_path):
    make_probe(tmp_path)
    (tmp_path / "position-0004" / "position.json").unlink()
    with pytest.raises(FileNotFoundError):
        analyse_closure(tmp_path)


def test_same_mesh_count_cannot_hide_changed_geometry(tmp_path):
    make_probe(tmp_path)
    folder = tmp_path / "position-0001"
    path = folder / "model.ans"
    path.write_text(path.read_text().replace("12 0 0 0", "12.1 0 0 0"))
    record_path = folder / "position.json"
    record = json.loads(record_path.read_text())
    record["mesh_geometry_sha256"] = mesh_signature(path)
    record_path.write_text(json.dumps(record))
    refresh_checkpoint(folder)
    assert analyse_closure(tmp_path)["mesh_invariance_gate"] == "FAIL"


def test_closure_probe_cannot_be_mistaken_for_a_full_history(tmp_path):
    make_probe(tmp_path)
    with pytest.raises(ValueError, match="closure probe is not a full-turn history"):
        analyse(tmp_path)


@pytest.mark.parametrize("radii", [(30, 30), (31, 30), (float("nan"), 30), (-1, 30)])
def test_band_cannot_intersect_solid_geometry(radii):
    with pytest.raises(ValueError):
        band_radii(*radii)


def test_band_is_inside_the_free_airgap():
    inner, outer = band_radii(29.5, 30)
    assert 29.5 < inner < outer < 30


def test_flat_ipm_air_label_moves_out_of_unmeshed_band_into_inner_air():
    geom = SimpleNamespace(stator_ID_r=48, rotor_OD_r=43,
        magnets=[SimpleNamespace(center_angle_rad=a) for a in (0, math.pi/4)])
    inner, outer = band_radii(43,48)
    old, new = inner_air_label_points(geom,43,inner,outer)
    assert inner < math.hypot(*old) < outer
    assert 43 < math.hypot(*new) < inner
    assert math.atan2(new[1],new[0]) == pytest.approx(math.pi/8)


def test_completed_spm_pilot_keeps_its_original_inter_magnet_air_label():
    geom = SimpleNamespace(stator_ID_r=30,rotor_OD_r=27,
        magnets=[SimpleNamespace(center_angle_rad=a) for a in (0, math.pi/4)])
    inner,outer = band_radii(29.5,30)
    assert inner_air_label_points(geom,29.5,inner,outer) is None


def test_closure_uses_both_maximum_and_rms_limits():
    limits = {"max_component_T": 1e-6, "rms_component_T": 1e-7}
    assert closure_metrics([[0, 0]], [[0, 0]], limits)["gate"] == "PASS"
    assert closure_metrics([[0, 0]], [[5e-7, 0]], limits)["gate"] == "FAIL"
