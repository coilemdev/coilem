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


def _constant(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{path.name} has no {name}")


def check(root: Path = ROOT, *, protocol: str = "1.6.0", candidate: str | None = None) -> list[str]:
    errors: list[str] = []
    try:
        report_path = _constant(root / "backend/qualification.py", "QUALIFICATION_REPORT")
        basis = _constant(root / "backend/qualification.py", "QUALIFICATION_BASIS")
        report = json.loads((root / report_path).read_text())
        run = report["run"]
        identity = run["identity"]
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
        bundle_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
        if run["reference_mode"] != "FROZEN_REFERENCE" or run["selection"]["bundle_sha256"] != bundle_sha:
            errors.append("qualification report does not use the registered frozen reference bundle")
        reference = json.loads(bundle.read_text())
        planned_unsupported = {"ornl_prius_2004_ipm"}
        unsupported = {row["id"] for row in report["rows"] if row["status"] == "UNSUPPORTED"}
        if not unsupported <= planned_unsupported:
            errors.append("qualification report unexpectedly marks supported cases as unsupported")
        required = {case["id"] for case in suite["cases"]} - planned_unsupported
        if "REVIEW_REQUIRED" in json.dumps(reference):
            errors.append("registered reference bundle still requires review")
        if not required <= set(reference["records"]):
            errors.append("registered frozen bundle is missing supported reference records")
        for key in ("windows-x86_64", "macos-arm64"):
            record = json.loads((root / "benchmarks/records" / f"{key}.json").read_text())
            if record["physics_files"] != actual:
                errors.append(f"{key} platform record does not match current physics")
            if record["suite_sha256"] != suite_sha or record["reference_bundle_sha256"] != bundle_sha:
                errors.append(f"{key} platform record has a different suite or reference basis")
        prius = json.loads((root / "docs/benchmarks/pyleecan-prius-v1/app-results.json").read_text())
        for name, digest in prius["source_sha256"].items():
            if name != "tools/benchmark_prius.py" and hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
                errors.append(f"Prius measured-source mismatch: {name}")
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
