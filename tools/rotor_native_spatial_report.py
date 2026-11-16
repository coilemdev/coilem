"""Audit three fixed-material native spatial levels without changing raw evidence."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from tools.rotor_native_pilot import sha, write
from tools.rotor_native_report import analyse

COMPONENTS = ("hysteresis_W", "lamination_eddy_W", "total_W")
METHODS = ("production_sampling", "independent_loss_math")
CONTROL_DRIVER = "tools/rotor_native_mesh_refinement.py"


def require_same_problem(cases):
    identities, configs, requests = [], [], []
    for case in cases:
        protocol = case["protocol"]
        if protocol["positions"] != 384 or protocol.get("motion_model") != "fixed-material":
            raise ValueError("native spatial comparison needs fixed-material 384 histories")
        sources = protocol["identity"]["source_sha256"]
        identities.append({k: v for k, v in sources.items() if k != CONTROL_DRIVER})
        config = copy.deepcopy(case["config"])
        config["solve_params"].pop("mesh_density", None)
        configs.append(config)
        requests.append({k: protocol[k] for k in ("fixture_sha256", "mechanical_angles_deg", "current_peak_A",
                         "speed_rpm", "requested_gamma_deg", "native_gamma_deg", "excitation_frame",
                         "expected_native_nonlinear_tolerance", "native_field_frame", "export_frame", "fresh_field_solves")}
                        | {"binary_sha256": protocol["identity"]["binary_sha256"], "loss_material": case["analysis"]["loss_material"]})
    if any(value != identities[0] for value in identities[1:]):
        raise ValueError("native physics or collection sources differ beyond the recorded mesh-control driver")
    if any(value != configs[0] for value in configs[1:]) or any(value != requests[0] for value in requests[1:]):
        raise ValueError("native spatial cases solve different operating points or material assumptions")
    driver_hashes = {case["protocol"]["identity"]["source_sha256"][CONTROL_DRIVER]
                     for case in cases if CONTROL_DRIVER in case["protocol"]["identity"]["source_sha256"]}
    if len(driver_hashes) > 1:
        raise ValueError("explicit mesh-control driver changed among spatial levels")


def mesh_metrics(directory, protocol):
    template = json.loads((directory / "material-template.json").read_text())
    mesh = template["mesh"]
    corners = np.asarray(mesh["nodes"])[np.asarray(mesh["triangles"])]
    rotor_ids = [r["id"] for r in template["physics_contract"]["regions"] if r["kind"] == "RotorCore"]
    corners = corners[np.isin(template["element_region_ids"], rotor_ids)]
    u, v = corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]
    areas = abs(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0])/2
    base = mesh["info"]["gmsh_base_lc_mm"]
    control = protocol["identity"].get("validation_mesh_controls")
    if control is not None and (control["method"] != "explicit_gmsh_template_base_lc/v1"
                                or abs(control["base_lc_mm"]-base) > 1e-12):
        raise ValueError("native saved template does not implement the recorded mesh-size control")
    zero = json.loads((directory / "position-0000/position.json").read_text())
    return {"base_lc_mm": base, "rotor_cells": len(corners), "rotor_max_cell_area_mm2": float(areas.max()),
            "total_elements": zero["total_elements"], "material_template_sha256": protocol["material_template_sha256"],
            "airgap_angular_divisions": protocol["airgap_angular_divisions"], "airgap_radial_layers": protocol["airgap_radial_layers"]}


def compare_levels(levels):
    if len(levels) != 3 or len({r["mesh"]["material_template_sha256"] for r in levels}) != 3:
        raise ValueError("native spatial study requires three distinct material meshes")
    steps = []
    for coarse, fine in zip(levels, levels[1:]):
        a, b = coarse["mesh"], fine["mesh"]
        design = (b["base_lc_mm"] < a["base_lc_mm"] and b["rotor_cells"] > a["rotor_cells"]
                  and b["rotor_max_cell_area_mm2"] < a["rotor_max_cell_area_mm2"]
                  and b["total_elements"] > a["total_elements"]
                  and b["airgap_angular_divisions"] > a["airgap_angular_divisions"]
                  and b["airgap_radial_layers"] > a["airgap_radial_layers"])
        step = {"from": coarse["data_directory"], "to": fine["data_directory"], "refinement_design_pass": design}
        for method in METHODS:
            changes = {k: fine[method][k]-coarse[method][k] for k in COMPONENTS}
            step[method] = {"change_W": changes,
                            "relative_change_of_finer": {k: abs(v)/fine[method][k] if fine[method][k] else None
                                                         for k, v in changes.items()},
                            "component_gates": {k: abs(v) <= max(0.001, 0.05*fine[method][k]) for k, v in changes.items()}}
        step["pass"] = design and all(all(step[m]["component_gates"].values()) for m in METHODS)
        steps.append(step)
    inputs = all(level["native_history_numerical_gates_pass"] for level in levels)
    return {"schema": "coilem.native_rotor_spatial/v1", "status": "PILOT_NOT_QUALIFIED",
            "scope": "one loaded full-motor SPM; native spatial convergence only",
            "levels": levels, "spatial_convergence": steps, "input_history_gates_pass": inputs,
            "native_spatial_gate": "PASS" if inputs and all(s["pass"] for s in steps) else "FAIL",
            "tolerances": {"relative_of_finer": 0.05, "absolute_W": 0.001, "successive_steps_required": 2},
            "corrected_femm_spatial_gate": "NOT_RUN", "full_matrix_started": False}


def markdown_report(report):
    lines = ["# #306: full-motor native spatial refinement", "", "Status: **PILOT_NOT_QUALIFIED**", "",
             "| Level | Rotor cells | Hysteresis mW | Lamination eddy mW | Total mW |",
             "|---|---:|---:|---:|---:|"]
    for level in report["levels"]:
        values = level["production_sampling"]
        lines.append(f'| {level["data_directory"]} | {level["mesh"]["rotor_cells"]} | '
                     + " | ".join(f"{values[k]*1000:.7f}" for k in COMPONENTS) + " |")
    lines += ["", f'Native spatial gate: **{report["native_spatial_gate"]}**.',
              "Both successive steps check each component using max(5% of finer, 0.001 W).",
              "Source/operating-point identity, actual mesh refinement and every history's numerical gates are checked separately.",
              "No mass normalization. Baseline raw evidence and its bound analysis are not overwritten.",
              "Corrected FEMM spatial convergence, remaining full-motor fixture coverage, "
              "product integration and release qualification remain separate.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("histories", nargs=3, type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases, levels = [], []
    for directory in args.histories:
        protocol = json.loads((directory / "protocol.json").read_text())
        config = json.loads((directory / "native-config.json").read_text())
        analysis = analyse(directory)
        cases.append({"protocol": protocol, "config": config, "analysis": analysis})
        row = next(r for r in analysis["results"] if r["positions"] == 384)
        levels.append({"data_directory": directory.name, "mesh": mesh_metrics(directory, protocol),
                       **{method: {k: row[method][k] for k in COMPONENTS} for method in METHODS},
                       "native_history_numerical_gates_pass": analysis["native_history_numerical_gates_pass"],
                       "protocol_sha256": sha(directory / "protocol.json"), "rotor_mass_kg": row["production_sampling"]["rotor_iron_mass_kg"],
                       "closure": analysis["closure"], "angular_convergence": analysis["angular_convergence"]})
    require_same_problem(cases)
    report = compare_levels(levels)
    report["analysis_sources_sha256"] = {"tools/rotor_native_spatial_report.py": sha(__file__)}
    args.out.mkdir(parents=True, exist_ok=True)
    for directory, case in zip(args.histories, cases):
        write(args.out / f"{directory.name}-analysis.json", case["analysis"])
    write(args.out / "comparison.json", report)
    (args.out / "comparison.md").write_text(markdown_report(report), encoding="utf-8")
    print(markdown_report(report))


if __name__ == "__main__":
    main()
