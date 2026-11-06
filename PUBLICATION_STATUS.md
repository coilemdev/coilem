# Release status

Prepared November 6, 2026: **coilEM 0.5.1 Developer Preview**, with
**Magneto2D 0.4.0**, passes the [release qualification gate](benchmarks/v0.5.1/release-qualification.json)
for registered A-D parity and Prius software checks. The
[release plan](docs/RELEASE_0_5_1.md) tracks packaging and protected publication;
the [GitHub releases](https://github.com/coilemdev/coilem/releases) record the
published packages.

## Accepted scope

The [owner's explicit decisions](benchmarks/qualification-a4f9f4dccf2b/owner-decisions.json)
accept reuse of the unchanged reviewed protocol 1.6 FEMM references, the single
near-zero macOS Prius observation difference, and an experimental cogging
scope. Automatic tolerances, original approved baselines, measured values and
reference bundle bytes are unchanged.

Both Windows and macOS retain 46 A-D PASS, one planned unsupported legacy
ORNL Prius and 336/336 gates PASS. Each Prius collection has all 17 jobs,
568 field reports and ten passing software checks. The original fields were
measured at `a4f9f4d`; all 64 guarded physics hashes match the versioned release
code. The [reuse-only workflow](https://github.com/coilemdev/coilem/actions/runs/42270527427)
successfully reverified both platforms without new field solves. Publication
metadata does not relabel the measured commit.

The macOS Prius `curve-180-16.mean_torque_Nm` observation moved from
0.0265393021 to 0.0301813299 Nm, exceeding its 0.001 Nm automatic carry limit.
The owner accepted this recorded experimental difference. All software checks
pass; no hardware or expanded performance qualification is claimed.

Cogging remains experimental. Proposed Phase E stays unregistered, its fresh
reference bundle stays REVIEW_REQUIRED and the two normal-mesh YELLOW cases
remain disclosed. The original baseline 9 PASS / 3 FAIL and selected-reference
10 PASS / 2 YELLOW comparisons, all 425 FEMM fields and five mesh controls are
retained in the [Windows packet](benchmarks/windows-v051-20261105-a4f9f4d/README.md).
Phase E acceptance/registration is deferred by the owner and is not a release
gate for this approved scope.

## Packaging and publication

The versioned code candidate `923de5f` passed all 41 active PR checks, including
four-platform wheel builds and 21 installed-package acceptance checks. The
qualification publication commit receives its own CI and packaging checks.
The preparation freeze advances to `freeze/v0.5.1-rc3`; rc1 and rc2 remain
immutable. The final matching `v0.5.1` tag uses the protected publication
workflow, including its `pypi` environment approval.

The [v0.5.0 assessment](benchmarks/v0.5.0/release-qualification.json) and all
earlier evidence remain preserved with their original measured identities.
New hardware correlation #69/#82 remains deferred; CREATOR #90 and named
presets #127 are outside this release.
