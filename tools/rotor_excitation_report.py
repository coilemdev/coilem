"""Audit the three fresh FEMM/native field anchors; never infer loss agreement."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from tools.femm_reference.rotor_airgap import mesh_signature
from tools.rotor_closure_report import boundary_pose
from tools.rotor_native_pilot import sha


def saved_current_error(model, applied):
    saved = {}
    for block in re.findall(r"<BeginBlock>(.*?)<EndBlock>", model, flags=re.S):
        name = re.search(r'<BlockName>\s*=\s*"([^"]+)"', block)
        density = re.search(r"<J_re>\s*=\s*([^\s]+)", block)
        if name and name[1].startswith("Coil_v3_"):
            saved[name[1]] = float(density[1])
    if saved.keys() != applied.keys():
        raise ValueError("saved FEMM winding materials differ from the applied audit")
    return max(abs(saved[name]*entry["area_mm2"]-entry["ampere_turns"]) for name, entry in applied.items())


def analyse(directory, native, bridge=None):
    directory, native = Path(directory), Path(native)
    protocol = json.loads((directory / "protocol.json").read_text())
    if (protocol["kind"] != "excitation_probe" or protocol["loss_watts"] is not None
            or protocol["raw_field_frame"] != "rotor_material" or not protocol["fresh_unsolved_base_each_pose"]):
        raise ValueError("FEMM anchors are not the explicit fresh material-frame probe")
    if sha(native / "protocol.json") != protocol["native_preflight_protocol_sha256"]:
        raise ValueError("native preflight identity differs from FEMM excitation source")
    points = np.loadtxt(directory / "material-query-points.csv", delimiter=",", ndmin=2)
    if not np.array_equal(points, np.loadtxt(native / "material-query-points.csv", delimiter=",", ndmin=2)):
        raise ValueError("native and FEMM material query locations differ")
    rows, meshes = [], []
    for index, angle in enumerate(protocol["angles_native_ccw_deg"]):
        folder = directory / f"position-{index:04d}"
        native_folder = native / folder.name
        record = json.loads((folder / "position.json").read_text())
        for name, digest in record["sha256"].items():
            if Path(name).name != name or sha(folder / name) != digest:
                raise ValueError("FEMM anchor artifact hash mismatch")
        excitation = json.loads((native_folder / "excitation.json").read_text())
        if (sha(native_folder / "excitation.json") != protocol["native_excitation_sha256"][index]
                or excitation["native_rotor_mechanical_deg"] != angle or excitation["gate"] != "PASS"):
            raise ValueError("FEMM anchor excitation source changed")
        model = (folder / "model.fem").read_text(encoding="latin-1")
        previous = re.search(r'^\[PrevSoln\]\s*=\s*"([^"]*)"', model, flags=re.M)
        if boundary_pose(model) != angle or previous is None or previous[1]:
            raise ValueError("FEMM anchor motion or fresh-solve contract differs")
        signature = mesh_signature(folder / "model.ans")
        if signature != record["mesh_sha256"]:
            raise ValueError("FEMM anchor mesh hash differs")
        meshes.append(signature)
        query_xy = np.asarray(re.findall(r"mo_getpointvalues\(([^,]+),([^\)]+)\)", (folder / "point-export.lua").read_text()), dtype=float)
        if query_xy.shape != points.shape or not np.allclose(query_xy, points, rtol=0, atol=1e-10):
            raise ValueError("FEMM queries moved out of their registered material frame")
        applied = json.loads((folder / "applied-excitation.json").read_text())
        for entry in applied.values():
            expected = excitation["phase_ampere_turns"][entry["phase"]]*(1 if entry["direction"] == "in" else -1)
            if abs(expected-entry["ampere_turns"]) > 1e-10:
                raise ValueError("FEMM winding excitation differs from native phase ampere-turns")
        current_error = saved_current_error(model, applied)
        if current_error > 1e-10:
            raise ValueError("saved FEMM current density does not reproduce native ampere-turns")
        actual = np.loadtxt(native_folder / "material-queries.csv", delimiter=",", ndmin=2)
        reference = np.loadtxt(folder / "points.csv", delimiter=",", ndmin=2)
        if actual.shape != reference.shape or reference.shape != points.shape or not np.isfinite(actual-reference).all():
            raise ValueError("invalid field anchor arrays")
        if bridge:
            bridge_folder = Path(bridge) / folder.name
            if (sha(bridge_folder / "excitation.json") != sha(native_folder / "excitation.json")
                    or not np.array_equal(actual, np.loadtxt(bridge_folder / "material-queries.csv", delimiter=",", ndmin=2))):
                raise ValueError("updated preflight does not reproduce original native excitation and queries")
        rms = float(np.sqrt(np.mean((actual-reference)**2)))
        rows.append({"index": index, "native_ccw_angle_deg": angle, "query_points": len(points), "rms_difference_T": rms,
                     "relative_rms_difference": rms/float(np.sqrt(np.mean(reference**2))),
                     "maximum_component_difference_T": float(np.max(abs(actual-reference))),
                     "maximum_saved_ampere_turn_error": current_error, "native_preflight_bridge_exact": bool(bridge)})
    if len(set(meshes)) != 1:
        raise ValueError("FEMM anchor mesh changed with motion")
    return {"schema": "coilem.rotor_excitation_comparison/v1", "protocol_sha256": sha(directory / "protocol.json"),
            "analysis_source_sha256": sha(__file__), "excitation_gate": "PASS", "fixed_mesh_gate": "PASS", "field_comparisons": rows,
            "loss_watts": None, "loss_agreement_gate": "NOT_RUN", "legacy_47mW_target_eligible": False,
            "bridge_protocol_sha256": sha(Path(bridge) / "protocol.json") if bridge else None, "full_matrix_started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("native_preflight", type=Path)
    parser.add_argument("--bridge", type=Path)
    args = parser.parse_args()
    result = analyse(args.directory, args.native_preflight, args.bridge)
    (args.directory / "excitation-analysis.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
