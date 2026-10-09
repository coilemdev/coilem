"""Solver-backed field fixtures used by the fundamentals-first lesson track."""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from backend.field_lines import generate_contour_levels, generate_contour_segments
from backend.gmsh_solver import (
    _GMSH_API_LOCK,
    GMSH_AVAILABLE,
    _add_threshold_field,
    _extract_gmsh_triangles,
    gmsh,
)
from backend.magneto2d_adapter import Magneto2DExecutionError, ensure_magneto2d_binary
from backend.solver_environment import ISOLATED_RUNTIME, solver_process_environment

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOMAIN_X_MIN_MM = -50.0
_DOMAIN_X_MAX_MM = 50.0
_DOMAIN_Y_MIN_MM = -34.0
_DOMAIN_Y_MAX_MM = 34.0
_TEACHING_DEPTH_MM = 10.0
_MAGNET_HALF_WIDTH_MM = 18.0
_MAGNET_HALF_HEIGHT_MM = 6.0
_WIRE_FIELD_REFERENCE_CURRENT_A = 16.0
_WIRE_FIELD_REFERENCE_CONTOUR_COUNT = 16
_FORCE_MAGNET_WIDTH_MM = 24.0
_FORCE_MAGNET_HALF_HEIGHT_MM = 6.0
_FORCE_MIN_POLE_GAP_MM = 0.5
_FORCE_MAX_POLE_GAP_MM = 16.0
_LINEAR_CAPSTONE_MAGNET_CENTERS_MM = (-27.0, -9.0, 9.0, 27.0)
_LINEAR_CAPSTONE_MAGNET_HALF_WIDTH_MM = 7.0
_LINEAR_CAPSTONE_MAGNET_BOTTOM_MM = -8.0
_LINEAR_CAPSTONE_MAGNET_TOP_MM = 0.0
_LINEAR_CAPSTONE_BACK_IRON_BOTTOM_MM = -14.0
_LINEAR_CAPSTONE_BACK_IRON_TOP_MM = -8.0
_LINEAR_CAPSTONE_BACK_IRON_HALF_WIDTH_MM = 39.0
_LINEAR_CAPSTONE_WIRE_RADIUS_MM = 3.0
_LINEAR_CAPSTONE_WORKER_TIMEOUT_S = 110.0
_ROTOR_CHASE_ROTOR_LENGTH_MM = 14.0
_ROTOR_CHASE_ROTOR_THICKNESS_MM = 6.0
_ROTOR_CHASE_COIL_RADIUS_MM = 3.0
_ROTOR_CHASE_COIL_Y_MM = 10.0
_ROTOR_CHASE_COIL_TURNS = 1008
_ROTATING_FIELD_COIL_RADIUS_MM = 5.0
_ROTATING_FIELD_COIL_OFFSET_MM = 22.0
_ROTATING_FIELD_DOMAIN_HALF_MM = 42.0
_ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM = 7.0
_ROTATING_FIELD_MOTOR_CORE_INNER_MM = 11.0
_ROTATING_FIELD_MOTOR_CORE_OUTER_MM = 34.0
_ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM = 5.5
_ROTATING_FIELD_MOTOR_COIL_RADIUS_MM = 2.4
_ROTATING_FIELD_MOTOR_COIL_CENTER_MM = 22.0
_ROTATING_FIELD_MOTOR_COIL_SIDE_MM = 9.0
_ROTATING_FIELD_MOTOR_LAG_DEG = 15.0
_THREE_PHASE_MOTOR_CORE_INNER_MM = 11.0
_THREE_PHASE_MOTOR_CORE_OUTER_MM = 35.0
_THREE_PHASE_MOTOR_CORE_HALF_WIDTH_MM = 4.2
_THREE_PHASE_MOTOR_COIL_RADIUS_MM = 2.1
_THREE_PHASE_MOTOR_COIL_CENTER_MM = 23.0
_THREE_PHASE_MOTOR_COIL_SIDE_MM = 7.2
_ROTATING_FIELD_STEP_DEG = 45.0 / 4.0
_ROTATING_FIELD_ANGLES_DEG = tuple(
    index * _ROTATING_FIELD_STEP_DEG
    for index in range(round(360.0 / _ROTATING_FIELD_STEP_DEG))
)


def _wire_field_absolute_contour_levels(
    az_nodal: list[float],
    current_a: float,
) -> list[float]:
    """Keep the wire-only contour interval fixed across the lesson current sweep."""

    finite_values = [float(value) for value in az_nodal if math.isfinite(float(value))]
    current_magnitude = abs(current_a)
    if not finite_values or current_magnitude <= 1.0e-9:
        return []

    dominant_extreme = max(finite_values, key=abs)
    amplitude = abs(dominant_extreme)
    if amplitude <= 1.0e-12:
        return []

    reference_amplitude = amplitude * _WIRE_FIELD_REFERENCE_CURRENT_A / current_magnitude
    contour_interval = reference_amplitude / (_WIRE_FIELD_REFERENCE_CONTOUR_COUNT + 1)
    direction = 1.0 if dominant_extreme >= 0.0 else -1.0
    levels = [
        direction * contour_interval * index
        for index in range(1, _WIRE_FIELD_REFERENCE_CONTOUR_COUNT + 1)
        if contour_interval * index < amplitude * (1.0 - 1.0e-9)
    ]
    return sorted(levels)


def _teaching_mesh_sizes(mesh_density: str) -> tuple[float, float, float, float]:
    """Return base, far-field, corner, and corner-influence sizes in mm."""

    # Match the application's regular Gmsh density ladder.  The original
    # teaching fixture used 2 mm for "normal", which produced only ~3.4k
    # triangles over this 100 x 68 mm domain and made the element-wise |B|
    # map look like a coarse preview.
    base_lc_mm = {"coarse": 2.0, "normal": 1.0, "fine": 0.5}[mesh_density]
    return (
        base_lc_mm,
        base_lc_mm * 1.3,
        max(0.22, base_lc_mm * 0.24),
        max(2.0, base_lc_mm * 2.5),
    )


def _point_tags_at(coordinates_mm: list[tuple[float, float]]) -> list[int]:
    wanted = {(round(x, 6), round(y, 6)) for x, y in coordinates_mm}
    tags: list[int] = []
    for _dim, tag in gmsh.model.getEntities(0):
        coordinate = gmsh.model.getValue(0, tag, [])
        key = (round(float(coordinate[0]), 6), round(float(coordinate[1]), 6))
        if key in wanted:
            tags.append(int(tag))
    return sorted(set(tags))


def _outer_boundary_nodes(
    nodes_mm: list[list[float]],
    *,
    x_min_mm: float = _DOMAIN_X_MIN_MM,
    x_max_mm: float = _DOMAIN_X_MAX_MM,
    y_min_mm: float = _DOMAIN_Y_MIN_MM,
    y_max_mm: float = _DOMAIN_Y_MAX_MM,
) -> list[int]:
    tolerance_mm = 1.0e-6
    return [
        index
        for index, (x_mm, y_mm) in enumerate(nodes_mm)
        if abs(x_mm - x_min_mm) <= tolerance_mm
        or abs(x_mm - x_max_mm) <= tolerance_mm
        or abs(y_mm - y_min_mm) <= tolerance_mm
        or abs(y_mm - y_max_mm) <= tolerance_mm
    ]


def _rotate_fixture_point(
    x_mm: float,
    y_mm: float,
    center_x_mm: float,
    center_y_mm: float,
    angle_deg: float,
) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg)
    cos_angle = math.cos(angle_rad)
    sin_angle = math.sin(angle_rad)
    return (
        center_x_mm + x_mm * cos_angle - y_mm * sin_angle,
        center_y_mm + x_mm * sin_angle + y_mm * cos_angle,
    )


def _rotated_rectangle_corners(
    center_x_mm: float,
    center_y_mm: float,
    half_width_mm: float,
    half_height_mm: float,
    angle_deg: float,
) -> list[tuple[float, float]]:
    return [
        _rotate_fixture_point(
            x_offset,
            y_offset,
            center_x_mm,
            center_y_mm,
            angle_deg,
        )
        for x_offset in (-half_width_mm, half_width_mm)
        for y_offset in (-half_height_mm, half_height_mm)
    ]


def _build_follow_flux_gmsh_mesh(
    *,
    steel_return: bool,
    steel_shape: str,
    steel_center_x_mm: float,
    steel_center_y_mm: float,
    magnet_center_x_mm: float,
    magnet_center_y_mm: float,
    mesh_density: str,
    magnet_angle_deg: float = 0.0,
    steel_angle_deg: float = 0.0,
    magnet2_enabled: bool = False,
    magnet2_center_x_mm: float = 44.0,
    magnet2_center_y_mm: float = 0.0,
    magnet2_angle_deg: float = 0.0,
) -> dict[str, Any]:
    """Build the fixed teaching domain with a corner-refined Gmsh mesh."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError("Follow-the-flux meshing requires the Gmsh Python package; no synthetic grid fallback is used.")

    base_lc_mm, far_lc_mm, corner_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    magnet_corners = _rotated_rectangle_corners(
        magnet_center_x_mm,
        magnet_center_y_mm,
        18.0,
        6.0,
        magnet_angle_deg,
    )
    refinement_corners = list(magnet_corners)
    if magnet2_enabled:
        refinement_corners.extend(
            _rotated_rectangle_corners(
                magnet2_center_x_mm,
                magnet2_center_y_mm,
                18.0,
                6.0,
                magnet2_angle_deg,
            )
        )
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_follow_flux_teaching")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )
            magnet_s = gmsh.model.occ.addRectangle(
                magnet_center_x_mm - 18.0,
                magnet_center_y_mm - 6.0,
                0.0,
                18.0,
                12.0,
            )
            magnet_n = gmsh.model.occ.addRectangle(
                magnet_center_x_mm,
                magnet_center_y_mm - 6.0,
                0.0,
                18.0,
                12.0,
            )
            magnet_angle_rad = math.radians(magnet_angle_deg)
            if abs(magnet_angle_rad) > 1.0e-12:
                gmsh.model.occ.rotate(
                    [(2, magnet_s), (2, magnet_n)],
                    magnet_center_x_mm,
                    magnet_center_y_mm,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    magnet_angle_rad,
                )
            tools = [(2, magnet_s), (2, magnet_n)]
            if magnet2_enabled:
                # Same 36 x 12 mm body as the first magnet. Fragmenting it into the
                # domain is what puts mesh edges on its pole faces; without this the
                # solver still tags it by centroid, but the boundary comes out jagged.
                magnet2_s = gmsh.model.occ.addRectangle(
                    magnet2_center_x_mm - 18.0,
                    magnet2_center_y_mm - 6.0,
                    0.0,
                    18.0,
                    12.0,
                )
                magnet2_n = gmsh.model.occ.addRectangle(
                    magnet2_center_x_mm,
                    magnet2_center_y_mm - 6.0,
                    0.0,
                    18.0,
                    12.0,
                )
                magnet2_angle_rad = math.radians(magnet2_angle_deg)
                if abs(magnet2_angle_rad) > 1.0e-12:
                    gmsh.model.occ.rotate(
                        [(2, magnet2_s), (2, magnet2_n)],
                        magnet2_center_x_mm,
                        magnet2_center_y_mm,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        magnet2_angle_rad,
                    )
                tools.extend([(2, magnet2_s), (2, magnet2_n)])
            if steel_return:
                if steel_shape == "circuit":
                    gap_mm = steel_center_x_mm
                    outer_x_mm = 26.0 + gap_mm
                    inner_x_mm = 18.0 + gap_mm
                    steel_entities = [
                        gmsh.model.occ.addRectangle(
                            -outer_x_mm,
                            -6.0,
                            0.0,
                            outer_x_mm - inner_x_mm,
                            26.0,
                        ),
                        gmsh.model.occ.addRectangle(
                            inner_x_mm,
                            -6.0,
                            0.0,
                            outer_x_mm - inner_x_mm,
                            26.0,
                        ),
                        gmsh.model.occ.addRectangle(
                            -outer_x_mm,
                            12.0,
                            0.0,
                            outer_x_mm * 2.0,
                            8.0,
                        ),
                    ]
                    tools.extend((2, entity) for entity in steel_entities)
                    refinement_corners.extend(
                        [
                            (-outer_x_mm, -6.0),
                            (-inner_x_mm, -6.0),
                            (inner_x_mm, -6.0),
                            (outer_x_mm, -6.0),
                            (-outer_x_mm, 12.0),
                            (-inner_x_mm, 12.0),
                            (inner_x_mm, 12.0),
                            (outer_x_mm, 12.0),
                            (-outer_x_mm, 20.0),
                            (outer_x_mm, 20.0),
                        ]
                    )
                elif steel_shape == "puck":
                    steel = gmsh.model.occ.addDisk(
                        steel_center_x_mm,
                        steel_center_y_mm,
                        0.0,
                        8.0,
                        8.0,
                    )
                    tools.append((2, steel))
                else:
                    width_mm, height_mm = (8.0, 28.0) if steel_shape == "bar" else (28.0, 8.0)
                    steel = gmsh.model.occ.addRectangle(
                        steel_center_x_mm - width_mm / 2.0,
                        steel_center_y_mm - height_mm / 2.0,
                        0.0,
                        width_mm,
                        height_mm,
                    )
                    steel_angle_rad = math.radians(steel_angle_deg)
                    if abs(steel_angle_rad) > 1.0e-12:
                        gmsh.model.occ.rotate(
                            [(2, steel)],
                            steel_center_x_mm,
                            steel_center_y_mm,
                            0.0,
                            0.0,
                            0.0,
                            1.0,
                            steel_angle_rad,
                        )
                    refinement_corners.extend(
                        _rotated_rectangle_corners(
                            steel_center_x_mm,
                            steel_center_y_mm,
                            width_mm / 2.0,
                            height_mm / 2.0,
                            steel_angle_deg,
                        )
                    )
                    tools.append((2, steel))

            gmsh.model.occ.fragment([(2, domain)], tools)
            gmsh.model.occ.synchronize()

            corner_points = _point_tags_at(refinement_corners)
            if len(corner_points) < 4:
                raise Magneto2DExecutionError("Gmsh did not preserve the permanent-magnet corner points required for refinement.")
            corner_field = _add_threshold_field(
                points=corner_points,
                size_min_mm=corner_lc_mm,
                size_max_mm=far_lc_mm,
                dist_min_mm=max(0.6, corner_lc_mm * 1.5),
                dist_max_mm=influence_mm,
                sampling=180,
            )
            gmsh.model.mesh.field.setAsBackgroundMesh(corner_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", corner_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Follow-the-flux Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError("Follow-the-flux Gmsh mesh is missing triangles or outer boundary nodes.")
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": f"Gmsh {mesh_density} teaching domain with magnet/steel corner refinement",
        "corner_refinement": True,
    }


def _build_current_wire_gmsh_mesh(
    *,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build a circular conductor in the fixed teaching domain with edge refinement."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError("Current-field meshing requires the Gmsh Python package; no synthetic grid fallback is used.")

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    wire_radius_mm = 5.0
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_current_wire_teaching")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )
            wire = gmsh.model.occ.addDisk(0.0, 0.0, 0.0, wire_radius_mm, wire_radius_mm)
            gmsh.model.occ.fragment([(2, domain)], [(2, wire)])
            gmsh.model.occ.synchronize()

            wire_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                if (
                    x_min >= -wire_radius_mm - 1.0e-5
                    and x_max <= wire_radius_mm + 1.0e-5
                    and y_min >= -wire_radius_mm - 1.0e-5
                    and y_max <= wire_radius_mm + 1.0e-5
                ):
                    wire_curves.append(int(tag))
            if not wire_curves:
                raise Magneto2DExecutionError("Gmsh did not preserve the circular conductor boundary required for refinement.")

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", wire_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 180)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", max(0.4, edge_lc_mm))
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 2.0)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 20)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Current-field Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError("Current-field Gmsh mesh is missing triangles or outer boundary nodes.")
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": f"Gmsh {mesh_density} teaching domain with conductor-boundary refinement",
        "corner_refinement": True,
    }


def _build_current_force_gmsh_mesh(
    *,
    pole_gap_mm: float = 8.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build two permanent-magnet poles and a central current conductor."""

    if not _FORCE_MIN_POLE_GAP_MM <= pole_gap_mm <= _FORCE_MAX_POLE_GAP_MM:
        raise ValueError("pole_gap_mm must be between 0.5 and 16 mm")

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError("Field-force meshing requires the Gmsh Python package; no synthetic grid fallback is used.")

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    wire_radius_mm = 4.0
    magnet_width_mm = _FORCE_MAGNET_WIDTH_MM
    magnet_inner_x_mm = wire_radius_mm + pole_gap_mm
    magnet_outer_x_mm = magnet_inner_x_mm + magnet_width_mm
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_current_force_teaching")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )
            left_magnet = gmsh.model.occ.addRectangle(
                -magnet_outer_x_mm,
                -_FORCE_MAGNET_HALF_HEIGHT_MM,
                0.0,
                magnet_width_mm,
                2.0 * _FORCE_MAGNET_HALF_HEIGHT_MM,
            )
            right_magnet = gmsh.model.occ.addRectangle(
                magnet_inner_x_mm,
                -_FORCE_MAGNET_HALF_HEIGHT_MM,
                0.0,
                magnet_width_mm,
                2.0 * _FORCE_MAGNET_HALF_HEIGHT_MM,
            )
            wire = gmsh.model.occ.addDisk(0.0, 0.0, 0.0, wire_radius_mm, wire_radius_mm)
            gmsh.model.occ.fragment([(2, domain)], [(2, left_magnet), (2, right_magnet), (2, wire)])
            gmsh.model.occ.synchronize()

            material_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                is_outer = (
                    (abs(x_min - _DOMAIN_X_MIN_MM) < 1.0e-5 and abs(x_max - _DOMAIN_X_MIN_MM) < 1.0e-5)
                    or (abs(x_min - _DOMAIN_X_MAX_MM) < 1.0e-5 and abs(x_max - _DOMAIN_X_MAX_MM) < 1.0e-5)
                    or (abs(y_min - _DOMAIN_Y_MIN_MM) < 1.0e-5 and abs(y_max - _DOMAIN_Y_MIN_MM) < 1.0e-5)
                    or (abs(y_min - _DOMAIN_Y_MAX_MM) < 1.0e-5 and abs(y_max - _DOMAIN_Y_MAX_MM) < 1.0e-5)
                )
                if not is_outer:
                    material_curves.append(int(tag))
            if len(material_curves) < 9:
                raise Magneto2DExecutionError("Gmsh did not preserve the magnet and conductor boundaries required for refinement.")

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", material_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 240)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            base_force_edge_lc_mm = max(0.3, edge_lc_mm * 1.35)
            # Keep several elements across the narrowest teaching gap so the
            # 0.5 mm view remains a resolved field solve, not just valid input.
            force_edge_lc_mm = min(
                base_force_edge_lc_mm,
                max(0.12, pole_gap_mm / 3.0),
            )
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", force_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", force_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.6)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", force_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Field-force Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError("Field-force Gmsh mesh is missing triangles or outer boundary nodes.")
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (f"Gmsh {mesh_density} teaching force fixture with magnet and conductor-boundary refinement"),
        "corner_refinement": True,
    }


def _build_linear_motor_capstone_gmsh_mesh(
    *,
    airgap_mm: float = 8.0,
    winding_spacing_mm: float = 18.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Mesh the capstone's magnet array, steel return, and four coil sides."""

    if not 2.0 <= airgap_mm <= 10.0:
        raise ValueError("airgap_mm must be between 2 and 10 mm")
    if not 12.0 <= winding_spacing_mm <= 22.0:
        raise ValueError("winding_spacing_mm must be between 12 and 22 mm")
    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError(
            "Linear-capstone meshing requires the Gmsh Python package; no synthetic grid fallback is used."
        )

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    wire_center_y_mm = (
        _LINEAR_CAPSTONE_MAGNET_TOP_MM
        + airgap_mm
        + _LINEAR_CAPSTONE_WIRE_RADIUS_MM
    )
    winding_centers_mm = tuple(
        factor * winding_spacing_mm for factor in (-1.5, -0.5, 0.5, 1.5)
    )
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_linear_motor_capstone")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )
            material_surfaces: list[tuple[int, int]] = []
            back_iron = gmsh.model.occ.addRectangle(
                -_LINEAR_CAPSTONE_BACK_IRON_HALF_WIDTH_MM,
                _LINEAR_CAPSTONE_BACK_IRON_BOTTOM_MM,
                0.0,
                2.0 * _LINEAR_CAPSTONE_BACK_IRON_HALF_WIDTH_MM,
                _LINEAR_CAPSTONE_BACK_IRON_TOP_MM
                - _LINEAR_CAPSTONE_BACK_IRON_BOTTOM_MM,
            )
            material_surfaces.append((2, back_iron))
            for center_x_mm in _LINEAR_CAPSTONE_MAGNET_CENTERS_MM:
                magnet = gmsh.model.occ.addRectangle(
                    center_x_mm - _LINEAR_CAPSTONE_MAGNET_HALF_WIDTH_MM,
                    _LINEAR_CAPSTONE_MAGNET_BOTTOM_MM,
                    0.0,
                    2.0 * _LINEAR_CAPSTONE_MAGNET_HALF_WIDTH_MM,
                    _LINEAR_CAPSTONE_MAGNET_TOP_MM
                    - _LINEAR_CAPSTONE_MAGNET_BOTTOM_MM,
                )
                material_surfaces.append((2, magnet))
            for center_x_mm in winding_centers_mm:
                wire = gmsh.model.occ.addDisk(
                    center_x_mm,
                    wire_center_y_mm,
                    0.0,
                    _LINEAR_CAPSTONE_WIRE_RADIUS_MM,
                    _LINEAR_CAPSTONE_WIRE_RADIUS_MM,
                )
                material_surfaces.append((2, wire))
            gmsh.model.occ.fragment([(2, domain)], material_surfaces)
            gmsh.model.occ.synchronize()

            material_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                is_outer = (
                    (abs(x_min - _DOMAIN_X_MIN_MM) < 1.0e-5 and abs(x_max - _DOMAIN_X_MIN_MM) < 1.0e-5)
                    or (abs(x_min - _DOMAIN_X_MAX_MM) < 1.0e-5 and abs(x_max - _DOMAIN_X_MAX_MM) < 1.0e-5)
                    or (abs(y_min - _DOMAIN_Y_MIN_MM) < 1.0e-5 and abs(y_max - _DOMAIN_Y_MIN_MM) < 1.0e-5)
                    or (abs(y_min - _DOMAIN_Y_MAX_MM) < 1.0e-5 and abs(y_max - _DOMAIN_Y_MAX_MM) < 1.0e-5)
                )
                if not is_outer:
                    material_curves.append(int(tag))
            if len(material_curves) < 20:
                raise Magneto2DExecutionError(
                    "Gmsh did not preserve the capstone magnet, back-iron, and conductor boundaries."
                )

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", material_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 320)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            capstone_edge_lc_mm = min(max(0.16, airgap_mm / 5.0), max(0.28, edge_lc_mm * 1.4))
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", capstone_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", capstone_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.8)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", capstone_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Linear-capstone Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError(
            "Linear-capstone Gmsh mesh is missing triangles or outer boundary nodes."
        )
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (
            f"Gmsh {mesh_density} four-pole linear-capstone fixture with winding and airgap refinement"
        ),
        "corner_refinement": True,
    }


def _build_rotor_chase_gmsh_mesh(
    *,
    rotor_angle_deg: float,
    pole_gap_mm: float = 8.0,
    source_kind: Literal["pm", "electromagnet"] = "pm",
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build two fixed field sources and a split, rotatable PM rotor."""

    if not 2.0 <= pole_gap_mm <= 16.0:
        raise ValueError("pole_gap_mm must be between 2 and 16 mm")
    if source_kind not in {"pm", "electromagnet"}:
        raise ValueError("source_kind must be pm or electromagnet")
    if not math.isfinite(rotor_angle_deg):
        raise ValueError("rotor_angle_deg must be finite")
    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError("Rotor-chase meshing requires the Gmsh Python package; no synthetic grid fallback is used.")

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    rotor_half_length_mm = _ROTOR_CHASE_ROTOR_LENGTH_MM / 2.0
    rotor_half_height_mm = _ROTOR_CHASE_ROTOR_THICKNESS_MM / 2.0
    stator_inner_x_mm = rotor_half_length_mm + pole_gap_mm
    stator_outer_x_mm = stator_inner_x_mm + _FORCE_MAGNET_WIDTH_MM

    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_rotor_chase_teaching")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )
            left_stator = gmsh.model.occ.addRectangle(
                -stator_outer_x_mm,
                -_FORCE_MAGNET_HALF_HEIGHT_MM,
                0.0,
                _FORCE_MAGNET_WIDTH_MM,
                2.0 * _FORCE_MAGNET_HALF_HEIGHT_MM,
            )
            right_stator = gmsh.model.occ.addRectangle(
                stator_inner_x_mm,
                -_FORCE_MAGNET_HALF_HEIGHT_MM,
                0.0,
                _FORCE_MAGNET_WIDTH_MM,
                2.0 * _FORCE_MAGNET_HALF_HEIGHT_MM,
            )
            rotor_s = gmsh.model.occ.addRectangle(
                -rotor_half_length_mm,
                -rotor_half_height_mm,
                0.0,
                rotor_half_length_mm,
                2.0 * rotor_half_height_mm,
            )
            rotor_n = gmsh.model.occ.addRectangle(
                0.0,
                -rotor_half_height_mm,
                0.0,
                rotor_half_length_mm,
                2.0 * rotor_half_height_mm,
            )
            angle_rad = math.radians(rotor_angle_deg)
            gmsh.model.occ.rotate([(2, rotor_s), (2, rotor_n)], 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, angle_rad)
            source_objects = [(2, left_stator), (2, right_stator), (2, rotor_s), (2, rotor_n)]
            if source_kind == "electromagnet":
                coil_x_mm = (stator_inner_x_mm + stator_outer_x_mm) / 2.0
                for x_mm in (-coil_x_mm, coil_x_mm):
                    for y_mm in (-_ROTOR_CHASE_COIL_Y_MM, _ROTOR_CHASE_COIL_Y_MM):
                        coil = gmsh.model.occ.addDisk(
                            x_mm,
                            y_mm,
                            0.0,
                            _ROTOR_CHASE_COIL_RADIUS_MM,
                            _ROTOR_CHASE_COIL_RADIUS_MM,
                        )
                        source_objects.append((2, coil))
            gmsh.model.occ.fragment(
                [(2, domain)],
                source_objects,
            )
            gmsh.model.occ.synchronize()

            material_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                is_outer = (
                    (abs(x_min - _DOMAIN_X_MIN_MM) < 1.0e-5 and abs(x_max - _DOMAIN_X_MIN_MM) < 1.0e-5)
                    or (abs(x_min - _DOMAIN_X_MAX_MM) < 1.0e-5 and abs(x_max - _DOMAIN_X_MAX_MM) < 1.0e-5)
                    or (abs(y_min - _DOMAIN_Y_MIN_MM) < 1.0e-5 and abs(y_max - _DOMAIN_Y_MIN_MM) < 1.0e-5)
                    or (abs(y_min - _DOMAIN_Y_MAX_MM) < 1.0e-5 and abs(y_max - _DOMAIN_Y_MAX_MM) < 1.0e-5)
                )
                if not is_outer:
                    material_curves.append(int(tag))
            if len(material_curves) < 12:
                raise Magneto2DExecutionError("Gmsh did not preserve the stator and rotor magnet boundaries required for refinement.")

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", material_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 280)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            chase_edge_lc_mm = max(0.26, edge_lc_mm * 1.2)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", chase_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", chase_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.8)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", chase_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Rotor-chase Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError("Rotor-chase Gmsh mesh is missing triangles or outer boundary nodes.")
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (
            f"Gmsh {mesh_density} rotor-chase fixture with "
            f"{'wound iron stator poles' if source_kind == 'electromagnet' else 'PM stator sources'} "
            "and rotating-rotor PM boundary refinement"
        ),
        "corner_refinement": True,
    }


def _build_rotating_field_gmsh_mesh(
    *,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build four conductor cross-sections for the two-phase rotating-field lab."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError("Rotating-field meshing requires the Gmsh Python package; no synthetic grid fallback is used.")

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    coil_centers = (
        (0.0, _ROTATING_FIELD_COIL_OFFSET_MM),
        (0.0, -_ROTATING_FIELD_COIL_OFFSET_MM),
        (-_ROTATING_FIELD_COIL_OFFSET_MM, 0.0),
        (_ROTATING_FIELD_COIL_OFFSET_MM, 0.0),
    )
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_rotating_field_teaching")

            domain = gmsh.model.occ.addRectangle(
                -_ROTATING_FIELD_DOMAIN_HALF_MM,
                -_ROTATING_FIELD_DOMAIN_HALF_MM,
                0.0,
                2.0 * _ROTATING_FIELD_DOMAIN_HALF_MM,
                2.0 * _ROTATING_FIELD_DOMAIN_HALF_MM,
            )
            coils = [
                (
                    2,
                    gmsh.model.occ.addDisk(
                        center_x_mm,
                        center_y_mm,
                        0.0,
                        _ROTATING_FIELD_COIL_RADIUS_MM,
                        _ROTATING_FIELD_COIL_RADIUS_MM,
                    ),
                )
                for center_x_mm, center_y_mm in coil_centers
            ]
            gmsh.model.occ.fragment([(2, domain)], coils)
            gmsh.model.occ.synchronize()

            coil_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                if any(
                    x_min >= center_x_mm - _ROTATING_FIELD_COIL_RADIUS_MM - 1.0e-5
                    and x_max <= center_x_mm + _ROTATING_FIELD_COIL_RADIUS_MM + 1.0e-5
                    and y_min >= center_y_mm - _ROTATING_FIELD_COIL_RADIUS_MM - 1.0e-5
                    and y_max <= center_y_mm + _ROTATING_FIELD_COIL_RADIUS_MM + 1.0e-5
                    for center_x_mm, center_y_mm in coil_centers
                ):
                    coil_curves.append(int(tag))
            if len(coil_curves) < 4:
                raise Magneto2DExecutionError("Gmsh did not preserve all four conductor boundaries required for refinement.")

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", coil_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 240)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            coil_edge_lc_mm = max(0.32, edge_lc_mm * 1.35)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", coil_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", coil_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.7)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", coil_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Rotating-field Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(
        nodes_mm,
        x_min_mm=-_ROTATING_FIELD_DOMAIN_HALF_MM,
        x_max_mm=_ROTATING_FIELD_DOMAIN_HALF_MM,
        y_min_mm=-_ROTATING_FIELD_DOMAIN_HALF_MM,
        y_max_mm=_ROTATING_FIELD_DOMAIN_HALF_MM,
    )
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError("Rotating-field Gmsh mesh is missing triangles or outer boundary nodes.")
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": f"Gmsh {mesh_density} two-phase fixture with four conductor boundaries refined",
        "corner_refinement": True,
    }


def _build_rotating_field_motor_gmsh_mesh(
    *,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build the four wound poles and circular PM rotor used by Lesson 7."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError(
            "Rotating-field motor meshing requires the Gmsh Python package; "
            "no synthetic grid fallback is used."
        )

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    coil_centers = (
        (-_ROTATING_FIELD_MOTOR_COIL_CENTER_MM, _ROTATING_FIELD_MOTOR_COIL_SIDE_MM),
        (-_ROTATING_FIELD_MOTOR_COIL_CENTER_MM, -_ROTATING_FIELD_MOTOR_COIL_SIDE_MM),
        (_ROTATING_FIELD_MOTOR_COIL_CENTER_MM, _ROTATING_FIELD_MOTOR_COIL_SIDE_MM),
        (_ROTATING_FIELD_MOTOR_COIL_CENTER_MM, -_ROTATING_FIELD_MOTOR_COIL_SIDE_MM),
        (-_ROTATING_FIELD_MOTOR_COIL_SIDE_MM, _ROTATING_FIELD_MOTOR_COIL_CENTER_MM),
        (_ROTATING_FIELD_MOTOR_COIL_SIDE_MM, _ROTATING_FIELD_MOTOR_COIL_CENTER_MM),
        (-_ROTATING_FIELD_MOTOR_COIL_SIDE_MM, -_ROTATING_FIELD_MOTOR_COIL_CENTER_MM),
        (_ROTATING_FIELD_MOTOR_COIL_SIDE_MM, -_ROTATING_FIELD_MOTOR_COIL_CENTER_MM),
    )
    core_rectangles = (
        (
            -_ROTATING_FIELD_MOTOR_CORE_OUTER_MM,
            -_ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            _ROTATING_FIELD_MOTOR_CORE_OUTER_MM - _ROTATING_FIELD_MOTOR_CORE_INNER_MM,
            2.0 * _ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
        ),
        (
            _ROTATING_FIELD_MOTOR_CORE_INNER_MM,
            -_ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            _ROTATING_FIELD_MOTOR_CORE_OUTER_MM - _ROTATING_FIELD_MOTOR_CORE_INNER_MM,
            2.0 * _ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
        ),
        (
            -_ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            _ROTATING_FIELD_MOTOR_CORE_INNER_MM,
            2.0 * _ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            _ROTATING_FIELD_MOTOR_CORE_OUTER_MM - _ROTATING_FIELD_MOTOR_CORE_INNER_MM,
        ),
        (
            -_ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            -_ROTATING_FIELD_MOTOR_CORE_OUTER_MM,
            2.0 * _ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM,
            _ROTATING_FIELD_MOTOR_CORE_OUTER_MM - _ROTATING_FIELD_MOTOR_CORE_INNER_MM,
        ),
    )

    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_rotating_field_motor_teaching")

            domain = gmsh.model.occ.addRectangle(
                -_ROTATING_FIELD_DOMAIN_HALF_MM,
                -_ROTATING_FIELD_DOMAIN_HALF_MM,
                0.0,
                2.0 * _ROTATING_FIELD_DOMAIN_HALF_MM,
                2.0 * _ROTATING_FIELD_DOMAIN_HALF_MM,
            )
            rotor = gmsh.model.occ.addDisk(
                0.0,
                0.0,
                0.0,
                _ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM,
                _ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM,
            )
            cores = [
                gmsh.model.occ.addRectangle(x_mm, y_mm, 0.0, width_mm, height_mm)
                for x_mm, y_mm, width_mm, height_mm in core_rectangles
            ]
            coils = [
                gmsh.model.occ.addDisk(
                    center_x_mm,
                    center_y_mm,
                    0.0,
                    _ROTATING_FIELD_MOTOR_COIL_RADIUS_MM,
                    _ROTATING_FIELD_MOTOR_COIL_RADIUS_MM,
                )
                for center_x_mm, center_y_mm in coil_centers
            ]
            gmsh.model.occ.fragment(
                [(2, domain)],
                [(2, rotor), *((2, tag) for tag in cores), *((2, tag) for tag in coils)],
            )
            gmsh.model.occ.synchronize()

            material_curves: list[int] = []
            domain_edge = _ROTATING_FIELD_DOMAIN_HALF_MM - 1.0e-5
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                on_outer_boundary = (
                    abs(x_min) >= domain_edge
                    and abs(x_max) >= domain_edge
                    or abs(y_min) >= domain_edge
                    and abs(y_max) >= domain_edge
                )
                if not on_outer_boundary:
                    material_curves.append(int(tag))
            if len(material_curves) < 17:
                raise Magneto2DExecutionError(
                    "Gmsh did not preserve the rotor, pole, and winding boundaries "
                    "required for the four-pole motor fixture."
                )

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", material_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 280)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            motor_edge_lc_mm = max(0.28, edge_lc_mm * 1.2)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", motor_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", motor_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.8)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", motor_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 28)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(
                f"Rotating-field motor Gmsh generation failed: {exc}"
            ) from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(
        nodes_mm,
        x_min_mm=-_ROTATING_FIELD_DOMAIN_HALF_MM,
        x_max_mm=_ROTATING_FIELD_DOMAIN_HALF_MM,
        y_min_mm=-_ROTATING_FIELD_DOMAIN_HALF_MM,
        y_max_mm=_ROTATING_FIELD_DOMAIN_HALF_MM,
    )
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError(
            "Rotating-field motor Gmsh mesh is missing triangles or outer boundary nodes."
        )
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (
            f"Gmsh {mesh_density} Lesson 7 motor fixture with four wound M350-50A poles, "
            "eight copper winding sides, and a circular PM rotor"
        ),
        "corner_refinement": True,
    }


def _build_three_phase_motor_gmsh_mesh(
    *,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build six wound M350-50A teaching teeth around a circular PM rotor."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError(
            "Three-phase motor meshing requires the Gmsh Python package; "
            "no synthetic grid fallback is used."
        )

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    phase_axes_deg = (0.0, 120.0, 240.0)
    coil_centers: list[tuple[float, float]] = []
    for axis_deg in phase_axes_deg:
        axis_rad = math.radians(axis_deg)
        axis_x, axis_y = math.cos(axis_rad), math.sin(axis_rad)
        normal_x, normal_y = -axis_y, axis_x
        for pole_sign in (-1.0, 1.0):
            for side_sign in (-1.0, 1.0):
                coil_centers.append(
                    (
                        pole_sign * _THREE_PHASE_MOTOR_COIL_CENTER_MM * axis_x
                        + side_sign * _THREE_PHASE_MOTOR_COIL_SIDE_MM * normal_x,
                        pole_sign * _THREE_PHASE_MOTOR_COIL_CENTER_MM * axis_y
                        + side_sign * _THREE_PHASE_MOTOR_COIL_SIDE_MM * normal_y,
                    )
                )

    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_three_phase_motor_teaching")

            domain = gmsh.model.occ.addRectangle(
                -_ROTATING_FIELD_DOMAIN_HALF_MM,
                -_ROTATING_FIELD_DOMAIN_HALF_MM,
                0.0,
                2.0 * _ROTATING_FIELD_DOMAIN_HALF_MM,
                2.0 * _ROTATING_FIELD_DOMAIN_HALF_MM,
            )
            rotor = gmsh.model.occ.addDisk(
                0.0,
                0.0,
                0.0,
                _ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM,
                _ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM,
            )
            cores: list[int] = []
            for pole_angle_deg in (0.0, 60.0, 120.0, 180.0, 240.0, 300.0):
                core = gmsh.model.occ.addRectangle(
                    _THREE_PHASE_MOTOR_CORE_INNER_MM,
                    -_THREE_PHASE_MOTOR_CORE_HALF_WIDTH_MM,
                    0.0,
                    _THREE_PHASE_MOTOR_CORE_OUTER_MM - _THREE_PHASE_MOTOR_CORE_INNER_MM,
                    2.0 * _THREE_PHASE_MOTOR_CORE_HALF_WIDTH_MM,
                )
                gmsh.model.occ.rotate(
                    [(2, core)],
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    math.radians(pole_angle_deg),
                )
                cores.append(core)
            coils = [
                gmsh.model.occ.addDisk(
                    center_x_mm,
                    center_y_mm,
                    0.0,
                    _THREE_PHASE_MOTOR_COIL_RADIUS_MM,
                    _THREE_PHASE_MOTOR_COIL_RADIUS_MM,
                )
                for center_x_mm, center_y_mm in coil_centers
            ]
            gmsh.model.occ.fragment(
                [(2, domain)],
                [(2, rotor), *((2, tag) for tag in cores), *((2, tag) for tag in coils)],
            )
            gmsh.model.occ.synchronize()

            material_curves: list[int] = []
            domain_edge = _ROTATING_FIELD_DOMAIN_HALF_MM - 1.0e-5
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                on_outer_boundary = (
                    abs(x_min) >= domain_edge
                    and abs(x_max) >= domain_edge
                    or abs(y_min) >= domain_edge
                    and abs(y_max) >= domain_edge
                )
                if not on_outer_boundary:
                    material_curves.append(int(tag))
            if len(material_curves) < 25:
                raise Magneto2DExecutionError(
                    "Gmsh did not preserve the six teeth, PM rotor, and twelve "
                    "winding-side boundaries required for Lesson 8."
                )

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", material_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 320)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            motor_edge_lc_mm = max(0.3, edge_lc_mm * 1.25)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", motor_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", motor_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.8)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", motor_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 28)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(
                f"Three-phase motor Gmsh generation failed: {exc}"
            ) from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(
        nodes_mm,
        x_min_mm=-_ROTATING_FIELD_DOMAIN_HALF_MM,
        x_max_mm=_ROTATING_FIELD_DOMAIN_HALF_MM,
        y_min_mm=-_ROTATING_FIELD_DOMAIN_HALF_MM,
        y_max_mm=_ROTATING_FIELD_DOMAIN_HALF_MM,
    )
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError(
            "Three-phase motor Gmsh mesh is missing triangles or outer boundary nodes."
        )
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (
            f"Gmsh {mesh_density} Lesson 8 fixture with six wound M350-50A teeth, "
            "twelve copper winding sides, and a circular N42 PM rotor"
        ),
        "corner_refinement": True,
    }


def _build_iron_saturation_gmsh_mesh(
    *,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Build a conductor and M350-50A annulus with refinement on every material boundary."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError("Iron-saturation meshing requires the Gmsh Python package; no synthetic grid fallback is used.")

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    wire_radius_mm = 5.0
    ring_inner_radius_mm = 11.0
    ring_outer_radius_mm = 23.0
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 10)
            gmsh.model.add("openem_iron_saturation_teaching")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )
            wire = gmsh.model.occ.addDisk(0.0, 0.0, 0.0, wire_radius_mm, wire_radius_mm)
            ring_outer = gmsh.model.occ.addDisk(0.0, 0.0, 0.0, ring_outer_radius_mm, ring_outer_radius_mm)
            ring_inner = gmsh.model.occ.addDisk(0.0, 0.0, 0.0, ring_inner_radius_mm, ring_inner_radius_mm)
            ring_entities, _ = gmsh.model.occ.cut([(2, ring_outer)], [(2, ring_inner)], removeObject=True, removeTool=True)
            gmsh.model.occ.fragment([(2, domain)], [(2, wire), *ring_entities])
            gmsh.model.occ.synchronize()

            circular_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                extent = max(abs(x_min), abs(x_max), abs(y_min), abs(y_max))
                if extent <= ring_outer_radius_mm + 1.0e-4:
                    circular_curves.append(int(tag))
            if len(circular_curves) < 3:
                raise Magneto2DExecutionError("Gmsh did not preserve the wire and iron-ring boundaries required for refinement.")

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", circular_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 240)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            ring_edge_lc_mm = max(0.36, edge_lc_mm * 1.5)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", ring_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", ring_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.5)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", ring_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(f"Iron-saturation Gmsh generation failed: {exc}") from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError("Iron-saturation Gmsh mesh is missing triangles or outer boundary nodes.")
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (f"Gmsh {mesh_density} teaching domain with conductor and M350-50A ring refinement"),
        "corner_refinement": True,
    }


def _build_iron_saturation_tooth_gmsh_mesh(
    *,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    surface_magnet: bool = False,
) -> dict[str, Any]:
    """Build a concentrated winding, nonlinear tooth, airgap, and rotor pole."""

    if not GMSH_AVAILABLE:
        raise Magneto2DExecutionError(
            "Iron-tooth meshing requires the Gmsh Python package; no synthetic grid fallback is used."
        )

    _, far_lc_mm, edge_lc_mm, influence_mm = _teaching_mesh_sizes(mesh_density)
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 12)
            gmsh.model.add("openem_iron_saturation_tooth_teaching")

            domain = gmsh.model.occ.addRectangle(
                _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MIN_MM,
                0.0,
                _DOMAIN_X_MAX_MM - _DOMAIN_X_MIN_MM,
                _DOMAIN_Y_MAX_MM - _DOMAIN_Y_MIN_MM,
            )

            def add_curved_band(
                *,
                half_width_mm: float,
                lower_y_mm: float,
                upper_y_mm: float,
                sag_mm: float,
            ) -> int:
                """Add a shallow annular-looking band without requiring a full motor sector."""

                sample_count = 17
                x_values = [
                    -half_width_mm + 2.0 * half_width_mm * index / (sample_count - 1)
                    for index in range(sample_count)
                ]

                def curved_y(base_y_mm: float, x_mm: float) -> float:
                    normalized_x = x_mm / half_width_mm
                    return base_y_mm - sag_mm * normalized_x * normalized_x

                outline = [
                    (x_mm, curved_y(lower_y_mm, x_mm))
                    for x_mm in x_values
                ]
                outline.extend(
                    (x_mm, curved_y(upper_y_mm, x_mm))
                    for x_mm in reversed(x_values)
                )
                point_tags = [
                    gmsh.model.occ.addPoint(x_mm, y_mm, 0.0)
                    for x_mm, y_mm in outline
                ]
                line_tags = [
                    gmsh.model.occ.addLine(
                        point_tags[index],
                        point_tags[(index + 1) % len(point_tags)],
                    )
                    for index in range(len(point_tags))
                ]
                loop = gmsh.model.occ.addCurveLoop(line_tags)
                return int(gmsh.model.occ.addPlaneSurface([loop]))

            rotor_regions = (
                [
                    # The N42 pole follows the same shallow rotor curvature as
                    # its M350-50A back iron. Its north face points across the 2 mm
                    # centerline airgap toward the wound stator tooth.
                    add_curved_band(
                        half_width_mm=9.0,
                        lower_y_mm=-15.0,
                        upper_y_mm=-10.0,
                        sag_mm=1.6 * (9.0 / 34.0) ** 2,
                    ),
                    add_curved_band(
                        half_width_mm=34.0,
                        lower_y_mm=-23.0,
                        upper_y_mm=-15.0,
                        sag_mm=1.6,
                    ),
                ]
                if surface_magnet
                else [
                    # Curved rotor bridge leaves a 2 mm centerline airgap.
                    add_curved_band(
                        half_width_mm=34.0,
                        lower_y_mm=-20.0,
                        upper_y_mm=-10.0,
                        sag_mm=1.6,
                    ),
                ]
            )
            material_regions = [
                # A shallow motor-radius curvature keeps the fixture recognizable
                # as a stator segment while preserving the compact teaching domain.
                add_curved_band(
                    half_width_mm=32.0,
                    lower_y_mm=16.0,
                    upper_y_mm=26.0,
                    sag_mm=1.8,
                ),
                # Energized center tooth.
                gmsh.model.occ.addRectangle(-6.0, -8.0, 0.0, 12.0, 24.0),
                # Adjacent teeth provide the two symmetric return paths.
                gmsh.model.occ.addRectangle(-32.0, -8.0, 0.0, 8.0, 24.0),
                gmsh.model.occ.addRectangle(24.0, -8.0, 0.0, 8.0, 24.0),
                *rotor_regions,
                # Opposite current directions are the two sides of one tooth coil.
                gmsh.model.occ.addRectangle(-20.0, -2.0, 0.0, 11.0, 15.0),
                gmsh.model.occ.addRectangle(9.0, -2.0, 0.0, 11.0, 15.0),
            ]
            gmsh.model.occ.fragment(
                [(2, domain)],
                [(2, tag) for tag in material_regions],
            )
            gmsh.model.occ.synchronize()

            interior_curves: list[int] = []
            for _dim, tag in gmsh.model.getEntities(1):
                x_min, y_min, _z_min, x_max, y_max, _z_max = gmsh.model.getBoundingBox(1, tag)
                on_outer_boundary = (
                    abs(x_min - _DOMAIN_X_MIN_MM) <= 1.0e-4
                    and abs(x_max - _DOMAIN_X_MIN_MM) <= 1.0e-4
                    or abs(x_min - _DOMAIN_X_MAX_MM) <= 1.0e-4
                    and abs(x_max - _DOMAIN_X_MAX_MM) <= 1.0e-4
                    or abs(y_min - _DOMAIN_Y_MIN_MM) <= 1.0e-4
                    and abs(y_max - _DOMAIN_Y_MIN_MM) <= 1.0e-4
                    or abs(y_min - _DOMAIN_Y_MAX_MM) <= 1.0e-4
                    and abs(y_max - _DOMAIN_Y_MAX_MM) <= 1.0e-4
                )
                if not on_outer_boundary:
                    interior_curves.append(int(tag))
            if len(interior_curves) < 18:
                raise Magneto2DExecutionError(
                    "Gmsh did not preserve the tooth, slot, airgap, and rotor boundaries required for Lesson 4."
                )

            distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", interior_curves)
            gmsh.model.mesh.field.setNumber(distance_field, "Sampling", 300)
            threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold_field, "IField", distance_field)
            tooth_edge_lc_mm = max(0.28, edge_lc_mm * 1.15)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", tooth_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", far_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", tooth_edge_lc_mm)
            gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", influence_mm * 1.5)
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)
            gmsh.option.setNumber("Mesh.MeshSizeMin", tooth_edge_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeMax", far_lc_mm)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.model.mesh.generate(2)
            nodes_mm, triangles = _extract_gmsh_triangles()
        except Magneto2DExecutionError:
            raise
        except Exception as exc:
            raise Magneto2DExecutionError(
                f"Iron-tooth Gmsh generation failed: {exc}"
            ) from exc
        finally:
            gmsh.finalize()

    boundary_nodes = _outer_boundary_nodes(nodes_mm)
    if not triangles or not boundary_nodes:
        raise Magneto2DExecutionError(
            "Iron-tooth Gmsh mesh is missing triangles or outer boundary nodes."
        )
    return {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "boundary_nodes": boundary_nodes,
        "source_detail": (
            f"Gmsh {mesh_density} Lesson 4 concentrated tooth winding with "
            f"curved M350-50A yoke and {'N42 SPM pole on rotor back iron' if surface_magnet else 'rotor segment'}, "
            "three tooth faces, and a 2 mm centerline airgap"
        ),
        "corner_refinement": True,
    }


def _contour_payload(contour: object) -> dict[str, Any]:
    if hasattr(contour, "model_dump"):
        return contour.model_dump()  # type: ignore[no-any-return, union-attr]
    if hasattr(contour, "dict"):
        return contour.dict()  # type: ignore[no-any-return, union-attr]
    if isinstance(contour, dict):
        return contour
    raise TypeError(f"Unsupported contour payload: {type(contour)!r}")


def _fixture_local_point(
    x_mm: float,
    y_mm: float,
    center_x_mm: float,
    center_y_mm: float,
    angle_deg: float,
) -> tuple[float, float]:
    """Transform a solved mesh point into the permanent magnet's frame."""

    angle_rad = math.radians(angle_deg)
    dx_mm = x_mm - center_x_mm
    dy_mm = y_mm - center_y_mm
    return (
        math.cos(angle_rad) * dx_mm + math.sin(angle_rad) * dy_mm,
        -math.sin(angle_rad) * dx_mm + math.cos(angle_rad) * dy_mm,
    )


def _integrate_magnet_face_flux_per_depth(
    payload: dict[str, Any],
    *,
    region_label: str,
    local_face_x_mm: float,
    outward_normal_sign: float,
) -> tuple[float, float]:
    """Integrate signed normal B over one magnet face in a 2D solved mesh.

    The returned values are flux per unit out-of-plane depth in Wb/m and the
    integrated face length in m. Element B is piecewise constant for the
    first-order triangles used by this teaching fixture.
    """

    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    regions = payload.get("regions") or []
    element_bx_t = payload.get("element_bx_t") or []
    element_by_t = payload.get("element_by_t") or []
    if not (len(regions) == len(triangles) and len(element_bx_t) == len(triangles) and len(element_by_t) == len(triangles)):
        return 0.0, 0.0

    center_x_mm = float(payload.get("magnet_center_x_mm", 0.0))
    center_y_mm = float(payload.get("magnet_center_y_mm", 0.0))
    angle_deg = float(payload.get("magnet_angle_deg", 0.0))
    angle_rad = math.radians(angle_deg)
    normal_x = outward_normal_sign * math.cos(angle_rad)
    normal_y = outward_normal_sign * math.sin(angle_rad)
    tolerance_mm = 1.0e-5
    flux_per_depth_wb_per_m = 0.0
    face_length_m = 0.0

    for triangle_index, triangle in enumerate(triangles):
        if regions[triangle_index] != region_label:
            continue
        bx_t = float(element_bx_t[triangle_index])
        by_t = float(element_by_t[triangle_index])
        normal_b_t = bx_t * normal_x + by_t * normal_y
        triangle_edges = (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        )
        for first_index, second_index in triangle_edges:
            first = nodes_mm[first_index]
            second = nodes_mm[second_index]
            first_local = _fixture_local_point(
                float(first[0]),
                float(first[1]),
                center_x_mm,
                center_y_mm,
                angle_deg,
            )
            second_local = _fixture_local_point(
                float(second[0]),
                float(second[1]),
                center_x_mm,
                center_y_mm,
                angle_deg,
            )
            if (
                abs(first_local[0] - local_face_x_mm) > tolerance_mm
                or abs(second_local[0] - local_face_x_mm) > tolerance_mm
                or abs(first_local[1]) > _MAGNET_HALF_HEIGHT_MM + tolerance_mm
                or abs(second_local[1]) > _MAGNET_HALF_HEIGHT_MM + tolerance_mm
            ):
                continue
            edge_length_m = (
                math.hypot(
                    float(second[0]) - float(first[0]),
                    float(second[1]) - float(first[1]),
                )
                * 1.0e-3
            )
            flux_per_depth_wb_per_m += normal_b_t * edge_length_m
            face_length_m += edge_length_m

    return flux_per_depth_wb_per_m, face_length_m


def _add_follow_flux_gate_metrics(payload: dict[str, Any]) -> None:
    """Add solver-derived B-versus-total-flux teaching measurements."""

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return

    north_per_depth, north_length_m = _integrate_magnet_face_flux_per_depth(
        payload,
        region_label="magnet_n",
        local_face_x_mm=_MAGNET_HALF_WIDTH_MM,
        outward_normal_sign=1.0,
    )
    south_out_per_depth, south_length_m = _integrate_magnet_face_flux_per_depth(
        payload,
        region_label="magnet_s",
        local_face_x_mm=-_MAGNET_HALF_WIDTH_MM,
        outward_normal_sign=-1.0,
    )
    if north_length_m <= 0.0 or south_length_m <= 0.0:
        return

    teaching_depth_m = _TEACHING_DEPTH_MM * 1.0e-3
    north_flux_wb = north_per_depth * teaching_depth_m
    south_in_flux_wb = -south_out_per_depth * teaching_depth_m
    metrics.update(
        {
            "teaching_depth_mm": _TEACHING_DEPTH_MM,
            "north_face_area_mm2": north_length_m * 1.0e3 * _TEACHING_DEPTH_MM,
            "north_face_mean_bn_t": north_per_depth / north_length_m,
            "north_face_flux_wb": north_flux_wb,
            "south_face_flux_wb": south_in_flux_wb,
        }
    )


def run_follow_flux_fixture(
    *,
    steel_return: bool,
    steel_shape: Literal["bar", "plate", "puck"] = "bar",
    steel_center_x_mm: float = 28.0,
    steel_center_y_mm: float = 0.0,
    magnet_center_x_mm: float = 0.0,
    magnet_center_y_mm: float = 0.0,
    magnet_angle_deg: float = 0.0,
    steel_angle_deg: float = 0.0,
    magnet2_enabled: bool = False,
    magnet2_center_x_mm: float = 44.0,
    magnet2_center_y_mm: float = 0.0,
    magnet2_angle_deg: float = 0.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    solve: bool = True,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Mesh and optionally solve the Lesson 1 permanent-magnet teaching fixture."""

    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request = {
        "fixture": "follow_flux",
        "steel_return": steel_return,
        "steel_shape": steel_shape,
        "steel_center_x_mm": steel_center_x_mm,
        "steel_center_y_mm": steel_center_y_mm,
        "magnet_center_x_mm": magnet_center_x_mm,
        "magnet_center_y_mm": magnet_center_y_mm,
        "magnet_angle_deg": magnet_angle_deg,
        "magnet2_enabled": magnet2_enabled,
        "magnet2_center_x_mm": magnet2_center_x_mm,
        "magnet2_center_y_mm": magnet2_center_y_mm,
        "magnet2_angle_deg": magnet2_angle_deg,
        "steel_angle_deg": steel_angle_deg,
        "mesh_density": mesh_density,
        "solve": solve,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_follow_flux_gmsh_mesh(
            steel_return=steel_return,
            steel_shape=steel_shape,
            steel_center_x_mm=steel_center_x_mm,
            steel_center_y_mm=steel_center_y_mm,
            magnet_center_x_mm=magnet_center_x_mm,
            magnet_center_y_mm=magnet_center_y_mm,
            mesh_density=mesh_density,
            magnet_angle_deg=magnet_angle_deg,
            steel_angle_deg=steel_angle_deg,
            magnet2_enabled=magnet2_enabled,
            magnet2_center_x_mm=magnet2_center_x_mm,
            magnet2_center_y_mm=magnet2_center_y_mm,
            magnet2_angle_deg=magnet2_angle_deg,
        )
    with tempfile.TemporaryDirectory(prefix="openem_follow_flux_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        command = [
            str(executable or "magneto2d"),
            str(input_path),
            "--mode",
            "teaching",
            "-o",
            str(output_path),
        ]
        completed = runner(
            command,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Follow-the-flux fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Follow-the-flux fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Follow-the-flux fixture returned invalid JSON") from exc

    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if solve and az_nodal and nodes_mm and triangles:
        _add_follow_flux_gate_metrics(payload)
        levels = generate_contour_levels(
            az_nodal,
            nodes_mm=nodes_mm,
            triangles=triangles,
        )
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_airgap_tax_fixture(
    *,
    airgap_mm: float = 4.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve the Lesson 2 magnet, two-airgap, and steel return-path fixture."""

    if not 0.5 <= airgap_mm <= 8.0:
        raise ValueError("airgap_mm must be between 0.5 and 8.0 mm")

    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": "magnetic_circuit",
        "steel_return": True,
        "steel_shape": "circuit",
        # The teaching solver uses this otherwise-unused placement field as
        # the circuit's two equal airgap lengths.
        "steel_center_x_mm": airgap_mm,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": 0.0,
        "steel_angle_deg": 0.0,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_follow_flux_gmsh_mesh(
            steel_return=True,
            steel_shape="circuit",
            steel_center_x_mm=airgap_mm,
            steel_center_y_mm=0.0,
            magnet_center_x_mm=0.0,
            magnet_center_y_mm=0.0,
            mesh_density=mesh_density,
        )

    with tempfile.TemporaryDirectory(prefix="openem_airgap_tax_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Airgap-tax fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Airgap-tax fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Airgap-tax fixture returned invalid JSON") from exc

    payload["airgap_mm"] = airgap_mm
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        _add_follow_flux_gate_metrics(payload)
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_current_field_fixture(
    *,
    current_a: float = 8.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve the Lesson 3 straight-conductor magnetic-field fixture."""

    if not -20.0 <= current_a <= 20.0:
        raise ValueError("current_a must be between -20 and 20 A")

    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": "current_wire",
        "steel_return": False,
        "steel_shape": "bar",
        "steel_center_x_mm": 0.0,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": 0.0,
        "steel_angle_deg": 0.0,
        "wire_current_a": current_a,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_current_wire_gmsh_mesh(mesh_density=mesh_density)

    with tempfile.TemporaryDirectory(prefix="openem_current_field_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Current-field fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Current-field fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Current-field fixture returned invalid JSON") from exc

    payload["current_a"] = current_a
    payload["wire_radius_mm"] = 5.0
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_iron_saturation_fixture(
    *,
    current_a: float = 100.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve the Lesson 4 nonlinear M350-50A ring at the requested current."""

    if not 0.0 <= current_a <= 1_200.0:
        raise ValueError("current_a must be between 0 and 1200 A")

    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": "iron_saturation",
        "steel_return": False,
        "steel_shape": "bar",
        "steel_center_x_mm": 0.0,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": 0.0,
        "steel_angle_deg": 0.0,
        "wire_current_a": current_a,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_iron_saturation_gmsh_mesh(mesh_density=mesh_density)

    with tempfile.TemporaryDirectory(prefix="openem_iron_saturation_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Iron-saturation fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Iron-saturation fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Iron-saturation fixture returned invalid JSON") from exc

    payload["current_a"] = current_a
    payload["wire_radius_mm"] = 5.0
    payload["iron_ring_inner_radius_mm"] = 11.0
    payload["iron_ring_outer_radius_mm"] = 23.0
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def _run_iron_saturation_tooth_fixture(
    *,
    current_a: float = 8.0,
    surface_magnet: bool,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve Lesson 4's wound tooth against steel or an N42 SPM pole."""

    if not 0.0 <= current_a <= 20.0:
        raise ValueError("current_a must be between 0 and 20 A")

    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": (
            "iron_saturation_spm_tooth"
            if surface_magnet
            else "iron_saturation_tooth"
        ),
        "steel_return": False,
        "steel_shape": "bar",
        "steel_center_x_mm": 0.0,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": 0.0,
        "steel_angle_deg": 0.0,
        "wire_current_a": current_a,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_iron_saturation_tooth_gmsh_mesh(
            mesh_density=mesh_density,
            surface_magnet=surface_magnet,
        )

    fixture_name = "SPM-tooth" if surface_magnet else "Iron-tooth"
    with tempfile.TemporaryDirectory(
        prefix=(
            "openem_iron_saturation_spm_tooth_"
            if surface_magnet
            else "openem_iron_saturation_tooth_"
        )
    ) as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"{fixture_name} fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError(f"{fixture_name} fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError(
                f"{fixture_name} fixture returned invalid JSON"
            ) from exc

    payload["current_a"] = current_a
    payload["coil_turns"] = 400
    payload["airgap_mm"] = 2.0
    payload["tooth_width_mm"] = 12.0
    payload["surface_magnet"] = surface_magnet
    if surface_magnet:
        payload["magnet_grade"] = "N42"
        payload["magnet_thickness_mm"] = 5.0
        payload["magnet_width_mm"] = 18.0
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_iron_saturation_tooth_fixture(
    *,
    current_a: float = 8.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve Lesson 4's wound tooth against a curved M350-50A rotor return."""

    return _run_iron_saturation_tooth_fixture(
        current_a=current_a,
        surface_magnet=False,
        mesh_density=mesh_density,
        runner=runner,
    )


def run_iron_saturation_spm_tooth_fixture(
    *,
    current_a: float = 0.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve Lesson 4's wound tooth facing an N42 surface magnet."""

    return _run_iron_saturation_tooth_fixture(
        current_a=current_a,
        surface_magnet=True,
        mesh_density=mesh_density,
        runner=runner,
    )


def run_field_force_fixture(
    *,
    current_a: float = 8.0,
    pole_gap_mm: float = 8.0,
    wire_only: bool = False,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve the Lesson 5 combined field or its current-only FEM component."""

    if not -20.0 <= current_a <= 20.0:
        raise ValueError("current_a must be between -20 and 20 A")
    if not _FORCE_MIN_POLE_GAP_MM <= pole_gap_mm <= _FORCE_MAX_POLE_GAP_MM:
        raise ValueError("pole_gap_mm must be between 0.5 and 16 mm")

    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": "current_force_wire" if wire_only else "current_force",
        "steel_return": False,
        "steel_shape": "bar",
        # The force fixtures do not contain steel. This otherwise-unused teaching
        # request coordinate carries the symmetric surface gap into Magneto2D.
        "steel_center_x_mm": pole_gap_mm,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": 0.0,
        "steel_angle_deg": 0.0,
        "wire_current_a": current_a,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_current_force_gmsh_mesh(pole_gap_mm=pole_gap_mm, mesh_density=mesh_density)

    with tempfile.TemporaryDirectory(prefix="openem_field_force_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Field-force fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Field-force fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Field-force fixture returned invalid JSON") from exc

    payload["current_a"] = current_a
    payload["pole_gap_mm"] = pole_gap_mm
    payload["wire_only"] = wire_only
    payload["wire_radius_mm"] = 4.0
    payload["teaching_depth_mm"] = 10.0
    payload["magnet_inner_x_mm"] = 4.0 + pole_gap_mm
    payload["magnet_outer_x_mm"] = 4.0 + pole_gap_mm + _FORCE_MAGNET_WIDTH_MM
    payload["magnet_half_height_mm"] = _FORCE_MAGNET_HALF_HEIGHT_MM
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = (
            _wire_field_absolute_contour_levels(az_nodal, current_a)
            if wire_only
            else generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        )
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    if wire_only:
        payload["contour_reference_current_a"] = _WIRE_FIELD_REFERENCE_CURRENT_A
        payload["contour_interval_is_fixed"] = True
    return payload


def run_linear_motor_capstone_fixture(
    *,
    current_a: float = 0.0,
    airgap_mm: float = 8.0,
    magnet_orientations: tuple[int, int, int, int] = (1, 1, 1, 1),
    winding_spacing_mm: float = 18.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    timeout_s: float = _LINEAR_CAPSTONE_WORKER_TIMEOUT_S,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve the Chapter 1 moving-coil capstone with PM and winding sources."""

    if not -20.0 <= current_a <= 20.0:
        raise ValueError("current_a must be between -20 and 20 A")
    if not 2.0 <= airgap_mm <= 10.0:
        raise ValueError("airgap_mm must be between 2 and 10 mm")
    if not 12.0 <= winding_spacing_mm <= 22.0:
        raise ValueError("winding_spacing_mm must be between 12 and 22 mm")
    if timeout_s <= 0.0:
        raise ValueError("timeout_s must be positive")
    if len(magnet_orientations) != 4 or any(
        orientation not in {-1, 1} for orientation in magnet_orientations
    ):
        raise ValueError("magnet_orientations must contain four values of -1 or 1")

    deadline = time.monotonic() + timeout_s
    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": "linear_motor_capstone",
        "steel_return": False,
        "steel_shape": "bar",
        # The capstone owns its fixed steel return. This otherwise-unused
        # coordinate carries the pole-face-to-conductor clearance to Magneto2D.
        "steel_center_x_mm": airgap_mm,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": 0.0,
        "steel_angle_deg": 0.0,
        "wire_current_a": current_a,
        "capstone_magnet_orientations": list(magnet_orientations),
        "capstone_winding_spacing_mm": winding_spacing_mm,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_linear_motor_capstone_gmsh_mesh(
            airgap_mm=airgap_mm,
            winding_spacing_mm=winding_spacing_mm,
            mesh_density=mesh_density,
        )

    with tempfile.TemporaryDirectory(prefix="openem_linear_capstone_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        command = [
            str(executable or "magneto2d"),
            str(input_path),
            "--mode",
            "teaching",
            "-o",
            str(output_path),
        ]
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0.0:
            raise TimeoutError(f"Linear-capstone fixture timed out after {timeout_s:g}s")
        try:
            completed = runner(
                command,
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
                timeout=remaining_s,
            )
        except subprocess.TimeoutExpired as exc:
            # subprocess.run terminates and waits for the child before raising,
            # so the API cannot return while Magneto2D is still running.
            raise TimeoutError(
                f"Linear-capstone fixture timed out after {timeout_s:g}s"
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Linear-capstone fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Linear-capstone fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Linear-capstone fixture returned invalid JSON") from exc

    payload["current_a"] = current_a
    payload["airgap_mm"] = airgap_mm
    payload["magnet_orientations"] = list(magnet_orientations)
    payload["winding_signs"] = [1, -1, 1, -1]
    payload["winding_spacing_mm"] = winding_spacing_mm
    payload["winding_turns"] = 3
    payload["wire_radius_mm"] = _LINEAR_CAPSTONE_WIRE_RADIUS_MM
    payload["wire_center_y_mm"] = (
        _LINEAR_CAPSTONE_MAGNET_TOP_MM
        + airgap_mm
        + _LINEAR_CAPSTONE_WIRE_RADIUS_MM
    )
    payload["teaching_depth_mm"] = _TEACHING_DEPTH_MM
    metrics = payload.get("metrics") or {}
    force_x_n = metrics.get("wire_force_x_n")
    force_y_n = metrics.get("wire_force_y_n")
    force_magnitude_n = metrics.get("wire_force_magnitude_n")
    payload["net_force_x_n"] = float(force_x_n) if force_x_n is not None else None
    payload["net_force_y_n"] = float(force_y_n) if force_y_n is not None else None
    payload["net_force_magnitude_n"] = (
        float(force_magnitude_n) if force_magnitude_n is not None else None
    )
    payload["force_method"] = "volume_lorentz_j_cross_b"
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(
            az_nodal,
            nodes_mm=nodes_mm,
            triangles=triangles,
        )
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_field_force_motor_fixture(
    *,
    current_a: float = 8.0,
    loop_angle_deg: float = 90.0,
    pole_gap_mm: float = 8.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Run a fresh side-conductor FEM solve and project its force into loop torque.

    Magneto2D resolves the active conductor cross-section at ``theta(I, B) =
    90 deg``. The requested loop-normal angle then sets the projected lever arm
    of the equal and opposite force pair. Keeping those two operations explicit
    avoids presenting a 2D solve as a tilted 3D mesh while still ensuring every
    motor-effect control change is backed by a fresh FEM field/force result.
    """

    if not math.isfinite(loop_angle_deg) or not 0.0 <= loop_angle_deg <= 360.0:
        raise ValueError("loop_angle_deg must be between 0 and 360 degrees")

    payload = run_field_force_fixture(
        current_a=current_a,
        pole_gap_mm=pole_gap_mm,
        mesh_density=mesh_density,
        runner=runner,
    )
    metrics = payload.get("metrics") or {}
    side_force_y_n = metrics.get("wire_force_y_n")
    side_force_bil_n = metrics.get("wire_force_bil_n")
    if side_force_y_n is None or side_force_bil_n is None:
        raise Magneto2DExecutionError(
            "Motor-effect FEM solve returned no conductor-force integral."
        )

    resolved_angle_deg = float(loop_angle_deg)
    side_force_magnitude_n = abs(float(side_force_y_n))
    torque_max_nm = 0.024 * side_force_magnitude_n
    torque_sign = -1.0 if current_a >= 0.0 else 1.0
    torque_nm = (
        torque_sign
        * torque_max_nm
        * math.sin(math.radians(resolved_angle_deg))
    )

    payload["fixture"] = "current_force_motor"
    payload["motor_effect_solve"] = True
    payload["loop_angle_deg"] = resolved_angle_deg
    payload["fem_reference_angle_deg"] = 90.0
    payload["active_side_force_y_n"] = float(side_force_y_n)
    payload["opposite_side_force_y_n"] = -float(side_force_y_n)
    payload["side_force_magnitude_n"] = side_force_magnitude_n
    payload["side_force_bil_n"] = abs(float(side_force_bil_n))
    payload["net_force_y_n"] = 0.0
    payload["loop_active_side_spacing_mm"] = 24.0
    payload["torque_max_nm"] = torque_max_nm
    payload["torque_nm"] = torque_nm
    payload["projection_method"] = "fresh_2d_fem_side_force_plus_3d_lever_arm"
    return payload


def run_rotor_chase_fixture(
    *,
    field_source: Literal["stator", "rotor", "combined"] = "combined",
    rotor_angle_deg: float = 90.0,
    pole_gap_mm: float = 8.0,
    source_kind: Literal["pm", "electromagnet"] = "pm",
    source_current_a: float = 0.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve Lesson 6 with permanent-magnet or wound-pole field sources."""

    if field_source not in {"stator", "rotor", "combined"}:
        raise ValueError("field_source must be stator, rotor, or combined")
    if source_kind not in {"pm", "electromagnet"}:
        raise ValueError("source_kind must be pm or electromagnet")
    if not math.isfinite(source_current_a) or abs(source_current_a) > 20.0:
        raise ValueError("source_current_a must be finite and between -20 and 20 A")
    if not math.isfinite(rotor_angle_deg):
        raise ValueError("rotor_angle_deg must be finite")
    if not 2.0 <= pole_gap_mm <= 16.0:
        raise ValueError("pole_gap_mm must be between 2 and 16 mm")

    normalized_angle_deg = rotor_angle_deg % 360.0
    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": (
            f"rotor_chase_coil_{field_source}"
            if source_kind == "electromagnet"
            else f"rotor_chase_{field_source}"
        ),
        "steel_return": False,
        "steel_shape": "bar",
        # This otherwise-unused coordinate carries the rotor-to-stator gap.
        "steel_center_x_mm": pole_gap_mm,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": normalized_angle_deg,
        "steel_angle_deg": 0.0,
        "wire_current_a": source_current_a if source_kind == "electromagnet" else 0.0,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if runner is subprocess.run:
        request["imported_mesh"] = _build_rotor_chase_gmsh_mesh(
            rotor_angle_deg=normalized_angle_deg,
            pole_gap_mm=pole_gap_mm,
            source_kind=source_kind,
            mesh_density=mesh_density,
        )

    with tempfile.TemporaryDirectory(prefix="openem_rotor_chase_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Rotor-chase fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Rotor-chase fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Rotor-chase fixture returned invalid JSON") from exc

    payload["field_source"] = field_source
    payload["source_kind"] = source_kind
    payload["source_current_a"] = source_current_a if source_kind == "electromagnet" else 0.0
    payload["rotor_angle_deg"] = normalized_angle_deg
    payload["pole_gap_mm"] = pole_gap_mm
    payload["rotor_length_mm"] = _ROTOR_CHASE_ROTOR_LENGTH_MM
    payload["rotor_thickness_mm"] = _ROTOR_CHASE_ROTOR_THICKNESS_MM
    payload["stator_magnet_width_mm"] = _FORCE_MAGNET_WIDTH_MM
    payload["stator_magnet_half_height_mm"] = _FORCE_MAGNET_HALF_HEIGHT_MM
    payload["coil_radius_mm"] = _ROTOR_CHASE_COIL_RADIUS_MM
    payload["coil_y_mm"] = _ROTOR_CHASE_COIL_Y_MM
    payload["coil_turns"] = _ROTOR_CHASE_COIL_TURNS
    payload["magnet_only"] = source_kind == "pm"
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_rotating_field_fixture(
    *,
    electrical_angle_deg: float = 0.0,
    peak_current_a: float = 8.0,
    field_component: Literal["combined", "phase_a", "phase_b"] = "combined",
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    imported_mesh: dict[str, Any] | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Solve one two-phase quadrature-current frame for Lesson 6."""

    if not 0.0 <= peak_current_a <= 20.0:
        raise ValueError("peak_current_a must be between 0 and 20 A")
    if not math.isfinite(electrical_angle_deg):
        raise ValueError("electrical_angle_deg must be finite")
    if field_component not in {"combined", "phase_a", "phase_b"}:
        raise ValueError("field_component must be combined, phase_a, or phase_b")

    normalized_angle_deg = electrical_angle_deg % 360.0
    angle_rad = math.radians(normalized_angle_deg)
    quadrature_phase_a_current_a = peak_current_a * math.cos(angle_rad)
    quadrature_phase_b_current_a = peak_current_a * math.sin(angle_rad)
    phase_a_current_a = 0.0 if field_component == "phase_b" else quadrature_phase_a_current_a
    phase_b_current_a = 0.0 if field_component == "phase_a" else quadrature_phase_b_current_a
    fixture_name = {
        "combined": "rotating_field",
        "phase_a": "rotating_field_phase_a",
        "phase_b": "rotating_field_phase_b",
    }[field_component]
    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    request: dict[str, Any] = {
        "fixture": fixture_name,
        "steel_return": False,
        "steel_shape": "bar",
        "steel_center_x_mm": 0.0,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        # This fixture contains no permanent magnet. Magneto2D uses this existing
        # angle field as the electrical phase angle for the two current pairs.
        "magnet_angle_deg": normalized_angle_deg,
        "steel_angle_deg": 0.0,
        "wire_current_a": peak_current_a,
        "mesh_density": mesh_density,
        "solve": True,
    }
    if imported_mesh is not None:
        request["imported_mesh"] = imported_mesh
    elif runner is subprocess.run:
        request["imported_mesh"] = _build_rotating_field_gmsh_mesh(mesh_density=mesh_density)

    with tempfile.TemporaryDirectory(prefix="openem_rotating_field_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(f"Rotating-field fixture failed: {detail}")
        if not output_path.exists():
            raise Magneto2DExecutionError("Rotating-field fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError("Rotating-field fixture returned invalid JSON") from exc

    payload["electrical_angle_deg"] = normalized_angle_deg
    payload["peak_current_a"] = peak_current_a
    payload["phase_a_current_a"] = phase_a_current_a
    payload["phase_b_current_a"] = phase_b_current_a
    payload["field_component"] = field_component
    payload["fixture"] = "rotating_field"
    payload["coil_radius_mm"] = _ROTATING_FIELD_COIL_RADIUS_MM
    payload["coil_offset_mm"] = _ROTATING_FIELD_COIL_OFFSET_MM
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_rotating_field_sweep(
    *,
    peak_current_a: float = 8.0,
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Solve one electrical revolution while reusing a single Gmsh mesh."""

    if not 0.0 < peak_current_a <= 20.0:
        raise ValueError("peak_current_a must be greater than 0 and at most 20 A")
    imported_mesh = _build_rotating_field_gmsh_mesh(mesh_density=mesh_density)
    frames = [
        run_rotating_field_fixture(
            electrical_angle_deg=float(angle_deg),
            peak_current_a=peak_current_a,
            field_component="combined",
            mesh_density=mesh_density,
            imported_mesh=imported_mesh,
        )
        for angle_deg in _ROTATING_FIELD_ANGLES_DEG
    ]
    phase_a_frames = [
        run_rotating_field_fixture(
            electrical_angle_deg=float(angle_deg),
            peak_current_a=peak_current_a,
            field_component="phase_a",
            mesh_density=mesh_density,
            imported_mesh=imported_mesh,
        )
        for angle_deg in _ROTATING_FIELD_ANGLES_DEG
    ]
    phase_b_frames = [
        run_rotating_field_fixture(
            electrical_angle_deg=float(angle_deg),
            peak_current_a=peak_current_a,
            field_component="phase_b",
            mesh_density=mesh_density,
            imported_mesh=imported_mesh,
        )
        for angle_deg in _ROTATING_FIELD_ANGLES_DEG
    ]
    return {
        "schema_version": "openem.rotating_field_sweep.v2",
        "fixture": "rotating_field",
        "peak_current_a": peak_current_a,
        "frame_count": len(frames),
        "electrical_angles_deg": list(_ROTATING_FIELD_ANGLES_DEG),
        "frames": frames,
        "phase_a_frames": phase_a_frames,
        "phase_b_frames": phase_b_frames,
    }


def run_rotating_field_motor_fixture(
    *,
    electrical_angle_deg: float = 0.0,
    rotor_angle_deg: float = -_ROTATING_FIELD_MOTOR_LAG_DEG,
    peak_current_a: float = 8.0,
    field_component: Literal["combined", "stator", "rotor"] = "combined",
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    imported_mesh: dict[str, Any] | None = None,
    solve: bool = True,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Build or solve one four-pole, two-phase stator frame with its PM rotor."""

    if not 0.0 <= peak_current_a <= 20.0:
        raise ValueError("peak_current_a must be between 0 and 20 A")
    if field_component not in {"combined", "stator", "rotor"}:
        raise ValueError("field_component must be combined, stator, or rotor")
    if not math.isfinite(electrical_angle_deg) or not math.isfinite(rotor_angle_deg):
        raise ValueError("electrical_angle_deg and rotor_angle_deg must be finite")

    normalized_angle_deg = electrical_angle_deg % 360.0
    normalized_rotor_angle_deg = rotor_angle_deg % 360.0
    angle_rad = math.radians(normalized_angle_deg)
    phase_a_current_a = peak_current_a * math.cos(angle_rad)
    phase_b_current_a = peak_current_a * math.sin(angle_rad)
    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    solver_fixture = {
        "combined": "rotating_field_motor",
        "stator": "rotating_field_motor_stator",
        "rotor": "rotating_field_motor_rotor",
    }[field_component]
    request: dict[str, Any] = {
        "fixture": solver_fixture,
        "steel_return": False,
        "steel_shape": "bar",
        "steel_center_x_mm": 0.0,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        # The PM orientation and electrical phase need independent angles.
        "magnet_angle_deg": normalized_rotor_angle_deg,
        "steel_angle_deg": normalized_angle_deg,
        "wire_current_a": peak_current_a,
        "mesh_density": mesh_density,
        "solve": solve,
    }
    if imported_mesh is not None:
        request["imported_mesh"] = imported_mesh
    elif runner is subprocess.run:
        request["imported_mesh"] = _build_rotating_field_motor_gmsh_mesh(
            mesh_density=mesh_density
        )

    with tempfile.TemporaryDirectory(prefix="openem_rotating_field_motor_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(
                f"Rotating-field motor fixture failed: {detail}"
            )
        if not output_path.exists():
            raise Magneto2DExecutionError("Rotating-field motor fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError(
                "Rotating-field motor fixture returned invalid JSON"
            ) from exc

    payload["fixture"] = "rotating_field_motor"
    payload["field_component"] = field_component
    payload["electrical_angle_deg"] = normalized_angle_deg
    payload["field_target_angle_deg"] = normalized_angle_deg
    payload["rotor_angle_deg"] = normalized_rotor_angle_deg
    payload["torque_angle_deg"] = (
        normalized_angle_deg - normalized_rotor_angle_deg + 180.0
    ) % 360.0 - 180.0
    payload["peak_current_a"] = peak_current_a
    payload["phase_a_current_a"] = phase_a_current_a
    payload["phase_b_current_a"] = phase_b_current_a
    payload["rotor_radius_mm"] = _ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM
    payload["core_inner_mm"] = _ROTATING_FIELD_MOTOR_CORE_INNER_MM
    payload["core_outer_mm"] = _ROTATING_FIELD_MOTOR_CORE_OUTER_MM
    payload["core_half_width_mm"] = _ROTATING_FIELD_MOTOR_CORE_HALF_WIDTH_MM
    payload["coil_radius_mm"] = _ROTATING_FIELD_MOTOR_COIL_RADIUS_MM
    payload["coil_center_mm"] = _ROTATING_FIELD_MOTOR_COIL_CENTER_MM
    payload["coil_side_mm"] = _ROTATING_FIELD_MOTOR_COIL_SIDE_MM
    payload["coil_turns"] = _ROTOR_CHASE_COIL_TURNS
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_rotating_field_motor_sweep(
    *,
    peak_current_a: float = 8.0,
    field_component: Literal["combined", "stator", "rotor"] = "combined",
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Solve one source view while the PM rotor follows the field by 15 degrees."""

    if not 0.0 < peak_current_a <= 20.0:
        raise ValueError("peak_current_a must be greater than 0 and at most 20 A")
    if field_component not in {"combined", "stator", "rotor"}:
        raise ValueError("field_component must be combined, stator, or rotor")
    imported_mesh = _build_rotating_field_motor_gmsh_mesh(mesh_density=mesh_density)
    jobs = [
        float(angle_deg)
        for angle_deg in _ROTATING_FIELD_ANGLES_DEG
    ]

    def solve_job(angle_deg: float) -> dict[str, Any]:
        return run_rotating_field_motor_fixture(
            electrical_angle_deg=angle_deg,
            rotor_angle_deg=angle_deg - _ROTATING_FIELD_MOTOR_LAG_DEG,
            peak_current_a=peak_current_a,
            field_component=field_component,
            mesh_density=mesh_density,
            imported_mesh=imported_mesh,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        frames = list(executor.map(solve_job, jobs))
    return {
        "schema_version": "openem.rotating_field_motor_sweep.v2",
        "fixture": "rotating_field_motor",
        "field_component": field_component,
        "peak_current_a": peak_current_a,
        "frame_count": len(frames),
        "electrical_angles_deg": list(_ROTATING_FIELD_ANGLES_DEG),
        "rotor_motion_default": True,
        "rotor_lag_deg": _ROTATING_FIELD_MOTOR_LAG_DEG,
        "frames": frames,
    }


ThreePhaseFieldComponent = Literal[
    "combined",
    "stator",
    "rotor",
    "phase_a",
    "phase_b",
    "phase_c",
    "open_c",
]


def run_three_phase_motor_fixture(
    *,
    electrical_angle_deg: float = 0.0,
    rotor_angle_deg: float = -_ROTATING_FIELD_MOTOR_LAG_DEG,
    peak_current_a: float = 8.0,
    field_component: ThreePhaseFieldComponent = "combined",
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
    imported_mesh: dict[str, Any] | None = None,
    solve: bool = True,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Build or solve one six-tooth, three-phase teaching-motor frame."""

    supported_components = {
        "combined",
        "stator",
        "rotor",
        "phase_a",
        "phase_b",
        "phase_c",
        "open_c",
    }
    if not 0.0 <= peak_current_a <= 20.0:
        raise ValueError("peak_current_a must be between 0 and 20 A")
    if field_component not in supported_components:
        raise ValueError("unsupported three-phase field component")
    if not math.isfinite(electrical_angle_deg) or not math.isfinite(rotor_angle_deg):
        raise ValueError("electrical_angle_deg and rotor_angle_deg must be finite")

    normalized_angle_deg = electrical_angle_deg % 360.0
    normalized_rotor_angle_deg = rotor_angle_deg % 360.0
    angle_rad = math.radians(normalized_angle_deg)
    phase_a_current_a = peak_current_a * math.cos(angle_rad)
    phase_b_current_a = peak_current_a * math.cos(angle_rad - 2.0 * math.pi / 3.0)
    phase_c_current_a = peak_current_a * math.cos(angle_rad + 2.0 * math.pi / 3.0)
    if field_component == "open_c":
        phase_b_current_a = -phase_a_current_a
        phase_c_current_a = 0.0
    executable = ensure_magneto2d_binary() if runner is subprocess.run else None
    solver_fixture = {
        "combined": "three_phase_motor",
        "stator": "three_phase_motor_stator",
        "rotor": "three_phase_motor_rotor",
        "phase_a": "three_phase_motor_phase_a",
        "phase_b": "three_phase_motor_phase_b",
        "phase_c": "three_phase_motor_phase_c",
        "open_c": "three_phase_motor_open_c",
    }[field_component]
    request: dict[str, Any] = {
        "fixture": solver_fixture,
        "steel_return": False,
        "steel_shape": "bar",
        "steel_center_x_mm": 0.0,
        "steel_center_y_mm": 0.0,
        "magnet_center_x_mm": 0.0,
        "magnet_center_y_mm": 0.0,
        "magnet_angle_deg": normalized_rotor_angle_deg,
        "steel_angle_deg": normalized_angle_deg,
        "wire_current_a": peak_current_a,
        "mesh_density": mesh_density,
        "solve": solve,
    }
    if imported_mesh is not None:
        request["imported_mesh"] = imported_mesh
    elif runner is subprocess.run:
        request["imported_mesh"] = _build_three_phase_motor_gmsh_mesh(
            mesh_density=mesh_density
        )

    with tempfile.TemporaryDirectory(prefix="openem_three_phase_motor_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "report.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        completed = runner(
            [
                str(executable or "magneto2d"),
                str(input_path),
                "--mode",
                "teaching",
                "-o",
                str(output_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            **({"env": solver_process_environment()} if runner is subprocess.run else {}),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown solver failure").strip()
            raise Magneto2DExecutionError(
                f"Three-phase motor fixture failed: {detail}"
            )
        if not output_path.exists():
            raise Magneto2DExecutionError("Three-phase motor fixture produced no report")
        try:
            payload: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Magneto2DExecutionError(
                "Three-phase motor fixture returned invalid JSON"
            ) from exc

    payload["fixture"] = "three_phase_motor"
    payload["field_component"] = field_component
    payload["electrical_angle_deg"] = normalized_angle_deg
    payload["rotor_angle_deg"] = normalized_rotor_angle_deg
    active_phase_currents = {
        "phase_a": (
            phase_a_current_a if field_component != "rotor" else 0.0
        ),
        "phase_b": (
            phase_b_current_a if field_component != "rotor" else 0.0
        ),
        "phase_c": (
            phase_c_current_a if field_component != "rotor" else 0.0
        ),
    }
    if field_component == "phase_a":
        active_phase_currents["phase_b"] = 0.0
        active_phase_currents["phase_c"] = 0.0
    elif field_component == "phase_b":
        active_phase_currents["phase_a"] = 0.0
        active_phase_currents["phase_c"] = 0.0
    elif field_component == "phase_c":
        active_phase_currents["phase_a"] = 0.0
        active_phase_currents["phase_b"] = 0.0
    stator_vector_x = active_phase_currents["phase_a"]
    stator_vector_y = 0.0
    for phase_name, phase_axis_deg in (("phase_b", 120.0), ("phase_c", 240.0)):
        phase_axis_rad = math.radians(phase_axis_deg)
        stator_vector_x += active_phase_currents[phase_name] * math.cos(phase_axis_rad)
        stator_vector_y += active_phase_currents[phase_name] * math.sin(phase_axis_rad)
    stator_vector_magnitude = math.hypot(stator_vector_x, stator_vector_y)
    if field_component == "rotor":
        field_target_angle_deg = normalized_rotor_angle_deg
    elif stator_vector_magnitude > 1.0e-9:
        field_target_angle_deg = math.degrees(
            math.atan2(stator_vector_y, stator_vector_x)
        ) % 360.0
    else:
        field_target_angle_deg = normalized_angle_deg
    payload["field_target_angle_deg"] = field_target_angle_deg
    payload["torque_angle_deg"] = (
        field_target_angle_deg - normalized_rotor_angle_deg + 180.0
    ) % 360.0 - 180.0
    payload["peak_current_a"] = peak_current_a
    payload["phase_a_current_a"] = phase_a_current_a
    payload["phase_b_current_a"] = phase_b_current_a
    payload["phase_c_current_a"] = phase_c_current_a
    payload["phase_current_sum_a"] = (
        phase_a_current_a + phase_b_current_a + phase_c_current_a
    )
    payload["phase_c_open"] = field_component == "open_c"
    payload["rotor_radius_mm"] = _ROTATING_FIELD_MOTOR_ROTOR_RADIUS_MM
    payload["core_inner_mm"] = _THREE_PHASE_MOTOR_CORE_INNER_MM
    payload["core_outer_mm"] = _THREE_PHASE_MOTOR_CORE_OUTER_MM
    payload["core_half_width_mm"] = _THREE_PHASE_MOTOR_CORE_HALF_WIDTH_MM
    payload["coil_radius_mm"] = _THREE_PHASE_MOTOR_COIL_RADIUS_MM
    payload["coil_center_mm"] = _THREE_PHASE_MOTOR_COIL_CENTER_MM
    payload["coil_side_mm"] = _THREE_PHASE_MOTOR_COIL_SIDE_MM
    payload["coil_turns"] = _ROTOR_CHASE_COIL_TURNS
    az_nodal = payload.get("az_nodal") or []
    nodes_mm = payload.get("nodes_mm") or []
    triangles = payload.get("triangles") or []
    if az_nodal and nodes_mm and triangles:
        levels = generate_contour_levels(az_nodal, nodes_mm=nodes_mm, triangles=triangles)
        contours = generate_contour_segments(nodes_mm, triangles, az_nodal, levels)
        payload["contour_levels"] = [_contour_payload(contour) for contour in contours]
        payload["az_min"] = min(az_nodal)
        payload["az_max"] = max(az_nodal)
    else:
        payload["contour_levels"] = []
        payload["az_min"] = 0.0
        payload["az_max"] = 0.0
    return payload


def run_three_phase_motor_sweep(
    *,
    peak_current_a: float = 8.0,
    field_component: ThreePhaseFieldComponent = "combined",
    mesh_density: Literal["coarse", "normal", "fine"] = "normal",
) -> dict[str, Any]:
    """Solve one Lesson 8 source view over a complete electrical revolution."""

    if not 0.0 < peak_current_a <= 20.0:
        raise ValueError("peak_current_a must be greater than 0 and at most 20 A")
    imported_mesh = _build_three_phase_motor_gmsh_mesh(mesh_density=mesh_density)
    angles_deg = [float(angle_deg) for angle_deg in _ROTATING_FIELD_ANGLES_DEG]

    def solve_job(angle_deg: float) -> dict[str, Any]:
        return run_three_phase_motor_fixture(
            electrical_angle_deg=angle_deg,
            rotor_angle_deg=(
                -_ROTATING_FIELD_MOTOR_LAG_DEG
                if field_component == "open_c"
                else angle_deg - _ROTATING_FIELD_MOTOR_LAG_DEG
            ),
            peak_current_a=peak_current_a,
            field_component=field_component,
            mesh_density=mesh_density,
            imported_mesh=imported_mesh,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        frames = list(executor.map(solve_job, angles_deg))
    return {
        "schema_version": "openem.three_phase_motor_sweep.v1",
        "fixture": "three_phase_motor",
        "field_component": field_component,
        "peak_current_a": peak_current_a,
        "frame_count": len(frames),
        "electrical_angles_deg": angles_deg,
        "rotor_motion_default": True,
        "rotor_lag_deg": _ROTATING_FIELD_MOTOR_LAG_DEG,
        "frames": frames,
    }
