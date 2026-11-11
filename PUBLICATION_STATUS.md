# Release status

Prepared November 11, 2026: **coilEM 0.5.7 Developer Preview**, with
**Magneto2D 0.5.0**. The 0.5.7 release branch is integrated into `main` by
[PR #250](https://github.com/coilemdev/coilem/pull/250).

## 0.5.7 qualification and publication

The formal release qualification gate passes for the current application
physics. The [Windows](benchmarks/records/windows-x86_64.json) and
[macOS](benchmarks/records/macos-arm64.json) records bind measured candidate
`4b41f837f3d89d4fbc836be54ecafff4729491c0`, protocol 1.10.0's full A–F
selection, 68 supported cases and all 468 registered gates per platform. The
planned unsupported Prius suite row is retained; the separate 17-job Prius
collection passes all ten software checks on each platform.

The version bump and release notes change no measured physics and do not
relabel the frozen field candidate. Qualification labels retain their mesh,
rotor-layout and output restrictions; see [Validation](docs/VALIDATION.md).

Main CI and the release-candidate wheel checks passed before this version
bump. Pushing `v0.5.7` starts fresh four-platform wheel builds and installed
acceptance checks. PyPI upload is gated by the workflow's `pypi` environment;
successful PyPI install checks then attach the wheels to a draft GitHub release.
This preparation does not claim that the package or GitHub release is already
published. Follow [the release workflow](docs/RELEASING.md#publishing-a-release).

## Historical 0.5.6 preparation record

Prepared November 9, 2026: **coilEM 0.5.6 Developer Preview candidate**, with
**Magneto2D 0.5.0**. PR #229's two-layer solution reuse is integrated into
`release/v0.5.6`. The application version is bumped before the final run so
its measurements identify the actual versioned release candidate.

## 0.5.6 candidate qualification passed

The frozen versioned candidate `e9eb89e818edf9a579c20e900a9ea93a0731ad28`
passes registered A-D (protocol 1.9.0) and complete Prius software qualification
on Windows and macOS. Each platform has 46 supported cases and 336/336 gates
passing, plus 17 Prius jobs / 568 field positions with all ten software checks
passing. All 69 guarded physics hashes and before-field grader snapshots verify.
The [qualification assessment](benchmarks/qualification-e9eb89e818ed/release-qualification.json)
retains the actual field commit separately from this evidence publication.

The [scoped owner decisions](benchmarks/qualification-e9eb89e818ed/owner-decisions.json)
approve unchanged FEMM reference reuse through the registered Newton bridge and
retain the previously accepted near-zero macOS Prius observation, unchanged
within 5.34e-13 Nm. Approved anchors, gates and tolerances are unchanged.
A separate Windows Phase F diagnostic passes all ten Newton outer-rotor cases
against sealed fresh FEMM references. The earlier
[Windows report](docs/benchmarks/windows-femm-release-v056-20261109.md) retains
its pre-two-layer `8b6b394`/`11aa06b` identities and timing scope.

Outer rotors and cogging remain experimental. Phase F and Phase E are proposed
suites, and inherited LRK and cogging findings remain retained. Their diagnostics
do not expand the registered A-D/Prius acceptance scope.

## 0.5.6 publication pending

[PR #232](https://github.com/coilemdev/coilem/pull/232) integrates the release
branch into `main` after qualification and review. Wheel acceptance and TestPyPI
rehearsal precede the version tag and protected PyPI publishing approval. No
0.5.6 release tag or package publication has been performed by this preparation.

## Historical v0.5.5 status

Prepared November 8, 2026: **coilEM 0.5.5 Developer Preview**, with
**Magneto2D 0.4.0**, passes the [release qualification gate](benchmarks/v0.5.5/release-qualification.json)
for registered A-D parity and Prius software checks. The
[release notes](RELEASE_NOTES.md) describe its scope, including the new,
experimental outer-rotor motors; the
[GitHub releases](https://github.com/coilemdev/coilem/releases) record the
published packages.

### v0.5.5 accepted scope

The [owner's explicit decisions](benchmarks/qualification-34de0f4ca160/owner-decisions.json)
accept reuse of the unchanged reviewed protocol 1.6 FEMM references and the
single near-zero macOS Prius observation difference. Automatic tolerances,
original approved baselines, measured values and reference bundle bytes are
unchanged.

The reference reuse rests on a fresh Windows FEMM collection of all 46
registered cases at `34de0f4`: native versus fresh FEMM records 46 PASS and
336/336 gates, and the reference d/q self-checks pass 12/12. The outer-rotor
layout changed reference-sensitive sources behind switches that leave the
registered inner-rotor cases' inputs unchanged.

Both Windows and macOS record 46 A-D PASS, one planned unsupported legacy
ORNL Prius and 336/336 gates PASS; the native values match 0.5.1 (macOS
identical, Windows within 3×10⁻⁸ relative). Each Prius collection has all 17
jobs, 568 field reports and ten passing software checks. The fields were
measured at `34de0f4`; all 69 guarded physics hashes match the versioned
release code. Publication metadata does not relabel the measured commit.

The macOS Prius `curve-180-16.mean_torque_Nm` observation is the value the
owner accepted for 0.5.1: 0.0301813299 Nm against the approved 0.0265393021 Nm,
beyond its 0.001 Nm automatic carry limit. The owner accepted it again for
0.5.5. All software checks pass; no hardware or expanded performance
qualification is claimed.

Outer-rotor motors are experimental. The proposed outer-rotor benchmark
(Phase F, [protocol 1.8.0](benchmarks/abcd-v1.8/README.md)) passes all 10 cases
and 60/60 gates against a first FEMM collection on Windows; it is registered
once the same comparison passes on macOS.

Cogging remains experimental. Proposed Phase E stays unregistered, its fresh
reference bundle stays REVIEW_REQUIRED and the two normal-mesh YELLOW cases
remain disclosed in the 0.5.1 [Windows packet](benchmarks/windows-v051-20261105-a4f9f4d/README.md).
Phase E acceptance/registration is deferred by the owner and is not a release
gate for this approved scope.

### v0.5.5 packaging and publication

The versioned code candidate receives its own CI on the release pull request
(#218), including four-platform wheel builds and installed-package acceptance
checks. The final matching `v0.5.5` tag uses the protected publication
workflow, including its `pypi` environment approval.

The [v0.5.1](benchmarks/v0.5.1/release-qualification.json) and
[v0.5.0](benchmarks/v0.5.0/release-qualification.json) assessments and all
earlier evidence remain preserved with their original measured identities.
New hardware correlation #69/#82 remains deferred; CREATOR #90 and named
presets #127 are outside this release.
