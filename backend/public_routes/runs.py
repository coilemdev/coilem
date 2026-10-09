"""Safe local run-management routes for the public application."""

from __future__ import annotations

import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from backend.solve_workspace import (
    RUN_MANIFEST_SCHEMA,
    SolveWorkspace,
    SolveWorkspaceError,
)

router = APIRouter()


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error_code": "RUN_NOT_FOUND",
            "message": str(exc),
        },
    )


def _invalid(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error_code": "INVALID_RUN_REQUEST",
            "message": str(exc),
        },
    )


def _export_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "RUN_EXPORT_UNAVAILABLE",
            "message": str(exc),
        },
    )


def _run_export(
    project_slug: str,
    run_id: str,
    export_name: str,
    *,
    extension: str,
    media_type: str,
) -> FileResponse:
    try:
        export = SolveWorkspace().resolve_export(
            project_slug,
            run_id,
            export_name,
        )
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _export_unavailable(exc) from exc
    return FileResponse(
        export,
        media_type=media_type,
        filename=f"coilem-{project_slug}-{run_id}.{extension}",
    )


@router.get("/runs", tags=["runs"])
async def list_runs() -> dict[str, Any]:
    """List completed runs and explicitly marked partial diagnostics."""

    workspace = SolveWorkspace()
    return {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "storage": workspace.storage_policy(),
        "runs": workspace.list_runs(include_partial=True),
    }


@router.get("/runs/{project_slug}/{run_id}", tags=["runs"])
async def load_run(project_slug: str, run_id: str) -> dict[str, Any]:
    """Load an immutable run for inspection or input-only replay."""

    try:
        return SolveWorkspace().load_run(project_slug, run_id)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _invalid(exc) from exc


@router.get("/runs/{project_slug}/{run_id}/comparison", tags=["runs"])
async def load_run_comparison(project_slug: str, run_id: str) -> dict[str, Any]:
    """Load only the small stored result subset needed for two-run comparison."""

    try:
        return SolveWorkspace().load_run_comparison(project_slug, run_id)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _invalid(exc) from exc


@router.get("/runs/{project_slug}/{run_id}/report.pdf", tags=["runs"])
async def download_run_pdf(project_slug: str, run_id: str) -> FileResponse:
    """Download the stored single-run PDF without re-running analysis."""

    return _run_export(
        project_slug,
        run_id,
        "pdf",
        extension="pdf",
        media_type="application/pdf",
    )


@router.get("/runs/{project_slug}/{run_id}/report.csv", tags=["runs"])
async def download_run_csv(project_slug: str, run_id: str) -> FileResponse:
    """Download the stored long-form CSV without re-running analysis."""

    return _run_export(
        project_slug,
        run_id,
        "csv",
        extension="csv",
        media_type="text/csv; charset=utf-8",
    )


@router.get("/runs/{project_slug}/{run_id}/package.zip", tags=["runs"])
async def download_run_package(project_slug: str, run_id: str) -> FileResponse:
    """Download the replayable project, settings, evidence, and reports."""

    return _run_export(
        project_slug,
        run_id,
        "package",
        extension="zip",
        media_type="application/zip",
    )


@router.post("/runs/{project_slug}/{run_id}/open-folder", tags=["runs"])
async def open_run_folder(project_slug: str, run_id: str) -> dict[str, Any]:
    """Ask the host OS to reveal a completed run directory."""

    try:
        opened = SolveWorkspace().open_run_folder(project_slug, run_id)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "error_code": "OPEN_FOLDER_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc
    return {"status": "opened", "path": str(opened)}


@router.delete("/runs/{project_slug}/{run_id}", tags=["runs"])
async def delete_run(
    project_slug: str,
    run_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Delete exactly one run after the caller repeats its run ID."""

    confirmation = body.get("confirm_run_id")
    if not isinstance(confirmation, str):
        raise _invalid(SolveWorkspaceError("confirm_run_id is required"))
    workspace = SolveWorkspace()
    try:
        workspace.delete_run(
            project_slug,
            run_id,
            confirmation=confirmation,
        )
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError) as exc:
        raise _invalid(exc) from exc
    return {
        "status": "deleted",
        "run_id": run_id,
        "storage": workspace.storage_policy(),
    }
