"""Compare the thermal network's cross-section reduction with an independent finite-element solution.

The six registered conduction cases and the bundled outer-rotor examples are
solved on their own Gmsh meshes by ``backend.benchmark_suite.thermal_fe`` and
set beside the network's prediction for the same isolated problem: winding,
teeth and yoke only, the yoke's back face held at the boundary temperature,
every other edge insulated, the registered conductivities.

This is not the registered FEMM comparison; that is
``tools.check_thermal_conduction_femm``. Run from a checkout:

    python -m tools.check_thermal_conduction_fe --out benchmarks/thermal-v0.6/conduction-fe-results.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.benchmark_suite.thermal_conduction import NODES, cross_section_prediction, registration
from backend.benchmark_suite.thermal_fe import stator_conduction_reference
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.models import MotorConfig
from backend.public_policy import parse_public_solve_request
from backend.rotor_layout import is_outer_rotor

ROOT = Path(__file__).resolve().parents[1]
# Outer-rotor designs are not in the registration, so they take its three heat cases unchanged.
OUTER_EXAMPLES = ("spm_outrunner_14p12s", "joint_outrunner_36s40p", "drone_outrunner_36s40p_b")
SOURCES = ("backend/benchmark_suite/thermal_fe.py", "backend/benchmark_suite/thermal_conduction.py", "backend/thermal_network.py")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def designs():
    """Yield ``(case id, fixture path, config, heat)`` for every compared case."""

    spec = registration()
    heat_cases = {}
    for case in spec["cases"]:
        raw = json.loads((ROOT / case["fixture"]).read_text(encoding="utf-8"))
        heat_cases[case["id"].rsplit("_", 1)[1]] = case["heat_W"]
        yield case["id"], case["fixture"], MotorConfig.model_validate(raw.get("config", raw)), case["heat_W"]
    for name in OUTER_EXAMPLES:
        fixture = f"frontend/src/public/examples/{name}.coilem"
        config, _, _ = parse_public_solve_request(json.loads((ROOT / fixture).read_text(encoding="utf-8")))
        for label, heat in heat_cases.items():
            yield f"{name}_{label}", fixture, config, heat


def compare(coarse: str, fine: str) -> dict:
    spec = registration()
    conductivity, boundary = spec["conductivity_W_mK"], spec["boundary_C"]
    meshes: dict[tuple[str, str], dict] = {}
    rows = []
    for case_id, fixture, config, heat in designs():
        prediction, areas = cross_section_prediction(config, heat, conductivity, boundary)
        outer = is_outer_rotor(config)
        reference = {}
        for level in (coarse, fine):
            if (fixture, level) not in meshes:
                sized = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"mesh_density": level})})
                meshes[(fixture, level)] = run_gmsh_mesh_preview(sized, rotor_angle_deg=0.0)
            solved = stator_conduction_reference(
                meshes[(fixture, level)], fixed_radius_mm=(config.stator.ID_mm if outer else config.stator.OD_mm) / 2,
                boundary_C=boundary, conductivity_W_mK=conductivity, heat_W=heat, stack_length_m=config.stator.stack_length_mm * 1e-3)
            reference[level] = solved | {"by_node": {row["node"]: row for row in solved["regions"]}}
        for node in NODES:
            fine_row, coarse_row = reference[fine]["by_node"][node], reference[coarse]["by_node"][node]
            rise = fine_row["mean_temperature_C"] - boundary
            difference = prediction[node] - fine_row["mean_temperature_C"]
            mesh_difference = abs(fine_row["mean_temperature_C"] - coarse_row["mean_temperature_C"])
            band = max(spec["relative_band"] * abs(rise), spec["absolute_floor_K"])
            mesh_band = max(spec["mesh_relative_band"] * abs(rise), spec["mesh_floor_K"])
            rows.append(dict(
                case=case_id, fixture=fixture, layout="outer" if outer else "inner", node=node,
                network_rise_K=prediction[node] - boundary, reference_rise_K=rise, difference_K=difference,
                difference_pct=100 * difference / rise if abs(rise) > 1e-12 else None,
                mesh_difference_K=mesh_difference, mesh_difference_pct=100 * mesh_difference / abs(rise) if abs(rise) > 1e-12 else None,
                registered_band_K=band,
                registered_band_status=("MESH" if mesh_difference > mesh_band else "PASS" if abs(difference) <= band
                                        else "YELLOW" if abs(difference) <= 2 * band else "FAIL"),
                area_difference_pct=100 * (fine_row["area_m2"] - areas[node]) / areas[node],
                triangles_coarse=reference[coarse]["triangles"], triangles_fine=reference[fine]["triangles"]))
    return dict(
        schema_version=1, kind="thermal_conduction_fe_comparison",
        reference="Independent linear-triangle finite elements on the design's Gmsh mesh (numpy); not FEMM",
        problem="Winding, teeth and yoke only; yoke back face fixed; other edges insulated; registered conductivities and heat cases",
        registration=spec["protocol"], boundary_C=boundary, conductivity_W_mK=conductivity, mesh_levels=dict(coarse=coarse, fine=fine),
        source_sha256={name: _sha256(ROOT / name) for name in SOURCES},
        fixture_sha256={fixture: _sha256(ROOT / fixture) for fixture in dict.fromkeys(row["fixture"] for row in rows)},
        rows=rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="write the comparison as JSON")
    parser.add_argument("--coarse", default="coarse", help="mesh density of the coarser solution (default: coarse)")
    parser.add_argument("--fine", default="fine", help="mesh density of the reference solution (default: fine)")
    args = parser.parse_args()
    result = compare(args.coarse, args.fine)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{'case':36s} {'layout':6s} {'node':8s} {'network K':>10s} {'FE K':>9s} {'diff %':>7s} {'mesh %':>7s} {'band':>6s}")
    for row in result["rows"]:
        print(f"{row['case']:36s} {row['layout']:6s} {row['node']:8s} {row['network_rise_K']:10.3f} {row['reference_rise_K']:9.3f} "
              f"{row['difference_pct']:7.1f} {row['mesh_difference_pct']:7.2f} {row['registered_band_status']:>6s}")
    return int(any(row["registered_band_status"] in ("FAIL", "MESH") for row in result["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
