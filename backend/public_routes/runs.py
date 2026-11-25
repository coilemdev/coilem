"""Safe local run-management routes for the public application."""

from __future__ import annotations

import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.convergence_reporting import convergence_report
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
    workspace = SolveWorkspace()
    try:
        export = workspace.resolve_export(
            project_slug,
            run_id,
            export_name,
        )
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _export_unavailable(exc) from exc
    # A package is built for this download only; remove it once it is sent.
    cleanup = BackgroundTask(export.unlink, missing_ok=True) if workspace.is_export_scratch(export) else None
    return FileResponse(
        export,
        media_type=media_type,
        filename=f"coilem-{project_slug}-{run_id}.{extension}",
        background=cleanup,
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
        payload = SolveWorkspace().load_run(project_slug, run_id)
        # Derive a view from stored evidence, including older runs. Never rewrite
        # the immutable result or its already generated exports.
        if isinstance(payload.get("result"), dict):
            payload = {**payload, "result": {**payload["result"], "solver_convergence": convergence_report(payload["result"])}}
        return payload
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _invalid(exc) from exc


@router.get("/runs/{project_slug}/{run_id}/comparison", tags=["runs"])
async def load_run_comparison(project_slug: str, run_id: str) -> dict[str, Any]:
    """Load the stored envelopes and compact records for multi-run comparison."""

    try:
        return SolveWorkspace().load_run_comparison(project_slug, run_id)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _invalid(exc) from exc


@router.get("/runs/{project_slug}/{run_id}/comparison/field", tags=["runs"])
def load_run_comparison_field(project_slug: str, run_id: str) -> dict[str, Any]:
    """Fetch an integrity-checked stored snapshot only when its view is opened."""
    from backend.public_routes.solve import _public_field_plot_payload

    try:
        plot = SolveWorkspace().load_run_comparison_field(project_slug, run_id)
        public_plot = _public_field_plot_payload(plot)
        if public_plot is None:
            raise FileNotFoundError("A field snapshot was not recorded for this run.")
        return {"field_line_frame": public_plot}
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except (OSError, SolveWorkspaceError, ValueError) as exc:
        raise _invalid(exc) from exc


def _run_export_with_thermal(project_slug: str, run_id: str, kind: str, thermal: str | None, thermal_curve: str | None) -> Response:
    """The run's report with its thermal results in it, built for this download.

    The stored report is written when the run completes and never changes. A
    thermal estimate or torque curve is computed afterwards from that run, so a
    report that includes them is built on request from the stored run and the
    saved thermal records. Nothing is solved and nothing stored is changed.
    """
    from backend.public_report import build_public_run_csv, build_public_run_pdf
    from backend.public_routes.thermal import ThermalRunRef, _record, _saved_report

    # The verified stored run, as the thermal routes read it (404 if it is gone, 409 if it fails its checks).
    run = ThermalRunRef(project_slug=project_slug, run_id=run_id)
    arguments = _saved_report(run)
    result = dict(arguments["result"])
    summary = dict(result.get("summary") or {})
    for identity, kind_wanted, place in ((thermal, "point", "thermal"), (thermal_curve, "rating", "thermal_torque_curve")):
        if not identity:
            continue
        record = _record(identity)
        # A thermal result belongs to the run it was computed from; one saved before runs were recorded
        # with it is matched on its design.
        origin = record.get("saved_run")
        same = (origin == run.model_dump() if origin
                else _design_parts(record.get("config")) == _design_parts(arguments["request"].get("resolved_config")))
        if record.get("kind") != kind_wanted or not same:
            raise HTTPException(status.HTTP_409_CONFLICT, "That thermal result was not computed for this run.")
        if place == "thermal":
            summary["thermal"] = record["result"]
        else:
            result[place] = record["result"]
    result["summary"] = summary
    arguments = {**arguments, "result": result}
    content = build_public_run_pdf(**arguments) if kind == "pdf" else build_public_run_csv(**arguments)
    media = "application/pdf" if kind == "pdf" else "text/csv; charset=utf-8"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="coilem-{project_slug}-{run_id}.{kind}"'})


def _design_parts(config: Any) -> Any:
    """The parts of a design a thermal result depends on; the operating point may differ between a run and its torque curve."""
    if not isinstance(config, dict):
        return None
    return [config.get(name) for name in ("topology", "rotor_layout", "stator", "rotor", "winding", "materials")]


@router.get("/runs/{project_slug}/{run_id}/report.pdf", tags=["runs"])
async def download_run_pdf(project_slug: str, run_id: str, thermal: str | None = None, thermal_curve: str | None = None) -> Response:
    """Download the single-run PDF without re-running analysis.

    Without thermal results this is the stored report. ``thermal`` and
    ``thermal_curve`` name saved thermal records to include.
    """

    if thermal or thermal_curve:
        return _run_export_with_thermal(project_slug, run_id, "pdf", thermal, thermal_curve)
    return _run_export(
        project_slug,
        run_id,
        "pdf",
        extension="pdf",
        media_type="application/pdf",
    )


@router.get("/runs/{project_slug}/{run_id}/report.csv", tags=["runs"])
async def download_run_csv(project_slug: str, run_id: str, thermal: str | None = None, thermal_curve: str | None = None) -> Response:
    """Download the long-form CSV without re-running analysis; ``thermal`` as for the PDF."""

    if thermal or thermal_curve:
        return _run_export_with_thermal(project_slug, run_id, "csv", thermal, thermal_curve)
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
