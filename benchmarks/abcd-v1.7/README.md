# Benchmark protocol 1.7.0: Phase E, cogging torque (proposed)

**Status: proposed, not registered.** Phase E's requests and gates are fixed
here before any comparison solve, as
[public issue 185](https://github.com/coilemdev/coilem/issues/185) asks. It
has no FEMM reference bundle yet, so it qualifies nothing. Harness **1.9.0**
can run and grade it, and protocol **1.9.0** is the default suite;
`coilem benchmark` runs phases A–D only.

The follow-up [protocol 1.7.1 cohort](../cogging-refined-v1/README.md) registers
reviewed refined FEMM references for the three distributed geometries with
very-fine native meshes. That separate cohort does not register this entire
12-case normal-mesh suite. See the [E/F integration plan](../femm-ef-20261110/formal-qualification.md).

Phase E is its own suite, `benchmark_spec.json` in this folder, because a
reference bundle carries one reference commit: its FEMM cogging records come
from a new collection, not from the reviewed protocol 1.6.0 bundle.

## Cases

Twelve requests, one per motor geometry. Each is a registered protocol 1.9.0
request (Newton since v0.5.6) with two changes, `solve_options.cogging_torque` and
`solve_params.corner_refinement` set to `true`. Cogging carries no current,
so the winding, phase current and current angle do not enter it; each case is
a different stator, rotor or magnet arrangement. Corner refinement only
refines coilEM's mesh: without it, the
[convergence study](../../docs/COGGING_CONVERGENCE.md#mesh) found the cogging
noise rose from 0.4% to 10% of the peak-to-peak.

| Case | Base phase | Motor | Slots / poles | Cycles per rev | Period (elec / mech) | Floor |
| --- | --- | --- | --- | ---: | --- | ---: |
| `spm_4p12s_simple__baseline__cogging` | A | SPM, concentrated | 12 / 4 | 12 | 60° / 30° | 0.0024 N·m |
| `spm_4p12s_simple__tight_airgap__cogging` | A | SPM, concentrated | 12 / 4 | 12 | 60° / 30° | 0.0029 N·m |
| `spm_8p12s_concentrated__baseline__cogging` | A | SPM, concentrated | 12 / 8 | 24 | 60° / 15° | 0.0111 N·m |
| `spm_8p12s_concentrated__tight_airgap__cogging` | A | SPM, concentrated | 12 / 8 | 24 | 60° / 15° | 0.0118 N·m |
| `spm_8p12s_example_shoed__cogging` | A | SPM, concentrated | 12 / 8 | 24 | 60° / 15° | 0.0557 N·m |
| `ipm_flat_8p12s_fsae_contract__cogging` | B | Flat IPM, concentrated | 12 / 8 | 24 | 60° / 15° | 0.0129 N·m |
| `ipm_flat_8p12s_fsae_angled_pocket_contract__cogging` | B | Flat IPM, concentrated | 12 / 8 | 24 | 60° / 15° | 0.0108 N·m |
| `ipm_flat_12s10p_fscw_contract__cogging` | B | Flat IPM, concentrated | 12 / 10 | 60 | 30° / 6° | 0.0240 N·m |
| `ipm_flat_24s16p_industrial_contract__cogging` | B | Flat IPM, concentrated | 24 / 16 | 48 | 60° / 7.5° | 0.0976 N·m |
| `spm_8p24s_distributed_femm_validation__cogging` | C | SPM, distributed | 24 / 8 | 24 | 60° / 15° | 0.0283 N·m |
| `spm_8p48s_distributed_femm_validation__cogging` | C | SPM, distributed | 48 / 8 | 48 | 30° / 7.5° | 0.0315 N·m |
| `spm_12p36s_distributed_femm_validation__cogging` | C | SPM, distributed | 36 / 12 | 36 | 60° / 10° | 0.0261 N·m |

What the selection covers:

- **Integer and fractional slots.** Integer-slot 4p/12s, 8p/24s and 12p/36s
  have large cogging; 12s/10p, at 60 cycles per revolution, has very little.
- **Air gap and slot shape.** Each 4p/12s and 8p/12s SPM appears with its
  tight-air-gap variant, and the 8p/12s example adds tooth shoes.
- **Rotors.** Four flat-buried IPMs: the FSAE pocket, its angled-pocket
  variant, a fractional-slot 12s/10p and a 24s/16p.
- **Sizes.** Stators from 50 mm to 270 mm.

Not included: V-shape IPM, whose 0.5.0 status is experimental, and the
BLDC fixtures, whose requests are six-step lanes; either can be added later.

## Gates

`backend/benchmark_suite/cogging_metrics.py`, with *r* the reference value
and *c* coilEM's, both from `backend/cogging.py`:

| Gate | PASS | YELLOW |
| --- | --- | --- |
| `cogging_peak_to_peak` | \|c − r\| ≤ max(10% of *r*, floor) | ≤ max(20% of *r*, 2 × floor) |
| `cogging_first_harmonic` | the same, on the amplitude at LCM(S, P) per revolution | the same |
| `reference_cogging_period` | \|T(period) − T(0)\| of the reference ≤ floor | — |
| `reference_cogging_mean` | \|mean\| of the reference over the period ≤ floor | — |
| `cogging_method` | coilEM used WST | — |
| `cogging_angle_grid` | both waveforms have the same rotor positions | — |

- **The floor** is 0.5% of the base request's FEMM mean loaded torque in the
  reviewed protocol 1.6.0 bundle. `cogging_floor_basis` on each case names the
  record and its torque.
- **The case's status** is the worst of its gates, and missing data makes it
  INCOMPLETE.
- **Diagnostics, not gates:** the waveforms' normalised RMS difference and
  correlation.
- **Why the floor and the gates look like this:** see
  [the proposal](../../docs/COGGING_BENCHMARK_PROPOSAL.md).

## Run it

Native only, until a reference bundle exists:

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.7/benchmark_spec.json \
  --no-reference --out-dir ../benchmark-output/v1.7-phase-e
```

With a bundle, pass `--reference-bundle <bundle>` instead of
`--no-reference`. The [FEMM request](../../docs/COGGING_FEMM_REQUEST.md)
says what the bundle must hold.

## What is left before it qualifies anything

1. The FEMM 4.2 bundle for the 12 cases, collected at one adapter commit and
   reviewed.
2. Native runs on Windows and macOS at the freeze candidate, graded against it.
3. The app's cogging status set to qualified for the combinations whose gates
   pass (`backend/qualification.py`).
