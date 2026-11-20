"""Native history gates must expose sampling failure and exclude the endpoint."""

from dataclasses import replace

import numpy as np
import pytest

from backend.iron_loss import M350_50A_LOSS
from backend.rotor_iron_loss import RotorFieldSample
from tools.rotor_excitation_report import saved_current_error
from tools.rotor_native_remesh_probe import linear_gradient_sample, static_potential
from tools.rotor_native_report import loss_rows, material_mesh_metrics


def history():
    corner = np.array([[[10., 0.], [12., 0.], [10., 2.]]])
    samples = [RotorFieldSample(-360*k/32, corner, np.array([0.8+0.1*np.cos(2*np.pi*k/32)]),
                               np.array([0.]), np.array([0])) for k in range(32)]
    # This deliberately invalid endpoint must never enter a harmonic estimate.
    samples.append(replace(samples[0], mechanical_angle_deg=-360, bx_t=np.array([10000.])))
    return samples


def test_independent_analytical_loss_and_endpoint_exclusion():
    rows, steps = loss_rows(history(), 32, 3000, 0.05)
    mass = 2e-6*0.05*M350_50A_LOSS.density_kg_m3
    h = mass*M350_50A_LOSS.kh*50*0.1**M350_50A_LOSS.alpha
    e = mass*M350_50A_LOSS.kc*50**2*0.1**2
    for row in rows:
        assert row["sampling_gate"] == "PASS" and row["self_consistency_pass"]
        assert np.isclose(row["production_sampling"]["hysteresis_W"], h, rtol=1e-12)
        assert np.isclose(row["production_sampling"]["lamination_eddy_W"], e, rtol=1e-12)
    assert all(step["pass"] for step in steps)


def test_missing_material_points_fail_every_angular_gate():
    samples = history()
    samples[4] = replace(samples[4], corners_mm=samples[4].corners_mm+100)
    rows, steps = loss_rows(samples, 32, 3000, 0.05)
    assert all(row["sampling_gate"] == "FAIL" for row in rows)
    assert not any(step["pass"] for step in steps)


def test_fixed_material_mesh_gate_detects_real_geometry_changes_and_missing_cells():
    samples = history()[:32]
    assert material_mesh_metrics(samples)["gate"] == "PASS"
    original = samples[4]
    samples[4] = replace(original, corners_mm=original.corners_mm+1e-4)
    assert material_mesh_metrics(samples)["gate"] == "FAIL"
    samples[4] = replace(original, corners_mm=np.concatenate((original.corners_mm, original.corners_mm)))
    assert material_mesh_metrics(samples)["gate"] == "FAIL"


def test_static_potential_has_known_values_and_remeshing_changes_linear_gradients():
    # The same square and same time-invariant potential, triangulated across
    # opposite diagonals. Raw piecewise-linear FE gradients need not be equal.
    a = np.array([[[10., 1.], [12., 1.], [10., 3.]], [[12., 1.], [12., 3.], [10., 3.]]])
    b = np.array([[[10., 1.], [12., 1.], [12., 3.]], [[10., 1.], [12., 3.], [10., 3.]]])
    assert np.isclose(static_potential([[[28., 0.], [0., 0.], [0., 28.]]])[0], 0.7*0.028/4)
    left, right = linear_gradient_sample(a, 0), linear_gradient_sample(b, 0)
    assert not np.allclose(left.bx_t, right.bx_t, rtol=1e-5)


@pytest.mark.parametrize("density,error", [(2, 0), (-2, 320), (1, 80)])
def test_saved_femm_density_is_checked_in_ampere_turns(density, error):
    model = f'<BeginBlock>\n<BlockName> = "Coil_v3_s0_l0"\n<J_re> = {density}\n<EndBlock>\n'
    applied = {"Coil_v3_s0_l0": {"area_mm2": 80, "ampere_turns": 160}}
    assert saved_current_error(model, applied) == error


def test_missing_femm_winding_cannot_pass_the_current_audit():
    with pytest.raises(ValueError, match="winding materials"):
        saved_current_error("", {"Coil_v3_s0_l0": {"area_mm2": 80, "ampere_turns": 160}})
