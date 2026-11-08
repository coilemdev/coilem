# Windows Phase F engineering parity for the v0.5.5 candidate

The complete Windows collection at public measured commit
`34de0f4ca1604311f15edf6fb49b5a2a1bf27909` passes **10/10 cases and 60/60
comparison gates**. It includes 48 loaded and 48 no-load positions for each
normal case. Two additional 96-position FEMM mesh controls bring the selected
reference collection to **1,152 field solutions**.

| Case | Mean torque error | Back-EMF fundamental error | Back-EMF peak error |
|---|---:|---:|---:|
| Drone baseline | 0.5144% | 0.0705% | 0.2551% |
| Drone high current | 0.3718% | 0.0705% | 0.2551% |
| Drone tight air gap | 0.0468% | 0.0293% | 0.0233% |
| Drone current angle 30° | 0.5646% | 0.0705% | 0.2551% |
| Drone no-load | 0.2270 mN·m absolute | 0.0705% | 0.2551% |
| Micro baseline | 0.8623% | 0.3120% | 0.3587% |
| Micro no-load | 0.0953 mN·m absolute | 0.3120% | 0.3587% |
| Single-layer baseline | 0.1371% | 0.1825% | 0.0614% |
| 28-pole multirotor | 0.0410% | 0.0419% | 0.3246% |
| 30-pole hub | 0.0461% | 0.1889% | 0.3062% |

The two no-load rows use their original absolute torque-error gate. No waveform
was shifted, fitted, filtered, interpolated or scaled. Signed waveform
diagnostics report no polarity mismatch. The air-gap refinement controls move
drone torque/fundamental by **0.0362% / 0.0112%** and micro torque/fundamental by
**0.7074% / 0.1555%**, each below the fixed 2% limit.

## Recorded scope

The compact record is
[`../records/phase-f/windows-x86_64.json`](../records/phase-f/windows-x86_64.json).
It retains the actual Windows environment, measured commit and all 69 measured
physics-source hashes. This packet is a post-hoc comparison of unchanged
native-only artifacts; publication did not run new fields or replace their
measurement identity.

Windows engineering qualification covers mean torque and back-EMF for the five
measured outer-rotor SPM families:

| Slots / poles | Concentrated winding layers | Conductors per slot | Peak current range |
|---|---:|---:|---:|
| 12 / 14 | 2 | 12 | 0–15 A |
| 9 / 12 | 2 | 14 | 0–5 A |
| 12 / 10 | 1 | 20 | 0–15 A |
| 24 / 28 | 2 | 10 | 0–10 A |
| 27 / 30 | 2 | 12 | 0–20 A |

The record further limits scope to wye, one parallel path, sinusoidal peak
current, 0–30° current angle, 18–100 mm stator OD, 0.25–0.5 mm air gaps, plain or
shoed teeth, M350-50A steel, N42 magnets, copper, 20 °C winding/magnet
temperature, 3000 rpm and normal/Precise native mesh. Runtime physics must
match the record. These conditions and the supported outputs are explicit in
`qualification_scope`; configurations outside them remain experimental.

Runtime qualification additionally requires the measured custom full-cycle
plan: 360° electrical at 7.5° steps with the signoff nonlinear tolerance.
Ordinary Standard remains experimental. Its Back-EMF request can resolve to the
same 48 angles, but its nonlinear tolerance differs from the measured plan.
The application checks the complete mesh, solver and extraction settings in
`backend/phase_f_qualification.py`.

macOS and Linux have no Phase F qualification record. Phase F supplies no
qualification for cogging (Phase E), loaded d/q, inductance, temperature
derating, losses or efficiency. Independent analytical qualifications, including
specified-wire resistance and its copper-loss calculation, retain their own
scope. Phase E has an experimental reference dataset and remains unqualified;
its retained older native comparison is 10 PASS / 2 YELLOW under unchanged gates
and floors. The normal benchmark report composes A–F while retaining each
component's identity; the reviewed A–D qualification evidence is unchanged.

## Review and provenance

The reviewed reference bundle is
[`../reference-baselines/phase-f-reviewed-20261108`](../reference-baselines/phase-f-reviewed-20261108/README.md).
The v2 dataset identifier binds the complete retained reference handback. It
does not masquerade as an adapter commit. Nine cases and both controls retain
the original source cohort; the hub retains its separate bulk-mesh variant.
The Windows review explicitly accepts that distinction.

The two LRK failures remain failed under their original limits and are accepted
as a documented numerical-sensitivity observation for this engineering review.
No uncertainty interval is asserted and neither failure was converted to PASS.
The owner decision is retained privately; only its digest is published.

A requested native timing lookup opened the hub artifact before the complete
reference seal. The generator and inputs were already frozen, and no
measurement-dependent changes were made. The final comparison helper sealed
the reference collection before its own native reads. This chronology is
retained in `provenance.json`.

The raw field files and failed/retried work remain privately retained with
hash ledgers. Public `native/` files contain allowlisted numeric projections
and the original artifact digests. They are not relabeled copies of the
original measurement artifacts.

## Reproduce the comparison

```sh
python -m tools.verify_phase_f_windows_packet
```

This checks the v2 reference review, all projected waveforms, 60 gates, 30
self-checks, both mesh controls, compact record, artifact hashes and privacy
constraints without launching FEMM or Magneto2D. The full report is
[`report/coilem_benchmark_report.html`](report/coilem_benchmark_report.html).
