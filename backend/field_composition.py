"""On-demand, source-separated electromagnetic field solves."""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from typing import Any, Callable, Iterator

from backend.field_artifacts import resolve_solve_cache_artifact_id
from backend.models import MotorConfig, SolveOptionsConfig
from backend.solver import Magneto2DSolver

_ARMATURE_CACHE_VERSION = "armature-field-sweep-v1"
_ARMATURE_CACHE_LIMIT = 4
_armature_cache_lock = threading.Lock()
_armature_cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_armature_in_flight: dict[str, Future[dict[str, Any]]] = {}

_PM_CACHE_VERSION = "pm-field-sweep-v1"
_PM_CACHE_LIMIT = 4
_pm_cache_lock = threading.Lock()
_pm_cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_pm_in_flight: dict[str, Future[dict[str, Any]]] = {}


def armature_field_cache_key(
    config: MotorConfig,
    solve_mesh_key: str | None = None,
    *,
    clockwise_positive: bool = False,
) -> str:
    """Hash the design, operating point, mesh policy, and requested angle grid."""

    payload = {
        "version": _ARMATURE_CACHE_VERSION,
        "config": config.model_dump(mode="json", exclude_none=True),
        "solve_mesh_key": solve_mesh_key,
        "rotation_convention": (
            "clockwise_positive_ui"
            if clockwise_positive
            else "counterclockwise_positive_solver"
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def pm_field_cache_key(config: MotorConfig, solve_mesh_key: str | None = None) -> str:
    """Hash the design, mesh policy, and angle grid for a PM-only sweep."""

    payload = {
        "version": _PM_CACHE_VERSION,
        "config": config.model_dump(mode="json", exclude_none=True),
        "solve_mesh_key": solve_mesh_key,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_armature_only_config(config: MotorConfig) -> MotorConfig:
    """Clone a normal solve config into a loaded, Br=0 field-only sweep.

    The original loaded angle grid is frozen into a custom sweep before
    Back-EMF is disabled. This avoids running a redundant zero-current leg
    while keeping Armature samples aligned with Resultant samples.
    """

    if config.solve_params is None:
        raise ValueError("solve_params is required for a stator-current field solve")
    if config.solve_params.current_amplitude_A <= 0.0:
        raise ValueError("stator-current field requires a non-zero phase current")

    # Local import avoids widening the backend model module's dependency graph.
    from backend.magneto2d_adapter import (
        estimate_magneto2d_sweep_positions,
        estimate_magneto2d_sweep_span_deg,
    )

    positions = estimate_magneto2d_sweep_positions(config)
    span_deg = estimate_magneto2d_sweep_span_deg(config)
    if span_deg >= 360.0 - 1e-6:
        step_deg = span_deg / max(1, positions)
    else:
        step_deg = span_deg / max(1, positions - 1)

    armature = config.model_copy(deep=True)
    assert armature.solve_params is not None
    armature.solve_params.solve_quality = "custom"
    armature.solve_params.rotor_sweep_range_deg = float(span_deg)
    armature.solve_params.rotor_step_deg = float(step_deg)
    armature.solve_params.stream_noload_field_lines = False
    armature.solve_params.field_composition_source = "armature"
    armature.solve_options = SolveOptionsConfig(
        torque_sweep=True,
        back_emf=False,
        flux_density=True,
        cogging_torque=False,
        torque_speed_envelope=False,
        thd_analysis=False,
    )
    return armature


def build_pm_only_config(config: MotorConfig) -> MotorConfig:
    """Clone a normal solve config into an unloaded, magnets-energized sweep.

    The loaded angle grid is frozen into a custom sweep before the phase
    current is zeroed so PM-only samples align with Resultant samples.
    """

    if config.solve_params is None:
        raise ValueError("solve_params is required for a PM-only field solve")

    # Local import avoids widening the backend model module's dependency graph.
    from backend.magneto2d_adapter import (
        estimate_magneto2d_sweep_positions,
        estimate_magneto2d_sweep_span_deg,
    )

    positions = estimate_magneto2d_sweep_positions(config)
    span_deg = estimate_magneto2d_sweep_span_deg(config)
    if span_deg >= 360.0 - 1e-6:
        step_deg = span_deg / max(1, positions)
    else:
        step_deg = span_deg / max(1, positions - 1)

    pm_only = config.model_copy(deep=True)
    assert pm_only.solve_params is not None
    pm_only.solve_params.solve_quality = "custom"
    pm_only.solve_params.rotor_sweep_range_deg = float(span_deg)
    pm_only.solve_params.rotor_step_deg = float(step_deg)
    pm_only.solve_params.current_amplitude_A = 0.0
    pm_only.solve_params.stream_noload_field_lines = False
    pm_only.solve_params.field_composition_source = "resultant"
    pm_only.solve_options = SolveOptionsConfig(
        torque_sweep=True,
        back_emf=False,
        flux_density=True,
        cogging_torque=False,
        torque_speed_envelope=False,
        thd_analysis=False,
    )
    return pm_only


def _hydrate_armature_frame_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """Hydrate contours offloaded by the normal solve-result artifact policy."""

    if payload.get("contour_levels"):
        return payload
    artifact = payload.get("field_frame_artifact") or payload.get("full_field_frame_artifact")
    artifact_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
    if not isinstance(artifact_id, str) or not artifact_id:
        return payload
    try:
        path = resolve_solve_cache_artifact_id(artifact_id)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            artifact_payload = json.load(fh)
        full_frame = artifact_payload.get("field_line_frame")
        if not isinstance(full_frame, dict):
            return payload
        return {**payload, **full_frame}
    except (OSError, ValueError, json.JSONDecodeError):
        return payload


def _slim_armature_frame(frame: Any) -> dict[str, Any]:
    payload = frame.model_dump(mode="json") if hasattr(frame, "model_dump") else dict(frame)
    payload = _hydrate_armature_frame_artifact(payload)
    # Contours and airgap records are the exact values the UI needs. The
    # repeated solve mesh and per-element arrays stay in the normal artifact
    # cache to keep this one-shot HTTP response bounded.
    for key in (
        "nodes_mm",
        "triangles",
        "regions",
        "element_b_mag_t",
        "element_bx_t",
        "element_by_t",
        "noload_plot",
    ):
        payload.pop(key, None)
    return payload


def _artifact_ids(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        artifact_id = value.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            yield artifact_id
        for child in value.values():
            yield from _artifact_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _artifact_ids(child)


def _cached_artifacts_available(response: dict[str, Any]) -> bool:
    """Whether every solve-cache file a cached response references still exists.

    Rolling solve-cache cleanup can delete a directory these in-memory
    responses still point at; such an entry must be recomputed, not served.
    """

    for artifact_id in _artifact_ids(response.get("frames")):
        try:
            if not resolve_solve_cache_artifact_id(artifact_id).is_file():
                return False
        except ValueError:
            return False
    return True


def clear_armature_field_cache() -> None:
    """Clear the small in-memory response cache (used by focused tests)."""

    with _armature_cache_lock:
        _armature_cache.clear()
        _armature_in_flight.clear()


def clear_pm_field_cache() -> None:
    """Clear the small in-memory PM-only response cache (used by focused tests)."""

    with _pm_cache_lock:
        _pm_cache.clear()
        _pm_in_flight.clear()


def solve_armature_field_sweep(
    config: MotorConfig,
    *,
    solve_mesh_key: str | None = None,
    solver_factory: Callable[[], Any] = Magneto2DSolver,
    clockwise_positive: bool = False,
    on_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Run or reuse an exact permanent-magnet-remanence-disabled field sweep."""

    cache_key = armature_field_cache_key(
        config,
        solve_mesh_key,
        clockwise_positive=clockwise_positive,
    )
    owns_solve = False
    with _armature_cache_lock:
        cached = _armature_cache.get(cache_key)
        if cached is not None and not _cached_artifacts_available(cached):
            del _armature_cache[cache_key]
            cached = None
        if cached is not None:
            _armature_cache.move_to_end(cache_key)
            return {**cached, "cache_hit": True}
        pending = _armature_in_flight.get(cache_key)
        if pending is None:
            pending = Future()
            _armature_in_flight[cache_key] = pending
            owns_solve = True

    if not owns_solve:
        return {**pending.result(), "cache_hit": True}

    try:
        armature_config = build_armature_only_config(config)
        started = time.perf_counter()
        solve_kwargs: dict[str, Any] = {"solve_mesh_key": solve_mesh_key}
        if on_progress is not None:
            solve_kwargs["on_progress"] = on_progress
        result = solver_factory().solve(armature_config, **solve_kwargs)
        frames = [_slim_armature_frame(frame) for frame in (getattr(result, "field_line_frames", None) or [])]
        frames = [frame for frame in frames if frame.get("contour_levels")]
        if not frames:
            raise ValueError("stator-current solve completed without renderable field frames")

        solve_params = armature_config.solve_params
        assert solve_params is not None
        response = {
            "schema_version": "openem.field_composition.armature.v1",
            "cache_key": cache_key,
            "cache_hit": False,
            "source": "magneto2d_exact_br_zero",
            "magnet_remanence_scale": 0.0,
            "current_amplitude_A": float(solve_params.current_amplitude_A),
            "current_angle_deg": float(solve_params.current_angle_deg),
            "frame_count": len(frames),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "frames": frames,
        }
    except Exception as exc:
        with _armature_cache_lock:
            _armature_in_flight.pop(cache_key, None)
            pending.set_exception(exc)
        raise

    with _armature_cache_lock:
        _armature_cache[cache_key] = response
        _armature_cache.move_to_end(cache_key)
        while len(_armature_cache) > _ARMATURE_CACHE_LIMIT:
            _armature_cache.popitem(last=False)
        _armature_in_flight.pop(cache_key, None)
        pending.set_result(response)
    return response


def solve_pm_field_sweep(
    config: MotorConfig,
    *,
    solve_mesh_key: str | None = None,
    solver_factory: Callable[[], Any] = Magneto2DSolver,
) -> dict[str, Any]:
    """Run or reuse an exact zero-current (permanent-magnet-only) field sweep."""

    cache_key = pm_field_cache_key(config, solve_mesh_key)
    owns_solve = False
    with _pm_cache_lock:
        cached = _pm_cache.get(cache_key)
        if cached is not None and not _cached_artifacts_available(cached):
            del _pm_cache[cache_key]
            cached = None
        if cached is not None:
            _pm_cache.move_to_end(cache_key)
            return {**cached, "cache_hit": True}
        pending = _pm_in_flight.get(cache_key)
        if pending is None:
            pending = Future()
            _pm_in_flight[cache_key] = pending
            owns_solve = True

    if not owns_solve:
        return {**pending.result(), "cache_hit": True}

    try:
        pm_config = build_pm_only_config(config)
        started = time.perf_counter()
        result = solver_factory().solve(pm_config, solve_mesh_key=solve_mesh_key)
        frames = [_slim_armature_frame(frame) for frame in (getattr(result, "field_line_frames", None) or [])]
        frames = [frame for frame in frames if frame.get("contour_levels")]
        if not frames:
            raise ValueError("PM-only solve completed without renderable field frames")

        solve_params = pm_config.solve_params
        assert solve_params is not None
        response = {
            "schema_version": "openem.field_composition.pm.v1",
            "cache_key": cache_key,
            "cache_hit": False,
            "source": "magneto2d_exact_zero_current",
            "magnet_remanence_scale": 1.0,
            "current_amplitude_A": 0.0,
            "current_angle_deg": float(solve_params.current_angle_deg),
            "frame_count": len(frames),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "frames": frames,
        }
    except Exception as exc:
        with _pm_cache_lock:
            _pm_in_flight.pop(cache_key, None)
            pending.set_exception(exc)
        raise

    with _pm_cache_lock:
        _pm_cache[cache_key] = response
        _pm_cache.move_to_end(cache_key)
        while len(_pm_cache) > _PM_CACHE_LIMIT:
            _pm_cache.popitem(last=False)
        _pm_in_flight.pop(cache_key, None)
        pending.set_result(response)
    return response
