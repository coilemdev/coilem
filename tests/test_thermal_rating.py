"""Coupling convergence, explicit failures and bounded rating constraints."""

from __future__ import annotations

import pytest

from backend.models import DriveLimits
from backend.temperature_maps import solve_temperature_bracket
from backend.thermal_rating import CouplingSettings, coupled_point, thermal_rating
from tests.test_flux_linkage_map import _config
from tests.test_temperature_maps import TemperatureSolver
from tests.test_thermal_network import inputs


@pytest.fixture
def bracket(tmp_path):
    return solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=TemperatureSolver(), store_root=tmp_path)


def cooling(**changes):
    return inputs(**(dict(housing_h_W_m2K=1000, end_space_h_W_m2K=1000, airgap_h_W_m2K=500) | changes))


def test_fixed_point_uses_temperature_resistance_and_has_convergence_evidence(bracket):
    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    assert point.status == "experimental", point.status_reason
    assert point.iterations > 1
    assert point.temperature_residual_K <= 0.1
    assert point.winding_temperature_C > 20
    assert point.magnet_temperature_C > 20
    assert point.copper_loss_W > 0 and point.iron_loss_W > 0
    assert point.phase_voltage_peak_V > 0
    assert len(point.temperature_history) == point.iterations
    assert point.verification_status == "NOT_COMPARED"
    assert point.thermal.rotor_heating.basis == "heat_transfer_only"
    assert point.thermal.rotor_heating.internal_loss_status == "not_modelled"
    assert "internal losses are not calculated" in point.status_reason
    for field in ("stator_iron_mass_kg", "validated_max_frequency_Hz", "validated_max_flux_density_T"):
        assert field not in point.model_dump_json(), "Ephemeral loss-adapter placeholders must not enter saved results or exports"


def test_outside_brackets_and_nonconvergence_remain_unavailable(bracket):
    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20, fixed_magnet_C=81)
    assert point.status == "unavailable" and "never extrapolate" in point.status_reason
    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20,
                          settings=CouplingSettings(max_iterations=1))
    assert point.status == "unavailable" and "iteration limit" in point.status_reason
    assert point.iterations == 1


def test_fixed_magnet_case_and_cancel_record(bracket):
    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20, fixed_magnet_C=60)
    assert point.status == "experimental"
    assert point.magnet_temperature_C == 60
    stopped = thermal_rating(bracket, cooling(), DriveLimits(dc_bus_V=24, peak_current_A=20, max_speed_rpm=5000),
                             speed_samples=3, current_samples=2, angle_samples=2, should_stop=lambda: True)
    assert stopped.cancelled and len(stopped.points) == 3
    assert all(p.status == "unavailable" and "cancelled" in p.status_reason for p in stopped.points)


def test_rating_respects_constraints_and_retains_weakest_status(bracket):
    result = thermal_rating(bracket, cooling(), DriveLimits(dc_bus_V=24, peak_current_A=2, continuous_current_A=1,
                            max_speed_rpm=1000), speed_samples=2, current_samples=2, angle_samples=2, user_magnet_C=60)
    assert result.status == "experimental" and result.acceptance_status == "NOT_COMPARED"
    assert len(result.points) == 2
    assert any(row.status == "experimental" for row in result.points)
    for row in result.points:
        if row.status == "unavailable":
            continue
        assert row.point.current_peak_A <= 1
        assert row.point.phase_voltage_peak_V <= 24 / 3**0.5
        assert row.point.thermal.nodes["winding"].margin_K >= 0
        assert row.user_magnet_case.magnet_temperature_C == 60
        assert row.point.verification_status == "NOT_COMPARED"


def test_direct_limiting_point_verification_retains_failed_band(bracket):
    from backend.thermal_rating import verify_limiting_point

    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    assert point.status == "experimental"
    solver = TemperatureSolver()
    verify_limiting_point(bracket, cooling(), DriveLimits(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000), point, solver)
    # This fake deliberately does not scale iron losses with speed; the
    # directly solved record therefore fails the iron-loss comparison.
    assert point.verification_status == "FAIL"
    assert "iron loss" in point.verification_reason
    assert len(solver.calls) == 1
    assert point.status == "experimental"
    assert point.verification_metrics


def test_a_direct_solve_past_the_voltage_limit_is_not_called_a_temperature_limit(bracket):
    from backend.thermal_rating import verify_limiting_point

    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    verify_limiting_point(bracket, cooling(), DriveLimits(dc_bus_V=1, peak_current_A=20, max_speed_rpm=1000), point, TemperatureSolver())
    assert point.status == "unavailable"
    assert point.status_reason.startswith("A direct solve at this point needs more voltage than the drive limit allows, so the value")
    assert "temperature limit" not in point.status_reason.split(", so the value")[0]


def test_runaway_is_not_a_silent_curve_point(bracket, monkeypatch):
    from backend import thermal_rating as module

    original = module.thermal_estimate

    def runaway(*args, **kwargs):
        result = original(*args, **kwargs)
        result.nodes["winding"].temperature_C = 1200
        return result

    monkeypatch.setattr(module, "thermal_estimate", runaway)
    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    assert point.status == "unavailable" and "runaway" in point.status_reason
    assert point.iterations == 1 and point.temperature_history


def test_direct_verification_uses_the_same_band_source_as_interpolation(bracket, monkeypatch):
    from backend.benchmark_suite import temperature_metrics
    from backend.thermal_rating import verify_limiting_point

    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    limits = DriveLimits(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000)
    # This fake fails the registered iron-loss band. Relax only the in-memory
    # test copy; both consumers must observe it, with the frozen file untouched.
    monkeypatch.setitem(temperature_metrics.BANDS, "iron_loss", (0, 100))
    assert temperature_metrics._metric("iron_loss", 0, 2)["status"] == "PASS"
    verify_limiting_point(bracket, cooling(), limits, point, TemperatureSolver())
    assert point.verification_status == "PASS", point.verification_reason


@pytest.mark.parametrize("peak,continuous,label,cap", [
    (2, 1, "current: drive continuous", 1),
    (1, None, "current: drive peak", 1),
    (40, 30, "current: map domain", 20),
    (20, None, "current: drive peak + map domain", 20),
])
def test_current_constraint_names_the_binding_domain(bracket, monkeypatch, peak, continuous, label, cap):
    from backend import thermal_rating as module

    sample = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=1, gamma_deg=0)
    # A monotonic feasible torque surface isolates the search-domain ceiling.
    def feasible(_bracket, _inputs, *, speed_rpm, current_peak_A, gamma_deg, **_):
        return sample.model_copy(update=dict(speed_rpm=speed_rpm, current_peak_A=current_peak_A,
            gamma_deg=gamma_deg, torque_Nm=current_peak_A))
    monkeypatch.setattr(module, "coupled_point", feasible)
    result = thermal_rating(bracket, cooling(), DriveLimits(dc_bus_V=24, peak_current_A=peak,
        continuous_current_A=continuous, max_speed_rpm=1000), speed_samples=2, current_samples=2, angle_samples=2)
    assert all(row.limiting_constraint == label and row.point.current_peak_A == cap for row in result.points)



def test_rating_search_and_native_verification_use_same_integer_rpm(bracket):
    seen = []
    fake = TemperatureSolver()
    def solve(config):
        assert isinstance(config.solve_params.rated_speed_rpm, int)
        seen.append(config.solve_params.rated_speed_rpm)
        return fake(config)
    result = thermal_rating(bracket, cooling(), DriveLimits(dc_bus_V=24, peak_current_A=1,
                            max_speed_rpm=1001), speed_samples=4, current_samples=2, angle_samples=2,
                            direct_solve=solve)
    assert [row.speed_rpm for row in result.points] == [0, 334, 667, 1001]
    assert seen == [0, 334, 667, 1001]


def test_rating_copper_uses_separate_winding_means_and_effective_voltage_resistance(bracket):
    import math

    import numpy as np

    from backend.drive_performance import MapModel
    from backend.temperature_maps import interpolate_temperature_map

    point = coupled_point(bracket, cooling(end_space_h_W_m2K=1), speed_rpm=1000, current_peak_A=4, gamma_deg=30, fixed_magnet_C=60)
    assert point.status == 'experimental', point.status_reason
    feedback = point.thermal.copper_feedback
    assert feedback is not None
    assert abs(point.thermal.nodes['winding'].temperature_C-point.thermal.nodes['end_winding'].temperature_C) > .01
    assert point.copper_loss_W == feedback.copper_loss_W
    assert point.copper_loss_W == pytest.approx(sum(point.thermal.nodes[n].heat_W for n in ('winding','end_winding')))
    assert point.copper_loss_W == pytest.approx(1.5 * point.current_peak_A**2 * feedback.phase_resistance_ohm)
    values = MapModel.from_map(interpolate_temperature_map(bracket, point.magnet_temperature_C).map).sample_points(np.array(4.), np.array(30.))
    omega = 1000 * 2*math.pi/60 * bracket.low.pole_pairs
    expected = math.hypot(feedback.phase_resistance_ohm*(-2)-omega*values['lambda_q'],
                          feedback.phase_resistance_ohm*(2*math.sqrt(3))+omega*values['lambda_d'])
    assert point.phase_voltage_peak_V == pytest.approx(expected)


def test_a_speed_whose_direct_solve_cannot_run_is_not_a_result(bracket):
    from backend.thermal_reporting import rating_row_held

    def broken(_config):
        raise RuntimeError("Magneto2D stopped: forced test failure")

    result = thermal_rating(bracket, cooling(), DriveLimits(dc_bus_V=24, peak_current_A=2, continuous_current_A=1,
                            max_speed_rpm=1000), speed_samples=2, current_samples=2, angle_samples=2, direct_solve=broken)
    checked = [row for row in result.points if row.point is not None]
    assert checked, "The search must find a limiting point for the direct solve to check"
    for row in checked:
        # The map point stays on record, but the speed is excluded, with the exception as its reason.
        assert row.status == "unavailable" and row.point.status == "unavailable"
        assert "Magneto2D stopped: forced test failure" in row.status_reason
        assert row.status_reason == row.point.status_reason
        assert row.point.verification_status == "FAIL"
        assert "forced test failure" in row.point.verification_reason
        assert row.point.torque_Nm is not None
        assert not rating_row_held(row.model_dump(mode="json"))


def test_a_cancel_during_a_direct_solve_stops_the_rating_instead_of_becoming_a_row(bracket):
    from backend.solver_contract import SolveCancelledError
    from backend.thermal_rating import verify_limiting_point

    def cancelled(_config):
        raise SolveCancelledError("Solve cancelled by user.")

    limits = DriveLimits(dc_bus_V=24, peak_current_A=2, continuous_current_A=1, max_speed_rpm=1000)
    point = coupled_point(bracket, cooling(), speed_rpm=1000, current_peak_A=1, gamma_deg=20)
    with pytest.raises(SolveCancelledError):
        verify_limiting_point(bracket, cooling(), limits, point, cancelled)
    assert point.status == "experimental" and point.verification_status == "NOT_COMPARED"
    # The rating ends as cancelled, as a cancel between speeds does: no speed from the cancel on is a result.
    rating = thermal_rating(bracket, cooling(), limits, speed_samples=2, current_samples=2, angle_samples=2, direct_solve=cancelled)
    assert rating.cancelled
    checked = [row for row in rating.points if row.limiting_constraint == "cancelled"]
    assert checked and all(row.status == "unavailable" and row.point is None for row in checked)
    assert all(row.speed_rpm >= checked[0].speed_rpm for row in checked) and len(rating.points) == 2
