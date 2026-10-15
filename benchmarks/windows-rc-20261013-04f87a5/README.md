# Windows release-candidate benchmark report v1.6

[Generated PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown results](benchmark_report.md), [JSON evidence](benchmark_summary.json), [Windows/main and Mac/RC comparison](comparison-to-windows-main-and-mac-rc.json), [job timings](execution-timings.json), [publication provenance](publication.json), [artifact hashes](artifact_manifest.json).

This full A/B/C/D run measures clean, frozen release candidate `04f87a5013415997cdef96a9bfa35125ce625bc5` from PR #28 on Windows: **coilEM 0.3.0 / Magneto2D 0.3.3**. All 35 supported native jobs completed. Outcome: **29 PASS, one expected UNSUPPORTED Prius case, 42/42 BLDC gates PASS**. Harness 1.2.1, protocol 1.1.0 and the unchanged frozen FEMM bundle were used. No reference solves were executed. All four process-pool override switches were absent.

## Numerical verification

All physical summary values, torque/Back-EMF/phase-current waveform objects, mesh counts, angle grids, numerical gate values and diagnostics exactly match the [preceding Windows main run](../main-20261012-af10e6d/README.md) at `af10e6d`. This includes steel RMS flux density: maximum change **0 T**. Registered inputs/resolved configurations, request/result hashes and report artifact hashes were checked; gates were independently reevaluated. All **1,875 native reports** identify Magneto2D 0.3.3 built at `04f87a501341`.

The source hash exactly matches the [Mac RC record](../macos-rc-20261013-04f87a5/README.md). Every verdict and gate status matches that record. Cross-platform mesh differences move mean torque by at most **0.2345%** outside the registered near-zero absolute gate. Near-zero cases retain absolute deltas; relative percentages are omitted because rounding around zero makes them misleading. Comparing these two machines does not establish a performance ratio.

The registered selection, frozen references, gates and qualification policy are unchanged. Report v1.1 remains the in-app qualification basis; V-shape remains experimental and Prius unsupported.

## Observed timing

Native execution took **44m 52.56s (2692.564787 s)** versus **43m 43.14s (2623.139099 s)** for the preceding Windows main run: **69.43s more (+2.65%)**. There is one pass per candidate, and read-only integrity checks of completed fixtures overlapped this RC pass. These timings are observations rather than a controlled performance comparison.

| Phase | Native jobs | Previous Windows main | Windows RC |
| --- | ---: | ---: | ---: |
| A | 10 | 10.21 min | 10.44 min |
| B | 12 | 21.51 min | 22.37 min |
| C | 4 | 5.06 min | 5.15 min |
| D | 9 | 6.88 min | 6.83 min |

Phase rows sum job durations and exclude between-job harness overhead. The CLI includes meshing, native solving, field-frame extraction and result construction; public HTTP PNG/WebP playback packaging and durable UI saving are outside it.

## Reproduction

Use a clean checkout, recorded dependency versions, and a fresh output directory:

```powershell
git checkout 04f87a5013415997cdef96a9bfa35125ce625bc5
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL -ErrorAction SilentlyContinue
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL -ErrorAction SilentlyContinue
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
.\.venv-stable\Scripts\python.exe -m tools.run_benchmarks `
  --suite benchmarks/abcd-v1.1/benchmark_spec.json `
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 `
  --phases A B C D `
  --out-dir ../benchmark-output/windows-rc-rerun `
  --pdf
```

The runtime record retains Windows/Python, dependency, source and binary identities. The Windows build used rustc 1.95.0; another toolchain can produce a different binary hash from the same source. The pin includes PR #42 and excludes the later persistent mesh cache proposed for 0.3.1 in PR #45.

## Publication

The original 64-page PDF was rendered and reviewed. The published copy differs only in its 36 fixture links, which named the originating local fixture paths and now point to the committed fixture JSON on GitHub; every other byte is identical apart from cross-reference offsets, and `publication.json` keeps both SHA-256 values. HTML and Markdown link to committed fixture JSON. Text/JSON substitutes the local run root and omits worker PIDs without changing numerical data. CSV, raw jobs, worker logs, caches and binaries remain local. The recorded measured commit remains the frozen pin; this publication adds documentation/data on the release-docs stack.
