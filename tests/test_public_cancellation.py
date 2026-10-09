"""Cancellation contracts using tiny synthetic workers, never native solves."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

import backend.solver as solver_module
from backend.models import MotorConfig
from backend.public_routes import solve as routes
from backend.solver import Magneto2DSolver
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr


@pytest.fixture
def public_config() -> MotorConfig:
    fixture = Path(__file__).parent / "fixtures" / "spm_4p12s_simple.json"
    return MotorConfig.model_validate_json(fixture.read_text(encoding="utf-8"))


@pytest.fixture
def isolated_solver(monkeypatch):
    """Keep cancellation away from any real native processes or solve caches."""
    stopped = []
    monkeypatch.setattr(solver_module, "cancel_active_magneto2d_processes", lambda: stopped.append(True))
    monkeypatch.setattr(solver_module, "_magneto2d_prepare_cache_dir", lambda: False)
    return Magneto2DSolver(launch_surface=True), stopped


def test_cancellation_persists_before_a_solve_starts(monkeypatch, public_config, isolated_solver):
    solver, stopped = isolated_solver

    def unexpected_mesh(*args, **kwargs):
        pytest.fail("A canceled solver must not start preparing meshes")

    monkeypatch.setattr(solver, "_solve_with_per_angle_gmsh_meshes", unexpected_mesh)
    solver.cancel_active_solve()
    for _ in range(2):
        with pytest.raises(SolveCancelledError):
            solver.solve(public_config)
    assert stopped


def test_cancellation_interrupts_the_next_mesh_progress_boundary(monkeypatch, public_config, isolated_solver):
    solver, stopped = isolated_solver
    seen = []

    def progress(position, total, torque_Nm, stage="torque_sweep", elec_deg=None):
        seen.append((position, stage))

    def mesh_worker(config, *, on_progress, **kwargs):
        # Producers inspect this signature to decide which optional data to emit.
        assert inspect.signature(on_progress) == inspect.signature(progress)
        on_progress(0, 2, None, "mesh")
        solver.cancel_active_solve()
        on_progress(1, 2, None, "mesh")
        pytest.fail("Cancellation must stop the producer before another native job")

    monkeypatch.setattr(solver, "_solve_with_per_angle_gmsh_meshes", mesh_worker)
    with pytest.raises(SolveCancelledError):
        solver.solve(public_config, on_progress=progress)
    assert seen == [(0, "mesh")]
    # Kill once on request, then again to catch a process racing that request.
    assert len(stopped) >= 2


def test_cancellation_interrupts_mesh_preparation_without_a_listener(monkeypatch, public_config, isolated_solver):
    solver, stopped = isolated_solver

    def mesh_worker(config, *, on_progress, **kwargs):
        # Direct API callers still need cooperative cancellation checkpoints.
        assert callable(on_progress)
        on_progress(0, 2, None, "mesh")
        solver.cancel_active_solve()
        on_progress(1, 2, None, "mesh")
        pytest.fail("A missing UI listener must not allow canceled mesh work to continue")

    monkeypatch.setattr(solver, "_solve_with_per_angle_gmsh_meshes", mesh_worker)
    with pytest.raises(SolveCancelledError):
        solver.solve(public_config)
    assert len(stopped) >= 2


def test_canceled_reports_are_not_packaged_without_a_progress_listener(monkeypatch, public_config, isolated_solver):
    solver, _ = isolated_solver

    def mesh_worker(*args, **kwargs):
        solver.cancel_active_solve()
        return {"sweep": {}}, {}

    def unexpected_packaging(*args, **kwargs):
        pytest.fail("Canceled work must never become a completed result")

    monkeypatch.setattr(solver, "_solve_with_per_angle_gmsh_meshes", mesh_worker)
    monkeypatch.setattr(solver, "build_result_from_reports", unexpected_packaging)
    monkeypatch.setattr(solver_module, "_select_magneto2d_torque_series", lambda *args: ([0.0], 0.0, "contour"))
    monkeypatch.setattr(solver_module, "_torque_in_ui_direction", lambda value, **kwargs: value)
    with pytest.raises(SolveCancelledError):
        solver.solve(public_config)


async def _eventually(predicate) -> None:
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=4)


@pytest.mark.parametrize("stream_kind", ["solve", "armature"])
@pytest.mark.parametrize("request_cancel", [False, True], ids=["disconnect", "cancel-then-disconnect"])
def test_disconnected_stream_keeps_lane_until_worker_finishes(
    monkeypatch, tmp_path, public_config, stream_kind, request_cancel,
):
    started = threading.Event()
    emit_late = threading.Event()
    emitted_late = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    cancelled = threading.Event()
    accepted_progress = []

    class TrackingQueue(asyncio.Queue):
        def put_nowait(self, item):
            accepted_progress.append(item)
            return super().put_nowait(item)

    class CleanupWorker:
        def cancel_active_solve(self):
            cancelled.set()

        def solve(self, config, *, on_progress, **kwargs):
            try:
                # Progress can reach the event loop before this thread resumes.
                # Publish readiness first so observing progress guarantees it.
                started.set()
                on_progress(1, 3, 0.25)
                if not emit_late.wait(timeout=10):
                    raise RuntimeError("Test did not permit late progress")
                on_progress(2, 3, 0.5)
                emitted_late.set()
                if not release_worker.wait(timeout=10):
                    raise RuntimeError("Test did not release worker cleanup")
                raise SolveCancelledError("Synthetic worker finished cancellation")
            finally:
                worker_finished.set()

    solver = CleanupWorker()
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "user-data"))
    monkeypatch.setattr(routes, "_ACTIVE_SOLVE", {
        "running": False, "cancelled": False, "solver": None, "run_writer": None,
    })
    monkeypatch.setattr(routes.asyncio, "Queue", TrackingQueue)
    monkeypatch.setattr(routes, "_create_public_solver", lambda *args: solver)
    monkeypatch.setattr(routes, "Magneto2DSolver", lambda **kwargs: solver)

    def armature_worker(config, *, on_progress, **kwargs):
        return solver.solve(config, on_progress=on_progress)

    monkeypatch.setattr(routes, "solve_armature_field_sweep", armature_worker)

    async def scenario():
        handler = routes.solve_stream if stream_kind == "solve" else routes.stream_public_armature_field
        response = await handler({"config": public_config.model_dump(mode="json")})
        events = response.body_iterator
        pending = None
        try:
            assert '"stage":"starting"' in await anext(events)
            assert '"position":1' in await asyncio.wait_for(anext(events), timeout=4)
            assert started.is_set()
            assert len(accepted_progress) == 1
            if request_cancel:
                assert await routes.cancel_solve() == {"status": "cancelling"}

            # Disconnect while the consumer awaits its next progress event.
            pending = asyncio.create_task(anext(events))
            await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert cancelled.is_set()
            assert not worker_finished.is_set()
            assert routes._ACTIVE_SOLVE["running"]
            assert routes._ACTIVE_SOLVE["solver"] is solver
            with pytest.raises(HTTPException) as conflict:
                routes._claim_solve(CleanupWorker())
            assert conflict.value.status_code == 409

            # The still-running thread must not accumulate unconsumed frames.
            emit_late.set()
            await _eventually(emitted_late.is_set)
            assert len(accepted_progress) == 1

            release_worker.set()
            await _eventually(lambda: not routes._ACTIVE_SOLVE["running"])
            assert worker_finished.is_set()
            assert routes._ACTIVE_SOLVE["solver"] is None
            replacement = CleanupWorker()
            routes._claim_solve(replacement)
            assert routes._ACTIVE_SOLVE["solver"] is replacement
            routes._release_solve(replacement)

            if stream_kind == "solve":
                manifests = list((tmp_path / "user-data").rglob("manifest.json"))
                assert len(manifests) == 1
                manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
                assert manifest["status"] == "cancelled"
                assert not (manifests[0].parent / "result.json").exists()
        finally:
            # Even a failed assertion must release the executor before loop shutdown.
            emit_late.set()
            release_worker.set()
            if pending is not None and not pending.done():
                pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
            await events.aclose()
            if started.is_set():
                await _eventually(worker_finished.is_set)

    asyncio.run(scenario())


@pytest.mark.parametrize("route_kind", ["solve", "armature"])
@pytest.mark.parametrize("interruption", ["request_cancel", "timeout"])
def test_direct_route_keeps_lane_until_interrupted_worker_finishes(
    monkeypatch, tmp_path, public_config, route_kind, interruption,
):
    started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    cancelled = threading.Event()

    class CleanupWorker:
        def cancel_active_solve(self):
            cancelled.set()

        def solve(self, config, **kwargs):
            try:
                started.set()
                if not release_worker.wait(timeout=10):
                    raise RuntimeError("Test did not release worker cleanup")
                raise SolveCancelledError("Synthetic worker finished cancellation")
            finally:
                worker_finished.set()

    solver = CleanupWorker()
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "user-data"))
    monkeypatch.setattr(routes, "_ACTIVE_SOLVE", {
        "running": False, "cancelled": False, "solver": None, "run_writer": None,
    })
    monkeypatch.setattr(routes, "_create_public_solver", lambda *args: solver)
    monkeypatch.setattr(routes, "Magneto2DSolver", lambda **kwargs: solver)
    monkeypatch.setattr(routes, "solve_armature_field_sweep", solver.solve)
    original_wait_for = asyncio.wait_for

    if interruption == "timeout":
        async def short_solve_timeout(awaitable, timeout):
            if timeout >= 1200:
                # Exercise real wait_for cancellation after the thread starts,
                # while retaining normal deadlines for the test's own waits.
                await _eventually(started.is_set)
                timeout = 0.01
            return await original_wait_for(awaitable, timeout)

        monkeypatch.setattr(routes.asyncio, "wait_for", short_solve_timeout)

    async def scenario():
        handler = routes.solve if route_kind == "solve" else routes.solve_public_armature_field
        pending = asyncio.create_task(handler({"config": public_config.model_dump(mode="json")}))
        try:
            await _eventually(started.is_set)
            if interruption == "request_cancel":
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                with pytest.raises(HTTPException) as timeout_error:
                    await original_wait_for(pending, timeout=4)
                assert timeout_error.value.status_code == 504
                expected_error = "SOLVE_TIMEOUT" if route_kind == "solve" else "FIELD_COMPOSITION_TIMEOUT"
                assert timeout_error.value.detail["error_code"] == expected_error

            assert cancelled.is_set()
            assert not worker_finished.is_set()
            assert routes._ACTIVE_SOLVE["running"]
            assert routes._ACTIVE_SOLVE["solver"] is solver
            with pytest.raises(HTTPException) as conflict:
                routes._claim_solve(CleanupWorker())
            assert conflict.value.status_code == 409

            if route_kind == "solve":
                manifests = list((tmp_path / "user-data").rglob("manifest.json"))
                assert len(manifests) == 1
                manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
                assert manifest["status"] == ("cancelled" if interruption == "request_cancel" else "failed")
                expected_error = "SOLVER_CANCELLED" if interruption == "request_cancel" else "SOLVE_TIMEOUT"
                assert manifest["failure"]["error_code"] == expected_error
                assert not (manifests[0].parent / "result.json").exists()

            release_worker.set()
            await _eventually(lambda: not routes._ACTIVE_SOLVE["running"])
            assert worker_finished.is_set()
            assert routes._ACTIVE_SOLVE["solver"] is None
            replacement = CleanupWorker()
            routes._claim_solve(replacement)
            routes._release_solve(replacement)
        finally:
            release_worker.set()
            if not pending.done():
                pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
            if started.is_set():
                await _eventually(worker_finished.is_set)

    asyncio.run(scenario())
