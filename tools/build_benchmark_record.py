"""Compact a complete benchmark run into the per-platform record ``coilem benchmark`` matches (#71).

The run's recorded measurements are graded again by this checkout's
evaluator against the registered suite and the frozen reference bundle, with
zero field solves. A native-only run therefore gets the verdicts a user's run
would, and a published comparison is reproduced exactly. Every measured
request must be the one the suite registers, and the run must have measured
every physics source the record names.

    python -m tools.build_benchmark_record benchmarks/windows-native-20261018-f390b25 \\
        --out benchmarks/records/windows-x86_64.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from backend.benchmark_suite import SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import CHECKOUT, DATA_ROOT, DEFAULT_BUNDLE, SPEC, canonical, checked_json, read, sha
from backend.benchmark_suite.metrics import evaluate_abc, evaluate_bldc
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.record import build_record
from backend.benchmark_suite.references import load_bundle, load_suite


def regrade(summary):
    """The run's rows, graded by this evaluator against the registered suite and frozen bundle."""

    spec_path = SPEC
    spec = load_suite(spec_path)
    measured_protocol = summary["run"]["identity"]["protocol_version"]
    if measured_protocol not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ValueError("Unsupported measured benchmark protocol")
    cap_change = spec.get("reference_compatibility", {}).get("iteration_cap_change")
    if cap_change and measured_protocol != spec["protocol_version"]:
        # Historical fields retain their cap-100 requests. Reuse the exact
        # registered validation suite; never relabel them as cap-200 evidence.
        checked_json(DATA_ROOT, cap_change["measured_suite"], cap_change["measured_suite_sha256"])
        spec_path = DATA_ROOT / cap_change["measured_suite"]
        spec = load_suite(spec_path)
    cases = {case["id"]: case for case in spec["cases"]}
    configs, protocols, golden = inputs(spec, spec["cases"])
    _, references, bundle_sha = load_bundle(DEFAULT_BUNDLE, spec)
    rows = []
    if {row["id"] for row in summary["rows"]} != set(cases):
        raise ValueError("The run did not measure exactly the registered cases")
    for original in summary["rows"]:
        row = copy.deepcopy(original)
        case = cases[row["id"]]
        for job in case["jobs"]:
            measured = row["configurations"].get(job["stage"])
            if measured is not None and canonical(measured) != job["input_sha256"]:
                raise ValueError(f"{row['id']} / {job['stage']} measured a different request than the suite registers")
        if row["status"] in ("UNSUPPORTED", "ERROR", "INCOMPLETE"):
            rows.append(row)
            continue
        reference = references.get(row["id"])
        if case["phase"] == "D":
            raw = {stage: {"result": result} for stage, result in row["measurements"].items()}
            if reference is not None:
                raw["femm-standard"] = {"result": reference}
            evaluation = evaluate_bldc(protocols[row["id"]], raw, golden)
        else:
            evaluation = evaluate_abc(row["measurements"]["native"], reference, configs[row["id"], "native"])
        row.update(evaluation=evaluation, status=evaluation["status"],
                   reference_mode="FROZEN_REFERENCE" if reference is not None else "NOT_COMPARED")
        rows.append(row)
    run = {**summary["run"], "selection": {**summary["run"]["selection"], "spec_sha256": sha(spec_path), "bundle_sha256": bundle_sha}}
    return {**summary, "run": run, "rows": rows}, spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("evidence", type=Path, help="a published evidence folder, or a run's report folder, holding benchmark_summary.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--historical-record", type=Path,
                        help="Reproduce this published record's original source registry without extending its qualification")
    args = parser.parse_args(argv)
    if CHECKOUT is None:
        parser.error("build records from a source checkout")
    summary = read(args.evidence / "benchmark_summary.json")
    identity = summary["run"]["identity"]
    if identity.get("dirty"):
        raise SystemExit("The run measured uncommitted code; a record needs a clean commit")
    measured = identity["source_files"]
    sources = list(physics_sources(CHECKOUT))
    if args.historical_record:
        historical = read(args.historical_record)
        source = args.evidence.resolve().relative_to(CHECKOUT).as_posix()
        if historical["source"] != source or historical["measured_commit"] != identity["commit"]:
            raise SystemExit("The historical record does not name this evidence and measured commit")
        if any(measured.get(path) != digest for path, digest in historical["physics_files"].items()):
            raise SystemExit("The historical record's source hashes do not match its measured evidence")
        sources = list(historical["physics_files"])
    # Preserve a historical record's original source guard. These three files
    # entered the registry together with the exact Prius cases; old runs cannot
    # acquire their hashes retrospectively. check_physics names the missing files
    # as changes, so the reconstructed legacy record cannot qualify this build.
    reference_sources = {
        "backend/reference_models/prius.py", "backend/reference_models/pyleecan_prius_2004.json",
        "backend/reference_models/pyleecan_prius_2004_config.json",
    }
    if reference_sources.isdisjoint(measured):
        sources = [path for path in sources if path not in reference_sources]
    missing = [path for path in sources if path not in measured]
    if missing:
        raise SystemExit(f"The run did not record these physics sources: {', '.join(missing)}")
    graded, spec = regrade(summary)
    source = args.evidence.resolve().relative_to(CHECKOUT).as_posix() if args.evidence.resolve().is_relative_to(CHECKOUT) else args.evidence.name
    note = (
        f"Graded from the recorded measurements (harness {identity['harness_version']}, protocol {identity['protocol_version']}) "
        f"against suite {spec['protocol_version']} and the frozen reference bundle, with zero field solves."
    )
    record = build_record(
        graded,
        source=source,
        physics_files={path: measured[path] for path in sources},
        evaluation_note=note,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, allow_nan=False, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    counts = {}
    for case in record["cases"].values():
        counts[case["status"]] = counts.get(case["status"], 0) + 1
    print(f"{record['platform']}: {', '.join(f'{n} {s}' for s, n in sorted(counts.items()))} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
