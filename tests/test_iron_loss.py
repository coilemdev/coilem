"""Iron-loss coefficients, stator element mapping across meshes, and harmonic loss."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from backend.iron_loss import (
    LOSS_GRADES,
    M350_50A_LOSS,
    M400_50A_LOSS,
    PRIUS_PYLEECAN_STEEL,
    VALIDATED_MAX_FLUX_DENSITY_T,
    FieldFrame,
    SteinmetzCoefficients,
    estimate_iron_loss,
    grade_limit_coefficients,
    harmonic_iron_loss,
    stator_flux_history,
)
from backend.models import IronLoss, MotorConfig
from backend.public_routes import solve as public_solve
from backend.reference_models import prius

CONFIG = MotorConfig.model_validate(
    json.loads((Path(__file__).resolve().parent / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8"))
)

STACK_M = 0.05
CELLS = 4


def _grid_mesh(cells: int = CELLS, half_mm: float = 1.0):
    """Square stator patch; every cell split along its rising diagonal."""
    coords = np.linspace(-half_mm, half_mm, cells + 1)
    nodes = np.array([(x, y) for y in coords for x in coords])
    triangles, cell_of = [], []
    for row in range(cells):
        for col in range(cells):
            n0 = row * (cells + 1) + col
            n1, n2, n3 = n0 + 1, n0 + cells + 1, n0 + cells + 2
            triangles += [[n0, n1, n3], [n0, n3, n2]]
            cell_of += [(row, col), (row, col)]
    return nodes, np.array(triangles), cell_of


def _frame(nodes, triangles, bx, by, regions=None) -> FieldFrame:
    count = len(triangles)
    return FieldFrame(
        nodes_mm=np.asarray(nodes, dtype=float),
        triangles=np.asarray(triangles, dtype=int),
        regions=regions or ["stator_tooth"] * count,
        bx_t=np.asarray(bx, dtype=float),
        by_t=np.asarray(by, dtype=float),
    )


def _uniform_frames(waveform_t, positions: int):
    nodes, triangles, _ = _grid_mesh()
    frames = []
    for k in range(positions):
        value = waveform_t(2 * math.pi * k / positions)
        frames.append(_frame(nodes, triangles, [value] * len(triangles), [0.0] * len(triangles)))
    return frames


def _patch_mass_kg(coefficients: SteinmetzCoefficients = M350_50A_LOSS) -> float:
    return (2e-3 * 2e-3) * STACK_M * coefficients.density_kg_m3


def test_m350_50a_coefficients_meet_the_grade_limits_at_50_hz():
    assert M350_50A_LOSS.specific_loss_w_per_kg(50.0, 1.0) == pytest.approx(1.50, abs=1e-12)
    assert M350_50A_LOSS.specific_loss_w_per_kg(50.0, 1.5) == pytest.approx(3.50, abs=1e-12)
    expected_kc = math.pi**2 * (0.50e-3) ** 2 / (6.0 * 42.2e-8 * 7650.0)
    assert M350_50A_LOSS.kc == pytest.approx(expected_kc)
    assert 1.6 < M350_50A_LOSS.alpha < 2.5


def test_m400_50a_coefficients_meet_the_grade_limits_at_50_hz():
    assert M400_50A_LOSS.specific_loss_w_per_kg(50.0, 1.0) == pytest.approx(1.70, abs=1e-12)
    assert M400_50A_LOSS.specific_loss_w_per_kg(50.0, 1.5) == pytest.approx(4.00, abs=1e-12)
    expected_kc = math.pi**2 * (0.50e-3) ** 2 / (6.0 * 33.4e-8 * 7700.0)
    assert M400_50A_LOSS.kc == pytest.approx(expected_kc)
    assert 1.6 < M400_50A_LOSS.alpha < 2.5


def test_the_pinned_prius_steel_takes_the_m400_50a_coefficients():
    # The Pyleecan Prius imports Pyleecan's M400-50A B-H curve as a custom steel.
    materials = prius.fixture()["materials"]
    assert materials["stator_steel"] == materials["rotor_steel"] == PRIUS_PYLEECAN_STEEL
    assert LOSS_GRADES[PRIUS_PYLEECAN_STEEL].grade == "M400-50A"
    assert LOSS_GRADES[PRIUS_PYLEECAN_STEEL].coefficients is M400_50A_LOSS

    config = CONFIG.model_copy(update={"materials": CONFIG.materials.model_copy(update={"stator_steel": PRIUS_PYLEECAN_STEEL})})
    estimate = estimate_iron_loss(config, _samples(1.0, pole_pitches=2), _cycle())
    poles = config.rotor.pole_count
    frequency = config.solve_params.rated_speed_rpm * (poles // 2) / 60.0
    mass = (2e-3 * 2e-3) * config.stator.stack_length_mm * 1e-3 * 7700.0 * poles / 2
    assert estimate.status == "experimental"
    assert "M400-50A grade limits" in estimate.status_reason
    assert estimate.steel == PRIUS_PYLEECAN_STEEL
    assert estimate.stator_iron_mass_kg == pytest.approx(mass)
    assert estimate.iron_loss_W == pytest.approx(mass * M400_50A_LOSS.specific_loss_w_per_kg(frequency, 1.0))


def test_teeth_and_yoke_are_split_only_when_the_stator_has_both():
    nodes, triangles, _ = _grid_mesh()
    count = len(triangles)
    regions = ["stator_tooth"] * (count // 2) + ["stator_yoke"] * (count - count // 2)

    def history(region_tags):
        frames = [
            _frame(nodes, triangles, [math.cos(2 * math.pi * k / 8)] * count, [0.0] * count, region_tags)
            for k in range(8)
        ]
        return stator_flux_history([frame.stator_sample() for frame in frames])

    split = harmonic_iron_loss(history(regions), electrical_frequency_hz=50.0, stack_length_m=STACK_M, machine_scale=1.0)
    assert split.teeth_w + split.yoke_w == pytest.approx(split.total_w)
    assert split.teeth_w > 0 and split.yoke_w > 0
    # The Pyleecan Prius draws its whole stator as one yoke region.
    whole = harmonic_iron_loss(history(["stator_yoke"] * count), electrical_frequency_hz=50.0, stack_length_m=STACK_M, machine_scale=1.0)
    assert whole.total_w > 0
    assert whole.teeth_w is None and whole.yoke_w is None


def test_grade_limits_without_positive_hysteresis_are_rejected():
    with pytest.raises(ValueError, match="hysteresis"):
        grade_limit_coefficients(
            p10_w_per_kg=0.10, p15_w_per_kg=0.20, thickness_m=0.50e-3, resistivity_ohm_m=1e-8, density_kg_m3=7650.0
        )


def test_uniform_sinusoidal_field_matches_hand_calculation():
    frequency, peak = 100.0, 1.2
    history = stator_flux_history(_uniform_frames(lambda theta: peak * math.cos(theta), positions=16))
    estimate = harmonic_iron_loss(history, electrical_frequency_hz=frequency, stack_length_m=STACK_M, machine_scale=3.0)
    mass = 3.0 * _patch_mass_kg()
    assert estimate.stator_iron_mass_kg == pytest.approx(mass)
    assert estimate.hysteresis_w == pytest.approx(mass * M350_50A_LOSS.kh * frequency * peak**M350_50A_LOSS.alpha)
    assert estimate.eddy_w == pytest.approx(mass * M350_50A_LOSS.kc * frequency**2 * peak**2)
    assert estimate.total_w == pytest.approx(mass * M350_50A_LOSS.specific_loss_w_per_kg(frequency, peak))
    assert estimate.share_above_validated_frequency == 0.0
    assert estimate.share_above_validated_flux_density == 0.0
    # Each element's W/kg splits into its hysteresis and eddy-current parts.
    assert estimate.element_hysteresis_w_per_kg + estimate.element_eddy_w_per_kg == pytest.approx(estimate.element_w_per_kg)
    assert estimate.element_eddy_w_per_kg[0] == pytest.approx(M350_50A_LOSS.kc * frequency**2 * peak**2)


def test_half_a_cycle_with_half_wave_symmetry_gives_the_full_cycle_loss():
    frequency = 80.0

    def field(theta: float) -> float:  # odd harmonics only: B(θ + 180°) = −B(θ)
        return 1.1 * math.cos(theta) + 0.15 * math.cos(5 * theta + 0.3) + 0.05 * math.cos(7 * theta - 0.4)

    full = stator_flux_history(_uniform_frames(field, positions=32))
    half_frames = _uniform_frames(field, positions=32)[:16]
    half = stator_flux_history(half_frames)
    kwargs = dict(electrical_frequency_hz=frequency, stack_length_m=STACK_M, machine_scale=1.0)
    expected = harmonic_iron_loss(full, **kwargs)
    got = harmonic_iron_loss(half, half_wave=True, **kwargs)
    assert got.total_w == pytest.approx(expected.total_w)
    assert got.eddy_w == pytest.approx(expected.eddy_w)
    assert got.element_w_per_kg == pytest.approx(expected.element_w_per_kg)


def test_each_harmonic_adds_its_own_loss():
    frequency = 80.0
    history = stator_flux_history(
        _uniform_frames(lambda theta: 1.0 * math.cos(theta) + 0.2 * math.cos(5 * theta + 0.3), positions=32)
    )
    estimate = harmonic_iron_loss(history, electrical_frequency_hz=frequency, stack_length_m=STACK_M, machine_scale=1.0)
    expected = _patch_mass_kg() * (
        M350_50A_LOSS.specific_loss_w_per_kg(frequency, 1.0) + M350_50A_LOSS.specific_loss_w_per_kg(5 * frequency, 0.2)
    )
    assert estimate.total_w == pytest.approx(expected)


def test_loss_outside_the_grade_data_is_reported():
    saturated = stator_flux_history(_uniform_frames(lambda theta: 1.6 * math.cos(theta), positions=8))
    estimate = harmonic_iron_loss(saturated, electrical_frequency_hz=50.0, stack_length_m=STACK_M, machine_scale=1.0)
    assert 1.6 > VALIDATED_MAX_FLUX_DENSITY_T
    assert estimate.share_above_validated_flux_density == pytest.approx(1.0)
    fast = stator_flux_history(_uniform_frames(lambda theta: 1.0 * math.cos(theta), positions=8))
    estimate = harmonic_iron_loss(fast, electrical_frequency_hz=1200.0, stack_length_m=STACK_M, machine_scale=1.0)
    assert estimate.share_above_validated_frequency == pytest.approx(1.0)


def test_identical_meshes_in_another_element_order_map_directly():
    nodes, triangles, _ = _grid_mesh()
    order = np.random.default_rng(7).permutation(len(triangles))
    values = np.arange(len(triangles), dtype=float)
    reference = _frame(nodes, triangles, values, np.zeros(len(triangles)))
    shuffled = _frame(nodes, triangles[order], values[order] + 100.0, np.zeros(len(triangles)))
    history = stator_flux_history([reference, shuffled])
    assert history.distinct_meshes == 2
    np.testing.assert_allclose(history.bx_t[1], values + 100.0)


def test_rotated_copy_positions_are_located_in_their_own_mesh():
    nodes, triangles, cell_of = _grid_mesh()

    def cell_value(row: int, col: int) -> float:
        return 0.1 * row + 0.01 * col

    reference = _frame(nodes, triangles, [cell_value(*cell) for cell in cell_of], np.zeros(len(triangles)))
    # A quarter turn maps the square onto itself but flips every cell's
    # diagonal, so no rotated triangle coincides with a reference triangle.
    rotated_nodes = np.column_stack([-nodes[:, 1], nodes[:, 0]])
    corners = rotated_nodes[triangles]
    centroids = corners.mean(axis=1)
    step = 2.0 / CELLS
    rotated_cells = [(int((cy + 1.0) // step), int((cx + 1.0) // step)) for cx, cy in centroids]
    rotated = _frame(rotated_nodes, triangles, [cell_value(*cell) for cell in rotated_cells], np.zeros(len(triangles)))

    history = stator_flux_history([reference, rotated])
    assert history.distinct_meshes == 2
    # The field sits on fixed cells in space, so every reference element reads its own cell's value.
    np.testing.assert_allclose(history.bx_t[1], history.bx_t[0])


def test_reference_elements_outside_a_rotated_mesh_are_an_error():
    nodes, triangles, _ = _grid_mesh()
    reference = _frame(nodes, triangles, np.ones(len(triangles)), np.zeros(len(triangles)))
    shifted_nodes = np.column_stack([nodes[:, 0] + 0.75, -nodes[:, 1]])
    shifted = _frame(shifted_nodes, triangles, np.ones(len(triangles)), np.zeros(len(triangles)))
    with pytest.raises(ValueError, match="fall outside"):
        stator_flux_history([reference, shifted])


def test_only_stator_iron_contributes():
    nodes, triangles, _ = _grid_mesh()
    regions = ["stator_tooth"] * (len(triangles) // 2) + ["airgap"] * (len(triangles) - len(triangles) // 2)
    frames = []
    for k in range(8):
        theta = 2 * math.pi * k / 8
        bx = [math.cos(theta) if region == "stator_tooth" else 50.0 * math.cos(theta) for region in regions]
        frames.append(_frame(nodes, triangles, bx, np.zeros(len(triangles)), regions=regions))
    estimate = harmonic_iron_loss(stator_flux_history(frames), electrical_frequency_hz=50.0, stack_length_m=STACK_M, machine_scale=1.0)
    assert estimate.stator_iron_mass_kg == pytest.approx(_patch_mass_kg() / 2)
    assert estimate.total_w == pytest.approx(_patch_mass_kg() / 2 * M350_50A_LOSS.specific_loss_w_per_kg(50.0, 1.0))


def test_a_single_position_is_rejected():
    nodes, triangles, _ = _grid_mesh()
    with pytest.raises(ValueError, match="two rotor positions"):
        stator_flux_history([_frame(nodes, triangles, np.ones(len(triangles)), np.zeros(len(triangles)))])


def _cycle(positions: int = 16):
    return [360.0 * k / positions for k in range(positions)]


def _samples(peak_t: float, positions: int = 16, pole_pitches: int | None = None):
    return [frame.stator_sample(pole_pitches) for frame in _uniform_frames(lambda theta: peak_t * math.cos(theta), positions)]


def test_estimate_reports_an_experimental_loss_for_m350_50a():
    estimate = estimate_iron_loss(CONFIG, _samples(1.0, pole_pitches=2), _cycle())
    poles = CONFIG.rotor.pole_count
    frequency = CONFIG.solve_params.rated_speed_rpm * (poles // 2) / 60.0
    mass = (2e-3 * 2e-3) * CONFIG.stator.stack_length_mm * 1e-3 * 7650.0 * poles / 2
    assert estimate.status == "experimental"
    assert estimate.electrical_frequency_Hz == pytest.approx(frequency)
    assert estimate.stator_iron_mass_kg == pytest.approx(mass)
    assert estimate.iron_loss_W == pytest.approx(mass * M350_50A_LOSS.specific_loss_w_per_kg(frequency, 1.0))
    assert estimate.iron_loss_W == pytest.approx(estimate.iron_hysteresis_loss_W + estimate.iron_eddy_loss_W)


def test_a_uniform_half_cycle_sweep_has_iron_loss():
    angles = [180.0 * k / 8 for k in range(8)]
    estimate = estimate_iron_loss(CONFIG, _samples(1.0, positions=8), angles)
    assert estimate.status == "experimental"


@pytest.mark.parametrize(
    ("change", "angles", "reason"),
    [
        ({"materials": CONFIG.materials.model_copy(update={"stator_steel": "custom-abc"})}, _cycle(), "No cited loss data"),
        ({"solve_params": CONFIG.solve_params.model_copy(update={"rated_speed_rpm": 0})}, _cycle(), "nonzero speed"),
        ({}, [180.0 * k / 15 for k in range(16)], "full electrical cycle"),
        ({}, _cycle(4), "full electrical cycle"),
    ],
)
def test_estimate_says_why_iron_loss_is_unavailable(change, angles, reason):
    config = CONFIG.model_copy(update=change)
    estimate = estimate_iron_loss(config, _samples(1.0, positions=len(angles)), angles)
    assert estimate.status == "unavailable"
    assert reason in estimate.status_reason
    assert estimate.iron_loss_W is None


def test_estimate_without_a_position_sample_is_unavailable():
    samples = _samples(1.0)
    samples[3] = None
    estimate = estimate_iron_loss(CONFIG, samples, _cycle())
    assert estimate.status == "unavailable"
    assert "stator field" in estimate.status_reason


def test_iron_loss_record_rules():
    limits = {"steel": "M350-50A", "validated_max_frequency_Hz": 1000.0, "validated_max_flux_density_T": 1.5}
    with pytest.raises(ValidationError, match="status_reason"):
        IronLoss(status="unavailable", **limits)
    with pytest.raises(ValidationError, match="must not carry values"):
        IronLoss(status="unavailable", status_reason="no", iron_loss_W=1.0, **limits)
    with pytest.raises(ValidationError, match="must equal iron_loss_W"):
        IronLoss(
            status="experimental", electrical_frequency_Hz=100.0, iron_loss_W=3.0, iron_hysteresis_loss_W=1.0,
            iron_eddy_loss_W=1.0, stator_iron_mass_kg=0.2, **limits,
        )


def test_iron_loss_reaches_public_results():
    assert "iron_loss" not in public_solve._EXCLUDED_SUMMARY_FIELDS
