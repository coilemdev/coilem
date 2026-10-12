"""Spawn-safe solver workers with cooperative cancellation of queued tasks."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from contextlib import contextmanager
from multiprocessing import get_context
from multiprocessing.synchronize import Event
from typing import Any

from backend.solver_contract import SolveCancelledError

_worker_cancelled: Event | None = None


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
