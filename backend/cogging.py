"""What Results, the run PDF and the CSV show from a cogging sweep (#185).

The solver samples one cogging period with no current, both ends included
(``backend.sweep_planning.cogging_angle_grid``). This module turns that
waveform into one record, so the three outputs read the same numbers: the
peak-to-peak and peak torque, the harmonic spectrum in cycles per mechanical
revolution, and noise measures. An exact solve averages to zero over the
period and repeats at its end. The endpoint mismatch measures remesh noise
only when the endpoints were independently meshed and solved.

Its summary defines Phase E's numerical comparison, so this module is a
guarded physics source (backend/benchmark_suite/physics.py). Changing it
requires matching measured-source evidence before qualification.
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence

from backend.models.performance import CoggingHarmonic, CoggingTorque

# Names the record gives each torque extraction method.
COGGING_METHOD_LABELS = {
    "arkkio": "Arkkio",
    "contour": "Contour MST",
    "mst": "Area MST",
    "weighted_stress": "WST",
    "weighted_stress_centered": "WST, mean removed",
}
# Below this phase current (A peak) a loaded sweep has no load to compare with.
_NO_LOAD_CURRENT_A = 1e-6


def cogging_period(slot_count: int, pole_count: int) -> tuple[float, float, int]:
    """(electrical degrees, mechanical degrees, cycles per revolution) of one cogging period."""

    order = math.lcm(int(slot_count), int(pole_count))
    period_mech_deg = 360.0 / order
    return period_mech_deg * pole_count / 2.0, period_mech_deg, order


def _one_period(angles: Sequence[float], values: Sequence[float], period_deg: float) -> list[float] | None:
    """The samples of one period, without a repeated endpoint, or None when the grid is not one uniform period."""

    count = len(angles)
    if count < 3 or count != len(values) or period_deg <= 0.0:
        return None
    span = angles[-1] - angles[0]
    step = span / (count - 1)
    tolerance = max(abs(step) * 1e-3, 1e-6)
    if step <= 0.0 or any(abs(angles[index + 1] - angles[index] - step) > tolerance for index in range(count - 1)):
        return None
    if abs(span - period_deg) <= tolerance * count:
        return list(values[:-1])
    if abs(span + step - period_deg) <= tolerance * count:
        return list(values)
    return None


def _harmonics(samples: Sequence[float], fundamental_order: int) -> list[CoggingHarmonic]:
    count = len(samples)
    harmonics = []
    for multiple in range(1, count // 2 + 1):
        coefficient = sum(
            value * cmath.exp(-2j * math.pi * multiple * index / count) for index, value in enumerate(samples)
        )
        # The Nyquist bin is real and is not mirrored, so it carries the whole amplitude.
        scale = 1.0 if 2 * multiple == count else 2.0
        harmonics.append(
            CoggingHarmonic(
                order=multiple * fundamental_order,
                multiple=multiple,
                amplitude_Nm=scale * abs(coefficient) / count,
            )
        )
    return harmonics


def cogging_record(
    angles_elec_deg: Sequence[float],
    torque_Nm: Sequence[float],
    *,
    slot_count: int,
    pole_count: int,
    method: str,
    independent_endpoints: bool = True,
    loaded_mean_torque_Nm: float | None = None,
    loaded_current_A: float | None = None,
) -> CoggingTorque | None:
    """The record for a cogging waveform over one period, or None when it is not one.

    ``loaded_current_A`` is the loaded sweep's peak phase current; with none,
    the run has no load to compare the cogging with.
    ``independent_endpoints`` must be false when the endpoints share a mesh
    or solution; a missing closing endpoint also leaves the mismatch unset.
    """

    angles = [float(value) for value in angles_elec_deg]
    values = [float(value) for value in torque_Nm]
    if not all(math.isfinite(value) for value in (*angles, *values)):
        return None
    period_elec_deg, period_mech_deg, fundamental_order = cogging_period(slot_count, pole_count)
    period = _one_period(angles, values, period_elec_deg)
    if period is None:
        return None
    harmonics = _harmonics(period, fundamental_order)
    peak_to_peak = max(values) - min(values)
    loaded = (
        loaded_mean_torque_Nm is not None
        and math.isfinite(loaded_mean_torque_Nm)
        and loaded_current_A is not None
        and abs(loaded_current_A) > _NO_LOAD_CURRENT_A
    )
    ratio = (
        100.0 * peak_to_peak / abs(loaded_mean_torque_Nm)
        if loaded and loaded_mean_torque_Nm
        else None
    )
    return CoggingTorque(
        method=method,
        positions_per_period=len(period),
        period_elec_deg=period_elec_deg,
        period_mech_deg=period_mech_deg,
        fundamental_order=fundamental_order,
        peak_to_peak_Nm=peak_to_peak,
        peak_Nm=max(abs(value) for value in values),
        first_harmonic_Nm=harmonics[0].amplitude_Nm if harmonics else 0.0,
        mean_Nm=sum(period) / len(period),
        endpoint_mismatch_Nm=(
            abs(values[-1] - values[0]) if independent_endpoints and len(values) > len(period) else None
        ),
        harmonics=harmonics,
        loaded_mean_torque_Nm=loaded_mean_torque_Nm if loaded else None,
        peak_to_peak_of_loaded_pct=ratio,
    )
