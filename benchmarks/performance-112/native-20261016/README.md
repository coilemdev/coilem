# Matched Windows Magneto2D and FEMM 4.2 repeat (2026-10-16)

[64-page PDF](coilem_benchmark_report.pdf) · [HTML plots](coilem_benchmark_report.html) ·
[Markdown results](benchmark_report.md) · [CSV results](benchmark_results.csv) ·
[Full numerical JSON](benchmark_summary.json) · [Comparison with main](comparison-to-main.json) ·
[Timing record](timings.json) · [Verification](verification.json) ·
[Publication provenance](publication.json) · [Original native manifest](run_manifest.json) ·
[Artifact checksums](artifact_manifest.json)

All **35 runnable Magneto2D jobs** completed on clean `9012f19` against the
[fresh 29-case FEMM 4.2 collection](../repeat-20261016.md). The registered suite
retains 30 rows / 36 jobs, including the planned unsupported Prius fixture.
The full registered grids were used, with no smoke or dirty-source override.
All 50 physics source hashes match the measured FEMM pin `738d951`.

## Outcome

| Phase | Recorded outcome |
| --- | --- |
| A: SPM | 10 PASS |
| B: IPM | 11 PASS, 1 YELLOW |
| C: distributed winding | 4 PASS, 1 planned unsupported Prius |
| D: BLDC | 3 PASS; 42/42 gates pass |

Overall: **28 PASS, 1 YELLOW, 1 planned UNSUPPORTED**, with no failed,
incomplete or errored rows. The V-shape baseline IPM remains YELLOW for a
**14.778701% peak back-EMF amplitude difference** (10% green / 15% yellow).
Its mean torque difference is 5.845430%, fundamental back-EMF difference
2.056293%, and back-EMF waveform NRMSE 12.650758%. There are no signed-waveform
polarity findings. All existing limits and statuses remain visible.

## Numerical comparison with main

The comparison is against the [Windows v3 report on main at `560ad49`](https://github.com/coilemdev/coilem/blob/560ad4969a06e9cde2e78b543b618a6429a8187c/benchmarks/windows-v3-20261015-738d951/README.md).
It checks the fixed commit, so later main changes do not change this record.

- All **35 native job result summaries and waveforms match exactly**:
  **23,287 numerical values**, zero numerical or structural changes.
- All **628 evaluation numbers** and **14,165 reference-result numbers** match
  exactly. All 30 case verdicts and every gate verdict remain unchanged.
- Checked native mesh metadata is unchanged. Torque, EMF, flux linkage,
  peak/RMS flux densities, Kt, Ke, current/torque/voltage waveforms and angle
  grids are included. Timings, timestamps, cache paths and execution provenance
  are compared separately from physical values.
- Across loaded A/B/C cases, the largest mean-torque difference from FEMM is
  **5.904005%**; the largest fundamental back-EMF difference is **3.386134%**.

The YELLOW waveform and residual shown in the previous report are therefore
numerically identical in this repeat. No phase, sign or scale fitting was used.

## Timing

| Stage | Current | Previous recorded run |
| --- | ---: | ---: |
| FEMM 4.2 reference collection | 1h50m54s | 1h52m02s optimized |
| Magneto2D native collection | 43m40s | 45m37s |
| Sum of the two current collection stages | 2h34m34s | Separate stages |

The native stage is 117.70 seconds (4.30%) quicker than the previous Windows
native run. These are observations on the development host with normal desktop
activity. The 17-minute gap between launching the two solvers is excluded from
the stage sum. Per-job timings, source identities and result hashes are retained.

## Integrity and publication

Every native request/result checksum, before/after source identity, the pinned
native executable and the fresh FEMM bundle selection were verified. The exact
fresh bundle digest is `d1e3504d6ccb241301776cec5ae7a263659383a0a9041a8c206b170a22323068`.
The native manifest is copied byte-for-byte; its checksum is
`bac4c1376648f9f6c3fa218c7680d4bd2838763d86d84d2c00c24e2fe9120fc5`.
The [suite candidate](candidate-suite.json) retains the explicit hash-bound
protocol-1.3 bridge to the fresh v3 bundle. Its numerical requests and gates
match the published suite.

The generated PDF is copied byte-for-byte unchanged. Its 36 relative fixture
links resolve to the [committed fixture copies](fixtures/). Published text/JSON/CSV
normalizes local execution/cache roots while retaining every numerical value.
Raw native requests/results, logs, the fresh FEMM bundle and executable remain
locally retained. Publication executed zero field solves.

**Keep reference v3 and validation protocol 1.3.0.** This package records a new
execution of unchanged fixtures. The original reports, reference registry and
scientific qualification remain unchanged; the fresh FEMM bundle retains
REVIEW_REQUIRED. All limitations in the original Windows v3 report remain
applicable, including steel-B/core-loss, Kt/current-base and peak-B sampling
comparability, unavailable native loss/efficiency evidence, and near-zero
no-load relative ripple.
