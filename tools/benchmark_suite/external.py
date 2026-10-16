"""Bounded, resumable processes for an operator-supplied reference producer.

The external module must expose identity(), cases() -> {id: phase}, and
measure(case_id, work_directory) -> a COMPLETE measurement dictionary. It owns
its solver sessions and must clean them up if its process is terminated.
"""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

from tools.benchmark_suite.contract import ROOT, now, read, run_lock, sha, write


def load_producer(path):
    spec = importlib.util.spec_from_file_location("_coilem_reference_producer", path)
    if spec is None or spec.loader is None:
        raise ValueError("Expected an external Python producer module")
    module = importlib.util.module_from_spec(spec)
    # Match normal module execution for sibling imports and dataclass annotations.
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def identity(producer, path):
    return {
        "producer": producer.identity(), "producer_sha256": sha(path),
        "runner_sources": {name: sha(ROOT / name) for name in (
            "tools/benchmark_suite/external.py", "tools/benchmark_suite/contract.py", "tools/run_reference_benchmark.py",
        )},
        "python": sys.version, "python_executable_sha256": sha(sys.executable),
    }


def safe_id(value):
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
        raise ValueError("Invalid reference case id")
    if value.endswith(".") or value.split(".")[0].lower() in reserved:
        raise ValueError("Reserved reference case id")
    return value


def verify(output, job, expected):
    request = output / job["request"]
    if sha(request) != job["request_sha256"] or read(request)["identity"] != expected:
        raise ValueError("Registered reference request changed")
    result = output / job["result"]
    if job.get("result_sha256") and sha(result) != job["result_sha256"]:
        raise ValueError("Recorded reference result changed")
    data = read(result)
    if data["request_sha256"] != job["request_sha256"]:
        raise ValueError("Reference result belongs to a different request")
    if data["status"] == "COMPLETE" and (data["identity_before"] != expected or data["identity_after"] != expected):
        raise ValueError("Reference producer identity mismatch")
    return data


def stop(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Exact owned process tree; never terminate solvers by executable name.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # The owned group exited between the wait and signal.
        process.wait(timeout=5)


def worker(request_path, result_path):
    # This lock outlives the controller if it crashes. Resume cannot duplicate a live job.
    with run_lock(result_path.parent):
        if result_path.exists():
            raise ValueError("Refusing to overwrite reference evidence")
        started = time.perf_counter()
        request = read(request_path)
        data = {"schema": "coilem.external_measurement/v1", "started_at": now(), "request_sha256": sha(request_path)}
        try:
            producer_path = Path(request["producer_path"])
            producer = load_producer(producer_path)
            before = identity(producer, producer_path)
            if before != request["identity"]:
                raise ValueError("Reference producer changed before measurement")
            work = result_path.parent / "attempts" / uuid.uuid4().hex[:12]
            work.mkdir(parents=True)
            data["work_directory"] = work.relative_to(result_path.parent).as_posix()
            measurement = producer.measure(request["case_id"], work)
            after = identity(producer, producer_path)
            if after != before:
                raise ValueError("Reference producer changed during measurement")
            if not isinstance(measurement, dict) or measurement.get("status") != "COMPLETE":
                raise ValueError("External producer did not return a COMPLETE measurement")
            data.update(status="COMPLETE", identity_before=before, identity_after=after, measurement=measurement)
        except Exception as exc:
            data.update(status="ERROR", error=str(exc), traceback=traceback.format_exc())
        data.update(runtime_s=time.perf_counter() - started, completed_at=now())
        write(result_path, data)
        return 0 if data["status"] == "COMPLETE" else 2


def execute(args):
    if not 1 <= args.workers <= 16 or not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
        raise ValueError("Use 1..16 workers and a positive timeout")
    producer_path, output = args.producer.resolve(), args.out_dir.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep reference execution artifacts outside the source checkout")
    producer = load_producer(producer_path)
    runtime = identity(producer, producer_path)
    cases = producer.cases()
    if not isinstance(cases, dict) or not cases or any(not isinstance(phase, str) for phase in cases.values()):
        raise ValueError("Producer cases() must return a nonempty mapping of case ids to phases")
    for case_id in cases:
        safe_id(case_id)
    selected = {case_id: phase for case_id, phase in cases.items() if not args.case or case_id in args.case}
    if not selected or (args.case and set(args.case) - selected.keys()):
        raise ValueError("No cases selected or unknown reference case")
    with run_lock(output):
        manifest_path = output / "run_manifest.json"
        if manifest_path.exists():
            if not args.resume:
                raise ValueError("Existing run; use --resume or a new output directory")
            manifest = read(manifest_path)
            if manifest["identity"] != runtime or manifest["selection"] != selected:
                raise ValueError("Resume refused: source, producer, runtime or selected cases changed")
        else:
            if args.resume:
                raise ValueError("No registered reference run to resume")
            if any(path.name != "run.lock" for path in output.iterdir()):
                raise ValueError("Use an empty directory for a new reference run")
            jobs = []
            for case_id, phase in selected.items():
                directory = Path("jobs") / case_id
                request = {"case_id": case_id, "producer_path": str(producer_path), "identity": runtime}
                request_path = output / directory / "request.json"
                write(request_path, request)
                jobs.append({"case_id": case_id, "phase": phase, "stage": "reference", "status": "READY",
                             "request": (directory / "request.json").as_posix(), "request_sha256": sha(request_path),
                             "result": (directory / "result.json").as_posix()})
            manifest = {"schema": "coilem.external_reference_run/v1", "identity": runtime, "selection": selected,
                        "started_at": now(), "jobs": jobs, "execution_sessions": []}
        if [job["case_id"] for job in manifest["jobs"]] != list(selected):
            raise ValueError("Registered reference job coverage or order changed")
        for job in manifest["jobs"]:
            directory = Path("jobs") / job["case_id"]
            if (job["request"] != (directory / "request.json").as_posix()
                    or job["result"] != (directory / "result.json").as_posix()
                    or job["phase"] != selected[job["case_id"]] or job["stage"] != "reference"):
                raise ValueError("Registered reference job paths or phase changed")
        pending = []
        # Preflight every job before updating the manifest, including jobs whose worker outlived a controller.
        for job in manifest["jobs"]:
            with run_lock((output / job["result"]).parent):
                if sha(output / job["request"]) != job["request_sha256"]:
                    raise ValueError("Registered reference request changed")
                request = read(output / job["request"])
                if request != {"case_id": job["case_id"], "producer_path": str(producer_path), "identity": runtime}:
                    raise ValueError("Registered reference request changed")
                if (output / job["result"]).exists():
                    result = verify(output, job, runtime)
                    job.update(status=result["status"], result_sha256=sha(output / job["result"]))
                    if job["status"] != "COMPLETE":
                        raise ValueError("Failed evidence retained; inspect it and use a new output directory")
                else:
                    pending.append(job)
        if args.timings:
            durations = {job["case_id"]: job.get("runtime_s") or 0 for job in read(args.timings)["jobs"]}
            pending.sort(key=lambda job: -durations.get(job["case_id"], 0))
        session = {"started_at": now(), "workers": args.workers, "timeout_s": args.timeout_s,
                   "order": "longest_first" if args.timings else "registered",
                   "launch_order": [job["case_id"] for job in pending],
                   "timings_sha256": sha(args.timings) if args.timings else None}
        manifest["execution_sessions"].append(session)
        manifest.update(status="RUNNING")
        manifest.pop("completed_at", None)
        manifest.pop("error", None)
        write(manifest_path, manifest)
        running = []
        started = time.perf_counter()
        try:
            while pending or running:
                while pending and len(running) < args.workers:
                    if identity(producer, producer_path) != runtime:
                        raise ValueError("Reference producer changed; remaining jobs were not launched")
                    job = pending.pop(0)
                    directory = (output / job["result"]).parent
                    log = (directory / "worker.log").open("ab")
                    try:
                        process = subprocess.Popen(
                            [sys.executable, "-u", "-m", "tools.benchmark_suite.external", "--request", str(output / job["request"]),
                             "--result", str(output / job["result"])], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=os.name != "nt",
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                        )
                    except BaseException:
                        log.close()
                        raise
                    running.append((job, process, log, time.perf_counter()))
                    for name in ("error", "completed_at", "exit_code"):
                        job.pop(name, None)
                    job.update(status="RUNNING", started_at=now(), pid=process.pid)
                    write(manifest_path, manifest)
                    print(f"{job['case_id']}: starting reference job (pid {process.pid})", flush=True)
                for item in list(running):
                    job, process, log, launched = item
                    code = process.poll()
                    if code is None:
                        if time.perf_counter() - launched > args.timeout_s:
                            raise ValueError(f"Reference job timed out: {job['case_id']}")
                        continue
                    log.close()
                    running.remove(item)
                    job.update(exit_code=code, completed_at=now())
                    if (output / job["result"]).exists():
                        result = verify(output, job, runtime)
                        job.update(status=result["status"], result_sha256=sha(output / job["result"]))
                    else:
                        job.update(status="ERROR", error="Worker exited without a measurement")
                    if code or job["status"] != "COMPLETE":
                        raise ValueError(f"Reference job failed: {job['case_id']}; inspect worker.log")
                    if identity(producer, producer_path) != runtime:
                        raise ValueError("Reference producer changed during the run")
                    write(manifest_path, manifest)
                    print(f"{job['case_id']}: COMPLETE", flush=True)
                if pending or running:
                    time.sleep(0.1)
            manifest.update(status="COMPLETE", completed_at=now())
        except BaseException as exc:
            manifest.update(status="INTERRUPTED", error=str(exc))
            raise
        finally:
            cleanup_errors = []
            for job, process, log, _ in running:
                try:
                    stop(process)
                except Exception as exc:
                    cleanup_errors.append({"case_id": job["case_id"], "pid": process.pid, "error": str(exc)})
                finally:
                    log.close()
                    job.update(status="INTERRUPTED")
            if cleanup_errors:
                manifest.update(status="CLEANUP_ERROR", cleanup_errors=cleanup_errors)
            session.update(completed_at=now(), wall_s=time.perf_counter() - started)
            write(manifest_path, manifest)
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, required=True, help="External Python module; not included in the public runtime")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--case", action="append", help="Select a case; repeat to select several; default all producer cases")
    parser.add_argument("--workers", type=int, default=1, help="Independent case processes, 1..16; default serial")
    parser.add_argument("--timeout-s", type=float, default=14400)
    parser.add_argument("--timings", type=Path, help="Runtime-analysis JSON used only to order jobs longest first")
    parser.add_argument("--resume", action="store_true")
    try:
        return execute(parser.parse_args())
    except (ValueError, OSError) as exc:
        print(f"Reference run refused: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Reference run interrupted; completed measurements retained.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(worker(args.request, args.result))
