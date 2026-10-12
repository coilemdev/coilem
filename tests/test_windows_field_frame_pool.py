"""Spawned field-frame extraction preserves numerical frames and cancellation."""

from __future__ import annotations

import gzip
import json

import pytest

import backend.solver as solver
from backend.solver._process_pool import cancellable_process_pool, completed_process_futures
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr


@pytest.fixture(autouse=True)
def clean_pool_switches(monkeypatch):
    for name in ("COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL",
                 "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL"):
        monkeypatch.delenv(name, raising=False)


def report(scale: float = 1.0):
    return {
        "config_summary": {"topology": "SPM", "slots": 12, "poles": 4, "stator_od_mm": 100.0,
                           "rotor_od_mm": 60.0, "magnet_thickness_mm": 3.0, "stack_length_mm": 50.0},
        "mesh_info": {"num_nodes": 4, "num_triangles": 2, "pole_pitch_deg": 90.0,
                      "n_pole_pitches": 4, "total_span_deg": 360.0},
        "field_plot": {"nodes_mm": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
                       "triangles": [[0, 1, 2], [0, 2, 3]], "regions": ["stator_teeth", "stator_yoke"],
                       "az_nodal": [0.0, 0.001 * scale, -0.001 * scale, 0.0]},
    }


def test_frame_pool_defaults_and_caps(monkeypatch):
    monkeypatch.setattr(solver.os, "cpu_count", lambda: 16)
    assert solver._field_preview_worker_count(48, 8) == 8
    assert solver._field_preview_worker_count(48, 4) == 4
    assert solver._field_preview_worker_count(1, 8) == 1
    monkeypatch.setattr(solver.os, "cpu_count", lambda: 3)
    assert solver._field_preview_worker_count(48, 8) == 3


def test_installed_frame_off_switch_keeps_other_pools(monkeypatch):
    monkeypatch.setenv("COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL", "0")
    assert solver._field_preview_worker_count(48, 8) == 1
    assert solver._gmsh_mesh_process_pool_enabled()
    assert solver._playback_process_pool_enabled()


@pytest.mark.parametrize("live", [False, True])
def test_real_frame_worker_preserves_full_artifact_live_data_and_rms(monkeypatch, tmp_path, live):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    serial = tmp_path / "solve_cache/serial"
    parallel = tmp_path / "solve_cache/parallel"
    args = (3, report(), 7.5, report(0.75))
    expected = solver._build_field_line_frame_in_subprocess(*args, str(serial), live)
    with cancellable_process_pool(2) as pool:
        actual = pool.submit(solver._build_field_line_frame_in_subprocess, *args, str(parallel), live).result(timeout=30)
        workers = list(pool._processes.values())
    assert all(not worker.is_alive() for worker in workers)
    assert actual[0] == expected[0] == 3
    assert actual[3] == expected[3]
    assert all(expected[3][bucket]["area_mm2"] > 0 for bucket in ("teeth", "yoke"))
    def stripped(value):
        return None if value is None else {
            k: v for k, v in value.items() if k not in ("field_frame_artifact", "full_field_frame_artifact")
        }

    for index in (1, 2):
        assert stripped(actual[index]) == stripped(expected[index])
    left, right = (next((cache / "field_line_frames").glob("*.json.gz")) for cache in (serial, parallel))
    with gzip.open(left, "rt", encoding="utf-8") as a, gzip.open(right, "rt", encoding="utf-8") as b:
        full_a, full_b = json.load(a), json.load(b)
    assert full_a == full_b
    assert full_a["position_index"] == 3
    assert full_a["field_line_frame"]["nodes_mm"]
    assert full_a["field_line_frame"]["noload_plot"]["contour_levels"]


def test_cancelled_frame_wait_joins_workers_before_return(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    cache = tmp_path / "solve_cache/cancelled"

    def cancel():
        raise SolveCancelledError("Frame extraction cancelled")

    workers = []
    with pytest.raises(SolveCancelledError, match="Frame extraction cancelled"):
        with cancellable_process_pool(2) as pool:
            futures = {pool.submit(solver._build_field_line_frame_in_subprocess,
                                   idx, report(), float(idx), None, str(cache), False): idx
                       for idx in range(40)}
            workers = list(pool._processes.values())
            list(completed_process_futures(futures, cancel))
    assert all(not worker.is_alive() for worker in workers)
    assert any(future.cancelled() for future in futures)
