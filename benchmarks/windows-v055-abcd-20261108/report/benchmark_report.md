# Coilem A/B/C/D benchmark

Outcome: **PASS for supported cases; deferred hardware coverage (v0.5.0)**

Harness 1.10.0; protocol 1.6.0.
Report presentation: 1.11.0.
Candidate commit: `34de0f4ca1604311f15edf6fb49b5a2a1bf27909`. Reference mode: `FROZEN_REFERENCE`.
Reference commit: `faced858937e93740ddf7f6f3583a3ad5ec35646`. No reference solves executed.


| Phase | Outcomes |
|---|---|
| A – SPM | 19 PASS |
| B – IPM | 20 PASS |
| C – Distributed Winding | 1 Deferred hardware coverage (v0.5.0), 4 PASS |
| D – BLDC | 3 PASS |

Phase colors cover active cases; explicitly deferred hardware rows are grey. All raw statuses, counts, gates and the overall numerical status include the full registered selection.
The legacy ORNL Prius row is distinct from the completed Pyleecan Prius software benchmark.

- [spm_4p12s_simple__baseline](fixtures/spm_4p12s_simple__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.003, reference 1.002

Mean torque numerical resolution (diagnostic only): absolute difference 0.39644 mNm; relative difference 0.0830975%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.002, reference 1.002

Mean torque numerical resolution (diagnostic only): absolute difference 0.0376502 mNm; relative difference 0.00525833%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.002, reference 1.004

Mean torque numerical resolution (diagnostic only): absolute difference 3.23905 mNm; relative difference 0.553672%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline__native.json): **PASS**

Mean torque numerical resolution (diagnostic only): absolute difference 0.651491 mNm; relative difference suppressed near zero. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.003, reference 0.999

Mean torque numerical resolution (diagnostic only): absolute difference 0.743316 mNm; relative difference 0.31228%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap__native.json): **PASS**

Mean torque numerical resolution (diagnostic only): absolute difference 2.01519 mNm; relative difference suppressed near zero. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.007

Mean torque numerical resolution (diagnostic only): absolute difference 5.22235 mNm; relative difference 0.235908%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.002, reference 1.005

Mean torque numerical resolution (diagnostic only): absolute difference 10.1665 mNm; relative difference 0.306683%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.000, reference 1.005

Mean torque numerical resolution (diagnostic only): absolute difference 14.9115 mNm; relative difference 0.632629%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.009

Mean torque numerical resolution (diagnostic only): absolute difference 82.2695 mNm; relative difference 0.493485%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_example_shoed](fixtures/spm_8p12s_example_shoed__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004, reference 0.999

Mean torque numerical resolution (diagnostic only): absolute difference 43.1084 mNm; relative difference 0.386955%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__magnet_60C](fixtures/spm_8p12s_concentrated__magnet_60C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.007

Mean torque numerical resolution (diagnostic only): absolute difference 4.42021 mNm; relative difference 0.208862%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__magnet_100C](fixtures/spm_8p12s_concentrated__magnet_100C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.007

Mean torque numerical resolution (diagnostic only): absolute difference 3.55185 mNm; relative difference 0.176243%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__dq_I20_g0](fixtures/spm_8p12s_concentrated__dq_I20_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.003

Mean torque numerical resolution (diagnostic only): absolute difference 3.57482 mNm; relative difference 0.162129%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__dq_I20_g30](fixtures/spm_8p12s_concentrated__dq_I20_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.009, reference 1.007

Mean torque numerical resolution (diagnostic only): absolute difference 4.63108 mNm; relative difference 0.241683%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__dq_I20_g60](fixtures/spm_8p12s_concentrated__dq_I20_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.012, reference 1.008

Mean torque numerical resolution (diagnostic only): absolute difference 5.26327 mNm; relative difference 0.475306%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__dq_I40_g0](fixtures/spm_8p12s_concentrated__dq_I40_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.999, reference 0.999

Mean torque numerical resolution (diagnostic only): absolute difference 2.23087 mNm; relative difference 0.0508008%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__dq_I40_g30](fixtures/spm_8p12s_concentrated__dq_I40_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.006, reference 1.006

Mean torque numerical resolution (diagnostic only): absolute difference 4.8436 mNm; relative difference 0.126537%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p12s_concentrated__dq_I40_g60](fixtures/spm_8p12s_concentrated__dq_I40_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.008, reference 1.005

Mean torque numerical resolution (diagnostic only): absolute difference 5.81277 mNm; relative difference 0.263066%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.010

Mean torque numerical resolution (diagnostic only): absolute difference 4.38179 mNm; relative difference 0.0912363%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.994, reference 1.000

Mean torque numerical resolution (diagnostic only): absolute difference 128.068 mNm; relative difference 0.655907%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.997, reference 0.999

Mean torque numerical resolution (diagnostic only): absolute difference 0.129551 mNm; relative difference 0.6013%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.908, reference 0.905

Mean torque numerical resolution (diagnostic only): absolute difference 0.375393 mNm; relative difference 0.0174211%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.993, reference 0.994

Mean torque numerical resolution (diagnostic only): absolute difference 8.27941 mNm; relative difference 0.321442%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.983, reference 0.983

Mean torque numerical resolution (diagnostic only): absolute difference 5.82845 mNm; relative difference 0.183486%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.128, reference 1.142

Mean torque numerical resolution (diagnostic only): absolute difference 58.8541 mNm; relative difference 7.02243%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_vshape_8p12s_deep_apex_high_output_v1](fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.249, reference 1.286

Mean torque numerical resolution (diagnostic only): absolute difference 31.7882 mNm; relative difference 5.0832%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.158, reference 1.162

Mean torque numerical resolution (diagnostic only): absolute difference 37.6572 mNm; relative difference 4.4022%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.400, reference 1.441

Mean torque numerical resolution (diagnostic only): absolute difference 53.7521 mNm; relative difference 5.08231%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.069, reference 1.054

Mean torque numerical resolution (diagnostic only): absolute difference 67.5547 mNm; relative difference 2.57977%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_vshape_8p12s_wide_angle_high_output_v1](fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.137, reference 1.159

Mean torque numerical resolution (diagnostic only): absolute difference 48.6222 mNm; relative difference 6.59403%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__magnet_60C](fixtures/ipm_flat_8p12s_fsae_contract__magnet_60C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.994, reference 0.995

Mean torque numerical resolution (diagnostic only): absolute difference 7.91156 mNm; relative difference 0.329357%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__magnet_100C](fixtures/ipm_flat_8p12s_fsae_contract__magnet_100C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.995, reference 0.995

Mean torque numerical resolution (diagnostic only): absolute difference 7.49761 mNm; relative difference 0.33633%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__dq_I50_g0](fixtures/ipm_flat_8p12s_fsae_contract__dq_I50_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.993, reference 0.992

Mean torque numerical resolution (diagnostic only): absolute difference 3.35815 mNm; relative difference 0.130627%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__dq_I50_g30](fixtures/ipm_flat_8p12s_fsae_contract__dq_I50_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.017, reference 1.015

Mean torque numerical resolution (diagnostic only): absolute difference 2.32718 mNm; relative difference 0.10213%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__dq_I50_g60](fixtures/ipm_flat_8p12s_fsae_contract__dq_I50_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.032, reference 1.030

Mean torque numerical resolution (diagnostic only): absolute difference 0.646081 mNm; relative difference 0.0483839%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__dq_I100_g0](fixtures/ipm_flat_8p12s_fsae_contract__dq_I100_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.998, reference 0.997

Mean torque numerical resolution (diagnostic only): absolute difference 7.3353 mNm; relative difference 0.141914%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__dq_I100_g30](fixtures/ipm_flat_8p12s_fsae_contract__dq_I100_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.044, reference 1.042

Mean torque numerical resolution (diagnostic only): absolute difference 4.73938 mNm; relative difference 0.101303%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ipm_flat_8p12s_fsae_contract__dq_I100_g60](fixtures/ipm_flat_8p12s_fsae_contract__dq_I100_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.080, reference 1.078

Mean torque numerical resolution (diagnostic only): absolute difference 1.68347 mNm; relative difference 0.0602778%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json): **Deferred hardware coverage (v0.5.0)**

This legacy ORNL-derived HoleM50 fixture remains unsupported in the registered suite. The separate fixed Pyleecan software references have different case IDs and inputs. Resolve the ORNL reconstruction and matched-reference scope separately; Pyleecan software reproduction does not qualify this legacy hardware fixture. Numerical status remains UNSUPPORTED; no comparison was performed.

- [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.762, reference 0.801

Mean torque numerical resolution (diagnostic only): absolute difference 269.068 mNm; relative difference 5.15966%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.841, reference 0.866

Mean torque numerical resolution (diagnostic only): absolute difference 173.079 mNm; relative difference 3.05684%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.974, reference 0.988

Mean torque numerical resolution (diagnostic only): absolute difference 98.4675 mNm; relative difference 1.64283%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.990, reference 1.004

Mean torque numerical resolution (diagnostic only): absolute difference 98.5915 mNm; relative difference 1.56402%. Noise sensitivity: no control evidence. Uncertainty: insufficient evidence. Recorded verdict and gates unchanged.

- [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json): **PASS**

- [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json): **PASS**

- [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json): **PASS**
