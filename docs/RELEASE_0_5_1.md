# coilEM v0.5.1 release preparation

Prepared November 6, 2026. **The registered A-D/Prius release qualification gate
passes. Packaging and protected publication follow below.** The app and frontend identify as
0.5.1; Magneto2D remains 0.4.0. The [release notes](../RELEASE_NOTES.md) describe
the user-visible changes since the published v0.5.0.

## Candidate identity

The non-publishing annotated tag `freeze/v0.5.1-rc3` pins the clean prepared
commit and its tree. Resolve the full identities with:

```sh
git rev-parse 'freeze/v0.5.1-rc3^{commit}'
git rev-parse 'freeze/v0.5.1-rc3^{tree}'
git show --no-patch freeze/v0.5.1-rc3
```

The [candidate plan](../benchmarks/v0.5.1/candidate-plan.json) records the
version, guarded physics files, dependency and protocol hashes, and pending
gates. The freeze receipt belongs in the tag and external release evidence,
so the source does not attempt to contain its own commit hash. Keep this tag
immutable. Any later source or version change requires a new candidate ref
and rechecking the affected release gates.

The original `freeze/v0.5.1-rc1` remains at `dff4e12`; rc2 remains at `923de5f`.
The rc1 wheel rehearsal passed, but runtime CI found a test pinned to 0.5.0 and the
saved-design export stamp still at 0.5.0. The rc2 code aligns that stamp with
0.5.1 and checks the current application version across metadata and docs.
Rc3 adds the accepted source-matched qualification records and owner decisions.
Numerical source, requests, gates and measured evidence are unchanged.

The measured development source is
`a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f`, the #190 integration merge.
All 64 guarded physics files match that source byte-for-byte. This PR adds
evidence, version metadata and release documentation. Existing reports keep
their original measured commit; matching physics hashes do not replace the
final-candidate qualification checks or create new platform measurements.

The freeze tag starts with `freeze/`, so it does not trigger the `v*`
publication workflow. Only the final `v0.5.1` tag may start publication after
qualification and owner acceptance. No final release tag is created here.

## Windows evidence

The [combined Magneto2D/FEMM packet](../benchmarks/windows-v051-20261105-a4f9f4d/README.md)
retains both complete runs and the separate stopped optional repeat:

| Collection | Result | Scope |
| --- | --- | --- |
| Native A–D against reviewed protocol 1.6 references | 52 supported jobs; 46 PASS, one planned unsupported; 336/336 gates PASS | Measured integration merge on Windows |
| Overnight fresh FEMM A–D | All 46 fresh cases complete; comparison 46 PASS; 336/336 gates PASS; all 46 waveforms exactly match reviewed references | Existing same-commit native fields reused; one readiness failure successfully retried |
| Proposed cogging Phase E | 12 native cases, 17 fresh FEMM sweeps / 425 fields; baseline 9 PASS / 3 FAIL; selected refined references 10 PASS / 2 YELLOW | Original reference self-check failures retained; all five finer-reference controls pass their self-checks |

The fresh bundles remain REVIEW_REQUIRED. No gate, fixture, numerical floor
or reference default changes. The owner's separate manual review registers
the source-matched A-D/Prius platform evidence under the scope below.

## Accepted qualification and scope

The [owner decisions](../benchmarks/qualification-a4f9f4dccf2b/owner-decisions.json)
record the explicit approvals on November 6. Both platform records and both
complete Prius collections retain measured commit `a4f9f4d`. The unchanged
64-file physics identity permits metadata publication without relabeling
those fields as newly measured on the versioned code commit.

The reviewed source difference from the old reference anchor adds optional
analysis settings in `backend/models/config.py`; registered configurations,
suite, FEMM bundle and all 46 fresh repeated reference waveforms are unchanged.
The owner accepted continued reference reuse. The owner also accepted the
single near-zero macOS Prius 180-degree torque observation change from
0.0265393021 to 0.0301813299 Nm. Automatic limits and old approved baselines
remain unchanged; this is an explicit manual review of that observation.

Both platforms have 46 A-D PASS, 336 passing gates and the planned unsupported
legacy ORNL Prius. Each complete Prius collection has 17 jobs / 568 fields
and all ten software checks passing. The
[release qualification assessment](../benchmarks/v0.5.1/release-qualification.json)
passes. The [reuse-only verification](https://github.com/coilemdev/coilem/actions/runs/42270527427)
passed on Windows and macOS without new field solves.

Cogging stays experimental by owner decision. Proposed Phase E is unregistered,
its reference bundle remains REVIEW_REQUIRED and both normal-mesh YELLOW
cases stay disclosed. Full Phase E review and registration are deferred from
this release scope. No new hardware/performance qualification is claimed.

## Acceptance before publication

- [x] Bump all app/frontend/saved-design version metadata to 0.5.1.
- [x] Publish the overnight FEMM supplement beside the native results.
- [x] Preserve both earlier preparation freezes and the original field identity.
- [x] Record explicit owner reference-reuse, Prius-observation and cogging-scope approvals.
- [x] Publish source-matched Windows/macOS A-D and complete Prius records.
- [x] Pass `python -m tools.release.qualification` with the accepted field candidate.
- [x] Pass code-candidate CI, browser workflows and all four wheel targets with
  21 installed-package acceptance checks at `923de5f`.
- [ ] Pass CI and packaging checks on the qualification publication commit.
- [ ] Merge the prepared release PR, tag the accepted publication commit as
  `v0.5.1` and run the protected publication workflow.

The protected `pypi` environment controls package publication. Keep exact
workflow URLs, immutable field/source identities and original failed attempts.

Public reports redact machine-local diagnostic paths. The [projection receipt](../benchmarks/qualification-a4f9f4dccf2b/publication-projection.json) preserves original artifact hashes and verifies that numerical values and measured identities are unchanged.
