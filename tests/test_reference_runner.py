"""Exercise real process overlap, immutable resume and failure/cancellation boundaries."""
import subprocess
import sys
from argparse import Namespace
from datetime import datetime

import pytest

from tools.benchmark_suite.contract import ROOT, read, run_lock, sha
from tools.benchmark_suite.contract import write as write_json
from tools.benchmark_suite.external import execute, identity, load_producer, safe_id, stop, worker


def producer(tmp_path, *, duration=0.8, fail=False):
    path = tmp_path / "producer.py"
    path.write_text(
        'import time\n'
        'def identity(): return {"physical_source": "fixed"}\n'
        'def cases(): return {"a": "A", "b": "D"}\n'
        f'def measure(case, directory):\n    time.sleep({duration!r})\n'
        + ('    raise RuntimeError("injected producer failure")\n' if fail else
           '    return {"status": "COMPLETE", "case": case, "directory": str(directory), "waveform": [1, 2, 3]}\n'),
        encoding="utf-8",
    )
    return path


def arguments(path, output, **kwargs):
    return Namespace(producer=path, out_dir=output, workers=2, case=None, timeout_s=10, timings=None, resume=False, **kwargs)


def test_real_workers_overlap_and_resume_preserves_results(tmp_path):
    args = arguments(producer(tmp_path), tmp_path / "run")
    assert execute(args) == 0
    manifest = read(args.out_dir / "run_manifest.json")
    assert manifest["status"] == "COMPLETE"
    assert [job["case_id"] for job in manifest["jobs"]] == ["a", "b"]
    results = [read(args.out_dir / job["result"]) for job in manifest["jobs"]]
    assert max(datetime.fromisoformat(result["started_at"]) for result in results) < min(
        datetime.fromisoformat(result["completed_at"]) for result in results
    )
    assert len({result["measurement"]["directory"] for result in results}) == 2
    assert all(result["measurement"]["waveform"] == [1, 2, 3] for result in results)
    before = [job["result_sha256"] for job in manifest["jobs"]]
    args.resume, args.workers = True, 1
    assert execute(args) == 0
    assert before == [job["result_sha256"] for job in read(args.out_dir / "run_manifest.json")["jobs"]]
    assert [session["workers"] for session in read(args.out_dir / "run_manifest.json")["execution_sessions"]] == [2, 1]


@pytest.mark.parametrize("change", ["producer", "request", "result", "selection"])
def test_resume_rejects_changed_sources_selection_and_evidence(tmp_path, change):
    args = arguments(producer(tmp_path, duration=0), tmp_path / "run")
    assert execute(args) == 0
    manifest_path = args.out_dir / "run_manifest.json"
    manifest_sha = sha(manifest_path)
    first = read(manifest_path)["jobs"][0]
    if change == "producer":
        args.producer.write_text(args.producer.read_text() + "\n# changed source\n", encoding="utf-8")
    elif change == "selection":
        args.case = ["a"]
    else:
        path = args.out_dir / first[change]
        path.write_text(path.read_text() + "\n", encoding="utf-8")
    args.resume = True
    with pytest.raises(ValueError, match="changed|refused"):
        execute(args)
    assert sha(manifest_path) == manifest_sha


def test_live_worker_lock_refuses_resume_without_manifest_edits(tmp_path):
    args = arguments(producer(tmp_path, duration=0), tmp_path / "run")
    assert execute(args) == 0
    manifest_path = args.out_dir / "run_manifest.json"
    before = sha(manifest_path)
    first = read(manifest_path)["jobs"][0]
    args.resume = True
    with run_lock((args.out_dir / first["result"]).parent):
        with pytest.raises(ValueError, match="already owns"):
            execute(args)
    assert sha(manifest_path) == before


def test_producer_failure_is_visible_and_other_process_survives(tmp_path):
    args = arguments(producer(tmp_path, duration=0.1, fail=True), tmp_path / "run")
    independent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=ROOT)
    try:
        with pytest.raises(ValueError, match="Reference job failed"):
            execute(args)
        assert independent.poll() is None
        manifest = read(args.out_dir / "run_manifest.json")
        assert manifest["status"] == "INTERRUPTED"
        assert any(job["status"] == "ERROR" for job in manifest["jobs"])
        failed = next(job for job in manifest["jobs"] if job["status"] == "ERROR")
        assert read(args.out_dir / failed["result"])["status"] == "ERROR"
    finally:
        stop(independent)


def test_timeout_joins_owned_worker_and_releases_job_lock(tmp_path):
    args = arguments(producer(tmp_path, duration=30), tmp_path / "run")
    args.timeout_s, args.workers = 0.3, 1
    with pytest.raises(ValueError, match="timed out"):
        execute(args)
    job = read(args.out_dir / "run_manifest.json")["jobs"][0]
    with run_lock((args.out_dir / job["result"]).parent):
        pass


def test_worker_rejects_changed_producer_identity_before_measurement(tmp_path):
    args = arguments(producer(tmp_path, duration=0), tmp_path / "run")
    assert execute(args) == 0
    first = read(args.out_dir / "run_manifest.json")["jobs"][0]
    request_path = args.out_dir / first["request"]
    args.producer.write_text(args.producer.read_text() + "\n# changed source\n", encoding="utf-8")
    result_path = tmp_path / "new-worker/result.json"
    assert worker(request_path, result_path) == 2
    assert "changed before" in read(result_path)["error"]


def test_source_change_during_measurement_is_not_accepted(tmp_path):
    path = producer(tmp_path, duration=0)
    path.write_text(path.read_text().replace(
        '    time.sleep(0)',
        '    from pathlib import Path\n    p = Path(__file__)\n    p.write_text(p.read_text() + "\\n# changed during solve\\n")',
    ), encoding="utf-8")
    request = tmp_path / "request.json"
    write_json(request, {"case_id": "a", "producer_path": str(path), "identity": identity(load_producer(path), path)})
    result = tmp_path / "job/result.json"
    assert worker(request, result) == 2
    assert "changed during" in read(result)["error"]


@pytest.mark.parametrize("change", ["coverage", "path", "phase"])
def test_registered_job_structure_is_checked_on_resume(tmp_path, change):
    args = arguments(producer(tmp_path, duration=0), tmp_path / "run")
    assert execute(args) == 0
    path = args.out_dir / "run_manifest.json"
    manifest = read(path)
    if change == "coverage":
        manifest["jobs"].pop()
    elif change == "path":
        manifest["jobs"][0]["result"] = "../outside.json"
    else:
        manifest["jobs"][0]["phase"] = "B"
    write_json(path, manifest)
    args.resume = True
    with pytest.raises(ValueError, match="Registered reference job"):
        execute(args)


def test_longest_first_changes_launch_order_without_changing_registered_order(tmp_path):
    args = arguments(producer(tmp_path, duration=0), tmp_path / "run")
    args.workers = 1
    args.timings = tmp_path / "timings.json"
    write_json(args.timings, {"jobs": [{"case_id": "a", "runtime_s": 1}, {"case_id": "b", "runtime_s": 9}]})
    assert execute(args) == 0
    manifest = read(args.out_dir / "run_manifest.json")
    assert [job["case_id"] for job in manifest["jobs"]] == ["a", "b"]
    assert manifest["execution_sessions"][0]["launch_order"] == ["b", "a"]
    assert manifest["execution_sessions"][0]["timings_sha256"] == sha(args.timings)


def test_producer_can_use_sibling_imports_and_annotated_dataclasses(tmp_path):
    (tmp_path / "producer_helper_112.py").write_text('VERSION = "fixed"\n', encoding="utf-8")
    path = tmp_path / "producer.py"
    path.write_text(
        'from __future__ import annotations\n'
        'from dataclasses import dataclass\n'
        'from producer_helper_112 import VERSION\n'
        '@dataclass\nclass Metadata:\n    version: str = VERSION\n'
        'def identity(): return {"version": Metadata().version}\n'
        'def cases(): return {"a": "A"}\n'
        'def measure(case, directory): return {"status": "COMPLETE", "version": Metadata().version}\n',
        encoding="utf-8",
    )
    args = arguments(path, tmp_path / "run")
    assert execute(args) == 0
    first = read(args.out_dir / "run_manifest.json")["jobs"][0]
    assert read(args.out_dir / first["result"])["measurement"]["version"] == "fixed"


@pytest.mark.parametrize("case_id", ["../escape", "NUL", "con.txt", "trailing.", "a/b", "a\\b", ""])
def test_unsafe_case_names_are_rejected(case_id):
    with pytest.raises(ValueError, match="case id"):
        safe_id(case_id)
