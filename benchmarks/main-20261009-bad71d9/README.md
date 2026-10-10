# Coilem main benchmark report v1.1

Report revision **1.1** publishes the completed A/B/C/D benchmark
of Coilem **0.2.0**, Magneto2D **0.3.2**, at public commit
`bad71d9cbcb10bf2daa293c5577f9d9e26778a12` captured on October 9, 2026.
This report revision does not change the measured application version or claim
results for later main commits.

- [Full HTML report with plots](coilem_benchmark_report.html) (open a downloaded copy in a browser).
- [Markdown report](benchmark_report.md).
- [JSON summary and numerical evidence](benchmark_summary.json).
- [Exact registered input fixtures](fixtures/).
- [Per-fixture waveforms and gates](rows/).
- [BLDC protocols and frozen golden commutation vectors](protocols/).
- [Back-EMF convention audit](reference_conventions.md).
- [Publication artifact hashes](artifact_manifest.json).

The completed matrix has **27 PASS, two FAIL and one unsupported fixture**.
The two Phase B V-shaped IPM failures (deep-apex and wide-angle) are preserved.
Phase D reports the three BLDC fixtures. Thermal coverage is separately
**UNSUPPORTED**, outside phases A-D. All three BLDC fixtures passed
their unchanged fourteen gates, **42/42 PASS** across twelve measured stages.
Green rows indicate PASS; red rows indicate FAIL. Torque plots show Coilem in
orange solid and matched FEMM in blue dashed, with residuals to expose overlap.

Fresh native measurements use the pinned public request policy,
`Magneto2DSolver(launch_surface=True)`, native Gmsh, WST torque and public
numerical defaults. Fine BLDC stages increase angular sampling on the same
normal spatial mesh. Low-current stages use native field solves and Back-EMF;
their power check compares cycle means. Ideal six-step 120-degree wye excitation
and exact frozen commutation vectors are retained.

Fresh FEMM references use the separate harness commit
`8b95decda27d475ddbb75e99d92744ebc8e53b28` with matching M350-50A and magnet inputs
(N42: 1.315 T / 1.05; N35: 1.23 T / 1.05). Steel curve SHA-256:
`d6096df7cc7103e8b9fc77407b1750e8ddf9f5d0cd1fdf8ad748d9febf896c3d`.
The identical steel curve is already distributed at
[`materials/electrical-steel/M350-50A.csv`](../../materials/electrical-steel/M350-50A.csv).
The reference commit belongs to the separate reference repository, not Coilem.

Fixture JSON bytes are retained by a package-specific Git attribute so their
registered hashes survive checkout on every platform. Numerical samples, comparison metrics, gate limits,
verdicts and original measurement/source/runtime hashes are preserved. Public
report JSON is a derived view: machine-specific launch commands and PIDs are
omitted, local user roots and private environment/validation path labels use
publication aliases, and links point to files within this package. Original
artifact hashes identify the unmodified local evidence, while
`artifact_manifest.json` hashes the files actually published here.
Protocol fixture paths retain their historical source names; the corresponding
templates are provided as `fixtures/source_<BLDC fixture>.json`. Registered
stage inputs are the linked `fixtures/bldc_<fixture>_<stage>.json` files.

The benchmark scripts, private reference implementation, solver binaries,
raw execution logs and source archive are not distributed in this package.
PDF and CSV exports remain in the frozen local snapshot because the current
repository publication check allows text benchmark artifacts only.
Native requests can be replayed through the public `/solve` API using the exact
fixture JSON; reference generation needs a separate FEMM installation.
This report provides comparison evidence and does not qualify a release or
establish spatial mesh convergence, thermal behavior or hardware accuracy.
