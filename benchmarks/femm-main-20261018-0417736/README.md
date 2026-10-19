# Fresh FEMM A/B/C/D repeat on main (October 18, 2026)

This is part of the [v0.4.0 release-planning report](../v0.4.0/README.md).
Native parity outcomes remain 28 PASS, 1 YELLOW and the planned unsupported Prius;
this repeat verifies reference reproducibility.

Reference-repeat status: **PASS**. Main `0417736249ae2926e05612ac58926cdc76cc8868`; clean measured checkout.

Completed 29/29 supported FEMM 4.2 cases. All physical payloads and both extraction audits exact: **True**.

Total wall time: **1h 49m 05s** (6544.722 s), compared with **1h 50m 54s** (6654.354 s) on October 16. Change: **-1.65%** (-109.633 s).

| Phase | Cases | Exact | Current worker sum (s) | Previous worker sum (s) | Change |
|---|---:|---:|---:|---:|---:|
| A | 10 | 10 | 4715.85 | 4728.44 | -0.27% |
| B | 12 | 12 | 16917.08 | 17073.26 | -0.91% |
| C | 4 | 4 | 14360.35 | 14824.51 | -3.13% |
| D | 3 | 3 | 1300.24 | 1241.51 | +4.73% |

Phase totals sum overlapping worker durations and are not elapsed phase wall times.

The same weighted 8-worker / cost-budget-8 policy and pinned FEMM producer, binaries, dependencies, requests and shared physics sources were used. The current-main payload option comparison helper has the reviewed array-safe equality change, recorded in the JSON evidence. The current-main scheduler ran the fresh collection. The private adapter retains its original source pin; the wrapper independently verifies compatibility with all 29 current-main registered requests and relevant shared sources.

## Per-case comparison

| Case | Phase | Exact | Current (s) | Previous (s) | Change |
|---|---|---|---:|---:|---:|
| `spm_4p12s_simple__baseline` | A | True | 385.77 | 391.39 | -1.43% |
| `spm_4p12s_simple__high_current` | A | True | 380.74 | 369.06 | +3.17% |
| `spm_4p12s_simple__tight_airgap` | A | True | 310.79 | 339.69 | -8.51% |
| `spm_4p12s_simple_noload__baseline` | A | True | 400.95 | 383.84 | +4.46% |
| `spm_4p12s_simple_noload__high_current` | A | True | 379.32 | 385.74 | -1.66% |
| `spm_4p12s_simple_noload__tight_airgap` | A | True | 311.20 | 319.70 | -2.66% |
| `spm_8p12s_concentrated__baseline` | A | True | 609.08 | 614.30 | -0.85% |
| `spm_8p12s_concentrated__high_current` | A | True | 599.50 | 615.79 | -2.65% |
| `spm_8p12s_concentrated__tight_airgap` | A | True | 640.66 | 650.30 | -1.48% |
| `spm_8p12s_reference_angle30__baseline` | A | True | 697.83 | 658.63 | +5.95% |
| `ipm_flat_12s10p_fscw_contract` | B | True | 1496.12 | 1529.78 | -2.20% |
| `ipm_flat_24s16p_industrial_contract` | B | True | 2018.53 | 2161.42 | -6.61% |
| `ipm_flat_4p12s_micro_contract` | B | True | 342.82 | 356.91 | -3.95% |
| `ipm_flat_8p12s_fsae_angled_pocket_contract` | B | True | 1135.88 | 1142.09 | -0.54% |
| `ipm_flat_8p12s_fsae_contract` | B | True | 1112.13 | 1008.53 | +10.27% |
| `ipm_flat_8p12s_fsae_thin_bridge_contract` | B | True | 1544.32 | 1553.92 | -0.62% |
| `ipm_vshape_8p12s_baseline_contract` | B | True | 1576.53 | 1569.75 | +0.43% |
| `ipm_vshape_8p12s_deep_apex_high_output_v1` | B | True | 1460.13 | 1625.60 | -10.18% |
| `ipm_vshape_8p12s_narrow_angle_contract` | B | True | 1645.46 | 1576.67 | +4.36% |
| `ipm_vshape_8p12s_pocket_offset_contract` | B | True | 1555.93 | 1552.29 | +0.23% |
| `ipm_vshape_8p12s_thin_bridge_contract` | B | True | 1537.21 | 1460.74 | +5.23% |
| `ipm_vshape_8p12s_wide_angle_high_output_v1` | B | True | 1492.04 | 1535.55 | -2.83% |
| `spm_12p36s_distributed_femm_validation` | C | True | 2246.46 | 2552.34 | -11.98% |
| `spm_8p24s_distributed_femm_validation` | C | True | 2032.62 | 2050.57 | -0.88% |
| `spm_8p48s_chorded_5_6` | C | True | 4930.89 | 5080.27 | -2.94% |
| `spm_8p48s_distributed_femm_validation` | C | True | 5150.38 | 5141.34 | +0.18% |
| `spm_14p12s_high_pole` | D | True | 747.27 | 675.72 | +10.59% |
| `spm_4p12s_small` | D | True | 204.63 | 202.57 | +1.02% |
| `spm_8p12s_reference` | D | True | 348.35 | 363.22 | -4.09% |

Exact comparisons exclude only timestamps, cache paths and elapsed timings. They retain full physical summaries, normalized results, raw/public waveforms, mesh counts, model/current contracts, slot excitation frames and flux/source extraction audits.

The unsupported Prius fixture remains outside the 29-case FEMM collection. The frozen baseline's scientific status remains REVIEW_REQUIRED.

## Retained evidence

- Fresh raw run: `<fresh-femm-run>`
- Previous raw run: `<previous-femm-run>`
- Fresh manifest SHA-256: `f4e5e720621fe0b259479d6db250603911117217c62d57b8131490993d8c2ce8`
- Previous manifest SHA-256: `8bfcdbc4abcbf4709c13aa038ff089b0aa9039f833eeedcef3be73fd5bc95f51`
- Per-case metrics, exact checks, source compatibility and runtime changes: `comparison.json`

## Execution audits

Recorded worker/cost limits, physical-core exclusivity and process assignments passed for all 29 cases. All 29 fresh FEMM session markers are unique and match their attempt records. No FEMM field processes remained after completion.

The legacy verifier passed every physical-payload and extraction check, then rejected one numeric PID appearing twice. The retained ownership audit establishes separate DispatchEx sessions: distinct markers, nonoverlapping jobs, and a 120.102408-second gap. The original assertion failure is preserved; producer and raw evidence were not changed.

- [Physical and timing comparison](comparison.json)
- [Concurrency audit](concurrency-check.json)
- [Session ownership audit](ownership-audit.json)
- [Machine and run session](session.json)
- [Artifact hashes](artifact_manifest.json)

Public copies normalize local paths only. Original run/result hashes refer to
locally retained, unmodified raw evidence. No private FEMM adapter code or raw
solver files are included. See [publication provenance](publication.json).
