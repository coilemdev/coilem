"""Tessellate shared geometry IR loops into SVG polygon points."""

from __future__ import annotations

import math

from backend.geometry_ir import GeometryIRLoop, GeometryIRRegion, GeometryIRSegment

DEFAULT_DEGREES_PER_SEGMENT = 1.0


def _reverse_segment(segment: GeometryIRSegment) -> GeometryIRSegment:
    if segment.kind == "line":
        return GeometryIRSegment(
            kind="line",
            start=segment.end,
            end=segment.start,
            boundary_tag=segment.boundary_tag,
        )
    sweep = segment.sweep_deg
    return GeometryIRSegment(
        kind="arc",
        start=segment.end,
        end=segment.start,
        center=segment.center,
        radius_mm=segment.radius_mm,
        sweep_deg=-sweep if sweep is not None else None,
        boundary_tag=segment.boundary_tag,
    )


def _append_ir_segment(
    points: list[tuple[float, float]],
    segment: GeometryIRSegment,
    *,
    include_start: bool,
    degrees_per_segment: float,
) -> None:
    start = (segment.start.x_mm, segment.start.y_mm)
    end = (segment.end.x_mm, segment.end.y_mm)

    if segment.kind == "line":
        if include_start:
            points.append(start)
        points.append(end)
        return

    center = segment.center
    radius = segment.radius_mm
    if center is None or radius is None or radius <= 0:
        if include_start:
            points.append(start)
        points.append(end)
        return

    cx, cy = center.x_mm, center.y_mm
    start_angle = math.atan2(segment.start.y_mm - cy, segment.start.x_mm - cx)
    if segment.sweep_deg is not None:
        sweep_rad = math.radians(segment.sweep_deg)
    else:
        end_angle = math.atan2(segment.end.y_mm - cy, segment.end.x_mm - cx)
        sweep_rad = end_angle - start_angle

    segment_count = max(1, int(math.ceil(abs(math.degrees(sweep_rad)) / degrees_per_segment)))
    if include_start:
        points.append(start)
    for step in range(1, segment_count + 1):
        angle = start_angle + sweep_rad * step / segment_count
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))


def tessellate_ir_loop(
    loop: GeometryIRLoop,
    *,
    reverse: bool = False,
    degrees_per_segment: float = DEFAULT_DEGREES_PER_SEGMENT,
) -> list[tuple[float, float]]:
    """Return polygon vertices for one closed IR loop."""
    points: list[tuple[float, float]] = []
    segments = loop.segments
    if reverse:
        segments = tuple(reversed(segments))

    for index, raw_segment in enumerate(segments):
        segment = _reverse_segment(raw_segment) if reverse else raw_segment
        _append_ir_segment(
            points,
            segment,
            include_start=index == 0,
            degrees_per_segment=degrees_per_segment,
        )
    return points


def tessellate_ir_region(
    region: GeometryIRRegion,
    *,
    degrees_per_segment: float = DEFAULT_DEGREES_PER_SEGMENT,
) -> list[list[float]]:
    """Tessellate an IR region into one SVG polygon (nonzero winding for holes)."""
    if not region.loops:
        return []

    combined: list[tuple[float, float]] = []
    for loop_index, loop in enumerate(region.loops):
        loop_points = tessellate_ir_loop(
            loop,
            reverse=loop_index > 0,
            degrees_per_segment=degrees_per_segment,
        )
        combined.extend(loop_points)

    if not combined:
        return []

    if combined[0] != combined[-1]:
        combined.append(combined[0])

    return [[float(x), float(y)] for x, y in combined]


def polygon_centroid(points: list[list[float]]) -> tuple[float, float]:
    """Simple vertex-average centroid for label placement."""
    ring = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    if not ring:
        return 0.0, 0.0
    return (
        sum(point[0] for point in ring) / len(ring),
        sum(point[1] for point in ring) / len(ring),
    )
