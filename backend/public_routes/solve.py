"""Launch-safe local Magneto2D and feature-gated Elmer solve routes."""

from __future__ import annotations

import asyncio
import errno
import gzip
import json
import re
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from backend.elmer.capabilities import ElmerCapabilities, discover_elmer
from backend.elmer.errors import (
    ElmerError,
    ElmerUnavailableError,
    ElmerUnsupportedError,
)
from backend.field_artifacts import resolve_solve_cache_artifact_id
from backend.field_composition import solve_armature_field_sweep
from backend.geometry import validate_geometry, winding_feasibility_warnings
from backend.gmsh_solver import GmshUnavailableError
from backend.magneto2d_adapter import (
    Magneto2DExecutionError,
    Magneto2DUnsupportedError,
    get_magneto2d_support_error,
)
from backend.public_field_playback import build_public_field_playback
from backend.public_policy import (
    PublicConfigError,
    PublicSolverId,
    normalize_public_mesh_preview_config,
    parse_public_solve_request,
    public_config_support_error,
)
from backend.solve_workspace import (
    RUN_ARTIFACT_PREFIX,
    SolveRunWriter,
    SolveWorkspace,
    SolveWorkspaceCapacityError,
    SolveWorkspaceError,
    resolve_run_artifact_id,
)
from backend.solver import Magneto2DSolver
from backend.solver_contract import SolveCancelledError, Solver
from backend.sweep_planning import loaded_sweep_plan

router = APIRouter()

_EXCLUDED_SUMMARY_FIELDS = frozenset(
    {
        "cogging_torque_Nm",
        "efficiency_pct",
        "loss_breakdown",
        "weight_inertia",
        "torque_speed_envelope",
        "thermal_estimate",
        "demag_check",
        "slot_fill_check",
    }
)

_EXCLUDED_RESULT_FIELDS = frozenset(
    {
        "cogging_torque_waveform",
        "femm_mesh",
        "slotless_noload_diagnostic",
        "loaded_field_diagnostic",
        "thermal_loss_map",
        "core_loss_density_w_per_m3",
    }
)

_ACTIVE_SOLVE: dict[str, Any] = {
    "running": False,
    "cancelled": False,
    "solver": None,
    "run_writer": None,
}

_PUBLIC_FIELD_PLOT_KEYS = frozenset(
    {
        "angle_deg",
        "config_summary",
        "mesh_info",
        "nodes_mm",
        "triangles",
        "regions",
        "element_b_mag_t",
        "element_bx_t",
        "element_by_t",
        "contour_levels",
        "az_min",
        "az_max",
        "n_pole_pitches",
        "total_span_deg",
        # Binned airgap field profile and its summary stats. Both are pure numeric
        # aggregates — airgap_brbt is {span_deg, bin_count, sample_count, bins[]} of
        # angles and tesla values (backend/field_artifacts.py:162-168) and
        # airgap_b_stats is count/mean/p95/max (backend/models/field.py:106-112).
        # Neither carries a path, an artifact id, or any config echo.
        # Lesson 9 plots peak and mean airgap B against airgap length and reads both;
        # without them here the chart is silently empty rather than erroring.
        "airgap_brbt",
        "airgap_b_stats",
    }
)


def _public_artifact_ref(value: Any) -> dict[str, str] | None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if not isinstance(payload, dict):
        return None
    artifact_id = payload.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    return {"artifact_id": artifact_id}


def _public_field_plot_payload(value: Any) -> dict[str, Any] | None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if not isinstance(payload, dict):
        return None
    sanitized = {
        key: payload[key]
        for key in _PUBLIC_FIELD_PLOT_KEYS
        if key in payload and payload[key] is not None
    }
    noload_plot = _public_field_plot_payload(payload.get("noload_plot"))
    if noload_plot is not None:
        sanitized["noload_plot"] = noload_plot
    return sanitized or None


def _public_field_frame_descriptor(value: Any) -> dict[str, Any] | None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if not isinstance(payload, dict):
        return None
    artifact = _public_artifact_ref(
        payload.get("full_field_frame_artifact") or payload.get("field_frame_artifact")
    )
    if artifact is None:
        return None
    try:
        angle_deg = float(payload.get("angle_deg", 0.0))
    except (TypeError, ValueError):
        angle_deg = 0.0
    descriptor = {
        "angle_deg": angle_deg,
        "field_frame_artifact": artifact,
        "has_pm_only": isinstance(payload.get("noload_plot"), dict),
    }
    # Carry the airgap aggregates on the descriptor as well as the fetched frame.
    # Consumers choose WHICH frame to fetch by comparing peak airgap B across the
    # inline list — Lesson 9 does exactly that (LessonTwoMagneticCircuit.tsx:237).
    # Without these, every comparison resolves to -1, the reduce never swaps, and
    # the lesson silently shows sweep position 0 instead of the peak-flux frame
    # its own caption promises. Same numeric aggregates allowlisted in
    # _PUBLIC_FIELD_PLOT_KEYS above: angles, tesla values and counts, no path,
    # artifact id or config echo.
    for key in ("airgap_brbt", "airgap_b_stats"):
        if payload.get(key) is not None:
            descriptor[key] = payload[key]
    return descriptor


def _public_field_frame_descriptors(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [
        descriptor
        for value in values
        if (descriptor := _public_field_frame_descriptor(value)) is not None
    ]


def _public_config_http_error(exc: PublicConfigError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error_code": "UNSUPPORTED_LAUNCH_CONFIG",
            "message": str(exc),
            "field": exc.field,
        },
    )


def _public_result_payload(
    result: Any,
    *,
    field_playback: dict[str, Any] | None = None,
    retained_field_frame_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Remove post-launch/private result fields from the public payload."""

    payload = result.model_dump(mode="json")
    summary = payload.get("summary")
    if isinstance(summary, dict):
        for field in _EXCLUDED_SUMMARY_FIELDS:
            summary.pop(field, None)
    for field in _EXCLUDED_RESULT_FIELDS:
        payload.pop(field, None)
    solve_metadata = payload.get("solve_metadata")
    if isinstance(solve_metadata, dict):
        solve_metadata.pop("solve_cache_dir", None)
        solve_metadata.pop("postprocess_source_cache_dir", None)
    field_frame_descriptors = _public_field_frame_descriptors(
        payload.get("field_line_frames")
    )
    if field_playback is not None and retained_field_frame_ids is not None:
        field_frame_descriptors = [
            descriptor
            for descriptor in field_frame_descriptors
            if descriptor["field_frame_artifact"]["artifact_id"]
            in retained_field_frame_ids
        ]
        payload["field_playback"] = field_playback
    payload["field_line_frames"] = field_frame_descriptors
    return payload


def _package_public_result(result: Any) -> dict[str, Any]:
    field_playback, retained_ids = build_public_field_playback(
        getattr(result, "field_line_frames", None),
        mode="resultant_pm",
    )
    return _public_result_payload(
        result,
        field_playback=field_playback,
        retained_field_frame_ids=retained_ids if field_playback is not None else None,
    )


def _project_name(body: dict[str, Any], config: Any) -> str:
    raw_name = body.get("project_name") if "config" in body else None
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()[:200]
    return (
        f"coilEM-{str(config.topology).lower()}-"
        f"{config.rotor.pole_count}p{config.stator.slot_count}s"
    )


def _stored_request(body: dict[str, Any]) -> dict[str, Any]:
    """Retain request facts without binding a durable run to a cache key."""

    import hashlib

    payload = dict(body)
    mesh_key = payload.pop("solve_mesh_key", None)
    if mesh_key is not None:
        payload["solve_mesh_key_sha256"] = hashlib.sha256(
            str(mesh_key).encode("utf-8")
        ).hexdigest()
    return payload


def _begin_run(
    body: dict[str, Any],
    config: Any,
) -> tuple[SolveWorkspace, SolveRunWriter]:
    workspace = SolveWorkspace()
    writer = workspace.begin_run(
        project_name=_project_name(body, config),
        config=config.model_dump(mode="json"),
        submitted_request=_stored_request(body),
    )
    return workspace, writer


def _store_public_result(
    workspace: SolveWorkspace,
    writer: SolveRunWriter,
    public_result: dict[str, Any],
) -> dict[str, Any]:
    location = writer.complete(public_result)
    stored = workspace.load_run(location.project_slug, location.run_id)
    result = stored["result"]
    result["saved_run"] = stored["saved_run"]
    return result


def _claim_solve(
    solver: Solver,
    run_writer: SolveRunWriter | None = None,
) -> None:
    if _ACTIVE_SOLVE["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "SOLVE_ALREADY_RUNNING",
                "message": "A local electromagnetic solve is already running.",
            },
        )
    _ACTIVE_SOLVE.update(
        {
            "running": True,
            "cancelled": False,
            "solver": solver,
            "run_writer": run_writer,
        }
    )


def _claim_durable_solve(
    solver: Solver,
    body: dict[str, Any],
    config: Any,
) -> tuple[SolveWorkspace, SolveRunWriter]:
    """Claim the single-solve lane before allocating a durable partial run."""

    _claim_solve(solver)
    try:
        workspace, writer = _begin_run(body, config)
    except Exception:
        _release_solve(solver)
        raise
    _ACTIVE_SOLVE["run_writer"] = writer
    return workspace, writer


def _release_solve(solver: Solver) -> None:
    if _ACTIVE_SOLVE.get("solver") is solver:
        _ACTIVE_SOLVE.update(
            {
                "running": False,
                "cancelled": False,
                "solver": None,
                "run_writer": None,
            }
        )


def _release_after_worker(solver: Solver, future: asyncio.Task[Any] | None) -> None:
    """A disconnected stream must not free the lane while its thread runs."""
    if future is None or future.done():
        _release_solve(solver)
        return

    def finished(task: asyncio.Task[Any]) -> None:
        if not task.cancelled():
            task.exception()  # Retrieve a detached worker's cancellation/error.
        _release_solve(solver)

    future.add_done_callback(finished)


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    return f"event: {event}\ndata: {encoded}\n\n"


_INSUFFICIENT_DISK_SPACE_CODE = "INSUFFICIENT_DISK_SPACE"
_INSUFFICIENT_DISK_SPACE_MESSAGE = (
    "This computer does not have enough free disk space to complete the solve."
)
_INSUFFICIENT_DISK_SPACE_SUGGESTION = (
    "Free at least 10 GB by deleting old runs from Previous runs or removing "
    "other files, then try again."
)


def _is_insufficient_disk_space(exc: BaseException) -> bool:
    """Recognize native and solver-wrapped disk-full failures."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    disk_full_errnos = {errno.ENOSPC}
    if hasattr(errno, "EDQUOT"):
        disk_full_errnos.add(errno.EDQUOT)
    messages = (
        "no space left on device",
        "not enough space on the disk",
        "disk full",
        "disk quota exceeded",
    )

    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, OSError) and (
            current.errno in disk_full_errnos
            or getattr(current, "winerror", None) == 112
        ):
            return True
        if any(message in str(current).casefold() for message in messages):
            return True
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return False


def _insufficient_disk_space_payload() -> dict[str, Any]:
    return {
        "error_code": _INSUFFICIENT_DISK_SPACE_CODE,
        "message": _INSUFFICIENT_DISK_SPACE_MESSAGE,
        "suggestion": _INSUFFICIENT_DISK_SPACE_SUGGESTION,
    }


def _fail_run_safely(
    run_writer: SolveRunWriter,
    payload: dict[str, Any],
    *,
    cancelled: bool = False,
) -> None:
    """Record a failure without hiding a disk-full response if the write also fails."""

    try:
        run_writer.fail(
            error_code=payload["error_code"],
            message=payload["message"],
            cancelled=cancelled,
        )
    except OSError:
        if payload["error_code"] != _INSUFFICIENT_DISK_SPACE_CODE:
            raise


def _stream_error_payload(exc: Exception) -> dict[str, Any]:
    if _is_insufficient_disk_space(exc):
        return _insufficient_disk_space_payload()
    if isinstance(exc, SolveCancelledError) or _ACTIVE_SOLVE["cancelled"]:
        return {
            "error_code": "SOLVER_CANCELLED",
            "message": "Solve cancelled by user.",
        }
    if isinstance(exc, Magneto2DExecutionError) and "nonlinear solve failed to converge" in str(exc).lower():
        # Extract only bounded numerical context; raw CLI errors may contain
        # local paths, full residual histories, or unrelated process output.
        context = re.search(
            r"failed to converge after (\d{1,5}) iterations at rotor_angle_deg=(-?\d{1,6}(?:\.\d{1,6})?)\b",
            str(exc),
            re.IGNORECASE,
        )
        message = "Magneto2D could not find a stable magnetic-field solution within the iteration limit."
        if context:
            iterations, angle = context.groups()
            message = (
                f"Magneto2D could not find a stable magnetic-field solution within {int(iterations)} nonlinear iterations "
                f"(rotor angle {float(angle):g}° mechanical)."
            )
        return {
            "error_code": "NONLINEAR_CONVERGENCE_FAILED",
            "message": message,
            "suggestion": "If using Picard, try Newton (experimental) under Advanced options → Nonlinear solver, then rerun.",
        }
    if isinstance(exc, Magneto2DUnsupportedError):
        return {
            "error_code": "UNSUPPORTED_LAUNCH_CONFIG",
            "message": "Configuration is outside the launch-supported Magneto2D solve boundary.",
        }
    if isinstance(exc, ElmerUnavailableError):
        return {
            "error_code": "ELMER_UNAVAILABLE",
            "message": str(exc) or "A qualified Elmer runtime is unavailable.",
        }
    if isinstance(exc, ElmerUnsupportedError):
        return {
            "error_code": "UNSUPPORTED_LAUNCH_CONFIG",
            "message": str(exc) or "Configuration is outside the qualified Elmer solve boundary.",
        }
    if isinstance(exc, GmshUnavailableError):
        return {
            "error_code": "GMSH_UNAVAILABLE",
            "message": "Gmsh is required for public electromagnetic solves.",
        }
    if isinstance(exc, SolveWorkspaceCapacityError):
        return {
            "error_code": "RUN_STORAGE_LIMIT",
            "message": "The saved-run workspace is full.",
            "suggestion": "Open Previous runs and delete an older saved or incomplete run, then try again.",
        }
    if isinstance(exc, SolveWorkspaceError):
        return {
            "error_code": "RUN_STORAGE_FAILED",
            "message": str(exc),
        }
    if isinstance(exc, ValueError):
        return {
            "error_code": "INVALID_GEOMETRY",
            "message": str(exc),
        }
    if isinstance(exc, ElmerError):
        return {
            "error_code": "SOLVE_FAILED",
            "message": "Elmer solve failed. Review the retained local solver logs for details.",
        }
    return {
        "error_code": "SOLVE_FAILED",
        "message": "The electromagnetic solve failed.",
    }


def _validated_solve_request(
    body: dict[str, Any],
    *,
    allow_elmer: bool = True,
) -> tuple[Any, str | None, PublicSolverId, ElmerCapabilities | None]:
    config, solve_mesh_key, solver_id = parse_public_solve_request(body)
    if solver_id == "elmer" and not allow_elmer:
        raise PublicConfigError(
            "This field-composition route is available only for Magneto2D results.",
            field="solver",
        )
    if (
        solver_id == "elmer"
        and config.solve_params is not None
        and config.solve_params.excitation_mode == "ideal_six_step_120"
    ):
        raise PublicConfigError(
            "Ideal six-step excitation uses the built-in Magneto2D solver in the MVP.",
            field="solver",
        )
    support_error = public_config_support_error(
        config,
        require_solve_params=True,
        solver_id=solver_id,
    )
    if support_error is not None:
        raise support_error
    config = normalize_public_mesh_preview_config(config)
    solve_params = config.solve_params
    assert solve_params is not None
    elmer_capabilities: ElmerCapabilities | None = None
    if solver_id == "elmer":
        elmer_capabilities = discover_elmer()
        if (
            not elmer_capabilities.available
            or not elmer_capabilities.qualified
            or not elmer_capabilities.adapter_ready
        ):
            raise PublicConfigError(
                elmer_capabilities.dependency_reason
                or elmer_capabilities.reason
                or "Install the qualified Elmer 26.2 runtime to enable this solver.",
                field="solver",
            )
        solve_mesh_key = None
        solve_params = solve_params.model_copy(
            update={
                "torque_method": "arkkio",
                "mesh_source": "native",
                "mesher": "gmsh",
                "rotor_rotation_model": "remesh_per_step",
                "stream_noload_field_lines": False,
            }
        )
    else:
        magneto2d_error = get_magneto2d_support_error(config)
        if magneto2d_error is not None:
            raise PublicConfigError(
                "Configuration is outside the launch-supported Magneto2D solve boundary.",
            )
    config = config.model_copy(
        update={
            "solve_params": solve_params.model_copy(
                update={
                    "stream_noload_field_lines": solver_id == "magneto2d",
                    "field_composition_source": "resultant",
                }
            )
        }
    )
    return config, solve_mesh_key, solver_id, elmer_capabilities


def _create_public_solver(
    solver_id: PublicSolverId,
    elmer_capabilities: ElmerCapabilities | None = None,
) -> Solver:
    if solver_id == "elmer":
        # Keep the optional solver implementation out of the default-off launch
        # import graph. The public policy rejects this branch unless the feature
        # was explicitly enabled before the API started.
        from backend.elmer.adapter import ElmerSolver

        return ElmerSolver(
            capabilities=elmer_capabilities or discover_elmer(),
            launch_surface=True,
        )
    return Magneto2DSolver(launch_surface=True)


def _resolve_public_artifact_id(artifact_id: str):
    if artifact_id.startswith(RUN_ARTIFACT_PREFIX):
        try:
            return resolve_run_artifact_id(artifact_id)
        except (FileNotFoundError, SolveWorkspaceError) as exc:
            raise ValueError(str(exc)) from exc
    return resolve_solve_cache_artifact_id(artifact_id)


@router.get("/solve/field-frame/{artifact_id}", tags=["solve"])
async def get_public_field_frame(artifact_id: str) -> dict[str, Any]:
    """Return one sanitized, local Magneto2D field frame by opaque id."""

    try:
        path = _resolve_public_artifact_id(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if (
        not path.exists()
        or not path.is_file()
        or (
            not artifact_id.startswith(RUN_ARTIFACT_PREFIX)
            and path.parent.name != "field_line_frames"
        )
        or not path.name.endswith(".json.gz")
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="field frame not found")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            artifact_payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="field frame could not be read",
        ) from exc
    field_frame = _public_field_plot_payload(artifact_payload.get("field_line_frame"))
    if field_frame is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="field frame not found")
    return {
        "schema_version": "coilem.public_field_frame.v1",
        "field_line_frame": field_frame,
    }


@router.get("/solve/playback-frame/{artifact_id}", tags=["solve"])
async def get_public_playback_frame(artifact_id: str) -> FileResponse:
    """Return one pre-rasterized PNG or WebP layer by opaque local-cache id."""

    try:
        path = _resolve_public_artifact_id(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if (
        not path.exists()
        or not path.is_file()
        or path.suffix.lower() not in {".png", ".webp"}
        or (
            not artifact_id.startswith(RUN_ARTIFACT_PREFIX)
            and path.parent.parent.name != "field_playback"
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="playback frame not found",
        )
    return FileResponse(
        path,
        media_type="image/png" if path.suffix.lower() == ".png" else "image/webp",
        headers={
            "Cache-Control": "private, max-age=3600, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/solve/field-composition/armature", tags=["solve"])
async def solve_public_armature_field(body: dict[str, Any]) -> dict[str, Any]:
    """Compute an exact Br=0 stator-current field sweep on demand."""

    try:
        config, solve_mesh_key, _, _ = _validated_solve_request(
            body,
            allow_elmer=False,
        )
    except PublicConfigError as exc:
        raise _public_config_http_error(exc) from exc

    solver = Magneto2DSolver(launch_surface=True)
    _claim_solve(solver)
    future = asyncio.create_task(asyncio.to_thread(
        solve_armature_field_sweep,
        config,
        solve_mesh_key=solve_mesh_key,
        solver_factory=lambda: solver,
        clockwise_positive=True,
    ))
    try:
        response = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=1200.0,
        )
    except SolveCancelledError as exc:
        raise HTTPException(status_code=409, detail=_stream_error_payload(exc)) from exc
    except (asyncio.TimeoutError, TimeoutError) as exc:
        solver.cancel_active_solve()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error_code": "FIELD_COMPOSITION_TIMEOUT",
                "message": "The stator-current field solve timed out after 1200 seconds.",
            },
        ) from exc
    except (Magneto2DUnsupportedError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_stream_error_payload(exc),
        ) from exc
    except GmshUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_stream_error_payload(exc),
        ) from exc
    except Magneto2DExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_stream_error_payload(exc),
        ) from exc
    finally:
        if not future.done():
            solver.cancel_active_solve()
        _release_after_worker(solver, future)

    return await _package_public_armature_response(response)


async def _package_public_armature_response(
    response: dict[str, Any],
) -> dict[str, Any]:
    """Build the bounded public response shared by one-shot and SSE callers."""

    field_playback, retained_ids = await asyncio.to_thread(
        build_public_field_playback,
        response.get("frames"),
        mode="armature",
    )
    frame_descriptors = _public_field_frame_descriptors(response.get("frames"))
    airgap_profiles = [
        {
            "angle_deg": descriptor["angle_deg"],
            "airgap_brbt": descriptor["airgap_brbt"],
        }
        for descriptor in frame_descriptors
        if descriptor.get("airgap_brbt") is not None
    ]
    if field_playback is not None:
        frame_descriptors = [
            descriptor
            for descriptor in frame_descriptors
            if descriptor["field_frame_artifact"]["artifact_id"] in retained_ids
        ]
    public_response = {
        "schema_version": "coilem.public_field_composition.armature.v1",
        "source": response.get("source"),
        "cache_hit": bool(response.get("cache_hit")),
        "elapsed_s": response.get("elapsed_s"),
        "frame_count": response.get("frame_count"),
        "frames": frame_descriptors,
        "airgap_profiles": airgap_profiles,
    }
    if field_playback is not None:
        public_response["field_playback"] = field_playback
    return public_response


@router.post("/solve/field-composition/armature/stream", tags=["solve"])
async def stream_public_armature_field(body: dict[str, Any]) -> StreamingResponse:
    """Stream exact Br=0 stator-current field frames as Magneto2D solves them."""

    try:
        config, solve_mesh_key, _, _ = _validated_solve_request(
            body,
            allow_elmer=False,
        )
    except PublicConfigError as exc:
        config_error = {
            "error_code": "UNSUPPORTED_LAUNCH_CONFIG",
            "message": str(exc),
            "field": exc.field,
        }

        async def config_error_stream():
            yield _sse_event("error", config_error)

        return StreamingResponse(
            config_error_stream(),
            media_type="text/event-stream",
        )

    solver = Magneto2DSolver(launch_surface=True)
    _claim_solve(solver)

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        future: asyncio.Task[Any] | None = None
        stream_closed = threading.Event()

        def on_progress(
            position: int,
            total: int,
            torque_Nm: float | None,
            stage: str = "torque_sweep",
            elec_deg: float | None = None,
            phase_a_V: float | None = None,
            phase_b_V: float | None = None,
            phase_c_V: float | None = None,
            field_line_frame: dict[str, Any] | None = None,
            solver_detail: dict[str, Any] | None = None,
        ) -> None:
            if stream_closed.is_set():
                return
            payload: dict[str, Any] = {
                "position": position,
                "total": total,
                "elapsed_s": round(time.perf_counter() - started, 1),
                "stage": stage,
            }
            optional_values = {
                "angle_deg": elec_deg,
                "solver_detail": solver_detail,
            }
            payload.update(
                {
                    key: value
                    for key, value in optional_values.items()
                    if value is not None
                }
            )
            if field_line_frame is not None:
                descriptor = _public_field_frame_descriptor(field_line_frame)
                if descriptor is not None:
                    payload["field_frame"] = descriptor
                else:
                    inline_plot = _public_field_plot_payload(field_line_frame)
                    if inline_plot is not None:
                        payload["field_line_frame"] = inline_plot
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        try:
            yield _sse_event(
                "progress",
                {
                    "position": 0,
                    "total": 0,
                    "stage": "starting",
                    "elapsed_s": 0,
                },
            )
            future = asyncio.create_task(
                asyncio.to_thread(
                    solve_armature_field_sweep,
                    config,
                    solve_mesh_key=solve_mesh_key,
                    solver_factory=lambda: solver,
                    clockwise_positive=True,
                    on_progress=on_progress,
                )
            )
            while not future.done():
                try:
                    progress = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield _sse_event("progress", progress)
                except asyncio.TimeoutError:
                    continue

            while not queue.empty():
                yield _sse_event("progress", queue.get_nowait())

            response = await future
            if _ACTIVE_SOLVE["cancelled"]:
                raise SolveCancelledError("Solve cancelled by user.")
            public_response = await _package_public_armature_response(response)
            yield _sse_event("complete", public_response)
        except asyncio.CancelledError:
            solver.cancel_active_solve()
            raise
        except Exception as exc:
            yield _sse_event("error", _stream_error_payload(exc))
        finally:
            stream_closed.set()
            if future is not None and not future.done():
                solver.cancel_active_solve()
            _release_after_worker(solver, future)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/solve", tags=["solve"])
async def solve(body: dict[str, Any]) -> dict[str, Any]:
    """Run a launch-supported local electromagnetic solve pipeline."""

    try:
        config, solve_mesh_key, solver_id, elmer_capabilities = _validated_solve_request(body)
    except PublicConfigError as exc:
        raise _public_config_http_error(exc) from exc

    solver = _create_public_solver(solver_id, elmer_capabilities)
    solver_label = "Elmer" if solver_id == "elmer" else "Magneto2D"
    timeout_seconds = 1800.0 if solver_id == "elmer" else 1200.0
    try:
        workspace, run_writer = _claim_durable_solve(solver, body, config)
    except Exception as exc:
        if _is_insufficient_disk_space(exc):
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=_insufficient_disk_space_payload(),
            ) from exc
        if isinstance(exc, SolveWorkspaceError):
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=_stream_error_payload(exc),
            ) from exc
        raise
    future = asyncio.create_task(asyncio.to_thread(solver.solve, config, solve_mesh_key=solve_mesh_key))
    try:
        result = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=timeout_seconds,
        )
        public_result = await asyncio.to_thread(_package_public_result, result)
        return await asyncio.to_thread(
            _store_public_result,
            workspace,
            run_writer,
            public_result,
        )
    except (asyncio.CancelledError, SolveCancelledError) as exc:
        solver.cancel_active_solve()
        run_writer.fail(
            error_code="SOLVER_CANCELLED",
            message="Solve cancelled by user.",
            cancelled=True,
        )
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(status_code=409, detail=_stream_error_payload(exc)) from exc
    except (asyncio.TimeoutError, TimeoutError) as exc:
        solver.cancel_active_solve()
        run_writer.fail(
            error_code="SOLVE_TIMEOUT",
            message=f"{solver_label} solve timed out after {timeout_seconds:.0f} seconds.",
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error_code": "SOLVE_TIMEOUT",
                "message": f"{solver_label} solve timed out after {timeout_seconds:.0f} seconds.",
            },
        ) from exc
    except (Magneto2DUnsupportedError, ElmerUnsupportedError) as exc:
        unsupported_message = (
            "Configuration is outside the qualified Elmer solve boundary."
            if solver_id == "elmer"
            else "Configuration is outside the launch-supported Magneto2D solve boundary."
        )
        run_writer.fail(
            error_code="UNSUPPORTED_LAUNCH_CONFIG",
            message=unsupported_message,
        )
        raise _public_config_http_error(
            PublicConfigError(unsupported_message)
        ) from exc
    except GmshUnavailableError as exc:
        run_writer.fail(
            error_code="GMSH_UNAVAILABLE",
            message=f"Gmsh is required for public {solver_label} solves.",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "GMSH_UNAVAILABLE",
                "message": f"Gmsh is required for public {solver_label} solves.",
            },
        ) from exc
    except Magneto2DExecutionError as exc:
        error_payload = _stream_error_payload(exc)
        _fail_run_safely(run_writer, error_payload)
        raise HTTPException(
            status_code=(
                status.HTTP_507_INSUFFICIENT_STORAGE
                if error_payload["error_code"] == _INSUFFICIENT_DISK_SPACE_CODE
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=error_payload,
        ) from exc
    except ElmerError as exc:
        error_payload = _stream_error_payload(exc)
        _fail_run_safely(run_writer, error_payload)
        response_status = (
            status.HTTP_507_INSUFFICIENT_STORAGE
            if error_payload["error_code"] == _INSUFFICIENT_DISK_SPACE_CODE
            else status.HTTP_503_SERVICE_UNAVAILABLE
            if isinstance(exc, ElmerUnavailableError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=response_status,
            detail=error_payload,
        ) from exc
    except ValueError as exc:
        run_writer.fail(
            error_code="INVALID_GEOMETRY",
            message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_GEOMETRY",
                "message": str(exc),
                "field": None,
            },
        ) from exc
    except SolveWorkspaceError as exc:
        error_payload = _stream_error_payload(exc)
        _fail_run_safely(run_writer, error_payload)
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=error_payload,
        ) from exc
    except Exception as exc:
        error_payload = _stream_error_payload(exc)
        if error_payload["error_code"] == _INSUFFICIENT_DISK_SPACE_CODE:
            _fail_run_safely(run_writer, error_payload)
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=error_payload,
            ) from exc
        run_writer.fail(
            error_code="SOLVE_FAILED",
            message=f"{solver_label} solve failed unexpectedly.",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "SOLVE_FAILED",
                "message": f"{solver_label} solve failed unexpectedly.",
            },
        ) from exc
    finally:
        if not future.done():
            solver.cancel_active_solve()
        _release_after_worker(solver, future)


@router.post("/solve/validate", tags=["solve"])
async def validate_solve(body: dict[str, Any]) -> dict[str, Any]:
    """Validate the launch-supported solve and return local estimates."""

    try:
        config, _, solver_id, _ = _validated_solve_request(body)
    except PublicConfigError as exc:
        raise _public_config_http_error(exc) from exc

    errors = validate_geometry(config)
    error_list = [
        {
            "code": error.error_code,
            "message": error.message,
            "suggestion": error.suggestion,
        }
        for error in errors
    ]
    solve_params = config.solve_params
    assert solve_params is not None
    pole_pairs = config.rotor.pole_count // 2
    include_no_load = (
        True
        if config.solve_options is None
        else bool(config.solve_options.back_emf or config.solve_options.thd_analysis)
    )
    sweep_positions, _ = loaded_sweep_plan(config)
    estimated_time_s = solve_params.estimate_solve_time_s(
        pole_pairs,
        include_no_load=include_no_load,
    )
    if solver_id == "elmer":
        estimated_time_s *= 3.0
    estimated_elements = (
        config.stator.slot_count * 500
        + config.rotor.pole_count * 200
        + 5000
    )
    warnings = winding_feasibility_warnings(config)
    if estimated_time_s > 120:
        warnings.append(
            "Estimated solve time exceeds two minutes; use quick quality for iteration.",
        )
    if estimated_elements > 100000:
        warnings.append("Estimated mesh exceeds 100,000 elements and may be slow.")

    return {
        "valid": not error_list,
        "errors": error_list,
        "warnings": warnings,
        "estimated_solve_time_s": round(estimated_time_s, 1),
        "estimated_mesh_elements": estimated_elements,
        "solve_quality": solve_params.solve_quality,
        "step_deg": solve_params.effective_step_deg(),
        "sweep_positions": sweep_positions,
        "solver_lane": {
            "native_supported": True,
            "reason": None,
            "lane": solver_id,
            "lane_unavailable_reason": None,
        },
    }


@router.post("/solve/stream", tags=["solve"])
async def solve_stream(body: dict[str, Any]) -> StreamingResponse:
    """Stream launch-safe local solver progress and a scrubbed result over SSE."""

    try:
        config, solve_mesh_key, solver_id, elmer_capabilities = _validated_solve_request(body)
    except PublicConfigError as exc:
        config_error = {
            "error_code": "UNSUPPORTED_LAUNCH_CONFIG",
            "message": str(exc),
            "field": exc.field,
        }

        async def config_error_stream():
            yield _sse_event("error", config_error)

        return StreamingResponse(
            config_error_stream(),
            media_type="text/event-stream",
        )

    solver = _create_public_solver(solver_id, elmer_capabilities)
    try:
        workspace, run_writer = _claim_durable_solve(solver, body, config)
    except Exception as exc:
        storage_error = _stream_error_payload(exc)
        if (
            not isinstance(exc, SolveWorkspaceError)
            and storage_error["error_code"] != _INSUFFICIENT_DISK_SPACE_CODE
        ):
            raise

        async def storage_error_stream():
            yield _sse_event("error", storage_error)

        return StreamingResponse(
            storage_error_stream(),
            media_type="text/event-stream",
        )

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        future: asyncio.Task[Any] | None = None
        stream_closed = threading.Event()
        latest_position = 0
        latest_total = 0

        def on_progress(
            position: int,
            total: int,
            torque_Nm: float | None,
            stage: str = "torque_sweep",
            elec_deg: float | None = None,
            phase_a_V: float | None = None,
            phase_b_V: float | None = None,
            phase_c_V: float | None = None,
            field_line_frame: dict[str, Any] | None = None,
            solver_detail: dict[str, Any] | None = None,
        ) -> None:
            nonlocal latest_position, latest_total
            if stream_closed.is_set():
                return
            if total > 0:
                latest_position = position
                latest_total = total
            payload: dict[str, Any] = {
                "position": position,
                "total": total,
                "elapsed_s": round(time.perf_counter() - started, 1),
                "stage": stage,
            }
            optional_values = {
                "torque_Nm": torque_Nm,
                "angle_deg": elec_deg,
                "phase_a_V": phase_a_V,
                "phase_b_V": phase_b_V,
                "phase_c_V": phase_c_V,
                "field_line_frame": field_line_frame,
                "solver_detail": solver_detail,
            }
            payload.update(
                {
                    key: value
                    for key, value in optional_values.items()
                    if value is not None
                }
            )
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        try:
            geometry_errors = validate_geometry(config)
            if geometry_errors:
                run_writer.fail(
                    error_code="INVALID_GEOMETRY",
                    message="; ".join(error.message for error in geometry_errors),
                )
                yield _sse_event(
                    "error",
                    {
                        "error_code": "INVALID_GEOMETRY",
                        "message": "; ".join(error.message for error in geometry_errors),
                    },
                )
                return

            yield _sse_event(
                "progress",
                {
                    "position": 0,
                    "total": 0,
                    "stage": "starting",
                    "elapsed_s": 0,
                },
            )
            future = asyncio.create_task(
                asyncio.to_thread(
                    solver.solve,
                    config,
                    on_progress=on_progress,
                    solve_mesh_key=solve_mesh_key,
                )
            )
            while not future.done():
                try:
                    progress = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield _sse_event("progress", progress)
                except asyncio.TimeoutError:
                    continue

            while not queue.empty():
                yield _sse_event("progress", queue.get_nowait())

            result = await future
            if _ACTIVE_SOLVE["cancelled"]:
                raise SolveCancelledError("Solve cancelled by user.")
            finalization_position = latest_total or latest_position
            yield _sse_event(
                "progress",
                {
                    "position": finalization_position,
                    "total": latest_total,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                    "stage": "packaging_results",
                },
            )
            public_result = await asyncio.to_thread(_package_public_result, result)
            yield _sse_event(
                "progress",
                {
                    "position": finalization_position,
                    "total": latest_total,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                    "stage": "saving_run",
                },
            )
            stored_result = await asyncio.to_thread(
                _store_public_result,
                workspace,
                run_writer,
                public_result,
            )
            yield _sse_event("complete", stored_result)
        except asyncio.CancelledError:
            solver.cancel_active_solve()
            run_writer.fail(
                error_code="SOLVER_CANCELLED",
                message="Solve cancelled by user.",
                cancelled=True,
            )
            raise
        except Exception as exc:
            error_payload = _stream_error_payload(exc)
            _fail_run_safely(
                run_writer,
                error_payload,
                cancelled=error_payload["error_code"] == "SOLVER_CANCELLED",
            )
            yield _sse_event("error", error_payload)
        finally:
            stream_closed.set()
            if future is not None and not future.done():
                solver.cancel_active_solve()
            _release_after_worker(solver, future)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/solve/cancel", tags=["solve"])
async def cancel_solve() -> dict[str, str]:
    """Cancel the active public electromagnetic solve, if one exists."""

    solver = _ACTIVE_SOLVE.get("solver")
    if not _ACTIVE_SOLVE["running"] or solver is None:
        return {"status": "no_active_solve"}

    _ACTIVE_SOLVE["cancelled"] = True
    run_writer = _ACTIVE_SOLVE.get("run_writer")
    if isinstance(run_writer, SolveRunWriter):
        run_writer.fail(
            error_code="SOLVER_CANCELLED",
            message="Solve cancelled by user.",
            cancelled=True,
        )
    try:
        solver.cancel_active_solve()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "CANCEL_FAILED",
                "message": "Failed to stop the active electromagnetic solve.",
            },
        ) from exc
    return {"status": "cancelling"}
