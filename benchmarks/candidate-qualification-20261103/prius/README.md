# Exact-candidate Windows Prius software qualification

The physical Windows collection measures clean candidate
**`88aae101fd487795e7fe5300737679f4133790fd`**, coilEM 0.5.0 and
Magneto2D 0.4.0. All **17 jobs / 568 field reports** completed. All **10
software checks pass** with the original frozen inputs and unchanged limits.

- [Complete numerical report](app-results.json) and [readable report](app-results.md)
- [Original registration](registration.json), including the interrupted-attempt history
- [Frozen grading inputs](frozen-inputs/protocol.json), copied before the first field
- [Analysis provenance](analysis-provenance.json) and [before-field source snapshot](source-snapshot.json)
- [Raw archive receipt](raw-archive-receipt.json), binding 3,418 retained files
  totalling 4,795,833,621 bytes in the separate local archive
- [Publication receipt](publication.json): the original numerical and readable
  reports retain their exact bytes; no numerical value was changed

The loaded mean is **353.950530 Nm**, compared with the retained FEMM software
control's **354.953115 Nm** (−0.28246%). The angular control changes mean
torque by **+0.001441 Nm**, and the fine-mesh control by **−0.016741 Nm**.
The complete tutorial waveform and all 13 torque-curve points are retained,
including discrepancies with the upstream software model. These are software
model checks, not hardware correlation or a general spatial-convergence proof.
The report's `qualified: false` and hardware-context limitations are preserved.

## Analysis policy provenance

The original analyzer unconditionally emits the legacy field
`analysis_policy_frozen_at_collection: false`. That field is preserved exactly.
For this new run, the snapshot hash captured in the identity before fields
binds the exact analyzer SHA-256 used for the audit. The
[supplemental receipt](analysis-provenance.json) verifies that chain, including
the already-implemented RHS-normalized residual policy. No grader or acceptance
limit was changed after collection. The release gate checks the snapshot and
analyzer binding directly.

The strict final RHS-normalized residual limit remains **less than 1e-8**.
The native history uses its own initial-defect normalization; it is not compared
directly with that protocol limit. The audit retains its stated scope: the final
continuation stage; intermediate RHS residuals are not retained.

## Retention

Requests, environments and artifact indices for all completed jobs are
published here with their original bytes. Complete waveforms and audit values
are in the numerical report; the [loaded performance observation](loaded-performance-observation.json)
retains the loss/resistance calculations with their source-result hash. Full
portable results, including large field/visualization payloads, stay in the
verified raw archive. The full compressed field
archives and original results are retained locally under
`coilem-benchmark-archives/v050-candidate-88aae101-20261102/prius` in the owner's
Documents folder. Their compressed-file hashes and sizes are in the receipt.
Large field/mesh archives are not included in the public repository. Interrupted
attempts remain in the original collection folder and contribute no qualified
job or field count. Both one-time Windows collection/audit tasks have finished
and their registrations were removed.

Historical Prius reports are unchanged. Exact-candidate Mac A–D evidence is
still required before the complete v0.5.0 release qualification gate can pass.
