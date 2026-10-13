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
# Set, under the lock, once application exit has begun: later pools are refused.
_EXITING = threading.Event()


@contextmanager
def tracked_process_pool(pool: Executor, cancelled: Event | None = None) -> Iterator[Executor]:
    """Register a process pool so application exit can stop its workers.

    Once exit has begun the pool is refused instead, like a native solve, so a
    pool created after ``terminate_process_pools`` cannot outlive it.
    """

    if not isinstance(pool, ProcessPoolExecutor):
        yield pool
        return
    with _LIVE_POOLS_LOCK:
        refused = _EXITING.is_set()
        if not refused:
            _LIVE_POOLS[pool] = cancelled
    if refused:
        pool.shutdown(wait=False, cancel_futures=True)
        raise SolveCancelledError("coilEM is stopping; no new solver workers are started.")
    try:
        yield pool
    finally:
        with _LIVE_POOLS_LOCK:
            _LIVE_POOLS.pop(pool, None)


def terminate_process_pools() -> None:
    """Stop every solver process pool's workers and refuse new pools, for application exit.

    Pending futures then fail with ``BrokenProcessPool``, so a solver or
    playback build waiting on them unwinds at once instead of after its
    running tasks, such as Gmsh meshes on Windows, finish.
    """

    with _LIVE_POOLS_LOCK:
        _EXITING.set()
        pools = list(_LIVE_POOLS.items())
    for pool, cancelled in pools:
        if cancelled is not None:
            cancelled.set()
        _stop_pool_workers(pool)


def _stop_pool_workers(pool: ProcessPoolExecutor) -> None:
    # submit() starts workers into this dict under the pool's shutdown lock.
    # Shutting down first refuses later submissions, so the dict then holds
    # every worker the pool will ever have, even ones a submission in flight
    # just started; shutdown() drops the pool's own references to it and to
    # the result queue.
    processes = getattr(pool, "_processes", None)
    results = getattr(pool, "_result_queue", None)
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001 - still stop the workers
        pass
    if processes is None:
        kill = getattr(pool, "kill_workers", None)  # Python 3.14+, if the layout changes
        if callable(kill):
            try:
                kill()
            except Exception:  # noqa: BLE001 - best effort at exit
                pass
        return
    for process in list(processes.values()):
        try:
            process.kill()
        except Exception:  # noqa: BLE001 - best effort at exit
            pass
    # A worker killed while sending its result, such as a large mesh, leaves
    # part of a message in the result pipe. The pool's manager thread then
    # waits in recv() for the rest while any process holds the pipe's write
    # end, and interpreter exit joins that thread. Once the workers are gone,
    # only this process does: closing it ends the read, and the manager
    # thread winds the pool down as broken.
    writer = getattr(results, "_writer", None)
    if writer is not None:
        try:
            writer.close()
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
