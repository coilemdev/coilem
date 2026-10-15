# macOS release-candidate benchmark report v1.5

[Generated PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown results](benchmark_report.md), [JSON numerical evidence](benchmark_summary.json), [comparison with v1.4](comparison-to-v1.4.json), [elapsed job timings](execution-timings.json), [publication provenance](publication.json) and [artifact hashes](artifact_manifest.json).

This full A/B/C/D run measures the pinned coilEM 0.3.0 release candidate `04f87a5013415997cdef96a9bfa35125ce625bc5` (the head of PR #28, declared in #46) on macOS. Outcome: **29 PASS and one planned UNSUPPORTED Prius fixture; all 42 BLDC gates PASS**. All 35 supported native jobs are new. Reference comparisons reuse the unchanged frozen, data-only FEMM bundle; no reference solves were executed.

The candidate is `main` at `6f78d69` plus the 0.3.0 release commit: application version coilEM 0.3.0 and native solver Magneto2D 0.3.3. Since [Windows report v1.4](../windows-process-pools-20261012-02fa24b/README.md) at `02fa24b`, the changes are the Windows process-pool benchmark record, the 0.2.1 / Magneto2D 0.3.3 version bump (#39), the tooth-shoe mesh-cache key (#42, provenance only) and the 0.3.0 release documentation (#28). None changes a solver input or numerical path.

## Comparison with v1.4

All 30 recorded verdicts and every gate status match the previous report, as do the selected cases, phases, fixtures, frozen reference commit and protocol. The four BLDC (Phase D) cases keep all 42 gates PASS.

The values are not bit-identical, because v1.4 ran on Windows and this run on macOS. Gmsh builds slightly different meshes on each platform from the same input: 26 of the 26 gated sinusoidal cases have a different element count, typically by a few to a few tens of elements. Candidate mean torque moves by at most 0.23% relative (V-shape deep apex) and by less than 0.01% for most SPM and flat-buried IPM cases. Every change stays far inside its gate.

| Phase | Case | Verdict (v1.4 → v1.5) | Mean torque vs FEMM, v1.4 | Mean torque vs FEMM, v1.5 | Mesh elements, v1.4 → v1.5 |
| --- | --- | --- | ---: | ---: | ---: |
| A | `spm_4p12s_simple__baseline` | PASS → PASS | 0.161% | 0.158% | 59,110 → 59,102 |
| A | `spm_4p12s_simple__high_current` | PASS → PASS | 0.117% | 0.116% | 59,110 → 59,102 |
| A | `spm_4p12s_simple__tight_airgap` | PASS → PASS | 0.076% | 0.063% | 45,700 → 45,694 |
| A | `spm_4p12s_simple_noload__baseline` | PASS → PASS | near-zero reference¹ | near-zero reference¹ | 59,110 → 59,102 |
| A | `spm_4p12s_simple_noload__high_current` | PASS → PASS | 0.279% | 0.275% | 59,110 → 59,102 |
| A | `spm_4p12s_simple_noload__tight_airgap` | PASS → PASS | near-zero reference¹ | near-zero reference¹ | 45,700 → 45,694 |
| A | `spm_8p12s_concentrated__baseline` | PASS → PASS | 0.158% | 0.158% | 82,940 → 82,938 |
| A | `spm_8p12s_concentrated__high_current` | PASS → PASS | 0.084% | 0.084% | 82,940 → 82,938 |
| A | `spm_8p12s_concentrated__tight_airgap` | PASS → PASS | 0.268% | 0.269% | 87,040 → 87,048 |
| A | `spm_8p12s_reference_angle30__baseline` | PASS → PASS | 0.320% | 0.320% | 77,218 → 77,228 |
| B | `ipm_flat_12s10p_fscw_contract` | PASS → PASS | 0.595% | 0.590% | 87,318 → 87,342 |
| B | `ipm_flat_24s16p_industrial_contract` | PASS → PASS | 0.580% | 0.580% | 97,578 → 97,542 |
| B | `ipm_flat_4p12s_micro_contract` | PASS → PASS | 0.331% | 0.333% | 109,788 → 109,776 |
| B | `ipm_flat_8p12s_fsae_angled_pocket_contract` | PASS → PASS | 0.102% | 0.102% | 122,806 → 122,762 |
| B | `ipm_flat_8p12s_fsae_contract` | PASS → PASS | 0.145% | 0.145% | 122,708 → 122,700 |
| B | `ipm_flat_8p12s_fsae_thin_bridge_contract` | PASS → PASS | 0.125% | 0.126% | 122,338 → 122,322 |
| B | `ipm_vshape_8p12s_baseline_contract` | PASS → PASS | 7.485% | 7.430% | 94,684 → 94,688 |
| B | `ipm_vshape_8p12s_deep_apex_high_output_v1` | PASS → PASS | 7.411% | 7.160% | 97,338 → 97,342 |
| B | `ipm_vshape_8p12s_narrow_angle_contract` | PASS → PASS | 4.116% | 4.154% | 94,304 → 94,306 |
| B | `ipm_vshape_8p12s_pocket_offset_contract` | PASS → PASS | 5.402% | 5.453% | 94,770 → 94,772 |
| B | `ipm_vshape_8p12s_thin_bridge_contract` | PASS → PASS | 1.803% | 1.804% | 91,026 → 91,030 |
| B | `ipm_vshape_8p12s_wide_angle_high_output_v1` | PASS → PASS | 7.076% | 7.123% | 94,154 → 94,160 |
| C | `spm_12p36s_distributed_femm_validation` | PASS → PASS | 2.976% | 3.103% | 77,084 → 77,070 |
| C | `spm_8p24s_distributed_femm_validation` | PASS → PASS | 1.131% | 1.101% | 74,560 → 74,552 |
| C | `spm_8p48s_chorded_5_6` | PASS → PASS | 0.625% | 0.700% | 74,662 → 74,656 |
| C | `spm_8p48s_distributed_femm_validation` | PASS → PASS | 0.565% | 0.662% | 74,662 → 74,656 |
| C | `ornl_prius_2004_ipm` | UNSUPPORTED → UNSUPPORTED (planned; not solved) | — | — | — |
| D | `spm_14p12s_high_pole` | PASS → PASS (14/14 BLDC gates) | 0.056% | 0.057% | — |
| D | `spm_4p12s_small` | PASS → PASS (14/14 BLDC gates) | 0.198% | 0.201% | — |
| D | `spm_8p12s_reference` | PASS → PASS (14/14 BLDC gates) | 0.852% | 0.817% | — |

¹ No-load cases whose FEMM mean torque is near zero are gated on the absolute torque difference, so a percentage is not meaningful.

These results confirm that the release candidate retains the existing fixture metrics on macOS. They do not extend geometry coverage or change the developer-preview qualification policy. Prius remains outside public HoleM50 support and was not solved.

## Recorded timings

Native execution elapsed **56.55 minutes** on an Apple M4 (10 cores, 16 GB), against 44.66 minutes for v1.4 on the Windows Ryzen 7 7700. The machines and operating systems differ, so these are observations, not a performance comparison.

| Phase | Native jobs | v1.4 summed job time (Windows) | v1.5 summed job time (macOS) |
| --- | ---: | ---: | ---: |
| A | 10 | 10.41 min | 8.23 min |
| B | 12 | 22.12 min | 33.06 min |
| C | 4 | 5.23 min | 7.32 min |
| D | 9 | 6.83 min | 7.91 min |

The CLI measures meshing, native field solving, field-frame extraction and result construction. Public HTTP playback packaging and durable UI run saving are outside this benchmark.

## Runtime and reproduction

`benchmark_summary.json` retains the exact runtime: commit, source hash `603030c7a118…` and native binary hash `fa2e1c7b6808…`, macOS-15.7.3-arm64-arm-64bit with Python 3.12.13, the locked dependencies, harness 1.2.1, protocol 1.1.0 and the reference provenance. Magneto2D was built from the pinned tree with `cargo build --release --locked` (rustc 1.94.0). The run used a clean checkout of the pinned commit with no process-pool overrides set.

```sh
git checkout 04f87a5013415997cdef96a9bfa35125ce625bc5
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
unset COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL \
  COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL
PYTHONPATH="$PWD" .venv/bin/python -m tools.run_benchmarks \
  --suite benchmarks/abcd-v1.1/benchmark_spec.json \
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 \
  --phases A B C D \
  --out-dir ../benchmark-output/macos-rc-04f87a5 \
  --pdf
```

Use a new output directory. Rebuilding with another Rust toolchain creates a different binary identity even when the source commit matches. Each job's solve cache was deleted after the job recorded its result, to keep disk use bounded; the report never reads those caches.

The release-candidate freeze in #46 asked for this run on the Windows Ryzen 7 7700. The owner accepted this macOS record instead, because every verdict and gate status matches Windows report v1.4; no Windows run of the pinned commit is recorded. The v1.4 PowerShell commands reproduce it on Windows at this commit.

## Publication

The generated PDF is committed unchanged except for its 36 fixture hyperlinks: they named the originating local report paths and now point to the committed fixture JSON on GitHub. Every other byte is identical apart from cross-reference offsets, and `publication.json` keeps both SHA-256 values. The HTML and Markdown versions link to the committed fixture JSON files. Published text and JSON replace the local run root with `<run-root>` and omit worker PIDs, while retaining all numerical values and identities. CSV, worker logs, raw job evidence, mesh and frame caches and solver binaries remain local; their registered result hashes are retained in `execution-timings.json`.
