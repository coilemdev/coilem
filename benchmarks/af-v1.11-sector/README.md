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
motor because it does not repeat. The default suite uses protocol 1.10.0. Its historical platform records
cover the measured full-motor source only. This optional suite supplies
request inputs for experimental sector modeling.

## Run and reproduce

```sh
coilem benchmark --sector --quick
coilem benchmark --sector --out ../benchmark-output/af-sector
python -m tools.run_benchmarks --suite benchmarks/af-v1.11-sector/benchmark_spec.json --out-dir ../benchmark-output/af-sector
python -m tools.make_sector_protocol      # rewrites this folder from protocol 1.10.0
```
