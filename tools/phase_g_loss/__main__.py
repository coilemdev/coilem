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
                child.terminate()
        for child in children:
            child.wait()
        for stream in streams:
            stream.close()


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
        if registration != old:
            raise ValueError("Campaign identity changed; use a fresh directory")
    else:
        write(registration_path, registration)
    state = {
        "status": "STARTING",
        "candidate": source,
        "registration_sha256": sha(registration_path),
        "native_completed": [],
        "femm_completed": [],
        "qualification_complete": False,
    }

    def save(status, case=None):
        state.update(status=status, current_case=case, updated_utc=datetime.now(timezone.utc).isoformat())
        write(output / "run-state.json", state)

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
                    commands([base + ["--limit", "1"]], [directory / "bootstrap.log"])
                    commands(
                        [base + ["--shard", f"{i}/{args.native_workers}"] for i in range(args.native_workers)],
                        [directory / f"worker-{i}.log" for i in range(args.native_workers)],
                    )
                    commands([[sys.executable, "-m", "tools.phase_g_loss.report", "--history", str(directory)]], [directory / "report.log"])
                    from tools.phase_g_loss.report import summary

                    summary(output, cases)
                    state["native_completed"].append(case_id)
                    save("MAGNETO2D_CASE_COMPLETE", case_id)
            if args.mode in ("femm", "run"):
                # All native conditions finish before any FEMM loss solve.
                for case in cases:
                    analysis_path = output / "native" / case["id"] / "analysis.json"
                    if not analysis_path.exists() or not read(analysis_path)["numerical_history_pass"]:
                        raise ValueError("Complete and audit every selected native case before FEMM")
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
                    commands([base + ["--limit", "1"]], [directory / "bootstrap.log"])
                    commands(
                        [base + ["--shard", f"{i}/{args.femm_workers}"] for i in range(args.femm_workers)],
                        [directory / f"worker-{i}.log" for i in range(args.femm_workers)],
                    )
                    commands(
                        [[sys.executable, "-m", "tools.phase_g_loss.report", "--history", str(directory), "--reference"]], [directory / "report.log"]
                    )
                    from tools.phase_g_loss.report import compare, summary

                    comparison = compare(read(native / "analysis.json"), read(directory / "analysis.json"))
                    write(output / "reports" / (case_id + ".json"), comparison)
                    summary(output, cases)
                    if not comparison["component_comparison_pass"]:
                        raise RuntimeError("Phase G component comparison failed: " + case_id)
                    state["femm_completed"].append(case_id)
                    save("FEMM_CASE_COMPLETE", case_id)
                save("NUMERICAL_COLLECTION_COMPLETE_EXPERIMENTAL")
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
    parser.add_argument("--case", action="append")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
