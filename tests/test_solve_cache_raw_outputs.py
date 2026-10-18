"""A saved run's raw Magneto2D output is removed from its solve-cache folder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import field_artifacts
from backend.field_artifacts import (
    encode_solve_cache_artifact_id,
    keep_raw_solver_outputs,
    prune_raw_solver_outputs,
    solve_cache_folders,
    write_field_line_frame_artifact,
)
from backend.public_routes.solve import _store_public_result
from backend.solve_workspace import SolveWorkspace

VALID_CONFIG = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))

RAW_NAMES = (
    "sweep_input.json",
    "sweep_report.json",
    "single_report.json",
    "single_mesh.json",
    "sweep_pos000_loaded_input.json",
    "sweep_pos000_loaded_mesh.json",
    "sweep_pos000_loaded_nonlinear_diagnostics.json",
    "sweep_pos000_loaded_provenance.json",
    "sweep_pos000_loaded_report.json",
    "sweep_pos015_noload_mesh.json",
    "sweep_pos015_noload_report.json",
)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "data"))
    for name in ("COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS", "COILEM_MAGNETO2D_PERSIST_ARTIFACTS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "data"


def _solve_folder(name: str = "magneto2d-2026-10-18T01-45-10-284617Z") -> tuple[Path, dict]:
    folder = field_artifacts.solve_cache_root() / name
    folder.mkdir(parents=True)
    for raw in RAW_NAMES:
        (folder / raw).write_text("{}", encoding="utf-8")
    (folder / "notes.json").write_text("{}", encoding="utf-8")
    frame = {"nodes_mm": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], "triangles": [[0, 1, 2]], "regions": ["airgap"]}
    ref = write_field_line_frame_artifact(frame, folder, pos_idx=0, elec_angle_deg=0.0)
    playback = folder / "field_playback" / "resultant"
    playback.mkdir(parents=True)
    (playback / "frame_0000_base.webp").write_bytes(b"RIFF")
    return folder, ref


def test_raw_solver_output_is_removed_and_frames_and_playback_stay(data_root: Path) -> None:
    folder, ref = _solve_folder()

    freed = prune_raw_solver_outputs({folder})

    assert freed == 2 * len(RAW_NAMES)
    assert sorted(path.name for path in folder.iterdir()) == ["field_line_frames", "field_playback", "notes.json"]
    assert field_artifacts.resolve_solve_cache_artifact_id(ref["artifact_id"]).is_file()
    assert (folder / "field_playback" / "resultant" / "frame_0000_base.webp").is_file()


def test_only_magneto2d_folders_a_result_references_are_found(data_root: Path) -> None:
    folder, ref = _solve_folder()
    other = field_artifacts.solve_cache_root() / "armature-cache"
    other.mkdir(parents=True)
    (other / "sweep_input.json").write_text("{}", encoding="utf-8")
    result = {
        "field_line_frames": [{"field_frame_artifact": ref}],
        "other": {"artifact_id": encode_solve_cache_artifact_id(other / "sweep_input.json")},
        "saved": {"artifact_id": "run.abc"},
    }

    assert solve_cache_folders(result) == {folder.resolve()}
    # A folder outside the cache root is never touched.
    outside = data_root.parent / "magneto2d-outside"
    outside.mkdir()
    (outside / "sweep_input.json").write_text("{}", encoding="utf-8")
    assert prune_raw_solver_outputs({outside}) == 0
    assert (outside / "sweep_input.json").is_file()


@pytest.mark.parametrize(
    ("raw", "persist", "keep"),
    [(None, None, False), ("1", None, True), ("0", None, False), (None, "true", True), ("0", "1", False)],
)
def test_keeping_raw_output_follows_the_solver_settings(
    data_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str | None,
    persist: str | None,
    keep: bool,
) -> None:
    if raw is not None:
        monkeypatch.setenv("COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS", raw)
    if persist is not None:
        monkeypatch.setenv("COILEM_MAGNETO2D_PERSIST_ARTIFACTS", persist)
    assert keep_raw_solver_outputs() is keep


def _result_with_frame(ref: dict) -> dict:
    from tests.test_solve_workspace import _result

    return _result(ref["artifact_id"])


@pytest.mark.parametrize("keep_raw", [False, True])
def test_saving_a_run_prunes_its_raw_solver_output_unless_kept(
    data_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    keep_raw: bool,
) -> None:
    if keep_raw:
        monkeypatch.setenv("COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS", "1")
    folder, ref = _solve_folder()
    workspace = SolveWorkspace(data_root)
    writer = workspace.begin_run(project_name="raw output", config=VALID_CONFIG, submitted_request={"config": VALID_CONFIG})

    stored = _store_public_result(workspace, writer, _result_with_frame(ref))

    assert stored["saved_run"]["run_id"]
    left = [name for name in RAW_NAMES if (folder / name).exists()]
    assert left == (list(RAW_NAMES) if keep_raw else [])
    # The saved run kept its own copy of the frame either way.
    assert field_artifacts.resolve_solve_cache_artifact_id(ref["artifact_id"]).is_file()
