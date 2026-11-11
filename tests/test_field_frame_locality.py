"""File-backed frame jobs preserve numerical data across spawned workers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import backend.solver as solver
from backend.field_artifacts import read_field_line_frame_artifact
from backend.solver._process_pool import cancellable_process_pool, completed_process_futures
from backend.solver_contract import SolveCancelledError

pytestmark = pytest.mark.pr


def _report(scale: float = 1.0) -> dict:
    return {
        "config_summary": {
            "topology": "SPM", "slots": 12, "poles": 4, "stator_od_mm": 100.0,
            "rotor_od_mm": 60.0, "magnet_thickness_mm": 3.0, "stack_length_mm": 50.0,
        },
        "mesh_info": {
            "num_nodes": 4, "num_triangles": 2, "pole_pitch_deg": 90.0,
            "n_pole_pitches": 4, "total_span_deg": 360.0,
        },
        "field_plot": {
            "nodes_mm": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
            "triangles": [[0, 1, 2], [0, 2, 3]], "regions": ["stator_teeth", "stator_yoke"],
            "az_nodal": [-0.0, 0.001 * scale, -0.001 * scale, 0.0],
        },
    }


def _write_report(path: Path, report: dict) -> str:
    path.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
    return str(path)


def _without_artifact_identity(frame):
    return None if frame is None else {
        key: value for key, value in frame.items()
        if key not in ("field_frame_artifact", "full_field_frame_artifact")
    }


def _stored_frame(cache: Path):
    return read_field_line_frame_artifact(next((cache / "field_line_frames").glob("*.f32.xz")))


def _congruent_report(scale: float) -> dict:
    report = _report(scale)
    report["results"] = {
        "source_current_angle_deg": 0.0,
        "phase_current_a": [0.0, 0.0, 0.0],
        "slot_flux_linkage_contributions": [
            {
                "slot_index_global": slot,
                "phase": "ABC"[slot % 3],
                "direction": "in" if slot % 2 else "out",
                "az_reference_wb_per_m": -0.001 * scale,
                "az_avg_wb_per_m": 0.002 * scale,
                "az_effective_wb_per_m": 0.003 * scale,
                "slot_area_m2": 1.0e-4,
                "contribution_wb": (slot + 1) * 0.001 * scale,
            }
            for slot in range(12)
        ],
    }
    return report


@pytest.mark.parametrize(("live", "no_load", "capture_stator"), [
    (False, False, False), (False, True, True), (True, False, True), (True, True, True),
])
def test_spawned_report_file_job_matches_dictionary_job(monkeypatch, tmp_path, live, no_load, capture_stator):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    loaded = _report()
    noload = _report(0.75) if no_load else None
    loaded_path = _write_report(tmp_path / "loaded_report.json", loaded)
    noload_path = _write_report(tmp_path / "noload_report.json", noload) if no_load else None
    serial, parallel = (tmp_path / "solve_cache" / name for name in ("dictionary", "files"))
    expected = solver._build_field_line_frame_in_subprocess(
        3, loaded, 7.5, noload, str(serial), live, capture_stator,
    )

    with cancellable_process_pool(1, start_method="spawn") as pool:
        actual = pool.submit(
            solver._build_field_line_frame_from_report_files_in_subprocess,
            3, loaded_path, 7.5, noload_path, str(parallel), live, capture_stator,
        ).result(timeout=30)
        workers = list(pool._processes.values())

    assert all(not worker.is_alive() for worker in workers)
    assert actual[0] == expected[0] == 3
    assert actual[3] == expected[3]
    for index in (1, 2):
        assert _without_artifact_identity(actual[index]) == _without_artifact_identity(expected[index])
    actual_frame, expected_frame = _stored_frame(parallel), _stored_frame(serial)
    assert actual_frame == expected_frame
    assert actual_frame["field_line_frame"]["nodes_mm"]
    if no_load:
        assert actual_frame["field_line_frame"]["noload_plot"]["contour_levels"]
    if not capture_stator:
        assert actual[4] is expected[4] is None
    else:
        sample, reference = actual[4], expected[4]
        assert sample is not None and reference is not None
        assert sample.signature == reference.signature
        assert sample.pole_pitches == reference.pole_pitches == 4
        for name in ("corners_mm", "bx_t", "by_t", "element_index", "in_teeth"):
            np.testing.assert_array_equal(getattr(sample, name), getattr(reference, name))


@pytest.mark.parametrize("noload_file", [False, True])
def test_spawned_congruent_source_matches_parent_derived_report(monkeypatch, tmp_path, noload_file):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    congruence = (12, 1, 30.0, 60.0)
    transform = {"slot_count": 12, "n_slot_pitches": 1, "rotation_delta_deg": 30.0, "elec_delta_deg": 60.0}
    loaded, noload = _congruent_report(1.0), _congruent_report(0.75)
    derived_loaded = solver.derive_congruent_solve_report(loaded, **transform)
    derived_noload = solver.derive_congruent_solve_report(noload, **transform)
    loaded_source = solver._FieldFrameReportSource(_write_report(tmp_path / "loaded.json", loaded), congruence)
    noload_source = (
        solver._FieldFrameReportSource(_write_report(tmp_path / "noload.json", noload), congruence)
        if noload_file else derived_noload
    )
    serial, parallel = (tmp_path / "solve_cache" / name for name in ("dictionary", "files"))
    expected = solver._build_field_line_frame_in_subprocess(
        4, derived_loaded, 60.0, derived_noload, str(serial), True, True,
    )

    with cancellable_process_pool(1, start_method="spawn") as pool:
        actual = pool.submit(
            solver._build_field_line_frame_from_sources_in_subprocess,
            4, loaded_source, 60.0, noload_source, str(parallel), True, True,
        ).result(timeout=30)
        workers = list(pool._processes.values())

    assert all(not worker.is_alive() for worker in workers)
    assert actual[0] == expected[0] == 4
    assert actual[3] == expected[3]
    for index in (1, 2):
        assert _without_artifact_identity(actual[index]) == _without_artifact_identity(expected[index])
    assert _stored_frame(parallel) == _stored_frame(serial)
    assert _stored_frame(parallel)["field_line_frame"]["nodes_mm"] != loaded["field_plot"]["nodes_mm"]
    assert actual[4].signature == expected[4].signature
    for name in ("corners_mm", "bx_t", "by_t", "element_index", "in_teeth"):
        np.testing.assert_array_equal(getattr(actual[4], name), getattr(expected[4], name))


@pytest.mark.parametrize("lane", ["loaded", "noload"])
@pytest.mark.parametrize("failure", ["missing", "invalid_json", "non_object"])
def test_spawned_report_file_failure_propagates_without_publishing_a_frame(monkeypatch, tmp_path, lane, failure):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    paths = {
        "loaded": _write_report(tmp_path / "loaded_report.json", _report()),
        "noload": _write_report(tmp_path / "noload_report.json", _report(0.75)),
    }
    if failure == "missing":
        Path(paths[lane]).unlink()
        error = FileNotFoundError
    else:
        Path(paths[lane]).write_text("{" if failure == "invalid_json" else "[]", encoding="utf-8")
        error = ValueError
    output = tmp_path / "solve_cache" / "failed"

    with cancellable_process_pool(1, start_method="spawn") as pool:
        future = pool.submit(
            solver._build_field_line_frame_from_report_files_in_subprocess,
            0, paths["loaded"], 0.0, paths["noload"], str(output), True,
        )
        with pytest.raises(error):
            future.result(timeout=30)
        workers = list(pool._processes.values())

    assert all(not worker.is_alive() for worker in workers)
    assert not list(output.rglob("*.json.gz"))


def test_cancelling_report_file_jobs_joins_workers(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    loaded = _write_report(tmp_path / "loaded_report.json", _report())

    def cancel():
        raise SolveCancelledError("File-backed frame extraction cancelled")

    with pytest.raises(SolveCancelledError, match="File-backed frame extraction cancelled"):
        with cancellable_process_pool(1, start_method="spawn") as pool:
            futures = {
                pool.submit(
                    solver._build_field_line_frame_from_report_files_in_subprocess,
                    index, loaded, float(index), None, str(tmp_path / "solve_cache" / "cancelled"), False,
                ): index
                for index in range(20)
            }
            workers = list(pool._processes.values())
            list(completed_process_futures(futures, cancel))

    assert all(not worker.is_alive() for worker in workers)
    assert any(future.cancelled() for future in futures)
