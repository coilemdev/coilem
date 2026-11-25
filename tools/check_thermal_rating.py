"""Reproduce the experimental registered-SPM limiting-point example (#22)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.flux_linkage_map import map_computation_identity
from backend.models import DriveLimits, MotorConfig
from backend.models.thermal import ThermalInputs
from backend.resources import data_file
from backend.temperature_maps import TemperatureMapBracket, solve_temperature_bracket
from backend.thermal_rating import thermal_rating


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--maps-root", type=Path, help="Resumable endpoint map directory")
    source.add_argument("--native-bundle", type=Path, help="Reuse a complete published bracket; no endpoint collection")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Evidence already exists; choose a new output path")
    from backend.solver import Magneto2DSolver

    spec = json.loads(data_file("benchmarks/thermal-v0.6/map-interpolation-gates.json").read_text())
    case = spec["cases"][0]
    raw = data_file(case["fixture"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != case["fixture_sha256"]:
        raise ValueError("Registered fixture hash changed")
    parsed = json.loads(raw)
    config = MotorConfig.model_validate(parsed.get("config", parsed))
    config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"magneto2d_workers": 8})})
    solver = Magneto2DSolver(launch_surface=True)
    if args.native_bundle:
        bundle = json.loads(args.native_bundle.read_text())
        if bundle["case_id"] != case["id"] or bundle["fixture_sha256"] != case["fixture_sha256"]:
            raise ValueError("Native bundle does not match the worked example fixture")
        bracket = TemperatureMapBracket.model_validate(bundle["bracket"])
        if bracket.design != config:
            raise ValueError("Native bracket design differs from the registered worked example")
    else:
        bracket = solve_temperature_bracket(config, 20, 80, peak_current_A=40, solve=solver.solve,
                                            store_root=args.maps_root, preset="preview")
    direct_checks = []

    def direct_solve(point_config):
        result = solver.solve(point_config)
        direct_checks.append(dict(config=point_config.model_dump(mode="json"), summary=result.summary.model_dump(mode="json")))
        return result
    inputs = ThermalInputs.model_validate(spec["thermal_inputs"] | dict(housing_h_W_m2K=1000,
        end_space_h_W_m2K=1000, airgap_h_W_m2K=500,
        coefficient_source="Worked-example sensitivity assumptions only; no measured cooling"))
    rating = thermal_rating(bracket, inputs, DriveLimits(dc_bus_V=48, peak_current_A=5, continuous_current_A=5,
        max_speed_rpm=3000), speed_samples=2, current_samples=3, angle_samples=4,
        direct_solve=direct_solve, user_magnet_C=60)
    result = dict(case_id=case["id"], fixture_sha256=case["fixture_sha256"],
        thermal_rating_source_sha256=hashlib.sha256((Path(__file__).resolve().parents[1] / "backend/thermal_rating.py").read_bytes()).hexdigest(),
        computation_identity=map_computation_identity(config), source_scope_keys=[bracket.low.scope_key, bracket.high.scope_key],
        thermal_processing_sha256={name:hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
            for name in ("backend/thermal_network.py", "backend/thermal_rating.py", "backend/models/thermal.py", "tools/check_thermal_rating.py")},
        source_bundle_sha256=hashlib.sha256(args.native_bundle.read_bytes()).hexdigest() if args.native_bundle else None,
        direct_checks=direct_checks, rating=rating.model_dump(mode="json"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps([dict(speed_rpm=row.speed_rpm, status=row.status,
        verification_status=row.point.verification_status if row.point else "NOT_COMPARED") for row in rating.points]))
    return int(any(row.point is None or row.point.verification_status != "PASS" for row in rating.points))


if __name__ == "__main__":
    raise SystemExit(main())
