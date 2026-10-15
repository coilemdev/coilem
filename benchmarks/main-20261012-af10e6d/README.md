# Windows main comparison record at af10e6d (unnumbered)

This historical Windows main comparison is unnumbered. Report v1.5 identifies the macOS release-candidate record; measured data are unchanged, and the PDF differs from the original only in its fixture-link targets.

[Generated PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown results](benchmark_report.md), [JSON numerical evidence](benchmark_summary.json), [comparison with v1.4](comparison-to-v1.4.json), [elapsed job timings](execution-timings.json), [publication provenance](publication.json) and [artifact hashes](artifact_manifest.json).

This fresh full A/B/C/D run measures clean main commit `af10e6dc8a5b3fc488ec96e4988fd50f2752b60d` on Windows, after the performance and process-pool changes were merged and the versions were bumped to **coilEM 0.2.1 / Magneto2D 0.3.3**. Outcome: **29 PASS and one planned UNSUPPORTED Prius fixture; all 42 BLDC gates PASS**. All 35 supported native jobs completed. The registered comparisons reuse the unchanged frozen, data-only FEMM bundle; no reference solves were executed.

The measured commit predates the tooth-shoe mesh cache fix subsequently merged in PR #42. This publication is based on newer main, but does not claim that later code was measured.

## Numerical comparison with v1.4

All 30 verdicts, numerical gate values and diagnostics match [the preceding Windows process-pool report](../windows-process-pools-20261012-02fa24b/README.md). Registered requests, resolved configurations, material/reference contracts, mesh element counts and angle grids match. All torque, Back-EMF and phase-current waveform objects from all 35 supported native jobs are exactly equal to the previous raw records.

Every physical summary value is exactly equal, including mean torque, torque ripple, Back-EMF fundamental and teeth/yoke steel RMS flux density. Maximum steel RMS absolute change: **0 T**. Solve duration, timestamps, cache paths and runtime provenance are recorded separately from numerical outputs. The comparison reevaluates all registered gates and verifies request/result hashes, all report artifact hashes and every native worker report's `0.3.3` version and `af10e6dc8a5b` build SHA.

These results retain the existing fixture metrics and developer-preview qualification policy. Prius remains outside public HoleM50 support and was not solved.

## Recorded timings

Native execution elapsed **43 min 43.14 s (2623.139099 s)**, compared with **44 min 39.36 s (2679.361760 s)** in v1.4: 56.22 s less time, or 2.10%. There is one full run per candidate; the small difference is an observation, not evidence of a further performance improvement from the version bump.

| Phase | Native jobs | v1.4 summed job time | Windows main summed job time |
| --- | ---: | ---: | ---: |
| A | 10 | 10.41 min | 10.21 min |
| B | 12 | 22.12 min | 21.51 min |
| C | 4 | 5.23 min | 5.06 min |
| D | 9 | 6.83 min | 6.88 min |

Phase D is slightly slower in this run (412.52 s vs 409.61 s). Summed job times exclude between-job harness overhead, so their sum differs from the full execution elapsed time.

The CLI measures meshing, native field solving, field-frame extraction and result construction. Public HTTP PNG/WebP playback packaging and durable UI run saving are outside this benchmark. The independent four-example HTTP/playback comparisons remain recorded in PR #37.

## Runtime and reproduction

The runtime record in `benchmark_summary.json` includes the clean commit, source and native binary hashes, Windows/Python and locked dependencies, harness 1.2.1, protocol 1.1.0 and frozen reference provenance. Selection, inputs and gates are unchanged from v1.4.

```powershell
git checkout af10e6dc8a5b3fc488ec96e4988fd50f2752b60d
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL -ErrorAction SilentlyContinue
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
.\.venv-stable\Scripts\python.exe -m tools.run_benchmarks `
  --suite benchmarks/abcd-v1.1/benchmark_spec.json `
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 `
  --phases A B C D `
  --out-dir ../benchmark-output/main-021-rerun `
  --pdf
```

Use a clean checkout, the recorded dependency versions and a new output directory. Rebuilding with another Rust toolchain creates a different binary identity even when the source commit matches.

## Publication

The generated 64-page PDF is committed unchanged except for its 36 fixture hyperlinks: they named the originating local report paths and now point to the committed fixture JSON on GitHub. Every other byte is identical apart from cross-reference offsets, and `publication.json` keeps both SHA-256 values. The HTML and Markdown versions link to the committed fixture JSON files. Published text/JSON replaces the local run root and omits worker PIDs while retaining all numerical values and identities. CSV, worker logs, raw job evidence, mesh/frame caches and solver binaries remain local. Their registered result hashes and full numerical comparison are retained here.
