"""Write the frozen specification of benchmark Phase H (thermal).

Run once to register the protocol. Afterwards the specification on disk is the
source of truth and this script is kept only to show where its numbers came
from. It refuses to overwrite an existing specification.

    python -m tools.make_phase_h

The heat of each problem is chosen so coilEM's slot winding sits about 80 K
above the surroundings in the in-plane scope, then rounded and frozen. Thermal
problems with fixed heat are linear, so the level only sets how readable the
temperatures are; it does not favour any tool.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.benchmark_suite.thermal_phase_h import PROTOCOL, SPEC, network_for, thermal_inputs
from backend.models import MotorConfig
from backend.public_policy import parse_public_solve_request
from backend.rotor_layout import is_outer_rotor
from backend.thermal_network import solve_network

ROOT = Path(__file__).resolve().parents[1]
WINDING_RISE_K = 80.0
SURROUNDINGS_C = 25.0
# Winding : teeth : yoke : magnets : rotor iron.
HEAT_SPLIT = {"winding": 10.0, "teeth": 3.0, "yoke": 7.0, "magnets": 1.0, "rotor": 1.0}
CONDUCTIVITY = {"slot": 1.0, "steel": 20.0, "conductor": 385.0, "magnet": 8.0, "housing": 205.0, "liner": 0.2}
CONSTRUCTION = {"housing_thickness_mm": 3.0, "contact_m2K_W": 0.001, "slot_liner_mm": 0.2,
                "bearing_to_housing_K_W": 2.0, "rotor_to_bearing_K_W": 3.0}
COOLING = {
    "inner": {
        "still_air": {"cooling": "still_air", "outside_h_W_m2K": 10.0, "end_space_h_W_m2K": 10.0, "airgap_h_W_m2K": 20.0},
        "forced_air": {"cooling": "forced_air", "outside_h_W_m2K": 60.0, "end_space_h_W_m2K": 25.0, "airgap_h_W_m2K": 40.0},
        "liquid_jacket": {"cooling": "liquid_jacket", "outside_h_W_m2K": 1000.0, "end_space_h_W_m2K": 25.0, "airgap_h_W_m2K": 40.0},
    },
    "outer": {
        "still_air": {"cooling": "still_air", "outside_h_W_m2K": 10.0, "end_space_h_W_m2K": 10.0, "airgap_h_W_m2K": 20.0,
                      "mount_to_ambient_K_W": 10.0},
        "prop_wash": {"cooling": "forced_air", "outside_h_W_m2K": 80.0, "end_space_h_W_m2K": 25.0, "airgap_h_W_m2K": 40.0,
                      "mount_to_ambient_K_W": 10.0},
        "cooled_mount": {"cooling": "still_air", "outside_h_W_m2K": 10.0, "end_space_h_W_m2K": 10.0, "airgap_h_W_m2K": 20.0,
                         "mount_to_ambient_K_W": 1.0},
    },
}
DESIGNS = (
    ("spm_8p12s_concentrated", "benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json",
     "Inner rotor, surface magnets, 8 poles and 12 slots, tooth coils"),
    ("spm_12p36s_distributed", "benchmarks/main-20261009-bad71d9/fixtures/spm_12p36s_distributed_femm_validation.json",
     "Inner rotor, surface magnets, 12 poles and 36 slots, distributed winding"),
    ("ipm_14p18s_flat_buried", "frontend/src/public/examples/validation_ipm_14p_flat_buried_large.openem",
     "Inner rotor, flat buried magnets, 14 poles and 18 slots"),
    ("ipm_10p12s_v_shape", "frontend/src/public/examples/validation_ipm_10p_v_shape_medium.openem",
     "Inner rotor, V-shape buried magnets, 10 poles and 12 slots"),
    ("outrunner_14p12s", "frontend/src/public/examples/spm_outrunner_14p12s.coilem",
     "Outer rotor, 14 poles and 12 slots, 28 mm stator"),
    ("joint_outrunner_36s40p", "frontend/src/public/examples/joint_outrunner_36s40p.coilem",
     "Outer rotor, 40 poles and 36 slots, robot-joint size"),
    ("drone_outrunner_36s40p", "frontend/src/public/examples/drone_outrunner_36s40p_b.coilem",
     "Outer rotor, 40 poles and 36 slots, drone size"),
)


def _load(source: str) -> MotorConfig:
    raw = json.loads((ROOT / source).read_text(encoding="utf-8"))
    if source.endswith(".json"):
        return MotorConfig.model_validate(raw.get("config", raw))
    return parse_public_solve_request(raw)[0]


def _rounded(value: float, digits: int = 4) -> float:
    return float(f"{value:.{digits}g}")


def main() -> int:
    spec_path = ROOT / SPEC
    if spec_path.exists():
        raise SystemExit(f"{SPEC} exists. A registered protocol is not overwritten; make a new version instead.")
    fixtures = ROOT / PROTOCOL / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    designs, cases = [], []
    unit = {part: share / sum(HEAT_SPLIT.values()) for part, share in HEAT_SPLIT.items()}
    for design_id, source, description in DESIGNS:
        config = _load(source)
        layout = "outer" if is_outer_rotor(config) else "inner"
        fixture = fixtures / f"{design_id}.json"
        # A plain request, like every other benchmark fixture: `coilem solve` and the Python client open it as it is.
        fixture.write_text(json.dumps(config.model_dump(mode="json"), indent=1, allow_nan=False) + "\n", encoding="utf-8")
        designs.append({"id": design_id, "layout": layout, "description": description, "source": source,
                        "fixture": str(fixture.relative_to(ROOT)), "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()})
        for cooling_id, cooling in COOLING[layout].items():
            inputs = thermal_inputs(config, cooling, CONSTRUCTION, CONDUCTIVITY, SURROUNDINGS_C, "in_plane", unit)
            network, _ = network_for(config, inputs, unit, "in_plane")
            rise_per_watt = solve_network(network)[0]["winding"] - SURROUNDINGS_C
            total = _rounded(WINDING_RISE_K / rise_per_watt, 3)
            heat = {part: _rounded(total * share) for part, share in unit.items()}
            for scope in ("in_plane", "full"):
                cases.append({"id": f"{design_id}__{cooling_id}__{scope}", "phase": "H", "design": design_id,
                              "cooling": cooling_id, "scope": scope, "heat_W": heat})
    spec = {
        "schema": "coilem.thermal_benchmark_spec/v1", "protocol_version": "H-1.0.0", "phase": "H",
        "scope": "Steady-state part temperatures for fixed heat, conductivities and cooling; seven designs, three cooling "
                 "levels each, in a flat cross-section scope and a full scope",
        "surroundings_C": SURROUNDINGS_C, "conductivity_W_mK": CONDUCTIVITY, "construction": CONSTRUCTION, "cooling": COOLING,
        "heat_split": HEAT_SPLIT,
        "heat_basis": f"Total heat per design and cooling level puts coilEM's slot winding about {WINDING_RISE_K:g} K above the "
                      "surroundings in the in_plane scope; the full scope takes the same heat",
        "copper_temperature_feedback": False,
        "bands": {"relative": 0.1, "floor_K": 2.0, "yellow_multiplier": 2.0,
                  "meaning": "A part passes when its temperature is within 10% of the reference rise above the surroundings, "
                             "or 2 K if that is larger; up to twice that is YELLOW"},
        "designs": designs, "cases": cases,
    }
    spec_path.write_text(json.dumps(spec, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{SPEC}: {len(designs)} designs, {len(cases)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
