# Release status

Updated November 3, 2026: the source candidate is **coilEM 0.5.0 Developer
Preview**, with **Magneto2D 0.4.0**. Windows and macOS protocol 1.6
measurements are complete at clean candidate `88aae101`, and the release
qualification gate passes. Version 0.5.0 has not been released; wheel
acceptance and publication remain pending.
The [release plan](docs/RELEASE_0_5_0.md) tracks those gates. PyPI installation
continues to select the published coilEM 0.4.0 release until 0.5.0 is published.

The [release notes](RELEASE_NOTES.md) describe the winding/flux corrections,
mesh controls, exact Prius examples, Layout ring, Phases preview, field/results
changes and migration limits. Layout #133 and Phases #134 are merged on main.
New hardware correlation #69/#82 is deferred until after v0.5.0. CREATOR #90 and named
presets #127 are outside the current milestone.

## Evidence retained before the final freeze

- [Windows protocol 1.6](benchmarks/windows-v050-20261102-88aae101/README.md)
  at `88aae101`: 52 supported native jobs, 46 PASS, one planned unsupported
  row and 336/336 gates PASS. All 46 fresh reference records are retained at
  sealed adapter `faced858`. The original manifest remains REVIEW_REQUIRED;
  the [subsequent reviewed bundle](benchmarks/reference-baselines/protocol16-reviewed-20261103/README.md)
  accepts the unchanged records for registered parity with a hash-bound review.
- [Adapter archive and version comparison](benchmarks/reference-adapters/windows-femm42-v3-20261102/README.md)
  identify the recovered implementation and FEMM executables used on this
  physical Windows host. The 29 legacy reference cases reproduce exactly.
- [Published Mac comparison](benchmarks/windows-v050-20261102-88aae101/macos-comparison.txt)
  covers 52 jobs using the older full report and rounded values for the 17
  additions. No available torque/EMF metrics exceed registered platform
  tolerances. Source pins and missing raw new-case data remain explicit;
  this is not same-candidate Mac qualification.
- [Windows A/B/C/D requalification](benchmarks/windows-prius-requal-20261018/README.md)
  at `5b6cb61`: 35 supported jobs, 28 PASS, 1 YELLOW and a planned unsupported
  legacy Prius row. All recorded gates and values match the preceding Windows
  report; its record retains the 53 measured physics-source hashes.
- [Pyleecan Prius development report](docs/benchmarks/pyleecan-prius-v1/README.md)
  at `d993d76`: two fixed software references, 17 jobs, 568 field reports and
  10 original software checks passing. The complete curve, controls and source
  identities remain intact. Final-candidate collection is still tracked by #126.
- [Fresh FEMM repeat](benchmarks/femm-main-20261018-0417736/README.md)
  at `0417736`: 29/29 exact physical payloads and extraction audits. It verifies
  the retained reference, without measuring native fields on a future candidate.
- [Historical Honda comparison](docs/hardware-validation/honda-accord-2005/real-winding-comparison/README.md)
  at `738d951`/`50fe405`: exploratory, blind N35 assumption, simplified rotor,
  no hardware pass/fail. The planned fitted variant is not claimed as evidence.

The [v0.5.0 evidence index](benchmarks/v0.5.0/README.md) links the new artifacts
and remaining qualification work. The [v0.4.0 benchmark report](benchmarks/v0.4.0/README.md)
remains the historical release evidence.
Historical qualification and measured commit IDs are preserved; changing the
application version does not relabel them as final 0.4.0 measurements.

## Gates before tagging

The Windows A/B/C/D collection retains the clean versioned candidate,
source/binary/dependency hashes, requests, results and complete comparison.
Reference review and the registered Windows comparison are complete in the
[candidate qualification update](benchmarks/candidate-qualification-20261103/README.md).
The [exact-candidate Windows Prius audit](benchmarks/candidate-qualification-20261103/prius/README.md)
passes all 10 software checks across 17 jobs and 568 field reports, with its
frozen inputs and complete raw archive retained. The
[exact-candidate macOS comparison](benchmarks/candidate-qualification-20261103/macos/report/benchmark_report.md)
records 46 PASS and 336/336 gates, and its record replaces the historical one.
The release assessment [passes](benchmarks/v0.5.0/release-qualification.json).
Linux/Python 3.15 smoke coverage does not establish full numerical parity.

Run the release-wheel workflow with `publish=none` on the exact candidate.
All four wheel targets, supported Python versions, bare-Linux acceptance and
installed-package walkthroughs must pass before the release decision. Owner
acceptance of the remaining limitations precedes the matching tag and protected
publication workflow. The measured Windows candidate is identified above;
no completed release or cross-platform release qualification is asserted here.

[Validation](docs/VALIDATION.md) records the qualified scope and limits.
[Runtime settings](docs/RUNTIME_SETTINGS.md) documents the native environment.
Elmer is disabled by default and requires a separate runtime and development
opt-in. No hosted service, FEMM implementation or motor thermal solver is bundled.

The snapshot manifest records original source provenance, listed public patches
and current file hashes. It is an integrity check, not numerical certification
or a review of repository history. Private vulnerability reporting is enabled.
