Completed the user-requested **Windows Magneto2D vs fresh FEMM v2 comparison** on the matched fixed source pin `1ea9e406818b9ceafe5408e9c16acd33e9c439b0`.

**Outcome: 28 PASS, 1 FAIL, 1 planned UNSUPPORTED Prius case.** All 35 supported native jobs completed; **41/42 six-step gates PASS**. Native wall time, including the generated reports, was **43m 45.44s**. The locked release build took a separate 1m 17s.

The single failure is `spm_8p12s_reference / native_standard_to_fine_ripple_delta_percentage_points`: **5.034056245943816 pp > 5.0 pp**. Standard ripple is 147.73733301165964%; fine ripple is 152.77138925760346%. The 7.5° and 3.75° runs agree **exactly at all 48 shared angles**. The finer grid adds a minimum at 11.25° (3.853866893984895 Nm), below the standard-grid minimum at 195° (4.767361602203942 Nm); the shared maximum at 105° is 30.542144277302476 Nm. This is an angular-sampling convergence failure, not a failed worker. The original verdict is retained, with no reruns, altered inputs, fitted signs/phases/scales or relaxed limits.

For that case, native/FEMM mean torque differs by **0.525707%**, the torque waveform NRMSE is **0.873909%**, standard/fine mean torque differs by **0.132025%**, and the low-current power/torque discrepancy is **0.274734%**. All current-property/golden-vector and commutation-alignment gates pass. The preceding Windows native report at `04f87a5` recorded 2.7551025405282417 pp for this convergence gate; the corrected loaded-field result now exceeds it.

| Phase | Outcome |
| --- | --- |
| A — SPM | 10 PASS |
| B — IPM | 12 PASS |
| C — distributed/double-layer controls | 4 PASS; Prius planned UNSUPPORTED |
| D — ideal six-step BLDC | 2 PASS; 1 FAIL |

The deep-apex and wide-angle higher-output V-shapes remain the largest primary torque differences: **7.406171%** and **7.078145%**, respectively, within the existing 8% green gate. These large offsets were present in earlier records; the deep-apex comparison previously measured 7.411251%. V-shape remains experimental.

<details>
<summary>All 26 A/B/C numerical comparisons</summary>

Back-EMF is phase-A fundamental RMS line-to-neutral at the registered speed. Percent differences use the absolute FEMM value as denominator. The three near-zero no-load mean-torque cases use the registered absolute gate; their relative torque percentages are omitted here.

| Case | Native mean Nm | FEMM mean Nm | Torque difference | Native Back-EMF V | FEMM Back-EMF V | Back-EMF difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `spm_4p12s_simple__baseline` | 0.478280217 | 0.477555372 | 0.151783% | 4.98726733 | 4.98784064 | 0.011494% |
| `spm_4p12s_simple__high_current` | 0.717237641 | 0.716438963 | 0.111479% | 4.98726733 | 4.98784064 | 0.011494% |
| `spm_4p12s_simple__tight_airgap` | 0.582623001 | 0.58307224 | 0.077047% | 6.0795375 | 6.10043119 | 0.342495% |
| `spm_4p12s_simple_noload__baseline` | 5.46342814e-06 | -0.00205833558 | 0.0020638 Nm absolute | 4.98726733 | 4.98784064 | 0.011494% |
| `spm_4p12s_simple_noload__high_current` | 0.239179689 | 0.238554898 | 0.261907% | 4.98726733 | 4.98784064 | 0.011494% |
| `spm_4p12s_simple_noload__tight_airgap` | -0.000179007405 | -0.000103983222 | 7.50242e-05 Nm absolute | 6.0795375 | 6.10043119 | 0.342495% |
| `spm_8p12s_concentrated__baseline` | 2.56183409 | 2.55779437 | 0.157937% | 18.8017484 | 18.7885384 | 0.070309% |
| `spm_8p12s_concentrated__high_current` | 3.83666412 | 3.83345617 | 0.083683% | 18.8017484 | 18.7885384 | 0.070309% |
| `spm_8p12s_concentrated__tight_airgap` | 2.71796542 | 2.72526444 | 0.267828% | 20.0356697 | 20.0327812 | 0.014419% |
| `spm_8p12s_reference_angle30__baseline` | 19.1730868 | 19.2346979 | 0.320312% | 46.0881945 | 46.1551151 | 0.144991% |
| `ipm_flat_12s10p_fscw_contract` | 4.50259606 | 4.47628999 | 0.587676% | 23.5870082 | 23.4439274 | 0.610311% |
| `ipm_flat_24s16p_industrial_contract` | 22.4265213 | 22.5595246 | 0.589566% | 33.3402169 | 33.4042148 | 0.191586% |
| `ipm_flat_4p12s_micro_contract` | 0.0214445372 | 0.0215174173 | 0.338703% | 0.449170354 | 0.451726018 | 0.565755% |
| `ipm_flat_8p12s_fsae_angled_pocket_contract` | 2.48423734 | 2.48678497 | 0.102447% | 8.11797716 | 8.14254083 | 0.301671% |
| `ipm_flat_8p12s_fsae_contract` | 2.9741422 | 2.97963142 | 0.184225% | 8.84268654 | 8.8642571 | 0.243343% |
| `ipm_flat_8p12s_fsae_thin_bridge_contract` | 3.67796747 | 3.67262366 | 0.145504% | 11.0279057 | 11.0523029 | 0.220744% |
| `ipm_vshape_8p12s_baseline_contract` | 0.934951884 | 0.869752725 | 7.496287% | 2.56262441 | 2.51039849 | 2.080384% |
| `ipm_vshape_8p12s_deep_apex_high_output_v1` | 0.625690352 | 0.582546001 | 7.406171% | 1.72014327 | 1.66439438 | 3.349500% |
| `ipm_vshape_8p12s_narrow_angle_contract` | 0.933945451 | 0.896935277 | 4.126293% | 2.60402946 | 2.51467493 | 3.553323% |
| `ipm_vshape_8p12s_pocket_offset_contract` | 1.12222876 | 1.06461299 | 5.411898% | 2.54573 | 2.51236689 | 1.327955% |
| `ipm_vshape_8p12s_thin_bridge_contract` | 3.01089951 | 2.95747313 | 1.806487% | 8.56241272 | 8.4900587 | 0.852220% |
| `ipm_vshape_8p12s_wide_angle_high_output_v1` | 0.789963502 | 0.737744851 | 7.078145% | 2.24926579 | 2.1733264 | 3.494155% |
| `spm_12p36s_distributed_femm_validation` | 5.05111554 | 5.20567485 | 2.969054% | 121.763589 | 120.577556 | 0.983627% |
| `spm_8p24s_distributed_femm_validation` | 5.56093423 | 5.62453597 | 1.130791% | 121.709648 | 121.089445 | 0.512186% |
| `spm_8p48s_chorded_5_6` | 5.94246666 | 5.98145735 | 0.651859% | 113.255121 | 112.356179 | 0.800082% |
| `spm_8p48s_distributed_femm_validation` | 6.06310893 | 6.09923122 | 0.592243% | 117.250329 | 116.242623 | 0.866899% |

</details>

The A/B/C registered gates check amplitude, angle grids, native mesh and torque method. Signed waveforms were also reviewed: there are no polarity diagnostic flags. The largest phase-A voltage waveform NRMSE is **5.719095%** (narrow-angle V-shape), and the largest torque waveform NRMSE is **8.980498%** (12p36s winding control). These waveform diagnostics are retained rather than implied to be zero.

| Six-step case | Native standard mean Nm | FEMM mean Nm | Mean difference | Waveform NRMSE | Standard/fine ripple difference pp | Power/torque difference | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `spm_14p12s_high_pole` | 3.27998923 | 3.27824693 | 0.053147% | 0.435583% | 3.138911620 | 0.572637% | PASS |
| `spm_4p12s_small` | 0.574050024 | 0.573341526 | 0.123573% | 0.278865% | 0.396496639 | 0.282358% | PASS |
| `spm_8p12s_reference` | 17.4463571 | 17.5385585 | 0.525707% | 0.873909% | 5.034056246 | 0.274734% | FAIL |

Against the recorded Windows native run at `04f87a5013415997cdef96a9bfa35125ce625bc5`, with identical suite/configuration hashes: **all 26 A/B/C native primary torque means and complete torque waveforms are bit-for-bit unchanged**. All 22 affected concentrated single-layer three-phase Back-EMF waveforms, fundamentals, lambda and Ke are **exactly 2×**; all four controls are **exactly unchanged**. No other common numeric A/B/C physical summary field changed. Native standard six-step mean-torque ratios are **2.0005005894**, **1.9998194972**, and **1.9994587612** (high-pole, small, reference). Every native stage retains the exact old terminal-current waveform; all three measured analytical-stage no-load voltage waveforms double exactly. The source commits include intervening changes, so this is an observed before/after comparison rather than an assertion that every code change is isolated.

Supplemental six-step Back-EMF comparison uses the already completed fresh **FEMM zero-current diagnostics** and the native low-current-discriminator stage's **no-load** Back-EMF solve. Historical v1 FEMM D Back-EMF records do not exist. No new FEMM solves were launched for this comparison.

| Case | Native no-load fundamental V | Fresh FEMM full-turn diagnostic V | Difference | Native/FEMM angle step |
| --- | ---: | ---: | ---: | --- |
| `spm_14p12s_high_pole` | 14.9881437 | 14.9777475 | 0.069412% | 3.75° / 3.75° |
| `spm_4p12s_small` | 10.0006389 | 9.97568128 | 0.250185% | 3.75° / 7.5° |
| `spm_8p12s_reference` | 46.1289531 | 46.1551151 | 0.056683% | 3.75° / 7.5° |

The high-pole diagnostic has matched grids: signed phase-A/B/C voltage NRMSE is 0.158197% / 0.342358% / 0.871576%. The small and reference no-load grids differ, so their waveform NRMSE was not calculated through interpolation or fitted alignment. Their amplitude comparisons include that grid difference.

Auxiliary summary differences are preserved separately in the full numeric audit. The v1-format FEMM auxiliary q-axis torque and Kt retain the raw CCW sign, while the primary torque waveform/mean is mapped to public CW. Historical FEMM Kt divides by the RMS request current; native Kt uses resolved peak phase current. Peak steel flux also uses different extraction definitions (FEMM discrete point samples versus native robust element peaks). These raw auxiliary fields are not interchangeable validation targets under the current primary benchmark contract. For example, the baseline native/FEMM raw Kt is +0.0338195 / −0.0477555 Nm/A, and tooth peak B is 1.565116 / 1.202178 T. The report retains those differences without changing either record.

Provenance: clean measured source `1ea9e406818b9ceafe5408e9c16acd33e9c439b0`; coilEM 0.3.1; Magneto2D 0.3.3; locked release build with rustc 1.95.0; default Windows process-pool policies with all four override switches absent. PR #84 has later diagnostic commits; this result covers the exact matched FEMM pin, not the later head. The fresh v2 bundle is in [data PR #93](https://github.com/coilemdev/coilem/pull/93), produced with FEMM 4.2.0.0 / pyFEMM 0.1.3 and adapter `8b95decda27d475ddbb75e99d92744ebc8e53b28` plus the exact fixed helpers at the matched pin.

Native source SHA-256: `0d285d645d53075bb99148f6acb1f25bb3f924b376e17117c2deba3d906918b1`. Native binary SHA-256: `f84d71aea782624eb173e0874fbb80c9ceb749d18b845877e352ac9cb53ecaa6`. Suite SHA-256: `ea9d60d81d8601d2cdd6d7c94b3b3df70c65c6cf516737aeb125a4b2f2004721`. FEMM bundle identity: `0770b1b17eef307b863c6fd00f7267441e2afd67b4b21b73e51e7c278417c367`.

All 35 request/result hashes, before/after runtime identities, imported backend sources, report artifact hashes and unchanged registered gates were verified. Original requests/results, worker logs, native cache evidence, HTML/PDF/CSV reports, all common numeric physical-summary differences, all three signed voltage-phase comparisons and the ripple-failure inspection remain local. The source checkouts and snapshot manifests remain unchanged.

Future benchmark runs should explicitly select `--reference-bundle benchmarks/reference-baselines/ipm-high-output-v2`; the runner at this pin still defaults to v1.


The later supplemental ripple investigation is [documented separately](ripple-diagnostic/investigation.md), with [plots in its diagnostic PDF](ripple-diagnostic/ripple-diagnostic.pdf). It retains the original FAIL.
