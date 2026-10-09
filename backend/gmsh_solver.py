"""Gmsh-backed mesh preview and Magneto2D solve-mesh artifact generation."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.custom_materials import is_custom_steel_id
from backend.geometry_drawer import (
    MotorGeometry,
    compute_3phase_current_density_for_rotor_elec,
    compute_geometry,
)
from backend.geometry_ir import GeometryIR, GeometryIRLoop, GeometryIRRegion, build_geometry_ir
from backend.models import MotorConfig
from backend.solver_environment import ISOLATED_RUNTIME
from backend.topology_provenance import build_topology_provenance

try:
    import gmsh  # type: ignore

    GMSH_AVAILABLE = True
except Exception:  # pragma: no cover - exercised when gmsh is installed
    gmsh = None  # type: ignore
    GMSH_AVAILABLE = False


class GmshUnavailableError(RuntimeError):
    """Raised when the user selects Gmsh but the local runtime is missing it."""


class GmshMeshQAError(ValueError):
    """Raised when a generated Gmsh solve mesh fails topology QA gates."""


_GMSH_API_LOCK = threading.Lock()
_GMSH_MESH_PROFILE_CONFIG_PATH = (
    Path(__file__).resolve().parent / "mesh_profiles" / "gmsh_profiles.json"
)
_GMSH_MESH_PROFILE_CONFIG_REPO_PATH = "backend/mesh_profiles/gmsh_profiles.json"


_PREVIEW_TO_SOLVE_REGION = {
    "shaft": "RotorCore",
    "rotor_core": "RotorCore",
    "magnet": "Magnet",
    "inter_pole_gap": "Airgap",
    "airgap": "Airgap",
    "slot_winding": "SlotWinding",
    "stator_tooth": "StatorTooth",
    "stator_yoke": "StatorYoke",
    "flux_barrier": "FluxBarrier",
    "magnet_pocket_air": "MagnetPocketAir",
}

_IR_KIND_TO_PREVIEW_REGION = {
    "Shaft": "shaft",
    "RotorCore": "rotor_core",
    "Magnet": "magnet",
    "MagnetPocketAir": "magnet_pocket_air",
    "Airgap": "airgap",
    "FluxBarrier": "flux_barrier",
    "SlotWinding": "slot_winding",
    "StatorTooth": "stator_tooth",
    "StatorYoke": "stator_yoke",
}


def _preview_region_for_contract_entry(contract_entry: dict[str, Any]) -> str:
    """Map a physics-contract region to the browser mesh preview tag."""
    kind = str(contract_entry.get("kind") or "")
    base = _IR_KIND_TO_PREVIEW_REGION.get(kind, kind.lower() or "unknown")
    if kind != "Magnet":
        return base
    source = str(contract_entry.get("source_group") or "")
    parts = source.split(":")
    if len(parts) >= 2 and parts[0] == "pm":
        polarity = parts[1].strip().lower()
        if polarity in {"n", "s"}:
            return f"magnet_{polarity}"
    return base


@dataclass
class _GmshGeometryBuilder:
    base_lc_mm: float
    center_tag: int = field(init=False)
    points: dict[tuple[int, int], int] = field(default_factory=dict)
    point_sizes: dict[int, float] = field(default_factory=dict)
    points_by_feature: dict[str, set[int]] = field(default_factory=dict)
    lines: dict[tuple[int, int], int] = field(default_factory=dict)
    arcs: dict[tuple[int, int, int], int] = field(default_factory=dict)
    curves_by_feature: dict[str, set[int]] = field(default_factory=dict)
    surfaces_by_region: dict[str, list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.center_tag = gmsh.model.geo.addPoint(0.0, 0.0, 0.0, self.base_lc_mm)

    def point(
        self,
        radius_mm: float,
        theta_rad: float,
        lc_mm: float | None = None,
        feature: str | None = None,
    ) -> int:
        x_mm = radius_mm * math.cos(theta_rad)
        y_mm = radius_mm * math.sin(theta_rad)
        key = (round(x_mm * 1.0e6), round(y_mm * 1.0e6))
        requested_lc_mm = lc_mm or self.base_lc_mm
        existing = self.points.get(key)
        if existing is not None:
            self._set_point_size(existing, requested_lc_mm)
            self._register_point_feature(existing, feature)
            return existing
        tag = gmsh.model.geo.addPoint(x_mm, y_mm, 0.0, requested_lc_mm)
        self.points[key] = tag
        self._set_point_size(tag, requested_lc_mm)
        self._register_point_feature(tag, feature)
        return tag

    def cartesian_point(
        self,
        x_mm: float,
        y_mm: float,
        lc_mm: float | None = None,
        feature: str | None = None,
    ) -> int:
        key = (round(x_mm * 1.0e6), round(y_mm * 1.0e6))
        requested_lc_mm = lc_mm or self.base_lc_mm
        existing = self.points.get(key)
        if existing is not None:
            self._set_point_size(existing, requested_lc_mm)
            self._register_point_feature(existing, feature)
            return existing
        tag = gmsh.model.geo.addPoint(x_mm, y_mm, 0.0, requested_lc_mm)
        self.points[key] = tag
        self._set_point_size(tag, requested_lc_mm)
        self._register_point_feature(tag, feature)
        return tag

    def line(self, start: int, end: int, feature: str | None = None) -> int:
        existing = self.lines.get((start, end))
        if existing is not None:
            self._register_curve_feature(existing, feature)
            return existing
        reverse = self.lines.get((end, start))
        if reverse is not None:
            self._register_curve_feature(reverse, feature)
            return -reverse
        tag = gmsh.model.geo.addLine(start, end)
        self.lines[(start, end)] = tag
        self._register_curve_feature(tag, feature)
        return tag

    def arc(self, radius_mm: float, theta_start: float, theta_end: float, feature: str | None = None) -> int:
        start = self.point(radius_mm, theta_start)
        end = self.point(radius_mm, theta_end)
        return self.circle_arc(start, self.center_tag, end, feature)

    def circle_arc(
        self,
        start: int,
        center: int,
        end: int,
        feature: str | None = None,
    ) -> int:
        key = (start, center, end)
        existing = self.arcs.get(key)
        if existing is not None:
            self._register_curve_feature(existing, feature)
            return existing
        reverse = self.arcs.get((end, center, start))
        if reverse is not None:
            self._register_curve_feature(reverse, feature)
            return -reverse
        tag = gmsh.model.geo.addCircleArc(start, center, end)
        self.arcs[key] = tag
        self._register_curve_feature(tag, feature)
        return tag

    def disk_sector(self, radius_mm: float, theta_start: float, theta_end: float, region: str) -> None:
        for a0, a1 in _split_interval(theta_start, theta_end):
            p_start = self.point(radius_mm, a0)
            p_end = self.point(radius_mm, a1)
            curves = [
                self.arc(radius_mm, a0, a1),
                self.line(p_end, self.center_tag),
                self.line(self.center_tag, p_start),
            ]
            self._add_surface(curves, region)

    def annular_sector(
        self,
        inner_radius_mm: float,
        outer_radius_mm: float,
        theta_start: float,
        theta_end: float,
        region: str,
        *,
        point_feature: str | None = None,
        point_lc_mm: float | None = None,
        inner_curve_feature: str | None = None,
        outer_curve_feature: str | None = None,
        radial_curve_feature: str | None = None,
    ) -> None:
        for a0, a1 in _split_interval(theta_start, theta_end):
            inner_start = self.point(inner_radius_mm, a0, point_lc_mm, point_feature)
            inner_end = self.point(inner_radius_mm, a1, point_lc_mm, point_feature)
            outer_start = self.point(outer_radius_mm, a0, point_lc_mm, point_feature)
            outer_end = self.point(outer_radius_mm, a1, point_lc_mm, point_feature)
            curves = [
                self.arc(outer_radius_mm, a0, a1, outer_curve_feature),
                self.line(outer_end, inner_end, radial_curve_feature),
                -self.arc(inner_radius_mm, a0, a1, inner_curve_feature),
                self.line(inner_start, outer_start, radial_curve_feature),
            ]
            self._add_surface(curves, region)

    def tapered_sector(
        self,
        inner_radius_mm: float,
        outer_radius_mm: float,
        inner_start: float,
        inner_end: float,
        outer_start: float,
        outer_end: float,
        region: str,
        *,
        point_feature: str | None = None,
        point_lc_mm: float | None = None,
        inner_curve_feature: str | None = None,
        outer_curve_feature: str | None = None,
        side_curve_feature: str | None = None,
    ) -> None:
        inner_end = _advance_after(inner_start, inner_end)
        outer_end = _advance_after(outer_start, outer_end)
        inner_start_point = self.point(inner_radius_mm, inner_start, point_lc_mm, point_feature)
        inner_end_point = self.point(inner_radius_mm, inner_end, point_lc_mm, point_feature)
        outer_start_point = self.point(outer_radius_mm, outer_start, point_lc_mm, point_feature)
        outer_end_point = self.point(outer_radius_mm, outer_end, point_lc_mm, point_feature)
        curves = [
            self.arc(outer_radius_mm, outer_start, outer_end, outer_curve_feature),
            self.line(outer_end_point, inner_end_point, side_curve_feature),
            -self.arc(inner_radius_mm, inner_start, inner_end, inner_curve_feature),
            self.line(inner_start_point, outer_start_point, side_curve_feature),
        ]
        self._add_surface(curves, region)

    def _add_surface(self, curves: list[int], region: str) -> None:
        loop = gmsh.model.geo.addCurveLoop(curves)
        surface = gmsh.model.geo.addPlaneSurface([loop])
        self.surfaces_by_region.setdefault(region, []).append(surface)

    def apply_point_sizes(self) -> None:
        for tag, lc_mm in self.point_sizes.items():
            gmsh.model.geo.mesh.setSize([(0, tag)], lc_mm)

    def _set_point_size(self, tag: int, lc_mm: float) -> None:
        current = self.point_sizes.get(tag)
        self.point_sizes[tag] = lc_mm if current is None else min(current, lc_mm)

    def _register_point_feature(self, tag: int, feature: str | None) -> None:
        if feature:
            self.points_by_feature.setdefault(feature, set()).add(tag)

    def _register_curve_feature(self, tag: int, feature: str | None) -> None:
        if feature:
            self.curves_by_feature.setdefault(feature, set()).add(abs(tag))


def run_gmsh_mesh_preview(
    config: MotorConfig,
    *,
    rotor_angle_deg: float | None = None,
) -> dict[str, Any]:
    """Generate a Gmsh mesh preview and embedded Magneto2D solve-mesh artifact."""

    if not GMSH_AVAILABLE:
        raise GmshUnavailableError(
            "Gmsh mesher is not available. Install the Python gmsh package "
            "in the backend environment to use the Gmsh mesh backend."
        )
    if config.solve_params is None:
        raise ValueError("Gmsh mesh preview requires solve_params")

    start = time.monotonic()
    geom = compute_geometry(config)
    _rotate_magnets_in_place(geom, math.radians(rotor_angle_deg or 0.0))
    density = config.solve_params.mesh_density or "normal"

    if str(config.topology).upper() in {"SPM", "IPM"}:
        # The Gmsh Python API owns process-global state and is not safe to
        # enter concurrently from FastAPI worker threads.
        with _GMSH_API_LOCK:
            return _run_gmsh_ir_mesh_preview(
                config,
                geom=geom,
                density=density,
                rotor_angle_deg=rotor_angle_deg or 0.0,
                start_time=start,
            )

    # Mesh preview runs in FastAPI's executor thread. The default Gmsh Python
    # initialization installs a signal handler, which is only legal on the main
    # Python thread.
    with _GMSH_API_LOCK:
        gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 5)
            gmsh.model.add("openem_motor_mesh")

            builder = _GmshGeometryBuilder(base_lc_mm=_base_lc_mm(config, density))
            _build_gmsh_surfaces(builder, geom)
            _mark_gmsh_physics_features(builder, geom)
            builder.apply_point_sizes()
            gmsh.model.geo.synchronize()
            _apply_gmsh_physics_mesh_fields(builder, geom, config)
            for region, surfaces in builder.surfaces_by_region.items():
                if surfaces:
                    gmsh.model.addPhysicalGroup(2, surfaces, name=region)
            gmsh.model.mesh.generate(2)

            nodes_mm, triangles = _extract_gmsh_triangles()
        finally:
            gmsh.finalize()

    regions = _classify_triangles_by_centroid(nodes_mm, triangles, geom)
    solve_regions = [_PREVIEW_TO_SOLVE_REGION[region] for region in regions]
    magnet_outer_radius_mm = config.rotor.OD_mm / 2.0 + config.rotor.magnet_thickness_mm
    stator_inner_radius_mm = config.stator.ID_mm / 2.0
    refined_gmsh = _gmsh_corner_refinement_enabled(config)
    mesh_info = {
        "num_nodes": len(nodes_mm),
        "num_triangles": len(triangles),
        "pole_pitch_deg": 360.0 / max(1, config.rotor.pole_count),
        "n_pole_pitches": config.rotor.pole_count,
        "total_span_deg": 360.0,
        "angular_divisions": 0,
        "radial_rings": 0,
        "mesh_density": f"gmsh_{density}",
        **_gmsh_refinement_profile_metadata(config),
        **_gmsh_mesh_size_metadata(config, builder.base_lc_mm),
        "corner_refinement": refined_gmsh,
        "radial_layers": ["gmsh_import"],
        "physics_aware_refinement": True,
        "refinement_features": sorted(
            set(builder.points_by_feature.keys()) | set(builder.curves_by_feature.keys())
        ),
        "airgap_inner_radius_mm": magnet_outer_radius_mm,
        "airgap_outer_radius_mm": stator_inner_radius_mm,
        "mesh_source": "gmsh",
        "magnet_outer_radius_mm": magnet_outer_radius_mm,
        "magnet_embrace": config.rotor.magnet_embrace,
        "stator_inner_radius_mm": stator_inner_radius_mm,
        "stator_slot_outer_radius_mm": _slot_outer_radius_mm(geom),
        "stator_outer_radius_mm": config.stator.OD_mm / 2.0,
        "topology_provenance": build_topology_provenance(config),
    }
    solve_mesh_artifact = {
        "mesh": {
            "nodes": nodes_mm,
            "length_units": "mm",
            "triangles": triangles,
            "regions": solve_regions,
            "boundary_nodes": _outer_boundary_nodes(nodes_mm, config.stator.OD_mm / 2.0),
            "sector_edge_pairs": [],
            "info": mesh_info,
        },
        "element_region_ids": regions,
        "topology_provenance": build_topology_provenance(config),
    }
    generation_time_ms = int((time.monotonic() - start) * 1000)
    return {
        "config_summary": {
            "topology": config.topology,
            "slots": config.stator.slot_count,
            "poles": config.rotor.pole_count,
            "stator_od_mm": config.stator.OD_mm,
            "rotor_od_mm": config.rotor.OD_mm,
            "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
            "stack_length_mm": config.stator.stack_length_mm,
        },
        "mesh_info": mesh_info,
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "regions": regions,
        "n_pole_pitches": config.rotor.pole_count,
        "total_span_deg": 360.0,
        "generation_time_ms": generation_time_ms,
        "solve_mesh_artifact": solve_mesh_artifact,
    }


def _run_gmsh_ir_mesh_preview(
    config: MotorConfig,
    *,
    geom: MotorGeometry,
    density: str,
    rotor_angle_deg: float,
    start_time: float,
) -> dict[str, Any]:
    """Generate an IR-driven Gmsh mesh for SPM/IPM topologies."""

    ir = build_geometry_ir(config, geom=geom)
    ir_report = ir.validation_report()
    if ir_report.issues:
        joined = "; ".join(ir_report.issues)
        raise GmshMeshQAError(f"Geometry IR failed before Gmsh meshing: {joined}")

    # No _GMSH_API_LOCK here: run_gmsh_mesh_preview already holds it across the call
    # into this function. threading.Lock is not reentrant, so taking it again would
    # deadlock the request thread outright.
    gmsh.initialize(readConfigFiles=not ISOLATED_RUNTIME, interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 5)
        gmsh.model.add("openem_ir_motor_mesh")

        builder = _GmshGeometryBuilder(base_lc_mm=_base_lc_mm(config, density))
        region_by_surface = _build_ir_gmsh_surfaces(builder, ir)
        builder.apply_point_sizes()
        gmsh.model.geo.synchronize()
        _apply_gmsh_physics_mesh_fields(builder, geom, config)
        for region in ir.regions:
            surfaces = builder.surfaces_by_region.get(region.region_id, [])
            if surfaces:
                gmsh.model.addPhysicalGroup(
                    2,
                    surfaces,
                    name=_gmsh_physical_name(region),
                )
        gmsh.model.mesh.generate(2)
        nodes_mm, triangles, element_region_ids = _extract_gmsh_triangles_by_surface(
            region_by_surface
        )
    finally:
        gmsh.finalize()

    solve_mesh_artifact = _build_ir_solve_mesh_artifact(
        config,
        ir,
        geom,
        nodes_mm,
        triangles,
        element_region_ids,
        density=density,
        rotor_angle_deg=rotor_angle_deg,
        builder=builder,
    )
    mesh_qa = _validate_gmsh_ir_solve_mesh_artifact(solve_mesh_artifact, ir)
    generation_time_ms = int((time.monotonic() - start_time) * 1000)
    contract_regions = solve_mesh_artifact["physics_contract"]["regions"]
    contract_region_by_id = {entry["id"]: entry for entry in contract_regions}
    regions = [
        _preview_region_for_contract_entry(contract_region_by_id[region_id])
        for region_id in element_region_ids
    ]
    return {
        "config_summary": {
            "topology": config.topology,
            "ipm_topology": getattr(config.rotor, "ipm_topology", None),
            "slots": config.stator.slot_count,
            "poles": config.rotor.pole_count,
            "stator_od_mm": config.stator.OD_mm,
            "rotor_od_mm": config.rotor.OD_mm,
            "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
            "stack_length_mm": config.stator.stack_length_mm,
        },
        "mesh_info": solve_mesh_artifact["mesh"]["info"],
        "mesh_qa": mesh_qa,
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "regions": regions,
        "element_region_ids": element_region_ids,
        "n_pole_pitches": config.rotor.pole_count,
        "total_span_deg": 360.0,
        "generation_time_ms": generation_time_ms,
        "solve_mesh_artifact": solve_mesh_artifact,
    }


def _build_ir_gmsh_surfaces(
    builder: _GmshGeometryBuilder,
    ir: GeometryIR,
) -> dict[int, str]:
    region_by_surface: dict[int, str] = {}
    for region in ir.regions:
        if not region.loops:
            continue
        if region.kind == "Airgap" and len(region.loops) == 2:
            outer_radius = _central_circle_radius(region.loops[0])
            inner_radius = _central_circle_radius(region.loops[1])
            if (
                outer_radius is not None
                and inner_radius is not None
                and outer_radius > inner_radius
                and outer_radius - inner_radius
                <= 2.0 * _feature_lc_mm(builder.base_lc_mm, "airgap")
            ):
                outer_loop = _curve_loop_from_ir_loop(
                    builder,
                    region,
                    region.loops[0],
                )
                inner_loop = _curve_loop_from_ir_loop(
                    builder,
                    region,
                    region.loops[1],
                    reverse=True,
                )
                midpoint_radius = 0.5 * (inner_radius + outer_radius)
                midpoint_outer = _central_circle_curve_loop(
                    builder,
                    radius_mm=midpoint_radius,
                    reverse=False,
                )
                midpoint_inner = _central_circle_curve_loop(
                    builder,
                    radius_mm=midpoint_radius,
                    reverse=True,
                )
                surfaces = [
                    gmsh.model.geo.addPlaneSurface([midpoint_outer, inner_loop]),
                    gmsh.model.geo.addPlaneSurface([outer_loop, midpoint_inner]),
                ]
                builder.surfaces_by_region.setdefault(region.region_id, []).extend(
                    surfaces
                )
                region_by_surface.update(
                    {surface: region.region_id for surface in surfaces}
                )
                continue
        outer_loop = _curve_loop_from_ir_loop(builder, region, region.loops[0])
        hole_loops = [
            _curve_loop_from_ir_loop(builder, region, loop, reverse=True)
            for loop in region.loops[1:]
        ]
        surface = gmsh.model.geo.addPlaneSurface([outer_loop, *hole_loops])
        builder.surfaces_by_region.setdefault(region.region_id, []).append(surface)
        region_by_surface[surface] = region.region_id
    return region_by_surface


def _central_circle_radius(loop: GeometryIRLoop) -> float | None:
    radii: list[float] = []
    for segment in loop.segments:
        center = segment.center
        radius = segment.radius_mm
        if (
            segment.kind != "arc"
            or center is None
            or abs(center.x_mm) > 1.0e-9
            or abs(center.y_mm) > 1.0e-9
            or radius is None
            or radius <= 0.0
        ):
            return None
        radii.append(float(radius))
    if not radii or max(radii) - min(radii) > 1.0e-9:
        return None
    return radii[0]


def _central_circle_curve_loop(
    builder: _GmshGeometryBuilder,
    *,
    radius_mm: float,
    reverse: bool,
) -> int:
    point_lc = _feature_lc_mm(builder.base_lc_mm, "airgap")
    angles = [index * 0.5 * math.pi for index in range(5)]
    curves: list[int] = []
    for start_angle, end_angle in zip(angles, angles[1:]):
        builder.point(
            radius_mm,
            start_angle,
            point_lc,
            "airgap_interface",
        )
        builder.point(
            radius_mm,
            end_angle,
            point_lc,
            "airgap_interface",
        )
        curves.append(
            builder.arc(
                radius_mm,
                start_angle,
                end_angle,
                "airgap_band",
            )
        )
    if reverse:
        curves = [-curve for curve in reversed(curves)]
    return gmsh.model.geo.addCurveLoop(curves)


def _curve_loop_from_ir_loop(
    builder: _GmshGeometryBuilder,
    region: GeometryIRRegion,
    loop: GeometryIRLoop,
    *,
    reverse: bool = False,
) -> int:
    curves: list[int] = []
    point_feature = _ir_point_feature(region)
    point_lc = _feature_lc_mm(builder.base_lc_mm, point_feature) if point_feature else None
    curve_feature = _ir_curve_feature(region)

    for segment in loop.segments:
        start = builder.cartesian_point(
            segment.start.x_mm,
            segment.start.y_mm,
            point_lc,
            point_feature,
        )
        end = builder.cartesian_point(
            segment.end.x_mm,
            segment.end.y_mm,
            point_lc,
            point_feature,
        )
        if segment.kind == "arc":
            radius = segment.radius_mm
            if radius is None or radius <= 0:
                raise GmshMeshQAError(f"IR loop {loop.loop_id} has arc without radius")
            center = segment.center
            if center is None:
                raise GmshMeshQAError(f"IR loop {loop.loop_id} has arc without center")
            if abs(center.x_mm) <= 1e-9 and abs(center.y_mm) <= 1e-9:
                start_angle = math.atan2(segment.start.y_mm, segment.start.x_mm)
                end_angle = math.atan2(segment.end.y_mm, segment.end.x_mm)
                if segment.sweep_deg is not None and segment.sweep_deg < 0:
                    curves.append(-builder.arc(radius, end_angle, start_angle, curve_feature))
                else:
                    curves.append(builder.arc(radius, start_angle, end_angle, curve_feature))
            else:
                center_tag = builder.cartesian_point(center.x_mm, center.y_mm)
                if segment.sweep_deg is not None and segment.sweep_deg < 0:
                    curves.append(-builder.circle_arc(end, center_tag, start, curve_feature))
                else:
                    curves.append(builder.circle_arc(start, center_tag, end, curve_feature))
        else:
            curves.append(builder.line(start, end, curve_feature))

    if reverse:
        curves = [-curve for curve in reversed(curves)]
    return gmsh.model.geo.addCurveLoop(curves)


def _ir_point_feature(region: GeometryIRRegion) -> str | None:
    if region.kind in {"Magnet", "MagnetPocketAir"}:
        return "magnet_corner"
    if region.kind == "SlotWinding":
        return "slot_mouth"
    if region.kind == "StatorTooth":
        return "slot_tooth_corner"
    if region.kind == "Airgap":
        return "airgap_interface"
    return None


def _ir_curve_feature(region: GeometryIRRegion) -> str | None:
    if region.kind == "Airgap":
        return "airgap_band"
    if region.kind == "Shaft":
        return "shaft_bore"
    if region.kind == "SlotWinding":
        return "slot_mouth"
    return None


def _gmsh_physical_name(region: GeometryIRRegion) -> str:
    source = region.source_group or "none"
    return (
        f"{region.region_id}|kind={region.kind}|material={region.material_key}"
        f"|source={source}|motion={region.motion_group}"
    )


def _ir_solve_region_kind(region: GeometryIRRegion) -> str:
    if region.kind == "Shaft":
        if _material_key_compatible_with_solve_kind("RotorCore", region.material_key):
            return "RotorCore"
        return "MagnetPocketAir"
    return region.kind


# Mirrors the acceptance rules of `material_from_contract_key` in
# solvers/magneto2d/src/materials.rs so an incompatible (kind, material)
# pair fails at mesh QA instead of inside the Rust solver.
_QA_STEEL_GRADES = {"M350-50A", "M19", "M27", "M36", "NO20", "NO27", "1018_steel"}
_QA_MAGNET_GRADES = {
    "N35",
    "N38",
    "N42",
    "N45",
    "N48",
    "N48SH",
    "N52",
    "Ferrite",
    "Ferrite_Y30",
    "Prius_2004_NdFeB",
}


def _material_key_compatible_with_solve_kind(solve_kind: str, material_key: str) -> bool:
    key = str(material_key).strip()
    if solve_kind in {"RotorCore", "StatorTooth", "StatorYoke"}:
        grade = key
        for prefix in ("steel:stator:", "steel:rotor:", "steel:"):
            if key.startswith(prefix):
                grade = key[len(prefix):]
                break
        return grade in _QA_STEEL_GRADES or is_custom_steel_id(grade)
    if solve_kind == "Magnet":
        grade = key[len("magnet:"):] if key.startswith("magnet:") else key
        return grade in _QA_MAGNET_GRADES
    if solve_kind in {"Airgap", "FluxBarrier", "MagnetPocketAir"}:
        return key == "air" or key.startswith("air:")
    if solve_kind == "SlotWinding":
        return key == "air" or key.startswith("conductor:")
    return False


def _extract_gmsh_triangles_by_surface(
    region_by_surface: dict[int, str],
) -> tuple[list[list[float]], list[list[int]], list[str]]:
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes: list[list[float]] = []
    tag_to_index: dict[int, int] = {}
    for idx, tag in enumerate(node_tags):
        coord_idx = idx * 3
        tag_to_index[int(tag)] = idx
        nodes.append([float(node_coords[coord_idx]), float(node_coords[coord_idx + 1])])

    triangles: list[list[int]] = []
    element_region_ids: list[str] = []
    for surface, region_id in sorted(region_by_surface.items()):
        elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(2, surface)
        for elem_type, connectivity in zip(elem_types, elem_node_tags):
            if int(elem_type) != 2:
                continue
            for idx in range(0, len(connectivity), 3):
                tri = [
                    tag_to_index[int(connectivity[idx])],
                    tag_to_index[int(connectivity[idx + 1])],
                    tag_to_index[int(connectivity[idx + 2])],
                ]
                if _signed_area(nodes, tri) < 0.0:
                    tri = [tri[0], tri[2], tri[1]]
                triangles.append(tri)
                element_region_ids.append(region_id)
    if not triangles:
        raise GmshMeshQAError("Gmsh generated no first-order triangle elements")
    compact_nodes, compact_triangles = _compact_mesh_nodes(nodes, triangles)
    return compact_nodes, compact_triangles, element_region_ids


def _compact_mesh_nodes(
    nodes: list[list[float]],
    triangles: list[list[int]],
) -> tuple[list[list[float]], list[list[int]]]:
    used = sorted({node_idx for tri in triangles for node_idx in tri})
    remap = {old_idx: new_idx for new_idx, old_idx in enumerate(used)}
    compact_nodes = [nodes[old_idx] for old_idx in used]
    compact_triangles = [[remap[idx] for idx in tri] for tri in triangles]
    return compact_nodes, compact_triangles


def _build_ir_solve_mesh_artifact(
    config: MotorConfig,
    ir: GeometryIR,
    geom: MotorGeometry,
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    element_region_ids: list[str],
    *,
    density: str,
    rotor_angle_deg: float,
    builder: _GmshGeometryBuilder,
) -> dict[str, Any]:
    region_by_id = {region.region_id: region for region in ir.regions}
    solve_regions = [
        _ir_solve_region_kind(region_by_id[region_id])
        for region_id in element_region_ids
    ]
    magnetization_by_region = {
        region.region_id: (
            math.degrees(math.atan2(region.magnetization_xy[1], region.magnetization_xy[0])) % 360.0
            if region.magnetization_xy is not None
            else None
        )
        for region in ir.regions
    }
    current_density_by_region = _current_density_by_ir_region(config, ir, rotor_angle_deg)
    element_magnetization = [
        magnetization_by_region.get(region_id)
        if region_by_id[region_id].kind == "Magnet"
        else None
        for region_id in element_region_ids
    ]
    element_current_density = [
        current_density_by_region.get(region_id)
        if region_by_id[region_id].kind == "SlotWinding"
        else None
        for region_id in element_region_ids
    ]
    stator_outer_radius_mm = config.stator.OD_mm / 2.0
    refined_gmsh = _gmsh_corner_refinement_enabled(config)
    if str(config.topology).upper() == "SPM" and geom.magnets:
        airgap_inner_radius_mm = max(magnet.outer_radius_mm for magnet in geom.magnets)
    else:
        airgap_inner_radius_mm = config.rotor.OD_mm / 2.0
    stator_inner_radius_mm = config.stator.ID_mm / 2.0
    slot_outer_radius_mm = _slot_outer_radius_mm(geom)
    region_contracts = []
    for region in ir.regions:
        entry: dict[str, Any] = {
            "id": region.region_id,
            "kind": _ir_solve_region_kind(region),
            "geometry_ir_kind": region.kind,
            "material": region.material_key,
            "motion_group": region.motion_group,
        }
        if region.source_group is not None:
            entry["source_group"] = region.source_group
        mag_angle = magnetization_by_region.get(region.region_id)
        if mag_angle is not None:
            entry["magnetization_angle_deg"] = mag_angle
        current_density = current_density_by_region.get(region.region_id)
        if current_density is not None:
            entry["current_density_a_per_m2"] = current_density
        winding = _winding_contract_metadata(
            config,
            region,
            current_density,
            geom,
        )
        if winding is not None:
            entry["winding"] = winding
        region_contracts.append(entry)

    mesh_info = {
        "num_nodes": len(nodes_mm),
        "num_triangles": len(triangles),
        "pole_pitch_deg": 360.0 / max(1, config.rotor.pole_count),
        "n_pole_pitches": config.rotor.pole_count,
        "total_span_deg": 360.0,
        "angular_divisions": 0,
        "radial_rings": 0,
        "mesh_density": f"gmsh_{density}",
        **_gmsh_refinement_profile_metadata(config),
        **_gmsh_mesh_size_metadata(config, builder.base_lc_mm),
        "corner_refinement": refined_gmsh,
        "radial_layers": ["geometry_ir"],
        "physics_aware_refinement": True,
        "refinement_features": sorted(
            set(builder.points_by_feature.keys()) | set(builder.curves_by_feature.keys())
        ),
        "geometry_ir_version": ir.version,
        "airgap_inner_radius_mm": airgap_inner_radius_mm,
        "airgap_outer_radius_mm": stator_inner_radius_mm,
        "mesh_source": "gmsh",
        "mesh_source_detail": "geometry_ir",
        "magnet_outer_radius_mm": airgap_inner_radius_mm,
        "magnet_embrace": config.rotor.magnet_embrace,
        "stator_inner_radius_mm": stator_inner_radius_mm,
        "stator_slot_outer_radius_mm": slot_outer_radius_mm,
        "stator_outer_radius_mm": stator_outer_radius_mm,
        "topology_provenance": build_topology_provenance(config),
        "gmsh_physical_names": {
            region.region_id: _gmsh_physical_name(region) for region in ir.regions
        },
    }
    return {
        "mesh": {
            "nodes": nodes_mm,
            "length_units": "mm",
            "triangles": triangles,
            "regions": solve_regions,
            "boundary_nodes": _outer_boundary_nodes(nodes_mm, stator_outer_radius_mm),
            "sector_edge_pairs": [],
            "info": mesh_info,
        },
        "element_region_ids": element_region_ids,
        "element_magnetization": element_magnetization,
        "element_current_density_a_per_m2": element_current_density,
        "topology_provenance": build_topology_provenance(config),
        "rotor_angle_mech_deg": rotor_angle_deg,
        "physics_contract": {
            "version": "magneto2d_imported_physics/v0",
            "topology_hint": config.topology,
            "geometry_ir_version": ir.version,
            "units": {
                "length": "mm",
                "angle": "deg",
                "current_density": "A_per_m2",
                "magnetization_angle": "deg",
            },
            "motion": {
                "rotor_angle_mech_deg": rotor_angle_deg,
                "rotor_state": "baked_in_mesh",
            },
            "boundary_policy": {
                "outer_boundary": "dirichlet_az_zero",
                "sector_edges": "none",
            },
            "regions": region_contracts,
            "provenance": {
                "mesh_source": "gmsh",
                "geometry_source": ir.version,
                "topology_provenance": build_topology_provenance(config),
                "region_source": "geometry_ir",
                "current_density_source": "geometry_ir_winding_table",
                "magnetization_source": "geometry_ir",
                "material_assignment_source": "geometry_ir",
                "element_region_sources": ["gmsh_physical_surface"] * len(triangles),
                "element_current_density_sources": [
                    "geometry_ir_winding_table"
                    if region_by_id[region_id].kind == "SlotWinding"
                    else "none"
                    for region_id in element_region_ids
                ],
                "element_magnetization_sources": [
                    "geometry_ir"
                    if region_by_id[region_id].kind == "Magnet"
                    else "none"
                    for region_id in element_region_ids
                ],
                "element_material_sources": ["geometry_ir"] * len(triangles),
            },
        },
    }


def _current_density_by_ir_region(
    config: MotorConfig,
    ir: GeometryIR,
    rotor_angle_mech_deg: float,
) -> dict[str, float]:
    pole_pairs = max(1, int(config.rotor.pole_count) // 2)
    rotor_angle_elec_deg = float(rotor_angle_mech_deg) * pole_pairs
    phase_current_density_a_per_mm2 = compute_3phase_current_density_for_rotor_elec(
        config,
        rotor_angle_elec_deg,
    )
    out: dict[str, float] = {}
    for region in ir.regions:
        if region.kind != "SlotWinding" or not region.source_group:
            continue
        parts = region.source_group.split(":")
        if len(parts) < 3:
            continue
        phase = parts[1]
        direction = parts[2]
        density = phase_current_density_a_per_mm2.get(phase, 0.0)
        if direction == "out":
            density = -density
        out[region.region_id] = density * 1.0e6
    return out


def _winding_contract_metadata(
    config: MotorConfig,
    region: GeometryIRRegion,
    current_density_a_per_m2: float | None,
    geom: MotorGeometry,
) -> dict[str, Any] | None:
    if region.kind != "SlotWinding":
        return None

    metadata: dict[str, Any] = {
        "winding_type": config.winding.type,
        "turns_per_coil": config.winding.turns_per_coil,
        "layers": config.winding.layers,
        "parallel_paths": config.winding.parallel_paths,
        "current_density_source": "geometry_ir_winding_table",
        "turn_fraction": 1.0,
    }
    if config.winding.coil_span is not None:
        metadata["coil_span"] = config.winding.coil_span
    if current_density_a_per_m2 is not None:
        metadata["current_density_a_per_m2"] = float(current_density_a_per_m2)

    source_group = region.source_group or ""
    parts = source_group.split(":")
    slot_index: int | None = None
    layer_index: int | None = None
    if len(parts) >= 4 and parts[0] == "winding":
        metadata["phase"] = parts[1]
        metadata["direction"] = parts[2]
        slot_token = parts[3]
        if slot_token.startswith("slot") and slot_token[4:].isdigit():
            slot_index = int(slot_token[4:])
            metadata["slot_index"] = slot_index
        if len(parts) >= 5:
            layer_token = parts[4]
            if layer_token.startswith("layer") and layer_token[5:].isdigit():
                layer_index = int(layer_token[5:])
                metadata["layer"] = layer_index
                metadata["turn_fraction"] = 1.0 / max(1, int(config.winding.layers))

    if slot_index is not None and layer_index is None:
        slot = next((slot for slot in geom.slots if slot.slot_index == slot_index), None)
        if slot is not None:
            metadata["layer"] = int(getattr(slot, "layer", 1))

    return metadata


def _validate_gmsh_ir_solve_mesh_artifact(
    artifact: dict[str, Any],
    ir: GeometryIR,
    *,
    min_quality: float = 0.01,
) -> dict[str, Any]:
    mesh = artifact["mesh"]
    nodes = mesh["nodes"]
    triangles = mesh["triangles"]
    solve_regions = mesh["regions"]
    element_region_ids = artifact["element_region_ids"]
    if not triangles or len(solve_regions) != len(triangles):
        raise GmshMeshQAError("Gmsh mesh has missing or mismatched element regions")
    if len(element_region_ids) != len(triangles):
        raise GmshMeshQAError("Gmsh mesh has missing element_region_ids")
    region_by_id = {region.region_id: region for region in ir.regions}
    unknown = sorted(set(element_region_ids) - set(region_by_id))
    if unknown:
        raise GmshMeshQAError(f"Gmsh mesh has unknown region ids: {unknown}")

    component_sizes = _mesh_component_sizes(len(nodes), triangles)
    if len(component_sizes) != 1:
        raise GmshMeshQAError(
            f"Gmsh mesh is disconnected: components={component_sizes}"
        )

    qualities = [_triangle_quality(nodes, tri) for tri in triangles]
    min_observed = min(qualities)
    if min_observed < min_quality:
        raise GmshMeshQAError(
            f"Gmsh mesh quality below threshold: min={min_observed:.5f}, "
            f"threshold={min_quality:.5f}"
        )

    element_magnetization = artifact.get("element_magnetization")
    if not isinstance(element_magnetization, list) or len(element_magnetization) != len(triangles):
        raise GmshMeshQAError("Gmsh mesh missing element_magnetization metadata")
    element_current_density = artifact.get("element_current_density_a_per_m2")
    if not isinstance(element_current_density, list) or len(element_current_density) != len(triangles):
        raise GmshMeshQAError("Gmsh mesh missing element_current_density metadata")

    region_counts: dict[str, int] = {}
    area_by_region_id = {region.region_id: 0.0 for region in ir.regions}
    for idx, region_id in enumerate(element_region_ids):
        region = region_by_id[region_id]
        region_counts[region.kind] = region_counts.get(region.kind, 0) + 1
        area_by_region_id[region_id] += abs(_signed_area(nodes, triangles[idx]))
        if region.kind == "Magnet" and element_magnetization[idx] is None:
            raise GmshMeshQAError(f"Magnet element {idx} lacks magnetization")
        if region.kind == "SlotWinding" and element_current_density[idx] is None:
            raise GmshMeshQAError(f"SlotWinding element {idx} lacks current density")
    required_kinds = {"RotorCore", "Magnet", "Airgap", "StatorYoke", "SlotWinding"}
    missing = sorted(kind for kind in required_kinds if region_counts.get(kind, 0) <= 0)
    if missing:
        raise GmshMeshQAError(f"Gmsh mesh missing required region kinds: {missing}")

    for region in ir.regions:
        solve_kind = _ir_solve_region_kind(region)
        if not _material_key_compatible_with_solve_kind(solve_kind, region.material_key):
            raise GmshMeshQAError(
                f"Region '{region.region_id}' material key '{region.material_key}' "
                f"is not accepted by the solver for kind '{solve_kind}'"
            )

    area_delta_pct: dict[str, float] = {}
    for region in ir.regions:
        if region.area_mm2 <= 1.0e-9:
            continue
        actual_area = area_by_region_id.get(region.region_id, 0.0)
        delta_pct = abs(actual_area - region.area_mm2) / region.area_mm2 * 100.0
        area_delta_pct[region.region_id] = delta_pct
        tolerance_pct = 5.0
        tolerance_mm2 = 0.5
        if delta_pct > tolerance_pct and abs(actual_area - region.area_mm2) > tolerance_mm2:
            raise GmshMeshQAError(
                f"Gmsh mesh region area mismatch for {region.region_id}: "
                f"expected={region.area_mm2:.6g}mm^2 actual={actual_area:.6g}mm^2 "
                f"delta={delta_pct:.3f}%"
            )

    return {
        "status": "pass",
        "min_triangle_quality": min_observed,
        "min_quality_threshold": min_quality,
        "connected_components": len(component_sizes),
        "component_sizes": component_sizes,
        "region_counts": region_counts,
        "max_region_area_delta_pct": max(area_delta_pct.values(), default=0.0),
        "region_area_delta_pct": area_delta_pct,
    }


def _mesh_component_sizes(node_count: int, triangles: list[list[int]]) -> list[int]:
    adjacency: list[set[int]] = [set() for _ in range(node_count)]
    referenced: set[int] = set()
    for i, j, k in triangles:
        referenced.update((i, j, k))
        adjacency[i].update((j, k))
        adjacency[j].update((i, k))
        adjacency[k].update((i, j))
    seen: set[int] = set()
    sizes: list[int] = []
    for start in sorted(referenced):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def _triangle_quality(nodes: list[list[float]], tri: list[int]) -> float:
    i, j, k = tri
    a = _distance(nodes[j], nodes[k])
    b = _distance(nodes[i], nodes[k])
    c = _distance(nodes[i], nodes[j])
    area = abs(_signed_area(nodes, tri))
    denom = a * a + b * b + c * c
    if denom <= 1.0e-18:
        return 0.0
    return 4.0 * math.sqrt(3.0) * area / denom


def _distance(p: list[float], q: list[float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


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


def _rotate_points(
    points: tuple[tuple[float, float], ...],
    angle_rad: float,
) -> tuple[tuple[float, float], ...]:
    return tuple(_rotate_point(point, angle_rad) for point in points)


def _rotate_point(point: tuple[float, float], angle_rad: float) -> tuple[float, float]:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    x, y = point
    return (x * c - y * s, x * s + y * c)


def _build_gmsh_surfaces(builder: _GmshGeometryBuilder, geom: MotorGeometry) -> None:
    magnet_outer_radius = max((m.outer_radius_mm for m in geom.magnets), default=geom.rotor_OD_r)
    slot_outer_radius = _slot_outer_radius_mm(geom)
    base_breakpoints = _uniform_angles(max(geom.slot_count * 2, geom.pole_count * 4, 48))
    airgap_lc = _feature_lc_mm(builder.base_lc_mm, "airgap")

    for a0, a1 in _angle_pairs(base_breakpoints):
        builder.disk_sector(geom.rotor_OD_r, a0, a1, "rotor_core")

    magnet_edges: list[float] = []
    for magnet in geom.magnets:
        magnet_edges.extend(
            [
                magnet.center_angle_rad - magnet.half_width_rad,
                magnet.center_angle_rad + magnet.half_width_rad,
            ]
        )
    magnet_breakpoints = _merged_angles(base_breakpoints + magnet_edges)
    for a0, a1 in _angle_pairs(magnet_breakpoints):
        mid = 0.5 * (a0 + a1)
        region = "magnet" if _is_magnet_angle(mid, geom) else "inter_pole_gap"
        builder.annular_sector(geom.rotor_OD_r, magnet_outer_radius, a0, a1, region)

    slot_inner_edges: list[float] = []
    slot_outer_edges: list[float] = []
    for slot in geom.slots:
        slot_inner_edges.extend(slot.edge_angles_at_radius(slot.inner_radius_mm))
        slot_outer_edges.extend(slot.edge_angles_at_radius(slot.outer_radius_mm))
    airgap_breakpoints = _merged_angles(base_breakpoints + magnet_edges + slot_inner_edges)
    for a0, a1 in _angle_pairs(airgap_breakpoints):
        builder.annular_sector(
            magnet_outer_radius,
            geom.stator_ID_r,
            a0,
            a1,
            "airgap",
            point_feature="airgap_interface",
            point_lc_mm=airgap_lc,
            inner_curve_feature="airgap_band",
            outer_curve_feature="airgap_band",
            radial_curve_feature="airgap_radial_split",
        )

    if geom.slots:
        for slot in geom.slots:
            inner_left, inner_right = slot.edge_angles_at_radius(slot.inner_radius_mm)
            outer_left, outer_right = slot.edge_angles_at_radius(slot.outer_radius_mm)
            builder.tapered_sector(
                slot.inner_radius_mm,
                slot.outer_radius_mm,
                inner_left,
                inner_right,
                outer_left,
                outer_right,
                "slot_winding",
                inner_curve_feature="slot_mouth",
            )

        for idx, slot in enumerate(geom.slots):
            next_slot = geom.slots[(idx + 1) % len(geom.slots)]
            inner_start = slot.edge_angles_at_radius(slot.inner_radius_mm)[1]
            inner_end = next_slot.edge_angles_at_radius(next_slot.inner_radius_mm)[0]
            outer_start = slot.edge_angles_at_radius(slot.outer_radius_mm)[1]
            outer_end = next_slot.edge_angles_at_radius(next_slot.outer_radius_mm)[0]
            builder.tapered_sector(
                slot.inner_radius_mm,
                slot.outer_radius_mm,
                inner_start,
                inner_end,
                outer_start,
                outer_end,
                "stator_tooth",
                inner_curve_feature="tooth_tip",
            )
    elif slot_outer_radius > geom.stator_ID_r + 1.0e-9:
        for a0, a1 in _angle_pairs(base_breakpoints):
            builder.annular_sector(geom.stator_ID_r, slot_outer_radius, a0, a1, "stator_tooth")

    yoke_breakpoints = _merged_angles(base_breakpoints + slot_outer_edges)
    for a0, a1 in _angle_pairs(yoke_breakpoints):
        builder.annular_sector(slot_outer_radius, geom.stator_OD_r, a0, a1, "stator_yoke")


def _mark_gmsh_physics_features(builder: _GmshGeometryBuilder, geom: MotorGeometry) -> None:
    magnet_lc = _feature_lc_mm(builder.base_lc_mm, "magnet_corner")
    for magnet in geom.magnets:
        if magnet.corners_mm is not None:
            for x_mm, y_mm in magnet.corners_mm:
                builder.point(
                    math.hypot(x_mm, y_mm),
                    math.atan2(y_mm, x_mm),
                    magnet_lc,
                    "magnet_corner",
                )
            continue
        for radius in (magnet.inner_radius_mm, magnet.outer_radius_mm):
            for theta in (
                magnet.center_angle_rad - magnet.half_width_rad,
                magnet.center_angle_rad + magnet.half_width_rad,
            ):
                builder.point(radius, theta, magnet_lc, "magnet_corner")

    slot_lc = _feature_lc_mm(builder.base_lc_mm, "slot_mouth")
    tooth_corner_lc = _feature_lc_mm(builder.base_lc_mm, "slot_tooth_corner")
    for slot in geom.slots:
        for theta in slot.edge_angles_at_radius(slot.inner_radius_mm):
            builder.point(slot.inner_radius_mm, theta, slot_lc, "slot_mouth")
            builder.point(
                slot.inner_radius_mm,
                theta,
                tooth_corner_lc,
                "slot_tooth_corner",
            )
        for theta in slot.edge_angles_at_radius(slot.outer_radius_mm):
            builder.point(
                slot.outer_radius_mm,
                theta,
                tooth_corner_lc,
                "slot_tooth_corner",
            )

def _gmsh_corner_refinement_enabled(config: MotorConfig) -> bool:
    solve_params = getattr(config, "solve_params", None)
    if solve_params is None:
        return False
    return (
        str(getattr(solve_params, "mesher", "") or "").lower() == "gmsh"
        and bool(getattr(solve_params, "corner_refinement", False))
    )


def _load_gmsh_mesh_profile_config() -> tuple[dict[str, Any], str]:
    raw = _GMSH_MESH_PROFILE_CONFIG_PATH.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid Gmsh mesh profile JSON in {_GMSH_MESH_PROFILE_CONFIG_REPO_PATH}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise RuntimeError(
            f"Gmsh mesh profile config {_GMSH_MESH_PROFILE_CONFIG_REPO_PATH} must be a JSON object"
        )
    return document, hashlib.sha256(raw).hexdigest()


def _gmsh_refined_profile_name() -> str:
    document, _ = _load_gmsh_mesh_profile_config()
    name = document.get("active_experimental_profile")
    if not isinstance(name, str) or not name:
        raise RuntimeError(
            "Gmsh mesh profile config must define non-empty active_experimental_profile"
        )
    return name


def _gmsh_refined_mesh_profile() -> dict[str, Any]:
    document, _ = _load_gmsh_mesh_profile_config()
    profiles = document.get("profiles")
    if not isinstance(profiles, dict):
        raise RuntimeError("Gmsh mesh profile config must define a profiles object")
    profile_name = _gmsh_refined_profile_name()
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise RuntimeError(f"Gmsh mesh profile {profile_name!r} is missing or invalid")
    return profile


def _gmsh_profile_section(profile: dict[str, Any], section: str) -> dict[str, Any]:
    value = profile.get(section)
    if not isinstance(value, dict):
        raise RuntimeError(f"Gmsh mesh profile section {section!r} is missing or invalid")
    return value


def _gmsh_profile_number(profile: dict[str, Any], section: str, key: str) -> float:
    value = _gmsh_profile_section(profile, section).get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(
            f"Gmsh mesh profile value {section}.{key} must be numeric"
        )
    return float(value)


def _gmsh_profile_int(profile: dict[str, Any], section: str, key: str) -> int:
    value = _gmsh_profile_number(profile, section, key)
    rounded = int(value)
    if rounded != value:
        raise RuntimeError(
            f"Gmsh mesh profile value {section}.{key} must be an integer"
        )
    return rounded


def _gmsh_refinement_profile_metadata(config: MotorConfig) -> dict[str, Any]:
    if not _gmsh_corner_refinement_enabled(config):
        return {"gmsh_refinement_profile": "default"}
    document, digest = _load_gmsh_mesh_profile_config()
    profile = _gmsh_refined_mesh_profile()
    return {
        "gmsh_refinement_profile": _gmsh_refined_profile_name(),
        "gmsh_refinement_profile_version": str(profile.get("version") or "unversioned"),
        "gmsh_refinement_profile_schema_version": document.get("schema_version"),
        "gmsh_refinement_profile_config_path": _GMSH_MESH_PROFILE_CONFIG_REPO_PATH,
        "gmsh_refinement_profile_config_sha256": digest,
    }


def _gmsh_mesh_size_metadata(config: MotorConfig, base_lc_mm: float) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "gmsh_base_lc_mm": base_lc_mm,
        "gmsh_far_lc_mm": base_lc_mm,
    }
    if _gmsh_corner_refinement_enabled(config):
        profile = _gmsh_refined_mesh_profile()
        metadata["gmsh_far_lc_mm"] = _gmsh_refined_far_lc_mm(profile, base_lc_mm)
    return metadata


def _gmsh_refined_far_lc_mm(profile: dict[str, Any], base_lc_mm: float) -> float:
    """Slightly coarser target away from airgap/corner physics hotspots."""

    return base_lc_mm * _gmsh_profile_number(profile, "far_field", "max_lc_base_scale")


def _gmsh_refined_corner_threshold(
    profile: dict[str, Any],
    *,
    base_lc_mm: float,
    airgap_width_mm: float,
) -> tuple[float, float, float, int]:
    corner_size = max(
        _gmsh_profile_number(profile, "corner", "size_floor_mm"),
        min(
            _gmsh_profile_number(profile, "corner", "size_cap_mm"),
            base_lc_mm * _gmsh_profile_number(profile, "corner", "size_base_scale"),
            airgap_width_mm
            * _gmsh_profile_number(profile, "corner", "size_airgap_width_scale"),
        ),
    )
    dist_min = max(
        _gmsh_profile_number(profile, "corner", "core_radius_mm"),
        corner_size * _gmsh_profile_number(profile, "corner", "core_size_multiplier"),
        base_lc_mm * _gmsh_profile_number(profile, "corner", "core_base_scale"),
    )
    dist_max = max(
        _gmsh_profile_number(profile, "corner", "influence_radius_mm"),
        dist_min + base_lc_mm * _gmsh_profile_number(profile, "corner", "transition_base_scale"),
    )
    return (
        corner_size,
        dist_min,
        dist_max,
        _gmsh_profile_int(profile, "corner", "sampling"),
    )


def _gmsh_refined_shaft_threshold(
    profile: dict[str, Any],
    *,
    base_lc_mm: float,
    shaft_radius_mm: float,
) -> tuple[float, float, float, int]:
    shaft_size = max(
        _gmsh_profile_number(profile, "shaft_bore", "size_floor_mm"),
        min(
            _gmsh_profile_number(profile, "shaft_bore", "size_cap_mm"),
            base_lc_mm
            * _gmsh_profile_number(profile, "shaft_bore", "size_base_scale"),
            shaft_radius_mm
            * _gmsh_profile_number(profile, "shaft_bore", "size_radius_scale"),
        ),
    )
    shaft_dist_min = max(
        shaft_size
        * _gmsh_profile_number(
            profile,
            "shaft_bore",
            "dist_min_size_multiplier",
        ),
        shaft_radius_mm
        * _gmsh_profile_number(
            profile,
            "shaft_bore",
            "dist_min_radius_scale",
        ),
    )
    shaft_dist_max = max(
        shaft_size
        * _gmsh_profile_number(
            profile,
            "shaft_bore",
            "dist_max_size_multiplier",
        ),
        base_lc_mm
        * _gmsh_profile_number(profile, "shaft_bore", "dist_max_base_scale"),
        shaft_radius_mm
        * _gmsh_profile_number(
            profile,
            "shaft_bore",
            "dist_max_radius_scale",
        ),
    )
    return (
        shaft_size,
        shaft_dist_min,
        shaft_dist_max,
        _gmsh_profile_int(profile, "shaft_bore", "sampling"),
    )


def _apply_gmsh_refined_size_options(*, min_lc_mm: float, max_lc_mm: float) -> None:
    gmsh.option.setNumber("Mesh.MeshSizeMin", min_lc_mm)
    gmsh.option.setNumber("Mesh.MeshSizeMax", max_lc_mm)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)


def _apply_gmsh_physics_mesh_fields(
    builder: _GmshGeometryBuilder,
    geom: MotorGeometry,
    config: MotorConfig,
) -> None:
    fields: list[int] = []
    base_lc = builder.base_lc_mm
    refined_corner_profile = _gmsh_corner_refinement_enabled(config)
    refined_profile = _gmsh_refined_mesh_profile() if refined_corner_profile else None
    far_lc = (
        _gmsh_refined_far_lc_mm(refined_profile, base_lc)
        if refined_profile is not None
        else base_lc
    )
    magnet_outer_radius = max(
        (m.outer_radius_mm for m in geom.magnets),
        default=geom.rotor_OD_r,
    )
    # Only surface magnets extend the physical rotor/air-gap interface. IPM
    # magnets are embedded inside the rotor, so using their outermost corner
    # radius exaggerates the gap and can leave a one-element radial bridge in
    # narrow IPM air gaps.
    airgap_inner_radius = (
        magnet_outer_radius
        if str(config.topology).upper() == "SPM"
        else geom.rotor_OD_r
    )
    airgap_width = max(0.05, geom.stator_ID_r - airgap_inner_radius)

    airgap_curves = sorted(builder.curves_by_feature.get("airgap_band", set()))
    if airgap_curves:
        if refined_profile is not None:
            # The experimental corner profile now shifts density budget from
            # the smooth airgap band into local PM/slot corner patches.
            airgap_base_size = base_lc * _gmsh_profile_number(
                refined_profile,
                "airgap",
                "size_base_scale",
            )
            airgap_width_size = airgap_width * _gmsh_profile_number(
                refined_profile,
                "airgap",
                "size_width_scale",
            )
            airgap_size = max(
                _gmsh_profile_number(refined_profile, "airgap", "size_floor_mm"),
                min(airgap_base_size, airgap_width_size),
            )
            airgap_dist_max = max(
                base_lc
                * _gmsh_profile_number(refined_profile, "airgap", "dist_max_base_scale"),
                airgap_width
                * _gmsh_profile_number(refined_profile, "airgap", "dist_max_width_scale"),
            )
            fields.append(
                _add_threshold_field(
                    curves=airgap_curves,
                    size_min_mm=airgap_size,
                    size_max_mm=far_lc,
                    dist_min_mm=airgap_width
                    * _gmsh_profile_number(refined_profile, "airgap", "dist_min_width_scale"),
                    dist_max_mm=airgap_dist_max,
                    sampling=_gmsh_profile_int(refined_profile, "airgap", "sampling"),
                )
            )
        else:
            fields.append(
                _add_threshold_field(
                    curves=airgap_curves,
                    size_min_mm=min(
                        _feature_lc_mm(base_lc, "airgap"),
                        airgap_width * 0.65,
                        base_lc * 0.19,
                    ),
                    size_max_mm=base_lc,
                    dist_min_mm=airgap_width * 0.60,
                    dist_max_mm=max(base_lc * 1.6, airgap_width * 2.2),
                    sampling=140,
                )
            )

    magnet_points = sorted(builder.points_by_feature.get("magnet_corner", set()))
    if magnet_points:
        if refined_profile is not None:
            corner_size, corner_dist_min, corner_dist_max, corner_sampling = (
                _gmsh_refined_corner_threshold(
                    refined_profile,
                    base_lc_mm=base_lc,
                    airgap_width_mm=airgap_width,
                )
            )
            fields.append(
                _add_threshold_field(
                    points=magnet_points,
                    size_min_mm=corner_size,
                    size_max_mm=far_lc,
                    dist_min_mm=corner_dist_min,
                    dist_max_mm=corner_dist_max,
                    sampling=corner_sampling,
                )
            )
        else:
            fields.append(
                _add_threshold_field(
                    points=magnet_points,
                    size_min_mm=_feature_lc_mm(base_lc, "magnet_corner"),
                    size_max_mm=base_lc,
                    dist_min_mm=max(airgap_width * 0.35, base_lc * 0.20),
                    dist_max_mm=max(base_lc * 1.15, airgap_width * 1.6),
                    sampling=80,
                )
            )

    slot_points = sorted(
        builder.points_by_feature.get("slot_mouth", set())
        | builder.points_by_feature.get("slot_tooth_corner", set())
    )
    if slot_points:
        if refined_profile is not None:
            slot_size, corner_dist_min, corner_dist_max, corner_sampling = (
                _gmsh_refined_corner_threshold(
                    refined_profile,
                    base_lc_mm=base_lc,
                    airgap_width_mm=airgap_width,
                )
            )
            fields.append(
                _add_threshold_field(
                    points=slot_points,
                    size_min_mm=slot_size,
                    size_max_mm=far_lc,
                    dist_min_mm=corner_dist_min,
                    dist_max_mm=corner_dist_max,
                    sampling=corner_sampling,
                )
            )
        else:
            fields.append(
                _add_threshold_field(
                    points=slot_points,
                    size_min_mm=_feature_lc_mm(base_lc, "slot_mouth"),
                    size_max_mm=base_lc,
                    dist_min_mm=base_lc * 0.25,
                    dist_max_mm=base_lc * 1.10,
                    sampling=80,
                )
            )

    shaft_curves = sorted(builder.curves_by_feature.get("shaft_bore", set()))
    shaft_points = sorted(builder.points_by_feature.get("shaft_bore", set()))
    if refined_profile is not None and (shaft_curves or shaft_points):
        shaft_size, shaft_dist_min, shaft_dist_max, shaft_sampling = (
            _gmsh_refined_shaft_threshold(
                refined_profile,
                base_lc_mm=base_lc,
                shaft_radius_mm=max(0.05, geom.shaft_r),
            )
        )
        fields.append(
            _add_threshold_field(
                curves=shaft_curves or None,
                points=shaft_points or None,
                size_min_mm=shaft_size,
                size_max_mm=far_lc,
                dist_min_mm=shaft_dist_min,
                dist_max_mm=shaft_dist_max,
                sampling=shaft_sampling,
            )
        )

    if not fields:
        return
    if refined_profile is not None:
        mesh_min_base = base_lc * _gmsh_profile_number(
            refined_profile,
            "mesh_size_options",
            "min_lc_base_scale",
        )
        mesh_min_airgap = airgap_width * _gmsh_profile_number(
            refined_profile,
            "mesh_size_options",
            "min_lc_airgap_width_scale",
        )
        _apply_gmsh_refined_size_options(
            min_lc_mm=max(
                _gmsh_profile_number(
                    refined_profile,
                    "mesh_size_options",
                    "min_lc_floor_mm",
                ),
                min(mesh_min_base, mesh_min_airgap),
            ),
            max_lc_mm=far_lc,
        )
    min_field = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(min_field, "FieldsList", fields)
    gmsh.model.mesh.field.setAsBackgroundMesh(min_field)


def _add_threshold_field(
    *,
    points: list[int] | None = None,
    curves: list[int] | None = None,
    size_min_mm: float,
    size_max_mm: float,
    dist_min_mm: float,
    dist_max_mm: float,
    sampling: int,
) -> int:
    distance_field = gmsh.model.mesh.field.add("Distance")
    if points:
        gmsh.model.mesh.field.setNumbers(distance_field, "PointsList", points)
    if curves:
        gmsh.model.mesh.field.setNumbers(distance_field, "CurvesList", curves)
    gmsh.model.mesh.field.setNumber(distance_field, "Sampling", sampling)

    threshold_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(threshold_field, "InField", distance_field)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", size_min_mm)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", size_max_mm)
    gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", dist_min_mm)
    gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", dist_max_mm)
    return threshold_field


def _extract_gmsh_triangles() -> tuple[list[list[float]], list[list[int]]]:
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes: list[list[float]] = []
    tag_to_index: dict[int, int] = {}
    for idx, tag in enumerate(node_tags):
        coord_idx = idx * 3
        tag_to_index[int(tag)] = idx
        nodes.append([float(node_coords[coord_idx]), float(node_coords[coord_idx + 1])])

    triangles: list[list[int]] = []
    elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(2)
    for elem_type, connectivity in zip(elem_types, elem_node_tags):
        if int(elem_type) != 2:
            continue
        for idx in range(0, len(connectivity), 3):
            tri = [
                tag_to_index[int(connectivity[idx])],
                tag_to_index[int(connectivity[idx + 1])],
                tag_to_index[int(connectivity[idx + 2])],
            ]
            if _signed_area(nodes, tri) < 0.0:
                tri = [tri[0], tri[2], tri[1]]
            triangles.append(tri)
    return nodes, triangles


def _classify_triangles_by_centroid(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    geom: MotorGeometry,
) -> list[str]:
    rotor_outer_with_magnets = max((m.outer_radius_mm for m in geom.magnets), default=geom.rotor_OD_r)
    slot_outer_r = _slot_outer_radius_mm(geom)
    out: list[str] = []
    for i, j, k in triangles:
        cx = (nodes_mm[i][0] + nodes_mm[j][0] + nodes_mm[k][0]) / 3.0
        cy = (nodes_mm[i][1] + nodes_mm[j][1] + nodes_mm[k][1]) / 3.0
        radius = math.hypot(cx, cy)
        theta = math.atan2(cy, cx)
        if radius < geom.shaft_r:
            out.append("shaft")
        elif radius < geom.rotor_OD_r:
            out.append("rotor_core")
        elif radius <= rotor_outer_with_magnets:
            magnet_region = _magnet_preview_region(theta, radius, geom)
            out.append(magnet_region if magnet_region is not None else "inter_pole_gap")
        elif radius <= geom.stator_ID_r:
            out.append("airgap")
        elif radius <= slot_outer_r:
            out.append("slot_winding" if _is_inside_slot(theta, radius, geom) else "stator_tooth")
        else:
            out.append("stator_yoke")
    return out


def _magnet_preview_region(
    theta: float,
    radius: float,
    geom: MotorGeometry,
) -> str | None:
    for magnet in geom.magnets:
        if magnet.inner_radius_mm <= radius <= magnet.outer_radius_mm:
            if abs(_normalize_signed_angle(theta - magnet.center_angle_rad)) <= magnet.half_width_rad:
                return f"magnet_{magnet.polarity.lower()}"
    return None


def _is_inside_magnet(theta: float, radius: float, geom: MotorGeometry) -> bool:
    return _magnet_preview_region(theta, radius, geom) is not None


def _is_magnet_angle(theta: float, geom: MotorGeometry) -> bool:
    return any(
        abs(_normalize_signed_angle(theta - magnet.center_angle_rad)) <= magnet.half_width_rad
        for magnet in geom.magnets
    )


def _is_inside_slot(theta: float, radius: float, geom: MotorGeometry) -> bool:
    for slot in geom.slots:
        if slot.inner_radius_mm <= radius <= slot.outer_radius_mm:
            if abs(_normalize_signed_angle(theta - slot.center_angle_rad)) <= slot.half_width_at_radius(radius):
                return True
    return False


def _base_lc_mm(config: MotorConfig, density: str) -> float:
    density_scale = {
        "coarse": 1.8,
        # Calibrated with physics-aware local fields to track FEMM's Auto mesh
        # scale on Phase A SPM fixtures (~45-50k triangles / ~24-26k nodes).
        # Small 4p/12s motors otherwise over-refine because the airgap
        # threshold field scales from base_lc; keep normal/fine above a floor
        # so Gmsh benchmark meshes stay comparable to FEMM instead of 5x dense.
        "normal": 0.78,
        "fine": 0.75,
        "very_fine": 0.3,
    }.get(density, 1.0)
    floor_mm = 0.9 if density in {"normal", "fine"} else 0.15
    return max(floor_mm, config.stator.OD_mm * 0.015 * density_scale)


def _feature_lc_mm(base_lc_mm: float, feature: str) -> float:
    scale = {
        "airgap": 0.42,
        "magnet_corner": 0.34,
        "slot_mouth": 0.46,
        "slot_tooth_corner": 1.0,
        "shaft_bore": 0.42,
    }.get(feature, 1.0)
    return max(0.08, base_lc_mm * scale)


def _slot_outer_radius_mm(geom: MotorGeometry) -> float:
    if geom.slots:
        return max(slot.outer_radius_mm for slot in geom.slots)
    return geom.stator_ID_r


def _outer_boundary_nodes(nodes: list[list[float]], radius_mm: float) -> list[int]:
    tol = max(1.0e-3, radius_mm * 1.0e-6)
    return [idx for idx, (x, y) in enumerate(nodes) if math.hypot(x, y) >= radius_mm - tol]


def _signed_area(nodes: list[list[float]], tri: list[int]) -> float:
    i, j, k = tri
    x1, y1 = nodes[i]
    x2, y2 = nodes[j]
    x3, y3 = nodes[k]
    return 0.5 * ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))


def _uniform_angles(count: int) -> list[float]:
    return [2.0 * math.pi * idx / count for idx in range(count)]


def _merged_angles(angles: list[float]) -> list[float]:
    normalized = sorted({round(angle % (2.0 * math.pi), 12) for angle in angles})
    return [float(angle) for angle in normalized]


def _angle_pairs(angles: list[float]) -> list[tuple[float, float]]:
    merged = _merged_angles(angles)
    if not merged:
        merged = [0.0]
    out: list[tuple[float, float]] = []
    for idx, start in enumerate(merged):
        end = merged[(idx + 1) % len(merged)]
        if idx + 1 == len(merged):
            end += 2.0 * math.pi
        if end - start > 1.0e-9:
            out.append((start, end))
    return out


def _split_interval(theta_start: float, theta_end: float, max_span: float = math.pi / 2.5) -> list[tuple[float, float]]:
    theta_end = _advance_after(theta_start, theta_end)
    span = theta_end - theta_start
    steps = max(1, int(math.ceil(span / max_span)))
    step = span / steps
    return [(theta_start + idx * step, theta_start + (idx + 1) * step) for idx in range(steps)]


def _advance_after(theta_start: float, theta_end: float) -> float:
    while theta_end <= theta_start + 1.0e-12:
        theta_end += 2.0 * math.pi
    return theta_end


def _normalize_signed_angle(theta: float) -> float:
    while theta > math.pi:
        theta -= 2.0 * math.pi
    while theta <= -math.pi:
        theta += 2.0 * math.pi
    return theta
