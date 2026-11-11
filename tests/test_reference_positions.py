"""Exercise checkpoint integrity and process recovery without a solver install."""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

import pytest

from tools.benchmark_suite import external_contract, positions

FAKE = '''
from contextlib import contextmanager
from pathlib import Path
import json
import time

def identity():
    return {"physics": "fixed-test-model"}

def cases():
    return {"motor": {"phase": "F", "positions": [
        {"id": "loaded-%02d" % i, "stage": "loaded", "index": i, "angle": i * 7.5, "estimated_s": .08}
        for i in range(8)]}}

def prepare(case_id):
    return {"grid": [i * 7.5 for i in range(8)]}

@contextmanager
def open_batch(case_id, directory, prepared):
    def measure(position, output):
        time.sleep(.10)
        model = output / "model.fem"
        answer = output / "model.ans"
        model.write_text(str(position["index"]))
        answer.write_text("answer-" + str(position["index"]))
        with (Path(__file__).parent / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"id": position["id"]}) + "\\n")
        return {"angle": position["angle"], "value": position["index"]}, [model, answer]
    yield measure

def assemble(case_id, points, prepared):
    assert [p["angle"] for p in points] == prepared["grid"]
    return {"positions": len(points)}
'''


@pytest.fixture
def producer(tmp_path):
    path = tmp_path / "producer.py"
    path.write_text(FAKE)
    return path


def args(producer, output, **overrides):
    return argparse.Namespace(producer=[producer], out_dir=output, selection=None, workers=1,
        batch_size=4, timeout_s=30, min_free_gib=0, resume=False, prepare_only=False,
        interrupt_after=None, **overrides)


def test_immutable_publish_refuses_overwrite_and_rejects_corruption(tmp_path):
    file = tmp_path / "receipt.json"
    positions.immutable(file, {"value": 1})
    with pytest.raises(FileExistsError):
        positions.immutable(file, {"value": 2})
    assert positions.unseal(file) == {"value": 1}
    doc = json.loads(file.read_text())
    doc["payload"]["value"] = 2
    file.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="checksum"):
        positions.unseal(file)
    assert not list(tmp_path.glob("*.pending"))


def test_interrupted_batch_resumes_only_uncommitted_positions_and_assembles(producer, tmp_path):
    output = tmp_path / "run"
    options = args(producer, output)
    options.interrupt_after = 1
    assert positions.execute(options) == 130
    receipts = list((output / "positions/motor").glob("*.json"))
    assert 1 <= len(receipts) < 8
    frozen = {p.name: p.read_bytes() for p in receipts}
    calls_path = tmp_path / "calls.jsonl"
    before_resume = calls_path.read_text().splitlines()
    options.resume, options.interrupt_after = True, None
    assert positions.execute(options) == 0
    for name, data in frozen.items():
        assert (output / "positions/motor" / name).read_bytes() == data
    calls = [json.loads(line)["id"] for line in calls_path.read_text().splitlines()]
    assert len(set(calls)) == 8
    # A killed worker can have measured/logged its next point before committing
    # its receipt. Only committed points are reusable; uncommitted attempts can
    # run again. Check the resumed work against the receipts, not all attempts.
    resumed_calls = calls[len(before_resume):]
    assert len(resumed_calls) == len(set(resumed_calls))
    assert set(resumed_calls) == {f"loaded-{i:02d}" for i in range(8)} - {p.stem for p in receipts}
    assembled = positions.unseal(output / "assembled/motor.json")
    assert assembled["full_registered_grid"] and assembled["result"]["positions"] == 8
    assert positions.execute(options) == 0
    assert [json.loads(line)["id"] for line in calls_path.read_text().splitlines()] == calls


def test_partial_pilot_never_assembles_full_reference(producer, tmp_path):
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"motor": ["loaded-00", "loaded-07"]}))
    options = args(producer, tmp_path / "run")
    options.selection = selection
    assert positions.execute(options) == 0
    completion = positions.unseal(next((options.out_dir / "completions").glob("*.json")))
    assert completion["scope"] == "NON_GATING_PILOT"
    assert completion["committed_positions"] == 2
    assert not (options.out_dir / "assembled").exists()


def test_worker_preserves_femm_installation_path_and_filters_solver_overrides(producer, tmp_path, monkeypatch):
    producer.write_text(FAKE + '''
import os
def identity():
    return {"binary_dir": os.environ.get("COILEM_FEMM_BIN")}
original_measure = open_batch
@contextmanager
def open_batch(case_id, directory, prepared):
    assert "COILEM_TEST_SOLVER_OVERRIDE" not in os.environ
    assert os.environ["COILEM_FEMM_BIN"] == "C:/custom-femm/bin"
    with original_measure(case_id, directory, prepared) as measure:
        yield measure
''')
    monkeypatch.setenv("COILEM_FEMM_BIN", "C:/custom-femm/bin")
    monkeypatch.setenv("COILEM_TEST_SOLVER_OVERRIDE", "must-not-leak")
    assert positions.execute(args(producer, tmp_path / "run")) == 0


def test_resume_rejects_changed_answer_and_changed_producer(producer, tmp_path):
    options = args(producer, tmp_path / "run")
    assert positions.execute(options) == 0
    receipt = positions.unseal(options.out_dir / "positions/motor/loaded-00.json")
    artifact = positions.contained(options.out_dir, receipt["artifacts"][0]["path"])
    original = artifact.read_bytes()
    artifact.write_bytes(b"changed")
    options.resume = True
    with pytest.raises(ValueError, match="artifact changed"):
        positions.execute(options)
    artifact.write_bytes(original)
    producer.write_text(FAKE + "\n# changed execution\n")
    with pytest.raises(ValueError, match="identical sources"):
        positions.execute(options)


def test_advisory_failure_does_not_cancel_workers_or_receipts(producer, tmp_path, monkeypatch):
    def fail(*a, **k):
        raise PermissionError("observer holds status file")
    monkeypatch.setattr(positions, "write", fail)
    options = args(producer, tmp_path / "run")
    options.workers = 2
    assert positions.execute(options) == 0
    assert len(list((options.out_dir / "positions/motor").glob("*.json"))) == 8
    assert positions.unseal(options.out_dir / "assembled/motor.json")["status"] == "COMPLETE"


def test_replace_retries_windows_sharing_errors_only(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_text("data")
    original = Path.replace
    attempts = []
    def replace(self, target):
        attempts.append(1)
        if len(attempts) < 3:
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        return original(self, target)
    monkeypatch.setattr(Path, "replace", replace)
    external_contract.replace_with_retry(source, destination)
    assert destination.read_text() == "data" and len(attempts) == 3
    error = PermissionError("real permission failure")
    error.winerror = 1314
    def denied(self, target):
        raise error
    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        external_contract.replace_with_retry(source, destination)


def test_containment_and_registration_reject_ambiguous_work(producer, tmp_path):
    with pytest.raises(ValueError, match="escaped"):
        positions.contained(tmp_path, "../outside")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"motor": ["loaded-00", "loaded-00"]}))
    with pytest.raises(ValueError, match="duplicate or unknown"):
        positions.registration([producer], selection)


def test_bounded_retry_succeeds_after_real_windows_reader_releases(tmp_path):
    if __import__("os").name != "nt":
        pytest.skip("Windows sharing semantics")
    import ctypes
    from ctypes import wintypes
    file = tmp_path / "status.json"
    file.write_text("old")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(file), 0x80000000, 1, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    released = threading.Event()
    def release():
        time.sleep(.15)
        kernel.CloseHandle(handle)
        released.set()
    thread = threading.Thread(target=release)
    thread.start()
    try:
        external_contract.write(file, {"new": True})
        assert json.loads(file.read_text()) == {"new": True}
        assert released.is_set()
    finally:
        thread.join()
