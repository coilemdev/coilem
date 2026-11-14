"""Every solve records where its time goes, across its processes, and stores the breakdown."""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from backend import field_artifacts, solve_profile


def _worker_stage() -> None:
    with solve_profile.span("mesh worker: build base mesh"):
        time.sleep(0.02)
    solve_profile.mark("mesh group ready")


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(solve_profile, "_handle", None)
    monkeypatch.setattr(solve_profile, "_started_at", None)
    return tmp_path


def test_nothing_is_recorded_when_profiling_is_turned_off(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COILEM_SOLVE_PROFILE", "0")
    solve_profile.begin()
    with solve_profile.span("solve: write input and mesh files"):
        pass
    solve_profile.record("solver: linear solves", 1.0)
    solve_profile.mark("solve started")
    assert solve_profile.finish(data_root / "out") is None
    assert not (field_artifacts.solve_cache_root() / ".solve-profile-spool").exists()
    assert not (data_root / "out").exists()


def test_a_solve_collects_the_stages_of_every_process(data_root: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("COILEM_SOLVE_PROFILE", "1")
    spool = field_artifacts.solve_cache_root() / ".solve-profile-spool"
    spool.mkdir(parents=True)
    # Records of an earlier solve, from a worker that has since exited, are not this solve's.
    stale = spool / "999999.jsonl"
    stale.write_text(json.dumps({"t": time.time() - 3600, "stage": "old", "s": 9.0}) + "\n", encoding="utf-8")
    os.utime(stale, (time.time() - 3600, time.time() - 3600))

    solve_profile.begin()
    solve_profile.record("solver: linear solves", 0.25, iterations=10)
    solve_profile.record("solver: linear solves", 0.75, iterations=12)
    solve_profile.mark("solve started")
    worker = multiprocessing.get_context("spawn").Process(target=_worker_stage)
    worker.start()
    worker.join(30)
    assert worker.exitcode == 0
    out = data_root / "cache" / "magneto2d-test"
    summary = solve_profile.finish(out)

    assert summary is not None and summary["schema"] == "coilem.solve_profile/v1"
    stages = {row["stage"]: row for row in summary["stages"]}
    assert "old" not in stages and not stale.exists()
    assert stages["solver: linear solves"]["count"] == 2
    assert stages["solver: linear solves"]["total_s"] == pytest.approx(1.0)
    assert stages["solver: linear solves"]["max_s"] == pytest.approx(0.75)
    mesh = stages["mesh worker: build base mesh"]
    assert mesh["count"] == 1 and mesh["total_s"] >= 0.02 and mesh["processes"] == 1
    assert set(summary["timeline"]) == {"solve started", "mesh group ready"}
    assert json.loads((out / "solve_profile.json").read_text(encoding="utf-8")) == summary
    logged = capsys.readouterr().err
    assert "solve profile:" in logged and "mesh worker: build base mesh" in logged
    # The next solve starts from nothing.
    assert solve_profile.finish(out) is None


def test_a_failing_spool_never_breaks_the_solve(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COILEM_SOLVE_PROFILE", "1")

    def refuse() -> Path:
        raise OSError("no spool")

    monkeypatch.setattr(solve_profile, "_spool_dir", refuse)
    solve_profile.begin()
    with solve_profile.span("mesh: Gmsh generates the mesh"):
        pass
    solve_profile.mark("solve started")
    summary = solve_profile.finish(None)
    assert summary is not None and summary["stages"] == []


def test_recording_is_on_by_default_and_only_the_verbose_mode_logs_and_writes_a_file(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("COILEM_SOLVE_PROFILE", raising=False)
    solve_profile.begin()
    solve_profile.record("solver: linear solves", 0.5)
    summary = solve_profile.finish(data_root / "out")
    assert summary is not None and summary["stages"][0]["stage"] == "solver: linear solves"
    assert capsys.readouterr().err == ""
    assert not (data_root / "out").exists()


def test_completed_profiles_can_be_archived_and_recorded_again(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.benchmark_archive import archive_runtime

    monkeypatch.delenv("COILEM_SOLVE_PROFILE", raising=False)
    for index in range(2):
        runtime = data_root / "runtime"
        monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(runtime))
        solve_profile.begin()
        solve_profile.record("solver: linear solves", 0.25)
        handle = solve_profile._handle
        worker = multiprocessing.get_context("spawn").Process(target=_worker_stage)
        worker.start()
        worker.join(30)
        assert worker.exitcode == 0
        summary = solve_profile.finish(None)
        assert handle.closed
        assert {row["stage"] for row in summary["stages"]} == {"solver: linear solves", "mesh worker: build base mesh"}
        receipt = archive_runtime(runtime, data_root / f"runtime-{index}.tar.gz")
        assert not runtime.exists()
        assert len([name for name in receipt["files"] if name.endswith(".jsonl")]) == 2


@pytest.mark.parametrize("failure", ["collection", "disabled"])
def test_finishing_releases_the_profile_even_without_a_summary(data_root: Path, monkeypatch: pytest.MonkeyPatch, failure) -> None:
    monkeypatch.delenv("COILEM_SOLVE_PROFILE", raising=False)
    solve_profile.begin()
    solve_profile.record("solver: linear solves", 0.25)
    handle = solve_profile._handle
    if failure == "disabled":
        monkeypatch.setenv("COILEM_SOLVE_PROFILE", "0")
    else:
        def refuse(*args):
            raise OSError("collection failed")

        monkeypatch.setattr(solve_profile, "_collect", refuse)
    assert solve_profile.finish(None) is None
    assert handle.closed


def _summary() -> dict:
    now = 1_000.0
    entries = [
        {"t": now + 16.0, "event": "mesh group ready"},
        {"t": now + 80.0, "event": "mesh group ready"},
        {"t": now + 20.0, "event": "solve finished"},
        {"t": now + 130.0, "event": "solve finished"},
        {"t": now + 150.0, "event": "frame finished"},
        {"t": now + 15.0, "stage": "mesh: Gmsh generates the mesh", "s": 12.0, "pid": "1"},
        {"t": now + 79.0, "stage": "mesh: Gmsh generates the mesh", "s": 14.0, "pid": "2"},
        {"t": now + 16.0, "stage": "mesh worker: build base mesh", "s": 14.0, "pid": "1"},
        {"t": now + 80.0, "stage": "mesh worker: build base mesh", "s": 16.0, "pid": "2"},
        {"t": now + 16.0, "stage": "mesh worker: one group, total", "s": 15.0, "pid": "1"},
        {"t": now + 80.0, "stage": "mesh worker: one group, total", "s": 17.0, "pid": "2"},
        {"t": now + 130.0, "stage": "solve (loaded): one position, total", "s": 9.0, "pid": "0"},
        {"t": now + 130.0, "stage": "solver: linear solves", "s": 2.0, "pid": "0"},
        {"t": now + 150.0, "stage": "frame worker: encode and write frame", "s": 2.0, "pid": "3"},
        {"t": now + 99.0, "stage": "a stage this version does not list", "s": 1.0, "pid": "0"},
    ]
    return solve_profile.summarize(entries, now, now + 160.0)


def test_breakdown_cuts_the_elapsed_time_at_the_last_mesh_and_the_last_solve() -> None:
    breakdown = solve_profile.breakdown(_summary())

    assert breakdown["schema_version"] == "coilem.solve_time_breakdown.v1"
    assert breakdown["elapsed_s"] == 160.0
    cuts = {step["key"]: step["seconds"] for step in breakdown["elapsed_steps"]}
    assert cuts == {"meshing": 80.0, "field_solve": 50.0, "packaging": 30.0}
    assert sum(cuts.values()) == breakdown["elapsed_s"]
    assert breakdown["counts"] == {"meshes_built": 2, "meshes_rotated": 0, "solves": 2, "field_frames": 1}
    steps = {step["key"]: step for step in breakdown["steps"]}
    assert list(steps) == ["meshing", "field_solve", "packaging"]
    meshing = steps["meshing"]
    # The step's work is its workers' own total, not the sum of nested rows.
    assert meshing["work_s"] == 32.0
    assert [(part["label"], part["indent"], part["count"], part["total_s"]) for part in meshing["parts"]] == [
        ("Build a mesh", 0, 2, 30.0),
        ("Gmsh generates the mesh", 1, 2, 26.0),
    ]
    assert meshing["parts"][1]["max_s"] == 14.0
    assert steps["packaging"]["work_s"] == 2.0
    # A run with no recorded stages has nothing to show.
    assert solve_profile.breakdown(None) is None
    assert solve_profile.breakdown({"stages": [], "elapsed_s": 1.0}) is None


def test_report_rows_read_like_the_results_card() -> None:
    summary, steps = solve_profile.report_rows(solve_profile.breakdown(_summary()))

    assert summary == [
        ("Elapsed", "160 s"),
        ("Meshing", "80.0 s (50%), until the last mesh was ready"),
        ("Field solve", "50.0 s (31%), from then until the last position was solved"),
        ("Packaging results", "30.0 s (19%), field frames and the result, after the last solve"),
        ("Meshes", "2 generated"),
        ("Field solves", "2"),
        ("Field frames", "1"),
    ]
    assert steps[0] == (
        "Meshing: 32.0 s of work across workers",
        [
            ("Build a mesh", "30.0 s in total; run 2 times, 15.0 s each on average, slowest 16.0 s"),
            ("– Gmsh generates the mesh", "26.0 s in total; run 2 times, 13.0 s each on average, slowest 14.0 s"),
        ],
    )
    assert solve_profile.report_rows(None) == ([], [])
    assert solve_profile.report_rows({"schema_version": "something else"}) == ([], [])
