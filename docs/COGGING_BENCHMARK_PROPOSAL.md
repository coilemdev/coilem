# Cogging torque benchmark proposal (#185)

A proposal for the cases and gates that would qualify coilEM's cogging torque
against FEMM 4.2, in the next A/B/C/D protocol (1.7.0). **Nothing here is
registered.** The gates are fixed now, before any comparison solve, as
[public issue 185](https://github.com/coilemdev/coilem/issues/185) asks. The
owner decides whether they go into the protocol; the FEMM references come from
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

## Cases

| Case | Phase | Base fixture | S / P | Cycles per rev | Floor | Why |
| --- | --- | --- | --- | --- | ---: | --- |
| `spm_8p12s_example_shoed__cogging` | A | `spm_8p12s_example_shoed` (protocol 1.5.0) | 12 / 8 | 24 | 0.0557 N·m | The app's default SPM. Large cogging (about 12% of its loaded torque), shoed slots |
| `ipm_flat_8p12s_fsae_contract__cogging` | B | `ipm_flat_8p12s_fsae_contract` | 12 / 8 | 24 | 0.0129 N·m | Flat-buried IPM: bridges and pockets set the cogging, not the magnet edge alone |
| `spm_8p48s_distributed_femm_validation__cogging` | C | `spm_8p48s_distributed_femm_validation` | 48 / 8 | 48 | 0.0315 N·m | Distributed winding stator: many narrow slots, low cogging, so the floor matters |
| `ipm_flat_12s10p_fscw_contract__cogging` (optional) | B | `ipm_flat_12s10p_fscw_contract` | 12 / 10 | 60 | 0.0240 N·m | Fractional-slot, very low cogging: tests the floor alone |

Each floor is 0.5% of the base case's FEMM mean loaded torque in the reviewed
protocol 1.6.0 bundle (11.140, 2.576, 6.304 and 4.803 N·m).

Cogging carries no current, so the winding type itself does not enter the
waveform; the distributed-winding case is there for its stator, whose slot
count and openings the 8p/12s cases do not cover.

coilEM's native values for these requests are in
[the convergence study](COGGING_CONVERGENCE.md#native-values-for-the-proposed-cases).

## Gates

Per case, with *r* the reference value and *c* coilEM's:

| Gate | Error | PASS | YELLOW |
| --- | --- | --- | --- |
| `cogging_peak_to_peak` | \|c − r\| of the peak-to-peak | ≤ max(10% of *r*, floor) | ≤ max(20% of *r*, 2 × floor) |
| `cogging_first_harmonic` | \|c − r\| of the first cogging harmonic | ≤ max(10% of *r*, floor) | ≤ max(20% of *r*, 2 × floor) |

Anything above YELLOW is FAIL; missing data is INCOMPLETE. A case's status is
the worst of its gates, as in protocol 1.6.0.

**The absolute floor** is 0.5% of the case's registered FEMM mean loaded
torque, from its base case in the protocol 1.6.0 reference bundle (the table
above). A
low-cogging design can have a peak-to-peak of a few hundredths of a
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

- Native runs on Windows and macOS at the freeze candidate, with
  `coilem benchmark` including the new cases, graded against the reviewed
  reference bundle. The records go into the release record, as for protocol
  1.6.0.
- Cogging becomes **qualified** only for the fixture combinations whose gates
  pass in the freeze report, and only once the app's status for it changes
  (in `backend/qualification.py`, applied when a run is stored).
- **Hardware correlation (optional):** the CREATOR PMSM's measured cogging,
  through #90, labelled hardware correlation, not qualification.

## What implementing it needs (a later PR)

- A `cogging_metrics.py` next to `backend/benchmark_suite/dq_metrics.py`, with
  the two gates and two self-checks above.
- A `"cogging_reference": true` flag on the four cases in the new
  `benchmark_spec.json`, and their derived fixtures.
- The reviewed FEMM bundle, and new native records on both platforms.
