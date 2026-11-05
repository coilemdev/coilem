"""Windows sharing contention and failure cleanup for local solve progress."""
import ctypes
import errno
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.experimental import outrunner_runtime as runtime
from backend.experimental import outrunner_storage as storage
from backend.experimental.outrunner_project import OutrunnerProject, OutrunnerRunRequest


def test_transient_replace_retries_without_truncating_committed_state(tmp_path, monkeypatch):
    path = tmp_path/"state.json"
    storage.write_json(path, {"completed": 1})
    replace = storage.os.replace
    attempts = []
    def contended(temporary, destination):
        attempts.append(Path(temporary))
        assert storage.read_json(path) == {"completed": 1}
        if len(attempts) < 4:
            raise PermissionError(errno.EACCES, "Windows reader holds the destination")
        replace(temporary, destination)
    monkeypatch.setattr(storage.os, "replace", contended)
    monkeypatch.setattr(storage.time, "sleep", lambda _: None)
    storage.write_json(path, {"completed": 2})
    assert len(attempts) == 4
    assert storage.read_json(path) == {"completed": 2}
    assert not list(tmp_path.glob("*.tmp"))


def test_permanent_permission_failure_is_bounded_preserves_state_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path/"state.json"
    storage.write_json(path, {"completed": 1})
    attempts = []
    def denied(*_):
        attempts.append(1)
        raise PermissionError(errno.EACCES, "Permanent access denial")
    monkeypatch.setattr(storage.os, "replace", denied)
    monkeypatch.setattr(storage.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError, match="Permanent access denial"):
        storage.write_json(path, {"completed": 2})
    assert len(attempts) == storage._REPLACE_ATTEMPTS
    assert storage.read_json(path) == {"completed": 1}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Uses a real Windows file handle without FILE_SHARE_DELETE")
def test_actual_windows_reader_lock_is_retried_until_reader_closes(tmp_path, monkeypatch):
    from ctypes import wintypes

    path = tmp_path/"state.json"
    storage.write_json(path, {"completed": 1})
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, OPEN_EXISTING.
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.WinError(ctypes.get_last_error())
    blocked, closed = threading.Event(), threading.Event()
    replace = storage.os.replace
    attempts = []
    def observed(temporary, destination):
        attempts.append(1)
        try:
            replace(temporary, destination)
        except PermissionError:
            blocked.set()
            raise
    monkeypatch.setattr(storage.os, "replace", observed)
    def release_reader():
        try:
            blocked.wait(3)
        finally:
            kernel.CloseHandle(handle)
            closed.set()
    reader = threading.Thread(target=release_reader)
    reader.start()
    try:
        runtime._write(path, {"completed": 2})
    finally:
        blocked.set()
        reader.join(timeout=4)
    assert closed.is_set()
    assert len(attempts) >= 2, "Must exercise a real failed Windows replacement"
    assert storage.read_json(path) == {"completed": 2}


def test_simultaneous_pollers_and_writers_always_observe_complete_json(tmp_path):
    path = tmp_path/"state.json"
    storage.write_json(path, {"completed": 0, "rows": [0]*1000})
    barrier = threading.Barrier(7)
    def writer(offset):
        barrier.wait()
        for index in range(offset, offset+40):
            storage.write_json(path, {"completed": index, "rows": [index]*1000})
    def reader():
        barrier.wait()
        for _ in range(150):
            state = storage.read_json(path)
            assert state["rows"] == [state["completed"]]*1000
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = [pool.submit(writer, offset) for offset in [1, 101]]+[pool.submit(reader) for _ in range(5)]
        for future in futures:
            future.result(timeout=20)
    assert not list(tmp_path.glob("*.tmp"))


def test_initial_and_terminal_save_failures_always_release_active_job(tmp_path, monkeypatch):
    run_id = "a"*32
    (tmp_path/run_id).mkdir()
    active = {run_id: threading.Event()}
    monkeypatch.setattr(runtime, "_root", lambda: tmp_path)
    monkeypatch.setattr(runtime, "_ACTIVE", active)
    monkeypatch.setattr(runtime, "estimate", lambda _: {})
    def denied(*_):
        raise PermissionError("Cannot save state")
    monkeypatch.setattr(runtime, "_write", denied)
    with pytest.raises(PermissionError, match="Cannot save state"):
        runtime._worker(run_id, OutrunnerRunRequest(project=OutrunnerProject()), active[run_id])
    assert not active


def test_queue_save_failure_does_not_register_an_active_job(tmp_path, monkeypatch):
    active = {}
    monkeypatch.setattr(runtime, "_root", lambda: tmp_path)
    monkeypatch.setattr(runtime, "_ACTIVE", active)
    write = runtime._write
    def denied(path, payload):
        if path.name == "state.json":
            raise PermissionError("Cannot queue state")
        write(path, payload)
    monkeypatch.setattr(runtime, "_write", denied)
    with pytest.raises(PermissionError, match="Cannot queue state"):
        runtime.start(OutrunnerRunRequest(project=OutrunnerProject()))
    assert not active
