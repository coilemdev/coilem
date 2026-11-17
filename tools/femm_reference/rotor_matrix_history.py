"""Fixture-aware input adapter over the audited matched FEMM field collector."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from tools.femm_reference.rotor_loss_pilot import sha
from tools.femm_reference.rotor_matched_history import main as collect
from tools.rotor_matrix_contract import CASES, validate_excitation

ROOT = Path(__file__).resolve().parents[2]


def native_inputs(directory, case_id):
    protocol = json.loads((directory / "protocol.json").read_text())
    analysis = json.loads((directory / "analysis.json").read_text())
    config = json.loads((directory / "native-config.json").read_text())
    case = CASES[case_id]
    if (protocol.get("schema") != "coilem.native_rotor_matrix/v1" or protocol["matrix_case_id"] != case_id
            or protocol["positions"] != 384 or protocol.get("motion_model") != "fixed-material"
            or protocol["fixture"] != case["fixture"] or protocol["fixture_sha256"] != sha(ROOT / case["fixture"])
            or protocol["current_peak_A"] != case["current_peak_A"] or protocol["speed_rpm"] != 3000
            or protocol["requested_gamma_deg"] != 0 or protocol["native_gamma_deg"] != 180
            or protocol["mechanical_angles_deg"] != [-360*i/384 for i in range(385)]
            or not analysis["native_history_numerical_gates_pass"] or analysis["speed_rpm"] != 3000
            or analysis["protocol_sha256"] != sha(directory / "protocol.json")
            or sha(directory / "native-config.json") != protocol["native_config_sha256"]):
        raise ValueError("Reference needs the registered, audited native matrix condition")
    params = config["solve_params"]
    winding = config["winding"]
    expected = {"pole_pairs": 4, "phase_offset_deg": 60.0,
        "peak_ampere_turns": case["current_peak_A"] * winding["turns_per_coil"],
        "native_gamma_deg": 180.0, "phase_offsets_deg": {"A": 0, "B": 120, "C": 240}}
    if (protocol["excitation_parameters"] != expected or params["current_angle_deg"] != 180
            or params["current_amplitude_A"] != case["current_peak_A"] or params["rated_speed_rpm"] != 3000
            or params.get("symmetry", "full") != "full" or params["magnet_temperature_C"] is not None
            or params["phase_connection"] != "wye" or params["excitation_mode"] != "sinusoidal"
            or config["rotor"]["pole_count"] != 8 or config["stator"]["slot_count"] != 12
            or winding["type"] != "concentrated" or winding["layers"] != 1 or winding["parallel_paths"] != 1
            or config["materials"]["magnet_grade"] != "N42"
            or any(config["materials"][key] != "M350-50A" for key in ("rotor_steel", "stator_steel"))):
        raise ValueError("Matrix phase convention, materials or domain changed")
    for name, digest in protocol["identity"]["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Native matrix collection source changed: {name}")
    material_source = ROOT / "solvers/magneto2d/src/materials.rs"
    match = re.search(r'"N42"\s*=>\s*\(([0-9.]+),\s*([0-9.]+)\)', material_source.read_text())
    if match is None:
        raise ValueError("Native magnet constants must be explicit")
    magnet = {"grade": "N42", "remanence_T": float(match[1]), "relative_permeability": float(match[2]),
        "native_source_sha256": sha(material_source)}
    first_path = directory / "position-0000/native_report.json"
    report = json.loads(first_path.read_text())
    if (report["solver_environment"]["policy"] != "request-only-v1"
            or "COILEM_MAGNET_BR_SCALE" in report["solver_environment"]["options"]):
        raise ValueError("Native matrix magnet environment differs")
    excitations, digests = [], []
    for i, angle in enumerate(protocol["mechanical_angles_deg"]):
        position = directory / f"position-{i:04d}"
        record = json.loads((position / "position.json").read_text())
        path = position / "excitation.json"
        digest = sha(path)
        if record["index"] != i or record["sha256"]["excitation.json"] != digest:
            raise ValueError("Native matrix excitation checkpoint changed")
        if i == 0 and record["sha256"]["native_report.json"] != sha(first_path):
            raise ValueError("Native zero report changed")
        excitation = json.loads(path.read_text())
        validate_excitation(excitation, angle, expected)
        excitations.append(excitation)
        digests.append(digest)
    template_path = directory / "material-template.json"
    if sha(template_path) != protocol["material_template_sha256"]:
        raise ValueError("Native matrix material template changed")
    template = json.loads(template_path.read_text())
    nodes = np.asarray(template["mesh"]["nodes"])
    triangles = np.asarray(template["mesh"]["triangles"], dtype=int)
    ids = np.asarray(template["element_region_ids"])
    regions = []
    for region in template["physics_contract"]["regions"]:
        if region["kind"] not in ("Magnet", "SlotWinding"):
            continue
        corners = nodes[triangles[ids == region["id"]]]
        u, v = corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]
        weights = abs(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0])
        centre = np.average(corners.mean(axis=1), weights=weights, axis=0)
        regions.append(region | {"centroid_mm": centre.tolist()})
    return {"protocol": protocol, "analysis": analysis, "config": config, "magnet": magnet,
        "excitations": excitations, "excitation_sha256": digests, "regions": regions,
        "protocol_sha256": sha(directory / "protocol.json"), "analysis_sha256": sha(directory / "analysis.json"),
        "first_report_sha256": sha(first_path), "config_sha256": sha(directory / "native-config.json")}


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--case", choices=CASES, required=True)
    args, remaining = parser.parse_known_args()
    collect(remaining, native_provider=lambda directory: native_inputs(directory, args.case),
        fixture=ROOT / CASES[args.case]["fixture"], matrix_case_id=args.case)


if __name__ == "__main__":
    main()
