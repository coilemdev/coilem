"""Independent analytical gates for the finite linear Halbach array.

The oracle in this file deliberately does not import production geometry,
meshing, postprocessing, or solver helpers.  It treats each magnet as a
uniformly magnetized rectangle with ``mu_r = 1`` and superposes the exact 2D
field from its four bound magnetic surface-charge segments.

Only the intended public source contract is imported:

* ``LinearHalbachArrayConfig`` and its canonical fixture;
* ``block_magnetization_angle_deg``;
* ``build_linear_planar_geometry``.

Production indexes blocks from left to right.  In the repository's +x/+y
coordinates, a +90 degree progression therefore enhances the positive-y side
and a -90 degree progression enhances the negative-y side.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass

import pytest

from backend.halbach.linear_geometry import (
    block_magnetization_angle_deg,
    build_linear_planar_geometry,
)
from backend.halbach.linear_models import (
    LinearHalbachArrayConfig,
    canonical_linear_halbach_config,
)


@dataclass(frozen=True)
class _RectangleMagnet:
    x_min_mm: float
    x_max_mm: float
    y_min_mm: float
    y_max_mm: float
    br_x_t: float
    br_y_t: float


def _signed_segment_angle(
    constant_distance: float,
    start_offset: float,
    end_offset: float,
) -> float:
    """Return the signed angle subtended by a straight source segment."""

    return math.atan2(
        constant_distance * (end_offset - start_offset),
        constant_distance**2 + start_offset * end_offset,
    )


def _rectangle_field_t(
    magnet: _RectangleMagnet,
    *,
    x_mm: float,
    y_mm: float,
) -> tuple[float, float]:
    """Return the exact external 2D B field of one ``mu_r = 1`` rectangle.

    For uniform magnetization, the bound surface charge is
    ``sigma_m = M dot n``.  Integrating the 2D line-charge kernel
    ``(r-r') / (2*pi*|r-r'|^2)`` over each rectangle face produces one signed
    angle and one logarithmic term.  Using ``B_r = mu_0 M`` lets the
    remanence components enter these expressions directly in tesla.

    Evaluation on a magnet face or corner is intentionally unsupported; the
    production accuracy gates sample only air points.
    """

    if (
        magnet.x_min_mm <= x_mm <= magnet.x_max_mm
        and magnet.y_min_mm <= y_mm <= magnet.y_max_mm
    ):
        raise ValueError("the independent rectangle oracle samples air only")

    bx_t = 0.0
    by_t = 0.0

    # Vertical faces: sigma_m * mu_0 is -Br_x on the left and +Br_x on
    # the right.
    for x_face_mm, sigma_br_t in (
        (magnet.x_min_mm, -magnet.br_x_t),
        (magnet.x_max_mm, magnet.br_x_t),
    ):
        dx = x_mm - x_face_mm
        bottom = magnet.y_min_mm - y_mm
        top = magnet.y_max_mm - y_mm
        bottom_r2 = dx * dx + (y_mm - magnet.y_min_mm) ** 2
        top_r2 = dx * dx + (y_mm - magnet.y_max_mm) ** 2
        bx_t += sigma_br_t / (2.0 * math.pi) * _signed_segment_angle(
            dx,
            bottom,
            top,
        )
        by_t += sigma_br_t / (4.0 * math.pi) * math.log(
            bottom_r2 / top_r2
        )

    # Horizontal faces: sigma_m * mu_0 is -Br_y on the bottom and +Br_y
    # on the top.
    for y_face_mm, sigma_br_t in (
        (magnet.y_min_mm, -magnet.br_y_t),
        (magnet.y_max_mm, magnet.br_y_t),
    ):
        dy = y_mm - y_face_mm
        left = magnet.x_min_mm - x_mm
        right = magnet.x_max_mm - x_mm
        left_r2 = (x_mm - magnet.x_min_mm) ** 2 + dy * dy
        right_r2 = (x_mm - magnet.x_max_mm) ** 2 + dy * dy
        bx_t += sigma_br_t / (4.0 * math.pi) * math.log(
            left_r2 / right_r2
        )
        by_t += sigma_br_t / (2.0 * math.pi) * _signed_segment_angle(
            dy,
            left,
            right,
        )

    return bx_t, by_t


def _array_field_t(
    magnets: list[_RectangleMagnet],
    *,
    x_mm: float,
    y_mm: float,
) -> tuple[float, float]:
    bx_t = 0.0
    by_t = 0.0
    for magnet in magnets:
        magnet_bx_t, magnet_by_t = _rectangle_field_t(
            magnet,
            x_mm=x_mm,
            y_mm=y_mm,
        )
        bx_t += magnet_bx_t
        by_t += magnet_by_t
    return bx_t, by_t


def _config(
    *,
    period_count: int = 9,
    block_width_mm: float = 10.0,
    magnet_height_mm: float = 10.0,
    block_gap_mm: float = 0.0,
    strong_side: str = "positive_y",
    phase_deg: float = 0.0,
) -> LinearHalbachArrayConfig:
    config = canonical_linear_halbach_config().model_copy(deep=True)
    config.geometry.period_count = period_count
    config.geometry.block_width = block_width_mm
    config.geometry.magnet_height = magnet_height_mm
    config.geometry.block_gap = block_gap_mm
    config.array.strong_side = strong_side
    config.array.phase_deg = phase_deg
    return config


def _oracle_magnets_from_angles(
    config: LinearHalbachArrayConfig,
    *,
    remanence_t: float,
    angles_deg: list[float],
) -> list[_RectangleMagnet]:
    geometry = config.geometry
    block_count = 4 * geometry.period_count
    assert len(angles_deg) == block_count
    active_length_mm = (
        block_count * geometry.block_width
        + (block_count - 1) * geometry.block_gap
    )
    first_x_mm = -0.5 * active_length_mm
    half_height_mm = 0.5 * geometry.magnet_height
    magnets: list[_RectangleMagnet] = []
    for index, angle_deg in enumerate(angles_deg):
        x_min_mm = first_x_mm + index * (
            geometry.block_width + geometry.block_gap
        )
        angle_rad = math.radians(angle_deg)
        magnets.append(
            _RectangleMagnet(
                x_min_mm=x_min_mm,
                x_max_mm=x_min_mm + geometry.block_width,
                y_min_mm=-half_height_mm,
                y_max_mm=half_height_mm,
                br_x_t=remanence_t * math.cos(angle_rad),
                br_y_t=remanence_t * math.sin(angle_rad),
            )
        )
    return magnets


def _public_source_angles(
    config: LinearHalbachArrayConfig,
) -> list[float]:
    return [
        block_magnetization_angle_deg(config, index)
        for index in range(4 * config.geometry.period_count)
    ]


def _probe_points(
    config: LinearHalbachArrayConfig,
    *,
    y_mm: float,
    samples: int = 64,
) -> list[tuple[float, float]]:
    wavelength_mm = 4.0 * (
        config.geometry.block_width + config.geometry.block_gap
    )
    return [
        (
            -0.5 * wavelength_mm
            + wavelength_mm * (index + 0.5) / samples,
            y_mm,
        )
        for index in range(samples)
    ]


def _rms_magnitude(
    magnets: list[_RectangleMagnet],
    points: list[tuple[float, float]],
) -> float:
    squared = []
    for x_mm, y_mm in points:
        bx_t, by_t = _array_field_t(magnets, x_mm=x_mm, y_mm=y_mm)
        squared.append(bx_t * bx_t + by_t * by_t)
    return math.sqrt(sum(squared) / len(squared))


def _fundamental_amplitude_t(
    magnets: list[_RectangleMagnet],
    *,
    wavelength_mm: float,
    y_mm: float,
    samples: int = 128,
) -> float:
    """Extract the rotating spatial fundamental from one centered period."""

    coefficient = 0.0j
    wave_number_per_mm = 2.0 * math.pi / wavelength_mm
    for index in range(samples):
        x_mm = (
            -0.5 * wavelength_mm
            + wavelength_mm * (index + 0.5) / samples
        )
        bx_t, by_t = _array_field_t(magnets, x_mm=x_mm, y_mm=y_mm)
        rotating_field = complex(bx_t, by_t)
        coefficient += rotating_field * cmath.exp(
            1j * wave_number_per_mm * x_mm
        )
    return abs(coefficient / samples)


def _continuous_segmented_amplitude_t(
    *,
    remanence_t: float,
    wavelength_mm: float,
    magnet_height_mm: float,
    surface_offset_mm: float,
) -> float:
    wave_number_per_mm = 2.0 * math.pi / wavelength_mm
    four_block_factor = math.sin(math.pi / 4.0) / (math.pi / 4.0)
    return (
        remanence_t
        * (1.0 - math.exp(-wave_number_per_mm * magnet_height_mm))
        * math.exp(-wave_number_per_mm * surface_offset_mm)
        * four_block_factor
    )


@pytest.mark.parametrize(
    ("strong_side", "step_deg"),
    [("positive_y", 90.0), ("negative_y", -90.0)],
)
def test_four_block_phase_and_left_to_right_handedness_are_frozen(
    strong_side: str,
    step_deg: float,
) -> None:
    phase_deg = 17.0
    config = _config(
        period_count=2,
        strong_side=strong_side,
        phase_deg=phase_deg,
    )
    angles = _public_source_angles(config)
    assert angles == pytest.approx(
        [(phase_deg + step_deg * index) % 360.0 for index in range(8)],
        abs=1.0e-12,
    )
    assert [
        (angles[index + 1] - angles[index]) % 360.0
        for index in range(7)
    ] == pytest.approx(
        [step_deg % 360.0] * 7,
        abs=1.0e-12,
    )


@pytest.mark.parametrize("strong_side", ["positive_y", "negative_y"])
def test_independent_oracle_confirms_selected_side_is_strong(
    strong_side: str,
) -> None:
    config = _config(period_count=9, strong_side=strong_side)
    magnets = _oracle_magnets_from_angles(
        config,
        remanence_t=1.3,
        angles_deg=_public_source_angles(config),
    )
    face_y_mm = 0.5 * config.geometry.magnet_height
    offset_mm = config.geometry.block_width
    positive_points = _probe_points(
        config,
        y_mm=face_y_mm + offset_mm,
    )
    negative_points = _probe_points(
        config,
        y_mm=-face_y_mm - offset_mm,
    )
    positive_rms = _rms_magnitude(magnets, positive_points)
    negative_rms = _rms_magnitude(magnets, negative_points)
    strong_rms, weak_rms = (
        (positive_rms, negative_rms)
        if strong_side == "positive_y"
        else (negative_rms, positive_rms)
    )

    assert strong_rms > 0.0
    assert weak_rms > 0.0
    assert strong_rms / weak_rms >= 20.0


@pytest.mark.parametrize("surface_offset_mm", [5.0, 10.0, 20.0])
def test_rectangle_superposition_reaches_continuous_four_block_limit(
    surface_offset_mm: float,
) -> None:
    config = _config(
        period_count=15,
        block_width_mm=10.0,
        magnet_height_mm=10.0,
        block_gap_mm=0.0,
        strong_side="positive_y",
    )
    remanence_t = 1.3
    magnets = _oracle_magnets_from_angles(
        config,
        remanence_t=remanence_t,
        angles_deg=[
            (90.0 * index) % 360.0
            for index in range(4 * config.geometry.period_count)
        ],
    )
    wavelength_mm = 4.0 * config.geometry.block_width
    solved_amplitude = _fundamental_amplitude_t(
        magnets,
        wavelength_mm=wavelength_mm,
        y_mm=0.5 * config.geometry.magnet_height + surface_offset_mm,
    )
    expected_amplitude = _continuous_segmented_amplitude_t(
        remanence_t=remanence_t,
        wavelength_mm=wavelength_mm,
        magnet_height_mm=config.geometry.magnet_height,
        surface_offset_mm=surface_offset_mm,
    )

    assert solved_amplitude == pytest.approx(expected_amplitude, rel=5.0e-3)


def test_public_geometry_source_vectors_scale_linearly_with_remanence() -> None:
    config = _config(period_count=3, phase_deg=11.0)
    low_br_t = 0.65
    high_br_t = 1.30
    low = build_linear_planar_geometry(
        config,
        remanence_t=low_br_t,
        material_key="independent_oracle_material",
    )
    high = build_linear_planar_geometry(
        config,
        remanence_t=high_br_t,
        material_key="independent_oracle_material",
    )
    low_sources = [
        region.magnetization_xy
        for region in low.regions
        if region.kind == "permanent_magnet"
    ]
    high_sources = [
        region.magnetization_xy
        for region in high.regions
        if region.kind == "permanent_magnet"
    ]

    assert len(low_sources) == len(high_sources) == 12
    for low_source, high_source in zip(low_sources, high_sources):
        assert low_source is not None
        assert high_source is not None
        assert math.hypot(*low_source) == pytest.approx(low_br_t, abs=1.0e-12)
        assert math.hypot(*high_source) == pytest.approx(high_br_t, abs=1.0e-12)
        assert high_source == pytest.approx(
            (2.0 * low_source[0], 2.0 * low_source[1]),
            abs=1.0e-12,
        )


def test_remanence_scaling_is_exact_in_independent_field_oracle() -> None:
    config = _config(period_count=7, phase_deg=23.0)
    angles = _public_source_angles(config)
    low = _oracle_magnets_from_angles(
        config,
        remanence_t=0.7,
        angles_deg=angles,
    )
    high = _oracle_magnets_from_angles(
        config,
        remanence_t=1.4,
        angles_deg=angles,
    )
    face_y_mm = 0.5 * config.geometry.magnet_height
    for x_mm, y_mm in (
        (-13.0, face_y_mm + 4.0),
        (0.0, face_y_mm + 9.0),
        (17.0, -face_y_mm - 11.0),
    ):
        low_field = _array_field_t(low, x_mm=x_mm, y_mm=y_mm)
        high_field = _array_field_t(high, x_mm=x_mm, y_mm=y_mm)
        assert high_field == pytest.approx(
            (2.0 * low_field[0], 2.0 * low_field[1]),
            abs=1.0e-12,
        )


def test_adding_180_degree_phase_negates_field_and_preserves_magnitude() -> None:
    base = _config(period_count=7, strong_side="positive_y", phase_deg=13.0)
    reversed_phase = _config(
        period_count=7,
        strong_side="positive_y",
        phase_deg=193.0,
    )
    base_angles = _public_source_angles(base)
    reversed_angles = _public_source_angles(reversed_phase)
    assert [
        (reversed_angle - base_angle) % 360.0
        for base_angle, reversed_angle in zip(base_angles, reversed_angles)
    ] == pytest.approx([180.0] * len(base_angles), abs=1.0e-12)

    base_magnets = _oracle_magnets_from_angles(
        base,
        remanence_t=1.3,
        angles_deg=base_angles,
    )
    reversed_magnets = _oracle_magnets_from_angles(
        reversed_phase,
        remanence_t=1.3,
        angles_deg=reversed_angles,
    )
    face_y_mm = 0.5 * base.geometry.magnet_height
    for x_mm, y_mm in (
        (-15.0, face_y_mm + 5.0),
        (0.0, face_y_mm + 10.0),
        (15.0, -face_y_mm - 8.0),
    ):
        base_field = _array_field_t(
            base_magnets,
            x_mm=x_mm,
            y_mm=y_mm,
        )
        reversed_field = _array_field_t(
            reversed_magnets,
            x_mm=x_mm,
            y_mm=y_mm,
        )
        assert reversed_field == pytest.approx(
            (-base_field[0], -base_field[1]),
            abs=1.0e-12,
        )
        assert math.hypot(*reversed_field) == pytest.approx(
            math.hypot(*base_field),
            abs=1.0e-12,
        )
