# Current Windows A–D evidence for the v0.5.5 candidate

This packet publishes the actual complete Windows collection measured at
`34de0f4ca1604311f15edf6fb49b5a2a1bf27909`: **52 supported native jobs**, **46
passing cases**, the planned unsupported legacy ORNL Prius row, and
**336/336 gates PASS** against the unchanged reviewed protocol 1.6 references.

The current `benchmarks/records/windows-x86_64.json` points to this packet and
retains all **69 actual measured physics-source hashes**. This is a new record
of an existing current-candidate collection, not a source-equivalence claim
about the older 64-file record. The previous Windows evidence remains in its
historical packets, and the macOS record keeps its earlier measured identity.

Public `report/` artifacts are sanitized projections of the recorded native
measurements. All waveforms, verdicts and gated values are unchanged; local
runtime paths are omitted. Measured harness **1.10.0** and the actual native
source commit are retained. Harness **1.11.0** supplies report presentation
and additive numerical-resolution diagnostics, without changing any gate.

The independent fresh FEMM repeat completed all 46 supported cases and exactly
reproduced the reviewed reference waveforms. The existing accepted reference
bundle and its public identity remain unchanged. Publication ran no new
native or FEMM fields and did not modify original measurements.

The normal composed benchmark additionally reports Phase E as experimental
and Phase F under its separate Windows-scoped engineering review. This A–D
record does not qualify cogging or establish complete cross-platform v0.5.5
release qualification.

```sh
python -m tools.verify_windows_abcd_packet
```

The check recomputes all numerical comparisons, including loaded d/q and BLDC
gates, and verifies the compact record, fixture inputs, measured physics,
artifact hashes and path sanitization without field solves. See the
[HTML report](report/coilem_benchmark_report.html) and
[publication provenance](provenance.json).
