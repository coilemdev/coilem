# Motor nonlinear convergence records

Issues [#11](https://github.com/coilemdev/coilem/issues/11) and
[#12](https://github.com/coilemdev/coilem/issues/12) cover numerical stopping
and the evidence carried with each motor result. These records apply to the
motor solver; the separate Halbach and generic field Newton paths are unchanged.

## Recorded fields

Each native single-angle `solve_info.nonlinear_convergence` contains:

- `method`: the method that produced the accepted field (`picard`, `newton`,
  or `linear`), rather than only the requested method.
- `iterations`, `max_iterations`: iterations used by that accepted method and
  its cap. For Newton continuation these are totals across stages;
  `stage_iterations` and `stage_iteration_cap` retain the per-stage accounting.
- `raw_max_residual`: for Picard, the largest steel-element
  `abs(mu_target(B) - mu_used) / mu_used`, before relaxation or step capping.
  It is evaluated on the returned field and the permeability used to solve it,
  including any final tight linear polish. It is not a torque-error estimate.
- `scaled_residual`: the Newton equation residual, with its exact normalization
  written into `residual_definition`. It is not a permeability mismatch.
- `tolerance`, `stopping_test`: the actual method-specific threshold and test.
  Historical reporting-only records identify the legacy relaxed Picard test
  and RHS-normalized Newton test explicitly; do not reinterpret their values
  under the new definitions.
- `solution_reused`: congruent positions retain their source solve's convergence
  evidence and counts. The legacy per-position iteration arrays still use zero
  for Python-owned reused positions where no new solve ran.
- `fallback_from`: `newton` if Newton failed and Picard produced the accepted
  field. Iterations describe the accepted method; they do not count discarded
  Newton attempts. Wall time includes the whole run.

The native sweep arrays `loaded_nonlinear_convergence` and
`no_load_nonlinear_convergence` align with their respective position grids.
An omitted no-load solve has no convergence record. Python-owned per-angle
sweeps carry the same records through aggregation into `SolveResult`, along
with the existing iteration arrays. Postprocessing retained reports preserves
this evidence instead of reconstructing it from current defaults.

`solve_metadata` records `solve_quality`, the existing mesh density and element
count, and `nonlinear_max_iterations_used`, `nonlinear_median_iterations`,
`nonlinear_worst_final_mismatch`, `nonlinear_worst_tolerance_ratio`, and
`nonlinear_residual_definitions`. Iteration summaries exclude reused positions.
The mismatch summary includes reused evidence. Raw values with different
definitions must not be presented as equivalent error measures; the
method-specific mismatch divided by its tolerance is the comparable threshold
ratio. A single metadata tolerance is null for a mixed-method sweep; individual
records remain authoritative.

Historical results without records retain null fields, meaning **not recorded**.
Iteration counts or a saved tolerance alone cannot reconstruct a final mismatch.

## Candidate stopping policy for 0.5.0

Picard tests the unrelaxed mismatch directly. Relaxation changes the iteration
path, never the acceptance threshold. Newton tests
`L2(f - K(A) A) / L2(f - K(A0) A0)`, with `A0` the initial linear field of each
continuation stage, using the same constrained equations in numerator and
denominator. Its existing RHS normalization cancels in this ratio because
sources and constraints remain fixed within a stage. Large PM or boundary
terms therefore cannot hide a large fraction of the initial nonlinear defect.
An exactly zero initial defect is accepted as zero.

| Preset | Picard raw mismatch tolerance | Newton stage-relative residual tolerance |
| --- | ---: | ---: |
| Preview (`quick`) | 0.05 | 0.0005 |
| Standard | 0.01 | 0.0001 |
| High accuracy (`fine`) | 0.001 | 0.00001 |
| Custom / direct CLI fallback | 0.001 | 0.00001 |

These are candidate tolerances for owner review, not a claim of equivalent
torque or voltage error bounds. The default cap is 200 per stage to accommodate
the stricter raw Picard test. Explicit request caps remain authoritative.
Diagnostic CLI tolerance overrides and the published Prius request's explicit
overrides are still recorded when used; the public runtime does not inherit
arbitrary numerical environment settings.

The stopping fix does not change meshing, B-H curves, excitation or torque
extraction. It does not tune a voltage or torque target, or alter the separate
Halbach and generic field Newton implementations. The targeted Windows
measurements are recorded separately from the release qualification.

## Display and export handoff

The Results block and dedicated PDF/CSV presentation remain separate work.
Their contract is to show preset, mesh elements, maximum and median iterations,
and method-labelled final mismatch. Render absent evidence as **not recorded**.
Warn if any recorded stage used at least 80% of its cap, or a method-specific
final mismatch exceeds its recorded tolerance (ratio greater than 1). Reused
positions inherit their source field's warning; a fallback should be identified.
Keep numerical stopping, spatial mesh error and reference limitations distinct.

Reporting does not claim qualification of a changed stopping policy. The
[IPM diagnosis](IPM_BENCHMARK_DIAGNOSIS.md) explains the remaining spatial and
reference sensitivity, especially for the deep-apex design. The complete release
matrix is rerun at the 0.5.0 freeze.
