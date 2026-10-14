"""Compare verified native-only evidence with a later frozen reference, without solving."""

from __future__ import annotations

import argparse
import copy
import hashlib
import subprocess
import sys
from pathlib import Path


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_source(source, expected_commit, native_identity):
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip()
    if commit != expected_commit or dirty or native_identity["commit"] != expected_commit or native_identity["dirty"]:
        raise ValueError("Use the clean measured source pin; candidate identity must match")
    for relative, expected in native_identity["source_files"].items():
        path = (source / relative).resolve()
        if not path.is_relative_to(source) or file_sha(path) != expected:
            raise ValueError(f"Measured source hash differs: {relative}")


def require_selection(manifest, spec, spec_sha):
    selection = manifest["selection"]
    selected = [case for case in spec["cases"] if case["id"] in selection["case_ids"]]
    if (
        manifest["schema"] != "coilem.benchmark_run/v1"
        or manifest["status"] not in ("COMPLETE", "COMPLETE_WITH_ERRORS")
        or manifest["smoke"]
        or not selection["no_reference"]
        or selection["bundle_sha256"] is not None
        or selection["spec_sha256"] != spec_sha
        or selection["case_ids"] != [case["id"] for case in selected]
    ):
        raise ValueError("Expected a finished, unchanged, full-grid native-only run")
    expected = [(case["id"], case["phase"], job["stage"]) for case in selected for job in case["jobs"]]
    actual = [(job["case_id"], job["phase"], job["stage"]) for job in manifest["jobs"]]
    if actual != expected:
        raise ValueError("Native job membership differs from the registered suite selection")
    if any(job["status"] not in ("COMPLETE", "ERROR", "UNSUPPORTED") for job in manifest["jobs"]):
        raise ValueError("Native measurements are still running or incomplete")
    return selected


def winding_axis_diagnostic(result, config, protocol, golden, axis):
    """Independent diagnostic; never changes the historical gates or waveforms."""
    current = result["phase_current_waveform"]
    plateau = protocol["excitation"]["product_current_A"]
    advance = protocol["excitation"]["commutation_advance_deg"]
    tolerance = protocol["gates"]["current_plateau_abs_A_max"]
    old_bad, new_bad = [], []
    for index, angle in enumerate(result["electrical_angle_deg"]):
        actual = [current[f"phase_{p}_A"][index] for p in "abc"]
        for offset, failures in ((0.0, old_bad), (axis, new_bad)):
            sector = int(((angle + offset + advance) % 360.0) // 60.0)
            expected = [v * plateau / golden["plateau_current_A"] for v in golden["sector_table_A"][sector]]
            if any(abs(a - b) > tolerance for a, b in zip(actual, expected, strict=True)):
                failures.append(angle)
    return {
        "phase_a_axis_offset_electrical_deg": axis,
        "historical_fixed_axis_sequence": "FAIL" if old_bad else "PASS",
        "pr100_winding_axis_sequence": "FAIL" if new_bad else "PASS",
        "historical_mismatch_angles_deg": old_bad,
        "pr100_mismatch_angles_deg": new_bad,
        "physical_angles_changed": False,
        "historical_gates_replaced": False,
    }


def compare(args):
    source = args.source_root.resolve()
    native = args.native_out.resolve()
    bundle = args.reference_bundle.resolve()
    output = args.out_dir.resolve()
    if output == native or output.is_relative_to(source) or output.is_relative_to(native) or output.is_relative_to(bundle):
        raise ValueError("Keep comparison output separate from source, native evidence and references")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Comparison output exists; select a new directory")
    sys.path.insert(0, str(source))
    from tools.benchmark_suite import cli
    from tools.benchmark_suite.contract import canonical, checked_path, read, sha, write
    from tools.benchmark_suite.metrics import validate_abc
    from tools.benchmark_suite.references import load_bundle, load_suite
    from tools.benchmark_suite.report import build
    from tools.benchmark_suite.worker import compact

    if cli.ROOT.resolve() != source:
        raise ValueError("Benchmark evaluator imported from another checkout")
    original = read(native / "run_manifest.json")
    manifest_sha = sha(native / "run_manifest.json")
    require_source(source, args.expected_commit, original["identity"])
    suite_path = (source / args.suite).resolve()
    if not suite_path.is_relative_to(source):
        raise ValueError("Suite path must belong to the measured checkout")
    spec = load_suite(suite_path)
    selected = require_selection(original, spec, sha(suite_path))
    configs, protocols, golden = cli.inputs(spec, selected)
    hardware = cli.hardware_targets(selected)
    evidence_hashes = {}
    for job in original["jobs"]:
        request_path = checked_path(native, job["request"])
        request = read(request_path)
        if (
            sha(request_path) != job["request_sha256"]
            or request["identity"] != original["identity"]
            or request["config_sha256"] != canonical(request["config"])
            or request["config"] != configs[job["case_id"], job["stage"]]
        ):
            raise ValueError(f"Native request changed: {job['case_id']} / {job['stage']}")
        evidence_hashes[job["request"]] = sha(request_path)
        if job["status"] == "COMPLETE":
            result_path = checked_path(native, job["result"])
            if not job.get("result_sha256") or sha(result_path) != job["result_sha256"]:
                raise ValueError("Missing or changed completed native artifact hash")
            data = cli.verify_artifact(native, job, original["identity"])
            if data["status"] != "COMPLETE":
                raise ValueError("Completed job disagrees with its measurement status")
            evidence_hashes[job["result"]] = sha(result_path)
    reference_manifest, references, bundle_sha = load_bundle(bundle, spec)
    if reference_manifest["reference_commit"] != args.expected_commit:
        raise ValueError("Reference must use the same measured source pin; v1/v2 cannot substitute for v3")
    needed = {case["id"] for case in selected if not all(
        job["status"] == "UNSUPPORTED" for job in original["jobs"] if job["case_id"] == case["id"]
    )}
    if not needed.issubset(references):
        raise ValueError(f"Missing matched references: {sorted(needed - references.keys())}")
    for case in selected:
        reference = references.get(case["id"])
        if reference is None:
            continue
        if case["phase"] == "D":
            # Only the structural pre-check is done here. The unchanged public
            # evaluator still computes and records every historical golden gate.
            cli.validate_lane_result(
                "femm-standard", reference, protocols[case["id"]], golden=golden, check_golden_sequence=False,
            )
        else:
            validate_abc(reference, configs[case["id"], "native"], native=False)
    derived = copy.deepcopy(original)
    derived.update(reference_mode="FROZEN_REFERENCE", reference_commit=reference_manifest["reference_commit"])
    derived["selection"].update(no_reference=False, bundle_sha256=bundle_sha)
    derived["comparison"] = {
        "schema": "coilem.late_reference_comparison/v1",
        "native_manifest_sha256": manifest_sha,
        "native_artifact_sha256": evidence_hashes,
        "comparison_tool_sha256": file_sha(__file__),
        "reference_manifest_sha256": sha(bundle / "manifest.json"),
        "reference_validation_status": reference_manifest.get("validation_status", "unspecified"),
        "field_solves_executed": 0,
        "native_manifest_mutated": False,
        "qualification": (
            "Diagnostic comparison; historical fixed-axis gates remain unchanged. "
            "Reconcile the PR100 winding-axis contract before release qualification."
        ),
    }
    rows = cli.evaluate(native, derived, selected, configs, protocols, golden, references, hardware)
    from backend.excitation import phase_axis_offset_deg
    from backend.models import MotorConfig

    diagnostics = {}
    for case in selected:
        if case["phase"] != "D":
            continue
        cid = case["id"]
        diagnostic = {}
        for job in original["jobs"]:
            if job["case_id"] != cid or job["status"] != "COMPLETE":
                continue
            if job["stage"] == "analytical":
                # This lane has a different current amplitude; keep its public
                # evaluation intact and diagnose it with that registered value.
                protocol = copy.deepcopy(protocols[cid])
                protocol["excitation"]["product_current_A"] = protocol["excitation"]["analytical_current_A"]
            else:
                protocol = protocols[cid]
            config = configs[cid, job["stage"]]
            result = compact(read(native / job["result"])["result"])
            axis = phase_axis_offset_deg(MotorConfig.model_validate(config))
            diagnostic[job["stage"]] = winding_axis_diagnostic(result, config, protocol, golden, axis)
        if cid in references:
            config = configs[cid, "native-standard"]
            axis = phase_axis_offset_deg(MotorConfig.model_validate(config))
            diagnostic["femm-standard"] = winding_axis_diagnostic(references[cid], config, protocols[cid], golden, axis)
        diagnostics[cid] = diagnostic
    output.mkdir(parents=True, exist_ok=True)
    verdict = build(output, derived, rows, pdf=args.pdf)
    write(output / "comparison_manifest.json", derived)
    write(output / "winding_axis_diagnostics.json", diagnostics)
    (output / "README.md").write_text(
        "# Native evidence compared with a later FEMM reference\n\n"
        f"Measured source and reference pin: `{args.expected_commit}`. Numerical outcome: **{verdict}**.\n\n"
        "This report reused verified native measurements and a separately generated reference. Zero field solves ran here. "
        "The original native-only manifest and artifacts remain unchanged. `comparison_manifest.json` is comparison provenance, "
        "not a native-run resume manifest. Keep the original native evidence alongside this output.\n\n"
        "The historical six-step fixed-axis gates remain unchanged, including FAILs. `winding_axis_diagnostics.json` separately "
        "checks PR100's geometry-derived phase-A frame without moving any waveform. A passing new-frame diagnostic does not "
        "replace a failed historical gate. Reconcile that contract and scientifically review FEMM v3 before release qualification.\n",
        encoding="utf-8",
    )
    if sha(native / "run_manifest.json") != manifest_sha or load_bundle(bundle, spec)[2] != bundle_sha:
        raise ValueError("Source evidence or reference changed while rendering")
    for relative, expected in evidence_hashes.items():
        if sha(checked_path(native, relative)) != expected:
            raise ValueError("Native evidence changed while rendering")
    require_source(source, args.expected_commit, original["identity"])
    print(f"{verdict}: {output / 'report/coilem_benchmark_report.html'} (0 field solves)")
    if any(row["status"] in ("ERROR", "INCOMPLETE") for row in rows):
        return 2
    return 1 if any(row["status"] == "FAIL" for row in rows) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="Clean, unchanged measured source checkout")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--native-out", type=Path, required=True)
    parser.add_argument("--reference-bundle", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=Path("benchmarks/abcd-v1.1/benchmark_spec.json"))
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    try:
        return compare(args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Comparison refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
