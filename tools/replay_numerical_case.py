"""Replay one measured native case from the published numerical evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="case id in benchmarks/preview-evidence/results.json")
    parser.add_argument("--lane", default="native-standard", help="native-standard, native-fine, analytical or native")
    parser.add_argument("--output", required=True, type=Path, help="new JSON output file; existing files are never overwritten")
    args = parser.parse_args()
    from fastapi.testclient import TestClient

    from backend.public_main import app
    from backend.solver_environment import ISOLATED_RUNTIME

    if not ISOLATED_RUNTIME:
        parser.error("run this tool from the exported public runtime")
    if args.lane not in {"native-standard", "native-fine", "analytical", "native"}:
        parser.error("choose a native lane; FEMM is not included")
    if args.output.exists():
        parser.error("output already exists")
    if not args.output.parent.is_dir():
        parser.error("output parent directory does not exist")
    root = Path(__file__).resolve().parents[1]
    evidence_path = root / "benchmarks/preview-evidence/results.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    case = next((row for row in evidence["cases"] if row["case"] == args.case), None)
    measurement_candidate = evidence["candidate"]
    correction = evidence.get("commutation_precision_correction")
    if correction and correction["case"] == args.case:
        case = correction
        measurement_candidate = correction["candidate"]
    if case is None or args.lane not in case["lanes"]:
        parser.error("case/lane has no published native measurement; choose an available entry in the evidence JSON")
    request = case["lanes"][args.lane]["request"]
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/solve", json=request)
        response.raise_for_status()
        result = response.json()
    try:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
        commit = git.stdout.strip() if git.returncode == 0 else None
    except OSError:
        commit = None
    output = {
        "schema": "coilem.numerical_replay/v1",
        "case": args.case,
        "lane": args.lane,
        "current_commit": commit,
        "snapshot_manifest_sha256": hashlib.sha256((root / "snapshot-manifest.json").read_bytes()).hexdigest(),
        "replayer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "measurement_candidate": measurement_candidate,
        "runtime": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
        "request": request,
        "result": result,
        "note": "A replay is a measurement, not a numerical qualification or release approval.",
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
