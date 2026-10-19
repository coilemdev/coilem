# Public app Prius benchmark

Measured clean candidate `d993d7674354cc723ad107e7a5452477c5f660ea`.

Software checks: **10/10 pass**. Hardware qualification is not claimed.

Tutorial: **107.513838 V AB sampled RMS**, -0.0412% from the retained tutorial; 171.833919 V absolute peak, 0.3983% waveform relative L2.

Loaded preset: **353.950530 Nm**, -0.2825% from the retained FEMM control.

The fixed drawing-reflection mapping reverses electrical sample order and voltage polarity. No fit is applied.

| Phi0 | Upstream Nm | Retained FEMM Nm | Fresh app Nm | App minus FEMM Nm | App minus upstream Nm |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 60 | 79 | 82.985293 | 80.756854 | -2.228438 | +1.756854 |
| 70 | 125 | 126.895716 | 124.765557 | -2.130159 | -0.234443 |
| 80 | 160 | 171.695420 | 169.770210 | -1.925210 | +9.770210 |
| 90 | 192 | 215.526882 | 213.665203 | -1.861679 | +21.665203 |
| 100 | 237 | 256.696920 | 254.910859 | -1.786061 | +17.910859 |
| 110 | 281 | 293.532564 | 291.762285 | -1.770279 | +10.762285 |
| 120 | 319 | 324.210327 | 322.561595 | -1.648732 | +3.561595 |
| 130 | 343 | 346.079112 | 344.716342 | -1.362770 | +1.716342 |
| 140 | 353 | 354.727492 | 353.913534 | -0.813958 | +0.913534 |
| 150 | 332 | 338.842745 | 339.230164 | +0.387419 | +7.230164 |
| 160 | 266 | 273.425249 | 275.163003 | +1.737754 | +9.163003 |
| 170 | 164 | 155.525085 | 156.079306 | +0.554221 | -7.920694 |
| 180 | 22 | -0.329487 | 0.026539 | +0.356027 | -21.973461 |

Full-curve upstream RMS error: **11.445109 Nm**. All thirteen discrepancies remain in the result.

| Independent refinement at Phi0=140 degrees | Actual poses | First-pose triangles | Mean Nm | Change from normal 32 Nm |
| --- | ---: | ---: | ---: | ---: |
| angular-64 | 64 | 77308 | 353.951971 | +0.001441 |
| mesh-fine-32 | 32 | 82872 | 353.933789 | -0.016741 |

The Normal 32 baseline has 77,308 first-pose triangles. Fine changes this model to 82,872 (+7.2%); this mesh change bounds observed sensitivity rather than establishing systematic spatial convergence.

| Check | Outcome |
| --- | --- |
| tutorial_RMS | PASS |
| tutorial_peak | PASS |
| tutorial_waveform | PASS |
| loaded_mean_vs_FEMM | PASS |
| all_13_same_model_means | PASS |
| angular_control | PASS |
| mesh_control | PASS |
| all_fields_converged | PASS |
| all_phase_currents | PASS |
| source_linkage_duality | PASS |

Hardware context at 1000 rpm: ORNL records 85.7 V line RMS and 150 V peak. The 20 C software model differs by +25.45% RMS and +14.56% peak. ORNL's nominal 25 C oil is not a measured magnet temperature. This comparison has no hardware verdict.

Actual app solves: 100 tutorial zero-current fields plus 100 separate no-load fields; 32 loaded plus 32 no-load fields; 13 current angles × 16 full-cycle fields; 64 angular and 32 Fine mesh control fields.

[JSON waveforms, identities and field hashes](app-results.json) · [Full protocol and interpretation](README.md)

Runtime is recorded per job as informational wall time, not a controlled performance qualification. These remain development-candidate software results; repeat on the frozen final v0.4.0 candidate.
