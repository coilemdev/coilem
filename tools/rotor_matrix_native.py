"""Fresh fixed-material native histories for the approved reduced #306 matrix."""
from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend import gmsh_solver
from backend.magneto2d_adapter import run_magneto2d_report
from backend.models import MotorConfig
from backend.rotor_motion_mesh import FixedMaterialRotorMesh
from backend.solver import _clockwise_excitation_config
from tools.rotor_matrix_contract import CASES, excitation_parameters, material_query_points, validate_excitation
from tools.rotor_native_pilot import audit_excitation, field_sample, query_sample, sha, source_identity, validate_convergence, write

ROOT = Path(__file__).resolve().parents[1]


def configured(case_id):
    case = CASES[case_id]
    requested = MotorConfig.model_validate_json((ROOT / case["fixture"]).read_text())
    requested.solve_params.current_amplitude_A = case["current_peak_A"]
    requested.solve_params.current_angle_deg = 0.0
    requested.solve_params.rated_speed_rpm = 3000
    requested.solve_params.mesh_density = "normal"
    requested.solve_params.solve_quality = "custom"
    requested.solve_params.symmetry = "full"
    requested.solve_params.magneto2d_workers = 1
    return requested, _clockwise_excitation_config(requested)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    shard, shards = map(int, args.shard.split("/"))
    if not 0 <= shard < shards or (args.limit is not None and args.limit < 1):
        parser.error("Invalid worker partition or limit")
    for key in tuple(os.environ):
        if key.startswith(("COILEM_", "MAGNETO2D_", "FEMM_", "GMSH_")):
            os.environ.pop(key)
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["COILEM_MAGNETO2D_BINARY"] = str(args.binary.resolve())
    os.environ["COILEM_USER_DATA_ROOT"] = str(directory / f"user-data-{shard}-of-{shards}")
    case = CASES[args.case]
    requested, config = configured(args.case)
    parameters = excitation_parameters(config)
    template_path = directory / "material-template.json"
    if not template_path.exists():
        if shards != 1 or (directory / "protocol.json").exists():
            raise ValueError("Prepare a single zero pose before starting matrix shards")
        control = case["native_base_lc_mm"]
        context = patch.object(gmsh_solver, "_base_lc_mm", return_value=control) if control else nullcontext()
        with context:
            template = gmsh_solver.run_gmsh_mesh_preview(config, rotor_angle_deg=0)["solve_mesh_artifact"]
        write(template_path, template)
    template = json.loads(template_path.read_text())
    motion = FixedMaterialRotorMesh(template, angular_divisions=case["native_airgap_divisions"],
                                    radial_layers=case["native_airgap_layers"])
    points = material_query_points(template)
    query_path = directory / "material-query-points.csv"
    if not query_path.exists():
        np.savetxt(query_path, points, delimiter=",", fmt="%.17g")
    if not np.array_equal(np.loadtxt(query_path, delimiter=",", ndmin=2), points):
        raise ValueError("Matrix material query coordinates changed")
    identity = source_identity(args.binary)
    for name in ("tools/rotor_matrix_native.py", "tools/rotor_matrix_contract.py"):
        identity["source_sha256"][name] = sha(ROOT / name)
    angles = [-360*i/384 for i in range(385)]
    config_path = directory / "native-config.json"
    if config_path.exists():
        if json.loads(config_path.read_text()) != config.model_dump(mode="json"):
            raise ValueError("Native matrix configuration changed")
    else:
        if (directory / "protocol.json").exists():
            raise ValueError("Native matrix configuration was lost")
        write(directory / "requested-config.json", requested.model_dump(mode="json"))
        write(config_path, config.model_dump(mode="json"))
    protocol = {"schema": "coilem.native_rotor_matrix/v1", "kind": "full_turn_history", "matrix_case_id": args.case,
        "fixture": case["fixture"], "fixture_sha256": sha(ROOT / case["fixture"]), "positions": 384,
        "mechanical_angles_deg": angles, "mesh": "normal", "excitation_frame": "public-clockwise",
        "requested_gamma_deg": 0.0, "native_gamma_deg": 180.0, "current_peak_A": case["current_peak_A"],
        "speed_rpm": 3000.0, "evaluation_speeds_rpm": [1500.0, 3000.0], "expected_native_nonlinear_tolerance": 1e-5,
        "native_field_frame": "global", "export_frame": "rotor_material", "fresh_field_solves": True,
        "motion_model": "fixed-material", "material_template_sha256": sha(template_path),
        "material_query_points_sha256": sha(query_path), "excitation_parameters": parameters,
        "native_template_control": {k: v for k, v in case.items() if k.startswith("native_")},
        "airgap_angular_divisions": case["native_airgap_divisions"], "airgap_radial_layers": case["native_airgap_layers"],
        "closure_tolerances": {"max_component_T": 1e-6, "rms_component_T": 1e-7}, "identity": identity,
        "native_config_sha256": sha(config_path),
        "mesh_policy": "fixed material cells; conforming air-gap retriangulation; fresh field solve per pose",
        "full_matrix_started": True}
    path = directory / "protocol.json"
    if path.exists():
        if not args.resume or json.loads(path.read_text()) != protocol:
            raise ValueError("Matrix case, sources, binary or mesh controls changed")
    else:
        write(path, protocol)
    started, new = time.perf_counter(), 0
    for index, angle in enumerate(angles):
        if index % shards != shard:
            continue
        output = directory / f"position-{index:04d}"
        checkpoint = output / "position.json"
        if checkpoint.exists():
            record = json.loads(checkpoint.read_text())
            if record["index"] != index or any(sha(output/name) != h for name, h in record["sha256"].items()):
                raise ValueError("Existing native matrix checkpoint changed")
            continue
        if args.limit is not None and new >= args.limit:
            break
        output.mkdir(exist_ok=True)
        begin = time.perf_counter()
        artifact = motion.at_angle(config, angle)
        excitation = audit_excitation(artifact, config, angle)
        validate_excitation(excitation, angle, parameters)
        report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=angle, solve_mesh_artifact=artifact,
                                     persist_artifacts_dir=output, artifact_prefix="native")
        convergence = report["solve_info"]["nonlinear_convergence"]
        validate_convergence(convergence, 1e-5)
        sample = field_sample(report, angle)
        np.savetxt(output / "rotor-material.csv", np.column_stack((sample.corners_mm.reshape(-1, 6), sample.bx_t, sample.by_t)),
                   delimiter=",", fmt="%.17g")
        np.savetxt(output / "material-queries.csv", query_sample(sample, points), delimiter=",", fmt="%.17g")
        write(output / "excitation.json", excitation)
        record = {"index": index, "mechanical_angle_deg": angle, "native_gamma_deg": 180.0,
            "rotor_elements": len(sample.bx_t), "total_elements": report["mesh_info"]["num_triangles"],
            "wall_s": time.perf_counter()-begin, "convergence": convergence,
            "material_motion_mesh": artifact["mesh"]["info"]["material_motion_mesh"],
            "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
        write(checkpoint, record)
        print(json.dumps({k: record[k] for k in ("index", "mechanical_angle_deg", "total_elements", "rotor_elements", "wall_s")}), flush=True)
        new += 1
    write(directory / f"collection-{shard}-of-{shards}.json", {"new_positions": new,
        "invocation_wall_s": time.perf_counter()-started, "positions_present": len(list(directory.glob("position-*/position.json")))})


if __name__ == "__main__":
    main()
