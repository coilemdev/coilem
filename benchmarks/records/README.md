# Published benchmark records

`coilem benchmark` matches a run against these records. Each JSON file is
the compact outcome of one complete A/B/C/D run on one platform, as the
current evaluator grades it against [protocol 1.3.0](../abcd-v1.3/README.md)
and the frozen [`ipm-high-output-v3`](../reference-baselines/ipm-high-output-v3/manifest.json)
FEMM reference. For each case it holds:

- the verdict;
- every gate's status;
- the measured values behind the numerical gates: mean torque, and the
  back-EMF fundamental and peak for A/B/C, and each lane's mean torque for D.

It also holds the hashes of the physics sources the run measured, the
environment, and each case's wall time, which `coilem benchmark --list` uses
for its estimates.

| Record | Measured at | Evidence | Outcome |
| --- | --- | --- | --- |
| [`macos-arm64.json`](macos-arm64.json) | `738d951` | [Historical macOS native run](../macos-native-20261015-738d951/README.md) | 28 PASS, 1 YELLOW, 1 unsupported |
| [`windows-x86_64.json`](windows-x86_64.json) | `5b6cb61` | [Windows Precise mesh requalification](../windows-prius-requal-20261018/README.md) | 28 PASS, 1 YELLOW, 1 unsupported |

The Windows run measured the current Precise mesh source and reproduces every
verdict, gate and recorded value of the previous Windows record exactly. Its
record was rebuilt from those measurements, including the new source hashes
and case times. Fast mesh remains experimental.

The macOS record retains its original measurements and source hashes. It has
not been remeasured for the mesh and conditional reference-dispatch changes, so a current
macOS run reports **NOT_COMPARABLE** against it until new macOS evidence is
collected. Numerical agreement alone does not bypass the source guard.

There is no Linux record yet. On Linux x86_64, `coilem benchmark` matches
against the Windows x86_64 record and says so. The tolerances below come from
the measured differences between platforms, so this comparison is still
meaningful.

## Matching a record

`coilem benchmark` first hashes the installation's physics sources and
compares them with the record's. These are the Python modules, the material
curve, pinned reference assets, and the Magneto2D Rust sources and lock file named in
[`backend/benchmark_suite/physics.py`](../../backend/benchmark_suite/physics.py).
A wheel carries the solver executable, not its Rust sources, so the build
stamps their hashes into the package. This is how a 0.4.0 install is checked
against a record measured at an earlier commit, without Git.

If a physics source differs, the result is **NOT_COMPARABLE**: the run still
grades every case, but differences are expected.

Otherwise each case must have:

- the same verdict and the same status for every gate;
- mean torque within 0.5% of the record, or 0.001 N·m if that is larger;
- back-EMF fundamental within 0.05%, or 0.001 V if that is larger;
- back-EMF peak within 1.5%, or 0.001 V if that is larger.

All four hold for **MATCH**; any miss is **DIFFERS**, and the report names
the case and the value.

### Where the tolerances come from

At `738d951` the macOS and Windows meshes differed by a few elements per case.
Across the 26 A/B/C cases and the three D cases, that moved:

| Value | Largest difference between platforms |
| --- | --- |
| Mean torque | 0.19%, or 0.012 N·m |
| Back-EMF fundamental | 0.007% |
| Back-EMF peak | 0.63% |

No verdict or gate status differed. Each tolerance is about 2.5 times its
largest difference. `tests/test_benchmark_command.py` checks that each
platform's run matches the other platform's record: they match on all 30
cases, using at most 43% of any tolerance.

## Building a record

Records are built from committed evidence, never edited by hand:

```sh
python -m tools.build_benchmark_record benchmarks/windows-prius-requal-20261018 \
    --out benchmarks/records/windows-x86_64.json
```

The tool grades the run's recorded measurements again with the current
evaluator, against the registered suite and frozen bundle, with zero field
solves. It refuses a run that:

- measured a request the suite does not register;
- measured uncommitted code;
- lacks a physics-source hash.

The two records above were graded this way. The Windows grading reproduces
the published requalification exactly. The macOS run was native-only (no FEMM
comparison), so this is its first grading against the frozen reference.
`tests/test_benchmark_command.py` rebuilds both records and requires them to
be byte-identical.

A platform whose physics sources change needs a new complete run before its
record can match that source. Commit its evidence beside the others and
rebuild its record from it; historical platform records retain their measured
identity and continue to enforce the source guard.

## Reproduce this record

Each release's notes carry this block, with the version filled in:

```sh
uv tool install coilem==X.Y.Z
coilem benchmark --quick    # one case per phase, about 5 minutes
coilem benchmark            # all 30 cases, about 50 minutes
```

The output folder holds the full report, plus a shareable Markdown and JSON
report under `share/` that names no local paths. The shareable report passes
the same path check as `tools/verify_snapshot.py --publication`, so it can be
posted in an issue as-is.
