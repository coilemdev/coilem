"""Windows playback processes preserve images without enabling field workers."""
from __future__ import annotations

import gzip
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pytest
from PIL import Image

import backend.solver as solver
from backend import public_field_playback as playback
from backend.field_artifacts import encode_solve_cache_artifact_id

pytestmark = pytest.mark.pr


@pytest.fixture(autouse=True)
def clean_process_pool_switches(monkeypatch):
    for name in ("COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL",
                 "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL", "COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL"):
        monkeypatch.delenv(name, raising=False)


def test_windows_playback_and_field_frame_pools_are_enabled(monkeypatch):
    assert solver._playback_process_pool_enabled()
    assert solver._magneto2d_python_process_pool_enabled()
    assert solver._field_preview_worker_count(48, 8) == min(8, solver.os.cpu_count() or 1)


def test_playback_uses_threads_for_small_sweeps_and_caps_large_pool(monkeypatch):
    monkeypatch.setattr(playback.os, "cpu_count", lambda: 2)
    with playback._playback_executor(7) as small:
        assert isinstance(small, ThreadPoolExecutor)
    with playback._playback_executor(48) as large:
        assert isinstance(large, ProcessPoolExecutor)
        assert large._max_workers == 2


def test_playback_pool_controls_in_development(monkeypatch):
    settings = {"COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL": "0"}
    monkeypatch.setattr(solver, "solver_setting", lambda key, default=None: settings.get(key, default))
    assert not solver._playback_process_pool_enabled()
    settings["COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL"] = "1"
    assert solver._playback_process_pool_enabled()
    settings["COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL"] = "0"
    with playback._playback_executor(48) as disabled:
        assert isinstance(disabled, ThreadPoolExecutor)


def test_playback_worker_preserves_decoded_layers_and_joins(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(playback.os, "cpu_count", lambda: 2)
    cache = tmp_path / "solve_cache/magneto2d-test"
    source = cache / "field_line_frames/frame_000.json.gz"
    source.parent.mkdir(parents=True)
    plot = {
        "angle_deg": 7.5,
        "nodes_mm": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
        "triangles": [[0, 1, 2], [0, 2, 3]],
        "regions": ["steel", "steel"],
        "element_b_mag_t": [0.5, 1.2],
        "contour_levels": [{"level": 0.1, "segments_mm": [[-0.8, 0.0, 0.8, 0.0]],
                            "segment_b_mag_t": [0.5], "segment_bx_t": [0.5], "segment_by_t": [0.0]}],
        "az_min": -0.1, "az_max": 0.1, "n_pole_pitches": 2, "total_span_deg": 360.0,
    }
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        json.dump({"field_line_frame": {**plot, "noload_plot": plot}}, handle)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    parent_dir, worker_dir = cache / "parent", cache / "worker"
    parent_dir.mkdir()
    worker_dir.mkdir()
    args = (0, encode_solve_cache_artifact_id(source), str(cache))
    expected_path, expected = playback._package_playback_frame(*args, str(parent_dir), "resultant_pm", 7.5)
    with playback._playback_executor(8) as pool:
        actual_path, actual = pool.submit(
            playback._package_playback_frame, *args, str(worker_dir), "resultant_pm", 7.5,
        ).result(timeout=30)
        workers = list(pool._processes.values())
    assert all(not worker.is_alive() for worker in workers)
    assert actual_path == expected_path == str(source)
    assert actual["index"] == expected["index"] and actual["coordinate"] == expected["coordinate"]
    assert actual["compositions"].keys() == expected["compositions"].keys()
    images = [p for p in parent_dir.iterdir() if p.suffix in (".png", ".webp")]
    assert len(images) == 6
    for left in images:
        with Image.open(left) as a, Image.open(worker_dir / left.name) as b:
            aa, bb = a.convert("RGBA"), b.convert("RGBA")
            assert aa.size == bb.size and aa.tobytes() == bb.tobytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
