"""Trace the pinned source curves into exact, shared, closed physical regions."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from backend.experimental.femm_outrunner import FIXTURE_ID, FixtureMesh, source
from backend.geometry_ir import GeometryIR, GeometryIRLoop, GeometryIRPoint, GeometryIRRegion, GeometryIRSegment


@dataclass(frozen=True)
class Curve:
    start: int
    end: int
    group: int
    boundary: int
    sweep_deg: float = 0
    center: tuple[float, float] | None = None
    max_segment_deg: float = 0


@dataclass
class Face:
    outer: list[int]
    holes: list[list[int]]
    component: int
    label_id: int | None = None


def _arc_center(a: np.ndarray, b: np.ndarray, sweep_deg: float) -> tuple[float, float]:
    angle = math.radians(sweep_deg)
    if not (0 < angle <= math.pi + 1e-12):
        raise ValueError("Pinned fixture expects arcs in (0,180] degrees")
    delta = b-a
    center = (a+b)/2 + np.array([-delta[1], delta[0]])/(2*math.tan(angle/2))
    return tuple(map(float, center))


@lru_cache(maxsize=1)
def primitives() -> tuple[np.ndarray, tuple[Curve, ...]]:
    data = source()
    nodes = np.asarray(data["points_raw"], dtype=float)[:, :2]
    curves = [Curve(int(x[0]), int(x[1]), int(x[5]), int(x[3])) for x in data["segments_raw"]]
    for x in data["arc_segments_raw"]:
        i, j = int(x[0]), int(x[1])
        curves.append(Curve(i, j, int(x[6]), int(x[4]), x[2], _arc_center(nodes[i], nodes[j], x[2]), x[3]))
    nodes.setflags(write=False)
    return nodes, tuple(curves)


def _ends(edge: int) -> tuple[int, int]:
    curve = primitives()[1][abs(edge)-1]
    return (curve.start, curve.end) if edge > 0 else (curve.end, curve.start)


def _tangent(edge: int) -> float:
    nodes, curves = primitives()
    curve = curves[abs(edge)-1]
    a, b = _ends(edge)
    if curve.center is None:
        delta = nodes[b]-nodes[a]
        return math.atan2(delta[1], delta[0])
    radial = nodes[a]-curve.center
    return math.atan2(radial[1], radial[0]) + math.copysign(math.pi/2, edge)


def loop_area(edges: list[int]) -> float:
    nodes, curves = primitives()
    result = 0.0
    for edge in edges:
        curve = curves[abs(edge)-1]
        a, b = (nodes[i] for i in _ends(edge))
        if curve.center is None:
            result += a[0]*b[1]-b[0]*a[1]
        else:
            x, y = curve.center
            radius2 = float(np.sum((a-curve.center)**2))
            result += x*(b[1]-a[1])-y*(b[0]-a[0]) + radius2*math.radians(math.copysign(curve.sweep_deg, edge))
    return result/2


def loop_polygon(edges: list[int]) -> np.ndarray:
    nodes, curves = primitives()
    result = []
    for edge in edges:
        curve = curves[abs(edge)-1]
        a, _ = (nodes[i] for i in _ends(edge))
        if curve.center is None:
            result.append(a)
        else:
            delta = a-curve.center
            angle = math.atan2(delta[1], delta[0])
            sweep = math.radians(math.copysign(curve.sweep_deg, edge))
            count = max(2, math.ceil(abs(curve.sweep_deg)/0.5))
            theta = angle + np.arange(count)*sweep/count
            result.extend(np.asarray(curve.center) + np.linalg.norm(delta)*np.column_stack((np.cos(theta), np.sin(theta))))
    return np.asarray(result)


def contains(poly: np.ndarray, point: np.ndarray) -> bool:
    x, y = point
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, 1), np.roll(y1, 1)
    selected = (y1 > y) != (y2 > y)
    crossings = x1[selected] + (y-y1[selected])*(x2[selected]-x1[selected])/(y2[selected]-y1[selected])
    return bool(np.count_nonzero(crossings > x) % 2)


@lru_cache(maxsize=1)
def faces() -> tuple[Face, ...]:
    nodes, curves = primitives()
    outgoing: dict[int, list[int]] = defaultdict(list)
    parent = list(range(len(nodes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, curve in enumerate(curves, 1):
        outgoing[curve.start].append(i)
        outgoing[curve.end].append(-i)
        parent[root(curve.start)] = root(curve.end)
    for edges in outgoing.values():
        edges.sort(key=_tangent)
    unseen = {edge for edges in outgoing.values() for edge in edges}
    loops = []
    while unseen:
        first = min(unseen)
        edge = first
        loop = []
        while True:
            if edge not in unseen:
                raise ValueError("Source edge walk is non-manifold")
            unseen.remove(edge)
            loop.append(edge)
            _, end = _ends(edge)
            fan = outgoing[end]
            edge = fan[(fan.index(-edge)-1) % len(fan)]
            if edge == first:
                break
        loops.append((loop, root(_ends(first)[0])))
    bounded = [Face(loop, [], component) for loop, component in loops if loop_area(loop) > 1e-9]
    outside = [(loop, component) for loop, component in loops if loop_area(loop) < -1e-9]
    polygons = [loop_polygon(face.outer) for face in bounded]
    for loop, component in outside:
        point = nodes[_ends(loop[0])[0]]
        hosts = [i for i, face in enumerate(bounded) if face.component != component and contains(polygons[i], point)]
        if hosts:
            host = min(hosts, key=lambda i: loop_area(bounded[i].outer))
            bounded[host].holes.append(loop)
    labels = source()["labels"]
    holes = [np.asarray(x[:2]) for x in source()["holes_raw"]]
    result = []
    for i, face in enumerate(bounded):
        def inside(point: np.ndarray) -> bool:
            return contains(polygons[i], point) and not any(contains(loop_polygon(loop), point) for loop in face.holes)
        assigned = [label["index"] for label in labels if inside(np.asarray([label["x_mm"], label["y_mm"]]))]
        excluded = [h for h in holes if inside(h)]
        if excluded:
            if assigned or len(excluded) != 1:
                raise ValueError("Hole and physical labels overlap")
            continue
        if len(assigned) != 1:
            raise ValueError(f"Source face must have one block label, found {assigned}")
        face.label_id = assigned[0]
        result.append(face)
    if sorted(face.label_id for face in result) != list(range(29)):
        raise ValueError("Not all 29 source block labels resolve to a unique region")
    area = sum(loop_area(f.outer)+sum(loop_area(h) for h in f.holes) for f in result)
    expected = math.pi*(15.39**2-6.5**2)
    if not math.isclose(area, expected, rel_tol=1e-10, abs_tol=1e-7):
        raise ValueError(f"Source region coverage differs from annular domain: {area} vs {expected}")
    return tuple(sorted(result, key=lambda face: face.label_id))


def build_ir(rotor_angle_ccw_deg: float = 0) -> GeometryIR:
    nodes, curves = primitives()
    angle = math.radians(rotor_angle_ccw_deg)
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])

    def point(value: Any, rotating: bool) -> GeometryIRPoint:
        xy = rotation @ np.asarray(value) if rotating else value
        return GeometryIRPoint(float(xy[0]), float(xy[1]))

    def make_loop(name: str, edges: list[int]) -> GeometryIRLoop:
        segments = []
        for edge in edges:
            curve = curves[abs(edge)-1]
            a, b = (nodes[i] for i in _ends(edge))
            rotating = curve.group == 2
            segments.append(GeometryIRSegment(
                "arc" if curve.center else "line", point(a, rotating), point(b, rotating),
                center=point(curve.center, rotating) if curve.center else None,
                radius_mm=float(np.linalg.norm(a-curve.center)) if curve.center else None,
                sweep_deg=math.copysign(curve.sweep_deg, edge) if curve.center else None,
                boundary_tag="dirichlet_az_zero" if curve.boundary == 1 else None))
        return GeometryIRLoop(name, "polygon", tuple(segments), tuple(x.start for x in segments))

    kinds = {"1018 Steel": "RotorCore", "M-19 Steel": "StatorYoke", "NdFeB 40 MGOe": "Magnet", "AWG22": "SlotWinding", "Air": "Airgap"}
    regions = []
    for face in faces():
        label = source()["labels"][face.label_id]
        name = f"source_block_{face.label_id}"
        loops = tuple(make_loop(f"{name}_{i}", edges) for i, edges in enumerate([face.outer, *face.holes]))
        theta = math.radians(label["magnetization_angle_deg_raw"]+rotor_angle_ccw_deg)
        winding = f"winding:{label['circuit']}:{int(label['signed_turns'])}" if label["circuit"] else None
        regions.append(GeometryIRRegion(name, kinds[label["material"]], f"fixture_material:{label['material_index_1based']-1}", loops,
                                       loop_area(face.outer)+sum(loop_area(h) for h in face.holes),
                                       "rotor" if label["group"] == 2 else ("none" if label["material"] == "Air" else "stationary"),
                                       source_group=winding,
                                       magnetization_xy=(math.cos(theta), math.sin(theta)) if label["material"] == "NdFeB 40 MGOe" else None))
    return GeometryIR("geometry_ir/v0", "SPM", None, 14, 12, tuple(regions),
                      {"fixture_id": FIXTURE_ID, "radial_layout": "outer_rotor", "airgap_inner_radius_mm": 12.8,
                       "airgap_outer_radius_mm": 13., "stack_length_mm": 10., "coordinate_convention": "source-native-CCW"})


def generate_native_mesh(rotor_angle_ccw_deg: float = 0, gap_size_mm: float = 0.05, bulk_size_mm: float = 0.25) -> FixtureMesh:
    """Mesh the same IR used for the preview, retaining exact physical surfaces."""
    import gmsh

    from backend.gmsh_solver import _GMSH_API_LOCK, initialize_gmsh

    if not math.isfinite(rotor_angle_ccw_deg):
        raise ValueError("Rotor angle must be finite")
    if not 0.005 <= gap_size_mm <= 0.1 or not gap_size_mm <= bulk_size_mm <= 0.5:
        raise ValueError("Experimental mesh sizes are outside the reviewed range")
    ir = build_ir(rotor_angle_ccw_deg)
    with _GMSH_API_LOCK:
        initialize_gmsh()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)
            gmsh.option.setNumber("Mesh.MeshSizeMax", bulk_size_mm)
            gmsh.model.add(FIXTURE_ID)
            point_tags = {}
            curve_tags = {}
            fixed_curves = set()

            def xy(point: GeometryIRPoint) -> tuple[float, float]:
                return (round(point.x_mm, 11), round(point.y_mm, 11))

            def geo_point(point: GeometryIRPoint) -> int:
                key = xy(point)
                if key not in point_tags:
                    point_tags[key] = gmsh.model.geo.addPoint(point.x_mm, point.y_mm, 0, bulk_size_mm)
                return point_tags[key]

            def lower_curve(segment: GeometryIRSegment) -> list[int]:
                a, b = xy(segment.start), xy(segment.end)
                middle = None
                if segment.kind == "arc":
                    center = segment.center
                    assert center is not None and segment.radius_mm is not None and segment.sweep_deg is not None
                    theta = math.atan2(segment.start.y_mm-center.y_mm, segment.start.x_mm-center.x_mm)
                    midtheta = theta + math.radians(segment.sweep_deg)/2
                    middle = GeometryIRPoint(center.x_mm+segment.radius_mm*math.cos(midtheta), center.y_mm+segment.radius_mm*math.sin(midtheta))
                key = (segment.kind, tuple(sorted((a, b))), xy(middle) if middle else None)
                if key in curve_tags:
                    start, tags = curve_tags[key]
                    result = tags if start == a else [-tag for tag in reversed(tags)]
                else:
                    start, end = geo_point(segment.start), geo_point(segment.end)
                    if segment.kind == "line":
                        result = [gmsh.model.geo.addLine(start, end)]
                    else:
                        center_tag = geo_point(center)
                        if abs(segment.sweep_deg) >= 179.999:
                            mid = geo_point(middle)
                            pairs = [(start, mid), (mid, end)]
                        else:
                            pairs = [(start, end)]
                        result = [gmsh.model.geo.addCircleArc(u, center_tag, v) if segment.sweep_deg > 0
                                  else -gmsh.model.geo.addCircleArc(v, center_tag, u) for u, v in pairs]
                        radius = segment.radius_mm
                        max_angle = 0.1 if abs(radius-12.8) < 1e-7 else (1.0 if abs(radius-13) < 1e-7 or abs(radius-14) < 1e-7 else 2.5)
                        critical_interface = any(abs(radius-r) < 1e-7 for r in (12.8, 13.0, 14.0, 14.14))
                        tangential_size = gap_size_mm if critical_interface else bulk_size_mm
                        divisions = max(math.ceil(abs(segment.sweep_deg)/len(pairs)/max_angle),
                                        math.ceil(radius*math.radians(abs(segment.sweep_deg))/len(pairs)/tangential_size))
                        for tag in result:
                            gmsh.model.geo.mesh.setTransfiniteCurve(abs(tag), divisions+1)
                    curve_tags[key] = (a, result)
                if segment.boundary_tag == "dirichlet_az_zero":
                    fixed_curves.update(map(abs, result))
                return result

            surface_labels = {}
            for region in ir.regions:
                loops = [gmsh.model.geo.addCurveLoop([tag for segment in loop.segments for tag in lower_curve(segment)]) for loop in region.loops]
                surface = gmsh.model.geo.addPlaneSurface(loops)
                label_id = int(region.region_id.removeprefix("source_block_"))
                surface_labels[surface] = label_id
            gmsh.model.geo.synchronize()
            for surface, label in surface_labels.items():
                gmsh.model.addPhysicalGroup(2, [surface], name=f"source_block_{label}")
            profile = gmsh.model.mesh.field.add("MathEval")
            radius = "Sqrt(x*x+y*y)"
            distance = f"Min(Max(0,Abs({radius}-12.9)-0.1),Max(0,Abs({radius}-14.07)-0.07))"
            gmsh.model.mesh.field.setString(profile, "F", f"Min({bulk_size_mm},{gap_size_mm}+0.3*{distance})")
            gmsh.model.mesh.field.setAsBackgroundMesh(profile)
            gmsh.model.mesh.generate(2)
            tags, coordinates, _ = gmsh.model.mesh.getNodes()
            coordinates = np.asarray(coordinates).reshape(-1, 3)[:, :2]
            index = {int(tag): i for i, tag in enumerate(tags)}
            triangles, labels = [], []
            for surface, label in surface_labels.items():
                types, _, connections = gmsh.model.mesh.getElements(2, surface)
                for kind, connection in zip(types, connections):
                    if int(kind) != 2:
                        raise ValueError("Expected only P1 triangular elements")
                    rows = np.asarray(connection).reshape(-1, 3)
                    triangles.extend([[index[int(node)] for node in row] for row in rows])
                    labels.extend([label]*len(rows))
            fixed = set()
            for curve in fixed_curves:
                node_tags, _, _ = gmsh.model.mesh.getNodes(1, curve, includeBoundary=True)
                fixed.update(index[int(tag)] for tag in node_tags)
            triangles = np.asarray(triangles, dtype=np.int64)
            used = np.unique(triangles)
            compact = {int(old): new for new, old in enumerate(used)}
            mesh = FixtureMesh(coordinates[used], np.asarray([[compact[int(i)] for i in row] for row in triangles]), np.asarray(labels),
                               np.asarray(sorted(compact[i] for i in fixed if i in compact)), provenance={
                                   "mesh_source": "native_Gmsh_geometry_IR", "gap_size_target_mm": gap_size_mm,
                                   "bulk_size_target_mm": bulk_size_mm, "rotor_angle_ccw_deg": rotor_angle_ccw_deg,
                                   "fixture_id": FIXTURE_ID, "mesh_policy_version": "outrunner_source_gap_interfaces/v2"})
            mesh.validate()
            return mesh
        finally:
            gmsh.finalize()
