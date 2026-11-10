"""Collect and independently check the registered three-case very-fine cohort."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from backend.benchmark_suite import cli
from backend.benchmark_suite.cogging_metrics import evaluate_cogging
from backend.benchmark_suite.contract import canonical, checked_json, read, sha
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.record import identity_platform_key
from backend.benchmark_suite.references import load_bundle, load_suite, require_reviewed_bundle

ROOT = Path(__file__).resolve().parents[1]
SUITE = Path("benchmarks/cogging-refined-v1/benchmark_spec.json")
BUNDLE = Path("benchmarks/reference-baselines/cogging-refined-20261110")


def assess(directory, candidate):
    spec = load_suite(ROOT / SUITE)
    reference, fields, bundle_sha = load_bundle(ROOT / BUNDLE, spec)
    require_reviewed_bundle(ROOT / BUNDLE, reference, spec)
    manifest_path = directory / "run_manifest.json"
    manifest = read(manifest_path)
    identity = manifest["identity"]
    if (manifest["status"] != "COMPLETE" or manifest.get("smoke") or identity.get("dirty") is not False
            or identity["commit"] != candidate or manifest["reference_mode"] != "FROZEN_REFERENCE"
            or manifest["selection"]["spec_sha256"] != sha(ROOT / SUITE)
            or manifest["selection"]["bundle_sha256"] != bundle_sha):
        raise ValueError("Need a complete clean candidate run against the exact registered refined cohort")
    source_hashes = {name: sha(ROOT / name) for name in physics_sources(ROOT)}
    if any(identity["source_files"].get(name) != digest for name, digest in source_hashes.items()):
        raise ValueError("Candidate physics differ from the recorded collection")
    by_id = {case["id"]: case for case in spec["cases"]}
    if len(manifest["jobs"]) != 3 or {job["case_id"] for job in manifest["jobs"]} != set(by_id):
        raise ValueError("Incomplete or unexpected qualification selection")
    rows = []
    hashes = {"run_manifest.json": sha(manifest_path)}
    for job in manifest["jobs"]:
        cid = job["case_id"]
        case = by_id[cid]
        request = read(directory / job["request"])
        config = checked_json(ROOT, case["jobs"][0]["fixture"], case["jobs"][0]["fixture_sha256"])
        if (job["status"] != "COMPLETE" or request["identity"] != identity
                or sha(directory / job["request"]) != job["request_sha256"]
                or canonical(request["config"]) != case["jobs"][0]["input_sha256"]
                or request["config"] != config or config["solve_params"]["mesh_density"] != "very_fine"):
            raise ValueError(f"Qualification request is not the registered very-fine fixture: {cid}")
        measured = cli.verify_artifact(directory, job, identity)
        metadata = measured["result"]["solve_metadata"]
        if metadata.get("mesh_density") != "very_fine" or metadata.get("mesh_source") != "native":
            raise ValueError("Recorded fields do not identify the requested very-fine native mesh")
        evaluation = evaluate_cogging(measured["result"], fields[cid], config, case["cogging_floor_Nm"])
        hashes[job["request"]] = job["request_sha256"]
        hashes[job["result"]] = job["result_sha256"]
        wave = measured["result"]["cogging_torque_waveform"]
        if len(wave["electrical_angle_deg"]) != 25 or len(wave["torque_Nm"]) != 25:
            raise ValueError("A complete 25-position cogging grid is required")
        rows.append({"case_id": cid, "status": evaluation["status"], "gates": evaluation["gates"],
                     "input_sha256": canonical(config), "request_sha256": job["request_sha256"],
                     "result_sha256": job["result_sha256"], "cogging": evaluation["cogging"],
                     "native_waveform": wave,
                     "representative_mesh_elements": measured["result"]["solve_metadata"].get("mesh_element_count"),
                     "runtime_s": measured["runtime_s"]})
    return {"schema": "coilem.cogging_platform_qualification/v1",
            "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
            "scope": "Only the three registered distributed-cogging fixtures with very_fine native mesh",
            "candidate_commit": candidate, "platform": identity_platform_key(identity),
            "protocol_version": spec["protocol_version"], "suite_sha256": sha(ROOT / SUITE),
            "reference_manifest_sha256": sha(ROOT / BUNDLE / "manifest.json"),
            "reference_bundle_sha256": bundle_sha, "reference_review_sha256": reference["review"]["sha256"],
            "reference_commit": reference["reference_commit"], "physics_files": source_hashes,
            "source_artifact_sha256": hashes, "native_identity_sha256": canonical(identity),
            "started_at": manifest["started_at"], "completed_at": manifest["completed_at"],
            "collection_wall_s": (datetime.fromisoformat(manifest["completed_at"])-datetime.fromisoformat(manifest["started_at"])).total_seconds(),
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--candidate", required=True, help="Exact immutable candidate commit")
    parser.add_argument("--assess-only", action="store_true")
    options = parser.parse_args()
    options.directory.mkdir(parents=True, exist_ok=True)
    output = options.directory / "out"
    if not options.assess_only:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        if head != options.candidate:
            raise ValueError("Checkout does not match the pinned qualification candidate")
        completed = subprocess.run([sys.executable, "-B", "-u", "-m", "tools.run_benchmarks",
            "--suite", str(SUITE), "--reference-bundle", str(BUNDLE), "--phases", "E", "--out-dir", str(output)], cwd=ROOT)
        if completed.returncode and not (output / "run_manifest.json").is_file():
            return completed.returncode
    result = assess(output, options.candidate)
    (options.directory / "qualification.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "candidate_commit", "platform", "collection_wall_s")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
