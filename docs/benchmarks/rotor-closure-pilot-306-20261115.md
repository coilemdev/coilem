# #306: fixed-mesh FEMM closure probe

> **2026-11-16 correction:** this closure probe uses the archived current
> trajectory. Closure does not validate constant-gamma excitation. See the
> [native pilot and excitation erratum](rotor-native-pilot-306-20261116.md).

Target: 0.5.9. Follow-up to the first-slice commit `85d8dd06`.

**Outcome: closure and mesh-invariance checks pass on the bounded five-solve
probe. Loss watts, angular/spatial convergence and the full matrix remain
unqualified and were not run.**

## Change

The reference collector now has an optional FEMM Periodic Air Gap motion model.
Two circles at 29.6666667 and 29.8333333 mm lie inside the SPM's free 29.5–30 mm
air gap. The band between them is unmeshed; its boundary arcs have a 0.25 degree
maximum segment angle. Rotor and stator geometry remain fixed. Motion is set by
the boundary's inner angle and matching winding currents.

Every pose reloads the same unsolved baseline. There is no previous-solution
seed, endpoint copying or replacement of -360 degrees with zero. The saved
model angles, complete triangular mesh geometry and material-point queries are
checked independently from collection.

FEMM returns rotor fields in its drawn rotor-material axes for this model. The
collector labels that frame explicitly. The existing global-frame loss
analyser refuses it, preventing accidental double rotation. A coordinate
adapter and full history must be tested before using this mode for loss watts.

## Bounded run

Same SPM 8p/12s fixture, sinusoidal 20 A peak, gamma 0 degrees, nominal magnet
properties, M350-50A and 50 mm stack. Five fresh solves at **0, -3.75, -90, -360
and 0 mechanical degrees**, using normal density and smart meshing. The
predeclared limits were **1e-6 T maximum** and **1e-7 T RMS** component error.

| Check | Previous remeshing pilot | Moving-air-gap probe |
|---|---:|---:|
| Full-turn endpoint RMS error | 0.0372118 T | 1.1251e-12 T |
| Full-turn endpoint maximum error | 0.725680 T | 4.1049e-12 T |
| Repeated zero-angle field error | 0 T | 0 T |
| Triangular mesh | Changed with pose | Identical at all five poses |

The new models all have **78,954 elements**, with **9,741 rotor integration
cells**. Full coordinate/connectivity hash, identical for every solve:

`d0e20a3b7680a0f6b65b590a8f11af26f8dd19f937f0e7b033764311f7f7c30a`

The -3.75 degree sample changes the field by **0.0108968 T RMS** and **0.0945367 T
maximum**, confirming that motion changes the solution. The -90 degree sample
differs from the start by **0.0510067 T RMS** and **0.156522 T maximum**. This
probe therefore provides no basis to shorten the rotor history to one
electrical cycle. The conservative full mechanical-turn contract remains.

Total per-position wall time was **87.64 s** for five solves. This is a closure
measurement on one mesh, not a mesh-accuracy or loss-convergence result. Each
run uses its own reference integration grid; old and new point grids differ.

## Verification and evidence

- 98 analytical, closure-integrity, existing loss/frame and historical FEMM
  adapter checks passed; Ruff passed.
- All 110 sealed historical FEMM source files verified unchanged.
- The earlier 97-solve remeshing pilot and its numerical report are preserved.
- The owned FEMM process exited after the five solves.

The adjacent JSON contains the measured closure statistics, mesh hashes,
timing, protocol digest and report source digest. Raw evidence is retained in
`output/rotor-iron-loss-306/closure-agb-v1` in the parent checkout: models,
answers, query/export scripts, field arrays, source snapshot and dependencies.

Reproduce with the [bounded closure commands](../ROTOR_IRON_LOSS_PILOT.md#follow-up-fixed-mesh-closure-probe).
Method: FEMM's [documented rotor-motion boundary](https://www.femm.info/wiki/RotorMotion).

The next bounded step is the coordinate adapter and repeat of the one-motor
full-turn history, followed by independent angular and spatial convergence.
The full SPM/IPM release matrix and public efficiency integration remain
pending review.
