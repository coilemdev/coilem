# #306 first slice: rotor sampling and FEMM pilot

Target: 0.5.9. Base: main `a3e70035`.

**Outcome: sampling/oracle agreement passes; the FEMM history is not qualified
as a rotor-loss reference. Angular convergence fails and endpoint closure is
poor. The values below are diagnostic outputs, not accepted rotor-loss watts.**

## Implementation

An internal full-turn rotor-material sampling contract follows material points
through remeshing and rotates B into rotor coordinates. It uses mechanical
elapsed time, explicit rotor-core ownership and cited material coefficients.
It rejects missing material points and incomplete/mislabelled sampling grids.
The existing stator kernel and public solve/efficiency behavior are unchanged.

Analytical tests cover co-rotating DC fields, vector sinusoids, multiple
harmonics, speed/mass scaling, CW/CCW poses, reordered/remeshed triangles and
invalid inputs. A separately implemented direct-DFT oracle is checked against
analytical examples. The FEMM analysis checks raw artifact hashes and actual
material-point query coordinates; partial or modified evidence is rejected.

## Pilot

SPM 8p/12s, sinusoidal 20 A peak, gamma 0 degrees, 3,000 rpm, M350-50A,
full machine. Normal FEMM mesh, smart meshing, 0.125 mm air-gap target.
96 independently remeshed positions plus a separately solved full-turn
endpoint, collected in two owned FEMM workers. About 79,900–81,600 elements
per model; 9,939 integration cells on the reference rotor mesh.

Production sampling is compared with independent FEMM queries at those moving
material points and a separate cosine/sine DFT calculation. Both calculations
use the same constitutive loss law and reference integration areas. This is
validation of material tracking and loss evaluation; native field-solver parity
and measured motor accuracy have not been established.

| Full-turn samples | Sampler hysteresis W | Sampler lamination eddy W | Sampler total W | Independent total W |
|---:|---:|---:|---:|---:|
| 24 | 0.03021818 | 0.08131397 | 0.11153214 | 0.11153216 |
| 48 | 0.05252227 | 0.29084944 | 0.34337171 | 0.34337159 |
| 96 | 0.09334389 | 1.13329884 | 1.22664273 | 1.22665536 |

The 96-position total differs from the independent calculation by about
**0.00103%** (0.00001264 W). Hysteresis and eddy comparisons separately pass
the predeclared 10%/0.001 W reference gate at all three resolutions.

Both successive angular convergence checks fail the 5%/0.001 W criterion,
in both implementations. The order-12 slot harmonic lies at the unresolved
Nyquist bin for 24 full-turn samples. At 96 samples, approximately 88% of
calculated loss comes from harmonics above 1 kHz, beyond the existing material
model's frequency coverage. No mesh-convergence series was run.

The independently solved endpoint differs from the first field by **0.72568 T
maximum** and **0.03721 T RMS** over B components at the same material points.
The earlier smoke test's zero-angle solution and this pilot's zero-angle
solution have identical field queries and identical `.ans` SHA-256:

`ae0e53ef3941b5d0f2afcb54b290810b7323adec703571b0d0bf2f2bdafda76b`

At the equivalent -360 degree pose, the mesh changes from 80,940 to 81,392
elements despite equivalent excitation to floating-point precision. This is
evidence of remeshing/field-sampling sensitivity; its exact contribution to the
loss tail still needs isolation. More angle samples alone cannot qualify it.

Mean collection cost was **19.59 s per position**; summed per-position wall
times were **1,900.22 s**. The sampler plus loss postprocessor took **2.32 s**
for the 96-position history in this run. Timing is diagnostic, not a benchmark
across machines.

## Checks and retained evidence

- 75 analytical, report-integrity and existing loss/frame tests passed.
- 9 historical FEMM adapter tests passed; all 110 sealed source files verified.
- Ruff and staged whitespace checks passed.
- Owned FEMM collection workers finished; no full matrix was launched.

The adjacent JSON retains the complete component errors, spectra, timing,
material inputs and analysis source hashes. The local raw evidence directory
is `output/rotor-iron-loss-306/pilot-n96` in the parent checkout. It contains
`analysis.md`, `analysis.json`, `protocol.json`, the source snapshot and
dependency versions, all model/answer files, per-position raw exports and
hashed checkpoints. The two-position smoke collection is retained separately.

## Next bounded experiment, before the full matrix

Stabilize the rotor material mesh/reference history and repeat the closure
control. Evaluate a preserved rotor mesh with FEMM's moving-air-gap approach,
or demonstrate adequate local rotor mesh convergence for the remeshing method.
Then collect angular refinements and independent spatial refinements with
per-component gates. Public efficiency integration and the remaining SPM/IPM,
no-load/loaded and two-speed cases remain pending review.

See [contract and reproduction instructions](../ROTOR_IRON_LOSS_PILOT.md) and
the [published FEMM rotating-loss method](https://www.femm.info/doku/doku.php?id=spmloss).
