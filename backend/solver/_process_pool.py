"""Spawn-safe solver workers with cooperative cancellation of queued tasks."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ProcessPoolExecutor, wait
from contextlib import contextmanager
from multiprocessing import get_context
from multiprocessing.synchronize import Event
from typing import Any

from backend.solver_contract import SolveCancelledError

_worker_cancelled: Event | None = None

# Live solver process pools and their cooperative-cancellation events. A user's
# cancellation lets running tasks finish; application exit stops their workers,
# because the interpreter otherwise waits for those tasks before it exits (#55).
_LIVE_POOLS: dict[ProcessPoolExecutor, Event | None] = {}
_LIVE_POOLS_LOCK = threading.Lock()


@contextmanager
def tracked_process_pool(pool: Executor, cancelled: Event | None = None) -> Iterator[Executor]:
    """Register a process pool so application exit can stop its workers."""

    if not isinstance(pool, ProcessPoolExecutor):
        yield pool
        return
    with _LIVE_POOLS_LOCK:
        _LIVE_POOLS[pool] = cancelled
    try:
        yield pool
    finally:
        with _LIVE_POOLS_LOCK:
            _LIVE_POOLS.pop(pool, None)


def terminate_process_pools() -> None:
    """Stop the workers of every live solver process pool, for application exit.

    Their pending futures then fail with ``BrokenProcessPool``, so a solver or
    playback build waiting on them unwinds at once instead of after its
    running tasks, such as Gmsh meshes on Windows, finish.
    """

    with _LIVE_POOLS_LOCK:
        pools = list(_LIVE_POOLS.items())
    for pool, cancelled in pools:
        if cancelled is not None:
            cancelled.set()
        _stop_pool_workers(pool)


def _stop_pool_workers(pool: ProcessPoolExecutor) -> None:
    kill = getattr(pool, "kill_workers", None)  # Python 3.14+
    if callable(kill):
        try:
            kill()
            return
        except Exception:  # noqa: BLE001 - fall back to the workers themselves
            pass
    # Python 3.11-3.13 have no public way to stop a pool's workers.
    for process in list((getattr(pool, "_processes", None) or {}).values()):
        try:
            process.kill()
        except Exception:  # noqa: BLE001 - best effort at exit
            pass


def _initialize_worker(cancelled: Event) -> None:
    global _worker_cancelled
    _worker_cancelled = cancelled


def check_process_worker_cancelled() -> None:
    if _worker_cancelled is not None and _worker_cancelled.is_set():
        raise SolveCancelledError("Solve cancelled before returning a worker result.")


@contextmanager
def cancellable_process_pool(workers: int) -> Iterator[ProcessPoolExecutor]:
    # Windows workers start from the backend's executor thread using spawn.
    # Keep the existing process-start default on other platforms.
    context = get_context("spawn" if os.name == "nt" else None)
    cancelled = context.Event()
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(cancelled,),
    )
    # Registered until shutdown returns: application exit usually finds the
    # solver already waiting there for running tasks after its cancellation.
    with tracked_process_pool(pool, cancelled):
        try:
            yield pool
        except BaseException:
            # Python 3.11-3.13 do not expose terminate_workers(). Let running tasks
            # finish, then skip work already queued in the process pipe.
            cancelled.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)


def completed_process_futures(
    futures: dict[Future[Any], Any],
    check_cancelled: Callable[[], None] | None,
) -> Iterator[Future[Any]]:
    pending = set(futures)
    while pending:
        if check_cancelled is not None:
            check_cancelled()
        completed, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
        for future in completed:
            if check_cancelled is not None:
                check_cancelled()
            yield future
