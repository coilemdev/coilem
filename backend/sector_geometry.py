"""Reduce a full-circle geometry IR to one repeating sector.

A motor with Q slots and p pole pairs repeats ``t = gcd(Q, p)`` times around
the circle; when ``Q / t`` is even, half of that repeat is enough because the
next half is its negative. Solving one sector with its two cut edges tied
together (equal potential, or opposite potential for the half repeat) gives the
full-circle answer from a mesh that is ``1 / repeats`` the size.

The stator and the rotor are cut separately, each along a line fixed in its own
frame:

* the stator through the middle of a tooth, so every slot stays whole;
* the rotor between two poles, so no magnet or pocket is ever cut, whatever the
  rotor angle.

The two wedges meet on a circle in the middle of the air gap. Where they do not
overlap, the stator-only arc and the rotor-only arc are one sector apart, so
they are tied like the cut edges. Each rotor position is cut independently from
the full IR built at that position.

Anything this module cannot cut cleanly raises :class:`SectorUnsupportedError`;
callers fall back to the full circle.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace

from backend.geometry_ir import (
    GeometryIR,
    GeometryIRLoop,
    GeometryIRPoint,
    GeometryIRRegion,
    GeometryIRSegment,
)

SECTOR_EDGE_TAG = "sector_edge"
SECTOR_MID_GAP_TAG = "sector_mid_gap"
# The line through a tooth centre between two slot-pitch pieces of the stator iron.
SECTOR_SLOT_PITCH_TAG = "sector_slot_pitch"
_STATOR_IRON_KINDS = frozenset({"StatorYoke", "StatorTooth"})

# Points closer than this to a cut line count as on it [mm].
_ON_LINE_TOL_MM = 1.0e-7
# Radii on a cut edge closer than this are one breakpoint [mm].
_RADIUS_CLUSTER_TOL_MM = 1.0e-6
_TWO_PI = 2.0 * math.pi
# Gmsh circle arcs must stay well under 180 degrees.
_MAX_MID_ARC_RAD = math.radians(60.0)


class SectorUnsupportedError(ValueError):
    """The geometry or winding cannot be reduced to a sector."""


@dataclass(frozen=True)
class SectorSymmetry:
    """How a motor repeats around the circle."""

    repeats: int
    anti_periodic: bool
    n_pole_pitches: int
    slots_per_sector: int

    @property
    def span_rad(self) -> float:
        return _TWO_PI / self.repeats

    @property
    def span_deg(self) -> float:
        return 360.0 / self.repeats

    @property
    def sign(self) -> float:
        return -1.0 if self.anti_periodic else 1.0


@dataclass(frozen=True)
class SectorPiece:
    """One connected part of a cut region: its outline and its holes, all counter-clockwise."""

    outer: GeometryIRLoop
    holes: tuple[GeometryIRLoop, ...] = ()


@dataclass(frozen=True)
class SectorCurvePair:
    """Two boundary curves one sector apart; the mesher gives them matching nodes."""

    kind: str  # "line" or "arc"
    master_start: tuple[float, float]
    master_end: tuple[float, float]
    slave_start: tuple[float, float]
    slave_end: tuple[float, float]
    # Rotation that carries the master onto the slave [rad].
    rotation_rad: float
    radius_mm: float | None = None


@dataclass(frozen=True)
class SectorIR:
    """A geometry IR cut down to one sector, with what the mesher needs to tie its edges."""

    ir: GeometryIR
    pieces_by_region: dict[str, tuple[SectorPiece, ...]]
    symmetry: SectorSymmetry
    stator_start_rad: float
    rotor_start_rad: float
    mid_gap_radius_mm: float
    curve_pairs: tuple[SectorCurvePair, ...]
    # The wedge reaches the centre: both cut edges share that node.
    apex_at_centre: bool
    # The tooth centre the cut search starts from (the one before slot 0); it
    # breaks ties between equally near teeth, so the cut can be found again at
    # any other rotor angle (sector_cuts_by_turn).
    first_tooth_rad: float | None = None
    # A stator-only arc on the mid-gap circle shorter than this is not meshed:
    # one cut moves onto the other ("rotor" or "stator", see snap_moves).
    min_mid_gap_offset_mm: float = 0.0
    snap_moves: str = "rotor"
    # The stator iron in slot-pitch pieces from the stator cut, (region id, piece
    # index, pitches from the cut): the mesher meshes the first pitch and copies it,
    # so every position's stator iron mesh is the same mesh wherever it is cut.
    stator_iron_units: tuple[tuple[str, int, int], ...] = ()
    slot_pitch_rad: float = 0.0


# --------------------------------------------------------------------------
# Symmetry
# --------------------------------------------------------------------------


def candidate_symmetries(slot_count: int, pole_count: int) -> tuple[SectorSymmetry, ...]:
    """Sector choices from slot and pole counts alone, smallest sector first.

    A sector holding a whole number of slots and of poles repeats the iron and
    magnets; an odd number of poles makes the next sector its negative. Whether
    the winding repeats the same way is checked separately: a single-layer
    winding on alternate teeth, for one, needs twice the sector its slot and
    pole counts suggest.
    """

    if slot_count <= 0 or pole_count <= 0 or pole_count % 2:
        return ()
    common = math.gcd(slot_count, pole_count)
    out: list[SectorSymmetry] = []
    for repeats in range(common, 1, -1):
        if common % repeats:
            continue
        poles = pole_count // repeats
        out.append(
            SectorSymmetry(
                repeats=repeats,
                anti_periodic=poles % 2 == 1,
                n_pole_pitches=poles,
                slots_per_sector=slot_count // repeats,
            )
        )
    return tuple(out)


def _winding_table(ir: GeometryIR) -> dict[tuple[int, int], tuple[str, str]] | None:
    """(slot, layer) -> (phase, direction) from the IR's winding regions; None when unreadable."""

    table: dict[tuple[int, int], tuple[str, str]] = {}
    for region in ir.regions:
        if region.kind != "SlotWinding":
            continue
        parts = (region.source_group or "").split(":")
        if len(parts) < 4 or parts[0] != "winding":
            return None
        slot_token = parts[3]
        if not (slot_token.startswith("slot") and slot_token[4:].isdigit()):
            return None
        layer = 0
        if len(parts) >= 5:
            layer_token = parts[4]
            if not (layer_token.startswith("layer") and layer_token[5:].isdigit()):
                return None
            layer = int(layer_token[5:])
        key = (int(slot_token[4:]), layer)
        if key in table:
            return None
        table[key] = (parts[1], parts[2])
    return table


def _winding_repeats(ir: GeometryIR, symmetry: SectorSymmetry) -> bool:
    table = _winding_table(ir)
    if not table:
        return False
    flipped = {"in": "out", "out": "in"}
    for (slot, layer), (phase, direction) in table.items():
        partner = table.get(((slot + symmetry.slots_per_sector) % ir.slot_count, layer))
        if partner is None:
            return False
        if direction not in flipped:
            return False
        expected = flipped[direction] if symmetry.anti_periodic else direction
        if partner != (phase, expected):
            return False
    return True


def _loop_vertices(loop: GeometryIRLoop) -> list[tuple[float, float]]:
    return [(segment.start.x_mm, segment.start.y_mm) for segment in loop.segments]


def _region_signature(region: GeometryIRRegion) -> tuple[float, float, int] | None:
    """Centroid of the outline's vertices and their count; None for a region that surrounds the axis.

    A ring or disc around the axis (yoke, air gap, rotor core, shaft) maps onto
    itself; its parts that could break the repeat (slots, pockets, magnets) are
    regions of their own and are checked there.
    """

    if not region.loops:
        return None
    vertices = _loop_vertices(region.loops[0])
    if len(vertices) < 3 or _point_in_polygon((0.0, 0.0), vertices):
        return None
    cx = sum(x for x, _ in vertices) / len(vertices)
    cy = sum(y for _, y in vertices) / len(vertices)
    return cx, cy, len(vertices)


def _geometry_repeats(ir: GeometryIR, symmetry: SectorSymmetry) -> bool:
    """Every off-axis region has a twin one sector on: same kind, material, area, and magnetization."""

    cos_a, sin_a = math.cos(symmetry.span_rad), math.sin(symmetry.span_rad)
    by_kind: dict[tuple[str, str], list[tuple[GeometryIRRegion, tuple[float, float, int]]]] = {}
    for region in ir.regions:
        signature = _region_signature(region)
        if signature is None:
            continue
        by_kind.setdefault((region.kind, region.material_key), []).append((region, signature))
    for candidates in by_kind.values():
        for region, (cx, cy, count) in candidates:
            tx, ty = cx * cos_a - cy * sin_a, cx * sin_a + cy * cos_a
            tol = 1.0e-6 * max(1.0, math.hypot(cx, cy))
            twin = None
            for other, (ox, oy, other_count) in candidates:
                if other_count == count and math.hypot(ox - tx, oy - ty) <= tol:
                    twin = other
                    break
            if twin is None:
                return False
            if abs(twin.area_mm2 - region.area_mm2) > 1.0e-6 * max(1.0, abs(region.area_mm2)):
                return False
            if (region.magnetization_xy is None) != (twin.magnetization_xy is None):
                return False
            if region.magnetization_xy is not None and twin.magnetization_xy is not None:
                mx, my = region.magnetization_xy
                ex = symmetry.sign * (mx * cos_a - my * sin_a)
                ey = symmetry.sign * (mx * sin_a + my * cos_a)
                if math.hypot(twin.magnetization_xy[0] - ex, twin.magnetization_xy[1] - ey) > 1.0e-6:
                    return False
    return True


def detect_sector_symmetry(ir: GeometryIR) -> SectorSymmetry | None:
    """The smallest sector the IR's geometry and winding both repeat over; None for the full circle."""

    for symmetry in candidate_symmetries(ir.slot_count, ir.pole_count):
        if _winding_repeats(ir, symmetry) and _geometry_repeats(ir, symmetry):
            return symmetry
    return None


# --------------------------------------------------------------------------
# Segment helpers
# --------------------------------------------------------------------------


def _xy(point: GeometryIRPoint) -> tuple[float, float]:
    return (point.x_mm, point.y_mm)


def _pt(xy: tuple[float, float]) -> GeometryIRPoint:
    return GeometryIRPoint(float(xy[0]), float(xy[1]))


def _arc_sweep_rad(segment: GeometryIRSegment) -> float:
    if segment.sweep_deg is not None:
        return math.radians(segment.sweep_deg)
    # No sweep recorded: the mesher draws the minor arc.
    center = _xy(segment.center)  # type: ignore[arg-type]
    start, end = _xy(segment.start), _xy(segment.end)
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = (a1 - a0) % _TWO_PI
    if sweep > math.pi:
        sweep -= _TWO_PI
    return sweep


def _normalized(segment: GeometryIRSegment) -> GeometryIRSegment:
    """Arcs carry an explicit sweep; a broken arc is rejected."""

    if segment.kind != "arc":
        return segment
    if segment.center is None or segment.radius_mm is None or segment.radius_mm <= 0.0:
        raise SectorUnsupportedError("an arc without centre or radius cannot be cut")
    if segment.sweep_deg is None:
        return replace(segment, sweep_deg=math.degrees(_arc_sweep_rad(segment)))
    return segment


def _arc_point(segment: GeometryIRSegment, fraction: float) -> tuple[float, float]:
    center = _xy(segment.center)  # type: ignore[arg-type]
    start = _xy(segment.start)
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    angle = a0 + fraction * _arc_sweep_rad(segment)
    radius = float(segment.radius_mm)  # type: ignore[arg-type]
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))


def _midpoint(segment: GeometryIRSegment) -> tuple[float, float]:
    if segment.kind == "arc":
        return _arc_point(segment, 0.5)
    return (
        0.5 * (segment.start.x_mm + segment.end.x_mm),
        0.5 * (segment.start.y_mm + segment.end.y_mm),
    )


def _length(segment: GeometryIRSegment) -> float:
    if segment.kind == "arc":
        return abs(_arc_sweep_rad(segment)) * float(segment.radius_mm)  # type: ignore[arg-type]
    return math.hypot(segment.end.x_mm - segment.start.x_mm, segment.end.y_mm - segment.start.y_mm)


def _reversed(segment: GeometryIRSegment) -> GeometryIRSegment:
    if segment.kind == "arc":
        return replace(
            segment,
            start=segment.end,
            end=segment.start,
            sweep_deg=-math.degrees(_arc_sweep_rad(segment)),
        )
    return replace(segment, start=segment.end, end=segment.start)


def _split(segment: GeometryIRSegment, fractions: list[float], points: list[tuple[float, float]]) -> list[GeometryIRSegment]:
    """Cut a segment at increasing fractions of its length; ``points`` are the cut points."""

    if not fractions:
        return [segment]
    out: list[GeometryIRSegment] = []
    previous_fraction = 0.0
    previous_point = segment.start
    total_sweep_deg = math.degrees(_arc_sweep_rad(segment)) if segment.kind == "arc" else 0.0
    for fraction, xy in [*zip(fractions, points), (1.0, _xy(segment.end))]:
        point = segment.end if fraction >= 1.0 else _pt(xy)
        if segment.kind == "arc":
            out.append(
                replace(
                    segment,
                    start=previous_point,
                    end=point,
                    sweep_deg=total_sweep_deg * (fraction - previous_fraction),
                )
            )
        else:
            out.append(replace(segment, start=previous_point, end=point))
        previous_fraction, previous_point = fraction, point
    return out


def _signed_loop_area(segments: list[GeometryIRSegment]) -> float:
    total = 0.0
    for segment in segments:
        sx, sy = _xy(segment.start)
        ex, ey = _xy(segment.end)
        if segment.kind == "line":
            total += 0.5 * (sx * ey - sy * ex)
            continue
        cx, cy = _xy(segment.center)  # type: ignore[arg-type]
        radius = float(segment.radius_mm)  # type: ignore[arg-type]
        total += 0.5 * (cx * (ey - sy) - cy * (ex - sx) + radius**2 * _arc_sweep_rad(segment))
    return total


def _polyline(segments: list[GeometryIRSegment]) -> list[tuple[float, float]]:
    """The loop as a polygon, arcs sampled finely; for containment tests only."""

    points: list[tuple[float, float]] = []
    for segment in segments:
        points.append(_xy(segment.start))
        if segment.kind == "arc":
            steps = max(1, int(abs(math.degrees(_arc_sweep_rad(segment))) // 3.0))
            points.extend(_arc_point(segment, k / (steps + 1)) for k in range(1, steps + 1))
    return points


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# --------------------------------------------------------------------------
# Cutting loops with a half-plane through the centre
# --------------------------------------------------------------------------


def _line_crossings(
    segment: GeometryIRSegment,
    normal: tuple[float, float],
) -> tuple[list[float], list[tuple[float, float]]]:
    """Where a segment crosses the line ``normal . p = 0``, strictly inside the segment."""

    nx, ny = normal
    length = _length(segment)
    if length <= 2.0 * _ON_LINE_TOL_MM:
        return [], []
    edge_fraction = _ON_LINE_TOL_MM / length
    if segment.kind == "line":
        s0 = nx * segment.start.x_mm + ny * segment.start.y_mm
        s1 = nx * segment.end.x_mm + ny * segment.end.y_mm
        if abs(s0) <= _ON_LINE_TOL_MM or abs(s1) <= _ON_LINE_TOL_MM or (s0 > 0.0) == (s1 > 0.0):
            return [], []
        fraction = s0 / (s0 - s1)
        if fraction <= edge_fraction or fraction >= 1.0 - edge_fraction:
            return [], []
        x = segment.start.x_mm + fraction * (segment.end.x_mm - segment.start.x_mm)
        y = segment.start.y_mm + fraction * (segment.end.y_mm - segment.start.y_mm)
        offset = nx * x + ny * y
        return [fraction], [(x - offset * nx, y - offset * ny)]

    cx, cy = _xy(segment.center)  # type: ignore[arg-type]
    radius = float(segment.radius_mm)  # type: ignore[arg-type]
    distance = nx * cx + ny * cy
    if abs(distance) >= radius - _ON_LINE_TOL_MM:
        return [], []
    sweep = _arc_sweep_rad(segment)
    start_angle = math.atan2(segment.start.y_mm - cy, segment.start.x_mm - cx)
    normal_angle = math.atan2(ny, nx)
    half = math.acos(max(-1.0, min(1.0, -distance / radius)))
    found: list[tuple[float, tuple[float, float]]] = []
    for angle in (normal_angle + half, normal_angle - half):
        delta = (angle - start_angle) % _TWO_PI if sweep > 0.0 else (start_angle - angle) % _TWO_PI
        fraction = delta / abs(sweep)
        if fraction <= edge_fraction or fraction >= 1.0 - edge_fraction:
            continue
        x, y = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        offset = nx * x + ny * y
        found.append((fraction, (x - offset * nx, y - offset * ny)))
    found.sort()
    return [f for f, _ in found], [p for _, p in found]


def _side(segment: GeometryIRSegment, normal: tuple[float, float]) -> str:
    mx, my = _midpoint(segment)
    value = normal[0] * mx + normal[1] * my
    if value > _ON_LINE_TOL_MM:
        return "in"
    if value < -_ON_LINE_TOL_MM:
        return "out"
    if segment.kind == "arc":
        raise SectorUnsupportedError("an arc lies along a sector cut")
    return "on"


@dataclass
class _Chain:
    segments: list[GeometryIRSegment]

    @property
    def start(self) -> tuple[float, float]:
        return _xy(self.segments[0].start)

    @property
    def end(self) -> tuple[float, float]:
        return _xy(self.segments[-1].end)


def _clip_piece(
    loops: list[list[GeometryIRSegment]],
    normal: tuple[float, float],
) -> list[tuple[list[GeometryIRSegment], list[list[GeometryIRSegment]]]]:
    """Keep the part of one region piece on the ``normal`` side of a line through the centre.

    ``loops`` is the outline followed by its holes. Returns pieces as
    (outline, holes), every loop counter-clockwise.
    """

    nx, ny = normal
    along = (ny, -nx)
    closed: list[list[GeometryIRSegment]] = []
    chains: list[_Chain] = []
    for loop in loops:
        parts: list[GeometryIRSegment] = []
        for segment in loop:
            fractions, points = _line_crossings(segment, normal)
            parts.extend(_split(segment, fractions, points))
        sides = [_side(part, normal) for part in parts]
        if all(side == "in" for side in sides):
            closed.append(parts)
            continue
        if not any(side == "in" for side in sides):
            continue
        first = next(i for i in range(len(parts)) if sides[i] == "in" and sides[i - 1] != "in")
        order = list(range(first, len(parts))) + list(range(first))
        run: list[GeometryIRSegment] = []
        for index in order:
            if sides[index] == "in":
                run.append(parts[index])
            elif run:
                chains.append(_Chain(run))
                run = []
        if run:
            chains.append(_Chain(run))

    for chain in chains:
        for x, y in (chain.start, chain.end):
            if abs(nx * x + ny * y) > 10.0 * _ON_LINE_TOL_MM:
                raise SectorUnsupportedError("a cut outline does not end on the sector edge")

    traced: list[list[GeometryIRSegment]] = []
    if chains:
        # Along the cut line the region lies between the 1st and 2nd outline
        # crossing, the 3rd and 4th, and so on.
        ends: list[tuple[float, int, str]] = []
        for index, chain in enumerate(chains):
            ends.append((along[0] * chain.start[0] + along[1] * chain.start[1], index, "start"))
            ends.append((along[0] * chain.end[0] + along[1] * chain.end[1], index, "end"))
        ends.sort(key=lambda item: item[0])
        if len(ends) % 2:
            raise SectorUnsupportedError("a sector cut crosses an outline an odd number of times")
        partner: dict[tuple[int, str], tuple[int, str]] = {}
        for k in range(0, len(ends), 2):
            a, b = ends[k], ends[k + 1]
            partner[(a[1], a[2])] = (b[1], b[2])
            partner[(b[1], b[2])] = (a[1], a[2])
        visited: set[int] = set()
        for seed in range(len(chains)):
            if seed in visited:
                continue
            loop_segments: list[GeometryIRSegment] = []
            index, forward = seed, True
            guard = 0
            while True:
                guard += 1
                if guard > 4 * len(chains) + 4:
                    raise SectorUnsupportedError("a sector cut could not be closed into loops")
                visited.add(index)
                chain = chains[index]
                segments = chain.segments if forward else [_reversed(s) for s in reversed(chain.segments)]
                loop_segments.extend(segments)
                leave = (index, "end" if forward else "start")
                arrive = partner[leave]
                here = _xy(segments[-1].end)
                target_chain = chains[arrive[0]]
                there = target_chain.start if arrive[1] == "start" else target_chain.end
                if math.hypot(there[0] - here[0], there[1] - here[1]) > _ON_LINE_TOL_MM:
                    loop_segments.append(
                        GeometryIRSegment("line", _pt(here), _pt(there), boundary_tag=SECTOR_EDGE_TAG)
                    )
                index, forward = arrive[0], arrive[1] == "start"
                if index == seed and forward:
                    break
                if index in visited:
                    raise SectorUnsupportedError("a sector cut produced a self-crossing outline")
            traced.append(loop_segments)

    all_loops = [*traced, *closed]
    if not all_loops:
        return []
    oriented: list[list[GeometryIRSegment]] = []
    for loop in all_loops:
        area = _signed_loop_area(loop)
        if abs(area) <= 1.0e-12:
            raise SectorUnsupportedError("a sector cut left a region with no area")
        oriented.append(loop if area > 0.0 else [_reversed(s) for s in reversed(loop)])
    if len(oriented) == 1:
        return [(oriented[0], [])]

    polygons = [_polyline(loop) for loop in oriented]
    areas = [_signed_loop_area(loop) for loop in oriented]
    probes = [_midpoint(loop[0]) for loop in oriented]
    containers: list[list[int]] = []
    for i, probe in enumerate(probes):
        containers.append([j for j in range(len(oriented)) if j != i and _point_in_polygon(probe, polygons[j])])
    pieces: dict[int, tuple[list[GeometryIRSegment], list[list[GeometryIRSegment]]]] = {}
    for i, inside in enumerate(containers):
        if len(inside) % 2 == 0:
            pieces[i] = (oriented[i], [])
    for i, inside in enumerate(containers):
        if len(inside) % 2 == 0:
            continue
        outers = [j for j in inside if j in pieces]
        if not outers:
            raise SectorUnsupportedError("a hole lost its outline in a sector cut")
        parent = min(outers, key=lambda j: areas[j])
        pieces[parent][1].append(oriented[i])
    return list(pieces.values())


def _wedge_normals(start_rad: float, span_rad: float) -> list[tuple[float, float]]:
    """Inward normals of the half-planes whose intersection is the wedge."""

    first = (-math.sin(start_rad), math.cos(start_rad))
    if abs(span_rad - math.pi) < 1.0e-12:
        return [first]
    if span_rad > math.pi:
        raise SectorUnsupportedError("a sector wider than half the circle is not supported")
    end = start_rad + span_rad
    return [first, (math.sin(end), -math.cos(end))]


def _clip_region_loops(
    loops: tuple[GeometryIRLoop, ...],
    start_rad: float,
    span_rad: float,
) -> list[tuple[list[GeometryIRSegment], list[list[GeometryIRSegment]]]]:
    oriented: list[list[GeometryIRSegment]] = []
    for loop in loops:
        segments = [_normalized(segment) for segment in loop.segments]
        if _signed_loop_area(segments) < 0.0:
            segments = [_reversed(s) for s in reversed(segments)]
        oriented.append(segments)
    pieces = [(oriented[0], oriented[1:])]
    for normal in _wedge_normals(start_rad, span_rad):
        cut: list[tuple[list[GeometryIRSegment], list[list[GeometryIRSegment]]]] = []
        for outer, holes in pieces:
            cut.extend(_clip_piece([outer, *holes], normal))
        pieces = cut
    return pieces


# --------------------------------------------------------------------------
# Building the sector IR
# --------------------------------------------------------------------------


def _loop_radial_extent(loop: GeometryIRLoop) -> tuple[float, float]:
    """Smallest and largest distance from the motor axis to a loop."""

    low, high = math.inf, 0.0
    for raw in loop.segments:
        segment = _normalized(raw)
        sx, sy = _xy(segment.start)
        ex, ey = _xy(segment.end)
        candidates = [math.hypot(sx, sy), math.hypot(ex, ey)]
        if segment.kind == "line":
            dx, dy = ex - sx, ey - sy
            length_sq = dx * dx + dy * dy
            if length_sq > 0.0:
                t = -(sx * dx + sy * dy) / length_sq
                if 0.0 < t < 1.0:
                    candidates.append(math.hypot(sx + t * dx, sy + t * dy))
        else:
            cx, cy = _xy(segment.center)  # type: ignore[arg-type]
            radius = float(segment.radius_mm)  # type: ignore[arg-type]
            offset = math.hypot(cx, cy)
            if offset > 1.0e-12:
                # The nearest and farthest points of the full circle lie on the
                # line through the axis and the arc's centre.
                sweep = _arc_sweep_rad(segment)
                start_angle = math.atan2(sy - cy, sx - cx)
                toward = math.atan2(cy, cx)
                for angle in (toward, toward + math.pi):
                    delta = (angle - start_angle) % _TWO_PI if sweep > 0.0 else (start_angle - angle) % _TWO_PI
                    if delta < abs(sweep):
                        candidates.append(math.hypot(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        low, high = min(low, *candidates), max(high, *candidates)
    return low, high


def _circle_with_breakpoints(loop_id: str, radius_mm: float, angles: list[float], tag: str) -> GeometryIRLoop:
    center = GeometryIRPoint(0.0, 0.0)
    points = [GeometryIRPoint(radius_mm * math.cos(a), radius_mm * math.sin(a)) for a in angles]
    segments = []
    for index, angle in enumerate(angles):
        nxt = (index + 1) % len(angles)
        sweep = (angles[nxt] - angle) % _TWO_PI
        segments.append(
            GeometryIRSegment("arc", points[index], points[nxt], center, radius_mm, math.degrees(sweep), tag)
        )
    return GeometryIRLoop(loop_id=loop_id, kind="circle", segments=tuple(segments), points_mm=tuple(points))


def _unique_angles(angles: list[float]) -> list[float]:
    ordered = sorted(angle % _TWO_PI for angle in angles)
    out: list[float] = []
    for angle in ordered:
        if out and angle - out[-1] < 1.0e-10:
            continue
        out.append(angle)
    if len(out) > 1 and out[0] + _TWO_PI - out[-1] < 1.0e-10:
        out.pop()
    return out


def _wrap_signed(angle: float, period: float) -> float:
    """Into [-period / 2, period / 2)."""

    return (angle + 0.5 * period) % period - 0.5 * period


def _stator_cut_angle(ir: GeometryIR) -> float:
    """The middle of the tooth just before slot 0, from the IR's own winding regions."""

    slot_pitch = _TWO_PI / ir.slot_count
    best: tuple[int, float] | None = None
    for region in ir.regions:
        if region.kind != "SlotWinding" or not region.loops:
            continue
        parts = (region.source_group or "").split(":")
        if len(parts) < 4 or not parts[3].startswith("slot") or not parts[3][4:].isdigit():
            continue
        slot = int(parts[3][4:])
        if best is not None and slot >= best[0]:
            continue
        vertices = _loop_vertices(region.loops[0])
        cx = sum(x for x, _ in vertices) / len(vertices)
        cy = sum(y for _, y in vertices) / len(vertices)
        best = (slot, math.atan2(cy, cx))
    if best is None:
        raise SectorUnsupportedError("no slot winding regions to place the stator cut")
    slot, angle = best
    # Layer regions of one slot share its centre line closely enough; the
    # tooth-to-tooth pitch is exact, so snap to it through the slot grid.
    slot_zero = angle - slot * slot_pitch
    return slot_zero - 0.5 * slot_pitch


def _snap_stator_cut(ir: GeometryIR, guess: float) -> float:
    """Refine the stator cut to the true tooth centre using the tooth regions."""

    slot_pitch = _TWO_PI / ir.slot_count
    best: float | None = None
    for region in ir.regions:
        if region.kind != "StatorTooth" or not region.loops:
            continue
        vertices = _loop_vertices(region.loops[0])
        # A tooth is mirror-symmetric about its centre line, so the mean
        # direction of its vertices is that line.
        cx = sum(x for x, _ in vertices) / len(vertices)
        cy = sum(y for _, y in vertices) / len(vertices)
        delta = _wrap_signed(math.atan2(cy, cx) - guess, slot_pitch)
        if best is None or abs(delta) < abs(best):
            best = delta
    if best is None:
        # A stator drawn as one lamination has no tooth regions; the middle
        # between two slots, from the slot grid, is the tooth centre.
        return guess
    if abs(best) > 0.25 * slot_pitch:
        raise SectorUnsupportedError("the stator teeth are not where the slot grid puts them")
    return guess + best


def _rotor_cut_candidates(ir: GeometryIR) -> list[float]:
    """Angles between poles, modulo one pole pitch, most likely first."""

    pole_pitch = _TWO_PI / ir.pole_count
    sum_cos = sum_sin = 0.0
    found = False
    for region in ir.regions:
        if region.kind != "Magnet" or not region.loops:
            continue
        vertices = _loop_vertices(region.loops[0])
        cx = sum(x for x, _ in vertices) / len(vertices)
        cy = sum(y for _, y in vertices) / len(vertices)
        phase = math.atan2(cy, cx) * ir.pole_count
        sum_cos += math.cos(phase)
        sum_sin += math.sin(phase)
        found = True
    if not found or math.hypot(sum_cos, sum_sin) < 1.0e-9:
        raise SectorUnsupportedError("no magnets to place the rotor cut between")
    pole_axis = math.atan2(sum_sin, sum_cos) / ir.pole_count
    # The magnets of one pole average onto its axis, unless a wide V puts them
    # nearer the neighbours; then the estimate is half a pitch out. Try both.
    return [pole_axis + 0.5 * pole_pitch, pole_axis]


def _loop_from_segments(loop_id: str, segments: list[GeometryIRSegment]) -> GeometryIRLoop:
    return GeometryIRLoop(
        loop_id=loop_id,
        kind="polygon",
        segments=tuple(segments),
        points_mm=tuple(segment.start for segment in segments),
    )


def _piece_area(outer: list[GeometryIRSegment], holes: list[list[GeometryIRSegment]]) -> float:
    return _signed_loop_area(outer) - sum(_signed_loop_area(hole) for hole in holes)


@dataclass
class _Frame:
    """One wedge: the stator's or the rotor's."""

    start_rad: float
    span_rad: float

    def ray_angles(self) -> tuple[float, float]:
        return (self.start_rad % _TWO_PI, (self.start_rad + self.span_rad) % _TWO_PI)


def _on_ray(xy: tuple[float, float], angle: float) -> float | None:
    """Radius of a point if it lies on the ray at ``angle``; None otherwise."""

    radius = math.hypot(xy[0], xy[1])
    if radius <= 5.0 * _ON_LINE_TOL_MM:
        return 0.0
    if math.hypot(xy[0] - radius * math.cos(angle), xy[1] - radius * math.sin(angle)) <= 5.0 * _ON_LINE_TOL_MM:
        return radius
    return None


def _cluster(values: list[float], preferred: list[float]) -> list[float]:
    out: list[float] = []
    for value in sorted(values):
        if out and value - out[-1] <= _RADIUS_CLUSTER_TOL_MM:
            continue
        out.append(value)
    for index, value in enumerate(out):
        for exact in preferred:
            if abs(value - exact) <= _RADIUS_CLUSTER_TOL_MM:
                out[index] = exact
                break
        if value <= _RADIUS_CLUSTER_TOL_MM:
            out[index] = 0.0
    return out


def _nearest(values: list[float], value: float) -> float | None:
    best = min(values, key=lambda candidate: abs(candidate - value), default=None)
    if best is None or abs(best - value) > 10.0 * _RADIUS_CLUSTER_TOL_MM:
        return None
    return best


_Pieces = list[tuple[list[GeometryIRSegment], list[list[GeometryIRSegment]]]]


def _finish_edges(
    pieces_by_key: dict[str, _Pieces],
    frame: _Frame,
    preferred_radii: list[float],
) -> tuple[list[tuple[float, float]], bool]:
    """Give both cut edges of a frame the same breakpoints, exactly one sector apart.

    Rewrites the pieces in place. Returns the radial intervals of the cut edge
    and whether the edge reaches the centre.
    """

    left, right = frame.ray_angles()
    radii: list[float] = []
    for pieces in pieces_by_key.values():
        for outer, holes in pieces:
            for loop in (outer, *holes):
                for segment in loop:
                    if segment.boundary_tag != SECTOR_EDGE_TAG:
                        continue
                    sides = []
                    for xy in (_xy(segment.start), _xy(segment.end)):
                        radius = _on_ray(xy, left)
                        sides.append("left")
                        if radius is None:
                            radius = _on_ray(xy, right)
                            sides[-1] = "right"
                        if radius is None:
                            raise SectorUnsupportedError("a cut edge strays from the sector boundary")
                        radii.append(radius)
                    if sides[0] != sides[1]:
                        # The edge runs through the motor axis: both cut edges start there.
                        radii.append(0.0)
    if not radii:
        raise SectorUnsupportedError("the sector cut touched nothing")
    breakpoints = _cluster(radii, preferred_radii)

    def snap(point: GeometryIRPoint) -> GeometryIRPoint:
        xy = _xy(point)
        for angle in (left, right):
            radius = _on_ray(xy, angle)
            if radius is None:
                continue
            exact = _nearest(breakpoints, radius)
            if exact is None:
                continue
            return GeometryIRPoint(exact * math.cos(angle), exact * math.sin(angle))
        return point

    def edge_radius(point: GeometryIRPoint, angle: float) -> float:
        radius = _on_ray(_xy(point), angle)
        exact = None if radius is None else _nearest(breakpoints, radius)
        if exact is None:
            raise SectorUnsupportedError("a cut edge point is not on a breakpoint")
        return exact

    intervals: dict[str, set[tuple[float, float]]] = {"left": set(), "right": set()}

    def rebuild(loop: list[GeometryIRSegment]) -> list[GeometryIRSegment]:
        out: list[GeometryIRSegment] = []
        for segment in loop:
            segment = replace(segment, start=snap(segment.start), end=snap(segment.end))
            if segment.boundary_tag != SECTOR_EDGE_TAG:
                out.append(segment)
                continue
            def ray_of(point: GeometryIRPoint) -> float | None:
                xy = _xy(point)
                if math.hypot(*xy) <= 5.0 * _ON_LINE_TOL_MM:
                    return None
                for angle in (left, right):
                    if _on_ray(xy, angle) is not None:
                        return angle
                raise SectorUnsupportedError("a cut edge is on neither sector boundary")

            start_ray, end_ray = ray_of(segment.start), ray_of(segment.end)
            if start_ray is not None and end_ray is not None and start_ray != end_ray:
                # Only a half-circle sector has an edge running through the centre.
                if abs(frame.span_rad - math.pi) > 1.0e-12:
                    raise SectorUnsupportedError("a cut edge joins the two sector boundaries")
                halves = [
                    (start_ray, edge_radius(segment.start, start_ray), 0.0),
                    (end_ray, 0.0, edge_radius(segment.end, end_ray)),
                ]
            else:
                angle = start_ray if start_ray is not None else end_ray
                if angle is None:
                    continue
                halves = [(angle, edge_radius(segment.start, angle), edge_radius(segment.end, angle))]
            for angle, r_from, r_to in halves:
                name = "left" if angle == left else "right"
                low, high = min(r_from, r_to), max(r_from, r_to)
                stops = [r for r in breakpoints if low <= r <= high]
                if r_from > r_to:
                    stops.reverse()
                for a, b in zip(stops, stops[1:]):
                    out.append(
                        GeometryIRSegment(
                            "line",
                            GeometryIRPoint(a * math.cos(angle), a * math.sin(angle)),
                            GeometryIRPoint(b * math.cos(angle), b * math.sin(angle)),
                            boundary_tag=SECTOR_EDGE_TAG,
                        )
                    )
                    intervals[name].add((min(a, b), max(a, b)))
        return out

    for key, pieces in pieces_by_key.items():
        pieces_by_key[key] = [(rebuild(outer), [rebuild(hole) for hole in holes]) for outer, holes in pieces]

    if intervals["left"] != intervals["right"]:
        raise SectorUnsupportedError("the two cut edges of the sector do not match")
    ordered = sorted(intervals["left"])
    for (_, high), (low, _) in zip(ordered, ordered[1:]):
        if abs(high - low) > _RADIUS_CLUSTER_TOL_MM:
            raise SectorUnsupportedError("a cut edge has a gap")
    return ordered, bool(ordered) and ordered[0][0] == 0.0


def build_sector_ir(
    ir: GeometryIR,
    symmetry: SectorSymmetry,
    *,
    min_mid_gap_offset_mm: float = 0.05,
) -> SectorIR:
    """Cut a full-circle IR, built at one rotor angle, down to one sector.

    ``min_mid_gap_offset_mm`` is the shortest stator-only arc worth meshing on
    the mid-gap circle; below it the stator cut moves to the rotor cut, which
    stays inside the same tooth.
    """

    if symmetry.repeats < 2:
        raise SectorUnsupportedError("the motor does not repeat")
    span = symmetry.span_rad
    pole_pitch = _TWO_PI / ir.pole_count
    outer_rotor = ir.rotor_layout == "outer"

    airgap = next((region for region in ir.regions if region.kind == "Airgap"), None)
    if airgap is None or len(airgap.loops) != 2:
        raise SectorUnsupportedError("the air gap is not a plain ring")
    # The air gap's faces need not be circles (slot openings, tooth tips,
    # magnet faces); the wedges meet on a circle that clears both of them.
    gap_outer_r = _loop_radial_extent(airgap.loops[0])[0]
    gap_inner_r = _loop_radial_extent(airgap.loops[1])[1]
    if gap_outer_r - gap_inner_r <= 1.0e-6:
        raise SectorUnsupportedError("no circle fits inside the air gap")
    mid_r = 0.5 * (gap_inner_r + gap_outer_r)

    first_tooth = _snap_stator_cut(ir, _stator_cut_angle(ir))

    snap = min_mid_gap_offset_mm / mid_r
    last_error: SectorUnsupportedError | None = None
    for rotor_axis in _rotor_cut_candidates(ir):
        stator_start = _nearest_tooth_cut(ir.slot_count, first_tooth, rotor_axis, pole_pitch)
        offset = _wrap_signed(rotor_axis - stator_start, pole_pitch)
        if abs(offset) * mid_r < 1.0e-9:
            offset = 0.0
        snap_moves = "rotor" if _rotor_cut_can_move(ir, stator_start + offset, span, snap) else "stator"
        if offset != 0.0 and abs(offset) < snap:
            # Too short an arc to mesh well between the cuts: cut the rotor at the
            # tooth, so the stator iron stays in whole slot pitches; a rotor with no
            # room for that cuts the stator where the rotor is instead.
            stator_cut = stator_start if snap_moves == "rotor" else stator_start + offset
            offset = 0.0
        else:
            stator_cut = stator_start
        rotor_cut = stator_cut + offset
        try:
            sector = _build_with_cuts(
                ir, symmetry, airgap, stator_cut, rotor_cut, mid_r, outer_rotor, span, offset,
                slot_pitch_units=abs(stator_cut - stator_start) < 1.0e-12,
            )
            return replace(
                sector, first_tooth_rad=first_tooth, min_mid_gap_offset_mm=min_mid_gap_offset_mm, snap_moves=snap_moves
            )
        except SectorUnsupportedError as exc:
            last_error = exc
    raise last_error or SectorUnsupportedError("no clean rotor cut was found")


def _rotor_cut_can_move(ir: GeometryIR, rotor_cut: float, span: float, shift: float) -> bool:
    """Whether the rotor cut can move ``shift`` either way without crossing a magnet or
    passing a rotor corner within a hair: a rotor drawn with corners on its pole
    boundary (the published Prius) would get a sliver where the moved cut grazes one."""

    if shift <= 0.0:
        return True
    for angle in (rotor_cut, rotor_cut + span):
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        for region in ir.regions:
            if region.motion_group != "rotor":
                continue
            for loop in region.loops:
                for segment in loop.segments:
                    x, y = _xy(segment.start)
                    along = x * cos_a + y * sin_a
                    if along > 1.0e-6 and abs(x * sin_a - y * cos_a) <= 2.0 * shift * along:
                        return False
    for region in ir.regions:
        if region.kind != "Magnet":
            continue
        for start in (rotor_cut - shift, rotor_cut + shift):
            try:
                pieces = _clip_region_loops(region.loops, start, span)
            except SectorUnsupportedError:
                return False
            if pieces and (
                len(pieces) != 1
                or abs(_piece_area(*pieces[0]) - _signed_area_of_region(region)) > 1.0e-6 * max(1.0, region.area_mm2)
            ):
                return False
    return True


def _nearest_tooth_cut(slot_count: int, first_tooth: float, rotor_axis: float, pole_pitch: float) -> float:
    """The tooth centre that leaves the shortest stator-only arc to the rotor cut.

    Any tooth centre can start the sector: the geometry and the winding repeat
    over its span. A fixed tooth lets the rotor cut drift up to half a pole
    pitch away as the rotor turns, so the mesh where the two wedges meet changes
    steadily over a sweep; on the shoed 8p/12s example that moved the cogging
    fundamental 7% from a full-motor solve. The nearest tooth keeps the two cuts
    within half the common pitch of slots and poles. At exactly half, the
    negative offset wins, so a position one period on is cut the same way and
    its mesh is the same mesh turned; then the tooth nearest the first one.
    """

    slot_pitch = _TWO_PI / slot_count

    def rank(step: int) -> tuple[float, int, int]:
        offset = _wrap_signed(rotor_axis - (first_tooth + step * slot_pitch), pole_pitch)
        return (round(abs(offset), 9), 0 if round(offset, 9) <= 0 else 1, abs(step))

    steps = range(-(slot_count // 2), slot_count - slot_count // 2)
    return first_tooth + min(steps, key=rank) * slot_pitch


# A pattern longer than this is not worth sending to a viewer.
_MAX_CUT_TABLE_ENTRIES = 4096


def sector_cuts_by_turn(
    slot_count: int,
    pole_count: int,
    first_tooth_deg: float,
    rotor_cut_deg: float,
    mid_gap_radius_mm: float = 0.0,
    min_mid_gap_offset_mm: float = 0.0,
    snap_moves: str = "rotor",
) -> list[dict[str, float | bool]] | None:
    """Where one sector is cut at every rotor angle, from a sector meshed at one.

    These are the cuts ``build_sector_ir`` makes for a mesh built at that
    angle, by the same rule. A turn is the rotor's rotation from the meshed
    angle, in degrees, counter-clockwise positive (a sweep turns it
    clockwise), over one revolution. Each entry holds from its
    ``turn_from_deg`` to the next one's: ``stator_cut_deg`` in the stator's
    frame and ``rotor_cut_deg`` in the rotor's own frame, before the turn.
    Neither cut moves in its own frame within an entry; both step to the next
    nearest tooth and pole gap once per common pitch of slots and poles. Where
    the two cuts are closer on the mid-gap circle than
    ``min_mid_gap_offset_mm``, one moves onto the other: the rotor is cut at the
    tooth (``rotor_on_stator_cut``), or, for a rotor with no room for that
    (``snap_moves`` "stator"), the stator where the rotor is
    (``stator_on_rotor_cut``). None when the pattern would need more than a few
    thousand entries.
    """

    steps_per_turn = math.lcm(slot_count, pole_count)
    if 3 * steps_per_turn > _MAX_CUT_TABLE_ENTRIES:
        return None
    pole_pitch = _TWO_PI / pole_count
    common = _TWO_PI / steps_per_turn
    first_tooth = math.radians(first_tooth_deg)
    # The rotor cut lies between two poles: the rule needs it only modulo a pole pitch.
    rotor_axis = math.radians(rotor_cut_deg)
    # Every tooth-to-gap offset differs from every other by a whole common pitch, so
    # the nearest pair changes when the offset reaches half of one.
    first_step = (first_tooth - rotor_axis + 0.5 * common) % common
    starts = [0.0] + [
        first_step + step * common
        for step in range(steps_per_turn)
        if 1.0e-9 < first_step + step * common < _TWO_PI - 1.0e-9
    ]
    # The stator cut moves onto the rotor cut within this angle either side of
    # the turn where the two meet (an offset of exactly zero needs no move).
    snap = min_mid_gap_offset_mm / mid_gap_radius_mm if mid_gap_radius_mm > 0.0 else 0.0
    entries: list[dict[str, float | bool]] = []

    def add(turn: float, stator_cut: float, rotor_cut: float, snapped: bool) -> None:
        entry: dict[str, float | bool] = {
            "turn_from_deg": round(math.degrees(turn), 9),
            "stator_cut_deg": round(math.degrees(stator_cut) % 360.0, 9),
            "rotor_cut_deg": round(math.degrees(rotor_cut) % 360.0, 9),
        }
        if snapped:
            entry["rotor_on_stator_cut" if snap_moves == "rotor" else "stator_on_rotor_cut"] = True
        entries.append(entry)

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else _TWO_PI
        middle = 0.5 * (start + end)
        axis = rotor_axis + middle
        stator_cut = _nearest_tooth_cut(slot_count, first_tooth, axis, pole_pitch)
        offset = _wrap_signed(axis - stator_cut, pole_pitch)
        rotor_cut = stator_cut + offset - middle
        # Within an entry the offset grows one for one with the turn.
        meet = middle - offset
        snap_from, snap_to = max(start, meet - snap), min(end, meet + snap)
        if snap_to - snap_from <= 1.0e-12:
            add(start, stator_cut, rotor_cut, False)
            continue
        if snap_from - start > 1.0e-12:
            add(start, stator_cut, rotor_cut, False)
        add(snap_from, stator_cut, rotor_cut, True)
        if end - snap_to > 1.0e-12:
            add(snap_to, stator_cut, rotor_cut, False)
    return entries


def _build_with_cuts(
    ir: GeometryIR,
    symmetry: SectorSymmetry,
    airgap: GeometryIRRegion,
    stator_cut: float,
    rotor_cut: float,
    mid_r: float,
    outer_rotor: bool,
    span: float,
    offset: float,
    *,
    slot_pitch_units: bool = True,
) -> SectorIR:
    stator_frame = _Frame(stator_cut, span)
    slot_pitch = _TWO_PI / ir.slot_count
    rotor_frame = _Frame(rotor_cut, span)

    steps = max(1, math.ceil(span / _MAX_MID_ARC_RAD - 1.0e-9))
    mid_angles: list[float] = []
    for start in (stator_cut, rotor_cut):
        for repeat in range(symmetry.repeats):
            for step in range(steps):
                mid_angles.append((start + repeat * span + step * span / steps) % _TWO_PI)
    # Keep the exact ray angles so cut points and mid-gap breakpoints coincide bit for bit.
    exact = [*stator_frame.ray_angles(), *rotor_frame.ray_angles()]
    mid_angles = _unique_angles([*exact, *mid_angles])
    for index, angle in enumerate(mid_angles):
        for ray in exact:
            if abs(angle - ray) < 1.0e-10:
                mid_angles[index] = ray
    mid_loop = _circle_with_breakpoints("airgap_mid", mid_r, mid_angles, SECTOR_MID_GAP_TAG)

    # loops[0] is the air gap's outer circle: the stator side for an inner rotor.
    if outer_rotor:
        stator_half = (mid_loop, airgap.loops[1])
        rotor_half = (airgap.loops[0], mid_loop)
    else:
        stator_half = (airgap.loops[0], mid_loop)
        rotor_half = (mid_loop, airgap.loops[1])

    stator_pieces: dict[str, _Pieces] = {}
    rotor_pieces: dict[str, _Pieces] = {}
    iron_steps: dict[str, list[int]] = {}
    for region in ir.regions:
        if region.kind == "Airgap":
            continue
        if region.motion_group == "stationary":
            frame, target = stator_frame, stator_pieces
        elif region.motion_group == "rotor":
            frame, target = rotor_frame, rotor_pieces
        else:
            raise SectorUnsupportedError(f"region {region.region_id} has no stator or rotor frame")
        if slot_pitch_units and region.motion_group == "stationary" and region.kind in _STATOR_IRON_KINDS:
            pieces, iron_steps[region.region_id] = _slot_pitch_pieces(
                region, stator_cut, slot_pitch, symmetry.slots_per_sector, _points_of_other_regions(ir, region)
            )
        else:
            pieces = _clip_region_loops(region.loops, frame.start_rad, frame.span_rad)
        if not pieces:
            continue
        if region.kind == "Magnet" and (
            len(pieces) != 1
            or abs(_piece_area(*pieces[0]) - _signed_area_of_region(region)) > 1.0e-6 * max(1.0, region.area_mm2)
        ):
            raise SectorUnsupportedError(f"the rotor cut passes through {region.region_id}")
        if region.kind == "SlotWinding" and (
            len(pieces) != 1
            or abs(_piece_area(*pieces[0]) - _signed_area_of_region(region)) > 1.0e-6 * max(1.0, region.area_mm2)
        ):
            raise SectorUnsupportedError(f"the stator cut passes through {region.region_id}")
        target[region.region_id] = pieces
    stator_pieces["airgap#stator"] = _clip_region_loops(stator_half, stator_frame.start_rad, span)
    rotor_pieces["airgap#rotor"] = _clip_region_loops(rotor_half, rotor_frame.start_rad, span)
    if not stator_pieces["airgap#stator"] or not rotor_pieces["airgap#rotor"]:
        raise SectorUnsupportedError("the air gap vanished in the sector cut")
    if iron_steps:
        # The slot-pitch cuts end on boundaries the iron shares (the tooth tips with
        # the air gap): break those boundaries there too, or the mesh would not join.
        _break_at_points(
            {key: value for key, value in stator_pieces.items() if key not in iron_steps},
            _slot_pitch_cut_points(stator_pieces[key] for key in iron_steps if key in stator_pieces),
        )

    stator_intervals, stator_apex = _finish_edges(stator_pieces, stator_frame, [mid_r])
    rotor_intervals, rotor_apex = _finish_edges(rotor_pieces, rotor_frame, [mid_r])

    pairs: list[SectorCurvePair] = []
    for frame, intervals in ((stator_frame, stator_intervals), (rotor_frame, rotor_intervals)):
        left, right = frame.ray_angles()
        for low, high in intervals:
            pairs.append(
                SectorCurvePair(
                    kind="line",
                    master_start=(low * math.cos(left), low * math.sin(left)),
                    master_end=(high * math.cos(left), high * math.sin(left)),
                    slave_start=(low * math.cos(right), low * math.sin(right)),
                    slave_end=(high * math.cos(right), high * math.sin(right)),
                    rotation_rad=span,
                )
            )
    if offset != 0.0:
        # The stator-only arc of the mid-gap circle and the rotor-only arc one sector away.
        if offset > 0.0:
            arc_start, arc_end, shift = stator_cut, stator_cut + offset, span
        else:
            arc_start, arc_end, shift = stator_cut + span + offset, stator_cut + span, -span
        sweep = arc_end - arc_start
        inside = sorted(
            ((angle - arc_start) % _TWO_PI, angle)
            for angle in mid_angles
            if (angle - arc_start) % _TWO_PI <= sweep + 1.0e-10 or _TWO_PI - (angle - arc_start) % _TWO_PI < 1.0e-10
        )
        stops = [angle for _, angle in sorted(((0.0 if _TWO_PI - d < 1.0e-10 else d), a) for d, a in inside)]
        if len(stops) < 2:
            raise SectorUnsupportedError("the mid-gap overlap arc has no breakpoints")

        def mid_point(angle: float) -> tuple[float, float]:
            exact_angle = angle % _TWO_PI
            for candidate in mid_angles:
                if abs(candidate - exact_angle) < 1.0e-10 or abs(abs(candidate - exact_angle) - _TWO_PI) < 1.0e-10:
                    exact_angle = candidate
                    break
            else:
                raise SectorUnsupportedError("a mid-gap arc has no partner one sector away")
            return (mid_r * math.cos(exact_angle), mid_r * math.sin(exact_angle))

        for a, b in zip(stops, stops[1:]):
            pairs.append(
                SectorCurvePair(
                    kind="arc",
                    master_start=mid_point(a),
                    master_end=mid_point(b),
                    slave_start=mid_point(a + shift),
                    slave_end=mid_point(b + shift),
                    rotation_rad=shift,
                    radius_mm=mid_r,
                )
            )

    pieces_by_region: dict[str, tuple[SectorPiece, ...]] = {}
    iron_units: list[tuple[str, int, int]] = []
    regions: list[GeometryIRRegion] = []
    for region in ir.regions:
        if region.kind == "Airgap":
            raw = [*stator_pieces["airgap#stator"], *rotor_pieces["airgap#rotor"]]
        else:
            raw = stator_pieces.get(region.region_id) or rotor_pieces.get(region.region_id) or []
        if not raw:
            continue
        pieces: list[SectorPiece] = []
        loops: list[GeometryIRLoop] = []
        area = 0.0
        for index, (outer, holes) in enumerate(raw):
            outer_loop = _loop_from_segments(f"{region.region_id}_sector_{index}", outer)
            hole_loops = tuple(
                _loop_from_segments(f"{region.region_id}_sector_{index}_hole_{k}", hole)
                for k, hole in enumerate(holes)
            )
            pieces.append(SectorPiece(outer_loop, hole_loops))
            loops.extend((outer_loop, *hole_loops))
            area += _piece_area(outer, holes)
        pieces_by_region[region.region_id] = tuple(pieces)
        iron_units.extend((region.region_id, index, step) for index, step in enumerate(iron_steps.get(region.region_id, ())))
        regions.append(replace(region, loops=tuple(loops), area_mm2=area))

    metadata = dict(ir.metadata)
    metadata.update(
        {
            "sector_repeats": symmetry.repeats,
            "sector_anti_periodic": symmetry.anti_periodic,
            "sector_span_deg": symmetry.span_deg,
            "sector_stator_start_deg": math.degrees(stator_cut),
            "sector_rotor_start_deg": math.degrees(rotor_cut),
            "sector_mid_gap_radius_mm": mid_r,
        }
    )
    return SectorIR(
        ir=replace(ir, regions=tuple(regions), metadata=metadata),
        pieces_by_region=pieces_by_region,
        symmetry=symmetry,
        stator_start_rad=stator_cut,
        rotor_start_rad=rotor_cut,
        mid_gap_radius_mm=mid_r,
        curve_pairs=tuple(pairs),
        apex_at_centre=stator_apex or rotor_apex,
        stator_iron_units=tuple(iron_units),
        slot_pitch_rad=slot_pitch if iron_units else 0.0,
    )


def _slot_pitch_pieces(
    region: GeometryIRRegion,
    stator_cut: float,
    slot_pitch: float,
    pitches: int,
    shared_points: set[tuple[int, int]],
) -> tuple[_Pieces, list[int]]:
    """A stator iron region cut into slot-pitch pieces at the tooth centres of the sector.

    The cuts inside the sector are tagged apart from the sector's own edges: they
    are not tied to anything, they only let the mesher copy one pitch's mesh. An
    arc drawn in parts whose joins no other region uses (a hub bore drawn as four
    quarter circles) is joined up, so every pitch has the same outline.
    """

    inner_rays = [stator_cut + step * slot_pitch for step in range(1, pitches)]
    pieces: _Pieces = []
    steps: list[int] = []

    def tidy(loop: list[GeometryIRSegment]) -> list[GeometryIRSegment]:
        return _join_unshared_arcs(_retag_inner_cuts(loop, inner_rays), shared_points)

    for step in range(pitches):
        for outer, holes in _clip_region_loops(region.loops, stator_cut + step * slot_pitch, slot_pitch):
            pieces.append((tidy(outer), [tidy(hole) for hole in holes]))
            steps.append(step)
    return pieces, steps


def _point_key(xy: tuple[float, float]) -> tuple[int, int]:
    return (round(xy[0] * 1.0e6), round(xy[1] * 1.0e6))


def _points_of_other_regions(ir: GeometryIR, region: GeometryIRRegion) -> set[tuple[int, int]]:
    return {
        _point_key(_xy(point))
        for other in ir.regions
        if other.region_id != region.region_id
        for loop in other.loops
        for segment in loop.segments
        for point in (segment.start, segment.end)
    }


def _join_unshared_arcs(loop: list[GeometryIRSegment], shared_points: set[tuple[int, int]]) -> list[GeometryIRSegment]:
    """Join consecutive arcs of one circle whose join no other region uses."""

    def joinable(a: GeometryIRSegment, b: GeometryIRSegment) -> bool:
        return (
            a.kind == "arc" == b.kind
            and a.center is not None and b.center is not None
            and _point_key(_xy(a.center)) == _point_key(_xy(b.center))
            and a.radius_mm is not None and b.radius_mm is not None
            and abs(a.radius_mm - b.radius_mm) <= 1.0e-9
            and a.boundary_tag == b.boundary_tag
            and (a.sweep_deg or 0.0) * (b.sweep_deg or 0.0) > 0.0
            and abs((a.sweep_deg or 0.0) + (b.sweep_deg or 0.0)) < 179.0
            and _point_key(_xy(a.end)) not in shared_points
        )

    out = list(loop)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for index in range(len(out)):
            a, b = out[index], out[(index + 1) % len(out)]
            if joinable(a, b):
                merged = replace(a, end=b.end, sweep_deg=(a.sweep_deg or 0.0) + (b.sweep_deg or 0.0))
                if index + 1 < len(out):
                    out[index:index + 2] = [merged]
                else:
                    out = [merged, *out[1:-1]]
                changed = True
                break
    return out


def _slot_pitch_cut_points(pieces_of_regions: Iterable[_Pieces]) -> list[tuple[float, float]]:
    points: dict[tuple[int, int], tuple[float, float]] = {}
    for pieces in pieces_of_regions:
        for outer, holes in pieces:
            for loop in (outer, *holes):
                for segment in loop:
                    if segment.boundary_tag == SECTOR_SLOT_PITCH_TAG:
                        for point in (segment.start, segment.end):
                            points.setdefault(_point_key(_xy(point)), _xy(point))
    return list(points.values())


def _break_at_points(pieces_by_key: dict[str, _Pieces], points: list[tuple[float, float]]) -> None:
    """Split, in place, every segment that passes through one of ``points``."""

    if not points:
        return
    for pieces in pieces_by_key.values():
        for piece_index, (outer, holes) in enumerate(pieces):
            loops = [_break_loop(loop, points) for loop in (outer, *holes)]
            pieces[piece_index] = (loops[0], loops[1:])


def _break_loop(loop: list[GeometryIRSegment], points: list[tuple[float, float]]) -> list[GeometryIRSegment]:
    out: list[GeometryIRSegment] = []
    for segment in loop:
        inside: list[tuple[float, tuple[float, float]]] = []
        for xy in points:
            fraction = _fraction_along(segment, xy)
            if fraction is not None and 1.0e-9 < fraction < 1.0 - 1.0e-9:
                inside.append((fraction, xy))
        inside.sort()
        out.extend(_split(segment, [f for f, _ in inside], [xy for _, xy in inside]))
    return out


def _fraction_along(segment: GeometryIRSegment, xy: tuple[float, float]) -> float | None:
    """Where ``xy`` lies along a segment, as a fraction of it; None off the segment."""

    tol = 5.0 * _ON_LINE_TOL_MM
    start, end = _xy(segment.start), _xy(segment.end)
    if segment.kind == "arc":
        center = _xy(segment.center)  # type: ignore[arg-type]
        radius = segment.radius_mm or 0.0
        if abs(math.hypot(xy[0] - center[0], xy[1] - center[1]) - radius) > tol:
            return None
        sweep = _arc_sweep_rad(segment)
        if abs(sweep) < 1.0e-15:
            return None
        a0 = math.atan2(start[1] - center[1], start[0] - center[0])
        a = math.atan2(xy[1] - center[1], xy[0] - center[0])
        delta = (a - a0) % _TWO_PI if sweep > 0 else -((a0 - a) % _TWO_PI)
        fraction = delta / sweep
        return fraction if 0.0 <= fraction <= 1.0 else None
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1.0e-24:
        return None
    t = ((xy[0] - start[0]) * dx + (xy[1] - start[1]) * dy) / length_sq
    if abs((xy[0] - start[0]) * dy - (xy[1] - start[1]) * dx) / math.sqrt(length_sq) > tol:
        return None
    return t if 0.0 <= t <= 1.0 else None


def _retag_inner_cuts(loop: list[GeometryIRSegment], inner_rays: list[float]) -> list[GeometryIRSegment]:
    out = []
    for segment in loop:
        if segment.boundary_tag == SECTOR_EDGE_TAG and any(
            _on_ray(_xy(segment.start), ray) is not None and _on_ray(_xy(segment.end), ray) is not None
            for ray in inner_rays
        ):
            segment = replace(segment, boundary_tag=SECTOR_SLOT_PITCH_TAG)
        out.append(segment)
    return out


def rotated_sector_ir(sector: SectorIR, angle_rad: float, *, digits: int = 9) -> SectorIR:
    """The same sector turned about the motor axis, with coordinates rounded.

    The mesher meshes every position's sector turned so its stator cut lies on the
    same tooth; rounding makes that slot pitch's points identical from one position
    to the next, so Gmsh meshes it the same way each time.
    """

    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

    def turn(x: float, y: float) -> tuple[float, float]:
        return (round(x * cos_a - y * sin_a, digits) + 0.0, round(x * sin_a + y * cos_a, digits) + 0.0)

    def point(p: GeometryIRPoint | None) -> GeometryIRPoint | None:
        if p is None:
            return None
        if abs(p.x_mm) <= 1.0e-12 and abs(p.y_mm) <= 1.0e-12:
            return GeometryIRPoint(0.0, 0.0)
        return _pt(turn(p.x_mm, p.y_mm))

    def loop(item: GeometryIRLoop) -> GeometryIRLoop:
        return replace(
            item,
            segments=tuple(replace(seg, start=point(seg.start), end=point(seg.end), center=point(seg.center)) for seg in item.segments),
            points_mm=tuple(point(p) for p in item.points_mm),
        )

    loops: dict[str, GeometryIRLoop] = {}

    def cached(item: GeometryIRLoop) -> GeometryIRLoop:
        if item.loop_id not in loops:
            loops[item.loop_id] = loop(item)
        return loops[item.loop_id]

    pieces = {
        key: tuple(SectorPiece(cached(piece.outer), tuple(cached(hole) for hole in piece.holes)) for piece in value)
        for key, value in sector.pieces_by_region.items()
    }
    regions = []
    for region in sector.ir.regions:
        magnetization = region.magnetization_xy
        if magnetization is not None:
            mx, my = magnetization
            magnetization = (mx * cos_a - my * sin_a, mx * sin_a + my * cos_a)
        regions.append(replace(region, loops=tuple(cached(item) for item in region.loops), magnetization_xy=magnetization))
    pairs = tuple(
        replace(
            pair,
            master_start=turn(*pair.master_start),
            master_end=turn(*pair.master_end),
            slave_start=turn(*pair.slave_start),
            slave_end=turn(*pair.slave_end),
        )
        for pair in sector.curve_pairs
    )
    return replace(
        sector,
        ir=replace(sector.ir, regions=tuple(regions)),
        pieces_by_region=pieces,
        curve_pairs=pairs,
        stator_start_rad=sector.stator_start_rad + angle_rad,
        rotor_start_rad=sector.rotor_start_rad + angle_rad,
        first_tooth_rad=None if sector.first_tooth_rad is None else sector.first_tooth_rad + angle_rad,
    )


def _signed_area_of_region(region: GeometryIRRegion) -> float:
    """Outline area minus holes, from the loops themselves."""

    areas = [abs(_signed_loop_area([_normalized(s) for s in loop.segments])) for loop in region.loops]
    return areas[0] - sum(areas[1:]) if areas else 0.0
