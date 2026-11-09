# Windows FEMM diagnostic results for release v0.5.6

Original fresh A–D/F collection: `8b6b394f8a5b3408d07c1ff00c7c32f012fd0373`. Current release diagnostic: `11aa06b1aa45ceac7d3d1b7cd75fa96463b0c894`.

Publication targets release metadata based on `1d306a0f7dce574eb9a78b719893d3d41e4cbede`. That later metadata/version commit is not represented as a new field measurement.

The current diagnostic reuses the original measured A–D evidence through the audited guarded-source equivalence bridge, retaining its actual `8b6b394` identity. All ten F cases were separately measured at `11aa06b` with Newton; the original F native results use Picard. Independently built executable hashes and the exact snapshot metadata exception are in JSON.

Reference dataset `sha256:fc349808da4384b569239b7cbbd51d8a26e28385774e56b54a15c68afa343648` remains **REVIEW_REQUIRED**. This is a diagnostic report; it does not approve references, change gates, promote qualification, or waive any scientific finding.

## Case and physics-gate outcomes

| Cohort | Phase | Cases | Case outcomes | Gate outcomes |
|---|---|---:|---|---|
| Original 8b / Picard F | A | 19 | 19 PASS | 132 PASS |
| Original 8b / Picard F | B | 20 | 20 PASS | 138 PASS |
| Original 8b / Picard F | C | 5 | 4 PASS, 1 UNSUPPORTED | 24 PASS |
| Original 8b / Picard F | D | 3 | 3 PASS | 42 PASS |
| Original 8b / Picard F | F | 10 | 10 PASS | 60 PASS |
| Current diagnostic / Newton F | A | 19 | 19 PASS | 132 PASS |
| Current diagnostic / Newton F | B | 20 | 20 PASS | 138 PASS |
| Current diagnostic / Newton F | C | 5 | 4 PASS, 1 UNSUPPORTED | 24 PASS |
| Current diagnostic / Newton F | D | 3 | 3 PASS | 42 PASS |
| Current diagnostic / Newton F | F | 10 | 10 PASS | 60 PASS |

Every case status and registered gate is retained in the companion JSON, including FAIL, YELLOW, unsupported and diagnostic-only outcomes. A–D rows are reused evidence, not another measurement at the current commit. Phase D's stage-specific numerical gate values are in JSON; dashes below indicate that the A/B/C/F amplitude-error field does not apply.

### Original measured A–D and Picard F

| Case | Phase | Outcome | Mean torque error (%) | Absolute torque error (Nm) | EMF fundamental error (%) | EMF peak error (%) |
|---|---|---|---:|---:|---:|---:|
| `spm_4p12s_simple__baseline` | A | PASS | 0.0831218355 | 0.000396556104 | 0.0248098904 | 0.0152468426 |
| `spm_4p12s_simple__high_current` | A | PASS | 0.00528304322 | 3.7827094e-05 | 0.0248098904 | 0.0152468426 |
| `spm_4p12s_simple__tight_airgap` | A | PASS | 0.553561717 | 0.00323840339 | 0.34540406 | 0.0500524277 |
| `spm_4p12s_simple_noload__baseline` | A | PASS | 101.534227 | 0.000651491442 | 0.0248098904 | 0.0152468426 |
| `spm_4p12s_simple_noload__high_current` | A | PASS | 0.312304317 | 0.000743372975 | 0.0248098904 | 0.0152468426 |
| `spm_4p12s_simple_noload__tight_airgap` | A | PASS | 113.214501 | 0.00201507145 | 0.34540406 | 0.0500524277 |
| `spm_8p12s_concentrated__baseline` | A | PASS | 0.235823256 | 0.0052204736 | 0.0169918651 | 0.0504706777 |
| `spm_8p12s_concentrated__high_current` | A | PASS | 0.306593776 | 0.0101635553 | 0.0169918651 | 0.0504706777 |
| `spm_8p12s_concentrated__tight_airgap` | A | PASS | 0.632512237 | 0.0149087247 | 0.0621936796 | 0.192613675 |
| `spm_8p12s_reference_angle30__baseline` | A | PASS | 0.493363747 | 0.0822492218 | 0.101648783 | 0.0349147275 |
| `spm_8p12s_example_shoed` | A | PASS | 0.386952408 | 0.0431081388 | 0.103685721 | 0.00899633666 |
| `spm_8p12s_concentrated__magnet_60C` | A | PASS | 0.208809047 | 0.00441909951 | 0.00252598135 | 0.0153682444 |
| `spm_8p12s_concentrated__magnet_100C` | A | PASS | 0.17620365 | 0.0035510537 | 0.00274156248 | 0.00389582394 |
| `spm_8p12s_concentrated__dq_I20_g0` | A | PASS | 0.162213762 | 0.00357669311 | 0.0396131973 | 0.0163126459 |
| `spm_8p12s_concentrated__dq_I20_g30` | A | PASS | 0.241755019 | 0.00463245503 | 0.0396131973 | 0.0163126459 |
| `spm_8p12s_concentrated__dq_I20_g60` | A | PASS | 0.475376896 | 0.00526405807 | 0.0396131973 | 0.0163126459 |
| `spm_8p12s_concentrated__dq_I40_g0` | A | PASS | 0.0508958316 | 0.00223503992 | 0.0396131973 | 0.0163126459 |
| `spm_8p12s_concentrated__dq_I40_g30` | A | PASS | 0.126627039 | 0.0048470435 | 0.0396131973 | 0.0163126459 |
| `spm_8p12s_concentrated__dq_I40_g60` | A | PASS | 0.263143239 | 0.00581448138 | 0.0396131973 | 0.0163126459 |
| `ipm_flat_12s10p_fscw_contract` | B | PASS | 0.091236318 | 0.00438178997 | 0.568070507 | 0.504512303 |
| `ipm_flat_24s16p_industrial_contract` | B | PASS | 0.65590688 | 0.128068473 | 0.143820783 | 0.220032042 |
| `ipm_flat_4p12s_micro_contract` | B | PASS | 0.601300449 | 0.000129550652 | 0.363595768 | 0.515238031 |
| `ipm_flat_8p12s_fsae_angled_pocket_contract` | B | PASS | 0.0174210773 | 0.000375392852 | 0.257299852 | 0.361502704 |
| `ipm_flat_8p12s_fsae_contract` | B | PASS | 0.321442079 | 0.00827941481 | 0.256327784 | 0.216586378 |
| `ipm_flat_8p12s_fsae_thin_bridge_contract` | B | PASS | 0.18348607 | 0.00582844718 | 0.229030933 | 0.243181559 |
| `ipm_vshape_8p12s_baseline_contract` | B | PASS | 7.02242572 | 0.0588541182 | 8.28643862 | 9.01275571 |
| `ipm_vshape_8p12s_deep_apex_high_output_v1` | B | PASS | 5.08319537 | 0.0317882194 | 8.19572534 | 8.59621422 |
| `ipm_vshape_8p12s_narrow_angle_contract` | B | PASS | 4.40220122 | 0.037657185 | 4.70961567 | 4.79256709 |
| `ipm_vshape_8p12s_pocket_offset_contract` | B | PASS | 5.08231162 | 0.0537520959 | 8.11410097 | 9.80692893 |
| `ipm_vshape_8p12s_thin_bridge_contract` | B | PASS | 2.57976849 | 0.0675546585 | 1.10538477 | 0.606538919 |
| `ipm_vshape_8p12s_wide_angle_high_output_v1` | B | PASS | 6.59403144 | 0.0486222122 | 8.6062342 | 9.62696389 |
| `ipm_flat_8p12s_fsae_contract__magnet_60C` | B | PASS | 0.329356566 | 0.00791156356 | 0.264436063 | 0.22940192 |
| `ipm_flat_8p12s_fsae_contract__magnet_100C` | B | PASS | 0.336329764 | 0.00749761122 | 0.271676678 | 0.238157375 |
| `ipm_flat_8p12s_fsae_contract__dq_I50_g0` | B | PASS | 0.130627305 | 0.00335815165 | 0.238057498 | 0.192789675 |
| `ipm_flat_8p12s_fsae_contract__dq_I50_g30` | B | PASS | 0.10213021 | 0.00232717709 | 0.238057498 | 0.192789675 |
| `ipm_flat_8p12s_fsae_contract__dq_I50_g60` | B | PASS | 0.0483838969 | 0.00064608078 | 0.238057498 | 0.192789675 |
| `ipm_flat_8p12s_fsae_contract__dq_I100_g0` | B | PASS | 0.141914015 | 0.007335296 | 0.238057498 | 0.192789675 |
| `ipm_flat_8p12s_fsae_contract__dq_I100_g30` | B | PASS | 0.101303097 | 0.00473937887 | 0.238057498 | 0.192789675 |
| `ipm_flat_8p12s_fsae_contract__dq_I100_g60` | B | PASS | 0.0602777744 | 0.00168347441 | 0.238057498 | 0.192789675 |
| `ornl_prius_2004_ipm` | C | UNSUPPORTED | — | — | — | — |
| `spm_12p36s_distributed_femm_validation` | C | PASS | 5.1596636 | 0.269067901 | 0.305713521 | 0.0388727179 |
| `spm_8p24s_distributed_femm_validation` | C | PASS | 3.05683943 | 0.173078577 | 0.222586383 | 0.0220966131 |
| `spm_8p48s_chorded_5_6` | C | PASS | 1.6428287 | 0.0984675139 | 0.226544184 | 0.627204129 |
| `spm_8p48s_distributed_femm_validation` | C | PASS | 1.56401644 | 0.0985914551 | 0.179706233 | 0.0379060542 |
| `spm_14p12s_high_pole` | D | PASS | — | — | — | — |
| `spm_4p12s_small` | D | PASS | — | — | — | — |
| `spm_8p12s_reference` | D | PASS | — | — | — | — |
| `spm_outer_14p12s_drone__baseline` | F | PASS | 0.514378621 | 0.000273025276 | 0.0704819701 | 0.255124733 |
| `spm_outer_14p12s_drone__high_current` | F | PASS | 0.371825405 | 0.000295975972 | 0.0704819701 | 0.255124733 |
| `spm_outer_14p12s_drone__tight_airgap` | F | PASS | 0.0468103789 | 2.63898765e-05 | 0.0292646871 | 0.0233288143 |
| `spm_outer_14p12s_drone__angle30` | F | PASS | 0.564587535 | 0.000262468771 | 0.0704819701 | 0.255124733 |
| `spm_outer_14p12s_drone_noload__baseline` | F | PASS | 100.079747 | 0.000227009415 | 0.0704819701 | 0.255124733 |
| `spm_outer_12p9s_micro__baseline` | F | PASS | 0.862340408 | 0.000131024995 | 0.31200683 | 0.358722044 |
| `spm_outer_12p9s_micro_noload__baseline` | F | PASS | 101.538056 | 9.53225352e-05 | 0.31200683 | 0.358722044 |
| `spm_outer_10p12s_single_layer__baseline` | F | PASS | 0.137064962 | 0.000780083205 | 0.182450993 | 0.0614345655 |
| `spm_outer_28p24s_multirotor__baseline` | F | PASS | 0.0409867117 | 0.000133095611 | 0.0419053145 | 0.324613048 |
| `spm_outer_30p27s_hub__baseline` | F | PASS | 0.0461390186 | 0.00204516435 | 0.188949187 | 0.306227498 |

### Separately measured Newton F

| Case | Phase | Outcome | Mean torque error (%) | Absolute torque error (Nm) | EMF fundamental error (%) | EMF peak error (%) |
|---|---|---|---:|---:|---:|---:|
| `spm_outer_14p12s_drone__baseline` | F | PASS | 0.514582417 | 0.000273133448 | 0.0705308923 | 0.255586676 |
| `spm_outer_14p12s_drone__high_current` | F | PASS | 0.372032129 | 0.000296140526 | 0.0705308923 | 0.255586676 |
| `spm_outer_14p12s_drone__tight_airgap` | F | PASS | 0.046833328 | 2.64028143e-05 | 0.0292642162 | 0.0234610757 |
| `spm_outer_14p12s_drone__angle30` | F | PASS | 0.564838715 | 0.000262585541 | 0.0705308923 | 0.255586676 |
| `spm_outer_14p12s_drone_noload__baseline` | F | PASS | 100.059246 | 0.000226962912 | 0.0705308923 | 0.255586676 |
| `spm_outer_12p9s_micro__baseline` | F | PASS | 0.862401093 | 0.000131034215 | 0.312022442 | 0.358765746 |
| `spm_outer_12p9s_micro_noload__baseline` | F | PASS | 101.539552 | 9.532394e-05 | 0.312022442 | 0.358765746 |
| `spm_outer_10p12s_single_layer__baseline` | F | PASS | 0.13704339 | 0.000779960428 | 0.182341901 | 0.0613724698 |
| `spm_outer_28p24s_multirotor__baseline` | F | PASS | 0.040799857 | 0.00013248884 | 0.0418371161 | 0.324505676 |
| `spm_outer_30p27s_hub__baseline` | F | PASS | 0.0461091413 | 0.00204384001 | 0.188863796 | 0.306108309 |

## Reference reproduction and retained findings

Fresh reference reproduction: **58/58 exact numeric cases** and **58/58 exact complete results** after only the explicitly listed runtime/location exclusions. This covers 46 A–D cases, ten F cases and two F mesh controls. Any mismatch and its numerical deltas remain in JSON; exact reproduction is not scientific acceptance.

Frozen FEMM producer identities and the original reference configurations remain unchanged. The explicit ten-case native-option bridge changes only Picard to Newton; original references are reused under that bridge and are not restamped as new FEMM solves. The normal F producer and distinct 0.5 mm hub bulk-mesh variant retain separate source cohorts. The standard single-producer contract remains unsatisfied.

| F half-gap control | Torque change (%) | EMF fundamental change (%) | Limit | Outcome |
|---|---:|---:|---|---|
| `spm_outer_14p12s_drone__tight_airgap` | 0.036209734 | 0.0112088444 | Strictly below 2% | PASS |
| `spm_outer_12p9s_micro__baseline` | 0.707357177 | 0.155496511 | Strictly below 2% | PASS |

Inherited LRK original and refined checks each remain **9 PASS / 2 FAIL**. They were not rerun, waived or reclassified and are outside the fresh case/gate totals. Phase E cogging was not measured in this collection and remains experimental.

### Collection recovery and field-count scope

The **1,152 selected F reference positions** cover twelve complete 96-position cases, including two mesh controls. A Windows atomic-manifest replacement interruption also completed **179 diagnostic poses**; all **358 model/answer SHA-256 checks** passed. These partial attempts lacked full-case completion/after-identity receipts, remain retained diagnostic evidence, and are excluded from completed-case counts and per-case timings. Incomplete cases were retried in full through unchanged producers, so total campaign work exceeds 1,152 positions and workflow wall includes retries, recovery and archival.

Operational recovery used a separate controller correction that avoids live manifest polling. A separate outside reporting helper corrected the original grader's gate-count shape error. The seven sealed capsule files, physical producers, requests, source pins and scientific gates were preserved; neither correction changes the physics comparison.

## Picard / Newton native F timing observations

One recorded native workflow observation per variant; worker runtime_s includes measurement and provenance work. No repeated-run uncertainty or statistical speed claim.

Executed solver source and dependencies are unchanged by the audited option bridge; independently built binaries retain separate hashes.

Both variants cover the same ten physical F configurations and use the same sealed FEMM fields. Negative changes below mean a shorter observed Newton worker interval. These single observations do not establish a confidence interval or a general speedup.

| Case | Picard worker wall (s) | Newton worker wall (s) | Newton minus Picard (%) |
|---|---:|---:|---:|
| `spm_outer_10p12s_single_layer__baseline` | 131.544347 | 52.4405265 | -60.1347167 |
| `spm_outer_12p9s_micro__baseline` | 258.690893 | 84.7204327 | -67.2503227 |
| `spm_outer_12p9s_micro_noload__baseline` | 257.555499 | 72.2130688 | -71.9621327 |
| `spm_outer_14p12s_drone__angle30` | 196.084691 | 69.3463581 | -64.6344863 |
| `spm_outer_14p12s_drone__baseline` | 194.786777 | 66.1389943 | -66.0454393 |
| `spm_outer_14p12s_drone__high_current` | 198.484983 | 67.3369727 | -66.0745253 |
| `spm_outer_14p12s_drone__tight_airgap` | 205.58656 | 61.3479466 | -70.159554 |
| `spm_outer_14p12s_drone_noload__baseline` | 198.877232 | 62.0218845 | -68.8139845 |
| `spm_outer_28p24s_multirotor__baseline` | 100.193293 | 39.2453891 | -60.8303231 |
| `spm_outer_30p27s_hub__baseline` | 66.7521929 | 34.202714 | -48.7616623 |
| **Worker-seconds sum** | **1808.55647** | **609.014287** | **-66.3259457** |

Separately recorded workflow wall: original Picard F last controller invocation **1844.97877 s**; new Newton F collection **645.941103 s**. Last controller invocation includes launch, checks and cleanup; retained resume invocations need not equal an entire original collection. Workflow totals are separate from summed worker intervals.

Reference collection times include verified compression/archival and identity checks; original per-pose timings have a narrower scope. Summed worker time is distinct from elapsed collection wall, especially for concurrent FEMM work and retained retries. Original workflow/reference timing scopes remain in JSON.

## Historical application-version context

Historical v0.5.1 and v0.5.5 A–D comparisons each had **46 PASS + 1 unsupported**, **336/336 PASS gates**, and 52 exactly equal published native waveform-stage sets. The actual measured commits were `a4f9f4d` and `34de0f4c`; the distinct application-tag commits were `5a3e80a0` and `63c7f2b0`. Tag bridges cover 64 and 69 guarded files respectively, with zero mismatches, rather than every repository file or new solves at the tags.

The v0.5.1 overnight run solved 46 fresh FEMM cases; PR218/v0.5.5 reused the unchanged published A–D bundle. Historical largest non-nearzero mean-torque, EMF fundamental and EMF peak errors were 7.0224%, 8.6062% and 9.8069%, all PASS. The near-zero maximum absolute torque difference was 0.00201519 Nm under the 0.01 Nm PASS floor.

Historical F had **10 PASS / 60 PASS gates**, with its mixed-source REVIEW_REQUIRED status and two LRK FAIL flags retained. No matched v0.5.1 F cohort was found in retained evidence. Historical experimental cogging retains original 9 PASS / 3 FAIL and selected-finer 10 PASS / 2 YELLOW outcomes. These historical results are context, not approval of the current evidence.

## Public evidence

[Companion JSON](windows-femm-release-v056-20261109.json) preserves per-case physical errors, every gate/status, signed-waveform diagnostics, source/cohort hashes, the option bridge, controls and precise timing scopes. Private paths, raw archives and full producer identities stay local. The report-ready receipt means the evidence pipeline completed; scientific findings remain separately visible.
