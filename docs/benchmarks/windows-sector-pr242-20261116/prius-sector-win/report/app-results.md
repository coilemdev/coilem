# Public app Prius benchmark

Measured clean candidate `52f19004982887a7d615bbb8ea3b5a69bdfcacf7`.

Grading: **frozen-at-collection**. Inputs were frozen before fields.

Software checks: **10/10 pass**. Hardware qualification is not claimed.

Convergence audit v2 applies the unchanged strict RHS-normalized residual limit and verifies the recorded native final-stage stopping test. This analysis revision was not frozen with the collection; its runner hash identifies the interpretation separately from the measured field source. Earlier reports and their verdicts remain historical evidence.

Tutorial: **107.491812 V AB sampled RMS**, -0.0617% from the retained tutorial; 171.642717 V absolute peak, 0.4190% waveform relative L2.

Loaded preset: **353.999782 Nm**, -0.2686% from the retained FEMM control.

The fixed drawing-reflection mapping reverses electrical sample order and voltage polarity. No fit is applied.

| Phi0 | Upstream Nm | Retained FEMM Nm | Fresh app Nm | App minus FEMM Nm | App minus upstream Nm |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 60 | 79 | 82.985293 | 80.750476 | -2.234817 | +1.750476 |
| 70 | 125 | 126.895716 | 124.794396 | -2.101319 | -0.205604 |
| 80 | 160 | 171.695420 | 169.812705 | -1.882715 | +9.812705 |
| 90 | 192 | 215.526882 | 213.721633 | -1.805249 | +21.721633 |
| 100 | 237 | 256.696920 | 254.942101 | -1.754819 | +17.942101 |
| 110 | 281 | 293.532564 | 291.756007 | -1.776557 | +10.756007 |
| 120 | 319 | 324.210327 | 322.566521 | -1.643806 | +3.566521 |
| 130 | 343 | 346.079112 | 344.731131 | -1.347981 | +1.731131 |
| 140 | 353 | 354.727492 | 353.938951 | -0.788540 | +0.938951 |
| 150 | 332 | 338.842745 | 339.219045 | +0.376299 | +7.219045 |
| 160 | 266 | 273.425249 | 275.047249 | +1.622000 | +9.047249 |
| 170 | 164 | 155.525085 | 155.960763 | +0.435678 | -8.039237 |
| 180 | 22 | -0.329487 | -0.021147 | +0.308340 | -22.021147 |

Full-curve upstream RMS error: **11.465539 Nm**. All thirteen discrepancies remain in the result.

| Independent refinement at Phi0=140 degrees | Actual poses | First-pose triangles | Mean Nm | Change from normal 32 Nm |
| --- | ---: | ---: | ---: | ---: |
| angular-64 | 64 | 9538 | 353.994201 | -0.005581 |
| mesh-fine-32 | 32 | 10205 | 353.886855 | -0.112927 |

The Normal 32 baseline has 9,538 first-pose triangles. Fine changes this model to 10,205 (+7.0%); this mesh change bounds observed sensitivity rather than establishing systematic spatial convergence.

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

Hardware context at 1000 rpm: ORNL records 85.7 V line RMS and 150 V peak. The 20 C software model differs by +25.43% RMS and +14.43% peak. ORNL's nominal 25 C oil is not a measured magnet temperature. This comparison has no hardware verdict.

Actual app solves: 100 tutorial zero-current fields plus 100 separate no-load fields; 32 loaded plus 32 no-load fields; 13 current angles × 16 full-cycle fields; 64 angular and 32 Fine mesh control fields.

[JSON waveforms, identities and field hashes](app-results.json) · [Full protocol and interpretation](https://github.com/coilemdev/coilem/blob/52f19004982887a7d615bbb8ea3b5a69bdfcacf7/docs/benchmarks/pyleecan-prius-v1/README.md)

Runtime is recorded per job as informational wall time, not a controlled performance qualification. These remain software results requiring separate release and hardware qualification.
