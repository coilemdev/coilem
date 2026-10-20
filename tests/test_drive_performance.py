"""Torque–speed envelope and efficiency map from a flux-linkage map (#140, #141), on analytic motors."""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.drive_performance import MapModel, efficiency_map, torque_speed_envelope
from backend.models.performance import DriveLimits, FluxLinkageMap, FluxLinkageMapPoint, dq_currents

POLE_PAIRS = 4
LAMBDA_PM = 0.05
R = 0.05
REFERENCE_RPM = 3000.0
IRON_H, IRON_E = 20.0, 10.0  # W at the reference speed, the same at every map point


def _map(l_d: float, l_q: float, *, max_current: float = 80.0, iron: bool = True, drop: tuple[float, float] | None = None) -> FluxLinkageMap:
    currents = [float(value) for value in np.linspace(0.0, max_current, 9)]
    gammas = [float(value) for value in range(-10, 95, 5)]
    points = []
    for current in currents:
        for gamma in gammas:
            if drop == (current, gamma):
                continue
            i_d, i_q = dq_currents(current, gamma)
            lambda_d, lambda_q = LAMBDA_PM + l_d * i_d, l_q * i_q
            points.append(FluxLinkageMapPoint(
                current_peak_A=current, gamma_deg=gamma, i_d_A=i_d, i_q_A=i_q, status="ok",
                avg_torque_Nm=1.5 * POLE_PAIRS * (lambda_d * i_q - lambda_q * i_d),
                lambda_d_Wb=lambda_d, lambda_q_Wb=lambda_q,
                iron_hysteresis_loss_W=IRON_H if iron else None, iron_eddy_loss_W=IRON_E if iron else None,
                iron_loss_W=IRON_H + IRON_E if iron else None,
            ))
    return FluxLinkageMap(
        scope_key="analytic-test-map-0001", pole_pairs=POLE_PAIRS, current_peak_A=currents, gamma_deg=gammas,
        reference_speed_rpm=REFERENCE_RPM, rotor_positions=48, mesh_density="normal", points=points,
    )


LIMITS = DriveLimits(dc_bus_V=150.0, peak_current_A=60.0, continuous_current_A=30.0, max_speed_rpm=12000.0)
V_MAX = LIMITS.modulation_index_max * LIMITS.dc_bus_V / 2


def _omega_e(rpm: float) -> float:
    return rpm * 2 * math.pi / 60 * POLE_PAIRS


def _voltage(l_d: float, l_q: float, current: float, gamma: float, rpm: float) -> float:
    i_d, i_q = dq_currents(current, gamma)
    w = _omega_e(rpm)
    return math.hypot(R * i_d - w * l_q * i_q, R * i_q + w * (LAMBDA_PM + l_d * i_d))


def _spm_envelope_torque(inductance: float, current: float, rpm: float) -> float:
    """Exact envelope of the analytic SPM below MTPV: γ = 0 until the voltage limit, then the γ that meets it."""
    if _voltage(inductance, inductance, current, 0.0, rpm) <= V_MAX:
        return 1.5 * POLE_PAIRS * LAMBDA_PM * current
    if _voltage(inductance, inductance, current, 90.0, rpm) > V_MAX:
        return 0.0
    low, high = 0.0, 90.0
    for _ in range(80):
        middle = 0.5 * (low + high)
        low, high = (middle, high) if _voltage(inductance, inductance, current, middle, rpm) > V_MAX else (low, middle)
    return 1.5 * POLE_PAIRS * LAMBDA_PM * current * math.cos(math.radians(high))


def test_textbook_spm_matches_the_analytic_curve_within_one_percent():
    inductance = 0.5e-3  # λpm / L = 100 A, above the current limit: no MTPV
    envelope = torque_speed_envelope(_map(inductance, inductance), LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0)
    peak = envelope.curves[0]
    rated = 1.5 * POLE_PAIRS * LAMBDA_PM * LIMITS.peak_current_A
    for speed, torque in zip(peak.speed_rpm, peak.torque_Nm):
        assert torque == pytest.approx(_spm_envelope_torque(inductance, LIMITS.peak_current_A, speed), abs=0.01 * rated)
    # Base speed in closed form: (L²I² + λpm²)ω² + 2RIλpm·ω + R²I² − V² = 0 at id = 0.
    current = LIMITS.peak_current_A
    a = inductance**2 * current**2 + LAMBDA_PM**2
    b = 2 * R * current * LAMBDA_PM
    c = R**2 * current**2 - V_MAX**2
    base_rpm = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a) / POLE_PAIRS * 60 / (2 * math.pi)
    assert peak.base_speed_rpm == pytest.approx(base_rpm, rel=0.01)
    assert set(peak.region) == {"mtpa", "field_weakening"}
    assert peak.region[0] == "mtpa" and peak.region[-1] == "field_weakening"
    assert peak.torque_Nm[0] == pytest.approx(rated, rel=0.005)
    assert peak.max_speed_rpm < LIMITS.max_speed_rpm
    assert peak.peak_power_W == pytest.approx(max(t * s * 2 * math.pi / 60 for t, s in zip(peak.torque_Nm, peak.speed_rpm)))
    for volts, speed in zip(peak.phase_voltage_peak_V, peak.speed_rpm):
        assert volts <= V_MAX * 1.001
    assert envelope.status == "experimental"
    assert [curve.limit for curve in envelope.curves] == ["peak", "continuous"]
    assert envelope.curves[1].torque_Nm[0] == pytest.approx(rated / 2, rel=0.005)
    assert envelope.curves[1].base_speed_rpm > peak.base_speed_rpm


def test_ipm_mtpa_angle_shows_reluctance_torque():
    l_d, l_q = 0.3e-3, 0.9e-3
    current = LIMITS.peak_current_A
    saliency = l_q - l_d
    i_d = (LAMBDA_PM - math.sqrt(LAMBDA_PM**2 + 8 * saliency**2 * current**2)) / (4 * saliency)
    i_q = math.sqrt(current**2 - i_d**2)
    torque = 1.5 * POLE_PAIRS * (LAMBDA_PM * i_q + (l_d - l_q) * i_d * i_q)
    peak = torque_speed_envelope(_map(l_d, l_q), LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0).curves[0]
    gamma = math.degrees(math.atan2(-peak.i_d_A[0], peak.i_q_A[0]))
    assert gamma == pytest.approx(math.degrees(math.atan2(-i_d, i_q)), abs=1.0)
    assert gamma > 10
    assert peak.torque_Nm[0] == pytest.approx(torque, rel=0.005)
    assert peak.torque_Nm[0] > 1.5 * POLE_PAIRS * LAMBDA_PM * current  # more than the magnet torque alone


def test_mtpv_appears_when_the_characteristic_current_is_inside_the_limit():
    inductance = 1.0e-3  # λpm / L = 50 A, below the 60 A limit: speed is unbounded, MTPV at the top
    peak = torque_speed_envelope(_map(inductance, inductance), LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0).curves[0]
    assert "mtpv" in peak.region
    assert peak.max_speed_rpm == pytest.approx(LIMITS.max_speed_rpm)
    first_mtpv = peak.region.index("mtpv")
    assert all(region == "mtpv" for region in peak.region[first_mtpv:])
    assert math.hypot(peak.i_d_A[-1], peak.i_q_A[-1]) < LIMITS.peak_current_A * 0.999


def test_efficiency_map_reproduces_the_operating_point_bookkeeping():
    inductance = 0.5e-3
    flux_map = _map(inductance, inductance)
    result = efficiency_map(flux_map, LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0, mechanical_loss_W=5.0)
    speeds, torques = np.array(result.speed_rpm), np.array(result.torque_Nm)
    # Below base speed the least-loss current is the SPM's MTPA current, all on the q-axis.
    column = int(np.searchsorted(speeds, 1500.0))
    for row in (5, 20, 35):
        torque, rpm = torques[row], speeds[column]
        current = torque / (1.5 * POLE_PAIRS * LAMBDA_PM)
        ratio = rpm / REFERENCE_RPM
        copper = 1.5 * R * current**2
        iron = IRON_H * ratio + IRON_E * ratio**2
        omega = rpm * 2 * math.pi / 60
        expected = 100 * (torque * omega - iron - 5.0) / (torque * omega + copper)
        assert result.efficiency_pct[row][column] == pytest.approx(expected, abs=0.05)
        assert result.copper_loss_W[row][column] == pytest.approx(copper, rel=0.01)
        assert result.iron_loss_W[row][column] == pytest.approx(iron, rel=1e-6)
    assert result.status == "experimental"


def test_efficiency_map_is_continuous_across_the_field_weakening_boundary():
    inductance = 0.5e-3
    flux_map = _map(inductance, inductance)
    envelope = torque_speed_envelope(flux_map, LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0)
    result = efficiency_map(flux_map, LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0, envelope=envelope)
    eta = np.array([[np.nan if value is None else value for value in row] for row in result.efficiency_pct])
    # Points above the envelope are empty, and the empty region sits at high torque.
    peak = envelope.curves[0]
    for column, rpm in enumerate(result.speed_rpm):
        limit = np.interp(rpm, peak.speed_rpm, peak.torque_Nm)
        for row, torque in enumerate(result.torque_Nm):
            if torque < 0.98 * limit:
                assert not np.isnan(eta[row, column]), (torque, rpm, limit)
            if torque > 1.02 * limit:
                assert np.isnan(eta[row, column]), (torque, rpm, limit)
    # No jumps: away from the low-torque, low-speed corner the efficiency bends smoothly
    # (a one-point step across the field-weakening boundary would show as a second difference near 1).
    assert envelope.curves[0].base_speed_rpm < result.speed_rpm[-1] / 2
    for axis in (0, 1):
        assert np.nanmax(np.abs(np.diff(eta[5:, 5:], n=2, axis=axis))) < 0.75


def test_iron_loss_is_left_out_and_said_so_when_the_map_has_none():
    flux_map = _map(0.5e-3, 0.5e-3, iron=False)
    assert not MapModel.from_map(flux_map).iron_loss_available
    result = efficiency_map(flux_map, LIMITS, phase_resistance_ohm=R, winding_temperature_C=80.0, speed_points=6, torque_points=6)
    assert "not included" in result.status_reason
    assert all(value in (None, 0.0) for row in result.iron_loss_W for value in row)


def test_a_map_with_an_unsolved_point_is_refused():
    with pytest.raises(ValueError, match="no solved result"):
        MapModel.from_map(_map(0.5e-3, 0.5e-3, drop=(40.0, 30.0)))


def test_a_current_limit_beyond_the_map_is_clamped_and_said_so():
    limits = DriveLimits(dc_bus_V=150.0, peak_current_A=100.0, max_speed_rpm=12000.0)
    envelope = torque_speed_envelope(_map(0.5e-3, 0.5e-3), limits, phase_resistance_ohm=R, winding_temperature_C=80.0)
    assert envelope.curves[0].torque_Nm[0] == pytest.approx(1.5 * POLE_PAIRS * LAMBDA_PM * 80.0, rel=0.005)
    assert "clamped" in envelope.status_reason
