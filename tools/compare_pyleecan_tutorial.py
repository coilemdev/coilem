"""Compare the published open-circuit Prius tutorial with matched full-model fields."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

LIMITS = {
    "common_mesh_relative_linkage": 0.02,
    "common_mesh_relative_line_rms": 0.02,
    "common_mesh_relative_line_peak": 0.03,
    "FEMM_extraction_relative": 1e-8,
    "native_final_residual": 1e-8,
    "tutorial_relative_line_rms": 0.02,
    "tutorial_relative_line_peak": 0.03,
    "tutorial_relative_line_waveform_L2": 0.05,
}


def contents(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else gzip.decompress(path.with_suffix(path.suffix + ".gz").read_bytes())


def digest(path: Path) -> str:
    return hashlib.sha256(contents(path)).hexdigest()


def read(path: Path):
    return json.loads(contents(path))


def half_cycle(phase_flux) -> np.ndarray:
    flux = np.asarray(phase_flux, float)
    if flux.shape != (50, 3) or not np.isfinite(flux).all():
        raise ValueError("The tutorial comparison requires 50 finite actual three-phase half-cycle samples")
    return np.concatenate((flux, -flux))


def metrics(phase_flux, speed_rpm: float = 1000) -> dict:
    flux = np.asarray(phase_flux, float)
    if flux.shape != (100, 3) or not np.isfinite(flux).all() or speed_rpm <= 0:
        raise ValueError("A complete finite 100-sample three-phase electrical cycle at positive speed is required")
    omega = speed_rpm * 2 * math.pi / 60 * 4
    dt = 2 * math.pi / (100 * omega)
    # Pyleecan OutMag.comp_emf uses +d(Phi)/dt. Use that convention for all
    # lanes rather than fit a voltage sign or a waveform phase offset.
    voltage = (np.roll(flux, -1, axis=0) - np.roll(flux, 1, axis=0)) / (2 * dt)
    line = voltage - np.roll(voltage, -1, axis=1)
    line_fund = 2 * abs(np.fft.rfft(line, axis=0)[1]) / 100 / math.sqrt(2)
    flux_fund = 2 * abs(np.fft.rfft(flux, axis=0)[1]) / 100
    return {
        "speed_rpm": speed_rpm,
        "electrical_angle_deg": (np.arange(100) * 3.6).tolist(),
        "phase_flux_Wb": flux.tolist(),
        "phase_voltage_V": voltage.tolist(),
        "line_voltage_AB_BC_CA_V": line.tolist(),
        "phase_rms_V": np.sqrt(np.mean(voltage**2, axis=0)).tolist(),
        "line_rms_V": np.sqrt(np.mean(line**2, axis=0)).tolist(),
        "line_sampled_peak_V": np.max(abs(line), axis=0).tolist(),
        "line_fundamental_rms_V": line_fund.tolist(),
        "phase_flux_fundamental_Wb": flux_fund.tolist(),
        "Ke_phase_peak_Vs_per_mech_rad": (4 * flux_fund).tolist(),
    }


def compare(reference: Path, femm: Path, native: Path, femm_executable: Path | None = None) -> dict:
    tr, fr, nr = (read(p / "registration.json") for p in (reference, femm, native))
    tw = read(reference / "waveform.json")
    fw, nw = (read(p / "waveform.json") for p in (femm, native))
    if not tw.get("complete") or not read(native / "completion.json").get("complete") or not (femm / "completion.json").exists():
        raise ValueError("All three field calculations must be complete")
    if fr["points"] != 50 or fr["electrical_range_deg"] != 180 or len(fw) != 50 or len(nw) != 50:
        raise ValueError("Expected 50 actual matched half-cycle fields per full-model solver")
    if tr["machine_sha256"] != fr["model_sha256"] or nr["FEMM_registration_sha256"] != digest(femm / "registration.json"):
        raise ValueError("Model or FEMM reference identity differs")
    if tr["speed_rpm"] != 1000 or fr["speed_rpm"] != 1000 or tr["magnet_temperature_C"] != 20 or fr["magnet_temperature_C"] != 20:
        raise ValueError("Tutorial conditions differ from the matched comparison")
    current = np.asarray(tw["phase_current_A"])
    if tr["current_dq_A_rms"] != [0, 0] or fr["phase_current_A"] != [0, 0, 0] or current.shape != (400, 3) or np.any(current):
        raise ValueError("The no-load comparison requires exactly zero current")
    if (
        not math.isclose(math.radians(fr["initial_rotor_mechanical_deg"]), tw["initial_rotor_angle_rad"], abs_tol=1e-12)
        or fr["rotation_direction"] != -1
    ):
        raise ValueError("Rotor starting pose or direction differs; no phase fitting is permitted")
    times = np.asarray(tw["time_s"])
    expected_time = np.arange(400) * 0.00015
    if times.shape != (400,) or not np.allclose(times, expected_time, atol=1e-12, rtol=0):
        raise ValueError("Unexpected tutorial time grid")
    rotor = np.asarray(tw["rotor_angle_rad"])
    if not np.allclose(rotor, tw["initial_rotor_angle_rad"] - np.arange(400) * math.pi / 200, atol=1e-12, rtol=0):
        raise ValueError("Unexpected tutorial rotor trajectory")
    tutorial_flux = np.asarray(tw["phase_flux_Wb"])
    if tutorial_flux.shape != (400, 3) or not np.allclose(tutorial_flux, np.tile(half_cycle(tutorial_flux[:50]), (4, 1)), atol=1e-12, rtol=0):
        raise ValueError("The tutorial's anti-periodic reconstruction is inconsistent")
    tm = metrics(tutorial_flux[:100])
    if not np.allclose(np.tile(tm["phase_voltage_V"], (4, 1)), tw["phase_emf_V"], atol=1e-9, rtol=1e-11):
        raise ValueError("Independent voltage derivative does not reproduce Pyleecan's native comp_emf")
    fm, nm = (metrics(half_cycle([r["phase_linkage_Wb"] for r in rows])) for rows in (fw, nw))
    poses = []
    for i, (f, n) in enumerate(zip(fw, nw, strict=True)):
        if (
            f["index"] != i
            or n["index"] != i
            or not math.isclose(f["electrical_angle_deg"], i * 3.6)
            or n["electrical_angle_deg"] != f["electrical_angle_deg"]
        ):
            raise ValueError("Actual field angles or order differ")
        if not math.isclose(f["mechanical_angle_deg"], fr["initial_rotor_mechanical_deg"] - i * 0.9):
            raise ValueError("The full-model rotor trajectory differs from the tutorial")
        if any(abs(c[0]) > 1e-15 for c in f["circuit_properties"]):
            raise ValueError("Nonzero FEMM circuit current")
        fp, npth = femm / f"pose-{i:03d}", native / f"pose-{i:03d}"
        if (
            f["fem_sha256"] != digest(fp / "motor.fem")
            or f["ans_sha256"] != digest(fp / "motor.ans")
            or n["source_FEMM_ans_sha256"] != f["ans_sha256"]
        ):
            raise ValueError("FEMM artifact identity mismatch")
        if n["mesh_sha256"] != digest(npth / "mesh.json") or n["report_sha256"] != digest(npth / "report.json"):
            raise ValueError("Native artifact identity mismatch")
        report = read(npth / "report.json")
        if [report["results"][f"flux_linkage_{p}_wb"] for p in "abc"] != n["phase_linkage_Wb"] or report["solve_info"]["nonlinear_residual_history"][
            -1
        ] != n["nonlinear_residual"]:
            raise ValueError("Native waveform does not reproduce its retained field report")
        if [c[2] for c in f["circuit_properties"]] != f["phase_linkage_Wb"]:
            raise ValueError("FEMM waveform differs from circuit extraction")
        request, mesh = read(npth / "input.json"), read(npth / "mesh.json")
        if request["solve_params"]["current_amplitude_A"] != 0 or np.any(mesh["element_current_density_a_per_m2"]):
            raise ValueError("Nonzero native winding current")
        poses.append({**n, "source_FEMM_fem_sha256": f["fem_sha256"], "input_sha256": digest(npth / "input.json")})
    tv, fv, nv = (np.asarray(m["line_voltage_AB_BC_CA_V"])[:, 0] for m in (tm, fm, nm))
    stats = {
        "common_mesh_line_rms_relative": nm["line_rms_V"][0] / fm["line_rms_V"][0] - 1,
        "common_mesh_line_peak_relative": nm["line_sampled_peak_V"][0] / fm["line_sampled_peak_V"][0] - 1,
        "max_common_mesh_linkage_relative": max(r["linkage_relative_difference"] for r in nw),
        "max_FEMM_extraction_relative": max(r["FEMM_extraction_relative_difference"] for r in nw),
        "max_native_final_residual": max(r["nonlinear_residual"] for r in nw),
        "native_vs_tutorial_line_rms_relative": nm["line_rms_V"][0] / tm["line_rms_V"][0] - 1,
        "native_vs_tutorial_line_peak_relative": nm["line_sampled_peak_V"][0] / tm["line_sampled_peak_V"][0] - 1,
        "native_vs_tutorial_line_waveform_relative_L2": float(np.linalg.norm(nv - tv) / np.linalg.norm(tv)),
        "full_FEMM_vs_tutorial_line_rms_relative": fm["line_rms_V"][0] / tm["line_rms_V"][0] - 1,
        "native_vs_full_FEMM_line_waveform_relative_L2": float(np.linalg.norm(nv - fv) / np.linalg.norm(fv)),
    }
    checks = {
        "common_mesh_linkage": stats["max_common_mesh_linkage_relative"] <= LIMITS["common_mesh_relative_linkage"],
        "common_mesh_line_rms": abs(stats["common_mesh_line_rms_relative"]) <= LIMITS["common_mesh_relative_line_rms"],
        "common_mesh_line_peak": abs(stats["common_mesh_line_peak_relative"]) <= LIMITS["common_mesh_relative_line_peak"],
        "FEMM_extraction": stats["max_FEMM_extraction_relative"] <= LIMITS["FEMM_extraction_relative"],
        "native_convergence": stats["max_native_final_residual"] <= LIMITS["native_final_residual"],
        "tutorial_line_rms": abs(stats["native_vs_tutorial_line_rms_relative"]) <= LIMITS["tutorial_relative_line_rms"],
        "tutorial_line_peak": abs(stats["native_vs_tutorial_line_peak_relative"]) <= LIMITS["tutorial_relative_line_peak"],
        "tutorial_line_waveform": stats["native_vs_tutorial_line_waveform_relative_L2"] <= LIMITS["tutorial_relative_line_waveform_L2"],
    }
    portable_tutorial = json.loads(json.dumps(tr))
    portable_tutorial["simulation"]["path_result"] = "<local output directory>"
    for role in ("rotor", "stator"):
        portable_tutorial["simulation"]["machine"][role]["mat_type"]["path"] = "<source material path; curve embedded>"
    return {
        "schema": "coilem.pyleecan_prius_tutorial_bemf/v1",
        "experimental": True,
        "qualified": False,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "limits": LIMITS,
        "checks": checks,
        "comparison": stats,
        "conditions": {
            "speed_rpm": 1000,
            "magnet_temperature_C": 20,
            "current_A": 0,
            "initial_rotor_mechanical_deg": fr["initial_rotor_mechanical_deg"],
            "direction": "clockwise",
            "electrical_step_deg": 3.6,
        },
        "samples": {
            "actual_fields_per_lane": 50,
            "computed_electrical_span_deg": 180,
            "reconstructed_electrical_cycle_samples": 100,
            "tutorial_reconstructed_mechanical_revolution_samples": 400,
            "reconstruction": "Append the negative half-cycle, exactly as the tutorial's temporal anti-periodicity; no phase or magnitude fitting.",
        },
        "source": {
            "tutorial": portable_tutorial,
            "tutorial_registration_sha256": digest(reference / "registration.json"),
            "portable_registration_note": (
                "Local output directory and nonfunctional source material paths are replaced; "
                "embedded numerical curves and original registration hash are retained."
            ),
            "full_FEMM_registration": fr,
            "native_registration": nr,
            "tutorial_output_sha256": digest(reference / "output.json"),
            "tutorial_waveform_sha256": digest(reference / "waveform.json"),
            "FEMM_binary_sha256": digest(femm_executable) if femm_executable else None,
        },
        "models": [
            {"label": label, "metrics": m}
            for label, m in (
                ("Published tutorial / FEMM sliding band", tm),
                ("Same model / full FEMM remesh", fm),
                ("Same full mesh / Magneto2D", nm),
            )
        ],
        "pose_controls": poses,
        "limits_of_interpretation": [
            "Reproduction of a published tutorial workflow, not a published numerical BEMF acceptance target.",
            "Common-mesh solver parity plus a separate sliding-band/symmetry comparison; no spatial convergence claim.",
            "The 20 C no-load tutorial is a separate condition from the 60 C loaded-torque UI fixture.",
            "No independent OEM hardware accuracy is inferred.",
        ],
    }


def plot(result: dict, destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    models = result["models"]
    theta = models[0]["metrics"]["electrical_angle_deg"]
    with plt.rc_context({"font.size": 10, "svg.fonttype": "none"}):
        fig, ax = plt.subplots(3, 1, figsize=(10, 8), layout="constrained")
        for p, color in enumerate(("#dc2626", "#16a34a", "#2563eb")):
            ax[0].plot(theta, np.asarray(models[0]["metrics"]["phase_voltage_V"])[:, p], color=color, label="ABC"[p])
        ax[0].set(title="Published Prius open-circuit tutorial: 1,000 rpm, 20 C, 0 A", ylabel="Phase EMF (V)")
        ax[0].legend(ncol=3)
        for model, color, style in zip(models, ("#2563eb", "#64748b", "#d97706"), ("-", ":", "--"), strict=True):
            ax[1].plot(theta, np.asarray(model["metrics"]["line_voltage_AB_BC_CA_V"])[:, 0], style, color=color, label=model["label"])
        ax[1].set(ylabel="AB line voltage (V)")
        ax[1].legend()
        tv, fv, nv = (np.asarray(m["metrics"]["line_voltage_AB_BC_CA_V"])[:, 0] for m in models)
        ax[2].plot(theta, nv - tv, label="Magneto minus tutorial", color="#7c3aed")
        ax[2].plot(theta, nv - fv, label="Magneto minus common-mesh FEMM", color="#d97706")
        ax[2].set(ylabel="AB difference (V)", xlabel="Clockwise electrical displacement (degrees)")
        ax[2].legend()
        for axis in ax:
            axis.grid(alpha=0.2)
            axis.set_xlim(0, 360)
        fig.savefig(destination)
        fig.savefig(destination.with_suffix(".png"), dpi=150)
        plt.close(fig)
        if destination.suffix.lower() == ".svg":
            svg = destination.read_text(encoding="utf-8")
            destination.write_text("\n".join(line.rstrip() for line in svg.splitlines()) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "femm", "native", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--plot", type=Path)
    parser.add_argument("--femm-executable", type=Path)
    args = parser.parse_args()
    result = compare(args.reference, args.femm, args.native, args.femm_executable)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    if args.plot:
        plot(result, args.plot)
    print(result["status"], json.dumps(result["comparison"], indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
