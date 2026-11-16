# #306: FEMM rotor iron-loss spatial refinement

Target: 0.5.9. Follow-up to `c9fda83e` and the
[384-sample angular study](rotor-angular-refinement-306-20261115.md).

**Outcome: both successive spatial refinements pass. All three meshes also
pass angular convergence, independent loss evaluation, within-turn mesh
invariance and endpoint closure. The finest rotor iron-loss estimate is
0.04770660 W. This qualifies the numerical reference for this one case under
the registered criteria; measured accuracy, native field-solver parity and
release-matrix qualification remain outstanding.**

## Case and mesh controls

The operating point is unchanged: full-machine SPM 8p/12s, 20 A peak sinusoidal
current, gamma 0 degrees, 3,000 rpm, nominal magnets, M350-50A, 50 mm stack and
stacking factor 1.0. Hysteresis/classical lamination eddy coefficients and the
7,650 kg/m3 steel density are unchanged. No public loss/efficiency integration
was added in this study.

Each history contains 384 half-open positions over a full mechanical turn and
an independently solved -360 degree endpoint. The endpoint is excluded from
loss evaluation. The existing normal history was retained read-only; two new
histories contribute 770 fresh solves. Each worker reloads an unsolved baseline
at every pose, with no previous-solution seed or angular symmetry reconstruction.

Fine and further-refined levels retain the existing `fine` and `very_fine`
bulk/geometry presets, with explicit intermediate air-gap targets to bound
runtime. These controls were selected before the full histories were collected
and confirmed by the user. Standard-preset preflights are retained separately;
they do not enter the convergence comparison. The loss tolerance was unchanged.

| Level | Bulk preset | Air-gap target mm | Moving-band step degrees | Total elements | Rotor cells |
|---|---|---:|---:|---:|---:|
| Normal | normal | 0.125 | 0.25 | 78,954 | 9,741 |
| Fine | fine | 0.100 | 0.20 | 114,948 | 16,313 |
| Further refined | very_fine | 0.080 | 0.16 | 190,184 | 29,906 |

Actual saved moving-band arc settings match the protocols. Maximum rotor-cell
areas decrease from 1.99801 to 1.13064 to 0.50214 mm2; maximum rotor edges
decrease from 2.70576 to 2.02897 to 1.38874 mm. Thus the study verifies smaller
cells and tighter air-gap controls as well as higher element counts.

The modelled rotor steel masses are 0.84092837, 0.84095885 and 0.84096653 kg.
The slight change reflects the refined representation of the same curved
geometry. Each mesh integrates its own physical domain without mass
renormalization. Integration cells may differ between levels but remain fixed
through every pose within each level.

## Rotor iron-loss estimates at 384 samples

| Level | Hysteresis W | Lamination eddy W | Total rotor iron W |
|---|---:|---:|---:|
| Normal | 0.01234172979 | 0.03566291913 | 0.04800464892 |
| Fine | 0.01230940536 | 0.03552219721 | 0.04783160257 |
| Further refined | 0.01229165268 | 0.03541495181 | 0.04770660449 |

These are empirical loss estimates on FEMM fields. The production sampler and
independent fixed-material-point/direct-DFT oracle use the same FEMM solutions.
Their agreement checks tracking and loss mathematics; coilEM's own field
solver has not yet been compared against this rotor reference.

The maximum total-loss difference between the two calculations is
**8.12e-16 W** across all three meshes and all 96/192/384 angular subsets.
All reference-agreement gates pass. Reanalysis reproduces the previous normal
results and the fine interim results with maximum component difference **0 W**.
Fresh normal zero-angle answers and field exports are byte-identical to the
previous normal run.

## Spatial convergence

Percentages are absolute changes divided by the finer result. Each component
must satisfy max(5% of finer loss, 0.001 W), separately in the production and
independent calculations. Both successive mesh steps pass, without relying
on the absolute floor. The tolerance was declared before collection.

| Refinement | Hysteresis change | Eddy change | Total change | Combined gate |
|---|---:|---:|---:|:---|
| Normal to fine | 0.26260% | 0.39615% | 0.36178% | PASS |
| Fine to further refined | 0.14443% | 0.30283% | 0.26201% | PASS |

The finer step changes hysteresis by -1.7753e-5 W, lamination eddy by
-1.0725e-4 W and total loss by -1.2500e-4 W. These are mesh-sensitivity
diagnostics, not an error bound relative to an exact or measured solution.

## Angular convergence and closure

Both 96 to 192 and 192 to 384 angular steps pass at every spatial level.
The finer angular step is shown below; components are checked separately in
both calculations with the same convergence criterion.

| Mesh | 192 to 384 hysteresis change | Eddy change | Total change | Angular gate |
|---|---:|---:|---:|:---|
| Normal | 0.000852% | 0.01589% | 0.01159% | PASS |
| Fine | 0.000651% | 0.01705% | 0.01249% | PASS |
| Further refined | 0.000684% | 0.01559% | 0.01139% | PASS |

| Mesh | Endpoint max component error T | Endpoint RMS error T | Closure gate |
|---|---:|---:|:---|
| Normal | 4.10e-12 | 1.13e-12 | PASS |
| Fine | 1.94e-12 | 5.68e-13 | PASS |
| Further refined | 8.50e-12 | 3.46e-12 | PASS |

Closure limits remain 1e-6 T maximum component error and 1e-7 T RMS component
error. All 385 answers at each level retain one full triangular mesh hash,
including coordinates/connectivity and unchanged rotor integration cells.
The three spatial levels have distinct mesh hashes. Artifact hashes, signed
unwrapped poses, fixed material query locations and empty previous-solution
seeds are verified for every history.

## Implementation, runtime and evidence

The optional collector now accepts explicit air-gap block targets and
moving-band arc segmentation. Defaults preserve the normal zero-angle
solution. The new spatial report rejects changes to physics, angle grids,
material assumptions, reference binaries, dependencies or unrelated reference
implementations. The production field solver and loss kernel are unchanged.

131 analytical, spatial-report integrity, existing loss/frame and historical
adapter checks passed. Ruff and whitespace checks passed. All 110 sealed
historical reference sources are unchanged. All 14 FEMM sessions opened by
the study's preflights and collection workers have exited. The unused
standard very-fine preflight was cancelled before producing a solution;
its partial files and cancellation record remain archived.

Fine used three workers and further refined used five, concurrently. Maximum
worker invocation times were **3 h 39 min** and **4 h 30 min** respectively.
Mean position times were 101.92 s and 209.80 s; summed concurrent position wall
times were 39,240.39 s and 80,771.84 s. The earlier normal history averaged
30.16 s per position with four workers. These timings are diagnostic.

The adjacent JSON is an unchanged copy of the generated combined analysis.
Raw models/answers, exports, checkpoints, protocols, source snapshots, worker
automation records, per-mesh spectra and audits are retained in the parent
checkout at `output/rotor-iron-loss-306/spatial-refinement-n384`. The normal
history remains at `output/rotor-iron-loss-306/fixed-history-n384`. Earlier
remeshing, closure and angular evidence are unchanged. See the
[reproduction commands and FEMM method references](../ROTOR_IRON_LOSS_PILOT.md#follow-up-fixed-mesh-spatial-refinement-at-384-samples).

## Qualification boundary and next step

The one-case numerical gates pass. The overall status remains
`PILOT_NOT_QUALIFIED`: the full release matrix and native field-solver parity
have not been run. At the finest mesh, **13.36%** of estimated loss comes from
harmonics above the existing model's 1 kHz coverage boundary. Grade-limit
coefficients and missing DC-bias/minor-loop, rotating-flux, excess-loss and
loss-field-feedback effects remain physical-model limitations.

The next bounded step is a rotor history from coilEM's own field solves at
this same operating point, compared against the stable FEMM reference.
Public efficiency integration and the multi-motor matrix remain separate
work. Neither was started in this study.
