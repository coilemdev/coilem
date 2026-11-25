# Phase G rotor references from FEMM

FEMM's rotor iron loss for the eight Phase G rotor histories (benchmarks/g-v2.0), so that coilEM's rotor
loss is graded against a second solver and not only on its own checks.

Each history is a full mechanical turn of 384 positions plus the closing pose, solved on **one fixed FEMM
mesh**: the rotor stays drawn at 0 degrees and FEMM's periodic air-gap boundary (an unmeshed band in the
air gap) turns it. Every rotor element's field is then already in rotor axes, and no remeshing noise gets
into the loss. For an outer rotor the band turns the stator by minus the rotor angle, which is the same
relative position (checked on FEMM 5 against the rotor drawn at the angle and remeshed, on the phase
flux linkages and the rotor sum of B squared times area).

The loss is worked out from the FEMM fields by `tools/rotor_loss_reference.py`, which shares no code with
coilEM's loss calculation, using the same M350-50A coefficients. Each component (hysteresis, lamination
eddy, total) of coilEM's 384-position loss must be within 10% of FEMM's or 1 mW.

| File | Runs on | Does |
|---|---|---|
| `request.py` | coilEM environment | writes the frozen request of each history to `benchmarks/g-v2.0/femm-requests` (committed; done) |
| `collect.py` | FEMM machine | solves one history, or one shard of it |
| `report.py` | anywhere with numpy | turns a complete history into `benchmarks/g-v2.0/references/femm-rotor/<history>.json` |
| `__main__.py` | FEMM machine | prepares, shards over workers, and reports each history |

Inner rotors are drawn by the FEMM E adapter and outer rotors by the FEMM F adapter's geometry lowering,
the same drawings as the 0.5.9 Phase G stator references.

## On macOS or Linux with FEMM 5

FEMM 5 (femm-qt) at `~/Applications/femm_gui.app` and a Python 3.12 environment with
`tools/femm_reference/requirements.txt` except pywin32 (numpy, pydantic):

```bash
PYTHONPATH=. python -m tools.phase_g_femm run --out ~/coilem-phase-g-femm5/out --workers 4 --femm5 33
PYTHONPATH=. python -m tools.phase_g_femm status --out ~/coilem-phase-g-femm5/out
```

`--femm5 33` meshes with a 33 degree minimum angle, which gives about FEMM 4.2's element counts (FEMM 5's
mesher is coarser at FEMM's default 30). Records then name FEMM 5 as their solver.

## On Windows with FEMM 4.2

FEMM 4.2 in `C:\femm42` and a Python environment with `tools\femm_reference\requirements.txt`:

```bat
git fetch origin v0.6.0/phase-g-femm-references
git checkout v0.6.0/phase-g-femm-references
py -3.12 -m venv .venv-femm
.venv-femm\Scripts\pip install -r tools\femm_reference\requirements.txt
set PYTHONPATH=%CD%
.venv-femm\Scripts\python -m tools.phase_g_femm run --out D:\coilem-phase-g-femm --workers 4
```

## Both

- `run` takes every history by default (`--history NAME` for one, repeatable). It continues where it
  stopped: finished poses are kept. A changed request, collector or FEMM build is refused in the same
  folder; use a new one.
- Each pose keeps its rotor fields (about 0.3 MB) and deletes its FEMM answer once hashed, except the
  first and the closing pose (`--keep-answers` keeps all, 8 to 22 MB each). Solving stops below
  `--min-free-gb` (6) free.
- When a history is complete, `run` writes its record. To write them again: `python -m tools.phase_g_femm.report --out DIR`.
- Then grade coilEM's stored record against them and rewrite the page, without solving:

```bash
PYTHONPATH=. python -m tools.run_phase_g --regrade
PYTHONPATH=. python -m tools.run_phase_g --check
```

Commit `benchmarks/g-v2.0/references/femm-rotor/*.json`, `results/coilem.json` and `RESULTS.md` in the private
repository. They are generated measurements (`tools/release/private_evidence.py`) and are left out of the public
source export and the wheel.
