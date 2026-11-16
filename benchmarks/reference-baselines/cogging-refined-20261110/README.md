# Reviewed refined FEMM cogging references

Owner-authorized registration for the three-case very-fine native cohort.
The records preserve the original 25 independent static fields per geometry,
their measured input hashes and adapter commit `341cd09342d58323689491ca060a913a34474ed1`.

The reference recipe retains normal FEMM density and halves the airgap target;
material curves, magnet recoil, geometry, precision, angular samples and torque
extraction are unchanged. All three complete sweeps pass the original mean and
periodicity floors. `review.json` binds the source measurements, 75 verified
model/answer pairs, source-current/area audits and material checks.

The records are accepted for this registered software parity scope. Native
very-fine requests use an explicit mesh-only compatibility bridge; recorded
source input identities are not restamped to the new native requests.

## Geometry renewals

`geometry-review.json` pins the geometry sources it was reviewed against. When
one of them changes without changing the geometry, `geometry-renewals.json`
records the renewal instead of rewriting the review: the source, its reviewed
and renewed hashes, and for each reviewed case the fixture, config dump,
full-motor geometry IR and mesh compared with the reviewed sources. The
benchmark accepts a renewed hash only when the record names this exact review,
says the geometry is unchanged, and covers all three cases with zero
differences. The review, the suite and the reference bundle keep their bytes,
so records measured against them stay verifiable.

- 2026-11-16, PR #242: `backend/models/config.py` gained `solve_params.symmetry`
  (`"full"` by default, left out of dumps when `"full"`). Fixtures, config
  dumps, geometry IR and full-motor meshes of all three cases are byte-identical.
