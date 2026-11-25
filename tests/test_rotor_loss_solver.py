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
    cfg.solve_params.corner_refinement = True
    cfg.solve_params.solve_quality = "standard"
    calls, progress, meshes = [], [], []
    monkeypatch.setattr(rotor, "POSITIONS", 32)

    def mesh(config, *, rotor_angle_deg, rotor_loss_mesh):
        meshes.append((config.solve_params.corner_refinement, rotor_angle_deg, rotor_loss_mesh))
        return {"solve_mesh_artifact": "template"}

    monkeypatch.setattr(rotor, "run_gmsh_mesh_preview", mesh)

    class Motion:
        def __init__(self, template):
            assert template == "template"

        def at_angle(self, config, angle):
            return {"pose": angle}

    def solve(config, *, sweep, rotor_angle_deg, solve_mesh_artifact, nonlinear_tolerance):
        assert not sweep and solve_mesh_artifact["pose"] == rotor_angle_deg
        assert config.solve_params.current_angle_deg == 180
        # The turn's own tolerance, not the one Standard quality would pick (0.01).
        assert nonlinear_tolerance == rotor.NONLINEAR_TOLERANCE == 1e-7
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
    # One rotor-loss mesh, without the corner profile, and the design itself is left as it was.
    assert meshes == [(False, 0, True)] and cfg.solve_params.corner_refinement
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


OUTER_FIXTURE = FIXTURE.parents[2] / "af-v1.10/measured-fixtures/spm_outer_14p12s_drone__baseline.json"


def test_an_outer_rotor_is_solved_and_its_result_says_the_ring_is_taken_as_laminated(monkeypatch):
    cfg = MotorConfig.model_validate(json.loads(OUTER_FIXTURE.read_text()))
    cfg.solve_params.nonlinear_solver = "newton"
    assert cfg.rotor_layout == "outer" and rotor.unavailable_reason(cfg) is None
    assert rotor.planned_positions(cfg.model_copy(update={"solve_options": cfg.solve_options.model_copy(
        update={"rotor_iron_loss": True})})) == rotor.POSITIONS+1
    monkeypatch.setattr(rotor, "POSITIONS", 32)
    monkeypatch.setattr(rotor, "run_gmsh_mesh_preview", lambda *a, **kw: {"solve_mesh_artifact": "template"})
    monkeypatch.setattr(rotor, "FixedMaterialRotorMesh", lambda template: type("Motion", (), {
        "at_angle": staticmethod(lambda config, angle: {"pose": angle})})())
    monkeypatch.setattr(rotor, "run_magneto2d_report",
                        lambda config, *, sweep, rotor_angle_deg, solve_mesh_artifact, nonlinear_tolerance:
                        analytic_report(rotor_angle_deg))
    value = rotor.compute_rotor_iron_loss(cfg, workers=2)
    assert value.status == "experimental", value.status_reason
    assert value.rotor_iron_loss_W > 0 and "solid steel rotor shell" in value.status_reason
    inner = rotor.compute_rotor_iron_loss(config(), workers=2)
    assert inner.status == "experimental" and "solid steel" not in inner.status_reason


def test_sector_is_explicitly_unavailable_without_starting_an_expensive_full_solve(monkeypatch):
    cfg = config()
    cfg.solve_params.symmetry = "auto"
    monkeypatch.setattr(rotor, "run_gmsh_mesh_preview", lambda *a, **kw: pytest.fail("unsupported solve must not start"))
    value = rotor.compute_rotor_iron_loss(cfg)
    assert value.status == "unavailable" and value.solved_region == "sector"
    assert value.rotor_iron_loss_W is None and "sector" in value.status_reason


def test_picard_is_explicitly_unavailable_without_starting_an_expensive_full_solve(monkeypatch):
    cfg = config()
    cfg.solve_params.nonlinear_solver = "picard"
    monkeypatch.setattr(rotor, "run_gmsh_mesh_preview", lambda *a, **kw: pytest.fail("unsupported solve must not start"))
    assert rotor.planned_positions(cfg) == 0
    value = rotor.compute_rotor_iron_loss(cfg)
    assert value.status == "unavailable" and value.rotor_iron_loss_W is None
    assert "Newton" in value.status_reason and "NoneType" not in value.status_reason


def test_a_position_solved_by_the_picard_fallback_is_refused_in_plain_words():
    # Picard reports raw_max_residual and leaves Newton's residuals empty.
    fallback = analytic_report(0)
    fallback["solve_info"]["nonlinear_convergence"].update(
        method="picard", fallback_from="newton", tolerance=0.05, raw_max_residual=0.04,
        scaled_residual=None, rhs_scaled_residual=None, absolute_residual_floor=None)
    with pytest.raises(ValueError, match="Picard fallback"):
        rotor.field_sample(fallback, 0)
    newton = analytic_report(0)
    newton["solve_info"]["nonlinear_convergence"]["method"] = "newton"
    assert rotor.field_sample(newton, 0) is not None


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


def test_the_rotor_loss_mesh_halves_the_air_gap_slot_mouth_and_magnet_corner_sizes_and_nothing_else():
    from backend.gmsh_solver import ROTOR_LOSS_FEATURE_SIZE_SCALE, run_gmsh_mesh_preview

    def smallest(out):
        nodes, triangles = np.asarray(out["nodes_mm"]), np.asarray(out["triangles"])
        corners = nodes[triangles]
        edges = np.stack([np.linalg.norm(corners[:, i]-corners[:, (i+1) % 3], axis=1) for i in range(3)], axis=1).max(axis=1)
        regions = np.asarray(out["element_region_ids"])
        return {kind: edges[np.char.startswith(regions, kind)].min() for kind in ("airgap", "stator_tooth", "magnet")}

    cfg = config()
    usual = run_gmsh_mesh_preview(cfg, rotor_angle_deg=0)
    assert usual["triangles"] == run_gmsh_mesh_preview(cfg, rotor_angle_deg=0, rotor_loss_mesh=False)["triangles"]
    fine = run_gmsh_mesh_preview(cfg, rotor_angle_deg=0, rotor_loss_mesh=True)
    before, after = smallest(usual), smallest(fine)
    assert ROTOR_LOSS_FEATURE_SIZE_SCALE == 0.5
    for kind in before:
        assert 0.35 < after[kind] / before[kind] < 0.65, (kind, before[kind], after[kind])
    assert len(usual["triangles"]) < len(fine["triangles"]) < 2.5 * len(usual["triangles"])
