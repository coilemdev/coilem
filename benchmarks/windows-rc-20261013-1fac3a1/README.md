# Windows frozen release-candidate benchmark report v1.8

[Generated PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown results](benchmark_report.md), [JSON evidence](benchmark_summary.json), [Windows v1.6 and macOS v1.7 comparison](comparison-to-windows-v1.6-and-macos-v1.7.json), [job timings and reboot record](execution-timings.json), [publication provenance](publication.json), [artifact hashes](artifact_manifest.json).

This full A/B/C/D run measures clean frozen commit `1fac3a17fca7501d054a12b64b4a0472916ade98` from PR #28: **coilEM 0.3.0 / Magneto2D 0.3.3** on the Windows Ryzen 7 7700. All 35 supported jobs completed with zero worker errors. **A: 10 PASS; B: 12 PASS; C: 4 PASS plus one expected UNSUPPORTED Prius case; D: 3 PASS, with all 42/42 BLDC gates PASS.** Harness 1.2.1, protocol 1.1.0 and the unchanged frozen, data-only FEMM bundle were used. No reference solves were executed.

## Numerical verification

Every registered request, resolved configuration, physical summary, torque/Back-EMF/phase-current waveform, mesh count, angle grid, numerical gate value and diagnostic exactly matches [Windows RC report v1.6](../windows-rc-20261013-04f87a5/README.md). Maximum steel RMS change is **0 T**. Request/result and generated artifact hashes were checked; gates were independently reevaluated. All **1,875 native reports belonging to the completed jobs** identify Magneto2D 0.3.3 built at `1fac3a17fca7`.

The source hash exactly matches [macOS report v1.7](../macos-rc-20261013-1fac3a1/README.md), which measures the same frozen commit. All 30 verdicts and every gate status match. The maximum cross-platform mean-torque difference outside the registered near-zero gate is **0.2345%**; near-zero cases retain absolute differences and omit relative percentages. Hardware differs, so these records do not establish a cross-platform performance ratio.

The registered selection, references, gates and qualification policy are unchanged. V-shape remains experimental, Prius unsupported, and report v1.1 remains the in-app qualification basis. Qualification wording is owned by PR #49; this publication contains benchmark data and its required manifest/PDF allowlist entries.

## Execution and interruption

The host rebooted after **24 jobs** had completed. On the owner's instruction, the registered run was resumed after its commit, source, binary, dependencies and saved request/result hashes were verified unchanged. The interrupted chorded-winding job had no `result.json`; it was restarted in full. Completed jobs were retained, and the remaining eleven jobs were completed after the reboot.

**This is a resumed registered run, not an uninterrupted pass.** Its recorded wall duration is **52.57 minutes (3154.391048 s)**, including the abandoned partial attempt, reboot downtime and harness overhead. The summed durations of the **35 successful jobs are 44.95 minutes (2696.982404 s)** and exclude those interruptions. No uninterrupted wall-clock performance comparison is claimed.

| Phase | Supported jobs | Windows v1.6 successful-job sum | Windows v1.8 successful-job sum |
| --- | ---: | ---: | ---: |
| A | 10 | 10.44 min | 10.45 min |
| B | 12 | 22.37 min | 22.39 min |
| C | 4 | 5.15 min | 5.02 min |
| D | 9 | 6.83 min | 7.09 min |

The machine had no other active solves or builds; its local development server was paused. Numerical comparisons and publication work were deferred until completion. Light progress polling continued during execution. Per-phase sums exclude between-job overhead and are observational timings, not a controlled performance study.

The CLI includes meshing, native solving, field-frame extraction and result construction. HTTP playback packaging, durable UI saving and thermal analysis are outside this benchmark.

## Reproduction

Use a clean checkout, the recorded dependencies and a fresh neutral output folder:

```powershell
git fetch origin
git checkout 1fac3a17fca7501d054a12b64b4a0472916ade98
Remove-Item Env:COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL, Env:COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL, Env:COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL, Env:COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL -ErrorAction SilentlyContinue
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
.\.venv-stable\Scripts\python.exe -m tools.run_benchmarks --suite benchmarks/abcd-v1.1/benchmark_spec.json --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 --phases A B C D --out-dir C:/bench/windows-rc-1fac3a1 --pdf
```

The actual continuation used the identical benchmark command with `--resume`. The output folder must be absent for a new run. Windows 11 build 26200, Python 3.12.14, Rust 1.95.0 and all 29 locked runtime dependencies were recorded. All four process-pool overrides were unset. A different toolchain can produce a different binary identity from the same source.

## Publication

The original 64-page PDF and all 36 fixture JSON files are copied byte-for-byte unchanged. Every PDF fixture link uses the neutral `C:/bench/windows-rc-1fac3a1/report/fixtures/` path and contains no username. HTML and Markdown link to committed fixtures. Published text/JSON normalizes the local run root and omits worker PIDs without changing numerical data. CSV, raw jobs, worker logs and binaries remain local. Solver caches may be removed after their completed results and native build identities have been verified; they are not needed to rebuild the report.

Historical Windows records at `af10e6d` and `04f87a5` are retained. The former is an unnumbered Windows main comparison record; v1.5 identifies the historical macOS RC record, v1.6 the historical Windows RC, v1.7 the new-pin macOS record, and v1.8 this Windows record.
