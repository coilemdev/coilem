"""Native solver progress parsing and streamed field results."""

from __future__ import annotations

import json
from math import isfinite
from typing import Any

from backend.field_lines import (
    generate_contour_levels,
    generate_contour_segments,
    generate_element_b_components,
    generate_element_b_magnitudes,
)

from ._state import (
    LIVE_FIELD_CONTOUR_BANDS_PER_SIDE,
    LIVE_FIELD_FRAME_PREFIX,
    LIVE_FIELD_MESH_PREFIX,
    SOLVE_CONTEXT_PREFIX,
    SOLVE_ITERATION_PROGRESS_PREFIX,
    SWEEP_PROGRESS_RE,
)


def _parse_sweep_progress(
    line: str,
) -> tuple[int, int, float, float | None, float | None, float | None, float | None] | None:
    """Parse one stderr progress line from the Rust sweep loop.

    Returns:
        (position, total, torque_Nm, elec_deg_or_None, psi_a_or_None,
         psi_b_or_None, psi_c_or_None)

    The angle is None when older CLI builds omit the `elec=` field from the
    progress line. The flux-linkage terms are optional for backward
    compatibility with older binaries that only streamed torque.
    """
    match = SWEEP_PROGRESS_RE.search(line)
    if not match:
        return None

    elec_str = match.group("elec_deg")
    elec_deg = float(elec_str) if elec_str is not None else None
    psi_a_str = match.group("psi_a")
    psi_b_str = match.group("psi_b")
    psi_c_str = match.group("psi_c")

    return (
        int(match.group("position")),
        int(match.group("total")),
        float(match.group("torque")),
        elec_deg,
        float(psi_a_str) if psi_a_str is not None else None,
        float(psi_b_str) if psi_b_str is not None else None,
        float(psi_c_str) if psi_c_str is not None else None,
    )


def _pack_live_float(value: Any, significant_digits: int = 6) -> Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not isfinite(numeric):
        return value
    return float(f"{numeric:.{significant_digits}g}")


def _pack_live_float_list(values: list[Any], significant_digits: int = 6) -> list[Any]:
    return [_pack_live_float(value, significant_digits) for value in values]


def _pack_live_segment(segment: list[Any]) -> list[Any]:
    return [_pack_live_float(value, 7) for value in segment]


def _pack_live_contours(contours: list[Any]) -> list[dict[str, Any]]:
    packed: list[dict[str, Any]] = []
    for contour in contours:
        segments = contour.segments_mm
        packed.append(
            {
                "level": _pack_live_float(contour.level),
                "segments_mm": [_pack_live_segment(segment) for segment in segments],
                "segment_b_mag_t": _pack_live_float_list(contour.segment_b_mag_t),
                "segment_bx_t": _pack_live_float_list(contour.segment_bx_t),
                "segment_by_t": _pack_live_float_list(contour.segment_by_t),
            }
        )
    return packed


def _parse_live_field_mesh(line: str) -> dict[str, Any] | None:
    """Parse the one-per-fixed-mesh live field mesh payload from Rust."""
    stripped = line.strip()
    if not stripped.startswith(LIVE_FIELD_MESH_PREFIX):
        return None

    raw_payload = stripped[len(LIVE_FIELD_MESH_PREFIX) :]
    try:
        mesh = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(mesh, dict):
        return None

    nodes_mm = mesh.get("nodes_mm")
    triangles = mesh.get("triangles")
    if not nodes_mm or not triangles:
        return None
    return mesh


def _build_live_field_plot_payload(
    raw_plot: Any,
    field_mesh: dict[str, Any] | None = None,
    *,
    include_static_mesh: bool = True,
) -> dict[str, Any] | None:
    """Build frontend contour payload for a streamed Rust field plot."""
    if not isinstance(raw_plot, dict):
        return None

    try:
        az_nodal = raw_plot["az_nodal"]
    except (KeyError, TypeError):
        return None

    nodes_mm = raw_plot.get("nodes_mm")
    triangles = raw_plot.get("triangles")
    if (not nodes_mm or not triangles) and field_mesh is not None:
        nodes_mm = field_mesh.get("nodes_mm")
        triangles = field_mesh.get("triangles")

    if not nodes_mm or not triangles or not az_nodal:
        return None

    try:
        contour_levels = generate_contour_levels(
            az_nodal,
            bands_per_side=LIVE_FIELD_CONTOUR_BANDS_PER_SIDE,
            nodes_mm=nodes_mm,
            triangles=triangles,
        )
        contours = generate_contour_segments(
            nodes_mm,
            triangles,
            az_nodal,
            contour_levels,
        )
        element_b_mag_t = generate_element_b_magnitudes(nodes_mm, triangles, az_nodal)
        element_bx_t, element_by_t = generate_element_b_components(nodes_mm, triangles, az_nodal)
        az_min = min(az_nodal)
        az_max = max(az_nodal)
    except (IndexError, TypeError, ValueError):
        return None

    regions = raw_plot.get("regions")
    if regions is None and include_static_mesh and field_mesh is not None:
        regions = field_mesh.get("regions")
    n_pole_pitches = raw_plot.get("n_pole_pitches")
    if n_pole_pitches is None and field_mesh is not None:
        n_pole_pitches = field_mesh.get("n_pole_pitches")
    total_span_deg = raw_plot.get("total_span_deg")
    if total_span_deg is None and field_mesh is not None:
        total_span_deg = field_mesh.get("total_span_deg")

    payload = {
        "contour_levels": _pack_live_contours(contours),
        "element_b_mag_t": _pack_live_float_list(element_b_mag_t),
        "element_bx_t": _pack_live_float_list(element_bx_t),
        "element_by_t": _pack_live_float_list(element_by_t),
        "az_min": _pack_live_float(az_min),
        "az_max": _pack_live_float(az_max),
        "n_pole_pitches": n_pole_pitches,
        "total_span_deg": total_span_deg,
    }
    if include_static_mesh or field_mesh is None:
        payload["nodes_mm"] = nodes_mm
        payload["triangles"] = triangles
    if regions is not None:
        payload["regions"] = regions or []
    return payload


def _parse_live_field_frame(
    line: str,
    field_mesh: dict[str, Any] | None = None,
    *,
    include_static_mesh: bool = True,
) -> tuple[int, int, float, dict[str, Any]] | None:
    """Parse streamed loaded + no-load A_z contour payloads from the Rust sweep loop."""
    stripped = line.strip()
    if not stripped.startswith(LIVE_FIELD_FRAME_PREFIX):
        return None

    raw_payload = stripped[len(LIVE_FIELD_FRAME_PREFIX) :]
    try:
        frame = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None

    try:
        position = int(frame["position"])
        total = int(frame["total"])
        angle_deg = float(frame["angle_deg"])
        raw_plot = frame["field_plot"]
    except (KeyError, TypeError, ValueError):
        return None

    loaded_plot = _build_live_field_plot_payload(
        raw_plot,
        field_mesh,
        include_static_mesh=include_static_mesh,
    )
    if loaded_plot is None:
        return None

    payload = {
        "angle_deg": angle_deg,
        **loaded_plot,
    }
    config_summary = frame.get("config_summary")
    if config_summary is None and include_static_mesh and field_mesh is not None:
        config_summary = field_mesh.get("config_summary")
    if config_summary is not None:
        payload["config_summary"] = config_summary

    mesh_info = frame.get("mesh_info")
    if mesh_info is None and include_static_mesh and field_mesh is not None:
        mesh_info = field_mesh.get("mesh_info")
    if mesh_info is not None:
        payload["mesh_info"] = mesh_info

    airgap_brbt = frame.get("airgap_brbt")
    if isinstance(airgap_brbt, dict):
        payload["airgap_brbt"] = airgap_brbt

    noload_plot = _build_live_field_plot_payload(
        frame.get("noload_field_plot"),
        field_mesh,
        include_static_mesh=False,
    )
    if noload_plot is not None:
        payload["noload_plot"] = noload_plot

    return (
        position,
        total,
        angle_deg,
        payload,
    )


def _parse_solve_iteration_progress(line: str) -> dict[str, Any] | None:
    """Parse one streamed nonlinear-iteration progress payload from Rust."""
    stripped = line.strip()
    if not stripped.startswith(SOLVE_ITERATION_PROGRESS_PREFIX):
        return None

    raw_payload = stripped[len(SOLVE_ITERATION_PROGRESS_PREFIX) :]
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    try:
        payload["completed_positions"] = int(payload.get("completed_positions", 0))
        payload["total_positions"] = int(payload.get("total_positions", 0))
        payload["position_index"] = int(payload.get("position_index", 0))
        payload["iteration"] = int(payload.get("iteration", 0))
        payload["max_iterations"] = int(payload.get("max_iterations", 0))
    except (TypeError, ValueError):
        return None
    if payload["total_positions"] <= 0:
        return None
    return payload


def _parse_solve_context(line: str) -> dict[str, Any] | None:
    """Parse the current Rust angle/iteration context for readable logs."""
    stripped = line.strip()
    if not stripped.startswith(SOLVE_CONTEXT_PREFIX):
        return None

    raw_payload = stripped[len(SOLVE_CONTEXT_PREFIX) :]
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    for key in ("completed_positions", "total_positions", "position_index", "iteration", "max_iterations"):
        try:
            payload[key] = int(payload.get(key, 0))
        except (TypeError, ValueError):
            payload[key] = 0
    return payload


def _magneto2d_step_label(solve_kind: object) -> str:
    if solve_kind == "loaded":
        return "Loaded field"
    if solve_kind == "no_load":
        return "No-load EMF"
    if solve_kind == "cogging":
        return "Cogging sweep"
    return "Field solve"


def _format_magneto2d_context(context: dict[str, Any] | None) -> str:
    if not context:
        return ""

    parts = [f"step={_magneto2d_step_label(context.get('solve_kind'))}"]
    position = context.get("position_index")
    total = context.get("total_positions")
    if isinstance(position, int) and isinstance(total, int) and position > 0 and total > 0:
        parts.append(f"pos={position}/{total}")

    iteration = context.get("iteration")
    max_iterations = context.get("max_iterations")
    if isinstance(iteration, int) and isinstance(max_iterations, int) and iteration > 0 and max_iterations > 0:
        parts.append(f"picard={iteration}/{max_iterations}")

    elec_deg = context.get("elec_deg")
    if isinstance(elec_deg, (int, float)) and isfinite(float(elec_deg)):
        parts.append(f"elec={float(elec_deg):.1f}deg")

    return " ".join(parts)


def _format_magneto2d_solver_line(line: str, context: dict[str, Any] | None) -> str:
    context_prefix = _format_magneto2d_context(context)
    if not context_prefix:
        return line
    return f"{context_prefix} | {line.lstrip()}"


def _is_magneto2d_step_diagnostic(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(
        (
            "pcg:",
            "asm=",
            "nonlinear_cfg:",
            "magnet_subelement:",
            "contour MST",
            "mst per-quadrant:",
            "mst(A_z) per-quadrant:",
        )
    )


def _format_field_preview_log(position: int, total: int, elec_deg: float | None) -> str:
    parts = ["step=Field preview"]
    if position > 0 and total > 0:
        parts.append(f"pos={position}/{total}")
    if elec_deg is not None and isfinite(float(elec_deg)):
        parts.append(f"elec={float(elec_deg):.1f}deg")
    parts.append("| live frame generated")
    return " ".join(parts)
