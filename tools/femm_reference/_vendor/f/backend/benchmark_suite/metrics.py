"""Evaluate complete evidence without fitted shifts, sign flips or relaxed gates."""

import math

from backend.benchmark_suite.abc_metrics import compare
from backend.benchmark_suite.bldc_metrics import (
    current_property_metrics,
    evaluate_numeric,
    mean,
    power_torque_metric,
    relative_delta_pct,
    ripple_pct,
    status,
    validate_lane_result,
)


def finite_series(values, count=None):
    if (
        not isinstance(values, list)
        or not values
        or (count is not None and len(values) != count)
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
    ):
        raise ValueError("Invalid or incomplete numerical waveform")


def validate_abc(result, config, *, native=True):
    params = config["solve_params"]
    for key, fields in (("torque_waveform", ("torque_Nm",)), ("back_emf_waveform", ("phase_a_V", "phase_b_V", "phase_c_V"))):
        span = 360.0 if key == "back_emf_waveform" else params["rotor_sweep_range_deg"]
        count = max(2, round(span / params["rotor_step_deg"]) + (0 if span >= 360.0 - 1e-9 else 1))
        wave = result.get(key) or {}
        finite_series(wave.get("electrical_angle_deg"), count)
        if any(abs(a - i * params["rotor_step_deg"]) > 1e-7 for i, a in enumerate(wave["electrical_angle_deg"])):
            raise ValueError("Waveform differs from the registered angle grid")
        for field in fields:
            finite_series(wave.get(field), count)
    summary = result.get("summary", {})
    finite_series([summary.get("avg_torque_Nm"), summary.get("back_emf_fundamental_V")])
    metadata = result.get("solve_metadata", {})
    if native and (
        not str(metadata.get("solver_name", "")).startswith("magneto2d-")
        or metadata.get("mesh_source") != "native"
        or metadata.get("torque_method") != "weighted_stress"
    ):
        raise ValueError("Candidate did not use the public native WST solver")


def energy_balance_ratio(result, config):
    """Average torque over the torque its own back-EMF and current imply.

    For sinusoidal current, T_implied = 3 * E_rms * I_rms * cos(gamma) / omega_m.
    A consistent model gives about 1, or less where load saturation lowers the
    flux linkage below its no-load value; the halved flux-linkage credit for
    single-layer concentrated windings gave about 2 (#80). Diagnostic only.
    """
    params = config.get("solve_params") or {}
    if (params.get("excitation_mode") or "sinusoidal") != "sinusoidal":
        return None
    summary = result.get("summary", {})
    torque = summary.get("avg_torque_Nm")
    emf_rms = summary.get("back_emf_fundamental_V")
    current = params.get("current_amplitude_A")
    speed_rpm = params.get("rated_speed_rpm")
    if not current or not speed_rpm or torque is None or emf_rms is None:
        return None
    rms = current if params.get("current_amplitude_convention") == "rms" else current / math.sqrt(2)
    gamma = math.radians(params.get("current_angle_deg") or 0.0)
    implied = 3 * emf_rms * rms * math.cos(gamma) / (speed_rpm * 2 * math.pi / 60)
    return abs(torque) / abs(implied) if abs(implied) > 1e-12 else None


def evaluate_abc(result, reference, config):
    validate_abc(result, config)
    if reference is None:
        return {"status": "NOT_COMPARED", "gates": {"reference_comparison": "NOT_EVALUATED"}}
    validate_abc(reference, config, native=False)
    return compare({"result": result}, reference)


def evaluate_bldc(protocol, raw, golden):
    required = {"native-standard", "native-fine", "analytical"}
    if not required.issubset(raw):
        return {"status": "INCOMPLETE", "gates": [], "missing_stages": sorted(required - raw.keys())}
    if "femm-standard" in raw:
        return evaluate_numeric(protocol, raw, golden)
    for stage, artifact in raw.items():
        validate_lane_result(stage, artifact["result"], protocol, golden=golden, check_golden_sequence=False)
    limits = protocol["gates"]
    standard, fine, analytical = (raw[s]["result"] for s in ("native-standard", "native-fine", "analytical"))
    power = power_torque_metric(analytical, protocol["matrix"]["low_current_power_discriminator"]["rated_speed_rpm"])
    checks = [
        ("power_torque_delta_pct", power["delta_pct"]),
        ("native_standard_to_fine_mean_torque_delta_pct", relative_delta_pct(mean(standard["torque_Nm"]), mean(fine["torque_Nm"]))),
        ("native_standard_to_fine_ripple_delta_percentage_points", abs(ripple_pct(standard["torque_Nm"]) - ripple_pct(fine["torque_Nm"]))),
    ]
    gates = [{"id": name, "value": value, "maximum": limits[name + "_max"], "status": status(value, limits[name + "_max"])} for name, value in checks]
    if not power["positive_motoring_sign"]:
        gates[0]["status"] = "FAIL"
    for stage, lane in (("native-standard", "native_standard"), ("native-fine", "native_fine"), ("analytical", "analytical_low_current")):
        result = raw[stage]["result"]
        current = protocol["excitation"]["analytical_current_A" if stage == "analytical" else "product_current_A"]
        props = current_property_metrics(result, current)
        passed = (
            props["max_zero_sum_abs_A"] <= limits["current_zero_sum_abs_A_max"]
            and props["max_plateau_error_abs_A"] <= limits["current_plateau_abs_A_max"]
            and props["max_zero_phase_abs_A"] <= limits["current_plateau_abs_A_max"]
            and props["invalid_conduction_samples"] == 0
        )
        gates.append({"id": lane + "_current_properties", "value": props, "status": "PASS" if passed else "FAIL"})
        try:
            validate_lane_result(stage, result, protocol, golden=golden)
            verdict, detail = "PASS", "matches frozen golden current table"
        except ValueError as exc:
            verdict, detail = "FAIL", str(exc)
        gates.append({"id": stage + "_golden_current_sequence", "value": detail, "status": verdict})
    for name in (
        "mean_torque_delta_pct",
        "torque_waveform_nrmse_pct",
        "commutation_transition_delta_samples",
        "femm_standard_current_properties",
        "femm-standard_golden_current_sequence",
    ):
        gates.append({"id": name, "value": None, "status": "NOT_EVALUATED"})
    return {
        "status": "FAIL" if any(g["status"] == "FAIL" for g in gates) else "NOT_COMPARED",
        "gates": gates,
        "results": {"power_torque_discriminator": power},
    }
