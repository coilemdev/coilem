"""Independent component gates; rotor results never participate in these verdicts."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import areas, read, sha, suite, write
from tools.phase_g_loss.report import components_pass, independent_loss, production_loss
from tools.phase_g_loss.stator_contract import PROFILE, SAMPLES, SPEEDS, checkpoint, cycle_repeatability, iron_values


def evaluate(calculate):
    result = {}
    for speed in SPEEDS:
        samples = {str(n): calculate(n, speed) for n in (24, 48, 96)}
        steps = [components_pass(samples["24"], samples["48"]), components_pass(samples["48"], samples["96"])]
        result[str(speed)] = {"samples": samples, "angular_steps": steps, "angular_pass": all(all(s.values()) for s in steps)}
    return result


def native_analysis(directory):
    directory = Path(directory)
    p = read(directory / "protocol.json")
    done = read(directory / "completed.json")
    if p["profile_sha256"] != sha(PROFILE) or any(sha(directory / name) != digest for name, digest in done["sha256"].items()):
        raise ValueError("Production stator evidence or qualification profile changed")
    index = read(directory / "result-index.json")
    results = {}
    for key, ref in index["results"].items():
        if sha(directory / ref["file"]) != ref["sha256"]:
            raise ValueError("Production result changed")
        results[key] = read(directory / ref["file"])
    for path, digest in index["raw_field_sha256"].items():
        if sha(path) != digest:
            raise ValueError("Original production field artifact changed")
    summary = results["96-3000"]["summary"]
    stator = evaluate(lambda n, speed: iron_values(results[f"{n}-{speed}"]["summary"]["iron_loss"]))
    with np.load(directory / "fields.npz") as data:
        values, endpoint, area = data["stator"], data["endpoint"], data["area_m2"]
    pairs = p["requested_config"]["rotor"]["pole_count"] // 2
    stack = p["requested_config"]["stator"]["stack_length_mm"] * 1e-3
    def calculate(v, speed):
        r = production_loss(v, area, speed * pairs, stack, p["coefficients"])
        return {k: r[k] for k in ("hysteresis_W", "lamination_eddy_W", "total_W")}
    repeat = cycle_repeatability(values, endpoint, area, calculate)
    return {"case_id": p["case_id"], "solver": "production_magneto2d", "protocol_sha256": sha(directory / "protocol.json"),
            "stator": stator, "cycle_repeatability": repeat, "public_api_exercised": True,
            "copper": {"phase_resistance_ohm": summary["winding_resistance"]["phase_resistance_ohm"],
                       "W": summary["loss_breakdown"]["copper_loss_W"]},
            "history_pass": repeat["pass"] and all(s["angular_pass"] for s in stator.values()),
            "rotor_gates_used": False, "model_status": "experimental"}


def reference_analysis(directory):
    directory = Path(directory)
    p = read(directory / "protocol.json")
    if p["profile_sha256"] != sha(PROFILE):
        raise ValueError("Reference qualification profile changed")
    records = [checkpoint(directory, i) for i in range(SAMPLES + 1)]
    if any(record is None for record in records):
        raise ValueError("Reference electrical cycle incomplete")
    with np.load(directory / "material-geometry.npz") as g:
        area = areas(g["stator_corners"])
    values = []
    for i in range(SAMPLES + 1):
        with np.load(directory / f"position-{i:04d}" / "fields.npz") as data:
            values.append(data["stator"])
    values = np.asarray(values)
    if values.shape != (SAMPLES + 1, len(area), 2) or not np.isfinite(values).all():
        raise ValueError("Reference stator integration cells changed")
    requested = p["requested_config"]
    pairs = requested["rotor"]["pole_count"] // 2
    stack = requested["stator"]["stack_length_mm"] * 1e-3
    def calculate(v, speed):
        return {k: value for k, value in independent_loss(v, -360 * np.arange(len(v)) / len(v), area,
                 speed * pairs, stack, p["coefficients"]).items() if k != "mass_kg"}
    stator = evaluate(lambda n, speed: calculate(values[:-1:96 // n], speed))
    repeat = cycle_repeatability(values[:-1], values[-1], area, calculate)
    resistance = p["electrical_contract"]["phase_resistance_ohm"]
    copper = 3 * (requested["solve_params"]["current_amplitude_A"] / math.sqrt(2))**2 * resistance
    return {"case_id": p["case_id"], "solver": "femm_independent_dft", "protocol_sha256": sha(directory / "protocol.json"),
            "native_protocol_sha256": p["native_protocol_sha256"], "stator": stator, "cycle_repeatability": repeat,
            "copper": {"phase_resistance_ohm": resistance, "W": copper},
            "history_pass": repeat["pass"] and all(s["angular_pass"] for s in stator.values()),
            "new_field_solves": sum(bool(r["new_field_solve"]) for r in records),
            "reused_poses": sum(not r["new_field_solve"] for r in records), "rotor_gates_used": False}


def compare(native, reference):
    if native["case_id"] != reference["case_id"] or native["protocol_sha256"] != reference["native_protocol_sha256"]:
        raise ValueError("Stator comparison inputs differ")
    stator = {}
    passed = native["history_pass"] and reference["history_pass"]
    for speed in SPEEDS:
        left, right = native["stator"][str(speed)]["samples"]["96"], reference["stator"][str(speed)]["samples"]["96"]
        gates = components_pass(left, right, .10, .001)
        stator[str(speed)] = {"native_W": left, "femm_W": right, "gates": gates}
        passed &= all(gates.values())
    copper_gates = {key: abs(native["copper"][key] - reference["copper"][key]) <= max(1e-12, .01 * abs(reference["copper"][key]))
                    for key in ("phase_resistance_ohm", "W")}
    return {"schema": "coilem.stator_dc_copper_comparison/v1", "case_id": native["case_id"], "stator": stator,
            "native_protocol_sha256": native["protocol_sha256"], "reference_protocol_sha256": reference["protocol_sha256"],
            "stator_reference_pass": bool(passed), "dc_copper_reference_pass": all(copper_gates.values()),
            "reference_checks_pass": bool(passed and all(copper_gates.values())),
            "copper": {"native": native["copper"], "femm_geometry_reference": reference["copper"], "gates": copper_gates},
            "native_repeatability": native["cycle_repeatability"], "reference_repeatability": reference["cycle_repeatability"],
            "rotor_loss_status": "experimental", "rotor_gates_used": False, "model_status": "experimental",
            "full_motor_efficiency_qualified": False, "new_reference_field_solves": reference["new_field_solves"],
            "reused_reference_poses": reference["reused_poses"]}


def report(root):
    root = Path(root)
    lines = ["# Stator iron and DC copper qualification for 5.9", "", "Numerical reference checks only. Rotor loss remains experimental.", "",
             "| Case | Stator/FEMM | DC copper | Native cycle | Reference cycle |", "|---|---|---|---|---|"]
    results = []
    for case in suite()["cases"]:
        cid = case["id"]
        n, f = root / "native" / cid, root / "femm" / cid
        if not (n / "completed.json").exists():
            lines.append(f"| {cid} | Pending | Pending | Pending | Pending |")
            continue
        native = native_analysis(n)
        write(n / "analysis.json", native)
        if not all((f / f"position-{i:04d}" / "position.json").exists() for i in range(97)):
            lines.append(f"| {cid} | Pending | Pending | {'PASS' if native['history_pass'] else 'FAIL'} | Pending |")
            continue
        ref = reference_analysis(f)
        write(f / "analysis.json", ref)
        comparison = compare(native, ref)
        write(root / "reports" / (cid + ".json"), comparison)
        results.append(comparison)
        def label(value):
            return "PASS" if value else "FAIL"
        lines.append(f"| {cid} | {label(comparison['stator_reference_pass'])} | {label(comparison['dc_copper_reference_pass'])} | "
                     f"{label(native['history_pass'])} | {label(ref['history_pass'])} |")
    complete = len(results) == len(suite()["cases"]) and all(r["reference_checks_pass"] for r in results)
    write(root / "summary.json", {"schema": "coilem.stator_dc_copper_summary/v1", "cases": results,
          "numerical_reference_qualification_complete": complete, "rotor_loss_status": "experimental",
          "model_status": "experimental", "full_motor_efficiency_qualified": False})
    (root / "qualification_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    report(parser.parse_args().out)
