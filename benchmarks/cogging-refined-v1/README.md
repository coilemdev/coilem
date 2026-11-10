# Registered refined cogging cohort, protocol 1.7.1

This cohort contains exactly three distributed SPM geometries: 8p24s, 8p48s
and 12p36s. The native requests use `very_fine` mesh and retain the current
Newton solver, corner refinement, material contract, 25-point cogging grid and
original case floors. Only native mesh density changes from the measured
normal requests in `measured-suite.json`.

The reviewed reference bundle is
`benchmarks/reference-baselines/cogging-refined-20261110`. It freezes the three
completed FEMM half-gap sweeps at their original adapter commit and input hashes.
The native mesh choice does not change the separately reviewed FEMM recipe.
The explicit hash-bound bridge verifies every request field and permits only
`normal` to `very_fine` native density. Original normal-mesh failures remain in
the original suite and investigation record.

The owner authorized registration after the raw-data review: all 75 refined
model/answer pairs, zero-current and winding-area audits, material coercivity,
independent closure and zero mean were verified. Six independently rerun
endpoints reproduced the models, solutions and extracted data exactly.

Run the complete native qualification from a clean candidate checkout:

```powershell
python -m tools.cogging_qualification --candidate <full-candidate-sha> --directory <new-output-folder>
```

The existing release benchmark workflow has a dedicated
`cogging-refined-very-fine` collection. With `runner=both`, it builds the pinned
candidate independently on Windows and macOS, collects all three requests, and
uploads immutable measurements plus a compact qualification report. The report
is independently regraded and binds candidate physics, source and result hashes,
the reviewed bundle, actual native mesh metadata and all 18 gates.

## Windows and macOS qualification, November 10

Both independent builds and full collections passed at candidate
`3ae3458ee45a6b2564f230103bd6c1ed33b91290`:
[workflow 42893314080](https://github.com/coilemdev/coilem/actions/runs/42893314080).
All **18 gates on each platform, 36 total**, pass after independent regrading of
the downloaded request/result artifacts. The
[qualification record](qualification-20261110/qualification.json) binds the
candidate, suite, reviewed reference bundle, physics files and both original
platform reports. The reports retain all native cogging waveforms and result
hashes; the workflow artifacts retain the complete request/result envelopes.

| Fixture | Windows peak-to-peak / H1 error | macOS peak-to-peak / H1 error |
| --- | ---: | ---: |
| 8p24s distributed | 3.0806% / 2.0917% | 3.0177% / 2.1114% |
| 8p48s distributed | 3.2697% / 2.5120% | 3.1618% / 2.4531% |
| 12p36s distributed | 4.0721% / 3.1245% | 4.1034% / 3.1267% |

Windows x86-64 collection took **489.902 s (8 min 10 s)**; macOS arm64 took
**788.186 s (13 min 8 s)**. These are complete collection wall times including
execution and report generation, excluding dependency installation and native
build. Actual native runtimes by case are 130.659/177.862/157.618 s on Windows
and 253.730/270.820/223.502 s on macOS.

Both platforms used the registered `very_fine` native mesh settings. Their
representative element counts were 105690/126630/118970 on Windows and
105682/126572/118684 on macOS. The largest pointwise cross-platform torque
difference was 0.021078 N·m; waveform values are not claimed to be bit identical.
The native periodic endpoint is reused, so it is not an independent native
closure measurement. The FEMM reference closure checks use independent fields.

This establishes software parity for these three registered requests. The
normal application default and original matrix remain unchanged. Application
qualification policy and full E/F inclusion are tracked in the
[integration plan](../femm-ef-20261110/formal-qualification.md); hardware
validation is outside this record.

To publish a new matched two-platform collection after downloading its artifacts:

```powershell
python -m tools.publish_cogging_qualification --windows <windows-artifact> --macos <macos-artifact> --candidate <measured-sha> --workflow <run-url> --out <new-record-directory>
```
