"""Cancellation stays valid for late spawned workers and overlapping pools (#234)."""

from __future__ import annotations

import gc
import os
import threading
import time
from contextlib import ExitStack
from multiprocessing import get_context
from pathlib import Path

import pytest

from backend.solver import _process_pool
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr


def _probe_cancellation(started: str, release: str) -> tuple[int, bool]:
    Path(started).touch()
    deadline = time.monotonic() + 20
    while not Path(release).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test worker was not released")
        time.sleep(0.01)
    try:
        _process_pool.check_process_worker_cancelled()
    except SolveCancelledError:
        return os.getpid(), True
    return os.getpid(), False


def _wait_for(paths: list[Path]) -> None:
    deadline = time.monotonic() + 20
    while not all(path.is_file() for path in paths):
        assert time.monotonic() < deadline, "spawned workers did not start"
        time.sleep(0.01)


def test_cancellation_is_visible_to_a_worker_started_after_the_signal(tmp_path):
    release = tmp_path / "release"
    started = [tmp_path / f"started-{index}" for index in range(2)]
    with _process_pool.cancellable_process_pool(2, start_method="spawn") as pool:
        try:
            first = pool.submit(_probe_cancellation, str(started[0]), str(release))
            _wait_for(started[:1])
            flag = _process_pool._LIVE_POOLS[pool]
            directory = flag.path.parent
            flag.set()
            gc.collect()
            # The first worker is still busy, so this starts a second worker
            # after cancellation, rather than reusing an idle process.
            second = pool.submit(_probe_cancellation, str(started[1]), str(release))
            _wait_for(started)
            release.touch()
            results = [future.result(timeout=20) for future in (first, second)]
            workers = list(pool._processes.values())
            assert len({pid for pid, _ in results}) == 2
            assert all(cancelled for _, cancelled in results)
            assert directory.is_dir()
        finally:
            release.touch()
    assert all(not worker.is_alive() for worker in workers)
    assert not directory.exists()


def test_overlapping_spawned_pools_keep_cancellation_separate(tmp_path):
    release = tmp_path / "release"
    workers = []
    with ExitStack() as stack:
        stack.callback(release.touch)
        pools = [stack.enter_context(_process_pool.cancellable_process_pool(2, start_method="spawn"))
                 for _ in range(3)]
        futures = [[] for _ in pools]
        started = []
        try:
            # Leave one busy worker in each pool, then start their remaining
            # workers while all three pools and their signals remain live.
            for wave in range(2):
                for index, pool in enumerate(pools):
                    marker = tmp_path / f"started-{index}-{wave}"
                    started.append(marker)
                    futures[index].append(pool.submit(_probe_cancellation, str(marker), str(release)))
                _wait_for(started)
                gc.collect()
            flags = [_process_pool._LIVE_POOLS[pool] for pool in pools]
            assert len({flag.path for flag in flags}) == 3
            # Only a string is transferred to the initializer: no Event's
            # lock, condition or semaphore handle needs duplication.
            assert all(pool._initargs == (str(flag.path),) for pool, flag in zip(pools, flags, strict=True))
            flags[0].set()
            release.touch()
            results = [[future.result(timeout=20) for future in group] for group in futures]
            assert all(cancelled for _, cancelled in results[0])
            assert not any(cancelled for group in results[1:] for _, cancelled in group)
            assert len({pid for group in results for pid, _ in group}) == 6
            workers = [worker for pool in pools for worker in pool._processes.values()]
        finally:
            release.touch()
    assert all(not worker.is_alive() for worker in workers)
    assert all(not flag.path.parent.exists() for flag in flags)


@pytest.mark.parametrize("outcome", ["normal", "cancelled", "refused"])
def test_marker_directory_is_cleaned_on_every_exit(monkeypatch, outcome):
    directories = []
    original = _process_pool.TemporaryDirectory

    def temporary_directory(**kwargs):
        directory = original(**kwargs)
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(_process_pool, "TemporaryDirectory", temporary_directory)
    latch = threading.Event()
    monkeypatch.setattr(_process_pool, "_EXITING", latch)
    if outcome == "refused":
        latch.set()

    def use_pool():
        with _process_pool.cancellable_process_pool(1, start_method="spawn"):
            if outcome == "cancelled":
                raise SolveCancelledError("cancel before submission")

    if outcome == "normal":
        use_pool()
    else:
        with pytest.raises(SolveCancelledError):
            use_pool()
    assert len(directories) == 1 and not directories[0].exists()
    assert not _process_pool._LIVE_POOLS


def test_pool_does_not_create_a_multiprocessing_event(monkeypatch):
    context = get_context("spawn")

    def event(*args, **kwargs):
        raise AssertionError("cancellation must not create an inherited Event")

    monkeypatch.setattr(context, "Event", event)
    with _process_pool.cancellable_process_pool(1, start_method="spawn") as pool:
        assert pool.submit(abs, -3).result(timeout=20) == 3


def test_marker_write_failure_still_joins_and_unregisters_workers(monkeypatch):
    def fail_to_set():
        raise OSError("synthetic marker write failure")

    with pytest.raises(OSError, match="synthetic marker write failure"):
        with _process_pool.cancellable_process_pool(1, start_method="spawn") as pool:
            assert pool.submit(abs, -3).result(timeout=20) == 3
            flag = _process_pool._LIVE_POOLS[pool]
            workers = list(pool._processes.values())
            monkeypatch.setattr(flag, "set", fail_to_set)
            raise SolveCancelledError("cancelled by the user")
    assert not _process_pool._LIVE_POOLS
    assert not flag.path.parent.exists()
    assert all(not worker.is_alive() for worker in workers)
