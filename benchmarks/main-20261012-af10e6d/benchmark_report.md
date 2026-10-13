# Coilem A/B/C/D benchmark

Outcome: **PASS with planned coverage (not yet supported)**

Harness 1.2.1; protocol 1.1.0.
Candidate commit: `af10e6dc8a5b3fc488ec96e4988fd50f2752b60d`. Reference mode: `FROZEN_REFERENCE`.
Reference commit: `8b95decda27d475ddbb75e99d92744ebc8e53b28`. No reference solves executed.

| Phase | Outcomes |
|---|---|
| A – SPM | 10 PASS |
| B – IPM | 12 PASS |
| C – Distributed Winding | 4 PASS, 1 Planned coverage (not yet supported) |
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

- [ipm_vshape_8p12s_deep_apex_high_output_v1](fixtures/ipm_vshape_8p12s_deep_apex_high_output_v1__native.json): **PASS**

- [ipm_vshape_8p12s_narrow_angle_contract](fixtures/ipm_vshape_8p12s_narrow_angle_contract__native.json): **PASS**

- [ipm_vshape_8p12s_pocket_offset_contract](fixtures/ipm_vshape_8p12s_pocket_offset_contract__native.json): **PASS**

- [ipm_vshape_8p12s_thin_bridge_contract](fixtures/ipm_vshape_8p12s_thin_bridge_contract__native.json): **PASS**

- [ipm_vshape_8p12s_wide_angle_high_output_v1](fixtures/ipm_vshape_8p12s_wide_angle_high_output_v1__native.json): **PASS**

- [ornl_prius_2004_ipm](fixtures/ornl_prius_2004_ipm__native.json): **Planned coverage (not yet supported)**

The Prius fixture uses HoleM50 rotor geometry; the public API currently accepts flat-buried and V-shape IPM only. Qualify the Prius geometry, native mesh and field solves against matched FEMM evidence before enabling public support. Numerical status remains UNSUPPORTED; no comparison was performed.

- [spm_12p36s_distributed_femm_validation](fixtures/spm_12p36s_distributed_femm_validation__native.json): **PASS**

- [spm_8p24s_distributed_femm_validation](fixtures/spm_8p24s_distributed_femm_validation__native.json): **PASS**

- [spm_8p48s_chorded_5_6](fixtures/spm_8p48s_chorded_5_6__native.json): **PASS**

- [spm_8p48s_distributed_femm_validation](fixtures/spm_8p48s_distributed_femm_validation__native.json): **PASS**

- [spm_14p12s_high_pole](fixtures/spm_14p12s_high_pole__native-standard.json): **PASS**

- [spm_4p12s_small](fixtures/spm_4p12s_small__native-standard.json): **PASS**

- [spm_8p12s_reference](fixtures/spm_8p12s_reference__native-standard.json): **PASS**
