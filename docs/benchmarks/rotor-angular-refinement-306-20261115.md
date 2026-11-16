# #306: fixed-mesh 192/384-sample rotor loss refinement

> **2026-11-16 correction:** the archived angle/current schedule does not match
> a constant-gamma native solve. The numerical convergence results below are
> preserved, but these watts are not eligible same-operating-point loss targets.
> See the [native pilot and excitation erratum](rotor-native-pilot-306-20261116.md).

Target: 0.5.9. Follow-up to `37144057` and the
[96-sample history](rotor-fixed-history-306-20261115.md).

**Outcome: both successive angular refinements pass. The 384-sample rotor
iron-loss estimate is 0.04800465 W; the 192 to 384 change is 0.01159%.
Independent loss evaluation, mesh invariance and endpoint closure also pass.
The pilot remains unqualified pending spatial convergence and further
validation. The full release matrix was not started.**

## Scope and reproduction controls

The motor and operating point are unchanged: full-machine SPM 8p/12s,
20 A peak sinusoidal current, gamma 0 degrees, 3,000 rpm, nominal magnets,
M350-50A, 50 mm stack and stacking factor 1.0. The existing grade-limit
hysteresis and classical lamination eddy coefficients are unchanged.

The collector solved 384 half-open positions over one complete mechanical
turn, plus an independent -360 degree endpoint. All 385 positions were freshly
solved. The 192- and 96-sample grids are integer-stride subsets of this history;
the repeated endpoint and unresolved Nyquist bin are excluded from each loss
calculation. No half-wave or electrical-period reconstruction is used.

The four FEMM workers each reloaded the unsolved baseline at every assigned
pose, with no previous-solution seed. The periodic-air-gap mesh and fixed
rotor-material integration points match the previous run. Protocol comparison
found only the sample count and angle list changed. At all 97 overlapping
angles, including the endpoint, the fresh FEMM answers and both field exports
are byte-identical to the earlier run. The fresh 96-sample loss is also
identical, component by component.

## Rotor iron loss

These are empirical loss estimates evaluated on FEMM fields, not a measured
motor-loss validation or a comparison of native field solvers.

| Full-turn samples | Step, mechanical degrees | Hysteresis W | Lamination eddy W | Total rotor iron W |
|---:|---:|---:|---:|---:|
| 96 | 3.75 | 0.01234029257 | 0.03528848128 | 0.04762877385 |
| 192 | 1.875 | 0.01234183493 | 0.03565725245 | 0.04799908739 |
| 384 | 0.9375 | 0.01234172979 | 0.03566291913 | 0.04800464892 |

The maximum total-loss difference between the production sampler and the
independent fixed-material-point/direct-DFT calculation is **7.70e-16 W**.
All three reference-agreement gates pass. The oracle reads the raw material
components independently of the production coordinate adapter.

## Convergence and closure

Changes below are absolute differences divided by the finer result. The
predeclared gate checks hysteresis, lamination eddy and total separately in
both calculations: each difference must be at most the larger of 5% of the
finer result and 0.001 W. Both successive steps pass, including without
relying on the absolute floor.

| Refinement | Hysteresis change | Eddy change | Total change | Combined gate |
|---|---:|---:|---:|:---|
| 96 to 192 | 0.01250% | 1.03421% | 0.77150% | PASS |
| 192 to 384 | 0.000852% | 0.01589% | 0.01159% | PASS |

The finer step changes hysteresis by -1.05e-7 W, lamination eddy by +5.67e-6 W
and total loss by +5.56e-6 W. The earlier angular sensitivity has settled on
this fixed mesh under the registered criterion.

- Mesh invariance: **PASS**, one full triangular mesh hash for all 385 solves:
  `d0e20a3b7680a0f6b65b590a8f11af26f8dd19f937f0e7b033764311f7f7c30a`.
- Full-turn closure: **PASS**, maximum component mismatch **4.10e-12 T** and
  RMS component mismatch **1.13e-12 T**, against limits 1e-6 T and 1e-7 T.
- Mesh size: **78,954 elements**, **9,741 rotor integration cells**,
  **0.840928 kg** modelled rotor steel.
- Spatial mesh convergence: **NOT RUN**. Keeping a mesh fixed through rotor
  motion does not establish convergence under mesh refinement.

At 384 samples, **13.46%** of estimated loss comes from harmonics above the
existing material model's 1 kHz coverage boundary. The grade-limit coefficient
assumption and missing DC-bias/minor-loop, rotating-flux, excess-loss and
loss-field-feedback effects remain limitations. Angular convergence does not
remove these physical-model uncertainties.

## Checks, runtime and retained evidence

108 analytical, report-integrity, existing loss/frame and historical adapter
checks passed. Ruff and whitespace checks passed. All 110 sealed historical
FEMM reference sources were verified unchanged. Automation records confirm
exactly 385 field solves: one preflight and 96 in each of four workers. All
owned FEMM processes exited after collection.

The four-worker collection took approximately 49 minutes. Mean per-position
collection time was **30.16 s**; summed position wall times were **11,611.08 s**
across concurrent workers. Production sampling and harmonic calculation took
**1.00 s** for the 384-position history. These timings are diagnostic.

The adjacent JSON is an unchanged copy of the generated analysis, including
harmonic spectra, source hashes, material inputs and gate details. Raw evidence
is retained in the parent checkout at
`output/rotor-iron-loss-306/fixed-history-n384`: models/answers, exports,
checkpoints, protocol, source snapshot, worker logs and reproduction controls.
Earlier remeshing, closure and fixed-96 evidence remain unchanged.
See the [reproduction commands and FEMM method references](../ROTOR_IRON_LOSS_PILOT.md#follow-up-192384-angular-refinement).

The next bounded step is independent spatial refinement on this same motor
and operating point, retaining 384 angular samples. Native field-solver parity,
public efficiency integration and the multi-motor release matrix remain
pending; none were started in this refinement.
