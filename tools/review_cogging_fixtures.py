"""Recompute the three distributed-cogging diagnoses from retained waveforms."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/benchmarks/cogging-windows-20261103"


def metrics(values):
    if len(values) != 25 or not all(math.isfinite(value) for value in values):
        raise ValueError("Expected 25 finite samples including the closing endpoint")
    period = values[:-1]
    real = sum(value * math.cos(2 * math.pi * i / 24) for i, value in enumerate(period))
    imag = -sum(value * math.sin(2 * math.pi * i / 24) for i, value in enumerate(period))
    return {"peak_to_peak_Nm": max(values) - min(values), "first_harmonic_Nm": 2 * math.hypot(real, imag) / 24,
            "mean_Nm": sum(period) / 24, "endpoint_mismatch_Nm": abs(values[-1] - values[0])}


def reference_checks(record, floor):
    return {"reference_cogging_period": "PASS" if record["endpoint_mismatch_Nm"] <= floor else "FAIL",
            "reference_cogging_mean": "PASS" if abs(record["mean_Nm"]) <= floor else "FAIL"}


def compare(candidate, reference, floor):
    gates, differences = {}, {}
    for key in ("peak_to_peak_Nm", "first_harmonic_Nm"):
        error = abs(candidate[key] - reference[key])
        limit = max(abs(reference[key]) * 0.1, floor)
        gates[key] = "PASS" if error <= limit else "YELLOW" if error <= 2 * limit else "FAIL"
        differences[key + "_error_pct"] = error / abs(reference[key]) * 100
    status = "FAIL" if "FAIL" in gates.values() else "YELLOW" if "YELLOW" in gates.values() else "PASS"
    return {"status": status, "gates": gates, **differences}


def review(folder=EVIDENCE):
    data = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    waves = json.loads((folder / "waveforms.json").read_text(encoding="utf-8"))
    by_id = {row["case_id"]: row for row in data["cases"]}
    rows = []
    for wave in waves["cases"]:
        case_id = wave["case_id"]
        if "distributed" not in case_id:
            continue
        case = by_id[case_id]
        floor = case["cogging_floor_Nm"]
        angles = wave["electrical_angle_deg"]
        expected_period = 180 * math.gcd(case["slots"], case["poles"]) / case["slots"]
        if len(angles) != 25 or any(abs(theta - i * expected_period / 24) > 1e-12 for i, theta in enumerate(angles)):
            raise ValueError("Recorded cogging grid differs from the registered period")
        baseline = metrics(wave["femm_baseline_torque_Nm"])
        refined = metrics(wave["femm_refined_torque_Nm"])
        native = {}
        for density in ("normal", "fine", "very_fine"):
            measured = metrics(wave[f"magneto2d_{density}_torque_Nm"])
            published = case["normal_native"] if density == "normal" else case["native_mesh_study"][density]["metrics"]
            for key in ("peak_to_peak_Nm", "first_harmonic_Nm", "mean_Nm"):
                if not math.isclose(measured[key], published[key], rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError(f"Stored native metric disagrees with waveform: {case_id}/{density}/{key}")
            native[density] = {"representative_mesh_elements": published["representative_mesh_elements"],
                               "vs_refined_femm": compare(measured, refined, floor)}
        rows.append({"case_id": case_id, "floor_Nm": floor,
                     "baseline_femm": {**baseline, "self_checks": reference_checks(baseline, floor)},
                     "refined_femm": {**refined, "self_checks": reference_checks(refined, floor)},
                     "native_mesh_study": native})
    if len(rows) != 3:
        raise ValueError("The retained study must contain all three distributed fixtures")
    return {"schema": "coilem.distributed_cogging_review/v1", "measured_native_commit": data["measured_commit"],
            "processing": "Direct metrics on original samples; no fitting, alignment, offset removal or rescaling",
            "native_endpoint_caveat": "Reused native endpoints are not independent closure checks; only amplitude gates are used here",
            "source_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("results.json", "waveforms.json")},
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Optional JSON destination; otherwise print to stdout")
    args = parser.parse_args()
    result = json.dumps(review(), indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result, encoding="utf-8", newline="\n")
    else:
        print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
