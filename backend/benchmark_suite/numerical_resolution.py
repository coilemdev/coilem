"""Observed scalar numerical sensitivity, independent of benchmark verdicts.

Deterministic mesh/orientation/repeat controls describe only the variation
actually observed for the identified model and quantity. They do not establish
an uncertainty bound, convergence, statistical confidence, or validated noise.
This module never assigns or changes a PASS/FAIL benchmark grade.
"""

from collections.abc import Mapping, Sequence
from math import isfinite
from numbers import Real

_CONTEXT_KEYS = (
    "case_id",
    "candidate_model_id",
    "reference_model_id",
    "quantity_id",
    "convention",
)
_SIDES = ("candidate", "reference")
_KINDS = frozenset({"mesh", "orientation", "repeat"})


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number, excluding bool")
    try:
        value = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{label} must be a finite representable number") from error
    if not isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _context(context, *, required):
    if context is None:
        if required:
            raise ValueError("context is required when numerical studies are supplied")
        return None
    if not isinstance(context, Mapping):
        raise ValueError("context must be a mapping")
    return {key: _text(context.get(key), f"context.{key}") for key in _CONTEXT_KEYS}


def _study(study, index, context, unit, baselines):
    label = f"studies[{index}]"
    if not isinstance(study, Mapping):
        raise ValueError(f"{label} must be a mapping")
    study_id = _text(study.get("id"), f"{label}.id")
    side = study.get("side")
    if side not in _SIDES:
        raise ValueError(f"{label}.side must be candidate or reference")
    kind = study.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError(f"{label}.kind must be mesh, orientation, or repeat")
    if study.get("physical_equivalence_verified") is not True:
        raise ValueError(f"{label} must explicitly verify physical equivalence")
    expected = {
        "case_id": context["case_id"],
        "model_id": context[f"{side}_model_id"],
        "quantity_id": context["quantity_id"],
        "unit": unit,
        "convention": context["convention"],
    }
    for key, target in expected.items():
        value = _text(study.get(key), f"{label}.{key}")
        if value != target:
            raise ValueError(f"{label}.{key} does not match the comparison context")
    baseline = _number(study.get("baseline"), f"{label}.baseline")
    if baseline != baselines[side]:
        raise ValueError(f"{label}.baseline does not match the {side} value")
    raw_values = study.get("values")
    if isinstance(raw_values, (str, bytes, bytearray)) or not isinstance(raw_values, Sequence) or not raw_values:
        raise ValueError(f"{label}.values must be a nonempty numerical sequence")
    values = [_number(value, f"{label}.values[{i}]") for i, value in enumerate(raw_values)]
    minimum, maximum = min(baseline, *values), max(baseline, *values)
    max_excursion = max(abs(value - baseline) for value in values)
    if not isfinite(max_excursion):
        raise ValueError(f"{label} has an unrepresentable observed excursion")
    return {
        "id": study_id,
        "side": side,
        "kind": kind,
        **expected,
        "baseline": baseline,
        "values": values,
        "minimum": minimum,
        "maximum": maximum,
        "max_excursion_abs": max_excursion,
        "physical_equivalence_verified": True,
    }


def scalar_resolution(candidate, reference, *, unit, relative_floor_abs=0.0, context=None, studies=()):
    """Describe a scalar difference and applicable observed numerical studies.

    ``context`` identifies case, candidate/reference models, quantity, and sign/
    angle convention. Every supplied study must match that context, its unit,
    its side's exact baseline, and an explicitly verified physical equivalence.
    Malformed or mismatched evidence raises ValueError instead of being ignored.

    Study ranges include the baseline and all supplied control values. The
    sensitivity label says whether the actual observed side ranges overlap;
    without a study on one side, its nominal value is only the comparison point,
    never an estimated zero-uncertainty bound. ``observed_variation_abs`` is the
    largest available side's maximum observed excursion, provided as context.

    A pair or identical repeats can report an observed change, including zero.
    None of these simple controls estimates numerical uncertainty. Accordingly,
    ``uncertainty_status`` is always INSUFFICIENT_EVIDENCE, for every result.
    The caller's original benchmark grades and measurements remain untouched.
    """
    candidate = _number(candidate, "candidate")
    reference = _number(reference, "reference")
    unit = _text(unit, "unit")
    floor = _number(relative_floor_abs, "relative_floor_abs")
    if floor < 0:
        raise ValueError("relative_floor_abs must be nonnegative")
    if isinstance(studies, (str, bytes, bytearray, Mapping)):
        raise ValueError("studies must be an iterable of study mappings")
    try:
        raw_studies = list(studies)
    except TypeError as error:
        raise ValueError("studies must be an iterable of study mappings") from error
    context = _context(context, required=bool(raw_studies))
    baselines = {"candidate": candidate, "reference": reference}
    observed = [_study(study, index, context, unit, baselines) for index, study in enumerate(raw_studies)]
    by_side = {}
    for side in _SIDES:
        side_studies = [study for study in observed if study["side"] == side]
        by_side[side] = (
            {
                "baseline": baselines[side],
                "minimum": min(study["minimum"] for study in side_studies),
                "maximum": max(study["maximum"] for study in side_studies),
                "max_excursion_abs": max(study["max_excursion_abs"] for study in side_studies),
                "study_count": len(side_studies),
            }
            if side_studies
            else None
        )
    signed_delta = candidate - reference
    abs_delta = abs(signed_delta)
    if not isfinite(abs_delta):
        raise ValueError("The scalar difference is not representable as a finite number")
    evidence_sides = [side for side in _SIDES if by_side[side] is not None]
    observed_variation = None
    sensitivity = "NO_CONTROL_EVIDENCE"
    if observed:
        observed_variation = max(by_side[side]["max_excursion_abs"] for side in evidence_sides)
        candidate_min = by_side["candidate"]["minimum"] if by_side["candidate"] else candidate
        candidate_max = by_side["candidate"]["maximum"] if by_side["candidate"] else candidate
        reference_min = by_side["reference"]["minimum"] if by_side["reference"] else reference
        reference_max = by_side["reference"]["maximum"] if by_side["reference"] else reference
        overlaps = max(candidate_min, reference_min) <= min(candidate_max, reference_max)
        sensitivity = "DIFFERENCE_WITHIN_OBSERVED_VARIATION" if overlaps else "DIFFERENCE_EXCEEDS_OBSERVED_VARIATION"
    near_zero = abs(reference) <= floor
    suppression = ["REFERENCE_AT_OR_BELOW_RELATIVE_FLOOR"] if near_zero else []
    reference_studies = by_side["reference"]
    if reference_studies and reference_studies["minimum"] <= 0 <= reference_studies["maximum"]:
        suppression.append("REFERENCE_VARIATION_INCLUDES_ZERO")
    relative = None
    if not suppression:
        relative = abs_delta / abs(reference) * 100.0
        if not isfinite(relative):
            relative = None
            suppression.append("RELATIVE_DELTA_NOT_REPRESENTABLE")
    return {
        "unit": unit,
        "candidate": candidate,
        "reference": reference,
        "signed_delta": signed_delta,
        "abs_delta": abs_delta,
        "relative_delta_pct": relative,
        "relative_meaningful": relative is not None,
        "reference_near_zero": near_zero,
        "relative_suppression_reasons": suppression,
        "opposite_signs": candidate < 0 < reference or reference < 0 < candidate,
        "noise_sensitivity": sensitivity,
        "uncertainty_status": "INSUFFICIENT_EVIDENCE",
        "evidence_sides": evidence_sides,
        "observed_variation_abs": observed_variation,
        "observed_variation_by_side": by_side,
        "observed_studies": observed,
    }
