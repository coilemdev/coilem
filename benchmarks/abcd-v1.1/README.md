# A/B/C/D benchmark protocol 1.1.0

Protocol **1.1.0** is retained for historical replay. Harness 1.4.0 now defaults
to [protocol 1.3.0](../abcd-v1.3/README.md), which reconciles the BLDC current
frame while preserving this protocol's original results. This edition replaces
the low-output deep-apex and wide-angle Phase B cases with qualified higher-output
physical designs. All other requests, references, angular grids, materials,
BLDC golden vectors and numerical gates remain unchanged.

| Phase | Registered cases | Saved references | Native field jobs |
| --- | ---: | ---: | ---: |
| A - SPM | 10 | 10 | 10 |
| B - IPM | 12, including two higher-output replacements | 12 | 12 |
| C - Distributed Winding | 5, including the policy-rejected Prius | 4 | 4 supported |
| D - BLDC | 3 | 3 | 9 |

The suite has **30 cases, 29 references and 35 supported native field jobs**.
ORNL Prius is shown as Planned coverage (not yet supported). Its numerical
status remains UNSUPPORTED; it has no parity measurement or PASS. Thermal analysis is outside A/B/C/D.

## Run a new native benchmark without FEMM

After installing the normal Python dependencies and Rust toolchain:

```sh
python -m tools.run_benchmarks --version
python -m tools.run_benchmarks --list
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.1/benchmark_spec.json \
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 \
  --phases A B C D --out-dir ../benchmark-output/my-run --pdf
```

The same command works on macOS, Windows and Linux. It builds and measures the
current checkout's public Magneto2D solver against saved normalized FEMM data.
FEMM, its adapter, a reference Python environment, Node and the UI are not needed.
Candidate commit, executable/source hashes, platform, dependencies, harness and
selected protocol are recorded. Keep output outside the checkout; a clean
checkout is required by default. `--allow-dirty` records uncommitted source hashes.

To run only the replacements:

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.1/benchmark_spec.json \
  --reference-bundle benchmarks/reference-baselines/ipm-high-output-v1 --phases B \
  --case ipm_vshape_8p12s_wide_angle_high_output_v1 \
  --case ipm_vshape_8p12s_deep_apex_high_output_v1 \
  --out-dir ../benchmark-output/high-output-ipm --pdf
```

Use `--resume` to continue an identical registered run, or `--report-only` to
rebuild it without solving. Keep the selection and output directory identical.
Changed source, executable, dependencies or inputs prevent resume. `--smoke`
is NON_GATING_SMOKE; `--no-reference` cannot establish parity PASS. Long jobs
are serialized with process locks and resumable manifests.

## Fixture changes and report v1.2

The [release baseline report v1.2](../release-baseline-20261011-v1.2/benchmark_report.md)
selects the new 30-case matrix: **29 PASS, one planned coverage item (numerical state UNSUPPORTED)**. It compiles the
unchanged October 10 macOS rerun at `45e0a5c` with two freshly qualified October 11
IPM designs at `af56962`. Each row identifies its actual measured candidate and
source evidence; this is not a new full sweep of a single release commit.

- Deep apex: magnet legs 9 -> 12 mm; 60-degree V, 17 mm apex depth retained.
- Wide angle: magnet legs 9 -> 10 mm; 75-degree V, 13.5 mm apex depth retained.

Current, winding, stack, materials and numerical settings are unchanged. Both
designs exceed **0.5 N m mean torque** in Magneto2D and FEMM. The
[qualification evidence](../ipm-high-output-20261011-af56962/benchmark_report.md)
links exact requests, openable `.coilem` designs, full waveforms and runtime hashes.
The loaded grid has 13 points over 0-90 degrees; Back-EMF has 48 points over a full
electrical cycle. Public normal meshes, WST and Newton defaults are used.

Original torque units were correctly N m; displaying mN m does not change the
relative error. These are new geometries, not a fix for the original failures or
proof of spatial convergence. The original cases are removed from the default
matrix and retained with their FAIL verdicts in the frozen historical suite and
reports. The [full Windows report v1.3](../main-20261012-0b463b3-rerun/README.md)
now reruns the complete selected matrix at `0b463b3` against these same frozen
references. It predates the later performance changes; subsequent candidates
need their own complete run, and elapsed timing comparisons need comparable load.

## Reference integrity and versions

The historical 1.1.0 data-only bundle is `benchmarks/reference-baselines/ipm-high-output-v1`.
Its 27 inherited reference files are byte-for-byte unchanged. Two new records
bind the replacement requests to fresh matched FEMM evidence. Full input hashes
prevent comparing the new geometry with old FEMM data. Candidate and reference
commits remain distinct. No reference code, adapter, binary or environment is
distributed, installed or run.

Changed solver implementation can reuse compatible references. Changed geometry,
current, winding, speed, materials, grids, conventions or request settings require
new matched reference evidence. Missing or incompatible references never PASS.

Harness 1.3.0 supports protocols 1.0.0, 1.1.0 and [1.2.0](../abcd-v1.2/README.md) and records the selected protocol
in worker identities. Protocol 1.1.0 changes matrix membership. Gates are unchanged:
mean torque PASS <=8% / YELLOW <=15% (existing absolute limits near zero),
Back-EMF H1/peak PASS <=10% / YELLOW <=15%, and fourteen BLDC gates per fixture.
Signed waveform residuals remain diagnostics. Reports use A/B/C/D order and
green summaries for all PASS, yellow for mixed/missing coverage, red for more
than 50% FAIL. Report revision, harness version, protocol and candidate commit
are separate identities.

To reproduce the original low-output matrix explicitly:

```sh
python -m tools.run_benchmarks \
  --suite benchmarks/abcd-v1/benchmark_spec.json \
  --reference-bundle benchmarks/reference-baselines/main-bad71d9 \
  --phases A B C D --out-dir ../benchmark-output/historical-suite --pdf
```

The [historical report v1.1](../main-20261009-bad71d9/benchmark_report.md),
[macOS rerun](../main-20261010-45e0a5c-rerun/README.md), original inputs and recorded
FAILs remain unchanged. See [historical protocol details](../abcd-v1/README.md).

## Planned ORNL Prius coverage

The planned item is ORNL Prius 2004: its HoleM50 rotor geometry is outside the public flat-buried/V-shape IPM policy. Geometry helpers exist, but native meshing/field solves and matched FEMM qualification are needed before enabling public support. Numerical status remains UNSUPPORTED; no comparison was performed and no delivery date is claimed.
