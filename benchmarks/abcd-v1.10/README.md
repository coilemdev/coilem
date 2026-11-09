# Benchmark protocol 1.10.0: the ORNL Prius placeholder is retired

Protocol 1.10.0 is the default A–D suite from v0.5.7. It is
[protocol 1.9.0](../abcd-v1.9/README.md) with one change: the case
`ornl_prius_2004_ipm` is no longer in the scored suite
([public issue 233](https://github.com/coilemdev/coilem/issues/233)).

## What changes

| | Protocol 1.9.0 | Protocol 1.10.0 |
| --- | --- | --- |
| Cases | 47 (46 solved, 1 recorded as UNSUPPORTED) | 46, all solved |
| Jobs | 53 | 52 |
| Requests, grids, gates, materials | — | unchanged, the same fixture files |
| FEMM reference bundle | reviewed protocol 1.6.0 bundle, 46 records | the same bundle, the same 46 records |

- **What the placeholder was.** A deferred ORNL 2004 Prius hardware fixture
  with a HoleM50 rotor. The public policy rejects that rotor, so the case was
  recorded as UNSUPPORTED, ran no field solve and never had a FEMM record.
- **Why it leaves.** Its unsupported row read as if coilEM had no Prius
  benchmark. Retiring it is a coverage and reporting clean-up. It is not a
  solver-time saving, since the case never solved.
- **What stays.** Protocols 1.1.0 to 1.9.0, their fixtures, the published
  records and their UNSUPPORTED outcomes are unchanged. No earlier evidence is
  relabelled.

`tools/make_protocol_1_10.py` writes `benchmark_spec.json` from protocol 1.9.0,
and `tests/test_benchmark_protocol_1_10.py` checks that it reproduces the file
and that nothing else differs. `case_change` in the suite names the retired
case and the reason.

## The Prius is still benchmarked

- **Pyleecan Prius software benchmark.** The dedicated 17-job benchmark stays
  part of Windows and macOS release qualification. It has its own model
  (`backend/reference_models/prius.py`), case IDs and report
  ([docs/benchmarks/pyleecan-prius-v1](../../docs/benchmarks/pyleecan-prius-v1/README.md)).
- **ORNL hardware correlation.** Comparing coilEM with ORNL's measured motor
  is separate work, tracked in
  [public issue 82](https://github.com/coilemdev/coilem/issues/82). A future
  supported hardware case needs its own frozen inputs, reference evidence and
  review.
- **The experimental ORNL example in the app** is unchanged.

## FEMM references

The suite keeps protocol 1.9.0's hash-bound bridge to the
[reviewed protocol 1.6.0 bundle](../reference-baselines/protocol16-reviewed-20261103/README.md)
and adds `reference_compatibility.retired_cases`.
`backend/benchmark_suite/references.py` accepts a retired case only when:

- the measured suite has that case, and
- the bundle holds no record for it.

So a bridge can drop a case that never had a reference, and cannot drop a
measured one. Leaving a case out without naming it is still refused. The
release gate (`tools/release/qualification.py`) applies the same rule, and for
this suite it plans no unsupported case: any UNSUPPORTED row fails it.

## Run it

```sh
python -m tools.run_benchmarks --out-dir ../benchmark-output/v1.10
```

`coilem benchmark` runs it by default. A record measured with protocol 1.9.0
does not qualify v0.5.7: the release needs a two-platform requalification with
this suite.
