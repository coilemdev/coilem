"""Bounded-memory V-shape refinement study, independent of release qualification."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from backend import solver
from backend.models import MotorConfig
from backend.solver._helpers import _slot_excitation_frames_from_reports

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks/windows-rc-20261013-1fac3a1/fixtures"
CASES = ("baseline_contract", "thin_bridge_contract", "wide_angle_high_output_v1")


def point(case: str, density: str) -> dict:
    path = FIXTURES / f"ipm_vshape_8p12s_{case}__native.json"
    body = json.loads(path.read_text())
    body["solve_params"].update(current_amplitude_A=50, current_angle_deg=30, solve_quality="custom",
                                rotor_sweep_range_deg=360, rotor_step_deg=7.5, mesh_density=density,
                                rotor_rotation_model="remesh_per_step")
    body["solve_options"].update(torque_sweep=True, back_emf=True, cogging_torque=True,
                                 losses_efficiency=False, flux_density=False, thd_analysis=False)
    config = MotorConfig.model_validate(body)
    real_setting, real_report = solver.solver_setting, solver.run_magneto2d_report
    real_aggregate = solver._aggregate_per_angle_mesh_sweep

    def settings(name, default=None):
        return "1" if name == "COILEM_MAGNETO2D_COMPACT_QA_REPORT" else real_setting(name, default)

    def numerical_report(*args, **kwargs):
        report = real_report(*args, **kwargs)
        report.pop("field_plot", None)  # Native scalar results and slot records remain full precision.
        return report

    def aggregate(cfg, reports, noload, angles, **kwargs):
        result = real_aggregate(cfg, reports, noload, angles, **kwargs)
        result["slot_excitation_frames"] = _slot_excitation_frames_from_reports(reports, angles)
        return result

    # Disable only caches and viewer packaging. Keep the public rotation convention,
    # native environment, meshes, angular grids and numerical post-processing.
    with tempfile.TemporaryDirectory(prefix="coilem-vshape-point-") as runtime:
        os.environ["COILEM_USER_DATA_ROOT"] = runtime
        os.environ["COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL"] = "0"
        with (patch.object(solver, "solver_setting", settings),
              patch.object(solver, "_angle_mesh_cache_enabled", return_value=False),
              patch.object(solver.Magneto2DSolver, "_prepare_solve_cache_dir", return_value=None),
              patch.object(solver, "run_magneto2d_report", numerical_report),
              patch.object(solver, "_aggregate_per_angle_mesh_sweep", aggregate)):
            started = time.monotonic()
            result = solver.Magneto2DSolver(launch_surface=True).solve(config)
    dq, cogging = result.summary.dq_flux_linkage, result.summary.cogging
    assert dq is not None and cogging is not None
    return {
        "case": case, "mesh_density": density, "request": body,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "fixture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "elapsed_s": round(time.monotonic() - started, 2), "mesh_elements": result.solve_metadata.mesh_element_count,
        "average_torque_Nm": result.summary.avg_torque_Nm, "back_emf_fundamental_V": result.summary.back_emf_fundamental_V,
        "L_d_H": dq.apparent_L_d_H, "L_q_H": dq.apparent_L_q_H,
        "cogging_peak_to_peak_Nm": cogging.peak_to_peak_Nm, "cogging_endpoint_mismatch_Nm": cogging.endpoint_mismatch_Nm,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--density", choices=["coarse", "normal", "fine", "very_fine"])
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.case:
        if not args.density:
            parser.error("--case requires --density")
        args.out.write_text(json.dumps(point(args.case, args.density), indent=2) + "\n")
        return
    report = {
        "scope": "Mesh sensitivity only; no FEMM or hardware qualification. Full-cycle 7.5-degree electrical sampling.",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "platform": platform.platform(),
        "dependencies": {n: importlib.metadata.version(n) for n in ("gmsh", "numpy", "pydantic")},
        "rows": [],
    }
    for case in CASES:
        for density in ("coarse", "normal", "fine", "very_fine"):
            row = args.out.with_name(f"{case}-{density}.json")
            if not row.exists():
                print(f"Starting {case}: {density}", flush=True)
                subprocess.run([sys.executable, "-m", "tools.vshape_mesh_study", "--case", case,
                                "--density", density, "--out", str(row)], cwd=ROOT, check=True)
            report["rows"].append(json.loads(row.read_text()))
            args.out.write_text(json.dumps(report, indent=2) + "\n")
            print({k: v for k, v in report["rows"][-1].items() if k != "request"}, flush=True)


if __name__ == "__main__":
    main()
