# Public A–F benchmark

`coilem benchmark` runs 69 registered cases across phases A–F. `--quick`
runs six cases, one per phase, using each case's complete registered grid.
Phase E cogging is explicitly experimental in the command and reports.

```sh
coilem benchmark --list
coilem benchmark --quick --out <output-folder>
coilem benchmark --out <output-folder>
coilem benchmark --phase E --phase F --out <output-folder>
```

Keep output outside the source checkout or installation. Runtime depends on
the computer and selected cases; `--list` shows measured case times where a
platform record exists. The command uses the installed Magneto2D solver and
frozen FEMM data. It does not launch FEMM.

## Independent evidence

The [collection descriptor](../benchmarks/public-benchmark-collection.json)
pins three components. Each retains its own suite, reference identity,
measured candidate and child run manifest.

| Phases | Protocol | Reference and comparison scope |
| --- | --- | --- |
| A–D | 1.6.0 | Reviewed frozen references and separate Windows/macOS platform records |
| E | 1.7.0 | Experimental cogging references; no accepted platform record |
| F | 1.8.0 | Reviewed Windows outrunner references and a separate Windows record |

The combined report preserves every numerical grade and gate. Experimental
E grades, including FAIL or YELLOW, remain visible and do not establish
qualification or change the recorded-component match result. Execution errors
and incomplete cases in any phase still fail the command. Exit codes are 0
for matching recorded components, 1 for a recorded-component mismatch or
unavailable comparison, and 2 for an execution or integrity error.

F's Windows engineering qualification applies to the tested torque/back-EMF
families and custom full-cycle Normal/Precise solver settings described in
[OUTRUNNER.md](OUTRUNNER.md). It does not qualify ordinary Standard/Preview
settings, other platforms, cogging or other untested outputs. The reviewed
packet preserves the two LRK sensitivity flags and the accepted source-cohort
exception; it does not rewrite their original outcomes.

## Resume and saved reports

```sh
coilem benchmark --resume --out <output-folder>
coilem benchmark --report-only --out <output-folder>
```

Resume restores the saved phase/quick selection and verifies pinned suite,
reference and record identities. Complete children rebuild their reports;
interrupted children continue through the existing per-suite executor.
Runtime retention and the free-space floor are also preserved; explicit
`--keep-runtime` or `--min-free-gb` options update those operational settings.
`--report-only` performs no field solves and requires every selected child
run. Changed inputs are refused. Historical single-suite runs retain their
original `python -m tools.run_benchmarks` resume/report-only commands.

The parent writes `collection_manifest.json`, a combined HTML/Markdown/JSON
report under `report/`, and portable Markdown/JSON under `share/`. Per-suite
artifacts remain under `suites/<component>/`. A collection summary cannot be
published as a single platform record: A–D and F keep separate records and
E has none.

The low-level developer harness still defaults to protocol 1.6.0. The
registered 1.6/1.7/1.8 fixture bytes, gates and historical evidence remain
unchanged. The public command composes them rather than creating a new
physical protocol.
