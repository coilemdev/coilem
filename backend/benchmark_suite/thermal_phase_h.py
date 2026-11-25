"""Benchmark Phase H: thermal.

Phases A to G compare electromagnetic results with FEMM. Phase H does the same
for the thermal estimate. It is a fixed set of thermal problems, each fully
stated so another tool can solve it: the design, the heat placed in each part,
the conductivities, the cooling and the temperature of the surroundings.

Every design is run at three cooling levels and in two scopes:

* ``in_plane``: only what a flat cross-section contains. All copper heat is in
  the slots, and the end windings, the air around them, the bearings and the
  slot liner are left out. A planar finite-element tool such as FEMM can solve
  exactly this problem.
* ``full``: the whole estimate, with end windings, end-space air, bearings and
  a slot liner. It needs a three-dimensional or lumped tool, or a bench test,
  to compare with.

The heat is fixed in watts, so copper-temperature feedback is off and every
problem is linear. The numbers are in ``benchmarks/h-v1.0/benchmark_spec.json``
and are frozen: a reference from another tool names the hash of that file.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from backend.geometry_ir import build_geometry_ir
from backend.loss_breakdown import operating_point_losses
from backend.models import IronLoss, MotorConfig
from backend.models.thermal import ThermalInputs
from backend.rotor_layout import is_outer_rotor
from backend.thermal_network import build_network, cylindrical_resistance, solve_network

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "benchmarks/h-v1.0"
SPEC = f"{PROTOCOL}/benchmark_spec.json"
RESULTS = f"{PROTOCOL}/results/coilem.json"
REFERENCES = f"{PROTOCOL}/references"
SOURCES = ("backend/benchmark_suite/thermal_phase_h.py", "backend/thermal_network.py", "backend/models/thermal.py",
           "backend/loss_breakdown.py", "backend/winding_resistance.py")
# The parts a result reports. A stator sits in a housing (inner rotor) or on a mount (outer rotor).
PARTS = ("winding", "end_winding", "teeth", "yoke", "housing", "mount", "magnets", "rotor", "bearings", "airgap", "end_air")
# What a flat cross-section can be asked for.
PLANAR_PARTS = ("winding", "teeth", "yoke", "magnets", "rotor")
# Region kinds of the cross-section and the material each is given in a planar model.
PLANAR_MATERIALS = {"SlotWinding": "winding", "StatorTooth": "teeth", "StatorYoke": "yoke", "Airgap": "gap",
                    "MagnetPocketAir": "pocket", "Magnet": "magnets", "RotorCore": "rotor", "Shaft": None}
CLOSED_K_W = 1e9
CLOSED_W_M2K = 1e-4
NO_LINER_MM = 1e-6


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def spec() -> dict:
    return json.loads((ROOT / SPEC).read_text(encoding="utf-8"))


def spec_sha256() -> str:
    return _sha256(ROOT / SPEC)


@lru_cache(maxsize=None)
def design(design_id: str) -> MotorConfig:
    entry = next(row for row in spec()["designs"] if row["id"] == design_id)
    path = ROOT / entry["fixture"]
    if _sha256(path) != entry["fixture_sha256"]:
        raise ValueError(f"Phase H fixture {entry['fixture']} differs from its frozen registration")
    return MotorConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def case(case_id: str) -> dict:
    return next(row for row in spec()["cases"] if row["id"] == case_id)


def thermal_inputs(config: MotorConfig, cooling: dict, construction: dict, conductivity: dict, surroundings_C: float,
                   scope: str, heat_W: dict) -> ThermalInputs:
    """The network inputs of one problem. ``in_plane`` closes every path a flat cross-section does not have."""

    in_plane = scope == "in_plane"
    rotor_heat = heat_W["magnets"] + heat_W["rotor"]
    values = {
        "cooling": cooling["cooling"], "ambient_C": surroundings_C,
        "housing_h_W_m2K": cooling["outside_h_W_m2K"], "airgap_h_W_m2K": cooling["airgap_h_W_m2K"],
        "end_space_h_W_m2K": CLOSED_W_M2K if in_plane else cooling["end_space_h_W_m2K"],
        "coefficient_source": "Benchmark Phase H: prescribed values, not a measurement",
        "housing_thickness_mm": construction["housing_thickness_mm"], "contact_m2K_W": construction["contact_m2K_W"],
        "slot_liner_mm": NO_LINER_MM if in_plane else construction["slot_liner_mm"],
        "bearing_to_housing_K_W": CLOSED_K_W if in_plane else construction["bearing_to_housing_K_W"],
        "rotor_to_bearing_K_W": CLOSED_K_W if in_plane else construction["rotor_to_bearing_K_W"],
        "mount_to_ambient_K_W": cooling.get("mount_to_ambient_K_W") if is_outer_rotor(config) else None,
        "steel_k_W_mK": conductivity["steel"], "conductor_k_W_mK": conductivity["conductor"], "housing_k_W_mK": conductivity["housing"],
        "magnet_k_W_mK": conductivity["magnet"], "liner_k_W_mK": conductivity["liner"],
        "slot_k_model": "user", "slot_k_W_mK": conductivity["slot"], "slot_k_source": "Benchmark Phase H: prescribed value",
        "extra_rotor_heat_W": rotor_heat, "extra_rotor_heat_to_magnets_fraction": heat_W["magnets"] / rotor_heat if rotor_heat else 0,
        "insulation_class": "H", "hotspot_allowance_K": 0,
    }
    return ThermalInputs.model_validate(values)


def network_for(config: MotorConfig, inputs: ThermalInputs, heat_W: dict, scope: str):
    """The thermal network of one problem, with the prescribed heat in its parts."""

    stator_iron = heat_W["teeth"] + heat_W["yoke"]
    iron = IronLoss(status="experimental", steel="M350-50A", electrical_frequency_Hz=100, iron_loss_W=stator_iron,
                    iron_hysteresis_loss_W=stator_iron / 2, iron_eddy_loss_W=stator_iron / 2,
                    iron_teeth_loss_W=heat_W["teeth"], iron_yoke_loss_W=heat_W["yoke"],
                    stator_iron_mass_kg=1, validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)
    winding, losses = operating_point_losses(config, 1.0, iron)
    # A flat cross-section has no end windings: all the copper heat is in the slots. Otherwise the
    # winding's own geometry says how much of its length, and so of its heat, is outside the stack.
    active = 1.0 if scope == "in_plane" else winding.active_fraction
    losses = losses.model_copy(update={
        "copper_loss_W": heat_W["winding"], "copper_active_loss_W": heat_W["winding"] * active,
        "copper_end_winding_loss_W": heat_W["winding"] * (1 - active), "iron_loss_W": stator_iron, "mechanical_loss_W": 0.0})
    return build_network(config, inputs, winding, losses, iron), winding


def _problem(case_row: dict, heat_W: dict | None = None):
    registered = spec()
    config = design(case_row["design"])
    layout = "outer" if is_outer_rotor(config) else "inner"
    heat = case_row["heat_W"] if heat_W is None else heat_W
    inputs = thermal_inputs(config, registered["cooling"][layout][case_row["cooling"]], registered["construction"],
                            registered["conductivity_W_mK"], registered["surroundings_C"], case_row["scope"], heat)
    network, winding = network_for(config, inputs, heat, case_row["scope"])
    return config, layout, inputs, network, winding


def solve_case(case_row: dict, heat_W: dict | None = None) -> dict:
    """coilEM's answer to one Phase H problem."""

    surroundings = spec()["surroundings_C"]
    config, layout, inputs, network, winding = _problem(case_row, heat_W)
    temperatures, rejected, balance = solve_network(network)
    heat = case_row["heat_W"] if heat_W is None else heat_W
    # Heat crossing each link into the surroundings, named by the part it leaves.
    exits = {}
    for link in network.links:
        if "ambient" in (link.a, link.b):
            part = link.b if link.a == "ambient" else link.a
            exits["shell" if part == "rotor" else part] = (temperatures[part] - surroundings) / link.resistance_K_W
    parts = {name: temperatures[name] for name in PARTS if name in temperatures}
    hottest = max((name for name in parts if name not in ("airgap", "end_air")), key=parts.get)
    return {
        "id": case_row["id"], "design": case_row["design"], "layout": layout, "cooling": case_row["cooling"], "scope": case_row["scope"],
        "heat_W": heat, "total_heat_W": sum(heat.values()),
        "end_winding_heat_W": network.heat_W["end_winding"], "copper_length_share_outside_stack": 1 - winding.active_fraction,
        "temperature_C": parts, "hottest_part": hottest, "exit_W": exits, "energy_balance_W": balance,
    }


def planar_problem(case_row: dict) -> dict:
    """What a flat finite-element tool needs for an ``in_plane`` case.

    The network treats the cooled surfaces and the air gap as plain
    resistances. A planar model gets exactly those: each cooled face carries
    the coefficient that gives the network's resistance over the face's own
    area, and the gap is a solid whose conductivity gives the network's two gap
    films across its real thickness. The air pockets beside the magnets conduct
    like the magnets, because the network puts the rotor-side film on the whole
    rotor circumference.
    """

    if case_row["scope"] != "in_plane":
        raise ValueError("Only an in_plane case can be solved on a flat cross-section")
    registered = spec()
    surroundings = registered["surroundings_C"]
    config, layout, inputs, network, _ = _problem(case_row)
    resistance = {(link.a, link.b): link.resistance_K_W for link in network.links}
    length = config.stator.stack_length_mm * 1e-3
    regions = [region for region in build_geometry_ir(config).regions if region.kind in PLANAR_MATERIALS]
    areas: dict[str, float] = {}
    for region in regions:
        material = PLANAR_MATERIALS[region.kind]
        if material:
            areas[material] = areas.get(material, 0.0) + region.area_mm2 * 1e-6
    gap_radii = sorted(_loop_radius(loop) for region in regions if region.kind == "Airgap" for loop in region.loops)
    gap_resistance = resistance[("stator_bore", "airgap")] + resistance[("airgap", "rotor")]
    conductivity = {"winding": inputs.slot_k_W_mK, "teeth": inputs.steel_k_W_mK, "yoke": inputs.steel_k_W_mK,
                    "magnets": inputs.magnet_k_W_mK, "rotor": inputs.steel_k_W_mK, "pocket": inputs.magnet_k_W_mK,
                    "gap": math.log(gap_radii[-1] / gap_radii[0]) / (2 * math.pi * length * gap_resistance)}

    def face(radius_mm, resistance_K_W, inward):
        return {"radius_mm": radius_mm, "inward": inward, "resistance_K_W": resistance_K_W,
                "h_W_m2K": 1 / (resistance_K_W * 2 * math.pi * radius_mm * 1e-3 * length), "surroundings_C": surroundings}

    if layout == "outer":
        shell_inner, shell_outer = config.rotor.ID_mm * 0.0005, config.rotor.OD_mm * 0.0005
        # A planar model conducts through the rotor shell itself, so the shell's outer face carries the film only.
        film = resistance[("rotor", "ambient")] - cylindrical_resistance(shell_inner, shell_outer, length, inputs.steel_k_W_mK)
        faces = {"mount": face(config.stator.ID_mm / 2, resistance[("stator_back", "mount")] + resistance[("mount", "ambient")], 1),
                 "shell": face(config.rotor.OD_mm / 2, film, -1)}
    else:
        faces = {"housing": face(config.stator.OD_mm / 2, resistance[("stator_outer", "housing")] + resistance[("housing", "ambient")], -1)}
    heat = case_row["heat_W"]
    source = {part: heat[part] / (areas[part] * length) for part in PLANAR_PARTS} | {"gap": 0.0, "pocket": 0.0}
    return {"config": config, "layout": layout, "regions": regions, "areas_m2": areas, "conductivity_W_mK": conductivity,
            "source_W_m3": source, "faces": faces, "gap_mm": gap_radii[-1] - gap_radii[0], "depth_mm": config.stator.stack_length_mm}


def _loop_radius(loop) -> float:
    radii = [math.hypot(segment.start.x_mm, segment.start.y_mm) for segment in loop.segments]
    if max(radii) - min(radii) > 1e-6:
        raise ValueError("Phase H needs a plain cylindrical air gap")
    return radii[0]


def run() -> dict:
    """Every registered case, solved by this build."""

    registered = spec()
    return {
        "schema": "coilem.thermal_benchmark_result/v1", "protocol_version": registered["protocol_version"], "phase": "H",
        "spec_sha256": spec_sha256(), "surroundings_C": registered["surroundings_C"],
        "source_sha256": {name: _sha256(ROOT / name) for name in SOURCES},
        "cases": [solve_case(row) for row in registered["cases"]],
    }


def references() -> dict[str, dict[str, dict]]:
    """Reference bundles on disk, by tool folder and case id. A bundle for another spec is refused."""

    found: dict[str, dict[str, dict]] = {}
    root = ROOT / REFERENCES
    for folder in sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []:
        for path in sorted(folder.glob("*.json")):
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if bundle.get("spec_sha256") != spec_sha256():
                raise ValueError(f"Reference {folder.name}/{path.name} was made for a different Phase H specification")
            found.setdefault(folder.name, {})[bundle["case_id"]] = bundle
    return found


def grade(result: dict, bundle: dict) -> dict:
    """One case against one reference: each part's temperature rise within the registered band."""

    registered = spec()
    bands, surroundings = registered["bands"], registered["surroundings_C"]
    rows = []
    for part, reference in bundle["temperature_C"].items():
        if part not in result["temperature_C"]:
            continue
        rise = reference - surroundings
        difference = result["temperature_C"][part] - reference
        band = max(bands["relative"] * abs(rise), bands["floor_K"])
        status = "PASS" if abs(difference) <= band else "YELLOW" if abs(difference) <= bands["yellow_multiplier"] * band else "FAIL"
        rows.append({"part": part, "coilem_C": result["temperature_C"][part], "reference_C": reference, "difference_K": difference,
                     "difference_pct_of_rise": 100 * difference / rise if abs(rise) > 1e-9 else None, "band_K": band, "status": status})
    exits = []
    for name, reference in (bundle.get("exit_W") or {}).items():
        if name in result["exit_W"]:
            total = result["total_heat_W"]
            exits.append({"exit": name, "coilem_share_pct": 100 * result["exit_W"][name] / total, "reference_share_pct": 100 * reference / total})
    worst = "FAIL" if any(row["status"] == "FAIL" for row in rows) else "YELLOW" if any(row["status"] == "YELLOW" for row in rows) else "PASS"
    return {"case_id": result["id"], "tool": bundle["tool"], "status": worst if rows else "NOT_COMPARED", "parts": rows, "exits": exits}


def compare(result: dict) -> dict:
    """Every case against every reference on disk. A case without a reference is NOT_COMPARED."""

    found = references()
    by_tool = {}
    for tool, bundles in found.items():
        graded = [grade(row, bundles[row["id"]]) if row["id"] in bundles
                  else {"case_id": row["id"], "tool": tool, "status": "NOT_COMPARED", "parts": [], "exits": []} for row in result["cases"]]
        counts: dict[str, int] = {}
        for row in graded:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        by_tool[tool] = {"counts": counts, "cases": graded}
    return by_tool
