# Benchmark protocol 1.8.0: Phase F, outer-rotor motors (proposed)

This is the historical proposal. The default is now the
[combined A-F protocol 1.10.0](../af-v1.10/README.md), which registers these ten
requests against explicitly reviewed original and hub reference cohorts.
Application qualification policy remains separate from that benchmark scope.

**Status: proposed, not registered.** Phase F's requests and gates are fixed
here before any comparison solve. It has no FEMM reference bundle yet, so it
qualifies nothing. Until it does, the app reports every outer-rotor design as
experimental. Harness **1.10.0** can run and grade it, and protocol **1.9.0**
is the default suite; `coilem benchmark` runs phases A–D only.

The [E/F collection results](../femm-ef-20261110/README.md) include exact FEMM
replay and the recorded ten-case Windows native comparison. The remaining
reference review and platform registration work is tracked in the
[E/F integration plan](../femm-ef-20261110/formal-qualification.md).

Phase F is its own suite, `benchmark_spec.json` in this folder, because a
reference bundle carries one reference commit: its FEMM records come from a new
collection, not from the reviewed protocol 1.6.0 bundle.

## Cases

Ten requests over five outer-rotor SPM motors. Each request is the registered
Phase A request `spm_8p12s_concentrated__baseline` of protocol 1.9.0 (Newton since
v0.5.6) with two changes: its motor is
replaced by an outer-rotor design, and its current is set per case. The solve
settings, materials (M350-50A, N42), 3000 rpm and the 7.5° electrical grid over
a full electrical cycle stay Phase A's. `tools/make_outrunner_phase_f.py` writes
the requests and this suite, and `tests/test_outrunner_phase_f.py` checks that
it reproduces them.

| Case | Motor | Slots / poles | Stator OD / hub bore | Teeth | Air gap | Winding (conductors per slot) | Current (peak) |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| `spm_outer_14p12s_drone__baseline` | 2806-class drone | 12 / 14 | 28 / 10 mm | shoes, 2.0 mm mouth | 0.40 mm | tooth coils, 12 | 10 A, γ 0° |
| `spm_outer_14p12s_drone__high_current` | 2806-class drone | 12 / 14 | 28 / 10 mm | shoes, 2.0 mm mouth | 0.40 mm | tooth coils, 12 | 15 A, γ 0° |
| `spm_outer_14p12s_drone__tight_airgap` | 2806-class drone | 12 / 14 | 28 / 10 mm | shoes, 2.0 mm mouth | 0.25 mm | tooth coils, 12 | 10 A, γ 0° |
| `spm_outer_14p12s_drone__angle30` | 2806-class drone | 12 / 14 | 28 / 10 mm | shoes, 2.0 mm mouth | 0.40 mm | tooth coils, 12 | 10 A, γ 30° |
| `spm_outer_14p12s_drone_noload__baseline` | 2806-class drone | 12 / 14 | 28 / 10 mm | shoes, 2.0 mm mouth | 0.40 mm | tooth coils, 12 | 0 A |
| `spm_outer_12p9s_micro__baseline` | 1806-class micro drone | 9 / 12 | 18 / 6 mm | shoes, 1.5 mm mouth | 0.35 mm | tooth coils, 14 | 5 A, γ 0° |
| `spm_outer_12p9s_micro_noload__baseline` | 1806-class micro drone | 9 / 12 | 18 / 6 mm | shoes, 1.5 mm mouth | 0.35 mm | tooth coils, 14 | 0 A |
| `spm_outer_10p12s_single_layer__baseline` | 42 mm outrunner | 12 / 10 | 42 / 20 mm | plain, 3.0 mm opening | 0.40 mm | single layer, 20 | 15 A, γ 0° |
| `spm_outer_28p24s_multirotor__baseline` | 5010-class multirotor | 24 / 28 | 50 / 30 mm | shoes, 2.0 mm mouth | 0.35 mm | tooth coils, 10 | 10 A, γ 0° |
| `spm_outer_30p27s_hub__baseline` | hub-motor class | 27 / 30 | 100 / 70 mm | shoes, 3.0 mm mouth | 0.50 mm | tooth coils, 12 | 20 A, γ 0° |

Four motors have parallel teeth with tooth shoes at the stator OD, as most real
outrunners do: each shoe's two overhangs narrow the tooth-body opening to the
listed mouth. The 12/10 single-layer motor keeps plain tapered teeth, so both
stator shapes are covered. "Tooth coils" is a two-layer concentrated winding, a
coil on every tooth. The winding column is the request's `turns_per_coil`, which
in coilEM counts the conductors in one slot (`backend/winding_utils.py`). With
tooth coils, two coils share each slot, so each coil has half of them: the
drone's 12 is 6 turns per coil. A single-layer winding puts all of them in one
coil. The magnets cover 85% of the pole pitch at their mid radius. Every case is
one operating point. As in Phase A, the high-current, tight-air-gap, 30° and
no-load cases each change one thing from their baseline. The tight air gap
closes the gap from 0.40 mm to 0.25 mm and keeps the magnets and rotor OD.
`docs/OUTRUNNER.md` gives the outer-rotor field meanings: stator OD is the
air-gap face, stator ID the hub bore, rotor ID the magnet seat.

What the selection covers:

- **Sizes.** Stators from 18 mm to 100 mm, air gaps from 0.25 mm to 0.5 mm.
- **Slot and pole combinations.** 12/14, 9/12, 12/10, 24/28 and 27/30, the
  usual outrunner combinations, with first cogging orders from 36 to 270 per
  revolution.
- **Windings.** Tooth coils on four motors and a single-layer winding on the
  12/10, the winding Phase A qualifies on inner rotors.
- **Excitation.** No load, rated and 1.5 × rated current, and a 30° current
  angle. For an SPM the 30° torque is close to cos 30° of the 0° torque, which
  checks the current-angle convention and the outer rotor's half-cycle
  phase-axis offset.

Not included: six-step excitation (Phase D's lanes), cogging (Phase E's
gates), the LRK reference (already compared with its published solution) and
IPM outer rotors, which coilEM does not model.

## Gates

Phase A's, unchanged (`backend/benchmark_suite/abc_metrics.py`):

| Gate | PASS | YELLOW |
| --- | --- | --- |
| `mean_torque` | within 8% (0.01 N·m when the reference is under 0.01 N·m) | within 15% (0.02 N·m) |
| `bemf_fundamental` | within 10% | within 15% |
| `bemf_peak` | within 10% | within 15% |
| `torque_method` | coilEM used WST | — |
| `native_mesh` | coilEM's own mesh | — |
| `angle_grids` | both waveforms on the registered grid | — |

Mean torque is compared with its sign, so a reference that reports the
stator's torque, or the rotor's counter-clockwise, fails. The harness also
prints Phase A's energy-balance diagnostic for both sides: torque over
3·E·I·cos γ / ω.

## Run it

Native only, until a reference bundle exists:

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.8/benchmark_spec.json \
  --no-reference --out-dir ../benchmark-output/v1.8-phase-f
```

With a bundle, pass `--reference-bundle <bundle>` instead of `--no-reference`.
The [FEMM request](../../docs/OUTRUNNER_FEMM_REQUEST.md) says what the bundle
must hold.

## What is left before it qualifies anything

1. The FEMM 4.2 bundle for the 10 cases, collected at one adapter commit and
   reviewed.
2. Native runs on Windows and macOS at the freeze candidate, graded against it.
3. Outer-rotor qualification in `backend/qualification.py` for the
   combinations whose gates pass.
