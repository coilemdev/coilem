"""Recompute the public Windows Phase F packet without launching a field solver.

    python -m tools.verify_phase_f_windows_packet

This checks public numeric projections and review bindings. The original
private field dataset is identified by its digest, not reproduced here.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from backend.benchmark_suite.contract import ROOT, canonical, read, sha
from backend.benchmark_suite.metrics import evaluate_abc
from backend.benchmark_suite.record import case_record, check_physics
from backend.benchmark_suite.references import load_bundle, load_suite, require_reviewed_bundle

BUNDLE = "benchmarks/reference-baselines/phase-f-reviewed-20261108"
PACKET = "benchmarks/windows-v055-phase-f-20261108"
RECORD = "benchmarks/records/phase-f/windows-x86_64.json"
MEASURED = "34de0f4ca1604311f15edf6fb49b5a2a1bf27909"


def public_text_errors(text):
    """Public packets carry dataset digests and public source pins only."""
    errors = []
    if re.search(r"(?:^|[\s\"'<>=])[A-Za-z]:[\\/]|\\\\|/(?:Users|home|bench)/", text):
        errors.append("local machine path")
    if any(token in text for token in ("adapter_commit", "producer_sha256", "reference_commit", "private_python_sources")):
        errors.append("private producer identity field")
    if any(value != MEASURED for value in re.findall(r"\b[0-9a-f]{40}\b", text)):
        errors.append("unexpected Git-shaped identity")
    return errors


def verify(root=ROOT):
    root = Path(root)
    errors = []
    spec = load_suite(root / "benchmarks/abcd-v1.8/benchmark_spec.json")
    manifest, references, identity = load_bundle(root / BUNDLE, spec)
    review = require_reviewed_bundle(root / BUNDLE, manifest, spec)
    record = read(root / RECORD)
    summary = read(root / PACKET / "report/benchmark_summary.json")
    if record["reference_bundle_sha256"] != identity or record["reference_manifest_sha256"] != sha(root / BUNDLE / "manifest.json"):
        errors.append("record reference identity mismatch")
    if record.get("reference_id") != manifest["reference_id"] or record.get("measured_commit") != MEASURED:
        errors.append("record dataset or measured candidate mismatch")
    if record.get("platform") != "windows-x86_64" or review.get("platform") != "windows-x86_64":
        errors.append("Windows-only scope mismatch")
    if record.get("source") != PACKET + "/report" or record.get("reference_review") != {
        "file": BUNDLE + "/review.json", "sha256": sha(root / BUNDLE / "review.json")
    }:
        errors.append("record public source or review binding mismatch")
    if check_physics(record)["status"] != "MATCH":
        errors.append("runtime physics does not match the measured candidate")
    expected_ids = {case["id"] for case in spec["cases"]}
    rows = summary["rows"]
    if len(rows) != 10 or {row["id"] for row in rows} != expected_ids or set(record["cases"]) != expected_ids:
        errors.append("incomplete Phase F case set")
    gates = Counter()
    for case in spec["cases"]:
        cid = case["id"]
        native = read(root / PACKET / "native" / (cid + ".json"))
        config = read(root / case["jobs"][0]["fixture"])
        row = next(row for row in rows if row["id"] == cid)
        if (native.get("schema") != "coilem.native_measurement_projection/v1" or native.get("measured_commit") != MEASURED
                or native.get("input_sha256") != canonical(config) or native.get("case_id") != cid):
            errors.append(cid + ": native projection identity mismatch")
        evaluation = evaluate_abc(native["result"], references[cid], config)
        if evaluation["status"] != "PASS" or row["status"] != "PASS" or row["evaluation"] != evaluation:
            errors.append(cid + ": comparison does not reproduce the saved evaluation")
        if row["measurements"] != {"native": native["result"]} or row["reference"] != references[cid]:
            errors.append(cid + ": report waveforms differ from the saved projections")
        if record["cases"][cid] != case_record(row):
            errors.append(cid + ": compact record differs from the public report")
        gates.update(evaluation["gates"].values())
    if gates != {"PASS": 60}:
        errors.append("expected all sixty Phase F gates to pass")
    checks = read(root / BUNDLE / "self-checks.json")
    if len(checks["checks"]) != 30 or any(check["status"] != "PASS" for check in checks["checks"]):
        errors.append("reference self-checks did not pass")
    controls = [check for check in checks["checks"] if check["id"].endswith(":half_airgap_mesh")]
    if len(controls) != 2 or any(max(check["delta_pct"].values()) >= 2 for check in controls):
        errors.append("reference mesh controls exceed the fixed two-percent limit")
    lrk = read(root / BUNDLE / "lrk-sensitivity-review.json")
    if (lrk["original_check_counts"] != {"PASS": 9, "FAIL": 2}
            or any(row["original_status"] != "FAIL" or row["uncertainty_status"] != "INSUFFICIENT_EVIDENCE" for row in lrk["rows"])):
        errors.append("historical LRK outcomes were reclassified")
    artifact_index = read(root / PACKET / "report/artifact_manifest.json")
    for relative, digest in artifact_index.items():
        path = (root / PACKET / "report" / relative).resolve()
        if not path.is_relative_to((root / PACKET / "report").resolve()) or sha(path) != digest:
            errors.append("report artifact hash mismatch: " + relative)
    checked = 0
    for path in [*sorted((root / BUNDLE).rglob("*")), *sorted((root / PACKET).rglob("*")), root / RECORD]:
        if path.is_file():
            for reason in public_text_errors(path.read_text(encoding="utf-8")):
                errors.append(path.relative_to(root).as_posix() + ": " + reason)
            checked += 1
    return {"schema": "coilem.phase_f_packet_verification/v1", "status": "PASS" if not errors else "FAIL",
            "cases": len(rows), "gate_counts": dict(gates), "reference_self_checks": len(checks["checks"]),
            "mesh_controls": len(controls), "public_files_checked": checked,
            "field_solves_executed": 0, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = verify()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
