"""Recompute the current public Windows A-D record without field solves."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import ROOT, read, sha
from backend.benchmark_suite.dq_metrics import with_dq_gates
from backend.benchmark_suite.metrics import evaluate_abc, evaluate_bldc
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.record import case_record
from backend.benchmark_suite.references import load_bundle, load_suite, require_reviewed_bundle
from backend.resources import BENCHMARK_REFERENCE_BUNDLE_DIR, BENCHMARK_SUITE_FILE

PACKET = "benchmarks/windows-v055-abcd-20261108"
MEASURED = "34de0f4ca1604311f15edf6fb49b5a2a1bf27909"


def public_errors(text):
    errors = []
    if re.search(r"(?:^|[\s\"'<>=])[A-Za-z]:[\\/]|\\\\|/(?:Users|home)/", text):
        errors.append("local machine path")
    if any(token in text for token in ("adapter_commit", "producer_sha256", "private_python_sources")):
        errors.append("private producer identity field")
    return errors


def verify(root=ROOT):
    spec = load_suite(root / BENCHMARK_SUITE_FILE)
    manifest, references, identity = load_bundle(root / BENCHMARK_REFERENCE_BUNDLE_DIR, spec)
    require_reviewed_bundle(root / BENCHMARK_REFERENCE_BUNDLE_DIR, manifest, spec)
    configs, protocols, golden = inputs(spec, spec["cases"])
    record = read(root / "benchmarks/records/windows-x86_64.json")
    summary = read(root / PACKET / "report/benchmark_summary.json")
    provenance = read(root / PACKET / "provenance.json")
    errors, gates = [], Counter()
    actual_physics = {relative: sha(root / relative) for relative in physics_sources(root)}
    if (record["measured_commit"] != MEASURED or record["platform"] != "windows-x86_64"
            or record["source"] != PACKET + "/report" or len(record["physics_files"]) != 69
            or record["reference_bundle_sha256"] != identity or actual_physics != record["physics_files"]):
        errors.append("Windows A-D record does not match its actual measured source and accepted references")
    expected = {case["id"] for case in spec["cases"]}
    rows = summary["rows"]
    if len(rows) != len(expected) or {row["id"] for row in rows} != expected or set(record["cases"]) != expected:
        errors.append("incomplete A-D case selection")
    for case in spec["cases"]:
        row = next(row for row in rows if row["id"] == case["id"])
        if case_record(row) != record["cases"][case["id"]]:
            errors.append(case["id"] + ": compact record differs from the report")
        for job in case["jobs"]:
            if row["configurations"][job["stage"]] != configs[case["id"], job["stage"]]:
                errors.append(case["id"] + ": request differs from the unchanged registered fixture")
        if case["id"] == "ornl_prius_2004_ipm":
            if row["status"] != "UNSUPPORTED":
                errors.append("planned unsupported legacy Prius outcome changed")
            continue
        if case["phase"] == "D":
            raw = {stage: {"result": result} for stage, result in row["measurements"].items()}
            raw["femm-standard"] = {"result": references[case["id"]]}
            evaluation = evaluate_bldc(protocols[case["id"]], raw, golden)
        else:
            config = configs[case["id"], "native"]
            evaluation = evaluate_abc(row["measurements"]["native"], references[case["id"]], config)
            if case.get("dq_reference"):
                evaluation = with_dq_gates(evaluation, row["measurements"]["native"], references[case["id"]], config)
        if row["status"] != "PASS" or evaluation != row["evaluation"]:
            errors.append(case["id"] + ": saved numerical evaluation does not reproduce")
        values = evaluation["gates"]
        gates.update(values.values() if isinstance(values, dict) else (gate["status"] for gate in values))
    if gates != {"PASS": 336} or summary["counts"] != {"PASS": 46, "UNSUPPORTED": 1}:
        errors.append("A-D outcomes or gate counts changed")
    if (provenance["source_native_jobs_complete"] != 52 or provenance["physics_guard_count"] != 69
            or provenance["field_solves_executed"] != 0 or provenance["native_measurements_modified"] is not False):
        errors.append("publication provenance claims changed")
    index = read(root / PACKET / "report/artifact_manifest.json")
    for relative, digest in index.items():
        path = (root / PACKET / "report" / relative).resolve()
        if not path.is_relative_to((root / PACKET / "report").resolve()) or sha(path) != digest:
            errors.append("report artifact hash mismatch: " + relative)
    for path in [*sorted((root / PACKET).rglob("*")), root / "benchmarks/records/windows-x86_64.json"]:
        if path.is_file():
            for reason in public_errors(path.read_text(encoding="utf-8")):
                errors.append(path.relative_to(root).as_posix() + ": " + reason)
    return {"schema": "coilem.current_windows_abcd_verification/v1", "status": "PASS" if not errors else "FAIL",
            "case_counts": summary["counts"], "gate_counts": dict(gates), "native_jobs": 52,
            "physics_guard_count": 69, "field_solves_executed": 0, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = verify()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
