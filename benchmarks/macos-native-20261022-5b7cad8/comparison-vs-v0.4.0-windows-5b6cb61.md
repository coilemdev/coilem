New: PASS_WITH_UNSUPPORTED {'PASS': 29, 'UNSUPPORTED': 1}
Windows 5b6cb61: YELLOW {'PASS': 28, 'YELLOW': 1, 'UNSUPPORTED': 1}
macOS 738d951 (native only): FAIL {'NOT_COMPARED': 27, 'UNSUPPORTED': 1, 'FAIL': 2}

| Case | Ph | Status (Win → new) | Torque new (N·m) | vs FEMM Win → new | Torque shift vs Win | vs macOS 738d951 | Back-EMF vs FEMM Win → new |
|---|---|---|---|---|---|---|---|
| spm_4p12s_simple__baseline | A | PASS → PASS | 0.4775 | +0.25% → +0.08% | -0.17% | -0.17% | 0.01% → 0.03% |
| spm_4p12s_simple__high_current | A | PASS → PASS | 0.7160 | +0.17% → +0.00% | -0.17% | -0.17% | 0.01% → 0.03% |
| spm_4p12s_simple__tight_airgap | A | PASS → PASS | 0.5819 | -0.41% → -0.54% | -0.13% | -0.14% | 0.34% → 0.35% |
| spm_4p12s_simple_noload__baseline | A | PASS → PASS | 0.0000 | near zero | — | — | 0.01% → 0.03% |
| spm_4p12s_simple_noload__high_current | A | PASS → PASS | 0.2388 | +0.48% → +0.31% | -0.17% | -0.17% | 0.01% → 0.03% |
| spm_4p12s_simple_noload__tight_airgap | A | PASS → PASS | -0.0002 | near zero | — | — | 0.34% → 0.35% |
| spm_8p12s_concentrated__baseline | A | PASS → PASS | 2.2085 | +0.19% → -0.24% | -0.43% | -0.43% | 0.00% → 0.02% |
| spm_8p12s_concentrated__high_current | A | PASS → PASS | 3.3048 | +0.11% → -0.31% | -0.41% | -0.41% | 0.00% → 0.02% |
| spm_8p12s_concentrated__tight_airgap | A | PASS → PASS | 2.3421 | -0.25% → -0.63% | -0.38% | -0.38% | 0.05% → 0.06% |
| spm_8p12s_reference_angle30__baseline | A | PASS → PASS | 16.5888 | -0.32% → -0.49% | -0.17% | -0.17% | 0.11% → 0.10% |
| ipm_flat_12s10p_fscw_contract | B | PASS → PASS | 4.8071 | +0.57% → +0.09% | -0.47% | -0.48% | 0.49% → 0.57% |
| ipm_flat_24s16p_industrial_contract | B | PASS → PASS | 19.3974 | -0.64% → -0.66% | -0.02% | -0.02% | 0.18% → 0.14% |
| ipm_flat_4p12s_micro_contract | B | PASS → PASS | 0.0214 | -0.47% → -0.60% | -0.14% | -0.13% | 0.56% → 0.36% |
| ipm_flat_8p12s_fsae_angled_pocket_contract | B | PASS → PASS | 2.1552 | +0.20% → +0.02% | -0.18% | -0.18% | 0.27% → 0.26% |
| ipm_flat_8p12s_fsae_contract | B | PASS → PASS | 2.5674 | -0.14% → -0.32% | -0.18% | -0.18% | 0.26% → 0.26% |
| ipm_flat_8p12s_fsae_thin_bridge_contract | B | PASS → PASS | 3.1707 | +0.01% → -0.18% | -0.20% | -0.20% | 0.23% → 0.23% |
| ipm_vshape_8p12s_baseline_contract | B | YELLOW → PASS | 0.8971 | +5.85% → +7.05% | +1.13% | +0.95% | 2.06% → 8.29% |
| ipm_vshape_8p12s_deep_apex_high_output_v1 | B | PASS → PASS | 0.6571 | +4.32% → +5.08% | +0.74% | +0.80% | 3.35% → 8.20% |
| ipm_vshape_8p12s_narrow_angle_contract | B | PASS → PASS | 0.8931 | +4.17% → +4.40% | +0.22% | +0.29% | 3.39% → 4.71% |
| ipm_vshape_8p12s_pocket_offset_contract | B | PASS → PASS | 1.1113 | +4.55% → +5.07% | +0.50% | +0.58% | 1.40% → 8.12% |
| ipm_vshape_8p12s_thin_bridge_contract | B | PASS → PASS | 2.6862 | +2.50% → +2.58% | +0.07% | +0.07% | 0.76% → 1.11% |
| ipm_vshape_8p12s_wide_angle_high_output_v1 | B | PASS → PASS | 0.7860 | +5.90% → +6.60% | +0.66% | +0.78% | 3.37% → 8.61% |
| ornl_prius_2004_ipm | C | UNSUPPORTED → UNSUPPORTED | None | — → — | — | — | — → — |
| spm_12p36s_distributed_femm_validation | C | PASS → PASS | 4.9435 | -4.90% → -5.20% | -0.32% | -0.40% | 0.23% → 0.31% |
| spm_8p24s_distributed_femm_validation | C | PASS → PASS | 5.4892 | -2.42% → -3.05% | -0.65% | -0.61% | 0.15% → 0.22% |
| spm_8p48s_chorded_5_6 | C | PASS → PASS | 5.8949 | -1.64% → -1.65% | -0.01% | +0.06% | 0.19% → 0.23% |
| spm_8p48s_distributed_femm_validation | C | PASS → PASS | 6.2047 | -1.70% → -1.57% | +0.14% | -0.05% | 0.15% → 0.18% |

Phase D (BLDC):
- spm_14p12s_high_pole: PASS → PASS; gate changes: none
- spm_4p12s_small: PASS → PASS; gate changes: none
- spm_8p12s_reference: PASS → PASS; gate changes: none
