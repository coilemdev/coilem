"""Pinned geometry helpers for the Phase F reference adapter."""

from __future__ import annotations

import math

from backend.geometry_drawer import MotorGeometry
from backend.models import MotorConfig
from backend.reference_models import reference_model


def xy(point):
    return point.x_mm, point.y_mm


def polyline(loop):
    points = []
    for segment in loop.segments:
        a = xy(segment.start)
        points.append(a)
        if segment.kind != "arc":
            continue
        c = xy(segment.center)
        radius = math.hypot(a[0] - c[0], a[1] - c[1])
        start = math.atan2(a[1] - c[1], a[0] - c[0])
        count = max(1, math.ceil(abs(segment.sweep_deg) / 0.2))
        for i in range(1, count):
            angle = start + math.radians(segment.sweep_deg) * i / count
            points.append((c[0] + radius * math.cos(angle), c[1] + radius * math.sin(angle)))
    return points


def inside(point, polygon):
    x, y = point
    hit = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def label(region):
    loops = [polyline(loop) for loop in region.loops]

    def valid(point):
        return inside(point, loops[0]) and not any(inside(point, hole) for hole in loops[1:])

    outer = loops[0]
    crosses = [a[0] * b[1] - b[0] * a[1] for a, b in zip(outer, outer[1:] + outer[:1])]
    area2 = sum(crosses)
    center = (
        sum((a[0] + b[0]) * cross for a, b, cross in zip(outer, outer[1:] + outer[:1], crosses)) / (3 * area2),
        sum((a[1] + b[1]) * cross for a, b, cross in zip(outer, outer[1:] + outer[:1], crosses)) / (3 * area2),
    )
    if valid(center):
        return center
    # Move from each curved boundary towards the region interior. This also
    # handles annuli and the connected air surrounding every rotor magnet.
    for loop in region.loops:
        for segment in loop.segments:
            a, b = xy(segment.start), xy(segment.end)
            if segment.kind == "arc":
                c = xy(segment.center)
                radius = math.hypot(a[0] - c[0], a[1] - c[1])
                angle = math.atan2(a[1] - c[1], a[0] - c[0]) + math.radians(segment.sweep_deg) / 2
                midpoint = (c[0] + radius * math.cos(angle), c[1] + radius * math.sin(angle))
                normal = (math.cos(angle), math.sin(angle))
            else:
                midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                normal = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
            for distance in (0.02, 0.05, 0.1, 0.2, 0.4):
                for sign in (1, -1):
                    point = (midpoint[0] + sign * distance * normal[0], midpoint[1] + sign * distance * normal[1])
                    if valid(point):
                        return point
    raise ValueError("No interior label for " + region.region_id)


def edge_midpoint(segment):
    a, b = xy(segment.start), xy(segment.end)
    if segment.kind == "line":
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    c = xy(segment.center)
    radius = math.hypot(a[0] - c[0], a[1] - c[1])
    angle = math.atan2(a[1] - c[1], a[0] - c[0]) + math.radians(segment.sweep_deg) / 2
    return c[0] + radius * math.cos(angle), c[1] + radius * math.sin(angle)


def _rotate_point(point: tuple[float, float], angle_rad: float) -> tuple[float, float]:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    x, y = point
    return (x * c - y * s, x * s + y * c)


def _rotate_points(
    points: tuple[tuple[float, float], ...],
    angle_rad: float,
) -> tuple[tuple[float, float], ...]:
    return tuple(_rotate_point(point, angle_rad) for point in points)


def _rotate_magnets_in_place(geom: MotorGeometry, rotor_angle_rad: float) -> None:
    if abs(rotor_angle_rad) <= 1.0e-12:
        return
    for magnet in geom.magnets:
        magnet.center_angle_rad += rotor_angle_rad
        magnet.magnetization_angle_deg = (magnet.magnetization_angle_deg + math.degrees(rotor_angle_rad)) % 360.0
        if magnet.corners_mm is not None:
            magnet.corners_mm = _rotate_points(magnet.corners_mm, rotor_angle_rad)
        if magnet.pocket_corners_mm is not None:
            magnet.pocket_corners_mm = _rotate_points(
                magnet.pocket_corners_mm,
                rotor_angle_rad,
            )
        if magnet.pocket_label_mm is not None:
            magnet.pocket_label_mm = _rotate_point(magnet.pocket_label_mm, rotor_angle_rad)
    for pocket in geom.rotor_air_pockets:
        pocket.corners_mm = _rotate_points(pocket.corners_mm, rotor_angle_rad)
        if pocket.label_mm is not None:
            pocket.label_mm = _rotate_point(pocket.label_mm, rotor_angle_rad)


def _clockwise_excitation_config(config: MotorConfig) -> MotorConfig:
    """Mirror the q-axis excitation into Magneto2D's native CCW frame.

    A launch-surface clockwise position ``theta_ui`` is solved at the native
    position ``-theta_ui``. Mirroring only that rotor position is incomplete:
    the native CCW motoring source angle ``theta - 90 + gamma`` would still
    produce CCW torque. The full coordinate reflection is

        -(theta_ui - 90 + gamma) = theta_native + 90 - gamma

    Existing mesh producers resolve source angle as ``theta - 90 + gamma``,
    so the equivalent internal gamma is ``180 - gamma`` modulo 360 degrees.
    Keep this transform isolated to the current-bearing mesh artifact; the
    user config and reported gamma remain unchanged.
    """

    mirrored = config.model_copy(deep=True)
    if mirrored.solve_params is None:
        raise ValueError("magneto2d solve requires solve_params")
    reference = reference_model(config)
    if reference is not None and reference.excitation_sample is not None:
        return mirrored
    if mirrored.solve_params.excitation_mode == "ideal_six_step_120":
        # Six-step source synthesis is rotor-position based; gamma is not an
        # input. Mark the public frame explicitly and leave the ignored legacy
        # current angle untouched for stable persistence/cache identity.
        mirrored.solve_params.excitation_rotation_convention = "clockwise_positive_ui"
        return mirrored
    gamma_deg = float(mirrored.solve_params.current_angle_deg)
    mirrored_gamma_deg = 180.0 - gamma_deg
    while mirrored_gamma_deg > 180.0:
        mirrored_gamma_deg -= 360.0
    while mirrored_gamma_deg < -180.0:
        mirrored_gamma_deg += 360.0
    mirrored.solve_params.current_angle_deg = mirrored_gamma_deg
    return mirrored
