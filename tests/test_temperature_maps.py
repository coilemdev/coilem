"""Temperature interpolation, native-reference acceptance and cache integration."""

from __future__ import annotations

import math

import pytest

from backend.benchmark_suite.temperature_metrics import BANDS, TemperatureReference, _metric, check_temperature_interpolation
from backend.flux_linkage_map import map_scope_key, point_config, point_from_result, run_flux_linkage_map
from backend.magnet_temperature import br_scale
from backend.models import DriveLimits
from backend.temperature_maps import (
    TemperatureMapBracket,
    at_temperature,
    interpolate_temperature_map,
    solve_temperature_bracket,
)
from tests.test_flux_linkage_map import FakeSolver, _config
from tests.test_thermal_network import inputs


class TemperatureSolver(FakeSolver):
    def __call__(self, config):
        result = super().__call__(config)
        scale = br_scale(config.materials.magnet_grade, config.solve_params.magnet_temperature_C)
        dq = result.summary.dq_flux_linkage
        dq.lambda_d_Wb *= scale
        dq.lambda_q_Wb *= scale
        dq.torque_dq_Nm *= scale
        result.summary.avg_torque_Nm *= scale
        result.summary.iron_loss = result.summary.iron_loss.model_copy(update={
            "iron_loss_W": 3 * scale, "iron_hysteresis_loss_W": 2 * scale, "iron_eddy_loss_W": scale,
        })
        return result


@pytest.fixture
def bracket(tmp_path):
    return solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=TemperatureSolver(), store_root=tmp_path)


def test_two_resumable_maps_and_no_solver_inside_interpolation(tmp_path):
    solver = TemperatureSolver()
    bracket = solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path)
    assert len(solver.calls) == 58
    resumed = solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path)
    assert len(solver.calls) == 58
    assert resumed.low.rotor_positions == bracket.low.rotor_positions == 12
    result = interpolate_temperature_map(resumed, 35)
    assert len(solver.calls) == 58
    assert result.br_weight == pytest.approx(0.25)
    a, b, c = bracket.low.points[10], bracket.high.points[10], result.map.points[10]
    for field in ("lambda_d_Wb", "lambda_q_Wb", "avg_torque_Nm", "iron_loss_W", "iron_hysteresis_loss_W", "iron_eddy_loss_W"):
        assert getattr(c, field) == pytest.approx(0.75 * getattr(a, field) + 0.25 * getattr(b, field))
    assert c.nonlinear_iterations_max is None and c.torque_ripple_pct is None
    assert result.map.scope_key not in {bracket.low.scope_key, bracket.high.scope_key, map_scope_key(at_temperature(_config(), 35))}
    assert type(result).model_validate_json(result.model_dump_json()) == result
    assert result.status == "experimental"


@pytest.mark.parametrize("temperature", [19, 81, float("nan"), float("inf")])
def test_no_extrapolation(bracket, temperature):
    with pytest.raises(ValueError, match="never extrapolate"):
        interpolate_temperature_map(bracket, temperature)


def test_every_point_field_has_an_explicit_temperature_interpolation_policy(bracket):
    from backend.models import FluxLinkageMapPoint

    interpolated = {"avg_torque_Nm", "lambda_d_Wb", "lambda_q_Wb", "iron_loss_W",
                    "iron_hysteresis_loss_W", "iron_eddy_loss_W"}
    nulled = {"torque_ripple_pct", "nonlinear_iterations_max", "nonlinear_residual_max", "rotor_iron_loss"}
    inherited = {"current_peak_A", "gamma_deg", "i_d_A", "i_q_A", "status", "error"}
    assert set(FluxLinkageMapPoint.model_fields) == interpolated | nulled | inherited, "Classify new map-point fields before interpolation"
    derived = interpolate_temperature_map(bracket, 35).map
    for low, high, result in zip(bracket.low.points, bracket.high.points, derived.points, strict=True):
        for name in interpolated:
            assert getattr(result, name) == pytest.approx(0.75 * getattr(low, name) + 0.25 * getattr(high, name))
        for name in nulled:
            assert getattr(result, name) is None
        for name in inherited:
            assert getattr(result, name) == getattr(low, name) == getattr(high, name)


def test_endpoint_values_and_temperature_changes_preserve_separate_constraints(bracket):
    for temperature, original in ((20, bracket.low), (80, bracket.high)):
        derived = interpolate_temperature_map(bracket, temperature).map
        assert derived.points[10].avg_torque_Nm == pytest.approx(original.points[10].avg_torque_Nm)
    cold, hot = bracket.low.points[10], bracket.high.points[10]
    assert cold.avg_torque_Nm > hot.avg_torque_Nm
    # Hotter magnets reduce the inductive/no-load voltage here, so colder is
    # the stricter voltage condition while hotter delivers less torque.
    assert math.hypot(cold.lambda_d_Wb, cold.lambda_q_Wb) > math.hypot(hot.lambda_d_Wb, hot.lambda_q_Wb)


def test_brackets_reject_other_design_missing_points_and_unknown_temperature_grade(bracket, tmp_path):
    changed = bracket.design.model_copy(update={"name": "Same physics"})
    assert TemperatureMapBracket(design=changed, preset="preview", low=bracket.low, high=bracket.high)
    changed = bracket.design.model_copy(update={"stator": bracket.design.stator.model_copy(update={"stack_length_mm": 45})})
    with pytest.raises(ValueError, match="identity"):
        TemperatureMapBracket(design=changed, preset="preview", low=bracket.low, high=bracket.high)
    with pytest.raises(ValueError, match="every grid point"):
        TemperatureMapBracket(design=bracket.design, preset="preview",
                              low=bracket.low.model_copy(update={"points": bracket.low.points[:-1]}), high=bracket.high)
    changed = bracket.design.model_copy(update={"materials": bracket.design.materials.model_copy(update={"magnet_grade": "Ferrite_Y30"})})
    solver = TemperatureSolver()
    with pytest.raises(ValueError, match="No cited"):
        solve_temperature_bracket(changed, 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path)
    assert not solver.calls


def test_thermal_only_solves_skip_rotor_iron_loss_and_keep_plain_identities(tmp_path):
    """Rotor iron loss on the source design must not cost a rotor turn per thermal map pose."""
    from backend.models import DriveLimits
    from backend.models.config import SolveOptionsConfig
    from backend.thermal_rating import coupled_point, verify_limiting_point

    plain = _config()
    rotor = plain.model_copy(update={"solve_options": SolveOptionsConfig(rotor_iron_loss=True)})
    assert at_temperature(plain, 20).solve_options is None
    assert at_temperature(rotor, 20).solve_options == SolveOptionsConfig()
    requested = []

    class Recording(TemperatureSolver):
        def __call__(self, config):
            requested.append(bool(config.solve_options and config.solve_options.rotor_iron_loss))
            return super().__call__(config)

    solver = Recording()
    bracket = solve_temperature_bracket(rotor, 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path)
    assert len(requested) == 58 and not any(requested)
    assert bracket.design.solve_options.rotor_iron_loss, "The source design keeps its own selection"
    for temperature, flux_map in ((20, bracket.low), (80, bracket.high)):
        assert not flux_map.rotor_iron_loss_requested
        assert flux_map.scope_key == map_scope_key(at_temperature(plain, temperature))
        ordinary = rotor.model_copy(update={"solve_params": rotor.solve_params.model_copy(update={"magnet_temperature_C": temperature})})
        assert flux_map.scope_key != map_scope_key(ordinary), "An ordinary rotor-loss map stays a separate namespace"
    # The design without rotor loss resolves the same identities and reuses the solved maps.
    solve_temperature_bracket(plain, 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path)
    assert len(requested) == 58
    # Rating verification solves the same thermal-only configuration; it never reads a rotor record.
    cooling = inputs(housing_h_W_m2K=1000, end_space_h_W_m2K=1000, airgap_h_W_m2K=500)
    point = coupled_point(bracket, cooling, speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    assert point.status == "experimental", point.status_reason
    verify_limiting_point(bracket, cooling, DriveLimits(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000), point, solver)
    assert requested[58:] == [False] and point.verification_metrics


def reference(bracket, temperature):
    config = at_temperature(bracket.design, temperature)
    solver = TemperatureSolver()
    direct = run_flux_linkage_map(config, solve=solver, peak_current_A=20)
    off_grid = []
    for current, gamma in ((7.5, 22.5), (17.5, 52.5), (17.5, 82.5)):
        off_grid.append(point_from_result(current, gamma, solver(point_config(config, current, gamma))))
    return TemperatureReference(temperature_C=temperature, computation_scope_key=direct.scope_key,
                                points=[*direct.points, *off_grid], direct_map=direct, source="Analytic test, not native evidence")


def check(bracket, references):
    return check_temperature_interpolation(bracket, references,
        limits=DriveLimits(dc_bus_V=12, peak_current_A=20, max_speed_rpm=10000), phase_resistance_ohm=0.01,
        thermal_inputs=inputs(magnet_frequency_limit_Hz=1000))


def test_broader_acceptance_includes_off_grid_loss_temperature_and_fw(bracket):
    refs = [reference(bracket, temperature) for temperature in (35, 50, 65)]
    result = check(bracket, refs)
    assert result.status == "PASS", result.model_dump()
    assert result.output_status == "experimental"
    names = {metric["name"] for metric in result.metrics}
    assert {"lambda_d", "lambda_q", "torque", "iron_loss", "temperature", "voltage", "voltage_feasibility", "base_speed", "max_speed"} <= names


def test_missing_acceptance_is_not_compared_and_bad_reference_is_rejected(bracket):
    assert check(bracket, []).status == "NOT_COMPARED"
    ref = reference(bracket, 50)
    ref.direct_map = None
    result = check(bracket, [ref])
    assert result.status == "NOT_COMPARED"
    ref.computation_scope_key = "wrong-computation"
    with pytest.raises(ValueError, match="identity"):
        check(bracket, [ref])


def test_bad_midpoint_remains_experimental_and_reports_failure(bracket):
    refs = [reference(bracket, temperature) for temperature in (35, 50, 65)]
    refs[1].points[-1] = refs[1].points[-1].model_copy(update={"iron_hysteresis_loss_W": 1000.0})
    result = check(bracket, refs)
    assert result.status == "FAIL" and result.output_status == "experimental"
    assert any(metric["name"] == "iron_loss" and metric["status"] == "FAIL" for metric in result.metrics)


def test_frozen_bands_and_yellow_absolute_floor():
    assert BANDS["lambda_d"] == (0.01, 1e-6)
    assert BANDS["temperature"] == (0, 2)
    assert _metric("torque", 0.075, 0)["status"] == "YELLOW"
    assert _metric("torque", 0.2, 0)["status"] == "FAIL"


def test_registered_fixtures_bands_and_collectable_off_grid_points(tmp_path):
    import hashlib

    from backend.models.thermal import ThermalInputs
    from backend.resources import data_file
    from tools.check_temperature_maps import collect, registration

    spec = registration()
    assert spec["intermediate_C"] == [35, 50, 65]
    assert set(spec["bands"]) == set(BANDS)
    for name, (relative, floor) in BANDS.items():
        assert spec["bands"][name] == dict(relative=relative, absolute_floor=floor, yellow_multiplier=2)
    for case in spec["cases"]:
        assert hashlib.sha256(data_file(case["fixture"]).read_bytes()).hexdigest() == case["fixture_sha256"]
    assert ThermalInputs.model_validate(spec["thermal_inputs"])
    # Exercise the same collector against an analytic fake without labelling
    # it a native record. This checks serialization and registration plumbing.
    result = collect(spec["cases"][0], spec, tmp_path, TemperatureSolver())
    assert len(result["references"]) == 3
    assert all(len(ref["points"]) == 38 for ref in result["references"])
    assert result["acceptance"]["output_status"] == "experimental"
    assert result["registration_sha256"] == hashlib.sha256(data_file(
        "benchmarks/thermal-v0.6/map-interpolation-gates.json").read_bytes()).hexdigest()


def test_a_bracket_reports_its_place_in_both_maps(tmp_path):
    reported, solver = [], TemperatureSolver()
    solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path,
                              progress=lambda index, done, total: reported.append((index, done, total)))
    total = reported[0][2]
    assert 2 * total == len(solver.calls) == 58
    assert [row for row in reported if row[0] == 0] == [(0, done, total) for done in range(1, total + 1)]
    assert [row for row in reported if row[0] == 1] == [(1, done, total) for done in range(1, total + 1)]
    # A resumed job solves nothing again and still reports where it stands.
    again = []
    solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=solver, store_root=tmp_path,
                              progress=lambda *row: again.append(row))
    assert again == reported and len(solver.calls) == 58
