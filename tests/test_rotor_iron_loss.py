"""Analytical rotor-material tests; expected losses do not call the loss kernel."""

from dataclasses import replace

import numpy as np
import pytest

from backend.iron_loss import FieldFrame, SteinmetzCoefficients
from backend.rotor_iron_loss import (
    RotorLossMaterial,
    RotorSamplingPlan,
    harmonic_rotor_iron_loss,
    rotor_flux_history,
    sample_rotor_field,
)
from tools.rotor_loss_reference import reference_loss

COEFFICIENTS = SteinmetzCoefficients(kh=0.02, alpha=2.1, kc=0.0003, density_kg_m3=7650)
MATERIAL = RotorLossMaterial("synthetic-steel", "analytical fixture, not measured data", COEFFICIENTS)
STACK = 0.05
MASS = 4e-6 * STACK * COEFFICIENTS.density_kg_m3


def frame_at(angle_deg, field, *, refined=False, reorder=False):
    """A rotating 2 x 2 mm steel patch; a second mesh splits its triangles."""
    nodes = np.array([[10, -1], [12, -1], [12, 1], [10, 1], [11, 0]], dtype=float)
    triangles = np.array([[0, 1, 2], [0, 2, 3]])
    if refined:
        triangles = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
    if reorder:
        triangles = triangles[::-1, ::-1]
    angle = np.deg2rad(angle_deg)
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    global_nodes = nodes @ rotation.T
    global_field = np.tile(np.asarray(field) @ rotation.T, (len(triangles), 1))
    return FieldFrame(global_nodes, triangles, ["rotor_core"] * len(triangles), global_field[:, 0], global_field[:, 1])


def history_for(plan, waveform, *, remesh=False):
    return rotor_flux_history(plan, [
        sample_rotor_field(
            frame_at(angle, waveform(2 * np.pi * k / plan.positions), refined=remesh and k % 2 == 1, reorder=k % 3 == 1),
            mechanical_angle_deg=angle,
        )
        for k, angle in enumerate(plan.mechanical_angles_deg)
    ])


def expected_loss(terms, speed_rpm, mass=MASS):
    """Terms are (mechanical order, peak vector amplitude); scalar arithmetic."""
    h = e = 0.0
    for order, amplitude in terms:
        frequency = speed_rpm / 60 * order
        h += mass * COEFFICIENTS.kh * frequency * amplitude ** COEFFICIENTS.alpha
        e += mass * COEFFICIENTS.kc * frequency ** 2 * amplitude ** 2
    return h, e


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("start", [0.0, 37.0])
def test_rigidly_rotating_field_is_dc_in_rotor_axes(direction, start):
    plan = RotorSamplingPlan(3000, 32, direction, start)
    history = history_for(plan, lambda t: (1.2, -0.4), remesh=True)
    assert history.bx_t == pytest.approx(np.full((32, 2), 1.2), abs=1e-14)
    assert history.by_t == pytest.approx(np.full((32, 2), -0.4), abs=1e-14)
    estimate = harmonic_rotor_iron_loss(history, material=MATERIAL, stack_length_m=STACK)
    assert estimate.total_W < 1e-20
    assert estimate.rotor_iron_mass_kg == pytest.approx(MASS)
    assert history.distinct_meshes > 1


@pytest.mark.parametrize("direction", [-1, 1])
def test_known_sinusoid_uses_mechanical_frequency_and_vector_components(direction):
    plan = RotorSamplingPlan(1800, 64, direction)
    history = history_for(plan, lambda t: (1.0 + 0.3 * np.cos(3 * t), 0.4 * np.sin(3 * t)), remesh=True)
    estimate = harmonic_rotor_iron_loss(history, material=MATERIAL, stack_length_m=STACK)
    # sqrt(0.3^2 + 0.4^2) = 0.5 in the documented harmonic-vector convention.
    h, e = expected_loss([(3, 0.5)], plan.speed_rpm)
    assert estimate.hysteresis_W == pytest.approx(h, rel=0.01)
    assert estimate.lamination_eddy_W == pytest.approx(e, rel=0.01)


def test_multiharmonic_loss_and_speed_scaling_with_dc_bias():
    def waveform(t):
        return 1.4 + 0.2 * np.cos(2*t) + 0.1 * np.sin(5*t), 0.0
    slow = harmonic_rotor_iron_loss(history_for(RotorSamplingPlan(1500, 64), waveform), material=MATERIAL, stack_length_m=STACK)
    fast = harmonic_rotor_iron_loss(history_for(RotorSamplingPlan(3000, 64), waveform), material=MATERIAL, stack_length_m=STACK)
    h, e = expected_loss([(2, 0.2), (5, 0.1)], 1500)
    assert slow.hysteresis_W == pytest.approx(h, rel=0.01)
    assert slow.lamination_eddy_W == pytest.approx(e, rel=0.01)
    assert fast.hysteresis_W == pytest.approx(2 * h, rel=0.01)
    assert fast.lamination_eddy_W == pytest.approx(4 * e, rel=0.01)
    filled = harmonic_rotor_iron_loss(
        history_for(RotorSamplingPlan(1500, 64), waveform), material=replace(MATERIAL, stacking_factor=0.95), stack_length_m=STACK,
    )
    assert filled.total_W == pytest.approx(0.95 * slow.total_W)
    assert filled.rotor_iron_mass_kg == pytest.approx(0.95 * MASS)


def test_reordering_preserves_nonuniform_fields_and_reference_mass():
    plan = RotorSamplingPlan(3000, 16)
    samples = []
    for k, angle in enumerate(plan.mechanical_angles_deg):
        frame = frame_at(angle, (0.0, 0.0))
        # Distinct material cells: ensure mapping is geometric, not index-based.
        field = np.array([[0.1, 0.0], [0.3, 0.0]]) * np.cos(2*np.pi*k/16)
        radians = np.deg2rad(angle)
        rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
        field = field @ rotation.T
        triangles = frame.triangles
        if k % 2:
            triangles, field = triangles[::-1], field[::-1]
        frame = replace(frame, triangles=triangles, bx_t=field[:, 0], by_t=field[:, 1])
        samples.append(sample_rotor_field(frame, mechanical_angle_deg=angle))
    history = rotor_flux_history(plan, samples)
    assert history.bx_t[:, 0] == pytest.approx(0.1*np.cos(2*np.pi*np.arange(16)/16))
    assert history.bx_t[:, 1] == pytest.approx(0.3*np.cos(2*np.pi*np.arange(16)/16))


def test_only_explicit_rotor_core_is_sampled():
    frame = frame_at(0, (1.0, 0.0), refined=True)
    frame = replace(frame, regions=["shaft", "Magnet", "rotor_core", "stator_yoke"])
    sample = sample_rotor_field(frame, mechanical_angle_deg=0)
    assert sample.source_element_index.tolist() == [2]
    with pytest.raises(ValueError, match="explicitly tagged"):
        sample_rotor_field(replace(frame, regions=["steel"]*4), mechanical_angle_deg=0)


def test_incomplete_or_mislabelled_period_is_rejected():
    plan = RotorSamplingPlan(3000, 8)
    samples = [sample_rotor_field(frame_at(a, (1, 0)), mechanical_angle_deg=a) for a in plan.mechanical_angles_deg]
    with pytest.raises(ValueError, match="complete sampling plan"):
        rotor_flux_history(plan, samples[:-1])
    with pytest.raises(ValueError, match="unwrapped plan"):
        rotor_flux_history(plan, samples[:-1] + [replace(samples[-1], mechanical_angle_deg=360)])


def test_missing_material_points_cannot_be_extrapolated():
    plan = RotorSamplingPlan(3000, 8)
    samples = [sample_rotor_field(frame_at(a, (1, 0)), mechanical_angle_deg=a) for a in plan.mechanical_angles_deg]
    samples[3] = replace(samples[3], corners_mm=samples[3].corners_mm + 100)
    with pytest.raises(ValueError, match="outside rotor steel"):
        rotor_flux_history(plan, samples)


@pytest.mark.parametrize("changes", [{"speed_rpm": 0}, {"speed_rpm": float("nan")}, {"positions": 4},
                                     {"positions": True}, {"direction": 0}, {"start_mechanical_deg": float("inf")}])
def test_sampling_plan_refuses_invalid_inputs(changes):
    with pytest.raises(ValueError):
        RotorSamplingPlan(**({"speed_rpm": 3000, "positions": 16} | changes))


def test_plan_is_half_open_and_records_actual_pose_and_elapsed_time():
    plan = RotorSamplingPlan(3000, 16, -1, 20)
    assert plan.period_s == 0.02
    assert plan.base_frequency_hz == 50
    assert plan.mechanical_angles_deg[-1] == 20 - 337.5
    assert plan.metadata()["half_wave_reconstruction"] is False
    assert plan.metadata()["angle_convention"] == "native_ccw_mechanical_unwrapped"


def test_independent_dft_oracle_reproduces_analytical_loss():
    plan = RotorSamplingPlan(1500, 64)
    # Construct the oracle's global-vector input directly from the test frames.
    global_vectors = []
    for k, angle in enumerate(plan.mechanical_angles_deg):
        frame = frame_at(angle, (1.4 + 0.2*np.cos(2*np.pi*2*k/64), 0.1*np.sin(2*np.pi*5*k/64)))
        global_vectors.append(np.column_stack([frame.bx_t, frame.by_t]))
    result = reference_loss(
        global_vectors, plan.mechanical_angles_deg, [2e-6, 2e-6], speed_rpm=1500, stack_m=STACK,
        coefficients={"kh": 0.02, "alpha": 2.1, "kc": 0.0003, "density_kg_m3": 7650},
    )
    h, e = expected_loss([(2, 0.2), (5, 0.1)], 1500)
    assert result["hysteresis_W"] == pytest.approx(h, rel=0.01)
    assert result["lamination_eddy_W"] == pytest.approx(e, rel=0.01)


@pytest.mark.parametrize("stack", [0, -1, float("nan"), float("inf")])
def test_stack_length_must_be_positive_and_finite(stack):
    history = history_for(RotorSamplingPlan(3000, 16), lambda t: (np.cos(t), 0))
    with pytest.raises(ValueError, match="stack length"):
        harmonic_rotor_iron_loss(history, material=MATERIAL, stack_length_m=stack)


def test_nonfinite_fields_and_degenerate_integration_cells_are_rejected():
    frame = frame_at(0, (1, 0))
    with pytest.raises(ValueError, match="finite"):
        sample_rotor_field(replace(frame, bx_t=np.array([float("nan"), 1])), mechanical_angle_deg=0)
    with pytest.raises(ValueError, match="out of bounds"):
        sample_rotor_field(replace(frame, triangles=np.array([[0, 1, 99]])), mechanical_angle_deg=0)
    plan = RotorSamplingPlan(3000, 8)
    samples = [sample_rotor_field(frame_at(a, (1, 0)), mechanical_angle_deg=a) for a in plan.mechanical_angles_deg]
    samples = [replace(s, corners_mm=np.zeros_like(s.corners_mm)) for s in samples]
    with pytest.raises(ValueError, match="positive element areas"):
        rotor_flux_history(plan, samples)
