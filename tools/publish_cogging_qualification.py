"""Verify downloaded qualification artifacts and publish a scoped two-platform record."""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

from backend.benchmark_suite.contract import read, sha
from tools.cogging_qualification import BUNDLE, SUITE, assess


def same_values(left, right):
    """Allow only floating-point regrading roundoff between supported hosts."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_values(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_values(a, b) for a, b in zip(left, right))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=5e-12, abs_tol=1e-12)
    return left == right


def verify_platform(folder, candidate):
    original = read(folder / "qualification.json")
    checked = assess(folder / "out", candidate)
    keys = ("schema", "status", "scope", "candidate_commit", "platform", "protocol_version", "suite_sha256", "reference_bundle_sha256",
            "reference_manifest_sha256", "reference_review_sha256", "reference_commit", "physics_files",
            "source_artifact_sha256", "native_identity_sha256", "started_at", "completed_at", "collection_wall_s")
    if any(original[key] != checked[key] for key in keys) or original["status"] != "PASS":
        raise ValueError("Downloaded qualification does not match independently verified candidate fields")
    expected = {row["case_id"]: row for row in checked["rows"]}
    if {row["case_id"] for row in original["rows"]} != set(expected):
        raise ValueError("Qualification report does not cover the complete cohort")
    for row in original["rows"]:
        if row["gates"] != expected[row["case_id"]]["gates"] or any(status != "PASS" for status in row["gates"].values()):
            raise ValueError("A published numerical gate differs from independent regrading")
        if not same_values(row, expected[row["case_id"]]):
            raise ValueError("Published numerical values differ from independently regraded fields")
    return original


def publish(windows, macos, candidate, workflow, output):
    win, mac = verify_platform(windows, candidate), verify_platform(macos, candidate)
    if not win["platform"].startswith("windows-") or not mac["platform"].startswith("macos-"):
        raise ValueError("Need independently measured Windows and macOS artifacts")
    shared = ("candidate_commit", "protocol_version", "suite_sha256", "reference_bundle_sha256",
              "reference_manifest_sha256", "reference_review_sha256", "physics_files")
    if any(win[key] != mac[key] for key in shared):
        raise ValueError("Platform measurements have different candidates, references or physics")
    if output.exists():
        raise ValueError("Use a new qualification publication directory")
    output.mkdir(parents=True)
    records = {}
    for source, report in ((windows, win), (macos, mac)):
        name = report["platform"] + ".json"
        shutil.copyfile(source / "qualification.json", output / name)
        records[report["platform"]] = {"file": name, "sha256": sha(output / name), "status": "PASS",
                                       "cases": len(report["rows"]), "gates": sum(len(row["gates"]) for row in report["rows"])}
    result = {"schema": "coilem.cogging_cohort_qualification/v1", "status": "QUALIFIED_FOR_REGISTERED_PARITY",
              "candidate_commit": candidate, "suite": SUITE.as_posix(), "suite_sha256": win["suite_sha256"],
              "reference_bundle": BUNDLE.as_posix(), "reference_bundle_sha256": win["reference_bundle_sha256"],
              "reference_review_sha256": win["reference_review_sha256"], "workflow_run": workflow,
              "scope": {"mesh_density": "very_fine", "nonlinear_solver": "newton", "corner_refinement": True,
                        "case_ids": [row["case_id"] for row in win["rows"]],
                        "outputs": ["cogging peak-to-peak", "cogging first harmonic"]},
              "platforms": records, "physics_files": win["physics_files"],
              "claim_boundary": "Software parity for the registered requests only; normal mesh and other geometries are outside this record"}
    (output / "qualification.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--macos", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.windows, args.macos, args.candidate, args.workflow, args.out)
    print(json.dumps({key: result[key] for key in ("status", "candidate_commit", "platforms")}))


if __name__ == "__main__":
    main()
