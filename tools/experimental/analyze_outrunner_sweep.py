"""Compare exact matched requests and emit torque/linkage/BEMF curves and receipts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from backend.experimental.outrunner_sweep import PERIOD_DEG, bemf, fundamental


def read_results(root: Path) -> tuple[dict, dict, dict]:
    manifest = json.loads((root/"manifest.json").read_text())
    records, hashes = {}, {"manifest.json": hashlib.sha256((root/"manifest.json").read_bytes()).hexdigest()}
    for case in manifest["cases"]:
        path = root/case["id"]/"result.json"
        if not path.exists():
            continue
        raw = path.read_bytes()
        result = json.loads(raw)
        if result["case"] != case:
            raise ValueError("Solved result does not match its declared request")
        if result["status"] == "COMPLETE":
            records[case["id"]] = result
            hashes[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
    return manifest, records, hashes


def error_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict:
    peak = float(np.max(abs(reference)))
    delta = candidate-reference
    return {"rmse": float(np.sqrt(np.mean(delta**2))), "max_absolute_error": float(np.max(abs(delta))),
            "nrmse_over_reference_peak": float(np.sqrt(np.mean(delta**2))/peak) if peak else None,
            "relative_L2": float(np.linalg.norm(delta)/np.linalg.norm(reference)) if peak else None}


def fundamental_error(reference: np.ndarray, candidate: np.ndarray) -> dict:
    ref, cand = fundamental(reference), fundamental(candidate)
    amplitude = np.asarray(cand["peak"])/np.asarray(ref["peak"])-1
    phase = (np.asarray(cand["cosine_phase_deg"])-np.asarray(ref["cosine_phase_deg"])+180) % 360-180
    return {"reference": ref, "candidate": cand, "relative_peak_error": amplitude.tolist(), "phase_error_electrical_deg": phase.tolist()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--femm", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    reference_manifest, reference, reference_hashes = read_results(args.femm)
    candidate_manifest, candidate, candidate_hashes = read_results(args.native)
    report = {"status": "DIAGNOSTIC_ONLY", "reference_count": len(reference), "candidate_count": len(candidate),
              "reference_requested": len(reference_manifest["cases"]), "candidate_requested": len(candidate_manifest["cases"]),
              "reference_root": str(args.femm.resolve()), "candidate_root": str(args.native.resolve()),
              "input_sha256": {"reference": reference_hashes, "candidate": candidate_hashes},
              "material_law_parity": "UNVERIFIED", "speed_rpm": 1000, "angle_positive": "CCW mechanical",
              "emf_sign_convention": "induced e=-omega_mechanical*d(lambda)/d(theta_mechanical)", "curves": {}}
    points = []
    for case_id in sorted(reference.keys() & candidate.keys()):
        ref, cand = reference[case_id], candidate[case_id]
        if ref["case"] != cand["case"]:
            raise ValueError("Candidate and reference must have identical unadjusted requests")
        points.append({"case": ref["case"], "reference_torque_Nm": ref["outer_rotor_torque_Nm"],
                       "candidate_torque_Nm": cand["outer_rotor_torque_Nm"],
                       "torque_error_Nm": cand["outer_rotor_torque_Nm"]-ref["outer_rotor_torque_Nm"],
                       "linkage_error_Wb": (np.asarray(cand["phase_linkage_Wb"])-ref["phase_linkage_Wb"]).tolist()})
    report["matched_points"] = points
    # The moving-boundary sign is checked against actual physical motion,
    # without changing either convention to improve a match.
    orientation = []
    for case in reference_manifest["cases"]:
        if case["family"] == "orientation" and case["reference_model"] == "full":
            other = case["id"].replace("_full", "_sliding")
            if case["id"] in reference and other in reference:
                full, sliding = reference[case["id"]], reference[other]
                flux_difference = np.asarray(full["phase_linkage_Wb"])-sliding["phase_linkage_Wb"]
                orientation.append({"angle_ccw_deg": case["angle_ccw_deg"], "physical_rotation_torque_Nm": full["outer_rotor_torque_Nm"],
                                    "sliding_outer_angle_torque_Nm": sliding["outer_rotor_torque_Nm"],
                                    "difference_Nm": sliding["outer_rotor_torque_Nm"]-full["outer_rotor_torque_Nm"],
                                    "max_linkage_difference_Wb": float(np.max(abs(flux_difference)))})
    report["reference_motion_controls"] = orientation
    for family in ("loaded", "noload"):
        cases = sorted([x for x in reference_manifest["cases"] if x["family"] == family], key=lambda x: x["angle_ccw_deg"])
        ids = [x["id"] for x in cases]
        if not cases or not all(key in reference and key in candidate for key in ids):
            report["curves"][family] = {"status": "INCOMPLETE", "missing_reference": [key for key in ids if key not in reference],
                                         "missing_candidate": [key for key in ids if key not in candidate]}
            continue
        angles = np.array([x["angle_ccw_deg"] for x in cases])
        if not np.allclose(np.diff(angles), PERIOD_DEG/(len(angles)-1), atol=1e-12) or angles[0] != 0 or not math.isclose(angles[-1], PERIOD_DEG):
            raise ValueError("Curve must cover the complete uniform electrical period with an independently solved endpoint")
        torque_ref = np.array([reference[key]["outer_rotor_torque_Nm"] for key in ids])
        torque_cand = np.array([candidate[key]["outer_rotor_torque_Nm"] for key in ids])
        flux_ref = np.array([reference[key]["phase_linkage_Wb"] for key in ids])
        flux_cand = np.array([candidate[key]["phase_linkage_Wb"] for key in ids])
        curve = {"status": "COMPLETE_DIAGNOSTIC", "unique_samples": len(ids)-1, "period_mechanical_deg": PERIOD_DEG,
                 "currents_A": cases[0]["currents_A"], "torque": error_metrics(torque_ref[:-1], torque_cand[:-1]),
                 "linkage": error_metrics(flux_ref[:-1], flux_cand[:-1]),
                 "torque_reference_range_Nm": [float(torque_ref.min()), float(torque_ref.max())],
                 "torque_candidate_range_Nm": [float(torque_cand.min()), float(torque_cand.max())],
                 "reference_torque_closure_Nm": float(torque_ref[-1]-torque_ref[0]),
                 "candidate_torque_closure_Nm": float(torque_cand[-1]-torque_cand[0]),
                 "reference_linkage_closure_Wb": (flux_ref[-1]-flux_ref[0]).tolist(),
                 "candidate_linkage_closure_Wb": (flux_cand[-1]-flux_cand[0]).tolist()}
        extra_columns, extra_arrays = [], []
        if family == "noload":
            e_ref, e_cand = bemf(flux_ref[:-1]), bemf(flux_cand[:-1])
            ll_ref, ll_cand = e_ref-np.roll(e_ref, -1, axis=1), e_cand-np.roll(e_cand, -1, axis=1)
            curve["phase_bemf"] = {**error_metrics(e_ref, e_cand), "fundamental": fundamental_error(e_ref, e_cand)}
            curve["line_to_line_bemf"] = {**error_metrics(ll_ref, ll_cand), "fundamental": fundamental_error(ll_ref, ll_cand)}
            curve["bemf_derivative_sensitivity"] = {"reference_spectral_vs_central4": error_metrics(e_ref, bemf(flux_ref[:-1], method="central4")),
                                                    "candidate_spectral_vs_central4": error_metrics(e_cand, bemf(flux_cand[:-1], method="central4"))}
            curve["cogging_reference_mean_Nm"] = float(torque_ref[:-1].mean())
            curve["cogging_candidate_mean_Nm"] = float(torque_cand[:-1].mean())
            curve["cogging_resolution"] = "Initial electrical grid only; dedicated short-period refinement is still required"
            for prefix, array in (("femm_emf", e_ref), ("magneto_emf", e_cand), ("femm_line_emf", ll_ref), ("magneto_line_emf", ll_cand)):
                extra_columns.extend(prefix+"_"+phase+"_V" for phase in ("A", "B", "C"))
                extra_arrays.append(np.vstack((array, np.full((1, 3), np.nan))))
        columns = ["angle_mechanical_ccw_deg", "angle_electrical_deg", "femm_outer_torque_Nm", "magneto_outer_torque_Nm"]
        columns += [prefix+"_"+phase+"_Wb" for prefix in ("femm_linkage", "magneto_linkage") for phase in "ABC"]
        columns += extra_columns
        matrix = np.column_stack((angles, angles*7, torque_ref, torque_cand, flux_ref, flux_cand, *extra_arrays))
        with (args.out/(family+".csv")).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            for row in matrix:
                writer.writerow([float(x) if math.isfinite(x) else "" for x in row])
        report["curves"][family] = curve
    (args.out/"summary.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    concise = {key: value for key, value in report.items() if key not in ("input_sha256", "matched_points")}
    print(json.dumps(concise, indent=2))


if __name__ == "__main__":
    main()
