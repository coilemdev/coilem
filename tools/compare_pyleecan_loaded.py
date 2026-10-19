"""Summarize loaded Prius torque against Pyleecan's Yang-2013 reference curve."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ANGLES = list(range(60, 181, 10))
REFERENCE_NM = [79, 125, 160, 192, 237, 281, 319, 343, 353, 332, 266, 164, 22]
REFERENCE_URL = (
    "https://github.com/Eomys/pyleecan/blob/e474b1e7944a4a90f2c3588025db27f752d9944e/"
    "Tests/Validation/Electrical/test_EEC_PMSM.py"
)


def dq_torque(row):
    """Peak-valued Park transform, consistent with Pyleecan's RMS dq convention."""
    theta = np.radians(row["time_electrical_angle_deg"] + np.array([0, -120, 120]))
    flux = np.asarray(row["phase_linkage_Wb"])
    current = np.asarray(row["phase_current_A"])
    ld, lq = 2 / 3 * np.dot(flux, np.cos(theta)), -2 / 3 * np.dot(flux, np.sin(theta))
    id_, iq = 2 / 3 * np.dot(current, np.cos(theta)), -2 / 3 * np.dot(current, np.sin(theta))
    return float(1.5 * 4 * (ld * iq - lq * id_))


def summarize(folder):
    registration = json.loads((folder / "registration.json").read_text())
    completion = json.loads((folder / "completion.json").read_text())
    rows = json.loads((folder / "waveform.json").read_text())
    expected = registration.get("expected_poses", registration.get("points", 0) * len(registration.get("current_angles_deg", [])))
    if len(rows) != expected or completion.get("complete") is False:
        raise ValueError("A complete actual-pose sweep is required")
    counts = {phi: sum(r["current_angle_deg"] == phi for r in rows) for phi in ANGLES}
    if len(set(counts.values())) != 1 or min(counts.values()) < 1:
        raise ValueError("All thirteen current angles must have equal complete pose grids")
    n = counts[60]
    curve = []
    for phi, ref in zip(ANGLES, REFERENCE_NM, strict=True):
        selected = sorted((r for r in rows if r["current_angle_deg"] == phi), key=lambda r: r["index"])
        if [r["index"] for r in selected] != list(range(n)):
            raise ValueError("Duplicate or missing rotor poses")
        expected_grid = -np.arange(n) * 180 / n
        if not np.allclose([r["time_electrical_angle_deg"] for r in selected], expected_grid, atol=1e-8):
            raise ValueError("A uniform 180-electrical-degree grid is required")
        for row in selected:
            theta = np.radians(row["time_electrical_angle_deg"] + phi + np.array([0, -120, 120]))
            if not np.allclose(row["phase_current_A"], 250 * np.cos(theta), atol=1e-7):
                raise ValueError("Phase currents disagree with the published RMS/phase-angle convention")
        torque = np.array([r["torque_Nm"] for r in selected])
        avg = float(torque.mean())
        curve.append({
            "current_angle_deg": phi, "reference_torque_Nm": ref,
            "mean_stress_torque_Nm": avg, "mean_dq_torque_Nm": float(np.mean([dq_torque(r) for r in selected])),
            "reference_error_Nm": avg - ref, "reference_error_pct": 100 * (avg / ref - 1),
            "min_pose_torque_Nm": float(torque.min()), "max_pose_torque_Nm": float(torque.max()),
            "pose_torque_Nm": torque.tolist(),
        })
    errors = np.array([r["reference_error_Nm"] for r in curve])
    peak = max(curve, key=lambda r: r["mean_stress_torque_Nm"])
    metrics = {
        "peak_mean_stress_Nm": peak["mean_stress_torque_Nm"], "peak_current_angle_deg": peak["current_angle_deg"],
        "peak_reference_Nm": max(REFERENCE_NM), "peak_error_pct": 100 * (peak["mean_stress_torque_Nm"] / max(REFERENCE_NM) - 1),
        "curve_RMSE_Nm": float(np.sqrt(np.mean(errors**2))),
        "curve_RMSE_normalized_to_reference_peak_pct": float(100 * np.sqrt(np.mean(errors**2)) / max(REFERENCE_NM)),
        "single_test_60deg_reference_Nm": 82, "single_test_60deg_tolerance_relative": .1,
        "single_test_60deg_pass": bool(abs(curve[0]["mean_stress_torque_Nm"] / 82 - 1) <= .1),
    }
    native = "expected_poses" in registration
    if native:
        metrics["maximum_nonlinear_residual"] = max(r["nonlinear_residual"] for r in rows)
    if rows and "relative_nodal_Az" in rows[0]:
        metrics.update(
            maximum_relative_nodal_Az=max(r["relative_nodal_Az"] for r in rows),
            maximum_relative_phase_linkage=max(r["relative_phase_linkage"] for r in rows),
            maximum_relative_FEMM_linkage_extraction=max(r["relative_FEMM_linkage_extraction"] for r in rows),
        )
    compact_rows = [{k: v for k, v in row.items() if k != "ampere_turn_audit"} for row in rows]
    sampling_change = []
    if n % 2 == 0:
        for phi in ANGLES:
            selected = [r for r in rows if r["current_angle_deg"] == phi]
            coarse = np.mean([r["torque_Nm"] for r in selected if r["index"] % 2 == 0])
            fine = np.mean([r["torque_Nm"] for r in selected])
            sampling_change.append({"current_angle_deg": phi, "coarse_mean_Nm": float(coarse),
                                    "fine_mean_Nm": float(fine), "change_Nm": float(fine - coarse)})
    return {"registration": registration, "registration_sha256": hashlib.sha256((folder / "registration.json").read_bytes()).hexdigest(),
            "actual_pose_count": len(rows), "poses_per_current_angle": n, "curve": curve, "metrics": metrics,
            "pose_evidence": compact_rows, "sampling_coarsening": sampling_change}


def compare(femm, native, corrected):
    models = {name: summarize(path) for name, path in [("FEMM_published", femm), ("Magneto_published", native), ("Magneto_corrected", corrected)]}
    source_identity = models["FEMM_published"]["registration_sha256"]
    for name in ("Magneto_published", "Magneto_corrected"):
        if models[name]["registration"]["FEMM_registration_sha256"] != source_identity:
            raise ValueError("Native sweep uses a different FEMM operating-point registration")
    a = np.array([r["mean_stress_torque_Nm"] for r in models["FEMM_published"]["curve"]])
    b = np.array([r["mean_stress_torque_Nm"] for r in models["Magneto_published"]["curve"]])
    parity = {
        "maximum_mean_torque_difference_Nm": float(np.max(np.abs(a-b))),
        "curve_relative_L2_difference": float(np.linalg.norm(a-b) / np.linalg.norm(a)),
        "maximum_mean_torque_difference_normalized_to_peak": float(np.max(np.abs(a-b)) / np.max(np.abs(a))),
    }
    m = models["Magneto_published"]["metrics"]
    checks = {
        "same_mesh_nodal_Az": m["maximum_relative_nodal_Az"] < .005,
        "same_mesh_phase_linkage": m["maximum_relative_phase_linkage"] < .005,
        "same_mesh_mean_torque": parity["maximum_mean_torque_difference_normalized_to_peak"] < .02,
        "native_nonlinear_residual": all(v["metrics"].get("maximum_nonlinear_residual", 0) < 1e-8 for v in models.values()),
        "all_model_sampling_coarsening": all(
            max(abs(r["change_Nm"]) for r in v["sampling_coarsening"]) / max(REFERENCE_NM) < .01 for v in models.values()
        ),
    }
    return {"schema": "coilem.pyleecan_prius_loaded/v1", "conditions": {"speed_rpm": 2000, "phase_current_peak_A": 250,
            "phase_current_rms_A": float(250 / np.sqrt(2)), "magnet_temperature_C": 60, "stack_mm": 83.82},
            "reference": {"url": REFERENCE_URL,
                          "attribution": "Yang, Krishnamurthy and Brown, IEMDC 2013, as transcribed in Pyleecan's validation test",
                          "torque_curve_is_not_independently_verified_hardware": True,
                          "single_point_test": "82 Nm +/-10% at 60 degrees; the 13-angle reference vector separately starts at 79 Nm"},
            "models": models, "same_model_solver_parity": parity, "numerical_checks": checks,
            "all_numerical_checks_pass": all(checks.values())}


def sampling_control(coarse, refined):
    """Compare actual solved pose grids, including the near-peak loaded point."""
    coarse_rows = json.loads((coarse / "waveform.json").read_text())
    fine_rows = json.loads((refined / "waveform.json").read_text())
    registration = json.loads((refined / "registration.json").read_text())
    completion = json.loads((refined / "completion.json").read_text())
    expected = registration.get("expected_poses", registration.get("points", 0) * len(registration.get("current_angles_deg", [])))
    if len(fine_rows) != expected or completion.get("complete") is False:
        raise ValueError("Incomplete refined sampling control")
    rows = []
    for phi in sorted({r["current_angle_deg"] for r in fine_rows}):
        old = [r for r in coarse_rows if r["current_angle_deg"] == phi]
        new = sorted((r for r in fine_rows if r["current_angle_deg"] == phi), key=lambda r: r["index"])
        if not old or len(new) != 2 * len(old) or [r["index"] for r in new] != list(range(len(new))):
            raise ValueError("Refinement must double a complete pose grid")
        expected_time = -np.arange(len(new)) * 180 / len(new)
        if not np.allclose([r["time_electrical_angle_deg"] for r in new], expected_time, atol=1e-8):
            raise ValueError("Nonuniform refined grid")
        a, b = float(np.mean([r["torque_Nm"] for r in old])), float(np.mean([r["torque_Nm"] for r in new]))
        rows.append({"current_angle_deg": phi, "coarse_poses": len(old), "refined_poses": len(new),
                     "coarse_mean_Nm": a, "refined_mean_Nm": b, "change_Nm": b-a,
                     "change_normalized_to_reference_peak": abs(b-a) / max(REFERENCE_NM)})
    checks = {"mean_sampling_change": all(r["change_normalized_to_reference_peak"] < .01 for r in rows)}
    if fine_rows and "nonlinear_residual" in fine_rows[0]:
        checks["native_nonlinear_residual"] = max(r["nonlinear_residual"] for r in fine_rows) < 1e-8
    if fine_rows and "relative_nodal_Az" in fine_rows[0]:
        checks["same_mesh_nodal_Az"] = max(r["relative_nodal_Az"] for r in fine_rows) < .005
        checks["same_mesh_phase_linkage"] = max(r["relative_phase_linkage"] for r in fine_rows) < .005
    return {"rows": rows, "actual_refined_pose_count": len(fine_rows),
            "registration_sha256": hashlib.sha256((refined / "registration.json").read_bytes()).hexdigest(),
            "checks": checks, "pass": all(checks.values()),
            "pose_evidence": [{k: v for k, v in r.items() if k != "ampere_turn_audit"} for r in fine_rows]}


def plot(data, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True, constrained_layout=True)
    axes[0].plot(ANGLES, REFERENCE_NM, "ko-", label="Published Yang-2013 reference in Pyleecan")
    for name, model in data["models"].items():
        values = [r["mean_stress_torque_Nm"] for r in model["curve"]]
        axes[0].plot(ANGLES, values, marker=".", label=name.replace("_", " "))
        axes[1].plot(ANGLES, np.array(values) - REFERENCE_NM, marker=".", label=name.replace("_", " "))
    axes[0].set(ylabel="Mean torque [Nm]", title="Prius loaded torque: 250 A peak, 2,000 rpm, magnets at 60°C")
    axes[1].set(ylabel="Difference from published curve [Nm]", xlabel="Pyleecan current angle [electrical degrees]")
    axes[1].axhline(0, color="black", lw=.8)
    for ax in axes:
        ax.grid(alpha=.25)
    axes[0].legend(fontsize=8)
    fig.savefig(path)
    plt.close(fig)
    if path.suffix.lower() == ".svg":
        path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n",
                        encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--femm", type=Path, required=True)
    ap.add_argument("--native", type=Path, required=True)
    ap.add_argument("--corrected", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--plot", type=Path)
    ap.add_argument("--femm-refined", type=Path)
    ap.add_argument("--native-refined", type=Path)
    ap.add_argument("--corrected-refined", type=Path)
    args = ap.parse_args()
    data = compare(args.femm, args.native, args.corrected)
    if any([args.femm_refined, args.native_refined, args.corrected_refined]):
        if not all([args.femm_refined, args.native_refined, args.corrected_refined]):
            ap.error("Supply all three refined control directories")
        data["sampling_refinement"] = {
            name: sampling_control(old, new) for name, old, new in [
                ("FEMM_published", args.femm, args.femm_refined),
                ("Magneto_published", args.native, args.native_refined),
                ("Magneto_corrected", args.corrected, args.corrected_refined),
            ]
        }
        data["numerical_checks"]["additional_sampling_refinement"] = all(v["pass"] for v in data["sampling_refinement"].values())
        reference_rows = data["sampling_refinement"]["FEMM_published"]["rows"]
        native_rows = data["sampling_refinement"]["Magneto_published"]["rows"]
        delta = max(abs(a["refined_mean_Nm"] - b["refined_mean_Nm"]) for a, b in zip(reference_rows, native_rows, strict=True))
        data["refined_solver_parity"] = {"maximum_mean_torque_difference_Nm": delta}
        data["numerical_checks"]["refined_same_model_mean_torque"] = delta / max(r["refined_mean_Nm"] for r in reference_rows) < .02
        data["all_numerical_checks_pass"] = all(data["numerical_checks"].values())
    args.out.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.plot:
        plot(data, args.plot)
    print(json.dumps({k: v["metrics"] for k, v in data["models"].items()}, indent=2))


if __name__ == "__main__":
    main()
