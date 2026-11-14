# coilEM v0.5.8 release preparation

The draft integration PR brings `release/v0.5.8` into `main`. Application and
frontend versions are 0.5.8; bundled Magneto2D remains 0.5.0. The
[release notes](../RELEASE_NOTES.md) describe changes since published v0.5.7.

## Candidate and scope

The release branch is rebased onto main's 0.5.7 metadata update. This candidate
includes the solver/performance work and merged PRs #286–#291 (including the
Python client, guided design, release fixes and timing clarification).
Sector models (#242) and opt-in pole-pitch mesh reuse (#281) remain excluded.
Do not add feature scope while collecting release evidence.

Freeze the exact versioned commit before measurement. Record its full commit,
tree, physics hashes, native binary identity and dependency versions alongside
all measurements. This preparation does not create a freeze tag or assert a
measured candidate identity. Evidence publication must preserve actual field
commits; a later merge must match the accepted physics cohort.

## Required before publication

- [x] Rebase release work onto current main and retain historical metadata.
- [x] Set backend, frontend and frontend lockfile versions to 0.5.8.
- [x] Prepare release notes and disclose unresolved limitations.
- [ ] Freeze the exact versioned candidate and record immutable identities.
- [ ] Pass candidate CI, backend/native tests and browser workflows.
- [ ] Complete registered protocol 1.10.0 A–F and separate complete Prius
  qualification on Windows x86-64 and macOS arm64. Publish matching evidence
  and pass `python -m tools.release.qualification --candidate FULL_SHA`.
- [ ] Review weekly qualification drift (#236) and candidate performance (#277).
  Preserve failed attempts and distinguish elapsed from summed worker time.
- [ ] Verify repeated Windows solve/cancel/restart and multiple/late worker
  cleanup for #234; retain platform, repetition count, logs and failures.
- [ ] Resolve #285's V-shape accuracy disposition: establish convergence or
  obtain an explicit scope decision consistent with qualification policy.
  The existing warning and mesh study alone do not close the accuracy issue.
- [ ] Build all four supported platform wheels and pass installed-package
  acceptance, including startup, motor/Halbach/tutorial solves, save/reopen,
  exports, interrupt during solve and native process cleanup.
- [ ] Review and merge the release PR only after required evidence is accepted.
- [ ] Tag the accepted publication commit `v0.5.8`; run the protected release
  workflow and verify published-package acceptance before announcing it.

## Local checks and controlled workflows

```sh
python -m tools.release.version --tag v0.5.8
python -m pytest tests/test_release_tools.py tests/test_release_qualification.py
python -m tools.verify_snapshot --publication
python -m tools.release.qualification
```

The final command currently reports BLOCKED because existing platform records
bind older physics. This is a pending release gate, not a reason to rewrite
historical records or weaken tolerances.

Keep the PR draft and use `[skip ci]` on preparation commits. Once the candidate
is frozen, run checks deliberately against its exact identity; draft status
alone does not suppress every workflow. Wheel rehearsal uses
`release-wheels.yml` with `publish: none`; TestPyPI and production publication
are separate steps. No workflows or publishing are triggered by this plan.
