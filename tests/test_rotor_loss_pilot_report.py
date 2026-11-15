"""Reference evidence must be complete and bound to the actual material queries."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tools.rotor_loss_pilot_report import analyse, markdown_report

FIXTURE = "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def write_pilot(directory):
    fixture = Path(__file__).resolve().parents[1] / FIXTURE
    protocol = {"positions": 32, "speed_rpm": 3000, "fixture": FIXTURE,
                "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()}
    (directory / "protocol.json").write_text(json.dumps(protocol))
    corners = np.array([[[10, 0], [12, 0], [11, 2]]], dtype=float)
    points = corners.mean(axis=1)
    np.savetxt(directory / "reference-points.csv", points, delimiter=",")
    for index in range(33):
        position = directory / f"position-{index:04d}"
        position.mkdir()
        angle = -360*index/32
        radians = np.deg2rad(angle)
        rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
        global_corners, global_points = corners @ rotation.T, points @ rotation.T
        vector = np.array([1.0 + 0.1*np.cos(2*np.pi*3*index/32), 0.0]) @ rotation.T
        mesh = np.concatenate([global_corners.reshape(1, 6), vector.reshape(1, 2)], axis=1)
        np.savetxt(position / "rotor.csv", mesh, delimiter=",")
        np.savetxt(position / "points.csv", vector.reshape(1, 2), delimiter=",")
        (position / "point-export.lua").write_text(f"az,bx,by=mo_getpointvalues({global_points[0, 0]:.17g},{global_points[0, 1]:.17g})")
        record = {"index": index, "mechanical_angle_deg": angle, "wall_s": 0.1, "total_elements": 1,
                  "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in position.iterdir()}}
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
