"""Windows mesh workers preserve fields and release the pool on cancellation."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import backend.solver as solver
from backend.models import MotorConfig
from backend.solver._mesh_pool import (
    check_mesh_worker_cancelled,
    completed_mesh_futures,
    gmsh_mesh_process_pool,
)
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr


@pytest.fixture(autouse=True)
def clean_process_pool_switches(monkeypatch):
    for name in ("COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL",
                 "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL"):
        monkeypatch.delenv(name, raising=False)


def _queued_mesh_probe(started_path: str) -> None:
    """A short running task, with the same checkpoints as a real Gmsh job."""
    check_mesh_worker_cancelled()
    Path(started_path).touch()
    time.sleep(0.25)
    check_mesh_worker_cancelled()


def test_windows_mesh_and_frame_worker_counts(monkeypatch):
    monkeypatch.setattr(solver.os, "cpu_count", lambda: 16)
    assert solver._gmsh_pipeline_worker_count(
        "COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", 48, uses_process_pool=True,
    ) == 8
    assert solver._gmsh_pipeline_worker_count(
        "COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", 1, uses_process_pool=True,
    ) == 1
    assert solver._magneto2d_python_process_pool_enabled()
    assert solver._field_preview_worker_count(48, 8) == min(8, solver.os.cpu_count() or 1)


def test_mesh_pool_disable_and_worker_cap_in_development(monkeypatch):
    settings = {"COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL": "0"}
    monkeypatch.setattr(solver, "solver_setting", lambda key, default=None: settings.get(key, default))
    assert solver._gmsh_pipeline_worker_count("mesh_workers", 48, uses_process_pool=True) == 1
    settings["COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL"] = "1"
    settings["mesh_workers"] = "4"
    assert solver._gmsh_pipeline_worker_count("mesh_workers", 48, uses_process_pool=True) == 4
    assert solver._gmsh_pipeline_worker_count("mesh_workers", 2, uses_process_pool=True) == 2
    settings.pop("COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL")
    settings["COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL"] = "0"
    assert solver._gmsh_pipeline_worker_count("mesh_workers", 48, uses_process_pool=True) == 1


def test_spawned_gmsh_artifact_matches_in_process():
    pytest.importorskip("gmsh")
    config = MotorConfig.model_validate_json(
        (Path(__file__).parent / "fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"),
    )
    config.solve_params.mesh_density = "coarse"
    payload = config.model_dump(mode="json")
    expected, _, _ = solver._build_gmsh_mesh_in_subprocess(payload, 7.5)
    with gmsh_mesh_process_pool(2) as pool:
        actual, _, _ = pool.submit(solver._build_gmsh_mesh_in_subprocess, payload, 7.5).result(timeout=30)
    assert actual == expected
    # Full mesh and physics data survive the worker's serialization boundary.
    assert actual["mesh"]["triangles"]
    assert actual["physics_contract"]


def test_cancelled_pool_skips_queued_meshes_and_joins_workers(tmp_path):
    started = tmp_path / "started"
    clock_start = time.perf_counter()
    workers = []

    def cancel_after_worker_starts():
        if started.exists():
            raise SolveCancelledError("Synthetic cancellation")
        if time.perf_counter() - clock_start > 15:
            pytest.fail("Mesh worker never started")

    with pytest.raises(SolveCancelledError, match="Synthetic cancellation"):
        with gmsh_mesh_process_pool(2) as pool:
            futures = {pool.submit(_queued_mesh_probe, str(started)): i for i in range(40)}
            workers = list(pool._processes.values())
            list(completed_mesh_futures(futures, cancel_after_worker_starts))
    assert started.exists()
    assert all(not worker.is_alive() for worker in workers)
    assert sum(future.cancelled() for future in futures) > 0
    # A subsequent solve can create a new pool and return a result.
    with gmsh_mesh_process_pool(1) as replacement:
        assert replacement.submit(json.loads, '{"ready":true}').result(timeout=15) == {"ready": True}


def test_solver_passes_its_cancellation_check_to_mesh_pipeline(monkeypatch):
    instance = solver.Magneto2DSolver()
    cancelled = threading.Event()
    monkeypatch.setattr(solver, "cancel_active_magneto2d_processes", cancelled.set)
    config = MotorConfig.model_validate_json(
        (Path(__file__).parent / "fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"),
    )

    def pipeline(config, producer, *, check_cancelled, **kwargs):
        instance.cancel_active_solve()
        check_cancelled()
        pytest.fail("A cancelled pool must not return a completed report")

    monkeypatch.setattr(solver, "_solve_with_per_angle_producer_meshes", pipeline)
    with pytest.raises(SolveCancelledError):
        instance._solve_with_per_angle_gmsh_meshes(config, solve_cache_dir=None)
    assert cancelled.is_set()
