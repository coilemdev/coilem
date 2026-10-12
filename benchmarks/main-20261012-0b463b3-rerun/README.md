# Coilem Windows main benchmark report v1.3

[Markdown report](benchmark_report.md), [HTML plots](coilem_benchmark_report.html), [JSON numerical evidence](benchmark_summary.json), [comparison with v1.2](comparison-to-v1.2.json), [elapsed job timings](execution-timings.json), [publication provenance](publication.json) and [artifact hashes](artifact_manifest.json).

This is a fresh, full, single-candidate Windows rerun of the selected A/B/C/D matrix at `0b463b31fc3479360ffaa3668731e3792c034639`. Outcome: **29 PASS, one planned unsupported Prius fixture**; BLDC **42/42 gates PASS**. All recorded v1.2 verdicts are retained.

Fresh Magneto2D native field measurements use frozen, data-only FEMM references from `benchmarks/reference-baselines/ipm-high-output-v1`. No FEMM installation, reference adapter or new FEMM solve was used. The reference commit belongs to a separate reference repository.

Measured candidate `0b463b3` is the baseline before performance PRs #32 (airgap radius indexing), #33 (post-solve pipeline) and #34 (wall-clock timing). It also predates the later main responsiveness changes in PRs #29, #30 and #31. Publishing this report on a newer branch does not mean those changes were measured.

Report revision 1.3 changes the evidence record, not the measured application version (coilEM 0.2.0 / Magneto2D 0.3.2), protocol 1.1.0, fixtures, reference bundle or numerical gates. Prior reports and original low-output V-shape FAILs remain archived.

## Runtime identity

| Field | Value |
| --- | --- |
| Candidate commit | `0b463b31fc3479360ffaa3668731e3792c034639` |
| Source hash | `763d6f217c1f458a7f4c4803e4780f7b4f9f6f16c5002ed0dcae87278c7988c0` |
| Magneto2D binary SHA-256 | `1ebf0d51e7db87ea3c572e6fec75d83a18a2bb470e6a6807c0e24037f3289152` |
| Platform | `Windows-11-10.0.26200-SP0 (AMD64)` |
| Python | `3.13.9` |
| Dependencies | `gmsh 4.15.2, meshio 5.3.5, numpy 2.4.6, pydantic 2.13.4` |
| Harness / protocol | `1.2.1 / 1.1.0` |
| Reference mode | `FROZEN_REFERENCE` |
| Reference commit (separate reference repository) | `8b95decda27d475ddbb75e99d92744ebc8e53b28` |
| Native run (UTC) | `2026-10-12T13:13:20.389646+00:00 to 2026-10-12T16:09:57.668522+00:00` |
| Elapsed wall time | `2.944 hours` |

## Outcomes

| Phase | Recorded outcomes |
| --- | --- |
| A - SPM | 10 PASS |
| B - IPM | 12 PASS |
| C - Distributed Winding | 4 PASS; one planned coverage item (UNSUPPORTED) |
| D - BLDC | 3 PASS; 42/42 gates |

## Frozen reference comparison

Unchanged A/B/C gates: mean torque PASS <=8% / YELLOW <=15%; Back-EMF fundamental and phase-A peak PASS <=10% / YELLOW <=15%. Near-zero references below 0.01 N m use absolute torque limits of 0.01 / 0.02 N m. Native Gmsh, weighted-stress torque and registered angle grids are required. Phase D retains fourteen gates per fixture, ideal six-step 120-degree wye, normal spatial meshes, fine angular sampling and frozen golden currents. Its low-current analytical lane is a native field solve. No fitted angle, sign or scale correction is used.

The inherited references are the same saved FEMM records used by v1.2. The two higher-output V-shape replacements retain their matched October 11 references; no new references were generated for this rerun. Native and reference waveforms, exact registered inputs, gates and runtime hashes are retained in the JSON evidence.

The Prius HoleM50 rotor remains outside public flat-buried/V-shape support. No native or reference comparison was performed for it. Thermal coverage, broad V-shape accuracy, spatial convergence and hardware accuracy are not established by these fixture results; the application qualification policy is unchanged.

## Comparison with report v1.2

All 30 case verdicts match. Across supported A/B/C cases, the largest nonzero mean-torque change is 0.131%; Back-EMF fundamental 0.016%; phase-A peak 0.164%. Near-zero torque changes are compared in N m. The [comparison record](comparison-to-v1.2.json) contains per-stage waveform differences and the three BLDC fixtures.

## Timings and later performance changes

Elapsed job timings reflect concurrent workloads, including another full benchmark and an older refined-IPM sweep. Use actual job timestamps in [execution timings](execution-timings.json); aggregate `solve_time_s` is not elapsed benchmark wall time. Future speed comparisons need comparable machine load and settings. Browser mesh and field playback responsiveness are outside this headless benchmark.

## Reproduce on the measured candidate

Use a clean checkout of the recorded commit, normal locked Python dependencies and Rust. The benchmark builds native Magneto2D and reads frozen reference data; Node and FEMM are not required. Keep generated output outside the checkout.

```sh
git checkout 0b463b31fc3479360ffaa3668731e3792c034639
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/main-0b463b3-rerun --pdf
```

A benchmark of later performance changes must use their exact candidate commit and a new output directory. `--smoke` cannot establish parity. See [protocol and resume commands](../abcd-v1.1/README.md).

## Publication

This package follows the prior text-artifact report format: Markdown, self-contained HTML/SVG plots, numerical JSON, fixtures and SHA-256 manifests. Local run roots use `<run-root>` and worker PIDs are omitted. Numeric samples, gates, verdicts, source identities and original artifact hashes are preserved. PDF, CSV, per-job logs, raw result JSON and solver binaries remain local. The [publication record](publication.json) binds those originals to the published view.
