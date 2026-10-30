# Registered cap-200 Windows checks

Native fields measured at `d9827b12d3a10fd9fc3ce0a32b899dc802fe762b`; validation after the historical-replay follow-up at `5c678c7c8fde0ed2a90990a74b6b25b13c363357`. These selected checks rerun PR #155's quick subset, remaining registered V-shape controls, all nine affected BLDC requests, and the exact Prius loaded-torque control. The full A/B/C/D qualification rerun remains deferred to the 0.5.0 freeze.

## Registration

Suite 1.4 registers nine new requests with `max_nonlinear_iterations: 200`. They retain Custom/Picard's raw mismatch tolerance of 0.001. A hash-bound bridge verifies that the cap is the only request change before reusing immutable FEMM fields. Historical suites, requests, reference records, qualification reports and published platform records remain unchanged.

The registration has a new suite hash and each changed request has a new input hash. Reference record input hashes still identify the original measured requests. Grids, excitation, materials, geometry, numerical gates and winding-axis protocols are unchanged. Packaging includes the original inputs needed to check the bridge.

## Registered numerical gates

The public quick command returned **PASS**: {'PASS': 4}. The additional selected suite returned **PASS**: {'PASS': 8}. All 18 native jobs completed. The historical platform comparison remains NOT_COMPARABLE because the physics sources changed; passing numerical gates does not refresh qualification.

The quick command exits 1 for that NOT_COMPARABLE platform comparison despite its 4 PASS numerical verdicts. Its complete public comparison is retained in the data file.

| Case | Registered gates |
| --- | --- |
| spm_4p12s_simple__tight_airgap | PASS |
| ipm_vshape_8p12s_thin_bridge_contract | PASS |
| spm_8p24s_distributed_femm_validation | PASS |
| spm_4p12s_small | PASS |
| spm_8p12s_reference_angle30__baseline | PASS |
| ipm_vshape_8p12s_baseline_contract | PASS |
| ipm_vshape_8p12s_deep_apex_high_output_v1 | PASS |
| ipm_vshape_8p12s_narrow_angle_contract | PASS |
| ipm_vshape_8p12s_pocket_offset_contract | PASS |
| ipm_vshape_8p12s_wide_angle_high_output_v1 | PASS |
| spm_14p12s_high_pole | PASS |
| spm_8p12s_reference | PASS |

## Cap headroom

These are actual registered solves, including the complete original torque/current/back-EMF grids required by their gates. All nine cap-200 requests converged; no tolerance or gate was loosened. Concurrent elapsed times are retained in the data and are not performance comparisons.

| Case / stage | Max / median iterations | Worst final raw mismatch |
| --- | ---: | ---: |
| spm_4p12s_small / native-standard | 107 / 102.5 | 0.000958413 |
| spm_4p12s_small / native-fine | 107 / 102.5 | 0.000985474 |
| spm_4p12s_small / analytical | 105 / 104.0 | 0.000996843 |
| spm_14p12s_high_pole / native-standard | 105 / 100.0 | 0.000998558 |
| spm_14p12s_high_pole / native-fine | 107 / 100.0 | 0.000998558 |
| spm_14p12s_high_pole / analytical | 100 / 100.0 | 0.000999602 |
| spm_8p12s_reference / native-standard | 109 / 106.5 | 0.000985145 |
| spm_8p12s_reference / native-fine | 109 / 107.0 | 0.000998650 |
| spm_8p12s_reference / analytical | 109 / 106.0 | 0.000998748 |

## Prius control

The exact unchanged 32-loaded/32-no-load control returned **353.950530280415 N m**, versus the retained FEMM control of 354.953115296745 N m (-0.282456%). Its registered 2% mean-torque gate passes. This does not claim the unrun tutorial, full curve, refinement or hardware checks.

## Validation and freeze work

- Full Python suite: **1227 passed, 3 platform skips, 17 failures**: the previous 16 expected guards plus one additional suite-registration guard described below. No unexplained failures.
- Rust: **264 passed**. Frontend build: **passed**.
- Cap registration/reference integrity, forbidden-change rejection, package-only loading and historical replay are covered by thirteen new tests.

The first full Python attempt exposed historical-record replay assuming the new default requests, and was stopped. Replay now selects the hash-bound original validation suite for legacy evidence and retains exact request checks; relabelled or altered inputs are rejected. The complete final run above includes that fix. Every native runtime source was checked against its collection hash; field-solver code is unchanged by the replay follow-up.

The previous 16 expected source/physics guards remain. One additional guard, `tests/test_qualification.py::test_basis_names_the_measured_commit_and_reference`, detects the new default suite hash versus the historical protocol-1.3 qualification report. It is intentionally retained: no old report/hash was repinned to protocol 1.4. Exact failing nodes are in the data file.

The cap-100 convergence blocker is resolved by the new registrations and targeted rerun. The full release freeze still requires the A/B/C/D qualification rerun, fresh published platform records, and owner review of preset tolerances/runtime. Issue #12 remains open for Results/PDF/CSV presentation. PR #155 continues to target `release/v0.5.0`.

[Machine-readable requests, source identities, grids, convergence records and gates](NONLINEAR_CONVERGENCE_CAP200_WINDOWS.json) · [Earlier review checks](NONLINEAR_CONVERGENCE_REVIEW_WINDOWS.md) · [Registration contract](../benchmarks/abcd-v1.4/README.md)
