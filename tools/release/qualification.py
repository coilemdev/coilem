"""Fail closed before a v0.5 release when its frozen qualification is incomplete.

Development tests exercise historical replay and experimental-status behavior.
This separate publication gate still requires current measured physics, complete
registered coverage, reviewed references and matching macOS/Windows records.

    python -m tools.release.qualification [--candidate FULL_MEASURED_COMMIT]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIUS_EXTRA_PHYSICS = (
    "backend/models/config.py", "backend/public_policy.py",
    "backend/solver_environment.py", "backend/topology_provenance.py",
)


def _constant(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{path.name} has no {name}")


def _optional_constant(path, name, default):
    try:
        return _constant(path, name)
    except ValueError:
        return default


def _file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("evidence path escapes the checkout")
    return path


def _data(root, name):
    return json.loads(_file(root, name).read_text(encoding="utf-8"))


def _review_errors(root, bundle_path, reference, suite, suite_sha):
    if reference.get("validation_status") != "REVIEWED_FOR_REGISTERED_PARITY":
        return ["registered reference bundle still requires review"]
    entry = reference.get("review") or {}
    path = _file(root / bundle_path, entry["file"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        return ["registered reference review artifact hash mismatch"]
    review = _data(root / bundle_path, entry["file"])
    required = {case["id"] for case in suite["cases"]} - {"ornl_prius_2004_ipm"}
    if (review.get("schema") != "coilem.protocol16_reference_review/v1"
            or review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or review.get("suite_sha256") != suite_sha
            or review.get("reference_commit") != reference.get("reference_commit")
            or review.get("parent_manifest_sha256") != reference.get("parent_manifest_sha256")
            or review.get("parent_bundle_sha256") != reference.get("parent_bundle_sha256")
            or set(review.get("cases", {})) != required):
        return ["registered reference review does not cover this suite and bundle"]
    return []


def check(root: Path = ROOT, *, protocol: str = "1.6.0", candidate: str | None = None) -> list[str]:
    errors: list[str] = []
    try:
        report_path = _constant(root / "backend/qualification.py", "QUALIFICATION_REPORT")
        basis = _constant(root / "backend/qualification.py", "QUALIFICATION_BASIS")
        report = json.loads((root / report_path).read_text())
        run = report["run"]
        identity = run["identity"]
        # Publication commits may add evidence and metadata, but the default
        # tag gate still requires both platforms and Prius to measure the
        # same immutable field candidate as the registered primary report.
        candidate = candidate or identity["commit"]
        if run["status"] != "COMPLETE" or run.get("smoke") or identity.get("dirty"):
            errors.append("qualification report must be a complete, clean, non-smoke collection")
        if identity["commit"][:7] not in basis:
            errors.append("qualification basis does not name the measured commit")
        if candidate is not None and identity["commit"] != candidate:
            errors.append("qualification report did not measure the frozen candidate")
        suite_path = _constant(root / "backend/resources.py", "BENCHMARK_SUITE_FILE")
        suite = json.loads((root / suite_path).read_text())
        suite_sha = hashlib.sha256((root / suite_path).read_bytes()).hexdigest()
        if suite["protocol_version"] != protocol or identity["protocol_version"] != protocol:
            errors.append(f"registered suite and measured report must both use protocol {protocol}")
        if run["selection"]["spec_sha256"] != suite_sha:
            errors.append("qualification report does not match the registered suite hash")
        if {row["id"] for row in report["rows"]} != {case["id"] for case in suite["cases"]}:
            errors.append("qualification report does not cover exactly the registered cases")
        if any(row["status"] in {"ERROR", "INCOMPLETE", "NOT_COMPARED"} for row in report["rows"]):
            errors.append("qualification report has uncollected or unevaluated cases")
        spec = importlib.util.spec_from_file_location("release_physics", root / "backend/benchmark_suite/physics.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in module.physics_sources(root)}
        for name, digest in actual.items():
            if identity["source_files"].get(name) != digest:
                errors.append(f"qualification physics mismatch: {name}")
        bundle_path = _constant(root / "backend/resources.py", "BENCHMARK_REFERENCE_BUNDLE_DIR")
        bundle = root / bundle_path / "manifest.json"
        reference = json.loads(bundle.read_text())
        # Match load_bundle() and build_record(): this identifies both the
        # manifest bytes and its record index, rather than the manifest alone.
        bundle_sha = hashlib.sha256(json.dumps({
            "manifest": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "records": reference["records"],
        }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if run["reference_mode"] != "FROZEN_REFERENCE" or run["selection"]["bundle_sha256"] != bundle_sha:
            errors.append("qualification report does not use the registered frozen reference bundle")
        planned_unsupported = {"ornl_prius_2004_ipm"}
        unsupported = {row["id"] for row in report["rows"] if row["status"] == "UNSUPPORTED"}
        if not unsupported <= planned_unsupported:
            errors.append("qualification report unexpectedly marks supported cases as unsupported")
        required = {case["id"] for case in suite["cases"]} - planned_unsupported
        if any(row["status"] != "PASS" for row in report["rows"] if row["id"] in required):
            errors.append("qualification report has a supported case without passing registered gates")
        errors.extend(_review_errors(root, bundle_path, reference, suite, suite_sha))
        if not required <= set(reference["records"]):
            errors.append("registered frozen bundle is missing supported reference records")
        for cid in required & set(reference["records"]):
            entry = reference["records"][cid]
            if hashlib.sha256(_file(root / bundle_path, entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
                errors.append(f"registered reference record hash mismatch: {cid}")
        for key in ("windows-x86_64", "macos-arm64"):
            record = json.loads((root / "benchmarks/records" / f"{key}.json").read_text())
            if record["physics_files"] != actual:
                errors.append(f"{key} platform record does not match current physics")
            if record["suite_sha256"] != suite_sha or record["reference_bundle_sha256"] != bundle_sha:
                errors.append(f"{key} platform record has a different suite or reference basis")
            measured = _data(root, record["source"] + "/benchmark_summary.json")
            measured_run = measured["run"]
            if (measured_run["status"] != "COMPLETE" or measured_run.get("smoke")
                    or measured_run["identity"].get("dirty") is not False
                    or measured_run["identity"]["commit"] != record["measured_commit"]
                    or (candidate is not None and record["measured_commit"] != candidate)
                    or measured_run["selection"]["spec_sha256"] != suite_sha
                    or measured_run["selection"]["bundle_sha256"] != bundle_sha
                    or {row["id"] for row in measured["rows"]} != {case["id"] for case in suite["cases"]}
                    or any(row["status"] in {"ERROR", "INCOMPLETE", "NOT_COMPARED"} for row in measured["rows"])
                    or any(row["status"] != "PASS" for row in measured["rows"] if row["id"] in required)
                    or any(measured_run["identity"]["source_files"].get(name) != digest for name, digest in actual.items())):
                errors.append(f"{key} platform record lacks matching complete measured candidate evidence")
        prius_path = _optional_constant(root / "backend/qualification.py", "PRIUS_QUALIFICATION_REPORT",
                                       "docs/benchmarks/pyleecan-prius-v1/app-results.json")
        prius = _data(root, prius_path)
        # Bind the actual grader to the snapshot captured before fields. The
        # original analyzer's legacy policy flag is retained in the report;
        # the snapshot proves which analysis code was already registered.
        snapshot_path = _file(root, Path(prius_path).with_name("source-snapshot.json"))
        snapshot_sha = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        snapshot = json.loads(snapshot_path.read_text())
        analysis_sources = {entry["path"]: entry["sha256"] for entry in snapshot["files"]}
        if (snapshot_sha != prius["source_sha256"].get("snapshot-manifest.json")
                or prius.get("analysis_runner_sha256") != analysis_sources.get("tools/report_prius_benchmark.py")):
            errors.append("Prius analysis code is not bound to its before-field source snapshot")
        # Full v2 registrations also hash reporting/packaging sources and the
        # snapshot itself. Those immutable historical identities are retained,
        # but an evidence-publication commit cannot reproduce its own future
        # snapshot hash. Compare every field-affecting source, including Prius
        # policy/configuration inputs, without excluding changed physics.
        prius_sources = {**actual, **{name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in PRIUS_EXTRA_PHYSICS}}
        for name, digest in prius_sources.items():
            if prius["source_sha256"].get(name) != digest:
                errors.append(f"Prius measured-source mismatch: {name}")
        if (prius.get("field_source_dirty") is not False or not prius.get("all_software_checks_pass")
                or not prius.get("checks") or not all(prius["checks"].values())
                or not prius.get("grading_provenance", {}).get("frozen_before_fields")
                or len(prius.get("jobs", [])) != 17
                or sum(len(a["field_reports"]) for a in prius.get("audits", {}).values()) != 568):
            errors.append("Prius qualification needs the complete frozen-input candidate collection and passing software checks")
        if candidate is not None and prius.get("field_source_commit") != candidate:
            errors.append("Prius report did not measure the frozen candidate")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"qualification evidence unavailable or invalid: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", help="exact commit measured before evidence publication")
    parser.add_argument("--protocol", default="1.6.0")
    args = parser.parse_args(argv)
    errors = check(protocol=args.protocol, candidate=args.candidate)
    print(json.dumps({"status": "BLOCKED" if errors else "PASS", "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
