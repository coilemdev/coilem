"""Verify the bounded fixed-mesh FEMM closure probe, without qualifying loss watts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from tools.femm_reference.rotor_airgap import BOUNDARY, mesh_signature

POSES = [0.0, -3.75, -90.0, -360.0, 0.0]
REQUIRED = {"model.fem", "model.ans", "rotor.csv", "points.csv", "point-export.lua", "mesh-export.lua"}


def closure_metrics(initial, endpoint, tolerances):
    a, b = np.asarray(initial), np.asarray(endpoint)
    if a.ndim != 2 or a.shape != b.shape or a.shape[1] != 2 or not len(a):
        raise ValueError("closure requires matching material points and two B components")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("closure fields must be finite")
    delta = b-a
    maximum = float(np.max(np.abs(delta)))
    rms = float(np.sqrt(np.mean(delta**2)))
    return {"max_component_difference_T": maximum, "rms_component_difference_T": rms,
            "gate": "PASS" if maximum <= tolerances["max_component_T"] and rms <= tolerances["rms_component_T"] else "FAIL"}


def boundary_pose(model):
    blocks = re.findall(r"<BeginBdry>(.*?)<EndBdry>", model, flags=re.S | re.I)
    for block in blocks:
        name = re.search(r'<BdryName>\s*=\s*"([^"]+)"', block, flags=re.I)
        if name and name[1] == BOUNDARY:
            values = dict((key.lower(), value.strip()) for key, value in re.findall(r"<(\w+)>\s*=\s*([^\r\n]+)", block))
            if int(values["bdrytype"]) != 6 or float(values["outerangle"]) != 0:
                raise ValueError("the fixed-stator periodic air-gap boundary changed")
            return float(values["innerangle"])
    raise ValueError("the periodic air-gap boundary is missing")


def analyse_closure(directory):
    directory = Path(directory)
    protocol = json.loads((directory / "protocol.json").read_text())
    if (protocol.get("collection_kind") != "closure_probe" or protocol.get("motion_model") != "periodic-air-gap"
            or protocol.get("mechanical_angles_deg") != POSES or not protocol.get("independent_base_reload")):
        raise ValueError("this report requires the independently reloaded five-pose closure protocol")
    if protocol.get("raw_mesh_frame") != "rotor_material" or protocol.get("raw_field_frame") != "rotor_material":
        raise ValueError("closure queries must be in the fixed rotor-material frame")
    points = np.loadtxt(directory / "reference-points.csv", delimiter=",", ndmin=2)
    fields, meshes, records, corners = [], [], [], []
    for index, expected_angle in enumerate(POSES):
        folder = directory / f"position-{index:04d}"
        record = json.loads((folder / "position.json").read_text())
        if record["index"] != index or record["mechanical_angle_deg"] != expected_angle:
            raise ValueError("the closure pose differs from the registered probe")
        if not REQUIRED.issubset(record["sha256"]):
            raise ValueError("closure evidence is missing required artifacts")
        for name, digest in record["sha256"].items():
            if Path(name).name != name or hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
                raise ValueError("closure artifact hash mismatch")
        model_text = (folder / "model.fem").read_text(encoding="latin-1")
        previous = re.search(r'^\[PrevSoln\]\s*=\s*"([^"]*)"', model_text, flags=re.M)
        if previous is None or previous[1]:
            raise ValueError("closure requires fresh solves without a previous-solution seed")
        saved_angle = boundary_pose(model_text)
        if saved_angle != expected_angle:
            raise ValueError("saved air-gap angle differs from the unwrapped requested pose")
        signature = mesh_signature(folder / "model.ans")
        if signature != record["mesh_geometry_sha256"]:
            raise ValueError("recorded mesh geometry hash is incorrect")
        queries = re.findall(r"mo_getpointvalues\(([^,]+),([^\)]+)\)", (folder / "point-export.lua").read_text())
        query_xy = np.asarray(queries, dtype=float)
        if query_xy.shape != points.shape or not np.allclose(query_xy, points, rtol=0, atol=1e-10):
            raise ValueError("air-gap-model queries must stay at the same drawn rotor-material points")
        mesh = np.loadtxt(folder / "rotor.csv", delimiter=",", ndmin=2)
        queried = np.loadtxt(folder / "points.csv", delimiter=",", ndmin=2)
        if mesh.shape[1] != 8 or queried.shape != points.shape or not np.isfinite(mesh).all():
            raise ValueError("invalid rotor-field exports")
        corners.append(mesh[:, :6].reshape(-1, 3, 2))
        if not np.allclose(corners[-1].mean(axis=1), points, rtol=0, atol=1e-10):
            raise ValueError("rotor mesh no longer matches its fixed material integration points")
        fields.append(queried)
        meshes.append(signature)
        records.append(record)
    mesh_pass = len(set(meshes)) == 1 and all(np.array_equal(corners[0], c) for c in corners[1:])
    closure = closure_metrics(fields[0], fields[3], protocol["closure_tolerances"])
    repeat = closure_metrics(fields[0], fields[4], protocol["closure_tolerances"])
    interior = closure_metrics(fields[0], fields[1], protocol["closure_tolerances"])
    interior_changed = interior.pop("gate") == "FAIL"
    quarter_turn = closure_metrics(fields[0], fields[2], protocol["closure_tolerances"])
    quarter_turn.pop("gate")  # Ninety degrees has not been established as a rotor-history period.
    passed = mesh_pass and closure["gate"] == repeat["gate"] == "PASS" and interior_changed
    return {
        "status": "PILOT_NOT_QUALIFIED", "closure_probe_gate": "PASS" if passed else "FAIL",
        "scope": "one SPM, five fresh solves; no full-turn loss-history or matrix qualification",
        "mechanical_angles_deg": POSES, "raw_coordinate_frame": "rotor_material",
        "mesh_invariance_gate": "PASS" if mesh_pass else "FAIL", "distinct_triangle_meshes": len(set(meshes)),
        "mesh_geometry_sha256": meshes, "rotor_elements": len(points),
        "total_elements": [r["total_elements"] for r in records],
        "closure": closure, "repeat_zero": repeat, "interior_motion": interior,
        "interior_motion_changed": interior_changed,
        "ninety_degree_difference": quarter_turn,
        "closure_tolerances": protocol["closure_tolerances"],
        "sum_position_wall_s": sum(r["wall_s"] for r in records),
        "protocol_sha256": hashlib.sha256((directory / "protocol.json").read_bytes()).hexdigest(),
        "report_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "loss_watts": None, "angular_loss_convergence": "NOT_RUN", "mesh_loss_convergence": "NOT_RUN",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = analyse_closure(args.directory)
    (args.directory / "closure-analysis.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
