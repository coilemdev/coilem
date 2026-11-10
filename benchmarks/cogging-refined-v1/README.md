# Registered refined cogging cohort, protocol 1.7.1

This cohort contains exactly three distributed SPM geometries: 8p24s, 8p48s
and 12p36s. The native requests use `very_fine` mesh and retain the current
Newton solver, corner refinement, material contract, 25-point cogging grid and
original case floors. Only native mesh density changes from the measured
normal requests in `measured-suite.json`.

The reviewed reference bundle is
`benchmarks/reference-baselines/cogging-refined-20261110`. It freezes the three
completed FEMM half-gap sweeps at their original adapter commit and input hashes.
The native mesh choice does not change the separately reviewed FEMM recipe.
The explicit hash-bound bridge verifies every request field and permits only
`normal` to `very_fine` native density. Original normal-mesh failures remain in
the original suite and investigation record.

The owner authorized registration after the raw-data review: all 75 refined
model/answer pairs, zero-current and winding-area audits, material coercivity,
independent closure and zero mean were verified. Six independently rerun
endpoints reproduced the models, solutions and extracted data exactly.

Run the complete native qualification from a clean candidate checkout:

```powershell
python -m tools.cogging_qualification --candidate <full-candidate-sha> --directory <new-output-folder>
```

The existing release benchmark workflow has a dedicated
`cogging-refined-very-fine` collection. With `runner=both`, it builds the pinned
candidate independently on Windows and macOS, collects all three requests, and
uploads immutable measurements plus a compact qualification report. The report
is independently regraded and binds candidate physics, source and result hashes,
the reviewed bundle, actual native mesh metadata and all 18 gates.

Reference registration does not itself confer native or hardware qualification.
Native qualification requires both platform runs to pass at the same candidate.
The normal application default and the original matrix remain unchanged.
