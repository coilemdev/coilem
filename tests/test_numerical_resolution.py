"""Observed numerical controls never replace a benchmark's original verdict."""

from copy import deepcopy

import pytest

from backend.benchmark_suite.numerical_resolution import scalar_resolution

pytestmark = pytest.mark.pr

CONTEXT = {
    "case_id": "lrk-zero-current",
    "candidate_model_id": "candidate-ir",
    "reference_model_id": "original-femm",
    "quantity_id": "rotor_torque",
    "convention": "public-clockwise-v2",
}


def study(*, side="reference", baseline=.0649, values=(.01,), kind="orientation", **updates):
    return {
        "id": "controlled-study",
        "side": side,
        "case_id": CONTEXT["case_id"],
        "model_id": CONTEXT.get(f"{side}_model_id", "invalid-side-model"),
        "quantity_id": CONTEXT["quantity_id"],
        "unit": "mN m",
        "convention": CONTEXT["convention"],
        "baseline": baseline,
        "values": list(values) if isinstance(values, tuple) else values,
        "kind": kind,
        "physical_equivalence_verified": True,
        **updates,
    }


def test_no_controls_reports_difference_without_uncertainty_claim_or_grade():
    result = scalar_resolution(11, 10, unit="N m")
    assert result["signed_delta"] == result["abs_delta"] == 1
    assert result["relative_delta_pct"] == 10
    assert result["relative_meaningful"]
    assert result["noise_sensitivity"] == "NO_CONTROL_EVIDENCE"
    assert result["uncertainty_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["observed_variation_abs"] is None
    assert result["observed_variation_by_side"] == {"candidate": None, "reference": None}
    assert not ({"status", "grade", "pass", "fail", "confidence", "uncertainty_bound"} & result.keys())


@pytest.mark.parametrize(("reference", "floor"), [(0, 0), (.0001, .01), (-.01, .01), (.01, .01)])
def test_relative_error_is_suppressed_at_or_below_floor(reference, floor):
    result = scalar_resolution(.02, reference, unit="N m", relative_floor_abs=floor)
    assert result["abs_delta"] == pytest.approx(abs(.02 - reference))
    assert result["reference_near_zero"]
    assert not result["relative_meaningful"]
    assert result["relative_delta_pct"] is None
    assert "REFERENCE_AT_OR_BELOW_RELATIVE_FLOOR" in result["relative_suppression_reasons"]


def test_one_sided_lrk_orientation_context_does_not_become_candidate_bound():
    evidence = study(values=(-.1306,))
    original = deepcopy(evidence)
    result = scalar_resolution(.01330316676225945, .0649, unit="mN m", context=CONTEXT, studies=[evidence])
    assert result["noise_sensitivity"] == "DIFFERENCE_WITHIN_OBSERVED_VARIATION"
    assert result["abs_delta"] == pytest.approx(.05159683323774055)
    assert result["evidence_sides"] == ["reference"]
    assert result["observed_variation_by_side"]["candidate"] is None
    assert result["observed_variation_abs"] == pytest.approx(.1955)
    assert result["relative_delta_pct"] is None
    assert result["relative_suppression_reasons"] == ["REFERENCE_VARIATION_INCLUDES_ZERO"]
    assert result["uncertainty_status"] == "INSUFFICIENT_EVIDENCE"
    assert evidence == original


def test_small_observed_pair_is_not_an_uncertainty_estimate():
    result = scalar_resolution(.5, 1, unit="mN m", context=CONTEXT,
                               studies=[study(baseline=1, values=(.9,), kind="mesh")])
    assert result["noise_sensitivity"] == "DIFFERENCE_EXCEEDS_OBSERVED_VARIATION"
    assert result["observed_variation_abs"] == pytest.approx(.1)
    assert result["uncertainty_status"] == "INSUFFICIENT_EVIDENCE"


def test_controls_moving_away_do_not_create_a_symmetric_unobserved_range():
    result = scalar_resolution(2, 1, unit="mN m", context=CONTEXT,
                               studies=[study(baseline=1, values=(0,))])
    assert result["abs_delta"] == result["observed_variation_abs"] == 1
    assert result["noise_sensitivity"] == "DIFFERENCE_EXCEEDS_OBSERVED_VARIATION"


def test_two_sided_observations_keep_side_provenance_and_actual_range_overlap():
    result = scalar_resolution(2, 1, unit="mN m", context=CONTEXT, studies=[
        study(side="candidate", baseline=2, values=(1.4,), kind="mesh"),
        study(baseline=1, values=(1.5,), kind="mesh"),
    ])
    assert result["evidence_sides"] == ["candidate", "reference"]
    assert result["observed_variation_abs"] == pytest.approx(.6)
    assert result["noise_sensitivity"] == "DIFFERENCE_WITHIN_OBSERVED_VARIATION"
    assert [entry["side"] for entry in result["observed_studies"]] == ["candidate", "reference"]


@pytest.mark.parametrize(("candidate", "expected"), [(0, "DIFFERENCE_WITHIN_OBSERVED_VARIATION"), (1, "DIFFERENCE_EXCEEDS_OBSERVED_VARIATION")])
def test_identical_zero_repeats_report_zero_observed_change_only(candidate, expected):
    result = scalar_resolution(candidate, 0, unit="mN m", context=CONTEXT,
                               studies=[study(baseline=0, values=(0, 0), kind="repeat")])
    assert result["observed_variation_abs"] == 0
    assert result["noise_sensitivity"] == expected
    assert result["uncertainty_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["relative_delta_pct"] is None


def test_opposite_signs_remain_explicit_even_if_reference_variation_crosses_zero():
    result = scalar_resolution(-.01, .01, unit="mN m", context=CONTEXT,
                               studies=[study(baseline=.01, values=(-.02,))])
    assert result["opposite_signs"]
    assert result["signed_delta"] == -.02
    assert result["abs_delta"] == .02
    assert result["noise_sensitivity"] == "DIFFERENCE_WITHIN_OBSERVED_VARIATION"
    assert not result["relative_meaningful"]
    assert result["uncertainty_status"] == "INSUFFICIENT_EVIDENCE"


def test_stable_opposite_signs_and_large_difference_are_not_hidden():
    result = scalar_resolution(-1000, 1000, unit="mN m", context=CONTEXT,
                               studies=[study(baseline=1000, values=(999, 1001))])
    assert result["opposite_signs"]
    assert result["abs_delta"] == 2000
    assert result["relative_delta_pct"] == 200
    assert result["noise_sensitivity"] == "DIFFERENCE_EXCEEDS_OBSERVED_VARIATION"


@pytest.mark.parametrize("bad", [True, False, None, "1", float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("side", ["candidate", "reference"])
def test_invalid_comparison_values_are_rejected(bad, side):
    arguments = {"candidate": 1, "reference": 1, side: bad}
    with pytest.raises(ValueError):
        scalar_resolution(**arguments, unit="N m")


@pytest.mark.parametrize("unit", ["", " ", None, True])
def test_unit_must_be_explicit_nonempty_text(unit):
    with pytest.raises(ValueError):
        scalar_resolution(1, 1, unit=unit)


@pytest.mark.parametrize("floor", [-1, True, float("nan"), float("inf"), "0"])
def test_invalid_relative_floor_is_rejected(floor):
    with pytest.raises(ValueError):
        scalar_resolution(1, 1, unit="N m", relative_floor_abs=floor)


@pytest.mark.parametrize(("field", "value"), [
    ("unit", "N m"), ("model_id", "candidate-ir"), ("case_id", "other-case"),
    ("quantity_id", "stator_torque"), ("convention", "native-ccw"), ("baseline", .065),
    ("physical_equivalence_verified", False), ("physical_equivalence_verified", 1),
    ("side", "both"), ("kind", "calibration"), ("kind", []), ("kind", {}), ("id", ""),
])
def test_inapplicable_or_malformed_study_is_rejected_explicitly(field, value):
    with pytest.raises(ValueError):
        scalar_resolution(.0133, .0649, unit="mN m", context=CONTEXT,
                          studies=[study(**{field: value})])


@pytest.mark.parametrize("values", [[], "0.1", [True], [float("nan")], [float("inf")], [None]])
def test_study_values_must_be_nonempty_and_finite(values):
    with pytest.raises(ValueError):
        scalar_resolution(.0133, .0649, unit="mN m", context=CONTEXT, studies=[study(values=values)])


@pytest.mark.parametrize("context", [None, {}, {**CONTEXT, "candidate_model_id": ""}])
def test_controls_require_complete_context(context):
    with pytest.raises(ValueError):
        scalar_resolution(.0133, .0649, unit="mN m", context=context, studies=[study()])


@pytest.mark.parametrize("studies", [None, "study", {"id": "study"}, [None]])
def test_malformed_study_collection_is_rejected(studies):
    with pytest.raises(ValueError):
        scalar_resolution(1, 1, unit="N m", context=CONTEXT, studies=studies)


def test_relative_overflow_is_unavailable_rather_than_nonfinite_json():
    result = scalar_resolution(1e100, 1e-300, unit="N m")
    assert result["relative_delta_pct"] is None
    assert not result["relative_meaningful"]
    assert result["relative_suppression_reasons"] == ["RELATIVE_DELTA_NOT_REPRESENTABLE"]


def test_unrepresentable_absolute_difference_is_rejected():
    with pytest.raises(ValueError):
        scalar_resolution(1e308, -1e308, unit="N m")
