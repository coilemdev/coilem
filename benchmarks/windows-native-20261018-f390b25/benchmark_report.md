# Coilem A/B/C/D benchmark

Outcome: **YELLOW**

Harness 1.5.0; protocol 1.3.0.
Candidate commit: `f390b252d8c7dddc3b7ff9f2c1c4f6cbf1d10d4c`. Reference mode: `FROZEN_REFERENCE`.
Reference commit: `738d9516e8500c5996c772bd96470472cbb9a0f9`. No reference solves executed.


| Phase | Outcomes |
|---|---|
| A – SPM | 10 PASS |
| B – IPM | 11 PASS, 1 YELLOW |
| C – Distributed Winding | 4 PASS, 1 Planned coverage (not yet supported) |
| D – BLDC | 3 PASS |

- [spm_4p12s_simple__baseline](fixtures/spm_4p12s_simple__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004, reference 1.002

- [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004, reference 1.002

- [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004, reference 1.004

- [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline__native.json): **PASS**

- [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004, reference 0.999

- [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap__native.json): **PASS**

- [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.009, reference 1.007

- [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.006, reference 1.005

- [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.003, reference 1.005

- [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.007, reference 1.009

- [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.011, reference 1.010

- [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.995, reference 1.000

- [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.000, reference 0.999

- [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.910, reference 0.905

- [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.995, reference 0.994

- [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.985, reference 0.983

- [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract__native.json): **YELLOW**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.184, reference 1.142

- [ipm_vshape_8p12s_deep_apex_high_output_v1](fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.298, reference 1.286

- [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.170, reference 1.162

- [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.486, reference 1.441

- [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.072, reference 1.054

- [ipm_vshape_8p12s_wide_angle_high_output_v1](fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.187, reference 1.159

- [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json): **Planned coverage (not yet supported)**

The Prius fixture uses HoleM50 rotor geometry; the public API currently accepts flat-buried and V-shape IPM only. Qualify the Prius geometry, native mesh and field solves against matched FEMM evidence before enabling public support. Numerical status remains UNSUPPORTED; no comparison was performed.

- [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.764, reference 0.801

- [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.846, reference 0.866

- [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.974, reference 0.988

- [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json): **PASS**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.989, reference 1.004

- [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json): **PASS**

- [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json): **PASS**

- [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json): **PASS**
