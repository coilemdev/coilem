"""Lower the published LRK 12-slot / 14-pole outer-rotor drawing to the shared geometry IR.

Source: the FEMM SlidingBandBenchmark ``WholeMotor.fem`` (lrk_12s14p_source.json,
hash-checked). Public identifiers and messages call it the LRK reference: the
public boundary keeps the private solver's name out of payloads and the UI.

The source is counterclockwise-positive with slot centres at 15+30k degrees and
the gap-facing north pole of the rotor centred on +x. The generic pipeline
expects slot k centred at 30k degrees, so the stator is turned +15 degrees and
the source's circuits B and C are relabelled C and B. The
signed source winding then equals the generic 12s/14p single-layer tooth-coil
map, so the ordinary winding, current and flux-linkage code applies unchanged.
The rotor keeps pole 0's north on the native rotor angle: source rotor position
theta corresponds to native angle theta + 15 degrees.

Two arcs are added to the drawing without changing any material: one at the
magnets' inner face, separating the stationary air gap from the rotating air
between and behind the magnets, and one at the slot bottoms, separating the
stator yoke from its teeth.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.geometry_ir import GeometryIR, GeometryIRLoop, GeometryIRPoint, GeometryIRRegion, GeometryIRSegment

REFERENCE = "lrk_12s14p"
SOURCE_SHA256 = "e69cce40a56f0c9840892a122cda86e5b3fa69d0b0c6ccc718d4d430b059253e"
ASSET_SHA256 = "474c5ce06d530a9c6281da165f83e28eeba40ba3458617001b18d11b5e17d608"
STATOR_ROTATION_DEG = 15.0
SOURCE_TO_GENERIC_PHASE = {"A": "A", "B": "C", "C": "B"}
MAGNET_GRADE = "LRK_NdFeB_40MGOe"

BORE_RADIUS_MM = 6.5
SLOT_BOTTOM_RADIUS_MM = 8.25
TOOTH_TIP_RADIUS_MM = 12.8
MAGNET_INNER_RADIUS_MM = 13.0
ROTOR_IRON_INNER_RADIUS_MM = 14.14
ROTOR_OUTER_RADIUS_MM = 15.39
SHOE_ROOT_RADIUS_MM = 11.871
SPLIT_RADII_MM = (SLOT_BOTTOM_RADIUS_MM, MAGNET_INNER_RADIUS_MM)

FIXED_CURRENT_CASE = "lrk-12s14p-fixed-current-v1"
# FEMM's benchmark drives A/B/C = 0/+4/-4 A; after the B/C relabel the
# generic phases carry 0/-4/+4 A at every rotor position.
CASES = {FIXED_CURRENT_CASE: {"phase_current_A": (0.0, -4.0, 4.0)}}


@lru_cache(maxsize=1)
def source():
    raw = Path(__file__).with_name("lrk_12s14p_source.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != ASSET_SHA256:
        raise ValueError("The LRK source asset changed; create and audit a new reference version")
    result = json.loads(raw)
    if result["sha256"] != SOURCE_SHA256:
        raise ValueError("LRK source identity mismatch")
    return result


def geometry_asset_sha256():
    return ASSET_SHA256


@lru_cache(maxsize=1)
def fixture():
    return json.loads(Path(__file__).with_name("lrk_12s14p_config.json").read_text(encoding="utf-8"))


def check_config(config):
    expected = fixture()
    if config.topology != "SPM" or config.rotor_layout != "outer":
        raise ValueError("The LRK reference is an outer-rotor SPM motor")
    for section in ("stator", "rotor", "winding", "materials"):
        actual = getattr(config, section).model_dump(mode="json")
        if any(actual.get(k) != v for k, v in expected[section].items()):
            raise ValueError(f"The LRK reference has a fixed {section}; load another design to edit its model")
    if config.solve_params is None:
        raise ValueError("The LRK reference requires explicit solve settings")
    if config.reference_case is not None and config.reference_case not in CASES:
        raise ValueError("Unknown LRK reference case")


@dataclass(frozen=True)
class _Curve:
    start: int
    end: int
    group: int
    boundary: int
    sweep_deg: float = 0.0
    center: tuple[float, float] | None = None


@lru_cache(maxsize=1)
def _primitives():
    data = source()
    nodes = np.asarray(data["points_raw"], dtype=float)[:, :2]
    curves = [_Curve(int(x[0]), int(x[1]), int(x[5]), int(x[3])) for x in data["segments_raw"]]
    for x in data["arc_segments_raw"]:
        i, j, sweep = int(x[0]), int(x[1]), float(x[2])
        curves.append(_Curve(i, j, int(x[6]), int(x[4]), sweep, _arc_center(nodes[i], nodes[j], sweep)))
    radii = np.linalg.norm(nodes, axis=1)
    angles = np.degrees(np.arctan2(nodes[:, 1], nodes[:, 0])) % 360
    for radius in SPLIT_RADII_MM:
        on_circle = sorted(np.flatnonzero(abs(radii - radius) < 1e-6), key=lambda index: angles[index])
        existing = {frozenset((c.start, c.end)) for c in curves if c.center is not None and abs(radii[c.start] - radius) < 1e-6}
        group = 2 if radius == MAGNET_INNER_RADIUS_MM else 0
        for i, j in zip(on_circle, [*on_circle[1:], on_circle[0]]):
            if frozenset((i, j)) not in existing:
                curves.append(_Curve(int(i), int(j), group, 0, float((angles[j] - angles[i]) % 360), (0.0, 0.0)))
    nodes.setflags(write=False)
    return nodes, tuple(curves)


def _arc_center(a, b, sweep_deg):
    angle = math.radians(sweep_deg)
    if not 0 < angle <= math.pi + 1e-12:
        raise ValueError("The LRK drawing expects arcs in (0, 180] degrees")
    delta = b - a
    center = (a + b) / 2 + np.array([-delta[1], delta[0]]) / (2 * math.tan(angle / 2))
    return tuple(map(float, center))


def _ends(edge):
    curve = _primitives()[1][abs(edge) - 1]
    return (curve.start, curve.end) if edge > 0 else (curve.end, curve.start)


def _tangent(edge):
    nodes, curves = _primitives()
    curve = curves[abs(edge) - 1]
    a, b = _ends(edge)
    if curve.center is None:
        delta = nodes[b] - nodes[a]
        return math.atan2(delta[1], delta[0])
    radial = nodes[a] - curve.center
    return math.atan2(radial[1], radial[0]) + math.copysign(math.pi / 2, edge)


def _loop_area(edges):
    nodes, curves = _primitives()
    total = 0.0
    for edge in edges:
        curve = curves[abs(edge) - 1]
        a, b = (nodes[i] for i in _ends(edge))
        if curve.center is None:
            total += a[0] * b[1] - b[0] * a[1]
        else:
            x, y = curve.center
            radius2 = float(np.sum((a - curve.center) ** 2))
            total += x * (b[1] - a[1]) - y * (b[0] - a[0]) + radius2 * math.radians(math.copysign(curve.sweep_deg, edge))
    return total / 2


def _loop_polygon(edges):
    nodes, curves = _primitives()
    points = []
    for edge in edges:
        curve = curves[abs(edge) - 1]
        a, _ = (nodes[i] for i in _ends(edge))
        if curve.center is None:
            points.append(a)
            continue
        delta = a - curve.center
        start = math.atan2(delta[1], delta[0])
        sweep = math.radians(math.copysign(curve.sweep_deg, edge))
        count = max(2, math.ceil(abs(curve.sweep_deg) / 0.5))
        theta = start + np.arange(count) * sweep / count
        points.extend(np.asarray(curve.center) + np.linalg.norm(delta) * np.column_stack((np.cos(theta), np.sin(theta))))
    return np.asarray(points)


def _contains(polygon, point):
    x, y = point
    x1, y1 = polygon[:, 0], polygon[:, 1]
    x2, y2 = np.roll(x1, 1), np.roll(y1, 1)
    crossing = (y1 > y) != (y2 > y)
    xs = x1[crossing] + (y - y1[crossing]) * (x2[crossing] - x1[crossing]) / (y2[crossing] - y1[crossing])
    return bool(np.count_nonzero(xs > x) % 2)


@dataclass
class _Face:
    outer: list[int]
    holes: list[list[int]]
    component: int
    role: str = ""
    label: dict | None = None


@lru_cache(maxsize=1)
def _faces():
    """Walk the planar drawing into faces, then name each one by its source label or radial span."""

    nodes, curves = _primitives()
    outgoing = defaultdict(list)
    parent = list(range(len(nodes)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for index, curve in enumerate(curves, 1):
        outgoing[curve.start].append(index)
        outgoing[curve.end].append(-index)
        parent[root(curve.start)] = root(curve.end)
    for edges in outgoing.values():
        # Cyclic order around the node: arc tangents can fall outside (-pi, pi].
        edges.sort(key=lambda edge: _tangent(edge) % (2 * math.pi))
    unseen = {edge for edges in outgoing.values() for edge in edges}
    loops = []
    while unseen:
        first = edge = min(unseen)
        loop = []
        while True:
            if edge not in unseen:
                raise ValueError("The LRK edge walk is non-manifold")
            unseen.remove(edge)
            loop.append(edge)
            fan = outgoing[_ends(edge)[1]]
            edge = fan[(fan.index(-edge) - 1) % len(fan)]
            if edge == first:
                break
        loops.append((loop, root(_ends(first)[0])))
    bounded = [_Face(loop, [], component) for loop, component in loops if _loop_area(loop) > 1e-9]
    polygons = [_loop_polygon(face.outer) for face in bounded]
    for loop, component in loops:
        if _loop_area(loop) >= -1e-9:
            continue
        # The outermost vertex: a vertex on a shared circle could read as inside the face it bounds.
        point = max((nodes[i] for edge in loop for i in _ends(edge)), key=lambda xy: float(np.hypot(*xy)))
        hosts = [i for i, face in enumerate(bounded) if face.component != component and _contains(polygons[i], point)]
        if hosts:
            bounded[min(hosts, key=lambda i: _loop_area(bounded[i].outer))].holes.append(loop)

    labels = source()["labels"]
    bore_marker = np.asarray(source()["holes_raw"][0][:2])
    radii = np.linalg.norm(nodes, axis=1)
    named = []
    for face, polygon in zip(bounded, polygons):
        def inside(point, face=face, polygon=polygon):
            return _contains(polygon, point) and not any(_contains(_loop_polygon(hole), point) for hole in face.holes)

        if inside(bore_marker):
            continue
        owned = [label for label in labels if label["material"] in ("AWG22", "NdFeB 40 MGOe", "1018 Steel")
                 and inside(np.asarray([label["x_mm"], label["y_mm"]]))]
        if len(owned) > 1:
            raise ValueError("An LRK face holds more than one winding, magnet or rotor label")
        span = radii[[i for loop in (face.outer, *face.holes) for edge in loop for i in _ends(edge)]]
        if owned:
            face.label = owned[0]
            face.role = {"AWG22": "winding", "NdFeB 40 MGOe": "magnet", "1018 Steel": "rotor_core"}[owned[0]["material"]]
        elif span.max() <= SLOT_BOTTOM_RADIUS_MM + 1e-6:
            face.role = "stator_yoke"
        elif span.max() <= TOOTH_TIP_RADIUS_MM + 1e-6 and span.min() >= SLOT_BOTTOM_RADIUS_MM - 1e-6:
            face.role = "stator_tooth"
        elif span.min() >= MAGNET_INNER_RADIUS_MM - 1e-6:
            face.role = "rotor_air"
        else:
            face.role = "airgap"
        named.append(face)
    counts = defaultdict(int)
    for face in named:
        counts[face.role] += 1
    if dict(counts) != {"stator_yoke": 1, "stator_tooth": 12, "winding": 12, "airgap": 1, "magnet": 14, "rotor_air": 1, "rotor_core": 1}:
        raise ValueError(f"Unexpected LRK region split: {dict(counts)}")
    covered = sum(_loop_area(face.outer) + sum(_loop_area(hole) for hole in face.holes) for face in named)
    expected = math.pi * (ROTOR_OUTER_RADIUS_MM**2 - BORE_RADIUS_MM**2)
    if not math.isclose(covered, expected, rel_tol=1e-10, abs_tol=1e-7):
        raise ValueError(f"LRK regions cover {covered} mm2, not the {expected} mm2 annulus")
    return tuple(named)


def _rotation(degrees):
    angle = math.radians(degrees)
    return np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])


def build(config, geom, rotor_angle_deg=None):
    """The exact drawing with the rotor at ``rotor_angle_deg`` (native, counterclockwise)."""

    rotor_angle_deg = float(rotor_angle_deg or 0.0)
    nodes, curves = _primitives()
    stator, rotor = _rotation(STATOR_ROTATION_DEG), _rotation(rotor_angle_deg)

    def place(xy, curve):
        return (rotor if curve.group == 2 else stator) @ np.asarray(xy)

    def ir_point(xy):
        return GeometryIRPoint(float(xy[0]), float(xy[1]))

    def segments(edge):
        curve = curves[abs(edge) - 1]
        a, b = (place(nodes[i], curve) for i in _ends(edge))
        tag = "dirichlet_az_zero" if curve.boundary == 1 else None
        if curve.center is None:
            return [GeometryIRSegment("line", ir_point(a), ir_point(b), boundary_tag=tag)]
        center = place(curve.center, curve)
        radius = float(np.linalg.norm(a - center))
        sweep = math.copysign(curve.sweep_deg, edge)
        # The mesher draws arcs below 180 degrees; both regions sharing an arc split it identically.
        pieces = max(1, math.ceil(abs(sweep) / 90.0 - 1e-9))
        start = math.atan2(a[1] - center[1], a[0] - center[0])
        result = []
        for k in range(pieces):
            t0 = start + math.radians(sweep) * k / pieces
            t1 = start + math.radians(sweep) * (k + 1) / pieces
            p0 = a if k == 0 else center + radius * np.array([math.cos(t0), math.sin(t0)])
            p1 = b if k == pieces - 1 else center + radius * np.array([math.cos(t1), math.sin(t1)])
            result.append(GeometryIRSegment("arc", ir_point(p0), ir_point(p1), center=ir_point(center),
                                            radius_mm=radius, sweep_deg=sweep / pieces, boundary_tag=tag))
        return result

    def ir_loop(name, edges):
        lines = tuple(segment for edge in edges for segment in segments(edge))
        return GeometryIRLoop(name, "polygon", lines, tuple(line.start for line in lines))

    def slot_index(face):
        angle = math.degrees(math.atan2(face.label["y_mm"], face.label["x_mm"])) + STATOR_ROTATION_DEG
        return round(angle / 30.0) % 12

    def angle_index(face, pitch_deg, offset_deg, turn_deg):
        polygon = _loop_polygon(face.outer)
        angle = math.degrees(math.atan2(polygon[:, 1].mean(), polygon[:, 0].mean())) + turn_deg
        return round((angle - offset_deg) / pitch_deg) % round(360 / pitch_deg)

    stator_material = f"steel:stator:{config.materials.stator_steel}"
    regions = []
    for face in sorted(_faces(), key=lambda f: (f.role, f.label["index"] if f.label else 0, min(f.outer))):
        loops = (ir_loop(f"{face.role}-0", face.outer), *(ir_loop(f"{face.role}-{i + 1}", hole) for i, hole in enumerate(face.holes)))
        area = abs(_loop_area(face.outer)) - sum(abs(_loop_area(hole)) for hole in face.holes)
        if face.role == "stator_yoke":
            regions.append(GeometryIRRegion("stator_yoke", "StatorYoke", stator_material, loops, area, "stationary"))
        elif face.role == "stator_tooth":
            # Tooth k sits between slots k and k+1.
            k = angle_index(face, 30.0, 15.0, STATOR_ROTATION_DEG)
            regions.append(GeometryIRRegion(f"stator_tooth_{k}", "StatorTooth", stator_material, loops, area, "stationary"))
        elif face.role == "winding":
            k = slot_index(face)
            phase = SOURCE_TO_GENERIC_PHASE[face.label["circuit"]]
            direction = "in" if face.label["signed_turns"] > 0 else "out"
            regions.append(GeometryIRRegion(f"slot_winding_{k}", "SlotWinding", "conductor:copper", loops, area, "stationary",
                                            source_group=f"winding:{phase}:{direction}:slot{k}"))
        elif face.role == "airgap":
            regions.append(GeometryIRRegion("airgap", "Airgap", "air", loops, area, "sliding_airgap"))
        elif face.role == "magnet":
            label = face.label
            magnet_index = angle_index(face, 360.0 / 14, 0.0, 0.0)
            theta = math.radians(label["magnetization_angle_deg_raw"] + rotor_angle_deg)
            north = math.cos(math.radians(label["magnetization_angle_deg_raw"] - label["theta_deg"])) < 0
            regions.append(GeometryIRRegion(f"magnet_{magnet_index}", "Magnet", f"magnet:{config.materials.magnet_grade}", loops,
                                            area, "rotor", source_group=f"pm:{'N' if north else 'S'}:magnet{magnet_index}",
                                            magnetization_xy=(math.cos(theta), math.sin(theta))))
        elif face.role == "rotor_air":
            regions.append(GeometryIRRegion("rotor_air", "MagnetPocketAir", "air", loops, area, "rotor"))
        else:
            regions.append(GeometryIRRegion("rotor_core", "RotorCore", f"steel:rotor:{config.materials.rotor_steel}", loops, area, "rotor"))
    return GeometryIR("geometry_ir/v0", "SPM", None, 14, 12, tuple(regions), {
        "geometry_reference": REFERENCE, "source_sha256": SOURCE_SHA256, "geometry_asset_sha256": ASSET_SHA256,
        "stator_od_mm": 2 * TOOTH_TIP_RADIUS_MM, "stator_id_mm": 2 * BORE_RADIUS_MM,
        "rotor_od_mm": 2 * ROTOR_OUTER_RADIUS_MM, "rotor_id_mm": 2 * (MAGNET_INNER_RADIUS_MM + 1.0),
        "airgap_mm": MAGNET_INNER_RADIUS_MM - TOOTH_TIP_RADIUS_MM, "stack_length_mm": config.stator.stack_length_mm,
        "winding_layers": 1, "winding_type": "concentrated",
        "radial_layout": "outer_rotor", "outer_radius_mm": ROTOR_OUTER_RADIUS_MM,
        "airgap_stator_side_radius_mm": TOOTH_TIP_RADIUS_MM, "airgap_rotor_side_radius_mm": MAGNET_INNER_RADIUS_MM,
        "tooth_sample_radius_mm": 0.5 * (SLOT_BOTTOM_RADIUS_MM + SHOE_ROOT_RADIUS_MM),
        "yoke_sample_radius_mm": 0.5 * (BORE_RADIUS_MM + SLOT_BOTTOM_RADIUS_MM),
        "coordinate_policy": "Source stator turned +15 degrees with circuits B/C relabelled; rotor angle native CCW",
    }, rotor_layout="outer")


def fixed_phase_currents_a(config):
    """The registered case's A/B/C currents, or None for the ordinary excitation."""

    case = CASES.get(getattr(config, "reference_case", None))
    return tuple(case["phase_current_A"]) if case else None


def equivalent_phase_current_peak_a(currents):
    """Peak of the balanced three-phase set an instant of which is these currents.

    0/-4/+4 A is the instant of a 4.62 A peak set where phase A crosses zero; the
    set's sum of squares, 1.5 * peak**2, is held at every instant.
    """

    return math.sqrt(sum(i * i for i in currents) / 1.5)


def exact_currents(artifact, config, rotor_angle_deg):
    """Hold the registered case's fixed phase currents on each meshed winding region."""

    case = CASES.get(config.reference_case)
    if case is None:
        return artifact
    currents = dict(zip("ABC", case["phase_current_A"]))
    nodes = np.asarray(artifact["mesh"]["nodes"], float)
    tri = np.asarray(artifact["mesh"]["triangles"], int)
    a, b = nodes[tri[:, 1]] - nodes[tri[:, 0]], nodes[tri[:, 2]] - nodes[tri[:, 0]]
    areas = abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * .5e-6
    ids = np.asarray(artifact["element_region_ids"])
    assignments = {}
    for region in artifact["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            assignments[region["id"]] = 0.0
            continue
        w = region["winding"]
        slot_area = areas[ids == region["id"]].sum()
        if not np.isfinite(slot_area) or slot_area <= 0:
            raise ValueError(f"Reference winding {region['id']} has no finite meshed area")
        density = (1 if w["direction"] == "in" else -1) * config.winding.turns_per_coil * currents[w["phase"]] / slot_area
        assignments[region["id"]] = float(density)
        region["current_density_a_per_m2"] = float(density)
        w["current_density_a_per_m2"] = float(density)
    artifact["element_current_density_a_per_m2"] = [assignments[x] for x in ids]
    artifact["physics_contract"]["provenance"]["phase_current_A"] = [currents[p] for p in "ABC"]
    artifact["physics_contract"]["provenance"]["current_density_source"] = "registered_fixed_phase_currents_and_actual_meshed_slot_areas"
    return artifact


def postprocess_report(report, config, artifact):
    """Report the fixed currents the benchmark case applied, not the unused generic excitation."""

    case = CASES.get(config.reference_case)
    if case is None:
        return
    report.setdefault("results", {})["phase_current_a"] = list(case["phase_current_A"])
    # Kt, the cogging comparison and the run metadata read the resolved peak; the
    # native report resolved it from the solve settings this case does not apply.
    report["operating_point"] = {**report.get("operating_point", {}), "case_id": config.reference_case,
                                 "phase_current_A": list(case["phase_current_A"]),
                                 "resolved_phase_current_peak_a": equivalent_phase_current_peak_a(case["phase_current_A"]),
                                 "resolution_rule": "Registered fixed phase currents on each actual meshed winding region"}


def report_settings(config, solve_params):
    from backend.public_report import _plain

    return [
        ("Case ID", _plain(config.get("reference_case")) if config.get("reference_case") else "Operating point from Solve"),
        ("Geometry reference", REFERENCE),
        ("Rotor layout", "Outer rotor (outrunner)"),
    ]


def model():
    from backend.models.config import WireSpec
    from backend.reference_models import ReferenceModel

    return ReferenceModel(
        reference_id=REFERENCE,
        label="LRK",
        build_ir=build,
        check_config=check_config,
        geometry_asset_sha256=geometry_asset_sha256,
        qualification_reason=("LRK 12s/14p software reference: pinned published geometry and materials; "
                              "hardware identity and release qualification remain separate."),
        magnet_temperatures_C=(20,),
        exact_currents=exact_currents,
        fixed_phase_currents_a=fixed_phase_currents_a,
        postprocess_report=postprocess_report,
        # The source's AWG22 magnet wire: 0.644 mm bare, one strand.
        wire=WireSpec(wire_bare_diameter_mm=0.644, strands_in_hand=1),
        report_settings=report_settings,
    )


def custom_steels():
    """The source B-H points as content-addressed custom steels, lamination fill folded into B."""

    from backend.custom_materials import CustomSteel, curve_digest

    mu0 = 4e-7 * math.pi
    result = {}
    for raw in source()["materials"]:
        points = raw.get("bh_points_T_A_per_m")
        if not points:
            continue
        fill = float(raw["LamFill"])
        curve = [(fill * b + (1 - fill) * mu0 * h, float(h)) for b, h in points]
        provisional = CustomSteel.model_construct(
            id="", name=f"LRK {raw['BlockName']}", lamination_thickness_mm=float(raw["d_lam"]) or None,
            source=f"Published LRK sliding-band benchmark model (WholeMotor.fem); lamination fill {fill:g} folded into B",
            bh_curve=curve, curve_sha256=curve_digest(curve))
        steel = CustomSteel.model_validate({**provisional.model_dump(), "id": provisional.content_id()})
        result[raw["BlockName"]] = steel
    return result


def case_config(case_id=None):
    config = copy.deepcopy(fixture())
    config["reference_case"] = case_id
    return config
