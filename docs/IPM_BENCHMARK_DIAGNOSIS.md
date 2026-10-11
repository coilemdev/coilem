# IPM benchmark diagnosis and next-release fixture decision

[PR #14](https://github.com/coilemdev/coilem/pull/14) replaces the two low-output
V-shape IPM cases in the default release matrix and publishes the
[compiled baseline v1.2](../benchmarks/release-baseline-20261011-v1.2/README.md).
It relates to [issue #11, nonlinear convergence](https://github.com/coilemdev/coilem/issues/11)
and [issue #12, convergence reporting](https://github.com/coilemdev/coilem/issues/12).
Neither issue is resolved by changing the fixtures. This PR changes no backend
or Rust solver implementation.

## What caused the original failures

The [original v1.1 measurements](../benchmarks/main-20261009-bad71d9/benchmark_report.md)
and [macOS rerun](../benchmarks/main-20261010-45e0a5c-rerun/README.md) retain both
FAIL verdicts. Torque was already measured in N m. Small net torque makes a
relative error sensitive to small absolute integration errors; displaying mN m
does not remove that error or justify changing the gates.

Controlled diagnostic sweeps at candidate
`1cc684f0b3bd29f7a69baa8f31446462a7c68356` held geometry, mesh, materials,
executable and angle grids fixed, changing only nonlinear tolerance from
0.05 to 1e-5. The separate FEMM reference commit was
`8b95decda27d475ddbb75e99d92744ebc8e53b28`.

| Original fixture / metric | Public defaults | Diagnostic tolerance 1e-5 |
| --- | ---: | ---: |
| Deep apex mean torque gap | 36.02% | 30.72% |
| Deep apex Back-EMF H1 gap | 4.88% | 0.33% |
| Wide angle mean torque gap | 12.41% | 6.56% |
| Wide angle Back-EMF H1 gap | 36.03% | 12.31% |
| Wide angle Back-EMF peak gap | 25.16% | 15.33% |

Both diagnostic full sweeps still FAIL the unchanged historical gates.
The registered IPM fixtures explicitly select **Newton**; they do not use
Picard by default. Issue #11's concern about the relaxed Picard stopping
criterion remains a separate implementation concern.

- **Wide angle:** premature nonlinear stopping explains much of the weak
  no-load flux / Back-EMF error. The default no-load solves stop after about
  three iterations. The global Newton residual is normalized by the entire
  right-hand side, so meeting its threshold does not guarantee convergence
  of the much smaller flux linking the winding. Spatial resolution at
  magnet/pocket corners accounts for further differences.
- **Deep apex:** tightening nonlinear convergence alone leaves a large torque
  mismatch. At a strict native 0-degree point, opposing stress contributions
  of about +0.475 and -0.488 N m leave a net magnitude of only 0.013 N m.
  Weighted-stress discretization and reference mesh sensitivity therefore
  matter substantially. On the same retained FEMM field at 45 degrees,
  smooth native weighting gives 0.014091 N m, while FEMM's area-weighted,
  rounded weighting gives 0.019666 N m. Refining FEMM at that angle changes
  its torque to 0.012389 N m. The original FEMM torque is not a converged
  ground-truth value.

The native field and FEMM field agree closely when solved on the same retained
FEMM mesh with a common torque estimator. That is a diagnostic comparison,
not a public native-Gmsh benchmark. It supports convergence, mesh and torque
extraction sensitivity as causes rather than a gross field-equation mismatch;
it does not allocate the entire waveform error quantitatively.

Additional point studies at `af56962` used explicit diagnostic settings.
Converged Picard and Newton on identical wide-angle meshes differed by only
0.000502% in no-load flux and 0.000089% in loaded torque. Both Picard runs
needed 149 iterations after the 80-iteration attempts failed. Merely switching
nonlinear methods is not the demonstrated remedy. The finest paired
corner/edge points (0.01 / 0.04 mm targets) still differed by about 4.09% in
flux and 4.07% in torque, failing the predeclared point screening. Those
points do not qualify a full sweep or a replacement reference.

## What PR #14 resolves

The default benchmark now uses new physical geometries with higher output,
retaining the apex/angle features. Magnet-leg length changes from 9 to 12 mm
for deep apex and from 9 to 10 mm for wide angle. Current, stack, winding,
materials, public normal-mesh/Newton defaults and gates remain unchanged.

| New fixture | Native / FEMM mean torque (N m) | Torque gap | Back-EMF H1 / peak gap | Outcome |
| --- | ---: | ---: | ---: | --- |
| Deep apex high output | 0.625690 / 0.582518 | 7.41% | 3.35% / 3.95% | PASS |
| Wide angle high output | 0.789964 / 0.737758 | 7.08% | 3.49% / 3.95% | PASS |

The [published qualification package](../benchmarks/ipm-high-output-20261011-af56962/README.md)
contains full registered torque and Back-EMF waveforms, exact inputs and
runtime/source hashes for candidate `af56962` and fresh matched FEMM.
New geometry passing is not a solver fix for the original designs or proof of
spatial convergence. Historical cases, evidence and FAILs remain in the
[archive](../benchmarks/README.md).

## Work that remains open

- **Issue #11:** qualify an output-reliable nonlinear stopping policy and
  native/reference spatial behavior, then regress the unchanged SPM, flat-IPM,
  distributed-winding and BLDC cases. Reproduce the original failed cases as
  well as the new default suite. Do not infer resolution from fixture removal.
- **Issue #12:** record per-position iteration counts, final residuals and
  their definitions, method, tolerance, caps and mesh statistics through the
  backend, Results view, PDF and CSV. Angular-convergence plots in the BLDC
  benchmark do not supply this nonlinear convergence reporting.
- Run the complete selected matrix on a single next-release commit before
  broadening the preview's numerical qualification.

The underlying diagnostic sweeps and point studies remain local, with
registered input, source, binary and artifact hashes. They are not redistributed
as reference code, adapters or field-solver binaries. Retained audit-file
SHA-256 identities identify the summarized records:

| Diagnostic record | SHA-256 |
| --- | --- |
| Original fixed-mesh sweep comparisons | `f0902629e7934ef84cc21fe15d02d2f6bf3107f62580afa09f760037f90b8677` |
| Corner/edge point plan | `91311f457d8dbe7379fd40acda7975c06faf4567b9f41f79083b08ba64171c1d` |
| Same-mesh Picard point plan | `7061a3910815c16df733f4413a69d89de980b5ebd59aee1429b42f61d726b584` |
