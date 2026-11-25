"""Rotor loss at the map, public-orchestration, saved-result and export boundaries."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.drive_performance import MapModel, efficiency_map
from backend.flux_linkage_map import map_scope_key, point_config, point_from_result
from backend.models import RotorIronLoss
from tests.test_drive_performance import LIMITS, R, _map
from tests.test_rotor_loss_accounting import config, rotor


def test_map_key_and_point_requests_keep_rotor_opt_in_separate():
    cfg = config()
    legacy_key = map_scope_key(cfg)
    cfg.solve_options.rotor_iron_loss = True
    assert map_scope_key(cfg) != legacy_key
    point = point_config(cfg, 10, 30)
    assert point.solve_options.rotor_iron_loss and point.solve_options.losses_efficiency
    result = SimpleNamespace(summary=SimpleNamespace(avg_torque_Nm=1, torque_ripple_pct=0,
        dq_flux_linkage=SimpleNamespace(lambda_d_Wb=0.1, lambda_q_Wb=0.01), iron_loss=None, rotor_iron_loss=rotor()),
        solve_metadata=None)
    assert point_from_result(10, 30, result).rotor_iron_loss == rotor()


def rotor_map(*, missing=False):
    flux_map = _map(0.0005, 0.0005)
    flux_map.rotor_iron_loss_requested = True
    for point in flux_map.points:
        point.rotor_iron_loss = rotor()
    if missing:
        flux_map.points[0].rotor_iron_loss = RotorIronLoss(status="unavailable", steel="M350-50A", status_reason="Incomplete history")
    return flux_map


def test_map_efficiency_adds_rotor_once_and_scales_its_two_components_by_speed():
    legacy = _map(0.0005, 0.0005)
    combined = rotor_map()
    model = MapModel.from_map(combined)
    assert np.all(model.iron_hysteresis_W == 22) and np.all(model.iron_eddy_W == 13)
    kwargs = dict(phase_resistance_ohm=R, winding_temperature_C=80, speed_points=4, torque_points=4)
    before = efficiency_map(legacy, LIMITS, **kwargs)
    after = efficiency_map(combined, LIMITS, **kwargs)
    checked = 0
    for row, torque in enumerate(after.torque_Nm):
        for column, rpm in enumerate(after.speed_rpm):
            if after.efficiency_pct[row][column] is None:
                continue
            ratio = rpm / combined.reference_speed_rpm
            expected_rotor = 2 * ratio + 3 * ratio**2
            assert after.rotor_iron_loss_W[row][column] == pytest.approx(expected_rotor)
            assert after.iron_loss_W[row][column] - before.iron_loss_W[row][column] == pytest.approx(expected_rotor)
            input_power = torque * rpm * 2 * np.pi / 60 + after.copper_loss_W[row][column]
            if before.efficiency_pct[row][column] > after.efficiency_pct[row][column] > 0:
                assert before.efficiency_pct[row][column] - after.efficiency_pct[row][column] == pytest.approx(100 * expected_rotor / input_power)
                checked += 1
    assert checked and after.loss_scope == "stator_and_rotor"


def test_missing_rotor_map_history_withholds_efficiency_instead_of_using_zero():
    result = efficiency_map(rotor_map(missing=True), LIMITS, phase_resistance_ohm=R,
        winding_temperature_C=80, speed_points=3, torque_points=3)
    assert result.status == result.rotor_iron_loss_status == "unavailable"
    assert all(value is None for row in result.efficiency_pct for value in row)
    assert all(value is None for row in result.rotor_iron_loss_W for value in row)
    assert "Requested rotor iron loss" in result.status_reason


def test_incomplete_rotor_map_cache_is_retried_and_cannot_cover_a_requested_map(tmp_path):
    from backend.flux_linkage_map import MapStore

    flux_map = rotor_map(missing=True)
    store = MapStore(tmp_path, flux_map.scope_key)
    bad, good = flux_map.points[:2]
    store.save(bad)
    store.save(good)
    store.save_map(flux_map)
    assert store.load(bad.current_peak_A, bad.gamma_deg, require_rotor_loss=True) is None
    assert store.load(good.current_peak_A, good.gamma_deg, require_rotor_loss=True) == good
    assert store.covering_map(flux_map.current_peak_A[-1]) is None
    good.rotor_iron_loss = None
    store.save(good)
    assert store.load(good.current_peak_A, good.gamma_deg) == good
    assert store.load(good.current_peak_A, good.gamma_deg, require_rotor_loss=True) is None


def test_public_orchestration_maps_excitation_once_and_saves_the_rotor_record(monkeypatch):
    import backend.solver as module
    from backend import rotor_loss_solver

    cfg = config()
    cfg.solve_params.current_angle_deg = 0
    cfg.solve_options.rotor_iron_loss = True
    monkeypatch.setattr(module, "_magneto2d_prepare_cache_dir", lambda: False)
    monkeypatch.setattr(module, "_select_magneto2d_torque_series", lambda *a: ([1.0], 1.0, "contour"))
    solver = module.Magneto2DSolver(launch_surface=True)
    events = []

    def fields(config, *, on_progress, **kwargs):
        on_progress(1, 2, None, "magneto2d_sweep", 0)
        return {"sweep": {}}, {}

    def compute(native, *, direction, on_progress, check_cancelled, **kwargs):
        assert native.solve_params.current_angle_deg == 180 and direction == -1
        check_cancelled()
        on_progress(385, 385, -360)
        return rotor()

    def package(config, sweep, single, **kwargs):
        assert sweep["rotor_iron_loss"] == rotor().model_dump(mode="json")
        return SimpleNamespace(summary=SimpleNamespace(solve_time_s=0), solve_metadata=SimpleNamespace(solve_time_s=0, solve_cache_dir=None))

    monkeypatch.setattr(solver, "_solve_with_per_angle_gmsh_meshes", fields)
    monkeypatch.setattr(rotor_loss_solver, "compute_or_cached", compute)
    monkeypatch.setattr(solver, "build_result_from_reports", package)
    solver.solve(cfg, on_progress=lambda *args, **kwargs: events.append(args))
    assert not any(len(e) > 3 and e[3] == "magneto2d_complete" for e in events)
    rotor_event = next(e for e in events if len(e) > 3 and e[3] == "rotor_iron_loss")
    assert rotor_event[0] == rotor_event[1] and rotor_event[1] > 385


def test_rotor_loss_progress_never_moves_back_when_the_field_stage_finishes(monkeypatch):
    """The field stage's last event counts the loaded sweep alone; the bar must not drop to it (#348)."""
    import backend.solver as module
    from backend import rotor_loss_solver

    cfg = config()
    cfg.solve_params.current_angle_deg = 0
    cfg.solve_options.rotor_iron_loss = True
    monkeypatch.setattr(module, "_magneto2d_prepare_cache_dir", lambda: False)
    monkeypatch.setattr(module, "_select_magneto2d_torque_series", lambda *a: ([1.0], 1.0, "contour"))
    solver = module.Magneto2DSolver(launch_surface=True)
    events = []

    def fields(config, *, on_progress, **kwargs):
        # Loaded and no-load sweeps together, then the loaded sweep's own completion count.
        for done in range(1, 50):
            on_progress(done, 49, None, "magneto2d_sweep", 0)
        on_progress(25, 25, 1.0, "magneto2d_complete", None)
        return {"sweep": {}}, {}

    def compute(native, *, direction, on_progress, check_cancelled, **kwargs):
        for position in range(1, 386):
            on_progress(position, 385, -position)
        return rotor()

    def package(config, sweep, single, **kwargs):
        return SimpleNamespace(summary=SimpleNamespace(solve_time_s=0), solve_metadata=SimpleNamespace(solve_time_s=0, solve_cache_dir=None))

    monkeypatch.setattr(solver, "_solve_with_per_angle_gmsh_meshes", fields)
    monkeypatch.setattr(rotor_loss_solver, "compute_or_cached", compute)
    monkeypatch.setattr(solver, "build_result_from_reports", package)
    solver.solve(cfg, on_progress=lambda *args, **kwargs: events.append(args))
    counted = [e for e in events if len(e) > 3 and e[3] in ("magneto2d_sweep", "rotor_iron_loss")]
    assert {e[1] for e in counted} == {49 + 385}, "one total for the whole run"
    done = [e[0] for e in counted]
    assert done == sorted(done) and done[-1] == 49 + 385, "the bar only moves forward"
    assert not any(len(e) > 3 and e[3] == "magneto2d_complete" for e in events)


def test_saved_rotor_record_survives_postprocessing_and_csv_and_is_unavailable_on_sector():
    from backend.models import SolveResult
    from backend.public_report import build_public_run_csv
    from backend.solver import Magneto2DSolver
    from backend.solver._helpers import _aggregate_per_angle_mesh_sweep
    from backend.sweep_planning import loaded_angle_grid
    from tests.test_analysis_options import native

    cfg = config()
    cfg.solve_options.rotor_iron_loss = True
    angles = loaded_angle_grid(cfg)
    sweep = _aggregate_per_angle_mesh_sweep(cfg, [native(angle) for angle in angles], None, angles,
        mesh_generation_time_ms=0, include_visual_frames=False)
    sweep["rotor_iron_loss"] = rotor().model_dump(mode="json")
    result = Magneto2DSolver.build_result_from_reports(cfg, sweep, native(0), pipeline_stage="postprocess")
    assert result.summary.rotor_iron_loss == rotor()
    assert SolveResult.model_validate_json(result.model_dump_json()).summary.rotor_iron_loss == rotor()
    output = build_public_run_csv(project={}, request={}, result=result.model_dump(mode="json"), material={}, manifest={})
    assert b"rotor_iron_loss,history_sha256" in output and b"rotor_iron_loss,rotor_iron_loss_W,W,5" in output
    cfg.solve_params.symmetry = "auto"
    sector = Magneto2DSolver.build_result_from_reports(cfg, sweep, native(0), pipeline_stage="postprocess")
    assert sector.summary.rotor_iron_loss.status == "unavailable"
    assert sector.summary.loss_breakdown.efficiency_pct is None
