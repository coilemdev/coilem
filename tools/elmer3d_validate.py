"""Run declared physical acceptance controls for the experimental 3D integration."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from backend.elmer.capabilities import discover_elmer
from backend.elmer.mesh import parse_mesh_names
from backend.elmer3d.demo import create_demo
from backend.elmer3d.model import Case3D, Material3D
from backend.elmer3d.solver import sha256, solve_case, write_case


def validate(root: Path, elmer_home: Path, *, resume: bool = False) -> dict:
    if not resume:
        root.mkdir(parents=True, exist_ok=False)
    elif not (root / "validation.json").is_file():
        raise ValueError("resume requires an existing validation.json")
    report = {
        "schema_version": "coilem.elmer3d_controls/v1",
        "status": "RUNNING",
        "motor_qualified": False,
        "limits": {
            "sphere_relative_error": 0.03,
            "mesh_relative_change": 0.02,
            "domain_relative_change": 0.01,
            "linearity_relative_error": 2e-6,
            "torque_reciprocity_relative_error": 0.10,
        },
        "checks": {},
        "runs": {},
    }
    if resume:
        previous = json.loads((root / "validation.json").read_text(encoding="utf-8"))
        if previous["limits"] != report["limits"]:
            raise ValueError("resume cannot change the predeclared limits")
    runtime = discover_elmer(configured_home=elmer_home).require_available(qualified=False)
    audit = root / f"resume-audit-{time.time_ns()}" if resume else None

    def demo(name, **kwargs):
        inputs = root / f"{name}_inputs"
        if resume and (inputs / "case.json").is_file():
            return Case3D.model_validate_json((inputs / "case.json").read_text(encoding="utf-8"))
        return create_demo(inputs, **kwargs)

    def save():
        (root / "validation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    save()

    def run(name, case):
        print(f"Starting {name}", flush=True)
        existing = root / name / "result.json"
        if resume and existing.is_file():
            result = json.loads(existing.read_text(encoding="utf-8"))
            if result["status"] != "COMPLETE" or result["request"] != case.model_dump(mode="json"):
                raise ValueError(f"cannot reuse incomplete or different case {name}; use a new validation directory")
            if result["mesh_sha256"] != sha256(case.mesh_file):
                raise ValueError(f"changed input mesh for {name}")
            for binary in ("solver", "grid"):
                if result["runtime"][f"{binary}_sha256"] != getattr(runtime, f"{binary}_sha256"):
                    raise ValueError(f"changed Elmer binary for {name}")
            proof = audit / name
            proof.mkdir(parents=True, exist_ok=False)
            names = parse_mesh_names(root / name / "mesh" / "mesh.names")
            expected_sif = write_case(case, None, proof, converted_names=names)
            if sha256(expected_sif) != result["sif_sha256"] or sha256(root / name / "case.sif") != result["sif_sha256"]:
                raise ValueError(f"changed SIF lowering for {name}; use a new validation directory")
        else:
            result = solve_case(case, output_dir=root / name, elmer_home=elmer_home)
        report["runs"][name] = {"elapsed_s": result["elapsed_s"], "tetrahedra": result["tetrahedra"], "result": f"{name}/result.json"}
        save()
        print(f"Completed {name}: {result['tetrahedra']} tetrahedra, {result['elapsed_s']:.2f}s", flush=True)
        return result

    try:
        averages = []
        for name, scale, radius in [("sphere", 1.0, 0.06), ("sphere_fine", 0.75, 0.06), ("sphere_exterior", 0.75, 0.09)]:
            case = demo(name, kind="sphere", mesh_scale=scale, outer_radius_m=radius)
            result = run(name, case)
            fields = np.load(root / name / result["fields_npz"])
            interior = np.linalg.norm(fields["nodes_m"], axis=1) < 0.002
            averages.append(float(fields["magnetic_b_T"][interior, 2].mean()))
        expected = 2 / (1.12 + 2)
        limits = report["limits"]
        report["sphere_B_T"] = {"coarse": averages[0], "fine": averages[1], "larger_domain": averages[2], "analytic": expected}
        report["checks"]["sphere_analytic"] = abs(averages[1] / expected - 1) < limits["sphere_relative_error"]
        report["checks"]["mesh_change"] = abs(averages[0] / averages[1] - 1) < limits["mesh_relative_change"]
        report["checks"]["domain_change"] = abs(averages[2] / averages[1] - 1) < limits["domain_relative_change"]
        linear_bh = Case3D.model_validate_json((root / "sphere_inputs" / "case.json").read_text(encoding="utf-8"))
        linear_bh.materials["AirLaw"] = Material3D(kind="bh_curve", bh_points=[(0, 0), (0.1, 0.1 / (4e-7 * np.pi)), (2, 2 / (4e-7 * np.pi))])
        linear_bh.stress_surface = None
        equivalent = run("bh_linear_gauge_reference", linear_bh)
        original_b = np.load(root / "sphere" / "fields.npz")["magnetic_b_T"]
        equivalent_b = np.load(root / "bh_linear_gauge_reference" / equivalent["fields_npz"])["magnetic_b_T"]
        difference = float(np.linalg.norm(original_b - equivalent_b) / np.linalg.norm(original_b))
        report["linear_bh_relative_field_difference"] = difference
        report["checks"]["bh_linear_equivalence"] = difference < limits["linearity_relative_error"]
        case = demo("coupling", kind="torque", mesh_scale=1.5)
        pm_law = case.materials["PMLaw"]
        case.materials["PMLaw"] = pm_law.model_copy(update={"remanence_T": (0, 0, 0)})
        one = run("coil_2A", case)
        case.coils["Winding"].current_A = 4.0
        two = run("coil_4A", case)
        lambda_1, lambda_2 = (r["phase_or_coil_flux_linkage_Wb"]["Winding"] for r in (one, two))
        report["checks"]["coil_nonzero_linkage"] = lambda_1 > 0
        report["checks"]["current_and_flux_normalization"] = abs(lambda_2 / lambda_1 - 2) < limits["linearity_relative_error"]
        fields = np.load(root / "coil_2A" / one["fields_npz"])
        center = np.linalg.norm(fields["nodes_m"], axis=1) < 0.002
        report["checks"]["right_hand_current_direction"] = float(fields["magnetic_b_T"][center, 2].mean()) > 0
        case.materials["PMLaw"] = pm_law.model_copy(update={"remanence_T": (0, 0, 1)})
        case.coils["Winding"].current_A = 0
        pm = run("pm_linkage_at_zero_current", case)
        pm_lambda = pm["phase_or_coil_flux_linkage_Wb"]["Winding"]
        report["checks"]["no_load_virtual_winding"] = pm_lambda > 0
        case.coils["Winding"].current_A = 2
        loaded = run("pm_and_coil", case)
        report["checks"]["flux_superposition"] = (
            abs((loaded["phase_or_coil_flux_linkage_Wb"]["Winding"] - pm_lambda) / lambda_1 - 1) < limits["linearity_relative_error"]
        )
        case.materials["PMLaw"] = pm_law
        case.coils["Winding"].current_A = 20
        plus = run("torque_plus", case)
        case.coils["Winding"].current_A = -20
        minus = run("torque_minus", case)
        stress_torque = (plus["stress"]["torque_Nm"][1] - minus["stress"]["torque_Nm"][1]) / 2
        reference_torque = -20 * pm_lambda
        error = abs(stress_torque / reference_torque - 1)
        report["torque_reciprocity"] = {
            "stress_odd_in_current_Nm": stress_torque,
            "flux_derivative_reference_Nm": reference_torque,
            "relative_error": error,
            "raw_plus_Nm": plus["stress"]["torque_Nm"],
            "raw_minus_Nm": minus["stress"]["torque_Nm"],
        }
        report["checks"]["torque_reciprocity"] = error < limits["torque_reciprocity_relative_error"]
        case = demo("nonlinear_core", kind="steel", mesh_scale=1.5)
        nonlinear = run("nonlinear_core", case)
        report["checks"]["nonlinear_material_solve"] = (
            nonlinear["convergence"]["final_relative_change"] <= case.numerics.nonlinear_tolerance
            and 0 < nonlinear["peak_nodal_b_T"] <= case.materials["CoreLaw"].bh_points[-1][0]
        )
        report["coil_linkage_Wb"] = {"2A": lambda_1, "4A": lambda_2, "PM_zero_current": pm_lambda}
        report["status"] = "PASS" if all(report["checks"].values()) else "FAIL"
        save()
        return report
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        save()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--elmer-home", required=True, type=Path)
    parser.add_argument("--resume", action="store_true", help="reuse complete cases only after request, mesh, binary and SIF hash checks")
    args = parser.parse_args()
    report = validate(args.output_dir.resolve(), args.elmer_home.resolve(), resume=args.resume)
    print(json.dumps({"status": report["status"], "checks": report["checks"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
