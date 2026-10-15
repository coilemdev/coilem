# Windows full-turn flux-credit benchmark comparison

[Final 64-page PDF with plots](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html), [Markdown gate report](benchmark_report.md), [all-case comparison](results-comparison.md), [JSON results](benchmark_summary.json), [publication provenance](publication.json), [artifact hashes](artifact_manifest.json).

The full A/B/C/D Magneto2D run measures **coilEM backend 0.3.1 / Magneto2D 0.3.3** at clean, frozen commit `1ea9e406818b9ceafe5408e9c16acd33e9c439b0` against the fresh FEMM v2 records with the same fixed-helper commit. **28 PASS, 1 FAIL, 1 planned UNSUPPORTED Prius case; all 35 supported native jobs completed, 41/42 six-step gates PASS.** Harness 1.2.1, protocol 1.1.0, Windows 11 build 26200 and the registered suite/inputs/gates were retained. The four process-pool overrides were absent. This run used the FEMM records without executing additional FEMM solves.

The measured pin is explicit: PR #84 includes subsequent reciprocity/energy-diagnostic code changes. This package validates the pinned full-turn/current fix; it does not certify the latest PR tip. The [data-only FEMM v2 PR #93](https://github.com/coilemdev/coilem/pull/93) carries the 30 reference JSON files; this publication preserves that PR's data-only scope.

## Results and limitations

| Phase | Result |
| --- | --- |
| A: SPM | 10 PASS |
| B: IPM | 12 PASS |
| C: distributed/double-layer controls | 4 PASS; Prius planned UNSUPPORTED |
| D: ideal six-step BLDC | 2 PASS; 1 FAIL |

All 26 sinusoidal native torque waveforms/means match the earlier Windows native record exactly. All 22 affected native three-phase Back-EMF waveforms, fundamentals, lambda and Ke exactly double; the four controls remain unchanged. The three six-step mean torques are approximately doubled, with commanded-current golden vectors intact. [Before/after numerical evidence](analysis/native-before-after.json) retains the earlier measured record rather than substituting rescaled reference data.

Compared with fresh FEMM v2, deep-apex and wide-angle higher-output V-shapes retain mean-torque differences of **7.406171%** and **7.078145%**, inside the existing 8% gate. These are existing offsets; V-shape remains experimental. Common physical summary quantities and full torque/voltage waveforms were reviewed in [physical-comparison.json](analysis/physical-comparison.json). Auxiliary raw FEMM Kt/q-axis signs and current conventions, and discrete-point versus element-based peak-field sampling, differ and are disclosed there; they are not interchangeable primary targets.

The three v1 six-step records have no Back-EMF. Their separate fresh FEMM no-load diagnostics were compared honestly with the native no-load stage: fundamental differences **0.069412%, 0.250185% and 0.056683%** for high-pole, small and 8p12s, respectively. High-pole uses a matching 3.75-degree grid and has a three-phase waveform comparison. The other two grids differ (native 3.75 degrees, FEMM 7.5 degrees); no interpolated waveform-error claim is made. The historical half-turn/full-turn FEMM extraction comparison uses the same freshly solved fields and establishes bookkeeping doubling; it does not invent absent v1 waveforms.

## Ripple failure and investigation

The original 8p12s standard-to-fine ripple gate remains **FAIL: 5.034056246 pp > 5.0 pp**. Mean native/FEMM torque differs by 0.525707%, torque waveform NRMSE is 0.873909%, standard/fine mean torque differs by 0.132025% and low-current power/torque discrepancy is 0.274734%. Every current-property/golden-vector/commutation gate passes.

The [separate ripple investigation](ripple-diagnostic/investigation.md), [two-page diagnostic PDF](ripple-diagnostic/ripple-diagnostic.pdf) and [full numerical evidence](ripple-diagnostic/investigation.json) refine 50 A angular sampling to 1.875 and 0.9375 degrees and add a fresh 25 A control. Successive shared-angle torque samples are bit-for-bit equal; the registered coarse grid misses a torque trough. The additional ripple changes are **0.054121 and 0.900966 pp**. The fresh 25 A solve exactly reproduces all 96 earlier fine-grid torque samples, isolating removal of the former half-current slot-source factor. These diagnostics preserve the original registered measurements and failed verdict. They do not establish spatial convergence or justify relaxing its threshold.

## Timing and provenance

Native execution/report generation took **43m 45.44s (2625.436761 s)**; the locked release build took a separate 1m 17s. The supplemental investigation took **4m 2.453s (242.452895 s)**. Phase/job timings are in [execution-timings.json](analysis/execution-timings.json). Source, binary, dependency, input, protocol, request/result and generated report hashes were verified; registered gates were independently reevaluated. The original measurements/report remain unchanged.

For reproduction, use the clean `1ea9e40` checkout, recorded runtime dependencies and a locked release build. Obtain the FEMM v2 folder from data commit `1071c266edf0762de4ff23c4df9427e704a8ea3b` / PR #93 in a separate reference directory; pass that directory to `--reference-bundle`. Run the registered CLI with `--suite benchmarks/abcd-v1.1/benchmark_spec.json --phases A B C D --pdf` and a fresh `--out-dir`. The registered outcome is FAIL; an exit code of 1 records that numerical failure, not an interrupted worker.

## Publication

The original 64-page PDF was rendered and visually reviewed and is copied byte-for-byte unchanged (SHA-256 `0f976481c0f31222f4dd3762119ef5061f670547918b316135af70b724a5ec65`). Its fixture links retain originating local paths; HTML/Markdown link to committed fixture JSON. The supplemental two-page PDF was also rendered and reviewed. Text/JSON replaces local directories with portable placeholders and omits worker PIDs; numerical values and verdicts remain exact. Diagnostic requests/results accompany this package; raw worker logs, main-suite request/results, CSV, field caches and solver binaries remain local. Snapshot/PDF registration updates apply only to this publication checkout, preserving the frozen measured checkout and the FEMM data branch.
