# Next-release benchmark baseline report v1.2

[Markdown report](benchmark_report.md), [HTML plots](coilem_benchmark_report.html),
[JSON numerical records](benchmark_summary.json), [artifact hashes](artifact_manifest.json)
and [run commands](../abcd-v1.1/README.md).

This is a compilation of recorded evidence for the new default matrix, not a
fresh full sweep at one candidate. The unchanged cases retain the
[October 10 macOS rerun](../main-20261010-45e0a5c-rerun/README.md) at `45e0a5c`.
The two physical replacements use [October 11 qualification](../ipm-high-output-20261011-af56962/README.md)
at `af56962`, with fresh matched FEMM. Each row retains native and reference
waveforms, gates, original runtime/source identities and source-record hashes.
Links resolve to the exact measured fixtures in their source packages.

The planned item is ORNL Prius 2004: its HoleM50 rotor geometry is outside the public flat-buried/V-shape IPM policy. Geometry helpers exist, but native meshing/field solves and matched FEMM qualification are needed before enabling public support. Numerical status remains UNSUPPORTED; no comparison was performed and no delivery date is claimed.

Selected outcomes: **29 PASS, one planned coverage item (not yet supported)**, across A - SPM, B - IPM,
C - Distributed Winding and D - BLDC. Phase D retains 42/42 gates. Only the
two Phase B magnet-leg dimensions change. All other requests, references,
material contracts, angular grids, golden vectors and gates remain unchanged.

The low-output originals are excluded from the default protocol 1.1.0, and remain
in [historical protocol 1.0.0](../abcd-v1/README.md) and
[report v1.1](../main-20261009-bad71d9/benchmark_report.md) with their FAILs.
New geometry passing does not resolve the original numerical differences,
establish spatial convergence or qualify a new release commit. Torque units
were already N m; expressing them in mN m does not change relative error.

Use the default full command on the next release checkout to create a fresh
single-candidate report. macOS runs only native Magneto2D against the saved
data-only references; FEMM is not a dependency. PDF and CSV exports remain
outside the repository under its text-artifact publication policy.
