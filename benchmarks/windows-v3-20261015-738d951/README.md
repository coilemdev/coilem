# Windows Magneto2D versus FEMM v3 at the PR #100 measured pin

[64-page PDF with plots](coilem_benchmark_report.pdf), [interactive HTML plots](coilem_benchmark_report.html), [Markdown gate report](benchmark_report.md), [full results JSON](benchmark_summary.json), [fixture configurations](fixtures/), [comparison provenance](comparison_manifest.json), [publication provenance](publication.json), [original evidence hashes](evidence-hashes.json), [environment](environment.json), [timings](timings.json).

Both solvers measured the clean pin **`738d9516e8500c5996c772bd96470472cbb9a0f9`**. All **29 Windows FEMM cases** and **35 supported Windows Magneto2D jobs** completed. The planned Prius case is unsupported. The [complete FEMM v3 reference bundle](../reference-baselines/ipm-high-output-v3/manifest.json) is unchanged. This publication adds no field solves.

## Result and remaining review

| Phase | Evaluated outcomes |
| --- | --- |
| A: SPM | 10 PASS |
| B: IPM | 11 PASS, 1 YELLOW |
| C: distributed winding | 4 PASS, 1 planned unsupported Prius |
| D: BLDC | 3 PASS |

Overall: **28 PASS, 1 YELLOW, 1 unsupported**. The V-shape baseline remains YELLOW because its peak Back-EMF differs by **14.778701363798104%**; its fundamental differs by 2.0562933199286557%, mean torque by 5.845430431801066%, and voltage waveform NRMSE is 12.650758033355352%. No waveforms were phase-, sign- or scale-fitted.

This is benchmark evidence, not release qualification. FEMM v3 retains `validation_status: REVIEW_REQUIRED`. Sparse first-position steel-B/core-loss estimates, differing Kt/current-base and peak-B sampling definitions, unavailable native loss/efficiency evidence, and near-zero no-load relative ripple still require the scientific-review limitations recorded in the [FEMM handoff](https://github.com/coilemdev/coilem/pull/100#issuecomment-6186258692). Windows versus published Mac numbers were reviewed separately; this package is the formal join against original **Windows** raw evidence and does not claim a raw-evidence join on the Mac publication.

## Measured contract versus evaluation contract

The native fields were measured with **harness 1.3.0 / protocol 1.1.0** at `738d951`. The saved measurements were subsequently re-evaluated with **harness 1.4.0 / evaluation protocol 1.3.0**, using clean evaluator commit **`8a4eb25ec47ae0d5799323a0722a866ea792e7dd`**. The separate evaluation contract and file hashes are recorded in `comparison_manifest.json`. This correction was registered **after** collecting the fields; it is explicitly post hoc.

Both FEMM and Coilem already used public-clockwise-v2 coordinates and the same geometry-defined phase-A commutation frame. Protocol 1.1.0's validator still interpreted the golden table in a fixed global frame. Protocol 1.3.0 registers geometry offsets of **15, 0 and 30 electrical degrees** for the three D fixtures. See the [contract and report-only replay command](../abcd-v1.3/README.md).

| D fixture | Historical fixed-axis outcome | Reconciled outcome | Standard/fine ripple delta, pp |
| --- | --- | --- | ---: |
| 14p12s high pole | FAIL | PASS | 0.005392347866436609 |
| 4p12s small | PASS | PASS | 0.39649663914045874 |
| 8p12s reference | FAIL | PASS | 0.015555017105015168 |

Every D row preserves `historical_evaluation` and `historical_protocol`, including the original failed golden-current checks. The original comparison's totals were 26 PASS, 1 YELLOW, 2 FAIL and 1 unsupported. Every physical value, waveform and non-golden numerical gate value is identical across these two evaluations. The **5.0-point ripple limit** and historical [#80 5.0340562459-point FAIL](../windows-flux-credit-20261014-1ea9e40/README.md) remain unchanged. No finer sweeps were performed.

## Provenance, runtime and publication

The original native requests/results, source identities and reference hashes were verified by the report-only tool before and after rendering, and again before packaging. All 145 measured source-file hashes are retained in the manifests. The original native run manifest is published byte-for-byte unchanged. The FEMM v3 manifest SHA256 is `b5178463b9746ea2ca7604ab24b97f221905e495bcfa22bc5169c7f7a9fd4008`; bundle digest is `95450ffcb909ed20caf514548f741c15611087a3482657c87add4255b308ba63`.

Windows 11 Home build 26200, Ryzen 7 7700 (8 physical / 16 logical cores), 64 GiB RAM, Python 3.12.14, rustc/cargo 1.95.0. All 29 locked runtime dependency pins matched. Magneto2D's release binary SHA256 is `e74510d91a93c6a290ce1544e21e695adb47ec44cf24e84297c2b15890ea2f9d`. No process-pool overrides were applied. FEMM product version 4.2.0.0 and pyFEMM 0.1.3 generated the reference fields.

The native collection ran **11:54:49-12:40:26 UTC on October 15, 2026**, **2737.385797 seconds (45m37s)** wall time. Successful-job runtime sums to 2655.022870800065 seconds; the wall duration also includes harness overhead. The FEMM collection's case runtime was 32907.4597 seconds (9.141 hours). These are observational execution times, not a controlled performance ratio.

Published JSON/HTML replaces only local cache-directory roots; all numerical values and verdicts are preserved. The PDF's 36 fixture-link annotations point to the committed PR fixtures; its 64 page-content streams and extracted text are identical to the reviewed original. The original and published PDF hashes are both recorded in `publication.json`. All pages were rendered again for publication QA.

`artifact_manifest.json` hashes the published files. `evidence-hashes.json` separately identifies the original report files and native request/result bytes. Original raw request/result files, worker logs, CSV and solver caches remain local and unchanged. The redacted report copies do not replace those original files for formal hash verification or resume. No physics, inputs, grids, limits, historical reports or reference records were edited for publication.
