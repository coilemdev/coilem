"""Read and verify a completed FEMM pilot; compare sampling against a separate DFT oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.iron_loss import M350_50A_LOSS, FieldFrame
from backend.rotor_iron_loss import (
    RotorLossMaterial,
    RotorSamplingPlan,
    harmonic_rotor_iron_loss,
    rotor_flux_history,
    sample_rotor_field,
)
from tools.rotor_loss_reference import reference_loss


def analyse(directory):
    directory = Path(directory)
    protocol = json.loads((directory / "protocol.json").read_text())
    reference_points = np.loadtxt(directory / "reference-points.csv", delimiter=",", ndmin=2)
    count = protocol["positions"]
    if count % 4 or count < 32:
        raise ValueError("pilot analysis needs a grid divisible by four and at least 32 positions")
    samples, queried_fields, timing, element_counts = [], [], [], []
    for index in range(count+1):
        position = directory / f"position-{index:04d}"
        record = json.loads((position / "position.json").read_text())
        for name, digest in record["sha256"].items():
            if hashlib.sha256((position / name).read_bytes()).hexdigest() != digest:
                raise ValueError("reference artifact hash mismatch")
        angle = -360*index/count
        if record["index"] != index or abs(record["mechanical_angle_deg"]-angle) > 1e-10:
            raise ValueError("reference pose mismatch")
        queries = re.findall(r"mo_getpointvalues\(([^,]+),([^\)]+)\)", (position / "point-export.lua").read_text())
        query_coordinates = np.asarray(queries, dtype=float)
        c, s = np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))
        expected_coordinates = reference_points @ np.array([[c, s], [-s, c]])
        if query_coordinates.shape != expected_coordinates.shape or not np.allclose(query_coordinates, expected_coordinates, rtol=0, atol=1e-10):
            raise ValueError("FEMM queries do not follow the fixed rotor material points")
        mesh = np.loadtxt(position / "rotor.csv", delimiter=",", ndmin=2)
        corners = mesh[:, :6].reshape(-1, 3, 2)
        frame = FieldFrame(corners.reshape(-1, 2), np.arange(len(corners)*3).reshape(-1, 3),
                           ["rotor_core"]*len(corners), mesh[:, 6], mesh[:, 7])
        samples.append(sample_rotor_field(frame, mechanical_angle_deg=angle))
        queried_fields.append(np.loadtxt(position / "points.csv", delimiter=",", ndmin=2))
        timing.append(record["wall_s"])
        element_counts.append(record["total_elements"])
    reference_corners = samples[0].corners_mm
    if not np.allclose(reference_corners.mean(axis=1), reference_points, rtol=0, atol=1e-10):
        raise ValueError("reference integration points differ from the first mesh centroids")
    u, v = reference_corners[:, 1]-reference_corners[:, 0], reference_corners[:, 2]-reference_corners[:, 0]
    areas = 0.5e-6*np.abs(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0])
    material = RotorLossMaterial("M350-50A", "EN 10106 grade limits + cited classical lamination eddy term", M350_50A_LOSS)
    fixture_path = Path(__file__).resolve().parents[1] / protocol["fixture"]
    if hashlib.sha256(fixture_path.read_bytes()).hexdigest() != protocol["fixture_sha256"]:
        raise ValueError("reference fixture changed")
    fixture = json.loads(fixture_path.read_text())
    stack = fixture["stator"]["stack_length_mm"]*1e-3
    fields = np.array(queried_fields)
    results = []
    for stride in (4, 2, 1):
        indices = list(range(0, count, stride))
        plan = RotorSamplingPlan(protocol["speed_rpm"], len(indices))
        selected = [samples[k] for k in indices]
        reference_start = time.perf_counter()
        reference = reference_loss(fields[indices], plan.mechanical_angles_deg, areas,
                                   speed_rpm=plan.speed_rpm, stack_m=stack, coefficients=asdict(material.coefficients))
        reference_seconds = time.perf_counter() - reference_start
        high_frequency_loss = sum(h["hysteresis_W"] + h["eddy_W"] for h in reference["harmonics"] if h["frequency_Hz"] > 1000)
        reference["share_loss_above_1kHz"] = high_frequency_loss/reference["total_W"] if reference["total_W"] else 0.0
        row = {"positions": len(indices), "reference": reference, "reference_postprocess_s": reference_seconds}
        production_start = time.perf_counter()
        try:
            history = rotor_flux_history(plan, selected)
            estimate = harmonic_rotor_iron_loss(history, material=material, stack_length_m=stack)
            parts = asdict(estimate) | {"total_W": estimate.total_W}
            row["production_sampling"] = parts
            row["distinct_rotor_meshes"] = history.distinct_meshes
            row["difference_W"] = {k: parts[k]-reference[k] for k in ("hysteresis_W", "lamination_eddy_W", "total_W")}
            row["reference_agreement_pass"] = all(
                abs(row["difference_W"][k]) <= max(0.001, 0.10*reference[k]) for k in row["difference_W"]
            )
            row["sampling_status"] = "PASS"
        except ValueError as exc:
            row.update(sampling_status="FAIL", sampling_error=str(exc), reference_agreement_pass=False)
        row["production_postprocess_s"] = time.perf_counter() - production_start
        results.append(row)
    convergence = []
    for coarse, fine in zip(results, results[1:]):
        changes = {k: fine["reference"][k]-coarse["reference"][k] for k in ("hysteresis_W", "lamination_eddy_W", "total_W")}
        reference_pass = all(abs(v) <= max(0.001, 0.05*fine["reference"][k]) for k, v in changes.items())
        product_changes, product_pass = None, False
        if "production_sampling" in coarse and "production_sampling" in fine:
            product_changes = {k: fine["production_sampling"][k]-coarse["production_sampling"][k] for k in changes}
            product_pass = all(abs(v) <= max(0.001, 0.05*fine["production_sampling"][k]) for k, v in product_changes.items())
        convergence.append({"from": coarse["positions"], "to": fine["positions"], "reference_change_W": changes,
                            "production_change_W": product_changes, "reference_pass": reference_pass,
                            "production_pass": product_pass, "pass": reference_pass and product_pass})
    closure = float(np.max(np.abs(fields[-1]-fields[0])))
    closure_rms = float(np.sqrt(np.mean((fields[-1]-fields[0])**2)))
    return {
        "status": "PILOT_NOT_QUALIFIED", "scope": "one loaded SPM, FEMM fields only; no native field-solver parity or mesh qualification",
        "protocol_sha256": hashlib.sha256((directory / "protocol.json").read_bytes()).hexdigest(),
        "analysis_sources_sha256": {
            path: hashlib.sha256((Path(__file__).resolve().parents[1] / path).read_bytes()).hexdigest()
            for path in ("backend/iron_loss.py", "backend/rotor_iron_loss.py", "tools/rotor_loss_reference.py", "tools/rotor_loss_pilot_report.py")
        },
        "sampling_plan": RotorSamplingPlan(protocol["speed_rpm"], count).metadata(),
        "operating_point": {k: protocol.get(k) for k in ("fixture", "fixture_sha256", "current_peak_A", "gamma_deg", "mesh", "smoothing")},
        "material": asdict(material), "stack_m": stack, "results": results,
        "angular_convergence": convergence, "angular_gate_pass": all(c["pass"] for c in convergence),
        "mesh_gate": "NOT_RUN", "independent_endpoint_max_component_difference_T": closure,
        "independent_endpoint_rms_component_difference_T": closure_rms,
        "timing": {"field_solves_including_endpoint": count+1, "sum_position_wall_s": sum(timing),
                   "mean_position_s": float(np.mean(timing)), "min_elements": min(element_counts), "max_elements": max(element_counts)},
    }


def markdown_report(report):
    lines = [
        "# Rotor iron-loss pilot: #306", "", "Status: **PILOT_NOT_QUALIFIED**", "",
        report["scope"] + ".", "",
        "The production sampler uses the same FEMM solutions as the independent fixed-material-point queries.",
        "Agreement here checks material tracking and the harmonic calculation, not native field-solver parity or measured motor accuracy.", "",
        "| Full-turn samples | Sampler hysteresis W | Sampler eddy W | Sampler total W | Independent total W | Reference gate |",
        "|---:|---:|---:|---:|---:|:---|",
    ]
    for row in report["results"]:
        product = row.get("production_sampling")
        if product:
            lines.append(f'| {row["positions"]} | {product["hysteresis_W"]:.8g} | {product["lamination_eddy_W"]:.8g} | '
                         f'{product["total_W"]:.8g} | {row["reference"]["total_W"]:.8g} | '
                         f'{"PASS" if row["reference_agreement_pass"] else "FAIL"} |')
        else:
            lines.append(f'| {row["positions"]} | unavailable | unavailable | unavailable | {row["reference"]["total_W"]:.8g} | FAIL |')
            lines.extend(["", row["sampling_error"], ""])
    lines.extend(["", "## Convergence", ""])
    for item in report["angular_convergence"]:
        lines.append(f'- {item["from"]} → {item["to"]} samples: **{"PASS" if item["pass"] else "FAIL"}** '
                     "(hysteresis, eddy and total checked separately in both calculations).")
    lines.extend([
        "- Mesh convergence: **NOT RUN**.", "",
        f'Independent endpoint maximum B-component mismatch: {report["independent_endpoint_max_component_difference_T"]:.8g} T.', "",
        f'Independent endpoint RMS B-component mismatch: {report["independent_endpoint_rms_component_difference_T"]:.8g} T.', "",
        f'Field solves, including endpoint: {report["timing"]["field_solves_including_endpoint"]}. '
        f'Mean time per position: {report["timing"]["mean_position_s"]:.2f} s. '
        f'Sum of per-position wall times: {report["timing"]["sum_position_wall_s"]:.2f} s.', "",
        "Gates: 10% reference agreement; 5% successive convergence changes; absolute 0.001 W floor for near-zero losses.",
        "24 full-turn samples cannot resolve the mechanical order-12 slot harmonic; the Nyquist bin is excluded.", "",
        "The raw models, answers, export scripts and fields are retained beside this report. `analysis.json` contains component errors,",
        "harmonic spectra, material/operating inputs and analysis source hashes. `protocol.json` identifies the collector and FEMM binaries.", "",
        "Before expanding: review this pilot, then select angular refinements and independent mesh refinements. Public efficiency integration",
        "and the SPM/IPM, no-load/loaded, two-speed release matrix remain pending.", "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report = analyse(args.directory)
    (args.directory / "analysis.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    (args.directory / "analysis.md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "angular_gate_pass", "mesh_gate", "timing")}, indent=2))


if __name__ == "__main__":
    main()
