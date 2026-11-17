"""Read the bounded native rotor pilot; do not treat legacy FEMM losses as a matching target."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.iron_loss import M350_50A_LOSS
from backend.rotor_iron_loss import (
    RotorFieldSample,
    RotorLossMaterial,
    RotorSamplingPlan,
    harmonic_rotor_iron_loss,
    rotor_flux_history,
)
from tools.rotor_closure_report import closure_metrics
from tools.rotor_loss_reference import reference_loss
from tools.rotor_native_pilot import material_query_points, sha, validate_convergence

COMPONENTS = ("hysteresis_W", "lamination_eddy_W", "total_W")


def material_mesh_metrics(samples):
    reference = samples[0].corners_mm
    maximum = 0.0
    for sample in samples[1:]:
        if sample.corners_mm.shape != reference.shape:
            return {"gate": "FAIL", "maximum_coordinate_difference_mm": None, "reason": "material cell count changed"}
        maximum = max(maximum, float(np.max(abs(sample.corners_mm-reference))))
    return {"gate": "PASS" if maximum <= 1e-9 else "FAIL", "maximum_coordinate_difference_mm": maximum,
            "coordinate_tolerance_mm": 1e-9, "rotor_cells": len(reference)}


def loss_rows(samples, positions, speed_rpm, stack_m):
    material = RotorLossMaterial("M350-50A", "EN 10106 grade limits + cited classical lamination eddy term", M350_50A_LOSS)
    rows = []
    for stride in (4, 2, 1):
        indices = list(range(0, positions, stride))
        plan = RotorSamplingPlan(speed_rpm, len(indices))
        row = {"positions": len(indices)}
        try:
            history = rotor_flux_history(plan, [samples[i] for i in indices])
            estimate = harmonic_rotor_iron_loss(history, material=material, stack_length_m=stack_m)
            row["production_sampling"] = asdict(estimate) | {"total_W": estimate.total_W}
            reference = reference_loss(np.stack((history.bx_t, history.by_t), axis=-1), plan.mechanical_angles_deg, history.area_m2,
                                       speed_rpm=speed_rpm, stack_m=stack_m, coefficients=asdict(material.coefficients),
                                       field_frame="rotor_material")
            row["independent_loss_math"] = reference
            row["difference_W"] = {k: row["production_sampling"][k]-reference[k] for k in COMPONENTS}
            row["self_consistency_pass"] = all(abs(d) <= max(0.001, 0.01*reference[k]) for k, d in row["difference_W"].items())
            row["distinct_rotor_meshes"] = history.distinct_meshes
            tail = sum(h["hysteresis_W"]+h["eddy_W"] for h in reference["harmonics"] if h["frequency_Hz"] > 1000)
            row["share_loss_above_1kHz"] = tail/reference["total_W"] if reference["total_W"] else 0
            row["sampling_gate"] = "PASS"
        except ValueError as exc:
            row.update(sampling_gate="FAIL", sampling_error=str(exc), self_consistency_pass=False)
        rows.append(row)
    convergence = []
    for coarse, fine in zip(rows, rows[1:]):
        step = {"from": coarse["positions"], "to": fine["positions"], "pass": False}
        if all("production_sampling" in row for row in (coarse, fine)):
            for method in ("production_sampling", "independent_loss_math"):
                changes = {k: fine[method][k]-coarse[method][k] for k in COMPONENTS}
                step[method] = {"change_W": changes,
                                "relative_change_of_finer": {k: abs(changes[k])/fine[method][k] if fine[method][k] else None
                                                             for k in COMPONENTS},
                                "pass": all(abs(v) <= max(0.001, 0.05*fine[method][k]) for k, v in changes.items())}
            step["pass"] = all(step[m]["pass"] for m in ("production_sampling", "independent_loss_math"))
        convergence.append(step)
    return rows, convergence


def analyse(directory, *, source_root=None, evaluation_speed_rpm=None):
    directory = Path(directory)
    protocol = json.loads((directory / "protocol.json").read_text())
    if protocol["native_field_frame"] != "global" or protocol["export_frame"] != "rotor_material":
        raise ValueError("native raw/export coordinate contract differs")
    if not protocol["fresh_field_solves"]:
        raise ValueError("native field reuse is not allowed in this pilot")
    fixed_material = protocol.get("motion_model") == "fixed-material"
    if fixed_material and sha(directory / "material-template.json") != protocol["material_template_sha256"]:
        raise ValueError("fixed material mesh template changed")
    expected_template_identity = None
    if fixed_material:
        template = json.loads((directory / "material-template.json").read_text())
        expected_template_identity = hashlib.sha256(json.dumps(template, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    for name, digest in protocol["identity"]["source_sha256"].items():
        path = Path(source_root or Path(__file__).resolve().parents[1]) / name
        if sha(path) != digest:
            raise ValueError(f"native source identity changed: {name}")
    points = np.loadtxt(directory / "material-query-points.csv", delimiter=",", ndmin=2)
    if protocol.get("schema") == "coilem.native_rotor_matrix/v1":
        from tools.rotor_matrix_contract import material_query_points as matrix_query_points
        expected_points = matrix_query_points(template)
        if sha(directory / "material-query-points.csv") != protocol["material_query_points_sha256"]:
            raise ValueError("Matrix query-grid hash changed")
        if sha(directory / "native-config.json") != protocol["native_config_sha256"]:
            raise ValueError("Matrix native configuration hash changed")
    else:
        expected_points = material_query_points()
    if points.shape != expected_points.shape or not np.allclose(points, expected_points, rtol=0, atol=1e-12):
        raise ValueError("native material query grid changed")
    config = json.loads((directory / "native-config.json").read_text())
    speed = protocol["speed_rpm"] if evaluation_speed_rpm is None else float(evaluation_speed_rpm)
    if not np.isfinite(speed) or speed <= 0:
        raise ValueError("Loss-evaluation speed must be finite and positive")
    if config["solve_params"]["current_angle_deg"] != protocol["native_gamma_deg"]:
        raise ValueError("native excitation config and declared gamma differ")
    samples, queries, timings, counts = [], [], [], []
    template_identity = None
    for i, angle in enumerate(protocol["mechanical_angles_deg"]):
        position = directory / f"position-{i:04d}"
        record = json.loads((position / "position.json").read_text())
        if record["index"] != i or record["mechanical_angle_deg"] != angle:
            raise ValueError("native checkpoint pose differs")
        for name, digest in record["sha256"].items():
            if Path(name).name != name or sha(position / name) != digest:
                raise ValueError("native checkpoint artifact hash mismatch")
        validate_convergence(record["convergence"], protocol["expected_native_nonlinear_tolerance"])
        if fixed_material:
            motion = record["material_motion_mesh"]
            if (motion["method"] != "fixed_material_conforming_airgap/v1"
                    or motion["template_sha256"] != expected_template_identity
                    or motion["angular_divisions"] != protocol["airgap_angular_divisions"]
                    or motion["radial_layers"] != protocol["airgap_radial_layers"]
                    or (template_identity is not None and motion["template_sha256"] != template_identity)):
                raise ValueError("fixed material motion policy or template differs between poses")
            template_identity = motion["template_sha256"]
        excitation = json.loads((position / "excitation.json").read_text())
        if excitation["gate"] != "PASS" or excitation["native_rotor_mechanical_deg"] != angle:
            raise ValueError("native excitation audit failed")
        if protocol.get("schema") == "coilem.native_rotor_matrix/v1":
            from tools.rotor_matrix_contract import validate_excitation
            validate_excitation(excitation, angle, protocol["excitation_parameters"])
        values = np.loadtxt(position / "rotor-material.csv", delimiter=",", ndmin=2)
        if values.shape != (record["rotor_elements"], 8) or not np.isfinite(values).all():
            raise ValueError("native rotor export malformed")
        samples.append(RotorFieldSample(angle, values[:, :6].reshape(-1, 3, 2), values[:, 6], values[:, 7],
                                        np.arange(len(values))))
        query = np.loadtxt(position / "material-queries.csv", delimiter=",", ndmin=2)
        if query.shape != points.shape or not np.isfinite(query).all():
            raise ValueError("native material queries malformed")
        queries.append(query)
        timings.append(record["wall_s"])
        counts.append(record["total_elements"])
    endpoint = 3 if protocol["kind"] == "preflight" else protocol["positions"]
    closure = closure_metrics(queries[0], queries[endpoint], protocol["closure_tolerances"])
    result = {"schema": "coilem.native_rotor_analysis/v1", "status": "PILOT_NOT_QUALIFIED",
              "scope": "one native SPM; legacy FEMM loss target has incompatible excitation and is excluded",
              "protocol_sha256": sha(directory / "protocol.json"), "kind": protocol["kind"],
              "requested_gamma_deg": protocol["requested_gamma_deg"], "native_gamma_deg": protocol["native_gamma_deg"],
              "mesh": protocol["mesh"], "speed_rpm": speed, "current_peak_A": protocol["current_peak_A"],
              "motion_model": protocol.get("motion_model", "remesh"),
              "closure": closure, "reference_loss_agreement_gate": "NOT_RUN_INVALID_LEGACY_EXCITATION",
              "loss_material": {"steel_id": "M350-50A", "coefficients": asdict(M350_50A_LOSS), "stacking_factor": 1.0,
                                "coefficient_source": "grade-limit hysteresis fit + classical lamination eddy term; not calibrated motor data"},
              "angular_tolerances": {"relative_of_finer": 0.05, "absolute_W": 0.001, "successive_steps_required": 2},
              "native_spatial_gate": "NOT_RUN", "full_matrix_started": False,
              "timing": {"field_solves": len(samples), "sum_position_wall_s": sum(timings),
                         "mean_position_s": float(np.mean(timings)), "min_elements": min(counts), "max_elements": max(counts)}}
    if fixed_material:
        result["material_mesh_invariance"] = material_mesh_metrics(samples)
    if protocol["kind"] == "preflight":
        result["repeat_zero"] = closure_metrics(queries[0], queries[-1], protocol["closure_tolerances"])
    else:
        n = protocol["positions"]
        if protocol["mechanical_angles_deg"] != [-360*k/n for k in range(n+1)]:
            raise ValueError("native history is not the registered full-turn grid")
        rows, convergence = loss_rows(samples, n, speed, config["stator"]["stack_length_mm"]*1e-3)
        result.update(results=rows, angular_convergence=convergence, angular_gate_pass=all(s["pass"] for s in convergence),
                      sampling_gate_pass=all(row["sampling_gate"] == "PASS" for row in rows),
                      loss_math_self_consistency_pass=all(row["self_consistency_pass"] for row in rows))
        result["native_history_numerical_gates_pass"] = (result["closure"]["gate"] == "PASS"
                                                       and result["sampling_gate_pass"] and result["angular_gate_pass"]
                                                       and result["loss_math_self_consistency_pass"]
                                                       and result.get("material_mesh_invariance", {"gate": "PASS"})["gate"] == "PASS")
        amplitude = 2*np.fft.rfft(np.asarray(queries[:n]), axis=0)/n
        power = np.mean(np.sum(abs(amplitude)**2, axis=-1), axis=-1)
        orders = sorted(range(1, n//2), key=lambda k: power[k], reverse=True)[:12]
        result["material_query_spectrum"] = [{"mechanical_order": k, "frequency_Hz": k*speed/60,
                                              "mean_squared_vector_amplitude_T2": float(power[k])} for k in orders]
    if evaluation_speed_rpm is not None:
        result["field_history_speed_rpm"] = protocol["speed_rpm"]
        result["evaluation_speed_rpm"] = speed
    if "matrix_case_id" in protocol:
        result["matrix_case_id"] = protocol["matrix_case_id"]
        result["scope"] = "Registered reduced full-motor rotor-loss matrix; native history only"
        result["full_matrix_started"] = True
    result["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["analysis_sources_sha256"] = {name: sha(Path(__file__).parent / name) for name in
                                         ("rotor_native_report.py", "rotor_loss_reference.py", "rotor_closure_report.py")}
    return result


def markdown_report(report):
    lines = ["# #306 native rotor pilot", "", "Status: **PILOT_NOT_QUALIFIED**", "", report["scope"]+".", "",
             f'Public requested gamma: {report["requested_gamma_deg"]} degrees; native gamma: {report["native_gamma_deg"]} degrees.', "",
             f'Independent endpoint closure: **{report["closure"]["gate"]}**; maximum component error '
             f'{report["closure"]["max_component_difference_T"]:.8g} T.', ""]
    if "material_mesh_invariance" in report:
        lines += [f'Material mesh invariance: **{report["material_mesh_invariance"]["gate"]}**.', ""]
    if "results" in report:
        lines += ["| Samples | Hysteresis W | Lamination eddy W | Total W | Sampling |", "|---:|---:|---:|---:|---|"]
        for row in report["results"]:
            if "production_sampling" in row:
                p = row["production_sampling"]
                lines.append(f'| {row["positions"]} | {p["hysteresis_W"]:.9g} | {p["lamination_eddy_W"]:.9g} | '
                             f'{p["total_W"]:.9g} | {row["sampling_gate"]} |')
            else:
                lines += [f'| {row["positions"]} | unavailable | unavailable | unavailable | FAIL |', "", row["sampling_error"], ""]
        lines += ["", f'Angular convergence: **{"PASS" if report["angular_gate_pass"] else "FAIL"}**.', ""]
    lines += ["FEMM loss agreement is not evaluated: the archived 47.707 mW reference uses a different phase-current trajectory.",
              "The current public/native excitation mapping must be matched in a new reference before claiming cross-solver loss accuracy.",
              "The full matrix remains unstarted.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report = analyse(args.directory)
    (args.directory / "analysis.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    (args.directory / "analysis.md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("kind", "closure", "reference_loss_agreement_gate")}, indent=2))
    if "results" in report:
        print(json.dumps({"sampling_gate_pass": report["sampling_gate_pass"], "angular_gate_pass": report["angular_gate_pass"],
                          "loss_W": [{"positions": row["positions"], "loss": row.get("production_sampling"),
                                      "sampling_error": row.get("sampling_error")} for row in report["results"]]}, indent=2))


if __name__ == "__main__":
    main()
