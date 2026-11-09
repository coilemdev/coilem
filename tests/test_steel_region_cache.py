"""Region classification reuse preserves steel RMS arithmetic and input semantics."""

from __future__ import annotations

import copy
import math
from collections import Counter
from typing import Any

import pytest

from backend import steel_flux_metrics as metrics

pytestmark = pytest.mark.pr


def _frame(regions: list[Any]) -> dict[str, Any]:
    return {
        "nodes_mm": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        "triangles": [[0, 1, 2] for _ in regions],
        "regions": regions,
        "element_b_mag_t": [1.0 for _ in regions],
    }


def _uncached_update(accumulator: metrics.SteelFluxDensityAccumulator, frame: dict[str, Any]) -> None:
    """The original per-triangle arithmetic, without classification reuse.

    These complete in-memory frames exercise the numerical loop rather than
    artifact loading. Keep the original operation and accumulation order so
    exact equality also detects changes hidden by a tolerance comparison.
    """

    nodes = frame["nodes_mm"]
    triangles = frame["triangles"]
    regions = frame["regions"]
    b_mag = frame.get("element_b_mag_t", [])
    b_x = frame.get("element_bx_t", [])
    b_y = frame.get("element_by_t", [])
    has_mag = len(b_mag) == len(triangles)
    has_xy = len(b_x) == len(triangles) and len(b_y) == len(triangles)
    for index, triangle in enumerate(triangles):
        bucket = metrics._steel_region_bucket(regions[index])
        if bucket is None:
            continue
        area_mm2 = metrics._triangle_area_mm2(nodes, triangle)
        if area_mm2 is None:
            continue
        field_t = metrics._finite_float(b_mag[index]) if has_mag else None
        if field_t is None and has_xy:
            bx_t = metrics._finite_float(b_x[index])
            by_t = metrics._finite_float(b_y[index])
            if bx_t is not None and by_t is not None:
                field_t = math.hypot(bx_t, by_t)
        if field_t is None or field_t < 0:
            continue
        accumulator[bucket]["area_mm2"] += area_mm2
        accumulator[bucket]["weighted_b2_t2_mm2"] += area_mm2 * field_t * field_t


def _record_classification_calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    classify = metrics._steel_region_bucket

    def recording_classify(value: Any) -> metrics.SteelRegionBucket | None:
        calls.append(value)
        return classify(value)

    monkeypatch.setattr(metrics, "_steel_region_bucket", recording_classify)
    return calls


@pytest.mark.parametrize("field_mode", ["magnitude", "components", "mixed"])
def test_reuse_matches_uncached_accumulator_and_rms_exactly(field_mode: str) -> None:
    regions = ["statorTooth", " Stator - BackIron ", "air", "TEETH", "stator_yoke", "", "statorTooth", "air"] * 12
    triangles = [[0, 1, 2], [1, 3, 2], [0, 0, 1], [0, 1, 3], [0, 2, 3], [0, 1, 99], [0, 1, 2.5], (0, 1, 2)] * 12
    magnitude_values = [1e8, 1e-8, 0.0, True, -1.0, math.nan, math.inf, "2.0", 1.7, None, 3.1, 0.125]
    bx_values = [0.3, 1e-9, 0.0, 0.8, -0.4, 2.2, math.nan, True, 1.3, 0.0, 0.9, 1e7]
    by_values = [0.4, 2e-9, 0.0, 0.6, 0.3, 0.5, 0.7, 0.1, math.inf, 1.2, 0.0, 1e7]
    initial = {
        "teeth": {"area_mm2": 0.125, "weighted_b2_t2_mm2": 1e-20},
        "yoke": {"area_mm2": 0.375, "weighted_b2_t2_mm2": 0.1},
    }
    expected = copy.deepcopy(initial)
    actual = copy.deepcopy(initial)
    for offset in range(3):
        frame = {
            "nodes_mm": [[0.1, 0.2], [1.7, 0.0], [0.0, 2.3], [2.4, 1.2]],
            "triangles": triangles,
            "regions": regions,
        }
        if field_mode != "components":
            frame["element_b_mag_t"] = [magnitude_values[(index + offset) % len(magnitude_values)] for index in range(len(regions))]
        if field_mode != "magnitude":
            frame["element_bx_t"] = [bx_values[(index + offset) % len(bx_values)] for index in range(len(regions))]
            frame["element_by_t"] = [by_values[(index + offset) % len(by_values)] for index in range(len(regions))]

        _uncached_update(expected, frame)
        metrics.update_steel_flux_density_rms_accumulator(actual, frame)

        assert actual == expected
        assert metrics.finalize_steel_flux_density_rms(actual) == metrics.finalize_steel_flux_density_rms(expected)
    assert all(actual[bucket]["area_mm2"] > initial[bucket]["area_mm2"] for bucket in ("teeth", "yoke"))


def test_repeated_positive_and_negative_strings_are_classified_once(monkeypatch: pytest.MonkeyPatch) -> None:
    labels = ["stator_tooth", "stator_yoke", "air", "", "unknown steel"]
    # Equal labels need not be the same Python string object.
    regions = [label.encode().decode() for _ in range(20) for label in labels]
    calls = _record_classification_calls(monkeypatch)
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    metrics.update_steel_flux_density_rms_accumulator(accumulator, _frame(regions))

    assert calls == labels
    assert accumulator == {
        "teeth": {"area_mm2": 10.0, "weighted_b2_t2_mm2": 10.0},
        "yoke": {"area_mm2": 10.0, "weighted_b2_t2_mm2": 10.0},
    }


def test_raw_variants_keep_normalization_and_distinct_cache_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    teeth = ["stator_tooth", "StatorTooth", "stator tooth", " STATOR-TOOTH ", "stator___tooth", "statorTeeth", "tooth", "TEETH"]
    yoke = ["statorYoke", " Stator - BackIron ", "backIron", "BACK IRON", "stator_back_iron", "YOKE"]
    other = ["rotor_steel", "stator_tooth_extra", "statorTooth2", "stator__yoke__", "", " \t "]
    labels = teeth + yoke + other
    calls = _record_classification_calls(monkeypatch)
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    metrics.update_steel_flux_density_rms_accumulator(accumulator, _frame(labels + labels[::-1]))

    assert calls == labels
    assert accumulator == {
        "teeth": {"area_mm2": float(len(teeth)), "weighted_b2_t2_mm2": float(len(teeth))},
        "yoke": {"area_mm2": float(len(yoke)), "weighted_b2_t2_mm2": float(len(yoke))},
    }


def test_cache_admits_only_first_128_strings_and_keeps_early_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    first_labels = [f"unknown_{index}" for index in range(126)] + ["stator_tooth", ""]
    regions = first_labels + ["stator_yoke"] * 3 + ["late_unknown"] * 3 + first_labels[::-1] + ["stator_yoke"] * 2
    calls = _record_classification_calls(monkeypatch)
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    metrics.update_steel_flux_density_rms_accumulator(accumulator, _frame(regions))

    expected_calls = dict.fromkeys(first_labels, 1)
    expected_calls.update(stator_yoke=5, late_unknown=3)
    assert Counter(calls) == expected_calls
    assert accumulator == {
        "teeth": {"area_mm2": 1.0, "weighted_b2_t2_mm2": 1.0},
        "yoke": {"area_mm2": 2.5, "weighted_b2_t2_mm2": 2.5},
    }


def test_classification_cache_is_scoped_to_one_update(monkeypatch: pytest.MonkeyPatch) -> None:
    labels = ["stator_tooth", "stator_yoke", "air"]
    frame = _frame(labels * 5)
    calls = _record_classification_calls(monkeypatch)
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    metrics.update_steel_flux_density_rms_accumulator(accumulator, frame)
    metrics.update_steel_flux_density_rms_accumulator(accumulator, frame)

    assert calls == labels * 2
    assert accumulator == {
        "teeth": {"area_mm2": 5.0, "weighted_b2_t2_mm2": 5.0},
        "yoke": {"area_mm2": 5.0, "weighted_b2_t2_mm2": 5.0},
    }


class _StatefulLabel:
    __hash__ = None

    def __init__(self, steps: list[tuple[bool | Exception, str | Exception]]) -> None:
        self.steps = iter(steps)
        self.events: list[str] = []
        self.text: str | Exception = ""

    def __bool__(self) -> bool:
        self.events.append("bool")
        truth, self.text = next(self.steps)
        if isinstance(truth, Exception):
            raise truth
        return truth

    def __str__(self) -> str:
        self.events.append("str")
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


class _StatefulString(_StatefulLabel, str):
    def __new__(cls, steps: list[tuple[bool | Exception, str | Exception]]) -> _StatefulString:
        return str.__new__(cls, "stator_tooth")


@pytest.mark.parametrize("label_type", [_StatefulLabel, _StatefulString], ids=["nonstring", "string-subclass"])
def test_stateful_labels_keep_per_triangle_truth_and_string_conversion(label_type: type[_StatefulLabel], monkeypatch: pytest.MonkeyPatch) -> None:
    label = label_type([(True, "stator_tooth"), (False, "stator_tooth"), (True, "stator_yoke"), (True, "air")])
    frame = _frame([label] * 4)
    frame["element_b_mag_t"] = [1.0, 2.0, 3.0, 4.0]
    calls = _record_classification_calls(monkeypatch)
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    metrics.update_steel_flux_density_rms_accumulator(accumulator, frame)

    assert len(calls) == 4 and all(value is label for value in calls)
    assert label.events == ["bool", "str", "bool", "bool", "str", "bool", "str"]
    assert accumulator == {
        "teeth": {"area_mm2": 0.5, "weighted_b2_t2_mm2": 0.5},
        "yoke": {"area_mm2": 0.5, "weighted_b2_t2_mm2": 4.5},
    }
    assert metrics.finalize_steel_flux_density_rms(accumulator) == {"teeth": 1.0, "yoke": 3.0}


def test_unhashable_and_false_nonstring_labels_keep_original_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    labels = [["stator_tooth"], {"region": "stator_yoke"}, [], {}, None, False, 0, 0.0, True, 7]
    calls = _record_classification_calls(monkeypatch)
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    metrics.update_steel_flux_density_rms_accumulator(accumulator, _frame(labels * 2))

    assert len(calls) == len(labels) * 2
    assert all(actual is expected for actual, expected in zip(calls, labels * 2))
    assert accumulator == metrics.new_steel_flux_density_rms_accumulator()


@pytest.mark.parametrize("label_type", [_StatefulLabel, _StatefulString], ids=["nonstring", "string-subclass"])
@pytest.mark.parametrize("failure", ["bool", "str"])
def test_normalization_errors_still_propagate_after_prior_contribution(label_type: type[_StatefulLabel], failure: str) -> None:
    error = ValueError("normalization failed")
    second_step = (error, "stator_yoke") if failure == "bool" else (True, error)
    label = label_type([(True, "stator_tooth"), second_step])
    accumulator = metrics.new_steel_flux_density_rms_accumulator()

    with pytest.raises(ValueError, match="normalization failed") as raised:
        metrics.update_steel_flux_density_rms_accumulator(accumulator, _frame([label, label]))

    assert raised.value is error
    assert label.events == ["bool", "str", "bool"] + (["str"] if failure == "str" else [])
    assert accumulator == {
        "teeth": {"area_mm2": 0.5, "weighted_b2_t2_mm2": 0.5},
        "yoke": {"area_mm2": 0.0, "weighted_b2_t2_mm2": 0.0},
    }
