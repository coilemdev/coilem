# coilEM v0.5.8 release preparation

The draft integration PR brings `release/v0.5.8` into `main`. Application and
frontend versions are 0.5.8; bundled Magneto2D is 0.6.0 for the changed solver sources. The
[release notes](../RELEASE_NOTES.md) describe changes since published v0.5.7.

## Candidate and scope

The release branch is rebased onto main's 0.5.7 metadata update. This candidate
includes the solver/performance work and merged PRs #286–#291 (including the
Python client, guided design, release fixes and timing clarification).
Sector models (#242) and opt-in pole-pitch mesh reuse (#281) remain excluded.
Do not add feature scope while collecting release evidence.

The frozen measured candidate is `78e6f4fc8aa8695c6f3ba1f4ad4eb9f843cf54f9`.
Its [two-platform evidence](../benchmarks/qualification-78e6f4fc8aa8/README.md)
records source hashes, binary identity, dependency versions and the original
field provenance. Later CI/test and evidence commits preserve those measured
identities and must retain identical guarded physics. No freeze tag is needed
to identify the immutable measured commit.

## Required before publication

- [x] Rebase release work onto current main and retain historical metadata.
- [x] Set backend, frontend and frontend lockfile versions to 0.5.8.
- [x] Bump Magneto2D to 0.6.0 for the changed solver sources, before freezing.
- [x] Prepare release notes and disclose unresolved limitations.
- [x] Freeze the exact versioned candidate and record immutable identities.
- [x] Pass candidate CI, backend/native tests and browser workflows.
- [x] Complete registered protocol 1.10.0 A–F and separate complete Prius
  qualification on Windows x86-64 and macOS arm64. Publish matching evidence
  and pass `python -m tools.release.qualification --candidate FULL_SHA`.
- [ ] Review weekly qualification drift (#236) and candidate performance (#277).
  Preserve failed attempts and distinguish elapsed from summed worker time.
- [ ] Verify repeated Windows solve/cancel/restart and multiple/late worker
  cleanup for #234; retain platform, repetition count, logs and failures.
- [ ] Resolve #285's V-shape accuracy disposition: establish convergence or
  obtain an explicit scope decision consistent with qualification policy.
  The existing warning and mesh study alone do not close the accuracy issue.
- [x] Build all four supported platform wheels and pass installed-package
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

The final command passes with matching Windows/macOS A–F and Prius records.
It also passes with `--candidate 78e6f4fc8aa8695c6f3ba1f4ad4eb9f843cf54f9`.
No historical fields were relabeled and no numerical gates were weakened.
Rerun CI on the evidence publication commit before approving the release.

Keep the PR draft and use `[skip ci]` on preparation commits. Once the candidate
is frozen, run checks deliberately against its exact identity; draft status
alone does not suppress every workflow. Wheel rehearsal uses
`release-wheels.yml` with `publish: none`; TestPyPI and production publication
are separate steps. No workflows or publishing are triggered by this plan.
