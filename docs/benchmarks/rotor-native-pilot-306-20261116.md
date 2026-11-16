# #306: native rotor pilot and FEMM excitation correction

Target: 0.5.9. Follow-up to `0735f5ba`. **PILOT_NOT_QUALIFIED.** The bounded
native history is complete. Angular convergence fails; a time-invariant field
replay demonstrates false loss from the remeshing/linear-gradient/material-point
sampling path. The earlier 47.707 mW FEMM result also has an excitation mismatch
and is ineligible as a same-operating-point loss target. No full corrected FEMM
history, native spatial study, public efficiency integration or release matrix
was started in this step.

## Excitation correction

The archived periodic-air-gap helper applies an inner boundary angle `theta`
in native CCW mechanical degrees, but generates currents from `-theta * pp`.
The native Gmsh adapter uses `+theta * pp`. Therefore the old run's effective
native gamma is `gamma_fixture - 2 * pp * theta`, rather than a constant gamma.
It also used raw fixture gamma zero. The public clockwise gamma-zero request
maps to native gamma 180 through the existing `_clockwise_excitation_config`.
These two mappings must be handled separately and applied exactly once.

For this fixture, `pp = 4`, phase A's axis is 30 electrical degrees and the
phase slot ampere-turn amplitude is `12 turns * 20 A = 240 At`. The independently
tested public gamma-zero schedule is
`NI_phase = 240 * sin(4 * theta + 60 - phase_offset)` with offsets 0/120/240.

| Native pose | Archived FEMM phase A/B/C, At | Correct public gamma-zero phase A/B/C, At |
|---:|---|---|
| 0 degrees | -207.846 / +207.846 / 0 | +207.846 / -207.846 / 0 |
| -0.9375 degrees | -215.249 / +199.553 / +15.697 | +199.553 / -215.249 / +15.697 |
| -22.5 degrees | -120 / -120 / +240 | -120 / -120 / +240 |

The accidental match at -22.5 degrees cannot validate the schedule. The
independent sine checks include zero, a noncongruent pose and the endpoint.
The old collector also used an analytic winding area; the corrected FEMM
anchors divide phase ampere-turns by the actually meshed FEMM coil areas.

The previous angular/spatial convergence results remain reproducible for the
archived drive trajectory. Their numbers and raw evidence are retained. The
claim that they qualify a constant-gamma, same-operating-point reference is
withdrawn. No native/FEMM loss percentage is calculated against that target.

## Native five-pose preflight

The existing 8p/12s SPM fixture is retained: full machine, 20 A peak sinusoidal
excitation, public gamma zero/native gamma 180, 3,000 rpm, 50 mm stack,
M350-50A, nominal magnets. The isolated native binary was rebuilt from the
branch's Rust source with a locked offline release build. The collector uses
the actual public excitation transform, imported Gmsh meshes and the native
solver adapter. It does not reuse solved fields.

Poses are 0, -0.9375, -22.5, -360 and repeated zero degrees. The repeated zero
forces a fresh mesh. The current-bearing mesh is checked against requested
ampere-turns at every pose. The actual reported nonlinear tolerance is `1e-5`;
the harness verifies that tolerance, an attained stopping criterion and
`solution_reused = false`. It does not claim an unforwarded shell override.

Raw native nodal potentials and full meshes are retained. Element B is obtained
from the linear potential gradient, then both mesh and B rotate once from global
to rotor-material coordinates. A separate set of 384 common interior material
queries uses four rings, 96 points per ring. Missing material points fail closed.

| Preflight check | Result |
|---|---|
| Full-turn maximum component closure | 1.863e-13 T; PASS |
| Full-turn RMS component closure | 6.070e-14 T; PASS |
| Fresh repeated-zero difference | Exactly zero; PASS |
| Excitation and solver-convergence audits | PASS at every pose |

Closure alone is insufficient to validate the intermediate field history.

## Corrected FEMM field anchors

Three fresh FEMM comparison poses use the audited native preflight's explicit
phase ampere-turns and signed native boundary angles. A separate area-probe solve
measures every winding block. Each comparison reloads the unsolved base; all
three retain the same 78,954-element mesh and 9,741 rotor cells. No production
backend is imported into the frozen FEMM process. No loss is inferred from
these three poses.

| Native pose | Common material queries | Relative RMS B difference | RMS B difference T |
|---:|---:|---:|---:|
| 0 degrees | 384 | 8.167% | 0.0384402 |
| -0.9375 degrees | 384 | 9.484% | 0.0446663 |
| -22.5 degrees | 384 | 8.297% | 0.0392250 |

The maximum mismatch between saved FEMM `J_re * measured block area` and native
ampere-turns is 2.843e-14 At. Saved boundary angles, empty previous-solution
paths, query coordinates, artifact hashes and mesh invariance are verified.
The anchors originated from preflight v2; current preflight v3 reproduces their
native excitation records and query arrays exactly. The comparison report
records this bridge and both protocol hashes.

These are unrefined pointwise field diagnostics, not a loss-accuracy gate.
Material, geometry, discretization and extraction differences remain to be
investigated before declaring field parity.

## Native full-turn history: failed convergence

All 385 poses were freshly solved: 384 half-open samples and an independent
-360 degree endpoint. The normal imported mesh has 82,716–82,984 elements.
Gmsh bases cover 32 distinct relative angles; the existing production
slot-congruence mesh rotation supplies the remaining poses, with currents
rebaked at each requested angle. Every pose gets a fresh field solution.
Material centroids remain within rotor steel at every sample.

| Samples | Hysteresis W | Lamination eddy W | Total W | Loss above 1 kHz |
|---:|---:|---:|---:|---:|
| 96 | 0.028337284 | 0.176949080 | 0.205286364 | 66.58% |
| 192 | 0.042125361 | 0.666016015 | 0.708141376 | 91.18% |
| 384 | 0.071458737 | 2.923829122 | 2.995287860 | 97.99% |

**These are failed diagnostic estimates, not accepted physical rotor losses.**
Both successive steps fail the unchanged `max(5% of finer loss, 0.001 W)`
criterion in hysteresis, lamination eddy and total loss. From 192 to 384 samples,
changes are 41.05%, 77.22% and 76.36%, respectively. The endpoint still closes
to 1.863e-13 T. The production sampler/kernel and independent direct DFT agree
within 3.11e-15 W, which verifies arithmetic on the same sampled fields;
it does not validate the fields themselves.

The high-frequency tail grows with sampling refinement, and most estimated
loss lies beyond the existing material model's 1 kHz coverage. No frequency
cutoff, smoothing, loss-floor adjustment or material fit was introduced to
force convergence. Four native collection workers completed in about 152 s
after setup; summed per-pose wall time is 589.16 s, averaging 1.53 s per pose.

## Time-invariant potential replay

An additional diagnostic uses the collected material meshes without new solves.
It prescribes the same smooth, time-invariant potential on every mesh:

`Az(x,y) = B0 / (4 R^3) * (x^4 - 6 x^2 y^2 + y^4)`, in material metres,
with `B0 = 0.7 T` and `R = 0.028 m`.

The exact field is constant in time at each material point, so exact rotor loss
is zero. Linear nodal-potential gradients and the existing material-centroid
sampling are then replayed on all registered meshes, after verifying hashes
and slot-congruent material mesh identity.

| Samples | Spurious hysteresis W | Spurious lamination eddy W | Spurious total W |
|---:|---:|---:|---:|
| 96 | 0.001332111 | 0.017638918 | 0.018971029 |
| 192 | 0.002959381 | 0.085856662 | 0.088816043 |
| 384 | 0.006369261 | 0.399632576 | 0.406001837 |

This proves that the current remeshing/extraction/sampling path can create
false temporal loss. It does not apportion all the loaded-history error,
provide an error bound or permit subtracting the replay watts from motor loss.

## Next bounded gate

Stabilize the native material-field history before another full FEMM collection.
Evaluate a fixed rotor integration mesh with consistent field recovery or an
appropriate sliding-interface formulation. First require the static-potential
control to remain below the predeclared 1 mW absolute loss floor, then require
both 96/192/384 loaded-history refinement steps to satisfy the existing
componentwise convergence criterion, alongside closure and fresh-solve checks.
Any recovered-field method must also preserve prescribed analytical time
harmonics; suppressing all variation cannot pass.

After that passes, collect a new same-motor fixed-mesh FEMM history with the
explicit corrected phase schedule, actual coil-area normalization and the
same closure/angular/spatial gates. Only then compare native and FEMM loss.
Retain the empirical material-law limitations: no measured loss calibration,
DC-bias/minor-loop correction, rotating-flux correction, excess loss or loss-field
feedback. The release matrix and public loss/efficiency integration remain gated.

## Reproduction and evidence

The new native collector and report are `tools.rotor_native_pilot` and
`tools.rotor_native_report`; the diagnostic is `tools.rotor_native_remesh_probe`.
FEMM anchors use `tools.femm_reference.rotor_excitation_probe` in the pinned
FEMM process and `tools.rotor_excitation_report` in the native analysis process.
All 110 sealed E/F reference sources remain unchanged.

Validation: 148 analytical, excitation, native-report, prior rotor/loss/frame
and historical-adapter checks passed in 15.29 s. Ruff and whitespace checks
passed. The public production field solver and loss kernel were not changed.

```powershell
python -m tools.rotor_native_pilot --preflight --out OUTPUT/native-preflight --binary PATH/magneto2d.exe
python -m tools.rotor_native_report OUTPUT/native-preflight
python -m tools.rotor_native_pilot --positions 384 --limit 1 --out OUTPUT/native-history --binary PATH/magneto2d.exe
# Run four disjoint workers, --shard 0/4 through 3/4, using the same binary:
python -m tools.rotor_native_pilot --positions 384 --resume --shard 0/4 --out OUTPUT/native-history --binary PATH/magneto2d.exe
python -m tools.rotor_native_report OUTPUT/native-history
python -m tools.rotor_native_remesh_probe OUTPUT/native-history
# Separate pinned FEMM process, after the native preflight:
python -m tools.femm_reference.rotor_excitation_probe --native-preflight OUTPUT/native-preflight --out OUTPUT/excitation-anchors
# Back in the native analysis environment:
python -m tools.rotor_excitation_report OUTPUT/excitation-anchors OUTPUT/native-preflight
```

Raw evidence is retained under the parent checkout's
`output/rotor-iron-loss-306`: `native-preflight-public-v3`,
`native-public-n384-v1`, `correct-excitation-anchors-v1`, `native-build`, logs
and a source snapshot. Failed tolerance preflight v1 and diagnostic preflight
v2 remain separate. Adjacent machine-readable reports retain native loss
harmonics, angular gates, replay results and the FEMM anchor audit.

The [official FEMM rotor-motion explanation](https://www.femm.info/doku/doku.php?id=RotorMotion)
describes motion through air-gap boundary angles while retaining the drawn mesh.
The [FEMM manual](https://www.femm.info/Archives/doc/manual.pdf) documents current
density, block-area integrals and field queries. The excitation sign correction
above is established by the saved native contracts and explicit fresh FEMM
anchor solves, rather than by assuming the two solvers share an angle convention.
