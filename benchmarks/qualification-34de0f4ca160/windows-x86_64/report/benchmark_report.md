# Coilem A/B/C/D benchmark

Outcome: **PASS for supported cases; deferred hardware coverage (v0.5.0)**

Harness 1.10.0; protocol 1.6.0.
Report presentation: 1.10.0.
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

- [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.002, reference 1.002

- [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.002, reference 1.004

- [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline__native.json): **PASS**

- [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.003, reference 0.999

- [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap__native.json): **PASS**

- [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.007

- [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.002, reference 1.005

- [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.000, reference 1.005

- [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.009

- [spm_8p12s_example_shoed](fixtures/spm_8p12s_example_shoed__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004, reference 0.999

- [spm_8p12s_concentrated__magnet_60C](fixtures/spm_8p12s_concentrated__magnet_60C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.007

- [spm_8p12s_concentrated__magnet_100C](fixtures/spm_8p12s_concentrated__magnet_100C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.007

- [spm_8p12s_concentrated__dq_I20_g0](fixtures/spm_8p12s_concentrated__dq_I20_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.003

- [spm_8p12s_concentrated__dq_I20_g30](fixtures/spm_8p12s_concentrated__dq_I20_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.009, reference 1.007

- [spm_8p12s_concentrated__dq_I20_g60](fixtures/spm_8p12s_concentrated__dq_I20_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.012, reference 1.008

- [spm_8p12s_concentrated__dq_I40_g0](fixtures/spm_8p12s_concentrated__dq_I40_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.999, reference 0.999

- [spm_8p12s_concentrated__dq_I40_g30](fixtures/spm_8p12s_concentrated__dq_I40_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.006, reference 1.006

- [spm_8p12s_concentrated__dq_I40_g60](fixtures/spm_8p12s_concentrated__dq_I40_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.008, reference 1.005

- [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.005, reference 1.010

- [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.994, reference 1.000

- [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.997, reference 0.999

- [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.908, reference 0.905

- [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.993, reference 0.994

- [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.983, reference 0.983

- [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.128, reference 1.142

- [ipm_vshape_8p12s_deep_apex_high_output_v1](fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.249, reference 1.286

- [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.158, reference 1.162

- [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.400, reference 1.441

- [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.069, reference 1.054

- [ipm_vshape_8p12s_wide_angle_high_output_v1](fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.137, reference 1.159

- [ipm_flat_8p12s_fsae_contract__magnet_60C](fixtures/ipm_flat_8p12s_fsae_contract__magnet_60C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.994, reference 0.995

- [ipm_flat_8p12s_fsae_contract__magnet_100C](fixtures/ipm_flat_8p12s_fsae_contract__magnet_100C__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.995, reference 0.995

- [ipm_flat_8p12s_fsae_contract__dq_I50_g0](fixtures/ipm_flat_8p12s_fsae_contract__dq_I50_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.993, reference 0.992

- [ipm_flat_8p12s_fsae_contract__dq_I50_g30](fixtures/ipm_flat_8p12s_fsae_contract__dq_I50_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.017, reference 1.015

- [ipm_flat_8p12s_fsae_contract__dq_I50_g60](fixtures/ipm_flat_8p12s_fsae_contract__dq_I50_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.032, reference 1.030

- [ipm_flat_8p12s_fsae_contract__dq_I100_g0](fixtures/ipm_flat_8p12s_fsae_contract__dq_I100_g0__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.998, reference 0.997

- [ipm_flat_8p12s_fsae_contract__dq_I100_g30](fixtures/ipm_flat_8p12s_fsae_contract__dq_I100_g30__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.044, reference 1.042

- [ipm_flat_8p12s_fsae_contract__dq_I100_g60](fixtures/ipm_flat_8p12s_fsae_contract__dq_I100_g60__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.080, reference 1.078

- [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json): **Deferred hardware coverage (v0.5.0)**

This legacy ORNL-derived HoleM50 fixture remains unsupported in the registered suite. The separate fixed Pyleecan software references have different case IDs and inputs. Resolve the ORNL reconstruction and matched-reference scope separately; Pyleecan software reproduction does not qualify this legacy hardware fixture. Numerical status remains UNSUPPORTED; no comparison was performed.

- [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.762, reference 0.801

- [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.841, reference 0.866

- [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.974, reference 0.988

- [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.990, reference 1.004

- [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json): **PASS**

- [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json): **PASS**

- [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json): **PASS**
