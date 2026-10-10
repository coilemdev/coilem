"""Run native fields and reuse compatible, immutable reference evidence."""

from __future__ import annotations

import argparse
import copy
import os
import subprocess
import sys
from pathlib import Path

from tools.benchmark_suite import HARNESS_VERSION, PHASE_LABELS
from tools.benchmark_suite.bldc_metrics import validate_lane_result
from tools.benchmark_suite.contract import (
    DEFAULT_BUNDLE,
    ROOT,
    SPEC,
    canonical,
    checked_json,
    identity,
    now,
    read,
    run_lock,
    sha,
    write,
)
from tools.benchmark_suite.metrics import evaluate_abc, evaluate_bldc, validate_abc
from tools.benchmark_suite.references import load_bundle, load_suite, verify_materials
from tools.benchmark_suite.report import build
from tools.benchmark_suite.worker import compact


def native_runtime_root(directory):
    path = str((directory / "native-runtime").resolve())
    if os.name == "nt":
        # Persisted mesh/frame filenames can exceed Windows' legacy 260-character limit.
        return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
    return path


def inputs(spec, selected):
    golden = checked_json(ROOT, spec["golden"], spec["golden_sha256"])
    configs, protocols = {}, {}
    for case in selected:
        for job in case["jobs"]:
            config = checked_json(ROOT, job["fixture"], job["fixture_sha256"])
            if canonical(config) != job["input_sha256"]:
                raise ValueError(f"Registered request mismatch: {case['id']}")
            configs[case["id"], job["stage"]] = config
        if case["phase"] == "D":
            protocols[case["id"]] = checked_json(ROOT, case["protocol"], case["protocol_sha256"])
    return configs, protocols, golden


def verify_artifact(output, job, registered_identity):
    request = read(output / job["request"])
    if sha(output / job["request"]) != job["request_sha256"] or request["identity"] != registered_identity:
        raise ValueError("Registered job request changed")
    path = output / job["result"]
    if job.get("result_sha256") and sha(path) != job["result_sha256"]:
        raise ValueError("Registered native evidence changed")
    data = read(path)
    if data["request_sha256"] != job["request_sha256"]:
        raise ValueError("Native evidence belongs to a different request")
    if data["status"] == "COMPLETE" and (data["identity_before"] != registered_identity or data["identity_after"] != registered_identity):
        raise ValueError("Native evidence runtime identity mismatch")
    return data


def evaluate(output, manifest, selected, configs, protocols, golden, references):
    rows = []
    for case in selected:
        jobs = [j for j in manifest["jobs"] if j["case_id"] == case["id"]]
        measurements = {}
        for job in jobs:
            if sha(output / job["request"]) != job["request_sha256"]:
                raise ValueError("Registered request changed")
            if job["status"] == "COMPLETE":
                data = verify_artifact(output, job, manifest["identity"])
                measurements[job["stage"]] = compact(data["result"]) if case["phase"] == "D" else data["result"]
        reference = references.get(case["id"])
        if all(j["status"] == "UNSUPPORTED" for j in jobs):
            evaluation = {"status": "UNSUPPORTED", "gates": [], "reason": jobs[0]["reason"]}
        elif any(j["status"] == "ERROR" for j in jobs):
            evaluation = {"status": "ERROR", "gates": [], "errors": [j.get("error") for j in jobs if j["status"] == "ERROR"]}
        elif len(measurements) != len(jobs):
            evaluation = {"status": "INCOMPLETE", "gates": []}
        elif manifest["smoke"]:
            evaluation = {"status": "NON_GATING_SMOKE", "gates": [], "reason": "Reduced grid; historical numerical gates not evaluated"}
        elif case["phase"] == "D":
            raw = {s: {"result": v} for s, v in measurements.items()}
            if reference is not None:
                raw["femm-standard"] = {"result": reference}
            try:
                evaluation = evaluate_bldc(protocols[case["id"]], raw, golden)
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                evaluation = {"status": "INCOMPLETE", "gates": [], "reason": str(exc)}
        else:
            try:
                evaluation = evaluate_abc(measurements["native"], reference, configs[case["id"], "native"])
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                evaluation = {"status": "INCOMPLETE", "gates": [], "reason": str(exc)}
        row = {
            "id": case["id"],
            "phase": case["phase"],
            "fixture": case["jobs"][0]["fixture"],
            "status": evaluation["status"],
            "evaluation": evaluation,
            "measurements": measurements,
            "reference": reference,
            "configurations": {job["stage"]: read(output / job["request"])["config"] for job in jobs},
            "reference_mode": "FROZEN_REFERENCE" if reference is not None and not manifest["smoke"] else "NOT_COMPARED",
        }
        if case["phase"] == "D":
            row["protocol"] = protocols[case["id"]]
        rows.append(row)
    return rows


def execute(args):
    spec = load_suite(SPEC)
    selected = [c for c in spec["cases"] if c["phase"] in args.phases and (not args.case or c["id"] in args.case)]
    if args.case and set(args.case) - {c["id"] for c in selected}:
        raise ValueError("Unknown case or case excluded by --phases")
    if not selected:
        raise ValueError("No cases selected")
    configs, protocols, golden = inputs(spec, selected)
    if args.list:
        for case in selected:
            print(case["phase"], PHASE_LABELS[case["phase"]], case["id"], ", ".join(j["stage"] for j in case["jobs"]))
        return 0
    if args.out_dir is None:
        raise ValueError("--out-dir is required; use a directory outside the source checkout")
    output = args.out_dir.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep generated artifacts outside the source checkout (--out-dir ../benchmark-output/run-id)")
    references, reference_manifest, bundle_sha = {}, {}, None
    if not args.no_reference and not args.smoke:
        reference_manifest, references, bundle_sha = load_bundle(args.reference_bundle.resolve(), spec)
        # Reject corrupt or mismatched frozen numerical arrays before spending time on fields.
        for case in selected:
            reference = references.get(case["id"])
            if reference is None:
                continue
            if case["phase"] == "D":
                validate_lane_result("femm-standard", reference, protocols[case["id"]], golden=golden)
            else:
                validate_abc(reference, configs[case["id"], "native"], native=False)
    selection = {
        "case_ids": [c["id"] for c in selected],
        "spec_sha256": sha(SPEC),
        "bundle_sha256": bundle_sha,
        "smoke": args.smoke,
        "no_reference": args.no_reference,
    }
    with run_lock(output):
        path = output / "run_manifest.json"
        if args.report_only:
            manifest = read(path)
            if manifest["selection"] != selection:
                raise ValueError("Report selection or input bundle differs from the registered run")
            return finish(output, manifest, selected, configs, protocols, golden, references, pdf=args.pdf)
        from backend.magneto2d_adapter import ensure_magneto2d_binary
        from backend.public_policy import PublicConfigError, parse_public_solve_request

        verify_materials(spec["material_contract"])
        binary = ensure_magneto2d_binary()
        runtime = identity(binary)
        if runtime["dirty"] and not args.allow_dirty:
            raise ValueError("Checkout has local changes; commit them or use --allow-dirty to register the actual source hashes")
        if path.exists():
            if not args.resume:
                raise ValueError("Existing run; use --resume or --report-only, or select a new output directory")
            manifest = read(path)
            if manifest["selection"] != selection or manifest["identity"] != runtime:
                raise ValueError("Resume refused: solver, harness, inputs, selection or reference bundle changed")
        else:
            if args.resume:
                raise ValueError("No registered run to resume")
            jobs = []
            for case in selected:
                for job in case["jobs"]:
                    config = copy.deepcopy(configs[case["id"], job["stage"]])
                    if args.smoke:
                        config["solve_params"].update(solve_quality="custom", rotor_sweep_range_deg=30.0, rotor_step_deg=30.0, mesh_density="coarse")
                    directory = Path("jobs") / case["id"] / job["stage"]
                    record = {
                        "case_id": case["id"],
                        "phase": case["phase"],
                        "stage": job["stage"],
                        "status": "READY",
                        "request": (directory / "request.json").as_posix(),
                        "result": (directory / "result.json").as_posix(),
                        "fixture_sha256": job["fixture_sha256"],
                    }
                    try:
                        parse_public_solve_request(config)
                    except PublicConfigError as exc:
                        record.update(status="UNSUPPORTED", reason=str(exc))
                    request = {
                        "config": config,
                        "config_sha256": canonical(config),
                        "identity": runtime,
                        "binary": binary.relative_to(ROOT).as_posix(),
                    }
                    write(output / record["request"], request)
                    record["request_sha256"] = sha(output / record["request"])
                    jobs.append(record)
            manifest = {
                "schema": "coilem.benchmark_run/v1",
                "started_at": now(),
                "identity": runtime,
                "selection": selection,
                "reference_mode": "NONE_SMOKE" if args.smoke else "NATIVE_ONLY" if args.no_reference else "FROZEN_REFERENCE",
                "reference_commit": reference_manifest.get("reference_commit"),
                "smoke": args.smoke,
                "jobs": jobs,
                "status": "RUNNING",
            }
            write(path, manifest)
        for job in manifest["jobs"]:
            if job["status"] in ("UNSUPPORTED", "ERROR"):
                continue
            directory = (output / job["result"]).parent
            # An orphaned live worker owns this lock; never launch a duplicate.
            with run_lock(directory):
                if (output / job["result"]).exists():
                    data = verify_artifact(output, job, runtime)
                    job.update(status=data["status"], result_sha256=sha(output / job["result"]), error=data.get("error"))
                    write(path, manifest)
                    continue
                if sha(output / job["request"]) != job["request_sha256"]:
                    raise ValueError("Registered request changed")
            job.update(status="RUNNING", started_at=now())
            write(path, manifest)
            print(f"{job['phase']} / {job['case_id']} / {job['stage']}: starting native solve", flush=True)
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1", COILEM_USER_DATA_ROOT=native_runtime_root(directory))
            env.pop("PYTHONPATH", None)
            with (directory / "worker.log").open("ab") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "tools.benchmark_suite.worker",
                        "--request",
                        str(output / job["request"]),
                        "--output",
                        str(output / job["result"]),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                job["pid"] = process.pid
                write(path, manifest)
                code = process.wait()
            job.update(exit_code=code, completed_at=now())
            if (output / job["result"]).exists():
                data = verify_artifact(output, job, runtime)
                job.update(status=data["status"], result_sha256=sha(output / job["result"]), error=data.get("error"))
            else:
                job.update(status="ERROR", error="Worker exited without a measurement artifact")
            write(path, manifest)
            print(f"{job['case_id']} / {job['stage']}: {job['status']}", flush=True)
            # Check again before registering or launching the next solve.
            inputs(spec, selected)
            if sha(SPEC) != selection["spec_sha256"]:
                raise ValueError("Registered suite changed")
            if bundle_sha is not None and load_bundle(args.reference_bundle.resolve(), spec)[2] != bundle_sha:
                raise ValueError("Reference bundle changed during the run")
            if identity(binary) != runtime:
                raise ValueError("Runtime changed; remaining jobs were not launched")
        manifest.update(status="COMPLETE_WITH_ERRORS" if any(j["status"] == "ERROR" for j in manifest["jobs"]) else "COMPLETE", completed_at=now())
        write(path, manifest)
        return finish(output, manifest, selected, configs, protocols, golden, references, pdf=args.pdf)


def finish(output, manifest, selected, configs, protocols, golden, references, *, pdf=False):
    rows = evaluate(output, manifest, selected, configs, protocols, golden, references)
    verdict = build(output, manifest, rows, pdf=pdf)
    print(f"{verdict}: {output / 'report/coilem_benchmark_report.html'}", flush=True)
    if any(r["status"] in ("ERROR", "INCOMPLETE") for r in rows):
        return 2
    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"Coilem benchmark harness {HARNESS_VERSION}")
    parser.add_argument("--phases", nargs="+", choices=list(PHASE_LABELS), default=list(PHASE_LABELS))
    parser.add_argument("--case", action="append", help="Select a registered case id; repeat for multiple cases")
    parser.add_argument("--reference-bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--list", action="store_true", help="List the verified suite without building or solving")
    parser.add_argument("--resume", action="store_true", help="Resume identical inputs and runtime; reuse completed native jobs")
    parser.add_argument("--report-only", action="store_true", help="Rebuild artifacts from verified recorded measurements")
    parser.add_argument("--no-reference", action="store_true", help="Evaluate native checks; no FEMM parity verdict")
    parser.add_argument("--smoke", action="store_true", help="Reduced coarse grid; never a numerical parity result")
    parser.add_argument("--allow-dirty", action="store_true", help="Explicitly register actual uncommitted source hashes")
    parser.add_argument("--pdf", action="store_true", help="Also export a PDF using the existing reportlab dependency")
    args = parser.parse_args()
    if args.resume and args.report_only:
        parser.error("--resume and --report-only are mutually exclusive")
    try:
        return execute(args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Benchmark refused: {exc}", file=sys.stderr)
        return 2
