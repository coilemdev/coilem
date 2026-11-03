# macOS A/B/C/D at the 0.5.0 development stack top (5b7cad8)

[64-page PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown gate report](benchmark_report.md), [CSV](benchmark_results.csv), [JSON results](benchmark_summary.json), [per-case fixtures](fixtures/), [run manifest](run_manifest.json), [timings](timings.json), [environment](environment.json), [original evidence hashes](evidence-hashes.json), [comparison with v0.4.0](comparison-vs-v0.4.0-windows-5b6cb61.md).

The run measures commit **`5b7cad88c43c0ac7ade9265988f71b6f2ba2884f`** on macOS arm64. That commit is the top of the 0.5.0 performance stack: the convergence fix, losses, d/q, maps, magnet temperature, the shoed-slot current fix and the Torque–speed exports. It uses harness 1.7.0 with the default protocol 1.4.0 against the frozen FEMM v3 bundle. This is **development evidence, not release qualification**: the 0.5.0 freeze reruns A/B/C/D on macOS and Windows and registers the qualified record.

## Outcome

**29 PASS and the planned unsupported legacy ORNL Prius.** All 35 supported jobs completed. The Phase D BLDC gates are unchanged.

## Compared with v0.4.0

The v0.4.0 baseline is the [Windows collection at 5b6cb61](../windows-prius-requal-20261018/README.md): 28 PASS, 1 YELLOW and the Prius. Every case is in [the comparison](comparison-vs-v0.4.0-windows-5b6cb61.md). By group:

| Group | Cases | Mean torque error vs FEMM | Worst torque error | Mean back-EMF error |
| --- | ---: | --- | --- | --- |
| A, SPM | 8 | 0.27% → 0.33% | 0.48% → 0.63% | 0.07% → 0.08% |
| B, flat IPM | 6 | 0.34% → 0.31% | 0.64% → 0.66% | 0.33% → 0.30% |
| B, V-shape IPM | 6 | 4.55% → 5.13% | 5.90% → 7.05% | 2.39% → 6.50% |
| C, distributed | 4 | 2.67% → 2.87% | 4.90% → 5.20% | 0.18% → 0.23% |

Two changes account for the shifts. The macOS 738d951 column in the comparison shows that platform differences are at most about 0.1%.

- **Slot current from each coil side's meshed area.** Plain slots used to receive 0.2–0.5% more than N·I/paths, so loaded torque falls by that much. Back-EMF is unchanged. Torque–λdq agreement moves toward 100% in every loaded case: it now reads 99.86–100.29%.
- **The Newton stopping fix (public issue 11, PR 155).** On the weak-flux V-shape IPMs (about 2 V), back-EMF rises 4.7–6.6% and torque 0.2–1.1%, both away from FEMM. Five V-shape cases now sit 8.1–8.6% from FEMM on the back-EMF fundamental and 9.0–9.6% on the peak, against 10% gates. `ipm_vshape_8p12s_baseline_contract` changes from YELLOW to PASS because its converged waveform's peak error falls from 14.8% to 9.0%. The freeze should check how FEMM converges on these bridges.

## Publication

These files are copied from the run's `report/` directory. In `benchmark_summary.json`, the HTML report and the fixtures, the native output directory's absolute path (in `solve_cache_dir`) is replaced with `<native-out>`; numbers and verdicts are unchanged. `run_manifest.json`, the PDF and the other copied files are byte-identical.

`evidence-hashes.json` lists the sha256 of the original files, including every job's `request.json` and `result.json`. The raw per-job files and solver caches stay on the measuring Mac.

The run was registered with `--allow-dirty` because of two untracked files outside the source. All 165 registered source files hash-match 5b7cad8.

## Timing and environment

Job wall time is A 570 s, B 2085 s without `ipm_vshape_8p12s_deep_apex_high_output_v1`, C 536 s and D 763 s ([per job](timings.json)). That one job's 13,223 s includes about 3.5 h with the Mac asleep, lid closed on battery; its solver recorded 350.9 s.

The machine is macOS 15.7.3 on Apple M4 (10 cores, 16 GiB), with Python 3.12.13 and `requirements.lock`, and rustc/cargo 1.94.0. The release binary sha256 is `1d23ea8f…67fe7c`, and no process-pool overrides were set. A QA app shared the CPU during part of the run, so timings are indicative only.
