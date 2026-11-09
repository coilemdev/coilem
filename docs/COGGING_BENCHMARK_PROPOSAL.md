# Cogging torque benchmark proposal: Phase E (#185)

Phase E is a cogging benchmark of 12 motors against FEMM 4.2, as its own suite
in [protocol 1.7.0](../benchmarks/abcd-v1.7/README.md). **It is proposed, not
registered.** The requests, floors and gates are fixed now, before any
comparison solve, as [public issue 185](https://github.com/coilemdev/coilem/issues/185)
asks, and harness 1.9.0 can already run and grade them. The owner decides
whether it is registered; the FEMM references come from
[the FEMM request](COGGING_FEMM_REQUEST.md).

## What is compared

Each case is a registered fixture with two changes: `solve_options.cogging_torque`
set to `true`, and `solve_params.corner_refinement` set to `true`. The
registered fixtures mesh without corner refinement, which the
[convergence study](COGGING_CONVERGENCE.md#mesh) found raises coilEM's cogging
noise from 0.4% to 10% of the peak-to-peak; corner refinement only changes
coilEM's mesh, not the geometry FEMM models. coilEM solves one cogging period with no current, at 24 positions per
period plus the repeated end (the `custom` and Standard presets), on
per-position Gmsh meshes, with weighted-stress (WST) torque
([convergence study](COGGING_CONVERGENCE.md)). FEMM solves the same 25 rotor
positions. The harness compares the two waveforms' summary numbers; it never
aligns, fits or filters either waveform.

Both sides' numbers come from `backend/cogging.py`, so they use one definition:

- **Peak-to-peak:** largest minus smallest torque over the 25 positions.
- **First cogging harmonic:** the peak amplitude at LCM(S, P) cycles per
  mechanical revolution, from the DFT of the 24 positions without the repeated
  end.
- **Mean** and **end mismatch** |T(period) − T(0)|: zero for an exact solve.
  Native end mismatch is available only for independently meshed endpoints;
  slot-pitch reuse can otherwise force it to zero. The reference closure
  gate requires a measured closing endpoint, and either waveform missing
  that endpoint makes the comparison INCOMPLETE.

Before the numerical gates, the harness recomputes the candidate's summary
from its retained waveform and checks the stored peak-to-peak, peak,
fundamental amplitude, mean, period, position count and harmonic spectrum.
A recorded endpoint mismatch must also agree; an unavailable endpoint
diagnostic stays unavailable, since a waveform cannot prove mesh independence.
Missing, non-finite or inconsistent summary values make the case INCOMPLETE,
including native-only runs. The harness does not repair or rewrite the record.
Consistency allows only serialization/platform rounding (relative `1e-9`,
absolute `1e-12`); the numerical gate bands and registered floors below are
unchanged. The gates use the recomputed values after that check passes.

`backend/cogging.py` is part of the guarded physics-source registry, like
the Back-EMF harmonic and torque summaries. A record missing its hash, or
measured with different source bytes, cannot qualify the current build.
Historical reports retain their measured sources and can be audited under
their original registry; adding a source to today's registry does not add
it to old evidence. Fresh, matching measurements are required before release.

## Cases

Twelve motors, one per geometry: the full table, with each case's floor, is
in the [protocol 1.7.0 README](../benchmarks/abcd-v1.7/README.md#cases).

- **SPM, concentrated (5):** 4p/12s and 8p/12s, each with its tight-air-gap
  variant, and the app's shoed 8p/12s example (large cogging, about 12% of its
  loaded torque).
- **Flat-buried IPM (4):** the FSAE rotor and its angled-pocket variant, where
  bridges and pockets shape the cogging, a fractional-slot 12s/10p with very
  little cogging, and a 24s/16p.
- **SPM, distributed winding stators (3):** 8p/24s, 8p/48s and 12p/36s, with
  many narrow slots.

They span 12 to 60 cogging cycles per revolution and 50 to 270 mm stators.
Cogging carries no current, so the winding type itself does not enter the
waveform; the distributed cases are there for their stators. V-shape IPM
(experimental in 0.5.0) and the six-step BLDC fixtures are left out for now.

coilEM's values on this Mac so far are in
[the convergence study](COGGING_CONVERGENCE.md#native-values-for-the-proposed-cases).

## Gates

Per case, with *r* the reference value and *c* coilEM's:

| Gate | Error | PASS | YELLOW |
| --- | --- | --- | --- |
| `cogging_peak_to_peak` | \|c − r\| of the peak-to-peak | ≤ max(10% of *r*, floor) | ≤ max(20% of *r*, 2 × floor) |
| `cogging_first_harmonic` | \|c − r\| of the first cogging harmonic | ≤ max(10% of *r*, floor) | ≤ max(20% of *r*, 2 × floor) |
| `cogging_method` | coilEM's torque method | WST | — |
| `cogging_angle_grid` | the two waveforms' rotor positions | identical | — |

Anything above YELLOW is FAIL; missing data is INCOMPLETE. A case's status is
the worst of its gates, as in protocol 1.6.0.

**The absolute floor** is 0.5% of the case's registered FEMM mean loaded
torque, from its base case in the protocol 1.6.0 reference bundle: 0.0024 to
0.098 N·m across the 12 cases. A low-cogging design can have a peak-to-peak of a few hundredths of a
newton-metre, where a 10% relative error is below both solvers' mesh noise
and says nothing about a design decision. Half a percent of the motor's own
torque is where cogging stops mattering for most drives, and on the 8p/12s
example it is about ten times coilEM's measured noise (mean and end mismatch
of 0.002 and 0.006 N·m, against a floor of 0.056 N·m).

**Why 10% and 20%.** Cogging is sensitive to the slot opening, the magnet
edges and the air-gap mesh, more than mean torque is (8% / 15%). On the
example, coilEM's WST peak-to-peak does not move between 12 and 96 positions
per period, and its first harmonic is within 2.6% of the 96-position value at
24. A 10% PASS leaves room for the reference's own mesh uncertainty, which the
FEMM request measures, without hiding a modelling error.

### Reference self-checks

Like `reference_dq_torque` in protocol 1.6.0, these check the reference
alone, before it is compared:

| Check | PASS |
| --- | --- |
| `reference_cogging_period` | \|T(period) − T(0)\| of the reference ≤ floor |
| `reference_cogging_mean` | \|mean\| of the reference over the period ≤ floor |

A failure means a rotation, sign or mesh problem in the reference model, not
a difference from coilEM.

### Diagnostics, not gates

The harness also prints the waveforms' normalised RMS difference, coilEM's own
mean and end mismatch, and the second and third cogging harmonics. They are
for review; none decides a status.

## Measurement and publication

- Native runs on Windows and macOS at the freeze candidate, graded against
  the reviewed reference bundle. The records go into the release record, as
  for protocol 1.6.0. `coilem benchmark` would gain Phase E once the owner
  registers it.
- Cogging becomes **qualified** only for the fixture combinations whose gates
  pass in the freeze report, and only once the app's status for it changes
  (in `backend/qualification.py`, applied when a run is stored).
- **Hardware correlation (optional):** the CREATOR PMSM's measured cogging,
  through #90, labelled hardware correlation, not qualification.

## What is in place, and what is left

In place, on this branch:

- `benchmarks/abcd-v1.7/`: the 12 requests, each a registered protocol 1.6.0 (re-derived from protocol 1.9.0, with Newton, in v0.5.6)
  request with the two changes above, and `benchmark_spec.json` with their
  hashes and floors. Protocol 1.6.0 stays the default, and `coilem benchmark`
  runs phases A–D only.
- `backend/benchmark_suite/cogging_metrics.py`: the gates and self-checks,
  graded by `tools.run_benchmarks --suite benchmarks/abcd-v1.7/benchmark_spec.json`.
- `tests/test_cogging_phase_e.py` checks the following:
  - every request derives from its base by exactly the two changes;
  - every floor follows from its reference record;
  - the 12 geometries are distinct;
  - each gate bands as stated.

Left:

1. The FEMM 4.2 bundle for the 12 cases, collected at one adapter commit and
   reviewed.
2. Native runs on Windows and macOS at the freeze candidate, graded against
   it, and published in the release record.
3. The owner's decision to register Phase E, and the app's cogging status
   qualified for the combinations whose gates pass.
