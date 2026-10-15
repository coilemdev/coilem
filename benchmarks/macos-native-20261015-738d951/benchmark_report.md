# Coilem A/B/C/D benchmark

Outcome: **FAIL**

Harness 1.3.0; protocol 1.1.0.
Candidate commit: `738d9516e8500c5996c772bd96470472cbb9a0f9`. Reference mode: `NATIVE_ONLY`.
Reference commit: `none`. No reference solves executed.

| Phase | Outcomes |
|---|---|
| A – SPM | 10 NOT_COMPARED |
| B – IPM | 12 NOT_COMPARED |
| C – Distributed Winding | 4 NOT_COMPARED, 1 Planned coverage (not yet supported) |
| D – BLDC | 2 FAIL, 1 NOT_COMPARED |

- [spm_4p12s_simple__baseline](fixtures/spm_4p12s_simple__baseline__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004

- [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004

- [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004

- [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline__native.json): **NOT_COMPARED**

- [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.004

- [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap__native.json): **NOT_COMPARED**

- [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.009

- [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.006

- [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.003

- [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.007

- [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.011

- [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.995

- [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.000

- [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.910

- [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.995

- [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.985

- [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.186

- [ipm_vshape_8p12s_deep_apex_high_output_v1](fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.297

- [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.170

- [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.484

- [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.072

- [ipm_vshape_8p12s_wide_angle_high_output_v1](fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 1.186

- [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json): **Planned coverage (not yet supported)**

The Prius fixture uses HoleM50 rotor geometry; the public API currently accepts flat-buried and V-shape IPM only. Qualify the Prius geometry, native mesh and field solves against matched FEMM evidence before enabling public support. Numerical status remains UNSUPPORTED; no comparison was performed.

- [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.765

- [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.846

- [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.973

- [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json): **NOT_COMPARED**. Energy balance, torque / (3·E·I·cos γ / ω): coilEM 0.991

- [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json): **FAIL**

- [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json): **NOT_COMPARED**

- [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json): **FAIL**
