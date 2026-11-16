"""Verify the bounded three-mesh #306 study without qualifying the release matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np

from tools.femm_reference.rotor_airgap import BOUNDARY
from tools.rotor_loss_pilot_report import analyse

COMPONENTS = ("hysteresis_W", "lamination_eddy_W", "total_W")
MESHES = ("normal", "fine", "very_fine")
CHANGED_IMPLEMENTATIONS = {"rotor_airgap.py", "rotor_loss_pilot.py"}


def band_arc_step(model_text):
    boundaries = re.findall(r"<BeginBdry>(.*?)<EndBdry>", model_text, re.S)
    matches = [i+1 for i, block in enumerate(boundaries) if f'"{BOUNDARY}"' in block]
    if len(matches) != 1:
        raise ValueError("missing or duplicate moving-band boundary")
    section = re.search(r"^\[NumArcSegments\]\s*=\s*(\d+)\s*\n", model_text, re.M)
    if section is None:
        raise ValueError("missing arc segment evidence")
    rows = [line.split() for line in model_text[section.end():].splitlines()[:int(section[1])]]
    steps = [float(row[3]) for row in rows if int(row[4]) == matches[0]]
    if len(steps) != 8 or len(set(steps)) != 1 or not 0 < steps[0] <= 180:
        raise ValueError("moving-band arcs must have one explicit, consistent step")
    return steps[0]


def mesh_metrics(directory, protocol):
    directory = Path(directory)
    first = directory / "position-0000"
    record = json.loads((first / "position.json").read_text())
    expected_step = protocol.get("airgap_arc_step_deg", 0.25)
    actual_step = band_arc_step((first / "model.fem").read_text(encoding="latin-1"))
    if actual_step != expected_step:
        raise ValueError("saved moving-band arc step differs from the protocol")
    corners = np.loadtxt(first / "rotor.csv", delimiter=",", ndmin=2)[:, :6].reshape(-1, 3, 2)
    edges = np.linalg.norm(corners-np.roll(corners, 1, axis=1), axis=2)
    u, v = corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]
    areas = 0.5*np.abs(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0])
    targets = {json.loads(p.read_text())["airgap_target_mm"] for p in directory.glob("position-*/position.json")}
    if len(targets) != 1:
        raise ValueError("air-gap target changed through the history")
    return {"mesh_geometry_sha256": record["mesh_geometry_sha256"], "total_elements": record["total_elements"],
            "rotor_cells": len(corners), "rotor_area_mm2": float(areas.sum()),
            "rotor_max_cell_area_mm2": float(areas.max()), "rotor_max_edge_mm": float(edges.max()),
            "airgap_target_mm": targets.pop(), "airgap_arc_step_deg": actual_step}


def compare_cases(cases):
    """Compare verified reports at equal angles, physics and material assumptions."""
    if len(cases) != 3 or tuple(c["protocol"]["mesh"] for c in cases) != MESHES:
        raise ValueError("the bounded spatial pilot requires normal, fine and very_fine histories")
    baseline = cases[0]
    baseline_protocol = baseline["protocol"]
    if baseline_protocol["positions"] != 384 or baseline_protocol.get("motion_model") != "periodic-air-gap":
        raise ValueError("the spatial pilot requires fixed-mesh 384-position histories")
    omitted = {"mesh", "collector_sha256", "reference_identity", "airgap_arc_step_deg", "airgap_target_override_mm"}
    physics = {k: v for k, v in baseline_protocol.items() if k not in omitted}
    reference = baseline_protocol["reference_identity"]
    common_reference = {k: v for k, v in reference.items() if k != "implementation_sha256"}
    stable_implementation = {k: v for k, v in reference["implementation_sha256"].items() if k not in CHANGED_IMPLEMENTATIONS}
    summaries = []
    for case in cases:
        protocol, report, metrics = case["protocol"], case["analysis"], case["mesh_metrics"]
        if {k: v for k, v in protocol.items() if k not in omitted} != physics:
            raise ValueError("spatial histories have different physics or sampling settings")
        identity = protocol["reference_identity"]
        if ({k: v for k, v in identity.items() if k != "implementation_sha256"} != common_reference
                or {k: v for k, v in identity["implementation_sha256"].items() if k not in CHANGED_IMPLEMENTATIONS} != stable_implementation):
            raise ValueError("reference backend, binary, dependency or unrelated implementation changed")
        if (report["material"] != baseline["analysis"]["material"] or report["stack_m"] != baseline["analysis"]["stack_m"]
                or report["analysis_sources_sha256"] != baseline["analysis"]["analysis_sources_sha256"]):
            raise ValueError("spatial reports use different loss assumptions or analysis sources")
        if report["raw_coordinate_frame"] != "rotor_material" or report["distinct_triangle_meshes"] != 1:
            raise ValueError("every spatial history must keep its own mesh fixed through the turn")
        rows = {row["positions"]: row for row in report["results"]}
        if set(rows) != {96, 192, 384} or "production_sampling" not in rows[384]:
            raise ValueError("missing complete angular loss results")
        row = rows[384]
        for values in (row["production_sampling"], row["reference"]):
            if not all(np.isfinite(values[k]) and values[k] >= 0 for k in COMPONENTS):
                raise ValueError("invalid spatial loss components")
        summaries.append({"mesh": protocol["mesh"], "data_directory": case["data_directory"], **metrics,
                          "production_sampling": row["production_sampling"],
                          "reference": {k: row["reference"][k] for k in (*COMPONENTS, "share_loss_above_1kHz")},
                          "difference_W": row["difference_W"],
                          "reference_agreement_pass": all(r["reference_agreement_pass"] for r in rows.values()),
                          "angular_gate_pass": report["angular_gate_pass"], "angular_convergence": report["angular_convergence"],
                          "closure_gate": report["closure_gate"], "mesh_invariance_gate": report["mesh_invariance_gate"],
                          "endpoint_max_component_difference_T": report["independent_endpoint_max_component_difference_T"],
                          "endpoint_rms_component_difference_T": report["independent_endpoint_rms_component_difference_T"],
                          "timing": report["timing"], "protocol_sha256": report["protocol_sha256"]})
    if len({case["mesh_geometry_sha256"] for case in summaries}) != 3:
        raise ValueError("spatial refinement must use three different meshes")
    convergence = []
    for coarse, fine in zip(summaries, summaries[1:]):
        design_pass = (fine["total_elements"] > coarse["total_elements"] and fine["rotor_cells"] > coarse["rotor_cells"]
                       and fine["rotor_max_cell_area_mm2"] < coarse["rotor_max_cell_area_mm2"]
                       and fine["airgap_target_mm"] < coarse["airgap_target_mm"]
                       and fine["airgap_arc_step_deg"] < coarse["airgap_arc_step_deg"])
        step = {"from": coarse["mesh"], "to": fine["mesh"], "refinement_design_pass": design_pass}
        for method in ("production_sampling", "reference"):
            changes = {k: fine[method][k]-coarse[method][k] for k in COMPONENTS}
            passes = {k: abs(changes[k]) <= max(0.001, 0.05*fine[method][k]) for k in COMPONENTS}
            step[method] = {"change_W": changes,
                            "relative_change_of_finer": {k: abs(changes[k])/fine[method][k] if fine[method][k] else None for k in COMPONENTS},
                            "component_pass": passes, "pass": all(passes.values())}
        step["pass"] = design_pass and all(step[method]["pass"] for method in ("production_sampling", "reference"))
        convergence.append(step)
    input_pass = all(c["angular_gate_pass"] and c["reference_agreement_pass"] and c["closure_gate"] == "PASS"
                     and c["mesh_invariance_gate"] == "PASS" for c in summaries)
    return {"schema": "coilem.rotor_spatial_pilot/v1", "status": "PILOT_NOT_QUALIFIED",
            "scope": "one loaded SPM, 384 samples per fixed mesh; no native field-solver parity or release-matrix qualification",
            "relative_tolerance": 0.05, "absolute_loss_floor_W": 0.001, "cases": summaries,
            "spatial_convergence": convergence, "spatial_gate_pass": all(c["pass"] for c in convergence),
            "input_numerical_gates_pass": input_pass, "one_case_numerical_gates_pass": input_pass and all(c["pass"] for c in convergence),
            "material": baseline["analysis"]["material"], "stack_m": baseline["analysis"]["stack_m"],
            "analysis_sources_sha256": baseline["analysis"]["analysis_sources_sha256"], "full_matrix_started": False}


def markdown_report(report):
    lines = ["# #306: fixed-mesh spatial refinement", "", "Status: **PILOT_NOT_QUALIFIED**", "", report["scope"]+".", "",
             "| Mesh | Elements | Rotor cells | Hysteresis W | Lamination eddy W | Total W |", "|---|---:|---:|---:|---:|---:|"]
    for case in report["cases"]:
        loss = case["production_sampling"]
        lines.append(f'| {case["mesh"]} | {case["total_elements"]} | {case["rotor_cells"]} | {loss["hysteresis_W"]:.10g} | '
                     f'{loss["lamination_eddy_W"]:.10g} | {loss["total_W"]:.10g} |')
    lines.extend(["", "| Refinement | Hysteresis change | Eddy change | Total change | Gate |", "|---|---:|---:|---:|---|"])
    for step in report["spatial_convergence"]:
        changes = step["production_sampling"]["relative_change_of_finer"]
        percentages = [f'{100*changes[k]:.5f}%' if changes[k] is not None else "n/a" for k in COMPONENTS]
        lines.append(f'| {step["from"]} to {step["to"]} | '+" | ".join(percentages)+f' | {"PASS" if step["pass"] else "FAIL"} |')
    lines.extend(["", f'Spatial gate: **{"PASS" if report["spatial_gate_pass"] else "FAIL"}**. '
                  f'All one-case numerical gates: **{"PASS" if report["one_case_numerical_gates_pass"] else "FAIL"}**.', "",
                  "Changes are relative to the finer result. Each component must satisfy max(5% of finer loss, 0.001 W), in both calculations.",
                  "Each mesh stays fixed through all 385 fresh solves, including the independent endpoint. The endpoint is excluded from loss.",
                  "The two successive mesh comparisons are required. These changes are convergence diagnostics, not measured accuracy bounds.", "",
                  "Material-law coverage, DC bias/minor loops, rotating-flux/excess loss and native field-solver parity remain separate limitations.",
                  "The full release matrix remains unstarted.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs=3, help="Normal, fine, very_fine raw histories")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = []
    for directory in args.directories:
        protocol = json.loads((directory / "protocol.json").read_text())
        report = analyse(directory)
        case_path = args.out / f'{protocol["mesh"]}-analysis.json'
        case_path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        cases.append({"protocol": protocol, "analysis": report, "mesh_metrics": mesh_metrics(directory, protocol),
                      "data_directory": Path(os.path.relpath(directory.resolve(), args.out.resolve())).as_posix()})
        print(json.dumps({"mesh": protocol["mesh"], "analysis_complete": True}), flush=True)
    report = compare_cases(cases)
    report["comparison_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.out / "spatial-analysis.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    (args.out / "spatial-analysis.md").write_text(markdown_report(report), encoding="utf-8")
    summary_keys = ("status", "spatial_gate_pass", "input_numerical_gates_pass", "one_case_numerical_gates_pass")
    print(json.dumps({k: report[k] for k in summary_keys}, indent=2))


if __name__ == "__main__":
    main()
