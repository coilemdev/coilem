"""Shared airgap field sampling helpers."""

from __future__ import annotations

import math
from typing import Any

from backend.field_lines import generate_element_b_components

DEFAULT_AIRGAP_RING_SAMPLE_COUNT = 36


def airgap_band_radii_from_mesh_info(mesh_info: dict[str, Any] | None) -> tuple[float, float] | None:
    """Return the physical airgap band radii in mm from mesh metadata."""
    if not isinstance(mesh_info, dict):
        return None

    inner = _finite_positive(mesh_info.get("airgap_inner_radius_mm"))
    outer = _finite_positive(mesh_info.get("airgap_outer_radius_mm"))
    if inner is None:
        inner = _finite_positive(mesh_info.get("magnet_outer_radius_mm"))
    if outer is None:
        outer = _finite_positive(mesh_info.get("stator_inner_radius_mm"))
    if inner is None or outer is None or outer <= inner:
        return None
    return inner, outer


def sample_airgap_midpoint_records_from_mesh(
    *,
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    regions: list[Any],
    element_bx_t: list[Any] | None = None,
    element_by_t: list[Any] | None = None,
    az_nodal: list[Any] | None = None,
    airgap_inner_radius_mm: float,
    airgap_outer_radius_mm: float,
    sample_count: int = DEFAULT_AIRGAP_RING_SAMPLE_COUNT,
    span_deg: float = 360.0,
) -> dict[str, list[float]] | None:
    """Sample B on a fixed ring at the airgap midpoint radius.

    The returned shape intentionally matches AirgapFieldRecords, even though the
    coordinate arrays hold sample points rather than triangle centroids. This
    keeps existing artifact and frontend plumbing unchanged while giving
    validation code a point-sampling contract shared by FEMM and Magneto2D.
    """
    if (
        not nodes_mm
        or not triangles
        or not regions
        or sample_count <= 0
        or airgap_outer_radius_mm <= airgap_inner_radius_mm
    ):
        return None

    bx_values = list(element_bx_t or [])
    by_values = list(element_by_t or [])
    if (
        (len(bx_values) != len(triangles) or len(by_values) != len(triangles))
        and az_nodal
    ):
        bx_values, by_values = generate_element_b_components(
            nodes_mm,
            triangles,
            list(az_nodal),
        )
    if len(bx_values) != len(triangles) or len(by_values) != len(triangles):
        return None

    candidates = _airgap_triangle_candidates(nodes_mm, triangles, regions)
    if not candidates:
        return None

    radius_mm = 0.5 * (float(airgap_inner_radius_mm) + float(airgap_outer_radius_mm))
    try:
        span_value = float(span_deg)
    except (TypeError, ValueError):
        span_value = 360.0
    normalized_span_deg = max(1.0, min(360.0, span_value if math.isfinite(span_value) else 360.0))
    centroid_x: list[float] = []
    centroid_y: list[float] = []
    b_mag: list[float] = []
    b_radial: list[float] = []
    b_tangential: list[float] = []

    for sample_idx in range(sample_count):
        theta = math.radians(sample_idx * normalized_span_deg / sample_count)
        x_mm = radius_mm * math.cos(theta)
        y_mm = radius_mm * math.sin(theta)
        match = _find_containing_airgap_triangle((x_mm, y_mm), candidates)
        if match is None:
            return None

        tri_idx = int(match["triangle_index"])
        try:
            bx = float(bx_values[tri_idx])
            by = float(by_values[tri_idx])
        except (IndexError, TypeError, ValueError):
            return None
        if not math.isfinite(bx) or not math.isfinite(by):
            return None

        br = bx * math.cos(theta) + by * math.sin(theta)
        bt = -bx * math.sin(theta) + by * math.cos(theta)
        if not math.isfinite(br) or not math.isfinite(bt):
            return None

        centroid_x.append(x_mm)
        centroid_y.append(y_mm)
        b_mag.append(math.hypot(bx, by))
        b_radial.append(br)
        b_tangential.append(bt)

    return {
        "centroid_x_mm": centroid_x,
        "centroid_y_mm": centroid_y,
        "b_magnitude_t": b_mag,
        "b_radial_t": b_radial,
        "b_tangential_t": b_tangential,
    }


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _airgap_triangle_candidates(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    regions: list[Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    node_count = len(nodes_mm)
    for tri_idx, tri in enumerate(triangles):
        if tri_idx >= len(regions) or str(regions[tri_idx]).lower() != "airgap":
            continue
        if len(tri) != 3:
            continue
        try:
            indices = [int(tri[0]), int(tri[1]), int(tri[2])]
        except (TypeError, ValueError):
            continue
        if any(index < 0 or index >= node_count for index in indices):
            continue
        try:
            coords = [
                (float(nodes_mm[index][0]), float(nodes_mm[index][1]))
                for index in indices
            ]
        except (IndexError, TypeError, ValueError):
            continue
        xs = [coord[0] for coord in coords]
        ys = [coord[1] for coord in coords]
        candidates.append(
            {
                "coords": coords,
                "bbox": (min(xs), max(xs), min(ys), max(ys)),
                "triangle_index": tri_idx,
            }
        )
    return candidates


def _find_containing_airgap_triangle(
    point_mm: tuple[float, float],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    x_mm, y_mm = point_mm
    pad_mm = 1.0e-7
    for candidate in candidates:
        xmin, xmax, ymin, ymax = candidate["bbox"]
        if (
            x_mm < xmin - pad_mm
            or x_mm > xmax + pad_mm
            or y_mm < ymin - pad_mm
            or y_mm > ymax + pad_mm
        ):
            continue
        if _barycentric_weights(point_mm, candidate["coords"]) is not None:
            return candidate
    return None


def _barycentric_weights(
    point_mm: tuple[float, float],
    coords: list[tuple[float, float]],
) -> tuple[float, float, float] | None:
    px, py = point_mm
    (x1, y1), (x2, y2), (x3, y3) = coords
    det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(det) <= 1.0e-18:
        return None
    w1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / det
    w2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / det
    w3 = 1.0 - w1 - w2
    tol = 1.0e-9
    if w1 < -tol or w2 < -tol or w3 < -tol:
        return None
    if w1 > 1.0 + tol or w2 > 1.0 + tol or w3 > 1.0 + tol:
        return None
    return w1, w2, w3
