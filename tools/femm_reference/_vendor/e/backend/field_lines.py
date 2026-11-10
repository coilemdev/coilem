"""Helpers for building deterministic field-line overlays from nodal A_z."""

from __future__ import annotations

import math
from typing import Any

from backend.models import FieldLineContourLevel, FieldLinePlot, MeshConfigSummary, MeshPlotInfo


def _dedupe_points(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    unique: list[tuple[float, float]] = []
    for point in points:
        if not any(abs(point[0] - existing[0]) <= tol and abs(point[1] - existing[1]) <= tol for existing in unique):
            unique.append(point)
    return unique


def _farthest_point_pair(points: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    best_pair: tuple[tuple[float, float], tuple[float, float]] | None = None
    best_dist_sq = -1.0
    for left_index, left_point in enumerate(points):
        for right_point in points[left_index + 1 :]:
            dx = left_point[0] - right_point[0]
            dy = left_point[1] - right_point[1]
            dist_sq = dx * dx + dy * dy
            if dist_sq > best_dist_sq:
                best_dist_sq = dist_sq
                best_pair = (left_point, right_point)
    return best_pair


def _uniform_levels(az_min: float, az_max: float, level_count: int) -> list[float]:
    span = az_max - az_min
    return [
        az_min + span * index / (level_count + 1)
        for index in range(1, level_count + 1)
    ]


def _dedupe_levels(levels: list[float], *, span: float) -> list[float]:
    tolerance = max(abs(span) * 1e-7, 1e-12)
    deduped: list[float] = []
    for level in sorted(level for level in levels if math.isfinite(level)):
        if not deduped or abs(level - deduped[-1]) > tolerance:
            deduped.append(level)
    return deduped


def _weighted_quantile_levels(
    weighted_values: list[tuple[float, float]],
    level_count: int,
    *,
    low_quantile: float = 0.08,
    high_quantile: float = 0.96,
) -> list[float]:
    samples = sorted(
        (float(value), float(weight))
        for value, weight in weighted_values
        if math.isfinite(float(value)) and math.isfinite(float(weight)) and float(weight) > 0.0
    )
    if not samples or level_count <= 0:
        return []

    total_weight = sum(weight for _, weight in samples)
    if total_weight <= 0:
        return []

    levels: list[float] = []
    cursor = 0
    cumulative = 0.0
    quantile_span = max(0.0, high_quantile - low_quantile)
    for index in range(1, level_count + 1):
        quantile = low_quantile + quantile_span * index / (level_count + 1)
        target = quantile * total_weight
        while cursor < len(samples) - 1 and cumulative + samples[cursor][1] < target:
            cumulative += samples[cursor][1]
            cursor += 1
        levels.append(samples[cursor][0])
    return levels


def _triangle_area_weighted_az_values(
    nodes_mm: list[list[float]] | None,
    triangles: list[list[int]] | None,
    az_nodal: list[float],
) -> list[tuple[float, float]]:
    if not nodes_mm or not triangles:
        return []

    weighted_values: list[tuple[float, float]] = []
    for tri in triangles:
        if len(tri) != 3:
            continue
        try:
            i, j, k = tri
            xi, yi = float(nodes_mm[i][0]), float(nodes_mm[i][1])
            xj, yj = float(nodes_mm[j][0]), float(nodes_mm[j][1])
            xk, yk = float(nodes_mm[k][0]), float(nodes_mm[k][1])
            ai = float(az_nodal[i])
            aj = float(az_nodal[j])
            ak = float(az_nodal[k])
        except (IndexError, TypeError, ValueError):
            continue

        area = abs((xj - xi) * (yk - yi) - (xk - xi) * (yj - yi)) * 0.5
        value = (ai + aj + ak) / 3.0
        if area > 0 and math.isfinite(value):
            weighted_values.append((value, area))
    return weighted_values


def generate_contour_levels(
    az_nodal: list[float],
    bands_per_side: int = 8,
    *,
    nodes_mm: list[list[float]] | None = None,
    triangles: list[list[int]] | None = None,
) -> list[float]:
    """Generate interior A_z contour levels with full-range and spatial coverage."""
    finite_values: list[float] = []
    for value in az_nodal:
        try:
            value_float = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value_float):
            finite_values.append(value_float)
    if not finite_values:
        return []

    az_min = min(finite_values)
    az_max = max(finite_values)
    span = az_max - az_min
    if span <= 1e-12:
        return []

    level_count = max(2, bands_per_side * 2)
    unique_values = _dedupe_levels(finite_values, span=span)
    if len(unique_values) <= 2:
        return _uniform_levels(az_min, az_max, level_count)

    uniform_count = max(2, level_count // 2)
    distribution_count = max(0, level_count - uniform_count)
    levels = _uniform_levels(az_min, az_max, uniform_count)

    if distribution_count > 0:
        weighted_values = _triangle_area_weighted_az_values(nodes_mm, triangles, az_nodal)
        if not weighted_values:
            weighted_values = [(value, 1.0) for value in finite_values]
        levels.extend(_weighted_quantile_levels(weighted_values, distribution_count))

    deduped = _dedupe_levels(levels, span=span)
    if len(deduped) < level_count:
        deduped = _dedupe_levels(
            deduped + _uniform_levels(az_min, az_max, level_count),
            span=span,
        )
    return deduped


def _triangle_b_components_t(
    nodes_mm: list[list[float]],
    az_nodal: list[float],
    i: int,
    j: int,
    k: int,
) -> tuple[float, float]:
    """Return element-constant (B_x, B_y) for a linear A_z triangle."""
    try:
        xi, yi = (float(nodes_mm[i][0]) * 1e-3, float(nodes_mm[i][1]) * 1e-3)
        xj, yj = (float(nodes_mm[j][0]) * 1e-3, float(nodes_mm[j][1]) * 1e-3)
        xk, yk = (float(nodes_mm[k][0]) * 1e-3, float(nodes_mm[k][1]) * 1e-3)
        ai = float(az_nodal[i])
        aj = float(az_nodal[j])
        ak = float(az_nodal[k])
    except (IndexError, TypeError, ValueError):
        return 0.0, 0.0

    double_area = (xj - xi) * (yk - yi) - (xk - xi) * (yj - yi)
    if abs(double_area) <= 1e-30:
        return 0.0, 0.0

    da_dx = (ai * (yj - yk) + aj * (yk - yi) + ak * (yi - yj)) / double_area
    da_dy = (ai * (xk - xj) + aj * (xi - xk) + ak * (xj - xi)) / double_area
    bx = da_dy
    by = -da_dx
    if not math.isfinite(bx) or not math.isfinite(by):
        return 0.0, 0.0
    return bx, by


def _triangle_b_magnitude_t(
    nodes_mm: list[list[float]],
    az_nodal: list[float],
    i: int,
    j: int,
    k: int,
) -> float:
    """Return element-constant |B| for a linear A_z triangle."""
    bx, by = _triangle_b_components_t(nodes_mm, az_nodal, i, j, k)
    b_mag = math.hypot(bx, by)
    return b_mag if math.isfinite(b_mag) else 0.0


def generate_element_b_magnitudes(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
) -> list[float]:
    """Return element-constant |B| in Tesla for each linear A_z triangle."""
    if not nodes_mm or not triangles or not az_nodal:
        return []

    return [
        _triangle_b_magnitude_t(nodes_mm, az_nodal, tri[0], tri[1], tri[2])
        if len(tri) == 3
        else 0.0
        for tri in triangles
    ]


def generate_element_b_components(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
) -> tuple[list[float], list[float]]:
    """Return element-constant B_x and B_y in Tesla, aligned with triangles."""
    if not nodes_mm or not triangles or not az_nodal:
        return [], []

    bx_values: list[float] = []
    by_values: list[float] = []
    for tri in triangles:
        bx, by = (
            _triangle_b_components_t(nodes_mm, az_nodal, tri[0], tri[1], tri[2])
            if len(tri) == 3
            else (0.0, 0.0)
        )
        bx_values.append(bx)
        by_values.append(by)
    return bx_values, by_values


def generate_contour_segments(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
    levels: list[float],
) -> list[FieldLineContourLevel]:
    """Generate contour segments for each requested A_z level on a triangle mesh."""
    if not nodes_mm or not triangles or not az_nodal or not levels:
        return []

    max_abs = max(abs(value) for value in az_nodal) if az_nodal else 0.0
    value_tol = max(max_abs * 1e-9, 1e-12)
    point_tol = 1e-7
    contours: list[FieldLineContourLevel] = []
    triangle_bx_t, triangle_by_t = generate_element_b_components(nodes_mm, triangles, az_nodal)
    triangle_b_mag_t = [
        math.hypot(bx, by)
        if math.isfinite(bx) and math.isfinite(by)
        else 0.0
        for bx, by in zip(triangle_bx_t, triangle_by_t)
    ]

    for level in levels:
        segments_mm: list[list[float]] = []
        segment_b_mag_t: list[float] = []
        segment_bx_t: list[float] = []
        segment_by_t: list[float] = []

        for tri_idx, tri in enumerate(triangles):
            if len(tri) != 3:
                continue

            i, j, k = tri
            tri_points = [nodes_mm[i], nodes_mm[j], nodes_mm[k]]
            tri_values = [az_nodal[i], az_nodal[j], az_nodal[k]]
            if all(abs(value - level) <= value_tol for value in tri_values):
                continue

            intersections: list[tuple[float, float]] = []

            for start, end in ((0, 1), (1, 2), (2, 0)):
                v1 = tri_values[start] - level
                v2 = tri_values[end] - level
                p1 = tri_points[start]
                p2 = tri_points[end]

                if abs(v1) <= value_tol and abs(v2) <= value_tol:
                    intersections.append((float(p1[0]), float(p1[1])))
                    intersections.append((float(p2[0]), float(p2[1])))
                    continue
                if abs(v1) <= value_tol:
                    intersections.append((float(p1[0]), float(p1[1])))
                    continue
                if abs(v2) <= value_tol:
                    intersections.append((float(p2[0]), float(p2[1])))
                    continue
                if (v1 > 0) == (v2 > 0):
                    continue

                t = v1 / (v1 - v2)
                x = p1[0] + t * (p2[0] - p1[0])
                y = p1[1] + t * (p2[1] - p1[1])
                intersections.append((float(x), float(y)))

            unique_points = _dedupe_points(intersections, point_tol)
            if len(unique_points) < 2:
                continue
            if len(unique_points) > 2:
                farthest_pair = _farthest_point_pair(unique_points)
                if farthest_pair is None:
                    continue
                unique_points = [farthest_pair[0], farthest_pair[1]]

            (x1, y1), (x2, y2) = unique_points
            segments_mm.append([x1, y1, x2, y2])
            segment_b_mag_t.append(triangle_b_mag_t[tri_idx])
            segment_bx_t.append(triangle_bx_t[tri_idx])
            segment_by_t.append(triangle_by_t[tri_idx])

        contours.append(
            FieldLineContourLevel(
                level=level,
                segments_mm=segments_mm,
                segment_b_mag_t=segment_b_mag_t,
                segment_bx_t=segment_bx_t,
                segment_by_t=segment_by_t,
            )
        )

    return contours


def build_field_line_plot(raw_report: dict[str, Any]) -> FieldLinePlot | None:
    """Build a SolveResult-ready field-line payload from a raw magneto2d report."""
    raw_plot = raw_report.get("field_plot")
    if not raw_plot:
        return None

    nodes_mm = raw_plot.get("nodes_mm") or []
    triangles = raw_plot.get("triangles") or []
    regions = raw_plot.get("regions") or []
    az_nodal = raw_plot.get("az_nodal") or []
    if not nodes_mm or not triangles or not regions or not az_nodal:
        return None

    mesh_info = raw_report.get("mesh_info") or {}
    config_summary = raw_report.get("config_summary") or {}
    element_b_mag_t = generate_element_b_magnitudes(nodes_mm, triangles, az_nodal)
    element_bx_t, element_by_t = generate_element_b_components(nodes_mm, triangles, az_nodal)
    contour_levels = generate_contour_levels(
        az_nodal,
        nodes_mm=nodes_mm,
        triangles=triangles,
    )
    contours = generate_contour_segments(nodes_mm, triangles, az_nodal, contour_levels)

    return FieldLinePlot(
        config_summary=MeshConfigSummary(
            topology=config_summary["topology"],
            slots=config_summary["slots"],
            poles=config_summary["poles"],
            stator_od_mm=config_summary["stator_od_mm"],
            rotor_od_mm=config_summary["rotor_od_mm"],
            magnet_thickness_mm=config_summary["magnet_thickness_mm"],
            stack_length_mm=config_summary["stack_length_mm"],
        ),
        mesh_info=MeshPlotInfo(
            num_nodes=mesh_info["num_nodes"],
            num_triangles=mesh_info["num_triangles"],
            pole_pitch_deg=mesh_info["pole_pitch_deg"],
            n_pole_pitches=mesh_info["n_pole_pitches"],
            total_span_deg=mesh_info["total_span_deg"],
        ),
        nodes_mm=nodes_mm,
        triangles=triangles,
        regions=regions,
        element_b_mag_t=element_b_mag_t,
        element_bx_t=element_bx_t,
        element_by_t=element_by_t,
        contour_levels=contours,
        az_min=min(az_nodal),
        az_max=max(az_nodal),
        n_pole_pitches=raw_plot.get("n_pole_pitches", mesh_info["n_pole_pitches"]),
        total_span_deg=raw_plot.get("total_span_deg", mesh_info["total_span_deg"]),
    )


def build_field_line_plot_from_mesh(
    *,
    config_summary: dict[str, Any],
    mesh_info: dict[str, Any],
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    regions: list[str],
    az_nodal: list[float],
    n_pole_pitches: int,
    total_span_deg: float,
) -> FieldLinePlot | None:
    """Build a FieldLinePlot from explicit mesh + nodal A_z data."""
    if not nodes_mm or not triangles or not regions or not az_nodal:
        return None

    element_b_mag_t = generate_element_b_magnitudes(nodes_mm, triangles, az_nodal)
    element_bx_t, element_by_t = generate_element_b_components(nodes_mm, triangles, az_nodal)
    contour_levels = generate_contour_levels(
        az_nodal,
        nodes_mm=nodes_mm,
        triangles=triangles,
    )
    contours = generate_contour_segments(nodes_mm, triangles, az_nodal, contour_levels)

    return FieldLinePlot(
        config_summary=MeshConfigSummary(
            topology=config_summary["topology"],
            slots=config_summary["slots"],
            poles=config_summary["poles"],
            stator_od_mm=config_summary["stator_od_mm"],
            rotor_od_mm=config_summary["rotor_od_mm"],
            magnet_thickness_mm=config_summary["magnet_thickness_mm"],
            stack_length_mm=config_summary["stack_length_mm"],
        ),
        mesh_info=MeshPlotInfo(
            num_nodes=mesh_info["num_nodes"],
            num_triangles=mesh_info["num_triangles"],
            pole_pitch_deg=mesh_info["pole_pitch_deg"],
            n_pole_pitches=mesh_info["n_pole_pitches"],
            total_span_deg=mesh_info["total_span_deg"],
        ),
        nodes_mm=nodes_mm,
        triangles=triangles,
        regions=regions,
        element_b_mag_t=element_b_mag_t,
        element_bx_t=element_bx_t,
        element_by_t=element_by_t,
        contour_levels=contours,
        az_min=min(az_nodal),
        az_max=max(az_nodal),
        n_pole_pitches=n_pole_pitches,
        total_span_deg=total_span_deg,
    )
