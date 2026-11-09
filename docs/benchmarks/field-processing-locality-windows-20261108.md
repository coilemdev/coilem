# Windows field-processing locality experiment

**The final branch reduced saved-result wall time by 9.6% for the outrunner and 11.4% for the Prius in these paired runs. All 2,018 compared numerical values, 104 decoded full field frames and 624 playback image files matched their baselines.**

Branch: `perf/field-processing-locality`. Base: [`a2dd22f2`](https://github.com/coilemdev/coilem/commit/a2dd22f2089fc1c3a8170008afba8f3106943222). Measured code: [`0230ceed`](https://github.com/coilemdev/coilem/commit/0230ceed24904c194553d88057e4ae3a10fe7df9).

## Change

Field jobs receive immutable saved-report references, including the original rotation recipe for congruent angles. They start when the loaded report and any requested no-load partner arrive, while later native solves continue. The coordinator waits on both native and field futures, propagates failures/cancellation, and retains angle order for numerical reductions and live previews. Native processes remain tracked in the parent; field workers use spawn and stay registered until joined. Unpersisted reports and the serial/pool-disabled route retain dictionary inputs.

Rust equations, mesh generation, nonlinear settings and request grids were retained. The source changes concern Python scheduling, report transport and worker lifetime.

## Final paired measurements

| Case | Baseline result ready | Branch result ready | Less wall time | Baseline all playback ready | Branch all playback ready |
| --- | ---: | ---: | ---: | ---: | ---: |
| SPM outrunner 14p/12s | 116.73 s | 105.56 s | 9.57% | 141.78 s | 131.26 s |
| Pyleecan Prius loaded torque | 65.65 s | 58.17 s | 11.40% | 75.56 s | 67.70 s |

The actual `solve_stream` handler was consumed directly through its asynchronous callback/timer loop (at most 10 ms polling delay). Solving, packaging, saving and automatic playback are included; HTTP transfer and browser rendering are excluded. Runs were sequential, with fresh processes/data roots and no competing test/build jobs. Requests were checked identical within each pair.

Host: AMD Ryzen 7 7700, 8 cores/16 logical processors, approximately 64 GiB RAM, Windows build 26200. Both variants used Python 3.13.9, orjson 3.13.0, NumPy 2.4.6, Gmsh 4.15.2 and Pillow 12.3.0, with the same frozen Rust executable.

The two unchanged outrunner controls took 115.96 and 116.73 s. An earlier overlapping prototype took 105.36 s; the final coordinator took 105.56 s. File-reference transport alone took 115.68 s, which did not establish a standalone speedup. These are a small number of observations, not confidence intervals or a cross-platform performance claim.

## Output checks

| Case | Numerical values (maximum difference 0) | Equal decoded full frames | Byte-identical WebP files |
| --- | ---: | ---: | ---: |
| SPM outrunner 14p/12s | 1260 | 72 | 432 |
| Pyleecan Prius loaded torque | 758 | 32 | 192 |

Compared numerical summaries, torque/current/back-EMF waveforms and cogging data where present; elapsed-time bookkeeping was excluded. Complete decoded frame payloads include retained numerical field data and contours. Playback had no recorded rendering errors. The normal public saved-run path deletes raw native debug reports and meshes, so this study makes no additional raw A_z or native-mesh byte-comparison claim.

## Timing and memory interpretation

After overlap, `field_frame_extract` measures the **remaining post-native field-processing tail**, including iron loss. The timer label now says so. The shorter tail does not mean field-processing CPU was halved; native solves and field processing share CPU, and some native-stage wall time increases. Whole-run saved-result and all-playback times are the performance comparisons.

| Case | Baseline peak private commit | Branch peak private commit | Baseline summed working sets | Branch summed working sets |
| --- | ---: | ---: | ---: | ---: |
| SPM outrunner 14p/12s | 15.94 GiB | 16.46 GiB | 9.83 GiB | 10.29 GiB |
| Pyleecan Prius loaded torque | 10.84 GiB | 12.11 GiB | 4.77 GiB | 4.93 GiB |

Memory was sampled at approximately 0.5 s intervals. Private commit is not resident RAM, and summed working sets can count shared pages more than once. Increased concurrency is a tradeoff; small-memory and other platform hosts still need measurement.

## Validation and scope

- Python suite: 1,900 passed, 3 skipped, across the full run and corrected environment-dependent retries. Git/Node were added to the hidden runner PATH; two source-registry tests were retried without the external-binary override they deliberately reject. No application changes were needed for those setup failures.
- 22 new regressions cover real spawn/file-input parity, congruent transforms, no-load layers, live frames, RMS/stator data, malformed inputs, joined workers, both partner-arrival orders, eager/out-of-order dispatch, serial fallback and prompt failure observation.
- Ruff and snapshot technical/publication checks passed.
- This Windows experiment covers two representative UI workflows. The full A-D/F/E collection and cross-platform performance were not rerun on this branch. It does not supply new independent FEMM or two-platform release qualification.

## Reproducibility

The cases use the public `spm_outrunner_14p12s.coilem` and `prius-2004-loaded-torque-v1.coilem` examples with Newton selected. Exact request hashes, source hashes, timing counters, sampled memory and validation outcomes are in the [machine-readable report](field-processing-locality-windows-20261108.json). Full event logs, requests/results, comparison inventories and field/playback artifacts are retained locally.

Native executable SHA-256: `7eecdf0e301fb386a6a135331eb6bb13a214553590ff59beed4fc38d73a1beb7`.
