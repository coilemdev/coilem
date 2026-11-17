# #306: fixed material meshes for native rotor-loss histories

Target: 0.5.9, on the #306 branch above PR #242 (`3870e0e1`).
**The native static-field and angular-convergence gates now pass on the same
one-motor pilot. Status remains PILOT_NOT_QUALIFIED.** Spatial convergence,
a corrected FEMM loss history, sector support and public efficiency integration
remain outstanding. The release matrix was not started.

## Implementation

`backend/rotor_motion_mesh.py` adds the internal `FixedMaterialRotorMesh`.
One validated full-machine Gmsh template supplies the rotor and stator cells.
All rotor regions, including magnets, inter-pole air and the shaft, move
rigidly. The stator nodes and cells remain fixed. Only the circular air-gap
annulus is triangulated again, using the existing material-boundary nodes and
uniform intermediate rings. Angular sweeps connect adjacent rings with a
conforming triangle strip; every interface node is shared by both regions.

Checks reject inverted/poor cells, orphan nodes, cracks, incomplete circular
interfaces and changed geometry. Shared-edge incidence and the disk Euler
characteristic verify the filled mesh. Template inputs are copied and remain
unchanged. Phase ampere-turns are rebaked for each actual native mechanical
angle, and magnetization rotates once with the rotor. The original explicit
global-to-material field adapter and two-term loss kernel are unchanged.

This first implementation accepts a full-circle inner SPM with one circular
air gap. Unsupported sectors, outer rotors and other topologies fail explicitly.
The existing public mesher/solve path is unchanged. The pilot selects the new
path with `--motion fixed-material`; it is not wired into public loss results.

The sampler report now verifies the authoritative template hash, identical
motion settings, actual material-cell invariance, endpoint closure and fresh
solver convergence. Agreement between the production calculation and independent
direct DFT is labeled as a mathematics check, separately from FEMM agreement.

## Registered pilot

The fixture is the same full-machine 8p/12s SPM: 20 A peak sinusoidal current,
public gamma zero/native gamma 180, 3,000 rpm, nominal N42 magnets, M350-50A,
50 mm stack, density 7,650 kg/m3 and stacking factor 1.0. The native gamma/current
mapping uses the corrected schedule described in the excitation erratum.

The body mesh is the existing normal Gmsh mesh. The air-gap controls were fixed
before collection: **1,536 angular divisions and four radial layers**. The
0.9375-degree history step is four intermediate-ring pitches. These mesh
controls stay unchanged for the 96/192/384 subsets. Arbitrary, noncommensurate
angles also have structural unit checks; their loss accuracy is not qualified
by this one registered grid.

Every pose retains 78,252 triangles outside the gap and 10,908 gap triangles,
for 89,160 total. All 17,742 rotor-steel integration cells stay the same in
material coordinates. The maximum coordinate difference over the turn is
2.665e-14 mm, below the declared 1e-9 mm invariance tolerance. The minimum
triangle quality is approximately 0.501; the minimum allowed is 0.01. Air-gap
connectivity changes as needed; full-mesh identity is not a gate for this method.

All 385 field solves are independent: 384 half-open full-mechanical-turn poses
and a separately solved -360-degree endpoint. No solved field is reused, no
symmetry waveform is reconstructed, and no field smoothing, frequency cutoff
or loss-floor adjustment is introduced. The mechanical base frequency is 50 Hz.
DC and the unresolved Nyquist bin are excluded as in the original loss contract.

## Static-field controls

The same time-invariant material potential is prescribed on the moving native
nodes: `Az = B0/(4 R^3) * (x^4 - 6 x^2 y^2 + y^4)`, in material metres, with
`B0 = 0.7 T` and `R = 0.028 m`. Its exact field at each material point is
constant in time, so exact rotor loss is zero. This is a manufactured field,
not a motor field solution.

The 32-pose control passes through the actual motion mesh, nodal-potential
gradient, coordinate adapter, sampler and loss kernel: **1.785e-28 W** total.
It passed the predeclared 1 mW limit before the full loaded history was collected.
The control template is semantically identical to the full-history template.

An additional replay on all collected rotor meshes gives:

| Samples | Spurious total loss W | Gate, absolute limit 0.001 W |
|---:|---:|---|
| 96 | 2.536e-28 | PASS |
| 192 | 1.337e-27 | PASS |
| 384 | 5.821e-27 | PASS |

For comparison, the archived remeshing diagnostic produced 0.01897, 0.08882
and 0.40600 W for the same static-potential definition. The replay diagnoses
false temporal variation; it is not an error bound or a correction to subtract
from a motor-loss result.

## Loaded rotor iron-loss estimates

| Samples | Hysteresis W | Lamination eddy W | Total rotor iron W |
|---:|---:|---:|---:|
| 96 | 0.0166003793 | 0.0475764436 | 0.0641768229 |
| 192 | 0.0165984039 | 0.0479783767 | 0.0645767805 |
| 384 | 0.0165971898 | 0.0479662636 | 0.0645634534 |

The rotor steel mass is 0.841162998 kg, unchanged from the native template.
Both successive angular refinements pass in each component, in the production
and independent direct-DFT calculations. The tolerance remains
`max(5% of finer loss, 0.001 W)`; every component also meets the 5% relative
criterion without relying on the absolute floor.

| Refinement | Hysteresis change | Eddy change | Total change | Gate |
|---|---:|---:|---:|---|
| 96 to 192 | 0.01190% | 0.83774% | 0.61935% | PASS |
| 192 to 384 | 0.007315% | 0.025253% | 0.020642% | PASS |

The maximum component difference between the production evaluation and the
independent DFT is 9.16e-16 W. Independent endpoint closure is 8.471e-14 T
maximum component difference and 2.284e-14 T RMS; both pass the original limits.
The five-pose preflight also passes, including an independently rebuilt zero
template and exactly matching repeated-zero queries.

These are temporally converged estimates on native fields, not verified
physical motor losses. At 384 samples, 10.54% of estimated loss comes from
frequencies above the existing coefficient model's 1 kHz coverage. Grade-limit
coefficients, DC-bias/minor-loop effects, rotating-flux corrections, excess loss
and loss-field feedback remain limitations.

## Verification and evidence

- **167 rotor/loss checks pass**, including fixed-material geometry, watertight
  interfaces, unchanged stator nodes, unwrapped endpoints, unsupported geometry,
  ampere-turn polarity, magnetization rotation and the existing analytical tests.
  Prescribed static fields give zero loss; independently calculated time-varying
  harmonics are preserved to numerical precision in both rotation directions.
- **81 sector regression checks pass** on the unchanged public path. The initial
  restricted-sandbox attempt had 80 passes and one Gmsh Windows invalid-handle
  error (`0xc0000008`). A complete fresh run outside the sandbox passed all 81
  in 43.31 s; the initial failure log is retained. No assertions were changed.
- **283 Rust tests pass**. No Rust source or loss kernel was modified. The
  collection executable's hash and all recorded source hashes still match.
- Ruff and whitespace checks pass. All 110 sealed historical reference sources
  are unchanged. Publication snapshot entries are refreshed for this slice.

Four native collection workers finished in a maximum of 236.74 s after setup.
Summed pose wall time is 925.75 s, averaging 2.405 s per solve/export. These are
diagnostic timings, not an end-to-end performance claim.

Raw models, answers, meshes, exports, checkpoints and the authoritative template
remain in the parent checkout at `output/rotor-iron-loss-306/fixed-material-n384-v1`.
The successful preflight is `fixed-material-preflight-v2`; the first development
preflight remains in `fixed-material-preflight-v1`. The manufactured-field
control is `fixed-material-static-control-v2.json`. Tests, spectra, source
snapshots and validation receipts are retained alongside these datasets. The
adjacent compact JSON binds the full raw analysis and replay by SHA-256.

## Reproduction and remaining gates

```powershell
python -m tools.rotor_native_pilot --motion fixed-material --preflight --out OUTPUT/preflight --binary PATH/magneto2d.exe
python -m tools.rotor_native_report OUTPUT/preflight
python -m tools.rotor_fixed_mesh_control --template OUTPUT/preflight/material-template.json --config OUTPUT/preflight/native-config.json --out OUTPUT/static-control.json
python -m tools.rotor_native_pilot --motion fixed-material --positions 384 --limit 1 --out OUTPUT/history --binary PATH/magneto2d.exe
# Run disjoint workers --shard 0/4 through 3/4 using the same request and binary:
python -m tools.rotor_native_pilot --motion fixed-material --positions 384 --resume --shard 0/4 --out OUTPUT/history --binary PATH/magneto2d.exe
python -m tools.rotor_native_report OUTPUT/history
python -m tools.rotor_native_remesh_probe OUTPUT/history
```

The [first corrected 96-sample reference comparison](rotor-matched-femm-306-20261116.md)
now passes the three component agreement checks. It uses the corrected
signed angle/current schedule, actual coil-area normalization and matched
native magnet constants. Corrected FEMM 192/384 angular refinement remains
open. The archived 47.707 mW trajectory remains ineligible as a matching target.
Native spatial convergence, corrected reference convergence/agreement and
full-versus-sector loss validation must precede release qualification and public
loss/efficiency integration. This implementation does not close #306.
