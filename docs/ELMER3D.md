# Experimental Elmer 3D integration

This development path solves explicit three-dimensional magnetostatic cases with
Elmer's `WhitneyAVSolver`. It is separate from the existing 2D adapter and the
public solver selector. A completed solve is not a numerical qualification of
the motor, its end regions, or the Elmer runtime.

The implementation builds on PR #122 (`2b70a2f46c35691c0b309fa068e13ec33822aa1d`).
It leaves the existing motor inputs, 2D implementation and registered research
runs unchanged. It does not download or redistribute Elmer.

## Run a physical control

Install Elmer separately, then use the repository's Python environment, which
already includes Gmsh, meshio, NumPy and Pydantic:

```powershell
python -m tools.elmer3d_solve --demo sphere --elmer-home C:\Elmer --output-dir C:\bench\sphere-3d
python -m tools.elmer3d_solve --demo torque --elmer-home C:\Elmer --output-dir C:\bench\torque-3d
```

Each output directory must be new. The controls write their meshes and input
JSON beside it, in a sibling directory with the suffix `-inputs`. Other control
choices include `coil` and `steel`. The sphere has a 4 mm radius, Br = 1 T and
recoil relative permeability 1.12. The torque control adds a closed toroidal
coil and turns the PM direction perpendicular to the coil's axis.

Run the physical acceptance matrix explicitly:

```powershell
python -m tools.elmer3d_validate --elmer-home C:\Elmer --output-dir C:\bench\elmer3d-controls
```

The matrix compares the sphere's interior field with its analytic value
`2 Br / (mu_rec + 2)`, refines its mesh and exterior domain, verifies the
closed coil's current direction and flux scaling, checks PM linkage at zero
physical current, checks linear superposition, and compares a nonzero torque
with an independent flux-derivative reference. Positive and negative current
results are both retained; their odd part isolates the PM/current interaction
from discretization self-torque. A final case exercises the catalog M350-50A
nonlinear H-B curve. The declared limits are recorded before any solve, in
`validation.json`. These controls do not qualify a motor or establish its mesh
convergence. The 10% torque limit is a pilot consistency check.

The H-B table path also has an independent linear-permeability equivalence
control. Nonlinear cases use Picard iteration with direct factorization
refreshed after every material update; retaining an old factorization is
invalid when reluctivity changes. Cases fail if the nodal field in a steel
body exceeds the supplied curve's B range. This conservative range audit is
not an integration-point error bound and does not add an extrapolation law.

For an interrupted matrix, `--resume` reuses complete cases only after
checking their requests, mesh hashes, runtime binary hashes, and regenerated
SIF hashes. New SIF audit files are retained; completed solve directories are
never overwritten. Use a new validation directory when changing control
geometry or generation parameters.

## Observed pilot controls

[The recorded control summary](ELMER3D_CONTROLS.json) contains all eleven
passing checks, the declared limits, mesh sizes, SIF/input hashes, source
snapshots and external runtime hashes. The Windows AMD64 no-GUI/no-MPI build
reported `26.2-unknown`; it is not an independently qualified runtime.

| Control | Observed result | Declared pilot limit |
| --- | --- | --- |
| PM sphere interior field | 0.628052 T versus analytic 0.641026 T; 2.02% error | 3% |
| Sphere mesh refinement | 0.00093% change | 2% |
| Sphere exterior-domain enlargement | 0.0452% change | 1% |
| Equivalent linear H-B curve versus permeability | Relative full-field difference 3.77e-12 | 2e-6 |
| Coil linkage at 2 A / 4 A | 1.352798e-5 / 2.705597e-5 Wb; exact doubling to printed precision | 2e-6 relative |
| PM linkage at zero physical coil current | 4.836288e-5 Wb | Positive with declared orientation |
| Odd-in-current torque versus flux derivative | -9.440931e-4 / -9.672576e-4 N m; 2.395% error | 10% |
| M350-50A shell around PM | 30 iterations; final change 7.32e-8; core nodal peak 0.948 T | 1e-7 change; within supplied 2.5 T curve |

The small mesh-change metric does not explain away the sphere's remaining
2.02% analytic discrepancy. These measurements establish a development pilot,
not general field or torque accuracy. The actual SPM fixture was also prepared
and topology-checked with independent 38 mm magnets and a 40 mm stack:
127,647 nodes and 677,856 tetrahedra. That motor was **not solved**. Its mesh
exceeds the default 500,000-element guard and needed an explicit larger limit.

The focused Python regression run passed 131 tests, with one external-runtime
test skipped by default. A broader non-weekly run passed 922 tests, with one
pre-existing Windows failure: an older Gmsh test mutates native PATH, preventing
a later bare `git` launch. The same failure reproduces with only the older
test modules. The 3D meshing entry points contain this DLL side effect; the
existing qualified 2D physics sources are unchanged.

## Explicit 3D case contract

`backend/elmer3d/model.py` defines the `coilem.elmer3d_case/v1` JSON contract.
Use `python -m tools.elmer3d_solve --case case.json --elmer-home C:\Elmer
--output-dir C:\bench\new-result` to run a supplied mesh. Relative `mesh_file`
paths resolve beside the JSON file.

- Mesh coordinates are metres. Physical volumes and surfaces must be named.
- Only conformal, first-order tetrahedra are accepted. Every volume must have
  exactly one physical body assignment and a declared material.
- The far boundary must cover the entire closed exterior, including both
  axial ends. ElmerGrid's renumbered physical IDs are read back before the SIF
  is generated; node and tetrahedron counts must be preserved.
- Materials are isotropic linear permeability, a vector PM remanence with
  recoil permeability, or a monotonically increasing scalar H-B curve.
  Nonlinear anisotropic lamination laws are not implemented in this version.
- Each optional coil consists of one meshed, closed solid torus, including
  end connections. Multiple volume groups may form that torus. Truncated slot
  columns and disconnected coils are rejected.
- `current_A` is a signed, static current in amperes per turn. `turns` is the
  number of series turns in that coil. No RMS/peak or phase-angle conversion
  is implicit. `normal` sets the right-hand winding direction. The lowering
  reverses Elmer's cut normal to match that convention.
- CoilSolver constructs a 1 A virtual current-density field. The physical
  source is scaled by `turns * current_A`; linked flux is integrated against
  the unit field and multiplied by `turns`. This also works at zero physical
  current, without dividing by that current. Body-to-component associations
  are explicit, rather than inferred from `Master Bodies`.
- An optional torque surface must be a closed internal surface with
  nonmagnetic, current-free air on both sides. The result integrates vacuum
  Maxwell traction on every face, using outward orientation and degree-three
  quadrature. Torque is already in N m; no stack-length multiplier is applied.

The fixed initial solver profile uses first-order edge elements, tree gauge
for linear cases, and a Lagrange gauge for H-B materials. It uses serial direct
UMFPACK and a configurable Picard iteration policy for nonlinear steel. Both
Lagrange gauge coefficients are scaled by vacuum reluctivity (`1 / mu0`) for
SI conditioning, as checked by the equivalent-linear H-B control. This is
intended for small pilots. A large motor mesh needs a separate memory/runtime
assessment and an evaluated iterative preconditioner before parallel batching.

## Prepare a finite-length motor

`tools.elmer3d_motor` lowers the existing motor cross-section to a 3D tetrahedral
mesh. The motor JSON must explicitly request zero current. It preserves the
source triangle regions and materials and introduces a conformal contour in
air for the closed torque surface. It separately represents:

- The configured steel stack length.
- The explicit magnet axial length and axial centre.
- Radial exterior air and air beyond both stack ends.

For the 40 mm stack in `tests/fixtures/spm_4p12s_simple.json`, an illustrative
axial JSON is:

```json
{
  "magnet_length_mm": 38,
  "magnet_center_mm": 0,
  "end_padding_mm": 15,
  "exterior_radius_mm": 50,
  "core_layers": 4,
  "end_layers": 2,
  "max_tetrahedra": 500000
}
```

```powershell
python -m tools.elmer3d_motor --config no-load-motor.json --axial-geometry axial.json --output-dir C:\bench\motor-3d
```

This prepares and validates the mesh. Add `--solve --elmer-home C:\Elmer` to
execute it. The mesh-size guard rejects an oversized case before allocating
the full 3D mesh. Inspect the prepared inputs before increasing the limit;
that limit is not an estimate of direct-solver memory.

This automatic extrusion currently provides no-load fields and a cogging
torque witness. Loaded motor cases need supplied, fully meshed closed end
turns through the explicit case interface. Automatic motor end-turn generation,
phase BEMF cycles/harmonics, a public 3D UI, transient/eddy-current analysis,
and nonlinear axial lamination physics remain future work. The extrusion
explicitly records its isotropic steel and omitted end-hardware assumptions;
it must not be used to identify OEM axial leakage without resolving those
inputs and proving mesh/domain convergence.

## Retained evidence and failures

Every run retains `input.msh`, the converted mesh, generated SIF and material
data, stdout/stderr logs, full-precision VTU fields, and `fields.npz`. The NPZ
keeps all three spatial and vector components and the tetrahedral connectivity.
The JSON result records the request, input/SIF/source hashes, runtime binary
hashes, mesh counts, nonlinear iterate-change evidence, individual coil flux
linkages, and any closed-surface force and torque. It does not aggregate coils
into phases automatically.

The result is marked `COMPLETE` only after Elmer's completion marker, converged
field iteration, finite vector fields, coordinate mapping and requested flux
outputs have been checked. Failure logs and a `FAILED` result are retained.
The nonlinear iterate-change criterion is not a discretization-error bound.
Results always carry `qualified: false`, including when the runtime is
accepted by the older 2D discovery profile. No existing run is overwritten.

The external process runner supplies timeouts, bounded logs and cancellation.
The 3D path does not use the 2D adapter's rolling cleanup; it retains all case
artifacts. Elmer remains a separately installed program under its original
GPL/LGPL terms; see `THIRD_PARTY_NOTICES.md`.

## Upstream references

- [WhitneyAVSolver](https://github.com/ElmerCSC/elmerfem/blob/release-26.2.1/fem/src/modules/MagnetoDynamics/WhitneyAVSolver.F90)
- [3D PM and tensor-reluctivity example](https://github.com/ElmerCSC/elmerfem/blob/release-26.2.1/fem/tests/mgdyn_anisotropic_rel/cyl-case.sif)
- [Closed-coil example](https://github.com/ElmerCSC/elmerfem/blob/release-26.2.1/fem/tests/mgdyn_steady_coils/case.sif)
- [Flux/field postprocessing](https://github.com/ElmerCSC/elmerfem/blob/release-26.2.1/fem/src/modules/MagnetoDynamics/CalcFields.F90)

For a future custom nonlinear tensor law, independently validate both material
energy and force extraction: the inspected `Reluctivity Function` branch uses
`0.5 B dot H` for energy, which generally is not the nonlinear energy integral.
