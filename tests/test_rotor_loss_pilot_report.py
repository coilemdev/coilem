"""Reference evidence must be complete and bound to the actual material queries."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tools.femm_reference.rotor_airgap import BOUNDARY, mesh_signature
from tools.rotor_loss_pilot_report import analyse, markdown_report

FIXTURE = "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def write_pilot(directory, *, coordinate_frame="global", positions=32):
    fixture = Path(__file__).resolve().parents[1] / FIXTURE
    protocol = {"positions": positions, "speed_rpm": 3000, "fixture": FIXTURE,
                "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()}
    if coordinate_frame == "rotor_material":
        protocol.update(motion_model="periodic-air-gap", collection_kind="full_turn_history",
                        raw_mesh_frame="rotor_material", raw_field_frame="rotor_material", independent_base_reload=True,
                        mechanical_angles_deg=[-360*k/positions for k in range(positions+1)],
                        closure_tolerances={"max_component_T": 1e-6, "rms_component_T": 1e-7})
    (directory / "protocol.json").write_text(json.dumps(protocol))
    corners = np.array([[[10, 0], [12, 0], [11, 2]]], dtype=float)
    points = corners.mean(axis=1)
    np.savetxt(directory / "reference-points.csv", points, delimiter=",")
    for index in range(positions+1):
        position = directory / f"position-{index:04d}"
        position.mkdir()
        angle = -360*index/positions
        radians = np.deg2rad(angle)
        rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
        if coordinate_frame == "rotor_material":
            rotation = np.eye(2)
        global_corners, global_points = corners @ rotation.T, points @ rotation.T
        vector = np.array([1.0 + 0.1*np.cos(2*np.pi*3*index/positions), 0.0]) @ rotation.T
        mesh = np.concatenate([global_corners.reshape(1, 6), vector.reshape(1, 2)], axis=1)
        np.savetxt(position / "rotor.csv", mesh, delimiter=",")
        np.savetxt(position / "points.csv", vector.reshape(1, 2), delimiter=",")
        (position / "point-export.lua").write_text(f"az,bx,by=mo_getpointvalues({global_points[0, 0]:.17g},{global_points[0, 1]:.17g})")
        if coordinate_frame == "rotor_material":
            (position / "model.fem").write_text(f'[PrevSoln] = ""\n<BeginBdry>\n<BdryName> = "{BOUNDARY}"\n'
                                               f'<BdryType> = 6\n<innerangle> = {angle}\n<outerangle> = 0\n<EndBdry>\n')
            (position / "model.ans").write_text(f'[Solution]\n3\n10 0 {index} 0\n12 0 0 0\n11 2 0 0\n1\n0 1 2 0 10 0\n')
            (position / "mesh-export.lua").write_text("synthetic fixed-mesh test fixture")
        record = {"index": index, "mechanical_angle_deg": angle, "wall_s": 0.1, "total_elements": 1,
                  "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in position.iterdir()}}
        if coordinate_frame == "rotor_material":
            record["mesh_geometry_sha256"] = mesh_signature(position / "model.ans")
        (position / "position.json").write_text(json.dumps(record))


def test_complete_evidence_reports_agreement_without_claiming_qualification(tmp_path):
    write_pilot(tmp_path)
    report = analyse(tmp_path)
    assert report["status"] == "PILOT_NOT_QUALIFIED"
    assert report["mesh_gate"] == "NOT_RUN"
    assert report["timing"]["field_solves_including_endpoint"] == 33
    assert all(row["sampling_status"] == "PASS" and row["reference_agreement_pass"] for row in report["results"])
    assert report["independent_endpoint_max_component_difference_T"] < 1e-12
    text = markdown_report(report)
    assert "PILOT_NOT_QUALIFIED" in text and "Mesh convergence: **NOT RUN**" in text
    assert "native field-solver parity" in text


def test_progressive_subset_uses_registered_pose_indices_and_independent_endpoint(tmp_path):
    write_pilot(tmp_path, coordinate_frame="rotor_material", positions=64)
    # Only the registered even poses exist at this progressive stage.
    for index in range(1, 64, 2):
        (tmp_path / f"position-{index:04d}" / "position.json").unlink()
    report = analyse(tmp_path, sample_stride=2)
    assert report["registered_positions"] == 64 and report["sample_stride"] == 2
    assert report["sampling_plan"]["positions"] == 32 and report["timing"]["field_solves_including_endpoint"] == 33
    assert report["closure_gate"] == "PASS" and all(r["reference_agreement_pass"] for r in report["results"])
    with pytest.raises(FileNotFoundError):
        analyse(tmp_path)


def test_partial_pilot_is_not_a_reference_result(tmp_path):
    write_pilot(tmp_path)
    (tmp_path / "position-0032" / "position.json").unlink()
    with pytest.raises(FileNotFoundError):
        analyse(tmp_path)


def test_modified_raw_field_is_rejected(tmp_path):
    write_pilot(tmp_path)
    with (tmp_path / "position-0001" / "points.csv").open("a") as stream:
        stream.write("0,0\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        analyse(tmp_path)


def test_wrong_material_point_cannot_pass_even_with_updated_file_hash(tmp_path):
    write_pilot(tmp_path)
    position = tmp_path / "position-0001"
    script = position / "point-export.lua"
    script.write_text("az,bx,by=mo_getpointvalues(0,0)")
    checkpoint = position / "position.json"
    record = json.loads(checkpoint.read_text())
    record["sha256"][script.name] = hashlib.sha256(script.read_bytes()).hexdigest()
    checkpoint.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="fixed rotor material points"):
        analyse(tmp_path)


def test_fixed_and_global_representations_produce_the_same_loss(tmp_path):
    global_dir, fixed_dir = tmp_path / "global", tmp_path / "fixed"
    global_dir.mkdir()
    fixed_dir.mkdir()
    write_pilot(global_dir)
    write_pilot(fixed_dir, coordinate_frame="rotor_material")
    global_report, fixed_report = analyse(global_dir), analyse(fixed_dir)
    assert fixed_report["closure_gate"] == fixed_report["mesh_invariance_gate"] == "PASS"
    assert fixed_report["distinct_triangle_meshes"] == 1
    for global_row, fixed_row in zip(global_report["results"], fixed_report["results"]):
        assert fixed_row["reference_agreement_pass"] and fixed_row["distinct_rotor_meshes"] == 1
        assert fixed_row["production_sampling"]["total_W"] == pytest.approx(global_row["production_sampling"]["total_W"], rel=1e-12)
        assert fixed_row["reference"]["total_W"] == pytest.approx(global_row["reference"]["total_W"], rel=1e-12)


def test_mixed_mesh_and_field_frames_are_not_guessed(tmp_path):
    write_pilot(tmp_path, coordinate_frame="rotor_material")
    path = tmp_path / "protocol.json"
    protocol = json.loads(path.read_text())
    protocol["raw_field_frame"] = "global"
    path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="explicit rotor-material"):
        analyse(tmp_path)


def test_fixed_history_rejects_changed_mesh_even_at_the_same_element_count(tmp_path):
    write_pilot(tmp_path, coordinate_frame="rotor_material")
    folder = tmp_path / "position-0001"
    answer = folder / "model.ans"
    answer.write_text(answer.read_text().replace("12 0 0 0", "12.1 0 0 0"))
    path = folder / "position.json"
    record = json.loads(path.read_text())
    record["sha256"]["model.ans"] = hashlib.sha256(answer.read_bytes()).hexdigest()
    record["mesh_geometry_sha256"] = mesh_signature(answer)
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="mesh changed"):
        analyse(tmp_path)


def test_fixed_history_queries_cannot_rotate_material_points_a_second_time(tmp_path):
    write_pilot(tmp_path, coordinate_frame="rotor_material")
    folder = tmp_path / "position-0001"
    script = folder / "point-export.lua"
    script.write_text("mo_getpointvalues(0,0)")
    path = folder / "position.json"
    record = json.loads(path.read_text())
    record["sha256"][script.name] = hashlib.sha256(script.read_bytes()).hexdigest()
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="fixed rotor material points"):
        analyse(tmp_path)
