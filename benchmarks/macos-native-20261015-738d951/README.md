# macOS native Magneto2D A/B/C/D collection for the PR #100 FEMM v3 comparison

[HTML plots](coilem_benchmark_report.html), [Markdown gate report](benchmark_report.md), [JSON results](benchmark_summary.json), [per-case fixtures](fixtures/), [run manifest](run_manifest.json), [timings](timings.json), [environment](environment.json), [original evidence hashes](evidence-hashes.json).

This is the native half of the [PR #100 v3 handoff](../pr100-v3-handoff/README.md). It measures the clean, frozen pin **`738d9516e8500c5996c772bd96470472cbb9a0f9`**, the same pin as the Windows FEMM v3 reference run, with harness 1.3.0, protocol 1.1.0 and `--phases A B C D --no-reference`. Nothing here is a FEMM parity result: A/B/C stay `NOT_COMPARED` until the v3 bundle exists.

## Outcome

All **35 supported native jobs COMPLETE**; the planned Prius case is UNSUPPORTED. The run manifest status is `COMPLETE` and the harness exited 1 because it recorded failed gates.

| Phase | Result |
| --- | --- |
| A: SPM | 10 NOT_COMPARED |
| B: IPM | 12 NOT_COMPARED |
| C: distributed winding | 4 NOT_COMPARED; Prius planned UNSUPPORTED |
| D: ideal six-step BLDC | 2 FAIL (`spm_14p12s_high_pole`, `spm_8p12s_reference`); `spm_4p12s_small` NOT_COMPARED |

Every native-only six-step gate passes for all three D cases: power/torque discriminator, standard-to-fine mean torque and ripple, and current properties. The only failures are the historical fixed-axis **golden current sequence** gates on the two tooth-coil fixtures, in all three stages: the sequence differs from the frozen table at **45.0 degrees** (14p12s) and **30.0 degrees** (8p12s). This is the current-frame limitation the handoff describes: PR #100 measures commutation from the winding's phase-A axis while the old validator selects sectors from the unadjusted angle. `spm_4p12s_small` is not wound with tooth coils and matches the golden table in every stage. These FAILs are retained, not reinterpreted.

| Six-step gate (limit) | 14p12s | 4p12s small | 8p12s reference |
| --- | ---: | ---: | ---: |
| power/torque delta, % (10) | 0.549 | 0.279 | 0.411 |
| standard-to-fine mean torque, % (2) | 0.036 | 0.186 | 0.012 |
| standard-to-fine ripple, pp (5.0) | 0.005 | 0.398 | 0.022 |

The 8p12s standard-to-fine ripple difference here is 0.022 pp at this pin. The historical #80 native record (5.0340562459 pp FAIL, [Windows full-turn comparison](../windows-flux-credit-20261014-1ea9e40/README.md)) is unchanged and remains that pin's result.

## Comparing against FEMM v3

- **Quick review:** compare each v3 record with the matching `fixtures/<case>__<stage>.json` or the `rows` in `benchmark_summary.json` (summary quantities plus torque and Back-EMF waveforms per case).
- **Formal join:** run the handoff's report-only tool (`tools/report_benchmark_against_reference.py`) against the original native output, not this folder. It verifies every native request/result hash in `run_manifest.json`, and those raw files stay on the measuring Mac (see below). Once the complete `ipm-high-output-v3` bundle (29 records plus manifest, reference commit `738d951…`) is available, the join runs there in a new output directory without any field solves.

## Publication

Copied from the run's `report/` directory: Markdown, HTML, JSON summary, artifact manifest and fixture JSON. In `benchmark_summary.json` and the fixtures, the native output directory's absolute path (in `solve_cache_dir`) is replaced with `<native-out>`; numbers and verdicts are unchanged. `run_manifest.json` is byte-identical. `evidence-hashes.json` lists the sha256 of the original files, including every job's `request.json` and `result.json`. The original PDF and CSV, worker logs, raw request/result files and per-angle solver caches (about 12 GB stored compressed) are kept locally; raw results embed local paths, and editing them would break the hash checks.

## Timing and environment

Job wall time totals **2850.1 s**: A 758.6 s, B 1398.1 s, C 277.3 s, D 416.1 s ([per job](timings.json)). The locked release build took 1m 18s. A free-disk guard paused the run three times; each resume used the same arguments plus `--resume`, and the harness re-verified source, binary and dependency identities. Another solve shared the CPU during phase A, so timings are indicative only.

macOS 15.7.3 on Apple M4 (10 cores, 16 GiB), Python 3.12.13 with `requirements.lock`, rustc/cargo 1.94.0, release binary sha256 `523108a287d71c34ba254f722d2e0766d2b1629a05eabbe7916a0885055aa729`; no process-pool overrides. Finished job directories were stored with APFS transparent compression after every file's sha256 matched; bytes are unchanged and `--resume` accepted them.

This is diagnostic evidence for the v3 comparison. It is not release qualification.
