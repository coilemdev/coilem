"""Run the separately registered Phase G benchmark: Magneto2D, then Windows FEMM."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.benchmark_suite.external_contract import run_lock
from tools.phase_g_loss.contract import ROOT, SUITE, read, sha, suite, write


def live_femm_count():
    if sys.platform != "win32":
        raise ValueError("FEMM collection requires Windows")
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/tasklist.exe"
    output = subprocess.check_output([str(executable), "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq femm.exe"], text=True)
    return sum(row and row[0].lower() == "femm.exe" for row in csv.reader(output.splitlines()))


def commands(arguments, log_paths):
    """Fail fast, terminating only children launched by this invocation."""
    children, streams = [], []
    try:
        for args, path in zip(arguments, log_paths, strict=True):
            stream = path.open("a", encoding="utf-8")
            streams.append(stream)
            children.append(subprocess.Popen(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT))
        while any(child.poll() is None for child in children):
            if any(child.poll() not in (None, 0) for child in children):
                raise RuntimeError("Phase G worker failed; see " + ", ".join(str(p) for p in log_paths))
            time.sleep(2)
        if any(child.returncode for child in children):
            raise RuntimeError("Phase G worker failed; see " + ", ".join(str(p) for p in log_paths))
    finally:
        for child in children:
            if child.poll() is None:
                if os.name == "nt":
                    # A Windows venv executable launches the real Python as a
                    # child. Kill that owned tree so its FEMM job handle closes.
                    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"
                    subprocess.run(
                        [str(executable), "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                    )
                else:
                    child.terminate()
        for child in children:
            child.wait()
        for stream in streams:
            stream.close()


def verify_native_snapshots(output):
    snapshots = list((Path(output) / "native").glob("*/protocol.json"))
    if not snapshots:
        raise ValueError("No native source snapshot establishes compatibility")
    for path in snapshots:
        for name, digest in read(path)["identity"]["source_sha256"].items():
            if sha(ROOT / name) != digest:
                raise ValueError("Measured native physics/collector source changed: " + name)


def run(args):
    output = args.out.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep measured output outside the source checkout")
    output.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip():
        raise ValueError("Commit the benchmark sources before field collection")
    spec = suite()
    cases = [case for case in spec["cases"] if not args.case or case["id"] in args.case]
    if len(cases) != len(set(args.case or [c["id"] for c in cases])):
        raise ValueError("Unknown or duplicate Phase G case selection")
    registration = {
        "schema": "coilem.phase_g_campaign/v1",
        "candidate": source,
        "suite_sha256": sha(SUITE),
        "cases": cases,
        "binary_sha256": sha(args.binary) if args.binary else None,
        "native_workers": args.native_workers,
        "femm_workers": args.femm_workers,
    }
    registration_path = output / "registration.json"
    if registration_path.exists():
        old = read(registration_path)
        # A later FEMM-only command may omit the native binary argument, but
        # cannot change sources, suite, selection or the collected histories.
        if args.binary is None:
            registration["binary_sha256"] = old["binary_sha256"]
        if old["candidate"] != source:
            verify_native_snapshots(output)
            # Retain the actual field producer identity. Changes confined to
            # orchestration/postprocessing do not retag immutable fields.
            registration["candidate"] = old["candidate"]
        if registration != old:
            raise ValueError("Campaign identity changed; use a fresh directory")
    else:
        write(registration_path, registration)
    state = {
        "status": "STARTING",
        "candidate": registration["candidate"],
        "tooling_commit": source,
        "registration_sha256": sha(registration_path),
        "native_completed": [],
        "native_angular_failures": [],
        "femm_completed": [],
        "femm_angular_failures": [],
        "allow_distributed_coarse_angular_failure": args.allow_angular_failure,
        "qualification_complete": False,
    }

    def save(status, case=None):
        state.update(status=status, current_case=case, updated_utc=datetime.now(timezone.utc).isoformat())
        write(output / "run-state.json", state)

    def analyse_case(directory, *, reference=False):
        from tools.phase_g_loss.report import admissible_history

        command = [sys.executable, "-m", "tools.phase_g_loss.report", "--history", str(directory)]
        if reference:
            command.append("--reference")
        log = directory / "report.log"
        try:
            commands([command], [log])
        except RuntimeError:
            # Accept a declared failed coarse-grid check as a pilot result,
            # never a traceback, invalid closure, or failed final refinement.
            message = log.read_text(encoding="utf-8").rstrip().splitlines()[-1]
            result = read(directory / "analysis.json")
            if message != "Phase G history gate failed; inspect analysis.json" or not admissible_history(
                result, allow_angular_failure=args.allow_angular_failure
            ):
                raise
        return read(directory / "analysis.json")

    with run_lock(output):
        try:
            if args.mode in ("native", "run"):
                if args.binary is None:
                    raise ValueError("Native collection needs --binary")
                for case in cases:
                    case_id = case["id"]
                    save("COLLECTING_MAGNETO2D", case_id)
                    directory = output / "native" / case_id
                    directory.mkdir(parents=True, exist_ok=True)
                    base = [
                        sys.executable,
                        "-m",
                        "tools.phase_g_loss.native",
                        "--case",
                        case_id,
                        "--out",
                        str(directory),
                        "--binary",
                        str(args.binary.resolve()),
                    ]
                    if not all((directory / f"position-{i:04d}" / "position.json").exists() for i in range(385)):
                        commands([base + ["--limit", "1"]], [directory / "bootstrap.log"])
                        commands(
                            [base + ["--shard", f"{i}/{args.native_workers}"] for i in range(args.native_workers)],
                            [directory / f"worker-{i}.log" for i in range(args.native_workers)],
                        )
                    result = analyse_case(directory)
                    if not result["numerical_history_pass"]:
                        state["native_angular_failures"].append(case_id)
                    from tools.phase_g_loss.report import summary

                    summary(output, cases)
                    state["native_completed"].append(case_id)
                    save("MAGNETO2D_CASE_COMPLETE", case_id)
            if args.mode in ("femm", "run"):
                # All native conditions finish before any FEMM loss solve.
                for case in cases:
                    analysis_path = output / "native" / case["id"] / "analysis.json"
                    from tools.phase_g_loss.report import admissible_history

                    if not analysis_path.exists() or not admissible_history(read(analysis_path), allow_angular_failure=args.allow_angular_failure):
                        raise ValueError("Complete and audit every selected native case before FEMM")
                    if not read(analysis_path)["numerical_history_pass"] and case["id"] not in state["native_angular_failures"]:
                        state["native_angular_failures"].append(case["id"])
                    if case["id"] not in state["native_completed"]:
                        state["native_completed"].append(case["id"])
                while live_femm_count():
                    save("WAITING_FOR_EXISTING_FEMM_WORKERS")
                    if not args.wait_for_femm:
                        raise RuntimeError("Existing FEMM instances detected; close/finish them or use --wait-for-femm")
                    time.sleep(10)
                if args.femm_python is None:
                    raise ValueError("FEMM collection needs its pinned --femm-python environment")
                for case in cases:
                    case_id = case["id"]
                    save("COLLECTING_FEMM", case_id)
                    native = output / "native" / case_id
                    directory = output / "femm" / case_id
                    directory.mkdir(parents=True, exist_ok=True)
                    base = [
                        str(args.femm_python),
                        "-m",
                        "tools.phase_g_loss.femm",
                        "--case",
                        case_id,
                        "--native",
                        str(native),
                        "--out",
                        str(directory),
                    ]
                    if args.allow_angular_failure and case_id.startswith("distributed-spm-"):
                        base.append("--allow-angular-failure")
                    commands([base + ["--limit", "1"]], [directory / "bootstrap.log"])
                    commands(
                        [base + ["--shard", f"{i}/{args.femm_workers}"] for i in range(args.femm_workers)],
                        [directory / f"worker-{i}.log" for i in range(args.femm_workers)],
                    )
                    result = analyse_case(directory, reference=True)
                    if not result["numerical_history_pass"]:
                        state["femm_angular_failures"].append(case_id)
                    from tools.phase_g_loss.report import compare, summary

                    comparison = compare(read(native / "analysis.json"), read(directory / "analysis.json"))
                    write(output / "reports" / (case_id + ".json"), comparison)
                    summary(output, cases)
                    if not comparison["component_comparison_pass"]:
                        if not (args.allow_angular_failure and case_id.startswith("distributed-spm-") and comparison["component_agreement_pass"]):
                            raise RuntimeError("Phase G component comparison failed: " + case_id)
                    state["femm_completed"].append(case_id)
                    save("FEMM_CASE_COMPLETE", case_id)
                save(
                    "PILOT_COLLECTION_COMPLETE_WITH_ANGULAR_FAILURES"
                    if state["native_angular_failures"] or state["femm_angular_failures"]
                    else "NUMERICAL_COLLECTION_COMPLETE_EXPERIMENTAL"
                )
            else:
                save("MAGNETO2D_COMPLETE_FEMM_NOT_STARTED")
        except BaseException as exc:
            state["error"] = str(exc)
            save("STOPPED_WITH_CHECKPOINTS")
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("native", "femm", "run"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--femm-python", type=Path)
    parser.add_argument("--native-workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--femm-workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--wait-for-femm", action="store_true")
    parser.add_argument(
        "--allow-angular-failure",
        action="store_true",
        help="Owner-approved distributed-fixture pilot: retain failed 96-to-192 checks; final refinement and closure must pass",
    )
    parser.add_argument("--case", action="append")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
