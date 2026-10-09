"""Solver-neutral rotor-angle planning for 2D electromagnetic sweeps."""

from __future__ import annotations

import math

from backend.models import MotorConfig, SolveOptionsConfig


def loaded_sweep_plan(config: MotorConfig) -> tuple[int, float]:
    """Return ``(sample_count, electrical_span_deg)`` for a loaded sweep.

    Full-cycle grids are half-open so 360 degrees does not duplicate zero.
    Partial grids include both endpoints. This is the established Magneto2D
    convention and is shared by Elmer so parity compares identical positions.
    """

    solve_params = config.solve_params
    if solve_params is None:
        raise ValueError("an electromagnetic sweep requires solve_params")
    step_deg = float(solve_params.effective_step_deg())
    span_deg = float(solve_params.effective_native_loaded_sweep_range_deg())
    options = config.solve_options or SolveOptionsConfig()
    if (
        solve_params.excitation_mode == "ideal_six_step_120"
        and solve_params.solve_quality in ("standard", "fine")
    ) or options.thd_analysis or (
        options.back_emf and solve_params.solve_quality == "standard"
    ):
        span_deg = 360.0
    if span_deg >= 360.0 - 1.0e-6:
        count = max(2, int(round(span_deg / step_deg)))
    else:
        count = max(2, int(round(span_deg / step_deg)) + 1)
    if options.thd_analysis:
        count = max(count, 48)
    return count, span_deg


def is_uniform_full_cycle_grid(angles_deg: list[float]) -> bool:
    """Return whether samples form a uniform half-open 360° electrical grid."""

    unique: list[float] = []
    for raw_angle in angles_deg:
        angle = float(raw_angle)
        if not math.isfinite(angle):
            return False
        normalized = angle % 360.0
        if not any(abs(normalized - existing) <= 1.0e-6 for existing in unique):
            unique.append(normalized)
    unique.sort()
    if len(unique) < 3:
        return False
    gaps = [unique[index + 1] - unique[index] for index in range(len(unique) - 1)]
    gaps.append(unique[0] + 360.0 - unique[-1])
    step = sum(gaps) / len(gaps)
    tolerance = max(1.0e-5, abs(step) * 1.0e-3)
    return step > 0.0 and all(abs(gap - step) <= tolerance for gap in gaps)


def loaded_angle_grid(config: MotorConfig) -> list[float]:
    """Return the requested loaded electrical-angle grid."""

    count, span_deg = loaded_sweep_plan(config)
    step_deg = span_deg / count if span_deg >= 360.0 - 1.0e-6 else span_deg / (count - 1)
    return [index * step_deg for index in range(count)]


def full_cycle_back_emf_angle_grid(
    config: MotorConfig,
    loaded_angles_elec_deg: list[float],
) -> list[float]:
    """Return the full-cycle no-load grid used for Back-EMF signoff."""

    solve_params = config.solve_params
    step_deg = float(solve_params.effective_step_deg()) if solve_params is not None else 0.0
    if not math.isfinite(step_deg) or step_deg <= 1.0e-9:
        differences = [
            float(loaded_angles_elec_deg[index + 1])
            - float(loaded_angles_elec_deg[index])
            for index in range(len(loaded_angles_elec_deg) - 1)
        ]
        differences = [value for value in differences if math.isfinite(value) and value > 1.0e-9]
        step_deg = min(differences) if differences else 7.5
    count = max(3, int(round(360.0 / step_deg)))
    options = config.solve_options or SolveOptionsConfig()
    if options.thd_analysis:
        # THD promotion uses a half-open grid with enough samples to separate
        # the fundamental from the active low-order harmonics. The loaded plan
        # already enforces 48, but the no-load planner used to ignore that
        # policy and could report THD from as few as 12 samples.
        count = max(count, 48)
    step_deg = 360.0 / count
    return [index * step_deg for index in range(count)]


def cogging_angle_grid(config: MotorConfig, *, step_deg: float = 1.0) -> list[float]:
    """Return one inclusive electrical cogging period, or an empty grid."""

    options = config.solve_options or SolveOptionsConfig()
    if not options.cogging_torque:
        return []
    slots = int(config.stator.slot_count)
    poles = int(config.rotor.pole_count)
    if slots <= 0 or poles <= 0 or not math.isfinite(step_deg) or step_deg <= 0.0:
        return []
    period_deg = 180.0 * math.gcd(slots, poles) / slots
    count = max(2, math.ceil(period_deg / step_deg) + 1)
    actual_step = period_deg / (count - 1)
    return [index * actual_step for index in range(count)]
