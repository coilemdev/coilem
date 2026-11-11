"""Cogging orchestration regressions: real planning/cache, stand-ins only for FEM."""
from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

import backend.solver as solver
from backend import solver_environment
from backend.cogging import cogging_record
from backend.models import MotorConfig
from backend.sweep_planning import cogging_angle_grid, full_cycle_back_emf_angle_grid

EXAMPLE = Path(__file__).resolve().parents[1] / 'benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json'


@pytest.fixture
def pipeline(monkeypatch):
    config = MotorConfig.model_validate_json(EXAMPLE.read_text())
    config.solve_params.solve_quality = 'quick'
    config.solve_options.cogging_torque = True
    config.solve_params.stream_noload_field_lines = False
    config.solve_options.back_emf = False
    config.solve_options.thd_analysis = False
    config.solve_options.flux_density = False
    built, solved = [], []

    class Producer:
        source = 'gmsh'
        display_name = 'Gmsh'

        @staticmethod
        def build(config, angle):
            artifact = {'angle': angle, 'mesh_origin': len(built)}
            built.append(deepcopy(artifact))
            return artifact, 0

    def rotate(artifact, config, angle):
        return {**deepcopy(artifact), 'angle': angle, 'derived': True}

    def report(config, **kwargs):
        solved.append((config.solve_params.current_amplitude_A, kwargs['rotor_angle_deg']))
        angle = kwargs['rotor_angle_deg']
        return {'results': {'torque_nm': angle, 'torque_weighted_stress_nm': angle}}

    monkeypatch.setattr(solver, 'estimate_magneto2d_sweep_angle_grid', lambda _: [0.0, 60.0])
    monkeypatch.setattr(solver, '_gmsh_imported_mesh_pipeline_enabled', lambda *args: True)
    monkeypatch.setattr(solver, '_gmsh_pipeline_worker_count', lambda *args, **kwargs: 1)
    monkeypatch.setattr(solver, '_rotate_gmsh_artifact_for_config', rotate)
    monkeypatch.setattr(solver, '_rebake_gmsh_artifact_for_config', lambda artifact, config: deepcopy(artifact))
    monkeypatch.setattr(solver, '_zero_current_solve_mesh_artifact', lambda artifact: artifact)
    monkeypatch.setattr(solver, 'slot_current_pattern_matches', lambda *args: False)
    monkeypatch.setattr(solver, 'gmsh_solve_reuse_enabled', lambda: False)
    monkeypatch.setattr(solver, 'build_solve_mesh_evidence', lambda *args, **kwargs: {'geometry_sha256': 'stand-in'})
    monkeypatch.setattr(solver, 'run_magneto2d_report', report)
    monkeypatch.setattr(solver, 'run_magneto2d_batch_reports', lambda config, jobs, **kwargs: [
        report(config, rotor_angle_deg=job['rotor_angle_deg']) for job in jobs
    ])
    monkeypatch.setattr(solver, '_assert_imported_mesh_consumed_by_rust', lambda *args, **kwargs: None)
    monkeypatch.setattr(solver, '_aggregate_per_angle_mesh_sweep', lambda *args, **kwargs: {'sweep': {}})
    monkeypatch.setattr(solver, '_angle_mesh_cache_enabled', lambda: True)
    monkeypatch.setattr(solver, '_angle_mesh_cache_max_entries', lambda: 256)
    monkeypatch.setattr(solver, 'solver_setting', lambda name, default=None: '1' if name == 'COILEM_MAGNETO2D_COMPACT_QA_REPORT' else default)
    solver.clear_per_angle_gmsh_mesh_cache()

    def run():
        return solver._solve_with_per_angle_producer_meshes(config, Producer(), solve_cache_dir=None, clockwise_positive=True)[0]['sweep']

    yield config, built, solved, run
    solver.clear_per_angle_gmsh_mesh_cache()


def test_disabling_reuse_remeshes_cached_rotated_endpoints_before_claiming_independence(pipeline, monkeypatch):
    config, built, _, run = pipeline
    config.rotor.pole_count = 4  # one cogging period equals one slot pitch
    enabled = True
    monkeypatch.setattr(solver, 'gmsh_mesh_reuse_enabled', lambda: enabled)
    first = run()
    assert first['cogging_endpoints_independent'] is False
    artifacts = list(solver._PER_ANGLE_GMSH_MESH_CACHE.values())
    endpoints = [artifact for artifact in artifacts if artifact['angle'] in (0, -30)]
    assert len(endpoints) == 2
    assert len({artifact['mesh_origin'] for artifact in endpoints}) == 1
    assert any(artifact.get('derived') for artifact in endpoints), 'the warm cache really contains a rotated endpoint'
    cold_builds = len(built)

    enabled = False
    independent = run()
    assert len(built) > cold_builds, 'turning reuse off must build independent meshes, not just change the diagnostic flag'
    assert independent['cogging_endpoints_independent'] is True
    scope = solver._angle_mesh_cache_scope_key(config, clockwise_positive=True)
    endpoint_keys = [solver._per_angle_grid_key(angle) for angle in (0, 60)]
    actual = solver._angle_mesh_cache_take_all(scope, endpoint_keys)
    assert len({artifact['mesh_origin'] for artifact in actual.values()}) == 2
    assert not any(artifact.get('derived') for artifact in actual.values())
    independent_builds = len(built)
    assert run()['cogging_endpoints_independent'] is True
    assert len(built) == independent_builds, 'independent meshes still support warm-cache reuse'

    enabled = True
    assert run()['cogging_endpoints_independent'] is False
    assert len(built) == independent_builds, 'the original rotated cache remains valid in its own mode'
    for key in ('cogging_rotor_positions_elec_deg', 'cogging_torque_waveform_nm'):
        assert independent[key] == first[key]


@pytest.mark.parametrize('execution', ['pipeline', 'batch', 'parallel', 'serial'])
@pytest.mark.parametrize(('slots', 'poles'), [(12, 8), (9, 8), (12, 10)])
def test_back_emf_and_cogging_solve_each_shared_no_current_angle_once(pipeline, monkeypatch, slots, poles, execution):
    config, _, solved, run = pipeline
    config.stator.slot_count, config.rotor.pole_count = slots, poles
    config.solve_options.back_emf = True
    monkeypatch.setattr(solver, '_gmsh_imported_mesh_pipeline_enabled', lambda *args: execution == 'pipeline')
    monkeypatch.setattr(solver, '_imported_mesh_batch_enabled', lambda *args: execution == 'batch')
    monkeypatch.setattr(solver, '_per_angle_parallel_workers', lambda *args: 2 if execution == 'parallel' else 1)
    monkeypatch.setattr(solver, '_per_angle_subprocess_workers', lambda *args: 1)
    monkeypatch.setattr(solver, 'gmsh_mesh_reuse_enabled', lambda: False)
    sweep = run()
    no_current_angles = [-angle * (poles // 2) for current, angle in solved if current == 0]
    expected = {*full_cycle_back_emf_angle_grid(config, [0.0, 60.0]), *cogging_angle_grid(config)}
    counts = Counter(round(angle, 6) for angle in no_current_angles)
    assert counts == Counter(round(angle, 6) for angle in expected)
    assert all(count == 1 for count in counts.values())
    assert sweep['cogging_rotor_positions_elec_deg'] == cogging_angle_grid(config)
    record = cogging_record(sweep['cogging_rotor_positions_elec_deg'], sweep['cogging_torque_waveform_nm'],
                           slot_count=slots, pole_count=poles, method=sweep['cogging_torque_method'])
    assert record is not None and record.positions_per_period == 12


@pytest.mark.parametrize(('isolated', 'override', 'count'), [
    (False, '0.7', 30), (False, '100', 2), (False, 'invalid', 13), (True, '0.7', 13),
])
def test_diagnostic_step_override_and_public_environment_boundary(monkeypatch, isolated, override, count):
    config = MotorConfig.model_validate_json(EXAMPLE.read_text())
    config.solve_options.cogging_torque = True
    config.stator.slot_count, config.rotor.pole_count = 9, 8
    config.solve_params.solve_quality = 'quick'
    monkeypatch.setattr(solver_environment, 'ISOLATED_RUNTIME', isolated)
    monkeypatch.setenv('MAGNETO2D_COGGING_STEP_DEG', override)
    grid = solver._cogging_angle_grid(config)
    assert len(grid) == count
    assert (grid[0], grid[-1]) == pytest.approx((0, 20))
    assert all(b - a == pytest.approx(20 / (count - 1)) for a, b in zip(grid, grid[1:]))
    if not isolated and override == '0.7':
        assert max(b - a for a, b in zip(grid, grid[1:])) <= 0.7


@pytest.mark.parametrize(('slots', 'poles', 'period', 'order'), [(9, 8, 20, 72), (12, 10, 30, 60)])
@pytest.mark.parametrize(('quality', 'positions'), [('quick', 12), ('standard', 24), ('fine', 48), ('custom', 24)])
def test_large_lcm_grids_keep_the_preset_resolution(slots, poles, period, order, quality, positions):
    config = MotorConfig.model_validate_json(EXAMPLE.read_text())
    config.stator.slot_count, config.rotor.pole_count = slots, poles
    config.solve_options.cogging_torque = True
    config.solve_params.solve_quality = quality
    angles = cogging_angle_grid(config)
    assert len(angles) == positions + 1
    assert angles[-1] == pytest.approx(period)
    assert all(b - a == pytest.approx(period / positions) for a, b in zip(angles, angles[1:]))
    torque = [math.sin(2 * math.pi * angle / period) for angle in angles]
    record = cogging_record(angles, torque, slot_count=slots, pole_count=poles, method='weighted_stress')
    assert record.positions_per_period == positions
    assert record.fundamental_order == order
    assert record.first_harmonic_Nm == pytest.approx(1)


def _held_sweep_report(monkeypatch):
    report = {'sweep': {}, 'comparison_mesh_evidence': {}}
    monkeypatch.setattr(solver, '_aggregate_per_angle_mesh_sweep', lambda *args, **kwargs: report)
    monkeypatch.setattr(
        solver, '_field_line_frames_from_reports',
        lambda reports, angles, *args, **kwargs: [{'angle_deg': angle} for angle in angles],
    )
    return report


def test_a_cogging_only_run_stores_its_cogging_positions_as_field_frames(pipeline, monkeypatch):
    # #241: with one loaded position the run had a single field frame, so the Field view had nothing to play.
    config, _, _, run = pipeline
    config.solve_options.torque_sweep = False
    config.solve_options.losses_efficiency = False
    monkeypatch.setattr(solver, 'estimate_magneto2d_sweep_angle_grid', lambda _: [0.0])
    report = _held_sweep_report(monkeypatch)
    run()
    assert [frame['angle_deg'] for frame in report['field_line_frames']] == cogging_angle_grid(config)
    assert len(report['field_line_frames']) >= 2


def test_a_run_with_a_loaded_sweep_keeps_its_own_field_frames(pipeline, monkeypatch):
    config, _, _, run = pipeline
    config.solve_options.torque_sweep = True
    report = _held_sweep_report(monkeypatch)
    run()
    assert 'field_line_frames' not in report
