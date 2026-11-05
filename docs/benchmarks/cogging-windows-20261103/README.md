# Windows cogging benchmark and mesh study

Measured on 3 November 2026 at PR #186 commit `6bc935d0beeaad1390134670a9813a7e04c3b22c`.

**Decision: keep normal mesh as the application default.** Against the selected consistent FEMM references, the 12 original normal-mesh native requests give **10 PASS and 2 YELLOW** outcomes. The two YELLOW results are retained. The additional mesh study is validation evidence; it changes no solver code, application default, registered request, threshold or qualification record.

## Reports and numerical data

- [All 12 fixtures: waveforms, peaks and FEMM refinement (PDF)](cogging-femm-vs-magneto2d.pdf)
- [Distributed fixtures: normal/fine/very-fine native convergence (PDF)](native-mesh-convergence.pdf)
- [Machine-readable metrics, gates and measured request hashes](results.json)
- [Sampled waveforms for every comparison](waveforms.json)
- [SHA-256 file checksums](sha256.json)

## Normal mesh results

The nine non-distributed fixtures use the original FEMM references. The three distributed fixtures use the completed refined FEMM references because the original FEMM zero-mean and/or period-closure checks failed. Original and refined results are both retained in the numerical data. Percentages below are absolute relative to the selected FEMM reference.

| Fixture | Native p-p (Nm) | Selected FEMM p-p (Nm) | P-p difference | Fundamental difference | Proposed gates |
| --- | ---: | ---: | ---: | ---: | --- |
| `spm_4p12s_simple__baseline__cogging` | 0.146045 | 0.145911 | 0.09% | 0.22% | PASS |
| `spm_4p12s_simple__tight_airgap__cogging` | 0.484924 | 0.480780 | 0.86% | 1.08% | PASS |
| `spm_8p12s_concentrated__baseline__cogging` | 0.898531 | 0.849164 | 5.81% | 3.58% | PASS |
| `spm_8p12s_concentrated__tight_airgap__cogging` | 1.463886 | 1.391640 | 5.19% | 1.32% | PASS |
| `spm_8p12s_example_shoed__cogging` | 1.332476 | 1.300832 | 2.43% | 1.37% | PASS |
| `ipm_flat_8p12s_fsae_contract__cogging` | 0.267718 | 0.266087 | 0.61% | 0.73% | PASS |
| `ipm_flat_8p12s_fsae_angled_pocket_contract__cogging` | 0.560043 | 0.564977 | 0.87% | 0.62% | PASS |
| `ipm_flat_12s10p_fscw_contract__cogging` | 1.075870 | 1.016123 | 5.88% | 6.04% | PASS |
| `ipm_flat_24s16p_industrial_contract__cogging` | 1.635075 | 1.675679 | 2.42% | 0.87% | PASS |
| `spm_8p24s_distributed_femm_validation__cogging` | 26.344040 | 23.791557 | 10.73% | 10.17% | YELLOW |
| `spm_8p48s_distributed_femm_validation__cogging` | 17.827481 | 16.340804 | 9.10% | 7.30% | PASS |
| `spm_12p36s_distributed_femm_validation__cogging` | 27.009623 | 24.289974 | 11.20% | 9.24% | YELLOW |

## What changed when FEMM was refined

All three distributed finer FEMM waveforms pass both reference self-checks. Halving the gap target changes p-p by 0.90-1.15% and the fundamental by 0.79-0.92%, while substantially reducing the mean offsets. This supports a mesh-dependent explanation for the original reference failures.

The distributed normal-mesh native waveforms remain very close in shape. Their original-baseline p-p differences were 9.61%, 8.13% and 9.94%; against refined FEMM they become 10.73%, 9.10% and 11.20%. Crossing the fixed 10% cutoff makes two cases YELLOW. This is borderline amplitude agreement, not a change in waveform shape.

## Native mesh sensitivity on the distributed fixtures

Only `solve_params.mesh_density` changes in the six diagnostic requests. The material contract, corner refinement, current settings, angular positions and WST extraction are held fixed. Every native level is compared with the same refined FEMM waveform for that fixture.

| Fixture | Native density | Representative elements | P-p difference | Fundamental difference | Proposed gates |
| --- | --- | ---: | ---: | ---: | --- |
| `spm_8p24s_distributed_femm_validation__cogging` | normal | 32,614 | 10.73% | 10.17% | YELLOW |
| `spm_8p24s_distributed_femm_validation__cogging` | fine | 34,722 | 9.02% | 8.25% | PASS |
| `spm_8p24s_distributed_femm_validation__cogging` | very_fine | 105,682 | 3.08% | 2.09% | PASS |
| `spm_8p48s_distributed_femm_validation__cogging` | normal | 44,718 | 9.10% | 7.30% | PASS |
| `spm_8p48s_distributed_femm_validation__cogging` | fine | 41,662 | 12.63% | 11.05% | YELLOW |
| `spm_8p48s_distributed_femm_validation__cogging` | very_fine | 126,662 | 3.27% | 2.51% | PASS |
| `spm_12p36s_distributed_femm_validation__cogging` | normal | 39,280 | 11.20% | 9.24% | YELLOW |
| `spm_12p36s_distributed_femm_validation__cogging` | fine | 41,988 | 10.30% | 7.45% | YELLOW |
| `spm_12p36s_distributed_femm_validation__cogging` | very_fine | 118,966 | 4.07% | 3.12% | PASS |

The fine preset gives mixed results and can even reduce the representative element count; the small target-size change does not ensure monotonic mesh refinement. Very-fine meshes give PASS on all three, with p-p differences of 3.08%, 3.27% and 4.07%, and fundamental differences of 2.09%, 2.51% and 3.12%. This is evidence of native mesh sensitivity, rather than a reason to change the default or relax the gates. Element counts describe the representative mesh reported by solve metadata, not every rotor position.

## Collection, checks and claim boundary

- FEMM 4.2: 12 baseline sweeps, the two requested original mesh controls and three additional distributed mesh controls; 25 positions each, for 425 retained no-current fields.
- Native: 12 original Windows normal-mesh requests and six additional fine/very-fine diagnostic requests. All jobs completed. Completed native request/result identities and hashes were verified.
- The 75 additional refined FEMM field pairs were checked against their saved hashes and integrated zero-current audits. The original sweeps and failed checks were preserved.
- One cogging period, including its repeated endpoint, is sampled at 25 matching electrical angles. The public clockwise convention is used, with rotor-body weighted-stress torque for FEMM and the public WST native path.
- PASS: error <= max(10% of reference magnitude, fixed case floor). YELLOW: <= max(20%, twice the floor). The floor is 0.5% of the base case's registered FEMM mean loaded torque. FEMM mean and endpoint mismatch must each be within the floor. No thresholds changed.
- The public material contract is inherited unchanged from protocol 1.7.0. No curve fitting, waveform alignment, filtering, interpolation or rescaling was applied.
- The original baseline references for the three distributed cases fail their own self-checks; those original comparisons cannot establish a qualified pass. The selected-refinement aggregate is a diagnostic summary, not a newly registered suite.
- The field measurement source is `6bc935d0beeaad1390134670a9813a7e04c3b22c`. Commit `6845aaa7a0a16934991b43b713c776b78d9971fe` subsequently changed tests and snapshot metadata. Later, `e30f31bd2336eacb3736404ba97aff4086396878` changed `backend/cogging.py`, the solver and `backend/benchmark_suite/cogging_metrics.py` to suppress non-independent endpoint diagnostics and require complete reference self-checks. That revision also appended the endpoint caveat below; the older checksum index did not cover that README edit. Neither revision collected new fields.
- The v0.5.1 follow-ups guard the summarizer, check stored-summary consistency, explain unavailable loaded-torque comparisons, and isolate independently meshed caches from rotated-mesh caches. Those changes apply to subsequent runs. This bundle's numerical JSON, PDFs, measured-source identity, original endpoint values and fixed gate outcomes remain the historical measurement; they have not been restamped to a later implementation.
- Native endpoint mismatches of exactly zero on the two 4p/12s cases and the three distributed cases reflect slot-pitch mesh/solution reuse. They are not independent remesh-noise measurements. The retained numbers describe the measured source; subsequent app results leave that diagnostic unavailable when endpoints share a mesh or solution. Waveforms, amplitude gates and reference self-checks are unchanged.
- These reports publish numerical evidence only. They do not register a FEMM bundle, qualify a release, establish physical-motor accuracy, or replace the required macOS/release-candidate runs.
