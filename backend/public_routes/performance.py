"""Performance routes: the flux-linkage map, torque–speed envelope and efficiency map (#139–#141).

The map runs on the single local solve lane, so ``/solve/cancel`` stops it and
no other solve can start meanwhile. Finished points are kept under the user
data root by design, and a later run of the same design resumes from them.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from backend.drive_performance import efficiency_map, torque_speed_envelope
from backend.flux_linkage_map import (
    MapPreset,
    MapStore,
    map_agreement_pct,
    map_grid,
    map_positions_per_point,
    map_scope_key,
    map_solve_count,
    run_flux_linkage_map,
)
from backend.models.performance import DriveControl, DriveLimits, FluxLinkageMap
from backend.performance_report import (
    ReportContext,
    build_idiq_table_csv,
    build_performance_csv,
    build_performance_pdf,
    performance_data,
)
from backend.public_policy import PublicConfigError
from backend.public_routes import solve as solve_routes
from backend.solve_workspace import user_data_root

router = APIRouter(tags=["performance"])


class MapSettings(BaseModel):
    preset: MapPreset = "preview"
    peak_current_A: float = Field(gt=0, le=5000.0, description="Largest peak phase current the map covers")


class DriveRequest(BaseModel):
    map: FluxLinkageMap
    limits: DriveLimits
    phase_resistance_ohm: float = Field(ge=0)
    winding_temperature_C: float = Field(ge=-50.0, le=250.0)
    mechanical_loss_W: float = Field(default=0.0, ge=0)
    control: DriveControl = "mtpa"


class ReportRequest(DriveRequest):
    context: ReportContext = Field(default_factory=ReportContext)


ReportKind = Literal["pdf", "csv", "idiq"]
_REPORT_FILES: dict[str, tuple[str, str]] = {
    "pdf": ("performance.pdf", "application/pdf"),
    "csv": ("performance.csv", "text/csv; charset=utf-8"),
    "idiq": ("idiq-table.csv", "text/csv; charset=utf-8"),
}


def _store_root():
    return user_data_root() / "performance_maps"


def _parse_map_request(body: dict[str, Any]):
    if not isinstance(body, dict) or not isinstance(body.get("request"), dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_MAP_REQUEST", "message": "The map request needs the solve request and the map settings."},
        )
    try:
        settings = MapSettings.model_validate(body.get("map") or {})
        config, _mesh_key, solver_id, _capabilities = solve_routes._validated_solve_request(body["request"], allow_elmer=False)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_MAP_SETTINGS", "message": exc.errors()[0].get("msg", "Invalid map settings.")},
        ) from exc
    except PublicConfigError as exc:
        raise solve_routes._public_config_http_error(exc) from exc
    if solver_id != "magneto2d":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "UNSUPPORTED_MAP_SOLVER", "message": "The flux-linkage map uses the built-in Magneto2D solver."},
        )
    return config, settings


def _map_payload(flux_map: FluxLinkageMap) -> dict[str, Any]:
    return {"map": flux_map.model_dump(mode="json"), "torque_agreement_pct": map_agreement_pct(flux_map)}


@router.post("/performance/map/status")
async def map_status(body: dict[str, Any]) -> dict[str, Any]:
    """The design's stored map, if any, and how many solves a new one needs."""

    config, settings = _parse_map_request(body)
    scope_key = map_scope_key(config, settings.preset)
    store = MapStore(_store_root(), scope_key)
    currents, gammas = map_grid(settings.peak_current_A, settings.preset)
    covering = store.covering_map(settings.peak_current_A)
    finished = sum(1 for current in currents for gamma in gammas if current > 0 and store.load(current, gamma) is not None)
    finished += 1 if store.load(0.0, gammas[0]) is not None else 0
    return {
        "scope_key": scope_key,
        "solves_total": map_solve_count(currents, gammas),
        "solves_finished": finished,
        "positions_per_point": map_positions_per_point(settings.preset),
        **(_map_payload(covering) if covering is not None else {"map": None}),
    }


@router.post("/performance/map/stream")
async def stream_map(body: dict[str, Any]) -> StreamingResponse:
    """Solve the map's points over SSE: progress per point, then the map."""

    config, settings = _parse_map_request(body)
    solver = solve_routes._create_public_solver("magneto2d")
    solve_routes._claim_solve(solver)
    store = MapStore(_store_root(), map_scope_key(config, settings.preset))

    async def events():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        future: asyncio.Future[Any] | None = None

        def on_progress(done: int, total: int, point, eta: float | None) -> None:
            payload = {
                "done": done,
                "total": total,
                "current_peak_A": point.current_peak_A,
                "gamma_deg": point.gamma_deg,
                "status": point.status,
                "elapsed_s": round(time.perf_counter() - started, 1),
                "eta_s": None if eta is None else round(eta),
            }
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        try:
            yield solve_routes._sse_event("progress", {"done": 0, "total": 0, "elapsed_s": 0, "stage": "starting"})
            future = solve_routes._run_solver_thread(
                run_flux_linkage_map,
                config,
                solve=solver.solve,
                peak_current_A=settings.peak_current_A,
                preset=settings.preset,
                store=store,
                progress=on_progress,
                should_stop=lambda: bool(solve_routes._ACTIVE_SOLVE["cancelled"]),
            )
            while not future.done():
                solve_routes._raise_if_server_stopping()
                try:
                    yield solve_routes._sse_event("progress", await asyncio.wait_for(queue.get(), timeout=0.5))
                except asyncio.TimeoutError:
                    continue
            while not queue.empty():
                yield solve_routes._sse_event("progress", queue.get_nowait())
            flux_map = await future
            yield solve_routes._sse_event("complete", _map_payload(flux_map))
        except asyncio.CancelledError:
            solver.cancel_active_solve()
            raise
        except Exception as exc:
            yield solve_routes._sse_event("error", solve_routes._stream_error_payload(exc))
        finally:
            if future is not None and not future.done():
                solver.cancel_active_solve()
            solve_routes._release_after_worker(solver, future)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/performance/drive")
async def drive_performance(body: dict[str, Any]) -> dict[str, Any]:
    """Torque–speed envelope and efficiency map from a finished map under the drive limits."""

    try:
        request = DriveRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_DRIVE_REQUEST", "message": exc.errors()[0].get("msg", "Invalid drive request.")},
        ) from exc
    try:
        envelope = await asyncio.to_thread(
            torque_speed_envelope,
            request.map,
            request.limits,
            phase_resistance_ohm=request.phase_resistance_ohm,
            winding_temperature_C=request.winding_temperature_C,
        )
        efficiency = await asyncio.to_thread(
            efficiency_map,
            request.map,
            request.limits,
            phase_resistance_ohm=request.phase_resistance_ohm,
            winding_temperature_C=request.winding_temperature_C,
            mechanical_loss_W=request.mechanical_loss_W,
            envelope=envelope,
            control=request.control,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "MAP_NOT_USABLE", "message": str(exc)},
        ) from exc
    return {"envelope": envelope.model_dump(mode="json"), "efficiency_map": efficiency.model_dump(mode="json")}


@router.post("/performance/report/{kind}")
async def performance_report(kind: ReportKind, body: dict[str, Any]) -> Response:
    """The Torque-speed tab's results as a PDF, the performance CSV or the id/iq table.

    Built on demand from the request the tab sends to /performance/drive, with
    the same functions, so the files carry the values the tab shows; a run's
    own report stays as written when its solve completed.
    """

    try:
        request = ReportRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_REPORT_REQUEST", "message": exc.errors()[0].get("msg", "Invalid report request.")},
        ) from exc
    try:
        data = await asyncio.to_thread(
            performance_data,
            request.map,
            request.limits,
            phase_resistance_ohm=request.phase_resistance_ohm,
            winding_temperature_C=request.winding_temperature_C,
            mechanical_loss_W=request.mechanical_loss_W,
            control=request.control,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "MAP_NOT_USABLE", "message": str(exc)},
        ) from exc
    builder = {"pdf": build_performance_pdf, "csv": build_performance_csv, "idiq": build_idiq_table_csv}[kind]
    content = await asyncio.to_thread(builder, data, request.context)
    suffix, media_type = _REPORT_FILES[kind]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", request.context.design_name or "coilem-design").strip("-") or "coilem-design"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{stem}-{suffix}"', "Cache-Control": "no-store"},
    )
