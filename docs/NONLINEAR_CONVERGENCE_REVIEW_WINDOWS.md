# Windows convergence review follow-up

These are selected checks for PR #155, not the complete 0.5.0 qualification rerun. The registered cases and the app plans were measured at `af8ad1a8bf8432d364b819e79a2fd86c523aeccd`. The cap-200 diagnostics use the subsequent torque-only reporting fix, recorded per request. All runs retain the stricter convergence tolerances. Concurrent elapsed times are not performance comparisons.

## Changes made after review

- Newton also accepts an RHS-scaled residual at or below `1e-8`, tied to the tight linear-solve tolerance. The initial, final RHS-scaled and stage-relative residuals and the floor are retained. A tiny-initial-defect regression test covers the stopping decision.
- Tolerance metadata carries distinct method-labelled settings and residual definitions. The scalar tolerance has a method label and is absent for mixed settings. Newton warning ratios account for both stopping alternatives; the unused current-default estimate was removed.
- A cap-200 torque-only diagnostic exposed an absent-no-load aggregation bug in the reporting change. The fix retains missing no-load convergence as null and preserves the legacy iteration placeholders. A regression test and the repeated public-path solves cover this case.

## Registered quick subset

`coilem benchmark --quick` returned **INCOMPLETE**: {'PASS': 3, 'ERROR': 1}. This is separate from the expected NOT_COMPARABLE result against historical source identities.

| Case | Registered gate result |
| --- | --- |
| spm_4p12s_simple__tight_airgap | PASS |
| ipm_vshape_8p12s_thin_bridge_contract | PASS |
| spm_8p24s_distributed_femm_validation | PASS |
| spm_4p12s_small | ERROR |

## Registered V-shape fixtures

Each request retains Custom, Newton and its explicit 80-iteration cap per continuation stage. The table separates equation convergence from the registered reference gates. The deep-apex reference limitation remains as documented in the diagnosis.

| Fixture | Reference gates | Max total iterations | Max stage iterations | Picard fallbacks |
| --- | --- | ---: | ---: | ---: |
| ipm_vshape_8p12s_thin_bridge_contract | PASS | 29 | 11 | 0 |
| ipm_vshape_8p12s_baseline_contract | PASS | 34 | 17 | 0 |
| ipm_vshape_8p12s_deep_apex_high_output_v1 | PASS | 30 | 13 | 0 |
| ipm_vshape_8p12s_narrow_angle_contract | PASS | 35 | 18 | 0 |
| ipm_vshape_8p12s_pocket_offset_contract | PASS | 32 | 16 | 0 |
| ipm_vshape_8p12s_wide_angle_high_output_v1 | PASS | 27 | 10 | 0 |

## Cap-100 Picard fixtures and cap-200 diagnostics

The registered requests are unchanged. The diagnostic requests change only `max_nonlinear_iterations` from 100 to 200; they retain Custom's raw mismatch tolerance of 0.001. These diagnostic inputs have not been registered as new qualification evidence.

| Fixture / stage | Registered cap-100 solve | Cap-200 solve | Max / median iterations at cap 200 |
| --- | --- | --- | ---: |
| spm_14p12s_high_pole / analytical | COMPLETE | COMPLETE | 100 / 100.0 |
| spm_14p12s_high_pole / native-fine | ERROR (iteration cap) | COMPLETE | 107 / 100.0 |
| spm_14p12s_high_pole / native-standard | ERROR (iteration cap) | COMPLETE | 105 / 100.0 |
| spm_4p12s_small / analytical | ERROR (iteration cap) | COMPLETE | 105 / 104.0 |
| spm_4p12s_small / native-fine | ERROR (iteration cap) | COMPLETE | 107 / 102.5 |
| spm_4p12s_small / native-standard | ERROR (iteration cap) | COMPLETE | 107 / 102.5 |
| spm_8p12s_reference / analytical | ERROR (iteration cap) | COMPLETE | 109 / 106.0 |
| spm_8p12s_reference / native-fine | ERROR (iteration cap) | COMPLETE | 109 / 107.0 |
| spm_8p12s_reference / native-standard | ERROR (iteration cap) | COMPLETE | 109 / 106.5 |

Recommendation: retain 0.001 and register cap-200 versions of the affected benchmark requests at the 0.5.0 freeze, with the required reference/qualification registration. Preserve the frozen inputs and historical hashes in this PR. The current registered suite remains blocked wherever the table records a cap-100 error.

## App plans

High accuracy uses the actual fine mesh and 96-position plan. The Custom checks use the default 2-degree full-cycle sampling with normal mesh. The last archived weak fixture is a Standard control. Exact requests, position records and source identities are in the data file.

| Case / plan | Solve | Max / median iterations | Mean torque N m | Phase fundamental RMS back-EMF V |
| --- | --- | ---: | ---: | ---: |
| ipm-10p-vshape-custom | COMPLETE | 152 / 141.0 | 2.758013525 | 8.593886653 |
| ipm-10p-vshape-fine | COMPLETE | 147 / 140.0 | 2.758167006 | 8.595841295 |
| ipm-14p-flat-custom | COMPLETE | 146 / 142.0 | 46.544044052 | 39.150613768 |
| ipm-14p-flat-fine | COMPLETE | 146 / 140.0 | 46.502922650 | 39.116375340 |
| spm-8p12s-custom | COMPLETE | 105 / 104.0 | 10.673478677 | 31.186896577 |
| spm-8p12s-fine | COMPLETE | 105 / 103.0 | 10.676711549 | 31.193763980 |
| wide-angle-original-standard | COMPLETE | 25 / 23.0 | 0.171111508 | 0.228964086 |

## Exact Prius loaded-torque control

The unchanged loaded request produced **353.950530280415 N m**, compared with the previous 353.950530266285 N m. The retained FEMM control is 354.953115296745 N m; the new difference is -0.282456%, inside the published 2% mean-torque limit. The request retains all 32 loaded and 32 no-load positions. This check does not claim the unrun tutorial, angle-curve, refinement or hardware controls.

27 of the 64 position records use the absolute floor instead of the relative threshold. The worst final RHS-scaled residual is 7.49510458e-09, below 1e-8. The method-labelled threshold settings and OR warning ratio retain this evidence without a false warning.

## Validation and remaining release work

- Full Python suite after the reporting fix, with the benchmark processes finished: **1215 passed, 3 platform skips, 16 expected qualification/hash failures**, no unexpected failures.
- Rust: **264 passed**, including the floor and serialization regression tests.
- Frontend build: **passed**; the previously verified fresh install and lockfile remain unchanged.
- An earlier concurrent Python run had two launcher-test failures after a worker missed its 15-second startup marker deadline. The complete final run above supersedes that attempt; the launcher tests and their timeouts were not changed.

The expected failures remain the 10 changed-source qualification guards, five benchmark physics-identity checks, and the published-app fixture measured-source guard. Exact nodes are in the data file. Clean Git archive publication validation is run separately after updating the snapshot manifest.

PR #155 remains a draft for owner review. Before the 0.5.0 freeze, register the benchmark caps and review preset tolerances/runtime; complete release qualification before reaching main. Issue #12 remains open for the Results block and dedicated PDF/CSV presentation.

[Machine-readable evidence](NONLINEAR_CONVERGENCE_REVIEW_WINDOWS.json) · [Original before/after timings](NONLINEAR_CONVERGENCE_WINDOWS.md) · [Convergence contract](NONLINEAR_CONVERGENCE.md)
