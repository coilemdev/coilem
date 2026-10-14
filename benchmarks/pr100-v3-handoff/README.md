# PR #100: parallel Magneto2D A/B/C/D benchmark handoff

Measure **`738d9516e8500c5996c772bd96470472cbb9a0f9`**. The Windows FEMM v3 reference run uses that exact pin. This handoff is a later tools/documentation commit on PR #100; it does not change the measured physics. Do not benchmark a moving branch head, rebase the measured checkout during a run, or substitute the older FEMM v1/v2 bundles.

The other machine can collect native fields while Windows generates FEMM. **Native-only collection is not a FEMM parity PASS.** Once the completed v3 bundle is transferred, the report-only tool below compares those verified native artifacts without repeating field solves.

The machine-readable [run contract](run-contract.json) records the suite, protocol, material, golden-vector and shared source hashes. Reference generation is in progress at handoff; this folder contains no newly measured reference or native results.

## Task for the other AI agent

1. Create a clean, isolated checkout at the exact source pin above. Keep it fixed and use it for both native collection and later evaluation. Keep this PR checkout, containing the handoff/report tool, separate.
2. Use the repository's locked runtime dependencies and build the source checkout's release Magneto2D binary. Record Python, dependency, OS, architecture, Rust/compiler and binary identities. Do not copy an old binary from another commit.
3. Run the registered protocol **1.1.0** A/B/C/D suite with **`--no-reference`** now. Retain all requests, worker results/logs, the immutable run manifest, timings, HTML/PDF plots and failures. Do not run FEMM on that machine.
4. Transfer the complete native output directory, not just the report or a scalar table. Wait for the complete **`ipm-high-output-v3`** bundle (29 records plus manifest) with reference commit `738d951...` from Windows. Record/check its manifest and per-file hashes.
5. Use the report-only join below in a new output directory. Keep original native-only artifacts and v3 reference bytes unchanged. Inspect all A/B/C/D quantities and waveforms, and report every failed gate and any unavailable comparison.
6. Hand back the measured commit, platform/dependencies/binary hashes, job statuses, timings, original native-only output and the joined comparison HTML/PDF/JSON. Include the current-frame limitation below. Do not merge or claim release qualification from diagnostic results.

## Registered work

| Phase | Cases | Native field jobs |
|---|---:|---:|
| A: SPM | 10 | 10 |
| B: IPM, including the two higher-output V-shape replacements | 12 | 12 |
| C: distributed winding | 5 | 4 supported; Prius remains UNSUPPORTED |
| D: ideal six-step BLDC | 3 | 9: standard, registered fine, low-current power discriminator |

Expected selection: **30 cases / 35 supported native field jobs / one planned unsupported Prius case**. The final matched bundle has 29 references. Accord, CREATOR and additional experimental Prius runs are separate work, not silently added to this matrix.

| Six-step fixture | Standard electrical grid | Registered fine electrical grid |
|---|---|---|
| `spm_14p12s_high_pole` | 3.75 degrees, 96 samples | 1.875 degrees, 192 samples |
| `spm_4p12s_small` | 7.5 degrees, 48 samples | 3.75 degrees, 96 samples |
| `spm_8p12s_reference` | 7.5 degrees, 48 samples | 3.75 degrees, 96 samples |

Keep registered geometry, currents, speed, normal spatial mesh, WST, solver settings, materials, grids and gates. The ripple-convergence limit is **5.0 percentage points**. Keep the historical #80 native record's 5.0340562459-point FAIL. Do not perform new 1.875/0.9375-degree diagnostic sweeps for `spm_8p12s_reference`, tune results, move waveforms, fit phases/signs/scales, widen tolerances, or replace failed records. The existing registered fine stages above are part of repeating A/B/C/D, not a new refinement experiment.

## Start native collection now

From an up-to-date PR #100 checkout, POSIX example:

```sh
git fetch origin fix/concentrated-tooth-coils-91
git worktree add --detach ../coilem-pr100-v3-738d951 738d9516e8500c5996c772bd96470472cbb9a0f9
cd ../coilem-pr100-v3-738d951
git rev-parse HEAD
git status --porcelain

python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock

# Keep the source-checkout build location and normal public process policies.
unset COILEM_MAGNETO2D_BINARY COILEM_MAGNETO2D_BUILD_RUSTFLAGS CARGO_TARGET_DIR RUSTFLAGS
unset COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL
unset COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
rustc --version
cargo --version

python -m tools.run_benchmarks --version
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.1/benchmark_spec.json --list
python -m tools.run_benchmarks \
  --suite benchmarks/abcd-v1.1/benchmark_spec.json \
  --phases A B C D --no-reference \
  --out-dir ../benchmark-output/pr100-v3-native-738d951 --pdf
```

The Python runtime supports 3.11–3.15; 3.12 is an explicit example using the committed 3.11–3.14 dependency pins. On Windows, use `.venv\Scripts\Activate.ps1` and PowerShell syntax for environment removal/multiline commands, then the same Python CLI arguments. Linux Gmsh must also have its OS shared-library dependencies available. Validate imports before solving if the environment is new.

Keep the terminal/process alive. Native jobs serialize within their own controller; the separate Windows FEMM process runs concurrently. If both workloads share a computer, record that concurrent load when reporting elapsed performance. Do not change global machine or solver settings to force different numbers.

Clean checkout is required. Use a fresh output directory outside the source. Do not use `--smoke` or `--allow-dirty` for this measured run. The harness records actual commit/source/binary/dependency hashes before and after each job, and refuses changed inputs or runtime during resume.

To resume, repeat the native command with the **same** arguments/output directory and add `--resume`. Do not change to a different reference mode on resume. A completed native-only run may exit **1** because it recorded a failed native/current gate; retain that failure. Exit **2** needs inspection of manifests/worker logs for errors or incomplete evidence. The manifest's `COMPLETE` means collection finished, not numerical qualification. A/B/C rows are `NOT_COMPARED` until v3 arrives. D may already show the fixed-axis golden FAIL described below.

## Attach FEMM v3 later without re-solving

The stock harness binds the reference bundle in the run's immutable selection. Switching a completed `--no-reference` run to `--reference-bundle` with `--resume` or `--report-only` is refused. Do not edit `run_manifest.json` to get around that check.

Use the added [report-only comparison tool](../../tools/report_benchmark_against_reference.py). Example layout:

```text
coilem-pr100-handoff/                    # PR checkout with this document/tool
coilem-pr100-v3-738d951/                 # unchanged measured source checkout
benchmark-output/pr100-v3-native-738d951/ # original native collection
reference-bundles/ipm-high-output-v3/    # completed transferred Windows bundle
```

From `coilem-pr100-v3-738d951`, with its environment active:

```sh
python ../coilem-pr100-handoff/tools/report_benchmark_against_reference.py \
  --source-root . \
  --expected-commit 738d9516e8500c5996c772bd96470472cbb9a0f9 \
  --native-out ../benchmark-output/pr100-v3-native-738d951 \
  --reference-bundle ../reference-bundles/ipm-high-output-v3 \
  --out-dir ../benchmark-output/pr100-v3-comparison-738d951 --pdf
```

Adjust directory names to the actual paths. This command checks source pin/hashes, completed native request/result identities and hashes, suite selection, reference identities/material/input/protocol hashes and array/grid contracts. It imports the pinned checkout's unchanged evaluator. It creates `comparison_manifest.json`, `winding_axis_diagnostics.json` and a new `report/` with plots/PDF, without building or importing the native solver, launching fields, mutating the native-only manifest, or rewriting reference data. The original native outputs remain necessary evidence; the new comparison manifest is not a resume manifest.

## Six-step current-frame limitation

PR #100 now measures current angle and commutation relative to the winding's phase-A axis. The old protocol validator selects a golden sector using the unadjusted physical angle. For 12s8p tooth coils, the phase-A offset is 30 electrical degrees. The exact frozen sector table remains the same; its interpretation now needs reconciliation in the formal benchmark contract.

The native-only run and late comparison **retain the historical fixed-axis gate results, including FAILs**. The join tool additionally checks the same table against the geometry-derived phase-A angle in `winding_axis_diagnostics.json`. That separate check does not shift any physical torque/current waveform, alter a golden file or threshold, or turn a failed historical gate into PASS. Report both results. Do not claim a fully passing release benchmark until the convention has been formally reconciled and FEMM v3 has passed scientific review.

The three registered FEMM six-step standard stages contain no Back-EMF. Their no-load Back-EMF parity is unavailable from that stage; do not invent a v2/v3 waveform comparison. The native low-current power discriminator does include its own registered Back-EMF. All other A/B/C physical summaries and torque/voltage waveforms should be compared with the new reference, including changed tooth-coil winding factors, phase-A axes and layer reductions.

## Windows lane and handoff boundary

Windows uses the same frozen source pin and original 29 reference cases with a FEMM adapter updated for PR #100's winding/geometry IR. Measured software is FEMM 4.2.0.0, pyFEMM 0.1.3, Windows 11 Home build 26200; private support begins from adapter commit `8b95decda27d475ddbb75e99d92744ebc8e53b28`. The updated adapter/runtime hashes, exact shared-source hashes, raw fields, source/flux extraction audits and unchanged normalizations are recorded locally. Private adapter code, installed binaries and local user paths are not part of this handoff commit.

Do not edit, switch or clean the Windows measured checkout while its reference run is active. Its baseline gate and per-region FEMM source/area guards must pass before accepting records. Native work uses a different checkout and machine. Any actual run failure must be reported with its measured numbers/evidence; this handoff does not authorize bypassing a smoke gate or silently rescaling a reference.
