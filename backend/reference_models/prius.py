"""Lower the exact published Pyleecan Prius curves to the shared geometry IR."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from backend.geometry_ir import GeometryIR, GeometryIRLoop, GeometryIRPoint, GeometryIRRegion, GeometryIRSegment

REFERENCE = "pyleecan_prius_2004"
INITIAL_ROTOR_DEG = 52.49991619047166
MAGNET_TEMPERATURE_C = 60.0
MAGNET_BR_FACTOR = 0.96
CASES = {
    "prius-2004-tutorial-bemf-v1": {"speed_rpm": 1000, "magnet_temperature_C": 20, "current_peak_A": 0, "Phi0_deg": 140},
    "prius-2004-loaded-torque-v1": {"speed_rpm": 2000, "magnet_temperature_C": 60, "current_peak_A": 250, "Phi0_deg": 140},
}


def magnet_br_factor(config):
    return 1 - 0.001 * (config.solve_params.magnet_temperature_C - 20)


def report_reference_sources(report, config, artifact):
    """Describe the explicit meshed currents rather than the CLI's unused sine formula."""
    if artifact is None:
        raise ValueError("The published reference requires its explicit native Gmsh source artifact")
    provenance = artifact["physics_contract"]["provenance"]
    currents = provenance["phase_current_A"]
    original = report.get("operating_point", {})
    report["native_input_operating_point"] = original
    report["operating_point"] = {
        **original,
        "current_angle_reference": "Pyleecan d-axis Phi0, degrees electrical",
        "resolution_rule": "Explicit signed phase currents divided by each actual meshed slot area; generic CLI sine formula is unused",
        "sweep_current_rule": "I_peak*cos(theta_clockwise_electrical + Phi0 + [0,-120,120] degrees)",
        "phase_current_A": currents,
        "case_id": config.reference_case,
        "magnet_temperature_C": config.solve_params.magnet_temperature_C,
        "geometry_asset_sha256": geometry_asset_sha256(),
    }


def extract_winding_report(report, config, artifact):
    """Integrate nodal Az using the reference's actual region/phase/turn labels.

    Generic polar slot bins do not retain the imported winding after reflection.
    This uses the same signed winding functional as the explicit current source,
    preserving sum(lambda_phase * I_phase) = L * integral(Az * Jz dA).
    """
    import numpy as np

    nodes = np.asarray(artifact["mesh"]["nodes"], dtype=float)
    tri = np.asarray(artifact["mesh"]["triangles"], dtype=int)
    az = np.asarray(report["field_plot"]["az_nodal"], dtype=float)
    if az.shape != (len(nodes),) or not np.isfinite(az).all():
        raise ValueError("Reference linkage extraction requires finite nodal Az for the actual mesh")
    a, b = nodes[tri[:, 1]] - nodes[tri[:, 0]], nodes[tri[:, 2]] - nodes[tri[:, 0]]
    areas = abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * .5e-6
    element_az = az[tri].mean(axis=1)
    centroids = nodes[tri].mean(axis=1)
    ids = np.asarray(artifact["element_region_ids"])
    densities = np.asarray(artifact["element_current_density_a_per_m2"], dtype=float)
    flux = np.zeros(3)
    flux_rows, current_rows = [], []
    for region in artifact["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            continue
        w = region["winding"]
        selected = ids == region["id"]
        area_m2 = float(areas[selected].sum())
        if not np.isfinite(area_m2) or area_m2 <= 0:
            raise ValueError(f"Reference winding {region['id']} has no finite meshed area")
        average = float(np.dot(element_az[selected], areas[selected]) / area_m2)
        sign = 1 if w["direction"] == "in" else -1
        turns = config.winding.turns_per_coil
        contribution = sign * turns * config.stator.stack_length_mm * .001 * average
        flux["ABC".index(w["phase"])] += contribution
        center = np.average(centroids[selected], weights=areas[selected], axis=0)
        common = {"slot_index_modeled": w["slot_index"], "slot_index_global": w["slot_index"],
                  "phase": w["phase"], "direction": w["direction"], "turns_per_coil": turns,
                  "center_angle_mech_deg": math.degrees(math.atan2(center[1], center[0])) % 360,
                  "slot_area_m2": area_m2}
        flux_rows.append({**common, "az_reference_wb_per_m": 0., "az_avg_wb_per_m": average,
                          "az_effective_wb_per_m": average, "contribution_wb": contribution})
        ampere_turns = float(np.dot(densities[selected], areas[selected]))
        current_rows.append({**common, "effective_current_density_a_per_m2": ampere_turns / area_m2,
                             "integrated_amp_turns_a": ampere_turns, "slot_current_a": ampere_turns / turns,
                             "phase_current_a": ampere_turns / (sign * turns)})
    if len(flux_rows) != 48:
        raise ValueError("Reference linkage extraction requires all 48 published winding regions")
    results = report["results"]
    report["native_generic_winding_extraction"] = {
        key: results.get(key) for key in ("flux_linkage_a_wb", "flux_linkage_b_wb", "flux_linkage_c_wb",
                                         "slot_flux_linkage_contributions", "slot_excitation_contributions",
                                         "phase_current_a")
    }
    results.update({f"flux_linkage_{phase}_wb": float(value) for phase, value in zip("abc", flux)})
    results["slot_flux_linkage_contributions"] = flux_rows
    results["slot_excitation_contributions"] = current_rows
    # The phase currents this position actually carries: the published ones the
    # explicit source applied. The solver's own triple follows its generic
    # excitation, which the reference's imported densities replace, so the d/q
    # record and Torque–λdq agreement would otherwise see no current.
    results["phase_current_a"] = [float(value) for value in artifact["physics_contract"]["provenance"]["phase_current_A"]]
    report["reference_winding_extraction"] = {
        "version": "published-region-winding/v1", "geometry_asset_sha256": geometry_asset_sha256(),
        "flux_rule": "signed turns * physical stack length * area-weighted nodal Az in each exact winding region",
        "phase_flux_linkage_Wb": flux.tolist(),
        "sum_phase_flux_current_J": float(np.dot(flux, artifact["physics_contract"]["provenance"]["phase_current_A"])),
        "integral_Az_Jz_L_J": float(np.dot(element_az * densities, areas) * config.stator.stack_length_mm * .001),
    }


def case_config(case_id):
    """A fresh, versioned reference preset; callers may vary operating/accuracy controls."""
    config = copy.deepcopy(fixture())
    case = CASES[case_id]
    config["reference_case"] = case_id
    sp = config["solve_params"]
    sp.update(rated_speed_rpm=case["speed_rpm"], magnet_temperature_C=case["magnet_temperature_C"],
              current_amplitude_A=case["current_peak_A"], current_angle_deg=case["Phi0_deg"], mesh_build="precise")
    if case_id == "prius-2004-tutorial-bemf-v1":
        sp["rotor_step_deg"] = 3.6
    return config


@lru_cache(maxsize=1)
def geometry_asset_sha256():
    return hashlib.sha256(Path(__file__).with_name("pyleecan_prius_2004.json").read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def fixture():
    return json.loads(Path(__file__).with_name("pyleecan_prius_2004_config.json").read_text(encoding="utf-8"))


def check_config(config):
    expected = fixture()
    if config.topology != "IPM":
        raise ValueError("Published Pyleecan reference requires its IPM topology")
    for section in ("stator", "rotor", "winding", "materials"):
        actual = getattr(config, section).model_dump(mode="json")
        if any(actual.get(k) != v for k, v in expected[section].items()):
            raise ValueError(f"Published Pyleecan reference has fixed {section}; load another design to edit its model")
    if config.solve_params is not None:
        sp = config.solve_params
        case = CASES.get(config.reference_case)
        if case is None or sp.magnet_temperature_C != case["magnet_temperature_C"] or sp.excitation_mode != "sinusoidal":
            raise ValueError("Published Pyleecan reference requires a registered case with its fixed magnet temperature and sinusoidal excitation")
    else:
        raise ValueError("Published Pyleecan reference requires explicit solve settings")


def key(point):
    return tuple(round(v, 8) for v in point)


def reverse(segment):
    return {**segment, "start": segment["end"], "end": segment["start"],
            **({"sweep_deg": -segment["sweep_deg"]} if segment["kind"] == "arc" else {})}


def area(segments):
    total = 0.0
    for segment in segments:
        a, b = segment["start"], segment["end"]
        if segment["kind"] == "line":
            total += a[0] * b[1] - b[0] * a[1]
        else:
            x, y = segment["center"]
            total += x * (b[1] - a[1]) - y * (b[0] - a[0]) + segment["radius_mm"] ** 2 * math.radians(segment["sweep_deg"])
    return total / 2


def union_boundaries(loops):
    """Cancel exact shared edges and trace the remaining manifold boundaries."""
    edges = {}
    counts = defaultdict(int)
    for loop in loops:
        for segment in loop:
            token = (tuple(sorted((key(segment["start"]), key(segment["end"])))),
                     key(segment.get("center", [0, 0])) if segment["kind"] == "arc" else None)
            counts[token] += 1
            edges[token] = segment
    if any(n > 2 for n in counts.values()):
        raise ValueError("Published surfaces have non-manifold shared edges")
    remaining = {token: edges[token] for token, count in counts.items() if count == 1}
    adjacency = defaultdict(list)
    for token, segment in remaining.items():
        for point in (segment["start"], segment["end"]):
            adjacency[key(point)].append(token)
    if any(len(v) != 2 for v in adjacency.values()):
        raise ValueError("Published surface union is not closed")
    result = []
    while remaining:
        token = next(iter(remaining))
        segment = remaining.pop(token)
        loop = [segment]
        first, last = key(segment["start"]), key(segment["end"])
        while last != first:
            token = next(t for t in adjacency[last] if t in remaining)
            segment = remaining.pop(token)
            if key(segment["start"]) != last:
                segment = reverse(segment)
            loop.append(segment)
            last = key(segment["end"])
        result.append(loop)
    return result


def ir_loop(name, segments):
    if area(segments) < 0:
        segments = [reverse(segment) for segment in reversed(segments)]
    lines = tuple(GeometryIRSegment(
        kind=s["kind"], start=GeometryIRPoint(*s["start"]), end=GeometryIRPoint(*s["end"]),
        center=GeometryIRPoint(*s["center"]) if "center" in s else None,
        radius_mm=s.get("radius_mm"), sweep_deg=s.get("sweep_deg"),
    ) for s in segments)
    return GeometryIRLoop(name, "polygon", lines, tuple(line.start for line in lines))


@lru_cache(maxsize=1)
def source():
    return json.loads(Path(__file__).with_name("pyleecan_prius_2004.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def winding_area_mm2():
    return abs(area(next(s for s in source()["surfaces"] if "winding" in s)["loops"][0]))


def exact_currents(artifact, config, rotor_angle_deg):
    """Conserve actual ampere-turns on each meshed reference winding region."""
    import numpy as np

    from backend.excitation import phase_current_sample_dict, resolve_phase_current_sample

    currents = phase_current_sample_dict(resolve_phase_current_sample(config, rotor_angle_deg * 4))
    nodes = np.asarray(artifact["mesh"]["nodes"], float)
    tri = np.asarray(artifact["mesh"]["triangles"], int)
    a, b = nodes[tri[:, 1]] - nodes[tri[:, 0]], nodes[tri[:, 2]] - nodes[tri[:, 0]]
    areas = abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * .5e-6
    ids = np.asarray(artifact["element_region_ids"])
    assignments = {}
    for region in artifact["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            assignments[region["id"]] = 0.
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
    artifact["physics_contract"]["provenance"]["current_density_source"] = "published_phase_currents_and_actual_meshed_slot_areas"
    return artifact


def build(config, geom):
    from backend.geometry_drawer import compute_geometry

    baseline = compute_geometry(config)
    angle = geom.magnets[0].magnetization_angle_deg - baseline.magnets[0].magnetization_angle_deg
    # Public coordinates are clockwise-positive. Reflect the published drawing
    # across X, including the axial-vector magnetic transformation M'=-R M.
    # J_z is unchanged. This is an exact isometry, not a geometric approximation.
    theta = math.radians(INITIAL_ROTOR_DEG - angle)

    def rotate(point):
        x, y = point
        return [x * math.cos(theta) - y * math.sin(theta), x * math.sin(theta) + y * math.cos(theta)]

    surfaces = copy.deepcopy(source()["surfaces"])
    for surface in surfaces:
        for loop in surface["loops"]:
            for segment in loop:
                for point in ("start", "end", "center"):
                    if point in segment:
                        x, y = rotate(segment[point]) if surface["side"] == "rotor" else segment[point]
                        segment[point] = [x, -y]
                if "sweep_deg" in segment:
                    segment["sweep_deg"] *= -1
        if "magnetization_angle_deg" in surface:
            surface["magnetization_angle_deg"] = 180 - surface["magnetization_angle_deg"] - math.degrees(theta)
    stator = next(s for s in surfaces if s["label"] == "Stator-0_Lamination")
    rotor = next(s for s in surfaces if s["label"] == "Rotor-0_Lamination")
    windings = [s for s in surfaces if "winding" in s]
    holes = [s for s in surfaces if "Hole" in s["label"]]
    air_boundary = union_boundaries([stator["loops"][1], *[s["loops"][0] for s in windings]])
    hole_boundaries = union_boundaries([s["loops"][0] for s in holes])
    if len(air_boundary) != 1 or len(hole_boundaries) != 8:
        raise ValueError("Unexpected published Prius slot/pocket topology")
    regions = []

    def add(name, kind, material, loops, motion="stationary", source_group=None, magnetization=None):
        loops_ir = tuple(ir_loop(f"{name}-{i}", loop) for i, loop in enumerate(loops))
        magnitude = abs(area(loops[0])) - sum(abs(area(loop)) for loop in loops[1:])
        regions.append(GeometryIRRegion(name, kind, material, loops_ir, magnitude, motion,
                                        source_group=source_group, magnetization_xy=magnetization))

    add("stator_yoke", "StatorYoke", f"steel:stator:{config.materials.stator_steel}", stator["loops"])
    add("airgap", "Airgap", "air", [air_boundary[0], rotor["loops"][0]])
    add("rotor_core", "RotorCore", f"steel:rotor:{config.materials.rotor_steel}",
        [*rotor["loops"], *hole_boundaries], motion="rotor")
    for surface in windings:
        w = surface["winding"]
        add(f"slot_winding_{w['slot']}", "SlotWinding", "conductor:copper", surface["loops"],
            source_group=f"winding:{w['phase']}:{w['direction']}:slot{w['slot']}")
    air_index = 0
    mag_index = 0
    for surface in holes:
        if "magnetization_angle_deg" in surface:
            radians = math.radians(surface["magnetization_angle_deg"])
            add(f"magnet_{mag_index}", "Magnet", f"magnet:{config.materials.magnet_grade}", surface["loops"],
                motion="rotor", magnetization=(math.cos(radians), math.sin(radians)))
            mag_index += 1
        else:
            add(f"pocket_air_{air_index}", "MagnetPocketAir", "air", surface["loops"], motion="rotor")
            air_index += 1
    return GeometryIR("geometry_ir/v0", "IPM", "pyleecan_holem50", 8, 48, tuple(regions), {
        "geometry_reference": REFERENCE, "source_machine_sha256": source()["source_machine_sha256"],
        "geometry_asset_sha256": geometry_asset_sha256(),
        "stator_od_mm": 269.24, "stator_id_mm": 161.9, "rotor_od_mm": 160.4,
        "rotor_id_mm": 110.64, "airgap_mm": .75, "stack_length_mm": config.stator.stack_length_mm,
        "pocket_clearance_mm": 0., "winding_layers": 1, "winding_type": "distributed",
        "coordinate_policy": "Exact clockwise-frame reflection; axial magnetization M'=-R M, Jz unchanged",
    })
