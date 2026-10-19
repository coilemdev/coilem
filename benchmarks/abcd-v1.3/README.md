# A/B/C/D protocol 1.3.0: winding-relative BLDC current validation

Harness **1.5.1** defaults to this protocol and the complete `ipm-high-output-v3`
FEMM bundle. The physical coordinate convention remains **public-clockwise-v2**.
Only the BLDC golden-sector interpretation changes from protocol 1.1.0.
Protocol 1.2.0 remains a separate experimental Prius extension; this suite keeps
the measured 1.1.0 matrix (35 supported native jobs and one unsupported Prius).

Harness 1.5.1 presents the legacy ORNL Prius row as grey deferred v0.5.0 hardware
coverage. Active phase colours exclude that explicitly deferred row; all raw
verdicts, counts, numerical gates and the overall status retain it. The
[named model collection](../models-v1/README.md) adds runnable Pyleecan Prius
and Honda Accord workflows without changing this suite or its reference bundle.

PR #100 changed the tooth-coil source map and phase-A axis in both solvers at
`738d9516e8500c5996c772bd96470472cbb9a0f9`. The old benchmark validator did not
include that axis. Protocol 1.3.0 explicitly registers it in each D protocol:

| Fixture | Phase-A axis, electrical degrees |
| --- | ---: |
| 14p12s high pole | 15 |
| 4p12s small | 0 |
| 8p12s reference | 30 |

The expected golden-table sector is
`floor(wrap360(physical_angle + phase_a_axis_offset + commutation_advance) / 60)`.
The offsets come from registered winding geometry. They are not fitted to
torque, voltage or current waveforms. The golden current table, physical angle
arrays, current amplitudes, numerical settings, grids and all limits are
unchanged, including the **5.0 percentage-point ripple convergence limit**.
Boundary tests cover the exact transition and either side, including nonzero
advance. Literal fixture-axis expectations also check the production helper.

## Historical results and post hoc interpretation

This reconciliation was registered **after** collecting the 738d951 evidence;
the JSON says `registered_before_full_evidence: false`. It is a validation
contract correction, not a newly measured or preregistered release benchmark.
The historical 1.1.0 reports and their fixed-axis FAILs remain immutable.
The historical #80 5.0340562459-point ripple FAIL also remains unchanged.

The suite has a strict reference bridge naming the exact v3 manifest SHA256,
measured source pin, measured protocol and all three original D protocol hashes.
It permits evaluation of those unchanged physical fields under the new current
frame. It does not relabel the original bundle's protocol, mutate any record,
or admit an arbitrary older reference bundle. Future references can register
protocol 1.3.0 directly.

## New runs

An installed coilEM runs this suite with `coilem benchmark`, and matches the
result against the [published record](../records/README.md) for its platform.
From a clean candidate checkout, with its locked dependencies:

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/my-run --pdf
```

Both delete each job's solver files once it is measured, and stop before a
job when the output drive has less than 3 GB free (`--min-free-gb`); resume
with `--resume`. `--keep-runtime` keeps the solver files.

This uses protocol 1.3.0 and FEMM v3 by default. Reproduce the older validator
explicitly with `--suite benchmarks/abcd-v1.1/benchmark_spec.json`; choose the
appropriate original bundle and preserve its source/input identities.

## Re-evaluate original 738d951 raw evidence without field solves

Keep the measured checkout unchanged. Run the updated report tool from a
separate checkout, against the original native-only output and original v3
reference bytes, writing a new directory:

```sh
python ../updated-pr100/tools/report_benchmark_against_reference.py \
  --source-root . --expected-commit 738d9516e8500c5996c772bd96470472cbb9a0f9 \
  --native-out ../benchmark-output/original-native \
  --reference-bundle ../reference-bundles/ipm-high-output-v3 \
  --evaluation-suite ../updated-pr100/benchmarks/abcd-v1.3/benchmark_spec.json \
  --out-dir ../benchmark-output/angle-reconciled --pdf
```

The tool checks the original raw request/result hashes and measured source,
preserves each D row's `historical_evaluation`, and records the separate new
evaluation contract and evaluator hashes. It rejects changes to case membership,
physical requests, grids, excitation settings or numerical limits. Numerical
gate values must remain exactly equal; only golden-sector checks are adjudicated
in the new frame. Reports identify both the measured and evaluation protocols.
Without `--evaluation-suite`, the same tool retains the historical validator.

No waveform is shifted, rescaled or sign-fitted. The existing V-shape voltage
YELLOW, FEMM v3 scientific-review items and unsupported coverage remain. Passing
the reconciled current checks does not establish loss/efficiency validity or
complete release qualification.
