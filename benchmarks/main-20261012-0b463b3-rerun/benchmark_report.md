# Coilem A/B/C/D benchmark report v1.3

Outcome: **29 PASS; one planned coverage item (not yet supported)**. Full Windows native rerun at `0b463b31fc3479360ffaa3668731e3792c034639`.

Fresh Magneto2D native field measurements use frozen, data-only FEMM references from `benchmarks/reference-baselines/ipm-high-output-v1`. No FEMM installation, reference adapter or new FEMM solve was used. The reference commit belongs to a separate reference repository.

Measured candidate `0b463b3` is the baseline before performance PRs #32 (airgap radius indexing), #33 (post-solve pipeline) and #34 (wall-clock timing). It also predates the later main responsiveness changes in PRs #29, #30 and #31. Publishing this report on a newer branch does not mean those changes were measured.

Harness 1.2.1; protocol 1.1.0. Actual elapsed wall time: **2.944 hours**.

[HTML plots](coilem_benchmark_report.html), [full JSON](benchmark_summary.json), [runtime and publication details](README.md), [comparison with v1.2](comparison-to-v1.2.json).

| Phase | Recorded outcomes |
| --- | --- |
| A - SPM | 10 PASS |
| B - IPM | 12 PASS |
| C - Distributed Winding | 4 PASS; one planned coverage item (UNSUPPORTED) |
| D - BLDC | 3 PASS; 42/42 gates |

## Comparison policy

Unchanged A/B/C gates: mean torque PASS <=8% / YELLOW <=15%; Back-EMF fundamental and phase-A peak PASS <=10% / YELLOW <=15%. Near-zero references below 0.01 N m use absolute torque limits of 0.01 / 0.02 N m. Native Gmsh, weighted-stress torque and registered angle grids are required. Phase D retains fourteen gates per fixture, ideal six-step 120-degree wye, normal spatial meshes, fine angular sampling and frozen golden currents. Its low-current analytical lane is a native field solve. No fitted angle, sign or scale correction is used.

Elapsed job timings reflect concurrent workloads, including another full benchmark and an older refined-IPM sweep. Use actual job timestamps in [execution timings](execution-timings.json); aggregate `solve_time_s` is not elapsed benchmark wall time. Future speed comparisons need comparable machine load and settings. Browser mesh and field playback responsiveness are outside this headless benchmark.

Orange solid = Magneto2D; blue dashed = frozen FEMM. Residuals, BLDC currents and angular refinement plots are retained in the HTML report.

## Phase A - SPM

| Fixture | Outcome | Magneto2D / frozen FEMM mean (N m) | Torque gap | Back-EMF H1 / peak gap |
| --- | --- | ---: | ---: | ---: |
| [spm_4p12s_simple__baseline](fixtures/spm_4p12s_simple__baseline__native.json) | PASS | 0.478280 / 0.477514 | 0.161% | 0.011% / 0.041% |
| [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current__native.json) | PASS | 0.717238 / 0.716397 | 0.117% | 0.011% / 0.041% |
| [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap__native.json) | PASS | 0.582623 / 0.583066 | 0.076% | 0.342% / 0.050% |
| [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline__native.json) | PASS | 0.000005 / -0.002058 | 0.002064 N m (absolute gate) | 0.011% / 0.041% |
| [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current__native.json) | PASS | 0.239180 / 0.238513 | 0.279% | 0.011% / 0.041% |
| [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap__native.json) | PASS | -0.000179 / -0.000104 | 0.000075 N m (absolute gate) | 0.342% / 0.050% |
| [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline__native.json) | PASS | 2.561834 / 2.557786 | 0.158% | 0.070% / 0.154% |
| [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current__native.json) | PASS | 3.836664 / 3.833448 | 0.084% | 0.070% / 0.154% |
| [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap__native.json) | PASS | 2.717965 / 2.725278 | 0.268% | 0.014% / 0.080% |
| [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline__native.json) | PASS | 19.173087 / 19.234698 | 0.320% | 0.145% / 0.174% |

All supported phase entries retain their six comparison/provenance gates in the JSON and HTML. Near-zero means are evaluated with absolute torque gates.

## Phase B - IPM

| Fixture | Outcome | Magneto2D / frozen FEMM mean (N m) | Torque gap | Back-EMF H1 / peak gap |
| --- | --- | ---: | ---: | ---: |
| [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract__native.json) | PASS | 4.502596 / 4.475955 | 0.595% | 0.610% / 0.622% |
| [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract__native.json) | PASS | 22.426521 / 22.557361 | 0.580% | 0.192% / 0.347% |
| [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract__native.json) | PASS | 0.021445 / 0.021516 | 0.331% | 0.566% / 0.791% |
| [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json) | PASS | 2.484237 / 2.486783 | 0.102% | 0.302% / 0.726% |
| [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract__native.json) | PASS | 2.974142 / 2.978470 | 0.145% | 0.243% / 0.291% |
| [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json) | PASS | 3.677967 / 3.673380 | 0.125% | 0.221% / 0.477% |
| [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract__native.json) | PASS | 0.934952 / 0.869846 | 7.485% | 2.080% / 6.249% |
| [ipm_vshape_8p12s_deep_apex_high_output_v1](fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1__native.json) | PASS | 0.625690 / 0.582518 | 7.411% | 3.349% / 3.953% |
| [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json) | PASS | 0.933945 / 0.897028 | 4.116% | 3.553% / 4.429% |
| [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json) | PASS | 1.122229 / 1.064713 | 5.402% | 1.328% / 3.009% |
| [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json) | PASS | 3.010900 / 2.957579 | 1.803% | 0.852% / 1.703% |
| [ipm_vshape_8p12s_wide_angle_high_output_v1](fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1__native.json) | PASS | 0.789964 / 0.737758 | 7.076% | 3.494% / 3.947% |

All supported phase entries retain their six comparison/provenance gates in the JSON and HTML. Near-zero means are evaluated with absolute torque gates.

## Phase C - Distributed Winding

| Fixture | Outcome | Magneto2D / frozen FEMM mean (N m) | Torque gap | Back-EMF H1 / peak gap |
| --- | --- | ---: | ---: | ---: |
| [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json) | Planned coverage (UNSUPPORTED) | Not measured | - | - |
| [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json) | PASS | 5.051116 / 5.206070 | 2.976% | 0.984% / 0.588% |
| [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json) | PASS | 5.560934 / 5.624537 | 1.131% | 0.512% / 0.277% |
| [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json) | PASS | 5.942467 / 5.979840 | 0.625% | 0.800% / 0.124% |
| [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json) | PASS | 6.063109 / 6.097581 | 0.565% | 0.867% / 0.976% |

All supported phase entries retain their six comparison/provenance gates in the JSON and HTML. Near-zero means are evaluated with absolute torque gates.

Prius uses HoleM50 geometry outside public support. Numerical status is UNSUPPORTED; no comparison was performed.

## Phase D - BLDC

| Fixture | Gates | Mean torque gap | Waveform NRMSE | Power / torque gap | Standard / fine torque gap |
| --- | --- | ---: | ---: | ---: | ---: |
| [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json) | 14/14 PASS | 0.056% | 0.867% | 0.669% | 0.400% |
| [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json) | 14/14 PASS | 0.198% | 0.530% | 0.328% | 0.210% |
| [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json) | 14/14 PASS | 0.852% | 1.285% | 0.319% | 0.147% |

### spm_14p12s_high_pole

Inputs: [native-standard](fixtures/spm_14p12s_high_pole__native-standard.json), [native-fine](fixtures/spm_14p12s_high_pole__native-fine.json), [analytical](fixtures/spm_14p12s_high_pole__analytical.json).

| Gate | Value | Limit | Outcome |
| --- | --- | --- | --- |
| mean_torque_delta_pct | 0.056287 | 5.000000 | PASS |
| torque_waveform_nrmse_pct | 0.867476 | 10.000000 | PASS |
| commutation_transition_delta_samples | 0.000000 | 1.000000 | PASS |
| power_torque_delta_pct | 0.668657 | 10.000000 | PASS |
| native_standard_to_fine_mean_torque_delta_pct | 0.399693 | 2.000000 | PASS |
| native_standard_to_fine_ripple_delta_percentage_points | 3.389231 | 5.000000 | PASS |
| native_standard_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| native_fine_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| femm_standard_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| analytical_low_current_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| native-standard_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| native-fine_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| analytical_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| femm-standard_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |

### spm_4p12s_small

Inputs: [native-standard](fixtures/spm_4p12s_small__native-standard.json), [native-fine](fixtures/spm_4p12s_small__native-fine.json), [analytical](fixtures/spm_4p12s_small__analytical.json).

| Gate | Value | Limit | Outcome |
| --- | --- | --- | --- |
| mean_torque_delta_pct | 0.197903 | 5.000000 | PASS |
| torque_waveform_nrmse_pct | 0.530097 | 10.000000 | PASS |
| commutation_transition_delta_samples | 0.000000 | 1.000000 | PASS |
| power_torque_delta_pct | 0.327743 | 10.000000 | PASS |
| native_standard_to_fine_mean_torque_delta_pct | 0.209825 | 2.000000 | PASS |
| native_standard_to_fine_ripple_delta_percentage_points | 1.038556 | 5.000000 | PASS |
| native_standard_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| native_fine_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| femm_standard_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| analytical_low_current_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| native-standard_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| native-fine_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| analytical_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| femm-standard_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |

### spm_8p12s_reference

Inputs: [native-standard](fixtures/spm_8p12s_reference__native-standard.json), [native-fine](fixtures/spm_8p12s_reference__native-fine.json), [analytical](fixtures/spm_8p12s_reference__analytical.json).

| Gate | Value | Limit | Outcome |
| --- | --- | --- | --- |
| mean_torque_delta_pct | 0.852327 | 5.000000 | PASS |
| torque_waveform_nrmse_pct | 1.284908 | 10.000000 | PASS |
| commutation_transition_delta_samples | 0.000000 | 1.000000 | PASS |
| power_torque_delta_pct | 0.319215 | 10.000000 | PASS |
| native_standard_to_fine_mean_torque_delta_pct | 0.147236 | 2.000000 | PASS |
| native_standard_to_fine_ripple_delta_percentage_points | 2.755103 | 5.000000 | PASS |
| native_standard_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| native_fine_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| femm_standard_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| analytical_low_current_current_properties | {"invalid_conduction_samples": 0, "max_plateau_error_abs_A": 0.0, "max_zero_phase_abs_A": 0.0, "max_zero_sum_abs_A": 0.0} | {"current_abs_A": 1e-09, "invalid_samples": 0, "zero_sum_abs_A": 1e-09} | PASS |
| native-standard_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| native-fine_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| analytical_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |
| femm-standard_golden_current_sequence | "matches frozen golden current table" | "exact phase sequence within frozen current tolerance" | PASS |

## Scope

Ideal current-commanded six-step results do not measure PWM, dead time, commutation overlap, dynamic bus behavior or hardware. Thermal analysis is outside this A/B/C/D protocol. The benchmark does not promote untested combinations or change application qualification status.
