# Public app Prius benchmark

Measured clean candidate `a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f`.

Grading: **frozen-at-collection**. Inputs were frozen before fields.

Software checks: **10/10 pass**. Hardware qualification is not claimed.

Convergence audit v2 applies the unchanged strict RHS-normalized residual limit and verifies the recorded native final-stage stopping test. This analysis revision was not frozen with the collection; its runner hash identifies the interpretation separately from the measured field source. Earlier reports and their verdicts remain historical evidence.

Tutorial: **107.513891 V AB sampled RMS**, -0.0412% from the retained tutorial; 171.851460 V absolute peak, 0.3983% waveform relative L2.

Loaded preset: **353.953040 Nm**, -0.2817% from the retained FEMM control.

The fixed drawing-reflection mapping reverses electrical sample order and voltage polarity. No fit is applied.

| Phi0 | Upstream Nm | Retained FEMM Nm | Fresh app Nm | App minus FEMM Nm | App minus upstream Nm |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 60 | 79 | 82.985293 | 80.755957 | -2.229335 | +1.755957 |
| 70 | 125 | 126.895716 | 124.766844 | -2.128872 | -0.233156 |
| 80 | 160 | 171.695420 | 169.771302 | -1.924118 | +9.771302 |
| 90 | 192 | 215.526882 | 213.665884 | -1.860998 | +21.665884 |
| 100 | 237 | 256.696920 | 254.912428 | -1.784492 | +17.912428 |
| 110 | 281 | 293.532564 | 291.764985 | -1.767579 | +10.764985 |
| 120 | 319 | 324.210327 | 322.564952 | -1.645375 | +3.564952 |
| 130 | 343 | 346.079112 | 344.720227 | -1.358886 | +1.720227 |
| 140 | 353 | 354.727492 | 353.917933 | -0.809559 | +0.917933 |
| 150 | 332 | 338.842745 | 339.234898 | +0.392152 | +7.234898 |
| 160 | 266 | 273.425249 | 275.165057 | +1.739808 | +9.165057 |
| 170 | 164 | 155.525085 | 156.086151 | +0.561066 | -7.913849 |
| 180 | 22 | -0.329487 | 0.030181 | +0.359669 | -21.969819 |

Full-curve upstream RMS error: **11.445258 Nm**. All thirteen discrepancies remain in the result.

| Independent refinement at Phi0=140 degrees | Actual poses | First-pose triangles | Mean Nm | Change from normal 32 Nm |
| --- | ---: | ---: | ---: | ---: |
| angular-64 | 64 | 77306 | 353.952463 | -0.000577 |
| mesh-fine-32 | 32 | 82856 | 353.933352 | -0.019688 |

The Normal 32 baseline has 77,306 first-pose triangles. Fine changes this model to 82,856 (+7.2%); this mesh change bounds observed sensitivity rather than establishing systematic spatial convergence.

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

Hardware context at 1000 rpm: ORNL records 85.7 V line RMS and 150 V peak. The 20 C software model differs by +25.45% RMS and +14.57% peak. ORNL's nominal 25 C oil is not a measured magnet temperature. This comparison has no hardware verdict.

Actual app solves: 100 tutorial zero-current fields plus 100 separate no-load fields; 32 loaded plus 32 no-load fields; 13 current angles × 16 full-cycle fields; 64 angular and 32 Fine mesh control fields.

[JSON waveforms, identities and field hashes](app-results.json) · [Full protocol and interpretation](README.md)

Runtime is recorded per job as informational wall time, not a controlled performance qualification. These remain software results requiring separate release and hardware qualification.
