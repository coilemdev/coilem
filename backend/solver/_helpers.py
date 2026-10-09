"""Motor result aggregation and postprocessing helpers."""

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend import field_artifacts
from backend.airgap_sampling import (
    DEFAULT_AIRGAP_RING_SAMPLE_COUNT,
    airgap_band_radii_from_mesh_info,
    sample_airgap_midpoint_records_from_mesh,
)
from backend.back_emf_harmonics import (
    analyze_back_emf_harmonics,
    harmonic_limit_for_quality,
)
from backend.field_lines import build_field_line_plot
from backend.logging_utils import log_event, tagged_log
from backend.models import FieldLineFrame, MotorConfig, SlotExcitationFrame
from backend.solver_environment import solver_setting

REPO_ROOT = Path(__file__).resolve().parents[1]


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_number_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out: list[float] = []
    for value in values:
        number = _finite_number(value)
        if number is None:
            return []
        out.append(number)
    return out


def _aligned_number_list(values: Any, expected_len: int) -> list[float]:
    numbers = _finite_number_list(values)
    if expected_len and len(numbers) != expected_len:
        return []
    return numbers


def _select_magneto2d_torque_series(
    sweep: dict[str, Any],
    torque_method: str = "contour",
) -> tuple[list[float], float, str]:
    """Select the app-facing native torque waveform.

    Magneto2D reports multiple torque extractors. Contour MST is the app-facing
    signoff path; Arkkio remains available as an explicit diagnostic selection
    and as a fallback for older payloads with incomplete contour arrays.
    """
    rotor_positions = _finite_number_list(sweep.get("rotor_positions_elec_deg"))
    expected_len = len(rotor_positions)
    default_candidates = (
        ("contour", "torque_nm", "avg_torque_nm"),
        ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
        ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
    )
    candidate_orders = {
        "coenergy_fd": (
            ("coenergy_fd", "torque_coenergy_fd_nm", "avg_torque_coenergy_fd_nm"),
            ("energy_fd", "torque_energy_fd_nm", "avg_torque_energy_fd_nm"),
            ("contour", "torque_nm", "avg_torque_nm"),
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
        ),
        "energy_fd": (
            ("energy_fd", "torque_energy_fd_nm", "avg_torque_energy_fd_nm"),
            ("coenergy_fd", "torque_coenergy_fd_nm", "avg_torque_coenergy_fd_nm"),
            ("contour", "torque_nm", "avg_torque_nm"),
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
        ),
        "arkkio": (
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
            ("contour", "torque_nm", "avg_torque_nm"),
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
        ),
        "contour": (
            ("contour", "torque_nm", "avg_torque_nm"),
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
        ),
        "mst": (
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
            ("contour", "torque_nm", "avg_torque_nm"),
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
        ),
        "weighted_stress": (
            ("weighted_stress", "torque_weighted_stress_nm", "avg_torque_weighted_stress_nm"),
            ("contour", "torque_nm", "avg_torque_nm"),
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
        ),
        "weighted_stress_centered": (
            (
                "weighted_stress_centered",
                "torque_weighted_stress_centered_nm",
                "avg_torque_weighted_stress_centered_nm",
            ),
            ("contour", "torque_nm", "avg_torque_nm"),
            ("arkkio", "torque_arkkio_nm", "avg_torque_arkkio_nm"),
            ("mst", "torque_mst_nm", "avg_torque_mst_nm"),
        ),
    }
    candidates = candidate_orders.get(str(torque_method), default_candidates)
    for metric, waveform_key, avg_key in candidates:
        values = _finite_number_list(sweep.get(waveform_key))
        if not values or (expected_len and len(values) != expected_len):
            continue
        avg = _finite_number(sweep.get(avg_key))
        if avg is None:
            avg = sum(values) / len(values)
        return values, avg, metric

    fallback_avg = _finite_number(sweep.get("avg_torque_nm"))
    return [], fallback_avg if fallback_avg is not None else 0.0, "missing"


def _select_magneto2d_cogging_series(
    sweep: dict[str, Any],
    torque_method: str = "contour",
) -> tuple[list[float], str]:
    rotor_positions = _finite_number_list(sweep.get("cogging_rotor_positions_elec_deg"))
    expected_len = len(rotor_positions)
    if expected_len < 2:
        return [], "missing"

    default_candidates = (
        ("contour", "cogging_torque_contour_waveform_nm"),
        ("selected", "cogging_torque_waveform_nm"),
        ("arkkio", "cogging_torque_arkkio_waveform_nm"),
        ("mst", "cogging_torque_area_mst_waveform_nm"),
    )
    candidate_orders = {
        "arkkio": (
            ("arkkio", "cogging_torque_arkkio_waveform_nm"),
            ("selected", "cogging_torque_waveform_nm"),
            ("contour", "cogging_torque_contour_waveform_nm"),
            ("mst", "cogging_torque_area_mst_waveform_nm"),
        ),
        "contour": (
            ("contour", "cogging_torque_contour_waveform_nm"),
            ("selected", "cogging_torque_waveform_nm"),
            ("arkkio", "cogging_torque_arkkio_waveform_nm"),
            ("mst", "cogging_torque_area_mst_waveform_nm"),
        ),
        "mst": (
            ("mst", "cogging_torque_area_mst_waveform_nm"),
            ("selected", "cogging_torque_waveform_nm"),
            ("contour", "cogging_torque_contour_waveform_nm"),
            ("arkkio", "cogging_torque_arkkio_waveform_nm"),
        ),
        "weighted_stress": (
            ("weighted_stress", "cogging_torque_weighted_stress_waveform_nm"),
            ("selected", "cogging_torque_waveform_nm"),
            ("contour", "cogging_torque_contour_waveform_nm"),
            ("arkkio", "cogging_torque_arkkio_waveform_nm"),
            ("mst", "cogging_torque_area_mst_waveform_nm"),
        ),
        "weighted_stress_centered": (
            ("weighted_stress_centered", "cogging_torque_weighted_stress_centered_waveform_nm"),
            ("selected", "cogging_torque_waveform_nm"),
            ("contour", "cogging_torque_contour_waveform_nm"),
            ("arkkio", "cogging_torque_arkkio_waveform_nm"),
            ("mst", "cogging_torque_area_mst_waveform_nm"),
        ),
    }
    candidates = candidate_orders.get(str(torque_method), default_candidates)
    for metric, waveform_key in candidates:
        values = _finite_number_list(sweep.get(waveform_key))
        if values and len(values) == expected_len:
            return values, metric
    return [], "missing"


def _torque_ripple_pct(values: list[float], avg_torque: float, fallback: Any) -> float:
    if values and abs(avg_torque) > 1e-12:
        return (max(values) - min(values)) / abs(avg_torque) * 100.0
    fallback_value = _finite_number(fallback)
    return fallback_value if fallback_value is not None else 0.0


def _close_enough(a: float, b: float, *, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b), 1.0))


def _requested_phase_current_peak_a(config: MotorConfig) -> float:
    solve_params = config.solve_params
    if solve_params is None:
        return 0.0
    current = float(solve_params.current_amplitude_A)
    if solve_params.current_amplitude_convention == "rms":
        return current * math.sqrt(2.0)
    return current


def _validate_magneto2d_postprocess_cache_matches_config(
    config: MotorConfig,
    sweep_report: dict[str, Any],
    single_report: dict[str, Any],
) -> None:
    """Reject postprocess reuse when field-solve inputs changed.

    Torque method and other extraction choices may change. Geometry, excitation,
    speed-scaled waveforms, and the solved angle grid may not, because those are
    baked into the cached fields.
    """
    solve_params = config.solve_params
    if solve_params is None:
        raise ValueError("magneto2d postprocess requires solve_params")

    mismatches: list[str] = []
    cached_summary = sweep_report.get("config_summary") or single_report.get("config_summary") or {}
    if isinstance(cached_summary, dict):
        int_checks = {
            "slots": config.stator.slot_count,
            "poles": config.rotor.pole_count,
        }
        for key, expected in int_checks.items():
            cached = _finite_number(cached_summary.get(key))
            if cached is not None and int(round(cached)) != int(expected):
                mismatches.append(f"{key} cached={int(round(cached))} requested={expected}")

        float_checks = {
            "stator_od_mm": config.stator.OD_mm,
            "rotor_od_mm": config.rotor.OD_mm,
            "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
            "stack_length_mm": config.stator.stack_length_mm,
        }
        for key, expected_float in float_checks.items():
            cached = _finite_number(cached_summary.get(key))
            if cached is not None and not _close_enough(cached, float(expected_float), abs_tol=1e-6):
                mismatches.append(f"{key} cached={cached:g} requested={float(expected_float):g}")

        cached_current_angle = _finite_number(cached_summary.get("current_angle_deg"))
        if cached_current_angle is not None and not _close_enough(
            cached_current_angle,
            float(solve_params.current_angle_deg),
            abs_tol=1e-6,
        ):
            mismatches.append(f"current_angle_deg cached={cached_current_angle:g} requested={float(solve_params.current_angle_deg):g}")

    operating_point = sweep_report.get("operating_point")
    if isinstance(operating_point, dict):
        cached_current_peak = _finite_number(operating_point.get("resolved_phase_current_peak_a"))
        requested_current_peak = _requested_phase_current_peak_a(config)
        if cached_current_peak is not None and not _close_enough(
            cached_current_peak,
            requested_current_peak,
            rel_tol=1e-5,
            abs_tol=1e-3,
        ):
            mismatches.append(f"phase_current_peak_a cached={cached_current_peak:g} requested={requested_current_peak:g}")

        cached_resolved_angle = _finite_number(operating_point.get("resolved_current_angle_deg"))
        if cached_resolved_angle is not None and not _close_enough(
            cached_resolved_angle,
            float(solve_params.current_angle_deg),
            abs_tol=1e-6,
        ):
            mismatches.append(f"resolved_current_angle_deg cached={cached_resolved_angle:g} requested={float(solve_params.current_angle_deg):g}")

        requested_mode = solve_params.excitation_mode
        cached_mode = str(operating_point.get("excitation_mode") or "sinusoidal")
        if cached_mode != requested_mode:
            mismatches.append(
                f"excitation_mode cached={cached_mode} requested={requested_mode}"
            )
        if requested_mode == "ideal_six_step_120":
            cached_advance = _finite_number(
                operating_point.get("commutation_advance_deg")
            )
            if cached_advance is None or not _close_enough(
                cached_advance,
                float(solve_params.commutation_advance_deg),
                abs_tol=1e-9,
            ):
                mismatches.append(
                    "commutation_advance_deg "
                    f"cached={cached_advance!r} requested={float(solve_params.commutation_advance_deg):g}"
                )
            cached_connection = operating_point.get("phase_connection")
            if cached_connection != solve_params.phase_connection:
                mismatches.append(
                    "phase_connection "
                    f"cached={cached_connection!r} requested={solve_params.phase_connection}"
                )

    sweep = sweep_report.get("sweep")
    if isinstance(sweep, dict):
        cached_speed = _finite_number(sweep.get("rated_speed_rpm"))
        if cached_speed is not None and int(round(cached_speed)) != int(solve_params.rated_speed_rpm):
            mismatches.append(f"rated_speed_rpm cached={int(round(cached_speed))} requested={int(solve_params.rated_speed_rpm)}")

        # The solved angle grid is part of the cache. Post-process rebuilds
        # must reuse that grid even if the current UI solve-quality preset
        # would request a different fresh-solve position count.

    if mismatches:
        raise ValueError("cached fields do not match requested field-solve inputs: " + "; ".join(mismatches) + ". Run Solve instead.")


def _require_cached_torque_method_available(sweep: dict[str, Any], torque_method: str) -> None:
    rotor_positions = _finite_number_list(sweep.get("rotor_positions_elec_deg"))
    expected_len = len(rotor_positions)
    method_to_waveform = {
        "arkkio": "torque_arkkio_nm",
        "contour": "torque_nm",
        "mst": "torque_mst_nm",
        "energy_fd": "torque_energy_fd_nm",
        "coenergy_fd": "torque_coenergy_fd_nm",
        "weighted_stress": "torque_weighted_stress_nm",
        "weighted_stress_centered": "torque_weighted_stress_centered_nm",
    }
    waveform_key = method_to_waveform.get(torque_method)
    if waveform_key is None:
        return
    values = _finite_number_list(sweep.get(waveform_key))
    if values and (not expected_len or len(values) == expected_len):
        return
    raise ValueError(
        "cached field reports do not contain the requested torque method "
        f"{torque_method!r}. Select that method in Post-process and run Solve "
        "once to populate the cached postprocess series."
    )


def _estimate_nonuniform_derivative(
    x_prev: float,
    y_prev: float,
    x_curr: float,
    y_curr: float,
    x_next: float,
    y_next: float,
) -> float:
    """Estimate dy/dx at x_curr using the closest samples on both sides."""
    return (
        y_prev * (x_curr - x_next) / ((x_prev - x_curr) * (x_prev - x_next))
        + y_curr * ((1.0 / (x_curr - x_prev)) + (1.0 / (x_curr - x_next)))
        + y_next * (x_curr - x_prev) / ((x_next - x_prev) * (x_next - x_curr))
    )


def _estimate_live_back_emf_at_angle(
    target_key: int,
    noload_flux_linkage_samples: dict[int, tuple[float, float, float, float]],
    omega_elec_rad_s: float,
) -> tuple[float, float, float] | None:
    """Estimate the native no-load back-EMF at one electrical angle.

    Native FEM solves loaded and no-load positions together inside one parallel
    sweep. Samples complete out of angle order, so we approximate dPsi/dtheta
    from the nearest solved neighbors currently available around the target.
    This keeps the live back-EMF chart filling in while the full sweep is still
    running, then the final report replaces it with the exact full-cycle curve.
    """
    if target_key not in noload_flux_linkage_samples or len(noload_flux_linkage_samples) < 3:
        return None

    ordered_samples = sorted(
        noload_flux_linkage_samples.items(),
        key=lambda item: item[1][0],
    )
    target_idx = next(
        (idx for idx, (sample_key, _) in enumerate(ordered_samples) if sample_key == target_key),
        None,
    )
    if target_idx is None:
        return None

    sample_count = len(ordered_samples)
    (_, (target_angle_deg, psi_a, psi_b, psi_c)) = ordered_samples[target_idx]
    (_, (prev_angle_deg, prev_psi_a, prev_psi_b, prev_psi_c)) = ordered_samples[target_idx - 1]
    (_, (next_angle_deg, next_psi_a, next_psi_b, next_psi_c)) = ordered_samples[(target_idx + 1) % sample_count]

    x_curr = math.radians(target_angle_deg)
    x_prev = math.radians(prev_angle_deg)
    x_next = math.radians(next_angle_deg)
    if x_prev >= x_curr:
        x_prev -= math.tau
    if x_next <= x_curr:
        x_next += math.tau

    dpsi_a = _estimate_nonuniform_derivative(x_prev, prev_psi_a, x_curr, psi_a, x_next, next_psi_a)
    dpsi_b = _estimate_nonuniform_derivative(x_prev, prev_psi_b, x_curr, psi_b, x_next, next_psi_b)
    dpsi_c = _estimate_nonuniform_derivative(x_prev, prev_psi_c, x_curr, psi_c, x_next, next_psi_c)
    return (
        -dpsi_a * omega_elec_rad_s,
        -dpsi_b * omega_elec_rad_s,
        -dpsi_c * omega_elec_rad_s,
    )


def _finite_difference_waveform(values: list[float], dx: float, *, periodic: bool) -> list[float]:
    """Mirror magneto2d's finite-difference helper for Python-built sweeps."""
    if not values:
        return []
    if not math.isfinite(dx) or abs(dx) <= 1e-12:
        return [0.0 for _ in values]
    if len(values) == 1:
        return [0.0]
    if len(values) == 2:
        slope = (values[1] - values[0]) / dx
        return [slope, slope]

    out: list[float] = []
    n = len(values)
    for idx in range(n):
        if periodic:
            prev_value = values[(idx + n - 1) % n]
            next_value = values[(idx + 1) % n]
            out.append((next_value - prev_value) / (2.0 * dx))
        elif idx == 0:
            out.append((values[1] - values[0]) / dx)
        elif idx + 1 == n:
            out.append((values[n - 1] - values[n - 2]) / dx)
        else:
            out.append((values[idx + 1] - values[idx - 1]) / (2.0 * dx))
    return out


def _back_emf_from_flux_linkage(
    psi_wb: list[float],
    d_theta_elec_rad: float,
    omega_scale: float,
    *,
    periodic: bool,
) -> list[float]:
    return [
        dpsi_dtheta * omega_scale
        for dpsi_dtheta in _finite_difference_waveform(
            psi_wb,
            d_theta_elec_rad,
            periodic=periodic,
        )
    ]


def _waveform_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _waveform_peak_abs(values: list[float]) -> float:
    finite_values = [abs(value) for value in values if math.isfinite(value)]
    return max(finite_values, default=0.0)


def _cogging_period_electrical_deg(slot_count: int, pole_count: int) -> float:
    if slot_count <= 0 or pole_count <= 0:
        return 0.0
    pole_pairs = pole_count / 2.0
    mechanical_period_deg = 360.0 / math.lcm(slot_count, pole_count)
    return mechanical_period_deg * pole_pairs


def _covers_integer_cogging_period(
    sweep_span_deg: float,
    slot_count: int,
    pole_count: int,
) -> bool:
    period = _cogging_period_electrical_deg(slot_count, pole_count)
    if period <= 0.0 or not math.isfinite(period) or not math.isfinite(sweep_span_deg):
        return False
    periods = sweep_span_deg / period
    return abs(periods - round(periods)) <= 1.0e-9


def _centered_no_load_cogging_waveform(
    values: list[float] | None,
    *,
    current_a: float,
    sweep_span_deg: float,
    slot_count: int,
    pole_count: int,
) -> list[float] | None:
    if not values or abs(current_a) > 1.0e-12 or not _covers_integer_cogging_period(sweep_span_deg, slot_count, pole_count):
        return None
    mean = _waveform_mean(values)
    return [value - mean for value in values]


def _fundamental_peak(values: list[float], angles_elec_deg: list[float]) -> float:
    if len(values) < 3 or len(values) != len(angles_elec_deg):
        return 0.0
    real = 0.0
    imag = 0.0
    for angle_deg, value in zip(angles_elec_deg, values):
        angle_rad = math.radians(angle_deg)
        real += value * math.cos(angle_rad)
        imag += value * math.sin(angle_rad)
    scale = 2.0 / len(values)
    return math.hypot(real * scale, imag * scale)


def _harmonic_peaks(
    values: list[float],
    angles_elec_deg: list[float],
    *,
    k_max: int = 6,
) -> dict[str, float]:
    if len(values) < 3 or len(values) != len(angles_elec_deg):
        return {}
    out: dict[str, float] = {}
    scale = 2.0 / len(values)
    for k in range(1, k_max + 1):
        real = 0.0
        imag = 0.0
        for angle_deg, value in zip(angles_elec_deg, values):
            angle_rad = math.radians(k * angle_deg)
            real += value * math.cos(angle_rad)
            imag += value * math.sin(angle_rad)
        out[str(k)] = math.hypot(real * scale, imag * scale)
    return out


def _thd_pct_from_harmonics(harmonics: dict[str, float]) -> float | None:
    fundamental = _finite_number(harmonics.get("1"))
    if fundamental is None or fundamental <= 1.0e-12:
        return None
    residual_sq = sum((harmonics.get(str(k)) or 0.0) ** 2 for k in range(2, 7))
    return math.sqrt(residual_sq) / fundamental * 100.0


def _result_float(report: dict[str, Any], key: str, default: float = 0.0) -> float:
    results = report.get("results", {})
    value = _finite_number(results.get(key))
    return value if value is not None else default


def _energy_series(
    reports: list[dict[str, Any]],
    key: str,
) -> list[float]:
    values: list[float] = []
    for report in reports:
        energy = report.get("results", {}).get("energy_functional")
        if not isinstance(energy, dict):
            return []
        value = _finite_number(energy.get(key))
        if value is None:
            return []
        values.append(value)
    return values


def _optional_result_series(
    reports: list[dict[str, Any]],
    key: str,
) -> list[float] | None:
    values: list[float] = []
    for report in reports:
        value = _finite_number(report.get("results", {}).get(key))
        if value is None:
            return None
        values.append(value)
    return values


def _config_with_phase_current(config: MotorConfig, current_a: float) -> MotorConfig:
    clone = config.model_copy(deep=True)
    if clone.solve_params is None:
        raise ValueError("magneto2d solve requires solve_params")
    clone.solve_params.current_amplitude_A = current_a
    return clone


def _field_line_frame_from_report(
    report: dict[str, Any],
    angle_elec_deg: float,
    noload_report: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a per-angle field frame from a raw Magneto2D report."""
    try:
        loaded_plot = build_field_line_plot(report)
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if loaded_plot is None:
        return None

    frame = loaded_plot.model_dump(mode="json")
    frame["angle_deg"] = float(angle_elec_deg)
    raw_mesh_info = report.get("mesh_info")
    if isinstance(raw_mesh_info, dict):
        frame["mesh_info"] = {**raw_mesh_info, **dict(frame.get("mesh_info") or {})}


    if noload_report is not None:
        try:
            noload_plot = build_field_line_plot(noload_report)
        except (KeyError, TypeError, ValueError, IndexError):
            noload_plot = None
        if noload_plot is not None:
            noload_frame = noload_plot.model_dump(mode="json")
            raw_noload_mesh_info = noload_report.get("mesh_info")
            if isinstance(raw_noload_mesh_info, dict):
                noload_frame["mesh_info"] = {
                    **raw_noload_mesh_info,
                    **dict(noload_frame.get("mesh_info") or {}),
                }
            frame["noload_plot"] = noload_frame

    return frame


def _frame_span_deg(frame: dict[str, Any]) -> float:
    span = _finite_number(frame.get("total_span_deg"))
    if span is None:
        mesh_info = frame.get("mesh_info")
        if isinstance(mesh_info, dict):
            span = _finite_number(mesh_info.get("total_span_deg"))
    return span if span is not None and span > 0.0 else 360.0


def _midpoint_airgap_records_from_frame(
    frame: dict[str, Any],
    raw_mesh_info: Any,
) -> dict[str, list[float]] | None:
    mesh_info = raw_mesh_info if isinstance(raw_mesh_info, dict) else frame.get("mesh_info")
    band = airgap_band_radii_from_mesh_info(mesh_info if isinstance(mesh_info, dict) else None)
    if band is None:
        return None
    inner_radius_mm, outer_radius_mm = band
    return sample_airgap_midpoint_records_from_mesh(
        nodes_mm=frame.get("nodes_mm") or [],
        triangles=frame.get("triangles") or [],
        regions=[str(region).lower() for region in frame.get("regions", [])],
        element_bx_t=frame.get("element_bx_t") or [],
        element_by_t=frame.get("element_by_t") or [],
        airgap_inner_radius_mm=inner_radius_mm,
        airgap_outer_radius_mm=outer_radius_mm,
        sample_count=DEFAULT_AIRGAP_RING_SAMPLE_COUNT,
        span_deg=_frame_span_deg(frame),
    )


def _field_line_frames_from_reports(
    loaded_reports: list[dict[str, Any]],
    angles_elec_deg: list[float],
    no_load_reports: list[dict[str, Any]] | None = None,
    *,
    include_noload_plot: bool = True,
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for idx, report in enumerate(loaded_reports):
        if idx >= len(angles_elec_deg):
            break
        noload_report = (
            no_load_reports[idx]
            if include_noload_plot and no_load_reports is not None and idx < len(no_load_reports)
            else None
        )
        frame = _field_line_frame_from_report(report, angles_elec_deg[idx], noload_report)
        if frame is not None:
            frames.append(frame)
    return frames


def _field_line_frame_json(frame: FieldLineFrame | dict[str, Any]) -> dict[str, Any]:
    if isinstance(frame, FieldLineFrame):
        return frame.model_dump(mode="json")
    return dict(frame)


def _attach_field_frame_artifacts(
    frames: Sequence[FieldLineFrame | dict[str, Any]] | None,
    solve_cache_dir: Path | str | None,
    *,
    start_idx: int = 0,
) -> list[FieldLineFrame] | None:
    """Persist full native field frames and keep lightweight refs in SolveResult."""

    if not frames:
        return None

    artifact_ready: list[FieldLineFrame] = []
    for idx, frame in enumerate(frames, start=start_idx):
        frame_payload = _field_line_frame_json(frame)
        try:
            elec_angle_deg = float(frame_payload.get("angle_deg", idx))
        except (TypeError, ValueError):
            elec_angle_deg = float(idx)
        if not isinstance(frame_payload.get("field_frame_artifact"), dict):
            artifact_ref = field_artifacts.write_field_line_frame_artifact(
                frame_payload,
                Path(solve_cache_dir).expanduser() if solve_cache_dir is not None else None,
                pos_idx=idx,
                elec_angle_deg=elec_angle_deg,
            )
            if artifact_ref is not None:
                frame_payload["field_frame_artifact"] = artifact_ref
                frame_payload.setdefault("full_field_frame_artifact", artifact_ref)
        try:
            artifact_ready.append(FieldLineFrame.model_validate(frame_payload))
        except Exception:
            continue
    return artifact_ready or None


def _slim_captured_field_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """Keep only data needed to locate/fetch a persisted native field frame."""

    keep_keys = {
        "angle_deg",
        "config_summary",
        "mesh_info",
        "n_pole_pitches",
        "total_span_deg",
        "airgap_brbt",
        "airgap_b_records",
        "airgap_b_stats",
        "airgap_b_artifact",
        "field_frame_artifact",
        "full_field_frame_artifact",
    }
    return {key: value for key, value in frame.items() if key in keep_keys and value is not None}


def _slim_progress_field_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """Keep live contour/airgap data, but drop raw mesh-sized arrays."""

    drop_keys = {
        "nodes_mm",
        "triangles",
        "regions",
        "element_b_mag_t",
        "element_bx_t",
        "element_by_t",
    }
    payload = {key: value for key, value in frame.items() if key not in drop_keys}
    noload_plot = payload.get("noload_plot")
    if isinstance(noload_plot, dict):
        payload["noload_plot"] = _slim_progress_field_frame(noload_plot)
    return payload


def _field_line_frames_from_cache(
    solve_cache_dir: Path | str | None,
    angles_elec_deg: list[float],
) -> list[dict[str, Any]]:
    if solve_cache_dir is None:
        return []
    cache_dir = Path(solve_cache_dir).expanduser()
    if not cache_dir.is_dir():
        return []

    frames: list[dict[str, Any]] = []
    for idx, angle_elec_deg in enumerate(angles_elec_deg):
        loaded_path = cache_dir / f"sweep_pos{idx:03d}_loaded_report.json"
        if not loaded_path.exists():
            continue
        try:
            loaded_report = json.loads(loaded_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        no_load_report: dict[str, Any] | None = None
        noload_path = cache_dir / f"sweep_pos{idx:03d}_noload_report.json"
        if noload_path.exists():
            try:
                no_load_report = json.loads(noload_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                no_load_report = None

        frame = _field_line_frame_from_report(
            loaded_report,
            angle_elec_deg,
            no_load_report,
        )
        if frame is not None:
            frames.append(frame)
    return frames


def _slot_excitation_frame_from_report(
    report: dict[str, Any],
    angle_elec_deg: float,
) -> dict[str, Any] | None:
    results = report.get("results")
    if not isinstance(results, dict):
        return None
    contributions = results.get("slot_excitation_contributions")
    if not isinstance(contributions, list) or not contributions:
        return None

    phase_current = _finite_number_list(results.get("phase_current_a"))
    frame: dict[str, Any] = {
        "angle_deg": float(angle_elec_deg),
        "source_current_angle_deg": _finite_number(results.get("source_current_angle_deg")),
        "phase_current_a": phase_current if phase_current else None,
        "contributions": contributions,
    }
    return frame


def _slot_excitation_frames_from_reports(
    loaded_reports: list[dict[str, Any]],
    angles_elec_deg: list[float],
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for idx, report in enumerate(loaded_reports):
        if idx >= len(angles_elec_deg):
            break
        frame = _slot_excitation_frame_from_report(report, angles_elec_deg[idx])
        if frame is not None:
            frames.append(frame)
    return frames


def _slot_excitation_frames_from_cache(
    solve_cache_dir: Path | str | None,
    angles_elec_deg: list[float],
) -> list[dict[str, Any]]:
    if solve_cache_dir is None:
        return []
    cache_dir = Path(solve_cache_dir).expanduser()
    if not cache_dir.is_dir():
        return []

    frames: list[dict[str, Any]] = []
    for idx, angle_elec_deg in enumerate(angles_elec_deg):
        loaded_path = cache_dir / f"sweep_pos{idx:03d}_loaded_report.json"
        if not loaded_path.exists():
            continue
        try:
            loaded_report = json.loads(loaded_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        frame = _slot_excitation_frame_from_report(loaded_report, angle_elec_deg)
        if frame is not None:
            frames.append(frame)
    return frames


def _truthy_env(name: str) -> bool:
    raw = solver_setting(name)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _slot_flux_diagnostics_enabled() -> bool:
    return _truthy_env("COILEM_MAGNETO2D_SLOT_FLUX_DIAGNOSTICS") or _truthy_env(
        "MAGNETO2D_SLOT_FLUX_DIAGNOSTICS"
    )


def _slot_flux_target_angles() -> list[float]:
    raw = (
        solver_setting("COILEM_MAGNETO2D_SLOT_FLUX_DIAGNOSTIC_ANGLES_DEG")
        or solver_setting("MAGNETO2D_SLOT_FLUX_DIAGNOSTIC_ANGLES_DEG")
        or ""
    )
    targets: list[float] = []
    for chunk in raw.replace(";", ",").split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            targets.append(float(text))
        except ValueError:
            tagged_log(
                "[SLOT-FLUX-DIAG] ignored invalid diagnostic angle "
                f"{text!r}",
                flush=True,
            )
    return targets


def _slot_flux_angle_selected(angle_deg: float, targets: list[float]) -> bool:
    if not targets:
        return True
    return any(
        abs(((angle_deg - target + 180.0) % 360.0) - 180.0) <= 1.0e-6
        for target in targets
    )


def _slot_flux_linkage_frame_from_report(
    report: dict[str, Any],
    angle_elec_deg: float,
) -> dict[str, Any] | None:
    results = report.get("results")
    if not isinstance(results, dict):
        return None
    contributions = results.get("slot_flux_linkage_contributions")
    if not isinstance(contributions, list):
        return None
    return {
        "angle_deg": float(angle_elec_deg),
        "flux_linkage_a_wb": _finite_number(results.get("flux_linkage_a_wb")),
        "flux_linkage_b_wb": _finite_number(results.get("flux_linkage_b_wb")),
        "flux_linkage_c_wb": _finite_number(results.get("flux_linkage_c_wb")),
        "contributions": contributions,
    }


def _slot_flux_linkage_frames_from_reports(
    reports: list[dict[str, Any]] | None,
    angles_elec_deg: list[float] | None,
) -> list[dict[str, Any]]:
    if not reports or not angles_elec_deg:
        return []
    targets = _slot_flux_target_angles()
    frames: list[dict[str, Any]] = []
    for idx, report in enumerate(reports):
        if idx >= len(angles_elec_deg):
            break
        angle_elec_deg = angles_elec_deg[idx]
        if not _slot_flux_angle_selected(angle_elec_deg, targets):
            continue
        frame = _slot_flux_linkage_frame_from_report(report, angle_elec_deg)
        if frame is not None:
            frames.append(frame)
    return frames


def _validated_field_line_frames(frames: Any) -> list[FieldLineFrame] | None:
    if not isinstance(frames, list) or not frames:
        return None
    validated: list[FieldLineFrame] = []
    for frame in frames:
        try:
            validated.append(FieldLineFrame.model_validate(frame))
        except Exception:
            continue
    return validated or None


def _validated_slot_excitation_frames(frames: Any) -> list[SlotExcitationFrame] | None:
    if not isinstance(frames, list) or not frames:
        return None
    validated: list[SlotExcitationFrame] = []
    for frame in frames:
        try:
            validated.append(SlotExcitationFrame.model_validate(frame))
        except Exception:
            continue
    return validated or None


def _aggregate_per_angle_mesh_sweep(
    config: MotorConfig,
    loaded_reports: list[dict[str, Any]],
    no_load_reports: list[dict[str, Any]] | None,
    angles_elec_deg: list[float],
    *,
    no_load_angles_elec_deg: list[float] | None = None,
    mesh_generation_time_ms: int,
    mesh_label: str = "gmsh",
    include_visual_frames: bool = True,
    include_no_load_field_frames: bool | None = None,
    precomputed_field_line_frames: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not loaded_reports:
        raise ValueError("per-angle Gmsh mesh sweep did not produce any loaded reports")
    if config.solve_params is None:
        raise ValueError("magneto2d solve requires solve_params")
    if include_no_load_field_frames is None:
        include_no_load_field_frames = bool(
            getattr(config.solve_params, "stream_noload_field_lines", False)
        )

    n_positions = len(loaded_reports)
    if len(angles_elec_deg) != n_positions:
        raise ValueError("loaded report count must match loaded angle grid")
    if no_load_reports and no_load_angles_elec_deg is None:
        no_load_angles_elec_deg = angles_elec_deg
    if no_load_reports and len(no_load_angles_elec_deg or []) != len(no_load_reports):
        raise ValueError("no-load report count must match no-load angle grid")

    pole_pairs = max(1, config.rotor.pole_count // 2)
    span_deg = (
        360.0
        if n_positions <= 1
        else (
            (angles_elec_deg[1] - angles_elec_deg[0]) * n_positions
            if abs((angles_elec_deg[-1] + (angles_elec_deg[1] - angles_elec_deg[0])) - 360.0) < 1e-6
            else angles_elec_deg[-1]
        )
    )
    periodic = span_deg >= 360.0 - 1e-6 and n_positions >= 3
    d_theta_elec = math.radians(angles_elec_deg[1] - angles_elec_deg[0]) if n_positions >= 2 else 0.0
    no_load_n_positions = len(no_load_reports or [])
    no_load_span_deg = (
        span_deg
        if not no_load_reports or not no_load_angles_elec_deg
        else (
            360.0
            if no_load_n_positions <= 1
            else (
                (no_load_angles_elec_deg[1] - no_load_angles_elec_deg[0]) * no_load_n_positions
                if abs((no_load_angles_elec_deg[-1] + (no_load_angles_elec_deg[1] - no_load_angles_elec_deg[0])) - 360.0) < 1e-6
                else no_load_angles_elec_deg[-1]
            )
        )
    )
    no_load_periodic = no_load_span_deg >= 360.0 - 1e-6 and no_load_n_positions >= 3
    d_theta_elec_no_load = (
        math.radians(no_load_angles_elec_deg[1] - no_load_angles_elec_deg[0])
        if no_load_reports and no_load_angles_elec_deg and no_load_n_positions >= 2
        else d_theta_elec
    )
    d_theta_mech = d_theta_elec / pole_pairs if pole_pairs else d_theta_elec
    omega_mech = 2.0 * math.pi * config.solve_params.rated_speed_rpm / 60.0
    omega_elec = omega_mech * pole_pairs

    torque_contour = [_result_float(report, "torque_contour_nm", _result_float(report, "torque_nm")) for report in loaded_reports]
    current_peak_a = _requested_phase_current_peak_a(config)
    torque_contour_centered = _centered_no_load_cogging_waveform(
        torque_contour,
        current_a=current_peak_a,
        sweep_span_deg=span_deg,
        slot_count=config.stator.slot_count,
        pole_count=config.rotor.pole_count,
    )
    torque_mst = [_result_float(report, "torque_area_mst_nm") for report in loaded_reports]
    torque_arkkio = [_result_float(report, "torque_arkkio_nm") for report in loaded_reports]
    torque_weighted_stress = _optional_result_series(loaded_reports, "torque_weighted_stress_nm")
    torque_weighted_stress_centered = _optional_result_series(
        loaded_reports,
        "torque_weighted_stress_centered_nm",
    )
    if torque_weighted_stress_centered is None:
        torque_weighted_stress_centered = _centered_no_load_cogging_waveform(
            torque_weighted_stress,
            current_a=current_peak_a,
            sweep_span_deg=span_deg,
            slot_count=config.stator.slot_count,
            pole_count=config.rotor.pole_count,
        )

    loaded_psi_a = [_result_float(report, "flux_linkage_a_wb") for report in loaded_reports]
    loaded_psi_b = [_result_float(report, "flux_linkage_b_wb") for report in loaded_reports]
    loaded_psi_c = [_result_float(report, "flux_linkage_c_wb") for report in loaded_reports]

    if no_load_reports:
        no_load_psi_a = [_result_float(report, "flux_linkage_a_wb") for report in no_load_reports]
        no_load_psi_b = [_result_float(report, "flux_linkage_b_wb") for report in no_load_reports]
        no_load_psi_c = [_result_float(report, "flux_linkage_c_wb") for report in no_load_reports]
        no_load_torque_contour = [_result_float(report, "torque_contour_nm", _result_float(report, "torque_nm")) for report in no_load_reports]
        no_load_torque_contour_centered = _centered_no_load_cogging_waveform(
            no_load_torque_contour,
            current_a=0.0,
            sweep_span_deg=no_load_span_deg,
            slot_count=config.stator.slot_count,
            pole_count=config.rotor.pole_count,
        )
        no_load_torque_mst = [_result_float(report, "torque_area_mst_nm") for report in no_load_reports]
        no_load_torque_arkkio = [_result_float(report, "torque_arkkio_nm") for report in no_load_reports]
        no_load_torque_weighted_stress = _optional_result_series(
            no_load_reports,
            "torque_weighted_stress_nm",
        )
        no_load_torque_weighted_stress_centered = _optional_result_series(
            no_load_reports,
            "torque_weighted_stress_centered_nm",
        )
        if no_load_torque_weighted_stress_centered is None:
            no_load_torque_weighted_stress_centered = _centered_no_load_cogging_waveform(
                no_load_torque_weighted_stress,
                current_a=0.0,
                sweep_span_deg=no_load_span_deg,
                slot_count=config.stator.slot_count,
                pole_count=config.rotor.pole_count,
            )
        no_load_iters = [int(report.get("solve_info", {}).get("nonlinear_iterations", 0) or 0) for report in no_load_reports]
    else:
        no_load_psi_a = [0.0 for _ in loaded_reports]
        no_load_psi_b = [0.0 for _ in loaded_reports]
        no_load_psi_c = [0.0 for _ in loaded_reports]
        no_load_torque_contour = []
        no_load_torque_contour_centered = None
        no_load_torque_mst = []
        no_load_torque_arkkio = []
        no_load_torque_weighted_stress = None
        no_load_torque_weighted_stress_centered = None
        no_load_iters = [0 for _ in loaded_reports]

    cogging_method = str(getattr(config.solve_params, "torque_method", "") or "contour").strip().lower().replace("-", "_")
    cogging_candidates: dict[str, list[float] | None] = {
        "contour": no_load_torque_contour,
        "native": no_load_torque_contour,
        "mst": no_load_torque_mst,
        "area_mst": no_load_torque_mst,
        "arkkio": no_load_torque_arkkio,
        "weighted_stress": no_load_torque_weighted_stress,
        "weighted_stress_centered": no_load_torque_weighted_stress_centered,
    }
    cogging_torque_waveform = cogging_candidates.get(cogging_method)
    if not cogging_torque_waveform:
        cogging_torque_waveform = (
            no_load_torque_arkkio
            or no_load_torque_contour
            or no_load_torque_mst
            or no_load_torque_weighted_stress
            or no_load_torque_weighted_stress_centered
        )
    cogging_torque_peak_abs = _waveform_peak_abs(cogging_torque_waveform) if cogging_torque_waveform else None

    loaded_emf_a = _back_emf_from_flux_linkage(
        loaded_psi_a,
        d_theta_elec,
        omega_mech,
        periodic=periodic,
    )
    loaded_emf_b = _back_emf_from_flux_linkage(
        loaded_psi_b,
        d_theta_elec,
        omega_mech,
        periodic=periodic,
    )
    loaded_emf_c = _back_emf_from_flux_linkage(
        loaded_psi_c,
        d_theta_elec,
        omega_mech,
        periodic=periodic,
    )
    no_load_emf_a = _back_emf_from_flux_linkage(
        no_load_psi_a,
        d_theta_elec_no_load,
        omega_mech,
        periodic=no_load_periodic,
    )
    no_load_emf_b = _back_emf_from_flux_linkage(
        no_load_psi_b,
        d_theta_elec_no_load,
        omega_mech,
        periodic=no_load_periodic,
    )
    no_load_emf_c = _back_emf_from_flux_linkage(
        no_load_psi_c,
        d_theta_elec_no_load,
        omega_mech,
        periodic=no_load_periodic,
    )
    no_load_emf_a_physical = _back_emf_from_flux_linkage(
        no_load_psi_a,
        d_theta_elec_no_load,
        omega_elec,
        periodic=no_load_periodic,
    )
    no_load_emf_b_physical = _back_emf_from_flux_linkage(
        no_load_psi_b,
        d_theta_elec_no_load,
        omega_elec,
        periodic=no_load_periodic,
    )
    no_load_emf_c_physical = _back_emf_from_flux_linkage(
        no_load_psi_c,
        d_theta_elec_no_load,
        omega_elec,
        periodic=no_load_periodic,
    )
    field_line_frames = (
        precomputed_field_line_frames
        if precomputed_field_line_frames is not None
        else (
            _field_line_frames_from_reports(
                loaded_reports,
                angles_elec_deg,
                no_load_reports if no_load_reports else None,
                include_noload_plot=include_no_load_field_frames,
            )
            if include_visual_frames
            else []
        )
    )
    slot_excitation_frames = (
        _slot_excitation_frames_from_reports(
            loaded_reports,
            angles_elec_deg,
        )
        if include_visual_frames
        else []
    )
    phase_current_samples: list[list[float]] = []
    for report in loaded_reports:
        results = report.get("results")
        sample = (
            _finite_number_list(results.get("phase_current_a"))
            if isinstance(results, dict)
            else []
        )
        if len(sample) != 3:
            phase_current_samples = []
            break
        phase_current_samples.append(sample)
    slot_flux_linkage_frames_enabled = _slot_flux_diagnostics_enabled()
    loaded_slot_flux_linkage_frames = (
        _slot_flux_linkage_frames_from_reports(
            loaded_reports,
            angles_elec_deg,
        )
        if slot_flux_linkage_frames_enabled
        else []
    )
    no_load_slot_flux_linkage_frames = (
        _slot_flux_linkage_frames_from_reports(
            no_load_reports,
            no_load_angles_elec_deg,
        )
        if slot_flux_linkage_frames_enabled and no_load_reports
        else []
    )

    potential_energy = _energy_series(loaded_reports, "potential_energy_j")
    coenergy = _energy_series(loaded_reports, "coenergy_j")
    field_energy = _energy_series(loaded_reports, "field_energy_j")
    current_source_work = _energy_series(loaded_reports, "current_source_work_j")
    pm_source_work = _energy_series(loaded_reports, "pm_source_work_j")
    pm_self_energy = _energy_series(loaded_reports, "pm_self_energy_j")
    potential_energy_with_pm_self = _energy_series(
        loaded_reports,
        "potential_energy_with_pm_self_j",
    )
    torque_energy_fd = (
        [-value for value in _finite_difference_waveform(potential_energy, d_theta_mech, periodic=periodic)] if potential_energy else None
    )
    torque_coenergy_fd = _finite_difference_waveform(coenergy, d_theta_mech, periodic=periodic) if coenergy else None

    # Finite-difference torque decomposition.
    # Compute per-component FD torques so we can see which energy component
    # carries the angle dependence on a loaded run. The relationship:
    #   potential = field - pm_source_work - current_source_work
    # implies
    #   torque_energy_fd = -d(potential)/dtheta
    #                    = -d(field)/dtheta + d(pm_source_work)/dtheta + d(current_source_work)/dtheta
    # so torque_energy_fd should equal sum of the component series with the
    # appropriate signs. If one component is missing/zero on loaded, the
    # average will reflect that.
    torque_field_fd = _finite_difference_waveform(field_energy, d_theta_mech, periodic=periodic) if field_energy else None
    torque_pm_source_work_fd = _finite_difference_waveform(pm_source_work, d_theta_mech, periodic=periodic) if pm_source_work else None
    torque_current_source_work_fd = _finite_difference_waveform(current_source_work, d_theta_mech, periodic=periodic) if current_source_work else None

    avg_torque_field_fd_nm = _waveform_mean(torque_field_fd) if torque_field_fd else None
    avg_torque_pm_source_work_fd_nm = _waveform_mean(torque_pm_source_work_fd) if torque_pm_source_work_fd else None
    avg_torque_current_source_work_fd_nm = _waveform_mean(torque_current_source_work_fd) if torque_current_source_work_fd else None

    # One-line decomposition log so a loaded solve immediately surfaces
    # which component is (or isn't) tracking angle-dependence.
    avg_torque_energy_fd_nm_log = _waveform_mean(torque_energy_fd) if torque_energy_fd else None
    avg_torque_arkkio_log = _waveform_mean(torque_arkkio) if torque_arkkio else None
    fd_decomp_message = (
        "finite-difference torque decomposition: "
        f"arkkio_avg={avg_torque_arkkio_log!r} Nm | "
        f"energy_fd_avg={avg_torque_energy_fd_nm_log!r} Nm | "
        f"field_fd_avg={avg_torque_field_fd_nm!r} Nm | "
        f"pm_source_fd_avg={avg_torque_pm_source_work_fd_nm!r} Nm | "
        f"current_source_fd_avg={avg_torque_current_source_work_fd_nm!r} Nm"
    )
    log_event("MAGNETO2D", fd_decomp_message)

    solve_time_ms = sum(int(report.get("solve_info", {}).get("total_time_ms", 0) or 0) for report in loaded_reports)
    if no_load_reports:
        solve_time_ms += sum(int(report.get("solve_info", {}).get("total_time_ms", 0) or 0) for report in no_load_reports)

    mesh_info = dict(loaded_reports[0].get("mesh_info", {}))
    mesh_info["mesh_density"] = mesh_info.get("mesh_density", f"{mesh_label}_import")
    mesh_info[f"{mesh_label}_mesh_rotation_model"] = "per_angle"
    mesh_info[f"per_angle_{mesh_label}_meshes"] = n_positions
    mesh_info[f"per_angle_{mesh_label}_loaded_meshes"] = n_positions
    mesh_info[f"per_angle_{mesh_label}_noload_meshes"] = no_load_n_positions

    config_summary = dict(loaded_reports[0].get("config_summary", {}))
    config_summary[f"{mesh_label}_mesh_rotation_model"] = "per_angle"

    operating_point = loaded_reports[0].get("operating_point") or {
        "requested_current_amplitude_a": config.solve_params.current_amplitude_A,
        "resolved_current_amplitude_a": _requested_phase_current_peak_a(config),
        "current_amplitude_convention": config.solve_params.current_amplitude_convention,
        "resolved_phase_current_peak_a": _requested_phase_current_peak_a(config),
        "requested_current_angle_deg": config.solve_params.current_angle_deg,
        "resolved_current_angle_deg": config.solve_params.current_angle_deg,
        "current_angle_reference": (
            "gamma from q-axis; positive gamma is flux-weakening advance; "
            "theta_e = pp*mech - 90 + gamma"
        ),
    }

    emf_peak = max((abs(value) for value in no_load_emf_a), default=0.0)
    emf_peak_physical = max((abs(value) for value in no_load_emf_a_physical), default=0.0)
    # When the sweep is shorter than one full electrical cycle (custom
    # solve_quality + --rotor-sweep-deg < 360, or quick/standard tiers
    # without back-EMF promotion), there's not enough support to extract a
    # meaningful Fourier fundamental. Emit None so downstream consumers
    # (Phase A report, scripts/postprocess_sweep, etc.) can distinguish
    # "fundamental unavailable" from a real zero-volt reading. Reporting
    # 0.0 here previously produced a -100% delta against FEMM in any
    # partial sweep, which masked real solver/post-process issues.
    emf_fundamental_peak_physical = _fundamental_peak(no_load_emf_a_physical, no_load_angles_elec_deg or []) if no_load_periodic else None
    emf_harmonics = (
        _harmonic_peaks(
            no_load_emf_a_physical,
            no_load_angles_elec_deg or [],
            k_max=6,
        )
        if no_load_periodic
        else {}
    )
    solve_options = config.solve_options
    harmonic_analysis = None
    if no_load_periodic and solve_options is not None and solve_options.thd_analysis:
        harmonic_analysis = analyze_back_emf_harmonics(
            angles_elec_deg=no_load_angles_elec_deg or [],
            phase_a_flux_linkage_Wb=no_load_psi_a,
            phase_b_flux_linkage_Wb=no_load_psi_b,
            phase_c_flux_linkage_Wb=no_load_psi_c,
            electrical_angular_speed_rad_s=omega_elec,
            max_harmonic=harmonic_limit_for_quality(config.solve_params.solve_quality),
        )
    emf_thd_pct = (
        harmonic_analysis.phase_a_thd_h12_pct
        if harmonic_analysis is not None
        else None
    )
    emf_fundamental_v = emf_fundamental_peak_physical / max(1, pole_pairs) if emf_fundamental_peak_physical is not None else None
    emf_fundamental_rms_v = (
        harmonic_analysis.harmonics[0].phase_a_rms_V
        if harmonic_analysis is not None
        else (
            emf_fundamental_peak_physical / math.sqrt(2.0)
            if emf_fundamental_peak_physical is not None
            else None
        )
    )

    sweep: dict[str, Any] = {
        "rotor_positions_elec_deg": angles_elec_deg,
        "back_emf_rotor_positions_elec_deg": (no_load_angles_elec_deg if no_load_reports else angles_elec_deg),
        "no_load_rotor_positions_elec_deg": (no_load_angles_elec_deg if no_load_reports else None),
        "torque_nm": torque_contour,
        "avg_torque_nm": _waveform_mean(torque_contour),
        "torque_contour_centered_nm": torque_contour_centered,
        "avg_torque_contour_centered_nm": (_waveform_mean(torque_contour_centered) if torque_contour_centered else None),
        "torque_mst_nm": torque_mst,
        "avg_torque_mst_nm": _waveform_mean(torque_mst),
        "torque_arkkio_nm": torque_arkkio,
        "avg_torque_arkkio_nm": _waveform_mean(torque_arkkio),
        "torque_weighted_stress_nm": torque_weighted_stress,
        "avg_torque_weighted_stress_nm": (_waveform_mean(torque_weighted_stress) if torque_weighted_stress else None),
        "torque_weighted_stress_centered_nm": torque_weighted_stress_centered,
        "avg_torque_weighted_stress_centered_nm": (_waveform_mean(torque_weighted_stress_centered) if torque_weighted_stress_centered else None),
        "torque_ripple_pct": _torque_ripple_pct(
            torque_contour,
            _waveform_mean(torque_contour),
            None,
        ),
        "torque_energy_fd_nm": torque_energy_fd,
        "avg_torque_energy_fd_nm": (_waveform_mean(torque_energy_fd) if torque_energy_fd else None),
        "torque_coenergy_fd_nm": torque_coenergy_fd,
        "avg_torque_coenergy_fd_nm": (_waveform_mean(torque_coenergy_fd) if torque_coenergy_fd else None),
        # Finite-difference component breakdown (see [FD-DECOMP] log):
        "torque_field_fd_nm": torque_field_fd,
        "avg_torque_field_fd_nm": avg_torque_field_fd_nm,
        "torque_pm_source_work_fd_nm": torque_pm_source_work_fd,
        "avg_torque_pm_source_work_fd_nm": avg_torque_pm_source_work_fd_nm,
        "torque_current_source_work_fd_nm": torque_current_source_work_fd,
        "avg_torque_current_source_work_fd_nm": avg_torque_current_source_work_fd_nm,
        "energy_potential_j": potential_energy,
        "energy_coenergy_j": coenergy,
        "energy_field_j": field_energy,
        "energy_current_source_work_j": current_source_work,
        "energy_pm_source_work_j": pm_source_work,
        "energy_pm_self_j": pm_self_energy,
        "energy_potential_with_pm_self_j": potential_energy_with_pm_self,
        "loaded_flux_linkage_a_wb": loaded_psi_a,
        "loaded_flux_linkage_b_wb": loaded_psi_b,
        "loaded_flux_linkage_c_wb": loaded_psi_c,
        "loaded_back_emf_a_v": loaded_emf_a,
        "loaded_back_emf_b_v": loaded_emf_b,
        "loaded_back_emf_c_v": loaded_emf_c,
        "no_load_flux_linkage_a_wb": no_load_psi_a,
        "no_load_flux_linkage_b_wb": no_load_psi_b,
        "no_load_flux_linkage_c_wb": no_load_psi_c,
        "no_load_back_emf_a_v": no_load_emf_a,
        "no_load_back_emf_b_v": no_load_emf_b,
        "no_load_back_emf_c_v": no_load_emf_c,
        "no_load_back_emf_a_physical_v": no_load_emf_a_physical,
        "no_load_back_emf_b_physical_v": no_load_emf_b_physical,
        "no_load_back_emf_c_physical_v": no_load_emf_c_physical,
        "flux_linkage_a_wb": no_load_psi_a,
        "flux_linkage_b_wb": no_load_psi_b,
        "flux_linkage_c_wb": no_load_psi_c,
        "back_emf_a_v": no_load_emf_a,
        "back_emf_b_v": no_load_emf_b,
        "back_emf_c_v": no_load_emf_c,
        "back_emf_peak_v": emf_peak,
        "back_emf_fundamental_v": emf_fundamental_v,
        "back_emf_peak_physical_v": emf_peak_physical,
        "back_emf_fundamental_peak_physical_v": emf_fundamental_peak_physical,
        "back_emf_fundamental_rms_v": emf_fundamental_rms_v,
        "back_emf_harmonics_v": emf_harmonics,
        "back_emf_k1_v": emf_harmonics.get("1"),
        "back_emf_k2_v": emf_harmonics.get("2"),
        "back_emf_k3_v": emf_harmonics.get("3"),
        "back_emf_k4_v": emf_harmonics.get("4"),
        "back_emf_k5_v": emf_harmonics.get("5"),
        "back_emf_k6_v": emf_harmonics.get("6"),
        "back_emf_thd_pct": emf_thd_pct,
        "back_emf_thd_h6_pct": (
            harmonic_analysis.phase_a_thd_h6_pct if harmonic_analysis is not None else None
        ),
        "back_emf_thd_h12_pct": (
            harmonic_analysis.phase_a_thd_h12_pct if harmonic_analysis is not None else None
        ),
        "back_emf_thd_h24_pct": (
            harmonic_analysis.phase_a_thd_h24_pct if harmonic_analysis is not None else None
        ),
        "back_emf_line_thd_h12_pct": (
            harmonic_analysis.line_ab_thd_h12_pct if harmonic_analysis is not None else None
        ),
        "back_emf_line_thd_h24_pct": (
            harmonic_analysis.line_ab_thd_h24_pct if harmonic_analysis is not None else None
        ),
        "back_emf_harmonic_analysis": (
            harmonic_analysis.model_dump(mode="json") if harmonic_analysis is not None else None
        ),
        "loaded_nonlinear_iterations": [int(report.get("solve_info", {}).get("nonlinear_iterations", 0) or 0) for report in loaded_reports],
        "no_load_nonlinear_iterations": no_load_iters,
        "cogging_torque_nm": cogging_torque_peak_abs,
        "cogging_rotor_positions_elec_deg": (no_load_angles_elec_deg if no_load_reports else None),
        "cogging_torque_waveform_nm": cogging_torque_waveform,
        "cogging_torque_arkkio_waveform_nm": (no_load_torque_arkkio if no_load_reports else None),
        "cogging_torque_contour_waveform_nm": (no_load_torque_contour if no_load_reports else None),
        "cogging_torque_contour_centered_waveform_nm": (no_load_torque_contour_centered if no_load_reports else None),
        "cogging_torque_area_mst_waveform_nm": (no_load_torque_mst if no_load_reports else None),
        "cogging_torque_weighted_stress_waveform_nm": no_load_torque_weighted_stress,
        "cogging_torque_weighted_stress_centered_waveform_nm": (no_load_torque_weighted_stress_centered),
        "cogging_torque_contour_inner_waveform_nm": None,
        "cogging_torque_contour_outer_waveform_nm": None,
        "cogging_torque_method": None,
        "core_loss_w": None,
        "hysteresis_loss_w": None,
        "eddy_current_loss_w": None,
        "stator_core_mass_kg": None,
        "rated_speed_rpm": config.solve_params.rated_speed_rpm,
        "total_time_ms": solve_time_ms + mesh_generation_time_ms,
    }
    if (
        config.solve_params.excitation_mode == "ideal_six_step_120"
        and len(phase_current_samples) == len(angles_elec_deg)
    ):
        sweep["phase_current_a_A"] = [sample[0] for sample in phase_current_samples]
        sweep["phase_current_b_A"] = [sample[1] for sample in phase_current_samples]
        sweep["phase_current_c_A"] = [sample[2] for sample in phase_current_samples]
    if slot_flux_linkage_frames_enabled:
        sweep["loaded_slot_flux_linkage_frames"] = loaded_slot_flux_linkage_frames
        sweep["no_load_slot_flux_linkage_frames"] = no_load_slot_flux_linkage_frames
        sweep["slot_flux_linkage_diagnostic"] = {
            "enabled": True,
            "angle_filter_deg": _slot_flux_target_angles(),
            "loaded_frame_count": len(loaded_slot_flux_linkage_frames),
            "no_load_frame_count": len(no_load_slot_flux_linkage_frames),
        }

    return {
        "openem_schema_version": "v1",
        "openem_schema_kind": "magneto2d_sweep_report",
        "openem_provenance": {
            "solver": "magneto2d",
            "mesh_source": mesh_label,
            f"{mesh_label}_mesh_rotation_model": "per_angle",
        },
        "config_summary": config_summary,
        "operating_point": operating_point,
        "mesh_info": mesh_info,
        "sweep": sweep,
        "field_line_frames": field_line_frames,
        "slot_excitation_frames": slot_excitation_frames,
    }
