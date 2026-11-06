# Windows v0.5.1 benchmark evidence

Measured on 5 November 2026 at the clean [#190 merge commit `a4f9f4dc`](https://github.com/coilemdev/coilem/commit/a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f). Completed at 8:46 PM America/New_York (6 November 01:46 UTC).

**Qualification remains pending.** This Windows development evidence records A–D parity and the proposed cogging comparisons at the exact integration merge. It does not complete macOS or Prius qualification, register Phase E, update qualified claims, or authorize a release tag.

## A–D: published reviewed FEMM references

All 52 supported full-grid native jobs completed: **46 PASS and one planned unsupported legacy ORNL Prius case**. The published protocol 1.6 reference bundle is unchanged.

| Phase | PASS cases | Planned unsupported |
| --- | ---: | ---: |
| A | 19 | 0 |
| B | 20 | 0 |
| C | 4 | 1 |
| D | 3 | 0 |

An optional additional fresh A–D reference repeat was stopped at the owner's request: 17 cases completed, six active attempts were interrupted, and 23 cases were not started. Completed and partial artifacts were preserved. This extra repeat supplies none of the reference values in the 46-PASS comparison.

## Cogging: fresh FEMM 4.2 and retained mesh controls

All 12 original normal-mesh native requests and 17 FEMM sweeps completed: 12 baseline sweeps, the shoed/FSCW mesh controls, and three distributed mesh controls. Each FEMM sweep solves 25 independent no-current positions, including the closing endpoint: **425 retained fields**.

The original baseline comparison is **9 PASS / 3 FAIL**. The three distributed FEMM references fail their own zero-mean and/or period-closure checks. Those failures are retained. All five finer-mesh controls pass both reference self-checks. Using the refined references for those three distributed cases gives **10 PASS / 2 YELLOW** on the unchanged native requests.

| Case | Native p-p (Nm) | Selected FEMM p-p (Nm) | P-p error | H1 error | Verdict |
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

The 8p/24s and 12p/36s distributed cases retain YELLOW. No candidate mesh, fixture, material, angle grid, floor, or numerical gate changed. The reference selection is based only on reference self-checks; no waveform alignment, filtering, interpolation or rescaling is applied.

Native waveforms match all 12 retained earlier Windows cogging waveforms exactly; current endpoint-independence metadata remains bound to the newly measured source. Reused endpoints are not independent remesh-noise measurements.

## Data and provenance

- [Case outcomes, numerical gates and five mesh controls](results.json)
- [Unmodified numerical waveform arrays](waveforms.json)
- [Source/binary/material identities, request/result hashes and original-artifact digests](provenance.json)
- [Public artifact checksums](sha256.json)

The original local evidence and raw solver files remain unchanged. This public projection omits machine paths and detailed solver diagnostics; it preserves measured source identity, numerical gate values, waveforms and outcomes. The original artifacts were hash-verified, and no FEMM field processes remained after completion.

## Remaining v0.5.1 release work

- Review the Phase E reference evidence and original failed self-checks; this bundle remains REVIEW_REQUIRED.
- Resolve the two YELLOW cases under the fixed gates, or explicitly review supported coverage before a new freeze. No passing claim is inferred for the original normal-mesh requests from separate refined-native studies.
- Complete the required source-matched macOS and Prius collections. This run contains no new Prius software qualification and no macOS measurements.
- Publish accepted platform/qualification records, complete Phase E registration/default-command coverage and pass the release qualification gate before tagging. None of those records or gates is changed here.

Release context: [integration PR #190](https://github.com/coilemdev/coilem/pull/190), [cogging work #185](https://github.com/coilemdev/coilem/issues/185), [A–D protocol 1.6](../abcd-v1.6/README.md), [proposed Phase E protocol 1.7](../abcd-v1.7/README.md).
