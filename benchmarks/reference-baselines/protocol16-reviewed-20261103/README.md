# Reviewed protocol 1.6 parity references

The [review receipt](review.json) accepts these 46 data-only records for the
registered protocol 1.6 parity comparisons. It records the reviewer as the
Codex assistant performing the owner's requested code/data review. This is
not an independent human or laboratory certification.

All record files retain their original bytes and adapter commit `faced858`.
The original [unreviewed bundle](../../windows-v050-20261102-88aae101/reference-bundle/manifest.json)
and its observations remain unchanged. This bundle has a new manifest and
canonical identity bound to the review; no field was solved or fitted again.

The review verifies collection/request/result hashes, stable producer identity,
all numerical fields against raw results, materials/precision, source integrals,
slot-flux reductions, circuit-to-terminal flux normalization and the twelve
registered reference d/q self-checks. All 29 legacy numerical signatures
reproduce exactly. The CLI that performs the checks is
`python -m tools.review_protocol16_references --help`; the complete raw audit
also needs the separately retained private collection/adapter capsule.

FEMM's series circuits support signed turns, prescribed branch current and
circuit flux linkage. The adapter uses branch current `I/a` and terminal
linkage `lambda_circuit/a` for the declared balanced parallel-path model.
These are physical connection conventions, not fitted gains. See the
[FEMM manual](https://www.femm.info/Archives/doc/manual.pdf), sections 2.2.7,
3.3.4 and 3.4.1. The circuit ampere-turn residual is below 5e-13% in the
retained observations. Legacy density sources preserve an area approximation;
their largest measured difference from ideal `N I/a` is 0.52530%. No correction
is applied to those records. The two repeated input pairs retain their distinct
measurement roles and their small torque/EMF differences.

The accepted scope is the registered torque/EMF comparisons, twelve loaded
flux-vector points and four declared-Br temperature cases. It excludes hardware
accuracy, catalogue temperature coefficients, irreversible demagnetisation,
inductances, maps and losses. V-shape accuracy remains experimental, including
its mixed v0.4/v0.5 EMF change. The separate refinement control is a sensitivity
check, not proof of spatial convergence. Native candidate and platform
qualification remain separate from accepting these reference data.
