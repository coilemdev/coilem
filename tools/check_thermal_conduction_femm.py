"""Compare the thermal network's cross-section reduction with FEMM's heat-flow solver.

The same isolated problem as ``tools.check_thermal_conduction_fe``: winding,
teeth and yoke only, the yoke's back face held at the boundary temperature,
every other edge insulated, the registered conductivities and heat cases. The
six registered cases and the bundled outer-rotor examples are drawn in FEMM
from the design's exact region outlines, solved on two meshes, and FEMM's own
block averages are set beside the network's prediction.

The registered cases also get a bundle each, in the form
``tools.check_thermal_conduction --bundle`` judges.

``--whole`` adds the whole cross-section: air gap, magnets and rotor are drawn
too, and the cooled surfaces carry convection instead of a fixed temperature.
The network runs with its out-of-plane paths closed (no end-winding heat, no
end-space air, no bearing path, no slot liner), so both codes solve the same
in-plane problem. See ``whole_section`` for how the surface coefficients and
the gap are made equivalent.

Run from a checkout, with FEMM 5 installed (set COILEM_FEMM5_APP if it is not
in ~/Applications):

    python -m tools.check_thermal_conduction_femm --whole --out benchmarks/thermal-v0.6/conduction-femm-results.json \
        --bundles benchmarks/thermal-v0.6/femm --work ~/coilem-femm5-runs/thermal-conduction
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import plistlib
import socket
from dataclasses import dataclass
from pathlib import Path

from backend.benchmark_suite.thermal_conduction import NODES, check_conduction, cross_section_prediction, registration, request_for_case
from backend.geometry_ir import build_geometry_ir
from backend.loss_breakdown import operating_point_losses
from backend.models import IronLoss
from backend.models.thermal import ThermalInputs
from backend.rotor_layout import is_outer_rotor
from backend.thermal_network import build_network, cylindrical_resistance, solve_network
from tools.check_thermal_conduction_fe import designs
from tools.femm_reference.ir_helpers import edge_midpoint, inside, polyline, xy

ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.environ.get("COILEM_FEMM5_APP", "~/Applications/femm_gui.app")).expanduser()
GROUPS = {"SlotWinding": "winding", "StatorTooth": "teeth", "StatorYoke": "yoke"}
NO_MESH = "<No Mesh>"
# The whole cross-section. The shaft carries no heat here: the network's bearing path is closed.
WHOLE_GROUPS = GROUPS | {"Airgap": "gap", "MagnetPocketAir": "pocket", "Magnet": "magnets", "RotorCore": "rotor", "Shaft": NO_MESH}
WHOLE_NODES = (*NODES, "magnets", "rotor")
# The whole-section heat case: the registered combined case plus rotor heat, scaled per design
# so the network's winding sits this far above the surroundings.
WHOLE_SPLIT = {"winding": 10.0, "teeth": 3.0, "yoke": 7.0, "magnets": 1.0, "rotor": 1.0}
WHOLE_WINDING_RISE_K = 80.0
WHOLE_AMBIENT_C = 25.0
CLOSED_K_W = 1e9
SOLVER = "FEMM 5.0 heat flow"
KELVIN = 273.15
ARC_DEG = 1.0
HEAT_FLOW = 2
SOURCES = ("tools/check_thermal_conduction_femm.py", "backend/benchmark_suite/thermal_conduction.py", "backend/thermal_network.py")
FE_RESULTS = "benchmarks/thermal-v0.6/conduction-fe-results.json"


@dataclass(frozen=True)
class HeatModel:
    """A stator cross-section as FEMM draws it: shared edges once, one label per region."""

    nodes: tuple[tuple[float, float], ...]
    lines: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
    arcs: tuple[tuple[tuple[float, float], tuple[float, float], float], ...]
    labels: tuple[tuple[str, str, tuple[float, float]], ...]
    # A point on every arc of each named cooled face.
    faces: dict[str, tuple[tuple[float, float], ...]]


def _key(point):
    return round(point[0], 6), round(point[1], 6)


def interior_point(region):
    """A point well inside the region: its centroid, else a step in from the middle of an edge."""

    loops = [polyline(loop) for loop in region.loops]

    def valid(point):
        return inside(point, loops[0]) and not any(inside(point, hole) for hole in loops[1:])

    outer = loops[0]
    pairs = list(zip(outer, outer[1:] + outer[:1]))
    crosses = [a[0] * b[1] - b[0] * a[1] for a, b in pairs]
    centre = (sum((a[0] + b[0]) * c for (a, b), c in zip(pairs, crosses)) / (3 * sum(crosses)),
              sum((a[1] + b[1]) * c for (a, b), c in zip(pairs, crosses)) / (3 * sum(crosses)))
    if valid(centre):
        return centre
    for distance in (1.0, 0.5, 0.2, 0.1, 0.05, 0.02):
        for loop in region.loops:
            for segment in loop.segments:
                a, b = xy(segment.start), xy(segment.end)
                middle = edge_midpoint(segment)
                if segment.kind == "arc":
                    c = xy(segment.center)
                    radius = math.hypot(middle[0] - c[0], middle[1] - c[1])
                    normal = ((middle[0] - c[0]) / radius, (middle[1] - c[1]) / radius)
                else:
                    length = math.hypot(b[0] - a[0], b[1] - a[1])
                    normal = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
                for sign in (1, -1):
                    point = (middle[0] + sign * distance * normal[0], middle[1] + sign * distance * normal[1])
                    # Both neighbours must be inside too, so the label keeps clear of the edges.
                    if all(valid((point[0] + dx * distance / 2, point[1] + dy * distance / 2))
                           for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))):
                        return point
    raise ValueError("No interior label for " + region.region_id)


def lower(regions, face_radius_mm: dict[str, float], groups=GROUPS) -> HeatModel:
    """Region outlines to nodes, lines and arcs, with the arcs of each named cooled face marked."""

    nodes, lines, arcs = {}, {}, {}
    faces: dict[str, list] = {name: [] for name in face_radius_mm}
    for region in regions:
        for loop in region.loops:
            for segment in loop.segments:
                a, b = xy(segment.start), xy(segment.end)
                nodes.setdefault(_key(a), a)
                nodes.setdefault(_key(b), b)
                if segment.kind != "arc":
                    lines.setdefault(frozenset((_key(a), _key(b))), (a, b))
                    continue
                # FEMM draws an arc anticlockwise from its first point.
                if segment.sweep_deg < 0:
                    a, b = b, a
                key = (_key(a), _key(b), round(abs(segment.sweep_deg), 6))
                if key in arcs:
                    continue
                arcs[key] = (a, b, abs(segment.sweep_deg))
                centre = xy(segment.center)
                for name, radius in face_radius_mm.items():
                    if math.hypot(*centre) < 1e-9 and math.isclose(math.hypot(*a), radius, abs_tol=1e-6):
                        faces[name].append(edge_midpoint(segment))
    missing = [name for name, points in faces.items() if not points]
    if missing:
        raise ValueError("Cooled face not found in the region outlines: " + ", ".join(missing))
    labels = tuple((region.region_id, groups[region.kind], interior_point(region)) for region in regions)
    return HeatModel(tuple(nodes.values()), tuple(lines.values()), tuple(arcs.values()), labels,
                     {name: tuple(points) for name, points in faces.items()})


def stator_regions(config):
    return [region for region in build_geometry_ir(config).regions if region.kind in GROUPS]


def mesh_size_mm(config, areas_m2) -> float:
    """Coarse element size: a quarter of the narrowest of tooth, slot and yoke."""

    depth = (config.stator.OD_mm - config.stator.ID_mm) / 2 - config.stator.yoke_thickness_mm
    slots = config.stator.slot_count
    tooth = areas_m2["teeth"] * 1e6 / slots / depth
    slot = areas_m2["winding"] * 1e6 / slots / depth
    return min(tooth, slot, config.stator.yoke_thickness_mm) / 4


def femm_build() -> dict:
    info = plistlib.loads((APP / "Contents" / "Info.plist").read_bytes())
    programs = APP / "Contents" / "MacOS"
    return {"version": info.get("CFBundleShortVersionString"),
            "sha256": {name: hashlib.sha256((programs / name).read_bytes()).hexdigest() for name in ("femm_headless", "hsolv")}}


def open_femm():
    """An owned headless FEMM on a free port. FEMM exits when the session closes."""

    binding = APP / "Contents" / "Resources" / "bindings" / "pyfemm" / "femm.py"
    if not binding.is_file():
        raise SystemExit(f"FEMM 5 not found at {APP}; set COILEM_FEMM5_APP to the femm_gui.app bundle")
    spec = importlib.util.spec_from_file_location("coilem_femm5_binding", binding)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ["FEMM_DIR"] = str(APP / "Contents" / "MacOS")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return module.FemmSession(port=port, headless=True)


def draw(femm, model: HeatModel, *, conductivity_W_mK, faces, depth_mm, size_mm):
    """Draw the model. ``faces`` gives each cooled face a fixed temperature or a coefficient to surroundings.

    ``size_mm`` is the element size, or a size per material.
    """

    femm.newdocument(HEAT_FLOW)
    femm.hi_probdef("millimeters", "planar", 1e-8, depth_mm, 30)
    for node, value in conductivity_W_mK.items():
        femm.hi_addmaterial(node, value, value, 0, 0)
    for name, face in faces.items():
        if "fixed_C" in face:
            # Format 0 is a fixed temperature, in kelvin.
            femm.hi_addboundprop(name, 0, face["fixed_C"] + KELVIN, 0, 0, 0, 0)
        else:
            # Format 2 is convection to surroundings at a given temperature.
            femm.hi_addboundprop(name, 2, 0, 0, face["surroundings_C"] + KELVIN, face["h_W_m2K"], 0)
    for point in model.nodes:
        femm.hi_addnode(*point)
    for a, b in model.lines:
        femm.hi_addsegment(*a, *b)
    for a, b, angle in model.arcs:
        femm.hi_addarc(*a, *b, angle, ARC_DEG)
    labels = [(node, point) for _, node, point in model.labels]
    if all(math.hypot(*point) > 1e-9 for _, point in labels):
        # The bore, or the hub hole of an outer-rotor stator, is closed by the outlines and is not part of the problem.
        labels.append((NO_MESH, (0.0, 0.0)))
    for node, point in labels:
        femm.hi_addblocklabel(*point)
        femm.hi_selectlabel(*point)
        femm.hi_setblockprop(node, 0, 0 if node == NO_MESH else size_mm[node] if isinstance(size_mm, dict) else size_mm, 0)
        femm.hi_clearselected()
    for name, points in model.faces.items():
        for point in points:
            femm.hi_selectarcsegment(*point)
        femm.hi_setarcsegmentprop(ARC_DEG, name, 0, 0, "<None>")
        femm.hi_clearselected()


def _real(value) -> float:
    """FEMM 5 answers a block integral as a real and imaginary pair; FEMM 4.2 as one number."""

    return float(value[0] if isinstance(value, (list, tuple)) else value)


def solve(femm, model: HeatModel, source_W_m3, path: Path, *, face_radius_mm=None) -> dict:
    """Set the heat sources on the drawn model, solve it and read FEMM's block averages.

    With ``face_radius_mm`` the mean temperature on each of those faces is read as well.
    """

    for node, value in source_W_m3.items():
        femm.hi_modifymaterial(node, 3, value)
    femm.hi_saveas(str(path))
    femm.hi_analyze(1)
    femm.hi_loadsolution()
    regions = []
    for region_id, node, point in model.labels:
        if node == NO_MESH:
            continue
        femm.ho_selectblock(*point)
        # Integral 0 is the block's mean temperature in kelvin, integral 1 its area in square metres.
        mean_K, area_m2 = _real(femm.ho_blockintegral(0)), _real(femm.ho_blockintegral(1))
        femm.ho_clearblock()
        regions.append({"region_id": region_id, "node": node, "area_m2": area_m2, "mean_temperature_C": mean_K - KELVIN})
    elements = int(femm.ho_numelements())
    face_C = {}
    for name, (radius, inward) in (face_radius_mm or {}).items():
        # Just inside the solid, all the way round. FEMM draws an arc as chords, so step in past their sag.
        r, count = radius + inward * (3 * radius * (1 - math.cos(math.radians(ARC_DEG / 2))) + 1e-4), 720
        values = [_real(femm.ho_getpointvalues(r * math.cos(2 * math.pi * i / count), r * math.sin(2 * math.pi * i / count)))
                  for i in range(count)]
        face_C[name] = sum(values) / count - KELVIN
    femm.ho_close()
    return {"regions": regions, "elements": elements, "face_C": face_C}


def _loop_radius(loop) -> float:
    radii = [math.hypot(*xy(segment.start)) for segment in loop.segments]
    if max(radii) - min(radii) > 1e-6:
        raise ValueError("The whole-section check needs a plain cylindrical air gap")
    return radii[0]


def whole_section(config, total_W: float):
    """The network with its out-of-plane paths closed, and the same problem for FEMM.

    The network takes the cooled surfaces and the air gap as plain resistances.
    FEMM gets exactly those: each cooled face carries the coefficient that gives
    the network's resistance over the face's own area, and the gap is a solid
    whose conductivity gives the network's two gap films across its real
    thickness. What FEMM then tests is the conduction inside the parts and how
    the heat divides between the exits.

    The network puts the rotor-side gap film on the whole rotor circumference.
    To match, the air pockets between magnets conduct like the magnets do.
    ``stagnant_pocket_W_mK`` in the result is the alternative: pockets of still
    air, which leaves only the magnet faces to pass heat.
    """

    outer = is_outer_rotor(config)
    share = {node: total_W * value / sum(WHOLE_SPLIT.values()) for node, value in WHOLE_SPLIT.items()}
    stator_iron = share["teeth"] + share["yoke"]
    rotor_heat = share["magnets"] + share["rotor"]
    iron = IronLoss(status="experimental", steel="M350-50A", electrical_frequency_Hz=100, iron_loss_W=stator_iron,
                    iron_hysteresis_loss_W=stator_iron / 2, iron_eddy_loss_W=stator_iron / 2,
                    iron_teeth_loss_W=share["teeth"], iron_yoke_loss_W=share["yoke"],
                    stator_iron_mass_kg=1, validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)
    winding, losses = operating_point_losses(config, 1.0, iron)
    losses = losses.model_copy(update={"copper_loss_W": share["winding"], "copper_active_loss_W": share["winding"],
                                       "copper_end_winding_loss_W": 0.0, "iron_loss_W": stator_iron, "mechanical_loss_W": 0.0})
    spec = registration()
    inputs = ThermalInputs.model_validate({
        "cooling": "still_air", "ambient_C": WHOLE_AMBIENT_C, "housing_h_W_m2K": 10, "airgap_h_W_m2K": 20,
        # Out of plane, so closed: FEMM's planar problem has no end space, bearings or slot liner.
        "end_space_h_W_m2K": 1e-4, "bearing_to_housing_K_W": CLOSED_K_W, "rotor_to_bearing_K_W": CLOSED_K_W, "slot_liner_mm": 1e-6,
        "coefficient_source": "Whole-section FEMM comparison: coilEM still-air starter values",
        "housing_thickness_mm": 3, "contact_m2K_W": 0.001, "mount_to_ambient_K_W": 10 if outer else None,
        "steel_k_W_mK": spec["conductivity_W_mK"]["teeth"], "slot_k_model": "user", "slot_k_W_mK": spec["conductivity_W_mK"]["winding"],
        "slot_k_source": "Registered conduction value",
        "extra_rotor_heat_W": rotor_heat, "extra_rotor_heat_to_magnets_fraction": share["magnets"] / rotor_heat,
        "insulation_class": "H", "hotspot_allowance_K": 0,
    })
    network = build_network(config, inputs, winding, losses, iron)
    temperatures, _, _ = solve_network(network)
    resistance = {(link.a, link.b): link.resistance_K_W for link in network.links}
    length = config.stator.stack_length_mm * 1e-3
    regions = [region for region in build_geometry_ir(config).regions if region.kind in WHOLE_GROUPS]
    areas = {}
    for region in regions:
        areas[WHOLE_GROUPS[region.kind]] = areas.get(WHOLE_GROUPS[region.kind], 0.0) + region.area_mm2 * 1e-6
    gap_radii = sorted(_loop_radius(loop) for region in regions if region.kind == "Airgap" for loop in region.loops)
    gap_resistance = resistance[("stator_bore", "airgap")] + resistance[("airgap", "rotor")]
    conductivity = {"winding": inputs.slot_k_W_mK, "teeth": inputs.steel_k_W_mK, "yoke": inputs.steel_k_W_mK,
                    "magnets": inputs.magnet_k_W_mK, "rotor": inputs.steel_k_W_mK,
                    "gap": math.log(gap_radii[-1] / gap_radii[0]) / (2 * math.pi * length * gap_resistance)}
    conductivity["pocket"] = inputs.magnet_k_W_mK

    def face(radius_mm, resistance_K_W, inward):
        area = 2 * math.pi * radius_mm * 1e-3 * length
        return {"radius_mm": radius_mm, "inward": inward, "resistance_K_W": resistance_K_W,
                "h_W_m2K": 1 / (resistance_K_W * area), "surroundings_C": WHOLE_AMBIENT_C}

    if outer:
        shell_inner, shell_outer = config.rotor.ID_mm * 0.0005, config.rotor.OD_mm * 0.0005
        # FEMM conducts through the shell itself, so its outer face carries the film only.
        film = resistance[("rotor", "ambient")] - cylindrical_resistance(shell_inner, shell_outer, length, inputs.steel_k_W_mK)
        faces = {"mount": face(config.stator.ID_mm / 2, resistance[("stator_back", "mount")] + resistance[("mount", "ambient")], 1),
                 "shell": face(config.rotor.OD_mm / 2, film, -1)}
        exits = {"mount": (temperatures["mount"] - WHOLE_AMBIENT_C) / resistance[("mount", "ambient")]}
        exits["shell"] = total_W - exits["mount"]
    else:
        faces = {"housing": face(config.stator.OD_mm / 2, resistance[("stator_outer", "housing")] + resistance[("housing", "ambient")], -1)}
        exits = {"housing": total_W}
    source = {node: share[node] / (areas[node] * length) for node in WHOLE_NODES} | {"gap": 0.0, "pocket": 0.0}
    gap_mm = (gap_radii[-1] - gap_radii[0])
    return dict(regions=regions, faces=faces, conductivity=conductivity, source=source, gap_mm=gap_mm, areas=areas,
                stagnant_pocket_W_mK=conductivity["gap"],
                network_C={node: temperatures[node] for node in WHOLE_NODES}, network_exit_W=exits, heat_W=share)


def compare_whole(femm, work: Path, only: str | None = None) -> list[dict]:
    rows, seen = [], set()
    for case_id, fixture, config, _ in designs():
        name = Path(fixture).stem.split("__")[0]
        if fixture in seen or (only is not None and only not in name and only not in case_id):
            continue
        seen.add(fixture)
        # The problem is linear: scale the heat so the network's winding sits the chosen rise above the surroundings.
        unit = whole_section(config, 1.0)
        problem = whole_section(config, WHOLE_WINDING_RISE_K / (unit["network_C"]["winding"] - WHOLE_AMBIENT_C))
        faces = problem["faces"]
        model = lower(problem["regions"], {key: value["radius_mm"] for key, value in faces.items()}, WHOLE_GROUPS)
        stator_areas = {node: problem["areas"][node] for node in NODES}
        coarse_mm = mesh_size_mm(config, stator_areas)
        solved = {}
        for level, scale in (("coarse", 1.0), ("fine", 0.5)):
            size = {node: coarse_mm * scale for node in problem["conductivity"]} | {"gap": min(coarse_mm, problem["gap_mm"] / 2) * scale}
            draw(femm, model, conductivity_W_mK=problem["conductivity"], faces=faces, depth_mm=config.stator.stack_length_mm, size_mm=size)
            face_radius = {key: (value["radius_mm"], value["inward"]) for key, value in faces.items()}
            solved[level] = solve(femm, model, problem["source"], work / f"whole-{name}-{level}.feh", face_radius_mm=face_radius)
            if level == "fine":
                for direction in (1, 2):
                    femm.hi_modifymaterial("pocket", direction, problem["stagnant_pocket_W_mK"])
                solved["stagnant"] = solve(femm, model, problem["source"], work / f"whole-{name}-stagnant-pockets.feh",
                                           face_radius_mm=face_radius)
            femm.hi_close()
        fine, coarse, stagnant = solved["fine"], solved["coarse"], solved["stagnant"]
        total = sum(problem["heat_W"].values())
        femm_exit = {key: (fine["face_C"][key] - WHOLE_AMBIENT_C) / value["resistance_K_W"] for key, value in faces.items()}
        row = dict(design=name, fixture=fixture, layout="outer" if is_outer_rotor(config) else "inner", surroundings_C=WHOLE_AMBIENT_C,
                   heat_W=problem["heat_W"], total_heat_W=total, gap_mm=problem["gap_mm"],
                   femm_conductivity_W_mK=problem["conductivity"],
                   femm_faces={key: {"radius_mm": value["radius_mm"], "h_W_m2K": value["h_W_m2K"]} for key, value in faces.items()},
                   elements_coarse=coarse["elements"], elements_fine=fine["elements"], nodes=[], exits=[],
                   femm_heat_balance_pct=100 * (sum(femm_exit.values()) - total) / total)
        for node in WHOLE_NODES:
            fine_C, fine_area = _mean(fine["regions"], node)
            coarse_C, _ = _mean(coarse["regions"], node)
            rise = fine_C - WHOLE_AMBIENT_C
            network = problem["network_C"][node]
            row["nodes"].append(dict(node=node, network_C=network, femm_C=fine_C, difference_K=network - fine_C,
                                     difference_pct=100 * (network - fine_C) / rise, mesh_difference_K=abs(fine_C - coarse_C),
                                     femm_stagnant_pockets_C=_mean(stagnant["regions"], node)[0],
                                     area_difference_pct=100 * (fine_area - problem["areas"][node]) / problem["areas"][node]))
        for key in faces:
            row["exits"].append(dict(exit=key, network_W=problem["network_exit_W"][key], femm_W=femm_exit[key],
                                     network_share_pct=100 * problem["network_exit_W"][key] / total, femm_share_pct=100 * femm_exit[key] / total,
                                     femm_face_C=fine["face_C"][key]))
        rows.append(row)
    return rows


def _mean(regions, node):
    selected = [row for row in regions if row["node"] == node]
    area = sum(row["area_m2"] for row in selected)
    return sum(row["area_m2"] * row["mean_temperature_C"] for row in selected) / area, area


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(work: Path, bundles: Path | None, only: str | None = None, whole: bool = False) -> dict:
    spec = registration()
    conductivity, boundary = spec["conductivity_W_mK"], spec["boundary_C"]
    registered = {case["id"]: case for case in spec["cases"]}
    fe_path = ROOT / FE_RESULTS
    fe = {(row["case"], row["node"]): row["reference_rise_K"] for row in json.loads(fe_path.read_text())["rows"]} if fe_path.is_file() else {}
    build = femm_build()
    work.mkdir(parents=True, exist_ok=True)
    by_fixture: dict[str, list] = {}
    for case_id, fixture, config, heat in designs():
        if only is None or only in case_id:
            by_fixture.setdefault(fixture, []).append((case_id, config, heat))
    rows, statuses = [], {}
    femm = open_femm()
    try:
        for fixture, cases in by_fixture.items():
            config = cases[0][1]
            outer = is_outer_rotor(config)
            regions = stator_regions(config)
            model = lower(regions, {"back": (config.stator.ID_mm if outer else config.stator.OD_mm) / 2})
            length = config.stator.stack_length_mm * 1e-3
            _, areas = cross_section_prediction(config, cases[0][2], conductivity, boundary)
            coarse_mm = mesh_size_mm(config, areas)
            solved: dict[tuple[str, str], dict] = {}
            for level, size in (("coarse", coarse_mm), ("fine", coarse_mm / 2)):
                draw(femm, model, conductivity_W_mK=conductivity, faces={"back": {"fixed_C": boundary}},
                     depth_mm=config.stator.stack_length_mm, size_mm=size)
                for case_id, _, heat in cases:
                    source = {node: heat[node] / (areas[node] * length) for node in NODES}
                    path = work / f"{case_id}-{level}.feh"
                    solved[(case_id, level)] = solve(femm, model, source, path) | {"input": path, "size_mm": size}
                femm.hi_close()
            for case_id, _, heat in cases:
                prediction, _ = cross_section_prediction(config, heat, conductivity, boundary)
                fine, coarse = solved[(case_id, "fine")], solved[(case_id, "coarse")]
                files = sorted(p for run in (coarse, fine) for p in (run["input"], run["input"].with_suffix(".anh")))
                raw = hashlib.sha256("".join(f"{p.name}:{_sha256(p)}\n" for p in files).encode()).hexdigest()
                if case_id in registered:
                    request = request_for_case(registered[case_id])
                    # The reference depends on the registration and the fixture only. The request hash also
                    # covers the network's source, so it dates the comparison, not the reference.
                    bundle = {"case_id": case_id, "request_sha256": request["request_sha256"],
                              "registration_sha256": request["registration_sha256"], "fixture_sha256": request["fixture_sha256"],
                              "solver": SOLVER,
                              "solver_build": f"{build['version']} macOS, femm_headless {build['sha256']['femm_headless'][:16]}",
                              "raw_artifact_sha256": raw, "boundary_C": boundary,
                              "mesh_size_mm": {"coarse": coarse["size_mm"], "fine": fine["size_mm"]},
                              "elements": {"coarse": coarse["elements"], "fine": fine["elements"]},
                              "regions": fine["regions"], "coarse_regions": coarse["regions"]}
                    judged = check_conduction(request, bundle)
                    statuses[case_id] = judged["status"]
                    if bundles is not None:
                        bundles.mkdir(parents=True, exist_ok=True)
                        (bundles / f"{case_id}.json").write_text(json.dumps(bundle, indent=1, allow_nan=False) + "\n", encoding="utf-8")
                for node in NODES:
                    fine_C, fine_area = _mean(fine["regions"], node)
                    coarse_C, _ = _mean(coarse["regions"], node)
                    rise = fine_C - boundary
                    difference = prediction[node] - fine_C
                    mesh_difference = abs(fine_C - coarse_C)
                    band = max(spec["relative_band"] * abs(rise), spec["absolute_floor_K"])
                    mesh_band = max(spec["mesh_relative_band"] * abs(rise), spec["mesh_floor_K"])
                    fe_rise = fe.get((case_id, node))
                    rows.append(dict(
                        case=case_id, fixture=fixture, layout="outer" if outer else "inner", node=node,
                        network_rise_K=prediction[node] - boundary, reference_rise_K=rise, difference_K=difference,
                        difference_pct=100 * difference / rise if abs(rise) > 1e-12 else None,
                        mesh_difference_K=mesh_difference, mesh_difference_pct=100 * mesh_difference / abs(rise) if abs(rise) > 1e-12 else None,
                        registered_band_K=band,
                        registered_band_status=("MESH" if mesh_difference > mesh_band else "PASS" if abs(difference) <= band
                                                else "YELLOW" if abs(difference) <= 2 * band else "FAIL"),
                        area_difference_pct=100 * (fine_area - areas[node]) / areas[node],
                        elements_coarse=coarse["elements"], elements_fine=fine["elements"], raw_artifact_sha256=raw,
                        own_fe_rise_K=fe_rise, own_fe_difference_pct=None if fe_rise is None or abs(rise) < 1e-12 else 100 * (fe_rise - rise) / rise))
        whole_rows = compare_whole(femm, work, only) if whole else []
    finally:
        femm.close()
    return dict(
        schema_version=1, kind="thermal_conduction_femm_comparison",
        reference=f"{SOLVER}, build {build['version']}, block averages from ho_blockintegral", femm_build=build,
        problem="Winding, teeth and yoke only; yoke back face fixed; other edges insulated; registered conductivities and heat cases",
        registration=spec["protocol"], boundary_C=boundary, conductivity_W_mK=conductivity,
        mesh="Coarse element size is a quarter of the narrowest of tooth, slot and yoke; fine is half of that",
        source_sha256={name: _sha256(ROOT / name) for name in SOURCES},
        fixture_sha256={fixture: _sha256(ROOT / fixture) for fixture in by_fixture},
        registered_status=statuses, rows=rows,
        whole_section=dict(
            problem="Whole cross-section with convection on the cooled faces; the network's end-winding, end-space, bearing and liner "
                    "paths are closed; surface coefficients and gap conductivity reproduce the network's resistances; the pockets "
                    "between magnets conduct like the magnets, with still-air pockets as a second FEMM solution",
            winding_rise_K=WHOLE_WINDING_RISE_K, heat_split=WHOLE_SPLIT, rows=whole_rows))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="write the comparison as JSON")
    parser.add_argument("--bundles", type=Path, help="folder for the registered cases' bundles")
    parser.add_argument("--work", type=Path, default=Path("~/coilem-femm5-runs/thermal-conduction"),
                        help="folder for FEMM's input and solution files")
    parser.add_argument("--only", help="run only the cases whose id contains this text")
    parser.add_argument("--whole", action="store_true", help="also compare the whole cross-section with convection")
    args = parser.parse_args()
    result = compare(args.work.expanduser(), args.bundles, args.only, args.whole)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{'case':36s} {'layout':6s} {'node':8s} {'network K':>10s} {'FEMM K':>9s} {'diff %':>7s} {'mesh %':>7s} {'own FE %':>9s} {'band':>6s}")
    for row in result["rows"]:
        own = "" if row["own_fe_difference_pct"] is None else f"{row['own_fe_difference_pct']:9.2f}"
        print(f"{row['case']:36s} {row['layout']:6s} {row['node']:8s} {row['network_rise_K']:10.3f} {row['reference_rise_K']:9.3f} "
              f"{row['difference_pct']:7.1f} {row['mesh_difference_pct']:7.2f} {own:>9s} {row['registered_band_status']:>6s}")
    for case_id, status in result["registered_status"].items():
        print(f"registered {case_id}: {status}")
    for row in result["whole_section"]["rows"]:
        print(f"whole section, {row['design']} ({row['layout']}), {row['total_heat_W']:.2f} W, "
              f"FEMM heat balance {row['femm_heat_balance_pct']:+.2f}%")
        for node in row["nodes"]:
            print(f"  {node['node']:8s} network {node['network_C']:7.2f} C  FEMM {node['femm_C']:7.2f} C  {node['difference_K']:+6.2f} K "
                  f"({node['difference_pct']:+5.1f}% of rise)  mesh {node['mesh_difference_K']:.3f} K  "
                  f"still-air pockets {node['femm_stagnant_pockets_C']:7.2f} C")
        for leaving in row["exits"]:
            print(f"  exit {leaving['exit']:8s} network {leaving['network_share_pct']:5.1f}%  FEMM {leaving['femm_share_pct']:5.1f}% of the heat")
    return int(any(row["registered_band_status"] in ("FAIL", "MESH") for row in result["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
