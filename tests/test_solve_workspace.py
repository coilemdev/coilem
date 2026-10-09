"""Contracts for durable local solve storage and containment."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from backend import field_artifacts
from backend.models import MotorConfig
from backend.solve_workspace import (
    RUN_ARTIFACT_PREFIX,
    RUN_MANIFEST_SCHEMA,
    SolveWorkspace,
    SolveWorkspaceCapacityError,
    SolveWorkspaceError,
    resolve_run_artifact_id,
    user_data_root,
)
from backend.solver import Magneto2DSolver, _prune_solve_cache

VALID_CONFIG = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))


def _result(artifact_id: str | None = None) -> dict:
    result = {
        "summary": {
            "avg_torque_Nm": 4.25,
            "torque_ripple_pct": 2.0,
        },
        "torque_waveform": {
            "electrical_angle_deg": [0.0, 30.0],
            "torque_Nm": [4.2, 4.3],
        },
        "back_emf_waveform": {
            "electrical_angle_deg": [0.0, 30.0],
            "phase_a_V": [0.0, 1.0],
            "phase_b_V": [-0.5, -0.5],
            "phase_c_V": [0.5, -0.5],
        },
        "solve_metadata": {
            "solver_name": "magneto2d-rust-0.3.2",
            "mesh_element_count": 1200,
            "rotor_positions": 2,
        },
    }
    if artifact_id is not None:
        result["field_line_frames"] = [
            {
                "angle_deg": 0.0,
                "field_frame_artifact": {"artifact_id": artifact_id},
            }
        ]
    return result


def test_user_data_root_honors_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured = tmp_path / "portable-data"
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(configured))

    assert user_data_root() == configured.resolve()


def test_solver_cache_lives_under_the_user_data_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "data"))

    cache_dir = Magneto2DSolver._prepare_solve_cache_dir()
    assert cache_dir is not None
    assert cache_dir.parent == (tmp_path / "data" / "solve_cache").resolve()

    artifact = field_artifacts.write_field_line_frame_artifact(
        {"angle_deg": 0.0},
        cache_dir,
        pos_idx=0,
        elec_angle_deg=0.0,
    )
    assert artifact is not None
    resolved = field_artifacts.resolve_solve_cache_artifact_id(artifact["artifact_id"])
    assert resolved.is_file()
    assert artifact["relative_path"] == resolved.relative_to(cache_dir.parent).as_posix()


def _write_cache_dir(root: Path, name: str, size: int, mtime: int) -> Path:
    cache_dir = root / name
    cache_dir.mkdir(parents=True)
    (cache_dir / "sweep_report.json").write_bytes(b"x" * size)
    os.utime(cache_dir, (mtime, mtime))
    return cache_dir


def test_solver_cache_pruning_honors_byte_budget_and_keeps_newest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "solve_cache"
    newest = _write_cache_dir(root, "magneto2d-4", 300, 4_000)
    second = _write_cache_dir(root, "magneto2d-3", 300, 3_000)
    third = _write_cache_dir(root, "magneto2d-2", 300, 2_000)
    small_oldest = _write_cache_dir(root, "magneto2d-1", 50, 1_000)
    unrelated = _write_cache_dir(root, "other-cache", 5_000, 500)

    monkeypatch.setenv("COILEM_SOLVE_CACHE_MAX_BYTES", "700")
    _prune_solve_cache(root)
    assert {path.name for path in root.iterdir()} == {
        newest.name,
        second.name,
        small_oldest.name,
        unrelated.name,
    }
    assert not third.exists()

    # The newest dir survives even when it alone exceeds the budget.
    monkeypatch.setenv("COILEM_SOLVE_CACHE_MAX_BYTES", "100")
    _prune_solve_cache(root)
    assert {path.name for path in root.iterdir()} == {newest.name, unrelated.name}


def test_solver_cache_pruning_keeps_at_most_ten_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "solve_cache"
    for index in range(12):
        _write_cache_dir(root, f"magneto2d-{index:02d}", 1, 1_000 + index)
    monkeypatch.delenv("COILEM_SOLVE_CACHE_MAX_BYTES", raising=False)

    _prune_solve_cache(root)

    assert sorted(path.name for path in root.iterdir()) == [f"magneto2d-{index:02d}" for index in range(2, 12)]


@pytest.mark.parametrize("linked_level", ["project", "solves"])
def test_begin_run_rejects_workspace_symlink_escape_without_writing_outside(
    tmp_path: Path,
    linked_level: str,
) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    workspace.root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "existing-user-file.txt"
    sentinel.write_text("preserve existing user data", encoding="utf-8")
    if linked_level == "project":
        workspace.solves_root.mkdir()
        link = workspace.solves_root / "test-project"
    else:
        link = workspace.solves_root
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable on this platform: {exc}")

    with pytest.raises(SolveWorkspaceError):
        workspace.begin_run(
            project_name="test-project",
            config=VALID_CONFIG,
            submitted_request={"config": VALID_CONFIG},
        )

    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "preserve existing user data"
    assert link.is_symlink()


@pytest.mark.parametrize("project_extension", [".coilem", ".openem"])
def test_complete_run_is_atomic_replayable_and_integrity_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_extension: str,
) -> None:
    cache_artifact = tmp_path / "cache" / "field_line_frames" / "frame.json.gz"
    cache_artifact.parent.mkdir(parents=True)
    cache_artifact.write_bytes(b"durable-field-frame")
    monkeypatch.setattr(
        "backend.solve_workspace.resolve_solve_cache_artifact_id",
        lambda _artifact_id: cache_artifact,
    )
    workspace = SolveWorkspace(tmp_path / "data")
    request = {
        "config": deepcopy(VALID_CONFIG),
        "solve_mesh_key_sha256": "a" * 64,
    }

    writer = workspace.begin_run(
        project_name=f"My Motor{project_extension}",
        config=VALID_CONFIG,
        submitted_request=request,
    )

    assert writer.partial_path.is_dir()
    assert not writer.final_path.exists()
    running = json.loads((writer.partial_path / "manifest.json").read_text(encoding="utf-8"))
    assert running["status"] == "running"

    result = _result("cache-frame")
    result["cogging_torque_waveform"] = {
        "electrical_angle_deg": [0.0, 15.0],
        "torque_Nm": [-0.1, 0.1],
    }
    location = writer.complete(result)

    assert location.path == writer.final_path
    assert location.path.is_dir()
    assert not writer.partial_path.exists()
    assert {
        "manifest.json",
        "project.coilem",
        "request.json",
        "result.json",
        "material.json",
        "report",
        "artifacts",
    } <= {path.name for path in location.path.iterdir()}
    assert (location.path / "report" / "report.pdf").is_file()
    assert (location.path / "report" / "report.csv").is_file()
    assert (location.path / "report" / "run-package.zip").is_file()

    # A fresh workspace instance is the application-restart boundary.
    loaded = SolveWorkspace(tmp_path / "data").load_run(
        location.project_slug,
        location.run_id,
    )
    assert loaded["schema_version"] == RUN_MANIFEST_SCHEMA
    assert loaded["integrity"] == {
        "valid": True,
        "binding_mismatches": [],
        "artifact_mismatches": [],
        "export_mismatches": [],
    }

    comparison = SolveWorkspace(tmp_path / "data").load_run_comparison(
        location.project_slug,
        location.run_id,
    )
    assert comparison["project_name"] == f"My Motor{project_extension}"
    assert "parity_identity" not in comparison
    assert comparison["result"]["summary"]["avg_torque_Nm"] == 4.25
    assert comparison["result"]["torque_waveform"] == {
        "electrical_angle_deg": [0.0, 30.0],
        "torque_Nm": [4.2, 4.3],
    }
    assert comparison["result"]["back_emf_waveform"]["phase_a_V"] == [0.0, 1.0]
    assert comparison["result"]["cogging_torque_waveform"] == {
        "electrical_angle_deg": [0.0, 15.0],
        "torque_Nm": [-0.1, 0.1],
    }
    assert "field_line_frames" not in comparison["result"]
    assert loaded["freshness"]["result_current"] is False
    assert loaded["freshness"]["requires_explicit_solve"] is True
    assert loaded["saved_run"]["completed_at"] == loaded["manifest"]["completed_at"]

    project = loaded["project"]
    assert project["name"] == "My Motor"
    assert location.project_slug == "my-motor"
    assert loaded["manifest"]["files"]["project"] == "project.coilem"
    assert project["openem_schema_version"] == 4
    replayed = MotorConfig.model_validate(project)
    resolved = MotorConfig.model_validate(loaded["request"]["resolved_config"])
    assert replayed.model_dump(mode="json") == resolved.model_dump(mode="json")

    retained = loaded["result"]["field_line_frames"][0]["field_frame_artifact"]
    assert retained["artifact_id"].startswith(RUN_ARTIFACT_PREFIX)
    assert retained["relative_path"].startswith("artifacts/")
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "data"))
    assert resolve_run_artifact_id(retained["artifact_id"]).read_bytes() == (b"durable-field-frame")


def test_load_run_keeps_legacy_openem_projects_replayable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    # Create an immutable run with the previous writer's filename and package.
    with monkeypatch.context() as legacy_writer:
        legacy_writer.setattr("backend.solve_workspace.PROJECT_FILE_NAME", "project.openem")
        writer = workspace.begin_run(
            project_name="Legacy motor.openem",
            config=VALID_CONFIG,
            submitted_request={"config": VALID_CONFIG},
        )
        location = writer.complete(_result())

    loaded = SolveWorkspace(tmp_path / "data").load_run(location.project_slug, location.run_id)
    assert loaded["project"]["name"] == "Legacy motor"
    assert loaded["manifest"]["files"]["project"] == "project.openem"
    assert loaded["integrity"]["valid"] is True
    assert (location.path / "project.openem").is_file()
    assert not (location.path / "project.coilem").exists()


def test_comparison_loads_pre_v4_run_without_parity_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A v3 arc run and an explicit v4 legacy replay are the same problem."""

    old_config = MotorConfig.model_validate(json.loads(
        Path("references/benchmark_configs/validation_ipm_14p_flat_buried_large.openem").read_text(encoding="utf-8")
    )).model_dump(mode="json")
    old_config["rotor"].pop("flat_buried_magnet_shape", None)
    project = {
        "openem_schema_version": 3,
        "openem_version": "0.1.3",
        "name": "legacy-flat-ipm",
        **deepcopy(old_config),
    }
    request = {
        "schema_version": "coilem.solve_request.v1",
        "submitted": {"config": deepcopy(old_config)},
        "resolved_config": deepcopy(old_config),
    }
    result = {"summary": {}, "solve_metadata": {}}
    workspace = SolveWorkspace(tmp_path / "data")
    run = workspace.solves_root / "legacy-flat-ipm" / "run-v3"
    (run / "report").mkdir(parents=True)
    (run / "material.json").write_text(
        json.dumps({"records": []}), encoding="utf-8"
    )
    (run / "report" / "summary.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    (run / "report" / "report.csv").write_text(
        "# coilem.report_csv.v1\nsection,field,sample_index,value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workspace,
        "load_run",
        lambda _project_slug, _run_id: {
            "integrity": {"valid": True},
            "saved_run": {"path": str(run)},
            "manifest": {"project_name": "legacy-flat-ipm"},
            "project": project,
            "request": request,
            "result": result,
        },
    )

    stored = workspace.load_run_comparison("legacy-flat-ipm", "run-v3")
    assert stored["project_name"] == "legacy-flat-ipm"
    assert stored["result"]["summary"] == {}
    assert "parity_identity" not in stored


def test_failed_run_remains_explicit_partial_diagnostic(tmp_path: Path) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="failure",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )

    writer.fail(error_code="SOLVE_FAILED", message="controlled failure")

    assert not writer.final_path.exists()
    assert writer.partial_path.is_dir()
    manifest = json.loads((writer.partial_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure"]["message"] == "controlled failure"
    assert workspace.list_runs() == [
        {
            "project_slug": "failure",
            "run_id": writer.run_id,
            "path": str(writer.partial_path.resolve()),
            "size_bytes": workspace.usage_bytes(),
            "status": "failed",
            "project_name": "failure",
            "started_at": manifest["started_at"],
            "completed_at": None,
        }
    ]
    with pytest.raises(FileNotFoundError):
        workspace.load_run("failure", writer.run_id)


def test_failed_partial_can_be_deleted_to_recover_workspace_capacity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    workspace = SolveWorkspace(root)
    writer = workspace.begin_run(
        project_name="recoverable",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )
    writer.fail(error_code="SOLVE_FAILED", message="controlled failure")
    used_bytes = workspace.usage_bytes()
    limited = SolveWorkspace(root, max_bytes=used_bytes)

    listed = limited.list_runs()
    assert listed[0]["size_bytes"] == used_bytes
    assert limited.storage_policy()["accepting_new_runs"] is False
    with pytest.raises(SolveWorkspaceCapacityError, match="size limit"):
        limited.begin_run(
            project_name="blocked",
            config=VALID_CONFIG,
            submitted_request={"config": VALID_CONFIG},
        )

    limited.delete_run(
        listed[0]["project_slug"],
        listed[0]["run_id"],
        confirmation=listed[0]["run_id"],
    )

    assert limited.storage_policy()["accepting_new_runs"] is True
    retry = limited.begin_run(
        project_name="retry",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )
    assert retry.partial_path.is_dir()


def test_active_partial_cannot_be_deleted_until_writer_is_closed(
    tmp_path: Path,
) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="active-run",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )

    with pytest.raises(SolveWorkspaceError, match="active solve run"):
        workspace.delete_run(
            writer.project_slug,
            writer.run_id,
            confirmation=writer.run_id,
        )
    assert writer.partial_path.is_dir()

    writer.fail(error_code="SOLVER_CANCELLED", message="cancelled", cancelled=True)
    workspace.delete_run(
        writer.project_slug,
        writer.run_id,
        confirmation=writer.run_id,
    )
    assert not writer.partial_path.exists()


def test_cancelled_run_never_appears_complete(tmp_path: Path) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="cancelled",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )

    writer.fail(
        error_code="SOLVER_CANCELLED",
        message="Solve cancelled by user.",
        cancelled=True,
    )

    manifest = json.loads((writer.partial_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "cancelled"
    assert not writer.final_path.exists()


def test_runs_never_overwrite_and_delete_requires_exact_confirmation(
    tmp_path: Path,
) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    first_writer = workspace.begin_run(
        project_name="repeat",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )
    first = first_writer.complete(_result())
    second_writer = workspace.begin_run(
        project_name="repeat",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )
    second = second_writer.complete(_result())

    assert first.run_id != second.run_id
    assert first.path.is_dir() and second.path.is_dir()

    with pytest.raises(SolveWorkspaceError, match="confirmation"):
        workspace.delete_run(
            first.project_slug,
            first.run_id,
            confirmation=second.run_id,
        )
    assert first.path.is_dir()
    workspace.delete_run(
        first.project_slug,
        first.run_id,
        confirmation=first.run_id,
    )
    assert not first.path.exists()
    assert second.path.is_dir()


@pytest.mark.parametrize(
    ("project_slug", "run_id"),
    [
        ("..", "valid"),
        ("valid", ".."),
        ("project/escape", "valid"),
        ("valid", "run/escape"),
    ],
)
def test_run_resolution_rejects_traversal(
    tmp_path: Path,
    project_slug: str,
    run_id: str,
) -> None:
    with pytest.raises(SolveWorkspaceError):
        SolveWorkspace(tmp_path / "data").resolve_run(
            project_slug,
            run_id,
            include_partial=True,
        )


def test_run_listing_ignores_symlinks_outside_root(tmp_path: Path) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    outside_run = tmp_path / "outside" / "project" / "run"
    outside_run.mkdir(parents=True)
    (outside_run / "manifest.json").write_text(
        json.dumps({"status": "complete"}),
        encoding="utf-8",
    )
    workspace.solves_root.mkdir(parents=True)
    (workspace.solves_root / "escaped").symlink_to(
        outside_run.parent,
        target_is_directory=True,
    )

    assert workspace.list_runs() == []


def test_load_reports_tampered_bound_file(tmp_path: Path) -> None:
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="tamper",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )
    location = writer.complete(_result())
    request_path = location.path / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["resolved_config"]["solve_params"]["rated_speed_rpm"] += 1
    request_path.write_text(json.dumps(request), encoding="utf-8")

    loaded = workspace.load_run(location.project_slug, location.run_id)

    assert loaded["integrity"]["valid"] is False
    assert loaded["integrity"]["binding_mismatches"] == ["resolved_request_sha256"]
    with pytest.raises(SolveWorkspaceError, match="integrity check"):
        workspace.load_run_comparison(location.project_slug, location.run_id)


def test_workspace_quota_refuses_to_publish_oversized_run(tmp_path: Path) -> None:
    workspace = SolveWorkspace(tmp_path / "data", max_bytes=1)
    writer = workspace.begin_run(
        project_name="quota",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )

    with pytest.raises(SolveWorkspaceError, match="size limit"):
        writer.complete(_result())

    assert not writer.final_path.exists()
    manifest = json.loads((writer.partial_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure"]["error_code"] == "RUN_STORAGE_LIMIT"
    assert not (writer.partial_path / "result.json").exists()
