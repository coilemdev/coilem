"""Record default config, full-motor IR and mesh hashes from an explicit source checkout."""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    sys.path.insert(0, str(source))
    from backend.geometry_ir import build_geometry_ir
    from backend.gmsh_solver import run_gmsh_mesh_preview
    from backend.models import MotorConfig

    suite = json.loads((source / "benchmarks/cogging-refined-v1/measured-suite.json").read_text())
    cases = {}
    for case in suite["cases"]:
        fixture_path = next(job["fixture"] for job in case["jobs"] if job["stage"] == "native")
        fixture = source / fixture_path
        config = MotorConfig.model_validate_json(fixture.read_text())
        artifact = run_gmsh_mesh_preview(config, rotor_angle_deg=0)["solve_mesh_artifact"]
        cases[case["id"]] = {"fixture": fixture_path, "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "config_dump_sha256": digest(config.model_dump(mode="json")), "geometry_ir_sha256": digest(asdict(build_geometry_ir(config))),
            "full_motor_mesh_sha256": digest(artifact), "full_motor_mesh_triangles": len(artifact["mesh"]["triangles"])}
    record = {"source_config_sha256": hashlib.sha256((source / "backend/models/config.py").read_bytes()).hexdigest(), "cases": cases}
    args.out.write_text(json.dumps(record, indent=2))
    print(json.dumps({"source_config_sha256": record["source_config_sha256"], "cases": len(cases)}))


if __name__ == "__main__":
    main()
