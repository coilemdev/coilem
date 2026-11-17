"""Run the 5.9 stator/DC-copper qualification independently of rotor loss."""
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from tools.benchmark_suite.external_contract import run_lock
from tools.phase_g_loss.__main__ import commands, live_femm_count
from tools.phase_g_loss.contract import ROOT, SUITE, read, sha, suite, write
from tools.phase_g_loss.stator_contract import PROFILE
from tools.phase_g_loss.stator_reproduction import verify_measurement_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--legacy", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--femm-python", required=True, type=Path)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    output = args.out.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep benchmark data outside source")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("Commit the qualification implementation before measuring")
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    cases = [case for case in suite()["cases"] if not args.case or case["id"] in args.case]
    if len(cases) != len(set(args.case or [case["id"] for case in cases])):
        raise ValueError("Unknown or duplicate cases")
    output.mkdir(parents=True, exist_ok=True)
    registration = {"schema": "coilem.stator_dc_copper_campaign/v1", "candidate": candidate,
                    "profile_sha256": sha(PROFILE), "fixture_suite_sha256": sha(SUITE),
                    "binary_sha256": sha(args.binary), "cases": [case["id"] for case in cases],
                    "legacy": str(args.legacy.resolve()), "femm_workers_per_case": 2, "femm_worker_limit": 4,
                    "rotor_qualification_required": False}
    path = output / "registration.json"
    if path.exists():
        old = read(path)
        if old["candidate"] != candidate:
            verify_measurement_sources(output)
            registration["candidate"] = old["candidate"]
        if old != registration:
            raise ValueError("Registered stator/DC-copper campaign changed; use a new directory")
    write(path, registration)
    state = {"status": "STARTING", "candidate": candidate, "native_completed": [], "femm_completed": [],
             "active_cases": [], "failed_component_cases": [], "rotor_loss_status": "experimental"}
    def save(status):
        state.update(status=status, updated_utc=datetime.now(timezone.utc).isoformat())
        write(output / "run-state.json", state)
    with run_lock(output):
        try:
            for case in cases:
                cid = case["id"]
                state["active_cases"] = [cid]
                save("COLLECTING_PRODUCTION_STATOR")
                target = output / "native" / cid
                target.mkdir(parents=True, exist_ok=True)
                command = [sys.executable, "-m", "tools.phase_g_loss.stator_native", "--case", cid,
                           "--out", str(target), "--binary", str(args.binary.resolve())]
                commands([command], [target / "worker.log"])
                state["native_completed"].append(cid)
                from tools.phase_g_loss.stator_report import report
                report(output)
            if live_femm_count():
                raise ValueError("Existing FEMM sessions detected; refuse to exceed the four-worker budget")
            cancel = Event()
            def collect(case):
                cid = case["id"]
                target = output / "femm" / cid
                target.mkdir(parents=True, exist_ok=True)
                base = [str(args.femm_python), "-m", "tools.phase_g_loss.stator_femm", "--case", cid,
                        "--native", str(output / "native" / cid), "--legacy", str(args.legacy.resolve()), "--out", str(target)]
                commands([base + ["--prepare-only"]], [target / "bootstrap.log"], cancel)
                commands([base + ["--shard", f"{i}/2"] for i in range(2)], [target / f"worker-{i}.log" for i in range(2)], cancel)
                return cid
            # Exercise the newly used outer reference adapter before spending
            # hours collecting the distributed fixture. This changes no input.
            reference_order = sorted(cases, key=lambda case: not case["id"].startswith("outer-spm-"))
            active, pending = {}, iter(reference_order)
            with ThreadPoolExecutor(max_workers=2) as pool:
                try:
                    exhausted = False
                    while active or not exhausted:
                        while len(active) < 2 and not exhausted:
                            case = next(pending, None)
                            if case is None:
                                exhausted = True
                                break
                            active[pool.submit(collect, case)] = case["id"]
                        state["active_cases"] = list(active.values())
                        save("COLLECTING_STATOR_FEMM")
                        if not active:
                            break
                        finished, _ = wait(active, return_when=FIRST_COMPLETED)
                        for future in finished:
                            cid = active.pop(future)
                            future.result()
                            state["femm_completed"].append(cid)
                            from tools.phase_g_loss.stator_report import report
                            results = report(output)
                            state["failed_component_cases"] = [r["case_id"] for r in results if not r["reference_checks_pass"]]
                except BaseException:
                    cancel.set()
                    raise
            state["active_cases"] = []
            save("STATOR_COPPER_REFERENCE_COMPLETE_WITH_FAILED_CHECKS" if state["failed_component_cases"] else "STATOR_COPPER_REFERENCE_COMPLETE")
        except BaseException as exc:
            state["error"] = str(exc)
            save("STOPPED_WITH_CHECKPOINTS")
            raise


if __name__ == "__main__":
    main()
