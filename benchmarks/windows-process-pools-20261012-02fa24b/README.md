# Windows process-pool benchmark report v1.4

[Generated PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown results](benchmark_report.md), [JSON numerical evidence](benchmark_summary.json), [comparison with v1.3](comparison-to-v1.3.json), [elapsed job timings](execution-timings.json), [publication provenance](publication.json) and [artifact hashes](artifact_manifest.json).

This full A/B/C/D run measures clean candidate `02fa24b7e9f00643d3d5931f55e79de0b623a9ec` on Windows. Outcome: **29 PASS and one planned UNSUPPORTED Prius fixture; all 42 BLDC gates PASS**. All 35 supported native jobs are new. Reference comparisons reuse the unchanged frozen, data-only FEMM bundle; no reference solves were executed.

The candidate includes performance PRs #32, #33, #34 and #36, and the Windows mesh, field-frame and playback process policies in PR #37. PR #35 published the prior numerical baseline. Application version remains coilEM 0.2.0 and native solver version remains Magneto2D 0.3.2; the candidate commit, source and binary hashes distinguish the measured build. A subsequent version bump was not part of this run.

## Numerical comparison with v1.3

All 30 recorded verdicts and every numerical gate value match [the previous Windows report](../main-20261012-0b463b3-rerun/README.md). Registered requests, resolved configurations, material/reference contracts, mesh element counts and angle grids match. All torque, Back-EMF and phase-current waveform objects from all 35 supported native jobs are exactly equal to the previous raw records.

Mean torque, torque ripple, Back-EMF fundamental and all other physical summary values are exactly equal. Only teeth/yoke steel RMS flux density shows floating-point accumulation differences: the largest absolute change is **6e-14 T**. Timing, cache paths, timestamps and runtime provenance are compared separately from numerical outputs. The comparison reevaluates the registered gates and verifies request/result hashes and each worker's before/after runtime identity.

These results establish retention of the existing fixture metrics. They do not extend geometry coverage or change the developer-preview qualification policy. Prius remains outside public HoleM50 support and was not solved.

## Recorded timings

Native execution elapsed **44.66 minutes**, compared with **176.62 minutes** in v1.3, an observed ratio of **3.96x**. The previous run had concurrent workloads; these are report-to-report observations across all intervening changes, rather than a controlled process-pool-only comparison.

| Phase | Native jobs | Previous summed job time | Current summed job time | Observed ratio |
| --- | ---: | ---: | ---: | ---: |
| A | 10 | 59.43 min | 10.41 min | 5.71x |
| B | 12 | 59.86 min | 22.12 min | 2.71x |
| C | 4 | 13.81 min | 5.23 min | 2.64x |
| D | 9 | 43.44 min | 6.83 min | 6.36x |

The CLI measures meshing, native field solving, field-frame extraction and result construction. Public HTTP PNG/WebP playback packaging and durable UI run saving are outside this benchmark. The independent four-example HTTP/playback comparisons remain recorded in PR #37.

## Runtime and reproduction

The exact runtime is retained in `benchmark_summary.json`: commit/source/native binary hashes, Windows and Python versions, locked dependencies, harness 1.2.1, protocol 1.1.0 and reference provenance. The suite and all gates are unchanged from v1.3.

```powershell
git checkout 02fa24b7e9f00643d3d5931f55e79de0b623a9ec
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL -ErrorAction SilentlyContinue
.\.venv-stable\Scripts\python.exe -m tools.run_benchmarks `
  --suite benchmarks/abcd-v1.1/benchmark_spec.json `
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 `
  --phases A B C D `
  --out-dir ../benchmark-output/windows-process-pools-rerun `
  --pdf
```

Use a clean checkout, the recorded dependency versions and a new output directory. Rebuilding with another Rust toolchain creates a different binary identity even when the source commit matches.

## Publication

The generated PDF is committed unchanged except for its 36 fixture hyperlinks: they named the originating local report paths and now point to the committed fixture JSON on GitHub. Every other byte is identical apart from cross-reference offsets, and `publication.json` keeps both SHA-256 values. The HTML and Markdown versions link to the committed fixture JSON files. Published text/JSON replaces the local run root and omits worker PIDs while retaining all numerical values and identities. CSV, worker logs, raw job evidence, mesh/frame caches and solver binaries remain local. Their registered result hashes and full numerical comparison are retained here.
