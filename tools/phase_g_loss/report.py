"""Audited component loss, closure, angular refinement and solver comparison."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import (
    POSITIONS,
    SPEEDS,
    areas,
    checkpoint,
    read,
    sha,
    write,
)


def independent_loss(fields, angles, area, speed, stack, coefficients):
    # Both inputs are already in their own material frame: stator axes are
    # global/static; FEMM sliding-band rotor fields are rotor-material vectors.
    from tools.rotor_loss_reference import reference_loss

    result = reference_loss(fields, angles, area, speed_rpm=speed, stack_m=stack, coefficients=coefficients, field_frame="rotor_material")
    return {key: result[key] for key in ("hysteresis_W", "lamination_eddy_W", "total_W", "mass_kg")}


def production_loss(fields, area, speed, stack, coefficients):
    from backend.iron_loss import StatorFluxHistory, SteinmetzCoefficients, harmonic_iron_loss

    # A complete mechanical turn has the mechanical base frequency. Stator
    # electrical harmonics occupy the corresponding pole-pair multiples.
    estimate = harmonic_iron_loss(
        StatorFluxHistory(fields[:, :, 0], fields[:, :, 1], area, 1),
        electrical_frequency_hz=speed / 60,
        stack_length_m=stack,
        machine_scale=1,
        coefficients=SteinmetzCoefficients(**coefficients),
    )
    return {
        "hysteresis_W": estimate.hysteresis_w,
        "lamination_eddy_W": estimate.eddy_w,
        "total_W": estimate.total_w,
        "mass_kg": estimate.stator_iron_mass_kg,
        "share_above_validated_frequency": estimate.share_above_validated_frequency,
        "share_above_validated_flux_density": estimate.share_above_validated_flux_density,
    }


def components_pass(less, more, relative=0.05, absolute=0.001):
    return {key: abs(less[key] - more[key]) <= max(absolute, relative * abs(more[key])) for key in ("hysteresis_W", "lamination_eddy_W", "total_W")}


def analyse(directory, *, reference=False):
    directory = Path(directory)
    protocol = read(directory / "protocol.json")
    if protocol["positions"] != POSITIONS or protocol["solver"] != ("femm" if reference else "magneto2d"):
        raise ValueError("Unexpected Phase G solver or sample plan")
    requested = protocol["requested_config"]
    regions = ("stator", "rotor") if protocol["case"]["rotor_supported"] else ("stator",)
    fields = {region: [] for region in regions}
    records = []
    for index in range(POSITIONS + 1):
        record = checkpoint(directory, index)
        if record is None:
            raise ValueError(f"Incomplete Phase G history: missing pose {index}")
        if "reused_source_history" in protocol:
            source = Path(protocol["reused_source_history"])
            original = source / f"position-{index:04d}"
            if (
                sha(source / "protocol.json") != protocol["reused_protocol_sha256"]
                or sha(original / "model.ans") != record["source_answer_sha256"]
                or sha(original / "position.json") != record["original_checkpoint_sha256"]
            ):
                raise ValueError("Immutable source FEMM answer changed after extraction")
        if record["protocol_sha256"] != sha(directory / "protocol.json"):
            raise ValueError("A pose belongs to a different protocol")
        if record["geometry_sha256"] != sha(directory / "material-geometry.npz"):
            raise ValueError("A pose belongs to different integration cells")
        records.append(record)
        with np.load(directory / f"position-{index:04d}" / "fields.npz") as data:
            for region in regions:
                fields[region].append(data[region])
    coeff = protocol["coefficients"]
    stack = requested["stator"]["stack_length_mm"] * 1e-3
    report = {
        "schema": "coilem.phase_g_analysis/v1",
        "case_id": protocol["case"]["id"],
        "solver": protocol["solver"],
        "protocol_sha256": sha(directory / "protocol.json"),
        "analysis_implementation_sha256": sha(__file__),
        "bound_native_protocol_sha256": protocol.get("native_protocol_sha256"),
        "rotor_status": protocol["rotor_status"],
        "rotor_unavailable_reason": protocol["rotor_unavailable_reason"],
        "model_status": "experimental",
        "numerical_history_pass": True,
        "regions": {},
        "collection_speed_rpm": 3000,
        "evaluation_speeds_rpm": list(SPEEDS),
        "independent_postprocessor": reference,
        "total_wall_s": sum(row["wall_s"] for row in records),
    }
    with np.load(directory / "material-geometry.npz") as geometry:
        for region in regions:
            values = np.asarray(fields[region])
            if values.shape != (POSITIONS + 1, len(geometry[region + "_corners"]), 2) or not np.isfinite(values).all():
                raise ValueError("Incomplete/nonfinite material fields")
            diff = values[-1] - values[0]
            closure = {"max_T": float(np.max(np.abs(diff))), "rms_T": float(np.sqrt(np.mean(diff**2)))}
            closure["pass"] = closure["max_T"] <= 1e-6 and closure["rms_T"] <= 1e-7
            region_report = {"closure": closure, "speeds": {}}
            for speed in SPEEDS:
                results = {}
                for stride in (4, 2, 1):
                    subset = values[:-1:stride]
                    angles = -360 * np.arange(len(subset)) / len(subset)
                    calculate = independent_loss if reference else production_loss
                    results[str(len(subset))] = (
                        calculate(subset, angles, areas(geometry[region + "_corners"]), speed, stack, coeff)
                        if reference
                        else calculate(subset, areas(geometry[region + "_corners"]), speed, stack, coeff)
                    )
                angular = [components_pass(results["96"], results["192"]), components_pass(results["192"], results["384"])]
                passed = closure["pass"] and all(all(step.values()) for step in angular)
                region_report["speeds"][str(speed)] = {"samples": results, "angular_steps": angular, "pass": passed}
                report["numerical_history_pass"] &= passed
            report["regions"][region] = region_report
    electrical = protocol["electrical_contract"] if reference else protocol["winding_resistance"]
    resistance = electrical["phase_resistance_ohm"]
    current = requested["solve_params"]["current_amplitude_A"]
    copper = 3 * (current / math.sqrt(2)) ** 2 * resistance
    report["copper"] = {
        "W": copper,
        "phase_resistance_ohm": resistance,
        "method": electrical["method"] if reference else "production winding_resistance and sinusoidal RMS",
        "shared_resistance_assumption": False,
    }
    report["modelled_totals"] = {}
    for speed in SPEEDS:
        parts = {"dc_copper_W": copper}
        parts.update({region + "_iron_W": values["speeds"][str(speed)]["samples"]["384"]["total_W"] for region, values in report["regions"].items()})
        known = sum(parts.values())
        report["modelled_totals"][str(speed)] = {
            "known_loss_subtotal_W": known,
            "modelled_total_loss_W": known if protocol["case"]["rotor_supported"] else None,
            "complete_for_registered_model": protocol["case"]["rotor_supported"],
            "mechanical_loss_W": 0.0,
            "component_W": parts,
            "share_of_known_loss": {name: value / known if known > 0 else 0.0 for name, value in parts.items()},
            "efficiency_status": "not_evaluated",
            "reason": "Loss histories do not independently qualify shaft torque, input power or efficiency.",
        }
    # These are numerical comparisons, never measured motor qualification.
    report["qualification_complete"] = False
    return report


def compare(native, reference):
    if native["case_id"] != reference["case_id"]:
        raise ValueError("Cannot compare different fixture/load conditions")
    if reference.get("bound_native_protocol_sha256") != native["protocol_sha256"]:
        raise ValueError("Reference belongs to a different bound native history")
    comparisons = {}
    passed = native["numerical_history_pass"] and reference["numerical_history_pass"]
    for region in native["regions"]:
        comparisons[region] = {}
        for speed in SPEEDS:
            left = native["regions"][region]["speeds"][str(speed)]["samples"]["384"]
            right = reference["regions"][region]["speeds"][str(speed)]["samples"]["384"]
            gates = components_pass(left, right, 0.10, 0.001)
            comparisons[region][str(speed)] = {"native_W": left, "femm_W": right, "component_gates": gates}
            passed &= all(gates.values())
    copper_pass = (
        abs(native["copper"]["phase_resistance_ohm"] - reference["copper"]["phase_resistance_ohm"])
        <= 0.01 * reference["copper"]["phase_resistance_ohm"]
    )
    totals = {}
    for speed in SPEEDS:
        left = native["modelled_totals"][str(speed)]["known_loss_subtotal_W"]
        right = reference["modelled_totals"][str(speed)]["known_loss_subtotal_W"]
        gate = abs(left - right) <= max(0.001, 0.1 * abs(right))
        totals[str(speed)] = {
            "native_known_subtotal_W": left,
            "femm_known_subtotal_W": right,
            "pass": gate,
            "complete_for_registered_model": native["rotor_status"] != "unavailable",
        }
        passed &= gate
    return {
        "schema": "coilem.phase_g_comparison/v1",
        "case_id": native["case_id"],
        "regions": comparisons,
        "totals": totals,
        "copper": {"native": native["copper"], "femm": reference["copper"]},
        "native_protocol_sha256": native["protocol_sha256"],
        "reference_protocol_sha256": reference["protocol_sha256"],
        "component_comparison_pass": bool(passed and copper_pass),
        "dc_copper_formula_pass": copper_pass,
        "dc_copper_uses_shared_declared_resistance": False,
        "rotor_status": native["rotor_status"],
        "overall_loss_comparison_complete": native["rotor_status"] != "unavailable",
        "status": "NUMERICAL_COMPONENT_PASS" if passed and copper_pass else "NUMERICAL_COMPONENT_FAIL",
        "model_status": "experimental",
        "qualification_complete": False,
    }


def summary(output, cases):
    """Readable progress/results without changing any raw measurement."""
    output = Path(output)
    rows = []
    for case in cases:
        for solver, label in (("native", "magneto2d"), ("femm", "femm")):
            path = output / solver / case["id"] / "analysis.json"
            if not path.exists():
                continue
            analysis = read(path)
            for speed in SPEEDS:
                rows.append(
                    {
                        "case_id": case["id"],
                        "solver": label,
                        "speed_rpm": speed,
                        "numerical_history_pass": analysis["numerical_history_pass"],
                        "rotor_status": analysis["rotor_status"],
                        **analysis["modelled_totals"][str(speed)],
                    }
                )
    write(
        output / "summary.json",
        {"schema": "coilem.phase_g_summary/v1", "rows": rows, "model_status": "experimental", "qualification_complete": False},
    )
    lines = [
        "# Phase G loss collection",
        "",
        "Experimental numerical evidence; incomplete rotor terms remain unavailable.",
        "",
        "| Case | Solver | rpm | Copper W | Stator iron W | Rotor iron W | Known subtotal W | History gates |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        parts = row["component_W"]
        rotor = f"{parts['rotor_iron_W']:.8g}" if "rotor_iron_W" in parts else "Unavailable"
        lines.append(
            f"| {row['case_id']} | {row['solver']} | {row['speed_rpm']} | {parts['dc_copper_W']:.8g} | "
            f"{parts['stator_iron_W']:.8g} | {rotor} | {row['known_loss_subtotal_W']:.8g} | "
            f"{'PASS' if row['numerical_history_pass'] else 'FAIL'} |"
        )
    (output / "benchmark_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--reference", action="store_true")
    args = parser.parse_args(argv)
    result = analyse(args.history, reference=args.reference)
    write(args.history / "analysis.json", result)
    if not result["numerical_history_pass"]:
        raise SystemExit("Phase G history gate failed; inspect analysis.json")


if __name__ == "__main__":
    main()
