"""Assemble a matched Pyleecan/FEMM and Magneto no-load reference comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def waveform_metrics(linkage, speed_rpm: float = 3000, pole_pairs: int = 4) -> dict:
    flux = np.asarray(linkage, dtype=float)
    if flux.ndim != 2 or flux.shape[1] != 3 or len(flux) < 12 or not np.isfinite(flux).all():
        raise ValueError("A finite, complete three-phase linkage cycle is required")
    if speed_rpm <= 0 or pole_pairs <= 0:
        raise ValueError("Speed and pole-pair count must be positive")
    n = len(flux)
    omega = speed_rpm * 2 * math.pi / 60 * pole_pairs
    dt = 2 * math.pi / n / omega
    voltage = -(np.roll(flux, -1, axis=0) - np.roll(flux, 1, axis=0)) / (2 * dt)
    ll = voltage - np.roll(voltage, -1, axis=1)
    spectrum = 2 * np.abs(np.fft.rfft(ll, axis=0)) / n
    flux_fund = 2 * np.abs(np.fft.rfft(flux, axis=0)[1]) / n
    return {
        "speed_rpm": speed_rpm,
        "pole_pairs": pole_pairs,
        "positions": n,
        "phase_linkage_Wb": flux.tolist(),
        "phase_voltage_V": voltage.tolist(),
        "line_voltage_AB_BC_CA_V": ll.tolist(),
        "LL_AB_RMS_V": float(np.sqrt(np.mean(ll[:, 0] ** 2))),
        "LL_AB_sampled_peak_V": float(np.max(np.abs(ll[:, 0]))),
        "LL_AB_fundamental_RMS_V": float(spectrum[1, 0] / math.sqrt(2)),
        "LL_RMS_by_pair_V": np.sqrt(np.mean(ll**2, axis=0)).tolist(),
        "phase_flux_fundamental_Wb": flux_fund.tolist(),
        "Ke_phase_peak_V_per_mech_rad_s_from_flux": (pole_pairs * flux_fund).tolist(),
        "voltage_derivative": "Periodic central difference on the same complete electrical-angle grid for both solvers",
    }


def compare(femm: Path, native: Path) -> dict:
    reg = json.loads((femm / "registration.json").read_text())
    if reg.get("electrical_range_deg", 360) != 360:
        raise ValueError("This comparison requires a complete actual electrical cycle; use the tutorial comparison for an explicit half-cycle")
    nr = json.loads((native / "registration.json").read_text())
    f = json.loads((femm / "waveform.json").read_text())
    m = json.loads((native / "waveform.json").read_text())
    n = reg["points"]
    if (
        len(f) != n
        or len(m) != n
        or not (femm / "completion.json").exists()
        or not (native / "completion.json").exists()
        or not json.loads((native / "completion.json").read_text()).get("complete")
    ):
        raise ValueError("Both actual field sweeps must be complete before comparison")
    if reg["phase_current_A"] != [0, 0, 0] or nr["FEMM_registration_sha256"] != digest(femm / "registration.json"):
        raise ValueError("Zero-current or reference identity mismatch")
    for i, (fr, mr) in enumerate(zip(f, m, strict=True)):
        expected = i * 360 / n
        if (
            fr["index"] != i
            or mr["index"] != i
            or not math.isclose(fr["electrical_angle_deg"], expected)
            or mr["electrical_angle_deg"] != fr["electrical_angle_deg"]
        ):
            raise ValueError("Actual position order/angle grids differ")
        if any(abs(c[0]) > 1e-15 for c in fr["circuit_properties"]):
            raise ValueError("Nonzero FEMM current")
        if mr["source_FEMM_ans_sha256"] != fr["ans_sha256"]:
            raise ValueError("Native comparison used a different FEMM pose")
    speed_rpm = reg["speed_rpm"]
    fm = waveform_metrics([r["phase_linkage_Wb"] for r in f], speed_rpm=speed_rpm)
    mm = waveform_metrics([r["phase_linkage_Wb"] for r in m], speed_rpm=speed_rpm)
    limits = nr["limits"]
    stats = {
        "LL_AB_RMS_relative_error": mm["LL_AB_RMS_V"] / fm["LL_AB_RMS_V"] - 1,
        "LL_AB_sampled_peak_relative_error": mm["LL_AB_sampled_peak_V"] / fm["LL_AB_sampled_peak_V"] - 1,
        "LL_AB_waveform_relative_L2": float(
            np.linalg.norm(np.array(mm["line_voltage_AB_BC_CA_V"])[:, 0] - np.array(fm["line_voltage_AB_BC_CA_V"])[:, 0])
            / np.linalg.norm(np.array(fm["line_voltage_AB_BC_CA_V"])[:, 0])
        ),
        "max_pose_phase_linkage_relative_error": max(r["linkage_relative_difference"] for r in m),
        "max_FEMM_circuit_vs_Az_extraction_relative_error": max(r["FEMM_extraction_relative_difference"] for r in m),
        "max_pose_nodal_Az_relative_error": max(r["relative_nodal_Az_difference"] for r in m),
        "max_native_nonlinear_residual": max(r["nonlinear_residual"] for r in m),
    }
    checks = {
        "RMS_parity": abs(stats["LL_AB_RMS_relative_error"]) <= limits["relative_LL_RMS"],
        "sampled_peak_parity": abs(stats["LL_AB_sampled_peak_relative_error"]) <= limits["relative_LL_sampled_peak"],
        "phase_linkage_parity": stats["max_pose_phase_linkage_relative_error"] <= limits["relative_phase_linkage"],
        "FEMM_extraction": stats["max_FEMM_circuit_vs_Az_extraction_relative_error"] <= limits["relative_FEMM_extraction"],
        "native_convergence": stats["max_native_nonlinear_residual"] <= limits["native_nonlinear_residual"],
    }
    target_path = ROOT / "docs/hardware-validation/ornl-prius-2004/target-back-emf.json"
    targets = json.loads(target_path.read_text())["rows"]
    models = []
    for label, metrics in (("Published Pyleecan / FEMM", fm), ("Same Pyleecan model / Magneto", mm)):
        rows = []
        for t in targets:
            speed = t["motor_shaft_rpm"]
            rms = metrics["LL_AB_RMS_V"] * speed / speed_rpm
            peak = metrics["LL_AB_sampled_peak_V"] * speed / speed_rpm
            rows.append(
                {
                    "motor_shaft_rpm": speed,
                    "ORNL_LL_RMS_V": t["back_emf_ll_rms_V"],
                    "model_LL_RMS_V": rms,
                    "ORNL_LL_peak_V": t["back_emf_ll_peak_V"],
                    "model_LL_sampled_peak_V": peak,
                    "RMS_error_pct": (rms / t["back_emf_ll_rms_V"] - 1) * 100,
                    "sampled_peak_error_pct": (peak / t["back_emf_ll_peak_V"] - 1) * 100,
                }
            )
        models.append(
            {
                "label": label,
                "metrics": metrics,
                "ORNL_rows": rows,
                "mean_ORNL_RMS_error_pct": float(np.mean([r["RMS_error_pct"] for r in rows])),
                "mean_ORNL_sampled_peak_error_pct": float(np.mean([r["sampled_peak_error_pct"] for r in rows])),
            }
        )
    history_path = ROOT / "docs/hardware-validation/ornl-prius-2004/turns-sweep-results.json"
    history = json.loads(history_path.read_text())
    history_bias = {
        model["name"]: next(c for c in model["cases"] if c["turns_per_coil"] == 9)["rms_error"]["mean_signed_pct"] for model in history["models"]
    }
    return {
        "schema": "coilem.pyleecan_prius_bemf/v1",
        "experimental": True,
        "qualified": False,
        "reference_parity_status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "limits": limits,
        "comparison": stats,
        "pose_controls": [
            {
                key: row[key]
                for key in (
                    "index",
                    "electrical_angle_deg",
                    "source_FEMM_ans_sha256",
                    "mesh_sha256",
                    "report_sha256",
                    "linkage_relative_difference",
                    "FEMM_extraction_relative_difference",
                    "relative_nodal_Az_difference",
                    "nonlinear_residual",
                )
            }
            for row in m
        ],
        "models": models,
        "source": {
            "Pyleecan_model_sha256": reg["model_sha256"],
            "FEMM_registration_sha256": digest(femm / "registration.json"),
            "native_registration_sha256": digest(native / "registration.json"),
            "target_sha256": digest(target_path),
            "actual_poses_per_solver": n,
            "native_binary_sha256": nr["binary_sha256"],
            "FEMM_runner_sha256": reg["runner_sha256"],
            "native_runner_sha256": nr["runner_sha256"],
            "historical_comparison_sha256": digest(history_path),
            "reference_runtime": reg["dependencies"],
        },
        "historical_mean_RMS_bias_pct": history_bias,
        "mesh": {
            "nodes_min": min(r["nodes"] for r in f),
            "nodes_max": max(r["nodes"] for r in f),
            "triangles_min": min(r["elements"] for r in f),
            "triangles_max": max(r["elements"] for r in f),
        },
        "conditions": {
            "current_A": 0,
            "speed_rpm": speed_rpm,
            "magnet_temperature_C": 20,
            "stack_mm": 83.82,
            "steel": "Published M400-50A curve, 44 points; actual Pyleecan FEMM LamFill=1",
            "magnet_Br_T": 1.24,
            "magnet_mu_r": 1.05,
            "coordinate_rotation_deg": nr["global_coordinate_rotation_deg"],
        },
        "limits_of_interpretation": [
            "Common-mesh 2D solver parity; not independent geometry/mesh validation.",
            "The published Pyleecan model differs from the corrected ORNL/Elmer fixture.",
            "No OEM winding identity, 3D convergence or hardware qualification is inferred.",
        ],
    }


def plot(result: dict, destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f, m = result["models"]
    fv = np.asarray(f["metrics"]["line_voltage_AB_BC_CA_V"])[:, 0]
    mv = np.asarray(m["metrics"]["line_voltage_AB_BC_CA_V"])[:, 0]
    theta = np.arange(len(fv)) * 360 / len(fv)
    with plt.rc_context({"font.size": 10, "svg.fonttype": "none"}):
        fig, ax = plt.subplots(2, 2, figsize=(11, 7), layout="constrained")
        ax[0, 0].plot(theta, fv, label="Pyleecan / FEMM", color="#2563eb")
        ax[0, 0].plot(theta, mv, "--", label="Same model / Magneto", color="#d97706")
        ax[0, 0].set(title=f"Line-to-line BEMF at {f['metrics']['speed_rpm']:,.0f} rpm", xlabel="Electrical angle (degrees)", ylabel="AB voltage (V)")
        ax[0, 0].legend()
        ax[0, 1].plot(theta, mv - fv, color="#7c3aed")
        ax[0, 1].set(title="Magneto minus FEMM", xlabel="Electrical angle (degrees)", ylabel="AB voltage difference (V)")
        rows = f["ORNL_rows"]
        speed = [r["motor_shaft_rpm"] for r in rows]
        ax[1, 0].plot(speed, [r["model_LL_RMS_V"] for r in rows], label="Published Pyleecan / FEMM", color="#2563eb")
        ax[1, 0].scatter(speed, [r["ORNL_LL_RMS_V"] for r in rows], label="ORNL measured", color="#111827", s=22)
        ax[1, 0].set(title="Published model versus hardware", xlabel="Motor speed (rpm)", ylabel="Line-to-line RMS (V)")
        ax[1, 0].legend()
        names = ["Corrected\nMagneto 2D", "Initial\nElmer 3D", "Pyleecan\nFEMM", "Pyleecan\nMagneto"]
        history = result["historical_mean_RMS_bias_pct"]
        values = [history["Magneto2D measured reference"], history["Elmer3D initial"], f["mean_ORNL_RMS_error_pct"], m["mean_ORNL_RMS_error_pct"]]
        ax[1, 1].bar(names, values, color=["#64748b", "#64748b", "#2563eb", "#d97706"])
        ax[1, 1].set(title="Mean RMS bias across 12 ORNL speeds", ylabel="Model minus measured (%)")
        for i, value in enumerate(values):
            ax[1, 1].text(i, value + 0.3, f"{value:+.2f}%", ha="center")
        ax[1, 1].set_ylim(0, max(values) * 1.18)
        for a in ax.flat:
            a.grid(axis="y", alpha=0.2)
            a.set_axisbelow(True)
        fig.suptitle("Prius no-load reference: same Pyleecan geometry, materials and mesh in both solvers")
        fig.supxlabel("48 actual poses per solver; shared central difference; software parity does not qualify hardware accuracy", fontsize=9)
        fig.savefig(destination)
        plt.close(fig)
    if destination.suffix.lower() == ".svg":
        text = destination.read_text(encoding="utf-8")
        destination.write_text("\n".join(line.rstrip() for line in text.splitlines()) + "\n", encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--femm", type=Path, required=True)
    ap.add_argument("--native", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--plot", type=Path)
    args = ap.parse_args()
    if args.out.exists() or (args.plot and args.plot.exists()):
        raise FileExistsError("Use new output paths")
    result = compare(args.femm, args.native)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    if args.plot:
        plot(result, args.plot)
    print(result["reference_parity_status"], result["comparison"])


if __name__ == "__main__":
    main()
