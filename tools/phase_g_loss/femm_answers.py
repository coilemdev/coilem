"""Read-only reuse of explicitly matched, immutable Windows FEMM answers.

The unsmoothed first-order triangular B field is derived independently from
FEMM's nodal A_z and checked against every retained FEMM rotor CSV export.
No native field/gradient/loss function or FEMM field solve is used here.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import (
    POSITIONS,
    ROOT,
    SUITE,
    case_by_id,
    checkpoint,
    config_for,
    protocol,
    read,
    reference_resistance,
    sha,
    write,
    write_npz,
)


def answer_fields(path):
    text = Path(path).read_text(encoding="latin-1")
    if not re.search(r"\[Frequency\]\s*=\s*0(?:\s|$)", text):
        raise ValueError("Only magnetostatic FEMM answers can be reused")
    if not re.search(r"\[LengthUnits\]\s*=\s*millimeters", text):
        raise ValueError("FEMM answer units must be millimeters")
    lines = text.splitlines()
    cursor = next(i for i, line in enumerate(lines) if line.startswith("[NumBlockLabels]"))
    count = int(lines[cursor].split("=")[1])
    labels = [line.split() for line in lines[cursor + 1 : cursor + 1 + count]]
    materials = re.findall(r'<BlockName>\s*=\s*"([^"]+)"', text)
    region_labels = {}
    for name, group in (("stator", 0), ("rotor", 10)):
        region_labels[name] = [
            i
            for i, row in enumerate(labels)
            if int(row[6]) == group and 0 < int(row[2]) <= len(materials) and materials[int(row[2]) - 1].startswith("coilEM_M350_50A_")
        ]
        if not region_labels[name]:
            raise ValueError("FEMM answer has no unambiguous " + name + " steel labels")
    cursor = lines.index("[Solution]") + 1
    count = int(lines[cursor])
    nodes = np.asarray([[float(x) for x in line.split()[:3]] for line in lines[cursor + 1 : cursor + 1 + count]])
    cursor += count + 1
    count = int(lines[cursor])
    triangles = np.asarray([[int(x) for x in line.split()[:4]] for line in lines[cursor + 1 : cursor + 1 + count]])
    result = {}
    for name, ids in region_labels.items():
        selected = triangles[np.isin(triangles[:, 3], ids), :3]
        corners, az = nodes[selected, :2], nodes[selected, 2]
        u, v = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
        d1, d2 = az[:, 1] - az[:, 0], az[:, 2] - az[:, 0]
        determinant = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
        if np.any(determinant == 0):
            raise ValueError("Degenerate FEMM material cell")
        b = np.column_stack(((u[:, 0] * d2 - v[:, 0] * d1) / determinant, -(d1 * v[:, 1] - d2 * u[:, 1]) / determinant)) * 1000
        if not np.isfinite(b).all():
            raise ValueError("Nonfinite FEMM answer field")
        result[name + "_corners"], result[name] = corners, b
    return result


def validate_inputs(case, native, source):
    requested = config_for(case)
    old = read(source / "protocol.json")
    if (
        old.get("schema") != "coilem.matched_rotor_reference/v1"
        or old["positions"] != POSITIONS
        or old.get("motion_model") != "periodic-air-gap"
        or old.get("raw_field_frame") != "rotor_material"
        or old["gamma_deg"] != 180
        or old["requested_public_gamma_deg"] != 0
        or old["current_peak_A"] != case["current_peak_A"]
        or old["speed_rpm"] != 3000
        or old["mesh"] != case["femm_mesh"]
        or old["airgap_target_mm"] != case["femm_airgap_target_mm"]
        or old["airgap_arc_step_deg"] != case["femm_arc_step_deg"]
    ):
        raise ValueError("Existing FEMM history has different operating point, mesh or frame")
    fixture = ROOT / old["fixture"]
    if sha(fixture) != old["fixture_sha256"]:
        raise ValueError("Original FEMM fixture changed")
    original = read(fixture)
    for name in ("stator", "rotor", "materials", "topology"):
        if original[name] != requested[name]:
            raise ValueError("Reused FEMM physical input differs: " + name)
    winding = {k: v for k, v in requested["winding"].items() if k != "wire"}
    if winding != {k: v for k, v in original["winding"].items() if k != "wire"}:
        raise ValueError("Reused FEMM winding geometry differs")
    if original.get("rotor_layout", "inner") != "inner" or not case["rotor_supported"]:
        raise ValueError("Only already audited inner-rotor histories are reusable here")
    if old["steel_bh_sha256"] != sha(ROOT / "materials/electrical-steel/M350-50A.csv"):
        raise ValueError("Reused FEMM material curve differs")
    if old["matched_magnet"]["remanence_T"] != 1.315 or old["matched_magnet"]["relative_permeability"] != 1.05:
        raise ValueError("Reused FEMM magnet properties differ")
    if old["native_loss_material"]["coefficients"] != native["coefficients"]:
        raise ValueError("Reused FEMM coefficient contract differs")
    return old


def collect(args, mapping):
    case = case_by_id(args.case)
    source = Path(mapping["history"]).resolve()
    source_code = Path(mapping["source_checkout"]).resolve()
    old_protocol = read(source / "protocol.json")
    native = read(args.native / "protocol.json")
    analysis = read(args.native / "analysis.json")
    if not analysis["numerical_history_pass"] or analysis["protocol_sha256"] != sha(args.native / "protocol.json"):
        raise ValueError("Complete audited native loss history before reference extraction")
    validate_inputs(case, native, source)
    from tools.femm_reference import runtime
    from tools.femm_reference.rotor_airgap import mesh_signature
    from tools.femm_reference.rotor_matched_history import model_audit

    package = source_code / "tools/femm_reference"
    runtime.verify_sources(package)
    identity = old_protocol["reference_identity"]
    if sha(package / "source-manifest.json") != identity["source_manifest_sha256"]:
        raise ValueError("Frozen reference source manifest changed")
    for name, digest in identity["implementation_sha256"].items():
        if sha(package / name) != digest:
            raise ValueError("Original FEMM producer source changed: " + name)
    preparation = read(source / "preparation.json")
    for name, digest in preparation["sha256"].items():
        if sha(source / name) != digest:
            raise ValueError("Original FEMM preparation changed")
    coils = []
    for name, block in preparation["coils"].items():
        slot = int(re.fullmatch(r"Coil_v3_s(\d+)_l(\d+)", name)[1])
        coils.append(block | {"slot": slot})
    expected = {
        "schema": "coilem.phase_g_history/v1",
        "solver": "femm",
        "case": case,
        "requested_config": config_for(case),
        "suite_sha256": sha(SUITE),
        "positions": POSITIONS,
        "collection_speed_rpm": 3000,
        "evaluation_speeds_rpm": [1500, 3000],
        "coefficients": native["coefficients"],
        "native_protocol_sha256": sha(args.native / "protocol.json"),
        "native_analysis_sha256": sha(args.native / "analysis.json"),
        "rotor_status": native["rotor_status"],
        "rotor_unavailable_reason": None,
        "electrical_contract": reference_resistance(config_for(case), coils),
        "motion": "original fixed-mesh periodic-air-gap FEMM history; read-only answer extraction",
        "reused_source_history": str(source),
        "reused_source_checkout": str(source_code),
        "reused_protocol_sha256": sha(source / "protocol.json"),
        "reference_identity": identity,
        "extractor_sha256": sha(__file__),
        "new_femm_field_solves": 0,
        "native_fields_used_to_compute_reference": False,
        "collector_commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
    }
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    protocol(directory, expected)
    geometry_path = directory / "material-geometry.npz"
    geometry = dict(np.load(geometry_path)) if geometry_path.exists() else None
    shard, shards = map(int, args.shard.split("/"))
    new = 0
    for index in range(POSITIONS + 1):
        if index % shards != shard or checkpoint(directory, index):
            continue
        if args.limit is not None and new >= args.limit:
            break
        started = time.perf_counter()
        original = source / f"position-{index:04d}"
        record = read(original / "position.json")
        if record["mechanical_angle_deg"] != -360 * index / POSITIONS:
            raise ValueError("Original FEMM answer pose differs")
        for name, digest in record["sha256"].items():
            if sha(original / name) != digest:
                raise ValueError("Original raw FEMM checkpoint changed: " + str(original / name))
        applied = read(original / "applied-excitation.json")
        model_audit((original / "model.fem").read_text(encoding="latin-1"), record["mechanical_angle_deg"], applied, old_protocol["matched_magnet"])
        if record["solution_current_error_At"] > 1e-8 or mesh_signature(original / "model.ans") != preparation["mesh_geometry_sha256"]:
            raise ValueError("Original FEMM current or fixed-mesh audit failed")
        fields = answer_fields(original / "model.ans")
        exported = np.loadtxt(original / "rotor.csv", delimiter=",", ndmin=2)
        if not np.array_equal(fields["rotor_corners"].reshape(-1, 6), exported[:, :6]) or np.max(np.abs(fields["rotor"] - exported[:, 6:])) > 1e-9:
            raise ValueError("Independent answer extraction differs from original FEMM unsmoothed fields")
        corners = {key: value for key, value in fields.items() if key.endswith("_corners")}
        if geometry is None:
            if shards != 1 or index != 0:
                raise ValueError("Bootstrap original zero-pose integration geometry first")
            geometry = corners
            write_npz(geometry_path, **geometry)
        elif any(not np.array_equal(corners[key], geometry[key]) for key in geometry):
            raise ValueError("Original FEMM material geometry changed")
        output = directory / f"position-{index:04d}"
        output.mkdir(exist_ok=True)
        write_npz(output / "fields.npz", stator=fields["stator"], rotor=fields["rotor"])
        write(
            output / "position.json",
            {
                "index": index,
                "angle_deg": record["mechanical_angle_deg"],
                "wall_s": time.perf_counter() - started,
                "protocol_sha256": sha(directory / "protocol.json"),
                "geometry_sha256": sha(geometry_path),
                "source_answer_sha256": sha(original / "model.ans"),
                "original_checkpoint_sha256": sha(original / "position.json"),
                "original_femm_wall_s": record["wall_s"],
                "answer_to_export_max_difference_T": float(np.max(np.abs(fields["rotor"] - exported[:, 6:]))),
                "sha256": {"fields.npz": sha(output / "fields.npz")},
            },
        )
        print(f"{args.case}: reused FEMM answer {index}/{POSITIONS}", flush=True)
        new += 1
