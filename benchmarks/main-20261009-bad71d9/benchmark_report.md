# Coilem main benchmark report v1.1

Pinned Coilem main: `bad71d9cbcb10bf2daa293c5577f9d9e26778a12`.
A/B/C state: **COMPLETE**. Combined run state: **COMPLETE**. Overall comparison: **FAIL**.

Fresh public native measurements use the OpenEM v0.2.5 matrix geometry and operating inputs. Fresh FEMM references come from pinned harness commit `8b95decda27d475ddbb75e99d92744ebc8e53b28`, using matching M350-50A and magnet values. Historical measurements are excluded from the fresh verdicts.

**Reference convention corrected:** the initial comparison reflected FEMM angles but retained positive CCW speed. Back-EMF also reverses for the same positive public CW speed: e_public(theta) = -e_FEMM(-theta). This fixed transform follows the pinned derivative code; no sign or phase is fitted. The convention audit is summarized in [reference_conventions.md](reference_conventions.md); original raw records remain in the frozen local snapshot. Raw measurements, torque and amplitude gates are unchanged.

| Phase | Outcomes |
| --- | --- |
| A | 10 PASS |
| B | 10 PASS, 2 FAIL |
| C | 1 UNSUPPORTED, 4 PASS |
| D - BLDC | 3 PASS; 42 / 42 gates |

## Comparison policy

Historical pairwise bands: mean torque 8% PASS / 15% YELLOW; Back-EMF fundamental and peak 10% PASS / 15% YELLOW. For reference mean torque below 0.01 N m, use 0.01 / 0.02 N m absolute bands. Missing values make a row incomplete. Actual WST, native meshing and matching angular grids are required. Waveform NRMSE/correlation are diagnostics. Declared reference mapping: angle = -angle modulo 360; torque = -torque; omega_FEMM = -omega_public; voltage = -voltage at the reflected angle; gamma_internal = 180 - gamma_public. Voltage polarity follows the speed transformation. Partial native grids use matching samples from the full reference cycle.

The unmodified public runtime uses its own request-derived settings, tolerance and caches. Native requests pass through the public policy and scientific solver with launch_surface=True; UI playback/export packaging is excluded. This is a candidate comparison; it does not repeat the private 0.005-tolerance signoff profile. THD, spatial convergence, airgap harmonics, promoted cogging references and release qualification are outside the A/B/C matrix. Phase D uses the distinct BLDC gates below.

## Per fixture results

| Phase | Fixture | Verdict | Mean torque delta | BEMF H1 delta | BEMF peak delta |
| --- | --- | --- | ---: | ---: | ---: |
| A | [spm_4p12s_simple__baseline](fixtures/spm_4p12s_simple__baseline.json) | PASS | 0.16% | 0.01% | 0.04% |
| A | [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current.json) | PASS | 0.12% | 0.01% | 0.04% |
| A | [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap.json) | PASS | 0.08% | 0.34% | 0.05% |
| A | [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline.json) | PASS | 0.00206 N m | 0.01% | 0.04% |
| A | [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current.json) | PASS | 0.28% | 0.01% | 0.04% |
| A | [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap.json) | PASS | 0.00008 N m | 0.34% | 0.05% |
| A | [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline.json) | PASS | 0.16% | 0.07% | 0.15% |
| A | [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current.json) | PASS | 0.08% | 0.07% | 0.15% |
| A | [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap.json) | PASS | 0.27% | 0.01% | 0.08% |
| A | [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline.json) | PASS | 0.32% | 0.14% | 0.17% |
| B | [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract.json) | PASS | 0.60% | 0.61% | 0.62% |
| B | [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract.json) | PASS | 0.58% | 0.19% | 0.35% |
| B | [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract.json) | PASS | 0.33% | 0.57% | 0.79% |
| B | [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract.json) | PASS | 0.10% | 0.30% | 0.73% |
| B | [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract.json) | PASS | 0.15% | 0.24% | 0.29% |
| B | [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract.json) | PASS | 0.12% | 0.22% | 0.48% |
| B | [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract.json) | PASS | 7.48% | 2.08% | 6.25% |
| B | [ipm_vshape_8p12s_deep_apex_contract](fixtures/ipm_vshape_8p12s_deep_apex_contract.json) | FAIL | 36.02% | 4.88% | 4.77% |
| B | [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract.json) | PASS | 4.12% | 3.55% | 4.43% |
| B | [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract.json) | PASS | 5.40% | 1.33% | 3.01% |
| B | [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract.json) | PASS | 1.80% | 0.85% | 1.70% |
| B | [ipm_vshape_8p12s_wide_angle_contract](fixtures/ipm_vshape_8p12s_wide_angle_contract.json) | FAIL | 12.41% | 36.03% | 25.16% |
| C | [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm.json) | UNSUPPORTED | - | - | - |
| C | [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation.json) | PASS | 2.98% | 0.98% | 0.59% |
| C | [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation.json) | PASS | 1.13% | 0.51% | 0.28% |
| C | [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6.json) | PASS | 0.62% | 0.80% | 0.12% |
| C | [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation.json) | PASS | 0.57% | 0.87% | 0.98% |

## Unsupported cases

- ornl_prius_2004_ipm: The public launch supports flat-buried and V-shape IPM only.
- Thermal: public requests exclude thermal validation; thermal coverage is outside the A-D benchmark matrix.

## Evidence

- `benchmark_summary.json`: provenance, gates and native metadata.
- `benchmark_rows.csv`: headline metrics.
- `rows/`: compact inputs, candidate and fresh matched reference waveforms.
- `fixtures/`: exact registered input JSON for each linked fixture; hashes are included in JSON, CSV and the artifact manifest.
- Original registered requests and raw execution logs remain in the frozen local snapshot; their hashes and numerical waveforms are retained here.
- `README.md`: run, resume and report commands.

## Phase D results - BLDC

Ideal six-step 120-degree wye BLDC: fresh public native/FEMM torque, currents and commutation; angular convergence; native low-current Back-EMF power balance.

Fourteen historical gates per fixture are unchanged. Fine increases angular samples using the same normal spatial mesh. Analytical denotes a native low-current field solve with Back-EMF. Thermal coverage is unsupported by the public API and is outside the A-D benchmark matrix.

Matrix state: **COMPLETE**.

### [spm_4p12s_small](fixtures/bldc_spm_4p12s_small_native-standard.json)

PASS; 4/4 stages complete.

| Stage / input | Status | Samples | Runtime (s) |
| --- | --- | ---: | ---: |
| [native-standard](fixtures/bldc_spm_4p12s_small_native-standard.json) | COMPLETE | 48 | 84.071 |
| [femm-standard](fixtures/bldc_spm_4p12s_small_femm-standard.json) | COMPLETE | 48 | 327.1 |
| [native-fine](fixtures/bldc_spm_4p12s_small_native-fine.json) | COMPLETE | 96 | 168.4 |
| [analytical](fixtures/bldc_spm_4p12s_small_analytical.json) | COMPLETE | 96 | 229.06 |

| Gate | Status | Value | Maximum / requirement |
| --- | --- | --- | --- |
| mean_torque_delta_pct | PASS | 0.1979 | 5 |
| torque_waveform_nrmse_pct | PASS | 0.5301 | 10 |
| commutation_transition_delta_samples | PASS | 0 | 1 |
| power_torque_delta_pct | PASS | 0.32774 | 10 |
| native_standard_to_fine_mean_torque_delta_pct | PASS | 0.20983 | 2 |
| native_standard_to_fine_ripple_delta_percentage_points | PASS | 1.0386 | 5 |
| native_standard_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| native_fine_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| femm_standard_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| analytical_low_current_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| native-standard_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| femm-standard_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| native-fine_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| analytical_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |

Measured mean torque: Coilem standard 0.28705 N m; FEMM standard 0.28648 N m; Coilem fine 0.28765 N m.
Low-current mean electromagnetic power 18.03 W; speed 628.32 rad/s. Torque from power 0.028696 / field torque 0.02879 N m; difference 0.32774%.

[Evidence](rows/bldc_spm_4p12s_small.json); [original fixture JSON](fixtures/source_spm_4p12s_small.json). Plots are included in the HTML and PDF.

### [spm_8p12s_reference](fixtures/bldc_spm_8p12s_reference_native-standard.json)

PASS; 4/4 stages complete.

| Stage / input | Status | Samples | Runtime (s) |
| --- | --- | ---: | ---: |
| [native-standard](fixtures/bldc_spm_8p12s_reference_native-standard.json) | COMPLETE | 48 | 108.24 |
| [femm-standard](fixtures/bldc_spm_8p12s_reference_femm-standard.json) | COMPLETE | 48 | 471.27 |
| [native-fine](fixtures/bldc_spm_8p12s_reference_native-fine.json) | COMPLETE | 96 | 214.47 |
| [analytical](fixtures/bldc_spm_8p12s_reference_analytical.json) | COMPLETE | 96 | 266.92 |

| Gate | Status | Value | Maximum / requirement |
| --- | --- | --- | --- |
| mean_torque_delta_pct | PASS | 0.85233 | 5 |
| torque_waveform_nrmse_pct | PASS | 1.2849 | 10 |
| commutation_transition_delta_samples | PASS | 0 | 1 |
| power_torque_delta_pct | PASS | 0.31922 | 10 |
| native_standard_to_fine_mean_torque_delta_pct | PASS | 0.14724 | 2 |
| native_standard_to_fine_ripple_delta_percentage_points | PASS | 2.7551 | 5 |
| native_standard_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| native_fine_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| femm_standard_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| analytical_low_current_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| native-standard_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| femm-standard_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| native-fine_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| analytical_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |

Measured mean torque: Coilem standard 8.7255 N m; FEMM standard 8.8005 N m; Coilem fine 8.7384 N m.
Low-current mean electromagnetic power 273.91 W; speed 314.16 rad/s. Torque from power 0.87187 / field torque 0.87466 N m; difference 0.31922%.

[Evidence](rows/bldc_spm_8p12s_reference.json); [original fixture JSON](fixtures/source_spm_8p12s_reference.json). Plots are included in the HTML and PDF.

### [spm_14p12s_high_pole](fixtures/bldc_spm_14p12s_high_pole_native-standard.json)

PASS; 4/4 stages complete.

| Stage / input | Status | Samples | Runtime (s) |
| --- | --- | ---: | ---: |
| [native-standard](fixtures/bldc_spm_14p12s_high_pole_native-standard.json) | COMPLETE | 96 | 258.6 |
| [femm-standard](fixtures/bldc_spm_14p12s_high_pole_femm-standard.json) | COMPLETE | 96 | 919.81 |
| [native-fine](fixtures/bldc_spm_14p12s_high_pole_native-fine.json) | COMPLETE | 192 | 522.81 |
| [analytical](fixtures/bldc_spm_14p12s_high_pole_analytical.json) | COMPLETE | 96 | 323.29 |

| Gate | Status | Value | Maximum / requirement |
| --- | --- | --- | --- |
| mean_torque_delta_pct | PASS | 0.056287 | 5 |
| torque_waveform_nrmse_pct | PASS | 0.86748 | 10 |
| commutation_transition_delta_samples | PASS | 0 | 1 |
| power_torque_delta_pct | PASS | 0.66866 | 10 |
| native_standard_to_fine_mean_torque_delta_pct | PASS | 0.39969 | 2 |
| native_standard_to_fine_ripple_delta_percentage_points | PASS | 3.3892 | 5 |
| native_standard_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| native_fine_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| femm_standard_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| analytical_low_current_current_properties | PASS | sum A: 0; plateau A: 0; zero A: 0; invalid: 0 | sum A: 1e-09; current A: 1e-09; invalid: 0 |
| native-standard_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| femm-standard_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| native-fine_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |
| analytical_golden_current_sequence | PASS | matches frozen golden current table | exact phase sequence within frozen current tolerance |

Measured mean torque: Coilem standard 1.6396 N m; FEMM standard 1.6405 N m; Coilem fine 1.6331 N m.
Low-current mean electromagnetic power 34.158 W; speed 209.44 rad/s. Torque from power 0.16309 / field torque 0.16419 N m; difference 0.66866%.

[Evidence](rows/bldc_spm_14p12s_high_pole.json); [original fixture JSON](fixtures/source_spm_14p12s_high_pole.json). Plots are included in the HTML and PDF.
