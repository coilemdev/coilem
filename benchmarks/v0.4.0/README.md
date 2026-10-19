# v0.4.0 benchmark evidence for release planning

This report compiles the completed evidence available on October 18, 2026.
It is the starting point for the [v0.4.0 release plan](../../docs/RELEASE_0_4_0.md),
not a claim that an unmeasured future tag has passed qualification. The
application still identifies as 0.3.1; measured commits are retained below.

## Complete A/B/C/D evidence

| Phase | Native outcome | Fresh FEMM repeat |
| --- | --- | --- |
| A: SPM | 10 PASS | 10/10 exact physical results and extraction audits |
| B: IPM | 11 PASS, 1 YELLOW | 12/12 exact |
| C: distributed winding | 4 PASS, planned unsupported Prius | 4/4 supported cases exact |
| D: BLDC | 3 PASS; 42/42 gates | 3/3 exact |

The native run completed all **35 supported jobs** at clean `f390b25`, with
**28 PASS, 1 YELLOW, 1 planned UNSUPPORTED**. It used the Precise mesh default,
release Magneto2D binary, harness 1.5.0 and protocol 1.3.0. Every recorded gate,
verdict and numerical value matches the preceding Windows v3 report exactly.

The fresh **29-case FEMM 4.2** run used the current-main scheduler at clean
`0417736`, with the pinned private FEMM producer and explicit current-main
request/source compatibility checks. Full physical payloads and both flux and
source extraction audits match both the October 16 repeat and original frozen
v3 evidence exactly. Only execution timestamps, cache paths and timing fields
are excluded from the physical comparison.

These are separately collected native and reference runs. The native report
read the registered frozen v3 bundle; the later FEMM run verifies that its
reference physics remains exact. No new native fields or qualification verdicts
were generated while assembling this report.

## Full reports and reproducible artifacts

- [Full 64-page native plot PDF](../windows-native-20261018-f390b25/coilem_benchmark_report.pdf),
  [HTML plots](../windows-native-20261018-f390b25/coilem_benchmark_report.html),
  [native gate report](../windows-native-20261018-f390b25/benchmark_report.md),
  [complete numerical JSON](../windows-native-20261018-f390b25/benchmark_summary.json),
  [results CSV](../windows-native-20261018-f390b25/benchmark_results.csv),
  [fixture inputs](../windows-native-20261018-f390b25/fixtures/), and
  [native provenance/integrity record](../windows-native-20261018-f390b25/README.md).
- [Fresh FEMM report, phase and per-case timing tables](../femm-main-20261018-0417736/README.md),
  [per-case physical comparison](../femm-main-20261018-0417736/comparison.json),
  [concurrency checks](../femm-main-20261018-0417736/concurrency-check.json),
  [owned-session audit](../femm-main-20261018-0417736/ownership-audit.json), and
  [publication provenance and checksums](../femm-main-20261018-0417736/publication.json).
- [Registered suite and reproduction commands](../abcd-v1.3/README.md),
  [Windows qualification record](../records/windows-x86_64.json), and
  [reference v3 registry](../reference-baselines/ipm-high-output-v3/manifest.json).

The PDF is the original native report, copied byte-for-byte with its measured
commit, frozen-reference label, YELLOW result and all 36 fixture links intact.
It is not restamped as a new v0.4.0 field solve.

## Observed timings

| Collection | October 18 | Earlier observation |
| --- | ---: | ---: |
| Native, including harness startup and report generation | 41m54.5s | 43m40s on October 16 |
| FEMM reference collection | 1h49m05s | 1h50m54s on October 16 |

The FEMM repeat is **109.63 seconds / 1.65% faster**. Phase worker-duration
changes are A -0.27%, B -0.91%, C -3.13% and D +4.73%; individual cases vary.
Worker sums overlap and are not elapsed phase wall times. These are single-host
observations, not a controlled statistical speed claim. The two collections
were separate stages, not one measured end-to-end release workflow.

## Limits and work before the final release report

The V-shape baseline remains YELLOW for its 14.778701% peak back-EMF amplitude
difference. Existing steel-B/core-loss, Kt/current-base, peak-B sampling and
near-zero no-load relative-ripple limitations remain. The reference bundle's
scientific status is REVIEW_REQUIRED. Keep reference v3 and protocol 1.3.0;
this repeat does not introduce a v4 scientific reference or qualify Fast mesh.

The legacy Prius row is still unsupported. Pyleecan Prius software reproduction
[#126](https://github.com/coilemdev/coilem/issues/126) and the separate ORNL
hardware work [#69](https://github.com/coilemdev/coilem/issues/69) /
[#82](https://github.com/coilemdev/coilem/issues/82) need their own model IDs,
matching references, refinement evidence, full curves and release-candidate
reports. Their outcomes cannot be inferred from the 29 supported FEMM cases.

The macOS record predates the changed mesh source and is currently
NOT_COMPARABLE; Linux full numerical parity and Python 3.15 full numerical
coverage are not established by these Windows measurements. Complete the
release plan's scope, version, frozen-candidate benchmarks, wheel checks and
platform walkthroughs before tagging v0.4.0.
