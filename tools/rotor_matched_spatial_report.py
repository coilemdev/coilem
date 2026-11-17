"""Audit the matched three-mesh FEMM pilot, including its collector-version control."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import numpy as np

from tools.rotor_loss_pilot_report import analyse
from tools.rotor_matched_report import COMPONENTS, audit_sources, reference_source_audit
from tools.rotor_native_pilot import sha, write
from tools.rotor_spatial_report import mesh_metrics

MESH_CONTROLS = {"mesh", "airgap_target_mm", "airgap_arc_step_deg", "mesh_control_contract"}
COLLECTOR_FIELDS = {"collector_sha256", "reference_identity"}


def physics(protocol, *, mesh=False):
    omitted = COLLECTOR_FIELDS | (MESH_CONTROLS if mesh else {"mesh_control_contract"})
    if protocol.get("schema") != "coilem.matched_rotor_reference/v1" or protocol.get("positions") != 384:
        raise ValueError("Matched spatial qualification requires registered 384-position histories")
    return {key: value for key, value in protocol.items() if key not in omitted}


def audit_zero(directory):
    zero = directory / "position-0000"
    record = json.loads((zero / "position.json").read_text())
    for name, digest in record["sha256"].items():
        if Path(name).name != name or sha(zero / name) != digest:
            raise ValueError("Collector control checkpoint changed")
    return record


def collection_bridge(baseline, control, old_source, new_source):
    """Recompute the default-mesh control instead of trusting a passing receipt."""
    a, b = [json.loads((path / "protocol.json").read_text()) for path in (baseline, control)]
    reference_source_audit(a, old_source)
    reference_source_audit(b, new_source)
    if physics(a) != physics(b):
        raise ValueError("Default collector control changes the scientific problem")
    identities = [p["reference_identity"] for p in (a, b)]
    if {k: v for k, v in identities[0].items() if k != "implementation_sha256"} != {
            k: v for k, v in identities[1].items() if k != "implementation_sha256"}:
        raise ValueError("Collector control changes the reference environment")
    impl_a, impl_b = [i["implementation_sha256"] for i in identities]
    changed = {key for key in impl_a.keys() | impl_b.keys() if impl_a.get(key) != impl_b.get(key)}
    if changed != {"rotor_matched_history.py"}:
        raise ValueError("Collector bridge permits only explicit-control plumbing changes")
    functions = []
    for root in (old_source, new_source):
        tree = ast.parse((root / "tools/femm_reference/rotor_matched_history.py").read_text())
        functions.append({node.name: ast.dump(node, include_attributes=False) for node in tree.body
                          if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "main"})
    if functions[0] != {k: v for k, v in functions[1].items() if k != "mesh_controls"}:
        raise ValueError("Scientific collector helpers changed across the bridge")
    records = [audit_zero(directory) for directory in (baseline, control)]
    if records[0]["mesh_geometry_sha256"] != records[1]["mesh_geometry_sha256"]:
        raise ValueError("Default collector control uses a different mesh")
    for name in ("reference-points.csv", "position-0000/rotor.csv"):
        x, y = [np.loadtxt(directory / name, delimiter=",") for directory in (baseline, control)]
        if x.shape != y.shape or not np.array_equal(x, y):
            raise ValueError("Default collector control changes mesh coordinates or zero-pose fields")
    x, y = [np.loadtxt(directory / "position-0000/points.csv", delimiter=",") for directory in (baseline, control)]
    if x.shape != y.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Invalid default collector control fields")
    difference = float(np.max(abs(x-y)))
    if difference > 1e-10:
        raise ValueError("Default collector control field difference exceeds 1e-10 T")
    return {"pass": True, "baseline_protocol_sha256": sha(baseline / "protocol.json"),
            "control_protocol_sha256": sha(control / "protocol.json"), "changed_implementations": sorted(changed),
            "maximum_field_difference_T": difference, "field_tolerance_T": 1e-10,
            "refined_implementation_sha256": impl_b}


def compare_cases(cases, bridge):
    if not bridge.get("pass") or len(cases) != 3:
        raise ValueError("Spatial comparison needs three audited levels and a collector bridge")
    baseline = cases[0]
    levels = []
    for case in cases:
        protocol, report = case["protocol"], case["analysis"]
        if physics(protocol, mesh=True) != physics(baseline["protocol"], mesh=True):
            raise ValueError("Spatial histories solve different scientific problems")
        if {key: value for key, value in protocol["reference_identity"].items() if key != "implementation_sha256"} != {
                key: value for key, value in baseline["protocol"]["reference_identity"].items() if key != "implementation_sha256"}:
            raise ValueError("Spatial histories use different reference environments")
        if case is not baseline and protocol["reference_identity"]["implementation_sha256"] != bridge["refined_implementation_sha256"]:
            raise ValueError("Refined history is not covered by the collector-version bridge")
        if (report["sampling_plan"]["positions"] != 384 or report["material"] != baseline["analysis"]["material"]
                or report["stack_m"] != baseline["analysis"]["stack_m"]):
            raise ValueError("Spatial histories have different sampling or loss material")
        row = next(row for row in report["results"] if row["positions"] == 384)
        levels.append({"directory": case["directory"], "mesh": case["mesh"],
            "reference": {key: row["reference"][key] for key in COMPONENTS},
            "production_sampling": {key: row["production_sampling"][key] for key in COMPONENTS},
            "protocol_sha256": report["protocol_sha256"],
            "numerical_gates_pass": report["angular_gate_pass"] and report["closure_gate"] == "PASS"
                and report["mesh_invariance_gate"] == "PASS" and all(r["reference_agreement_pass"] for r in report["results"]),
            "endpoint_max_T": report["independent_endpoint_max_component_difference_T"],
            "angular_convergence": report["angular_convergence"], "source_audit": case["source_audit"]})
    if len({level["mesh"]["mesh_geometry_sha256"] for level in levels}) != 3:
        raise ValueError("Spatial comparison needs three distinct fixed meshes")
    steps = []
    for coarse, fine in zip(levels, levels[1:]):
        a, b = coarse["mesh"], fine["mesh"]
        design = (b["total_elements"] > a["total_elements"] and b["rotor_cells"] > a["rotor_cells"]
            and b["rotor_max_cell_area_mm2"] < a["rotor_max_cell_area_mm2"]
            and b["airgap_target_mm"] < a["airgap_target_mm"] and b["airgap_arc_step_deg"] < a["airgap_arc_step_deg"])
        step = {"from": coarse["directory"], "to": fine["directory"], "refinement_design_pass": design}
        for method in ("reference", "production_sampling"):
            changes = {key: fine[method][key]-coarse[method][key] for key in COMPONENTS}
            step[method] = {"change_W": changes, "component_gates": {
                key: abs(value) <= max(0.001, 0.05*fine[method][key]) for key, value in changes.items()}}
        step["pass"] = design and all(all(step[method]["component_gates"].values()) for method in ("reference", "production_sampling"))
        steps.append(step)
    passed = all(level["numerical_gates_pass"] for level in levels) and all(step["pass"] for step in steps)
    return {"schema": "coilem.matched_rotor_spatial/v1", "status": "PILOT_NOT_QUALIFIED", "levels": levels,
        "femm_spatial_gate": "PASS" if passed else "FAIL", "spatial_convergence": steps, "collector_bridge": bridge,
        "tolerances": {"relative_of_finer": 0.05, "absolute_W": 0.001, "successive_steps_required": 2},
        "mass_renormalization": False, "full_matrix_started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("histories", nargs=3, type=Path)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--refined-source", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    bridge = collection_bridge(args.histories[0], args.control, args.baseline_source, args.refined_source)
    cases = []
    for index, directory in enumerate(args.histories):
        protocol = json.loads((directory / "protocol.json").read_text())
        source = args.baseline_source if index == 0 else args.refined_source
        audit = audit_sources(directory, protocol, 1, source_root=source)
        report = analyse(directory)
        cases.append({"directory": directory.name, "protocol": protocol, "analysis": report,
                      "mesh": mesh_metrics(directory, protocol), "source_audit": audit})
    result = compare_cases(cases, bridge)
    result["analysis_script_sha256"] = sha(__file__)
    args.out.mkdir(parents=True, exist_ok=True)
    for case in cases:
        write(args.out / (case["directory"] + "-analysis.json"), case["analysis"])
    write(args.out / "comparison.json", result)
    print(json.dumps({"status": result["status"], "femm_spatial_gate": result["femm_spatial_gate"]}))


if __name__ == "__main__":
    main()
