# Prius convergence audit correction, 30 October 2026

The complete macOS and Windows Prius collections measured candidate
`40d8ab9a0a1cadf5cf60023852229f4af010abad`: 17 jobs and 568 actual field
reports per platform. The original reporter returned 9/10 software checks on
both. A separate corrected analysis returns **10/10**, with every registered
request, result, waveform, source identity and reference-input byte unchanged.
This is a post-collection analysis revision, not a new field collection or
release/hardware qualification. The original failing reports remain retained.

## Cause and correction

The protocol's strict `native_final_residual < 1e-8` gate historically audited
Newton's RHS-normalized residual, `L2(f-K(A)A)/L2(f)`. The nonlinear stopping
fix changed the diagnostic history to normalization by the initial nonlinear
defect. The reporter continued reading the last history value, confusing the
two denominators. It flagged loaded positions 4 and 12 of `curve-180-16` on
both platforms.

The solver's stopping rule also changed: current Newton permits its recorded
RHS floor as an alternative to the stage-relative reduction test. This was
not solely a display change. The reporter now checks the explicitly recorded
RHS residual against the unchanged strict protocol limit, and verifies the
recorded native final-stage OR stopping test independently. It retains both
residual values and names their denominators. The record does not expose
intermediate-stage RHS residuals; this audit does not invent them.

Unknown definitions, absent current structured records, non-finite/negative
values, inconsistent history/normalization, and relaxed declared thresholds
are rejected. The old history is accepted only for explicitly opted-in legacy
v1 reanalysis and is labelled as lacking structured stopping evidence.

| Platform | Verified fields | Maximum RHS residual | Original checks | Corrected checks |
| --- | ---: | ---: | ---: | ---: |
| macos | 568 | 9.78378603085e-09 | 9/10 | 10/10 |
| windows | 568 | 9.99640707567e-09 | 9/10 | 10/10 |

The frozen protocol SHA-256 remains
`42adbb9b7803b11eae7d05e4bd347ef1c3f672b81cb8fee858064db97e407a77`.
The Windows report's two derived waveform norms change by at most 3.47e-18
when recomputed on macOS; all actual waves and measured torque values remain
identical. No tolerance was widened and no failed historical artifact was
replaced.

## Review and reproduction

[Machine-readable receipt](PRIUS_CONVERGENCE_AUDIT_20261030.json) records the
original and revised report hashes, separate field/analysis hosts, registration
and runner hashes, unchanged
protected artifacts and exact values. Full retained raw fields and both report
revisions remain in the owner's qualification archive. The revised report
explicitly marks its analysis policy as not frozen at collection, even though
the reference/protocol input bytes were frozen then. `qualified` remains false.

Use the revised reporter on each original collection in a **new** output
directory:

```sh
python -m tools.report_prius_benchmark <original-collection> --out <new-analysis-directory>
```

Validation: 106 focused Python tests pass, including the actual near-floor
regression values, strict boundary rejection at exactly 1e-8, rejection of a
failed native stopping test, frozen-input/provenance guards and existing
Prius/convergence checks. No numerical runtime source or solver binary changed.
The remaining V-shape/reference investigation is separate; this correction
alone does not justify calling the candidate regression-free.
