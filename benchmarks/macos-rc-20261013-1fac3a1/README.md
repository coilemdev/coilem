# macOS benchmark report v1.7: the frozen 0.3.0 commit

[Generated PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown results](benchmark_report.md), [JSON numerical evidence](benchmark_summary.json), [comparison with v1.5](comparison-to-v1.5.json), [elapsed job timings](execution-timings.json), [publication provenance](publication.json) and [artifact hashes](artifact_manifest.json).

This full A/B/C/D run measures the frozen coilEM 0.3.0 commit `1fac3a17fca7501d054a12b64b4a0472916ade98` on macOS. That commit is the head of PR #28, declared on #46 after the 0.3 QA fixes. The outcome is **29 PASS and one planned UNSUPPORTED Prius fixture, with all 42 BLDC gates passing**. All 35 supported native jobs were run fresh. Reference comparisons reuse the unchanged, frozen, data-only FEMM bundle; no reference solves were executed.

The candidate is `main` at `750d458` plus the 0.3.0 release commits, with application version coilEM 0.3.0 and native solver Magneto2D 0.3.3.

**What changed since v1.5:** since [macOS report v1.5](../macos-rc-20261013-04f87a5/README.md) at the previous pin `04f87a5`, the only changes are the 0.3 QA fixes in stack #65 (#56–#68, fixing #51–#55, #58, #59 and #62) and their release notes. None of them changes a benchmark input or numerical path:
- the benchmark fixtures use the custom plan, which Preview's Back-EMF grid change (#58) does not touch;
- the other fixes concern the UI, the PDF report and launcher shutdown.

Report v1.6 is the Windows record of `04f87a5` (PR #50).

## Comparison with v1.5

Both runs used the same Apple M4, macOS 15.7.3, Python 3.12.13 and rustc 1.94.0. **Every numerical value is identical to v1.5.** That covers all 30 rows, including:
- the native measurements;
- every gate evaluation;
- the mesh element counts;
- the Phase D standard, fine and analytical runs.

[`comparison-to-v1.5.json`](comparison-to-v1.5.json) records this check. It compares each row's measurements and evaluation exactly, ignoring only solve and CPU times, timestamps and the scrubbed local cache path. All 30 verdicts and every gate status are retained, the selection and protocol are unchanged, and the four BLDC cases keep all 42 gates passing.

These results confirm that the frozen 0.3.0 commit keeps the existing fixture metrics. They do not extend geometry coverage or change the developer-preview qualification policy. Prius remains outside public HoleM50 support and was not solved.

## Recorded timings

Native execution took **56.64 minutes**, against 56.55 minutes for v1.5 on the same machine. Each record is one pass, so per-job differences of a few percent are run-to-run noise.

| Phase | Native jobs | v1.5 summed job time | v1.7 summed job time |
| --- | ---: | ---: | ---: |
| A | 10 | 8.23 min | 8.67 min |
| B | 12 | 33.06 min | 32.79 min |
| C | 4 | 7.32 min | 6.99 min |
| D | 9 | 7.91 min | 8.17 min |

The largest single difference is `spm_4p12s_simple_noload__baseline` at 51.6 s, against 41.1 s in v1.5. It is flagged as an outlier, not re-run, because light documentation work ran on the same machine during the pass.

The CLI measures meshing, native field solving, field-frame extraction and result construction. Public HTTP playback packaging and durable UI run saving are outside this benchmark.

## Runtime and reproduction

`benchmark_summary.json` retains the exact runtime:
- the commit, source hash `c8279a44bda1…` and native binary hash `b5a2ac6c3903…`;
- macOS-15.7.3-arm64-arm-64bit, Python 3.12.13 and the locked dependencies;
- harness 1.2.1, protocol 1.1.0 and the reference provenance.

Magneto2D was built from the frozen tree with `cargo build --release --locked` (rustc 1.94.0). The binary hash differs from v1.5's although the Magneto2D source is unchanged, because the build directory differs. The run used a clean checkout of the frozen commit with no process-pool overrides set.

```sh
git checkout 1fac3a17fca7501d054a12b64b4a0472916ade98
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
unset COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL \
  COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL
PYTHONPATH="$PWD" .venv/bin/python -m tools.run_benchmarks \
  --suite benchmarks/abcd-v1.1/benchmark_spec.json \
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 \
  --phases A B C D \
  --out-dir ../benchmark-output/macos-rc-1fac3a1 \
  --pdf
```

Use a new output directory. A full run writes about 25 GB of per-job solve caches. Each job's cache was deleted once the job had recorded its result, to keep disk use bounded; the report never reads those caches.

The owner asked for the benchmark to be re-run on both platforms at the new freeze. The Windows run of this commit is recorded separately.

## Publication

The generated PDF is committed byte-for-byte unchanged, and its SHA-256 matches the original report artifact. Its fixture hyperlinks keep the originating local report paths; the HTML and Markdown versions link to the committed fixture JSON files.

Published text and JSON replace the local run root with `<run-root>` and omit worker PIDs, while keeping all numerical values and identities. CSV, worker logs, raw job evidence, mesh and frame caches and solver binaries stay local; their registered result hashes are kept in `execution-timings.json`.
