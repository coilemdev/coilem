"""Collect/evaluate the pre-registered native map-interpolation checks (#21).

Without --collect this reports NOT_COMPARED. It never treats synthetic or
missing records as measured native evidence. Run with PYTHONPATH at checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

from backend.benchmark_suite.temperature_metrics import TemperatureReference, check_temperature_interpolation
from backend.flux_linkage_map import MapStore, map_computation_identity, map_scope_key, point_config, point_from_result, run_flux_linkage_map
from backend.models import DriveLimits, MotorConfig
from backend.models.thermal import ThermalInputs
from backend.resources import data_file
from backend.temperature_maps import at_temperature, solve_temperature_bracket
from backend.winding_resistance import winding_resistance

REGISTRATION = "benchmarks/thermal-v0.6/map-interpolation-gates.json"


def registration():
    return json.loads(data_file(REGISTRATION).read_text(encoding="utf-8"))


def collect(case, spec, root: Path, solve, *, workers=8):
    """Keep the expensive endpoint/intermediate map points resumable on disk."""

    content = data_file(case["fixture"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != case["fixture_sha256"]:
        raise ValueError("Registered fixture hash changed")
    raw = json.loads(content)
    config = MotorConfig.model_validate(raw.get("config", raw))
    config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"magneto2d_workers": workers})})
    computation = map_computation_identity(config)
    runtime = dict(python=sys.version.split()[0], platform=platform.system(), architecture=platform.machine(), workers=workers,
                   resumed_cache_possible=any((root / "maps").rglob("I*.json")))
    bracket = solve_temperature_bracket(config, spec["low_C"], spec["high_C"],
        peak_current_A=case["peak_current_A"], solve=solve, store_root=root / "maps", preset=spec["preset"])
    references = []
    for temperature in spec["intermediate_C"]:
        intermediate = at_temperature(config, temperature)
        scope_key = map_scope_key(intermediate, spec["preset"])
        direct = run_flux_linkage_map(intermediate, solve=solve, peak_current_A=case["peak_current_A"],
                                     preset=spec["preset"], store=MapStore(root / "maps", scope_key))
        points = list(direct.points)
        for fraction, gamma in spec["off_grid"]:
            current = fraction * case["peak_current_A"]
            point = point_from_result(current, gamma, solve(point_config(intermediate, current, gamma, spec["preset"])))
            points.append(point)
        references.append(TemperatureReference(temperature_C=temperature, computation_scope_key=scope_key,
            points=points, direct_map=direct, source="Direct native solve; identity bound by map scope key"))
    settings = ThermalInputs.model_validate(spec["thermal_inputs"])
    limits = DriveLimits(dc_bus_V=case["dc_bus_V"], max_speed_rpm=case["max_speed_rpm"], peak_current_A=case["peak_current_A"])
    verdict = check_temperature_interpolation(bracket, references, limits=limits,
        phase_resistance_ohm=winding_resistance(config).phase_resistance_ohm, thermal_inputs=settings,
        required_temperatures_C=tuple(spec["intermediate_C"]), required_off_grid=tuple(tuple(p) for p in spec["off_grid"]))
    return dict(computation_identity=computation, runtime=runtime,
                registration_sha256=hashlib.sha256(data_file(REGISTRATION).read_bytes()).hexdigest(),
                fixture_sha256=case["fixture_sha256"], case_id=case["id"], bracket=bracket.model_dump(mode="json"),
                references=[reference.model_dump(mode="json") for reference in references], acceptance=verdict.model_dump(mode="json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[case["id"] for case in registration()["cases"]], required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--collect", action="store_true", help="Run 154 preview native solves: five maps plus nine off-grid points")
    args = parser.parse_args()
    if not args.collect:
        print(json.dumps(dict(status="NOT_COMPARED", status_reason="No native collection requested; no reference evidence recorded.")))
        return 0
    if args.out is None:
        parser.error("--collect requires an explicit --out directory")
    from backend.solver import Magneto2DSolver

    spec = registration()
    case = next(case for case in spec["cases"] if case["id"] == args.case)
    solver = Magneto2DSolver(launch_surface=True)
    result = collect(case, spec, args.out, solver.solve)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "acceptance.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    temporary.replace(target)
    print(json.dumps(result["acceptance"]))
    return 1 if result["acceptance"]["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
