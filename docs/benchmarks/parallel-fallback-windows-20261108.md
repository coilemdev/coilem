# Windows parallel fallback experiment

**Keeping real fallback solves in the native pool reduced average benchmark-worker wall time in both measured two-layer Phase F cases.**

Branch: `perf/parallel-fallback-solves`. Base: [`121f144f`](https://github.com/coilemdev/coilem/commit/121f144fa0c64471a30212e0ed4be125f849ba32). Measured code: [`1b4f7c33`](https://github.com/coilemdev/coilem/commit/1b4f7c33eba0c34fc8e11f1ffde193f38266f3cd).

## Change

When congruent-report synthesis fails, the retained derived mesh now feeds a real solve on the existing native ThreadPool, instead of solving synchronously in the result coordinator. Dynamic futures join the same wait, error and cancellation paths as initial jobs. Loaded/no-load pairing, angle-indexed results and reductions retain their order. Queued native jobs are also cancelled before joining runs that do not open a field pool.

The pool limit, native executable, equations, meshes, nonlinear settings and request grids are unchanged. This schedules the same native work; it does not add layer-aware reuse or reduce the number of solves.

## Paired Windows measurements

| Case | Baseline mean (range) | Branch mean (range) | Less wall time | Speedup |
| --- | ---: | ---: | ---: | ---: |
| Phase F 14p/12s drone | 92.39 s (88.65-96.13) | 65.88 s (61.87-69.89) | 28.69% | 1.40x |
| Phase F 12p/9s micro | 173.10 s (172.45-173.75) | 79.56 s (79.40-79.71) | 54.04% | 2.18x |

Each variant ran twice per case in a fresh process and data root. First pairs used baseline→candidate for drone and candidate→baseline for micro; repeats reversed those orders. These are eight observations, not confidence intervals. The requests are unchanged Newton copies retained from the earlier Phase F experiment.

The primary timer is the unchanged `backend.benchmark_suite.worker.measure` runtime, including numerical postprocessing and field extraction. HTTP transfer, browser rendering, durable public-run saving and playback drawing are excluded. Process-wall timings, which also include harness/startup/monitor overhead, are recorded separately in the JSON.

Host: AMD Ryzen 7 7700, 8 physical cores/16 logical processors, approximately 64 GiB RAM, Windows. The same frozen Rust executable and Python validation environment with orjson were used for every run. All jobs were sequential, with no competing tests/builds/comparers. Source, request and executable identities were checked before/after.

| Pair | Baseline | Branch | Fallbacks per run |
| --- | ---: | ---: | ---: |
| Phase F 14p/12s drone, 1 | 88.65 s | 61.87 s | 20 |
| Phase F 14p/12s drone, 2 | 96.13 s | 69.89 s | 20 |
| Phase F 12p/9s micro, 1 | 172.45 s | 79.71 s | 32 |
| Phase F 12p/9s micro, 2 | 173.75 s | 79.40 s | 32 |

## Memory

Highest sampled peaks across the two runs of each variant:

| Case | Baseline private commit | Branch private commit | Baseline summed working sets | Branch summed working sets |
| --- | ---: | ---: | ---: | ---: |
| Phase F 14p/12s drone | 13.98 GiB | 15.01 GiB | 7.63 GiB | 7.83 GiB |
| Phase F 12p/9s micro | 13.43 GiB | 15.91 GiB | 7.88 GiB | 8.87 GiB |

Private commit is not resident RAM, and summed working sets can count shared pages more than once. Samples were taken about every 0.5 s. The configured native pool size stayed at eight; the sampled peak native count was nine in baseline runs (inline fallback could run beside the pool) and eight on the branch. Increased overlap used more memory despite that cap.

## Output parity

All four baseline/branch comparisons passed: **2,246 retained result numerical values**, **461,880 cached aggregate numerical values**, **384 byte-identical mesh pairs**, **384 per-angle native report pairs**, **21,900,576 native A_z values** and **192 decoded full field-frame pairs**. Numerical differences were zero. Per-angle native reports matched after excluding execution timings and the run-specific input path/generation timestamps; fixture hashes and sizes remain compared. All exclusions are recorded in the JSON, with no waveform or physical-output tolerance introduced. Counts span four paired comparisons and include repeated measurements.

The cached numerical comparison covers the complete `sweep` block (including all torque/energy variants, loaded/no-load flux and back-EMF, harmonics and convergence), slot excitation frames, steel RMS, iron loss and its density. Only the sweep elapsed-time counter is excluded. Cached wrapper provenance and field artifact references are not claimed byte-identical; the referenced full frames are compared separately.

The benchmark worker retains native debug artifacts, so raw mesh/report/A_z comparisons are available here. Playback pixels were not generated or compared in this experiment.

## Validation and limits

- Python: 1,905 passed, 3 skipped, across the full run and documented environment retries. Five new regressions cover concurrent fallback starts, dynamic future draining, paired reports and ordered frames, failure propagation, and cancellation before joining the no-field-pool path.
- Seven setup failures were Windows path-length limits; one was socket-buffer exhaustion. Targeted retries passed with a shorter temporary path after the machine restart. Two source-provenance tests passed separately without the external-binary override they intentionally reject.
- Ruff and snapshot technical/publication checks passed.
- Two affected Windows workflows were measured. The full A-D/F/E collection and independent FEMM/two-platform release qualification were not rerun.
- Single-layer cases and excitation modes that disable solution reuse have no demonstrated benefit from this experiment. In particular, the prior six-step UI outrunner profile does not exercise this fallback.

Peak sampled private commit and summed working sets are in the JSON. Private commit is not resident RAM, and summed working sets can count shared pages more than once. Samples were taken about every 0.5 s; concurrency can change peak memory.

Native executable SHA-256: `7eecdf0e301fb386a6a135331eb6bb13a214553590ff59beed4fc38d73a1beb7`.

The [machine-readable report](parallel-fallback-windows-20261108.json) includes every run, source/config hashes, paired timings, sampled memory and parity counts. Full logs and retained artifacts remain local.

## Parent-stack integration

The measurements compare historical base `121f144f` with measured code `1b4f7c33`; parent `4691c48c` was subsequently merged in `5584a769`. Integration checks confirmed unchanged measured solver/process-pool/native-adapter sources and identical resolved configurations for all eight explicit-Newton requests. Timings were not rerun after integration.

The integrated tree passed 1,926 Python tests with 3 skipped (1,924 in the full run and two source-provenance checks in their required environment). Ruff and the final snapshot publication check passed.
