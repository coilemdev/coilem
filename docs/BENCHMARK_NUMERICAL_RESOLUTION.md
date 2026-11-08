# Numerical sensitivity in benchmark reports

Benchmark verdicts and numerical-resolution diagnostics answer different
questions. The registered gates retain their original limits and PASS, YELLOW
or FAIL results. The diagnostic explains whether a percentage is meaningful
and what the available numerical controls actually show. It never promotes a
reference, waives a gate or qualifies a release.

Every scalar diagnostic reports the signed and absolute difference with its
unit. Relative error is unavailable when the reference is at or below an
explicit absolute reporting floor, or when its tested variation crosses zero.
The A/B/C evaluator uses the existing 0.01 N m near-zero torque threshold for
this reporting decision; its original relative-error field and gates remain
unchanged. A large percentage on a tiny no-load mean therefore remains
available in raw historical metrics, but the new note emphasizes the absolute
difference.

## Evidence and interpretation

Mesh, rigid-orientation and repeat controls must identify the same physical
case, model, scalar quantity, units and convention as the side being examined.
They also assert that physical equivalence has been checked. A control for an
original drawing cannot establish the rebuilt model's uncertainty; it can
describe sensitivity on the reference side only. A spot-pose flux check cannot
establish a full-cycle back-EMF uncertainty.

The diagnostic records the actual tested ranges, their available evidence
sides and whether those ranges overlap. A missing side remains explicitly
untested. These ranges and observed excursions are **not error bounds**.

- `NO_CONTROL_EVIDENCE`: no applicable numerical controls were supplied.
- `DIFFERENCE_WITHIN_OBSERVED_VARIATION`: the tested ranges overlap; the cause of
  the discrepancy remains unresolved.
- `DIFFERENCE_EXCEEDS_OBSERVED_VARIATION`: the difference remains outside the
  tested values. This establishes neither convergence nor physical truth.

Simple deterministic controls always retain
`uncertainty_status: INSUFFICIENT_EVIDENCE`. One mesh pair does not establish
convergence order or a numerical noise floor. Repeating an identical result
does not establish zero error. Solver residual tolerance is not a torque
uncertainty in N m. Opposite signs and existing polarity diagnostics remain
visible.

This distinction follows standard solution-verification practice: grid
convergence needs an appropriate refinement study and an asymptotic check,
and numerical verification is separate from physical validation. See
[NASA's spatial convergence tutorial](https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html)
and [NISTIR 8298](https://doi.org/10.6028/NIST.IR.8298).

## Review saved comparisons

For controls collected outside the normal harness, create a separate input:

```json
{
  "schema": "coilem.numerical_resolution_request/v1",
  "comparisons": [{
    "id": "example-small-mean-torque",
    "original_gate_status": "FAIL",
    "candidate": 0.0000133,
    "reference": 0.0000649,
    "unit": "N m",
    "relative_floor_abs": 0.00005,
    "context": {
      "case_id": "example-zero-current",
      "candidate_model_id": "rebuilt-model-v1",
      "reference_model_id": "source-model-v1",
      "quantity_id": "rotor-weighted-stress-torque",
      "convention": "rotor-clockwise"
    },
    "studies": [{
      "id": "source-orientation-control",
      "side": "reference",
      "case_id": "example-zero-current",
      "model_id": "source-model-v1",
      "quantity_id": "rotor-weighted-stress-torque",
      "unit": "N m",
      "convention": "rotor-clockwise",
      "baseline": 0.0000649,
      "values": [-0.0001306],
      "kind": "orientation",
      "physical_equivalence_verified": true
    }]
  }]
}
```

```sh
python -m tools.review_numerical_resolution --input review-input.json --out-dir new-review
```

The command writes HTML, Markdown and JSON plus an artifact hash manifest to a
new directory. It runs no field solves and never rewrites the input or original
report. Report units are N m, N·m, Nm, mNm or V. Keep source and control receipts with their hashes when preparing a
real review input. JSON retains evidence identities for audit; the shareable
benchmark report uses a scalar-only projection without model or study IDs.

An owner can separately review the engineering significance of a discrepancy.
Such a decision must be recorded explicitly and does not retroactively change
the original gate verdict or establish a new numerical uncertainty bound.
