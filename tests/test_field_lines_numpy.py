"""The numpy field-line paths give bit-identical results to the per-triangle Python paths."""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
import pytest

from backend import field_lines
from backend.field_lines import (
    _contour_levels_python,
    _contour_segments_python,
    _element_b_components_python,
    _element_b_magnitudes_python,
    _field_line_plot_fields,
    _weighted_quantile_levels,
    _weighted_quantile_levels_array,
    generate_contour_levels,
    generate_contour_segments,
    generate_element_b_components,
    generate_element_b_magnitudes,
)


def _assert_same(actual: Any, expected: Any) -> None:
    """Compare reprs, which tell -0.0 from 0.0 and show every bit of each float."""

    actual_text, expected_text = repr(actual), repr(expected)
    if actual_text == expected_text:
        return
    # Report a short window: pytest's own diff of these long strings takes minutes.
    at = next(
        (index for index, (a, b) in enumerate(zip(actual_text, expected_text)) if a != b),
        min(len(actual_text), len(expected_text)),
    )
    window = slice(max(0, at - 80), at + 80)
    pytest.fail(f"differs at character {at}:\n  actual   {actual_text[window]}\n  expected {expected_text[window]}")


def _grid_mesh(size: int, *, jitter: float, seed: int) -> tuple[list[list[float]], list[list[int]]]:
    rng = random.Random(seed)
    nodes = [
        [x + rng.uniform(-jitter, jitter), y + rng.uniform(-jitter, jitter)]
        for y in range(size)
        for x in range(size)
    ]
    triangles = []
    for y in range(size - 1):
        for x in range(size - 1):
            a, b, c, d = y * size + x, y * size + x + 1, (y + 1) * size + x, (y + 1) * size + x + 1
            triangles += [[a, b, c], [b, d, c]]
    return nodes, triangles


def _python_fields(nodes, triangles, az):
    levels = _contour_levels_python(az, nodes_mm=nodes, triangles=triangles)
    return (
        _element_b_magnitudes_python(nodes, triangles, az),
        *_element_b_components_python(nodes, triangles, az),
        _contour_segments_python(nodes, triangles, az, levels) if levels else [],
    )


def _assert_same_fields(nodes, triangles, az) -> None:
    """Every public generator and the combined plot helper match the Python paths."""

    expected_levels = _contour_levels_python(az, nodes_mm=nodes, triangles=triangles)
    _assert_same(generate_contour_levels(az, nodes_mm=nodes, triangles=triangles), expected_levels)
    _assert_same(generate_contour_levels(az), _contour_levels_python(az))
    _assert_same(
        generate_element_b_components(nodes, triangles, az),
        _element_b_components_python(nodes, triangles, az),
    )
    _assert_same(
        generate_element_b_magnitudes(nodes, triangles, az),
        _element_b_magnitudes_python(nodes, triangles, az),
    )
    _assert_same(
        generate_contour_segments(nodes, triangles, az, expected_levels),
        _contour_segments_python(nodes, triangles, az, expected_levels),
    )
    _assert_same(_field_line_plot_fields(nodes, triangles, az), _python_fields(nodes, triangles, az))


def test_smooth_field_matches_python() -> None:
    nodes, triangles = _grid_mesh(40, jitter=0.3, seed=1)
    az = [0.02 * math.sin(0.3 * x) * math.cos(0.2 * y) + 1e-4 * x for x, y in nodes]

    assert field_lines._mesh_arrays(nodes, triangles, az) is not None
    _assert_same_fields(nodes, triangles, az)
    contours = generate_contour_segments(nodes, triangles, az, generate_contour_levels(az))
    assert sum(len(level.segments_mm) for level in contours) > 100
    # A non-finite level keeps the Python path even on an exact mesh.
    _assert_same(
        generate_contour_segments(nodes, triangles, az, [math.nan, 0.0]),
        _contour_segments_python(nodes, triangles, az, [math.nan, 0.0]),
    )


def test_vertices_on_levels_match_python() -> None:
    """Quantised values put vertices exactly on levels, so the touching-triangle path runs."""

    nodes, triangles = _grid_mesh(16, jitter=0.0, seed=2)
    rng = random.Random(3)
    az = [round(rng.uniform(-1.0, 1.0), 1) for _ in nodes]
    levels = [-0.5, -0.2, 0.0, 0.1, 0.3, 0.7, 1.0, -1.0, 0.25]

    _assert_same(
        generate_contour_segments(nodes, triangles, az, levels),
        _contour_segments_python(nodes, triangles, az, levels),
    )
    _assert_same_fields(nodes, triangles, az)


def test_integer_inputs_match_python() -> None:
    nodes, triangles = _grid_mesh(10, jitter=0.0, seed=4)
    int_nodes = [[int(x), int(y)] for x, y in nodes]
    rng = random.Random(5)
    int_az = [rng.randint(-5, 5) for _ in nodes]
    mixed_az = [value + 0.5 if index % 3 else value for index, value in enumerate(int_az)]

    _assert_same_fields(int_nodes, triangles, int_az)
    _assert_same_fields(int_nodes, triangles, mixed_az)
    _assert_same(
        generate_contour_segments(int_nodes, triangles, int_az, [0, 1, -2]),
        _contour_segments_python(int_nodes, triangles, int_az, [0, 1, -2]),
    )


def test_degenerate_and_tiny_triangles_match_python() -> None:
    """Zero-area triangles zero B; sub-1e-7 mm triangles collapse their two crossings to one point."""

    nodes, triangles = _grid_mesh(12, jitter=0.2, seed=6)
    count = len(nodes)
    nodes += [
        [3.0, 3.0], [3.0, 3.0],
        [5.0, 5.0], [6.0, 6.0], [7.0, 7.0],
        [2.0, 9.0], [2.0 + 3e-8, 9.0], [2.0, 9.0 + 3e-8],
    ]  # fmt: skip
    triangles += [[count, count + 1, 0], [count + 2, count + 3, count + 4], [count + 5, count + 6, count + 7]]
    az = [0.01 * x - 0.007 * y for x, y in nodes]
    az[count + 5], az[count + 6], az[count + 7] = -1.0, 1.0, 1.0

    _assert_same_fields(nodes, triangles, az)
    _assert_same(
        generate_contour_segments(nodes, triangles, az, [0.0, 0.5]),
        _contour_segments_python(nodes, triangles, az, [0.0, 0.5]),
    )


@pytest.mark.parametrize(
    "change",
    ["nan_value", "inf_node", "out_of_range", "negative_index", "float_index", "ragged", "huge_int", "string"],
)
def test_inputs_outside_the_exact_numpy_path_use_the_python_path(change: str) -> None:
    nodes, triangles = _grid_mesh(6, jitter=0.1, seed=7)
    az = [0.1 * x + 0.05 * y for x, y in nodes]
    if change == "nan_value":
        az[7] = math.nan
    elif change == "inf_node":
        nodes[8] = [math.inf, 1.0]
    elif change == "out_of_range":
        triangles[3] = [0, 1, len(nodes) + 4]
    elif change == "negative_index":
        triangles[3] = [0, 1, -1]
    elif change == "float_index":
        triangles[3] = [0, 1.0, 2]
    elif change == "ragged":
        triangles[3] = [0, 1, 2, 3]
    elif change == "huge_int":
        az[5] = 2**60
    elif change == "string":
        az[5] = "0.25"

    assert field_lines._mesh_arrays(nodes, triangles, az) is None
    for generate, python in (
        (generate_element_b_components, _element_b_components_python),
        (generate_element_b_magnitudes, _element_b_magnitudes_python),
    ):
        _assert_same(generate(nodes, triangles, az), python(nodes, triangles, az))
    for levels in ([0.1, 0.4], [math.nan, 0.2]):
        try:
            expected = _contour_segments_python(nodes, triangles, az, levels)
        except (IndexError, TypeError) as error:
            with pytest.raises(type(error)):
                generate_contour_segments(nodes, triangles, az, levels)
        else:
            _assert_same(generate_contour_segments(nodes, triangles, az, levels), expected)


def _assert_same_quantiles(values: list[float], weights: list[float], level_count: int, **quantiles: float) -> None:
    _assert_same(
        _weighted_quantile_levels_array(np.array(values), np.array(weights), level_count, **quantiles),
        _weighted_quantile_levels(list(zip(values, weights)), level_count, **quantiles),
    )


def test_weighted_quantiles_match_python_with_ties_and_wide_weights() -> None:
    rng = random.Random(8)
    for _ in range(50):
        size = rng.randint(1, 400)
        values = [round(rng.uniform(-1.0, 1.0), rng.choice((1, 2, 6))) for _ in range(size)]
        weights = [10.0 ** rng.uniform(-12.0, 3.0) for _ in range(size)]
        _assert_same_quantiles(values, weights, rng.randint(1, 20))


def test_weighted_quantile_targets_on_a_running_sum_match_python() -> None:
    """A target equal to a running sum stops the Python loop at that sample, not the next."""

    _assert_same_quantiles([float(index) for index in range(8)], [1.0] * 8, 3, low_quantile=0.0, high_quantile=1.0)


def test_weighted_quantile_total_keeps_the_builtin_sum() -> None:
    """Here numpy's pairwise sum gives a different total weight, which would move the median."""

    rng = random.Random(10246)
    size = rng.randint(9, 64)
    values = [float(rng.randint(-20, 20)) for _ in range(size)]
    weights = [rng.choice((1.0, 0.5, 3.0, 1e-3, 1e8, 0.1)) for _ in range(size)]
    _assert_same_quantiles(values, weights, 1, low_quantile=0.0, high_quantile=1.0)


def test_cumsum_is_the_sequential_running_sum() -> None:
    rng = random.Random(9)
    weights = [10.0 ** rng.uniform(-16.0, 8.0) for _ in range(5000)]
    running = 0.0
    expected = []
    for weight in weights:
        running += weight
        expected.append(running)
    assert np.cumsum(np.array(weights)).tolist() == expected
