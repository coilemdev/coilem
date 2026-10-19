"""Audit a complete app Prius run and publish its actual waves and all torque points."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/benchmarks/pyleecan-prius-v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_job(run, job, asset_sha):
    folder = run / job["job"]
    for filename, key in [("request.json", "request_sha256"), ("result.json", "result_sha256"),
                          ("artifact-index.json", "artifact_index_sha256")]:
        if digest(folder / filename) != job[key]:
            raise ValueError(f"Changed {job['job']}/{filename}")
    if read(folder / "request.json") != job["request"]:
        raise ValueError("Portable request does not describe the measured job")
    result = read(folder / "result.json")
    for key in ("torque_waveform", "back_emf_waveform", "solve_metadata"):
        if result[key] != job[key]:
            raise ValueError(f"Registered {key} differs from the retained result")
    if result["summary"]["avg_torque_Nm"] != job["metrics"]["mean_torque_Nm"]:
        raise ValueError("Registered torque mean differs from the retained result")
    config = job["request"]
    sp = config["solve_params"]
    tutorial_case = job["job"] == "tutorial-bemf-100"
    expected_step = (3.6 if tutorial_case else 22.5 if job["job"].startswith("curve-")
                     else 5.625 if job["job"] == "angular-64" else 11.25)
    expected_angle = int(job["job"].split("-")[1]) if job["job"].startswith("curve-") else 140
    expected_settings = {
        "rated_speed_rpm": 1000 if tutorial_case else 2000,
        "magnet_temperature_C": 20 if tutorial_case else 60,
        "current_amplitude_A": 0 if tutorial_case else 250, "current_amplitude_convention": "peak",
        "current_angle_deg": expected_angle, "excitation_mode": "sinusoidal",
        "solve_quality": "custom", "rotor_sweep_range_deg": 360, "rotor_step_deg": expected_step,
        "mesh_density": "fine" if job["job"] == "mesh-fine-32" else "normal", "mesh_build": "precise",
        "corner_refinement": False, "slot_sidewall_refinement": False, "max_nonlinear_iterations": 200,
        "nonlinear_solver": "newton", "linear_solver_preconditioner": "direct", "torque_method": "weighted_stress",
    }
    if any(sp.get(key) != value for key, value in expected_settings.items()):
        raise ValueError(f"Changed registered conditions for {job['job']}")
    if config["geometry_reference"] != "pyleecan_prius_2004" or config["reference_case"] != (
        "prius-2004-tutorial-bemf-v1" if tutorial_case else "prius-2004-loaded-torque-v1"
    ):
        raise ValueError("Wrong pinned reference case")
    current_peak = sp["current_amplitude_A"] * (math.sqrt(2) if sp["current_amplitude_convention"] == "rms" else 1)
    reports, methods, max_residual, max_duality, max_current_error = [], set(), 0., 0., 0.
    environments = set()
    loaded, noload = set(), set()
    for entry in read(folder / "artifact-index.json"):
        # Every original-byte hash remains in the published index. Inflate and
        # check every field report; bulky geometry/frame files remain retained locally.
        name = entry["file"]
        if not name.startswith("sweep_pos") or not name.endswith("_report.json"):
            continue
        raw = gzip.decompress((folder / "retained" / (name + ".gz")).read_bytes())
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"Changed retained field report: {name}")
        report = json.loads(raw)
        index = int(name[len("sweep_pos"):].split("_")[0])
        is_noload = "_noload_" in name
        (noload if is_noload else loaded).add(index)
        angle = index * sp["rotor_step_deg"]
        expected = [0., 0., 0.] if is_noload else [
            current_peak * math.cos(math.radians(angle + sp["current_angle_deg"] + offset)) for offset in (0, -120, 120)
        ]
        op = report["operating_point"]
        if op["geometry_asset_sha256"] != asset_sha or "Pyleecan d-axis Phi0" not in op["current_angle_reference"]:
            raise ValueError("Field report lost its actual model or current convention")
        current_error = max(abs(a - b) for a, b in zip(op["phase_current_A"], expected))
        for slot in report["results"]["slot_excitation_contributions"]:
            phase = expected["ABC".index(slot["phase"])]
            signed_turns = 9 if slot["direction"] == "in" else -9
            current_error = max(current_error, abs(slot["integrated_amp_turns_a"] / signed_turns - phase))
        extraction = report["reference_winding_extraction"]
        if extraction["version"] != "published-region-winding/v1":
            raise ValueError("A generic polar-bin linkage result cannot qualify the reference")
        duality = abs(extraction["sum_phase_flux_current_J"] - extraction["integral_Az_Jz_L_J"])
        residual = report["solve_info"]["nonlinear_residual_history"][-1]
        if not all(math.isfinite(v) for v in (duality, residual, current_error)):
            raise ValueError("Non-finite source/convergence audit")
        max_residual, max_duality, max_current_error = max(max_residual, residual), max(max_duality, duality), max(max_current_error, current_error)
        methods.add(report["solve_info"]["solver_method"])
        environments.add(json.dumps(report["solver_environment"], sort_keys=True))
        reports.append({"file": name, "sha256": entry["sha256"], "final_residual": residual,
                        "duality_absolute_J": duality, "phase_current_max_error_A": current_error})
    count = round(360 / sp["rotor_step_deg"])
    if loaded != set(range(count)) or noload != (set(range(count)) if config["solve_options"]["back_emf"] else set()):
        raise ValueError(f"Incomplete actual field grid for {job['job']}")
    return {"actual_loaded_fields": len(loaded), "actual_noload_fields": len(noload), "actual_solver_methods": sorted(methods),
            "actual_solver_environments": [json.loads(value) for value in sorted(environments)],
            "max_final_residual": max_residual, "max_source_linkage_duality_absolute_J": max_duality,
            "max_phase_current_error_A": max_current_error, "field_reports": reports,
            "artifact_index": read(folder / "artifact-index.json")}


def analyze(run):
    registration = read(run / "registration.json")
    if not registration.get("complete") or registration.get("source_dirty"):
        raise ValueError("A complete clean-source app run is required")
    expected_jobs = {"tutorial-bemf-100", "loaded-torque-32", "angular-64", "mesh-fine-32",
                     *[f"curve-{angle}-16" for angle in range(60, 181, 10)]}
    jobs = {job["job"]: job for job in registration["jobs"]}
    if set(jobs) != expected_jobs:
        raise ValueError("The full report requires both presets, all thirteen angles and both refinement controls")
    protocol = read(EVIDENCE / "protocol.json")
    limits = protocol["limits"]
    audits = {name: audit_job(run, job, registration["geometry_asset_sha256"]) for name, job in jobs.items()}
    tutorial = read(EVIDENCE / "pyleecan-tutorial-results.json")
    loaded_reference = read(EVIDENCE / "pyleecan-loaded-results.json")
    native_wave = jobs["tutorial-bemf-100"]["back_emf_waveform"]
    native = np.asarray([native_wave[f"phase_{phase}_V"] for phase in "abc"]).T
    if native.shape != (100, 3):
        raise ValueError("Tutorial comparison requires the full 100 actual no-load samples")
    # Deterministic coordinate mapping, fixed by the drawing reflection. This
    # is not a best-fit circular shift, sign search or amplitude normalization.
    indices = (-np.arange(100)) % 100
    reference = -np.asarray(tutorial["models"][0]["metrics"]["phase_voltage_V"])[indices]
    common_femm = -np.asarray(tutorial["models"][1]["metrics"]["phase_voltage_V"])[indices]
    native_ab, reference_ab = native[:, 0] - native[:, 1], reference[:, 0] - reference[:, 1]
    def rms(values):
        return float(np.sqrt(np.mean(values**2)))
    bemf = {"sampled_AB_rms_V": rms(native_ab), "sampled_AB_peak_V": float(np.max(abs(native_ab))),
            "tutorial_AB_rms_V": rms(reference_ab), "tutorial_AB_peak_V": float(np.max(abs(reference_ab))),
            "tutorial_line_rms_relative": rms(native_ab) / rms(reference_ab) - 1,
            "tutorial_line_peak_relative": float(np.max(abs(native_ab)) / np.max(abs(reference_ab)) - 1),
            "tutorial_line_waveform_relative_L2": float(np.linalg.norm(native_ab - reference_ab) / np.linalg.norm(reference_ab)),
            "full_FEMM_phase_waveform_relative_L2": float(np.linalg.norm(native - common_femm) / np.linalg.norm(common_femm)),
            "electrical_angle_deg": native_wave["electrical_angle_deg"],
            "app_phase_voltage_V": native.tolist(), "mapped_tutorial_phase_voltage_V": reference.tolist(),
            "mapped_full_FEMM_phase_voltage_V": common_femm.tolist(), "mapping": protocol["waveform_mapping"]}
    femm_curve = loaded_reference["models"]["FEMM_published"]["curve"]
    common_curve = loaded_reference["models"]["Magneto_published"]["curve"]
    curve = []
    for femm, common in zip(femm_curve, common_curve):
        angle = femm["current_angle_deg"]
        mean = jobs[f"curve-{angle}-16"]["metrics"]["mean_torque_Nm"]
        curve.append({"Phi0_deg": angle, "upstream_Nm": femm["reference_torque_Nm"],
                      "retained_FEMM_Nm": femm["mean_stress_torque_Nm"], "retained_common_mesh_native_Nm": common["mean_stress_torque_Nm"],
                      "app_Nm": mean, "app_minus_FEMM_Nm": mean - femm["mean_stress_torque_Nm"],
                      "app_minus_upstream_Nm": mean - femm["reference_torque_Nm"]})
    baseline = jobs["loaded-torque-32"]["metrics"]["mean_torque_Nm"]
    femm_peak_control = next(row["refined_mean_Nm"] for row in loaded_reference["sampling_refinement"]["FEMM_published"]["rows"]
                             if row["current_angle_deg"] == 140)
    controls = {name: {"mean_torque_Nm": jobs[name]["metrics"]["mean_torque_Nm"],
                       "actual_positions": jobs[name]["metrics"]["loaded_actual_positions"],
                       "first_pose_mesh_triangles": jobs[name]["solve_metadata"]["mesh_element_count"],
                       "change_from_normal_32_Nm": jobs[name]["metrics"]["mean_torque_Nm"] - baseline,
                       "change_normalized_to_reference_peak": abs(jobs[name]["metrics"]["mean_torque_Nm"] - baseline) / 353}
                for name in ("angular-64", "mesh-fine-32")}
    checks = {"tutorial_RMS": abs(bemf["tutorial_line_rms_relative"]) < limits["tutorial_line_rms_relative"],
              "tutorial_peak": abs(bemf["tutorial_line_peak_relative"]) < limits["tutorial_line_peak_relative"],
              "tutorial_waveform": bemf["tutorial_line_waveform_relative_L2"] < limits["tutorial_line_waveform_relative_L2"],
              "loaded_mean_vs_FEMM": abs(baseline / femm_peak_control - 1) < limits["loaded_mean_relative_to_femm"],
              "all_13_same_model_means": max(abs(row["app_minus_FEMM_Nm"]) for row in curve) / max(row["retained_FEMM_Nm"] for row in curve)
              < limits["curve_max_mean_difference_normalized_to_femm_peak"],
              "angular_control": controls["angular-64"]["change_normalized_to_reference_peak"]
              < limits["angular_mean_change_normalized_to_reference_peak"],
              "mesh_control": controls["mesh-fine-32"]["change_normalized_to_reference_peak"]
              < limits["mesh_mean_change_normalized_to_reference_peak"],
              "all_fields_converged": max(a["max_final_residual"] for a in audits.values()) < limits["native_final_residual"],
              "all_phase_currents": max(a["max_phase_current_error_A"] for a in audits.values()) < 1e-8,
              "source_linkage_duality": max(a["max_source_linkage_duality_absolute_J"] for a in audits.values()) < 1e-9}
    hardware_path = ROOT / "docs/hardware-validation/ornl-prius-2004/target-back-emf.json"
    hardware_row = next(row for row in read(hardware_path)["rows"] if row["motor_shaft_rpm"] == 1000)
    hardware_context = {
        "target_file": hardware_path.relative_to(ROOT).as_posix(), "target_sha256": digest(hardware_path),
        "ORNL_1000rpm_line_RMS_V": hardware_row["back_emf_ll_rms_V"],
        "ORNL_1000rpm_line_peak_V": hardware_row["back_emf_ll_peak_V"],
        "software_model_RMS_difference_relative": bemf["sampled_AB_rms_V"] / hardware_row["back_emf_ll_rms_V"] - 1,
        "software_model_peak_difference_relative": bemf["sampled_AB_peak_V"] / hardware_row["back_emf_ll_peak_V"] - 1,
        "status": "Context only; no hardware verdict. Software model uses 20 C magnets; ORNL recorded nominal 25 C oil, not magnet temperature.",
    }
    return {"schema": "coilem.pyleecan_prius_public_app_report/v1", "qualified": False,
            "interpretation": "Software reproduction; retain all upstream discrepancies. Final v0.4.0 candidate rerun remains required.",
            "field_source_commit": registration["source_commit"], "field_source_dirty": registration["source_dirty"],
            "source_sha256": registration["source_sha256"], "binary_sha256": registration["binary_sha256"],
            "platform": registration["platform"], "python": registration["python"], "dependencies": registration["dependencies"],
            "started_utc": registration["started_utc"], "finished_utc": registration["finished_utc"],
            "registration_sha256": digest(run / "registration.json"), "protocol_sha256": digest(EVIDENCE / "protocol.json"),
            "historical_evidence_sha256": {name: digest(EVIDENCE / name) for name in
                                           ("pyleecan-tutorial-results.json", "pyleecan-loaded-results.json", "pyleecan-ui-results.json")},
            "analysis_runner_sha256": digest(Path(__file__)), "analysis_numpy": np.__version__,
            "checks": checks, "all_software_checks_pass": all(checks.values()), "tutorial": bemf, "hardware_context": hardware_context,
            "loaded": {"app_mean_Nm": baseline,
                       "first_pose_mesh_triangles": jobs["loaded-torque-32"]["solve_metadata"]["mesh_element_count"],
                       "retained_FEMM_16_half_cycle_mean_Nm": femm_peak_control,
                       "difference_to_FEMM_relative": baseline / femm_peak_control - 1},
            "curve": curve, "curve_upstream_RMSE_Nm": rms(np.asarray([row["app_minus_upstream_Nm"] for row in curve])),
            "controls": controls, "jobs": registration["jobs"], "audits": audits}


def markdown(data):
    t, loaded = data["tutorial"], data["loaded"]
    lines = ["# Public app Prius benchmark", "", f"Measured clean candidate `{data['field_source_commit']}`.", "",
             f"Software checks: **{sum(data['checks'].values())}/{len(data['checks'])} pass**. Hardware qualification is not claimed.", "",
             f"Tutorial: **{t['sampled_AB_rms_V']:.6f} V AB sampled RMS**, {100*t['tutorial_line_rms_relative']:+.4f}% from the retained tutorial; "
             f"{t['sampled_AB_peak_V']:.6f} V absolute peak, {100*t['tutorial_line_waveform_relative_L2']:.4f}% waveform relative L2.", "",
             f"Loaded preset: **{loaded['app_mean_Nm']:.6f} Nm**, "
             f"{100*loaded['difference_to_FEMM_relative']:+.4f}% from the retained FEMM control.", "",
             "The fixed drawing-reflection mapping reverses electrical sample order and voltage polarity. No fit is applied.", "",
             "| Phi0 | Upstream Nm | Retained FEMM Nm | Fresh app Nm | App minus FEMM Nm | App minus upstream Nm |",
             "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in data["curve"]:
        lines.append(f"| {row['Phi0_deg']} | {row['upstream_Nm']} | {row['retained_FEMM_Nm']:.6f} | {row['app_Nm']:.6f} | "
                     f"{row['app_minus_FEMM_Nm']:+.6f} | {row['app_minus_upstream_Nm']:+.6f} |")
    lines += ["", f"Full-curve upstream RMS error: **{data['curve_upstream_RMSE_Nm']:.6f} Nm**. All thirteen discrepancies remain in the result.", "",
              "| Independent refinement at Phi0=140 degrees | Actual poses | First-pose triangles | Mean Nm | Change from normal 32 Nm |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for name, control in data["controls"].items():
        lines.append(f"| {name} | {control['actual_positions']} | {control['first_pose_mesh_triangles']} | "
                     f"{control['mean_torque_Nm']:.6f} | {control['change_from_normal_32_Nm']:+.6f} |")
    normal_triangles = loaded["first_pose_mesh_triangles"]
    fine_triangles = data["controls"]["mesh-fine-32"]["first_pose_mesh_triangles"]
    lines += ["", f"The Normal 32 baseline has {normal_triangles:,} first-pose triangles. Fine changes this model to {fine_triangles:,} "
              f"({100*(fine_triangles/normal_triangles-1):+.1f}%); this mesh change bounds observed sensitivity "
              "rather than establishing systematic spatial convergence.", "", "| Check | Outcome |", "| --- | --- |"]
    lines += [f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in data["checks"].items()]
    h = data["hardware_context"]
    lines += ["", f"Hardware context at 1000 rpm: ORNL records {h['ORNL_1000rpm_line_RMS_V']} V line RMS and "
              f"{h['ORNL_1000rpm_line_peak_V']} V peak. The 20 C software model differs by "
              f"{100*h['software_model_RMS_difference_relative']:+.2f}% RMS and {100*h['software_model_peak_difference_relative']:+.2f}% peak. "
              "ORNL's nominal 25 C oil is not a measured magnet temperature. This comparison has no hardware verdict."]
    lines += ["", "Actual app solves: 100 tutorial zero-current fields plus 100 separate no-load fields; "
              "32 loaded plus 32 no-load fields; 13 current angles × 16 full-cycle fields; 64 angular and 32 Fine mesh control fields.", "",
              "[JSON waveforms, identities and field hashes](app-results.json) · [Full protocol and interpretation](README.md)", "",
              "Runtime is recorded per job as informational wall time, not a controlled performance qualification. "
              "These remain development-candidate software results; repeat on the frozen final v0.4.0 candidate.", ""]
    return "\n".join(lines)


def plot(data, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), constrained_layout=True)
    t = data["tutorial"]
    native, reference = np.asarray(t["app_phase_voltage_V"]), np.asarray(t["mapped_tutorial_phase_voltage_V"])
    x = t["electrical_angle_deg"]
    axes[0].plot(x, reference[:, 0] - reference[:, 1], label="Retained tutorial, declared frame mapping", linewidth=2)
    axes[0].plot(x, native[:, 0] - native[:, 1], "--", label="Fresh normal app", linewidth=1.5)
    axes[0].set(xlabel="App electrical angle (degrees)", ylabel="AB voltage (V)", title="1000 rpm, 20 C, zero phase current")
    rows = data["curve"]
    for key, label, style in [("upstream_Nm", "Upstream transcription", "o-"),
                              ("retained_FEMM_Nm", "Retained exact-model FEMM", "-"), ("app_Nm", "Fresh app", "--")]:
        axes[1].plot([row["Phi0_deg"] for row in rows], [row[key] for row in rows], style, label=label)
    axes[1].set(xlabel="Published d-axis Phi0 (degrees)", ylabel="Mean torque (Nm)", title="2000 rpm, 60 C, 250 A peak — every tested angle")
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend()
    fig.savefig(path, metadata={"Date": None})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plot", action="store_true", help="Also render app-results.svg (optional Matplotlib)")
    args = parser.parse_args()
    data = analyze(args.run)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "app-results.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    (args.out / "app-results.md").write_text(markdown(data), encoding="utf-8", newline="\n")
    if args.plot:
        plot(data, args.out / "app-results.svg")
    print(json.dumps({"checks": data["checks"], "loaded": data["loaded"], "upstream_curve_RMSE_Nm": data["curve_upstream_RMSE_Nm"]}, indent=2))
    return 0 if data["all_software_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
