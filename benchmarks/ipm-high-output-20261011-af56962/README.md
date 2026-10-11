# Higher-output IPM evidence package

[Report](benchmark_report.md), [HTML plots](coilem_benchmark_report.html),
[summary](benchmark_summary.json) and per-case `rows/` records identify the exact
candidate/reference commits, full input hashes, measured waveforms, gate results,
before/after source/runtime hashes and imported-backend hashes. Each field record
retains its original result/FEM/answer SHA-256; large field files remain in the
external frozen measurement archive. Published JSON sanitizes local paths and
retains the original source-result hashes separately. No reference implementation,
adapter, executable, runtime environment or dependency is distributed.

`fixtures/` holds the exact public benchmark requests. The two `.coilem` files
open in the UI, with an explicit 18.8 mm shaft equivalent to the backend-derived
shaft. The UI runs a full electrical cycle; benchmark loaded torque covers 0–90°.
Default public settings are retained. Artifact SHA-256 values are recorded in
`artifact_manifest.json` and the root snapshot manifest.
