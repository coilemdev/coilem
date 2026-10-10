"""Fourteen historical BLDC gates, operating only on numerical evidence.

Adapted from the registered validator at reference commit
8b95decda27d475ddbb75e99d92744ebc8e53b28. No reference solver imports.
"""

from __future__ import annotations

import math
from typing import Any


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot compute a mean of an empty series")
    return sum(values) / len(values)


def rms(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot compute RMS of an empty series")
    return math.sqrt(sum(value * value for value in values) / len(values))


def relative_delta_pct(candidate: float, reference: float) -> float:
    if abs(reference) <= 1e-15:
        raise ValueError("relative delta reference is zero")
    return abs(candidate - reference) / abs(reference) * 100.0


def normalized_rms_error_pct(candidate: list[float], reference: list[float]) -> float:
    if len(candidate) != len(reference):
        raise ValueError("NRMSE series lengths do not agree")
    reference_rms = rms(reference)
    if reference_rms <= 1e-15:
        raise ValueError("NRMSE reference RMS is zero")
    return rms([left - right for left, right in zip(candidate, reference, strict=True)]) / reference_rms * 100.0


def ripple_pct(values: list[float]) -> float:
    average = mean(values)
    if abs(average) <= 1e-15:
        raise ValueError("torque ripple mean is zero")
    return (max(values) - min(values)) / abs(average) * 100.0


def assert_aligned_angles(*series: list[float], tolerance_deg: float = 1e-8) -> None:
    if not series:
        return
    expected = series[0]
    for actual in series[1:]:
        if len(actual) != len(expected) or any(
            not math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance_deg) for a, b in zip(actual, expected, strict=True)
        ):
            raise ValueError("validation series do not share the exact angle grid")


def current_rows(payload: dict[str, Any]) -> list[tuple[float, float, float]]:
    waveform = payload["phase_current_waveform"]
    return list(
        zip(
            waveform["phase_a_A"],
            waveform["phase_b_A"],
            waveform["phase_c_A"],
            strict=True,
        )
    )


def current_property_metrics(payload: dict[str, Any], plateau_a: float) -> dict[str, float | int]:
    max_zero_sum = 0.0
    max_plateau_error = 0.0
    max_zero_phase = 0.0
    invalid_conduction_samples = 0
    for row in current_rows(payload):
        max_zero_sum = max(max_zero_sum, abs(sum(row)))
        conducting = [abs(value) for value in row if abs(value) > 1e-12]
        zero = [abs(value) for value in row if abs(value) <= 1e-12]
        if len(conducting) != 2 or len(zero) != 1:
            invalid_conduction_samples += 1
            continue
        max_plateau_error = max(
            max_plateau_error,
            *(abs(value - plateau_a) for value in conducting),
        )
        max_zero_phase = max(max_zero_phase, *zero)
    return {
        "max_zero_sum_abs_A": max_zero_sum,
        "max_plateau_error_abs_A": max_plateau_error,
        "max_zero_phase_abs_A": max_zero_phase,
        "invalid_conduction_samples": invalid_conduction_samples,
    }


def transition_indices(rows: list[tuple[float, float, float]]) -> list[int]:
    if not rows:
        return []
    return [index for index, row in enumerate(rows) if row != rows[index - 1]]


def circular_index_delta(left: int, right: int, sample_count: int) -> int:
    direct = abs(left - right)
    return min(direct, sample_count - direct)


def transition_metric(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    candidate_transitions = transition_indices(current_rows(candidate))
    reference_transitions = transition_indices(current_rows(reference))
    if len(candidate_transitions) != len(reference_transitions):
        return {
            "candidate_indices": candidate_transitions,
            "reference_indices": reference_transitions,
            "max_delta_samples": len(candidate["electrical_angle_deg"]),
        }
    count = len(candidate["electrical_angle_deg"])
    deltas = [circular_index_delta(left, right, count) for left, right in zip(candidate_transitions, reference_transitions, strict=True)]
    return {
        "candidate_indices": candidate_transitions,
        "reference_indices": reference_transitions,
        "delta_samples": deltas,
        "max_delta_samples": max(deltas, default=0),
    }


def power_torque_metric(payload: dict[str, Any], rated_speed_rpm: float) -> dict[str, Any]:
    current = payload["phase_current_waveform"]
    emf = payload["back_emf_waveform"]
    assert_aligned_angles(
        payload["electrical_angle_deg"],
        current["electrical_angle_deg"],
        emf["electrical_angle_deg"],
    )
    instantaneous_power = [
        ea * ia + eb * ib + ec * ic
        for ea, eb, ec, ia, ib, ic in zip(
            emf["phase_a_V"],
            emf["phase_b_V"],
            emf["phase_c_V"],
            current["phase_a_A"],
            current["phase_b_A"],
            current["phase_c_A"],
            strict=True,
        )
    ]
    omega_mech_rad_s = 2.0 * math.pi * rated_speed_rpm / 60.0
    torque_from_power = mean(instantaneous_power) / omega_mech_rad_s
    solved_torque = mean(payload["torque_Nm"])
    return {
        "mean_electromagnetic_power_W": mean(instantaneous_power),
        "omega_mechanical_rad_s": omega_mech_rad_s,
        "torque_from_power_Nm": torque_from_power,
        "mean_solved_torque_Nm": solved_torque,
        "delta_pct": relative_delta_pct(torque_from_power, solved_torque),
        "positive_motoring_sign": torque_from_power > 0.0 and solved_torque > 0.0,
    }


def status(value: float, maximum: float) -> str:
    return "PASS" if math.isfinite(value) and value <= maximum else "FAIL"


def validate_lane_result(
    stage: str, result: dict[str, Any], protocol: dict[str, Any], *, golden: dict[str, Any], check_golden_sequence: bool = True
) -> None:
    """Reject incomplete or mismatched evidence before computing any gate."""
    matrix_key = {
        "native-standard": "cross_lane_product",
        "femm-standard": "cross_lane_product",
        "native-fine": "native_fine_convergence",
        "analytical": "low_current_power_discriminator",
    }[stage]
    grid = protocol["matrix"][matrix_key]
    count = int(grid["sample_count"])
    expected = [float(grid["electrical_angle_start_deg"]) + i * float(grid["electrical_angle_step_deg"]) for i in range(count)]

    def series(values: Any, name: str, *, angles: bool = False) -> None:
        if (
            not isinstance(values, list)
            or len(values) != count
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
        ):
            raise ValueError(f"{stage}: invalid or incomplete {name}")
        if angles and any(not math.isclose(a, b, rel_tol=0.0, abs_tol=1e-8) for a, b in zip(values, expected, strict=True)):
            raise ValueError(f"{stage}: {name} does not match frozen angle grid")

    prefix = "femm-" if stage == "femm-standard" else "magneto2d-"
    if not str(result.get("solver_name", "")).startswith(prefix):
        raise ValueError(f"{stage}: wrong solver identity")
    for key, value in {"mesh_density": "normal", "mesh_source": "native", "torque_method": "weighted_stress", "loaded_cycle_complete": True}.items():
        if result.get(key) != value:
            raise ValueError(f"{stage}: invalid {key}")
    series(result.get("electrical_angle_deg"), "electrical_angle_deg", angles=True)
    series(result.get("torque_Nm"), "torque_Nm")
    current = result.get("phase_current_waveform", {})
    series(current.get("electrical_angle_deg"), "current angle grid", angles=True)
    for phase in "abc":
        series(current.get(f"phase_{phase}_A"), f"phase_{phase}_A")
    plateau = protocol["excitation"]["analytical_current_A" if stage == "analytical" else "product_current_A"]
    scale = plateau / golden["plateau_current_A"]
    advance = protocol["excitation"]["commutation_advance_deg"]
    tolerance = protocol["gates"]["current_plateau_abs_A_max"]
    for angle, row in zip(expected, current_rows(result), strict=True):
        sector = int(((angle + advance) % 360.0) // 60.0)
        if check_golden_sequence and any(
            abs(actual - frozen * scale) > tolerance for actual, frozen in zip(row, golden["sector_table_A"][sector], strict=True)
        ):
            raise ValueError(f"{stage}: current phase sequence differs from golden table at {angle} degrees")
    if stage == "analytical":
        emf = result.get("back_emf_waveform", {})
        series(emf.get("electrical_angle_deg"), "back-EMF angle grid", angles=True)
        for phase in "abc":
            series(emf.get(f"phase_{phase}_V"), f"phase_{phase}_V")


def evaluate_numeric(protocol, raw, golden):
    for stage, artifact in raw.items():
        validate_lane_result(stage, artifact["result"], protocol, golden=golden, check_golden_sequence=False)
    native_standard = raw["native-standard"]["result"]
    native_fine = raw["native-fine"]["result"]
    femm_standard = raw["femm-standard"]["result"]
    analytical = raw["analytical"]["result"]
    assert_aligned_angles(
        native_standard["electrical_angle_deg"],
        femm_standard["electrical_angle_deg"],
        native_standard["phase_current_waveform"]["electrical_angle_deg"],
        femm_standard["phase_current_waveform"]["electrical_angle_deg"],
    )
    gates = protocol["gates"]
    current_a = float(protocol["excitation"]["product_current_A"])
    native_mean = mean(native_standard["torque_Nm"])
    femm_mean = mean(femm_standard["torque_Nm"])
    mean_delta = relative_delta_pct(native_mean, femm_mean)
    waveform_nrmse = normalized_rms_error_pct(native_standard["torque_Nm"], femm_standard["torque_Nm"])
    native_standard_ripple = ripple_pct(native_standard["torque_Nm"])
    native_fine_ripple = ripple_pct(native_fine["torque_Nm"])
    native_fine_mean = mean(native_fine["torque_Nm"])
    convergence_mean_delta = relative_delta_pct(native_mean, native_fine_mean)
    convergence_ripple_delta = abs(native_standard_ripple - native_fine_ripple)
    transitions = transition_metric(native_standard, femm_standard)
    analytical_metric = power_torque_metric(analytical, float(protocol["matrix"]["low_current_power_discriminator"]["rated_speed_rpm"]))
    property_metrics = {
        "native_standard": current_property_metrics(native_standard, current_a),
        "native_fine": current_property_metrics(native_fine, current_a),
        "femm_standard": current_property_metrics(femm_standard, current_a),
        "analytical_low_current": current_property_metrics(analytical, float(protocol["excitation"]["analytical_current_A"])),
    }
    gate_rows = [
        {
            "id": "mean_torque_delta_pct",
            "value": mean_delta,
            "maximum": gates["mean_torque_delta_pct_max"],
            "status": status(mean_delta, gates["mean_torque_delta_pct_max"]),
        },
        {
            "id": "torque_waveform_nrmse_pct",
            "value": waveform_nrmse,
            "maximum": gates["torque_waveform_nrmse_pct_max"],
            "status": status(waveform_nrmse, gates["torque_waveform_nrmse_pct_max"]),
        },
        {
            "id": "commutation_transition_delta_samples",
            "value": transitions["max_delta_samples"],
            "maximum": gates["commutation_transition_delta_samples_max"],
            "status": status(float(transitions["max_delta_samples"]), gates["commutation_transition_delta_samples_max"]),
        },
        {
            "id": "power_torque_delta_pct",
            "value": analytical_metric["delta_pct"],
            "maximum": gates["power_torque_delta_pct_max"],
            "status": status(analytical_metric["delta_pct"], gates["power_torque_delta_pct_max"])
            if analytical_metric["positive_motoring_sign"]
            else "FAIL",
        },
        {
            "id": "native_standard_to_fine_mean_torque_delta_pct",
            "value": convergence_mean_delta,
            "maximum": gates["native_standard_to_fine_mean_torque_delta_pct_max"],
            "status": status(convergence_mean_delta, gates["native_standard_to_fine_mean_torque_delta_pct_max"]),
        },
        {
            "id": "native_standard_to_fine_ripple_delta_percentage_points",
            "value": convergence_ripple_delta,
            "maximum": gates["native_standard_to_fine_ripple_delta_percentage_points_max"],
            "status": status(convergence_ripple_delta, gates["native_standard_to_fine_ripple_delta_percentage_points_max"]),
        },
    ]
    for lane, metrics in property_metrics.items():
        property_pass = (
            metrics["max_zero_sum_abs_A"] <= gates["current_zero_sum_abs_A_max"]
            and metrics["max_plateau_error_abs_A"] <= gates["current_plateau_abs_A_max"]
            and (metrics["max_zero_phase_abs_A"] <= gates["current_plateau_abs_A_max"])
            and (metrics["invalid_conduction_samples"] == 0)
        )
        gate_rows.append(
            {
                "id": f"{lane}_current_properties",
                "value": metrics,
                "maximum": {
                    "zero_sum_abs_A": gates["current_zero_sum_abs_A_max"],
                    "current_abs_A": gates["current_plateau_abs_A_max"],
                    "invalid_samples": 0,
                },
                "status": "PASS" if property_pass else "FAIL",
            }
        )
    for stage, artifact in raw.items():
        try:
            validate_lane_result(stage, artifact["result"], protocol, golden=golden)
            sequence_status, detail = ("PASS", "matches frozen golden current table")
        except ValueError as exc:
            sequence_status, detail = ("FAIL", str(exc))
        gate_rows.append(
            {
                "id": f"{stage}_golden_current_sequence",
                "value": detail,
                "maximum": "exact phase sequence within frozen current tolerance",
                "status": sequence_status,
            }
        )
    overall_status = "PASS" if all((row["status"] == "PASS" for row in gate_rows)) else "FAIL"
    evidence = {
        "status": overall_status,
        "results": {
            "native_standard_mean_torque_Nm": native_mean,
            "native_standard_torque_ripple_pct": native_standard_ripple,
            "native_fine_mean_torque_Nm": native_fine_mean,
            "native_fine_torque_ripple_pct": native_fine_ripple,
            "femm_standard_mean_torque_Nm": femm_mean,
            "femm_standard_torque_ripple_pct": ripple_pct(femm_standard["torque_Nm"]),
            "mean_torque_delta_pct": mean_delta,
            "torque_waveform_nrmse_pct": waveform_nrmse,
            "transition_alignment": transitions,
            "power_torque_discriminator": analytical_metric,
            "current_properties": property_metrics,
        },
        "gates": gate_rows,
        "limitations": [
            "ideal current-commanded 120-degree six-step only",
            "guided wye-connected inner-rotor radial-flux SPM only",
            "no PWM, current ripple, commutation overlap, dead time, Hall electronics, dynamic bus, startup, delta winding, IPM, or outrunner claim",
        ],
    }
    return evidence
