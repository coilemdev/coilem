# Protocol 1.11.0: the A-F benchmark solved as sectors

Protocol 1.11.0 is the combined A-F suite of protocol 1.10.0 with one change:
every request sets `solve_params.symmetry` to `"auto"`. coilEM then meshes and
solves one repeating sector when the geometry and winding repeat around the
circle, and the full motor otherwise (see `docs/MAGNETO2D.md`, "Sector models").
The suite has the same **69 cases and 75 jobs**. Motors, materials, currents,
angle grids, iteration caps, cogging floors, extraction methods and gates are
unchanged.

FEMM always solves the whole motor and never reads this field, so the suite is
graded against the **same 68 frozen references** as protocol 1.10.0. A
hash-bound solve-option bridge in `benchmark_spec.json` names the measured
suite; `backend/benchmark_suite/references.py` checks that every request
differs from its protocol 1.10.0 request in `symmetry` alone (an absent field is
the full motor) before any record is reused. No reference record is copied or
restamped.

Each measured row records the region it solved, `sector_repeats` per stage
(null for the full motor), and the report names any case that solved the full
motor because it does not repeat. Against a separately meshed full motor a
sector solve differs at mesh level; it reproduces the full-circle solve of the
same mesh to round-off (`tests/test_sector_symmetry.py`).

The default suite stays protocol 1.10.0, which qualifies full-motor solves.
This suite is the evidence for sector solves; published platform records match
only full-motor runs.

## Run and reproduce

```sh
coilem benchmark --sector --quick
coilem benchmark --sector --out ../benchmark-output/af-sector
python -m tools.run_benchmarks --suite benchmarks/af-v1.11-sector/benchmark_spec.json --out-dir ../benchmark-output/af-sector
python -m tools.make_sector_protocol      # rewrites this folder from protocol 1.10.0
```

The release numerical workflow's `sector` collection measures this suite and
the 17 separate Prius jobs as sectors on Windows and macOS, with the same
shards, build and join as the `registered` collection.
