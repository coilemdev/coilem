"""Full-turn execution preserves native angles, field frames and failure status."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from backend import rotor_loss_solver as rotor
from backend.models import MotorConfig
from backend.solver_contract import SolveCancelledError

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def config():
    cfg = MotorConfig.model_validate(json.loads(FIXTURE.read_text()))
    cfg.solve_params.current_angle_deg = 180
    cfg.solve_params.rated_speed_rpm = 3000
    return cfg


def analytic_report(angle, *, reused=False):
    corners = np.array([[10., 0.], [12., 0.], [11., 2.]])
    a = math.radians(angle)
    rotation = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    nodes = corners @ rotation.T
    material_b = np.array([0.2+0.1*math.cos(3*a), 0.05*math.sin(7*a)])
    global_b = material_b @ rotation.T
    az = (global_b[0]*nodes[:, 1]-global_b[1]*nodes[:, 0])*1e-3
    return {"mesh_info": {"total_span_deg": 360}, "solve_info": {"nonlinear_convergence": {
        "solution_reused": reused, "tolerance": 1e-5, "scaled_residual": 1e-8,
        "rhs_scaled_residual": 1e-8, "absolute_residual_floor": 1e-12}},
        "field_plot": {"total_span_deg": 360, "nodes_mm": nodes.tolist(), "triangles": [[0, 1, 2]],
                       "regions": ["rotor_core"], "az_nodal": az.tolist()}}


@pytest.mark.parametrize("direction", [-1, 1])
def test_full_turn_and_independent_endpoint_produce_the_prescribed_loss(monkeypatch, direction, tmp_path):
    cfg = config()
    calls, progress = [], []
    monkeypatch.setattr(rotor, "POSITIONS", 32)
    monkeypatch.setattr(rotor, "run_gmsh_mesh_preview", lambda *a, **kw: {"solve_mesh_artifact": "template"})

    class Motion:
        def __init__(self, template):
            assert template == "template"

        def at_angle(self, config, angle):
            return {"pose": angle}

    def solve(config, *, sweep, rotor_angle_deg, solve_mesh_artifact):
        assert not sweep and solve_mesh_artifact["pose"] == rotor_angle_deg
        assert config.solve_params.current_angle_deg == 180
        calls.append(rotor_angle_deg)
        return analytic_report(rotor_angle_deg)

    monkeypatch.setattr(rotor, "FixedMaterialRotorMesh", Motion)
    monkeypatch.setattr(rotor, "run_magneto2d_report", solve)
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("COILEM_SOLVE_PROFILE", "1")
    rotor.solve_profile._close_own_records()
    rotor.solve_profile.begin()
    try:
        value = rotor.compute_rotor_iron_loss(cfg, direction=direction, workers=2,
                                             on_progress=lambda n, total, angle: progress.append((n, total)))
    finally:
        profile = rotor.solve_profile.finish(None)
    counts = rotor.solve_profile.breakdown(profile)["counts"]
    assert counts["solves"] == 33 and counts["meshes_built"] == 1 and counts["meshes_rotated"] == 33
    assert value.status == "experimental", value.status_reason
    assert sorted(calls) == sorted(direction*360*k/32 for k in range(33))
    assert progress[-1] == (33, 33) and value.samples_per_mechanical_turn == 32
    assert value.mechanical_frequency_Hz == 50 and len(value.history_sha256) == 64
    mass = 2e-6*0.05*7650
    c = rotor.MATERIAL.coefficients
    expected_h = mass*c.kh*(150*0.1**c.alpha+350*0.05**c.alpha)
    expected_e = mass*c.kc*(150**2*0.1**2+350**2*0.05**2)
    assert value.rotor_hysteresis_loss_W == pytest.approx(expected_h, rel=1e-10)
    assert value.rotor_lamination_eddy_loss_W == pytest.approx(expected_e, rel=1e-10)
    assert value.rotor_iron_loss_W == pytest.approx(expected_h+expected_e, rel=1e-10)


def test_sector_is_explicitly_unavailable_without_starting_an_expensive_full_solve(monkeypatch):
    cfg = config()
    cfg.solve_params.symmetry = "auto"
    monkeypatch.setattr(rotor, "run_gmsh_mesh_preview", lambda *a, **kw: pytest.fail("unsupported solve must not start"))
    value = rotor.compute_rotor_iron_loss(cfg)
    assert value.status == "unavailable" and value.solved_region == "sector"
    assert value.rotor_iron_loss_W is None and "sector" in value.status_reason


def test_reused_or_unconverged_native_fields_cannot_be_loss_inputs():
    with pytest.raises(ValueError, match="fresh, converged"):
        rotor.field_sample(analytic_report(0, reused=True), 0)
    bad = analytic_report(0)
    bad["solve_info"]["nonlinear_convergence"].update(scaled_residual=1, rhs_scaled_residual=1)
    with pytest.raises(ValueError, match="fresh, converged"):
        rotor.field_sample(bad, 0)


def test_duplicate_zero_is_not_an_independently_unwrapped_endpoint():
    plan = rotor.RotorSamplingPlan(3000, 32)
    samples = [rotor.field_sample(analytic_report(angle), angle) for angle in (*plan.mechanical_angles_deg, 0.)]
    with pytest.raises(ValueError, match="independent endpoint"):
        rotor.record_from_samples(config(), plan, samples)


def test_cancellation_is_not_converted_to_a_zero_or_unavailable_loss():
    def cancelled():
        raise SolveCancelledError("cancelled")

    with pytest.raises(SolveCancelledError):
        rotor.compute_rotor_iron_loss(config(), check_cancelled=cancelled)


def test_complete_cache_reuses_only_the_same_sampling_and_operating_point(monkeypatch, tmp_path):
    monkeypatch.setattr(rotor, "POSITIONS", 32)
    calls = []

    def compute(cfg, *, direction, **kwargs):
        calls.append(cfg.solve_params.rated_speed_rpm)
        plan = rotor.RotorSamplingPlan(cfg.solve_params.rated_speed_rpm, 32, direction)
        samples = [rotor.field_sample(analytic_report(a), a) for a in (*plan.mechanical_angles_deg, direction*360.)]
        return rotor.record_from_samples(cfg, plan, samples)

    monkeypatch.setattr(rotor, "compute_rotor_iron_loss", compute)
    cfg = config()
    first = rotor.compute_or_cached(cfg, cache_dir=tmp_path)
    progress = []
    second = rotor.compute_or_cached(cfg, cache_dir=tmp_path, on_progress=lambda n, total, a: progress.append((n, total)))
    assert first == second and calls == [3000] and progress == [(33, 33)]
    cfg.solve_params.rated_speed_rpm = 6000
    third = rotor.compute_or_cached(cfg, cache_dir=tmp_path)
    assert calls == [3000, 6000]
    assert third.rotor_hysteresis_loss_W == pytest.approx(2*first.rotor_hysteresis_loss_W)
    assert third.rotor_lamination_eddy_loss_W == pytest.approx(4*first.rotor_lamination_eddy_loss_W)


def test_unavailable_results_do_not_poison_the_complete_history_cache(monkeypatch, tmp_path):
    calls = []

    def compute(cfg, **kwargs):
        calls.append(1)
        return rotor.unavailable(cfg, "Temporary native solver failure.")

    monkeypatch.setattr(rotor, "compute_rotor_iron_loss", compute)
    rotor.compute_or_cached(config(), cache_dir=tmp_path)
    rotor.compute_or_cached(config(), cache_dir=tmp_path)
    assert len(calls) == 2 and not (tmp_path / "rotor-iron-loss-v1.json").exists()
