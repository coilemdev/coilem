"""Local thermal estimates, cancellable bracket/rating jobs and frozen supplements."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import math
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field

from backend.benchmark_suite.temperature_metrics import InterpolationAcceptance, thermal_processing_identity
from backend.flux_linkage_map import map_computation_identity
from backend.loss_breakdown import operating_point_losses
from backend.models import DriveLimits, IronLoss
from backend.models.thermal import ThermalInputs, ThermalModel
from backend.public_policy import PublicConfigError
from backend.public_routes import solve as solve_routes
from backend.public_routes.performance import _map_store
from backend.resources import data_file
from backend.solve_workspace import user_data_root
from backend.solver_contract import SolveCancelledError
from backend.temperature_maps import solve_temperature_bracket
from backend.thermal_network import thermal_estimate
from backend.thermal_rating import CouplingSettings, thermal_rating

router = APIRouter(tags=["thermal"])


class ThermalPointRequest(ThermalModel):
    request: dict[str, Any]
    source: dict[str, Any]
    inputs: ThermalInputs
    design_name: str = Field(default="Motor", max_length=200)


class ThermalRatingRequest(ThermalModel):
    request: dict[str, Any]
    inputs: ThermalInputs
    limits: DriveLimits
    low_C: float = 20
    high_C: float = 80
    preset: Literal["preview", "standard"] = "preview"
    coupling: CouplingSettings = Field(default_factory=CouplingSettings)
    control: Literal["mtpa", "least_loss"] = "mtpa"
    user_magnet_C: float | None = None
    speed_samples: int = Field(default=13, ge=2, le=61)
    design_name: str = Field(default="Motor", max_length=200)


def _config(request):
    try:
        config, _, solver_id, _ = solve_routes._validated_solve_request(request, allow_elmer=False)
    except PublicConfigError as exc:
        raise solve_routes._public_config_http_error(exc) from exc
    if solver_id != "magneto2d":
        raise ValueError("Thermal estimates use the Magneto2D motor model")
    return config


def _freeze(kind, config, inputs, result, **extra):
    identity = uuid.uuid4().hex
    record = dict(id=identity, kind=kind, config=config.model_dump(mode="json"), inputs=inputs.model_dump(mode="json"),
                  result=result.model_dump(mode="json"), computation_identity=map_computation_identity(config), **extra)
    # Both point and rating temperatures depend on the thermal reduction. Keep
    # that provenance separate so correcting it neither invalidates EM maps nor
    # repins EM guards. Older frozen records retain their original identities.
    backend_root = Path(__file__).resolve().parents[1]
    sources = ("thermal_network.py", "models/thermal.py", "winding_resistance.py", "loss_breakdown.py", "public_routes/thermal.py")
    if kind == "rating":
        sources += ("thermal_rating.py",)
    record["computation_identity"][f"thermal_{kind}_processing"] = {
        name: hashlib.sha256((backend_root / name).read_bytes()).hexdigest() for name in sources
    }
    root = user_data_root() / "thermal_analyses"
    root.mkdir(parents=True, exist_ok=True)
    path = root / (identity + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
    return record


def _record(identity):
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise HTTPException(404, "Thermal analysis not found")
    try:
        return json.loads((user_data_root() / "thermal_analyses" / (identity + ".json")).read_text())
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "Thermal analysis not found") from exc


def _acceptance(bracket):
    try:
        rechecked = json.loads(data_file("benchmarks/thermal-v0.6/rotor-heat-recomputed.json").read_text())
        if rechecked["thermal_processing_sha256"] != thermal_processing_identity():
            return None  # Historical temperature comparisons cannot attest new paths.
    except (OSError, ValueError, KeyError):
        return None
    for name in ("spm_8p12s_concentrated", "ipm_flat_8p12s_fsae"):
        try:
            raw = data_file(f"benchmarks/thermal-v0.6/{name}-native.json").read_bytes()
            record = json.loads(raw)
        except (OSError, ValueError):
            continue
        if (record["bracket"]["low"]["scope_key"] == bracket.low.scope_key
                and record["bracket"]["high"]["scope_key"] == bracket.high.scope_key
                and record["bracket"]["low"]["current_peak_A"] == bracket.low.current_peak_A
                and record["bracket"]["low"]["gamma_deg"] == bracket.low.gamma_deg):
            for fresh in rechecked["native"]:
                if (fresh["case_id"] == name and fresh["source_bundle_sha256"] == hashlib.sha256(raw).hexdigest()
                        and fresh["source_scope_keys"] == [bracket.low.scope_key, bracket.high.scope_key]):
                    return InterpolationAcceptance.model_validate(fresh["acceptance"])
    return None


@router.post("/performance/thermal/point")
async def thermal_point(body: ThermalPointRequest):
    try:
        config = _config(body.request)
        # Preflight computation identity also gives a clear error before saving.
        _map_store(config, "preview")
        # Same local supplied-result trust boundary as run-report export. The
        # frozen config/summary is reproducible, not server-attested solve evidence.
        source = body.source
        summary = source.get("summary")
        if not isinstance(summary, dict) or not summary.get("iron_loss"):
            raise ValueError("Thermal estimates use this run's losses. Turn on Losses & efficiency under "
                             "Solve > Analysis, then solve again.")
        torque = summary.get("avg_torque_Nm")
        if isinstance(torque, bool) or not isinstance(torque, (int, float)) or not math.isfinite(torque):
            raise ValueError("Thermal estimates use this run's torque, and this run has none. Solve the operating "
                             "point with torque and losses, then try again.")
        iron = IronLoss.model_validate(summary["iron_loss"])
        winding, losses = operating_point_losses(config, float(torque), iron)
        if winding is None or losses is None:
            raise ValueError("Solve this operating point with winding and iron-loss outputs first")
        result = await asyncio.to_thread(thermal_estimate, config, body.inputs, winding, losses, iron, with_copper_feedback=True)
        result.notes.append("Uses the supplied run summary; its match to this design has not been independently verified.")
        # Store only the numerical source and provenance, never large field media.
        source = {key: source[key] for key in ("summary", "solve_metadata") if key in source}
        return _freeze("point", config, body.inputs, result, source=source, design_name=body.design_name)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/performance/thermal/stream")
async def thermal_stream(body: ThermalRatingRequest):
    from backend.magnet_temperature import magnet_temperature_unavailable_reason

    try:
        config = _config(body.request)
        if body.low_C >= body.high_C:
            raise ValueError("Temperature brackets must be strictly increasing")
        for temperature in (body.low_C, body.high_C):
            reason = magnet_temperature_unavailable_reason(config.materials.magnet_grade, temperature)
            if reason:
                raise ValueError(reason)
        _map_store(config, body.preset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    solver = solve_routes._create_public_solver("magneto2d")
    solve_routes._claim_solve(solver)

    async def events():
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        future = None
        # Set when the stream ends; a worker still running then has no listener.
        stream_closed = threading.Event()

        def progress(stage, done=0, total=0):
            if not stream_closed.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, dict(stage=stage, done=done, total=total))

        def should_stop():
            # The rating search runs mostly between native solves, where
            # cancelling the solver alone does not reach it.
            return stream_closed.is_set() or bool(solve_routes._ACTIVE_SOLVE["cancelled"])

        def work():
            progress("Solving the cold and hot torque-speed maps")
            # Both maps have the same grid, so the two counts run on as one.
            bracket = solve_temperature_bracket(config, body.low_C, body.high_C, peak_current_A=body.limits.peak_current_A,
                solve=solver.solve, store_root=user_data_root() / "performance_maps", preset=body.preset,
                should_stop=should_stop,
                progress=lambda index, done, total: progress(f"Solving the {'hot' if index else 'cold'} map", done + index * total, 2 * total))
            progress("Finding the torque each speed can hold")
            rating = thermal_rating(bracket, body.inputs, body.limits, coupling=body.coupling, control=body.control,
                speed_samples=body.speed_samples, user_magnet_C=body.user_magnet_C, acceptance=_acceptance(bracket),
                direct_solve=solver.solve, should_stop=should_stop,
                progress=lambda done, total: progress("Checking each speed's limiting point with a direct solve", done, total))
            if stream_closed.is_set():
                # Nobody receives a record for a job the client walked away from.
                raise SolveCancelledError("The thermal stream closed before the rating finished.")
            return _freeze("rating", config, body.inputs, rating, bracket=bracket.model_dump(mode="json"), design_name=body.design_name)

        try:
            yield solve_routes._sse_event("progress", dict(stage="Starting", done=0, total=0))
            future = solve_routes._run_solver_thread(work)
            while not future.done():
                try:
                    yield solve_routes._sse_event("progress", await asyncio.wait_for(queue.get(), timeout=0.5))
                except asyncio.TimeoutError:
                    solve_routes._raise_if_server_stopping()
            yield solve_routes._sse_event("complete", await future)
        except Exception as exc:
            yield solve_routes._sse_event("error", dict(error_code="THERMAL_JOB_FAILED", message=str(exc)))
        finally:
            # Client disconnect, task cancellation (CancelledError) and closing
            # the iterator (GeneratorExit at a yield) all end here. A worker
            # still running is told to stop, both the search between native
            # solves and the native solve itself, and the lane is freed only
            # once that worker has returned.
            stream_closed.set()
            try:
                if future is not None and not future.done():
                    solve_routes._stop_solve_worker(solver)
            finally:
                solve_routes._release_after_worker(solver, future)
    return solve_routes._SolveLaneStream(events(), abandon=lambda: solve_routes._release_solve(solver))


@router.get("/performance/thermal/record/{identity}")
async def thermal_record(identity: str):
    return _record(identity)


@router.get("/performance/thermal/report/{identity}/{kind}")
async def thermal_report(identity: str, kind: Literal["pdf", "csv"]):
    from backend.thermal_reporting import thermal_csv_rows, thermal_story

    record = _record(identity)
    result = record["result"]
    if record["kind"] == "point":
        from backend.public_report import build_public_run_csv, build_public_run_pdf
        source = record.get("source") or {}
        source = {**source, "summary": {**source.get("summary", {}), "thermal": result}}
        arguments = dict(project=record["config"], request={"resolved_config": record["config"]}, result=source,
                         material={}, manifest={"run_id": identity, "project_name": record.get("design_name", "Motor")})
        content = build_public_run_csv(**arguments) if kind == "csv" else build_public_run_pdf(**arguments)
        media = "text/csv" if kind == "csv" else "application/pdf"
    elif kind == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["section", "field", "unit", "value", "sample_index"])
        writer.writerows(thermal_csv_rows(record))
        content, media = output.getvalue().encode(), "text/csv"
    else:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=42.52, rightMargin=42.52,
                                title="coilEM thermal analysis", author="coilEM")
        doc.build(thermal_story(result, rating=record["kind"] == "rating"))
        content, media = output.getvalue(), "application/pdf"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="thermal-{identity}.{kind}"'})
