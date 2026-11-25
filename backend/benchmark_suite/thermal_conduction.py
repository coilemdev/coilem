"""Pre-registered cross-section conduction checks; no convection qualification."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict

from backend.geometry_ir import build_geometry_ir
from backend.models import MotorConfig
from backend.models.thermal import ThermalLink, ThermalNetwork, ThermalSlab
from backend.resources import data_file, package_resource
from backend.rotor_layout import is_outer_rotor
from backend.thermal_network import slab_mean_resistance, solve_network

REGISTRATION = "benchmarks/thermal-v0.6/conduction-gates.json"
NODES = ("winding", "teeth", "yoke")
MODELS = ("legacy_mean_paths_v1", "surface_mean_v2")
# FEMM 5 solves the same heat-flow problem with its own mesher and is the build that runs on macOS and Linux.
SOLVERS = ("FEMM 4.2 heat flow", "FEMM 5.0 heat flow")


def registration():
    return json.loads(data_file(REGISTRATION).read_text())


def request_for_case(case, *, candidate_model="surface_mean_v2"):
    if candidate_model not in MODELS:
        raise ValueError("Unknown conduction candidate model")
    spec = registration()
    raw = data_file(case["fixture"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != case["fixture_sha256"]:
        raise ValueError("Conduction fixture differs from its frozen registration")
    parsed = json.loads(raw)
    config = MotorConfig.model_validate(parsed.get("config", parsed))
    regions = [r for r in build_geometry_ir(config).regions if r.kind in ("SlotWinding", "StatorTooth", "StatorYoke")]
    groups = {"SlotWinding": "winding", "StatorTooth": "teeth", "StatorYoke": "yoke"}
    areas = {node: sum(r.area_mm2 for r in regions if groups[r.kind] == node) * 1e-6 for node in NODES}
    if min(areas.values()) <= 0:
        raise ValueError("Conduction registration needs separate winding, tooth and yoke regions")
    length = config.stator.stack_length_mm * 1e-3
    outer = config.stator.OD_mm * 0.0005
    yoke = config.stator.yoke_thickness_mm * 1e-3
    depth = outer - config.stator.ID_mm * 0.0005 - yoke
    width = areas["winding"] / config.stator.slot_count / depth
    conductivity = spec["conductivity_W_mK"]
    resistance = [slab_mean_resistance(width, conductivity["winding"], depth * config.stator.slot_count * length, two_sided=True),
                  slab_mean_resistance(depth, conductivity["teeth"], areas["teeth"] / depth * length, two_sided=False),
                  slab_mean_resistance(yoke, conductivity["yoke"], 2 * math.pi * outer * length, two_sided=False)]
    network = ThermalNetwork(nodes=[*NODES, "boundary"], fixed_C={"boundary": spec["boundary_C"]}, heat_W=case["heat_W"],
        links=[ThermalLink(a=a, b=b, resistance_K_W=r, assumption="M1 uniform-source mean-path reduction; isolated cross-section")
               for (a, b), r in zip(zip(NODES, (*NODES[1:], "boundary")), resistance)])
    if candidate_model == "surface_mean_v2":
        # Winding heat enters the tooth mean as a distributed side source. Bore
        # is insulated, tooth/yoke share a real surface, yoke outer face is fixed.
        network = ThermalNetwork(nodes=[*NODES, "boundary", "stator_bore", "tooth_yoke_interface"],
            fixed_C={"boundary": spec["boundary_C"]}, heat_W=case["heat_W"], links=[network.links[0]],
            slabs=[ThermalSlab(mean="teeth", a="stator_bore", b="tooth_yoke_interface", resistance_K_W=3 * resistance[1],
                               assumption="Planar tooth mean and two surfaces; winding heat distributed at tooth mean"),
                   ThermalSlab(mean="yoke", a="tooth_yoke_interface", b="boundary", resistance_K_W=3 * resistance[2],
                               assumption="Planar yoke mean and two surfaces; fixed outer surface")])
    temperature, rejection, balance = solve_network(network)
    if candidate_model == "legacy_mean_paths_v1":
        # Preserve the original exported request byte identity, including its
        # summation order and pre-slab network schema, for existing owner runs.
        rejection = sum((temperature[link.a] - temperature[link.b]) / link.resistance_K_W
                        for link in network.links if link.b in network.fixed_C)
        balance = rejection - sum(network.heat_W.values())
    request = dict(schema_version=1, kind="thermal_conduction_request", case_id=case["id"],
        registration_sha256=hashlib.sha256(data_file(REGISTRATION).read_bytes()).hexdigest(), fixture_sha256=case["fixture_sha256"],
        boundary_C=spec["boundary_C"], outer_radius_mm=config.stator.OD_mm / 2, stack_length_mm=config.stator.stack_length_mm,
        conductivity_W_mK=conductivity, heat_W=case["heat_W"], areas_m2=areas,
        regions=[dict(**asdict(r), thermal_node=groups[r.kind], conductivity_W_mK=conductivity[groups[r.kind]],
                      source_W_m3=case["heat_W"][groups[r.kind]] / (areas[groups[r.kind]] * length)) for r in regions],
        network=network.model_dump(mode="json", exclude={"slabs"} if candidate_model == "legacy_mean_paths_v1" else set()),
        prediction_C={node: temperature[node] for node in NODES},
        rejected_heat_W=rejection, energy_balance_error_W=balance)
    if candidate_model == "surface_mean_v2":
        request["candidate_model"] = candidate_model
        request["source_sha256"] = {name: hashlib.sha256(package_resource(*name.split("/")).read_bytes()).hexdigest()
                                    for name in ("thermal_network.py", "models/thermal.py", "benchmark_suite/thermal_conduction.py")}
    request["request_sha256"] = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return request


def cross_section_prediction(config, heat_W, conductivity_W_mK, boundary_C):
    """The network's reduction of the isolated stator cross-section, for either rotor layout.

    Winding heat reaches the tooth mean through the slot's mean path; the tooth
    and the yoke are slabs with two faces; the yoke's back face is held at the
    boundary temperature. That face is the stator's outside for an inner rotor
    and its hub side for an outer rotor, as in ``build_network``. Returns the
    node temperatures and the group areas.
    """

    regions = [r for r in build_geometry_ir(config).regions if r.kind in ("SlotWinding", "StatorTooth", "StatorYoke")]
    groups = {"SlotWinding": "winding", "StatorTooth": "teeth", "StatorYoke": "yoke"}
    areas = {node: sum(r.area_mm2 for r in regions if groups[r.kind] == node) * 1e-6 for node in NODES}
    if min(areas.values()) <= 0:
        raise ValueError("Conduction check needs separate winding, tooth and yoke regions")
    length = config.stator.stack_length_mm * 1e-3
    outer, inner = config.stator.OD_mm * 0.0005, config.stator.ID_mm * 0.0005
    yoke = config.stator.yoke_thickness_mm * 1e-3
    depth = outer - inner - yoke
    width = areas["winding"] / config.stator.slot_count / depth
    back = inner if is_outer_rotor(config) else outer
    network = ThermalNetwork(nodes=[*NODES, "boundary", "stator_bore", "tooth_yoke_interface"],
        fixed_C={"boundary": boundary_C}, heat_W=heat_W,
        links=[ThermalLink(a="winding", b="teeth", assumption="Slot mean path; isolated cross-section",
                           resistance_K_W=slab_mean_resistance(width, conductivity_W_mK["winding"],
                                                               depth * config.stator.slot_count * length, two_sided=True))],
        slabs=[ThermalSlab(mean="teeth", a="stator_bore", b="tooth_yoke_interface", assumption="Planar tooth mean and two surfaces",
                           resistance_K_W=depth / (conductivity_W_mK["teeth"] * (areas["teeth"] / depth) * length)),
               ThermalSlab(mean="yoke", a="tooth_yoke_interface", b="boundary", assumption="Planar yoke mean and two surfaces; back face fixed",
                           resistance_K_W=yoke / (conductivity_W_mK["yoke"] * 2 * math.pi * back * length))])
    temperature, _, _ = solve_network(network)
    return {node: temperature[node] for node in NODES}, areas


def area_average(regions, node, expected_area):
    selected = [row for row in regions if row["node"] == node]
    if not selected or any(not math.isfinite(row["area_m2"]) or row["area_m2"] <= 0
                           or not math.isfinite(row["mean_temperature_C"]) for row in selected):
        raise ValueError("Reference needs finite temperatures and positive region areas")
    area = sum(row["area_m2"] for row in selected)
    if not math.isclose(area, expected_area, rel_tol=0.005, abs_tol=1e-12):
        raise ValueError("Reference area does not match registered geometry")
    return sum(row["area_m2"] * row["mean_temperature_C"] for row in selected) / area


def check_conduction(request, bundle=None):
    base = dict(output_status="experimental", claim="Geometry-driven cross-section conduction only; no physical thermal qualification")
    if bundle is None:
        return dict(**base, status="NOT_COMPARED", status_reason="FEMM heat-flow bundle has not been supplied.", metrics=[])
    if bundle.get("request_sha256") != request["request_sha256"] or bundle.get("case_id") != request["case_id"]:
        raise ValueError("FEMM bundle does not match the frozen request")
    if bundle.get("solver") not in SOLVERS or not bundle.get("solver_build") or not bundle.get("raw_artifact_sha256"):
        raise ValueError("Reference needs FEMM version and raw artifact identity")
    if bundle.get("boundary_C") != request["boundary_C"]:
        raise ValueError("FEMM boundary differs from registered fixed temperature")
    metrics = []
    spec = registration()
    for node in NODES:
        fine = area_average(bundle["regions"], node, request["areas_m2"][node])
        coarse = area_average(bundle["coarse_regions"], node, request["areas_m2"][node])
        rise = fine - request["boundary_C"]
        band = max(spec["relative_band"] * abs(rise), spec["absolute_floor_K"])
        error = abs(request["prediction_C"][node] - fine)
        mesh_error = abs(fine - coarse)
        mesh_band = max(spec["mesh_relative_band"] * abs(rise), spec["mesh_floor_K"])
        status = "FAIL" if mesh_error > mesh_band else "PASS" if error <= band else "YELLOW" if error <= 2 * band else "FAIL"
        metrics.append(dict(node=node, predicted_C=request["prediction_C"][node], reference_C=fine, reference_rise_K=rise,
            absolute_error_K=error, pass_band_K=band, mesh_difference_K=mesh_error, mesh_band_K=mesh_band, status=status))
    status = "FAIL" if any(m["status"] == "FAIL" for m in metrics) else "YELLOW" if any(m["status"] == "YELLOW" for m in metrics) else "PASS"
    return dict(**base, status=status,
                status_reason="Frozen temperature-rise bands and mesh check; failed measurements are retained.", metrics=metrics)
