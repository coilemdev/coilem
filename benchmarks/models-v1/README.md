# Motor benchmark coverage

The benchmark collection includes the A/B/C/D matrix, **Pyleecan Prius 8p48s**,
and **Honda Accord 2005 16p24s**. They have separate physical models and reference
contracts. Their numerical outcomes are not interchangeable.

| Benchmark | Measured evidence | Interpretation |
| --- | --- | --- |
| A/B/C/D FEMM matrix | [Windows regression](../windows-prius-requal-20261018/README.md), measured at `5b6cb61`: 35 supported jobs; 28 PASS, 1 YELLOW, 1 unsupported legacy row | Software comparison against frozen FEMM v3, protocol 1.3.0 |
| Pyleecan Prius 8p48s: BEMF and loaded torque | [Complete report](../../docs/benchmarks/pyleecan-prius-v1/README.md), measured at `d993d76`: 17 jobs, 568 audited fields, 10/10 software checks PASS | Exact pinned software-model reproduction, including all thirteen torque angles and separate angular/mesh controls |
| Honda Accord 2005 16p24s | [Winding-as-built comparison](../../docs/hardware-validation/honda-accord-2005/real-winding-comparison/README.md), measured at `738d951` / `50fe405`: 18 speed comparisons, 198 locked-rotor solves, 9 current peaks | Exploratory hardware correlation; N35 assumed and simplified rotor; no hardware pass/fail |

These links retain their original measured commits. The later frozen v0.4.0
candidate `4b88c4e1687acd6c40d37af2ee4d33348824734e` has separate external
qualification evidence: full Windows and macOS A/B/C/D collections and a full
17-job / 568-field Prius repeat. Its raw reports retain their original presentation.
Adding this workflow does not retroactively change that candidate or establish a
fresh Honda measurement on it.

## Run the selected models

From a clean committed checkout with the documented locked environment and
release Magneto2D executable:

```sh
python -m tools.run_model_benchmarks --list
python -m tools.run_model_benchmarks --out ../benchmark-output/all-models
python -m tools.run_model_benchmarks --model pyleecan-prius --model honda-accord --out ../benchmark-output/prius-and-accord
python -m tools.run_model_benchmarks --resume --out ../benchmark-output/prius-and-accord
```

The default selection runs all three benchmarks sequentially. The Prius entry
always includes the complete torque-angle curve and separate angular/Fine
controls. Honda runs its no-load sweep, the registered 198 locked-rotor points,
then assembles the hardware comparison and both SVG charts. It preserves the
existing 300-degree electrical zero-offset convention and winding as built.

The combined `benchmark-report.md` links each complete model report.
`model-benchmarks.json` records the selection, source/binary/runtime identity,
grading-input hashes, attempt states, and all portable output hashes. Exact
grading inputs are copied before fields start. Each subprocess uses a private
runtime directory. Resume verifies completed evidence before skipping it;
an interrupted model gets a new attempt directory so partial evidence survives.
The A/B/C/D and Prius collectors also retain their own registrations and audits.

This source workflow does not add dependencies on Pyleecan or FEMM. The installed
`coilem benchmark` command continues to run the registered A/B/C/D suite; the new
model selection is a source-checkout command. No historical reference bundle,
case ID, limit, or measured record is rewritten.

## Why was planned coverage yellow?

The matrix's `ornl_prius_2004_ipm` row is a **legacy ORNL-derived HoleM50
reconstruction**, distinct from the exact pinned Pyleecan Prius model. Its
registered public request remains UNSUPPORTED. Passing the Pyleecan software
benchmark does not qualify that request or establish ORNL hardware accuracy.
That hardware work is deferred to **v0.5.0** (#69/#82).

Previously, phase presentation treated that unsupported row as incomplete active
coverage and coloured Phase C yellow. New reports show explicitly deferred
hardware rows in grey, and phase colours describe active cases: Phase C is green
when its four active cases pass. Every raw status, gate, count and the overall
numerical status still includes the complete registered selection. Unexpected
unsupported cases remain yellow; a failed deferred model is still a failure.

The V-shape baseline's back-EMF YELLOW is a measured numerical discrepancy and
remains yellow. Honda's measured residuals also remain visible: mean back-EMF
error +0.6% (range -2.6% to +5.4%) and mean peak-torque error -3.6% (range -8.3%
to +1.8%). Including Honda in the benchmark does not turn those results into a
hardware acceptance verdict.
