"""Bounded, resumable processes for an operator-supplied reference producer.

The external module supplies identity(), cases() and measure(case_id, directory).
It owns solver sessions and must close them when its worker process terminates.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path

from tools.benchmark_suite.external_contract import ROOT, json_bytes, now, read, run_lock, sha, write


@contextmanager
def producer_imports(path):
    """Make sibling imports available without changing later caller imports."""
    previous = sys.path[:]
    sys.path.insert(0, str(path.parent))
    try:
        yield
    finally:
        sys.path[:] = previous


def load_producer(path):
    spec = importlib.util.spec_from_file_location("_coilem_reference_producer", path)
    if spec is None or spec.loader is None:
        raise ValueError("Expected an external Python producer module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with producer_imports(path):
        spec.loader.exec_module(module)
    return module


def identity(producer, path):
    with producer_imports(path):
        physical = producer.identity()
    value = {
        "producer": physical, "producer_sha256": sha(path),
        "runner_sources": {name: sha(ROOT / name) for name in (
            "tools/benchmark_suite/external.py", "tools/benchmark_suite/external_contract.py", "tools/run_reference_benchmark.py",
        )},
        "python": sys.version, "python_executable_sha256": sha(sys.executable),
    }
    return json.loads(json.dumps(value, allow_nan=False))


def safe_id(value):
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
        raise ValueError("Invalid reference case id")
    if value.endswith(".") or value.split(".")[0].lower() in reserved:
        raise ValueError("Reserved reference case id")
    return value


def result_path(case, relative):
    if not isinstance(relative, str) or not re.fullmatch(rf"jobs/{re.escape(case)}/result(?:-[0-9a-f]{{12}})?\.json", relative):
        raise ValueError("Registered reference job result path changed")
    return relative


def verify(output, job, expected):
    request = output / job["request"]
    if sha(request) != job["request_sha256"] or read(request)["identity"] != expected:
        raise ValueError("Registered reference request changed")
    result = output / job["result"]
    if not result.is_file():
        raise ValueError("Recorded reference evidence missing")
    if job.get("result_sha256") and sha(result) != job["result_sha256"]:
        raise ValueError("Recorded reference result changed")
    data = read(result)
    if not isinstance(data, dict) or data.get("status") not in ("COMPLETE", "ERROR"):
        raise ValueError("Invalid reference result status")
    if data.get("request_sha256") != job["request_sha256"]:
        raise ValueError("Reference result belongs to a different request")
    if data["status"] == "COMPLETE" and (data.get("identity_before") != expected or data.get("identity_after") != expected):
        raise ValueError("Reference producer identity mismatch")
    return data


def exited_process_group(pgid):
    """Confirm that a Darwin group is gone or contains only zombies."""
    try:
        result = subprocess.run(["ps", "-ax", "-o", "pgid=,stat="], capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 2 or not parts[0].isdigit():
            return False
        if int(parts[0]) == pgid and not parts[1].startswith("Z"):
            return False
    return True


def signal_worker_group(process, sig):
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin can return EPERM for a group containing only the just-exited
        # leader's zombie. Reap it, then retry: a live or inaccessible child
        # must still surface its real permission error.
        if process.poll() is None:
            raise
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Orphaned zombie children can outlive the reaped leader until
            # launchd reaps them. They cannot be signalled or do more work.
            if sys.platform != "darwin" or not exited_process_group(process.pid):
                raise


def stop(process):
    alive = process.poll() is None
    if os.name == "nt":
        if alive:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, check=False)
    else:
        # A session can still contain owned children after its leader exits.
        signal_worker_group(process, signal.SIGTERM)
    try:
        if alive:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    finally:
        if os.name != "nt":
            signal_worker_group(process, signal.SIGKILL)


def worker(request_path, result_path, deadline_ns=None):
    with run_lock(result_path.parent):
        if result_path.exists():
            raise ValueError("Refusing to overwrite reference evidence")
        started = time.perf_counter()
        request = read(request_path)
        data = {"schema": "coilem.external_measurement/v1", "started_at": now(), "request_sha256": sha(request_path)}
        finished = threading.Event()
        commit = threading.Lock()

        def expire():
            with commit:
                if finished.is_set():
                    return
                failure = {**data, "status": "ERROR", "error": "Reference worker timed out",
                           "runtime_s": time.perf_counter() - started, "completed_at": now(), "deadline_unix_ns": deadline_ns}
                try:
                    write(result_path, failure)
                finally:
                    # Worker exit closes producer-owned kill-on-close solver jobs.
                    if os.name == "nt":
                        try:
                            subprocess.run(["taskkill", "/PID", str(os.getpid()), "/T", "/F"],
                                           capture_output=True, timeout=5, check=False)
                        finally:
                            os._exit(124)
                    if os.getpgrp() == os.getpid():
                        os.killpg(os.getpid(), signal.SIGKILL)
                    os._exit(124)

        timer = None
        if deadline_ns is not None:
            timer = threading.Timer(max(0, (deadline_ns - time.time_ns()) / 1e9), expire)
            timer.daemon = True
            timer.start()
        try:
            try:
                producer_path = Path(request["producer_path"])
                producer = load_producer(producer_path)
                before = identity(producer, producer_path)
                if before != request["identity"]:
                    raise ValueError("Reference producer changed before measurement")
                work = result_path.parent / "attempts" / uuid.uuid4().hex[:12]
                work.mkdir(parents=True)
                data["work_directory"] = work.relative_to(result_path.parent).as_posix()
                with producer_imports(producer_path):
                    measurement = producer.measure(request["case_id"], work)
                after = identity(producer, producer_path)
                if after != before:
                    raise ValueError("Reference producer changed during measurement")
                if not isinstance(measurement, dict) or measurement.get("status") != "COMPLETE":
                    raise ValueError("External producer did not return a COMPLETE measurement")
                json.dumps(measurement, allow_nan=False)
                data.update(status="COMPLETE", identity_before=before, identity_after=after, measurement=measurement)
            except Exception as exc:
                data.update(status="ERROR", error=str(exc), traceback=traceback.format_exc())
            data.update(runtime_s=time.perf_counter() - started, completed_at=now())
            with commit:
                write(result_path, data)
                finished.set()
            return 0 if data["status"] == "COMPLETE" else 2
        finally:
            if timer is not None:
                timer.cancel()


def timing_hints(path, weighted, budget):
    hints = {}
    if path is None:
        return hints
    document = read(path)
    if not isinstance(document, dict) or not isinstance(document.get("jobs"), list):
        raise ValueError("Timing hints need a jobs list")
    for row in document["jobs"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid timing hint")
        case = safe_id(row.get("case_id"))
        duration = row.get("runtime_s")
        duration = 0 if duration is None else duration
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ValueError("Timing runtime_s must be a finite non-negative number")
        cost = row.get("worker_cost", 1) if weighted else 1
        if type(cost) is not int or not 1 <= cost <= budget:
            raise ValueError("Each worker cost must be a positive integer within the worker budget")
        previous = hints.setdefault(case, {"runtime_s": 0, "worker_cost": 1})
        previous["runtime_s"] += duration
        if not math.isfinite(previous["runtime_s"]):
            raise ValueError("Aggregated timing runtime_s must be finite")
        previous["worker_cost"] = max(previous["worker_cost"], cost)
    return hints


def finish_job(output, job, runtime, code=None, interrupted=False):
    if code is not None:
        job["exit_code"] = code
    if interrupted:
        # The controller stopped this worker, so a signal exit code is its own
        # doing; resume must not later read it as the producer failing.
        job["stopped_by_controller"] = True
    if job.get("status") not in ("COMPLETE", "ERROR") or not job.get("completed_at"):
        job["completed_at"] = now()
    if (output / job["result"]).exists():
        try:
            result = verify(output, job, runtime)
        except Exception as exc:
            job.update(status="ERROR", error=str(exc), integrity_failure=True)
            raise
        job.update(status=result["status"], result_sha256=sha(output / job["result"]))
        if result["status"] == "ERROR":
            job["error"] = result.get("error", "External producer failed")
        elif code not in (None, 0) and not interrupted:
            job.update(status="ERROR", error=f"Worker exited with code {code}")
    else:
        job.update(status="INTERRUPTED" if interrupted else "ERROR",
                   error="Worker interrupted" if interrupted else "Worker exited without a measurement")


def execute(args):
    if type(args.workers) is not int or not 1 <= args.workers <= 16 or not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
        raise ValueError("Use 1..16 workers and a positive timeout")
    retry_failed = getattr(args, "retry_failed", False)
    if retry_failed and not args.resume:
        raise ValueError("--retry-failed requires --resume")
    producer_path, output = args.producer.resolve(), args.out_dir.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep reference execution artifacts outside the source checkout")
    producer = load_producer(producer_path)
    runtime = identity(producer, producer_path)
    with producer_imports(producer_path):
        cases = producer.cases()
    if not isinstance(cases, dict) or not cases or any(not isinstance(phase, str) for phase in cases.values()):
        raise ValueError("Producer cases() must return a nonempty mapping of case ids to phases")
    for case in cases:
        safe_id(case)
    if len({case.casefold() for case in cases}) != len(cases):
        raise ValueError("Reference case ids collide when case-folded")
    selected = {case: phase for case, phase in cases.items() if not args.case or case in args.case}
    if not selected or (args.case and set(args.case) - selected.keys()):
        raise ValueError("No cases selected or unknown reference case")
    budget = getattr(args, "worker_budget", None)
    weighted = budget is not None
    if weighted and (type(budget) is not int or budget < 1):
        raise ValueError("Worker budget must be a positive integer")
    budget = budget if weighted else args.workers
    hints = timing_hints(args.timings, weighted, budget)
    costs = {case: hints.get(case, {}).get("worker_cost", 1) for case in selected}
    requests = {case: {"case_id": case, "producer_path": str(producer_path), "identity": runtime} for case in selected}
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
            jobs = [{"case_id": case, "phase": phase, "stage": "reference", "status": "READY",
                     "request": f"jobs/{case}/request.json", "request_sha256": hashlib.sha256(json_bytes(requests[case])).hexdigest(),
                     "result": f"jobs/{case}/result.json"} for case, phase in selected.items()]
            manifest = {"schema": "coilem.external_reference_run/v1", "identity": runtime, "selection": selected,
                        "status": "READY", "started_at": now(), "jobs": jobs, "execution_sessions": []}
            write(manifest_path, manifest)
        if [job["case_id"] for job in manifest["jobs"]] != list(selected):
            raise ValueError("Registered reference job coverage or order changed")
        for job in manifest["jobs"]:
            case = job["case_id"]
            if job["request"] != f"jobs/{case}/request.json" or job["phase"] != selected[case] or job["stage"] != "reference":
                raise ValueError("Registered reference job paths or phase changed")
            result_path(case, job["result"])
        pending = []
        for job in manifest["jobs"]:
            case = job["case_id"]
            directory = (output / job["result"]).parent
            with run_lock(directory):
                request_file = output / job["request"]
                if not request_file.exists() and manifest["status"] == "READY" and not manifest["execution_sessions"]:
                    if hashlib.sha256(json_bytes(requests[case])).hexdigest() != job["request_sha256"]:
                        raise ValueError("Registered reference request changed")
                    write(request_file, requests[case])
                if sha(request_file) != job["request_sha256"] or read(request_file) != requests[case]:
                    raise ValueError("Registered reference request changed")
                seen = {job["result"]}
                for old in job.get("attempt_history", []):
                    result_path(case, old["result"])
                    if old["result"] in seen:
                        raise ValueError("Repeated reference attempt path")
                    seen.add(old["result"])
                    if old.get("result_sha256"):
                        verify(output, {**job, **old}, runtime)
                    elif (output / old["result"]).exists():
                        raise ValueError("Unregistered result appeared in an earlier attempt")
                if (output / job["result"]).exists():
                    finish_job(output, job, runtime, code=job.get("exit_code"),
                               interrupted=job.get("stopped_by_controller", False))
                elif job.get("result_sha256") or job["status"] == "COMPLETE":
                    raise ValueError("Recorded reference evidence missing; restore it or use a new output directory")
                if job["status"] == "ERROR":
                    if not retry_failed:
                        raise ValueError("Failed evidence retained; use --resume --retry-failed to retry failed cases")
                    fields = ("result", "result_sha256", "status", "error", "started_at", "completed_at", "exit_code", "pid",
                              "stopped_by_controller")
                    job.setdefault("attempt_history", []).append({key: job[key] for key in fields if key in job})
                    job["result"] = f"jobs/{case}/result-{uuid.uuid4().hex[:12]}.json"
                    for key in ("result_sha256", "error", "started_at", "completed_at", "exit_code", "pid", "integrity_failure",
                                "stopped_by_controller"):
                        job.pop(key, None)
                    job["status"] = "READY"
                if job["status"] != "COMPLETE":
                    pending.append(job)
        if args.timings:
            pending.sort(key=lambda job: -hints.get(job["case_id"], {}).get("runtime_s", 0))
        session = {"started_at": now(), "workers": args.workers, "timeout_s": args.timeout_s,
                   "order": "longest_first" if args.timings else "registered", "retry_failed": retry_failed,
                   "worker_budget": budget, "weighted": weighted, "worker_costs": costs,
                   "planned_order": [job["case_id"] for job in pending], "launch_order": [],
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
                    active_cost = sum(costs[item[0]["case_id"]] for item in running)
                    eligible = next((i for i, job in enumerate(pending) if active_cost + costs[job["case_id"]] <= budget), None)
                    if eligible is None:
                        break
                    if identity(producer, producer_path) != runtime:
                        raise ValueError("Reference producer changed; remaining jobs were not launched")
                    job = pending.pop(eligible)
                    log = ((output / job["result"]).parent / "worker.log").open("ab")
                    deadline = time.time_ns() + int(args.timeout_s * 1e9)
                    try:
                        process = subprocess.Popen(
                            [sys.executable, "-u", "-m", "tools.benchmark_suite.external", "--request", str(output / job["request"]),
                             "--result", str(output / job["result"]), "--deadline-ns", str(deadline)], cwd=ROOT,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt",
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                        )
                    except BaseException:
                        log.close()
                        raise
                    running.append((job, process, log, time.perf_counter()))
                    for name in ("error", "completed_at", "exit_code", "stopped_by_controller"):
                        job.pop(name, None)
                    job.update(status="RUNNING", started_at=now(), pid=process.pid,
                               worker_cost=costs[job["case_id"]], deadline_unix_ns=deadline)
                    session["launch_order"].append(job["case_id"])
                    write(manifest_path, manifest)
                    print(f"{job['case_id']}: starting reference job (pid {process.pid})", flush=True)
                for item in list(running):
                    job, process, log, launched = item
                    code = process.poll()
                    timed_out = code is None and time.perf_counter() - launched > args.timeout_s
                    if timed_out:
                        stop(process)
                        code = process.returncode
                    if code is None:
                        continue
                    finish_job(output, job, runtime, code=code)
                    if timed_out and job["status"] != "COMPLETE":
                        job["error"] = "Reference job timed out"
                    if identity(producer, producer_path) != runtime:
                        raise ValueError("Reference producer changed during the run")
                    write(manifest_path, manifest)
                    log.close()
                    running.remove(item)
                    print(f"{job['case_id']}: {job['status']}", flush=True)
                if pending or running:
                    time.sleep(0.1)
            failed = any(job["status"] != "COMPLETE" for job in manifest["jobs"])
            manifest.update(status="COMPLETE_WITH_ERRORS" if failed else "COMPLETE", completed_at=now())
        except BaseException as exc:
            manifest.update(status="INTERRUPTED", error=str(exc))
            raise
        finally:
            cleanup_errors = []
            for job, process, log, _ in running:
                try:
                    stop(process)
                    if not job.get("integrity_failure"):
                        finish_job(output, job, runtime, code=process.returncode, interrupted=True)
                except Exception as exc:
                    cleanup_errors.append({"case_id": job["case_id"], "pid": process.pid, "error": str(exc)})
                finally:
                    log.close()
            if cleanup_errors:
                manifest.update(status="CLEANUP_ERROR", cleanup_errors=cleanup_errors)
            session.update(completed_at=now(), wall_s=time.perf_counter() - started)
            write(manifest_path, manifest)
        return 0 if manifest["status"] == "COMPLETE" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, required=True, help="External Python module; not included in the public runtime")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--case", action="append", help="Select a case; repeat to select several; default all producer cases")
    parser.add_argument("--workers", type=int, default=1, help="Independent case processes, 1..16; default serial")
    parser.add_argument("--timeout-s", type=float, default=14400)
    parser.add_argument("--timings", type=Path, help="Runtime-analysis JSON: sum durations and maximum worker_cost per case")
    parser.add_argument("--worker-budget", type=int, help="Opt into summed worker_cost limits from --timings; missing costs are 1")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true", help="With --resume, retry failed cases and preserve every earlier result")
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
    parser.add_argument("--deadline-ns", type=int)
    args = parser.parse_args()
    raise SystemExit(worker(args.request, args.result, args.deadline_ns))
