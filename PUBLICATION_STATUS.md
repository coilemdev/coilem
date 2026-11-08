# Release status

Prepared November 8, 2026: **coilEM 0.5.5 Developer Preview**, with
**Magneto2D 0.4.0**, passes the [release qualification gate](benchmarks/v0.5.5/release-qualification.json)
for registered A-D parity and Prius software checks. The
[release notes](RELEASE_NOTES.md) describe its scope, including the new,
experimental outer-rotor motors; the
[GitHub releases](https://github.com/coilemdev/coilem/releases) record the
published packages.

## Accepted scope

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

## Packaging and publication

The versioned code candidate receives its own CI on the release pull request
(#218), including four-platform wheel builds and installed-package acceptance
checks. The final matching `v0.5.5` tag uses the protected publication
workflow, including its `pypi` environment approval.

The [v0.5.1](benchmarks/v0.5.1/release-qualification.json) and
[v0.5.0](benchmarks/v0.5.0/release-qualification.json) assessments and all
earlier evidence remain preserved with their original measured identities.
New hardware correlation #69/#82 remains deferred; CREATOR #90 and named
presets #127 are outside this release.
