# Coilem A/B/C/D benchmark

Outcome: **FAIL**

Harness 1.0.0; protocol 1.0.0.
Candidate commit: `45e0a5c7662ade04a4be5519b7e5bac771a6122f`. Reference mode: `FROZEN_REFERENCE`.
Reference commit: `8b95decda27d475ddbb75e99d92744ebc8e53b28`. No reference solves executed.

| Phase | Outcomes |
|---|---|
| A – SPM | 10 PASS |
| B – IPM | 2 FAIL, 10 PASS |
| C – Distributed Winding | 4 PASS, 1 UNSUPPORTED |
| D – BLDC | 3 PASS |

- [spm_4p12s_simple__baseline](fixtures/spm_4p12s_simple__baseline__native.json): **PASS**

- [spm_4p12s_simple__high_current](fixtures/spm_4p12s_simple__high_current__native.json): **PASS**

- [spm_4p12s_simple__tight_airgap](fixtures/spm_4p12s_simple__tight_airgap__native.json): **PASS**

- [spm_4p12s_simple_noload__baseline](fixtures/spm_4p12s_simple_noload__baseline__native.json): **PASS**

- [spm_4p12s_simple_noload__high_current](fixtures/spm_4p12s_simple_noload__high_current__native.json): **PASS**

- [spm_4p12s_simple_noload__tight_airgap](fixtures/spm_4p12s_simple_noload__tight_airgap__native.json): **PASS**

- [spm_8p12s_concentrated__baseline](fixtures/spm_8p12s_concentrated__baseline__native.json): **PASS**

- [spm_8p12s_concentrated__high_current](fixtures/spm_8p12s_concentrated__high_current__native.json): **PASS**

- [spm_8p12s_concentrated__tight_airgap](fixtures/spm_8p12s_concentrated__tight_airgap__native.json): **PASS**

- [spm_8p12s_reference_angle30__baseline](fixtures/spm_8p12s_reference_angle30__baseline__native.json): **PASS**

- [ipm_flat_12s10p_fscw_contract](fixtures/ipm_flat_12s10p_fscw_contract__native.json): **PASS**

- [ipm_flat_24s16p_industrial_contract](fixtures/ipm_flat_24s16p_industrial_contract__native.json): **PASS**

- [ipm_flat_4p12s_micro_contract](fixtures/ipm_flat_4p12s_micro_contract__native.json): **PASS**

- [ipm_flat_8p12s_fsae_angled_pocket_contract](fixtures/ipm_flat_8p12s_fsae_angled_pocket_contract__native.json): **PASS**

- [ipm_flat_8p12s_fsae_contract](fixtures/ipm_flat_8p12s_fsae_contract__native.json): **PASS**

- [ipm_flat_8p12s_fsae_thin_bridge_contract](fixtures/ipm_flat_8p12s_fsae_thin_bridge_contract__native.json): **PASS**

- [ipm_vshape_8p12s_baseline_contract](fixtures/ipm_vshape_8p12s_baseline_contract__native.json): **PASS**

- [ipm_vshape_8p12s_deep_apex_contract](fixtures/ipm_vshape_8p12s_deep_apex_contract__native.json): **FAIL**

- [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json): **PASS**

- [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json): **PASS**

- [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json): **PASS**

- [ipm_vshape_8p12s_wide_angle_contract](fixtures/ipm_vshape_8p12s_wide_angle_contract__native.json): **FAIL**

- [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json): **UNSUPPORTED**

- [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json): **PASS**

- [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json): **PASS**

- [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json): **PASS**

- [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json): **PASS**

- [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json): **PASS**

- [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json): **PASS**

- [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json): **PASS**
