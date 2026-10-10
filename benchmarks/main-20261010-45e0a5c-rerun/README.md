# A/B/C/D rerun on public main `45e0a5c`

This package records a rerun of the versioned A/B/C/D benchmark (harness
1.0.0, protocol 1.0.0) on public Coilem commit
`45e0a5c7662ade04a4be5519b7e5bac771a6122f` against the FEMM references retained from
[benchmark report v1.1](../main-20261009-bad71d9/README.md). The v1.1 package is
unchanged; it remains the fresh-reference record for commit `bad71d9`.

This is new native evidence against retained references, not a regenerated FEMM
baseline: reference mode is `FROZEN_REFERENCE`, the reference commit is
`8b95decda27d475ddbb75e99d92744ebc8e53b28`, and no reference solves were executed.

Outcome: **FAIL**, with the same verdicts as v1.1: 27 PASS,
2 FAIL (the deep-apex and wide-angle V-shape IPM fixtures) and
1 UNSUPPORTED (Prius). All three BLDC fixtures pass 14/14 gates.

- [HTML report with plots](coilem_benchmark_report.html) (open a downloaded copy in a browser).
- [Markdown report](benchmark_report.md).
- [JSON summary with per-fixture measurements, gates and runtime identity](benchmark_summary.json).
- [Native input fixtures](fixtures/).
- [Publication record and original artifact hashes](publication.json).
- [Published artifact hashes](artifact_manifest.json).

## Runtime identity

| Field | Value |
| --- | --- |
| Commit | `45e0a5c7662ade04a4be5519b7e5bac771a6122f` (clean checkout: true) |
| Source hash | `7f53cc0f0523b8816957c5760cfa883ebf9d097686d4b03001b9da52cea4c6c6` over 137 files, listed in `run.identity.source_files` |
| Magneto2D binary SHA-256 | `8871e6406be2f6108a5f20af696fd16af972da0b69a8b806d3994965c0c7f191` |
| Platform | macOS-15.7.3-arm64-arm-64bit (arm64), Python 3.12.13 |
| Dependencies | gmsh 4.15.2, meshio 5.3.5, numpy 2.4.6, pydantic 2.13.4 |
| Run | 2026-10-10T16:10:45Z to 2026-10-10T17:54:38Z |

## Per-fixture results

Phases A, B and C: candidate difference from the retained FEMM reference. v1.1 values are in parentheses.
Near-zero references (below 0.01 N m) use absolute torque differences.

| Phase | Fixture | Verdict (v1.1) | Mean torque | Back-EMF H1 | Back-EMF peak |
| --- | --- | --- | ---: | ---: | ---: |
| A | `spm_4p12s_simple__baseline` | PASS (PASS) | 0.16% (0.16%) | 0.01% (0.01%) | 0.04% (0.04%) |
| A | `spm_4p12s_simple__high_current` | PASS (PASS) | 0.12% (0.12%) | 0.01% (0.01%) | 0.04% (0.04%) |
| A | `spm_4p12s_simple__tight_airgap` | PASS (PASS) | 0.06% (0.08%) | 0.35% (0.34%) | 0.05% (0.05%) |
| A | `spm_4p12s_simple_noload__baseline` | PASS (PASS) | 0.002055 N m (0.002064 N m) | 0.01% (0.01%) | 0.04% (0.04%) |
| A | `spm_4p12s_simple_noload__high_current` | PASS (PASS) | 0.28% (0.28%) | 0.01% (0.01%) | 0.04% (0.04%) |
| A | `spm_4p12s_simple_noload__tight_airgap` | PASS (PASS) | 0.000012 N m (0.000075 N m) | 0.35% (0.34%) | 0.05% (0.05%) |
| A | `spm_8p12s_concentrated__baseline` | PASS (PASS) | 0.16% (0.16%) | 0.07% (0.07%) | 0.15% (0.15%) |
| A | `spm_8p12s_concentrated__high_current` | PASS (PASS) | 0.08% (0.08%) | 0.07% (0.07%) | 0.15% (0.15%) |
| A | `spm_8p12s_concentrated__tight_airgap` | PASS (PASS) | 0.27% (0.27%) | 0.01% (0.01%) | 0.08% (0.08%) |
| A | `spm_8p12s_reference_angle30__baseline` | PASS (PASS) | 0.32% (0.32%) | 0.14% (0.14%) | 0.17% (0.17%) |
| B | `ipm_flat_12s10p_fscw_contract` | PASS (PASS) | 0.59% (0.60%) | 0.61% (0.61%) | 0.78% (0.62%) |
| B | `ipm_flat_24s16p_industrial_contract` | PASS (PASS) | 0.58% (0.58%) | 0.18% (0.19%) | 0.31% (0.35%) |
| B | `ipm_flat_4p12s_micro_contract` | PASS (PASS) | 0.33% (0.33%) | 0.56% (0.57%) | 0.78% (0.79%) |
| B | `ipm_flat_8p12s_fsae_angled_pocket_contract` | PASS (PASS) | 0.10% (0.10%) | 0.30% (0.30%) | 0.73% (0.73%) |
| B | `ipm_flat_8p12s_fsae_contract` | PASS (PASS) | 0.15% (0.15%) | 0.24% (0.24%) | 0.30% (0.29%) |
| B | `ipm_flat_8p12s_fsae_thin_bridge_contract` | PASS (PASS) | 0.13% (0.12%) | 0.22% (0.22%) | 0.45% (0.48%) |
| B | `ipm_vshape_8p12s_baseline_contract` | PASS (PASS) | 7.43% (7.48%) | 2.09% (2.08%) | 6.26% (6.25%) |
| B | `ipm_vshape_8p12s_deep_apex_contract` | FAIL (FAIL) | 36.21% (36.02%) | 4.87% (4.88%) | 4.81% (4.77%) |
| B | `ipm_vshape_8p12s_narrow_angle_contract` | PASS (PASS) | 4.15% (4.12%) | 3.54% (3.55%) | 4.43% (4.43%) |
| B | `ipm_vshape_8p12s_pocket_offset_contract` | PASS (PASS) | 5.45% (5.40%) | 1.33% (1.33%) | 3.03% (3.01%) |
| B | `ipm_vshape_8p12s_thin_bridge_contract` | PASS (PASS) | 1.80% (1.80%) | 0.85% (0.85%) | 1.70% (1.70%) |
| B | `ipm_vshape_8p12s_wide_angle_contract` | FAIL (FAIL) | 13.28% (12.41%) | 36.03% (36.03%) | 25.78% (25.16%) |
| C | `ornl_prius_2004_ipm` | UNSUPPORTED (UNSUPPORTED) | - | - | - |
| C | `spm_12p36s_distributed_femm_validation` | PASS (PASS) | 3.10% (2.98%) | 0.98% (0.98%) | 0.59% (0.59%) |
| C | `spm_8p24s_distributed_femm_validation` | PASS (PASS) | 1.10% (1.13%) | 0.51% (0.51%) | 0.28% (0.28%) |
| C | `spm_8p48s_chorded_5_6` | PASS (PASS) | 0.70% (0.62%) | 0.80% (0.80%) | 0.13% (0.12%) |
| C | `spm_8p48s_distributed_femm_validation` | PASS (PASS) | 0.66% (0.57%) | 0.87% (0.87%) | 0.96% (0.98%) |

Phase D, BLDC (selected gates; all fourteen are in the JSON summary). v1.1 values are in parentheses.

| Fixture | Outcome | Mean torque vs FEMM (5%) | Waveform NRMSE (10%) | Low-current power balance (10%) | Standard to fine torque (2%) |
| --- | --- | ---: | ---: | ---: | ---: |
| `spm_14p12s_high_pole` | PASS, 14/14 gates | 0.05652% (0.05629%) | 0.863% (0.8675%) | 0.6698% (0.6687%) | 0.4063% (0.3997%) |
| `spm_4p12s_small` | PASS, 14/14 gates | 0.2008% (0.1979%) | 0.5307% (0.5301%) | 0.3221% (0.3277%) | 0.2058% (0.2098%) |
| `spm_8p12s_reference` | PASS, 14/14 gates | 0.8168% (0.8523%) | 1.284% (1.285%) | 0.614% (0.3192%) | 0.1405% (0.1472%) |

The rerun ran on a different platform from the original v1.1 measurement and
includes later solver changes, so small differences are expected. Passing A/B/C
fixtures moved by at most 0.17 percentage points; the failing V-shape metrics by
at most 0.9 points.

## Publication changes

The local run directory is replaced by the alias `<run-root>`, and worker
process IDs are omitted. Numerical values, gates and verdicts are unchanged.
`publication.json` retains the SHA-256 of every original report artifact,
including the PDF and CSV exports, which stay local because the repository
publishes text benchmark artifacts only. Per-job worker logs and raw result
files also stay local; their result hashes are in `run.jobs`.

## Reproduce

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/rerun --pdf
```

Run it from a clean checkout of `45e0a5c`. Cross-platform floating-point
results and runtimes may differ slightly; see the [benchmark protocol](../abcd-v1/README.md).
