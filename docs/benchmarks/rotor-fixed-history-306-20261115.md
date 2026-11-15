# #306: coordinate adapter and fixed-mesh full-turn history

Target: 0.5.9. Follow-up to `90367d6f`.

**Outcome: coordinate adaptation, independent loss evaluation, fixed-mesh
invariance and full-turn closure pass. Angular loss convergence still fails.
The 96-sample estimate is 0.0476288 W and remains provisional. Spatial
convergence, native field-solver parity and the release matrix are pending.**

## Implementation and checks

The internal rotor sampler now accepts an explicit `global` or
`rotor_material` coordinate frame. It rotates global mesh/B data into rotor
axes and retains already-material-frame data. The mechanical pose stays signed
and unwrapped in either case. The default global path is backward compatible.

The independent direct-DFT oracle reads raw material-frame B directly, without
calling the production adapter. Analytical harmonics, DC fields, CW/CCW motion,
nonzero poses and equivalent global/material representations are covered by
tests. The analyser rejects mixed/missing frame declarations, a closure-only
probe used as a history, moved query locations, geometry changes, previous
solution seeds and incorrect saved boundary angles.

The archived global-frame pilot was replayed read-only through the new code:
all three resolutions' loss components were unchanged, with maximum difference
0 W. No earlier evidence was overwritten.

## One-motor run

Same full-machine SPM 8p/12s fixture, 20 A peak sinusoidal current, gamma 0
degrees, 3,000 rpm, nominal magnet properties, M350-50A and 50 mm stack.
Material coefficients and density are unchanged; stacking factor is 1.0.
This uses the existing grade-limit hysteresis/classical lamination eddy law.

96 independent positions over a complete mechanical revolution and a separate
endpoint were collected in two owned FEMM workers. The moving-air-gap geometry
and reference integration grid stayed fixed. The analyser verified model and
answer hashes, full mesh coordinates/connectivity, fixed query coordinates,
unwrapped poses and fresh unsolved-base reloads for all 97 solves.

| Full-turn samples | Hysteresis W | Lamination eddy W | Total rotor iron W |
|---:|---:|---:|---:|
| 24 | 0.00997142 | 0.02116406 | 0.03113548 |
| 48 | 0.01184870 | 0.02989957 | 0.04174827 |
| 96 | 0.01234029 | 0.03528848 | 0.04762877 |

The maximum total-loss difference from the independent query/DFT calculation
was **1.08e-16 W** across these comparisons. This verifies sampling and loss
evaluation on the FEMM fields; measured motor accuracy is not established.

## Convergence and closure

Percentages below are absolute changes divided by the finer result, matching
the convergence gate. Each component also has the predeclared 0.001 W absolute
floor; otherwise the limit is 5% of the finer value. Both numerical
implementations give the same gate decisions.

| Refinement | Hysteresis change | Eddy change | Total change | Combined gate |
|---|---:|---:|---:|:---|
| 24 → 48 | 15.84% | 29.22% | 25.42% | FAIL |
| 48 → 96 | 3.98% | 15.27% | 12.35% | FAIL |

Hysteresis passes the finer step. Eddy and total loss do not. The 48 → 96
absolute changes are 0.000492 W hysteresis, 0.005389 W eddy and 0.005881 W total.
24 samples cannot resolve the mechanical order-12 slot harmonic at Nyquist.
At 96 samples, **12.72%** of estimated loss comes from harmonics above 1 kHz,
beyond the existing material model's frequency coverage.

- Mesh invariance: **PASS**, one full triangular mesh hash for all 97 solves.
- Full-turn closure: **PASS**, maximum component mismatch **4.10e-12 T**, RMS
  component mismatch **1.13e-12 T** (limits 1e-6 T and 1e-7 T respectively).
- Mesh size: **78,954 elements**, **9,741 rotor integration cells**,
  **0.840928 kg** modelled rotor steel.
- Spatial mesh convergence: **NOT RUN**. Mesh invariance is a different check.

The reference no longer changes triangulation with pose. The remaining
angular sensitivity must be resolved before these watts become an acceptance
target. The same empirical material-law limitations, including DC bias/minor
loops and excess loss, remain.

## Runtime and evidence

Mean FEMM collection time was **18.96 s per position**; summed per-position
wall times were **1,838.81 s**, with the workers running concurrently. The
sampler and harmonic calculation took **0.24 s** for the 96-position history
in this run. These timings are diagnostic.

108 analytical, report-integrity, existing loss/frame and historical adapter
checks passed; Ruff and whitespace checks passed. The owned FEMM processes
exited after collection. All 110 sealed historical FEMM sources are unchanged.

The adjacent JSON records component errors, harmonic losses, method/material
inputs, timing and source digests. Raw evidence is retained in the parent
checkout at `output/rotor-iron-loss-306/fixed-history-n96`: all models/answers,
exports, checkpoints, protocol, source snapshot and dependency versions.
See [reproduction instructions](../ROTOR_IRON_LOSS_PILOT.md#follow-up-fixed-mesh-full-turn-history).

The next bounded refinement is 192/384 full-turn samples on this same motor,
followed by independent spatial refinements. No additional motor, speed/load
matrix or public efficiency integration was started in this slice.
