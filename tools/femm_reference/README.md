# FEMM E/F reference adapter

The Phase E cogging and Phase F outrunner collectors live in this repository.
They use the same batching, immutable position checkpoints, resume validation,
and advisory progress files as `tools.run_reference_positions`. No separate
adapter repository, historical checkout, or `C:/bench` directory is required.

This is optional benchmark tooling, run from a source checkout on Windows.
Install FEMM 4.2 separately and register its COM server. The application wheel
continues to use Magneto2D/Elmer; installing coilEM does not install FEMM.

## Setup and commands

Use a dedicated Python 3.11–3.14 environment. The requirements file pins the
environment used for the November 10, 2026 validation:

```powershell
python -m venv .venv-femm
.venv-femm/Scripts/python -m pip install -r tools/femm_reference/requirements.txt
.venv-femm/Scripts/python -m tools.femm_reference --verify-sources
```

The default binary directory is `C:/femm42/bin`. Set `--femm-bin` or
`COILEM_FEMM_BIN` for another installation directory. The adapter verifies the
recorded hashes of `femm.exe`, `fkn.exe`, and `triangle.exe`, including the actual
COM server process. The executable files themselves are not bundled.

Prepare all models without opening FEMM or solving fields:

```powershell
.venv-femm/Scripts/python -m tools.femm_reference --prepare-only --out-dir output/femm-preflight
```

Collect the standard E/F matrix:

```powershell
.venv-femm/Scripts/python -m tools.femm_reference --out-dir output/femm-ef --workers 8 --batch-size 4
```

Repeat that command with `--resume` after interruption. Each committed position
is verified against its request, source identity and retained artifact hashes.
Use a new output directory after changing adapter sources, dependencies,
requests, or selection. Existing runs retain their original source identity;
the consolidated adapter cannot resume an older external adapter's run.

Use `--phases E` or `--phases F` for one phase, or `--include-refinements` to
include the three additional E refinement diagnostics. `--selection file.json`
accepts the runner's case-to-position mapping for bounded pilots; an incomplete
grid is explicitly non-gating and never assembled as a full reference.

The generic entry point also accepts the producers directly:

```powershell
python -m tools.run_reference_positions --producer tools/femm_reference/e_producer.py --producer tools/femm_reference/f_producer.py --selection tools/femm_reference/data/standard-selection.json --out-dir output/femm-ef --workers 8 --batch-size 4
```

## Preserved physics and source history

The standard matrix has 1,502 independent field solves: 350 E positions across
12 cases and two controls, and 1,152 F positions across 10 cases and two controls.
E retains its original 25-point grid. F retains 48 loaded and 48 no-load positions
at 7.5 electrical degrees. Meshes, material curves, currents, extraction,
normalization and derivative stencils retain their measured definitions,
including the existing 0.5 mm hub bulk recipe and half-gap controls.

The inputs replay the E protocol 1.7 and F protocol 1.8 requests used in the
November 10 collection. They are distinct from the later winding-configuration
expansion under `benchmarks/phase-e-v1`; this command does not silently substitute
new inputs or collect that expansion.

- `e_producer.py` and `f_producer.py`: scheduler interface and position execution.
- `phase_e.py`, `phase_f.py`, `hub.py`, `ir_helpers.py`: preserved lowering and extraction.
- `automation.py`: owned DispatchEx COM processes, kill-on-close Windows job
  objects, actual binary checks and command timing.
- `runtime.py`: portable paths, source verification and worker namespace isolation.
- `data/`: registered inputs, complete selections, scheduling estimates,
  expected binary hashes and the inherited LRK review receipt.
- `_vendor/e` and `_vendor/f`: the required, byte-preserved model/geometry helpers
  from the measured sources. These are explicit historical reference snapshots.
  Each phase imports its snapshot in a separate worker process; neither changes
  the application's `backend` namespace.
- `source-manifest.json`: per-file source hashes, origins and transformations.
  Copied physics definitions also carry their original AST hashes.

Keeping the two small reference snapshots prevents changes to the active product
backend from silently changing the FEMM baseline. Their sources are now readable
and versionable in coilEM. Future physics changes require a new reviewed source
identity and validation; historical run artifacts and seals remain untouched.

Source imports and extraction are covered by coilEM's repository license and
existing third-party notices. The M350-50A curve retains its BSD-3-Clause
provenance in the preserved material contract and `THIRD_PARTY_NOTICES.md`.

All results retain `REVIEW_REQUIRED`. The existing E periodicity/zero-mean
failures and inherited LRK findings remain visible. A faster or relocated run
does not waive those findings or confer release qualification.

## Consolidation validation, November 10, 2026

All 26 standard preparation records match the completed reference collection
exactly. A fresh 19-position E/F pilot also matched all 19 model hashes, answer
hashes and physical payloads, including the hub and mesh controls. Timing and
owned-process metadata were compared separately. This is a bounded source
relocation check; the earlier complete 1,502-position run established the
approximately 3 hour 16 minute collection-and-comparison time.

The regression tests exercise imported-source integrity, preserved physics ASTs,
registered grids, worker namespace isolation, a relocated checkout without the
old source directories, checkpoint recovery and FEMM installation-path forwarding:

```powershell
python -m pytest tests/test_femm_reference_adapter.py tests/test_reference_positions.py -q
```
