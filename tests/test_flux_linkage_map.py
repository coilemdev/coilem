"""Flux-linkage map runner (#139): grid, resume, failures and scope, with a stand-in solver."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.flux_linkage_map import (
    MapStore,
    map_agreement_pct,
    map_grid,
    map_positions_per_point,
    map_scope_key,
    map_solve_count,
    point_config,
    run_flux_linkage_map,
)
from backend.models import DqFluxLinkage, IronLoss, MotorConfig
from backend.solver_contract import SolveCancelledError

RAW = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))
LAMBDA_PM, L_D, L_Q = 0.0113, 4.7e-5, 4.8e-5


def _config(**changes) -> MotorConfig:
    raw = deepcopy(RAW)
    raw["solve_params"].update(changes)
    return MotorConfig.model_validate(raw)


class FakeSolver:
    """An analytic SPM in place of the FEM solve; records every operating point it is asked for."""

    def __init__(self, *, fail_at: tuple[float, float] | None = None, cancel_after: int | None = None):
        self.calls: list[tuple[float, float]] = []
        self.fail_at = fail_at
        self.cancel_after = cancel_after

    def __call__(self, config: MotorConfig):
        params = config.solve_params
        assert params.current_amplitude_convention == "peak" and params.excitation_mode == "sinusoidal"
        point = (params.current_amplitude_A, params.current_angle_deg)
        if self.cancel_after is not None and len(self.calls) >= self.cancel_after:
            raise SolveCancelledError("cancelled")
        self.calls.append(point)
        if point == self.fail_at:
            raise RuntimeError("mesh failed")
        import math
        current, gamma = point
        i_d, i_q = -current * math.sin(math.radians(gamma)), current * math.cos(math.radians(gamma))
        lambda_d, lambda_q = LAMBDA_PM + L_D * i_d, L_Q * i_q
        torque = 1.5 * 2 * (lambda_d * i_q - lambda_q * i_d)
        dq = DqFluxLinkage(
            current_angle_convention="q_axis_gamma_flux_weakening_positive", transform="amplitude_invariant_park",
            i_d_A=i_d, i_q_A=i_q, lambda_d_Wb=lambda_d, lambda_q_Wb=lambda_q, torque_dq_Nm=torque,
        )
        iron = IronLoss(
            status="experimental", steel="M350-50A", electrical_frequency_Hz=100.0, iron_loss_W=3.0,
            iron_hysteresis_loss_W=2.0, iron_eddy_loss_W=1.0, stator_iron_mass_kg=0.5,
            validated_max_frequency_Hz=1000.0, validated_max_flux_density_T=1.5,
        )
        return SimpleNamespace(
            summary=SimpleNamespace(avg_torque_Nm=torque, torque_ripple_pct=-4.0, dq_flux_linkage=dq, iron_loss=iron),
            solve_metadata=SimpleNamespace(rotor_positions=12, nonlinear_max_iterations_used=6, nonlinear_worst_final_mismatch=2e-6),
        )


def test_presets_give_the_grid_and_the_solve_count():
    currents, gammas = map_grid(20.0, "preview")
    assert currents == [0.0, 5.0, 10.0, 15.0, 20.0]
    assert gammas == [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0]
    assert map_solve_count(currents, gammas) == 29  # the zero-current point once
    currents, gammas = map_grid(20.0, "standard")
    assert len(currents) == 7 and gammas[1] == 10.0 and gammas[-1] == 90.0
    assert map_solve_count(currents, gammas) == 61
    with pytest.raises(ValueError):
        map_grid(0.0)


def test_point_config_sets_a_sinusoidal_peak_current_at_the_angle():
    config = point_config(_config(current_amplitude_convention="rms", excitation_mode="sinusoidal"), 12.5, 30.0, "preview")
    params = config.solve_params
    assert (params.current_amplitude_A, params.current_amplitude_convention, params.current_angle_deg) == (12.5, "peak", 30.0)
    # Half a cycle, stopping one step short of 180° because a partial sweep includes its end.
    assert (params.solve_quality, params.rotor_sweep_range_deg, params.rotor_step_deg) == ("custom", 165.0, 15.0)
    assert map_positions_per_point("preview") == 12 and map_positions_per_point("standard") == 24
    assert params.stream_noload_field_lines is False
    assert config.solve_options.back_emf is False and config.solve_options.torque_sweep is True
    assert point_config(_config(), 0.0, 0.0).solve_options.back_emf is True  # the zero-current point keeps it
    assert point_config(_config(solve_quality="fine"), 1.0, 0.0, "standard").solve_params.rotor_step_deg == 7.5


def test_map_runs_every_point_once_and_reports_progress(tmp_path):
    solver = FakeSolver()
    seen = []
    config = _config()
    flux_map = run_flux_linkage_map(
        config, solve=solver, peak_current_A=20.0, store=MapStore(tmp_path, map_scope_key(config)),
        progress=lambda done, total, point, eta: seen.append((done, total)),
    )
    assert len(solver.calls) == 29
    assert solver.calls.count((0.0, 0.0)) == 1
    assert seen[-1] == (29, 29) and [done for done, _ in seen] == list(range(1, 30))
    assert len(flux_map.points) == 35 and all(point.status == "ok" for point in flux_map.points)
    assert flux_map.pole_pairs == 2 and flux_map.reference_speed_rpm == 3000
    point = next(p for p in flux_map.points if (p.current_peak_A, p.gamma_deg) == (10.0, 30.0))
    assert point.torque_ripple_pct == 4.0 and point.iron_hysteresis_loss_W == 2.0 and point.nonlinear_iterations_max == 6
    assert all(value is None or value == pytest.approx(100.0) for value in map_agreement_pct(flux_map))
    assert MapStore(tmp_path, map_scope_key(config)).load_map() == flux_map


def test_a_cancelled_map_resumes_without_solving_finished_points(tmp_path):
    config = _config()
    store = MapStore(tmp_path, map_scope_key(config))
    with pytest.raises(SolveCancelledError):
        run_flux_linkage_map(config, solve=FakeSolver(cancel_after=10), peak_current_A=20.0, store=store)
    resumed = FakeSolver()
    flux_map = run_flux_linkage_map(config, solve=resumed, peak_current_A=20.0, store=store)
    assert len(resumed.calls) == 29 - 10
    assert (0.0, 0.0) not in resumed.calls
    assert all(point.status == "ok" for point in flux_map.points)


def test_a_failed_point_is_recorded_and_solved_again_on_the_next_run(tmp_path):
    config = _config()
    store = MapStore(tmp_path, map_scope_key(config))
    flux_map = run_flux_linkage_map(config, solve=FakeSolver(fail_at=(10.0, 45.0)), peak_current_A=20.0, store=store)
    failed = [point for point in flux_map.points if point.status == "failed"]
    assert [(p.current_peak_A, p.gamma_deg, p.error) for p in failed] == [(10.0, 45.0, "mesh failed")]
    retry = FakeSolver()
    run_flux_linkage_map(config, solve=retry, peak_current_A=20.0, store=store)
    assert retry.calls == [(10.0, 45.0)]


def test_scope_key_follows_the_machine_not_the_operating_point():
    base = map_scope_key(_config())
    assert map_scope_key(_config(current_amplitude_A=33.0, current_angle_deg=40.0, winding_temperature_C=120.0)) == base
    raw = deepcopy(RAW)
    raw["winding"]["turns_per_coil"] = raw["winding"]["turns_per_coil"] + 1
    assert map_scope_key(MotorConfig.model_validate(raw)) != base
    assert map_scope_key(_config(mesh_density="fine")) != base
    assert map_scope_key(_config(), "standard") != base


def test_a_stopped_speed_has_no_iron_loss_reference():
    with pytest.raises(ValueError, match="rated speed"):
        run_flux_linkage_map(_config(rated_speed_rpm=0), solve=FakeSolver(), peak_current_A=20.0)


def test_agreement_skips_points_with_next_to_no_torque():
    flux_map = run_flux_linkage_map(_config(), solve=FakeSolver(), peak_current_A=20.0)
    agreement = dict(zip(((p.current_peak_A, p.gamma_deg) for p in flux_map.points), map_agreement_pct(flux_map)))
    assert agreement[(20.0, 0.0)] == pytest.approx(100.0)
    assert agreement[(20.0, 90.0)] is None and agreement[(0.0, 0.0)] is None


def test_a_stored_map_is_reused_for_a_lower_peak_when_its_steps_are_fine_enough(tmp_path):
    config = _config()
    store = MapStore(tmp_path, map_scope_key(config))
    run_flux_linkage_map(config, solve=FakeSolver(), peak_current_A=20.0, store=store)
    run_flux_linkage_map(config, solve=FakeSolver(), peak_current_A=40.0, store=store)
    assert store.covering_map(20.0).current_peak_A[-1] == 20.0  # the smallest that reaches it
    assert store.covering_map(15.0).current_peak_A[-1] == 20.0
    assert store.covering_map(30.0).current_peak_A[-1] == 40.0
    assert store.covering_map(45.0) is None  # nothing reaches it
    assert store.covering_map(9.0) is None  # 20 A in 5 A steps is too coarse for a 9 A drive


def test_scope_key_tracks_physics_and_loss_coefficients(monkeypatch):
    from dataclasses import replace

    from backend import flux_linkage_map as maps

    hashes = {"backend/geometry.py": "first"}
    monkeypatch.setattr(maps, "installed_physics_hashes", lambda: (dict(hashes), {"solver.rs": "solver"}))
    config = _config()
    original = map_scope_key(config)
    assert map_scope_key(config) == original
    hashes["backend/geometry.py"] = "changed"
    assert map_scope_key(config) != original
    hashes["backend/geometry.py"] = "first"
    grade = maps.LOSS_GRADES[config.materials.stator_steel]
    monkeypatch.setitem(maps.LOSS_GRADES, config.materials.stator_steel,
                        replace(grade, coefficients=replace(grade.coefficients, kh=grade.coefficients.kh * 1.1)))
    assert map_scope_key(config) != original


def test_scope_key_tracks_solver_identity_and_rejects_missing_identity(monkeypatch, tmp_path):
    from backend import flux_linkage_map as maps

    monkeypatch.delenv("COILEM_MAGNETO2D_BINARY", raising=False)
    monkeypatch.setattr(maps, "installed_physics_hashes", lambda: ({"python": "hash"}, {"solver": "first"}))
    first = map_scope_key(_config())
    monkeypatch.setattr(maps, "installed_physics_hashes", lambda: ({"python": "hash"}, {"solver": "second"}))
    assert map_scope_key(_config()) != first
    monkeypatch.setattr(maps, "installed_physics_hashes", lambda: ({"python": "hash"}, {}))
    with pytest.raises(ValueError, match="solver build identity"):
        map_scope_key(_config())
    binary = tmp_path / "solver"
    binary.write_bytes(b"first executable")
    monkeypatch.setenv("COILEM_MAGNETO2D_BINARY", str(binary))
    first = map_scope_key(_config())
    binary.write_bytes(b"second executable")
    assert map_scope_key(_config()) != first
    monkeypatch.setattr(maps, "installed_physics_hashes", lambda: ({"python": None}, {}))
    with pytest.raises(ValueError, match="physics source"):
        map_scope_key(_config())


def test_installed_solver_stamp_has_the_same_map_identity_as_checkout(monkeypatch):
    from backend.benchmark_suite import record
    from backend.benchmark_suite.physics import BUILD_INFO_KEY

    monkeypatch.delenv("COILEM_MAGNETO2D_BINARY", raising=False)
    _, solver = record.installed_physics_hashes()
    assert solver
    original = map_scope_key(_config())
    monkeypatch.setattr(record, "CHECKOUT", None)
    monkeypatch.setattr(record, "stamped_build_info", lambda: {BUILD_INFO_KEY: solver})
    assert map_scope_key(_config()) == original


def test_imported_steel_is_embedded_in_scope_and_has_no_external_loss_coefficients():
    from pydantic import ValidationError

    from backend.custom_materials import CustomSteel, SteelImportRequest, import_steel
    from backend.flux_linkage_map import map_computation_identity
    from backend.iron_loss import iron_loss_unavailable_reason

    steel = import_steel(SteelImportRequest(name="Test steel", source="Test curve",
        csv_text="B_T,H_A_per_m\n0,0\n1,100\n2,1000\n"))
    raw = _config().model_dump(mode="json")
    raw["materials"].update(stator_steel=steel.id, custom_steels={steel.id: steel.model_dump(mode="json")})
    config = MotorConfig.model_validate(raw)
    assert map_computation_identity(config)["iron_loss"] is None
    assert "No cited loss data" in iron_loss_unavailable_reason(config, [])
    assert config.model_dump(mode="json")["materials"]["custom_steels"][steel.id] == steel.model_dump(mode="json")
    with pytest.raises(ValidationError, match="Extra inputs"):
        CustomSteel.model_validate(steel.model_dump() | {"loss_coefficients": {"kh": 1}})
    changed = import_steel(SteelImportRequest(name="Test steel", source="Test curve",
        csv_text="B_T,H_A_per_m\n0,0\n1,120\n2,1100\n"))
    raw["materials"].update(stator_steel=changed.id, custom_steels={changed.id: changed.model_dump(mode="json")})
    assert map_scope_key(MotorConfig.model_validate(raw)) != map_scope_key(config)
