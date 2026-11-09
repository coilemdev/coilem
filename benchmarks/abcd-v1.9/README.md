# Benchmark protocol 1.9.0: Newton for every request

Protocol 1.9.0 is the default A–D suite from v0.5.6, the release where Newton becomes coilEM's
default nonlinear method. It is [protocol 1.6.0](../abcd-v1.6/README.md) with one change: every
request that set `solve_params.nonlinear_solver` to `picard` now sets `newton`.

## What changes

| | Protocol 1.6.0 | Protocol 1.9.0 |
| --- | --- | --- |
| Phase A (19 cases) | Picard | Newton |
| Phase D (3 cases, 9 jobs) | Picard | Newton |
| Phases B and C (25 cases) | Newton | Newton, same fixture files |
| Motors, materials, currents, grids, iteration caps, cases and gates | — | unchanged |

`tools/make_newton_protocol.py` writes the 28 changed requests and `benchmark_spec.json` from
protocol 1.6.0. `tests/test_benchmark_newton_registration.py` checks that it reproduces them and
that each changed request differs from its 1.6.0 request in that one field alone. `request_change`
in the suite lists the changed jobs.

## FEMM references

FEMM solves its own nonlinear problem and never reads coilEM's nonlinear method, so the frozen
FEMM records stay valid. The suite reuses the
[reviewed protocol 1.6.0 bundle](../reference-baselines/protocol16-reviewed-20261103/README.md)
through `reference_compatibility.solve_option_change`, a hash-bound bridge (schema
`coilem.solve_option_bridge/v1`) like protocol 1.4.0's iteration-cap bridge:

- It names the measured suite (`abcd-v1.6/benchmark_spec.json`) by path and SHA-256.
- `backend/benchmark_suite/references.py` loads every changed request and its 1.6.0 request. It
  refuses the bridge unless the only difference is `nonlinear_solver` from `picard` to `newton`.
  The harness registers that change, and no other, in `REFERENCE_INDEPENDENT_SOLVE_OPTIONS`.
- The bundle's review receipt is checked against the measured 1.6.0 suite, which the bridge
  reuses. No record, review or bundle file changes.

## Evidence that Newton holds

Measured at PR #221 (e12918d), with Newton copies of the Picard requests and everything else
unchanged:

- **macOS** (M4, same commit, Picard and Newton interleaved per case): 22/22 A/D cases PASS with
  both methods. Values agree within 6e-5, apart from quantities that are essentially zero. No
  Newton solve fell back to Picard. A/D job time dropped from 1,731 s to 1,052 s (1.64×) and solver
  CPU from 10,269 s to 4,484 s.
- **Windows** (Ryzen 7 7700): A–D 336/336 gates PASS with the Newton copies. Torque-waveform RMS
  differences from the earlier native results were at most 0.004%.

## Run it

```sh
python -m tools.run_benchmarks --out-dir ../benchmark-output/v1.9
```

`coilem benchmark` runs it by default. A record measured with protocol 1.6.0 does not qualify
v0.5.6: the release needs a two-platform requalification with this suite.
