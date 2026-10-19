# Release status

Prepared October 19, 2026: the source candidate is **coilEM 0.4.0 Developer
Preview**, with **Magneto2D 0.3.3**. Version preparation is complete in source;
final numerical qualification, wheel acceptance and publication remain pending.
The [release plan](docs/RELEASE_0_4_0.md) tracks those gates. PyPI installation
continues to select the published release until 0.4.0 is published.

The [release notes](RELEASE_NOTES.md) describe the winding/flux corrections,
mesh controls, exact Prius examples, Layout ring, Phases preview, field/results
changes and migration limits. Layout #133 and Phases #134 are merged on main.
New hardware correlation #69/#82 is deferred to v0.5.0. CREATOR #90 and named
presets #127 are outside the current milestone.

## Evidence retained before the final freeze

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

The [benchmark report](benchmarks/v0.4.0/README.md) links the complete artifacts.
Historical qualification and measured commit IDs are preserved; changing the
application version does not relabel them as final 0.4.0 measurements.

## Gates before tagging

Freeze one clean versioned commit, then retain its A/B/C/D and full Prius runs,
source/binary/dependency hashes, complete reports and discrepancy review.
The current macOS record remains NOT_COMPARABLE to the changed physics sources;
a fresh full macOS run is required before claiming current numerical parity.
Linux/Python 3.15 smoke coverage does not establish full numerical parity.

Run the release-wheel workflow with `publish=none` on the exact candidate.
All four wheel targets, supported Python versions, bare-Linux acceptance and
installed-package walkthroughs must pass before the release decision. Owner
acceptance of the remaining limitations precedes the matching tag and protected
publication workflow. No final candidate SHA or completed release is asserted here.

[Validation](docs/VALIDATION.md) records the qualified scope and limits.
[Runtime settings](docs/RUNTIME_SETTINGS.md) documents the native environment.
Elmer is disabled by default and requires a separate runtime and development
opt-in. No hosted service, FEMM implementation or motor thermal solver is bundled.

The snapshot manifest records original source provenance, listed public patches
and current file hashes. It is an integrity check, not numerical certification
or a review of repository history. Private vulnerability reporting is enabled.
