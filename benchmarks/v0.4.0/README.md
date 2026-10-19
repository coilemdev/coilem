# v0.4.0 benchmark evidence for release planning

This report compiles the completed evidence available on October 18, 2026.
It is the starting point for the [v0.4.0 release plan](../../docs/RELEASE_0_4_0.md),
not a claim that an unmeasured future tag has passed qualification. The
application still identifies as 0.3.1; measured commits are retained below.

## Pyleecan Prius development benchmark (#126)

The [complete versioned report](../../docs/benchmarks/pyleecan-prius-v1/README.md)
adds the exact pinned software model in two normal-workspace examples. The clean
Windows collection at `d993d76` completed **17 jobs and 568 field reports**, with
**10/10 original software checks passing**. Both cases preserve their analytic
geometry, winding, materials and source/case IDs through save and reopen.

| Case | Fresh app | Retained matching software reference |
| --- | ---: | ---: |
| Tutorial, 1000 rpm / 20°C / zero current | 107.513838 V line RMS | 107.558193 V; −0.0412% |
| Loaded, 2000 rpm / 60°C / 250 A peak / Φ₀=140° | 353.950530 Nm | 354.953115 Nm FEMM control; −0.2825% |

[Every torque-angle point and control](../../docs/benchmarks/pyleecan-prius-v1/app-results.md),
[full numerical data and hashes](../../docs/benchmarks/pyleecan-prius-v1/app-results.json),
[comparison plots](../../docs/benchmarks/pyleecan-prius-v1/app-results.svg), and
[workspace validation](../../docs/benchmarks/pyleecan-prius-v1/workflow-validation.json)
retain their own identities. The largest app/FEMM mean difference over all
thirteen angles is 0.6282% of FEMM peak. The upstream table still differs by
11.445109 Nm RMS, including 90° and 180° discrepancies. Angular/Fine controls
change the loaded mean by +0.001441/−0.016741 Nm. Fine adds only 7.2% triangles
in this model, so this is a bounded sensitivity check.

Software agreement does not resolve hardware accuracy: the tutorial model's
1000 rpm RMS remains 25.45% above the registered ORNL value, with different
magnet/oil temperature information and model assumptions. The legacy ORNL
matrix row and separate #69/#82 work are unchanged. #126 still requires the
actual final v0.4.0 candidate rerun; these are development measurements.

## Fresh A/B/C/D regression after the Prius changes

The [new complete native collection](../windows-prius-requal-20261018/README.md) measures clean
`5b6cb61` after the exact Prius model changed shared meshing, excitation and
flux extraction. All **35 supported jobs** complete with **28 PASS, 1 YELLOW
and one planned unsupported legacy ORNL Prius**. Every recorded verdict,
gate and numerical value is **exactly identical** to the earlier `f390b25`
Windows report. The [current Windows record](../records/windows-x86_64.json)
now retains all **53** measured physics sources; the historical macOS record
keeps its original 50-file guard and reports NOT_COMPARABLE.

The [original 64-page PDF](../windows-prius-requal-20261018/coilem_benchmark_report.pdf),
[HTML](../windows-prius-requal-20261018/coilem_benchmark_report.html),
[complete JSON](../windows-prius-requal-20261018/benchmark_summary.json),
[CSV](../windows-prius-requal-20261018/benchmark_results.csv),
[fixtures](../windows-prius-requal-20261018/fixtures/), and
[exact comparison](../windows-prius-requal-20261018/comparison-to-prior.json) retain the full run.
No FEMM reference fields or numerical limits changed. This is development
regression evidence; it does not replace the frozen final-candidate gate.

## Earlier complete A/B/C/D baseline

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
reference physics remains exact. That earlier compilation generated no new
native fields; the separately identified Prius-branch run above supplies the
subsequent fresh native regression.

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
[#82](https://github.com/coilemdev/coilem/issues/82) retain distinct model IDs and evidence. The Pyleecan development report above
supplies its software cases, references, controls and full curve; final-candidate
measurements remain outstanding for v0.4.0. The separate hardware work in
#69/#82 is explicitly deferred to v0.5.0 and does not block this release.
Its outcomes cannot be inferred from the 29 supported FEMM cases.

The macOS record predates the changed mesh and reference-dispatch sources and is currently
NOT_COMPARABLE; Linux full numerical parity and Python 3.15 full numerical
coverage are not established by these Windows measurements. Complete the
release plan's scope, version, frozen-candidate benchmarks, wheel checks and
platform walkthroughs before tagging v0.4.0.
