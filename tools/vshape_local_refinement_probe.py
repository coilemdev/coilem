"""Probe which mesh region drives V-shape sensitivity (#285). Diagnostic only.

Adds extra Gmsh size fields on top of the shipped ones without editing the
mesher, so each point answers "what changes if only this region is finer".
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import gmsh

from backend import gmsh_solver, solver
from backend.models import MotorConfig
from backend.solver._helpers import _slot_excitation_frames_from_reports

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks/windows-rc-20261013-1fac3a1/fixtures"


def _install_extra_fields(rotor_mm: float | None, rotor_reach_mm: float, rotor_grow_mm: float | None, slot_mm: float | None, gap_scale: float | None):
    real_apply = gmsh_solver._apply_gmsh_physics_mesh_fields
    real_add = gmsh_solver._add_threshold_field

    def apply(builder, geom, config, airgap_width_mm=None):
        made: list[int] = []

        def add(**kwargs):
            tag = real_add(**kwargs)
            made.append(tag)
            return tag

        with patch.object(gmsh_solver, "_add_threshold_field", add):
            real_apply(builder, geom, config, airgap_width_mm)
        base = builder.base_lc_mm
        extra: list[int] = []
        magnet_points = sorted(builder.points_by_feature.get("magnet_corner", set()))
        if rotor_mm is not None and magnet_points:
            extra.append(real_add(points=magnet_points, size_min_mm=rotor_mm, size_max_mm=base,
                                  dist_min_mm=rotor_reach_mm,
                                  dist_max_mm=rotor_reach_mm + (4.0 * base if rotor_grow_mm is None else rotor_grow_mm), sampling=80))
        slot_points = sorted(builder.points_by_feature.get("slot_mouth", set())
                             | builder.points_by_feature.get("slot_tooth_corner", set()))
        if slot_mm is not None and slot_points:
            extra.append(real_add(points=slot_points, size_min_mm=slot_mm, size_max_mm=base,
                                  dist_min_mm=2.0, dist_max_mm=2.0 + 4.0 * base, sampling=80))
        gap_curves = sorted(builder.curves_by_feature.get("airgap_band", set()))
        if gap_scale is not None and gap_curves:
            gap = max(0.05, geom.stator_ID_r - geom.rotor_OD_r)
            size = min(gmsh_solver._feature_lc_mm(base, "airgap"), gap * 0.65, base * 0.19) * gap_scale
            extra.append(real_add(curves=gap_curves, size_min_mm=size, size_max_mm=base,
                                  dist_min_mm=gap * 0.6, dist_max_mm=max(base * 1.6, gap * 2.2), sampling=140))
        if extra:
            combined = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(combined, "FieldsList", made + extra)
            gmsh.model.mesh.field.setAsBackgroundMesh(combined)

    return patch.object(gmsh_solver, "_apply_gmsh_physics_mesh_fields", apply)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", required=True)
    p.add_argument("--fixture", help="fixture file name; default is the V-shape fixture for --case")
    p.add_argument("--density", default="normal")
    p.add_argument("--rotor-mm", type=float)
    p.add_argument("--rotor-reach-mm", type=float, default=5.5)
    p.add_argument("--rotor-grow-mm", type=float)
    p.add_argument("--slot-mm", type=float)
    p.add_argument("--gap-scale", type=float)
    p.add_argument("--cogging", action="store_true")
    p.add_argument("--corner-refinement", action="store_true")
    p.add_argument("--as-registered", action="store_true", help="solve the fixture request unchanged")
    p.add_argument("--no-v-shape-patch", action="store_true", help="mesh as before the V-shape corner patch")
    p.add_argument("--label", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()

    body = json.loads((FIXTURES / (a.fixture or f"ipm_vshape_8p12s_{a.case}__native.json")).read_bytes())
    if not a.as_registered:
        body["solve_params"].update(current_amplitude_A=50, current_angle_deg=30, solve_quality="custom",
                                    rotor_sweep_range_deg=360, rotor_step_deg=7.5, mesh_density=a.density,
                                    rotor_rotation_model="remesh_per_step", corner_refinement=a.corner_refinement)
        body["solve_options"].update(torque_sweep=True, back_emf=True, cogging_torque=a.cogging,
                                     losses_efficiency=False, flux_density=False, thd_analysis=False)
    config = MotorConfig.model_validate(body)
    real_setting, real_report = solver.solver_setting, solver.run_magneto2d_report
    real_aggregate = solver._aggregate_per_angle_mesh_sweep

    def aggregate(cfg, reports, noload, angles, **kwargs):
        result = real_aggregate(cfg, reports, noload, angles, **kwargs)
        result["slot_excitation_frames"] = _slot_excitation_frames_from_reports(reports, angles)
        return result

    def settings(name, default=None):
        return "1" if name == "COILEM_MAGNETO2D_COMPACT_QA_REPORT" else real_setting(name, default)

    def numerical_report(*args, **kwargs):
        report = real_report(*args, **kwargs)
        report.pop("field_plot", None)
        return report

    with tempfile.TemporaryDirectory(prefix="coilem-vshape-probe-") as runtime:
        os.environ["COILEM_USER_DATA_ROOT"] = runtime
        os.environ["COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL"] = "0"
        with (patch.object(solver, "solver_setting", settings),
              patch.object(solver, "_angle_mesh_cache_enabled", return_value=False),
              patch.object(solver.Magneto2DSolver, "_prepare_solve_cache_dir", return_value=None),
              patch.object(solver, "run_magneto2d_report", numerical_report),
              patch.object(solver, "_aggregate_per_angle_mesh_sweep", aggregate),
              _install_extra_fields(a.rotor_mm, a.rotor_reach_mm, a.rotor_grow_mm, a.slot_mm, a.gap_scale),
              (patch.object(gmsh_solver, "_is_v_shape_ipm", return_value=False) if a.no_v_shape_patch else nullcontext())):
            started = time.monotonic()
            result = solver.Magneto2DSolver(launch_surface=True).solve(config)
    dq, cog = result.summary.dq_flux_linkage, result.summary.cogging
    row = {
        "label": a.label, "as_registered": a.as_registered, "v_shape_patch": not a.no_v_shape_patch,
        "corner_refinement": a.corner_refinement, "case": a.case, "density": a.density, "rotor_mm": a.rotor_mm,
        "rotor_reach_mm": a.rotor_reach_mm, "rotor_grow_mm": a.rotor_grow_mm, "slot_mm": a.slot_mm, "gap_scale": a.gap_scale,
        "elapsed_s": round(time.monotonic() - started, 1),
        "elements": result.solve_metadata.mesh_element_count,
        "torque_Nm": result.summary.avg_torque_Nm,
        "bemf_V": result.summary.back_emf_fundamental_V,
        "Ld_mH": None if dq is None or dq.apparent_L_d_H is None else dq.apparent_L_d_H * 1e3,
        "Lq_mH": None if dq is None or dq.apparent_L_q_H is None else dq.apparent_L_q_H * 1e3,
        "cogging_pp_Nm": None if cog is None else cog.peak_to_peak_Nm,
        "cogging_end_mismatch_Nm": None if cog is None else cog.endpoint_mismatch_Nm,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(row, indent=2) + "\n")
    print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
