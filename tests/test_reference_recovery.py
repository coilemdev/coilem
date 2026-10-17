"""Reproduce review findings with real worker processes and preserved evidence."""
import os
import signal
import subprocess
import sys
import time
from argparse import Namespace

import pytest

from tools.benchmark_suite import external
from tools.benchmark_suite.external_contract import ROOT, read, run_lock, sha, write


def setup_run(tmp_path, body, *, cases='{"a": "A", "b": "B", "c": "C"}', identity='{"fixed": 1}', timeout=10):
    producer = tmp_path / "producer.py"
    producer.write_text(
        'import time\nfrom pathlib import Path\n'
        f'def identity(): return {identity}\ndef cases(): return {cases}\n'
        'def measure(case, directory):\n' + body + '\n', encoding="utf-8",
    )
    return Namespace(producer=producer, out_dir=tmp_path / "run", workers=2, case=None,
                     timeout_s=timeout, timings=None, resume=False, worker_budget=None, retry_failed=False)


def test_retry_only_failed_case_preserves_successes_and_each_failed_result(tmp_path):
    args = setup_run(tmp_path,
        '    marker=Path(__file__).with_suffix(".failed")\n'
        '    if case=="b" and not marker.exists():\n'
        '        marker.touch()\n        raise RuntimeError("transient fixture failure")\n'
        '    time.sleep(.3)\n    return {"status":"COMPLETE", "case":case}')
    assert external.execute(args) == 2
    manifest_path = args.out_dir / "run_manifest.json"
    first = read(manifest_path)
    assert first["status"] == "COMPLETE_WITH_ERRORS"
    assert [job["status"] for job in first["jobs"]] == ["COMPLETE", "ERROR", "COMPLETE"]
    original = {j["case_id"]: j for j in first["jobs"]}
    failed = original["b"]
    args.resume = True
    original_manifest_hash = sha(manifest_path)
    with pytest.raises(ValueError, match="retry-failed"):
        external.execute(args)
    assert sha(manifest_path) == original_manifest_hash
    args.retry_failed = True
    assert external.execute(args) == 0
    after = read(manifest_path)
    assert after["execution_sessions"][-1]["launch_order"] == ["b"]
    for job in after["jobs"]:
        if job["case_id"] != "b":
            assert job == original[job["case_id"]]
            assert sha(args.out_dir / job["result"]) == job["result_sha256"]
        else:
            assert job["result"] != failed["result"]
            assert job["attempt_history"][0]["result_sha256"] == failed["result_sha256"]
    assert sha(args.out_dir / failed["result"]) == failed["result_sha256"]
    # Old errors remain immutable evidence even after a successful retry.
    (args.out_dir / failed["result"]).write_text('{}', encoding="utf-8")
    before = sha(manifest_path)
    with pytest.raises(ValueError, match="result changed"):
        external.execute(args)
    assert sha(manifest_path) == before


def test_missing_hash_recorded_result_refuses_before_another_solve(tmp_path, monkeypatch):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}')
    assert external.execute(args) == 0
    manifest_path = args.out_dir / "run_manifest.json"
    job = read(manifest_path)["jobs"][0]
    (args.out_dir / job["result"]).unlink()
    before = sha(manifest_path)
    args.resume, args.retry_failed = True, True
    monkeypatch.setattr(external.subprocess, "Popen", lambda *a, **k: pytest.fail("A recorded missing result was re-solved"))
    with pytest.raises(ValueError, match="evidence missing"):
        external.execute(args)
    assert sha(manifest_path) == before


@pytest.mark.parametrize("expression", ['float("nan")', 'float("inf")', 'Path("artifact")', 'b"not JSON"'])
def test_invalid_measurement_becomes_inspectable_error(tmp_path, expression):
    args = setup_run(tmp_path, f'    return {{"status":"COMPLETE", "value":{expression}}}', cases='{"a":"A"}')
    assert external.execute(args) == 2
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["status"] == "COMPLETE_WITH_ERRORS"
    data = read(args.out_dir / manifest["jobs"][0]["result"])
    assert data["status"] == "ERROR" and "traceback" in data and "measurement" not in data
    assert data["work_directory"].startswith("attempts/")


def test_json_compatible_identity_round_trip_and_resume(tmp_path):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}', identity='{"version":(4,2), 7:"key"}')
    assert external.execute(args) == 0
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["identity"]["producer"] == {"version": [4, 2], "7": "key"}
    args.resume = True
    assert external.execute(args) == 0


def test_interrupted_request_initialization_can_resume(tmp_path, monkeypatch):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}')
    original = external.write

    def interrupt(path, value):
        if path.name == "request.json" and path.parent.name == "b":
            raise KeyboardInterrupt()
        return original(path, value)

    monkeypatch.setattr(external, "write", interrupt)
    with pytest.raises(KeyboardInterrupt):
        external.execute(args)
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["status"] == "READY" and manifest["execution_sessions"] == []
    first_request = args.out_dir / manifest["jobs"][0]["request"]
    original_hash = sha(first_request)
    monkeypatch.setattr(external, "write", original)
    args.resume = True
    assert external.execute(args) == 0
    assert sha(first_request) == original_hash


def test_case_fold_collision_is_rejected_before_registration(tmp_path):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}', cases='{"Case":"A","case":"B"}')
    with pytest.raises(ValueError, match="case-folded"):
        external.execute(args)
    assert not args.out_dir.exists()


@pytest.mark.parametrize("value", ['"bad"', '-1', 'true', 'NaN', 'Infinity'])
def test_invalid_timing_is_rejected_before_output_creation(tmp_path, value):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}')
    args.timings = tmp_path / "timings.json"
    args.timings.write_text('{"jobs":[{"case_id":"a","runtime_s":' + value + '}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="finite|runtime_s"):
        external.execute(args)
    assert not args.out_dir.exists()


def test_multi_stage_hints_sum_runtime_and_take_maximum_cost(tmp_path):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}', cases='{"a":"A","b":"B"}')
    args.timings, args.worker_budget = tmp_path / "timings.json", 2
    write(args.timings, {"jobs": [
        {"case_id": "a", "stage": "standard", "runtime_s": 10, "worker_cost": 2},
        {"case_id": "a", "stage": "fine", "runtime_s": 5, "worker_cost": 1},
        {"case_id": "b", "runtime_s": 12, "worker_cost": 1},
    ]})
    assert external.execute(args) == 0
    session = read(args.out_dir / "run_manifest.json")["execution_sessions"][0]
    assert session["planned_order"] == ["a", "b"]
    assert session["worker_costs"] == {"a": 2, "b": 1}


def test_worker_deadline_is_enforced_without_a_controller(tmp_path):
    args = setup_run(tmp_path, '    time.sleep(30)\n    return {"status":"COMPLETE"}', cases='{"a":"A"}')
    request, result = tmp_path / "request.json", tmp_path / "job/result.json"
    write(request, {"case_id": "a", "producer_path": str(args.producer),
                    "identity": external.identity(external.load_producer(args.producer), args.producer)})
    command = [sys.executable, "-m", "tools.benchmark_suite.external", "--request", str(request),
               "--result", str(result), "--deadline-ns", str(time.time_ns() + 1_000_000_000)]
    process = subprocess.Popen(command, cwd=ROOT, start_new_session=os.name != "nt",
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert process.wait(timeout=10) != 0
        assert read(result)["status"] == "ERROR"
        assert "timed out" in read(result)["error"]
        with run_lock(result.parent):
            pass
    finally:
        external.stop(process)


def test_interrupt_retains_results_written_between_controller_polls(tmp_path, monkeypatch):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}', cases='{"a":"A","b":"B"}')
    original_sleep = time.sleep
    interrupted = False

    def interrupt(seconds):
        nonlocal interrupted
        if interrupted:
            return original_sleep(seconds)
        deadline = time.monotonic() + 5
        while len(list(args.out_dir.glob("jobs/*/result.json"))) != 2:
            assert time.monotonic() < deadline
            original_sleep(.02)
        # POSIX Popen.wait also sleeps; let cleanup wait after the one interrupt.
        interrupted = True
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(external.time, "sleep", interrupt)
        with pytest.raises(KeyboardInterrupt):
            external.execute(args)
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["status"] == "INTERRUPTED"
    assert all(job["status"] == "COMPLETE" for job in manifest["jobs"])
    args.resume = True
    assert external.execute(args) == 0
    assert read(args.out_dir / "run_manifest.json")["execution_sessions"][-1]["launch_order"] == []


def test_resume_keeps_results_whose_worker_was_stopped_after_writing(tmp_path, monkeypatch):
    # Each worker lingers after writing its result, so the interrupt's cleanup
    # stops it and it exits by signal. Resume must still accept the results.
    args = setup_run(tmp_path, '    import atexit\n    atexit.register(time.sleep, 1.0)\n    return {"status":"COMPLETE"}',
                     cases='{"a":"A","b":"B"}')
    original_sleep = time.sleep
    interrupted = False

    def interrupt(seconds):
        nonlocal interrupted
        if interrupted:
            return original_sleep(seconds)
        deadline = time.monotonic() + 5
        while len(list(args.out_dir.glob("jobs/*/result.json"))) != 2:
            assert time.monotonic() < deadline
            original_sleep(.02)
        interrupted = True
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(external.time, "sleep", interrupt)
        with pytest.raises(KeyboardInterrupt):
            external.execute(args)
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["status"] == "INTERRUPTED"
    assert all(job["status"] == "COMPLETE" and job["stopped_by_controller"] for job in manifest["jobs"])
    if os.name != "nt":
        assert all(job["exit_code"] < 0 for job in manifest["jobs"])
    args.resume = True
    assert external.execute(args) == 0
    resumed = read(args.out_dir / "run_manifest.json")
    assert resumed["status"] == "COMPLETE"
    assert resumed["execution_sessions"][-1]["launch_order"] == []


def test_verify_failure_records_terminal_status_before_abort(tmp_path, monkeypatch):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}')
    verify = external.verify

    def reject(output, job, runtime):
        if job["case_id"] == "a":
            raise ValueError("injected result integrity failure")
        return verify(output, job, runtime)

    monkeypatch.setattr(external, "verify", reject)
    with pytest.raises(ValueError, match="integrity failure"):
        external.execute(args)
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["jobs"][0]["status"] == "ERROR"
    assert all(job["status"] != "RUNNING" for job in manifest["jobs"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup; Windows producer uses Job Objects")
def test_stop_cleans_children_after_group_leader_exits(tmp_path):
    pidfile = tmp_path / "child.pid"
    code = ('import subprocess,sys; from pathlib import Path; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
            'Path(sys.argv[1]).write_text(str(p.pid))')
    process = subprocess.Popen([sys.executable, "-c", code, str(pidfile)], start_new_session=True)
    try:
        assert process.wait(timeout=5) == 0
        child = int(pidfile.read_text())
        os.kill(child, 0)
        external.stop(process)
        deadline = time.monotonic() + 3
        while True:
            status = subprocess.run(["ps", "-p", str(child), "-o", "stat="], capture_output=True, text=True)
            if status.returncode != 0 or status.stdout.strip().startswith("Z"):
                break
            assert time.monotonic() < deadline, "Owned child survived stop()"
            time.sleep(.02)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_producer_import_error_restores_callers_search_path(tmp_path):
    args = setup_run(tmp_path, '    return {"status":"COMPLETE"}')
    args.producer.write_text('raise RuntimeError("import failed")', encoding="utf-8")
    before = sys.path[:]
    with pytest.raises(RuntimeError, match="import failed"):
        external.load_producer(args.producer)
    assert sys.path == before
