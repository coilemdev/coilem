# coilEM v0.5.1 release preparation

Prepared November 6, 2026. **The candidate is frozen for qualification; the
release is not qualified or published.** The app and frontend identify as
0.5.1; Magneto2D remains 0.4.0. The [release notes](../RELEASE_NOTES.md) describe
the user-visible changes since the published v0.5.0.

## Candidate identity

The non-publishing annotated tag `freeze/v0.5.1-rc2` pins the clean prepared
commit and its tree. Resolve the full identities with:

```sh
git rev-parse 'freeze/v0.5.1-rc2^{commit}'
git rev-parse 'freeze/v0.5.1-rc2^{tree}'
git show --no-patch freeze/v0.5.1-rc2
```

The [candidate plan](../benchmarks/v0.5.1/candidate-plan.json) records the
version, guarded physics files, dependency and protocol hashes, and pending
gates. The freeze receipt belongs in the tag and external release evidence,
so the source does not attempt to contain its own commit hash. Keep this tag
immutable. Any later source or version change requires a new candidate ref
and rechecking the affected release gates.

The original `freeze/v0.5.1-rc1` remains at `dff4e12`. Its four-platform
wheel rehearsal passed, but runtime CI found a test pinned to 0.5.0 and the
saved-design export stamp still at 0.5.0. Candidate rc2 aligns that stamp with
0.5.1 and checks the current application version across metadata and docs.
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

The fresh bundles remain REVIEW_REQUIRED. No gate, fixture, numerical floor,
reference default, registered platform record or qualified output claim is
changed by this preparation.

## Acceptance before publication

- [x] Bump backend, frontend and frontend lock metadata to 0.5.1 before freezing.
- [x] Publish the complete overnight FEMM supplement beside the native results,
  with numerical gates, waveforms, provenance, retry history and checksums.
- [x] Record the preparation freeze and unchanged guarded physics hashes.
- [ ] Review Phase E references, including the original failed self-checks.
- [ ] Resolve the 8p/24s and 12p/36s distributed cogging YELLOW cases under the
  existing gates, or explicitly accept a narrower supported scope. Separate
  refined-native studies do not make the current normal-mesh requests PASS.
- [ ] Finish Phase E registration/default-command coverage after owner review.
- [ ] Complete and publish the required matching Windows/macOS A–D and Prius
  qualification with frozen inputs, raw archives and preserved failed attempts.
  Review candidate identity and permitted evidence carry-forward explicitly.
- [ ] Pass `python -m tools.release.qualification` for the accepted candidate.
  The historical v0.5.0 assessment is not a v0.5.1 release assessment.
- [ ] Pass development CI, dependency audits, snapshot/publication checks,
  installed-package/browser walkthroughs, and all four release wheel targets
  with `publish=none` at the frozen candidate. Retain exact workflow run links.
- [ ] Obtain owner release acceptance, then create the matching `v0.5.1` tag
  and use the protected publication workflow.

The existing [release benchmark workflow](../.github/workflows/release-benchmarks.yml)
accepts a full immutable candidate SHA. The
[wheel workflow](../.github/workflows/release-wheels.yml) supports a
non-publishing `publish=none` rehearsal. Successful builds alone do not pass
the numerical qualification gate. Additional field solves are scheduled
explicitly after reviewing the existing evidence and remaining scope.
