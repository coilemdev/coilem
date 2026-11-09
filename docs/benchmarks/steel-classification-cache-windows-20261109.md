# Windows steel-region classification cache experiment

**The isolated steel RMS update became about 4.8 times faster on two real field frames. These whole-job measurements do not establish a total solve-time improvement.**

Branch: `perf/steel-region-classification`. Base: [`5e140b90`](https://github.com/coilemdev/coilem/commit/5e140b90a97dfd6fc3caf43c1a25fbfd8695e2cd). Measured code: [`2e0db171`](https://github.com/coilemdev/coilem/commit/2e0db1714bbfdd6d926ea1ec0b74a30a10f633f5).

## Change

Each steel RMS update keeps a local dictionary for the first 128 distinct exact built-in string labels. Both steel buckets and non-steel results are cached. The dictionary is discarded after the frame. Non-string objects and string subclasses retain the original truthiness/string conversion and exception behavior. Geometry, triangle-area calculations, field magnitudes and accumulation order are unchanged. Shared iron-loss classifier callers retain their previous implementation.

## Isolated RMS function

Real retained field frames were decoded before timing. Each variant warmed up once, then ran seven times in alternating order on the same frame object. Accumulator initialization, finalization and explicit garbage collection were outside the timer. Every raw accumulator and final RMS value matched exactly.

| Source frame | Triangles | Baseline mean | Cached mean | Less RMS-update time | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: |
| spm_outer_14p12s_drone__baseline (loaded) | 103,402 | 238.98 ms | 49.94 ms | 79.10% | 4.79x |
| spm_outer_12p9s_micro__baseline (loaded) | 124,060 | 291.68 ms | 59.88 ms | 79.47% | 4.87x |

## Complete benchmark worker

Four sequential fresh-process/data-root jobs used the same explicit-Newton Phase F micro request, frozen Rust executable and unchanged worker budgets. Order was baseline, candidate, candidate repeat, baseline repeat. Tests, builds and artifact comparers did not compete with timing.

| Pair | Baseline | Cached |
| --- | ---: | ---: |
| 1 | 78.73 s | 80.56 s |
| 2 | 79.88 s | 79.35 s |
| Mean | 79.30 s | 79.95 s |

The cached mean was **0.82% longer**. This is a small four-run sample with ordinary run variation, so it does not establish a whole-job speedup. The function-level gain should not be advertised as a solver-time gain.

The primary measurement is the unchanged `backend.benchmark_suite.worker.measure` runtime, including numerical postprocessing and field extraction. Public-run saving, HTTP transfer, browser rendering and playback drawing are excluded. Host: AMD Ryzen 7 7700, 8 physical cores/16 logical processors, approximately 64 GiB RAM, Windows.

## Parity and validation

Both strict worker comparisons passed: 1,096 retained result numerical values, 247,956 cached aggregate values, 192 byte-identical mesh pairs, 192 per-angle native report pairs, 11,942,132 native A_z values and 96 decoded full frame pairs matched. Numerical differences were zero. Explicit elapsed-time/run-path/timestamp exclusions are recorded; native fixture hashes and sizes remain checked.

Cached aggregate checks include the complete sweep except its elapsed counter, slot excitation frames, steel RMS, iron loss and loss density. Wrapper provenance/artifact references are not claimed byte-identical; referenced full frames are checked separately.

- 14 new regressions passed: exact numerical equivalence, positive/negative hits, raw normalization variants, bounded admission, per-call lifetime, stateful/unhashable inputs and normalization failures.
- 54 related postsolve, iron-loss and spawned field-worker regressions passed.
- Ruff and snapshot technical/publication checks passed. The full Python suite was not rerun for this local optimization.
- No complete A-D/F/E rerun, new FEMM grading or two-platform release qualification.

Per-run sampled memory counters are retained in the JSON. Private commit is not resident RAM; summed working sets can count shared pages more than once. The classification cache retains no more than 128 label/result entries for a single frame.

The [machine-readable report](steel-classification-cache-windows-20261109.json) includes all timing samples, exact module/config identities, memory counters and parity outcomes. Full raw evidence remains local.
