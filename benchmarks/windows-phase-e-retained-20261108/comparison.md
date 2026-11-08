# Retained experimental Windows Phase E comparison

**EXPERIMENTAL — cogging remains unqualified.**

These are unchanged native measurements at `a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f`, regraded against their retained selected FEMM references.
No new v0.5.5 native collection or field solve was performed.

| Case | Verdict | Peak-to-peak error | First-harmonic error |
|---|---|---:|---:|
| spm_4p12s_simple__baseline__cogging | PASS | 0.0918% | 0.2202% |
| spm_4p12s_simple__tight_airgap__cogging | PASS | 0.8621% | 1.0790% |
| spm_8p12s_concentrated__baseline__cogging | PASS | 5.8136% | 3.5804% |
| spm_8p12s_concentrated__tight_airgap__cogging | PASS | 5.1914% | 1.3163% |
| spm_8p12s_example_shoed__cogging | PASS | 2.4326% | 1.3674% |
| ipm_flat_8p12s_fsae_contract__cogging | PASS | 0.6128% | 0.7274% |
| ipm_flat_8p12s_fsae_angled_pocket_contract__cogging | PASS | 0.8732% | 0.6203% |
| ipm_flat_12s10p_fscw_contract__cogging | PASS | 5.8799% | 6.0379% |
| ipm_flat_24s16p_industrial_contract__cogging | PASS | 2.4231% | 0.8707% |
| spm_8p24s_distributed_femm_validation__cogging | YELLOW | 10.7285% | 10.1743% |
| spm_8p48s_distributed_femm_validation__cogging | PASS | 9.0979% | 7.2982% |
| spm_12p36s_distributed_femm_validation__cogging | YELLOW | 11.1966% | 9.2421% |

Original outcomes remain 10 PASS / 2 YELLOW. Nine baseline references and three previously selected half-gap distributed references are retained.
All twelve selected reference period/mean self-checks pass. The historical three baseline reference failures remain in comparison.json.
The fixed relative PASS/YELLOW limits are 10%/20%, with each registered absolute floor. This dataset has no accepted reference review or qualification record.

Reference dataset: `sha256:74519b52191c8d711704b9db1044cf130050637d940d56382f5eba0769c76227`.
