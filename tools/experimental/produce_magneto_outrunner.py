"""Run resumable independent-mesh LRK angle/current sweeps with raw evidence."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from backend.experimental.femm_outrunner import ASSET_SHA256, SOURCE_SHA256, build_field_problem, phase_linkage
from backend.experimental.outrunner_geometry import generate_native_mesh
from backend.experimental.outrunner_stress import weighted_stress_torque
from backend.experimental.outrunner_sweep import SweepCase


def write_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temp.replace(path)


def archive(path: Path) -> str:
    raw = path.read_bytes()
    with gzip.open(path.with_suffix(path.suffix+".gz"), "wb", compresslevel=3) as stream:
        stream.write(raw)
    with gzip.open(path.with_suffix(path.suffix+".gz"), "rb") as stream:
        if stream.read() != raw:
            raise RuntimeError("Archive verification failed")
    path.unlink()
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gap-size-mm", type=float, default=0.05)
    parser.add_argument("--nonlinear-tolerance", type=float, default=1e-5)
    parser.add_argument("--family", nargs="*")
    parser.add_argument("--case", nargs="*")
    parser.add_argument("--reuse-from", type=Path, help="Copy identical completed requests after matching solver/physics policy and raw hashes")
    args = parser.parse_args()
    if not 1e-8 <= args.nonlinear_tolerance <= 1e-4:
        raise ValueError("Nonlinear tolerance outside reviewed range")
    binary_sha = hashlib.sha256(args.binary.read_bytes()).hexdigest()
    raw_manifest = json.loads(args.manifest.read_text())
    cases = [SweepCase.from_dict(raw) for raw in raw_manifest["cases"]]
    # Full and sliding orientation controls have the same native request.
    cases = [c for c in cases if c.family != "orientation" or c.reference_model == "full"]
    if args.family:
        cases = [c for c in cases if c.family in args.family]
    if args.case:
        cases = [c for c in cases if c.id in args.case]
    if not cases:
        raise ValueError("No requested cases")
    manifest = {"schema": "magneto_outrunner_sweep/v1", "source_sha256": SOURCE_SHA256, "asset_sha256": ASSET_SHA256,
                "binary_sha256": binary_sha, "gap_size_mm": args.gap_size_mm, "bulk_size_mm": 0.25,
                "mesh_policy": "outrunner_source_gap_interfaces/v2", "nonlinear_tolerance": args.nonlinear_tolerance,
                "material_law": "source-points-piecewise-linear-with-in-plane-fill; FEMM spline parity UNVERIFIED",
                "cases": [c.to_dict() for c in cases]}
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out/"manifest.json"
    if path.exists() and json.loads(path.read_text()) != json.loads(json.dumps(manifest)):
        raise ValueError("Output already belongs to a different experiment")
    write_json(path, manifest)
    if args.reuse_from:
        previous_manifest = json.loads((args.reuse_from/"manifest.json").read_text())
        if {k: v for k, v in previous_manifest.items() if k != "cases"} != {k: v for k, v in manifest.items() if k != "cases"}:
            raise ValueError("Reused solver, fixture, material or mesh policy differs")
        previous_cases = {x["id"]: x for x in previous_manifest["cases"]}
        for case in cases:
            old_folder, new_folder = args.reuse_from/case.id, args.out/case.id
            if json.loads(json.dumps(case.to_dict())) != previous_cases.get(case.id):
                continue
            if new_folder.exists() or not (old_folder/"result.json").exists():
                continue
            row = json.loads((old_folder/"result.json").read_text())
            if row["status"] != "COMPLETE" or row["case"] != previous_cases[case.id]:
                continue
            for name, expected in row["raw_sha256"].items():
                with gzip.open(old_folder/(name+".gz"), "rb") as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != expected:
                        raise ValueError("Reused field evidence changed")
            new_folder.mkdir()
            for name in ("result.json", "problem.json.gz", "field.json.gz", "mesh.json.gz", "stdout.txt", "stderr.txt"):
                shutil.copy2(old_folder/name, new_folder/name)
            write_json(new_folder/"reuse.json", {"from": str(old_folder.resolve()), "exact_case_policy_and_evidence_verified": True})
    mesh, previous_angle = None, None
    for case in cases:
        folder = args.out/case.id
        result_path = folder/"result.json"
        if result_path.exists():
            old = json.loads(result_path.read_text())
            if old["status"] != "COMPLETE" or old["case"] != json.loads(json.dumps(case.to_dict())):
                raise ValueError(f"Keep failed attempt and use a new output directory: {folder}")
            for name, expected in old["raw_sha256"].items():
                with gzip.open(folder/(name+".gz"), "rb") as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != expected:
                        raise ValueError("Retained raw field evidence hash mismatch")
            continue
        if folder.exists() and any(folder.iterdir()):
            folder.rename(folder.with_name(folder.name+f"_interrupted_{time.time_ns()}"))
        folder.mkdir(exist_ok=True)
        start = time.monotonic()
        try:
            if mesh is None or previous_angle != case.angle_ccw_deg:
                mesh = generate_native_mesh(case.angle_ccw_deg, args.gap_size_mm)
                previous_angle = case.angle_ccw_deg
            problem = build_field_problem(mesh, case.currents_A, case.angle_ccw_deg)
            problem["options"]["nonlinear"]["tolerance"] = args.nonlinear_tolerance
            problem_path = folder/"problem.json"
            problem_path.write_text(json.dumps(problem, allow_nan=False), encoding="utf-8")
            mesh_path = folder/"mesh.json"
            mesh_path.write_text(json.dumps({"nodes_mm": mesh.nodes_mm.tolist(), "triangles": mesh.triangles.tolist(),
                                            "label_ids": mesh.label_ids.tolist(), "dirichlet_nodes": mesh.dirichlet_nodes.tolist(),
                                            "provenance": mesh.provenance}, allow_nan=False), encoding="utf-8")
            report_path = folder/"field.json"
            process = subprocess.run([str(args.binary.resolve()), str(problem_path.resolve()), "--mode", "field", "-o", str(report_path.resolve())],
                                     capture_output=True, text=True, timeout=300)
            (folder/"stdout.txt").write_text(process.stdout)
            (folder/"stderr.txt").write_text(process.stderr)
            process.check_returncode()
            solution = json.loads(report_path.read_text())["solution"]
            if not solution["convergence"]["converged"]:
                raise RuntimeError("Nonconverged field cannot enter the comparison")
            az = np.asarray(solution["az_nodal"])
            torque = weighted_stress_torque(mesh, az)
            result = {"status": "COMPLETE", "qualification": "DIAGNOSTIC_ONLY", "case": case.to_dict(),
                      "phase_linkage_Wb": phase_linkage(mesh, az).tolist(),
                      "outer_rotor_torque_Nm": torque["outer_rotor_torque_Nm"], "weighted_stress": torque,
                      "mesh": mesh.provenance, "nodes": len(mesh.nodes_mm), "elements": len(mesh.triangles),
                      "convergence": solution["convergence"], "elapsed_s": time.monotonic()-start,
                      "raw_sha256": {file.name: archive(file) for file in (problem_path, report_path, mesh_path)}}
            write_json(result_path, result)
            print(json.dumps({"id": case.id, "torque_Nm": result["outer_rotor_torque_Nm"], "elapsed_s": result["elapsed_s"]}), flush=True)
        except Exception as exc:
            write_json(result_path, {"status": "ERROR", "case": case.to_dict(), "error": str(exc), "elapsed_s": time.monotonic()-start})
            raise


if __name__ == "__main__":
    main()
