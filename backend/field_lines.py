"""Helpers for building deterministic field-line overlays from nodal A_z.

Each public generator has a numpy path and a per-triangle Python path
(``_*_python``). The numpy path repeats the Python arithmetic operation for
operation, and element-wise float64 operations round exactly like Python
floats, so both paths give bit-identical results. Sums keep their sequential
order: cumulative sums use ``np.cumsum`` (sequential), and totals use the
built-in ``sum`` on the same ordered values. Inputs where that equivalence is
not certain (non-finite or non-numeric values, ragged lists, out-of-range
triangle indices) take the Python path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.models import FieldLineContourLevel, FieldLinePlot, MeshConfigSummary, MeshPlotInfo

# Below this magnitude, integers convert to float64 exactly and the
# difference of two values is exact, so int inputs give the same results
# as Python's mixed int/float arithmetic.
_EXACT_VALUE_LIMIT = 2.0**52
_DEFAULT_BANDS_PER_SIDE = 8


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


def _contour_levels_python(
    az_nodal: list[float],
    bands_per_side: int = _DEFAULT_BANDS_PER_SIDE,
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


def _element_b_magnitudes_python(
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


def _element_b_components_python(
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


def _triangle_contour_segment(
    tri_points: list[list[float]],
    tri_values: list[float],
    level: float,
    value_tol: float,
    point_tol: float,
) -> list[float] | None:
    """Return the [x1, y1, x2, y2] segment where ``level`` crosses one triangle."""
    if all(abs(value - level) <= value_tol for value in tri_values):
        return None

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
        return None
    if len(unique_points) > 2:
        farthest_pair = _farthest_point_pair(unique_points)
        if farthest_pair is None:
            return None
        unique_points = [farthest_pair[0], farthest_pair[1]]

    (x1, y1), (x2, y2) = unique_points
    return [x1, y1, x2, y2]


def _contour_segments_python(
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
    triangle_bx_t, triangle_by_t = _element_b_components_python(nodes_mm, triangles, az_nodal)
    triangle_b_mag_t = [
        math.hypot(bx, by)
        if math.isfinite(bx) and math.isfinite(by)
        else 0.0
        for bx, by in zip(triangle_bx_t, triangle_by_t)
    ]
    # A triangle whose node values all sit more than value_tol on one side of
    # a level adds no segment for it. Testing its extremes with the same
    # subtraction the edge checks use skips it exactly, without re-testing
    # all three edges for every level. A NaN value keeps the full checks.
    value_ranges: list[tuple[float, float]] = []
    for tri in triangles:
        if len(tri) != 3:
            value_ranges.append((math.inf, -math.inf))
            continue
        tri_values = (az_nodal[tri[0]], az_nodal[tri[1]], az_nodal[tri[2]])
        if any(math.isnan(value) for value in tri_values):
            value_ranges.append((-math.inf, math.inf))
        else:
            value_ranges.append((min(tri_values), max(tri_values)))

    for level in levels:
        segments_mm: list[list[float]] = []
        segment_b_mag_t: list[float] = []
        segment_bx_t: list[float] = []
        segment_by_t: list[float] = []

        for tri_idx, tri in enumerate(triangles):
            lowest, highest = value_ranges[tri_idx]
            if highest - level < -value_tol or lowest - level > value_tol:
                continue
            if len(tri) != 3:
                continue

            i, j, k = tri
            segment = _triangle_contour_segment(
                [nodes_mm[i], nodes_mm[j], nodes_mm[k]],
                [az_nodal[i], az_nodal[j], az_nodal[k]],
                level,
                value_tol,
                point_tol,
            )
            if segment is None:
                continue

            segments_mm.append(segment)
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


@dataclass(frozen=True)
class _MeshArrays:
    """A mesh and its nodal A_z as arrays the numpy paths can use exactly."""

    nodes_mm: np.ndarray  # (n, 2) float64: x, y
    triangles: np.ndarray  # (m, 3) intp, every index valid for nodes_mm and az
    az: np.ndarray  # (k,) float64


def _exact_float_array(values: Any) -> np.ndarray | None:
    """Return finite numeric ``values`` as float64, or None if they may not convert exactly."""
    try:
        array = np.asarray(values)
    except (TypeError, ValueError):
        return None
    if array.dtype.kind not in "fiu":
        return None
    array = array.astype(np.float64)
    # NaN and inf fail this test too.
    if not np.all(np.abs(array) < _EXACT_VALUE_LIMIT):
        return None
    return array


def _mesh_arrays(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
) -> _MeshArrays | None:
    """Return the mesh as arrays, or None when the Python path must handle it."""
    try:
        nodes = np.asarray(nodes_mm)
        tris = np.asarray(triangles)
    except (TypeError, ValueError):
        return None
    if nodes.ndim != 2 or nodes.shape[1] < 2 or tris.ndim != 2 or tris.shape[1] != 3:
        return None
    if tris.dtype.kind not in "iu" or tris.size == 0:
        return None
    nodes_xy = _exact_float_array(nodes[:, :2])
    az = _exact_float_array(az_nodal)
    if nodes_xy is None or az is None or az.ndim != 1:
        return None
    if tris.min() < 0 or tris.max() >= min(len(nodes_xy), len(az)):
        return None
    return _MeshArrays(nodes_mm=nodes_xy, triangles=tris.astype(np.intp), az=az)


def _exact_levels(levels: list[float]) -> bool:
    return all(isinstance(level, (int, float)) and abs(level) < _EXACT_VALUE_LIMIT for level in levels)


def _element_b_components_array(mesh: _MeshArrays) -> tuple[np.ndarray, np.ndarray]:
    """``_triangle_b_components_t`` for every triangle at once."""
    x = mesh.nodes_mm[:, 0] * 1e-3
    y = mesh.nodes_mm[:, 1] * 1e-3
    i, j, k = mesh.triangles.T
    xi, yi = x[i], y[i]
    xj, yj = x[j], y[j]
    xk, yk = x[k], y[k]
    ai, aj, ak = mesh.az[i], mesh.az[j], mesh.az[k]

    double_area = (xj - xi) * (yk - yi) - (xk - xi) * (yj - yi)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        da_dx = (ai * (yj - yk) + aj * (yk - yi) + ak * (yi - yj)) / double_area
        da_dy = (ai * (xk - xj) + aj * (xi - xk) + ak * (xj - xi)) / double_area
    bx = da_dy
    by = -da_dx
    zeroed = (np.abs(double_area) <= 1e-30) | ~np.isfinite(bx) | ~np.isfinite(by)
    bx[zeroed] = 0.0
    by[zeroed] = 0.0
    return bx, by


def _b_magnitudes(bx_values: list[float], by_values: list[float]) -> list[float]:
    # math.hypot, not np.hypot: the two can differ in the last bit.
    return list(map(math.hypot, bx_values, by_values))


def _finite_or_zero(values: list[float]) -> list[float]:
    return [value if math.isfinite(value) else 0.0 for value in values]


def _more_than_two_levels(values: np.ndarray, *, span: float) -> bool:
    """Whether ``_dedupe_levels(values, span=span)`` keeps more than two values."""
    tolerance = max(abs(span) * 1e-7, 1e-12)
    ordered = np.sort(values)
    gaps = np.flatnonzero(np.abs(ordered - ordered[0]) > tolerance)
    if gaps.size == 0:
        return False
    second = ordered[gaps[0]]
    return bool(np.any(np.abs(ordered[gaps[0] + 1 :] - second) > tolerance))


def _triangle_area_weighted_az_arrays(mesh: _MeshArrays) -> tuple[np.ndarray, np.ndarray]:
    """``_triangle_area_weighted_az_values`` as (values, areas) arrays."""
    x = mesh.nodes_mm[:, 0]
    y = mesh.nodes_mm[:, 1]
    i, j, k = mesh.triangles.T
    area = np.abs((x[j] - x[i]) * (y[k] - y[i]) - (x[k] - x[i]) * (y[j] - y[i])) * 0.5
    value = (mesh.az[i] + mesh.az[j] + mesh.az[k]) / 3.0
    keep = area > 0
    return value[keep], area[keep]


def _weighted_quantile_levels_array(
    values: np.ndarray,
    weights: np.ndarray,
    level_count: int,
    *,
    low_quantile: float = 0.08,
    high_quantile: float = 0.96,
) -> list[float]:
    """``_weighted_quantile_levels`` for finite values and finite positive weights."""
    if values.size == 0 or level_count <= 0:
        return []

    # Sort like the Python (value, weight) tuples; lexsort is stable.
    order = np.lexsort((weights, values))
    values = values[order]
    weights = weights[order]
    total_weight = sum(weights.tolist())
    if total_weight <= 0:
        return []

    # cumulative[c] is the Python loop's running sum plus weight c.
    cumulative = np.cumsum(weights)
    last = len(values) - 1
    levels: list[float] = []
    cursor = 0
    quantile_span = max(0.0, high_quantile - low_quantile)
    for index in range(1, level_count + 1):
        quantile = low_quantile + quantile_span * index / (level_count + 1)
        target = quantile * total_weight
        # The loop stops at the first cursor whose sum reaches the target.
        cursor = max(cursor, min(int(np.searchsorted(cumulative, target, side="left")), last))
        levels.append(float(values[cursor]))
    return levels


def _contour_levels_array(az: np.ndarray, bands_per_side: int, mesh: _MeshArrays | None) -> list[float]:
    """``_contour_levels_python`` for finite A_z."""
    if az.size == 0:
        return []

    az_min = float(az.min())
    az_max = float(az.max())
    span = az_max - az_min
    if span <= 1e-12:
        return []

    level_count = max(2, bands_per_side * 2)
    if not _more_than_two_levels(az, span=span):
        return _uniform_levels(az_min, az_max, level_count)

    uniform_count = max(2, level_count // 2)
    distribution_count = max(0, level_count - uniform_count)
    levels = _uniform_levels(az_min, az_max, uniform_count)

    if distribution_count > 0:
        values, weights = _triangle_area_weighted_az_arrays(mesh) if mesh is not None else (az[:0], az[:0])
        if values.size == 0:
            values, weights = az, np.ones_like(az)
        levels.extend(_weighted_quantile_levels_array(values, weights, distribution_count))

    deduped = _dedupe_levels(levels, span=span)
    if len(deduped) < level_count:
        deduped = _dedupe_levels(
            deduped + _uniform_levels(az_min, az_max, level_count),
            span=span,
        )
    return deduped


def _edge_crossings(
    mesh: _MeshArrays,
    corners: np.ndarray,
    offsets: np.ndarray,
    rows: np.ndarray,
    edges: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Where each row's level crosses its edge from corner ``edges`` to the next corner."""
    ends = (edges + 1) % 3
    v1 = offsets[rows, edges]
    v2 = offsets[rows, ends]
    start_nodes = corners[rows, edges]
    end_nodes = corners[rows, ends]
    x = mesh.nodes_mm[:, 0]
    y = mesh.nodes_mm[:, 1]
    t = v1 / (v1 - v2)
    return (
        x[start_nodes] + t * (x[end_nodes] - x[start_nodes]),
        y[start_nodes] + t * (y[end_nodes] - y[start_nodes]),
    )


def _contour_segments_array(
    mesh: _MeshArrays,
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
    levels: list[float],
    bx: np.ndarray,
    by: np.ndarray,
    b_mag: np.ndarray,
) -> list[FieldLineContourLevel]:
    """``_contour_segments_python`` for an exact mesh and levels.

    A triangle with no vertex within value_tol of the level is crossed on two
    edges or none, and those are cut here in numpy. The few with a vertex on
    the level go through ``_triangle_contour_segment``.
    """
    value_tol = max(float(np.abs(mesh.az).max()) * 1e-9, 1e-12)
    point_tol = 1e-7
    tri_az = mesh.az[mesh.triangles]
    lowest = tri_az.min(axis=1)
    highest = tri_az.max(axis=1)
    contours: list[FieldLineContourLevel] = []

    for level in levels:
        # The Python path's skip test, negated.
        candidates = np.flatnonzero((highest - level >= -value_tol) & (lowest - level <= value_tol))
        corners = mesh.triangles[candidates]
        offsets = tri_az[candidates] - level
        on_level_count = (np.abs(offsets) <= value_tol).sum(axis=1)
        positive = offsets > 0
        # Edges (0, 1), (1, 2) and (2, 0) whose ends lie on opposite sides.
        crossed = positive != np.roll(positive, -1, axis=1)

        cut = np.flatnonzero((on_level_count == 0) & crossed.any(axis=1))
        x1, y1 = _edge_crossings(mesh, corners, offsets, cut, np.where(crossed[cut, 0], 0, 1))
        x2, y2 = _edge_crossings(mesh, corners, offsets, cut, np.where(crossed[cut, 2], 2, 1))
        distinct = ~((np.abs(x2 - x1) <= point_tol) & (np.abs(y2 - y1) <= point_tol))
        segment_rows = candidates[cut[distinct]]
        segments = np.column_stack((x1[distinct], y1[distinct], x2[distinct], y2[distinct]))

        touching_rows: list[int] = []
        touching_segments: list[list[float]] = []
        for tri_idx in candidates[(on_level_count > 0) & (on_level_count < 3)].tolist():
            i, j, k = triangles[tri_idx]
            segment = _triangle_contour_segment(
                [nodes_mm[i], nodes_mm[j], nodes_mm[k]],
                [az_nodal[i], az_nodal[j], az_nodal[k]],
                level,
                value_tol,
                point_tol,
            )
            if segment is not None:
                touching_rows.append(tri_idx)
                touching_segments.append(segment)
        if touching_rows:
            segment_rows = np.concatenate((segment_rows, np.array(touching_rows, dtype=np.intp)))
            segments = np.concatenate((segments, np.array(touching_segments, dtype=np.float64)))
            order = np.argsort(segment_rows, kind="stable")
            segment_rows = segment_rows[order]
            segments = segments[order]

        contours.append(
            FieldLineContourLevel(
                level=level,
                segments_mm=segments.tolist(),
                segment_b_mag_t=b_mag[segment_rows].tolist(),
                segment_bx_t=bx[segment_rows].tolist(),
                segment_by_t=by[segment_rows].tolist(),
            )
        )

    return contours


def generate_contour_levels(
    az_nodal: list[float],
    bands_per_side: int = _DEFAULT_BANDS_PER_SIDE,
    *,
    nodes_mm: list[list[float]] | None = None,
    triangles: list[list[int]] | None = None,
) -> list[float]:
    """Generate interior A_z contour levels with full-range and spatial coverage."""
    mesh = None
    if nodes_mm and triangles:
        mesh = _mesh_arrays(nodes_mm, triangles, az_nodal)
        az = mesh.az if mesh is not None else None
    else:
        az = _exact_float_array(az_nodal)
        if az is not None and az.ndim != 1:
            az = None
    if az is None:
        return _contour_levels_python(az_nodal, bands_per_side, nodes_mm=nodes_mm, triangles=triangles)
    return _contour_levels_array(az, bands_per_side, mesh)


def generate_element_b_magnitudes(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
) -> list[float]:
    """Return element-constant |B| in Tesla for each linear A_z triangle."""
    if not nodes_mm or not triangles or not az_nodal:
        return []

    mesh = _mesh_arrays(nodes_mm, triangles, az_nodal)
    if mesh is None:
        return _element_b_magnitudes_python(nodes_mm, triangles, az_nodal)
    bx, by = _element_b_components_array(mesh)
    return _finite_or_zero(_b_magnitudes(bx.tolist(), by.tolist()))


def generate_element_b_components(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
) -> tuple[list[float], list[float]]:
    """Return element-constant B_x and B_y in Tesla, aligned with triangles."""
    if not nodes_mm or not triangles or not az_nodal:
        return [], []

    mesh = _mesh_arrays(nodes_mm, triangles, az_nodal)
    if mesh is None:
        return _element_b_components_python(nodes_mm, triangles, az_nodal)
    bx, by = _element_b_components_array(mesh)
    return bx.tolist(), by.tolist()


def generate_contour_segments(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
    levels: list[float],
) -> list[FieldLineContourLevel]:
    """Generate contour segments for each requested A_z level on a triangle mesh."""
    if not nodes_mm or not triangles or not az_nodal or not levels:
        return []

    mesh = _mesh_arrays(nodes_mm, triangles, az_nodal)
    if mesh is None or not _exact_levels(levels):
        return _contour_segments_python(nodes_mm, triangles, az_nodal, levels)
    bx, by = _element_b_components_array(mesh)
    b_mag = np.array(_b_magnitudes(bx.tolist(), by.tolist()))
    return _contour_segments_array(mesh, nodes_mm, triangles, az_nodal, levels, bx, by, b_mag)


def _field_line_plot_fields(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    az_nodal: list[float],
) -> tuple[list[float], list[float], list[float], list[FieldLineContourLevel]]:
    """Return element |B|, B_x, B_y and the contours, computing B once per triangle."""
    mesh = _mesh_arrays(nodes_mm, triangles, az_nodal)
    if mesh is None:
        element_b_mag_t = generate_element_b_magnitudes(nodes_mm, triangles, az_nodal)
        element_bx_t, element_by_t = generate_element_b_components(nodes_mm, triangles, az_nodal)
        contour_levels = generate_contour_levels(
            az_nodal,
            nodes_mm=nodes_mm,
            triangles=triangles,
        )
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, contour_levels)
        return element_b_mag_t, element_bx_t, element_by_t, contours

    bx, by = _element_b_components_array(mesh)
    element_bx_t = bx.tolist()
    element_by_t = by.tolist()
    b_mag = _b_magnitudes(element_bx_t, element_by_t)
    contour_levels = _contour_levels_array(mesh.az, _DEFAULT_BANDS_PER_SIDE, mesh)
    contours = (
        _contour_segments_array(mesh, nodes_mm, triangles, az_nodal, contour_levels, bx, by, np.array(b_mag))
        if contour_levels
        else []
    )
    return _finite_or_zero(b_mag), element_bx_t, element_by_t, contours


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
    element_b_mag_t, element_bx_t, element_by_t, contours = _field_line_plot_fields(
        nodes_mm,
        triangles,
        az_nodal,
    )

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

    element_b_mag_t, element_bx_t, element_by_t, contours = _field_line_plot_fields(
        nodes_mm,
        triangles,
        az_nodal,
    )

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
