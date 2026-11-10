"""Solver-neutral Back-EMF harmonic analysis from periodic flux linkage."""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence

from backend.models import BackEMFHarmonicAnalysis, BackEMFHarmonicComponent


def harmonic_limit_for_quality(solve_quality: str) -> int:
    """Return the public spectrum bandwidth for a solve tier."""

    return 24 if solve_quality == "fine" else 12


def _validate_periodic_grid(angles_elec_deg: Sequence[float]) -> None:
    if len(angles_elec_deg) < 5:
        raise ValueError("Back-EMF harmonic analysis requires at least five samples")
    step = float(angles_elec_deg[1]) - float(angles_elec_deg[0])
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("Back-EMF harmonic angles must be strictly increasing")
    for index, angle in enumerate(angles_elec_deg):
        expected = float(angles_elec_deg[0]) + index * step
        if not math.isclose(float(angle), expected, rel_tol=0.0, abs_tol=1.0e-6):
            raise ValueError("Back-EMF harmonic angles must use a uniform grid")
    if not math.isclose(step * len(angles_elec_deg), 360.0, rel_tol=0.0, abs_tol=1.0e-5):
        raise ValueError("Back-EMF harmonic analysis requires a half-open 360 degree grid")


def _positive_frequency_coefficients(
    values: Sequence[float],
    angles_elec_deg: Sequence[float],
    max_harmonic: int,
) -> list[complex]:
    count = len(values)
    return [
        sum(
            float(value) * cmath.exp(-1j * order * math.radians(float(angle)))
            for value, angle in zip(values, angles_elec_deg, strict=True)
        )
        / count
        for order in range(1, max_harmonic + 1)
    ]


def _thd_pct(amplitudes: Sequence[float], limit: int) -> float | None:
    if len(amplitudes) < limit:
        return None
    fundamental = float(amplitudes[0])
    if fundamental <= 1.0e-12:
        return None
    residual = math.sqrt(sum(float(value) ** 2 for value in amplitudes[1:limit]))
    return residual / fundamental * 100.0


def analyze_back_emf_harmonics(
    *,
    angles_elec_deg: Sequence[float],
    phase_a_flux_linkage_Wb: Sequence[float],
    phase_b_flux_linkage_Wb: Sequence[float],
    phase_c_flux_linkage_Wb: Sequence[float],
    electrical_angular_speed_rad_s: float,
    max_harmonic: int,
) -> BackEMFHarmonicAnalysis:
    """Compute phase and line spectra without differentiating mesh-to-mesh noise.

    A real periodic linkage waveform has positive-frequency coefficient
    ``Lambda_h``. Its voltage coefficient is ``-j*h*omega_e*Lambda_h``;
    multiplying its magnitude by ``sqrt(2)`` therefore gives RMS voltage.
    """

    _validate_periodic_grid(angles_elec_deg)
    count = len(angles_elec_deg)
    phases = (
        phase_a_flux_linkage_Wb,
        phase_b_flux_linkage_Wb,
        phase_c_flux_linkage_Wb,
    )
    if any(len(values) != count for values in phases):
        raise ValueError("Back-EMF flux-linkage arrays must match the angle grid")
    if not math.isfinite(electrical_angular_speed_rad_s) or electrical_angular_speed_rad_s < 0:
        raise ValueError("electrical angular speed must be finite and non-negative")
    resolvable_max = count // 2 - 1
    if max_harmonic < 2 or max_harmonic > resolvable_max:
        raise ValueError(
            f"H{max_harmonic} requires more samples; H{resolvable_max} is the limit for {count} samples"
        )

    linkage_coefficients = [
        _positive_frequency_coefficients(values, angles_elec_deg, max_harmonic)
        for values in phases
    ]
    voltage_coefficients = [
        [
            -1j * order * electrical_angular_speed_rad_s * coefficient
            for order, coefficient in enumerate(coefficients, start=1)
        ]
        for coefficients in linkage_coefficients
    ]
    phase_rms = [
        [math.sqrt(2.0) * abs(value) for value in coefficients]
        for coefficients in voltage_coefficients
    ]
    line_coefficients = [
        [
            voltage_coefficients[first][index] - voltage_coefficients[second][index]
            for index in range(max_harmonic)
        ]
        for first, second in ((0, 1), (1, 2), (2, 0))
    ]
    line_rms = [
        [math.sqrt(2.0) * abs(value) for value in coefficients]
        for coefficients in line_coefficients
    ]
    phase_a_fundamental = phase_rms[0][0]
    line_ab_fundamental = line_rms[0][0]
    fundamental_frequency_hz = electrical_angular_speed_rad_s / (2.0 * math.pi)

    harmonics = [
        BackEMFHarmonicComponent(
            order=order,
            frequency_Hz=order * fundamental_frequency_hz,
            phase_a_rms_V=phase_rms[0][order - 1],
            phase_b_rms_V=phase_rms[1][order - 1],
            phase_c_rms_V=phase_rms[2][order - 1],
            line_ab_rms_V=line_rms[0][order - 1],
            line_bc_rms_V=line_rms[1][order - 1],
            line_ca_rms_V=line_rms[2][order - 1],
            phase_a_pct_fundamental=(
                phase_rms[0][order - 1] / phase_a_fundamental * 100.0
                if phase_a_fundamental > 1.0e-12
                else None
            ),
            line_ab_pct_fundamental=(
                line_rms[0][order - 1] / line_ab_fundamental * 100.0
                if line_ab_fundamental > 1.0e-12
                else None
            ),
        )
        for order in range(1, max_harmonic + 1)
    ]

    return BackEMFHarmonicAnalysis(
        sample_count=count,
        electrical_fundamental_frequency_Hz=fundamental_frequency_hz,
        headline_harmonic_max=12,
        extended_harmonic_max=max_harmonic,
        phase_a_thd_h6_pct=_thd_pct(phase_rms[0], 6),
        phase_a_thd_h12_pct=_thd_pct(phase_rms[0], 12),
        phase_a_thd_h24_pct=_thd_pct(phase_rms[0], 24),
        line_ab_thd_h12_pct=_thd_pct(line_rms[0], 12),
        line_ab_thd_h24_pct=_thd_pct(line_rms[0], 24),
        harmonics=harmonics,
    )
