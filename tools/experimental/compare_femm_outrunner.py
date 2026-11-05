"""Run the same-mesh FEMM/Magneto2D field diagnostic on the pinned LRK model."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from backend.experimental.femm_outrunner import ASSET_SHA256, FIXTURE_ID, SOURCE_SHA256, build_field_problem, read_femm_answer, summarize_field


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mesh", choices=("same", "native"), default="same")
    parser.add_argument("--gap-size-mm", type=float, default=0.05)
    parser.add_argument("--reuse-solve-dir", type=Path, help="Repostprocess an identical hashed input and binary without rerunning the field solve")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if any(args.out.iterdir()):
        raise ValueError("Use a new output directory so earlier attempts remain unchanged")
    reference_mesh = read_femm_answer(args.answer)
    if args.mesh == "native":
        from backend.experimental.outrunner_geometry import generate_native_mesh
        mesh = generate_native_mesh(gap_size_mm=args.gap_size_mm)
    else:
        mesh = reference_mesh
    problem = build_field_problem(mesh)
    problem_path = args.out / "magnetostatic_problem.json"
    report_path = args.out / "field_solution_report.json"
    problem_path.write_text(json.dumps(problem, allow_nan=False), encoding="utf-8")
    binary_sha = hashlib.sha256(args.binary.read_bytes()).hexdigest()
    mesh_record = {
        "nodes_mm": mesh.nodes_mm.tolist(), "triangles": mesh.triangles.tolist(), "label_ids": mesh.label_ids.tolist(),
        "dirichlet_nodes": mesh.dirichlet_nodes.tolist(), "provenance": mesh.provenance,
    }
    (args.out / "fixture_mesh.json").write_text(json.dumps(mesh_record, allow_nan=False))
    if args.reuse_solve_dir:
        old = args.reuse_solve_dir
        metadata = json.loads((old / "comparison.json").read_text())
        if metadata["binary_sha256"] != binary_sha or metadata["status"] != "DIAGNOSTIC_ONLY":
            raise ValueError("Reused solve must be complete and use the identical solver binary")
        if json.loads((old / "magnetostatic_problem.json").read_text()) != problem:
            raise ValueError("Reused solve's entire field input differs; run a fresh solve")
        report_path.write_bytes((old / "field_solution_report.json").read_bytes())
        (args.out / "solver-stdout.txt").write_text(f"Reused verified field solve from {old}\n")
        (args.out / "solver-stderr.txt").write_bytes((old / "solver-stderr.txt").read_bytes())
    else:
        command = [str(args.binary.resolve()), str(problem_path.resolve()), "--mode", "field", "-o", str(report_path.resolve())]
        process = subprocess.run(command, capture_output=True, text=True, timeout=300)
        (args.out / "solver-stdout.txt").write_text(process.stdout)
        (args.out / "solver-stderr.txt").write_text(process.stderr)
        if process.returncode:
            failure = {"status": "ERROR", "returncode": process.returncode,
                       "problem_sha256": hashlib.sha256(problem_path.read_bytes()).hexdigest(), "stderr": "solver-stderr.txt"}
            (args.out / "comparison.json").write_text(json.dumps(failure, indent=2)+"\n")
            process.check_returncode()
    report = json.loads(report_path.read_text())
    if not report["solution"]["convergence"]["converged"]:
        raise RuntimeError("Magneto2D did not converge")
    az = np.asarray(report["solution"]["az_nodal"])
    assert reference_mesh.reference_az is not None
    reference = summarize_field(reference_mesh, reference_mesh.reference_az)
    candidate = summarize_field(mesh, az)
    linkage_reference = np.asarray(reference["phase_linkage_Wb"])
    linkage_candidate = np.asarray(candidate["phase_linkage_Wb"])
    relative_az = None
    if args.mesh == "same":
        relative_az = float(np.linalg.norm(az-reference_mesh.reference_az)/np.linalg.norm(reference_mesh.reference_az))
    result = {"status": "DIAGNOSTIC_ONLY", "fixture_id": FIXTURE_ID,
              "source_sha256": SOURCE_SHA256, "asset_sha256": ASSET_SHA256,
              "binary_sha256": binary_sha, "field_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
              "answer_sha256": reference_mesh.provenance["answer_sha256"], "candidate_mesh": mesh.provenance,
              "problem_sha256": hashlib.sha256(problem_path.read_bytes()).hexdigest(), "solver_options": problem["options"],
              "material_law": "source-points-piecewise-linear-with-in-plane-fill; FEMM spline parity not yet established",
              "reference": reference, "candidate": candidate,
              "az_relative_L2": relative_az,
              "phase_linkage_relative_error": ((linkage_candidate-linkage_reference)/abs(linkage_reference)).tolist(),
              "convergence": report["solution"]["convergence"]}
    (args.out / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
